# Compact Home Assistant Entities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the many per-field Home Assistant sensors with one readiness binary sensor plus four notification sensors, add uptime and a safe restart button, and translate known iOS app bundle IDs into documented Korean display names.

**Architecture:** Keep the existing notification and retained state topics. Enrich notification JSON with `app_name`, project only three focused notification values, publish all diagnostics as attributes of one connectivity binary sensor, and clear legacy retained Discovery topics with paced tombstones. Route exact non-retained restart commands through the existing application coordinator and delayed restart timer.

**Tech Stack:** ESP-IDF 6.0.2, ESP-MQTT, FreeRTOS, Home Assistant MQTT Discovery, Unity component tests, pytest source contracts, PowerShell build matrix, GitHub Pages.

---

## File Structure

- `components/mqtt_relay/include/mqtt_app_name.h`: small public lookup contract used by payload tests.
- `components/mqtt_relay/mqtt_app_name.c`: exact case-insensitive bundle-ID to Korean display-name table.
- `components/mqtt_relay/CMakeLists.txt`: includes the new lookup translation unit.
- `components/mqtt_relay/mqtt_payload.c`: adds backward-compatible `app_name` to outgoing notification JSON.
- `components/mqtt_relay/include/mqtt_relay.h`: compact Discovery, runtime status, legacy migration, and restart command contracts.
- `components/mqtt_relay/include/mqtt_relay_test.h`: test-only runtime and command simulation hooks.
- `components/mqtt_relay/mqtt_relay.c`: retained state, compact Discovery, legacy tombstones, subscriptions, and command event emission.
- `components/mqtt_relay/test/test_mqtt_payload.c`: executable Unity coverage for lookup, JSON, Discovery, state, migration, and commands.
- `main/app_main.c`: BLE transition sampling, periodic status refresh, and delayed restart ownership.
- `tools/tests/test_mqtt_contract.py`: source-level entity, migration, secret-exclusion, and mapping/document synchronization contracts.
- `tools/tests/test_startup_contract.py`: coordinator-only BLE status and restart handling contracts.
- `tools/tests/test_multi_target_contract.py`: release version, manifests, binaries, and installer hash coverage.
- `CMakeLists.txt`, `tools/build_matrix.ps1`, `tools/build.sh`: v0.3.3 build version.
- `docs/APP_ID_REFERENCE.md`: user-facing table that must remain identical to the firmware lookup table.
- `README.md`, `docs/IOS_PAIRING.md`, `docs/VALIDATION_REPORT.md`: compact entity and runtime verification guidance.
- `docs/manifests/*.json`, `docs/app.js`, `docs/firmware/<target>/*.bin`: v0.3.3 web installer release.

### Task 1: Lock and implement app-name JSON enrichment

**Files:**
- Create: `components/mqtt_relay/include/mqtt_app_name.h`
- Create: `components/mqtt_relay/mqtt_app_name.c`
- Modify: `components/mqtt_relay/CMakeLists.txt`
- Modify: `components/mqtt_relay/mqtt_payload.c`
- Modify: `components/mqtt_relay/test/test_mqtt_payload.c`
- Modify: `tools/tests/test_mqtt_contract.py`
- Test: `tools/tests/test_mqtt_contract.py`

- [ ] **Step 1: Write failing mapping and JSON tests**

Add Unity assertions that cover known, case-insensitive, unknown, and empty IDs:

```c
TEST_CASE("app names use documented mapping and safe fallback", "[mqtt_relay]")
{
    TEST_ASSERT_EQUAL_STRING("메시지", mqtt_app_name_lookup("com.apple.MobileSMS"));
    TEST_ASSERT_EQUAL_STRING("카카오톡", mqtt_app_name_lookup("COM.IWILAB.KAKAOTALK"));
    TEST_ASSERT_EQUAL_STRING("com.example.Unknown",
                             mqtt_app_name_lookup("com.example.Unknown"));
    TEST_ASSERT_EQUAL_STRING("", mqtt_app_name_lookup(""));
    TEST_ASSERT_EQUAL_STRING("", mqtt_app_name_lookup(NULL));
}
```

Extend the notification payload test so `com.iwilab.KakaoTalk` produces both:

