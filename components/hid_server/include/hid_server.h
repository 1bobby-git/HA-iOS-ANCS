#pragma once

#include <stdbool.h>

#include "esp_err.h"

esp_err_t hid_server_init(void);
bool hid_server_is_ready(void);
