import json
from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def render_portal_status(status):
    portal_js = ROOT / "components/portal_http/portal.js"
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const source = fs.readFileSync({json.dumps(str(portal_js))}, 'utf8');
        const elements = new Map();
        function makeElement() {{
          return {{
            value: '',
            checked: false,
            disabled: false,
            textContent: '',
            innerHTML: '',
            className: '',
            dataset: {{}},
            classList: {{ add() {{}}, remove() {{}}, toggle() {{}} }},
            appendChild() {{}},
            addEventListener() {{}},
            setAttribute() {{}},
            removeAttribute() {{}},
          }};
        }}
        global.document = {{
          getElementById(id) {{
            if (!elements.has(id)) elements.set(id, makeElement());
            return elements.get(id);
          }},
          createElement() {{ return makeElement(); }},
        }};
        global.fetch = async () => ({{
          ok: true,
          statusText: 'OK',
          json: async () => ({json.dumps(status)}),
        }});
        eval(source);
        setTimeout(() => {{
          process.stdout.write(JSON.stringify({{
            clientId: elements.get('mqtt-client-id').value,
            baseTopic: elements.get('mqtt-base-topic').value,
          }}));
        }}, 20);
        """
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        encoding="utf-8",
        timeout=5,
    )
    return json.loads(result.stdout)


def render_portal_ble_status(system_overrides):
    status = {
        "configured": False,
        "config": {},
        "runtime": {
            "ap_started": True,
            "sta_started": False,
            "sta_connecting": False,
            "sta_has_ip": False,
            "ap_ssid": "IOS-ANCS-SETUP-A1B2C3",
        },
        "system": {
            "mqtt_connected": False,
            "ble_bonded": False,
            "ble_connected": False,
            "enroll_window_open": False,
            "notifications_published": 0,
            "notifications_dropped": 0,
            **system_overrides,
        },
    }
    portal_js = ROOT / "components/portal_http/portal.js"
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const source = fs.readFileSync({json.dumps(str(portal_js))}, 'utf8');
        const elements = new Map();
        function makeElement() {{
          return {{
            value: '',
            checked: false,
            disabled: false,
            textContent: '',
            innerHTML: '',
            className: '',
            dataset: {{}},
            classList: {{ add() {{}}, remove() {{}}, toggle() {{}} }},
            appendChild() {{}},
            addEventListener() {{}},
            setAttribute() {{}},
            removeAttribute() {{}},
          }};
        }}
        global.document = {{
          getElementById(id) {{
            if (!elements.has(id)) elements.set(id, makeElement());
            return elements.get(id);
          }},
          createElement() {{ return makeElement(); }},
        }};
        global.fetch = async () => ({{
          ok: true,
          statusText: 'OK',
          json: async () => ({json.dumps(status)}),
        }});
        eval(source);
        setTimeout(() => {{
          process.stdout.write(JSON.stringify({{
            value: elements.get('status-ble-value').textContent,
            detail: elements.get('status-ble-detail').textContent,
            guidance: elements.get('ble-guidance').textContent,
          }}));
        }}, 20);
        """
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        encoding="utf-8",
        timeout=5,
    )
    return json.loads(result.stdout)


