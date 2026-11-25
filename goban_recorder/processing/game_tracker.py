import numpy as np


class GameTracker:
    """現在の認識盤面と過去の確定盤面を比較し、手番とアゲハマを管理して変化を検出するクラス"""

    def __init__(self, game_state):
        self.game_state = game_state

    def analyze_board_change(self, recognized_board):
        """
        :param recognized_board: 19x19 のNumPy配列 または list (0:空, 1:黒, 2:白)
        :return: (status, details)
                 status: 'NO_CHANGE', 'NEW_MOVE', 'INVALID'
        """
        recognized_board = np.array(recognized_board)
        current_board = np.array(self.game_state.board)

        # 変化の有無チェック
        if np.array_equal(recognized_board, current_board):
            return "NO_CHANGE", {}

        # 現在の正しい手番 ("B" または "W")
        expected_color_str = self.game_state.current_turn

        # 1. 新しく増えた石の検出 (元が0で、今回1または2になった場所)
        added_mask = (current_board == 0) & (recognized_board > 0)
        added_positions = np.argwhere(added_mask)

        # 2. 消えた石（アゲハマ）の検出 (元が1/2で、今回0になった場所)
        removed_mask = (current_board > 0) & (recognized_board == 0)
        removed_positions = np.argwhere(removed_mask)

        # 【ケースA】石が1つ増えた場合（一般的な着手）
        if len(added_positions) == 1:
            y, x = added_positions[0]
            new_val = recognized_board[y, x]
            color_str = "B" if new_val == 1 else "W"

            # 新しく置かれた石の色が「現在の手番の色」と一致しない場合はノイズと判定
            if color_str != expected_color_str:
                return "INVALID", {
                    "reason": f"手番違い: 期待={expected_color_str}, 検出={color_str}"
                }

            # 取られた石（アゲハマ）の計算
            captured_count = len(removed_positions)

            return "NEW_MOVE", {
                "pos": (int(x), int(y)),
                "color": color_str,
                "captured_count": captured_count,
            }

        # 一度に複数の石が増えている場合や、無効な変化
        return "INVALID", {
            "reason": f"不整合な盤面変化を検出 (増={len(added_positions)}, 減={len(removed_positions)})"
        }
    