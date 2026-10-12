"""MQTT runtime for iOS ANCS."""

from __future__ import annotations

import asyncio
import json
from time import monotonic
from collections import deque
from collections.abc import Callable
from copy import deepcopy
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
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    AVAILABILITY_TOPIC_SUFFIX,
    DEFAULT_RELAY_ID_WINDOW_SIZE,
    EVENT_TYPE_NOTIFICATION,
    NOTIFICATION_TOPIC_SUFFIX,
)
from .diagnostics import STATUS_TTL_SECONDS, parse_diagnostics
from .notification import RelayIdWindow, parse_notification, parse_notification_data
from .source import async_resolve_ancs_source, async_resolve_ancs_status_entity

_QOS = 1

type NotificationListener = Callable[[dict[str, Any]], None]
type AvailabilityListener = Callable[[bool | None], None]
type BleConnectionListener = Callable[[bool | None], None]


class AncsRuntime(Protocol):
    """Shared runtime contract consumed by notification entity platforms."""

    @property
    def available(self) -> bool | None:
        """Return current source availability."""
        raise NotImplementedError

    @property
    def ble_connected(self) -> bool | None:
        """Return current BLE connection state."""
        raise NotImplementedError

    @property
    def diagnostics(self) -> dict[str, Any]:
        """Return sanitized connection diagnostics."""
        raise NotImplementedError

    @property
    def diagnostics_fresh(self) -> bool:
        """Whether the latest connection sample is demonstrably current."""
        raise NotImplementedError

    def async_add_diagnostics_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        raise NotImplementedError

    @property
    def unique_id(self) -> str:
        """Return the notification event unique ID."""
        raise NotImplementedError

    @property
    def latest_notification(self) -> dict[str, Any] | None:
        """Return a defensive copy of the latest accepted notification."""
        raise NotImplementedError

    def restore_notification(
        self, notification: dict[str, Any] | None
    ) -> bool:
        """Restore a saved notification without replaying it as an event."""
        raise NotImplementedError

    async def async_start(self) -> None:
        """Start the runtime."""
        raise NotImplementedError

    async def async_stop(self) -> None:
        """Stop the runtime."""
        raise NotImplementedError

    def async_add_notification_listener(
        self,
        listener: NotificationListener,
        *,
        replay_pending: bool = True,
    ) -> CALLBACK_TYPE:
        """Add a listener, optionally replaying queued event notifications."""
        raise NotImplementedError

    def async_add_availability_listener(
        self, listener: AvailabilityListener
    ) -> CALLBACK_TYPE:
        """Add an availability listener."""
        raise NotImplementedError

    def async_add_ble_connection_listener(
        self, listener: BleConnectionListener
    ) -> CALLBACK_TYPE:
        """Add a BLE connection listener."""
        raise NotImplementedError


def _get_mqtt_api() -> Any:
    from homeassistant.components import mqtt

    return mqtt


class _DiagnosticsRuntime:
    """Connection freshness is independent of the last notification's age."""

    def _init_diagnostics(self) -> None:
        self._diagnostics: dict[str, Any] = {}
        self._diagnostics_listeners: list[Callable[[], None]] = []
        self._diagnostics_timer: asyncio.TimerHandle | None = None
        self._diagnostics_received_at: float | None = None
        self._diagnostics_source_uptime: int | None = None
        self._diagnostics_generation = 0

    @property
    def diagnostics(self) -> dict[str, Any]:
        return deepcopy(self._diagnostics)

    @property
    def diagnostics_fresh(self) -> bool:
        return (self._diagnostics_received_at is not None and
                monotonic() - self._diagnostics_received_at < STATUS_TTL_SECONDS)

    @callback
    def async_add_diagnostics_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        self._diagnostics_listeners.append(listener)
        @callback
        def remove() -> None:
            if listener in self._diagnostics_listeners:
                self._diagnostics_listeners.remove(listener)
        return remove

    @callback
    def _notify_diagnostics(self) -> None:
        for listener in tuple(self._diagnostics_listeners):
            listener()

    @callback
    def _expire_diagnostics(self, generation: int | None = None) -> None:
        if generation is not None and generation != self._diagnostics_generation:
            return
        if self._diagnostics_timer is not None:
            self._diagnostics_timer.cancel()
            self._diagnostics_timer = None
        self._diagnostics_generation += 1
        self._diagnostics_received_at = None
        if self._ble_connected is not None:
            self._ble_connected = None
            for listener in tuple(self._ble_connection_listeners):
                listener(None)
        self._notify_diagnostics()

    @callback
    def _update_diagnostics(self, data: Any, *, live: bool, preserve_fresh: bool = False) -> None:
        parsed = parse_diagnostics(data)
        self._diagnostics = parsed
        if preserve_fresh and self.diagnostics_fresh:
            self._notify_diagnostics()
            return
        if self._diagnostics_timer is not None:
            self._diagnostics_timer.cancel()
            self._diagnostics_timer = None
        self._diagnostics_generation += 1
        self._diagnostics_received_at = monotonic() if live else None
        if live:
            self._diagnostics_timer = self._hass.loop.call_later(
                STATUS_TTL_SECONDS, self._expire_diagnostics, self._diagnostics_generation
            )
        self._notify_diagnostics()

    def _stop_diagnostics(self) -> None:
        self._diagnostics_generation += 1
        if self._diagnostics_timer is not None:
            self._diagnostics_timer.cancel()
            self._diagnostics_timer = None
        self._diagnostics_received_at = None
        self._diagnostics_source_uptime = None
        self._diagnostics.clear()
        self._diagnostics_listeners.clear()


