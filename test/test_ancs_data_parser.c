#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "ancs_protocol.h"
#include "unity.h"

typedef struct {
    uint8_t *bytes;
    size_t length;
    size_t capacity;
} fixture_builder_t;

static void fixture_append(fixture_builder_t *fixture, const void *source, size_t length)
{
    TEST_ASSERT_NOT_NULL(fixture);
    TEST_ASSERT_LESS_OR_EQUAL_size_t(fixture->capacity - fixture->length, length);
    memcpy(fixture->bytes + fixture->length, source, length);
    fixture->length += length;
}

static void fixture_append_u8(fixture_builder_t *fixture, uint8_t value)
{
    fixture_append(fixture, &value, sizeof(value));
}

static void fixture_begin(fixture_builder_t *fixture, uint32_t uid)
{
    const uint8_t header[5] = {
        0x00,
        (uint8_t)(uid & 0xFF),
        (uint8_t)((uid >> 8) & 0xFF),
        (uint8_t)((uid >> 16) & 0xFF),
        (uint8_t)((uid >> 24) & 0xFF),
    };
    fixture_append(fixture, header, sizeof(header));
}

static void fixture_begin_app(fixture_builder_t *fixture, const char *app_id)
{
    fixture_append_u8(fixture, 0x01);
    fixture_append(fixture, app_id, strlen(app_id) + 1U);
}

static void fixture_attribute_bytes(fixture_builder_t *fixture,
                                    uint8_t attribute_id,
                                    const uint8_t *value,
                                    size_t value_length)
{
    TEST_ASSERT_LESS_OR_EQUAL_UINT16(UINT16_MAX, value_length);
    fixture_append_u8(fixture, attribute_id);
    fixture_append_u8(fixture, (uint8_t)(value_length & 0xFF));
    fixture_append_u8(fixture, (uint8_t)((value_length >> 8) & 0xFF));
    fixture_append(fixture, value, value_length);
}

static void fixture_attribute(fixture_builder_t *fixture,
                              uint8_t attribute_id,
                              const char *value)
{
    fixture_attribute_bytes(fixture,
                            attribute_id,
                            (const uint8_t *)value,
                            strlen(value));
}

static void make_complete_fixture(fixture_builder_t *fixture, uint32_t uid)
{
    fixture_begin(fixture, uid);
    fixture_attribute(fixture, 0, "com.apple.MobileSMS");
    fixture_attribute(fixture, 1, "택배 도착");
    fixture_attribute(fixture, 2, "");
    fixture_attribute(fixture, 3, "현관 앞에 두었습니다.");
    fixture_attribute(fixture, 4, "29");
    fixture_attribute(fixture, 5, "20260728T164500");
}

static void make_app_fixture(fixture_builder_t *fixture,
                             const char *app_id,
                             const uint8_t *display_name,
                             size_t display_name_length)
{
    fixture_begin_app(fixture, app_id);
    fixture_attribute_bytes(fixture,
                            ANCS_APP_ATTRIBUTE_DISPLAY_NAME,
                            display_name,
                            display_name_length);
}

static void init_notification(ancs_notification_t *notification, uint32_t uid)
{
    const ancs_notification_event_t event = {
        .event_id = 0,
        .event_flags = 0x02,
        .category_id = 4,
        .category_count = 1,
        .uid = uid,
    };
    ancs_notification_init(notification, 7, &event, 123456);
}

static ancs_parser_result_t feed_complete_fixture(const uint8_t *bytes,
                                                  size_t length,
                                                  size_t first_length,
                                                  ancs_notification_t *notification,
                                                  uint32_t uid)
{
    ancs_data_parser_t parser;
    init_notification(notification, uid);
    ancs_data_parser_init(&parser, notification, uid, ANCS_ATTR_MASK_REQUIRED);

    ancs_parser_result_t result = ancs_data_parser_feed(&parser, bytes, first_length);
    if (result == ANCS_PARSER_ERROR) {
        return result;
    }
    return ancs_data_parser_feed(&parser,
                                 bytes + first_length,
                                 length - first_length);
}

static ancs_parser_result_t feed_app_fixture(const uint8_t *bytes,
                                             size_t length,
                                             size_t first_length,
                                             ancs_notification_t *notification,
                                             const char *app_id)
{
    memset(notification, 0, sizeof(*notification));
    strcpy(notification->app_id, app_id);
    ancs_app_data_parser_t parser;
    ancs_app_data_parser_init(&parser, notification);

    ancs_parser_result_t result =
        ancs_app_data_parser_feed(&parser, bytes, first_length);
    if (result == ANCS_PARSER_ERROR) {
        return result;
    }
    return ancs_app_data_parser_feed(&parser,
                                     bytes + first_length,
                                     length - first_length);
}

