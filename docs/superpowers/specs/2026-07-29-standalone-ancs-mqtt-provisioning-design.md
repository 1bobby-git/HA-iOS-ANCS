# ESP32-C6 독립형 ANCS MQTT 릴레이 설계

상태: 사용자 설계 승인 완료  
작성일: 2026-07-29  
대상: `IOS-ANCS-C6-2B20`

## 1. 목표

ESP32-C6가 Windows COM 포트나 별도 브리지 없이 독립적으로 다음 작업을 수행한다.

1. iPhone과 BLE ANCS로 연결한다.
2. 새 iOS 알림의 상세 속성을 수신한다.
3. 저장된 Wi-Fi에 연결한다.
4. 설정된 MQTT 브로커로 알림 JSON을 발행한다.
5. Home Assistant가 MQTT 알림을 `notify.mobile_app_1bobby`로 한 번만 전달한다.
6. 릴레이가 만든 Home Assistant 알림이 다시 ANCS로 수신되어도 재발행하지 않는다.

## 2. 범위

### 포함

- Wi-Fi 미설정 시 자동 SoftAP 및 captive portal
- 주변 Wi-Fi 스캔과 자격증명 저장
- MQTT 브로커·포트·계정·TLS·CA·Client ID·토픽 설정
- Wi-Fi/MQTT/BLE 상태 표시와 설정 변경
- 명시적인 BLE Enroll과 본딩 교체
- MQTT Discovery, availability, 진단과 알림 발행
- 현재 Home Assistant에 MQTT 기반 모바일 알림 자동화 설치
- 재부팅 후 Wi-Fi, MQTT와 기존 BLE 본딩 자동 복구

### 제외

- Home Assistant REST API를 통한 알림 전송
- Wi-Fi/MQTT 장애 중 수신한 알림의 저장 또는 지연 재전송
- `pre_existing=true` 알림의 재전송
- 웹 브라우저에서 iOS BLE 페어링 자체를 완료하는 기능
- Perform Notification Action 전송
- MQTT와 REST의 동시 전송
- flash encryption, secure boot 또는 eFuse 변경

## 3. 전체 구조

```text
iPhone ANCS
    |
    v
ancs_client -> relay_policy -> mqtt_relay
                    |              |
                    |              +--> MQTT notification topic
                    |
                    +--> pre-existing/echo/invalid/drop 판단

ESP32-C6 provisioning
    |
    +--> SoftAP + DNS captive redirect + HTTP portal
    +--> Wi-Fi STA configuration
    +--> MQTT configuration
    +--> BLE Enroll control

Home Assistant
    |
    +--> MQTT Discovery sensor
    +--> relay_id 상태 변경 자동화
    +--> notify.mobile_app_1bobby
```

기존 `ancs_client`, `ancs_protocol`, `ancs_state`, `notification_sink`, `hid_server` 경계를 유지한다. 네트워크 연결과 MQTT I/O는 BLE 콜백에서 실행하지 않고 별도 큐와 작업 컨텍스트에서 처리한다.

## 4. 부팅과 프로비저닝 상태

### 4.1 부팅 판정

1. 전용 `provision` NVS 파티션을 연다.
2. 스키마 버전, 필수 필드와 CRC를 검증한다.
3. 설정이 없거나 유효하지 않으면 버튼 입력 없이 즉시 프로비저닝 모드에 진입한다.
4. 설정이 유효하면 Wi-Fi STA와 기존 본딩 재연결을 시작한다.
5. 저장된 Wi-Fi에 30초 동안 연결하지 못하면 AP+STA 프로비저닝 모드로 전환한다.
6. MQTT 연결에 실패하면 Wi-Fi STA는 유지하고 설정 AP도 유지하여 브로커 설정을 수정할 수 있게 한다.

### 4.2 설정 AP

- SSID: `IOS-ANCS-SETUP-<MAC 끝 3바이트>`
- 현재 장치 SSID: `IOS-ANCS-SETUP-572B20`
- WPA2 비밀번호: `ANCS-<MAC 끝 3바이트>`
- 현재 장치 비밀번호: `ANCS-572B20`
- AP 주소: `192.168.4.1`
- DHCP: 활성
- DNS: 모든 호스트 이름을 `192.168.4.1`로 응답
- captive portal probe: iOS와 Windows의 일반 probe URL을 포털로 리디렉션
- 외부 CDN, 글꼴 또는 인터넷 자산: 사용하지 않음

