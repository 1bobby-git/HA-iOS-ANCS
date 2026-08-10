#include "notification_sink.h"

#include <inttypes.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "platform_identity.h"

static notification_sink_observer_t s_observer;
static void *s_observer_context;

typedef struct {
    char *buffer;
    size_t capacity;
    size_t length;
    bool failed;
} json_writer_t;

static void writer_raw(json_writer_t *writer, const char *text)
{
    if (writer == NULL || text == NULL || writer->failed) {
        return;
    }
    const size_t length = strlen(text);
    if (length >= writer->capacity - writer->length) {
        writer->failed = true;
        return;
    }
    memcpy(writer->buffer + writer->length, text, length);
    writer->length += length;
    writer->buffer[writer->length] = '\0';
}

static void writer_bytes(json_writer_t *writer, const char *bytes, size_t length)
{
    if (writer == NULL || bytes == NULL || writer->failed) {
        return;
    }
    if (length >= writer->capacity - writer->length) {
        writer->failed = true;
        return;
    }
    memcpy(writer->buffer + writer->length, bytes, length);
    writer->length += length;
    writer->buffer[writer->length] = '\0';
}

static void writer_format(json_writer_t *writer, const char *format, ...)
{
    if (writer == NULL || format == NULL || writer->failed) {
        return;
    }
    va_list args;
    va_start(args, format);
    const int written = vsnprintf(writer->buffer + writer->length,
                                  writer->capacity - writer->length,
                                  format,
                                  args);
    va_end(args);
    if (written < 0 || (size_t)written >= writer->capacity - writer->length) {
        writer->failed = true;
        return;
    }
    writer->length += (size_t)written;
}

static bool continuation(uint8_t byte)
{
    return (byte & 0xC0U) == 0x80U;
}

static size_t valid_utf8_sequence(const uint8_t *bytes, size_t remaining)
{
    const uint8_t first = bytes[0];
    if (first < 0x80U) {
        return 1U;
    }
    if (first >= 0xC2U && first <= 0xDFU && remaining >= 2U &&
        continuation(bytes[1])) {
        return 2U;
    }
    if (remaining >= 3U && continuation(bytes[1]) && continuation(bytes[2])) {
        if ((first == 0xE0U && bytes[1] >= 0xA0U && bytes[1] <= 0xBFU) ||
            ((first >= 0xE1U && first <= 0xECU) ||
             (first >= 0xEEU && first <= 0xEFU)) ||
            (first == 0xEDU && bytes[1] >= 0x80U && bytes[1] <= 0x9FU)) {
            return 3U;
        }
    }
    if (remaining >= 4U && continuation(bytes[1]) && continuation(bytes[2]) &&
        continuation(bytes[3])) {
        if ((first == 0xF0U && bytes[1] >= 0x90U && bytes[1] <= 0xBFU) ||
            (first >= 0xF1U && first <= 0xF3U) ||
            (first == 0xF4U && bytes[1] >= 0x80U && bytes[1] <= 0x8FU)) {
            return 4U;
        }
    }
    return 0U;
}

static void writer_string(json_writer_t *writer, const char *text)
{
    writer_raw(writer, "\"");
    const uint8_t *bytes = (const uint8_t *)(text != NULL ? text : "");
    const size_t length = strlen((const char *)bytes);
    for (size_t index = 0; index < length && !writer->failed;) {
        const uint8_t byte = bytes[index];
        switch (byte) {
        case '"':
            writer_raw(writer, "\\\"");
            index++;
            continue;
        case '\\':
            writer_raw(writer, "\\\\");
            index++;
            continue;
        case '\b':
            writer_raw(writer, "\\b");
            index++;
            continue;
        case '\f':
            writer_raw(writer, "\\f");
            index++;
            continue;
        case '\n':
            writer_raw(writer, "\\n");
            index++;
            continue;
        case '\r':
            writer_raw(writer, "\\r");
            index++;
            continue;
        case '\t':
            writer_raw(writer, "\\t");
            index++;
            continue;
        default:
            break;
        }

        if (byte < 0x20U) {
            writer_format(writer, "\\u%04X", (unsigned int)byte);
            index++;
            continue;
        }
        const size_t sequence = valid_utf8_sequence(bytes + index, length - index);
        if (sequence == 0U) {
            writer_raw(writer, "\\uFFFD");
            index++;
            continue;
        }
        writer_bytes(writer, (const char *)bytes + index, sequence);
        index += sequence;
    }
    writer_raw(writer, "\"");
}

