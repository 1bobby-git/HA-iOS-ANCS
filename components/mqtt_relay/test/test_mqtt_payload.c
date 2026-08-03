#include <string.h>
#include <stdlib.h>
#include <stdio.h>

#include "ancs_protocol.h"
#include "mqtt_relay.h"
#include "mqtt_relay_test.h"
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
    strcpy(notification.message_size_raw, "7");
    strcpy(notification.date_raw, "20260729T120000");
    return notification;
}

static provision_config_t valid_config(void)
{
    provision_config_t config = {0};
    config.schema_version = PROVISION_CONFIG_SCHEMA_VERSION;
    strcpy(config.wifi_ssid, "ssid");
    strcpy(config.mqtt_host, "broker.local");
    config.mqtt_port = 1883;
    strcpy(config.mqtt_username, "user");
    strcpy(config.mqtt_password, "secret");
    strcpy(config.mqtt_client_id, "ios_ancs_c6_ab12");
    strcpy(config.mqtt_base_topic, "ios-ancs/2b20");
    return config;
}

static int s_publish_calls;
static int s_next_msg_id;
static int s_last_qos;
static int s_last_retain;
static mqtt_relay_event_t s_last_event;
static int s_event_count;
static int s_discovery_publish_calls;

static int capture_publish(const char *topic,
                           const char *payload,
                           int length,
                           int qos,
                           int retain)
{
    (void)topic;
    (void)payload;
    (void)length;
    s_publish_calls++;
    s_last_qos = qos;
    s_last_retain = retain;
    if (strncmp(topic, "homeassistant/sensor/", 21) == 0) {
        s_discovery_publish_calls++;
    }
    return s_next_msg_id++;
}

static void reset_relay_for_ownership_test(void)
{
    provision_config_t config = valid_config();
    s_publish_calls = 0;
    s_next_msg_id = 40;
    s_last_qos = -1;
    s_last_retain = -1;
    s_last_event = MQTT_RELAY_EVENT_FAILED;
    s_event_count = 0;
    s_discovery_publish_calls = 0;
    TEST_ASSERT_EQUAL(ESP_OK, mqtt_relay_reset_for_test(&config));
    mqtt_relay_set_publish_for_test(capture_publish);
    mqtt_relay_simulate_connected_for_test(true);
}

static void capture_event(mqtt_relay_event_t event, void *context)
{
    (void)context;
    s_last_event = event;
    s_event_count++;
}

TEST_CASE("notification payload preserves serial fields and adds relay fields",
          "[mqtt_relay]")
{
    ancs_notification_t notification = valid_notification();
    char *payload = NULL;
    size_t length = 0;

    TEST_ASSERT_EQUAL(ESP_OK,
                      mqtt_payload_build_notification(&notification,
                                                      "IOS-ANCS-C6-AB12",
                                                      "relay-1",
                                                      123456,
                                                      &payload,
                                                      &length));
    TEST_ASSERT_NOT_NULL(payload);
    TEST_ASSERT_GREATER_THAN(0, length);
    TEST_ASSERT_NOT_NULL(strstr(payload, "\"relay_id\":\"relay-1\""));
    TEST_ASSERT_NOT_NULL(strstr(payload, "\"source\":\"esp32c6_ancs\""));
    TEST_ASSERT_NOT_NULL(strstr(payload, "\"published_at_ms\":123456"));
    TEST_ASSERT_NOT_NULL(strstr(payload, "\"app_id\":\"com.example.app\""));
    TEST_ASSERT_NOT_NULL(strstr(payload, "\"complete\":true"));
    free(payload);
}

