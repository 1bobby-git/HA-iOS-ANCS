from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from custom_components.ha_ios_ancs import async_setup_entry
from custom_components.ha_ios_ancs.const import (
    CONF_BASE_TOPIC,
    CONF_MQTT_DEVICE_IDENTIFIER,
    CONF_SOURCE_ENTITY_UNIQUE_ID,
    DOMAIN,
)

from tests.helpers import EMPTY_DISCOVERY_KEYS

EXPECTED_PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.EVENT]


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
    hass: HomeAssistant, run
) -> None:
    entry = make_source_entry()
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
    hass: HomeAssistant, run
) -> None:
    entry = make_legacy_entry()
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
    hass: HomeAssistant, run
) -> None:
    entry = make_source_entry()
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
