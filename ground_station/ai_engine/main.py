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
from datetime import datetime

# --- Add Path Modifier ---
sys.path.insert(0, sys.path[0]+'/../..')
from shared.protos.mission_data_pb2 import SystemCommand

# --- CONFIGURATION ---
# <-- USER: Set this to the Tailscale IP of the Comms Hub machine
COMMS_HUB_IP = "127.0.0.1"
COMMS_HUB_PORT = 8765
AI_ENGINE_VIDEO_PORT = 5601
model = YOLO('best.pt')

class MissionState(Enum):
    STANDBY = 1
    EXECUTING_SURVEY = 2
    TRANSITING_TO_DROP_ZONE = 3
    PERFORMING_PAYLOAD_DROP = 4
    RESUMING_SURVEY = 5
    RETURNING_TO_LAUNCH = 6

class FlightLogger:
    def __init__(self):
        self.log_file = None
        self.start_new_log()

    def start_new_log(self):
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.log_file_path = f"flight_log_{timestamp}.json"
        self.log_file = open(self.log_file_path, 'w')
        print(f"INFO: New flight log started: {self.log_file_path}")

    def log(self, event_type, data):
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "data": data
        }
        self.log_file.write(json.dumps(log_entry) + '\n')
        self.log_file.flush()

    def close(self):
        if self.log_file:
            self.log_file.close()

class MissionLogic:
    def __init__(self, command_queue, broadcast_queue, logger):
        self.command_queue = command_queue
        self.broadcast_queue = broadcast_queue
        self.logger = logger
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
            state_data = {'state': new_state.name}
            print(f"LOG: State changed to {new_state.name}.")
            self.logger.log('STATE_CHANGE', state_data)
            await self.broadcast_queue.put({'type': 'mission_state', 'state': new_state.name})

    async def process_packet(self, packet):
        if packet['type'] == 'telemetry':
            self.latest_telemetry = packet
        
        handler = getattr(self, f'_handle_{self.current_state.name.lower()}_state', None)
        if handler:
            await handler(packet)

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
                    detection_data = {'class_name': class_name, 'latitude': lat, 'longitude': lon}
                    self.detected_objects.append({'class_name': class_name, 'coords': world_coords})
                    self.logger.log('DETECTION', detection_data)
                    log_msg = f"LOGGED: {class_name} at ({lat:.5f}, {lon:.5f})"
                    print(f"** {log_msg} **")
                    await self.broadcast_queue.put({'type': 'mission_log', 'message': log_msg})

            if 'disaster_zone' in [d['class_name'] for d in packet.get('detections', [])] and not self.payload_dropped:
                print("\n!!! DISASTER ZONE DETECTED !!!")
                self.resume_point = self.latest_telemetry
                self.logger.log('INTERRUPTION', {'reason': 'disaster_zone_detected', 'resume_point': self.resume_point})
                await self._set_state(MissionState.TRANSITING_TO_DROP_ZONE)

    async def _handle_transiting_to_drop_zone_state(self, packet):
        # Simplified: Assume we are at the drop zone and proceed
        await self._set_state(MissionState.PERFORMING_PAYLOAD_DROP)

    async def _handle_performing_payload_drop_state(self, packet):
        servo_payload = {"servo_id": 0, "pwm_value": 1800}
        await self._send_command(SystemCommand.CommandType.SET_SERVO, payload_data=servo_payload)
        self.payload_dropped = True
        print("LOG: Payload has been dropped.")
        self.logger.log('ACTION', {'action': 'payload_dropped'})
        await asyncio.sleep(2) # Give it time
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
        await self._send_command(SystemCommand.CommandType.RETURN_TO_LAUNCH)
        await self._set_state(None) # Final state

    async def _send_command(self, command_type, payload_data=None):
        command_message = {"type": "system_command", "command_name": SystemCommand.CommandType.Name(command_type), "payload": payload_data}
        await self.command_queue.put(json.dumps(command_message))
        print(f"CMD: Queued command: {command_message['command_name']}")

    def _calculate_world_coordinates(self, detection_pixel_coords, drone_telemetry):
        return (drone_telemetry.get('latitude', 0), drone_telemetry.get('longitude', 0))

    def _is_duplicate(self, new_coords):
        for obj in self.detected_objects:
            if haversine(obj['coords'], new_coords, unit=Unit.METERS) < self.duplicate_distance_m:
                return True
        return False

def video_processing_thread(mission_logic, model, stop_event):
    pipeline = (f"udpsrc port={AI_ENGINE_VIDEO_PORT} ! application/x-rtp, encoding-name=H264 ! "
                "rtph264depay ! decodebin ! videoconvert ! appsink")
    cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
    if not cap.isOpened():
        print(f"Error: Could not open video stream on port {AI_ENGINE_VIDEO_PORT}.")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    video_log_path = f"video_log_{timestamp}.mp4"
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(video_log_path, fourcc, 20.0, (1280, 720))

    loop = asyncio.get_running_loop()
    print("--- Video processing thread started. ---")
    
    while not stop_event.is_set():
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.1)
            continue
        
        results = model(frame, verbose=False)
        result = results[0]
        detections = []
        
        for box in result.boxes:
            class_id = int(box.cls[0])
            class_name = model.names[class_id]
            detections.append({'class_name': class_name, 'box': box.xyxy[0].tolist()})
            
            # Draw on frame for video log
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, class_name, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
            
        out.write(frame)
        
        packet = {'type': 'detections_result', 'detections': detections}
        asyncio.run_coroutine_threadsafe(mission_logic.process_packet(packet), loop)

    print("--- Video processing thread shutting down. ---")
    cap.release()
    out.release()

async def command_sender(websocket, queue):
    while True:
        command_json = await queue.get()
        await websocket.send(command_json)
        queue.task_done()

async def broadcast_sender(websocket, queue):
    while True:
        message = await queue.get()
        await websocket.send(json.dumps(message))
        queue.task_done()

async def run():
    uri = f"ws://{COMMS_HUB_IP}:{COMMS_HUB_PORT}"
    command_queue = asyncio.Queue()
    broadcast_queue = asyncio.Queue()
    flight_logger = FlightLogger()
    mission_logic = MissionLogic(command_queue, broadcast_queue, flight_logger)

    async for websocket in websockets.connect(uri):
        video_stop_event = threading.Event()
        video_thread_task = None
        try:
            print(f"--- Connected to Comms Hub at {uri} ---")
            loop = asyncio.get_running_loop()
            video_thread_func = functools.partial(video_processing_thread, mission_logic, model, video_stop_event)
            video_thread_task = loop.run_in_executor(None, video_thread_func)

            command_task = asyncio.create_task(command_sender(websocket, command_queue))
            broadcast_task = asyncio.create_task(broadcast_sender(websocket, broadcast_queue))

            async for message in websocket:
                data = json.loads(message)
                if data.get('type') in ['telemetry', 'mission_state', 'mission_log']:
                    await mission_logic.process_packet(data)
        
        except websockets.ConnectionClosed:
            print("--- Connection to Comms Hub lost. Reconnecting... ---")
        finally:
            video_stop_event.set()
            if video_thread_task:
                await video_thread_task
            command_task.cancel()
            broadcast_task.cancel()
            await asyncio.sleep(5)
    
    flight_logger.close()

if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n--> AI Engine shutting down.")
