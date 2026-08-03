from pathlib import Path


CLIENT_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "components"
    / "ancs_client"
    / "ancs_client.c"
)
CLIENT_HEADER = (
    Path(__file__).resolve().parents[2]
    / "components"
    / "ancs_client"
    / "include"
    / "ancs_client.h"
)
ENROLL_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "components"
    / "ble_enroll"
    / "ble_enroll.c"
)


def _function_body(source, signature, next_signature):
    start_marker = f"{signature}\n{{"
    assert start_marker in source, f"missing function definition: {signature}"
    remainder = source.split(start_marker, 1)[1]
    assert next_signature in remainder, (
        f"missing next function marker after {signature}: {next_signature}"
    )
    return remainder.split(next_signature, 1)[0]


def _assert_guard_returns_before(body, guard_expression, guarded_call):
    assert guard_expression in body
    assert guarded_call in body
    guard_prefix = body[body.index(guard_expression): body.index(guarded_call)]
    assert "return;" in guard_prefix


def test_ancs_uses_sc_mitm_with_user_entered_passkey():
    source = CLIENT_SOURCE.read_text(encoding="utf-8")

    assert (
        "esp_ble_auth_req_t auth_request = ESP_LE_AUTH_REQ_SC_MITM_BOND;"
        in source
    )
    assert "esp_ble_io_cap_t io_capability = ESP_IO_CAP_OUT;" in source
    assert "uint32_t static_passkey = 123456U;" in source
    assert "ESP_BLE_SM_SET_STATIC_PASSKEY" in source
    assert "ESP_BLE_SEC_ENCRYPT_MITM" in source

    # The device has no trusted Yes/No input, so numeric comparison must not
    # be silently accepted by firmware.
    assert "parameter->ble_security.ble_req.bd_addr, false" in source


def test_security_request_uses_current_bluedroid_bond_list():
    source = CLIENT_SOURCE.read_text(encoding="utf-8")

    assert "static bool bond_list_contains_peer" in source
    assert "esp_ble_get_bond_device_num()" in source
    assert "esp_ble_get_bond_device_list(&list_count, bond_list)" in source
    assert "memcmp(bond_list[index].bd_addr, peer_addr, ESP_BD_ADDR_LEN) == 0" in source
    assert "bond_list_contains_peer(parameter->ble_security.ble_req.bd_addr)" in source
    assert "esp_ble_gap_security_rsp(\n            parameter->ble_security.ble_req.bd_addr, allowed)" in source
    assert "esp_ble_gap_disconnect(parameter->ble_security.ble_req.bd_addr)" in source


def test_replace_confirmation_and_status_contract():
    source = CLIENT_SOURCE.read_text(encoding="utf-8")
    header = CLIENT_HEADER.read_text(encoding="utf-8")
    enroll = ENROLL_SOURCE.read_text(encoding="utf-8")

    assert "return ESP_ERR_INVALID_STATE;" in enroll
    assert "return ESP_ERR_INVALID_STATE;" in source
    assert "ancs_client_enrollment_status_t" in header
    assert "ancs_client_get_enrollment_status(void)" in header
    assert "bool replace_pending;" in header
    assert "esp_err_t last_replace_error;" in header
    assert "int bond_count;" in header
    assert "ancs_client_replace_pending(void)" in header
    assert "ancs_client_last_replace_error(void)" in header
    assert "ancs_client_bond_count(void)" in header
    assert "s_client.replace_pending = true;" in source
    assert "s_client.last_replace_error = error;" in source


def test_plain_enroll_with_existing_bond_does_not_open_pairing_window():
    source = CLIENT_SOURCE.read_text(encoding="utf-8")
    enroll = ENROLL_SOURCE.read_text(encoding="utf-8")

    assert "if (state->has_bond)" in enroll
    assert "ble_enroll_close_window(state);" in enroll
    assert "if (current_bond_count() > 0 || ancs_client_has_bond())" in source
    assert "ble_enroll_close_window(&s_enroll);" in source
    assert "load_existing_ble_bond();" in source
    assert "start_advertising();" in source
    assert "esp_timer_start_once(\n        s_client.enroll_timer" in source


