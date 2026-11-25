"""
ファイル名: goban_recorder/config.py
説明: アプリケーション全体のデバッグ設定・保存フラグの一元管理ファイル
"""

class DebugConfig:
    # 🎛 361分割パッチのディスク保存を制御するフラグ
    # - False: 361分割パッチの保存を行いません
    # - True: "debug_patches/" への361分割パッチ保存を有効にします
    ENABLE_DEBUG_SAVE = False

    # 🎛 受信した 1000x1000 矩形化画像（判定ラベル付き）のディスク保存を制御するフラグ
    # - False: 1000x1000 画像のデバッグ保存を行いません
    # - True: "debug_rectified_1000/" への保存を有効にします
    SAVE_RECTIFIED_DEBUG = False
    