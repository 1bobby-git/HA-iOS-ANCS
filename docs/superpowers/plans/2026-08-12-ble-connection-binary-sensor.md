# iOS ANCS BLE Connection Binary Sensor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a companion-owned diagnostic BLE connectivity binary sensor that mirrors the configured MQTT device status entity without subscribing to MQTT directly or changing MQTT-owned registry objects.

**Architecture:** Resolve the MQTT Discovery `device_status` binary sensor from the configured MQTT device registry identity. Extend both runtime implementations with a nullable BLE state and push listener, then expose that state through one companion binary sensor using Home Assistant's connectivity device class. Missing, unknown, or unavailable source state maps to an unknown sensor state.

**Tech Stack:** Python 3.13+, Home Assistant custom integration APIs, entity/device registries, state-change event helpers, pytest, HACS custom repository release metadata.

---

## File structure

- Modify `custom_components/ha_ios_ancs/source.py`: resolve the MQTT-owned device-status entity by registry identity.
- Modify `custom_components/ha_ios_ancs/runtime.py`: derive, retain, and push nullable BLE connection state.
- Modify `custom_components/ha_ios_ancs/binary_sensor.py`: expose the companion-owned connectivity entity.
- Modify `custom_components/ha_ios_ancs/strings.json`: add the English fallback entity name.
- Modify `custom_components/ha_ios_ancs/translations/en.json`: add the English entity name.
- Modify `custom_components/ha_ios_ancs/translations/ko.json`: add the Korean entity name.
- Modify `custom_components/ha_ios_ancs/manifest.json`: release integration version `0.6.6`.
- Modify `README.md` and `README.en.md`: document the dedicated BLE connection diagnostic.
- Modify `tests/helpers.py`: register an MQTT device-status entity in registry-backed tests.
- Modify `tests/test_source.py`: verify safe status-entity resolution.
- Modify `tests/test_runtime.py`: verify BLE state derivation and updates.
- Modify `tests/test_binary_sensor.py`: verify entity contract, state updates, and registry ownership.
- Modify `tests/test_event.py`: update the companion binary-sensor count assertion.
- Modify `tests/test_config_flow.py`: update translation contract assertions.

### Task 1: Resolve the MQTT device-status entity

**Files:**
- Modify: `custom_components/ha_ios_ancs/source.py`
- Modify: `tests/helpers.py`
- Test: `tests/test_source.py`

- [ ] **Step 1: Write the failing status-resolution tests**

Add tests that register a `binary_sensor` with unique ID
`ios_ancs_A1B2C3_device_status` on the MQTT source device and verify exact
resolution. Also register a same-named entity on a different device and verify
it is rejected.

```python
def test_resolve_status_entity_on_configured_mqtt_device(registry_hass, run) -> None:
    hass = registry_hass
    registered = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_A1B2C3",
            device_name="Kitchen Relay",
        )
    )
    status = run(async_register_mqtt_ancs_status(hass, registered))

    assert async_resolve_ancs_status_entity(
        hass,
        "ios_ancs_A1B2C3",
    ) == status.entity_id


def test_resolve_status_entity_rejects_foreign_mqtt_device(registry_hass, run) -> None:
    hass = registry_hass
    configured = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_A1B2C3",
            device_name="Kitchen Relay",
        )
    )
    foreign = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_D4E5F6",
            device_name="Office Relay",
        )
    )
    run(
        async_register_mqtt_ancs_status(
            hass,
            foreign,
            entity_unique_id="ios_ancs_A1B2C3_device_status",
        )
    )

    assert async_resolve_ancs_status_entity(
        hass,
        "ios_ancs_A1B2C3",
    ) is None
    assert configured.device.id != foreign.device.id
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_source.py -q
```

Expected: collection or assertion failure because
`async_resolve_ancs_status_entity` and `async_register_mqtt_ancs_status` do not
exist.

- [ ] **Step 3: Add the test registration helper**

Add this helper to `tests/helpers.py`:

```python
async def async_register_mqtt_ancs_status(
    hass: HomeAssistant,
    registered: RegisteredMqttSource,
    *,
    entity_unique_id: str | None = None,
) -> er.RegistryEntry:
    return er.async_get(hass).async_get_or_create(
        Platform.BINARY_SENSOR,
        "mqtt",
        entity_unique_id
        or f"{next(
            value
            for domain, value in registered.device.identifiers
            if domain == "mqtt"
        )}_device_status",
        config_entry=registered.config_entry,
        device_id=registered.device.id,
        suggested_object_id="device_status",
    )
```

- [ ] **Step 4: Add the registry resolver**