TEST_CASE("topics use configurable base and discovery device id", "[mqtt_relay]")
{
    provision_config_t config = valid_config();
    char notification[MQTT_RELAY_TOPIC_MAX];
    char availability[MQTT_RELAY_TOPIC_MAX];
    char state[MQTT_RELAY_TOPIC_MAX];
    char discovery[MQTT_RELAY_DISCOVERY_TOPIC_MAX];

    TEST_ASSERT_EQUAL(ESP_OK,
                      mqtt_relay_build_topics(&config,
                                              notification,
                                              sizeof(notification),
                                              availability,
                                              sizeof(availability),
                                              state,
                                              sizeof(state),
                                              discovery,
                                              sizeof(discovery)));
    TEST_ASSERT_EQUAL_STRING("ios-ancs/2b20/notification", notification);
    TEST_ASSERT_EQUAL_STRING("ios-ancs/2b20/availability", availability);
    TEST_ASSERT_EQUAL_STRING("ios-ancs/2b20/state", state);
    TEST_ASSERT_EQUAL_STRING("homeassistant/sensor/ios_ancs_c6_ab12/last_notification/config",
                             discovery);
}

TEST_CASE("client config maps broker auth client id tls and retained lwt",
          "[mqtt_relay]")
{
    provision_config_t config = valid_config();
    config.mqtt_tls = true;
    strcpy(config.mqtt_ca, "-----BEGIN CERTIFICATE-----\nCA\n-----END CERTIFICATE-----\n");
    esp_mqtt_client_config_t mqtt_config = {0};

    TEST_ASSERT_EQUAL(ESP_OK,
                      mqtt_relay_build_client_config(&config,
                                                     "ios-ancs/2b20/availability",
                                                     &mqtt_config));
    TEST_ASSERT_EQUAL_STRING("broker.local", mqtt_config.broker.address.hostname);
    TEST_ASSERT_EQUAL_UINT32(1883, mqtt_config.broker.address.port);
    TEST_ASSERT_EQUAL_STRING("user", mqtt_config.credentials.username);
    TEST_ASSERT_EQUAL_STRING("secret",
                             mqtt_config.credentials.authentication.password);
    TEST_ASSERT_EQUAL_STRING("ios_ancs_c6_ab12", mqtt_config.credentials.client_id);
    TEST_ASSERT_EQUAL_STRING(config.mqtt_ca,
                             mqtt_config.broker.verification.certificate);
    TEST_ASSERT_EQUAL_STRING("ios-ancs/2b20/availability",
                             mqtt_config.session.last_will.topic);
    TEST_ASSERT_EQUAL_STRING("offline", mqtt_config.session.last_will.msg);
    TEST_ASSERT_EQUAL(1, mqtt_config.session.last_will.qos);
    TEST_ASSERT_TRUE(mqtt_config.session.last_will.retain);

    config.mqtt_ca[0] = '\0';
    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_ARG,
                      mqtt_relay_build_client_config(&config,
                                                     "ios-ancs/2b20/availability",
                                                     &mqtt_config));
}

TEST_CASE("discovery uses relay id state and json attributes", "[mqtt_relay]")
{
    provision_config_t config = valid_config();
    char payload[1024];

    TEST_ASSERT_EQUAL(ESP_OK,
                      mqtt_relay_build_discovery_payload(&config,
                                                         "ios-ancs/2b20/notification",
                                                         "ios-ancs/2b20/availability",
                                                         payload,
                                                         sizeof(payload)));
    TEST_ASSERT_NOT_NULL(strstr(payload, "\"state_topic\":\"ios-ancs/2b20/notification\""));
    TEST_ASSERT_NOT_NULL(strstr(payload, "\"name\":\"ios_ancs_c6_ab12 last notification\""));
    TEST_ASSERT_NOT_NULL(strstr(payload, "\"unique_id\":\"ios_ancs_c6_ab12_last_notification\""));
    TEST_ASSERT_NOT_NULL(strstr(payload, "\"object_id\":\"ios_ancs_c6_ab12_last_notification\""));
    TEST_ASSERT_NULL(strstr(payload, "\"name\":\"ios_ancs_c6_ab12\",\"unique_id\""));
    TEST_ASSERT_NOT_NULL(strstr(payload, "\"value_template\":\"{{ value_json.relay_id }}\""));
    TEST_ASSERT_NOT_NULL(strstr(payload, "\"json_attributes_topic\":\"ios-ancs/2b20/notification\""));
    TEST_ASSERT_NOT_NULL(strstr(payload, "\"availability_topic\":\"ios-ancs/2b20/availability\""));
    TEST_ASSERT_NULL(strstr(payload, "secret"));

    strcpy(config.mqtt_client_id, "bad/client");
    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_ARG,
                      mqtt_relay_build_discovery_payload(&config,
                                                         "ios-ancs/2b20/notification",
                                                         "ios-ancs/2b20/availability",
                                                         payload,
                                                         sizeof(payload)));
    config = valid_config();
    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_ARG,
                      mqtt_relay_build_discovery_payload(&config,
                                                         "ios-ancs/+/notification",
                                                         "ios-ancs/2b20/availability",
                                                         payload,
                                                         sizeof(payload)));
}

