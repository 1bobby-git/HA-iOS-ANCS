"""Home Assistant setup for the HA iOS ANCS integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_BASE_TOPIC
from .runtime import AncsMqttRuntime

PLATFORMS = [Platform.EVENT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HA iOS ANCS from a config entry."""

    runtime = AncsMqttRuntime(hass, entry.data[CONF_BASE_TOPIC])
    await runtime.async_start()
    entry.runtime_data = runtime

    if entry.setup_lock.locked():
        try:
            await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        except Exception:
            await runtime.async_stop()
            entry.runtime_data = None
            raise

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload HA iOS ANCS."""

    if entry.setup_lock.locked():
        if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
            return False

        # EventEntity unload leaves registry-backed states restored/unavailable.
        # This companion contract removes only states owned by this config entry.
        entity_registry = er.async_get(hass)
        if hasattr(entity_registry, "entities"):
            for registry_entry in er.async_entries_for_config_entry(
                entity_registry, entry.entry_id
            ):
                if registry_entry.domain == Platform.EVENT:
                    hass.states.async_remove(registry_entry.entity_id)

    if (runtime := entry.runtime_data) is not None:
        await runtime.async_stop()
    entry.runtime_data = None
    return True
