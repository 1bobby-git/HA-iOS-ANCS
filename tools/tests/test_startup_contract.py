from pathlib import Path


ROOT = Path(__file__).parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_startup_initializes_storage_before_network_and_ble():
    source = read("main/app_main.c")
    app_main = source.split("void app_main(void)", 1)[1]

    nvs = app_main.index("nvs_flash_init")
    store = app_main.index("provision_store_init")
    network = app_main.index("provisioning_runtime_init")
    ancs = app_main.index("ancs_client_init")

    assert nvs < store < network < ancs
    assert nvs < store < ancs


def test_relay_observer_is_registered_before_ancs_can_publish():
    source = read("main/app_main.c")

    observer = source.index("notification_sink_register_observer")
    ancs = source.index("ancs_client_init")

    assert observer < ancs
    assert "mqtt_relay_observe_notification" in source


def test_no_config_boot_opens_recovery_ap():
    source = read("main/app_main.c")

    assert "provision_store_load" in source
    assert "PROVISION_EVENT_BOOT_NO_CONFIG" in source
    assert "provisioning_runtime_start_ap" in source
    assert "state.ap_required" in source


def test_valid_config_does_not_start_a_competing_setup_ap():
    state_header = read("components/provisioning/include/provisioning_state.h")
    state_source = read("components/provisioning/provisioning_state.c")

    assert "bool recovery_required;" in state_header
    reconcile = state_source.split("static void reconcile_requirements", 1)[1].split(
        "provisioning_state_t provisioning_initial", 1
    )[0]
    assert "!state->valid_config" in reconcile
    assert "state->recovery_required" in reconcile
    assert "state->recovery_window" in reconcile
    assert "state->wifi_connected" not in reconcile
    assert "state->mqtt_connected" not in reconcile
    assert "state->has_bond" not in reconcile


def test_mqtt_is_started_only_after_wifi_ip():
    source = read("main/app_main.c")

    handler = source.split("static void handle_provisioning_event", 1)[1].split(
        "static void handle_mqtt_event", 1
    )[0]
    wifi_case = handler.split("case PROVISION_EVENT_WIFI_CONNECTED:", 1)[1].split(
        "break;", 1
    )[0]
    starter = source.split("static esp_err_t start_or_reconnect_mqtt", 1)[1].split(
        "static provisioning_state_t reduce_app_state", 1
    )[0]

    assert "mqtt_relay_set_wifi_connected(true)" in wifi_case
    assert "start_or_reconnect_mqtt()" in wifi_case
    assert "!app.config_valid || !app.state.wifi_connected" in starter
    assert "mqtt_relay_start()" in starter
    assert "mqtt.connected || mqtt.connecting" in starter


def test_mqtt_enroll_request_runs_only_in_the_app_coordinator():
    source = read("main/app_main.c")
    callback = source.split("static void mqtt_event_callback", 1)[1].split(
        "static void boot_held_callback", 1
    )[0]
    handler = source.split("static void handle_mqtt_event", 1)[1].split(
        "static void handle_config_changed", 1
    )[0]

    assert "APP_EVENT_MQTT" in callback
    assert "ancs_client_request_enroll" not in callback
    assert "MQTT_RELAY_EVENT_ENROLL_REQUEST" in handler
    assert "ancs_client_request_enroll();" in handler


def test_wifi_timeout_stops_station_before_starting_recovery_portal():
    source = read("main/app_main.c")
    recovery_helper = source.split("static void enter_wifi_timeout_recovery", 1)[1].split(
        "static void handle_provisioning_event", 1
    )[0]
    handler = source.split("static void handle_provisioning_event", 1)[1].split(
        "static void handle_mqtt_event", 1
    )[0]
    wifi_timeout_case = handler.split(
        "case PROVISION_EVENT_WIFI_TIMEOUT:", 1
    )[1].split("break;", 1)[0]

    assert "enter_wifi_timeout_recovery()" in wifi_timeout_case
    recovery = recovery_helper.index("provisioning_runtime_enter_stable_recovery()")
    offline = recovery_helper.index("mqtt_relay_set_wifi_connected(false)")

    assert recovery < offline


def test_saved_config_waits_for_http_response_grace_period():
    source = read("main/app_main.c")
    handler = source.split("static void handle_config_changed", 1)[1].split(
        "static void handle_reset_provisioning", 1
    )[0]

    null_check = handler.index("if (config == NULL)")
    delay = handler.index("vTaskDelay(pdMS_TO_TICKS(APP_CONFIG_HANDOFF_DELAY_MS))")
    stop = handler.index("stop_mqtt()")
    sta_stop = handler.index("provisioning_runtime_stop_sta()")

    assert "#define APP_CONFIG_HANDOFF_DELAY_MS 750" in source
    assert null_check < delay < stop
    assert delay < sta_stop


