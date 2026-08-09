# Dedicated HA iOS ANCS Notification Entities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose every accepted ANCS MQTT notification field as purpose-specific companion sensors and binary sensors while preserving the event entity, the complete raw payload, and all existing MQTT entities.

**Architecture:** Extend the existing runtime with an immutable latest-notification snapshot and listener replay control. Add shared push-entity behavior, then build sensor and binary-sensor platforms that derive values from the same cached payload and attach to the already resolved MQTT device. Keep the event entity as the automation signal and retain the entire JSON object on a diagnostic raw sensor.

**Tech Stack:** Python 3.14, Home Assistant Core 2026.8 entity APIs, MQTT Discovery source entities, pytest, HACS validation, Hassfest.

---

## File Structure

- Modify `custom_components/ha_ios_ancs/runtime.py`: cache the latest accepted payload, return defensive copies, and let non-event listeners avoid consuming the pending event replay queue.
- Create `custom_components/ha_ios_ancs/entity.py`: shared entity lifecycle, device attachment, availability, snapshot handling, and type-safe payload extractors.
- Create `custom_components/ha_ios_ancs/sensor.py`: sensor descriptions and the raw-payload sensor.
- Create `custom_components/ha_ios_ancs/binary_sensor.py`: boolean and nested boolean entity descriptions.
- Modify `custom_components/ha_ios_ancs/event.py`: reuse shared entity behavior while preserving the existing event unique ID and pending-event replay.
- Modify `custom_components/ha_ios_ancs/__init__.py`: forward and unload sensor, binary-sensor, and event platforms.
- Modify `custom_components/ha_ios_ancs/strings.json`, `translations/en.json`, and `translations/ko.json`: add stable names for every new entity.
- Modify `tests/test_runtime.py`: lock runtime snapshot and replay behavior.
- Create `tests/test_entity.py`: lock extractor, text-limit, raw-copy, common device, and availability behavior.
- Create `tests/test_sensor.py`: lock the complete sensor contract.
- Create `tests/test_binary_sensor.py`: lock boolean and nested-field behavior.
- Modify `tests/test_event.py`, `tests/test_init.py`, and `tests/test_config_flow.py`: update platform lists, shared-base behavior, translations, and version expectations.
- Modify `custom_components/ha_ios_ancs/manifest.json`, `tools/tests/test_documentation_contract.py`, `README.md`, and `README.en.md`: document and release version `0.6.0`.

### Task 1: Add a lossless runtime snapshot and event-only pending replay

**Files:**
- Modify: `tests/test_runtime.py`
- Modify: `custom_components/ha_ios_ancs/runtime.py`

- [ ] **Step 1: Write failing direct-MQTT runtime tests**

Add tests that prove a non-event listener cannot drain an early pending notification and that every snapshot access returns a defensive copy:

```python
def test_runtime_snapshot_preserves_pending_event_for_event_listener(
    hass: HomeAssistant, run
) -> None:
    runtime, subscriptions, _ = run(start_runtime_with_subscribe_patch(hass))
    _, callback, _ = subscriptions[0]
    callback(
        mqtt_message(
            "ios_ancs/notification",
            notification_payload(
                relay_id="relay-before-platforms",
                title="Original title",
            ),
        )
    )

    detail_updates: list[dict[str, Any]] = []
    runtime.async_add_notification_listener(
        detail_updates.append,
        replay_pending=False,
    )
    assert detail_updates == []

    snapshot = runtime.latest_notification
    assert snapshot is not None
    assert snapshot["relay_id"] == "relay-before-platforms"
    snapshot["title"] = "Mutated by consumer"
    assert runtime.latest_notification["title"] == "Original title"

    event_updates: list[dict[str, Any]] = []
    runtime.async_add_notification_listener(event_updates.append)
    assert [item["relay_id"] for item in event_updates] == [
        "relay-before-platforms"
    ]
    run(runtime.async_stop())
```

Add a second assertion to an existing stop test:

```python
assert runtime.latest_notification is None
```

- [ ] **Step 2: Run the direct-MQTT tests and verify RED**

Run:

```powershell
.\.venv314\Scripts\python.exe -m pytest tests/test_runtime.py -k "snapshot or pending" -q
```

Expected: failure because `latest_notification` and `replay_pending` do not exist.

- [ ] **Step 3: Write failing source-runtime seed tests**

Add a test that sets a valid aggregate source state before `async_start()` and proves the runtime caches it without re-emitting it as a new event:

