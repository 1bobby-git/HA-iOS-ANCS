# Troubleshooting

## COM9 Is Not Available

- Close other serial monitors.
- In Device Manager, confirm `USB-Enhanced-SERIAL CH343 (COM9)` or the current board port.
- List ports:

```powershell
python -m serial.tools.list_ports -v
```

- If flashing reports no serial data, hold BOOT, tap RESET once, release BOOT after the download starts, or unplug and reconnect USB.

COM9 is only needed for flashing, logs, and validation. Normal relay operation is power-only after provisioning.

## Provisioning AP Does Not Appear

Expected first-boot AP:

```text
SSID: IOS-ANCS-SETUP-<SUFFIX>
Address: http://192.168.4.1
```

For the current board, use `IOS-ANCS-SETUP-ABC123`; derive the AP password locally from the displayed suffix.

The setup password format is `ancs-<lowercase_suffix>`; for that board it is
`ancs-abc123`. This lowercase rule applies only to the device setup AP.
Infrastructure Wi-Fi passwords remain case-sensitive and must not be normalized.

If the AP is absent:

- Hold BOOT for 3 seconds to open recovery AP.
- Confirm the `provision` NVS partition is invalid or reset if first-boot behavior is being tested.
- Do not erase the default `nvs` partition unless intentionally deleting BLE bonds.

Provisioning reset targets only the `provision` partition. It clears Wi-Fi, MQTT, TLS CA, client ID, and base topic settings, but it must not erase iPhone BLE bonds.

## Stable Recovery AP After Failed Wi-Fi

The production firmware keeps the setup AP available while it attempts STA connection, then returns to a stable AP-only recovery state if STA cannot obtain a working connection. This is expected recovery behavior, not a portal crash.

Known-good Task 5 after-review recovery evidence on the current board is saved under `artifacts/task5-final-after-review/`. The later duplicate-cache-fix revalidation is under `artifacts/task5-final-dupfix/` and left the current production firmware flashed on COM9.

- `production-serial-after-review.log`: COM9 boot started STA for `EXAMPLE_OFFICE14_5F`, started setup AP `IOS-ANCS-SETUP-ABC123` at `192.168.4.1`, loaded BLE bond count `1`, and entered `state=advertising`.
- `windows-wlan-before-connect-after-review.txt`: DAISO was the setup adapter, GUID `{FEB7E51C-7AB8-4993-B725-E4E8058764FD}`, IP `192.168.4.2/24`; AX1800 was inspected read-only and stayed connected to `EXAMPLE_OFFICE14_5F`.
- `http-after-review.json`: `GET http://192.168.4.1/` returned HTTP 200 with content length `9927`; `GET /api/status` stayed reachable; `GET /api/wifi/scan` returned AP lists twice with count `20`.
- `http-after-review.json` and `http-save-repeat-after-review.json`: after save/connect with empty secret fields, the portal returned `{"ok":true,"saved":true,"reconnect":true}`; status first showed reconnect in progress, then returned to `ap_started=true`, `sta_started=false`, `sta_connecting=false`, `sta_has_ip=false`.
- `save-recovery-serial-after-review-2.log`: repeat save window showed STA connect attempts, Wi-Fi disconnect reasons, AP channel recovery activity, and DAISO DHCP assignment to `192.168.4.2`; paired HTTP status proves the final AP-only recovery flags.
- `artifacts/task5-final-dupfix/production-serial-dupfix.log`: current dupfix production boot showed project `ios_ancs_capture_c6`, compile time `Jul 30 2026 17:45:20`, setup AP start, BLE bond count `1`, and `state=advertising`.
- `artifacts/task5-final-dupfix/windows-wlan-readonly-dupfix.txt`: DAISO remained on the setup AP with `192.168.4.2`; AX1800 remained on `EXAMPLE_OFFICE14_5F`; no portal config POST was performed in the dupfix pass.

Use the implemented scan endpoint:

```powershell
Invoke-RestMethod http://192.168.4.1/api/wifi/scan
```

`POST /api/wifi/scan` is not implemented by the current firmware route table and should return `405 Method Not Allowed`. Treat repeated GET scan success plus stable `/api/status` recovery flags as the recovery proof.

## Portal Does Not Open

- Join the setup AP first.
- Browse directly to `http://192.168.4.1`.
- Captive probes should redirect from iOS and Windows, but direct navigation is the canonical test.
- If Windows keeps another route active, disconnect from other Wi-Fi or use the spare Wi-Fi adapter for the setup AP.

The portal accepts arbitrary Wi-Fi and MQTT settings:

- Wi-Fi SSID and password.
- MQTT host and port.
- MQTT username and password.
- MQTT client ID.
- MQTT base topic.
- TLS enable flag and CA PEM.

TLS without a CA certificate is invalid. Empty secret fields preserve existing stored secrets.

## MQTT Does Not Connect

Check the portal status and retained broker events:

```text
<base>/availability
<base>/state
homeassistant/sensor/<device_id>/last_notification/config
```

Expected contracts:

- Availability is retained, QoS 1, and `online` after connect.
- LWT publishes retained `offline`.
- Discovery config is retained and references `<base>/notification`.
- Notification publishes use QoS 1 and retained false.

If Wi-Fi works but MQTT fails, the recovery AP should remain available so broker settings can be changed. Check host, port, credentials, TLS CA, and broker ACLs for the configured base topic.

## No iPhone Pairing Prompt

- Pairing is not automatic on unbonded boot.
- Hold BOOT for 3 seconds or press **Enroll** in the portal.
- Pair within 120 seconds.
- Use PIN `123456`.

If a bond already exists, unknown new pairing requests are rejected. Use confirmed **Replace enrollment** only when intentionally deleting the current bond.

## `ancs_ready` Does Not Appear

- Confirm iOS notification sharing is enabled for the Bluetooth device.
- Confirm iPhone notification settings allow previews for the test app.
- Check serial logs for Data Source subscription before Notification Source subscription.
- If authentication repeatedly fails, remove the device from iOS Bluetooth settings. Delete ESP32 BLE bonds only through the confirmed Replace flow or by intentionally erasing the default `nvs` partition.

## MQTT Notification Missing

The relay intentionally drops:

- Notifications received while Wi-Fi or MQTT is disconnected.
- `pre_existing=true` notifications.
- Removed events.
- Incomplete or invalid payloads.
- Exact duplicates.
- Every Home Assistant notification where `app_id` is `io.robbie.HomeAssistant`, regardless of title.

Capture broker events and validate:

```powershell
python tools/verify_mqtt_relay.py artifacts/mqtt-events.jsonl `
  --report artifacts/mqtt-relay-report.md
```

Use `--expect-offline-drop` only when the capture includes offline and reconnect availability plus a state event with `dropped_offline >= 1`.

## Home Assistant Sends More Than One Alert

- Confirm the automation uses the MQTT Discovery last-notification sensor.
- Confirm the trigger requires a state change, not only attribute updates.
- Confirm the automation rejects a transition whose previous state was `unavailable`; MQTT availability recovery otherwise restores the old `relay_id` and can resend the old mobile alert.
- Confirm the device state reports increment `dropped_echo` for every `io.robbie.HomeAssistant` notification.
- Confirm the automation ignores `unknown`, `unavailable`, incomplete payloads, and `pre_existing=true`.
- Confirm there is no REST command, webhook, or HTTP action path.
