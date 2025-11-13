import asyncio
import websockets
import json
import cv2
import numpy as np
import customtkinter
from PIL import Image, ImageTk
import threading
import queue
import socket
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# --- CONFIGURATION ---
WEBSOCKET_PORT = 8765
VIDEO_PORT = 9999

# --- VIDEO FORWARDING CONFIGURATION ---
ENABLE_VIDEO_FORWARDING = False # Set to True to forward the stream
FORWARD_TO_IP = "100.122.254.14" # <-- USER: Set Tailscale IP of the second device (e.g., Pi with screen)
FORWARD_TO_PORT = 5600 # Standard video streaming port

class Dashboard(customtkinter.CTk):
    """Main GUI application window."""
    def __init__(self, video_q, telemetry_q):
        super().__init__()
        self.video_queue = video_q
        self.telemetry_queue = telemetry_q

        self.title("AetherLink GCS Dashboard")
        self.geometry("1440x810")

        # --- Layout ---
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- Video Panel ---
        self.video_frame = customtkinter.CTkFrame(self)
        self.video_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.video_frame.grid_propagate(False) # Prevent frame from resizing
        self.video_label = customtkinter.CTkLabel(self.video_frame, text="Waiting for video feed...")
        self.video_label.pack(padx=10, pady=10, expand=True, fill="both")

        # --- Data & Control Panel ---
        self.data_frame = customtkinter.CTkFrame(self)
        self.data_frame.grid(row=0, column=1, padx=(0, 10), pady=10, sticky="nsew")
        self.data_frame.grid_rowconfigure(2, weight=1) # Graph expands

        # --- Connection Status ---
        self.conn_status_label = customtkinter.CTkLabel(
            self.data_frame, text="DISCONNECTED", text_color="red",
            font=customtkinter.CTkFont(size=18, weight="bold")
        )
        self.conn_status_label.grid(row=0, column=0, columnspan=2, padx=10, pady=10, sticky="ew")

        # --- Telemetry Display ---
        self._create_telemetry_labels()

        # --- Matplotlib Altitude Graph ---
        self.graph_frame = customtkinter.CTkFrame(self.data_frame)
        self.graph_frame.grid(row=2, column=0, columnspan=2, padx=10, pady=10, sticky="nsew")

        self.fig = Figure(figsize=(5, 3), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title("Altitude (m)")
        self.ax.set_xlabel("Time")
        self.ax.set_ylabel("Altitude")
        self.altitude_history = [0] * 100 # Store last 100 data points

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.graph_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(side="top", fill="both", expand=True)
        self.fig.tight_layout()

        # Start the periodic update of widgets
        self.after(50, self.update_widgets)

    def _create_telemetry_labels(self):
        """Creates and grids all the telemetry labels."""
        telemetry_grid = customtkinter.CTkFrame(self.data_frame)
        telemetry_grid.grid(row=1, column=0, columnspan=2, padx=10, pady=10, sticky="ew")

        labels_info = {
            "Lat:": (0, 0), "Lon:": (0, 1),
            "Alt:": (1, 0), "Speed:": (1, 1),
            "Heading:": (2, 0), "Battery:": (3, 0),
            "Voltage:": (3, 1)
        }
        self.telemetry_labels = {}
        for text, (row, col) in labels_info.items():
            label = customtkinter.CTkLabel(telemetry_grid, text=f"{text} N/A", font=customtkinter.CTkFont(size=14))
            label.grid(row=row, column=col, padx=10, pady=5, sticky="w")
            self.telemetry_labels[text] = label
            telemetry_grid.grid_columnconfigure(col, weight=1)

    def update_connection_status(self, is_connected):
        if is_connected:
            self.conn_status_label.configure(text="CONNECTED", text_color="#2ECC71")
        else:
            self.conn_status_label.configure(text="DISCONNECTED", text_color="#E74C3C")

    def update_widgets(self):
        """Periodically updates GUI with data from queues."""
        # --- Update Telemetry ---
        try:
            telemetry = self.telemetry_queue.get_nowait()
            self.telemetry_labels["Lat:"].configure(text=f"Lat: {telemetry.get('latitude', 0)}")
            self.telemetry_labels["Lon:"].configure(text=f"Lon: {telemetry.get('longitude', 0)}")
            self.telemetry_labels["Alt:"].configure(text=f"Alt: {telemetry.get('altitude', 0)} m")
            self.telemetry_labels["Speed:"].configure(text=f"Speed: {telemetry.get('speed', 0)} m/s")
            self.telemetry_labels["Heading:"].configure(text=f"Heading: {telemetry.get('heading', 0)}°")
            self.telemetry_labels["Battery:"].configure(text=f"Battery: {telemetry.get('battery_percentage', 0)}%")
            self.telemetry_labels["Voltage:"].configure(text=f"Voltage: {telemetry.get('voltage', 0)}V")

            # --- Update Altitude Graph ---
            self.altitude_history.pop(0)
            self.altitude_history.append(telemetry.get('altitude', 0))
            self.ax.clear()
            self.ax.plot(self.altitude_history)
            self.ax.set_title("Altitude (m)")
            self.ax.set_xticklabels([]) # Hide x-axis labels for clarity
            self.canvas.draw()

        except queue.Empty:
            pass # No new telemetry data

        # --- Update Video ---
        try:
            frame = self.video_queue.get_nowait()
            # Get the size of the video_frame to resize the image appropriately
            frame_w = self.video_frame.winfo_width()
            frame_h = self.video_frame.winfo_height()

            img = Image.fromarray(frame)
            ctk_image = customtkinter.CTkImage(img, size=(frame_w - 20, frame_h - 20)) # -20 for padding
            self.video_label.configure(image=ctk_image, text="")
        except queue.Empty:
            pass # No new video frame
        except Exception as e:
            # This can happen on first launch if the window size is 0
            # print(f"DEBUG: Could not update video frame: {e}")
            pass

        # Schedule next update
        self.after(50, self.update_widgets)

def video_receiver_thread(video_q):
    """
    Thread function to receive UDP video frames.
    """
    # Create the main socket for receiving video
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", VIDEO_PORT))
    print(f"INFO: Video receiver listening on port {VIDEO_PORT}")

    # Create the forwarding socket if enabled
    forwarding_socket = None
    if ENABLE_VIDEO_FORWARDING:
        forwarding_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        print(f"INFO: Video forwarding enabled. Sending to {FORWARD_TO_IP}:{FORWARD_TO_PORT}")

    while True:
        try:
            packet, _ = sock.recvfrom(65536) # Buffer size

            # Forward the raw packet immediately
            if ENABLE_VIDEO_FORWARDING and forwarding_socket:
                forwarding_socket.sendto(packet, (FORWARD_TO_IP, FORWARD_TO_PORT))

            # Decode for local display
            np_arr = np.frombuffer(packet, np.uint8)
            image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

            if image is not None:
                # Convert from BGR (OpenCV default) to RGB (Pillow/Tkinter standard)
                #rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                rgb_image = image
                try:
                    video_q.put_nowait(rgb_image)
                except queue.Full:
                    # Discard frame if GUI is lagging
                    pass
        except Exception as e:
            print(f"ERROR: Video receiver failed: {e}")
            break # Exit loop on error

    sock.close()
    if forwarding_socket:
        forwarding_socket.close()

def websocket_server_thread(telemetry_q, dashboard_ref):
    """
    Thread function to run the asyncio WebSocket server.
    """
    async def handler(websocket):
        """Handles incoming WebSocket connections."""
        print(f"INFO: Onboard client connected from {websocket.remote_address}")
        # Use lambda to schedule GUI update in main thread
        dashboard_ref.after(0, lambda: dashboard_ref.update_connection_status(True))
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    if data.get('type') == 'telemetry':
                        telemetry_q.put(data.get('payload')) # This is a thread-safe queue
                except json.JSONDecodeError:
                    print(f"WARN: Received non-JSON message from client.")
        except websockets.exceptions.ConnectionClosed:
            print(f"INFO: Onboard client disconnected.")
        finally:
            dashboard_ref.after(0, lambda: dashboard_ref.update_connection_status(False))

    async def start_server():
        """Starts the WebSocket server."""
        print(f"INFO: WebSocket server listening on port {WEBSOCKET_PORT}")
        async with websockets.serve(handler, "0.0.0.0", WEBSOCKET_PORT):
            await asyncio.Future() # Run forever

    # Create and run a new asyncio event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_server())

if __name__ == "__main__":
    # Thread-safe queues for communication
    video_queue = queue.Queue(maxsize=2)
    telemetry_queue = queue.Queue(maxsize=10)

    # Instantiate the dashboard
    app = Dashboard(video_q=video_queue, telemetry_q=telemetry_queue)

    # Create and start daemon threads
    video_thread = threading.Thread(
        target=video_receiver_thread, args=(video_queue,), daemon=True
    )
    websocket_thread = threading.Thread(
        target=websocket_server_thread, args=(telemetry_queue, app), daemon=True
    )

    video_thread.start()
    websocket_thread.start()

    # Start the GUI main loop (must be in the main thread)
    app.mainloop()
