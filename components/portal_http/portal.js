const $ = (id) => document.getElementById(id);
const STATUS_POLL_MS = 2000;
let formHydrated = false;

function setMessage(text, tone = 'info') {
  const message = $('message');
  message.textContent = text;
  message.dataset.tone = tone;
}

function setBusy(id, busy, busyLabel) {
  const button = $(id);
  if (!button.dataset.label) button.dataset.label = button.textContent;
  button.dataset.busy = busy ? 'true' : 'false';
  const requiresMqtt = button.dataset.requiresMqtt === 'true';
  const mqttConnected = document.body?.dataset?.mqttConnected === 'true';
  button.disabled = busy || (requiresMqtt && !mqttConnected);
  button.textContent = busy ? busyLabel : button.dataset.label;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'content-type': 'application/json' },
    cache: 'no-store',
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || response.statusText);
  return body;
}

const delay = (milliseconds) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

function deviceSuffix(apSsid) {
  const match = String(apSsid || '').match(/([0-9a-f]{4})$/i);
  return match ? match[1].toLowerCase() : 'c6';
}

function iphoneBluetoothName(apSsid, deviceFamily) {
  return `IOS-ANCS-${deviceFamily}-${deviceSuffix(apSsid).toUpperCase()}`;
}

function recommendedClientId(apSsid, deviceFamily) {
  return `ios_ancs_${deviceFamily.toLowerCase()}_${deviceSuffix(apSsid)}`;
}

function recommendedBaseTopic(apSsid, deviceFamily) {
  return `ios-ancs/${deviceFamily.toLowerCase()}-${deviceSuffix(apSsid)}`;
}

function updateTile(id, state, value, detail) {
  $(id).dataset.state = state;
  $(`${id}-value`).textContent = value;
  $(`${id}-detail`).textContent = detail;
}

function updateEnrollmentControls(system, blePasskey) {
  const button = $('start-enrollment');
  const code = $('ble-enroll-code');
  const codeValue = $('ble-enroll-code-value');
  const busy = button.dataset.busy === 'true';
  const windowOpen = Boolean(system.enroll_window_open);
  code.hidden = !windowOpen;
  codeValue.textContent = blePasskey || '확인 중';

  let label = 'iPhone 기기 등록';
  let unavailable = false;
  if (system.ble_pairing_repair_required) {
    label = '등록 교체 필요';
    unavailable = true;
  } else if (system.ble_connected) {
    label = 'iPhone 연결됨';
    unavailable = true;
  } else if (windowOpen) {
    label = '등록 신호 다시 보내기';
  } else if (system.ble_bonded) {
    label = '등록된 iPhone 다시 연결';
  }
  if (!busy) {
    button.textContent = label;
    button.dataset.label = label;
  }
  button.disabled = busy || unavailable;
}

function mqttEndpoint(config) {
  const host = config.mqtt_host || '브로커 주소 미설정';
  const port = Number(config.mqtt_port || 1883);
  return `${host}:${port} · ${config.mqtt_tls ? 'TLS' : 'TCP'}`;
}

function mqttErrorDetail(system, config) {
  const endpoint = mqttEndpoint(config);
  const type = Number(system.mqtt_error_type || 0);
  const espError = Number(system.mqtt_last_esp_error || 0);
  const socketError = Number(system.mqtt_last_socket_errno || 0);
  const returnCode = Number(system.mqtt_connect_return_code || 0);
  const retrySeconds = Math.max(
    0,
    Math.round(Number(system.mqtt_retry_delay_ms || 0) / 1000),
  );
  const retry = retrySeconds > 0 ? ` · ${retrySeconds}초 후 재시도` : '';

  if (type === 2) {
    if (returnCode === 4 || returnCode === 5) {
      return `${endpoint} · 사용자 이름 또는 비밀번호가 거부됨${retry}`;
    }
    if (returnCode === 2) {
      return `${endpoint} · Client ID가 거부됨${retry}`;
    }
    if (returnCode === 3) {
      return `${endpoint} · 브로커 사용 불가${retry}`;
    }
    return `${endpoint} · 브로커 연결 거부 코드 ${returnCode}${retry}`;
  }

  if (type === 1 || espError || socketError) {
    if (espError === 32774 || socketError === 110) {
      return `${endpoint} · TCP 연결 시간 초과${retry}`;
    }
    if (socketError === 111 || socketError === 61) {
      return `${endpoint} · 포트 연결 거부${retry}`;
    }
    if (socketError === 101 || socketError === 113) {
      return `${endpoint} · ESP32 네트워크에서 서버까지 경로 없음${retry}`;
    }
    return `${endpoint} · 전송 오류 ESP ${espError}, socket ${socketError}${retry}`;
  }

  return `${endpoint}${retry}`;
}

