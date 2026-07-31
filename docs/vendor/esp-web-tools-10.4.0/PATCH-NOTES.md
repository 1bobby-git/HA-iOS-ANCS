# ESP Web Tools 10.4.0 patched build

This directory contains the browser bundle built from the official
`esp-web-tools` 10.4.0 npm source under its Apache-2.0 license.

The local build pins `@material/web` to 2.2.0 and adds three attempts, with a
150 ms pause, around every `ESPLoader.flashDeflBlock` call. This matches the
three-attempt block policy in the reference Python `esptool` and prevents a
single transient Web Serial response from aborting the complete installation.

The retry is intentionally scoped to compressed writes because ESP Web Tools
10.4.0 invokes `writeFlash` with `compress: true`.

Upstream references:

- ESP Web Tools: https://github.com/esphome/esp-web-tools/tree/v10.4.0
- esptool-js retry proposal: https://github.com/espressif/esptool-js/pull/245
- Reference esptool block retries:
  https://github.com/espressif/esptool/blob/master/esptool/loader.py
