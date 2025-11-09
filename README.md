# Project Aetherlink: GCS Architecture

This repository contains the software for a two-component drone control system: an Onboard System and a Ground Control Station (GCS).

## System Architecture

1. **Onboard System (Raspberry Pi):** A lightweight client responsible for capturing and streaming sensor data (video, telemetry) over a single WebSocket connection.

2. **Ground Control Station (Laptop):** A comprehensive server application that receives the data stream, performs AI inference, displays a mission dashboard, and logs all flight data.
