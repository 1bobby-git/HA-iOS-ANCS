#include "provisioning_state.h"

#include <string.h>

static void reconcile_requirements(provisioning_state_t *state)
{
    state->sta_required = state->valid_config;
    state->ap_required = !state->valid_config ||
                         state->recovery_required ||
                         state->recovery_window;
}

static bool mqtt_rejection_established(const provisioning_state_t *state,
                                       uint64_t now_ms)
{
    return state->mqtt_rejecting &&
           now_ms >= state->mqtt_rejected_since_ms &&
           now_ms - state->mqtt_rejected_since_ms >=
               PROVISION_MQTT_REJECTED_RECOVERY_MS;
}

static void forget_mqtt_settings(provisioning_state_t *state)
{
    state->mqtt_settings_verified = false;
    state->mqtt_rejecting = false;
    state->mqtt_rejected_since_ms = 0;
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
        current.recovery_required = false;
        current.recovery_window = false;
        current.recovery_deadline_ms = 0;
        forget_mqtt_settings(&current);
        break;

    case PROVISION_EVENT_BOOT_VALID_CONFIG:
        current.valid_config = true;
        current.wifi_connected = false;
        current.mqtt_connected = false;
        current.recovery_required = false;
        current.recovery_window = false;
        current.recovery_deadline_ms = 0;
        forget_mqtt_settings(&current);
        break;

    case PROVISION_EVENT_WIFI_CONNECTED:
        current.wifi_connected = true;
        break;

    case PROVISION_EVENT_WIFI_DISCONNECTED:
        current.wifi_connected = false;
        current.mqtt_connected = false;
        break;

    case PROVISION_EVENT_WIFI_TIMEOUT:
        current.wifi_connected = false;
        current.mqtt_connected = false;
        current.recovery_required = true;
        break;

    case PROVISION_EVENT_MQTT_CONNECTED:
        current.mqtt_connected = current.wifi_connected;
        if (current.mqtt_connected) {
            current.recovery_required = false;
            current.mqtt_settings_verified = true;
            current.mqtt_rejecting = false;
            current.mqtt_rejected_since_ms = 0;
        }
        break;

    case PROVISION_EVENT_MQTT_FAILED:
        current.mqtt_connected = false;
        if (!current.mqtt_settings_verified) {
            /* Settings that never connected may be a typo: let the user fix them. */
            current.recovery_required = true;
        } else if (current.wifi_connected) {
            /* Proven settings over working Wi-Fi: the broker side is down. Keep
             * retrying without the AP unless a refusal is already established. */
            current.recovery_required =
                mqtt_rejection_established(&current, now_ms);
        }
        break;

    case PROVISION_EVENT_MQTT_REJECTED:
        current.mqtt_connected = false;
        if (!current.mqtt_settings_verified) {
            current.recovery_required = true;
            break;
        }
        if (!current.mqtt_rejecting) {
            current.mqtt_rejecting = true;
            current.mqtt_rejected_since_ms = now_ms;
        }
        if (current.wifi_connected) {
            current.recovery_required =
                mqtt_rejection_established(&current, now_ms);
        }
        break;

    case PROVISION_EVENT_MQTT_SETTINGS_VERIFIED:
        current.mqtt_settings_verified = current.valid_config;
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

