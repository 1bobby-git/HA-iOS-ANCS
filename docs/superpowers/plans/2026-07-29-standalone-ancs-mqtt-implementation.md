# Standalone ANCS MQTT Relay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the ESP32-C6 a power-only ANCS-to-MQTT appliance with automatic captive-portal provisioning, explicit BLE Enroll, and exactly-once Home Assistant relay behavior.

**Architecture:** Keep ANCS transport isolated, add pure policy/state components, place Wi-Fi/AP/HTTP and MQTT in separate owners, and preserve serial JSON as a diagnostic sink. Provisioning settings live in a separate NVS partition, network notification payloads are heap-owned JSON pointers, and Home Assistant consumes a Discovery sensor whose state is a stable relay ID.

**Tech Stack:** ESP-IDF v6.0.2, ESP32-C6 Bluedroid, `esp_wifi`, `esp_http_server`, bundled captive-portal DNS code, NVS, managed `espressif/mqtt`, cJSON, FreeRTOS, Unity, pytest, Home Assistant MQTT Discovery.

**Repository note:** This directory has no Git metadata. Replace each commit step with a Ralph checkpoint recorded in `.omx/state/ralph-progress.json`.

---

## File structure

### New firmware components

- `components/provision_store/`: schema validation, two-slot atomic NVS persistence, redaction
- `components/provisioning/`: pure AP/STA/MQTT/bond state reducer and runtime coordinator
- `components/portal_http/`: embedded portal, HTTP API and captive-probe routes
- `components/ble_enroll/`: BOOT debounce/long-press, Enroll window, bond allow policy
- `components/relay_policy/`: pure filter, duplicate cache and relay ID
- `components/mqtt_relay/`: MQTT client, topics, Discovery, LWT, queue ownership and counters

### New project artifacts

- `partitions.csv`
- `idf_component.yml`
- `homeassistant/automation_ios_ancs_c6_relay.yaml`
- `tools/tests/test_partition_contract.py`
- `tools/tests/test_portal_contract.py`
- `tools/tests/test_mqtt_contract.py`
- `tools/tests/test_home_assistant_automation.py`

### Existing files to modify

- `main/app_main.c`
- `main/CMakeLists.txt`
- `components/ancs_client/ancs_client.c`
- `components/ancs_client/include/ancs_client.h`
- `components/notification_sink/include/notification_sink.h`
- `components/notification_sink/notification_sink_serial.c`
- `components/notification_sink/CMakeLists.txt`
- `test_app/main/test_main.c`
- `test_app/main/CMakeLists.txt`
- `sdkconfig.defaults`
- `README.md`
- `docs/IOS_PAIRING.md`
- `docs/TROUBLESHOOTING.md`
- `docs/VALIDATION_REPORT.md`

## Task 1: Lock the partition and dependency contract

**Files:**

- Create: `tools/tests/test_partition_contract.py`
- Create: `partitions.csv`
- Create: `idf_component.yml`
- Modify: `sdkconfig.defaults`

- [ ] **Step 1: Write the failing partition contract**

```python
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_partition_table_preserves_bond_nvs_and_adds_provision_nvs():
    text = (ROOT / "partitions.csv").read_text(encoding="utf-8")
    assert "nvs,data,nvs,0x9000,0x6000" in text.replace(" ", "")
    assert "provision,data,nvs" in text.replace(" ", "")


def test_idf6_uses_external_esp_mqtt_component():
    text = (ROOT / "idf_component.yml").read_text(encoding="utf-8")
    assert "espressif/mqtt:" in text
```

- [ ] **Step 2: Run the test and confirm RED**

Run:

```powershell
python -m pytest tools/tests/test_partition_contract.py -q
```

Expected: FAIL because `partitions.csv` and `idf_component.yml` do not exist.

- [ ] **Step 3: Add the exact partition/dependency configuration**

`partitions.csv`:

