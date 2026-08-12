from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from homeassistant.components import binary_sensor as binary_sensor_component
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.helpers import device_registry, entity_registry

from custom_components.ha_ios_ancs import binary_sensor as ancs_binary_sensor
from custom_components.ha_ios_ancs.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS,
    AncsNotificationBinarySensor,
    async_setup_entry,
)
from custom_components.ha_ios_ancs.const import (
    CONF_BASE_TOPIC,
    CONF_MQTT_DEVICE_IDENTIFIER,
    CONF_SOURCE_ENTITY_UNIQUE_ID,
    DOMAIN,
)
from custom_components.ha_ios_ancs.runtime import AncsMqttRuntime, AncsSourceRuntime

from tests.helpers import (
    EMPTY_DISCOVERY_KEYS,
    async_register_mqtt_ancs_source,
    async_register_mqtt_ancs_status,
    async_setup_ancs_platform,
)


EXPECTED_BINARY_SENSOR_KEYS = {
    "complete",
    "silent",
    "important",
    "pre_existing",
    "positive_action_available",
    "negative_action_available",
    "app_id_truncated",
    "app_name_truncated",
    "title_truncated",
    "subtitle_truncated",
    "message_truncated",
    "has_error",
    "ble_connected",
}
EXPECTED_NOTIFICATION_BINARY_SENSOR_KEYS = EXPECTED_BINARY_SENSOR_KEYS - {
    "ble_connected"
}

EXPECTED_FIELD_PATHS = {
    "complete": ("complete",),
    "silent": ("silent",),
    "important": ("important",),
    "pre_existing": ("pre_existing",),
    "positive_action_available": ("positive_action_available",),
    "negative_action_available": ("negative_action_available",),
    "app_id_truncated": ("truncated", "app_id"),
    "app_name_truncated": ("truncated", "app_name"),
    "title_truncated": ("truncated", "title"),
    "subtitle_truncated": ("truncated", "subtitle"),
    "message_truncated": ("truncated", "message"),
    "has_error": ("error",),
}


class RuntimeStub:
    def __init__(self, payload: dict[str, Any] | None) -> None:
        self.available = True
        self.device_entry = None
        self.latest_notification = deepcopy(payload)
        self.ble_connected: bool | None = None


def entry_with_runtime(payload: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        entry_id="entry-1",
        unique_id="ios_ancs_A1B2C3",
        title="Kitchen Relay",
        data={CONF_MQTT_DEVICE_IDENTIFIER: "ios_ancs_A1B2C3"},
        runtime_data=RuntimeStub(payload),
    )


def source_entry() -> ConfigEntry:
    return ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="Kitchen Relay",
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


def legacy_entry() -> ConfigEntry:
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


def mqtt_registry_snapshot(hass) -> set[tuple[str, object, str | None]]:
    return {
        (item.entity_id, item.disabled_by, item.device_id)
        for item in entity_registry.async_get(hass).entities.values()
        if item.platform == "mqtt"
    }


def test_binary_descriptions_cover_boolean_contract() -> None:
    assert {
        description.key for description in BINARY_SENSOR_DESCRIPTIONS
    } == EXPECTED_NOTIFICATION_BINARY_SENSOR_KEYS
    assert len(BINARY_SENSOR_DESCRIPTIONS) == len(
        EXPECTED_NOTIFICATION_BINARY_SENSOR_KEYS
    )
    assert {
        description.key: description.path
        for description in BINARY_SENSOR_DESCRIPTIONS
    } == EXPECTED_FIELD_PATHS

    descriptions = {
        description.key: description
        for description in BINARY_SENSOR_DESCRIPTIONS
    }
    assert descriptions["has_error"].non_null_presence is True
    for key in EXPECTED_NOTIFICATION_BINARY_SENSOR_KEYS - {"has_error"}:
        assert descriptions[key].non_null_presence is False
    for key in {
        "app_id_truncated",
        "app_name_truncated",
        "title_truncated",
        "subtitle_truncated",
        "message_truncated",
        "has_error",
    }:
        assert descriptions[key].device_class == BinarySensorDeviceClass.PROBLEM
        assert descriptions[key].entity_category == EntityCategory.DIAGNOSTIC


