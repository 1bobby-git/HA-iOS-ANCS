"""Full config-entry lifecycle: saved notification cleanup and recorder hints."""

from __future__ import annotations

from collections.abc import Callable
import asyncio
import json
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryDisabler,
    ConfigEntryState,
)
from homeassistant.const import EVENT_HOMEASSISTANT_FINAL_WRITE, Platform
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from custom_components.ha_ios_ancs.const import (
    CONF_BASE_TOPIC,
    CONF_MQTT_DEVICE_IDENTIFIER,
    CONF_SOURCE_ENTITY_UNIQUE_ID,
    DOMAIN,
)

from tests.helpers import EMPTY_DISCOVERY_KEYS, async_register_mqtt_ancs_source

BASE_TOPIC = "ios_ancs/lifecycle"
# Far longer than any test: a pending save is written only by an explicit
# flush or by Home Assistant's final write, never by wall-clock timing.
SAVE_DELAY_SECONDS = 60.0
VOLATILE_DIAGNOSTICS = {
    "uptime_seconds",
    "last_notification_uptime_ms",
    "accepted",
    "published_ack",
    "dropped_offline",
    "dropped_enqueue",
    "dropped_policy",
    "wifi_retry_in_ms",
    "mqtt_retry_in_ms",
    "enrollment_remaining_seconds",
}


class FakeMqttApi:
    """Minimal MQTT API used by the legacy direct-topic runtime."""

    def __init__(self) -> None:
        self.subscriptions: dict[str, Callable[[Any], None]] = {}

    async def async_wait_for_mqtt_client(self, hass: HomeAssistant) -> bool:
        return True

    async def async_subscribe(
        self,
        hass: HomeAssistant,
        topic: str,
        msg_callback: Callable[[Any], None],
        qos: int,
    ) -> CALLBACK_TYPE:
        self.subscriptions[topic] = msg_callback

        @callback
        def unsubscribe() -> None:
            if self.subscriptions.get(topic) is msg_callback:
                del self.subscriptions[topic]

        return unsubscribe

    def fire(self, suffix: str, payload: dict[str, Any] | str) -> None:
        if not isinstance(payload, str):
            payload = json.dumps(payload)
        self.subscriptions[f"{BASE_TOPIC}/{suffix}"](
            SimpleNamespace(payload=payload, retain=False)
        )


def make_entry(**overrides: Any) -> ConfigEntry:
    values: dict[str, Any] = {
        "version": 4,
        "minor_version": 1,
        "domain": DOMAIN,
        "title": f"iOS ANCS ({BASE_TOPIC})",
        "data": {CONF_BASE_TOPIC: BASE_TOPIC},
        "source": "user",
        "unique_id": BASE_TOPIC,
        "discovery_keys": EMPTY_DISCOVERY_KEYS,
        "options": {},
        "subentries_data": {},
    }
    values.update(overrides)
    return ConfigEntry(**values)


def make_source_entry() -> ConfigEntry:
    return ConfigEntry(
        version=4,
        minor_version=1,
        domain=DOMAIN,
        title="iOS ANCS (ios_ancs_A1B2C3)",
        data={
            CONF_SOURCE_ENTITY_UNIQUE_ID: "ios_ancs_A1B2C3_last_notification",
            CONF_MQTT_DEVICE_IDENTIFIER: "ios_ancs_A1B2C3",
        },
        source="user",
        unique_id="ios_ancs_A1B2C3",
        discovery_keys=MappingProxyType({}),
        options={},
        subentries_data={},
    )


def notification(relay_id: str) -> dict[str, Any]:
    return {
        "relay_id": relay_id,
        "complete": True,
        "pre_existing": False,
        "app_id": "com.example.chat",
        "event": "added",
        "title": f"Title {relay_id}",
        "message": "Private message",
    }


def status(uptime: int) -> dict[str, Any]:
    return {
        "diagnostics_version": 1,
        "uptime_seconds": uptime,
        "wifi_connected": True,
        "mqtt_connected": True,
        "ble_connected": True,
        "ancs_ready": True,
        "session_authenticated": True,
        "link_encrypted": True,
        "ancs_service_found": True,
        "data_source_subscribed": True,
        "notification_source_subscribed": True,
        "bond_store_known": True,
        "stored_peer_count": 1,
        "accepted": 3,
        "published_ack": 3,
        "last_notification_uptime_ms": uptime * 1000,
        "wifi_disconnect_reason": 0,
    }


def storage_path(hass: HomeAssistant, entry_id: str) -> Path:
    return Path(hass.config.path(".storage", f"{DOMAIN}.{entry_id}.last_notification"))


def saved_relay_id(hass: HomeAssistant, entry_id: str) -> str | None:
    path = storage_path(hass, entry_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))["data"]["relay_id"]


