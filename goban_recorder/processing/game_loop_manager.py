"""
ファイル名: goban_recorder/processing/game_loop_manager.py
説明: 確定済み基準盤面との比較、手番・囲碁ルール（打ち上げ）検証、
      pending_1 -> pending_2 -> 確定 の基本ループおよび
      1) 複数石同時増加（2個・3個等、3個時の前後Ambiguous付番）
      2) pending_1 -> pending_2 遷移時に次の手番の石が重なるケース
      3) 不正判定時の座標ログ出力および通知シグナル
      に対応したメインループ管理（手番 next_turn_color を本クラスで集中管理・明示確定）
"""

import logging
from collections import deque
from typing import List, Tuple, Dict, Any, Optional, Set
from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


def _get_group_and_liberties(
    board: List[List[int]], start_r: int, start_c: int, board_size: int = 19
) -> Tuple[Set[Tuple[int, int]], int]:
    """指定座標の石と連結する同色の連（グループ）および呼吸点（空点）の数を返す。"""
    color = board[start_r][start_c]
    if color == 0:
        return set(), 0

    visited: Set[Tuple[int, int]] = {(start_r, start_c)}
    liberties: Set[Tuple[int, int]] = set()
    queue = deque([(start_r, start_c)])
    directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    while queue:
        r, c = queue.popleft()
        for dr, dc in directions:
            nr, nc = r + dr, c + dc
            if 0 <= nr < board_size and 0 <= nc < board_size:
                val = board[nr][nc]
                if val == 0:
                    liberties.add((nr, nc))
                elif val == color and (nr, nc) not in visited:
                    visited.add((nr, nc))
                    queue.append((nr, nc))

    return visited, len(liberties)


def simulate_move_and_captures(
    base_board: List[List[int]], row: int, col: int, color: int, board_size: int = 19
) -> Tuple[bool, List[Tuple[int, int]], List[List[int]], str]:
    """
    確定済み基準盤面 base_board の (row, col) に color (1:黒, 2:白) を仮着手し、
    囲碁のルールに従って打ち上げられる相手石と、適用後の新盤面を返す。
    """
    if base_board[row][col] != 0:
        return False, [], base_board, "すでに石が存在する交点です。"

    next_board = [r[:] for r in base_board]
    next_board[row][col] = color

    opponent_color = 2 if color == 1 else 1
    directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    captured_set: Set[Tuple[int, int]] = set()

    for dr, dc in directions:
        nr, nc = row + dr, col + dc
        if 0 <= nr < board_size and 0 <= nc < board_size:
            if next_board[nr][nc] == opponent_color and (nr, nc) not in captured_set:
                group, libs = _get_group_and_liberties(next_board, nr, nc, board_size)
                if libs == 0:
                    captured_set.update(group)

    for cr, cc in captured_set:
        next_board[cr][cc] = 0

    _, own_libs = _get_group_and_liberties(next_board, row, col, board_size)
    if own_libs == 0:
        return False, [], base_board, "自殺手（着手禁止点）です。"

    captured_list = sorted(list(captured_set))
    return True, captured_list, next_board, ""


