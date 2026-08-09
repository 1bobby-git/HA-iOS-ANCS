"""Integration-owned device helpers for iOS ANCS."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN


def device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return integration-owned device information."""

    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
    )


@callback
def async_ensure_integration_device(
    hass: HomeAssistant, entry: ConfigEntry
) -> dr.DeviceEntry:
    """Create the owned device and move only companion entities to it."""

    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
    )
    entity_registry = er.async_get(hass)
    for entity_entry in er.async_entries_for_config_entry(
        entity_registry, entry.entry_id
    ):
        if entity_entry.platform != DOMAIN or entity_entry.device_id == device.id:
            continue
        entity_registry.async_update_entity(
            entity_entry.entity_id,
            device_id=device.id,
        )
    return device
