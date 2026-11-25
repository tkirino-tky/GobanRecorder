"""
ファイル名: goban_recorder/pipeline/cnn_stone_detector.py
説明: Android版（CnnStoneDetector.kt）と完全同一の幾何クランプ、TFLite推論、光飛び対策安全フィルタを実装したCNN石検出器
"""

import numpy as np
import cv2
import tensorflow as tf
import threading
from typing import List, Tuple, Any

class CnnStoneDetector:
    def __init__(self, model_path: str = None, interpreter: tf.lite.Interpreter = None):
        # Android版と完全同一のパッチ設定（60x60px、半径30px）
        self.patch_size = 60
        self.patch_radius = 30
        self.confidence_threshold = 0.80

        # クラスインデックス定義（Android版 INDEX_EMPTY=0, INDEX_BLACK=1, INDEX_WHITE=2 と完全一致）
        self.INDEX_EMPTY = 0
        self.INDEX_BLACK = 1
        self.INDEX_WHITE = 2

        # スレッド競合（クラッシュ・切断）を防ぐための排他ロック
        self._lock = threading.Lock()

        # TFLite Interpreter の初期化
        if interpreter is not None:
            self.interpreter = interpreter
        elif model_path is not None:
            self.interpreter = tf.lite.Interpreter(model_path=str(model_path))
            self.interpreter.allocate_tensors()
        else:
            self.interpreter = None

        if self.interpreter is not None:
            self.input_details = self.interpreter.get_input_details()
            self.output_details = self.interpreter.get_output_details()

    def predict_probabilities(self, rectified_mat: np.ndarray, geometry_grid: List[List[Tuple[int, int]]]) -> np.ndarray:
        """
        19x19全交点の確率分布 [19][19][3] を算出する関数
        ※ Android版 CnnStoneDetector.kt の predictProbabilities および coerceIn クランプ処理と完全同一
        """
        prob_grid = np.zeros((19, 19, 3), dtype=np.float32)
        max_rows, max_cols = rectified_mat.shape[:2]

        if self.interpreter is None:
            return prob_grid

        with self._lock:
            try:
                for row in range(19):
                    for col in range(19):
                        x, y = geometry_grid[row][col]

                        # Android版と完全同一の範囲計算
                        x1 = x - self.patch_radius
                        y1 = y - self.patch_radius

                        # Androidの coerceIn(0, maxOf(0, maxCols - patchSize)) と完全同等の安全クランプ
                        safe_x1 = max(0, min(x1, max(0, max_cols - self.patch_size)))
                        safe_y1 = max(0, min(y1, max(0, max_rows - self.patch_size)))

                        # 60x60pxパッチの切り出し
                        patch = rectified_mat[safe_y1:safe_y1 + self.patch_size, safe_x1:safe_x1 + self.patch_size]

                        if patch.shape[0] == self.patch_size and patch.shape[1] == self.patch_size:
                            prob_grid[row][col] = self._run_inference_probs_locked(patch)

            except Exception as e:
                print(f"[CnnStoneDetector] 確率予測中にエラーが発生しました: {e}")

        return prob_grid

    def _run_inference_probs_locked(self, color_mat: np.ndarray) -> np.ndarray:
        """
        単一パッチ（60x60px）に対するTFLite推論を実行
        ※ Android版 runInferenceProbs と完全同一の BGR->RGB変換 および 0〜1正規化
        """
        try:
            # BGRからRGBへ変換 (学習時のデータ形式に一致)
            rgb_patch = cv2.cvtColor(color_mat, cv2.COLOR_BGR2RGB)

            # 0〜1のfloat32配列へ変換 (60, 60, 3)
            input_tensor = rgb_patch.astype(np.float32) / 255.0
            input_tensor = np.expand_dims(input_tensor, axis=0)

            self.interpreter.set_tensor(self.input_details[0]['index'], input_tensor)
            self.interpreter.invoke()
            
            output_data = self.interpreter.get_tensor(self.output_details[0]['index'])
            return output_data[0]  # shape: (3,)

        except Exception as e:
            print(f"[CnnStoneDetector] 推論実行エラー: {e}")
            return np.array([1.0, 0.0, 0.0], dtype=np.float32)

    def aggregate_inferences(self, frame_probs_list: List[np.ndarray]) -> Tuple[List[List[int]], List[List[bool]]]:
        """
        確率分布から最終的な盤面状態（石の色・確信度）を決定する関数
        ※ Android版 CnnStoneDetector.kt の aggregateInferences と完全同一の安全フィルタ（光飛び対策）
        """
        board_layout = [[0 for _ in range(19)] for _ in range(19)]
        certainty_layout = [[True for _ in range(19)] for _ in range(19)]

        if not frame_probs_list:
            return board_layout, certainty_layout

        probs_map = frame_probs_list[0]  # shape: (19, 19, 3)

        for row in range(19):
            for col in range(19):
                probs = probs_map[row][col]

                max_index = int(np.argmax(probs))
                max_val = float(probs[max_index])

                winning_class = max_index

                # ★【光飛び対策安全フィルタ：偽白石防止（Android版完全一致）】
                # 白石(INDEX_WHITE)と判定されても確率が0.80未満の場合はノイズとみなしEMPTY（空白）へ変換
                if winning_class == self.INDEX_WHITE and max_val < self.confidence_threshold:
                    winning_class = self.INDEX_EMPTY

                predicted_color = winning_class  # 0: EMPTY, 1: BLACK, 2: WHITE

                # ★【光飛び対策安全フィルタ：黒石ハイライト補正（Android版完全一致）】
                # 黒石と判定され、確率が 0.80 未満であっても、白石の確率が極めて低い（0.05未満）場合は
                # 表面テカリ（ハイライト）によるスコア下落とみなし確信度 true とする
                if winning_class == self.INDEX_EMPTY:
                    is_certain = True
                elif winning_class == self.INDEX_BLACK:
                    white_score = float(probs[self.INDEX_WHITE])
                    is_certain = (max_val >= self.confidence_threshold) or (white_score < 0.05)
                else:
                    is_certain = (max_val >= self.confidence_threshold)

                board_layout[row][col] = predicted_color
                certainty_layout[row][col] = is_certain

        return board_layout, certainty_layout

    def detect_stones(self, rectified_mat: np.ndarray, geometry_grid: List[List[Tuple[int, int]]]) -> Tuple[List[List[int]], List[List[bool]]]:
        """
        単一フレーム解析エントリーポイント
        """
        single_probs = self.predict_probabilities(rectified_mat, geometry_grid)
        return self.aggregate_inferences([single_probs])
    