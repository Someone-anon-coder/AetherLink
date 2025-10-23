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
UDP_LISTEN_IP = "0.0.0.0"
UDP_LISTEN_PORT = 9999
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
    def connection_made(self, transport):
        print(f"UDP listener started on {UDP_LISTEN_IP}:{UDP_LISTEN_PORT}")
        self.transport = transport

    def datagram_received(self, data, addr):
        """
        This method is called automatically by asyncio whenever a UDP packet is received.
        """
        # --- This is the critical link ---
        # 1. Parse the data
        # 2. Convert it to a JSON string
        # 3. Create a task to broadcast it to all WebSocket clients
        
        parsed_message = None
        message_type = "unknown"

        try:
            # First, try to parse as a VideoStreamFrame
            frame = VideoStreamFrame()
            frame.ParseFromString(data)
            # Base64 encode the binary frame data to make it JSON-safe
            frame_data_b64 = base64.b64encode(frame.frame_data).decode('utf-8')
            parsed_message = {
                "type": "video_frame",
                "timestamp": frame.timestamp,
                "frame_id": frame.frame_id,
                "frame_data_b64": frame_data_b64
            }
            message_type = "Video Frame"
        except DecodeError:
            # If that fails, it might be a Telemetry message
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
                message_type = "Telemetry"
            except DecodeError:
                print(f"Received an unknown/corrupt packet from {addr}")

        if parsed_message:
            # If parsing was successful, create a task to broadcast the message
            # This ensures the UDP listener is not blocked by slow WebSocket clients
            json_message = json.dumps(parsed_message)
            asyncio.create_task(broadcast(json_message))
            # Optional: Add a log for debugging, but can be noisy
            # print(f"Received and broadcasting {message_type}")


async def main():
    """
    Main entry point. Starts the UDP listener and WebSocket server.
    """
    loop = asyncio.get_running_loop()

    # Start the UDP listener
    udp_transport, udp_protocol = await loop.create_datagram_endpoint(
        lambda: UdpProtocol(),
        local_addr=(UDP_LISTEN_IP, UDP_LISTEN_PORT)
    )

    # Start the WebSocket server
    websocket_server = await websockets.serve(handler, WEBSOCKET_LISTEN_IP, WEBSOCKET_LISTEN_PORT)
    print(f"WebSocket server started on {WEBSOCKET_LISTEN_IP}:{WEBSOCKET_LISTEN_PORT}")

    try:
        # Keep the server running forever
        await asyncio.Future()
    finally:
        websocket_server.close()
        udp_transport.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n--> Server shutting down.")