```python
def test_source_runtime_seeds_snapshot_without_replaying_current_state(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    registered = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_A1B2C3",
            device_name="Kitchen Relay",
        )
    )
    payload = firmware_notification(relay_id="seed-relay", title="Seed title")
    hass.states.async_set(
        registered.entity.entity_id,
        payload["relay_id"],
        payload,
    )

    runtime = AncsSourceRuntime(
        hass,
        registered.entity.unique_id,
        "ios_ancs_A1B2C3",
    )
    events: list[dict[str, Any]] = []
    runtime.async_add_notification_listener(events.append)
    run(runtime.async_start())

    assert events == []
    assert runtime.latest_notification == payload
    run(runtime.async_stop())
```

- [ ] **Step 4: Run the source-runtime test and verify RED**

Run:

```powershell
.\.venv314\Scripts\python.exe -m pytest tests/test_runtime.py::test_source_runtime_seeds_snapshot_without_replaying_current_state -q
```

Expected: failure because the current source state only seeds deduplication.

- [ ] **Step 5: Implement the minimal runtime contract**

In `runtime.py`, import `deepcopy`, extend the protocol, and add the same snapshot/replay behavior to both runtime implementations:

```python
from copy import deepcopy

class AncsRuntime(Protocol):
    @property
    def latest_notification(self) -> dict[str, Any] | None:
        """Return a defensive copy of the latest accepted notification."""
        raise NotImplementedError

    def async_add_notification_listener(
        self,
        listener: NotificationListener,
        *,
        replay_pending: bool = True,
    ) -> CALLBACK_TYPE:
        """Add a listener, optionally replaying queued event notifications."""
        raise NotImplementedError
```

Initialize and expose the snapshot in both runtimes:

```python
self._latest_notification: dict[str, Any] | None = None

@property
def latest_notification(self) -> dict[str, Any] | None:
    return (
        None
        if self._latest_notification is None
        else deepcopy(self._latest_notification)
    )
```

Only drain the pending queue when requested:

```python
def async_add_notification_listener(
    self,
    listener: NotificationListener,
    *,
    replay_pending: bool = True,
) -> CALLBACK_TYPE:
    self._notification_listeners.append(listener)
    if replay_pending:
        while self._pending_notifications:
            listener(deepcopy(self._pending_notifications.popleft()))
    ...
```

Store before queueing or dispatching and isolate listeners from one another:

```python
self._latest_notification = deepcopy(notification)
if not self._notification_listeners:
    self._pending_notifications.append(deepcopy(notification))
    return
for listener in tuple(self._notification_listeners):
    listener(deepcopy(notification))
```

For a valid current source state, cache the accepted value without dispatching:

```python
seed = parse_notification_data(
    self._notification_data_from_state(current_state),
    self._seen,
)
if seed is not None:
    self._latest_notification = deepcopy(seed)
```

Clear `_latest_notification` in both `async_stop()` methods.

- [ ] **Step 6: Run runtime tests and verify GREEN**

Run:

```powershell
.\.venv314\Scripts\python.exe -m pytest tests/test_runtime.py -q
```

Expected: all runtime tests pass.

- [ ] **Step 7: Commit the runtime slice**

```powershell
git add custom_components/ha_ios_ancs/runtime.py tests/test_runtime.py
git commit -m "Preserve one coherent ANCS notification snapshot" -m "Constraint: Detail platforms must not consume the event replay queue`nRejected: Independent pending queues per entity | they multiply payload storage and delivery state`nConfidence: high`nScope-risk: narrow`nDirective: Keep event replay opt-in and return defensive snapshot copies`nTested: tests/test_runtime.py`nNot-tested: Entity platforms are added in later tasks"
```

### Task 2: Add shared typed extraction and entity lifecycle behavior

**Files:**
- Create: `custom_components/ha_ios_ancs/entity.py`
- Create: `tests/test_entity.py`

- [ ] **Step 1: Write failing extractor tests**

Create `tests/test_entity.py` with exact behavioral cases:

```python
from custom_components.ha_ios_ancs.entity import (
    MAX_STATE_TEXT_LENGTH,
    as_boolean,
    as_integer,
    as_text,
    nested_value,
    preview_text,
    raw_payload_attributes,
)

def test_extractors_reject_bool_as_integer_and_truthy_non_booleans() -> None:
    payload = {"count": 3, "wrong_count": True, "flag": False, "wrong_flag": 1}
    assert as_integer(nested_value(payload, ("count",))) == 3
    assert as_integer(nested_value(payload, ("wrong_count",))) is None
    assert as_boolean(nested_value(payload, ("flag",))) is False
    assert as_boolean(nested_value(payload, ("wrong_flag",))) is None

def test_nested_and_text_helpers_preserve_source_payload() -> None:
    long_message = "x" * 4096
    payload = {
        "message": long_message,
        "truncated": {"message": True},
    }
    assert nested_value(payload, ("truncated", "message")) is True
    assert nested_value(payload, ("error", "code")) is None
    assert as_text(payload["message"]) == long_message
    assert preview_text(long_message) == long_message[:MAX_STATE_TEXT_LENGTH]

    attributes = raw_payload_attributes(payload)
    attributes["truncated"]["message"] = False
    assert payload["truncated"]["message"] is True
```

