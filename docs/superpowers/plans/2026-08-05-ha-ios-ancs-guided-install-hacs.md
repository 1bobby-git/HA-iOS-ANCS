# HA-iOS-ANCS Guided Install and HACS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the repository into a Korean-first guided ESP32/iPhone/Home Assistant project, add an optional HACS companion that emits native Home Assistant notification events, rename the GitHub repository to `HA-iOS-ANCS`, and verify the new public installation path.

**Architecture:** Keep firmware MQTT Discovery as the zero-extra-install path. Add one optional `custom_components/ha_ios_ancs` integration that subscribes to the existing notification and availability topics and exposes a single `EventEntity` without duplicating firmware-created sensors or buttons. Keep the browser installer static and preserve its one-selector, one-auto-detect-manifest, checked-in-binary integrity contract while reorganizing its text into a guided sequence.

**Tech Stack:** ESP-IDF 6.0.2, ESP Web Tools 10.4.0-r2, static HTML/CSS/JavaScript, Python 3.12, pytest, Home Assistant custom integration APIs, MQTT, HACS Action, Hassfest, GitHub Pages, GitHub CLI.

---

## File Map

### Documentation and installer

- Modify `README.md`: Korean canonical guide and quick-start path.
- Create `README.en.md`: English guide with the same safety and behavior contracts.
- Modify `docs/index.html`: guided installation content and renamed source/document links.
- Modify `docs/styles.css`: responsive guide, check, result, and troubleshooting layouts.
- Modify `docs/app.js`: preserve board selection behavior and add non-invasive progress affordances only where tested.
- Create `tools/tests/test_documentation_contract.py`: Korean/English/installer content and repository URL contract.
- Modify `tools/tests/test_release_integrity.py`: keep firmware `v0.3.3` anchors while moving the English release sentence to `README.en.md` and updating the renamed repository command.

### Home Assistant companion

- Create `custom_components/ha_ios_ancs/__init__.py`: config-entry setup, runtime start, platform forwarding, and unload.
- Create `custom_components/ha_ios_ancs/const.py`: domain, config keys, topic suffixes, event types, and filter constants.
- Create `custom_components/ha_ios_ancs/config_flow.py`: base-topic validation and duplicate-entry protection.
- Create `custom_components/ha_ios_ancs/notification.py`: pure JSON validation and bounded `relay_id` deduplication.
- Create `custom_components/ha_ios_ancs/runtime.py`: MQTT notification/availability subscriptions and listener lifecycle.
- Create `custom_components/ha_ios_ancs/event.py`: one native `EventEntity` with availability derived from MQTT.
- Create `custom_components/ha_ios_ancs/manifest.json`: Home Assistant and HACS metadata, MQTT dependency, local-push IoT class, version `0.4.0`.
- Create `custom_components/ha_ios_ancs/translations/en.json`: English config-flow and entity strings.
- Create `custom_components/ha_ios_ancs/translations/ko.json`: Korean config-flow and entity strings.
- Create `hacs.json`: HACS display name and minimum Home Assistant version.
- Create `tests/conftest.py`: shared mocks and helpers while importing the real Home Assistant 2026.7.3 APIs.
- Create `tests/test_notification.py`: pure parser/filter/deduplication tests.
- Create `tests/test_config_flow.py`: input validation and duplicate-entry tests.
- Create `tests/test_runtime.py`: MQTT subscription, event emission, availability, and cleanup tests.
- Create `requirements_test.txt`: pinned Home Assistant Core and pytest versions for Python 3.14.

### Validation, branding, and publication

- Create `.github/workflows/validate.yml`: HACS integration validation and Hassfest.
- Create `brand/icon.png`: square integration icon for HACS/Brands submission.
- Modify `docs/VALIDATION_REPORT.md`: renamed GitHub repository command and separate firmware/companion release identities.
- Modify repository description, homepage, and topics through `gh repo edit` after rename.
- Prepare upstream submissions to `home-assistant/brands` and `hacs/default` after the project release passes.

## Task 1: Lock the Documentation and URL Contract