TEST_CASE("attribute request contains only get-attributes command and required fields",
          "[ancs][control_point]")
{
    uint8_t request[32] = {0};
    size_t request_length = 0;

    TEST_ASSERT_EQUAL(ANCS_PROTOCOL_OK,
                      ancs_build_get_notification_attributes(0x12345678,
                                                             request,
                                                             sizeof(request),
                                                             &request_length));
    const uint8_t expected[] = {
        0x00, 0x78, 0x56, 0x34, 0x12,
        0x00,
        0x01, (uint8_t)(CONFIG_ANCS_TITLE_MAX & 0xFF),
        (uint8_t)((CONFIG_ANCS_TITLE_MAX >> 8) & 0xFF),
        0x02, (uint8_t)(CONFIG_ANCS_SUBTITLE_MAX & 0xFF),
        (uint8_t)((CONFIG_ANCS_SUBTITLE_MAX >> 8) & 0xFF),
        0x03, (uint8_t)(CONFIG_ANCS_MESSAGE_MAX & 0xFF),
        (uint8_t)((CONFIG_ANCS_MESSAGE_MAX >> 8) & 0xFF),
        0x04,
        0x05,
    };
    TEST_ASSERT_EQUAL_size_t(sizeof(expected), request_length);
    TEST_ASSERT_EQUAL_UINT8_ARRAY(expected, request, sizeof(expected));
}

TEST_CASE("app attribute request asks only for display name",
          "[ancs][control_point]")
{
    uint8_t request[64] = {0};
    size_t request_length = 0;

    TEST_ASSERT_EQUAL(
        ANCS_PROTOCOL_OK,
        ancs_build_get_app_attributes("com.example.chat",
                                      request,
                                      sizeof(request),
                                      &request_length));
    const uint8_t expected[] = {
        0x01,
        'c', 'o', 'm', '.', 'e', 'x', 'a', 'm', 'p', 'l', 'e', '.',
        'c', 'h', 'a', 't', 0x00,
        0x00,
    };
    TEST_ASSERT_EQUAL_size_t(sizeof(expected), request_length);
    TEST_ASSERT_EQUAL_UINT8_ARRAY(expected, request, sizeof(expected));

    TEST_ASSERT_EQUAL(
        ANCS_PROTOCOL_ERR_ARGUMENT,
        ancs_build_get_app_attributes("", request, sizeof(request), &request_length));
    TEST_ASSERT_EQUAL(
        ANCS_PROTOCOL_ERR_LENGTH,
        ancs_build_get_app_attributes("com.example.chat",
                                      request,
                                      sizeof(expected) - 1U,
                                      &request_length));
}

TEST_CASE("app parser reconstructs UTF-8 display name at every split",
          "[ancs][app_parser]")
{
    static const uint8_t display_name[] = {
        0xEC, 0xB9, 0xB4, 0xEC, 0xB9, 0xB4,
        0xEC, 0x98, 0xA4, 0xED, 0x86, 0xA1,
    };
    uint8_t storage[128] = {0};
    fixture_builder_t fixture = {.bytes = storage, .capacity = sizeof(storage)};
    make_app_fixture(&fixture,
                     "com.iwilab.KakaoTalk",
                     display_name,
                     sizeof(display_name));

    for (size_t split = 0; split <= fixture.length; ++split) {
        ancs_notification_t notification;
        TEST_ASSERT_EQUAL(
            ANCS_PARSER_COMPLETE,
            feed_app_fixture(storage,
                             fixture.length,
                             split,
                             &notification,
                             "com.iwilab.KakaoTalk"));
        TEST_ASSERT_EQUAL_MEMORY(display_name,
                                 notification.app_name,
                                 sizeof(display_name));
        TEST_ASSERT_EQUAL_CHAR('\0', notification.app_name[sizeof(display_name)]);
        TEST_ASSERT_FALSE(notification.app_name_truncated);
    }
}

