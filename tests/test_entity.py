from __future__ import annotations

from custom_components.ha_ios_ancs.entity import (
    MAX_STATE_TEXT_LENGTH,
    as_boolean,
    as_integer,
    as_text,
    nested_value,
    preview_text,
    raw_payload_attributes,
)


def test_extractors_reject_bool_as_integer_and_truthy_non_booleans() -> None:
    payload = {
        "count": 3,
        "wrong_count": True,
        "flag": False,
        "wrong_flag": 1,
    }

    assert as_integer(nested_value(payload, ("count",))) == 3
    assert as_integer(nested_value(payload, ("wrong_count",))) is None
    assert as_boolean(nested_value(payload, ("flag",))) is False
    assert as_boolean(nested_value(payload, ("wrong_flag",))) is None


def test_nested_and_text_helpers_preserve_source_payload() -> None:
    long_message = "x" * 4096
    payload = {
        "message": long_message,
        "truncated": {"message": True},
    }

    assert nested_value(payload, ("truncated", "message")) is True
    assert nested_value(payload, ("error", "code")) is None
    assert as_text(payload["message"]) == long_message
    assert preview_text(long_message) == long_message[:MAX_STATE_TEXT_LENGTH]

    attributes = raw_payload_attributes(payload)
    attributes["truncated"]["message"] = False
    assert payload["truncated"]["message"] is True