```csv
# Name,      Type, SubType, Offset,   Size,     Flags
nvs,         data, nvs,     0x9000,   0x6000,
phy_init,    data, phy,     0xf000,   0x1000,
factory,     app,  factory, 0x10000,  0x200000,
provision,   data, nvs,     0x210000, 0x20000,
coredump,    data, coredump,0x230000, 0x10000,
```

`idf_component.yml`:

```yaml
dependencies:
  idf:
    version: ">=6.0.2,<6.1"
  espressif/mqtt: "^1.0.0"
```

Add to `sdkconfig.defaults`:

```text
CONFIG_ESPTOOLPY_FLASHSIZE_8MB=y
CONFIG_PARTITION_TABLE_CUSTOM=y
CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions.csv"
CONFIG_MBEDTLS_CERTIFICATE_BUNDLE=y
CONFIG_ESP_COEX_SW_COEXIST_ENABLE=y
```

- [ ] **Step 4: Verify GREEN and build dependency resolution**

Run:

```powershell
python -m pytest tools/tests/test_partition_contract.py -q
.\tools\build.ps1
```

Expected: partition contract passes; managed MQTT resolves; main firmware still links.

- [ ] **Step 5: Record Ralph checkpoint**

Set Task 1 complete in `.omx/state/ralph-progress.json` with the exact test/build outputs.

## Task 2: Implement atomic provisioning storage

**Files:**

- Create: `components/provision_store/CMakeLists.txt`
- Create: `components/provision_store/include/provision_store.h`
- Create: `components/provision_store/provision_store.c`
- Create: `components/provision_store/test/test_provision_config.c`
- Modify: `test_app/main/CMakeLists.txt`
- Modify: `test_app/main/test_main.c`

- [ ] **Step 1: Define the desired API in a failing Unity test**

```c
void test_provision_config_requires_wifi_and_mqtt(void)
{
    provision_config_t config = {0};
    TEST_ASSERT_EQUAL(
        PROVISION_CONFIG_MISSING_WIFI,
        provision_config_validate(&config));
    strcpy(config.wifi_ssid, "ssid");
    TEST_ASSERT_EQUAL(
        PROVISION_CONFIG_MISSING_MQTT_HOST,
        provision_config_validate(&config));
}

void test_tls_requires_ca(void)
{
    provision_config_t config = valid_config();
    config.mqtt_tls = true;
    config.mqtt_ca[0] = '\0';
    TEST_ASSERT_EQUAL(
        PROVISION_CONFIG_TLS_CA_REQUIRED,
        provision_config_validate(&config));
}
```

- [ ] **Step 2: Build the Unity app and confirm RED**

Run:

```powershell
Push-Location test_app
idf.py -B build-tests build
Pop-Location
```

Expected: FAIL because `provision_store.h` and functions are absent.

- [ ] **Step 3: Add concrete config types and validation**

`provision_store.h` must expose:

```c
#define PROVISION_WIFI_SSID_MAX 32
#define PROVISION_WIFI_PASSWORD_MAX 64
#define PROVISION_MQTT_HOST_MAX 128
#define PROVISION_MQTT_USERNAME_MAX 128
#define PROVISION_MQTT_PASSWORD_MAX 256
#define PROVISION_MQTT_CLIENT_ID_MAX 64
#define PROVISION_MQTT_BASE_TOPIC_MAX 128
#define PROVISION_MQTT_CA_MAX 4096

typedef struct {
    uint32_t schema_version;
    char wifi_ssid[PROVISION_WIFI_SSID_MAX + 1];
    char wifi_password[PROVISION_WIFI_PASSWORD_MAX + 1];
    char mqtt_host[PROVISION_MQTT_HOST_MAX + 1];
    uint16_t mqtt_port;
    char mqtt_username[PROVISION_MQTT_USERNAME_MAX + 1];
    char mqtt_password[PROVISION_MQTT_PASSWORD_MAX + 1];
    bool mqtt_tls;
    char mqtt_ca[PROVISION_MQTT_CA_MAX + 1];
    char mqtt_client_id[PROVISION_MQTT_CLIENT_ID_MAX + 1];
    char mqtt_base_topic[PROVISION_MQTT_BASE_TOPIC_MAX + 1];
} provision_config_t;

provision_config_result_t provision_config_validate(
    const provision_config_t *config);
esp_err_t provision_store_init(void);
esp_err_t provision_store_load(provision_config_t *out);
esp_err_t provision_store_save_atomic(const provision_config_t *config);
esp_err_t provision_store_reset(void);
```

