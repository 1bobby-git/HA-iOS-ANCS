from pathlib import Path


ROOT = Path(__file__).parents[2]
MQTT_RELAY = ROOT / "components" / "mqtt_relay"
RELAY_POLICY = ROOT / "components" / "relay_policy"


def read(name: str) -> str:
    return (MQTT_RELAY / name).read_text(encoding="utf-8")


def read_policy(name: str) -> str:
    return (RELAY_POLICY / name).read_text(encoding="utf-8")


def test_mqtt_component_uses_pointer_queue_capacity_and_qos_contracts():
    header = read("include/mqtt_relay.h")
    source = read("mqtt_relay.c")
    assert "#define MQTT_RELAY_QUEUE_CAPACITY 8" in header
    assert "xQueueCreate(MQTT_RELAY_QUEUE_CAPACITY, sizeof(mqtt_payload_item_t *))" in source
    assert "esp_mqtt_client_publish" in source
    assert "MQTT_RELAY_NOTIFICATION_QOS" in source
    assert "MQTT_RELAY_NOTIFICATION_RETAIN" in source
    assert "MQTT_RELAY_RETAINED_QOS" in source
    assert "MQTT_RELAY_RETAINED_RETAIN" in source
    assert "mqtt_relay_worker" in source
    assert "mqtt_relay_register_event_callback" in header
    assert "mqtt_relay_reconfigure" in header
    assert "mqtt_relay_deinit" in header
    assert "explicitly offline, not accepting observers" in header


def test_client_config_sets_broker_auth_tls_and_lwt():
    source = read("mqtt_relay.c")
    assert ".broker.address.hostname = config->mqtt_host" in source
    assert ".broker.address.port = config->mqtt_port" in source
    assert "MQTT_TRANSPORT_OVER_SSL" in source
    assert "MQTT_TRANSPORT_OVER_TCP" in source
    assert ".credentials.username = config->mqtt_username" in source
    assert ".credentials.authentication.password = config->mqtt_password" in source
    assert ".credentials.client_id = config->mqtt_client_id" in source
    assert ".broker.verification.certificate = config->mqtt_tls ? config->mqtt_ca : NULL" in source
    assert '.session.last_will.msg = "offline"' in source
    assert ".session.last_will.qos = 1" in source
    assert ".session.last_will.retain = true" in source
    assert "PROVISION_CONFIG_TLS_CA_REQUIRED" in source
    assert ".network.disable_auto_reconnect = true" in source


def test_discovery_and_payload_contracts_are_present():
    payload = read("mqtt_payload.c")
    source = read("mqtt_relay.c")
    assert '#include "platform_identity.h"' in payload
    assert "ANCS_SOURCE_ID" in payload
    assert '\\"source\\":\\"esp32c6_ancs\\"' not in payload
    assert '\\"relay_id\\":' in payload
    assert '\\"published_at_ms\\":' in payload
    assert "value_json.relay_id" in source
    assert "json_attributes_topic" in source
    assert "homeassistant/sensor/" in source
    assert "%s_last_notification" in source
    assert "%s last notification" in source
    assert '\\"object_id\\":' in source
    assert "topic_has_publish_wildcard" in source
    assert "discovery_id_is_safe" in source


def test_home_assistant_enroll_button_is_retained_and_command_is_subscribed():
    header = read("include/mqtt_relay.h")
    source = read("mqtt_relay.c")
    assert "MQTT_RELAY_EVENT_ENROLL_REQUEST" in header
    assert "homeassistant/button/%s/enroll/config" in source
    assert r'\"payload_press\":' in source
    assert "esp_mqtt_client_subscribe" in source
    assert "MQTT_RELAY_ENROLL_COMMAND_QOS" in source
    assert "MQTT_EVENT_DATA" in source
    assert "mqtt_relay_is_enroll_command" in source


def test_offline_no_replay_and_cleanup_paths_are_explicit():
    source = read("mqtt_relay.c")
    assert "if (!s_ctx.accepting_observers || !s_ctx.wifi_connected || !s_ctx.mqtt_connected)" in source
    assert "s_ctx.counters.dropped_offline++" in source
    assert "MQTT_EVENT_PUBLISHED" in source
    assert "mqtt_relay_free_item(item)" in source
    assert "mqtt_relay_free_pending_locked()" in source
    assert "mqtt_relay_free_queue_locked()" in source
    observer = source.split("void mqtt_relay_observe_notification", 1)[1].split(
        "void mqtt_relay_get_counters", 1
    )[0]
    assert "mqtt_relay_drain_queue" not in observer
    assert "esp_mqtt_client_publish" not in observer
    assert "mqtt_relay_notify_worker();" in observer