function relayDropBreakdown(system = {}) {
  const detailKeys = [
    'notifications_dropped_offline',
    'notifications_dropped_enqueue',
    'notifications_dropped_policy',
  ];
  const hasDetailedCounters = detailKeys.some((key) =>
    Object.prototype.hasOwnProperty.call(system, key),
  );
  const offline = Number(system.notifications_dropped_offline || 0);
  const enqueue = Number(system.notifications_dropped_enqueue || 0);
  const policy = Number(system.notifications_dropped_policy || 0);
  const calculatedTotal = offline + enqueue + policy;
  const total = Number(system.notifications_dropped ?? calculatedTotal);
  if (total <= 0) {
    return { total: 0, offline, enqueue, policy, detail: null };
  }
  if (!hasDetailedCounters) {
    return {
      total,
      offline,
      enqueue,
      policy,
      detail: `부팅 후 제외 ${total}건 · 이전 펌웨어는 제외 원인을 구분하지 않습니다`,
    };
  }
  const reasons = [];
  if (offline > 0) reasons.push(`MQTT 미연결 ${offline}건`);
  if (policy > 0) reasons.push(`정책 필터 ${policy}건`);
  if (enqueue > 0) reasons.push(`내부 처리 실패 ${enqueue}건`);
  const unclassified = Math.max(0, total - calculatedTotal);
  if (unclassified > 0) reasons.push(`기타 ${unclassified}건`);
  return {
    total,
    offline,
    enqueue,
    policy,
    detail: `부팅 후 제외 ${total}건${reasons.length ? ` · ${reasons.join(' · ')}` : ''}`,
  };
}

function hydrateForm(status, apName, deviceFamily) {
  if (formHydrated) return;
  const config = status.config || {};
  $('wifi-ssid-manual').value = config.wifi_ssid || '';
  $('mqtt-host').value = config.mqtt_host || '';
  $('mqtt-port').value = config.mqtt_port || 1883;
  $('mqtt-username').value = config.mqtt_username || '';
  $('mqtt-tls').checked = Boolean(config.mqtt_tls);
  $('mqtt-client-id').value =
    config.mqtt_client_id || recommendedClientId(apName, deviceFamily);
  $('mqtt-base-topic').value =
    config.mqtt_base_topic || recommendedBaseTopic(apName, deviceFamily);
  formHydrated = true;
}

