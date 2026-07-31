# BLE Enrollment and Stable Recovery Portal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve bond-aware BLE advertising while making the ESP32-C6 setup portal and Wi-Fi scan reliably recover after station connection failure.

**Architecture:** Keep the existing `ble_enroll` policy as the source of truth and strengthen its regression coverage. Add a stable recovery transition that stops station connection attempts before enabling the setup AP, run Wi-Fi scans through a temporary idle STA interface, and defer saved-configuration application long enough for the HTTP response to leave the device.

**Tech Stack:** ESP-IDF v6.0.2, ESP32-C6 Bluedroid, `esp_wifi`, FreeRTOS timers/queues, `esp_http_server`, Unity, pytest, Windows PowerShell, COM9.

---

## File map

- `components/ble_enroll/test/test_ble_enroll.c`
  - Locks the approved unbonded, enrollment-window, bonded, and replacement advertising rules.
- `tools/tests/test_ble_security_contract.py`
  - Verifies the ANCS client routes all advertising attempts through the enrollment policy.
- `components/provisioning/include/provisioning_runtime.h`
  - Exposes one coordinator-facing stable recovery operation.
- `components/provisioning/provisioning_runtime.c`
  - Owns Wi-Fi mode selection, bounded station retries, stable recovery, and temporary scan-mode promotion.
- `main/app_main.c`
  - Applies saved configuration after an HTTP-response grace period and invokes stable recovery on Wi-Fi timeout.
- `tools/tests/test_portal_contract.py`
  - Locks the runtime source contract and the Korean setup-page status/message contract.
- `tools/tests/test_startup_contract.py`
  - Locks coordinator ordering for configuration handoff and Wi-Fi timeout recovery.
- `components/portal_http/portal.js`
  - Shows the exact BLE radio state and explains AP disappearance/recovery after save.
- `components/portal_http/portal.html`
  - Provides static fallback guidance consistent with the approved behavior.
- `docs/TROUBLESHOOTING.md`
  - Documents recovery AP behavior and the expected network handoff.
- `docs/VALIDATION_REPORT.md`
  - Records host, build, COM9, BLE, Wi-Fi, HTTP, and MQTT evidence.

The project directory currently has no Git metadata. Each task therefore ends
with a diff/checkpoint review instead of a commit; no fake commit command is
included.

### Task 1: Lock the approved BLE advertising policy

**Files:**
- Modify: `components/ble_enroll/test/test_ble_enroll.c`
- Modify: `tools/tests/test_ble_security_contract.py`

- [ ] **Step 1: Add explicit Unity assertions for all four approved states**

Append these test cases to `components/ble_enroll/test/test_ble_enroll.c`:

```c
TEST_CASE("unbonded boot remains radio silent until enrollment",
          "[ble_enroll]")
{
    ble_enroll_state_t state;
    ble_enroll_init(&state, test_config());

    TEST_ASSERT_FALSE(ble_enroll_should_advertise(&state, 0));
    TEST_ASSERT_FALSE(ble_enroll_should_advertise(&state, 60000));
}

TEST_CASE("enrollment button opens bounded advertising for an unbonded iPhone",
          "[ble_enroll]")
{
    ble_enroll_state_t state;
    ble_enroll_init(&state, test_config());

    TEST_ASSERT_EQUAL(ESP_OK, ble_enroll_open_window(&state, 1000));
    TEST_ASSERT_TRUE(ble_enroll_should_advertise(&state, 1000));
    TEST_ASSERT_FALSE(ble_enroll_should_advertise(&state, 121001));
}

TEST_CASE("stored bond enables automatic advertising without opening pairing",
          "[ble_enroll]")
{
    ble_enroll_state_t state;
    ble_enroll_init(&state, test_config());
    ble_enroll_note_bonded(&state, PEER_A);

    TEST_ASSERT_TRUE(ble_enroll_should_advertise(&state, 0));
    TEST_ASSERT_FALSE(ble_enroll_window_active(&state, 0));
    TEST_ASSERT_TRUE(ble_enroll_pairing_allowed(&state, PEER_A, 0));
    TEST_ASSERT_FALSE(ble_enroll_pairing_allowed(&state, PEER_B, 0));
}
```