**Files:**
- Create: `tools/tests/test_documentation_contract.py`
- Modify: `tools/tests/test_release_integrity.py`

- [ ] **Step 1: Write the failing documentation contract**

Add tests that require the exact user journey and renamed URLs:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_korean_readme_explains_ancs_and_complete_user_path():
    readme = text("README.md")
    assert "Apple Notification Center Service (ANCS)" in readme
    assert "블루투스(BLE)를 통해 아이폰 등의 iOS 기기 알림" in readme
    assert "iPhone → BLE ANCS → ESP32 → Wi-Fi/MQTT → Home Assistant" in readme
    for heading in ("빠른 설치", "Wi-Fi와 MQTT 설정", "iPhone 등록", "HACS", "문제 해결"):
        assert heading in readme


def test_readmes_and_installer_use_renamed_public_urls():
    combined = "\n".join(text(path) for path in ("README.md", "README.en.md", "docs/index.html"))
    assert "https://github.com/1bobby-git/HA-iOS-ANCS" in combined
    assert "https://1bobby-git.github.io/HA-iOS-ANCS/" in combined
    assert "https://1bobby-git.github.io/ios-ancs/" not in combined


def test_installer_distinguishes_firmware_from_hacs():
    installer = text("docs/index.html")
    assert "웹 설치기는 ESP32 펌웨어를 설치합니다" in installer
    assert "HACS는 Home Assistant 동반 통합을 설치합니다" in installer
    for section_id in ("prepare", "flash", "provision", "pair", "home-assistant", "troubleshooting"):
        assert f'id="{section_id}"' in installer
```

- [ ] **Step 2: Update release-integrity expectations without changing firmware version**

Change the README anchor from `README.md` to `README.en.md`, require the renamed `gh release view` repository, and keep every firmware manifest/build anchor at `0.3.3`.

- [ ] **Step 3: Run the focused tests and confirm the intended failure**

Run:

```powershell
python -m pytest tools/tests/test_documentation_contract.py tools/tests/test_release_integrity.py -q
```

Expected: failures for missing `README.en.md`, missing Korean guide text and section IDs, and old repository URLs; existing binary/hash assertions still pass.

- [ ] **Step 4: Commit the red tests**

Stage only both test files and commit with a Lore message whose `Tested:` trailer records the expected failing command.

## Task 2: Rewrite the Korean and English README Guides

**Files:**
- Modify: `README.md`
- Create: `README.en.md`

- [ ] **Step 1: Preserve and revise the English contract**

Copy the current verified technical content into `README.en.md`, update the repository and Pages URLs, and organize it under these visible headings:

```markdown
# HA-iOS-ANCS
## What ANCS Means
## How It Works
## Supported Boards and Verification Status
## Five-Minute Installation
## Browser Installation
## Wi-Fi and MQTT Provisioning
## iPhone Enrollment
## Home Assistant and HACS
## Normal Operation
## Updating, Resetting, and Replacing a Device
## Troubleshooting
## Privacy and Security
## Build and Verification
```

Keep the exact seven target sizes, MQTT topic contracts, secret-handling rules, `v0.3.3` image statement, and verification commands from the existing README.

- [ ] **Step 2: Replace `README.md` with the Korean canonical guide**

Lead with the required ANCS definition and the exact architecture line. Provide a numbered quick start that links to the public installer, setup AP, `192.168.4.1`, Home Assistant MQTT integration, and iPhone enrollment PIN `123456`. Include one table that separates `빌드 검증`, `실기기 플래시`, `BLE 등록`, and `실제 iPhone 알림 수신` evidence.

- [ ] **Step 3: Run documentation and release tests**

Run:

```powershell
python -m pytest tools/tests/test_documentation_contract.py tools/tests/test_release_integrity.py tools/tests/test_multi_target_contract.py -q
```

Expected: URL tests may still fail only for `docs/index.html`; README content and firmware integrity tests pass.

- [ ] **Step 4: Commit the bilingual guides**

Stage `README.md`, `README.en.md`, and the exact test expectation changes. Record the targeted pytest result in `Tested:`.

## Task 3: Turn the Browser Installer into a Guided Procedure

**Files:**
- Modify: `docs/index.html`
- Modify: `docs/styles.css`
- Modify: `docs/app.js`
- Test: `tools/tests/test_documentation_contract.py`
- Test: `tools/tests/test_multi_target_contract.py`

- [ ] **Step 1: Add the required guide sections without changing installer identity**

Keep exactly one `#board-select`, one `<esp-web-install-button>`, and `manifest="./manifests/ios-ancs.json"`. Add semantic sections with IDs `prepare`, `flash`, `provision`, `pair`, `home-assistant`, and `troubleshooting`. Each action block contains labels equivalent to `할 일`, `성공 확인`, and `문제가 있으면`.