Wi-Fi와 MQTT가 모두 정상 연결되고 BLE 본딩도 존재하면 AP를 종료한다. Wi-Fi와 MQTT가 정상이더라도 BLE 본딩이 없으면 포털의 Enroll 버튼에 접근할 수 있도록 AP를 유지한다. BOOT 버튼을 3초 누르면 저장된 설정이 있어도 AP를 다시 열며, 사용자가 포털에서 닫거나 10분 동안 조작이 없으면 정상 연결·본딩 상태에서 AP를 종료한다.

## 5. 웹 포털

### 5.1 화면

단일 반응형 페이지로 다음 영역을 제공한다.

1. 장치 상태
   - 장치 이름과 MAC suffix
   - Wi-Fi STA/AP 상태와 IP
   - MQTT 연결 상태
   - BLE 본딩·연결·Enroll 상태
   - 전송 및 제외 횟수
2. Wi-Fi 설정
   - 비동기 스캔
   - SSID 선택 또는 직접 입력
   - 비밀번호 입력
3. MQTT 설정
   - 호스트
   - 포트
   - 사용자명
   - 비밀번호
   - TLS 사용 여부
   - CA 인증서 PEM
   - Client ID
   - 기본 토픽
4. 작업
   - Save & Connect
   - MQTT 연결 테스트
   - Enroll
   - Replace enrollment
   - Restart
   - Reset provisioning

비밀번호, MQTT 비밀번호와 CA 원문은 상태 API에서 반환하지 않는다. 기존 비밀 필드는 `설정됨/미설정`만 표시하고, 빈 값으로 저장하면 기존 값을 유지한다.

### 5.2 HTTP API

- `GET /api/status`
- `GET /api/wifi/scan`
- `POST /api/config`
- `POST /api/mqtt/test`
- `POST /api/ble/enroll`
- `POST /api/ble/replace`
- `POST /api/restart`
- `POST /api/reset`

상태를 바꾸는 요청은 AP 인터페이스에서만 허용한다. 요청 본문 크기와 문자열 길이를 제한하고 JSON 형식을 엄격히 검증한다.

### 5.3 설정 저장

`POST /api/config`은 다음 순서를 따른다.

1. 입력을 임시 구조체에 파싱한다.
2. 필수 필드, 길이, 포트 범위, TLS/CA 일관성을 검증한다.
3. 전용 NVS namespace에 새 버전을 기록한다.
4. 읽기 검증과 CRC 확인 후 활성 버전 포인터를 전환한다.
5. 네트워크 작업에 재연결 이벤트를 전달한다.

부분 기록 또는 전원 중단 시 마지막 정상 설정을 유지한다.

## 6. BLE Enroll과 재연결

### 6.1 본딩이 없는 장치

- 부팅 시 ANCS용 BLE 페어링 광고를 시작하지 않는다.
- BOOT 버튼 3초 또는 포털의 Enroll 버튼으로 120초 Enroll 창을 연다.
- Enroll 창에서 HID GATT 서비스 준비 후 `IOS-ANCS-C6-2B20`을 광고한다.
- iPhone 사용자는 iOS Bluetooth 설정에서 장치를 선택하고 PIN `123456`을 입력한다.
- SC+MITM+Bonding 성공 후 본딩을 저장하고 Enroll 창을 닫는다.
- 시간 초과 시 광고를 중단한다.

### 6.2 본딩이 있는 장치

- 부팅과 일시 연결 해제 후 저장된 iPhone의 재연결을 자동 허용한다.
- 새 장치의 보안 요청은 Enroll 교체가 승인되지 않은 동안 거부한다.
- 광고와 보안 요청을 현재 본딩 목록과 대조하고, 정상 재연결에서는 본딩된 identity만 허용한다.
- BOOT 버튼은 설정 AP를 열지만 기존 본딩을 삭제하지 않는다.
- Replace enrollment는 웹에서 명시적인 확인을 받은 후 기존 본딩을 삭제하고 새 120초 Enroll 창을 연다.

브라우저는 iOS ANCS 페어링을 직접 완료하지 않는다. 포털은 광고 시작, 장치 이름, PIN, 남은 시간과 연결 상태만 제공한다.

