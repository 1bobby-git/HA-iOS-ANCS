# iOS ANCS BLE Connection Binary Sensor Design

## Goal

Expose the current iPhone BLE link as a dedicated diagnostic binary sensor on
the companion-owned `iOS ANCS (<device id>)` device. Existing MQTT devices and
entities remain enabled and unchanged.

## Chosen approach

The companion integration will locate the MQTT Discovery status entity that
belongs to the configured MQTT device. It will observe that entity's
`ble_connected` attribute and expose the value as a companion-owned binary
sensor with the connectivity device class.

This preserves the existing ownership boundary:

- Firmware and MQTT Discovery continue to own the MQTT device and status entity.
- The HACS companion integration owns the new BLE connection binary sensor.
- The companion integration does not subscribe to MQTT topics directly.
- No firmware reflash is required.

## Alternatives considered

### Add another MQTT Discovery entity in firmware

This would expose the same value but would require a firmware release and a
physical reflash. It would also place the requested sensor on the MQTT-owned
device rather than the separate companion device.

### Subscribe to the firmware state topic from the companion integration

This would work but would reintroduce direct MQTT topic configuration and
duplicate the MQTT integration's responsibility. It conflicts with the current
device separation contract.

## Data flow

1. Resolve the configured MQTT last-notification source entity.
2. Use its MQTT device registry entry to find the status entity on that device.
3. Read and track the status entity's `ble_connected` attribute.
4. Publish `on` for literal `true`, `off` for literal `false`, and unknown when
   the status entity or attribute is missing or unavailable.
5. Notify the companion binary sensor only when the derived BLE value changes.

## Entity contract

- Platform: `binary_sensor`
- Translation key: `ble_connected`
- Device class: `connectivity`
- Entity category: `diagnostic`
- Unique ID suffix: `binary_sensor:ble_connected`
- Device: existing companion-owned `iOS ANCS (<device id>)`

## Compatibility

Legacy topic-backed config entries do not have a registry-linked MQTT status
entity. Their BLE connection sensor remains unknown instead of opening a new
direct MQTT subscription.

The integration must not rename, disable, migrate, merge, or delete any
MQTT-owned device or entity.

## Error handling

- Missing MQTT status entity: sensor state is unknown.
- Status entity unavailable or unknown: sensor state is unknown.
- Missing or non-boolean `ble_connected`: sensor state is unknown.
- Registry changes after startup: resolve again when relevant source/status
  state changes, without failing the config entry.

## Verification

Tests will prove that:

- the sensor is created on the companion device;
- `true`, `false`, and unavailable/missing values map correctly;
- status-entity changes update the sensor;
- MQTT registry ownership and entities remain unchanged;
- legacy entries remain loadable;
- the full Home Assistant integration test suite remains green.
