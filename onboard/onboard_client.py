import asyncio
import websockets
import json
import cv2
import time
import socket
from picamera2 import Picamera2
from concurrent.futures import ThreadPoolExecutor

# --- CONFIGURATION ---
GCS_IP = "100.x.x.x"  # <-- USER: Set this to the Tailscale IP of the GCS laptop
GCS_WS_PORT = 8765
GCS_VIDEO_UDP_PORT = 9999
VIDEO_RESOLUTION = (640, 480)
VIDEO_FRAMERATE = 30
JPEG_QUALITY = 80

executor = ThreadPoolExecutor(max_workers=2)

def udp_video_producer_sync():
    """
    Synchronous function for video capture and UDP streaming. Runs in a separate thread.
    """
    print("INFO: Initializing camera for UDP stream...")
    picam2 = Picamera2()
    config = picam2.create_video_configuration(main={"size": VIDEO_RESOLUTION})
    picam2.configure(config)
    picam2.start()
    print("INFO: Camera initialized.")
    time.sleep(2.0)  # Allow camera to warm up

    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    gcs_address = (GCS_IP, GCS_VIDEO_UDP_PORT)
    print(f"INFO: Streaming video to {gcs_address} via UDP.")

    while True:
        try:
            frame = picam2.capture_array()
            _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])

            if buffer.nbytes > 65507:
                print(f"WARN: Frame size ({buffer.nbytes} bytes) is larger than UDP limit; skipping.")
                continue

            udp_socket.sendto(buffer.tobytes(), gcs_address)

        except Exception as e:
            print(f"ERROR: Video producer failed: {e}")
            break

        time.sleep(1 / VIDEO_FRAMERATE)

    udp_socket.close()
    print("INFO: UDP video producer stopped.")

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
    loop = asyncio.get_running_loop()

    # Start the blocking UDP video producer in a separate thread.
    # This runs independently of the WebSocket connection.
    loop.run_in_executor(executor, udp_video_producer_sync)

    uri = f"ws://{GCS_IP}:{GCS_WS_PORT}"

    while True:
        try:
            async with websockets.connect(uri) as websocket:
                print(f"INFO: Connected to GCS at {uri}")

                # Only telemetry and command receiver run over WebSocket now
                telemetry_task = asyncio.create_task(telemetry_producer(websocket))
                receiver_task = asyncio.create_task(receiver(websocket))

                done, pending = await asyncio.wait(
                    [telemetry_task, receiver_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in pending:
                    task.cancel()

        except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as e:
            print(f"WARN: WebSocket connection lost ({e}). Retrying in 5 seconds...")
        except Exception as e:
            print(f"ERROR: An unexpected error occurred in WebSocket task: {e}")

        await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("INFO: Shutting down client.")
    finally:
        executor.shutdown(wait=False)
