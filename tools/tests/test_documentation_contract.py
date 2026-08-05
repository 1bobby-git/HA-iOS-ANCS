from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_readme_korean_overview_and_installation_contract():
    readme = read_text("README.md")

    required_phrases = (
        "Apple Notification Center Service (ANCS)",
        "블루투스(BLE)를 통해 아이폰 등의 iOS 기기 알림",
        "iPhone → BLE ANCS → ESP32 → Wi-Fi/MQTT → Home Assistant",
        "빠른 설치",
        "Wi-Fi와 MQTT 설정",
        "iPhone 등록",
        "HACS",
        "문제 해결",
    )
    for phrase in required_phrases:
        assert phrase in readme


def test_public_docs_use_canonical_repository_and_pages_urls():
    documents = {
        "README.md": read_text("README.md"),
        "README.en.md": read_text("README.en.md"),
        "docs/index.html": read_text("docs/index.html"),
    }
    combined = "\n".join(documents.values())

    assert "https://github.com/1bobby-git/HA-iOS-ANCS" in combined
    assert "https://1bobby-git.github.io/HA-iOS-ANCS/" in combined
    assert "https://1bobby-git.github.io/ios-ancs/" not in combined


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