## 7. 알림 릴레이 정책

MQTT로 보낼 조건은 모두 만족해야 한다.

- `event`가 `added` 또는 `modified`
- `complete=true`
- `pre_existing=false`
- `app_id`가 비어 있지 않음
- MQTT가 현재 연결됨
- 정확히 같은 세션·UID·이벤트·내용 해시가 직전에 처리되지 않음
- echo 차단 조건에 해당하지 않음

### 7.1 Home Assistant 알림 차단

Home Assistant 자동화가 모바일 알림 제목 앞에 `[C6→HA]`를 붙인다.

다음 조건을 만족하는 ANCS 알림은 제목과 관계없이 MQTT로 보내지 않는다.

- `app_id == "io.robbie.HomeAssistant"`

따라서 릴레이 결과뿐 아니라 표식 없는 원본 Home Assistant 알림도 캡처 대상에서 제외된다. 다른 앱이 우연히 `[C6→HA]` 제목을 사용해도 제외되지 않는다.

### 7.2 장애 처리

Wi-Fi 또는 MQTT가 연결되지 않은 시점에 완성된 알림은 저장하지 않고 제외한다. 제외 횟수와 원인은 메모리 카운터에 누적하며 MQTT가 복구되면 진단 토픽에 반영한다. 해당 알림을 나중에 재전송하지 않는다.

## 8. MQTT 계약

기본 토픽은 `ios-ancs/<device_id>`이며 포털에서 변경할 수 있다.

- `<base>/notification`: 알림 JSON, QoS 1, retained false
- `<base>/availability`: `online`/`offline`, QoS 1, retained true, LWT 사용
- `<base>/state`: 연결·카운터 상태 JSON, QoS 1, retained true
- `homeassistant/sensor/<device_id>/last_notification/config`: MQTT Discovery, retained true

알림 payload는 기존 `ANCS_NOTIFICATION_JSON` 필드를 보존하고 다음 필드를 추가한다.

- `relay_id`: boot nonce, session ID, UID, event ID와 내용 해시로 만든 고유 문자열
- `source`: `esp32c6_ancs`
- `published_at_ms`: 장치 uptime 기준

Discovery sensor는 notification payload의 `relay_id`를 state로 사용하고 나머지 JSON을 attributes로 제공한다. QoS 1 재전송으로 같은 payload가 다시 도착해도 sensor state가 바뀌지 않으므로 Home Assistant 알림 자동화가 다시 실행되지 않는다.

TLS가 활성화되면 CA 인증서를 필수로 하고 인증서 검증을 비활성화하는 옵션은 제공하지 않는다.

## 9. Home Assistant 자동화

현재 Home Assistant에는 안정적인 automation ID로 자동화를 하나 설치한다.

- trigger: MQTT Discovery로 생성된 마지막 알림 sensor의 state 변경
- condition:
  - 새 state가 `unknown`/`unavailable`이 아님
  - `trigger.from_state.state != trigger.to_state.state`
  - attributes의 `complete`가 true
  - attributes의 `pre_existing`이 false
- action:
  - service: `notify.mobile_app_1bobby`
  - title: `[C6→HA] <원본 제목 또는 app_id>`
  - message: 원본 `message`, 없으면 `subtitle`, 둘 다 없으면 앱 ID와 category
- mode: queued
- max: 10

자동화는 MQTT 브로커 설정과 별개로 Home Assistant에 한 번 설치한다. 다른 Home Assistant 인스턴스로 브로커를 변경한 경우 같은 자동화를 새 인스턴스에도 설치해야 한다.

## 10. 메모리·동시성

- BLE 콜백은 기존 ANCS worker 경계를 유지한다.
- relay policy는 완성된 알림을 엄격한 최대 길이의 JSON으로 직렬화하고 소유권이 명확한 heap buffer pointer만 bounded network queue에 넣는다. 약 5KB인 `ancs_notification_t` 전체를 큐 원소에 값 복사하지 않는다.
- queue 용량은 8건이다.
- MQTT가 연결되지 않은 경우 queue에 넣지 않고 즉시 제외한다.
- MQTT 연결 중 queue가 가득 차면 새 항목을 제외하고 카운터를 증가시킨다.
- PUBACK, enqueue 실패와 연결 해제 정리 경로에서 각 buffer를 정확히 한 번 해제한다.
- 알림 payload와 CA 인증서의 최대 길이는 Kconfig로 제한한다.
- HTTP 요청 버퍼, Wi-Fi scan 결과와 MQTT payload는 수명과 소유권을 명확히 분리한다.

