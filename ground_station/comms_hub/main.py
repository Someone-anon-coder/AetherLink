import asyncio
import base64
import json
import socket
import sys
import websockets
from google.protobuf.message import DecodeError

# --- Add Path Modifier ---
sys.path.append('../../')

from shared.protos.mission_data_pb2 import Telemetry, VideoStreamFrame

# --- CONFIGURATION ---
UDP_LISTEN_IP = "0.0.0.0"
UDP_LISTEN_PORT = 9999
WS_LISTEN_IP = "0.0.0.0"
WS_LISTEN_PORT = 8765

# --- GLOBAL STATE ---
CONNECTED_CLIENTS = set()

# --- WEBSOCKET HANDLERS ---
async def register(websocket):
    """Adds a new client to the connected clients set."""
    CONNECTED_CLIENTS.add(websocket)
    print(f"Client connected: {websocket.remote_address}")

async def unregister(websocket):
    """Removes a client from the connected clients set."""
    CONNECTED_CLIENTS.remove(websocket)
    print(f"Client disconnected: {websocket.remote_address}")

async def handler(websocket, path):
    """Handles a single WebSocket client connection."""
    await register(websocket)
    try:
        # Keep the connection alive
        await websocket.wait_closed()
    finally:
        await unregister(websocket)

# --- UDP PROTOCOL ---
class UdpProtocol(asyncio.DatagramProtocol):
    """
    An asyncio DatagramProtocol for receiving and broadcasting UDP packets.
    """
    def datagram_received(self, data, addr):
        """
        Handles incoming UDP datagrams.
        """
        try:
            # First, try to parse as a VideoStreamFrame
            frame = VideoStreamFrame()
            frame.ParseFromString(data)

            # Encode frame data as Base64 for JSON safety
            encoded_frame = base64.b64encode(frame.frame_data).decode('utf-8')

            message = {
                'type': 'video',
                'data': {
                    'frame_id': frame.frame_id,
                    'timestamp': frame.timestamp,
                    'frame_data': encoded_frame
                }
            }
            print(f"Received Video Frame #{frame.frame_id} from {addr}")

        except DecodeError:
            # If that fails, it might be a Telemetry message
            try:
                telemetry = Telemetry()
                telemetry.ParseFromString(data)

                message = {
                    'type': 'telemetry',
                    'data': {
                        'latitude': telemetry.latitude,
                        'longitude': telemetry.longitude,
                        'altitude': telemetry.altitude,
                        'speed': telemetry.speed
                    }
                }
                print(f"Received Telemetry from {addr}: Lat={telemetry.latitude}, Lon={telemetry.longitude}")

            except DecodeError:
                # If both fail, it's an unknown packet
                print(f"Received an unknown packet from {addr}")
                return

        # Broadcast the message to all connected clients
        json_message = json.dumps(message)
        asyncio.create_task(self.broadcast(json_message))

    async def broadcast(self, message):
        """
        Broadcasts a message to all connected WebSocket clients.
        """
        # Make a copy of the set to avoid issues with clients disconnecting
        # while we are iterating.
        for client in CONNECTED_CLIENTS.copy():
            try:
                await client.send(message)
            except websockets.exceptions.ConnectionClosed:
                # The client has disconnected. The unregister function will handle
                # removing it from the set.
                pass

# --- MAIN COROUTINE ---
async def main():
    """
    Main function to run the Comms Hub server.
    """
    loop = asyncio.get_running_loop()

    # Start the UDP server
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: UdpProtocol(),
        local_addr=(UDP_LISTEN_IP, UDP_LISTEN_PORT),
        family=socket.AF_INET)

    print(f"Comms Hub UDP listener running on {UDP_LISTEN_IP}:{UDP_LISTEN_PORT}")

    # Start the WebSocket server
    server = await websockets.serve(handler, WS_LISTEN_IP, WS_LISTEN_PORT)
    print(f"Comms Hub WebSocket server running on {WS_LISTEN_IP}:{WS_LISTEN_PORT}")

    # Keep the servers running indefinitely
    await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Servers shutting down.")
