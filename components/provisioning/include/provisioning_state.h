#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PROVISION_RECOVERY_WINDOW_MS UINT64_C(600000)
/* Proven MQTT settings that the broker keeps refusing open the setup AP only
 * after this long; brokers that authenticate against Home Assistant refuse
 * logins while Home Assistant restarts. */
#define PROVISION_MQTT_REJECTED_RECOVERY_MS UINT64_C(600000)

typedef enum {
    PROVISION_EVENT_BOOT_NO_CONFIG = 0,
    PROVISION_EVENT_BOOT_VALID_CONFIG,
    PROVISION_EVENT_WIFI_CONNECTED,
    PROVISION_EVENT_WIFI_TIMEOUT,
    PROVISION_EVENT_MQTT_CONNECTED,
    /* The broker or the network is unreachable. */
    PROVISION_EVENT_MQTT_FAILED,
    PROVISION_EVENT_BOND_PRESENT,
    PROVISION_EVENT_BOND_REMOVED,
    PROVISION_EVENT_BOOT_HELD_3S,
    PROVISION_EVENT_PORTAL_IDLE_TIMEOUT,
    PROVISION_EVENT_WIFI_DISCONNECTED,
    /* The broker answered and refused these settings. */
    PROVISION_EVENT_MQTT_REJECTED,
    /* The saved MQTT settings connected before (stored marker). */
    PROVISION_EVENT_MQTT_SETTINGS_VERIFIED,
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
    /* These MQTT settings connected at least once. */
    bool mqtt_settings_verified;
    /* The broker has refused the settings since the last connection. */
    bool mqtt_rejecting;
    uint64_t recovery_deadline_ms;
    uint64_t mqtt_rejected_since_ms;
} provisioning_state_t;

provisioning_state_t provisioning_initial(void);
provisioning_state_t provisioning_reduce(provisioning_state_t current,
                                         provisioning_event_t event,
                                         uint64_t now_ms);

#ifdef __cplusplus
}
#endif