- [ ] **Step 2: Run extractor tests and verify RED**

Run:

```powershell
.\.venv314\Scripts\python.exe -m pytest tests/test_entity.py -q
```

Expected: import failure because `entity.py` does not exist.

- [ ] **Step 3: Implement extractors and common push lifecycle**

Create `entity.py` with these public helpers and the shared mixin:

```python
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .runtime import AncsRuntime

MAX_STATE_TEXT_LENGTH = 255

def nested_value(payload: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = payload
    for key in path:
        if not isinstance(value, Mapping) or key not in value:
            return None
        value = value[key]
    return value

def as_text(value: Any) -> str | None:
    return value if isinstance(value, str) else None

def as_integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None

def as_boolean(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None

def preview_text(value: str) -> str:
    return value[:MAX_STATE_TEXT_LENGTH]

def raw_payload_attributes(payload: Mapping[str, Any]) -> dict[str, Any]:
    return deepcopy(dict(payload))

class AncsNotificationEntity:
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        entry: ConfigEntry,
        runtime: AncsRuntime,
        platform: Platform,
        key: str,
        *,
        unique_id: str | None = None,
        replay_pending: bool = False,
    ) -> None:
        identity = entry.unique_id or entry.entry_id
        self._attr_unique_id = unique_id or f"{identity}:{platform.value}:{key}"
        self._runtime = runtime
        self._payload = runtime.latest_notification
        self._replay_pending = replay_pending
        self.device_entry = runtime.device_entry
        if self.device_entry is None:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, entry.entry_id)},
                name=entry.title,
            )
        self._attr_available = runtime.available is not False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self._runtime.async_add_notification_listener(
                self._handle_notification,
                replay_pending=self._replay_pending,
            )
        )
        self.async_on_remove(
            self._runtime.async_add_availability_listener(
                self._handle_availability
            )
        )

    @callback
    def _handle_notification(self, payload: dict[str, Any]) -> None:
        self._payload = deepcopy(payload)
        self.async_write_ha_state()

    @callback
    def _handle_availability(self, available: bool | None) -> None:
        if available is None:
            return
        self._attr_available = available
        self.async_write_ha_state()
```

If static typing rejects the cooperative `super()` call in this mixin, annotate only that call with the narrow type-ignore required by the installed Home Assistant typing; do not duplicate lifecycle logic across three platforms.

- [ ] **Step 4: Run extractor tests and byte compilation**

Run:

```powershell
.\.venv314\Scripts\python.exe -m pytest tests/test_entity.py -q
.\.venv314\Scripts\python.exe -m py_compile custom_components/ha_ios_ancs/entity.py
```

Expected: all extractor tests pass and compilation exits zero.

- [ ] **Step 5: Commit the shared-entity slice**

```powershell
git add custom_components/ha_ios_ancs/entity.py tests/test_entity.py
git commit -m "Define typed ANCS entity state extraction" -m "Constraint: Home Assistant states are limited to 255 characters and JSON booleans must not be coerced`nRejected: Per-platform extraction copies | they would drift across the same payload contract`nConfidence: high`nScope-risk: narrow`nDirective: Keep raw attributes defensive and all entity properties memory-only`nTested: tests/test_entity.py and py_compile`nNot-tested: Sensor and binary-sensor registration follows"
```

### Task 3: Add the complete sensor platform

**Files:**
- Create: `custom_components/ha_ios_ancs/sensor.py`
- Create: `tests/test_sensor.py`

- [ ] **Step 1: Write failing sensor-contract tests**

Create tests that instantiate every description and assert the exact key set:

```python
EXPECTED_SENSOR_KEYS = {
    "app_name", "app_id", "title", "subtitle", "message", "event",
    "category", "date", "uid", "session_id", "event_id",
    "event_flags", "category_id", "category_count", "message_size",
    "schema_version", "relay_id", "target", "source", "device_name",
    "received_at_ms", "published_at_ms", "error_code", "error_name",
    "raw_notification",
}

def test_sensor_descriptions_cover_complete_contract() -> None:
    assert {description.key for description in SENSOR_DESCRIPTIONS} == (
        EXPECTED_SENSOR_KEYS
    )
```

Add value tests using a complete payload whose `app_name` is absent, whose message exceeds 255 characters, whose `message_size` is decimal text, and whose `error` is null. Assert:

