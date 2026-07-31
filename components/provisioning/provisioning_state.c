#include "provisioning_state.h"

#include <string.h>

static void reconcile_requirements(provisioning_state_t *state)
{
    state->sta_required = state->valid_config;
    state->ap_required =
        !(state->valid_config &&
          state->wifi_connected &&
          state->mqtt_connected &&
          state->has_bond &&
          !state->recovery_window);
}

provisioning_state_t provisioning_initial(void)
{
    provisioning_state_t state;
    memset(&state, 0, sizeof(state));
    return state;
}

provisioning_state_t provisioning_reduce(provisioning_state_t current,
                                         provisioning_event_t event,
                                         uint64_t now_ms)
{
    switch (event) {
    case PROVISION_EVENT_BOOT_NO_CONFIG:
        current.valid_config = false;
        current.wifi_connected = false;
        current.mqtt_connected = false;
        current.recovery_window = false;
        current.recovery_deadline_ms = 0;
        break;

    case PROVISION_EVENT_BOOT_VALID_CONFIG:
        current.valid_config = true;
        current.wifi_connected = false;
        current.mqtt_connected = false;
        current.recovery_window = false;
        current.recovery_deadline_ms = 0;
        break;

    case PROVISION_EVENT_WIFI_CONNECTED:
        current.wifi_connected = true;
        break;

    case PROVISION_EVENT_WIFI_TIMEOUT:
        current.wifi_connected = false;
        current.mqtt_connected = false;
        break;

    case PROVISION_EVENT_MQTT_CONNECTED:
        current.mqtt_connected = current.wifi_connected;
        break;

    case PROVISION_EVENT_MQTT_FAILED:
        current.mqtt_connected = false;
        break;

    case PROVISION_EVENT_BOND_PRESENT:
        current.has_bond = true;
        break;

    case PROVISION_EVENT_BOND_REMOVED:
        current.has_bond = false;
        break;

    case PROVISION_EVENT_BOOT_HELD_3S:
        current.recovery_window = true;
        current.recovery_deadline_ms =
            now_ms > UINT64_MAX - PROVISION_RECOVERY_WINDOW_MS
                ? UINT64_MAX
                : now_ms + PROVISION_RECOVERY_WINDOW_MS;
        break;

    case PROVISION_EVENT_PORTAL_IDLE_TIMEOUT:
        if (current.recovery_window &&
            now_ms >= current.recovery_deadline_ms) {
            current.recovery_window = false;
            current.recovery_deadline_ms = 0;
        }
        break;

    default:
        break;
    }

    reconcile_requirements(&current);
    return current;
}