Implement two NVS blobs `slot_a`/`slot_b`, each containing schema, generation, CRC32 and config; commit and read back the inactive slot before changing `active`.

- [ ] **Step 4: Add tests for secret preservation, CRC and reset isolation**

Tests must assert:

```c
TEST_ASSERT_EQUAL_STRING("old-secret", merged.wifi_password);
TEST_ASSERT_EQUAL_STRING("old-mqtt-secret", merged.mqtt_password);
TEST_ASSERT_EQUAL(ESP_ERR_INVALID_CRC, provision_store_decode(corrupt, &out));
TEST_ASSERT_EQUAL_STRING("provision", fake_nvs.last_erased_partition);
```

- [ ] **Step 5: Verify GREEN**

Run the Unity build and host tests. Expected: all provisioning storage tests pass.

- [ ] **Step 6: Record Ralph checkpoint**

Record exact test counts and files changed.

## Task 3: Implement the pure provisioning state reducer

**Files:**

- Create: `components/provisioning/CMakeLists.txt`
- Create: `components/provisioning/include/provisioning_state.h`
- Create: `components/provisioning/provisioning_state.c`
- Create: `components/provisioning/test/test_provisioning_state.c`

- [ ] **Step 1: Write reducer tests first**

```c
void test_no_config_starts_ap_without_button(void)
{
    provisioning_state_t next = provisioning_reduce(
        provisioning_initial(), PROVISION_EVENT_BOOT_NO_CONFIG, 0);
    TEST_ASSERT_TRUE(next.ap_required);
    TEST_ASSERT_FALSE(next.sta_required);
}

void test_network_ready_without_bond_keeps_ap(void)
{
    provisioning_state_t state = ready_network_state();
    state.has_bond = false;
    provisioning_state_t next =
        provisioning_reduce(state, PROVISION_EVENT_MQTT_CONNECTED, 0);
    TEST_ASSERT_TRUE(next.ap_required);
}
```

- [ ] **Step 2: Confirm RED**

Build `test_app`; expected missing reducer symbols.

- [ ] **Step 3: Implement a table-like reducer**

Use explicit events:

```c
typedef enum {
    PROVISION_EVENT_BOOT_NO_CONFIG,
    PROVISION_EVENT_BOOT_VALID_CONFIG,
    PROVISION_EVENT_WIFI_CONNECTED,
    PROVISION_EVENT_WIFI_TIMEOUT,
    PROVISION_EVENT_MQTT_CONNECTED,
    PROVISION_EVENT_MQTT_FAILED,
    PROVISION_EVENT_BOND_PRESENT,
    PROVISION_EVENT_BOND_REMOVED,
    PROVISION_EVENT_BOOT_HELD_3S,
    PROVISION_EVENT_PORTAL_IDLE_TIMEOUT
} provisioning_event_t;
```

The reducer must close AP only when `wifi_connected && mqtt_connected && has_bond && !recovery_window`.

- [ ] **Step 4: Verify GREEN**

Run reducer tests and full Unity build.

- [ ] **Step 5: Record Ralph checkpoint**

Record transition coverage.

## Task 4: Add relay policy and typed sink fan-out

**Files:**

- Create: `components/relay_policy/CMakeLists.txt`
- Create: `components/relay_policy/include/relay_policy.h`
- Create: `components/relay_policy/relay_policy.c`
- Create: `components/relay_policy/test/test_relay_policy.c`
- Modify: `components/notification_sink/include/notification_sink.h`
- Modify: `components/notification_sink/notification_sink_serial.c`
- Modify: `components/ancs_client/ancs_client.c`

