from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8", newline="\n")


def replace_required(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}: {old[:100]!r}")
    write(path, content.replace(old, new, 1))


# Keep the primary documentation aligned with same-page enrollment.
replace_required(
    "README.md",
    "5. Home Assistant에서 MQTT Discovery로 장치가 보이면 **iPhone 등록 시작** 버튼을 눌러 120초 등록 창을 엽니다.\n"
    "6. iOS Bluetooth 설정에서 장치를 선택하고 PIN `설정 포털에 등록 시간 동안 표시되는 장치별 6자리 코드`을 입력한 뒤 알림 공유를 허용합니다. Home Assistant에서 `최근 알림`과 `앱 이름` 센서가 갱신되는지 확인합니다.",
    "5. `http://192.168.4.1` 설정 포털을 떠나지 않고 **iPhone 기기 등록** 버튼을 눌러 120초 등록 창을 엽니다. Home Assistant의 **iPhone 등록 시작** 버튼과 BOOT 3초 누르기도 같은 등록 창을 엽니다.\n"
    "6. 설정 포털에 표시되는 장치별 6자리 등록 코드를 확인한 뒤 iOS Bluetooth 설정에서 장치를 선택하고 코드를 입력합니다. 알림 공유를 허용하고 Home Assistant에서 `최근 알림`과 `앱 이름` 센서가 갱신되는지 확인합니다.",
)
replace_required(
    "README.md",
    "Home Assistant의 **iPhone 등록 시작** 버튼이나 BOOT 버튼을 3초 눌러 120초 등록 창을 열고, iOS Bluetooth 설정에서 PIN `설정 포털에 등록 시간 동안 표시되는 장치별 6자리 코드`을 입력한 뒤 알림 공유를 허용합니다. 저장된 기존 iPhone 페어링 정보가 있으면 같은 동작은 기존 iPhone 재연결만 요청합니다.",
    "설정 포털의 **iPhone 기기 등록** 버튼, Home Assistant의 **iPhone 등록 시작** 버튼 또는 BOOT 버튼 3초 누르기로 120초 등록 창을 엽니다. 설정 포털에 표시되는 장치별 6자리 코드를 iOS Bluetooth 설정에 입력하고 알림 공유를 허용합니다. 저장된 기존 iPhone 페어링 정보가 있으면 같은 동작은 기존 iPhone 재연결만 요청합니다.",
)

replace_required(
    "README.en.md",
    "5. In Home Assistant, wait for MQTT Discovery to find the device, then press **iPhone 등록 시작** to open the 120-second enrollment window.\n"
    "6. In iOS Bluetooth settings, select the device, enter PIN `the device-specific six-digit code shown in the setup portal while enrollment is open`, and allow notification sharing. Verify that `최근 알림` and `앱 이름` update in Home Assistant.",
    "5. Without leaving `http://192.168.4.1`, press **iPhone 기기 등록** in the setup portal to open the 120-second enrollment window. The Home Assistant **iPhone 등록 시작** button and holding BOOT for 3 seconds remain available alternatives.\n"
    "6. Read the device-specific six-digit enrollment code shown in the setup portal, select the device in iOS Bluetooth settings, enter the code, and allow notification sharing. Verify that `최근 알림` and `앱 이름` update in Home Assistant.",
)
replace_required(
    "README.en.md",
    "- If the iPhone does not see the device, reopen the 120-second enrollment window with **iPhone 등록 시작** or BOOT for 3 seconds.\n"
    "- If iOS asks for a PIN, enter `the device-specific six-digit code shown in the setup portal while enrollment is open` and allow notification sharing.",
    "- If the iPhone does not see the device, reopen the 120-second enrollment window with setup-portal **iPhone 기기 등록**, Home Assistant **iPhone 등록 시작**, or BOOT for 3 seconds.\n"
    "- If iOS asks for a PIN, enter the device-specific six-digit code shown in the setup portal while enrollment is open and allow notification sharing.",
)
replace_required(
    "README.en.md",
    "- Pairing uses PIN `the device-specific six-digit code shown in the setup portal while enrollment is open`; open enrollment only on a trusted local network and fully erase plus re-enroll before handing the device to another user.",
    "- Pairing uses the device-specific six-digit code shown in the setup portal while enrollment is open; open enrollment only on a trusted local network and fully erase plus re-enroll before handing the device to another user.",
)

# Publish the measured sizes of the newly built 0.3.7 factory images.
size_replacements = {
    "1,427,376 bytes": "1,440,912 bytes",
    "1,447,504 bytes": "1,461,792 bytes",
    "1,636,560 bytes": "1,650,800 bytes",
    "1,781,696 bytes": "1,795,936 bytes",
    "1,781,712 bytes": "1,795,968 bytes",
    "1,724,816 bytes": "1,739,072 bytes",
    "1,409,392 bytes": "1,422,960 bytes",
}
for path in ("README.md", "README.en.md"):
    content = read(path)
    for old, new in size_replacements.items():
        if content.count(old) != 1:
            raise RuntimeError(f"{path}: expected one size {old}")
        content = content.replace(old, new, 1)
    write(path, content)

