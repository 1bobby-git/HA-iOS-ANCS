#include "mqtt_relay.h"

#include <inttypes.h>
#include <stdlib.h>
#include <string.h>

#include "mqtt_app_name.h"
#include "notification_sink.h"
#include "platform_identity.h"

esp_err_t mqtt_payload_build_notification(const ancs_notification_t *notification,
                                          const char *device_name,
                                          const char *relay_id,
                                          uint64_t uptime_ms,
                                          char **out_payload,
                                          size_t *out_length)
{
    if (notification == NULL || device_name == NULL || relay_id == NULL ||
        out_payload == NULL || out_length == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    *out_payload = NULL;
    *out_length = 0;

    const char *app_name = notification->app_name[0] != '\0'
                               ? notification->app_name
                               : mqtt_app_name_lookup(notification->app_id);
    const size_t text_length = strlen(notification->app_id) +
                               strlen(app_name) +
                               strlen(notification->title) +
                               strlen(notification->subtitle) +
                               strlen(notification->message) +
                               strlen(notification->message_size_raw) +
                               strlen(notification->date_raw) +
                               strlen(device_name) +
                               strlen(relay_id);
    if (text_length > (SIZE_MAX - 2304U) / 6U) {
        return ESP_ERR_INVALID_SIZE;
    }
    const size_t capacity = 2304U + (text_length * 6U);
    char *payload = malloc(capacity);
    if (payload == NULL) {
        return ESP_ERR_NO_MEM;
    }

    ancs_notification_t enriched = *notification;
    const size_t app_name_length = strlen(app_name);
    if (app_name_length > CONFIG_ANCS_APP_NAME_MAX) {
        free(payload);
        return ESP_ERR_INVALID_SIZE;
    }
    memcpy(enriched.app_name, app_name, app_name_length + 1U);

    const int serial_result = notification_sink_format_json(
        &enriched, device_name, payload, capacity);
    if (serial_result != 0) {
        free(payload);
        return ESP_ERR_INVALID_SIZE;
    }

    const size_t length = strlen(payload);
    if (length == 0U || payload[length - 1U] != '}') {
        free(payload);
        return ESP_ERR_INVALID_RESPONSE;
    }
    payload[length - 1U] = '\0';

    const int written = snprintf(payload + length - 1U,
                                 capacity - length + 1U,
                                 ",\"relay_id\":\"%s\",\"source\":\""
                                 ANCS_SOURCE_ID
                                 "\",\"published_at_ms\":%" PRIu64 "}",
                                 relay_id,
                                 uptime_ms);
    if (written < 0 || (size_t)written >= capacity - length + 1U) {
        free(payload);
        return ESP_ERR_INVALID_SIZE;
    }

    *out_payload = payload;
    *out_length = strlen(payload);
    return ESP_OK;
}