- [ ] **Step 1: Write failing relay-policy tests**

```c
void test_pre_existing_and_offline_notifications_drop(void)
{
    ancs_notification_t n = valid_notification();
    n.event.event_flags = ANCS_EVENT_FLAG_PRE_EXISTING;
    TEST_ASSERT_EQUAL(
        RELAY_DROP_PRE_EXISTING,
        relay_policy_decide(&n, connected(), NULL));

    n.event.event_flags = 0;
    TEST_ASSERT_EQUAL(
        RELAY_DROP_OFFLINE,
        relay_policy_decide(&n, disconnected(), NULL));
}

void test_only_marked_home_assistant_echo_drops(void)
{
    ancs_notification_t n = valid_notification();
    strcpy(n.app_id, "io.robbie.HomeAssistant");
    strcpy(n.title, "[C6→HA] relay");
    TEST_ASSERT_EQUAL(RELAY_DROP_ECHO, relay_policy_decide(&n, connected(), NULL));
    strcpy(n.title, "original");
    TEST_ASSERT_EQUAL(RELAY_PUBLISH, relay_policy_decide(&n, connected(), NULL));
}
```

- [ ] **Step 2: Confirm RED**

Build Unity app; expected missing `relay_policy_decide`.

- [ ] **Step 3: Implement pure decision and stable relay ID**

Expose:

```c
typedef enum {
    RELAY_PUBLISH,
    RELAY_DROP_PRE_EXISTING,
    RELAY_DROP_OFFLINE,
    RELAY_DROP_ECHO,
    RELAY_DROP_DUPLICATE,
    RELAY_DROP_INCOMPLETE,
    RELAY_DROP_INVALID,
    RELAY_DROP_EVENT
} relay_decision_t;

relay_decision_t relay_policy_decide(
    const ancs_notification_t *notification,
    relay_connectivity_t connectivity,
    relay_recent_cache_t *cache);

esp_err_t relay_policy_build_id(
    const ancs_notification_t *notification,
    uint32_t boot_nonce,
    char *out,
    size_t out_size);
```

Hash app ID, title, subtitle, message, date, session, UID and event ID using SHA-256 truncated to 16 hex bytes.

- [ ] **Step 4: Add a typed observer without breaking serial output**

`notification_sink.h`:

```c
typedef void (*notification_sink_observer_t)(
    const ancs_notification_t *notification,
    const char *device_name,
    void *context);

esp_err_t notification_sink_register_observer(
    notification_sink_observer_t observer,
    void *context);
```

`notification_sink_publish()` must still print serial JSON, then call the registered observer from the ANCS worker context. The observer may only copy/serialize and enqueue; it must not block on network I/O.

- [ ] **Step 5: Verify GREEN and legacy regression**

Run all Unity and Python tests. Expected: serial schema unchanged; relay tests pass.

- [ ] **Step 6: Record Ralph checkpoint**

Record decision coverage and legacy test count.

## Task 5: Implement explicit BLE Enroll

**Files:**

- Create: `components/ble_enroll/CMakeLists.txt`
- Create: `components/ble_enroll/include/ble_enroll.h`
- Create: `components/ble_enroll/ble_enroll_policy.c`
- Create: `components/ble_enroll/ble_enroll_runtime.c`
- Create: `components/ble_enroll/test/test_ble_enroll_policy.c`
- Modify: `components/ancs_client/include/ancs_client.h`
- Modify: `components/ancs_client/ancs_client.c`

- [ ] **Step 1: Write failing policy tests**

