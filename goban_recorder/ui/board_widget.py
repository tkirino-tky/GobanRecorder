import sys
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import QWidget

from goban_recorder.models.game_state import BoardCoordinateStyle


class BoardWidget(QWidget):
    # クリックされた座標 (col, row) を外部に伝えるシグナル
    intersection_clicked = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.coord_style = BoardCoordinateStyle.NONE
        self.grid_size = 19
        
        # 盤面状態 (0: 空, 1: 黒, 2: 白)
        self.board_state = [[0] * self.grid_size for _ in range(self.grid_size)]
        self.last_move = None  # (col, row) 最新手

        # 最小サイズ設定
        self.setMinimumSize(400, 400)

    def set_coordinate_style(self, style: BoardCoordinateStyle):
        """座標スタイルの変更"""
        self.coord_style = style
        self.update()

    def clear_board(self):
        """盤面クリア"""
        self.board_state = [[0] * self.grid_size for _ in range(self.grid_size)]
        self.last_move = None
        self.update()

    def set_stone(self, col: int, row: int, color: int):
        """碁石の配置 (col: 0~18, row: 0~18, color: 1=黒, 2=白)"""
        if 0 <= col < self.grid_size and 0 <= row < self.grid_size:
            self.board_state[row][col] = color
            self.last_move = (col, row)
            self.update()

    def mousePressEvent(self, event):
        """碁盤がクリックされたとき、ピクセル座標から19x19の交点(col, row)を逆算する"""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            x, y = pos.x(), pos.y()

            # paintEvent と同じジオメトリ計算を再現して逆算
            has_coords = self.coord_style != BoardCoordinateStyle.NONE
            margin_left = 36 if has_coords else 20
            margin_top = 36 if has_coords else 20
            margin_right = 20
            margin_bottom = 20

            avail_w = self.width() - (margin_left + margin_right)
            avail_h = self.height() - (margin_top + margin_bottom)
            board_side = min(avail_w, avail_h)

            if board_side <= 0:
                return

            board_left = margin_left + (avail_w - board_side) / 2
            board_top = margin_top + (avail_h - board_side) / 2

            cell_size = board_side / self.grid_size
            cell_offset = cell_size / 2.0

            # 盤面エリア内かどうかの判定
            board_right = board_left + board_side
            board_bottom = board_top + board_side

            if board_left <= x <= board_right and board_top <= y <= board_bottom:
                # 最も近い交点のインデックス (0 ~ 18) を計算
                col = round((x - board_left - cell_offset) / cell_size)
                row = round((y - board_top - cell_offset) / cell_size)

                if 0 <= col < self.grid_size and 0 <= row < self.grid_size:
                    # 有効な交点ならシグナルを発火
                    self.intersection_clicked.emit(col, row)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # --------------------------------------------------
        # 1. 背景テクスチャ描画（プログラム生成）
        # --------------------------------------------------
        self._draw_background_texture(painter)

        # --------------------------------------------------
        # 2. ジオメトリ計算 (正方形の碁盤＋余白)
        # --------------------------------------------------
        has_coords = self.coord_style != BoardCoordinateStyle.NONE
        margin_left = 36 if has_coords else 20
        margin_top = 36 if has_coords else 20
        margin_right = 20
        margin_bottom = 20

        avail_w = self.width() - (margin_left + margin_right)
        avail_h = self.height() - (margin_top + margin_bottom)
        board_side = min(avail_w, avail_h)

        if board_side <= 0:
            return

        board_left = margin_left + (avail_w - board_side) / 2
        board_top = margin_top + (avail_h - board_side) / 2
        board_rect = QRectF(board_left, board_top, board_side, board_side)

        cell_size = board_side / self.grid_size
        cell_offset = cell_size / 2.0

        # --------------------------------------------------
        # 3. 碁盤（木目調本体）の描画
        # --------------------------------------------------
        painter.fillRect(board_rect, QColor(220, 178, 108))
        painter.setPen(QPen(QColor(80, 50, 20), 2))
        painter.drawRect(board_rect)

        # 格子線の描画
        painter.setPen(QPen(QColor(40, 30, 20), 1))
        for i in range(self.grid_size):
            x = board_left + cell_offset + i * cell_size
            painter.drawLine(x, board_top + cell_offset, x, board_top + board_side - cell_offset)
            y = board_top + cell_offset + i * cell_size
            painter.drawLine(board_left + cell_offset, y, board_left + board_side - cell_offset, y)

        # 星（星点）の描画
        star_indices = [3, 9, 15]
        painter.setBrush(QBrush(QColor(40, 30, 20)))
        star_radius = max(2.5, cell_size * 0.08)
        for row in star_indices:
            for col in star_indices:
                sx = board_left + cell_offset + col * cell_size
                sy = board_top + cell_offset + row * cell_size
                painter.drawEllipse(QRectF(sx - star_radius, sy - star_radius, star_radius * 2, star_radius * 2))

        # --------------------------------------------------
        # 4. 座標標記の描画（上側・左側のみ）
        # --------------------------------------------------
        if has_coords:
            self._draw_coordinates(painter, board_left, board_top, cell_size, cell_offset)

        # --------------------------------------------------
        # 5. 碁石の描画
        # --------------------------------------------------
        stone_radius = cell_size * 0.46
        font = QFont("Sans-serif", max(8, int(cell_size * 0.35)), QFont.Weight.Bold)
        painter.setFont(font)

        for r in range(self.grid_size):
            for c in range(self.grid_size):
                stone = self.board_state[r][c]
                if stone == 0:
                    continue

                cx = board_left + cell_offset + c * cell_size
                cy = board_top + cell_offset + r * cell_size
                stone_rect = QRectF(cx - stone_radius, cy - stone_radius, stone_radius * 2, stone_radius * 2)

                if stone == 1:  # 黒石
                    grad = QLinearGradient(stone_rect.topLeft(), stone_rect.bottomRight())
                    grad.setColorAt(0.0, QColor(70, 70, 70))
                    grad.setColorAt(1.0, QColor(10, 10, 10))
                    painter.setBrush(QBrush(grad))
                    painter.setPen(QPen(QColor(0, 0, 0), 1))
                    painter.drawEllipse(stone_rect)

                elif stone == 2:  # 白石
                    grad = QLinearGradient(stone_rect.topLeft(), stone_rect.bottomRight())
                    grad.setColorAt(0.0, QColor(255, 255, 255))
                    grad.setColorAt(1.0, QColor(210, 210, 210))
                    painter.setBrush(QBrush(grad))
                    painter.setPen(QPen(QColor(160, 160, 160), 1))
                    painter.drawEllipse(stone_rect)

                # 最新手の赤い印
                if self.last_move == (c, r):
                    painter.setPen(QPen(QColor(230, 50, 50), 2))
                    mark_r = stone_radius * 0.4
                    painter.drawEllipse(QRectF(cx - mark_r, cy - mark_r, mark_r * 2, mark_r * 2))

    def _draw_background_texture(self, painter: QPainter):
        w, h = self.width(), self.height()
        bg_grad = QLinearGradient(0, 0, w, h)
        bg_grad.setColorAt(0.0, QColor(32, 44, 62))
        bg_grad.setColorAt(1.0, QColor(18, 24, 36))
        painter.fillRect(0, 0, w, h, bg_grad)

        painter.save()
        painter.setPen(QPen(QColor(255, 255, 255, 8), 1))
        step = 4
        for x in range(0, w, step):
            painter.drawLine(x, 0, x, h)
        for y in range(0, h, step):
            painter.drawLine(0, y, w, y)
        painter.restore()

    def _draw_coordinates(self, painter: QPainter, board_left: float, board_top: float, cell_size: float, cell_offset: float):
        painter.save()
        painter.setPen(QColor(210, 220, 230))
        font = QFont("Sans-serif", max(8, int(cell_size * 0.32)), QFont.Weight.Bold)
        painter.setFont(font)

        kanji_nums = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
                      "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九"]

        for i in range(self.grid_size):
            if self.coord_style == BoardCoordinateStyle.KGS:
                col_char = chr(ord('A') + i + (1 if i >= 8 else 0))
                row_char = str(19 - i)
            else:
                col_char = str(i + 1)
                row_char = kanji_nums[i]

            cx = board_left + cell_offset + i * cell_size
            col_rect = QRectF(cx - cell_size / 2, board_top - cell_size, cell_size, cell_size)
            painter.drawText(col_rect, Qt.AlignmentFlag.AlignCenter, col_char)

            cy = board_top + cell_offset + i * cell_size
            row_rect = QRectF(board_left - cell_size, cy - cell_size / 2, cell_size, cell_size)
            painter.drawText(row_rect, Qt.AlignmentFlag.AlignCenter, row_char)

        painter.restore()
        