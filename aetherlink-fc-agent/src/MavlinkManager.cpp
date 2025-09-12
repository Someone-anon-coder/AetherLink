#include "MavlinkManager.h"
#include <iostream>
#include <thread>
#include <chrono>

MavlinkManager::MavlinkManager() {}

void MavlinkManager::connect_and_start() {
    mavsdk::ConnectionResult connection_result;

    std::cout << "Connecting to simulator..." << std::endl;
    connection_result = _mavsdk.add_any_connection("udp://:14540");

    if (connection_result != mavsdk::ConnectionResult::Success) {
        std::cerr << "Connection failed: " << connection_result << std::endl;
        return;
    }

    std::cout << "Waiting for system to be discovered..." << std::endl;
    _mavsdk.subscribe_on_new_system([this]() {
        const auto system = _mavsdk.systems().at(0);

        if (system->is_connected()) {
            _system = system;
            std::cout << "System discovered!" << std::endl;

            std::cout << "Subscribing to telemetry..." << std::endl;
            auto telemetry = std::make_shared<mavsdk::Telemetry>(_system);

            telemetry->subscribe_attitude([this](mavsdk::Telemetry::Attitude attitude) {
                std::cout << "Attitude: "
                          << "Roll(deg): " << attitude.roll_deg << ", "
                          << "Pitch(deg): " << attitude.pitch_deg << ", "
                          << "Yaw(deg): " << attitude.yaw_deg << std::endl;
            });

            telemetry->subscribe_position([this](mavsdk::Telemetry::Position position) {
                std::cout << "Position: "
                          << "Lat: " << position.latitude_deg << ", "
                          << "Lon: " << position.longitude_deg << ", "
                          << "Alt(m): " << position.relative_altitude_m << std::endl;
            });
        }
    });
}
