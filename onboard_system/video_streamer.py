import time
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import UdpOutput

# --- CONFIGURATION ---
# <-- USER: Set this to the Tailscale IP of the Comms Hub machine
COMMS_HUB_IP = "127.0.0.1"
VIDEO_PORT = 9999

def main():
    """
    Captures video from Picamera2, encodes it as H.264, and streams it
    directly over UDP.
    """
    print("Initializing Picamera2...")
    picam2 = Picamera2()
    video_config = picam2.create_video_configuration(main={"size": (1280, 720)})
    picam2.configure(video_config)

    encoder = H264Encoder(bitrate=1000000)
    output = UdpOutput((COMMS_HUB_IP, VIDEO_PORT))

    print(f"--> Starting H.264 stream to {COMMS_HUB_IP}:{VIDEO_PORT}")
    picam2.start_recording(encoder, output)

    try:
        # Keep the script running indefinitely
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n--> Shutting down video stream.")
    finally:
        picam2.stop_recording()
        print("--> Stream stopped.")

if __name__ == '__main__':
    main()
