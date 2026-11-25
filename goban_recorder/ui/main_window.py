"""
ファイル名: goban_recorder/ui/main_window.py
説明: メインウィンドウ（上部メニューバー・連番途中SGF保存・終局時SGF出力・
      中途再開対応・不正判定時の直前フレーム＋1000x1000＋361交点パッチ一覧保存（D:\_Down）・
      プレビュー画像のCenter Crop対応・初期設定から本スタートへの明確な状態遷移版）
"""

from datetime import datetime
from pathlib import Path
import socket
import time
import urllib.request
import cv2
import numpy as np
from PySide6.QtCore import Qt, Slot, QTimer
from PySide6.QtGui import QImage, QPixmap, QAction
from PySide6.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QWidget,
    QStackedWidget,
    QGroupBox,
    QDoubleSpinBox,
    QSizePolicy,
    QFormLayout,
    QFileDialog,
    QInputDialog,
    QMessageBox,
)

from goban_recorder.ui.board_widget import BoardWidget
from goban_recorder.ui.game_model import GameTree, GameSettings, StartMode
from goban_recorder.network.receiver_server import ReceiverServerManager
from goban_recorder.models.game_state import GameState, BoardCoordinateStyle


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setWindowTitle("GobanRecorder - 碁盤対局自動記録")
        self.resize(1200, 850)

        self.controller = None
        self.game_tree = None
        self.game_state = GameState()

        self._is_ready = False
        self._is_initial_loaded = False
        self._is_resumed_mode = False
        self._first_move_decided = False
        self._initial_board_for_sgf = None

        # 不正判定時の診断画像保存用（直前フレーム・現在フレーム・推論行列・クールダウン管理）
        self._prev_png_bytes = None
        self._latest_png_bytes = None
        self._latest_jpeg_bytes = None
        self._latest_detected_matrix = None
        self._last_invalid_save_time = 0.0
        self._last_invalid_sig = None
        self._invalid_signal_connected = False

        # 🛡 堅牢なゲームループ制御用の変数
        self.is_processing = False         # 排他制御（再入防止フラグ）

        # 🌐 GobanViewer（Android端末）のIPアドレス保持用
        self.viewer_ip = None

        self._init_menu_bar()
        self._init_ui()

        # 通信サーバーマネージャーの初期化・バックグラウンド起動 (ポート8080)
        self.server_manager = ReceiverServerManager(port=8080)
        self.server_manager.signals.log_message.connect(self._on_server_log)
        self.server_manager.signals.data_received.connect(self._on_images_received)
        self.server_manager.signals.enable_start_btn.connect(self._on_remote_ready_received)

        if hasattr(self.server_manager.signals, 'ready_client_ip'):
            self.server_manager.signals.ready_client_ip.connect(self._on_viewer_ip_captured)

        self.server_manager.start_server()

        # GobanViewer（画像サーバー）から定期的に 1000x1000 画像を取得するタイマー (1秒間隔)
        self.snapshot_timer = QTimer(self)
        self.snapshot_timer.setInterval(1000)
        self.snapshot_timer.timeout.connect(self._fetch_snapshot_from_phone)

    def _ensure_invalid_signal_connected(self):
        if self._invalid_signal_connected:
            return
        glm = getattr(getattr(self, "controller", None), "game_loop_manager", None)
        if glm is not None and hasattr(glm, "invalid_move_detected"):
            glm.invalid_move_detected.connect(self._on_invalid_move_detected)
            self._invalid_signal_connected = True

    def _get_inference_engine(self):
        if hasattr(self, 'controller') and self.controller:
            ie = getattr(self.controller, 'inference_engine', None)
            if ie is not None:
                return ie
        if hasattr(self, '_inference_engine') and self._inference_engine is not None:
            return self._inference_engine
        return None

    def _extract_60x60_patch(self, board_bgr: np.ndarray, cx: float, cy: float, patch_size: int = 60) -> np.ndarray:
        """1000x1000盤面画像から指定中心座標 (cx, cy) の 60x60 パッチを切り出す。"""
        h, w = board_bgr.shape[:2]
        half = patch_size // 2
        x1 = int(round(cx)) - half
        y1 = int(round(cy)) - half
        x2 = x1 + patch_size
        y2 = y1 + patch_size

        pad_left = max(0, -x1)
        pad_top = max(0, -y1)
        pad_right = max(0, x2 - w)
        pad_bottom = max(0, y2 - h)

        sx1 = max(0, x1)
        sy1 = max(0, y1)
        sx2 = min(w, x2)
        sy2 = min(h, y2)

        crop = board_bgr[sy1:sy2, sx1:sx2]
        if pad_left or pad_top or pad_right or pad_bottom:
            crop = cv2.copyMakeBorder(
                crop, pad_top, pad_bottom, pad_left, pad_right, cv2.BORDER_REPLICATE
            )
        return crop

    def _save_361_patches_sheet(
        self,
        board_bgr: np.ndarray,
        detected_matrix: list,
        highlight_coords: set,
        out_dir: Path,
        ts: str,
    ):
        """361交点（19x19）の 60x60 切り出し画像一覧シートと問題座標の個別パッチを保存する。"""
        h, w = board_bgr.shape[:2]
        ie = self._get_inference_engine()
        if ie is not None and hasattr(ie, "create_arithmetic_grid"):
            grid = ie.create_arithmetic_grid(float(w), float(h))
        else:
            step_x = w / 19.5
            step_y = h / 19.5
            margin_x = 0.75 * step_x
            margin_y = 0.75 * step_y
            grid = [
                [(margin_x + c * step_x, margin_y + r * step_y) for c in range(19)]
                for r in range(19)
            ]

        cell_w, cell_h = 74, 82
        sheet = np.full((19 * cell_h, 19 * cell_w, 3), 30, dtype=np.uint8)

        for r in range(19):
            for c in range(19):
                cx, cy = grid[r][c]
                patch = self._extract_60x60_patch(board_bgr, cx, cy, patch_size=60)

                pred_val = 0
                if detected_matrix is not None and r < len(detected_matrix) and c < len(detected_matrix[r]):
                    pred_val = int(detected_matrix[r][c])

                # 枠色: 空=灰, 黒=水色, 白=黄緑, 問題座標=赤太枠
                if (r, c) in highlight_coords:
                    border_color = (0, 0, 255)
                    thickness = 3
                    patch_path = out_dir / f"patch_r{r}_c{c}_{ts}.png"
                    cv2.imwrite(str(patch_path), patch)
                elif pred_val == 1:
                    border_color = (255, 200, 0)
                    thickness = 2
                elif pred_val == 2:
                    border_color = (80, 230, 80)
                    thickness = 2
                else:
                    border_color = (90, 90, 90)
                    thickness = 1

                cell = np.full((cell_h, cell_w, 3), 24, dtype=np.uint8)
                px = (cell_w - 60) // 2
                py = 18
                cell[py:py + 60, px:px + 60] = patch
                cv2.rectangle(cell, (px - 1, py - 1), (px + 60, py + 60), border_color, thickness)

                pred_label = "E" if pred_val == 0 else ("B" if pred_val == 1 else "W")
                text = f"{r},{c}:{pred_label}"
                text_color = (120, 120, 255) if (r, c) in highlight_coords else (220, 220, 220)
                cv2.putText(cell, text, (4, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.36, text_color, 1, cv2.LINE_AA)

                y0 = r * cell_h
                x0 = c * cell_w
                sheet[y0:y0 + cell_h, x0:x0 + cell_w] = cell

        sheet_path = out_dir / f"grid361_{ts}.png"
        cv2.imwrite(str(sheet_path), sheet)
        print(f"[Debug InvalidSave] 🧩 361交点パッチ一覧シートを保存しました: {sheet_path}")

    @Slot(str, list, list)
    def _on_invalid_move_detected(self, reason: str, added_coords: list, removed_coords: list):
        """不正な石変化を検知した瞬間に、直前フレーム・現在フレーム・361交点パッチ一覧を D:\\_Down へ保存する。"""
        now = time.monotonic()
        sig = (reason, tuple(added_coords), tuple(removed_coords))
        if sig == self._last_invalid_sig and (now - self._last_invalid_save_time) < 5.0:
            return

        self._last_invalid_sig = sig
        self._last_invalid_save_time = now

        if not self._latest_png_bytes:
            print("[Debug InvalidSave] ⚠️ 保存対象の PNG 画像がありません。")
            return

        out_dir = Path("D:/_Down")
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]

        if self._prev_png_bytes:
            prev_path = out_dir / f"prev_before_invalid_{ts}.png"
            prev_path.write_bytes(self._prev_png_bytes)

        png_path = out_dir / f"invalid_{ts}.png"
        png_path.write_bytes(self._latest_png_bytes)
        print(
            f"[Debug InvalidSave] 💾 不正判定画像を保存しました: {png_path} "
            f"(理由: {reason}, 追加={added_coords}, 減少={removed_coords})"
        )

        nparr = np.frombuffer(self._latest_png_bytes, np.uint8)
        board_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if board_bgr is not None:
            highlight = set(tuple(pt) for pt in added_coords) | set(tuple(pt) for pt in removed_coords)
            self._save_361_patches_sheet(
                board_bgr=board_bgr,
                detected_matrix=self._latest_detected_matrix,
                highlight_coords=highlight,
                out_dir=out_dir,
                ts=ts,
            )

    def _init_menu_bar(self):
        menu_bar = self.menuBar()
        menu_bar.setStyleSheet("""
            QMenuBar {
                background-color: #1f382e;
                color: #ffffff;
                border-bottom: 1px solid #3d6b57;
                padding: 2px;
            }
            QMenuBar::item {
                padding: 4px 10px;
                background: transparent;
            }
            QMenuBar::item:selected {
                background-color: #356350;
            }
            QMenu {
                background-color: #233e33;
                color: #ffffff;
                border: 1px solid #4a8268;
            }
            QMenu::item:selected {
                background-color: #356350;
            }
        """)

        # 1. ファイルメニュー
        file_menu = menu_bar.addMenu("ファイル(&F)")

        act_new_game = QAction("新規対局 / リセット(&N)", self)
        act_new_game.triggered.connect(self._on_menu_new_game)
        file_menu.addAction(act_new_game)

        act_save_segment = QAction("途中棋譜を連番保存 (seg_XX.sgf)(&S)", self)
        act_save_segment.triggered.connect(self._on_menu_save_segment_sgf)
        file_menu.addAction(act_save_segment)

        file_menu.addSeparator()

        act_finish_save = QAction("対局終了・SGF保存(&E)...", self)
        act_finish_save.triggered.connect(self._on_menu_finish_and_save_sgf)
        file_menu.addAction(act_finish_save)

        file_menu.addSeparator()

        act_exit = QAction("終了(&X)", self)
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        # 2. 表示メニュー
        view_menu = menu_bar.addMenu("表示(&V)")

        act_toggle_view = QAction("カメラ映像 / 碁盤表示切替(&T)", self)
        act_toggle_view.triggered.connect(self._on_menu_toggle_view)
        view_menu.addAction(act_toggle_view)

        view_menu.addSeparator()

        act_coord_none = QAction("座標表示: なし", self)
        act_coord_none.triggered.connect(lambda: self._set_coordinate_style(BoardCoordinateStyle.NONE))
        view_menu.addAction(act_coord_none)

        act_coord_kiin = QAction("座標表示: 日本棋院方式", self)
        act_coord_kiin.triggered.connect(lambda: self._set_coordinate_style(BoardCoordinateStyle.KIIN))
        view_menu.addAction(act_coord_kiin)

        act_coord_kgs = QAction("座標表示: KGS方式", self)
        act_coord_kgs.triggered.connect(lambda: self._set_coordinate_style(BoardCoordinateStyle.KGS))
        view_menu.addAction(act_coord_kgs)

        # 3. Aboutメニュー
        about_menu = menu_bar.addMenu("About(&A)")

        act_about = QAction("GobanRecorder について(&A)", self)
        act_about.triggered.connect(self._on_menu_about)
        about_menu.addAction(act_about)

    def _on_menu_new_game(self):
        self.snapshot_timer.stop()
        self._is_ready = False
        self._is_initial_loaded = False
        self._is_resumed_mode = False
        self._first_move_decided = False
        self._initial_board_for_sgf = None
        self._prev_png_bytes = None
        self._latest_png_bytes = None
        self._latest_detected_matrix = None
        self._last_invalid_sig = None

        self.komi_spinbox.setEnabled(True)
        self.input_black_name.setEnabled(True)
        self.input_white_name.setEnabled(True)

        self.btn_ready_stop.setText("START")
        self.btn_ready_stop.setStyleSheet("""
            QPushButton {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #4CAF50, stop:1 #388E3C);
                color: white;
                font-size: 16px;
                font-weight: bold;
                border: 2px solid #2E7D32;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #66BB6A, stop:1 #43A047);
            }
            QPushButton:pressed {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #388E3C, stop:1 #2E7D32);
            }
        """)

        if self.controller and hasattr(self.controller, "reset_for_new_game"):
            self.controller.reset_for_new_game()

        self.game_state = GameState()
        empty_board = [[0 for _ in range(19)] for _ in range(19)]
        self.board_widget.board_state = empty_board
        self.board_widget.last_move = None
        self.board_widget.update()

        self.label_mode_status.setText("対局方式: 自動判別待機中...")
        self.label_turn_info.setText("手数: 0手目  |  次手番: -")
        self.label_captures.setText("アゲ石: 黒: 0個 | 白: 0個")
        self.view_stack.setCurrentIndex(0)
        print("[UI] ✔ 新規対局にリセットしました。")

    def _on_menu_save_segment_sgf(self):
        """途中棋譜を決められたフォルダに seg_01.sgf, seg_02.sgf ... の連番で保存する。"""
        if self.controller and hasattr(self.controller, "save_segment_sgf"):
            saved_path = self.controller.save_segment_sgf()
            QMessageBox.information(self, "途中棋譜保存", f"途中棋譜を保存しました:\n{saved_path}")
            return

        from goban_recorder.export.sgf_writer import SgfWriter
        writer = SgfWriter()
        board_data = (
            self._initial_board_for_sgf
            if self._initial_board_for_sgf is not None
            else self.board_widget.board_state
        )
        sgf_str = writer.generate_sgf_string(
            board_layout=board_data,
            komi=self.komi_spinbox.value(),
            black_player=self.input_black_name.text(),
            white_player=self.input_white_name.text(),
        )
        saved_path = writer.save_next_segment_sgf(sgf_str)
        QMessageBox.information(self, "途中棋譜保存", f"途中棋譜を保存しました:\n{saved_path}")

    def _on_menu_finish_and_save_sgf(self):
        """
        対局終了処理（投了・結果選択＋ユーザー指定保存先へのSGF出力）。
        終了操作時には十分な間が空くため、pending 確認ダイアログは行わない。
        """
        result_options = [
            "投了: 黒中押勝 (B+R)",
            "投了: 白中押勝 (W+R)",
            "結果指定なし / 中断 (Void / Unknown)",
        ]
        choice, ok = QInputDialog.getItem(
            self,
            "対局終了・結果選択",
            "終局理由 / 結果を選択してください:",
            result_options,
            0,
            False,
        )
        if not ok:
            return

        if choice.startswith("投了: 黒"):
            sgf_result = "B+R"
        elif choice.startswith("投了: 白"):
            sgf_result = "W+R"
        else:
            sgf_result = ""

        default_name = f"game_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sgf"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "最終SGFファイルの保存先を指定",
            default_name,
            "SGF Files (*.sgf);;All Files (*)",
        )
        if not file_path:
            return

        if self.controller and hasattr(self.controller, "save_final_sgf"):
            saved_path = self.controller.save_final_sgf(file_path, result=sgf_result or None)
        else:
            from goban_recorder.export.sgf_writer import SgfWriter
            writer = SgfWriter()
            board_data = (
                self._initial_board_for_sgf
                if self._initial_board_for_sgf is not None
                else self.board_widget.board_state
            )
            sgf_str = writer.generate_sgf_string(
                board_layout=board_data,
                komi=self.komi_spinbox.value(),
                black_player=self.input_black_name.text(),
                white_player=self.input_white_name.text(),
                result=sgf_result or None,
            )
            saved_path = writer.save_sgf_to_path(sgf_str, file_path)

        if self._is_ready:
            self._stop_recording_session()

        QMessageBox.information(self, "SGF保存完了", f"最終SGFファイルを保存しました:\n{saved_path}")

    def _on_menu_toggle_view(self):
        next_idx = 1 if self.view_stack.currentIndex() == 0 else 0
        self.view_stack.setCurrentIndex(next_idx)

    def _set_coordinate_style(self, style: BoardCoordinateStyle):
        if hasattr(self.board_widget, "coordinate_style"):
            self.board_widget.coordinate_style = style
            self.board_widget.update()
        elif hasattr(self.board_widget, "set_coordinate_style"):
            self.board_widget.set_coordinate_style(style)
            self.board_widget.update()

    def _on_menu_about(self):
        QMessageBox.about(
            self,
            "About GobanRecorder",
            "GobanRecorder\n"
            "PC (Windows / PySide6) 碁盤対局自動記録アプリケーション\n"
            "19x19 盤面追跡・SGF 出力対応",
        )

    def _init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)

        main_widget.setStyleSheet("""
            QWidget {
                background-color: #2b4c3f;
                color: #ffffff;
                font-family: 'Meiryo', 'Segoe UI', sans-serif;
            }
            QGroupBox {
                border: 2px solid #3d6b57;
                border-radius: 6px;
                margin-top: 10px;
                font-weight: bold;
                background-color: #233e33;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px;
                color: #d1f7e2;
            }
            QLineEdit, QDoubleSpinBox {
                background-color: #1a2e25;
                border: 1px solid #4a8268;
                border-radius: 4px;
                padding: 4px;
                color: #ffffff;
            }
            QPushButton {
                background-color: #356350;
                border: 1px solid #529679;
                border-radius: 4px;
                padding: 6px;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #427c64;
            }
            QPushButton:pressed {
                background-color: #284f3e;
            }
        """)

        root_layout = QVBoxLayout(main_widget)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        # ----------------------------------------------------------------------
        # 1. 上部コントロールバー（PCのIPアドレスを常時明示表示）
        # ----------------------------------------------------------------------
        top_bar_layout = QHBoxLayout()

        local_ip = self._get_local_ip()
        ip_display_text = f"💡 GobanViewer設定用アドレス: http://{local_ip}:8080"
        self.label_pc_ip = QLabel(ip_display_text)
        self.label_pc_ip.setStyleSheet("font-size: 15px; font-weight: bold; color: #a3ffce; padding: 4px;")
        top_bar_layout.addWidget(self.label_pc_ip)

        top_bar_layout.addStretch()

        # 右上の大型立体 START ⇄ Stop ボタン
        self.btn_ready_stop = QPushButton("START")
        self.btn_ready_stop.setFixedSize(160, 45)
        self.btn_ready_stop.setStyleSheet("""
            QPushButton {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #4CAF50, stop:1 #388E3C);
                color: white;
                font-size: 16px;
                font-weight: bold;
                border: 2px solid #2E7D32;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #66BB6A, stop:1 #43A047);
            }
            QPushButton:pressed {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #388E3C, stop:1 #2E7D32);
            }
        """)
        self.btn_ready_stop.clicked.connect(self._on_ready_stop_clicked)
        top_bar_layout.addWidget(self.btn_ready_stop)

        root_layout.addLayout(top_bar_layout)

        # ----------------------------------------------------------------------
        # 2. 左右2カラム構造
        # ----------------------------------------------------------------------
        content_layout = QHBoxLayout()
        content_layout.setSpacing(15)

        # --- 左カラム ---
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.view_stack = QStackedWidget()
        self.view_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.view_stack.setMinimumSize(600, 600)

        self.video_label = QLabel("GobanViewerからの接続待機中...")
        self.video_label.setStyleSheet(
            "background-color: #11221b; color: #a0c2b2; font-size: 18px; border: 2px solid #3d6b57; border-radius: 6px;"
        )
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view_stack.addWidget(self.video_label)

        self.board_widget = BoardWidget()
        self.board_widget.intersection_clicked.connect(self._on_board_clicked)
        self.view_stack.addWidget(self.board_widget)

        self.view_stack.setCurrentIndex(0)
        left_layout.addWidget(self.view_stack)

        content_layout.addLayout(left_layout, stretch=3)

        # --- 右カラム ---
        right_container = QWidget()
        right_container.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        right_container.setFixedWidth(380)
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        # 1. 対局方式（★フォントを大きめ・太字に強化）
        mode_group_box = QGroupBox("対局方式 (自動判別)")
        mode_layout = QVBoxLayout(mode_group_box)
        self.label_mode_status = QLabel("対局方式: 自動判別待機中...")
        self.label_mode_status.setStyleSheet("font-size: 15px; font-weight: bold; color: #a3ffce; padding: 4px;")
        mode_layout.addWidget(self.label_mode_status)
        right_layout.addWidget(mode_group_box)

        # 2. 対局設定
        settings_group_box = QGroupBox("対局設定")
        settings_form = QFormLayout(settings_group_box)
        settings_form.setContentsMargins(8, 8, 8, 8)

        self.input_black_name = QLineEdit("黒番")
        self.input_white_name = QLineEdit("白番")

        self.komi_spinbox = QDoubleSpinBox()
        self.komi_spinbox.setRange(-10.0, 20.0)
        self.komi_spinbox.setSingleStep(0.5)
        self.komi_spinbox.setValue(6.5)
        self.komi_spinbox.setDecimals(1)
        self.komi_spinbox.setMinimumWidth(80)

        settings_form.addRow("黒番プレイヤー:", self.input_black_name)
        settings_form.addRow("白番プレイヤー:", self.input_white_name)
        settings_form.addRow("コミ:", self.komi_spinbox)

        right_layout.addWidget(settings_group_box)

        # 3. 対局ステータス（★手数・次手番のフォントを16pxに大型化し最も目立たせる）
        status_group_box = QGroupBox("対局ステータス")
        status_layout = QVBoxLayout(status_group_box)
        status_layout.setContentsMargins(8, 8, 8, 8)
        status_layout.setSpacing(6)

        self.label_turn_info = QLabel("手数: 0手目  |  次手番: -")
        self.label_turn_info.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffd54f; padding: 3px;")

        self.label_captures = QLabel("アゲ石: 黒: 0個 | 白: 0個")
        self.label_captures.setStyleSheet("font-size: 13px; padding: 2px;")

        self.label_elapsed_time = QLabel("経過時間: 00:00:00")
        self.label_elapsed_time.setStyleSheet("font-size: 13px; padding: 2px;")

        status_layout.addWidget(self.label_turn_info)
        status_layout.addWidget(self.label_captures)
        status_layout.addWidget(self.label_elapsed_time)

        right_layout.addWidget(status_group_box)

        # 4. 現実の碁盤プレビュー
        live_layout = QVBoxLayout()
        live_layout.setContentsMargins(0, 0, 0, 0)

        self.live_preview_label = QLabel("映像待機中...")
        self.live_preview_label.setFixedSize(364, 364)
        self.live_preview_label.setStyleSheet(
            "background-color: #11221b; color: #a0c2b2; font-size: 14px; border: 2px solid #3d6b57; border-radius: 6px;"
        )
        self.live_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        live_layout.addWidget(self.live_preview_label, alignment=Qt.AlignmentFlag.AlignCenter)

        right_layout.addLayout(live_layout)
        right_layout.addStretch()

        content_layout.addWidget(right_container, stretch=1)
        root_layout.addLayout(content_layout)

    def set_controller(self, controller):
        self.controller = controller
        self._ensure_invalid_signal_connected()

    def _get_local_ip(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except Exception:
            try:
                return socket.gethostbyname(socket.gethostname())
            except Exception:
                return "127.0.0.1"

    @Slot(str)
    def _on_viewer_ip_captured(self, ip_str: str):
        self.viewer_ip = ip_str
        print(f"[UI] 💡 GobanViewerのIPアドレスを自動検出しました: {ip_str}")

    @Slot(bool)
    def _on_remote_ready_received(self, enabled: bool):
        print("[UI] GobanViewerからの Ready 信号を検知しました。")
        if not self._is_ready:
            self.btn_ready_stop.setStyleSheet("""
                QPushButton {
                    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FF5722, stop:1 #E64A19);
                    color: white;
                    font-size: 16px;
                    font-weight: bold;
                    border: 2px solid #D84315;
                    border-radius: 6px;
                }
                QPushButton:hover {
                    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FF7043, stop:1 #F4511E);
                }
            """)
            self.btn_ready_stop.setToolTip("GobanViewer側の準備が完了しました！クリックして対局記録を開始できます")

    def _stop_recording_session(self):
        self._is_ready = False
        self._is_initial_loaded = False
        self.snapshot_timer.stop()

        self.komi_spinbox.setEnabled(True)
        self.input_black_name.setEnabled(True)
        self.input_white_name.setEnabled(True)

        self.btn_ready_stop.setText("START")
        self.btn_ready_stop.setStyleSheet("""
            QPushButton {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #4CAF50, stop:1 #388E3C);
                color: white;
                font-size: 16px;
                font-weight: bold;
                border: 2px solid #2E7D32;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #66BB6A, stop:1 #43A047);
            }
            QPushButton:pressed {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #388E3C, stop:1 #2E7D32);
            }
        """)

        if self.controller and hasattr(self.controller, 'cleanup'):
            self.controller.cleanup()

        print("[UI] ⏹ 記録を停止しました。")

    def _on_ready_stop_clicked(self):
        if not self._is_ready:
            self._ensure_invalid_signal_connected()
            self._is_ready = True
            self._is_initial_loaded = False
            self._is_resumed_mode = False
            self._first_move_decided = False
            self._prev_png_bytes = None
            self._latest_png_bytes = None
            self._latest_detected_matrix = None
            self._last_invalid_sig = None
            self.komi_spinbox.setEnabled(False)
            self.input_black_name.setEnabled(False)
            self.input_white_name.setEnabled(False)

            self.btn_ready_stop.setText("Stop")
            self.btn_ready_stop.setStyleSheet("""
                QPushButton {
                    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #F44336, stop:1 #C62828);
                    color: white;
                    font-size: 16px;
                    font-weight: bold;
                    border: 2px solid #B71C1C;
                    border-radius: 6px;
                }
                QPushButton:hover {
                    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #E57373, stop:1 #D32F2F);
                }
            """)

            game_settings = GameSettings(
                start_mode=StartMode.NORMAL,
                black_player=self.input_black_name.text(),
                white_player=self.input_white_name.text(),
                komi=self.komi_spinbox.value(),
            )

            self.game_tree = GameTree(game_settings)

            self.snapshot_timer.start()
            print("[UI] ✔ スタートしました。初期盤面の自動設定フェーズを開始します。")

        else:
            self._stop_recording_session()

    def _fetch_snapshot_from_phone(self):
        if self.is_processing:
            return

        target_urls = []
        if self.viewer_ip:
            target_urls.append(f"http://{self.viewer_ip}:8080/snapshot")

        target_urls.extend([
            "http://127.0.0.1:8080/snapshot",
            f"http://{self._get_local_ip()}:8080/snapshot",
        ])

        for url in target_urls:
            try:
                self.is_processing = True
                req = urllib.request.Request(url, headers={'User-Agent': 'GobanRecorder'})
                with urllib.request.urlopen(req, timeout=0.8) as response:
                    png_data = response.read()
                    if png_data:
                        jpeg_data = None
                        try:
                            preview_url = url.replace("/snapshot", "/preview")
                            req_prev = urllib.request.Request(preview_url, headers={'User-Agent': 'GobanRecorder'})
                            with urllib.request.urlopen(req_prev, timeout=1.5) as resp_prev:
                                jpeg_data = resp_prev.read()
                        except Exception as e:
                            print(f"[Debug] ⚠️ プレビュー画像取得失敗: {e} (URL: {preview_url})")

                        self._on_images_received(jpeg_data, png_data)
                        break
            except Exception:
                pass
            finally:
                self.is_processing = False
            break

    def _on_board_clicked(self, col: int, row: int):
        if self.view_stack.currentIndex() != 1:
            print("[Test] 対局記録中（ボード表示中）のみクリック入力が可能です。")
            return

        current_color = self.game_state.turn
        success = self.game_state.play_move(col, row, current_color)
        if success:
            self.board_widget.board_state = self.game_state.board.tolist()
            self.board_widget.last_move = (col, row)
            self.board_widget.update()

    def switch_to_board_view(self):
        self.view_stack.setCurrentIndex(1)

    def update_game_status(self, move_count: int, next_color_char: str, black_captures: int, white_captures: int):
        """着手確定時に手数・次手番・アゲハマ表示を更新する。"""
        if next_color_char == "B":
            turn_str = "黒番 (●)"
        elif next_color_char == "W":
            turn_str = "白番 (○)"
        else:
            turn_str = "-"
        self.label_turn_info.setText(f"手数: {move_count}手目  |  次手番: {turn_str}")
        self.label_captures.setText(f"アゲ石: 黒: {black_captures}個 | 白: {white_captures}個")

    @Slot(str)
    def _on_server_log(self, message: str):
        print(f"[Server Log] {message}")

    @Slot(bytes, bytes)
    def _on_images_received(self, jpeg_data, png_data):
        if png_data:
            self._prev_png_bytes = self._latest_png_bytes
            self._latest_png_bytes = png_data
        if jpeg_data:
            self._latest_jpeg_bytes = jpeg_data

        # ★ 全フレーム連番保存（received_images/）は停止し、不正検知時のみ D:\_Down へ保存する

        if jpeg_data:
            q_img = QImage.fromData(jpeg_data)
            if not q_img.isNull():
                pixmap = QPixmap.fromImage(q_img)
                target_size = self.live_preview_label.size()

                # ★ Jetpack Compose の ContentScale.Crop と同様の Center Crop 処理
                scaled_pixmap = pixmap.scaled(
                    target_size,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                x = max(0, (scaled_pixmap.width() - target_size.width()) // 2)
                y = max(0, (scaled_pixmap.height() - target_size.height()) // 2)
                cropped_pixmap = scaled_pixmap.copy(x, y, target_size.width(), target_size.height())

                self.live_preview_label.setPixmap(cropped_pixmap)

        if not png_data or not self._is_ready:
            return

        nparr = np.frombuffer(png_data, np.uint8)
        rectified_board = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if rectified_board is None:
            print("[Debug] ⚠️ rectified_board のデコードに失敗しました。")
            return

        try:
            inference_engine = self._get_inference_engine()
            if inference_engine is None:
                from goban_recorder.pipeline.inference_engine import InferenceEngine
                self._inference_engine = InferenceEngine()
                self._inference_engine.load_models()
                inference_engine = self._inference_engine

            if inference_engine is None:
                return

            # 1000x1000正方形画像から361交点を推論
            h, w = rectified_board.shape[:2]
            geometry_grid = inference_engine.create_arithmetic_grid(float(w), float(h))
            detected_matrix, _ = inference_engine.predict_stones(rectified_board, geometry_grid)

            if detected_matrix is None:
                return

            current_matrix = []
            black_stone_count = 0
            white_stone_count = 0

            for row in detected_matrix:
                row_list = []
                for stone in row:
                    val = int(stone.value) if hasattr(stone, "value") else int(stone)
                    if val == 1:
                        black_stone_count += 1
                    elif val == 2:
                        white_stone_count += 1
                    row_list.append(val)
                current_matrix.append(row_list)

            self._latest_detected_matrix = [r[:] for r in current_matrix]

            # ==================================================================
            # 【分岐 1】初期条件の自動設定フェーズ
            # ==================================================================
            if not self._is_initial_loaded:
                is_handicap = (white_stone_count == 0 and black_stone_count >= 2)
                is_resume = (black_stone_count > 0 or white_stone_count > 0) and not is_handicap

                if is_handicap:
                    mode_text = f"置き碁 ({black_stone_count}子)"
                    self.label_mode_status.setText(f"対局方式: {mode_text}")
                    self.komi_spinbox.setValue(0.0)
                    print(f"[UI] 🌟 置き碁を自動検知しました（黒石: {black_stone_count}個）。コミを0.0に設定しました。")
                elif is_resume:
                    mode_text = "対局中途再開 (Resume)"
                    self.label_mode_status.setText(f"対局方式: {mode_text}")
                    print("[UI] 🌟 対局中途再開を自動検知しました。")
                else:
                    mode_text = "互先 (Even Game)"
                    self.label_mode_status.setText(f"対局方式: {mode_text}")
                    print("[UI] 🌟 互先（Even）として初期化します。")

                self.switch_to_board_view()

                if is_handicap:
                    initial_next_turn = 2
                    self.label_turn_info.setText("手数: 0手目  |  次手番: 白番 (○)")
                elif is_resume:
                    initial_next_turn = 1
                    self.label_turn_info.setText("手数: 0手目  |  次手番: 初手待ち")
                else:
                    initial_next_turn = 1
                    self.label_turn_info.setText("手数: 0手目  |  次手番: 黒番 (●)")

                self._is_resumed_mode = is_resume
                self._first_move_decided = not is_resume
                self._initial_board_for_sgf = [r[:] for r in current_matrix]

                mode = StartMode.RESUME if is_resume else StartMode.NORMAL
                active_settings = GameSettings(
                    start_mode=mode,
                    black_player=self.input_black_name.text(),
                    white_player=self.input_white_name.text(),
                    komi=self.komi_spinbox.value(),
                )

                if hasattr(self, 'controller') and self.controller:
                    self.controller.confirm_setup_and_start_recording(
                        game_settings=active_settings,
                        initial_board=current_matrix,
                        next_turn_color=initial_next_turn,
                    )
                    self._ensure_invalid_signal_connected()
                else:
                    self.game_tree = GameTree(active_settings, initial_board=current_matrix)
                    self.game_state.board = np.array(current_matrix, dtype=int)
                    if hasattr(self, 'board_widget'):
                        self.board_widget.board_state = current_matrix
                        self.board_widget.update()

                self._is_initial_loaded = True
                print(
                    f"[Bridge] ✔ 初期設定完了 (黒:{black_stone_count}, 白:{white_stone_count}) → 本スタートへ移行。"
                )

            # ==================================================================
            # 【分岐 2】本スタート後の着手追従・Game Loop フェーズ
            # ==================================================================
            else:
                self._ensure_invalid_signal_connected()
                game_loop_manager = None
                if hasattr(self, 'controller') and self.controller:
                    game_loop_manager = getattr(self.controller, 'game_loop_manager', None)

                if game_loop_manager and self._is_resumed_mode and not self._first_move_decided:
                    base = game_loop_manager.current_board_state
                    added_stones = []
                    for r_idx in range(19):
                        for c_idx in range(19):
                            if base[r_idx][c_idx] == 0 and current_matrix[r_idx][c_idx] in (1, 2):
                                added_stones.append((r_idx, c_idx, current_matrix[r_idx][c_idx]))
                    if len(added_stones) == 1:
                        _, _, first_col = added_stones[0]
                        self._first_move_decided = True
                        if hasattr(self, 'controller') and self.controller and hasattr(self.controller, 'sync_resumed_first_move_turn'):
                            self.controller.sync_resumed_first_move_turn(first_col)
                        else:
                            next_col = 2 if first_col == 1 else 1
                            game_loop_manager.set_next_turn_color(next_col, reason="中途再開 初手確定")
                        first_label = "黒番 (●)" if first_col == 1 else "白番 (○)"
                        print(f"[Bridge] ✔ 中途再開の最初の手番を {first_label} に確定しました。")

                is_running = getattr(game_loop_manager, 'is_running', None)
                print(
                    f"[Debug Loop] glm={game_loop_manager is not None}, is_running={is_running}, "
                    f"黒:{black_stone_count}, 白:{white_stone_count}"
                )

                if game_loop_manager and is_running:
                    game_loop_manager.process_board_matrix(current_matrix)

        except Exception as e:
            print(f"[Bridge] ⚠️ 例外発生: {e}")

    def closeEvent(self, event):
        if hasattr(self, 'controller') and self.controller:
            self.controller.cleanup()
        event.accept()
        