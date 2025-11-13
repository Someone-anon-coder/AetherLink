import asyncio
from enum import Enum, auto
import time
from haversine import haversine, Unit

class MissionState(Enum):
    STANDBY = auto()
    TAKEOFF = auto()
    PERFORMING_SURVEY = auto()
    TARGET_FOUND = auto()
    PERFORMING_PAYLOAD_DROP = auto()
    RETURNING_TO_LAUNCH = auto()
    LANDING = auto()

class MissionLogic:
    def __init__(self, command_queue, broadcast_queue):
        self.state = MissionState.STANDBY
        self.command_queue = command_queue
        self.broadcast_queue = broadcast_queue

        self.survey_altitude_m = 8.0
        self.payload_drop_altitude_m = 5.0

        self.home_location = None
        self.target_location = None

        print("INFO: MissionLogic initialized in STANDBY state.")

    async def process_telemetry(self, telemetry):
        # This is where the state machine logic for telemetry is handled
        if self.state == MissionState.STANDBY and telemetry['altitude'] > 1.0:
            self.state = MissionState.TAKEOFF
            await self._broadcast_state()

        elif self.state == MissionState.TAKEOFF and telemetry['altitude'] >= self.survey_altitude_m:
            self.state = MissionState.PERFORMING_SURVEY
            await self._broadcast_state()

    async def process_detections(self, detections):
        if self.state == MissionState.PERFORMING_SURVEY:
            # For now, any detection triggers the payload drop
            self.target_location = detections[0] # Simplified for now
            self.state = MissionState.TARGET_FOUND
            await self._broadcast_state()
            await self._handle_target_found_state()

    async def _handle_target_found_state(self):
        self.state = MissionState.PERFORMING_PAYLOAD_DROP
        await self._broadcast_state()
        await self._handle_performing_payload_drop_state()

    async def _handle_performing_payload_drop_state(self):
        print("MISSION_LOGIC: Descending to payload drop altitude.")
        await self._send_command("GOTO_LOCATION", {
            "lat": self.target_location['box'][0], # Simplified for now
            "lon": self.target_location['box'][1], # Simplified for now
            "alt": self.payload_drop_altitude_m
        })

        await asyncio.sleep(10) # Wait for descent

        print("MISSION_LOGIC: Releasing payload.")
        await self._send_command("SET_SERVO", {"servo_id": 1, "pwm_value": 1800})

        await asyncio.sleep(2)

        print("MISSION_LOGIC: Ascending back to survey altitude.")
        await self._send_command("GOTO_LOCATION", {
            "lat": self.target_location['box'][0], # Simplified for now
            "lon": self.target_location['box'][1], # Simplified for now
            "alt": self.survey_altitude_m
        })

        self.state = MissionState.RETURNING_TO_LAUNCH
        await self._broadcast_state()
        await self._send_command("RTL", {})

    async def _send_command(self, command_name, payload):
        command = {
            "type": "system_command",
            "command_name": command_name,
            "payload": payload
        }
        await self.command_queue.put(command)

    async def _broadcast_state(self):
        state_update = {
            "type": "mission_state_update",
            "state": self.state.name
        }
        await self.broadcast_queue.put(state_update)
