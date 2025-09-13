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

MavlinkManager::MavlinkManager() :
    _secure_transmitter(std::make_unique<SecureTransmitter>("127.0.0.1", 50051)) {
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

        if (!_secure_transmitter->connect()) {
            return;
        }

        _system = _mavsdk->systems().front();
        _telemetry = std::make_shared<mavsdk::Telemetry>(_system);

        std::cout << " ========== MAVLINK TELEMETRY ========== " << std::endl;

        _telemetry->subscribe_attitude_euler([this](mavsdk::Telemetry::EulerAngle angle) {
            std::lock_guard<std::mutex> lock(_telemetry_mutex);
            _latest_attitude = angle;
        });

        _telemetry->subscribe_position([this](mavsdk::Telemetry::Position position) {
            std::lock_guard<std::mutex> lock(_telemetry_mutex);
            _latest_position = position;
            if (_latest_attitude) {
                auto serialized_data = _serialization_manager.serialize_telemetry(_latest_attitude.value(), _latest_position.value());
                _secure_transmitter->send(serialized_data);
            }
        });

        std::cout << "====================================================" << std::endl;
    });
}