Add this callback to `custom_components/ha_ios_ancs/source.py`:

```python
@callback
def async_resolve_ancs_status_entity(
    hass: HomeAssistant,
    mqtt_device_identifier: str,
) -> str | None:
    """Resolve the MQTT device-status entity for one configured device."""

    entity_registry = er.async_get(hass)
    expected_unique_id = f"{mqtt_device_identifier}_device_status"
    for entity_entry in entity_registry.entities.values():
        if (
            entity_entry.domain != Platform.BINARY_SENSOR
            or entity_entry.platform != MQTT_DOMAIN
            or entity_entry.unique_id != expected_unique_id
            or entity_entry.device_id is None
        ):
            continue
        device_entry = dr.async_get(hass).async_get(entity_entry.device_id)
        if (
            device_entry is not None
            and (MQTT_DOMAIN, mqtt_device_identifier) in device_entry.identifiers
        ):
            return entity_entry.entity_id
    return None
```

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_source.py -q
```

Expected: all `tests/test_source.py` tests pass.

- [ ] **Step 6: Commit the resolver**

```powershell
git add custom_components/ha_ios_ancs/source.py tests/helpers.py tests/test_source.py
git commit -m "Resolve BLE status from the configured MQTT device"
```

Use Lore trailers describing the registry ownership constraint and focused test result.

### Task 2: Track BLE connection state in the runtime

**Files:**
- Modify: `custom_components/ha_ios_ancs/runtime.py`
- Test: `tests/test_runtime.py`

- [ ] **Step 1: Write failing runtime tests**

Add one test for initial state and transitions and one test for malformed or
unavailable status values:

```python
def test_source_runtime_tracks_ble_connection_status(registry_hass, run) -> None:
    hass = registry_hass
    registered = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_A1B2C3",
            device_name="Kitchen Relay",
        )
    )
    status = run(async_register_mqtt_ancs_status(hass, registered))
    hass.states.async_set(status.entity_id, "off", {"ble_connected": False})
    runtime, _, _ = run(async_make_source_runtime(hass, registered))
    observed: list[bool | None] = []
    remove = runtime.async_add_ble_connection_listener(observed.append)

    assert runtime.ble_connected is False
    hass.states.async_set(status.entity_id, "on", {"ble_connected": True})
    run(hass.async_block_till_done())
    assert runtime.ble_connected is True
    assert observed == [True]

    remove()
    run(runtime.async_stop())


def test_source_runtime_maps_unusable_ble_status_to_unknown(registry_hass, run) -> None:
    hass = registry_hass
    registered = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_A1B2C3",
            device_name="Kitchen Relay",
        )
    )
    status = run(async_register_mqtt_ancs_status(hass, registered))
    hass.states.async_set(status.entity_id, "on", {"ble_connected": "true"})
    runtime, _, _ = run(async_make_source_runtime(hass, registered))

    assert runtime.ble_connected is None
    hass.states.async_set(status.entity_id, STATE_UNAVAILABLE)
    run(hass.async_block_till_done())
    assert runtime.ble_connected is None

    run(runtime.async_stop())
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_runtime.py -q
```

Expected: failure because the runtime has no `ble_connected` property or BLE
listener API.

- [ ] **Step 3: Extend the runtime contract**

Add the listener type and protocol surface:

```python
type BleConnectionListener = Callable[[bool | None], None]


class AncsRuntime(Protocol):
    @property
    def ble_connected(self) -> bool | None:
        """Return the current iPhone BLE link state."""
        raise NotImplementedError

    def async_add_ble_connection_listener(
        self,
        listener: BleConnectionListener,
    ) -> CALLBACK_TYPE:
        """Add a BLE connection listener."""
        raise NotImplementedError
```

Both runtime classes receive `_ble_connected: bool | None = None` and a
`_ble_connection_listeners` list. The legacy `AncsMqttRuntime` keeps the value
unknown and supports listener registration/removal so legacy config entries
remain loadable.

- [ ] **Step 4: Track the source runtime's status entity**

Import `async_resolve_ancs_status_entity`, resolve it in
`AncsSourceRuntime.async_start`, seed the value, and track changes:

```python
@staticmethod
def _ble_connection_from_state(state: State | None) -> bool | None:
    if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return None
    value = state.attributes.get("ble_connected")
    return value if isinstance(value, bool) else None

@callback
def _handle_status_state_change(
    self,
    event: Event[EventStateChangedData],
) -> None:
    self._set_ble_connected(
        self._ble_connection_from_state(event.data["new_state"])
    )

