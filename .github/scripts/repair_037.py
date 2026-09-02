from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8", newline="\n")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one replacement, found {count}: {old[:80]!r}")
    write(path, content.replace(old, new, 1))


def replace_regex_once(path: str, pattern: str, replacement: str) -> None:
    content = read(path)
    updated, count = re.subn(pattern, replacement, content, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"{path}: expected one regex replacement, found {count}: {pattern[:80]!r}")
    write(path, updated)


def transform_block(path: str, start: str, end: str, transform) -> None:
    content = read(path)
    start_at = content.index(start)
    end_at = content.index(end, start_at)
    block = content[start_at:end_at]
    updated = transform(block)
    if updated == block:
        raise RuntimeError(f"{path}: block transform made no change: {start}")
    write(path, content[:start_at] + updated + content[end_at:])


# 1. Fix the fatal NVS identifier error that prevents the ANCS client from initializing.
replace_once(
    "components/device_credentials/device_credentials.c",
    '#define DEVICE_CREDENTIALS_NAMESPACE "ancs_credentials"\n'
    '#define DEVICE_CREDENTIALS_BLE_PASSKEY_KEY "ble_passkey"\n'
    '#define DEVICE_CREDENTIALS_PASSKEY_MIN 100000U\n',
    '#define DEVICE_CREDENTIALS_NVS_NAME_MAX 15U\n'
    '#define DEVICE_CREDENTIALS_NAMESPACE "ancs_creds"\n'
    '#define DEVICE_CREDENTIALS_BLE_PASSKEY_KEY "ble_passkey"\n'
    '#define DEVICE_CREDENTIALS_PASSKEY_MIN 100000U\n\n'
    '_Static_assert(sizeof(DEVICE_CREDENTIALS_NAMESPACE) - 1U <=\n'
    '                   DEVICE_CREDENTIALS_NVS_NAME_MAX,\n'
    '               "NVS namespace exceeds ESP-IDF limit");\n'
    '_Static_assert(sizeof(DEVICE_CREDENTIALS_BLE_PASSKEY_KEY) - 1U <=\n'
    '                   DEVICE_CREDENTIALS_NVS_NAME_MAX,\n'
    '               "NVS key exceeds ESP-IDF limit");\n',
)

# 2. Harden enrollment requests so an incomplete ANCS initialization can never call a null timer.
replace_once(
    "components/ancs_client/ancs_client.c",
    "typedef struct {\n    ancs_client_state_t state;\n",
    "typedef struct {\n    ancs_client_state_t state;\n    bool initialized;\n",
)
transform_block(
    "components/ancs_client/ancs_client.c",
    "static void cleanup_init_resources(const init_progress_t *progress)",
    "esp_err_t ancs_client_init(void)",
    lambda block: block.replace(
        "    taskENTER_CRITICAL(&s_shared_state_lock);\n"
        "    s_client.connected = false;\n",
        "    taskENTER_CRITICAL(&s_shared_state_lock);\n"
        "    s_client.initialized = false;\n"
        "    s_client.connected = false;\n",
        1,
    ),
)
replace_once(
    "components/ancs_client/ancs_client.c",
    "    ESP_LOGI(TAG,\n"
    "             \"initialized device=%s static_notification_bytes=%u cache_entries=%u\",\n"
    "             s_client.device_name,\n"
    "             (unsigned int)sizeof(ancs_notification_t),\n"
    "             (unsigned int)CONFIG_ANCS_CACHE_CAPACITY);\n"
    "    return ESP_OK;\n",
    "    taskENTER_CRITICAL(&s_shared_state_lock);\n"
    "    s_client.initialized = true;\n"
    "    taskEXIT_CRITICAL(&s_shared_state_lock);\n"
    "    ESP_LOGI(TAG,\n"
    "             \"initialized device=%s static_notification_bytes=%u cache_entries=%u\",\n"
    "             s_client.device_name,\n"
    "             (unsigned int)sizeof(ancs_notification_t),\n"
    "             (unsigned int)CONFIG_ANCS_CACHE_CAPACITY);\n"
    "    return ESP_OK;\n",
)


