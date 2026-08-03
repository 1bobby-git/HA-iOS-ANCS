# Lowercase AP, Wi-Fi Diagnostics, and Device Information Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate the setup AP password entirely in lowercase and expose live Wi-Fi diagnostics plus trustworthy ESP32 device metadata through Home Assistant MQTT Discovery.

**Architecture:** Keep Wi-Fi reads inside `provisioning_runtime`, copy a bounded non-secret snapshot through `app_main`, and let `mqtt_relay` own retained state and Discovery JSON. Compile-time target identity comes from `platform_identity`; semantic firmware version and runtime chip revision are collected by the coordinator. A 60-second FreeRTOS timer posts a coordinator event, so timer callbacks never call Wi-Fi or MQTT APIs directly.

**Tech Stack:** ESP-IDF 6.0.2, ESP Wi-Fi and esp-netif, ESP-MQTT, Home Assistant MQTT Discovery, FreeRTOS timers, Unity component tests, pytest contract tests, ESP Web Tools, PowerShell build matrix.

---

## File ownership map

- `components/provisioning/include/provisioning_runtime.h`: public non-secret Wi-Fi snapshot type and getter.
- `components/provisioning/provisioning_runtime.c`: lowercase AP credentials and live station SSID/IP/RSSI snapshot.
- `components/platform_identity/include/platform_identity.h`: accurate display model per compiled ESP32 target.
- `components/mqtt_relay/include/mqtt_relay.h`: bounded device/Wi-Fi metadata types and public builders/update API.
- `components/mqtt_relay/mqtt_relay.c`: device JSON helper, Wi-Fi Discovery builders, retained state serialization and status refresh.
- `components/mqtt_relay/test/test_mqtt_payload.c`: executable Unity coverage for JSON, topics, retained publication, metadata, and secret exclusion.
- `main/app_main.c`: device-info construction, Wi-Fi snapshot transfer, and 60-second coordinator refresh.
- `main/CMakeLists.txt`: explicit platform identity and chip-information dependencies.
- `CMakeLists.txt`: semantic release version `0.3.1` embedded in the ESP-IDF application descriptor.
- `tools/tests/test_portal_contract.py`: lowercase AP and case-sensitive infrastructure-password contracts.
- `tools/tests/test_mqtt_contract.py`: source-level state, metadata and credential-exclusion contracts.
- `tools/tests/test_startup_contract.py`: coordinator ownership and timer-event contracts.
- `tools/tests/test_multi_target_contract.py`: v0.3.1 installer manifest and binary contracts.
- `README.md`, `docs/index.html`, `docs/app.js`, `docs/manifests/*.json`, `docs/VALIDATION_REPORT.md`, `docs/TROUBLESHOOTING.md`, `docs/IOS_PAIRING.md`: operator and release documentation.

### Task 1: Lowercase setup AP password and stable target identity

**Files:**
- Modify: `tools/tests/test_portal_contract.py`
- Modify: `components/provisioning/include/provisioning_runtime.h`
- Modify: `components/provisioning/provisioning_runtime.c`
- Modify: `components/platform_identity/include/platform_identity.h`
- Modify: `CMakeLists.txt`

- [ ] **Step 1: Write failing AP and identity contract tests**

Add tests that require separate uppercase and lowercase suffix formats, preserve the infrastructure password copy, and require a display model for every supported target:

```python
def test_setup_ap_password_is_lowercase_without_normalizing_station_password():
    header = read("components/provisioning/include/provisioning_runtime.h")
    runtime = read("components/provisioning/provisioning_runtime.c")
    assert '#define PROVISIONING_RUNTIME_AP_PASSWORD_PREFIX "ancs-"' in header
    identity = runtime.split("static esp_err_t make_ap_identity", 1)[1].split(
        "static void fill_ap_config", 1
    )[0]
    assert '"%02X%02X%02X"' in identity
    assert '"%02x%02x%02x"' in identity
    start_sta = runtime.split("esp_err_t provisioning_runtime_start_sta", 1)[1].split(
        "esp_err_t provisioning_runtime_stop_sta", 1
    )[0]
    assert "config->wifi_password" in start_sta
    assert "tolower" not in start_sta

def test_platform_identity_defines_home_assistant_model_for_every_target():
    identity = read("components/platform_identity/include/platform_identity.h")
    for model in ("ESP32", "ESP32-C2", "ESP32-C3", "ESP32-C5", "ESP32-C6", "ESP32-C61", "ESP32-S3"):
        assert f'#define ANCS_DEVICE_MODEL "{model}"' in identity
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tools/tests/test_portal_contract.py -q
```

