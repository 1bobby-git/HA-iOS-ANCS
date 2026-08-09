from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant import config_entries
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.ha_ios_ancs.config_flow import normalize_base_topic
from custom_components.ha_ios_ancs.const import (
    CONF_BASE_TOPIC,
    CONF_MQTT_DEVICE_IDENTIFIER,
    CONF_SOURCE_ENTITY_UNIQUE_ID,
    DOMAIN,
)

from tests.helpers import EMPTY_DISCOVERY_KEYS, async_register_mqtt_ancs_source


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ios_ancs", "ios_ancs"),
        (" ios_ancs ", "ios_ancs"),
        ("/ios_ancs/", "ios_ancs"),
        (" /ios_ancs/device-1/ ", "ios_ancs/device-1"),
    ],
)
def test_normalize_base_topic_canonicalizes_valid_topics(raw: str, expected: str) -> None:
    assert normalize_base_topic(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "/",
        "ios ancs",
        "ios\tancs",
        "ios+ancs",
        "ios#ancs",
        "ios//ancs",
        "/ios//ancs/",
    ],
)
def test_normalize_base_topic_rejects_invalid_topics(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_base_topic(raw)


@pytest.mark.parametrize("raw", [None, 7, [], {}])
def test_normalize_base_topic_rejects_non_string_values(raw: object) -> None:
    with pytest.raises(ValueError):
        normalize_base_topic(raw)


def test_config_flow_auto_creates_entry_for_one_mqtt_ancs_device(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    registered = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_A1B2C3",
            device_name="Kitchen iPhone Relay",
        )
    )
    with (
        patch.object(hass.config_entries, "async_setup", new=AsyncMock(return_value=True)),
        patch(
            "custom_components.ha_ios_ancs.config_flow._async_mqtt_available",
            new=AsyncMock(return_value=True),
        ),
    ):
        result = run(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Kitchen iPhone Relay"
    assert result["data"] == {
        CONF_SOURCE_ENTITY_UNIQUE_ID: registered.entity.unique_id,
        CONF_MQTT_DEVICE_IDENTIFIER: "ios_ancs_A1B2C3",
    }
    assert CONF_BASE_TOPIC not in result["data"]


def test_config_flow_shows_device_selector_for_multiple_sources(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    first = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_A1B2C3",
            device_name="Kitchen Relay",
        )
    )
    second = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_D4E5F6",
            device_name="Office Relay",
        )
    )
    with (
        patch.object(hass.config_entries, "async_setup", new=AsyncMock(return_value=True)),
        patch(
            "custom_components.ha_ios_ancs.config_flow._async_mqtt_available",
            new=AsyncMock(return_value=True),
        ),
    ):
        form = run(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )
        )
        result = run(
            hass.config_entries.flow.async_configure(
                form["flow_id"],
                {CONF_SOURCE_ENTITY_UNIQUE_ID: second.entity.unique_id},
            )
        )

    schema_keys = [key.schema for key in form["data_schema"].schema]
    assert form["type"] is FlowResultType.FORM
    assert form["step_id"] == "user"
    assert schema_keys == [CONF_SOURCE_ENTITY_UNIQUE_ID]
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Office Relay"
    assert result["data"] == {
        CONF_SOURCE_ENTITY_UNIQUE_ID: second.entity.unique_id,
        CONF_MQTT_DEVICE_IDENTIFIER: "ios_ancs_D4E5F6",
    }
    assert first.entity.unique_id != second.entity.unique_id


