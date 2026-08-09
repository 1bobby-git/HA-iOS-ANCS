"""Config flow for the HA iOS ANCS integration."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector

from .const import (
    CONF_MQTT_DEVICE_IDENTIFIER,
    CONF_SOURCE_ENTITY_UNIQUE_ID,
    DOMAIN,
)
from .source import AncsSource, async_discover_ancs_sources


_WHITESPACE = re.compile(r"\s")


def normalize_base_topic(raw_topic: object) -> str:
    """Return a canonical MQTT base topic or raise ValueError."""

    if not isinstance(raw_topic, str):
        raise ValueError("invalid MQTT base topic")

    topic = raw_topic.strip().strip("/")
    if (
        not topic
        or _WHITESPACE.search(topic)
        or "+" in topic
        or "#" in topic
        or "//" in topic
    ):
        raise ValueError("invalid MQTT base topic")
    return topic


async def _async_mqtt_available(hass: HomeAssistant) -> bool:
    """Return whether the Home Assistant MQTT client is available."""

    from homeassistant.components import mqtt

    return await mqtt.async_wait_for_mqtt_client(hass)


def _source_data(source: AncsSource) -> dict[str, str]:
    """Return config-entry data for an MQTT ANCS source."""

    return {
        CONF_SOURCE_ENTITY_UNIQUE_ID: source.entity_unique_id,
        CONF_MQTT_DEVICE_IDENTIFIER: source.mqtt_device_identifier,
    }


def _source_schema(sources: list[AncsSource]) -> vol.Schema:
    """Return a device-name selector for compatible MQTT sources."""

    options = [
        {
            "value": source.entity_unique_id,
            "label": f"{source.name} ({source.mqtt_device_identifier})",
        }
        for source in sources
    ]
    return vol.Schema(
        {
            vol.Required(CONF_SOURCE_ENTITY_UNIQUE_ID): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        }
    )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for HA iOS ANCS."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Discover and configure the existing MQTT ANCS device."""

        if not await _async_mqtt_available(self.hass):
            return self.async_abort(reason="mqtt_unavailable")

        sources = async_discover_ancs_sources(self.hass)
        if not sources:
            return self.async_abort(reason="no_devices_found")

        if user_input is None and len(sources) == 1:
            return await self._async_create_source_entry(sources[0])

        if user_input is not None:
            selected_unique_id = user_input[CONF_SOURCE_ENTITY_UNIQUE_ID]
            selected_source = next(
                (
                    source
                    for source in sources
                    if source.entity_unique_id == selected_unique_id
                ),
                None,
            )
            if selected_source is None:
                return self.async_abort(reason="no_devices_found")
            return await self._async_create_source_entry(selected_source)

        return self.async_show_form(
            step_id="user",
            data_schema=_source_schema(sources),
        )

    async def _async_create_source_entry(
        self, source: AncsSource
    ) -> config_entries.ConfigFlowResult:
        """Create a config entry for a discovered MQTT ANCS source."""

        await self.async_set_unique_id(source.mqtt_device_identifier)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=source.name,
            data=_source_data(source),
        )
