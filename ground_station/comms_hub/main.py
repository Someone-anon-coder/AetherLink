# ground_station/comms_hub/main.py

import asyncio
import websockets
import json
import base64
import sys
from google.protobuf.message import DecodeError

# --- Add Path Modifier ---
# This allows us to import from the 'shared' directory
sys.path.insert(0, sys.path[0]+'/../..')

from shared.protos.mission_data_pb2 import Telemetry, VideoStreamFrame

# --- CONFIGURATION ---
VIDEO_UDP_PORT = 9999
TELEMETRY_UDP_PORT = 9998
WEBSOCKET_LISTEN_IP = "0.0.0.0"
WEBSOCKET_LISTEN_PORT = 8765

# --- STATE ---
# A set to hold all currently connected WebSocket clients
CONNECTED_CLIENTS = set()

# --- WebSocket Logic ---
async def handler(websocket, path=None):
    """
    Handles a single WebSocket client connection. Registers the client
    and keeps the connection alive until the client disconnects.
    """
    global CONNECTED_CLIENTS
    print(f"Client connected: {websocket.remote_address}")
    CONNECTED_CLIENTS.add(websocket)
    try:
        # Keep the connection open and listen for any potential incoming messages
        await websocket.wait_closed()
    finally:
        print(f"Client disconnected: {websocket.remote_address}")
        CONNECTED_CLIENTS.remove(websocket)

async def broadcast(message):
    """
    Broadcasts a message to all connected clients.
    """
    # Use asyncio.gather to send messages to all clients concurrently
    if CONNECTED_CLIENTS:
        await asyncio.gather(
            *[client.send(message) for client in CONNECTED_CLIENTS]
        )

# --- UDP Logic ---
class UdpProtocol(asyncio.DatagramProtocol):
    """
    The asyncio protocol for handling incoming UDP packets.
    """
    def __init__(self, data_type, queue):
        self.data_type = data_type
        self.queue = queue
        self.transport = None
        super().__init__()

    def connection_made(self, transport):
        self.transport = transport
        sockname = self.transport.get_extra_info('sockname')
        print(f"UDP listener for {self.data_type} started on {sockname[0]}:{sockname[1]}")

    def datagram_received(self, data, addr):
        """
        This method is called automatically by asyncio whenever a UDP packet is received.
        """
        parsed_message = None
        
        if self.data_type == 'video':
            try:
                frame = VideoStreamFrame()
                frame.ParseFromString(data)
                frame_data_b64 = base64.b64encode(frame.frame_data).decode('utf-8')
                parsed_message = {
                    "type": "video_frame",
                    "timestamp": frame.timestamp,
                    "frame_id": frame.frame_id,
                    "frame_data_b64": frame_data_b64
                }
            except DecodeError:
                print(f"Could not decode VideoStreamFrame from {addr}")

        elif self.data_type == 'telemetry':
            try:
                telemetry = Telemetry()
                telemetry.ParseFromString(data)
                parsed_message = {
                    "type": "telemetry",
                    "timestamp": telemetry.timestamp,
                    "latitude": telemetry.latitude,
                    "longitude": telemetry.longitude,
                    "relative_altitude_m": telemetry.relative_altitude_m,
                    "battery_voltage": telemetry.battery_voltage
                }
            except DecodeError:
                print(f"Could not decode Telemetry from {addr}")
        
        if parsed_message:
            json_message = json.dumps(parsed_message)
            self.queue.put_nowait(json_message)


async def broadcaster(queue):
    """
    Pulls messages from the queue and broadcasts them to all clients.
    """
    while True:
        message = await queue.get()
        await broadcast(message)


async def main():
    """
    Main entry point. Starts the UDP listener and WebSocket server.
    """
    loop = asyncio.get_running_loop()
    broadcast_queue = asyncio.Queue()

    # Start the broadcaster task
    asyncio.create_task(broadcaster(broadcast_queue))

    # Start the UDP listener for Video
    video_transport, _ = await loop.create_datagram_endpoint(
        lambda: UdpProtocol(data_type='video', queue=broadcast_queue),
        local_addr=("0.0.0.0", VIDEO_UDP_PORT)
    )

    # Start the UDP listener for Telemetry
    telemetry_transport, _ = await loop.create_datagram_endpoint(
        lambda: UdpProtocol(data_type='telemetry', queue=broadcast_queue),
        local_addr=("0.0.0.0", TELEMETRY_UDP_PORT)
    )

    # Start the WebSocket server
    websocket_server = await websockets.serve(handler, WEBSOCKET_LISTEN_IP, WEBSOCKET_LISTEN_PORT)
    print(f"WebSocket server started on {WEBSOCKET_LISTEN_IP}:{WEBSOCKET_LISTEN_PORT}")

    try:
        # Keep the server running forever
        await asyncio.Future()
    finally:
        websocket_server.close()
        video_transport.close()
        telemetry_transport.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n--> Server shutting down.")
