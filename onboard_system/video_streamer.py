import time
import sys
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput

# --- CONFIGURATION ---
# This should be the Tailscale IP of the Comms Hub Laptop
COMMS_HUB_IP = "100.69.186.67"  # <-- USER: SET THIS
VIDEO_PORT = 9999

def main():
    print("INFO: Initializing Picamera2...")
    picam2 = Picamera2()
    # A 720p resolution is a good balance of quality and bandwidth
    video_config = picam2.create_video_configuration(
        main={"size": (1280, 720), "format": "YUV420"}
    )
    picam2.configure(video_config)

    # Use a hardware-accelerated H.264 encoder
    encoder = H264Encoder(bitrate=1500000) # 1.5 Mbps bitrate

    # The output MUST be an RTP stream for GStreamer to understand it
    output_url = f"rtp://{COMMS_HUB_IP}:{VIDEO_PORT}"
    output = FfmpegOutput(f"-f rtp {output_url}")

    print(f"INFO: Starting H.264 stream to {output_url}")
    picam2.start_recording(encoder, output)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n--> Shutting down video stream.")
    finally:
        picam2.stop_recording()
        print("--> Stream stopped.")

if __name__ == '__main__':
    main()
