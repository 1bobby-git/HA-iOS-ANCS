# Separate iOS ANCS Device Design

## Goal

Rename the Home Assistant companion integration from **HA iOS ANCS** to
**iOS ANCS** while keeping the repository name, integration domain, and public
URLs unchanged. The integration must continue to consume an existing MQTT
Discovery `last_notification` sensor as a read-only notification source, but
its companion entities must belong to a separate integration-owned Home
Assistant device instead of the MQTT device.

## Invariants

- Repository name: `HA-iOS-ANCS`.
- Integration domain: `ha_ios_ancs`.
- The existing MQTT Discovery sensor remains the only live notification data
  source for a source-backed config entry.
- Existing MQTT devices and MQTT entities are not renamed, disabled, removed,
  migrated, or assigned to another device.
- One MQTT source can configure at most one iOS ANCS config entry.
- Existing iOS ANCS entity registry IDs and unique IDs are preserved during
  migration.
- The integration continues to expose 25 sensors, 11 binary sensors, and one
  event entity for each configured source.

## Naming

The user-facing integration name becomes `iOS ANCS` in the integration
manifest, HACS metadata, config-flow strings, translations, documentation, and
release notes. The repository name and links remain `HA-iOS-ANCS` because they
identify the existing public project.

Each integration-owned device is named using the stable source identity, for
example `iOS ANCS (ios_ancs_example)`. Config entry titles use the same naming
rule so the integration page distinguishes multiple relays without relying on
the MQTT device name.

## Device Ownership

Every config entry owns one Home Assistant device with the identifier:

```text
(ha_ios_ancs, <config_entry_id>)
```

The 25 sensors, 11 binary sensors, and event entity attach to this device.
They do not use the MQTT device's registry ID, do not reuse the MQTT device's
identifiers, and do not declare a `via_device` relationship. This keeps the
devices visually and structurally separate even though the integration reads
the MQTT sensor.

The source entity unique ID and MQTT device identifier remain in config-entry
data. They identify the read-only data source and prevent duplicate config
entries; they do not determine companion device ownership.

## Data Flow

1. The config flow discovers compatible MQTT `last_notification` sensor
   entities and selects one automatically when only one source exists.
2. The config entry stores the selected source entity unique ID and MQTT
   device identifier.
3. The runtime listens to that existing sensor's state and attributes.
4. Accepted notification payloads are copied to the iOS ANCS sensors, binary
   sensors, and event entity.
5. Only iOS ANCS entities write state under the integration-owned device. No
   MQTT registry record is changed.

The integration therefore depends on Home Assistant's MQTT integration as a
transport source, but it does not merge or relate its device with the MQTT
device.

## Migration

The release adds an idempotent migration for every existing source-backed
config entry:

1. Create or resolve the integration-owned device identified by
   `(ha_ios_ancs, config_entry_id)`.
2. Find only entity-registry entries whose platform is `ha_ios_ancs` and whose
   config entry matches the current entry.
3. Move those entries to the integration-owned device while preserving their
   registry IDs, entity IDs, unique IDs, enabled state, and names.
4. Never update entries whose platform is `mqtt`.
5. Leave the former MQTT device and all of its entities intact.

Legacy manual-topic entries already own an integration device. Their entities
stay on that device; the migration only normalizes the device name and remains
safe to run repeatedly.

Reconfiguration changes the read-only source selection but keeps the same
integration-owned device. It updates source data and source-derived entity
unique IDs only where required for the existing uniqueness contract; it never
moves companion entities to the selected MQTT device.

## Failure Handling

- If MQTT is unavailable or no compatible source exists, config flow behavior
  remains unchanged except for the new integration name.
- If the selected source disappears, the iOS ANCS entities become unavailable
  through the existing runtime behavior; the separate device remains
  registered.
- Unknown future enum values remain `unknown` in enum sensors and continue to
  reach the raw sensor and event attributes.
- Migration skips unrelated or malformed registry entries instead of touching
  foreign platforms.

## Tests

Test-driven implementation must add failing tests before production changes
for these behaviors:

- Manifest, HACS metadata, config-flow titles, translations, and documentation
  use `iOS ANCS`, while repository URLs remain unchanged.
- Source-backed sensors, binary sensors, and the event entity attach to one
  integration-owned device rather than the MQTT device.
- The separate device uses the stable integration identifier and has no
  `via_device` link.
- Updating an existing v0.6.0 entry preserves iOS ANCS entity registry IDs,
  entity IDs, unique IDs, and enabled states while changing only their device
  assignment.
- MQTT entity registry snapshots remain byte-for-byte equivalent across the
  migration for the compared identity, device, and disabled-state fields.
- Reconfiguration keeps the integration-owned device and leaves both the old
  and new MQTT devices unchanged.
- Legacy manual-topic entries remain functional and separate.
- The complete integration suite and documentation contracts pass.

## Release And Live Acceptance

Publish this change as companion version `0.6.1` from the existing repository.
The release is complete only after all of the following are verified:

- Local tests, Python compilation, whitespace checks, HACS validation, and
  Hassfest pass.
- `main`, the public tag, and the release target the same commit.
- HACS reports `v0.6.1` installed and Home Assistant has restarted cleanly.
- Each configured source has one separate `iOS ANCS` device containing exactly
  25 sensors, 11 binary sensors, and one event entity.
- Existing MQTT entity counts, device assignments, unique IDs, entity IDs, and
  disabled states are unchanged.
- A real iPhone notification updates title, message, raw payload, completion,
  error, and event entities on the separate iOS ANCS device.
