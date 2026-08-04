# Validation Report

Validation date: 2026-08-04 (Asia/Seoul)

## Compact Home Assistant entities and readable app names v0.3.3

- Home Assistant Discovery now keeps one aggregate `최근 알림` sensor, three
  focused sensors (`알림 제목`, `알림 내용`, and `앱 이름`), and one diagnostic
  `장치 상태` binary sensor. The status entity uses Wi-Fi, MQTT, and BLE
  connectivity for its state and exposes detailed runtime values as JSON
  attributes instead of creating a separate entity for every field.
- The retained status attributes include Wi-Fi SSID/IP/RSSI, BLE bond and
  connection state, uptime in seconds and Korean-readable text, publish/drop
  counters, and Espressif model/software/hardware metadata. Home Assistant also
  receives a guarded `장치 재시작` button on the exact non-retained `RESTART`
  command contract.
- Firmware Discovery removes the retained configs for the former 33
  notification-field sensors and three Wi-Fi sensors before publishing the
  compact model, preventing stale Home Assistant entities from surviving an
  upgrade.
- Notification JSON preserves the original `app_id` and adds `app_name`.
  Eighty known bundle identifiers are mapped to readable names; unknown IDs
  safely fall back to the original bundle identifier. The matching user
  reference is checked in as `docs/APP_ID_REFERENCE.md`.
- `python -m pytest tools/tests -q` reports `118 passed`. The ESP32-C6 ESP-IDF
  test firmware also completed compile, link, and partition-size validation;
  this pass did not run the Unity image on physical C6 hardware.
- ESP-IDF v6.0.2 completed configure, compile, link, partition validation, and
  merged factory-image generation for all seven supported targets. The matrix
  build tool now accepts an optional bounded Ninja job count so parallel target
  lanes can use the host CPU without multiplying the default job count.
- COM7 was freshly identified as ESP32-D0WD-V3 revision 3.1 with base MAC
  `a8:42:e3:aa:f7:38`. The v0.3.3 ESP32 application was written at `0x10000`
  and hash-verified without erasing NVS or the provisioning partition. It
  booted as app version `0.3.3` and, after the saved network failed, started
  `IOS-ANCS-SETUP-AAF738` automatically at `192.168.4.1` after about 31 seconds.
- The saved `EXAMPLE_OFFICE14_4F` network was only observed around `-78` to `-88
  dBm`; association/authentication expired with Wi-Fi reason 2/4. MQTT, Home
  Assistant Discovery, restart-button execution, and live iPhone ANCS capture
  therefore remain unverified on v0.3.3 hardware. The boot snapshot also
  reported no BLE bond on this WROOM board. Historical v0.3.2 ESP32 MQTT/BLE
  evidence and v0.3.0 C6 evidence remain documented below.
- NVS and provisioning backups were captured before the app-only flash. They
  remain local under the ignored artifacts directory and are not published to
  Git because they may contain credentials.

| Target | Merged bytes | SHA-256 | Validation level |
| --- | ---: | --- | --- |
| `esp32` | 1,425,616 | `a6a2cceb642124a5e0877ce26c062d746ad01256d0f065723440af8c5f5f96af` | v0.3.3 COM7 flash, boot, and automatic setup AP verified; MQTT/BLE pending |
| `esp32c2` | 1,445,488 | `8edb97e48a05fac6756bcc089df627e3295001b385906c7f1247f0d44379bfa6` | v0.3.3 build verified |
| `esp32c3` | 1,634,528 | `5eabaca4753ae9382b94db2f4d24fe0a2a11050e4b0c7f94ecbbd7dd83e263d0` | v0.3.3 build verified |
| `esp32c5` | 1,779,664 | `ad4b697018469227aa6e7d03c2369aefce80d38ded69390a3a2a77fa330a34d0` | v0.3.3 build verified |
| `esp32c6` | 1,779,680 | `727e3bff1b68215eedf639bbbfc3426905cc8e403e27a115c558f75e2a9977dd` | v0.3.3 build verified; v0.3.0 hardware evidence is historical |
| `esp32c61` | 1,722,800 | `5c231f070fc786471101e937f81ae8f74c4a8d78c6da12fdefaf081695df18f4` | v0.3.3 build verified |
| `esp32s3` | 1,407,600 | `041d5b4fc5f2ef21d76860ec711e44212fc01124736a0f6ffaca0d0a5ecd5f47` | v0.3.3 build verified |