def test_config_flow_aborts_when_no_compatible_device_exists(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    with patch(
        "custom_components.ha_ios_ancs.config_flow._async_mqtt_available",
        new=AsyncMock(return_value=True),
    ):
        result = run(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


def test_config_flow_aborts_when_mqtt_is_unavailable(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    with patch(
        "custom_components.ha_ios_ancs.config_flow._async_mqtt_available",
        new=AsyncMock(return_value=False),
    ):
        result = run(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "mqtt_unavailable"


def test_config_flow_duplicate_mqtt_device_identifier_aborts(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_A1B2C3",
            device_name="Kitchen Relay",
        )
    )
    with (
        patch.object(hass.config_entries, "async_setup", new=AsyncMock(return_value=True)),
        patch(
            "custom_components.ha_ios_ancs.config_flow._async_mqtt_available",
            new=AsyncMock(return_value=True),
        ),
    ):
        first = run(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )
        )
        duplicate = run(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )
        )

    assert first["type"] is FlowResultType.CREATE_ENTRY
    assert duplicate["type"] is FlowResultType.ABORT
    assert duplicate["reason"] == "already_configured"


def test_config_flow_reconfigure_converts_legacy_entry_and_migrates_event(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    registered = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_A1B2C3",
            device_name="Kitchen iPhone Relay",
        )
    )
    legacy_entry = config_entries.ConfigEntry(
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
    with patch.object(
        hass.config_entries,
        "async_setup",
        new=AsyncMock(return_value=True),
    ):
        run(hass.config_entries.async_add(legacy_entry))

    device_registry = dr.async_get(hass)
    legacy_device = device_registry.async_get_or_create(
        config_entry_id=legacy_entry.entry_id,
        identifiers={(DOMAIN, legacy_entry.entry_id)},
        name=legacy_entry.title,
    )
    entity_registry = er.async_get(hass)
    legacy_event = entity_registry.async_get_or_create(
        Platform.EVENT,
        DOMAIN,
        "ios_ancs/legacy:notification",
        config_entry=legacy_entry,
        device_id=legacy_device.id,
        suggested_object_id="ha_ios_ancs_notification",
    )
    assert device_registry.async_get(legacy_device.id) is not None

    with (
        patch(
            "custom_components.ha_ios_ancs.config_flow._async_mqtt_available",
            new=AsyncMock(return_value=True),
        ),
        patch.object(
            hass.config_entries,
            "async_reload",
            new=AsyncMock(return_value=True),
        ),
    ):
        form = run(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_RECONFIGURE,
                    "entry_id": legacy_entry.entry_id,
                },
            )
        )
        result = run(
            hass.config_entries.flow.async_configure(
                form["flow_id"],
                {CONF_SOURCE_ENTITY_UNIQUE_ID: registered.entity.unique_id},
            )
        )

    assert form["type"] is FlowResultType.FORM
    assert form["step_id"] == "reconfigure"
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert legacy_entry.data == {
        CONF_SOURCE_ENTITY_UNIQUE_ID: registered.entity.unique_id,
        CONF_MQTT_DEVICE_IDENTIFIER: "ios_ancs_A1B2C3",
    }
    assert legacy_entry.unique_id == "ios_ancs_A1B2C3"
    assert legacy_entry.title == "Kitchen iPhone Relay"
    migrated = entity_registry.async_get(legacy_event.entity_id)
    assert migrated is not None
    assert migrated.id == legacy_event.id
    assert migrated.unique_id == "ios_ancs_A1B2C3:notification"
    assert migrated.device_id == registered.device.id
    assert device_registry.async_get(legacy_device.id) is None


def test_config_flow_reconfigure_defaults_to_current_mqtt_source(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_A1B2C3",
            device_name="Kitchen Relay",
        )
    )
    current = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_D4E5F6",
            device_name="Office Relay",
        )
    )
    entry = config_entries.ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="Office Relay",
        data={
            CONF_SOURCE_ENTITY_UNIQUE_ID: current.entity.unique_id,
            CONF_MQTT_DEVICE_IDENTIFIER: "ios_ancs_D4E5F6",
        },
        source="user",
        unique_id="ios_ancs_D4E5F6",
        discovery_keys=EMPTY_DISCOVERY_KEYS,
        options={},
        subentries_data={},
    )
    with patch.object(
        hass.config_entries,
        "async_setup",
        new=AsyncMock(return_value=True),
    ):
        run(hass.config_entries.async_add(entry))

    with patch(
        "custom_components.ha_ios_ancs.config_flow._async_mqtt_available",
        new=AsyncMock(return_value=True),
    ):
        form = run(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_RECONFIGURE,
                    "entry_id": entry.entry_id,
                },
            )
        )

    source_key = next(iter(form["data_schema"].schema))
    assert form["type"] is FlowResultType.FORM
    assert form["step_id"] == "reconfigure"
    assert source_key.schema == CONF_SOURCE_ENTITY_UNIQUE_ID
    assert source_key.default() == current.entity.unique_id


