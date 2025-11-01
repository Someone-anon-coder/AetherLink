#!/bin/bash
# This script compiles the .proto files into Python code.
# It must be run from the root of the Aetherlink repository.

# Prerequisite: Install the protobuf compiler and python tools.
# On your active virtual environment, run:
# pip install grpcio-tools

echo "Compiling protocol buffers..."

python3 -m grpc_tools.protoc \
    -I=./shared/protos \
    --python_out=./shared/protos \
    mission_data.proto

# Create an __init__.py file to make the folder a Python package
touch ./shared/protos/__init__.py

echo "Compilation complete. Python files generated in shared/protos/"
