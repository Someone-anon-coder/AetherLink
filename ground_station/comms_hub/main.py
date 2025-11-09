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
TELEMETRY_UDP_PORT = 9998
VIDEO_UDP_PORT = 9999  # Listen for video from the drone
COMMAND_PORT = 9997    # Port to send commands to the drone

AI_ENGINE_VIDEO_TARGET = ('127.0.0.1', 5601)
DASHBOARD_VIDEO_TARGET = ('127.0.0.1', 5602)

WEBSOCKET_LISTEN_IP = "0.0.0.0"
WEBSOCKET_LISTEN_PORT = 8765

# --- STATE ---
CONNECTED_CLIENTS = set()
ONBOARD_SYSTEM_IP = None  # Will be updated dynamically from telemetry packets

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
                    if ONBOARD_SYSTEM_IP is None:
                        print("WARN: No onboard system IP available. Cannot relay command.")
                        continue

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

                    serialized_cmd = cmd_proto.SerializeToString()
                    command_sock.sendto(serialized_cmd, (ONBOARD_SYSTEM_IP, COMMAND_PORT))
                    print(f"RELAY: Relaying command {command_name_str} to {ONBOARD_SYSTEM_IP}:{COMMAND_PORT}")

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                print(f"Error processing command from client: {e}")
    except websockets.ConnectionClosed:
        print(f"Client {websocket.remote_address} disconnected.")
    finally:
        CONNECTED_CLIENTS.remove(websocket)
        command_sock.close()
        print(f"Client {websocket.remote_address} cleaned up.")

async def broadcast(message):
    if CONNECTED_CLIENTS:
        # Use asyncio.gather to send messages concurrently without waiting for each one
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
        print(f"UDP listener for '{self.data_type}' started on {sockname[0]}:{sockname[1]}")

    def datagram_received(self, data, addr):
        global ONBOARD_SYSTEM_IP
        if self.data_type == 'telemetry':
            # Update the onboard system's IP address with every telemetry packet
            if ONBOARD_SYSTEM_IP != addr[0]:
                ONBOARD_SYSTEM_IP = addr[0]
                print(f"INFO: Onboard system IP updated to {ONBOARD_SYSTEM_IP}")

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
                # Broadcast the telemetry data to all WebSocket clients
                asyncio.create_task(broadcast(json_message))
            except DecodeError:
                print(f"Could not decode Telemetry from {addr}")

        elif self.data_type == 'video':
            # Forward the raw UDP video packet to both the AI Engine and Dashboard
            self.transport.sendto(data, AI_ENGINE_VIDEO_TARGET)
            self.transport.sendto(data, DASHBOARD_VIDEO_TARGET)
            # This print statement is very noisy, so it's commented out.
            # print(f"RELAY: Forwarded {len(data)} video bytes from {addr} -> AI @ {AI_ENGINE_VIDEO_TARGET} & Dash @ {DASHBOARD_VIDEO_TARGET}")

async def main():
    loop = asyncio.get_running_loop()

    # Start UDP listener for Telemetry from the drone
    await loop.create_datagram_endpoint(
        lambda: UdpProtocol(data_type='telemetry'),
        local_addr=("0.0.0.0", TELEMETRY_UDP_PORT)
    )

    # Start UDP listener for Video from the drone
    await loop.create_datagram_endpoint(
        lambda: UdpProtocol(data_type='video'),
        local_addr=("0.0.0.0", VIDEO_UDP_PORT)
    )

    # Start the WebSocket server for ground station clients
    async with websockets.serve(handler, WEBSOCKET_LISTEN_IP, WEBSOCKET_LISTEN_PORT):
        print(f"WebSocket server started on {WEBSOCKET_LISTEN_IP}:{WEBSOCKET_LISTEN_PORT}")
        await asyncio.Future()  # Run forever

if __name__ == "__main__":
    try:
        print("--- Comms Hub initializing ---")
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n--> Server shutting down.")
