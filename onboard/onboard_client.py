import asyncio
import websockets
import json
import cv2
import base64
import time
from picamera2 import Picamera2
from concurrent.futures import ThreadPoolExecutor
import socket

# --- CONFIGURATION ---
GCS_IP = "100.69.186.67"  # <-- USER: Set this to the Tailscale IP of the GCS laptop
GCS_PORT = 8765
GCS_VIDEO_PORT = 9999
VIDEO_RESOLUTION = (640, 480)
VIDEO_FRAMERATE = 30
JPEG_QUALITY = 80

executor = ThreadPoolExecutor(max_workers=1)

def video_producer_sync(udp_socket, gcs_address):
    """
    Synchronous function for video capture. Runs in a separate thread.
    """
    print("INFO: Initializing camera...")
    picam2 = Picamera2()
    config = picam2.create_video_configuration(main={"size": VIDEO_RESOLUTION})
    picam2.configure(config)
    picam2.start()
    print("INFO: Camera initialized.")
    time.sleep(2.0)  # Allow camera to warm up

    while True:
        frame = picam2.capture_array()
        _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
        
        try:
            udp_socket.sendto(buffer, gcs_address)
        except Exception as e:
            print(f"WARN: Could not send video frame via UDP: {e}")
            break

        time.sleep(1 / VIDEO_FRAMERATE)

async def telemetry_producer(websocket):
    """
    Coroutine to produce and send simulated telemetry data.
    """
    while True:
        telemetry_data = {
            'latitude': 12.34,
            'longitude': 56.78,
            'altitude': 150.5,
            'speed': 25.2,
            'heading': 90,
            'timestamp': time.time()
        }
        message = json.dumps({
            'type': 'telemetry',
            'payload': telemetry_data
        })
        try:
            await websocket.send(message)
        except websockets.ConnectionClosed:
            print("WARN: Telemetry producer connection closed.")
            break
        await asyncio.sleep(1)

async def receiver(websocket):
    """
    Coroutine to listen for incoming messages from the GCS.
    """
    async for message in websocket:
        print(f"INFO: Received message from GCS: {message}")

async def run():
    """
    Main coroutine to connect to the GCS and manage data producers.
    """
    uri = f"ws://{GCS_IP}:{GCS_PORT}"
    loop = asyncio.get_running_loop()
    
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    gcs_video_address = (GCS_IP, GCS_VIDEO_PORT)

    while True:
        try:
            async with websockets.connect(uri) as websocket:
                print(f"INFO: Connected to GCS at {uri}")

                video_task = loop.run_in_executor(
                    executor, video_producer_sync, udp_socket, gcs_video_address
                )
                telemetry_task = asyncio.create_task(telemetry_producer(websocket))
                receiver_task = asyncio.create_task(receiver(websocket))

                done, pending = await asyncio.wait(
                    [video_task, telemetry_task, receiver_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in pending:
                    task.cancel()

        except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as e:
            print(f"WARN: Connection lost ({e}). Retrying in 5 seconds...")
        except Exception as e:
            print(f"ERROR: An unexpected error occurred: {e}")

        await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("INFO: Shutting down client.")
    finally:
        executor.shutdown(wait=False)