## 11. 파티션과 설정

실물 flash 8MB를 사용하고 기존 BLE 본딩 NVS 주소를 유지하는 사용자 파티션 테이블을 사용한다.

- 기존 `nvs`: BLE bonding과 Bluedroid 데이터 유지
- 기존 `phy_init`
- 확장된 factory app
- 별도 `provision` NVS: Wi-Fi/MQTT/portal 설정

프로비저닝 초기화는 `provision` 파티션만 지우며 BLE 본딩은 유지한다. Replace enrollment는 BLE 본딩만 지운다. 두 데이터를 모두 지우는 작업은 포털에서 별도 확인을 요구한다.

## 12. 보안 경계

- AP는 WPA2를 사용한다.
- 설정 변경 API는 AP 인터페이스에서만 허용한다.
- 비밀번호와 토큰은 로그, MQTT state와 HTTP GET 응답에 포함하지 않는다.
- MQTT TLS는 CA 검증을 강제한다.
- MQTT 비밀번호는 NVS에 저장된다.
- 이번 범위에서는 flash encryption과 secure boot를 켜지 않으므로 물리적인 flash 읽기에 대한 비밀 보호는 보장하지 않는다.
- eFuse는 변경하지 않는다.

## 13. 테스트 전략

### 13.1 호스트 자동 테스트

- 설정 schema와 CRC
- 비밀 필드 유지 규칙
- Wi-Fi/MQTT 입력 경계
- `pre_existing` 제외
- Home Assistant echo 표식 제외
- 원본 Home Assistant 알림 허용
- exact duplicate 제외
- relay ID 안정성과 boot nonce 분리
- MQTT topic/payload/Discovery 생성
- captive portal API validation

모든 새 정책 함수는 실패하는 테스트를 먼저 작성한 뒤 최소 구현으로 통과시킨다.

### 13.2 ESP32 Unity 테스트

- 프로비저닝 상태 전환
- Enroll window와 timeout
- 본딩 존재 시 신규 장치 거부
- 설정 원자적 저장·복원
- network queue 소유권과 overflow
- MQTT 연결/비연결 drop 정책

### 13.3 실기 검증

1. `provision` 설정이 없는 상태로 부팅한다.
2. 버튼 없이 설정 AP가 나타나는지 확인한다.
3. Windows 보조 Wi-Fi 어댑터와 iPhone에서 captive portal을 연다.
4. Wi-Fi scan, 저장, STA 연결과 AP 종료를 확인한다.
5. MQTT 브로커 설정, TLS/비TLS 연결과 Discovery를 확인한다.
6. BOOT과 포털 Enroll을 각각 확인한다.
7. iPhone 본딩, `ancs_ready`와 재부팅 후 자동 재연결을 확인한다.
8. 일반 앱 알림이 MQTT와 Home Assistant에 한 번 도착하는지 확인한다.
9. 표식 있는 반사 알림이 MQTT에 다시 발행되지 않는지 확인한다.
10. Wi-Fi/MQTT 장애 중 알림이 복구 후 재전송되지 않는지 확인한다.
11. 설정 AP 복구와 포털을 통한 Wi-Fi/MQTT 변경을 확인한다.

## 14. 완료 조건

- 최초 설정이 없을 때 버튼 없이 AP가 생성된다.
- iPhone과 Windows에서 포털로 Wi-Fi 및 MQTT를 변경할 수 있다.
- 명시적인 Enroll 전에는 신규 BLE 페어링 광고가 없다.
- Enroll 후 본딩과 자동 재연결이 동작한다.
- 새 iOS 알림이 MQTT와 Home Assistant 모바일 알림으로 한 번 전달된다.
- `pre_existing`, 전송 장애 중 알림과 릴레이 echo는 전달되지 않는다.
- REST 전송 경로와 Perform Notification Action 경로가 없다.
- 테스트, 빌드, 플래시와 실기 로그가 모두 증거로 저장된다.
