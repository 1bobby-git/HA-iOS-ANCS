#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ancs_protocol.h"
#include "esp_err.h"

#define RELAY_POLICY_RECENT_CAPACITY 8
#define RELAY_POLICY_ID_MAX 33

typedef enum {
    RELAY_PUBLISH = 0,
    RELAY_DROP_PRE_EXISTING,
    RELAY_DROP_OFFLINE,
    RELAY_DROP_ECHO,
    RELAY_DROP_DUPLICATE,
    RELAY_DROP_INCOMPLETE,
    RELAY_DROP_INVALID,
    RELAY_DROP_EVENT,
} relay_decision_t;

typedef struct {
    bool wifi_connected;
    bool mqtt_connected;
    uint32_t boot_nonce;
} relay_connectivity_t;

typedef struct {
    char relay_ids[RELAY_POLICY_RECENT_CAPACITY][RELAY_POLICY_ID_MAX];
    size_t next_index;
    size_t count;
} relay_recent_cache_t;

typedef struct {
    uint32_t published;
    uint32_t drop_pre_existing;
    uint32_t drop_offline;
    uint32_t drop_echo;
    uint32_t drop_duplicate;
    uint32_t drop_incomplete;
    uint32_t drop_invalid;
    uint32_t drop_event;
} relay_policy_counters_t;

relay_decision_t relay_policy_decide(const ancs_notification_t *notification,
                                     relay_connectivity_t connectivity,
                                     relay_recent_cache_t *cache);
esp_err_t relay_policy_build_id(const ancs_notification_t *notification,
                                uint32_t boot_nonce,
                                char *out,
                                size_t out_size);
void relay_policy_recent_cache_init(relay_recent_cache_t *cache);
void relay_policy_mark_recent(relay_recent_cache_t *cache, const char *relay_id);
void relay_policy_counters_init(relay_policy_counters_t *counters);
void relay_policy_counters_record(relay_policy_counters_t *counters,
                                  relay_decision_t decision);
const char *relay_policy_decision_name(relay_decision_t decision);
