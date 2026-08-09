# Home Assistant iOS ANCS

[English](README.en.md) | [GitHub](https://github.com/1bobby-git/HA-iOS-ANCS) | [브라우저 설치 페이지](https://1bobby-git.github.io/HA-iOS-ANCS/)

Home Assistant iOS ANCS는 ESP32가 iPhone 알림을 BLE ANCS로 받고 MQTT로 로컬 Home Assistant에 전달하도록 만든 펌웨어와 선택형 Home Assistant companion integration입니다. MQTT Discovery만으로 기본 엔티티와 버튼이 생성되며, HACS는 Home Assistant 쪽 통합 설치만 담당합니다. ESP32 펌웨어 설치는 브라우저 설치 페이지나 소스 빌드 도구로 진행합니다.

**Apple Notification Center Service (ANCS)**: 블루투스(BLE)를 통해 아이폰 등의 iOS 기기 알림을 스마트워치나 이어폰 같은 주변 기기로 전달해 주는 애플 규격 서비스입니다

```text
iPhone → BLE ANCS → ESP32 → Wi-Fi/MQTT → Home Assistant
```

## 개발 배경

이 프로젝트는 iOS 앱이나 Apple 개발자 계정 없이, 로컬 네트워크 안에서 iOS 알림을 Home Assistant 자동화에 연결하기 위한 ESP32+MQTT 브리지입니다. ESP32는 iPhone과 직접 BLE로 페어링하고, 사용자가 입력한 Wi-Fi와 MQTT 브로커로 새 알림 이벤트를 게시합니다.

## 요구 사항

- 지원되는 Wi-Fi + BLE ESP32 보드
- 데스크톱 Chrome 또는 Edge와 USB 데이터 케이블
- 2.4 GHz Wi-Fi와 MQTT 브로커
- Home Assistant MQTT integration과 MQTT Discovery
- iPhone Bluetooth 설정에서 알림 공유 허용
- 소스 빌드 시 ESP-IDF v6.0.2 with Bluedroid, Python 3.11 이상

## 빠른 설치

1. 데스크톱 Chrome 또는 Edge에서 [브라우저 설치 페이지](https://1bobby-git.github.io/HA-iOS-ANCS/)를 열고 ESP32 보드를 USB 데이터 케이블로 연결합니다.
2. 보드 모델을 선택한 뒤 ESP Web Tools로 factory 이미지를 플래시합니다.
3. 보드가 만드는 `IOS-ANCS-SETUP-XXXXXX` Wi-Fi에 `ancs-xxxxxx` 비밀번호로 접속합니다.
4. `http://192.168.4.1` 포털에서 Wi-Fi와 MQTT 설정만 저장합니다. 이 포털은 Home Assistant나 iPhone 알림 설정을 저장하지 않습니다.
5. Home Assistant에서 MQTT Discovery로 장치가 보이면 **iPhone 등록 시작** 버튼을 눌러 120초 등록 창을 엽니다.
6. iOS Bluetooth 설정에서 장치를 선택하고 PIN `123456`을 입력한 뒤 알림 공유를 허용합니다. Home Assistant에서 `최근 알림`과 `앱 이름` 센서가 갱신되는지 확인합니다.

`XXXXXX`는 보드의 기본 Wi-Fi MAC 주소의 마지막 6자리 16진수입니다. SSID에는 대문자를 사용하고, 비밀번호에는 같은 값을 소문자로 사용합니다. 일반 형식은 `ancs-<lowercase_suffix>`이며 예시는 모델 번호가 아닙니다. 인프라 Wi-Fi 비밀번호는 case-sensitive 값으로 그대로 저장됩니다.

BOOT 버튼을 3초 눌러 설정 AP 또는 iPhone 등록 창을 엽니다. 저장된 iPhone 페어링 정보(bond)가 있으면 등록 동작은 새 휴대폰을 허용하지 않고 기존 iPhone 재연결만 요청합니다.

## Wi-Fi와 MQTT 설정

설정 AP와 `http://192.168.4.1` 포털은 Wi-Fi와 MQTT 설정만 저장합니다. `IOS-ANCS-SETUP-XXXXXX`의 `XXXXXX`는 기본 Wi-Fi MAC 주소의 마지막 6자리이며, SSID에는 대문자, `ancs-xxxxxx` 또는 일반 형식 `ancs-<lowercase_suffix>` 비밀번호에는 소문자를 사용합니다. Home Assistant 장치는 MQTT Discovery로 생성됩니다.

## iPhone 등록

Home Assistant의 **iPhone 등록 시작** 버튼이나 BOOT 버튼을 3초 눌러 120초 등록 창을 열고, iOS Bluetooth 설정에서 PIN `123456`을 입력한 뒤 알림 공유를 허용합니다. 저장된 기존 iPhone 페어링 정보가 있으면 같은 동작은 기존 iPhone 재연결만 요청합니다.

## 지원 보드와 v0.3.3 빌드 사실

공통 펌웨어는 최소 4 MB 플래시 레이아웃을 사용합니다. ESP32-S2는 BLE가 없고, ESP32-H2는 Wi-Fi가 없으며, ESP32-P4는 내장 Wi-Fi/BLE 라디오가 없어 제외됩니다.

| Target | 일반 모듈/보드 | Factory 이미지 | v0.3.3 상태 |
| --- | --- | ---: | --- |
| `esp32` | ESP32-WROOM-32 / WROOM-D32 | 1,425,616 bytes | 빌드 검증, 제한적 실보드 플래시/부팅/AP 검증 |
| `esp32c2` | ESP32-C2 | 1,445,488 bytes | 빌드 검증 |
| `esp32c3` | ESP32-C3 | 1,634,528 bytes | 빌드 검증 |
| `esp32c5` | ESP32-C5 | 1,779,664 bytes | 빌드 검증 |
| `esp32c6` | ESP32-C6 | 1,779,680 bytes | 빌드 검증, 이전 하드웨어 증거는 과거 참고 |
| `esp32c61` | ESP32-C61 | 1,722,800 bytes | 빌드 검증 |
| `esp32s3` | ESP32-S3 | 1,407,600 bytes | 빌드 검증 |

표의 상태는 공개된 v0.3.3 이미지 기준입니다. 빌드 검증, 실제 보드 플래시, BLE 등록, iPhone 알림 수신은 서로 다른 검증 범위이며 보드별 실기기 결과가 없는 항목은 빌드 검증으로만 표시합니다.

## Home Assistant와 HACS

MQTT Discovery는 HACS 없이 동작합니다. 장치가 MQTT 브로커에 연결되면 retained Discovery 설정을 게시하고 Home Assistant가 장치, `최근 알림`, `앱 이름`, 상태 센서, `iPhone 등록 시작` 버튼을 생성합니다.

HACS는 Home Assistant 동반 통합만 설치합니다. ESP32 펌웨어를 설치하거나 업데이트하지 않습니다. HACS custom repository 설치는 [HA iOS ANCS HACS My Link](https://my.home-assistant.io/redirect/hacs_repository/?owner=1bobby-git&repository=HA-iOS-ANCS&category=integration)를 열고 Home Assistant에서 저장소 추가를 확인합니다. 이 문서는 custom repository 경로만 설명하며, HACS 기본 스토어 등록을 주장하지 않습니다.

HACS 통합을 추가할 때 MQTT 기본 토픽을 입력하지 않습니다. 통합은 MQTT Discovery가 이미 등록한 `최근 알림` 센서와 장치를 찾아 사용합니다. 호환 기기가 하나면 자동으로 선택하고, 둘 이상이면 기기 이름 선택 목록을 표시합니다.

`알림` 이벤트 엔티티는 새 장치를 만들지 않고 기존 MQTT 장치에 추가됩니다. 새로 수신된 완전한 알림만 이벤트로 표시하며, Home Assistant를 다시 시작해도 retained `최근 알림` 상태를 새 알림으로 재생하지 않습니다. 기존 수동 토픽 항목은 통합의 **재구성**에서 MQTT 장치를 선택할 때까지 기존 방식으로 유지됩니다.

동반 통합은 기존 MQTT Discovery 엔터티를 변경하거나 비활성화하지 않습니다. 같은 기기에 알림 이벤트, 목적별 센서 25개와 엄격한 바이너리 센서 11개, 진단용 `원본 알림` 센서를 추가합니다. 텍스트 센서 상태는 최대 255자로 제한되며 긴 값은 `full_value` 속성에, 전체 원본 JSON은 속성에 유지됩니다. 알림 제목과 내용 같은 개인정보는 Home Assistant Recorder에 기록될 수 있으므로 기록이 필요하지 않으면 해당 엔터티를 Recorder에서 제외하세요.

MQTT Discovery의 compact model은 `최근 알림`, `알림 제목`, `알림 내용`, `앱 이름`, `장치 상태`, `장치 재시작` 엔티티를 중심으로 구성됩니다. 상태 속성에는 `ready`, `uptime_seconds`, `ble_connected`, `wifi_ssid` 같은 진단 값이 포함됩니다.

예제 자동화:

```text
homeassistant/automation_ios_ancs_c6_relay.yaml
```

사용 전에 `sensor.replace_with_your_last_notification_entity`를 본인 Home Assistant의 last-notification sensor로, `notify.replace_with_your_mobile_app_service`를 본인 mobile app notify 서비스로 바꾸세요. 예제는 새 `relay_id` 상태 변화만 전달하고, `complete=false`, `pre_existing=true`, `unknown`, `unavailable`, availability 복구 전환은 전달하지 않습니다.

알림 JSON은 원본 `app_id`를 보존하고 표시용 `app_name`을 추가합니다. 목록에 없으면 원본 ID를 그대로 표시합니다. 대표 매핑은 [App ID Reference](docs/APP_ID_REFERENCE.md)에 있습니다.

## 문제 해결

- 설치 버튼이 보이지 않거나 실패하면 데스크톱 Chrome/Edge, USB 데이터 케이블, OS serial 권한을 확인합니다. iPhone/iPad 브라우저는 USB 플래시를 할 수 없습니다.
- `IOS-ANCS-SETUP-XXXXXX`가 보이지 않으면 전원과 플래시 성공 여부를 확인하고 BOOT 버튼을 3초 눌러 복구 창을 엽니다.
- `http://192.168.4.1`이 열리지 않으면 setup AP에 실제로 연결되어 있는지 확인하고 VPN/모바일 데이터 라우팅을 잠시 끕니다.
- MQTT가 연결되지 않으면 host, port, TLS CA, username/password, ACL, 중복 Client ID를 확인합니다.
- iPhone에 장치가 보이지 않으면 `iPhone 등록 시작` 또는 BOOT 3초로 120초 등록 창을 다시 엽니다.
- PIN 요청에는 `123456`을 입력하고, iOS 알림 공유 요청을 허용합니다.
- Home Assistant 엔티티가 없으면 MQTT integration, Discovery 활성화, retained config, `<base>/state`를 확인합니다.

더 자세한 절차는 [iOS Pairing Guide](docs/IOS_PAIRING.md)와 [Troubleshooting](docs/TROUBLESHOOTING.md)를 참고하세요.

## 개인정보와 보안

- iOS 앱, Apple 계정, iCloud credential을 사용하지 않습니다.
- Wi-Fi password, MQTT password, TLS CA 본문은 상태 API, Discovery, retained state, 보고서에 평문으로 노출하지 않습니다.
- 빈 secret 입력은 저장된 기존 값을 보존합니다.
- iOS 알림 제목, 본문, 앱 이름, 앱 ID는 MQTT 브로커와 Home Assistant에 게시될 수 있으므로 broker 접근 권한을 제한하세요.
- PIN `123456`은 로컬 등록 창에서만 사용하고, 기기를 양도하기 전에는 전체 erase와 새 등록을 수행하세요.

## 개발자 참고

```powershell
python -m pip install -r tools/requirements.txt
python -m pytest tools/tests -q
python -m pytest tests -q
.\tools\build.ps1 -Target esp32c6
.\tools\flash.ps1 -Port COMx
.\tools\build_matrix.ps1
```

```bash
./tools/build.sh
./tools/flash.sh /dev/ttyACM0
```

`COMx`와 `/dev/ttyACM0`는 일반 예시입니다. 실제 보드, target, serial port에 맞게 바꾸세요. MQTT relay 검증은 `python tools/verify_mqtt_relay.py ...`, serial ANCS capture는 `python tools/verify_capture.py --port COMx ...`를 사용합니다.
