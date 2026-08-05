from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.ha_ios_ancs.config_flow import normalize_base_topic
from custom_components.ha_ios_ancs.const import CONF_BASE_TOPIC, DOMAIN


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


def test_config_flow_user_step_shows_form(hass: HomeAssistant, run) -> None:
    result = run(hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER}))

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}


def test_config_flow_creates_entry_with_canonical_topic(hass: HomeAssistant, run) -> None:
    with patch.object(hass.config_entries, "async_setup", new=AsyncMock(return_value=True)):
        result = run(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
                data={CONF_BASE_TOPIC: " /ios_ancs/device-1/ "},
            )
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "HA iOS ANCS (ios_ancs/device-1)"
    assert result["data"] == {CONF_BASE_TOPIC: "ios_ancs/device-1"}


def test_config_flow_invalid_topic_returns_field_error(hass: HomeAssistant, run) -> None:
    result = run(
        hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_BASE_TOPIC: "ios ancs"},
        )
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {CONF_BASE_TOPIC: "invalid_base_topic"}


def test_config_flow_duplicate_canonical_topic_aborts(hass: HomeAssistant, run) -> None:
    with patch.object(hass.config_entries, "async_setup", new=AsyncMock(return_value=True)):
        first = run(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
                data={CONF_BASE_TOPIC: "ios_ancs"},
            )
        )
        assert first["type"] is FlowResultType.CREATE_ENTRY

        duplicate = run(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
                data={CONF_BASE_TOPIC: "/ios_ancs/"},
            )
        )

        assert duplicate["type"] is FlowResultType.ABORT
        assert duplicate["reason"] == "already_configured"


def test_manifest_contract() -> None:
    manifest = json.loads((ROOT / "custom_components/ha_ios_ancs/manifest.json").read_text(encoding="utf-8"))

    assert manifest == {
        "domain": "ha_ios_ancs",
        "name": "HA iOS ANCS",
        "codeowners": ["@1bobby-git"],
        "config_flow": True,
        "dependencies": ["mqtt"],
        "documentation": "https://github.com/1bobby-git/HA-iOS-ANCS",
        "issue_tracker": "https://github.com/1bobby-git/HA-iOS-ANCS/issues",
        "integration_type": "device",
        "iot_class": "local_push",
        "requirements": [],
        "version": "0.4.0",
    }


def test_translations_contract() -> None:
    en = json.loads((ROOT / "custom_components/ha_ios_ancs/translations/en.json").read_text(encoding="utf-8"))
    ko = json.loads((ROOT / "custom_components/ha_ios_ancs/translations/ko.json").read_text(encoding="utf-8"))

    for data in (en, ko):
        assert data["title"]
        assert data["config"]["step"]["user"]["description"]
        assert data["config"]["step"]["user"]["data"][CONF_BASE_TOPIC]
        assert data["config"]["error"]["invalid_base_topic"]
        assert data["config"]["abort"]["already_configured"]

    assert en["title"] == "HA iOS ANCS"
    assert en["config"]["step"]["user"]["data"][CONF_BASE_TOPIC] == "Base MQTT topic"
    assert "MQTT" in en["config"]["step"]["user"]["description"]
    assert "MQTT" in ko["config"]["step"]["user"]["description"]
