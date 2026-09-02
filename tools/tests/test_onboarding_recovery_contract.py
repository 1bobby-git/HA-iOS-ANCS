from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_portal_can_send_a_synthetic_notification_without_ble():
    html = read("components/portal_http/portal.html")
    script = read("components/portal_http/portal.js")
    source = read("components/portal_http/portal_http.c")
    header = read("components/portal_http/include/portal_http.h")
    relay = read("components/mqtt_relay/mqtt_relay.c")
    relay_header = read("components/mqtt_relay/include/mqtt_relay.h")

    assert 'id="test-notification"' in html
    assert "'/api/notification/test'" in script
    assert '"/api/notification/test"' in source
    assert "test_notification" in header
    assert "mqtt_relay_publish_test_notification" in relay
    assert "mqtt_relay_publish_test_notification" in relay_header
    assert "local.ios_ancs.test" in relay
    assert "테스트 알림" in relay


def test_discovery_is_not_delayed_by_legacy_cleanup():
    source = read("components/mqtt_relay/mqtt_relay.c")

    assert "MQTT_RELAY_DISCOVERY_SETTLE_MS" not in source
    mark = source.index("s_ctx.discovery_attempted_this_boot = true")
    legacy = source.index("mqtt_relay_legacy_discovery_count()", mark)
    aggregate = source.index("mqtt_relay_build_discovery_payload")
    assert aggregate < mark < legacy


def test_mqtt_status_includes_diagnostics_and_bounded_backoff():
    app = read("main/app_main.c")
    relay = read("components/mqtt_relay/mqtt_relay.c")
    relay_header = read("components/mqtt_relay/include/mqtt_relay.h")
    portal = read("components/portal_http/portal_http.c")
    script = read("components/portal_http/portal.js")

    for delay in (
        "APP_MQTT_RETRY_INITIAL_MS 5000U",
        "APP_MQTT_RETRY_SECOND_MS 15000U",
        "APP_MQTT_RETRY_THIRD_MS 30000U",
        "APP_MQTT_RETRY_MAX_MS 60000U",
    ):
        assert delay in app
    assert "xTimerChangePeriod" in app
    assert "mqtt.connected || mqtt.connecting" in app
    assert "mqtt_relay_connection_status_t" in relay_header
    assert "mqtt_relay_capture_error_locked" in relay
    assert "esp_transport_sock_errno" in relay
    assert '"mqtt_last_socket_errno"' in portal
    assert "mqttErrorDetail" in script

    assert "STATUS_POLL_MS = 2000" in script


def test_repeated_ble_auth_failure_stops_the_reconnect_loop():
    client = read("components/ancs_client/ancs_client.c")
    header = read("components/ancs_client/include/ancs_client.h")
    script = read("components/portal_http/portal.js")

    assert "AUTH_FAILURE_REPAIR_THRESHOLD 3U" in client
    assert "AUTH_FAILURE_WINDOW_MS 120000LL" in client
    assert "pairing_repair_required" in client
    assert "pairing_repair_required" in header
    assert "pairing repair required" in client
    assert "if (repair_required)" in client
    assert "schedule_advertising_retry();" in client
    repair = client.split("if (repair_required)", 1)[1].split("} else {", 1)[0]
    assert "stop_advertising();" in repair
    assert "schedule_advertising_retry" not in repair
    assert "ble_pairing_repair_required" in script
    assert "등록 복구 필요" in script


def test_portal_reclaims_stale_http_connections():
    source = read("components/portal_http/portal_http.c")

    assert "PORTAL_HTTP_SERVER_STACK_SIZE 8192" in source
    assert "config.stack_size = PORTAL_HTTP_SERVER_STACK_SIZE" in source
    assert "config.max_open_sockets = 7" in source
    assert "config.lru_purge_enable = true" in source
    assert "config.recv_wait_timeout = 5" in source
    assert "config.send_wait_timeout = 5" in source
    assert '"/favicon.ico"' in source


