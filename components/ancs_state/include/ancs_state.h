#pragma once

typedef enum {
    ANCS_STATE_BOOT = 0,
    ANCS_STATE_ADVERTISING,
    ANCS_STATE_CONNECTED,
    ANCS_STATE_ENCRYPTING,
    ANCS_STATE_BONDED,
    ANCS_STATE_DISCOVERING_ANCS,
    ANCS_STATE_SUBSCRIBING_DATA_SOURCE,
    ANCS_STATE_SUBSCRIBING_NOTIFICATION_SOURCE,
    ANCS_STATE_ANCS_READY,
    ANCS_STATE_DISCONNECTED,
    ANCS_STATE_RECOVERING,
} ancs_client_state_t;

typedef enum {
    ANCS_SIGNAL_BOOT_COMPLETE = 0,
    ANCS_SIGNAL_CONNECTED,
    ANCS_SIGNAL_ENCRYPTION_STARTED,
    ANCS_SIGNAL_BONDED,
    ANCS_SIGNAL_DISCOVERY_STARTED,
    ANCS_SIGNAL_DATA_SUBSCRIBE_STARTED,
    ANCS_SIGNAL_DATA_SUBSCRIBED,
    ANCS_SIGNAL_NOTIFICATION_SUBSCRIBED,
    ANCS_SIGNAL_SERVICE_CHANGED,
    ANCS_SIGNAL_DISCONNECTED,
    ANCS_SIGNAL_RECOVER,
} ancs_client_signal_t;

ancs_client_state_t ancs_client_state_after(ancs_client_state_t current,
                                            ancs_client_signal_t signal);
const char *ancs_client_state_name(ancs_client_state_t state);
