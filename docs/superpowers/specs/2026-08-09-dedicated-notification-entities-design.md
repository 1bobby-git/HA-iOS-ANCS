# Dedicated HA iOS ANCS Notification Entities

Status: approved design

Date: 2026-08-09

## Context

The firmware publishes each accepted iOS ANCS notification as one MQTT JSON object. The aggregate MQTT `last_notification` sensor keeps the relay ID as its state and stores the complete JSON object as attributes. The HA iOS ANCS companion integration resolves that source sensor, validates the payload, and currently exposes only one `EventEntity`.

Live evidence confirmed that the payload is not lost: the installed firmware delivered 29 top-level fields, and the event entity stored those fields plus `event_type`. The current firmware contract can add `app_name` as a 30th top-level field. The missing user experience is structural. The companion integration forwards only the `event` platform, so the payload does not appear as purpose-specific entities in the device details view.

## Goals

- Preserve the existing MQTT Discovery entities without disabling, deleting, renaming, or adopting them.
- Add companion-owned `sensor` and `binary_sensor` entities for every meaningful notification field.
- Keep the existing notification event entity for automations and event history.
- Attach all companion entities to the same resolved MQTT device for source-backed entries.
- Preserve the complete, unmodified MQTT payload even when a Home Assistant sensor state must be shortened.
- Update every companion entity from the same accepted payload snapshot.
- Support both source-backed entries and legacy direct-topic entries.

## Non-goals

- Do not change the firmware MQTT topics or Discovery contract.
- Do not remove or disable duplicate MQTT entities.
- Do not publish synthetic notifications to the live broker.
- Do not interpret device-uptime millisecond values as wall-clock timestamps.
- Do not restore stale notification detail values after Home Assistant restarts.

## Considered Approaches

### 1. Full purpose-specific entities plus a raw-payload sensor

Create dedicated sensors and binary sensors for the full notification contract, while also exposing one diagnostic raw-payload sensor whose attributes preserve the complete JSON object.

This is the selected approach. It provides useful device-card values, correct boolean semantics, automation-friendly entity IDs, and a lossless fallback for long or nested values.

### 2. Focused entities plus raw attributes

Create only title, message, app, category, and a few flags, leaving all remaining fields in raw attributes. This reduces entity count but does not satisfy the requirement to model the complete MQTT content by purpose.

### 3. Event-only attribute improvements

Keep one event entity and improve naming or attributes. This is the smallest change, but Home Assistant still would not show the payload as dedicated device entities.

## Architecture

### Runtime snapshot

The runtime remains the single parser and deduplication boundary. It will additionally retain an immutable copy of the latest accepted notification and expose it through a read-only `latest_notification` property.

Every accepted notification follows this order:

1. Validate and deduplicate the MQTT payload.
2. Copy the complete payload into the runtime snapshot.
3. Notify all registered entity listeners.
4. Each entity derives its state only from the in-memory snapshot and writes its Home Assistant state.

The existing pending-event queue remains responsible for an event received before the event platform attaches. The runtime snapshot solves the corresponding multi-platform startup problem: every sensor and binary sensor can seed itself from the same latest payload even if another listener consumed the pending event first.

### Platforms

The config entry will forward these platforms:

- `sensor`
- `binary_sensor`
- `event`

All entities are push based and set `should_poll` to false. Entity properties perform no I/O.

### Shared entity behavior

A small shared base class will provide:

- stable unique IDs derived from the runtime device identity and entity-description key;
- `has_entity_name = True`;
- attachment through `runtime.device_entry` when the MQTT device exists;
- the existing integration-owned `DeviceInfo` fallback for legacy topic entries;
- availability updates from the runtime;
- notification-listener registration and cleanup;
- access to the latest immutable payload snapshot.

The source-backed path must continue setting `entity.device_entry`; it must not copy the MQTT device identifiers into a new `DeviceInfo` or create a second device.

## Entity Contract

### Event

The existing `Notification` event entity remains. It fires `notification` and includes the complete accepted payload as event data.

### Primary content sensors

| Key | Source field | Representation |
| --- | --- | --- |
| `app_name` | `app_name`, falling back to `app_id` | Text sensor |
| `app_id` | `app_id` | Text sensor |
| `title` | `title` | Text sensor |
| `subtitle` | `subtitle` | Text sensor |
| `message` | `message` | Text sensor |
| `event` | `event` | Enum sensor: `added`, `modified`, `removed` |
| `category` | `category` | Enum sensor using the ANCS category names |
| `date` | `date` | Raw text sensor because the payload has no timezone contract |

Text values longer than Home Assistant's 255-character state limit use a 255-character preview as the native state. The complete value is retained in the entity's `full_value` attribute and in the raw-payload sensor.

### Numeric and identifier sensors

| Key | Source field | Representation |
| --- | --- | --- |
| `uid` | `uid` | Integer sensor |
| `session_id` | `session_id` | Integer diagnostic sensor |
| `event_id` | `event_id` | Integer diagnostic sensor |
| `event_flags` | `event_flags` | Integer diagnostic sensor |
| `category_id` | `category_id` | Integer diagnostic sensor |
| `category_count` | `category_count` | Integer sensor |
| `message_size` | `message_size` | Integer when the raw decimal string is valid; otherwise unknown |
| `schema_version` | `schema_version` | Integer diagnostic sensor |
| `relay_id` | `relay_id` | Text diagnostic sensor |
| `target` | `target` | Text diagnostic sensor |
| `source` | `source` | Text diagnostic sensor |
| `device_name` | `device_name` | Text diagnostic sensor |
| `received_at_ms` | `received_at_ms` | Diagnostic milliseconds since device boot |
| `published_at_ms` | `published_at_ms` | Diagnostic milliseconds since device boot |
| `error_code` | `error.code` | Integer diagnostic sensor; unknown when `error` is null |
| `error_name` | `error.name` | Text diagnostic sensor; unknown when `error` is null |