TEST_CASE("app parser handles one byte at a time and empty names",
          "[ancs][app_parser]")
{
    uint8_t storage[128] = {0};
    fixture_builder_t fixture = {.bytes = storage, .capacity = sizeof(storage)};
    make_app_fixture(&fixture,
                     "com.example.empty",
                     (const uint8_t *)"",
                     0U);

    ancs_notification_t notification = {0};
    strcpy(notification.app_id, "com.example.empty");
    ancs_app_data_parser_t parser;
    ancs_app_data_parser_init(&parser, &notification);
    for (size_t index = 0; index < fixture.length; ++index) {
        const ancs_parser_result_t result =
            ancs_app_data_parser_feed(&parser, &storage[index], 1U);
        TEST_ASSERT_EQUAL(index + 1U == fixture.length
                              ? ANCS_PARSER_COMPLETE
                              : ANCS_PARSER_MORE,
                          result);
    }
    TEST_ASSERT_EQUAL_STRING("", notification.app_name);
    TEST_ASSERT_FALSE(notification.app_name_truncated);
}

TEST_CASE("app parser bounds oversized display names", "[ancs][app_parser]")
{
    const size_t long_length = CONFIG_ANCS_APP_NAME_MAX + 17U;
    uint8_t *display_name = malloc(long_length);
    uint8_t *storage = calloc(1, long_length + 64U);
    TEST_ASSERT_NOT_NULL(display_name);
    TEST_ASSERT_NOT_NULL(storage);
    memset(display_name, 'N', long_length);
    fixture_builder_t fixture = {
        .bytes = storage,
        .capacity = long_length + 64U,
    };
    make_app_fixture(&fixture,
                     "com.example.long",
                     display_name,
                     long_length);

    ancs_notification_t notification;
    TEST_ASSERT_EQUAL(
        ANCS_PARSER_COMPLETE,
        feed_app_fixture(storage,
                         fixture.length,
                         fixture.length - 1U,
                         &notification,
                         "com.example.long"));
    TEST_ASSERT_TRUE(notification.app_name_truncated);
    TEST_ASSERT_EQUAL_size_t(CONFIG_ANCS_APP_NAME_MAX,
                             strlen(notification.app_name));
    TEST_ASSERT_EQUAL_CHAR('\0',
                           notification.app_name[CONFIG_ANCS_APP_NAME_MAX]);

    free(storage);
    free(display_name);
}

TEST_CASE("app parser rejects wrong command app id attribute and trailing data",
          "[ancs][app_parser]")
{
    uint8_t storage[128] = {0};
    fixture_builder_t fixture = {.bytes = storage, .capacity = sizeof(storage)};
    make_app_fixture(&fixture,
                     "com.example.actual",
                     (const uint8_t *)"Actual",
                     strlen("Actual"));

    ancs_notification_t notification = {0};
    strcpy(notification.app_id, "com.example.actual");
    ancs_app_data_parser_t parser;
    ancs_app_data_parser_init(&parser, &notification);
    storage[0] = 0x00;
    TEST_ASSERT_EQUAL(ANCS_PARSER_ERROR,
                      ancs_app_data_parser_feed(&parser,
                                                storage,
                                                fixture.length));
    TEST_ASSERT_EQUAL(ANCS_PROTOCOL_ERR_COMMAND, parser.error_code);

    fixture.length = 0U;
    make_app_fixture(&fixture,
                     "com.example.other",
                     (const uint8_t *)"Other",
                     strlen("Other"));
    memset(&notification, 0, sizeof(notification));
    strcpy(notification.app_id, "com.example.actual");
    ancs_app_data_parser_init(&parser, &notification);
    TEST_ASSERT_EQUAL(ANCS_PARSER_ERROR,
                      ancs_app_data_parser_feed(&parser,
                                                storage,
                                                fixture.length));
    TEST_ASSERT_EQUAL(ANCS_PROTOCOL_ERR_APP_ID_MISMATCH, parser.error_code);

    fixture.length = 0U;
    fixture_begin_app(&fixture, "com.example.actual");
    fixture_attribute(&fixture, 1U, "Wrong");
    memset(&notification, 0, sizeof(notification));
    strcpy(notification.app_id, "com.example.actual");
    ancs_app_data_parser_init(&parser, &notification);
    TEST_ASSERT_EQUAL(ANCS_PARSER_ERROR,
                      ancs_app_data_parser_feed(&parser,
                                                storage,
                                                fixture.length));
    TEST_ASSERT_EQUAL(ANCS_PROTOCOL_ERR_ATTRIBUTE, parser.error_code);

    fixture.length = 0U;
    make_app_fixture(&fixture,
                     "com.example.actual",
                     (const uint8_t *)"Actual",
                     strlen("Actual"));
    fixture_append_u8(&fixture, 0xFF);
    memset(&notification, 0, sizeof(notification));
    strcpy(notification.app_id, "com.example.actual");
    ancs_app_data_parser_init(&parser, &notification);
    TEST_ASSERT_EQUAL(ANCS_PARSER_ERROR,
                      ancs_app_data_parser_feed(&parser,
                                                storage,
                                                fixture.length));
    TEST_ASSERT_EQUAL(ANCS_PROTOCOL_ERR_SEQUENCE, parser.error_code);
}

