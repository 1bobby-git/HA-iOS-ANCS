# Validation Report

Validation date: 2026-07-31 (Asia/Seoul)

## Home Assistant field-sensor correction v0.2.1

- MQTT Discovery now publishes one retained aggregate sensor config and 33
  retained individual field-sensor configs for every configured device.
- Individual configs share `<base>/notification` as the state topic and
  extract their value with `value_template`.
- The four members of `truncated` are also individual sensors.
- The `app_id`, `title`, `subtitle`, and `message` sensor states are clipped to
  255 characters; the complete JSON remains available on the aggregate sensor
  through `json_attributes_topic`.
- Host contract: `python -m pytest tools/tests -q` reports `93 passed`.
- ESP-IDF Unity test firmware compiles successfully with the new field
  Discovery cases.
- Home Assistant live MQTT Discovery registration was exercised through the
  configured MQTT integration for device `ios_ancs_c6_2b20`. The device now
  reports exactly 34 entities: one aggregate `last_notification` entity and
  all 33 field entities. This proves Home Assistant accepted every retained
  Discovery config; it does not prove that the disconnected C6 is already
  running v0.2.1.
- ESP-IDF v6.0.2 completed build, link, partition checks, and merged-image
  generation for all seven public targets:

| Target | Merged bytes | SHA-256 | Validation level |
| --- | ---: | --- | --- |
| `esp32` | 1,414,080 | `949aa5982ab9b01d893867750a48896de0e6f9744cec7c70899e49cf9cc2a68d` | v0.2.1 build verified |
| `esp32c2` | 1,432,336 | `4e035429738a0769cfe83548c0eacfb9cca0465170a29b078df9d7f31e05a1cb` | v0.2.1 build verified |
| `esp32c3` | 1,511,936 | `7cb8af801d0e0100241eab29d378a95cc280f512a49de95f5ad7fd0124ce5c19` | v0.2.1 build verified |
| `esp32c5` | 1,766,240 | `f0507c429a9be485bff484117bf8ce2a93a66afe17e9356f61f16a12e8f0f4b6` | v0.2.1 build verified |
| `esp32c6` | 1,766,448 | `92027eba5d2be465db56115287b6912b9f3e12a355668f5e5ecf7115d46dab6b` | v0.2.1 build verified; device flash pending |
| `esp32c61` | 1,709,408 | `eb2d3931763fb83b310ddb2048bfd5779bed6771001ef9215df93a6498402448` | v0.2.1 build verified |
| `esp32s3` | 1,395,808 | `2bac7fb3a0c035b0c9e452703a65548a421102537fc81e2af83c6744ab736ef0` | v0.2.1 build verified |

- Current physical reflash remains pending because the known ESP32-C6 CH343
  port `COM9` is not present. The active `COM7` was identified read-only as an
  ESP32-D0WD-V3 and was not flashed.

## Multi-target v0.2.0 build evidence (2026-07-31)

`tools/build_matrix.ps1` completed one final sequential ESP-IDF v6.0.2 build, link,
partition-size check, and esptool merged-image generation pass for every public
installer target. All images use the 4 MB minimum flash layout.

| Target | Merged bytes | SHA-256 | Validation level |
| --- | ---: | --- | --- |
| `esp32` | 1,411,632 | `70972a7ea25d258de99777df19e28fcbc60dfcd6e6a07c1ad2f6118e97096622` | Build verified |
| `esp32c2` | 1,429,760 | `1f935bfdad64f3ad2e81f3ec24563a5d1855c7da534a69a4bd6f13d183f060e0` | Build verified |
| `esp32c3` | 1,509,344 | `9b4054ea76299a7c1b8bf882805a8b9d107d0f6036464129de4a5d74646b28da` | Build verified |
| `esp32c5` | 1,763,648 | `9eb99f11a3bb6ae0033662b5130cdf66d3e3ccc77f1fa0db74fd03be8d5b95f1` | Build verified |
| `esp32c6` | 1,763,856 | `3cbd015af10ce2d9f43ca2689fe43c6df57d086b2c23725e58790408b8898986` | v0.2.0 build, flash, and boot verified on COM9 |
| `esp32c61` | 1,706,816 | `90bcd4d9ae65a8f7f0be354509f98d806296af965cc8db6a99a6602ecbe3c0b6` | Build verified |
| `esp32s3` | 1,393,312 | `1d0a5bf96c4404d8c0a3402f973791f337dbdf982ede11080be0b99cdaea63f9` | Build verified |