```python
assert states["app_name"] == payload["app_id"]
assert states["message"] == payload["message"][:255]
assert attributes["message"]["full_value"] == payload["message"]
assert states["message_size"] == 4096
assert states["error_code"] is None
assert states["error_name"] is None
assert attributes["raw_notification"] == payload
```

Include an unknown future field in `payload` and assert it survives unchanged in `attributes["raw_notification"]`. Seed the runtime snapshot before platform setup and assert every sensor starts from that snapshot without requiring a new notification. Add a second payload with `error={"code": -10, "name": "timeout"}` and assert the two error sensors update.

- [ ] **Step 2: Run sensor tests and verify RED**

Run:

```powershell
.\.venv314\Scripts\python.exe -m pytest tests/test_sensor.py -q
```

Expected: import failure because `sensor.py` does not exist.

- [ ] **Step 3: Implement sensor descriptions and entity state**

Create a frozen description type with explicit extraction kind:

```python
from dataclasses import dataclass
from enum import StrEnum

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import EntityCategory, Platform, UnitOfTime

class SensorValueKind(StrEnum):
    TEXT = "text"
    INTEGER = "integer"
    DECIMAL_TEXT = "decimal_text"
    RAW = "raw"

@dataclass(frozen=True, kw_only=True)
class AncsSensorEntityDescription(SensorEntityDescription):
    path: tuple[str, ...]
    kind: SensorValueKind
    fallback_path: tuple[str, ...] | None = None
    preserve_full_text: bool = False
```

Define all 25 descriptions. Use `SensorDeviceClass.ENUM` with these explicit options:

```python
EVENT_OPTIONS = ["added", "modified", "removed"]
CATEGORY_OPTIONS = [
    "other", "incoming_call", "missed_call", "voicemail", "social",
    "schedule", "email", "news", "health_and_fitness",
    "business_and_finance", "location", "entertainment", "reserved",
]
```

Use `EntityCategory.DIAGNOSTIC` for schema, IDs, raw flags, source metadata, uptime markers, errors, and raw notification. Set `native_unit_of_measurement=UnitOfTime.MILLISECONDS` on both uptime-marker sensors without assigning a timestamp device class.

The description table must contain these exact path/kind relationships:

```python
SENSOR_FIELD_SPECS = {
    "app_name": (("app_name",), "text", ("app_id",), True),
    "app_id": (("app_id",), "text", None, True),
    "title": (("title",), "text", None, True),
    "subtitle": (("subtitle",), "text", None, True),
    "message": (("message",), "text", None, True),
    "event": (("event",), "text", None, False),
    "category": (("category",), "text", None, False),
    "date": (("date",), "text", None, False),
    "uid": (("uid",), "integer", None, False),
    "session_id": (("session_id",), "integer", None, False),
    "event_id": (("event_id",), "integer", None, False),
    "event_flags": (("event_flags",), "integer", None, False),
    "category_id": (("category_id",), "integer", None, False),
    "category_count": (("category_count",), "integer", None, False),
    "message_size": (("message_size",), "decimal_text", None, False),
    "schema_version": (("schema_version",), "integer", None, False),
    "relay_id": (("relay_id",), "text", None, False),
    "target": (("target",), "text", None, False),
    "source": (("source",), "text", None, False),
    "device_name": (("device_name",), "text", None, True),
    "received_at_ms": (("received_at_ms",), "integer", None, False),
    "published_at_ms": (("published_at_ms",), "integer", None, False),
    "error_code": (("error", "code"), "integer", None, False),
    "error_name": (("error", "name"), "text", None, False),
    "raw_notification": (("relay_id",), "raw", None, False),
}
```

Implement `AncsNotificationSensor(AncsNotificationEntity, SensorEntity)` so `native_value` uses strict extractors, `DECIMAL_TEXT` accepts only an optional leading minus plus decimal digits, and `RAW` uses relay ID as state. A text fallback is used when the primary value is missing or is the empty string, so an empty or missing `app_name` resolves to `app_id`. `extra_state_attributes` returns the entire defensive payload for `RAW`, and returns `{"full_value": full_text}` only when a preserved text value exceeds 255 characters.

Implement platform setup:

```python
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    runtime: AncsRuntime = entry.runtime_data
    async_add_entities(
        AncsNotificationSensor(entry, runtime, description)
        for description in SENSOR_DESCRIPTIONS
    )
```

- [ ] **Step 4: Run sensor tests and verify GREEN**

Run:

```powershell
.\.venv314\Scripts\python.exe -m pytest tests/test_sensor.py tests/test_entity.py -q
```

Expected: all sensor and extractor tests pass.

- [ ] **Step 5: Commit the sensor platform**

