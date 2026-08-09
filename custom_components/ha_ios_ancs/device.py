"""Integration-owned device helpers for iOS ANCS."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo

from .const import CONF_BASE_TOPIC, CONF_MQTT_DEVICE_IDENTIFIER, DOMAIN


def source_title(source_identity: str) -> str:
    """Return the iOS ANCS title for a source identity."""

    return f"iOS ANCS ({source_identity})"


def entry_source_identity(entry: ConfigEntry) -> str:
    """Return the stable user-visible source identity."""

    value = entry.data.get(CONF_MQTT_DEVICE_IDENTIFIER)
    if not isinstance(value, str):
        value = entry.data.get(CONF_BASE_TOPIC)
    return value if isinstance(value, str) and value else entry.entry_id


def entry_title(entry: ConfigEntry) -> str:
    """Return the iOS ANCS config-entry and device title."""

    return source_title(entry_source_identity(entry))


def device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return integration-owned device information."""

    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry_title(entry),
    )


@callback
def async_ensure_integration_device(
    hass: HomeAssistant, entry: ConfigEntry
) -> dr.DeviceEntry:
    """Create the owned device and move only companion entities to it."""

    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry_title(entry),
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