def test_task6_wifi_runtime_source_contracts():
    runtime = read("components/provisioning/provisioning_runtime.c")
    header = read("components/provisioning/include/provisioning_runtime.h")
    dns = read("components/provisioning/captive_dns.c")

    assert "esp_netif_create_default_wifi_ap" in runtime
    assert "WIFI_MODE_APSTA" in runtime
    assert "WIFI_MODE_STA" in runtime
    assert "WIFI_MODE_AP" in runtime
    assert "WIFI_MODE_NULL" in runtime
    assert "WIFI_PROTOCOL_11B | WIFI_PROTOCOL_11G | WIFI_PROTOCOL_11N" in runtime
    assert "ap_config->ap.pairwise_cipher = WIFI_CIPHER_TYPE_CCMP" in runtime
    assert "ap_config->ap.pmf_cfg.capable = true" in runtime
    assert "esp_wifi_set_protocol(\n            WIFI_IF_STA," in runtime
    assert "esp_wifi_set_bandwidth(WIFI_IF_STA, WIFI_BW20)" in runtime
    assert "esp_wifi_set_ps(WIFI_PS_NONE)" in runtime
    start_sta = runtime.split(
        "esp_err_t provisioning_runtime_start_sta", 1
    )[1].split("esp_err_t provisioning_runtime_stop_sta", 1)[0]
    assert start_sta.index("lock_wifi_operation()") < start_sta.index(
        "err = apply_wifi_mode_unlocked()"
    )
    assert start_sta.index("err = apply_wifi_mode_unlocked()") < start_sta.index(
        "esp_wifi_set_protocol("
    )
    assert "last_wifi_disconnect_reason" in header
    assert "wifi_event_sta_disconnected_t *disconnected" in runtime
    assert "s_last_wifi_disconnect_reason = disconnected->reason" in runtime
    assert "s_last_wifi_disconnect_rssi = disconnected->rssi" in runtime
    assert '"STA disconnected reason=%u rssi=%d"' in runtime
    assert "const bool had_ip = s_sta_has_ip" in runtime
    assert "if (had_ip)" in runtime
    assert "dispatch_event_with_generation(PROVISION_EVENT_WIFI_TIMEOUT" in runtime
    disconnected_case = runtime.split(
        "event_id == WIFI_EVENT_STA_DISCONNECTED", 1
    )[1].split("IP_EVENT_STA_GOT_IP", 1)[0]
    assert "xTimerReset(s_wifi_timeout_timer, 0)" not in disconnected_case
    had_ip_block = disconnected_case.split("if (had_ip)", 1)[1].split("unlock_state()", 1)[0]
    assert "s_sta_connecting = false" in had_ip_block
    assert "reconnect = false" in had_ip_block
    assert "s_sta_started = false" in had_ip_block
    reconnect_block = disconnected_case.split("else if (s_sta_started && s_sta_connecting)", 1)[1]
    assert "s_sta_connecting = true" in reconnect_block
    assert "reconnect = true" in reconnect_block
    assert "out->last_wifi_disconnect_reason = s_last_wifi_disconnect_reason" in runtime
    assert "out->last_wifi_disconnect_rssi = s_last_wifi_disconnect_rssi" in runtime
    portal = read("components/portal_http/portal_http.c")
    assert '"last_wifi_disconnect_reason"' in portal
    assert '"last_wifi_disconnect_rssi"' in portal
    assert "esp_wifi_disable_pmf_config(WIFI_IF_AP)" not in runtime
    assert "esp_wifi_scan_get_ap_records" in runtime
    assert "192.168.4.1" in runtime
    assert "ESP_NETIF_CAPTIVEPORTAL_URI" in runtime
    assert "static char s_captiveportal_uri[]" in runtime
    assert "strlen(s_captiveportal_uri)" in runtime
    assert "provisioning_runtime_init" in header
    assert "provisioning_runtime_enter_stable_recovery" in header
    assert "provisioning_runtime_start_ap" in header
    assert "provisioning_runtime_start_sta" in header
    assert "provisioning_runtime_scan" in header
    assert "provisioning_runtime_notify_mqtt_failed" in header
    assert "PROVISION_EVENT_WIFI_TIMEOUT" in runtime
    assert "PROVISION_EVENT_MQTT_FAILED" in runtime
    assert "PROVISIONING_RUNTIME_AP_PASSWORD_PREFIX" in header
    assert "s_ap_password" in runtime
    assert "esp_read_mac(mac, ESP_MAC_WIFI_STA)" in runtime
    assert "ESP_RETURN_ON_ERROR(make_ap_identity()" in runtime
    assert "ANCS-A1B2C3" not in runtime
    assert "xTaskCreate(wifi_timeout_task" in runtime
    assert "s_wifi_handler_instance" in runtime
    assert "s_ip_handler_instance" in runtime
    assert "xQueueCreate(PROVISIONING_EVENT_QUEUE_LEN" in runtime
    assert "xTaskCreate(event_callback_task" in runtime
    assert "xQueueSend(s_event_queue" in runtime
    assert "s_event_overflow_count" in runtime
    assert "portMUX_TYPE s_state_lock" in runtime
    assert "taskENTER_CRITICAL(&s_state_lock)" in runtime
    assert "taskEXIT_CRITICAL(&s_state_lock)" in runtime
    assert "SemaphoreHandle_t s_wifi_operation_mutex" in runtime
    assert "xSemaphoreCreateMutex" in runtime
    assert "xSemaphoreTake(s_wifi_operation_mutex" in runtime
    assert "xSemaphoreGive(s_wifi_operation_mutex)" in runtime
    assert "lock_state()" in runtime
    assert "wildcard" in dns.lower()
    assert "SO_RCVTIMEO" in dns
    assert "memcpy(&qtype" in dns
    assert "handle->started = false" in dns
    assert "while (s_dns.task != NULL)" in dns
    assert "qd_count != 1" in dns
    assert "size_t question_len = (size_t)(question_end + 4 - reply)" in dns
    assert "reply + question_len" in dns
    assert "header->ar_count = 0" in dns
    assert "header->ns_count = 0" in dns
    assert "int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP)" in dns
    assert "bind(sock, (struct sockaddr *)&bind_addr, sizeof(bind_addr))" in dns
    assert dns.index("int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP)") < dns.index("xTaskCreate(captive_dns_task")