```powershell
git add custom_components/ha_ios_ancs/sensor.py tests/test_sensor.py
git commit -m "Expose complete ANCS notification sensor details" -m "Constraint: Full notification text must survive Home Assistant's state-length limit`nRejected: Summary-only sensors | they omit accepted MQTT fields`nConfidence: high`nScope-risk: moderate`nDirective: Keep the raw notification sensor lossless and uptime markers non-timestamp`nTested: tests/test_sensor.py and tests/test_entity.py`nNot-tested: Platform forwarding and live registration follow"
```

### Task 4: Add the binary-sensor platform

**Files:**
- Create: `custom_components/ha_ios_ancs/binary_sensor.py`
- Create: `tests/test_binary_sensor.py`

- [ ] **Step 1: Write failing binary-sensor tests**

Create tests for the exact key set and strict boolean behavior:

```python
EXPECTED_BINARY_SENSOR_KEYS = {
    "complete", "silent", "important", "pre_existing",
    "positive_action_available", "negative_action_available",
    "app_id_truncated", "title_truncated", "subtitle_truncated",
    "message_truncated", "has_error",
}

def test_binary_descriptions_cover_boolean_contract() -> None:
    assert {description.key for description in BINARY_SENSOR_DESCRIPTIONS} == (
        EXPECTED_BINARY_SENSOR_KEYS
    )
```

Use a payload containing nested `truncated` flags and `error=None`. Assert literal booleans map exactly, `has_error` is false, missing keys are unknown, and integer `1` does not become true. Then update with an error object and assert `has_error` becomes true.

Also pass malformed nested values such as `truncated="invalid"` and `error="invalid"`. Truncation sensors must become unknown without raising, while `has_error` remains true because the error field is present and non-null.

- [ ] **Step 2: Run binary-sensor tests and verify RED**

Run:

```powershell
.\.venv314\Scripts\python.exe -m pytest tests/test_binary_sensor.py -q
```

Expected: import failure because `binary_sensor.py` does not exist.

- [ ] **Step 3: Implement descriptions and strict state mapping**

Create the description class:

```python
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)

@dataclass(frozen=True, kw_only=True)
class AncsBinarySensorEntityDescription(BinarySensorEntityDescription):
    path: tuple[str, ...]
    non_null_presence: bool = False
```

Define these exact paths:

```python
BINARY_FIELD_PATHS = {
    "complete": ("complete",),
    "silent": ("silent",),
    "important": ("important",),
    "pre_existing": ("pre_existing",),
    "positive_action_available": ("positive_action_available",),
    "negative_action_available": ("negative_action_available",),
    "app_id_truncated": ("truncated", "app_id"),
    "title_truncated": ("truncated", "title"),
    "subtitle_truncated": ("truncated", "subtitle"),
    "message_truncated": ("truncated", "message"),
    "has_error": ("error",),
}
```

Set `non_null_presence=True` only for `has_error`. Mark truncation and error entities as `BinarySensorDeviceClass.PROBLEM` and diagnostic; mark `complete` and `pre_existing` diagnostic without coercion. Keep notification importance, silence, and action availability as normal entities.

Implement `AncsNotificationBinarySensor(AncsNotificationEntity, BinarySensorEntity)`:

```python
@property
def is_on(self) -> bool | None:
    if self._payload is None:
        return None
    value = nested_value(self._payload, self.entity_description.path)
    if self.entity_description.non_null_presence:
        return None if "error" not in self._payload else value is not None
    return as_boolean(value)
```

Add all descriptions in `async_setup_entry` exactly as the sensor platform does.

- [ ] **Step 4: Run binary-sensor tests and verify GREEN**

Run:

```powershell
.\.venv314\Scripts\python.exe -m pytest tests/test_binary_sensor.py tests/test_entity.py -q
```

Expected: all binary and shared tests pass.

- [ ] **Step 5: Commit the binary-sensor platform**

```powershell
git add custom_components/ha_ios_ancs/binary_sensor.py tests/test_binary_sensor.py
git commit -m "Model ANCS notification flags as binary sensors" -m "Constraint: Only literal JSON booleans may define boolean entity state`nRejected: Truthy coercion | malformed payloads would appear valid`nConfidence: high`nScope-risk: narrow`nDirective: Keep nested truncation and error handling null-safe`nTested: tests/test_binary_sensor.py and tests/test_entity.py`nNot-tested: Multi-platform config-entry loading follows"
```

### Task 5: Wire all platforms and preserve device/event behavior

**Files:**
- Modify: `custom_components/ha_ios_ancs/__init__.py`
- Modify: `custom_components/ha_ios_ancs/event.py`
- Modify: `tests/test_init.py`
- Modify: `tests/test_event.py`
- Modify: `tests/test_sensor.py`
- Modify: `tests/test_binary_sensor.py`