def evaluate_and_validate_move(
    prev_board: List[List[int]],
    curr_board: List[List[int]],
    expected_color: Optional[int] = None,
    board_size: int = 19,
) -> Tuple[str, Dict[str, Any]]:
    """
    確定済み基準盤面 prev_board と現在の推論盤面 curr_board を比較し、
    1. 次の手番（expected_color）の石が1つだけ増えているか
    2. 基準盤面にその着手を適用した際のルール上の打ち上げ（アゲハマ）と、
       実際の相手石の減少（および盤面全体）が一致するか
    を検証する。
    """
    added_stones = []
    removed_stones = []
    changed_color_stones = []

    for r in range(board_size):
        for c in range(board_size):
            p = prev_board[r][c]
            curr = curr_board[r][c]

            if p == 0 and curr != 0:
                added_stones.append((r, c, curr))
            elif p != 0 and curr == 0:
                removed_stones.append((r, c, p))
            elif p != 0 and curr != 0 and p != curr:
                changed_color_stones.append((r, c, p, curr))

    if not added_stones and not removed_stones and not changed_color_stones:
        return "NO_CHANGE", {}

    if changed_color_stones:
        return "INVALID", {"reason": "既存石の色反転を検知しました。"}

    if len(added_stones) == 1:
        r, c, color = added_stones[0]

        if expected_color is not None and color != expected_color:
            exp_name = "黒" if expected_color == 1 else "白"
            det_name = "黒" if color == 1 else "白"
            return "INVALID", {"reason": f"手番不一致（期待: {exp_name}, 検出: {det_name}）"}

        is_valid, expected_captured, expected_next_board, reason = simulate_move_and_captures(
            prev_board, r, c, color, board_size
        )
        if not is_valid:
            return "INVALID", {"reason": reason}

        opponent_color = 2 if color == 1 else 1
        if any(rem_color != opponent_color for _, _, rem_color in removed_stones):
            return "INVALID", {"reason": "手番側の石が不正に消えています。"}

        actual_removed_coords = sorted([(rr, rc) for rr, rc, _ in removed_stones])
        if actual_removed_coords != expected_captured:
            return "INVALID", {
                "reason": f"打ち上げ石の不整合（ルール計算: {len(expected_captured)}個, 実検出: {len(actual_removed_coords)}個）"
            }

        move_info = {
            "row": r,
            "col": c,
            "color": color,
            "added_stones": added_stones,
            "captured": removed_stones,
            "removed_stones": removed_stones,
            "captured_count": len(expected_captured),
            "next_board": expected_next_board,
            "flag": "NORMAL",
            "ambiguous": False,
        }
        return "NORMAL", move_info

    elif len(added_stones) > 1:
        forced_board = [r[:] for r in prev_board]
        for ar, ac, acol in added_stones:
            forced_board[ar][ac] = acol
        for rr_coord, rc_coord, _ in removed_stones:
            forced_board[rr_coord][rc_coord] = 0

        return "AMBIGUOUS", {
            "added_stones": added_stones,
            "removed_stones": removed_stones,
            "forced_board": forced_board,
            "flag": "AMBIGUOUS",
            "ambiguous": True,
        }

    return "INVALID", {"reason": "石の増加を伴わない盤面変化です。"}


