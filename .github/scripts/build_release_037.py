from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION = "0.3.7"
TARGETS = (
    ("ESP32", "esp32"),
    ("ESP32-C2", "esp32c2"),
    ("ESP32-C3", "esp32c3"),
    ("ESP32-C5", "esp32c5"),
    ("ESP32-C6", "esp32c6"),
    ("ESP32-C61", "esp32c61"),
    ("ESP32-S3", "esp32s3"),
)


def run(*args: str) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, check=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tracked_paths(pattern: str) -> set[str]:
    output = subprocess.check_output(
        ["git", "ls-files", pattern], cwd=ROOT, text=True, encoding="utf-8"
    )
    return {line for line in output.splitlines() if line}


def merge_factory_binary(target: str, build_dir: Path, output: Path) -> None:
    args_path = build_dir / "flasher_args.json"
    data = json.loads(args_path.read_text(encoding="utf-8"))
    chip = str(data["extra_esptool_args"]["chip"])
    settings = data["flash_settings"]
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
    for offset, relative in sorted(
        data["flash_files"].items(), key=lambda item: int(item[0], 0)
    ):
        command.extend((str(offset), str(build_dir / str(relative))))
    run(*command)


def update_release_metadata(digests: dict[str, str]) -> None:
    main_manifest_path = ROOT / "docs/manifests/ios-ancs.json"
    main_manifest = json.loads(main_manifest_path.read_text(encoding="utf-8"))
    main_manifest["version"] = VERSION
    expected_builds = []
    for chip_family, target in TARGETS:
        expected_builds.append(
            {
                "chipFamily": chip_family,
                "parts": [
                    {
                        "path": f"../firmware/{target}/ios-ancs-{target}-v{VERSION}.factory.bin",
                        "offset": 0,
                    }
                ],
            }
        )
    main_manifest["builds"] = expected_builds
    main_manifest_path.write_text(
        json.dumps(main_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    c6_manifest_path = ROOT / "docs/manifests/esp32-c6.json"
    c6_manifest = json.loads(c6_manifest_path.read_text(encoding="utf-8"))
    c6_manifest["version"] = VERSION
    c6_manifest["builds"] = [
        {
            "chipFamily": "ESP32-C6",
            "parts": [
                {
                    "path": f"../firmware/esp32c6/ios-ancs-esp32c6-v{VERSION}.factory.bin",
                    "offset": 0,
                }
            ],
        }
    ]
    c6_manifest_path.write_text(
        json.dumps(c6_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    app_js_path = ROOT / "docs/app.js"
    app_js = app_js_path.read_text(encoding="utf-8")
    for _chip_family, target in TARGETS:
        pattern = re.compile(
            rf'(^  {re.escape(target)}: \{{.*?^    hash: "SHA256 )([0-9A-F]{{12}})(",)',
            flags=re.MULTILINE | re.DOTALL,
        )
        app_js, count = pattern.subn(
            lambda match, digest=digests[target]:
                match.group(1) + digest[:12].upper() + match.group(3),
            app_js,
            count=1,
        )
        if count != 1:
            raise RuntimeError(f"docs/app.js: hash field not found for {target}")
    app_js_path.write_text(app_js, encoding="utf-8", newline="\n")

    index_path = ROOT / "docs/index.html"
    index = index_path.read_text(encoding="utf-8")
    index, count = re.subn(
        r'(<span id="build-hash">SHA256 )[0-9A-F]{12}(</span>)',
        rf"\g<1>{digests['esp32'][:12].upper()}\g<2>",
        index,
        count=1,
    )
    if count != 1:
        raise RuntimeError("docs/index.html: default hash marker not found")
    index_path.write_text(index, encoding="utf-8", newline="\n")

    for old in (ROOT / "docs").glob("release-fingerprints-v*.sha256"):
        old.unlink()
    fingerprint_path = ROOT / f"docs/release-fingerprints-v{VERSION}.sha256"
    fingerprint_path.write_text(
        "\n".join(
            f"{digests[target]}  docs/firmware/{target}/ios-ancs-{target}-v{VERSION}.factory.bin"
            for _chip_family, target in TARGETS
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    old_dependency_lock = ROOT / "dependencies.lock"
    dependency_lock_existed = old_dependency_lock.exists()
    dependency_lock_content = (
        old_dependency_lock.read_bytes() if dependency_lock_existed else None
    )
    tracked_sdkconfigs = tracked_paths("sdkconfig.*")

    firmware_root = ROOT / "docs/firmware"
    for old_binary in firmware_root.glob("*/ios-ancs-*.factory.bin"):
        old_binary.unlink()

    digests: dict[str, str] = {}
    try:
        for _chip_family, target in TARGETS:
            build_dir = ROOT / f"build-{target}"
            if build_dir.exists():
                shutil.rmtree(build_dir)
            sdkconfig = ROOT / f"sdkconfig.{target}"
            if sdkconfig.exists():
                sdkconfig.unlink()

            run(
                "idf.py",
                "-B",
                str(build_dir),
                f"-DIDF_TARGET={target}",
                f"-DSDKCONFIG={sdkconfig}",
                "build",
            )

            output_dir = firmware_root / target
            output_dir.mkdir(parents=True, exist_ok=True)
            output = output_dir / f"ios-ancs-{target}-v{VERSION}.factory.bin"
            merge_factory_binary(target, build_dir, output)
            digests[target] = sha256(output)
            print(
                f"built {target}: {output.stat().st_size} bytes, SHA256 {digests[target]}",
                flush=True,
            )
    finally:
        if dependency_lock_existed and dependency_lock_content is not None:
            old_dependency_lock.write_bytes(dependency_lock_content)
        elif old_dependency_lock.exists():
            old_dependency_lock.unlink()

        for _chip_family, target in TARGETS:
            build_dir = ROOT / f"build-{target}"
            if build_dir.exists():
                shutil.rmtree(build_dir)
            sdkconfig = ROOT / f"sdkconfig.{target}"
            relative = sdkconfig.relative_to(ROOT).as_posix()
            if relative in tracked_sdkconfigs:
                subprocess.run(
                    ["git", "checkout", "--", relative], cwd=ROOT, check=True
                )
            elif sdkconfig.exists():
                sdkconfig.unlink()

    if set(digests) != {target for _chip_family, target in TARGETS}:
        missing = sorted({target for _chip_family, target in TARGETS} - set(digests))
        raise RuntimeError(f"missing firmware builds: {missing}")

    update_release_metadata(digests)
    run(
        "git",
        "add",
        "-A",
        "docs/firmware",
        "docs/manifests",
        "docs/app.js",
        "docs/index.html",
        f"docs/release-fingerprints-v{VERSION}.sha256",
        "docs/release-fingerprints-v0.3.7.sha256",
    )
    run(
        sys.executable,
        "-m",
        "pytest",
        "tools/tests/test_multi_target_contract.py",
        "tools/tests/test_release_integrity.py",
        "-q",
    )


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
