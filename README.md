# HA-iOS-ANCS

[English guide](README.en.md) | [GitHub 저장소](https://github.com/1bobby-git/HA-iOS-ANCS) | [브라우저 설치 페이지](https://1bobby-git.github.io/HA-iOS-ANCS/)

HA-iOS-ANCS는 전원만 연결한 ESP32 보드가 iPhone 알림을 BLE ANCS로 받아 MQTT로 전달하고, Home Assistant가 그 알림을 자동화나 엔티티로 사용할 수 있게 하는 펌웨어와 선택형 Home Assistant 동반 통합입니다.

**Apple Notification Center Service (ANCS)**: 블루투스(BLE)를 통해 아이폰 등의 iOS 기기 알림을 스마트워치나 이어폰 같은 주변 기기로 전달해 주는 애플 규격 서비스입니다.

기본 흐름:

```text
iPhone → BLE ANCS → ESP32 → Wi-Fi/MQTT → Home Assistant
```

이 프로젝트의 목표는 iOS 알림을 로컬 네트워크 안에서 MQTT 이벤트로 중계하는 것입니다. iPhone 앱을 설치하거나 Apple 계정에 접근하지 않으며, ESP32가 iOS 알림 내용을 수신한 뒤 MQTT로 게시합니다. 알림을 다시 iPhone으로 보내거나, iOS 알림 권한을 우회하거나, Home Assistant 알림을 무한 루프로 재중계하는 것은 목표가 아닙니다.

HACS는 ESP32 펌웨어를 플래시하지 않습니다. ESP32 설치는 브라우저 설치 페이지 또는 소스 빌드/플래시로 진행합니다. MQTT Discovery만으로도 Home Assistant 엔티티가 생성되며, HACS 동반 통합은 나중에 Home Assistant 쪽 경험을 보강하기 위한 선택 사항입니다. 기본 HACS 스토어 승인 여부는 이 문서에서 주장하지 않습니다.

## 지원 보드와 검증 상태

공통 펌웨어는 최소 4 MB 플래시 레이아웃을 사용합니다. ESP32-S2는 BLE가 없어서 제외됩니다. ESP32-H2는 Wi-Fi가 없고, ESP32-P4는 내장 Wi-Fi/BLE 라디오가 없어서 제외됩니다.

설치 페이지에 표시되는 모든 v0.3.3 이미지는 컴파일, 링크, 파티션 검증, 병합 factory 이미지 생성을 통과했습니다. ESP32/WROOM 계열 COM7 보드는 v0.3.3 애플리케이션 플래시, 해시 검증, 부팅, 자동 설정 AP 시작까지만 새 하드웨어 증거가 있습니다. 저장된 Wi-Fi가 테스트 위치에서 연결되지 않아 v0.3.3의 MQTT, Home Assistant Discovery, BLE enrollment, live iPhone notification capture는 아직 검증되지 않았습니다. ESP32/WROOM v0.3.2의 MQTT/BLE 증거와 ESP32-C6 v0.3.0 COM9 증거는 과거 참고용입니다.

| 대상 | 일반 모듈/보드 | Factory 이미지 | 검증 상태 |
| --- | --- | ---: | --- |
| `esp32` | ESP32-WROOM-32 / WROOM-D32 | 1,425,616 bytes | v0.3.3 COM7 플래시, 부팅, 자동 설정 AP 검증 완료; MQTT/BLE 보류 |
| `esp32c2` | ESP32-C2 | 1,445,488 bytes | v0.3.3 빌드 검증 완료 |
| `esp32c3` | ESP32-C3 | 1,634,528 bytes | v0.3.3 빌드 검증 완료 |
| `esp32c5` | ESP32-C5 | 1,779,664 bytes | v0.3.3 빌드 검증 완료 |
| `esp32c6` | ESP32-C6 | 1,779,680 bytes | v0.3.3 빌드 검증 완료; v0.3.0 하드웨어 증거는 과거 참고용 |
| `esp32c61` | ESP32-C61 | 1,722,800 bytes | v0.3.3 빌드 검증 완료 |
| `esp32s3` | ESP32-S3 | 1,407,600 bytes | v0.3.3 빌드 검증 완료 |

빌드 검증은 컴파일, 링크, 파티션, 병합 이미지 생성을 의미합니다. 하드웨어 플래시는 특정 보드와 포트에 실제 바이너리를 기록하고 해시/부팅을 확인한 증거입니다. BLE 등록은 iPhone과 ESP32의 페어링 증거이며, 실제 iPhone 알림 캡처는 알림 수신과 MQTT 게시까지 별도로 확인해야 합니다.

## 빠른 설치

5분 설치 경로:

1. 데스크톱 Chrome 또는 Edge에서 [브라우저 설치 페이지](https://1bobby-git.github.io/HA-iOS-ANCS/)를 엽니다.
2. 지원 ESP32 보드를 USB 데이터 케이블로 연결합니다. iPhone/iPad 브라우저는 USB 플래시를 할 수 없습니다.
3. 보드 모델을 선택하고 설치 버튼을 눌러 ESP Web Tools가 연결된 칩에 맞는 factory 이미지를 쓰게 합니다.
4. 설치가 끝나면 보드가 자동 설정 AP를 띄울 때까지 기다립니다.
5. `IOS-ANCS-SETUP-<SUFFIX>` Wi-Fi에 연결하고 `http://192.168.4.1`에서 Wi-Fi와 MQTT를 저장합니다.

설치 페이지는 통합 manifest `./manifests/ios-ancs.json`을 사용합니다. 사용자가 모델을 선택하면 안내 문구가 바뀌고, 실제 이미지는 ESP Web Tools가 연결 칩과 manifest를 기준으로 선택합니다. legacy C6 manifest `./manifests/esp32-c6.json`은 기존 C6 사용자와 오래된 링크를 현재 `esp32c6` v0.3.3 factory 이미지로 안내하기 위한 단일 칩 포인터입니다.

## 소스 빌드와 플래시

요구 사항:

- 지원 Wi-Fi + BLE ESP32 보드
- ESP-IDF v6.0.2 with Bluedroid
- Python 3.11 이상

Python 의존성:

```powershell
python -m pip install -r tools/requirements.txt
```

PowerShell:

```powershell
.\tools\build.ps1 -Target esp32c6
.\tools\flash.ps1 -Port COM9
```

`-Target`과 serial `-Port`는 예시입니다. 선택한 보드와 현재 감지된 포트에 맞게 바꿔야 하며, `COM9`/C6는 모든 사용자에게 적용되는 기본값이 아닙니다.

모든 지원 타깃을 빌드하고 웹 설치용 병합 이미지를 생성:

```powershell
.\tools\build_matrix.ps1
```

Linux/macOS:

```bash
./tools/build.sh
./tools/flash.sh /dev/ttyACM0
```

플래시 후 장치는 USB 전원만으로 동작하도록 설계되어 있습니다. Windows `COM9` 같은 시리얼 포트는 로그, ANCS 캡처, Unity 테스트에는 유용하지만 알림 중계 경로 자체에는 포함되지 않습니다.

## Wi-Fi와 MQTT 설정

처음 부팅했거나 `provision` NVS 파티션이 비어 있거나 유효하지 않으면 장치가 자동으로 WPA2 설정 AP를 시작합니다. BOOT 버튼을 누를 필요는 없습니다.

1. `IOS-ANCS-SETUP-<SUFFIX>`에 연결합니다.
2. 비밀번호는 `ancs-<lowercase_suffix>`입니다.
3. 브라우저에서 `http://192.168.4.1`을 엽니다.
4. Wi-Fi 스캔을 사용하거나 SSID를 직접 입력합니다.
5. MQTT host, port, 계정 정보를 입력합니다. 고급 MQTT 설정에는 권장 Client ID와 base topic이 자동으로 들어갑니다.
6. 저장 후 연결 상태를 확인합니다.

알려진 기준 보드의 base MAC suffix는 `ABC123`입니다. 이 보드는 `IOS-ANCS-SETUP-ABC123` AP와 `ancs-abc123` 비밀번호를 사용합니다. 다른 보드는 SSID에 대문자 MAC suffix를 쓰고, 설정 비밀번호에는 소문자 형식 `ancs-<lowercase_suffix>`를 씁니다. 인프라 Wi-Fi 비밀번호는 case-sensitive이며 입력한 그대로 저장됩니다.

TLS 모드는 CA 인증서가 필요합니다. 비어 있는 Wi-Fi password, MQTT password, CA 필드는 이미 저장된 secret 값을 보존합니다. 상태 API와 보고서는 secret 본문을 표시하지 않고 configured/unconfigured 플래그만 표시해야 합니다.

설정 AP는 Wi-Fi 또는 MQTT가 비정상일 때 계속 열려 있습니다. 네트워크가 준비되었지만 BLE bond가 없을 때도 열려 있습니다. 일반 Enroll 동작은 포털에 노출되지 않습니다. Home Assistant 버튼 또는 BOOT 버튼을 사용합니다. AP는 Wi-Fi, MQTT, 기존 BLE bond가 모두 준비된 뒤 닫힙니다.

## iPhone 등록

BLE 페어링은 명시적으로 열어야 합니다. bond가 없는 장치는 Enroll 창을 열기 전까지 ANCS/HID 페어링 광고를 하지 않습니다.

- 저장된 bond가 없으면 BOOT 버튼을 3초 누르거나 Home Assistant의 **iPhone 등록 시작** 버튼을 눌러 120초 페어링 창을 엽니다.
- 저장된 bond가 있으면 같은 동작은 알려진 iPhone 재연결만 요청합니다. 알 수 없는 새 휴대폰 페어링은 허용하지 않습니다.
- iOS Bluetooth 설정에서 PIN `123456`으로 페어링합니다.
- iOS가 알림 공유를 요청하면 허용합니다.

**Replace enrollment**는 현재 iPhone bond를 삭제하고 새 iPhone을 등록하려는 경우에만 사용합니다. BOOT 복구는 포털 또는 Enroll 창을 열지만 BLE bond를 삭제하지 않습니다.

## Home Assistant와 HACS

MQTT Discovery는 HACS 없이 동작합니다. 브로커에 연결되면 펌웨어가 retained Discovery config를 게시하고 Home Assistant가 장치와 엔티티를 생성합니다. HACS는 Home Assistant 동반 통합만 설치합니다. ESP32 펌웨어를 설치하거나 업데이트하지 않습니다.

HACS custom repository로 설치하려면 [HA iOS ANCS HACS My Link](https://my.home-assistant.io/redirect/hacs_repository/?owner=1bobby-git&repository=HA-iOS-ANCS&category=integration)를 열고 Home Assistant에서 저장소 추가를 확인합니다. 이 링크는 Home Assistant companion integration 설치만 준비하며, HACS 기본 스토어 승인이나 펌웨어 플래시를 의미하지 않습니다.

기존 자동화 파일:

```text
homeassistant/automation_ios_ancs_c6_relay.yaml
```

이 파일을 Home Assistant automation YAML에 복사하거나 automation package에서 include할 수 있습니다. 자동화는 MQTT Discovery의 last-notification sensor 상태 변화를 트리거로 사용하고, incomplete 또는 `pre_existing` payload를 무시하며, `unavailable`에서 복구된 전환을 거부해 오래된 `relay_id`가 재전송되지 않게 합니다. 파일 안의 `notify.mobile_app_example_phone`와 `sensor.ios_ancs_c6_ab12_ios_ancs_c6_ab12_last_notification`은 저장소 소유자 환경 예시입니다. 자동화를 켜기 전에 `service:`를 `notify.mobile_app_<your_device>`로 바꾸고, trigger `entity_id:`를 본인 Home Assistant에서 발견된 last-notification sensor로 바꿔야 합니다. 예시 모바일 알림 제목 marker는 `[C6→HA]`입니다.

펌웨어는 `app_id`가 `io.robbie.HomeAssistant`인 ANCS 이벤트를 게시하지 않습니다. 제목 marker는 운영자 가시성을 위해 남지만, loop 방지 경계는 app-level exclusion입니다. marker 유무와 관계없이 Home Assistant 알림은 MQTT로 되돌아가지 않습니다.

MQTT Discovery가 만드는 기본 엔티티:

- `장치 상태`: connectivity `binary_sensor`. Wi-Fi, MQTT, BLE가 모두 연결되었을 때만 `ON`입니다. attributes에는 `ready`, `wifi_connected`, `mqtt_connected`, `ble_connected`, `ble_bonded`, `uptime_seconds`, 한국어 `uptime`, `wifi_ssid`, `wifi_ip`, `wifi_rssi`, counters, manufacturer/model/software/hardware metadata가 포함됩니다.
- `최근 알림`: 최신 `relay_id`를 state로 유지하고 전체 notification JSON을 attributes로 노출합니다.
- `알림 제목`, `알림 내용`, `앱 이름`: 집중 notification sensor입니다. state는 255자로 잘리며 전체 원본 값은 `최근 알림`에 남습니다.
- `iPhone 등록 시작`, `장치 재시작`: non-retained Home Assistant button입니다. Restart는 정확한 `RESTART` 명령만 받습니다.

펌웨어 v0.3.3은 이전 33개 notification-field sensor와 3개 Wi-Fi sensor의 retained Discovery config를 제거하므로, 업그레이드한 장치가 오래된 엔티티를 남기지 않습니다. Discovery와 retained state에는 Wi-Fi 또는 MQTT password가 들어가지 않습니다.

Notification JSON은 원본 `app_id`를 보존하고 friendly `app_name`을 추가합니다. 알 수 없는 bundle identifier는 원본 ID로 안전하게 fallback합니다. 참고 목록은 [`docs/APP_ID_REFERENCE.md`](docs/APP_ID_REFERENCE.md)에 있습니다.

## 정상 동작과 MQTT 토픽

기본 base topic은 포털에서 설정하며 보통 다음 형식입니다.

```text
ios-ancs/<device_id>
```

게시 토픽:

```text
<base>/notification
<base>/availability
<base>/state
homeassistant/sensor/<device_id>/last_notification/config
homeassistant/sensor/<device_id>/<field>/config
homeassistant/button/<device_id>/enroll/config
homeassistant/button/<device_id>/restart/config
<base>/command/enroll
<base>/command/restart
```

계약:

- `<base>/notification`: ANCS JSON에 `relay_id`, target별 `source=<target>_ancs`, uptime을 추가합니다. QoS 1, retained false입니다.
- `<base>/availability`: `online` 또는 `offline`. QoS 1, retained true이며 LWT가 `offline`을 게시합니다.
- `<base>/state`: counters와 diagnostics. QoS 1, retained true입니다.
- Discovery configs: retained true입니다. aggregate sensor는 `relay_id`를 state로 사용하고 각 field sensor는 JSON 값 하나를 추출합니다.
- Enroll button은 정확한 payload `ENROLL`을 `<base>/command/enroll`에 QoS 1로 게시합니다. retained, partial, malformed command는 무시됩니다.
- Restart button은 정확한 payload `RESTART`를 `<base>/command/restart`에 QoS 1, non-retained로 게시합니다. retained, partial, malformed, non-exact command는 펌웨어 계약에 따라 무시됩니다.

Wi-Fi 또는 MQTT가 끊긴 동안 받은 알림은 즉시 drop되며 재연결 후 replay하지 않습니다. `pre_existing`, incomplete, invalid, duplicate, removed, Home Assistant echo로 표시된 notification은 MQTT에서 제외됩니다.

기존 C6 장치 identity는 `target=esp32c6`, `source=esp32c6_ancs`를 유지합니다. 다른 firmware target은 `target=esp32c3`, `source=esp32c3_ancs`처럼 ESP-IDF target 이름을 그대로 사용합니다.

## 업데이트, 전체 삭제, 장치 교체

일반 업데이트는 브라우저 설치 페이지에서 같은 보드 모델을 선택해 새 이미지를 플래시합니다. 저장된 Wi-Fi/MQTT/BLE 정보 보존 여부는 erase 방식에 따라 달라집니다.

전체 삭제가 필요한 경우:

- 저장된 Wi-Fi/MQTT 설정이 손상되어 설정 AP 복구가 되지 않을 때
- 잘못된 BLE bond나 iPhone 교체 상태를 완전히 초기화해야 할 때
- 장치를 다른 사용자나 다른 Home Assistant 환경으로 넘길 때

장치 교체 시에는 새 ESP32를 플래시하고, 새 설정 AP에서 Wi-Fi/MQTT를 다시 저장한 뒤, 새 iPhone 등록을 진행합니다. Home Assistant에는 새 device ID와 Discovery 엔티티가 생길 수 있습니다. 같은 broker topic을 재사용하려면 포털의 Advanced MQTT settings에서 base topic과 Client ID를 의도적으로 맞춥니다.

## 문제 해결

| 증상 | 확인할 것 |
| --- | --- |
| 브라우저에서 설치 버튼이 동작하지 않음 | 데스크톱 Chrome/Edge인지, USB 데이터 케이블인지, OS가 serial access를 막지 않는지 확인합니다. iPhone/iPad 브라우저는 플래시할 수 없습니다. |
| `IOS-ANCS-SETUP-<SUFFIX>`가 보이지 않음 | 보드 전원과 플래시 성공 여부를 확인합니다. Wi-Fi, MQTT, BLE bond가 모두 정상인 장치는 AP를 닫습니다. |
| `http://192.168.4.1`이 열리지 않음 | 설정 AP에 실제로 연결되어 있는지 확인하고 모바일 데이터/VPN을 잠시 끕니다. |
| MQTT가 연결되지 않음 | host, port, TLS CA, username/password, broker ACL, Client ID 중복을 확인합니다. |
| iPhone이 보이지 않음 | BOOT 3초 또는 Home Assistant **iPhone 등록 시작**으로 120초 Enroll 창을 열었는지 확인합니다. |
| PIN이 필요함 | `123456`을 입력합니다. |
| Home Assistant 엔티티가 없음 | MQTT integration, broker 접속, Discovery 활성화, `<base>/state`와 Discovery config retained publish를 확인합니다. HACS는 필수가 아닙니다. |
| 알림이 오지 않음 | iOS Bluetooth 알림 공유 허용, BLE 연결 상태, Wi-Fi/MQTT 연결 상태, `pre_existing` 또는 Home Assistant echo 제외 여부를 확인합니다. |
| 재연결 뒤 오래된 알림이 오지 않음 | 정상입니다. 오프라인 중 받은 알림은 replay하지 않습니다. |

시리얼 ANCS 캡처:

```powershell
python tools/verify_capture.py `
  --port COM9 `
  --baud 115200 `
  --timeout 180 `
  --output artifacts/ancs-capture.jsonl
```

위 `--port COM9`는 예시입니다. 현재 연결된 보드의 실제 serial port로 바꿔야 합니다.

MQTT broker event 검증:

```powershell
python tools/verify_mqtt_relay.py artifacts/mqtt-events.jsonl `
  --report artifacts/mqtt-relay-report.md
```

offline drop 증거가 포함된 캡처에는 `--expect-offline-drop`을 사용합니다.

## 개인정보와 보안

- 장치는 Apple 계정, iCloud, iPhone 앱 credential을 사용하지 않습니다.
- Wi-Fi password, MQTT password, TLS CA 같은 secret은 상태 API, Discovery, retained state, 보고서에 본문으로 노출하지 않습니다.
- 빈 secret 입력은 저장된 기존 값을 보존합니다.
- MQTT Discovery와 retained state에는 Wi-Fi/MQTT password가 포함되지 않습니다.
- iOS 알림 제목, 본문, 앱 이름은 MQTT broker와 Home Assistant에 게시될 수 있으므로 broker 접근 권한을 제한해야 합니다.
- 페어링 PIN 기본값은 `123456`입니다. 신뢰하는 로컬 환경에서만 Enroll 창을 열고, 장치를 넘기기 전에는 전체 erase와 새 등록을 수행합니다.

## 개발과 검증

자동 host checks:

```powershell
python -m pytest tools/tests -q
```

Firmware 및 Unity checks:

```powershell
.\tools\build.ps1
Push-Location test_app
idf.py -B build-tests build
idf.py -B build-tests -p COM9 flash monitor
Pop-Location
```

위 build/flash 예시의 target과 `COM9` 포트는 선택한 보드와 현재 감지된 serial port에 맞게 조정해야 합니다.

검증을 보고할 때는 build verification, hardware flashing, BLE enrollment, live iPhone notification capture를 구분합니다. 예를 들어 v0.3.3의 모든 공개 target은 빌드 검증을 통과했지만, 실제 하드웨어 플래시와 iPhone 알림 캡처 증거는 보드와 환경별로 따로 기록해야 합니다.
