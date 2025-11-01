import asyncio
import socket
import time
import sys

sys.path.append('..')


from mavsdk import System
from shared.protos import mission_data_pb2

# --- CONFIGURATION ---
# MAVSDK Connection
MAVSDK_CONNECTION = "udp://:14540" # For SITL on the same machine

# Ground Station IP and Ports
COMMS_HUB_IP = "100.73.152.43" # To be filled by user
TELEMETRY_PORT = 9998

class TelemetryState:
    """Holds the latest telemetry data in a thread-safe manner."""
    def __init__(self):
        self.latitude = 0.0
        self.longitude = 0.0
        self.relative_altitude_m = 0.0
        self.battery_voltage = 0.0
        self.lock = asyncio.Lock()

    async def get_latest(self):
        async with self.lock:
            return {
                "latitude": self.latitude,
                "longitude": self.longitude,
                "relative_altitude_m": self.relative_altitude_m,
                "battery_voltage": self.battery_voltage,
            }

    async def update_position(self, position):
        async with self.lock:
            self.latitude = position.latitude_deg
            self.longitude = position.longitude_deg
            self.relative_altitude_m = position.relative_altitude_m

    async def update_battery(self, battery):
        async with self.lock:
            self.battery_voltage = battery.voltage_v


async def subscribe_position(drone, state):
    """Subscribes to position updates and updates the state."""
    async for position in drone.telemetry.position():
        await state.update_position(position)


async def subscribe_battery(drone, state):
    """Subscribes to battery updates and updates the state."""
    async for battery in drone.telemetry.battery():
        await state.update_battery(battery)


async def produce_telemetry_packets(state, queue):
    """Periodically creates and queues a consolidated telemetry packet."""
    while True:
        latest_data = await state.get_latest()
        msg = mission_data_pb2.Telemetry()
        msg.timestamp = time.time()
        msg.latitude = latest_data["latitude"]
        msg.longitude = latest_data["longitude"]
        msg.relative_altitude_m = latest_data["relative_altitude_m"]
        msg.battery_voltage = latest_data["battery_voltage"]
        await queue.put(msg)
        print("LOG: Queued consolidated Telemetry packet.")
        await asyncio.sleep(1.0) # Send a full packet every 1 second


async def udp_sender(sock, queue, port, stream_name=""):
    """
    Receives messages from the queue and sends them over a UDP socket.
    """
    packets_sent = 0
    while True:
        msg = await queue.get()
        serialized_msg = msg.SerializeToString()
        sock.sendto(serialized_msg, (COMMS_HUB_IP, port))
        packets_sent += 1
        if packets_sent % 100 == 0:
            print(f"LOG: Sent {packets_sent} {stream_name} packets.")


async def run():
    """Main entry point for the onboard system."""
    # Create sockets and queues
    telemetry_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    telemetry_queue = asyncio.Queue()

    # Initialize drone and state
    drone = System()
    telemetry_state = TelemetryState()

    # Connect to the drone
    print("--> Connecting to drone...")
    await drone.connect(system_address=MAVSDK_CONNECTION)
    async for state in drone.core.connection_state():
        if state.is_connected:
            print("--> Drone discovered!")
            break

    # Get the current event loop
    loop = asyncio.get_event_loop()

    # Schedule all producers and senders as independent background tasks
    loop.create_task(subscribe_position(drone, telemetry_state))
    loop.create_task(subscribe_battery(drone, telemetry_state))
    loop.create_task(produce_telemetry_packets(telemetry_state, telemetry_queue))
    loop.create_task(udp_sender(telemetry_sock, telemetry_queue, TELEMETRY_PORT, "Telemetry"))

    print("--- All systems running. Streaming data... ---")

    # Keep the main coroutine alive forever to allow background tasks to run
    await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("--> Script interrupted by user.")
