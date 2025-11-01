import asyncio
import websockets
import json
from ultralytics import YOLO
import cv2
import numpy as np
import base64
from enum import Enum
from haversine import haversine, Unit
import time

# --- CONFIGURATION ---
# The IP address should be the Tailscale IP of the machine running the Comms Hub.
COMMS_HUB_IP = "100.73.152.43"  # <-- USER: Set this to the Tailscale IP of the Comms Hub machine
COMMS_HUB_PORT = 8765

# Load the trained YOLOv8 model once.
model = YOLO('best.pt')


class MissionState(Enum):
    STANDBY = 1
    EXECUTING_SURVEY = 2
    TRANSITING_TO_DROP_ZONE = 3
    PERFORMING_PAYLOAD_DROP = 4
    RESUMING_SURVEY = 5
    RETURNING_TO_LAUNCH = 6


class MissionLogic:
    def __init__(self):
        self.current_state = MissionState.STANDBY
        self.detected_objects = []
        self.latest_telemetry = {}
        self.survey_altitude_m = 15.0
        self.duplicate_distance_m = 10.0
        self.resume_point = None
        self.payload_dropped = False

    async def process_packet(self, packet):
        if packet['type'] == 'telemetry':
            self.latest_telemetry = packet

        if self.current_state == MissionState.STANDBY:
            await self._handle_standby_state(packet)
        elif self.current_state == MissionState.EXECUTING_SURVEY:
            await self._handle_executing_survey_state(packet)
        elif self.current_state == MissionState.TRANSITING_TO_DROP_ZONE:
            await self._handle_transiting_to_drop_zone_state(packet)
        elif self.current_state == MissionState.PERFORMING_PAYLOAD_DROP:
            await self._handle_performing_payload_drop_state(packet)
        elif self.current_state == MissionState.RESUMING_SURVEY:
            await self._handle_resuming_survey_state(packet)
        elif self.current_state == MissionState.RETURNING_TO_LAUNCH:
            await self._handle_returning_to_launch_state(packet)

    async def _handle_standby_state(self, packet):
        if packet['type'] == 'telemetry':
            if packet.get('relative_altitude_m', 0) > 5.0:
                self.current_state = MissionState.EXECUTING_SURVEY
                print("LOG: Drone is airborne. Switching to EXECUTING_SURVEY state.")

    async def _handle_executing_survey_state(self, packet):
        if packet['type'] == 'video_frame' and 'detections' in packet:
            for detection in packet['detections']:
                world_coords = self._calculate_world_coordinates(detection['box'], self.latest_telemetry)
                if not self._is_duplicate(world_coords):
                    class_name = detection['class_name']
                    lat, lon = world_coords
                    self.detected_objects.append({'class_name': class_name, 'coords': world_coords})
                    print(f"** UNIQUE OBJECT LOGGED: {class_name} at ({lat}, {lon}) **")

            # --- Simulated Disaster Detection Placeholder ---
            if 'disaster_zone' in [d['class_name'] for d in packet.get('detections', [])] and not self.payload_dropped:
                print("\n!!! DISASTER ZONE DETECTED !!!")
                self.resume_point = self.latest_telemetry  # Save current telemetry as resume point
                # For now, we don't save the next waypoint, just the location.
                print(f"LOG: Saving resume point at {self.resume_point['latitude']}, {self.resume_point['longitude']}")
                self.current_state = MissionState.TRANSITING_TO_DROP_ZONE
                print("LOG: State changed to TRANSITING_TO_DROP_ZONE.")

        if self._is_survey_complete() and self.payload_dropped:
            self.current_state = MissionState.RETURNING_TO_LAUNCH

    async def _handle_transiting_to_drop_zone_state(self, packet):
        print("CMD: ==> COMMAND DRONE: Override mission and fly to DISASTER_ZONE_COORDS.")
        self.current_state = MissionState.PERFORMING_PAYLOAD_DROP
        print("LOG: State changed to PERFORMING_PAYLOAD_DROP.")

    async def _handle_performing_payload_drop_state(self, packet):
        print("CMD: ==> COMMAND DRONE: Descend to 10m.")
        await asyncio.sleep(2)
        print("LOG: Searching for safe drop area...")
        await asyncio.sleep(2)
        print("LOG: Centering over safe drop area...")
        await asyncio.sleep(2)
        print("CMD: ==> COMMAND DRONE: Actuate gripper servos to OPEN.")
        self.payload_dropped = True
        print("LOG: Payload has been dropped.")
        await asyncio.sleep(1)
        print("CMD: ==> COMMAND DRONE: Ascend to 15m.")

        if self.resume_point:
            self.current_state = MissionState.RESUMING_SURVEY
            print("LOG: State changed to RESUMING_SURVEY.")
        else:
            self.current_state = MissionState.RETURNING_TO_LAUNCH
            print("LOG: State changed to RETURNING_TO_LAUNCH.")

    async def _handle_resuming_survey_state(self, packet):
        print("CMD: ==> COMMAND DRONE: Fly to resume point.")
        print("CMD: ==> COMMAND DRONE: Continue QGC mission.")
        self.current_state = MissionState.EXECUTING_SURVEY
        self.resume_point = None
        print("LOG: State changed to EXECUTING_SURVEY.")

    async def _handle_returning_to_launch_state(self, packet):
        if self.current_state == MissionState.RETURNING_TO_LAUNCH:
            print("CMD: ==> COMMAND DRONE: Return to Launch (RTL).")
            self.current_state = None  # Or some final state

    def _calculate_world_coordinates(self, detection_pixel_coords, drone_telemetry):
        return (drone_telemetry.get('latitude'), drone_telemetry.get('longitude'))

    def _is_duplicate(self, new_coords):
        for obj in self.detected_objects:
            distance = haversine(obj['coords'], new_coords, unit=Unit.METERS)
            if distance < self.duplicate_distance_m:
                return True
        return False

    def _is_survey_complete(self):
        # Placeholder for real survey completion logic
        return len(self.detected_objects) > 2 # Example condition


async def run():
    """
    Connects to the Comms Hub WebSocket server and processes incoming data.
    """
    uri = f"ws://{COMMS_HUB_IP}:{COMMS_HUB_PORT}"
    mission_logic = MissionLogic()
    start_time = time.time()
    async for websocket in websockets.connect(uri):
        try:
            print(f"--- Connected to Comms Hub at {uri} ---")
            async for message in websocket:
                data = json.loads(message)

                if data.get('type') == 'video_frame':
                    frame_bytes = base64.b64decode(data['frame_data_b64'])
                    image_np = np.frombuffer(frame_bytes, np.uint8)
                    image = cv2.imdecode(image_np, cv2.IMREAD_COLOR)
                    results = model(image, verbose=False)
                    result = results[0]

                    detections = []
                    if len(result.boxes) > 0:
                        for box in result.boxes:
                            class_id = int(box.cls[0])
                            class_name = model.names[class_id]
                            detections.append({'class_name': class_name, 'box': box.xyxy[0].tolist()})
                    data['detections'] = detections

                    # --- Placeholder for disaster detection ---
                    if time.time() - start_time > 20 and not mission_logic.payload_dropped:  # Trigger after 20 seconds
                        # Inject a fake detection into the packet
                        if 'detections' not in data:
                            data['detections'] = []
                        data['detections'].append({'class_name': 'disaster_zone', 'box': []})


                await mission_logic.process_packet(data)

        except websockets.ConnectionClosed:
            print("--- Connection to Comms Hub lost. Attempting to reconnect... ---")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(run())
