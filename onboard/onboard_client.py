import asyncio
import cv2
import time
from picamera2 import Picamera2
from concurrent.futures import ThreadPoolExecutor
import socket

# --- CONFIGURATION ---
GCS_IP = "100.69.186.67"  # <-- USER: Set this to the Tailscale IP of the GCS laptop
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
        try:
            frame = picam2.capture_array()
            _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])

            udp_socket.sendto(buffer, gcs_address)
        except Exception as e:
            print(f"ERROR: Could not capture or send video frame: {e}")
            break

        # A small sleep to prevent overwhelming the CPU, but the primary rate
        # limit is the camera's framerate itself.
        time.sleep(1 / (VIDEO_FRAMERATE * 2))

async def main():
    """
    Main coroutine to run the video producer.
    """
    loop = asyncio.get_running_loop()
    
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    gcs_video_address = (GCS_IP, GCS_VIDEO_PORT)
    print(f"INFO: Streaming video to {GCS_IP}:{GCS_VIDEO_PORT}")

    # Start the blocking video capture in a separate thread
    video_task = loop.run_in_executor(
        executor, video_producer_sync, udp_socket, gcs_video_address
    )

    try:
        await video_task
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"ERROR: Video producer task failed: {e}")
    finally:
        udp_socket.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("INFO: Shutting down video client.")
    finally:
        executor.shutdown(wait=False)
