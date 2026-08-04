# Compact Home Assistant Entities, Uptime, and Restart Design

Date: 2026-08-04

## Goal

Reduce the Home Assistant entity count while preserving the complete ANCS JSON,
make device health visible as one binary sensor, add uptime diagnostics and a
safe MQTT restart control, and expose the three notification values that are
most useful to a Korean-speaking user.

## User-visible contract

The device publishes these Home Assistant entities under its existing MQTT
Discovery device identifier:

- one diagnostic binary sensor named `장치 상태`;
- one aggregate sensor named `최근 알림` whose attributes contain the complete
  notification JSON;
- three focused sensors named `알림 제목`, `알림 내용`, and `앱 이름`;
- the existing `iPhone 등록 시작` button;
- one new diagnostic/configuration button named `장치 재시작`.

The previous per-field notification sensors and individual Wi-Fi sensors are
removed from MQTT Discovery. Wi-Fi values and relay counters remain available
as attributes of `장치 상태`, so reducing entity count does not discard their
diagnostic value.

## Considered approaches

### 1. One readiness binary sensor plus aggregate attributes (selected)

Publish one retained state object and let `장치 상태` read its readiness value
and all other fields as attributes. This is compact, preserves diagnostics, and
gives automations a proper binary state.

### 2. Separate Wi-Fi, MQTT, and BLE binary sensors

This gives clearer history per transport but recreates the entity-count problem
the user asked to solve.

### 3. One text status sensor

This is similarly compact but loses binary-device semantics and makes readiness
automations more complicated.

## Readiness and availability semantics

`장치 상태` is `ON` only when all three conditions are true:

- station Wi-Fi is connected;
- the MQTT session is connected;
- the bonded iPhone BLE/ANCS link is connected.

When MQTT remains connected and BLE disconnects, the binary sensor becomes
`OFF`. When Wi-Fi or MQTT is lost, the ESP32 cannot publish a fresh `OFF` state,
so the existing MQTT last-will topic makes the entity `unavailable`. This is an
intentional distinction between an incomplete ready state and a device that
cannot communicate with Home Assistant.

## Retained state object

The existing `<base_topic>/state` topic remains the single retained diagnostic
state topic. Its object gains readiness, BLE, uptime, and device metadata while
preserving relay counters and Wi-Fi diagnostics:

```json
{
  "ready": true,
  "wifi_connected": true,
  "mqtt_connected": true,
  "ble_connected": true,
  "ble_bonded": true,
  "uptime_seconds": 3723,
  "uptime": "1시간 2분 3초",
  "wifi_ssid": "SPARKPLUS14_4F",
  "wifi_ip": "10.140.40.39",
  "wifi_rssi": -65,
  "accepted": 12,
  "published_ack": 12,
  "dropped_offline": 0,
  "dropped_enqueue": 0,
  "dropped_policy": 1,
  "model": "ESP32-C6",
  "sw_version": "0.2.1",
  "hw_version": "revision 0"
}
```

The values above are illustrative. Runtime values come from the active device.
No Wi-Fi password, MQTT password, TLS certificate, or other credential may be
serialized.

The state is refreshed immediately after MQTT connection, after a Wi-Fi status
change, after a BLE connection-state change, and every 60 seconds. The periodic
refresh advances uptime even when no notification is received.

## Notification entities

The notification topic and all existing JSON fields remain unchanged. The
payload gains one backward-compatible field, `app_name`, while preserving the
original `app_id`. `최근 알림` keeps the notification `relay_id` as its state and
the full notification object as JSON attributes. Existing automations that
consume the previous fields therefore keep working.

The focused sensors read the same notification topic:

- `알림 제목`: `title`, limited to 255 characters for Home Assistant state;
- `알림 내용`: `message`, limited to 255 characters for Home Assistant state;
- `앱 이름`: the payload's friendly Korean `app_name` value.

The complete title and message remain available in the aggregate sensor's JSON
attributes even when a focused sensor state is shortened. The raw `app_id` also
remains in those attributes.

