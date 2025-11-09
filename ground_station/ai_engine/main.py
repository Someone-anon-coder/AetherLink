import asyncio
import websockets
import json
from ultralytics import YOLO
import cv2
import numpy as np
from enum import Enum
from haversine import haversine, Unit
import time
import sys
import functools
import threading

# --- Add Path Modifier ---
sys.path.insert(0, sys.path[0]+'/../..')
from shared.protos.mission_data_pb2 import SystemCommand

# --- CONFIGURATION ---
COMMS_HUB_IP = "127.0.0.1"  # Connect to the local Comms Hub relay
COMMS_HUB_PORT = 8765
GSTREAMER_PIPELINE = "udpsrc port=5601 ! application/x-rtp, encoding-name=H264, payload=96 ! rtph264depay ! decodebin ! videoconvert ! appsink"
model = YOLO('best.pt')

class MissionState(Enum):
    STANDBY = 1
    EXECUTING_SURVEY = 2
    TRANSITING_TO_DROP_ZONE = 3
    PERFORMING_PAYLOAD_DROP = 4
    RESUMING_SURVEY = 5
    RETURNING_TO_LAUNCH = 6

class MissionLogic:
    def __init__(self, command_queue, broadcast_queue):
        self.command_queue = command_queue
        self.broadcast_queue = broadcast_queue
        self.current_state = MissionState.STANDBY
        self.detected_objects = []
        self.latest_telemetry = {}
        self.survey_altitude_m = 15.0
        self.duplicate_distance_m = 10.0
        self.resume_point = None
        self.payload_dropped = False

    async def _set_state(self, new_state):
        if self.current_state != new_state:
            self.current_state = new_state
            print(f"LOG: State changed to {new_state.name}.")
            await self.broadcast_queue.put({'type': 'mission_state', 'state': new_state.name})

    async def process_packet(self, packet):
        # Always update telemetry
        if packet['type'] == 'telemetry':
            self.latest_telemetry = packet

        # Route packet to the correct state handler
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
        if packet['type'] == 'telemetry' and packet.get('relative_altitude_m', 0) > 5.0:
            await self._set_state(MissionState.EXECUTING_SURVEY)

    async def _handle_executing_survey_state(self, packet):
        if packet['type'] == 'detections_result':
            for detection in packet['detections']:
                world_coords = self._calculate_world_coordinates(detection['box'], self.latest_telemetry)
                if not self._is_duplicate(world_coords):
                    class_name = detection['class_name']
                    lat, lon = world_coords
                    self.detected_objects.append({'class_name': class_name, 'coords': world_coords})
                    log_msg = f"LOGGED: {class_name} at ({lat:.5f}, {lon:.5f})"
                    print(f"** {log_msg} **")
                    await self.broadcast_queue.put({'type': 'mission_log', 'message': log_msg})

            if 'disaster_zone' in [d['class_name'] for d in packet.get('detections', [])] and not self.payload_dropped:
                print("\n!!! DISASTER ZONE DETECTED !!!")
                self.resume_point = self.latest_telemetry
                print(f"LOG: Saving resume point at {self.resume_point['latitude']}, {self.resume_point['longitude']}")
                await self._set_state(MissionState.TRANSITING_TO_DROP_ZONE)

        if self._is_survey_complete() and self.payload_dropped:
            await self._set_state(MissionState.RETURNING_TO_LAUNCH)

    async def _handle_transiting_to_drop_zone_state(self, packet):
        if self.resume_point:
            disaster_coords = (self.resume_point.get('latitude'), self.resume_point.get('longitude'))
            location_payload = {"latitude": disaster_coords[0], "longitude": disaster_coords[1], "altitude_m": self.survey_altitude_m}
            await self._send_command(SystemCommand.CommandType.GOTO_LOCATION, payload_data=location_payload)
        await self._set_state(MissionState.PERFORMING_PAYLOAD_DROP)

    async def _handle_performing_payload_drop_state(self, packet):
        descend_payload = {"latitude": self.latest_telemetry.get('latitude'),"longitude": self.latest_telemetry.get('longitude'),"altitude_m": 10.0}
        await self._send_command(SystemCommand.CommandType.GOTO_LOCATION, payload_data=descend_payload)
        await asyncio.sleep(5)
        servo_payload = {"servo_id": 0, "pwm_value": 1800}
        await self._send_command(SystemCommand.CommandType.SET_SERVO, payload_data=servo_payload)
        self.payload_dropped = True
        print("LOG: Payload has been dropped.")
        await asyncio.sleep(2)
        ascend_payload = {"latitude": self.latest_telemetry.get('latitude'), "longitude": self.latest_telemetry.get('longitude'), "altitude_m": self.survey_altitude_m}
        await self._send_command(SystemCommand.CommandType.GOTO_LOCATION, payload_data=ascend_payload)
        if self.resume_point:
            await self._set_state(MissionState.RESUMING_SURVEY)
        else:
            await self._set_state(MissionState.RETURNING_TO_LAUNCH)

    async def _handle_resuming_survey_state(self, packet):
        resume_payload = {"latitude": self.resume_point.get('latitude'), "longitude": self.resume_point.get('longitude'), "altitude_m": self.resume_point.get('relative_altitude_m')}
        await self._send_command(SystemCommand.CommandType.GOTO_LOCATION, payload_data=resume_payload)
        print("LOG: Commanded drone to resume point. Resuming survey.")
        await self._set_state(MissionState.EXECUTING_SURVEY)
        self.resume_point = None

    async def _handle_returning_to_launch_state(self, packet):
        if self.current_state == MissionState.RETURNING_TO_LAUNCH:
            await self._send_command(SystemCommand.CommandType.RETURN_TO_LAUNCH)
            self.current_state = None  # Or some final state

    async def _send_command(self, command_type, payload_data=None):
        command_message = {"type": "system_command", "command_name": SystemCommand.CommandType.Name(command_type), "payload": payload_data}
        await self.command_queue.put(json.dumps(command_message))
        print(f"CMD: Queued command: {command_message['command_name']}")

    def _calculate_world_coordinates(self, detection_pixel_coords, drone_telemetry):
        return (drone_telemetry.get('latitude'), drone_telemetry.get('longitude'))
    def _is_duplicate(self, new_coords):
        for obj in self.detected_objects:
            if haversine(obj['coords'], new_coords, unit=Unit.METERS) < self.duplicate_distance_m:
                return True
        return False
    def _is_survey_complete(self):
        return len(self.detected_objects) > 2

