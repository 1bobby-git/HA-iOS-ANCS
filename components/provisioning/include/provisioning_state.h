#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PROVISION_RECOVERY_WINDOW_MS UINT64_C(600000)

typedef enum {
    PROVISION_EVENT_BOOT_NO_CONFIG = 0,
    PROVISION_EVENT_BOOT_VALID_CONFIG,
    PROVISION_EVENT_WIFI_CONNECTED,
    PROVISION_EVENT_WIFI_TIMEOUT,
    PROVISION_EVENT_MQTT_CONNECTED,
    PROVISION_EVENT_MQTT_FAILED,
    PROVISION_EVENT_BOND_PRESENT,
    PROVISION_EVENT_BOND_REMOVED,
    PROVISION_EVENT_BOOT_HELD_3S,
    PROVISION_EVENT_PORTAL_IDLE_TIMEOUT,
} provisioning_event_t;

typedef struct {
    bool valid_config;
    bool wifi_connected;
    bool mqtt_connected;
    bool has_bond;
    bool recovery_required;
    bool recovery_window;
    bool ap_required;
    bool sta_required;
    uint64_t recovery_deadline_ms;
} provisioning_state_t;

provisioning_state_t provisioning_initial(void);
provisioning_state_t provisioning_reduce(provisioning_state_t current,
                                         provisioning_event_t event,
                                         uint64_t now_ms);

#ifdef __cplusplus
}
#endif

