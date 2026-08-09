# HA iOS ANCS MQTT Device Auto-Registration Design

Date: 2026-08-09

## Problem

The optional HACS integration currently asks the user to enter an MQTT base topic even though the firmware has already registered its device and notification sensors through Home Assistant MQTT Discovery. The integration then derives exact subscription topics from that manually entered value. A mismatch prevents notification delivery.

The integration also creates its event entity on a separate `ha_ios_ancs` device identifier. As a result, the native notification event is detached from the MQTT device where the existing `최근 알림`, title, message, and app-name sensors are shown. A notification can therefore be published by the firmware without becoming visible in the location the user expects.

## Goals

- Remove raw MQTT topic input from new HACS integration setup.
- Find already registered HA iOS ANCS MQTT devices through Home Assistant's public entity and device registries.
- Automatically configure the integration when exactly one compatible device exists.
- Show a device choice, not a topic field, when multiple compatible devices exist.
- Attach the native ANCS event entity to the existing MQTT device.
- Reuse the MQTT `last_notification` sensor as the authoritative notification source.
- Surface new firmware notification attributes on the event entity without replaying stale state after startup.
- Preserve existing manual-topic entries until they can be safely reconfigured or automatically upgraded.
- Cover the firmware-to-MQTT-to-Home-Assistant contract with regression tests.

## Non-Goals

- Do not duplicate the MQTT Discovery sensors or buttons in the HACS integration.
- Do not add a Home Assistant `NotifyEntity`; ANCS notifications originate outside Home Assistant and belong on an `EventEntity`.
- Do not change the firmware MQTT payload or Discovery schema unless testing exposes a separate firmware defect.
- Do not add a new dependency or use undocumented MQTT integration state.
- Do not replay the current retained/restored notification as a new event during Home Assistant startup.

## Considered Approaches

### 1. Reuse the existing MQTT notification entity

This is the selected approach. The config flow discovers the firmware's MQTT `last_notification` sensor in Home Assistant's registries. Runtime delivery listens for state changes on that sensor, and the event entity links to the sensor's existing device.

Benefits:

- No raw topic knowledge is required.
- Setup works immediately after HACS installation without requiring an MQTT reload.
- The MQTT integration remains the owner of MQTT subscriptions and Discovery state.
- The HACS event appears on the same device as the existing notification sensors.
- Entity renames remain recoverable because the config entry stores the MQTT entity unique ID rather than its current entity ID.

### 2. Re-subscribe to retained MQTT Discovery topics

The config flow could subscribe to `homeassistant/sensor/+/last_notification/config`, parse retained payloads, and store the discovered topics. This still duplicates part of MQTT Discovery, requires a bounded wait, and is sensitive to retained-message and reload timing. It is reserved only as a possible legacy migration aid, not the primary design.

### 3. Add a HACS-specific firmware discovery channel

The firmware could publish an additional retained registration document for the custom integration. This requires a firmware rollout and creates a second discovery protocol for data Home Assistant already owns. It is out of scope.

## Registry Discovery Contract

A compatible source is an entity registry entry that satisfies all of these conditions:

- entity domain is `sensor`;
- platform is `mqtt`;
- the entry belongs to a device registry entry;
- the device has an MQTT identifier `(mqtt, <device_identifier>)`;
- the entity unique ID equals `<device_identifier>_last_notification`.

The exact unique-ID relationship is already emitted by the repository's firmware Discovery payload. It distinguishes this sensor from unrelated MQTT notification sensors without reading MQTT internals.

For every match, the integration retains:

- the stable MQTT entity unique ID;
- the stable MQTT device identifier;
- the current entity ID for display and immediate runtime binding;
- the existing device registry entry for entity attachment.

Candidates are sorted by Home Assistant device name and entity ID to keep the selection form deterministic.

## Config Flow

### New entry

1. Verify that the Home Assistant MQTT client is available.
2. Scan the entity and device registries for compatible sources.
3. If no source exists, abort with `no_devices_found` and direct the user to confirm MQTT Discovery and the firmware device first.
4. If one source exists, create the config entry immediately without displaying a form.
5. If several sources exist, display a selector containing device names; never display a topic field.
6. Use the MQTT device identifier as the config-flow unique ID and abort duplicate configuration.

New config-entry data contains:

- `source_entity_unique_id`;
- `mqtt_device_identifier`.

It does not contain `base_topic`.

### Reconfiguration and legacy entries

Existing entries containing only `base_topic` remain loadable. During setup:

- if exactly one compatible MQTT source exists, update the entry to the new source-based data automatically;
- if no unambiguous source exists, retain the existing direct-MQTT runtime so the update does not break a previously working entry;
- expose a reconfigure step that uses the same device-selection flow and replaces the legacy data once the user chooses a device.

This compatibility path is intentionally isolated. All newly created entries use only the source-entity runtime.

## Runtime and Data Flow

