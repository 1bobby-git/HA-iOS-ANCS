"""Registry-backed MQTT source discovery for HA iOS ANCS."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import LAST_NOTIFICATION_UNIQUE_ID_SUFFIX, MQTT_DOMAIN


@dataclass(frozen=True, slots=True)
class AncsSource:
    """A compatible MQTT-discovered ANCS notification source."""

    entity_id: str
    entity_unique_id: str
    mqtt_device_identifier: str
    device_id: str
    name: str


def _source_from_entries(
    entity_entry: er.RegistryEntry,
    device_entry: dr.DeviceEntry,
    mqtt_device_identifier: str,
) -> AncsSource | None:
    expected_unique_id = (
        f"{mqtt_device_identifier}_{LAST_NOTIFICATION_UNIQUE_ID_SUFFIX}"
    )
    if entity_entry.unique_id != expected_unique_id:
        return None

    return AncsSource(
        entity_id=entity_entry.entity_id,
        entity_unique_id=entity_entry.unique_id,
        mqtt_device_identifier=mqtt_device_identifier,
        device_id=device_entry.id,
        name=(
            device_entry.name_by_user
            or device_entry.name
            or entity_entry.name
            or entity_entry.original_name
            or mqtt_device_identifier
        ),
    )


@callback
def async_discover_ancs_sources(hass: HomeAssistant) -> list[AncsSource]:
    """Return compatible MQTT-discovered ANCS notification sources."""

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    sources: list[AncsSource] = []

    for entity_entry in entity_registry.entities.values():
        if (
            entity_entry.domain != Platform.SENSOR
            or entity_entry.platform != MQTT_DOMAIN
            or entity_entry.device_id is None
        ):
            continue

        device_entry = device_registry.async_get(entity_entry.device_id)
        if device_entry is None:
            continue

        for identifier_domain, identifier_value in device_entry.identifiers:
            if identifier_domain != MQTT_DOMAIN:
                continue
            source = _source_from_entries(
                entity_entry,
                device_entry,
                identifier_value,
            )
            if source is not None:
                sources.append(source)

    return sorted(sources, key=lambda source: (source.name.casefold(), source.entity_id))


@callback
def async_resolve_ancs_source(
    hass: HomeAssistant,
    entity_unique_id: str,
    mqtt_device_identifier: str,
) -> AncsSource | None:
    """Resolve a stored source identity to its current entity and device."""

    entity_registry = er.async_get(hass)
    entity_id = entity_registry.async_get_entity_id(
        Platform.SENSOR,
        MQTT_DOMAIN,
        entity_unique_id,
    )
    if entity_id is None:
        return None

    entity_entry = entity_registry.async_get(entity_id)
    if entity_entry is None or entity_entry.device_id is None:
        return None

    device_entry = dr.async_get(hass).async_get(entity_entry.device_id)
    if device_entry is None:
        return None
    if (MQTT_DOMAIN, mqtt_device_identifier) not in device_entry.identifiers:
        return None

    return _source_from_entries(
        entity_entry,
        device_entry,
        mqtt_device_identifier,
    )