The final matrix report is `artifacts/build-matrix.json`. Only C6 has
physical-device evidence. The other targets must not be described as hardware
verified.

### Current release C6 hardware smoke (2026-07-31)

- `python -m esptool --port COM9 chip-id` detected an ESP32-C6 and base MAC
  `40:4C:CA:57:2B:20`.
- `tools/flash.ps1 -Target esp32c6 -Port COM9` wrote the v0.2.0 bootloader,
  partition table, and application and verified every written hash.
- The device booted ESP-IDF v6.0.2 from the factory partition with the 4 MB
  image layout.
- Existing provisioning and BLE bond data survived the normal flash. Serial
  runtime showed Wi-Fi connected to the stored SSID and obtained
  `10.140.40.33`, BLE bond count `1`, state `advertising`, and device name
  `IOS-ANCS-C6-2B20`.
- The Windows host was on a different routed subnet, so the current pass did
  not claim a live MQTT broker connection, Home Assistant Discovery receipt,
  iPhone `ancs_ready`, or a new end-to-end notification event.

This report tracks evidence for the standalone ESP32-C6 ANCS MQTT relay. Host contracts, production/test firmware builds, COM9 flash verification, setup AP portal recovery, existing-bond BLE portal behavior, and the duplicate-cache-after-MQTT-queue-acceptance fix have fresh evidence. Live iPhone reconnect, MQTT, and Home Assistant event proof remain pending.

## Scope

Target behavior:

- Automatic protected setup AP when provisioning config is absent or invalid.
- Arbitrary Wi-Fi and MQTT settings through `http://192.168.4.1`.
- MQTT TLS with required CA validation.
- Explicit BLE Enroll and confirmed Replace enrollment.
- MQTT notification relay with no REST path and no Perform Notification Action path.
- Home Assistant exactly-once mobile notification through MQTT Discovery.
- Drop every Home Assistant notification with `app_id=io.robbie.HomeAssistant`, regardless of title.
- Offline-window drop with no delayed replay after reconnect.

## Known Device Parameters

| Item | Value |
| --- | --- |
| Board port | `COM9` |
| USB bridge | `USB-Enhanced-SERIAL CH343`, VID:PID `1A86:55D3` |
| Chip | ESP32-C6 |
| Known base MAC | `40:4C:CA:57:2B:20` |
| Setup suffix | `572B20` |
| Setup AP | `IOS-ANCS-SETUP-572B20` |
| Setup AP password | Redacted; derived locally from the setup suffix |
| Setup portal | `http://192.168.4.1` |
| Pairing PIN | `123456` |

Other boards derive the setup suffix from the last three MAC bytes.

## Automated Evidence

