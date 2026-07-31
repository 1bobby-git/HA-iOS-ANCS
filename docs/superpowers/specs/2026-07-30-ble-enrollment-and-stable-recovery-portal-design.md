# BLE Enrollment and Stable Recovery Portal Design

Date: 2026-07-30

## Goal

Keep BLE silent before an iPhone has been enrolled, allow BLE advertising only
through the explicit enrollment action in that state, preserve automatic
reconnection for an already bonded iPhone, and make the recovery setup page
reliably reachable when station Wi-Fi cannot connect.

## Confirmed BLE behavior

| Bond state | User action | BLE advertising | Pairing policy |
| --- | --- | --- | --- |
| No bonded iPhone | None | Off | No peer accepted |
| No bonded iPhone | Press `아이폰 등록 시작` or hold BOOT | On for the bounded enrollment window | One new iPhone may pair |
| Bonded iPhone exists | Boot or disconnect | On automatically | Only the bonded iPhone is accepted |
| Bonded iPhone exists | Press `아이폰 등록 시작` | On immediately | Only the bonded iPhone is accepted |
| Bonded iPhone exists | Confirm `등록 iPhone 교체` | On for the bounded replacement window | Old bond is removed and one new iPhone may pair |

The BLE controller and GATT services may be initialized while advertising is
off. "BLE signal off" means no connectable advertising is transmitted.

The enrollment window remains bounded by the existing configured timeout.
When an unbonded enrollment window expires, advertising must stop. A disconnect
must not schedule advertising again unless a bond exists or an enrollment
window is still active.

## Recovery portal problem

The ESP32-C6 uses one 2.4 GHz radio for both SoftAP and station operation. When
the configured station network is weak or unavailable, repeated all-channel
station connection attempts force the SoftAP away from its configured channel.
Clients connected to the setup AP then lose the page. The current scan endpoint
also rejects scans while a station connection attempt is active, so the page
can remain visible while Wi-Fi scanning still fails.

## Recovery portal design

### Stable recovery mode

When station Wi-Fi reaches its connection timeout:

1. Stop station connection attempts and the station timeout timer.
2. Change Wi-Fi operation to AP-only mode.
3. Start or keep the setup AP on channel 6.
4. Keep captive DNS and HTTP available at `192.168.4.1`.
5. Permit Wi-Fi scans because no station connection attempt is active.

The firmware must not continuously retry station Wi-Fi while stable recovery
mode is active. This preserves the setup page instead of trading reachability
for automatic reconnect attempts.

### Save and connect

When the user submits Wi-Fi and MQTT settings:

1. Validate and persist the complete configuration.
2. Return a successful HTTP response before changing the active interface.
3. Stop the recovery AP and captive portal after a short deferred handoff.
4. Start one bounded station connection attempt with the saved configuration.
5. On station success, start or reconnect MQTT.
6. On station timeout or failure, stop station operation and restore stable
   AP-only recovery mode automatically.

Losing the setup-page connection after a successful `저장하고 연결` action is
expected because the device is switching networks. If the target network fails,
the setup AP must reappear without a reboot or button press.

### MQTT failure

An MQTT failure while station Wi-Fi remains connected does not require AP-only
mode. The station channel is already stable, so the setup AP may coexist in
AP+STA mode while MQTT retries continue in the background.

### Unconfigured boot

With no valid stored configuration, boot directly into AP-only recovery mode.
Do not start station operation until the user saves valid settings.

## UI behavior

- Show a clear BLE status: `미등록 · 광고 꺼짐`, `등록 대기`, `등록됨 · 연결
  대기`, or `연결됨`.
- Label the primary action `아이폰 등록 시작`.
- Explain that pressing the primary action with an existing bond reconnects
  only the registered iPhone.
- Keep replacement enrollment separately confirmed.
- During save/connect, show that the AP will disconnect temporarily and will
  return automatically if connection fails.
- Report Wi-Fi scan errors inline without clearing existing form values.

## Safety boundaries

- Do not change the Windows AX1800 adapter, its profile, or its guard task.
- Do not print or expose stored Wi-Fi or MQTT passwords.
- Do not erase an existing BLE bond through the normal enrollment action.
- Continue excluding Home Assistant-originated notifications from MQTT relay
  to prevent loops.
- Notifications received while Wi-Fi or MQTT is unavailable remain dropped;
  no outage backlog is introduced.

## Verification

### Automated

- An unbonded idle state never allows advertising.
- Opening enrollment without a bond allows advertising until timeout.
- Enrollment timeout stops unbonded advertising.
- A stored bond allows automatic advertising after boot and disconnect.
- Normal enrollment with a stored bond accepts only the bonded peer.
- Replacement enrollment requires confirmation and permits a new peer.
- Wi-Fi timeout stops station operation before recovery AP startup.
- Recovery Wi-Fi scan is allowed after station operation stops.
- Save/connect performs one bounded station attempt and restores AP-only mode
  after failure.
- MQTT failure with Wi-Fi connected does not stop station operation.

### Device

1. Flash the new firmware through COM9.
2. Boot with the existing iPhone bond and verify BLE advertising/reconnection.
3. Remove or replace the bond, reboot, and verify no advertising before
   `아이폰 등록 시작`.
4. Press `아이폰 등록 시작` and verify bounded advertising appears.
5. Force station Wi-Fi failure and verify the setup AP remains on channel 6.
6. Connect through the DAISO adapter and load `http://192.168.4.1/`.
7. Run Wi-Fi scan repeatedly and verify results return without losing the page.
8. Submit settings and verify either station/MQTT success or automatic recovery
   of the setup AP after timeout.

Physical BLE and Wi-Fi behavior must be reported from serial, radio/client, and
HTTP evidence; build or unit-test success alone is insufficient.
