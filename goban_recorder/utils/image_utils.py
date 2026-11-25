"""
ファイル名: goban_recorder/utils/image_utils.py
説明: 画像クロップおよびカメラ映像上へのYOLO枠線・4隅ポイントの描画ユーティリティ
"""

import cv2
import numpy as np
from typing import List, Tuple, Optional


def crop_center_square(frame: np.ndarray) -> np.ndarray:
    """カメラの生画像（例: 1280x720 や 1920x1080）から中央の正方形領域を切り出す"""
    if frame is None:
        return None

    h, w = frame.shape[:2]
    min_dim = min(h, w)

    top = (h - min_dim) // 2
    left = (w - min_dim) // 2

    return frame[top : top + min_dim, left : left + min_dim].copy()


def draw_board_corners(
    frame_bgr: np.ndarray,
    corners: Optional[List[Tuple[float, float]]],
    color: Tuple[int, int, int] = (0, 255, 0),
    thickness: int = 4,
    corner_radius: int = 10,
) -> np.ndarray:
    """
    カメラ映像上にYOLOで検出された碁盤の4隅と境界外枠線を太く描画する (GobanReader同等スタイル)

    :param frame_bgr: 元のカメラ画像 (OpenCV Mat)
    :param corners: 4隅の座標リスト [(x1,y1), (x2,y2), (x3,y3), (x4,y4)]
    :param color: 線および点のカラー (BGR形式: デフォルトは明るい緑)
    :param thickness: 枠線の太さ (ピクセル)
    :param corner_radius: 4隅の塗りつぶし円の半径 (ピクセル)
    :return: 描画済みの画像フレーム
    """
    if frame_bgr is None:
        return None

    output_frame = frame_bgr.copy()

    if corners is None or len(corners) < 4:
        return output_frame

    # 4隅の座標を整数値に変換
    pts = np.array(corners, dtype=np.int32)

    # 1. 4隅を結ぶ太い外枠線を描画 (閉じた多角形)
    cv2.polylines(
        output_frame,
        [pts],
        isClosed=True,
        color=color,
        thickness=thickness,
        lineType=cv2.LINE_AA,
    )

    # 2. 4隅に大きめの塗りつぶし円を描画
    for pt in pts:
        center = (int(pt[0]), int(pt[1]))
        cv2.circle(
            output_frame,
            center=center,
            radius=corner_radius,
            color=color,
            thickness=-1,  # -1 で塗りつぶし
            lineType=cv2.LINE_AA,
        )

    return output_frame