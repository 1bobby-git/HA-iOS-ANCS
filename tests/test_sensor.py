from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from homeassistant.components import sensor as sensor_component
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.helpers import device_registry, entity_registry

from custom_components.ha_ios_ancs import sensor as ancs_sensor
from custom_components.ha_ios_ancs.const import (
    CONF_BASE_TOPIC,
    CONF_MQTT_DEVICE_IDENTIFIER,
    CONF_SOURCE_ENTITY_UNIQUE_ID,
    DOMAIN,
    HA_ECHO_APP_ID,
)
from custom_components.ha_ios_ancs.runtime import AncsMqttRuntime, AncsSourceRuntime
from custom_components.ha_ios_ancs.sensor import (
    CATEGORY_OPTIONS,
    EVENT_OPTIONS,
    SENSOR_DESCRIPTIONS,
    AncsNotificationSensor,
    SensorValueKind,
    async_setup_entry,
)

from tests.helpers import (
    EMPTY_DISCOVERY_KEYS,
    async_register_mqtt_ancs_source,
    async_setup_ancs_platform,
)


EXPECTED_SENSOR_KEYS = {
    "app_name",
    "app_id",
    "title",
    "subtitle",
    "message",
    "event",
    "category",
    "date",
    "uid",
    "session_id",
    "event_id",
    "event_flags",
    "category_id",
    "category_count",
    "message_size",
    "schema_version",
    "relay_id",
    "target",
    "source",
    "device_name",
    "received_at_ms",
    "published_at_ms",
    "error_code",
    "error_name",
    "raw_notification",
}

EXPECTED_FIELD_SPECS = {
    "app_name": (("app_name",), SensorValueKind.TEXT, ("app_id",), True),
    "app_id": (("app_id",), SensorValueKind.TEXT, None, True),
    "title": (("title",), SensorValueKind.TEXT, None, True),
    "subtitle": (("subtitle",), SensorValueKind.TEXT, None, True),
    "message": (("message",), SensorValueKind.TEXT, None, True),
    "event": (("event",), SensorValueKind.TEXT, None, False),
    "category": (("category",), SensorValueKind.TEXT, None, False),
    "date": (("date",), SensorValueKind.TEXT, None, False),
    "uid": (("uid",), SensorValueKind.INTEGER, None, False),
    "session_id": (("session_id",), SensorValueKind.INTEGER, None, False),
    "event_id": (("event_id",), SensorValueKind.INTEGER, None, False),
    "event_flags": (("event_flags",), SensorValueKind.INTEGER, None, False),
    "category_id": (("category_id",), SensorValueKind.INTEGER, None, False),
    "category_count": (("category_count",), SensorValueKind.INTEGER, None, False),
    "message_size": (("message_size",), SensorValueKind.DECIMAL_TEXT, None, False),
    "schema_version": (("schema_version",), SensorValueKind.INTEGER, None, False),
    "relay_id": (("relay_id",), SensorValueKind.TEXT, None, False),
    "target": (("target",), SensorValueKind.TEXT, None, False),
    "source": (("source",), SensorValueKind.TEXT, None, False),
    "device_name": (("device_name",), SensorValueKind.TEXT, None, True),
    "received_at_ms": (("received_at_ms",), SensorValueKind.INTEGER, None, False),
    "published_at_ms": (("published_at_ms",), SensorValueKind.INTEGER, None, False),
    "error_code": (("error", "code"), SensorValueKind.INTEGER, None, False),
    "error_name": (("error", "name"), SensorValueKind.TEXT, None, False),
    "raw_notification": (("relay_id",), SensorValueKind.RAW, None, False),
}


class RuntimeStub:
    def __init__(self, payload: dict[str, Any] | None) -> None:
        self.available = True
        self.device_entry = None
        self.latest_notification = deepcopy(payload)


def entry_with_runtime(payload: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        entry_id="entry-1",
        unique_id="ios_ancs_A1B2C3",
        title="Kitchen Relay",
        runtime_data=RuntimeStub(payload),
    )


def complete_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "target": "esp32c6",
        "source": "esp32c6_ancs",
        "relay_id": "boot1-1-42-aabbcc",
        "device_name": "IOS-ANCS-C6-AB12",
        "session_id": 1,
        "event": "added",
        "event_id": 0,
        "event_flags": 16,
        "uid": 42,
        "category_id": 6,
        "category": "email",
        "category_count": 2,
        "app_id": "com.example.chat",
        "title": "Private title",
        "subtitle": "Private subtitle",
        "message": "x" * 4096,
        "message_size": "4096",
        "date": "20260809T121314",
        "complete": True,
        "received_at_ms": 123000,
        "published_at_ms": 123456,
        "error": None,
        "future_contract": {"nested": [1, 2, 3]},
    }


def source_entry(
    identifier: str = "ios_ancs_A1B2C3",
    *,
    title: str = "Kitchen Relay",
) -> ConfigEntry:
    return ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title=title,
        data={
            CONF_SOURCE_ENTITY_UNIQUE_ID: f"{identifier}_last_notification",
            CONF_MQTT_DEVICE_IDENTIFIER: identifier,
        },
        source="user",
        unique_id=identifier,
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