| Check | Status | Evidence |
| --- | --- | --- |
| MQTT relay verifier contract | PASS | Included in final full suite and static subset; artifacts `artifacts/task5-final/pytest-task5-final.log`, `artifacts/task5-final/static-contract-task5-final.log` |
| Final Python test suite | PASS | `python -m pytest tools/tests -q`: `73 passed in 0.86s`; artifact `artifacts/task5-final/pytest-task5-final.log` |
| Main firmware build/hash | PASS | ESP-IDF v6.0.2 incremental `idf.py build`; `0x19d980`, 19% free; SHA-256 `20A66F5A609A85FA5B1ECEC6D62C9C79EA8779104E984E851BB4B2991F4C0515`; artifacts `artifacts/task5-final/production-hash-task5-final.log`, `artifacts/task5-final/production-hash-task5-final-after-tests.log` |
| Unity test app build/flash | PASS | `ios_ancs_capture_c6_tests.bin` size `0x3b620`, 77% free; esptool hash verification for bootloader, partition table, and test app; artifact `artifacts/task5-final/unity-flash-task5-final.log` |
| Unity device run on COM9 | PASS | Artifact `artifacts/task5-final/unity-task5-final.log`: `67 Tests 0 Failures 0 Ignored`; `ANCS_TEST_RESULT failures=0` |
| Production flash on COM9 | PASS | Artifact `artifacts/task5-final/production-flash-task5-final.log`: esptool wrote production firmware and verified hashes for bootloader, partition table, and `ios_ancs_capture_c6.bin`; production firmware was left on COM9 |
| Production boot/runtime serial | PARTIAL | Artifact `artifacts/task5-final/production-task5-final.log`: booted `ios_ancs_capture_c6`; compile time `Jul 30 2026 14:21:01`; STA attempted `SPARKPLUS14_5F`; setup AP started `IOS-ANCS-SETUP-572B20` at `192.168.4.1`; BLE loaded existing bond count `1`; state JSON showed `bonded=true`, `state=advertising`; STA disconnects observed including reason `34`, RSSI `-81` |
| DAISO setup AP path | PASS | Artifact `artifacts/task5-final/windows-wlan-task5-final.txt`: DAISO adapter `Realtek RTL8192EU Wireless LAN 802.11n USB 2.0 Network Adapter`, GUID `{FEB7E51C-7AB8-4993-B725-E4E8058764FD}`, IP `192.168.4.2/24`, connected to `IOS-ANCS-SETUP-572B20`; AX1800 was read-only inspected and stayed connected to `SPARKPLUS14_5F` |
| Portal root/status/scan | PASS | Artifact `artifacts/task5-final/http-task5-final.json`: `root_gets` are `200/9927` x3; `statuses_before` all show `ap_started=true`, `sta_started=false`, `sta_connecting=false`, `sta_has_ip=false`, `ble_bonded=true`, `mqtt_connected=false`, reason `34`, RSSI `-81`; `scans` counts are `20`, `20`, `20`; `scan_post_contract.status_code=405` |
| Save/connect with preserved secrets | PASS | Artifact `artifacts/task5-final/http-task5-final.json`: `save_connect.response={"ok":true,"saved":true,"reconnect":true}`; raw submitted payload intentionally omitted; status polls show reconnect in progress, one timeout during handoff, then automatic AP return with final polls `ap_started=true`, `sta_started=false`, `sta_connecting=false`, `sta_has_ip=false`, reason `4`, RSSI `-81`; no plaintext Wi-Fi or MQTT secrets were logged |
| BLE enroll with existing bond | PARTIAL | Artifact `artifacts/task5-final/http-task5-final.json`: `ble_enroll.status_code=200`, body `{"ok":true}`; `status_after_ble_enroll.system.ble_bonded=true`, `enroll_window_open=false`, `replace_pending=false`; no bond erase or replace was performed |
| Static REST/action negative checks | PASS | Artifact `artifacts/task5-final/static-contract-task5-final.log`: contract subset `39 passed`; source scan over `main`, `components`, and `homeassistant` found no REST client, REST command, webhook, or Perform Notification Action path; route table lists only `/api/status`, `/api/wifi/scan`, `/api/config`, `/api/mqtt/test`, `/api/ble/enroll`, `/api/ble/replace`, `/api/restart`, and `/api/reset` |
| Home Assistant automation install | PARTIAL | Prior retained readback only, not refreshed in Task 5: `artifacts/live-ha-automation.json` observed `2026-07-29T18:52:16+09:00`, config id `ios_ancs_c6_relay_to_1bobby`, entity `automation.relay_ios_ancs_c6_notifications_to_1bobby`, state `on`, `physical_mobile_receipt_proven=false` |

## Task 5 Final After-Review Evidence

Fresh revalidation artifacts are under `artifacts/task5-final-after-review/`.