- [ ] **Step 2: Strengthen the host-side source contract**

Add this test to `tools/tests/test_ble_security_contract.py`:

```python
def test_every_advertising_entry_point_is_guarded_by_enrollment_policy():
    source = CLIENT_SOURCE.read_text(encoding="utf-8")
    enroll = ENROLL_SOURCE.read_text(encoding="utf-8")

    assert (
        "state->has_bond || ble_enroll_window_active(state, now_ms)"
        in enroll
    )
    starter = source.split("static void start_advertising(void)", 2)[2].split(
        "static void stop_advertising(void)", 1
    )[0]
    retry = source.split("static void schedule_advertising_retry(void)", 1)[1].split(
        "static void schedule_discovery_retry(void)", 1
    )[0]
    assert "!ble_enroll_should_advertise(&s_enroll, now_ms())" in starter
    assert "!ble_enroll_should_advertise(&s_enroll, now_ms())" in retry
    assert "if (current_bond_count() > 0 || ancs_client_has_bond())" in source
```

- [ ] **Step 3: Run the BLE host contract**

Run:

```powershell
python -m pytest tools/tests/test_ble_security_contract.py -q
```

Expected: all BLE source-contract tests pass. No production BLE change is
expected because the current policy already implements the approved behavior.

- [ ] **Step 4: Review the BLE checkpoint**

Run:

```powershell
git diff --no-index NUL components/ble_enroll/test/test_ble_enroll.c
python -m pytest tools/tests/test_ble_security_contract.py -q
```

Expected: only regression coverage is added and pytest reports no failures.
The first command may return exit code `1` because `--no-index` uses that code
when a difference is present.

### Task 2: Make station connection attempts bounded and recovery AP stable

**Files:**
- Modify: `components/provisioning/include/provisioning_runtime.h`
- Modify: `components/provisioning/provisioning_runtime.c`
- Modify: `tools/tests/test_portal_contract.py`

- [ ] **Step 1: Replace the old reconnect assertions with failing recovery assertions**

In `test_task6_wifi_runtime_source_contracts()` inside
`tools/tests/test_portal_contract.py`, replace:

```python
assert "xTimerReset(s_wifi_timeout_timer, 0)" in disconnected_case
```

with:

```python
assert "xTimerReset(s_wifi_timeout_timer, 0)" not in disconnected_case
assert "if (had_ip)" in disconnected_case
assert "reconnect = false;" in disconnected_case
assert "provisioning_runtime_enter_stable_recovery" in header
assert "original_mode == WIFI_MODE_AP" in runtime
assert "esp_wifi_set_mode(WIFI_MODE_APSTA)" in runtime
assert "esp_wifi_set_mode(WIFI_MODE_AP)" in runtime
```

Add this dedicated mode-selection test:

```python
def test_recovery_ap_uses_ap_only_mode_when_station_is_stopped():
    runtime = read("components/provisioning/provisioning_runtime.c")
    mode = runtime.split("static esp_err_t apply_wifi_mode", 1)[1].split(
        "esp_err_t provisioning_runtime_init", 1
    )[0]

    assert "if (ap_started && sta_started)" in mode
    assert "else if (ap_started)" in mode
    assert "mode = WIFI_MODE_APSTA;" in mode
    assert "mode = WIFI_MODE_AP;" in mode
    assert "mode = WIFI_MODE_STA;" in mode
```

- [ ] **Step 2: Run the portal contract and verify it fails**

Run:

```powershell
python -m pytest tools/tests/test_portal_contract.py -q
```

Expected: FAIL because disconnect handling still resets the timeout, AP-only
mode is not selected, and the recovery API does not exist.

- [ ] **Step 3: Expose stable recovery through the runtime header**

Add this declaration after `provisioning_runtime_stop_sta` in
`components/provisioning/include/provisioning_runtime.h`:

```c
esp_err_t provisioning_runtime_enter_stable_recovery(void);
```

- [ ] **Step 4: Replace `apply_wifi_mode()` with exact AP/STA mode selection**

Replace the function in `components/provisioning/provisioning_runtime.c` with:

