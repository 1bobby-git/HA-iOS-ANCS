"""Sensor platform for iOS ANCS notification details."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, Platform, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import (
    MAX_STATE_TEXT_LENGTH,
    AncsNotificationEntity,
    as_integer,
    as_text,
    nested_value,
    preview_text,
    raw_payload_attributes,
)
from .runtime import AncsRuntime

EVENT_OPTIONS = ["added", "modified", "removed"]
CATEGORY_OPTIONS = [
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
]


class SensorValueKind(StrEnum):
    """Supported strict conversions from an ANCS JSON payload."""

    TEXT = "text"
    INTEGER = "integer"
    DECIMAL_TEXT = "decimal_text"
    RAW = "raw"


@dataclass(frozen=True, kw_only=True)
class AncsSensorEntityDescription(SensorEntityDescription):
    """Describe a notification sensor and its source value."""

    path: tuple[str, ...]
    kind: SensorValueKind
    fallback_path: tuple[str, ...] | None = None
    preserve_full_text: bool = False


def _description(
    key: str,
    path: tuple[str, ...],
    kind: SensorValueKind,
    *,
    fallback_path: tuple[str, ...] | None = None,
    preserve_full_text: bool = False,
    entity_category: EntityCategory | None = None,
    device_class: SensorDeviceClass | None = None,
    options: list[str] | None = None,
    native_unit_of_measurement: str | None = None,
) -> AncsSensorEntityDescription:
    """Build a translated notification sensor description."""

    return AncsSensorEntityDescription(
        key=key,
        translation_key=key,
        path=path,
        kind=kind,
        fallback_path=fallback_path,
        preserve_full_text=preserve_full_text,
        entity_category=entity_category,
        device_class=device_class,
        options=options,
        native_unit_of_measurement=native_unit_of_measurement,
    )


_DIAGNOSTIC = EntityCategory.DIAGNOSTIC

SENSOR_DESCRIPTIONS: tuple[AncsSensorEntityDescription, ...] = (
    _description(
        "app_name",
        ("app_name",),
        SensorValueKind.TEXT,
        fallback_path=("app_id",),
        preserve_full_text=True,
    ),
    _description(
        "app_id",
        ("app_id",),
        SensorValueKind.TEXT,
        preserve_full_text=True,
        entity_category=_DIAGNOSTIC,
    ),
    _description(
        "title", ("title",), SensorValueKind.TEXT, preserve_full_text=True
    ),
    _description(
        "subtitle", ("subtitle",), SensorValueKind.TEXT, preserve_full_text=True
    ),
    _description(
        "message", ("message",), SensorValueKind.TEXT, preserve_full_text=True
    ),
    _description(
        "event",
        ("event",),
        SensorValueKind.TEXT,
        device_class=SensorDeviceClass.ENUM,
        options=EVENT_OPTIONS,
    ),
    _description(
        "category",
        ("category",),
        SensorValueKind.TEXT,
        device_class=SensorDeviceClass.ENUM,
        options=CATEGORY_OPTIONS,
    ),
    _description("date", ("date",), SensorValueKind.TEXT),
    _description("uid", ("uid",), SensorValueKind.INTEGER, entity_category=_DIAGNOSTIC),
    _description(
        "session_id",
        ("session_id",),
        SensorValueKind.INTEGER,
        entity_category=_DIAGNOSTIC,
    ),
    _description(
        "event_id",
        ("event_id",),
        SensorValueKind.INTEGER,
        entity_category=_DIAGNOSTIC,
    ),
    _description(
        "event_flags",
        ("event_flags",),
        SensorValueKind.INTEGER,
        entity_category=_DIAGNOSTIC,
    ),
    _description(
        "category_id",
        ("category_id",),
        SensorValueKind.INTEGER,
        entity_category=_DIAGNOSTIC,
    ),
    _description("category_count", ("category_count",), SensorValueKind.INTEGER),
    _description(
        "message_size",
        ("message_size",),
        SensorValueKind.DECIMAL_TEXT,
        entity_category=_DIAGNOSTIC,
    ),
    _description(
        "schema_version",
        ("schema_version",),
        SensorValueKind.INTEGER,
        entity_category=_DIAGNOSTIC,
    ),
    _description(
        "relay_id",
        ("relay_id",),
        SensorValueKind.TEXT,
        entity_category=_DIAGNOSTIC,
    ),
    _description(
        "target",
        ("target",),
        SensorValueKind.TEXT,
        entity_category=_DIAGNOSTIC,
    ),
    _description(
        "source",
        ("source",),
        SensorValueKind.TEXT,
        entity_category=_DIAGNOSTIC,
    ),
    _description(
        "device_name",
        ("device_name",),
        SensorValueKind.TEXT,
        preserve_full_text=True,
        entity_category=_DIAGNOSTIC,
    ),
    _description(
        "received_at_ms",
        ("received_at_ms",),
        SensorValueKind.INTEGER,
        entity_category=_DIAGNOSTIC,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
    ),
    _description(
        "published_at_ms",
        ("published_at_ms",),
        SensorValueKind.INTEGER,
        entity_category=_DIAGNOSTIC,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
    ),
    _description(
        "error_code",
        ("error", "code"),
        SensorValueKind.INTEGER,
        entity_category=_DIAGNOSTIC,
    ),
    _description(
        "error_name",
        ("error", "name"),
        SensorValueKind.TEXT,
        entity_category=_DIAGNOSTIC,
    ),
    _description(
        "raw_notification",
        ("relay_id",),
        SensorValueKind.RAW,
        entity_category=_DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up all purpose-specific notification sensors."""

    runtime: AncsRuntime = entry.runtime_data
    async_add_entities(
        AncsNotificationSensor(entry, runtime, description)
        for description in SENSOR_DESCRIPTIONS
    )


