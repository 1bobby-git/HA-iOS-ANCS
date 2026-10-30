"""Home Assistant setup for the iOS ANCS integration."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import STORAGE_DIR, Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.util.hass_dict import HassKey

from .const import (
    CONFIG_ENTRY_VERSION,
    CONF_BASE_TOPIC,
    CONF_MQTT_DEVICE_IDENTIFIER,
    CONF_SOURCE_ENTITY_UNIQUE_ID,
    DOMAIN,
)
from .device import async_ensure_integration_device, entry_title
from .runtime import AncsMqttRuntime, AncsRuntime, AncsSourceRuntime

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.EVENT]
_STORAGE_VERSION = 1
_STORAGE_SAVE_DELAY_SECONDS = 2.0
_STORE_FILE_PATTERN = re.compile(
    rf"^{re.escape(DOMAIN)}\.([0-9A-Za-z]+)\.last_notification$"
)
# The Store each set-up entry writes through. Removal after a failed unload
# must cancel this instance's pending delayed and final writes.
_ENTRY_STORES: HassKey[dict[str, Store[dict[str, Any]]]] = HassKey(
    f"{DOMAIN}_notification_stores"
)


def _notification_store(
    hass: HomeAssistant, entry_id: str
) -> Store[dict[str, Any]]:
    """Return the per-entry last-notification store."""

    return Store(
        hass,
        _STORAGE_VERSION,
        f"{DOMAIN}.{entry_id}.last_notification",
        private=True,
    )


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Delete saved notifications of entries removed before 0.6.14."""

    await _async_remove_orphaned_notifications(hass)
    return True


async def _async_remove_orphaned_notifications(hass: HomeAssistant) -> None:
    """Remove last-notification files whose config entry no longer exists."""

    current = {
        entry.entry_id
        for entry in hass.config_entries.async_entries(
            DOMAIN, include_ignore=True, include_disabled=True
        )
    }
    storage_dir = Path(hass.config.path(STORAGE_DIR))

    def find_orphans() -> list[str]:
        try:
            names = os.listdir(storage_dir)
        except OSError:
            return []
        return [
            match.group(1)
            for name in names
            if (match := _STORE_FILE_PATTERN.match(name))
            and match.group(1) not in current
        ]

    for entry_id in await hass.async_add_executor_job(find_orphans):
        await _notification_store(hass, entry_id).async_remove()


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
    store = _notification_store(hass, entry.entry_id)
    stored_notification = await store.async_load()
    runtime = _runtime_from_entry(hass, entry)

    restored_notification = runtime.restore_notification(stored_notification)
    latest_snapshot: dict[str, Any] | None = None
    entry_stores = hass.data.setdefault(_ENTRY_STORES, {})
    entry_stores[entry.entry_id] = store

    def persist_notification(notification: dict[str, Any]) -> None:
        """Persist accepted details without delaying entity updates."""

        nonlocal latest_snapshot
        snapshot = dict(notification)
        latest_snapshot = snapshot
        store.async_delay_save(
            lambda: snapshot,
            _STORAGE_SAVE_DELAY_SECONDS,
        )

    async def async_flush_notification() -> None:
        """Write a still-delayed save before reload or removal continues."""

        if entry_stores.get(entry.entry_id) is store:
            del entry_stores[entry.entry_id]
        # async_save cancels this Store's pending delayed and final writes, so
        # a removed entry's file is not recreated and a reload restores it.
        if latest_snapshot is not None:
            await store.async_save(latest_snapshot)

    entry.async_on_unload(async_flush_notification)
    runtime.async_add_notification_listener(
        persist_notification,
        replay_pending=False,
    )
    try:
        await runtime.async_start()
        if not restored_notification and (
            current_notification := runtime.latest_notification
        ):
            await store.async_save(current_notification)
        entry.runtime_data = runtime
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except (Exception, asyncio.CancelledError):
        # Startup/save failures and cancellation must not leave live listeners.
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


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the saved last notification when the entry is deleted."""

    # A normal unload already stopped the runtime and flushed its Store. After
    # a failed unload both are still live: stop the runtime so it cannot
    # schedule another save, and remove through the setup's own Store so its
    # pending delayed and final writes are cancelled together with the file.
    if (runtime := getattr(entry, "runtime_data", None)) is not None:
        await runtime.async_stop()
        entry.runtime_data = None
    store = hass.data.get(_ENTRY_STORES, {}).pop(entry.entry_id, None)
    await (store or _notification_store(hass, entry.entry_id)).async_remove()
