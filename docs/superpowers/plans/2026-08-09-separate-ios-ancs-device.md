# Separate iOS ANCS Device Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the companion integration to iOS ANCS and move all companion entities from the MQTT device to a stable integration-owned device without changing any MQTT registry record.

**Architecture:** Keep the existing MQTT Discovery `last_notification` sensor as a read-only event source. Add one focused device-ownership module that creates `(ha_ios_ancs, config_entry_id)`, migrates only `ha_ios_ancs` registry entries to it, and supplies entity `DeviceInfo`; source discovery and notification parsing remain unchanged.

**Tech Stack:** Python 3.14, Home Assistant config entries and device/entity registries, pytest-homeassistant-custom-component, HACS validation, Hassfest, GitHub Actions, HACS UI.

---

## File Map

- Create `custom_components/ha_ios_ancs/device.py`: integration-owned device naming, `DeviceInfo`, creation, and entity-device migration.
- Modify `custom_components/ha_ios_ancs/__init__.py`: run config-entry migration and ensure the owned device before platform setup.
- Modify `custom_components/ha_ios_ancs/entity.py`: always expose integration-owned `DeviceInfo`; never attach through the runtime's MQTT device.
- Modify `custom_components/ha_ios_ancs/runtime.py`: remove the foreign-device attachment contract while preserving source validation and state listening.
- Modify `custom_components/ha_ios_ancs/config_flow.py`: create version-2 entries with iOS ANCS titles and keep reconfigured entities on the owned device.
- Modify `custom_components/ha_ios_ancs/manifest.json`, `hacs.json`, `strings.json`, and `translations/{en,ko}.json`: user-facing rename and version `0.6.1`.
- Modify `README.md`, `README.en.md`, and release/documentation contracts: explain separate device ownership and stable repository name.
- Modify `tests/test_sensor.py`, `tests/test_binary_sensor.py`, `tests/test_event.py`, `tests/test_init.py`, `tests/test_config_flow.py`, and `tools/tests/test_documentation_contract.py`: lock device separation, migration, naming, and MQTT preservation.

### Task 1: Lock Separate Device Ownership At The Entity Layer

**Files:**
- Modify: `tests/test_sensor.py`
- Modify: `tests/test_binary_sensor.py`
- Modify: `tests/test_event.py`
- Modify: `custom_components/ha_ios_ancs/entity.py`
- Modify: `custom_components/ha_ios_ancs/runtime.py`

- [ ] **Step 1: Rewrite the source sensor ownership test to require two devices**

Replace the MQTT-attachment assertions with this contract:

```python
def test_source_sensors_use_separate_integration_device_without_mutating_mqtt(
    registry_hass, run
) -> None:
    hass = registry_hass
    registered = run(
        async_register_mqtt_ancs_source(
            hass, "ios_ancs_A1B2C3", device_name="Kitchen Relay"
        )
    )
    before = mqtt_registry_snapshot(hass)
    entry = source_entry()
    runtime = AncsSourceRuntime(
        hass, registered.entity.unique_id, "ios_ancs_A1B2C3"
    )
    run(runtime.async_start())

    _, entity_ids = run(
        async_setup_ancs_platform(
            hass,
            entry,
            runtime,
            sensor_component,
            ancs_sensor,
            sensor_component.DOMAIN,
        )
    )

    registry = entity_registry.async_get(hass)
    device_ids = {
        registry.async_get(entity_id).device_id
        for entity_id in entity_ids
        if registry.async_get(entity_id) is not None
    }
    assert len(device_ids) == 1
    companion_device_id = device_ids.pop()
    assert companion_device_id is not None
    assert companion_device_id != registered.device.id
    companion_device = device_registry.async_get(hass).async_get(
        companion_device_id
    )
    assert companion_device is not None
    assert companion_device.identifiers == {(DOMAIN, entry.entry_id)}
    assert companion_device.via_device_id is None
    assert len(device_registry.async_get(hass).devices) == 2
    assert mqtt_registry_snapshot(hass) == before
```

- [ ] **Step 2: Apply the same ownership contract to binary sensors and event**

For the binary sensor test, require the same separate device and unchanged MQTT
snapshot. Replace the event ownership test with:

