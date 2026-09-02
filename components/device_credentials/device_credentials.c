#include "device_credentials.h"

#include <stdbool.h>

#define DEVICE_CREDENTIALS_BLE_PASSKEY 123456U

_Static_assert(DEVICE_CREDENTIALS_BLE_PASSKEY >= 100000U &&
                   DEVICE_CREDENTIALS_BLE_PASSKEY <= 999999U,
               "BLE passkey must be a six-digit number");

static bool s_initialized;

esp_err_t device_credentials_init(void)
{
    s_initialized = true;
    return ESP_OK;
}

uint32_t device_credentials_ble_passkey(void)
{
    return s_initialized ? DEVICE_CREDENTIALS_BLE_PASSKEY : 0U;
}
