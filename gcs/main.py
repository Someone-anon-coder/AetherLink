import asyncio
import websockets
import json
import base64
import cv2
import numpy as np
from ultralytics import YOLO

class DataProcessor:
    def __init__(self):
        self.model = YOLO('best.pt')
        print("INFO: YOLO model loaded.")

    async def process_video_packet(self, video_payload):
        try:
            img_bytes = base64.b64decode(video_payload)
            np_arr = np.frombuffer(img_bytes, np.uint8)
            image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

            if image is None:
                print("WARN: Failed to decode image.")
                return None, []

            results = self.model(image, verbose=False)

            detections = []
            for result in results:
                for box in result.boxes:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    confidence = float(box.conf[0])
                    class_id = int(box.cls[0])
                    class_name = self.model.names[class_id]
                    detections.append({
                        "class_name": class_name,
                        "confidence": confidence,
                        "box": [x1, y1, x2, y2]
                    })

            print(f"DEBUG: Processed video frame, found {len(detections)} detections.")
            return image, detections
        except Exception as e:
            print(f"ERROR: Error processing video packet: {e}")
            return None, []

class GCSApp:
    def __init__(self):
        self.data_processor = DataProcessor()
        self.video_for_gui_queue = asyncio.Queue()
        self.telemetry_for_gui_queue = asyncio.Queue()
        self.detections_for_mission_logic_queue = asyncio.Queue()
        self.telemetry_for_mission_logic_queue = asyncio.Queue()

    async def websocket_handler(self, websocket):
        print(f"INFO: Onboard system connected from {websocket.remote_address}")
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    if 'type' in data:
                        if data['type'] == 'video':
                            payload = data.get('payload', '')
                            print(f"DEBUG: Received VIDEO packet, payload size: {len(payload)} bytes")
                            image, detections = await self.data_processor.process_video_packet(payload)
                            if image is not None:
                                await self.video_for_gui_queue.put(image)
                                await self.detections_for_mission_logic_queue.put(detections)
                        elif data['type'] == 'telemetry':
                            payload = data.get('payload')
                            print(f"DEBUG: Received TELEMETRY packet: {payload}")
                            await self.telemetry_for_gui_queue.put(payload)
                            await self.telemetry_for_mission_logic_queue.put(payload)
                        else:
                            print(f"WARN: Received unknown data type: {data['type']}")
                    else:
                        print(f"WARN: Received message without 'type' field: {data}")
                except json.JSONDecodeError:
                    print(f"WARN: Received non-JSON message: {message}")

        except websockets.ConnectionClosed as e:
            print(f"INFO: Connection with {websocket.remote_address} closed: {e}")
        finally:
            print(f"INFO: Onboard system {websocket.remote_address} disconnected.")

    async def start_server(self):
        HOST = "0.0.0.0"
        PORT = 8765
        async with websockets.serve(self.websocket_handler, HOST, PORT):
            print(f"INFO: GCS WebSocket server started on ws://{HOST}:{PORT}")
            await asyncio.Future()

async def gui_video_consumer(app):
    while True:
        frame = await app.video_for_gui_queue.get()
        print("GUI: Received new video frame for display.")

async def gui_telemetry_consumer(app):
    while True:
        telemetry = await app.telemetry_for_gui_queue.get()
        print(f"GUI: Received new telemetry data for display: {telemetry}")

async def mission_logic_detections_consumer(app):
    while True:
        detections = await app.detections_for_mission_logic_queue.get()
        print(f"MISSION_LOGIC: Received {len(detections)} detections.")

async def mission_logic_telemetry_consumer(app):
    while True:
        telemetry = await app.telemetry_for_mission_logic_queue.get()
        print(f"MISSION_LOGIC: Received telemetry: {telemetry}")

async def main():
    app = GCSApp()
    await asyncio.gather(
        app.start_server(),
        gui_video_consumer(app),
        gui_telemetry_consumer(app),
        mission_logic_detections_consumer(app),
        mission_logic_telemetry_consumer(app)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("INFO: Shutting down GCS application.")
