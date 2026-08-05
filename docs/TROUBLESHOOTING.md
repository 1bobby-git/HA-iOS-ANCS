# Troubleshooting

This guide lists generic symptoms and actions. Historical validation evidence stays in [Validation Report](VALIDATION_REPORT.md).

## Browser Flashing Fails

- Use desktop Chrome or Edge.
- Confirm the USB cable supports data, not only charging.
- Close serial monitors and other tools using the port.
- Check OS serial-device permissions.
- If flashing cannot enter download mode, hold BOOT, tap RESET once, and release BOOT after download starts.

Developer examples use `COMx` on Windows and `/dev/ttyACM0` on Linux. Replace them with the actual detected serial port.

## Setup AP Is Missing

- Expected SSID: `IOS-ANCS-SETUP-XXXXXX`.
- Expected password: `ancs-xxxxxx`.
- `XXXXXX` is the last six hexadecimal digits of the base Wi-Fi MAC address, uppercase in the SSID and lowercase in the password. The generic form is `ancs-<lowercase_suffix>`, and it is not a model number.
- Infrastructure Wi-Fi passwords are case-sensitive and stored exactly as entered.
- Verify the board is powered and the flash completed.
- Hold BOOT for 3 seconds to open the recovery window.

The setup AP can close after Wi-Fi, MQTT, and an existing BLE bond are all ready.

## Portal Does Not Open

- Join `IOS-ANCS-SETUP-XXXXXX` first.
- Browse directly to `http://192.168.4.1`.
- Temporarily disable VPN, mobile-data routing, or another active Wi-Fi route if the browser goes elsewhere.

The portal stores Wi-Fi and MQTT settings only. It does not store Home Assistant configuration or iPhone notification permissions.

## Wi-Fi Or MQTT Does Not Connect

- Check Wi-Fi SSID and password exactly as entered.
- Check MQTT host, port, username, password, TLS mode, CA certificate, broker ACL, and duplicate Client ID.
- Empty secret fields preserve existing stored values.
- TLS mode requires a CA certificate.

The setup AP should remain available while Wi-Fi or MQTT is unhealthy so settings can be corrected.

## Home Assistant Entities Are Missing

- Confirm the Home Assistant MQTT integration is installed and connected to the same broker.
- Confirm MQTT Discovery is enabled.
- Check retained Discovery configs under `homeassistant/.../config`.
- Check runtime state under `<base>/state`.
- HACS is optional for MQTT Discovery and does not flash ESP32 firmware.

## iPhone Does Not Pair

- Open the 120-second enrollment window with BOOT for 3 seconds or Home Assistant **iPhone 등록 시작**.
- Pair from iOS **Settings > Bluetooth**.
- Enter PIN `123456`.
- Allow notification sharing when prompted.

If pairing information already exists, enrollment requests reconnect to the stored iPhone only. Use confirmed Replace enrollment only when intentionally deleting the current iPhone pairing information.

## Notifications Do Not Arrive

- Confirm iOS notification sharing remains enabled for the Bluetooth device.
- Confirm BLE, Wi-Fi, and MQTT are connected.
- Confirm the test app is allowed to show notifications on iOS.
- Remember that offline notifications are dropped and are not replayed after reconnect.
- The relay filters `pre_existing=true`, removed, incomplete, invalid, duplicate, and Home Assistant echo notifications.

Validate broker captures with:

```powershell
python tools/verify_mqtt_relay.py artifacts/mqtt-events.jsonl `
  --report artifacts/mqtt-relay-report.md
```

Use `--expect-offline-drop` only when the capture includes offline and reconnect events plus state counters proving an offline drop.

## Automation Sends Duplicate Mobile Alerts

- Trigger from the MQTT Discovery last-notification sensor state change, not only attribute updates.
- Reject transitions where the previous state was `unavailable`.
- Ignore `unknown`, `unavailable`, incomplete payloads, and `pre_existing=true`.
- Do not use REST commands, webhooks, or HTTP actions for relay delivery.