```c
static esp_err_t apply_wifi_mode(void)
{
    lock_state();
    const bool ap_started = s_ap_started;
    const bool sta_started = s_sta_started;
    unlock_state();

    wifi_mode_t mode = WIFI_MODE_NULL;
    if (ap_started && sta_started) {
        mode = WIFI_MODE_APSTA;
    } else if (ap_started) {
        mode = WIFI_MODE_AP;
    } else if (sta_started) {
        mode = WIFI_MODE_STA;
    }
    return esp_wifi_set_mode(mode);
}
```

- [ ] **Step 5: Keep the original timeout deadline across disconnect retries**

Replace the `WIFI_EVENT_STA_DISCONNECTED` branch in `wifi_event_handler()` with:

```c
if (event_base == WIFI_EVENT &&
    event_id == WIFI_EVENT_STA_DISCONNECTED) {
    const wifi_event_sta_disconnected_t *disconnected = event_data;
    bool reconnect = false;
    lock_state();
    const bool had_ip = s_sta_has_ip;
    s_sta_has_ip = false;
    if (disconnected != NULL) {
        s_last_wifi_disconnect_reason = disconnected->reason;
        s_last_wifi_disconnect_rssi = disconnected->rssi;
    } else {
        s_last_wifi_disconnect_reason = 0;
        s_last_wifi_disconnect_rssi = 0;
    }
    if (s_sta_started && !had_ip) {
        s_sta_connecting = true;
        reconnect = true;
    } else {
        s_sta_connecting = false;
    }
    unlock_state();

    ESP_LOGW(TAG,
             "STA disconnected reason=%u rssi=%d",
             (unsigned)s_last_wifi_disconnect_reason,
             (int)s_last_wifi_disconnect_rssi);
    if (had_ip) {
        dispatch_event(PROVISION_EVENT_WIFI_TIMEOUT);
    } else if (reconnect) {
        (void)esp_wifi_connect();
    }
}
```

The one-shot timeout remains owned by `provisioning_runtime_start_sta()`.
Repeated disconnect events no longer extend it indefinitely.

- [ ] **Step 6: Add the stable recovery operation**

Add this function after `provisioning_runtime_stop_sta()`:

```c
esp_err_t provisioning_runtime_enter_stable_recovery(void)
{
    esp_err_t stop_error = provisioning_runtime_stop_sta();
    if (stop_error != ESP_OK) {
        return stop_error;
    }
    return provisioning_runtime_start_ap();
}
```

- [ ] **Step 7: Temporarily enable idle STA only while scanning**

Refactor `provisioning_runtime_scan()` so its scan section follows this complete
cleanup shape:

```c
wifi_mode_t original_mode = WIFI_MODE_NULL;
ESP_RETURN_ON_ERROR(esp_wifi_get_mode(&original_mode), TAG, "get scan mode");
const bool restore_ap_only = original_mode == WIFI_MODE_AP;
if (restore_ap_only) {
    ESP_RETURN_ON_ERROR(esp_wifi_set_mode(WIFI_MODE_APSTA),
                        TAG,
                        "enable idle STA for scan");
}

esp_err_t scan_error = esp_wifi_scan_start(&scan_config, true);
if (scan_error == ESP_OK) {
    scan_error = collect_scan_records(records, count);
}

esp_err_t restore_error = ESP_OK;
if (restore_ap_only) {
    restore_error = esp_wifi_set_mode(WIFI_MODE_AP);
}
if (scan_error != ESP_OK) {
    return scan_error;
}
return restore_error;
```

Move the existing AP-count, record-limit, record-copy, and AP-list cleanup code
into this helper immediately above `provisioning_runtime_scan()`:

```c
static esp_err_t collect_scan_records(wifi_ap_record_t *records, size_t *count)
{
    uint16_t ap_count = 0;
    esp_err_t error = esp_wifi_scan_get_ap_num(&ap_count);
    if (error != ESP_OK) {
        (void)esp_wifi_clear_ap_list();
        return error;
    }

    uint16_t requested =
        (uint16_t)(*count > UINT16_MAX ? UINT16_MAX : *count);
    if (requested > PROVISIONING_RUNTIME_SCAN_MAX_APS) {
        requested = PROVISIONING_RUNTIME_SCAN_MAX_APS;
    }
    if (requested > ap_count) {
        requested = ap_count;
    }
    if (requested == 0) {
        *count = 0;
        (void)esp_wifi_clear_ap_list();
        return ESP_OK;
    }

    error = esp_wifi_scan_get_ap_records(&requested, records);
    if (error != ESP_OK) {
        (void)esp_wifi_clear_ap_list();
        return error;
    }
    *count = requested;
    return ESP_OK;
}
```

