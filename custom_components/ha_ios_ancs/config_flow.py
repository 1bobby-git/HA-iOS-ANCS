"""Config flow for the HA iOS ANCS integration."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from .const import CONF_BASE_TOPIC, DOMAIN


_WHITESPACE = re.compile(r"\s")


def normalize_base_topic(raw_topic: str) -> str:
    """Return a canonical MQTT base topic or raise ValueError."""

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


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for HA iOS ANCS."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial user step."""

        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                base_topic = normalize_base_topic(user_input[CONF_BASE_TOPIC])
            except ValueError:
                errors[CONF_BASE_TOPIC] = "invalid_base_topic"
            else:
                if not await _async_mqtt_available(self.hass):
                    errors[CONF_BASE_TOPIC] = "mqtt_unavailable"
                    return self.async_show_form(
                        step_id="user",
                        data_schema=vol.Schema({vol.Required(CONF_BASE_TOPIC): str}),
                        errors=errors,
                    )

                await self.async_set_unique_id(base_topic)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"HA iOS ANCS ({base_topic})",
                    data={CONF_BASE_TOPIC: base_topic},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_BASE_TOPIC): str}),
            errors=errors,
        )
