from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.ha_ios_ancs.source import (
    AncsSource,
    async_discover_ancs_sources,
    async_resolve_ancs_status_entity,
    async_resolve_ancs_source,
)

from tests.helpers import (
    async_register_mqtt_ancs_source,
    async_register_mqtt_ancs_status,
)


def test_discovery_returns_only_matching_mqtt_last_notification_sensor(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    compatible = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_A1B2C3",
            device_name="iOS ANCS A1B2C3",
        )
    )
    run(
        async_register_mqtt_ancs_source(
            hass,
            "unrelated",
            device_name="Unrelated MQTT device",
            entity_unique_id="unrelated_temperature",
        )
    )

    sources = async_discover_ancs_sources(hass)

    assert sources == [
        AncsSource(
            entity_id=compatible.entity.entity_id,
            entity_unique_id="ios_ancs_A1B2C3_last_notification",
            mqtt_device_identifier="ios_ancs_A1B2C3",
            device_id=compatible.device.id,
            name="iOS ANCS A1B2C3",
        )
    ]


def test_resolver_uses_unique_id_after_entity_id_rename(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    registered = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_A1B2C3",
            device_name="iOS ANCS A1B2C3",
        )
    )
    registry = er.async_get(hass)
    registry.async_update_entity(
        registered.entity.entity_id,
        new_entity_id="sensor.renamed_ancs_notification",
    )

    source = async_resolve_ancs_source(
        hass,
        "ios_ancs_A1B2C3_last_notification",
        "ios_ancs_A1B2C3",
    )

    assert source is not None
    assert source.entity_id == "sensor.renamed_ancs_notification"
    assert source.device_id == registered.device.id


def test_resolver_rejects_identifier_mismatch(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    registered = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_A1B2C3",
            device_name="iOS ANCS A1B2C3",
        )
    )

    assert (
        async_resolve_ancs_source(
            hass,
            registered.entity.unique_id,
            "ios_ancs_DIFFERENT",
        )
        is None
    )


def test_status_resolver_returns_configured_mqtt_device_binary_sensor(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    registered = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_A1B2C3",
            device_name="iOS ANCS A1B2C3",
        )
    )
    status = run(async_register_mqtt_ancs_status(hass, registered))

    assert (
        async_resolve_ancs_status_entity(hass, "ios_ancs_A1B2C3")
        == status.entity_id
    )


def test_status_resolver_rejects_expected_unique_id_on_foreign_mqtt_device(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_A1B2C3",
            device_name="iOS ANCS A1B2C3",
        )
    )
    foreign = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_FOREIGN",
            device_name="Other iOS ANCS",
        )
    )
    run(
        async_register_mqtt_ancs_status(
            hass,
            foreign,
            entity_unique_id="ios_ancs_A1B2C3_device_status",
        )
    )

    assert async_resolve_ancs_status_entity(hass, "ios_ancs_A1B2C3") is None
