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
        "alias: Relay iOS ANCS notifications to your mobile app",
        "id: ios_ancs_relay_to_mobile_app",
        "- platform: state",
        "entity_id: sensor.replace_with_your_last_notification_entity",
        "trigger.from_state.state != trigger.to_state.state",
        "trigger.from_state.state != 'unavailable'",
        "not in ['unknown', 'unavailable']",
        "get('complete', false) | bool(false)",
        "get('pre_existing', true) | bool(true)",
        "service: notify.replace_with_your_mobile_app_service",
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
    assert 'title: "[iOS ANCS] ' in title_body
    assert title_body.index("get('title')") < title_body.index("get('app_id')")

    message_body = _between(automation, "      message:", "\nmode:")
    assert message_body.index("get('message')") < message_body.index("get('subtitle')")
    assert message_body.index("get('subtitle')") < message_body.index("get('app_id')")
    assert message_body.index("get('app_id')") < message_body.index("get('category')")
    assert "~ ' (' ~" in message_body

    forbidden_fragments = (
        "ios_ancs_relay_to_example_phone",
        "notify.mobile_app_" + "1bobby",
        "sensor.ios_ancs_c6_ab12_ios_ancs_c6_ab12_last_notification",
        "rest_command",
        "webhook",
        "http://",
        "https://",
    )
    for fragment in forbidden_fragments:
        assert fragment not in automation.lower()


def test_parking_arrival_tts_requires_exact_target_app():
    automation_path = (
        Path(__file__).resolve().parents[2]
        / "homeassistant"
        / "automation_ios_ancs_parking_arrival_tts.yaml"
    )
    automation = automation_path.read_text(encoding="utf-8")

    required_fragments = (
        "trigger: event.received",
        "event.replace_with_your_ios_ancs_notification_event",
        "target_app_id: \"com.replace_with_your_apartment_app\"",
        "target_app_name: \"교체할 아파트 앱 이름\"",
        "notification_app_id == target_app_id",
        "notification_app_name == target_app_name",
        "notification.get('event') == 'added'",
        "notification.get('complete', false)",
        "notification.get('pre_existing', true)",
        "regex_findall",
        "차량이\\s*입차",
        "action: tts.speak",
        "tts.replace_with_your_korean_tts",
        "media_player.replace_with_your_speaker",
        "{{ parking_announcement | trim }}",
    )
    for fragment in required_fragments:
        assert fragment in automation

    assert " or notification_app_name == target_app_name" not in automation
    assert " or notification_app_id == target_app_id" not in automation
