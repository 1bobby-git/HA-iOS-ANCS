#include "ancs_protocol.h"

#include <limits.h>
#include <string.h>

enum {
    PARSER_STATE_COMMAND = 0,
    PARSER_STATE_UID,
    PARSER_STATE_ATTRIBUTE_ID,
    PARSER_STATE_ATTRIBUTE_LENGTH,
    PARSER_STATE_ATTRIBUTE_VALUE,
    PARSER_STATE_COMPLETE,
    PARSER_STATE_ERROR,
};

enum {
    APP_PARSER_STATE_COMMAND = 0,
    APP_PARSER_STATE_APP_ID,
    APP_PARSER_STATE_ATTRIBUTE_ID,
    APP_PARSER_STATE_ATTRIBUTE_LENGTH,
    APP_PARSER_STATE_ATTRIBUTE_VALUE,
    APP_PARSER_STATE_COMPLETE,
    APP_PARSER_STATE_ERROR,
};

static uint32_t read_u32_le(const uint8_t *bytes)
{
    return ((uint32_t)bytes[0]) |
           ((uint32_t)bytes[1] << 8U) |
           ((uint32_t)bytes[2] << 16U) |
           ((uint32_t)bytes[3] << 24U);
}

static ancs_parser_result_t parser_fail(ancs_data_parser_t *parser, int error_code)
{
    if (parser != NULL) {
        parser->state = PARSER_STATE_ERROR;
        parser->error_code = error_code;
        if (parser->notification != NULL) {
            parser->notification->complete = false;
            parser->notification->error_code = error_code;
        }
    }
    return ANCS_PARSER_ERROR;
}

static ancs_parser_result_t app_parser_fail(ancs_app_data_parser_t *parser,
                                            int error_code)
{
    if (parser != NULL) {
        parser->state = APP_PARSER_STATE_ERROR;
        parser->error_code = error_code;
        if (parser->notification != NULL) {
            parser->notification->app_name[0] = '\0';
            parser->notification->app_name_truncated = false;
        }
    }
    return ANCS_PARSER_ERROR;
}

static void attribute_target(ancs_data_parser_t *parser,
                             char **target,
                             size_t *capacity,
                             bool **truncated)
{
    ancs_notification_t *notification = parser->notification;
    *target = NULL;
    *capacity = 0;
    *truncated = NULL;

    switch (parser->attribute_id) {
    case 0:
        *target = notification->app_id;
        *capacity = CONFIG_ANCS_APP_ID_MAX;
        *truncated = &notification->app_id_truncated;
        break;
    case 1:
        *target = notification->title;
        *capacity = CONFIG_ANCS_TITLE_MAX;
        *truncated = &notification->title_truncated;
        break;
    case 2:
        *target = notification->subtitle;
        *capacity = CONFIG_ANCS_SUBTITLE_MAX;
        *truncated = &notification->subtitle_truncated;
        break;
    case 3:
        *target = notification->message;
        *capacity = CONFIG_ANCS_MESSAGE_MAX;
        *truncated = &notification->message_truncated;
        break;
    case 4:
        *target = notification->message_size_raw;
        *capacity = sizeof(notification->message_size_raw) - 1U;
        break;
    case 5:
        *target = notification->date_raw;
        *capacity = CONFIG_ANCS_DATE_MAX;
        break;
    default:
        break;
    }
}

static ancs_parser_result_t finish_attribute(ancs_data_parser_t *parser)
{
    char *target = NULL;
    size_t capacity = 0;
    bool *truncated = NULL;
    attribute_target(parser, &target, &capacity, &truncated);
    if (target == NULL) {
        return parser_fail(parser, ANCS_PROTOCOL_ERR_ATTRIBUTE);
    }

    const size_t terminator_index =
        parser->attribute_length < capacity ? parser->attribute_length : capacity;
    target[terminator_index] = '\0';
    if ((size_t)parser->attribute_length > capacity) {
        if (truncated != NULL) {
            *truncated = true;
        } else {
            return parser_fail(parser, ANCS_PROTOCOL_ERR_OVERFLOW);
        }
    }

    const uint32_t bit = 1U << parser->attribute_id;
    parser->received_mask |= bit;
    if ((parser->received_mask & parser->expected_mask) == parser->expected_mask) {
        parser->notification->complete = true;
        parser->notification->error_code = ANCS_PROTOCOL_OK;
        parser->state = PARSER_STATE_COMPLETE;
        return ANCS_PARSER_COMPLETE;
    }

    parser->state = PARSER_STATE_ATTRIBUTE_ID;
    parser->attribute_length = 0;
    parser->attribute_read = 0;
    parser->length_bytes_read = 0;
    return ANCS_PARSER_MORE;
}

