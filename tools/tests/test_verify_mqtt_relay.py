import json
from pathlib import Path

import pytest

from tools.verify_mqtt_relay import MqttRelayValidationError, verify_broker_events


BASE_TOPIC = "ios-ancs/c6-ab12"
DISCOVERY_TOPIC = "homeassistant/sensor/ios_ancs_c6_ab12/last_notification/config"


def event(topic, payload, *, retain=False, qos=1):
    if isinstance(payload, dict):
        payload = json.dumps(payload, ensure_ascii=False)
    return {"topic": topic, "payload": payload, "retain": retain, "qos": qos}


def notification(**overrides):
    payload = {
        "schema_version": 1,
        "target": "esp32c6",
        "source": "esp32c6_ancs",
        "relay_id": "boot1-1-42-aabbcc",
        "device_name": "IOS-ANCS-C6-AB12",
        "session_id": 1,
        "event": "added",
        "event_id": 0,
        "uid": 42,
        "app_id": "com.example.chat",
        "title": "Private title",
        "subtitle": "",
        "message": "Private message",
        "complete": True,
        "pre_existing": False,
        "published_at_ms": 123456,
    }
    payload.update(overrides)
    return payload


def valid_events():
    return [
        event(f"{BASE_TOPIC}/availability", "online", retain=True),
        event(
            DISCOVERY_TOPIC,
            {
                "state_topic": f"{BASE_TOPIC}/notification",
                "value_template": "{{ value_json.relay_id }}",
                "json_attributes_topic": f"{BASE_TOPIC}/notification",
            },
            retain=True,
        ),
        event(f"{BASE_TOPIC}/notification", notification(), retain=False),
        event(f"{BASE_TOPIC}/state", {"notifications_published": 1}, retain=True),
    ]


def test_verifier_accepts_required_mqtt_capture_and_redacts_report():
    result = verify_broker_events(valid_events())

    assert result.base_topic == BASE_TOPIC
    assert result.notification_count == 1
    assert result.relay_ids == ["boot1-1-42-aabbcc"]
    assert result.echo_blocked is True
    assert result.offline_drop_verified is None
    assert "Private title" not in result.report
    assert "Private message" not in result.report
    assert "com.example.chat" in result.report


def test_verifier_requires_retained_availability_and_discovery():
    missing_discovery = valid_events()
    missing_discovery.pop(1)

    with pytest.raises(MqttRelayValidationError, match="discovery"):
        verify_broker_events(missing_discovery)

    bad_availability = valid_events()
    bad_availability[0]["retain"] = False
    with pytest.raises(MqttRelayValidationError, match="availability"):
        verify_broker_events(bad_availability)


def test_verifier_rejects_home_assistant_publish_or_second_relay_id():
    echo_publish = valid_events() + [
        event(
            f"{BASE_TOPIC}/notification",
            notification(
                relay_id="boot1-1-43-echo",
                app_id="io.robbie.HomeAssistant",
                title="[C6\u2192HA] Private title",
            ),
        )
    ]

    with pytest.raises(MqttRelayValidationError, match="Home Assistant"):
        verify_broker_events(echo_publish)

    duplicate_relay = valid_events() + [
        event(f"{BASE_TOPIC}/notification", notification(message="duplicate delivery"))
    ]
    with pytest.raises(MqttRelayValidationError, match="second notification"):
        verify_broker_events(duplicate_relay)


def test_verifier_rejects_unmarked_home_assistant_notification():
    events = valid_events()
    payload = notification(
        app_id="io.robbie.HomeAssistant",
        title="unmarked Home Assistant notification",
    )
    events[2] = event(f"{BASE_TOPIC}/notification", payload, retain=False)

    with pytest.raises(MqttRelayValidationError, match="Home Assistant"):
        verify_broker_events(events)


def test_verifier_allows_relay_marker_title_from_another_app():
    events = valid_events()
    payload = notification(
        app_id="com.example.other",
        title="[C6\u2192HA] unrelated",
    )
    events[2] = event(f"{BASE_TOPIC}/notification", payload, retain=False)

    result = verify_broker_events(events)

    assert result.notification_count == 1


def test_verifier_can_prove_offline_window_absent_and_no_replay():
    events = valid_events() + [
        event(f"{BASE_TOPIC}/availability", "offline", retain=True),
        event(f"{BASE_TOPIC}/availability", "online", retain=True),
        event(f"{BASE_TOPIC}/state", {"dropped_offline": 1, "notifications_published": 1}, retain=True),
    ]

    result = verify_broker_events(events, expect_offline_drop=True)

    assert result.offline_drop_verified is True
    assert result.notification_count == 1


def test_cli_reads_jsonl_and_writes_redacted_report(tmp_path: Path):
    capture = tmp_path / "mqtt-events.jsonl"
    report = tmp_path / "mqtt-report.md"
    capture.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in valid_events()) + "\n",
        encoding="utf-8",
    )

    from tools.verify_mqtt_relay import main

    assert main([str(capture), "--report", str(report)]) == 0
    text = report.read_text(encoding="utf-8")
    assert "Private message" not in text
    assert "relay_id" in text
