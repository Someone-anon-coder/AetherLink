#include "MavlinkManager.h"
#include <thread>
#include <chrono>

int main() {
    MavlinkManager mavlink_manager;
    mavlink_manager.connect_and_start();

    // Keep the main thread alive
    while (true) {
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }

    return 0;
}
