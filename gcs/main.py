import asyncio
import websockets
import json
import cv2
import numpy as np
from ultralytics import YOLO
import customtkinter
from PIL import Image
import threading
import queue
import socket
from datetime import datetime
import csv
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from collections import deque

# --- CONFIGURATION ---
WEBSOCKET_PORT = 8765
VIDEO_PORT = 9999

class FlightLogger:
    def __init__(self):
        now = datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d_%H-%M-%S")
        self.filename = f"flight_log_{timestamp_str}.csv"
        self.file = open(self.filename, 'w', newline='')
        self.writer = csv.writer(self.file)
        self.header = [
            'timestamp', 'latitude', 'longitude', 'relative_altitude_m',
            'ground_speed_mps', 'heading_deg', 'battery_v', 'event'
        ]
        self.writer.writerow(self.header)
        print(f"INFO: Flight logger initialized. Saving to {self.filename}")

    def log_telemetry(self, data):
        log_row = [
            data.get('timestamp', datetime.now().isoformat()),
            data.get('latitude', ''),
            data.get('longitude', ''),
            data.get('relative_altitude_m', ''),
            data.get('ground_speed_mps', ''),
            data.get('heading_deg', ''),
            data.get('battery_v', ''),
            ''
        ]
        self.writer.writerow(log_row)

    def log_event(self, event_string):
        log_row = [datetime.now().isoformat(), '', '', '', '', '', '', event_string]
        self.writer.writerow(log_row)

    def close(self):
        self.file.close()
        print("INFO: Flight log closed.")

class DataProcessor:
    def __init__(self):
        self.model = YOLO('best.pt')

    def process_video_frame(self, image):
        if image is None: return None, []
        results = self.model(image, verbose=False)
        detections = []
        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                confidence = float(box.conf[0])
                class_id = int(box.cls[0])
                class_name = self.model.names[class_id]
                detections.append({"class_name": class_name, "confidence": confidence, "box": [x1, y1, x2, y2]})
        return image, detections

class GCSApp:
    def __init__(self, logger):
        self.logger = logger
        self.data_processor = DataProcessor()
        # Thread-safe queues for GUI
        self.video_for_gui_queue = queue.Queue(maxsize=2)
        self.telemetry_for_gui_queue = queue.Queue(maxsize=10)
        # Asyncio queues for mission logic
        self.raw_video_for_ai_queue = queue.Queue(maxsize=2)
        self.detections_for_mission_logic_queue = asyncio.Queue(maxsize=10)
        self.telemetry_for_mission_logic_queue = asyncio.Queue(maxsize=10)

    async def websocket_handler(self, websocket):
        print(f"INFO: Onboard system connected from {websocket.remote_address}")
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    if data.get('type') == 'telemetry':
                        payload = data.get('payload')
                        self.logger.log_telemetry(payload)
                        self.telemetry_for_gui_queue.put(payload)
                        await self.telemetry_for_mission_logic_queue.put(payload)
                except json.JSONDecodeError:
                    print(f"WARN: Received non-JSON message.")
        except websockets.ConnectionClosed:
            print(f"INFO: Connection with {websocket.remote_address} closed.")

    async def start_server(self):
        HOST = "0.0.0.0"
        server = await websockets.serve(self.websocket_handler, HOST, WEBSOCKET_PORT)
        print(f"INFO: GCS WebSocket server started on ws://{HOST}:{WEBSOCKET_PORT}")
        await server.wait_closed()