- [ ] **Step 1: Write failing platform-forwarding tests**

Change existing forwarding and unloading expectations to the exact platform order:

```python
EXPECTED_PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.EVENT]
```

Assert setup forwards that list for source and legacy entries and unload uses the same list before stopping the runtime.

- [ ] **Step 2: Run init/event tests and verify RED**

Run:

```powershell
.\.venv314\Scripts\python.exe -m pytest tests/test_init.py tests/test_event.py -q
```

Expected: failures showing only `[Platform.EVENT]` is forwarded and unloaded.

- [ ] **Step 3: Add source-backed and legacy device-attachment tests**

For both new platforms, use the existing registry helper to assert:

```python
assert registry_entry.config_entry_id == entry.entry_id
assert registry_entry.device_id == registered.device.id
assert ("mqtt", "ios_ancs_A1B2C3") in registered.device.identifiers
assert len(device_registry.async_get(hass).devices) == 1
```

For a legacy entry, assert each companion entity uses the existing fallback identifier:

```python
assert (DOMAIN, entry.entry_id) in legacy_device.identifiers
```

Also record the MQTT registry entries before setup and assert the same IDs, `disabled_by`, and device IDs remain after companion setup and unload.

Add lifecycle assertions covering the complete shared runtime:

```python
runtime.fire_availability(False)
assert all(
    hass.states.get(entity_id).state == STATE_UNAVAILABLE
    for entity_id in companion_ids
)
runtime.fire_availability(True)
assert all(
    hass.states.get(entity_id).state != STATE_UNAVAILABLE
    for entity_id in companion_ids
)
```

Configure two source-backed ANCS entries, fire different relay IDs, and assert neither entry's sensors receive the other device's payload. Unload one entry and assert its companion states/listeners are removed while the other entry and every MQTT entity remain registered and active. Send duplicate, incomplete, pre-existing, removed, and Home Assistant echo payloads through the runtime and assert no companion sensor or binary-sensor state changes.

- [ ] **Step 4: Refactor the event entity onto the shared base**

Preserve its existing unique ID and opt it into pending replay:

```python
class AncsNotificationEvent(AncsNotificationEntity, EventEntity):
    _attr_event_types = [EVENT_TYPE_NOTIFICATION]
    _attr_translation_key = "notification"

    def __init__(self, entry: ConfigEntry, runtime: AncsRuntime) -> None:
        super().__init__(
            entry,
            runtime,
            Platform.EVENT,
            "notification",
            unique_id=runtime.unique_id,
            replay_pending=True,
        )

    @callback
    def _handle_notification(self, payload: dict[str, Any]) -> None:
        self._payload = deepcopy(payload)
        self._trigger_event(EVENT_TYPE_NOTIFICATION, deepcopy(payload))
        self.async_write_ha_state()
```

Remove duplicated device and availability code from `event.py`.

- [ ] **Step 5: Forward all platforms**

Change `__init__.py`:

```python
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.EVENT]
```

Keep the explicit event-state removal workaround limited to `Platform.EVENT`; let normal platform unloading manage sensor and binary-sensor states. Preserve the existing stop-on-forward-failure and unload-before-runtime-stop behavior.

- [ ] **Step 6: Run all component tests and verify GREEN**

Run:

```powershell
.\.venv314\Scripts\python.exe -m pytest tests -q
```

Expected: all component tests pass, with device-registry counts proving no duplicate physical device and no mutation of MQTT registry entries.

- [ ] **Step 7: Commit multi-platform integration**

```powershell
git add custom_components/ha_ios_ancs/__init__.py custom_components/ha_ios_ancs/event.py tests/test_init.py tests/test_event.py tests/test_sensor.py tests/test_binary_sensor.py
git commit -m "Load ANCS detail entities on the existing MQTT device" -m "Constraint: Existing MQTT entities must remain enabled and owned by MQTT`nRejected: Copying MQTT identifiers into DeviceInfo | Home Assistant 2026.8 requires device_entry linkage`nConfidence: high`nScope-risk: moderate`nDirective: Unload all companion platforms before stopping their shared runtime`nTested: complete tests directory`nNot-tested: Translations and release metadata follow"
```

### Task 6: Add translations, documentation, and version 0.6.0

**Files:**
- Modify: `custom_components/ha_ios_ancs/strings.json`
- Modify: `custom_components/ha_ios_ancs/translations/en.json`
- Modify: `custom_components/ha_ios_ancs/translations/ko.json`
- Modify: `custom_components/ha_ios_ancs/manifest.json`
- Modify: `tests/test_config_flow.py`
- Modify: `tools/tests/test_documentation_contract.py`
- Modify: `README.md`
- Modify: `README.en.md`

- [ ] **Step 1: Write failing translation and release-contract tests**

