# ESP32 iOS ANCS MQTT Relay

Multi-target ESP32 firmware for a power-only iOS ANCS notification relay. The device pairs with one iPhone through BLE ANCS, connects to user-provided Wi-Fi and MQTT settings, publishes eligible notifications to MQTT, and lets Home Assistant relay each new `relay_id` once.

## Browser Installer

Open the [ANCS Flash Station](https://1bobby-git.github.io/ios-ancs/) in Chrome or Edge on a desktop computer, connect the ESP board with a USB data cable, select the model for guidance, and press **USB 장치 자동 감지 후 설치**. A unified ESP Web Tools manifest detects the connected chip and selects the matching checked-in factory image, so ESP-IDF is not required for installation.

The shared firmware uses a 4 MB minimum flash layout. All v0.3.2 images shown in the installer are compile, link, partition, and merged-image verified. ESP32/WROOM v0.3.2 is hardware-verified on `COM7`; ESP32-C6 v0.3.0 on `COM9` remains historical hardware evidence.

| Target | Typical module/board | Factory image | Validation |
| --- | --- | ---: | --- |
| `esp32` | ESP32-WROOM-32 / WROOM-D32 | 1,421,040 bytes | v0.3.2 COM7 flash, Unity, MQTT, and BLE enrollment verified |
| `esp32c2` | ESP32-C2 | 1,440,224 bytes | v0.3.2 build verified |
| `esp32c3` | ESP32-C3 | 1,629,280 bytes | v0.3.2 build verified |
| `esp32c5` | ESP32-C5 | 1,774,400 bytes | v0.3.2 build verified |
| `esp32c6` | ESP32-C6 | 1,774,416 bytes | v0.3.2 build verified; v0.3.0 hardware evidence remains historical |
| `esp32c61` | ESP32-C61 | 1,717,552 bytes | v0.3.2 build verified |
| `esp32s3` | ESP32-S3 | 1,402,928 bytes | v0.3.2 build verified |

ESP32-S2 is excluded because it has no BLE. ESP32-H2 is excluded because it has no Wi-Fi, and ESP32-P4 has no integrated Wi-Fi/BLE radio.

> iPhone and iPad browsers cannot flash the board over USB. Use desktop Chrome or Edge for installation, then use the captive portal from any phone or computer for Wi-Fi and MQTT setup.

## Requirements

- A supported Wi-Fi + BLE ESP32 board. ESP32-C6 on Windows `COM9` is the local hardware-validation reference.
- ESP-IDF v6.0.2 with Bluedroid.
- Python 3.11 or newer.
- Python dependencies:

```powershell
python -m pip install -r tools/requirements.txt
```

The known test board has base MAC suffix `572B20`. Its provisioning AP is `IOS-ANCS-SETUP-572B20` with password `ancs-572b20`. Other boards use the uppercase MAC suffix in the SSID and the lowercase form `ancs-<lowercase_suffix>` for the setup password. Infrastructure Wi-Fi passwords remain case-sensitive and are stored exactly as entered.

## Build And Flash

PowerShell:

```powershell
.\tools\build.ps1 -Target esp32c6
.\tools\flash.ps1 -Port COM9
```

Build every supported target and generate merged web-installer images:

```powershell
.\tools\build_matrix.ps1
```

Linux/macOS:

```bash
./tools/build.sh
./tools/flash.sh /dev/ttyACM0
```

After flashing, the device is designed to run from USB power only. Windows on `COM9` is still useful for logs, serial ANCS capture, and device-side Unity tests, but it is not part of the notification relay path.

## First Boot Provisioning

If the `provision` NVS partition is empty or invalid, the device automatically starts a WPA2 setup AP. No BOOT press is required.

1. Join `IOS-ANCS-SETUP-<SUFFIX>` with password `ancs-<lowercase_suffix>`.
2. Open `http://192.168.4.1`.
3. Use Wi-Fi scan or enter any SSID manually.
4. Enter the MQTT host, port, and account details. The portal automatically applies a recommended device-specific Client ID and base topic under **Advanced MQTT settings**; edit them only when your broker requires a custom value.
5. Save and connect.

TLS mode requires a CA certificate. Empty Wi-Fi password, MQTT password, and CA fields preserve already stored secret values. Status APIs and reports must show only configured/unconfigured flags for secrets, not secret bodies.

The setup AP stays available while Wi-Fi or MQTT is unhealthy, and also remains available when the network is ready but no BLE bond exists. The ordinary Enroll action is intentionally not exposed in the portal; use the Home Assistant button or BOOT instead. The AP closes only after Wi-Fi, MQTT, and an existing BLE bond are all ready.

## BLE Enrollment

BLE pairing is explicit. An unbonded device does not advertise for ANCS/HID pairing until an Enroll window is opened.

- With no stored bond, press BOOT for 3 seconds or press the discovered Home Assistant **iPhone 등록 시작** button to open a 120-second pairing window.
- With a stored bond, the same actions request reconnect to that known iPhone only; they do not permit an unknown phone to pair.
- Pair from iOS Bluetooth settings with PIN `123456`.
- Allow iOS notification sharing when prompted.

Use **Replace enrollment** only when intentionally deleting the current iPhone bond and enrolling a new one. BOOT recovery opens the portal or Enroll window; it does not delete BLE bonds.

## MQTT Topics

The default base topic is configured in the portal, commonly:

```text
ios-ancs/<device_id>
```

Published topics:

```text
<base>/notification
<base>/availability
<base>/state
homeassistant/sensor/<device_id>/last_notification/config
homeassistant/sensor/<device_id>/<field>/config
homeassistant/button/<device_id>/enroll/config
<base>/command/enroll
```

Contracts:

- `<base>/notification`: ANCS JSON plus `relay_id`, target-specific `source=<target>_ancs`, and uptime; QoS 1; retained false.
- `<base>/availability`: `online` or `offline`; QoS 1; retained true; LWT publishes `offline`.
- `<base>/state`: counters and diagnostics; QoS 1; retained true.
- Discovery configs: retained true. The aggregate sensor uses `relay_id` as
  its state, and each field sensor extracts one JSON value.
- The Enroll button publishes the exact payload `ENROLL` to
  `<base>/command/enroll` with QoS 1. Retained, partial, and malformed commands
  are ignored.

Notifications received while Wi-Fi or MQTT is disconnected are dropped immediately and are not replayed after reconnect. `pre_existing`, incomplete, invalid, duplicate, removed, and marked Home Assistant echo notifications are excluded from MQTT.

## Home Assistant

Install the automation file:

```text
homeassistant/automation_ios_ancs_c6_relay.yaml
```

Copy its content into Home Assistant automation YAML or include it from your automation package. The automation triggers on the MQTT Discovery last-notification sensor state change, ignores incomplete or `pre_existing` payloads, and rejects transitions restored from `unavailable` so an old `relay_id` is not forwarded after MQTT availability recovers. It sends `notify.mobile_app_1bobby` and prefixes the mobile notification title with `[C6→HA]`.

The firmware drops every ANCS event whose `app_id` is `io.robbie.HomeAssistant`. The title marker is retained for operator visibility, but the app-level exclusion is the loop-prevention boundary, so marked and unmarked Home Assistant notifications are never published back to MQTT.

MQTT Discovery also creates an **iPhone 등록 시작** button. Pressing it starts
new-iPhone advertising only when no bond exists. If a bond already exists, it
only requests a reconnect to that known iPhone and never deletes the bond.

MQTT Discovery creates one aggregate `last notification` sensor plus 33
individual field sensors per device. The aggregate sensor state is the latest
`relay_id`, and the complete notification JSON remains attached to it through
`json_attributes_topic`. The individual sensors cover:

```text
schema_version, target, device_name, session_id, event, event_id, uid,
event_flags, silent, important, pre_existing, positive_action_available,
negative_action_available, category_id, category, category_count, app_id,
title, subtitle, message, message_size, date, complete, truncated, error,
received_at_ms, relay_id, source, published_at_ms
```

The four nested `truncated` flags are also exposed as
`truncated_app_id`, `truncated_title`, `truncated_subtitle`, and
`truncated_message`. The `app_id`, `title`, `subtitle`, and `message` entity
states are clipped to 255 characters to stay within Home Assistant's state
limit; their complete values are preserved in the aggregate sensor attributes.

Three retained diagnostic sensors expose the live connection snapshot as
`wifi_ssid`, `wifi_ip`, and `wifi_rssi`. Home Assistant attaches every entity
to the same device record and shows `manufacturer`, `model`, `sw_version`, and
`hw_version`. Neither Discovery nor retained state contains Wi-Fi or MQTT
passwords.

For the existing C6 device, the identity remains `target=esp32c6` and `source=esp32c6_ancs`. Other firmware targets use their own exact ESP-IDF target name, such as `target=esp32c3` and `source=esp32c3_ancs`.

## Validation Tools

Serial ANCS capture:

```powershell
python tools/verify_capture.py `
  --port COM9 `
  --baud 115200 `
  --timeout 180 `
  --output artifacts/ancs-capture.jsonl
```

MQTT broker event validation:

```powershell
python tools/verify_mqtt_relay.py artifacts/mqtt-events.jsonl `
  --report artifacts/mqtt-relay-report.md
```

Use `--expect-offline-drop` when the capture includes offline and reconnect availability events plus state counters proving an offline drop.

Automated host checks:

```powershell
python -m pytest tools/tests -q
```

Firmware and Unity checks:

```powershell
.\tools\build.ps1
Push-Location test_app
idf.py -B build-tests build
idf.py -B build-tests -p COM9 flash monitor
Pop-Location
```
