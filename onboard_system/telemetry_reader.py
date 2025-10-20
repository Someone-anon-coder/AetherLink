import time
from dronekit import connect, VehicleMode

# Set the connection string for your vehicle
connection_string = '/dev/ttyAMA0'
baud_rate = 57600

# Connect to the Vehicle
print(f"Connecting to vehicle on: {connection_string}")
try:
    vehicle = connect(connection_string, baud=baud_rate, wait_ready=True)

    # Get some vehicle attributes (state)
    print("Autopilot Firmware version: %s" % vehicle.version)
    print("Vehicle mode: %s" % vehicle.mode.name)

    # Loop for 30 seconds
    end_time = time.time() + 30
    while time.time() < end_time:
        print(f"GPS: {vehicle.location.global_relative_frame}")
        print(f"Attitude: {vehicle.attitude}")
        print(f"Battery: {vehicle.battery}")
        time.sleep(2)

    print("Closing vehicle connection")
    vehicle.close()

except Exception as e:
    print(f"Error connecting to vehicle: {e}")

print("Script finished.")