TEST_CASE("app parser rejects unterminated oversized app id",
          "[ancs][app_parser]")
{
    uint8_t storage[CONFIG_ANCS_APP_ID_MAX + 2U] = {0};
    storage[0] = 0x01;
    memset(storage + 1U, 'A', CONFIG_ANCS_APP_ID_MAX + 1U);
    ancs_notification_t notification = {0};
    strcpy(notification.app_id, "com.example.actual");
    ancs_app_data_parser_t parser;
    ancs_app_data_parser_init(&parser, &notification);

    TEST_ASSERT_EQUAL(ANCS_PARSER_ERROR,
                      ancs_app_data_parser_feed(&parser,
                                                storage,
                                                sizeof(storage)));
    TEST_ASSERT_EQUAL(ANCS_PROTOCOL_ERR_OVERFLOW, parser.error_code);
}

TEST_CASE("data parser reconstructs all requested attributes", "[ancs][parser]")
{
    uint8_t storage[512] = {0};
    fixture_builder_t fixture = {.bytes = storage, .capacity = sizeof(storage)};
    ancs_notification_t notification;
    make_complete_fixture(&fixture, 0x12345678);

    TEST_ASSERT_EQUAL(ANCS_PARSER_COMPLETE,
                      feed_complete_fixture(storage,
                                            fixture.length,
                                            fixture.length,
                                            &notification,
                                            0x12345678));
    TEST_ASSERT_TRUE(notification.complete);
    TEST_ASSERT_EQUAL_STRING("com.apple.MobileSMS", notification.app_id);
    TEST_ASSERT_EQUAL_STRING("택배 도착", notification.title);
    TEST_ASSERT_EQUAL_STRING("", notification.subtitle);
    TEST_ASSERT_EQUAL_STRING("현관 앞에 두었습니다.", notification.message);
    TEST_ASSERT_EQUAL_STRING("29", notification.message_size_raw);
    TEST_ASSERT_EQUAL_STRING("20260728T164500", notification.date_raw);
}

TEST_CASE("data parser handles every two-fragment byte boundary", "[ancs][parser]")
{
    uint8_t storage[512] = {0};
    fixture_builder_t fixture = {.bytes = storage, .capacity = sizeof(storage)};
    make_complete_fixture(&fixture, 0x44332211);

    for (size_t split = 0; split <= fixture.length; ++split) {
        ancs_notification_t notification;
        TEST_ASSERT_EQUAL(ANCS_PARSER_COMPLETE,
                          feed_complete_fixture(storage,
                                                fixture.length,
                                                split,
                                                &notification,
                                                0x44332211));
        TEST_ASSERT_EQUAL_STRING("택배 도착", notification.title);
        TEST_ASSERT_EQUAL_STRING("현관 앞에 두었습니다.", notification.message);
    }
}

TEST_CASE("data parser handles one byte at a time", "[ancs][parser]")
{
    uint8_t storage[512] = {0};
    fixture_builder_t fixture = {.bytes = storage, .capacity = sizeof(storage)};
    ancs_notification_t notification;
    ancs_data_parser_t parser;
    make_complete_fixture(&fixture, 99);
    init_notification(&notification, 99);
    ancs_data_parser_init(&parser, &notification, 99, ANCS_ATTR_MASK_REQUIRED);

    for (size_t index = 0; index < fixture.length; ++index) {
        const ancs_parser_result_t result =
            ancs_data_parser_feed(&parser, &storage[index], 1);
        if (index + 1 < fixture.length) {
            TEST_ASSERT_EQUAL(ANCS_PARSER_MORE, result);
        } else {
            TEST_ASSERT_EQUAL(ANCS_PARSER_COMPLETE, result);
        }
    }
    TEST_ASSERT_EQUAL_STRING("택배 도착", notification.title);
}