Extend the translation contract to require these exact entity keys in all three files:

```python
EXPECTED_ENTITY_KEYS = {
    "sensor": {
        "app_name", "app_id", "title", "subtitle", "message", "event",
        "category", "date", "uid", "session_id", "event_id",
        "event_flags", "category_id", "category_count", "message_size",
        "schema_version", "relay_id", "target", "source", "device_name",
        "received_at_ms", "published_at_ms", "error_code", "error_name",
        "raw_notification",
    },
    "binary_sensor": {
        "complete", "silent", "important", "pre_existing",
        "positive_action_available", "negative_action_available",
        "app_id_truncated", "title_truncated", "subtitle_truncated",
        "message_truncated", "has_error",
    },
    "event": {"notification"},
}
```

Change both version assertions from `0.5.1` to `0.6.0`. Add documentation assertions that the public README surfaces mention dedicated sensor/binary-sensor details, raw payload preservation, and MQTT coexistence.

- [ ] **Step 2: Run contract tests and verify RED**

Run:

```powershell
.\.venv314\Scripts\python.exe -m pytest tests/test_config_flow.py tools/tests/test_documentation_contract.py -q
```

Expected: failures for missing translation keys, README language, and version `0.6.0`.

- [ ] **Step 3: Add all English and Korean names**

Use these exact names in `strings.json` and English translation:

```text
app_name=App name; app_id=App ID; title=Notification title;
subtitle=Notification subtitle; message=Notification message;
event=Notification event; category=Notification category;
date=Notification date; uid=Notification UID; session_id=Session ID;
event_id=Event ID; event_flags=Event flags; category_id=Category ID;
category_count=Category count; message_size=Message size;
schema_version=Schema version; relay_id=Relay ID; target=Target;
source=Source; device_name=Device name;
received_at_ms=Received at device uptime;
published_at_ms=Published at device uptime; error_code=Error code;
error_name=Error name; raw_notification=Raw notification;
complete=Collection complete; silent=Silent; important=Important;
pre_existing=Pre-existing; positive_action_available=Positive action available;
negative_action_available=Negative action available;
app_id_truncated=App ID truncated; title_truncated=Title truncated;
subtitle_truncated=Subtitle truncated; message_truncated=Message truncated;
has_error=Error present
```

Use these exact Korean names:

```text
app_name=앱 이름; app_id=앱 ID; title=알림 제목; subtitle=알림 부제목;
message=알림 내용; event=알림 이벤트; category=알림 카테고리;
date=알림 날짜; uid=알림 UID; session_id=세션 ID; event_id=이벤트 ID;
event_flags=이벤트 플래그; category_id=카테고리 ID;
category_count=카테고리 수; message_size=메시지 크기;
schema_version=스키마 버전; relay_id=릴레이 ID; target=대상; source=소스;
device_name=기기 이름; received_at_ms=수신 시점 기기 가동시간;
published_at_ms=발행 시점 기기 가동시간; error_code=오류 코드;
error_name=오류 이름; raw_notification=원본 알림; complete=수집 완료;
silent=무음 알림; important=중요 알림; pre_existing=기존 알림;
positive_action_available=긍정 동작 가능;
negative_action_available=부정 동작 가능; app_id_truncated=앱 ID 잘림;
title_truncated=제목 잘림; subtitle_truncated=부제목 잘림;
message_truncated=내용 잘림; has_error=오류 발생
```

For the two enum sensors, include translated state labels for every declared option. English labels use normal title case. Korean labels use natural Korean terms such as `추가됨`, `수정됨`, `삭제됨`, `수신 전화`, `부재중 전화`, `음성사서함`, `소셜`, `일정`, `이메일`, `뉴스`, `건강 및 피트니스`, `비즈니스 및 금융`, `위치`, `엔터테인먼트`, `기타`, and `예약됨`.

- [ ] **Step 4: Document coexistence and privacy**

Add a companion-integration section to both READMEs stating:

```text
The companion integration keeps MQTT Discovery entities unchanged and adds its
own event, purpose-specific sensors, strict binary sensors, and a diagnostic raw
notification entity to the same device. Text shown as a sensor state is limited
to 255 characters; the full payload remains in attributes. Notification content
can be recorded by Home Assistant unless those entities are excluded from Recorder.
```

Use an equivalent natural Korean paragraph in `README.md` and keep all examples general-purpose with no household SSID, IP address, MAC address, or COM-port fixture.

- [ ] **Step 5: Set manifest version 0.6.0 and run contracts**

Change only the companion manifest version:

```json
"version": "0.6.0"
```

Run:

```powershell
.\.venv314\Scripts\python.exe -m pytest tests/test_config_flow.py tools/tests/test_documentation_contract.py -q
```

