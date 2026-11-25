"""
ファイル名: goban_recorder/controllers/app_controller.py
説明: 初期石配置の確定とGameLoopManagerへの基準盤面引き渡し、着手確定時のUI反映、
      途中連番SGF保存、および終局時SGF出力を行うメインコントローラー
"""

from pathlib import Path
from typing import List, Optional
import cv2
import numpy as np
from PySide6.QtCore import QObject, Slot

from goban_recorder.camera.camera_service import CameraService
from goban_recorder.pipeline.inference_engine import InferenceEngine
from goban_recorder.processing.game_loop_manager import GameLoopManager
from goban_recorder.processing.initial_state_analyzer import InitialStateAnalyzer
from goban_recorder.ui.game_model import GameTree, GameSettings, StartMode
from goban_recorder.export.sgf_writer import SgfWriter


class AppController(QObject):
    """GobanRecorderのメインコントローラー"""

    def __init__(self, main_window):
        super().__init__(parent=main_window)
        self.main_window = main_window
        self.frame_count = 0

        self.camera_service = CameraService(parent=self)
        self.camera_service.frame_received.connect(self.handle_new_frame)

        self.game_settings = GameSettings()
        self.game_tree = GameTree(self.game_settings)

        print("[AppController] 推論モデルをロード中...")
        self.inference_engine = InferenceEngine()
        if self.inference_engine.load_models():
            print("[AppController] ✔ YOLOおよびTFLiteモデルのロードに成功しました。")
        else:
            print("[AppController] ⚠️ モデルのロードに失敗しました。")

        self.game_loop_manager = GameLoopManager(self.game_tree, parent=self)
        self.game_loop_manager.inference_engine = self.inference_engine

        self.game_loop_manager.state_changed.connect(self._handle_state_changed)
        self.game_loop_manager.warning_triggered.connect(self._handle_warning)
        self.game_loop_manager.move_confirmed.connect(self._handle_move_confirmed)

        self.initial_analyzer = InitialStateAnalyzer()
        self.sgf_writer = SgfWriter()

        self.last_corners = None
        self.is_recording = False
        self.latest_frame = None

        # 中途再開（途中配石からの開始）管理用
        self.is_resumed_game = False
        self.initial_board_snapshot: Optional[List[List[int]]] = None
        self.first_move_turn_decided = False

    def start_app(self, camera_source):
        print(f"[AppController] カメラ接続を開始: {camera_source}")
        self.last_corners = None
        self.is_recording = False
        self.latest_frame = None
        self.camera_service.set_source_and_start(camera_source)

    def stop_camera(self):
        if self.camera_service:
            self.camera_service.stop()

    @Slot(object)
    def handle_new_frame(self, frame_bgr):
        if frame_bgr is None:
            return

        self.frame_count += 1
        self.latest_frame = frame_bgr.copy()

        if self.is_recording:
            try:
                self.game_loop_manager.process_frame(frame_bgr, self.last_corners)
            except Exception as e:
                print(f"[AppController] メインループ処理例外: {e}")

    def confirm_setup_and_start_recording(self, game_settings=None, initial_board=None, next_turn_color: int = 1):
        """
        初期設定を確定し、確定済み基準盤面をセットして Game Loop（本スタート）を開始する。
        GobanViewer からの HTTP 受信モードでは initial_board が直接渡される。
        中途再開（途中配石からの開始）の場合は、最初に着手された石の色から手番を確定する。
        """
        if game_settings:
            self.game_settings = game_settings

        if initial_board is not None:
            board_matrix = [row[:] for row in initial_board]
        elif self.latest_frame is not None:
            board_matrix = [[0] * 19 for _ in range(19)]
            try:
                h, w = self.latest_frame.shape[:2]
                grid = self.inference_engine.create_arithmetic_grid(float(w), float(h))
                board_layout, _ = self.inference_engine.predict_stones(self.latest_frame, grid)
                if board_layout is not None:
                    board_matrix = [
                        [int(stone.value) if hasattr(stone, "value") else int(stone) for stone in row]
                        for row in board_layout
                    ]
            except Exception as e:
                print(f"[AppController] CNN初期石解析例外: {e}")
        else:
            print("[AppController] 初回スナップショット受信による自動初期設定を待機します...")
            return

        self.initial_board_snapshot = [row[:] for row in board_matrix]

        start_mode = getattr(self.game_settings, "start_mode", StartMode.NORMAL)
        self.is_resumed_game = (start_mode == StartMode.RESUME)

        if self.is_resumed_game:
            self.first_move_turn_decided = False
            effective_turn = next_turn_color
        else:
            self.first_move_turn_decided = True
            effective_turn = next_turn_color

        if isinstance(self.game_settings, GameSettings):
            self.game_tree = GameTree(self.game_settings, initial_board=board_matrix)
        else:
            self.game_tree = GameTree(GameSettings(), initial_board=board_matrix)

        self.game_loop_manager.game_tree = self.game_tree
        self.game_loop_manager.initialize_board(board_matrix, next_turn_color=effective_turn)

        self._update_left_board_widget(board_matrix)

        self.is_recording = True
        self.game_loop_manager.start_loop()
        if self.is_resumed_game:
            print("[AppController] ★中途再開モードで開始しました。最初に着手された石の色から手番を確定します。")
        else:
            print("[AppController] ★初期化完了：対局の自動記録（本スタート）を開始しました！")

    def sync_resumed_first_move_turn(self, first_color: int):
        """
        中途再開時に最初に着手された石の色（1:黒, 2:白）から最初の手番を確定し、
        次手番を相手番（3 - first_color）に合わせる。
        """
        if self.is_resumed_game and not self.first_move_turn_decided:
            self.first_move_turn_decided = True
            self.game_loop_manager.next_turn_color = 3 - first_color
            turn_name = "黒番" if first_color == 1 else "白番"
            print(f"[AppController] ✔ 中途再開の最初の手番を {turn_name} として確定しました。")

    def _update_left_board_widget(self, board_matrix):
        try:
            board_widget = getattr(self.main_window, "board_widget", None)
            if board_widget is not None:
                board_widget.board_state = [row[:] for row in board_matrix]
                board_widget.update()
        except Exception as e:
            print(f"[AppController] ⚠️ 左側碁盤描画エラー: {e}")

    def _handle_state_changed(self, state_msg: str):
        pass

    def _handle_warning(self, warn_msg: str):
        pass

    @Slot(int, int, str, int, int)
    def _handle_move_confirmed(self, row, col, color_char, move_num, captured_count):
        if self.game_tree is not None:
            self.game_tree.add_move(color=color_char, coord=(row, col))

        latest_board = self.game_loop_manager.current_board_state
        self._update_left_board_widget(latest_board)

        board_widget = getattr(self.main_window, "board_widget", None)
        if board_widget is not None:
            board_widget.last_move = (col, row)
            board_widget.update()

        next_color = "W" if color_char == "B" else "B"
        b_caps = self.game_loop_manager.black_captures
        w_caps = self.game_loop_manager.white_captures

        if hasattr(self.main_window, "update_game_status"):
            self.main_window.update_game_status(move_num, next_color, b_caps, w_caps)

    def build_sgf_content(self, result: Optional[str] = None) -> str:
        """現在の盤面・着手履歴・対局設定からSGF文字列を生成する。"""
        init_board = (
            self.initial_board_snapshot
            if self.initial_board_snapshot is not None
            else self.game_loop_manager.current_board_state
        )

        black_name = getattr(self.game_settings, "black_player", "黒番")
        white_name = getattr(self.game_settings, "white_player", "白番")
        komi = getattr(self.game_settings, "komi", 6.5)

        start_mode = getattr(self.game_settings, "start_mode", StartMode.NORMAL)
        handicap = 0
        if start_mode == StartMode.NORMAL and init_board is not None:
            b_cnt = sum(1 for r in init_board for v in r if (v.value if hasattr(v, "value") else v) == 1)
            w_cnt = sum(1 for r in init_board for v in r if (v.value if hasattr(v, "value") else v) == 2)
            if w_cnt == 0 and b_cnt >= 2:
                handicap = b_cnt

        next_char = "B" if self.game_loop_manager.next_turn_color == 1 else "W"
        moves = [dict(m) for m in self.game_loop_manager.move_history]
        print(f"[AppController] SGF生成: 初期盤面あり={init_board is not None}, 確定着手数={len(moves)}, 結果={result}")

        return self.sgf_writer.generate_sgf_string(
            board_layout=init_board,
            board_size=19,
            komi=komi,
            handicap=handicap,
            black_player=black_name,
            white_player=white_name,
            next_player=next_char,
            moves=moves,
            result=result,
            include_initial_stones=True,
        )

    def save_segment_sgf(self) -> Path:
        """途中棋譜を決められたフォルダに seg_01.sgf, seg_02.sgf ... の連番で保存する。"""
        sgf_text = self.build_sgf_content(result=None)
        return self.sgf_writer.save_next_segment_sgf(sgf_text)

    def save_final_sgf(self, file_path: str | Path, result: Optional[str] = None) -> Path:
        """終局時の最終SGFファイルをユーザーが指定したパスへ保存する。"""
        sgf_text = self.build_sgf_content(result=result)
        return self.sgf_writer.save_sgf_to_path(sgf_text, file_path)

    def reset_for_new_game(self):
        """新規対局に向けてコントローラーの状態を初期化する。"""
        self.is_recording = False
        self.last_corners = None
        self.is_resumed_game = False
        self.initial_board_snapshot = None
        self.first_move_turn_decided = False
        if self.game_loop_manager:
            self.game_loop_manager.stop_loop()
            self.game_loop_manager.reset_state()
        self.game_settings = GameSettings()
        self.game_tree = GameTree(self.game_settings)
        self.game_loop_manager.game_tree = self.game_tree

    def cleanup(self):
        self.is_recording = False
        if self.game_loop_manager:
            self.game_loop_manager.stop_loop()
            self.game_loop_manager.reset_state()
        self.stop_camera()
        