#include "SerializationManager.h"

std::string SerializationManager::serialize_telemetry(const mavsdk::Telemetry::EulerAngle& attitude, const mavsdk::Telemetry::Position& position) {
    AetherLinkTelemetry telemetry_msg;
    telemetry_msg.set_roll_deg(attitude.roll_deg);
    telemetry_msg.set_pitch_deg(attitude.pitch_deg);
    telemetry_msg.set_yaw_deg(attitude.yaw_deg);
    telemetry_msg.set_latitude_deg(position.latitude_deg);
    telemetry_msg.set_longitude_deg(position.longitude_deg);
    telemetry_msg.set_relative_altitude_m(position.relative_altitude_m);

    std::string serialized_data;
    telemetry_msg.SerializeToString(&serialized_data);
    return serialized_data;
}
