import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
IDENTITY_HEADER = (
    ROOT / "components" / "platform_identity" / "include" / "platform_identity.h"
)
SINK_SOURCE = ROOT / "components" / "notification_sink" / "notification_sink_serial.c"
MQTT_PAYLOAD_SOURCE = ROOT / "components" / "mqtt_relay" / "mqtt_payload.c"
PORTAL_SOURCE = ROOT / "components" / "portal_http" / "portal_http.c"
PORTAL_JS = ROOT / "components" / "portal_http" / "portal.js"
PORTAL_HTML = ROOT / "components" / "portal_http" / "portal.html"
INSTALLER_HTML = ROOT / "docs" / "index.html"
INSTALLER_JS = ROOT / "docs" / "app.js"
INSTALLER_VENDOR_DIR = ROOT / "docs" / "vendor" / "esp-web-tools-10.4.0-r2"
MULTI_MANIFEST = ROOT / "docs" / "manifests" / "ios-ancs.json"
LEGACY_C6_MANIFEST = ROOT / "docs" / "manifests" / "esp32-c6.json"
BUILD_MATRIX = ROOT / "tools" / "build_matrix.ps1"
FLASH_SCRIPT = ROOT / "tools" / "flash.ps1"
C3_DEFAULTS = ROOT / "sdkconfig.defaults.esp32c3"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_platform_identity_maps_every_wifi_ble_target():
    assert IDENTITY_HEADER.exists()
    header = read(IDENTITY_HEADER)

    expected = {
        "CONFIG_IDF_TARGET_ESP32": ("ESP32", "0"),
        "CONFIG_IDF_TARGET_ESP32C2": ("C2", "9"),
        "CONFIG_IDF_TARGET_ESP32C3": ("C3", "9"),
        "CONFIG_IDF_TARGET_ESP32C5": ("C5", "28"),
        "CONFIG_IDF_TARGET_ESP32C6": ("C6", "9"),
        "CONFIG_IDF_TARGET_ESP32C61": ("C61", "9"),
        "CONFIG_IDF_TARGET_ESP32S3": ("S3", "0"),
    }
    assert '#define ANCS_TARGET_ID CONFIG_IDF_TARGET' in header
    assert '#define ANCS_SOURCE_ID CONFIG_IDF_TARGET "_ancs"' in header
    for target_symbol, (family, boot_gpio) in expected.items():
        assert target_symbol in header
        assert f'#define ANCS_DEVICE_FAMILY "{family}"' in header
        assert f"#define ANCS_DEFAULT_BOOT_GPIO {boot_gpio}" in header


def test_notification_and_state_json_use_target_identity():
    sink = read(SINK_SOURCE)
    mqtt = read(MQTT_PAYLOAD_SOURCE)

    assert '#include "platform_identity.h"' in sink
    assert '#include "platform_identity.h"' in mqtt
    assert "ANCS_TARGET_ID" in sink
    assert "ANCS_SOURCE_ID" in mqtt
    assert '"target":"esp32c6"' not in sink
    assert '"source":"esp32c6_ancs"' not in mqtt


def test_home_assistant_sensor_receives_complete_notification_attributes():
    sink = read(SINK_SOURCE)
    mqtt = read(MQTT_PAYLOAD_SOURCE)
    relay = read(ROOT / "components" / "mqtt_relay" / "mqtt_relay.c")

    sink_keys = {
        "schema_version",
        "target",
        "device_name",
        "session_id",
        "event",
        "event_id",
        "uid",
        "event_flags",
        "silent",
        "important",
        "pre_existing",
        "positive_action_available",
        "negative_action_available",
        "category_id",
        "category",
        "category_count",
        "app_id",
        "app_name",
        "title",
        "subtitle",
        "message",
        "message_size",
        "date",
        "complete",
        "truncated",
        "error",
        "received_at_ms",
    }
    mqtt_keys = {"relay_id", "source", "published_at_ms"}
    for key in sink_keys:
        assert f'\\"{key}\\"' in sink, f"missing ANCS attribute: {key}"
    for key in mqtt_keys:
        assert f'\\"{key}\\"' in mqtt, f"missing MQTT attribute: {key}"

    assert '\\"value_template\\":\\"{{ value_json.relay_id }}\\"' in relay
    assert '\\"json_attributes_topic\\":' in relay