| Check | Status | Evidence |
| --- | --- | --- |
| Host Python test suite | PASS | `pytest-after-review.log`: `76 passed in 1.41s` |
| Production build/hash | PASS | `production-build-after-review.log`: `ios_ancs_capture_c6.bin` size `0x19e230`, 19% free; `production-hash-after-review.log`: SHA-256 `7CAE24FC256EE795366681FEED1AAE3986C2A04EBE7AFEEED9B1438F102F816A` |
| Unity test app build | PASS | Deep artifact build failed at `esp_driver_usb_serial_jtag` dependency-file creation, consistent with Windows path length; retry in short `test_app\ba` build dir succeeded. Evidence: `unity-build-after-review.log`, `unity-build-after-review-shortdir.log`, `unity-hash-after-review.log` SHA-256 `62DD716C63F9FF956BEA344007C14DB7459A516381AA829AAF876198A9FF8A80`, size `0x3b620` |
| Unity flash/run on COM9 | PASS | `unity-flash-after-review.log`: bootloader, partition table, and test app hash verification passed; `unity-serial-after-review.log`: `67 Tests 0 Failures 0 Ignored`, `ANCS_TEST_RESULT failures=0` |
| Production reflash on COM9 | PASS | `production-flash-after-review.log`: bootloader, partition table, and production app hash verification passed; production firmware was flashed last and left on COM9 |
| Production boot/runtime serial | PARTIAL | `production-serial-after-review.log` and `.jsonl`: project `ios_ancs_capture_c6`, app compile time `Jul 30 2026 16:32:27`, bootloader compile time `Jul 30 2026 16:33:08`, STA attempted `SPARKPLUS14_5F`, setup AP started `IOS-ANCS-SETUP-572B20` at `192.168.4.1`, existing BLE bond count `1`, state `advertising`, bounded capture did not observe live iPhone `ancs_ready` |
| DAISO/AX WLAN state | PASS | `windows-wlan-before-connect-after-review.txt`: DAISO GUID `{FEB7E51C-7AB8-4993-B725-E4E8058764FD}` connected to `IOS-ANCS-SETUP-572B20` with `192.168.4.2`; AX1800 remained connected to `SPARKPLUS14_5F` before and after |
| Portal AP guard and reads | PASS | `http-after-review.json`: `GET /` HTTP 200 twice, `/api/status` HTTP 200 twice, `/api/wifi/scan` HTTP 200 twice with 20 APs each |
| BLE enroll AP POST guard regression | PASS | `http-after-review.json`: `POST /api/ble/enroll` returned HTTP 200/body `{"ok":true}` through DAISO; following status kept `ble_bonded=true`, `enroll_window_open=false`, `replace_pending=false` |
| Save/connect handoff and AP return | PASS | `http-after-review.json`: redacted current config with empty secret fields returned `{"ok":true,"saved":true,"reconnect":true}`; status then showed `sta_started=true`, `sta_connecting=true`, followed by `ap_started=true`, `sta_started=false`, `sta_connecting=false`, `sta_has_ip=false`, DAISO `192.168.4.2`, and bond retained. `http-save-repeat-after-review.json` repeated the handoff and recorded one expected timeout during transition before recovery. Raw config payloads were intentionally not stored |
| Save/recovery serial correlation | PARTIAL | `save-recovery-serial-after-review-2.log`: repeat save window shows STA connect attempts, disconnect reasons `2`/`4`, DAISO client DHCP `192.168.4.2`, and AP channel recovery activity. The log does not include explicit structured `sta_started=false`; that state is proven by the paired HTTP status artifacts |

## Task 5 Final Dupfix Evidence

Fresh duplicate-cache-fix revalidation artifacts are under `artifacts/task5-final-dupfix/`. This pass did not POST portal config because portal/runtime code was unchanged; production firmware was flashed after the Unity test app and left on COM9.

| Check | Status | Evidence |
| --- | --- | --- |
| Host Python test suite | PASS | `pytest-dupfix.log`: `77 passed in 1.44s` |
| Production build/hash | PASS | `production-build-dupfix.log`: `ios_ancs_capture_c6.bin` size `0x19e280`, 19% free; `production-hash-dupfix.log`: SHA-256 `BC6DBB676DE6A31443472F6FF36258D348302EB34C2DE853FBC4F0739CD9F43B` |
| Unity test app build | PASS | Built with the known short `test_app\ba` build directory to avoid Windows path-length failures. `unity-build-dupfix.log` completed; `unity-hash-dupfix.log`: SHA-256 `F4F4E85AFDE3B48F617A94FC7D33C5A9E8348DA08E50D25631354DED08D32BE2`, size `243952` bytes |
| Unity flash/run on COM9 | PASS | `unity-flash-dupfix.log`: bootloader, partition table, and test app hash verification passed; `unity-serial-dupfix.log`: `68 Tests 0 Failures 0 Ignored`, `ANCS_TEST_RESULT failures=0`, including `queue overflow does not mark rejected relay id duplicate` |
| Production flash last on COM9 | PASS | `production-flash-dupfix.log`: bootloader, partition table, and production app hash verification passed after the Unity run; production firmware was flashed last and left on COM9 |
| Production boot/runtime serial | PARTIAL | `production-serial-dupfix.log` and `.jsonl`: project `ios_ancs_capture_c6`, app compile time `Jul 30 2026 17:45:20`, bootloader compile time `Jul 30 2026 17:46:05`, STA attempted `SPARKPLUS14_5F`, setup AP started `IOS-ANCS-SETUP-572B20` at `192.168.4.1`, existing BLE bond count `1`, state `advertising`, bounded capture did not observe live iPhone `ancs_ready` |
| Read-only DAISO/AX WLAN state | PASS | `windows-wlan-readonly-dupfix.txt`: DAISO GUID `{FEB7E51C-7AB8-4993-B725-E4E8058764FD}` was already connected to `IOS-ANCS-SETUP-572B20` with `192.168.4.2`; AX1800 remained connected to `SPARKPLUS14_5F`; no AX mutation or config POST was performed |

