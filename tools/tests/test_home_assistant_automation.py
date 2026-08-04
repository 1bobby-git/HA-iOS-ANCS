from pathlib import Path


AUTOMATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "homeassistant"
    / "automation_ios_ancs_c6_relay.yaml"
)


def _between(source, start_marker, end_marker):
    start = source.index(start_marker)
    end = source.index(end_marker, start + len(start_marker))
    return source[start:end]


def test_ios_ancs_c6_relay_has_required_safe_notification_contract():
    """The C6 relay only forwards complete, newly received notifications."""
    automation = AUTOMATION_PATH.read_text(encoding="utf-8")

    required_fragments = (
        "id: ios_ancs_relay_to_example_phone",
        "entity_id: sensor.ios_ancs_c6_ab12_ios_ancs_c6_ab12_last_notification",
        "trigger.from_state.state != trigger.to_state.state",
        "trigger.from_state.state != 'unavailable'",
        "not in ['unknown', 'unavailable']",
        "get('complete', false) | bool(false)",
        "get('pre_existing', true) | bool(true)",
        "service: notify.mobile_app_example_phone",
        "message: >-",
        "trigger.to_state.attributes.get('message')",
        "or trigger.to_state.attributes.get('subtitle')",
        "or trigger.to_state.attributes.get('app_id')",
        "mode: queued",
        "max: 10",
    )
    for fragment in required_fragments:
        assert fragment in automation

    title_body = _between(automation, "      title:", "      message:")
    assert 'title: "[C6\\u2192HA] ' in title_body
    assert title_body.index("get('title')") < title_body.index("get('app_id')")

    message_body = _between(automation, "      message:", "\nmode:")
    assert message_body.index("get('message')") < message_body.index("get('subtitle')")
    assert message_body.index("get('subtitle')") < message_body.index("get('app_id')")
    assert message_body.index("get('app_id')") < message_body.index("get('category')")
    assert "~ ' (' ~" in message_body

    forbidden_fragments = ("rest_command", "webhook", "http://", "https://")
    for fragment in forbidden_fragments:
        assert fragment not in automation.lower()
