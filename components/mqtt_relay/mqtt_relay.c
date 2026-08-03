#include "mqtt_relay.h"

#include <ctype.h>
#include <inttypes.h>
#include <stdlib.h>
#include <string.h>

#include "esp_event.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "mqtt_relay_test.h"
#include "relay_policy.h"

#define MQTT_RELAY_WORKER_STACK 4096
#define MQTT_RELAY_WORKER_PRIORITY 5
#define MQTT_RELAY_DISCOVERY_PAYLOAD_MAX 1536

static const char MQTT_RELAY_ENROLL_PAYLOAD[] = "ENROLL";

typedef struct {
    provision_config_t config;
    mqtt_relay_device_info_t device_info;
    mqtt_relay_wifi_status_t wifi_status;
    esp_mqtt_client_handle_t client;
    QueueHandle_t queue;
    SemaphoreHandle_t lock;
    SemaphoreHandle_t lifecycle_lock;
    TaskHandle_t worker_task;
    bool worker_running;
    bool worker_busy;
    bool accepting_observers;
    bool publish_allowed;
    uint32_t publish_in_flight;
    bool wifi_connected;
    bool mqtt_connected;
    mqtt_relay_event_callback_t event_callback;
    void *event_context;
    uint32_t boot_nonce;
    relay_recent_cache_t recent;
    mqtt_relay_counters_t counters;
    mqtt_payload_item_t *pending;
    char notification_topic[MQTT_RELAY_TOPIC_MAX];
    char availability_topic[MQTT_RELAY_TOPIC_MAX];
    char state_topic[MQTT_RELAY_TOPIC_MAX];
    char discovery_topic[MQTT_RELAY_DISCOVERY_TOPIC_MAX];
    char enroll_command_topic[MQTT_RELAY_TOPIC_MAX];
    char enroll_discovery_topic[MQTT_RELAY_DISCOVERY_TOPIC_MAX];
} mqtt_relay_context_t;

typedef struct {
    const char *key;
    const char *name;
    const char *value_template;
} mqtt_relay_discovery_field_t;

typedef struct {
    const char *key;
    const char *name;
    const char *value_template;
    const char *device_class;
    const char *state_class;
    const char *unit_of_measurement;
} mqtt_relay_wifi_discovery_field_t;

static const mqtt_relay_discovery_field_t s_discovery_fields[] = {
    {.key = "schema_version",
     .name = "Schema version",
     .value_template = "{{ value_json.schema_version }}"},
    {.key = "target", .name = "Target", .value_template = "{{ value_json.target }}"},
    {.key = "device_name",
     .name = "Device name",
     .value_template = "{{ value_json.device_name }}"},
    {.key = "session_id",
     .name = "Session ID",
     .value_template = "{{ value_json.session_id }}"},
    {.key = "event", .name = "Event", .value_template = "{{ value_json.event }}"},
    {.key = "event_id",
     .name = "Event ID",
     .value_template = "{{ value_json.event_id }}"},
    {.key = "uid", .name = "UID", .value_template = "{{ value_json.uid }}"},
    {.key = "event_flags",
     .name = "Event flags",
     .value_template = "{{ value_json.event_flags }}"},
    {.key = "silent", .name = "Silent", .value_template = "{{ value_json.silent }}"},
    {.key = "important",
     .name = "Important",
     .value_template = "{{ value_json.important }}"},
    {.key = "pre_existing",
     .name = "Pre-existing",
     .value_template = "{{ value_json.pre_existing }}"},
    {.key = "positive_action_available",
     .name = "Positive action available",
     .value_template = "{{ value_json.positive_action_available }}"},
    {.key = "negative_action_available",
     .name = "Negative action available",
     .value_template = "{{ value_json.negative_action_available }}"},
    {.key = "category_id",
     .name = "Category ID",
     .value_template = "{{ value_json.category_id }}"},
    {.key = "category",
     .name = "Category",
     .value_template = "{{ value_json.category }}"},
    {.key = "category_count",
     .name = "Category count",
     .value_template = "{{ value_json.category_count }}"},
    {.key = "app_id",
     .name = "App ID",
     .value_template = "{{ (value_json.app_id | default('', true))[:255] }}"},
    {.key = "title",
     .name = "Title",
     .value_template = "{{ (value_json.title | default('', true))[:255] }}"},
    {.key = "subtitle",
     .name = "Subtitle",
     .value_template = "{{ (value_json.subtitle | default('', true))[:255] }}"},
    {.key = "message",
     .name = "Message",
     .value_template = "{{ (value_json.message | default('', true))[:255] }}"},
    {.key = "message_size",
     .name = "Message size",
     .value_template = "{{ value_json.message_size }}"},
    {.key = "date", .name = "Date", .value_template = "{{ value_json.date }}"},
    {.key = "complete",
     .name = "Complete",
     .value_template = "{{ value_json.complete }}"},
    {.key = "truncated",
     .name = "Truncated fields",
     .value_template = "{{ value_json.truncated | to_json }}"},
    {.key = "error",
     .name = "Error",
     .value_template = "{{ value_json.error | to_json }}"},
    {.key = "received_at_ms",
     .name = "Received at ms",
     .value_template = "{{ value_json.received_at_ms }}"},
    {.key = "relay_id",
     .name = "Relay ID",
     .value_template = "{{ value_json.relay_id }}"},
    {.key = "source", .name = "Source", .value_template = "{{ value_json.source }}"},
    {.key = "published_at_ms",
     .name = "Published at ms",
     .value_template = "{{ value_json.published_at_ms }}"},
    {.key = "truncated_app_id",
     .name = "App ID truncated",
     .value_template = "{{ value_json.truncated.app_id | default(false) }}"},
    {.key = "truncated_title",
     .name = "Title truncated",
     .value_template = "{{ value_json.truncated.title | default(false) }}"},
    {.key = "truncated_subtitle",
     .name = "Subtitle truncated",
     .value_template = "{{ value_json.truncated.subtitle | default(false) }}"},
    {.key = "truncated_message",
     .name = "Message truncated",
     .value_template = "{{ value_json.truncated.message | default(false) }}"},
};

static const mqtt_relay_wifi_discovery_field_t s_wifi_discovery_fields[] = {
    {.key = "wifi_ssid",
     .name = "Wi-Fi SSID",
     .value_template = "{{ value_json.wifi_ssid }}"},
    {.key = "wifi_ip",
     .name = "Wi-Fi IP",
     .value_template = "{{ value_json.wifi_ip }}"},
    {.key = "wifi_rssi",
     .name = "Wi-Fi RSSI",
     .value_template = "{{ value_json.wifi_rssi }}",
     .device_class = "signal_strength",
     .state_class = "measurement",
     .unit_of_measurement = "dBm"},
};

static mqtt_relay_context_t s_ctx;
static mqtt_relay_publish_for_test_t s_publish_for_test;

static void mqtt_relay_lock(void);
static void mqtt_relay_unlock(void);
static void mqtt_relay_lifecycle_lock(void);
static void mqtt_relay_lifecycle_unlock(void);

static void mqtt_relay_emit_event(mqtt_relay_event_t event)
{
    mqtt_relay_event_callback_t callback = NULL;
    void *context = NULL;
    mqtt_relay_lock();
    callback = s_ctx.event_callback;
    context = s_ctx.event_context;
    mqtt_relay_unlock();
    if (callback != NULL) {
        callback(event, context);
    }
}

static bool topic_has_publish_wildcard(const char *topic)
{
    return topic == NULL || strchr(topic, '+') != NULL || strchr(topic, '#') != NULL;
}

static bool discovery_id_is_safe(const char *id)
{
    if (id == NULL || id[0] == '\0') {
        return false;
    }
    for (const unsigned char *cursor = (const unsigned char *)id; *cursor != '\0';
         ++cursor) {
        if (!isalnum(*cursor) && *cursor != '_' && *cursor != '-') {
            return false;
        }
    }
    return true;
}

static esp_err_t json_write_string(char **cursor,
                                   size_t *remaining,
                                   const char *value)
{
    if (cursor == NULL || *cursor == NULL || remaining == NULL || *remaining == 0U) {
        return ESP_ERR_INVALID_ARG;
    }
    const char *text = value != NULL ? value : "";
    int written = snprintf(*cursor, *remaining, "\"");
    if (written < 0 || (size_t)written >= *remaining) {
        return ESP_ERR_INVALID_SIZE;
    }
    *cursor += written;
    *remaining -= (size_t)written;

    for (const unsigned char *p = (const unsigned char *)text; *p != '\0'; ++p) {
        const char *escaped = NULL;
        char control[7];
        switch (*p) {
        case '"':
            escaped = "\\\"";
            break;
        case '\\':
            escaped = "\\\\";
            break;
        case '\b':
            escaped = "\\b";
            break;
        case '\f':
            escaped = "\\f";
            break;
        case '\n':
            escaped = "\\n";
            break;
        case '\r':
            escaped = "\\r";
            break;
        case '\t':
            escaped = "\\t";
            break;
        default:
            if (*p < 0x20U) {
                (void)snprintf(control, sizeof(control), "\\u%04x", *p);
                escaped = control;
            }
            break;
        }
        if (escaped != NULL) {
            written = snprintf(*cursor, *remaining, "%s", escaped);
        } else {
            written = snprintf(*cursor, *remaining, "%c", *p);
        }
        if (written < 0 || (size_t)written >= *remaining) {
            return ESP_ERR_INVALID_SIZE;
        }
        *cursor += written;
        *remaining -= (size_t)written;
    }

    written = snprintf(*cursor, *remaining, "\"");
    if (written < 0 || (size_t)written >= *remaining) {
        return ESP_ERR_INVALID_SIZE;
    }
    *cursor += written;
    *remaining -= (size_t)written;
    return ESP_OK;
}