## Bounded MQTT Discovery and Home Assistant enrollment v0.3.2

- The reported Wi-Fi and MQTT portal tests were both valid, but they only
  proved a short connection. The attached runtime log showed the sustained
  failure: at roughly `-87` to `-93 dBm`, retained Home Assistant Discovery
  publishing repeatedly logged `Writing didn't complete`, `tcp_write`, and
  `outbox_enqueue(53): Memory exhausted`.
- The retained Discovery publisher no longer retries one failed record five
  times and then continues through the rest of the batch. It now attempts each
  retained record once and aborts the batch on the first negative MQTT publish
  result. A later broker reconnect safely replays the batch from the beginning.
  Availability remains the last record, so an incomplete batch cannot report
  the bridge as online.
- `python -m pytest tools/tests -q` reports `112 passed`. The new regression
  contract proves that a simulated Wi-Fi sensor Discovery outbox failure causes
  exactly one failed publish and no subsequent retained publishes.
- The ESP-IDF Unity test image ran on COM7 and reported `77 Tests 0 Failures 0
  Ignored`, including `retained discovery aborts after one MQTT outbox
  failure:PASS`.
- COM7 was freshly identified as ESP32-D0WD-V3 revision 3.1 with base MAC
  `a8:42:e3:aa:f7:38`, device name `IOS-ANCS-ESP32-F738`, and Bluetooth address
  `A8:42:E3:AA:F7:3A`.
- With a temporary Windows 2.4 GHz hotspot, the device received
  `192.168.137.244` at `-56 dBm`. The existing MQTT configuration published
  retained availability `online`, the diagnostic state, the enroll button, and
  all notification and Wi-Fi sensor Discovery records.
- Home Assistant registered `button.ios_ancs_esp32_f738_enroll` as enabled and
  grouped it with the notification and Wi-Fi entities. The retained device
  record exposed manufacturer `Espressif Systems`, model `ESP32`, software
  `0.3.2`, and hardware `rev 3.1`.
- Before enrollment, a Bluetooth scan found no target advertisement. Publishing
  the exact non-retained `ENROLL` command once on
  `ios-ancs/esp32-f738/command/enroll` exposed `IOS-ANCS-ESP32-F738` at about
  `-61 dBm` with HID service UUID `00001812-0000-1000-8000-00805f9b34fb`.
- ESP-IDF v6.0.2 completed compile, link, partition-size validation, and merged
  factory-image generation for all seven supported targets. SHA-256 values
  below were recalculated from the checked-in v0.3.2 files.
- The original office 2.4 GHz SSID remained marginal at the test location, so
  reliable standalone operation still requires moving the device or providing
  a stronger 2.4 GHz signal. The temporary hotspot was stopped, the original
  `EXAMPLE_OFFICE14_4F` configuration was restored with MQTT secrets preserved, and
  a device restart proved that configuration persisted. The recovery portal
  then reported the original network at `-87 dBm`. AX1800 was not reconfigured.
  A live iPhone pairing and ANCS notification capture were not performed in
  this validation pass.