@callback
def _set_ble_connected(self, connected: bool | None) -> None:
    if self._ble_connected is connected:
        return
    self._ble_connected = connected
    for listener in tuple(self._ble_connection_listeners):
        listener(connected)
```

Store the status unsubscribe callback separately, remove it in
`async_stop`, clear BLE listeners, and reset `_ble_connected` to `None`.

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_runtime.py -q
```

Expected: all runtime tests pass with no warnings.

- [ ] **Step 6: Commit runtime tracking**

```powershell
git add custom_components/ha_ios_ancs/runtime.py tests/test_runtime.py
git commit -m "Track the iPhone BLE link through Home Assistant state"
```

Use Lore trailers identifying that the companion observes HA state rather than MQTT topics.

### Task 3: Expose the companion BLE connectivity entity

**Files:**
- Modify: `custom_components/ha_ios_ancs/binary_sensor.py`
- Modify: `custom_components/ha_ios_ancs/strings.json`
- Modify: `custom_components/ha_ios_ancs/translations/en.json`
- Modify: `custom_components/ha_ios_ancs/translations/ko.json`
- Test: `tests/test_binary_sensor.py`
- Test: `tests/test_event.py`
- Test: `tests/test_config_flow.py`

- [ ] **Step 1: Write failing entity tests**

Update the expected key set with `ble_connected`, then add an end-to-end entity
test:

```python
def test_ble_connection_binary_sensor_tracks_status_on_companion_device(
    registry_hass,
    run,
) -> None:
    hass = registry_hass
    registered = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_A1B2C3",
            device_name="Kitchen Relay",
        )
    )
    status = run(async_register_mqtt_ancs_status(hass, registered))
    hass.states.async_set(status.entity_id, "off", {"ble_connected": False})
    before = mqtt_registry_snapshot(hass)
    entry = source_entry()
    runtime = AncsSourceRuntime(
        hass,
        registered.entity.unique_id,
        "ios_ancs_A1B2C3",
    )
    run(runtime.async_start())
    _, entity_ids = run(
        async_setup_ancs_platform(
            hass,
            entry,
            runtime,
            binary_sensor_component,
            ancs_binary_sensor,
            binary_sensor_component.DOMAIN,
        )
    )
    ble_entity_id = next(
        entity_id
        for entity_id in entity_ids
        if er.async_get(hass).async_get(entity_id).unique_id
        == "ios_ancs_A1B2C3:binary_sensor:ble_connected"
    )

    assert hass.states[ble_entity_id].state == "off"
    hass.states.async_set(status.entity_id, "on", {"ble_connected": True})
    run(hass.async_block_till_done())
    assert hass.states[ble_entity_id].state == "on"
    assert mqtt_registry_snapshot(hass) == before

    run(binary_sensor_component.async_unload_entry(hass, entry))
    run(runtime.async_stop())
```

