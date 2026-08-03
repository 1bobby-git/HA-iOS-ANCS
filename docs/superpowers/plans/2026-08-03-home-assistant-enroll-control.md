# Home Assistant Enroll Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move ordinary iPhone enrollment from the captive portal to an automatically discovered Home Assistant MQTT button while preserving safe BOOT-button enrollment and existing-bond protection.

**Architecture:** Extend the existing `mqtt_relay` client with retained Home Assistant button discovery and an exact non-retained command subscription. Convert a valid command into a new relay event, enqueue it through `app_main`, and call `ancs_client_request_enroll()` only from the coordinator task. Remove the ordinary portal action but retain status guidance and the confirmation-protected replacement action.

**Tech Stack:** ESP-IDF 6.0.2, ESP-MQTT, FreeRTOS queue, Home Assistant MQTT Discovery, Unity component tests, pytest contract tests, PowerShell build matrix, GitHub Pages.

---

## File Structure

- `components/mqtt_relay/include/mqtt_relay.h`: public event, topic, discovery-payload, and command-validation contracts.
- `components/mqtt_relay/mqtt_relay.c`: MQTT topic storage, discovery publishing, subscription, command validation, and relay event emission.
- `components/mqtt_relay/test/test_mqtt_payload.c`: executable Unity coverage for discovery and command validation.
- `main/app_main.c`: coordinator event handling that owns the BLE enrollment call.
- `components/portal_http/include/portal_http.h`: portal handler contract without ordinary enrollment.
- `components/portal_http/portal_http.c`: HTTP route table without `POST /api/ble/enroll`.
- `components/portal_http/portal.html`: BLE status/instructions without the ordinary action button.
- `components/portal_http/portal.js`: status text without an ordinary enrollment click handler.
- `tools/tests/test_mqtt_contract.py`: source contract for subscription lifecycle and MQTT callback safety.
- `tools/tests/test_startup_contract.py`: source contract for queued MQTT enrollment handling and preserved BOOT handling.
- `tools/tests/test_portal_contract.py`: source/render contract for the portal removal and replacement retention.
- `tools/tests/test_multi_target_contract.py`: v0.3.0 release manifest, binary, hash, and target coverage.
- `tools/build_matrix.ps1`, `tools/build.sh`: release version defaults.
- `docs/manifests/ios-ancs.json`, `docs/manifests/esp32-c6.json`: web installer v0.3.0 firmware locations.
- `docs/app.js`, `README.md`, `docs/IOS_PAIRING.md`, `docs/VALIDATION_REPORT.md`: user guidance and verified release evidence.
- `docs/firmware/<target>/ios-ancs-<target>-v0.3.0.factory.bin`: merged release images.

### Task 1: Lock the portal removal contract

**Files:**
- Modify: `tools/tests/test_portal_contract.py`
- Test: `tools/tests/test_portal_contract.py`

- [ ] **Step 1: Replace the ordinary-enrollment expectations with absence checks**

Add a test with these exact assertions while retaining the existing replacement assertions:

```python
def test_portal_moves_ordinary_enrollment_to_home_assistant():
    html = PORTAL_HTML.read_text(encoding="utf-8")
    script = PORTAL_JS.read_text(encoding="utf-8")
    source = PORTAL_SOURCE.read_text(encoding="utf-8")
    header = PORTAL_HEADER.read_text(encoding="utf-8")

    assert 'id="enroll"' not in html
    assert "$('enroll').addEventListener" not in script
    assert '"/api/ble/enroll"' not in source
    assert "ble_enroll" not in header
    assert 'id="replace-enrollment"' in html
    assert '"/api/ble/replace"' in source
    assert "Home Assistant" in html
    assert "BOOT" in html
```

