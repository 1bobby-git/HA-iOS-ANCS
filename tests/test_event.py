from __future__ import annotations

from collections.abc import Callable, Iterable
from copy import deepcopy
from datetime import timedelta
import json
import logging
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from homeassistant.components import binary_sensor as binary_sensor_component
from homeassistant.components import event as event_component
from homeassistant.components import sensor as sensor_component
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, Platform
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.discovery_flow import DiscoveryKey
from homeassistant.helpers import device_registry, entity_registry
from homeassistant.helpers.entity_platform import EntityPlatform

from custom_components.ha_ios_ancs import binary_sensor as ancs_binary_sensor
from custom_components.ha_ios_ancs import event as ancs_event
from custom_components.ha_ios_ancs import sensor as ancs_sensor
from custom_components.ha_ios_ancs import async_setup_entry, async_unload_entry
from custom_components.ha_ios_ancs.const import (
    CONF_BASE_TOPIC,
    CONF_MQTT_DEVICE_IDENTIFIER,
    CONF_SOURCE_ENTITY_UNIQUE_ID,
    DOMAIN,
)

from tests.helpers import async_register_mqtt_ancs_source, async_setup_ancs_platform


EMPTY_DISCOVERY_KEYS: MappingProxyType[str, tuple[DiscoveryKey, ...]] = MappingProxyType({})
EXPECTED_PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.EVENT]


class RuntimeStub:
    def __init__(
        self,
        available: bool | None = None,
        *,
        unique_id: str = "ios_ancs/device-1:notification",
        device_entry: device_registry.DeviceEntry | None = None,
        latest_notification: dict[str, Any] | None = None,
    ) -> None:
        self.available = available
        self.unique_id = unique_id
        self.device_entry = device_entry
        self.latest_notification = deepcopy(latest_notification)
        self.async_start = AsyncMock()
        self.async_stop = AsyncMock()
        self._notification_listeners: list[Callable[[dict[str, Any]], None]] = []
        self._availability_listeners: list[Callable[[bool | None], None]] = []
        self.notification_replay_pending: bool | None = None
        self.notification_listener_removed = False
        self.availability_listener_removed = False

    def restore_notification(
        self, notification: dict[str, Any] | None
    ) -> bool:
        """Restore a saved notification for setup-entry tests."""

        if notification is None:
            return False
        self.latest_notification = deepcopy(notification)
        return True

    @callback
    def async_add_notification_listener(
        self,
        listener: Callable[[dict[str, Any]], None],
        *,
        replay_pending: bool = True,
    ) -> CALLBACK_TYPE:
        self._notification_listeners.append(listener)
        self.notification_replay_pending = replay_pending

        @callback
        def remove_listener() -> None:
            self.notification_listener_removed = True
            if listener in self._notification_listeners:
                self._notification_listeners.remove(listener)

        return remove_listener

    @callback
    def async_add_availability_listener(
        self, listener: Callable[[bool | None], None]
    ) -> CALLBACK_TYPE:
        self._availability_listeners.append(listener)

        @callback
        def remove_listener() -> None:
            self.availability_listener_removed = True
            if listener in self._availability_listeners:
                self._availability_listeners.remove(listener)

        return remove_listener

    @callback
    def fire_notification(self, payload: dict[str, Any]) -> None:
        assert self._notification_listeners
        self.latest_notification = deepcopy(payload)
        for listener in tuple(self._notification_listeners):
            listener(deepcopy(payload))

    @callback
    def fire_availability(self, available: bool | None) -> None:
        self.available = available
        assert self._availability_listeners
        for listener in tuple(self._availability_listeners):
            listener(available)


def make_entry(base_topic: str = "ios_ancs/device-1") -> ConfigEntry:
    return ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title=f"HA iOS ANCS ({base_topic})",
        data={CONF_BASE_TOPIC: base_topic},
        source="user",
        unique_id=base_topic,
        discovery_keys=EMPTY_DISCOVERY_KEYS,
        options={},
        subentries_data={},
    )


def make_source_entry() -> ConfigEntry:
    return ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="Kitchen Relay",
        data={
            CONF_SOURCE_ENTITY_UNIQUE_ID: "ios_ancs_A1B2C3_last_notification",
            CONF_MQTT_DEVICE_IDENTIFIER: "ios_ancs_A1B2C3",
        },
        source="user",
        unique_id="ios_ancs_A1B2C3",
        discovery_keys=EMPTY_DISCOVERY_KEYS,
        options={},
        subentries_data={},
    )


