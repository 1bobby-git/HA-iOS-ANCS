# Release Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (recommended). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add strict release integrity controls for `v0.3.3` without changing distribution mechanism (GitHub Pages installer + ESP Web Tools manifest) and without broad version-generator refactor.

**Architecture:** Keep runtime installer/build behavior unchanged. Add one authoritative pytest contract test and one CI gate job that validates:

- version drift across source anchors,
- manifest + firmware artifact parity,
- binary existence and SHA-256 prefix proof used by `docs/app.js`,
- release evidence traceability for tag/release creation.

**Tech Stack:** pytest only (single test file), GH CLI, existing firmware build artifacts in `docs/firmware`, and GitHub Pages workflow.

---

## File Structure

- `tools/tests/test_release_integrity.py` (single new file): all release-integrity checks.
- `docs/VALIDATION_REPORT.md` (modify): add concrete `v0.3.3` trace block with hash artifacts and git coordinates.
- `.github/workflows/pages.yml` (modify): add pre-deploy integrity job dependency.
- `docs/app.js` (modify only when the contract test proves a checksum prefix is stale): update build hash prefixes from the verified binaries.
- `docs/manifests/ios-ancs.json`, `docs/manifests/esp32-c6.json`: version/path contract assertion inputs; this release preserves their current paths.
- `tools/tests/__init__.py` remains present and unchanged.

---

## Task 1: Create one complete contract test file (RED/Green)

### Files
- Create: `tools/tests/test_release_integrity.py`
- No separate `test_release_trace.py`; trace is validated by the same test file and report commands in Task 2.

- [ ] **Step 1: Add full failing test implementation for v0.3.3 contract**

Use the exact full content below.

```python
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
REQUIRED_VERSION = "0.3.3"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def find_build_items(manifest_path: Path) -> list[tuple[str, str]]:
    data = json.loads(read_text(manifest_path))
    assert data.get("version") == REQUIRED_VERSION
    builds = data.get("builds")
    assert isinstance(builds, list)
    return [
        (item.get("chipFamily"), part.get("path"))
        for item in builds
        for part in (item.get("parts") or [])
    ]


def test_version_anchor_contract():
    version_markers = {
        ROOT / "CMakeLists.txt": f'set(PROJECT_VER "{REQUIRED_VERSION}")',
        ROOT / "tools" / "build.ps1": "[string]$Version = '{}'".format(REQUIRED_VERSION),
        ROOT / "tools" / "build_matrix.ps1": "[string]$Version = '{}'".format(REQUIRED_VERSION),
        ROOT / "tools" / "build.sh": f'VERSION="${{VERSION:-{REQUIRED_VERSION}}}"',
        ROOT / "docs" / "manifests" / "ios-ancs.json": f'"version": "{REQUIRED_VERSION}"',
        ROOT / "docs" / "manifests" / "esp32-c6.json": f'"version": "{REQUIRED_VERSION}"',
        ROOT / "README.md": f"v{REQUIRED_VERSION}",
        ROOT / "docs" / "index.html": f"v{REQUIRED_VERSION}",
    }

    for path, pattern in version_markers.items():
        content = read_text(path)
        assert pattern in content, f"{path} does not contain required version marker {REQUIRED_VERSION}"


def test_manifest_build_contract():
    ios = ROOT / "docs" / "manifests" / "ios-ancs.json"
    c6 = ROOT / "docs" / "manifests" / "esp32-c6.json"

    ios_items = find_build_items(ios)
    c6_items = find_build_items(c6)
    assert len(ios_items) == 7, "ios-ancs.json must contain 7 build entries"
    assert len({chip for chip, _ in ios_items if chip}) == 7
    assert c6_items and c6_items[0][0] == "ESP32-C6"
    assert len(c6_items) == 1

    for _, relpath in ios_items + c6_items:
        assert relpath is not None
        assert f"-v{REQUIRED_VERSION}.factory.bin" in relpath
        abs_path = (ROOT / "docs" / relpath).resolve()
        assert abs_path.exists(), f"missing firmware artifact: {abs_path}"
        assert abs_path.is_file()


def _iter_manifest_binary_paths(manifest_path: Path):
    data = json.loads(read_text(manifest_path))
    for item in data.get("builds", []):
        for part in item.get("parts", []):
            rel = part.get("path")
            if rel:
                yield (item.get("chipFamily"), (ROOT / "docs" / rel).resolve())


def test_sha256_prefix_proof_contract():
    expected_prefixes = set()
    for _, binary in list(_iter_manifest_binary_paths(ROOT / "docs" / "manifests" / "ios-ancs.json")) + \
            list(_iter_manifest_binary_paths(ROOT / "docs" / "manifests" / "esp32-c6.json")):
        digest = hashlib.sha256(binary.read_bytes()).hexdigest().upper()
        expected_prefixes.add(digest[:12])

    app_js = read_text(ROOT / "docs" / "app.js")
    ui_prefixes = set(re.findall(r"SHA256\\s+([0-9A-Fa-f]{12})", app_js))
    assert not expected_prefixes.isdisjoint(ui_prefixes)
    missing = sorted(expected_prefixes - set(p.upper() for p in ui_prefixes))
    assert not missing, f"Missing SHA-256 prefixes in docs/app.js: {missing}"


def test_release_integrity_report_is_versioned():
    report = ROOT / "docs" / "VALIDATION_REPORT.md"
    content = read_text(report)
    marker = f"## Release Integrity Trace v{REQUIRED_VERSION}"
    assert marker in content

    payload = re.search(
        rf"{re.escape(marker)}\\n([\\s\\S]*?)(\\n## |\\Z)",
        content,
    )
    assert payload, "release integrity trace section not found as expected"
    section = payload.group(1)
    for key in (
        "release_version:",
        "release_tag:",
        "git_commit:",
        "git_tree:",
        "manifest_paths:",
        "artifact_paths:",
        "sha256_full:",
        "sha256_prefix_12:",
        "test_command:",
        "pages_job:",
    ):
        assert key in section

```

