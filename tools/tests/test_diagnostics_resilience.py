"""Executable, content-free diagnostics and pairing policy regressions."""
import asyncio
import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("ancs_diagnostics_contract", ROOT / "custom_components/ha_ios_ancs/diagnostics.py")
diagnostics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostics)


def ready_sample():
    return {"diagnostics_version": 1, "wifi_connected": True, "mqtt_connected": True,
            "ble_connected": True, "bond_store_known": True, "stored_peer_count": 1,
            "session_authenticated": True, "link_encrypted": True,
            "ancs_service_found": True, "data_source_subscribed": True,
            "notification_source_subscribed": True, "ancs_ready": True}


@pytest.mark.parametrize("field", ["wifi_connected", "mqtt_connected", "ble_connected",
    "session_authenticated", "link_encrypted", "ancs_service_found",
    "data_source_subscribed", "notification_source_subscribed", "ancs_ready"])
def test_each_ready_stage_is_required(field):
    data = ready_sample()
    assert diagnostics.notification_ready(data, True) is True
    data[field] = False
    assert diagnostics.notification_ready(data, True) is False
    del data[field]
    assert diagnostics.notification_ready(data, True) is None
    data[field] = "true"
    assert diagnostics.notification_ready(diagnostics.parse_diagnostics(data), True) is None


@pytest.mark.parametrize("data,fresh,expected", [
    ({}, True, None), ({"ble_connected": True, "ble_bonded": True}, True, None),
    (ready_sample(), False, None),
])
def test_legacy_and_stale_samples_cannot_claim_ready(data, fresh, expected):
    assert diagnostics.notification_ready(data, fresh) is expected


def test_unknown_storage_is_not_zero_peers_and_sensitive_fields_are_removed():
    data = ready_sample() | {"bond_store_known": False, "stored_peer_count": 0,
        "boot_peer_count": -1, "wifi_password": "fixture", "mqtt_password": "fixture",
        "title": "fixture", "message": "fixture", "peer_key": "fixture", "ssid": "fixture"}
    parsed = diagnostics.parse_diagnostics(data)
    assert parsed["stored_peer_count"] is None
    assert parsed["boot_peer_count"] is None
    assert diagnostics.connection_state(parsed, True, True) == "bond_store_error"
    assert not {"wifi_password", "mqtt_password", "title", "message", "peer_key", "ssid"} & parsed.keys()
    entry = SimpleNamespace(runtime_data=SimpleNamespace(diagnostics=data, diagnostics_fresh=True, available=True))
    downloaded = asyncio.run(diagnostics.async_get_config_entry_diagnostics(None, entry))
    assert downloaded["connection"] == parsed


@pytest.mark.parametrize("delta,expected", [
    ({"wifi_retry_paused": True}, "configuration"),
    ({"wifi_connected": False}, "wifi_retry"),
    ({"mqtt_connected": False}, "mqtt_error"),
    ({"authentication_protection": True}, "authentication_protection"),
    ({"enrollment_active": True}, "enrollment_open"),
    ({"auth_error": 81, "stored_peer_count": 0}, "authentication_failed"),
    ({"auth_error": 6}, "pairing_check"),
    ({"ble_connected": False}, "reconnecting"),
    ({"ble_connected": False, "stored_peer_count": 0}, "enrollment_required"),
])
def test_action_states_do_not_merge_wifi_pairing_and_auth_errors(delta, expected):
    assert diagnostics.connection_state(ready_sample() | delta, True, True) == expected


def c_function(source, signature):
    start = source.index(signature + "\n{")
    brace = source.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


def test_actual_ble_guard_and_enrollment_expiry_execute_with_virtual_time(tmp_path):
    compiler = shutil.which("cc") or shutil.which("gcc")
    if compiler is None:
        pytest.skip("host C compiler unavailable")
    client = (ROOT / "components/ancs_client/ancs_client.c").read_text()
    functions = c_function(client, "static void clear_auth_failure_guard_locked(void)")
    functions += "\n" + c_function(client, "static bool record_auth_failure_locked(int64_t failure_at_ms,\n                                       bool missing_local_bond)")
    constants = "\n".join(re.findall(r"^#define AUTH_FAILURE_(?:WINDOW_MS|REPAIR_THRESHOLD).*$", client, re.M))
    (tmp_path / "esp_err.h").write_text("typedef int esp_err_t;\n#define ESP_OK 0\n#define ESP_ERR_INVALID_ARG 258\n#define ESP_ERR_INVALID_STATE 259\n")
    source = tmp_path / "ble.c"
    source.write_text('''#include <assert.h>
#include <stdint.h>
#include "ble_enroll.h"
static struct { int auth_error; uint8_t auth_failure_count; int64_t last_auth_failure_ms; bool pairing_repair_required; } s_client;
static ble_enroll_state_t s_enroll;
''' + constants + "\n" + functions + '''
int main(void) {
    ble_enroll_init(&s_enroll, (ble_enroll_config_t){0});
    assert(ble_enroll_open_window(&s_enroll, 0) == ESP_OK);
    assert(ble_enroll_window_active(&s_enroll, 119999));
    assert(!ble_enroll_window_active(&s_enroll, 120000));
    assert(!ble_enroll_should_advertise(&s_enroll, 120000));
    assert(ble_enroll_open_window(&s_enroll, 120001) == ESP_OK);
    assert(ble_enroll_window_active(&s_enroll, 120002));
    clear_auth_failure_guard_locked();
    assert(!record_auth_failure_locked(0, true));
    assert(!record_auth_failure_locked(120000, true));
    assert(record_auth_failure_locked(240000, true)); /* adjacent interval inclusive */
    assert(!ble_enroll_window_active(&s_enroll, 240000));
    clear_auth_failure_guard_locked();
    assert(!record_auth_failure_locked(0, true));
    assert(!record_auth_failure_locked(120001, true));
    assert(s_client.auth_failure_count == 1);
    assert(!record_auth_failure_locked(120002, true));
    assert(record_auth_failure_locked(120003, true));
    clear_auth_failure_guard_locked();
    for (int i=0;i<300;i++) assert(!record_auth_failure_locked(i, false));
    assert(s_client.auth_failure_count == UINT8_MAX);
    clear_auth_failure_guard_locked();
    const uint8_t peer[6] = {1,2,3,4,5,6};
    const uint8_t other[6] = {2,3,4,5,6,7};
    ble_enroll_note_bonded(&s_enroll, peer);
    assert(ble_enroll_open_window(&s_enroll, 300000) == ESP_ERR_INVALID_STATE);
    assert(ble_enroll_should_advertise(&s_enroll, 900000));
    assert(ble_enroll_pairing_allowed(&s_enroll, peer, 900000));
    assert(!ble_enroll_pairing_allowed(&s_enroll, other, 900000));
    assert(ble_enroll_request_replace(&s_enroll, false, 900000) == ESP_ERR_INVALID_STATE);
    assert(ble_enroll_has_bond(&s_enroll));
    assert(ble_enroll_request_replace(&s_enroll, true, 900000) == ESP_OK);
    assert(!ble_enroll_has_bond(&s_enroll));
    assert(ble_enroll_window_active(&s_enroll, 900001));
    return 0;
}
''')
    exe = tmp_path / "ble"
    subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(tmp_path),
        "-I", str(ROOT / "components/ble_enroll/include"), str(source),
        str(ROOT / "components/ble_enroll/ble_enroll.c"), "-o", str(exe)], check=True, capture_output=True, text=True)
    subprocess.run([str(exe)], check=True, capture_output=True)
