import asyncio
import cv2
import socket
import time
import sys

sys.path.append('..')


from mavsdk import System
from shared.protos import mission_data_pb2

# --- CONFIGURATION ---
# MAVSDK Connection
MAVSDK_CONNECTION = "udp://:14540" # For SITL on the same machine

# GStreamer Pipeline for Gazebo Simulation
GAZEBO_GSTREAMER_PIPELINE = "udpsrc port=5600 ! application/x-rtp, media=video, clock-rate=90000, encoding-name=H264, payload=96 ! rtph264depay ! decodebin ! videoconvert ! appsink"

# Ground Station IP and Port (Replace with the Comms Hub's Tailscale IP)
COMMS_HUB_IP = "100.99.103.27"
COMMS_HUB_PORT = 9999


async def stream_telemetry(drone, queue):
    """Subscribes to MAVSDK telemetry and puts protobuf messages into the queue."""
    async def subscribe_and_queue(stream, msg_type):
        async for item in stream:
            msg = mission_data_pb2.Telemetry()
            msg.timestamp = time.time()
            if msg_type == 'position':
                msg.latitude = item.latitude_deg
                msg.longitude = item.longitude_deg
                msg.relative_altitude_m = item.relative_altitude_m
            elif msg_type == 'battery':
                msg.battery_voltage = item.voltage_v

            await queue.put(msg)
            print(f"LOG: Queued {msg_type.capitalize()} packet.")

    # Run subscribers concurrently
    await asyncio.gather(
        subscribe_and_queue(drone.telemetry.position(), 'position'),
        subscribe_and_queue(drone.telemetry.battery(), 'battery')
    )


def video_processing_thread(queue, loop):
    """
    Connects to the GStreamer pipeline, processes video frames, and puts them into a queue.
    This runs in a separate thread to avoid blocking asyncio.
    """
    cap = cv2.VideoCapture(GAZEBO_GSTREAMER_PIPELINE, cv2.CAP_GSTREAMER)
    if not cap.isOpened():
        print("Error: Could not open video stream.")
        return

    frame_id = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Error: Could not read frame.")
            break

        frame_resized = cv2.resize(frame, (640, 480))
        ret, buffer = cv2.imencode('.jpg', frame_resized)
        if not ret:
            print("Error: Could not encode frame.")
            continue

        video_frame_msg = mission_data_pb2.VideoStreamFrame()
        video_frame_msg.timestamp = time.time()
        video_frame_msg.frame_id = frame_id
        video_frame_msg.frame_data = buffer.tobytes()

        asyncio.run_coroutine_threadsafe(queue.put(video_frame_msg), loop)

        if frame_id % 30 == 0:
            print(f"LOG: Queued Video Frame #{frame_id}")

        frame_id += 1


async def udp_sender(sock, queue):
    """
    Receives messages from the queue and sends them over a UDP socket.
    """
    packets_sent = 0
    while True:
        msg = await queue.get()
        serialized_msg = msg.SerializeToString()
        sock.sendto(serialized_msg, (COMMS_HUB_IP, COMMS_HUB_PORT))
        packets_sent += 1
        if packets_sent % 100 == 0:
            print(f"LOG: Sent {packets_sent} packets.")


async def run():
    """Main entry point for the onboard system."""
    # ... (socket, queue, drone connection logic remains the same) ...
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    queue = asyncio.Queue()
    drone = System()
    await drone.connect(system_address=MAVSDK_CONNECTION)

    print("--> Waiting for drone to connect...")
    async for state in drone.core.connection_state():
        if state.is_connected:
            print("--> Drone discovered!")
            break

    # Start the blocking video thread in the background
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, video_processing_thread, queue, loop)
    print("LOG: Video processing thread started in background.")

    # Now, run the async tasks concurrently
    telemetry_task = asyncio.create_task(stream_telemetry(drone, queue))
    sender_task = asyncio.create_task(udp_sender(sock, queue))

    await asyncio.gather(telemetry_task, sender_task)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("--> Script interrupted by user.")
