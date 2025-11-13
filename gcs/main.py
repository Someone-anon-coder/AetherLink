import asyncio
import websockets
import json
import cv2
import numpy as np
from ultralytics import YOLO
import customtkinter
from PIL import Image, ImageTk
import threading
import queue
import socket
import argparse
import datetime
import csv
import os
from mavsdk import System

# --- CONFIGURATION ---
WEBSOCKET_PORT = 8765
VIDEO_PORT = 9999
SITL_MAVSDK_PORT = 5763

class FlightLogger:
    def __init__(self, log_dir="flight_logs"):
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.log_file_path = os.path.join(log_dir, f"flight_log_{timestamp}.csv")

        self.file = open(self.log_file_path, 'w', newline='')
        self.writer = csv.writer(self.file)

        self.header = [
            "timestamp", "latitude", "longitude", "relative_altitude_m",
            "speed_m_s", "heading_deg", "battery_percent", "battery_voltage"
        ]
        self.writer.writerow(self.header)
        print(f"INFO: Flight logger initialized. Log file: {self.log_file_path}")

    def log(self, telemetry_data):
        try:
            log_entry = [telemetry_data.get(key, 'N/A') for key in self.header]
            self.writer.writerow(log_entry)
        except Exception as e:
            print(f"ERROR: Could not write to log file: {e}")

    def close(self):
        self.file.close()

class TelemetryHub:
    def __init__(self, mode, output_queue):
        self.mode = mode
        self.output_queue = output_queue
        self.drone = System()

    async def start(self):
        if self.mode == 'sitl':
            await self._run_sitl_producer()
        # 'real' mode is handled by the WebSocket server

    async def _run_sitl_producer(self):
        print("INFO: Starting TelemetryHub in SITL mode.")
        await self.drone.connect(system_address=f"udp://:{SITL_MAVSDK_PORT}")

        print("INFO: Waiting for SITL drone to connect...")
        async for state in self.drone.core.connection_state():
            if state.is_connected:
                print("INFO: SITL drone connected!")
                break

        asyncio.ensure_future(self._stream_telemetry())

    async def _stream_telemetry(self):
        # Create concurrent tasks for each telemetry stream
        position_task = asyncio.ensure_future(self._get_telemetry_stream(self.drone.telemetry.position()))
        heading_task = asyncio.ensure_future(self._get_telemetry_stream(self.drone.telemetry.heading()))
        velocity_task = asyncio.ensure_future(self._get_telemetry_stream(self.drone.telemetry.velocity_ned()))
        battery_task = asyncio.ensure_future(self._get_telemetry_stream(self.drone.telemetry.battery()))

        while True:
            # Wait for all telemetry to be updated
            await asyncio.gather(position_task, heading_task, velocity_task, battery_task)

            position = position_task.result()
            heading = heading_task.result()
            velocity = velocity_task.result()
            battery = battery_task.result()

            if all([position, heading, velocity, battery]):
                telemetry_data = {
                    'latitude': position.latitude_deg,
                    'longitude': position.longitude_deg,
                    'relative_altitude_m': position.relative_altitude_m,
                    'speed_m_s': (velocity.north_m_s**2 + velocity.east_m_s**2)**0.5,
                    'heading_deg': heading.heading_deg,
                    'battery_percent': battery.remaining_percent * 100,
                    'battery_voltage': battery.voltage_v,
                    'timestamp': datetime.datetime.now().isoformat()
                }
                await self.output_queue.put(telemetry_data)

            # Reset tasks to fetch the next update
            position_task = asyncio.ensure_future(self._get_telemetry_stream(self.drone.telemetry.position()))
            heading_task = asyncio.ensure_future(self._get_telemetry_stream(self.drone.telemetry.heading()))
            velocity_task = asyncio.ensure_future(self._get_telemetry_stream(self.drone.telemetry.velocity_ned()))
            battery_task = asyncio.ensure_future(self._get_telemetry_stream(self.drone.telemetry.battery()))

    async def _get_telemetry_stream(self, stream):
        async for item in stream:
            return item

    async def handle_real_telemetry(self, telemetry_payload):
        if self.mode == 'real':
            telemetry_payload['timestamp'] = datetime.datetime.now().isoformat()
            await self.output_queue.put(telemetry_payload)