TEST_CASE("discovery creates a retained sensor for every notification field",
          "[mqtt_relay]")
{
    static const char *expected_fields[] = {
        "schema_version",
        "target",
        "device_name",
        "session_id",
        "event",
        "event_id",
        "uid",
        "event_flags",
        "silent",
        "important",
        "pre_existing",
        "positive_action_available",
        "negative_action_available",
        "category_id",
        "category",
        "category_count",
        "app_id",
        "title",
        "subtitle",
        "message",
        "message_size",
        "date",
        "complete",
        "truncated",
        "error",
        "received_at_ms",
        "relay_id",
        "source",
        "published_at_ms",
        "truncated_app_id",
        "truncated_title",
        "truncated_subtitle",
        "truncated_message",
    };
    provision_config_t config = valid_config();
    char topic[MQTT_RELAY_DISCOVERY_TOPIC_MAX];
    char payload[1024];

    TEST_ASSERT_EQUAL(sizeof(expected_fields) / sizeof(expected_fields[0]),
                      mqtt_relay_discovery_field_count());
    for (size_t index = 0; index < mqtt_relay_discovery_field_count(); ++index) {
        TEST_ASSERT_EQUAL_STRING(expected_fields[index],
                                 mqtt_relay_discovery_field_key(index));
        TEST_ASSERT_EQUAL(
            ESP_OK,
            mqtt_relay_build_field_discovery_topic(&config,
                                                   index,
                                                   topic,
                                                   sizeof(topic)));
        char expected_topic[MQTT_RELAY_DISCOVERY_TOPIC_MAX];
        snprintf(expected_topic,
                 sizeof(expected_topic),
                 "homeassistant/sensor/ios_ancs_c6_ab12/%s/config",
                 expected_fields[index]);
        TEST_ASSERT_EQUAL_STRING(expected_topic, topic);
        TEST_ASSERT_EQUAL(
            ESP_OK,
            mqtt_relay_build_field_discovery_payload(
                &config,
                "ios-ancs/2b20/notification",
                "ios-ancs/2b20/availability",
                index,
                payload,
                sizeof(payload)));
        TEST_ASSERT_NOT_NULL(
            strstr(payload, "\"state_topic\":\"ios-ancs/2b20/notification\""));
        TEST_ASSERT_NOT_NULL(strstr(payload, "\"value_template\":\"{{"));
        if (strcmp(expected_fields[index], "app_id") == 0 ||
            strcmp(expected_fields[index], "title") == 0 ||
            strcmp(expected_fields[index], "subtitle") == 0 ||
            strcmp(expected_fields[index], "message") == 0) {
            TEST_ASSERT_NOT_NULL(strstr(payload, "[:255]"));
        }
        TEST_ASSERT_NOT_NULL(
            strstr(payload, "\"availability_topic\":\"ios-ancs/2b20/availability\""));
        TEST_ASSERT_NULL(strstr(payload, "\"json_attributes_topic\""));
    }
    TEST_ASSERT_NULL(
        mqtt_relay_discovery_field_key(mqtt_relay_discovery_field_count()));
    TEST_ASSERT_EQUAL(
        ESP_ERR_INVALID_ARG,
        mqtt_relay_build_field_discovery_topic(
            &config,
            mqtt_relay_discovery_field_count(),
            topic,
            sizeof(topic)));
}

