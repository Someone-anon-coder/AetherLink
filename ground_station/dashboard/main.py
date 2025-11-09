import asyncio
import json
import queue
import threading
import websockets
import customtkinter
from PIL import Image
import cv2
import numpy as np

# <-- USER: Set this to the Tailscale IP of the Comms Hub machine
COMMS_HUB_IP = "100.69.186.67"
COMMS_HUB_PORT = 8765

class DashboardApp(customtkinter.CTk):
    def __init__(self):
        super().__init__()

        self.title("Aetherlink Dashboard")
        self.geometry("1280x720")

        # Main layout
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Video Feed
        self.video_label = customtkinter.CTkLabel(self, text="Waiting for video feed...")
        self.video_label.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        # Data Panels Frame
        self.data_frame = customtkinter.CTkFrame(self)
        self.data_frame.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        self.data_frame.grid_rowconfigure(1, weight=1)
        self.data_frame.grid_columnconfigure(0, weight=1)

        # Mission State
        self.mission_state_label = customtkinter.CTkLabel(self.data_frame, text="Mission State: N/A", font=("Arial", 20))
        self.mission_state_label.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        # Telemetry Frame
        self.telemetry_frame = customtkinter.CTkFrame(self.data_frame)
        self.telemetry_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")

        self.lat_label = customtkinter.CTkLabel(self.telemetry_frame, text="Lat: N/A")
        self.lat_label.pack(padx=10, pady=5)

        self.lon_label = customtkinter.CTkLabel(self.telemetry_frame, text="Lon: N/A")
        self.lon_label.pack(padx=10, pady=5)

        self.alt_label = customtkinter.CTkLabel(self.telemetry_frame, text="Alt: N/A")
        self.alt_label.pack(padx=10, pady=5)

        self.battery_label = customtkinter.CTkLabel(self.telemetry_frame, text="Battery: N/A")
        self.battery_label.pack(padx=10, pady=5)

        # Mission Log
        self.mission_log = customtkinter.CTkTextbox(self.data_frame)
        self.mission_log.grid(row=2, column=0, padx=10, pady=10, sticky="ew")
        self.mission_log.insert("0.0", "--- Mission Log ---\n")
        self.mission_log.configure(state="disabled")

        self.data_queue = queue.Queue()
        self.video_frame_queue = queue.Queue()
        self.video_port = None
        self.video_port_event = threading.Event()
        self.latest_frame = None


    def update_gui(self):
        try:
            # Process all available data messages
            while not self.data_queue.empty():
                data = self.data_queue.get_nowait()

                if data.get('type') == 'telemetry':
                    self.lat_label.configure(text=f"Lat: {data.get('latitude', 0):.6f}")
                    self.lon_label.configure(text=f"Lon: {data.get('longitude', 0):.6f}")
                    self.alt_label.configure(text=f"Alt: {data.get('relative_altitude_m', 0):.2f} m")
                    self.battery_label.configure(text=f"Battery: {data.get('battery_voltage', 0):.2f}%")

                elif data.get('type') == 'video_frame' and 'detections' in data:
                    if self.latest_frame is not None:
                        frame_with_boxes = self.latest_frame.copy()
                        for detection in data['detections']:
                            box = detection['box']
                            cv2.rectangle(frame_with_boxes, (int(box[0]), int(box[1])), (int(box[2]), int(box[3])), (0, 255, 0), 2)
                            cv2.putText(frame_with_boxes, detection['class_name'], (int(box[0]), int(box[1]) - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,255,0), 2)

                        image = Image.fromarray(cv2.cvtColor(frame_with_boxes, cv2.COLOR_BGR2RGB))
                        ctk_image = customtkinter.CTkImage(light_image=image, dark_image=image, size=(640, 480))
                        self.video_label.configure(image=ctk_image, text="")

                elif data.get('type') == 'mission_state':
                    self.mission_state_label.configure(text=f"Mission State: {data.get('state', 'N/A')}")

                elif data.get('type') == 'mission_log':
                    self.mission_log.configure(state="normal")
                    self.mission_log.insert('end', data.get('message', '') + '\n')
                    self.mission_log.configure(state="disabled")

            # Process the latest video frame
            if not self.video_frame_queue.empty():
                self.latest_frame = self.video_frame_queue.get_nowait()
                image = Image.fromarray(cv2.cvtColor(self.latest_frame, cv2.COLOR_BGR2RGB))
                ctk_image = customtkinter.CTkImage(light_image=image, dark_image=image, size=(640, 480))
                self.video_label.configure(image=ctk_image, text="")


        except queue.Empty:
            pass
        finally:
            self.after(30, self.update_gui)

    async def websocket_client(self):
        uri = f"ws://{COMMS_HUB_IP}:{COMMS_HUB_PORT}"
        while True:
            try:
                async for websocket in websockets.connect(uri):
                    print("Dashboard connected to Comms Hub.")
                    await websocket.send(json.dumps({"action": "subscribe", "stream": "video"}))
                    try:
                        async for message in websocket:
                            data = json.loads(message)
                            if data.get('status') == 'subscribed' and data.get('stream') == 'video':
                                self.video_port = data.get('port')
                                self.video_port_event.set()
                                print(f"Received video port: {self.video_port}")
                            else:
                                self.data_queue.put(data)
                    except websockets.ConnectionClosed:
                        print("Connection to Comms Hub closed. Retrying...")
                        self.video_port_event.clear()
                        continue
            except Exception as e:
                print(f"Failed to connect to Comms Hub: {e}. Retrying in 5 seconds...")
                await asyncio.sleep(5)

    def video_capture_thread(self):
        self.video_port_event.wait()
        print(f"Video capture thread started for port {self.video_port}.")
        pipeline = (
            f"udpsrc port={self.video_port} ! "
            "application/x-rtp, media=(string)video, clock-rate=(int)90000, encoding-name=(string)H264, payload=(int)96 ! "
            "rtph264depay ! decodebin ! videoconvert ! appsink"
        )
        cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
        if not cap.isOpened():
            print("Error: Could not open video stream.")
            return

        while True:
            ret, frame = cap.read()
            if ret:
                frame = cv2.resize(frame, (640, 480))
                self.video_frame_queue.put(frame)

    def start(self):
        def run_asyncio_loop():
            asyncio.run(self.websocket_client())

        network_thread = threading.Thread(target=run_asyncio_loop, daemon=True)
        network_thread.start()

        video_thread = threading.Thread(target=self.video_capture_thread, daemon=True)
        video_thread.start()

        self.update_gui()
        self.mainloop()

if __name__ == "__main__":
    app = DashboardApp()
    app.start()
