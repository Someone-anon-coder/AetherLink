import asyncio
import time

class TelemetryProvider:
    async def connect(self):
        raise NotImplementedError

    async def get_telemetry(self):
        raise NotImplementedError

class SimulatedTelemetryProvider(TelemetryProvider):
    async def connect(self):
        pass

    async def get_telemetry(self):
        return {
            'latitude': 12.34,
            'longitude': 56.78,
            'altitude': 150.5,
            'speed': 25.2,
            'heading': 90,
            'timestamp': time.time()
        }

class MavsdkTelemetryProvider(TelemetryProvider):
    def __init__(self):
        self.drone = None

    async def connect(self):
        # MAVSDK connection logic will go here
        print("INFO: MAVSDK telemetry provider is not yet implemented.")
        pass

    async def get_telemetry(self):
        # MAVSDK data fetching logic will go here
        return {
            'latitude': 0.0,
            'longitude': 0.0,
            'altitude': 0.0,
            'speed': 0.0,
            'heading': 0.0,
            'timestamp': time.time()
        }
