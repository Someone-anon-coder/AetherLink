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
import socket
from mission_planner import MissionLogic

# --- CONFIGURATION ---
WEBSOCKET_PORT = 8765
VIDEO_PORT = 9999

class DataProcessor:
    def __init__(self):
        self.model = YOLO('best.pt')
        print("INFO: YOLO model loaded.")

    def process_video_frame(self, image):
        """Processes a single video frame for object detection."""
        if image is None:
            print("WARN: AI processor received an empty frame.")
            return None, []
        try:
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
            return image, detections
        except Exception as e:
            print(f"ERROR: Error processing video frame: {e}")
            return image, []

class GCSApp:
    def __init__(self):
        self.data_processor = DataProcessor()
        self.video_for_gui_queue = queue.Queue(maxsize=1) 
        self.telemetry_for_gui_queue = queue.Queue(maxsize=1)

        self.command_queue = asyncio.Queue()
        self.broadcast_queue = asyncio.Queue()
        self.mission_logic = MissionLogic(self.command_queue, self.broadcast_queue)

    async def websocket_handler(self, websocket):
        print(f"INFO: Onboard system connected from {websocket.remote_address}")

        sender_task = asyncio.create_task(self.command_and_broadcast_sender(websocket))

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    if data.get('type') == 'telemetry':
                        payload = data.get('payload')
                        self.telemetry_for_gui_queue.put(payload)
                        await self.mission_logic.process_telemetry(payload)
                    else:
                        print(f"WARN: Received message with unknown type: {data.get('type')}")
                except json.JSONDecodeError:
                    print(f"WARN: Received non-JSON message: {message}")
        except websockets.ConnectionClosed as e:
            print(f"INFO: Connection with {websocket.remote_address} closed: {e}")
        finally:
            sender_task.cancel()
            print(f"INFO: Onboard system {websocket.remote_address} disconnected.")

    async def command_and_broadcast_sender(self, websocket):
        async def sender(queue_obj):
            while True:
                message = await queue_obj.get()
                await websocket.send(json.dumps(message))

        await asyncio.gather(
            sender(self.command_queue),
            sender(self.broadcast_queue)
        )

    async def start_server(self):
        HOST = "0.0.0.0"
        async with websockets.serve(self.websocket_handler, HOST, WEBSOCKET_PORT):
            print(f"INFO: GCS WebSocket server started on ws://{HOST}:{WEBSOCKET_PORT}")
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
            self.lat_label.configure(text=f"Lat: {telemetry.get('latitude', 'N/A'):.6f}")
            self.lon_label.configure(text=f"Lon: {telemetry.get('longitude', 'N/A'):.6f}")
            self.alt_label.configure(text=f"Alt: {telemetry.get('altitude', 'N/A'):.2f} m")
            self.v_ground_label.configure(text=f"V Gnd: {telemetry.get('speed', 'N/A'):.2f} m/s")
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

def video_receiver_thread(app):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("0.0.0.0", VIDEO_PORT))
        print(f"INFO: UDP video receiver listening on port {VIDEO_PORT}")
        while True:
            packet, _ = sock.recvfrom(65536) 
            np_arr = np.frombuffer(packet, np.uint8)
            image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if image is not None:
                try:
                    app.video_for_gui_queue.put(image, block=False)
                except queue.Full:
                    pass # Discard frame if GUI is lagging

def ai_processing_thread(app, main_loop):
    """
    Thread to run AI inference on video frames.
    """
    while True:
        try:
            frame = app.video_for_gui_queue.get(timeout=1)
            _, detections = app.data_processor.process_video_frame(frame)
            if detections:
                future = asyncio.run_coroutine_threadsafe(
                    app.mission_logic.process_detections(detections),
                    main_loop
                )
                future.result(timeout=1)
        except queue.Empty:
            continue
        except Exception as e:
            print(f"ERROR: AI processing thread error: {e}")

async def main():
    app = GCSApp()

    main_loop = asyncio.get_running_loop()

    gui_thread = threading.Thread(
        target=run_gui,
        args=(app.video_for_gui_queue, app.telemetry_for_gui_queue),
        daemon=True
    )
    video_thread = threading.Thread(
        target=video_receiver_thread,
        args=(app,),
        daemon=True
    )
    ai_thread = threading.Thread(
        target=ai_processing_thread,
        args=(app, main_loop),
        daemon=True
    )

    gui_thread.start()
    video_thread.start()
    ai_thread.start()

    await app.start_server()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("INFO: Shutting down GCS application.")
