# ESP Web Tools 10.4.0 reliability patch 2

This browser bundle is built from the official `esp-web-tools` 10.4.0 npm
source under its Apache-2.0 license. `@material/web` is pinned to 2.2.0.

Local reliability changes:

- retry every compressed flash block up to three times with a 150 ms pause;
- retry the idempotent full-chip erase up to three times with a 250 ms pause;
- convert a final erase failure into the install dialog's error state instead
  of leaving an unhandled promise and a permanent `Erasing` spinner;
- best-effort reset and release the serial port after a final erase failure.

The erase handling specifically covers Web Serial response loss such as
`No serial data received.` after the flasher stub has started.

Upstream references:

- ESP Web Tools 10.4.0:
  https://github.com/esphome/esp-web-tools/tree/v10.4.0
- esptool-js retry proposal:
  https://github.com/espressif/esptool-js/pull/245
- Python esptool compressed-block retry:
  https://github.com/espressif/esptool/blob/master/esptool/loader.py