def test_every_advertising_entry_point_is_guarded_by_enrollment_policy():
    source = CLIENT_SOURCE.read_text(encoding="utf-8")
    enroll = ENROLL_SOURCE.read_text(encoding="utf-8")

    should_advertise = _function_body(
        enroll,
        "bool ble_enroll_should_advertise(const ble_enroll_state_t *state, int64_t now_ms)",
        "bool ble_enroll_pairing_allowed",
    )
    assert "state != NULL" in should_advertise
    assert "state->has_bond || ble_enroll_window_active(state, now_ms)" in should_advertise

    assert source.count("esp_ble_gap_start_advertising(") == 1
    start_advertising = _function_body(
        source,
        "static void start_advertising(void)",
        "static void stop_advertising(void)",
    )
    _assert_guard_returns_before(
        start_advertising,
        "!ble_enroll_should_advertise(&s_enroll, now_ms())",
        "esp_ble_gap_start_advertising",
    )

    schedule_retry = _function_body(
        source,
        "static void schedule_advertising_retry(void)",
        "static void schedule_discovery_retry(void)",
    )
    _assert_guard_returns_before(
        schedule_retry,
        "!ble_enroll_should_advertise(&s_enroll, now_ms())",
        "esp_timer_start_once",
    )

    public_start = _function_body(
        source,
        "esp_err_t ancs_client_start_advertising(void)",
        "esp_err_t ancs_client_stop_advertising",
    )
    assert "!enroll_should_advertise_now()" in public_start
    assert "return ESP_ERR_INVALID_STATE;" in public_start[
        public_start.index("!enroll_should_advertise_now()"):
        public_start.index("start_advertising();")
    ]
    assert "esp_ble_gap_start_advertising(" not in public_start
    assert "start_advertising();" in public_start

    should_advertise_now = _function_body(
        source,
        "static bool enroll_should_advertise_now(void)",
        "static int current_bond_count",
    )
    assert "ble_enroll_should_advertise(&s_enroll, now)" in should_advertise_now

    request_enroll = _function_body(
        source,
        "esp_err_t ancs_client_request_enroll(void)",
        "esp_err_t ancs_client_replace_enrollment",
    )
    assert "if (current_bond_count() > 0 || ancs_client_has_bond())" in request_enroll
    assert "ble_enroll_close_window(&s_enroll);" in request_enroll
    assert "load_existing_ble_bond();" in request_enroll
    assert "ble_enroll_open_window(&s_enroll, now)" in request_enroll
    assert request_enroll.index("current_bond_count()") < request_enroll.index(
        "ble_enroll_open_window"
    )


def test_hid_ancs_device_advertises_from_the_public_controller_address():
    source = CLIENT_SOURCE.read_text(encoding="utf-8")
    adv_params = source.split(
        "static esp_ble_adv_params_t s_adv_params = {", 1
    )[1].split("};", 1)[0]

    assert ".own_addr_type = BLE_ADDR_TYPE_PUBLIC," in adv_params
    assert "connection.own_addr_type = s_adv_params.own_addr_type;" in source


def test_connect_and_terminal_events_are_bound_to_the_accepted_peer():
    source = CLIENT_SOURCE.read_text(encoding="utf-8")

    connect_case = source.split("case ESP_GATTC_CONNECT_EVT:", 1)[1].split(
        "case ESP_GATTC_OPEN_EVT:", 1
    )[0]
    assert "connection_peer_allowed(parameter->connect.remote_bda)" in connect_case
    assert connect_case.index("connection_peer_allowed") < connect_case.index(
        "s_client.connected = true;"
    )
    assert "esp_ble_gap_disconnect(parameter->connect.remote_bda)" in connect_case

    open_case = source.split("case ESP_GATTC_OPEN_EVT:", 1)[1].split(
        "case ESP_GATTC_CFG_MTU_EVT:", 1
    )[0]
    assert (
        "connection_event_matches(\n"
        "                parameter->open.conn_id,\n"
        "                parameter->open.remote_bda)"
    ) in open_case
    assert open_case.index("connection_event_matches") < open_case.index(
        "s_client.conn_id = parameter->open.conn_id;"
    )

    disconnect_case = source.split("case ESP_GATTC_DISCONNECT_EVT:", 1)[1].split(
        "default:", 1
    )[0]
    assert "connection_event_matches(" in disconnect_case
    assert "parameter->disconnect.conn_id" in disconnect_case
    assert "parameter->disconnect.remote_bda" in disconnect_case
    assert disconnect_case.index("connection_event_matches") < disconnect_case.index(
        "reset_connection_session();"
    )

    auth_case = source.split("case ESP_GAP_BLE_AUTH_CMPL_EVT:", 1)[1].split(
        "case ESP_GAP_BLE_REMOVE_BOND_DEV_COMPLETE_EVT:", 1
    )[0]
    assert "authentication_event_matches(" in auth_case
    assert auth_case.index("authentication_event_matches") < auth_case.index(
        "s_client.auth_error"
    )
    assert "reset_connection_session();" in auth_case