```c
void test_unbonded_boot_does_not_advertise(void)
{
    ble_enroll_state_t state = ble_enroll_initial(false);
    TEST_ASSERT_FALSE(state.advertising_allowed);
}

void test_enroll_trigger_opens_120_second_window(void)
{
    ble_enroll_state_t next = ble_enroll_reduce(
        ble_enroll_initial(false), BLE_ENROLL_EVENT_TRIGGER, 1000);
    TEST_ASSERT_TRUE(next.advertising_allowed);
    TEST_ASSERT_EQUAL_UINT64(121000, next.deadline_ms);
}
```

- [ ] **Step 2: Confirm RED**

Build Unity app; expected missing policy.

- [ ] **Step 3: Add ANCS advertising control APIs**

`ancs_client.h`:

```c
esp_err_t ancs_client_init(void);
esp_err_t ancs_client_start_advertising(void);
esp_err_t ancs_client_stop_advertising(void);
void ancs_client_set_pairing_allowed(bool allowed);
bool ancs_client_is_connected(void);
```

Remove automatic unbonded advertising from the privacy-complete path. On disconnect, restart only when the bond manager reports a known bond or Enroll is active. In `ESP_GAP_BLE_SEC_REQ_EVT`, accept only a known bonded identity or active replacement/enroll window.

- [ ] **Step 4: Implement BOOT 3-second trigger and timers**

Configure the actual board BOOT GPIO through Kconfig, debounce at 20ms, fire once after 3000ms, and use an `esp_timer` to close the 120-second window.

- [ ] **Step 5: Add confirmed replacement**

`ble_enroll_replace(true)` calls Bluedroid bond enumeration/delete APIs, verifies zero bonds, then opens Enroll. `false` returns `ESP_ERR_INVALID_STATE`.

- [ ] **Step 6: Verify GREEN**

Run BLE policy tests, full Unity suite and main build.

- [ ] **Step 7: Record Ralph checkpoint**

Record advertising/security contract evidence.

## Task 6: Implement Wi-Fi APSTA, captive DNS and runtime state

**Files:**

- Create: `components/provisioning/provisioning_runtime.c`
- Create: `components/provisioning/include/provisioning_runtime.h`
- Create: `components/provisioning/captive_dns.c`
- Modify: `components/provisioning/CMakeLists.txt`

- [ ] **Step 1: Add failing source-contract tests**

`tools/tests/test_portal_contract.py` must require:

```python
assert "esp_netif_create_default_wifi_ap" in runtime
assert "WIFI_MODE_APSTA" in runtime
assert "esp_wifi_scan_get_ap_records" in runtime
assert "192.168.4.1" in runtime
assert "ESP_NETIF_CAPTIVEPORTAL_URI" in runtime
```

- [ ] **Step 2: Confirm RED**

Run only `test_portal_contract.py`; expected missing files/contracts.

- [ ] **Step 3: Adapt the official v6.0.2 examples**

Use local sources:

- `work/sdk/esp-idf-6.0.2/examples/protocols/http_server/captive_portal`
- `work/sdk/esp-idf-6.0.2/examples/wifi/softap_sta`
- `work/sdk/esp-idf-6.0.2/examples/wifi/scan`

Runtime must:

```c
esp_err_t provisioning_runtime_init(
    const provision_config_t *config,
    provisioning_event_callback_t callback,
    void *context);
esp_err_t provisioning_runtime_start_ap(void);
esp_err_t provisioning_runtime_start_sta(const provision_config_t *config);
esp_err_t provisioning_runtime_scan(wifi_ap_record_t *records, size_t *count);
```

Start AP immediately on invalid config, configure `192.168.4.1/24`, wildcard DNS and DHCP Option 114. Do not scan while STA connection is active.

- [ ] **Step 4: Implement 30-second Wi-Fi and MQTT recovery events**

Use timers that emit reducer events; do not directly decide AP closure in Wi-Fi callbacks.

- [ ] **Step 5: Verify GREEN**

Run contract tests and main firmware build.

- [ ] **Step 6: Record Ralph checkpoint**

Record build size and portal source contracts.

## Task 7: Implement the embedded portal and APIs

**Files:**

