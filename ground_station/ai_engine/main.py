# ground_station/ai_engine/main.py

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
COMMS_HUB_IP = "100.69.186.67"  # <-- USER: Set Tailscale IP of Comms Hub Laptop
COMMS_HUB_PORT = 8765
AI_ENGINE_VIDEO_PORT = 5601  # This is the port WE listen on for UDP video
model = YOLO('best.pt')

# This pipeline correctly expects an RTP-encapsulated H.264 stream.
GSTREAMER_PIPELINE = (
    f"udpsrc port={AI_ENGINE_VIDEO_PORT} "
    "! application/x-rtp, media=video, clock-rate=90000, encoding-name=H264 "
    "! rtph264depay "
    "! decodebin "
    "! videoconvert "
    "! appsink"
)

class MissionState(Enum):
    STANDBY = 1
    EXECUTING_SURVEY = 2
    TRANSITING_TO_DROP_ZONE = 3
    PERFORMING_PAYLOAD_DROP = 4
    RESUMING_SURVEY = 5
    RETURNING_TO_LAUNCH = 6
    MISSION_COMPLETE = 7

class FlightLogger:
    """Handles logging of all major flight events to a JSON file."""
    def __init__(self):
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.log_file_path = f"flight_log_{timestamp}.json"
        self.log_file = open(self.log_file_path, 'w')
        print(f"INFO: New flight log started: {self.log_file_path}")

    def log(self, event_type, data):
        log_entry = {"timestamp": datetime.now().isoformat(), "event_type": event_type, "data": data}
        self.log_file.write(json.dumps(log_entry) + '\n')
        self.log_file.flush() # Ensure data is written immediately

    def close(self):
        if self.log_file:
            self.log_file.close()
            print(f"INFO: Flight log saved to {self.log_file_path}")

class MissionLogic:
    """Manages the mission state and decision-making process."""
    def __init__(self, command_queue, broadcast_queue, logger):
        self.command_queue = command_queue
        self.broadcast_queue = broadcast_queue
        self.logger = logger
        self.current_state = MissionState.STANDBY
        self.detected_objects = []
        self.latest_telemetry = {}
        self.duplicate_distance_m = 10.0
        self.resume_point = None
        self.payload_dropped = False

    async def _set_state(self, new_state):
        if self.current_state != new_state:
            self.current_state = new_state
            state_name = new_state.name if new_state else "MISSION_COMPLETE"
            state_data = {'state': state_name}
            print(f"LOG: State changed to {state_name}.")
            self.logger.log('STATE_CHANGE', state_data)
            await self.broadcast_queue.put({'type': 'mission_state', 'state': state_name})

    async def process_telemetry(self, telemetry_packet):
        self.latest_telemetry = telemetry_packet
        if self.current_state == MissionState.STANDBY:
            if telemetry_packet.get('relative_altitude_m', 0) > 2.0:
                await self._set_state(MissionState.EXECUTING_SURVEY)
    
    async def process_detections(self, detections):
        if self.current_state == MissionState.EXECUTING_SURVEY:
            # --- Object Detection Logic ---
            for detection in detections:
                if not self.latest_telemetry: continue
                world_coords = self._calculate_world_coordinates(detection['box'], self.latest_telemetry)
                if world_coords and not self._is_duplicate(world_coords):
                    class_name = detection['class_name']
                    lat, lon = world_coords
                    detection_data = {'class_name': class_name, 'latitude': lat, 'longitude': lon}
                    self.detected_objects.append({'coords': world_coords})
                    self.logger.log('DETECTION', detection_data)
                    log_msg = f"LOGGED: {class_name} at ({lat:.5f}, {lon:.5f})"
                    print(f"** {log_msg} **")
                    await self.broadcast_queue.put({'type': 'mission_log', 'message': log_msg})
            
            # --- Disaster Detection Logic ---
            if 'disaster_zone' in [d['class_name'] for d in detections] and not self.payload_dropped:
                print("\n!!! DISASTER ZONE DETECTED !!!")
                self.resume_point = self.latest_telemetry
                self.logger.log('INTERRUPTION', {'reason': 'disaster_zone_detected', 'resume_point': self.resume_point})
                await self._set_state(MissionState.TRANSITING_TO_DROP_ZONE)
                await self._handle_transiting_to_drop_zone_state()

    async def _handle_transiting_to_drop_zone_state(self):
        print("CMD LOGIC: Simulating transition to drop zone.")
        await asyncio.sleep(1)
        await self._set_state(MissionState.PERFORMING_PAYLOAD_DROP)
        await self._handle_performing_payload_drop_state()

    async def _handle_performing_payload_drop_state(self):
        print("CMD LOGIC: Simulating payload drop sequence.")
        await asyncio.sleep(2)
        servo_payload = {"servo_id": 0, "pwm_value": 1800}
        await self._send_command(SystemCommand.CommandType.SET_SERVO, payload_data=servo_payload)
        self.payload_dropped = True
        self.logger.log('ACTION', {'action': 'payload_dropped'})
        print("LOG: Payload has been dropped.")
        await asyncio.sleep(2)
        if self.resume_point:
            await self._set_state(MissionState.RESUMING_SURVEY)
            await self._handle_resuming_survey_state()
        else:
            await self._set_state(MissionState.RETURNING_TO_LAUNCH)
            await self._handle_returning_to_launch_state()
            
    async def _handle_resuming_survey_state(self):
        print("CMD LOGIC: Simulating return to survey.")
        self.resume_point = None
        await asyncio.sleep(2)
        await self._set_state(MissionState.EXECUTING_SURVEY)

    async def _handle_returning_to_launch_state(self):
        await self._send_command(SystemCommand.CommandType.RETURN_TO_LAUNCH)
        await self._set_state(MissionState.MISSION_COMPLETE)

    async def _send_command(self, command_type, payload_data=None):
        command_message = {"type": "system_command", "command_name": command_type.name, "payload": payload_data}
        await self.command_queue.put(json.dumps(command_message))
        print(f"CMD: Queued command: {command_type.name}")

    def _calculate_world_coordinates(self, box, telemetry):
        if 'latitude' in telemetry and 'longitude' in telemetry:
            return (telemetry['latitude'], telemetry['longitude'])
        return None

    def _is_duplicate(self, new_coords):
        for obj in self.detected_objects:
            if haversine(obj['coords'], new_coords, unit=Unit.METERS) < self.duplicate_distance_m:
                return True
        return False