def test_wifi_timeout_uses_attempt_generation_for_config_handoff():
    source = read("main/app_main.c")
    event_msg = source.split("typedef struct {", 1)[1].split(
        "} app_event_msg_t;", 1
    )[0]
    post_provisioning = source.split(
        "static void app_post_provisioning", 1
    )[1].split("static void provisioning_event_callback", 1)[0]
    callback = source.split(
        "static void provisioning_event_callback", 1
    )[1].split("static void mqtt_event_callback", 1)[0]
    handler = source.split("static void handle_provisioning_event", 1)[1].split(
        "static void handle_mqtt_event", 1
    )[0]
    recovery_helper = source.split("static void enter_wifi_timeout_recovery", 1)[1].split(
        "static void handle_provisioning_event", 1
    )[0]
    stale_guard = handler.split(
        "if (event == PROVISION_EVENT_WIFI_TIMEOUT", 1
    )[1].split("provisioning_state_t state = reduce_app_state(event);", 1)[0]
    timeout_case = handler.split("case PROVISION_EVENT_WIFI_TIMEOUT:", 1)[1].split(
        "break;", 1
    )[0]
    config_handler = source.split("static void handle_config_changed", 1)[1].split(
        "static void handle_reset_provisioning", 1
    )[0]

    assert "uint32_t sta_attempt_generation;" in event_msg
    assert "uint32_t active_sta_attempt_generation;" in source
    assert "const provisioning_runtime_event_t *runtime_event" in callback
    assert ".provisioning = event" in post_provisioning
    assert ".sta_attempt_generation = sta_attempt_generation" in post_provisioning
    assert "runtime_event->event" in callback
    assert "runtime_event->sta_attempt_generation" in callback
    assert "posted_at_us" not in event_msg
    assert "wifi_timeout_not_before_us" not in source
    assert "active_sta_attempt_generation" in stale_guard
    assert "sta_attempt_generation != active_generation" in stale_guard
    assert "return;" in stale_guard
    assert stale_guard.index("return;") < handler.index(
        "provisioning_state_t state = reduce_app_state(event);"
    )
    assert "enter_wifi_timeout_recovery()" in timeout_case
    assert "active_sta_attempt_generation = 0" in recovery_helper
    assert recovery_helper.index("provisioning_runtime_enter_stable_recovery()") > 0

    start_sta = config_handler.index("provisioning_runtime_start_sta(&s_app.config)")
    status = config_handler.index("provisioning_runtime_get_status(&runtime)")
    active = config_handler.rindex("s_app.active_sta_attempt_generation =")
    assert start_sta < status < active


def test_boot_hold_reaches_recovery_reducer_and_enroll():
    source = read("main/app_main.c")
    ancs_source = read("components/ancs_client/ancs_client.c")
    boot_callback = ancs_source.split(
        "static void enroll_button_callback", 1
    )[1].split("static void discovery_retry_callback", 1)[0]
    boot_event_case = source.split(
        "case PROVISION_EVENT_BOOT_HELD_3S:", 1
    )[1].split("break;", 1)[0]

    assert "PROVISION_EVENT_BOOT_HELD_3S" in source
    assert "boot_held_callback" in boot_callback
    assert "ancs_client_request_enroll();" in boot_callback
    assert "ancs_client_request_enroll" not in boot_event_case
    assert "PROVISION_RECOVERY_WINDOW_MS" in read(
        "components/provisioning/include/provisioning_state.h"
    )


def test_portal_start_failure_rolls_back_the_recovery_ap():
    source = read("main/app_main.c")
    starter = source.split("static esp_err_t start_recovery_portal", 1)[1].split(
        "static void stop_recovery_portal", 1
    )[0]
    failure = starter.split("if (error != ESP_OK)", 2)[2]

    assert "provisioning_runtime_stop_ap()" in failure


def test_provisioning_reset_side_effect_is_owned_by_the_coordinator():
    source = read("main/app_main.c")
    callback = source.split("static esp_err_t portal_reset_provisioning", 1)[1].split(
        "static const portal_http_handlers_t", 1
    )[0]
    coordinator = source.split("static void handle_reset_provisioning", 1)[1].split(
        "static void handle_bond_poll", 1
    )[0]

    assert "provision_store_reset" not in callback
    assert "app_post(&message)" in callback
    assert "provision_store_reset()" in coordinator
    assert coordinator.index("provision_store_reset()") < coordinator.index("stop_mqtt()")
    assert "if (error != ESP_OK)" in coordinator


