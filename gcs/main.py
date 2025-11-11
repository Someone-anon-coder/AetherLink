import asyncio
import websockets
import json
import base64
import cv2
import numpy as np
from ultralytics import YOLO
import customtkinter
from PIL import Image, ImageTk
import threading
import queue

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
        self.video_for_gui_queue = queue.Queue()
        self.telemetry_for_gui_queue = queue.Queue()
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
                                self.video_for_gui_queue.put_nowait(image)
                                await self.detections_for_mission_logic_queue.put(detections)
                        elif data['type'] == 'telemetry':
                            payload = data.get('payload')
                            print(f"DEBUG: Received TELEMETRY packet: {payload}")
                            self.telemetry_for_gui_queue.put_nowait(payload)
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

class Dashboard(customtkinter.CTk):
    def __init__(self, video_queue, telemetry_queue):
        super().__init__()

        self.video_queue = video_queue
        self.telemetry_queue = telemetry_queue

        self.title("AetherLink GCS")
        self.geometry("1280x720")

        self.grid_columnconfigure(0, weight=4)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Video Frame
        self.video_label = customtkinter.CTkLabel(self, text="Waiting for video feed...")
        self.video_label.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        # Data Frame
        self.data_frame = customtkinter.CTkFrame(self)
        self.data_frame.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        self.data_frame.grid_columnconfigure(0, weight=1)

        # Telemetry
        self.telemetry_label = customtkinter.CTkLabel(self.data_frame, text="Telemetry", font=customtkinter.CTkFont(size=20, weight="bold"))
        self.telemetry_label.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.lat_label = customtkinter.CTkLabel(self.data_frame, text="Lat: N/A")
        self.lat_label.grid(row=1, column=0, padx=10, pady=2, sticky="w")
        self.lon_label = customtkinter.CTkLabel(self.data_frame, text="Lon: N/A")
        self.lon_label.grid(row=2, column=0, padx=10, pady=2, sticky="w")
        self.alt_label = customtkinter.CTkLabel(self.data_frame, text="Alt: N/A")
        self.alt_label.grid(row=3, column=0, padx=10, pady=2, sticky="w")
        self.v_ground_label = customtkinter.CTkLabel(self.data_frame, text="V Gnd: N/A")
        self.v_ground_label.grid(row=4, column=0, padx=10, pady=2, sticky="w")
        self.heading_label = customtkinter.CTkLabel(self.data_frame, text="Heading: N/A")
        self.heading_label.grid(row=5, column=0, padx=10, pady=2, sticky="w")

        # Mission State
        self.mission_state_label = customtkinter.CTkLabel(self.data_frame, text="Mission State", font=customtkinter.CTkFont(size=20, weight="bold"))
        self.mission_state_label.grid(row=6, column=0, padx=10, pady=(20, 10), sticky="ew")
        self.current_state_label = customtkinter.CTkLabel(self.data_frame, text="STANDBY", text_color="yellow", font=customtkinter.CTkFont(size=16))
        self.current_state_label.grid(row=7, column=0, padx=10, pady=2, sticky="ew")

        self.update_widgets()

    def update_widgets(self):
        # Update telemetry
        try:
            telemetry = self.telemetry_queue.get_nowait()
            self.lat_label.configure(text=f"Lat: {telemetry.get('lat', 'N/A'):.6f}")
            self.lon_label.configure(text=f"Lon: {telemetry.get('lon', 'N/A'):.6f}")
            self.alt_label.configure(text=f"Alt: {telemetry.get('alt', 'N/A'):.2f} m")
            self.v_ground_label.configure(text=f"V Gnd: {telemetry.get('v_ground', 'N/A'):.2f} m/s")
            self.heading_label.configure(text=f"Heading: {telemetry.get('heading', 'N/A'):.2f}°")
        except queue.Empty:
            pass

        # Update video
        try:
            frame = self.video_queue.get_nowait()
            if frame is not None:
                img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(img)
                ctk_image = customtkinter.CTkImage(light_image=img, dark_image=img, size=(960, 540))
                self.video_label.configure(image=ctk_image, text="")
        except queue.Empty:
            pass

        self.after(33, self.update_widgets)

def run_gui(video_queue, telemetry_queue):
    app = Dashboard(video_queue, telemetry_queue)
    app.mainloop()

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

    gui_thread = threading.Thread(
        target=run_gui,
        args=(app.video_for_gui_queue, app.telemetry_for_gui_queue),
        daemon=True
    )
    gui_thread.start()

    await asyncio.gather(
        app.start_server(),
        mission_logic_detections_consumer(app),
        mission_logic_telemetry_consumer(app)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("INFO: Shutting down GCS application.")
