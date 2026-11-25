"""
ファイル名: goban_recorder/export/sgf_writer.py
説明: 盤面の初期配置・着手履歴・終局結果からSGF文字列を生成し、
      連番の途中保存およびユーザー指定パスの最終SGF保存を行う。
"""

from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional


class SgfWriter:
    def __init__(self, segment_dir: Optional[Path] = None):
        if segment_dir is not None:
            self.segment_dir = Path(segment_dir)
        else:
            self.segment_dir = Path.home() / "Downloads" / "SgfFiles" / "segments"

    def _sanitize_sgf_text(self, text: str) -> str:
        """ユーザー入力の文字をエスケープ・クレンジングする"""
        if not text:
            return ""
        return text.replace("[", "(").replace("]", ")")

    def generate_sgf_string(
        self,
        board_layout: list,
        board_size: int = 19,
        komi: float = 6.5,
        handicap: int = 0,
        black_player: str = "黒番",
        white_player: str = "白番",
        next_player: str = "B",
        moves: Optional[List[Dict[str, Any]]] = None,
        result: Optional[str] = None,
        include_initial_stones: bool = True,
    ) -> str:
        """
        盤面レイアウト（19x19の二次元配列/リスト）および着手履歴からSGF形式の文字列を生成する
        board_layout の値: 0 = EMPTY, 1 = BLACK, 2 = WHITE (または StoneColor 列挙型)
        moves の要素例: {"row": r, "col": c, "color": 1 or 2 (または "B"/"W"), "ambiguous": bool}
        """
        sb = []

        # SGFヘッダーの生成
        sb.append(f"(;GM[1]FF[4]CA[UTF-8]AP[GobanRecorder:1.0]SZ[{board_size}]")

        if komi != 0.0:
            sb.append(f"KM[{komi}]")
        if handicap > 0:
            sb.append(f"HA[{handicap}]")
        if result:
            sb.append(f"RE[{self._sanitize_sgf_text(result)}]")

        if black_player:
            sb.append(f"PB[{self._sanitize_sgf_text(black_player)}]")
        if white_player:
            sb.append(f"PW[{self._sanitize_sgf_text(white_player)}]")

        if next_player:
            sb.append(f"PL[{next_player}]")

        current_date = datetime.now().strftime("%Y-%m-%d")
        sb.append(f"DT[{current_date}]")

        # 初期配置（黒石AB / 白石AW）の書き出し
        if include_initial_stones and board_layout is not None:
            black_stones = []
            white_stones = []

            for r in range(board_size):
                for c in range(board_size):
                    val = board_layout[r][c]
                    val_num = val.value if hasattr(val, "value") else val

                    if val_num == 1:
                        black_stones.append((c, r))
                    elif val_num == 2:
                        white_stones.append((c, r))

            if black_stones:
                sb.append("AB")
                for x, y in black_stones:
                    sgf_coord = self._convert_to_sgf_coordinate(x, y)
                    sb.append(f"[{sgf_coord}]")

            if white_stones:
                sb.append("AW")
                for x, y in white_stones:
                    sgf_coord = self._convert_to_sgf_coordinate(x, y)
                    sb.append(f"[{sgf_coord}]")

        # 確定着手手順の書き出し
        if moves:
            for mv in moves:
                row = mv.get("row")
                col = mv.get("col")
                if row is None or col is None:
                    continue
                if not (0 <= col < board_size and 0 <= row < board_size):
                    continue

                raw_color = mv.get("color")
                if raw_color in (1, "B", "b"):
                    color_tag = "B"
                elif raw_color in (2, "W", "w"):
                    color_tag = "W"
                else:
                    continue

                sgf_coord = self._convert_to_sgf_coordinate(col, row)
                if mv.get("ambiguous"):
                    sb.append(f";{color_tag}[{sgf_coord}]C[AMBIGUOUS]")
                else:
                    sb.append(f";{color_tag}[{sgf_coord}]")

        sb.append(")")
        return "".join(sb)

    def _convert_to_sgf_coordinate(self, x: int, y: int) -> str:
        """列・行インデックス（0〜18）をSGF座標（a〜s）に変換"""
        x_char = chr(ord('a') + x)
        y_char = chr(ord('a') + y)
        return f"{x_char}{y_char}"

    def save_sgf_file(self, sgf_content: str, file_name: str | None = None) -> Path:
        """
        SGFファイルを Download/SgfFiles フォルダに保存する
        """
        downloads_dir = Path.home() / "Downloads"
        target_dir = downloads_dir / "SgfFiles"
        target_dir.mkdir(parents=True, exist_ok=True)

        if not file_name:
            current_str = datetime.now().strftime("%Y%m%d-%H%M%S")
            file_name = f"GobanRecorder-{current_str}.sgf"

        target_file = target_dir / file_name
        target_file.write_text(sgf_content, encoding="utf-8")

        print(f"[SgfWriter] SGFファイルを保存しました: {target_file}")
        return target_file

    def save_next_segment_sgf(self, sgf_content: str, target_dir: Optional[Path] = None) -> Path:
        """
        あらかじめ決められたフォルダに seg_01.sgf, seg_02.sgf ... の連番で途中棋譜を保存する。
        """
        save_dir = Path(target_dir) if target_dir is not None else self.segment_dir
        save_dir.mkdir(parents=True, exist_ok=True)

        seq = 1
        while True:
            candidate = save_dir / f"seg_{seq:02d}.sgf"
            if not candidate.exists():
                target_file = candidate
                break
            seq += 1

        target_file.write_text(sgf_content, encoding="utf-8")
        print(f"[SgfWriter] 途中棋譜（連番）を保存しました: {target_file}")
        return target_file

    def save_sgf_to_path(self, sgf_content: str, file_path: str | Path) -> Path:
        """
        ユーザーが指定したパスへ最終SGFファイルを保存する。
        """
        target_file = Path(file_path)
        if target_file.suffix.lower() != ".sgf":
            target_file = target_file.with_suffix(".sgf")
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text(sgf_content, encoding="utf-8")
        print(f"[SgfWriter] 最終SGFファイルを保存しました: {target_file}")
        return target_file
    