def harden_enroll(block: str) -> str:
    block = block.replace(
        "    taskENTER_CRITICAL(&s_shared_state_lock);\n"
        "    const bool repair_required = s_client.pairing_repair_required;\n"
        "    taskEXIT_CRITICAL(&s_shared_state_lock);\n",
        "    taskENTER_CRITICAL(&s_shared_state_lock);\n"
        "    const bool initialized = s_client.initialized;\n"
        "    const esp_timer_handle_t enroll_timer = s_client.enroll_timer;\n"
        "    const bool repair_required = s_client.pairing_repair_required;\n"
        "    taskEXIT_CRITICAL(&s_shared_state_lock);\n"
        "    if (!initialized || enroll_timer == NULL) {\n"
        "        ESP_LOGW(TAG, \"enrollment requested before ANCS initialization completed\");\n"
        "        return ESP_ERR_INVALID_STATE;\n"
        "    }\n",
        1,
    )
    block = block.replace("esp_timer_stop(s_client.enroll_timer)", "esp_timer_stop(enroll_timer)")
    block = block.replace("        s_client.enroll_timer,\n", "        enroll_timer,\n")
    return block


transform_block(
    "components/ancs_client/ancs_client.c",
    "esp_err_t ancs_client_request_enroll(void)",
    "esp_err_t ancs_client_replace_enrollment(bool confirmed)",
    harden_enroll,
)
replace_once(
    "components/ancs_client/ancs_client.c",
    "esp_err_t ancs_client_replace_enrollment(bool confirmed)\n"
    "{\n"
    "    if (!confirmed) {\n",
    "esp_err_t ancs_client_replace_enrollment(bool confirmed)\n"
    "{\n"
    "    taskENTER_CRITICAL(&s_shared_state_lock);\n"
    "    const bool initialized = s_client.initialized;\n"
    "    taskEXIT_CRITICAL(&s_shared_state_lock);\n"
    "    if (!initialized) {\n"
    "        ESP_LOGW(TAG, \"enrollment replacement requested before ANCS initialization completed\");\n"
    "        return ESP_ERR_INVALID_STATE;\n"
    "    }\n"
    "    if (!confirmed) {\n",
)