class DataProcessor:
    def __init__(self):
        self.model = YOLO('best.pt')
        print("INFO: YOLO model loaded.")

    def process_frame(self, image):
        if image is None: return None, []
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
            print(f"ERROR: AI processing failed: {e}")
            return image, []

class Dashboard(customtkinter.CTk):
    def __init__(self, video_q, telemetry_q):
        super().__init__()
        self.video_queue = video_q
        self.telemetry_queue = telemetry_q

        self.title("AetherLink GCS")
        self.geometry("1280x720")

        self.grid_columnconfigure(0, weight=4)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.video_label = customtkinter.CTkLabel(self, text="Waiting for video feed...")
        self.video_label.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        self.data_frame = customtkinter.CTkFrame(self)
        self.data_frame.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        self.data_frame.grid_columnconfigure(0, weight=1)

        # Connection Status
        self.conn_status_label = customtkinter.CTkLabel(self.data_frame, text="DISCONNECTED", text_color="red", font=customtkinter.CTkFont(size=16, weight="bold"))
        self.conn_status_label.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        # Telemetry
        self.telemetry_label = customtkinter.CTkLabel(self.data_frame, text="Telemetry", font=customtkinter.CTkFont(size=20, weight="bold"))
        self.telemetry_label.grid(row=1, column=0, padx=10, pady=10, sticky="ew")
        self.lat_label = customtkinter.CTkLabel(self.data_frame, text="Lat: N/A")
        self.lat_label.grid(row=2, column=0, padx=10, pady=2, sticky="w")
        self.lon_label = customtkinter.CTkLabel(self.data_frame, text="Lon: N/A")
        self.lon_label.grid(row=3, column=0, padx=10, pady=2, sticky="w")
        self.alt_label = customtkinter.CTkLabel(self.data_frame, text="Alt: N/A")
        self.alt_label.grid(row=4, column=0, padx=10, pady=2, sticky="w")
        self.speed_label = customtkinter.CTkLabel(self.data_frame, text="Speed: N/A")
        self.speed_label.grid(row=5, column=0, padx=10, pady=2, sticky="w")
        self.heading_label = customtkinter.CTkLabel(self.data_frame, text="Heading: N/A")
        self.heading_label.grid(row=6, column=0, padx=10, pady=2, sticky="w")
        self.battery_label = customtkinter.CTkLabel(self.data_frame, text="Battery: N/A")
        self.battery_label.grid(row=7, column=0, padx=10, pady=2, sticky="w")

        self.update_widgets()

    def update_connection_status(self, is_connected):
        if is_connected:
            self.conn_status_label.configure(text="CONNECTED", text_color="green")
        else:
            self.conn_status_label.configure(text="DISCONNECTED", text_color="red")

    def update_widgets(self):
        try:
            telemetry = self.telemetry_queue.get_nowait()
            self.lat_label.configure(text=f"Lat: {telemetry.get('latitude', 0):.6f}")
            self.lon_label.configure(text=f"Lon: {telemetry.get('longitude', 0):.6f}")
            self.alt_label.configure(text=f"Alt: {telemetry.get('relative_altitude_m', 0):.2f} m")
            self.speed_label.configure(text=f"Speed: {telemetry.get('speed_m_s', 0):.2f} m/s")
            self.heading_label.configure(text=f"Heading: {telemetry.get('heading_deg', 0):.2f}°")
            self.battery_label.configure(text=f"Battery: {telemetry.get('battery_percent', 0):.1f}% ({telemetry.get('battery_voltage', 0):.2f}V)")
        except queue.Empty:
            pass

        try:
            frame = self.video_queue.get_nowait()
            img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            ctk_image = customtkinter.CTkImage(Image.fromarray(img), size=(960, 540))
            self.video_label.configure(image=ctk_image, text="")
        except queue.Empty:
            pass

        self.after(33, self.update_widgets)

