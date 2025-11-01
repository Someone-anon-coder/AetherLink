
import sys
import asyncio
import websockets
import json
import numpy as np
import cv2
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QGridLayout, QLabel, QGroupBox, QVBoxLayout, QListWidget
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtCore import QThread, pyqtSignal, QObject

class WebsocketClient(QObject):
    new_telemetry = pyqtSignal(dict)
    new_video_frame = pyqtSignal(np.ndarray)
    new_log = pyqtSignal(str)

    def __init__(self, uri):
        super().__init__()
        self.uri = uri

    def run(self):
        asyncio.run(self.connect_and_listen())

    async def connect_and_listen(self):
        async for websocket in websockets.connect(self.uri):
            try:
                async for message in websocket:
                    data = json.loads(message)
                    if data['type'] == 'telemetry':
                        self.new_telemetry.emit(data['data'])
                    elif data['type'] == 'video_frame':
                        # This assumes the video frame is received as a list/byte array
                        # that can be converted to a numpy array
                        frame_data = np.array(data['data'], dtype=np.uint8)
                        self.new_video_frame.emit(frame_data)
                    elif data['type'] == 'log':
                        self.new_log.emit(data['data'])
            except websockets.ConnectionClosed:
                continue

class DashboardApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Aetherlink Dashboard")
        self.setGeometry(100, 100, 1200, 800)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QGridLayout(self.central_widget)

        self._create_widgets()
        self._arrange_widgets()
        self._init_websocket_client()

    def _create_widgets(self):
        self.video_feed_label = QLabel("Waiting for video stream...")
        self.mission_status_label = QLabel("STATUS: STANDBY")

        self.telemetry_groupbox = QGroupBox("Telemetry")
        self.telemetry_layout = QGridLayout()
        self.telemetry_groupbox.setLayout(self.telemetry_layout)
        self.altitude_label = QLabel("Altitude:")
        self.altitude_value = QLabel("0.0 m")
        self.ground_speed_label = QLabel("Ground Speed:")
        self.ground_speed_value = QLabel("0.0 m/s")
        self.battery_label = QLabel("Battery:")
        self.battery_value = QLabel("N/A")
        self.gps_position_label = QLabel("GPS Position:")
        self.gps_position_value = QLabel("N/A")

        self.logged_objects_groupbox = QGroupBox("Logged Objects")
        self.logged_objects_layout = QVBoxLayout()
        self.logged_objects_groupbox.setLayout(self.logged_objects_layout)
        self.logged_objects_list = QListWidget()

    def _arrange_widgets(self):
        self.main_layout.addWidget(self.video_feed_label, 0, 0, 2, 1)
        self.main_layout.addWidget(self.mission_status_label, 0, 1)
        self.main_layout.addWidget(self.telemetry_groupbox, 1, 1)
        self.main_layout.addWidget(self.logged_objects_groupbox, 2, 0, 1, 2)

        # Arrange telemetry widgets
        self.telemetry_layout.addWidget(self.altitude_label, 0, 0)
        self.telemetry_layout.addWidget(self.altitude_value, 0, 1)
        self.telemetry_layout.addWidget(self.ground_speed_label, 1, 0)
        self.telemetry_layout.addWidget(self.ground_speed_value, 1, 1)
        self.telemetry_layout.addWidget(self.battery_label, 2, 0)
        self.telemetry_layout.addWidget(self.battery_value, 2, 1)
        self.telemetry_layout.addWidget(self.gps_position_label, 3, 0)
        self.telemetry_layout.addWidget(self.gps_position_value, 3, 1)

        # Arrange logged objects
        self.logged_objects_layout.addWidget(self.logged_objects_list)

    def _init_websocket_client(self):
        # The URI should point to your comms_hub WebSocket server
        self.websocket_client = WebsocketClient("ws://localhost:8765")
        self.websocket_thread = QThread()
        self.websocket_client.moveToThread(self.websocket_thread)

        self.websocket_thread.started.connect(self.websocket_client.run)
        self.websocket_client.new_telemetry.connect(self.update_telemetry_display)
        self.websocket_client.new_video_frame.connect(self.update_video_feed)
        self.websocket_client.new_log.connect(self.add_log_entry)

        self.websocket_thread.start()

    def update_telemetry_display(self, telemetry_data):
        self.altitude_value.setText(f"{telemetry_data.get('altitude', 0.0):.2f} m")
        self.ground_speed_value.setText(f"{telemetry_data.get('ground_speed', 0.0):.2f} m/s")
        # Add battery and GPS updates when available

    def update_video_feed(self, frame):
        # Assuming frame is a numpy array (OpenCV format)
        height, width, channel = frame.shape
        bytes_per_line = 3 * width
        q_image = QImage(frame.data, width, height, bytes_per_line, QImage.Format.Format_RGB888).rgbSwapped()
        self.video_feed_label.setPixmap(QPixmap.fromImage(q_image))

    def add_log_entry(self, log_message):
        self.logged_objects_list.addItem(log_message)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    dashboard = DashboardApp()
    dashboard.show()
    sys.exit(app.exec())
