#pragma once

#include <stdint.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t device_credentials_init(void);
uint32_t device_credentials_ble_passkey(void);

#ifdef __cplusplus
}
#endif