def test_task6_runtime_starts_network_before_dispatching_boot_state():
    runtime = read("components/provisioning/provisioning_runtime.c")
    init = runtime.split("esp_err_t provisioning_runtime_init", 1)[1].split(
        "esp_err_t provisioning_runtime_start_ap", 1
    )[0]

    valid = init.split(
        "if (provision_config_validate(config) == PROVISION_CONFIG_OK)", 1
    )[1].split("dispatch_event(PROVISION_EVENT_BOOT_NO_CONFIG)", 1)[0]
    assert valid.index("provisioning_runtime_start_sta(config)") < valid.index(
        "dispatch_event(PROVISION_EVENT_BOOT_VALID_CONFIG)"
    )
    assert init.index("provisioning_runtime_start_ap()") < init.index(
        "dispatch_event(PROVISION_EVENT_BOOT_NO_CONFIG)"
    )


def test_task6_runtime_init_failure_cleans_partial_resources():
    runtime = read("components/provisioning/provisioning_runtime.c")
    ready = runtime.split("static esp_err_t ensure_runtime_ready", 1)[1].split(
        "static esp_err_t ensure_wifi_started", 1
    )[0]

    assert "goto init_failed;" in ready
    assert "init_failed:" in ready
    cleanup = ready.split("init_failed:", 1)[1]
    assert "esp_event_loop_delete_default" not in cleanup
    assert "esp_event_handler_instance_unregister(WIFI_EVENT" in cleanup
    assert "esp_event_handler_instance_unregister(IP_EVENT" in cleanup
    assert "esp_wifi_deinit()" in cleanup
    assert "esp_netif_destroy_default_wifi(s_sta_netif)" in cleanup
    assert "esp_netif_destroy_default_wifi(s_ap_netif)" in cleanup
    assert "vSemaphoreDelete(s_wifi_operation_mutex)" in cleanup
    assert "vTaskDelete(s_wifi_timeout_task)" in cleanup
    assert "vTaskDelete(s_event_task)" in cleanup
    assert "vQueueDelete(s_event_queue)" in cleanup
    assert cleanup.index("vTaskDelete(s_wifi_timeout_task)") < cleanup.index(
        "vTaskDelete(s_event_task)"
    )
    assert cleanup.index("vTaskDelete(s_event_task)") < cleanup.index(
        "vQueueDelete(s_event_queue)"
    )
    for reset in [
        "s_wifi_handler_instance = NULL",
        "s_ip_handler_instance = NULL",
        "s_ap_netif = NULL",
        "s_sta_netif = NULL",
        "s_wifi_operation_mutex = NULL",
        "s_wifi_timeout_task = NULL",
        "s_event_task = NULL",
        "s_event_queue = NULL",
        "s_initialized = false",
        "s_wifi_started = false",
        "s_ap_started = false",
        "s_sta_started = false",
        "s_sta_connecting = false",
        "s_sta_has_ip = false",
        "s_active_sta_attempt_generation = 0",
    ]:
        assert reset in cleanup
    assert "return err;" in cleanup


def test_task6_sta_disconnect_revalidates_reconnect_after_operation_lock():
    runtime = read("components/provisioning/provisioning_runtime.c")
    disconnected_case = runtime.split(
        "event_id == WIFI_EVENT_STA_DISCONNECTED", 1
    )[1].split("IP_EVENT_STA_GOT_IP", 1)[0]
    reconnect_block = disconnected_case.split("if (reconnect)", 1)[1].split(
        "} else if", 1
    )[0]

    assert "const uint32_t attempt_generation = s_active_sta_attempt_generation" in disconnected_case
    assert "lock_wifi_operation()" in reconnect_block
    assert "const bool reconnect_still_valid" in reconnect_block
    assert "s_sta_started && s_sta_connecting" in reconnect_block
    assert "s_active_sta_attempt_generation == attempt_generation" in reconnect_block
    assert reconnect_block.index("lock_wifi_operation()") < reconnect_block.index(
        "lock_state()"
    )
    assert reconnect_block.index("lock_state()") < reconnect_block.index(
        "unlock_state()"
    )
    assert reconnect_block.index("unlock_state()") < reconnect_block.index(
        "esp_wifi_connect()"
    )
    assert "if (reconnect_still_valid)" in reconnect_block
    assert reconnect_block.index("esp_wifi_connect()") < reconnect_block.index(
        "unlock_wifi_operation()"
    )