- [ ] **Step 2: Run RED**
  - `python -m pytest tools/tests/test_release_integrity.py -q`
  - Expected at least one failure before implementing report section and path alignment changes.

- [ ] **Step 3: Run GREEN**
  - After writing the required report section and workflow/manifest/artifact states, run:
    - `python -m pytest tools/tests/test_release_integrity.py -q`
  - Expected: all tests pass.

---

## Task 2: docs/VALIDATION_REPORT.md trace section (actual v0.3.3 values)

### Files
- Modify: `docs/VALIDATION_REPORT.md`

- [ ] **Step 4: Add concrete v0.3.3 release trace block**

Append this block with actual commands below, then populate values from command output.

```markdown
## Release Integrity Trace v0.3.3

- release_version: 0.3.3
- release_tag: v0.3.3
- git_commit: <`git rev-parse HEAD` output>
- git_tree: <`git rev-parse HEAD^{tree}` output>
- manifest_paths:
  - docs/manifests/ios-ancs.json
  - docs/manifests/esp32-c6.json
- artifact_paths:
  - docs/firmware/esp32/ios-ancs-esp32-v0.3.3.factory.bin
  - docs/firmware/esp32c2/ios-ancs-esp32c2-v0.3.3.factory.bin
  - docs/firmware/esp32c3/ios-ancs-esp32c3-v0.3.3.factory.bin
  - docs/firmware/esp32c5/ios-ancs-esp32c5-v0.3.3.factory.bin
  - docs/firmware/esp32c6/ios-ancs-esp32c6-v0.3.3.factory.bin
  - docs/firmware/esp32c61/ios-ancs-esp32c61-v0.3.3.factory.bin
  - docs/firmware/esp32s3/ios-ancs-esp32s3-v0.3.3.factory.bin
- sha256_full:
  - `<`full hex from docs/release-fingerprints-v0.3.3.sha256`>
- sha256_prefix_12:
  - `<`prefix list from artifacts`>
- build_script_versions:
  - build.ps1: 0.3.3
  - build_matrix.ps1: 0.3.3
  - build.sh: 0.3.3
- test_command: `python -m pytest tools/tests/test_release_integrity.py -q`
- pages_job: `.github/workflows/pages.yml` release-integrity
```

- [ ] **Step 5: Collect immutable digest evidence**
  - `git rev-parse HEAD`
  - `git rev-parse HEAD^{tree}`
  - `Get-ChildItem -Recurse -File docs\\firmware | Where-Object { $_.Name -like "*-v0.3.3.factory.bin" } | Sort-Object FullName | ForEach-Object { "{0} {1}" -f $_.FullName, (Get-FileHash $_.FullName -Algorithm SHA256).Hash }`