class GCSApp:
    def __init__(self, mode):
        self.mode = mode
        self.flight_logger = FlightLogger()
        self.data_processor = DataProcessor()

        self.video_q_for_gui = queue.Queue(maxsize=1)
        self.video_q_for_ai = queue.Queue(maxsize=1)
        self.telemetry_q_for_gui = queue.Queue(maxsize=10)
        self.telemetry_q_for_logic = asyncio.Queue(maxsize=10)
        self.detections_q_for_logic = asyncio.Queue(maxsize=10)
        self.telemetry_hub_output_q = asyncio.Queue(maxsize=10)

        self.dashboard = Dashboard(self.video_q_for_gui, self.telemetry_q_for_gui)
        self.telemetry_hub = TelemetryHub(self.mode, self.telemetry_hub_output_q)
        self.main_loop = None

    async def websocket_handler(self, websocket):
        print(f"INFO: Onboard system connected from {websocket.remote_address}")
        self.main_loop.call_soon_threadsafe(self.dashboard.update_connection_status, True)
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    if data.get('type') == 'telemetry':
                        await self.telemetry_hub.handle_real_telemetry(data.get('payload'))
                except json.JSONDecodeError:
                    print(f"WARN: Received non-JSON message")
        finally:
            print(f"INFO: Onboard system disconnected.")
            self.main_loop.call_soon_threadsafe(self.dashboard.update_connection_status, False)

    async def start(self):
        self.main_loop = asyncio.get_running_loop()

        # Start Threads
        threading.Thread(target=self.run_gui, daemon=True).start()
        threading.Thread(target=self.video_receiver, daemon=True).start()
        threading.Thread(target=self.ai_processor, daemon=True).start()

        # Start Async Tasks
        server = websockets.serve(self.websocket_handler, "0.0.0.0", WEBSOCKET_PORT)

        await asyncio.gather(
            server,
            self.telemetry_hub.start(),
            self._distribute_data()
        )

    def run_gui(self):
        self.dashboard.mainloop()

    def video_receiver(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(("0.0.0.0", VIDEO_PORT))
            while True:
                packet, _ = sock.recvfrom(65536)
                np_arr = np.frombuffer(packet, np.uint8)
                image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                if image is not None:
                    try: self.video_q_for_gui.put_nowait(image)
                    except queue.Full: pass
                    try: self.video_q_for_ai.put_nowait(image)
                    except queue.Full: pass

    def ai_processor(self):
        while True:
            try:
                frame = self.video_q_for_ai.get(timeout=1)
                _, detections = self.data_processor.process_frame(frame)
                if detections:
                    asyncio.run_coroutine_threadsafe(
                        self.detections_q_for_logic.put(detections), self.main_loop
                    ).result(timeout=1)
            except queue.Empty:
                continue

    async def _distribute_data(self):
        while True:
            telemetry = await self.telemetry_hub_output_q.get()

            # Log to CSV
            self.flight_logger.log(telemetry)

            # Send to GUI
            try: self.telemetry_q_for_gui.put_nowait(telemetry)
            except queue.Full: pass

            # Send to Mission Logic
            try: await asyncio.wait_for(self.telemetry_q_for_logic.put(telemetry), timeout=0.01)
            except asyncio.TimeoutError: pass

def main():
    parser = argparse.ArgumentParser(description="AetherLink GCS")
    parser.add_argument('--mode', type=str, default='sitl', choices=['sitl', 'real'],
                        help="Telemetry source mode ('sitl' or 'real')")
    args = parser.parse_args()

    app = GCSApp(mode=args.mode)
    try:
        asyncio.run(app.start())
    except KeyboardInterrupt:
        print("INFO: Shutting down GCS...")
    finally:
        app.flight_logger.close()

if __name__ == "__main__":
    main()