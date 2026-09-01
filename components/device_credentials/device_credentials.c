#include "device_credentials.h"

#include <stdbool.h>

#include "esp_random.h"
#include "nvs.h"

#define DEVICE_CREDENTIALS_NAMESPACE "ancs_credentials"
#define DEVICE_CREDENTIALS_BLE_PASSKEY_KEY "ble_passkey"
#define DEVICE_CREDENTIALS_PASSKEY_MIN 100000U
#define DEVICE_CREDENTIALS_PASSKEY_SPAN 900000U

static bool s_initialized;
static uint32_t s_ble_passkey;

static bool passkey_valid(uint32_t value)
{
    return value >= DEVICE_CREDENTIALS_PASSKEY_MIN && value <= 999999U;
}

static uint32_t generate_passkey(void)
{
    uint32_t random_value = 0U;
    esp_fill_random(&random_value, sizeof(random_value));
    return DEVICE_CREDENTIALS_PASSKEY_MIN +
           (random_value % DEVICE_CREDENTIALS_PASSKEY_SPAN);
}

esp_err_t device_credentials_init(void)
{
    if (s_initialized) {
        return ESP_OK;
    }

    nvs_handle_t handle;
    esp_err_t error = nvs_open(DEVICE_CREDENTIALS_NAMESPACE,
                               NVS_READWRITE,
                               &handle);
    if (error != ESP_OK) {
        return error;
    }

    uint32_t passkey = 0U;
    error = nvs_get_u32(handle,
                        DEVICE_CREDENTIALS_BLE_PASSKEY_KEY,
                        &passkey);
    if (error == ESP_ERR_NVS_NOT_FOUND ||
        (error == ESP_OK && !passkey_valid(passkey))) {
        passkey = generate_passkey();
        error = nvs_set_u32(handle,
                            DEVICE_CREDENTIALS_BLE_PASSKEY_KEY,
                            passkey);
        if (error == ESP_OK) {
            error = nvs_commit(handle);
        }
    }
    nvs_close(handle);

    if (error != ESP_OK) {
        return error;
    }
    if (!passkey_valid(passkey)) {
        return ESP_ERR_INVALID_STATE;
    }

    s_ble_passkey = passkey;
    s_initialized = true;
    return ESP_OK;
}

uint32_t device_credentials_ble_passkey(void)
{
    return s_initialized ? s_ble_passkey : 0U;
}