def test_task6_wifi_timeout_binds_origin_attempt_generation():
    runtime = read("components/provisioning/provisioning_runtime.c")
    header = read("components/provisioning/include/provisioning_runtime.h")
    start_sta = runtime.split(
        "esp_err_t provisioning_runtime_start_sta", 1
    )[1].split("esp_err_t provisioning_runtime_stop_sta", 1)[0]
    timeout_task = runtime.split("static void wifi_timeout_task", 1)[1].split(
        "static esp_err_t create_default_event_loop_once", 1
    )[0]
    disconnected_case = runtime.split(
        "event_id == WIFI_EVENT_STA_DISCONNECTED", 1
    )[1].split("IP_EVENT_STA_GOT_IP", 1)[0]
    callback_task = runtime.split("static void event_callback_task", 1)[1].split(
        "static void dispatch_event", 1
    )[0]

    assert "typedef struct {" in header
    assert "provisioning_runtime_event_t" in header
    assert "provisioning_event_t event;" in header
    assert "uint32_t sta_attempt_generation;" in header
    assert "provisioning_runtime_event_t event" in runtime
    assert "s_next_sta_attempt_generation" in runtime
    assert "s_active_sta_attempt_generation" in runtime
    assert "s_wifi_timeout_task" in runtime
    assert "next_sta_attempt_generation" in runtime
    assert "if (generation == 0)" in runtime
    assert start_sta.index("next_sta_attempt_generation()") < start_sta.index(
        "s_sta_started = true"
    )
    assert "s_active_sta_attempt_generation = attempt_generation" in start_sta
    assert "s_active_sta_attempt_generation = 0" in start_sta
    assert "schedule_wifi_timeout(attempt_generation)" in start_sta
    assert "cancel_wifi_timeout()" in start_sta
    assert "callback(&msg.event, context)" in callback_task
    assert "uint32_t pending_generation = 0" in timeout_task
    assert "const uint32_t expired_generation = pending_generation" in timeout_task
    assert "s_active_sta_attempt_generation == expired_generation" in timeout_task
    assert "s_sta_started && s_sta_connecting" in timeout_task
    assert "dispatch_event_with_generation(PROVISION_EVENT_WIFI_TIMEOUT, expired_generation)" in timeout_task
    assert "dispatch_event_with_generation(PROVISION_EVENT_WIFI_TIMEOUT, attempt_generation)" not in timeout_task
    assert "wifi_timeout_timer_cb" not in runtime
    assert "xTimerReset(s_wifi_timeout_timer" not in runtime
    assert "xTimerStop(s_wifi_timeout_timer" not in runtime
    assert "TimerHandle_t s_wifi_timeout_timer" not in runtime
    assert "const uint32_t attempt_generation = s_active_sta_attempt_generation" in disconnected_case
    assert "dispatch_event_with_generation(PROVISION_EVENT_WIFI_TIMEOUT, attempt_generation)" in disconnected_case
    assert "out->sta_attempt_generation = s_active_sta_attempt_generation" in runtime


def test_task6_ap_security_is_configured_before_wifi_start():
    runtime = read("components/provisioning/provisioning_runtime.c")
    ready = runtime.split("static esp_err_t ensure_runtime_ready", 1)[1].split(
        "static esp_err_t ensure_wifi_started", 1
    )[0]
    profile = runtime.split(
        "static esp_err_t configure_ap_profile_before_wifi_start", 1
    )[1].split("static esp_err_t configure_ap_ip_and_dhcp", 1)[0]

    assert "configure_ap_profile_before_wifi_start()" in ready
    assert "esp_wifi_start()" not in ready
    assert "esp_wifi_set_config(WIFI_IF_AP" in profile
    assert "esp_wifi_disable_pmf_config(WIFI_IF_AP)" not in profile
    assert "esp_wifi_set_bandwidth(WIFI_IF_AP, WIFI_BW20)" in profile


def test_task6_runtime_does_not_log_secrets():
    runtime = read("components/provisioning/provisioning_runtime.c")

    forbidden_fragments = [
        "wifi_password",
        "mqtt_password",
        "config->wifi_password",
        "config->mqtt_password",
        "password:%s",
    ]
    log_lines = [
        line for line in runtime.splitlines()
        if "ESP_LOG" in line or "printf" in line
    ]
    joined_logs = "\n".join(log_lines)
    for fragment in forbidden_fragments:
        assert fragment not in joined_logs


def test_task6_scan_rejects_while_sta_connecting():
    runtime = read("components/provisioning/provisioning_runtime.c")

    assert "s_sta_connecting" in runtime
    assert "ESP_ERR_INVALID_STATE" in runtime
    assert "esp_wifi_scan_start" in runtime
    assert "esp_wifi_scan_get_ap_num" in runtime
    assert "esp_wifi_clear_ap_list" in runtime
    assert "threshold.authmode = WIFI_AUTH_OPEN" in runtime
    assert "schedule_wifi_timeout(attempt_generation)" in runtime
    assert runtime.count("schedule_wifi_timeout(attempt_generation)") == 1
    scan = runtime.split("esp_err_t provisioning_runtime_scan", 1)[1].split(
        "esp_err_t provisioning_runtime_notify_mqtt_failed", 1
    )[0]
    assert ".min =" not in scan
    assert ".max =" not in scan
    assert ".home_chan_dwell_time = 30" in scan
    assert ".coex_background_scan = true" in scan