- [ ] **Step 2: Put safety messages next to their actions**

Place the USB data-cable warning before flashing and the full-erase warning next to the install control. State that full erase removes Wi-Fi, MQTT, and BLE bond information. Explain that iPhone/iPad cannot use Web Serial and that HACS does not flash the ESP32.

- [ ] **Step 3: Add responsive guide styles**

Add focused classes:

```css
.procedure-grid { display: grid; gap: 1rem; }
.procedure-card { display: grid; gap: .75rem; }
.procedure-outcome { border-left: 2px solid var(--signal); padding-left: .875rem; }
.procedure-trouble { color: var(--muted); }
@media (min-width: 900px) {
  .procedure-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
```

Use existing color variables and layout containers rather than introducing a second design system.

- [ ] **Step 4: Preserve JavaScript board behavior**

Keep `boards` and `applyBoard(target)` as the only board metadata and render path. Add progress navigation only through DOM anchors; do not add a framework, storage, or network dependency.

- [ ] **Step 5: Run installer contracts**

Run:

```powershell
python -m pytest tools/tests/test_documentation_contract.py tools/tests/test_multi_target_contract.py tools/tests/test_release_integrity.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Verify the static page visually**

Serve `docs/` locally, open desktop and mobile viewport screenshots, verify the install button remains above the first long troubleshooting section, the selector remains usable, and no horizontal overflow appears.

- [ ] **Step 7: Commit the guided installer**

Stage the three `docs` files and installer contract test. Record pytest plus visual viewport checks in the commit trailers.

## Task 4: Implement the Pure Notification Contract with TDD

**Files:**
- Create: `custom_components/ha_ios_ancs/const.py`
- Create: `custom_components/ha_ios_ancs/notification.py`
- Create: `tests/test_notification.py`

- [ ] **Step 1: Write parser and deduplication tests**

Cover valid JSON, malformed JSON, non-object JSON, missing/empty `relay_id`, `complete != true`, `pre_existing == true`, `event == "removed"`, `app_id == "io.robbie.HomeAssistant"`, duplicate relay IDs, and acceptance after bounded eviction.

```python
def test_accepts_one_complete_new_notification():
    seen = RelayIdWindow(limit=2)
    event = parse_notification(
        '{"relay_id":"session:1","complete":true,"pre_existing":false,"event":"added","app_id":"com.apple.MobileSMS"}',
        seen,
    )
    assert event is not None
    assert event["relay_id"] == "session:1"
    assert parse_notification(json.dumps(event), seen) is None