- [ ] **Step 8: Run the portal contract**

Run:

```powershell
python -m pytest tools/tests/test_portal_contract.py -q
```

Expected: all portal/runtime source-contract tests pass.

- [ ] **Step 9: Review the runtime checkpoint**

Run:

```powershell
rg -n "xTimerReset\\(s_wifi_timeout_timer" components/provisioning/provisioning_runtime.c
rg -n "WIFI_MODE_APSTA|WIFI_MODE_AP|enter_stable_recovery" components/provisioning/provisioning_runtime.c
```

Expected: the Wi-Fi timer is reset only when a new bounded station attempt is
started, and AP-only recovery plus temporary scan promotion are visible.

### Task 3: Make the coordinator enter recovery and preserve the save response

**Files:**
- Modify: `main/app_main.c`
- Modify: `tools/tests/test_startup_contract.py`

- [ ] **Step 1: Add failing coordinator-order tests**

Append these tests to `tools/tests/test_startup_contract.py`:

```python
def test_wifi_timeout_stops_station_before_starting_recovery_portal():
    source = read("main/app_main.c")
    timeout_case = source.split(
        "case PROVISION_EVENT_WIFI_TIMEOUT:", 1
    )[1].split("break;", 1)[0]

    assert "provisioning_runtime_enter_stable_recovery()" in timeout_case
    assert timeout_case.index(
        "provisioning_runtime_enter_stable_recovery()"
    ) < timeout_case.index("mqtt_relay_set_wifi_connected(false)")


def test_saved_config_waits_for_http_response_grace_period():
    source = read("main/app_main.c")
    handler = source.split("static void handle_config_changed", 1)[1].split(
        "static void handle_reset_provisioning", 1
    )[0]

    assert "#define APP_CONFIG_HANDOFF_DELAY_MS 750" in source
    assert "vTaskDelay(pdMS_TO_TICKS(APP_CONFIG_HANDOFF_DELAY_MS));" in handler
    assert handler.index("vTaskDelay(") < handler.index("stop_mqtt();")
    assert handler.index("vTaskDelay(") < handler.index(
        "provisioning_runtime_stop_sta();"
    )
```

- [ ] **Step 2: Run the startup contract and verify it fails**

Run:

```powershell
python -m pytest tools/tests/test_startup_contract.py -q
```

Expected: FAIL because stable recovery and the response grace period are not
yet invoked.

- [ ] **Step 3: Add the configuration handoff delay**

Add this constant beside the other application timing constants:

```c
#define APP_CONFIG_HANDOFF_DELAY_MS 750
```

Add this as the first action after the null check in
`handle_config_changed()`:

```c
vTaskDelay(pdMS_TO_TICKS(APP_CONFIG_HANDOFF_DELAY_MS));
```

This delay occurs on the coordinator task after the portal callback has queued
the new configuration. It lets the HTTP server send the success response before
station/AP mode changes disconnect the setup client.

- [ ] **Step 4: Enter stable recovery on Wi-Fi timeout**

Replace the beginning of the `PROVISION_EVENT_WIFI_TIMEOUT` case with:

```c
case PROVISION_EVENT_WIFI_TIMEOUT: {
    const esp_err_t recovery_error =
        provisioning_runtime_enter_stable_recovery();
    if (recovery_error != ESP_OK) {
        ESP_LOGW(TAG,
                 "stable recovery start failed: %s",
                 esp_err_to_name(recovery_error));
    }
    mqtt_relay_set_wifi_connected(false);
```

Keep the existing MQTT stop/state cleanup below it. The existing
`apply_reducer_requirements(state)` call then starts or preserves captive DNS
and HTTP after the AP is stable.

- [ ] **Step 5: Run the coordinator contracts**

Run:

