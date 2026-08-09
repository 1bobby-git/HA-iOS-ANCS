from __future__ import annotations

import json

import pytest

from custom_components.ha_ios_ancs.const import HA_ECHO_APP_ID
from custom_components.ha_ios_ancs.notification import (
    RelayIdWindow,
    parse_notification,
    parse_notification_data,
)


def payload(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "relay_id": "relay-1",
        "complete": True,
        "app_id": "com.example.Messages",
        "event": "added",
        "title": "Doorbell",
    }
    data.update(overrides)
    return data


def encode(data: object) -> str:
    return json.dumps(data)


def test_parse_valid_string_payload_preserves_fields_and_copies() -> None:
    seen = RelayIdWindow()
    original = payload(extra={"nested": True})

    parsed = parse_notification(encode(original), seen)

    assert parsed == original
    assert parsed is not original
    assert parsed is not None
    parsed["title"] = "Changed"
    assert original["title"] == "Doorbell"
    assert "relay-1" in seen


def test_parse_valid_bytes_payload() -> None:
    seen = RelayIdWindow()

    parsed = parse_notification(encode(payload()).encode("utf-8"), seen)

    assert parsed == payload()


def test_parse_notification_data_accepts_mapping_and_copies() -> None:
    seen = RelayIdWindow()
    original = payload(extra={"nested": True})

    parsed = parse_notification_data(original, seen)

    assert parsed == original
    assert parsed is not original
    assert "relay-1" in seen


def test_parse_notification_data_rejected_value_does_not_consume_id() -> None:
    seen = RelayIdWindow()

    assert parse_notification_data(payload(complete=False), seen) is None
    assert parse_notification_data(payload(), seen) is not None


@pytest.mark.parametrize(
    "raw",
    [
        b'{"relay_id": "\xff"}',
        "{not json",
    ],
)
def test_parse_malformed_utf8_or_json_returns_none(raw: str | bytes) -> None:
    seen = RelayIdWindow()

    assert parse_notification(raw, seen) is None


@pytest.mark.parametrize("data", [[], "scalar", 3, None])
def test_parse_rejects_non_object_json(data: object) -> None:
    seen = RelayIdWindow()

    assert parse_notification(encode(data), seen) is None


@pytest.mark.parametrize(
    "relay_id",
    [
        None,
        "",
        "   ",
        7,
    ],
)
def test_parse_requires_non_empty_string_relay_id(relay_id: object) -> None:
    seen = RelayIdWindow()
    data = payload()
    if relay_id is None:
        data.pop("relay_id")
    else:
        data["relay_id"] = relay_id

    assert parse_notification(encode(data), seen) is None


@pytest.mark.parametrize("complete", [1, "true", [], False, None])
def test_parse_accepts_only_literal_true_complete(complete: object) -> None:
    seen = RelayIdWindow()

    assert parse_notification(encode(payload(complete=complete)), seen) is None


def test_parse_rejects_pre_existing_true() -> None:
    seen = RelayIdWindow()

    assert parse_notification(encode(payload(pre_existing=True)), seen) is None


def test_parse_rejects_removed_event() -> None:
    seen = RelayIdWindow()

    assert parse_notification(encode(payload(event="removed")), seen) is None


def test_parse_rejects_home_assistant_echo_app_id() -> None:
    seen = RelayIdWindow()

    assert parse_notification(encode(payload(app_id=HA_ECHO_APP_ID)), seen) is None


def test_parse_rejects_duplicate_accepted_relay_id() -> None:
    seen = RelayIdWindow()

    assert parse_notification(encode(payload()), seen) is not None
    assert parse_notification(encode(payload()), seen) is None


def test_parse_rejected_relay_id_does_not_consume_dedupe() -> None:
    seen = RelayIdWindow()

    assert parse_notification(encode(payload(complete=False)), seen) is None
    assert parse_notification(encode(payload()), seen) is not None


def test_relay_id_window_evicts_oldest_when_limit_exceeded() -> None:
    window = RelayIdWindow(limit=2)

    window.add("one")
    window.add("two")
    window.add("three")

    assert "one" not in window
    assert "two" in window
    assert "three" in window


def test_relay_id_window_does_not_queue_duplicates() -> None:
    window = RelayIdWindow(limit=2)

    window.add("one")
    window.add("one")
    window.add("two")
    window.add("three")

    assert "one" not in window
    assert "two" in window
    assert "three" in window


@pytest.mark.parametrize("limit", [0, -1])
def test_relay_id_window_requires_positive_limit(limit: int) -> None:
    with pytest.raises(ValueError):
        RelayIdWindow(limit=limit)
