from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.ha_ios_ancs.config_flow import normalize_base_topic
from custom_components.ha_ios_ancs.const import (
    CONF_BASE_TOPIC,
    CONF_MQTT_DEVICE_IDENTIFIER,
    CONF_SOURCE_ENTITY_UNIQUE_ID,
    DOMAIN,
)

from tests.helpers import async_register_mqtt_ancs_source


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
        "version": "0.4.1",
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

    assert en["title"] == "HA iOS ANCS"
    assert (
        en["config"]["step"]["user"]["data"][CONF_SOURCE_ENTITY_UNIQUE_ID]
        == "MQTT device"
    )
    assert "MQTT" in en["config"]["step"]["user"]["description"]
    assert "MQTT" in ko["config"]["step"]["user"]["description"]
    assert ko["entity"]["event"]["notification"]["name"] == "알림"