- [ ] **Step 6: Create stable checksum file for release artifacts**
  - `python -c "import hashlib,glob,pathlib;from pathlib import Path;from glob import glob; p=Path('docs/release-fingerprints-v0.3.3.sha256'); lines=[]; [lines.append(f'{hashlib.sha256(Path(f).read_bytes()).hexdigest()}  {f}') for f in sorted(glob('docs/firmware/*/*-v0.3.3.factory.bin'))]; p.write_text('\\n'.join(lines)+'\\n', encoding='utf-8')"`
  - Keep `docs/release-fingerprints-v0.3.3.sha256` committed if generated.

---

## Task 3: GitHub Pages workflow gate (single job patch)

### Files
- Modify: `.github/workflows/pages.yml`

- [ ] **Step 7: Add explicit integrity gate**

Use this exact YAML change.

```yaml
jobs:
  release_integrity:
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install test dependencies
        run: |
          python -m pip install --upgrade pip
          if [ -f requirements.txt ]; then
            pip install -r requirements.txt
          fi

      - name: Run release integrity tests
        run: python -m pytest tools/tests/test_release_integrity.py -q

  deploy:
    needs: release_integrity
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    ...
```

- [ ] **Step 8: Verify gate behavior**
  - `python -m pytest tools/tests/test_release_integrity.py -q`
  - Expected: deploy is blocked automatically in CI when drift or checksum proof mismatch exists.

---

## Task 4: Non-force v0.3.3 tag/release path with checksum file + gh verify

### Files
- `docs/VALIDATION_REPORT.md`
- `docs/release-fingerprints-v0.3.3.sha256` (if created)

- [ ] **Step 9: Execute non-force tag/release sequence (explicit)**
  - `git checkout main`
  - `git pull --ff-only`
  - `git status --short`
  - `git tag v0.3.3`
  - `git push origin v0.3.3`
  - `gh release create v0.3.3 --notes-file docs/VALIDATION_REPORT.md --verify-tag`
  - `gh release upload v0.3.3 docs/release-fingerprints-v0.3.3.sha256`
  - `gh release view v0.3.3 --json tagName,name,body,assets --jq '.tagName,.name,.assets[].name'`

- [ ] **Step 10: Verify and attach release evidence**
  - `git log --oneline -1`
  - `git rev-parse v0.3.3`
  - `python -m pytest tools/tests/test_release_integrity.py -q`
  - `gh release view v0.3.3 --json name,tagName,publishedAt,url,resourcesPath,author`

- [ ] **Step 11: Record commit message trailers on implementation commits**
  - Add in final commit messages:
    - `Constraint: Keep release distribution on GitHub Pages and avoid HACS paths`
    - `Rejected: Broad VERSION generator refactor due to multi-file drift risk`
    - `Confidence: medium`
    - `Scope-risk: moderate`
    - `Directive: Keep app.js SHA256 prefix proof synchronized with each firmware binary`
    - `Tested: python -m pytest tools/tests/test_release_integrity.py -q`
    - `Not-tested: full physical flash verification`

---

## Non-goals

- No HACS migration (`hacs.json`, `hacs.yaml`, or HACS publish flow).
- No firmware feature or protocol changes.
- No runtime behavior change of installer flow.
- No broad version/refactor framework changes.

---

## Final verification checklist (required order)
- [ ] `tools/tests/test_release_integrity.py` exists with full assertions and remains the single integrity test file.
- [ ] `python -m pytest tools/tests/test_release_integrity.py -q` passes after report and version anchors are aligned.
- [ ] `docs/VALIDATION_REPORT.md` has `## Release Integrity Trace v0.3.3` with all required fields and concrete values.
- [ ] `.github/workflows/pages.yml` contains `release_integrity` job and `deploy.needs: release_integrity`.
- [ ] `docs/release-fingerprints-v0.3.3.sha256` exists and is attached to the release.
- [ ] `docs/app.js` contains all 12-char SHA-256 prefixes for the 7 manifest artifacts used.
- [ ] GitHub release for v0.3.3 is created without forcing (`git tag`/`gh release`) and verified via `gh release view`.

## Release validation for this plan

- Final state: `python -m pytest tools/tests/test_release_integrity.py -q` passes on local runner and in Pages CI, then `gh release create v0.3.3 ...` can be executed.
- Current HACS status: **not target, no HACS distribution**.