## MQTT Broker Capture Contract

Capture broker events as JSONL or a JSON array. Each event should contain:

```json
{
  "topic": "ios-ancs/c6-2b20/notification",
  "payload": {"relay_id": "example", "source": "esp32c6_ancs"},
  "qos": 1,
  "retain": false
}
```

Required broker evidence:

- Retained QoS 1 `online` availability on `<base>/availability`.
- Retained QoS 1 MQTT Discovery config on `homeassistant/sensor/<device_id>/last_notification/config`.
- Exactly one QoS 1 non-retained notification on `<base>/notification`.
- Notification payload includes `relay_id` and `source=esp32c6_ancs`.
- Published payload is complete and not `pre_existing`.
- No published notification with `app_id=io.robbie.HomeAssistant`, regardless of title.
- When offline-drop proof is requested, the capture includes offline availability, reconnect availability, a `dropped_offline >= 1` state counter, and no replayed notification.

Verifier command:

```powershell
python tools/verify_mqtt_relay.py artifacts/mqtt-events.jsonl `
  --report artifacts/mqtt-relay-report.md
```

Offline-drop verifier command:

```powershell
python tools/verify_mqtt_relay.py artifacts/mqtt-events-offline.jsonl `
  --expect-offline-drop `
  --report artifacts/mqtt-relay-offline-report.md
