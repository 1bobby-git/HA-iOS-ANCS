"""Binary sensor platform for iOS ANCS notification flags."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import AncsNotificationEntity, as_boolean, nested_value
from .runtime import AncsRuntime


@dataclass(frozen=True, kw_only=True)
class AncsBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describe a notification boolean and its source path."""

    path: tuple[str, ...]
    non_null_presence: bool = False


def _description(
    key: str,
    path: tuple[str, ...],
    *,
    non_null_presence: bool = False,
    diagnostic: bool = False,
    device_class: BinarySensorDeviceClass | None = None,
) -> AncsBinarySensorEntityDescription:
    """Build a translated notification binary-sensor description."""

    return AncsBinarySensorEntityDescription(
        key=key,
        translation_key=key,
        path=path,
        non_null_presence=non_null_presence,
        entity_category=EntityCategory.DIAGNOSTIC if diagnostic else None,
        device_class=device_class,
    )


_PROBLEM = BinarySensorDeviceClass.PROBLEM

BINARY_SENSOR_DESCRIPTIONS: tuple[AncsBinarySensorEntityDescription, ...] = (
    _description("complete", ("complete",), diagnostic=True),
    _description("silent", ("silent",)),
    _description("important", ("important",)),
    _description("pre_existing", ("pre_existing",), diagnostic=True),
    _description(
        "positive_action_available",
        ("positive_action_available",),
    ),
    _description(
        "negative_action_available",
        ("negative_action_available",),
    ),
    _description(
        "app_id_truncated",
        ("truncated", "app_id"),
        diagnostic=True,
        device_class=_PROBLEM,
    ),
    _description(
        "app_name_truncated",
        ("truncated", "app_name"),
        diagnostic=True,
        device_class=_PROBLEM,
    ),
    _description(
        "title_truncated",
        ("truncated", "title"),
        diagnostic=True,
        device_class=_PROBLEM,
    ),
    _description(
        "subtitle_truncated",
        ("truncated", "subtitle"),
        diagnostic=True,
        device_class=_PROBLEM,
    ),
    _description(
        "message_truncated",
        ("truncated", "message"),
        diagnostic=True,
        device_class=_PROBLEM,
    ),
    _description(
        "has_error",
        ("error",),
        non_null_presence=True,
        diagnostic=True,
        device_class=_PROBLEM,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up all purpose-specific notification binary sensors."""

    runtime: AncsRuntime = entry.runtime_data
    async_add_entities(
        AncsNotificationBinarySensor(entry, runtime, description)
        for description in BINARY_SENSOR_DESCRIPTIONS
    )


class AncsNotificationBinarySensor(AncsNotificationEntity, BinarySensorEntity):
    """Expose one strict boolean from the latest ANCS notification."""

    entity_description: AncsBinarySensorEntityDescription

    def __init__(
        self,
        entry: ConfigEntry,
        runtime: AncsRuntime,
        description: AncsBinarySensorEntityDescription,
    ) -> None:
        """Initialize a notification flag binary sensor."""

        self.entity_description = description
        super().__init__(entry, runtime, Platform.BINARY_SENSOR, description.key)

    @property
    def is_on(self) -> bool | None:
        """Return a literal boolean or explicit non-null field presence."""

        if self._payload is None:
            return None
        description = self.entity_description
        value = nested_value(self._payload, description.path)
        if description.non_null_presence:
            return (
                None
                if description.path[0] not in self._payload
                else value is not None
            )
        return as_boolean(value)
