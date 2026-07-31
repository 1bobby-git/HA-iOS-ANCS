#include <string.h>

#include "ancs_protocol.h"
#include "relay_policy.h"
#include "unity.h"

static ancs_notification_t valid_notification(void)
{
    ancs_notification_t notification = {0};
    notification.session_id = 7;
    notification.uid = 1234;
    notification.event_id = 0;
    notification.category_id = 4;
    notification.category_count = 1;
    notification.complete = true;
    notification.received_at_ms = 45678;
    strcpy(notification.app_id, "com.example.app");
    strcpy(notification.title, "title");
    strcpy(notification.subtitle, "subtitle");
    strcpy(notification.message, "message");
    strcpy(notification.date_raw, "20260729T120000");
    return notification;
}

static relay_connectivity_t connected(void)
{
    return (relay_connectivity_t){
        .wifi_connected = true,
        .mqtt_connected = true,
    };
}

static relay_connectivity_t disconnected(void)
{
    return (relay_connectivity_t){
        .wifi_connected = true,
        .mqtt_connected = false,
    };
}

TEST_CASE("pre-existing and offline notifications drop", "[relay_policy]")
{
    ancs_notification_t notification = valid_notification();
    notification.event_flags = ANCS_EVENT_FLAG_PRE_EXISTING;

    TEST_ASSERT_EQUAL(RELAY_DROP_PRE_EXISTING,
                      relay_policy_decide(&notification, connected(), NULL));

    notification.event_flags = 0;
    TEST_ASSERT_EQUAL(RELAY_DROP_OFFLINE,
                      relay_policy_decide(&notification, disconnected(), NULL));
}

TEST_CASE("all Home Assistant notifications drop", "[relay_policy]")
{
    ancs_notification_t notification = valid_notification();
    strcpy(notification.app_id, "io.robbie.HomeAssistant");
    strcpy(notification.title, "[C6\342\206\222HA] relay");

    TEST_ASSERT_EQUAL(RELAY_DROP_ECHO,
                      relay_policy_decide(&notification, connected(), NULL));

    strcpy(notification.title, "original");
    TEST_ASSERT_EQUAL(RELAY_DROP_ECHO,
                      relay_policy_decide(&notification, connected(), NULL));

    strcpy(notification.app_id, "com.example.other");
    strcpy(notification.title, "[C6\342\206\222HA] unrelated");
    TEST_ASSERT_EQUAL(RELAY_PUBLISH,
                      relay_policy_decide(&notification, connected(), NULL));
}

TEST_CASE("relay policy requires added or modified complete notifications",
          "[relay_policy]")
{
    ancs_notification_t notification = valid_notification();

    notification.event_id = 2;
    TEST_ASSERT_EQUAL(RELAY_DROP_EVENT,
                      relay_policy_decide(&notification, connected(), NULL));

    notification.event_id = 0;
    notification.complete = false;
    TEST_ASSERT_EQUAL(RELAY_DROP_INCOMPLETE,
                      relay_policy_decide(&notification, connected(), NULL));

    notification.complete = true;
    notification.app_id[0] = '\0';
    TEST_ASSERT_EQUAL(RELAY_DROP_INVALID,
                      relay_policy_decide(&notification, connected(), NULL));
}

TEST_CASE("modified notifications publish", "[relay_policy]")
{
    ancs_notification_t notification = valid_notification();
    notification.event_id = 1;

    TEST_ASSERT_EQUAL(RELAY_PUBLISH,
                      relay_policy_decide(&notification, connected(), NULL));
}

TEST_CASE("recent cache drops duplicate relay ids", "[relay_policy]")
{
    ancs_notification_t notification = valid_notification();
    relay_recent_cache_t cache;
    char relay_id[RELAY_POLICY_ID_MAX];
    relay_policy_recent_cache_init(&cache);

    TEST_ASSERT_EQUAL(RELAY_PUBLISH,
                      relay_policy_decide(&notification, connected(), &cache));
    TEST_ASSERT_EQUAL(RELAY_PUBLISH,
                      relay_policy_decide(&notification, connected(), &cache));
    TEST_ASSERT_EQUAL(ESP_OK,
                      relay_policy_build_id(&notification, 0, relay_id, sizeof(relay_id)));
    relay_policy_mark_recent(&cache, relay_id);
    TEST_ASSERT_EQUAL(RELAY_DROP_DUPLICATE,
                      relay_policy_decide(&notification, connected(), &cache));

    notification.uid++;
    TEST_ASSERT_EQUAL(RELAY_PUBLISH,
                      relay_policy_decide(&notification, connected(), &cache));
}