def test_sensor_descriptions_cover_complete_contract() -> None:
    assert {description.key for description in SENSOR_DESCRIPTIONS} == (
        EXPECTED_SENSOR_KEYS
    )
    assert len(SENSOR_DESCRIPTIONS) == len(EXPECTED_SENSOR_KEYS)
    assert {
        description.key: (
            description.path,
            description.kind,
            description.fallback_path,
            description.preserve_full_text,
        )
        for description in SENSOR_DESCRIPTIONS
    } == EXPECTED_FIELD_SPECS

    descriptions = {description.key: description for description in SENSOR_DESCRIPTIONS}
    assert descriptions["event"].options == EVENT_OPTIONS
    assert descriptions["category"].options == CATEGORY_OPTIONS
    assert descriptions["received_at_ms"].native_unit_of_measurement == UnitOfTime.MILLISECONDS
    assert descriptions["published_at_ms"].native_unit_of_measurement == UnitOfTime.MILLISECONDS
    assert descriptions["raw_notification"].entity_category == EntityCategory.DIAGNOSTIC


def test_seeded_sensor_states_preserve_full_notification(run) -> None:
    payload = complete_payload()
    entry = entry_with_runtime(payload)
    entities: list[AncsNotificationSensor] = []

    run(async_setup_entry(None, entry, entities.extend))

    assert len(entities) == len(EXPECTED_SENSOR_KEYS)
    states = {entity.entity_description.key: entity.native_value for entity in entities}
    attributes = {
        entity.entity_description.key: entity.extra_state_attributes
        for entity in entities
    }
    assert states["app_name"] == payload["app_id"]
    assert states["message"] == payload["message"][:255]
    assert attributes["message"] == {"full_value": payload["message"]}
    assert states["message_size"] == 4096
    assert states["error_code"] is None
    assert states["error_name"] is None
    assert states["raw_notification"] == payload["relay_id"]
    assert attributes["raw_notification"] == payload

    attributes["raw_notification"]["future_contract"]["nested"].append(4)
    raw_entity = next(
        entity
        for entity in entities
        if entity.entity_description.key == "raw_notification"
    )
    assert raw_entity.extra_state_attributes == payload


def test_sensor_updates_nested_errors_and_rejects_invalid_values(run) -> None:
    entry = entry_with_runtime(complete_payload())
    entities: list[AncsNotificationSensor] = []
    run(async_setup_entry(None, entry, entities.extend))
    by_key = {entity.entity_description.key: entity for entity in entities}

    updated = complete_payload()
    updated["message_size"] = "-10"
    updated["error"] = {"code": -10, "name": "timeout"}
    updated["uid"] = True
    with patch.object(AncsNotificationSensor, "async_write_ha_state"):
        for entity in entities:
            entity._handle_notification(updated)

    assert by_key["error_code"].native_value == -10
    assert by_key["error_name"].native_value == "timeout"
    assert by_key["message_size"].native_value == -10
    assert by_key["uid"].native_value is None

    invalid = complete_payload()
    invalid["message_size"] = "+10"
    invalid["error"] = "invalid"
    with patch.object(AncsNotificationSensor, "async_write_ha_state"):
        for entity in entities:
            entity._handle_notification(invalid)

    assert by_key["message_size"].native_value is None
    assert by_key["error_code"].native_value is None
    assert by_key["error_name"].native_value is None


def test_source_sensors_attach_to_mqtt_device_without_mutating_mqtt_registry(
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
            sensor_component,
            ancs_sensor,
            sensor_component.DOMAIN,
        )
    )

    registry = entity_registry.async_get(hass)
    assert len(entity_ids) == len(EXPECTED_SENSOR_KEYS)
    for entity_id in entity_ids:
        registry_entry = registry.async_get(entity_id)
        assert registry_entry is not None
        assert registry_entry.config_entry_id == entry.entry_id
        assert registry_entry.device_id == registered.device.id
    assert ("mqtt", "ios_ancs_A1B2C3") in registered.device.identifiers
    assert len(device_registry.async_get(hass).devices) == 1
    assert mqtt_registry_snapshot(hass) == before

    run(sensor_component.async_unload_entry(hass, entry))
    run(runtime.async_stop())
    assert mqtt_registry_snapshot(hass) == before
    assert entity_registry.async_get(hass).async_get(registered.entity.entity_id) is not None


def test_legacy_sensors_share_one_integration_owned_device(registry_hass, run) -> None:
    hass = registry_hass
    entry = legacy_entry()
    runtime = AncsMqttRuntime(hass, "ios_ancs/legacy")

    _, entity_ids = run(
        async_setup_ancs_platform(
            hass,
            entry,
            runtime,
            sensor_component,
            ancs_sensor,
            sensor_component.DOMAIN,
        )
    )

    registry = entity_registry.async_get(hass)
    device_ids = {
        registry_entry.device_id
        for entity_id in entity_ids
        if (registry_entry := registry.async_get(entity_id)) is not None
    }
    assert len(entity_ids) == len(EXPECTED_SENSOR_KEYS)
    assert len(device_ids) == 1
    device_id = device_ids.pop()
    assert device_id is not None
    legacy_device = device_registry.async_get(hass).async_get(device_id)
    assert legacy_device is not None
    assert (DOMAIN, entry.entry_id) in legacy_device.identifiers

    run(sensor_component.async_unload_entry(hass, entry))
    run(runtime.async_stop())