```powershell
python -m pytest tools/tests/test_startup_contract.py tools/tests/test_portal_contract.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Review the coordinator checkpoint**

Run:

```powershell
rg -n -C 8 "PROVISION_EVENT_WIFI_TIMEOUT|APP_CONFIG_HANDOFF_DELAY_MS" main/app_main.c
```

Expected: response grace precedes network teardown and Wi-Fi timeout invokes
stable recovery before MQTT cleanup.

### Task 4: Make the portal explain the exact BLE and network state

**Files:**
- Modify: `components/portal_http/portal.js`
- Modify: `components/portal_http/portal.html`
- Modify: `tools/tests/test_portal_contract.py`

- [ ] **Step 1: Add failing Korean copy assertions**

Add this test to `tools/tests/test_portal_contract.py`:

```python
def test_portal_explains_ble_silence_and_network_handoff():
    html = read("components/portal_http/portal.html")
    js = read("components/portal_http/portal.js")

    assert "미등록 · 광고 꺼짐" in js
    assert "등록된 iPhone만 자동으로 다시 연결" in js
    assert "설정 AP가 잠시 종료됩니다" in js
    assert "연결에 실패하면 설정 AP가 자동으로 다시 나타납니다" in js
    assert "등록 전에는 Bluetooth 등록 신호를 보내지 않습니다" in html
```

- [ ] **Step 2: Run the portal test and verify it fails**

Run:

```powershell
python -m pytest tools/tests/test_portal_contract.py::test_portal_explains_ble_silence_and_network_handoff -q
```

Expected: FAIL because the exact approved copy is not present.

- [ ] **Step 3: Update the BLE status copy**

Replace the unbonded branch in `components/portal_http/portal.js` with:

```javascript
} else {
  updateTile('status-ble', 'neutral', '미등록 · 광고 꺼짐', '등록 시작 전에는 Bluetooth 신호를 보내지 않습니다');
  $('ble-guidance').textContent = 'iPhone 등록 시작을 누르면 등록 신호를 보냅니다. 등록된 iPhone만 전원을 켠 뒤 자동으로 다시 연결됩니다.';
}
```

Replace the bonded-but-disconnected guidance with:

```javascript
$('ble-guidance').textContent = '등록된 iPhone만 자동으로 다시 연결합니다. 버튼을 누르면 기존 iPhone 연결 신호를 즉시 다시 보냅니다.';
```

- [ ] **Step 4: Update save/connect guidance**

Replace the successful save message in `components/portal_http/portal.js` with:

```javascript
setMessage(
  '설정을 저장했습니다. 연결을 위해 설정 AP가 잠시 종료됩니다. 연결에 실패하면 설정 AP가 자동으로 다시 나타납니다.',
  'success',
);
```

Replace the static BLE paragraph in `components/portal_http/portal.html` with:

```html
<p id="ble-guidance">등록 전에는 Bluetooth 등록 신호를 보내지 않습니다. iPhone 등록 시작을 누르면 등록을 시작하고, 등록된 iPhone은 이후 자동으로 다시 연결됩니다.</p>
```

- [ ] **Step 5: Run the portal contract**

Run:

```powershell
python -m pytest tools/tests/test_portal_contract.py -q
```

Expected: all portal tests pass.

### Task 5: Build, flash, and prove the device behavior

**Files:**
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/VALIDATION_REPORT.md`
- Generated: `build/ios_ancs_capture_c6.bin`
- Generated: `build-tests/`

- [ ] **Step 1: Run all host tests**

Run from the project root:

```powershell
python -m pytest tools/tests -q
```

Expected: all host tests pass with zero failures.

- [ ] **Step 2: Build production firmware**

Run:

```powershell
.\tools\build.ps1
```

Expected: ESP-IDF v6.0.2 completes the ESP32-C6 build and produces
`build/ios_ancs_capture_c6.bin`.

- [ ] **Step 3: Build and run device-side Unity tests**

Run:

