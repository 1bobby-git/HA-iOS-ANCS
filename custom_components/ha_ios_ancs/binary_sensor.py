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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .device import device_info
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
        [
            *(
                AncsNotificationBinarySensor(entry, runtime, description)
                for description in BINARY_SENSOR_DESCRIPTIONS
            ),
            AncsBleConnectionBinarySensor(entry, runtime),
        ]
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


class AncsBleConnectionBinarySensor(BinarySensorEntity):
    """Expose the current source device BLE connection state."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "ble_connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    entity_description = BinarySensorEntityDescription(key="ble_connected")

    def __init__(self, entry: ConfigEntry, runtime: AncsRuntime) -> None:
        """Initialize the BLE connection binary sensor."""

        identity = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{identity}:{Platform.BINARY_SENSOR.value}:ble_connected"
        self._attr_device_info = device_info(entry)
        self._runtime = runtime
        self._attr_available = runtime.available is not False

    @property
    def is_on(self) -> bool | None:
        """Return the current BLE connection state, or unknown."""

        return self._runtime.ble_connected

    async def async_added_to_hass(self) -> None:
        """Register for BLE connection updates after attachment."""

        await super().async_added_to_hass()
        self.async_on_remove(
            self._runtime.async_add_ble_connection_listener(
                self._handle_ble_connection
            )
        )
        self.async_on_remove(
            self._runtime.async_add_availability_listener(
                self._handle_availability
            )
        )

    @callback
    def _handle_ble_connection(self, _ble_connected: bool | None) -> None:
        """Write Home Assistant state after a BLE connection transition."""

        self.async_write_ha_state()

    @callback
    def _handle_availability(self, available: bool | None) -> None:
        """Update entity availability when the runtime reports a transition."""

        if available is None:
            return
        self._attr_available = available
        self.async_write_ha_state()
