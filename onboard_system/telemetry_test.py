import asyncio
import sys
from mavsdk import System

class Colors:
    """ANSI color codes for terminal output."""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

# --- CONFIGURATION ---
# To connect to a real Pixhawk on a Raspberry Pi via GPIO:
# CONNECTION_STRING = "serial:///dev/serial0:57600"

# To connect to a PX4 SITL instance running on the same or another machine:
# Replace
CONNECTION_STRING = "udp://:14540@100.99.103.27"


# --- TELEMETRY STATE ---
telemetry_state = {
    "connection": f"{Colors.FAIL}DISCONNECTED{Colors.ENDC}",
    "gps_fix": "NO_FIX",
    "num_satellites": 0,
    "latitude": "N/A",
    "longitude": "N/A",
    "altitude": "N/A",
    "battery_percent": 0.0,
    "status": "UNKNOWN"
}


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
            telemetry_state["connection"] = f"{Colors.OKGREEN}CONNECTED{Colors.ENDC}"
            print("--> Drone discovered!")
            break

    # --- Telemetry Update Functions ---
    async def update_position(drone):
        """Updates position data in the telemetry dictionary."""
        async for position in drone.telemetry.position():
            telemetry_state["latitude"] = f"{position.latitude_deg:.6f}"
            telemetry_state["longitude"] = f"{position.longitude_deg:.6f}"
            telemetry_state["altitude"] = f"{position.relative_altitude_m:.2f}m"

    async def update_battery(drone):
        """Updates battery data in the telemetry dictionary."""
        async for battery in drone.telemetry.battery():
            telemetry_state["battery_percent"] = battery.remaining_percent * 100

    async def update_gps_info(drone):
        """Updates GPS info in the telemetry dictionary."""
        async for gps_info in drone.telemetry.gps_info():
            telemetry_state["gps_fix"] = str(gps_info.fix_type)
            telemetry_state["num_satellites"] = gps_info.num_satellites

    async def update_status(drone):
        """Updates the drone's in-air status in the telemetry dictionary."""
        async for in_air in drone.telemetry.in_air():
            telemetry_state["status"] = "IN AIR" if in_air else "ON GROUND"

    async def print_telemetry_display():
        """Continuously prints the formatted telemetry data to the console."""
        # Hide cursor
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()

        try:
            while True:
                # Move cursor to top-left and clear screen
                sys.stdout.write("\033[H\033[2J")

                display = (
                    f"{Colors.BOLD}--- MAVSDK TELEMETRY ---{Colors.ENDC}\n"
                    f"[{Colors.HEADER} CONNECTION {Colors.ENDC}]: {telemetry_state['connection']}\n"
                    f"[{Colors.OKCYAN} GPS        {Colors.ENDC}]: {telemetry_state['gps_fix']} ({telemetry_state['num_satellites']} Satellites)\n"
                    f"[{Colors.OKBLUE} POSITION   {Colors.ENDC}]: Lat: {telemetry_state['latitude']}, Lon: {telemetry_state['longitude']}, Alt: {telemetry_state['altitude']}\n"
                    f"[{Colors.OKGREEN} BATTERY    {Colors.ENDC}]: {telemetry_state['battery_percent']:.2f}%\n"
                    f"[{Colors.WARNING} STATUS     {Colors.ENDC}]: {telemetry_state['status']}\n"
                )
                sys.stdout.write(display)
                sys.stdout.flush()

                await asyncio.sleep(0.1)
        finally:
            # Show cursor on exit
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()

    # --- Task Creation ---
    asyncio.create_task(update_position(drone))
    asyncio.create_task(update_battery(drone))
    asyncio.create_task(update_gps_info(drone))
    asyncio.create_task(update_status(drone))

    # Start the display task and wait for it to complete
    await print_telemetry_display()


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(run())
    except KeyboardInterrupt:
        # Graceful exit on Ctrl+C
        print(f"\n{Colors.WARNING}--> Script interrupted by user.{Colors.ENDC}")
    finally:
        print(f"{Colors.BOLD}--> Script finished.{Colors.ENDC}")
        loop.close()

