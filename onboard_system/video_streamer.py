import time
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput

# --- CONFIGURATION ---
# <-- USER: Set this to the Tailscale IP of the Comms Hub machine
COMMS_HUB_IP = "127.0.0.1"
VIDEO_PORT = 9999

def main():
    """
    Captures video from Picamera2, encodes it as H.264, and streams it
    directly over UDP using FFmpeg for RTP containerization.
    """
    print("Initializing Picamera2...")
    picam2 = Picamera2()
    # Using a YUV420 format is often more compatible with h264 encoders
    video_config = picam2.create_video_configuration(
        main={"size": (1280, 720), "format": "YUV420"}
    )
    picam2.configure(video_config)

    encoder = H264Encoder(bitrate=1000000)
    # The output needs to be wrapped in an RTP container for GStreamer to understand it.
    # FFmpeg is used here to handle the containerization.
    output = FfmpegOutput(f"-f rtp udp://{COMMS_HUB_IP}:{VIDEO_PORT}")

    print(f"--> Starting H.264 stream to rtp://{COMMS_HUB_IP}:{VIDEO_PORT}")
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
