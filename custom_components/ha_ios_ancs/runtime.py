"""MQTT runtime for HA iOS ANCS."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback

from .const import AVAILABILITY_TOPIC_SUFFIX, NOTIFICATION_TOPIC_SUFFIX
from .notification import RelayIdWindow, parse_notification

_QOS = 1

type NotificationListener = Callable[[dict[str, Any]], None]
type AvailabilityListener = Callable[[bool | None], None]


def _get_mqtt_api() -> Any:
    from homeassistant.components import mqtt

    return mqtt


class AncsMqttRuntime:
    """Manage MQTT subscriptions and listeners for HA iOS ANCS."""

    def __init__(self, hass: HomeAssistant, base_topic: str) -> None:
        self._hass = hass
        self._base_topic = base_topic
        self._notification_topic = f"{base_topic}/{NOTIFICATION_TOPIC_SUFFIX}"
        self._availability_topic = f"{base_topic}/{AVAILABILITY_TOPIC_SUFFIX}"
        self._seen = RelayIdWindow()
        self._notification_listeners: list[NotificationListener] = []
        self._availability_listeners: list[AvailabilityListener] = []
        self._unsubscribes: list[CALLBACK_TYPE] = []
        self._available: bool | None = None

    @property
    def available(self) -> bool | None:
        """Return current device availability, or None when unknown."""

        return self._available

    async def async_start(self) -> None:
        """Wait for MQTT and subscribe to notification and availability topics."""

        if self._unsubscribes:
            return

        mqtt_api = _get_mqtt_api()
        if not await mqtt_api.async_wait_for_mqtt_client(self._hass):
            raise ConfigEntryNotReady("MQTT client is not available")

        unsubscribes: list[CALLBACK_TYPE] = []
        try:
            unsubscribes.append(
                await mqtt_api.async_subscribe(
                    self._hass,
                    self._notification_topic,
                    self._handle_notification,
                    _QOS,
                )
            )
            unsubscribes.append(
                await mqtt_api.async_subscribe(
                    self._hass,
                    self._availability_topic,
                    self._handle_availability,
                    _QOS,
                )
            )
        except Exception:
            for unsubscribe in unsubscribes:
                unsubscribe()
            raise

        self._unsubscribes = unsubscribes

    async def async_stop(self) -> None:
        """Unsubscribe and clear listeners."""

        unsubscribes = self._unsubscribes
        self._unsubscribes = []
        for unsubscribe in unsubscribes:
            unsubscribe()
        self._notification_listeners.clear()
        self._availability_listeners.clear()

    @callback
    def async_add_notification_listener(
        self, listener: NotificationListener
    ) -> CALLBACK_TYPE:
        """Add a notification listener and return a removal callback."""

        self._notification_listeners.append(listener)

        @callback
        def remove_listener() -> None:
            if listener in self._notification_listeners:
                self._notification_listeners.remove(listener)

        return remove_listener

    @callback
    def async_add_availability_listener(
        self, listener: AvailabilityListener
    ) -> CALLBACK_TYPE:
        """Add an availability listener and return a removal callback."""

        self._availability_listeners.append(listener)

        @callback
        def remove_listener() -> None:
            if listener in self._availability_listeners:
                self._availability_listeners.remove(listener)

        return remove_listener

    @callback
    def _handle_notification(self, msg: Any) -> None:
        notification = parse_notification(msg.payload, self._seen)
        if notification is None:
            return

        for listener in tuple(self._notification_listeners):
            listener(notification)

    @callback
    def _handle_availability(self, msg: Any) -> None:
        available = self._availability_from_payload(msg.payload)
        if available is None or available is self._available:
            return

        self._available = available
        for listener in tuple(self._availability_listeners):
            listener(available)

    @staticmethod
    def _availability_from_payload(payload: str | bytes) -> bool | None:
        if payload == "online" or payload == b"online":
            return True
        if payload == "offline" or payload == b"offline":
            return False
        return None
