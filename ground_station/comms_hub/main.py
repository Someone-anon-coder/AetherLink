# ground_station/comms_hub/main.py

import asyncio
import websockets
import json
import base64
import sys
import struct
from google.protobuf.message import DecodeError

from google.protobuf import json_format
import socket

# --- Add Path Modifier ---
# This allows us to import from the 'shared' directory
sys.path.insert(0, sys.path[0]+'/../..')

from shared.protos.mission_data_pb2 import Telemetry, VideoStreamFrame, SystemCommand

# --- CONFIGURATION ---
VIDEO_UDP_PORT = 9999
TELEMETRY_UDP_PORT = 9998
COMMAND_UDP_PORT = 9997
COMMAND_PORT = 9997
ONBOARD_SYSTEM_IP = "127.0.0.1" # For local testing
WEBSOCKET_LISTEN_IP = "0.0.0.0"
WEBSOCKET_LISTEN_PORT = 8765

# --- STATE ---
# A set to hold all currently connected WebSocket clients
CONNECTED_CLIENTS = set()
# A UDP socket for sending commands, created once at startup
COMMAND_SOCKET = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


# --- WebSocket Logic ---
async def handler(websocket, path=None):
    """
    Handles a WebSocket client. Registers for broadcasting and listens for commands.
    """
    global CONNECTED_CLIENTS
    print(f"Client connected: {websocket.remote_address}")
    CONNECTED_CLIENTS.add(websocket)

    # Create a dedicated UDP socket for sending commands for this client
    command_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        # Listen for incoming messages (commands) from this client
        async for message in websocket:
            try:
                data = json.loads(message)
                if data.get("type") == "system_command":
                    command_name_str = data.get("command_name")
                    payload_dict = data.get("payload")

                    # Convert string name back to enum value
                    command_type = SystemCommand.CommandType.Value(command_name_str)

                    cmd_proto = SystemCommand()
                    cmd_proto.command_type = command_type

                    # Populate payload if it exists
                    if payload_dict:
                        if command_type == SystemCommand.CommandType.GOTO_LOCATION:
                            cmd_proto.location.latitude = payload_dict['latitude']
                            cmd_proto.location.longitude = payload_dict['longitude']
                            cmd_proto.location.altitude_m = payload_dict['altitude_m']
                        elif command_type == SystemCommand.CommandType.SET_SERVO:
                            cmd_proto.servo.servo_id = payload_dict['servo_id']
                            cmd_proto.servo.pwm_value = payload_dict['pwm_value']

                    # Serialize and send to the onboard system's IP (from telemetry)
                    # NOTE: For now, we hardcode the target IP. This will be dynamic later.
                    ONBOARD_IP = "100.122.254.14" # The IP of your Raspberry Pi
                    serialized_cmd = cmd_proto.SerializeToString()
                    command_sock.sendto(serialized_cmd, (ONBOARD_IP, COMMAND_PORT))
                    print(f"RELAY: Relaying command {command_name_str} to {ONBOARD_IP}:{COMMAND_PORT}")

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                print(f"Error processing command from client: {e}")

    except websockets.ConnectionClosed:
        print(f"Client {websocket.remote_address} disconnected.")
    finally:
        CONNECTED_CLIENTS.remove(websocket)
        command_sock.close()

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
    def __init__(self, data_type):
        self.data_type = data_type
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
        
        if self.data_type == 'telemetry':
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
            asyncio.create_task(broadcast(json_message))

# --- TCP Video Logic ---
async def handle_video_client(reader, writer):
    """
    Handles a single TCP client connection for video data.
    """
    addr = writer.get_extra_info('peername')
    print(f"Video client connected: {addr}")
    try:
        while True:
            # 1. Read the 4-byte header to get the message length
            header = await reader.readexactly(4)
            message_len = struct.unpack('!I', header)[0]

            # 2. Read the full protobuf message
            data = await reader.readexactly(message_len)

            # 3. Parse, convert to JSON, and broadcast
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
                json_message = json.dumps(parsed_message)
                asyncio.create_task(broadcast(json_message))
            except DecodeError:
                print(f"Could not decode VideoStreamFrame from {addr}")

    except asyncio.IncompleteReadError:
        print(f"Video client {addr} disconnected (incomplete read).")
    except ConnectionResetError:
        print(f"Video client {addr} connection reset.")
    finally:
        print(f"Closing connection for video client {addr}")
        writer.close()
        await writer.wait_closed()


async def main():
    """
    Main entry point. Starts the UDP listener and WebSocket server.
    """
    loop = asyncio.get_running_loop()

    # Start the TCP server for Video
    video_server = await asyncio.start_server(
        handle_video_client, '0.0.0.0', VIDEO_UDP_PORT
    )
    video_addr = video_server.sockets[0].getsockname()
    print(f"TCP server for video started on {video_addr[0]}:{video_addr[1]}")

    # Start the UDP listener for Telemetry
    telemetry_transport, _ = await loop.create_datagram_endpoint(
        lambda: UdpProtocol(data_type='telemetry'),
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
        video_server.close()
        telemetry_transport.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n--> Server shutting down.")