class Dashboard(customtkinter.CTk):
    def __init__(self, app_queues):
        super().__init__()
        self.video_queue = app_queues['video_for_gui_queue']
        self.telemetry_queue = app_queues['telemetry_for_gui_queue']
        self.title("AetherLink GCS"); self.geometry("1440x810")

        self.grid_columnconfigure(0, weight=3); self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Video Frame
        self.video_panel = customtkinter.CTkFrame(self); self.video_panel.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.video_label = customtkinter.CTkLabel(self.video_panel, text="Waiting for video..."); self.video_label.pack(expand=True, fill="both")

        # Right Panel
        self.right_panel = customtkinter.CTkFrame(self); self.right_panel.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        self.right_panel.grid_rowconfigure(1, weight=1)

        # Telemetry Group
        self.telemetry_group = customtkinter.CTkFrame(self.right_panel); self.telemetry_group.grid(row=0, column=0, padx=10, pady=10, sticky="new")
        self.lat_label = customtkinter.CTkLabel(self.telemetry_group, text="Lat: N/A"); self.lat_label.pack(anchor="w")
        self.lon_label = customtkinter.CTkLabel(self.telemetry_group, text="Lon: N/A"); self.lon_label.pack(anchor="w")
        self.alt_label = customtkinter.CTkLabel(self.telemetry_group, text="Alt: N/A"); self.alt_label.pack(anchor="w")

        # Altitude Plot
        self.fig = plt.figure(figsize=(5, 3), dpi=100); self.ax = self.fig.add_subplot(111)
        self.ax.set_title("Altitude (m)"); self.ax.set_ylim(0, 20)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.right_panel)
        self.canvas.get_tk_widget().grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        self.time_data = deque(maxlen=100); self.alt_data = deque(maxlen=100)

        self.update_widgets()

    def update_widgets(self):
        try:
            telemetry = self.telemetry_queue.get_nowait()
            self.lat_label.configure(text=f"Lat: {telemetry.get('latitude', 0):.6f}")
            self.lon_label.configure(text=f"Lon: {telemetry.get('longitude', 0):.6f}")
            altitude = telemetry.get('relative_altitude_m', 0)
            self.alt_label.configure(text=f"Alt: {altitude:.2f} m")

            if 7.0 <= altitude <= 9.0: self.alt_label.configure(text_color="green")
            else: self.alt_label.configure(text_color="red")

            self.time_data.append(datetime.now()); self.alt_data.append(altitude)
            self.ax.clear(); self.ax.plot(self.time_data, self.alt_data)
            self.ax.axhline(y=7.0, color='g', linestyle='--'); self.ax.axhline(y=9.0, color='g', linestyle='--')
            self.ax.set_title("Altitude (m)"); self.ax.set_ylim(0, max(10, altitude + 5))
            self.canvas.draw()
        except queue.Empty: pass

        try:
            frame = self.video_queue.get_nowait()
            img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(img)
            ctk_image = customtkinter.CTkImage(light_image=img, dark_image=img, size=(960, 540))
            self.video_label.configure(image=ctk_image, text="")
        except queue.Empty: pass

        self.after(50, self.update_widgets)

def run_gui(app_queues):
    dashboard = Dashboard(app_queues); dashboard.mainloop()

def video_receiver_thread(raw_video_queue):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("0.0.0.0", VIDEO_PORT))
        print(f"INFO: UDP video receiver listening on port {VIDEO_PORT}")
        while True:
            packet, _ = sock.recvfrom(65536)
            np_arr = np.frombuffer(packet, np.uint8)
            image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if image is not None:
                try: raw_video_queue.put(image, block=False)
                except queue.Full: pass

def ai_processing_thread(app, main_loop):
    while True:
        try:
            frame = app.raw_video_for_ai_queue.get(timeout=1)
            _, detections = app.data_processor.process_video_frame(frame)

            # Draw detections on the frame
            for det in detections:
                box = det['box']; name = det['class_name']
                cv2.rectangle(frame, (box[0], box[1]), (box[2], box[3]), (0, 255, 0), 2)
                cv2.putText(frame, name, (box[0], box[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

            # Send annotated frame to GUI and detections to mission logic
            try: app.video_for_gui_queue.put(frame, block=False)
            except queue.Full: pass

            if detections:
                asyncio.run_coroutine_threadsafe(
                    app.detections_for_mission_logic_queue.put(detections),
                    main_loop
                )
        except queue.Empty: continue
        except Exception as e: print(f"ERROR: AI processing thread error: {e}")

async def mission_logic_consumer(app):
    while True:
        telemetry = await app.telemetry_for_mission_logic_queue.get()
        detections = await app.detections_for_mission_logic_queue.get()
        # Mission logic placeholder
        print(f"MISSION_LOGIC: Processing telemetry and {len(detections)} detections.")
        app.logger.log_event(f"PROCESSED_FRAME: Found {len(detections)} objects.")

async def main():
    logger = FlightLogger()
    app = GCSApp(logger)

    # Prepare queues for the dashboard
    gui_queues = {
        'video_for_gui_queue': app.video_for_gui_queue,
        'telemetry_for_gui_queue': app.telemetry_for_gui_queue,
    }

    main_loop = asyncio.get_running_loop()

    # Start all threads
    threading.Thread(target=run_gui, args=(gui_queues,), daemon=True).start()
    threading.Thread(target=video_receiver_thread, args=(app.raw_video_for_ai_queue,), daemon=True).start()
    threading.Thread(target=ai_processing_thread, args=(app, main_loop), daemon=True).start()

    try:
        await asyncio.gather(
            app.start_server(),
            mission_logic_consumer(app)
        )
    finally:
        logger.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("INFO: Shutting down GCS application.")
