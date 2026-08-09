from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from homeassistant.const import EntityCategory, UnitOfTime

from custom_components.ha_ios_ancs.sensor import (
    CATEGORY_OPTIONS,
    EVENT_OPTIONS,
    SENSOR_DESCRIPTIONS,
    AncsNotificationSensor,
    SensorValueKind,
    async_setup_entry,
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
        "device_name": "IOS-ANCS-C6-2B20",
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
