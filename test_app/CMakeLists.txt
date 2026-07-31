cmake_minimum_required(VERSION 3.16)

set(MINIMAL_BUILD ON)
set(EXTRA_COMPONENT_DIRS
    "${CMAKE_CURRENT_LIST_DIR}/../components/ancs_protocol"
    "${CMAKE_CURRENT_LIST_DIR}/../components/ancs_state"
    "${CMAKE_CURRENT_LIST_DIR}/../components/notification_sink"
    "${CMAKE_CURRENT_LIST_DIR}/../components/platform_identity"
    "${CMAKE_CURRENT_LIST_DIR}/../components/relay_policy"
    "${CMAKE_CURRENT_LIST_DIR}/../components/provision_store"
    "${CMAKE_CURRENT_LIST_DIR}/../components/provisioning"
    "${CMAKE_CURRENT_LIST_DIR}/../components/ble_enroll"
    "${CMAKE_CURRENT_LIST_DIR}/../components/mqtt_relay"
    "${CMAKE_CURRENT_LIST_DIR}/../managed_components/espressif__mqtt"
)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(ios_ancs_capture_c6_tests)
