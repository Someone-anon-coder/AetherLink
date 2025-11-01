#ifndef MAVLINK_MANAGER_H
#define MAVLINK_MANAGER_H

#include <mavsdk/mavsdk.h>
#include <mavsdk/plugins/telemetry/telemetry.h>
#include <memory>
#include <optional>
#include <mutex>
#include "SerializationManager.h"
#include "SecureTransmitter.h"

class MavlinkManager {
public:
    MavlinkManager();
    void connect_and_start();

private:
    std::unique_ptr<mavsdk::Mavsdk> _mavsdk;
    std::shared_ptr<mavsdk::System> _system;
    std::shared_ptr<mavsdk::Telemetry> _telemetry;
    std::unique_ptr<SecureTransmitter> _secure_transmitter;

    std::optional<mavsdk::Telemetry::Position> _latest_position;
    std::optional<mavsdk::Telemetry::EulerAngle> _latest_attitude;
    SerializationManager _serialization_manager;
    std::mutex _telemetry_mutex;
};

#endif // MAVLINK_MANAGER_H