class AncsMqttRuntime(_DiagnosticsRuntime):
    """Manage MQTT subscriptions and listeners for iOS ANCS."""

    def __init__(self, hass: HomeAssistant, base_topic: str) -> None:
        self._hass = hass
        self._init_diagnostics()
        self._base_topic = base_topic
        self._notification_topic = f"{base_topic}/{NOTIFICATION_TOPIC_SUFFIX}"
        self._availability_topic = f"{base_topic}/{AVAILABILITY_TOPIC_SUFFIX}"
        self._state_topic = f"{base_topic}/state"
        self._seen = RelayIdWindow()
        self._notification_listeners: list[NotificationListener] = []
        self._notification_replay_listeners: list[NotificationListener] = []
        # Subscriptions can receive data before the EventEntity listener attaches.
        self._pending_notifications: deque[dict[str, Any]] = deque(
            maxlen=DEFAULT_RELAY_ID_WINDOW_SIZE
        )
        self._availability_listeners: list[AvailabilityListener] = []
        self._ble_connection_listeners: list[BleConnectionListener] = []
        self._unsubscribes: list[CALLBACK_TYPE] = []
        self._start_lock = asyncio.Lock()
        self._available: bool | None = None
        self._ble_connected: bool | None = None
        self._latest_notification: dict[str, Any] | None = None

    @property
    def available(self) -> bool | None:
        """Return current device availability, or None when unknown."""

        return self._available

    @property
    def ble_connected(self) -> bool | None:
        """Return current BLE connection state, or None when unknown."""

        return self._ble_connected

    @property
    def unique_id(self) -> str:
        """Return the legacy topic-backed event unique ID."""

        return f"{self._base_topic}:{EVENT_TYPE_NOTIFICATION}"

    @property
    def latest_notification(self) -> dict[str, Any] | None:
        """Return a defensive copy of the latest accepted notification."""

        return (
            None
            if self._latest_notification is None
            else deepcopy(self._latest_notification)
        )

    def restore_notification(
        self, notification: dict[str, Any] | None
    ) -> bool:
        """Restore a saved notification without queuing an event replay."""

        if notification is None:
            return False
        restored = parse_notification_data(deepcopy(notification), self._seen)
        if restored is None:
            return False
        self._latest_notification = deepcopy(restored)
        return True

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
                unsubscribes.append(
                    await mqtt_api.async_subscribe(
                        self._hass, self._state_topic, self._handle_status, _QOS
                    )
                )
            except (Exception, asyncio.CancelledError):
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
            self._stop_diagnostics()
            self._notification_listeners.clear()
            self._notification_replay_listeners.clear()
            self._pending_notifications.clear()
            self._availability_listeners.clear()
            self._ble_connection_listeners.clear()
            self._ble_connected = None
            self._latest_notification = None

    @callback
    def async_add_notification_listener(
        self,
        listener: NotificationListener,
        *,
        replay_pending: bool = True,
    ) -> CALLBACK_TYPE:
        """Add a notification listener and return a removal callback."""

        self._notification_listeners.append(listener)
        if replay_pending:
            self._notification_replay_listeners.append(listener)
            while self._pending_notifications:
                listener(deepcopy(self._pending_notifications.popleft()))

        @callback
        def remove_listener() -> None:
            if listener in self._notification_listeners:
                self._notification_listeners.remove(listener)
            if listener in self._notification_replay_listeners:
                self._notification_replay_listeners.remove(listener)

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
    def async_add_ble_connection_listener(
        self, listener: BleConnectionListener
    ) -> CALLBACK_TYPE:
        """Add a BLE connection listener and return a removal callback."""

        self._ble_connection_listeners.append(listener)

        @callback
        def remove_listener() -> None:
            if listener in self._ble_connection_listeners:
                self._ble_connection_listeners.remove(listener)

        return remove_listener

    @callback
    def _handle_notification(self, msg: Any) -> None:
        notification = parse_notification(msg.payload, self._seen)
        if notification is None:
            return

        if bool(getattr(msg, "retain", False)):
            if self._latest_notification is None:
                self._latest_notification = deepcopy(notification)
            return
        self._latest_notification = deepcopy(notification)
        if not self._notification_replay_listeners:
            self._pending_notifications.append(deepcopy(notification))
        if not self._notification_listeners:
            return

        for listener in tuple(self._notification_listeners):
            listener(deepcopy(notification))

    @callback
    def _handle_status(self, msg: Any) -> None:
        try:
            data = json.loads(msg.payload)
        except (TypeError, ValueError, UnicodeDecodeError):
            return
        if not isinstance(data, dict):
            return
        live = not bool(getattr(msg, "retain", False))
        self._update_diagnostics(data, live=live)
        connected = self._diagnostics.get("ble_connected") if live else None
        if connected is not self._ble_connected:
            self._ble_connected = connected
            for listener in tuple(self._ble_connection_listeners):
                listener(connected)

    @callback
    def _handle_availability(self, msg: Any) -> None:
        available = self._availability_from_payload(msg.payload)
        if available is None or available is self._available:
            return

        self._available = available
        if available is False:
            self._expire_diagnostics()
        for listener in tuple(self._availability_listeners):
            listener(available)

    @staticmethod
    def _availability_from_payload(payload: str | bytes) -> bool | None:
        if payload == "online" or payload == b"online":
            return True
        if payload == "offline" or payload == b"offline":
            return False
        return None


