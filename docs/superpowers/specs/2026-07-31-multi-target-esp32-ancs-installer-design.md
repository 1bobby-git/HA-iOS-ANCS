# Multi-target ESP32 ANCS Installer Design

## Goal

Publish one browser installer for the iOS ANCS MQTT relay that supports the
largest practical set of ESP32 chips with both Wi-Fi and Bluetooth LE, while
preventing users from flashing a binary built for the wrong chip.

The Home Assistant MQTT Discovery sensor must keep `relay_id` as its state and
expose the complete notification JSON as attributes, including:

- `schema_version`
- `target`
- `device_name`
- `session_id`
- `event`
- `event_id`
- `uid`
- `event_flags`
- `silent`
- `important`
- `pre_existing`
- `positive_action_available`
- `negative_action_available`
- `category_id`
- `category`
- `category_count`
- `app_id`
- `title`
- `subtitle`
- `message`
- `message_size`
- `date`
- `complete`
- `truncated`
- `error`
- `received_at_ms`
- `relay_id`
- `source`
- `published_at_ms`

## Supported-target policy

The firmware source is shared, but each chip family receives its own bootloader,
partition table, application binary, and merged factory image. A single binary
cannot be shared across different CPU and ROM bootloader families.

Initial build candidates are:

| ESP-IDF target | Installer family | Device label | Default BOOT GPIO | Minimum flash |
| --- | --- | --- | ---: | ---: |
| `esp32` | `ESP32` | `ESP32` | 0 | 4 MB |
| `esp32c2` | `ESP32-C2` | `C2` | 9 | 4 MB |
| `esp32c3` | `ESP32-C3` | `C3` | 9 | 4 MB |
| `esp32c5` | `ESP32-C5` | `C5` | 28 | 4 MB |
| `esp32c6` | `ESP32-C6` | `C6` | 9 | 4 MB |
| `esp32c61` | `ESP32-C61` | `C61` | 9 | 4 MB |
| `esp32s3` | `ESP32-S3` | `S3` | 0 | 4 MB |

Only targets that complete configuration, compilation, linking, partition-size
validation, and merged-image inspection are published in the installer
manifest. ESP32-S2 is excluded because it has no Bluetooth LE. ESP32-H2 is
excluded because it has no Wi-Fi. ESP32-P4 is excluded because it requires an
external wireless companion.

ESP32-C6 remains the hardware-validated target. Other generated targets are
shown as build-validated until a physical board completes boot, provisioning,
BLE enrollment, ANCS subscription, Wi-Fi, MQTT, and Home Assistant checks.

## Target identity

A small header-only `platform_identity` component owns all compile-time target
identity:

- MQTT/serial `target`: the ESP-IDF target, such as `esp32c6`.
- MQTT `source`: `<target>_ancs`, such as `esp32c6_ancs`.
- Bluetooth device family label: `ESP32`, `C2`, `C3`, `C5`, `C6`, `C61`, or
  `S3`.
- Bluetooth device name: `IOS-ANCS-<family>-<MAC4>`.

This removes C6 literals from notification JSON, state JSON, MQTT payloads, BLE
names, and portal defaults while preserving the existing C6 values exactly.

## Firmware configuration

All variants use the existing custom partition layout and a 4 MB flash baseline.
The used partition range ends below 4 MB, so the same logical partition contract
works on modules with 4 MB or more. Each target uses Bluedroid with GATT client
and GATT server enabled because the product simultaneously consumes ANCS and
advertises the HID service used for iOS enrollment.

The build matrix uses isolated directories (`build-<target>`) and isolated
SDKCONFIG files. This prevents `idf.py set-target` for one target from
overwriting the checked-in C6 development configuration.

## Browser installer

The large board-card grid is replaced by one compact installer console:

1. A model selector shows every published build and its validation level.
2. A detail panel shows chip family, minimum flash, firmware version, and
   validation status.
3. One ESP Web Tools install button points to a unified manifest containing all
   published `chipFamily` builds.
4. ESP Web Tools detects the connected chip and selects the matching binary.
   The selector is informational and cannot force a mismatched binary.

This keeps the interface compact while making wrong-target flashing harder than
the per-model-manifest design.

## Home Assistant discovery contract

The notification topic remains both:

- the Discovery `state_topic`, with `value_template` set to
  `{{ value_json.relay_id }}`;
- the Discovery `json_attributes_topic`.

Therefore Home Assistant stores the unique relay ID as sensor state and copies
the complete notification object into sensor attributes. Discovery remains
retained, notification payloads remain non-retained QoS 1, and the existing
Home Assistant echo-loop marker remains enforced.

Tests must enumerate the required attribute keys instead of checking only a
small sample. Target and source assertions must be target-aware.

## Failure handling

- A target that fails to build or exceeds the app partition is omitted from the
  public manifest and reported in the build summary.
- A connected chip with no matching build is rejected by ESP Web Tools.
- A 2 MB module is unsupported and must not be presented as compatible.
- Build validation is never described as hardware validation.
- Existing Wi-Fi, MQTT, BLE enrollment, offline-drop, and Home Assistant
  loop-prevention behavior must remain unchanged.

## Verification

Completion requires:

- all host contract tests passing;
- each published target building from a clean isolated directory;
- each merged factory image reporting the expected chip family;
- manifest paths, offsets, and binary hashes validating locally;
- GitHub Pages rendering one selector and one install button without console
  errors or horizontal overflow;
- the live page, manifest, and every published factory binary returning HTTP
  200;
- ESP32-C6 retaining its existing target, source, device-name format, and
  hardware-validation status.
