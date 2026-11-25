"""
ファイル名: goban_recorder/network/receiver_server.py
説明: HTTP受信用バックグラウンドサーバー（Ready信号・送信元IP自動キャプチャ・画像データ受信対応版）
"""

import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from PySide6.QtCore import Signal, QObject

class ServerSignals(QObject):
    log_message = Signal(str)
    enable_start_btn = Signal(bool)          # Ready信号受信用シグナル
    ready_client_ip = Signal(str)            # ★ Ready信号の送信元IP通知用シグナル
    data_received = Signal(bytes, bytes)     # jpeg_data, png_data

class HttpReceiveHandler(BaseHTTPRequestHandler):
    signals = None

    def do_POST(self):
        # 1. Android側からの Ready 信号を受け付けるエンドポイント
        if self.path == '/ready':
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                if content_length > 0:
                    self.rfile.read(content_length)

                # 接続元のクライアントIPアドレスを取得 (例: "192.168.40.202" や "127.0.0.1")
                client_ip = self.client_address[0] if self.client_address else "127.0.0.1"

                if self.signals:
                    self.signals.log_message.emit(f"スマホ ({client_ip}) から Ready 信号を受信しました！")
                    self.signals.enable_start_btn.emit(True)
                    self.signals.ready_client_ip.emit(client_ip)  # ★ IPアドレスをUI側に渡す

                self.send_response(200)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.end_headers()
                self.wfile.write(b"READY_ACK")

            except Exception as e:
                self.send_response(500)
                self.end_headers()
                if self.signals:
                    self.signals.log_message.emit(f"Ready信号処理エラー: {str(e)}")

        # 2. スマホからの画像データ（1000x1000画像等）を受け取るエンドポイント
        elif self.path == '/upload' or self.path == '/frame':
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body_data = self.rfile.read(content_length) if content_length > 0 else b""

                if self.signals and len(body_data) > 0:
                    self.signals.log_message.emit(f"スマホから画像データを受信しました (サイズ: {len(body_data)} bytes)")
                    
                    jpeg_data = body_data
                    png_data = body_data
                    
                    self.signals.data_received.emit(jpeg_data, png_data)

                self.send_response(200)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.end_headers()
                self.wfile.write(b"UPLOAD_OK")

            except Exception as e:
                self.send_response(500)
                self.end_headers()
                if self.signals:
                    self.signals.log_message.emit(f"画像データ受信エラー: {str(e)}")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


class ReceiverServerManager:
    def __init__(self, port=8080):
        self.port = port
        self.signals = ServerSignals()
        self.server_thread = None
        self.server = None

    def start_server(self):
        HttpReceiveHandler.signals = self.signals
        def run():
            try:
                self.server = HTTPServer(('0.0.0.0', self.port), HttpReceiveHandler)
                self.signals.log_message.emit(f"HTTPサーバーがポート {self.port} で起動しました。")
                self.server.serve_forever()
            except Exception as e:
                self.signals.log_message.emit(f"サーバー起動エラー: {str(e)}")

        self.server_thread = threading.Thread(target=run, daemon=True)
        self.server_thread.start()
        