cmake_minimum_required(VERSION 3.10)
project(AetherlinkFCAgent)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(MAVSDK REQUIRED)
find_package(Protobuf REQUIRED)

set(PROTO_FILES ${CMAKE_CURRENT_SOURCE_DIR}/proto/telemetry.proto)
protobuf_generate_cpp(PROTO_SRCS PROTO_HDRS ${PROTO_FILES})

include_directories(${CMAKE_CURRENT_BINARY_DIR})

add_executable(fc_agent
    src/main.cpp
    src/MavlinkManager.cpp
    src/SerializationManager.cpp
    ${PROTO_SRCS}
)

target_include_directories(fc_agent PUBLIC ${Protobuf_INCLUDE_DIRS})
target_link_libraries(fc_agent MAVSDK::mavsdk ${Protobuf_LIBRARIES})