def test_duplicate_cache_marks_only_after_queue_acceptance():
    policy = read_policy("relay_policy.c")
    decide = policy.split("relay_decision_t relay_policy_decide", 1)[1].split(
        "esp_err_t relay_policy_build_id", 1
    )[0]
    assert "recent_cache_contains(cache, relay_id)" in decide
    assert "recent_cache_store(cache, relay_id)" not in decide

    source = read("mqtt_relay.c")
    observer = source.split("void mqtt_relay_observe_notification", 1)[1].split(
        "void mqtt_relay_get_counters", 1
    )[0]
    queue_send = observer.index("xQueueSend(s_ctx.queue, &item, 0)")
    enqueue_drop = observer.index("s_ctx.counters.dropped_enqueue++", queue_send)
    mark_recent = observer.index("relay_policy_mark_recent(&s_ctx.recent, relay_id)")
    accepted = observer.index("s_ctx.counters.accepted++")
    assert queue_send < enqueue_drop < mark_recent < accepted


def test_retained_status_uses_small_non_secret_snapshot_and_worker_rendezvous():
    source = read("mqtt_relay.c")
    retained = source.split("static void mqtt_relay_publish_retained_status", 1)[1].split(
        "static void mqtt_relay_drain_queue", 1
    )[0]
    assert "provision_config_t config;" not in retained
    assert "provision_config_t discovery_config" not in retained
    assert "calloc(1, sizeof(*discovery_config))" in retained
    assert "free(discovery_config);" in retained
    assert "discovery_config->mqtt_client_id" in retained
    assert "mqtt_password" not in retained
    assert "mqtt_ca" not in retained

    assert "s_ctx.worker_busy = true" in source
    assert "s_ctx.worker_busy = false" in source
    assert "publish_in_flight" in source
    assert "s_ctx.publish_in_flight++" in source
    assert "s_ctx.publish_in_flight--" in source
    assert "mqtt_relay_wait_publish_idle();" in source
    assert "mqtt_relay_wait_worker_idle();" in source
    assert "mqtt_relay_stop_worker_for_teardown();" in source
    assert "s_ctx.worker_task = NULL" in source


def test_connected_event_defers_retained_discovery_to_the_worker():
    source = read("mqtt_relay.c")
    handler = source.split("static void mqtt_relay_event_handler", 1)[1].split(
        "static esp_err_t mqtt_relay_prepare_context", 1
    )[0]
    connected = handler.split("if (event_id == MQTT_EVENT_CONNECTED)", 1)[1].split(
        "if (event_id == MQTT_EVENT_DATA)", 1
    )[0]
    worker = source.split("static void mqtt_relay_worker", 1)[1].split(
        "static void mqtt_relay_notify_worker", 1
    )[0]

    assert "s_ctx.retained_refresh_pending = true;" in connected
    assert "mqtt_relay_publish_retained_status();" not in connected
    assert "s_ctx.retained_refresh_pending" in worker
    assert "mqtt_relay_publish_retained_status();" in worker
    assert "mqtt_relay_publish_retained_once" in source
    assert "MQTT_RELAY_RETAINED_PUBLISH_ATTEMPTS" not in source
    assert "MQTT_RELAY_RETAINED_RETRY_DELAY_MS" not in source
    assert "SemaphoreHandle_t lifecycle_lock" in source
    assert "mqtt_relay_lifecycle_lock();" in source
    assert "mqtt_relay_lifecycle_unlock();" in source


def test_reconfigure_and_worker_notify_are_lifecycle_serialized():
    source = read("mqtt_relay.c")
    notify = source.split("static void mqtt_relay_notify_worker", 1)[1].split(
        "static void mqtt_relay_wait_worker_idle", 1
    )[0]
    assert "mqtt_relay_lock();" in notify
    assert "TaskHandle_t worker = s_ctx.worker_task;" in notify
    assert "mqtt_relay_unlock();" in notify
    assert "xTaskNotifyGive(worker)" in notify

    reconfigure = source.split("esp_err_t mqtt_relay_reconfigure", 1)[1].split(
        "esp_err_t mqtt_relay_register_event_callback", 1
    )[0]
    assert "mqtt_relay_lifecycle_lock();" in reconfigure
    assert "s_ctx.accepting_observers = false;" in reconfigure
    assert "mqtt_relay_stop_unlocked();" in reconfigure
    assert "esp_mqtt_client_destroy(old_client)" in reconfigure
    assert "s_ctx.client = NULL;" in reconfigure
    assert "s_ctx.mqtt_connected = false;" in reconfigure
    assert "s_ctx.accepting_observers = true;" in reconfigure
    assert "mqtt_relay_start_unlocked();" in reconfigure
    assert "s_ctx.publish_allowed = false;" in reconfigure
    assert "mqtt_relay_terminal_reconfigure_failure_cleanup();" in reconfigure
    assert "mqtt_relay_lifecycle_unlock();" in reconfigure


