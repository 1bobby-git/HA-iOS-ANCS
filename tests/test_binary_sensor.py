from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import EntityCategory

from custom_components.ha_ios_ancs.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS,
    AncsNotificationBinarySensor,
    async_setup_entry,
)


EXPECTED_BINARY_SENSOR_KEYS = {
    "complete",
    "silent",
    "important",
    "pre_existing",
    "positive_action_available",
    "negative_action_available",
    "app_id_truncated",
    "title_truncated",
    "subtitle_truncated",
    "message_truncated",
    "has_error",
}

EXPECTED_FIELD_PATHS = {
    "complete": ("complete",),
    "silent": ("silent",),
    "important": ("important",),
    "pre_existing": ("pre_existing",),
    "positive_action_available": ("positive_action_available",),
    "negative_action_available": ("negative_action_available",),
    "app_id_truncated": ("truncated", "app_id"),
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


def entry_with_runtime(payload: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        entry_id="entry-1",
        unique_id="ios_ancs_A1B2C3",
        title="Kitchen Relay",
        runtime_data=RuntimeStub(payload),
    )


def test_binary_descriptions_cover_boolean_contract() -> None:
    assert {
        description.key for description in BINARY_SENSOR_DESCRIPTIONS
    } == EXPECTED_BINARY_SENSOR_KEYS
    assert len(BINARY_SENSOR_DESCRIPTIONS) == len(EXPECTED_BINARY_SENSOR_KEYS)
    assert {
        description.key: description.path
        for description in BINARY_SENSOR_DESCRIPTIONS
    } == EXPECTED_FIELD_PATHS

    descriptions = {
        description.key: description
        for description in BINARY_SENSOR_DESCRIPTIONS
    }
    assert descriptions["has_error"].non_null_presence is True
    for key in EXPECTED_BINARY_SENSOR_KEYS - {"has_error"}:
        assert descriptions[key].non_null_presence is False
    for key in {
        "app_id_truncated",
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
        "title_truncated": True,
        "subtitle_truncated": False,
        "message_truncated": True,
        "has_error": False,
    }

    by_key = {entity.entity_description.key: entity for entity in entities}
    with_error = deepcopy(payload)
    with_error["error"] = {"code": -10, "name": "timeout"}
    with patch.object(AncsNotificationBinarySensor, "async_write_ha_state"):
        for entity in entities:
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