ancs_protocol_error_t ancs_parse_notification_source(
    const uint8_t *frame,
    size_t length,
    ancs_notification_event_t *event)
{
    if (frame == NULL || event == NULL) {
        return ANCS_PROTOCOL_ERR_ARGUMENT;
    }
    if (length != 8U) {
        return ANCS_PROTOCOL_ERR_LENGTH;
    }
    if (frame[0] > 2U) {
        return ANCS_PROTOCOL_ERR_EVENT;
    }

    event->event_id = frame[0];
    event->event_flags = frame[1];
    event->category_id = frame[2];
    event->category_count = frame[3];
    event->uid = read_u32_le(&frame[4]);
    return ANCS_PROTOCOL_OK;
}

bool ancs_event_flag_is_set(uint8_t flags, ancs_event_flag_t flag)
{
    return (flags & (uint8_t)flag) != 0U;
}

const char *ancs_event_name(uint8_t event_id)
{
    static const char *const names[] = {"added", "modified", "removed"};
    return event_id < (sizeof(names) / sizeof(names[0])) ? names[event_id] : "unknown";
}

const char *ancs_category_name(uint8_t category_id)
{
    static const char *const names[] = {
        "other",
        "incoming_call",
        "missed_call",
        "voicemail",
        "social",
        "schedule",
        "email",
        "news",
        "health_and_fitness",
        "business_and_finance",
        "location",
        "entertainment",
    };
    return category_id < (sizeof(names) / sizeof(names[0]))
               ? names[category_id]
               : "reserved";
}

void ancs_notification_init(ancs_notification_t *notification,
                            uint32_t session_id,
                            const ancs_notification_event_t *event,
                            int64_t received_at_ms)
{
    if (notification == NULL) {
        return;
    }
    memset(notification, 0, sizeof(*notification));
    notification->session_id = session_id;
    notification->received_at_ms = received_at_ms;
    if (event != NULL) {
        notification->uid = event->uid;
        notification->event_id = event->event_id;
        notification->event_flags = event->event_flags;
        notification->category_id = event->category_id;
        notification->category_count = event->category_count;
    }
}

ancs_protocol_error_t ancs_build_get_notification_attributes(
    uint32_t uid,
    uint8_t *output,
    size_t output_capacity,
    size_t *output_length)
{
    if (output == NULL || output_length == NULL) {
        return ANCS_PROTOCOL_ERR_ARGUMENT;
    }

    const size_t required = 17U;
    if (output_capacity < required) {
        *output_length = 0;
        return ANCS_PROTOCOL_ERR_OVERFLOW;
    }

    const uint16_t title_max = (uint16_t)CONFIG_ANCS_TITLE_MAX;
    const uint16_t subtitle_max = (uint16_t)CONFIG_ANCS_SUBTITLE_MAX;
    const uint16_t message_max = (uint16_t)CONFIG_ANCS_MESSAGE_MAX;
    const uint8_t command[] = {
        ANCS_COMMAND_GET_NOTIFICATION_ATTRIBUTES,
        (uint8_t)(uid & 0xFFU),
        (uint8_t)((uid >> 8U) & 0xFFU),
        (uint8_t)((uid >> 16U) & 0xFFU),
        (uint8_t)((uid >> 24U) & 0xFFU),
        0x00,
        0x01,
        (uint8_t)(title_max & 0xFFU),
        (uint8_t)(title_max >> 8U),
        0x02,
        (uint8_t)(subtitle_max & 0xFFU),
        (uint8_t)(subtitle_max >> 8U),
        0x03,
        (uint8_t)(message_max & 0xFFU),
        (uint8_t)(message_max >> 8U),
        0x04,
        0x05,
    };
    memcpy(output, command, sizeof(command));
    *output_length = sizeof(command);
    return ANCS_PROTOCOL_OK;
}