```

The verifier redacts `title`, `subtitle`, `message`, passwords, tokens, and CA bodies in generated reports.

## Live Evidence Placeholders

These entries are intentionally pending or partial. Do not mark them PASS until fresh device and external-service evidence exists.

### 2026-07-31 COM7 WROOM configuration-save regression

- Hardware: ESP32-D0WD-V3 revision 3.1, 4 MB flash, MAC suffix `F738`, on COM7.
- Before the fix, `POST /api/config` returned `{"ok":false,"error":"save failed"}`. Instrumented runtime logs identified `provision_store: read slots failed: ESP_ERR_NO_MEM`.
- Root cause: the portal and provisioning store simultaneously allocated multiple fixed-size configuration structures after Bluetooth initialization. The configuration includes a 4096-byte CA field, so the final slot-read scratch allocation failed on the live ESP32 heap.
- The fix reuses the existing portal and NVS work buffers instead of allocating four portal configurations plus an additional slot-read buffer.
- After the fix, the same request returned `{"ok":true,"saved":true,"reconnect":true}`. A fresh `/api/status` read reported `configured=true`, both secret-configured flags, the expected client ID and base topic, and no plaintext passwords.
- `GET /api/wifi/scan` returned HTTP 200 with nearby 2.4 GHz networks, and `POST /api/ble/enroll` changed `enroll_window_open` from `false` to `true`; restart returned it to `false` for the unbonded device.
- The saved `SPARKPLUS14_4F` attempt did not obtain an IP in this location. Runtime status ended with disconnect reason `2` (`WIFI_REASON_AUTH_EXPIRE`) at RSSI `-86`, so MQTT and Home Assistant delivery remain pending rather than claimed.
- AX1800 remained connected to `SPARKPLUS14_5F` throughout; only the NUC adapter was temporarily moved to the setup AP and restored.
- The rebuilt v0.2.1 matrix completed for ESP32, ESP32-C2, ESP32-C3, ESP32-C5, ESP32-C6, ESP32-C61, and ESP32-S3. Host contract verification passed `96` tests.

The final Task 5 and after-review status captures show the device config still targeted MQTT broker `220.85.87.159:1883` (`artifacts/task5-final/http-task5-final.json`, `artifacts/task5-final-after-review/http-after-review.json`). The dupfix pass did not repeat portal config POST because that code path was unchanged. MQTT and Home Assistant delivery stayed unverified because the device never reached `sta_has_ip=true`; no broker routing failure was proven in Task 5.

Task 5 did not print or store plaintext Wi-Fi or MQTT secrets. Redacted status showed only secret-configured flags, and the save/connect handoff used empty secret fields to preserve existing stored values.

| Scenario | Status | Evidence path |
| --- | --- | --- |
| Automatic AP visible without BOOT | PASS | `artifacts/task5-final-dupfix/production-serial-dupfix.log`, `artifacts/task5-final-dupfix/windows-wlan-readonly-dupfix.txt` |
| Portal reachable at `192.168.4.1` from Windows | PASS | `artifacts/task5-final-after-review/http-after-review.json`: `root_gets` HTTP 200 x2, content length `9927`; `/api/status` x2 |
| Portal reachable from iPhone | Pending | `artifacts/live-portal-iphone.*` |
| Wi-Fi scan and persistent save | PASS | 2026-07-31 COM7 live run: scan HTTP 200; save returned `ok/saved/reconnect=true`; fresh status returned `configured=true` with redacted secrets |
| Wi-Fi STA IP | Pending | Saved 2.4 GHz candidate ended at reason `2`, RSSI `-86`; recovery AP remained available |
| MQTT availability, state, and Discovery retained | Pending | `artifacts/mqtt-events.jsonl` |
| Enroll from BOOT and portal | PARTIAL | `artifacts/task5-final-after-review/http-after-review.json`: portal `POST /api/ble/enroll` returned 200 and retained existing bond; BOOT enroll not exercised |
| Bonded reconnect without Enroll | Pending | `artifacts/task5-final-dupfix/production-serial-dupfix.log` shows existing bond loaded and advertising observed, but no live iPhone reconnect event observed |
| One real iOS notification to MQTT and HA | Pending | `artifacts/mqtt-events.jsonl`, HA trace |
| Marked or unmarked Home Assistant notifications publish zero MQTT notifications | Pending | `artifacts/mqtt-events-echo.jsonl` |
| MQTT offline notification drop has no replay | Pending | `artifacts/mqtt-events-offline.jsonl` |
| Provisioning reset preserves BLE bond | Pending | `artifacts/live-reset-boundary.*` |

## Task 5 Gaps

- No live iPhone reconnect event was observed in the serial/status windows; existing bond load and bonded advertising were verified only.
- The device did not reach `sta_has_ip=true`, so MQTT connection, Home Assistant availability, and one eligible iOS notification event remain unproved.
- `POST /api/wifi/scan` is not implemented and is not required by the current firmware route contract; the implemented and verified route is `GET /api/wifi/scan`.
- Earlier `tools/build.ps1` fullclean and first `test_app` build attempts exceeded bounded waits. Fresh final artifacts use successful incremental builds, reflashes, serial logs, final host tests, and hash checks listed above.
- The after-review Unity build first failed only in the deep artifact build directory due to dependency-file path creation; the short build directory retry succeeded and was the binary flashed/run on COM9.
- The dupfix pass intentionally did not repeat portal config POST or MQTT/HA delivery because the changed behavior was duplicate-cache marking after MQTT queue acceptance; portal/runtime behavior remains covered by `artifacts/task5-final-after-review/`.

## Reset Boundaries

- Provisioning reset erases only the `provision` NVS partition.
- Default `nvs` at `0x9000,0x6000` stores BLE/Bluedroid bond material and must be preserved for normal provisioning reset.
- Confirmed Replace enrollment deletes BLE bonds and opens a new Enroll window.
- BOOT recovery opens AP or Enroll behavior; it does not erase bonds.

## Home Assistant Artifact

Install:

```text
homeassistant/automation_ios_ancs_c6_relay.yaml
```

Expected behavior:

- Trigger on last-notification sensor state change.
- Ignore `unknown`, `unavailable`, incomplete payloads, and `pre_existing=true`.
- Send exactly one `notify.mobile_app_1bobby` call for a new `relay_id`.
- Prefix relayed title with `[C6→HA]`.
- Use queued mode with max 10.
