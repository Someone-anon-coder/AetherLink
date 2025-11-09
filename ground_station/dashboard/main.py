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
        self.comms_hub_connected = asyncio.Event()

    def update_gui(self):
        try:
            data = self.data_queue.get_nowait()
            if data.get('type') == 'telemetry':
                self.lat_label.configure(text=f"Lat: {data.get('latitude', 0):.6f}")
                self.lon_label.configure(text=f"Lon: {data.get('longitude', 0):.6f}")
                self.alt_label.configure(text=f"Alt: {data.get('relative_altitude_m', 0):.2f} m")
                self.battery_label.configure(text=f"Battery: {data.get('battery_voltage', 0):.2f}%")
            elif data.get('type') == 'video_image':
                ctk_image = customtkinter.CTkImage(light_image=data['image'], dark_image=data['image'], size=(960, 720))
                self.video_label.configure(image=ctk_image, text="")
            elif data.get('type') == 'mission_state':
                self.mission_state_label.configure(text=f"Mission State: {data.get('state', 'N/A')}")
            elif data.get('type') == 'mission_log':
                self.mission_log.configure(state="normal")
                self.mission_log.insert('end', data.get('message', '') + '\n')
                self.mission_log.configure(state="disabled")
        except queue.Empty:
            pass
        finally:
            self.after(100, self.update_gui)

    async def websocket_client(self):
        uri = f"ws://{COMMS_HUB_IP}:{COMMS_HUB_PORT}"
        while True:
            try:
                async for websocket in websockets.connect(uri):
                    print("Dashboard connected to Comms Hub.")
                    self.comms_hub_connected.set()
                    try:
                        async for message in websocket:
                            self.data_queue.put(json.loads(message))
                    except websockets.ConnectionClosed:
                        print("Connection to Comms Hub closed. Retrying...")
                        self.comms_hub_connected.clear()
            except Exception as e:
                print(f"Failed to connect: {e}. Retrying...")
                self.comms_hub_connected.clear()
                await asyncio.sleep(5)

    async def video_update_loop(self):
        await self.comms_hub_connected.wait()
        print("Connection event received, starting video loop.")

        pipeline = (
            "udpsrc port=5602 ! application/x-rtp, encoding-name=H264, payload=96 ! "
            "rtph264depay ! decodebin ! videoconvert ! appsink"
        )
        cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
        if not cap.isOpened():
            print("Error: Could not open video stream.")
            return

        loop = asyncio.get_running_loop()
        while True:
            if not self.comms_hub_connected.is_set():
                print("Connection lost. Pausing video stream.")
                cap.release()
                await self.comms_hub_connected.wait()
                print("Reconnected. Restarting video stream.")
                cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)

            ret, frame = await loop.run_in_executor(None, cap.read)
            if ret:
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_image = Image.fromarray(rgb_frame)
                self.data_queue.put({'type': 'video_image', 'image': pil_image})
            else:
                # Small sleep to prevent a tight loop if cap.read() fails continuously
                await asyncio.sleep(0.1)

    def start(self):
        def _run_async_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(
                asyncio.gather(
                    self.websocket_client(),
                    self.video_update_loop()
                )
            )

        network_thread = threading.Thread(target=_run_async_loop, daemon=True)
        network_thread.start()

        self.update_gui()
        self.mainloop()

if __name__ == "__main__":
    app = DashboardApp()
    app.start()
