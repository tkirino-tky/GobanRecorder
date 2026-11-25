"""
ファイル名: goban_recorder/utils/corner_utils.py
説明: GeometryUtils.kt (CornerUtils) の完全直訳移植クラス
"""

class CornerUtils:
    @staticmethod
    def calculate_expanded_corners_60(corners: list[tuple[float, float]]) -> list[tuple[float, float]]:
        """
        60x60pxパッチ用：各辺の1/24（0.75マス分）外側に拡張した新しい4隅の座標を計算
        GeometryUtils.kt / CornerUtils.kt の calculateExpandedCorners60 を完全直訳
        """
        return CornerUtils.calculate_expanded_corners_by_ratio(corners, 24.0)

    @staticmethod
    def calculate_expanded_corners_by_ratio(corners: list[tuple[float, float]], ratio_denominator: float) -> list[tuple[float, float]]:
        if len(corners) != 4 or ratio_denominator == 0.0:
            return corners

        ratio = 1.0 / ratio_denominator

        p0 = corners[0]  # Top-Left
        p1 = corners[1]  # Top-Right
        p2 = corners[2]  # Bottom-Right
        p3 = corners[3]  # Bottom-Left

        new_tl = (
            p0[0] - (p1[0] - p0[0]) * ratio - (p3[0] - p0[0]) * ratio,
            p0[1] - (p1[1] - p0[1]) * ratio - (p3[1] - p0[1]) * ratio
        )
        new_tr = (
            p1[0] + (p1[0] - p0[0]) * ratio - (p2[0] - p1[0]) * ratio,
            p1[1] + (p1[1] - p0[1]) * ratio - (p2[1] - p1[1]) * ratio
        )
        new_br = (
            p2[0] + (p2[0] - p3[0]) * ratio + (p2[0] - p1[0]) * ratio,
            p2[1] + (p2[1] - p3[0]) * ratio + (p2[1] - p1[1]) * ratio
        )
        new_bl = (
            p3[0] - (p2[0] - p3[0]) * ratio + (p3[0] - p0[0]) * ratio,
            p3[1] - (p2[0] - p3[0]) * ratio + (p3[1] - p0[0]) * ratio
        )

        return [new_tl, new_tr, new_br, new_bl]
    