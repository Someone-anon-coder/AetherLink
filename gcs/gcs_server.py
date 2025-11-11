import asyncio
import websockets
import json

async def handler(websocket):
    print(f"INFO: Onboard system connected from {websocket.remote_address}")
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                if 'type' in data:
                    if data['type'] == 'video':
                        payload_size = len(data.get('payload', ''))
                        print(f"DEBUG: Received VIDEO packet, payload size: {payload_size} bytes")
                    elif data['type'] == 'telemetry':
                        print(f"DEBUG: Received TELEMETRY packet: {data.get('payload')}")
                    else:
                        print(f"WARN: Received unknown data type: {data['type']}")
                else:
                    print(f"WARN: Received message without 'type' field: {data}")
            except json.JSONDecodeError:
                print(f"WARN: Received non-JSON message: {message}")

    except websockets.ConnectionClosed as e:
        print(f"INFO: Connection with {websocket.remote_address} closed: {e}")
    finally:
        print(f"INFO: Onboard system {websocket.remote_address} disconnected.")

async def main():
    HOST = "0.0.0.0"
    PORT = 8765
    async with websockets.serve(handler, HOST, PORT):
        print(f"INFO: GCS WebSocket server started on ws://{HOST}:{PORT}")
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
