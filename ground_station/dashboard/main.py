import asyncio
import base64
import io
import json
import queue
import threading
import websockets
import customtkinter
from PIL import Image, ImageTk
import socket
import cv2
import numpy as np
import time

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
        self.displayed_detections = set()


    def update_gui(self):
        try:
            data = self.data_queue.get_nowait()

            if data.get('type') == 'telemetry':
                self.lat_label.configure(text=f"Lat: {data.get('latitude', 0):.6f}")
                self.lon_label.configure(text=f"Lon: {data.get('longitude', 0):.6f}")
                self.alt_label.configure(text=f"Alt: {data.get('relative_altitude_m', 0):.2f} m")
                self.battery_label.configure(text=f"Battery: {data.get('battery_voltage', 0):.2f}%")

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

    def video_processing_thread(self):
        # GStreamer pipeline for receiving H.264 video over UDP
        pipeline = (
            "udpsrc port=5601 ! "
            "application/x-rtp, encoding-name=H264, payload=96 ! "
            "rtph264depay ! "
            "decodebin ! "
            "videoconvert ! "
            "appsink"
        )

        cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)

        if not cap.isOpened():
            print("Failed to open video capture pipeline.")
            return

        while True:
            ret, frame = cap.read()
            if ret:
                # Convert the BGR frame from OpenCV to RGB for Pillow
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                # Create a Pillow Image object
                pil_image = Image.fromarray(rgb_frame)

                # Create a CTkImage object
                ctk_image = customtkinter.CTkImage(light_image=pil_image, dark_image=pil_image, size=(640, 480))

                # Update the GUI. CTk calls are generally thread-safe for simple config changes.
                self.video_label.configure(image=ctk_image, text="")
            else:
                # Add a small delay to prevent a tight loop on read failure
                time.sleep(0.01)


    async def websocket_client(self):
        uri = f"ws://{COMMS_HUB_IP}:{COMMS_HUB_PORT}"
        # Create a UDP socket for the local relay
        local_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        local_address = ("127.0.0.1", 5601)

        while True:
            try:
                async for websocket in websockets.connect(uri):
                    print("Dashboard connected to Comms Hub.")
                    try:
                        async for message in websocket:
                            header = message[0]
                            payload = message[1:]

                            if header == 0x01: # Telemetry
                                try:
                                    data = json.loads(payload.decode('utf-8'))
                                    self.data_queue.put(data)
                                except (json.JSONDecodeError, UnicodeDecodeError):
                                    print("Failed to decode telemetry JSON.")

                            elif header == 0x02: # Video
                                # Relay the raw video packet to the local GStreamer instance
                                local_udp_socket.sendto(payload, local_address)

                    except websockets.ConnectionClosed:
                        print("Connection to Comms Hub closed. Retrying...")
                        continue
            except Exception as e:
                print(f"Failed to connect to Comms Hub: {e}. Retrying in 5 seconds...")
                await asyncio.sleep(5)

    def start(self):
        # --- Start WebSocket Network Thread ---
        def run_asyncio_loop():
            asyncio.run(self.websocket_client())

        network_thread = threading.Thread(target=run_asyncio_loop, daemon=True)
        network_thread.start()

        # --- Start Video Processing Thread ---
        video_thread = threading.Thread(target=self.video_processing_thread, daemon=True)
        video_thread.start()

        # --- Start GUI ---
        self.update_gui()
        self.mainloop()

if __name__ == "__main__":
    app = DashboardApp()
    app.start()