Update the existing required-control and registered-route collections so they no longer require `id="enroll"`, `"/api/ble/enroll"`, or `ble_enroll`.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m pytest tools/tests/test_portal_contract.py -q
```

Expected: failure because the current HTML, JavaScript, header, and route still expose ordinary enrollment.

- [ ] **Step 3: Commit the failing contract**

```powershell
git add tools/tests/test_portal_contract.py
git commit -m "Define the portal boundary for Home Assistant enrollment" -m "Constraint: Ordinary enrollment must leave the captive portal`nConfidence: high`nScope-risk: narrow`nTested: Focused portal test fails against the old behavior`nNot-tested: Production portal changes are intentionally absent"
```

### Task 2: Define MQTT button discovery and command validation

**Files:**
- Modify: `components/mqtt_relay/include/mqtt_relay.h`
- Modify: `components/mqtt_relay/test/test_mqtt_payload.c`
- Modify: `tools/tests/test_mqtt_contract.py`
- Test: `components/mqtt_relay/test/test_mqtt_payload.c`
- Test: `tools/tests/test_mqtt_contract.py`

- [ ] **Step 1: Add failing Unity tests for topics and discovery JSON**

Add tests that call the new pure builders:

```c
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
        "homeassistant/button/ios_ancs_c6_2b20/enroll/config",
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
    TEST_ASSERT_NOT_NULL(strstr(payload, "\"unique_id\":\"ios_ancs_c6_2b20_enroll\""));
    TEST_ASSERT_NULL(strstr(payload, "secret"));
}
```

- [ ] **Step 2: Add failing Unity tests for exact, non-retained commands**

```c
TEST_CASE("enroll command rejects retained partial and malformed input", "[mqtt_relay]")
{
    const char *topic = "ios-ancs/2b20/command/enroll";
    TEST_ASSERT_TRUE(mqtt_relay_is_enroll_command(
        topic, topic, strlen(topic), "ENROLL", 6, 6, 0, false));
    TEST_ASSERT_FALSE(mqtt_relay_is_enroll_command(
        topic, topic, strlen(topic), "ENROLL", 6, 6, 0, true));
    TEST_ASSERT_FALSE(mqtt_relay_is_enroll_command(
        topic, topic, strlen(topic), "ENROLL", 3, 6, 0, false));
    TEST_ASSERT_FALSE(mqtt_relay_is_enroll_command(
        topic, topic, strlen(topic), "enroll", 6, 6, 0, false));
    TEST_ASSERT_FALSE(mqtt_relay_is_enroll_command(
        topic, "ios-ancs/2b20/command/replace", 31, "ENROLL", 6, 6, 0, false));
}
```

- [ ] **Step 3: Add failing Python lifecycle assertions**

```python
def test_home_assistant_enroll_button_is_retained_and_command_is_subscribed():
    header = read("include/mqtt_relay.h")
    source = read("mqtt_relay.c")
    assert "MQTT_RELAY_EVENT_ENROLL_REQUEST" in header
    assert "homeassistant/button/%s/enroll/config" in source
    assert '"payload_press":' in source
    assert "esp_mqtt_client_subscribe" in source
    assert "MQTT_RELAY_ENROLL_COMMAND_QOS" in source
    assert "MQTT_EVENT_DATA" in source
    assert "mqtt_relay_is_enroll_command" in source
```

- [ ] **Step 4: Run tests and verify RED**

Run:

```powershell
python -m pytest tools/tests/test_mqtt_contract.py -q
```

Expected: failure because the event, builders, subscription, and command validator do not exist.

- [ ] **Step 5: Commit the failing MQTT contract**

```powershell
git add components/mqtt_relay/test/test_mqtt_payload.c tools/tests/test_mqtt_contract.py
git commit -m "Define the MQTT enrollment control contract" -m "Constraint: Commands must not replay after reconnect`nConfidence: high`nScope-risk: moderate`nTested: MQTT contract tests fail against publish-only firmware`nNot-tested: Runtime subscription is intentionally absent"
```

### Task 3: Implement MQTT discovery, subscription, and relay event

**Files:**
- Modify: `components/mqtt_relay/include/mqtt_relay.h`
- Modify: `components/mqtt_relay/mqtt_relay.c`
- Modify: `components/mqtt_relay/test/test_mqtt_payload.c`
- Test: `tools/tests/test_mqtt_contract.py`

- [ ] **Step 1: Add the event and public pure-function declarations**

Add:

```c
typedef enum {
    MQTT_RELAY_EVENT_CONNECTED = 0,
    MQTT_RELAY_EVENT_DISCONNECTED,
    MQTT_RELAY_EVENT_FAILED,
    MQTT_RELAY_EVENT_ENROLL_REQUEST,
} mqtt_relay_event_t;

esp_err_t mqtt_relay_build_enroll_command_topic(
    const provision_config_t *config, char *out, size_t out_size);
esp_err_t mqtt_relay_build_enroll_discovery_topic(
    const provision_config_t *config, char *out, size_t out_size);
esp_err_t mqtt_relay_build_enroll_discovery_payload(
    const provision_config_t *config,
    const char *command_topic,
    const char *availability_topic,
    char *out,
    size_t out_size);