def video_processing_thread(mission_logic, stop_event):
    """Runs in a separate thread to handle blocking OpenCV calls."""
    cap = cv2.VideoCapture(GSTREAMER_PIPELINE, cv2.CAP_GSTREAMER)
    if not cap.isOpened():
        print(f"ERROR: Could not open GStreamer pipeline on port {AI_ENGINE_VIDEO_PORT}.")
        print("TROUBLESHOOTING: Check that Comms Hub is running and forwarding video.")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    video_log_path = f"video_log_{timestamp}.mp4"
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    # Assuming 1280x720 from the Pi streamer
    out = cv2.VideoWriter(video_log_path, fourcc, 20.0, (1280, 720))

    loop = asyncio.get_running_loop()
    print("INFO: Video processing thread started, receiving stream.")
    
    start_time = time.time()
    
    while not stop_event.is_set():
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.01)
            continue
        
        results = model(frame, verbose=False)
        result = results[0]
        detections = []
        
        annotated_frame = frame.copy()
        for box in result.boxes:
            class_id = int(box.cls[0])
            class_name = model.names[class_id]
            detections.append({'class_name': class_name, 'box': box.xyxy[0].tolist()})
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(annotated_frame, f"{class_name} {float(box.conf):.2f}", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
            
        out.write(annotated_frame)
        
        if time.time() - start_time > 20 and not mission_logic.payload_dropped:
            detections.append({'class_name': 'disaster_zone', 'box': []})
        
        if detections:
            asyncio.run_coroutine_threadsafe(mission_logic.process_detections(detections), loop)

    print("INFO: Video processing thread shutting down.")
    cap.release()
    out.release()
    print(f"INFO: Annotated video saved to {video_log_path}")

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

    stop_event = threading.Event()
    loop = asyncio.get_running_loop()
    video_thread_func = functools.partial(video_processing_thread, mission_logic, stop_event)
    video_thread_task = loop.run_in_executor(None, video_thread_func)

    while True:
        try:
            async with websockets.connect(uri) as websocket:
                print(f"INFO: Connected to Comms Hub at {uri}")
                
                cmd_sender_task = asyncio.create_task(command_sender(websocket, command_queue))
                broadcast_task = asyncio.create_task(broadcast_sender(websocket, broadcast_queue))
                
                async for message in websocket:
                    data = json.loads(message)
                    if data.get('type') == 'telemetry':
                        await mission_logic.process_telemetry(data)
                
        except (websockets.ConnectionClosed, ConnectionRefusedError) as e:
            print(f"WARN: Connection to Comms Hub lost: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"ERROR: An unexpected error occurred in networking: {e}")
            break

    stop_event.set()
    await video_thread_task
    flight_logger.close()

if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n--> AI Engine shutting down.")
