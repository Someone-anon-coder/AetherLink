import asyncio
import json
import queue
import socket
import subprocess
import threading
import websockets
import customtkinter
from PIL import Image, ImageTk

# <-- USER: Set this to the Tailscale IP of the Comms Hub machine
COMMS_HUB_IP = "100.69.186.67"
COMMS_HUB_PORT = 8765
VIDEO_PORT = 9999
GSTREAMER_VIDEO_PORT = 5601


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
        self.video_label = customtkinter.CTkFrame(self, width=1280, height=720)
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

        self.after(100, self.start_gstreamer)

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

    async def websocket_client(self):
        # Register for video stream
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(b'register', (COMMS_HUB_IP, VIDEO_PORT))

        uri = f"ws://{COMMS_HUB_IP}:{COMMS_HUB_PORT}"
        while True:
            try:
                async for websocket in websockets.connect(uri):
                    print("Dashboard connected to Comms Hub.")
                    try:
                        async for message in websocket:
                            data = json.loads(message)
                            self.data_queue.put(data)
                    except websockets.ConnectionClosed:
                        print("Connection to Comms Hub closed. Retrying...")
                        continue
            except Exception as e:
                print(f"Failed to connect to Comms Hub: {e}. Retrying in 5 seconds...")
                await asyncio.sleep(5)

    def start_gstreamer(self):
        def run_gstreamer(xid):
            pipeline = (
                f"gst-launch-1.0 udpsrc port={GSTREAMER_VIDEO_PORT} ! "
                "application/x-rtp, media=video, clock-rate=90000, encoding-name=H264, payload=96 ! "
                "rtph264depay ! decodebin ! videoconvert ! "
                f"ximagesink window-xid={xid}"
            )
            subprocess.Popen(pipeline, shell=True)

        xid = self.video_label.winfo_id()
        gstreamer_thread = threading.Thread(target=run_gstreamer, args=(xid,), daemon=True)
        gstreamer_thread.start()

    def start(self):
        def run_asyncio_loop():
            asyncio.run(self.websocket_client())

        network_thread = threading.Thread(target=run_asyncio_loop, daemon=True)
        network_thread.start()

        self.update_gui()
        self.mainloop()


if __name__ == "__main__":
    app = DashboardApp()
    app.start()