bool mqtt_relay_is_enroll_command(
    const char *expected_topic,
    const char *topic,
    size_t topic_len,
    const char *payload,
    size_t payload_len,
    size_t total_payload_len,
    size_t current_data_offset,
    bool retained);
```

- [ ] **Step 2: Add exact topic builders and command validation**

Implement builders with `snprintf` bounds checks, `provision_config_validate`, `discovery_id_is_safe`, and `topic_has_publish_wildcard`. Implement command validation as exact byte-length comparisons:

```c
static const char ENROLL_PAYLOAD[] = "ENROLL";

return !retained && current_data_offset == 0U &&
       payload_len == sizeof(ENROLL_PAYLOAD) - 1U &&
       total_payload_len == payload_len &&
       topic_len == strlen(expected_topic) &&
       memcmp(topic, expected_topic, topic_len) == 0 &&
       memcmp(payload, ENROLL_PAYLOAD, payload_len) == 0;
```

- [ ] **Step 3: Add button discovery JSON**

Use the existing bounded JSON string writer and the same device identity fields as sensor discovery. Include the exact contract from the design: name, unique ID, default entity ID, command topic, `ENROLL`, availability, QoS 1, `retain:false`, `entity_category:config`, and device metadata. Do not serialize credentials, CA material, or Wi-Fi fields.

- [ ] **Step 4: Store and publish the new topics**

Add `enroll_command_topic` and `enroll_discovery_topic` to `mqtt_relay_context_t`, build them during initialization and reconfiguration, and publish the button discovery from `mqtt_relay_publish_retained_status()` with `MQTT_RELAY_RETAINED_QOS` and `MQTT_RELAY_RETAINED_RETAIN`.

- [ ] **Step 5: Subscribe and handle data events**

On `MQTT_EVENT_CONNECTED`, subscribe to the copied command topic with QoS 1 before emitting connected. On `MQTT_EVENT_DATA`, validate against the copied expected topic and emit `MQTT_RELAY_EVENT_ENROLL_REQUEST` only on an exact match. Never call ANCS or BLE code from `mqtt_relay.c`.

- [ ] **Step 6: Run focused tests and make them GREEN**

Run:

```powershell
python -m pytest tools/tests/test_mqtt_contract.py -q
```

Then build the component tests:

```powershell
cmd /d /s /c "call C:\Users\bobby\Documents\Codex\2026-07-29\new-chat-2\work\sdk\esp-idf-6.0.2\export.bat && idf.py -C test_app -B build-tests build"
```

Expected: pytest passes and ESP-IDF builds the Unity test application without compiler or linker errors.

- [ ] **Step 7: Commit MQTT implementation**

```powershell
git add components/mqtt_relay/include/mqtt_relay.h components/mqtt_relay/mqtt_relay.c components/mqtt_relay/test/test_mqtt_payload.c tools/tests/test_mqtt_contract.py
git commit -m "Let Home Assistant request safe iPhone enrollment" -m "Constraint: MQTT callbacks may only validate and enqueue control events`nRejected: A second MQTT client | it duplicates credentials and reconnect state`nConfidence: high`nScope-risk: moderate`nDirective: Never retain enrollment commands or erase bonds from this event`nTested: MQTT contract suite and ESP-IDF test application build`nNot-tested: Broker and Home Assistant runtime are verified after flashing"
```

### Task 4: Route MQTT enrollment through the coordinator

**Files:**
- Modify: `tools/tests/test_startup_contract.py`
- Modify: `main/app_main.c`
- Test: `tools/tests/test_startup_contract.py`

- [ ] **Step 1: Write the failing coordinator test**

```python
def test_mqtt_enroll_request_runs_only_in_the_app_coordinator():
    source = APP_MAIN.read_text(encoding="utf-8")
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
    assert "MQTT_RELAY_EVENT_ENROLL_REQUEST" not in source.split(
        "static void boot_held_callback", 1
    )[0]