def test_fixed_passkey_and_ap_hardening_are_enabled():
    credentials = read("components/device_credentials/device_credentials.c")
    client = read("components/ancs_client/ancs_client.c")
    runtime = read("components/provisioning/provisioning_runtime.c")

    assert "#define DEVICE_CREDENTIALS_BLE_PASSKEY 123456U" in credentials
    assert "esp_fill_random" not in credentials
    assert "device_credentials_ble_passkey()" in client
    assert "123456" not in client
    assert "#define PROVISIONING_AP_MAX_CLIENTS 2" in runtime
    assert "ap_config->ap.pmf_cfg.capable = true" in runtime



def test_config_save_keeps_portal_open_for_verification_only():
    source = read("main/app_main.c")
    handler = source.split("static void handle_config_changed", 1)[1].split(
        "static void handle_reset_provisioning", 1
    )[0]
    app_main = source.split("void app_main(void)", 1)[1]

    assert "PROVISION_EVENT_BOOT_HELD_3S" in handler
    assert "10-minute verification window" in handler
    assert "PROVISION_EVENT_BOOT_HELD_3S" not in app_main



def test_repair_guard_requires_explicit_replace_enrollment():
    client = read("components/ancs_client/ancs_client.c")
    request = client.split("esp_err_t ancs_client_request_enroll", 1)[1].split(
        "esp_err_t ancs_client_replace_enrollment", 1
    )[0]
    replace_enrollment = client.split(
        "esp_err_t ancs_client_replace_enrollment", 1
    )[1].split("uint32_t ancs_client_ble_passkey", 1)[0]

    assert "repair_required" in request
    assert "return ESP_ERR_INVALID_STATE" in request
    assert "clear_auth_failure_guard_locked" not in request
    assert "clear_auth_failure_guard_locked" in replace_enrollment


def test_mqtt_backoff_is_scheduled_only_once_per_failure_cycle():
    app = read("main/app_main.c")
    scheduler = app.split("static void schedule_mqtt_retry", 1)[1].split(
        "static esp_err_t refresh_wifi_status", 1
    )[0]

    assert "xTimerIsTimerActive" in scheduler
    assert scheduler.index("xTimerIsTimerActive") < scheduler.index(
        "s_app.mqtt_retry_attempt"
    )


def test_ble_passkey_pointer_matches_esp_idf_mutable_api():
    client = read("components/ancs_client/ancs_client.c")
    security = client.split("static esp_err_t configure_security", 1)[1].split(
        "static bool configure_button", 1
    )[0]

    assert "uint32_t static_passkey = device_credentials_ble_passkey();" in security
    assert "const uint32_t static_passkey" not in security



def test_generated_c_sources_do_not_contain_literal_nul_bytes():
    for pattern in ("*.c", "*.h"):
        for path in ROOT.rglob(pattern):
            assert "\x00" not in path.read_text(encoding="utf-8"), path

    app = read("main/app_main.c")
    assert r"device_name[0] == '\0'" in app



def test_existing_portal_contracts_match_new_verification_window():
    script = read("components/portal_http/portal.js")
    provisioning = read("components/provisioning/provisioning_runtime.c")

    assert "설정 포털은 테스트를 위해 10분간 유지" in script
    assert "esp_wifi_disable_pmf_config(WIFI_IF_AP)" not in provisioning


def test_device_credentials_use_fixed_pairing_pin_without_nvs():
    credentials = read("components/device_credentials/device_credentials.c")
    component = read("components/device_credentials/CMakeLists.txt")

    assert "#define DEVICE_CREDENTIALS_BLE_PASSKEY 123456U" in credentials
    assert "device_credentials_init" in credentials
    assert "esp_fill_random" not in credentials
    assert "nvs_" not in credentials
    assert "nvs_flash" not in component
    assert "esp_hw_support" not in component



def test_wifi_reconnect_uses_signal_sorting_driver_retries_and_bounded_recovery():
    runtime = read("components/provisioning/provisioning_runtime.c")
    header = read("components/provisioning/include/provisioning_runtime.h")

    assert 'PROVISIONING_RUNTIME_WIFI_TIMEOUT_MS 45000' in header
    assert 'WIFI_CONNECT_AP_BY_SIGNAL' in runtime
    assert 'failure_retry_cnt = PROVISIONING_STA_FAILURE_RETRY_COUNT' in runtime
    assert 'threshold.rssi = PROVISIONING_STA_MIN_RSSI' in runtime
    assert 'set_wifi_mode_with_retry' in runtime
    assert 'start_reconnect_timeout = true' in runtime
