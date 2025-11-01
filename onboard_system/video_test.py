import cv2
import sys

# Define the GStreamer pipeline for connecting to the Gazebo camera
GAZEBO_GSTREAMER_PIPELINE = "udpsrc port=5600 ! application/x-rtp, media=video, clock-rate=90000, encoding-name=H264, payload=96 ! rtph264depay ! decodebin ! videoconvert ! appsink"

def main():
    """
    Captures and displays the video stream from the Gazebo simulator.
    """
    print("Starting Gazebo video test script...")

    # Create a VideoCapture object
    cap = cv2.VideoCapture(GAZEBO_GSTREAMER_PIPELINE, cv2.CAP_GSTREAMER)

    # Check if the VideoCapture object was opened successfully
    if not cap.isOpened():
        print("Error: Could not open video stream.")
        print("Please check if the Gazebo simulation is running and if the correct drone model with a camera is being used.")
        sys.exit()

    print("--> Video stream connected. Displaying feed. Press 'q' to quit.")

    while True:
        # Read a frame from the video stream
        ret, frame = cap.read()

        # Check if the frame was read successfully
        if not ret:
            print("Error: Could not read frame from video stream.")
            break

        # Display the frame
        cv2.imshow("Gazebo Camera Feed", frame)

        # Check for user input to quit
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # Clean up
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
