# AetherLink

AetherLink is a secure telemetry system for unmanned aerial vehicles (UAVs), providing a secure communication channel between a UAV's flight controller and a ground station. It ensures the integrity and confidentiality of telemetry data by using mutual TLS (mTLS) for authentication and encryption.

## Project Overview

The project consists of two main components:

*   **AetherLink Flight Controller Agent (`aetherlink-fc-agent`):** A C++ application that runs on an onboard computer connected to the flight controller. It collects telemetry data using the MAVSDK and transmits it securely to the ground station.
*   **AetherLink Ground Station Backend (`aetherlink-gs-backend`):** A Go application that runs on a ground station computer. It receives the encrypted telemetry data, decrypts it, and makes it available for display or further processing.

The telemetry data is serialized using Protocol Buffers (Protobuf) for efficient and language-agnostic data exchange.

## AetherLink Flight Controller Agent (`aetherlink-fc-agent`)

The flight controller agent is a C++ application responsible for the following:

*   Connecting to the flight controller via MAVLink.
*   Subscribing to telemetry data (position and attitude).
*   Serializing the telemetry data into a Protobuf message.
*   Establishing a secure mTLS connection with the ground station backend.
*   Transmitting the serialized telemetry data to the ground station.

### Building and Running

**Prerequisites:**

*   C++17 compiler
*   CMake
*   MAVSDK
*   OpenSSL

**Build Steps:**

1.  Navigate to the `aetherlink-fc-agent` directory.
2.  Create a `build` directory: `mkdir build && cd build`
3.  Run CMake: `cmake ..`
4.  Compile the source code: `make`

**Running the Agent:**

After a successful build, the executable will be located in the `build` directory. To run the agent:

```bash
./aetherlink-fc-agent
```

## AetherLink Ground Station Backend (`aetherlink-gs-backend`)

The ground station backend is a Go application that performs the following tasks:

*   Listens for incoming mTLS connections from the flight controller agent.
*   Verifies the client's certificate.
*   Receives the encrypted telemetry data.
*   Deserializes the Protobuf message.
*   Prints the received telemetry data to the console.

### Building and Running

**Prerequisites:**

*   Go 1.18 or higher
*   Protocol Buffers compiler (`protoc`)

**Build Steps:**

1.  Navigate to the `aetherlink-gs-backend` directory.
2.  Install the required Go modules: `go mod tidy`
3.  Compile the application: `go build`

**Running the Backend:**

After a successful build, the executable will be in the `aetherlink-gs-backend` directory. To run the backend:

```bash
./aetherlink-gs-backend
```

## Current Status

The project is currently in a proof-of-concept stage. The following features are implemented:

*   Secure communication between the flight controller agent and the ground station backend using mTLS.
*   Serialization and deserialization of telemetry data (position and attitude) using Protobuf.
*   Basic data display on the ground station backend's console.

**Limitations:**

*   The system has been tested only in a simulated environment.
*   Error handling is minimal.
*   The ground station does not have a graphical user interface (GUI).

## Future Work

*   **Real-world Testing:** Test the system on a physical UAV to evaluate its performance and reliability in a real-world environment.
*   **Bidirectional Communication:** Implement bidirectional communication to allow the ground station to send commands to the UAV.
*   **GUI for Ground Station:** Develop a graphical user interface for the ground station to provide a more user-friendly way to visualize telemetry data.
*   **Support for More MAVLink Messages:** Extend the system to support a wider range of MAVLink messages.