static esp_err_t json_write_literal(char **cursor,
                                    size_t *remaining,
                                    const char *literal)
{
    if (cursor == NULL || *cursor == NULL || remaining == NULL ||
        *remaining == 0U || literal == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    const int written = snprintf(*cursor, *remaining, "%s", literal);
    if (written < 0 || (size_t)written >= *remaining) {
        return ESP_ERR_INVALID_SIZE;
    }
    *cursor += written;
    *remaining -= (size_t)written;
    return ESP_OK;
}

static bool bounded_required_text(const char *value, size_t capacity)
{
    return value != NULL && value[0] != '\0' && strnlen(value, capacity) < capacity;
}

static bool device_info_is_valid(const mqtt_relay_device_info_t *device_info)
{
    return device_info != NULL &&
           bounded_required_text(device_info->manufacturer,
                                 sizeof(device_info->manufacturer)) &&
           bounded_required_text(device_info->model, sizeof(device_info->model)) &&
           bounded_required_text(device_info->sw_version,
                                 sizeof(device_info->sw_version)) &&
           bounded_required_text(device_info->hw_version,
                                 sizeof(device_info->hw_version));
}

static esp_err_t append_device_json(char **cursor,
                                    size_t *remaining,
                                    const provision_config_t *config,
                                    const mqtt_relay_device_info_t *device_info)
{
    if (config == NULL || !discovery_id_is_safe(config->mqtt_client_id) ||
        !device_info_is_valid(device_info)) {
        return ESP_ERR_INVALID_ARG;
    }

    esp_err_t err = json_write_literal(
        cursor, remaining, ",\"device\":{\"identifiers\":[");
    if (err == ESP_OK) {
        err = json_write_string(cursor, remaining, config->mqtt_client_id);
    }
    if (err == ESP_OK) {
        err = json_write_literal(cursor, remaining, "],\"name\":");
    }
    if (err == ESP_OK) {
        err = json_write_string(cursor, remaining, config->mqtt_client_id);
    }
    if (err == ESP_OK) {
        err = json_write_literal(cursor, remaining, ",\"manufacturer\":");
    }
    if (err == ESP_OK) {
        err = json_write_string(cursor, remaining, device_info->manufacturer);
    }
    if (err == ESP_OK) {
        err = json_write_literal(cursor, remaining, ",\"model\":");
    }
    if (err == ESP_OK) {
        err = json_write_string(cursor, remaining, device_info->model);
    }
    if (err == ESP_OK) {
        err = json_write_literal(cursor, remaining, ",\"sw_version\":");
    }
    if (err == ESP_OK) {
        err = json_write_string(cursor, remaining, device_info->sw_version);
    }
    if (err == ESP_OK) {
        err = json_write_literal(cursor, remaining, ",\"hw_version\":");
    }
    if (err == ESP_OK) {
        err = json_write_string(cursor, remaining, device_info->hw_version);
    }
    if (err == ESP_OK) {
        err = json_write_literal(cursor, remaining, "}");
    }
    return err;
}

static esp_err_t append_topic(const char *base,
                              const char *suffix,
                              char *out,
                              size_t out_size)
{
    if (base == NULL || suffix == NULL || out == NULL || out_size == 0U ||
        base[0] == '\0' || topic_has_publish_wildcard(base)) {
        return ESP_ERR_INVALID_ARG;
    }
    const int written = snprintf(out, out_size, "%s/%s", base, suffix);
    return (written < 0 || (size_t)written >= out_size) ? ESP_ERR_INVALID_SIZE
                                                        : ESP_OK;
}

esp_err_t mqtt_relay_build_topics(const provision_config_t *config,
                                  char *notification_topic,
                                  size_t notification_topic_size,
                                  char *availability_topic,
                                  size_t availability_topic_size,
                                  char *state_topic,
                                  size_t state_topic_size,
                                  char *discovery_topic,
                                  size_t discovery_topic_size)
{
    if (config == NULL || notification_topic == NULL || availability_topic == NULL ||
        state_topic == NULL || discovery_topic == NULL ||
        !discovery_id_is_safe(config->mqtt_client_id)) {
        return ESP_ERR_INVALID_ARG;
    }
    esp_err_t err = append_topic(config->mqtt_base_topic,
                                 "notification",
                                 notification_topic,
                                 notification_topic_size);
    if (err != ESP_OK) {
        return err;
    }
    err = append_topic(config->mqtt_base_topic,
                       "availability",
                       availability_topic,
                       availability_topic_size);
    if (err != ESP_OK) {
        return err;
    }
    err = append_topic(config->mqtt_base_topic, "state", state_topic, state_topic_size);
    if (err != ESP_OK) {
        return err;
    }
    const int written = snprintf(discovery_topic,
                                 discovery_topic_size,
                                 "homeassistant/sensor/%s/last_notification/config",
                                 config->mqtt_client_id);
    return (written < 0 || (size_t)written >= discovery_topic_size)
               ? ESP_ERR_INVALID_SIZE
               : ESP_OK;
}

esp_err_t mqtt_relay_build_enroll_command_topic(
    const provision_config_t *config,
    char *out,
    size_t out_size)
{
    if (config == NULL || out == NULL || out_size == 0U) {
        return ESP_ERR_INVALID_ARG;
    }
    return append_topic(config->mqtt_base_topic, "command/enroll", out, out_size);
}

esp_err_t mqtt_relay_build_enroll_discovery_topic(
    const provision_config_t *config,
    char *out,
    size_t out_size)
{
    if (config == NULL || out == NULL || out_size == 0U ||
        !discovery_id_is_safe(config->mqtt_client_id)) {
        return ESP_ERR_INVALID_ARG;
    }
    const int written = snprintf(out,
                                 out_size,
                                 "homeassistant/button/%s/enroll/config",
                                 config->mqtt_client_id);
    return (written < 0 || (size_t)written >= out_size) ? ESP_ERR_INVALID_SIZE
                                                        : ESP_OK;
}

esp_err_t mqtt_relay_build_enroll_discovery_payload(
    const provision_config_t *config,
    const mqtt_relay_device_info_t *device_info,
    const char *command_topic,
    const char *availability_topic,
    char *out,
    size_t out_size)
{
    if (config == NULL || command_topic == NULL || availability_topic == NULL ||
        out == NULL || out_size == 0U ||
        !discovery_id_is_safe(config->mqtt_client_id) ||
        !device_info_is_valid(device_info) ||
        topic_has_publish_wildcard(command_topic) ||
        topic_has_publish_wildcard(availability_topic)) {
        return ESP_ERR_INVALID_ARG;
    }

    char unique_id[PROVISION_MQTT_CLIENT_ID_MAX + 16];
    char default_entity_id[PROVISION_MQTT_CLIENT_ID_MAX + 24];
    int id_written = snprintf(unique_id,
                              sizeof(unique_id),
                              "%s_enroll",
                              config->mqtt_client_id);
    if (id_written < 0 || (size_t)id_written >= sizeof(unique_id)) {
        return ESP_ERR_INVALID_SIZE;
    }
    id_written = snprintf(default_entity_id,
                          sizeof(default_entity_id),
                          "button.%s",
                          unique_id);
    if (id_written < 0 || (size_t)id_written >= sizeof(default_entity_id)) {
        return ESP_ERR_INVALID_SIZE;
    }

    char *cursor = out;
    size_t remaining = out_size;
#define APPEND_ENROLL_LITERAL(text)                                             \
    do {                                                                        \
        const int literal_written = snprintf(cursor, remaining, "%s", (text)); \
        if (literal_written < 0 || (size_t)literal_written >= remaining) {       \
            return ESP_ERR_INVALID_SIZE;                                        \
        }                                                                       \
        cursor += literal_written;                                              \
        remaining -= (size_t)literal_written;                                   \
    } while (0)

    APPEND_ENROLL_LITERAL("{\"name\":");
    esp_err_t err = json_write_string(&cursor, &remaining, "iPhone 등록 시작");
    if (err != ESP_OK) {
        return err;
    }
    APPEND_ENROLL_LITERAL(",\"unique_id\":");
    err = json_write_string(&cursor, &remaining, unique_id);
    if (err != ESP_OK) {
        return err;
    }
    APPEND_ENROLL_LITERAL(",\"default_entity_id\":");
    err = json_write_string(&cursor, &remaining, default_entity_id);
    if (err != ESP_OK) {
        return err;
    }
    APPEND_ENROLL_LITERAL(",\"command_topic\":");
    err = json_write_string(&cursor, &remaining, command_topic);
    if (err != ESP_OK) {
        return err;
    }
    APPEND_ENROLL_LITERAL(",\"payload_press\":\"ENROLL\",\"availability_topic\":");
    err = json_write_string(&cursor, &remaining, availability_topic);
    if (err != ESP_OK) {
        return err;
    }
    APPEND_ENROLL_LITERAL(
        ",\"payload_available\":\"online\",\"payload_not_available\":\"offline\""
        ",\"qos\":1,\"retain\":false,\"entity_category\":\"config\""
        ",\"icon\":\"mdi:bluetooth-connect\"");
    err = append_device_json(&cursor, &remaining, config, device_info);
    if (err != ESP_OK) {
        return err;
    }
    APPEND_ENROLL_LITERAL("}");
#undef APPEND_ENROLL_LITERAL
    return ESP_OK;
}

bool mqtt_relay_is_enroll_command(const char *expected_topic,
                                  const char *topic,
                                  size_t topic_len,
                                  const char *payload,
                                  size_t payload_len,
                                  size_t total_payload_len,
                                  size_t current_data_offset,
                                  bool retained)
{
    if (expected_topic == NULL || topic == NULL || payload == NULL || retained ||
        current_data_offset != 0U || payload_len != total_payload_len ||
        payload_len != sizeof(MQTT_RELAY_ENROLL_PAYLOAD) - 1U) {
        return false;
    }
    const size_t expected_topic_len = strlen(expected_topic);
    return topic_len == expected_topic_len &&
           memcmp(topic, expected_topic, topic_len) == 0 &&
           memcmp(payload, MQTT_RELAY_ENROLL_PAYLOAD, payload_len) == 0;
}

esp_err_t mqtt_relay_build_client_config(const provision_config_t *config,
                                         const char *availability_topic,
                                         esp_mqtt_client_config_t *out)
{
    if (config == NULL || availability_topic == NULL || out == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    const provision_config_result_t validation = provision_config_validate(config);
    if (validation == PROVISION_CONFIG_TLS_CA_REQUIRED) {
        return ESP_ERR_INVALID_ARG;
    }
    if (validation != PROVISION_CONFIG_OK || topic_has_publish_wildcard(availability_topic)) {
        return ESP_ERR_INVALID_ARG;
    }

    const esp_mqtt_client_config_t mqtt_config = {
        .broker.address.hostname = config->mqtt_host,
        .broker.address.port = config->mqtt_port,
        .broker.address.transport =
            config->mqtt_tls ? MQTT_TRANSPORT_OVER_SSL : MQTT_TRANSPORT_OVER_TCP,
        .credentials.username = config->mqtt_username,
        .credentials.authentication.password = config->mqtt_password,
        .credentials.client_id = config->mqtt_client_id,
        .broker.verification.certificate = config->mqtt_tls ? config->mqtt_ca : NULL,
        .network.disable_auto_reconnect = true,
        .session.last_will.topic = availability_topic,
        .session.last_will.msg = "offline",
        .session.last_will.qos = 1,
        .session.last_will.retain = true,
    };
    *out = mqtt_config;
    return ESP_OK;
}

esp_err_t mqtt_relay_build_discovery_payload(const provision_config_t *config,
                                             const mqtt_relay_device_info_t *device_info,
                                             const char *notification_topic,
                                             const char *availability_topic,
                                             char *out,
                                             size_t out_size)
{
    if (config == NULL || notification_topic == NULL || availability_topic == NULL ||
        out == NULL || out_size == 0U ||
        !discovery_id_is_safe(config->mqtt_client_id) ||
        !device_info_is_valid(device_info) ||
        topic_has_publish_wildcard(notification_topic) ||
        topic_has_publish_wildcard(availability_topic)) {
        return ESP_ERR_INVALID_ARG;
    }

    char object_name[PROVISION_MQTT_CLIENT_ID_MAX + 32];
    char unique_id[PROVISION_MQTT_CLIENT_ID_MAX + 32];
    int id_written = snprintf(object_name,
                              sizeof(object_name),
                              "%s last notification",
                              config->mqtt_client_id);
    if (id_written < 0 || (size_t)id_written >= sizeof(object_name)) {
        return ESP_ERR_INVALID_SIZE;
    }
    id_written = snprintf(unique_id,
                          sizeof(unique_id),
                          "%s_last_notification",
                          config->mqtt_client_id);
    if (id_written < 0 || (size_t)id_written >= sizeof(unique_id)) {
        return ESP_ERR_INVALID_SIZE;
    }

    char *cursor = out;
    size_t remaining = out_size;
    int written = snprintf(cursor, remaining, "{\"name\":");
    if (written < 0 || (size_t)written >= remaining) {
        return ESP_ERR_INVALID_SIZE;
    }
    cursor += written;
    remaining -= (size_t)written;
    esp_err_t err = json_write_string(&cursor, &remaining, object_name);
    if (err != ESP_OK) {
        return err;
    }
    written = snprintf(cursor, remaining, ",\"unique_id\":");
    if (written < 0 || (size_t)written >= remaining) {
        return ESP_ERR_INVALID_SIZE;
    }
    cursor += written;
    remaining -= (size_t)written;
    err = json_write_string(&cursor, &remaining, unique_id);
    if (err != ESP_OK) {
        return err;
    }
    written = snprintf(cursor, remaining, ",\"object_id\":");
    if (written < 0 || (size_t)written >= remaining) {
        return ESP_ERR_INVALID_SIZE;
    }
    cursor += written;
    remaining -= (size_t)written;
    err = json_write_string(&cursor, &remaining, unique_id);
    if (err != ESP_OK) {
        return err;
    }
    written = snprintf(cursor, remaining, ",\"state_topic\":");
    if (written < 0 || (size_t)written >= remaining) {
        return ESP_ERR_INVALID_SIZE;
    }
    cursor += written;
    remaining -= (size_t)written;
    err = json_write_string(&cursor, &remaining, notification_topic);
    if (err != ESP_OK) {
        return err;
    }
    written = snprintf(cursor,
                       remaining,
                       ",\"value_template\":\"{{ value_json.relay_id }}\""
                       ",\"json_attributes_topic\":");
    if (written < 0 || (size_t)written >= remaining) {
        return ESP_ERR_INVALID_SIZE;
    }
    cursor += written;
    remaining -= (size_t)written;
    err = json_write_string(&cursor, &remaining, notification_topic);
    if (err != ESP_OK) {
        return err;
    }
    written = snprintf(cursor, remaining, ",\"availability_topic\":");
    if (written < 0 || (size_t)written >= remaining) {
        return ESP_ERR_INVALID_SIZE;
    }
    cursor += written;
    remaining -= (size_t)written;
    err = json_write_string(&cursor, &remaining, availability_topic);
    if (err != ESP_OK) {
        return err;
    }
    written = snprintf(cursor,
                       remaining,
                       ",\"payload_available\":\"online\",\"payload_not_available\":\"offline\"");
    if (written < 0 || (size_t)written >= remaining) {
        return ESP_ERR_INVALID_SIZE;
    }
    cursor += written;
    remaining -= (size_t)written;
    err = append_device_json(&cursor, &remaining, config, device_info);
    if (err != ESP_OK) {
        return err;
    }
    written = snprintf(cursor, remaining, "}");
    return (written < 0 || (size_t)written >= remaining) ? ESP_ERR_INVALID_SIZE
                                                         : ESP_OK;
}

size_t mqtt_relay_discovery_field_count(void)
{
    return sizeof(s_discovery_fields) / sizeof(s_discovery_fields[0]);
}

const char *mqtt_relay_discovery_field_key(size_t field_index)
{
    if (field_index >= mqtt_relay_discovery_field_count()) {
        return NULL;
    }
    return s_discovery_fields[field_index].key;
}

esp_err_t mqtt_relay_build_field_discovery_topic(
    const provision_config_t *config,
    size_t field_index,
    char *out,
    size_t out_size)
{
    if (config == NULL || out == NULL || out_size == 0U ||
        field_index >= mqtt_relay_discovery_field_count() ||
        !discovery_id_is_safe(config->mqtt_client_id)) {
        return ESP_ERR_INVALID_ARG;
    }
    const int written = snprintf(out,
                                 out_size,
                                 "homeassistant/sensor/%s/%s/config",
                                 config->mqtt_client_id,
                                 s_discovery_fields[field_index].key);
    return (written < 0 || (size_t)written >= out_size) ? ESP_ERR_INVALID_SIZE
                                                        : ESP_OK;
}

esp_err_t mqtt_relay_build_field_discovery_payload(
    const provision_config_t *config,
    const mqtt_relay_device_info_t *device_info,
    const char *notification_topic,
    const char *availability_topic,
    size_t field_index,
    char *out,
    size_t out_size)
{
    if (config == NULL || notification_topic == NULL || availability_topic == NULL ||
        out == NULL || out_size == 0U ||
        field_index >= mqtt_relay_discovery_field_count() ||
        !discovery_id_is_safe(config->mqtt_client_id) ||
        !device_info_is_valid(device_info) ||
        topic_has_publish_wildcard(notification_topic) ||
        topic_has_publish_wildcard(availability_topic)) {
        return ESP_ERR_INVALID_ARG;
    }

    const mqtt_relay_discovery_field_t *field = &s_discovery_fields[field_index];
    char object_name[PROVISION_MQTT_CLIENT_ID_MAX + 40];
    char unique_id[PROVISION_MQTT_CLIENT_ID_MAX + 32];
    int id_written = snprintf(object_name,
                              sizeof(object_name),
                              "%s %s",
                              config->mqtt_client_id,
                              field->name);
    if (id_written < 0 || (size_t)id_written >= sizeof(object_name)) {
        return ESP_ERR_INVALID_SIZE;
    }
    id_written = snprintf(unique_id,
                          sizeof(unique_id),
                          "%s_%s",
                          config->mqtt_client_id,
                          field->key);
    if (id_written < 0 || (size_t)id_written >= sizeof(unique_id)) {
        return ESP_ERR_INVALID_SIZE;
    }

    char *cursor = out;
    size_t remaining = out_size;
    int written = snprintf(cursor, remaining, "{\"name\":");
    if (written < 0 || (size_t)written >= remaining) {
        return ESP_ERR_INVALID_SIZE;
    }
    cursor += written;
    remaining -= (size_t)written;
    esp_err_t err = json_write_string(&cursor, &remaining, object_name);
    if (err != ESP_OK) {
        return err;
    }

#define APPEND_JSON_LABEL(label)                                        \
    do {                                                                \
        written = snprintf(cursor, remaining, label);                    \
        if (written < 0 || (size_t)written >= remaining) {               \
            return ESP_ERR_INVALID_SIZE;                                 \
        }                                                               \
        cursor += written;                                               \
        remaining -= (size_t)written;                                    \
    } while (0)

    APPEND_JSON_LABEL(",\"unique_id\":");
    err = json_write_string(&cursor, &remaining, unique_id);
    if (err != ESP_OK) {
        return err;
    }
    APPEND_JSON_LABEL(",\"object_id\":");
    err = json_write_string(&cursor, &remaining, unique_id);
    if (err != ESP_OK) {
        return err;
    }
    APPEND_JSON_LABEL(",\"state_topic\":");
    err = json_write_string(&cursor, &remaining, notification_topic);
    if (err != ESP_OK) {
        return err;
    }
    APPEND_JSON_LABEL(",\"value_template\":");
    err = json_write_string(&cursor, &remaining, field->value_template);
    if (err != ESP_OK) {
        return err;
    }
    APPEND_JSON_LABEL(",\"availability_topic\":");
    err = json_write_string(&cursor, &remaining, availability_topic);
    if (err != ESP_OK) {
        return err;
    }
    APPEND_JSON_LABEL(
        ",\"payload_available\":\"online\",\"payload_not_available\":\"offline\"");
    err = append_device_json(&cursor, &remaining, config, device_info);
    if (err != ESP_OK) {
        return err;
    }
    APPEND_JSON_LABEL("}");
#undef APPEND_JSON_LABEL

    return ESP_OK;
}

size_t mqtt_relay_wifi_discovery_field_count(void)
{
    return sizeof(s_wifi_discovery_fields) / sizeof(s_wifi_discovery_fields[0]);
}

const char *mqtt_relay_wifi_discovery_field_key(size_t field_index)
{
    if (field_index >= mqtt_relay_wifi_discovery_field_count()) {
        return NULL;
    }
    return s_wifi_discovery_fields[field_index].key;
}

esp_err_t mqtt_relay_build_wifi_discovery_topic(
    const provision_config_t *config,
    size_t field_index,
    char *out,
    size_t out_size)
{
    if (config == NULL || out == NULL || out_size == 0U ||
        field_index >= mqtt_relay_wifi_discovery_field_count() ||
        !discovery_id_is_safe(config->mqtt_client_id)) {
        return ESP_ERR_INVALID_ARG;
    }
    const int written = snprintf(out,
                                 out_size,
                                 "homeassistant/sensor/%s/%s/config",
                                 config->mqtt_client_id,
                                 s_wifi_discovery_fields[field_index].key);
    return (written < 0 || (size_t)written >= out_size) ? ESP_ERR_INVALID_SIZE
                                                        : ESP_OK;
}

esp_err_t mqtt_relay_build_wifi_discovery_payload(
    const provision_config_t *config,
    const mqtt_relay_device_info_t *device_info,
    const char *state_topic,
    const char *availability_topic,
    size_t field_index,
    char *out,
    size_t out_size)
{
    if (config == NULL || !device_info_is_valid(device_info) ||
        state_topic == NULL || availability_topic == NULL || out == NULL ||
        out_size == 0U ||
        field_index >= mqtt_relay_wifi_discovery_field_count() ||
        !discovery_id_is_safe(config->mqtt_client_id) ||
        topic_has_publish_wildcard(state_topic) ||
        topic_has_publish_wildcard(availability_topic)) {
        return ESP_ERR_INVALID_ARG;
    }

    const mqtt_relay_wifi_discovery_field_t *field =
        &s_wifi_discovery_fields[field_index];
    char object_name[PROVISION_MQTT_CLIENT_ID_MAX + 40];
    char unique_id[PROVISION_MQTT_CLIENT_ID_MAX + 32];
    int written = snprintf(object_name,
                           sizeof(object_name),
                           "%s %s",
                           config->mqtt_client_id,
                           field->name);
    if (written < 0 || (size_t)written >= sizeof(object_name)) {
        return ESP_ERR_INVALID_SIZE;
    }
    written = snprintf(unique_id,
                       sizeof(unique_id),
                       "%s_%s",
                       config->mqtt_client_id,
                       field->key);
    if (written < 0 || (size_t)written >= sizeof(unique_id)) {
        return ESP_ERR_INVALID_SIZE;
    }

    char *cursor = out;
    size_t remaining = out_size;
    esp_err_t err = json_write_literal(&cursor, &remaining, "{\"name\":");
    if (err == ESP_OK) {
        err = json_write_string(&cursor, &remaining, object_name);
    }
    if (err == ESP_OK) {
        err = json_write_literal(&cursor, &remaining, ",\"unique_id\":");
    }
    if (err == ESP_OK) {
        err = json_write_string(&cursor, &remaining, unique_id);
    }
    if (err == ESP_OK) {
        err = json_write_literal(&cursor, &remaining, ",\"object_id\":");
    }
    if (err == ESP_OK) {
        err = json_write_string(&cursor, &remaining, unique_id);
    }
    if (err == ESP_OK) {
        err = json_write_literal(&cursor, &remaining, ",\"state_topic\":");
    }
    if (err == ESP_OK) {
        err = json_write_string(&cursor, &remaining, state_topic);
    }
    if (err == ESP_OK) {
        err = json_write_literal(&cursor, &remaining, ",\"value_template\":");
    }
    if (err == ESP_OK) {
        err = json_write_string(&cursor, &remaining, field->value_template);
    }
    if (err == ESP_OK) {
        err = json_write_literal(&cursor, &remaining, ",\"availability_topic\":");
    }
    if (err == ESP_OK) {
        err = json_write_string(&cursor, &remaining, availability_topic);
    }
    if (err == ESP_OK) {
        err = json_write_literal(
            &cursor,
            &remaining,
            ",\"payload_available\":\"online\",\"payload_not_available\":\"offline\""
            ",\"entity_category\":\"diagnostic\"");
    }
    if (err == ESP_OK && field->device_class != NULL) {
        err = json_write_literal(&cursor, &remaining, ",\"device_class\":");
        if (err == ESP_OK) {
            err = json_write_string(&cursor, &remaining, field->device_class);
        }
    }
    if (err == ESP_OK && field->state_class != NULL) {
        err = json_write_literal(&cursor, &remaining, ",\"state_class\":");
        if (err == ESP_OK) {
            err = json_write_string(&cursor, &remaining, field->state_class);
        }
    }
    if (err == ESP_OK && field->unit_of_measurement != NULL) {
        err = json_write_literal(&cursor, &remaining, ",\"unit_of_measurement\":");
        if (err == ESP_OK) {
            err = json_write_string(&cursor,
                                    &remaining,
                                    field->unit_of_measurement);
        }
    }
    if (err == ESP_OK) {
        err = append_device_json(&cursor, &remaining, config, device_info);
    }
    if (err == ESP_OK) {
        err = json_write_literal(&cursor, &remaining, "}");
    }
    return err;
}

esp_err_t mqtt_relay_build_state_payload(const mqtt_relay_counters_t *counters,
                                         bool connected,
                                         char *out,
                                         size_t out_size)
{
    if (counters == NULL || out == NULL || out_size == 0U) {
        return ESP_ERR_INVALID_ARG;
    }
    const int written =
        snprintf(out,
                 out_size,
                 "{\"connected\":%s,\"accepted\":%" PRIu32
                 ",\"published_ack\":%" PRIu32 ",\"dropped_offline\":%" PRIu32
                 ",\"dropped_enqueue\":%" PRIu32 ",\"dropped_policy\":%" PRIu32
                 "}",
                 connected ? "true" : "false",
                 counters->accepted,
                 counters->published_ack,
                 counters->dropped_offline,
                 counters->dropped_enqueue,
                 counters->dropped_policy);
    return (written < 0 || (size_t)written >= out_size) ? ESP_ERR_INVALID_SIZE
                                                        : ESP_OK;
}

static void mqtt_relay_lock(void)
{
    if (s_ctx.lock != NULL) {
        (void)xSemaphoreTake(s_ctx.lock, portMAX_DELAY);
    }
}

static void mqtt_relay_unlock(void)
{
    if (s_ctx.lock != NULL) {
        (void)xSemaphoreGive(s_ctx.lock);
    }
}

static void mqtt_relay_lifecycle_lock(void)
{
    if (s_ctx.lifecycle_lock != NULL) {
        (void)xSemaphoreTake(s_ctx.lifecycle_lock, portMAX_DELAY);
    }
}

static void mqtt_relay_lifecycle_unlock(void)
{
    if (s_ctx.lifecycle_lock != NULL) {
        (void)xSemaphoreGive(s_ctx.lifecycle_lock);
    }
}

static void mqtt_relay_free_item(mqtt_payload_item_t *item)
{
    if (item == NULL) {
        return;
    }
    free(item->topic);
    free(item->payload);
    free(item);
    s_ctx.counters.freed++;
}

static void mqtt_relay_free_pending_locked(void)
{
    mqtt_payload_item_t *item = s_ctx.pending;
    s_ctx.pending = NULL;
    while (item != NULL) {
        mqtt_payload_item_t *next = item->next;
        mqtt_relay_free_item(item);
        item = next;
    }
}

static void mqtt_relay_free_queue_locked(void)
{
    if (s_ctx.queue == NULL) {
        return;
    }
    mqtt_payload_item_t *item = NULL;
    while (xQueueReceive(s_ctx.queue, &item, 0) == pdTRUE) {
        mqtt_relay_free_item(item);
    }
}

static void mqtt_relay_cleanup_runtime_locked(void)
{
    mqtt_relay_free_queue_locked();
    mqtt_relay_free_pending_locked();
    if (s_ctx.queue != NULL) {
        vQueueDelete(s_ctx.queue);
        s_ctx.queue = NULL;
    }
    if (s_ctx.lock != NULL) {
        SemaphoreHandle_t lock = s_ctx.lock;
        s_ctx.lock = NULL;
        vSemaphoreDelete(lock);
    }
    if (s_ctx.lifecycle_lock != NULL) {
        SemaphoreHandle_t lifecycle_lock = s_ctx.lifecycle_lock;
        s_ctx.lifecycle_lock = NULL;
        vSemaphoreDelete(lifecycle_lock);
    }
}

static void mqtt_relay_track_pending_locked(mqtt_payload_item_t *item, int msg_id)
{
    item->msg_id = msg_id;
    item->next = s_ctx.pending;
    s_ctx.pending = item;
}

static mqtt_payload_item_t *mqtt_relay_take_pending_locked(int msg_id)
{
    mqtt_payload_item_t **cursor = &s_ctx.pending;
    while (*cursor != NULL) {
        if ((*cursor)->msg_id == msg_id) {
            mqtt_payload_item_t *item = *cursor;
            *cursor = item->next;
            item->next = NULL;
            return item;
        }
        cursor = &(*cursor)->next;
    }
    return NULL;
}

static int mqtt_relay_publish_raw(const char *topic,
                                  const char *payload,
                                  int length,
                                  int qos,
                                  int retain)
{
    if (s_publish_for_test != NULL) {
        return s_publish_for_test(topic, payload, length, qos, retain);
    }

    mqtt_relay_lock();
    esp_mqtt_client_handle_t client = s_ctx.client;
    if (client == NULL || !s_ctx.publish_allowed) {
        mqtt_relay_unlock();
        return -1;
    }
    s_ctx.publish_in_flight++;
    mqtt_relay_unlock();

    const int result = esp_mqtt_client_publish(client, topic, payload, length, qos, retain);

    mqtt_relay_lock();
    if (s_ctx.publish_in_flight > 0U) {
        s_ctx.publish_in_flight--;
    }
    mqtt_relay_unlock();
    return result;
}

static void mqtt_relay_wait_publish_idle(void)
{
    for (;;) {
        mqtt_relay_lock();
        const uint32_t in_flight = s_ctx.publish_in_flight;
        mqtt_relay_unlock();
        if (in_flight == 0U) {
            return;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

static void mqtt_relay_publish_retained_status(void)
{
    provision_config_t *discovery_config = calloc(1, sizeof(*discovery_config));
    char *discovery = calloc(1, MQTT_RELAY_DISCOVERY_PAYLOAD_MAX);
    if (discovery_config == NULL || discovery == NULL) {
        free(discovery);
        free(discovery_config);
        return;
    }
    mqtt_relay_counters_t counters;
    mqtt_relay_device_info_t device_info;
    bool connected;
    char notification_topic[MQTT_RELAY_TOPIC_MAX];
    char availability_topic[MQTT_RELAY_TOPIC_MAX];
    char state_topic[MQTT_RELAY_TOPIC_MAX];
    char discovery_topic[MQTT_RELAY_DISCOVERY_TOPIC_MAX];
    char enroll_command_topic[MQTT_RELAY_TOPIC_MAX];
    char enroll_discovery_topic[MQTT_RELAY_DISCOVERY_TOPIC_MAX];

    mqtt_relay_lock();
    (void)strlcpy(discovery_config->mqtt_client_id,
                  s_ctx.config.mqtt_client_id,
                  sizeof(discovery_config->mqtt_client_id));
    counters = s_ctx.counters;
    device_info = s_ctx.device_info;
    connected = s_ctx.mqtt_connected;
    (void)strlcpy(notification_topic, s_ctx.notification_topic, sizeof(notification_topic));
    (void)strlcpy(availability_topic, s_ctx.availability_topic, sizeof(availability_topic));
    (void)strlcpy(state_topic, s_ctx.state_topic, sizeof(state_topic));
    (void)strlcpy(discovery_topic, s_ctx.discovery_topic, sizeof(discovery_topic));
    (void)strlcpy(enroll_command_topic,
                  s_ctx.enroll_command_topic,
                  sizeof(enroll_command_topic));
    (void)strlcpy(enroll_discovery_topic,
                  s_ctx.enroll_discovery_topic,
                  sizeof(enroll_discovery_topic));
    mqtt_relay_unlock();

    char state[256];
    if (mqtt_relay_build_discovery_payload(discovery_config,
                                           &device_info,
                                           notification_topic,
                                           availability_topic,
                                           discovery,
                                           MQTT_RELAY_DISCOVERY_PAYLOAD_MAX) == ESP_OK) {
        (void)mqtt_relay_publish_raw(discovery_topic,
                                     discovery,
                                     0,
                                     MQTT_RELAY_RETAINED_QOS,
                                     MQTT_RELAY_RETAINED_RETAIN);
    }
    if (mqtt_relay_build_enroll_discovery_payload(
            discovery_config,
            &device_info,
            enroll_command_topic,
            availability_topic,
            discovery,
            MQTT_RELAY_DISCOVERY_PAYLOAD_MAX) == ESP_OK) {
        (void)mqtt_relay_publish_raw(enroll_discovery_topic,
                                     discovery,
                                     0,
                                     MQTT_RELAY_RETAINED_QOS,
                                     MQTT_RELAY_RETAINED_RETAIN);
    }
    for (size_t field_index = 0;
         field_index < mqtt_relay_discovery_field_count();
         ++field_index) {
        if (mqtt_relay_build_field_discovery_topic(discovery_config,
                                                   field_index,
                                                   discovery_topic,
                                                   sizeof(discovery_topic)) != ESP_OK ||
            mqtt_relay_build_field_discovery_payload(discovery_config,
                                                     &device_info,
                                                     notification_topic,
                                                     availability_topic,
                                                     field_index,
                                                     discovery,
                                                     MQTT_RELAY_DISCOVERY_PAYLOAD_MAX) !=
            ESP_OK) {
            continue;
        }
        (void)mqtt_relay_publish_raw(discovery_topic,
                                     discovery,
                                     0,
                                     MQTT_RELAY_RETAINED_QOS,
                                     MQTT_RELAY_RETAINED_RETAIN);
    }
    if (mqtt_relay_build_state_payload(&counters,
                                       connected,
                                       state,
                                       sizeof(state)) == ESP_OK) {
        (void)mqtt_relay_publish_raw(state_topic,
                                     state,
                                     0,
                                     MQTT_RELAY_RETAINED_QOS,
                                     MQTT_RELAY_RETAINED_RETAIN);
    }
    (void)mqtt_relay_publish_raw(availability_topic,
                                 "online",
                                 0,
                                 MQTT_RELAY_RETAINED_QOS,
                                 MQTT_RELAY_RETAINED_RETAIN);
    free(discovery);
    free(discovery_config);
}

static void mqtt_relay_drain_queue(void)
{
    for (;;) {
        mqtt_relay_lock();
        if (!s_ctx.mqtt_connected || s_ctx.queue == NULL) {
            mqtt_relay_unlock();
            return;
        }
        mqtt_payload_item_t *item = NULL;
        if (xQueueReceive(s_ctx.queue, &item, 0) != pdTRUE) {
            mqtt_relay_unlock();
            return;
        }
        s_ctx.worker_busy = true;
        mqtt_relay_unlock();

        const int msg_id = mqtt_relay_publish_raw(item->topic,
                                                  item->payload,
                                                  (int)item->payload_length,
                                                  MQTT_RELAY_NOTIFICATION_QOS,
                                                  MQTT_RELAY_NOTIFICATION_RETAIN);

        mqtt_relay_lock();
        s_ctx.worker_busy = false;
        if (msg_id <= 0 || !s_ctx.mqtt_connected) {
            mqtt_relay_free_item(item);
        } else {
            mqtt_relay_track_pending_locked(item, msg_id);
        }
        mqtt_relay_unlock();
    }
}

static void mqtt_relay_worker(void *arg)
{
    (void)arg;
    for (;;) {
        (void)ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        mqtt_relay_lock();
        const bool running = s_ctx.worker_running;
        if (!running) {
            s_ctx.worker_task = NULL;
            mqtt_relay_unlock();
            vTaskDelete(NULL);
        }
        mqtt_relay_unlock();
        mqtt_relay_drain_queue();
    }
}

static void mqtt_relay_notify_worker(void)
{
    mqtt_relay_lock();
    TaskHandle_t worker = s_ctx.worker_task;
    mqtt_relay_unlock();
    if (worker != NULL) {
        xTaskNotifyGive(worker);
    }
}

static void mqtt_relay_wait_worker_idle(void)
{
    for (;;) {
        mqtt_relay_lock();
        const bool busy = s_ctx.worker_busy || s_ctx.publish_in_flight > 0U;
        mqtt_relay_unlock();
        if (!busy) {
            return;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

static void mqtt_relay_stop_worker_for_teardown(void)
{
    mqtt_relay_lock();
    s_ctx.worker_running = false;
    TaskHandle_t worker = s_ctx.worker_task;
    mqtt_relay_unlock();
    if (worker != NULL) {
        xTaskNotifyGive(worker);
    }
    for (;;) {
        mqtt_relay_lock();
        const bool stopped = s_ctx.worker_task == NULL && !s_ctx.worker_busy;
        mqtt_relay_unlock();
        if (stopped) {
            return;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

static esp_err_t mqtt_relay_ensure_worker(void)
{
    mqtt_relay_lock();
    if (s_ctx.worker_task != NULL) {
        s_ctx.worker_running = true;
        mqtt_relay_unlock();
        return ESP_OK;
    }
    s_ctx.worker_running = true;
    mqtt_relay_unlock();
    TaskHandle_t worker = NULL;
    if (xTaskCreate(mqtt_relay_worker,
                    "mqtt_relay",
                    MQTT_RELAY_WORKER_STACK,
                    NULL,
                    MQTT_RELAY_WORKER_PRIORITY,
                    &worker) != pdPASS) {
        mqtt_relay_lock();
        s_ctx.worker_running = false;
        mqtt_relay_unlock();
        return ESP_ERR_NO_MEM;
    }
    mqtt_relay_lock();
    s_ctx.worker_task = worker;
    mqtt_relay_unlock();
    return ESP_OK;
}

static void mqtt_relay_handle_disconnect_locked(void)
{
    s_ctx.mqtt_connected = false;
    mqtt_relay_free_queue_locked();
    mqtt_relay_free_pending_locked();
}

static void mqtt_relay_terminal_reconfigure_failure_cleanup(void)
{
    mqtt_relay_lock();
    s_ctx.client = NULL;
    s_ctx.accepting_observers = false;
    s_ctx.publish_allowed = false;
    s_ctx.mqtt_connected = false;
    mqtt_relay_free_queue_locked();
    mqtt_relay_free_pending_locked();
    mqtt_relay_unlock();

    mqtt_relay_wait_publish_idle();
    mqtt_relay_stop_worker_for_teardown();

    mqtt_relay_lock();
    QueueHandle_t queue = s_ctx.queue;
    s_ctx.queue = NULL;
    mqtt_relay_unlock();
    if (queue != NULL) {
        vQueueDelete(queue);
    }
}

static bool mqtt_relay_event_is_current(esp_mqtt_event_handle_t event,
                                        int32_t event_id)
{
    if (event == NULL) {
        return false;
    }
    mqtt_relay_lock();
    const bool active_client = event->client != NULL && event->client == s_ctx.client;
    const bool accepting = s_ctx.accepting_observers;
    const bool publish_allowed = s_ctx.publish_allowed;
    mqtt_relay_unlock();

    if (!active_client) {
        return false;
    }
    switch (event_id) {
    case MQTT_EVENT_CONNECTED:
    case MQTT_EVENT_DATA:
        return accepting && publish_allowed;
    case MQTT_EVENT_PUBLISHED:
        return accepting && publish_allowed;
    case MQTT_EVENT_DISCONNECTED:
    case MQTT_EVENT_ERROR:
        return accepting;
    default:
        return true;
    }
}

static void mqtt_relay_event_handler(void *handler_args,
                                     esp_event_base_t base,
                                     int32_t event_id,
                                     void *event_data)
{
    (void)handler_args;
    (void)base;
    esp_mqtt_event_handle_t event = (esp_mqtt_event_handle_t)event_data;

    if (!mqtt_relay_event_is_current(event, event_id)) {
        return;
    }

    if (event_id == MQTT_EVENT_CONNECTED) {
        char enroll_command_topic[MQTT_RELAY_TOPIC_MAX];
        mqtt_relay_lock();
        s_ctx.mqtt_connected = true;
        (void)strlcpy(enroll_command_topic,
                      s_ctx.enroll_command_topic,
                      sizeof(enroll_command_topic));
        mqtt_relay_unlock();
        const int subscription_id = esp_mqtt_client_subscribe(
            event->client,
            enroll_command_topic,
            MQTT_RELAY_ENROLL_COMMAND_QOS);
        if (subscription_id < 0) {
            mqtt_relay_lock();
            s_ctx.mqtt_connected = false;
            mqtt_relay_unlock();
            mqtt_relay_emit_event(MQTT_RELAY_EVENT_FAILED);
            return;
        }
        mqtt_relay_publish_retained_status();
        mqtt_relay_notify_worker();
        mqtt_relay_emit_event(MQTT_RELAY_EVENT_CONNECTED);
        return;
    }

    if (event_id == MQTT_EVENT_DATA) {
        if (event->topic_len < 0 || event->data_len < 0 ||
            event->total_data_len < 0 || event->current_data_offset < 0) {
            return;
        }
        char expected_topic[MQTT_RELAY_TOPIC_MAX];
        mqtt_relay_lock();
        (void)strlcpy(expected_topic,
                      s_ctx.enroll_command_topic,
                      sizeof(expected_topic));
        mqtt_relay_unlock();
        if (mqtt_relay_is_enroll_command(
                expected_topic,
                event->topic,
                (size_t)event->topic_len,
                event->data,
                (size_t)event->data_len,
                (size_t)event->total_data_len,
                (size_t)event->current_data_offset,
                event->retain != 0)) {
            mqtt_relay_emit_event(MQTT_RELAY_EVENT_ENROLL_REQUEST);
        }
        return;
    }

    bool emit_disconnected = false;
    bool emit_failed = false;
    mqtt_relay_lock();
    switch (event_id) {
    case MQTT_EVENT_PUBLISHED:
        if (event != NULL) {
            mqtt_payload_item_t *item = mqtt_relay_take_pending_locked(event->msg_id);
            if (item != NULL) {
                s_ctx.counters.published_ack++;
                mqtt_relay_free_item(item);
            }
        }
        break;
    case MQTT_EVENT_DISCONNECTED:
        mqtt_relay_handle_disconnect_locked();
        emit_disconnected = true;
        break;
    case MQTT_EVENT_ERROR:
        mqtt_relay_handle_disconnect_locked();
        emit_failed = true;
        break;
    default:
        break;
    }
    mqtt_relay_unlock();
    if (emit_failed) {
        mqtt_relay_emit_event(MQTT_RELAY_EVENT_FAILED);
    }
    if (emit_disconnected) {
        mqtt_relay_emit_event(MQTT_RELAY_EVENT_DISCONNECTED);
    }
}

static esp_err_t mqtt_relay_prepare_context(
    const provision_config_t *config,
    const mqtt_relay_device_info_t *device_info)
{
    if (config == NULL || !device_info_is_valid(device_info)) {
        return ESP_ERR_INVALID_ARG;
    }
    esp_err_t err = mqtt_relay_build_topics(config,
                                            s_ctx.notification_topic,
                                            sizeof(s_ctx.notification_topic),
                                            s_ctx.availability_topic,
                                            sizeof(s_ctx.availability_topic),
                                            s_ctx.state_topic,
                                            sizeof(s_ctx.state_topic),
                                            s_ctx.discovery_topic,
                                            sizeof(s_ctx.discovery_topic));
    if (err != ESP_OK) {
        return err;
    }
    err = mqtt_relay_build_enroll_command_topic(
        config,
        s_ctx.enroll_command_topic,
        sizeof(s_ctx.enroll_command_topic));
    if (err != ESP_OK) {
        return err;
    }
    err = mqtt_relay_build_enroll_discovery_topic(
        config,
        s_ctx.enroll_discovery_topic,
        sizeof(s_ctx.enroll_discovery_topic));
    if (err != ESP_OK) {
        return err;
    }
    s_ctx.config = *config;
    s_ctx.device_info = *device_info;
    s_ctx.queue = xQueueCreate(MQTT_RELAY_QUEUE_CAPACITY, sizeof(mqtt_payload_item_t *));
    s_ctx.lock = xSemaphoreCreateMutex();
    s_ctx.lifecycle_lock = xSemaphoreCreateMutex();
    if (s_ctx.queue == NULL || s_ctx.lock == NULL || s_ctx.lifecycle_lock == NULL) {
        mqtt_relay_cleanup_runtime_locked();
        return ESP_ERR_NO_MEM;
    }
    s_ctx.boot_nonce = (uint32_t)esp_timer_get_time();
    relay_policy_recent_cache_init(&s_ctx.recent);
    return ESP_OK;
}

esp_err_t mqtt_relay_init(const provision_config_t *config,
                          const mqtt_relay_device_info_t *device_info)
{
    if (s_ctx.client != NULL || s_ctx.queue != NULL) {
        return ESP_ERR_INVALID_STATE;
    }

    esp_err_t err = mqtt_relay_prepare_context(config, device_info);
    if (err != ESP_OK) {
        return err;
    }
    esp_mqtt_client_config_t mqtt_config = {0};
    err = mqtt_relay_build_client_config(config, s_ctx.availability_topic, &mqtt_config);
    if (err != ESP_OK) {
        mqtt_relay_cleanup_runtime_locked();
        return err;
    }
    s_ctx.client = esp_mqtt_client_init(&mqtt_config);
    if (s_ctx.client == NULL) {
        mqtt_relay_cleanup_runtime_locked();
        return ESP_ERR_NO_MEM;
    }
    err = esp_mqtt_client_register_event(s_ctx.client,
                                         ESP_EVENT_ANY_ID,
                                         mqtt_relay_event_handler,
                                         NULL);
    if (err != ESP_OK) {
        (void)esp_mqtt_client_destroy(s_ctx.client);
        s_ctx.client = NULL;
        mqtt_relay_cleanup_runtime_locked();
        return err;
    }
    mqtt_relay_lock();
    s_ctx.accepting_observers = true;
    s_ctx.publish_allowed = true;
    mqtt_relay_unlock();
    return ESP_OK;
}

static esp_err_t mqtt_relay_start_unlocked(void)
{
    if (s_ctx.client == NULL) {
        return ESP_ERR_INVALID_STATE;
    }
    esp_err_t err = mqtt_relay_ensure_worker();
    if (err != ESP_OK) {
        return err;
    }
    mqtt_relay_lock();
    s_ctx.publish_allowed = true;
    mqtt_relay_unlock();
    return esp_mqtt_client_start(s_ctx.client);
}

esp_err_t mqtt_relay_start(void)
{
    mqtt_relay_lifecycle_lock();
    esp_err_t err = mqtt_relay_start_unlocked();
    mqtt_relay_lifecycle_unlock();
    return err;
}

esp_err_t mqtt_relay_reconnect(void)
{
    mqtt_relay_lifecycle_lock();
    if (s_ctx.client == NULL) {
        mqtt_relay_lifecycle_unlock();
        return ESP_ERR_INVALID_STATE;
    }
    esp_err_t err = mqtt_relay_ensure_worker();
    if (err != ESP_OK) {
        mqtt_relay_lifecycle_unlock();
        return err;
    }
    mqtt_relay_lock();
    s_ctx.publish_allowed = true;
    mqtt_relay_unlock();
    err = esp_mqtt_client_reconnect(s_ctx.client);
    mqtt_relay_lifecycle_unlock();
    return err;
}

static esp_err_t mqtt_relay_stop_unlocked(void)
{
    char availability_topic[MQTT_RELAY_TOPIC_MAX];
    bool publish_offline = false;

    mqtt_relay_lock();
    if (s_ctx.mqtt_connected) {
        publish_offline = true;
        (void)strlcpy(availability_topic,
                      s_ctx.availability_topic,
                      sizeof(availability_topic));
    }
    mqtt_relay_handle_disconnect_locked();
    mqtt_relay_unlock();
    mqtt_relay_wait_worker_idle();

    if (publish_offline) {
        (void)mqtt_relay_publish_raw(availability_topic,
                                     "offline",
                                     0,
                                     MQTT_RELAY_RETAINED_QOS,
                                     MQTT_RELAY_RETAINED_RETAIN);
    }
    mqtt_relay_lock();
    s_ctx.publish_allowed = false;
    mqtt_relay_unlock();
    mqtt_relay_wait_publish_idle();

    if (s_ctx.client != NULL) {
        return esp_mqtt_client_stop(s_ctx.client);
    }
    return ESP_OK;
}

esp_err_t mqtt_relay_stop(void)
{
    mqtt_relay_lifecycle_lock();
    esp_err_t err = mqtt_relay_stop_unlocked();
    mqtt_relay_lifecycle_unlock();
    return err;
}

esp_err_t mqtt_relay_deinit(void)
{
    mqtt_relay_lifecycle_lock();
    esp_mqtt_client_handle_t client = s_ctx.client;
    if (client != NULL) {
        (void)mqtt_relay_stop_unlocked();
        mqtt_relay_wait_publish_idle();
        (void)esp_mqtt_client_destroy(client);
    }
    mqtt_relay_stop_worker_for_teardown();

    if (s_ctx.lock != NULL) {
        (void)xSemaphoreTake(s_ctx.lock, portMAX_DELAY);
    }
    s_ctx.client = NULL;
    s_ctx.worker_running = false;
    s_ctx.worker_task = NULL;
    s_ctx.accepting_observers = false;
    s_ctx.publish_allowed = false;
    mqtt_relay_free_queue_locked();
    mqtt_relay_free_pending_locked();
    QueueHandle_t queue = s_ctx.queue;
    SemaphoreHandle_t lock = s_ctx.lock;
    SemaphoreHandle_t lifecycle_lock = s_ctx.lifecycle_lock;
    s_ctx.queue = NULL;
    s_ctx.lock = NULL;
    s_ctx.lifecycle_lock = NULL;
    if (lock != NULL) {
        (void)xSemaphoreGive(lock);
    }
    if (queue != NULL) {
        vQueueDelete(queue);
    }
    if (lock != NULL) {
        vSemaphoreDelete(lock);
    }
    if (lifecycle_lock != NULL) {
        (void)xSemaphoreGive(lifecycle_lock);
        vSemaphoreDelete(lifecycle_lock);
    }
    memset(&s_ctx, 0, sizeof(s_ctx));
    return ESP_OK;
}

esp_err_t mqtt_relay_reconfigure(const provision_config_t *config)
{
    if (config == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    mqtt_relay_lifecycle_lock();

    char next_notification_topic[MQTT_RELAY_TOPIC_MAX];
    char next_availability_topic[MQTT_RELAY_TOPIC_MAX];
    char next_state_topic[MQTT_RELAY_TOPIC_MAX];
    char next_discovery_topic[MQTT_RELAY_DISCOVERY_TOPIC_MAX];
    char next_enroll_command_topic[MQTT_RELAY_TOPIC_MAX];
    char next_enroll_discovery_topic[MQTT_RELAY_DISCOVERY_TOPIC_MAX];
    esp_err_t err = mqtt_relay_build_topics(config,
                                            next_notification_topic,
                                            sizeof(next_notification_topic),
                                            next_availability_topic,
                                            sizeof(next_availability_topic),
                                            next_state_topic,
                                            sizeof(next_state_topic),
                                            next_discovery_topic,
                                            sizeof(next_discovery_topic));
    if (err != ESP_OK) {
        mqtt_relay_lifecycle_unlock();
        return err;
    }
    err = mqtt_relay_build_enroll_command_topic(
        config,
        next_enroll_command_topic,
        sizeof(next_enroll_command_topic));
    if (err != ESP_OK) {
        mqtt_relay_lifecycle_unlock();
        return err;
    }
    err = mqtt_relay_build_enroll_discovery_topic(
        config,
        next_enroll_discovery_topic,
        sizeof(next_enroll_discovery_topic));
    if (err != ESP_OK) {
        mqtt_relay_lifecycle_unlock();
        return err;
    }
    esp_mqtt_client_config_t mqtt_config = {0};
    err = mqtt_relay_build_client_config(config,
                                         next_availability_topic,
                                         &mqtt_config);
    if (err != ESP_OK) {
        mqtt_relay_lifecycle_unlock();
        return err;
    }

    mqtt_relay_lock();
    s_ctx.accepting_observers = false;
    s_ctx.publish_allowed = false;
    const bool should_start = s_ctx.wifi_connected;
    mqtt_relay_unlock();

    esp_mqtt_client_handle_t old_client = s_ctx.client;
    if (old_client != NULL) {
        (void)mqtt_relay_stop_unlocked();
        mqtt_relay_wait_publish_idle();
        (void)esp_mqtt_client_destroy(old_client);
    }

    mqtt_relay_lock();
    s_ctx.client = NULL;
    s_ctx.mqtt_connected = false;
    mqtt_relay_free_queue_locked();
    mqtt_relay_free_pending_locked();
    (void)strlcpy(s_ctx.notification_topic,
                  next_notification_topic,
                  sizeof(s_ctx.notification_topic));
    (void)strlcpy(s_ctx.availability_topic,
                  next_availability_topic,
                  sizeof(s_ctx.availability_topic));
    (void)strlcpy(s_ctx.state_topic, next_state_topic, sizeof(s_ctx.state_topic));
    (void)strlcpy(s_ctx.discovery_topic,
                  next_discovery_topic,
                  sizeof(s_ctx.discovery_topic));
    (void)strlcpy(s_ctx.enroll_command_topic,
                  next_enroll_command_topic,
                  sizeof(s_ctx.enroll_command_topic));
    (void)strlcpy(s_ctx.enroll_discovery_topic,
                  next_enroll_discovery_topic,
                  sizeof(s_ctx.enroll_discovery_topic));
    s_ctx.config = *config;
    mqtt_relay_unlock();

    memset(&mqtt_config, 0, sizeof(mqtt_config));
    err = mqtt_relay_build_client_config(&s_ctx.config,
                                         s_ctx.availability_topic,
                                         &mqtt_config);
    if (err != ESP_OK) {
        mqtt_relay_terminal_reconfigure_failure_cleanup();
        mqtt_relay_lifecycle_unlock();
        return err;
    }
    esp_mqtt_client_handle_t new_client = esp_mqtt_client_init(&mqtt_config);
    if (new_client == NULL) {
        mqtt_relay_terminal_reconfigure_failure_cleanup();
        mqtt_relay_lifecycle_unlock();
        return ESP_ERR_NO_MEM;
    }
    err = esp_mqtt_client_register_event(new_client,
                                         ESP_EVENT_ANY_ID,
                                         mqtt_relay_event_handler,
                                         NULL);
    if (err != ESP_OK) {
        (void)esp_mqtt_client_destroy(new_client);
        mqtt_relay_terminal_reconfigure_failure_cleanup();
        mqtt_relay_lifecycle_unlock();
        return err;
    }

    mqtt_relay_lock();
    s_ctx.client = new_client;
    relay_policy_recent_cache_init(&s_ctx.recent);
    s_ctx.accepting_observers = true;
    s_ctx.publish_allowed = true;
    mqtt_relay_unlock();

    if (should_start) {
        err = mqtt_relay_start_unlocked();
        if (err != ESP_OK) {
            (void)mqtt_relay_stop_unlocked();
            mqtt_relay_wait_publish_idle();
            (void)esp_mqtt_client_destroy(new_client);
            mqtt_relay_terminal_reconfigure_failure_cleanup();
            mqtt_relay_lifecycle_unlock();
            return err;
        }
    }
    mqtt_relay_lifecycle_unlock();
    return ESP_OK;
}

esp_err_t mqtt_relay_register_event_callback(mqtt_relay_event_callback_t callback,
                                             void *context)
{
    mqtt_relay_lock();
    s_ctx.event_callback = callback;
    s_ctx.event_context = context;
    mqtt_relay_unlock();
    return ESP_OK;
}

void mqtt_relay_set_wifi_connected(bool connected)
{
    mqtt_relay_lock();
    s_ctx.wifi_connected = connected;
    mqtt_relay_unlock();
}

void mqtt_relay_observe_notification(const ancs_notification_t *notification,
                                     const char *device_name,
                                     void *context)
{
    (void)context;
    if (notification == NULL || device_name == NULL) {
        return;
    }

    char relay_id[RELAY_POLICY_ID_MAX];
    char topic[MQTT_RELAY_TOPIC_MAX];

    mqtt_relay_lock();
    if (!s_ctx.accepting_observers || !s_ctx.wifi_connected || !s_ctx.mqtt_connected) {
        s_ctx.counters.dropped_offline++;
        mqtt_relay_unlock();
        return;
    }
    relay_connectivity_t connectivity = {
        .wifi_connected = s_ctx.wifi_connected,
        .mqtt_connected = s_ctx.mqtt_connected,
        .boot_nonce = s_ctx.boot_nonce,
    };
    relay_decision_t decision =
        relay_policy_decide(notification, connectivity, &s_ctx.recent);
    if (decision != RELAY_PUBLISH ||
        relay_policy_build_id(notification, s_ctx.boot_nonce, relay_id, sizeof(relay_id)) !=
            ESP_OK) {
        s_ctx.counters.dropped_policy++;
        mqtt_relay_unlock();
        return;
    }
    (void)strlcpy(topic, s_ctx.notification_topic, sizeof(topic));
    mqtt_relay_unlock();

    char *payload = NULL;
    size_t payload_length = 0;
    if (mqtt_payload_build_notification(notification,
                                        device_name,
                                        relay_id,
                                        (uint64_t)(esp_timer_get_time() / 1000),
                                        &payload,
                                        &payload_length) != ESP_OK) {
        mqtt_relay_lock();
        s_ctx.counters.dropped_enqueue++;
        mqtt_relay_unlock();
        return;
    }

    mqtt_payload_item_t *item = calloc(1, sizeof(*item));
    char *heap_topic = strdup(topic);
    if (item == NULL || heap_topic == NULL) {
        free(heap_topic);
        free(item);
        free(payload);
        mqtt_relay_lock();
        s_ctx.counters.dropped_enqueue++;
        mqtt_relay_unlock();
        return;
    }
    item->topic = heap_topic;
    item->payload = payload;
    item->payload_length = payload_length;

    mqtt_relay_lock();
    if (!s_ctx.accepting_observers || !s_ctx.wifi_connected || !s_ctx.mqtt_connected) {
        s_ctx.counters.dropped_offline++;
        mqtt_relay_free_item(item);
        mqtt_relay_unlock();
        return;
    }
    connectivity.wifi_connected = s_ctx.wifi_connected;
    connectivity.mqtt_connected = s_ctx.mqtt_connected;
    connectivity.boot_nonce = s_ctx.boot_nonce;
    decision = relay_policy_decide(notification, connectivity, &s_ctx.recent);
    if (decision != RELAY_PUBLISH) {
        s_ctx.counters.dropped_policy++;
        mqtt_relay_free_item(item);
        mqtt_relay_unlock();
        return;
    }
    if (xQueueSend(s_ctx.queue, &item, 0) != pdTRUE) {
        s_ctx.counters.dropped_enqueue++;
        mqtt_relay_free_item(item);
        mqtt_relay_unlock();
        return;
    }
    relay_policy_mark_recent(&s_ctx.recent, relay_id);
    s_ctx.counters.accepted++;
    mqtt_relay_unlock();
    mqtt_relay_notify_worker();
}

void mqtt_relay_get_counters(mqtt_relay_counters_t *out)
{
    if (out == NULL) {
        return;
    }
    mqtt_relay_lock();
    *out = s_ctx.counters;
    mqtt_relay_unlock();
}

esp_err_t mqtt_relay_reset_for_test(
    const provision_config_t *config,
    const mqtt_relay_device_info_t *device_info)
{
    if (s_ctx.lock != NULL) {
        (void)xSemaphoreTake(s_ctx.lock, portMAX_DELAY);
    }
    mqtt_relay_free_queue_locked();
    mqtt_relay_free_pending_locked();
    QueueHandle_t queue = s_ctx.queue;
    SemaphoreHandle_t lock = s_ctx.lock;
    SemaphoreHandle_t lifecycle_lock = s_ctx.lifecycle_lock;
    s_ctx.queue = NULL;
    s_ctx.lock = NULL;
    s_ctx.lifecycle_lock = NULL;
    if (lock != NULL) {
        (void)xSemaphoreGive(lock);
    }
    if (queue != NULL) {
        vQueueDelete(queue);
    }
    if (lock != NULL) {
        vSemaphoreDelete(lock);
    }
    if (lifecycle_lock != NULL) {
        vSemaphoreDelete(lifecycle_lock);
    }
    memset(&s_ctx, 0, sizeof(s_ctx));
    s_publish_for_test = NULL;
    esp_err_t err = mqtt_relay_prepare_context(config, device_info);
    if (err == ESP_OK) {
        s_ctx.accepting_observers = true;
        s_ctx.publish_allowed = true;
    }
    return err;
}

void mqtt_relay_set_publish_for_test(mqtt_relay_publish_for_test_t publish)
{
    s_publish_for_test = publish;
}

void mqtt_relay_simulate_connected_for_test(bool connected)
{
    mqtt_relay_lock();
    s_ctx.wifi_connected = connected;
    s_ctx.mqtt_connected = connected;
    mqtt_relay_unlock();
    mqtt_relay_emit_event(connected ? MQTT_RELAY_EVENT_CONNECTED
                                    : MQTT_RELAY_EVENT_DISCONNECTED);
}

void mqtt_relay_publish_retained_for_test(void)
{
    mqtt_relay_publish_retained_status();
}

void mqtt_relay_drain_for_test(void)
{
    mqtt_relay_drain_queue();
}

void mqtt_relay_simulate_published_for_test(int msg_id)
{
    mqtt_relay_lock();
    mqtt_payload_item_t *item = mqtt_relay_take_pending_locked(msg_id);
    if (item != NULL) {
        s_ctx.counters.published_ack++;
        mqtt_relay_free_item(item);
    }
    mqtt_relay_unlock();
}

void mqtt_relay_simulate_disconnect_for_test(void)
{
    mqtt_relay_lock();
    mqtt_relay_handle_disconnect_locked();
    mqtt_relay_unlock();
    mqtt_relay_emit_event(MQTT_RELAY_EVENT_DISCONNECTED);
}
