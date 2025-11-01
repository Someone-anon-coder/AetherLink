import asyncio
import websockets
import json
from ultralytics import YOLO
import cv2
import numpy as np
import base64
from enum import Enum
from haversine import haversine, Unit

# --- CONFIGURATION ---
# The IP address should be the Tailscale IP of the machine running the Comms Hub.
COMMS_HUB_IP = "100.73.152.43" # <-- USER: Set this to the Tailscale IP of the Comms Hub machine
COMMS_HUB_PORT = 8765

# Load the trained YOLOv8 model once.
model = YOLO('best.pt')

class MissionState(Enum):
    STANDBY = 1
    EXECUTING_SURVEY = 2
    PERFORMING_PAYLOAD_DROP = 3 # Simplified for now
    RETURNING_TO_LAUNCH = 4

class MissionLogic:
    def __init__(self):
        self.current_state = MissionState.STANDBY
        self.detected_objects = []
        self.latest_telemetry = None # Initialize as None until first telemetry packet arrives
        self.survey_altitude_m = 15.0
        self.duplicate_distance_m = 10.0

    async def process_packet(self, packet):
        # Update telemetry regardless of type to ensure it's always current
        if packet['type'] == 'telemetry':
            self.latest_telemetry = packet['data']
        
        if self.current_state == MissionState.STANDBY:
            # We only need to check telemetry packets for state transitions
            if packet['type'] == 'telemetry':
                await self._handle_standby_state(packet['data'])
        elif self.current_state == MissionState.EXECUTING_SURVEY:
            # The survey state needs to process video frames
            await self._handle_survey_state(packet)

    async def _handle_standby_state(self, telemetry_data):
        if telemetry_data.get('relative_altitude_m', 0) > 5.0:
            self.current_state = MissionState.EXECUTING_SURVEY
            print("LOG: Drone is airborne. Switching to EXECUTING_SURVEY state.")

    async def _handle_survey_state(self, packet):
        # Only process detections if we have both a video frame and recent telemetry data
        if packet['type'] == 'video_frame' and 'detections' in packet and self.latest_telemetry:
            for detection in packet['detections']:
                world_coords = self._calculate_world_coordinates(detection['box'], self.latest_telemetry)
                # Ensure coordinates are valid before processing
                if world_coords[0] is not None and world_coords[1] is not None:
                    if not self._is_duplicate(world_coords):
                        class_name = detection['class_name']
                        lat, lon = world_coords
                        self.detected_objects.append({'class_name': class_name, 'coords': world_coords})
                        print(f"** UNIQUE OBJECT LOGGED: {class_name} at ({lat}, {lon}) **")

    def _calculate_world_coordinates(self, detection_pixel_coords, drone_telemetry):
        # Placeholder: In a real implementation, this would involve complex geometric calculations.
        # For now, we'll just use the drone's current GPS coordinates as the object's coordinates.
        if drone_telemetry:
            lat = drone_telemetry.get('latitude_deg', None)
            lon = drone_telemetry.get('longitude_deg', None)
            if lat is not None and lon is not None:
                return (lat, lon)
        return (None, None) # Return None if telemetry is missing or incomplete

    def _is_duplicate(self, new_coords):
        for obj in self.detected_objects:
            distance = haversine(obj['coords'], new_coords, unit=Unit.METERS)
            if distance < self.duplicate_distance_m:
                return True
        return False

async def run():
    """
    Connects to the Comms Hub WebSocket server and processes incoming data.
    """
    uri = f"ws://{COMMS_HUB_IP}:{COMMS_HUB_PORT}"
    mission_logic = MissionLogic()
    async for websocket in websockets.connect(uri):
        try:
            print(f"--- Connected to Comms Hub at {uri} ---")
            async for message in websocket:
                print(f"DEBUG: Raw message received, size: {len(message)}") # <-- ADD THIS LINE
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

                await mission_logic.process_packet(data)

        except websockets.ConnectionClosed:
            print("--- Connection to Comms Hub lost. Attempting to reconnect... ---")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(run())