def test_binary_states_are_strict_and_null_safe(run) -> None:
    payload = {
        "complete": True,
        "silent": False,
        "important": 1,
        "pre_existing": False,
        "positive_action_available": True,
        "truncated": {
            "app_id": False,
            "app_name": True,
            "title": True,
            "subtitle": False,
            "message": True,
        },
        "error": None,
    }
    entities: list[AncsNotificationBinarySensor] = []
    run(async_setup_entry(None, entry_with_runtime(payload), entities.extend))
    states = {entity.entity_description.key: entity.is_on for entity in entities}

    assert states == {
        "complete": True,
        "silent": False,
        "important": None,
        "pre_existing": False,
        "positive_action_available": True,
        "negative_action_available": None,
        "app_id_truncated": False,
        "app_name_truncated": True,
        "title_truncated": True,
        "subtitle_truncated": False,
        "message_truncated": True,
        "has_error": False,
        "ble_connected": None,
    }

    by_key = {entity.entity_description.key: entity for entity in entities}
    with_error = deepcopy(payload)
    with_error["error"] = {"code": -10, "name": "timeout"}
    with patch.object(AncsNotificationBinarySensor, "async_write_ha_state"):
        for entity in entities:
            if isinstance(entity, AncsNotificationBinarySensor):
                entity._handle_notification(with_error)
    assert by_key["has_error"].is_on is True


def test_malformed_nested_values_remain_safe_and_explicit(run) -> None:
    payload = {
        "truncated": "invalid",
        "error": "invalid",
    }
    entities: list[AncsNotificationBinarySensor] = []
    run(async_setup_entry(None, entry_with_runtime(payload), entities.extend))
    states = {entity.entity_description.key: entity.is_on for entity in entities}

    assert states["app_id_truncated"] is None
    assert states["app_name_truncated"] is None
    assert states["title_truncated"] is None
    assert states["subtitle_truncated"] is None
    assert states["message_truncated"] is None
    assert states["has_error"] is True

    missing_error_entities: list[AncsNotificationBinarySensor] = []
    run(
        async_setup_entry(
            None,
            entry_with_runtime({"truncated": {}}),
            missing_error_entities.extend,
        )
    )
    missing_error = next(
        entity
        for entity in missing_error_entities
        if entity.entity_description.key == "has_error"
    )
    assert missing_error.is_on is None


def test_source_binary_sensors_use_separate_device_without_mutating_mqtt(
    registry_hass, run
) -> None:
    hass = registry_hass
    registered = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_A1B2C3",
            device_name="Kitchen Relay",
        )
    )
    before = mqtt_registry_snapshot(hass)
    entry = source_entry()
    runtime = AncsSourceRuntime(
        hass,
        registered.entity.unique_id,
        "ios_ancs_A1B2C3",
    )
    run(runtime.async_start())

    _, entity_ids = run(
        async_setup_ancs_platform(
            hass,
            entry,
            runtime,
            binary_sensor_component,
            ancs_binary_sensor,
            binary_sensor_component.DOMAIN,
        )
    )

    registry = entity_registry.async_get(hass)
    assert len(entity_ids) == len(EXPECTED_BINARY_SENSOR_KEYS)
    device_ids = {
        registry_entry.device_id
        for entity_id in entity_ids
        if (registry_entry := registry.async_get(entity_id)) is not None
    }
    assert len(device_ids) == 1
    companion_device_id = device_ids.pop()
    assert companion_device_id is not None
    assert companion_device_id != registered.device.id
    companion_device = device_registry.async_get(hass).async_get(
        companion_device_id
    )
    assert companion_device is not None
    assert companion_device.identifiers == {(DOMAIN, entry.entry_id)}
    assert companion_device.via_device_id is None
    assert ("mqtt", "ios_ancs_A1B2C3") in registered.device.identifiers
    assert len(device_registry.async_get(hass).devices) == 2
    assert mqtt_registry_snapshot(hass) == before

    run(binary_sensor_component.async_unload_entry(hass, entry))
    run(runtime.async_stop())


