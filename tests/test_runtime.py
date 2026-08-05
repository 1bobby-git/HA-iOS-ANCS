from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.core import HomeAssistant

from custom_components.ha_ios_ancs import async_setup_entry, async_unload_entry
from custom_components.ha_ios_ancs.const import CONF_BASE_TOPIC, DOMAIN
from custom_components.ha_ios_ancs.runtime import AncsMqttRuntime


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

    assert [(topic, qos) for topic, _, qos in subscriptions] == [
        ("ios_ancs/notification", 1),
        ("ios_ancs/availability", 1),
    ]
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
    runtime, _, unsubscribes = run(start_runtime_with_subscribe_patch(hass))
    runtime.async_add_notification_listener(lambda notification: None)
    runtime.async_add_availability_listener(lambda available: None)

    run(runtime.async_stop())
    run(runtime.async_stop())

    assert [unsubscribe.call_count for unsubscribe in unsubscribes] == [1, 1]


def test_setup_entry_stores_runtime_and_unload_stops_it(hass: HomeAssistant, run) -> None:
    entry = ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="HA iOS ANCS (ios_ancs)",
        data={CONF_BASE_TOPIC: "ios_ancs"},
        source="user",
        unique_id="ios_ancs",
        discovery_keys={},
        options={},
        subentries_data={},
    )

    with patch("custom_components.ha_ios_ancs.AncsMqttRuntime") as runtime_cls:
        runtime = runtime_cls.return_value
        runtime.async_start = AsyncMock()
        runtime.async_stop = AsyncMock()

        assert run(async_setup_entry(hass, entry)) is True
        assert entry.runtime_data is runtime
        runtime_cls.assert_called_once_with(hass, "ios_ancs")
        runtime.async_start.assert_awaited_once()

        assert run(async_unload_entry(hass, entry)) is True
        runtime.async_stop.assert_awaited_once()
        assert entry.runtime_data is None


def test_setup_entry_raises_not_ready_when_mqtt_client_unavailable(hass: HomeAssistant, run) -> None:
    entry = ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="HA iOS ANCS (ios_ancs)",
        data={CONF_BASE_TOPIC: "ios_ancs"},
        source="user",
        unique_id="ios_ancs",
        discovery_keys={},
        options={},
        subentries_data={},
    )
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
