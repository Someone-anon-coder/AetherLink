import subprocess
import time
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput

# Configuration
COMMS_HUB_IP = "100.73.152.43"  # <-- USER: Set this to the Tailscale IP of the Comms Hub machine
VIDEO_STREAM_PORT = 5600

def main():
    """
    Main function to capture video from Picamera2 and stream it over UDP using GStreamer.
    """
    print("Initializing Picamera2...")
    picam2 = Picamera2()
    video_config = picam2.create_video_configuration(main={"size": (1280, 720), "format": "RGB888"})
    picam2.configure(video_config)

    encoder = H264Encoder(bitrate=1000000)

    print("Setting up GStreamer pipeline...")
    gst_command = [
        'gst-launch-1.0',
        '-v',
        'fdsrc',  # Use a file descriptor source
        '!', 'h264parse',
        '!', 'rtph264pay', 'config-interval=1', 'pt=96',
        '!', 'udpsink', f'host={COMMS_HUB_IP}', f'port={VIDEO_STREAM_PORT}'
    ]

    try:
        # Start the GStreamer pipeline
        gst_process = subprocess.Popen(gst_command, stdin=subprocess.PIPE)
        print(f"--> GStreamer process started. Streaming to {COMMS_HUB_IP}:{VIDEO_STREAM_PORT}")

        # Pipe the encoded video output to the GStreamer process
        output = FileOutput(gst_process.stdin)
        picam2.start_recording(encoder, output)

        print("--> Picamera2 recording started. Streaming video...")

        # Keep the script running
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        picam2.stop_recording()
        if 'gst_process' in locals() and gst_process.poll() is None:
            gst_process.terminate()
            gst_process.wait()
        print("Stream stopped.")


if __name__ == '__main__':
    main()
