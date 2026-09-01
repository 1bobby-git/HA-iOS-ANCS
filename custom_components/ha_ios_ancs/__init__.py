"""Home Assistant setup for the iOS ANCS integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import (
    CONFIG_ENTRY_VERSION,
    CONF_BASE_TOPIC,
    CONF_MQTT_DEVICE_IDENTIFIER,
    CONF_SOURCE_ENTITY_UNIQUE_ID,
    DOMAIN,
)
from .device import async_ensure_integration_device, entry_title
from .runtime import AncsMqttRuntime, AncsRuntime, AncsSourceRuntime

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.EVENT]
_STORAGE_VERSION = 1
_STORAGE_SAVE_DELAY_SECONDS = 2.0


def _notification_store(
    hass: HomeAssistant, entry: ConfigEntry
) -> Store[dict[str, Any]]:
    """Return the per-entry last-notification store."""

    return Store(
        hass,
        _STORAGE_VERSION,
        f"{DOMAIN}.{entry.entry_id}.last_notification",
        private=True,
    )


async def async_migrate_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Migrate an iOS ANCS config entry without changing its source."""

    if entry.version > CONFIG_ENTRY_VERSION:
        return False
    if entry.version < CONFIG_ENTRY_VERSION:
        entity_registry = er.async_get(hass)
        for registry_entry in er.async_entries_for_config_entry(
            entity_registry, entry.entry_id
        ):
            if (
                registry_entry.domain == Platform.SENSOR
                and registry_entry.platform == DOMAIN
                and registry_entry.unique_id.endswith(
                    (
                        ":sensor:published_at_ms",
                        ":sensor:received_at_ms",
                    )
                )
            ):
                entity_registry.async_remove(registry_entry.entity_id)
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
    store = _notification_store(hass, entry)
    stored_notification = await store.async_load()
    runtime = _runtime_from_entry(hass, entry)

    restored_notification = runtime.restore_notification(stored_notification)

    def persist_notification(notification: dict[str, Any]) -> None:
        """Persist accepted details without delaying entity updates."""

        snapshot = dict(notification)
        store.async_delay_save(
            lambda: snapshot,
            _STORAGE_SAVE_DELAY_SECONDS,
        )

    runtime.async_add_notification_listener(
        persist_notification,
        replay_pending=False,
    )
    await runtime.async_start()
    if not restored_notification and (
        current_notification := runtime.latest_notification
    ):
        await store.async_save(current_notification)
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
