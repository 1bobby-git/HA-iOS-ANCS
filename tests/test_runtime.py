from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from types import MappingProxyType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_FRIENDLY_NAME,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.discovery_flow import DiscoveryKey

from custom_components.ha_ios_ancs import async_setup_entry, async_unload_entry
from custom_components.ha_ios_ancs.const import CONF_BASE_TOPIC, DOMAIN, HA_ECHO_APP_ID
from custom_components.ha_ios_ancs.runtime import AncsMqttRuntime, AncsSourceRuntime

from tests.helpers import (
    RegisteredMqttSource,
    async_register_mqtt_ancs_source,
    async_register_mqtt_ancs_status,
)


EMPTY_DISCOVERY_KEYS: MappingProxyType[str, tuple[DiscoveryKey, ...]] = MappingProxyType({})


def notification_payload(**overrides: object) -> str:
    payload: dict[str, object] = {
        "relay_id": "relay-1",
        "complete": True,
        "app_id": "com.example.Messages",
        "event": "added",
        "title": "Doorbell",
    }
    payload.update(overrides)
    return json.dumps(payload)


def firmware_notification(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
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
    data.update(overrides)
    return data


async def async_make_source_runtime(
    hass: HomeAssistant,
    registered: RegisteredMqttSource,
) -> tuple[AncsSourceRuntime, list[dict[str, Any]], list[bool | None]]:
    runtime = AncsSourceRuntime(
        hass,
        registered.entity.unique_id,
        next(
            value
            for domain, value in registered.device.identifiers
            if domain == "mqtt"
        ),
    )
    notifications: list[dict[str, Any]] = []
    availability: list[bool | None] = []
    runtime.async_add_notification_listener(notifications.append)
    runtime.async_add_availability_listener(availability.append)
    await runtime.async_start()
    await hass.async_block_till_done()
    return runtime, notifications, availability


async def async_make_source_runtime_with_status(
    hass: HomeAssistant,
    registered: RegisteredMqttSource,
) -> tuple[AncsSourceRuntime, list[bool | None], str]:
    mqtt_device_identifier = next(
        value
        for domain, value in registered.device.identifiers
        if domain == "mqtt"
    )
    status = await async_register_mqtt_ancs_status(hass, registered)
    runtime = AncsSourceRuntime(
        hass,
        registered.entity.unique_id,
        mqtt_device_identifier,
    )
    ble_updates: list[bool | None] = []
    runtime.async_add_ble_connection_listener(ble_updates.append)
    await runtime.async_start()
    await hass.async_block_till_done()
    return runtime, ble_updates, status.entity_id


def mqtt_message(topic: str, payload: str | bytes) -> ReceiveMessage:
    return ReceiveMessage(
        topic=topic,
        payload=payload,
        qos=1,
        retain=False,
        subscribed_topic=topic,
        timestamp=0.0,
    )


async def start_runtime_with_subscribe_patch(
    hass: HomeAssistant,
) -> tuple[AncsMqttRuntime, list[tuple[str, Callable[[ReceiveMessage], None], int]], list[Mock]]:
    subscriptions: list[tuple[str, Callable[[ReceiveMessage], None], int]] = []
    unsubscribes = [Mock(), Mock()]

    async def fake_wait_for_client(hass: HomeAssistant) -> bool:
        return True

    async def fake_subscribe(
        hass: HomeAssistant,
        topic: str,
        msg_callback: Callable[[ReceiveMessage], None],
        qos: int = 0,
        encoding: str | None = "utf-8",
    ) -> Callable[[], None]:
        subscriptions.append((topic, msg_callback, qos))
        return unsubscribes[len(subscriptions) - 1]

    runtime = AncsMqttRuntime(hass, "ios_ancs")
    mqtt_api = SimpleNamespace(
        async_wait_for_mqtt_client=fake_wait_for_client,
        async_subscribe=fake_subscribe,
    )
    with patch("custom_components.ha_ios_ancs.runtime._get_mqtt_api", return_value=mqtt_api):
        await runtime.async_start()

    return runtime, subscriptions, unsubscribes


def test_runtime_subscribes_exact_topics_with_qos_one(hass: HomeAssistant, run) -> None:
    runtime, subscriptions, _ = run(start_runtime_with_subscribe_patch(hass))
    ble_updates: list[bool | None] = []
    runtime.async_add_ble_connection_listener(ble_updates.append)

    assert [(topic, qos) for topic, _, qos in subscriptions] == [
        ("ios_ancs/notification", 1),
        ("ios_ancs/availability", 1),
    ]
    assert runtime.ble_connected is None
    assert ble_updates == []
    run(runtime.async_stop())


def test_runtime_notification_listener_receives_only_accepted_payloads(hass: HomeAssistant, run) -> None:
    runtime, subscriptions, _ = run(start_runtime_with_subscribe_patch(hass))
    received: list[dict[str, Any]] = []
    remove = runtime.async_add_notification_listener(received.append)

    _, callback, _ = subscriptions[0]
    callback(mqtt_message("ios_ancs/notification", notification_payload()))
    callback(mqtt_message("ios_ancs/notification", notification_payload(relay_id="relay-2", complete=False)))
    remove()
    callback(mqtt_message("ios_ancs/notification", notification_payload(relay_id="relay-3")))

    assert [item["relay_id"] for item in received] == ["relay-1"]
    run(runtime.async_stop())


def test_runtime_buffers_notification_until_listener_attaches(
    hass: HomeAssistant, run
) -> None:
    runtime, subscriptions, _ = run(start_runtime_with_subscribe_patch(hass))
    _, callback, _ = subscriptions[0]
    callback(
        mqtt_message(
            "ios_ancs/notification",
            notification_payload(relay_id="relay-before-listener"),
        )
    )

    received: list[dict[str, Any]] = []
    runtime.async_add_notification_listener(received.append)

    assert [item["relay_id"] for item in received] == ["relay-before-listener"]
    run(runtime.async_stop())


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
    latest = runtime.latest_notification
    assert latest is not None
    assert latest["title"] == "Original title"

    event_updates: list[dict[str, Any]] = []
    runtime.async_add_notification_listener(event_updates.append)
    assert [item["relay_id"] for item in event_updates] == [
        "relay-before-platforms"
    ]
    run(runtime.async_stop())


def test_runtime_keeps_event_replay_while_detail_listener_is_already_active(
    hass: HomeAssistant, run
) -> None:
    runtime, subscriptions, _ = run(start_runtime_with_subscribe_patch(hass))
    details: list[dict[str, Any]] = []
    runtime.async_add_notification_listener(details.append, replay_pending=False)

    _, callback, _ = subscriptions[0]
    callback(
        mqtt_message(
            "ios_ancs/notification",
            notification_payload(relay_id="between-platforms"),
        )
    )
    assert [item["relay_id"] for item in details] == ["between-platforms"]

    events: list[dict[str, Any]] = []
    runtime.async_add_notification_listener(events.append, replay_pending=True)
    assert [item["relay_id"] for item in events] == ["between-platforms"]
    run(runtime.async_stop())


def test_runtime_availability_changes_only_on_exact_online_offline(hass: HomeAssistant, run) -> None:
    runtime, subscriptions, _ = run(start_runtime_with_subscribe_patch(hass))
    states: list[bool | None] = []
    runtime.async_add_availability_listener(states.append)

    _, callback, _ = subscriptions[1]
    assert runtime.available is None
    callback(mqtt_message("ios_ancs/availability", b"online"))
    callback(mqtt_message("ios_ancs/availability", "online"))
    callback(mqtt_message("ios_ancs/availability", "offline"))
    callback(mqtt_message("ios_ancs/availability", b"unknown"))
    callback(mqtt_message("ios_ancs/availability", b"offline"))
    callback(mqtt_message("ios_ancs/availability", b"online "))

    assert runtime.available is False
    assert states == [True, False]
    run(runtime.async_stop())


def test_runtime_listener_self_removal_does_not_break_dispatch(hass: HomeAssistant, run) -> None:
    runtime, subscriptions, _ = run(start_runtime_with_subscribe_patch(hass))
    received: list[str] = []
    remove_self: Callable[[], None] | None = None

    def self_removing_listener(notification: dict[str, Any]) -> None:
        received.append(f"self:{notification['relay_id']}")
        assert remove_self is not None
        remove_self()

    def stable_listener(notification: dict[str, Any]) -> None:
        received.append(f"stable:{notification['relay_id']}")

    remove_self = runtime.async_add_notification_listener(self_removing_listener)
    runtime.async_add_notification_listener(stable_listener)

    _, callback, _ = subscriptions[0]
    callback(mqtt_message("ios_ancs/notification", notification_payload(relay_id="relay-1")))
    callback(mqtt_message("ios_ancs/notification", notification_payload(relay_id="relay-2")))

    assert received == ["self:relay-1", "stable:relay-1", "stable:relay-2"]
    run(runtime.async_stop())


def test_runtime_repeated_start_is_idempotent_without_duplicate_subscriptions(hass: HomeAssistant, run) -> None:
    runtime, subscriptions, _ = run(start_runtime_with_subscribe_patch(hass))

    run(runtime.async_start())

    assert len(subscriptions) == 2
    run(runtime.async_stop())


def test_runtime_concurrent_starts_create_one_subscription_pair(hass: HomeAssistant, run) -> None:
    subscriptions: list[tuple[str, Callable[[ReceiveMessage], None], int]] = []
    unsubscribes = [Mock(), Mock()]

    async def fake_wait_for_client(hass: HomeAssistant) -> bool:
        await asyncio.sleep(0)
        return True

    async def fake_subscribe(
        hass: HomeAssistant,
        topic: str,
        msg_callback: Callable[[ReceiveMessage], None],
        qos: int = 0,
        encoding: str | None = "utf-8",
    ) -> Callable[[], None]:
        await asyncio.sleep(0)
        subscriptions.append((topic, msg_callback, qos))
        return unsubscribes[len(subscriptions) - 1]

    async def start_twice() -> AncsMqttRuntime:
        runtime = AncsMqttRuntime(hass, "ios_ancs")
        mqtt_api = SimpleNamespace(
            async_wait_for_mqtt_client=fake_wait_for_client,
            async_subscribe=fake_subscribe,
        )
        with patch("custom_components.ha_ios_ancs.runtime._get_mqtt_api", return_value=mqtt_api):
            await asyncio.gather(runtime.async_start(), runtime.async_start())
        return runtime

    runtime = run(start_twice())

    assert [(topic, qos) for topic, _, qos in subscriptions] == [
        ("ios_ancs/notification", 1),
        ("ios_ancs/availability", 1),
    ]
    run(runtime.async_stop())
    assert [unsubscribe.call_count for unsubscribe in unsubscribes] == [1, 1]


def test_runtime_stop_waits_for_in_flight_start_and_unsubscribes(hass: HomeAssistant, run) -> None:
    wait_started = asyncio.Event()
    release_wait = asyncio.Event()
    subscriptions: list[str] = []
    unsubscribes = [Mock(), Mock()]

    async def fake_wait_for_client(hass: HomeAssistant) -> bool:
        wait_started.set()
        await release_wait.wait()
        return True

    async def fake_subscribe(
        hass: HomeAssistant,
        topic: str,
        msg_callback: Callable[[ReceiveMessage], None],
        qos: int = 0,
        encoding: str | None = "utf-8",
    ) -> Callable[[], None]:
        subscriptions.append(topic)
        return unsubscribes[len(subscriptions) - 1]

    async def start_then_stop() -> AncsMqttRuntime:
        runtime = AncsMqttRuntime(hass, "ios_ancs")
        mqtt_api = SimpleNamespace(
            async_wait_for_mqtt_client=fake_wait_for_client,
            async_subscribe=fake_subscribe,
        )
        with patch("custom_components.ha_ios_ancs.runtime._get_mqtt_api", return_value=mqtt_api):
            start_task = asyncio.create_task(runtime.async_start())
            await wait_started.wait()
            stop_task = asyncio.create_task(runtime.async_stop())
            await asyncio.sleep(0)
            release_wait.set()
            await asyncio.gather(start_task, stop_task)
        return runtime

    runtime = run(start_then_stop())

    assert subscriptions == ["ios_ancs/notification", "ios_ancs/availability"]
    assert [unsubscribe.call_count for unsubscribe in unsubscribes] == [1, 1]
    run(runtime.async_stop())
    assert [unsubscribe.call_count for unsubscribe in unsubscribes] == [1, 1]


def test_runtime_cleans_up_partial_start_and_can_retry(hass: HomeAssistant, run) -> None:
    first_unsubscribe = Mock()
    retry_notification_unsubscribe = Mock()
    retry_availability_unsubscribe = Mock()
    subscriptions: list[str] = []
    subscribe_attempts = 0

    async def fake_wait_for_client(hass: HomeAssistant) -> bool:
        return True

    async def flaky_subscribe(
        hass: HomeAssistant,
        topic: str,
        msg_callback: Callable[[ReceiveMessage], None],
        qos: int = 0,
        encoding: str | None = "utf-8",
    ) -> Callable[[], None]:
        nonlocal subscribe_attempts
        subscribe_attempts += 1
        subscriptions.append(topic)
        if subscribe_attempts == 2:
            raise RuntimeError("availability subscribe failed")
        return {
            1: first_unsubscribe,
            3: retry_notification_unsubscribe,
            4: retry_availability_unsubscribe,
        }[subscribe_attempts]

    runtime = AncsMqttRuntime(hass, "ios_ancs")
    mqtt_api = SimpleNamespace(
        async_wait_for_mqtt_client=fake_wait_for_client,
        async_subscribe=flaky_subscribe,
    )

    with patch("custom_components.ha_ios_ancs.runtime._get_mqtt_api", return_value=mqtt_api):
        with pytest.raises(RuntimeError, match="availability subscribe failed"):
            run(runtime.async_start())

        assert first_unsubscribe.call_count == 1
        assert subscriptions == ["ios_ancs/notification", "ios_ancs/availability"]

        run(runtime.async_start())

    assert subscriptions == [
        "ios_ancs/notification",
        "ios_ancs/availability",
        "ios_ancs/notification",
        "ios_ancs/availability",
    ]
    assert retry_notification_unsubscribe.call_count == 0
    assert retry_availability_unsubscribe.call_count == 0
    run(runtime.async_stop())
    assert retry_notification_unsubscribe.call_count == 1
    assert retry_availability_unsubscribe.call_count == 1


def test_runtime_stop_unsubscribes_once_and_is_idempotent(hass: HomeAssistant, run) -> None:
    runtime, subscriptions, unsubscribes = run(start_runtime_with_subscribe_patch(hass))
    runtime.async_add_notification_listener(lambda notification: None)
    runtime.async_add_availability_listener(lambda available: None)
    _, callback, _ = subscriptions[0]
    callback(mqtt_message("ios_ancs/notification", notification_payload()))

    run(runtime.async_stop())
    run(runtime.async_stop())

    assert [unsubscribe.call_count for unsubscribe in unsubscribes] == [1, 1]
    assert runtime.latest_notification is None


def test_source_runtime_resolves_renamed_entity_and_dispatches(
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
    er.async_get(hass).async_update_entity(
        registered.entity.entity_id,
        new_entity_id="sensor.renamed_ancs_notification",
    )
    runtime, notifications, _ = run(async_make_source_runtime(hass, registered))

    hass.states.async_set(
        "sensor.renamed_ancs_notification",
        "boot1-1-42-aabbcc",
        firmware_notification(),
    )
    run(hass.async_block_till_done())

    assert notifications == [firmware_notification()]
    assert runtime.unique_id == "ios_ancs_A1B2C3:notification"
    assert not hasattr(runtime, "device_entry")
    run(runtime.async_stop())


def test_source_runtime_does_not_replay_existing_startup_state(
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
    hass.states.async_set(
        registered.entity.entity_id,
        "boot1-1-42-aabbcc",
        firmware_notification(),
    )

    runtime, notifications, _ = run(async_make_source_runtime(hass, registered))
    assert notifications == []

    same_relay = firmware_notification(title="Restored title")
    hass.states.async_set(
        registered.entity.entity_id,
        "boot1-1-42-aabbcc",
        same_relay,
    )
    run(hass.async_block_till_done())
    assert notifications == []

    new_notification = firmware_notification(relay_id="boot1-1-43-aabbcc", uid=43)
    hass.states.async_set(
        registered.entity.entity_id,
        "boot1-1-43-aabbcc",
        new_notification,
    )
    run(hass.async_block_till_done())

    assert notifications == [new_notification]
    run(runtime.async_stop())


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


def test_source_runtime_unknown_startup_state_is_ready_without_payload(
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
    hass.states.async_set(registered.entity.entity_id, STATE_UNKNOWN)

    runtime, notifications, availability = run(
        async_make_source_runtime(hass, registered)
    )

    assert notifications == []
    assert availability == [True]
    assert runtime.available is True

    notification = firmware_notification()
    hass.states.async_set(
        registered.entity.entity_id,
        "boot1-1-42-aabbcc",
        notification,
    )
    run(hass.async_block_till_done())

    assert notifications == [notification]
    run(runtime.async_stop())


def test_source_runtime_buffers_notification_until_listener_attaches(
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
    runtime = AncsSourceRuntime(
        hass,
        registered.entity.unique_id,
        "ios_ancs_A1B2C3",
    )
    run(runtime.async_start())

    notification = firmware_notification(
        relay_id="boot1-1-43-aabbcc",
        uid=43,
    )
    hass.states.async_set(
        registered.entity.entity_id,
        "boot1-1-43-aabbcc",
        notification,
    )
    run(hass.async_block_till_done())

    received: list[dict[str, Any]] = []
    runtime.async_add_notification_listener(received.append)

    assert received == [notification]
    run(runtime.async_stop())


def test_source_runtime_keeps_event_replay_while_detail_listener_is_active(
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
    runtime = AncsSourceRuntime(
        hass,
        registered.entity.unique_id,
        "ios_ancs_A1B2C3",
    )
    run(runtime.async_start())
    details: list[dict[str, Any]] = []
    runtime.async_add_notification_listener(details.append, replay_pending=False)

    notification = firmware_notification(relay_id="between-platforms", uid=43)
    hass.states.async_set(
        registered.entity.entity_id,
        notification["relay_id"],
        notification,
    )
    run(hass.async_block_till_done())
    assert details == [notification]

    events: list[dict[str, Any]] = []
    runtime.async_add_notification_listener(events.append, replay_pending=True)
    assert events == [notification]
    run(runtime.async_stop())


def test_source_runtime_dispatches_firmware_attributes_without_ha_metadata(
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
    runtime, notifications, _ = run(async_make_source_runtime(hass, registered))
    attributes = firmware_notification()
    attributes[ATTR_FRIENDLY_NAME] = "Last notification"

    hass.states.async_set(
        registered.entity.entity_id,
        "boot1-1-42-aabbcc",
        attributes,
    )
    run(hass.async_block_till_done())

    assert notifications == [firmware_notification()]
    assert ATTR_FRIENDLY_NAME not in notifications[0]
    run(runtime.async_stop())


def test_source_runtime_uses_sensor_state_as_relay_id_fallback(
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
    runtime, notifications, _ = run(async_make_source_runtime(hass, registered))
    attributes = firmware_notification()
    attributes.pop("relay_id")

    hass.states.async_set(
        registered.entity.entity_id,
        "boot1-1-42-aabbcc",
        attributes,
    )
    run(hass.async_block_till_done())

    assert notifications[0]["relay_id"] == "boot1-1-42-aabbcc"
    run(runtime.async_stop())


def test_source_runtime_tracks_unavailable_and_recovers_without_replay(
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
    hass.states.async_set(
        registered.entity.entity_id,
        "boot1-1-42-aabbcc",
        firmware_notification(),
    )
    runtime, notifications, availability = run(
        async_make_source_runtime(hass, registered)
    )
    availability.clear()

    hass.states.async_set(registered.entity.entity_id, STATE_UNKNOWN)
    hass.states.async_set(registered.entity.entity_id, STATE_UNAVAILABLE)
    run(hass.async_block_till_done())
    assert notifications == []
    assert availability == [False]
    assert runtime.available is False

    hass.states.async_set(
        registered.entity.entity_id,
        "boot1-1-42-aabbcc",
        firmware_notification(),
    )
    run(hass.async_block_till_done())
    assert notifications == []
    assert availability == [False, True]

    recovered = firmware_notification(relay_id="boot1-1-43-aabbcc", uid=43)
    hass.states.async_set(
        registered.entity.entity_id,
        "boot1-1-43-aabbcc",
        recovered,
    )
    run(hass.async_block_till_done())
    assert notifications == [recovered]
    run(runtime.async_stop())


def test_source_runtime_unknown_state_recovers_from_unavailable_without_dispatch(
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
    hass.states.async_set(
        registered.entity.entity_id,
        "boot1-1-41-aabbcc",
        firmware_notification(relay_id="boot1-1-41-aabbcc", uid=41),
    )
    runtime, notifications, availability = run(
        async_make_source_runtime(hass, registered)
    )
    availability.clear()

    hass.states.async_set(registered.entity.entity_id, STATE_UNAVAILABLE)
    run(hass.async_block_till_done())
    assert runtime.available is False
    assert availability == [False]

    hass.states.async_set(registered.entity.entity_id, STATE_UNKNOWN)
    run(hass.async_block_till_done())

    assert notifications == []
    assert availability == [False, True]
    assert runtime.available is True

    notification = firmware_notification()
    hass.states.async_set(
        registered.entity.entity_id,
        "boot1-1-42-aabbcc",
        notification,
    )
    run(hass.async_block_till_done())

    assert notifications == [notification]
    run(runtime.async_stop())


def test_source_runtime_seeds_initial_ble_connection_false(
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
    status = run(async_register_mqtt_ancs_status(hass, registered))
    hass.states.async_set(status.entity_id, "on", {"ble_connected": False})

    runtime = AncsSourceRuntime(
        hass,
        registered.entity.unique_id,
        "ios_ancs_A1B2C3",
    )
    ble_updates: list[bool | None] = []
    runtime.async_add_ble_connection_listener(ble_updates.append)
    run(runtime.async_start())

    assert runtime.ble_connected is False
    assert ble_updates == [False]
    run(runtime.async_stop())


def test_source_runtime_tracks_ble_connection_transition_to_true(
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
    status = run(async_register_mqtt_ancs_status(hass, registered))
    hass.states.async_set(status.entity_id, "on", {"ble_connected": False})
    runtime, ble_updates, status_entity_id = run(
        async_make_source_runtime_with_status(hass, registered)
    )
    ble_updates.clear()

    hass.states.async_set(status_entity_id, "on", {"ble_connected": True})
    run(hass.async_block_till_done())

    assert runtime.ble_connected is True
    assert ble_updates == [True]
    run(runtime.async_stop())


def test_source_runtime_treats_malformed_ble_connection_attribute_as_unknown(
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
    status = run(async_register_mqtt_ancs_status(hass, registered))
    hass.states.async_set(status.entity_id, "on", {"ble_connected": True})
    runtime, ble_updates, status_entity_id = run(
        async_make_source_runtime_with_status(hass, registered)
    )
    ble_updates.clear()

    hass.states.async_set(status_entity_id, "on", {"ble_connected": "true"})
    run(hass.async_block_till_done())

    assert runtime.ble_connected is None
    assert ble_updates == [None]
    run(runtime.async_stop())


def test_source_runtime_treats_unavailable_ble_status_as_unknown(
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
    status = run(async_register_mqtt_ancs_status(hass, registered))
    hass.states.async_set(status.entity_id, "on", {"ble_connected": False})
    runtime, ble_updates, status_entity_id = run(
        async_make_source_runtime_with_status(hass, registered)
    )
    ble_updates.clear()

    hass.states.async_set(
        status_entity_id,
        STATE_UNAVAILABLE,
        {"ble_connected": True},
    )
    run(hass.async_block_till_done())

    assert runtime.ble_connected is None
    assert ble_updates == [None]
    run(runtime.async_stop())


def test_source_runtime_removes_ble_listener_and_resets_on_stop(
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
    status = run(async_register_mqtt_ancs_status(hass, registered))
    hass.states.async_set(status.entity_id, "on", {"ble_connected": False})
    runtime = AncsSourceRuntime(
        hass,
        registered.entity.unique_id,
        "ios_ancs_A1B2C3",
    )
    ble_updates: list[bool | None] = []
    remove = runtime.async_add_ble_connection_listener(ble_updates.append)
    run(runtime.async_start())
    ble_updates.clear()

    remove()
    hass.states.async_set(status.entity_id, "on", {"ble_connected": True})
    run(hass.async_block_till_done())

    assert runtime.ble_connected is True
    assert ble_updates == []

    run(runtime.async_stop())
    hass.states.async_set(status.entity_id, "on", {"ble_connected": False})
    run(hass.async_block_till_done())

    assert runtime.ble_connected is None
    assert ble_updates == []


@pytest.mark.parametrize(
    ("rejected", "recovered"),
    [
        ({"complete": False}, {"complete": True}),
        ({"pre_existing": True}, {"pre_existing": False}),
        ({"event": "removed"}, {"event": "added"}),
        ({"app_id": HA_ECHO_APP_ID}, {"app_id": "com.example.chat"}),
    ],
)
def test_source_runtime_rejected_startup_state_does_not_consume_relay_id(
    registry_hass: HomeAssistant,
    run,
    rejected: dict[str, object],
    recovered: dict[str, object],
) -> None:
    hass = registry_hass
    registered = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_A1B2C3",
            device_name="Kitchen Relay",
        )
    )
    hass.states.async_set(
        registered.entity.entity_id,
        "boot1-1-42-aabbcc",
        firmware_notification(**rejected),
    )
    runtime, notifications, _ = run(async_make_source_runtime(hass, registered))
    assert notifications == []

    hass.states.async_set(
        registered.entity.entity_id,
        "boot1-1-42-aabbcc",
        firmware_notification(**recovered),
    )
    run(hass.async_block_till_done())

    assert notifications == [firmware_notification(**recovered)]
    run(runtime.async_stop())


def test_source_runtime_stop_removes_listener_but_keeps_mqtt_entity(
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
    runtime, notifications, _ = run(async_make_source_runtime(hass, registered))

    run(runtime.async_stop())
    hass.states.async_set(
        registered.entity.entity_id,
        "boot1-1-42-aabbcc",
        firmware_notification(),
    )
    run(hass.async_block_till_done())

    assert notifications == []
    assert hass.states.get(registered.entity.entity_id) is not None
    assert er.async_get(hass).async_get(registered.entity.entity_id) is not None


def test_source_runtime_missing_registry_source_raises_not_ready(
    registry_hass: HomeAssistant, run
) -> None:
    runtime = AncsSourceRuntime(
        registry_hass,
        "missing_last_notification",
        "missing",
    )

    with pytest.raises(ConfigEntryNotReady, match="missing_last_notification"):
        run(runtime.async_start())


def test_setup_entry_stores_runtime_and_unload_stops_it(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    entry = ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="HA iOS ANCS (ios_ancs)",
        data={CONF_BASE_TOPIC: "ios_ancs"},
        source="user",
        unique_id="ios_ancs",
        discovery_keys=EMPTY_DISCOVERY_KEYS,
        options={},
        subentries_data={},
    )
    with patch.object(
        hass.config_entries,
        "async_setup",
        new=AsyncMock(return_value=True),
    ):
        run(hass.config_entries.async_add(entry))

    with patch("custom_components.ha_ios_ancs.AncsMqttRuntime") as runtime_cls:
        runtime = runtime_cls.return_value
        runtime.async_start = AsyncMock()
        runtime.async_stop = AsyncMock()
        hass.config_entries.async_forward_entry_setups = AsyncMock()
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

        async def setup_with_locked_entry() -> bool:
            async with entry.setup_lock:
                return await async_setup_entry(hass, entry)

        assert run(setup_with_locked_entry()) is True
        assert entry.runtime_data is runtime
        runtime_cls.assert_called_once_with(hass, "ios_ancs")
        runtime.async_start.assert_awaited_once()
        hass.config_entries.async_forward_entry_setups.assert_awaited_once()

        async def unload_with_locked_entry() -> bool:
            async with entry.setup_lock:
                with patch(
                    "custom_components.ha_ios_ancs.er.async_entries_for_config_entry",
                    return_value=[],
                ):
                    return await async_unload_entry(hass, entry)

        assert run(unload_with_locked_entry()) is True
        hass.config_entries.async_unload_platforms.assert_awaited_once()
        runtime.async_stop.assert_awaited_once()
        assert entry.runtime_data is None


def test_setup_entry_raises_not_ready_when_mqtt_client_unavailable(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    entry = ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="HA iOS ANCS (ios_ancs)",
        data={CONF_BASE_TOPIC: "ios_ancs"},
        source="user",
        unique_id="ios_ancs",
        discovery_keys=EMPTY_DISCOVERY_KEYS,
        options={},
        subentries_data={},
    )
    with patch.object(
        hass.config_entries,
        "async_setup",
        new=AsyncMock(return_value=True),
    ):
        run(hass.config_entries.async_add(entry))
    subscribe = AsyncMock()

    async def fake_wait_for_client(hass: HomeAssistant) -> bool:
        return False

    mqtt_api = SimpleNamespace(
        async_wait_for_mqtt_client=fake_wait_for_client,
        async_subscribe=subscribe,
    )

    with patch("custom_components.ha_ios_ancs.runtime._get_mqtt_api", return_value=mqtt_api):
        with pytest.raises(ConfigEntryNotReady):
            run(async_setup_entry(hass, entry))

    subscribe.assert_not_awaited()
    assert getattr(entry, "runtime_data", None) is None
