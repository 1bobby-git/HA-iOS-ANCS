"""Event platform for HA iOS ANCS."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_BASE_TOPIC, DOMAIN, EVENT_TYPE_NOTIFICATION
from .runtime import AncsMqttRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up HA iOS ANCS event entities."""

    runtime: AncsMqttRuntime = entry.runtime_data
    async_add_entities([AncsNotificationEvent(entry, runtime)])


class AncsNotificationEvent(EventEntity):
    """Native Home Assistant event entity for ANCS notifications."""

    _attr_event_types: list[str] = [EVENT_TYPE_NOTIFICATION]
    _attr_has_entity_name: bool = True
    _attr_translation_key: str | None = "notification"

    def __init__(self, entry: ConfigEntry, runtime: AncsMqttRuntime) -> None:
        """Initialize the ANCS notification event entity."""

        base_topic: str = entry.data[CONF_BASE_TOPIC]
        self._attr_unique_id = f"{base_topic}:{EVENT_TYPE_NOTIFICATION}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
        )
        self._runtime = runtime
        self._attr_available = runtime.available is not False

    async def async_added_to_hass(self) -> None:
        """Register runtime listeners."""

        self.async_on_remove(
            self._runtime.async_add_notification_listener(self._handle_notification)
        )
        self.async_on_remove(
            self._runtime.async_add_availability_listener(self._handle_availability)
        )

    @callback
    def _handle_notification(self, payload: dict[str, Any]) -> None:
        """Trigger a Home Assistant event from a parsed ANCS payload."""

        self._trigger_event(EVENT_TYPE_NOTIFICATION, dict(payload))
        self.async_write_ha_state()

    @callback
    def _handle_availability(self, available: bool | None) -> None:
        """Update entity availability from the runtime."""

        if available is None:
            return

        self._attr_available = available
        self.async_write_ha_state()