| Target | Merged bytes | SHA-256 | Validation level |
| --- | ---: | --- | --- |
| `esp32` | 1,421,040 | `74229e987afebf2164cae7f37d49d11e82897f77b51055565a55b3b1a047db6a` | v0.3.2 COM7 flash, Unity, MQTT, HA Discovery, and BLE enrollment verified |
| `esp32c2` | 1,440,224 | `09150778d91c64420defe13f30c36b801f08725b6124e65564b181bdc52f8eaa` | v0.3.2 build verified |
| `esp32c3` | 1,629,280 | `2d95b1ba58c733eded295843b78870425fe7dca07e7eb3817bf44433078655e6` | v0.3.2 build verified |
| `esp32c5` | 1,774,400 | `2a150e750617e074e5a0a80ece0a0473db5de9098e967ab3c34cce9080212673` | v0.3.2 build verified |
| `esp32c6` | 1,774,416 | `da1b4bd591a048a0816ba7c491dc4ce7fa9ce6dafb42eb602c93206b85a4d117` | v0.3.2 build verified; v0.3.0 hardware evidence is historical |
| `esp32c61` | 1,717,552 | `300f0f4dd0e41b22093f2f87f676709c2c443626cc100ba3aac539a7dd880896` | v0.3.2 build verified |
| `esp32s3` | 1,402,928 | `bcabdc144d857648907034bc43e89b96302d06500a75c9fe7e58647631cfd18a` | v0.3.2 build verified |

## Lowercase setup AP and Home Assistant diagnostics v0.3.1

- The setup AP keeps the uppercase MAC suffix in its SSID and now derives its
  WPA2 password as `ancs-<lowercase_suffix>`.
- Infrastructure Wi-Fi passwords remain case-sensitive and are stored exactly
  as entered; the lowercase rule applies only to the generated setup password.
- MQTT Discovery now groups all entities under a device record containing
  `manufacturer`, `model`, `sw_version`, and `hw_version`.
- Retained diagnostics expose `wifi_ssid`, `wifi_ip`, and `wifi_rssi` without
  publishing Wi-Fi or MQTT secrets. The coordinator refreshes this snapshot
  every 60 seconds while MQTT is connected.
- A COM7 hardware run exposed MQTT outbox pressure during connection startup:
  the final three Wi-Fi Discovery records could be omitted when roughly 30
  retained QoS 1 records were queued inside the MQTT callback. Retained
  publication now runs in the relay worker, paces each record, and retries a
  transient queue failure up to five times.
- ESP-IDF v6.0.2 completed compile, link, partition-size validation, and merged
  factory-image generation for all seven supported targets. SHA-256 values
  below were recalculated from the checked-in v0.3.1 files.
- `python -m pytest tools/tests -q` reports `112 passed`. The ESP-IDF Unity test
  image ran on the attached ESP32-D0WD-V3 and reported `77 Tests 0 Failures 0
  Ignored` before the production image was restored.
- COM7 was freshly identified as ESP32-D0WD-V3 revision 3.1 with base MAC
  `a8:42:e3:aa:f7:38`. The v0.3.1 ESP32 production image was written and
  hash-verified without erasing NVS, then booted as target `esp32`.
- The device exposed `IOS-ANCS-SETUP-AAF738`. Windows connected with the new
  lowercase password `ancs-aaf738`; the obsolete uppercase `ANCS-AAF738` was
  rejected. The status and Wi-Fi scan APIs remained reachable at
  `http://192.168.4.1`.
- With no BLE bond, the production image did not advertise unless enrollment
  was explicitly requested. The portal contains no ordinary enrollment button;
  Home Assistant and the three-second BOOT action remain the supported paths.
- A temporary Windows 2.4 GHz hotspot gave the WROOM-D32 address
  `192.168.137.129`. The stored broker connected successfully and retained all
  three Wi-Fi Discovery records, the diagnostic state, and availability. The
  state reported SSID `TOISS_WROVER_CAM`, IP `192.168.137.129`, and RSSI
  `-56 dBm`.
- Home Assistant registered the enabled MQTT enroll button and all three Wi-Fi
  sensors under one device. The device registry reported manufacturer
  `Espressif Systems`, model `ESP32`, software `0.3.1`, and hardware
  `rev 3.1`.
- After validation, the Windows hotspot was stopped and the device was restored
  to its original `EXAMPLE_OFFICE14_4F` Wi-Fi configuration with MQTT secrets
  preserved. Boot logs proved the restored SSID was used; association failed
  only because the local signal was weak (`-83` to `-87 dBm`), so the protected
  setup AP remained available. AX1800 stayed connected to `EXAMPLE_OFFICE14_5F` and
  was never reconfigured.
