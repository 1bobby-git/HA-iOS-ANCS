#include "ancs_state.h"

#include <stddef.h>

ancs_client_state_t ancs_client_state_after(ancs_client_state_t current,
                                            ancs_client_signal_t signal)
{
    if (signal == ANCS_SIGNAL_DISCONNECTED) {
        return ANCS_STATE_DISCONNECTED;
    }
    if (signal == ANCS_SIGNAL_SERVICE_CHANGED) {
        return ANCS_STATE_RECOVERING;
    }

    switch (signal) {
    case ANCS_SIGNAL_BOOT_COMPLETE:
        return current == ANCS_STATE_BOOT ? ANCS_STATE_ADVERTISING : current;
    case ANCS_SIGNAL_CONNECTED:
        return current == ANCS_STATE_ADVERTISING ? ANCS_STATE_CONNECTED : current;
    case ANCS_SIGNAL_ENCRYPTION_STARTED:
        return current == ANCS_STATE_CONNECTED ? ANCS_STATE_ENCRYPTING : current;
    case ANCS_SIGNAL_BONDED:
        return current == ANCS_STATE_ENCRYPTING ? ANCS_STATE_BONDED : current;
    case ANCS_SIGNAL_DISCOVERY_STARTED:
        return (current == ANCS_STATE_BONDED || current == ANCS_STATE_RECOVERING)
                   ? ANCS_STATE_DISCOVERING_ANCS
                   : current;
    case ANCS_SIGNAL_DATA_SUBSCRIBE_STARTED:
        return current == ANCS_STATE_DISCOVERING_ANCS
                   ? ANCS_STATE_SUBSCRIBING_DATA_SOURCE
                   : current;
    case ANCS_SIGNAL_DATA_SUBSCRIBED:
        return current == ANCS_STATE_SUBSCRIBING_DATA_SOURCE
                   ? ANCS_STATE_SUBSCRIBING_NOTIFICATION_SOURCE
                   : current;
    case ANCS_SIGNAL_NOTIFICATION_SUBSCRIBED:
        return current == ANCS_STATE_SUBSCRIBING_NOTIFICATION_SOURCE
                   ? ANCS_STATE_ANCS_READY
                   : current;
    case ANCS_SIGNAL_RECOVER:
        return current == ANCS_STATE_DISCONNECTED ? ANCS_STATE_ADVERTISING : current;
    default:
        return current;
    }
}

const char *ancs_client_state_name(ancs_client_state_t state)
{
    static const char *const names[] = {
        "boot",
        "advertising",
        "connected",
        "encrypting",
        "bonded",
        "discovering_ancs",
        "subscribing_data_source",
        "subscribing_notification_source",
        "ancs_ready",
        "disconnected",
        "recovering",
    };
    return (unsigned int)state < (sizeof(names) / sizeof(names[0]))
               ? names[state]
               : "unknown";
}
