#!/usr/bin/env python3

import sys

from serial.tools import list_ports


ESP_USB_VIDS = {
    0x303A,  # Espressif native USB/JTAG
    0x1A86,  # QinHeng CH34x
    0x10C4,  # Silicon Labs CP210x
    0x0403,  # FTDI
}


def main() -> int:
    candidates = [
        port
        for port in list_ports.comports()
        if port.vid in ESP_USB_VIDS
    ]
    if len(candidates) == 1:
        print(candidates[0].device)
        return 0

    if not candidates:
        print(
            "ESP 계열 USB 시리얼 포트를 찾지 못했습니다. 포트를 명시하십시오.",
            file=sys.stderr,
        )
        return 3

    print(
        "ESP 계열 USB 시리얼 후보가 여러 개입니다. 포트를 명시하십시오:",
        file=sys.stderr,
    )
    for port in candidates:
        print(
            f"  {port.device}: {port.description} "
            f"(VID:PID={port.vid:04X}:{port.pid or 0:04X})",
            file=sys.stderr,
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