# 3. Expose ordinary enrollment through the local settings portal.
replace_once(
    "components/portal_http/include/portal_http.h",
    "    esp_err_t (*reconnect)(const provision_config_t *config, void *context);\n"
    "    esp_err_t (*ble_replace)(void *context);\n",
    "    esp_err_t (*reconnect)(const provision_config_t *config, void *context);\n"
    "    esp_err_t (*ble_enroll)(void *context);\n"
    "    esp_err_t (*ble_replace)(void *context);\n",
)
replace_once(
    "main/app_main.c",
    "static esp_err_t portal_ble_replace(void *context)\n"
    "{\n"
    "    (void)context;\n"
    "    return ancs_client_replace_enrollment(true);\n"
    "}\n",
    "static esp_err_t portal_ble_enroll(void *context)\n"
    "{\n"
    "    (void)context;\n"
    "    return ancs_client_request_enroll();\n"
    "}\n\n"
    "static esp_err_t portal_ble_replace(void *context)\n"
    "{\n"
    "    (void)context;\n"
    "    return ancs_client_replace_enrollment(true);\n"
    "}\n",
)
replace_once(
    "main/app_main.c",
    "    .reconnect = portal_reconnect,\n"
    "    .ble_replace = portal_ble_replace,\n",
    "    .reconnect = portal_reconnect,\n"
    "    .ble_enroll = portal_ble_enroll,\n"
    "    .ble_replace = portal_ble_replace,\n",
)
replace_once(
    "components/portal_http/portal_http.c",
    "#define PORTAL_HTTP_SCAN_LIMIT PROVISIONING_RUNTIME_SCAN_MAX_APS\n",
    "#define PORTAL_HTTP_SCAN_LIMIT PROVISIONING_RUNTIME_SCAN_MAX_APS\n"
    "#define PORTAL_HTTP_SERVER_STACK_SIZE 8192\n",
)
replace_once(
    "components/portal_http/portal_http.c",
    "static esp_err_t handle_ble_replace_post(httpd_req_t *req)\n",
    "static esp_err_t handle_ble_enroll_post(httpd_req_t *req)\n"
    "{\n"
    "    esp_err_t guard_err = require_ap_local_request(req);\n"
    "    if (guard_err != ESP_OK) {\n"
    "        return send_ap_guard_error(req, guard_err);\n"
    "    }\n"
    "    if (s_handlers.ble_enroll == NULL) {\n"
    "        return send_error_json(req, \"503 Service Unavailable\", \"enrollment unavailable\");\n"
    "    }\n"
    "    cJSON *json = NULL;\n"
    "    esp_err_t err = read_json_body(req, &json);\n"
    "    if (err != ESP_OK) {\n"
    "        return send_error_json(req, \"400 Bad Request\", \"invalid JSON\");\n"
    "    }\n"
    "    cJSON_Delete(json);\n\n"
    "    err = s_handlers.ble_enroll(s_handlers.context);\n"
    "    if (err == ESP_ERR_INVALID_STATE) {\n"
    "        return send_error_json(req, \"409 Conflict\", \"enrollment is not ready\");\n"
    "    }\n"
    "    return err == ESP_OK\n"
    "               ? send_json(req, \"{\\\"ok\\\":true,\\\"enroll_started\\\":true}\")\n"
    "               : send_error_json(req,\n"
    "                                 \"500 Internal Server Error\",\n"
    "                                 \"enrollment failed\");\n"
    "}\n\n"
    "static esp_err_t handle_ble_replace_post(httpd_req_t *req)\n",
)
replace_once(
    "components/portal_http/portal_http.c",
    "    ESP_RETURN_ON_ERROR(register_uri(server, \"/api/notification/test\", HTTP_POST, handle_test_notification_post), TAG, \"notification test\");\n"
    "    ESP_RETURN_ON_ERROR(register_uri(server, \"/api/ble/replace\", HTTP_POST, handle_ble_replace_post), TAG, \"ble replace\");\n",
    "    ESP_RETURN_ON_ERROR(register_uri(server, \"/api/notification/test\", HTTP_POST, handle_test_notification_post), TAG, \"notification test\");\n"
    "    ESP_RETURN_ON_ERROR(register_uri(server, \"/api/ble/enroll\", HTTP_POST, handle_ble_enroll_post), TAG, \"ble enroll\");\n"
    "    ESP_RETURN_ON_ERROR(register_uri(server, \"/api/ble/replace\", HTTP_POST, handle_ble_replace_post), TAG, \"ble replace\");\n",
)
replace_once(
    "components/portal_http/portal_http.c",
    "    httpd_config_t config = HTTPD_DEFAULT_CONFIG();\n"
    "    config.max_uri_handlers = 24;\n",
    "    httpd_config_t config = HTTPD_DEFAULT_CONFIG();\n"
    "    config.stack_size = PORTAL_HTTP_SERVER_STACK_SIZE;\n"
    "    config.max_uri_handlers = 24;\n",
)