def firmware_notification() -> dict[str, object]:
    return {
        "schema_version": 1,
        "target": "esp32c6",
        "source": "esp32c6_ancs",
        "relay_id": "boot1-1-42-aabbcc",
        "device_name": "IOS-ANCS-C6-AB12",
        "session_id": 1,
        "event": "added",
        "event_id": 0,
        "uid": 42,
        "app_id": "com.example.chat",
        "title": "Private title",
        "subtitle": "",
        "message": "Private message",
        "complete": True,
        "pre_existing": False,
        "published_at_ms": 123456,
    }


async def setup_event_entity(
    hass: HomeAssistant,
    entry: ConfigEntry,
    runtime: RuntimeStub,
) -> str:
    await event_component.async_setup(hass, {})
    try:
        device_registry.async_get(hass)
    except RuntimeError:
        device_registry.async_setup(hass)
        await device_registry.async_load(hass, load_empty=True)
        await entity_registry.async_get(hass).async_load(load_empty=True)
    with patch.object(
        hass.config_entries,
        "async_setup",
        new=AsyncMock(return_value=True),
    ):
        await hass.config_entries.async_add(entry)
        await hass.async_block_till_done()
    entry.runtime_data = runtime

    platform = EntityPlatform(
        hass=hass,
        logger=logging.getLogger(__name__),
        domain=event_component.DOMAIN,
        platform_name=DOMAIN,
        platform=cast(Any, ancs_event),
        scan_interval=timedelta(seconds=30),
        entity_namespace=None,
    )

    assert await platform.async_setup_entry(entry) is True
    hass.data[event_component.DATA_COMPONENT]._platforms[entry.entry_id] = platform
    await hass.async_block_till_done()

    entity_ids = [
        registry_entry.entity_id
        for registry_entry in entity_registry.async_entries_for_config_entry(
            entity_registry.async_get(hass),
            entry.entry_id,
        )
        if registry_entry.domain == Platform.EVENT
    ]
    assert len(entity_ids) == 1
    return entity_ids[0]


def test_event_entity_triggers_notification_event_with_payload_attributes(
    hass: HomeAssistant, run
) -> None:
    runtime = RuntimeStub(available=None)
    entry = make_entry()

    entity_id = run(setup_event_entity(hass, entry, runtime))
    assert runtime.notification_replay_pending is True
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_UNKNOWN

    payload = firmware_notification()
    runtime.fire_notification(payload)
    state = hass.states.get(entity_id)

    assert state is not None
    assert state.state != STATE_UNKNOWN
    assert state.attributes["event_type"] == "notification"
    for key, value in payload.items():
        assert state.attributes[key] == value
    assert state.attributes["event_types"] == ["notification"]