Expected: FAIL because the password prefix is `ANCS-`, the password reuses the uppercase suffix, and `ANCS_DEVICE_MODEL` does not exist.

- [ ] **Step 3: Implement the minimal credential and identity changes**

Use distinct buffers in `make_ap_identity()`:

```c
char ssid_suffix[7] = {0};
char password_suffix[7] = {0};
(void)snprintf(ssid_suffix, sizeof(ssid_suffix), "%02X%02X%02X", mac[3], mac[4], mac[5]);
(void)snprintf(password_suffix, sizeof(password_suffix), "%02x%02x%02x", mac[3], mac[4], mac[5]);
```

Set `PROVISIONING_RUNTIME_AP_PASSWORD_PREFIX` to `"ancs-"`. Leave the station-password `strlcpy` unchanged. Define `ANCS_DEVICE_MODEL` inside each existing target branch and set the project version before `project()`:

```cmake
set(PROJECT_VER "0.3.1")
project(ios_ancs_capture_c6)
```

- [ ] **Step 4: Verify GREEN**

Run the focused pytest command again. Expected: all selected tests PASS.

- [ ] **Step 5: Commit**

Commit only Task 1 files using the repository Lore trailers and record the focused pytest result.

### Task 2: Provide a bounded live Wi-Fi snapshot

**Files:**
- Modify: `tools/tests/test_portal_contract.py`
- Modify: `components/provisioning/include/provisioning_runtime.h`
- Modify: `components/provisioning/provisioning_runtime.c`

- [ ] **Step 1: Write the failing snapshot contract test**

```python
def test_provisioning_runtime_exposes_non_secret_wifi_snapshot():
    header = read("components/provisioning/include/provisioning_runtime.h")
    runtime = read("components/provisioning/provisioning_runtime.c")
    assert "provisioning_wifi_snapshot_t" in header
    assert "char ssid[PROVISION_WIFI_SSID_MAX + 1]" in header
    assert "char ip[16]" in header
    assert "int32_t rssi" in header
    assert "provisioning_runtime_get_wifi_snapshot" in header
    getter = runtime.split("esp_err_t provisioning_runtime_get_wifi_snapshot", 1)[1]
    assert "esp_wifi_sta_get_ap_info" in getter
    assert "esp_netif_get_ip_info" in getter
    assert "esp_ip4addr_ntoa" in getter
    assert "password" not in getter
```

- [ ] **Step 2: Verify RED**

Run the single pytest test. Expected: FAIL because the snapshot type and getter do not exist.

- [ ] **Step 3: Implement the getter**

Add this public shape:

```c
typedef struct {
    bool connected;
    char ssid[PROVISION_WIFI_SSID_MAX + 1];
    char ip[16];
    int32_t rssi;
} provisioning_wifi_snapshot_t;
```

The getter must zero the output, read `s_sta_has_ip` under the existing state lock, return an empty disconnected snapshot when false, and otherwise call `esp_wifi_sta_get_ap_info()`, `esp_netif_get_ip_info(s_sta_netif, ...)`, and `esp_ip4addr_ntoa()`. Set `connected=true` only after every live read succeeds. Never copy a password into the snapshot.

- [ ] **Step 4: Verify GREEN and build the provisioning component**

Run:

```powershell
python -m pytest tools/tests/test_portal_contract.py::test_provisioning_runtime_exposes_non_secret_wifi_snapshot -q
cmd /d /s /c "call C:\Users\bobby\Documents\Codex\2026-07-29\new-chat-2\work\sdk\esp-idf-6.0.2\export.bat && idf.py -B build-esp32c6 -DIDF_TARGET=esp32c6 build"
```

Expected: the focused test passes and the ESP32-C6 production image compiles.

- [ ] **Step 5: Commit**

Commit the snapshot API and its test with Lore trailers.

### Task 3: Define MQTT device metadata and Wi-Fi Discovery builders

**Files:**
- Modify: `components/mqtt_relay/include/mqtt_relay.h`
- Modify: `components/mqtt_relay/mqtt_relay.c`
- Modify: `components/mqtt_relay/test/test_mqtt_payload.c`
- Modify: `tools/tests/test_mqtt_contract.py`

- [ ] **Step 1: Write failing Unity tests for device metadata**

