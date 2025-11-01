# Project Aetherlink: AeroTHON 2025 GCS

This repository contains the complete software suite for Team Vayuratha's entry in the AeroTHON 2025 competition. The system is designed as a distributed, ground-control-based intelligence network for autonomous drone operations.

## System Architecture

The suite consists of four primary, independent software components that communicate over a secure VPN:

1.  **Onboard System (Raspberry Pi):** Captures and streams real-time telemetry and video.
2.  **Communications Hub (Laptop 3):** The central server that ingests all drone data and broadcasts it to the GCS modules.
3.  **AI Engine (Laptop 1):** Performs real-time object detection, runs mission logic, and makes autonomous decisions.
4.  **Dashboard (Laptop 2):** Provides the human operators with a comprehensive GUI for mission monitoring and situational awareness.

## Hardware Stack
*   **Flight Controller:** Pixhawk 2.4.8
*   **Companion Computer:** Raspberry Pi 3B
*   **Camera:** Raspberry Pi Camera Module