def test_task6_timeout_disables_late_reconnect_and_stale_got_ip():
    runtime = read("components/provisioning/provisioning_runtime.c")
    timeout = runtime.split("static void wifi_timeout_task", 1)[1].split(
        "static esp_err_t create_default_event_loop_once", 1
    )[0]
    disconnected_case = runtime.split(
        "event_id == WIFI_EVENT_STA_DISCONNECTED", 1
    )[1].split("IP_EVENT_STA_GOT_IP", 1)[0]
    got_ip_case = runtime.split(
        "event_id == IP_EVENT_STA_GOT_IP", 1
    )[1].split("static esp_err_t ensure_runtime_ready", 1)[0]

    assert "s_sta_started = false" in timeout
    assert "s_sta_connecting = false" in timeout
    assert "else if (s_sta_started && s_sta_connecting)" in disconnected_case
    assert "const bool accept_ip = s_sta_started && s_sta_connecting" in got_ip_case
    assert "if (!accept_ip)" in got_ip_case
    assert got_ip_case.index("if (!accept_ip)") < got_ip_case.index(
        "dispatch_event_with_generation(PROVISION_EVENT_WIFI_CONNECTED"
    )


def test_task6_recovery_enters_ap_only_and_scans_with_temporary_sta():
    runtime = read("components/provisioning/provisioning_runtime.c")
    mode = runtime.split("static esp_err_t apply_wifi_mode", 1)[1].split(
        "esp_err_t provisioning_runtime_init", 1
    )[0]
    scan = runtime.split("esp_err_t provisioning_runtime_scan", 1)[1].split(
        "esp_err_t provisioning_runtime_notify_mqtt_failed", 1
    )[0]
    stop_sta = runtime.split("esp_err_t provisioning_runtime_stop_sta", 1)[1].split(
        "esp_err_t provisioning_runtime_enter_stable_recovery", 1
    )[0]
    recovery = runtime.split(
        "esp_err_t provisioning_runtime_enter_stable_recovery", 1
    )[1].split("esp_err_t provisioning_runtime_notify_mqtt_failed", 1)[0]

    assert "if (ap_started && sta_started)" in mode
    assert "mode = WIFI_MODE_APSTA;" in mode.split("if (ap_started && sta_started)", 1)[1]
    assert "else if (ap_started)" in mode
    assert "mode = WIFI_MODE_AP;" in mode.split("else if (ap_started)", 1)[1]
    assert "else if (sta_started)" in mode
    assert "mode = WIFI_MODE_STA;" in mode.split("else if (sta_started)", 1)[1]
    assert "WIFI_MODE_NULL" in mode

    assert recovery.index("provisioning_runtime_stop_sta()") < recovery.index(
        "provisioning_runtime_start_ap()"
    )
    assert "s_sta_started = false" in stop_sta
    assert "s_sta_connecting = false" in stop_sta

    assert "wifi_mode_t original_mode" in scan
    assert "esp_wifi_get_mode(&original_mode)" in scan
    assert "original_mode == WIFI_MODE_AP" in scan
    assert "esp_wifi_set_mode(WIFI_MODE_APSTA)" in scan
    assert "finish_scan_restore_if_needed" in scan
    assert scan.index("esp_wifi_set_mode(WIFI_MODE_APSTA)") < scan.index(
        "esp_wifi_scan_start"
    )
    assert scan.index("esp_wifi_clear_ap_list") < scan.rindex(
        "finish_scan_restore_if_needed"
    )
    assert "restore_err" in runtime


def test_task6_scan_serializes_mode_changes_and_restores_current_flags():
    runtime = read("components/provisioning/provisioning_runtime.c")
    scan = runtime.split("esp_err_t provisioning_runtime_scan", 1)[1].split(
        "esp_err_t provisioning_runtime_notify_mqtt_failed", 1
    )[0]
    helper = runtime.split(
        "static esp_err_t finish_scan_restore_if_needed", 1
    )[1].split("esp_err_t provisioning_runtime_scan", 1)[0]

    assert "s_wifi_operation_mutex" in runtime
    assert scan.index("lock_wifi_operation()") < scan.index(
        "esp_wifi_set_mode(WIFI_MODE_APSTA)"
    )
    assert scan.index("esp_wifi_scan_start") < scan.rindex(
        "unlock_wifi_operation()"
    )
    assert "finish_scan_restore_if_needed" in scan
    assert "apply_wifi_mode_unlocked()" in helper
    assert "esp_wifi_set_mode(WIFI_MODE_AP)" not in helper
    assert "original_mode" not in helper