Create a fixture:

```c
static mqtt_relay_device_info_t valid_device_info(void)
{
    mqtt_relay_device_info_t info = {0};
    strcpy(info.manufacturer, "Espressif Systems");
    strcpy(info.model, "ESP32-C6");
    strcpy(info.sw_version, "0.3.1");
    strcpy(info.hw_version, "rev 0.1");
    return info;
}
```

Update the aggregate, field, and enrollment Discovery tests to pass this fixture and assert each payload contains:

```c
TEST_ASSERT_NOT_NULL(strstr(payload, "\"manufacturer\":\"Espressif Systems\""));
TEST_ASSERT_NOT_NULL(strstr(payload, "\"model\":\"ESP32-C6\""));
TEST_ASSERT_NOT_NULL(strstr(payload, "\"sw_version\":\"0.3.1\""));
TEST_ASSERT_NOT_NULL(strstr(payload, "\"hw_version\":\"rev 0.1\""));
```

- [ ] **Step 2: Write failing Unity tests for three Wi-Fi sensors**

Require keys `wifi_ssid`, `wifi_ip`, and `wifi_rssi`; state topic `<base>/state`; `entity_category:"diagnostic"`; and RSSI metadata `device_class:"signal_strength"`, `state_class:"measurement"`, `unit_of_measurement:"dBm"`.

- [ ] **Step 3: Verify RED with an ESP32-C6 Unity build**

Run:

```powershell
cmd /d /s /c "call C:\Users\bobby\Documents\Codex\2026-07-29\new-chat-2\work\sdk\esp-idf-6.0.2\export.bat && idf.py -C test_app -B ba -DIDF_TARGET=esp32c6 build"
```

Expected: compilation fails because the new types and builders do not exist.

- [ ] **Step 4: Implement bounded types and one shared device JSON helper**

Add:

```c
typedef struct {
    char manufacturer[32];
    char model[24];
    char sw_version[32];
    char hw_version[24];
} mqtt_relay_device_info_t;

typedef struct {
    bool connected;
    char ssid[PROVISION_WIFI_SSID_MAX + 1];
    char ip[16];
    int32_t rssi;
} mqtt_relay_wifi_status_t;
```

Create a single `append_device_json()` helper that JSON-escapes all strings and appends identifiers, name, manufacturer, model, `sw_version`, and `hw_version`. Change every Discovery builder to require the same validated device-info object and use this helper.

- [ ] **Step 5: Implement Wi-Fi Discovery descriptors and builders**

Add a three-entry table with templates reading `value_json.wifi_ssid`, `value_json.wifi_ip`, and `value_json.wifi_rssi`. Provide count/key/topic/payload APIs parallel to the existing notification-field APIs, but point payloads at `state_topic`.

- [ ] **Step 6: Verify GREEN**

Run the component tests and `python -m pytest tools/tests/test_mqtt_contract.py -q`. Expected: PASS with no secret strings in state or Discovery builder sections.

- [ ] **Step 7: Commit**

Commit the MQTT schema and builder changes with Lore trailers.

### Task 4: Publish retained Wi-Fi state safely

**Files:**
- Modify: `components/mqtt_relay/include/mqtt_relay.h`
- Modify: `components/mqtt_relay/mqtt_relay.c`
- Modify: `components/mqtt_relay/test/test_mqtt_payload.c`
- Modify: `tools/tests/test_mqtt_contract.py`

- [ ] **Step 1: Write failing state and retained-publication tests**

Pass a Wi-Fi status fixture to `mqtt_relay_build_state_payload()` and require:

```c
TEST_ASSERT_NOT_NULL(strstr(payload, "\"wifi_ssid\":\"EDENARI\""));
TEST_ASSERT_NOT_NULL(strstr(payload, "\"wifi_ip\":\"192.168.1.42\""));
TEST_ASSERT_NOT_NULL(strstr(payload, "\"wifi_rssi\":-61"));
TEST_ASSERT_NULL(strstr(payload, "password"));
```

Change the retained publish expectation to:

```c
mqtt_relay_discovery_field_count() +
    mqtt_relay_wifi_discovery_field_count() + 4U
```

and assert all three Wi-Fi Discovery messages are retained at QoS 1.

- [ ] **Step 2: Verify RED**

Run the focused component tests. Expected: signature/count/payload failures.

- [ ] **Step 3: Implement state serialization and runtime update**