replace_once(
    "components/portal_http/portal.html",
    "    <section class=\"panel ble-panel\" aria-labelledby=\"ble-title\">\n"
    "      <div class=\"ble-copy\">\n"
    "        <p class=\"section-kicker\">Bluetooth</p>\n"
    "        <h2 id=\"ble-title\">iPhone 연결</h2>\n"
    "        <p id=\"ble-guidance\">Home Assistant의 iPhone 등록 시작 버튼을 누르거나 BOOT 버튼을 3초 동안 누르세요. 등록 전에는 Bluetooth 등록 신호를 보내지 않습니다.</p>\n"
    "      </div>\n"
    "    </section>\n",
    "    <section class=\"panel ble-panel\" aria-labelledby=\"ble-title\">\n"
    "      <div class=\"ble-copy\">\n"
    "        <p class=\"section-kicker\">Bluetooth</p>\n"
    "        <h2 id=\"ble-title\">iPhone 연결</h2>\n"
    "        <p id=\"ble-guidance\">아래 버튼으로 등록을 시작하세요. 이 설정 페이지는 열린 상태로 유지되며, 등록 전에는 Bluetooth 등록 신호를 보내지 않습니다.</p>\n"
    "      </div>\n"
    "      <div class=\"ble-enroll-actions\">\n"
    "        <div id=\"ble-enroll-code\" class=\"ble-enroll-code\" role=\"status\" aria-live=\"polite\" hidden>\n"
    "          <span>iPhone 등록 코드</span>\n"
    "          <strong id=\"ble-enroll-code-value\">------</strong>\n"
    "          <small>iPhone의 Bluetooth 등록 창에 입력하세요.</small>\n"
    "        </div>\n"
    "        <button class=\"button button-primary\" id=\"start-enrollment\" type=\"button\" aria-describedby=\"ble-guidance\">iPhone 기기 등록</button>\n"
    "      </div>\n"
    "    </section>\n",
)
replace_once(
    "components/portal_http/portal.css",
    ".ble-copy h2 {\n  margin-bottom: 8px;\n}\n",
    ".ble-copy h2 {\n  margin-bottom: 8px;\n}\n\n"
    ".ble-enroll-actions {\n"
    "  display: grid;\n"
    "  gap: 10px;\n"
    "  min-width: min(100%, 220px);\n"
    "}\n\n"
    ".ble-enroll-code {\n"
    "  padding: 12px 14px;\n"
    "  border: 1px solid #b9e2d3;\n"
    "  border-radius: 12px;\n"
    "  background: var(--color-success-soft);\n"
    "  text-align: center;\n"
    "}\n\n"
    ".ble-enroll-code span,\n"
    ".ble-enroll-code strong,\n"
    ".ble-enroll-code small {\n"
    "  display: block;\n"
    "}\n\n"
    ".ble-enroll-code span {\n"
    "  color: var(--color-success);\n"
    "  font-size: 0.72rem;\n"
    "  font-weight: 800;\n"
    "}\n\n"
    ".ble-enroll-code strong {\n"
    "  margin: 4px 0;\n"
    "  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;\n"
    "  font-size: 1.45rem;\n"
    "  font-variant-numeric: tabular-nums;\n"
    "  letter-spacing: 0.12em;\n"
    "}\n\n"
    ".ble-enroll-code small {\n"
    "  color: var(--color-muted);\n"
    "  font-size: 0.72rem;\n"
    "  line-height: 1.35;\n"
    "}\n",
)
replace_once(
    "components/portal_http/portal.js",
    "function updateTile(id, state, value, detail) {\n"
    "  $(id).dataset.state = state;\n"
    "  $(`${id}-value`).textContent = value;\n"
    "  $(`${id}-detail`).textContent = detail;\n"
    "}\n",
    "function updateTile(id, state, value, detail) {\n"
    "  $(id).dataset.state = state;\n"
    "  $(`${id}-value`).textContent = value;\n"
    "  $(`${id}-detail`).textContent = detail;\n"
    "}\n\n"
    "function updateEnrollmentControls(system, blePasskey) {\n"
    "  const button = $('start-enrollment');\n"
    "  const code = $('ble-enroll-code');\n"
    "  const codeValue = $('ble-enroll-code-value');\n"
    "  const busy = button.dataset.busy === 'true';\n"
    "  const windowOpen = Boolean(system.enroll_window_open);\n"
    "  code.hidden = !windowOpen;\n"
    "  codeValue.textContent = blePasskey || '확인 중';\n\n"
    "  let label = 'iPhone 기기 등록';\n"
    "  let unavailable = false;\n"
    "  if (system.ble_pairing_repair_required) {\n"
    "    label = '등록 교체 필요';\n"
    "    unavailable = true;\n"
    "  } else if (system.ble_connected) {\n"
    "    label = 'iPhone 연결됨';\n"
    "    unavailable = true;\n"
    "  } else if (windowOpen) {\n"
    "    label = '등록 신호 다시 보내기';\n"
    "  } else if (system.ble_bonded) {\n"
    "    label = '등록된 iPhone 다시 연결';\n"
    "  }\n"
    "  if (!busy) {\n"
    "    button.textContent = label;\n"
    "    button.dataset.label = label;\n"
    "  }\n"
    "  button.disabled = busy || unavailable;\n"
    "}\n",
)
replace_once(
    "components/portal_http/portal.js",
    "    $('ble-guidance').textContent = '등록된 iPhone만 자동으로 다시 연결됩니다. Home Assistant 버튼 또는 BOOT 3초 길게 누르기로 재연결 신호를 보낼 수 있습니다.';\n",
    "    $('ble-guidance').textContent = '등록된 iPhone만 자동으로 다시 연결됩니다. 이 페이지의 버튼으로 재연결 신호를 다시 보낼 수 있습니다.';\n",
)
replace_once(
    "components/portal_http/portal.js",
    "    $('ble-guidance').textContent = 'Home Assistant의 iPhone 등록 시작 버튼을 누르거나 BOOT 버튼을 3초 동안 누르면 Bluetooth 등록 신호를 보냅니다.';\n"
    "  }\n\n"
    "  const published = Number(system.notifications_published || 0);\n",
    "    $('ble-guidance').textContent = '이 페이지의 iPhone 기기 등록 버튼을 누르면 Bluetooth 등록 신호를 보냅니다.';\n"
    "  }\n\n"
    "  updateEnrollmentControls(system, blePasskey);\n\n"
    "  const published = Number(system.notifications_published || 0);\n",
)
replace_once(
    "components/portal_http/portal.js",
    "$('replace-enrollment').addEventListener('click', () => {\n",
    "$('start-enrollment').addEventListener('click', () => runButton('start-enrollment', '등록 시작 중', async () => {\n"
    "  await api('/api/ble/enroll', { method: 'POST', body: '{}' });\n"
    "  const status = await loadStatus();\n"
    "  const passkey = Number(status.system?.ble_passkey || 0);\n"
    "  const code = Number.isInteger(passkey) && passkey >= 100000 && passkey <= 999999\n"
    "    ? String(passkey).padStart(6, '0')\n"
    "    : null;\n"
    "  setMessage(\n"
    "    code\n"
    "      ? `iPhone 등록을 시작했습니다. 이 페이지에 표시된 등록 코드 ${code}를 iPhone Bluetooth 등록 창에 입력하세요.`\n"
    "      : 'iPhone 등록 신호를 시작했습니다. 상태 카드가 갱신될 때까지 현재 페이지를 유지하세요.',\n"
    "    'success',\n"
    "  );\n"
    "}));\n\n"
    "$('replace-enrollment').addEventListener('click', () => {\n",
)

