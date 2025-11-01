import sys
sys.path.append('../')

import socket
import time
import cv2
from picamera2 import Picamera2
from shared.protos import mission_data_pb2

# Configuration
COMMS_HUB_IP = "192.168.1.2"  # Placeholder - Replace with actual IP
VIDEO_PORT = 9999

def main():
    """
    Main function to capture video from Picamera2 and stream it over UDP.
    """
    # Create a UDP socket
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        print(f"Socket created. Target: {COMMS_HUB_IP}:{VIDEO_PORT}")

        print("Initializing Picamera2...")
        picam2 = Picamera2()
        config = picam2.create_video_configuration(main={"size": (640, 480)})
        picam2.configure(config)
        picam2.start()
        print("--> Picamera2 started. Streaming video...")

        frame_id = 0
        while True:
            try:
                # Capture a frame as a NumPy array
                frame = picam2.capture_array()

                # Encode the image to JPEG format
                _, buffer = cv2.imencode('.jpg', frame)

                # Create a Protobuf message
                proto_frame = mission_data_pb2.VideoStreamFrame()
                proto_frame.frame_id = frame_id
                proto_frame.timestamp = int(time.time() * 1000)
                proto_frame.frame_data = buffer.tobytes()

                # Serialize the Protobuf message
                serialized_frame = proto_frame.SerializeToString()

                # Send the data over the UDP socket
                sock.sendto(serialized_frame, (COMMS_HUB_IP, VIDEO_PORT))

                # Debugging: Print frame ID every 30 frames
                if frame_id % 30 == 0:
                    print(f"Sent frame {frame_id} ({len(serialized_frame)} bytes)")

                frame_id += 1

            except Exception as e:
                print(f"An error occurred: {e}")
                break

if __name__ == '__main__':
    main()
