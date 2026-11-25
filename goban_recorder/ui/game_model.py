"""
ファイル名: goban_recorder/ui/game_model.py
説明: 対局設定および棋譜ツリー構造管理クラス（盤面マトリクス取得メソッド・整数キャスト安全ガード追加版）
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List
import time


class StartMode(Enum):
    NORMAL = "通常スタート（初手から）"
    RESUME = "途中再開モード（盤面認識）"


# 言語別デフォルト対局者名
DEFAULT_PLAYER_NAMES = {
    "ja": {"black": "黒番", "white": "白番"},
    "en": {"black": "Black", "white": "White"},
}
CURRENT_LANG = "ja"


@dataclass
class GameSettings:
    """対局設定（デフォルト値付き）"""
    start_mode: StartMode = StartMode.NORMAL
    black_player: str = DEFAULT_PLAYER_NAMES[CURRENT_LANG]["black"]
    white_player: str = DEFAULT_PLAYER_NAMES[CURRENT_LANG]["white"]
    handicap: int = 0         # 置き石 (0: 平手)
    komi: float = 6.5         # コミ
    initial_move_count: int = 0
    initial_captures_black: int = 0
    initial_captures_white: int = 0


@dataclass
class MoveNode:
    """着手1手を表すノード（双方向連結リスト構造）"""
    move_number: int                  # 手数 (0は初期盤面)
    color: Optional[str]              # 'B' (黒), 'W' (白), None (初期盤面)
    coordinate: Optional[tuple]       # (x, y) 座標 (0~18, 0~18) または None
    captures_black: int = 0           # 黒の累計取り石
    captures_white: int = 0           # 白の累計取り石
    timestamp: float = field(default_factory=time.time)

    # ポインタ
    prev_node: Optional['MoveNode'] = None
    next_node: Optional['MoveNode'] = None
    variations: List['MoveNode'] = field(default_factory=list)


class GameTree:
    """対局全体を管理するツリー構造"""
    def __init__(self, settings: GameSettings, initial_board: Optional[List[List[int]]] = None):
        self.settings = settings
        self.board_size = 19
        
        # 初期盤面（指定がなければ19x19の空盤面）
        if initial_board is not None:
            self.initial_board = [row[:] for row in initial_board]
        else:
            self.initial_board = [[0 for _ in range(self.board_size)] for _ in range(self.board_size)]

        # ルートノード（0手目または途中再開基点）
        self.root = MoveNode(
            move_number=settings.initial_move_count,
            color=None,
            coordinate=None,
            captures_black=settings.initial_captures_black,
            captures_white=settings.initial_captures_white
        )
        self.current_node = self.root
        self.total_moves = settings.initial_move_count

    def add_move(self, color: str, coord: Optional[tuple], cap_b: int = 0, cap_w: int = 0) -> MoveNode:
        """新しい着手ノードを追加してリンクを更新"""
        self.total_moves += 1
        new_node = MoveNode(
            move_number=self.total_moves,
            color=color,
            coordinate=coord,
            captures_black=cap_b,
            captures_white=cap_w,
            prev_node=self.current_node
        )
        self.current_node.next_node = new_node
        self.current_node = new_node
        return new_node

    def get_current_board_matrix(self) -> List[List[int]]:
        """
        ルート（初期盤面）から現在のノードまでの着手を順番に適用し、
        現在の盤面状態（19x19の整数マトリクス: 0=空, 1=黒, 2=白）を正確に復元して返す。
        """
        # 初期盤面をベースにする
        board = [row[:] for row in self.initial_board]

        # ルートから現在のノードまでのパスを収集
        path = []
        node = self.current_node
        while node is not None and node.coordinate is not None:
            path.append(node)
            node = node.prev_node
        
        # 古い順（根から葉へ）に適用
        for n in reversed(path):
            if n.coordinate is not None:
                try:
                    # 座標が文字列等で入っていても確実に整数に変換する安全ガード
                    r = int(n.coordinate[0])
                    c = int(n.coordinate[1])
                    if 0 <= r < self.board_size and 0 <= c < self.board_size:
                        stone_val = 1 if n.color == "B" else 2
                        board[r][c] = stone_val
                except (ValueError, TypeError):
                    continue

        return board
    