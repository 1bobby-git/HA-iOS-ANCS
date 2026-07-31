#include <stdint.h>
#include <string.h>

#include "ancs_protocol.h"
#include "notification_sink.h"
#include "unity.h"

static char s_json_output[8192];
static int s_observer_calls;
static const ancs_notification_t *s_observed_notification;
static const char *s_observed_device_name;

static void test_observer(const ancs_notification_t *notification,
                          const char *device_name,
                          void *context)
{
    TEST_ASSERT_EQUAL_PTR((void *)0x1234, context);
    s_observer_calls++;
    s_observed_notification = notification;
    s_observed_device_name = device_name;
}

static ancs_notification_t sample_notification(void)
{
    ancs_notification_t notification = {0};
    notification.session_id = 1;
    notification.uid = 19483021;
    notification.event_id = 0;
    notification.event_flags = ANCS_EVENT_FLAG_IMPORTANT;
    notification.category_id = 4;
    notification.category_count = 1;
    notification.complete = true;
    notification.received_at_ms = 123456;
    strcpy(notification.app_id, "com.example.delivery");
    strcpy(notification.title, "택배 \"도착\"");
    strcpy(notification.subtitle, "");
    strcpy(notification.message, "현관\\앞\n보관");
    strcpy(notification.message_size_raw, "20");
    strcpy(notification.date_raw, "20260728T164500");
    return notification;
}

TEST_CASE("notification JSON is valid escaped UTF-8", "[ancs][json]")
{
    ancs_notification_t notification = sample_notification();
    memset(s_json_output, 0, sizeof(s_json_output));

    TEST_ASSERT_EQUAL(0,
                      notification_sink_format_json(&notification,
                                                    "IOS-ANCS-C6-2B20",
                                                    s_json_output,
                                                    sizeof(s_json_output)));
    TEST_ASSERT_EQUAL_CHAR('{', s_json_output[0]);
    TEST_ASSERT_EQUAL_CHAR('}', s_json_output[strlen(s_json_output) - 1]);
    TEST_ASSERT_NOT_NULL(strstr(s_json_output, "\"target\":\"esp32c6\""));
    TEST_ASSERT_NOT_NULL(
        strstr(s_json_output, "\"title\":\"택배 \\\"도착\\\"\""));
    TEST_ASSERT_NOT_NULL(
        strstr(s_json_output, "\"message\":\"현관\\\\앞\\n보관\""));
    TEST_ASSERT_NOT_NULL(strstr(s_json_output, "\"error\":null"));
}

TEST_CASE("notification JSON reports flag and truncation fields", "[ancs][json]")
{
    ancs_notification_t notification = sample_notification();
    memset(s_json_output, 0, sizeof(s_json_output));
    notification.message_truncated = true;

    TEST_ASSERT_EQUAL(0,
                      notification_sink_format_json(&notification,
                                                    "IOS-ANCS-C6-2B20",
                                                    s_json_output,
                                                    sizeof(s_json_output)));
    TEST_ASSERT_NOT_NULL(strstr(s_json_output, "\"important\":true"));
    TEST_ASSERT_NOT_NULL(strstr(
        s_json_output,
        "\"truncated\":{\"app_id\":false,\"title\":false,\"subtitle\":false,\"message\":true}"));
}

TEST_CASE("invalid UTF-8 is replaced without producing invalid JSON", "[ancs][json]")
{
    ancs_notification_t notification = sample_notification();
    memset(s_json_output, 0, sizeof(s_json_output));
    notification.title[0] = (char)0xC3;
    notification.title[1] = '(';
    notification.title[2] = '\0';

    TEST_ASSERT_EQUAL(0,
                      notification_sink_format_json(&notification,
                                                    "IOS-ANCS-C6-2B20",
                                                    s_json_output,
                                                    sizeof(s_json_output)));
    TEST_ASSERT_NOT_NULL(strstr(s_json_output, "\"title\":\"\\uFFFD(\""));
}

TEST_CASE("state JSON contains subscription and auth failure evidence", "[ancs][json]")
{
    char output[1024] = {0};

    TEST_ASSERT_EQUAL(0,
                      notification_sink_format_state_json("recovering",
                                                          3,
                                                          true,
                                                          true,
                                                          false,
                                                          0x05,
                                                          output,
                                                          sizeof(output)));
    TEST_ASSERT_NOT_NULL(strstr(output, "\"state\":\"recovering\""));
    TEST_ASSERT_NOT_NULL(strstr(output, "\"auth_error\":5"));
    TEST_ASSERT_NOT_NULL(strstr(output,
                                "\"notification_source_subscribed\":false"));
}

TEST_CASE("JSON formatter fails without crossing a small buffer boundary",
          "[ancs][json][memory]")
{
    ancs_notification_t notification = sample_notification();
    struct {
        char output[16];
        uint8_t guard[8];
    } guarded = {0};
    memset(guarded.guard, 0xA5, sizeof(guarded.guard));

    TEST_ASSERT_EQUAL(-2,
                      notification_sink_format_json(&notification,
                                                    "IOS-ANCS-C6-2B20",
                                                    guarded.output,
                                                    sizeof(guarded.output)));
    for (size_t index = 0; index < sizeof(guarded.guard); ++index) {
        TEST_ASSERT_EQUAL_HEX8(0xA5, guarded.guard[index]);
    }
}

TEST_CASE("notification publish calls typed observer after serial formatting",
          "[ancs][json][observer]")
{
    ancs_notification_t notification = sample_notification();
    s_observer_calls = 0;
    s_observed_notification = NULL;
    s_observed_device_name = NULL;

    TEST_ASSERT_EQUAL(ESP_OK,
                      notification_sink_register_observer(test_observer,
                                                          (void *)0x1234));
    TEST_ASSERT_EQUAL(0,
                      notification_sink_publish(&notification,
                                                "IOS-ANCS-C6-2B20"));
    TEST_ASSERT_EQUAL(1, s_observer_calls);
    TEST_ASSERT_EQUAL_PTR(&notification, s_observed_notification);
    TEST_ASSERT_EQUAL_STRING("IOS-ANCS-C6-2B20", s_observed_device_name);

    TEST_ASSERT_EQUAL(ESP_OK, notification_sink_register_observer(NULL, NULL));
}