```python
def test_source_event_uses_separate_integration_device(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    registered = run(
        async_register_mqtt_ancs_source(
            hass, "ios_ancs_A1B2C3", device_name="Kitchen Relay"
        )
    )
    runtime = RuntimeStub(
        available=True,
        unique_id="ios_ancs_A1B2C3:notification",
        device_entry=registered.device,
    )
    entry = make_source_entry()

    entity_id = run(setup_event_entity(hass, entry, runtime))
    registry_entry = entity_registry.async_get(hass).async_get(entity_id)
    assert registry_entry is not None
    assert registry_entry.device_id != registered.device.id
    companion_device = device_registry.async_get(hass).async_get(
        registry_entry.device_id
    )
    assert companion_device is not None
    assert companion_device.identifiers == {(DOMAIN, entry.entry_id)}
    assert companion_device.via_device_id is None
```

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```powershell
.\.venv314\Scripts\python.exe -m pytest `
  tests/test_sensor.py::test_source_sensors_use_separate_integration_device_without_mutating_mqtt `
  tests/test_binary_sensor.py::test_source_binary_sensors_use_separate_integration_device_without_mutating_mqtt `
  tests/test_event.py::test_source_event_uses_separate_integration_device -q
```

Expected: FAIL because source-backed entities still use the MQTT device ID.

- [ ] **Step 4: Make entities own their device**

Change `AncsNotificationEntity.__init__` to always set:

```python
self._attr_device_info = DeviceInfo(
    identifiers={(DOMAIN, entry.entry_id)},
    name=entry.title,
)
```

Remove `self.device_entry = runtime.device_entry` and the conditional foreign
device path. Remove `device_entry` from the runtime protocol and concrete
runtimes; remove source runtime's redundant stored device entry.

- [ ] **Step 5: Run focused platform tests and verify GREEN**

Run:

```powershell
.\.venv314\Scripts\python.exe -m pytest `
  tests/test_sensor.py tests/test_binary_sensor.py tests/test_event.py -q
```

Expected: all three modules pass and MQTT snapshots remain unchanged.

- [ ] **Step 6: Commit the entity ownership change**

Stage the five files and commit with a Lore message whose directive states that
`ha_ios_ancs` entities must never attach to an MQTT device ID.

### Task 2: Migrate Existing v0.6.0 Registry Entries Without Touching MQTT

**Files:**
- Create: `custom_components/ha_ios_ancs/device.py`
- Modify: `custom_components/ha_ios_ancs/__init__.py`
- Modify: `custom_components/ha_ios_ancs/config_flow.py`
- Modify: `tests/test_init.py`
- Modify: `tests/test_config_flow.py`

- [ ] **Step 1: Add a failing setup migration test**

Register an MQTT source, create representative event/title/error
`ha_ios_ancs` registry entries on the MQTT device, capture their registry ID,
entity ID, unique ID, disabled state and a complete MQTT registry snapshot,
call `async_setup_entry`, and assert:

```python
assert migrated_event.id == event_before.id
assert migrated_event.entity_id == event_before.entity_id
assert migrated_event.unique_id == event_before.unique_id
assert migrated_event.device_id == companion_device.id
assert migrated_title.device_id == companion_device.id
assert migrated_error.device_id == companion_device.id
assert companion_device.identifiers == {(DOMAIN, entry.entry_id)}
assert companion_device.via_device_id is None
assert mqtt_registry_snapshot(hass) == mqtt_before
```

Patch runtime startup and platform forwarding with `AsyncMock` so the test
isolates registry migration.

- [ ] **Step 2: Run the setup migration test and verify RED**

```powershell
.\.venv314\Scripts\python.exe -m pytest `
  tests/test_init.py::test_setup_entry_moves_only_companion_entities_to_owned_device -q