# 4. Improve Wi-Fi candidate selection and reconnect transient disconnects before opening recovery AP.
replace_once(
    "components/provisioning/include/provisioning_runtime.h",
    "#define PROVISIONING_RUNTIME_WIFI_TIMEOUT_MS 30000\n",
    "#define PROVISIONING_RUNTIME_WIFI_TIMEOUT_MS 45000\n",
)
replace_once(
    "components/provisioning/provisioning_runtime.c",
    "#define PROVISIONING_AP_CHANNEL 6\n"
    "#define PROVISIONING_AP_MAX_CLIENTS 1\n"
    "#define PROVISIONING_DHCPS_DNS_OFFER 0x02\n"
    "#define PROVISIONING_EVENT_QUEUE_LEN 8\n",
    "#define PROVISIONING_AP_CHANNEL 6\n"
    "#define PROVISIONING_AP_MAX_CLIENTS 2\n"
    "#define PROVISIONING_STA_FAILURE_RETRY_COUNT 5\n"
    "#define PROVISIONING_STA_MIN_RSSI -90\n"
    "#define PROVISIONING_WIFI_MODE_RETRY_COUNT 6\n"
    "#define PROVISIONING_WIFI_MODE_RETRY_DELAY_MS 100\n"
    "#define PROVISIONING_DHCPS_DNS_OFFER 0x02\n"
    "#define PROVISIONING_EVENT_QUEUE_LEN 8\n",
)
replace_once(
    "components/provisioning/provisioning_runtime.c",
    "        bool reconnect = false;\n"
    "        lock_state();\n",
    "        bool reconnect = false;\n"
    "        bool start_reconnect_timeout = false;\n"
    "        lock_state();\n",
)
replace_once(
    "components/provisioning/provisioning_runtime.c",
    "        if (had_ip) {\n"
    "            s_sta_started = false;\n"
    "            s_sta_connecting = false;\n"
    "            s_active_sta_attempt_generation = 0;\n"
    "            reconnect = false;\n"
    "        } else if (s_sta_started && s_sta_connecting) {\n"
    "            s_sta_connecting = true;\n"
    "            reconnect = true;\n"
    "        }\n",
    "        if (had_ip) {\n"
    "            if (s_sta_started) {\n"
    "                s_sta_connecting = true;\n"
    "                reconnect = true;\n"
    "                start_reconnect_timeout = true;\n"
    "            }\n"
    "        } else if (s_sta_started && s_sta_connecting) {\n"
    "            s_sta_connecting = true;\n"
    "            reconnect = true;\n"
    "        }\n",
)
replace_once(
    "components/provisioning/provisioning_runtime.c",
    "        if (had_ip) {\n"
    "            (void)apply_wifi_mode();\n"
    "            dispatch_event_with_generation(PROVISION_EVENT_WIFI_TIMEOUT, attempt_generation);\n"
    "        }\n"
    "        if (reconnect) {\n",
    "        if (start_reconnect_timeout) {\n"
    "            schedule_wifi_timeout(attempt_generation);\n"
    "        }\n"
    "        if (reconnect) {\n",
)
replace_once(
    "components/provisioning/provisioning_runtime.c",
    "            if (reconnect_still_valid) {\n"
    "                (void)esp_wifi_connect();\n"
    "            }\n",
    "            if (reconnect_still_valid) {\n"
    "                const esp_err_t reconnect_error = esp_wifi_connect();\n"
    "                if (reconnect_error != ESP_OK &&\n"
    "                    reconnect_error != ESP_ERR_WIFI_CONN) {\n"
    "                    ESP_LOGW(TAG,\n"
    "                             \"STA reconnect start failed: %s\",\n"
    "                             esp_err_to_name(reconnect_error));\n"
    "                }\n"
    "            }\n",
)
replace_once(
    "components/provisioning/provisioning_runtime.c",
    "static esp_err_t apply_wifi_mode_unlocked(void)\n"
    "{\n"
    "    return esp_wifi_set_mode(select_wifi_mode_from_flags());\n"
    "}\n",
    "static esp_err_t set_wifi_mode_with_retry(wifi_mode_t mode)\n"
    "{\n"
    "    esp_err_t err = ESP_OK;\n"
    "    for (uint8_t attempt = 0;\n"
    "         attempt < PROVISIONING_WIFI_MODE_RETRY_COUNT;\n"
    "         ++attempt) {\n"
    "        err = esp_wifi_set_mode(mode);\n"
    "        if (err != ESP_ERR_WIFI_STOP_STATE) {\n"
    "            return err;\n"
    "        }\n"
    "        if (attempt + 1U < PROVISIONING_WIFI_MODE_RETRY_COUNT) {\n"
    "            vTaskDelay(pdMS_TO_TICKS(PROVISIONING_WIFI_MODE_RETRY_DELAY_MS));\n"
    "        }\n"
    "    }\n"
    "    return err;\n"
    "}\n\n"
    "static esp_err_t apply_wifi_mode_unlocked(void)\n"
    "{\n"
    "    return set_wifi_mode_with_retry(select_wifi_mode_from_flags());\n"
    "}\n",
)
replace_once(
    "components/provisioning/provisioning_runtime.c",
    "    sta_config.sta.scan_method = WIFI_ALL_CHANNEL_SCAN;\n"
    "    sta_config.sta.threshold.authmode = WIFI_AUTH_OPEN;\n"
    "    sta_config.sta.sae_pwe_h2e = WPA3_SAE_PWE_BOTH;\n",
    "    sta_config.sta.scan_method = WIFI_ALL_CHANNEL_SCAN;\n"
    "    sta_config.sta.sort_method = WIFI_CONNECT_AP_BY_SIGNAL;\n"
    "    sta_config.sta.threshold.rssi = PROVISIONING_STA_MIN_RSSI;\n"
    "    sta_config.sta.threshold.authmode = WIFI_AUTH_OPEN;\n"
    "    sta_config.sta.failure_retry_cnt = PROVISIONING_STA_FAILURE_RETRY_COUNT;\n"
    "    sta_config.sta.sae_pwe_h2e = WPA3_SAE_PWE_BOTH;\n",
)

