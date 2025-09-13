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
        _telemetry = std::make_shared<mavsdk::Telemetry>(_system);

        std::cout << " ========== MAVLINK TELEMETRY ========== " << std::endl;

        _telemetry->subscribe_attitude_euler([this](mavsdk::Telemetry::EulerAngle angle) {
            std::cout << "==============================" << std::endl;
            std::cout << "== Roll(deg): "  << (std::isnan(angle.roll_deg)  ? "NaN" : std::to_string(angle.roll_deg))  << " == " << std::endl;
            std::cout << "== Pitch(deg): " << (std::isnan(angle.pitch_deg) ? "NaN" : std::to_string(angle.pitch_deg)) << " == " << std::endl;
            std::cout << "== Yaw(deg): "   << (std::isnan(angle.yaw_deg)   ? "NaN" : std::to_string(angle.yaw_deg))   << " == " << std::endl;
            std::cout << "==============================" << std::endl;
        });

        _telemetry->subscribe_position([this](mavsdk::Telemetry::Position position) {
            std::cout << "==============================" << std::endl;
            std::cout << "Latitude:  "   << (std::isnan(position.latitude_deg)        ? "NaN" : std::to_string(position.latitude_deg))        << " == " << std::endl;
            std::cout << "Longitude: "   << (std::isnan(position.longitude_deg)       ? "NaN" : std::to_string(position.longitude_deg))       << " == " << std::endl;
            std::cout << "Altitude(m): " << (std::isnan(position.relative_altitude_m) ? "NaN" : std::to_string(position.relative_altitude_m)) << " == " << std::endl;
            std::cout << "==============================" << std::endl;
        });

        std::cout << "====================================================" << std::endl;
    });
}
