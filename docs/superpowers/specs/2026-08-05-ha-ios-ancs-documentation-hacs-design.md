# HA-iOS-ANCS Documentation, Installer, and HACS Design

## Status

Approved in conversation on 2026-08-05. This document defines the implementation boundary for renaming `1bobby-git/ios-ancs` to `1bobby-git/HA-iOS-ANCS`, improving the public documentation and browser installer, and making the Home Assistant companion installable through HACS.

## Outcome

The repository will become one clear entry point for four related tasks:

1. Understanding what ANCS is and why the project exists.
2. Installing supported ESP32 firmware from a desktop browser or source.
3. Connecting the device to Wi-Fi, MQTT, an iPhone, and Home Assistant.
4. Installing an optional Home Assistant companion through HACS.

The instructions must remain concise at the decision points while providing enough detail for a first-time user to finish installation without guessing.

## Audience and Language

The primary README and browser installer will be written in Korean. An English README will preserve the same contracts for international users and HACS reviewers. Product names, commands, MQTT topics, entity identifiers, and protocol terminology remain in their canonical English form.

## Core Explanation

The first screen and first README section must explain the project in one sentence and define ANCS before mentioning build tools.

Required Korean definition:

> **Apple Notification Center Service (ANCS)**: 블루투스(BLE)를 통해 아이폰 등의 iOS 기기 알림을 스마트워치나 이어폰 같은 주변 기기로 전달해 주는 애플 규격 서비스입니다.

Required system flow:

```text
iPhone -> BLE ANCS -> ESP32 -> Wi-Fi/MQTT -> Home Assistant
```

The documentation must also make the following boundaries explicit:

- The web installer flashes ESP32 firmware; HACS does not flash hardware.
- HACS installs the optional Home Assistant companion.
- MQTT Discovery remains the firmware's default Home Assistant connection path.
- Build verification, hardware flashing, BLE enrollment, and live iPhone notification capture are separate claims and must not be conflated.

## README Information Architecture

`README.md` will become the Korean canonical guide. The current English content will be revised and retained as `README.en.md`.

The Korean guide will use this order:

1. Project purpose and ANCS definition.
2. Architecture and data path.
3. Suitable users and non-goals.
4. Supported boards and current verification status.
5. Five-minute quick start.
6. Browser installation.
7. Source build and flash.
8. First-boot Wi-Fi and MQTT provisioning.
9. iPhone enrollment and notification-sharing permission.
10. Home Assistant MQTT Discovery and optional HACS companion.
11. Normal operation, entities, events, and MQTT topics.
12. Updating, reset behavior, device replacement, and stored-data impact.
13. Troubleshooting organized by symptom.
14. Security, privacy, and notification-retention behavior.
15. Development and verification commands.

Long command references and protocol contracts may use tables or collapsible details, but the quick-start path must stay visible without expanding anything.

## Browser Installer Information Architecture

The public installer will remain a static GitHub Pages application and preserve the current chip auto-detection and release-integrity behavior. Its content will be reorganized into a guided sequence:

1. What the project does and what ANCS means.
2. Prerequisites: supported board, desktop Chrome or Edge, USB data cable, Wi-Fi, MQTT broker, iPhone, and Home Assistant.
3. Board selection and verified support status.
4. USB installation with explicit success and failure states.
5. Post-flash setup AP connection and `192.168.4.1` provisioning.
6. Wi-Fi and MQTT field explanations.
7. Home Assistant connection check.
8. iPhone enrollment, PIN entry, and notification-sharing permission.
9. First-notification verification.
10. HACS companion installation.
11. Symptom-based troubleshooting.

Every step must answer three questions:

- What must the user do?
- What visible result proves success?
- What should the user check if that result does not appear?

Warnings must appear next to the action they govern. In particular, a full erase must explain that it removes stored Wi-Fi, MQTT, and BLE enrollment data before the user starts the operation.

## Home Assistant and HACS Companion