- Create: `components/portal_http/CMakeLists.txt`
- Create: `components/portal_http/include/portal_http.h`
- Create: `components/portal_http/portal_http.c`
- Create: `components/portal_http/portal.html`
- Create: `components/portal_http/portal.css`
- Create: `components/portal_http/portal.js`
- Extend: `tools/tests/test_portal_contract.py`

- [ ] **Step 1: Write failing portal contracts**

Tests assert all controls and routes, no CDN, no secret serialization, POST body maximum, AP-interface checks, and confirmation literals.

- [ ] **Step 2: Confirm RED**

Run portal contract tests.

- [ ] **Step 3: Implement a small embedded responsive portal**

Use one page with:

```html
<section id="status"></section>
<form id="wifi-config">
  <button type="button" id="scan-wifi">Wi-Fi scan</button>
  <select id="wifi-ssid"></select>
  <input id="wifi-password" type="password" autocomplete="new-password">
</form>
<form id="mqtt-config">
  <input id="mqtt-host" required>
  <input id="mqtt-port" type="number" min="1" max="65535">
  <input id="mqtt-username">
  <input id="mqtt-password" type="password">
  <input id="mqtt-tls" type="checkbox">
  <textarea id="mqtt-ca"></textarea>
</form>
<button id="enroll">Enroll</button>
<button id="replace-enrollment">Replace enrollment</button>
```

Embed assets with CMake `EMBED_FILES`; do not add a JS framework.

- [ ] **Step 4: Implement API handlers**

Register the exact routes from the design. Reject POSTs from the STA interface by checking the local socket address/interface. Cap JSON body at 8192 bytes. Return secrets only as boolean configured flags.

- [ ] **Step 5: Verify GREEN**

Run portal contracts and build.

- [ ] **Step 6: Record Ralph checkpoint**

Record route, size and secret-redaction evidence.

## Task 8: Implement MQTT relay and Discovery

**Files:**

- Create: `components/mqtt_relay/CMakeLists.txt`
- Create: `components/mqtt_relay/include/mqtt_relay.h`
- Create: `components/mqtt_relay/mqtt_payload.c`
- Create: `components/mqtt_relay/mqtt_relay.c`
- Create: `components/mqtt_relay/test/test_mqtt_payload.c`
- Create: `tools/tests/test_mqtt_contract.py`

- [ ] **Step 1: Write failing MQTT tests**

Tests capture adapter calls and assert:

```c
TEST_ASSERT_EQUAL(1, publish.qos);
TEST_ASSERT_FALSE(publish.retain);
TEST_ASSERT_EQUAL_STRING("offline", lwt.payload);
TEST_ASSERT_TRUE(discovery.retain);
TEST_ASSERT_NOT_NULL(strstr(payload, "\"source\":\"esp32c6_ancs\""));
```

- [ ] **Step 2: Confirm RED**

Run Unity and Python MQTT tests.

- [ ] **Step 3: Implement payload construction**

Expose:

```c
esp_err_t mqtt_payload_build_notification(
    const ancs_notification_t *notification,
    const char *device_name,
    const char *relay_id,
    uint64_t uptime_ms,
    char **out_payload,
    size_t *out_length);
```

Allocate exactly one bounded buffer, reuse the serial JSON field contract, add relay fields, and return ownership to the caller.

- [ ] **Step 4: Implement client configuration**

Map provisioning config into `esp_mqtt_client_config_t`:

```c
.broker.address.hostname = config->mqtt_host,
.broker.address.port = config->mqtt_port,
.credentials.username = config->mqtt_username,
.credentials.authentication.password = config->mqtt_password,
.credentials.client_id = config->mqtt_client_id,
.broker.verification.certificate = config->mqtt_tls ? config->mqtt_ca : NULL,
.session.last_will.topic = availability_topic,
.session.last_will.msg = "offline",
.session.last_will.qos = 1,
.session.last_will.retain = true,
```

- [ ] **Step 5: Implement queue ownership and publish rules**