Store `device_info` and `wifi_status` in `mqtt_relay_context_t`. Update the state builder to use the existing bounded JSON writer for SSID and IP. Serialize disconnected Wi-Fi as empty strings with `wifi_rssi:null`.

Add:

```c
esp_err_t mqtt_relay_update_wifi_status(const mqtt_relay_wifi_status_t *status);
```

It validates/copies the snapshot under the relay mutex and publishes only the retained state topic when MQTT is currently connected. Do not republish every Discovery message during the 60-second refresh.

- [ ] **Step 4: Extend initial retained publication**

The MQTT-connected path publishes aggregate Discovery, enrollment Discovery, all notification-field Discovery messages, all Wi-Fi Discovery messages, retained state, and availability. Copy only client ID, device info, Wi-Fi status, counters, and topics under the lock; never copy credentials into the retained-publication stack snapshot.

- [ ] **Step 5: Verify GREEN and ownership safety**

Run component tests plus `tools/tests/test_mqtt_contract.py`. Confirm lifecycle tests still prove publish-reference draining before teardown.

- [ ] **Step 6: Commit**

Commit retained state publication and tests with Lore trailers.

### Task 5: Wire metadata and 60-second refresh through the coordinator

**Files:**
- Modify: `tools/tests/test_startup_contract.py`
- Modify: `main/app_main.c`
- Modify: `main/CMakeLists.txt`

- [ ] **Step 1: Write failing coordinator contract tests**

Require:

```python
assert "APP_WIFI_STATUS_REFRESH_MS 60000" in source
assert "APP_EVENT_WIFI_STATUS_REFRESH" in source
assert "wifi_status_timer_callback" in source
assert "provisioning_runtime_get_wifi_snapshot" in source
assert "mqtt_relay_update_wifi_status" in source
assert "esp_app_get_description" in source
assert "esp_chip_info" in source
assert "ANCS_DEVICE_MODEL" in source
```

Also assert the timer callback only posts an event, the coordinator switch performs the live reads, the timer starts on `MQTT_RELAY_EVENT_CONNECTED`, and it stops on Wi-Fi/MQTT failure or relay teardown.

- [ ] **Step 2: Verify RED**

Run the focused startup contract tests. Expected: FAIL because the event, timer and metadata construction are absent.

- [ ] **Step 3: Construct truthful device information**

Build `mqtt_relay_device_info_t` before relay initialization:

```c
strlcpy(info.manufacturer, "Espressif Systems", sizeof(info.manufacturer));
strlcpy(info.model, ANCS_DEVICE_MODEL, sizeof(info.model));
strlcpy(info.sw_version, esp_app_get_description()->version, sizeof(info.sw_version));
esp_chip_info_t chip = {0};
esp_chip_info(&chip);
snprintf(info.hw_version, sizeof(info.hw_version), "rev %u.%u",
         chip.revision / 100U, chip.revision % 100U);
```

Pass it into `mqtt_relay_init()` so the first Discovery publication already has complete metadata.

- [ ] **Step 4: Transfer and periodically refresh Wi-Fi status**

Create `refresh_wifi_status()` to call `provisioning_runtime_get_wifi_snapshot()`, convert only `connected`, SSID, IP and RSSI, and call `mqtt_relay_update_wifi_status()`. Call it after relay initialization but before MQTT start/reconnect. Add an auto-reload 60-second FreeRTOS timer whose callback posts `APP_EVENT_WIFI_STATUS_REFRESH`; handle the event in the coordinator task.

- [ ] **Step 5: Verify GREEN and compile all coordinator dependencies**

Run:

```powershell
python -m pytest tools/tests/test_startup_contract.py -q
cmd /d /s /c "call C:\Users\bobby\Documents\Codex\2026-07-29\new-chat-2\work\sdk\esp-idf-6.0.2\export.bat && idf.py -B build-esp32c6 -DIDF_TARGET=esp32c6 build"
```

Expected: startup contracts pass and the production image compiles without implicit-component dependency errors.

- [ ] **Step 6: Commit**

Commit coordinator wiring and tests with Lore trailers.

### Task 6: Update release, installer and operator documentation

