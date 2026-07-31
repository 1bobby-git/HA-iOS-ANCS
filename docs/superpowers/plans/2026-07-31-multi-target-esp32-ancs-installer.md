# Multi-target ESP32 ANCS Installer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and publish target-specific ANCS relay firmware for compatible ESP32 families behind one compact, auto-detecting browser installer while preserving the complete Home Assistant sensor attribute schema.

**Architecture:** A header-only platform identity component replaces C6 literals at compile time. Isolated ESP-IDF builds generate one merged image per passing target, and one ESP Web Tools manifest maps detected chip families to those images. The installer selector changes only the displayed model details; ESP Web Tools remains responsible for safe chip detection.

**Tech Stack:** ESP-IDF 6.0.2, Bluedroid GATTC/GATTS, Python pytest contract tests, PowerShell build orchestration, esptool, ESP Web Tools 10, static HTML/CSS/JavaScript, GitHub Pages Actions.

---

### Task 1: Lock the multi-target and Home Assistant contracts

**Files:**
- Create: `tools/tests/test_multi_target_contract.py`
- Modify: `tools/tests/test_mqtt_contract.py`
- Modify: `tools/tests/test_portal_contract.py`

- [ ] **Step 1: Write failing tests for the supported target map**

Add assertions that require a platform identity header to map `esp32`, `esp32c2`,
`esp32c3`, `esp32c5`, `esp32c6`, `esp32c61`, and `esp32s3` to stable device
labels, dynamic target/source macros, and target-appropriate BOOT defaults.

- [ ] **Step 2: Write failing tests for the complete sensor attributes**

Parse the notification JSON construction contract and require every key listed
in the design specification. Require Discovery to use:

```json
{
  "value_template": "{{ value_json.relay_id }}",
  "json_attributes_topic": "<base>/notification"
}
```

- [ ] **Step 3: Write failing tests for dynamic portal defaults**

Require the portal status JSON to expose `target` and `device_family`, and
require the JavaScript helpers to derive Bluetooth name, MQTT client ID, and
base topic from those fields rather than a C6 literal.

- [ ] **Step 4: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tools/tests/test_multi_target_contract.py tools/tests/test_mqtt_contract.py tools/tests/test_portal_contract.py -q
```

Expected: failures for the missing platform identity component and remaining
C6-specific literals.

### Task 2: Introduce compile-time platform identity

**Files:**
- Create: `components/platform_identity/CMakeLists.txt`
- Create: `components/platform_identity/include/platform_identity.h`
- Modify: `components/notification_sink/CMakeLists.txt`
- Modify: `components/notification_sink/notification_sink_serial.c`
- Modify: `components/mqtt_relay/CMakeLists.txt`
- Modify: `components/mqtt_relay/mqtt_payload.c`
- Modify: `components/ancs_client/CMakeLists.txt`
- Modify: `components/ancs_client/ancs_client.c`
- Modify: `components/ancs_client/Kconfig`

- [ ] **Step 1: Define target, source, family, and BOOT mappings**

Expose compile-time string macros:

```c
#define ANCS_TARGET_ID CONFIG_IDF_TARGET
#define ANCS_SOURCE_ID CONFIG_IDF_TARGET "_ancs"
#define ANCS_DEVICE_FAMILY "C6"
```

Select `ANCS_DEVICE_FAMILY` by `CONFIG_IDF_TARGET_*` and fail compilation for an
unsupported target.

- [ ] **Step 2: Replace C6 JSON and BLE literals**

Use `ANCS_TARGET_ID` in notification/state JSON, `ANCS_SOURCE_ID` in MQTT
notifications, and `ANCS_DEVICE_FAMILY` in
`IOS-ANCS-<family>-<MAC4>`.

- [ ] **Step 3: Make the BOOT GPIO target-aware**

Set Kconfig defaults to GPIO0 for ESP32/S3, GPIO28 for C5, and GPIO9 for the
remaining supported RISC-V targets while preserving a user override.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
python -m pytest tools/tests/test_multi_target_contract.py tools/tests/test_mqtt_contract.py -q
```

Expected: all selected tests pass.

### Task 3: Make provisioning portal identity target-aware

**Files:**
- Modify: `components/portal_http/CMakeLists.txt`
- Modify: `components/portal_http/portal_http.c`
- Modify: `components/portal_http/portal.js`
- Modify: `tools/tests/test_portal_contract.py`

- [ ] **Step 1: Add target identity to status JSON**

Return:

```json
{
  "target": "esp32c6",
  "device_family": "C6"
}
```

without exposing stored passwords or certificates.

- [ ] **Step 2: Derive portal defaults from status identity**

Generate:

