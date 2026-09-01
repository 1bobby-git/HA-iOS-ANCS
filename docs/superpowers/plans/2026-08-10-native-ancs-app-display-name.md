# Native ANCS App Display Name Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve localized iOS app names through native ANCS, retain safe firmware fallbacks, remove the Home Assistant `published_at_ms` sensor, and publish aligned firmware/HACS releases.

> **Follow-up decision:** The user subsequently removed the companion
> `received_at_ms` sensor as well. MQTT payload fields and MQTT-owned entities
> remain untouched. This follow-up uses config-entry version `4` and companion
> version `0.6.4`; any later step in this historical plan that says
> `received_at_ms` remains or names companion `0.6.3` is superseded.

**Architecture:** Add a fragmented Get App Attributes parser to `ancs_protocol`, a bounded session resolver component for app-name cache decisions, and a two-stage request state in `ancs_client`. Carry native names on `ancs_notification_t`, let the MQTT serializer apply the existing static map only when the native name is empty, and migrate only the deprecated companion sensor out of Home Assistant's entity registry.

**Tech Stack:** ESP-IDF 6.0.2, C11, Unity, Home Assistant Python integration, pytest, MQTT JSON, GitHub Actions, HACS, ESP Web Tools.

---

## File Map

- `components/ancs_protocol/include/ancs_protocol.h`: public command, parser, limits, and notification app-name fields.
- `components/ancs_protocol/ancs_protocol.c`: Get App Attributes request builder and fragmented response parser.
- `components/ancs_protocol/Kconfig`: bounded display-name size.
- `test/test_ancs_data_parser.c`: command bytes and response parser regression coverage.
- `components/ancs_app_resolver/include/ancs_app_resolver.h`: session resolver API and bounded cache types.
- `components/ancs_app_resolver/ancs_app_resolver.c`: cache lookup, LRU replacement, native completion, and fallback decisions.
- `components/ancs_app_resolver/CMakeLists.txt`, `components/ancs_app_resolver/Kconfig`: ESP-IDF component definition and cache capacity.
- `components/ancs_app_resolver/test/test_ancs_app_resolver.c`: first lookup, cache hit, failure, reset, and LRU tests.
- `components/ancs_client/ancs_client.c`: two-stage Control Point orchestration and enrichment-specific recovery.
- `components/ancs_client/CMakeLists.txt`: resolver dependency.
- `sdkconfig.defaults`: explicit app-name and resolver cache bounds.
- `test_app/CMakeLists.txt`, `test_app/main/CMakeLists.txt`: include the resolver and its Unity tests.
- `components/mqtt_relay/mqtt_payload.c`: native-name precedence and static fallback.
- `components/mqtt_relay/test/test_mqtt_payload.c`: payload precedence regressions.
- `components/notification_sink/notification_sink_serial.c`, `test/test_json_output.c`: expose app-name truncation evidence without duplicating `app_name`.
- `custom_components/ha_ios_ancs/sensor.py`: remove only the dedicated `published_at_ms` sensor.
- `custom_components/ha_ios_ancs/__init__.py`, `custom_components/ha_ios_ancs/const.py`: config-entry migration and exact registry cleanup.
- `custom_components/ha_ios_ancs/strings.json`, `custom_components/ha_ios_ancs/translations/en.json`, `custom_components/ha_ios_ancs/translations/ko.json`: remove the deprecated sensor name.
- `tests/test_sensor.py`, `tests/test_config_flow.py`, `tests/test_init.py`: entity count, translation, migration, and MQTT non-interference regressions.
- `tools/tests/test_documentation_contract.py`, `tools/tests/test_multi_target_contract.py`, `tools/tests/test_release_integrity.py`: version and release/publication contracts.
- `.github/workflows/pages.yml`: stage public docs while excluding internal `docs/superpowers` files.
- `CMakeLists.txt`, `tools/build.ps1`, `tools/build.sh`, `tools/build_matrix.ps1`: firmware version `0.3.6`.
- `custom_components/ha_ios_ancs/manifest.json`: HACS integration version `0.6.3`.
- `README.md`, `README.en.md`, `docs/index.html`, `docs/app.js`, `docs/manifests/*.json`: release documentation and installer pointers.
- `docs/firmware/*/*.factory.bin`, `docs/release-fingerprints-v0.3.6.sha256`: rebuilt release artifacts and hashes.

