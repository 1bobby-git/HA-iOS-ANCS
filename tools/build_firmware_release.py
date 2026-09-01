from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

VERSION = "0.3.5"
TARGETS = (
    ("ESP32", "esp32"),
    ("ESP32-C2", "esp32c2"),
    ("ESP32-C3", "esp32c3"),
    ("ESP32-C5", "esp32c5"),
    ("ESP32-C6", "esp32c6"),
    ("ESP32-C61", "esp32c61"),
    ("ESP32-S3", "esp32s3"),
)

ROOT = Path.cwd()
RELEASE_ROOT = Path("/tmp/ios-ancs-release")


def run(command: list[str]) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def replace_once(path: Path, pattern: str, replacement: str, *, flags: int = 0) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"unable to update {path}: {pattern}")
    path.write_text(updated, encoding="utf-8")


def build_factory_images() -> dict[str, str]:
    lock_path = ROOT / "dependencies.lock"
    original_lock = lock_path.read_bytes() if lock_path.exists() else None
    shutil.rmtree(RELEASE_ROOT, ignore_errors=True)
    RELEASE_ROOT.mkdir(parents=True)
    digests: dict[str, str] = {}

    try:
        for _family, target in TARGETS:
            build_dir = ROOT / f"build-{target}"
            sdkconfig = ROOT / f"sdkconfig.{target}"
            shutil.rmtree(build_dir, ignore_errors=True)
            sdkconfig.unlink(missing_ok=True)
            run(
                [
                    "idf.py",
                    f"-B{build_dir}",
                    f"-DIDF_TARGET={target}",
                    f"-DSDKCONFIG={sdkconfig}",
                    "build",
                ]
            )

            flasher = json.loads(
                (build_dir / "flasher_args.json").read_text(encoding="utf-8")
            )
            chip = str(flasher["extra_esptool_args"]["chip"])
            settings = flasher["flash_settings"]
            output = RELEASE_ROOT / f"ios-ancs-{target}-v{VERSION}.factory.bin"
            command = [
                sys.executable,
                "-m",
                "esptool",
                "--chip",
                chip,
                "merge-bin",
                "-o",
                str(output),
                "--flash-mode",
                str(settings["flash_mode"]),
                "--flash-size",
                "4MB",
                "--flash-freq",
                str(settings["flash_freq"]),
            ]
            for offset, filename in flasher["flash_files"].items():
                command.extend([str(offset), str(build_dir / filename)])
            run(command)
            digests[target] = hashlib.sha256(output.read_bytes()).hexdigest()
    finally:
        if original_lock is None:
            lock_path.unlink(missing_ok=True)
        else:
            lock_path.write_bytes(original_lock)

    return digests


def publish_installer_files(digests: dict[str, str]) -> None:
    firmware_root = ROOT / "docs" / "firmware"
    shutil.rmtree(firmware_root, ignore_errors=True)
    for _family, target in TARGETS:
        destination = firmware_root / target
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            RELEASE_ROOT / f"ios-ancs-{target}-v{VERSION}.factory.bin",
            destination / f"ios-ancs-{target}-v{VERSION}.factory.bin",
        )

    app_js_path = ROOT / "docs" / "app.js"
    app_js = app_js_path.read_text(encoding="utf-8")
    for _family, target in TARGETS:
        pattern = rf'({target}: \{{.*?hash: "SHA256 )[A-F0-9]{{12}}(")'
        app_js, count = re.subn(
            pattern,
            rf"\g<1>{digests[target][:12].upper()}\g<2>",
            app_js,
            count=1,
            flags=re.S,
        )
        if count != 1:
            raise RuntimeError(f"unable to update installer hash for {target}")
    app_js_path.write_text(app_js, encoding="utf-8")

    replace_once(
        ROOT / "docs" / "index.html",
        r'(<span id="build-hash">SHA256 )[A-F0-9]{12}(</span>)',
        rf"\g<1>{digests['esp32'][:12].upper()}\g<2>",
    )
    replace_once(
        ROOT / "tools" / "tests" / "test_release_integrity.py",
        r'(<span id="build-hash">SHA256 )[A-F0-9]{12}(</span>)',
        rf"\g<1>{digests['esp32'][:12].upper()}\g<2>",
    )

    for fingerprint in (ROOT / "docs").glob("release-fingerprints-v*.sha256"):
        fingerprint.unlink()
    (ROOT / f"docs/release-fingerprints-v{VERSION}.sha256").write_text(
        "\n".join(
            f"{digests[target]}  docs/firmware/{target}/ios-ancs-{target}-v{VERSION}.factory.bin"
            for _family, target in TARGETS
        )
        + "\n",
        encoding="utf-8",
    )


def validate_release_surfaces() -> None:
    for manifest_path in (
        ROOT / "docs" / "manifests" / "ios-ancs.json",
        ROOT / "docs" / "manifests" / "esp32-c6.json",
    ):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("version") != VERSION:
            raise RuntimeError(f"unexpected installer version in {manifest_path}")
        for build in manifest.get("builds", []):
            for part in build.get("parts", []):
                if f"v{VERSION}.factory.bin" not in part["path"]:
                    raise RuntimeError(
                        f"stale firmware path in {manifest_path}: {part['path']}"
                    )

    manifest = json.loads(
        (ROOT / "custom_components/ha_ios_ancs/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    if manifest.get("version") != "0.6.7":
        raise RuntimeError("Home Assistant integration version must remain 0.6.7")


if __name__ == "__main__":
    release_digests = build_factory_images()
    publish_installer_files(release_digests)
    validate_release_surfaces()
    for _family, target in TARGETS:
        print(f"{target}: {release_digests[target]}")
