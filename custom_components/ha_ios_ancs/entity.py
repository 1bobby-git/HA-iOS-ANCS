"""Shared entities and payload extraction for HA iOS ANCS."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .runtime import AncsRuntime

MAX_STATE_TEXT_LENGTH = 255


def nested_value(payload: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    """Return a nested payload value, or None when the path is malformed."""

    value: Any = payload
    for key in path:
        if not isinstance(value, Mapping) or key not in value:
            return None
        value = value[key]
    return value


def as_text(value: Any) -> str | None:
    """Return only literal string values."""

    return value if isinstance(value, str) else None


def as_integer(value: Any) -> int | None:
    """Return only literal integer values, excluding booleans."""

    return value if isinstance(value, int) and not isinstance(value, bool) else None


def as_boolean(value: Any) -> bool | None:
    """Return only literal boolean values."""

    return value if isinstance(value, bool) else None


def preview_text(value: str) -> str:
    """Limit text used as a Home Assistant entity state."""

    return value[:MAX_STATE_TEXT_LENGTH]


def raw_payload_attributes(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a defensive deep copy of an accepted notification payload."""

    return deepcopy(dict(payload))


class AncsNotificationEntity:
    """Share push updates, availability, and device attachment."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        entry: ConfigEntry,
        runtime: AncsRuntime,
        platform: Platform,
        key: str,
        *,
        unique_id: str | None = None,
        replay_pending: bool = False,
    ) -> None:
        """Initialize a notification-backed entity."""

        identity = entry.unique_id or entry.entry_id
        self._attr_unique_id = unique_id or f"{identity}:{platform.value}:{key}"
        self._runtime = runtime
        self._payload = runtime.latest_notification
        self._replay_pending = replay_pending
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
        )
        self._attr_available = runtime.available is not False

    async def async_added_to_hass(self) -> None:
        """Register runtime listeners after the entity is attached."""

        await super().async_added_to_hass()
        self.async_on_remove(
            self._runtime.async_add_notification_listener(
                self._handle_notification,
                replay_pending=self._replay_pending,
            )
        )
        self.async_on_remove(
            self._runtime.async_add_availability_listener(
                self._handle_availability
            )
        )

    @callback
    def _handle_notification(self, payload: dict[str, Any]) -> None:
        """Store a defensive notification snapshot and write entity state."""

        self._payload = deepcopy(payload)
        self.async_write_ha_state()

    @callback
    def _handle_availability(self, available: bool | None) -> None:
        """Update entity availability when the runtime reports a transition."""

        if available is None:
            return
        self._attr_available = available
        self.async_write_ha_state()
