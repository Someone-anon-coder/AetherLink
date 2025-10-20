
import dronekit
import time
import sys

# Define the connection string for Raspberry Pi 3 via GPIO
connection_string = '/dev/serial0'
baud_rate = 57600

print("Starting telemetry test script...")

vehicle = None  # Initialize vehicle to None

try:
    # Connect to the vehicle
    print(f"--> Connecting to vehicle on: {connection_string}")
    vehicle = dronekit.connect(connection_string, wait_ready=True, baud=baud_rate, timeout=60)
    print("--> Vehicle Connected!")

    # Main loop to read and print telemetry data
    while True:
        print("----------------------------------------")
        print(f" GPS Fix Type: {vehicle.gps_0.fix_type}")
        print(f" Latitude: {vehicle.location.global_relative_frame.lat}")
        print(f" Longitude: {vehicle.location.global_relative_frame.lon}")
        print(f" Relative Altitude: {vehicle.location.global_relative_frame.alt} m")
        print(f" Battery Voltage: {vehicle.battery.voltage} V")
        print("----------------------------------------")
        time.sleep(2)

except KeyboardInterrupt:
    print("\n--> Script interrupted by user.")

except Exception as e:
    print(f"--> An error occurred: {e}")

finally:
    if vehicle:
        print("--> Closing vehicle connection.")
        vehicle.close()
