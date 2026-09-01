import json
from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def render_relay_status(system: dict) -> dict:
    status = {
        "configured": True,
        "config": {
  "wifi_ssid": "KDP-STG",
  "mqtt_host": "220.85.87.159",
  "mqtt_port": 1883,
  "mqtt_tls": False,
  "mqtt_client_id": "ios_ancs_c6_2b20",
  "mqtt_base_topic": "ios-ancs/c6-2b20",
        },
        "runtime": {
  "ap_started": True,
  "sta_started": True,
  "sta_connecting": False,
  "sta_has_ip": True,
  "ap_ssid": "IOS-ANCS-SETUP-572B20",
        },
        "system": system,
    }
    portal_js = ROOT / "components/portal_http/portal.js"
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const source = fs.readFileSync({json.dumps(str(portal_js))}, 'utf8');
        const elements = new Map();
        function makeElement() {{
return {{
  value: '', checked: false, disabled: false, hidden: false,
  textContent: '', innerHTML: '', className: '', dataset: {{}},
  classList: {{ add() {{}}, remove() {{}}, toggle() {{}} }},
  appendChild() {{}}, addEventListener() {{}}, setAttribute() {{}},
  removeAttribute() {{}}, focus() {{}},
}};
        }}
        global.document = {{
body: makeElement(), hidden: false,
getElementById(id) {{
  if (!elements.has(id)) elements.set(id, makeElement());
  return elements.get(id);
}},
createElement() {{ return makeElement(); }},
        }};
        global.fetch = async () => ({{
ok: true, statusText: 'OK', json: async () => ({json.dumps(status)}),
        }});
        eval(source);
        setTimeout(() => {{
process.stdout.write(JSON.stringify({{
  value: elements.get('status-relay-value').textContent,
  detail: elements.get('status-relay-detail').textContent,
  state: elements.get('status-relay').dataset.state,
}}));
        }}, 30);
        """
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        encoding="utf-8",
        timeout=5,
    )
    return json.loads(result.stdout)


def test_firmware_status_exposes_each_drop_reason():
    header = read("components/portal_http/include/portal_http.h")
    app = read("main/app_main.c")
    api = read("components/portal_http/portal_http.c")
    frontend = read("components/portal_http/portal.js")

    for name in (
        "notifications_dropped_offline",
        "notifications_dropped_enqueue",
        "notifications_dropped_policy",
    ):
        assert name in header
        assert name in app
        assert f'"{name}"' in api
        assert name in frontend
    assert "연결 장애 중" not in frontend
    assert "부팅 후 제외" in frontend


def test_portal_renders_cumulative_drop_breakdown():
    rendered = render_relay_status(
        {
  "mqtt_connected": True,
  "mqtt_connecting": False,
  "ble_bonded": True,
  "ble_connected": True,
  "enroll_window_open": False,
  "notifications_published": 4,
  "notifications_dropped": 63,
  "notifications_dropped_offline": 60,
  "notifications_dropped_enqueue": 0,
  "notifications_dropped_policy": 3,
        }
    )
    assert rendered == {
        "value": "4건 전송",
        "detail": "부팅 후 제외 63건 · MQTT 미연결 60건 · 정책 필터 3건",
        "state": "ready",
    }


def test_portal_marks_legacy_total_as_unclassified():
    rendered = render_relay_status(
        {
  "mqtt_connected": False,
  "mqtt_connecting": False,
  "ble_bonded": True,
  "ble_connected": True,
  "enroll_window_open": False,
  "notifications_published": 0,
  "notifications_dropped": 7,
        }
    )
    assert rendered["detail"] == (
        "부팅 후 제외 7건 · 이전 펌웨어는 제외 원인을 구분하지 않습니다"
    )
    assert rendered["state"] == "error"