```

Expected: FAIL because setup does not create or migrate an owned device.

- [ ] **Step 3: Create the focused device module**

Create `custom_components/ha_ios_ancs/device.py`:

```python
"""Integration-owned device helpers for iOS ANCS."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo

from .const import CONF_BASE_TOPIC, CONF_MQTT_DEVICE_IDENTIFIER, DOMAIN


def entry_source_identity(entry: ConfigEntry) -> str:
    """Return the stable user-visible source identity."""
    value = entry.data.get(CONF_MQTT_DEVICE_IDENTIFIER)
    if not isinstance(value, str):
        value = entry.data.get(CONF_BASE_TOPIC)
    return value if isinstance(value, str) and value else entry.entry_id


def entry_title(entry: ConfigEntry) -> str:
    """Return the iOS ANCS config-entry and device title."""
    return f"iOS ANCS ({entry_source_identity(entry)})"


def device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return integration-owned device information."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry_title(entry),
    )


@callback
def async_ensure_integration_device(
    hass: HomeAssistant, entry: ConfigEntry
) -> dr.DeviceEntry:
    """Create the owned device and move only companion entities to it."""
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry_title(entry),
    )
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.platform == DOMAIN and entity.device_id != device.id:
            registry.async_update_entity(entity.entity_id, device_id=device.id)
    return device
```

Use `device_info(entry)` from `entity.py`. Call
`async_ensure_integration_device(hass, entry)` at the beginning of
`async_setup_entry`, before runtime startup and platform forwarding.

- [ ] **Step 4: Verify setup migration GREEN**

```powershell
.\.venv314\Scripts\python.exe -m pytest tests/test_init.py -q
```

Expected: setup tests pass, including the MQTT snapshot invariant.

- [ ] **Step 5: Rewrite reconfigure tests for a stable owned device**

Update legacy-conversion and existing-source reconfigure tests so the
integration device remains present and becomes the target for companion
entries. Snapshot all MQTT entries before reconfigure and assert the snapshot is
identical after reconfigure. The selected MQTT source's device ID must never
become a companion device ID.

- [ ] **Step 6: Change reconfigure migration to target the owned device**

In `config_flow.py`:

```python
owned_device = async_ensure_integration_device(self.hass, entry)
self._async_migrate_companion_entities(
    entry.entry_id,
    entry.unique_id or entry.entry_id,
    old_event_unique_id,
    source,
    owned_device.id,
)
```

Add `owned_device_id: str` to the migration helper and replace
`source.device_id` with `owned_device_id`. Delete
`_async_remove_orphan_legacy_device`; the integration device is required.

- [ ] **Step 7: Run reconfigure tests and verify GREEN**

```powershell
.\.venv314\Scripts\python.exe -m pytest tests/test_config_flow.py -q
```

Expected: unique IDs migrate as before, companion registry IDs remain stable,
and MQTT snapshots do not change.

- [ ] **Step 8: Commit registry migration**

Stage the device module, setup/config-flow code and migration tests. Use a Lore
message rejecting delete-and-recreate migration because it would break
dashboards and history.

### Task 3: Rename The Integration And Version The Migration

**Files:**
- Modify: `custom_components/ha_ios_ancs/__init__.py`
- Modify: `custom_components/ha_ios_ancs/config_flow.py`
- Modify: `custom_components/ha_ios_ancs/const.py`
- Modify: `custom_components/ha_ios_ancs/manifest.json`
- Modify: `hacs.json`
- Modify: `custom_components/ha_ios_ancs/strings.json`
- Modify: `custom_components/ha_ios_ancs/translations/en.json`
- Modify: `custom_components/ha_ios_ancs/translations/ko.json`
- Modify: `README.md`
- Modify: `README.en.md`
- Modify: `tests/test_config_flow.py`
- Modify: `tools/tests/test_documentation_contract.py`

- [ ] **Step 1: Add failing naming and migration tests**

Require:

```python
assert manifest["name"] == "iOS ANCS"
assert manifest["version"] == "0.6.1"
assert hacs["name"] == "iOS ANCS"
assert strings["title"] == "iOS ANCS"
assert en["title"] == "iOS ANCS"
assert ko["title"] == "iOS ANCS"
assert manifest["documentation"] == "https://github.com/1bobby-git/HA-iOS-ANCS"
```

Add a direct migration test:

```python
original_data = dict(entry.data)
assert run(async_migrate_entry(hass, entry)) is True
assert entry.version == 2
assert entry.title == "iOS ANCS (ios_ancs_A1B2C3)"
assert entry.data == original_data
assert entry.unique_id == "ios_ancs_A1B2C3"
```

- [ ] **Step 2: Run naming tests and verify RED**

```powershell
.\.venv314\Scripts\python.exe -m pytest `
  tests/test_config_flow.py tools/tests/test_documentation_contract.py -q
```

Expected: FAIL on old names, version, titles, and missing version-2 migration.

- [ ] **Step 3: Implement config-entry version migration**

Define `CONFIG_ENTRY_VERSION = 2` in `const.py`, set
`ConfigFlow.VERSION = CONFIG_ENTRY_VERSION`, and add:

```python
async def async_migrate_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Migrate an iOS ANCS config entry without changing its source."""
    if entry.version > CONFIG_ENTRY_VERSION:
        return False
    if entry.version < CONFIG_ENTRY_VERSION:
        hass.config_entries.async_update_entry(
            entry,
            title=entry_title(entry),
            version=CONFIG_ENTRY_VERSION,
        )
    return True
