"""
ファイル名: goban_recorder/pipeline/inference_engine.py
説明: 1000x1000の正方形画像を受け取り、算術グリッド生成およびTFLite版石検出器による推論を実行する推論エンジン
"""

from pathlib import Path
import numpy as np
import cv2
from datetime import datetime
import tensorflow as tf

from goban_recorder.pipeline.cnn_stone_detector import CnnStoneDetector
from goban_recorder.config import DebugConfig  # ★ config.py からデバッグ設定をインポート


class InferenceEngine:
    def __init__(
        self,
        cnn_model_path: str = "assets/models/goban_stone_model.tflite"
    ):
        self.cnn_path = Path(cnn_model_path)
        self.cnn_stone_detector = CnnStoneDetector()
        self._rectified_seq = 0

    def load_models(self) -> bool:
        try:
            if not self.cnn_path.exists():
                print(f"[InferenceEngine] ⚠️ TFLiteモデルファイルが見つかりません: {self.cnn_path}")
                return False

            # TFLite版石検出器の初期化
            self.cnn_stone_detector = CnnStoneDetector(model_path=str(self.cnn_path))

            if self.cnn_stone_detector.interpreter is None:
                print(f"[InferenceEngine] ⚠️ TFLiteモデルのインタープリター初期化に失敗しました: {self.cnn_path}")
                return False

            print(f"[InferenceEngine] ✔ TFLite石検出モデルのロードに成功しました。")
            return True

        except Exception as e:
            print(f"[InferenceEngine] モデルロードエラー: {e}")
            return False

    def create_arithmetic_grid(self, width: float, height: float) -> list[list[tuple[int, int]]]:
        """1000x1000の盤面サイズに対応する19x19の交点グリッド座標を生成"""
        step_x = width / 19.0
        step_y = height / 19.0
        center_index = 9.0
        base_center_x = (center_index + 0.5) * step_x
        base_center_y = (center_index + 0.5) * step_y

        geometry_grid = []
        for r in range(19):
            row_pts = []
            for c in range(19):
                x = int(base_center_x + (c - center_index) * step_x)
                y = int(base_center_y + (r - center_index) * step_y)
                row_pts.append((x, y))
            geometry_grid.append(row_pts)
        return geometry_grid

    def predict_stones(
        self,
        rectified_board_bgr: np.ndarray,
        geometry_grid: list[list[tuple[int, int]]],
        status_label: str = "RAW",
    ) -> tuple[list[list[int]], list[list[bool]]]:
        """受け取った1000x1000画像とグリッド座標をそのままCnnStoneDetectorへ渡し、盤面を推論する"""
        if self.cnn_stone_detector.interpreter is None or rectified_board_bgr is None:
            empty_board = [[0] * 19 for _ in range(19)]
            certainty = [[True] * 19 for _ in range(19)]
            return empty_board, certainty

        # ★ 1000x1000 矩形化画像を判定ラベル付きで保存（361パッチとは分離）
        if getattr(DebugConfig, "SAVE_RECTIFIED_DEBUG", False):
            self._save_rectified_for_debug(rectified_board_bgr, status_label=status_label)

        # ★ 361分割パッチの保存（DebugConfig.ENABLE_DEBUG_SAVE が True のときのみ）
        if DebugConfig.ENABLE_DEBUG_SAVE:
            self._save_patches_for_debug(rectified_board_bgr, geometry_grid)

        return self.cnn_stone_detector.detect_stones(rectified_board_bgr, geometry_grid)

    def _save_rectified_for_debug(self, rectified_board_bgr: np.ndarray, status_label: str = "RAW"):
        """1000x1000 矩形化PNG画像を、成否・状態ラベル付きで保存するヘルパー"""
        try:
            if rectified_board_bgr is None or rectified_board_bgr.size == 0:
                return

            self._rectified_seq += 1
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            safe_label = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in (status_label or "RAW"))

            base_path = Path("debug_rectified_1000")
            base_path.mkdir(parents=True, exist_ok=True)

            filename = base_path / f"board_{self._rectified_seq:04d}_{safe_label}_{timestamp}.png"
            cv2.imwrite(str(filename), rectified_board_bgr)
        except Exception as e:
            print(f"[Debug] 1000x1000画像保存エラー: {e}")

    def _save_patches_for_debug(self, rectified_board_bgr: np.ndarray, geometry_grid: list[list[tuple[int, int]]]):
        """361分割の切り出しテスト用ヘルパー"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            base_path = Path("debug_patches") / timestamp
            base_path.mkdir(parents=True, exist_ok=True)

            patch_size = 60
            patch_radius = 30
            max_rows, max_cols = rectified_board_bgr.shape[:2]

            saved_count = 0
            for row in range(19):
                for col in range(19):
                    x, y = geometry_grid[row][col]

                    x1 = x - patch_radius
                    y1 = y - patch_radius
                    safe_x1 = max(0, min(x1, max(0, max_cols - patch_size)))
                    safe_y1 = max(0, min(y1, max(0, max_rows - patch_size)))

                    patch = rectified_board_bgr[safe_y1:safe_y1 + patch_size, safe_x1:safe_x1 + patch_size]

                    if patch.shape[0] == patch_size and patch.shape[1] == patch_size:
                        filename = base_path / f"patch_r{row:02d}_c{col:02d}.png"
                        cv2.imwrite(str(filename), patch)
                        saved_count += 1

            print(f"[Debug] ステップC: 361分割パッチの保存が完了しました ({saved_count}枚): {base_path.absolute()}")
        except Exception as e:
            print(f"[Debug] パッチ保存エラー: {e}")
            