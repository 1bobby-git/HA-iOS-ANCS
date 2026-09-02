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
    bool mqtt_connecting;
    uint8_t mqtt_retry_attempt;
    uint32_t mqtt_retry_delay_ms;
    int mqtt_error_type;
    int mqtt_last_esp_error;
    int mqtt_last_tls_error;
    int mqtt_last_socket_errno;
    int mqtt_connect_return_code;
    uint64_t mqtt_last_error_at_ms;
    bool ble_bonded;
    bool ble_connected;
    bool enroll_window_open;
    uint32_t ble_passkey;
    bool ble_pairing_repair_required;
    uint8_t ble_auth_failure_count;
    int ble_auth_error;
    bool replace_pending;
    bool replace_failed;
    int replace_error_code;
    uint32_t notifications_published;
    uint32_t notifications_dropped;
    uint32_t notifications_dropped_offline;
    uint32_t notifications_dropped_enqueue;
    uint32_t notifications_dropped_policy;
} portal_http_system_status_t;

typedef struct {
    esp_err_t (*status)(portal_http_system_status_t *out, void *context);
    esp_err_t (*mqtt_test)(void *context);
    esp_err_t (*test_notification)(void *context);
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