```

- [ ] **Step 2: Run the test and confirm import failure**

Run `python -m pytest tests/test_notification.py -q`.

Expected: collection fails because `custom_components.ha_ios_ancs.notification` does not exist.

- [ ] **Step 3: Implement the minimal pure contract**

Use a `deque[str]` plus `set[str]` with a fixed default limit of `128`. Parse UTF-8 JSON, require a mapping and non-empty string `relay_id`, apply the five filter rules, remember accepted IDs only, and return a copied `dict[str, Any]`.

- [ ] **Step 4: Run pure tests**

Run `python -m pytest tests/test_notification.py -q`.

Expected: all parser and deduplication tests pass without importing Home Assistant.

- [ ] **Step 5: Commit the pure notification boundary**

Stage only the constants, parser, and pure tests.

## Task 5: Add the Home Assistant Config Flow and MQTT Runtime

**Files:**
- Create: `requirements_test.txt`
- Create: `tests/conftest.py`
- Create: `tests/test_config_flow.py`
- Create: `tests/test_runtime.py`
- Create: `custom_components/ha_ios_ancs/__init__.py`
- Create: `custom_components/ha_ios_ancs/config_flow.py`
- Create: `custom_components/ha_ios_ancs/runtime.py`
- Create: `custom_components/ha_ios_ancs/manifest.json`
- Create: `custom_components/ha_ios_ancs/translations/en.json`
- Create: `custom_components/ha_ios_ancs/translations/ko.json`

- [ ] **Step 1: Pin and install the current stable Home Assistant API**

Write:

```text
homeassistant==2026.7.3
pytest>=9.0,<10
```

Use `uv run --python 3.14 --with-requirements requirements_test.txt` so the tests import the real current Home Assistant API without modifying the firmware tool environment. Home Assistant 2026.7.3 requires Python 3.14.2 or newer; do not use the obsolete `pytest-homeassistant-custom-component` package, whose latest PyPI release is pinned to Home Assistant 2024.3.3.

- [ ] **Step 2: Write config-flow tests**

Require `base_topic`, strip surrounding `/`, reject empty values, whitespace, `+`, and `#`, set the normalized topic as the config-entry unique ID, and abort duplicate topics with `already_configured`.

- [ ] **Step 3: Write runtime lifecycle tests**

Patch `homeassistant.components.mqtt.async_subscribe`. Require subscriptions to `<base>/notification` and `<base>/availability`, confirm accepted JSON reaches a registered listener once, confirm `online`/`offline` updates availability, and confirm both unsubscribe callbacks run during unload.

- [ ] **Step 4: Run the HA tests and confirm intended failures**

Run with the real Home Assistant package:

```powershell
uv run --python 3.14 --with-requirements requirements_test.txt python -m pytest tests/test_config_flow.py tests/test_runtime.py -q
```

Expected: imports or config-flow setup fail because the integration files are absent.

- [ ] **Step 5: Implement metadata and config flow**

Use this manifest contract:

```json
{
  "domain": "ha_ios_ancs",
  "name": "HA iOS ANCS",
  "codeowners": ["@1bobby-git"],
  "config_flow": true,
  "dependencies": ["mqtt"],
  "documentation": "https://github.com/1bobby-git/HA-iOS-ANCS",
  "integration_type": "device",
  "iot_class": "local_push",
  "issue_tracker": "https://github.com/1bobby-git/HA-iOS-ANCS/issues",
  "requirements": [],
  "version": "0.4.0"
}
```

Implement a regular `ConfigFlow` so invalid topics return `errors={"base_topic": "invalid_base_topic"}` and duplicates abort through `_abort_if_unique_id_configured()`.

- [ ] **Step 6: Implement runtime start and cleanup**

`AncsMqttRuntime.async_start()` waits for MQTT, subscribes at QoS 1, stores unsubscribe callbacks through the config entry unload lifecycle, parses notification messages with the pure contract, and notifies event listeners. Availability accepts only exact `online` and `offline` payloads.

- [ ] **Step 7: Run config-flow and runtime tests**

Run `uv run --python 3.14 --with-requirements requirements_test.txt python -m pytest tests/test_config_flow.py tests/test_runtime.py tests/test_notification.py -q`.

Expected: all tests pass.

- [ ] **Step 8: Commit the config and MQTT runtime**

Stage the integration metadata/runtime/config files, translations, test harness requirement, and exact tests.

## Task 6: Expose One Native Event Entity

**Files:**
- Create: `custom_components/ha_ios_ancs/event.py`
- Create: `tests/test_event.py`
- Modify: `custom_components/ha_ios_ancs/__init__.py`
- Modify: `custom_components/ha_ios_ancs/translations/en.json`
- Modify: `custom_components/ha_ios_ancs/translations/ko.json`

- [ ] **Step 1: Write the entity behavior tests**

