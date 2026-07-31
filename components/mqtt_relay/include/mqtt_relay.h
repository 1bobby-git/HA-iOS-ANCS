#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ancs_protocol.h"
#include "esp_err.h"
#include "mqtt_client.h"
#include "provision_store.h"

#ifdef __cplusplus
extern "C" {
#endif

#define MQTT_RELAY_QUEUE_CAPACITY 8
#define MQTT_RELAY_TOPIC_MAX (PROVISION_MQTT_BASE_TOPIC_MAX + 32)
#define MQTT_RELAY_DISCOVERY_TOPIC_MAX (PROVISION_MQTT_CLIENT_ID_MAX + 64)
#define MQTT_RELAY_NOTIFICATION_QOS 1
#define MQTT_RELAY_NOTIFICATION_RETAIN false
#define MQTT_RELAY_RETAINED_QOS 1
#define MQTT_RELAY_RETAINED_RETAIN true

typedef struct mqtt_payload_item_t {
    char *topic;
    char *payload;
    size_t payload_length;
    int msg_id;
    struct mqtt_payload_item_t *next;
} mqtt_payload_item_t;

typedef struct {
    uint32_t accepted;
    uint32_t published_ack;
    uint32_t dropped_offline;
    uint32_t dropped_enqueue;
    uint32_t dropped_policy;
    uint32_t freed;
} mqtt_relay_counters_t;

typedef enum {
    MQTT_RELAY_EVENT_CONNECTED = 0,
    MQTT_RELAY_EVENT_DISCONNECTED,
    MQTT_RELAY_EVENT_FAILED,
} mqtt_relay_event_t;

typedef void (*mqtt_relay_event_callback_t)(mqtt_relay_event_t event,
                                            void *context);

esp_err_t mqtt_payload_build_notification(const ancs_notification_t *notification,
                                          const char *device_name,
                                          const char *relay_id,
                                          uint64_t uptime_ms,
                                          char **out_payload,
                                          size_t *out_length);

esp_err_t mqtt_relay_build_topics(const provision_config_t *config,
                                  char *notification_topic,
                                  size_t notification_topic_size,
                                  char *availability_topic,
                                  size_t availability_topic_size,
                                  char *state_topic,
                                  size_t state_topic_size,
                                  char *discovery_topic,
                                  size_t discovery_topic_size);
esp_err_t mqtt_relay_build_client_config(const provision_config_t *config,
                                         const char *availability_topic,
                                         esp_mqtt_client_config_t *out);
esp_err_t mqtt_relay_build_discovery_payload(const provision_config_t *config,
                                             const char *notification_topic,
                                             const char *availability_topic,
                                             char *out,
                                             size_t out_size);
size_t mqtt_relay_discovery_field_count(void);
const char *mqtt_relay_discovery_field_key(size_t field_index);
esp_err_t mqtt_relay_build_field_discovery_topic(
    const provision_config_t *config,
    size_t field_index,
    char *out,
    size_t out_size);
esp_err_t mqtt_relay_build_field_discovery_payload(
    const provision_config_t *config,
    const char *notification_topic,
    const char *availability_topic,
    size_t field_index,
    char *out,
    size_t out_size);
esp_err_t mqtt_relay_build_state_payload(const mqtt_relay_counters_t *counters,
                                         bool connected,
                                         char *out,
                                         size_t out_size);

esp_err_t mqtt_relay_init(const provision_config_t *config);
esp_err_t mqtt_relay_start(void);
esp_err_t mqtt_relay_reconnect(void);
esp_err_t mqtt_relay_stop(void);
/*
 * If reconfigure fails after the old client is torn down, the relay is left
 * explicitly offline, not accepting observers, with no active MQTT client.
 * Call mqtt_relay_deinit()/mqtt_relay_init() to recover from that terminal
 * state.
 */
esp_err_t mqtt_relay_reconfigure(const provision_config_t *config);
esp_err_t mqtt_relay_deinit(void);
esp_err_t mqtt_relay_register_event_callback(mqtt_relay_event_callback_t callback,
                                             void *context);
void mqtt_relay_set_wifi_connected(bool connected);
void mqtt_relay_observe_notification(const ancs_notification_t *notification,
                                     const char *device_name,
                                     void *context);
void mqtt_relay_get_counters(mqtt_relay_counters_t *out);

#ifdef __cplusplus
}
#endif
