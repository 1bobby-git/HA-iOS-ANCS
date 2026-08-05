"""Home Assistant setup for the HA iOS ANCS integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_BASE_TOPIC
from .runtime import AncsMqttRuntime


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HA iOS ANCS from a config entry."""

    runtime = AncsMqttRuntime(hass, entry.data[CONF_BASE_TOPIC])
    await runtime.async_start()
    entry.runtime_data = runtime
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload HA iOS ANCS."""

    if (runtime := entry.runtime_data) is not None:
        await runtime.async_stop()
    entry.runtime_data = None
    return True