- ESP32-C6 v0.3.1 physical validation remains pending because the known COM9
  device is absent. The v0.3.0 C6 evidence below is historical and is not
  transferred to the current C6 binary. No live iPhone ANCS notification was
  generated during this WROOM-D32 pass.

| Target | Merged bytes | SHA-256 | Validation level |
| --- | ---: | --- | --- |
| `esp32` | 1,421,056 | `9f3012492cdbc1c093118edb1a8f4022c7c4fca425440074cdb15a9ace2526d6` | v0.3.1 COM7 flash, boot, AP, portal, MQTT, HA diagnostics, and Unity verified |
| `esp32c2` | 1,440,320 | `9abba1ffc10ee88437166d47741737be6ea0c4d77c564c1fe73fc2b197c5f416` | v0.3.1 build verified |
| `esp32c3` | 1,629,360 | `a1c50ff7905f54085d5a6eba94b4eaaf76e06a1a006ffea8f13abd355bffb9dd` | v0.3.1 build verified |
| `esp32c5` | 1,774,480 | `233eac5ec22dcaf0e3f1babb39ddfed8882b8f648a4c4441d356bb5c5b02c10e` | v0.3.1 build verified |
| `esp32c6` | 1,774,512 | `c2561fe937db44b37fadd9f3fcdbeb79c5cedec2d3afa759dc9cfddb728ae14d` | v0.3.1 build verified; v0.3.0 hardware evidence is historical |
| `esp32c61` | 1,717,632 | `ca7ec18aece10b5c0602ea2a5c279777a80823f36cdff3705f7396307a82bb1f` | v0.3.1 build verified |
| `esp32s3` | 1,402,944 | `9daf0ef3df2cfda4ca60ad6d313ccb8095363874ed39466f5f1a40f175885351` | v0.3.1 build verified |

## Home Assistant enrollment control v0.3.0

- The captive portal no longer exposes the ordinary iPhone Enroll action.
- MQTT Discovery publishes a retained `button` entity named
  `iPhone 등록 시작`; its QoS 1 command is the exact non-retained payload
  `ENROLL` on `<base>/command/enroll`.
- The firmware rejects retained, partial, malformed, and wrong-topic Enroll
  commands. The MQTT callback emits an application event; BLE work runs in the
  application coordinator.
- Home Assistant and the 3-second BOOT action use the same safe operation: no
  bond opens a new 120-second enrollment window, while an existing bond only
  requests reconnect and is never deleted.
- `python -m pytest tools/tests -q` reports `102 passed` after the release
  manifests and all seven v0.3.0 factory images were generated.
- COM9 was freshly identified as ESP32-C6 revision v0.0 with base MAC
  `40:4c:ca:57:2b:20`. A normal non-erase flash wrote and hash-verified the
  bootloader, partition table, and v0.3.0 application, preserving NVS.
- The flashed device booted, automatically exposed
  `IOS-ANCS-SETUP-ABC123`, and served `/api/status`. The live portal contains
  no ordinary Enroll button, `id="enroll"`, or `/api/ble/enroll`; it retains
  Home Assistant/BOOT guidance and the confirmation-protected replacement
  action.
- With DTR/RTS fixed before opening COM9, holding the board's BOOT GPIO9 low
  for 3.5 seconds did not reset the C6. `/api/status` reported
  `enroll_window_open=true`, and an active Windows BLE scan found
  `IOS-ANCS-C6-AB12` at Bluetooth address `40:4C:CA:57:2B:22` and RSSI
  `-63 dBm`.
- The office infrastructure AP remained too weak at the C6 (`-83` to
  `-89 dBm`), so a temporary NUC-hosted 2.4 GHz AP at `-42 dBm` and a local
  SSH TCP forward were used only to exercise the real HA broker. The device
  obtained a `192.168.137.x` address and `/api/status` reported both
  `sta_has_ip=true` and `mqtt_connected=true`.