def test_config_flow_reconfigure_infers_recommended_legacy_topic_source(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_c3_a5dc",
            device_name="Living Room Relay",
        )
    )
    expected = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_c6_2b20",
            device_name="Office Relay",
        )
    )
    legacy_entry = config_entries.ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="HA iOS ANCS (ios-ancs/c6-2b20/state)",
        data={CONF_BASE_TOPIC: "ios-ancs/c6-2b20/state"},
        source="user",
        unique_id="ios-ancs/c6-2b20/state",
        discovery_keys=EMPTY_DISCOVERY_KEYS,
        options={},
        subentries_data={},
    )
    with patch.object(
        hass.config_entries,
        "async_setup",
        new=AsyncMock(return_value=True),
    ):
        run(hass.config_entries.async_add(legacy_entry))

    with patch(
        "custom_components.ha_ios_ancs.config_flow._async_mqtt_available",
        new=AsyncMock(return_value=True),
    ):
        form = run(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_RECONFIGURE,
                    "entry_id": legacy_entry.entry_id,
                },
            )
        )

    source_key = next(iter(form["data_schema"].schema))
    assert form["type"] is FlowResultType.FORM
    assert form["step_id"] == "reconfigure"
    assert callable(source_key.default)
    assert source_key.default() == expected.entity.unique_id


