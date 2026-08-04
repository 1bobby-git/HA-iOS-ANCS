import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERSION = "0.3.3"
EXPECTED_TARGETS = (
    ("ESP32", "esp32"),
    ("ESP32-C2", "esp32c2"),
    ("ESP32-C3", "esp32c3"),
    ("ESP32-C5", "esp32c5"),
    ("ESP32-C6", "esp32c6"),
    ("ESP32-C61", "esp32c61"),
    ("ESP32-S3", "esp32s3"),
)

MAIN_MANIFEST = ROOT / "docs" / "manifests" / "ios-ancs.json"
C6_MANIFEST = ROOT / "docs" / "manifests" / "esp32-c6.json"
FINGERPRINTS = ROOT / "docs" / f"release-fingerprints-v{VERSION}.sha256"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_manifest(path: Path) -> dict:
    return json.loads(read_text(path))


def manifest_binary_path(manifest_path: Path, part_path: str) -> Path:
    return (manifest_path.parent / part_path).resolve()


def binary_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def release_builds() -> list[tuple[str, str, Path]]:
    manifest = load_manifest(MAIN_MANIFEST)
    builds = []
    for build in manifest["builds"]:
        part = build["parts"][0]
        builds.append(
            (
                build["chipFamily"],
                part["path"],
                manifest_binary_path(MAIN_MANIFEST, part["path"]),
            )
        )
    return builds


def test_v033_version_anchors_are_on_release_surfaces():
    checks = {
        "CMakeLists.txt": 'set(PROJECT_VER "0.3.3")',
        "tools/build.ps1": "[string]$Version = '0.3.3'",
        "tools/build.sh": 'version="${VERSION:-0.3.3}"',
        "tools/build_matrix.ps1": "[string]$Version = '0.3.3'",
        "docs/manifests/ios-ancs.json": '"version": "0.3.3"',
        "docs/manifests/esp32-c6.json": '"version": "0.3.3"',
        "README.md": "All v0.3.3 images shown in the installer",
        "docs/index.html": '<dd id="hero-version">v0.3.3</dd>',
        "docs/app.js": 'validation: "v0.3.3',
    }
    for relative_path, anchor in checks.items():
        assert anchor in read_text(ROOT / relative_path), relative_path


def test_main_manifest_has_exactly_seven_unique_v033_chip_builds():
    manifest = load_manifest(MAIN_MANIFEST)
    builds = manifest["builds"]

    assert manifest["version"] == VERSION
    assert manifest["new_install_improv_wait_time"] == 0
    assert [(build["chipFamily"], build["parts"][0]["path"]) for build in builds] == [
        (
            chip_family,
            f"../firmware/{target}/ios-ancs-{target}-v{VERSION}.factory.bin",
        )
        for chip_family, target in EXPECTED_TARGETS
    ]
    assert len({build["chipFamily"] for build in builds}) == 7


def test_c6_manifest_is_legacy_single_chip_pointer_to_current_factory_image():
    manifest = load_manifest(C6_MANIFEST)
    builds = manifest["builds"]

    assert manifest["version"] == VERSION
    assert len(builds) == 1
    assert builds[0]["chipFamily"] == "ESP32-C6"
    assert builds[0]["parts"] == [
        {
            "path": f"../firmware/esp32c6/ios-ancs-esp32c6-v{VERSION}.factory.bin",
            "offset": 0,
        }
    ]
    assert manifest_binary_path(C6_MANIFEST, builds[0]["parts"][0]["path"]).is_file()


def test_every_manifest_part_resolves_to_committed_versioned_binary():
    tracked = set(
        subprocess_output("git", "ls-files", "docs/firmware").splitlines()
    )
    for manifest_path in (MAIN_MANIFEST, C6_MANIFEST):
        manifest = load_manifest(manifest_path)
        for build in manifest["builds"]:
            assert len(build["parts"]) == 1
            part = build["parts"][0]
            assert part["offset"] == 0
            assert re.search(rf"/ios-ancs-[a-z0-9]+-v{VERSION}\.factory\.bin$", part["path"])
            binary = manifest_binary_path(manifest_path, part["path"])
            relative = binary.relative_to(ROOT).as_posix()
            assert relative in tracked
            assert binary.is_file()
            assert binary.stat().st_size > 0


def test_installer_advertised_sha256_prefixes_match_factory_binaries():
    app_js = read_text(ROOT / "docs" / "app.js")
    report = read_text(ROOT / "docs" / "VALIDATION_REPORT.md")

    for _chip_family, _part_path, binary in release_builds():
        digest = binary_digest(binary)
        assert f"SHA256 {digest[:12].upper()}" in app_js
        assert digest in report


def test_release_fingerprint_file_exactly_matches_publishable_binaries():
    expected_lines = [
        f"{binary_digest(binary)}  {binary.relative_to(ROOT).as_posix()}"
        for _chip_family, _part_path, binary in release_builds()
    ]
    assert read_text(FINGERPRINTS).splitlines() == expected_lines


def test_pages_workflow_gates_deploy_on_release_integrity():
    workflow = read_text(ROOT / ".github" / "workflows" / "pages.yml")
    release_integrity_job = workflow.split("  release_integrity:", 1)[1].split("\n  deploy:", 1)[0]
    deploy_job = workflow.split("  deploy:", 1)[1]
    top_level_permissions = workflow.split("concurrency:", 1)[0]

    assert "release_integrity:" in workflow
    assert "permissions:\n  contents: read" in top_level_permissions
    assert "pages: write" not in top_level_permissions
    assert "id-token: write" not in top_level_permissions
    assert "permissions:" not in release_integrity_job
    assert "permissions:\n      contents: read\n      pages: write\n      id-token: write" in deploy_job
    assert "python-version: '3.12'" in workflow
    assert "python -m pip install pytest" in workflow
    assert "python -m pytest tools/tests/test_multi_target_contract.py tools/tests/test_release_integrity.py -q" in workflow
    assert "needs: release_integrity" in workflow


def test_validation_report_records_non_self_referential_v033_release_integrity():
    report = read_text(ROOT / "docs" / "VALIDATION_REPORT.md")

    assert "## Release integrity v0.3.3" in report
    assert "`release_tag: v0.3.3`" in report
    assert "`release_name: iOS ANCS MQTT Bridge v0.3.3`" in report
    assert "`release_title: iOS ANCS MQTT Bridge v0.3.3`" in report
    assert "`checksum_asset_name: release-fingerprints-v0.3.3.sha256`" in report
    assert f"`docs/release-fingerprints-v{VERSION}.sha256`" in report
    assert "Publish-time release metadata verification is pending until the `v0.3.3` GitHub release exists" in report
    assert "Before publishing the checksum asset or declaring release integrity complete" in report
    assert "gh release view v0.3.3 --repo 1bobby-git/ios-ancs --json tagName,name,url,targetCommitish,isDraft,isPrerelease" in report
    assert "intentionally not hardcoded in this report" in report
    assert "python -m pytest tools/tests/test_release_integrity.py -q" in report
    assert "python -m pytest tools/tests -q" in report

    section = report.split("## Release integrity v0.3.3", 1)[1].split("\n## ", 1)[0]
    assert " are verified from this command" not in section
    assert "release integrity complete" in section
    assert "git rev-parse HEAD" not in section
    assert "targetCommitish:" not in section
    assert "release_url:" not in section
    for _chip_family, _part_path, binary in release_builds():
        assert binary.relative_to(ROOT).as_posix() in section


def subprocess_output(*args: str) -> str:
    import subprocess

    return subprocess.check_output(args, cwd=ROOT, text=True, encoding="utf-8")
