"""Event platform for iOS ANCS."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import EVENT_TYPE_NOTIFICATION
from .entity import AncsNotificationEntity
from .runtime import AncsRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up iOS ANCS event entities."""

    runtime: AncsRuntime = entry.runtime_data
    async_add_entities([AncsNotificationEvent(entry, runtime)])


class AncsNotificationEvent(AncsNotificationEntity, EventEntity):
    """Native Home Assistant event entity for ANCS notifications."""

    _attr_event_types: list[str] = [EVENT_TYPE_NOTIFICATION]
    _attr_translation_key: str | None = "notification"

    def __init__(self, entry: ConfigEntry, runtime: AncsRuntime) -> None:
        """Initialize the ANCS notification event entity."""

        super().__init__(
            entry,
            runtime,
            Platform.EVENT,
            "notification",
            unique_id=runtime.unique_id,
            replay_pending=True,
        )

    @callback
    def _handle_notification(self, payload: dict[str, Any]) -> None:
        """Trigger a Home Assistant event from a parsed ANCS payload."""

        self._payload = deepcopy(payload)
        self._trigger_event(EVENT_TYPE_NOTIFICATION, deepcopy(payload))
        self.async_write_ha_state()