```c
TEST_ASSERT_NOT_NULL(strstr(payload, "\"app_id\":\"com.iwilab.KakaoTalk\""));
TEST_ASSERT_NOT_NULL(strstr(payload, "\"app_name\":\"카카오톡\""));
```

Import `re`, then add a Python synchronization test that parses every Markdown
table row and requires the exact C pair:

```python
def test_documented_app_ids_are_the_firmware_mapping_source_of_truth():
    document = (ROOT / "docs" / "APP_ID_REFERENCE.md").read_text(encoding="utf-8")
    source = read("mqtt_app_name.c")
    rows = re.findall(r"^\| `([^`]+)` \| ([^|]+?) \|", document, re.MULTILINE)
    assert len(rows) == 80
    assert len({app_id.lower() for app_id, _ in rows}) == len(rows)
    for app_id, name in rows:
        assert f'{{"{app_id}", "{name.strip()}"}}' in source
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m pytest tools/tests/test_mqtt_contract.py -q
```

Expected: failure because `mqtt_app_name.c`, the lookup symbol, and `app_name`
JSON enrichment do not exist.

- [ ] **Step 3: Add the lookup component**

Declare the lookup:

```c
#pragma once

const char *mqtt_app_name_lookup(const char *app_id);
```

Implement a static table with all 80 exact rows from
`docs/APP_ID_REFERENCE.md`, use `strcasecmp`, and return the original pointer
for an unknown non-empty ID:

```c
typedef struct {
    const char *app_id;
    const char *display_name;
} mqtt_app_name_entry_t;

static const mqtt_app_name_entry_t APP_NAMES[] = {
    {"com.apple.MobileSMS", "메시지"},
    {"com.apple.Maps", "지도"},
    {"com.apple.Music", "Apple Music"},
    {"com.iwilab.KakaoTalk", "카카오톡"},
    {"com.nhncorp.NaverSearch", "네이버"},
    {"com.nhncorp.NaverMap", "네이버 지도"},
    {"com.nhncorp.NaverWebtoon", "네이버 웹툰"},
    {"net.daum.maps", "카카오맵"},
    {"com.google.Gmail", "Gmail"},
    {"com.google.GoogleMobile", "Google"},
    {"com.google.Maps", "Google 지도"},
    {"com.google.ios.youtube", "YouTube"},
    {"com.google.ios.youtubemusic", "YouTube Music"},
    {"com.google.chrome.ios", "Chrome"},
    {"net.whatsapp.WhatsApp", "WhatsApp"},
    {"net.whatsapp.WhatsAppSMB", "WhatsApp Business"},
    {"com.facebook.Facebook", "Facebook"},
    {"com.facebook.Messenger", "Messenger"},
    {"com.burbn.instagram", "Instagram"},
    {"ph.telegra.Telegraph", "Telegram"},
    {"com.atebits.Tweetie2", "X"},
    {"com.spotify.client", "Spotify"},
    {"com.netflix.Netflix", "Netflix"},
    {"com.hammerandchisel.discord", "Discord"},
    {"com.microsoft.Office.Outlook", "Outlook"},
    {"com.microsoft.skype.teams", "Microsoft Teams"},
    {"com.microsoft.azureauthenticator", "Microsoft Authenticator"},
    {"com.tinyspeck.chatlyio", "Slack"},
    {"com.slack.slackintune", "Slack for Intune"},
    {"notion.id", "Notion"},
    {"com.cron.calendar", "Notion 캘린더"},
    {"com.openai.chat", "ChatGPT"},
    {"com.tving.iphone001", "TVING"},
    {"com.jawebs.baedal", "배달의민족"},
    {"com.coupang.Coupang", "쿠팡"},
    {"com.coupang.coupang-eats", "쿠팡이츠"},
    {"com.vivarepublica.cash", "토스"},
    {"com.kakaobank.channel", "카카오뱅크"},
    {"com.kakaopay.payapp.store", "카카오페이"},
    {"com.kbstar.kbbank", "KB스타뱅킹"},
    {"com.kbcard.cxh.appcard", "KB Pay"},
    {"com.shinhan.sbank", "신한 슈퍼SOL"},
    {"com.shinhan.sbank2015", "구 신한 SOL뱅크"},
    {"com.wooribank.smart.npib", "우리WON뱅킹"},
    {"com.wooricard.wcard", "우리WON카드"},
    {"com.hanabank.oqf", "하나원큐"},
    {"com.kebhana.hanapush", "구 하나원큐"},
    {"com.samsungCard.samsungCard", "모니모"},
    {"com.shinhancard.MobilePay", "신한 SOL페이"},
    {"com.hyundaicard.hcappcard", "현대카드"},
    {"com.nonghyup.card.NHAllonePay", "NH pay"},
    {"com.nonghyup.newsmartbanking", "NH스마트뱅킹"},
    {"com.naverfin.payapp", "네이버페이"},
    {"com.nhncorp.NaverShopping", "네이버플러스 스토어"},
    {"com.towneers.www", "당근"},
    {"net.quicket.app", "번개장터"},
    {"net.bucketplacet.ohouse", "오늘의집"},
    {"jp.naver.line", "LINE"},
    {"com.ss.iphone.ugc.Ame", "TikTok"},
    {"com.ss.iphone.ugc.tiktok.lite", "TikTok Lite"},
    {"us.zoom.videomeetings", "Zoom Workplace"},
    {"us.zoom.videomeetings4intune", "Zoom Workplace for Intune"},
    {"com.google.Drive", "Google 드라이브"},
    {"com.google.photos", "Google 포토"},
    {"com.google.calendar", "Google 캘린더"},
    {"com.microsoft.skydrive", "OneDrive"},
    {"com.microsoft.msedge", "Microsoft Edge"},
    {"com.getdropbox.Dropbox", "Dropbox"},
    {"com.reddit.Reddit", "Reddit"},
    {"com.linkedin.LinkedIn", "LinkedIn"},
    {"org.whispersystems.signal", "Signal"},
    {"com.tencent.xin", "WeChat"},
    {"com.alipay.iphoneclient", "Alipay"},
    {"com.ubercab.UberClient", "Uber"},
    {"com.ubercab.UberEats", "Uber Eats"},
    {"com.airbnb.app", "Airbnb"},
    {"kr.co.withweb.aboutyeogi", "여기어때"},
    {"kr.co.rememberapp", "리멤버"},
    {"com.github.stormbreaker.prod", "GitHub"},
    {"com.anthropic.claude", "Claude"},
};

const char *mqtt_app_name_lookup(const char *app_id)
{
    if (app_id == NULL || app_id[0] == '\0') {
        return "";
    }
    for (size_t index = 0; index < sizeof(APP_NAMES) / sizeof(APP_NAMES[0]); ++index) {
        if (strcasecmp(app_id, APP_NAMES[index].app_id) == 0) {
            return APP_NAMES[index].display_name;
        }
    }
    return app_id;
}
```

- [ ] **Step 4: Enrich the outgoing notification JSON**

Include `mqtt_app_name.h`, include the display-name length in the bounded
capacity calculation, and insert `app_name` before relay metadata:

```c
const char *app_name = mqtt_app_name_lookup(notification->app_id);
const size_t text_length = strlen(notification->app_id) + strlen(app_name) +
                           strlen(notification->title) +
                           strlen(notification->subtitle) +
                           strlen(notification->message) +
                           strlen(notification->message_size_raw) +
                           strlen(notification->date_raw) +
                           strlen(device_name) + strlen(relay_id);

const int written = snprintf(payload + length - 1U,
                             capacity - length + 1U,
                             ",\"app_name\":\"%s\",\"relay_id\":\"%s\","
                             "\"source\":\"" ANCS_SOURCE_ID
                             "\",\"published_at_ms\":%" PRIu64 "}",
                             app_name,
                             relay_id,
                             uptime_ms);
```

Add `mqtt_app_name.c` to the component `SRCS` list.

- [ ] **Step 5: Run focused tests and make them GREEN**

Run:

```powershell
python -m pytest tools/tests/test_mqtt_contract.py -q
cmd /d /s /c "call C:\Users\bobby\Documents\Codex\2026-07-29\new-chat-2\work\sdk\esp-idf-6.0.2\export.bat && idf.py -C test_app -B build-tests build"
```

Expected: pytest passes and the Unity test application compiles and links.

- [ ] **Step 6: Commit the mapping and JSON enrichment**

```powershell
git add components/mqtt_relay docs/APP_ID_REFERENCE.md tools/tests/test_mqtt_contract.py
git commit -m "Make ANCS app identity readable without losing bundle IDs" -m "Constraint: Unknown app IDs must remain visible and the reference document must match firmware`nRejected: A large Home Assistant Jinja lookup | it would inflate every retained Discovery payload`nConfidence: high`nScope-risk: moderate`nDirective: Change the C mapping and APP_ID_REFERENCE.md together`nTested: Mapping contract and ESP-IDF Unity application build`nNot-tested: Live third-party notification names are checked after flash"
```

### Task 2: Replace per-field Discovery with compact entities and tombstones

**Files:**
- Modify: `components/mqtt_relay/include/mqtt_relay.h`
- Modify: `components/mqtt_relay/mqtt_relay.c`
- Modify: `components/mqtt_relay/test/test_mqtt_payload.c`
- Modify: `tools/tests/test_mqtt_contract.py`
- Modify: `tools/tests/test_multi_target_contract.py`
- Test: `tools/tests/test_mqtt_contract.py`

- [ ] **Step 1: Replace old entity expectations with failing compact contracts**

Require only these sensor projections:

```python
expected = {
    "last_notification": "최근 알림",
    "notification_title": "알림 제목",
    "notification_message": "알림 내용",
    "app_name": "앱 이름",
}
```

Require a binary-sensor topic
`homeassistant/binary_sensor/<client_id>/device_status/config`, the exact Korean
names, 255-character title/message templates, the aggregate JSON attributes,
and no non-empty legacy field or Wi-Fi Discovery loop. Require 33 legacy
notification keys and 3 legacy Wi-Fi keys to remain available only for retained
empty migration publications.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
python -m pytest tools/tests/test_mqtt_contract.py tools/tests/test_multi_target_contract.py -q
```

Expected: failure because the current source still creates every field and
three Wi-Fi entities and has no readiness binary sensor.

- [ ] **Step 3: Define compact Discovery builders**

Replace public per-field payload builders with:

```c
size_t mqtt_relay_focused_sensor_count(void);
const char *mqtt_relay_focused_sensor_key(size_t index);
esp_err_t mqtt_relay_build_focused_discovery_topic(
    const provision_config_t *config, size_t index, char *out, size_t out_size);
esp_err_t mqtt_relay_build_focused_discovery_payload(
    const provision_config_t *config,
    const mqtt_relay_device_info_t *device_info,
    const char *notification_topic,
    const char *availability_topic,
    size_t index,
    char *out,
    size_t out_size);
esp_err_t mqtt_relay_build_status_discovery_topic(
    const provision_config_t *config, char *out, size_t out_size);
esp_err_t mqtt_relay_build_status_discovery_payload(
    const provision_config_t *config,
    const mqtt_relay_device_info_t *device_info,
    const char *state_topic,
    const char *availability_topic,
    char *out,
    size_t out_size);
```

Use exactly three focused definitions:

```c
static const mqtt_relay_discovery_field_t FOCUSED_SENSORS[] = {
    {"notification_title", "알림 제목",
     "{{ (value_json.title | default('', true))[:255] }}"},
    {"notification_message", "알림 내용",
     "{{ (value_json.message | default('', true))[:255] }}"},
    {"app_name", "앱 이름",
     "{{ (value_json.app_name | default(value_json.app_id, true))[:255] }}"},
};
```

The status payload uses `device_class:"connectivity"`,
`entity_category:"diagnostic"`, the retained state topic for both state and
JSON attributes, and `{{ 'ON' if value_json.ready else 'OFF' }}`.

- [ ] **Step 4: Publish legacy retained tombstones before the new set**

Keep the 33 former field keys and 3 Wi-Fi keys in `LEGACY_*` arrays used only to
build the old config topics. For every topic, call the existing paced retained
Discovery publisher with an empty payload:

```c
for (size_t index = 0; index < legacy_count; ++index) {
    if (mqtt_relay_build_legacy_discovery_topic(
            discovery_config, index, discovery_topic,
            sizeof(discovery_topic)) != ESP_OK ||
        !mqtt_relay_publish_discovery_once(discovery_topic, "")) {
        goto cleanup;
    }
}
```

Publish the aggregate sensor, three focused sensors, readiness binary sensor,
enroll button, and later restart button only after every tombstone succeeds.
Set `discovery_attempted_this_boot = true` only after the entire migration and
new Discovery pass succeeds; leave it false on failure so reconnect retries.

- [ ] **Step 5: Run focused contracts and component build**

```powershell
python -m pytest tools/tests/test_mqtt_contract.py tools/tests/test_multi_target_contract.py -q
cmd /d /s /c "call C:\Users\bobby\Documents\Codex\2026-07-29\new-chat-2\work\sdk\esp-idf-6.0.2\export.bat && idf.py -C test_app -B build-tests build"
```

Expected: compact source contracts pass and the Unity test application builds.

- [ ] **Step 6: Commit the compact Discovery migration**

```powershell
git add components/mqtt_relay tools/tests/test_mqtt_contract.py tools/tests/test_multi_target_contract.py
git commit -m "Keep Home Assistant useful without flooding it with entities" -m "Constraint: Old retained Discovery topics must be actively removed and weak Wi-Fi pacing must remain`nRejected: Hiding old entities only in the UI | retained broker state would recreate them`nConfidence: high`nScope-risk: moderate`nDirective: Keep legacy topic keys until every deployed device has migrated`nTested: Compact Discovery contracts and ESP-IDF Unity application build`nNot-tested: Broker tombstones and HA registry are verified on the live C6"
```

### Task 3: Add readiness, BLE status, and uptime attributes

**Files:**
- Modify: `components/mqtt_relay/include/mqtt_relay.h`
- Modify: `components/mqtt_relay/mqtt_relay.c`
- Modify: `components/mqtt_relay/test/test_mqtt_payload.c`
- Modify: `main/app_main.c`
- Modify: `tools/tests/test_mqtt_contract.py`
- Modify: `tools/tests/test_startup_contract.py`
- Test: `tools/tests/test_startup_contract.py`

- [ ] **Step 1: Add failing state-payload and coordinator contracts**

Define a runtime snapshot test with Wi-Fi, MQTT, BLE, bond, and uptime values.
Assert this JSON and no secret fields:

```c
TEST_ASSERT_NOT_NULL(strstr(state, "\"ready\":true"));
TEST_ASSERT_NOT_NULL(strstr(state, "\"wifi_connected\":true"));
TEST_ASSERT_NOT_NULL(strstr(state, "\"mqtt_connected\":true"));
TEST_ASSERT_NOT_NULL(strstr(state, "\"ble_connected\":true"));
TEST_ASSERT_NOT_NULL(strstr(state, "\"ble_bonded\":true"));
TEST_ASSERT_NOT_NULL(strstr(state, "\"uptime_seconds\":3723"));
TEST_ASSERT_NOT_NULL(strstr(state, "\"uptime\":\"1시간 2분 3초\""));
TEST_ASSERT_NOT_NULL(strstr(state, "\"model\":\"ESP32-C6\""));
```

Add Python assertions that the existing one-second bond timer samples both
`ancs_client_has_bond()` and `ancs_client_is_connected()`, detects transitions,
and calls a relay status update from the coordinator rather than from a BLE
callback. Require the 60-second Wi-Fi timer path to advance the same retained
state.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
python -m pytest tools/tests/test_mqtt_contract.py tools/tests/test_startup_contract.py -q
```

Expected: failure because state contains no BLE, readiness, uptime, or device
metadata and the coordinator tracks only bond presence.

- [ ] **Step 3: Introduce a bounded runtime status snapshot**

Add:

```c
typedef struct {
    mqtt_relay_wifi_status_t wifi;
    bool mqtt_connected;
    bool ble_connected;
    bool ble_bonded;
    uint64_t uptime_seconds;
} mqtt_relay_runtime_status_t;

esp_err_t mqtt_relay_build_state_payload(
    const mqtt_relay_counters_t *counters,
    const mqtt_relay_runtime_status_t *runtime,
    const mqtt_relay_device_info_t *device_info,
    char *out,
    size_t out_size);
esp_err_t mqtt_relay_update_ble_status(bool connected, bool bonded);
esp_err_t mqtt_relay_refresh_state(void);
```

Change the pure state builder to accept counters, runtime status, and device
information. Compute `ready` as the conjunction of Wi-Fi, MQTT, and BLE. Format
uptime as Korean hours/minutes/seconds, including whole days when nonzero, with
bounded `snprintf` and `PRIu64`.

- [ ] **Step 4: Centralize retained state publication**

Add an internal helper that snapshots counters, Wi-Fi, MQTT, BLE, device info,
and `esp_timer_get_time() / 1000000ULL`, builds the JSON, and publishes once to
the retained state topic. Make initial retained publication,
`mqtt_relay_update_wifi_status`, `mqtt_relay_update_ble_status`, and
`mqtt_relay_refresh_state` use that helper without holding the data mutex across
MQTT publication.

- [ ] **Step 5: Detect BLE transitions in the coordinator**

Extend `app_coordinator_state_t` with cached BLE-connected and BLE-bonded flags.
In `handle_bond_poll`, sample both ANCS values, preserve the provisioning bond
event behavior, and call `mqtt_relay_update_ble_status` only when either flag
changes. Immediately after relay initialization, seed the relay with the
current ANCS snapshot. Let the existing 60-second Wi-Fi refresh update uptime;
if Wi-Fi snapshot acquisition fails, call `mqtt_relay_refresh_state()` so
uptime still advances while MQTT remains online.

- [ ] **Step 6: Run focused tests and component build**

```powershell
python -m pytest tools/tests/test_mqtt_contract.py tools/tests/test_startup_contract.py -q
cmd /d /s /c "call C:\Users\bobby\Documents\Codex\2026-07-29\new-chat-2\work\sdk\esp-idf-6.0.2\export.bat && idf.py -C test_app -B build-tests build"
```

Expected: state and startup contracts pass and the test firmware builds.

- [ ] **Step 7: Commit readiness and uptime**

```powershell
git add components/mqtt_relay main/app_main.c tools/tests/test_mqtt_contract.py tools/tests/test_startup_contract.py
git commit -m "Expose whether the bridge is truly ready" -m "Constraint: Readiness requires Wi-Fi, MQTT, and the bonded iPhone link while network loss remains unavailable`nConfidence: high`nScope-risk: moderate`nDirective: Keep credentials out of retained diagnostics`nTested: State, startup, and ESP-IDF Unity build contracts`nNot-tested: Physical BLE transition and live uptime are verified after flash"
```

### Task 4: Add exact non-retained restart control

**Files:**
- Modify: `components/mqtt_relay/include/mqtt_relay.h`
- Modify: `components/mqtt_relay/include/mqtt_relay_test.h`
- Modify: `components/mqtt_relay/mqtt_relay.c`
- Modify: `components/mqtt_relay/test/test_mqtt_payload.c`
- Modify: `main/app_main.c`
- Modify: `tools/tests/test_mqtt_contract.py`
- Modify: `tools/tests/test_startup_contract.py`
- Test: `tools/tests/test_mqtt_contract.py`

- [ ] **Step 1: Add failing restart topic, payload, and coordinator tests**

Require:

```c
TEST_ASSERT_EQUAL_STRING("ios-ancs/2b20/command/restart", command_topic);
TEST_ASSERT_EQUAL_STRING(
    "homeassistant/button/ios_ancs_c6_ab12/restart/config",
    discovery_topic);
TEST_ASSERT_NOT_NULL(strstr(discovery, "\"name\":\"장치 재시작\""));
TEST_ASSERT_NOT_NULL(strstr(discovery, "\"payload_press\":\"RESTART\""));
TEST_ASSERT_NOT_NULL(strstr(discovery, "\"retain\":false"));
```

Validate exact command acceptance and reject retained, partial, fragmented,
lowercase, wrong-topic, and trailing-byte inputs. In startup contracts, require
the restart event to reset `s_restart_timer` only inside `handle_mqtt_event` and
forbid `esp_restart()` from the MQTT callback path.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
python -m pytest tools/tests/test_mqtt_contract.py tools/tests/test_startup_contract.py -q
```

Expected: failure because restart topics, event, subscription, and Discovery do
not exist.

- [ ] **Step 3: Add restart builders and exact validator**

Add `MQTT_RELAY_EVENT_RESTART_REQUEST`, topic fields, and pure builders matching
the existing enrollment pattern. Implement a shared exact validator:

```c
static bool mqtt_relay_is_exact_command(
    const char *expected_topic,
    const char *expected_payload,
    const char *topic,
    size_t topic_len,
    const char *payload,
    size_t payload_len,
    size_t total_payload_len,
    size_t current_data_offset,
    bool retained);
```

Keep `mqtt_relay_is_enroll_command` as a wrapper for `ENROLL` and add
`mqtt_relay_is_restart_command` for `RESTART`.

- [ ] **Step 4: Subscribe and emit without restarting in the callback**

On MQTT connect, subscribe to both command topics at QoS 1 before marking the
control path ready. On `MQTT_EVENT_DATA`, copy both expected topics under lock,
validate once, and emit either enrollment or restart. Do not call
`esp_restart()`, reset a timer, or perform BLE work in `mqtt_relay.c`.

- [ ] **Step 5: Schedule the existing delayed restart from the coordinator**

Handle the new event before generic failure handling:

```c
if (event == MQTT_RELAY_EVENT_RESTART_REQUEST) {
    if (s_restart_timer == NULL ||
        xTimerReset(s_restart_timer, 0) != pdPASS) {
        ESP_LOGW(TAG, "MQTT restart request could not be scheduled");
    }
    return;
}
```

The existing 750 ms timer remains the only call site that invokes
`esp_restart()`.

- [ ] **Step 6: Run focused tests and component build**

```powershell
python -m pytest tools/tests/test_mqtt_contract.py tools/tests/test_startup_contract.py -q
cmd /d /s /c "call C:\Users\bobby\Documents\Codex\2026-07-29\new-chat-2\work\sdk\esp-idf-6.0.2\export.bat && idf.py -C test_app -B build-tests build"
```

Expected: restart contracts pass and the test application builds.

- [ ] **Step 7: Commit restart control**

```powershell
git add components/mqtt_relay main/app_main.c tools/tests/test_mqtt_contract.py tools/tests/test_startup_contract.py
git commit -m "Let Home Assistant restart the bridge without replay risk" -m "Constraint: Restart commands must be exact, complete, non-retained, and delayed outside the MQTT callback`nConfidence: high`nScope-risk: moderate`nDirective: Never accept retained control commands`nTested: Restart validation, coordinator contracts, and ESP-IDF Unity build`nNot-tested: Exactly one physical reboot is verified after flash"
```

### Task 5: Run regressions and publish v0.3.3 for every target

**Files:**
- Modify: `CMakeLists.txt`
- Modify: `tools/build_matrix.ps1`
- Modify: `tools/build.sh`
- Modify: `tools/tests/test_multi_target_contract.py`
- Modify: `docs/manifests/ios-ancs.json`
- Modify: `docs/manifests/esp32-c6.json`
- Modify: `docs/app.js`
- Modify: `README.md`
- Modify: `docs/IOS_PAIRING.md`
- Modify: `docs/VALIDATION_REPORT.md`
- Create: `docs/firmware/<target>/ios-ancs-<target>-v0.3.3.factory.bin`

- [ ] **Step 1: Change release assertions to v0.3.3 and verify RED**

Require project version, build-script defaults, both manifests, seven binary
paths, installer labels, sizes, and SHA-256 prefixes to use `0.3.3`.

```powershell
python -m pytest tools/tests/test_multi_target_contract.py -q
```

Expected: failure while source and artifacts remain v0.3.2.

- [ ] **Step 2: Run the complete host suite before release changes**

```powershell
python -m pytest -q
```

Expected: every functional test passes; deliberate v0.3.3 release assertions
remain the only failures until metadata is advanced.

- [ ] **Step 3: Advance version and user guidance**

Set `PROJECT_VER`, matrix/script defaults, manifest version and paths to 0.3.3.
Document the compact entity set, binary readiness semantics, 60-second uptime,
restart button, full JSON preservation, 255-character focused states, app-name
fallback, and the `APP_ID_REFERENCE.md` maintenance rule. Do not claim hardware
or Home Assistant proof before it is observed.

- [ ] **Step 4: Build all seven targets and merged images**

```powershell
.\tools\build_matrix.ps1 -Version 0.3.3
```

Expected: `artifacts/build-matrix.json` records seven `success: true` entries and
every output is a non-empty 4 MB merged factory image.

- [ ] **Step 5: Synchronize manifests and installer hashes**

Copy the exact size and complete SHA-256 for each output into validation
evidence, the first 12 uppercase hex characters into `docs/app.js`, and the
v0.3.3 path into both manifests. Do not reuse v0.3.2 hashes.

- [ ] **Step 6: Run full verification**

```powershell
python -m pytest -q
git diff --check
git status --short
```

Expected: all tests pass, whitespace check is empty, and only intentional
source, docs, manifest, and v0.3.3 artifact changes remain.

- [ ] **Step 7: Commit the release artifacts**

```powershell
git add CMakeLists.txt tools docs README.md
git commit -m "Ship the compact Home Assistant model to every installer target" -m "Constraint: Shared firmware changes require fresh merged images and hashes for all supported ESP32 targets`nConfidence: high`nScope-risk: broad`nDirective: Never carry a binary hash across release versions`nTested: Full pytest suite and seven-target ESP-IDF build matrix`nNot-tested: Physical validation is limited to the identified connected C6"
```

### Task 6: Validate the C6, integrate, push, and verify Pages

**Files:**
- Modify: `docs/VALIDATION_REPORT.md` only for fresh observed evidence.

- [ ] **Step 1: Identify hardware immediately before flash**

```powershell
Get-CimInstance Win32_SerialPort | Select-Object DeviceID,Name,PNPDeviceID
cmd /d /s /c "call C:\Users\bobby\Documents\Codex\2026-07-29\new-chat-2\work\sdk\esp-idf-6.0.2\export.bat && python -m esptool --port COM9 chip_id"
```

Expected before flashing COM9: esptool reports ESP32-C6. If COM9 is absent or a
different chip is reported, do not flash that port; release the web installer
and report physical verification as pending.

- [ ] **Step 2: Flash without transferring proof from another board**

For an identified C6 on COM9:

```powershell
cmd /d /s /c "call C:\Users\bobby\Documents\Codex\2026-07-29\new-chat-2\work\sdk\esp-idf-6.0.2\export.bat && python -m esptool --chip esp32c6 --port COM9 write-flash 0x0 docs\firmware\esp32c6\ios-ancs-esp32c6-v0.3.3.factory.bin"
```

Capture UART boot output after reset. Preserve provisioning only if the chosen
flash path does not erase NVS; a factory-image flash at offset 0 can replace the
partition table and must be treated as a fresh provisioning install.

- [ ] **Step 3: Verify broker and Home Assistant behavior**

Observe fresh retained payloads and prove:

- old field and Wi-Fi Discovery topics contain zero-length tombstones;
- only `장치 상태`, `최근 알림`, `알림 제목`, `알림 내용`, `앱 이름`,
  `iPhone 등록 시작`, and `장치 재시작` are discovered for the device;
- `uptime_seconds` increases after at least 60 seconds;
- nearby bonded iPhone produces `ble_connected:true` and binary `ON` only when
  Wi-Fi and MQTT are also true;
- a real BLE disconnect produces binary `OFF` while MQTT stays online;
- one non-retained Home Assistant restart press produces exactly one boot;
- a retained `RESTART` publish does not reboot;
- a real notification updates all four notification sensors and preserves the
  complete JSON plus `app_id` and `app_name`.

- [ ] **Step 4: Record only observed evidence**

Add timestamp, chip identity, firmware SHA-256, broker topics, HA entity IDs,
uptime samples, BLE transition, restart count, and notification sample to
`docs/VALIDATION_REPORT.md`. Mark every unperformed check explicitly.

- [ ] **Step 5: Integrate the isolated branch**

Use the `finishing-a-development-branch` skill, merge the verified feature
branch into `main` without discarding unrelated work, and rerun:

```powershell
python -m pytest -q
git diff --check
```

Expected: all tests pass and the main worktree is clean after the integration
commit.

- [ ] **Step 6: Push and verify GitHub Pages**

```powershell
git push origin main
git ls-remote origin refs/heads/main
```

Wait for GitHub Pages deployment, open the public installer manifest and each
v0.3.3 binary URL, and compare downloaded SHA-256 values with the committed
matrix. Do not claim public release until the remote SHA, Pages manifest, and
served binaries match.
