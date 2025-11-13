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
import time
from datetime import datetime
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# --- CONFIGURATION ---
WEBSOCKET_PORT = 8765
VIDEO_PORT = 9999

class FlightLogger:
    def __init__(self, mission_name):
        self.log_file_path = f"{mission_name}_events.jsonl"
        self.video_writer = None
        self.frame_size = None

    def log_event(self, event_type, data):
        with open(self.log_file_path, 'a') as f:
            log_entry = {
                'timestamp': time.time(),
                'event_type': event_type,
                'data': data
            }
            f.write(json.dumps(log_entry) + '\n')

    def log_frame(self, frame):
        if self.video_writer is None:
            height, width, _ = frame.shape
            self.frame_size = (width, height)
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self.video_writer = cv2.VideoWriter(f"{mission_name}_video.mp4", fourcc, 20.0, self.frame_size)

        self.video_writer.write(frame)

    def close(self):
        if self.video_writer:
            self.video_writer.release()

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

            # print(f"DEBUG: Processed video frame, found {len(detections)} detections.")
            return image, detections
        except Exception as e:
            print(f"ERROR: Error processing video frame: {e}")
            return image, []

class GCSApp:
    def __init__(self):
        mission_name = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.logger = FlightLogger(mission_name)
        self.data_processor = DataProcessor()
        self.video_for_gui_queue = queue.Queue(maxsize=1)
        self.telemetry_for_gui_queue = queue.Queue(maxsize=1)
        self.detections_for_mission_logic_queue = asyncio.Queue(maxsize=10)
        self.telemetry_for_mission_logic_queue = asyncio.Queue(maxsize=10)
        self.command_queue = asyncio.Queue(maxsize=10)
        self.mission_logic = MissionLogic(self.command_queue, self.logger)

    async def websocket_handler(self, websocket):
        print(f"INFO: Onboard system connected from {websocket.remote_address}")
        self.logger.log_event('GCS_CONNECTION', {'status': 'connected', 'client': websocket.remote_address})

        command_sender_task = asyncio.create_task(self.command_sender(websocket))

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    if data.get('type') == 'telemetry':
                        payload = data.get('payload')
                        self.logger.log_event('TELEMETRY_RECEIVED', payload)
                        self.telemetry_for_gui_queue.put(payload)
                        await self.telemetry_for_mission_logic_queue.put(payload)
                    else:
                        print(f"WARN: Received message with unknown type: {data.get('type')}")
                except json.JSONDecodeError:
                    print(f"WARN: Received non-JSON message: {message}")
        except websockets.ConnectionClosed as e:
            print(f"INFO: Connection with {websocket.remote_address} closed: {e}")
        finally:
            command_sender_task.cancel()
            self.logger.log_event('GCS_CONNECTION', {'status': 'disconnected', 'client': websocket.remote_address})
            print(f"INFO: Onboard system {websocket.remote_address} disconnected.")

    async def command_sender(self, websocket):
        while True:
            command = await self.command_queue.get()
            await websocket.send(json.dumps(command))
            self.logger.log_event('COMMAND_SENT', command)

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

        # Mission Log
        self.mission_log_label = customtkinter.CTkLabel(self.data_frame, text="Mission Log", font=customtkinter.CTkFont(size=20, weight="bold"))
        self.mission_log_label.grid(row=8, column=0, padx=10, pady=(20, 10), sticky="ew")
        self.mission_log_textbox = customtkinter.CTkTextbox(self.data_frame, height=200)
        self.mission_log_textbox.grid(row=9, column=0, padx=10, pady=10, sticky="nsew")
        self.data_frame.grid_rowconfigure(9, weight=1)

        # Graphs
        self.fig, (self.ax1, self.ax2) = plt.subplots(2, 1, figsize=(5, 4))
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.data_frame)
        self.canvas.get_tk_widget().grid(row=10, column=0, padx=10, pady=10, sticky="ew")
        self.altitude_data = []
        self.speed_data = []

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

            # Update graphs
            self.altitude_data.append(telemetry.get('altitude', 0))
            self.speed_data.append(telemetry.get('speed', 0))
            self.ax1.clear()
            self.ax1.plot(self.altitude_data)
            self.ax1.set_title("Altitude")
            self.ax2.clear()
            self.ax2.plot(self.speed_data)
            self.ax2.set_title("Speed")
            self.fig.tight_layout()
            self.canvas.draw()
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
                app.logger.log_frame(image)
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
                    app.detections_for_mission_logic_queue.put(detections),
                    main_loop
                )
                future.result(timeout=1)
        except queue.Empty:
            continue
        except Exception as e:
            print(f"ERROR: AI processing thread error: {e}")


class MissionLogic:
    def __init__(self, command_queue, logger):
        self.state = 'STANDBY'
        self.command_queue = command_queue
        self.logger = logger
        self.resume_point = None
        self.payload_dropped = False
        self.detected_objects = set()

    async def run(self, telemetry_queue, detections_queue):
        while True:
            telemetry = await telemetry_queue.get()
            detections = await detections_queue.get()

            # Simple state machine logic
            if self.state == 'STANDBY':
                # Logic to start the mission
                pass
            elif self.state == 'EXECUTING_SURVEY':
                # Logic for survey
                pass
            elif self.state == 'TRANSITING_TO_DROP_ZONE':
                # Logic for transiting
                pass
            elif self.state == 'PERFORMING_PAYLOAD_DROP':
                # Logic for dropping payload
                pass
            elif self.state == 'RESUMING_SURVEY':
                # Logic for resuming survey
                pass
            elif self.state == 'RETURNING_TO_LAUNCH':
                # Logic for returning to launch
                pass

            self.logger.log_event('MISSION_STATE_UPDATE', {'state': self.state})

    async def send_command(self, command_type, payload):
        await self.command_queue.put({'type': command_type, 'payload': payload})


async def main():
    app = GCSApp()

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

    main_loop = asyncio.get_running_loop()

    # Pass the main asyncio loop to the AI thread
    ai_thread = threading.Thread(
        target=ai_processing_thread,
        args=(app, main_loop),
        daemon=True
    )

    gui_thread.start()
    video_thread.start()
    ai_thread.start()

    await asyncio.gather(
        app.start_server(),
        app.mission_logic.run(app.telemetry_for_mission_logic_queue, app.detections_for_mission_logic_queue)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("INFO: Shutting down GCS application.")