def test_failed_async_replace_resynchronizes_bonds_and_restarts_known_peer_advertising():
    source = CLIENT_SOURCE.read_text(encoding="utf-8")

    remove_case = source.split(
        "case ESP_GAP_BLE_REMOVE_BOND_DEV_COMPLETE_EVT:", 1
    )[1].split("case ESP_GAP_BLE_UPDATE_CONN_PARAMS_EVT:", 1)[0]
    assert "sync_existing_ble_bond()" in remove_case
    assert "remaining > 0" in remove_case
    assert "start_advertising();" in remove_case
    assert remove_case.index("sync_existing_ble_bond()") < remove_case.index(
        "start_advertising();"
    )

    sync_body = source.split("static int sync_existing_ble_bond(void)", 1)[1].split(
        "static void load_existing_ble_bond", 1
    )[0]
    assert "return -1;" not in sync_body
    assert "return bond_count;" in sync_body

    replace_body = source.split(
        "esp_err_t ancs_client_replace_enrollment(bool confirmed)", 1
    )[1].split(
        "ancs_client_enrollment_status_t ancs_client_get_enrollment_status", 1
    )[0]
    immediate_failure = replace_body.split(
        "if (error != ESP_OK)", 1
    )[1].split("return error;", 1)[0]
    assert "sync_existing_ble_bond()" in immediate_failure
    assert "start_advertising();" in immediate_failure


def test_init_failure_uses_single_reverse_order_cleanup_path():
    source = CLIENT_SOURCE.read_text(encoding="utf-8")

    init_body = source.split("esp_err_t ancs_client_init(void)", 1)[1].split(
        "esp_err_t ancs_client_request_enroll(void)", 1
    )[0]
    assert "goto init_failed;" in init_body
    assert "init_failed:" in init_body
    assert "cleanup_init_resources(" in init_body
    assert "set_state(ANCS_STATE_RECOVERING);" in init_body

    cleanup = source.split("static void cleanup_init_resources(", 1)[1].split(
        "esp_err_t ancs_client_init(void)", 1
    )[0]
    assert cleanup.index("esp_bluedroid_disable()") < cleanup.index(
        "esp_bluedroid_deinit()"
    )
    assert cleanup.index("esp_bluedroid_deinit()") < cleanup.index(
        "esp_bt_controller_disable()"
    )
    assert cleanup.index("esp_bt_controller_disable()") < cleanup.index(
        "esp_bt_controller_deinit()"
    )
    assert "esp_timer_delete(*timer)" in source
    assert cleanup.index("cleanup_timer(&s_client.button_timer)") < cleanup.index(
        "vTaskDelete"
    )
    assert cleanup.index("vTaskDelete") < cleanup.index("vQueueDelete")


def test_boot_hold_callback_can_be_registered_for_provisioning_reducer_queue():
    source = CLIENT_SOURCE.read_text(encoding="utf-8")
    header = CLIENT_HEADER.read_text(encoding="utf-8")

    assert "ancs_client_boot_held_callback_t" in header
    assert "ancs_client_register_boot_held_callback(" in header
    assert "ancs_client_boot_held_callback_t boot_held_callback;" in source
    assert "boot_held_callback_context" in source
    button_callback = source.split(
        "static void enroll_button_callback(void *argument)", 1
    )[1].split("static void discovery_retry_callback", 1)[0]
    assert "boot_held_callback" in button_callback
    assert "ancs_client_request_enroll();" in button_callback