- The broker retained the v0.3.0 button Discovery config with unique ID
  `ios_ancs_c6_ab12_enroll`, command topic
  `ios-ancs/c6-ab12/command/enroll`, exact payload `ENROLL`, QoS 1, and
  `retain=false`. Its retained availability value was `online`; a later
  subscription timed out as expected, proving the command itself was not
  retained.
- Home Assistant registered `button.ios_ancs_c6_ab12_enroll` as an enabled
  MQTT entity. The C6 device has exactly 35 MQTT entities: 34 sensors and the
  one Enroll button.
- Calling Home Assistant's real `button.press` service emitted exactly one
  `ENROLL` command. The connected C6 changed to `enroll_window_open=true`;
  an active BLE scan immediately found `IOS-ANCS-C6-AB12` at
  `40:4C:CA:57:2B:22`, RSSI `-61 dBm`, with 15 advertisements observed.
- After validation, the temporary TCP forward and NUC hotspot were stopped,
  port 1884 was no longer listening, and the C6 was restored to its original
  `EDENARI` Wi-Fi plus `172.30.1.52:1883` MQTT configuration with both stored
  secrets preserved. AX1800 was never reconfigured. Older evidence is
  retained in later historical sections.

| Target | Merged bytes | SHA-256 | Validation level |
| --- | ---: | --- | --- |
| `esp32` | 1,416,192 | `4962453db50f0fed57e7d87f0e30acdda53f71cdb7607d8cbd0cecd23436f032` | v0.3.0 build verified |
| `esp32c2` | 1,434,784 | `1fbd72b18bcf1826f6dbea34c65f9f3fe8f5e23628d5343f219054a7174b6366` | v0.3.0 build verified |
| `esp32c3` | 1,623,824 | `8ae37d65304ce8c11242ed82bc48e5faa089c2ed54ebf33d3f6e413938ceaa53` | v0.3.0 build verified |
| `esp32c5` | 1,768,688 | `647cddd5ff45e13b77f132fccb6c36f71a494477c6ce01ab94f38ba15bc3891b` | v0.3.0 build verified |
| `esp32c6` | 1,768,896 | `a1730f7937b12b9ba524395eb3b09da64ae538c3f7d029c0dbe548a591b07237` | v0.3.0 COM9 flash, boot, AP, portal, BOOT, MQTT, HA button, and BLE advertising verified |
| `esp32c61` | 1,711,888 | `4787e34fc66a352c0ec3f645ee7ad64b1f550b36da9786d6822cd7cbffb36a81` | v0.3.0 build verified |
| `esp32s3` | 1,398,064 | `7b2efb8efec8d084ed38cf3e229e2291d002b006cbf9813fe2fc81496d5b500b` | v0.3.0 build verified |

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
  configured MQTT integration for device `ios_ancs_c6_ab12`. The device now
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
  `IOS-ANCS-C6-AB12`.
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
| Setup suffix | `ABC123` |
| Setup AP | `IOS-ANCS-SETUP-ABC123` |
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
| Production boot/runtime serial | PARTIAL | Artifact `artifacts/task5-final/production-task5-final.log`: booted `ios_ancs_capture_c6`; compile time `Jul 30 2026 14:21:01`; STA attempted `EXAMPLE_OFFICE14_5F`; setup AP started `IOS-ANCS-SETUP-ABC123` at `192.168.4.1`; BLE loaded existing bond count `1`; state JSON showed `bonded=true`, `state=advertising`; STA disconnects observed including reason `34`, RSSI `-81` |
| DAISO setup AP path | PASS | Artifact `artifacts/task5-final/windows-wlan-task5-final.txt`: DAISO adapter `Realtek RTL8192EU Wireless LAN 802.11n USB 2.0 Network Adapter`, GUID `{FEB7E51C-7AB8-4993-B725-E4E8058764FD}`, IP `192.168.4.2/24`, connected to `IOS-ANCS-SETUP-ABC123`; AX1800 was read-only inspected and stayed connected to `EXAMPLE_OFFICE14_5F` |
| Portal root/status/scan | PASS | Artifact `artifacts/task5-final/http-task5-final.json`: `root_gets` are `200/9927` x3; `statuses_before` all show `ap_started=true`, `sta_started=false`, `sta_connecting=false`, `sta_has_ip=false`, `ble_bonded=true`, `mqtt_connected=false`, reason `34`, RSSI `-81`; `scans` counts are `20`, `20`, `20`; `scan_post_contract.status_code=405` |
| Save/connect with preserved secrets | PASS | Artifact `artifacts/task5-final/http-task5-final.json`: `save_connect.response={"ok":true,"saved":true,"reconnect":true}`; raw submitted payload intentionally omitted; status polls show reconnect in progress, one timeout during handoff, then automatic AP return with final polls `ap_started=true`, `sta_started=false`, `sta_connecting=false`, `sta_has_ip=false`, reason `4`, RSSI `-81`; no plaintext Wi-Fi or MQTT secrets were logged |
| BLE enroll with existing bond | PARTIAL | Artifact `artifacts/task5-final/http-task5-final.json`: `ble_enroll.status_code=200`, body `{"ok":true}`; `status_after_ble_enroll.system.ble_bonded=true`, `enroll_window_open=false`, `replace_pending=false`; no bond erase or replace was performed |
| Static REST/action negative checks | PASS | Artifact `artifacts/task5-final/static-contract-task5-final.log`: contract subset `39 passed`; source scan over `main`, `components`, and `homeassistant` found no REST client, REST command, webhook, or Perform Notification Action path; route table lists only `/api/status`, `/api/wifi/scan`, `/api/config`, `/api/mqtt/test`, `/api/ble/enroll`, `/api/ble/replace`, `/api/restart`, and `/api/reset` |
| Home Assistant automation install | PARTIAL | Prior retained readback only, not refreshed in Task 5: `artifacts/live-ha-automation.json` observed `2026-07-29T18:52:16+09:00`, config id `ios_ancs_relay_to_example_phone`, entity `automation.relay_ios_ancs_c6_notifications_to_1bobby`, state `on`, `physical_mobile_receipt_proven=false` |

