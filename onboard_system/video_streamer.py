import sys
sys.path.append('../')

import socket
import time
import cv2
import picamera
import picamera.array
from shared.protos import mission_data_pb2

# Configuration
COMMS_HUB_IP = "192.168.1.2"  # Placeholder - Replace with actual IP
VIDEO_PORT = 9999

def main():
    """
    Main function to capture video from PiCamera and stream it over UDP.
    """
    # Create a UDP socket
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        print(f"Socket created. Target: {COMMS_HUB_IP}:{VIDEO_PORT}")

        # Initialize the PiCamera
        with picamera.PiCamera() as camera:
            camera.resolution = (640, 480)
            camera.framerate = 30
            time.sleep(2)  # Allow the camera to warm up

            print("PiCamera initialized.")

            # Create a reusable buffer for frames
            with picamera.array.PiRGBArray(camera, size=(640, 480)) as stream:
                frame_id = 0
                # Use capture_continuous for efficient frame capture
                for frame in camera.capture_continuous(stream, format='bgr', use_video_port=True):
                    try:
                        # Get the raw image data from the frame
                        image = frame.array

                        # Encode the image to JPEG format
                        _, buffer = cv2.imencode('.jpg', image)

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
                    finally:
                        # Crucially, clear the stream for the next capture
                        stream.truncate(0)

if __name__ == '__main__':
    main()