For a source-based entry:

1. Resolve the current entity ID from platform `mqtt`, domain `sensor`, and the stored entity unique ID.
2. Resolve its current device registry entry.
3. Subscribe to Home Assistant state-change events for that entity.
4. Treat `unknown`, `unavailable`, missing states, and availability-only transitions as availability changes, not notifications.
5. For a valid new state, copy its attributes and use the sensor state as a `relay_id` fallback when the attribute is absent.
6. Apply the existing filters for incomplete, pre-existing, removed, duplicate, and Home Assistant echo notifications.
7. Dispatch the accepted payload to the native ANCS event entity.
8. Call `_trigger_event("notification", payload)` followed by `async_write_ha_state()`.

The runtime records the current source state when it starts but does not dispatch it. Only later state changes can create ANCS events. Because firmware relay IDs are unique per accepted notification, a new relay ID produces a new state transition and duplicate IDs remain suppressed.

Home Assistant-managed metadata such as `friendly_name` is removed from event data. Firmware attributes, including title, message, app ID, app name, completion status, and relay ID, are preserved.

## Device and Entity Model

The ANCS `EventEntity` has a stable unique ID derived from the MQTT device identifier and the `notification` event type.

It must not declare `DeviceInfo` with a new `ha_ios_ancs` identifier. Instead, it assigns the resolved MQTT `DeviceEntry` to `entity.device_entry`. This attaches the event entity to the device already owned by the MQTT config entry and follows the Home Assistant 2026.8 single-config-entry device model while remaining compatible with the repository's pinned Home Assistant 2026.7.3 tests.

The resulting device page keeps the existing MQTT entities:

- recent notification relay ID and JSON attributes;
- notification title;
- notification message;
- app name;
- device status and configuration buttons;

The HACS integration adds only the native notification event entity.

## Error Handling

- Missing MQTT integration: abort setup with `mqtt_unavailable`.
- No compatible MQTT device: abort setup with `no_devices_found`.
- Source entity removed while the entry is loaded: mark the event entity unavailable without firing a notification.
- Source entity missing during setup or reload: raise `ConfigEntryNotReady` with the missing source unique ID.
- Source entity renamed: resolve the current entity ID from the stored unique ID on the next setup or reload.
- Multiple devices during legacy auto-upgrade: keep the legacy runtime until the entry is explicitly reconfigured.
- Malformed or incomplete notification attributes: ignore the state change without consuming its relay ID in the deduplication window.
- Unload: remove state listeners before discarding runtime data; do not remove states or registry entries owned by MQTT.

## Testing Strategy

### Registry and config-flow tests

- no topic field is present in new setup;
- one compatible MQTT device creates an entry automatically;
- multiple devices show deterministic device choices;
- no devices and unavailable MQTT return the correct translated reasons;
- unrelated MQTT sensors and malformed identifier relationships are ignored;
- duplicate device discovery aborts;
- entity-ID renames still resolve through the stored unique ID;
- reconfigure converts a legacy entry without creating a duplicate.

### Notification and event tests

- a full firmware notification payload from `tools/tests/test_verify_mqtt_relay.py` produces a native event;
- title, message, app ID, app name, completion status, and relay ID appear as event attributes;
- the event entity uses the existing MQTT `DeviceEntry`;
- startup state is not replayed;
- duplicate, incomplete, pre-existing, removed, and Home Assistant echo payloads are ignored;
- `unknown` and `unavailable` update availability without firing an event;
- listener removal and entry unload do not affect MQTT-owned entities.

### Compatibility and repository checks

- legacy topic entries continue to load when automatic migration is ambiguous;
- the existing Python integration suite passes against `homeassistant==2026.7.3`;
- `tools/tests` continue to pass;
- translations and manifest JSON validate;
- Hassfest and HACS validation remain clean;
- static type checking passes for changed integration and test files.

## Acceptance Criteria

- Adding HA iOS ANCS with one MQTT-discovered firmware device creates the config entry without asking for a topic or device choice.
- Adding it with multiple devices asks only which device to use.
- The config entry consumes state changes from the already registered MQTT sensor rather than deriving raw MQTT topics.
- A new valid firmware notification changes the native event entity and exposes the full notification attributes.
- The event entity appears on the existing MQTT device, alongside the current MQTT sensors and buttons.
- Restarting Home Assistant does not replay a stale notification as a new event.
- Existing manual-topic entries are not broken by the upgrade and can be converted through automatic or explicit reconfiguration.
- Fresh targeted and full tests prove the new behavior; hardware and live iPhone validation are reported separately if unavailable.

## References

- Home Assistant EventEntity: https://developers.home-assistant.io/docs/core/entity/event/
- Home Assistant device registry: https://developers.home-assistant.io/docs/device_registry_index/
- Home Assistant single-config-entry device guidance: https://developers.home-assistant.io/blog/2026/07/21/device-registry-single-config-entry/
