"""HA runtime regressions for freshness, stale callbacks and retained notifications."""
import json
from types import SimpleNamespace
from unittest.mock import patch

from homeassistant.core import State

from custom_components.ha_ios_ancs.diagnostics import notification_ready
from custom_components.ha_ios_ancs.runtime import AncsMqttRuntime, AncsSourceRuntime
from tests.test_runtime import notification_payload, start_runtime_with_subscribe_patch


def sample(uptime=100, **changes):
    return {"diagnostics_version": 1, "uptime_seconds": uptime,
        "wifi_connected": True, "mqtt_connected": True, "ble_connected": True,
        "ancs_ready": True, "session_authenticated": True, "link_encrypted": True,
        "ancs_service_found": True, "data_source_subscribed": True,
        "notification_source_subscribed": True, "bond_store_known": True,
        "stored_peer_count": 1, **changes}


def message(data, retain=False):
    return SimpleNamespace(payload=json.dumps(data), retain=retain)


def test_retained_state_is_not_live_and_all_ready_stages_are_required(hass, run):
    runtime = AncsMqttRuntime(hass, "ios_ancs")
    runtime._handle_status(message(sample(), retain=True))
    assert not runtime.diagnostics_fresh
    assert runtime.ble_connected is None
    assert notification_ready(runtime.diagnostics, runtime.diagnostics_fresh) is None
    runtime._handle_status(message(sample()))
    assert runtime.diagnostics_fresh and runtime.ble_connected is True
    assert notification_ready(runtime.diagnostics, True) is True
    runtime._handle_status(message(sample(notification_source_subscribed=False)))
    assert notification_ready(runtime.diagnostics, True) is False
    run(runtime.async_stop())


def test_late_expiry_cannot_overwrite_fresh_reconnected_status(hass, run):
    runtime = AncsMqttRuntime(hass, "ios_ancs")
    runtime._handle_status(message(sample()))
    old_generation = runtime._diagnostics_generation
    old_timer = runtime._diagnostics_timer
    runtime._handle_availability(SimpleNamespace(payload="offline"))
    assert old_timer.cancelled()
    runtime._handle_availability(SimpleNamespace(payload="online"))
    runtime._handle_status(message(sample(101)))
    runtime._expire_diagnostics(old_generation)
    assert runtime.diagnostics_fresh
    assert runtime.ble_connected is True
    run(runtime.async_stop())


def test_freshness_expires_without_discarding_last_notification(hass, run):
    runtime = AncsMqttRuntime(hass, "ios_ancs")
    runtime._handle_notification(SimpleNamespace(payload=notification_payload(), retain=False))
    clock = [100.0]
    with patch("custom_components.ha_ios_ancs.runtime.monotonic", side_effect=lambda: clock[0]):
        runtime._handle_status(message(sample()))
        assert runtime.diagnostics_fresh
        clock[0] = 280.0
        assert not runtime.diagnostics_fresh
        runtime._expire_diagnostics(runtime._diagnostics_generation)
        assert runtime.ble_connected is None
        assert runtime.latest_notification["relay_id"] == "relay-1"
    run(runtime.async_stop())


def test_retained_notification_never_replays_as_new_or_replaces_live(hass, run):
    runtime, subscriptions, _ = run(start_runtime_with_subscribe_patch(hass))
    received = []
    runtime.async_add_notification_listener(received.append)
    callback = subscriptions[0][1]
    callback(SimpleNamespace(payload=notification_payload(relay_id="retained"), retain=True))
    assert received == []
    assert runtime.latest_notification["relay_id"] == "retained"
    callback(SimpleNamespace(payload=notification_payload(relay_id="retained"), retain=False))
    assert received == []
    callback(SimpleNamespace(payload=notification_payload(relay_id="new"), retain=False))
    assert [item["relay_id"] for item in received] == ["new"]
    callback(SimpleNamespace(payload=notification_payload(relay_id="older-retained"), retain=True))
    assert runtime.latest_notification["relay_id"] == "new"
    assert len(received) == 1
    run(runtime.async_stop())


def source_event(data):
    return SimpleNamespace(data={"new_state": State("sensor.status", "ready", data)})


def test_source_cached_same_uptime_does_not_extend_freshness(hass, run):
    runtime = AncsSourceRuntime(hass, "fixture-source", "fixture-device")
    clock = [100.0]
    with patch("custom_components.ha_ios_ancs.runtime.monotonic", side_effect=lambda: clock[0]):
        runtime._handle_status_state_change(source_event(sample(10)))
        assert not runtime.diagnostics_fresh
        runtime._handle_status_state_change(source_event(sample(11)))
        assert runtime.diagnostics_fresh
        generation = runtime._diagnostics_generation
        timer = runtime._diagnostics_timer
        clock[0] = 200.0
        runtime._handle_status_state_change(source_event(sample(11, data_source_subscribed=False)))
        assert runtime._diagnostics_generation == generation
        assert runtime._diagnostics_timer is timer
        assert notification_ready(runtime.diagnostics, True) is False
        clock[0] = 280.0
        assert not runtime.diagnostics_fresh
        runtime._expire_diagnostics(generation)
        assert runtime.ble_connected is None
    run(runtime.async_stop())


def test_source_uptime_reset_needs_an_advancing_new_sample(hass, run):
    runtime = AncsSourceRuntime(hass, "fixture-source", "fixture-device")
    runtime._handle_status_state_change(source_event(sample(100)))
    runtime._handle_status_state_change(source_event(sample(101)))
    assert runtime.diagnostics_fresh
    runtime._handle_status_state_change(source_event(sample(1)))
    assert not runtime.diagnostics_fresh
    runtime._handle_status_state_change(source_event(sample(2)))
    assert runtime.diagnostics_fresh
    run(runtime.async_stop())


def test_old_firmware_link_compatibility_does_not_invent_ancs_ready(hass, run):
    runtime = AncsMqttRuntime(hass, "ios_ancs")
    runtime._handle_status(message({"ble_connected": True, "ble_bonded": True}))
    assert runtime.ble_connected is True
    assert notification_ready(runtime.diagnostics, runtime.diagnostics_fresh) is None
    run(runtime.async_stop())