static const char *error_name(int error_code)
{
    switch (error_code) {
    case ANCS_PROTOCOL_ERR_ARGUMENT:
        return "invalid_argument";
    case ANCS_PROTOCOL_ERR_LENGTH:
        return "invalid_length";
    case ANCS_PROTOCOL_ERR_EVENT:
        return "invalid_event";
    case ANCS_PROTOCOL_ERR_COMMAND:
        return "invalid_command";
    case ANCS_PROTOCOL_ERR_UID_MISMATCH:
        return "uid_mismatch";
    case ANCS_PROTOCOL_ERR_ATTRIBUTE:
        return "invalid_attribute";
    case ANCS_PROTOCOL_ERR_OVERFLOW:
        return "overflow";
    case ANCS_PROTOCOL_ERR_SEQUENCE:
        return "invalid_sequence";
    case ANCS_PROTOCOL_ERR_CANCELED:
        return "canceled";
    case ANCS_PROTOCOL_ERR_TIMEOUT:
        return "timeout";
    case 0xA0:
        return "unknown_command";
    case 0xA1:
        return "invalid_ancs_command";
    case 0xA2:
        return "invalid_parameter";
    case 0xA3:
        return "action_failed";
    default:
        return "unknown";
    }
}

static const char *json_bool(bool value)
{
    return value ? "true" : "false";
}

int notification_sink_format_json(const ancs_notification_t *notification,
                                  const char *device_name,
                                  char *output,
                                  size_t output_capacity)
{
    if (notification == NULL || device_name == NULL || output == NULL ||
        output_capacity == 0U) {
        return -1;
    }
    output[0] = '\0';
    json_writer_t writer = {
        .buffer = output,
        .capacity = output_capacity,
    };

    writer_raw(&writer,
               "{\"schema_version\":1,\"target\":\"" ANCS_TARGET_ID
               "\",\"device_name\":");
    writer_string(&writer, device_name);
    writer_format(&writer,
                  ",\"session_id\":%" PRIu32 ",\"event\":",
                  notification->session_id);
    writer_string(&writer, ancs_event_name(notification->event_id));
    writer_format(&writer,
                  ",\"event_id\":%u,\"uid\":%" PRIu32
                  ",\"event_flags\":%u,\"silent\":%s,\"important\":%s"
                  ",\"pre_existing\":%s,\"positive_action_available\":%s"
                  ",\"negative_action_available\":%s,\"category_id\":%u,\"category\":",
                  (unsigned int)notification->event_id,
                  notification->uid,
                  (unsigned int)notification->event_flags,
                  json_bool(ancs_event_flag_is_set(notification->event_flags,
                                                   ANCS_EVENT_FLAG_SILENT)),
                  json_bool(ancs_event_flag_is_set(notification->event_flags,
                                                   ANCS_EVENT_FLAG_IMPORTANT)),
                  json_bool(ancs_event_flag_is_set(notification->event_flags,
                                                   ANCS_EVENT_FLAG_PRE_EXISTING)),
                  json_bool(ancs_event_flag_is_set(notification->event_flags,
                                                   ANCS_EVENT_FLAG_POSITIVE_ACTION)),
                  json_bool(ancs_event_flag_is_set(notification->event_flags,
                                                   ANCS_EVENT_FLAG_NEGATIVE_ACTION)),
                  (unsigned int)notification->category_id);
    writer_string(&writer, ancs_category_name(notification->category_id));
    writer_format(&writer,
                  ",\"category_count\":%u,\"app_id\":",
                  (unsigned int)notification->category_count);
    writer_string(&writer, notification->app_id);
    writer_raw(&writer, ",\"app_name\":");
    writer_string(&writer, notification->app_name);
    writer_raw(&writer, ",\"title\":");
    writer_string(&writer, notification->title);
    writer_raw(&writer, ",\"subtitle\":");
    writer_string(&writer, notification->subtitle);
    writer_raw(&writer, ",\"message\":");
    writer_string(&writer, notification->message);
    writer_raw(&writer, ",\"message_size\":");
    writer_string(&writer, notification->message_size_raw);
    writer_raw(&writer, ",\"date\":");
    writer_string(&writer, notification->date_raw);
    writer_format(&writer,
                  ",\"complete\":%s,\"truncated\":{\"app_id\":%s,\"app_name\":%s,\"title\":%s"
                  ",\"subtitle\":%s,\"message\":%s},\"error\":",
                  json_bool(notification->complete),
                  json_bool(notification->app_id_truncated),
                  json_bool(notification->app_name_truncated),
                  json_bool(notification->title_truncated),
                  json_bool(notification->subtitle_truncated),
                  json_bool(notification->message_truncated));
    if (notification->complete && notification->error_code == 0) {
        writer_raw(&writer, "null");
    } else {
        writer_format(&writer, "{\"code\":%d,\"name\":", notification->error_code);
        writer_string(&writer, error_name(notification->error_code));
        writer_raw(&writer, "}");
    }
    writer_format(&writer,
                  ",\"received_at_ms\":%" PRId64 "}",
                  notification->received_at_ms);
    return writer.failed ? -2 : 0;
}