ancs_protocol_error_t ancs_build_get_app_attributes(
    const char *app_id,
    uint8_t *output,
    size_t output_capacity,
    size_t *output_length)
{
    if (app_id == NULL || output == NULL || output_length == NULL) {
        return ANCS_PROTOCOL_ERR_ARGUMENT;
    }
    *output_length = 0U;

    const size_t app_id_length = strnlen(app_id, CONFIG_ANCS_APP_ID_MAX + 1U);
    if (app_id_length == 0U) {
        return ANCS_PROTOCOL_ERR_ARGUMENT;
    }
    if (app_id_length > CONFIG_ANCS_APP_ID_MAX) {
        return ANCS_PROTOCOL_ERR_LENGTH;
    }

    const size_t required = app_id_length + 3U;
    if (output_capacity < required) {
        return ANCS_PROTOCOL_ERR_LENGTH;
    }

    output[0] = ANCS_COMMAND_GET_APP_ATTRIBUTES;
    memcpy(output + 1U, app_id, app_id_length + 1U);
    output[required - 1U] = ANCS_APP_ATTRIBUTE_DISPLAY_NAME;
    *output_length = required;
    return ANCS_PROTOCOL_OK;
}

void ancs_data_parser_init(ancs_data_parser_t *parser,
                           ancs_notification_t *notification,
                           uint32_t expected_uid,
                           uint32_t expected_mask)
{
    if (parser == NULL) {
        return;
    }
    memset(parser, 0, sizeof(*parser));
    parser->notification = notification;
    parser->expected_uid = expected_uid;
    parser->expected_mask = expected_mask & ANCS_ATTR_MASK_REQUIRED;
    parser->state = PARSER_STATE_COMMAND;
    if (notification == NULL || parser->expected_mask == 0U) {
        (void)parser_fail(parser, ANCS_PROTOCOL_ERR_ARGUMENT);
    }
}

ancs_parser_result_t ancs_data_parser_feed(ancs_data_parser_t *parser,
                                           const uint8_t *bytes,
                                           size_t length)
{
    if (parser == NULL || (bytes == NULL && length != 0U)) {
        return parser_fail(parser, ANCS_PROTOCOL_ERR_ARGUMENT);
    }
    if (parser->state == PARSER_STATE_ERROR) {
        return ANCS_PARSER_ERROR;
    }
    if (parser->state == PARSER_STATE_COMPLETE) {
        return length == 0U ? ANCS_PARSER_COMPLETE
                            : parser_fail(parser, ANCS_PROTOCOL_ERR_SEQUENCE);
    }

    for (size_t index = 0; index < length; ++index) {
        const uint8_t byte = bytes[index];
        switch (parser->state) {
        case PARSER_STATE_COMMAND:
            if (byte != 0x00U) {
                return parser_fail(parser, ANCS_PROTOCOL_ERR_COMMAND);
            }
            parser->response_uid = 0U;
            parser->uid_bytes_read = 0U;
            parser->state = PARSER_STATE_UID;
            break;

        case PARSER_STATE_UID:
            parser->response_uid |=
                ((uint32_t)byte << (8U * parser->uid_bytes_read));
            parser->uid_bytes_read++;
            if (parser->uid_bytes_read == 4U) {
                if (parser->response_uid != parser->expected_uid) {
                    return parser_fail(parser, ANCS_PROTOCOL_ERR_UID_MISMATCH);
                }
                parser->state = PARSER_STATE_ATTRIBUTE_ID;
            }
            break;

        case PARSER_STATE_ATTRIBUTE_ID: {
            if (byte > 5U) {
                return parser_fail(parser, ANCS_PROTOCOL_ERR_ATTRIBUTE);
            }
            const uint32_t bit = 1U << byte;
            if ((parser->expected_mask & bit) == 0U ||
                (parser->received_mask & bit) != 0U) {
                return parser_fail(parser, ANCS_PROTOCOL_ERR_SEQUENCE);
            }
            parser->attribute_id = byte;
            parser->attribute_length = 0U;
            parser->attribute_read = 0U;
            parser->length_bytes_read = 0U;
            parser->state = PARSER_STATE_ATTRIBUTE_LENGTH;
            break;
        }

        case PARSER_STATE_ATTRIBUTE_LENGTH:
            parser->attribute_length |=
                (uint16_t)((uint16_t)byte << (8U * parser->length_bytes_read));
            parser->length_bytes_read++;
            if (parser->length_bytes_read == 2U) {
                if (parser->attribute_length == 0U) {
                    const ancs_parser_result_t result = finish_attribute(parser);
                    if (result != ANCS_PARSER_MORE) {
                        if (result == ANCS_PARSER_COMPLETE && index + 1U < length) {
                            return parser_fail(parser, ANCS_PROTOCOL_ERR_SEQUENCE);
                        }
                        return result;
                    }
                } else {
                    parser->state = PARSER_STATE_ATTRIBUTE_VALUE;
                }
            }
            break;

        case PARSER_STATE_ATTRIBUTE_VALUE: {
            char *target = NULL;
            size_t capacity = 0;
            bool *truncated = NULL;
            attribute_target(parser, &target, &capacity, &truncated);
            (void)truncated;
            if (target == NULL) {
                return parser_fail(parser, ANCS_PROTOCOL_ERR_ATTRIBUTE);
            }
            if ((size_t)parser->attribute_read < capacity) {
                target[parser->attribute_read] = (char)byte;
            }
            parser->attribute_read++;
            if (parser->attribute_read == parser->attribute_length) {
                const ancs_parser_result_t result = finish_attribute(parser);
                if (result != ANCS_PARSER_MORE) {
                    if (result == ANCS_PARSER_COMPLETE && index + 1U < length) {
                        return parser_fail(parser, ANCS_PROTOCOL_ERR_SEQUENCE);
                    }
                    return result;
                }
            }
            break;
        }

        default:
            return parser_fail(parser, ANCS_PROTOCOL_ERR_SEQUENCE);
        }
    }

    return parser->state == PARSER_STATE_COMPLETE ? ANCS_PARSER_COMPLETE
                                                   : ANCS_PARSER_MORE;
}

