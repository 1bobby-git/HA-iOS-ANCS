"""Config flow for the iOS ANCS integration."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    CONFIG_ENTRY_VERSION,
    CONF_BASE_TOPIC,
    CONF_MQTT_DEVICE_IDENTIFIER,
    CONF_SOURCE_ENTITY_UNIQUE_ID,
    DOMAIN,
    EVENT_TYPE_NOTIFICATION,
)
from .device import async_ensure_integration_device, source_title
from .source import AncsSource, async_discover_ancs_sources


_WHITESPACE = re.compile(r"\s")
_RECOMMENDED_LEGACY_TOPIC = re.compile(
    r"^ios[-_]ancs/([a-z0-9][a-z0-9_-]*)(?:/(?:state|notification))?$",
    re.IGNORECASE,
)


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


def _default_source_unique_id(
    sources: list[AncsSource],
    entry_data: Mapping[str, Any],
) -> str | None:
    """Return the current or safely inferred MQTT source for reconfigure."""

    current_unique_id = entry_data.get(CONF_SOURCE_ENTITY_UNIQUE_ID)
    if isinstance(current_unique_id, str):
        return current_unique_id

    base_topic = entry_data.get(CONF_BASE_TOPIC)
    if not isinstance(base_topic, str):
        return None

    match = _RECOMMENDED_LEGACY_TOPIC.fullmatch(base_topic.strip().strip("/"))
    if match is None:
        return None

    expected_identifier = f"ios_ancs_{match.group(1).replace('-', '_')}"
    matches = [
        source.entity_unique_id
        for source in sources
        if source.mqtt_device_identifier.casefold()
        == expected_identifier.casefold()
    ]
    return matches[0] if len(matches) == 1 else None


def _source_schema(
    sources: list[AncsSource],
    default_source_unique_id: str | None = None,
) -> vol.Schema:
    """Return a device-name selector for compatible MQTT sources."""

    source_unique_ids = {source.entity_unique_id for source in sources}
    source_key = (
        vol.Required(
            CONF_SOURCE_ENTITY_UNIQUE_ID,
            default=default_source_unique_id,
        )
        if default_source_unique_id in source_unique_ids
        else vol.Required(CONF_SOURCE_ENTITY_UNIQUE_ID)
    )
    options: list[selector.SelectOptionDict] = [
        {
            "value": source.entity_unique_id,
            "label": f"{source.name} ({source.mqtt_device_identifier})",
        }
        for source in sources
    ]
    return vol.Schema(
        {
            source_key: selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        }
    )


def _selected_source(
    sources: list[AncsSource], user_input: dict[str, Any]
) -> AncsSource | None:
    """Return the currently discovered source selected by the user."""

    selected_unique_id = user_input[CONF_SOURCE_ENTITY_UNIQUE_ID]
    return next(
        (
            source
            for source in sources
            if source.entity_unique_id == selected_unique_id
        ),
        None,
    )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for iOS ANCS."""

    VERSION = CONFIG_ENTRY_VERSION

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
            selected_source = _selected_source(sources, user_input)
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
            title=source_title(source.mqtt_device_identifier),
            data=_source_data(source),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Explicitly attach an existing entry to a discovered MQTT device."""

        if not await _async_mqtt_available(self.hass):
            return self.async_abort(reason="mqtt_unavailable")

        sources = async_discover_ancs_sources(self.hass)
        if not sources:
            return self.async_abort(reason="no_devices_found")

        if user_input is None:
            entry = self._get_reconfigure_entry()
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=_source_schema(
                    sources,
                    _default_source_unique_id(sources, entry.data),
                ),
            )

        source = _selected_source(sources, user_input)
        if source is None:
            return self.async_abort(reason="no_devices_found")

        entry = self._get_reconfigure_entry()
        if any(
            candidate.entry_id != entry.entry_id
            and candidate.unique_id == source.mqtt_device_identifier
            for candidate in self._async_current_entries()
        ):
            return self.async_abort(reason="already_configured")

        old_event_unique_id: str | None = None
        if isinstance(base_topic := entry.data.get(CONF_BASE_TOPIC), str):
            old_event_unique_id = f"{base_topic}:{EVENT_TYPE_NOTIFICATION}"
        elif isinstance(
            old_device_identifier := entry.data.get(CONF_MQTT_DEVICE_IDENTIFIER),
            str,
        ):
            old_event_unique_id = (
                f"{old_device_identifier}:{EVENT_TYPE_NOTIFICATION}"
            )

        owned_device = async_ensure_integration_device(self.hass, entry)
        self._async_migrate_companion_entities(
            entry.entry_id,
            entry.unique_id or entry.entry_id,
            old_event_unique_id,
            source,
            owned_device.id,
        )

        return self.async_update_reload_and_abort(
            entry,
            data=_source_data(source),
            unique_id=source.mqtt_device_identifier,
            title=source_title(source.mqtt_device_identifier),
            reason="reconfigure_successful",
        )

    def _async_migrate_companion_entities(
        self,
        entry_id: str,
        old_detail_identity: str,
        old_event_unique_id: str | None,
        source: AncsSource,
        owned_device_id: str,
    ) -> None:
        """Update companion identities on the integration-owned device."""

        entity_registry = er.async_get(self.hass)
        target_identity = source.mqtt_device_identifier
        target_event_unique_id = f"{target_identity}:{EVENT_TYPE_NOTIFICATION}"

        for entity_entry in er.async_entries_for_config_entry(
            entity_registry, entry_id
        ):
            if entity_entry.platform != DOMAIN:
                continue

            target_unique_id: str | None = None
            if (
                entity_entry.domain == Platform.EVENT
                and old_event_unique_id is not None
                and entity_entry.unique_id == old_event_unique_id
            ):
                target_unique_id = target_event_unique_id
            elif entity_entry.domain in (
                Platform.SENSOR,
                Platform.BINARY_SENSOR,
            ):
                detail_prefix = (
                    f"{old_detail_identity}:{entity_entry.domain}:"
                )
                if entity_entry.unique_id.startswith(detail_prefix):
                    detail_key = entity_entry.unique_id[len(detail_prefix) :]
                    target_unique_id = (
                        f"{target_identity}:{entity_entry.domain}:{detail_key}"
                    )

            if target_unique_id is None:
                continue

            entity_updates: dict[str, str] = {}
            if entity_entry.unique_id != target_unique_id:
                entity_updates["new_unique_id"] = target_unique_id
            if entity_entry.device_id != owned_device_id:
                entity_updates["device_id"] = owned_device_id
            if entity_updates:
                entity_registry.async_update_entity(
                    entity_entry.entity_id,
                    **entity_updates,
                )