# 5. Update source-contract tests to cover the repaired behavior.
portal_test = "tools/tests/test_portal_contract.py"
replace_once(
    portal_test,
    '    assert "s_sta_connecting = false" in had_ip_block\n'
    '    assert "reconnect = false" in had_ip_block\n'
    '    assert "s_sta_started = false" in had_ip_block\n',
    '    assert "s_sta_connecting = true" in had_ip_block\n'
    '    assert "reconnect = true" in had_ip_block\n'
    '    assert "start_reconnect_timeout = true" in had_ip_block\n'
    '    assert "s_sta_started = false" not in had_ip_block\n',
)
replace_once(
    portal_test,
    '    assert "dispatch_event_with_generation(PROVISION_EVENT_WIFI_TIMEOUT, attempt_generation)" in disconnected_case\n',
    '    assert "dispatch_event_with_generation(PROVISION_EVENT_WIFI_TIMEOUT, attempt_generation)" not in disconnected_case\n'
    '    assert "schedule_wifi_timeout(attempt_generation)" in disconnected_case\n',
)
replace_once(
    portal_test,
    '    assert runtime.count("schedule_wifi_timeout(attempt_generation)") == 1\n',
    '    assert runtime.count("schedule_wifi_timeout(attempt_generation)") == 2\n',
)
replace_once(
    portal_test,
    '        \'id="test-notification"\',\n'
    '        \'id="replace-confirmation"\',\n',
    '        \'id="test-notification"\',\n'
    '        \'id="start-enrollment"\',\n'
    '        \'id="replace-confirmation"\',\n',
)
replace_regex_once(
    portal_test,
    r"def test_portal_moves_ordinary_enrollment_to_home_assistant\(\):\n.*?(?=\ndef test_portal_exposes_a_compact_korean_guided_setup)",
    "def test_portal_can_start_ordinary_enrollment_without_leaving_settings():\n"
    "    html = read(\"components/portal_http/portal.html\")\n"
    "    script = read(\"components/portal_http/portal.js\")\n"
    "    source = read(\"components/portal_http/portal_http.c\")\n"
    "    header = read(\"components/portal_http/include/portal_http.h\")\n\n"
    "    assert 'id=\"start-enrollment\"' in html\n"
    "    assert \"$('start-enrollment').addEventListener\" in script\n"
    "    assert \"'/api/ble/enroll'\" in script\n"
    "    assert '\"/api/ble/enroll\"' in source\n"
    "    assert \"ble_enroll\" in header\n"
    "    assert 'id=\"replace-enrollment\"' in html\n"
    "    assert '\"/api/ble/replace\"' in source\n"
    "    assert \"이 설정 페이지는 열린 상태로 유지\" in html\n\n",
)
replace_once(
    portal_test,
    '    assert "ble_replace" in header\n',
    '    assert "ble_enroll" in header\n'
    '    assert "ble_replace" in header\n',
)
replace_once(
    portal_test,
    '        "handle_empty_action_post",\n'
    '        "handle_ble_replace_post",\n',
    '        "handle_empty_action_post",\n'
    '        "handle_ble_enroll_post",\n'
    '        "handle_ble_replace_post",\n',
)
replace_once(
    portal_test,
    '    assert "enroll_started" not in source\n',
    '    assert "enroll_started" in source\n',
)

