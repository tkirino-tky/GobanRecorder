"""
ファイル名: goban_recorder/processing/game_loop_worker.py
説明: カメラ等のフレームを受け取り、YOLO/CNN推論を経て GameLoopManager へ繋ぐパイプラインワーカー
"""

import logging
from typing import List, Tuple, Dict, Any, Optional
import cv2
import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

logger = logging.getLogger(__name__)


def evaluate_and_validate_move(prev_board: List[List[int]], curr_board: List[List[int]], board_size: int = 19) -> Tuple[str, Dict[str, Any]]:
    """
    前後の盤面を比較し、起きた変化が合法な1手であるかを検証する。
    """
    added_stones = []
    removed_stones = []

    for r in range(board_size):
        for c in range(board_size):
            p = prev_board[r][c]
            curr = curr_board[r][c]
            if p == 0 and curr != 0:
                added_stones.append((r, c, curr))
            elif p != 0 and curr == 0:
                removed_stones.append((r, c, p))
            elif p != 0 and curr != 0 and p != curr:
                pass

    if not added_stones and not removed_stones:
        return "NO_CHANGE", {}

    if len(added_stones) == 1:
        r, c, color = added_stones[0]
        
        if _is_suicide_move(curr_board, r, c, color, board_size):
            return "INVALID", {"reason": "自殺手（着手禁止点）です。"}

        move_info = {
            "row": r,
            "col": c,
            "color": color,
            "captured": removed_stones,
            "flag": "NORMAL"
        }
        return "NORMAL", move_info

    elif len(added_stones) > 1:
        return "AMBIGUOUS", {
            "added_stones": added_stones,
            "removed_stones": removed_stones,
            "flag": "AMBIGUOUS"
        }

    return "INVALID", {"reason": "不自然な盤面の変化です。"}


def _is_suicide_move(board: List[List[int]], row: int, col: int, color: int, board_size: int) -> bool:
    """
    自殺手（呼吸点がなく、相手の石も取らない手）の簡易判定。
    """
    directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    liberties = 0
    opponent_color = 3 - color
    adjacent_opponent_stones = []

    for dr, dc in directions:
        nr, nc = row + dr, col + dc
        if 0 <= nr < board_size and 0 <= nc < board_size:
            neighbor = board[nr][nc]
            if neighbor == 0:
                liberties += 1
            elif neighbor == opponent_color:
                adjacent_opponent_stones.append((nr, nc))

    if liberties > 0:
        return False
    if adjacent_opponent_stones:
        return False

    return True


class GameLoopPipelineWorker(QObject):
    """
    カメラ映像などのフレームを受け取り、YOLO/CNNによる画像処理を経て
    GameLoopManager（コントローラー）へ繋ぐパイプライン。
    """
    status_updated = Signal(object, str)
    board_state_updated = Signal(list)

    def __init__(self, game_loop_controller, board_size: int = 19):
        super().__init__()
        self.controller = game_loop_controller
        self.board_size = board_size
        
        # 実際の推論エンジン・検出器
        self.inference_engine = None
        self.corner_detector = None
        self.stone_classifier = None

    def set_engines(self, inference_engine=None, corner_detector=None, stone_classifier=None):
        """YOLO検出器やCNN分類器、またはInferenceEngineを設定する"""
        self.inference_engine = inference_engine
        self.corner_detector = corner_detector
        self.stone_classifier = stone_classifier

    @Slot(np.ndarray)
    def process_incoming_frame(self, frame: np.ndarray):
        """
        カメラから新しいフレームが入ってきたときに呼ばれるメイン処理。
        """
        if not self.controller.is_running:
            return

        try:
            # 1. YOLO等によるコーナー検出 & 透視変換（盤面切り出し）
            warped_board = self._detect_and_warp_board(frame)
            if warped_board is None:
                status, msg = self.controller.process_frame(None)
                self.status_updated.emit(status, msg)
                return

            # 2. CNN等による19x19サンプリングと石の分類
            board_matrix = self._classify_board_stones(warped_board)
            if board_matrix is None:
                self.status_updated.emit(None, "石の分類に失敗しました。")
                return

            # 3. Game Loop マネージャーへ渡して変化を評価
            status, message = self.controller.process_frame(board_matrix)

            # 4. 結果をUI側に通知
            self.status_updated.emit(status, message)
            if status.name in ["NORMAL", "MULTI_MOVE", "AMBIGUOUS"]:
                self.board_state_updated.emit(board_matrix)

        except Exception as e:
            logger.error(f"Error in GameLoopPipeline: {e}", exc_info=True)
            self.status_updated.emit(None, f"処理エラー: {e}")

    def _detect_and_warp_board(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """
        YOLOコーナー検出器を用いた台形補正（Perspective Transform）
        """
        # 1. 統合された inference_engine がある場合
        if self.inference_engine and hasattr(self.inference_engine, 'detect_corners_and_warp'):
            return self.inference_engine.detect_corners_and_warp(frame)
        
        # 2. 個別の corner_detector がある場合
        if self.corner_detector and hasattr(self.corner_detector, 'detect'):
            corners = self.corner_detector.detect(frame)
            if corners is not None and len(corners) == 4:
                from goban_recorder.utils.image_utils import warp_perspective
                return warp_perspective(frame, corners)
            return None

        # フォールバック（未設定時はそのまま返す）
        return frame

    def _classify_board_stones(self, warped_board: np.ndarray) -> Optional[List[List[int]]]:
        """
        CNN分類器を用いた19x19交点の石の判定（0:空, 1:黒, 2:白）
        """
        # 1. 統合された inference_engine がある場合
        if self.inference_engine and hasattr(self.inference_engine, 'classify_board'):
            return self.inference_engine.classify_board(warped_board)
        
        if self.inference_engine and hasattr(self.inference_engine, 'predict'):
            return self.inference_engine.predict(warped_board)

        # 2. 個別の stone_classifier がある場合
        if self.stone_classifier and hasattr(self.stone_classifier, 'predict_board'):
            return self.stone_classifier.predict_board(warped_board)

        # フォールバック（未設定時は現在の状態を維持）
        return self.controller.current_board_state
    