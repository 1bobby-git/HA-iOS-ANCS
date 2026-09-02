const boards = {
  esp32: {
    chip: "32",
    name: "ESP32 / WROOM-32",
    boot: "GPIO 0",
    validation: "v0.3.7 build verified",
    status: "BUILD VERIFIED",
    description: "ESP32/WROOM-32 계열용 v0.3.7 ANCS-to-MQTT factory build입니다.",
    hash: "SHA256 D022CFF91F02",
  },
  esp32c2: {
    chip: "C2",
    name: "ESP32-C2",
    boot: "GPIO 9",
    validation: "v0.3.7 build verified",
    status: "BUILD VERIFIED",
    description: "ESP32-C2 계열용 v0.3.7 ANCS-to-MQTT factory build입니다.",
    hash: "SHA256 AFC62ECF6A76",
  },
  esp32c3: {
    chip: "C3",
    name: "ESP32-C3",
    boot: "GPIO 9",
    validation: "v0.3.7 build verified",
    status: "BUILD VERIFIED",
    description: "ESP32-C3 계열용 v0.3.7 ANCS-to-MQTT factory build입니다.",
    hash: "SHA256 EB5F37B6A388",
  },
  esp32c5: {
    chip: "C5",
    name: "ESP32-C5",
    boot: "GPIO 28",
    validation: "v0.3.7 build verified",
    status: "BUILD VERIFIED",
    description: "ESP32-C5 계열용 v0.3.7 ANCS-to-MQTT factory build입니다.",
    hash: "SHA256 1C0DF5A4A104",
  },
  esp32c6: {
    chip: "C6",
    name: "ESP32-C6",
    boot: "GPIO 9",
    validation: "v0.3.7 build verified",
    status: "BUILD VERIFIED",
    description: "ESP32-C6 계열용 v0.3.7 ANCS-to-MQTT factory build입니다.",
    hash: "SHA256 B798B12EC084",
  },
  esp32c61: {
    chip: "C61",
    name: "ESP32-C61",
    boot: "GPIO 9",
    validation: "v0.3.7 build verified",
    status: "BUILD VERIFIED",
    description:
      "ESP32-C61은 ESP32-C6의 리비전이 아니라 별도 최신 칩입니다. 실제 보드 각인이 C61인 경우에 선택하세요.",
    hash: "SHA256 64C5B12340CD",
  },
  esp32s3: {
    chip: "S3",
    name: "ESP32-S3",
    boot: "GPIO 0",
    validation: "v0.3.7 build verified",
    status: "BUILD VERIFIED",
    description: "ESP32-S3 계열용 v0.3.7 ANCS-to-MQTT factory build입니다.",
    hash: "SHA256 5EFA7C87AF8C",
  },
};

function setRuntimeStatus(elementId, lampId, supported, goodText, badText) {
  const status = document.getElementById(elementId);
  const lamp = document.getElementById(lampId);

  if (!status || !lamp) return;

  status.textContent = supported ? goodText : badText;
  lamp.classList.toggle("ready", supported);
  lamp.classList.toggle("blocked", !supported);
}

function updateClock() {
  const clock = document.getElementById("clock");
  if (!clock) return;

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

if (boardSelect) {
  boardSelect.addEventListener("change", (event) => applyBoard(event.target.value));
  applyBoard(boardSelect.value);
}

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
  "Chrome 또는 Edge 필요",
);

updateClock();
window.setInterval(updateClock, 1000);
