# Lowercase Setup AP Password and Home Assistant Wi-Fi Diagnostics

Date: 2026-08-03

## Goal

Make the ESP32 setup access-point password predictable in lowercase and expose
the registered device's current Wi-Fi connection details as Home Assistant MQTT
Discovery sensors.

## User-visible contract

- The setup AP SSID remains `IOS-ANCS-SETUP-<MAC_SUFFIX>` with the MAC suffix in
  uppercase.
- The setup AP password becomes `ancs-<mac_suffix>` with both the prefix and MAC
  suffix in lowercase. The known C6 therefore uses `ancs-572b20`.
- Infrastructure Wi-Fi passwords entered by the user remain byte-for-byte
  unchanged because Wi-Fi credentials are case-sensitive.
- Home Assistant creates these diagnostic sensors under the same ESP32 device
  as the notification sensors and enrollment button:
  - Wi-Fi SSID
  - Wi-Fi IP address
  - Wi-Fi signal strength in dBm
- The Home Assistant device entry also reports:
  - manufacturer: `Espressif Systems`
  - model: the compiled ESP32 chip family, such as `ESP32` or `ESP32-C6`
  - firmware version: the semantic release version embedded in the image
  - hardware version: the runtime chip revision reported by ESP-IDF
- No Wi-Fi password, MQTT password, certificate, or other credential is
  serialized into MQTT state or Discovery payloads.

## Considered approaches

### 1. Extend the existing retained state topic (selected)

Add the Wi-Fi fields to `<base_topic>/state` and publish three Discovery sensor
definitions that read from that topic. This preserves the current topic
structure, availability contract, and Home Assistant device identity.

### 2. Add a separate retained Wi-Fi topic

Publish the same fields to `<base_topic>/wifi`. This separates diagnostics from
relay counters but creates another lifecycle and retained-state path without a
user-visible benefit.

### 3. Add Wi-Fi data only as aggregate sensor attributes

Attach the values to an existing entity instead of creating individual sensors.
This is the smallest payload change but does not satisfy the requirement for
separately visible Home Assistant sensors.

## Architecture

The provisioning runtime remains the owner of ESP-IDF Wi-Fi and network state.
It provides a bounded snapshot containing connection status, configured SSID,
station IP address, and RSSI. The application coordinator transfers that
snapshot to the MQTT relay. The MQTT relay owns JSON serialization, retained
state publication, and Home Assistant Discovery.

The platform identity component remains the owner of target-family names. The
application obtains the release version from the ESP-IDF application descriptor
and the chip revision from ESP-IDF chip information, then supplies a bounded
device-information snapshot to the MQTT relay. Discovery builders consume this
snapshot instead of guessing a board-module name from the generic ESP32 target.

This boundary prevents the MQTT component from directly managing Wi-Fi or
network interfaces and keeps credentials in the provisioning configuration
owner. The snapshot contains no password field.

## MQTT state and Discovery

The retained `<base_topic>/state` object keeps its existing relay counters and
adds:

```json
{
  "wifi_ssid": "EDENARI",
  "wifi_ip": "192.168.1.42",
  "wifi_rssi": -61
}
```

The exact address above is illustrative. Runtime values come from the active
station connection.

Discovery publishes retained configurations for:

- `homeassistant/sensor/<client_id>/wifi_ssid/config`
- `homeassistant/sensor/<client_id>/wifi_ip/config`
- `homeassistant/sensor/<client_id>/wifi_rssi/config`

All three configurations use the existing availability topic and device
identifier. They are marked as diagnostic entities. The RSSI sensor has unit
`dBm`, device class `signal_strength`, and state class `measurement`.

## Home Assistant device information

Every aggregate sensor, field sensor, diagnostic sensor, and enrollment button
publishes the same complete Discovery `device` object. It contains the existing
identifier and name plus `manufacturer`, `model`, `sw_version`, and
`hw_version`. This fills the manufacturer and model columns shown in Home
Assistant and keeps all entities attached to one device.

The classic `esp32` target is reported as `ESP32`, not as `WROOM-D32`, because
ESP-IDF cannot reliably distinguish every module or third-party board that uses
the same chip. More specific targets are reported as `ESP32-C2`, `ESP32-C3`,
`ESP32-C5`, `ESP32-C6`, `ESP32-C61`, or `ESP32-S3`. The hardware version is the
actual runtime chip revision rather than a fabricated board revision.

## Update behavior

The coordinator refreshes the Wi-Fi snapshot immediately after Wi-Fi and MQTT
become connected and every 60 seconds while both remain connected. Each refresh
updates the retained state payload. Home Assistant therefore restores the last
known values after restart and receives ongoing RSSI changes without requiring
a new notification.

If the station is not connected, MQTT availability already prevents the device
entities from presenting stale values as available. A failed Wi-Fi snapshot
read is logged without credentials and does not restart the device or block
notification relay.

## Security and compatibility

- Setup AP authentication remains WPA2-PSK; only the generated password casing
  changes.
- Existing Windows or phone profiles containing the old uppercase setup AP
  password must be updated once after flashing.
- The setup AP SSID, infrastructure Wi-Fi credentials, MQTT credentials, topic
  roots, notification payloads, and enrollment behavior otherwise remain
  unchanged.
- AX1800 is outside the change and verification scope and must not be modified.

## Testing and verification

Implementation follows test-driven development:

1. Add a failing contract test for the lowercase setup AP password generation
   while proving infrastructure Wi-Fi passwords are not normalized.
2. Add failing MQTT tests for the three Discovery topics and payloads.
3. Add a failing state-payload test for SSID, IP, and RSSI and assert that no
   credential fields appear.
4. Add failing Discovery tests that require identical manufacturer, model,
   semantic firmware version, and runtime chip revision metadata on every
   entity type.
5. Add failing coordinator/runtime contract tests for initial and 60-second
   refresh behavior and bounded device-information propagation.
6. Implement the minimum code required to pass each test, then run the complete
   host test suite and all supported firmware builds.
7. Re-identify the chip on COM9, flash the C6 without erasing provisioning NVS,
   update only the DAISO setup-AP profile to the lowercase password, and verify
   setup AP access, station/MQTT connectivity, retained state, and the three
   Home Assistant entities plus device metadata.
8. Restore temporary network paths after verification, confirm AX1800 remains
   unchanged, publish the release artifacts, and verify GitHub Pages manifests
   and binary hashes.

## Completion criteria

The change is complete only when the known C6 accepts `ancs-572b20`, rejects the
old uppercase setup password, continues to use the stored infrastructure Wi-Fi
password unchanged, and Home Assistant shows live SSID, IP, and RSSI diagnostic
sensors plus manufacturer, model, firmware version, and chip revision under the
registered ESP32 device without exposing secrets.
