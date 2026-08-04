# Release Integrity Plan (Non-HACS, Pages-first)

> **Scope:** `docs/plans/2026-08-04-release-integrity-design.md` is the design memo; implementation detail and checklist tasks are in `docs/superpowers/plans/2026-08-04-release-integrity.md`.

**Goal:** Preserve current behavior (GitHub Pages web installer) while adding release-integrity safeguards for `v0.3.3` that prevent version drift, verify binary/checksum consistency, and preserve commit traceability.

**Constraint:** The project is **not HACS-related**. Firmware distribution remains browser-based via ESP Web Tools manifest and GitHub Pages.

## Proposed scope
- Add small, explicit validation layers (tests + check scripts) instead of a broad `VERSION` generator refactor.
- Keep installer behavior unchanged:
  - `docs/index.html`
  - `docs/manifests/ios-ancs.json`
  - `docs/manifests/esp32-c6.json`
  - Pages workflow publish in `.github/workflows/pages.yml`

## Required design artifacts
1. Release contract test file to stop drift before publish.
2. Release integrity documentation section in `docs/VALIDATION_REPORT.md` (commit and artifact traceability).
3. Release tagging/release flow with explicit notes including hash proof and commit SHA.
4. CI gate so validation runs before installer publication.

## version drift contract
- `CMakeLists.txt` (`PROJECT_VER`) must equal release version marker.
- `tools/build.ps1`, `tools/build.sh`, `tools/build_matrix.ps1` must expose the same release marker.
- `docs/manifests/ios-ancs.json` and `docs/manifests/esp32-c6.json` must use the same marker.
- README, installer UI proof, and runtime docs should not advertise a different marker.

## checksum + artifact contract
- For each manifest `part.path`, validate that:
  - file exists,
  - filename contains `-v${release}.factory.bin`,
  - SHA-256 is stable and at least one digest prefix appears in `docs/app.js` build-proof strings,
  - all seven targets are published.

## commit traceability
- Every integrity pass records:
  - `release_version`, `release_tag`, `release_commit`, `release_tree`,
  - manifest path/name/version,
  - binary full path and SHA-256,
  - pages deploy artifact ID (or run URL).
- Release notes must refer to this single traceability section.