def test_home_assistant_discovery_uses_compact_entities_and_removes_legacy_fields():
    relay = read(ROOT / "components" / "mqtt_relay" / "mqtt_relay.c")
    focused = {"notification_title", "notification_message", "app_name"}
    for field in focused:
        field_block = relay.split(f'.key = "{field}"', 1)[1].split("},", 1)[0]
        assert "[:255]" in field_block, f"unbounded Home Assistant state: {field}"

    assert '"homeassistant/sensor/%s/%s/config"' in relay
    assert '"homeassistant/binary_sensor/%s/device_status/config"' in relay
    assert "mqtt_relay_build_focused_discovery_payload" in relay
    assert "mqtt_relay_legacy_discovery_count()" in relay
    retained = relay.split(
        "static void mqtt_relay_publish_retained_status", 1
    )[1].split("static void mqtt_relay_drain_queue", 1)[0]
    assert "mqtt_relay_build_legacy_discovery_topic" in retained
    assert "mqtt_relay_publish_discovery_once(discovery_topic, \"\")" in retained
    assert "mqtt_relay_build_focused_discovery_topic" in retained
    assert "mqtt_relay_build_focused_discovery_payload" in retained


def test_portal_defaults_are_derived_from_reported_target():
    portal = read(PORTAL_SOURCE)
    javascript = read(PORTAL_JS)
    html = read(PORTAL_HTML)

    assert "ANCS_TARGET_ID" in portal
    assert "ANCS_DEVICE_FAMILY" in portal
    assert 'add_string(root, "target", ANCS_TARGET_ID)' in portal
    assert 'add_string(root, "device_family", ANCS_DEVICE_FAMILY)' in portal
    assert "status.target" in javascript
    assert "status.device_family" in javascript
    assert "deviceFamily.toLowerCase()" in javascript
    assert "IOS-ANCS-C6-" not in javascript
    assert "ios_ancs_c6_" not in javascript
    assert "ios-ancs/c6-" not in javascript
    assert "ESP32-C6" not in html


def test_installer_uses_one_selector_and_one_auto_detect_manifest():
    html = read(INSTALLER_HTML)
    javascript = read(INSTALLER_JS)

    assert html.count("<select") == 1
    assert html.count("<esp-web-install-button") == 1
    assert "./manifests/ios-ancs.json" in html
    assert "board-select" in html
    assert "board-select" in javascript
    assert "board-grid" not in javascript


def test_installer_retries_transient_compressed_block_failures():
    html = read(INSTALLER_HTML)

    assert (
        'src="./vendor/esp-web-tools-10.4.0-r2/install-button.js"'
        in html
    )
    assert INSTALLER_VENDOR_DIR.is_dir()

    runtime = "\n".join(
        read(path)
        for path in sorted(INSTALLER_VENDOR_DIR.glob("*.js"))
    )
    assert "Compressed block" in runtime
    assert "retrying with" in runtime
    assert "3 attempts" in runtime


def test_installer_retries_and_reports_transient_chip_erase_failures():
    runtime = "\n".join(
        read(path)
        for path in sorted(INSTALLER_VENDOR_DIR.glob("*.js"))
    )

    assert "Chip erase attempt" in runtime
    assert "erase retrying with" in runtime
    assert "3 attempts" in runtime
    assert 'error:"erase_failed"' in runtime
    assert "Failed to erase the device." in runtime


def test_installer_models_are_sorted_and_c61_is_explained():
    html = read(INSTALLER_HTML)
    javascript = read(INSTALLER_JS)
    option_labels = re.findall(r'<option value="[^"]+">([^<]+)</option>', html)

    assert option_labels == [
        "ESP32 / WROOM-32",
        "ESP32-C2",
        "ESP32-C3",
        "ESP32-C5",
        "ESP32-C6",
        "ESP32-C61",
        "ESP32-S3",
    ]
    assert "ESP32-C61은 ESP32-C6의 리비전이 아니라 별도 최신 칩입니다." in javascript


def test_unified_manifest_has_unique_builds_and_existing_binaries():
    assert MULTI_MANIFEST.exists()
    manifest = json.loads(read(MULTI_MANIFEST))
    builds = manifest["builds"]
    families = [build["chipFamily"] for build in builds]

    assert manifest["version"] == "0.3.7"
    assert len(families) == 7
    assert len(families) == len(set(families))
    assert "ESP32" in families
    assert "ESP32-C3" in families
    assert "ESP32-C6" in families
    assert "ESP32-S3" in families
    assert manifest["new_install_improv_wait_time"] == 0
    for build in builds:
        assert len(build["parts"]) == 1
        part = build["parts"][0]
        assert part["offset"] == 0
        assert "-v0.3.7.factory.bin" in part["path"]
        binary = (MULTI_MANIFEST.parent / part["path"]).resolve()
        assert binary.is_file()
        assert binary.stat().st_size > 0