TEST_CASE("retained status publishes last notification and every field discovery",
          "[mqtt_relay]")
{
    reset_relay_for_ownership_test();
    s_publish_calls = 0;
    s_discovery_publish_calls = 0;

    mqtt_relay_publish_retained_for_test();

    TEST_ASSERT_EQUAL(mqtt_relay_discovery_field_count() + 3U, s_publish_calls);
    TEST_ASSERT_EQUAL(mqtt_relay_discovery_field_count() + 1U,
                      s_discovery_publish_calls);
    TEST_ASSERT_EQUAL(MQTT_RELAY_RETAINED_QOS, s_last_qos);
    TEST_ASSERT_EQUAL(MQTT_RELAY_RETAINED_RETAIN, s_last_retain);
}

TEST_CASE("field discovery supports maximum configured identifiers and topics",
          "[mqtt_relay]")
{
    provision_config_t config = valid_config();
    memset(config.mqtt_client_id, 'a', PROVISION_MQTT_CLIENT_ID_MAX);
    config.mqtt_client_id[PROVISION_MQTT_CLIENT_ID_MAX] = '\0';
    memset(config.mqtt_base_topic, 'b', PROVISION_MQTT_BASE_TOPIC_MAX);
    config.mqtt_base_topic[PROVISION_MQTT_BASE_TOPIC_MAX] = '\0';

    char notification[MQTT_RELAY_TOPIC_MAX];
    char availability[MQTT_RELAY_TOPIC_MAX];
    char state[MQTT_RELAY_TOPIC_MAX];
    char discovery_topic[MQTT_RELAY_DISCOVERY_TOPIC_MAX];
    char discovery_payload[1536];

    TEST_ASSERT_EQUAL(ESP_OK,
                      mqtt_relay_build_topics(&config,
                                              notification,
                                              sizeof(notification),
                                              availability,
                                              sizeof(availability),
                                              state,
                                              sizeof(state),
                                              discovery_topic,
                                              sizeof(discovery_topic)));
    for (size_t index = 0; index < mqtt_relay_discovery_field_count(); ++index) {
        TEST_ASSERT_EQUAL(
            ESP_OK,
            mqtt_relay_build_field_discovery_topic(&config,
                                                   index,
                                                   discovery_topic,
                                                   sizeof(discovery_topic)));
        TEST_ASSERT_EQUAL(
            ESP_OK,
            mqtt_relay_build_field_discovery_payload(&config,
                                                     notification,
                                                     availability,
                                                     index,
                                                     discovery_payload,
                                                     sizeof(discovery_payload)));
    }
}

TEST_CASE("state payload reports counters without secrets", "[mqtt_relay]")
{
    mqtt_relay_counters_t counters = {
        .accepted = 2,
        .published_ack = 1,
        .dropped_offline = 3,
        .dropped_enqueue = 4,
    };
    char payload[256];

    TEST_ASSERT_EQUAL(ESP_OK,
                      mqtt_relay_build_state_payload(&counters,
                                                     true,
                                                     payload,
                                                     sizeof(payload)));
    TEST_ASSERT_NOT_NULL(strstr(payload, "\"connected\":true"));
    TEST_ASSERT_NOT_NULL(strstr(payload, "\"accepted\":2"));
    TEST_ASSERT_NOT_NULL(strstr(payload, "\"published_ack\":1"));
    TEST_ASSERT_NULL(strstr(payload, "password"));
    TEST_ASSERT_NULL(strstr(payload, "ca"));
}

