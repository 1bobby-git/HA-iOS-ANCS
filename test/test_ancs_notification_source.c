#include <stddef.h>
#include <stdint.h>

#include "ancs_protocol.h"
#include "unity.h"

TEST_CASE("notification source accepts exactly eight bytes", "[ancs][notification_source]")
{
    const uint8_t frame[8] = {0x00, 0x1F, 0x04, 0x03, 0x78, 0x56, 0x34, 0x12};
    ancs_notification_event_t event = {0};

    TEST_ASSERT_EQUAL(ANCS_PROTOCOL_OK,
                      ancs_parse_notification_source(frame, sizeof(frame), &event));
    TEST_ASSERT_EQUAL_UINT8(0, event.event_id);
    TEST_ASSERT_EQUAL_UINT8(0x1F, event.event_flags);
    TEST_ASSERT_EQUAL_UINT8(4, event.category_id);
    TEST_ASSERT_EQUAL_UINT8(3, event.category_count);
    TEST_ASSERT_EQUAL_HEX32(0x12345678, event.uid);
}

TEST_CASE("notification source rejects every truncated length", "[ancs][notification_source]")
{
    const uint8_t frame[8] = {0};
    ancs_notification_event_t event = {0};

    for (size_t length = 0; length < sizeof(frame); ++length) {
        TEST_ASSERT_EQUAL(ANCS_PROTOCOL_ERR_LENGTH,
                          ancs_parse_notification_source(frame, length, &event));
    }
}

TEST_CASE("notification source rejects oversized and reserved event frames",
          "[ancs][notification_source]")
{
    uint8_t frame[9] = {0};
    ancs_notification_event_t event = {0};

    TEST_ASSERT_EQUAL(ANCS_PROTOCOL_ERR_LENGTH,
                      ancs_parse_notification_source(frame, sizeof(frame), &event));

    frame[0] = 3;
    TEST_ASSERT_EQUAL(ANCS_PROTOCOL_ERR_EVENT,
                      ancs_parse_notification_source(frame, 8, &event));
}

TEST_CASE("event flags and names match the ANCS appendix", "[ancs][metadata]")
{
    const uint8_t flags = 0x1F;

    TEST_ASSERT_TRUE(ancs_event_flag_is_set(flags, ANCS_EVENT_FLAG_SILENT));
    TEST_ASSERT_TRUE(ancs_event_flag_is_set(flags, ANCS_EVENT_FLAG_IMPORTANT));
    TEST_ASSERT_TRUE(ancs_event_flag_is_set(flags, ANCS_EVENT_FLAG_PRE_EXISTING));
    TEST_ASSERT_TRUE(ancs_event_flag_is_set(flags, ANCS_EVENT_FLAG_POSITIVE_ACTION));
    TEST_ASSERT_TRUE(ancs_event_flag_is_set(flags, ANCS_EVENT_FLAG_NEGATIVE_ACTION));
    TEST_ASSERT_EQUAL_STRING("added", ancs_event_name(0));
    TEST_ASSERT_EQUAL_STRING("modified", ancs_event_name(1));
    TEST_ASSERT_EQUAL_STRING("removed", ancs_event_name(2));
    TEST_ASSERT_EQUAL_STRING("social", ancs_category_name(4));
    TEST_ASSERT_EQUAL_STRING("reserved", ancs_category_name(255));
}