function applyStatus(status) {
  const runtime = status.runtime || {};
  const system = status.system || {};
  const config = status.config || {};
  const target = String(status.target || 'esp32c6').toLowerCase();
  const deviceFamily = String(status.device_family || 'C6').toUpperCase();
  const apName = runtime.ap_ssid || 'IOS-ANCS-SETUP';
  const bluetoothName = iphoneBluetoothName(apName, deviceFamily);
  const passkeyValue = Number(system.ble_passkey || 0);
  const blePasskey = Number.isInteger(passkeyValue) &&
    passkeyValue >= 100000 && passkeyValue <= 999999
    ? String(passkeyValue).padStart(6, '0')
    : null;

  if (document.body?.dataset) {
    document.body.dataset.target = target;
    document.body.dataset.mqttConnected =
      system.mqtt_connected ? 'true' : 'false';
  }

  $('device-name').textContent = apName;

  if (runtime.sta_has_ip) {
    updateTile('status-wifi', 'ready', '연결됨', config.wifi_ssid || 'IP 주소를 받았습니다');
  } else if (runtime.sta_connecting) {
    updateTile('status-wifi', 'pending', '연결 중', config.wifi_ssid || 'Wi-Fi 응답을 기다리는 중');
  } else {
    updateTile('status-wifi', 'pending', '설정 필요', runtime.ap_started ? '아래에서 Wi-Fi를 선택하세요' : 'Wi-Fi 연결 없음');
  }

  if (system.mqtt_connected) {
    updateTile('status-mqtt', 'ready', '연결됨', mqttEndpoint(config));
  } else if (system.mqtt_connecting) {
    updateTile('status-mqtt', 'pending', '연결 중', mqttEndpoint(config));
  } else if (runtime.sta_has_ip && Number(system.mqtt_last_error_at_ms || 0) > 0) {
    updateTile('status-mqtt', 'error', '연결 실패', mqttErrorDetail(system, config));
  } else if (runtime.sta_has_ip) {
    updateTile('status-mqtt', 'pending', '연결 대기', mqttErrorDetail(system, config));
  } else {
    updateTile('status-mqtt', 'neutral', 'Wi-Fi 필요', 'Wi-Fi 연결 후 브로커에 접속합니다');
  }

  if (system.ble_connected) {
    updateTile('status-ble', 'ready', '연결됨', 'iPhone 알림 공유 준비 완료');
    $('ble-guidance').textContent = '등록된 iPhone이 연결되어 있습니다. 전원을 다시 켜도 자동으로 재연결됩니다.';
  } else if (system.ble_pairing_repair_required) {
    updateTile(
      'status-ble',
      'error',
      '등록 복구 필요',
      `인증 오류 ${Number(system.ble_auth_error || 0)} · iPhone의 기존 Bluetooth 등록을 지우세요`,
    );
    $('ble-guidance').textContent =
      '반복 인증 실패로 자동 재연결을 중지했습니다. iPhone 설정 > Bluetooth에서 기존 IOS-ANCS 항목을 지운 뒤, 아래의 iPhone 등록 교체를 실행하세요.';
  } else if (system.enroll_window_open) {
    updateTile(
      'status-ble',
      'pending',
      '등록 대기',
      blePasskey
        ? `${bluetoothName} · 고정 PIN ${blePasskey}`
        : `${bluetoothName}을 iPhone Bluetooth 설정에서 선택하세요`,
    );
    $('ble-guidance').textContent = blePasskey
      ? `등록 신호를 보내고 있습니다. iPhone Bluetooth 설정에서 ${bluetoothName}을 선택하고 고정 PIN ${blePasskey}를 입력하세요.`
      : `등록 신호를 보내고 있습니다. iPhone Bluetooth 설정에서 ${bluetoothName}을 선택하고 고정 PIN 123456을 입력하세요.`;
  } else if (system.ble_bonded) {
    updateTile('status-ble', 'pending', '등록됨 · 연결 대기', '등록된 iPhone을 찾고 있습니다');
    $('ble-guidance').textContent = '등록된 iPhone만 자동으로 다시 연결됩니다. 이 페이지의 버튼으로 재연결 신호를 다시 보낼 수 있습니다.';
  } else {
    updateTile('status-ble', 'neutral', '미등록 · 광고 꺼짐', '등록 시작 전에는 Bluetooth 등록 신호를 보내지 않습니다');
    $('ble-guidance').textContent = '이 페이지의 iPhone 기기 등록 버튼을 누르면 Bluetooth 등록 신호를 보냅니다.';
  }

  updateEnrollmentControls(system, blePasskey);

  const published = Number(system.notifications_published || 0);
  const dropStats = relayDropBreakdown(system);
  const relayReady = runtime.sta_has_ip && system.mqtt_connected && system.ble_connected;
  const relayState = relayReady
    ? 'ready'
    : system.mqtt_connected || system.mqtt_connecting
      ? 'pending'
      : runtime.sta_has_ip
        ? 'error'
        : 'neutral';
  updateTile(
    'status-relay',
    relayState,
    `${published}건 전송`,
    dropStats.detail
      || (system.mqtt_connected
        ? '테스트 알림 또는 iPhone 알림을 기다리고 있습니다'
        : 'MQTT 연결이 준비되면 Discovery가 자동 발행됩니다'),
  );

  const testButton = $('test-notification');
  testButton.dataset.requiresMqtt = 'true';
  if (testButton.dataset.busy !== 'true') {
    testButton.disabled = !system.mqtt_connected;
  }

  hydrateForm(status, apName, deviceFamily);

  $('wifi-password-help').textContent = config.wifi_password_configured
    ? '저장된 비밀번호가 있습니다. 변경할 때만 새로 입력하세요.'
    : '암호가 없는 네트워크는 비워 두세요.';
  $('mqtt-password-help').textContent = config.mqtt_password_configured
    ? '저장된 비밀번호가 있습니다. 변경할 때만 새로 입력하세요.'
    : '브로커에 비밀번호가 없으면 비워 두세요.';
  $('mqtt-ca-help').textContent = config.mqtt_ca_configured
    ? '저장된 CA 인증서가 있습니다. 변경할 때만 새로 입력하세요.'
    : 'TLS를 켜면 CA 인증서가 필요합니다.';
  toggleTlsField();
}

