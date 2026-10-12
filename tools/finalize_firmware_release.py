#!/usr/bin/env python3
"""Verify seven build artifacts and atomically stage the existing installer layout."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

TARGETS = ("esp32", "esp32c2", "esp32c3", "esp32c5", "esp32c6", "esp32c61", "esp32s3")
ROOT = Path(__file__).resolve().parents[1]

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    version = json.loads((ROOT / "docs/manifests/ios-ancs.json").read_text())["version"]
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_commit):
        raise ValueError("Full source commit is required")
    checked = []
    for target in TARGETS:
        stem = f"ios-ancs-{target}-v{version}"
        records = list(args.artifacts.rglob(f"{stem}.json"))
        if len(records) != 1:
            raise ValueError(f"Expected one metadata file for {target}")
        metadata = json.loads(records[0].read_text())
        parent = records[0].parent
        factory, app = parent / f"{stem}.factory.bin", parent / f"{stem}.app.bin"
        for key, expected in {"version": version, "target": target, "source_commit": args.source_commit,
            "factory_file": factory.name, "application_file": app.name,
            "factory_sha256": digest(factory), "application_sha256": digest(app)}.items():
            if metadata.get(key) != expected:
                raise ValueError(f"{target}: {key} mismatch")
        # ESP image header + first segment header precede esp_app_desc_t.
        image = app.read_bytes()
        if image[32:36] != bytes.fromhex("3254cdab") or image[176:208].hex() != metadata["firmware_elf_sha256"]:
            raise ValueError(f"{target}: running-image ELF fingerprint mismatch")
        checked.append((target, factory, metadata))
    fingerprints = []
    app_js = (ROOT / "docs/app.js").read_text()
    readmes = {name: (ROOT / name).read_text() for name in ("README.md", "README.en.md")}
    for target, factory, metadata in checked:
        destination = ROOT / "docs/firmware" / target / factory.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        for old in destination.parent.glob(f"ios-ancs-{target}-v*.factory.bin"):
            if old != destination:
                old.unlink()
        shutil.copyfile(factory, destination)
        value = metadata["factory_sha256"]
        fingerprints.append(f"{value}  {destination.relative_to(ROOT).as_posix()}")
        pattern = rf'(  {target}: \{{.*?hash: ")SHA256 [A-F0-9]+(".*?\n  \}})'
        app_js, count = re.subn(pattern, lambda m:m[1]+f"SHA256 {value[:12].upper()}"+m[2], app_js, count=1, flags=re.S)
        if count != 1:
            raise ValueError(f"Installer target missing: {target}")
        for name, text in readmes.items():
            state = "빌드 검증 · 이 버전 실기기 미검증" if name == "README.md" else "Build verified; this version not hardware validated"
            pattern = rf'^(\| `{target}` \| [^|]+ \| )[^|]+\|[^\n]+$'
            text, count = re.subn(pattern, lambda m:m[1]+f"{factory.stat().st_size:,} bytes | {state} |", text, count=1, flags=re.M)
            if count != 1:
                raise ValueError(f"README target missing: {name}/{target}")
            readmes[name] = text
    (ROOT / "docs/app.js").write_text(app_js)
    for name, text in readmes.items():
        (ROOT / name).write_text(text)
    index = ROOT / "docs/index.html"
    index.write_text(re.sub(r'(<span id="build-hash">)SHA256 [A-F0-9]+(</span>)',
        lambda m:m[1]+f"SHA256 {checked[0][2]['factory_sha256'][:12].upper()}"+m[2], index.read_text(), count=1))
    (ROOT / f"docs/release-fingerprints-v{version}.sha256").write_text("\n".join(fingerprints)+"\n")
    (ROOT / f"docs/release-builds-v{version}.json").write_text(json.dumps(
        {"version": version, "source_commit": args.source_commit,
         "builds": [metadata for _,_,metadata in checked]}, indent=2)+"\n")
    print(f"Verified {len(checked)} factory/app image pairs, source {args.source_commit}")

if __name__ == "__main__":
    main()
