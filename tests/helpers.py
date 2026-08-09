from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.discovery_flow import DiscoveryKey


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
