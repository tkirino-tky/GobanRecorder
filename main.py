"""
ファイル名: main.py
説明: GobanRecorderアプリケーションのエントリポイント
"""

import sys
from PySide6.QtWidgets import QApplication
from goban_recorder.ui.main_window import MainWindow
from goban_recorder.controllers.app_controller import AppController

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    controller = AppController(window)
    window.set_controller(controller)
    window.show()
    sys.exit(app.exec())
    