import asyncio
import websockets
import json
import cv2
import base64
import time
from picamera2 import Picamera2
from concurrent.futures import ThreadPoolExecutor
import socket
from mavsdk import System
import random

# --- CONFIGURATION ---
GCS_IP = "100.69.186.67"  # <-- USER: Set this to the Tailscale IP of the GCS laptop
GCS_PORT = 8765
GCS_VIDEO_PORT = 9999
VIDEO_RESOLUTION = (640, 480)
VIDEO_FRAMERATE = 30
JPEG_QUALITY = 80
USE_SIMULATED_TELEMETRY = True

# --- TELEMETRY ABSTRACTION ---
class TelemetrySource:
    """Abstract base class for telemetry sources."""
    async def get_telemetry(self):
        raise NotImplementedError

class SimulatedTelemetrySource(TelemetrySource):
    """Generates simulated telemetry data."""
    def __init__(self):
        self._latitude = 12.34
        self._longitude = 56.78
        self._altitude = 150.5
        self._speed = 25.2
        self._heading = 90

    async def get_telemetry(self):
        # Simulate slight variations in data
        self._latitude += random.uniform(-0.0001, 0.0001)
        self._longitude += random.uniform(-0.0001, 0.0001)
        self._altitude += random.uniform(-0.5, 0.5)
        self._speed += random.uniform(-0.1, 0.1)
        self._heading = (self._heading + random.uniform(-1, 1)) % 360
        return {
            'latitude': self._latitude,
            'longitude': self._longitude,
            'altitude': self._altitude,
            'speed': self._speed,
            'heading': self._heading,
            'timestamp': time.time()
        }

class MavsdkTelemetrySource(TelemetrySource):
    """Fetches telemetry data from a MAVSDK drone connection."""
    def __init__(self):
        self.drone = System()
        self._telemetry = {}

    async def connect(self):
        print("INFO: Connecting to drone...")
        await self._drone.connect(system_address="udp://:14540")
        print("INFO: Drone connected.")

        async def update_position():
            async for position in self._drone.telemetry.position():
                self._telemetry['latitude'] = position.latitude_deg
                self._telemetry['longitude'] = position.longitude_deg
                self._telemetry['altitude'] = position.relative_altitude_m

        async def update_velocity():
            async for velocity in self._drone.telemetry.velocity_ned():
                self._telemetry['speed'] = (velocity.north_m_s**2 + velocity.east_m_s**2)**0.5

        async def update_heading():
            async for heading in self._drone.telemetry.heading():
                self._telemetry['heading'] = heading.heading_deg

        asyncio.create_task(update_position())
        asyncio.create_task(update_velocity())
        asyncio.create_task(update_heading())

    async def get_telemetry(self):
        self._telemetry['timestamp'] = time.time()
        return self._telemetry

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

async def telemetry_producer(websocket, telemetry_source):
    """
    Coroutine to produce and send telemetry data from a given source.
    """
    while True:
        telemetry_data = await telemetry_source.get_telemetry()
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

async def receiver(websocket, telemetry_source):
    """
    Coroutine to listen for incoming messages from the GCS and execute commands.
    """
    async for message in websocket:
        try:
            command_data = json.loads(message)
            command_type = command_data.get('type')
            payload = command_data.get('payload', {})
            print(f"INFO: Received command '{command_type}' from GCS.")

            if USE_SIMULATED_TELEMETRY:
                print(f"SIMULATE_CMD: Would execute '{command_type}' with payload: {payload}")
                continue

            drone = telemetry_source.drone
            if not drone:
                print("WARN: Drone is not connected. Cannot execute command.")
                continue

            if command_type == 'GOTO_LOCATION':
                await drone.action.goto_location(
                    payload['latitude'],
                    payload['longitude'],
                    payload['altitude'],
                    payload['yaw']
                )
            elif command_type == 'SET_SERVO':
                await drone.action.set_actuator(
                    payload['actuator'],
                    payload['value']
                )
            elif command_type == 'RTL':
                await drone.action.return_to_launch()
            else:
                print(f"WARN: Unknown command type '{command_type}'")

        except json.JSONDecodeError:
            print(f"WARN: Received non-JSON message: {message}")
        except Exception as e:
            print(f"ERROR: Error processing command: {e}")

async def run():
    """
    Main coroutine to connect to the GCS and manage data producers.
    """
    uri = f"ws://{GCS_IP}:{GCS_PORT}"
    loop = asyncio.get_running_loop()
    
    # Initialize telemetry source
    if USE_SIMULATED_TELEMETRY:
        telemetry_source = SimulatedTelemetrySource()
        print("INFO: Using simulated telemetry source.")
    else:
        telemetry_source = MavsdkTelemetrySource()
        await telemetry_source.connect()
        print("INFO: Using MAVSDK telemetry source.")

    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    gcs_video_address = (GCS_IP, GCS_VIDEO_PORT)

    while True:
        try:
            async with websockets.connect(uri) as websocket:
                print(f"INFO: Connected to GCS at {uri}")

                video_task = loop.run_in_executor(
                    executor, video_producer_sync, udp_socket, gcs_video_address
                )
                telemetry_task = asyncio.create_task(telemetry_producer(websocket, telemetry_source))
                receiver_task = asyncio.create_task(receiver(websocket, telemetry_source))

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
