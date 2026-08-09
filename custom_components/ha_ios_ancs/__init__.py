"""Home Assistant setup for the iOS ANCS integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONFIG_ENTRY_VERSION,
    CONF_BASE_TOPIC,
    CONF_MQTT_DEVICE_IDENTIFIER,
    CONF_SOURCE_ENTITY_UNIQUE_ID,
)
from .device import async_ensure_integration_device, entry_title
from .runtime import AncsMqttRuntime, AncsRuntime, AncsSourceRuntime

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.EVENT]


async def async_migrate_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Migrate an iOS ANCS config entry without changing its source."""

    if entry.version > CONFIG_ENTRY_VERSION:
        return False
    if entry.version < CONFIG_ENTRY_VERSION:
        hass.config_entries.async_update_entry(
            entry,
            title=entry_title(entry),
            version=CONFIG_ENTRY_VERSION,
        )
    return True


def _runtime_from_entry(hass: HomeAssistant, entry: ConfigEntry) -> AncsRuntime:
    """Create the source-backed or legacy runtime described by an entry."""

    if CONF_SOURCE_ENTITY_UNIQUE_ID in entry.data:
        return AncsSourceRuntime(
            hass,
            entry.data[CONF_SOURCE_ENTITY_UNIQUE_ID],
            entry.data[CONF_MQTT_DEVICE_IDENTIFIER],
        )
    return AncsMqttRuntime(hass, entry.data[CONF_BASE_TOPIC])


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up iOS ANCS from a config entry."""

    async_ensure_integration_device(hass, entry)
    runtime = _runtime_from_entry(hass, entry)
    await runtime.async_start()
    entry.runtime_data = runtime

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await runtime.async_stop()
        entry.runtime_data = None
        raise

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload iOS ANCS."""

    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False

    # EventEntity unload leaves registry-backed states restored/unavailable.
    # This companion contract removes only states owned by this config entry.
    entity_registry = er.async_get(hass)
    for registry_entry in er.async_entries_for_config_entry(
        entity_registry, entry.entry_id
    ):
        if registry_entry.domain == Platform.EVENT:
            hass.states.async_remove(registry_entry.entity_id)

    if (runtime := entry.runtime_data) is not None:
        await runtime.async_stop()
    entry.runtime_data = None
    return True