TEST_CASE("observer enqueues only and PUBACK frees exactly once", "[mqtt_relay]")
{
    reset_relay_for_ownership_test();
    ancs_notification_t notification = valid_notification();

    mqtt_relay_observe_notification(&notification, "IOS-ANCS-C6-AB12", NULL);
    mqtt_relay_counters_t counters = {0};
    mqtt_relay_get_counters(&counters);
    TEST_ASSERT_EQUAL_UINT32(1, counters.accepted);
    TEST_ASSERT_EQUAL(0, s_publish_calls);

    mqtt_relay_drain_for_test();
    mqtt_relay_get_counters(&counters);
    TEST_ASSERT_EQUAL(1, s_publish_calls);
    TEST_ASSERT_EQUAL(MQTT_RELAY_NOTIFICATION_QOS, s_last_qos);
    TEST_ASSERT_EQUAL(MQTT_RELAY_NOTIFICATION_RETAIN, s_last_retain);
    TEST_ASSERT_EQUAL_UINT32(0, counters.freed);

    mqtt_relay_simulate_published_for_test(40);
    mqtt_relay_simulate_published_for_test(40);
    mqtt_relay_get_counters(&counters);
    TEST_ASSERT_EQUAL_UINT32(1, counters.published_ack);
    TEST_ASSERT_EQUAL_UINT32(1, counters.freed);
}

TEST_CASE("relay emits connection callbacks for coordinator", "[mqtt_relay]")
{
    provision_config_t config = valid_config();
    TEST_ASSERT_EQUAL(ESP_OK, mqtt_relay_reset_for_test(&config));
    TEST_ASSERT_EQUAL(ESP_OK, mqtt_relay_register_event_callback(capture_event, NULL));

    mqtt_relay_simulate_connected_for_test(true);
    TEST_ASSERT_EQUAL(1, s_event_count);
    TEST_ASSERT_EQUAL(MQTT_RELAY_EVENT_CONNECTED, s_last_event);

    mqtt_relay_simulate_disconnect_for_test();
    TEST_ASSERT_EQUAL(2, s_event_count);
    TEST_ASSERT_EQUAL(MQTT_RELAY_EVENT_DISCONNECTED, s_last_event);
}

TEST_CASE("queue overflow frees rejected heap item", "[mqtt_relay]")
{
    reset_relay_for_ownership_test();

    for (uint32_t index = 0; index < MQTT_RELAY_QUEUE_CAPACITY + 1; ++index) {
        ancs_notification_t notification = valid_notification();
        notification.uid += index;
        mqtt_relay_observe_notification(&notification, "IOS-ANCS-C6-AB12", NULL);
    }

    mqtt_relay_counters_t counters = {0};
    mqtt_relay_get_counters(&counters);
    TEST_ASSERT_EQUAL_UINT32(MQTT_RELAY_QUEUE_CAPACITY, counters.accepted);
    TEST_ASSERT_EQUAL_UINT32(1, counters.dropped_enqueue);
    TEST_ASSERT_EQUAL_UINT32(1, counters.freed);
    TEST_ASSERT_EQUAL(0, s_publish_calls);
}

TEST_CASE("queue overflow does not mark rejected relay id duplicate", "[mqtt_relay]")
{
    reset_relay_for_ownership_test();

    for (uint32_t index = 0; index < MQTT_RELAY_QUEUE_CAPACITY; ++index) {
        ancs_notification_t notification = valid_notification();
        notification.uid += index;
        mqtt_relay_observe_notification(&notification, "IOS-ANCS-C6-AB12", NULL);
    }

    ancs_notification_t rejected = valid_notification();
    rejected.uid = 9001;
    mqtt_relay_observe_notification(&rejected, "IOS-ANCS-C6-AB12", NULL);

    mqtt_relay_counters_t counters = {0};
    mqtt_relay_get_counters(&counters);
    TEST_ASSERT_EQUAL_UINT32(MQTT_RELAY_QUEUE_CAPACITY, counters.accepted);
    TEST_ASSERT_EQUAL_UINT32(1, counters.dropped_enqueue);
    TEST_ASSERT_EQUAL_UINT32(0, counters.dropped_policy);

    mqtt_relay_drain_for_test();
    mqtt_relay_observe_notification(&rejected, "IOS-ANCS-C6-AB12", NULL);

    mqtt_relay_get_counters(&counters);
    TEST_ASSERT_EQUAL_UINT32(MQTT_RELAY_QUEUE_CAPACITY + 1, counters.accepted);
    TEST_ASSERT_EQUAL_UINT32(1, counters.dropped_enqueue);
    TEST_ASSERT_EQUAL_UINT32(0, counters.dropped_policy);
}

