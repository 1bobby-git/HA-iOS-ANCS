# iOS Pairing Guide

This device uses explicit BLE enrollment. It does not advertise for a new iPhone until the owner opens an enrollment window.

## Before Pairing

1. Flash a supported ESP32 board.
2. Join `IOS-ANCS-SETUP-XXXXXX` with password `ancs-xxxxxx`.
3. Open `http://192.168.4.1`.
4. Save Wi-Fi and MQTT settings. The portal stores only Wi-Fi and MQTT configuration.
5. Wait for Home Assistant MQTT Discovery to create the device and **iPhone 등록 시작** button.

`XXXXXX` is the last six hexadecimal digits of the base Wi-Fi MAC address. Use uppercase in the SSID and lowercase in the password. The generic form is `ancs-<lowercase_suffix>`, and it is not a model number. Infrastructure Wi-Fi passwords are case-sensitive and stored exactly as entered.

## Pair An iPhone

1. Hold BOOT for 3 seconds or press Home Assistant **iPhone 등록 시작**.
2. Pair within the 120-second enrollment window.
3. On iPhone, open **Settings > Bluetooth** and select the `IOS-ANCS-*` device.
4. Enter PIN `123456`.
5. Allow notification sharing when iOS asks.
6. Generate a visible notification and confirm Home Assistant updates `최근 알림` and `앱 이름`.

## Existing Bond

After successful pairing, the ESP32 reconnects only to the stored iPhone. BOOT or **iPhone 등록 시작** requests reconnect when a bond exists; it does not permit a different phone to pair.

## Replace Enrollment

Use confirmed Replace enrollment only when moving the relay to another iPhone or repairing a broken bond. Replace deletes stored BLE bonds and opens a new 120-second enrollment window. BOOT fallback and Wi-Fi/MQTT provisioning reset do not delete BLE bonds.

If the iPhone still has the old Bluetooth record, remove it from iOS Bluetooth settings before pairing again.

## Verification Helpers

Serial capture example:

```powershell
python tools/verify_capture.py `
  --target esp32c6 `
  --port COMx `
  --baud 115200 `
  --timeout 180 `
  --output artifacts/ancs-capture.jsonl
```

`COMx` is a generic Windows serial-port placeholder. Use the actual connected port. On Linux, a generic example is `/dev/ttyACM0`.

Serial ANCS capture does not prove MQTT or Home Assistant delivery. Use `tools/verify_mqtt_relay.py` with broker events for that layer.