onboarding_test = "tools/tests/test_onboarding_recovery_contract.py"
replace_once(
    onboarding_test,
    '    assert "config.max_open_sockets = 7" in source\n',
    '    assert "PORTAL_HTTP_SERVER_STACK_SIZE 8192" in source\n'
    '    assert "config.stack_size = PORTAL_HTTP_SERVER_STACK_SIZE" in source\n'
    '    assert "config.max_open_sockets = 7" in source\n',
)
replace_once(
    onboarding_test,
    '    assert "#define PROVISIONING_AP_MAX_CLIENTS 1" in runtime\n',
    '    assert "#define PROVISIONING_AP_MAX_CLIENTS 2" in runtime\n',
)
with (ROOT / onboarding_test).open("a", encoding="utf-8", newline="\n") as stream:
    stream.write(
        "\n\ndef test_device_credential_nvs_identifiers_fit_esp_idf_limit():\n"
        "    credentials = read(\"components/device_credentials/device_credentials.c\")\n\n"
        "    assert '#define DEVICE_CREDENTIALS_NVS_NAME_MAX 15U' in credentials\n"
        "    assert '#define DEVICE_CREDENTIALS_NAMESPACE \"ancs_creds\"' in credentials\n"
        "    assert '_Static_assert(sizeof(DEVICE_CREDENTIALS_NAMESPACE)' in credentials\n"
        "    assert 'ancs_credentials' not in credentials\n"
        "\n\ndef test_wifi_reconnect_uses_signal_sorting_driver_retries_and_bounded_recovery():\n"
        "    runtime = read(\"components/provisioning/provisioning_runtime.c\")\n"
        "    header = read(\"components/provisioning/include/provisioning_runtime.h\")\n\n"
        "    assert 'PROVISIONING_RUNTIME_WIFI_TIMEOUT_MS 45000' in header\n"
        "    assert 'WIFI_CONNECT_AP_BY_SIGNAL' in runtime\n"
        "    assert 'failure_retry_cnt = PROVISIONING_STA_FAILURE_RETRY_COUNT' in runtime\n"
        "    assert 'threshold.rssi = PROVISIONING_STA_MIN_RSSI' in runtime\n"
        "    assert 'set_wifi_mode_with_retry' in runtime\n"
        "    assert 'start_reconnect_timeout = true' in runtime\n"
    )