The repository will contain one HACS-managed integration under `custom_components/ha_ios_ancs/`. It is an optional companion and must not be required for firmware flashing or basic MQTT Discovery.

The companion will provide a native Home Assistant event surface for notification relay while avoiding duplicate copies of the firmware's MQTT Discovery sensors and buttons. Its configuration flow will accept the device MQTT base topic and validate that the Home Assistant MQTT integration is available.

Runtime responsibilities:

- Subscribe to the configured notification and availability topics through Home Assistant's MQTT APIs.
- Emit structured Home Assistant events for complete, new notifications.
- Deduplicate by `relay_id` within the active runtime session.
- Reject incomplete, `pre_existing`, malformed, removed, and Home Assistant echo notifications using the existing firmware contract.
- Expose integration health without copying the firmware's existing Discovery entity set.
- Unsubscribe cleanly when the config entry is unloaded or reconfigured.

Packaging responsibilities:

- Root `hacs.json`.
- Integration `manifest.json` with required HACS and Home Assistant fields.
- Config flow, strings, Korean and English translations.
- Brand asset suitable for Home Assistant Brands.
- HACS validation and Hassfest workflows.
- Focused unit tests for configuration, subscription lifecycle, filtering, and deduplication.
- A full GitHub release after all validation passes.

The repository documentation will include a HACS custom-repository link immediately. Default-store visibility requires separate upstream review and cannot be described as complete until the `hacs/default` pull request is merged.

## Repository Rename and URL Migration

The GitHub repository will be renamed to `HA-iOS-ANCS` only after the codebase is prepared for the new slug.

Migration sequence:

1. Update repository links, Pages base paths, installer links, documentation, manifests, tests, and workflow contracts to `HA-iOS-ANCS`.
2. Run local documentation, integration, firmware-release, and Pages checks.
3. Commit and push the prepared change to the existing repository.
4. Rename the GitHub repository.
5. Update the local `origin` URL.
6. Trigger and verify GitHub Pages at `https://1bobby-git.github.io/HA-iOS-ANCS/`.
7. Verify manifests, firmware downloads, source links, and HACS links from the public site.

GitHub repository redirects may preserve ordinary Git URLs, but the old GitHub Pages project URL must not be treated as a supported redirect. All public instructions will use the new Pages URL after migration.

## HACS Default-Store Submission

After the renamed repository has a passing HACS Action, passing Hassfest, valid brand assets, and a full release:

1. Submit the integration brand to `home-assistant/brands` if it is not already accepted.
2. Prepare and submit the repository entry to `hacs/default` in alphabetical order.
3. Link the upstream pull requests from the project README.
4. Describe default-store visibility as pending until upstream approval and scheduled ingestion complete.

No claim will imply that opening an upstream pull request guarantees acceptance or immediate visibility.

## Verification and Acceptance Criteria

The work is complete only when all applicable checks below pass with fresh evidence:

- README links, headings, commands, and terminology are internally consistent.
- Korean and English guides agree on installation and safety contracts.
- The browser installer renders at desktop and mobile widths without hiding the primary path.
- USB installation controls and existing chip auto-detection remain functional.
- The new Pages URL loads and all checked-in firmware manifests and images resolve.
- Existing release-integrity and multi-target contract tests pass.
- New Home Assistant companion tests pass.
- HACS Action and Hassfest pass without ignored failures.
- The renamed Git remote, GitHub repository, homepage metadata, topics, and Pages deployment all use the new slug.
- HACS custom-repository installation is documented and validated.
- Upstream HACS and Brands submissions are reported accurately as merged, pending, or blocked.

Hardware and live iPhone validation will only be claimed when performed during this implementation. Existing historical evidence may be identified as historical but cannot substitute for a fresh runtime check.

## Non-Goals

- Replacing Apple ANCS with an iOS application.
- Making iPhone or iPad browsers flash ESP32 hardware over Web Serial.
- Removing MQTT Discovery from the firmware.
- Redesigning unrelated firmware protocol behavior.
- Claiming HACS default-store acceptance before upstream review completes.
