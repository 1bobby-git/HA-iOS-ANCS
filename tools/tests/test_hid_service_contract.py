from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CLIENT_SOURCE = (
    PROJECT_ROOT / "components" / "ancs_client" / "ancs_client.c"
)
HID_COMPONENT = PROJECT_ROOT / "components" / "hid_server"


def test_advertised_hid_service_is_actually_registered():
    client_source = CLIENT_SOURCE.read_text(encoding="utf-8")
    hid_source = (HID_COMPONENT / "hid_server.c").read_text(encoding="utf-8")
    hid_cmake = (HID_COMPONENT / "CMakeLists.txt").read_text(encoding="utf-8")

    assert "hid_server_init()" in client_source
    assert "hid_server_is_ready()" in client_source
    assert "esp_hidd_profile_init()" in hid_source
    assert "esp_hidd_register_callbacks" in hid_source
    assert "hid_device_le_prf.c" in hid_cmake
    assert "ESP_BLE_APPEARANCE_GENERIC_HID" in client_source
    assert "ESP_BLE_APPEARANCE_GENERIC_WATCH" not in client_source


def test_enrollment_advertisement_places_name_and_standard_hid_uuid_in_primary_packet():
    client_source = CLIENT_SOURCE.read_text(encoding="utf-8")

    # iOS Settings can passively inspect the primary advertisement.  Keep both
    # the complete device name and the standardized HOGP UUID there instead of
    # requiring a scan-response round trip to identify the ANCS accessory.
    assert "static uint8_t s_hid_service_uuid[2]" in client_source
    assert "0x12, 0x18" in client_source
    adv_data = client_source.split("static esp_ble_adv_data_t s_adv_data", 1)[1].split(
        "static esp_ble_adv_data_t s_scan_response", 1
    )[0]
    assert ".include_name = true" in adv_data
    assert ".service_uuid_len = sizeof(s_hid_service_uuid)" in adv_data
    assert ".min_interval = 0" in adv_data
    assert ".max_interval = 0" in adv_data
    assert ".appearance = 0" in adv_data


def test_hid_profile_does_not_downgrade_mitm_pairing():
    profile_source = (
        HID_COMPONENT / "vendor" / "hid_device_le_prf.c"
    ).read_text(encoding="utf-8")

    assert "ESP_BLE_SEC_ENCRYPT_MITM" in profile_source
    assert "ESP_BLE_SEC_ENCRYPT_NO_MITM" not in profile_source
