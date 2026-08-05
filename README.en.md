# Home Assistant iOS ANCS

[Korean](README.md) | [GitHub](https://github.com/1bobby-git/HA-iOS-ANCS) | [Browser installer](https://1bobby-git.github.io/HA-iOS-ANCS/)

Home Assistant iOS ANCS is ESP32 firmware plus an optional Home Assistant companion integration for relaying iPhone notifications into local Home Assistant automation through BLE ANCS and MQTT. MQTT Discovery creates the basic device entities and buttons without HACS. ESP32 firmware is installed with the browser installer or source build tools, not through HACS.

**Apple Notification Center Service (ANCS)** is Apple's Bluetooth Low Energy service that lets an iPhone or other iOS device share notification metadata with a nearby accessory after pairing and notification-sharing approval.

```text
iPhone → BLE ANCS → ESP32 → Wi-Fi/MQTT → Home Assistant
```

## Background

The project bridges iOS notifications into local Home Assistant automations through ESP32 and MQTT without requiring an iOS app or Apple developer account. The ESP32 pairs directly with one iPhone over BLE, then publishes new eligible notification events to the user's Wi-Fi and MQTT broker.

## Prerequisites

- A supported Wi-Fi + BLE ESP32 board
- Desktop Chrome or Edge and a USB data cable
- 2.4 GHz Wi-Fi and an MQTT broker
- Home Assistant MQTT integration with MQTT Discovery enabled
- iPhone Bluetooth notification sharing approval
- For source builds: ESP-IDF v6.0.2 with Bluedroid and Python 3.11 or newer

## Quick Install

1. Open the [browser installer](https://1bobby-git.github.io/HA-iOS-ANCS/) in desktop Chrome or Edge and connect the ESP32 board with a USB data cable.
2. Select the board model and flash the factory image with ESP Web Tools.
3. Join the board's `IOS-ANCS-SETUP-XXXXXX` Wi-Fi using password `ancs-xxxxxx`.
4. Open `http://192.168.4.1` and save Wi-Fi and MQTT settings only. The portal does not store Home Assistant or iPhone notification settings.
5. In Home Assistant, wait for MQTT Discovery to find the device, then press **iPhone 등록 시작** to open the 120-second enrollment window.
6. In iOS Bluetooth settings, select the device, enter PIN `123456`, and allow notification sharing. Verify that `최근 알림` and `앱 이름` update in Home Assistant.

`XXXXXX` is the last six hexadecimal digits of the base Wi-Fi MAC address. The SSID uses uppercase hex and the password uses the same suffix in lowercase. The generic form is `ancs-<lowercase_suffix>`, and it is not a model number.

Holding BOOT for 3 seconds opens the setup AP or iPhone enrollment recovery window. If a BLE bond already exists, enrollment actions request reconnect to the known iPhone only and do not allow a new phone to pair.

## Supported Boards And v0.3.3 Build Facts

The shared firmware uses a 4 MB minimum flash layout. All v0.3.3 images shown in the installer are compile, link, partition, and merged-image verified. ESP32-S2 is excluded because it has no BLE. ESP32-H2 is excluded because it has no Wi-Fi, and ESP32-P4 has no integrated Wi-Fi/BLE radio.

| Target | Typical module/board | Factory image | v0.3.3 status |
| --- | --- | ---: | --- |
| `esp32` | ESP32-WROOM-32 / WROOM-D32 | 1,425,616 bytes | Build verified; limited board flash/boot/AP proof |
| `esp32c2` | ESP32-C2 | 1,445,488 bytes | Build verified |
| `esp32c3` | ESP32-C3 | 1,634,528 bytes | Build verified |
| `esp32c5` | ESP32-C5 | 1,779,664 bytes | Build verified |
| `esp32c6` | ESP32-C6 | 1,779,680 bytes | Build verified; older hardware evidence is historical |
| `esp32c61` | ESP32-C61 | 1,722,800 bytes | Build verified |
| `esp32s3` | ESP32-S3 | 1,407,600 bytes | Build verified |

See [Validation Report](docs/VALIDATION_REPORT.md) for detailed validation boundaries and historical hardware evidence. Build verification, flashing, BLE enrollment, and live iPhone notification capture are separate evidence types.

## Home Assistant And HACS

MQTT Discovery works without HACS. After the device connects to the broker, it publishes retained Discovery configs and Home Assistant creates the device, `최근 알림`, `앱 이름`, status sensor, and **iPhone 등록 시작** button.

HACS installs only the Home Assistant companion integration; it never flashes or updates ESP32 firmware. To install as a HACS custom repository, open the [HA iOS ANCS HACS My Link](https://my.home-assistant.io/redirect/hacs_repository/?owner=1bobby-git&repository=HA-iOS-ANCS&category=integration) and confirm the repository addition in Home Assistant. This documents custom-repository installation only; it does not claim default HACS-store acceptance.

Example automation:

```text
homeassistant/automation_ios_ancs_c6_relay.yaml
```

Before enabling it, replace `sensor.replace_with_your_last_notification_entity` with your discovered last-notification sensor and `notify.replace_with_your_mobile_app_service` with your mobile app notify service. The example forwards only new `relay_id` state changes and filters `complete=false`, `pre_existing=true`, `unknown`, `unavailable`, and availability-restore transitions.

Notification JSON preserves the original `app_id` and adds a friendly `app_name`. Unknown bundle identifiers fall back to the original ID. Representative mappings are in [App ID Reference](docs/APP_ID_REFERENCE.md).

## Troubleshooting

- If browser flashing fails, use desktop Chrome/Edge, verify the USB cable supports data, and check OS serial permissions. iPhone and iPad browsers cannot flash over USB.
- If `IOS-ANCS-SETUP-XXXXXX` is missing, verify power and flashing, then hold BOOT for 3 seconds to open the recovery window.
- If `http://192.168.4.1` does not open, confirm you are connected to the setup AP and temporarily disable VPN or mobile-data routing.
- If MQTT does not connect, check host, port, TLS CA, username/password, broker ACLs, and duplicate Client IDs.
- If the iPhone does not see the device, reopen the 120-second enrollment window with **iPhone 등록 시작** or BOOT for 3 seconds.
- If iOS asks for a PIN, enter `123456` and allow notification sharing.
- If Home Assistant entities are missing, check the MQTT integration, Discovery, retained configs, and `<base>/state`.

See [iOS Pairing Guide](docs/IOS_PAIRING.md) and [Troubleshooting](docs/TROUBLESHOOTING.md) for more detail.

## Privacy And Security

- The firmware does not use an iOS app, Apple account credentials, or iCloud credentials.
- Wi-Fi passwords, MQTT passwords, and TLS CA bodies are not exposed in status APIs, Discovery, retained state, or reports.
- Empty secret fields preserve already stored values.
- iOS notification title, body, app name, and app ID may be published to the MQTT broker and Home Assistant. Restrict broker access accordingly.
- Pairing uses PIN `123456`; open enrollment only on a trusted local network and fully erase plus re-enroll before handing the device to another user.

## Developer Reference

```powershell
python -m pip install -r tools/requirements.txt
python -m pytest tools/tests -q
python -m pytest tests -q
.\tools\build.ps1 -Target esp32c6
.\tools\flash.ps1 -Port COMx
.\tools\build_matrix.ps1
```

```bash
./tools/build.sh
./tools/flash.sh /dev/ttyACM0
```

`COMx` and `/dev/ttyACM0` are generic examples. Replace the target and serial port with the connected board's actual values. Use `python tools/verify_mqtt_relay.py ...` for MQTT relay captures and `python tools/verify_capture.py --port COMx ...` for serial ANCS captures.