Only enqueue while connected. Queue `mqtt_payload_item_t *`, capacity 8. Publish QoS 1 retained false. Free on matching `MQTT_EVENT_PUBLISHED`, enqueue failure, stop or fatal error exactly once. Do not accept new items while disconnected.

- [ ] **Step 6: Publish retained Discovery/state/availability**

Discovery state topic is the notification topic with `value_template` extracting `relay_id`; JSON attributes use the same payload. Availability and state are separate retained topics.

- [ ] **Step 7: Verify GREEN**

Run MQTT tests, full tests and build.

- [ ] **Step 8: Record Ralph checkpoint**

Record QoS/retain/ownership and binary size evidence.

## Task 9: Add the Home Assistant automation artifact

**Files:**

- Create: `homeassistant/automation_ios_ancs_c6_relay.yaml`
- Create: `tools/tests/test_home_assistant_automation.py`

- [ ] **Step 1: Write the failing YAML contract test**

Parse YAML and assert stable ID, sensor state trigger, from/to inequality, complete/pre-existing conditions, marker title, notify service, queued mode and no REST/webhook.

- [ ] **Step 2: Confirm RED**

Run:

```powershell
python -m pytest tools/tests/test_home_assistant_automation.py -q
```

Expected: missing YAML.

- [ ] **Step 3: Add concrete automation**

```yaml
id: ios_ancs_c6_relay_to_1bobby
alias: iOS ANCS C6 relay to 1bobby
triggers:
  - trigger: state
    entity_id: sensor.ios_ancs_c6_2b20_last_notification
conditions:
  - condition: template
    value_template: >-
      {{ trigger.from_state is not none
         and trigger.to_state is not none
         and trigger.from_state.state != trigger.to_state.state
         and trigger.to_state.state not in ['unknown', 'unavailable']
         and trigger.to_state.attributes.complete == true
         and trigger.to_state.attributes.pre_existing == false }}
actions:
  - action: notify.mobile_app_1bobby
    data:
      title: >-
        [C6→HA] {{ trigger.to_state.attributes.title
                    or trigger.to_state.attributes.app_id }}
      message: >-
        {{ trigger.to_state.attributes.message
           or trigger.to_state.attributes.subtitle
           or trigger.to_state.attributes.app_id }}
mode: queued
max: 10
```

- [ ] **Step 4: Verify GREEN**

Run YAML contract and full Python suite.

- [ ] **Step 5: Record Ralph checkpoint**

Record automation contract evidence.

## Task 10: Integrate startup and component lifecycle

**Files:**

- Modify: `main/app_main.c`
- Modify: `main/CMakeLists.txt`
- Modify: component CMake dependency lists

- [ ] **Step 1: Add a failing startup-order contract**

`tools/tests/test_startup_contract.py` must assert:

- NVS and provision store initialize before network
- relay observer registers before ANCS can complete a notification
- no-config path starts AP
- BLE init does not automatically advertise when no bond
- MQTT starts only after valid config and Wi-Fi IP

- [ ] **Step 2: Confirm RED**

Run the new test.

- [ ] **Step 3: Implement deterministic startup**

`app_main()` order:

```c
ESP_ERROR_CHECK(nvs_flash_init());
ESP_ERROR_CHECK(provision_store_init());
ESP_ERROR_CHECK(provisioning_init());
ESP_ERROR_CHECK(mqtt_relay_init());
ESP_ERROR_CHECK(notification_sink_register_observer(
    mqtt_relay_observe_notification, NULL));
ESP_ERROR_CHECK(ancs_client_init());
ESP_ERROR_CHECK(ble_enroll_init());
ESP_ERROR_CHECK(portal_http_init());
ESP_ERROR_CHECK(provisioning_start());
```

Errors that prevent safe operation must leave the AP recovery portal active rather than reboot-looping.

- [ ] **Step 4: Verify GREEN**

Run startup contract, full tests and main build.

- [ ] **Step 5: Record Ralph checkpoint**

Record startup behavior and build output.

