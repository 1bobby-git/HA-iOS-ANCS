#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"
#include "provision_store.h"
#include "provisioning_runtime.h"

#ifdef __cplusplus
extern "C" {
#endif

#define PORTAL_HTTP_CONFIRM_REPLACE "REPLACE ENROLLMENT"
#define PORTAL_HTTP_CONFIRM_RESET_PROVISIONING "RESET PROVISIONING"
#define PORTAL_HTTP_CONFIRM_RESET_ALL_DATA "RESET ALL DATA"

typedef struct {
    bool mqtt_connected;
    bool ble_bonded;
    bool ble_connected;
    bool enroll_window_open;
    bool replace_pending;
    bool replace_failed;
    int replace_error_code;
    uint32_t notifications_published;
    uint32_t notifications_dropped;
} portal_http_system_status_t;

typedef struct {
    esp_err_t (*status)(portal_http_system_status_t *out, void *context);
    esp_err_t (*mqtt_test)(void *context);
    esp_err_t (*reconnect)(const provision_config_t *config, void *context);
    esp_err_t (*ble_enroll)(void *context);
    esp_err_t (*ble_replace)(void *context);
    esp_err_t (*restart)(void *context);
    esp_err_t (*reset_provisioning)(void *context);
    esp_err_t (*reset_all_data)(void *context);
    void *context;
} portal_http_handlers_t;

esp_err_t portal_http_init(const portal_http_handlers_t *handlers);
esp_err_t portal_http_stop(void);

#ifdef __cplusplus
}
#endif
