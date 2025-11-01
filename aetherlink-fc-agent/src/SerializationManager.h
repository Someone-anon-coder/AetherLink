#ifndef SERIALIZATION_MANAGER_H
#define SERIALIZATION_MANAGER_H

#include "telemetry.pb.h"
#include <mavsdk/plugins/telemetry/telemetry.h>
#include <string>

class SerializationManager {
public:
    std::string serialize_telemetry(const mavsdk::Telemetry::EulerAngle& attitude, const mavsdk::Telemetry::Position& position);
};

#endif // SERIALIZATION_MANAGER_H