int notification_sink_format_state_json(const char *state,
                                        uint32_t session_id,
                                        bool bonded,
                                        bool data_source_subscribed,
                                        bool notification_source_subscribed,
                                        int auth_error,
                                        char *output,
                                        size_t output_capacity)
{
    if (state == NULL || output == NULL || output_capacity == 0U) {
        return -1;
    }
    output[0] = '\0';
    json_writer_t writer = {
        .buffer = output,
        .capacity = output_capacity,
    };
    writer_raw(&writer, "{\"target\":\"" ANCS_TARGET_ID "\",\"state\":");
    writer_string(&writer, state);
    writer_format(&writer,
                  ",\"session_id\":%" PRIu32 ",\"bonded\":%s"
                  ",\"data_source_subscribed\":%s"
                  ",\"notification_source_subscribed\":%s,\"auth_error\":%d}",
                  session_id,
                  json_bool(bonded),
                  json_bool(data_source_subscribed),
                  json_bool(notification_source_subscribed),
                  auth_error);
    return writer.failed ? -2 : 0;
}

int notification_sink_publish(const ancs_notification_t *notification,
                              const char *device_name)
{
    if (notification == NULL || device_name == NULL) {
        return -1;
    }
    const size_t text_length = strlen(notification->app_id) +
                               strlen(notification->app_name) +
                               strlen(notification->title) +
                               strlen(notification->subtitle) +
                               strlen(notification->message) +
                               strlen(notification->message_size_raw) +
                               strlen(notification->date_raw) +
                               strlen(device_name);
    if (text_length > (SIZE_MAX - 2048U) / 6U) {
        return -1;
    }
    const size_t capacity = 2048U + (text_length * 6U);
    char *json = malloc(capacity);
    if (json == NULL) {
        return -1;
    }
    const int result =
        notification_sink_format_json(notification, device_name, json, capacity);
    if (result == 0) {
        printf("ANCS_NOTIFICATION_JSON %s\n", json);
        fflush(stdout);
        if (s_observer != NULL) {
            s_observer(notification, device_name, s_observer_context);
        }
    }
    free(json);
    return result;
}

esp_err_t notification_sink_register_observer(notification_sink_observer_t observer,
                                              void *context)
{
    s_observer = observer;
    s_observer_context = context;
    return ESP_OK;
}

int notification_sink_publish_state(const char *state,
                                    uint32_t session_id,
                                    bool bonded,
                                    bool data_source_subscribed,
                                    bool notification_source_subscribed,
                                    int auth_error)
{
    char json[768];
    const int result =
        notification_sink_format_state_json(state,
                                            session_id,
                                            bonded,
                                            data_source_subscribed,
                                            notification_source_subscribed,
                                            auth_error,
                                            json,
                                            sizeof(json));
    if (result == 0) {
        printf("ANCS_STATE_JSON %s\n", json);
        fflush(stdout);
    }
    return result;
}