async def async_final_write(hass: HomeAssistant) -> None:
    """Run pending delayed Store writes now, as Home Assistant does at stop."""

    hass.bus.async_fire(EVENT_HOMEASSISTANT_FINAL_WRITE)
    await hass.async_block_till_done()


async def async_setup_loaded_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    # The MQTT integration itself is replaced by FakeMqttApi.
    hass.config.components.add("mqtt")
    await hass.config_entries.async_add(entry)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


def entity_id_for(hass: HomeAssistant, platform: Platform, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{BASE_TOPIC}:{platform.value}:{key}"
    )
    assert entity_id is not None
    return entity_id


def run_scenario(run, scenario: Callable[[FakeMqttApi], Any]) -> Any:
    mqtt_api = FakeMqttApi()
    with (
        patch(
            "custom_components.ha_ios_ancs.runtime._get_mqtt_api",
            return_value=mqtt_api,
        ),
        patch(
            "custom_components.ha_ios_ancs._STORAGE_SAVE_DELAY_SECONDS",
            SAVE_DELAY_SECONDS,
        ),
    ):
        return run(scenario(mqtt_api))


def test_removing_entry_deletes_saved_notification(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    entry = make_entry()

    async def scenario(mqtt_api: FakeMqttApi) -> tuple[str | None, bool]:
        await async_setup_loaded_entry(hass, entry)
        mqtt_api.fire("notification", notification("saved"))
        await hass.async_block_till_done()
        await async_final_write(hass)
        saved = saved_relay_id(hass, entry.entry_id)
        await hass.config_entries.async_remove(entry.entry_id)
        await async_final_write(hass)
        return saved, storage_path(hass, entry.entry_id).exists()

    saved, left_after_remove = run_scenario(run, scenario)
    assert saved == "saved"
    assert left_after_remove is False


def test_removing_entry_during_pending_save_leaves_no_file(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    entry = make_entry()

    async def scenario(mqtt_api: FakeMqttApi) -> bool:
        await async_setup_loaded_entry(hass, entry)
        mqtt_api.fire("notification", notification("pending"))
        await hass.async_block_till_done()
        assert not storage_path(hass, entry.entry_id).exists()
        await hass.config_entries.async_remove(entry.entry_id)
        # A write still pending in a setup-time Store would land here.
        await async_final_write(hass)
        return storage_path(hass, entry.entry_id).exists()

    assert run_scenario(run, scenario) is False


def test_reload_during_pending_save_restores_newest_notification(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    entry = make_entry()

    async def scenario(mqtt_api: FakeMqttApi) -> tuple[str | None, str]:
        await async_setup_loaded_entry(hass, entry)
        mqtt_api.fire("notification", notification("newest"))
        await hass.async_block_till_done()
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        restored = entry.runtime_data.latest_notification
        title_state = hass.states.get(entity_id_for(hass, Platform.SENSOR, "title"))
        assert title_state is not None
        await hass.config_entries.async_unload(entry.entry_id)
        return (None if restored is None else restored["relay_id"]), title_state.state

    relay_id, title = run_scenario(run, scenario)
    assert relay_id == "newest"
    assert title == "Title newest"


def test_reload_without_new_notification_does_not_write_storage(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    entry = make_entry()

    async def scenario(mqtt_api: FakeMqttApi) -> bool:
        await async_setup_loaded_entry(hass, entry)
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        await hass.config_entries.async_unload(entry.entry_id)
        await async_final_write(hass)
        return storage_path(hass, entry.entry_id).exists()

    assert run_scenario(run, scenario) is False


def test_failed_setup_writes_pending_notification_and_stops_runtime(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    entry = make_entry()

    async def scenario(mqtt_api: FakeMqttApi) -> tuple[Any, str | None, list[str]]:
        hass.config.components.add("mqtt")

        async def failing_forward(_entry: ConfigEntry, _platforms: Any) -> None:
            mqtt_api.fire("notification", notification("during-setup"))
            raise RuntimeError("platform setup failed")

        with patch.object(
            hass.config_entries, "async_forward_entry_setups", failing_forward
        ):
            await hass.config_entries.async_add(entry)
            await hass.async_block_till_done()
        return entry.state, saved_relay_id(hass, entry.entry_id), sorted(mqtt_api.subscriptions)

    state, saved, subscriptions = run_scenario(run, scenario)
    assert state is ConfigEntryState.SETUP_ERROR
    assert saved == "during-setup"
    assert subscriptions == []


def test_removing_entry_after_failed_unload_stops_runtime_and_leaves_no_file(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    entry = make_entry()

    async def scenario(mqtt_api: FakeMqttApi) -> tuple[Any, list[str], bool]:
        await async_setup_loaded_entry(hass, entry)
        mqtt_api.fire("notification", notification("pending"))
        await hass.async_block_till_done()
        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            AsyncMock(return_value=False),
        ):
            result = await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()
        await async_final_write(hass)
        return result, sorted(mqtt_api.subscriptions), storage_path(hass, entry.entry_id).exists()

    result, subscriptions, file_left = run_scenario(run, scenario)
    assert result["require_restart"] is True
    assert subscriptions == []
    assert file_left is False


def test_removal_after_failed_unload_waits_for_write_in_progress(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    entry = make_entry()
    release_write = asyncio.Event()
    write_started = asyncio.Event()
    original_write = Store._async_write_data

    async def slow_write(store: Store, data: dict[str, Any]) -> None:
        if store.key.startswith(f"{DOMAIN}.") and not release_write.is_set():
            write_started.set()
            await release_write.wait()
        await original_write(store, data)

    async def scenario(mqtt_api: FakeMqttApi) -> bool:
        await async_setup_loaded_entry(hass, entry)
        mqtt_api.fire("notification", notification("in-flight"))
        await hass.async_block_till_done()
        with (
            patch.object(Store, "_async_write_data", slow_write),
            patch.object(
                hass.config_entries,
                "async_unload_platforms",
                AsyncMock(return_value=False),
            ),
        ):
            # Start the delayed write; it holds the Store write lock.
            hass.bus.async_fire(EVENT_HOMEASSISTANT_FINAL_WRITE)
            await asyncio.wait_for(write_started.wait(), 5)
            remove = hass.async_create_task(
                hass.config_entries.async_remove(entry.entry_id)
            )
            # Let removal run as far as it can while the write is held: it must
            # wait for the write instead of deleting the file underneath it.
            await asyncio.wait({remove}, timeout=0.5)
            release_write.set()
            await asyncio.wait_for(remove, 10)
            await hass.async_block_till_done()
        return storage_path(hass, entry.entry_id).exists()

    assert run_scenario(run, scenario) is False


def test_removing_disabled_entry_deletes_notification_saved_at_disable(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    entry = make_entry()

    async def scenario(mqtt_api: FakeMqttApi) -> tuple[str | None, bool]:
        await async_setup_loaded_entry(hass, entry)
        mqtt_api.fire("notification", notification("before-disable"))
        await hass.async_block_till_done()
        await hass.config_entries.async_set_disabled_by(
            entry.entry_id, ConfigEntryDisabler.USER
        )
        await hass.async_block_till_done()
        saved_at_disable = saved_relay_id(hass, entry.entry_id)
        await hass.config_entries.async_remove(entry.entry_id)
        await async_final_write(hass)
        return saved_at_disable, storage_path(hass, entry.entry_id).exists()

    saved_at_disable, file_left = run_scenario(run, scenario)
    assert saved_at_disable == "before-disable"
    assert file_left is False


def test_source_entry_reload_and_removal(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    entry = make_source_entry()

    async def scenario(mqtt_api: FakeMqttApi) -> tuple[str | None, bool]:
        registered = await async_register_mqtt_ancs_source(
            hass, "ios_ancs_A1B2C3", device_name="Kitchen Relay"
        )
        source_id = registered.entity.entity_id
        hass.states.async_set(source_id, "unknown")
        await async_setup_loaded_entry(hass, entry)
        hass.states.async_set(source_id, "relay-1", notification("relay-1"))
        await hass.async_block_till_done()
        # Unavailable at setup, so the runtime cannot reseed from the source
        # state and the restore depends on the flushed file.
        hass.states.async_set(source_id, "unavailable")
        await hass.async_block_till_done()
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        restored = entry.runtime_data.latest_notification
        hass.states.async_set(source_id, "relay-2", notification("relay-2"))
        await hass.async_block_till_done()
        await hass.config_entries.async_remove(entry.entry_id)
        await async_final_write(hass)
        return (
            None if restored is None else restored["relay_id"],
            storage_path(hass, entry.entry_id).exists(),
        )

    restored, file_left = run_scenario(run, scenario)
    assert restored == "relay-1"
    assert file_left is False


def test_setup_removes_saved_notifications_of_deleted_entries(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    entry = make_entry()
    disabled = make_entry(
        unique_id="ios_ancs/disabled",
        data={CONF_BASE_TOPIC: "ios_ancs/disabled"},
        disabled_by=ConfigEntryDisabler.USER,
    )
    ignored = make_entry(
        unique_id="ios_ancs/ignored",
        data={CONF_BASE_TOPIC: "ios_ancs/ignored"},
        source="ignore",
    )
    storage = Path(hass.config.path(".storage"))
    storage.mkdir(parents=True, exist_ok=True)

    def write_store(name: str, relay_id: str) -> Path:
        path = storage / name
        key = name
        path.write_text(
            json.dumps(
                {"version": 1, "minor_version": 1, "key": key, "data": notification(relay_id)}
            ),
            encoding="utf-8",
        )
        return path

    own = write_store(f"{DOMAIN}.{entry.entry_id}.last_notification", "own")
    kept_for_entries = [
        write_store(f"{DOMAIN}.{disabled.entry_id}.last_notification", "disabled"),
        write_store(f"{DOMAIN}.{ignored.entry_id}.last_notification", "ignored"),
    ]
    orphan = write_store(f"{DOMAIN}.01J0RPHANENTRY000000000000.last_notification", "orphan")
    old_style = write_store(f"{DOMAIN}.0123456789abcdef0123456789abcdef.last_notification", "old")
    unrelated = [
        write_store("other_domain.01J0RPHANENTRY000000000000.last_notification", "x"),
        write_store(f"{DOMAIN}.01J0RPHANENTRY000000000000.last_notification.bak", "x"),
        write_store(f"{DOMAIN}.settings", "x"),
    ]

    async def scenario(mqtt_api: FakeMqttApi) -> str | None:
        # Register the disabled and ignored entries without setting anything up.
        with patch.object(
            hass.config_entries, "async_setup", new=AsyncMock(return_value=True)
        ):
            await hass.config_entries.async_add(disabled)
            await hass.config_entries.async_add(ignored)
            await hass.async_block_till_done()
        await async_setup_loaded_entry(hass, entry)
        restored = entry.runtime_data.latest_notification
        await hass.config_entries.async_unload(entry.entry_id)
        return None if restored is None else restored["relay_id"]

    assert run_scenario(run, scenario) == "own"
    assert own.exists()
    for path in kept_for_entries:
        assert path.exists(), path.name
    assert not orphan.exists()
    assert not old_style.exists()
    for path in unrelated:
        assert path.exists(), path.name


def test_orphan_cleanup_error_does_not_block_setup(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    entry = make_entry()
    blocked = Path(
        hass.config.path(
            ".storage", f"{DOMAIN}.01J0RPHANDIR00000000000000.last_notification"
        )
    )
    # A directory with a matching name cannot be unlinked.
    blocked.mkdir(parents=True)

    async def scenario(mqtt_api: FakeMqttApi) -> Any:
        await async_setup_loaded_entry(hass, entry)
        state = entry.state
        await hass.config_entries.async_unload(entry.entry_id)
        return state

    assert run_scenario(run, scenario) is ConfigEntryState.LOADED
    assert blocked.is_dir()


def test_connection_entities_skip_recording_volatile_diagnostics(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    entry = make_entry()

    async def scenario(mqtt_api: FakeMqttApi) -> list[Any]:
        await async_setup_loaded_entry(hass, entry)
        # notification_ready is unavailable (no attributes) until "online".
        mqtt_api.fire("availability", "online")
        mqtt_api.fire("state", status(120))
        await hass.async_block_till_done()
        states = [
            hass.states.get(entity_id_for(hass, Platform.SENSOR, "connection_state")),
            hass.states.get(
                entity_id_for(hass, Platform.BINARY_SENSOR, "notification_ready")
            ),
        ]
        await hass.config_entries.async_unload(entry.entry_id)
        return states

    for state in run_scenario(run, scenario):
        assert state is not None
        # Current values stay visible to templates and automations.
        assert state.attributes["uptime_seconds"] == 120
        assert state.attributes["accepted"] == 3
        assert state.attributes["connection_state"] == "ready"
        unrecorded = state.state_info["unrecorded_attributes"]
        assert VOLATILE_DIAGNOSTICS <= unrecorded
        for kept in (
            "connection_state",
            "status_fresh",
            "required_user_action",
            "wifi_connected",
            "wifi_disconnect_reason",
            "stored_peer_count",
        ):
            assert kept not in unrecorded


def test_notification_entities_keep_recording_notification_attributes(
    registry_hass: HomeAssistant, run
) -> None:
    """README tells users to exclude these entities themselves if needed."""

    hass = registry_hass
    entry = make_entry()

    async def scenario(mqtt_api: FakeMqttApi) -> Any:
        await async_setup_loaded_entry(hass, entry)
        mqtt_api.fire("notification", notification("recorded"))
        await hass.async_block_till_done()
        state = hass.states.get(
            entity_id_for(hass, Platform.SENSOR, "raw_notification")
        )
        await hass.config_entries.async_unload(entry.entry_id)
        return state

    state = run_scenario(run, scenario)
    assert state is not None
    assert state.attributes["title"] == "Title recorded"
    assert "title" not in state.state_info["unrecorded_attributes"]
    assert "message" not in state.state_info["unrecorded_attributes"]