async function loadStatus() {
  const status = await fetch('/api/status', { cache: 'no-store' }).then((response) => {
    if (!response.ok) throw new Error(response.statusText);
    return response.json();
  });
  applyStatus(status);
  return status;
}

function toggleTlsField() {
  $('mqtt-ca-field').hidden = !$('mqtt-tls').checked;
}

async function runButton(id, busyLabel, action) {
  setBusy(id, true, busyLabel);
  try {
    await action();
  } catch (error) {
    setMessage(error.message || '요청을 처리하지 못했습니다.', 'error');
  } finally {
    setBusy(id, false, busyLabel);
    loadStatus().catch(() => {});
  }
}

async function waitForMqttResult(maxAttempts = 16) {
  let latest = null;
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    await delay(1000);
    latest = await loadStatus();
    if (latest.system?.mqtt_connected) return latest;
    if (
      Number(latest.system?.mqtt_last_error_at_ms || 0) > 0 &&
      !latest.system?.mqtt_connecting
    ) {
      throw new Error(mqttErrorDetail(latest.system, latest.config || {}));
    }
  }
  throw new Error(
    latest
      ? `브로커 응답을 받지 못했습니다. ${mqttErrorDetail(latest.system || {}, latest.config || {})}`
      : '브로커 응답을 받지 못했습니다.',
  );
}

$('refresh-status').addEventListener('click', () => runButton('refresh-status', '확인 중', async () => {
  await loadStatus();
  setMessage('현재 연결 상태를 새로 확인했습니다.', 'success');
}));

$('scan-wifi').addEventListener('click', () => runButton('scan-wifi', '검색 중', async () => {
  const result = await fetch('/api/wifi/scan').then((response) => {
    if (!response.ok) throw new Error(response.statusText);
    return response.json();
  });
  const select = $('wifi-ssid');
  select.innerHTML = '';
  const aps = result.aps || [];
  if (aps.length === 0) {
    const option = document.createElement('option');
    option.value = '';
    option.textContent = '검색된 네트워크가 없습니다';
    select.appendChild(option);
    setMessage('Wi-Fi를 찾지 못했습니다. SSID를 직접 입력할 수 있습니다.', 'error');
    return;
  }
  for (const ap of aps) {
    const option = document.createElement('option');
    option.value = ap.ssid;
    option.textContent = `${ap.ssid} · ${ap.rssi} dBm`;
    select.appendChild(option);
  }
  $('wifi-ssid-manual').value = '';
  setMessage(`${aps.length}개의 Wi-Fi를 찾았습니다.`, 'success');
}));

$('wifi-ssid').addEventListener('change', () => {
  if ($('wifi-ssid').value) $('wifi-ssid-manual').value = '';
});

$('wifi-ssid-manual').addEventListener('input', () => {
  if ($('wifi-ssid-manual').value.trim()) $('wifi-ssid').value = '';
});

$('mqtt-tls').addEventListener('change', toggleTlsField);

$('mqtt-config').addEventListener('submit', async (event) => {
  event.preventDefault();
  const ssid = $('wifi-ssid-manual').value.trim() || $('wifi-ssid').value;
  if (!ssid) {
    setMessage('연결할 Wi-Fi를 검색하거나 SSID를 직접 입력하세요.', 'error');
    $('wifi-ssid').focus();
    return;
  }

  const payload = {
    wifi_ssid: ssid,
    wifi_password: $('wifi-password').value,
    mqtt_host: $('mqtt-host').value.trim(),
    mqtt_port: Number($('mqtt-port').value),
    mqtt_username: $('mqtt-username').value.trim(),
    mqtt_password: $('mqtt-password').value,
    mqtt_tls: $('mqtt-tls').checked,
    mqtt_ca: $('mqtt-ca').value.trim(),
    mqtt_client_id: $('mqtt-client-id').value.trim(),
    mqtt_base_topic: $('mqtt-base-topic').value.trim(),
  };

  await runButton('save-connect', '저장 중', async () => {
    await api('/api/config', { method: 'POST', body: JSON.stringify(payload) });
    formHydrated = false;
    setMessage('설정을 저장하고 연결을 시작했습니다. 설정 포털은 테스트를 위해 10분간 유지됩니다. 연결에 실패하면 설정 AP가 자동으로 다시 나타납니다. 구체적인 원인이 이 페이지에 표시됩니다.', 'success');
    setTimeout(() => loadStatus().catch(() => {}), 1200);
  });
});

