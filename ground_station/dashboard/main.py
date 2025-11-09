import asyncio
import json
import queue
import threading
import websockets
import customtkinter
from PIL import Image
import cv2
import numpy as np

# --- CONFIGURATION ---
COMMS_HUB_IP = "127.0.0.1" # Connect to the local Comms Hub relay
COMMS_HUB_PORT = 8765
GSTREAMER_PIPELINE = "udpsrc port=5602 ! application/x-rtp, encoding-name=H264, payload=96 ! rtph264depay ! decodebin ! videoconvert ! appsink"

class DashboardApp(customtkinter.CTk):
    def __init__(self):
        super().__init__()
        self.title("Aetherlink Dashboard")
        self.geometry("1280x720")
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.video_label = customtkinter.CTkLabel(self, text="Waiting for video feed...")
        self.video_label.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        self.data_frame = customtkinter.CTkFrame(self)
        self.data_frame.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        self.data_frame.grid_rowconfigure(1, weight=1)
        self.data_frame.grid_columnconfigure(0, weight=1)

        self.mission_state_label = customtkinter.CTkLabel(self.data_frame, text="Mission State: N/A", font=("Arial", 20))
        self.mission_state_label.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

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

        self.mission_log = customtkinter.CTkTextbox(self.data_frame)
        self.mission_log.grid(row=2, column=0, padx=10, pady=10, sticky="ew")
        self.mission_log.insert("0.0", "--- Mission Log ---\n")
        self.mission_log.configure(state="disabled")

        self.data_queue = queue.Queue()

    def update_gui(self):
        try:
            data = self.data_queue.get_nowait()
            if data['type'] == 'telemetry':
                self.lat_label.configure(text=f"Lat: {data.get('latitude', 0):.6f}")
                self.lon_label.configure(text=f"Lon: {data.get('longitude', 0):.6f}")
                self.alt_label.configure(text=f"Alt: {data.get('relative_altitude_m', 0):.2f} m")
                self.battery_label.configure(text=f"Battery: {data.get('battery_voltage', 0):.2f}V")
            elif data['type'] == 'video_image':
                ctk_image = customtkinter.CTkImage(light_image=data['image'], dark_image=data['image'], size=(960, 540))
                self.video_label.configure(image=ctk_image, text="")
            elif data['type'] == 'mission_state':
                self.mission_state_label.configure(text=f"Mission State: {data.get('state', 'N/A')}")
            elif data['type'] == 'mission_log':
                self.mission_log.configure(state="normal")
                self.mission_log.insert('end', data.get('message', '') + '\n')
                self.mission_log.see('end')
                self.mission_log.configure(state="disabled")
        except queue.Empty:
            pass
        finally:
            self.after(100, self.update_gui)

    async def websocket_client(self):
        uri = f"ws://{COMMS_HUB_IP}:{COMMS_HUB_PORT}"
        while True:
            try:
                async with websockets.connect(uri) as websocket:
                    print("Dashboard connected to Comms Hub.")
                    # This loop ONLY processes non-video data
                    async for message in websocket:
                        data = json.loads(message)
                        if data.get('type') != 'video_image': # Explicitly ignore any stray video data
                            self.data_queue.put(data)
            except (websockets.ConnectionClosed, ConnectionRefusedError):
                print("Connection to Comms Hub lost. Retrying...")
                await asyncio.sleep(5)

    def video_update_thread(self, stop_event):
        cap = cv2.VideoCapture(GSTREAMER_PIPELINE, cv2.CAP_GSTREAMER)
        if not cap.isOpened():
            print("="*50)
            print("FATAL: Dashboard could not open GStreamer video stream.")
            print(f"PIPELINE: {GSTREAMER_PIPELINE}")
            print("="*50)
            return

        print("--> Video thread started successfully.")
        while not stop_event.is_set():
            ret, frame = cap.read()
            if ret:
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_image = Image.fromarray(rgb_frame)
                self.data_queue.put({'type': 'video_image', 'image': pil_image})
            else:
                time.sleep(0.1) # Avoid tight loop on error

        cap.release()
        print("--- Video thread has shut down. ---")

    def start(self):
        # Create a stop event for the video thread
        self.stop_event = threading.Event()

        # Run asyncio parts in a separate thread
        asyncio_thread = threading.Thread(target=lambda: asyncio.run(self.websocket_client()), daemon=True)
        asyncio_thread.start()

        # Run video processing in its own thread
        video_thread = threading.Thread(target=self.video_update_thread, args=(self.stop_event,), daemon=True)
        video_thread.start()

        # Start the GUI
        self.update_gui()
        self.mainloop()

        # When mainloop exits, signal the video thread to stop
        self.stop_event.set()

if __name__ == "__main__":
    app = DashboardApp()
    app.start()
