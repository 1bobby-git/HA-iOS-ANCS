const $ = (id) => document.getElementById(id);

function setMessage(text, tone = 'info') {
  const message = $('message');
  message.textContent = text;
  message.dataset.tone = tone;
}

function setBusy(id, busy, busyLabel) {
  const button = $(id);
  if (!button.dataset.label) button.dataset.label = button.textContent;
  button.disabled = busy;
  button.textContent = busy ? busyLabel : button.dataset.label;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'content-type': 'application/json' },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || response.statusText);
  return body;
}

function deviceSuffix(apSsid) {
  const match = String(apSsid || '').match(/([0-9a-f]{4})$/i);
  return match ? match[1].toLowerCase() : 'c6';
}

function iphoneBluetoothName(apSsid) {
  return `IOS-ANCS-C6-${deviceSuffix(apSsid).toUpperCase()}`;
}

function recommendedClientId(apSsid) {
  return `ios_ancs_c6_${deviceSuffix(apSsid)}`;
}

function recommendedBaseTopic(apSsid) {
  return `ios-ancs/c6-${deviceSuffix(apSsid)}`;
}

function updateTile(id, state, value, detail) {
  $(id).dataset.state = state;
  $(`${id}-value`).textContent = value;
  $(`${id}-detail`).textContent = detail;
}

function applyStatus(status) {
  const runtime = status.runtime || {};
  const system = status.system || {};
  const config = status.config || {};
  const apName = runtime.ap_ssid || 'IOS ANCS C6';
  const bluetoothName = iphoneBluetoothName(apName);

  $('device-name').textContent = apName;

  if (runtime.sta_has_ip) {
    updateTile('status-wifi', 'ready', '연결됨', config.wifi_ssid || 'IP 주소를 받았습니다');
  } else if (runtime.sta_connecting) {
    updateTile('status-wifi', 'pending', '연결 중', config.wifi_ssid || 'Wi-Fi 응답을 기다리는 중');
  } else {
    updateTile('status-wifi', 'pending', '설정 필요', runtime.ap_started ? '아래에서 Wi-Fi를 선택하세요' : 'Wi-Fi 연결 없음');
  }

  if (system.mqtt_connected) {
    updateTile('status-mqtt', 'ready', '연결됨', config.mqtt_host || '브로커 준비 완료');
  } else if (runtime.sta_has_ip) {
    updateTile('status-mqtt', 'pending', '연결 대기', config.mqtt_host || '브로커 주소를 입력하세요');
  } else {
    updateTile('status-mqtt', 'neutral', 'Wi-Fi 필요', 'Wi-Fi 연결 후 브로커에 접속합니다');
  }

  if (system.ble_connected) {
    updateTile('status-ble', 'ready', '연결됨', 'iPhone 알림 공유 준비 완료');
    $('ble-guidance').textContent = '등록된 iPhone이 연결되어 있습니다. 전원을 다시 켜도 자동으로 재연결됩니다.';
  } else if (system.enroll_window_open) {
    updateTile('status-ble', 'pending', '등록 대기', `${bluetoothName}을 iPhone Bluetooth 설정에서 선택하세요`);
    $('ble-guidance').textContent = `등록 신호를 보내고 있습니다. iPhone Bluetooth 설정에서 ${bluetoothName}을 선택하고, 표시되면 코드 123456을 입력하세요.`;
  } else if (system.ble_bonded) {
    updateTile('status-ble', 'pending', '등록됨 · 연결 대기', '등록된 iPhone을 찾고 있습니다');
    $('ble-guidance').textContent = '등록된 iPhone만 자동으로 다시 연결됩니다. 버튼을 누르면 기존 iPhone 연결 신호를 즉시 보냅니다.';
  } else {
    updateTile('status-ble', 'neutral', '미등록 · 광고 꺼짐', '등록 시작 전에는 Bluetooth 등록 신호를 보내지 않습니다');
    $('ble-guidance').textContent = 'iPhone 등록 시작을 누르면 Bluetooth 등록 신호를 보냅니다. 이후에는 등록된 iPhone만 자동으로 다시 연결됩니다.';
  }

  const published = Number(system.notifications_published || 0);
  const dropped = Number(system.notifications_dropped || 0);
  const relayReady = runtime.sta_has_ip && system.mqtt_connected && system.ble_connected;
  updateTile(
    'status-relay',
    relayReady ? 'ready' : 'neutral',
    `${published}건 전송`,
    dropped > 0 ? `연결 장애 중 ${dropped}건 제외` : relayReady ? '새 알림을 기다리고 있습니다' : '모든 연결이 준비되면 시작됩니다',
  );

  $('wifi-ssid-manual').value = config.wifi_ssid || '';
  $('mqtt-host').value = config.mqtt_host || '';
  $('mqtt-port').value = config.mqtt_port || 1883;
  $('mqtt-username').value = config.mqtt_username || '';
  $('mqtt-tls').checked = Boolean(config.mqtt_tls);
  $('mqtt-client-id').value = config.mqtt_client_id || recommendedClientId(apName);
  $('mqtt-base-topic').value = config.mqtt_base_topic || recommendedBaseTopic(apName);

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
  const status = await fetch('/api/status').then((response) => {
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
  }
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
    setMessage('설정을 저장했습니다. 설정 AP가 잠시 종료됩니다. 연결에 실패하면 설정 AP가 자동으로 다시 나타납니다.', 'success');
    setTimeout(() => loadStatus().catch(() => {}), 1200);
  });
});

$('mqtt-test').addEventListener('click', () => runButton('mqtt-test', '테스트 중', async () => {
  await api('/api/mqtt/test', { method: 'POST', body: '{}' });
  setMessage('MQTT 연결 테스트를 시작했습니다. 잠시 후 상태를 새로고침하세요.', 'success');
}));

$('enroll').addEventListener('click', () => runButton('enroll', '등록 신호 전송 중', async () => {
  await api('/api/ble/enroll', { method: 'POST', body: '{}' });
  setMessage('iPhone 등록 신호를 시작했습니다.', 'success');
  setTimeout(() => loadStatus().catch(() => {}), 500);
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
    setMessage('Wi-Fi와 MQTT 설정을 초기화했습니다.', 'success');
  });
});

loadStatus().catch((error) => setMessage(error.message || '기기 상태를 불러오지 못했습니다.', 'error'));