def test_fatal_initialization_falls_back_to_recovery_portal_without_restart_loop():
    source = read("main/app_main.c")
    app_main = source.split("void app_main(void)", 1)[1]
    runtime_failure = app_main.split("provisioning_runtime_init", 1)[1]

    assert "start_recovery_portal" in source
    assert "start_recovery_portal" in runtime_failure
    assert "esp_restart" not in runtime_failure
    assert "ESP_ERROR_CHECK(" not in source


def test_main_component_declares_all_lifecycle_dependencies():
    cmake = read("main/CMakeLists.txt")
    for component in (
        "ancs_client",
        "mqtt_relay",
        "notification_sink",
        "portal_http",
        "provision_store",
        "provisioning",
    ):
        assert component in cmake


def test_device_metadata_and_wifi_refresh_are_owned_by_the_coordinator():
    source = read("main/app_main.c")

    assert "#define APP_WIFI_STATUS_REFRESH_MS 60000" in source
    assert "APP_EVENT_WIFI_STATUS_REFRESH" in source
    assert "wifi_status_timer_callback" in source
    assert "provisioning_runtime_get_wifi_snapshot" in source
    assert "mqtt_relay_update_wifi_status" in source
    assert "mqtt_relay_update_ble_status" in source
    assert "ancs_client_get_enrollment_status" in source
    assert "esp_app_get_description" in source
    assert "esp_chip_info" in source
    assert "ANCS_DEVICE_MODEL" in source

    callback = source.split("static void wifi_status_timer_callback", 1)[1].split(
        "static void restart_timer_callback", 1
    )[0]
    assert "app_post(&message)" in callback
    assert "provisioning_runtime_get_wifi_snapshot" not in callback
    assert "mqtt_relay_update_wifi_status" not in callback

    refresh = source.split("static esp_err_t refresh_wifi_status", 1)[1].split(
        "static esp_err_t start_or_reconnect_mqtt", 1
    )[0]
    assert "provisioning_runtime_get_wifi_snapshot" in refresh
    assert "mqtt_relay_update_wifi_status" in refresh

    coordinator = source.split("static void coordinator_task", 1)[1].split(
        "static esp_err_t initialize_coordinator", 1
    )[0]
    assert "case APP_EVENT_WIFI_STATUS_REFRESH:" in coordinator
    assert "refresh_wifi_status()" in coordinator

    bond_poll = source.split("static void handle_bond_poll", 1)[1].split(
        "static void coordinator_task", 1
    )[0]
    assert "ancs_client_get_enrollment_status" in bond_poll
    assert "mqtt_relay_update_ble_status" in bond_poll


def test_wifi_refresh_timer_tracks_mqtt_lifecycle():
    source = read("main/app_main.c")

    mqtt_handler = source.split("static void handle_mqtt_event", 1)[1].split(
        "static void handle_config_changed", 1
    )[0]
    connected = mqtt_handler.split("MQTT_RELAY_EVENT_CONNECTED", 1)[1].split(
        "return;", 1
    )[0]
    assert "xTimerReset(s_wifi_status_timer" in connected

    stop_mqtt = source.split("static void stop_mqtt", 1)[1].split(
        "static void schedule_mqtt_retry", 1
    )[0]
    assert "xTimerStop(s_wifi_status_timer" in stop_mqtt

    provisioning_handler = source.split(
        "static void handle_provisioning_event", 1
    )[1].split("static void handle_mqtt_event", 1)[0]
    mqtt_failed = provisioning_handler.split(
        "case PROVISION_EVENT_MQTT_FAILED:", 1
    )[1].split("break;", 1)[0]
    assert "xTimerStop(s_wifi_status_timer" in mqtt_failed

    initializer = source.split("static esp_err_t initialize_coordinator", 1)[1].split(
        "static void log_error", 1
    )[0]
    assert 'xTimerCreate("wifi_status"' in initializer
    assert "pdTRUE" in initializer


def test_mqtt_restart_request_reuses_the_delayed_restart_timer():
    source = read("main/app_main.c")
    handler = source.split("static void handle_mqtt_event", 1)[1].split(
        "static void handle_config_changed", 1
    )[0]
    assert "MQTT_RELAY_EVENT_RESTART_REQUEST" in handler
    assert "schedule_restart()" in handler

    scheduler = source.split("static esp_err_t schedule_restart", 1)[1].split(
        "static esp_err_t portal_restart", 1
    )[0]
    assert "xTimerReset(s_restart_timer" in scheduler
    assert "esp_restart" not in scheduler


def test_main_declares_device_information_dependencies():
    cmake = read("main/CMakeLists.txt")
    for component in ("esp_app_format", "esp_system", "platform_identity"):
        assert component in cmake