### Task 1: Keep Internal Plans Out of GitHub Pages

**Files:**
- Modify: `tools/tests/test_release_integrity.py:117-133`
- Modify: `.github/workflows/pages.yml:43-49`

- [ ] **Step 1: Write the failing publication-boundary test**

Replace the tracked-file prohibition with a deploy-artifact assertion that permits committed implementation records while keeping them off the public site:

```python
def test_pages_workflow_excludes_internal_plans_from_public_artifact():
    workflow = read_text(ROOT / ".github" / "workflows" / "pages.yml")

    assert "mkdir -p pages-site" in workflow
    assert "rsync -a --delete --exclude 'superpowers/' docs/ pages-site/" in workflow
    assert "path: pages-site" in workflow
    assert "path: docs" not in workflow
```

Keep the existing assertion that `docs/plans/` and the superseded vendor bundle are not tracked, but remove only the assertion rejecting `docs/superpowers/`.

- [ ] **Step 2: Run the boundary test and verify RED**

Run: `python -m pytest tools/tests/test_release_integrity.py::test_pages_workflow_excludes_internal_plans_from_public_artifact -q`

Expected: FAIL because `pages.yml` still uploads `docs` directly.

- [ ] **Step 3: Stage the Pages artifact without internal plans**

Insert before `Upload installer artifact`:

```yaml
      - name: Prepare public installer artifact
        run: |
          mkdir -p pages-site
          rsync -a --delete --exclude 'superpowers/' docs/ pages-site/

      - name: Upload installer artifact
        uses: actions/upload-pages-artifact@v4
        with:
          path: pages-site
```

- [ ] **Step 4: Run the boundary and workflow contract tests**

Run: `python -m pytest tools/tests/test_release_integrity.py tools/tests/test_documentation_contract.py -q`

Expected: PASS with no internal planning path exposed by the upload step.

- [ ] **Step 5: Commit the boundary**

Commit intent: `Keep implementation records out of the public installer`

Trailers: `Constraint: GitHub Pages must publish firmware documentation only`, `Tested: release integrity and documentation contract tests`.

### Task 2: Add Native Get App Attributes Protocol Support

**Files:**
- Modify: `components/ancs_protocol/include/ancs_protocol.h:7-137`
- Modify: `components/ancs_protocol/ancs_protocol.c:1-390`
- Modify: `components/ancs_protocol/Kconfig:1-30`
- Modify: `test/test_ancs_data_parser.c:1-310`

- [ ] **Step 1: Add failing request and fragmented parser tests**

Add helpers that construct `CommandID=1`, a null-terminated App Identifier, and one Display Name tuple. Add tests with these exact expectations:

```c
TEST_CASE("app attribute request asks only for display name", "[ancs][control_point]")
{
    uint8_t request[64] = {0};
    size_t request_length = 0;
    const uint8_t expected[] = {
        0x01, 'c','o','m','.','e','x','a','m','p','l','e','.','c','h','a','t',
        0x00, 0x00,
    };

    TEST_ASSERT_EQUAL(
        ANCS_PROTOCOL_OK,
        ancs_build_get_app_attributes("com.example.chat", request,
                                      sizeof(request), &request_length));
    TEST_ASSERT_EQUAL_size_t(sizeof(expected), request_length);
    TEST_ASSERT_EQUAL_UINT8_ARRAY(expected, request, sizeof(expected));
}

TEST_CASE("app parser reconstructs localized display name at every split",
          "[ancs][app_parser]")
{
    const uint8_t response[] = {
        0x01, 'c','o','m','.','e','x','a','m','p','l','e','.','c','h','a','t',0x00,
        0x00, 0x09, 0x00, 0xec,0xb1,0x84,0xed,0x8c,0x85,0xed,0x8c,0x85,
    };
    for (size_t split = 0; split <= sizeof(response); ++split) {
        ancs_notification_t notification = {0};
        strcpy(notification.app_id, "com.example.chat");
        ancs_app_data_parser_t parser;
        ancs_app_data_parser_init(&parser, &notification);
        TEST_ASSERT_NOT_EQUAL(
            ANCS_PARSER_ERROR,
            ancs_app_data_parser_feed(&parser, response, split));
        TEST_ASSERT_EQUAL(
            ANCS_PARSER_COMPLETE,
            ancs_app_data_parser_feed(&parser, response + split,
                                      sizeof(response) - split));
        TEST_ASSERT_EQUAL_STRING("채팁팁", notification.app_name);
    }
}
```