TEST_CASE("disconnect frees queued and pending items without PUBACK", "[mqtt_relay]")
{
    reset_relay_for_ownership_test();

    for (uint32_t index = 0; index < 2; ++index) {
        ancs_notification_t notification = valid_notification();
        notification.uid += index;
        mqtt_relay_observe_notification(&notification, "IOS-ANCS-C6-AB12", NULL);
    }
    mqtt_relay_drain_for_test();
    mqtt_relay_simulate_disconnect_for_test();

    mqtt_relay_counters_t counters = {0};
    mqtt_relay_get_counters(&counters);
    TEST_ASSERT_EQUAL_UINT32(2, counters.accepted);
    TEST_ASSERT_EQUAL_UINT32(0, counters.published_ack);
    TEST_ASSERT_EQUAL_UINT32(2, counters.freed);

    ancs_notification_t notification = valid_notification();
    notification.uid = 999;
    mqtt_relay_observe_notification(&notification, "IOS-ANCS-C6-AB12", NULL);
    mqtt_relay_get_counters(&counters);
    TEST_ASSERT_EQUAL_UINT32(1, counters.dropped_offline);
}

TEST_CASE("enroll button topics and discovery are stable", "[mqtt_relay]")
{
    provision_config_t config = valid_config();
    char command[MQTT_RELAY_TOPIC_MAX];
    char discovery_topic[MQTT_RELAY_DISCOVERY_TOPIC_MAX];
    char payload[1536];

    TEST_ASSERT_EQUAL(ESP_OK,
                      mqtt_relay_build_enroll_command_topic(
                          &config, command, sizeof(command)));
    TEST_ASSERT_EQUAL_STRING("ios-ancs/2b20/command/enroll", command);
    TEST_ASSERT_EQUAL(ESP_OK,
                      mqtt_relay_build_enroll_discovery_topic(
                          &config, discovery_topic, sizeof(discovery_topic)));
    TEST_ASSERT_EQUAL_STRING(
        "homeassistant/button/ios_ancs_c6_ab12/enroll/config",
        discovery_topic);
    TEST_ASSERT_EQUAL(ESP_OK,
                      mqtt_relay_build_enroll_discovery_payload(
                          &config,
                          command,
                          "ios-ancs/2b20/availability",
                          payload,
                          sizeof(payload)));
    TEST_ASSERT_NOT_NULL(strstr(payload, "\"payload_press\":\"ENROLL\""));
    TEST_ASSERT_NOT_NULL(strstr(payload, "\"retain\":false"));
    TEST_ASSERT_NOT_NULL(strstr(payload, "\"entity_category\":\"config\""));
    TEST_ASSERT_NOT_NULL(strstr(payload, "\"unique_id\":\"ios_ancs_c6_ab12_enroll\""));
    TEST_ASSERT_NULL(strstr(payload, "secret"));
}

TEST_CASE("enroll command rejects retained partial and malformed input",
          "[mqtt_relay]")
{
    const char *topic = "ios-ancs/2b20/command/enroll";
    const char *wrong_topic = "ios-ancs/2b20/command/replace";
    TEST_ASSERT_TRUE(mqtt_relay_is_enroll_command(
        topic, topic, strlen(topic), "ENROLL", 6, 6, 0, false));
    TEST_ASSERT_FALSE(mqtt_relay_is_enroll_command(
        topic, topic, strlen(topic), "ENROLL", 6, 6, 0, true));
    TEST_ASSERT_FALSE(mqtt_relay_is_enroll_command(
        topic, topic, strlen(topic), "ENR", 3, 6, 0, false));
    TEST_ASSERT_FALSE(mqtt_relay_is_enroll_command(
        topic, topic, strlen(topic), "enroll", 6, 6, 0, false));
    TEST_ASSERT_FALSE(mqtt_relay_is_enroll_command(
        topic,
        wrong_topic,
        strlen(wrong_topic),
        "ENROLL",
        6,
        6,
        0,
        false));
}
