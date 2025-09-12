#include "MavlinkManager.h"
#include <iostream>
#include <thread>
#include <chrono>

#include <mavsdk/mavsdk.h>
#include <chrono>
#include <cstdint>
#include <mavsdk/plugins/telemetry/telemetry.h>
#include <iostream>
#include <future>
#include <memory>
#include <thread>

MavlinkManager::MavlinkManager() {
    _mavsdk = std::make_unique<mavsdk::Mavsdk>(
        mavsdk::Mavsdk::Configuration(mavsdk::ComponentType::GroundStation));
}

void MavlinkManager::connect_and_start() {
    auto result = _mavsdk->add_any_connection("udp://:14540");
    if (result != mavsdk::ConnectionResult::Success) {
        std::cout << "Connection failed: " << result << '\n';
        return;
    }

    std::cout << "Waiting for system to connect\n";
    _mavsdk->subscribe_on_new_system([this]() {
        std::cout << "Discovered a new system\n";
        _system = _mavsdk->systems().front();
        auto telemetry = std::make_shared<mavsdk::Telemetry>(_system);

        telemetry->subscribe_attitude_euler([this](mavsdk::Telemetry::EulerAngle angle) {
            std::cout << "Attitude: "
                      << "Roll(deg): " << angle.roll_deg << ", "
                      << "Pitch(deg): " << angle.pitch_deg << ", "
                      << "Yaw(deg): " << angle.yaw_deg << std::endl;
        });

        telemetry->subscribe_position([this](mavsdk::Telemetry::Position position) {
            std::cout << "Position: "
                      << "Lat: " << position.latitude_deg << ", "
                      << "Lon: " << position.longitude_deg << ", "
                      << "Alt(m): " << position.relative_altitude_m << std::endl;
        });
    });
}
