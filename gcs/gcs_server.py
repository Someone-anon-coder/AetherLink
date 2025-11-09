import asyncio
import websockets

async def handler(websocket):
    print(f"INFO: Onboard system connected from {websocket.remote_address}")
    try:
        async for message in websocket:
            print(f"DEBUG: Received message: {message}")
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
