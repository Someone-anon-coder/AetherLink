# ground_station/comms_hub/main.py

import asyncio
import websockets
import json
import sys
from google.protobuf.message import DecodeError
import socket

# --- Add Path Modifier ---
sys.path.insert(0, sys.path[0]+'/../..')

from shared.protos.mission_data_pb2 import Telemetry, SystemCommand

# --- CONFIGURATION ---
VIDEO_PORT = 9999
TELEMETRY_UDP_PORT = 9998
COMMAND_PORT = 9997
CLIENT_VIDEO_PORT = 5600  # Port for local UDP relay
WEBSOCKET_LISTEN_IP = "0.0.0.0"
WEBSOCKET_LISTEN_PORT = 8765

# --- STATE ---
CONNECTED_CLIENTS = set()

# --- WebSocket Logic ---
async def handler(websocket, path=None):
    global CONNECTED_CLIENTS
    print(f"Client connected: {websocket.remote_address}")
    CONNECTED_CLIENTS.add(websocket)

    command_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                if data.get("type") == "system_command":
                    command_name_str = data.get("command_name")
                    payload_dict = data.get("payload")
                    command_type = SystemCommand.CommandType.Value(command_name_str)
                    cmd_proto = SystemCommand()
                    cmd_proto.command_type = command_type
                    if payload_dict:
                        if command_type == SystemCommand.CommandType.GOTO_LOCATION:
                            cmd_proto.location.latitude = payload_dict['latitude']
                            cmd_proto.location.longitude = payload_dict['longitude']
                            cmd_proto.location.altitude_m = payload_dict['altitude_m']
                        elif command_type == SystemCommand.CommandType.SET_SERVO:
                            cmd_proto.servo.servo_id = payload_dict['servo_id']
                            cmd_proto.servo.pwm_value = payload_dict['pwm_value']
                    ONBOARD_IP = "100.122.254.14"
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
    if CONNECTED_CLIENTS:
        await asyncio.gather(*[client.send(message) for client in CONNECTED_CLIENTS])

# --- UDP Logic ---
class UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, data_type):
        self.data_type = data_type
        self.transport = None
        super().__init__()

    def connection_made(self, transport):
        self.transport = transport
        sockname = self.transport.get_extra_info('sockname')
        print(f"UDP listener for {self.data_type} started on {sockname[0]}:{sockname[1]}")

    def datagram_received(self, data, addr):
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
                json_message = json.dumps(parsed_message)
                asyncio.create_task(broadcast(json_message))
            except DecodeError:
                print(f"Could not decode Telemetry from {addr}")
        elif self.data_type == 'video':
            # Simply forward the raw UDP packet to the local client port
            self.transport.sendto(data, ('127.0.0.1', CLIENT_VIDEO_PORT))


async def main():
    loop = asyncio.get_running_loop()

    # Start UDP listener for Telemetry
    telemetry_transport, _ = await loop.create_datagram_endpoint(
        lambda: UdpProtocol(data_type='telemetry'),
        local_addr=("0.0.0.0", TELEMETRY_UDP_PORT)
    )

    # Start UDP listener for Video
    video_transport, _ = await loop.create_datagram_endpoint(
        lambda: UdpProtocol(data_type='video'),
        local_addr=("0.0.0.0", VIDEO_PORT)
    )

    websocket_server = await websockets.serve(handler, WEBSOCKET_LISTEN_IP, WEBSOCKET_LISTEN_PORT)
    print(f"WebSocket server started on {WEBSOCKET_LISTEN_IP}:{WEBSOCKET_LISTEN_PORT}")

    try:
        await asyncio.Future()
    finally:
        websocket_server.close()
        telemetry_transport.close()
        video_transport.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n--> Server shutting down.")
