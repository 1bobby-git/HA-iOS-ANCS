"""Full config-entry lifecycle: saved notification cleanup and recorder hints."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from custom_components.ha_ios_ancs.const import CONF_BASE_TOPIC, DOMAIN

from tests.helpers import EMPTY_DISCOVERY_KEYS

BASE_TOPIC = "ios_ancs/lifecycle"
# Long enough that unload/remove finish first, short enough for a fast test.
SAVE_DELAY_SECONDS = 0.4
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


def make_entry() -> ConfigEntry:
    return ConfigEntry(
        version=4,
        minor_version=1,
        domain=DOMAIN,
        title=f"iOS ANCS ({BASE_TOPIC})",
        data={CONF_BASE_TOPIC: BASE_TOPIC},
        source="user",
        unique_id=BASE_TOPIC,
        discovery_keys=EMPTY_DISCOVERY_KEYS,
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


def storage_path(hass: HomeAssistant, entry: ConfigEntry) -> Path:
    return Path(hass.config.path(".storage", f"{DOMAIN}.{entry.entry_id}.last_notification"))


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

    async def scenario(mqtt_api: FakeMqttApi) -> tuple[bool, bool]:
        await async_setup_loaded_entry(hass, entry)
        mqtt_api.fire("notification", notification("saved"))
        await asyncio.sleep(SAVE_DELAY_SECONDS + 0.3)
        await hass.async_block_till_done()
        saved = storage_path(hass, entry).exists()
        await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()
        return saved, storage_path(hass, entry).exists()

    saved, left_after_remove = run_scenario(run, scenario)
    assert saved is True
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
        await hass.config_entries.async_remove(entry.entry_id)
        # Let the delay of a save scheduled before removal run out.
        await asyncio.sleep(SAVE_DELAY_SECONDS + 0.3)
        await hass.async_block_till_done()
        return storage_path(hass, entry).exists()

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
        return storage_path(hass, entry).exists()

    assert run_scenario(run, scenario) is False


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
