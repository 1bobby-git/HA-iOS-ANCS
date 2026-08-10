#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifndef CONFIG_ANCS_APP_ID_MAX
#define CONFIG_ANCS_APP_ID_MAX 256
#endif
#ifndef CONFIG_ANCS_APP_NAME_MAX
#define CONFIG_ANCS_APP_NAME_MAX 256
#endif
#ifndef CONFIG_ANCS_TITLE_MAX
#define CONFIG_ANCS_TITLE_MAX 512
#endif
#ifndef CONFIG_ANCS_SUBTITLE_MAX
#define CONFIG_ANCS_SUBTITLE_MAX 512
#endif
#ifndef CONFIG_ANCS_MESSAGE_MAX
#define CONFIG_ANCS_MESSAGE_MAX 4096
#endif
#ifndef CONFIG_ANCS_DATE_MAX
#define CONFIG_ANCS_DATE_MAX 32
#endif
#ifndef CONFIG_ANCS_REQUEST_QUEUE_CAPACITY
#define CONFIG_ANCS_REQUEST_QUEUE_CAPACITY 16
#endif

#define ANCS_ATTR_MASK_APP_ID (1U << 0)
#define ANCS_ATTR_MASK_TITLE (1U << 1)
#define ANCS_ATTR_MASK_SUBTITLE (1U << 2)
#define ANCS_ATTR_MASK_MESSAGE (1U << 3)
#define ANCS_ATTR_MASK_MESSAGE_SIZE (1U << 4)
#define ANCS_ATTR_MASK_DATE (1U << 5)
#define ANCS_ATTR_MASK_REQUIRED ((1U << 6) - 1U)

#define ANCS_COMMAND_GET_NOTIFICATION_ATTRIBUTES 0U
#define ANCS_COMMAND_GET_APP_ATTRIBUTES 1U
#define ANCS_APP_ATTRIBUTE_DISPLAY_NAME 0U

typedef enum {
    ANCS_PROTOCOL_OK = 0,
    ANCS_PROTOCOL_ERR_ARGUMENT = -1,
    ANCS_PROTOCOL_ERR_LENGTH = -2,
    ANCS_PROTOCOL_ERR_EVENT = -3,
    ANCS_PROTOCOL_ERR_COMMAND = -4,
    ANCS_PROTOCOL_ERR_UID_MISMATCH = -5,
    ANCS_PROTOCOL_ERR_ATTRIBUTE = -6,
    ANCS_PROTOCOL_ERR_OVERFLOW = -7,
    ANCS_PROTOCOL_ERR_SEQUENCE = -8,
    ANCS_PROTOCOL_ERR_CANCELED = -9,
    ANCS_PROTOCOL_ERR_TIMEOUT = -10,
    ANCS_PROTOCOL_ERR_APP_ID_MISMATCH = -11,
} ancs_protocol_error_t;

typedef enum {
    ANCS_EVENT_FLAG_SILENT = (1U << 0),
    ANCS_EVENT_FLAG_IMPORTANT = (1U << 1),
    ANCS_EVENT_FLAG_PRE_EXISTING = (1U << 2),
    ANCS_EVENT_FLAG_POSITIVE_ACTION = (1U << 3),
    ANCS_EVENT_FLAG_NEGATIVE_ACTION = (1U << 4),
} ancs_event_flag_t;

typedef struct {
    uint8_t event_id;
    uint8_t event_flags;
    uint8_t category_id;
    uint8_t category_count;
    uint32_t uid;
} ancs_notification_event_t;

typedef struct {
    uint32_t session_id;
    uint32_t uid;
    uint8_t event_id;
    uint8_t event_flags;
    uint8_t category_id;
    uint8_t category_count;
    char app_id[CONFIG_ANCS_APP_ID_MAX + 1];
    char app_name[CONFIG_ANCS_APP_NAME_MAX + 1];
    char title[CONFIG_ANCS_TITLE_MAX + 1];
    char subtitle[CONFIG_ANCS_SUBTITLE_MAX + 1];
    char message[CONFIG_ANCS_MESSAGE_MAX + 1];
    char message_size_raw[24];
    char date_raw[CONFIG_ANCS_DATE_MAX + 1];
    bool complete;
    bool app_id_truncated;
    bool app_name_truncated;
    bool title_truncated;
    bool subtitle_truncated;
    bool message_truncated;
    int error_code;
    int64_t received_at_ms;
} ancs_notification_t;

typedef enum {
    ANCS_PARSER_MORE = 0,
    ANCS_PARSER_COMPLETE = 1,
    ANCS_PARSER_ERROR = -1,
} ancs_parser_result_t;

typedef struct {
    ancs_notification_t *notification;
    uint32_t expected_uid;
    uint32_t expected_mask;
    uint32_t received_mask;
    uint32_t response_uid;
    uint16_t attribute_length;
    uint16_t attribute_read;
    uint8_t state;
    uint8_t uid_bytes_read;
    uint8_t attribute_id;
    uint8_t length_bytes_read;
    int error_code;
} ancs_data_parser_t;

typedef struct {
    ancs_notification_t *notification;
    char response_app_id[CONFIG_ANCS_APP_ID_MAX + 1];
    size_t response_app_id_read;
    uint16_t attribute_length;
    uint16_t attribute_read;
    uint8_t state;
    uint8_t attribute_id;
    uint8_t length_bytes_read;
    int error_code;
} ancs_app_data_parser_t;

typedef struct {
    ancs_notification_event_t items[CONFIG_ANCS_REQUEST_QUEUE_CAPACITY];
    size_t head;
    size_t count;
} ancs_request_queue_t;

ancs_protocol_error_t ancs_parse_notification_source(
    const uint8_t *frame,
    size_t length,
    ancs_notification_event_t *event);
bool ancs_event_flag_is_set(uint8_t flags, ancs_event_flag_t flag);
const char *ancs_event_name(uint8_t event_id);
const char *ancs_category_name(uint8_t category_id);
void ancs_notification_init(ancs_notification_t *notification,
                            uint32_t session_id,
                            const ancs_notification_event_t *event,
                            int64_t received_at_ms);
ancs_protocol_error_t ancs_build_get_notification_attributes(
    uint32_t uid,
    uint8_t *output,
    size_t output_capacity,
    size_t *output_length);
ancs_protocol_error_t ancs_build_get_app_attributes(
    const char *app_id,
    uint8_t *output,
    size_t output_capacity,
    size_t *output_length);
void ancs_data_parser_init(ancs_data_parser_t *parser,
                           ancs_notification_t *notification,
                           uint32_t expected_uid,
                           uint32_t expected_mask);
ancs_parser_result_t ancs_data_parser_feed(ancs_data_parser_t *parser,
                                           const uint8_t *bytes,
                                           size_t length);
void ancs_app_data_parser_init(ancs_app_data_parser_t *parser,
                               ancs_notification_t *notification);
ancs_parser_result_t ancs_app_data_parser_feed(ancs_app_data_parser_t *parser,
                                               const uint8_t *bytes,
                                               size_t length);
void ancs_request_queue_init(ancs_request_queue_t *queue);
bool ancs_request_queue_push(ancs_request_queue_t *queue,
                             const ancs_notification_event_t *event);
bool ancs_request_queue_pop(ancs_request_queue_t *queue,
                            ancs_notification_event_t *event);
bool ancs_request_queue_cancel_uid(ancs_request_queue_t *queue, uint32_t uid);
void ancs_request_queue_clear(ancs_request_queue_t *queue);