def test_reconfigure_failures_share_terminal_cleanup_and_event_handler_rejects_stale_events():
    source = read("mqtt_relay.c")
    assert "static void mqtt_relay_terminal_reconfigure_failure_cleanup" in source
    cleanup = source.split("static void mqtt_relay_terminal_reconfigure_failure_cleanup", 1)[1].split(
        "static bool mqtt_relay_event_is_current", 1
    )[0]
    assert "s_ctx.client = NULL;" in cleanup
    assert "s_ctx.accepting_observers = false;" in cleanup
    assert "s_ctx.publish_allowed = false;" in cleanup
    assert "s_ctx.mqtt_connected = false;" in cleanup
    assert "mqtt_relay_free_queue_locked();" in cleanup
    assert "mqtt_relay_free_pending_locked();" in cleanup
    assert "mqtt_relay_stop_worker_for_teardown();" in cleanup
    assert "vQueueDelete(queue);" in cleanup

    reconfigure = source.split("esp_err_t mqtt_relay_reconfigure", 1)[1].split(
        "esp_err_t mqtt_relay_register_event_callback", 1
    )[0]
    assert reconfigure.count("mqtt_relay_terminal_reconfigure_failure_cleanup();") >= 4

    event_current = source.split("static bool mqtt_relay_event_is_current", 1)[1].split(
        "static void mqtt_relay_event_handler", 1
    )[0]
    assert "event == NULL" in event_current
    assert "event->client != NULL && event->client == s_ctx.client" in event_current
    assert "MQTT_EVENT_CONNECTED" in event_current
    assert "return accepting && publish_allowed;" in event_current
    assert "MQTT_EVENT_DISCONNECTED" in event_current
    assert "return accepting;" in event_current

    handler = source.split("static void mqtt_relay_event_handler", 1)[1].split(
        "static esp_err_t mqtt_relay_prepare_context", 1
    )[0]
    assert "if (!mqtt_relay_event_is_current(event, event_id))" in handler
    assert "return;" in handler


def test_stop_publishes_offline_outside_data_mutex_and_waits_all_publish_refs():
    source = read("mqtt_relay.c")
    stop = source.split("static esp_err_t mqtt_relay_stop_unlocked", 1)[1].split(
        "esp_err_t mqtt_relay_stop", 1
    )[0]
    before_unlock = stop.split("mqtt_relay_unlock();", 1)[0]
    assert "mqtt_relay_publish_raw" not in before_unlock
    assert "publish_offline = true;" in before_unlock
    assert "mqtt_relay_publish_raw(availability_topic" in stop
    assert "s_ctx.publish_allowed = false;" in stop
    assert "mqtt_relay_wait_publish_idle();" in stop


def test_no_secret_logging_or_state_discovery_serialization():
    combined = "\n".join(path.read_text(encoding="utf-8") for path in MQTT_RELAY.rglob("*.[ch]"))
    forbidden_log_fragments = [
        "ESP_LOGI(TAG, config->mqtt_password",
        "ESP_LOGI(TAG, config->mqtt_ca",
        "ESP_LOG",
    ]
    for fragment in forbidden_log_fragments:
        assert fragment not in combined

    state_discovery = read("mqtt_relay.c")
    assert "mqtt_password" not in state_discovery.split("mqtt_relay_build_state_payload", 1)[1]
    assert "mqtt_ca" not in state_discovery.split("mqtt_relay_build_discovery_payload", 1)[1]


def test_device_metadata_and_wifi_discovery_contracts_are_present():
    header = read("include/mqtt_relay.h")
    source = read("mqtt_relay.c")

    assert "mqtt_relay_device_info_t" in header
    for field in ("manufacturer", "model", "sw_version", "hw_version"):
        assert field in header
    assert "append_device_json" in source
    assert "mqtt_relay_wifi_discovery_field_count" in header
    assert "mqtt_relay_wifi_discovery_field_key" in header
    assert "mqtt_relay_build_wifi_discovery_topic" in header
    assert "mqtt_relay_build_wifi_discovery_payload" in header
    for key in ("wifi_ssid", "wifi_ip", "wifi_rssi"):
        assert f'.key = "{key}"' in source
    assert r'\"entity_category\":\"diagnostic\"' in source
    assert 'signal_strength' in source
    assert 'measurement' in source
    assert 'unit_of_measurement' in source
    assert 'dBm' in source


def test_retained_wifi_state_update_is_bounded_and_secret_free():
    header = read("include/mqtt_relay.h")
    source = read("mqtt_relay.c")

    assert "mqtt_relay_wifi_status_t wifi_status" in source
    assert "mqtt_relay_update_wifi_status" in header
    state_builder = source.split("esp_err_t mqtt_relay_build_state_payload", 1)[1].split(
        "static void mqtt_relay_lock", 1
    )[0]
    for key in ("wifi_ssid", "wifi_ip", "wifi_rssi"):
        assert key in state_builder
    assert "password" not in state_builder

    updater = source.split("esp_err_t mqtt_relay_update_wifi_status", 1)[1].split(
        "void mqtt_relay_set_wifi_connected", 1
    )[0]
    assert "s_ctx.wifi_status = *status" in updater
    assert "mqtt_relay_build_state_payload" in updater
    assert "mqtt_relay_publish_raw" in updater
    assert "mqtt_relay_publish_retained_status" not in updater
    assert "mqtt_password" not in updater
    assert "mqtt_ca" not in updater
