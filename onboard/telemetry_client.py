import asyncio
import websockets
import json
import time
from mavsdk import System

# --- CONFIGURATION ---
GCS_IP = "100.69.186.67"  # <-- USER: Set this to the Tailscale IP of the GCS laptop
GCS_WS_PORT = 8765
MAVSDK_CONNECTION = "serial:///dev/serial0:57600"

async def get_telemetry_stream(stream):
    """Helper to get a single item from an async stream."""
    async for item in stream:
        return item

async def stream_telemetry(drone, websocket):
    """Streams all telemetry concurrently to the WebSocket."""
    position_task = asyncio.ensure_future(get_telemetry_stream(drone.telemetry.position()))
    heading_task = asyncio.ensure_future(get_telemetry_stream(drone.telemetry.heading()))
    velocity_task = asyncio.ensure_future(get_telemetry_stream(drone.telemetry.velocity_ned()))
    battery_task = asyncio.ensure_future(get_telemetry_stream(drone.telemetry.battery()))

    while True:
        try:
            # Wait for all telemetry sources to provide a new value
            await asyncio.gather(position_task, heading_task, velocity_task, battery_task)

            position = position_task.result()
            heading = heading_task.result()
            velocity = velocity_task.result()
            battery = battery_task.result()

            if all([position, heading, velocity, battery]):
                telemetry_data = {
                    'latitude': position.latitude_deg,
                    'longitude': position.longitude_deg,
                    'relative_altitude_m': position.relative_altitude_m,
                    'speed_m_s': (velocity.north_m_s**2 + velocity.east_m_s**2)**0.5,
                    'heading_deg': heading.heading_deg,
                    'battery_percent': battery.remaining_percent * 100,
                    'battery_voltage': battery.voltage_v,
                    'timestamp': time.time()
                }

                message = json.dumps({'type': 'telemetry', 'payload': telemetry_data})
                await websocket.send(message)

            # Re-schedule tasks to listen for the next update
            position_task = asyncio.ensure_future(get_telemetry_stream(drone.telemetry.position()))
            heading_task = asyncio.ensure_future(get_telemetry_stream(drone.telemetry.heading()))
            velocity_task = asyncio.ensure_future(get_telemetry_stream(drone.telemetry.velocity_ned()))
            battery_task = asyncio.ensure_future(get_telemetry_stream(drone.telemetry.battery()))

            await asyncio.sleep(0.1)  # 10 Hz telemetry rate

        except websockets.ConnectionClosed:
            print("WARN: Telemetry stream connection closed.")
            break  # Exit loop to allow outer loop to reconnect
        except Exception as e:
            print(f"ERROR: Error in telemetry stream: {e}")
            await asyncio.sleep(1) # Avoid spamming errors

async def run():
    """Main coroutine to connect to the GCS and the Pixhawk, then stream telemetry."""
    uri = f"ws://{GCS_IP}:{GCS_WS_PORT}"
    drone = System()

    print("INFO: Initializing MAVSDK...")
    await drone.connect(system_address=MAVSDK_CONNECTION)

    print("INFO: Waiting for drone to connect...")
    async for state in drone.core.connection_state():
        if state.is_connected:
            print("INFO: Drone connected!")
            break

    while True:
        try:
            async with websockets.connect(uri) as websocket:
                print(f"INFO: Connected to GCS WebSocket at {uri}")
                await stream_telemetry(drone, websocket)
        except (websockets.exceptions.ConnectionClosedError, ConnectionRefusedError, OSError) as e:
            print(f"WARN: Connection to GCS failed ({e}). Retrying in 5 seconds...")
        except Exception as e:
            print(f"ERROR: An unexpected error occurred in the main run loop: {e}")

        await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("INFO: Shutting down telemetry client.")
