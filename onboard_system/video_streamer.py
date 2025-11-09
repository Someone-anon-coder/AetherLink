import subprocess
import time
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput

# --- CONFIGURATION ---
COMMS_HUB_IP = "100.0.0.1"  # <-- USER: Set this to the Tailscale IP of the Comms Hub machine
VIDEO_STREAM_PORT = 9999

def main():
    """
    Captures video from a Picamera2 and streams it raw over UDP using a GStreamer pipeline.
    This script is designed to run on the Raspberry Pi onboard the drone.
    """
    picam2 = None
    gst_process = None
    try:
        print("Initializing Picamera2...")
        picam2 = Picamera2()
        video_config = picam2.create_video_configuration(main={"size": (1280, 720)})
        picam2.configure(video_config)

        encoder = H264Encoder(bitrate=1000000)

        print("Defining GStreamer pipeline...")
        gst_command = [
            'gst-launch-1.0', '-v',
            'fdsrc',  # Use a file descriptor as the source
            '!', 'h264parse',
            '!', 'rtph264pay', 'config-interval=1', 'pt=96',
            '!', 'udpsink', f'host={COMMS_HUB_IP}', f'port={VIDEO_STREAM_PORT}'
        ]

        print(f"Starting GStreamer process to stream to {COMMS_HUB_IP}:{VIDEO_STREAM_PORT}")
        # Start the GStreamer pipeline, making its stdin available for piping
        gst_process = subprocess.Popen(gst_command, stdin=subprocess.PIPE)

        # Create a FileOutput object that writes to the GStreamer process's stdin
        output = FileOutput(gst_process.stdin)

        # Start the camera recording, sending the output to our GStreamer pipeline
        picam2.start_recording(encoder, output)
        print("--> Video stream is live.")

        # Keep the script running indefinitely
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n--> User interrupted. Shutting down.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        print("Cleaning up resources...")
        if picam2 and picam2.is_recording:
            picam2.stop_recording()
            print("Picamera2 recording stopped.")
        if gst_process:
            gst_process.terminate()
            gst_process.wait()
            print("GStreamer process terminated.")
        print("Shutdown complete.")


if __name__ == '__main__':
    main()