class AncsNotificationSensor(AncsNotificationEntity, SensorEntity):
    """Expose one typed value from the latest ANCS notification."""

    entity_description: AncsSensorEntityDescription

    def __init__(
        self,
        entry: ConfigEntry,
        runtime: AncsRuntime,
        description: AncsSensorEntityDescription,
    ) -> None:
        """Initialize a notification detail sensor."""

        self.entity_description = description
        super().__init__(entry, runtime, Platform.SENSOR, description.key)

    def _text_value(self) -> str | None:
        """Resolve a text value and its optional fallback."""

        if self._payload is None:
            return None
        description = self.entity_description
        value = as_text(nested_value(self._payload, description.path))
        if (value is None or value == "") and description.fallback_path is not None:
            value = as_text(nested_value(self._payload, description.fallback_path))
        return value

    @property
    def native_value(self) -> str | int | None:
        """Return the strict, state-safe value for this field."""

        if self._payload is None:
            return None

        description = self.entity_description
        if description.kind is SensorValueKind.TEXT:
            value = self._text_value()
            if value is None:
                return None
            if (
                description.options is not None
                and value not in description.options
            ):
                return None
            return preview_text(value)
        if description.kind is SensorValueKind.INTEGER:
            return as_integer(nested_value(self._payload, description.path))
        if description.kind is SensorValueKind.DECIMAL_TEXT:
            value = as_text(nested_value(self._payload, description.path))
            if value is None:
                return None
            digits = value[1:] if value.startswith("-") else value
            return int(value) if digits and digits.isdecimal() else None

        value = as_text(nested_value(self._payload, description.path))
        return None if value is None else preview_text(value)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return lossless raw or long-text attributes when needed."""

        if self._payload is None:
            return None
        description = self.entity_description
        if description.kind is SensorValueKind.RAW:
            return raw_payload_attributes(self._payload)
        if not description.preserve_full_text:
            return None

        value = self._text_value()
        if value is None or len(value) <= MAX_STATE_TEXT_LENGTH:
            return None
        return {"full_value": value}
