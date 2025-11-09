import asyncio
import websockets
import time

# --- CONFIGURATION ---
GCS_IP = "100.x.x.x" # <-- USER: Set this to the Tailscale IP of the GCS laptop
GCS_PORT = 8765

async def main():
    uri = f"ws://{GCS_IP}:{GCS_PORT}"
    while True:
        try:
            async with websockets.connect(uri) as websocket:
                print(f"INFO: Connected to GCS at {uri}")
                counter = 0
                while True:
                    counter += 1
                    message = f"Heartbeat {counter}"
                    await websocket.send(message)
                    print(f"DEBUG: Sent '{message}'")
                    await asyncio.sleep(3)
        except (websockets.ConnectionClosed, ConnectionRefusedError) as e:
            print(f"WARN: Connection lost ({e}). Retrying in 5 seconds...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
