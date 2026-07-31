#!/usr/bin/env python3

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ECHO_APP_ID = "io.robbie.HomeAssistant"
SOURCE = "esp32c6_ancs"
REDACTED = "<redacted>"
CONTENT_FIELDS = {"title", "subtitle", "message"}
SECRET_FIELDS = {
    "wifi_password",
    "mqtt_password",
    "password",
    "ca_cert",
    "mqtt_ca",
    "token",
}


class MqttRelayValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class MqttRelayVerificationResult:
    base_topic: str
    notification_count: int
    relay_ids: list[str]
    echo_blocked: bool
    offline_drop_verified: bool | None
    report: str


def _decode_payload(payload: Any) -> Any:
    if isinstance(payload, (dict, list)):
        return payload
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    if not isinstance(payload, str):
        return payload
    stripped = payload.strip()
    if not stripped:
        return payload
    if stripped[0] not in "[{":
        return payload
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return payload


def _event_retain(event: dict[str, Any]) -> bool:
    return bool(event.get("retain", event.get("retained", False)))


def _event_qos(event: dict[str, Any]) -> int:
    qos = event.get("qos", event.get("qos_level", 0))
    try:
        return int(qos)
    except (TypeError, ValueError):
        return 0


def _load_events(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        return []
    if stripped[0] == "[":
        data = json.loads(stripped)
        if not isinstance(data, list):
            raise MqttRelayValidationError("capture JSON root must be an array")
        return data

    events = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MqttRelayValidationError(
                f"invalid JSONL event on line {line_number}: {exc}"
            ) from exc
        if not isinstance(event, dict):
            raise MqttRelayValidationError(f"event on line {line_number} is not an object")
        events.append(event)
    return events


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            if key in CONTENT_FIELDS:
                sanitized[key] = REDACTED if item else ""
            elif key in SECRET_FIELDS:
                sanitized[key] = REDACTED if item else item
            else:
                sanitized[key] = _sanitize(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MqttRelayValidationError(message)


def _find_notification_events(events: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any], dict[str, Any]]]:
    notifications = []
    for index, event in enumerate(events):
        topic = str(event.get("topic", ""))
        if not topic.endswith("/notification"):
            continue
        payload = _decode_payload(event.get("payload"))
        _require(isinstance(payload, dict), f"notification payload at event {index} is not JSON")
        notifications.append((index, event, payload))
    return notifications


def _base_topic_from_notification(topic: str) -> str:
    return topic[: -len("/notification")]


def _has_required_availability(events: list[dict[str, Any]], base_topic: str) -> bool:
    expected_topic = f"{base_topic}/availability"
    for event in events:
        if str(event.get("topic", "")) != expected_topic:
            continue
        if str(event.get("payload", "")).strip() != "online":
            continue
        if _event_retain(event) and _event_qos(event) == 1:
            return True
    return False


def _has_required_discovery(events: list[dict[str, Any]], base_topic: str) -> bool:
    for event in events:
        topic = str(event.get("topic", ""))
        if not (topic.startswith("homeassistant/") and topic.endswith("/config")):
            continue
        payload = _decode_payload(event.get("payload"))
        if not isinstance(payload, dict):
            continue
        if not _event_retain(event) or _event_qos(event) != 1:
            continue
        payload_text = json.dumps(payload, ensure_ascii=False)
        if f"{base_topic}/notification" in payload_text and "relay_id" in payload_text:
            return True
    return False


def _verify_notification_event(event: dict[str, Any], payload: dict[str, Any]) -> str:
    _require(_event_qos(event) == 1, "notification publish must use QoS 1")
    _require(not _event_retain(event), "notification publish must not be retained")
    _require(payload.get("source") == SOURCE, "notification source must be esp32c6_ancs")
    relay_id = payload.get("relay_id")
    _require(isinstance(relay_id, str) and relay_id, "notification relay_id is required")
    _require(payload.get("complete") is True, "notification complete must be true")
    _require(payload.get("pre_existing") is not True, "pre-existing notification was published")
    _require(
        not _is_home_assistant_notification(payload),
        "Home Assistant notification was published",
    )
    return relay_id


def _is_home_assistant_notification(payload: dict[str, Any]) -> bool:
    return payload.get("app_id", "") == ECHO_APP_ID


