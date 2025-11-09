# ground_station/dashboard/main.py

import asyncio
import json
import queue
import threading
import websockets
import customtkinter
from PIL import Image, ImageTk
import cv2
import sys

# --- CONFIGURATION ---
COMMS_HUB_IP = "100.69.186.67"  # <-- USER: Set Tailscale IP of Comms Hub Laptop
COMMS_HUB_PORT = 8765
DASHBOARD_VIDEO_PORT = 5602 # We listen on this port

# This pipeline correctly expects an RTP-encapsulated H.264 stream.
GSTREAMER_PIPELINE = (
    f"udpsrc port={DASHBOARD_VIDEO_PORT} "
    "! application/x-rtp, media=video, clock-rate=90000, encoding-name=H264 "
    "! rtph264depay "
    "! decodebin "
    "! videoconvert "
    "! appsink"
)

class DashboardApp(customtkinter.CTk):
    def __init__(self):
        super().__init__()
        self.title("AetherLink Dashboard")
        self.geometry("1280x720")
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Video Frame
        self.video_label = customtkinter.CTkLabel(self, text="Waiting for video feed...")
        self.video_label.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        # Data Panels Frame
        self.data_frame = customtkinter.CTkFrame(self)
        self.data_frame.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        self.data_frame.grid_rowconfigure(2, weight=1)
        self.data_frame.grid_columnconfigure(0, weight=1)

        # Mission State
        self.mission_state_label = customtkinter.CTkLabel(self.data_frame, text="Mission State: STANDBY", font=("Arial", 20, "bold"))
        self.mission_state_label.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        # Telemetry
        self.telemetry_frame = customtkinter.CTkFrame(self.data_frame)
        self.telemetry_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        self.lat_label = customtkinter.CTkLabel(self.telemetry_frame, text="Lat: N/A")
        self.lat_label.pack(padx=10, pady=5, anchor="w")
        self.lon_label = customtkinter.CTkLabel(self.telemetry_frame, text="Lon: N/A")
        self.lon_label.pack(padx=10, pady=5, anchor="w")
        self.alt_label = customtkinter.CTkLabel(self.telemetry_frame, text="Alt: N/A")
        self.alt_label.pack(padx=10, pady=5, anchor="w")
        self.battery_label = customtkinter.CTkLabel(self.telemetry_frame, text="Battery: N/A")
        self.battery_label.pack(padx=10, pady=5, anchor="w")
        
        # Mission Log
        self.mission_log_label = customtkinter.CTkLabel(self.data_frame, text="--- Mission Log ---")
        self.mission_log_label.grid(row=2, column=0, padx=10, pady=(10,0), sticky="sw")
        self.mission_log = customtkinter.CTkTextbox(self.data_frame)
        self.mission_log.grid(row=3, column=0, padx=10, pady=10, sticky="nsew")
        self.mission_log.configure(state="disabled")

        self.data_queue = queue.Queue()
        self.stop_event = threading.Event()

    def update_gui(self):
        try:
            # Process all pending items in the queue
            while not self.data_queue.empty():
                data = self.data_queue.get_nowait()
                if data['type'] == 'telemetry':
                    self.lat_label.configure(text=f"Lat: {data.get('latitude', 0):.6f}")
                    self.lon_label.configure(text=f"Lon: {data.get('longitude', 0):.6f}")
                    self.alt_label.configure(text=f"Alt: {data.get('relative_altitude_m', 0):.2f} m")
                    self.battery_label.configure(text=f"Battery: {data.get('battery_voltage', 0):.2f}V")
                elif data['type'] == 'video_image':
                    # Resize the image to fit the label while maintaining aspect ratio
                    w, h = 960, 540 # Target size
                    img = data['image']
                    img.thumbnail((w, h))
                    ctk_image = ImageTk.PhotoImage(img)
                    
                    self.video_label.configure(image=ctk_image, text="")
                    self.video_label.image = ctk_image # Keep a reference
                elif data['type'] == 'mission_state':
                    self.mission_state_label.configure(text=f"Mission State: {data.get('state', 'N/A')}")
                elif data['type'] == 'mission_log':
                    self.mission_log.configure(state="normal")
                    self.mission_log.insert('end', data.get('message', '') + '\n')
                    self.mission_log.yview_moveto(1.0)
                    self.mission_log.configure(state="disabled")
                elif data['type'] == 'video_error':
                    self.video_label.configure(text="Error: Could not open video stream.", image=None)
        except queue.Empty:
            pass
        self.after(33, self.update_gui) # Schedule next update (~30fps)

    def video_thread_func(self):
        cap = cv2.VideoCapture(GSTREAMER_PIPELINE, cv2.CAP_GSTREAMER)
        if not cap.isOpened():
            print(f"FATAL: Could not open GStreamer pipeline on port {DASHBOARD_VIDEO_PORT}.")
            self.data_queue.put({'type': 'video_error'})
            return

        print("INFO: Video display thread started, receiving stream.")
        while not self.stop_event.is_set():
            ret, frame = cap.read()
            if ret:
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_image = Image.fromarray(rgb_frame)
                self.data_queue.put({'type': 'video_image', 'image': pil_image})
            else:
                time.sleep(0.01)
        cap.release()
        print("INFO: Video display thread stopped.")
        
    async def websocket_client(self):
        uri = f"ws://{COMMS_HUB_IP}:{COMMS_HUB_PORT}"
        while not self.stop_event.is_set():
            try:
                async with websockets.connect(uri) as websocket:
                    print("INFO: Dashboard connected to Comms Hub.")
                    async for message in websocket:
                        self.data_queue.put(json.loads(message))
            except (websockets.ConnectionClosed, ConnectionRefusedError):
                print("WARN: Connection to Comms Hub lost. Retrying in 5s...")
                await asyncio.sleep(5)
    
    def on_closing(self):
        print("INFO: Closing application...")
        self.stop_event.set()
        self.destroy()

    def start(self):
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        threading.Thread(target=self.video_thread_func, daemon=True).start()

        def _run_async_loop():
            asyncio.run(self.websocket_client())

        threading.Thread(target=_run_async_loop, daemon=True).start()

        self.update_gui()
        self.mainloop()

if __name__ == "__main__":
    app = DashboardApp()
    app.start()