## Task 11: Update operational documentation and validation tooling

**Files:**

- Modify: `README.md`
- Modify: `docs/IOS_PAIRING.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/VALIDATION_REPORT.md`
- Create: `tools/verify_mqtt_relay.py`
- Create: `tools/tests/test_verify_mqtt_relay.py`

- [ ] **Step 1: Write failing verifier tests**

The verifier must accept broker events, require availability/discovery/one notification, verify no second publish for an echo relay ID, and redact content in its report.

- [ ] **Step 2: Confirm RED**

Run verifier tests.

- [ ] **Step 3: Implement verifier and docs**

Document AP credentials, portal, arbitrary broker settings, TLS, Enroll/Replace, reset boundaries, MQTT topics, HA YAML installation and exact live commands. Preserve the original ANCS serial verifier.

- [ ] **Step 4: Verify GREEN**

Run all Python tests and scan docs for stale “Wi-Fi runtime absent” claims.

- [ ] **Step 5: Record Ralph checkpoint**

Record docs/verifier evidence.

## Task 12: Automated build and device verification

**Files:**

- Update: `.omx/state/ralph-progress.json`
- Update: `docs/VALIDATION_REPORT.md`
- Create runtime artifacts under `artifacts/`

- [ ] **Step 1: Run the full pre-device suite**

```powershell
python -m pytest -q
.\tools\build.ps1
Push-Location test_app
idf.py -B build-tests build
Pop-Location
```

Expected: zero failures and successful firmware images.

- [ ] **Step 2: Run static negative-scope checks**

Prove no REST relay, no Perform Notification Action and no secret serialization.

- [ ] **Step 3: Flash and run Unity on COM9**

Use 115200 flash baud and the physical BOOT/RESET sequence when needed. Capture `ANCS_TEST_RESULT failures=0`.

- [ ] **Step 4: Flash the final firmware**

Preserve default bond NVS. Erase only `provision` for first-boot AP proof.

- [ ] **Step 5: Verify AP and portal**

Use the spare Windows Wi-Fi adapter so the primary connection remains available. Verify automatic AP, captive portal, scan and configuration. Verify iPhone portal manually.

- [ ] **Step 6: Verify MQTT**

Configure the live broker through the portal without logging secrets. Capture availability, state, Discovery and a real notification.

- [ ] **Step 7: Verify BLE Enroll and reconnect**

If a bond exists, verify automatic reconnect. For explicit fresh-enroll proof, use confirmed Replace only when the user has approved deleting the current iPhone bond. Prove no unbonded advertising before Enroll.

- [ ] **Step 8: Verify HA exactly-once and echo drop**

Generate one new iOS app notification, prove one MQTT payload and one `notify.mobile_app_1bobby` result, then prove the `[C6→HA]` reflected ANCS event produces no MQTT publish.

- [ ] **Step 9: Verify offline drop**

Disconnect MQTT, generate one notification, reconnect and prove no delayed payload.

- [ ] **Step 10: Update report with masked evidence**

Record app ID, field presence, relay ID, counts, timestamps and hashes while masking personal content.

## Task 13: Ralph completion gates

- [ ] **Step 1: Prompt-to-artifact audit**

Map every PRD story and test-spec row to a file and fresh command/live result.

- [ ] **Step 2: THOROUGH architect verification**

Request architect review because this changes security, provisioning, BLE, Wi-Fi, MQTT and Home Assistant across more than 20 files. Fix every required issue and rerun verification.

- [ ] **Step 3: Run `oh-my-codex:ai-slop-cleaner`**

Scope standard-mode cleanup to files changed during this Ralph session only.

- [ ] **Step 4: Post-deslop regression**

Rerun full Python tests, main build, Unity build, static checks and the relevant live smoke checks.

- [ ] **Step 5: Complete Ralph state and cleanup**

Set `.omx/state/ralph-progress.json` to complete, confirm no pending checkboxes, then run the cancel workflow to clear active Ralph state.