class AncsSourceRuntime(_DiagnosticsRuntime):
    """Consume notifications from an existing MQTT sensor entity."""

    def __init__(
        self,
        hass: HomeAssistant,
        source_entity_unique_id: str,
        mqtt_device_identifier: str,
    ) -> None:
        self._hass = hass
        self._init_diagnostics()
        self._source_entity_unique_id = source_entity_unique_id
        self._mqtt_device_identifier = mqtt_device_identifier
        self._seen = RelayIdWindow()
        self._notification_listeners: list[NotificationListener] = []
        self._notification_replay_listeners: list[NotificationListener] = []
        # State changes can arrive before the EventEntity listener attaches.
        self._pending_notifications: deque[dict[str, Any]] = deque(
            maxlen=DEFAULT_RELAY_ID_WINDOW_SIZE
        )
        self._availability_listeners: list[AvailabilityListener] = []
        self._ble_connection_listeners: list[BleConnectionListener] = []
        self._unsubscribe: CALLBACK_TYPE | None = None
        self._status_unsubscribe: CALLBACK_TYPE | None = None
        self._start_lock = asyncio.Lock()
        self._available: bool | None = None
        self._ble_connected: bool | None = None
        self._latest_notification: dict[str, Any] | None = None

    @property
    def available(self) -> bool | None:
        """Return whether the MQTT source entity is available."""

        return self._available

    @property
    def ble_connected(self) -> bool | None:
        """Return current BLE connection state, or None when unknown."""

        return self._ble_connected

    @property
    def unique_id(self) -> str:
        """Return the device-backed event unique ID."""

        return f"{self._mqtt_device_identifier}:{EVENT_TYPE_NOTIFICATION}"

    @property
    def latest_notification(self) -> dict[str, Any] | None:
        """Return a defensive copy of the latest accepted notification."""

        return (
            None
            if self._latest_notification is None
            else deepcopy(self._latest_notification)
        )

    def restore_notification(
        self, notification: dict[str, Any] | None
    ) -> bool:
        """Restore a saved notification without queuing an event replay."""

        if notification is None:
            return False
        restored = parse_notification_data(deepcopy(notification), self._seen)
        if restored is None:
            return False
        self._latest_notification = deepcopy(restored)
        return True

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

            current_state = self._hass.states.get(source.entity_id)
            if current_state is None or current_state.state == STATE_UNAVAILABLE:
                self._set_available(False)
            elif current_state.state == STATE_UNKNOWN:
                self._set_available(True)
            else:
                self._set_available(True)
                seed = parse_notification_data(
                    self._notification_data_from_state(current_state),
                    self._seen,
                )
                if seed is not None:
                    self._latest_notification = deepcopy(seed)

            self._unsubscribe = async_track_state_change_event(
                self._hass,
                source.entity_id,
                self._handle_source_state_change,
            )
            status_entity_id = async_resolve_ancs_status_entity(
                self._hass,
                self._mqtt_device_identifier,
            )
            if status_entity_id is not None:
                initial_status = self._hass.states.get(status_entity_id)
                if initial_status is not None:
                    self._update_diagnostics(dict(initial_status.attributes), live=False)
                    uptime = initial_status.attributes.get("uptime_seconds")
                    self._diagnostics_source_uptime = uptime if type(uptime) is int else None
                self._set_ble_connected(
                    None if self._diagnostics.get("diagnostics_version") == 1
                    else self._ble_connected_from_state(initial_status)
                )
                self._status_unsubscribe = async_track_state_change_event(
                    self._hass,
                    status_entity_id,
                    self._handle_status_state_change,
                )

    async def async_stop(self) -> None:
        """Remove the source listener and integration-owned callbacks."""

        async with self._start_lock:
            if self._unsubscribe is not None:
                self._unsubscribe()
                self._unsubscribe = None
            if self._status_unsubscribe is not None:
                self._status_unsubscribe()
                self._status_unsubscribe = None
            self._stop_diagnostics()
            self._notification_listeners.clear()
            self._notification_replay_listeners.clear()
            self._pending_notifications.clear()
            self._availability_listeners.clear()
            self._ble_connection_listeners.clear()
            self._ble_connected = None
            self._latest_notification = None

    @callback
    def async_add_notification_listener(
        self,
        listener: NotificationListener,
        *,
        replay_pending: bool = True,
    ) -> CALLBACK_TYPE:
        """Add a notification listener and return a removal callback."""

        self._notification_listeners.append(listener)
        if replay_pending:
            self._notification_replay_listeners.append(listener)
            while self._pending_notifications:
                listener(deepcopy(self._pending_notifications.popleft()))

        @callback
        def remove_listener() -> None:
            if listener in self._notification_listeners:
                self._notification_listeners.remove(listener)
            if listener in self._notification_replay_listeners:
                self._notification_replay_listeners.remove(listener)

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
    def async_add_ble_connection_listener(
        self, listener: BleConnectionListener
    ) -> CALLBACK_TYPE:
        """Add a BLE connection listener and return a removal callback."""

        self._ble_connection_listeners.append(listener)

        @callback
        def remove_listener() -> None:
            if listener in self._ble_connection_listeners:
                self._ble_connection_listeners.remove(listener)

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
        if new_state is None or new_state.state == STATE_UNAVAILABLE:
            self._set_available(False)
            return
        if new_state.state == STATE_UNKNOWN:
            self._set_available(True)
            return

        self._set_available(True)
        notification = parse_notification_data(
            self._notification_data_from_state(new_state),
            self._seen,
        )
        if notification is None:
            return

        self._latest_notification = deepcopy(notification)
        if not self._notification_replay_listeners:
            self._pending_notifications.append(deepcopy(notification))
        if not self._notification_listeners:
            return

        for listener in tuple(self._notification_listeners):
            listener(deepcopy(notification))

    @callback
    def _handle_status_state_change(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Dispatch BLE connection state changes from MQTT status entity."""

        state = event.data["new_state"]
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            self._update_diagnostics({}, live=False)
            self._set_ble_connected(None)
            return
        data = dict(state.attributes)
        uptime = data.get("uptime_seconds")
        previous = self._diagnostics_source_uptime
        # Legacy samples without diagnostics keep existing link compatibility,
        # while the new ready sensor stays unknown rather than guessing false.
        legacy = data.get("diagnostics_version") != 1
        live = legacy or (type(uptime) is int and previous is not None and uptime > previous)
        preserve = not live and type(uptime) is int and uptime == previous
        if type(uptime) is int:
            self._diagnostics_source_uptime = uptime
        self._update_diagnostics(data, live=live, preserve_fresh=preserve)
        self._set_ble_connected(
            self._ble_connected_from_state(state) if self.diagnostics_fresh else None
        )

    @callback
    def _set_available(self, available: bool) -> None:
        """Update availability and notify listeners only on a transition."""

        if self._available is available:
            return
        self._available = available
        if available is False:
            self._expire_diagnostics()
        for listener in tuple(self._availability_listeners):
            listener(available)

    @staticmethod
    def _ble_connected_from_state(state: State | None) -> bool | None:
        """Derive nullable BLE connection state from a status entity state."""

        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        ble_connected = state.attributes.get("ble_connected")
        if isinstance(ble_connected, bool):
            return ble_connected
        return None

    @callback
    def _set_ble_connected(self, ble_connected: bool | None) -> None:
        """Update BLE connection state and notify listeners on transitions."""

        if self._ble_connected is ble_connected:
            return
        self._ble_connected = ble_connected
        for listener in tuple(self._ble_connection_listeners):
            listener(ble_connected)
