import io
import json
from pathlib import Path

import pytest

from tools.verify_capture import (
    CaptureFormatError,
    CaptureNotReadyError,
    CaptureTimeoutError,
    CaptureValidationError,
    consume_log_stream,
    validate_notification,
)


def notification(**overrides):
    payload = {
        "schema_version": 1,
        "target": "esp32c6",
        "device_name": "IOS-ANCS-C6-AB12",
        "session_id": 1,
        "event": "added",
        "event_id": 0,
        "uid": 10,
        "event_flags": 0,
        "category_id": 4,
        "category": "social",
        "category_count": 1,
        "app_id": "com.example.test",
        "title": "테스트",
        "subtitle": "",
        "message": "본문",
        "message_size": "6",
        "date": "20260728T164500",
        "complete": True,
        "truncated": {
            "app_id": False,
            "title": False,
            "subtitle": False,
            "message": False,
        },
        "error": None,
        "received_at_ms": 123,
    }
    payload.update(overrides)
    return payload


def state_line():
    return (
        'ANCS_STATE_JSON '
        '{"target":"esp32c6","state":"ancs_ready","session_id":1,'
        '"bonded":true,"data_source_subscribed":true,'
        '"notification_source_subscribed":true}\n'
    )


def notification_line(payload):
    return "ANCS_NOTIFICATION_JSON " + json.dumps(payload, ensure_ascii=False) + "\n"


def test_pass_stream_writes_raw_and_capture_files(tmp_path: Path):
    raw_path = tmp_path / "ancs-capture.jsonl"
    capture_path = tmp_path / "ancs-capture.capture.json"
    lines = [
        "I (10) ANCS: boot\n",
        state_line(),
        notification_line(notification()),
    ]

    result = consume_log_stream(
        lines,
        output_path=raw_path,
        capture_path=capture_path,
        allow_empty_content=False,
    )

    assert result["app_id"] == "com.example.test"
    assert "테스트" in raw_path.read_text(encoding="utf-8")
    assert json.loads(capture_path.read_text(encoding="utf-8"))["message"] == "본문"


def test_empty_title_subtitle_and_message_fails_by_default():
    with pytest.raises(CaptureValidationError, match="content"):
        validate_notification(notification(title="", subtitle="", message=""))


def test_empty_content_can_be_allowed_explicitly():
    errors = validate_notification(
        notification(title="", subtitle="", message=""),
        allow_empty_content=True,
    )
    assert errors == []


def test_broken_json_is_reported():
    lines = [state_line(), 'ANCS_NOTIFICATION_JSON {"target":\n']
    with pytest.raises(CaptureFormatError, match="JSON"):
        consume_log_stream(lines, output_path=io.StringIO(), capture_path=None)


def test_wrong_target_is_rejected():
    with pytest.raises(CaptureValidationError, match="target"):
        validate_notification(notification(target="esp32c3"))


def test_notification_before_ready_does_not_pass():
    lines = [notification_line(notification())]
    with pytest.raises(CaptureNotReadyError, match="ancs_ready"):
        consume_log_stream(lines, output_path=io.StringIO(), capture_path=None)


def test_ready_without_notification_reports_timeout():
    with pytest.raises(CaptureTimeoutError, match="qualifying"):
        consume_log_stream(
            [state_line()],
            output_path=io.StringIO(),
            capture_path=None,
        )