Also add one-byte feed, empty name, `CONFIG_ANCS_APP_NAME_MAX + 1` truncation, wrong command, duplicate/wrong attribute, missing null terminator overflow, mismatched App Identifier, and trailing-byte sequence tests.

- [ ] **Step 2: Run a compile RED**

Run the ESP-IDF test-app build using the configured SDK:

```powershell
$idfExport = Join-Path $env:IDF_PATH 'export.bat'
cmd /d /s /c "call `"$idfExport`" && idf.py -C test_app -B build-test-app -DIDF_TARGET=esp32c6 build"
```

Expected: FAIL because `ancs_build_get_app_attributes`, `ancs_app_data_parser_t`, and parser functions are undefined.

- [ ] **Step 3: Add bounded public types and APIs**

Add `CONFIG_ANCS_APP_NAME_MAX` with default `256`, then extend the public contract:

```c
#define ANCS_COMMAND_GET_NOTIFICATION_ATTRIBUTES 0U
#define ANCS_COMMAND_GET_APP_ATTRIBUTES 1U
#define ANCS_APP_ATTRIBUTE_DISPLAY_NAME 0U

char app_name[CONFIG_ANCS_APP_NAME_MAX + 1];
bool app_name_truncated;

typedef struct {
    ancs_notification_t *notification;
    char response_app_id[CONFIG_ANCS_APP_ID_MAX + 1];
    size_t response_app_id_read;
    uint16_t attribute_length;
    uint16_t attribute_read;
    uint8_t state;
    uint8_t attribute_id;
    uint8_t length_bytes_read;
    bool response_app_id_terminated;
    int error_code;
} ancs_app_data_parser_t;

ancs_protocol_error_t ancs_build_get_app_attributes(
    const char *app_id, uint8_t *output, size_t output_capacity,
    size_t *output_length);
void ancs_app_data_parser_init(ancs_app_data_parser_t *parser,
                               ancs_notification_t *notification);
ancs_parser_result_t ancs_app_data_parser_feed(ancs_app_data_parser_t *parser,
                                               const uint8_t *bytes,
                                               size_t length);