## Task 5 Final After-Review Evidence

Fresh revalidation artifacts are under `artifacts/task5-final-after-review/`.

| Check | Status | Evidence |
| --- | --- | --- |
| Host Python test suite | PASS | `pytest-after-review.log`: `76 passed in 1.41s` |
| Production build/hash | PASS | `production-build-after-review.log`: `ios_ancs_capture_c6.bin` size `0x19e230`, 19% free; `production-hash-after-review.log`: SHA-256 `7CAE24FC256EE795366681FEED1AAE3986C2A04EBE7AFEEED9B1438F102F816A` |
| Unity test app build | PASS | Deep artifact build failed at `esp_driver_usb_serial_jtag` dependency-file creation, consistent with Windows path length; retry in short `test_app\ba` build dir succeeded. Evidence: `unity-build-after-review.log`, `unity-build-after-review-shortdir.log`, `unity-hash-after-review.log` SHA-256 `62DD716C63F9FF956BEA344007C14DB7459A516381AA829AAF876198A9FF8A80`, size `0x3b620` |
| Unity flash/run on COM9 | PASS | `unity-flash-after-review.log`: bootloader, partition table, and test app hash verification passed; `unity-serial-after-review.log`: `67 Tests 0 Failures 0 Ignored`, `ANCS_TEST_RESULT failures=0` |
| Production reflash on COM9 | PASS | `production-flash-after-review.log`: bootloader, partition table, and production app hash verification passed; production firmware was flashed last and left on COM9 |
| Production boot/runtime serial | PARTIAL | `production-serial-after-review.log` and `.jsonl`: project `ios_ancs_capture_c6`, app compile time `Jul 30 2026 16:32:27`, bootloader compile time `Jul 30 2026 16:33:08`, STA attempted `EXAMPLE_OFFICE14_5F`, setup AP started `IOS-ANCS-SETUP-ABC123` at `192.168.4.1`, existing BLE bond count `1`, state `advertising`, bounded capture did not observe live iPhone `ancs_ready` |
| DAISO/AX WLAN state | PASS | `windows-wlan-before-connect-after-review.txt`: DAISO GUID `{FEB7E51C-7AB8-4993-B725-E4E8058764FD}` connected to `IOS-ANCS-SETUP-ABC123` with `192.168.4.2`; AX1800 remained connected to `EXAMPLE_OFFICE14_5F` before and after |
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
| Production boot/runtime serial | PARTIAL | `production-serial-dupfix.log` and `.jsonl`: project `ios_ancs_capture_c6`, app compile time `Jul 30 2026 17:45:20`, bootloader compile time `Jul 30 2026 17:46:05`, STA attempted `EXAMPLE_OFFICE14_5F`, setup AP started `IOS-ANCS-SETUP-ABC123` at `192.168.4.1`, existing BLE bond count `1`, state `advertising`, bounded capture did not observe live iPhone `ancs_ready` |
| Read-only DAISO/AX WLAN state | PASS | `windows-wlan-readonly-dupfix.txt`: DAISO GUID `{FEB7E51C-7AB8-4993-B725-E4E8058764FD}` was already connected to `IOS-ANCS-SETUP-ABC123` with `192.168.4.2`; AX1800 remained connected to `EXAMPLE_OFFICE14_5F`; no AX mutation or config POST was performed |