Update the binary-sensor count in `tests/test_event.py` from 12 to 13 and add
translation assertions for `ble_connected` in `tests/test_config_flow.py`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_binary_sensor.py tests/test_event.py tests/test_config_flow.py -q
```

Expected: failures because no `ble_connected` companion entity or translation exists.

- [ ] **Step 3: Implement the BLE binary sensor**

Add one non-notification entity and include it in `async_setup_entry`:

```python
class AncsBleConnectionBinarySensor(BinarySensorEntity):
    """Expose the current iPhone BLE connection from the source runtime."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "ble_connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry, runtime: AncsRuntime) -> None:
        identity = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{identity}:binary_sensor:ble_connected"
        self._attr_device_info = device_info(entry)
        self._runtime = runtime

    @property
    def is_on(self) -> bool | None:
        return self._runtime.ble_connected

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self._runtime.async_add_ble_connection_listener(
                self._handle_ble_connection
            )
        )

    @callback
    def _handle_ble_connection(self, connected: bool | None) -> None:
        self.async_write_ha_state()
```

Change setup to create all existing notification entities plus exactly one
`AncsBleConnectionBinarySensor`.

- [ ] **Step 4: Add translations**

Add this entry under `entity.binary_sensor` in the fallback and English files:

```json
"ble_connected": {"name": "BLE connection"}
```

Add this entry to the UTF-8 Korean translation file:

```json
"ble_connected": {"name": "BLE 연결"}
```

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_binary_sensor.py tests/test_event.py tests/test_config_flow.py -q
```

Expected: all focused tests pass and the MQTT registry snapshot is unchanged.

- [ ] **Step 6: Commit the entity**

```powershell
git add custom_components/ha_ios_ancs/binary_sensor.py custom_components/ha_ios_ancs/strings.json custom_components/ha_ios_ancs/translations/en.json custom_components/ha_ios_ancs/translations/ko.json tests/test_binary_sensor.py tests/test_event.py tests/test_config_flow.py
git commit -m "Show the iPhone BLE link on the iOS ANCS device"
```

Use Lore trailers recording connectivity semantics and targeted test proof.

### Task 4: Release, deploy, and verify version 0.6.6

**Files:**
- Modify: `custom_components/ha_ios_ancs/manifest.json`
- Modify: `README.md`
- Modify: `README.en.md`

- [ ] **Step 1: Write failing release-contract assertions**

Add assertions to `tests/test_config_flow.py` that the manifest version is
`0.6.6` and both READMEs name the dedicated BLE connection sensor:

```python
def test_release_documents_ble_connection_sensor() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads(
        (root / "custom_components/ha_ios_ancs/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["version"] == "0.6.6"
    assert "BLE 연결" in (root / "README.md").read_text(encoding="utf-8")
    assert "BLE connection" in (root / "README.en.md").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the release-contract test and verify RED**

Run:

```powershell
python -m pytest tests/test_config_flow.py::test_release_documents_ble_connection_sensor -q
```

Expected: failure because the current manifest is `0.6.5` and the sensor is undocumented.

- [ ] **Step 3: Update release metadata and documentation**

Set the manifest version to `0.6.6`. In both READMEs, document that the HACS
companion device exposes a diagnostic BLE connection binary sensor derived from
the MQTT device-status entity, that MQTT entities remain enabled, and that no
firmware reflash is needed.

- [ ] **Step 4: Run the release-contract test and verify GREEN**

Run:

```powershell
python -m pytest tests/test_config_flow.py::test_release_documents_ble_connection_sensor -q
```

Expected: pass.

- [ ] **Step 5: Run all local verification**

Run:

```powershell
python -m pytest tests -q
python -m pytest tools/tests -q
python -m compileall -q custom_components/ha_ios_ancs
git diff --check
```

Expected: both suites pass, compileall emits no output, and `git diff --check`
returns exit code 0.

- [ ] **Step 6: Commit the release**

```powershell
git add custom_components/ha_ios_ancs/manifest.json README.md README.en.md tests/test_config_flow.py
git commit -m "Release BLE connection visibility through HACS"
```

Use Lore trailers listing both test suites and the remaining physical pairing verification.

- [ ] **Step 7: Back up and deploy the integration to Home Assistant**

Create a recoverable backup inside the Home Assistant container:

```powershell
ssh pve-new-ts "qm guest exec 100 -- docker exec homeassistant cp -a /config/custom_components/ha_ios_ancs /config/custom_components/ha_ios_ancs.bak-0.6.5"
```

Stream the updated component through the guest agent:

```powershell
tar -C custom_components -czf - ha_ios_ancs | ssh pve-new-ts "qm guest exec 100 --pass-stdin -- docker exec -i homeassistant tar -xzf - -C /config/custom_components"
```

- [ ] **Step 8: Validate and restart Home Assistant**

Run:

```powershell
ssh pve-new-ts "qm guest exec 100 -- ha core check"
ssh pve-new-ts "qm guest exec 100 -- ha core restart"
```

Expected: config check succeeds; after restart, `/api/` returns HTTP 200 and
Home Assistant logs contain no `ha_ios_ancs` setup error.

- [ ] **Step 9: Verify the live entity and MQTT ownership**

Query Home Assistant state and registries. First resolve the actual entity ID by
the stable unique ID `ios_ancs_c6_ab12:binary_sensor:ble_connected`; do not infer
the entity ID from translated names. Expected live assertions:

```text
the registry entry with unique ID ios_ancs_c6_ab12:binary_sensor:ble_connected exists
its resolved entity ID has a current state
device_class == connectivity
entity_category == diagnostic
state == off while firmware state has ble_connected:false
state == on after iPhone pairing yields ble_connected:true
MQTT device and all pre-existing MQTT entities remain registered and enabled
```

Send one fresh non-Home-Assistant iPhone notification after pairing and confirm
the MQTT notification sensor, companion event/title/message/app-name entities,
and relay automation all advance once.

- [ ] **Step 10: Publish the HACS release**

```powershell
git push origin main
git tag v0.6.6
git push origin v0.6.6
gh release create v0.6.6 --title "iOS ANCS 0.6.6" --notes "Adds a companion BLE connection diagnostic without changing or disabling MQTT entities."
```

Expected: GitHub main includes all commits, tag `v0.6.6` exists, and the release
is visible to HACS custom-repository users.
