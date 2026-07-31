#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

#define PROVISION_CONFIG_SCHEMA_VERSION 1U
#define PROVISION_WIFI_SSID_MAX 32
#define PROVISION_WIFI_PASSWORD_MAX 64
#define PROVISION_MQTT_HOST_MAX 128
#define PROVISION_MQTT_USERNAME_MAX 128
#define PROVISION_MQTT_PASSWORD_MAX 256
#define PROVISION_MQTT_CLIENT_ID_MAX 64
#define PROVISION_MQTT_BASE_TOPIC_MAX 128
#define PROVISION_MQTT_CA_MAX 4096

typedef enum {
    PROVISION_CONFIG_OK = 0,
    PROVISION_CONFIG_INVALID_ARGUMENT,
    PROVISION_CONFIG_UNSUPPORTED_SCHEMA,
    PROVISION_CONFIG_MISSING_WIFI,
    PROVISION_CONFIG_MISSING_MQTT_HOST,
    PROVISION_CONFIG_INVALID_MQTT_PORT,
    PROVISION_CONFIG_MISSING_MQTT_CLIENT_ID,
    PROVISION_CONFIG_MISSING_MQTT_BASE_TOPIC,
    PROVISION_CONFIG_TLS_CA_REQUIRED,
} provision_config_result_t;

typedef struct {
    uint32_t schema_version;
    char wifi_ssid[PROVISION_WIFI_SSID_MAX + 1];
    char wifi_password[PROVISION_WIFI_PASSWORD_MAX + 1];
    char mqtt_host[PROVISION_MQTT_HOST_MAX + 1];
    uint16_t mqtt_port;
    char mqtt_username[PROVISION_MQTT_USERNAME_MAX + 1];
    char mqtt_password[PROVISION_MQTT_PASSWORD_MAX + 1];
    bool mqtt_tls;
    char mqtt_ca[PROVISION_MQTT_CA_MAX + 1];
    char mqtt_client_id[PROVISION_MQTT_CLIENT_ID_MAX + 1];
    char mqtt_base_topic[PROVISION_MQTT_BASE_TOPIC_MAX + 1];
} provision_config_t;

typedef struct {
    char wifi_ssid[PROVISION_WIFI_SSID_MAX + 1];
    bool wifi_password_configured;
    char mqtt_host[PROVISION_MQTT_HOST_MAX + 1];
    uint16_t mqtt_port;
    char mqtt_username[PROVISION_MQTT_USERNAME_MAX + 1];
    bool mqtt_password_configured;
    bool mqtt_tls;
    bool mqtt_ca_configured;
    char mqtt_client_id[PROVISION_MQTT_CLIENT_ID_MAX + 1];
    char mqtt_base_topic[PROVISION_MQTT_BASE_TOPIC_MAX + 1];
} provision_config_status_t;

typedef struct {
    uint32_t schema_version;
    uint32_t generation;
    uint32_t crc32;
    provision_config_t config;
} provision_store_slot_blob_t;

provision_config_result_t provision_config_validate(const provision_config_t *config);
esp_err_t provision_config_merge_preserving_secrets(
    const provision_config_t *existing,
    const provision_config_t *update,
    provision_config_t *out);
esp_err_t provision_config_redact_status(
    const provision_config_t *config,
    provision_config_status_t *out);

esp_err_t provision_store_init(void);
esp_err_t provision_store_load(provision_config_t *out);
esp_err_t provision_store_save_atomic(const provision_config_t *config);
esp_err_t provision_store_reset(void);

esp_err_t provision_store_encode_for_test(
    const provision_config_t *config,
    uint32_t generation,
    uint8_t *out,
    size_t *inout_len);
esp_err_t provision_store_decode(
    const uint8_t *data,
    size_t data_len,
    provision_config_t *out,
    uint32_t *generation_out);

#ifdef __cplusplus
}
#endif
