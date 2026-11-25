from enum import Enum, auto
import numpy as np


class BoardCoordinateStyle(Enum):
    NONE = auto()          # 1. 座標なし (Default)
    KGS = auto()           # 2. KGS方式 (A~T / 19~1)
    KIIN = auto()          # 3. 日本棋院方式 (1~19 / 一~十九)

class CoordinateFormatter:
    """内部座標(col, row: 0-18)から各種スタイルの軸ラベル文字列を生成するクラス"""

    # KGS方式用のX軸アルファベット列 (Iを除外した19文字)
    KGS_X_LABELS = [
        "A", "B", "C", "D", "E", "F", "G", "H", "J", "K",
        "L", "M", "N", "O", "P", "Q", "R", "S", "T"
    ]

    # 日本棋院方式用のY軸漢数字列
    KIIN_Y_LABELS = [
        "一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
        "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九"
    ]

    @classmethod
    def get_x_label(cls, col: int, style: BoardCoordinateStyle) -> str:
        """横軸（上・下）のラベル文字列を取得 (col: 0..18)"""
        if not (0 <= col <= 18):
            return ""

        if style == BoardCoordinateStyle.NONE:
            return ""
        elif style == BoardCoordinateStyle.KIIN:
            return str(col + 1)  # 1 ~ 19
        elif style == BoardCoordinateStyle.KGS:
            return cls.KGS_X_LABELS[col]  # A ~ T (I抜き)

    @classmethod
    def get_y_label(cls, row: int, style: BoardCoordinateStyle) -> str:
        """縦軸（左・右）のラベル文字列を取得 (row: 0..18)"""
        if not (0 <= row <= 18):
            return ""

        if style == BoardCoordinateStyle.NONE:
            return ""
        elif style == BoardCoordinateStyle.KIIN:
            return cls.KIIN_Y_LABELS[row]  # 一 ~ 十九 (上から下)
        elif style == BoardCoordinateStyle.KGS:
            return str(19 - row)  # 19 ~ 1 (下から上)


class MoveNode:
    """棋譜の1手（ノード）を表すクラス（Linked List構造）"""

    def __init__(self, move_number=0, color=None, pos=None, parent=None):
        self.move_number = move_number  # 手数 (1, 2, 3...)
        self.color = color  # 'B' (黒) または 'W' (白)
        self.pos = pos  # (x, y) 座標
        self.parent = parent  # 親ノード（前の手へのリンク）
        self.children = []  # 子ノード（次の手 / 変化図）
        self.captured_stones = []  # この手で取り上げた石の座標リスト


class GameState:
    """盤面状態および棋譜全体を管理するクラス（囲碁ルール判定統合版）"""

    def __init__(self):
        # 19x19 盤面 (0: 空点, 1: 黒石, 2: 白石)
        self.board = np.zeros((19, 19), dtype=np.int8)

        # 棋譜ツリーの開始ノード
        self.root_node = MoveNode(move_number=0)
        self.current_node = self.root_node

        # 手番 ('B' から開始)
        self.turn = 'B'

        # アゲハマのカウント
        self.black_captures = 0
        self.white_captures = 0

        # 座標表示スタイルの保持（デフォルト: 日本棋院方式）
        self.coordinate_style = BoardCoordinateStyle.KIIN

    def set_coordinate_style(self, style: BoardCoordinateStyle):
        """座標表示スタイルを変更する"""
        self.coordinate_style = style

    def get_group_and_liberties(self, start_x, start_y):
        """
        指定した座標の石からスタートし、つながっている同じ色の「連（グループ）」と、
        その連が持つすべての「呼吸点（リバティ）」をグラフ探索（DFS）で取得する。
        """
        color = self.board[start_y, start_x]
        if color == 0:
            return set(), set()

        group = set()     # 連に含まれる石の座標 (x, y) のセット
        liberties = set() # 連が持つ呼吸点（空きマス）の座標 (x, y) のセット
        stack = [(start_x, start_y)]
        visited = set()

        while stack:
            cx, cy = stack.pop()
            if (cx, cy) in visited:
                continue
            visited.add((cx, cy))
            group.add((cx, cy))

            # 上下左右をチェック
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = cx + dx, cy + dy
                if 0 <= nx < 19 and 0 <= ny < 19:
                    neighbor = self.board[ny, nx]
                    if neighbor == 0:
                        liberties.add((nx, ny))
                    elif neighbor == color and (nx, ny) not in visited:
                        stack.append((nx, ny))

        return group, liberties

    def play_move(self, x, y, color=None) -> bool:
        """
        指定した座標に石を置き、囲碁のルールに基づいて妥当性を判定し、
        アゲハマの回収や棋譜ノード・盤面の更新を行う。
        成功した場合は True、自殺手などで無効な場合は False を返す。

        :param x: 着手のX座標 (0-18)
        :param y: 着手のY座標 (0-18)
        :param color: 'B' (黒) または 'W' (白)。省略時は現在の self.turn を使用
        """
        if color is None:
            color = self.turn

        if not (0 <= x < 19 and 0 <= y < 19):
            return False
        if self.board[y, x] != 0:
            return False  # すでに石がある

        stone_val = 1 if color == 'B' else 2
        opponent_stone_val = 2 if color == 'B' else 1

        # 1. 仮に石を置いてみる
        self.board[y, x] = stone_val

        captured_stones_list = []

        # 2. 上下左右の敵の連をチェックし、呼吸点が0なら取り除く対象にする
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx, ny = x + dx, y + dy
            if 0 <= nx < 19 and 0 <= ny < 19:
                if self.board[ny, nx] == opponent_stone_val:
                    opp_group, opp_liberties = self.get_group_and_liberties(nx, ny)
                    if len(opp_liberties) == 0:
                        for gx, gy in opp_group:
                            if (gx, gy) not in captured_stones_list:
                                captured_stones_list.append((gx, gy))

        # 3. 自分の置いた石の連の呼吸点をチェック（自殺手チェック）
        my_group, my_liberties = self.get_group_and_liberties(x, y)

        # 敵を取れておらず、かつ自分の呼吸点も0なら「自殺手」となるため無効
        if len(captured_stones_list) == 0 and len(my_liberties) == 0:
            self.board[y, x] = 0  # 盤面を元に戻す
            return False

        # 4. 打ち取った石を一時的に盤面から取り除く（アゲハマ計算のため）
        for cx, cy in captured_stones_list:
            self.board[cy, cx] = 0

        if color == 'B':
            self.black_captures += len(captured_stones_list)
        else:
            self.white_captures += len(captured_stones_list)

        # 5. 新しいノード（手）を作成して棋譜ツリーに登録し、手番を交代
        new_node = MoveNode(
            move_number=self.current_node.move_number + 1,
            color=color,
            pos=(x, y),
            parent=self.current_node,
        )
        new_node.captured_stones = captured_stones_list

        self.current_node.children.append(new_node)
        self.current_node = new_node

        # 手番の交替
        self.turn = 'W' if color == 'B' else 'B'

        return True
    