replace_required(
    "docs/IOS_PAIRING.md",
    "5. Wait for Home Assistant MQTT Discovery to create the device and **iPhone 등록 시작** button.",
    "5. Keep the setup portal open. It now provides an **iPhone 기기 등록** button and shows the device-specific six-digit code while enrollment is open. Home Assistant MQTT Discovery also creates an **iPhone 등록 시작** button after MQTT connects.",
)
replace_required(
    "docs/IOS_PAIRING.md",
    "1. Hold BOOT for 3 seconds or press Home Assistant **iPhone 등록 시작**.\n"
    "2. Pair within the 120-second enrollment window.\n"
    "3. On iPhone, open **Settings > Bluetooth** and select the `IOS-ANCS-*` device.\n"
    "4. Enter PIN `설정 포털에 등록 시간 동안 표시되는 장치별 6자리 코드`.",
    "1. Press setup-portal **iPhone 기기 등록**, press Home Assistant **iPhone 등록 시작**, or hold BOOT for 3 seconds.\n"
    "2. Pair within the 120-second enrollment window without leaving the setup portal.\n"
    "3. On iPhone, open **Settings > Bluetooth** and select the `IOS-ANCS-*` device.\n"
    "4. Enter the device-specific six-digit code shown in the setup portal.",
)
replace_required(
    "docs/IOS_PAIRING.md",
    "After successful pairing, the ESP32 reconnects only to the stored iPhone. BOOT or **iPhone 등록 시작** requests reconnect when pairing information already exists; it does not permit a different phone to pair.",
    "After successful pairing, the ESP32 reconnects only to the stored iPhone. Setup-portal **iPhone 기기 등록**, BOOT, or Home Assistant **iPhone 등록 시작** requests reconnect when pairing information already exists; it does not permit a different phone to pair.",
)

replace_required(
    "docs/TROUBLESHOOTING.md",
    "- Open the 120-second enrollment window with BOOT for 3 seconds or Home Assistant **iPhone 등록 시작**.\n"
    "- Pair from iOS **Settings > Bluetooth**.\n"
    "- Enter PIN `설정 포털에 등록 시간 동안 표시되는 장치별 6자리 코드`.",
    "- Open the 120-second enrollment window with setup-portal **iPhone 기기 등록**, Home Assistant **iPhone 등록 시작**, or BOOT for 3 seconds.\n"
    "- Keep the setup portal open and pair from iOS **Settings > Bluetooth**.\n"
    "- Enter the device-specific six-digit code displayed in the setup portal.",
)

replace_required(
    "docs/index.html",
    "            플래시, 설정 AP, Wi-Fi/MQTT 저장, Home Assistant Discovery, iPhone\n"
    "            페어링, 알림 확인 순서로 진행합니다.",
    "            플래시, 설정 AP, Wi-Fi/MQTT 저장, 설정 포털 내 iPhone 등록,\n"
    "            Home Assistant Discovery, 알림 확인 순서로 진행합니다.",
)
replace_required(
    "docs/index.html",
    "              브라우저에서 <code>http://192.168.4.1</code>을 열고 Wi-Fi와 MQTT\n"
    "              broker 정보를 저장합니다. 이 포털은 Home Assistant 설정을 저장하지\n"
    "              않고 ESP32의 네트워크 및 MQTT 접속 정보만 저장합니다.",
    "              브라우저에서 <code>http://192.168.4.1</code>을 열고 Wi-Fi와 MQTT\n"
    "              broker 정보를 저장합니다. 같은 페이지의 <strong>iPhone 기기 등록</strong>\n"
    "              버튼으로 페이지를 떠나지 않고 등록 창을 열 수 있습니다.",
)
replace_required(
    "docs/index.html",
    "              BOOT을 3초 누르거나 Home Assistant의 <strong>iPhone 등록 시작</strong>\n"
    "              버튼을 눌러 120초 등록 창을 엽니다. iOS Bluetooth 목록에서\n"
    "              <code>IOS-ANCS-...</code> 장치를 선택하고 PIN <code>123456</code>을\n"
    "              입력한 뒤 알림 공유를 허용합니다.",
    "              설정 포털의 <strong>iPhone 기기 등록</strong>, Home Assistant의\n"
    "              <strong>iPhone 등록 시작</strong> 또는 BOOT 3초 누르기로 120초 등록 창을\n"
    "              엽니다. 포털에 표시되는 장치별 6자리 코드를 iOS Bluetooth에 입력하고\n"
    "              알림 공유를 허용합니다.",
)

# Undo the accidental release-version replacement in a historical design document.
historical_path = "docs/superpowers/plans/2026-08-10-native-ancs-app-display-name.md"
historical = subprocess.check_output(
    ["git", "show", f"origin/main:{historical_path}"], cwd=ROOT
).decode("utf-8")
write(historical_path, historical)

# Remove one-shot repair automation and diagnostics from the product branch.
for relative in (
    ".github/scripts/build_release_037.py",
    ".github/scripts/repair_037.py",
    ".github/scripts/repair_037_hotfix.py",
    ".github/scripts/finalize_037.py",
    ".github/workflows/repair-0.3.7.yml",
    ".github/workflows/finalize-0.3.7.yml",
    "build-release.log",
    "repair-source.log",
):
    path = ROOT / relative
    if path.exists():
        path.unlink()

print("firmware 0.3.7 documentation and repository cleanup applied")