def test_task7_embedded_portal_assets_and_controls():
    cmake = read("components/portal_http/CMakeLists.txt")
    manifest = read("main/idf_component.yml")
    html = read("components/portal_http/portal.html")
    css = read("components/portal_http/portal.css")
    js = read("components/portal_http/portal.js")

    assert "espressif/cjson" in manifest
    assert "espressif__cjson" in cmake
    assert "EMBED_FILES" in cmake
    assert "portal.html" in cmake
    assert "portal.css" in cmake
    assert "portal.js" in cmake
    for forbidden in ["https://", "http://", "cdn", "unpkg", "jsdelivr"]:
        assert forbidden not in html.lower()
        assert forbidden not in css.lower()
        assert forbidden not in js.lower()
    for control in [
        'id="status"',
        'id="wifi-config"',
        'id="scan-wifi"',
        'id="wifi-ssid"',
        'id="wifi-password"',
        'id="mqtt-config"',
        'id="mqtt-host"',
        'id="mqtt-port"',
        'id="mqtt-username"',
        'id="mqtt-password"',
        'id="mqtt-tls"',
        'id="mqtt-ca"',
        'id="test-notification"',
        'id="replace-confirmation"',
        'id="replace-enrollment"',
        'id="restart"',
        'id="reset-confirmation"',
        'id="reset-provisioning"',
    ]:
        assert control in html
    assert "fetch('/api/status'" in js
    assert "fetch('/api/wifi/scan')" in js
    assert "'/api/config'" in js
    assert "const confirmation = $('replace-confirmation').value" in js
    assert "const confirmation = $('reset-confirmation').value" in js
    assert "JSON.stringify({ confirmation: 'REPLACE ENROLLMENT' })" not in js
    assert "JSON.stringify({ confirmation: 'RESET PROVISIONING' })" not in js


def test_portal_moves_ordinary_enrollment_to_home_assistant():
    html = read("components/portal_http/portal.html")
    script = read("components/portal_http/portal.js")
    source = read("components/portal_http/portal_http.c")
    header = read("components/portal_http/include/portal_http.h")

    assert 'id="enroll"' not in html
    assert "$('enroll').addEventListener" not in script
    assert '"/api/ble/enroll"' not in source
    assert "ble_enroll" not in header
    assert 'id="replace-enrollment"' in html
    assert '"/api/ble/replace"' in source
    assert "Home Assistant" in html
    assert "BOOT" in html


def test_portal_exposes_a_compact_korean_guided_setup():
    html = read("components/portal_http/portal.html")
    css = read("components/portal_http/portal.css")

    assert '<html lang="ko">' in html
    assert 'aria-live="polite"' in html
    assert 'id="device-name"' in html
    for status_id in [
        "status-wifi",
        "status-mqtt",
        "status-ble",
        "status-relay",
    ]:
        assert f'id="{status_id}"' in html
    assert 'id="advanced-mqtt"' in html
    assert 'id="mqtt-client-id-help"' in html
    assert 'id="mqtt-base-topic-help"' in html
    assert 'id="device-management"' in html
    assert "권장값" in html
    assert "--color-primary" in css
    assert ":focus-visible" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "max-width: 840px" in css
    assert "word-break: keep-all" in css


def test_portal_explains_ble_silence_and_network_handoff():
    js = read("components/portal_http/portal.js")
    html = read("components/portal_http/portal.html")

    assert "미등록 · 광고 꺼짐" in js
    assert "등록된 iPhone만 자동으로 다시 연결" in js
    assert "설정 포털은 테스트를 위해 10분간 유지" in js
    assert "연결에 실패하면 설정 AP가 자동으로 다시 나타납니다" in js
    assert "등록 전에는 Bluetooth 등록 신호를 보내지 않습니다" in html


def test_portal_renders_ble_status_for_all_runtime_states():
    assert render_portal_ble_status({})["value"] == "미등록 · 광고 꺼짐"
    assert render_portal_ble_status({"enroll_window_open": True})["value"] == "등록 대기"
    assert render_portal_ble_status({"ble_bonded": True})["value"] == "등록됨 · 연결 대기"
    assert render_portal_ble_status({"ble_connected": True})["value"] == "연결됨"


def test_portal_enrollment_guidance_names_the_exact_iphone_bluetooth_entry():
    rendered = render_portal_ble_status({"enroll_window_open": True})

    assert "IOS-ANCS-C6-B2C3" in rendered["guidance"]
    assert "Bluetooth 설정" in rendered["guidance"]


