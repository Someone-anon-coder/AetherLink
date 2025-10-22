import asyncio
from mavsdk import System

# --- CONFIGURATION ---
# To connect to a real Pixhawk on a Raspberry Pi via GPIO:
# CONNECTION_STRING = "serial:///dev/serial0:57600"

# To connect to a PX4 SITL instance running on the same or another machine:
# Replace
CONNECTION_STRING = "udp://:14540"

async def run():
    """
    Main coroutine to run the MAVSDK telemetry script.
    """
    drone = System()
    print(f"--> Attempting to connect to MAVSDK via {CONNECTION_STRING}...")
    await drone.connect(system_address=CONNECTION_STRING)

    print("--> Waiting for drone to connect...")
    async for state in drone.core.connection_state():
        if state.is_connected:
            print("--> Drone discovered!")
            break

    print("--- STARTING TELEMETRY ---")

    async def print_position(drone):
        async for position in drone.telemetry.position():
            print(f"Position: Latitude={position.latitude_deg}, Longitude={position.longitude_deg}, Relative Altitude={position.relative_altitude_m} m")

    async def print_battery(drone):
        async for battery in drone.telemetry.battery():
            print(f"Battery: {battery.remaining_percent * 100:.2f}%")

    async def print_gps_info(drone):
        async for gps_info in drone.telemetry.gps_info():
            print(f"GPS Info: Fix Type={gps_info.fix_type}, Satellites={gps_info.num_satellites}")

    async def print_in_air(drone):
        async for in_air in drone.telemetry.in_air():
            print(f"In Air: {in_air}")

    # Create tasks for each telemetry stream
    asyncio.create_task(print_position(drone))
    asyncio.create_task(print_battery(drone))
    asyncio.create_task(print_gps_info(drone))
    asyncio.create_task(print_in_air(drone))

    # Keep the main coroutine alive
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(run())
    except KeyboardInterrupt:
        print("--> Script interrupted by user.")
    finally:
        loop.close()
