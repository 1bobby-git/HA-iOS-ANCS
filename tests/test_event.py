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
from custom_components.ha_ios_ancs.const import CONF_BASE_TOPIC, DOMAIN


EMPTY_DISCOVERY_KEYS: MappingProxyType[str, tuple[DiscoveryKey, ...]] = MappingProxyType({})


class RuntimeStub:
    def __init__(self, available: bool | None = None) -> None:
        self.available = available
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


async def setup_event_entity(
    hass: HomeAssistant,
    entry: ConfigEntry,
    runtime: RuntimeStub,
) -> str:
    await event_component.async_setup(hass, {})
    device_registry.async_setup(hass)
    await device_registry.async_load(hass, load_empty=True)
    await entity_registry.async_get(hass).async_load(load_empty=True)
    await hass.config_entries.async_add(entry)
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
        state.entity_id
        for state in hass.states.async_all()
        if state.entity_id.startswith("event.ha_ios_ancs")
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

    payload = {
        "relay_id": "session:1",
        "app_id": "com.apple.MobileSMS",
        "title": "Doorbell",
        "event": "added",
    }
    runtime.fire_notification(payload)
    state = hass.states.get(entity_id)

    assert state is not None
    assert state.state != STATE_UNKNOWN
    assert state.attributes["event_type"] == "notification"
    assert state.attributes["relay_id"] == "session:1"
    assert state.attributes["app_id"] == "com.apple.MobileSMS"
    assert state.attributes["title"] == "Doorbell"
    assert state.attributes["event"] == "added"
    assert state.attributes["event_types"] == ["notification"]


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


def test_event_entity_unload_marks_unavailable_and_removes_runtime_listeners(
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