def test_installer_build_proof_matches_each_published_binary():
    javascript = read(INSTALLER_JS)
    manifest = json.loads(read(MULTI_MANIFEST))

    for build in manifest["builds"]:
        part = build["parts"][0]
        binary = (MULTI_MANIFEST.parent / part["path"]).resolve()
        digest_prefix = hashlib.sha256(binary.read_bytes()).hexdigest()[:12].upper()
        assert f"SHA256 {digest_prefix}" in javascript


def test_c6_manifest_points_existing_users_to_current_image():
    manifest = json.loads(read(LEGACY_C6_MANIFEST))
    build = manifest["builds"][0]
    part = build["parts"][0]
    binary = (LEGACY_C6_MANIFEST.parent / part["path"]).resolve()

    assert manifest["version"] == "0.3.7"
    assert build["chipFamily"] == "ESP32-C6"
    assert part["path"] == "../firmware/esp32c6/ios-ancs-esp32c6-v0.3.7.factory.bin"
    assert binary.is_file()
    assert not (
        ROOT
        / "docs"
        / "firmware"
        / "esp32-c6"
        / "ios-ancs-c6-v0.1.0.factory.bin"
    ).exists()


def test_build_matrix_isolated_target_outputs_and_four_megabyte_baseline():
    defaults = read(ROOT / "sdkconfig.defaults")
    script = read(BUILD_MATRIX)

    assert "CONFIG_IDF_TARGET=" not in defaults
    assert "CONFIG_ESPTOOLPY_FLASHSIZE_4MB=y" in defaults
    for target in (
        "esp32",
        "esp32c2",
        "esp32c3",
        "esp32c5",
        "esp32c6",
        "esp32c61",
        "esp32s3",
    ):
        assert f"'{target}'" in script
    assert "-DIDF_TARGET=$Target" in script
    assert "-DSDKCONFIG=$SdkconfigPath" in script
    assert "build-$Target" in script
    assert "[string]$BuildRoot" in script
    assert "[int]$Jobs = 0" in script
    assert "if ($Jobs -gt 0)" in script
    assert "function Invoke-NinjaBuild" in script
    assert "'reconfigure'" in script
    assert "ninja.exe -C" in script
    assert "-j $Jobs all" in script
    assert 'Join-Path $BuildRoot "build-$Target"' in script
    assert "flasher_args.json" in script
    assert "merge-bin" in script


def test_c3_release_supports_every_published_c3_chip_revision():
    script = read(BUILD_MATRIX)

    assert C3_DEFAULTS.is_file()
    c3_defaults = read(C3_DEFAULTS)
    assert "CONFIG_ESP32C3_REV_MIN_0=y" in c3_defaults
    assert "CONFIG_ESP32C3_REV_MIN_3=y" not in c3_defaults
    assert "CONFIG_BT_CTRL_RUN_IN_FLASH_ONLY=y" in c3_defaults
    assert "Remove-Item -LiteralPath $SdkconfigPath" in script


def test_flash_helper_uses_the_selected_target_build_directory():
    script = read(FLASH_SCRIPT)

    assert "[string]$Target = 'esp32c6'" in script
    assert '"build-$Target"' in script
    assert '--target $Target' in script


def test_v034_release_guidance_documents_compact_home_assistant_entities():
    matrix = read(BUILD_MATRIX)
    build_ps1 = read(ROOT / "tools" / "build.ps1")
    build_sh = read(ROOT / "tools" / "build.sh")
    readme = read(ROOT / "README.md")
    installer = read(INSTALLER_HTML)
    pairing = read(ROOT / "docs" / "IOS_PAIRING.md")
    troubleshooting = read(ROOT / "docs" / "TROUBLESHOOTING.md")

    cmake = read(ROOT / "CMakeLists.txt")
    for source in (cmake, matrix, build_ps1, build_sh, installer):
        assert "0.3.7" in source
    for source in (readme, pairing, troubleshooting):
        assert "ancs-<lowercase_suffix>" in source
        assert "case-sensitive" in source
    for key in ("ready", "uptime_seconds", "ble_connected", "wifi_ssid"):
        assert key in readme
    for label in ("최근 알림", "알림 제목", "알림 내용", "앱 이름", "장치 상태", "장치 재시작"):
        assert label in readme
