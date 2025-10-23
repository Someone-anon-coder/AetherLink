import socket
import sys
from google.protobuf.message import DecodeError

# --- Add Path Modifier ---
# Add the parent directory to the sys.path to allow importing from the shared directory
sys.path.append('../..')

from shared.protos.mission_data_pb2 import Telemetry, VideoStreamFrame

# --- CONFIGURATION ---
LISTEN_IP = "0.0.0.0" # Listen on all available network interfaces
LISTEN_PORT = 9999
BUFFER_SIZE = 65536 # Large enough buffer for video frames

def main():
    """
    Main function to run the Comms Hub server.
    """
    # Create and bind a UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((LISTEN_IP, LISTEN_PORT))

    print(f"Comms Hub listening on {LISTEN_IP}:{LISTEN_PORT}")

    while True:
        try:
            # Receive data from the socket
            data, addr = sock.recvfrom(BUFFER_SIZE)

            # Attempt to parse as a VideoStreamFrame
            try:
                frame = VideoStreamFrame()
                frame.ParseFromString(data)
                print(f"Received Video Frame #{frame.frame_id} from {addr}")
                continue # Skip to the next iteration
            except DecodeError:
                # If parsing as VideoStreamFrame fails, try parsing as Telemetry
                pass

            # Attempt to parse as a Telemetry message
            try:
                telemetry = Telemetry()
                telemetry.ParseFromString(data)
                print(f"Received Telemetry from {addr}: Lat={telemetry.latitude}, Lon={telemetry.longitude}")
                continue # Skip to the next iteration
            except DecodeError:
                # If both parsing attempts fail, log an error
                print(f"Received an unknown packet from {addr}")

        except Exception as e:
            print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
