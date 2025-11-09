import asyncio
import websockets
import json
import sys
from google.protobuf.message import DecodeError

# --- Add Path Modifier ---
sys.path.insert(0, sys.path[0]+'/../..')

from shared.protos.mission_data_pb2 import Telemetry, SystemCommand

# --- CONFIGURATION ---
# Use this configuration for a single-laptop setup
AI_ENGINE_IP = "127.0.0.1"
DASHBOARD_IP = "127.0.0.1"
# ---
# Use this configuration for a three-laptop setup
# AI_ENGINE_IP = "TAILSCALE_IP_OF_AI_ENGINE" # <-- USER: Set this
# DASHBOARD_IP = "TAILSCALE_IP_OF_DASHBOARD" # <-- USER: Set this
# ---
VIDEO_PORT = 9999
TELEMETRY_UDP_PORT = 9998
COMMAND_PORT = 9997
AI_ENGINE_VIDEO_PORT = 5601
DASHBOARD_VIDEO_PORT = 5602
WEBSOCKET_LISTEN_IP = "0.0.0.0"
WEBSOCKET_LISTEN_PORT = 8765

# --- STATE ---
CONNECTED_CLIENTS = set()
ONBOARD_SYSTEM_IP = None # Dynamically learned

# --- WebSocket Logic ---
async def handler(websocket, path=None):
    global CONNECTED_CLIENTS
    print(f"Client connected: {websocket.remote_address}")
    CONNECTED_CLIENTS.add(websocket)

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                if data.get("type") == "system_command":
                    if not ONBOARD_SYSTEM_IP:
                        print("WARN: No onboard system IP learned yet. Cannot send command.")
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
                    
                    # This part needs to be async; we'll create a temporary socket
                    loop = asyncio.get_running_loop()
                    transport, _ = await loop.create_datagram_endpoint(
                        lambda: asyncio.DatagramProtocol(),
                        remote_addr=(ONBOARD_SYSTEM_IP, COMMAND_PORT)
                    )
                    transport.sendto(serialized_cmd)
                    transport.close()
                    
                    print(f"RELAY: Relaying command {command_name_str} to {ONBOARD_SYSTEM_IP}:{COMMAND_PORT}")

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                print(f"Error processing command from client: {e}")
    except websockets.ConnectionClosed:
        print(f"Client {websocket.remote_address} disconnected.")
    finally:
        CONNECTED_CLIENTS.remove(websocket)

async def broadcast(message):
    if CONNECTED_CLIENTS:
        await asyncio.gather(*[client.send(message) for client in CONNECTED_CLIENTS])

# --- UDP Logic ---
class UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, data_type):
        self.data_type = data_type
        self.transport = None
        self.video_packet_count = 0
        super().__init__()

    def connection_made(self, transport):
        self.transport = transport
        sockname = self.transport.get_extra_info('sockname')
        print(f"UDP listener for {self.data_type} started on {sockname[0]}:{sockname[1]}")

    def datagram_received(self, data, addr):
        global ONBOARD_SYSTEM_IP
        
        if self.data_type == 'telemetry':
            if ONBOARD_SYSTEM_IP is None:
                ONBOARD_SYSTEM_IP = addr[0]
                print(f"INFO: Onboard system IP learned as {ONBOARD_SYSTEM_IP}")
            
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
            ai_engine_target = (AI_ENGINE_IP, AI_ENGINE_VIDEO_PORT)
            dashboard_target = (DASHBOARD_IP, DASHBOARD_VIDEO_PORT)
            self.transport.sendto(data, ai_engine_target)
            self.transport.sendto(data, dashboard_target)
            
            self.video_packet_count += 1
            if self.video_packet_count % 100 == 0:
                print(f"DEBUG: Forwarded 100 video packets. Total: {self.video_packet_count}")

async def main():
    loop = asyncio.get_running_loop()

    # Start UDP listener for Telemetry
    await loop.create_datagram_endpoint(
        lambda: UdpProtocol(data_type='telemetry'),
        local_addr=("0.0.0.0", TELEMETRY_UDP_PORT)
    )

    # Start UDP listener for Video
    await loop.create_datagram_endpoint(
        lambda: UdpProtocol(data_type='video'),
        local_addr=("0.0.0.0", VIDEO_PORT)
    )

    websocket_server = await websockets.serve(handler, WEBSOCKET_LISTEN_IP, WEBSOCKET_LISTEN_PORT)
    print(f"WebSocket server started on {WEBSOCKET_LISTEN_IP}:{WEBSOCKET_LISTEN_PORT}")

    await asyncio.Future() # Run forever

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n--> Server shutting down.")