The firmware enriches each outgoing notification with the app name before JSON
serialization. This avoids embedding a large lookup table in every retained
Discovery payload. App-name mapping is an exact, case-insensitive bundle-ID
lookup. Known IDs use the Korean display names documented in
`docs/APP_ID_REFERENCE.md`. Unknown IDs fall back to the original `app_id`; an
empty ID produces an empty state. The reference document is maintained
alongside the firmware mapping so users can see what will be translated without
reading C source.

## MQTT restart control

The MQTT relay subscribes at QoS 1 to `<base_topic>/command/restart` in addition
to the existing enrollment command topic. Home Assistant Discovery publishes a
retained button configuration at:

`homeassistant/button/<client_id>/restart/config`

The button sends the exact payload `RESTART` with `retain: false`. The firmware
rejects retained, fragmented, oversized, differently cased, or otherwise
malformed commands. The MQTT callback only emits a restart-request event. The
application coordinator schedules the existing delayed restart timer so the
callback returns and the MQTT packet can finish cleanly before `esp_restart()`.

## Discovery migration

Removing discovery builders alone would leave old retained configurations on
the broker. The new firmware therefore publishes retained empty payloads to all
legacy per-field notification and Wi-Fi discovery topics before publishing the
new compact entity set.

Cleanup uses the existing paced discovery/outbox path. A failed cleanup stops
the current discovery pass and is retried after the next MQTT reconnect or
boot. This preserves the weak-Wi-Fi safeguards introduced after earlier MQTT
outbox exhaustion failures. Repeating an empty retained publication is safe and
keeps migration correct if Home Assistant or broker retained state is restored.

The aggregate `최근 알림` entity keeps its existing unique ID so Home Assistant
updates it in place instead of creating a duplicate.

## Component boundaries

- `ancs_client` remains the owner of BLE bond and connection state.
- `app_main` samples BLE state from the existing coordinator poll, detects
  transitions, schedules restarts, and passes bounded runtime snapshots to the
  MQTT relay.
- `mqtt_relay` owns MQTT topics, command validation, retained state,
  Home Assistant Discovery, legacy tombstones, app-name lookup, and the
  backward-compatible `app_name` JSON enrichment.
- `ancs_protocol` remains the owner of raw ANCS fields and does not replace the
  original bundle ID with a display name.

No MQTT callback performs BLE work or restarts the chip directly.

## Testing and verification

Implementation follows test-driven development:

1. Add failing payload tests for readiness, BLE, uptime, device metadata, and
   the absence of credentials.
2. Add failing Discovery tests for the single binary sensor, aggregate sensor,
   three Korean focused sensors, restart button, and unchanged enrollment
   button.
3. Add failing command tests proving that only an exact, complete, non-retained
   `RESTART` message emits the restart event.
4. Add failing migration tests for every legacy discovery tombstone and for the
   absence of old non-empty discovery payloads.
5. Add failing app-name lookup and notification JSON enrichment tests for every
   documented bundle ID plus unknown and empty fallbacks.
6. Add failing coordinator tests for 60-second uptime refresh, BLE transition
   refresh, and delayed restart scheduling.
7. Run the complete host contract suite and build every supported ESP32 target.
8. Re-identify the connected serial chip immediately before any flash. For the
   C6, verify retained topics, Home Assistant entity migration, uptime changes,
   BLE `ON` while the nearby bonded iPhone is connected, BLE `OFF` after a real
   disconnect, and one restart-button reboot.

## Completion criteria

The change is complete when Home Assistant shows exactly the selected compact
entity set for a freshly migrated device, old field and Wi-Fi sensors have been
removed by retained tombstones, uptime advances without notifications, device
readiness follows Wi-Fi/MQTT/BLE semantics, the three Korean focused sensors
project the latest notification correctly, the full JSON remains available,
and the restart button causes exactly one delayed reboot without accepting a
retained command.