Set up a config entry, capture the runtime listener, deliver one valid notification, and require an `event.ha_ios_ancs_*` state with `event_type == "notification"` and notification attributes. Deliver `offline` and require the same entity to become unavailable. Unload and require its state to be removed.

- [ ] **Step 2: Run the event tests and confirm missing platform failure**

Run `uv run --python 3.14 --with-requirements requirements_test.txt python -m pytest tests/test_event.py -q`.

Expected: the config entry cannot forward the absent `event` platform.

- [ ] **Step 3: Implement `EventEntity`**

Declare `_attr_event_types = ["notification"]`, stable unique ID `<normalized_base_topic>:notification`, and device information keyed by the config entry. On accepted payload call `_trigger_event("notification", payload)` and `async_write_ha_state()`. Availability follows the runtime and listener removal uses `async_on_remove`.

- [ ] **Step 4: Forward and unload the platform**

In `async_setup_entry`, store the runtime in `entry.runtime_data`, start it, and call `hass.config_entries.async_forward_entry_setups(entry, [Platform.EVENT])`. In `async_unload_entry`, call `async_unload_platforms`, then stop the runtime only when platform unload succeeds.

- [ ] **Step 5: Run all companion tests**

Run `uv run --python 3.14 --with-requirements requirements_test.txt python -m pytest tests -q`.

Expected: all notification, config-flow, runtime, and event tests pass.

- [ ] **Step 6: Commit the event entity**

Stage the event platform, setup/unload change, translations, and event tests.

## Task 7: Add HACS Metadata, Brand Asset, and CI Validation

**Files:**
- Create: `hacs.json`
- Create: `brand/icon.png`
- Create: `.github/workflows/validate.yml`
- Modify: `README.md`
- Modify: `README.en.md`
- Test: `tools/tests/test_documentation_contract.py`

- [ ] **Step 1: Add HACS metadata**

Create:

```json
{
  "name": "HA iOS ANCS",
  "homeassistant": "2026.7.0"
}
```

Add the generated HACS repository My Link to both READMEs and state that HACS installs the Home Assistant companion, not ESP32 firmware.

- [ ] **Step 2: Add a square brand asset**

Create a legible, non-Apple-trademark-dependent icon at `brand/icon.png`, verify PNG decoding and equal width/height, and keep source artwork or generation notes in the commit message.

- [ ] **Step 3: Add validation workflow**

Use two least-privilege jobs: `hacs/action@main` with `category: integration`, and `home-assistant/actions/hassfest@master`. Trigger on push, pull request, daily schedule, and manual dispatch with `permissions: {}`.

- [ ] **Step 4: Extend documentation tests**

Require `hacs.json`, the icon, HACS My Link, integration manifest, HACS workflow category, Hassfest action, and no ignored HACS checks.

- [ ] **Step 5: Run local validation**

Run:

```powershell
uv run --python 3.14 --with-requirements requirements_test.txt python -m pytest tests -q
python -m pytest tools/tests -q
python -m json.tool hacs.json > $null
python -m json.tool custom_components/ha_ios_ancs/manifest.json > $null
```

Expected: all tests and JSON parsing pass.

- [ ] **Step 6: Commit HACS publication metadata**

Stage metadata, workflow, icon, docs, and tests.

## Task 8: Prepare the Repository Rename Without Renaming Product Contracts

**Files:**
- Modify: `docs/VALIDATION_REPORT.md`
- Modify: `tools/tests/test_release_integrity.py`
- Modify: repository URLs found by `rg`

- [ ] **Step 1: Replace repository-only URL references**

Change `github.com/1bobby-git/ios-ancs` and `1bobby-git.github.io/ios-ancs` references to the new slug. Keep firmware filenames, MQTT base-topic examples, manifest filenames, component names, and protocol identifiers containing lowercase `ios-ancs` unchanged.

- [ ] **Step 2: Audit remaining occurrences**

Run:

```powershell
rg -n "github\.com/1bobby-git/ios-ancs|1bobby-git\.github\.io/ios-ancs|--repo 1bobby-git/ios-ancs" -g '!docs/superpowers/**' .
```

Expected: no results.

- [ ] **Step 3: Run repository-wide tests**

