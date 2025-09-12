cmake_minimum_required(VERSION 3.10)
project(AetherlinkFCAgent)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(MAVSDK REQUIRED)

add_executable(fc_agent
    src/main.cpp
    src/MavlinkManager.cpp
)

target_link_libraries(fc_agent MAVSDK::mavsdk)
