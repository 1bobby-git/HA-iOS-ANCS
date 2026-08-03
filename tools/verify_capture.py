#!/usr/bin/env python3

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Iterable, TextIO


STATE_PREFIX = "ANCS_STATE_JSON "
NOTIFICATION_PREFIX = "ANCS_NOTIFICATION_JSON "


class CaptureError(RuntimeError):
    pass


class CaptureFormatError(CaptureError):
    pass


class CaptureValidationError(CaptureError):
    pass


class CaptureNotReadyError(CaptureError):
    pass


class CaptureTimeoutError(CaptureError):
    pass


def validate_notification(payload, allow_empty_content=False, target="esp32c6"):
    errors = []
    if not isinstance(payload, dict):
        raise CaptureValidationError("notification must be a JSON object")
    if payload.get("target") != target:
        errors.append(f"target must be {target}")
    if payload.get("event") not in {"added", "modified"}:
        errors.append("event must be added or modified")
    if not isinstance(payload.get("session_id"), int) or payload["session_id"] < 1:
        errors.append("session_id must be an integer >= 1")
    if not isinstance(payload.get("uid"), int) or payload["uid"] < 0:
        errors.append("uid must be an integer >= 0")
    if not isinstance(payload.get("app_id"), str) or not payload["app_id"]:
        errors.append("app_id must be a non-empty string")
    if payload.get("complete") is not True:
        errors.append("complete must be true")
    for field in ("title", "subtitle", "message"):
        if not isinstance(payload.get(field), str):
            errors.append(f"{field} must be a string")
    if not allow_empty_content and all(
        payload.get(field, "") == "" for field in ("title", "subtitle", "message")
    ):
        errors.append("at least one content field must be non-empty")
    if errors:
        raise CaptureValidationError("; ".join(errors))
    return []


def _open_output(output_path):
    if hasattr(output_path, "write"):
        return output_path, False
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("wb"), True


def _write_raw(stream, line):
    if isinstance(line, bytes):
        raw = line
        text = line.decode("utf-8", errors="replace")
    else:
        text = str(line)
        raw = text.encode("utf-8")
    try:
        stream.write(raw)
    except TypeError:
        stream.write(text)
    if hasattr(stream, "flush"):
        stream.flush()
    return text


def _decode_prefixed_json(line, prefix):
    payload_text = line[len(prefix) :].strip()
    try:
        return json.loads(payload_text)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CaptureFormatError(f"invalid JSON after {prefix.strip()}: {exc}") from exc


def _write_capture(capture_path, payload):
    if capture_path is None:
        return
    path = Path(capture_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def consume_log_stream(
    lines,
    *,
    output_path,
    capture_path,
    allow_empty_content=False,
    target="esp32c6",
):
    output, close_output = _open_output(output_path)
    ready = False
    try:
        for raw_line in lines:
            line = _write_raw(output, raw_line)
            if line.startswith(STATE_PREFIX):
                state = _decode_prefixed_json(line, STATE_PREFIX)
                if (
                    state.get("target") == target
                    and state.get("state") == "ancs_ready"
                    and state.get("bonded") is True
                    and state.get("data_source_subscribed") is True
                    and state.get("notification_source_subscribed") is True
                ):
                    ready = True
                continue
            if not line.startswith(NOTIFICATION_PREFIX):
                continue
            notification = _decode_prefixed_json(line, NOTIFICATION_PREFIX)
            if not ready:
                continue
            validate_notification(
                notification,
                allow_empty_content=allow_empty_content,
                target=target,
            )
            _write_capture(capture_path, notification)
            return notification
    finally:
        if hasattr(output, "flush"):
            output.flush()
        if close_output:
            output.close()

    if not ready:
        raise CaptureNotReadyError("state ancs_ready was not observed")
    raise CaptureTimeoutError("no qualifying ANCS notification was observed")


def _default_capture_path(output_path):
    output = Path(output_path)
    if output.suffix:
        return output.with_suffix(".capture.json")
    return output.with_name(output.name + ".capture.json")


def _open_serial_connection(serial_module, *, port, baud, timeout):
    connection = serial_module.Serial()
    connection.port = port
    connection.baudrate = baud
    connection.timeout = timeout
    connection.dtr = False
    connection.rts = False
    connection.open()
    return connection


def _serial_lines(port, baud, timeout_seconds):
    import serial

    deadline = time.monotonic() + timeout_seconds
    with _open_serial_connection(
        serial,
        port=port,
        baud=baud,
        timeout=0.25,
    ) as connection:
        while time.monotonic() < deadline:
            line = connection.readline()
            if line:
                sys.stdout.buffer.write(line)
                sys.stdout.buffer.flush()
                yield line


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Capture and validate ESP32 ANCS serial JSON."
    )
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--target", default="esp32c6")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/ancs-capture.jsonl"),
    )
    parser.add_argument("--allow-empty-content", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    capture_path = _default_capture_path(args.output)
    print(
        "iPhone에서 미리보기가 보이는 테스트 앱 알림을 1건 발생시키십시오.",
        flush=True,
    )
    try:
        notification = consume_log_stream(
            _serial_lines(args.port, args.baud, args.timeout),
            output_path=args.output,
            capture_path=capture_path,
            allow_empty_content=args.allow_empty_content,
            target=args.target,
        )
    except CaptureNotReadyError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 4
    except CaptureTimeoutError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    except (CaptureFormatError, CaptureValidationError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"FAIL: serial port error: {exc}", file=sys.stderr)
        return 3

    print(
        f"PASS app_id={notification['app_id']} "
        f"title_present={bool(notification['title'])} "
        f"subtitle_present={bool(notification['subtitle'])} "
        f"message_present={bool(notification['message'])}",
        flush=True,
    )
    print(f"capture={capture_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
