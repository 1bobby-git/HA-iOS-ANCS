#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"
#include "esp_wifi_types.h"
#include "provision_store.h"
#include "provisioning_state.h"

#ifdef __cplusplus
extern "C" {
#endif

#define PROVISIONING_RUNTIME_AP_SSID_PREFIX "IOS-ANCS-SETUP-"
#define PROVISIONING_RUNTIME_AP_PASSWORD_PREFIX "ancs-"
#define PROVISIONING_RUNTIME_CAPTIVE_URI "http://192.168.4.1"
#define PROVISIONING_RUNTIME_WIFI_TIMEOUT_MS 30000
#define PROVISIONING_RUNTIME_SCAN_MAX_APS 20

typedef struct {
    provisioning_event_t event;
    uint32_t sta_attempt_generation;
} provisioning_runtime_event_t;

typedef void (*provisioning_event_callback_t)(
    const provisioning_runtime_event_t *runtime_event,
    void *context);

typedef struct {
    bool initialized;
    bool ap_started;
    bool sta_started;
    bool sta_connecting;
    bool sta_has_ip;
    uint32_t last_wifi_disconnect_reason;
    int32_t last_wifi_disconnect_rssi;
    uint32_t event_overflow_count;
    uint32_t sta_attempt_generation;
    char ap_ssid[sizeof(PROVISIONING_RUNTIME_AP_SSID_PREFIX) + 12];
} provisioning_runtime_status_t;

esp_err_t provisioning_runtime_init(
    const provision_config_t *config,
    provisioning_event_callback_t callback,
    void *context);
esp_err_t provisioning_runtime_start_ap(void);
esp_err_t provisioning_runtime_stop_ap(void);
esp_err_t provisioning_runtime_start_sta(const provision_config_t *config);
esp_err_t provisioning_runtime_stop_sta(void);
esp_err_t provisioning_runtime_enter_stable_recovery(void);
esp_err_t provisioning_runtime_scan(wifi_ap_record_t *records, size_t *count);
esp_err_t provisioning_runtime_notify_mqtt_failed(void);
esp_err_t provisioning_runtime_notify_mqtt_connected(void);
esp_err_t provisioning_runtime_get_status(provisioning_runtime_status_t *out);

#ifdef __cplusplus
}
#endif