def test_source_ble_connection_binary_sensor_tracks_status_without_mutating_mqtt(
    registry_hass, run
) -> None:
    hass = registry_hass
    registered = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_A1B2C3",
            device_name="Kitchen Relay",
        )
    )
    status = run(async_register_mqtt_ancs_status(hass, registered))
    hass.states.async_set(registered.entity.entity_id, STATE_UNKNOWN)
    hass.states.async_set(status.entity_id, "on", {"ble_connected": False})
    before = mqtt_registry_snapshot(hass)
    entry = source_entry()
    runtime = AncsSourceRuntime(
        hass,
        registered.entity.unique_id,
        "ios_ancs_A1B2C3",
    )
    run(runtime.async_start())

    _, entity_ids = run(
        async_setup_ancs_platform(
            hass,
            entry,
            runtime,
            binary_sensor_component,
            ancs_binary_sensor,
            binary_sensor_component.DOMAIN,
        )
    )

    registry = entity_registry.async_get(hass)
    ble_entry = next(
        item
        for item in entity_registry.async_entries_for_config_entry(
            registry, entry.entry_id
        )
        if item.unique_id == "ios_ancs_A1B2C3:binary_sensor:ble_connected"
    )
    assert ble_entry.entity_id in entity_ids
    assert len(entity_ids) == len(EXPECTED_BINARY_SENSOR_KEYS)
    ble_state = hass.states.get(ble_entry.entity_id)
    assert ble_state is not None
    assert ble_state.state == STATE_OFF

    assert ble_entry.device_id is not None
    assert ble_entry.device_id != registered.device.id
    companion_device = device_registry.async_get(hass).async_get(
        ble_entry.device_id
    )
    assert companion_device is not None
    assert companion_device.identifiers == {(DOMAIN, entry.entry_id)}
    assert companion_device.via_device_id is None
    assert mqtt_registry_snapshot(hass) == before

    hass.states.async_set(status.entity_id, "on", {"ble_connected": True})
    run(hass.async_block_till_done())

    ble_state = hass.states.get(ble_entry.entity_id)
    assert ble_state is not None
    assert ble_state.state == STATE_ON
    assert mqtt_registry_snapshot(hass) == before

    run(binary_sensor_component.async_unload_entry(hass, entry))
    run(runtime.async_stop())
    assert mqtt_registry_snapshot(hass) == before
    assert (
        entity_registry.async_get(hass).async_get(registered.entity.entity_id)
        is not None
    )


def test_legacy_binary_sensors_share_one_integration_device(
    registry_hass, run
) -> None:
    hass = registry_hass
    entry = legacy_entry()
    runtime = AncsMqttRuntime(hass, "ios_ancs/legacy")

    _, entity_ids = run(
        async_setup_ancs_platform(
            hass,
            entry,
            runtime,
            binary_sensor_component,
            ancs_binary_sensor,
            binary_sensor_component.DOMAIN,
        )
    )

    registry = entity_registry.async_get(hass)
    device_ids = {
        registry_entry.device_id
        for entity_id in entity_ids
        if (registry_entry := registry.async_get(entity_id)) is not None
    }
    assert len(entity_ids) == len(EXPECTED_BINARY_SENSOR_KEYS)
    assert len(device_ids) == 1
    device_id = device_ids.pop()
    assert device_id is not None
    legacy_device = device_registry.async_get(hass).async_get(device_id)
    assert legacy_device is not None
    assert (DOMAIN, entry.entry_id) in legacy_device.identifiers

    run(binary_sensor_component.async_unload_entry(hass, entry))
    run(runtime.async_stop())
