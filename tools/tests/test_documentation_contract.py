import json
import re
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CANONICAL_REPO_URL = "https://github.com/1bobby-git/HA-iOS-ANCS"
CANONICAL_PAGES_URL = "https://1bobby-git.github.io/HA-iOS-ANCS/"
HACS_MY_LINK = (
    "https://my.home-assistant.io/redirect/hacs_repository/"
    "?owner=1bobby-git&repository=HA-iOS-ANCS&category=integration"
)
OLD_REPO_URL_RE = re.compile(r"https://github\.com/1bobby-git/ios-ancs(?:/|\b|[?#])")
OLD_PAGES_URL_RE = re.compile(r"https://1bobby-git\.github\.io/ios-ancs(?:/|\b|[?#])")

PUBLIC_GUIDANCE_SURFACES = (
    "README.md",
    "README.en.md",
    "docs/index.html",
    "docs/app.js",
    "docs/IOS_PAIRING.md",
    "docs/TROUBLESHOOTING.md",
    "homeassistant/automation_ios_ancs_c6_relay.yaml",
)
APP_ID_REFERENCE_SURFACES = (
    "README.md",
    "README.en.md",
    "docs/index.html",
)
INSTALLER_SECTION_MARKERS = (
    "flash",
    "setup-ap",
    "provision",
    "home-assistant",
    "pair",
    "verify",
)
INSTALLER_FACTS = (
    "IOS-ANCS-SETUP-XXXXXX",
    "ancs-xxxxxx",
    "http://192.168.4.1",
    "iPhone 등록 시작",
    "123456",
)
LEGACY_INSTALLER_COPY = (
    "ANCS Flash Station",
    "모델을 고르고",
    "현장에서 설치합니다",
    "FIELD PROCEDURE",
    "현장 준비",
)
OWNER_SPECIFIC_GUIDANCE = (
    "COM" + "7",
    "COM" + "9",
    "572" + "B20",
    "SPARK" + "PLUS",
    "DAI" + "SO",
    "AX" + "1800",
    "notify.mobile_app_" + "1bobby",
    "sensor.ios_ancs_c6_2b20_ios_ancs_c6_2b20_last_notification",
)


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def read_json(relative_path: str) -> dict:
    return json.loads(read_text(relative_path))


def find_section_marker_position(text: str, marker: str) -> int:
    marker_re = re.escape(marker)
    pattern = rf'<section\b(?=[^>]*\bid="{marker_re}")[^>]*>'
    match = re.search(pattern, text, re.IGNORECASE)
    if match is not None:
        return match.start()
    return -1


def assert_uses_only_canonical_urls(surface: str, text: str) -> None:
    assert CANONICAL_REPO_URL in text, surface
    assert CANONICAL_PAGES_URL in text, surface


def test_readme_korean_overview_contract():
    readme = read_text("README.md")

    required_phrases = (
        "Apple Notification Center Service (ANCS)",
        "블루투스(BLE)를 통해 아이폰 등의 iOS 기기 알림",
        "iPhone → BLE ANCS → ESP32 → Wi-Fi/MQTT → Home Assistant",
    )
    for phrase in required_phrases:
        assert phrase in readme


def test_readme_korean_guide_headings_are_structured_and_ordered():
    readme = read_text("README.md")
    heading_patterns = (
        r"^## 빠른 설치\s*$",
        r"^## Wi-Fi와 MQTT 설정\s*$",
        r"^## iPhone 등록\s*$",
        r"^## Home Assistant와 HACS\s*$",
        r"^## 문제 해결\s*$",
    )

    positions = []
    for pattern in heading_patterns:
        match = re.search(pattern, readme, re.MULTILINE)
        assert match is not None, pattern
        positions.append(match.start())

    assert positions == sorted(positions)


def test_readmes_expose_canonical_repository_and_pages_urls():
    for surface in ("README.md", "README.en.md"):
        assert_uses_only_canonical_urls(surface, read_text(surface))


def test_installer_page_exposes_canonical_urls_and_rejects_old_urls():
    surface = "docs/index.html"
    index = read_text(surface)

    assert_uses_only_canonical_urls(surface, index)


def test_public_surfaces_reject_legacy_repository_and_pages_urls():
    for surface in ("README.md", "README.en.md", "docs/index.html"):
        text = read_text(surface)
        assert OLD_REPO_URL_RE.search(text) is None, surface
        assert OLD_PAGES_URL_RE.search(text) is None, surface


def test_installer_distinguishes_firmware_flashing_from_hacs_integration():
    index = read_text("docs/index.html")

    assert "Apple Notification Center Service (ANCS)" in index
    assert "블루투스(BLE)를 통해 아이폰 등의 iOS 기기 알림" in index
    assert "이 페이지는 ESP32 펌웨어 설치용입니다." in index
    assert (
        "HACS는 Home Assistant 동반 통합만 설치하며 "
        "ESP32 펌웨어를 설치하거나 업데이트하지 않습니다."
    ) in index


def test_installer_title_uses_public_home_assistant_copy_and_rejects_old_copy():
    index = read_text("docs/index.html")

    assert "<title>Home Assistant iOS ANCS Installer</title>" in index
    for phrase in LEGACY_INSTALLER_COPY:
        assert phrase not in index, phrase


def test_installer_has_ordered_six_step_public_guidance_markers():
    index = read_text("docs/index.html")

    positions = []
    for marker in INSTALLER_SECTION_MARKERS:
        position = find_section_marker_position(index, marker)
        assert position >= 0, marker
        positions.append(position)

    assert positions == sorted(positions)