def test_config_flow_reconfigure_removes_existing_orphan_legacy_device(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    registered = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_A1B2C3",
            device_name="Kitchen iPhone Relay",
        )
    )
    entry = config_entries.ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="Kitchen iPhone Relay",
        data={
            CONF_SOURCE_ENTITY_UNIQUE_ID: registered.entity.unique_id,
            CONF_MQTT_DEVICE_IDENTIFIER: "ios_ancs_A1B2C3",
        },
        source="user",
        unique_id="ios_ancs_A1B2C3",
        discovery_keys=EMPTY_DISCOVERY_KEYS,
        options={},
        subentries_data={},
    )
    with patch.object(
        hass.config_entries,
        "async_setup",
        new=AsyncMock(return_value=True),
    ):
        run(hass.config_entries.async_add(entry))

    device_registry = dr.async_get(hass)
    legacy_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="HA iOS ANCS (ios_ancs/legacy)",
    )
    entity_registry = er.async_get(hass)
    event = entity_registry.async_get_or_create(
        Platform.EVENT,
        DOMAIN,
        "ios_ancs_A1B2C3:notification",
        config_entry=entry,
        device_id=registered.device.id,
        suggested_object_id="ha_ios_ancs_notification",
    )
    assert device_registry.async_get(legacy_device.id) is not None

    with (
        patch(
            "custom_components.ha_ios_ancs.config_flow._async_mqtt_available",
            new=AsyncMock(return_value=True),
        ),
        patch.object(
            hass.config_entries,
            "async_reload",
            new=AsyncMock(return_value=True),
        ),
    ):
        form = run(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_RECONFIGURE,
                    "entry_id": entry.entry_id,
                },
            )
        )
        result = run(
            hass.config_entries.flow.async_configure(
                form["flow_id"],
                {CONF_SOURCE_ENTITY_UNIQUE_ID: registered.entity.unique_id},
            )
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    unchanged = entity_registry.async_get(event.entity_id)
    assert unchanged is not None
    assert unchanged.unique_id == "ios_ancs_A1B2C3:notification"
    assert unchanged.device_id == registered.device.id
    assert device_registry.async_get(legacy_device.id) is None


def test_config_flow_reconfigure_duplicate_leaves_legacy_entry_unchanged(
    registry_hass: HomeAssistant, run
) -> None:
    hass = registry_hass
    registered = run(
        async_register_mqtt_ancs_source(
            hass,
            "ios_ancs_A1B2C3",
            device_name="Kitchen iPhone Relay",
        )
    )
    configured_entry = config_entries.ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="Kitchen iPhone Relay",
        data={
            CONF_SOURCE_ENTITY_UNIQUE_ID: registered.entity.unique_id,
            CONF_MQTT_DEVICE_IDENTIFIER: "ios_ancs_A1B2C3",
        },
        source="user",
        unique_id="ios_ancs_A1B2C3",
        discovery_keys=EMPTY_DISCOVERY_KEYS,
        options={},
        subentries_data={},
    )
    legacy_entry = config_entries.ConfigEntry(
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
    with patch.object(
        hass.config_entries,
        "async_setup",
        new=AsyncMock(return_value=True),
    ):
        run(hass.config_entries.async_add(configured_entry))
        run(hass.config_entries.async_add(legacy_entry))

    device_registry = dr.async_get(hass)
    legacy_device = device_registry.async_get_or_create(
        config_entry_id=legacy_entry.entry_id,
        identifiers={(DOMAIN, legacy_entry.entry_id)},
        name=legacy_entry.title,
    )
    entity_registry = er.async_get(hass)
    legacy_event = entity_registry.async_get_or_create(
        Platform.EVENT,
        DOMAIN,
        "ios_ancs/legacy:notification",
        config_entry=legacy_entry,
        device_id=legacy_device.id,
        suggested_object_id="ha_ios_ancs_notification",
    )

    with patch(
        "custom_components.ha_ios_ancs.config_flow._async_mqtt_available",
        new=AsyncMock(return_value=True),
    ):
        form = run(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": config_entries.SOURCE_RECONFIGURE,
                    "entry_id": legacy_entry.entry_id,
                },
            )
        )
        result = run(
            hass.config_entries.flow.async_configure(
                form["flow_id"],
                {CONF_SOURCE_ENTITY_UNIQUE_ID: registered.entity.unique_id},
            )
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert legacy_entry.data == {CONF_BASE_TOPIC: "ios_ancs/legacy"}
    assert legacy_entry.unique_id == "ios_ancs/legacy"
    unchanged = entity_registry.async_get(legacy_event.entity_id)
    assert unchanged is not None
    assert unchanged.unique_id == "ios_ancs/legacy:notification"
    assert unchanged.device_id == legacy_device.id
    assert device_registry.async_get(legacy_device.id) is not None


def test_manifest_contract() -> None:
    manifest = json.loads(
        (ROOT / "custom_components/ha_ios_ancs/manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert list(manifest) == [
        "domain",
        "name",
        "codeowners",
        "config_flow",
        "dependencies",
        "documentation",
        "integration_type",
        "iot_class",
        "issue_tracker",
        "requirements",
        "version",
    ]
    assert manifest == {
        "domain": "ha_ios_ancs",
        "name": "HA iOS ANCS",
        "codeowners": ["@1bobby-git"],
        "config_flow": True,
        "dependencies": ["mqtt"],
        "documentation": "https://github.com/1bobby-git/HA-iOS-ANCS",
        "integration_type": "device",
        "iot_class": "local_push",
        "issue_tracker": "https://github.com/1bobby-git/HA-iOS-ANCS/issues",
        "requirements": [],
        "version": "0.6.0",
    }


def test_translations_contract() -> None:
    strings = json.loads(
        (ROOT / "custom_components/ha_ios_ancs/strings.json").read_text(
            encoding="utf-8"
        )
    )
    en = json.loads(
        (ROOT / "custom_components/ha_ios_ancs/translations/en.json").read_text(
            encoding="utf-8"
        )
    )
    ko = json.loads(
        (ROOT / "custom_components/ha_ios_ancs/translations/ko.json").read_text(
            encoding="utf-8"
        )
    )

    expected_entity_keys = {
        "sensor": {
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
        },
        "binary_sensor": {
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
        },
        "event": {"notification"},
    }

    assert strings.keys() == en.keys() == ko.keys()
    assert strings["config"].keys() == en["config"].keys() == ko["config"].keys()
    for data in (strings, en, ko):
        assert data["title"]
        assert data["config"]["step"]["user"]["description"]
        assert data["config"]["step"]["user"]["data"] == {
            CONF_SOURCE_ENTITY_UNIQUE_ID: data["config"]["step"]["user"]["data"][
                CONF_SOURCE_ENTITY_UNIQUE_ID
            ]
        }
        assert CONF_BASE_TOPIC not in data["config"]["step"]["user"]["data"]
        assert data["config"]["abort"]["already_configured"]
        assert data["config"]["abort"]["mqtt_unavailable"]
        assert data["config"]["abort"]["no_devices_found"]
        assert set(data["entity"]) == set(expected_entity_keys)
        for platform, keys in expected_entity_keys.items():
            assert set(data["entity"][platform]) == keys
            assert all(data["entity"][platform][key]["name"] for key in keys)

        assert set(data["entity"]["sensor"]["event"]["state"]) == {
            "added",
            "modified",
            "removed",
        }
        assert set(data["entity"]["sensor"]["category"]["state"]) == {
            "other",
            "incoming_call",
            "missed_call",
            "voicemail",
            "social",
            "schedule",
            "email",
            "news",
            "health_and_fitness",
            "business_and_finance",
            "location",
            "entertainment",
            "reserved",
        }

    assert en["title"] == "HA iOS ANCS"
    assert (
        en["config"]["step"]["user"]["data"][CONF_SOURCE_ENTITY_UNIQUE_ID]
        == "MQTT device"
    )
    assert "MQTT" in en["config"]["step"]["user"]["description"]
    assert "MQTT" in ko["config"]["step"]["user"]["description"]
    assert ko["entity"]["event"]["notification"]["name"] == "알림"
    assert ko["entity"]["sensor"]["message"]["name"] == "알림 내용"
    assert ko["entity"]["binary_sensor"]["has_error"]["name"] == "오류 발생"