```

- [ ] **Step 2: Run the focused test and verify RED**

```powershell
python -m pytest tools/tests/test_startup_contract.py -q
```

Expected: failure because the new MQTT event is not handled.

- [ ] **Step 3: Implement coordinator handling**

Branch before connection failure handling:

```c
if (event == MQTT_RELAY_EVENT_ENROLL_REQUEST) {
    const esp_err_t error = ancs_client_request_enroll();
    if (error != ESP_OK) {
        ESP_LOGW(TAG, "MQTT enrollment request failed: %s", esp_err_to_name(error));
    }
    return;
}
```

Keep `mqtt_event_callback()` queue-only and preserve the BOOT callback plus existing three-second tests.

- [ ] **Step 4: Run startup and BLE security tests**

```powershell
python -m pytest tools/tests/test_startup_contract.py tools/tests/test_ble_security_contract.py -q
```

Expected: all tests pass, including existing-bond and BOOT-button protections.

- [ ] **Step 5: Commit coordinator handling**

```powershell
git add main/app_main.c tools/tests/test_startup_contract.py
git commit -m "Run MQTT enrollment from the application coordinator" -m "Constraint: BLE work cannot run in the ESP MQTT callback`nConfidence: high`nScope-risk: narrow`nTested: Startup and BLE security contracts`nNot-tested: Physical BLE advertising is verified after flash"
```

### Task 5: Remove ordinary portal enrollment and update guidance

**Files:**
- Modify: `components/portal_http/include/portal_http.h`
- Modify: `components/portal_http/portal_http.c`
- Modify: `components/portal_http/portal.html`
- Modify: `components/portal_http/portal.js`
- Modify: `main/app_main.c`
- Test: `tools/tests/test_portal_contract.py`

- [ ] **Step 1: Remove the public portal action**

Delete `ble_enroll` from `portal_http_handlers_t`, delete `handle_ble_enroll_post`, stop registering `/api/ble/enroll`, delete `portal_ble_enroll`, and remove `.ble_enroll` from `s_portal_handlers`.

- [ ] **Step 2: Remove the button and JavaScript handler**

Delete the `id="enroll"` button and its `$('enroll').addEventListener(...)` block. Retain the BLE status tile and replace guidance with text equivalent to:

```html
<p id="ble-guidance">Home Assistant의 iPhone 등록 시작 버튼을 누르거나 BOOT 버튼을 3초 동안 누르세요.</p>
```

Do not remove `id="replace-enrollment"`, `/api/ble/replace`, or the confirmation field.

- [ ] **Step 3: Run portal tests and make them GREEN**

```powershell
python -m pytest tools/tests/test_portal_contract.py -q
```

Expected: all portal tests pass and no ordinary enroll route or handler remains.

- [ ] **Step 4: Commit portal changes**

```powershell
git add components/portal_http/include/portal_http.h components/portal_http/portal_http.c components/portal_http/portal.html components/portal_http/portal.js main/app_main.c tools/tests/test_portal_contract.py
git commit -m "Keep iPhone enrollment out of the captive portal" -m "Constraint: iPhone must leave setup Wi-Fi before Bluetooth pairing`nConfidence: high`nScope-risk: narrow`nDirective: Preserve confirmed replacement as a separate maintenance path`nTested: Portal contract suite`nNot-tested: Rendered portal is checked after flashing"
```

### Task 6: Run regression verification and build every target

**Files:**
- Modify: `tools/tests/test_multi_target_contract.py`
- Modify: `tools/build_matrix.ps1`
- Modify: `tools/build.sh`
- Modify: `docs/manifests/ios-ancs.json`
- Modify: `docs/manifests/esp32-c6.json`
- Create: `docs/firmware/<target>/ios-ancs-<target>-v0.3.0.factory.bin`

- [ ] **Step 1: Change release expectations to v0.3.0 and verify RED**

Update the multi-target contract to require manifest version `0.3.0`, v0.3.0 binary paths, seven binary files, and matching SHA-256 prefixes in `docs/app.js`.

Run:

```powershell
python -m pytest tools/tests/test_multi_target_contract.py -q
```

Expected: failure while manifests and binaries remain v0.2.1.

- [ ] **Step 2: Run the complete host contract suite before building**

```powershell
python -m pytest tools/tests -q
```

Expected: every non-release test passes; only deliberate v0.3.0 artifact assertions may fail before the matrix build.

- [ ] **Step 3: Set v0.3.0 release defaults and manifests**

Set the default version in `tools/build_matrix.ps1` and `tools/build.sh` to `0.3.0`. Update both JSON manifests to version `0.3.0` and v0.3.0 paths.

- [ ] **Step 4: Build and merge all supported targets**

```powershell
.\tools\build_matrix.ps1 -Version 0.3.0
```

Expected: `artifacts/build-matrix.json` contains seven entries with `success: true`; each output is a non-empty merged factory image.

- [ ] **Step 5: Update hashes and release evidence**

Copy each complete SHA-256 and byte size from `artifacts/build-matrix.json` into `docs/VALIDATION_REPORT.md` and `README.md`; copy the first 12 uppercase hex characters into the matching `docs/app.js` board entry. Describe the HA Enroll button and BOOT three-second flow in `README.md` and `docs/IOS_PAIRING.md`.

- [ ] **Step 6: Run final static and release tests**

```powershell
python -m pytest tools/tests -q
git diff --check
```

Expected: all tests pass and `git diff --check` produces no output.

- [ ] **Step 7: Commit release artifacts**

```powershell
git add tools/build_matrix.ps1 tools/build.sh tools/tests/test_multi_target_contract.py docs/manifests docs/firmware docs/app.js README.md docs/IOS_PAIRING.md docs/VALIDATION_REPORT.md
git commit -m "Ship Home Assistant enrollment across every installer target" -m "Constraint: One public installer must remain compatible with all supported Wi-Fi and BLE ESP32 targets`nConfidence: high`nScope-risk: broad`nDirective: Rebuild every factory image whenever shared firmware changes`nTested: Full pytest suite and seven-target ESP-IDF build matrix`nNot-tested: Only the connected C6 receives physical validation"
```

### Task 7: Flash C6, verify Home Assistant control, and deploy

**Files:**
- Modify: `docs/VALIDATION_REPORT.md` if hardware evidence adds new facts.

- [ ] **Step 1: Re-identify the connected device**

```powershell
python tools/detect_port.py
```

Store the reported port in `$AncsC6Port`, then query it with ESP-IDF/esptool and require `ESP32-C6` before any flash command. Do not assume a port solely from history.

- [ ] **Step 2: Flash the fresh C6 image without erasing provisioning**

Use the detected C6 port and the build flasher arguments:

```powershell
cmd /d /s /c "call C:\Users\bobby\Documents\Codex\2026-07-29\new-chat-2\work\sdk\esp-idf-6.0.2\export.bat && idf.py -B build-esp32c6 -p $AncsC6Port flash"
```

Expected: esptool verifies all written regions and resets the C6.

- [ ] **Step 3: Capture boot and portal evidence**

Capture UART without asserting DTR/RTS reset, confirm the target is `esp32c6`, and fetch the local portal. Verify the page contains Home Assistant/BOOT guidance and does not contain an ordinary enrollment button.

- [ ] **Step 4: Verify broker discovery and Home Assistant entity**

At the configured broker, verify retained payload at:

```text
homeassistant/button/ios_ancs_c6_2b20/enroll/config
```

Verify Home Assistant contains an available `button.ios_ancs_c6_2b20_enroll` linked to the existing ANCS device whenever the C6 is online.

- [ ] **Step 5: Verify the HA command and BOOT fallback**

Press the Home Assistant button once and capture UART/BLE evidence that enrollment advertising starts. Confirm no bond-removal log occurs. Hold BOOT for three seconds and capture the same advertising evidence. If the iPhone is already bonded, verify reconnection advertising rather than replacement.

- [ ] **Step 6: Verify notification relay regressions**

Confirm the existing 34 notification sensor entities remain associated with the device and the Home Assistant echo application ID remains excluded by `relay_policy` tests. Do not generate a loop-causing Home Assistant notification.

- [ ] **Step 7: Push and verify GitHub Pages**

```powershell
git push origin main
gh run list --workflow pages.yml --limit 1
```

Wait for the workflow to finish successfully, then verify the public manifest and one firmware response from `https://1bobby-git.github.io/ios-ancs/`. Confirm public JSON reports v0.3.0 and all seven artifacts return HTTP 200 with the committed byte sizes and hashes.

- [ ] **Step 8: Record final evidence**

Update `docs/VALIDATION_REPORT.md` only with actually observed UART, MQTT, Home Assistant, BLE, and Pages evidence. Commit and push the evidence update using the Lore commit protocol, then confirm `git status --short --branch` is clean and synchronized with `origin/main`.

## Self-review Result

- Spec coverage: every portal, MQTT, coordinator, BOOT, safe-bond, multi-target, hardware, Home Assistant, and deployment requirement maps to a task above.
- Placeholder scan: every code-changing step and verification command is concrete.
- Type consistency: `MQTT_RELAY_EVENT_ENROLL_REQUEST` and all four MQTT helper signatures are identical across declaration, test, implementation, and coordinator tasks.
