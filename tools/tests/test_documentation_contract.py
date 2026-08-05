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


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def read_json(relative_path: str) -> dict:
    return json.loads(read_text(relative_path))


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


def assert_uses_only_canonical_urls(surface: str, text: str) -> None:
    assert CANONICAL_REPO_URL in text, surface
    assert CANONICAL_PAGES_URL in text, surface


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

    assert "설치기는 ESP32 펌웨어를 설치합니다" in index
    assert "HACS는 Home Assistant 동반 통합을 설치합니다" in index


def test_installer_has_stable_guided_section_ids():
    index = read_text("docs/index.html")

    for section_id in (
        "prepare",
        "flash",
        "provision",
        "pair",
        "home-assistant",
        "troubleshooting",
    ):
        assert f'id="{section_id}"' in index


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
    assert manifest["version"] == "0.4.0"


def test_brand_icon_is_square_png_with_recommended_size():
    data = (ROOT / "brand/icon.png").read_bytes()

    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert data[12:16] == b"IHDR"
    width, height = struct.unpack(">II", data[16:24])
    assert width == height
    assert width >= 256


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
