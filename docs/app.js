const boards = [
  {
    id: "esp32-c6",
    order: "BOARD / 001",
    chip: "C6",
    name: "ESP32-C6",
    status: "검증 완료",
    description: "iPhone ANCS 알림을 Wi-Fi와 MQTT로 전달하는 현재 검증 펌웨어입니다.",
    specs: ["8 MB FLASH", "BLE 5", "Wi-Fi 6"],
    version: "v0.1.0 · ESP-IDF 6.0.2 · SHA256 1F4EC9D1…",
    manifest: "./manifests/esp32-c6.json",
    available: true,
  },
  {
    id: "esp32-wroom-32",
    order: "BOARD / 002",
    chip: "D32",
    name: "ESP32-WROOM-32",
    status: "준비 중",
    description: "클래식 ESP32 WROOM-D32 보드를 위한 전용 빌드와 검증 슬롯입니다.",
    specs: ["ESP32", "BT CLASSIC", "2.4 GHz"],
    available: false,
  },
  {
    id: "esp32-c3",
    order: "BOARD / 003",
    chip: "C3",
    name: "ESP32-C3",
    status: "준비 중",
    description: "소형 RISC-V ESP32-C3 보드를 위한 전용 빌드와 검증 슬롯입니다.",
    specs: ["RISC-V", "BLE 5", "2.4 GHz"],
    available: false,
  },
];

function boardCard(board) {
  const action = board.available
    ? `
      <esp-web-install-button manifest="${board.manifest}">
        <button class="install-button" slot="activate" type="button">
          C6 펌웨어 설치 →
        </button>
        <span class="installer-message" slot="unsupported">
          이 브라우저는 USB 설치를 지원하지 않습니다. Windows Chrome 또는 Edge를 사용하세요.
        </span>
        <span class="installer-message" slot="not-allowed">
          USB 설치는 HTTPS 또는 localhost에서만 실행할 수 있습니다.
        </span>
      </esp-web-install-button>
      <p class="card-build">${board.version}</p>
    `
    : `
      <button class="planned-button" type="button" disabled>
        전용 펌웨어 준비 중
      </button>
      <p class="card-build">검증된 바이너리가 등록되면 활성화됩니다.</p>
    `;

  return `
    <article class="board-card ${board.available ? "available" : "planned"}" id="${board.id}">
      <div class="card-index">
        <span>${board.order}</span>
        <span class="card-status">${board.status}</span>
      </div>
      <div class="chip-diagram" aria-hidden="true">${board.chip}</div>
      <h3>${board.name}</h3>
      <p class="board-description">${board.description}</p>
      <ul class="spec-list" aria-label="${board.name} 사양">
        ${board.specs.map((spec) => `<li>${spec}</li>`).join("")}
      </ul>
      <div class="install-wrap">${action}</div>
    </article>
  `;
}

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

document.getElementById("board-grid").innerHTML = boards.map(boardCard).join("");

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

updateClock();
window.setInterval(updateClock, 1000);
