const boards = {
  esp32c6: {
    chip: "C6",
    name: "ESP32-C6",
    boot: "GPIO 9",
    validation: "COM9 실기기 검증",
    status: "HARDWARE VERIFIED",
    description:
      "v0.2.1은 알림 JSON의 각 항목을 Home Assistant 개별 센서로 생성합니다.",
    hash: "SHA256 A245826CC27C",
  },
  esp32: {
    chip: "32",
    name: "ESP32 / WROOM-32",
    boot: "GPIO 0",
    validation: "펌웨어 빌드 검증",
    status: "BUILD VERIFIED",
    description:
      "ESP32-WROOM-32와 WROOM-D32 계열을 위한 Xtensa 듀얼 코어 빌드입니다.",
    hash: "SHA256 E0B2B0F27A3C",
  },
  esp32c3: {
    chip: "C3",
    name: "ESP32-C3",
    boot: "GPIO 9",
    validation: "펌웨어 빌드 검증",
    status: "BUILD VERIFIED",
    description:
      "칩 리비전 v0.0 이상을 지원하는 ESP32-C3 Wi-Fi·BLE ANCS 브리지 빌드입니다.",
    hash: "SHA256 A04BF547337D",
  },
  esp32s3: {
    chip: "S3",
    name: "ESP32-S3",
    boot: "GPIO 0",
    validation: "펌웨어 빌드 검증",
    status: "BUILD VERIFIED",
    description:
      "USB 기능과 넉넉한 메모리를 갖춘 ESP32-S3 계열용 빌드입니다.",
    hash: "SHA256 EA6A6425DD3D",
  },
  esp32c2: {
    chip: "C2",
    name: "ESP32-C2",
    boot: "GPIO 9",
    validation: "펌웨어 빌드 검증",
    status: "BUILD VERIFIED",
    description:
      "저비용 ESP32-C2 보드를 위한 4 MB 기준 ANCS·MQTT 빌드입니다.",
    hash: "SHA256 3C80841A8E1C",
  },
  esp32c5: {
    chip: "C5",
    name: "ESP32-C5",
    boot: "GPIO 28",
    validation: "펌웨어 빌드 검증",
    status: "BUILD VERIFIED",
    description:
      "ESP32-C5의 Wi-Fi·BLE 기능에 맞춘 ANCS MQTT 브리지 빌드입니다.",
    hash: "SHA256 1808C6468E68",
  },
  esp32c61: {
    chip: "C61",
    name: "ESP32-C61",
    boot: "GPIO 9",
    validation: "펌웨어 빌드 검증",
    status: "BUILD VERIFIED",
    description:
      "ESP32-C61은 ESP32-C6의 리비전이 아니라 별도 최신 칩입니다. 실제 보드 각인이 C61인 경우에만 선택하세요.",
    hash: "SHA256 E01F3E36D66D",
  },
};

function setRuntimeStatus(elementId, lampId, supported, goodText, badText) {
  const status = document.getElementById(elementId);
  const lamp = document.getElementById(lampId);

  status.textContent = supported ? goodText : badText;
  lamp.classList.toggle("ready", supported);
  lamp.classList.toggle("blocked", !supported);
}

function updateClock() {
  const clock = document.getElementById("clock");
  clock.textContent = `${new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date())} KST`;
}

function applyBoard(target) {
  const board = boards[target];
  if (!board) return;

  document.getElementById("signal-chip").textContent = board.chip;
  document.getElementById("target-family").textContent = board.name;
  document.getElementById("target-boot").textContent = board.boot;
  document.getElementById("target-validation").textContent = board.validation;
  document.getElementById("selected-name").textContent = board.name;
  document.getElementById("selected-status").textContent = board.status;
  document.getElementById("selected-description").textContent = board.description;
  document.getElementById("build-hash").textContent = board.hash;
}

const boardSelect = document.getElementById("board-select");
boardSelect.addEventListener("change", (event) => applyBoard(event.target.value));

setRuntimeStatus(
  "secure-status",
  "secure-lamp",
  window.isSecureContext,
  "연결 안전",
  "HTTPS 필요",
);

setRuntimeStatus(
  "serial-status",
  "serial-lamp",
  "serial" in navigator,
  "설치 가능",
  "Chrome · Edge 필요",
);

applyBoard(boardSelect.value);
updateClock();
window.setInterval(updateClock, 1000);