$('mqtt-test').addEventListener('click', () => runButton('mqtt-test', '연결 확인 중', async () => {
  await api('/api/mqtt/test', { method: 'POST', body: '{}' });
  setMessage('MQTT 연결 결과를 확인하고 있습니다.', 'info');
  await waitForMqttResult();
  setMessage('MQTT 브로커 연결과 Home Assistant Discovery 발행이 완료되었습니다.', 'success');
}));

$('test-notification').addEventListener('click', () => runButton('test-notification', '전송 확인 중', async () => {
  const before = await loadStatus();
  const publishedBefore = Number(before.system?.notifications_published || 0);
  await api('/api/notification/test', { method: 'POST', body: '{}' });

  for (let attempt = 0; attempt < 20; attempt += 1) {
    await delay(500);
    const current = await loadStatus();
    if (Number(current.system?.notifications_published || 0) > publishedBefore) {
      setMessage('테스트 알림을 MQTT로 전송했습니다. Home Assistant의 최근 알림 센서를 확인하세요.', 'success');
      return;
    }
  }
  throw new Error('테스트 알림을 큐에 넣었지만 MQTT 전송 확인을 받지 못했습니다.');
}));

$('start-enrollment').addEventListener('click', () => runButton('start-enrollment', '등록 시작 중', async () => {
  await api('/api/ble/enroll', { method: 'POST', body: '{}' });
  const status = await loadStatus();
  const passkey = Number(status.system?.ble_passkey || 0);
  const code = Number.isInteger(passkey) && passkey >= 100000 && passkey <= 999999
    ? String(passkey).padStart(6, '0')
    : null;
  setMessage(
    code
      ? `iPhone 등록을 시작했습니다. 이 페이지에 표시된 고정 PIN ${code}를 iPhone Bluetooth 등록 창에 입력하세요.`
      : 'iPhone 등록 신호를 시작했습니다. 상태 카드가 갱신될 때까지 현재 페이지를 유지하세요.',
    'success',
  );
}));

$('replace-enrollment').addEventListener('click', () => {
  const confirmation = $('replace-confirmation').value;
  if (confirmation !== 'REPLACE ENROLLMENT') {
    setMessage('REPLACE ENROLLMENT를 정확히 입력하세요.', 'error');
    return;
  }
  runButton('replace-enrollment', '교체 중', async () => {
    await api('/api/ble/replace', {
      method: 'POST',
      body: JSON.stringify({ confirmation }),
    });
    $('replace-confirmation').value = '';
    setMessage('기존 iPhone 등록을 지우고 새 등록을 시작했습니다.', 'success');
  });
});

$('restart').addEventListener('click', () => runButton('restart', '재시작 요청 중', async () => {
  await api('/api/restart', { method: 'POST', body: '{}' });
  setMessage('기기 재시작을 요청했습니다.', 'success');
}));

$('reset-provisioning').addEventListener('click', () => {
  const confirmation = $('reset-confirmation').value;
  if (confirmation !== 'RESET PROVISIONING') {
    setMessage('RESET PROVISIONING을 정확히 입력하세요.', 'error');
    return;
  }
  runButton('reset-provisioning', '초기화 중', async () => {
    await api('/api/reset', {
      method: 'POST',
      body: JSON.stringify({ confirmation }),
    });
    $('reset-confirmation').value = '';
    formHydrated = false;
    setMessage('Wi-Fi와 MQTT 설정을 초기화했습니다.', 'success');
  });
});

loadStatus().catch((error) => setMessage(error.message || '기기 상태를 불러오지 못했습니다.', 'error'));

if (typeof window !== 'undefined') {
  window.setInterval(() => {
    if (!document.hidden) loadStatus().catch(() => {});
  }, STATUS_POLL_MS);
}