Expected: all selected contract tests pass.

- [ ] **Step 6: Commit release metadata and documentation**

```powershell
git add custom_components/ha_ios_ancs/strings.json custom_components/ha_ios_ancs/translations/en.json custom_components/ha_ios_ancs/translations/ko.json custom_components/ha_ios_ancs/manifest.json tests/test_config_flow.py tools/tests/test_documentation_contract.py README.md README.en.md
git commit -m "Explain and version complete ANCS notification details" -m "Constraint: Public guidance must remain general-purpose and existing MQTT entities remain visible`nRejected: Hiding long-value limits | users need to know where complete text is stored`nConfidence: high`nScope-risk: narrow`nDirective: Keep companion and firmware version tracks independent`nTested: config-flow and documentation contract tests`nNot-tested: Full suite and HACS validators follow"
```

### Task 7: Full verification, review, release, and live HACS deployment

**Files:**
- Verify: all changed files
- Live install: `/config/custom_components/ha_ios_ancs`

- [ ] **Step 1: Run the complete fresh local verification gate**

Run:

```powershell
.\.venv314\Scripts\python.exe -m pytest -q
.\.venv314\Scripts\python.exe -m compileall -q custom_components tests tools/tests
git diff --check origin/main...HEAD
git status --short
```

Expected: zero failures, byte compilation exit zero, no whitespace errors, and no unrelated working-tree changes.

- [ ] **Step 2: Review the complete diff against the approved spec**

Verify each acceptance criterion explicitly:

```text
all 25 sensor keys exist
all 11 binary-sensor keys exist
event unique ID remains unchanged
raw payload is deep-copied and complete
long text state is at most 255 characters
literal booleans are required
source-backed entities use device_entry
legacy entities use the integration-owned fallback device
MQTT registry entries are not changed
runtime stop clears the snapshot and listeners
```

Dispatch an independent code reviewer and verifier. Resolve every blocking finding with a new failing test before changing production behavior, then rerun the full gate.

- [ ] **Step 3: Push main and wait for GitHub validation**

Run:

```powershell
git push origin main
gh run list --branch main --limit 5
```

Wait for the run on the pushed SHA and require both `HACS` and `Hassfest` to conclude `success`.

- [ ] **Step 4: Publish GitHub release v0.6.0**

Run:

```powershell
gh release create v0.6.0 --target main --title "HA iOS ANCS v0.6.0" --notes "Adds complete purpose-specific notification sensors and binary sensors, preserves the full raw MQTT payload, keeps the native notification event, and leaves existing MQTT Discovery entities unchanged."
gh release view v0.6.0 --json tagName,targetCommitish,url,isDraft,isPrerelease,publishedAt
```

Expected: a non-draft, non-prerelease `v0.6.0` release targeting `main`.

- [ ] **Step 5: Install v0.6.0 through HACS and restart Home Assistant**

Use the authenticated Home Assistant HACS UI to redownload HA iOS ANCS `v0.6.0`, verify the download dialog names that exact version, install it, and restart Home Assistant Core. Do not copy files directly around HACS.

Verify after restart:

```powershell
ssh pve-new-ts "qm guest exec 100 -- ha core info"
```

Expected: `boot: true`, Core `2026.8.1` or the current installed Core version, and no pending Core update required for this component.

- [ ] **Step 6: Verify live registry and UI structure without a synthetic alert**

Read the live registries and assert for each HA iOS ANCS config entry:

```text
1 companion event entity
25 companion sensor entities
11 companion binary_sensor entities
all companion entities share the expected MQTT device_id
no integration-owned orphan device exists for a source-backed entry
all pre-existing MQTT entities retain platform=mqtt and disabled_by unchanged
manifest and HACS installed/latest version are 0.6.0
```

Open the physical device page and confirm the new `Sensors`, `Binary sensors`, and `Events` sections render. Before a new notification, values may correctly show `Unknown`; they must not show `Unavailable` while the MQTT source is ready.

- [ ] **Step 7: Verify a real iPhone notification when physically available**

Observe one new notification from the iPhone paired to the device. Confirm:

```text
event timestamp advances once
title/message/app/category sensors update from the same relay_id
binary flags match the raw payload
raw_notification attributes contain all received keys and the complete long values
existing MQTT entities continue updating independently
no ha_ios_ancs errors appear in Home Assistant logs
```

If the paired device is not physically available, report the code, HACS, registry, and readiness checks as complete but keep physical end-to-end payload population explicitly unverified.

- [ ] **Step 8: Record final evidence**

Report the pushed SHA, GitHub release URL, HACS/Hassfest results, local test count, live installed version, entity counts, device attachment, MQTT coexistence, log result, and the physical-notification result or gap.
