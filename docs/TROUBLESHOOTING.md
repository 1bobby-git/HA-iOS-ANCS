# Troubleshooting

This guide lists generic symptoms and actions for supported boards.

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

- Open the 120-second enrollment window with setup-portal **iPhone 기기 등록**, Home Assistant **iPhone 등록 시작**, or BOOT for 3 seconds.
- Keep the setup portal open and pair from iOS **Settings > Bluetooth**.
- Enter the device-specific six-digit code displayed in the setup portal.
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


## MQTT 브로커 연결 대기에서 멈춤

설정 포털은 2초마다 연결 상태를 갱신합니다. `연결 실패`가 표시되면 브로커 주소·포트·TLS 모드와 함께 TCP 시간 초과, 포트 거부, 인증 거부 또는 ESP32 네트워크 경로 오류가 표시됩니다. PC에서 포트가 열리더라도 ESP32가 연결된 서브넷의 NAT loopback·VLAN·게스트 네트워크 정책은 별도로 확인해야 합니다.

MQTT가 연결되면 Home Assistant Discovery가 실제 iPhone 알림보다 먼저 발행됩니다. **테스트 알림 보내기**로 BLE 연결 없이도 MQTT 센서 등록과 상태 갱신을 검증할 수 있습니다.
