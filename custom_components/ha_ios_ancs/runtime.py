"""MQTT runtime for HA iOS ANCS."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from typing import Any, Protocol

from homeassistant.const import ATTR_FRIENDLY_NAME, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    AVAILABILITY_TOPIC_SUFFIX,
    DEFAULT_RELAY_ID_WINDOW_SIZE,
    EVENT_TYPE_NOTIFICATION,
    NOTIFICATION_TOPIC_SUFFIX,
)
from .notification import RelayIdWindow, parse_notification, parse_notification_data
from .source import async_resolve_ancs_source

_QOS = 1

type NotificationListener = Callable[[dict[str, Any]], None]
type AvailabilityListener = Callable[[bool | None], None]


class AncsRuntime(Protocol):
    """Shared runtime contract consumed by the event platform."""

    @property
    def available(self) -> bool | None:
        """Return current source availability."""
        raise NotImplementedError

    @property
    def unique_id(self) -> str:
        """Return the notification event unique ID."""
        raise NotImplementedError

    @property
    def device_entry(self) -> dr.DeviceEntry | None:
        """Return an existing device entry when the source owns one."""
        raise NotImplementedError

    async def async_start(self) -> None:
        """Start the runtime."""
        raise NotImplementedError

    async def async_stop(self) -> None:
        """Stop the runtime."""
        raise NotImplementedError

    def async_add_notification_listener(
        self, listener: NotificationListener
    ) -> CALLBACK_TYPE:
        """Add a notification listener."""
        raise NotImplementedError

    def async_add_availability_listener(
        self, listener: AvailabilityListener
    ) -> CALLBACK_TYPE:
        """Add an availability listener."""
        raise NotImplementedError


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
        # Subscriptions can receive data before the EventEntity listener attaches.
        self._pending_notifications: deque[dict[str, Any]] = deque(
            maxlen=DEFAULT_RELAY_ID_WINDOW_SIZE
        )
        self._availability_listeners: list[AvailabilityListener] = []
        self._unsubscribes: list[CALLBACK_TYPE] = []
        self._start_lock = asyncio.Lock()
        self._available: bool | None = None

    @property
    def available(self) -> bool | None:
        """Return current device availability, or None when unknown."""

        return self._available

    @property
    def unique_id(self) -> str:
        """Return the legacy topic-backed event unique ID."""

        return f"{self._base_topic}:{EVENT_TYPE_NOTIFICATION}"

    @property
    def device_entry(self) -> dr.DeviceEntry | None:
        """Return no external device for a legacy topic entry."""

        return None

    async def async_start(self) -> None:
        """Wait for MQTT and subscribe to notification and availability topics."""

        async with self._start_lock:
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

        async with self._start_lock:
            unsubscribes = self._unsubscribes
            self._unsubscribes = []
            for unsubscribe in unsubscribes:
                unsubscribe()
            self._notification_listeners.clear()
            self._pending_notifications.clear()
            self._availability_listeners.clear()

    @callback
    def async_add_notification_listener(
        self, listener: NotificationListener
    ) -> CALLBACK_TYPE:
        """Add a notification listener and return a removal callback."""

        self._notification_listeners.append(listener)
        while self._pending_notifications:
            listener(self._pending_notifications.popleft())

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

        if not self._notification_listeners:
            self._pending_notifications.append(notification)
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


class AncsSourceRuntime:
    """Consume notifications from an existing MQTT sensor entity."""

    def __init__(
        self,
        hass: HomeAssistant,
        source_entity_unique_id: str,
        mqtt_device_identifier: str,
    ) -> None:
        self._hass = hass
        self._source_entity_unique_id = source_entity_unique_id
        self._mqtt_device_identifier = mqtt_device_identifier
        self._seen = RelayIdWindow()
        self._notification_listeners: list[NotificationListener] = []
        # State changes can arrive before the EventEntity listener attaches.
        self._pending_notifications: deque[dict[str, Any]] = deque(
            maxlen=DEFAULT_RELAY_ID_WINDOW_SIZE
        )
        self._availability_listeners: list[AvailabilityListener] = []
        self._unsubscribe: CALLBACK_TYPE | None = None
        self._start_lock = asyncio.Lock()
        self._available: bool | None = None
        self._device_entry: dr.DeviceEntry | None = None

    @property
    def available(self) -> bool | None:
        """Return whether the MQTT source entity is available."""

        return self._available

    @property
    def unique_id(self) -> str:
        """Return the device-backed event unique ID."""

        return f"{self._mqtt_device_identifier}:{EVENT_TYPE_NOTIFICATION}"

    @property
    def device_entry(self) -> dr.DeviceEntry | None:
        """Return the MQTT-owned device entry resolved at startup."""

        return self._device_entry

    async def async_start(self) -> None:
        """Resolve the source entity, seed dedupe, and track state changes."""

        async with self._start_lock:
            if self._unsubscribe is not None:
                return

            source = async_resolve_ancs_source(
                self._hass,
                self._source_entity_unique_id,
                self._mqtt_device_identifier,
            )
            if source is None:
                raise ConfigEntryNotReady(
                    "MQTT ANCS source entity "
                    f"{self._source_entity_unique_id} is not registered"
                )

            device_entry = dr.async_get(self._hass).async_get(source.device_id)
            if device_entry is None:
                raise ConfigEntryNotReady(
                    f"MQTT ANCS source device {source.device_id} is not registered"
                )
            self._device_entry = device_entry

            current_state = self._hass.states.get(source.entity_id)
            if current_state is None or current_state.state in (
                STATE_UNKNOWN,
                STATE_UNAVAILABLE,
            ):
                self._set_available(False)
            else:
                self._set_available(True)
                parse_notification_data(
                    self._notification_data_from_state(current_state),
                    self._seen,
                )

            self._unsubscribe = async_track_state_change_event(
                self._hass,
                source.entity_id,
                self._handle_source_state_change,
            )

    async def async_stop(self) -> None:
        """Remove the source listener and integration-owned callbacks."""

        async with self._start_lock:
            if self._unsubscribe is not None:
                self._unsubscribe()
                self._unsubscribe = None
            self._notification_listeners.clear()
            self._pending_notifications.clear()
            self._availability_listeners.clear()

    @callback
    def async_add_notification_listener(
        self, listener: NotificationListener
    ) -> CALLBACK_TYPE:
        """Add a notification listener and return a removal callback."""

        self._notification_listeners.append(listener)
        while self._pending_notifications:
            listener(self._pending_notifications.popleft())

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

    @staticmethod
    def _notification_data_from_state(state: State) -> dict[str, Any]:
        """Copy firmware attributes and fill relay ID from sensor state."""

        data = dict(state.attributes)
        data.pop(ATTR_FRIENDLY_NAME, None)
        relay_id = data.get("relay_id")
        if not isinstance(relay_id, str) or not relay_id.strip():
            data["relay_id"] = state.state
        return data

    @callback
    def _handle_source_state_change(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Dispatch accepted notifications from MQTT sensor state changes."""

        new_state = event.data["new_state"]
        if new_state is None or new_state.state in (
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        ):
            self._set_available(False)
            return

        self._set_available(True)
        notification = parse_notification_data(
            self._notification_data_from_state(new_state),
            self._seen,
        )
        if notification is None:
            return

        if not self._notification_listeners:
            self._pending_notifications.append(notification)
            return

        for listener in tuple(self._notification_listeners):
            listener(notification)

    @callback
    def _set_available(self, available: bool) -> None:
        """Update availability and notify listeners only on a transition."""

        if self._available is available:
            return
        self._available = available
        for listener in tuple(self._availability_listeners):
            listener(available)