def test_source_event_uses_separate_integration_device(
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
    runtime = RuntimeStub(
        available=True,
        unique_id="ios_ancs_A1B2C3:notification",
        device_entry=registered.device,
    )

    entry = make_source_entry()
    entity_id = run(setup_event_entity(hass, entry, runtime))
    registry_entry = entity_registry.async_get(hass).async_get(entity_id)

    assert registry_entry is not None
    assert registry_entry.unique_id == "ios_ancs_A1B2C3:notification"
    assert registry_entry.device_id != registered.device.id
    companion_device = device_registry.async_get(hass).async_get(
        registry_entry.device_id
    )
    assert companion_device is not None
    assert companion_device.identifiers == {(DOMAIN, entry.entry_id)}
    assert companion_device.via_device_id is None
    assert len(device_registry.async_get(hass).devices) == 2


def test_legacy_event_retains_integration_owned_device(
    hass: HomeAssistant, run
) -> None:
    entry = make_entry()
    entity_id = run(setup_event_entity(hass, entry, RuntimeStub(available=True)))
    registry_entry = entity_registry.async_get(hass).async_get(entity_id)

    assert registry_entry is not None
    assert registry_entry.unique_id == "ios_ancs/device-1:notification"
    assert registry_entry.device_id is not None
    legacy_device = device_registry.async_get(hass).async_get(registry_entry.device_id)
    assert legacy_device is not None
    assert (DOMAIN, entry.entry_id) in legacy_device.identifiers


def test_event_entity_availability_follows_runtime_and_ignores_unknown(
    hass: HomeAssistant, run
) -> None:
    runtime = RuntimeStub(available=True)
    entity_id = run(setup_event_entity(hass, make_entry(), runtime))

    runtime.fire_availability(False)
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_UNAVAILABLE

    runtime.fire_availability(None)
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_UNAVAILABLE

    runtime.fire_availability(True)
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_UNKNOWN


def test_all_companion_platforms_share_owned_device_and_unload_cleanly(
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
    seed = firmware_notification()
    hass.states.async_set(
        registered.entity.entity_id,
        seed["relay_id"],
        seed,
    )
    mqtt_before = {
        (item.entity_id, item.disabled_by, item.device_id)
        for item in entity_registry.async_get(hass).entities.values()
        if item.platform == "mqtt"
    }
    entry = make_source_entry()
    runtime = RuntimeStub(
        available=True,
        unique_id="ios_ancs_A1B2C3:notification",
        device_entry=registered.device,
        latest_notification=seed,
    )

    _, sensor_ids = run(
        async_setup_ancs_platform(
            hass,
            entry,
            runtime,
            sensor_component,
            ancs_sensor,
            Platform.SENSOR,
        )
    )
    _, binary_sensor_ids = run(
        async_setup_ancs_platform(
            hass,
            entry,
            runtime,
            binary_sensor_component,
            ancs_binary_sensor,
            Platform.BINARY_SENSOR,
        )
    )
    _, event_ids = run(
        async_setup_ancs_platform(
            hass,
            entry,
            runtime,
            event_component,
            ancs_event,
            Platform.EVENT,
        )
    )
    companion_ids = sensor_ids + binary_sensor_ids + event_ids

    registry = entity_registry.async_get(hass)
    assert len(sensor_ids) == 24
    assert len(binary_sensor_ids) == 12
    assert len(event_ids) == 1
    companion_device_ids = {
        registry_entry.device_id
        for entity_id in companion_ids
        if (registry_entry := registry.async_get(entity_id)) is not None
    }
    assert len(companion_device_ids) == 1
    companion_device_id = companion_device_ids.pop()
    assert companion_device_id is not None
    assert companion_device_id != registered.device.id
    companion_device = device_registry.async_get(hass).async_get(
        companion_device_id
    )
    assert companion_device is not None
    assert companion_device.identifiers == {(DOMAIN, entry.entry_id)}
    assert companion_device.via_device_id is None
    assert len(device_registry.async_get(hass).devices) == 2
    assert {
        (item.entity_id, item.disabled_by, item.device_id)
        for item in registry.entities.values()
        if item.platform == "mqtt"
    } == mqtt_before

    runtime.fire_availability(False)
    assert all(
        (state := hass.states.get(entity_id)) is not None
        and state.state == STATE_UNAVAILABLE
        for entity_id in companion_ids
    )
    runtime.fire_availability(None)
    assert all(
        (state := hass.states.get(entity_id)) is not None
        and state.state == STATE_UNAVAILABLE
        for entity_id in companion_ids
    )
    runtime.fire_availability(True)
    assert all(
        (state := hass.states.get(entity_id)) is not None
        and state.state != STATE_UNAVAILABLE
        for entity_id in companion_ids
    )

    updated = firmware_notification()
    updated["relay_id"] = "boot1-1-43-aabbcc"
    updated["uid"] = 43
    updated["title"] = "Updated private title"
    updated["important"] = True
    runtime.fire_notification(updated)
    title_entry = next(
        item
        for item in entity_registry.async_entries_for_config_entry(
            registry, entry.entry_id
        )
        if item.unique_id.endswith(":sensor:title")
    )
    important_entry = next(
        item
        for item in entity_registry.async_entries_for_config_entry(
            registry, entry.entry_id
        )
        if item.unique_id.endswith(":binary_sensor:important")
    )
    title_state = hass.states.get(title_entry.entity_id)
    important_state = hass.states.get(important_entry.entity_id)
    event_state = hass.states.get(event_ids[0])
    assert title_state is not None
    assert important_state is not None
    assert event_state is not None
    assert title_state.state == "Updated private title"
    assert important_state.state == "on"
    assert event_state.attributes["relay_id"] == "boot1-1-43-aabbcc"
    mqtt_state = hass.states.get(registered.entity.entity_id)
    assert mqtt_state is not None
    assert mqtt_state.state == seed["relay_id"]

    async def unload_platforms(
        unload_entry: ConfigEntry,
        platforms: Iterable[Platform | str],
    ) -> bool:
        assert unload_entry is entry
        assert list(platforms) == EXPECTED_PLATFORMS
        results = [
            await sensor_component.async_unload_entry(hass, entry),
            await binary_sensor_component.async_unload_entry(hass, entry),
            await event_component.async_unload_entry(hass, entry),
        ]
        return all(results)

    cast(Any, hass.config_entries).async_unload_platforms = unload_platforms

    async def unload_with_locked_entry() -> bool:
        async with entry.setup_lock:
            return await async_unload_entry(hass, entry)

    assert run(unload_with_locked_entry()) is True
    run(hass.async_block_till_done())

    remaining_states = {
        entity_id: state.state
        for entity_id in companion_ids
        if (state := hass.states.get(entity_id)) is not None
    }
    assert all(event_id not in remaining_states for event_id in event_ids)
    assert set(remaining_states) == set(sensor_ids + binary_sensor_ids)
    assert set(remaining_states.values()) == {STATE_UNAVAILABLE}
    assert runtime._notification_listeners == []
    assert runtime._availability_listeners == []
    runtime.async_stop.assert_awaited_once()
    assert hass.states.get(registered.entity.entity_id) is not None
    assert {
        (item.entity_id, item.disabled_by, item.device_id)
        for item in registry.entities.values()
        if item.platform == "mqtt"
    } == mqtt_before


def test_unknown_enum_values_do_not_block_event_delivery(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    entry = make_entry()
    runtime = RuntimeStub(available=True)
    _, sensor_ids = run(
        async_setup_ancs_platform(
            hass,
            entry,
            runtime,
            sensor_component,
            ancs_sensor,
            Platform.SENSOR,
        )
    )
    _, event_ids = run(
        async_setup_ancs_platform(
            hass,
            entry,
            runtime,
            event_component,
            ancs_event,
            Platform.EVENT,
        )
    )
    registry = entity_registry.async_get(hass)
    sensor_entries = {
        item.unique_id.rsplit(":", 1)[-1]: item.entity_id
        for item in entity_registry.async_entries_for_config_entry(
            registry, entry.entry_id
        )
        if item.domain == Platform.SENSOR
    }

    payload = firmware_notification()
    payload["event"] = "future_event"
    payload["category"] = "future_category"
    payload["title"] = "Still delivered"
    runtime.fire_notification(payload)

    event_sensor = hass.states.get(sensor_entries["event"])
    category_sensor = hass.states.get(sensor_entries["category"])
    title_sensor = hass.states.get(sensor_entries["title"])
    event_state = hass.states.get(event_ids[0])
    assert event_sensor is not None
    assert category_sensor is not None
    assert title_sensor is not None
    assert event_state is not None
    assert event_sensor.state == STATE_UNKNOWN
    assert category_sensor.state == STATE_UNKNOWN
    assert title_sensor.state == "Still delivered"
    assert event_state.attributes["event"] == "future_event"
    assert event_state.attributes["category"] == "future_category"


def test_event_entity_unload_removes_state_and_runtime_listeners(
    hass: HomeAssistant, run
) -> None:
    runtime = RuntimeStub(available=True)
    entry = make_entry()
    entity_id = run(setup_event_entity(hass, entry, runtime))

    async def unload_platforms(
        entry: ConfigEntry, platforms: Iterable[Platform | str]
    ) -> bool:
        assert entry is unload_entry
        assert list(platforms) == EXPECTED_PLATFORMS
        return await event_component.async_unload_entry(hass, entry)

    unload_entry = entry
    cast(Any, hass.config_entries).async_unload_platforms = unload_platforms

    async def unload_with_locked_entry() -> bool:
        async with entry.setup_lock:
            return await async_unload_entry(hass, entry)

    assert run(unload_with_locked_entry()) is True
    run(hass.async_block_till_done())

    assert hass.states.get(entity_id) is None
    assert runtime.notification_listener_removed is True
    assert runtime.availability_listener_removed is True
    runtime.async_stop.assert_awaited_once()


def test_unload_entry_keeps_other_config_entry_event_state(
    hass: HomeAssistant, run
) -> None:
    runtime = RuntimeStub(available=True)
    entry = make_entry("ios_ancs/device-1")
    entity_id = run(setup_event_entity(hass, entry, runtime))
    other_entry = make_entry("ios_ancs/device-2")
    run(hass.config_entries.async_add(other_entry))
    registry = entity_registry.async_get(hass)
    other_registry_entry = registry.async_get_or_create(
        event_component.DOMAIN,
        DOMAIN,
        "ios_ancs/device-2:notification",
        config_entry=other_entry,
        suggested_object_id="ha_ios_ancs_other_notification",
    )
    hass.states.async_set(other_registry_entry.entity_id, "2026-08-05T00:00:00+00:00")

    async def unload_platforms(
        entry: ConfigEntry, platforms: Iterable[Platform | str]
    ) -> bool:
        assert entry is unload_entry
        assert list(platforms) == EXPECTED_PLATFORMS
        return await event_component.async_unload_entry(hass, entry)

    unload_entry = entry
    cast(Any, hass.config_entries).async_unload_platforms = unload_platforms

    async def unload_with_locked_entry() -> bool:
        async with entry.setup_lock:
            return await async_unload_entry(hass, entry)

    assert run(unload_with_locked_entry()) is True

    assert hass.states.get(entity_id) is None
    assert hass.states.get(other_registry_entry.entity_id) is not None


def test_korean_translation_defines_notification_entity_name() -> None:
    translations = json.loads(
        Path("custom_components/ha_ios_ancs/translations/ko.json").read_text(
            encoding="utf-8"
        )
    )

    assert translations["entity"]["event"]["notification"]["name"] == "알림"


def test_setup_entry_cleans_runtime_when_event_forward_fails(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    entry = make_entry("ios_ancs")
    with patch.object(
        hass.config_entries,
        "async_setup",
        new=AsyncMock(return_value=True),
    ):
        run(hass.config_entries.async_add(entry))
    runtime = RuntimeStub()
    forward_error = RuntimeError("event platform failed")
    hass.config_entries.async_forward_entry_setups = AsyncMock(side_effect=forward_error)

    async def setup_with_locked_entry() -> None:
        with patch("custom_components.ha_ios_ancs.AncsMqttRuntime") as runtime_cls:
            runtime_cls.return_value = runtime
            async with entry.setup_lock:
                await async_setup_entry(hass, entry)

    try:
        run(setup_with_locked_entry())
    except RuntimeError as err:
        assert err is forward_error
    else:
        raise AssertionError("setup should raise the platform forward error")

    runtime.async_start.assert_awaited_once()
    runtime.async_stop.assert_awaited_once()
    assert entry.runtime_data is None
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry, EXPECTED_PLATFORMS
    )


def test_setup_entry_does_not_skip_unlocked_forwarding(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    entry = make_entry("ios_ancs")
    with patch.object(
        hass.config_entries,
        "async_setup",
        new=AsyncMock(return_value=True),
    ):
        run(hass.config_entries.async_add(entry))
    runtime = RuntimeStub()
    hass.config_entries.async_forward_entry_setups = AsyncMock()

    with patch("custom_components.ha_ios_ancs.AncsMqttRuntime") as runtime_cls:
        runtime_cls.return_value = runtime

        assert run(async_setup_entry(hass, entry)) is True

    runtime.async_start.assert_awaited_once()
    assert entry.runtime_data is runtime
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry, EXPECTED_PLATFORMS
    )


def test_unload_entry_unloads_platform_before_stopping_runtime(
    hass: HomeAssistant, run
) -> None:
    entry = make_entry("ios_ancs")
    runtime = RuntimeStub()
    entry.runtime_data = runtime
    calls: list[str] = []

    async def unload_platforms(
        entry: ConfigEntry, platforms: Iterable[Platform | str]
    ) -> bool:
        assert entry is unload_entry
        assert list(platforms) == EXPECTED_PLATFORMS
        assert runtime.async_stop.await_count == 0
        calls.append("platform")
        return True

    async def stop_runtime() -> None:
        calls.append("runtime")

    unload_entry = entry
    cast(Any, hass.config_entries).async_unload_platforms = unload_platforms
    runtime.async_stop.side_effect = stop_runtime

    async def unload_with_locked_entry() -> bool:
        async with entry.setup_lock:
            with patch(
                "custom_components.ha_ios_ancs.er.async_entries_for_config_entry",
                return_value=[],
            ):
                return await async_unload_entry(hass, entry)

    assert run(unload_with_locked_entry()) is True

    assert calls == ["platform", "runtime"]
    assert entry.runtime_data is None


def test_unload_entry_keeps_runtime_when_platform_unload_fails(
    hass: HomeAssistant, run
) -> None:
    entry = make_entry("ios_ancs")
    runtime = RuntimeStub()
    entry.runtime_data = runtime
    cast(Any, hass.config_entries).async_unload_platforms = AsyncMock(return_value=False)

    async def unload_with_locked_entry() -> bool:
        async with entry.setup_lock:
            return await async_unload_entry(hass, entry)

    assert run(unload_with_locked_entry()) is False

    runtime.async_stop.assert_not_awaited()
    assert entry.runtime_data is runtime