static ancs_parser_result_t finish_app_attribute(
    ancs_app_data_parser_t *parser)
{
    if (parser->attribute_id != ANCS_APP_ATTRIBUTE_DISPLAY_NAME ||
        parser->notification == NULL) {
        return app_parser_fail(parser, ANCS_PROTOCOL_ERR_ATTRIBUTE);
    }

    const size_t terminator_index =
        parser->attribute_length < CONFIG_ANCS_APP_NAME_MAX
            ? parser->attribute_length
            : CONFIG_ANCS_APP_NAME_MAX;
    parser->notification->app_name[terminator_index] = '\0';
    parser->notification->app_name_truncated =
        (size_t)parser->attribute_length > CONFIG_ANCS_APP_NAME_MAX;
    parser->state = APP_PARSER_STATE_COMPLETE;
    parser->error_code = ANCS_PROTOCOL_OK;
    return ANCS_PARSER_COMPLETE;
}

void ancs_app_data_parser_init(ancs_app_data_parser_t *parser,
                               ancs_notification_t *notification)
{
    if (parser == NULL) {
        return;
    }
    memset(parser, 0, sizeof(*parser));
    parser->notification = notification;
    parser->state = APP_PARSER_STATE_COMMAND;
    if (notification == NULL || notification->app_id[0] == '\0') {
        (void)app_parser_fail(parser, ANCS_PROTOCOL_ERR_ARGUMENT);
        return;
    }
    notification->app_name[0] = '\0';
    notification->app_name_truncated = false;
}

