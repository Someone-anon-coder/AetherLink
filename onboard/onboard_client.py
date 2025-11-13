import asyncio
import cv2
import time
import json
import random
import websockets
import math
import mavsdk
from picamera2 import Picamera2
from concurrent.futures import ThreadPoolExecutor
import socket

# --- CONFIGURATION ---
SIMULATE_TELEMETRY = True  # Set to False to use a real Pixhawk
GCS_IP = "100.69.186.67"  # <-- USER: Set GCS Tailscale IP
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
        self._latitude_deg = 47.6062
        self._longitude_deg = -122.3321
        self._altitude_m = 100.0
        self._heading_deg = 90.0
        self._time_counter = 0

    async def get_telemetry(self):
        """Generates oscillating and rotating fake data."""
        self._time_counter += 0.1
        
        # Oscillate altitude
        altitude = self._altitude_m + 5 * math.sin(self._time_counter)
        
        # Slowly rotate heading
        heading = (self._heading_deg + self._time_counter * 5) % 360
        
        # Slightly change lat/lon
        lat = self._latitude_deg + 0.0001 * math.cos(self._time_counter / 10)
        lon = self._longitude_deg + 0.0001 * math.sin(self._time_counter / 10)

        return {
            "latitude": lat,
            "longitude": lon,
            "altitude": altitude,
            "battery_percentage": 95.0 - (self._time_counter / 20),
            "voltage": 16.4 - (self._time_counter / 100),
            "heading": heading,
            "speed": 12.5 + math.sin(self._time_counter),
        }

class MavsdkTelemetrySource:
    """Provides real telemetry data from a Pixhawk via MAVSDK."""
    def __init__(self):
        self.drone = mavsdk.System()
        self._state = {
            "latitude": None, "longitude": None, "altitude": None,
            "battery_percentage": None, "voltage": None,
            "heading": None, "speed": None
        }

    async def connect(self):
        """Connects to the Pixhawk."""
        await self.drone.connect(system_address="serial:///dev/ttyACM0:57600")

    async def run(self):
        """
        Launches all telemetry subscription tasks.
        """
        tasks = [
            asyncio.create_task(self._subscribe_position()),
            asyncio.create_task(self._subscribe_battery()),
            asyncio.create_task(self._subscribe_heading()),
            asyncio.create_task(self._subscribe_velocity()),
        ]
        await asyncio.gather(*tasks)

    async def get_telemetry(self):
        """Returns the latest telemetry state."""
        return self._state.copy()

    async def _subscribe_position(self):
        async for position in self.drone.telemetry.position():
            self._state["latitude"] = position.latitude_deg
            self._state["longitude"] = position.longitude_deg
            self._state["altitude"] = position.relative_altitude_m

    async def _subscribe_battery(self):
        async for battery in self.drone.telemetry.battery():
            self._state["battery_percentage"] = battery.remaining_percent * 100
            self._state["voltage"] = battery.voltage_v

    async def _subscribe_heading(self):
        async for heading in self.drone.telemetry.heading():
            self._state["heading"] = heading.heading_deg

    async def _subscribe_velocity(self):
        async for velocity in self.drone.telemetry.velocity_ned():
            self._state["speed"] = math.sqrt(velocity.north_m_s**2 + velocity.east_m_s**2)

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

async def telemetry_producer(websocket, source):
    """
    Coroutine that fetches telemetry and sends it over WebSocket.
    """
    while True:
        try:
            telemetry_data = await source.get_telemetry()
            payload = {
                "type": "telemetry",
                "payload": telemetry_data
            }
            await websocket.send(json.dumps(payload))
            await asyncio.sleep(0.5)  # Send telemetry twice a second
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
        print("INFO: Using SimulatedTelemetrySource.")
        telemetry_source = SimulatedTelemetrySource()
    else:
        print("INFO: Using MavsdkTelemetrySource.")
        telemetry_source = MavsdkTelemetrySource()
        await telemetry_source.connect()
        asyncio.create_task(telemetry_source.run())

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
