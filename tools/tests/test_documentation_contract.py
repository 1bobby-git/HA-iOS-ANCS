import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CANONICAL_REPO_URL = "https://github.com/1bobby-git/HA-iOS-ANCS"
CANONICAL_PAGES_URL = "https://1bobby-git.github.io/HA-iOS-ANCS/"
OLD_REPO_URL_RE = re.compile(r"https://github\.com/1bobby-git/ios-ancs(?:/|\b|[?#])")
OLD_PAGES_URL_RE = re.compile(r"https://1bobby-git\.github\.io/ios-ancs(?:/|\b|[?#])")


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


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

    assert "웹 설치기는 ESP32 펌웨어를 설치합니다" in index
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
