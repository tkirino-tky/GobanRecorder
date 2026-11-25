"""
ファイル名: goban_recorder/processing/initial_state_analyzer.py
説明: 初期盤面状態の自動判定クラス（StoneColor Enum と数値の比較不一致を修正した完全版）
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Tuple, Optional, Any

class GameStartStatus(Enum):
    EVEN_GAME_READY = auto()       # 互先で開始準備完了（石0個）
    HANDICAP_READY = auto()        # 置き碁で開始準備完了（黒石のみ・星の位置）
    RESUME_READY = auto()          # 中途再開準備完了（黒白存在・SGF履歴あり）
    MID_GAME_READY = auto()        # 中途開始準備完了（黒白存在・新規スタート）
    NOT_READY = auto()             # 開始不可（エラー・確認待ちメッセージを表示）


@dataclass
class InitialAnalysisResult:
    status: GameStartStatus
    message: str
    handicap_count: int = 0
    is_startable: bool = False


class InitialStateAnalyzer:
    """盤面の検出情報から初期対局状態を評価・判定するクラス"""

    # 19路盤の9つの「星」の座標定義 (col, row: 0-18)
    STAR_POINTS_19 = {
        (3, 3),   (3, 9),   (3, 15),
        (9, 3),   (9, 9),   (9, 15),
        (15, 3),  (15, 9),  (15, 15)
    }

    def analyze(
        self,
        board_layout: Optional[List[List[Any]]],
        has_sgf_history: bool = False,
        sgf_move_count: int = 0
    ) -> InitialAnalysisResult:
        """
        board_layout: 19x19の2次元リスト (StoneColor または 0:空, 1:黒, 2:白)
        """
        if board_layout is None:
            return InitialAnalysisResult(
                status=GameStartStatus.NOT_READY,
                message="盤面を認識中...",
                is_startable=False
            )

        black_stones: List[Tuple[int, int]] = []
        white_stones: List[Tuple[int, int]] = []

        for r in range(19):
            for c in range(19):
                val = board_layout[r][c]
                # ★ StoneColor Enum の場合にも対応できるよう .value を安全に取得
                val_num = val.value if hasattr(val, "value") else val

                if val_num == 1:
                    black_stones.append((c, r))
                elif val_num == 2:
                    white_stones.append((c, r))

        b_count = len(black_stones)
        w_count = len(white_stones)

        # ① 石が 0 個 ──> 「互先」
        if b_count == 0 and w_count == 0:
            return InitialAnalysisResult(
                status=GameStartStatus.EVEN_GAME_READY,
                message="🟢 互先（初手から開始）の準備が完了しました",
                is_startable=True
            )

        # ② 黒石のみ存在 ──> 「置き碁」
        if b_count > 0 and w_count == 0:
            return self._validate_handicap(black_stones)

        # ③ 黒石と白石の両方が存在 ──> 「中途開始 / 中途再開」
        if b_count > 0 and w_count > 0:
            if has_sgf_history:
                return InitialAnalysisResult(
                    status=GameStartStatus.RESUME_READY,
                    message=f"🔵 中途再開: {sgf_move_count}手目から記録を継続します",
                    is_startable=True
                )
            else:
                return InitialAnalysisResult(
                    status=GameStartStatus.MID_GAME_READY,
                    message=f"🟡 中途開始: 現局面（黒{b_count}個/白{w_count}個）から新規記録します",
                    is_startable=True
                )

        return InitialAnalysisResult(
            status=GameStartStatus.NOT_READY,
            message="盤面状態を確認中...",
            is_startable=False
        )

    def _validate_handicap(self, black_stones: List[Tuple[int, int]]) -> InitialAnalysisResult:
        count = len(black_stones)

        # 個数チェック（2〜9子）
        if not (2 <= count <= 9):
            return InitialAnalysisResult(
                status=GameStartStatus.NOT_READY,
                message=f"🟡 置き石の数を確認してください (検出: {count}個 / 対象: 2〜9子)",
                is_startable=False
            )

        # すべての黒石が「星」の座標の上にあるかチェック
        all_on_stars = all(pt in self.STAR_POINTS_19 for pt in black_stones)
        if not all_on_stars:
            return InitialAnalysisResult(
                status=GameStartStatus.NOT_READY,
                message="🟡 置き石が星以外の場所に置かれています",
                is_startable=False
            )

        return InitialAnalysisResult(
            status=GameStartStatus.HANDICAP_READY,
            message=f"🟢 置き碁 ({count}子) の準備が完了しました",
            handicap_count=count,
            is_startable=True
        )
    