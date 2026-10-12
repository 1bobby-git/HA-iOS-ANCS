#!/usr/bin/env python3
"""Package an already built ESP-IDF application using its actual flasher metadata.

Factory images are for new installations. They can overwrite NVS when flashed
from offset zero. The separate application image is not an automatic USB updater.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

TARGETS = ("esp32", "esp32c2", "esp32c3", "esp32c5", "esp32c6", "esp32c61", "esp32s3")
ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=TARGETS)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build = args.build_dir.resolve()
    output = args.output.resolve()
    config = json.loads((build / "flasher_args.json").read_text())
    project = json.loads((build / "project_description.json").read_text())
    version = project["project_version"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.-]+)?", version):
        raise ValueError("Unexpected project version")
    if config["extra_esptool_args"]["chip"] != args.target:
        raise ValueError("Flasher target does not match requested target")
    flash_files = []
    for offset, relative in config["flash_files"].items():
        path = (build / relative).resolve()
        if not path.is_relative_to(build) or not path.is_file():
            raise ValueError("Invalid built flash image path")
        flash_files += [offset, str(path)]
    output.mkdir(parents=True, exist_ok=True)
    base = f"ios-ancs-{args.target}-v{version}"
    factory = output / f"{base}.factory.bin"
    settings = config["flash_settings"]
    subprocess.run([
        sys.executable, "-m", "esptool", "--chip", args.target, "merge-bin", "-o", str(factory),
        "--flash-mode", settings["flash_mode"], "--flash-size", "4MB",
        "--flash-freq", settings["flash_freq"], *flash_files,
    ], check=True)
    application = (build / project["app_bin"]).resolve()
    elf = (build / project["app_elf"]).resolve()
    for path in (application, elf):
        if not path.is_relative_to(build) or not path.is_file():
            raise ValueError("Missing built application or ELF")
    app_output = output / f"{base}.app.bin"
    app_output.write_bytes(application.read_bytes())
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    evidence = {
        "target": args.target, "version": version, "source_commit": commit,
        "idf_version": project.get("idf_ver"), "factory_file": factory.name,
        "factory_sha256": sha256(factory), "application_file": app_output.name,
        "application_sha256": sha256(app_output), "firmware_elf_sha256": sha256(elf),
        "partition_csv_sha256": sha256(ROOT / "partitions.csv"),
        "hardware_validated": False, "bond_persistence_validated": False,
        "factory_overwrites_nvs": True,
    }
    (output / f"{base}.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
