from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.ha_ios_ancs import async_setup_entry
from custom_components.ha_ios_ancs.const import (
    CONF_BASE_TOPIC,
    CONF_MQTT_DEVICE_IDENTIFIER,
    CONF_SOURCE_ENTITY_UNIQUE_ID,
    DOMAIN,
)

from tests.helpers import EMPTY_DISCOVERY_KEYS, async_register_mqtt_ancs_source

EXPECTED_PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.EVENT]


def mqtt_registry_snapshot(hass: HomeAssistant) -> list[tuple[object, ...]]:
    """Return stable identity and ownership fields for every MQTT entity."""

    return sorted(
        (
            item.id,
            item.entity_id,
            item.unique_id,
            item.disabled_by,
            item.device_id,
        )
        for item in er.async_get(hass).entities.values()
        if item.platform == "mqtt"
    )


def make_source_entry() -> ConfigEntry:
    return ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="Kitchen iPhone Relay",
        data={
            CONF_SOURCE_ENTITY_UNIQUE_ID: "ios_ancs_A1B2C3_last_notification",
            CONF_MQTT_DEVICE_IDENTIFIER: "ios_ancs_A1B2C3",
        },
        source="user",
        unique_id="ios_ancs_A1B2C3",
        discovery_keys=EMPTY_DISCOVERY_KEYS,
        options={},
        subentries_data={},
    )


def make_legacy_entry() -> ConfigEntry:
    return ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="HA iOS ANCS (ios_ancs/legacy)",
        data={CONF_BASE_TOPIC: "ios_ancs/legacy"},
        source="user",
        unique_id="ios_ancs/legacy",
        discovery_keys=EMPTY_DISCOVERY_KEYS,
        options={},
        subentries_data={},
    )


def test_setup_entry_uses_source_runtime_for_device_data(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    entry = make_source_entry()
    with patch.object(
        hass.config_entries,
        "async_setup",
        new=AsyncMock(return_value=True),
    ):
        run(hass.config_entries.async_add(entry))
    with patch("custom_components.ha_ios_ancs.AncsSourceRuntime") as runtime_cls:
        runtime = runtime_cls.return_value
        runtime.async_start = AsyncMock()
        runtime.async_stop = AsyncMock()
        hass.config_entries.async_forward_entry_setups = AsyncMock()

        assert run(async_setup_entry(hass, entry)) is True

    runtime_cls.assert_called_once_with(
        hass,
        "ios_ancs_A1B2C3_last_notification",
        "ios_ancs_A1B2C3",
    )
    runtime.async_start.assert_awaited_once()
    assert entry.runtime_data is runtime
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry,
        EXPECTED_PLATFORMS,
    )


def test_setup_entry_keeps_legacy_direct_mqtt_runtime(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    entry = make_legacy_entry()
    with patch.object(
        hass.config_entries,
        "async_setup",
        new=AsyncMock(return_value=True),
    ):
        run(hass.config_entries.async_add(entry))
    with patch("custom_components.ha_ios_ancs.AncsMqttRuntime") as runtime_cls:
        runtime = runtime_cls.return_value
        runtime.async_start = AsyncMock()
        runtime.async_stop = AsyncMock()
        hass.config_entries.async_forward_entry_setups = AsyncMock()

        assert run(async_setup_entry(hass, entry)) is True

    runtime_cls.assert_called_once_with(hass, "ios_ancs/legacy")
    runtime.async_start.assert_awaited_once()
    assert entry.data == {CONF_BASE_TOPIC: "ios_ancs/legacy"}
    assert entry.runtime_data is runtime
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry,
        EXPECTED_PLATFORMS,
    )


def test_setup_entry_stops_source_runtime_when_event_forward_fails(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    entry = make_source_entry()
    with patch.object(
        hass.config_entries,
        "async_setup",
        new=AsyncMock(return_value=True),
    ):
        run(hass.config_entries.async_add(entry))
    forward_error = RuntimeError("event platform failed")
    hass.config_entries.async_forward_entry_setups = AsyncMock(
        side_effect=forward_error
    )

    with patch("custom_components.ha_ios_ancs.AncsSourceRuntime") as runtime_cls:
        runtime = runtime_cls.return_value
        runtime.async_start = AsyncMock()
        runtime.async_stop = AsyncMock()

        try:
            run(async_setup_entry(hass, entry))
        except RuntimeError as err:
            assert err is forward_error
        else:
            raise AssertionError("setup should raise the platform forward error")

    runtime.async_start.assert_awaited_once()
    runtime.async_stop.assert_awaited_once()
    assert entry.runtime_data is None


def test_setup_entry_moves_only_companion_entities_to_owned_device(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    registered = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_A1B2C3",
            device_name="Kitchen Relay",
        )
    )
    entry = make_source_entry()
    with patch.object(
        hass.config_entries,
        "async_setup",
        new=AsyncMock(return_value=True),
    ):
        run(hass.config_entries.async_add(entry))

    registry = er.async_get(hass)
    event_before = registry.async_get_or_create(
        Platform.EVENT,
        DOMAIN,
        "ios_ancs_A1B2C3:notification",
        config_entry=entry,
        device_id=registered.device.id,
        suggested_object_id="ios_ancs_notification",
    )
    title_before = registry.async_get_or_create(
        Platform.SENSOR,
        DOMAIN,
        "ios_ancs_A1B2C3:sensor:title",
        config_entry=entry,
        device_id=registered.device.id,
        suggested_object_id="ios_ancs_title",
    )
    error_before = registry.async_get_or_create(
        Platform.BINARY_SENSOR,
        DOMAIN,
        "ios_ancs_A1B2C3:binary_sensor:has_error",
        config_entry=entry,
        device_id=registered.device.id,
        suggested_object_id="ios_ancs_has_error",
    )
    mqtt_before = mqtt_registry_snapshot(hass)

    with patch("custom_components.ha_ios_ancs.AncsSourceRuntime") as runtime_cls:
        runtime = runtime_cls.return_value
        runtime.async_start = AsyncMock()
        runtime.async_stop = AsyncMock()
        hass.config_entries.async_forward_entry_setups = AsyncMock()
        assert run(async_setup_entry(hass, entry)) is True

    companion_device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, entry.entry_id)}
    )
    assert companion_device is not None
    assert companion_device.name == "iOS ANCS (ios_ancs_A1B2C3)"
    assert companion_device.id != registered.device.id
    assert companion_device.via_device_id is None

    for before in (event_before, title_before, error_before):
        migrated = registry.async_get(before.entity_id)
        assert migrated is not None
        assert migrated.id == before.id
        assert migrated.entity_id == before.entity_id
        assert migrated.unique_id == before.unique_id
        assert migrated.disabled_by == before.disabled_by
        assert migrated.device_id == companion_device.id

    assert mqtt_registry_snapshot(hass) == mqtt_before
