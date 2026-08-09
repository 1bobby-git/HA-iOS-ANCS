from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import timedelta
import json
import logging
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from homeassistant.components import event as event_component
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, Platform
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.discovery_flow import DiscoveryKey
from homeassistant.helpers import device_registry, entity_registry
from homeassistant.helpers.entity_platform import EntityPlatform

from custom_components.ha_ios_ancs import event as ancs_event
from custom_components.ha_ios_ancs import async_setup_entry, async_unload_entry
from custom_components.ha_ios_ancs.const import (
    CONF_BASE_TOPIC,
    CONF_MQTT_DEVICE_IDENTIFIER,
    CONF_SOURCE_ENTITY_UNIQUE_ID,
    DOMAIN,
)

from tests.helpers import async_register_mqtt_ancs_source


EMPTY_DISCOVERY_KEYS: MappingProxyType[str, tuple[DiscoveryKey, ...]] = MappingProxyType({})


class RuntimeStub:
    def __init__(
        self,
        available: bool | None = None,
        *,
        unique_id: str = "ios_ancs/device-1:notification",
        device_entry: device_registry.DeviceEntry | None = None,
    ) -> None:
        self.available = available
        self.unique_id = unique_id
        self.device_entry = device_entry
        self.async_start = AsyncMock()
        self.async_stop = AsyncMock()
        self._notification_listener: Callable[[dict[str, Any]], None] | None = None
        self._availability_listener: Callable[[bool | None], None] | None = None
        self.notification_listener_removed = False
        self.availability_listener_removed = False

    @callback
    def async_add_notification_listener(
        self, listener: Callable[[dict[str, Any]], None]
    ) -> CALLBACK_TYPE:
        self._notification_listener = listener

        @callback
        def remove_listener() -> None:
            self.notification_listener_removed = True
            if self._notification_listener is listener:
                self._notification_listener = None

        return remove_listener

    @callback
    def async_add_availability_listener(
        self, listener: Callable[[bool | None], None]
    ) -> CALLBACK_TYPE:
        self._availability_listener = listener

        @callback
        def remove_listener() -> None:
            self.availability_listener_removed = True
            if self._availability_listener is listener:
                self._availability_listener = None

        return remove_listener

    @callback
    def fire_notification(self, payload: dict[str, Any]) -> None:
        assert self._notification_listener is not None
        self._notification_listener(payload)

    @callback
    def fire_availability(self, available: bool | None) -> None:
        self.available = available
        assert self._availability_listener is not None
        self._availability_listener(available)


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


def test_source_event_attaches_to_existing_mqtt_device(
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

    entity_id = run(setup_event_entity(hass, make_source_entry(), runtime))
    registry_entry = entity_registry.async_get(hass).async_get(entity_id)

    assert registry_entry is not None
    assert registry_entry.unique_id == "ios_ancs_A1B2C3:notification"
    assert registry_entry.device_id == registered.device.id
    assert len(device_registry.async_get(hass).devices) == 1


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
        assert list(platforms) == [Platform.EVENT]
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
        assert list(platforms) == [Platform.EVENT]
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
    hass: HomeAssistant, run
) -> None:
    entry = make_entry("ios_ancs")
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
        entry, [Platform.EVENT]
    )


def test_setup_entry_does_not_skip_unlocked_forwarding(
    hass: HomeAssistant, run
) -> None:
    entry = make_entry("ios_ancs")
    runtime = RuntimeStub()
    hass.config_entries.async_forward_entry_setups = AsyncMock()

    with patch("custom_components.ha_ios_ancs.AncsMqttRuntime") as runtime_cls:
        runtime_cls.return_value = runtime

        assert run(async_setup_entry(hass, entry)) is True

    runtime.async_start.assert_awaited_once()
    assert entry.runtime_data is runtime
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry, [Platform.EVENT]
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
        assert list(platforms) == [Platform.EVENT]
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
