# HA-iOS-ANCS

[Korean canonical guide](README.md) | [GitHub repository](https://github.com/1bobby-git/HA-iOS-ANCS) | [Browser installer](https://1bobby-git.github.io/HA-iOS-ANCS/)

HA-iOS-ANCS is multi-target ESP32 firmware for a power-only iOS ANCS notification relay, plus optional Home Assistant-side assets. The device pairs with one iPhone through BLE ANCS, connects to user-provided Wi-Fi and MQTT settings, publishes eligible notifications to MQTT, and lets Home Assistant relay each new `relay_id` once.

HACS never flashes the ESP32. Flash the ESP32 with the browser installer or the source build/flash scripts. MQTT Discovery works without the companion integration. The companion may improve Home Assistant-side installation and events, but this repository does not claim default HACS-store acceptance unless that acceptance is separately verified.

## What ANCS Means

**Apple Notification Center Service (ANCS)** is Apple's Bluetooth Low Energy service that lets a nearby accessory receive notification metadata from an iPhone or other iOS device after the user explicitly pairs the accessory and allows notification sharing.

This project uses ANCS only as a local notification source. It does not install an iOS app, access an Apple account, bypass iOS notification permissions, or send notifications back to the iPhone.

## How It Works

```text
iPhone → BLE ANCS → ESP32 → Wi-Fi/MQTT → Home Assistant
```

The ESP32 receives eligible ANCS notifications over BLE, filters events that should not be relayed, and publishes MQTT messages. Home Assistant receives retained MQTT Discovery configs and runtime MQTT messages from the broker.

Notifications received while Wi-Fi or MQTT is disconnected are dropped immediately and are not replayed after reconnect. `pre_existing`, incomplete, invalid, duplicate, removed, and marked Home Assistant echo notifications are excluded from MQTT.

The firmware drops every ANCS event whose `app_id` is `io.robbie.HomeAssistant`. The title marker is retained for operator visibility, but the app-level exclusion is the loop-prevention boundary, so marked and unmarked Home Assistant notifications are never published back to MQTT.

## Supported Boards and Verification Status

The shared firmware uses a 4 MB minimum flash layout. All v0.3.3 images shown in the installer are compile, link, partition, and merged-image verified. ESP32/WROOM v0.3.3 was written and hash-verified on `COM7`, then booted into its automatic setup AP. MQTT and BLE validation for this release remains pending because the saved office Wi-Fi was not reachable at the test location. The fuller ESP32/WROOM v0.3.2 proof and ESP32-C6 v0.3.0 `COM9` proof remain historical evidence.

| Target | Typical module/board | Factory image | Validation |
| --- | --- | ---: | --- |
| `esp32` | ESP32-WROOM-32 / WROOM-D32 | 1,425,616 bytes | v0.3.3 COM7 flash, boot, and automatic setup AP verified; MQTT/BLE pending |
| `esp32c2` | ESP32-C2 | 1,445,488 bytes | v0.3.3 build verified |
| `esp32c3` | ESP32-C3 | 1,634,528 bytes | v0.3.3 build verified |
| `esp32c5` | ESP32-C5 | 1,779,664 bytes | v0.3.3 build verified |
| `esp32c6` | ESP32-C6 | 1,779,680 bytes | v0.3.3 build verified; v0.3.0 hardware evidence remains historical |
| `esp32c61` | ESP32-C61 | 1,722,800 bytes | v0.3.3 build verified |
| `esp32s3` | ESP32-S3 | 1,407,600 bytes | v0.3.3 build verified |

ESP32-S2 is excluded because it has no BLE. ESP32-H2 is excluded because it has no Wi-Fi, and ESP32-P4 has no integrated Wi-Fi/BLE radio.

Build verification, hardware flashing, BLE enrollment, and live iPhone notification capture are distinct evidence types. Build verification proves the firmware artifact was produced. Hardware flashing proves an artifact was written to a specific board. BLE enrollment proves a specific iPhone bond. Live iPhone notification capture proves end-to-end ANCS receipt and MQTT publication.

## Five-Minute Installation

1. Open the [browser installer](https://1bobby-git.github.io/HA-iOS-ANCS/) in desktop Chrome or Edge.
2. Connect a supported ESP32 board with a USB data cable.
3. Select the board model for guidance.
4. Press the install button and let ESP Web Tools flash the matching factory image from the unified manifest.
5. Join the setup AP and provision Wi-Fi/MQTT at `http://192.168.4.1`.

The quickest Home Assistant path is MQTT Discovery. The optional HACS companion is not part of ESP32 flashing.

## Browser Installation

Open the [ANCS Flash Station](https://1bobby-git.github.io/HA-iOS-ANCS/) in Chrome or Edge on a desktop computer, connect the ESP board with a USB data cable, select the model for guidance, and press the install button. A unified ESP Web Tools manifest detects the connected chip and selects the matching checked-in factory image, so ESP-IDF is not required for installation.

iPhone and iPad browsers cannot flash the board over USB. Use desktop Chrome or Edge for installation, then use the captive portal from any phone or computer for Wi-Fi and MQTT setup.

The installer uses `./manifests/ios-ancs.json` for all seven supported chip families. The legacy C6 manifest remains a single-chip pointer for existing users and points to the current `esp32c6` v0.3.3 factory image.

## Wi-Fi and MQTT Provisioning

If the `provision` NVS partition is empty or invalid, the device automatically starts a WPA2 setup AP. No BOOT press is required.

1. Join `IOS-ANCS-SETUP-<SUFFIX>` with password `ancs-<lowercase_suffix>`.
2. Open `http://192.168.4.1`.
3. Use Wi-Fi scan or enter any SSID manually.
4. Enter the MQTT host, port, and account details. The portal automatically applies a recommended device-specific Client ID and base topic under **Advanced MQTT settings**; edit them only when your broker requires a custom value.
5. Save and connect.

The known test board has base MAC suffix `ABC123`. Its provisioning AP is `IOS-ANCS-SETUP-ABC123` with password `ancs-abc123`. Other boards use the uppercase MAC suffix in the SSID and the lowercase form `ancs-<lowercase_suffix>` for the setup password. Infrastructure Wi-Fi passwords remain case-sensitive and are stored exactly as entered.

TLS mode requires a CA certificate. Empty Wi-Fi password, MQTT password, and CA fields preserve already stored secret values. Status APIs and reports must show only configured/unconfigured flags for secrets, not secret bodies.

The setup AP stays available while Wi-Fi or MQTT is unhealthy, and also remains available when the network is ready but no BLE bond exists. The ordinary Enroll action is intentionally not exposed in the portal; use the Home Assistant button or BOOT instead. The AP closes only after Wi-Fi, MQTT, and an existing BLE bond are all ready.

## iPhone Enrollment

BLE pairing is explicit. An unbonded device does not advertise for ANCS/HID pairing until an Enroll window is opened.

- With no stored bond, press BOOT for 3 seconds or press the discovered Home Assistant **iPhone 등록 시작** button to open a 120-second pairing window.
- With a stored bond, the same actions request reconnect to that known iPhone only; they do not permit an unknown phone to pair.
- Pair from iOS Bluetooth settings with PIN `123456`.
- Allow iOS notification sharing when prompted.

Use **Replace enrollment** only when intentionally deleting the current iPhone bond and enrolling a new one. BOOT recovery opens the portal or Enroll window; it does not delete BLE bonds.

## Home Assistant and HACS

MQTT Discovery works without HACS or any custom integration. Discovery creates the device, focused sensors, status binary sensor, and control buttons from retained MQTT config messages.

HACS, when used, installs only the Home Assistant companion integration. It never flashes ESP32 firmware, does not write factory images, and does not replace the browser installer. Default HACS-store acceptance is not claimed here.

Install the automation file:

```text
homeassistant/automation_ios_ancs_c6_relay.yaml
```

Copy its content into Home Assistant automation YAML or include it from your automation package. The automation triggers on the MQTT Discovery last-notification sensor state change, ignores incomplete or `pre_existing` payloads, and rejects transitions restored from `unavailable` so an old `relay_id` is not forwarded after MQTT availability recovers. It sends `notify.mobile_app_example_phone` and prefixes the mobile notification title with `[C6묶A]`.

MQTT Discovery also creates an **iPhone 등록 시작** button. Pressing it starts new-iPhone advertising only when no bond exists. If a bond already exists, it only requests a reconnect to that known iPhone and never deletes the bond.

MQTT Discovery keeps the Home Assistant device compact:

- `장치 상태` is one connectivity `binary_sensor`. It is `ON` only while Wi-Fi, MQTT, and BLE are all connected. Its attributes include `ready`, `wifi_connected`, `mqtt_connected`, `ble_connected`, `ble_bonded`, `uptime_seconds`, the Korean-readable `uptime`, `wifi_ssid`, `wifi_ip`, `wifi_rssi`, counters, and manufacturer/model/software/hardware metadata.
- `최근 알림` keeps the latest `relay_id` as state and exposes the complete notification JSON through attributes.
- `알림 제목`, `알림 내용`, and `앱 이름` are the only focused notification sensors. Their states are clipped to 255 characters while the complete original values remain in `최근 알림`.
- `iPhone 등록 시작` and `장치 재시작` are non-retained Home Assistant buttons. Restart accepts only the exact `RESTART` command.

Firmware v0.3.3 removes the retained Discovery configs for the former 33 notification-field sensors and three Wi-Fi sensors, so upgraded devices do not leave those entities behind. Neither Discovery nor retained state contains Wi-Fi or MQTT passwords.

Notification JSON preserves the original `app_id` and adds a friendly `app_name`. Unknown bundle identifiers safely fall back to the original ID. The maintained reference list is in [`docs/APP_ID_REFERENCE.md`](docs/APP_ID_REFERENCE.md).

For the existing C6 device, the identity remains `target=esp32c6` and `source=esp32c6_ancs`. Other firmware targets use their own exact ESP-IDF target name, such as `target=esp32c3` and `source=esp32c3_ancs`.

## Normal Operation

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
- Discovery configs: retained true. The aggregate sensor uses `relay_id` as its state, and each field sensor extracts one JSON value.
- The Enroll button publishes the exact payload `ENROLL` to `<base>/command/enroll` with QoS 1. Retained, partial, and malformed commands are ignored.

## Updating, Resetting, and Replacing a Device

Use the browser installer or source flashing scripts to update firmware. The selected erase mode determines whether Wi-Fi, MQTT, and BLE enrollment data are preserved.

Use a full erase when provisioning data is corrupt, the device is moving to a different user, an old BLE bond must be removed completely, or you need a clean device replacement.

When replacing hardware, flash the new ESP32, provision Wi-Fi/MQTT from its setup AP, enroll the iPhone again, and let Home Assistant discover the new device. To intentionally keep the same MQTT identity, set the same base topic and Client ID under the portal's Advanced MQTT settings.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Browser installer cannot flash | Use desktop Chrome/Edge, verify the USB cable supports data, and check OS serial permissions. iPhone and iPad browsers cannot flash over USB. |
| Setup AP is missing | Verify power and flashing. A device closes the AP only after Wi-Fi, MQTT, and an existing BLE bond are all ready. |
| `http://192.168.4.1` does not open | Confirm you are connected to `IOS-ANCS-SETUP-<SUFFIX>`, then temporarily disable mobile data or VPN routing. |
| MQTT does not connect | Check host, port, TLS CA, username/password, broker ACLs, and duplicate Client IDs. |
| iPhone does not see the device | Open a 120-second Enroll window with BOOT for 3 seconds or the Home Assistant **iPhone 등록 시작** button. |
| iOS asks for a PIN | Enter `123456`. |
| Home Assistant entities are missing | Check the MQTT integration, broker connectivity, Discovery enablement, retained Discovery configs, and `<base>/state`. HACS is optional. |
| Notifications do not arrive | Check iOS notification sharing, BLE connection, Wi-Fi/MQTT connection, and whether the event was filtered as `pre_existing` or a Home Assistant echo. |
| Old notification is not replayed after reconnect | This is expected. Offline notifications are dropped, not replayed. |

## Privacy and Security

- The firmware does not use Apple account credentials, iCloud credentials, or an iPhone app credential.
- Wi-Fi passwords, MQTT passwords, and TLS CA material are not exposed in status API bodies, reports, MQTT Discovery, or retained state.
- Empty Wi-Fi password, MQTT password, and CA fields preserve already stored secret values.
- Infrastructure Wi-Fi passwords remain case-sensitive and are stored exactly as entered.
- iOS notification title, message, app name, and app ID may be published to the MQTT broker and Home Assistant. Restrict broker access accordingly.
- Pairing uses PIN `123456`; open the enrollment window only on a trusted local network.

## Build and Verification

Requirements:

- A supported Wi-Fi + BLE ESP32 board. The current local hardware reference is an ESP32-D0WD-V3/WROOM-class board on Windows `COM7`; ESP32-C6 on `COM9` remains historical evidence.
- ESP-IDF v6.0.2 with Bluedroid.
- Python 3.11 or newer.

Python dependencies:

```powershell
python -m pip install -r tools/requirements.txt
```

PowerShell build and flash:

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
