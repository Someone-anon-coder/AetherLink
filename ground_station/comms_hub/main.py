import socket
import sys
from google.protobuf.message import DecodeError

# --- Add Path Modifier ---
sys.path.append('../../')

from shared.protos.mission_data_pb2 import Telemetry, VideoStreamFrame

# --- CONFIGURATION ---
LISTEN_IP = "0.0.0.0" # Listen on all available network interfaces
LISTEN_PORT = 9999
BUFFER_SIZE = 65536 # Large enough buffer for video frames

def main():
    """
    Main function to run the Comms Hub server.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((LISTEN_IP, LISTEN_PORT))

    print(f"Comms Hub listening on {LISTEN_IP}:{LISTEN_PORT}")

    while True:
        data, addr = sock.recvfrom(BUFFER_SIZE)

        try:
            # First, try to parse as a VideoStreamFrame
            frame = VideoStreamFrame()
            frame.ParseFromString(data)
            print(f"Received Video Frame #{frame.frame_id} from {addr}")
        except DecodeError:
            # If that fails, it might be a Telemetry message
            try:
                telemetry = Telemetry()
                telemetry.ParseFromString(data)
                print(f"Received Telemetry from {addr}: Lat={telemetry.latitude}, Lon={telemetry.longitude}")
            except DecodeError:
                # If both fail, it's an unknown packet
                print(f"Received an unknown packet from {addr}")

if __name__ == "__main__":
    main()