```

- [ ] **Step 4: Implement the minimal request builder and parser**

The builder validates non-null arguments, rejects empty or over-limit IDs, requires `strlen(app_id) + 3` bytes, writes command `1`, the identifier including its null byte, and attribute `0`.

The parser state sequence is `COMMAND -> APP_ID -> ATTRIBUTE_ID -> ATTRIBUTE_LENGTH -> ATTRIBUTE_VALUE -> COMPLETE`. It compares the terminated response identifier with `notification->app_id`, accepts only attribute `0` once, copies at most `CONFIG_ANCS_APP_NAME_MAX` bytes, sets `app_name_truncated` when the declared length is larger, null-terminates, and rejects bytes arriving after completion. Reuse the existing `ANCS_PROTOCOL_ERR_COMMAND`, `ANCS_PROTOCOL_ERR_ATTRIBUTE`, `ANCS_PROTOCOL_ERR_OVERFLOW`, and `ANCS_PROTOCOL_ERR_SEQUENCE`; add `ANCS_PROTOCOL_ERR_APP_ID_MISMATCH` so UID and App Identifier mismatches remain distinguishable.

- [ ] **Step 5: Build and run available Unity tests**

Run the same test-app build. Expected: link/build PASS. Detect a unique serial target with the repository helper and run Unity only when detection succeeds:

```powershell
$detectedPort = python tools/detect_port.py
if ($LASTEXITCODE -eq 0) {
    cmd /d /s /c "call `"$idfExport`" && idf.py -C test_app -B build-test-app -p $detectedPort flash monitor"
}
```

Require every `[ancs][app_parser]` Unity case to pass; when detection does not return exactly one device, record execution as a physical-test gap rather than treating build success as test execution.

- [ ] **Step 6: Commit protocol support**

Commit intent: `Resolve installed app names through the ANCS protocol`

Trailers: `Constraint: No external app catalog or API`, `Tested: ESP-IDF test-app compile and available Unity execution`.

### Task 3: Add a Bounded Session App Resolver

**Files:**
- Create: `components/ancs_app_resolver/include/ancs_app_resolver.h`
- Create: `components/ancs_app_resolver/ancs_app_resolver.c`
- Create: `components/ancs_app_resolver/CMakeLists.txt`
- Create: `components/ancs_app_resolver/Kconfig`
- Create: `components/ancs_app_resolver/test/test_ancs_app_resolver.c`
- Modify: `test_app/CMakeLists.txt:4-16`
- Modify: `test_app/main/CMakeLists.txt:1-20`
- Modify: `sdkconfig.defaults:20-36`

- [ ] **Step 1: Write failing resolver tests**

Define tests around this API:

```c
typedef enum {
    ANCS_APP_RESOLUTION_REQUEST_NATIVE = 0,
    ANCS_APP_RESOLUTION_USE_NATIVE,
    ANCS_APP_RESOLUTION_USE_FALLBACK,
} ancs_app_resolution_t;

ancs_app_resolution_t ancs_app_resolver_begin(
    ancs_app_resolver_t *resolver, const char *app_id,
    char *output, size_t output_capacity);
ancs_app_resolution_t ancs_app_resolver_complete(
    ancs_app_resolver_t *resolver, const char *app_id,
    const char *display_name, char *output, size_t output_capacity);
ancs_app_resolution_t ancs_app_resolver_fail(
    char *output, size_t output_capacity);
```

Assert: the first non-empty ID returns `REQUEST_NATIVE`; completion with `"카카오톡"` returns `USE_NATIVE`; the second begin returns `USE_NATIVE` and copies the cached UTF-8 name; empty ID and failed/empty completion return `USE_FALLBACK`; reset makes the same ID request again; inserting capacity-plus-one IDs evicts the least recently used entry.

- [ ] **Step 2: Build and verify RED**

Run the test-app build. Expected: FAIL because the resolver component and API do not exist.

- [ ] **Step 3: Implement the fixed-storage resolver**

Use `CONFIG_ANCS_APP_CACHE_CAPACITY` default `16`. Each entry stores `used`, `age`, `app_id[CONFIG_ANCS_APP_ID_MAX + 1]`, and `display_name[CONFIG_ANCS_APP_NAME_MAX + 1]`. `begin` refreshes age on a hit. `complete` stores only non-empty exact IDs/names and chooses an unused entry before the lowest-age entry. `fail` writes an empty output. `ancs_app_resolver_init` zeroes the whole resolver, making session reset explicit. Reject null/zero-capacity output by returning fallback without writing out of bounds.

- [ ] **Step 4: Register the component and run tests**

Add `ancs_app_resolver` to `EXTRA_COMPONENT_DIRS`, `REQUIRES`, and test sources. Add `CONFIG_ANCS_APP_NAME_MAX=256` and `CONFIG_ANCS_APP_CACHE_CAPACITY=16` to `sdkconfig.defaults`. Build the test app and run Unity on hardware when available.

- [ ] **Step 5: Commit the resolver**

Commit intent: `Reuse app names only within the active ANCS session`

Trailers: `Constraint: Cache must be bounded and cleared on reconnect`, `Tested: resolver Unity cases and ESP-IDF build`.

### Task 4: Prefer Native Names in MQTT Without Breaking Fallbacks

**Files:**
- Modify: `components/mqtt_relay/test/test_mqtt_payload.c:207-250`
- Modify: `components/mqtt_relay/mqtt_payload.c:12-70`
- Modify: `test/test_json_output.c:60-82`
- Modify: `components/notification_sink/notification_sink_serial.c:238-250`

- [ ] **Step 1: Write failing native-precedence tests**

Set `notification.app_id` to a statically mapped ID and `notification.app_name` to `"Messages from iPhone"`; assert the JSON contains the native value. Clear `notification.app_name`; assert the mapped value remains. Use `com.example.Unknown`; assert the App Identifier remains. Set `app_name_truncated=true`; assert the truncation object contains `"app_name":true`.

- [ ] **Step 2: Build and verify RED**

Expected failures: the serializer ignores `notification.app_name`, and the truncation object lacks `app_name`.

- [ ] **Step 3: Implement native precedence**

Use exactly:

```c
const char *app_name = notification->app_name[0] != '\0'
                           ? notification->app_name
                           : mqtt_app_name_lookup(notification->app_id);
```

Include `strlen(notification->app_name)` in capacity accounting. Add `app_name` to truncation evidence in `notification_sink_format_json`, but keep the top-level `app_name` appended only once by `mqtt_payload_build_notification`.

- [ ] **Step 4: Build/run payload and JSON tests**

Expected: native, static, and unknown fallbacks pass; the existing JSON fields and escaping tests remain green.

- [ ] **Step 5: Commit payload behavior**

Commit intent: `Prefer the iPhone display name without weakening MQTT fallbacks`

Trailers: `Constraint: Existing app_name JSON field and topics remain stable`, `Tested: MQTT payload and notification JSON Unity cases`.

### Task 5: Orchestrate Two-Stage ANCS Requests

**Files:**
- Modify: `components/ancs_client/CMakeLists.txt:1-5`
- Modify: `components/ancs_client/ancs_client.c:30-760`

- [ ] **Step 1: Add a compile-time RED for resolver integration**

Include `ancs_app_resolver.h`, add the resolver dependency, and introduce references to `ancs_app_resolver_t` and `ancs_app_data_parser_t` before changing request logic. Build the firmware for ESP32-C6 and require the initial compile to fail at the unimplemented stage transitions rather than silently retaining the one-stage path.

- [ ] **Step 2: Add explicit request kind and worker state**

Add:

```c
typedef enum {
    ACTIVE_REQUEST_NOTIFICATION_ATTRIBUTES = 0,
    ACTIVE_REQUEST_APP_ATTRIBUTES,
} active_request_kind_t;

active_request_kind_t active_request_kind;
ancs_app_data_parser_t app_parser;
ancs_app_resolver_t app_resolver;
```

Increase `CONTROL_REQUEST_MAX` to `CONFIG_ANCS_APP_ID_MAX + 3U`.

- [ ] **Step 3: Split request construction by active kind**

For notification requests, retain the current UID request and parser initialization. For app requests, build from `active_notification.app_id`, initialize `app_parser` against the completed notification, and leave the notification's core attributes/`complete` flag untouched. Each stage sets the same response deadline and logs the request kind.

- [ ] **Step 4: Add one-shot publication finalization**

Create a helper that publishes `active_notification`, stores it in the UID removal cache, and clears `active`/`active_canceled`. After notification parser completion, call `ancs_app_resolver_begin`. On `USE_NATIVE` or `USE_FALLBACK`, finalize immediately. On `REQUEST_NATIVE`, switch kind, reset attempt to zero, and write the app request without popping a new notification event.

- [ ] **Step 5: Parse app responses and isolate enrichment failures**

When the active kind is app attributes, feed `app_parser`. On completion, pass its name through `ancs_app_resolver_complete` and finalize once. On empty completion, call resolver completion, leave `app_name` empty, and finalize so MQTT applies its static fallback. On parser error or timeout, retry once; after the retry, call `ancs_app_resolver_fail`, finalize the complete notification, then recover the data stream because alignment is unknown. On a Control Point write failure, retry once and then finalize fallback without marking the notification incomplete.

- [ ] **Step 6: Preserve cancellation and reset behavior**

An active removed UID sets `active_canceled` in either stage. Drain completion/error without publishing the added/modified notification. In `reset_worker_session`, clear both parsers and call `ancs_app_resolver_init`; this is the only persistent-name cache reset boundary.

- [ ] **Step 7: Build the C6 firmware and test app**

Run:

```powershell
.\tools\build_matrix.ps1 -Targets esp32c6 -Version 0.3.6
```

Expected: firmware compile/link/merge PASS and no static-analysis warning from request buffer sizes or parser types. Run Unity on a connected test device if available.

- [ ] **Step 8: Commit client orchestration**

Commit intent: `Delay first app notification until its native name is resolved`

Trailers: `Constraint: Publish one Home Assistant event per iPhone notification`, `Directive: App-name failure must never become notification failure`, `Tested: C6 firmware build and available Unity execution`.

### Task 6: Remove the Published-Uptime Sensor Safely

**Files:**
- Modify: `tests/test_sensor.py:24-210`
- Modify: `tests/test_config_flow.py:90-135,713-748`
- Modify: `tests/test_init.py`
- Modify: `custom_components/ha_ios_ancs/sensor.py:195-214`
- Modify: `custom_components/ha_ios_ancs/__init__.py:35-54`
- Modify: `custom_components/ha_ios_ancs/const.py:1-10`
- Modify: `custom_components/ha_ios_ancs/strings.json:68-74`
- Modify: `custom_components/ha_ios_ancs/translations/en.json:68-74`
- Modify: `custom_components/ha_ios_ancs/translations/ko.json:68-74`

- [ ] **Step 1: Write failing entity and migration tests**

Remove `published_at_ms` from expected sensor keys/specs while keeping it in `complete_payload()`. Assert `raw_notification` attributes still contain `published_at_ms`. Add a migration test that registers three entities for one config entry:

```python
deprecated = registry.async_get_or_create(
    domain="sensor", platform=DOMAIN,
    unique_id="ios_ancs_A1B2C3:sensor:published_at_ms",
    config_entry=entry,
)
received = registry.async_get_or_create(
    domain="sensor", platform=DOMAIN,
    unique_id="ios_ancs_A1B2C3:sensor:received_at_ms",
    config_entry=entry,
)
mqtt_owned = registry.async_get_or_create(
    domain="sensor", platform="mqtt",
    unique_id="ios_ancs_A1B2C3:sensor:published_at_ms",
    config_entry=entry,
)
```

After migration, assert only `deprecated.entity_id` is absent. Assert entry version becomes `3` and source data/unique ID remain unchanged.

- [ ] **Step 2: Run focused pytest and verify RED**

Run: `python -m pytest tests/test_sensor.py tests/test_config_flow.py tests/test_init.py -q`

Expected: FAIL because the sensor is still described, config-entry version is `2`, and migration does not remove it.

- [ ] **Step 3: Remove the sensor and translations**

Delete only the `published_at_ms` description and translation key. Do not remove `received_at_ms`, payload normalization, stored raw fields, or event data.

- [ ] **Step 4: Implement exact registry migration**

Set `CONFIG_ENTRY_VERSION = 3`. Before updating the entry version, iterate `er.async_entries_for_config_entry`. Remove an entity only when all conditions are true: `domain == Platform.SENSOR`, `platform == DOMAIN`, and `unique_id.endswith(":sensor:published_at_ms")`. Use `entity_registry.async_remove(entity_id)`. Leave MQTT platform entries untouched.

- [ ] **Step 5: Run Home Assistant tests**

Run focused tests, then `python -m pytest tests -q`.

Expected: all tests PASS; entity count decreases by one; raw attributes retain the field.

- [ ] **Step 6: Commit the migration**

Commit intent: `Retire the redundant published-uptime entity on upgrade`

Trailers: `Constraint: Preserve raw MQTT timing and all MQTT-owned entities`, `Tested: Home Assistant sensor, migration, and full integration tests`.

### Task 7: Align Firmware, HACS, Installer, and Release Contracts

**Files:**
- Modify: `tools/tests/test_documentation_contract.py`
- Modify: `tools/tests/test_multi_target_contract.py`
- Modify: `tools/tests/test_release_integrity.py`
- Modify: `tests/test_config_flow.py`
- Modify: `CMakeLists.txt`, `tools/build.ps1`, `tools/build.sh`, `tools/build_matrix.ps1`
- Modify: `custom_components/ha_ios_ancs/manifest.json`
- Modify: `README.md`, `README.en.md`, `docs/index.html`, `docs/app.js`
- Modify: `docs/manifests/ios-ancs.json`, `docs/manifests/esp32-c6.json`
- Replace: seven `docs/firmware/*/ios-ancs-*-v0.3.3.factory.bin` files with `v0.3.6` builds
- Replace: `docs/release-fingerprints-v0.3.3.sha256` with `docs/release-fingerprints-v0.3.6.sha256`

- [ ] **Step 1: Update release tests first and verify RED**

Set firmware `VERSION = "0.3.6"`, rename test names from `v033` to `v034`, change installer/docs expectations to `0.3.6`, and change companion manifest expectations to `0.6.3`. Add README assertions that native ANCS Display Name is primary and static mapping is fallback. Run tool and manifest contract tests; expect failures against current `0.3.3`/`0.6.2` files.

- [ ] **Step 2: Update textual version anchors and guidance**

Set firmware defaults/project version to `0.3.6` and integration manifest to `0.6.3`. Update both READMEs and installer surfaces to explain: first notification from an app may incur one native lookup; subsequent notifications use a session cache; app lookup failure falls back without losing notification details; HACS installs the companion only.

- [ ] **Step 3: Build all seven firmware targets**

Run:

```powershell
.\tools\build_matrix.ps1 -Version 0.3.6 -Jobs 6
```

Expected: seven successful results in `artifacts/build-matrix.json` and seven new factory binaries. For every report item, resolve its `path` and verify it begins with the repository's absolute `docs/firmware/` directory before removing the seven tracked `v0.3.3` images.

- [ ] **Step 4: Update manifests, SHA prefixes, and fingerprints**

Point both manifests to `v0.3.6` files. Compute each binary SHA-256, update its 12-character uppercase prefix in `docs/app.js`, and create the fingerprint file in manifest target order using lowercase full digests and repository-relative paths. Remove the superseded fingerprint and firmware files only after all new paths and hashes validate.

- [ ] **Step 5: Run release integrity and complete local verification**

Run:

```powershell
python -m pytest tools/tests -q
python -m pytest tests -q
python -m compileall custom_components tools tests
git diff --check
```

Expected: all suites PASS, seven manifest binaries exist and are tracked, fingerprints match, no whitespace errors.

- [ ] **Step 6: Commit the release artifacts**

Commit intent: `Ship native iOS app names across firmware and HACS`

Trailers: `Constraint: Firmware 0.3.6 and companion 0.6.3 must remain independently identifiable`, `Tested: full pytest suites, seven-target builds, compileall, release integrity`, `Not-tested: physical iPhone notification until deployment step`.

### Task 8: Publish and Verify the Release

**Files:**
- No additional source files expected.

- [ ] **Step 1: Review the complete diff and repository state**

Run `git status --short`, `git diff origin/main...HEAD --check`, `git log --oneline origin/main..HEAD`, and verify no unrelated user files are included.

- [ ] **Step 2: Push `main` and wait for GitHub Actions**

Run `git push origin main`. Inspect the Validate and Pages runs for the pushed SHA with `gh run list`/`gh run watch`. Require HACS, Hassfest, release-integrity, and Pages deployment success before tagging.

- [ ] **Step 3: Create and push HACS release tag**

Create annotated tag `v0.6.3` at the verified SHA. Push the tag. Create a GitHub release named `iOS ANCS v0.6.3` with release notes separating companion `0.6.3` from firmware `0.3.6`, and attach all seven factory binaries plus `release-fingerprints-v0.3.6.sha256`.

- [ ] **Step 4: Verify public artifacts**

Fetch the GitHub release metadata, confirm tag/SHA/assets, open the Pages manifests, and verify all public manifest binary URLs return the new `0.3.6` files whose hashes match the committed fingerprint list. Confirm HACS can see manifest version `0.6.3`; do not claim HACS default-store acceptance unless its upstream review actually shows acceptance.

- [ ] **Step 5: Perform live deployment proof where accessible**

If the intended ESP32-C6 serial port is identifiable without ambiguity, flash `ios-ancs-esp32c6-v0.3.6.factory.bin`, preserve provisioning, reconnect the paired iPhone, and inspect MQTT for a fresh non-Home-Assistant notification. Require the payload `app_name` to be a localized native name and Home Assistant to expose it on the separate `iOS ANCS` companion device while the MQTT device remains enabled. Confirm the deprecated `published_at_ms` companion entity is gone and `received_at_ms` remains.

- [ ] **Step 6: Report verified and unverified scopes separately**

Report commit/tag/release/Actions/HACS/Pages evidence. If physical access or a fresh notification is unavailable, state that static/build/release verification is complete but live iPhone-to-MQTT proof remains unverified; do not substitute an old notification for a fresh native-name lookup.