class GameLoopManager(QObject):
    """
    対局ループ中の手番（next_turn_color）と確定済み基準盤面を単一箇所で管理するクラス。
    手番の変更は initialize_board / set_next_turn_color / _commit_single_move / reset_state のみで行い、
    次の手番も明示的に指定する。
    """
    state_changed = Signal(str)
    warning_triggered = Signal(str)
    move_confirmed = Signal(int, int, str, int, int)
    ambiguous_move_recorded = Signal(int, dict)
    invalid_move_detected = Signal(str, list, list)
    turn_updated = Signal(int)

    def __init__(self, game_tree=None, inference_engine=None, parent=None, board_size: int = 19):
        super().__init__(parent=parent)
        self.game_tree = game_tree
        self.inference_engine = inference_engine
        self.board_size = board_size

        self.is_processing = False
        self.current_state = "IDLE"

        self.current_board_state = [[0 for _ in range(board_size)] for _ in range(board_size)]
        self._next_turn_color: int = 1
        self.black_captures: int = 0
        self.white_captures: int = 0
        self.move_history: List[Dict[str, Any]] = []
        self.is_running = False

        # pending_stage: 0=なし, 1=pending_1, 2=pending_2, 3=確定段階
        self.pending_stage: int = 0
        self.pending_added_stones: List[Tuple[int, int, int]] = []
        self.pending_removed_stones: List[Tuple[int, int, int]] = []
        self.pending_status: Optional[str] = None
        self.pending_details: Optional[Dict[str, Any]] = None
        self.required_consecutive_frames: int = 3

    @property
    def next_turn_color(self) -> int:
        """現在の次手番（1: 黒, 2: 白）を返す。"""
        return self._next_turn_color

    def _set_turn_internal(self, turn_color: int, reason: str = ""):
        if turn_color not in (1, 2):
            return
        prev = self._next_turn_color
        self._next_turn_color = turn_color
        if prev != turn_color:
            turn_name = "黒番(1)" if turn_color == 1 else "白番(2)"
            print(f"[GameLoopManager] 🔄 手番更新: {prev} -> {turn_color} ({turn_name}) [{reason}]")
            self.turn_updated.emit(self._next_turn_color)

    def set_next_turn_color(self, turn_color: int, reason: str = "外部確定"):
        """手番を明示設定するための公式窓口（外部からの直接代入を避ける）。"""
        self._set_turn_internal(turn_color, reason=reason)

    def _clear_pending(self):
        self.pending_stage = 0
        self.pending_added_stones = []
        self.pending_removed_stones = []
        self.pending_status = None
        self.pending_details = None

    def _diff_from_base(
        self, base_board: List[List[int]], curr_board: List[List[int]]
    ) -> Tuple[List[Tuple[int, int, int]], List[Tuple[int, int, int]], List[Tuple[int, int, int, int]]]:
        added = []
        removed = []
        color_flipped = []
        for r in range(self.board_size):
            for c in range(self.board_size):
                p = base_board[r][c]
                curr = curr_board[r][c]
                if p == 0 and curr != 0:
                    added.append((r, c, curr))
                elif p != 0 and curr == 0:
                    removed.append((r, c, p))
                elif p != 0 and curr != 0 and p != curr:
                    color_flipped.append((r, c, p, curr))
        return added, removed, color_flipped

    def _commit_single_move(self, r: int, c: int, color: int, ambiguous: bool = False):
        """1手分の着手を基準盤面へ反映し、着手番号を付与して記録し、次の手番を明示的に設定する。"""
        is_valid, expected_captured, expected_next_board, _ = simulate_move_and_captures(
            self.current_board_state, r, c, color, self.board_size
        )
        if is_valid:
            next_board = expected_next_board
            cap_coords = expected_captured
        else:
            next_board = [row[:] for row in self.current_board_state]
            next_board[r][c] = color
            cap_coords = []

        cap_count = len(cap_coords)
        if color == 1:
            self.black_captures += cap_count
        else:
            self.white_captures += cap_count

        self.current_board_state = next_board
        explicit_next_turn = 2 if color == 1 else 1
        self._set_turn_internal(explicit_next_turn, reason=f"着手確定 ({r},{c}) color={color}")

        move_num = len(self.move_history) + 1
        color_char = "B" if color == 1 else "W"
        flag_str = "AMBIGUOUS" if ambiguous else "NORMAL"

        record = {
            "row": r,
            "col": c,
            "color": color,
            "captured": cap_coords,
            "captured_count": cap_count,
            "next_board": [row[:] for row in next_board],
            "flag": flag_str,
            "ambiguous": ambiguous,
            "move_number": move_num,
        }
        self.move_history.append(record)

        if ambiguous:
            self.ambiguous_move_recorded.emit(move_num, record)
            print(f"[GameLoopManager] ⚡ {move_num}手目 [AMBIGUOUS] 確定: 座標=({r}, {c}), 色={color_char}")
        else:
            print(f"[GameLoopManager] 🎯 {move_num}手目を確定: 座標=({r}, {c}), 色={color_char}, アゲハマ={cap_count}個")

        self.move_confirmed.emit(r, c, color_char, move_num, cap_count)

    def _commit_pending_candidate(self):
        """
        pending 候補（1個または複数個）を確定させる。
        - 1個の場合：通常確定（または手番・ルール不整合時は ambiguous 扱い）
        - 2個の場合：手番順（手番石 -> 次手番石）に沿って順次確定
        - 3個以上の場合：前後2手（最初と最後）を必ず ambiguous=True とし、全石を順次付番
        """
        added_list = list(self.pending_added_stones)
        count = len(added_list)
        self._clear_pending()

        if count == 0:
            return

        if count == 1:
            r, c, col = added_list[0]
            amb = (col != self._next_turn_color)
            self._commit_single_move(r, c, col, ambiguous=amb)
            return

        if count == 2:
            # 手番の石 -> 次の手番の石 の順に1手ずつ確定
            for r, c, col in added_list:
                self._commit_single_move(r, c, col, ambiguous=False)
            return

        for idx, (r, c, col) in enumerate(added_list):
            is_amb = (idx == 0) or (idx == count - 1)
            self._commit_single_move(r, c, col, ambiguous=is_amb)

    def initialize_board(self, initial_board: List[List[int]], next_turn_color: int = 1):
        """初期設定完了時に確定済み基準盤面と次手番をセットする。"""
        self.current_board_state = [row[:] for row in initial_board]
        self._next_turn_color = next_turn_color if next_turn_color in (1, 2) else 1
        self.black_captures = 0
        self.white_captures = 0
        self.move_history.clear()
        self._clear_pending()
        self.turn_updated.emit(self._next_turn_color)

    def start_loop(self):
        self.is_running = True
        self.is_processing = True
        self.current_state = "RUNNING"
        self.state_changed.emit(self.current_state)
        turn_label = "黒番" if self._next_turn_color == 1 else "白番"
        print(f"[GameLoopManager] ★ Game Loop が正式に開始されました（初期次手番: {turn_label}）。")

    def stop_loop(self):
        self.is_running = False
        self.is_processing = False
        self.current_state = "STOPPED"
        self.state_changed.emit(self.current_state)
        print("[GameLoopManager] Game Loop が停止しました。")

    def get_ambiguous_moves(self) -> List[Dict[str, Any]]:
        """後から AMBIGUOUS 属性が付与された着手レコードを抽出して返す。"""
        return [dict(rec) for rec in self.move_history if rec.get("ambiguous") is True]

    def _report_invalid_change(self, reason: str, added_coords: List[Tuple[int, int]], removed_coords: List[Tuple[int, int]]):
        """不正な盤面変化をログ出力し、画像保存等の通知シグナルを送出する。"""
        print(
            f"[Debug GLM] ⚠️ 不正な石変化のためCNN判定を破棄: {reason} "
            f"added_coords={added_coords}, removed_coords={removed_coords}"
        )
        self.invalid_move_detected.emit(reason, added_coords, removed_coords)

    def _advance_pending(self, candidate_added: List[Tuple[int, int, int]], candidate_removed: List[Tuple[int, int, int]]):
        """候補石リストをもとに pending_1 -> pending_2 -> 確定 を進める共通処理。"""
        if self.pending_stage == 0:
            self.pending_stage = 1
            self.pending_added_stones = list(candidate_added)
            self.pending_removed_stones = list(candidate_removed)
            print(
                f"[Debug GLM] pending_1 (石数={len(self.pending_added_stones)}, "
                f"追加={self.pending_added_stones}, 減少相手石={self.pending_removed_stones})"
            )
            return

        prev_added_set = set(self.pending_added_stones)
        curr_added_set = set(candidate_added)

        if not prev_added_set.issubset(curr_added_set):
            self._clear_pending()
            print("[Debug GLM] 前回pendingが消滅したためクリア（本フレーム破棄）")
            return

        extra_added = sorted(list(curr_added_set - prev_added_set))
        if len(extra_added) > 0:
            if self.pending_stage >= 2:
                print(f"[Debug GLM] pending_{self.pending_stage} 確定と同時に新規追加石 {extra_added} を検知")
                self._commit_pending_candidate()
                self.pending_stage = 1
                self.pending_added_stones = list(candidate_added)
                self.pending_removed_stones = list(candidate_removed)
                print(f"[Debug GLM] 引き継ぎ新規 pending_1: {self.pending_added_stones}")
            else:
                print("[Debug GLM] 単発(pending_1)のまま次変化が来たため pending をクリアして破棄")
                self._clear_pending()
            return

        self.pending_stage += 1
        print(f"[Debug GLM] pending_{self.pending_stage} (継続)")

        if self.pending_stage >= self.required_consecutive_frames:
            self._commit_pending_candidate()

    def process_board_matrix(self, board_matrix: List[List[int]]):
        """
        1000x1000画像からCNN推論済みの 19x19 盤面マトリックスを受け取り、
        次の手番の石の増加（1個）を軸に妥当な盤面変化のみを pending_1 -> pending_2 -> 確定 へ進める。
        例外として、手番の石が1個かつ次の手番の石が1個同時に増えている場合は、
        まず手番の石を処理し、次にその次の手番の石を処理する（pending 段階を経て確定）。
        """
        if not self.is_running or board_matrix is None:
            print(f"[Debug GLM] 早期リターン: is_running={self.is_running}, board_matrix={board_matrix is not None}")
            return

        clean_matrix = [
            [int(val.value) if hasattr(val, "value") else (int(val) if val is not None else 0) for val in row]
            for row in board_matrix
        ]

        added_from_base, removed_from_base, flipped_from_base = self._diff_from_base(
            self.current_board_state, clean_matrix
        )

        if not added_from_base and not removed_from_base and not flipped_from_base:
            if self.pending_stage != 0:
                print("[Debug GLM] 基準盤面と同一に戻ったため pending 候補を消滅")
                self._clear_pending()
            print(f"[Debug GLM] NO_CHANGE (次手番:{self._next_turn_color})")
            return

        if flipped_from_base:
            flipped_coords = [(r, c) for (r, c, _, _) in flipped_from_base]
            self._report_invalid_change("既存石の色反転", flipped_coords, [])
            return

        turn_color = self._next_turn_color
        opp_color = 2 if turn_color == 1 else 1

        added_turn = [(r, c, col) for (r, c, col) in added_from_base if col == turn_color]
        added_opp = [(r, c, col) for (r, c, col) in added_from_base if col == opp_color]
        removed_turn = [(r, c, col) for (r, c, col) in removed_from_base if col == turn_color]
        removed_opp = [(r, c, col) for (r, c, col) in removed_from_base if col == opp_color]

        # 例外事象: 手番の石1個＋次の手番の石1個が同時に増えている場合
        # まず手番の石（added_turn）、次にその次の手番の石（added_opp）の順で pending 処理する
        is_two_step_exception = (
            len(added_turn) == 1
            and len(added_opp) == 1
            and len(removed_turn) == 0
        )

        if is_two_step_exception:
            candidate_added = sorted(added_turn) + sorted(added_opp)
            self._advance_pending(candidate_added, sorted(removed_opp))
            return

        if len(added_opp) > 0 or len(removed_turn) > 0:
            opp_coords = [(r, c) for (r, c, _) in added_opp]
            rem_turn_coords = [(r, c) for (r, c, _) in removed_turn]
            self._report_invalid_change(
                f"turn={turn_color}, opp={opp_color}, added_opp={len(added_opp)}, removed_turn={len(removed_turn)}",
                opp_coords,
                rem_turn_coords,
            )
            return

        if len(added_turn) >= 2:
            turn_coords = [(r, c) for (r, c, _) in added_turn]
            self._report_invalid_change(f"added_turn_multi={len(added_turn)}", turn_coords, [])
            return

        if len(added_turn) == 0:
            print(f"[Debug GLM] 次手番の増加なし変化を破棄 (removed_opp={removed_opp})")
            return

        self._advance_pending(sorted(added_turn), sorted(removed_opp))

    def process_frame(self, frame_bgr, corners):
        if not self.is_running or not self.inference_engine or frame_bgr is None:
            return
        try:
            h, w = frame_bgr.shape[:2]
            geometry_grid = self.inference_engine.create_arithmetic_grid(float(w), float(h))
            detected_board_matrix, _ = self.inference_engine.predict_stones(frame_bgr, geometry_grid)
            if detected_board_matrix is not None:
                self.process_board_matrix(detected_board_matrix)
        except Exception as e:
            print(f"[GameLoopManager] ⚠️ process_frame エラー例外: {e}")

    def reset_state(self):
        self.is_processing = False
        self.current_state = "IDLE"
        self.is_running = False
        self.current_board_state = [[0 for _ in range(self.board_size)] for _ in range(self.board_size)]
        self._next_turn_color = 1
        self.black_captures = 0
        self.white_captures = 0
        self.move_history.clear()
        self._clear_pending()
        self.state_changed.emit(self.current_state)
        self.turn_updated.emit(self._next_turn_color)