```text
IOS-ANCS-<family>-<suffix>
ios_ancs_<target>_<suffix>
ios-ancs/<target>-<suffix>
```

while preserving an already stored client ID or base topic.

- [ ] **Step 3: Verify portal tests**

Run:

```powershell
python -m pytest tools/tests/test_portal_contract.py -q
```

Expected: all portal tests pass.

### Task 4: Build isolated target variants

**Files:**
- Create: `tools/build_matrix.ps1`
- Create: `tools/merge_firmware.ps1`
- Modify: `sdkconfig.defaults`
- Modify: `.gitignore`
- Modify: `tools/tests/test_multi_target_contract.py`

- [ ] **Step 1: Remove the fixed target and 8 MB requirement**

Keep Bluetooth, TLS, partition, and runtime defaults in `sdkconfig.defaults`,
but select each target and a 4 MB flash baseline through the matrix command.

- [ ] **Step 2: Implement isolated build orchestration**

For each candidate target, configure:

```powershell
idf.py -B "build-$Target" -D "IDF_TARGET=$Target" `
  -D "SDKCONFIG=sdkconfig.$Target" build
```

Record success, failure, app size, partition headroom, binary path, and SHA-256.

- [ ] **Step 3: Merge passing factory images**

Use each target build's `flasher_args.json` to obtain flash mode, frequency,
size, offsets, and component paths. Write versioned merged images under
`docs/firmware/<target>/`.

- [ ] **Step 4: Run all candidate builds**

Run:

```powershell
.\tools\build_matrix.ps1
```

Expected: every published target completes; any failing candidate is omitted
from the manifest and named in the build report.

### Task 5: Replace board cards with one safe installer

**Files:**
- Create: `docs/manifests/ios-ancs.json`
- Modify: `docs/index.html`
- Modify: `docs/styles.css`
- Modify: `docs/app.js`
- Delete: `docs/manifests/esp32-c6.json`
- Modify: `tools/tests/test_multi_target_contract.py`

- [ ] **Step 1: Generate one multi-build manifest**

Add one build entry per passing target:

```json
{
  "chipFamily": "ESP32-C6",
  "parts": [
    {
      "path": "../firmware/esp32c6/ios-ancs-esp32c6-v0.2.0.factory.bin",
      "offset": 0
    }
  ]
}
```

- [ ] **Step 2: Implement one selector and one install button**

The selector updates the target detail panel. The install button always points
to `./manifests/ios-ancs.json`, allowing ESP Web Tools to select the connected
chip safely.

- [ ] **Step 3: Show validation levels honestly**

Display `hardware verified` for ESP32-C6 and `build verified` for other passing
targets. Do not display failed or excluded targets as installable.

- [ ] **Step 4: Verify manifest and DOM contracts**

Run:

```powershell
python -m pytest tools/tests/test_multi_target_contract.py -q
```

Expected: one selector, one install element, unique chip families, valid paths,
and all referenced binaries present.

### Task 6: Generalize documentation and Home Assistant guidance

**Files:**
- Modify: `README.md`
- Modify: `homeassistant/automation_ios_ancs_c6_relay.yaml`
- Modify: `docs/IOS_PAIRING.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/VALIDATION_REPORT.md`

- [ ] **Step 1: Document target-aware sensor attributes**

State that C6 keeps `target=esp32c6` and `source=esp32c6_ancs`, while other
variants use their ESP-IDF target name with the same full attribute schema.

- [ ] **Step 2: Make Home Assistant automation entity selection portable**

Document that the discovered entity ID depends on the configured client ID and
preserve the `[C6→HA]` echo boundary for the deployed C6 automation.

- [ ] **Step 3: Document flash and validation levels**

List the 4 MB minimum, supported targets, excluded target reasons, BOOT-button
variation, and the difference between build validation and physical validation.

### Task 7: Full verification and deployment

**Files:**
- Modify: `.github/workflows/pages.yml` only if the published Pages artifact path changes

- [ ] **Step 1: Run the full host suite**

Run:

```powershell
python -m pytest tools/tests -q
```

Expected: all tests pass.

- [ ] **Step 2: Validate all merged images and manifest responses locally**

Require each manifest path to return HTTP 200 with the expected content length
and require esptool image inspection to match the target.

- [ ] **Step 3: Browser-test desktop and mobile layouts**

Verify one model selector, one install button, secure context, Web Serial
support, no horizontal overflow, and zero console errors.

- [ ] **Step 4: Commit and push**

Commit with the Lore trailers, push `main`, and confirm local HEAD equals
`origin/main`.

- [ ] **Step 5: Verify GitHub Pages**

Wait for the Pages workflow to succeed, then verify the live page, unified
manifest, and every referenced binary over HTTPS.