ancs_parser_result_t ancs_app_data_parser_feed(ancs_app_data_parser_t *parser,
                                               const uint8_t *bytes,
                                               size_t length)
{
    if (parser == NULL || (bytes == NULL && length != 0U)) {
        return app_parser_fail(parser, ANCS_PROTOCOL_ERR_ARGUMENT);
    }
    if (parser->state == APP_PARSER_STATE_ERROR) {
        return ANCS_PARSER_ERROR;
    }
    if (parser->state == APP_PARSER_STATE_COMPLETE) {
        return length == 0U
                   ? ANCS_PARSER_COMPLETE
                   : app_parser_fail(parser, ANCS_PROTOCOL_ERR_SEQUENCE);
    }

    for (size_t index = 0; index < length; ++index) {
        const uint8_t byte = bytes[index];
        switch (parser->state) {
        case APP_PARSER_STATE_COMMAND:
            if (byte != ANCS_COMMAND_GET_APP_ATTRIBUTES) {
                return app_parser_fail(parser, ANCS_PROTOCOL_ERR_COMMAND);
            }
            parser->state = APP_PARSER_STATE_APP_ID;
            break;

        case APP_PARSER_STATE_APP_ID:
            if (byte == 0U) {
                parser->response_app_id[parser->response_app_id_read] = '\0';
                if (strcmp(parser->response_app_id,
                           parser->notification->app_id) != 0) {
                    return app_parser_fail(
                        parser, ANCS_PROTOCOL_ERR_APP_ID_MISMATCH);
                }
                parser->state = APP_PARSER_STATE_ATTRIBUTE_ID;
                break;
            }
            if (parser->response_app_id_read >= CONFIG_ANCS_APP_ID_MAX) {
                return app_parser_fail(parser, ANCS_PROTOCOL_ERR_OVERFLOW);
            }
            parser->response_app_id[parser->response_app_id_read++] = (char)byte;
            break;

        case APP_PARSER_STATE_ATTRIBUTE_ID:
            if (byte != ANCS_APP_ATTRIBUTE_DISPLAY_NAME) {
                return app_parser_fail(parser, ANCS_PROTOCOL_ERR_ATTRIBUTE);
            }
            parser->attribute_id = byte;
            parser->attribute_length = 0U;
            parser->attribute_read = 0U;
            parser->length_bytes_read = 0U;
            parser->state = APP_PARSER_STATE_ATTRIBUTE_LENGTH;
            break;

        case APP_PARSER_STATE_ATTRIBUTE_LENGTH:
            parser->attribute_length |=
                (uint16_t)((uint16_t)byte <<
                           (8U * parser->length_bytes_read));
            parser->length_bytes_read++;
            if (parser->length_bytes_read == 2U) {
                if (parser->attribute_length == 0U) {
                    const ancs_parser_result_t result =
                        finish_app_attribute(parser);
                    if (result == ANCS_PARSER_COMPLETE && index + 1U < length) {
                        return app_parser_fail(
                            parser, ANCS_PROTOCOL_ERR_SEQUENCE);
                    }
                    return result;
                }
                parser->state = APP_PARSER_STATE_ATTRIBUTE_VALUE;
            }
            break;

        case APP_PARSER_STATE_ATTRIBUTE_VALUE:
            if ((size_t)parser->attribute_read < CONFIG_ANCS_APP_NAME_MAX) {
                parser->notification->app_name[parser->attribute_read] =
                    (char)byte;
            }
            parser->attribute_read++;
            if (parser->attribute_read == parser->attribute_length) {
                const ancs_parser_result_t result =
                    finish_app_attribute(parser);
                if (result == ANCS_PARSER_COMPLETE && index + 1U < length) {
                    return app_parser_fail(parser, ANCS_PROTOCOL_ERR_SEQUENCE);
                }
                return result;
            }
            break;

        default:
            return app_parser_fail(parser, ANCS_PROTOCOL_ERR_SEQUENCE);
        }
    }

    return parser->state == APP_PARSER_STATE_COMPLETE ? ANCS_PARSER_COMPLETE
                                                       : ANCS_PARSER_MORE;
}

void ancs_request_queue_init(ancs_request_queue_t *queue)
{
    if (queue != NULL) {
        memset(queue, 0, sizeof(*queue));
    }
}

bool ancs_request_queue_push(ancs_request_queue_t *queue,
                             const ancs_notification_event_t *event)
{
    if (queue == NULL || event == NULL ||
        queue->count >= CONFIG_ANCS_REQUEST_QUEUE_CAPACITY) {
        return false;
    }
    const size_t tail =
        (queue->head + queue->count) % CONFIG_ANCS_REQUEST_QUEUE_CAPACITY;
    queue->items[tail] = *event;
    queue->count++;
    return true;
}

bool ancs_request_queue_pop(ancs_request_queue_t *queue,
                            ancs_notification_event_t *event)
{
    if (queue == NULL || event == NULL || queue->count == 0U) {
        return false;
    }
    *event = queue->items[queue->head];
    queue->head = (queue->head + 1U) % CONFIG_ANCS_REQUEST_QUEUE_CAPACITY;
    queue->count--;
    return true;
}

bool ancs_request_queue_cancel_uid(ancs_request_queue_t *queue, uint32_t uid)
{
    if (queue == NULL || queue->count == 0U) {
        return false;
    }

    size_t write_count = 0U;
    bool removed = false;
    const size_t original_count = queue->count;
    for (size_t index = 0; index < original_count; ++index) {
        const size_t source =
            (queue->head + index) % CONFIG_ANCS_REQUEST_QUEUE_CAPACITY;
        if (queue->items[source].uid == uid) {
            removed = true;
            continue;
        }
        queue->items[write_count++] = queue->items[source];
    }
    queue->head = 0U;
    queue->count = write_count;
    return removed;
}

void ancs_request_queue_clear(ancs_request_queue_t *queue)
{
    ancs_request_queue_init(queue);
}
