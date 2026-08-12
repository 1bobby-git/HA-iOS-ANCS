from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from types import MappingProxyType
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.discovery_flow import DiscoveryKey
from homeassistant.helpers.entity_platform import EntityPlatform


EMPTY_DISCOVERY_KEYS: MappingProxyType[str, tuple[DiscoveryKey, ...]] = (
    MappingProxyType({})
)


@dataclass(frozen=True, slots=True)
class RegisteredMqttSource:
    config_entry: ConfigEntry
    device: dr.DeviceEntry
    entity: er.RegistryEntry


async def async_register_mqtt_ancs_source(
    hass: HomeAssistant,
    mqtt_device_identifier: str,
    *,
    device_name: str,
    entity_unique_id: str | None = None,
) -> RegisteredMqttSource:
    mqtt_entries = hass.config_entries.async_entries("mqtt")
    if mqtt_entries:
        mqtt_entry = mqtt_entries[0]
    else:
        mqtt_entry = ConfigEntry(
            version=1,
            minor_version=1,
            domain="mqtt",
            title="MQTT",
            data={},
            source="user",
            unique_id=None,
            discovery_keys=EMPTY_DISCOVERY_KEYS,
            options={},
            subentries_data={},
        )
        with patch.object(
            hass.config_entries,
            "async_setup",
            new=AsyncMock(return_value=True),
        ):
            await hass.config_entries.async_add(mqtt_entry)
            await hass.async_block_till_done()

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=mqtt_entry.entry_id,
        identifiers={("mqtt", mqtt_device_identifier)},
        name=device_name,
    )
    entity = entity_registry.async_get_or_create(
        "sensor",
        "mqtt",
        entity_unique_id or f"{mqtt_device_identifier}_last_notification",
        config_entry=mqtt_entry,
        device_id=device.id,
        suggested_object_id=f"{mqtt_device_identifier}_last_notification",
    )
    return RegisteredMqttSource(mqtt_entry, device, entity)


async def async_register_mqtt_ancs_status(
    hass: HomeAssistant,
    registered: RegisteredMqttSource,
    *,
    entity_unique_id: str | None = None,
) -> er.RegistryEntry:
    mqtt_device_identifier = next(
        identifier_value
        for identifier_domain, identifier_value in registered.device.identifiers
        if identifier_domain == "mqtt"
    )
    return er.async_get(hass).async_get_or_create(
        "binary_sensor",
        "mqtt",
        entity_unique_id or f"{mqtt_device_identifier}_device_status",
        config_entry=registered.config_entry,
        device_id=registered.device.id,
        suggested_object_id=f"{mqtt_device_identifier}_device_status",
    )


async def async_setup_ancs_platform(
    hass: HomeAssistant,
    entry: ConfigEntry,
    runtime: Any,
    component: Any,
    integration_platform: Any,
    domain: Platform,
) -> tuple[EntityPlatform, list[str]]:
    """Set up one companion platform through Home Assistant's entity layer."""

    if component.DATA_COMPONENT not in hass.data:
        await component.async_setup(hass, {})
    if hass.config_entries.async_get_entry(entry.entry_id) is None:
        with patch.object(
            hass.config_entries,
            "async_setup",
            new=AsyncMock(return_value=True),
        ):
            await hass.config_entries.async_add(entry)
            await hass.async_block_till_done()
    entry.runtime_data = runtime

    platform = EntityPlatform(
        hass=hass,
        logger=logging.getLogger(__name__),
        domain=domain,
        platform_name="ha_ios_ancs",
        platform=cast(Any, integration_platform),
        scan_interval=timedelta(seconds=30),
        entity_namespace=None,
    )
    assert await platform.async_setup_entry(entry) is True
    hass.data[component.DATA_COMPONENT]._platforms[entry.entry_id] = platform
    await hass.async_block_till_done()

    entity_ids = [
        registry_entry.entity_id
        for registry_entry in er.async_entries_for_config_entry(
            er.async_get(hass),
            entry.entry_id,
        )
        if registry_entry.domain == domain
    ]
    return platform, entity_ids