## MQTT Broker Capture Contract

Capture broker events as JSONL or a JSON array. Each event should contain:

```json
{
  "topic": "ios-ancs/c6-ab12/notification",
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
- The saved `EXAMPLE_OFFICE14_4F` attempt did not obtain an IP in this location. Runtime status ended with disconnect reason `2` (`WIFI_REASON_AUTH_EXPIRE`) at RSSI `-86`, so MQTT and Home Assistant delivery remain pending rather than claimed.
- AX1800 remained connected to `EXAMPLE_OFFICE14_5F` throughout; only the NUC adapter was temporarily moved to the setup AP and restored.
- The rebuilt v0.2.1 matrix completed for ESP32, ESP32-C2, ESP32-C3, ESP32-C5, ESP32-C6, ESP32-C61, and ESP32-S3. Host contract verification passed `96` tests.

The final Task 5 and after-review status captures show the device config still targeted MQTT broker `203.0.113.10:1883` (`artifacts/task5-final/http-task5-final.json`, `artifacts/task5-final-after-review/http-after-review.json`). The dupfix pass did not repeat portal config POST because that code path was unchanged. MQTT and Home Assistant delivery stayed unverified because the device never reached `sta_has_ip=true`; no broker routing failure was proven in Task 5.

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
- Send exactly one `notify.mobile_app_example_phone` call for a new `relay_id`.
- Prefix relayed title with `[C6→HA]`.
- Use queued mode with max 10.

## ESP32-C3 setup AP compatibility build (2026-08-02)

- The previously published C3 factory image declared minimum chip revision v0.3, so an older C3 could be rejected before `app_main` and never start the setup AP.
- The C3 target now declares minimum revision v0.0 and enables `CONFIG_BT_CTRL_RUN_IN_FLASH_ONLY=y`, avoiding ECO3-only Bluetooth ROM symbols while retaining the ANCS client.
- ESP-IDF v6.0.2 completed the C3 build and merge. The factory image is 1,622,032 bytes, SHA-256 `8DD305F8229C887757C18119B79363CA10455975F8344A7DCB6C3FEC8BB4273F`, with 26% of the 2 MB app partition free.
- `esptool image-info` reports ESP32-C3, 4 MB DIO, minimum chip revision v0.0, and valid checksum/hash.
- Host contracts pass: `python -m pytest tools/tests -q` reports `97 passed`.
- Live C3 AP and portal verification is pending because no ESP32-C3 USB/JTAG serial device was connected during this build.