```powershell
$idfPath = (Resolve-Path '..\..\work\sdk\esp-idf-6.0.2').Path
$command = @(
  "call `"$idfPath\export.bat`""
  'idf.py -B build-tests build'
  'idf.py -B build-tests -p COM9 flash'
) -join ' && '
cmd.exe /d /s /c $command
python tools/capture_unity_serial.py --port COM9 --baud 115200 --timeout 180
```

Expected: serial output ends with `ANCS_TEST_RESULT failures=0`.

- [ ] **Step 4: Rebuild and flash production firmware to COM9**

Run:

```powershell
.\tools\build.ps1
.\tools\flash.ps1 -Port COM9
```

Expected: esptool verifies all written segments and the ESP32-C6 restarts into
the production application.

- [ ] **Step 5: Prove stable recovery through serial and DAISO**

With the configured target Wi-Fi unavailable or too weak to connect:

1. Capture serial output until the station attempt times out.
2. Require a station-stop/recovery log followed by
   `setup AP started ... ip=192.168.4.1`.
3. Connect only the DAISO adapter to `IOS-ANCS-SETUP-572B20`.
4. Confirm DAISO receives `192.168.4.x`.
5. Load `http://192.168.4.1/` repeatedly.
6. Press `Wi-Fi 검색` at least three times.
7. Require HTTP success and a non-error scan response without the AP
   disappearing between scans.

Do not disable, reset, reconnect, or reconfigure the AX1800 adapter.

- [ ] **Step 6: Prove save/connect failure recovery**

Submit the stored Wi-Fi and MQTT settings without printing either password.
Require:

1. The browser receives the saved-success message.
2. The setup AP disappears for the bounded station attempt.
3. If station connection fails, the same setup AP reappears automatically.
4. DAISO reconnects and `http://192.168.4.1/api/status` reports
   `ap_started=true`, `sta_started=false`, and `sta_connecting=false`.

- [ ] **Step 7: Prove BLE behavior**

Use status JSON, serial logs, and iPhone Bluetooth observation:

1. If the C6 bond list is empty, reboot and require
   `ble_bonded=false`, `enroll_window_open=false`, and no connectable
   `IOS-ANCS-C6-*` advertisement.
2. Press `iPhone 등록 시작` and require the advertisement to appear for the
   bounded enrollment window.
3. Complete bonding, reboot, and require automatic advertisement/reconnection
   for the registered iPhone.
4. Press `iPhone 등록 시작` while bonded and verify it advertises for the
   existing iPhone without opening pairing to a different peer.

Do not erase the current bond merely to make a claim. If unbonded behavior
cannot be physically exercised without destructive replacement, report the
Unity/source proof separately and retain that physical verification gap.

- [ ] **Step 8: Prove MQTT remains independent of the recovery page**

When station Wi-Fi succeeds, require:

1. MQTT connection state becomes connected.
2. The retained availability topic becomes `online`.
3. One eligible non-Home-Assistant iOS notification reaches the MQTT relay.
4. A Home Assistant echo-marked notification remains excluded.

Do not claim MQTT success from saved configuration alone.

- [ ] **Step 9: Record validation evidence**

Add a dated section to `docs/VALIDATION_REPORT.md` containing:

- host pytest result;
- production and Unity build result;
- firmware SHA-256;
- COM9 flash verification;
- serial Wi-Fi timeout/recovery lines;
- DAISO DHCP address and repeated HTTP/scan results;
- BLE bond/window/advertising evidence;
- MQTT connection and one notification result;
- every untested physical branch.

Add this recovery explanation to `docs/TROUBLESHOOTING.md`:

```markdown
### Setup AP is visible but the page or Wi-Fi scan fails

After a station connection timeout, current firmware stops station retries and
returns to stable recovery mode. Reconnect to `IOS-ANCS-SETUP-*`, open
`http://192.168.4.1/`, and run Wi-Fi search again. Saving settings intentionally
disconnects the setup AP for one bounded station attempt; if that attempt
fails, the setup AP returns automatically.
```

- [ ] **Step 10: Final self-check**

Run:

```powershell
python -m pytest tools/tests -q
Get-FileHash build/ios_ancs_capture_c6.bin -Algorithm SHA256
rg -n "failures=0|ap_started=true|sta_started=false|sta_connecting=false|MQTT" docs/VALIDATION_REPORT.md
```

Expected: tests pass, the firmware hash is recorded, and the validation report
contains device-side evidence or explicitly states the remaining physical gap.
