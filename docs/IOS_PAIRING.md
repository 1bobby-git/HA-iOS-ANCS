# iOS Pairing And Enrollment

This device uses explicit BLE enrollment. It does not advertise for a new iPhone on normal unbonded boot until the owner opens an Enroll window.

## Before Pairing

1. Power the ESP32 board from USB.
2. If provisioning is not complete, join `IOS-ANCS-SETUP-<SUFFIX>` with password `ANCS-<SUFFIX>`.
3. Open `http://192.168.4.1`.
4. Configure Wi-Fi and MQTT. Home Assistant creates the Enroll button after MQTT connects.

For the current board, `<SUFFIX>` is `572B20`, so the AP is `IOS-ANCS-SETUP-572B20` and the password is `ANCS-572B20`.

## Enroll A First iPhone

1. Open an Enroll window by holding BOOT for 3 seconds or pressing the Home Assistant **iPhone 등록 시작** button.
2. On iPhone, open **Settings > Bluetooth**.
3. Select `IOS-ANCS-<FAMILY>-<SUFFIX>` when it appears, such as `IOS-ANCS-C6-2B20`.
4. Enter PIN `123456`.
5. Accept the iOS prompt to share system notifications.
6. Confirm the device reaches `ancs_ready` in serial logs or validation output.

The Enroll window closes after 120 seconds or after a successful bond. If it closes before pairing completes, start Enroll again.

## Existing Bond Reconnect

After a successful bond, rebooting the ESP32 should reconnect to the same iPhone without pressing Enroll. The device should reject new unknown pairing requests while a bond exists.

## Replace Enrollment

Use **Replace enrollment** only when intentionally moving the relay to another iPhone or repairing a broken bond pair. Replace is different from Enroll:

- **Enroll** from Home Assistant or BOOT opens pairing only when no bond exists. With a stored bond it is reconnect-only and rejects unknown phones.
- **Replace enrollment** requires an explicit confirmed portal action, deletes stored BLE bonds, then opens a new 120-second Enroll window.
- BOOT does not delete bonds.
- Provisioning reset does not delete bonds.

If the iPhone still has the old Bluetooth record after Replace, remove it from iOS Bluetooth settings before pairing again.

## Serial Pairing Verification

```powershell
python tools/verify_capture.py `
  --target esp32c6 `
  --port COM9 `
  --baud 115200 `
  --timeout 180 `
  --output artifacts/ancs-capture.jsonl
```

Expected readiness line:

```text
ANCS_STATE_JSON {"target":"<idf-target>","state":"ancs_ready",...,"bonded":true,"data_source_subscribed":true,"notification_source_subscribed":true}
```

Generate one visible iOS notification after `ancs_ready`. The verifier writes the raw serial stream and a single capture JSON file. It does not prove MQTT or Home Assistant delivery; use `tools/verify_mqtt_relay.py` with broker events for that layer.
