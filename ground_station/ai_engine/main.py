import asyncio
import websockets
import json

# --- CONFIGURATION ---
# The IP address should be the Tailscale IP of the machine running the Comms Hub.
COMMS_HUB_IP = "100.x.x.x"
COMMS_HUB_PORT = 8765

async def run():
    """
    Connects to the Comms Hub WebSocket server and processes incoming data.
    """
    uri = f"ws://{COMMS_HUB_IP}:{COMMS_HUB_PORT}"
    async for websocket in websockets.connect(uri):
        try:
            print(f"--- Connected to Comms Hub at {uri} ---")
            async for message in websocket:
                data = json.loads(message)
                if 'type' in data:
                    if data['type'] == 'telemetry':
                        print(f"Received TELEMETRY: Lat={data.get('latitude', 'N/A')}, Alt={data.get('relative_altitude_m', 'N/A')}")
                    elif data['type'] == 'video_frame':
                        frame_data = data.get('frame_data_b64', '')
                        print(f"Received VIDEO FRAME: ID={data.get('frame_id', 'N/A')}, Size={len(frame_data)} bytes")
        except websockets.ConnectionClosed:
            print("--- Connection to Comms Hub lost. Attempting to reconnect... ---")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(run())
