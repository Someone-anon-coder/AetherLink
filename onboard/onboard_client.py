import asyncio
import websockets
import json
import cv2
import time
from picamera2 import Picamera2
from concurrent.futures import ThreadPoolExecutor
import socket
from mavsdk import System

# --- CONFIGURATION ---
GCS_IP = "100.69.186.67"  # <-- USER: Set this to the Tailscale IP of the GCS laptop
GCS_PORT = 8765
GCS_VIDEO_PORT = 9999
VIDEO_RESOLUTION = (640, 480)
VIDEO_FRAMERATE = 30
JPEG_QUALITY = 80
SIMULATE_TELEMETRY = True # <-- New Flag

executor = ThreadPoolExecutor(max_workers=1)

class TelemetrySource:
    """
    Abstracts the source of telemetry data, supporting both real and simulated streams.
    """
    async def connect_real(self, telemetry_queue):
        """
        Connects to a real drone via MAVSDK and streams telemetry.
        """
        drone = System()
        print("INFO: Connecting to drone...")
        await drone.connect(system_address="serial:///dev/ttyAMA0:57600")

        async for state in drone.core.connection_state():
            if state.is_connected:
                print("INFO: Drone connected.")
                break

        async def stream_position():
            async for pos in drone.telemetry.position():
                await telemetry_queue.put({
                    'latitude': pos.latitude_deg,
                    'longitude': pos.longitude_deg,
                    'relative_altitude_m': pos.relative_altitude_m,
                })

        async def stream_velocity():
            async for vel in drone.telemetry.ground_speed_mps():
                await telemetry_queue.put({'ground_speed_mps': vel})

        async def stream_heading():
            async for head in drone.telemetry.heading():
                await telemetry_queue.put({'heading_deg': head.heading_deg})

        async def stream_battery():
            async for bat in drone.telemetry.battery():
                 await telemetry_queue.put({'battery_v': bat.voltage_v})

        await asyncio.gather(
            stream_position(),
            stream_velocity(),
            stream_heading(),
            stream_battery()
        )

    async def connect_sim(self, telemetry_queue):
        """
        Generates and streams simulated telemetry data.
        """
        print("INFO: Starting simulated telemetry stream.")
        lat, lon = 34.0522, -118.2437
        alt = 0
        while True:
            lat += 0.00001
            lon += 0.00001
            alt = (alt + 0.1) % 15

            telemetry_data = {
                'latitude': lat,
                'longitude': lon,
                'relative_altitude_m': alt,
                'ground_speed_mps': 5.2,
                'heading_deg': 45.0,
                'battery_v': 15.8
            }
            await telemetry_queue.put(telemetry_data)
            await asyncio.sleep(1)

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
    time.sleep(2.0)

    while True:
        frame = picam2.capture_array()
        _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
        
        try:
            udp_socket.sendto(buffer, gcs_address)
        except Exception as e:
            print(f"WARN: Could not send video frame via UDP: {e}")
            break
        time.sleep(1 / VIDEO_FRAMERATE)

async def telemetry_producer(websocket, telemetry_queue):
    """
    Reads from the telemetry queue and sends data over the WebSocket.
    """
    while True:
        telemetry_data = await telemetry_queue.get()
        telemetry_data['timestamp'] = time.time()
        message = json.dumps({
            'type': 'telemetry',
            'payload': telemetry_data
        })
        try:
            await websocket.send(message)
        except websockets.ConnectionClosed:
            print("WARN: Telemetry producer connection closed.")
            break

async def command_receiver(websocket):
    """
    Listens for and acts on commands from the GCS.
    """
    async for message in websocket:
        print(f"INFO: Received command from GCS: {message}")
        # Command execution logic would go here

async def run():
    """
    Main coroutine to connect to the GCS and manage data producers.
    """
    uri = f"ws://{GCS_IP}:{GCS_PORT}"
    loop = asyncio.get_running_loop()
    
    # Setup UDP socket for video
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    gcs_video_address = (GCS_IP, GCS_VIDEO_PORT)

    while True:
        try:
            async with websockets.connect(uri) as websocket:
                print(f"INFO: Connected to GCS at {uri}")

                # Create shared queues
                telemetry_queue = asyncio.Queue()

                # Instantiate and start telemetry source based on flag
                telemetry_source = TelemetrySource()
                if SIMULATE_TELEMETRY:
                    telemetry_connection_task = asyncio.create_task(telemetry_source.connect_sim(telemetry_queue))
                else:
                    telemetry_connection_task = asyncio.create_task(telemetry_source.connect_real(telemetry_queue))

                # Start other producers and consumers
                video_task = loop.run_in_executor(executor, video_producer_sync, udp_socket, gcs_video_address)
                telemetry_sender_task = asyncio.create_task(telemetry_producer(websocket, telemetry_queue))
                command_receiver_task = asyncio.create_task(command_receiver(websocket))

                done, pending = await asyncio.wait(
                    [video_task, telemetry_sender_task, command_receiver_task, telemetry_connection_task],
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