def test_source_sensors_ignore_every_rejected_notification(registry_hass, run) -> None:
    hass = registry_hass
    registered = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_A1B2C3",
            device_name="Kitchen Relay",
        )
    )
    seed = complete_payload()
    seed["relay_id"] = "seed-relay"
    seed["title"] = "Accepted title"
    seed["pre_existing"] = False
    hass.states.async_set(registered.entity.entity_id, seed["relay_id"], seed)
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
            sensor_component,
            ancs_sensor,
            sensor_component.DOMAIN,
        )
    )
    registry = entity_registry.async_get(hass)
    title_id = next(
        entity_id
        for entity_id in entity_ids
        if (item := registry.async_get(entity_id)) is not None
        and item.unique_id.endswith(":sensor:title")
    )

    rejected_payloads = [
        {**seed, "relay_id": "incomplete", "title": "Rejected", "complete": False},
        {
            **seed,
            "relay_id": "pre-existing",
            "title": "Rejected",
            "pre_existing": True,
        },
        {**seed, "relay_id": "removed", "title": "Rejected", "event": "removed"},
        {
            **seed,
            "relay_id": "ha-echo",
            "title": "Rejected",
            "app_id": HA_ECHO_APP_ID,
        },
        {**seed, "title": "Rejected duplicate"},
    ]
    for payload in rejected_payloads:
        hass.states.async_set(
            registered.entity.entity_id,
            payload["relay_id"],
            payload,
        )
        run(hass.async_block_till_done())
        state = hass.states.get(title_id)
        assert state is not None
        assert state.state == "Accepted title"

    run(sensor_component.async_unload_entry(hass, entry))
    run(runtime.async_stop())


def test_two_source_entries_keep_notification_state_isolated(registry_hass, run) -> None:
    hass = registry_hass
    registered_a = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_A1B2C3",
            device_name="Kitchen Relay",
        )
    )
    registered_b = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_D4E5F6",
            device_name="Living Room Relay",
        )
    )
    payload_a = complete_payload()
    payload_a.update(relay_id="a-1", title="Kitchen title")
    payload_b = complete_payload()
    payload_b.update(relay_id="b-1", title="Living room title")
    hass.states.async_set(registered_a.entity.entity_id, "a-1", payload_a)
    hass.states.async_set(registered_b.entity.entity_id, "b-1", payload_b)

    entry_a = source_entry()
    entry_b = source_entry("ios_ancs_D4E5F6", title="Living Room Relay")
    runtime_a = AncsSourceRuntime(
        hass,
        registered_a.entity.unique_id,
        "ios_ancs_A1B2C3",
    )
    runtime_b = AncsSourceRuntime(
        hass,
        registered_b.entity.unique_id,
        "ios_ancs_D4E5F6",
    )
    run(runtime_a.async_start())
    run(runtime_b.async_start())
    _, ids_a = run(
        async_setup_ancs_platform(
            hass,
            entry_a,
            runtime_a,
            sensor_component,
            ancs_sensor,
            sensor_component.DOMAIN,
        )
    )
    _, ids_b = run(
        async_setup_ancs_platform(
            hass,
            entry_b,
            runtime_b,
            sensor_component,
            ancs_sensor,
            sensor_component.DOMAIN,
        )
    )
    registry = entity_registry.async_get(hass)
    title_a = next(
        entity_id
        for entity_id in ids_a
        if (item := registry.async_get(entity_id)) is not None
        and item.unique_id.endswith(":sensor:title")
    )
    title_b = next(
        entity_id
        for entity_id in ids_b
        if (item := registry.async_get(entity_id)) is not None
        and item.unique_id.endswith(":sensor:title")
    )

    payload_a.update(relay_id="a-2", title="Kitchen updated")
    hass.states.async_set(registered_a.entity.entity_id, "a-2", payload_a)
    run(hass.async_block_till_done())
    assert hass.states.get(title_a).state == "Kitchen updated"
    assert hass.states.get(title_b).state == "Living room title"

    run(sensor_component.async_unload_entry(hass, entry_a))
    run(runtime_a.async_stop())
    payload_b.update(relay_id="b-2", title="Living room updated")
    hass.states.async_set(registered_b.entity.entity_id, "b-2", payload_b)
    run(hass.async_block_till_done())

    assert hass.states.get(title_a).state == "unavailable"
    assert hass.states.get(title_b).state == "Living room updated"
    assert hass.states.get(registered_a.entity.entity_id) is not None
    assert hass.states.get(registered_b.entity.entity_id) is not None

    run(sensor_component.async_unload_entry(hass, entry_b))
    run(runtime_b.async_stop())