def test_portal_applies_recommended_identifiers_from_device_suffix():
    rendered = render_portal_status(
        {
            "configured": False,
            "config": {},
            "runtime": {
                "ap_started": True,
                "sta_started": False,
                "sta_connecting": False,
                "sta_has_ip": False,
                "ap_ssid": "IOS-ANCS-SETUP-A1B2C3",
            },
            "system": {
                "mqtt_connected": False,
                "ble_bonded": False,
                "ble_connected": False,
                "enroll_window_open": False,
                "notifications_published": 0,
                "notifications_dropped": 0,
            },
        }
    )

    assert rendered == {
        "clientId": "ios_ancs_c6_b2c3",
        "baseTopic": "ios-ancs/c6-b2c3",
    }


def test_portal_preserves_existing_custom_identifiers():
    rendered = render_portal_status(
        {
            "configured": True,
            "config": {
                "mqtt_client_id": "livingroom_ancs",
                "mqtt_base_topic": "home/livingroom/ancs",
            },
            "runtime": {"ap_ssid": "IOS-ANCS-SETUP-A1B2C3"},
            "system": {},
        }
    )

    assert rendered == {
        "clientId": "livingroom_ancs",
        "baseTopic": "home/livingroom/ancs",
    }


def test_task7_http_routes_and_captive_probes():
    source = read("components/portal_http/portal_http.c")
    header = read("components/portal_http/include/portal_http.h")

    for route in [
        '"/api/status"',
        '"/api/wifi/scan"',
        '"/api/config"',
        '"/api/mqtt/test"',
        '"/api/notification/test"',
        '"/favicon.ico"',
        '"/api/ble/replace"',
        '"/api/restart"',
        '"/api/reset"',
        '"/hotspot-detect.html"',
        '"/library/test/success.html"',
        '"/ncsi.txt"',
        '"/connecttest.txt"',
        '"/generate_204"',
        '"/gen_204"',
    ]:
        assert route in source
    assert "http://192.168.4.1" in source
    assert "HTTPD_404_NOT_FOUND" in source
    assert "portal_http_handlers_t" in header
    assert "mqtt_test" in header
    assert "test_notification" in header
    assert "reconnect" in header
    assert "ble_replace" in header


def test_task7_mutating_handlers_are_ap_local_and_bounded():
    source = read("components/portal_http/portal_http.c")
    sdkconfig = read("sdkconfig")

    assert "PORTAL_HTTP_MAX_POST_BODY 8192" in source
    assert '#define PORTAL_HTTP_AP_HOST "192.168.4.1"' in source
    assert "CONFIG_LWIP_IPV6=y" in sdkconfig
    assert "require_ap_local_request" in source
    for handler in [
        "handle_config_post",
        "handle_empty_action_post",
        "handle_ble_replace_post",
        "handle_reset_post",
    ]:
        block = source[source.index(f"static esp_err_t {handler}"):
                       source.index("}", source.index(f"static esp_err_t {handler}"))]
        assert "require_ap_local_request(req)" in block
    assert "cJSON_ParseWithLengthOpts" in source
    assert "parse_end" in source
    assert "trailing_garbage" in source
    assert "cJSON_IsString" in source
    assert "cJSON_IsNumber" in source
    assert "cJSON_IsBool" in source
    assert "PROVISION_MQTT_CA_MAX" in source
    guard = source.split("static esp_err_t require_ap_local_request", 1)[1].split(
        "static const char *skip_space_const", 1
    )[0]
    assert "httpd_req_to_sockfd(req)" in guard
    assert "sockaddr_storage" in guard
    assert "socklen_t" in guard
    assert "getsockname" in guard
    assert "AF_INET" in guard
    assert "sizeof(struct sockaddr_in)" in guard
    assert "sin_addr.s_addr" in guard
    assert "inet_addr(PORTAL_HTTP_AP_HOST)" in guard
    assert "AF_INET6" in guard
    assert "sizeof(struct sockaddr_in6)" in guard
    assert "IN6_IS_ADDR_V4MAPPED" in guard
    assert "s6_addr[12]" in guard
    assert "memcmp" in guard
    assert 'httpd_req_get_hdr_value_len(req, "Host")' not in guard
    assert 'httpd_req_get_hdr_value_str(req, "Host"' not in guard
    assert 'PORTAL_HTTP_AP_HOST ":80"' not in guard
    assert "getpeername" not in guard