**Files:**
- Modify: `tools/tests/test_multi_target_contract.py`
- Modify: `tools/build_matrix.ps1`
- Modify: `tools/build.ps1`
- Modify: `tools/build.sh`
- Modify: `README.md`
- Modify: `docs/index.html`
- Modify: `docs/app.js`
- Modify: `docs/manifests/ios-ancs.json`
- Modify: `docs/manifests/esp32-c6.json`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/IOS_PAIRING.md`
- Modify: `docs/VALIDATION_REPORT.md`

- [ ] **Step 1: Write failing v0.3.1 release tests**

Change installer tests to require manifest version `0.3.1`, v0.3.1 binary paths, lowercase setup password guidance, three Home Assistant Wi-Fi sensors, and manufacturer/model/firmware/hardware device metadata.

- [ ] **Step 2: Verify RED**

Run `python -m pytest tools/tests/test_multi_target_contract.py -q`. Expected: FAIL on current v0.3.0 strings and binaries.

- [ ] **Step 3: Update source-controlled release metadata and guidance**

Use `0.3.1` consistently. Document `ancs-<lowercase_suffix>`, warn that infrastructure Wi-Fi passwords stay case-sensitive, and list the new diagnostic sensors/device details. Do not document or print any live Wi-Fi/MQTT secret.

- [ ] **Step 4: Build all seven targets**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File tools/build_matrix.ps1 -Version 0.3.1
```

Expected: `esp32`, `esp32c2`, `esp32c3`, `esp32c5`, `esp32c6`, `esp32c61`, and `esp32s3` all succeed and generate factory binaries plus SHA-256 summary.

- [ ] **Step 5: Update manifests from actual build output and verify GREEN**

Insert only measured sizes and SHA-256 values. Run the complete host suite:

```powershell
python -m pytest tools/tests -q
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

Commit v0.3.1 documentation, manifests and binaries with measured results in Lore trailers.

### Task 7: Hardware, broker, Home Assistant and public release verification

**Files:**
- Modify: `docs/VALIDATION_REPORT.md`
- Create: `artifacts/v0.3.1/*` evidence files as appropriate; do not commit secrets.

- [ ] **Step 1: Release the browser-owned WROOM serial port and identify the device**

Close only the ESP Web Tools serial/log session, then run:

```powershell
python -m esptool --port COM7 --baud 115200 --after hard-reset chip-id
```

Expected: classic ESP32 identity. If the port mapping changed, re-enumerate serial devices before any flash.

- [ ] **Step 2: Flash WROOM without erasing NVS and verify boot/AP**

Flash the v0.3.1 ESP32 image normally, capture UART, and require project version `0.3.1`, target `esp32`, setup AP `IOS-ANCS-SETUP-AAF738`, and lowercase password `ancs-aaf738`. Confirm the old uppercase password no longer authenticates. Do not modify AX1800.

- [ ] **Step 3: Verify Wi-Fi recovery behavior on WROOM**

Record that the previous v0.3.0 image booted successfully but `EXAMPLE_OFFICE14_4F` timed out at RSSI `-88` to `-95 dBm` with reasons 2 and 4. Use the setup portal to select an operator-authorized reachable 2.4 GHz network; do not infer or alter unrelated router credentials.

- [ ] **Step 4: Re-identify and flash the C6 when COM9 is present**

Read chip ID and MAC immediately before a normal non-erase flash. Update only the DAISO profile to `ancs-abc123`, leave AX1800 untouched, and verify AP/portal plus stored infrastructure Wi-Fi and MQTT settings.

- [ ] **Step 5: Verify retained MQTT and Home Assistant registration**

Capture retained `<base>/state` with SSID, IP and RSSI but no password. Verify Home Assistant creates all three diagnostic sensors under the existing device and shows `Espressif Systems`, correct model, `0.3.1`, and live chip revision. Confirm the enrollment button and notification sensors remain attached to the same device.

- [ ] **Step 6: Restore temporary connectivity and record gaps**

Restore the C6's original network/MQTT settings, stop any temporary tunnel or hotspot, verify port 1884 is closed, and confirm AX1800 stayed unchanged. If C6 hardware is absent, mark that exact proof pending rather than transferring WROOM evidence.

- [ ] **Step 7: Push and verify GitHub Pages**

Push `main`, wait for the Pages workflow, then fetch the public page, both manifests, and all seven binaries. Compare public SHA-256 values with the local build summary and confirm the installer advertises v0.3.1.

- [ ] **Step 8: Final verification commit**

Update `docs/VALIDATION_REPORT.md` with only fresh evidence, run `git diff --check` and the full host suite once more, commit with Lore trailers, push, and verify the final public commit and Pages deployment.
