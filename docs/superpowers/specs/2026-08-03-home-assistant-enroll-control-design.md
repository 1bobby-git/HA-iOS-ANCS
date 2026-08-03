# Home Assistant Enroll Control Design

## Context

The provisioning portal currently exposes an `iPhone 등록 시작` button that calls `POST /api/ble/enroll`. This is an unsuitable first-enrollment flow on iPhone because the user must leave the ESP32 setup access point and open iOS Bluetooth settings before pairing can continue.

The firmware already has two safe enrollment semantics in `ancs_client_request_enroll()`:

- without a stored bond, it opens a bounded enrollment window and starts BLE advertising;
- with a stored bond, it keeps the bond and advertises only for reconnection.

The BOOT button already reaches the same function after a three-second hold. MQTT currently publishes notifications and Home Assistant sensor discovery but does not subscribe to control commands.

## Goals

- Remove ordinary iPhone enrollment from the provisioning web page.
- Create a Home Assistant MQTT button immediately after the device connects to its configured MQTT broker.
- Start safe enrollment or bonded reconnection when that Home Assistant button is pressed.
- Preserve the three-second BOOT-button enrollment path on every supported target.
- Never erase an existing iPhone bond from the ordinary Home Assistant button or BOOT-button path.
- Preserve the confirmation-protected replacement flow under advanced device management.
- Rebuild and publish installer images for every supported ESP32 target.

## Non-goals

- No REST control path.
- No Home Assistant YAML or manual automation requirement.
- No automatic BLE advertising before a Home Assistant or BOOT request when no bond exists.
- No queued enrollment command while the ESP32 is offline.
- No change to the existing notification relay or Home Assistant echo-suppression policy.

## Chosen Architecture

Extend the existing `mqtt_relay` component because it already owns the MQTT client, connection lifecycle, availability topic, device identity, and retained Home Assistant discovery messages. A second MQTT client or a new component would duplicate lifecycle and credential handling without improving the user-visible behavior.

`mqtt_relay` will expose a new `MQTT_RELAY_EVENT_ENROLL_REQUEST` event. The MQTT event callback will only validate the incoming command and emit that event. The application coordinator queue will receive it and call `ancs_client_request_enroll()` from the coordinator task, keeping BLE operations out of the ESP MQTT event loop.

## MQTT Contract

On each successful broker connection the firmware will:

1. subscribe at QoS 1 to `<base_topic>/command/enroll`;
2. publish retained discovery to `homeassistant/button/<mqtt_client_id>/enroll/config`;
3. publish the existing retained `online` availability message and sensor discovery messages.

The Home Assistant button discovery payload will contain:

- `name`: `iPhone 등록 시작`
- `unique_id`: `<mqtt_client_id>_enroll`
- `default_entity_id`: `button.<mqtt_client_id>_enroll`
- `command_topic`: `<base_topic>/command/enroll`
- `payload_press`: `ENROLL`
- `availability_topic`: the existing `<base_topic>/availability`
- `payload_available`: `online`
- `payload_not_available`: `offline`
- `qos`: `1`
- `retain`: `false`
- `entity_category`: `config`
- the same device identifier, name, manufacturer, model, and software version used by the sensor discovery payloads.

The command handler accepts only an exact topic match and an exact, complete `ENROLL` payload. It rejects retained commands, malformed topics, fragmented or oversized payloads, empty payloads, and all other strings. Repeated valid presses are idempotent at the enrollment-state layer.

The discovery message is retained so Home Assistant recreates the button after its own restart. The command is not retained, preventing stale enrollment requests from replaying when the ESP32 reconnects.

## Enrollment Semantics

- No bond: open the configured bounded enrollment window (currently 120 seconds) and advertise for a new iPhone.
- Existing bond: do not open pairing to an unknown device and do not erase the bond; advertise for the known iPhone to reconnect.
- Already connected: the request succeeds without deleting or replacing the active bond.
- Replacement: remains a separate confirmation-protected action and is never triggered by the Home Assistant button or BOOT button.

## Portal Behavior

Remove the ordinary Bluetooth enrollment panel button, its JavaScript click handler, the `POST /api/ble/enroll` route, and the corresponding portal handler field. Keep BLE status in the dashboard and change its guidance to instruct the user to use the Home Assistant `iPhone 등록 시작` button or hold BOOT for three seconds.

Keep the advanced `iPhone 등록 교체` control with its explicit `REPLACE ENROLLMENT` confirmation because it is a separate destructive maintenance operation.

## BOOT Button Behavior

Retain the existing target-specific BOOT GPIO mapping and three-second hold threshold. A completed hold calls `ancs_client_request_enroll()` exactly once. The existing recovery-portal event remains active so the same physical gesture continues to provide network recovery access while also starting BLE enrollment.

## Failure Handling

- If Wi-Fi or MQTT is unavailable, Home Assistant shows the button unavailable through the existing LWT availability topic; the BOOT button remains the local fallback.
- If MQTT subscription fails, treat the connection as unable to provide control, report the error, and retry through the existing MQTT reconnect path.
- If the coordinator queue is full, log and drop the command rather than invoking BLE from the MQTT callback.
- If `ancs_client_request_enroll()` fails, log the ESP error without deleting the bond or restarting the device.
- Notifications received while Wi-Fi or MQTT is down remain dropped under the existing policy and are not replayed.

## Verification

### Automated

- Portal contract tests prove that the ordinary enroll button, JavaScript handler, API route, and handler field are absent while BLE status and confirmed replacement remain.
- MQTT component tests prove the discovery topic and JSON payload, retained discovery, QoS 1 subscription, exact non-retained command validation, and event emission.
- Startup contract tests prove that MQTT enrollment reaches the app coordinator and calls `ancs_client_request_enroll()` outside the MQTT callback.
- Existing BLE security tests prove that a stored bond is never erased by ordinary enrollment.
- Existing BOOT-button tests continue to prove a three-second hold reaches `ancs_client_request_enroll()` exactly once.
- Run the complete Python contract suite and ESP-IDF builds for ESP32, C2, C3, C5, C6, C61, and S3.

### Hardware and Home Assistant

- Identify the connected COM port and chip immediately before flashing.
- Flash the freshly built C6 factory image and capture UART boot evidence.
- Verify the setup portal no longer exposes ordinary enrollment.
- With valid Wi-Fi and MQTT connectivity, verify the retained button discovery topic at the broker and the button entity in Home Assistant.
- Press the Home Assistant button and verify UART enrollment evidence plus BLE advertising without bond deletion.
- Hold BOOT for three seconds and verify the same advertising path.
- Verify existing notification sensors and the Home Assistant notification echo filter remain present.

## Release

Build fresh merged factory images for every supported target, update installer manifests and SHA-256 metadata, run installer validation, commit using the repository Lore commit protocol, push `main`, wait for GitHub Pages deployment, and verify the public installer serves the new release artifacts.
