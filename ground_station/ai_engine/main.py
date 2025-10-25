import asyncio
import websockets
import json
from ultralytics import YOLO
import cv2
import numpy as np
import base64

# --- CONFIGURATION ---
# The IP address should be the Tailscale IP of the machine running the Comms Hub.
COMMS_HUB_IP = "100.99.103.27"
COMMS_HUB_PORT = 8765

# Load the trained YOLOv8 model once.
model = YOLO('best.pt')

async def run():
    """
    Connects to the Comms Hub WebSocket server and processes incoming data.
    """
    uri = f"ws://{COMMS_HUB_IP}:{COMMS_HUB_PORT}"
    async for websocket in websockets.connect(uri):
        try:
            print(f"--- Connected to Comms Hub at {uri} ---")
            async for message in websocket:
                data = json.loads(message)
                if 'type' in data:
                    if data['type'] == 'telemetry':
                        print(f"Received TELEMETRY: Lat={data.get('latitude', 'N/A')}, Alt={data.get('relative_altitude_m', 'N/A')}")
                    elif data['type'] == 'video_frame':
                        # a. Decode the Base64-encoded frame data back into bytes.
                        frame_bytes = base64.b64decode(data['frame_data_b64'])

                        # b. Use np.frombuffer() to convert the bytes into a NumPy array.
                        image_np = np.frombuffer(frame_bytes, np.uint8)

                        # c. Use cv2.imdecode() to convert the NumPy array into a full-color image that OpenCV can use.
                        image = cv2.imdecode(image_np, cv2.IMREAD_COLOR)

                        # d. Run the model on the image
                        results = model(image, verbose=False)

                        # e. Get the first result object
                        result = results[0]

                        # g. Print the original "Received VIDEO FRAME" log message.
                        print(f"Received VIDEO FRAME: ID={data.get('frame_id', 'N/A')}, Size={len(data['frame_data_b64'])} bytes")

                        # f. Check if any objects were detected
                        if len(result.boxes) > 0:
                            # h. If objects were detected, loop through the detected boxes
                            for box in result.boxes:
                                # i. Inside the loop, extract the class ID, get the class name from model.names, and get the confidence score.
                                class_id = int(box.cls[0])
                                class_name = model.names[class_id]
                                confidence = box.conf[0]

                                # j. Print a formatted log for each detection, indented to show it's related to the frame
                                print(f"    DETECTED: {class_name} with confidence {confidence:.2f}")

        except websockets.ConnectionClosed:
            print("--- Connection to Comms Hub lost. Attempting to reconnect... ---")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(run())