```

New config entries and successful reconfigure results use the same
`entry_title` rule.

- [ ] **Step 4: Rename surfaces and bump only companion version**

Change `HA iOS ANCS` to `iOS ANCS` in manifest, HACS metadata,
config-flow strings/translations and companion documentation. Keep all
`HA-iOS-ANCS` repository URLs unchanged. Set only the companion manifest to
`0.6.1`; firmware manifests remain `0.3.3`.

- [ ] **Step 5: Run naming and migration tests and verify GREEN**

```powershell
.\.venv314\Scripts\python.exe -m pytest `
  tests/test_config_flow.py tools/tests/test_documentation_contract.py -q
```

Expected: all tests pass and repository URL assertions remain unchanged.

- [ ] **Step 6: Commit naming and version changes**

Stage the naming, version, migration and documentation files. Use a Lore message
that rejects renaming the repository because existing HACS installations
depend on it.

### Task 4: Full Local And GitHub Verification

- [ ] **Step 1: Run the complete suite**

```powershell
.\.venv314\Scripts\python.exe -m pytest -q
```

Expected: all tests pass; total is greater than the v0.6.0 baseline of 266.

- [ ] **Step 2: Run static checks**

```powershell
.\.venv314\Scripts\python.exe -m compileall -q custom_components/ha_ios_ancs
git diff --check
git status --short
```

Expected: all checks exit zero and the worktree is clean after commits.

- [ ] **Step 3: Review the final commit range**

```powershell
git diff --stat 113697c..HEAD
git log --oneline 113697c..HEAD
```

Expected: design, plan, device separation, migration, and naming only; no
firmware binary or MQTT Discovery implementation changes.

- [ ] **Step 4: Push main and wait for validators**

```powershell
git push origin main
$validatorRun = gh run list --branch main --limit 1 `
  --json databaseId --jq '.[0].databaseId'
gh run watch $validatorRun --exit-status
```

Expected: HACS and Hassfest succeed for the pushed commit.

### Task 5: Publish v0.6.1 And Update The Live HACS Installation

- [ ] **Step 1: Create the GitHub release**

```powershell
$releaseSha = git rev-parse HEAD
gh release create v0.6.1 --target $releaseSha `
  --title "iOS ANCS v0.6.1" `
  --notes "Rename the companion integration to iOS ANCS and move its entities to a separate integration-owned device while preserving all MQTT entities and existing entity identities."
```

Expected: public non-prerelease `v0.6.1` targeting the pushed SHA.

- [ ] **Step 2: Capture the live pre-update registry snapshot**

For each source, record MQTT tuples
`(id, entity_id, unique_id, disabled_by, device_id)` and companion tuples with
the same fields. Hash sorted MQTT tuples with SHA-256. Record MQTT device IDs
and companion config-entry IDs.

- [ ] **Step 3: Install v0.6.1 through HACS and restart Home Assistant**

Use the authenticated HACS repository page, select `v0.6.1`, download, and
restart Home Assistant Core. Do not copy files directly into
`/config/custom_components`.

- [ ] **Step 4: Verify live device separation and migration**

For both configured sources, assert:

```text
integration name = iOS ANCS
owned device identifier = (ha_ios_ancs, config_entry_id)
owned device via_device = null
owned entity counts = sensor 25, binary_sensor 11, event 1
owned disabled count = 0
owned device ID != MQTT device ID
MQTT tuple SHA-256 = pre-update SHA-256
MQTT disabled count = 0
companion registry IDs/entity IDs/unique IDs = pre-update values
```

- [ ] **Step 5: Verify one real iPhone notification**

Subscribe read-only or compare relay counters, send one visible non-HA iPhone
notification, and verify without printing private content:

```text
accepted and published_ack increment
title sensor state length > 0
message sensor state length > 0
raw notification attribute count >= 29
collection complete = on
error present = off
event event_type = notification
all six entities belong to the separate iOS ANCS device
```

- [ ] **Step 6: Close out**

Verify logs contain no `ha_ios_ancs` error or traceback, run `ha core check`,
and report release URL, SHA, tests, Action results, registry hashes, entity
counts, and physical alert evidence.