# 6. Bump all current release surfaces while preserving historical changelog entries.
for raw_path in subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).split(b"\0"):
    if not raw_path:
        continue
    path = raw_path.decode("utf-8")
    if path == "CHANGELOG.md" or path == ".github/workflows/repair-0.3.7.yml":
        continue
    if path.startswith("docs/firmware/") or path.endswith(".sha256"):
        continue
    file_path = ROOT / path
    try:
        content = file_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, IsADirectoryError):
        continue
    if "0.3.7" in content:
        file_path.write_text(content.replace("0.3.7", "0.3.7"), encoding="utf-8", newline="\n")

replace_once(
    "CHANGELOG.md",
    "# 변경 이력\n\n",
    "# 변경 이력\n\n"
    "## 펌웨어 0.3.7 - 2026-09-02\n\n"
    "- 16자 NVS 네임스페이스 때문에 ANCS 초기화가 중단되던 문제를 수정해 enroll 등록 창이 정상 동작하도록 했습니다.\n"
    "- 설정 포털에 `iPhone 기기 등록` 버튼과 6자리 등록 코드 표시를 추가했습니다.\n"
    "- 연결된 Wi-Fi가 순간적으로 끊겨도 45초 동안 자동 재연결한 뒤에만 복구 AP로 전환합니다.\n"
    "- 동일 SSID 다중 AP에서 신호 강도 우선 선택과 드라이버 재시도를 적용하고 설정 AP 동시 접속 허용 수를 2대로 늘렸습니다.\n"
    "- HTTP 서버 스택을 8KB로 늘려 설정 페이지 처리 중 스택 보호 재부팅을 방지합니다.\n\n",
)

print("0.3.7 source repair applied successfully")
