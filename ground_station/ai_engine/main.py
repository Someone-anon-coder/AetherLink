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
import sys
from google.protobuf import json_format

# --- Add Path Modifier ---
sys.path.insert(0, sys.path[0]+'/../..')
from shared.protos.mission_data_pb2 import SystemCommand

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
    def __init__(self, command_queue):
        self.command_queue = command_queue
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

    async def _send_command(self, command_type, payload_data=None):
        """Creates a command dictionary and puts it on the queue."""
        command_message = {
            "type": "system_command",
            "command_name": SystemCommand.CommandType.Name(command_type),
            "payload": payload_data # payload_data will be a simple dict
        }
        await self.command_queue.put(json.dumps(command_message))
        print(f"CMD: Queued command: {command_message['command_name']}")

    async def _handle_transiting_to_drop_zone_state(self, packet):
        # For this example, we'll command it to the location where the disaster was detected.
        # A real implementation might have a predefined drop zone.
        if self.resume_point:
            disaster_coords = (self.resume_point.get('latitude'), self.resume_point.get('longitude'))
            # Assuming disaster_coords is a tuple (lat, lon)
            location_payload = {"latitude": disaster_coords[0], "longitude": disaster_coords[1], "altitude_m": self.survey_altitude_m}
            await self._send_command(SystemCommand.CommandType.GOTO_LOCATION, payload_data=location_payload)

        self.current_state = MissionState.PERFORMING_PAYLOAD_DROP
        print("LOG: State changed to PERFORMING_PAYLOAD_DROP.")


    async def _handle_performing_payload_drop_state(self, packet):
        # Create a Location payload for descending
        descend_payload = {
            "latitude": self.latest_telemetry.get('latitude'),
            "longitude": self.latest_telemetry.get('longitude'),
            "altitude_m": 10.0
        }
        await self._send_command(SystemCommand.CommandType.GOTO_LOCATION, payload_data=descend_payload)

        await asyncio.sleep(5) # Simulate time to descend and search

        # Create a Servo payload for actuating the gripper
        servo_payload = {"servo_id": 0, "pwm_value": 1800}
        await self._send_command(SystemCommand.CommandType.SET_SERVO, payload_data=servo_payload)
        self.payload_dropped = True
        print("LOG: Payload has been dropped.")

        await asyncio.sleep(2) # Allow time for drop

        # Create a Location payload for ascending back to survey altitude
        ascend_payload = {
            "latitude": self.latest_telemetry.get('latitude'),
            "longitude": self.latest_telemetry.get('longitude'),
            "altitude_m": self.survey_altitude_m
        }
        await self._send_command(SystemCommand.CommandType.GOTO_LOCATION, payload_data=ascend_payload)

        if self.resume_point:
            self.current_state = MissionState.RESUMING_SURVEY
            print("LOG: State changed to RESUMING_SURVEY.")
        else:
            self.current_state = MissionState.RETURNING_TO_LAUNCH
            print("LOG: State changed to RETURNING_TO_LAUNCH.")

    async def _handle_resuming_survey_state(self, packet):
        # Command the drone to fly back to the resume point
        resume_payload = {
            "latitude": self.resume_point.get('latitude'),
            "longitude": self.resume_point.get('longitude'),
            "altitude_m": self.resume_point.get('relative_altitude_m')
        }
        await self._send_command(SystemCommand.CommandType.GOTO_LOCATION, payload_data=resume_payload)

        # In a real system, you'd need a way to tell the flight controller to resume its mission plan.
        # This is a placeholder for that logic.
        print("LOG: Commanded drone to resume point. Resuming survey.")
        self.current_state = MissionState.EXECUTING_SURVEY
        self.resume_point = None # Clear the resume point
        print("LOG: State changed to EXECUTING_SURVEY.")


    async def _handle_returning_to_launch_state(self, packet):
        if self.current_state == MissionState.RETURNING_TO_LAUNCH:
            await self._send_command(SystemCommand.CommandType.RETURN_TO_LAUNCH)
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


async def command_sender(websocket, queue):
    """
    Waits for a command from the queue and sends it.
    """
    while True:
        command_json = await queue.get()
        try:
            await websocket.send(command_json)
            print(f"SENT: {command_json}")
        except websockets.ConnectionClosed:
            print("Cannot send command, connection is closed.")
            break
        finally:
            queue.task_done()


async def run():
    """
    Connects to the Comms Hub WebSocket server, creates a command queue,
    and runs the command sender and message processor concurrently.
    """
    uri = f"ws://{COMMS_HUB_IP}:{COMMS_HUB_PORT}"
    command_queue = asyncio.Queue()
    mission_logic = MissionLogic(command_queue)
    start_time = time.time()

    async for websocket in websockets.connect(uri):
        try:
            print(f"--- Connected to Comms Hub at {uri} ---")

            # Start the command sender task
            sender_task = asyncio.create_task(command_sender(websocket, command_queue))

            # Run the message processing loop
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
                    if time.time() - start_time > 20 and not mission_logic.payload_dropped:
                        if 'detections' not in data:
                            data['detections'] = []
                        data['detections'].append({'class_name': 'disaster_zone', 'box': []})

                await mission_logic.process_packet(data)

            # Once the message loop is broken, cancel the sender task
            sender_task.cancel()
            await asyncio.gather(sender_task, return_exceptions=True)

        except websockets.ConnectionClosed:
            print("--- Connection to Comms Hub lost. Attempting to reconnect... ---")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"An error occurred: {e}")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(run())
