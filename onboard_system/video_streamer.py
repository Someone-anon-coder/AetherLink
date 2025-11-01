import sys
sys.path.append('../')

import socket
import time
import cv2
import struct
from picamera2 import Picamera2
from shared.protos import mission_data_pb2

# Configuration
COMMS_HUB_IP = "192.168.1.2"  # Placeholder - Replace with actual IP
VIDEO_PORT = 9999

def main():
    """
    Main function to capture video from Picamera2 and stream it over TCP.
    """
    while True:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                print(f"Attempting to connect to {COMMS_HUB_IP}:{VIDEO_PORT}...")
                sock.connect((COMMS_HUB_IP, VIDEO_PORT))
                print("--> Connected to Comms Hub.")

                print("Initializing Picamera2...")
                picam2 = Picamera2()
                config = picam2.create_video_configuration(main={"size": (640, 480)})
                picam2.configure(config)
                picam2.start()
                print("--> Picamera2 started. Streaming video...")

                frame_id = 0
                while True:
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
                    message_len = len(serialized_frame)
                    header = struct.pack('!I', message_len)

                    try:
                        # Send the header and then the message
                        sock.sendall(header)
                        sock.sendall(serialized_frame)

                        if frame_id % 30 == 0:
                            print(f"Sent frame {frame_id} ({len(serialized_frame)} bytes)")

                        frame_id += 1

                    except (BrokenPipeError, ConnectionResetError):
                        print("Connection lost. Reconnecting...")
                        break  # Break inner loop to trigger reconnection
                    except Exception as e:
                        print(f"An error occurred during sending: {e}")
                        time.sleep(1)


        except ConnectionRefusedError:
            print("Connection refused. Retrying in 5 seconds...")
            time.sleep(5)
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            print("Restarting script in 10 seconds...")
            time.sleep(10)

if __name__ == '__main__':
    main()
