"""
ファイル名: goban_recorder/camera/camera_service.py
説明: カメラサービスおよびストリーム/ポーリング受容ワーカー（デバッグログ追加版）
"""

import socket
import time
import urllib.request
import cv2
import numpy as np
from PySide6.QtCore import QObject, QThread, Signal, Slot


class CameraWorker(QObject):
    """
    IP Webcam の /video ストリーム、または /photo.jpg / /shot.jpg の単発ポーリングを行うワーカー。
    """

    frame_received = Signal(object)
    finished = Signal()

    def __init__(self, camera_source):
        super().__init__()
        src = str(camera_source).strip()
        self.camera_source = src
        self.is_running = False

    @Slot()
    def start_work(self):
        self.is_running = True
        is_polling = self.camera_source.endswith("/photo.jpg") or self.camera_source.endswith("/shot.jpg")

        if is_polling:
            print(f"[CameraWorker] 静止画ポーリング受容を開始します: {self.camera_source}")
            poll_interval = 0.2
            while self.is_running:
                try:
                    print(f"[Debug] 1. urlopen 呼び出し開始...")
                    req = urllib.request.Request(
                        self.camera_source, 
                        headers={'User-Agent': 'Mozilla/5.0'}
                    )
                    with urllib.request.urlopen(req, timeout=3.0) as response:
                        print(f"[Debug] 2. response 取得成功。bytes読み込み開始...")
                        img_bytes = response.read()
                    
                    print(f"[Debug] 3. 読み込み完了 (サイズ: {len(img_bytes)} bytes)")
                    if img_bytes:
                        img_np = np.frombuffer(img_bytes, dtype=np.uint8)
                        frame = cv2.imdecode(img_np, cv2.IMREAD_COLOR)

                        if frame is not None and self.is_running:
                            print(f"[Debug] 4. 画像デコード＆回転処理開始...")
                            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
                            self.frame_received.emit(frame)
                            print(f"[Debug] 5. frame_received シグナル送信完了！")
                        else:
                            print(f"[Debug] ⚠️ フレームがNoneです")

                except Exception as e:
                    if self.is_running:
                        print(f"[CameraWorker] ⚠️ ポーリング例外発生: {e}")

                time.sleep(poll_interval)
        else:
            print(f"[CameraWorker] MJPEGストリーム受容を開始します: {self.camera_source}")
            while self.is_running:
                try:
                    stream = urllib.request.urlopen(self.camera_source, timeout=5.0)
                    bytes_buffer = bytearray()
                    first_frame = True

                    while self.is_running:
                        try:
                            chunk = stream.read(4096)
                            if not chunk:
                                break
                            bytes_buffer.extend(chunk)
                        except (socket.timeout, TimeoutError):
                            print("[CameraWorker] ⚠️ ストリーム読み込みタイムアウト。再接続を試みます...")
                            break

                        a = bytes_buffer.find(b"\xff\xd8")
                        b = bytes_buffer.find(b"\xff\xd9")

                        if a != -1 and b != -1 and a < b:
                            jpg = bytes_buffer[a : b + 2]
                            bytes_buffer = bytes_buffer[b + 2 :]

                            img_np = np.frombuffer(jpg, dtype=np.uint8)
                            frame = cv2.imdecode(img_np, cv2.IMREAD_COLOR)

                            if frame is not None and self.is_running:
                                frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
                                if first_frame:
                                    print("[CameraWorker] ★MJPEGストリームの受信・解凍に成功しました！")
                                    first_frame = False
                                self.frame_received.emit(frame)

                    try:
                        stream.close()
                    except Exception:
                        pass

                except Exception as e:
                    if self.is_running:
                        print(f"[CameraWorker] ネットワーク通信例外 ({e})。1秒後に再試行します...")
                        time.sleep(1.0)

        print("[CameraWorker] キャプチャスレッドが正常終了しました。")
        self.finished.emit()

    def stop(self):
        self.is_running = False


class CameraService(QObject):
    """常駐型カメラサービスインターフェース"""

    frame_received = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread = None
        self.worker = None
        self.current_source = ""

    def set_source_and_start(self, camera_source: str):
        src = str(camera_source).strip()

        if self.current_source == src and self.is_running():
            print("[CameraService] 既に同じカメラソースで動作中です。")
            return

        self.stop()

        self.current_source = src
        self.thread = QThread()
        self.worker = CameraWorker(src)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.start_work)
        self.worker.frame_received.connect(self.frame_received)

        self.thread.start()
        print(f"[CameraService] カメラサービスを開始しました: {src}")

    def stop(self):
        if self.worker:
            self.worker.stop()
            self.worker = None

        if self.thread and self.thread.isRunning():
            self.thread.quit()
            self.thread.wait(500)
            self.thread = None

        self.current_source = ""

    def is_running(self):
        return self.thread is not None and self.thread.isRunning()
    