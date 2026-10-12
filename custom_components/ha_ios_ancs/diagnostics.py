"""Strict, content-free connection diagnostics shared by both runtime modes."""
from __future__ import annotations

from typing import Any

STATUS_TTL_SECONDS = 180
_BOOL_FIELDS = frozenset({
    "wifi_connected", "mqtt_connected", "ble_connected", "ble_bonded",
    "automatic_recovery_ap", "wifi_retry_paused", "bond_store_known",
    "session_authenticated", "link_encrypted", "ancs_service_found",
    "data_source_subscribed", "notification_source_subscribed", "ancs_ready",
    "notification_ready", "enrollment_active", "authentication_protection",
})
_INT_FIELDS = frozenset({
    "diagnostics_version", "uptime_seconds", "wifi_retry_attempts", "wifi_retry_in_ms",
    "wifi_generation", "wifi_disconnect_reason", "wifi_connect_error", "stored_peer_count",
    "bond_store_error", "boot_peer_count", "enrollment_remaining_seconds",
    "auth_failure_count", "auth_error", "ble_stage_error", "ble_disconnect_reason",
    "ble_generation", "mqtt_error_type", "mqtt_esp_error", "mqtt_tls_error",
    "mqtt_socket_errno", "mqtt_connect_return_code", "mqtt_retry_in_ms", "reset_reason",
    "last_notification_uptime_ms", "accepted", "published_ack", "dropped_offline",
    "dropped_enqueue", "dropped_policy", "last_mqtt_error_type", "last_mqtt_esp_error",
    "last_mqtt_error_at_ms",
})
_REQUIRED_READY = (
    "ble_connected", "session_authenticated", "link_encrypted", "ancs_service_found",
    "data_source_subscribed", "notification_source_subscribed",
)


def parse_diagnostics(data: Any) -> dict[str, Any]:
    """Allow only known scalar fields; never retain credentials or notification text."""
    if not isinstance(data, dict):
        return {}
    result: dict[str, Any] = {}
    for key in _BOOL_FIELDS:
        if type(value := data.get(key)) is bool:
            result[key] = value
    for key in _INT_FIELDS:
        if type(value := data.get(key)) is int and -(2**63) <= value < 2**64:
            result[key] = value
    digest = data.get("firmware_elf_sha256")
    if isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdefABCDEF" for c in digest):
        result["firmware_elf_sha256"] = digest.lower()
    if result.get("bond_store_known") is not True or result.get("stored_peer_count", -1) < 0:
        result["stored_peer_count"] = None
    if "boot_peer_count" in result and result["boot_peer_count"] < 0:
        result["boot_peer_count"] = None
    return result


def notification_ready(data: dict[str, Any], fresh: bool) -> bool | None:
    """Missing old-firmware fields remain unknown; a BLE link alone is not ready."""
    if not fresh or data.get("diagnostics_version") != 1:
        return None
    values = [data.get(key) for key in _REQUIRED_READY]
    if any(value is False for value in values):
        return False
    if all(value is True for value in values):
        return True
    return None


def connection_state(data: dict[str, Any], fresh: bool, available: bool | None) -> str | None:
    """Return a diagnosis without inferring erased NVS from runtime authentication."""
    if available is False:
        return "offline"
    if not data or data.get("diagnostics_version") != 1:
        return None
    if not fresh:
        return "stale"
    if data.get("wifi_retry_paused") is True:
        return "configuration"
    if data.get("wifi_connected") is False:
        return "wifi_retry"
    if data.get("mqtt_connected") is False:
        return "mqtt_error"
    if data.get("bond_store_known") is False:
        return "bond_store_error"
    if data.get("authentication_protection") is True:
        return "authentication_protection"
    if data.get("enrollment_active") is True:
        return "enrollment_open"
    if data.get("auth_error", 0) != 0:
        return "pairing_check" if data.get("stored_peer_count", 0) else "authentication_failed"
    if data.get("stored_peer_count") == 0 and data.get("ble_connected") is not True:
        return "enrollment_required"
    if data.get("ble_connected") is False:
        return "reconnecting"
    if notification_ready(data, fresh):
        return "ready"
    if data.get("ble_stage_error", 0) != 0:
        return "ancs_retry" if data.get("session_authenticated") is True else "authentication_timeout"
    if data.get("session_authenticated") is False:
        return "authenticating"
    if data.get("ancs_service_found") is False:
        return "discovering"
    if data.get("session_authenticated") is True and data.get("ancs_service_found") is True:
        return "subscribing"
    return None


USER_ACTIONS = {
    "offline": "장치 전원과 Wi-Fi·MQTT 연결을 확인하세요. 마지막 알림은 과거 기록입니다.",
    "stale": "실시간 상태를 기다리세요. 마지막 연결값을 현재 상태로 판단하지 마세요.",
    "configuration": "Wi-Fi 설정을 저장하거나 설정 모드를 종료하세요.",
    "wifi_retry": "자동 재접속 중입니다. 반복 인증 실패라면 Wi-Fi 비밀번호를 확인하세요.",
    "mqtt_error": "MQTT 서버·DNS·인증 설정과 오류 코드를 확인하세요.",
    "bond_store_error": "저장소 조회 오류입니다. 초기화하거나 페어링을 삭제하지 말고 오류 코드를 확인하세요.",
    "authentication_protection": "신규 등록을 명시적으로 다시 요청한 뒤 기기의 PIN으로 인증하세요. 재시작이나 Replace는 우선 필요하지 않습니다.",
    "enrollment_open": "등록 창 안에 기기의 PIN으로 등록한 뒤 시스템 알림 공유를 확인하세요.",
    "authentication_failed": "PIN과 인증 오류를 확인하고 등록을 다시 요청하세요. 남은 iPhone 등록이 새 등록을 막는 경우에만 이 기기 지우기를 사용하세요.",
    "pairing_check": "양쪽 등록 상태와 인증 오류를 확인하세요. 저장 정보 불일치가 확인된 경우에만 명시적으로 재페어링하세요.",
    "enrollment_required": "신규 등록을 요청하세요. iPhone에 기존 항목이 남아 등록을 막는 경우에만 이 기기 지우기를 사용하세요.",
    "reconnecting": "기존 페어링은 유지됩니다. iPhone의 Bluetooth와 거리를 확인하세요.",
    "authentication_timeout": "인증 시간이 초과되었습니다. iPhone 연결 상태와 PIN 입력을 확인하세요.",
    "ancs_retry": "시스템 알림 공유가 켜져 있는지 확인하세요. 자동 복구는 기존 페어링을 삭제하지 않습니다.",
}
