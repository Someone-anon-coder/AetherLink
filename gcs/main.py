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

# --- CONFIGURATION ---
GCS_WS_PORT = 8765
GCS_VIDEO_UDP_PORT = 9999
HOST = "0.0.0.0"

class VideoReceiverProtocol(asyncio.DatagramProtocol):
    def __init__(self, video_queue):
        super().__init__()
        self.video_queue = video_queue

    def datagram_received(self, data, addr):
        """
        Handles incoming UDP packets.
        """
        try:
            np_arr = np.frombuffer(data, np.uint8)
            image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

            if image is not None:
                self.video_queue.put_nowait(image)
            else:
                print("WARN: Failed to decode UDP video frame.")

        except queue.Full:
            print("WARN: GUI video queue is full, dropping frame.")
        except Exception as e:
            print(f"ERROR: Could not process UDP packet: {e}")

async def udp_video_receiver(video_queue):
    """
    Coroutine to set up and run the UDP server for video.
    """
    loop = asyncio.get_running_loop()
    print(f"INFO: Starting UDP video receiver on {HOST}:{GCS_VIDEO_UDP_PORT}")

    transport, protocol = await loop.create_datagram_endpoint(
        lambda: VideoReceiverProtocol(video_queue),
        local_addr=(HOST, GCS_VIDEO_UDP_PORT)
    )

    try:
        await asyncio.Future()
    finally:
        transport.close()

class GCSApp:
    def __init__(self):
        self.video_for_gui_queue = queue.Queue(maxsize=10) # Bounded queue
        self.telemetry_for_gui_queue = queue.Queue()
        self.detections_for_mission_logic_queue = asyncio.Queue()
        self.telemetry_for_mission_logic_queue = asyncio.Queue()

    async def websocket_handler(self, websocket):
        print(f"INFO: Onboard system connected from {websocket.remote_address}")
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    if data.get('type') == 'telemetry':
                        payload = data.get('payload')
                        # print(f"DEBUG: Received TELEMETRY packet: {payload}")
                        self.telemetry_for_gui_queue.put_nowait(payload)
                        await self.telemetry_for_mission_logic_queue.put(payload)
                    else:
                        print(f"WARN: Received unknown message type on WebSocket: {data.get('type')}")
                except json.JSONDecodeError:
                    print(f"WARN: Received non-JSON message: {message}")
                except queue.Full:
                    print("WARN: GUI telemetry queue is full.")

        except websockets.ConnectionClosed as e:
            print(f"INFO: Connection with {websocket.remote_address} closed: {e}")
        finally:
            print(f"INFO: Onboard system {websocket.remote_address} disconnected.")

    async def start_server(self):
        async with websockets.serve(self.websocket_handler, HOST, GCS_WS_PORT):
            print(f"INFO: GCS WebSocket server started on ws://{HOST}:{GCS_WS_PORT}")
            await asyncio.Future()

class Dashboard(customtkinter.CTk):
    def __init__(self, video_queue, telemetry_queue, detections_queue_async):
        super().__init__()

        self.video_queue = video_queue
        self.telemetry_queue = telemetry_queue
        self.detections_queue_async = detections_queue_async
        self.loop = asyncio.get_running_loop()

        # Initialize DataProcessor here, so the model is in the GUI thread
        self.data_processor = DataProcessor()
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
        except queue.Empty:
            pass

        # Update video and run inference
        try:
            frame = self.video_queue.get_nowait()
            if frame is not None:
                # Run inference
                processed_frame, detections = self.data_processor.process_frame(frame)

                # Send detections to mission logic
                if detections:
                    asyncio.run_coroutine_threadsafe(self.detections_queue_async.put(detections), self.loop)

                # Display the frame
                img = cv2.cvtColor(processed_frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(img)
                ctk_image = customtkinter.CTkImage(light_image=img, dark_image=img, size=(960, 540))
                self.video_label.configure(image=ctk_image, text="")
        except queue.Empty:
            pass

        self.after(33, self.update_widgets)

class DataProcessor:
    def __init__(self):
        self.model = YOLO('best.pt')
        print("INFO: YOLO model loaded.")

    def process_frame(self, image):
        # This is now a synchronous method
        results = self.model(image, verbose=False)
        detections = []

        # Drawing boxes on the image
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

                # Draw the bounding box
                cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
                label = f"{class_name}: {confidence:.2f}"
                cv2.putText(image, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        return image, detections

def run_gui(app):
    gui = Dashboard(
        app.video_for_gui_queue,
        app.telemetry_for_gui_queue,
        app.detections_for_mission_logic_queue
    )
    gui.mainloop()

async def mission_logic_consumer(app):
    while True:
        detections = await app.detections_for_mission_logic_queue.get()
        print(f"MISSION_LOGIC: Received {len(detections)} detections.")
        # We can also consume telemetry here if needed:
        # telemetry = await app.telemetry_for_mission_logic_queue.get()

async def main():
    app = GCSApp()

    gui_thread = threading.Thread(
        target=run_gui,
        args=(app,),
        daemon=True
    )
    gui_thread.start()

    await asyncio.gather(
        app.start_server(),
        udp_video_receiver(app.video_for_gui_queue),
        mission_logic_consumer(app)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("INFO: Shutting down GCS application.")
