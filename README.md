# ESP32-C6 iOS ANCS MQTT Relay

ESP32-C6 firmware for a power-only iOS ANCS notification relay. The device pairs with one iPhone through BLE ANCS, connects to user-provided Wi-Fi and MQTT settings, publishes eligible notifications to MQTT, and lets Home Assistant relay each new `relay_id` once.

## Browser Installer

Open the [ANCS Flash Station](https://1bobby-git.github.io/ios-ancs/) in Chrome or Edge on a desktop computer, connect the ESP32-C6 with a USB data cable, and select **Install C6 firmware**. The page uses ESP Web Tools and the checked-in merged factory image, so ESP-IDF is not required for installation.

The current verified target is ESP32-C6 with 8 MB flash. ESP32-WROOM-32 and ESP32-C3 entries are reserved in the installer catalog but remain disabled until board-specific firmware is built and tested.

> iPhone and iPad browsers cannot flash the board over USB. Use desktop Chrome or Edge for installation, then use the captive portal from any phone or computer for Wi-Fi and MQTT setup.

## Requirements

- ESP32-C6 board on Windows `COM9` for local build, flash, and serial validation.
- ESP-IDF v6.0.2 with Bluedroid.
- Python 3.11 or newer.
- Python dependencies:

```powershell
python -m pip install -r tools/requirements.txt
```

The known test board has base MAC suffix `572B20`. Its provisioning AP is `IOS-ANCS-SETUP-572B20` with password `ANCS-572B20`. Other boards derive both values from the last three MAC bytes as `IOS-ANCS-SETUP-<SUFFIX>` and `ANCS-<SUFFIX>`.

## Build And Flash

PowerShell:

```powershell
.\tools\build.ps1
.\tools\flash.ps1 -Port COM9
```

Linux/macOS:

```bash
./tools/build.sh
./tools/flash.sh /dev/ttyACM0
```

After flashing, the device is designed to run from USB power only. Windows on `COM9` is still useful for logs, serial ANCS capture, and device-side Unity tests, but it is not part of the notification relay path.

## First Boot Provisioning

If the `provision` NVS partition is empty or invalid, the device automatically starts a WPA2 setup AP. No BOOT press is required.

1. Join `IOS-ANCS-SETUP-<SUFFIX>` with password `ANCS-<SUFFIX>`.
2. Open `http://192.168.4.1`.
3. Use Wi-Fi scan or enter any SSID manually.
4. Enter the MQTT host, port, and account details. The portal automatically applies a recommended device-specific Client ID and base topic under **Advanced MQTT settings**; edit them only when your broker requires a custom value.
5. Save and connect.

TLS mode requires a CA certificate. Empty Wi-Fi password, MQTT password, and CA fields preserve already stored secret values. Status APIs and reports must show only configured/unconfigured flags for secrets, not secret bodies.

The setup AP stays available while Wi-Fi or MQTT is unhealthy, and also remains available when the network is ready but no BLE bond exists so that Enroll can be started from the portal. The AP closes only after Wi-Fi, MQTT, and an existing BLE bond are all ready.

## BLE Enrollment

BLE pairing is explicit. An unbonded device does not advertise for ANCS/HID pairing until an Enroll window is opened.

- With no stored bond, press BOOT for 3 seconds or press **Enroll** in the portal to open a 120-second pairing window.
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
```

Contracts:

- `<base>/notification`: ANCS JSON plus `relay_id`, `source=esp32c6_ancs`, and uptime; QoS 1; retained false.
- `<base>/availability`: `online` or `offline`; QoS 1; retained true; LWT publishes `offline`.
- `<base>/state`: counters and diagnostics; QoS 1; retained true.
- Discovery config: retained true and uses `relay_id` as the sensor state.

Notifications received while Wi-Fi or MQTT is disconnected are dropped immediately and are not replayed after reconnect. `pre_existing`, incomplete, invalid, duplicate, removed, and marked Home Assistant echo notifications are excluded from MQTT.

## Home Assistant

Install the automation file:

```text
homeassistant/automation_ios_ancs_c6_relay.yaml
```

Copy its content into Home Assistant automation YAML or include it from your automation package. The automation triggers on the MQTT Discovery last-notification sensor state change, ignores incomplete or `pre_existing` payloads, sends `notify.mobile_app_1bobby`, and prefixes the mobile notification title with `[C6→HA]`.

That title marker is the echo boundary. ANCS events from `io.robbie.HomeAssistant` whose title starts with `[C6→HA]` must not be published back to MQTT. Unmarked original Home Assistant notifications are treated like any other original iOS notification and may relay once.

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
