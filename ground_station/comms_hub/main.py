# ground_station/comms_hub/main.py

import asyncio
import websockets
import json
import sys

sys.path.insert(0, sys.path[0]+'/../..')
from shared.protos.mission_data_pb2 import Telemetry

# --- CONFIGURATION (FOR 3-LAPTOP SETUP) ---
AI_ENGINE_IP = "100.69.186.67"  # <-- USER: Set Tailscale IP of AI Engine Laptop
DASHBOARD_IP = "100.69.186.67"  # <-- USER: Set Tailscale IP of Dashboard Laptop
# --- For single-laptop testing, set both to "127.0.0.1" ---

VIDEO_LISTEN_PORT = 9999
TELEMETRY_LISTEN_PORT = 9998
COMMAND_LISTEN_PORT = 9997

AI_ENGINE_VIDEO_PORT = 5601
DASHBOARD_VIDEO_PORT = 5602

WEBSOCKET_LISTEN_IP = "0.0.0.0"
WEBSOCKET_LISTEN_PORT = 8765

CONNECTED_CLIENTS = set()
ONBOARD_SYSTEM_IP = None

async def handler(websocket):
    global CONNECTED_CLIENTS
    print(f"INFO: WebSocket client connected: {websocket.remote_address}")
    CONNECTED_CLIENTS.add(websocket)
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                if data.get("type") == "system_command":
                    if not ONBOARD_SYSTEM_IP:
                        print("WARN: Cannot relay command, onboard IP not yet learned.")
                        continue
                    
                    loop = asyncio.get_running_loop()
                    transport, _ = await loop.create_datagram_endpoint(
                        lambda: asyncio.DatagramProtocol(), remote_addr=(ONBOARD_SYSTEM_IP, COMMAND_LISTEN_PORT)
                    )
                    transport.sendto(message.encode())
                    transport.close()
                    print(f"RELAY: Relayed command to {ONBOARD_SYSTEM_IP}:{COMMAND_LISTEN_PORT}")
                else: # If it's not a command, it's a broadcast from the AI Engine
                    await broadcast(data, exclude_sender=websocket)
            except (json.JSONDecodeError, KeyError) as e:
                print(f"ERROR: Could not process WebSocket message: {e}")
    except websockets.ConnectionClosed:
        print(f"INFO: WebSocket client disconnected: {websocket.remote_address}")
    finally:
        CONNECTED_CLIENTS.remove(websocket)

async def broadcast(message_dict, exclude_sender=None):
    if CONNECTED_CLIENTS:
        json_message = json.dumps(message_dict)
        await asyncio.gather(*[client.send(json_message) for client in CONNECTED_CLIENTS if client != exclude_sender])

class UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, data_type):
        self.data_type = data_type
        self.transport = None
        self.packet_count = 0
    def connection_made(self, transport):
        self.transport = transport
        sockname = transport.get_extra_info('sockname')
        print(f"INFO: UDP listener for {self.data_type} started on {sockname[0]}:{sockname[1]}")
    def datagram_received(self, data, addr):
        global ONBOARD_SYSTEM_IP
        if self.data_type == 'telemetry':
            if ONBOARD_SYSTEM_IP is None:
                ONBOARD_SYSTEM_IP = addr[0]
                print(f"INFO: Onboard system IP learned as {ONBOARD_SYSTEM_IP}")
            try:
                telemetry = Telemetry.FromString(data)
                parsed_message = {"type": "telemetry", "latitude": telemetry.latitude, "longitude": telemetry.longitude, "relative_altitude_m": telemetry.relative_altitude_m, "battery_voltage": telemetry.battery_voltage}
                asyncio.create_task(broadcast(parsed_message))
            except Exception: pass
        elif self.data_type == 'video':
            self.transport.sendto(data, (AI_ENGINE_IP, AI_ENGINE_VIDEO_PORT))
            self.transport.sendto(data, (DASHBOARD_IP, DASHBOARD_VIDEO_PORT))

async def main():
    loop = asyncio.get_running_loop()
    await loop.create_datagram_endpoint(lambda: UdpProtocol(data_type='telemetry'), local_addr=("0.0.0.0", TELEMETRY_LISTEN_PORT))
    await loop.create_datagram_endpoint(lambda: UdpProtocol(data_type='video'), local_addr=("0.0.0.0", VIDEO_LISTEN_PORT))
    async with websockets.serve(handler, WEBSOCKET_LISTEN_IP, WEBSOCKET_LISTEN_PORT):
        print(f"INFO: WebSocket server started on {WEBSOCKET_LISTEN_IP}:{WEBSOCKET_LISTEN_PORT}")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