def video_processing_thread(loop, mission_logic, model, stop_event):
    cap = cv2.VideoCapture(GSTREAMER_PIPELINE, cv2.CAP_GSTREAMER)
    if not cap.isOpened():
        print("Error: Could not open video stream from GStreamer pipeline.")
        return

    print("--> Video processing thread started successfully.")
    while not stop_event.is_set():
        ret, frame = cap.read()
        if not ret:
            print("Video stream ended or failed.")
            time.sleep(1)
            continue

        results = model(frame, verbose=False)
        result = results[0]
        detections = []
        if len(result.boxes) > 0:
            for box in result.boxes:
                class_id = int(box.cls[0])
                class_name = model.names[class_id]
                detections.append({'class_name': class_name, 'box': box.xyxy[0].tolist()})
                print(f"DETECTED: {class_name}")

        packet = {'type': 'detections_result', 'detections': detections}
        asyncio.run_coroutine_threadsafe(mission_logic.process_packet(packet), loop)

    print("--- Video processing thread has shut down. ---")
    cap.release()

async def command_sender(websocket, queue):
    while True:
        command_json = await queue.get()
        try:
            await websocket.send(command_json)
        except websockets.ConnectionClosed:
            break
        finally:
            queue.task_done()

async def broadcast_sender(websocket, queue):
    while True:
        message = await queue.get()
        try:
            await websocket.send(json.dumps(message))
        except websockets.ConnectionClosed:
            break
        finally:
            queue.task_done()

async def run():
    uri = f"ws://{COMMS_HUB_IP}:{COMMS_HUB_PORT}"
    command_queue = asyncio.Queue()
    broadcast_queue = asyncio.Queue()
    mission_logic = MissionLogic(command_queue, broadcast_queue)

    while True:
        try:
            async with websockets.connect(uri) as websocket:
                print(f"--- Connected to Comms Hub at {uri} ---")
                stop_event = threading.Event()
                loop = asyncio.get_running_loop()

                # Start the video processing in a separate thread
                video_thread_func = functools.partial(video_processing_thread, loop, mission_logic, model, stop_event)
                video_future = loop.run_in_executor(None, video_thread_func)

                command_sender_task = asyncio.create_task(command_sender(websocket, command_queue))
                broadcast_sender_task = asyncio.create_task(broadcast_sender(websocket, broadcast_queue))

                # This loop now ONLY processes telemetry from the Comms Hub
                async for message in websocket:
                    data = json.loads(message)
                    if data.get('type') == 'telemetry':
                        await mission_logic.process_packet(data)

                # Cancel tasks on graceful disconnect
                command_sender_task.cancel()
                broadcast_sender_task.cancel()
                await asyncio.gather(command_sender_task, broadcast_sender_task, return_exceptions=True)

        except (websockets.ConnectionClosed, ConnectionRefusedError) as e:
            print(f"Connection lost or refused: {e}. Reconnecting in 5 seconds...")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
        finally:
            if 'stop_event' in locals():
                stop_event.set()
            if 'video_future' in locals():
                await video_future
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n--> AI Engine shutting down.")