def test_installer_exposes_generic_setup_pairing_and_home_assistant_facts():
    index = read_text("docs/index.html")

    for fact in INSTALLER_FACTS:
        assert fact in index, fact


def test_readmes_and_installer_link_app_id_reference():
    for surface in APP_ID_REFERENCE_SURFACES:
        text = read_text(surface)
        assert "APP_ID_REFERENCE.md" in text, surface


def test_public_guidance_surfaces_reject_machine_and_owner_specific_examples():
    for surface in PUBLIC_GUIDANCE_SURFACES:
        text = read_text(surface)
        for token in OWNER_SPECIFIC_GUIDANCE:
            assert token not in text, f"{surface}: {token}"


def test_hacs_metadata_matches_custom_integration_contract():
    metadata = read_json("hacs.json")

    assert metadata == {
        "name": "HA iOS ANCS",
        "homeassistant": "2026.7.0",
    }

    manifest = read_json("custom_components/ha_ios_ancs/manifest.json")
    assert manifest["domain"] == "ha_ios_ancs"
    assert manifest["name"] == "HA iOS ANCS"
    assert manifest["documentation"] == CANONICAL_REPO_URL
    assert manifest["issue_tracker"] == f"{CANONICAL_REPO_URL}/issues"
    assert manifest["iot_class"] == "local_push"
    assert manifest["integration_type"] == "device"
    assert manifest["version"] == "0.5.1"


def test_integration_brand_icon_is_square_png_with_recommended_size():
    data = (
        ROOT / "custom_components/ha_ios_ancs/brand/icon.png"
    ).read_bytes()

    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert data[12:16] == b"IHDR"
    width, height = struct.unpack(">II", data[16:24])
    assert width == height
    assert width >= 256


def test_hacs_package_contains_the_brand_asset_and_an_osi_license():
    integration_icon = (
        ROOT / "custom_components/ha_ios_ancs/brand/icon.png"
    ).read_bytes()
    license_text = read_text("LICENSE")

    assert integration_icon.startswith(b"\x89PNG\r\n\x1a\n")
    assert not (ROOT / "brand").exists()
    assert license_text.startswith("MIT License\n")
    assert "Copyright (c) 2026 1bobby-git" in license_text
    assert "Permission is hereby granted, free of charge" in license_text


def test_readmes_include_hacs_my_link_and_firmware_boundary():
    for surface in ("README.md", "README.en.md"):
        content = read_text(surface)
        assert HACS_MY_LINK in content, surface
        assert "ESP32" in content, surface
        assert "firmware" in content.lower() or "펌웨어" in content, surface
        assert "HACS" in content, surface

    korean = read_text("README.md")
    english = read_text("README.en.md")
    assert "HACS는 Home Assistant 동반 통합만 설치합니다" in korean
    assert "ESP32 펌웨어를 설치하거나 업데이트하지 않습니다" in korean
    assert "HACS installs only the Home Assistant companion integration" in english
    assert "never flashes or updates ESP32 firmware" in english


def test_readmes_document_registry_backed_hacs_device_setup():
    korean = read_text("README.md")
    english = read_text("README.en.md")

    korean_phrases = (
        "HACS 통합을 추가할 때 MQTT 기본 토픽을 입력하지 않습니다.",
        "호환 기기가 하나면 자동으로 선택하고, 둘 이상이면 기기 이름 선택 목록을 표시합니다.",
        "`알림` 이벤트 엔티티는 새 장치를 만들지 않고 기존 MQTT 장치에 추가됩니다.",
        "retained `최근 알림` 상태를 새 알림으로 재생하지 않습니다.",
        "기존 수동 토픽 항목은 통합의 **재구성**에서 MQTT 장치를 선택할 때까지 기존 방식으로 유지됩니다.",
    )
    english_phrases = (
        "Adding the HACS integration no longer asks for an MQTT base topic.",
        "One compatible device is selected automatically; multiple devices are shown by name.",
        "The `Notification` event entity is added to the existing MQTT device instead of creating another device.",
        "does not replay the retained `Last notification` state as a new event",
        "Legacy manual-topic entries keep working until you choose **Reconfigure** and select their MQTT device.",
    )

    for phrase in korean_phrases:
        assert phrase in korean
    for phrase in english_phrases:
        assert phrase in english


def test_validation_workflow_runs_hacs_and_hassfest_without_ignored_checks():
    workflow = (ROOT / ".github/workflows/validate.yml").read_text(encoding="utf-8")

    try:
        import yaml
    except ImportError:
        parsed = None
    else:
        parsed = yaml.safe_load(workflow)

    if parsed is not None:
        triggers = parsed.get("on", {})
        assert "push" in triggers
        assert "pull_request" in triggers
        assert "schedule" in triggers
        assert "workflow_dispatch" in triggers
        assert parsed.get("permissions") == {}
        jobs = parsed["jobs"]
        assert len(jobs) == 2

    assert "uses: hacs/action@main" in workflow
    assert "category: integration" in workflow
    assert "uses: home-assistant/actions/hassfest@master" in workflow
    assert "Floating action refs are intentional" in workflow
    assert "scheduled runs detect upstream validation-rule drift" in workflow
    assert "job-level contents: read permissions limit exposure" in workflow
    assert re.search(r"\bignore", workflow, re.IGNORECASE) is None