def test_task7_secret_redaction_and_confirmations():
    source = read("components/portal_http/portal_http.c")
    header = read("components/portal_http/include/portal_http.h")

    assert "wifi_password_configured" in source
    assert "mqtt_password_configured" in source
    assert "mqtt_ca_configured" in source
    assert "provision_config_redact_status" in source
    assert "provision_config_merge_preserving_secrets" in source
    assert "provision_store_save_atomic" in source
    assert "provision_store_load(existing)" in source
    assert "PORTAL_HTTP_CONFIRM_REPLACE \"REPLACE ENROLLMENT\"" in header
    assert "PORTAL_HTTP_CONFIRM_RESET_PROVISIONING \"RESET PROVISIONING\"" in header
    assert "PORTAL_HTTP_CONFIRM_RESET_ALL_DATA \"RESET ALL DATA\"" in header
    assert "reset_all_data" in header
    assert "replace_pending" in header
    assert "replace_failed" in header
    assert "replace_error_code" in header
    assert "replace_pending" in source
    assert "replace_failed" in source
    assert "replace_error_code" in source
    assert "replace_requested" in source
    assert "enroll_started" not in source
    assert "reconnect unavailable" in source
    assert 'saved\\":true' in source
    assert 'reconnect\\":false' in source
    assert 'reconnect\\":true' in source
    assert 'reset_requested\\":true' in source
    assert "static esp_err_t add_bool" in source
    assert "static esp_err_t add_number" in source
    assert "if (add_string(ap" in source

    status_block = source[source.index("static cJSON *build_status_response"):
                          source.index("static esp_err_t handle_status_get")]
    for secret_fragment in [
        "config.wifi_password",
        "config.mqtt_password",
        "config.mqtt_ca",
        "redacted->wifi_password)",
        "redacted->mqtt_password)",
        "redacted->mqtt_ca)",
    ]:
        assert secret_fragment not in status_block


def test_task7_reuses_large_config_buffers_and_rolls_back_partial_start():
    source = read("components/portal_http/portal_http.c")
    store = read("components/provision_store/provision_store.c")

    assert "calloc(1, sizeof(*update))" in source
    assert "calloc(1, sizeof(*existing))" in source
    assert "calloc(1, sizeof(*merged))" not in source
    assert "calloc(1, sizeof(*readback))" not in source
    assert "provision_config_merge_preserving_secrets(existing, update, update)" in source
    assert "provision_store_load(existing)" in source
    assert "calloc(PORTAL_HTTP_SCAN_LIMIT, sizeof(*records))" in source
    assert "cJSON_PrintUnformatted" in source
    assert "register_all_routes" in source

    nvs_reader = store[
        store.index("static esp_err_t read_best_nvs_slot"):
        store.index("esp_err_t provision_store_load")
    ]
    assert "provision_config_t *scratch" in nvs_reader
    assert "calloc(" not in nvs_reader

    init_block = source[source.index("esp_err_t portal_http_init"):
                        source.index("esp_err_t portal_http_stop")]
    assert "httpd_stop(server)" in init_block
    assert "s_server = NULL" in init_block


def test_setup_ap_password_is_lowercase_without_normalizing_station_password():
    header = read("components/provisioning/include/provisioning_runtime.h")
    runtime = read("components/provisioning/provisioning_runtime.c")

    assert '#define PROVISIONING_RUNTIME_AP_PASSWORD_PREFIX "ancs-"' in header

    identity = runtime.split("static esp_err_t make_ap_identity", 1)[1].split(
        "static void fill_ap_config", 1
    )[0]
    assert '"%02X%02X%02X"' in identity
    assert '"%02x%02x%02x"' in identity

    start_sta = runtime.split(
        "esp_err_t provisioning_runtime_start_sta", 1
    )[1].split("esp_err_t provisioning_runtime_stop_sta", 1)[0]
    assert "config->wifi_password" in start_sta
    assert "tolower" not in start_sta


def test_platform_identity_defines_home_assistant_model_for_every_target():
    identity = read("components/platform_identity/include/platform_identity.h")

    for model in (
        "ESP32",
        "ESP32-C2",
        "ESP32-C3",
        "ESP32-C5",
        "ESP32-C6",
        "ESP32-C61",
        "ESP32-S3",
    ):
        assert f'#define ANCS_DEVICE_MODEL "{model}"' in identity


def test_provisioning_runtime_exposes_non_secret_wifi_snapshot():
    header = read("components/provisioning/include/provisioning_runtime.h")
    runtime = read("components/provisioning/provisioning_runtime.c")

    assert "provisioning_wifi_snapshot_t" in header
    assert "char ssid[PROVISION_WIFI_SSID_MAX + 1]" in header
    assert "char ip[16]" in header
    assert "int32_t rssi" in header
    assert "provisioning_runtime_get_wifi_snapshot" in header

    getter = runtime.split(
        "esp_err_t provisioning_runtime_get_wifi_snapshot", 1
    )[1]
    assert "esp_wifi_sta_get_ap_info" in getter
    assert "esp_netif_get_ip_info" in getter
    assert "esp_ip4addr_ntoa" in getter
    assert "password" not in getter