TEST_CASE("empty title subtitle and message are complete attributes", "[ancs][parser]")
{
    uint8_t storage[128] = {0};
    fixture_builder_t fixture = {.bytes = storage, .capacity = sizeof(storage)};
    ancs_notification_t notification;

    fixture_begin(&fixture, 12);
    fixture_attribute(&fixture, 0, "com.example.empty");
    fixture_attribute(&fixture, 1, "");
    fixture_attribute(&fixture, 2, "");
    fixture_attribute(&fixture, 3, "");
    fixture_attribute(&fixture, 4, "0");
    fixture_attribute(&fixture, 5, "20260728T164500");

    TEST_ASSERT_EQUAL(ANCS_PARSER_COMPLETE,
                      feed_complete_fixture(storage,
                                            fixture.length,
                                            7,
                                            &notification,
                                            12));
    TEST_ASSERT_TRUE(notification.complete);
    TEST_ASSERT_EQUAL_STRING("", notification.title);
    TEST_ASSERT_EQUAL_STRING("", notification.subtitle);
    TEST_ASSERT_EQUAL_STRING("", notification.message);
}

TEST_CASE("oversized message is bounded and marked truncated", "[ancs][parser]")
{
    const size_t long_length = CONFIG_ANCS_MESSAGE_MAX + 37U;
    const size_t fixture_capacity = long_length + 128U;
    uint8_t *storage = calloc(1, fixture_capacity);
    uint8_t *long_message = malloc(long_length);
    TEST_ASSERT_NOT_NULL(storage);
    TEST_ASSERT_NOT_NULL(long_message);
    memset(long_message, 'A', long_length);

    fixture_builder_t fixture = {.bytes = storage, .capacity = fixture_capacity};
    ancs_notification_t notification;
    fixture_begin(&fixture, 33);
    fixture_attribute(&fixture, 0, "com.example.long");
    fixture_attribute(&fixture, 1, "title");
    fixture_attribute(&fixture, 2, "");
    fixture_attribute_bytes(&fixture, 3, long_message, long_length);
    fixture_attribute(&fixture, 4, "9999");
    fixture_attribute(&fixture, 5, "20260728T164500");

    TEST_ASSERT_EQUAL(ANCS_PARSER_COMPLETE,
                      feed_complete_fixture(storage,
                                            fixture.length,
                                            fixture.length - 1,
                                            &notification,
                                            33));
    TEST_ASSERT_TRUE(notification.message_truncated);
    TEST_ASSERT_EQUAL_size_t(CONFIG_ANCS_MESSAGE_MAX, strlen(notification.message));
    TEST_ASSERT_EQUAL_CHAR('\0', notification.message[CONFIG_ANCS_MESSAGE_MAX]);

    free(long_message);
    free(storage);
}

TEST_CASE("response for another UID fails without completing current request",
          "[ancs][parser]")
{
    uint8_t storage[256] = {0};
    fixture_builder_t fixture = {.bytes = storage, .capacity = sizeof(storage)};
    ancs_notification_t notification;
    ancs_data_parser_t parser;
    make_complete_fixture(&fixture, 200);
    init_notification(&notification, 100);
    ancs_data_parser_init(&parser, &notification, 100, ANCS_ATTR_MASK_REQUIRED);

    TEST_ASSERT_EQUAL(ANCS_PARSER_ERROR,
                      ancs_data_parser_feed(&parser, storage, fixture.length));
    TEST_ASSERT_EQUAL(ANCS_PROTOCOL_ERR_UID_MISMATCH, parser.error_code);
    TEST_ASSERT_FALSE(notification.complete);
    TEST_ASSERT_EQUAL_STRING("", notification.app_id);
}

TEST_CASE("request queue preserves order and cancellation does not mix notifications",
          "[ancs][queue]")
{
    ancs_request_queue_t queue;
    ancs_notification_event_t first = {.event_id = 0, .uid = 101};
    ancs_notification_event_t second = {.event_id = 1, .uid = 202};
    ancs_notification_event_t output = {0};

    ancs_request_queue_init(&queue);
    TEST_ASSERT_TRUE(ancs_request_queue_push(&queue, &first));
    TEST_ASSERT_TRUE(ancs_request_queue_push(&queue, &second));
    TEST_ASSERT_TRUE(ancs_request_queue_cancel_uid(&queue, 101));
    TEST_ASSERT_TRUE(ancs_request_queue_pop(&queue, &output));
    TEST_ASSERT_EQUAL_UINT32(202, output.uid);
    TEST_ASSERT_FALSE(ancs_request_queue_pop(&queue, &output));
}
