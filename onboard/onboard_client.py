import asyncio
import cv2
import time
import json
import random
import websockets
from picamera2 import Picamera2
from concurrent.futures import ThreadPoolExecutor
import socket
from mavsdk import System

# --- CONFIGURATION ---
SIMULATE_TELEMETRY = True  # Set to False to use a real Pixhawk
GCS_IP = "100.x.x.x"  # <-- USER: Set GCS Tailscale IP
GCS_WEBSOCKET_PORT = 8765
GCS_VIDEO_PORT = 9999
VIDEO_RESOLUTION = (640, 480)
VIDEO_FRAMERATE = 24
JPEG_QUALITY = 85

# Global executor for running blocking IO in a separate thread
executor = ThreadPoolExecutor(max_workers=2)

class SimulatedTelemetrySource:
    """Generates realistic-looking fake telemetry data."""
    def __init__(self):
        self.latitude = 47.6062
        self.longitude = -122.3321
        self.altitude = 100.0
        self.heading = 90.0
        self.battery_percentage = 99.0
        self.voltage = 16.8
        self.speed = 10.0
        print("INFO: Initialized SimulatedTelemetrySource.")

    async def get_telemetry(self):
        """Slightly alters and returns telemetry data."""
        self.latitude += random.uniform(-0.00001, 0.00001)
        self.longitude += random.uniform(-0.00001, 0.00001)
        self.altitude += random.uniform(-0.1, 0.1)
        self.heading = (self.heading + random.uniform(-0.5, 0.5)) % 360
        self.battery_percentage -= 0.001

        # Simulate voltage drop with battery percentage
        self.voltage = 14.0 + (self.battery_percentage / 100) * 2.8

        return {
            'latitude': self.latitude,
            'longitude': self.longitude,
            'altitude': self.altitude,
            'battery_percentage': self.battery_percentage,
            'voltage': self.voltage,
            'heading': self.heading,
            'speed': self.speed + random.uniform(-0.2, 0.2)
        }

class MavsdkTelemetrySource:
    """Connects to a Pixhawk and streams telemetry via MAVSDK."""
    def __init__(self):
        self.drone = System()
        self.latitude = None
        self.longitude = None
        self.altitude = None
        self.battery_percentage = None
        self.voltage = None
        self.heading = None
        self.speed = None
        self.connection_string = "serial:///dev/ttyACM0:57600"
        print("INFO: Initialized MavsdkTelemetrySource.")

    async def connect(self):
        print(f"INFO: Connecting to drone at {self.connection_string}...")
        await self.drone.connect(system_address=self.connection_string)

        print("INFO: Waiting for drone to connect...")
        async for state in self.drone.core.connection_state():
            if state.is_connected:
                print("INFO: Drone connected!")
                break

        # Start background tasks to update telemetry
        asyncio.create_task(self._update_position())
        asyncio.create_task(self._update_battery())
        asyncio.create_task(self._update_heading())
        asyncio.create_task(self._update_speed())
        print("INFO: MAVSDK telemetry update tasks started.")

    async def _update_position(self):
        async for position in self.drone.telemetry.position():
            self.latitude = position.latitude_deg
            self.longitude = position.longitude_deg
            self.altitude = position.relative_altitude_m

    async def _update_battery(self):
        async for battery in self.drone.telemetry.battery():
            self.battery_percentage = battery.remaining_percent * 100
            self.voltage = battery.voltage_v

    async def _update_heading(self):
        async for heading in self.drone.telemetry.heading():
            self.heading = heading.heading_deg

    async def _update_speed(self):
        async for speed in self.drone.telemetry.velocity_ned():
            self.speed = (speed.north_m_s**2 + speed.east_m_s**2)**0.5

    async def get_telemetry(self):
        """Returns the latest available telemetry data."""
        return {
            'latitude': self.latitude,
            'longitude': self.longitude,
            'altitude': self.altitude,
            'battery_percentage': self.battery_percentage,
            'voltage': self.voltage,
            'heading': self.heading,
            'speed': self.speed
        }

def video_producer_sync(udp_socket, gcs_address):
    """
    Synchronous function for video capture. Runs in a separate thread.
    """
    print("INFO: Initializing camera...")
    try:
        picam2 = Picamera2()
        config = picam2.create_video_configuration(main={"size": VIDEO_RESOLUTION})
        picam2.configure(config)
        picam2.start()
        print("INFO: Camera initialized.")
        time.sleep(2.0)  # Allow camera to warm up
    except Exception as e:
        print(f"FATAL: Could not initialize camera: {e}. Is it connected?")
        return

    while True:
        try:
            frame = picam2.capture_array()
            _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])

            # This is a blocking call, but UDP is fast.
            udp_socket.sendto(buffer, gcs_address)
        except Exception as e:
            print(f"ERROR: Could not capture or send video frame: {e}")
            break

        # A small sleep to yield control and prevent pegging the CPU
        time.sleep(1 / (VIDEO_FRAMERATE * 2))

async def telemetry_producer(websocket, telemetry_source):
    """
    Coroutine that fetches telemetry and sends it over WebSocket.
    """
    while True:
        try:
            data = await telemetry_source.get_telemetry()
            payload = {
                "type": "telemetry",
                "payload": data
            }
            await websocket.send(json.dumps(payload))
            await asyncio.sleep(0.1)  # 10 Hz telemetry update rate
        except websockets.exceptions.ConnectionClosed:
            print("INFO: GCS connection closed.")
            break
        except Exception as e:
            print(f"ERROR: Telemetry producer failed: {e}")
            break


async def run():
    """
    Main coroutine to set up connections and run producers.
    """
    loop = asyncio.get_running_loop()
    
    # --- Initialize Telemetry Source ---
    if SIMULATE_TELEMETRY:
        telemetry_source = SimulatedTelemetrySource()
    else:
        telemetry_source = MavsdkTelemetrySource()
        try:
            await telemetry_source.connect()
        except Exception as e:
            print(f"FATAL: Could not connect to drone: {e}. Is it powered and connected?")
            return # Exit if we can't connect

    # --- Initialize Video UDP Socket ---
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    gcs_video_address = (GCS_IP, GCS_VIDEO_PORT)
    print(f"INFO: Streaming video to {gcs_video_address}")

    # --- Start Video Producer Thread ---
    loop.run_in_executor(
        executor, video_producer_sync, udp_socket, gcs_video_address
    )

    # --- WebSocket Connection Loop ---
    uri = f"ws://{GCS_IP}:{GCS_WEBSOCKET_PORT}"
    while True:
        try:
            print(f"INFO: Connecting to GCS WebSocket at {uri}...")
            async with websockets.connect(uri) as websocket:
                print("INFO: GCS WebSocket connected.")
                # Start the telemetry producer once connected
                await telemetry_producer(websocket, telemetry_source)
        except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError, OSError) as e:
            print(f"WARN: WebSocket connection failed: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"FATAL: An unexpected error occurred in the run loop: {e}")
            break

    udp_socket.close()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("INFO: Shutting down onboard client.")
    finally:
        # This ensures the video thread is cleaned up.
        executor.shutdown(wait=False, cancel_futures=True)