def _verify_offline_drop(
    events: list[dict[str, Any]],
    base_topic: str,
    notification_indices: list[int],
) -> bool:
    availability_topic = f"{base_topic}/availability"
    offline_indices = [
        index
        for index, event in enumerate(events)
        if str(event.get("topic", "")) == availability_topic
        and str(event.get("payload", "")).strip() == "offline"
    ]
    online_after_offline = [
        index
        for index, event in enumerate(events)
        if str(event.get("topic", "")) == availability_topic
        and str(event.get("payload", "")).strip() == "online"
        and any(index > offline_index for offline_index in offline_indices)
    ]
    _require(offline_indices, "offline drop proof requires an offline availability event")
    _require(online_after_offline, "offline drop proof requires reconnect availability")

    first_offline = offline_indices[0]
    first_reconnect = online_after_offline[0]
    replayed = [idx for idx in notification_indices if first_offline < idx <= first_reconnect]
    _require(not replayed, "notification was published during offline window")

    for event in events:
        if str(event.get("topic", "")) != f"{base_topic}/state":
            continue
        payload = _decode_payload(event.get("payload"))
        if isinstance(payload, dict) and int(payload.get("dropped_offline", 0) or 0) >= 1:
            return True
    raise MqttRelayValidationError("offline drop proof requires dropped_offline state >= 1")


def _build_report(
    *,
    base_topic: str,
    availability_ok: bool,
    discovery_ok: bool,
    relay_ids: list[str],
    notification_payload: dict[str, Any],
    echo_blocked: bool,
    offline_drop_verified: bool | None,
) -> str:
    sanitized = _sanitize(notification_payload)
    app_id = sanitized.get("app_id", "<unknown>")
    lines = [
        "# MQTT Relay Validation Report",
        "",
        "Validation source: captured broker events.",
        "Live device, iPhone, and Home Assistant receipt evidence must be added separately.",
        "",
        "## Broker Contracts",
        f"- base_topic: `{base_topic}`",
        f"- retained availability observed: `{availability_ok}`",
        f"- retained discovery observed: `{discovery_ok}`",
        f"- notification_count: `{len(relay_ids)}`",
        f"- relay_id: `{relay_ids[0] if relay_ids else ''}`",
        f"- app_id: `{app_id}`",
        f"- content fields: redacted",
        f"- Home Assistant app publish excluded: `{echo_blocked}`",
        f"- offline drop proof: `{offline_drop_verified}`",
        "",
        "## Sanitized Notification Shape",
        "```json",
        json.dumps(sanitized, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
    ]
    return "\n".join(lines)


def verify_broker_events(
    events: Iterable[dict[str, Any]],
    *,
    expect_offline_drop: bool = False,
) -> MqttRelayVerificationResult:
    event_list = list(events)
    _require(event_list, "no broker events supplied")

    notifications = _find_notification_events(event_list)
    _require(notifications, "one MQTT notification publish is required")
    _require(
        not any(
            _is_home_assistant_notification(payload)
            for _, _, payload in notifications
        ),
        "Home Assistant notification was published",
    )
    _require(len(notifications) == 1, "second notification publish was observed")

    notification_index, notification_event, notification_payload = notifications[0]
    base_topic = _base_topic_from_notification(str(notification_event.get("topic", "")))
    _require(base_topic, "notification topic must include a base topic")

    availability_ok = _has_required_availability(event_list, base_topic)
    discovery_ok = _has_required_discovery(event_list, base_topic)
    _require(availability_ok, "retained online availability event is required")
    _require(discovery_ok, "retained discovery config with relay_id is required")

    relay_id = _verify_notification_event(notification_event, notification_payload)
    offline_drop_verified = None
    if expect_offline_drop:
        offline_drop_verified = _verify_offline_drop(
            event_list,
            base_topic,
            [notification_index],
        )

    report = _build_report(
        base_topic=base_topic,
        availability_ok=availability_ok,
        discovery_ok=discovery_ok,
        relay_ids=[relay_id],
        notification_payload=notification_payload,
        echo_blocked=True,
        offline_drop_verified=offline_drop_verified,
    )
    return MqttRelayVerificationResult(
        base_topic=base_topic,
        notification_count=1,
        relay_ids=[relay_id],
        echo_blocked=True,
        offline_drop_verified=offline_drop_verified,
        report=report,
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate captured MQTT broker events for the ESP32-C6 ANCS relay."
    )
    parser.add_argument("capture", type=Path, help="JSONL or JSON array broker event capture")
    parser.add_argument("--report", type=Path, default=Path("artifacts/mqtt-relay-report.md"))
    parser.add_argument("--expect-offline-drop", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        result = verify_broker_events(
            _load_events(args.capture),
            expect_offline_drop=args.expect_offline_drop,
        )
    except (OSError, json.JSONDecodeError, MqttRelayValidationError) as exc:
        print(f"FAIL: {exc}")
        return 1

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(result.report + "\n", encoding="utf-8")
    print(
        "PASS "
        f"base_topic={result.base_topic} "
        f"relay_id={result.relay_ids[0]} "
        f"report={args.report}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
