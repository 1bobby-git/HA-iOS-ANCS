"""Pure notification parsing and relay-id dedupe helpers."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
import json
from typing import Any

from .const import DEFAULT_RELAY_ID_WINDOW_SIZE, HA_ECHO_APP_ID


class RelayIdWindow:
    """Bounded O(1) membership window for accepted relay IDs."""

    def __init__(self, limit: int = DEFAULT_RELAY_ID_WINDOW_SIZE) -> None:
        if limit <= 0:
            raise ValueError("RelayIdWindow limit must be positive")
        self._limit = limit
        self._queue: deque[str] = deque()
        self._ids: set[str] = set()

    def __contains__(self, relay_id: str) -> bool:
        return relay_id in self._ids

    def add(self, relay_id: str) -> None:
        if relay_id in self._ids:
            return

        self._queue.append(relay_id)
        self._ids.add(relay_id)

        if len(self._queue) > self._limit:
            oldest = self._queue.popleft()
            self._ids.remove(oldest)


def parse_notification_data(
    data: Mapping[str, Any], seen: RelayIdWindow
) -> dict[str, Any] | None:
    """Validate notification data and return an independent mapping."""

    relay_id = data.get("relay_id")
    if not isinstance(relay_id, str) or not relay_id.strip():
        return None

    if data.get("complete") is not True:
        return None

    if data.get("pre_existing") is True:
        return None

    if data.get("event") == "removed":
        return None

    if data.get("app_id") == HA_ECHO_APP_ID:
        return None

    if relay_id in seen:
        return None

    seen.add(relay_id)
    return dict(data)


def parse_notification(
    payload: str | bytes, seen: RelayIdWindow
) -> dict[str, Any] | None:
    """Decode and validate a relay notification payload."""

    try:
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="strict")
        data = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None

    if not isinstance(data, Mapping):
        return None

    return parse_notification_data(data, seen)
