#ifndef MAVLINK_MANAGER_H
#define MAVLINK_MANAGER_H

#include <mavsdk/mavsdk.h>
#include <mavsdk/plugins/telemetry/telemetry.h>
#include <memory>

class MavlinkManager {
public:
    MavlinkManager();
    void connect_and_start();

private:
    std::unique_ptr<mavsdk::Mavsdk> _mavsdk;
    std::shared_ptr<mavsdk::System> _system;
    std::shared_ptr<mavsdk::Telemetry> _telemetry;
};

#endif // MAVLINK_MANAGER_H
