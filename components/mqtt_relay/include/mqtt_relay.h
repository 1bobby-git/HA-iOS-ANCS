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
#define MQTT_RELAY_RETAINED_QOS 0
#define MQTT_RELAY_RETAINED_RETAIN true
#define MQTT_RELAY_DISCOVERY_QOS 0
#define MQTT_RELAY_ENROLL_COMMAND_QOS 1
#define MQTT_RELAY_RESTART_COMMAND_QOS 1

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

typedef struct {
    char manufacturer[32];
    char model[24];
    char sw_version[32];
    char hw_version[24];
} mqtt_relay_device_info_t;

typedef struct {
    bool connected;
    char ssid[PROVISION_WIFI_SSID_MAX + 1];
    char ip[16];
    int32_t rssi;
} mqtt_relay_wifi_status_t;

typedef struct {
    mqtt_relay_wifi_status_t wifi;
    bool mqtt_connected;
    bool ble_connected;
    bool ble_bonded;
    uint64_t uptime_seconds;
} mqtt_relay_runtime_status_t;

typedef enum {
    MQTT_RELAY_EVENT_CONNECTED = 0,
    MQTT_RELAY_EVENT_DISCONNECTED,
    MQTT_RELAY_EVENT_FAILED,
    MQTT_RELAY_EVENT_ENROLL_REQUEST,
    MQTT_RELAY_EVENT_RESTART_REQUEST,
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
                                             const mqtt_relay_device_info_t *device_info,
                                             const char *notification_topic,
                                             const char *availability_topic,
                                             char *out,
                                             size_t out_size);
esp_err_t mqtt_relay_build_enroll_command_topic(
    const provision_config_t *config,
    char *out,
    size_t out_size);
esp_err_t mqtt_relay_build_enroll_discovery_topic(
    const provision_config_t *config,
    char *out,
    size_t out_size);
esp_err_t mqtt_relay_build_enroll_discovery_payload(
    const provision_config_t *config,
    const mqtt_relay_device_info_t *device_info,
    const char *command_topic,
    const char *availability_topic,
    char *out,
    size_t out_size);
bool mqtt_relay_is_enroll_command(const char *expected_topic,
                                  const char *topic,
                                  size_t topic_len,
                                  const char *payload,
                                  size_t payload_len,
                                  size_t total_payload_len,
                                  size_t current_data_offset,
                                  bool retained);
esp_err_t mqtt_relay_build_restart_command_topic(
    const provision_config_t *config,
    char *out,
    size_t out_size);
esp_err_t mqtt_relay_build_restart_discovery_topic(
    const provision_config_t *config,
    char *out,
    size_t out_size);
esp_err_t mqtt_relay_build_restart_discovery_payload(
    const provision_config_t *config,
    const mqtt_relay_device_info_t *device_info,
    const char *command_topic,
    const char *availability_topic,
    char *out,
    size_t out_size);
bool mqtt_relay_is_restart_command(const char *expected_topic,
                                   const char *topic,
                                   size_t topic_len,
                                   const char *payload,
                                   size_t payload_len,
                                   size_t total_payload_len,
                                   size_t current_data_offset,
                                   bool retained);
size_t mqtt_relay_focused_sensor_count(void);
const char *mqtt_relay_focused_sensor_key(size_t field_index);
esp_err_t mqtt_relay_build_focused_discovery_topic(
    const provision_config_t *config,
    size_t field_index,
    char *out,
    size_t out_size);
esp_err_t mqtt_relay_build_focused_discovery_payload(
    const provision_config_t *config,
    const mqtt_relay_device_info_t *device_info,
    const char *notification_topic,
    const char *availability_topic,
    size_t field_index,
    char *out,
    size_t out_size);
size_t mqtt_relay_legacy_discovery_count(void);
const char *mqtt_relay_legacy_discovery_key(size_t field_index);
esp_err_t mqtt_relay_build_legacy_discovery_topic(
    const provision_config_t *config,
    size_t field_index,
    char *out,
    size_t out_size);
esp_err_t mqtt_relay_build_status_discovery_topic(
    const provision_config_t *config,
    char *out,
    size_t out_size);
esp_err_t mqtt_relay_build_status_discovery_payload(
    const provision_config_t *config,
    const mqtt_relay_device_info_t *device_info,
    const char *state_topic,
    const char *availability_topic,
    char *out,
    size_t out_size);
esp_err_t mqtt_relay_build_state_payload(const mqtt_relay_counters_t *counters,
                                         const mqtt_relay_runtime_status_t *runtime,
                                         const mqtt_relay_device_info_t *device_info,
                                         char *out,
                                         size_t out_size);

esp_err_t mqtt_relay_init(const provision_config_t *config,
                          const mqtt_relay_device_info_t *device_info);
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
esp_err_t mqtt_relay_update_wifi_status(const mqtt_relay_wifi_status_t *status);
esp_err_t mqtt_relay_update_ble_status(bool connected, bool bonded);
esp_err_t mqtt_relay_refresh_state(void);
void mqtt_relay_set_wifi_connected(bool connected);
void mqtt_relay_observe_notification(const ancs_notification_t *notification,
                                     const char *device_name,
                                     void *context);
void mqtt_relay_get_counters(mqtt_relay_counters_t *out);

#ifdef __cplusplus
}
#endif
