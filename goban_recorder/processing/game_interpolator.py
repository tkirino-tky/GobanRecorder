"""
processing/board_interpolator.py
【設計思想・議論の背景】
囲碁の対局において、カメラのサンプリング間隔や手の影によりフレームが数手分飛んだ場合
（例: すぐ取返し、打って返し、打ち欠きなど）、単純な1手差分では盤面の変化を説明できない。
そのため、以下の制約のもとでローカルな逆算探索を行い、隠された中間手を復元する。
- 探索領域：変化のあった周辺の局所領域（Bounding Box）に限定
- 探索深度：最大2〜3手
- ルール：気、アゲハマ、コウ、自殺手禁止等の囲碁のルールに完全整合する最短パスを選択する
"""

from typing import List, Tuple, Optional

# 盤面の型定義: 19x19 の2次元リスト (0: 空, 1: 黒, 2: 白)
BoardState = List[List[int]]

class Move:
    def __init__(self, color: int, x: int, y: int, captures: List[Tuple[int, int]] = None):
        self.color = color  # 1: 黒, 2: 白
        self.x = x
        self.y = y
        self.captures = captures or [] # この手で取り去った石の座標リスト

class BoardInterpolator:
    def __init__(self, board_size: int = 19):
        self.board_size = board_size

    def is_single_valid_move(self, old_board: BoardState, new_board: BoardState) -> Optional[Move]:
        """
        通常の1手合法手による遷移かどうかを判定する。
        1手で説明がつく場合はその手（Move）を返し、つかない場合は None を返す。
        """
        diffs = []
        for y in range(self.board_size):
            for x in range(self.board_size):
                if old_board[y][x] != new_board[y][x]:
                    diffs.append((x, y, old_board[y][x], new_board[y][x]))

        # 通常の1手であれば、空(0)から石(1 or 2)に変わった場所が原則1つ、
        # ＋ルールに従ったアゲハマ（消滅した石）が存在するはず。
        # ここに簡易的なルールチェッカー（既存のエンジン）を適用する。
        # （※詳細は省きますが、1手分の変化かどうかの判定ロジックが入ります）
        
        return None # 仮実装

    def resolve_skipped_moves(self, old_board: BoardState, new_board: BoardState, current_turn: int, max_depth: int = 3) -> List[Move]:
        """
        【核心部】
        old_board から new_board への変化が1手では説明できない（フレームが飛んだ）場合、
        最大 max_depth（例: 2〜3手）までのローカル逆算探索を行い、
        間に挟まれていたはずの合法手シーケンス（打ち欠き、取返し、打って返し等）を復元する。
        """
        # 1. 変化のあった局所領域（Bounding Box）の特定
        bounding_box = self._get_changed_region(old_board, new_board)
        if not bounding_box:
            return [] # 変化なし

        # 2. 探索の初期化（現在の新しい盤面から過去へ遡る、または候補手を全探索）
        # 効率化のため、変化があった周辺の交点のみをターゲットにする
        recovered_path: List[Move] = []
        
        # バックトラック（深さ優先探索 / 幅優先探索）による逆算シミュレーション
        # 深度1〜max_depthまで、ルールエンジン上で合法手をシミュレートし、
        # new_board の状態に一致する最短の経路を探す
        found = self._backtrack_search(old_board, new_board, current_turn, depth=0, max_depth=max_depth, path=[])

        if found:
            return found
        else:
            # 万が一ルール的に完全に矛盾する場合は、安全のためフォールバック（直前の状態を維持等）
            print("[Warning] 隠された手筋の逆算に失敗しました。不連続なジャンプとして処理します。")
            return []

    def _get_changed_region(self, board_a: BoardState, board_b: BoardState) -> Optional[Tuple[int, int, int, int]]:
        """盤面で変化があった最小の矩形領域 (min_x, min_y, max_x, max_y) を返す"""
        min_x, min_y = self.board_size, self.board_size
        max_x, max_y = -1, -1
        changed = False

        for y in range(self.board_size):
            for x in range(self.board_size):
                if board_a[y][x] != board_b[y][x]:
                    changed = True
                    min_x = min(min_x, x)
                    min_y = min(min_y, y)
                    max_x = max(max_x, x)
                    max_y = max(max_y, y)

        if not changed:
            return None
        return (min_x, min_y, max_x, max_y)

    def _backtrack_search(self, current_board: BoardState, target_board: BoardState, turn: int, depth: int, max_depth: int, path: List[Move]) -> Optional[List[Move]]:
        """
        再帰的な逆算探索（メモ化・枝刈り付き）
        """
        if depth >= max_depth:
            return None

        # 終了条件：シミュレーション結果が target_board と一致するか
        if self._boards_match(current_board, target_board):
            return path

        # 局所エリアの空いている交点に対して、次の合法手を試す
        # （※実際には、囲碁のルールに基づく気・アゲハマ計算、打ち欠き・打って返しを生む候補手生成ロジックが入ります）
        
        return None
    