`received_at_ms` and `published_at_ms` are monotonic device-uptime markers. They are not timestamp sensors and must not be converted to dates.

### Binary sensors

| Key | Source field | Meaning |
| --- | --- | --- |
| `complete` | `complete` | Required ANCS attributes were collected |
| `silent` | `silent` | Notification has the silent flag |
| `important` | `important` | Notification has the important flag |
| `pre_existing` | `pre_existing` | Notification existed before the current session |
| `positive_action_available` | `positive_action_available` | Positive action is available |
| `negative_action_available` | `negative_action_available` | Negative action is available |
| `app_id_truncated` | `truncated.app_id` | App ID was truncated by the device parser |
| `title_truncated` | `truncated.title` | Title was truncated by the device parser |
| `subtitle_truncated` | `truncated.subtitle` | Subtitle was truncated by the device parser |
| `message_truncated` | `truncated.message` | Message was truncated by the device parser |
| `has_error` | `error` | The payload contains a non-null error object |

Boolean values must be accepted only when the JSON value is a literal boolean. Missing or wrongly typed values produce an unknown binary-sensor state instead of truthy coercion.

### Raw notification sensor

The diagnostic `Raw notification` sensor uses `relay_id` as its native state and exposes a deep copy of the complete MQTT JSON object as state attributes. It is the lossless representation for:

- long text values;
- the nested `truncated` object;
- the nested or null `error` value;
- fields added by a future backward-compatible firmware schema.

Known fields still receive dedicated entities. Unknown future fields remain available in raw attributes without requiring an immediate companion release.

## State and Availability Semantics

- Before the first accepted notification after setup or restart, detail entities are available but have unknown values when the MQTT source itself is ready.
- When the source becomes unavailable, all companion entities become unavailable.
- When the source returns with an unknown non-retained notification state, entities become available again without fabricating a notification.
- A new accepted notification updates every entity from one snapshot.
- Rejected duplicate, incomplete, pre-existing, removed, and Home Assistant echo payloads do not update the snapshot or any detail entity.
- No detail state is restored across a Home Assistant restart. The next real notification establishes the new snapshot.
- Notification content is recorder-visible entity state and attribute data unless the user excludes those entities from Recorder. This is an intentional consequence of exposing the requested details.

## Coexistence and Migration

- Existing MQTT Discovery entities remain enabled and unchanged.
- The companion does not modify foreign MQTT entity-registry entries.
- Existing HA iOS ANCS config entries require no data migration.
- Reloading an entry after upgrading creates the new companion entities with stable unique IDs.
- Source-backed companion entities attach to the current MQTT device.
- Legacy direct-topic entries retain their integration-owned fallback device.
- Unloading the config entry removes listeners and runtime state only for that entry and leaves all MQTT entities untouched.

## Error Handling

- Field extractors return unknown for missing values or incompatible JSON types.
- Nested access never raises when `truncated` or `error` is absent, null, or malformed.
- Text preview generation never mutates the raw payload.
- Entity callbacks operate on copies or immutable snapshots so one entity cannot alter another entity's data.
- A platform setup failure stops the runtime and leaves no partially active listeners.

## Testing Strategy

Implementation follows red-green-refactor. Tests must first fail for the missing behavior and then pass after the minimal implementation.

Required coverage:

- config entries forward sensor, binary-sensor, and event platforms;
- every declared entity has a stable unique ID and translation key;
- source-backed entities attach to the existing MQTT device;
- legacy entities attach to the integration-owned fallback device;
- one payload updates every sensor and binary sensor;
- nested truncation and error fields map correctly;
- invalid and missing types become unknown rather than coerced values;
- long title, subtitle, message, and app ID states are capped at 255 characters while `full_value` and raw attributes preserve the complete text;
- runtime snapshots preserve an early notification for every platform;
- availability transitions affect all entities consistently;
- rejected payloads do not change entity states;
- unloading one entry removes only its listeners and states;
- multiple configured ANCS devices remain isolated;
- existing MQTT registry entities remain untouched.

The complete Python suite, byte-compilation, whitespace checks, HACS validation, and Hassfest must pass before release.

## Release and Live Validation

This is a feature release and will use version `0.6.0`.

Release sequence:

1. Implement with TDD.
2. Run the full local verification suite.
3. Commit and push to `main` using the repository commit protocol.
4. Wait for HACS and Hassfest checks.
5. Publish GitHub release `v0.6.0`.
6. Install `v0.6.0` through HACS on the live Home Assistant instance.
7. Restart or reload Home Assistant as required.
8. Verify registry ownership, device attachment, entity availability, and log cleanliness.
9. Observe a fresh physical iPhone notification before claiming end-to-end payload population. Do not inject a synthetic MQTT notification into the live broker.

## Acceptance Criteria

- The HA iOS ANCS integration exposes the event plus all specified sensor and binary-sensor entities.
- The complete MQTT notification JSON remains accessible without truncation in the raw sensor attributes.
- The main device page shows useful text, enum, numeric, and boolean details after a notification.
- All companion entities share the correct physical device.
- Existing MQTT entities remain enabled and unchanged.
- No accepted field is silently discarded.
- No rejected notification updates detail state.
- Local tests and GitHub integration validation pass.
- The HACS-installed live version reports `0.6.0`.
- Physical end-to-end completion is claimed only after a new real notification populates the live entities.