Run:

```powershell
python -m pytest tools/tests -q
uv run --python 3.14 --with-requirements requirements_test.txt python -m pytest tests -q
git diff --check
```

Expected: all tests pass and no whitespace errors are reported.

- [ ] **Step 4: Commit rename preparation**

Stage only URL, validation-report, and test changes. Record that the GitHub repository is not renamed yet in `Not-tested:`.

## Task 9: Push, Rename, Redeploy, and Live-Verify

**Files:**
- External GitHub repository settings and Pages deployment.
- Local `.git/config` remote URL through `git remote set-url`.

- [ ] **Step 1: Rebase-safe sync and push**

Fetch `origin`, confirm the working tree is clean, confirm `main` contains only the intended commits, run the full test suite again, then push `main` to `1bobby-git/ios-ancs`.

- [ ] **Step 2: Rename the GitHub repository**

Run:

```powershell
gh api --method PATCH repos/1bobby-git/ios-ancs -f name=HA-iOS-ANCS
git remote set-url origin https://github.com/1bobby-git/HA-iOS-ANCS.git
```

Verify `gh repo view 1bobby-git/HA-iOS-ANCS --json nameWithOwner,url,defaultBranchRef` reports the new owner/name and `main`.

- [ ] **Step 3: Update public repository metadata**

Set the description to identify the ESP32 ANCS-to-MQTT bridge and optional Home Assistant companion, set homepage to `https://1bobby-git.github.io/HA-iOS-ANCS/`, and add `hacs` and `custom-integration` while retaining `ancs`, `esp32`, `esp32-c6`, `home-assistant`, `mqtt`, and `web-serial`.

- [ ] **Step 4: Trigger and wait for Pages**

Dispatch the Pages workflow if the rename did not trigger it. Wait for the latest run to complete successfully and do not claim deployment from workflow creation alone.

- [ ] **Step 5: Verify the public chain**

Check the new Pages HTML, `docs/manifests/ios-ancs.json` relative endpoint, every factory image, repository source links, README links, and HACS My Link. Download every manifest image and compare SHA-256 with `docs/release-fingerprints-v0.3.3.sha256`.

- [ ] **Step 6: Record fresh evidence**

Update `docs/VALIDATION_REPORT.md` only with facts from the completed run, commit, push, and re-run Pages integrity checks if that file affects deployment.

## Task 10: Publish the Companion and Submit HACS Visibility Work

**Files:**
- GitHub release `v0.4.0`.
- Upstream pull requests to `home-assistant/brands` and `hacs/default`.

- [ ] **Step 1: Verify CI on the release commit**

Require successful Pages, HACS Action, and Hassfest runs for the exact `main` SHA. Confirm the local companion tests and repository-wide tests pass on the same SHA.

- [ ] **Step 2: Publish the full GitHub release**

Create `v0.4.0` with release notes that separate companion version `0.4.0` from firmware images `0.3.3`. Attach no regenerated firmware unless the checked-in images and release-integrity evidence require it.

- [ ] **Step 3: Validate HACS custom-repository installation metadata**

Confirm the release exposes `custom_components/ha_ios_ancs`, `hacs.json`, valid manifest version `0.4.0`, and public documentation. Record custom-repository readiness separately from default-store visibility.

- [ ] **Step 4: Submit the Brands contribution**

Fork `home-assistant/brands`, add the `ha_ios_ancs` icon structure required by the current repository contract, run its required checks, push a dedicated branch, and open a PR that links the released integration.

- [ ] **Step 5: Submit the HACS default-store contribution when prerequisites pass**

Fork `hacs/default`, branch from current `master`, add `1bobby-git/HA-iOS-ANCS` alphabetically under `integration`, run repository checks, and open an editable PR using the full template. If Brands acceptance is a hard prerequisite at submission time, keep the prepared branch unsubmitted until the Brands check can pass.

- [ ] **Step 6: Report external review states accurately**

Report the GitHub release and custom-repository readiness as complete only when verified. Report Brands and HACS default visibility as `pending` until their upstream PRs merge and HACS scheduled ingestion completes.
