#include "hid_server.h"

#include "esp_hidd_prf_api.h"
#include "esp_log.h"
#include "hidd_le_prf_int.h"

static const char *const TAG = "HID_SERVER";

static void hid_event_callback(esp_hidd_cb_event_t event,
                               esp_hidd_cb_param_t *parameter)
{
    switch (event) {
    case ESP_HIDD_EVENT_REG_FINISH:
        ESP_LOGI(TAG,
                 "HID profile registration status=%u",
                 (unsigned int)parameter->init_finish.state);
        break;

    case ESP_BAT_EVENT_REG:
        ESP_LOGI(TAG, "Battery service registered");
        break;

    case ESP_HIDD_EVENT_BLE_CONNECT:
        ESP_LOGI(TAG,
                 "HID GATT connection established conn_id=%u",
                 (unsigned int)parameter->connect.conn_id);
        break;

    case ESP_HIDD_EVENT_BLE_DISCONNECT:
        ESP_LOGI(TAG, "HID GATT connection closed");
        break;

    case ESP_HIDD_EVENT_DEINIT_FINISH:
    case ESP_HIDD_EVENT_BLE_VENDOR_REPORT_WRITE_EVT:
    case ESP_HIDD_EVENT_BLE_LED_REPORT_WRITE_EVT:
    default:
        break;
    }
}

esp_err_t hid_server_init(void)
{
    esp_err_t error = esp_hidd_profile_init();
    if (error != ESP_OK) {
        return error;
    }
    return esp_hidd_register_callbacks(hid_event_callback);
}

bool hid_server_is_ready(void)
{
    return hidd_le_env.enabled &&
           hidd_le_env.hidd_inst.att_tbl[HIDD_LE_IDX_SVC] != 0U;
}