TEST_CASE("same uid with changed event or content publishes", "[relay_policy]")
{
    ancs_notification_t notification = valid_notification();
    relay_recent_cache_t cache;
    char relay_id[RELAY_POLICY_ID_MAX];
    relay_policy_recent_cache_init(&cache);

    TEST_ASSERT_EQUAL(RELAY_PUBLISH,
                      relay_policy_decide(&notification, connected(), &cache));
    TEST_ASSERT_EQUAL(ESP_OK,
                      relay_policy_build_id(&notification, 0, relay_id, sizeof(relay_id)));
    relay_policy_mark_recent(&cache, relay_id);

    notification.event_id = 1;
    TEST_ASSERT_EQUAL(RELAY_PUBLISH,
                      relay_policy_decide(&notification, connected(), &cache));
    TEST_ASSERT_EQUAL(ESP_OK,
                      relay_policy_build_id(&notification, 0, relay_id, sizeof(relay_id)));
    relay_policy_mark_recent(&cache, relay_id);

    strcpy(notification.message, "changed");
    TEST_ASSERT_EQUAL(RELAY_PUBLISH,
                      relay_policy_decide(&notification, connected(), &cache));
}

TEST_CASE("relay id is stable for same notification and separates boot nonce",
          "[relay_policy]")
{
    ancs_notification_t notification = valid_notification();
    char first[RELAY_POLICY_ID_MAX];
    char second[RELAY_POLICY_ID_MAX];
    char third[RELAY_POLICY_ID_MAX];

    TEST_ASSERT_EQUAL(ESP_OK,
                      relay_policy_build_id(&notification, 1, first, sizeof(first)));
    TEST_ASSERT_EQUAL(ESP_OK,
                      relay_policy_build_id(&notification, 1, second, sizeof(second)));
    TEST_ASSERT_EQUAL_STRING(first, second);

    TEST_ASSERT_EQUAL(ESP_OK,
                      relay_policy_build_id(&notification, 2, third, sizeof(third)));
    TEST_ASSERT_NOT_EQUAL(0, strcmp(first, third));
    TEST_ASSERT_EQUAL(32, strlen(first));
}

TEST_CASE("relay id uses SHA-256 first 16 bytes", "[relay_policy]")
{
    ancs_notification_t notification = valid_notification();
    char relay_id[RELAY_POLICY_ID_MAX];

    TEST_ASSERT_EQUAL(ESP_OK,
                      relay_policy_build_id(&notification,
                                            1,
                                            relay_id,
                                            sizeof(relay_id)));
    TEST_ASSERT_EQUAL_STRING("d8ae9ebf4a797ac4cf33c53cc9e9db7b",
                             relay_id);

    notification.event_id = 1;
    TEST_ASSERT_EQUAL(ESP_OK,
                      relay_policy_build_id(&notification,
                                            1,
                                            relay_id,
                                            sizeof(relay_id)));
    TEST_ASSERT_EQUAL_STRING("177cc1dc4dcf87e74125103a3808d56f",
                             relay_id);
}

TEST_CASE("counters and decision names cover each result", "[relay_policy]")
{
    relay_policy_counters_t counters;
    relay_policy_counters_init(&counters);

    relay_policy_counters_record(&counters, RELAY_PUBLISH);
    relay_policy_counters_record(&counters, RELAY_DROP_PRE_EXISTING);
    relay_policy_counters_record(&counters, RELAY_DROP_OFFLINE);
    relay_policy_counters_record(&counters, RELAY_DROP_ECHO);
    relay_policy_counters_record(&counters, RELAY_DROP_DUPLICATE);
    relay_policy_counters_record(&counters, RELAY_DROP_INCOMPLETE);
    relay_policy_counters_record(&counters, RELAY_DROP_INVALID);
    relay_policy_counters_record(&counters, RELAY_DROP_EVENT);

    TEST_ASSERT_EQUAL_UINT32(1, counters.published);
    TEST_ASSERT_EQUAL_UINT32(1, counters.drop_pre_existing);
    TEST_ASSERT_EQUAL_UINT32(1, counters.drop_offline);
    TEST_ASSERT_EQUAL_UINT32(1, counters.drop_echo);
    TEST_ASSERT_EQUAL_UINT32(1, counters.drop_duplicate);
    TEST_ASSERT_EQUAL_UINT32(1, counters.drop_incomplete);
    TEST_ASSERT_EQUAL_UINT32(1, counters.drop_invalid);
    TEST_ASSERT_EQUAL_UINT32(1, counters.drop_event);

    TEST_ASSERT_EQUAL_STRING("publish",
                             relay_policy_decision_name(RELAY_PUBLISH));
    TEST_ASSERT_EQUAL_STRING("drop_pre_existing",
                             relay_policy_decision_name(RELAY_DROP_PRE_EXISTING));
    TEST_ASSERT_EQUAL_STRING("drop_offline",
                             relay_policy_decision_name(RELAY_DROP_OFFLINE));
    TEST_ASSERT_EQUAL_STRING("drop_echo",
                             relay_policy_decision_name(RELAY_DROP_ECHO));
    TEST_ASSERT_EQUAL_STRING("drop_duplicate",
                             relay_policy_decision_name(RELAY_DROP_DUPLICATE));
    TEST_ASSERT_EQUAL_STRING("drop_incomplete",
                             relay_policy_decision_name(RELAY_DROP_INCOMPLETE));
    TEST_ASSERT_EQUAL_STRING("drop_invalid",
                             relay_policy_decision_name(RELAY_DROP_INVALID));
    TEST_ASSERT_EQUAL_STRING("drop_event",
                             relay_policy_decision_name(RELAY_DROP_EVENT));
}
