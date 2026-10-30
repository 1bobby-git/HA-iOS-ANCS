"""Additive diagnostic entities; notification entities and IDs are unchanged."""
from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.entity import Entity
from .device import device_info
from .diagnostics import USER_ACTIONS, connection_state

# Values that change with every 60-second status sample or notification. They
# stay in the live state. Excluding them lets the recorder reuse one attribute
# row instead of storing a new one per sample (each sample still adds a small
# state row); the firmware's MQTT status entity records their history.
VOLATILE_DIAGNOSTIC_ATTRIBUTES = frozenset({
    "uptime_seconds", "last_notification_uptime_ms", "accepted", "published_ack",
    "dropped_offline", "dropped_enqueue", "dropped_policy",
    "wifi_retry_in_ms", "mqtt_retry_in_ms", "enrollment_remaining_seconds",
})


class AncsConnectionEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _unrecorded_attributes = VOLATILE_DIAGNOSTIC_ATTRIBUTES

    def __init__(self, entry, runtime, platform: str, key: str) -> None:
        self._runtime = runtime
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}:{platform}:{key}"
        self._attr_device_info = device_info(entry)

    @property
    def extra_state_attributes(self):
        data = getattr(self._runtime, "diagnostics", {})
        fresh = getattr(self._runtime, "diagnostics_fresh", False)
        state = connection_state(data, fresh, self._runtime.available)
        return {**data, "status_fresh": fresh, "connection_state": state,
                "required_user_action": USER_ACTIONS.get(state, "")}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._runtime.async_add_diagnostics_listener(self._handle_status))
        self.async_on_remove(self._runtime.async_add_availability_listener(self._handle_status))

    @callback
    def _handle_status(self, *_args) -> None:
        self.async_write_ha_state()
