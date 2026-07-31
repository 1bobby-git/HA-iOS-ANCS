#include "provision_store.h"

#include <stdlib.h>
#include <string.h>

#include "esp_check.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "sdkconfig.h"

#define PROVISION_PARTITION "provision"
#define PROVISION_NAMESPACE "config"
#define PROVISION_SLOT_A "slot_a"
#define PROVISION_SLOT_B "slot_b"
#define PROVISION_ACTIVE_KEY "active"
#define PROVISION_ACTIVE_A 0U
#define PROVISION_ACTIVE_B 1U

static const char *const TAG = "provision_store";

static bool s_initialized;
#if CONFIG_PROVISION_STORE_TEST_BACKEND
static bool s_test_backend;
static char s_last_erased_partition[16];
static provision_store_slot_blob_t s_test_slots[2];
static bool s_test_slot_valid[2];
static uint8_t s_test_active;
static bool s_test_active_valid;
static bool s_test_fail_next_commit;
static bool s_test_fail_next_readback;
static bool s_test_fail_next_active_commit;
#endif

typedef struct {
    bool found;
    bool active_known;
    bool active_valid;
    uint8_t active_slot;
    uint32_t active_generation;
    provision_config_t active_config;
    uint8_t best_slot;
    uint32_t generation;
    provision_config_t config;
} provision_best_slot_t;

typedef struct {
    bool found;
    uint8_t slot;
    uint32_t generation;
    provision_config_t config;
} provision_live_slot_t;

typedef struct {
    provision_best_slot_t best;
    provision_live_slot_t live;
} provision_store_selection_workspace_t;

typedef struct {
    provision_best_slot_t best;
    provision_live_slot_t live;
    provision_store_slot_blob_t blob;
    provision_config_t readback;
} provision_store_save_workspace_t;

static uint32_t crc32_update(uint32_t crc, const uint8_t *data, size_t len)
{
    crc = ~crc;
    for (size_t i = 0; i < len; ++i) {
        crc ^= data[i];
        for (int bit = 0; bit < 8; ++bit) {
            const uint32_t mask = 0U - (crc & 1U);
            crc = (crc >> 1) ^ (0xEDB88320U & mask);
        }
    }
    return ~crc;
}

static size_t bounded_strlen(const char *value, size_t max_len)
{
    size_t len = 0;
    while (len <= max_len && value[len] != '\0') {
        ++len;
    }
    return len;
}

static bool string_field_valid(const char *value, size_t max_len)
{
    return value != NULL && bounded_strlen(value, max_len) <= max_len;
}

static bool string_field_present(const char *value, size_t max_len)
{
    return string_field_valid(value, max_len) && value[0] != '\0';
}

provision_config_result_t provision_config_validate(const provision_config_t *config)
{
    if (config == NULL) {
        return PROVISION_CONFIG_INVALID_ARGUMENT;
    }
    if (config->schema_version != 0 &&
        config->schema_version != PROVISION_CONFIG_SCHEMA_VERSION) {
        return PROVISION_CONFIG_UNSUPPORTED_SCHEMA;
    }
    if (!string_field_present(config->wifi_ssid, PROVISION_WIFI_SSID_MAX)) {
        return PROVISION_CONFIG_MISSING_WIFI;
    }
    if (!string_field_valid(config->wifi_password, PROVISION_WIFI_PASSWORD_MAX) ||
        !string_field_valid(config->mqtt_username, PROVISION_MQTT_USERNAME_MAX) ||
        !string_field_valid(config->mqtt_password, PROVISION_MQTT_PASSWORD_MAX) ||
        !string_field_valid(config->mqtt_ca, PROVISION_MQTT_CA_MAX)) {
        return PROVISION_CONFIG_INVALID_ARGUMENT;
    }
    if (!string_field_present(config->mqtt_host, PROVISION_MQTT_HOST_MAX)) {
        return PROVISION_CONFIG_MISSING_MQTT_HOST;
    }
    if (config->mqtt_port == 0) {
        return PROVISION_CONFIG_INVALID_MQTT_PORT;
    }
    if (config->mqtt_tls && !string_field_present(config->mqtt_ca, PROVISION_MQTT_CA_MAX)) {
        return PROVISION_CONFIG_TLS_CA_REQUIRED;
    }
    if (!string_field_present(config->mqtt_client_id, PROVISION_MQTT_CLIENT_ID_MAX)) {
        return PROVISION_CONFIG_MISSING_MQTT_CLIENT_ID;
    }
    if (!string_field_present(config->mqtt_base_topic, PROVISION_MQTT_BASE_TOPIC_MAX)) {
        return PROVISION_CONFIG_MISSING_MQTT_BASE_TOPIC;
    }
    return PROVISION_CONFIG_OK;
}

esp_err_t provision_config_merge_preserving_secrets(
    const provision_config_t *existing,
    const provision_config_t *update,
    provision_config_t *out)
{
    if (existing == NULL || update == NULL || out == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    *out = *update;
    if (out->schema_version == 0) {
        out->schema_version = PROVISION_CONFIG_SCHEMA_VERSION;
    }
    if (out->wifi_password[0] == '\0') {
        strlcpy(out->wifi_password, existing->wifi_password, sizeof(out->wifi_password));
    }
    if (out->mqtt_password[0] == '\0') {
        strlcpy(out->mqtt_password, existing->mqtt_password, sizeof(out->mqtt_password));
    }
    if (out->mqtt_ca[0] == '\0' && existing->mqtt_ca[0] != '\0') {
        strlcpy(out->mqtt_ca, existing->mqtt_ca, sizeof(out->mqtt_ca));
    }

    return provision_config_validate(out) == PROVISION_CONFIG_OK ? ESP_OK : ESP_ERR_INVALID_ARG;
}

esp_err_t provision_config_redact_status(
    const provision_config_t *config,
    provision_config_status_t *out)
{
    if (config == NULL || out == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    memset(out, 0, sizeof(*out));
    strlcpy(out->wifi_ssid, config->wifi_ssid, sizeof(out->wifi_ssid));
    out->wifi_password_configured = config->wifi_password[0] != '\0';
    strlcpy(out->mqtt_host, config->mqtt_host, sizeof(out->mqtt_host));
    out->mqtt_port = config->mqtt_port;
    strlcpy(out->mqtt_username, config->mqtt_username, sizeof(out->mqtt_username));
    out->mqtt_password_configured = config->mqtt_password[0] != '\0';
    out->mqtt_tls = config->mqtt_tls;
    out->mqtt_ca_configured = config->mqtt_ca[0] != '\0';
    strlcpy(out->mqtt_client_id, config->mqtt_client_id, sizeof(out->mqtt_client_id));
    strlcpy(out->mqtt_base_topic, config->mqtt_base_topic, sizeof(out->mqtt_base_topic));
    return ESP_OK;
}

static esp_err_t encode_blob(const provision_config_t *config, uint32_t generation, provision_store_slot_blob_t *blob)
{
    if (config == NULL || blob == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    if (provision_config_validate(config) != PROVISION_CONFIG_OK) {
        return ESP_ERR_INVALID_ARG;
    }

    memset(blob, 0, sizeof(*blob));
    blob->schema_version = PROVISION_CONFIG_SCHEMA_VERSION;
    blob->generation = generation;
    blob->config = *config;
    blob->config.schema_version = PROVISION_CONFIG_SCHEMA_VERSION;
    blob->crc32 = 0;
    blob->crc32 = crc32_update(0, (const uint8_t *)blob, sizeof(*blob));
    return ESP_OK;
}

esp_err_t provision_store_encode_for_test(
    const provision_config_t *config,
    uint32_t generation,
    uint8_t *out,
    size_t *inout_len)
{
    if (out == NULL || inout_len == NULL || *inout_len < sizeof(provision_store_slot_blob_t)) {
        return ESP_ERR_INVALID_ARG;
    }

    provision_store_slot_blob_t *blob = calloc(1, sizeof(*blob));
    if (blob == NULL) {
        return ESP_ERR_NO_MEM;
    }

    esp_err_t err = encode_blob(config, generation, blob);
    if (err == ESP_OK) {
        memcpy(out, blob, sizeof(*blob));
        *inout_len = sizeof(*blob);
    }

    memset(blob, 0, sizeof(*blob));
    free(blob);
    return err;
}

esp_err_t provision_store_decode(
    const uint8_t *data,
    size_t data_len,
    provision_config_t *out,
    uint32_t *generation_out)
{
    if (data == NULL || out == NULL || data_len != sizeof(provision_store_slot_blob_t)) {
        return ESP_ERR_INVALID_ARG;
    }

    provision_store_slot_blob_t *blob = malloc(sizeof(*blob));
    if (blob == NULL) {
        return ESP_ERR_NO_MEM;
    }

    memcpy(blob, data, sizeof(*blob));
    const uint32_t expected_crc = blob->crc32;
    blob->crc32 = 0;
    const uint32_t actual_crc = crc32_update(0, (const uint8_t *)blob, sizeof(*blob));
    if (actual_crc != expected_crc) {
        memset(blob, 0, sizeof(*blob));
        free(blob);
        return ESP_ERR_INVALID_CRC;
    }
    if (blob->schema_version != PROVISION_CONFIG_SCHEMA_VERSION ||
        blob->config.schema_version != PROVISION_CONFIG_SCHEMA_VERSION) {
        memset(blob, 0, sizeof(*blob));
        free(blob);
        return ESP_ERR_INVALID_VERSION;
    }
    if (provision_config_validate(&blob->config) != PROVISION_CONFIG_OK) {
        memset(blob, 0, sizeof(*blob));
        free(blob);
        return ESP_ERR_INVALID_ARG;
    }

    *out = blob->config;
    if (generation_out != NULL) {
        *generation_out = blob->generation;
    }
    memset(blob, 0, sizeof(*blob));
    free(blob);
    return ESP_OK;
}

esp_err_t provision_store_init(void)
{
    esp_err_t err = nvs_flash_init_partition(PROVISION_PARTITION);
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_RETURN_ON_ERROR(nvs_flash_erase_partition(PROVISION_PARTITION), "provision_store", "erase partition");
        err = nvs_flash_init_partition(PROVISION_PARTITION);
    }
    if (err == ESP_OK) {
        s_initialized = true;
    }
    return err;
}

static esp_err_t open_namespace(nvs_open_mode_t mode, nvs_handle_t *handle)
{
    if (!s_initialized) {
        esp_err_t err = provision_store_init();
        if (err != ESP_OK) {
            return err;
        }
    }
    return nvs_open_from_partition(PROVISION_PARTITION, PROVISION_NAMESPACE, mode, handle);
}

static esp_err_t read_slot(nvs_handle_t handle, const char *key, provision_config_t *config, uint32_t *generation)
{
    provision_store_slot_blob_t *blob = calloc(1, sizeof(*blob));
    if (blob == NULL) {
        return ESP_ERR_NO_MEM;
    }

    size_t len = sizeof(*blob);
    esp_err_t err = nvs_get_blob(handle, key, blob, &len);
    if (err == ESP_OK) {
        err = provision_store_decode((const uint8_t *)blob, len, config, generation);
    }

    memset(blob, 0, sizeof(*blob));
    free(blob);
    return err;
}

static bool generation_at_least(uint32_t left, uint32_t right)
{
    return left >= right;
}

static void consider_best_slot(
    provision_best_slot_t *best,
    uint8_t slot,
    const provision_config_t *config,
    uint32_t generation)
{
    if (!best->found || generation_at_least(generation, best->generation)) {
        best->found = true;
        best->best_slot = slot;
        best->generation = generation;
        best->config = *config;
    }
}

static esp_err_t select_live_slot(const provision_best_slot_t *best, provision_live_slot_t *live)
{
    if (best == NULL || live == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    memset(live, 0, sizeof(*live));
    if (!best->found) {
        return ESP_ERR_NVS_NOT_FOUND;
    }

    if (best->active_known && best->active_valid) {
        live->found = true;
        live->slot = best->active_slot;
        live->generation = best->active_generation;
        live->config = best->active_config;
        return ESP_OK;
    } else {
        live->found = true;
        live->slot = best->best_slot;
        live->generation = best->generation;
        live->config = best->config;
        return ESP_OK;
    }

    return ESP_ERR_INVALID_STATE;
}

#if CONFIG_PROVISION_STORE_TEST_BACKEND
static esp_err_t read_best_test_slot(provision_best_slot_t *best,
                                     provision_config_t *scratch)
{
    if (best == NULL || scratch == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    memset(best, 0, sizeof(*best));
    best->active_known = s_test_active_valid;
    best->active_slot = s_test_active;

    for (uint8_t slot = PROVISION_ACTIVE_A; slot <= PROVISION_ACTIVE_B; ++slot) {
        if (!s_test_slot_valid[slot]) {
            continue;
        }
        memset(scratch, 0, sizeof(*scratch));
        uint32_t generation = 0;
        esp_err_t err = provision_store_decode(
            (const uint8_t *)&s_test_slots[slot],
            sizeof(s_test_slots[slot]),
            scratch,
            &generation);
        if (err != ESP_OK) {
            continue;
        }
        if (best->active_known && best->active_slot == slot) {
            best->active_valid = true;
            best->active_config = *scratch;
            best->active_generation = generation;
        }
        consider_best_slot(best, slot, scratch, generation);
    }

    memset(scratch, 0, sizeof(*scratch));
    return best->found ? ESP_OK : ESP_ERR_NVS_NOT_FOUND;
}
#endif

static esp_err_t read_best_nvs_slot(nvs_handle_t handle,
                                    provision_best_slot_t *best,
                                    provision_config_t *scratch)
{
    if (best == NULL || scratch == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    memset(best, 0, sizeof(*best));
    uint8_t active = PROVISION_ACTIVE_A;
    if (nvs_get_u8(handle, PROVISION_ACTIVE_KEY, &active) == ESP_OK) {
        best->active_known = true;
        best->active_slot = active == PROVISION_ACTIVE_B ? PROVISION_ACTIVE_B : PROVISION_ACTIVE_A;
    }

    uint32_t generation = 0;
    esp_err_t err = read_slot(handle, PROVISION_SLOT_A, scratch, &generation);
    if (err == ESP_OK) {
        if (best->active_known && best->active_slot == PROVISION_ACTIVE_A) {
            best->active_valid = true;
            best->active_config = *scratch;
            best->active_generation = generation;
        }
        consider_best_slot(best, PROVISION_ACTIVE_A, scratch, generation);
    }

    memset(scratch, 0, sizeof(*scratch));
    generation = 0;
    err = read_slot(handle, PROVISION_SLOT_B, scratch, &generation);
    if (err == ESP_OK) {
        if (best->active_known && best->active_slot == PROVISION_ACTIVE_B) {
            best->active_valid = true;
            best->active_config = *scratch;
            best->active_generation = generation;
        }
        consider_best_slot(best, PROVISION_ACTIVE_B, scratch, generation);
    }

    memset(scratch, 0, sizeof(*scratch));
    return best->found ? ESP_OK : ESP_ERR_NVS_NOT_FOUND;
}

esp_err_t provision_store_load(provision_config_t *out)
{
    if (out == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    provision_store_selection_workspace_t *workspace = calloc(1, sizeof(*workspace));
    if (workspace == NULL) {
        return ESP_ERR_NO_MEM;
    }

    esp_err_t err = ESP_OK;
#if CONFIG_PROVISION_STORE_TEST_BACKEND
    if (s_test_backend) {
        err = read_best_test_slot(&workspace->best, &workspace->live.config);
        if (err == ESP_OK) {
            err = select_live_slot(&workspace->best, &workspace->live);
        }
        if (err == ESP_OK) {
            *out = workspace->live.config;
        }
        goto cleanup;
    }
#endif

    nvs_handle_t handle = 0;
    err = open_namespace(NVS_READONLY, &handle);
    if (err != ESP_OK) {
        goto cleanup;
    }

    err = read_best_nvs_slot(handle, &workspace->best, &workspace->live.config);
    nvs_close(handle);
    if (err == ESP_OK) {
        err = select_live_slot(&workspace->best, &workspace->live);
    }
    if (err == ESP_OK) {
        *out = workspace->live.config;
    }

cleanup:
    memset(workspace, 0, sizeof(*workspace));
    free(workspace);
    return err;
}

#if CONFIG_PROVISION_STORE_TEST_BACKEND
static esp_err_t save_test_atomic(
    const provision_config_t *config,
    provision_store_save_workspace_t *workspace)
{
    esp_err_t best_err = read_best_test_slot(&workspace->best, &workspace->readback);
    if (best_err != ESP_OK && best_err != ESP_ERR_NVS_NOT_FOUND) {
        return best_err;
    }
    esp_err_t live_err = select_live_slot(&workspace->best, &workspace->live);
    if (live_err != ESP_OK && live_err != ESP_ERR_NVS_NOT_FOUND) {
        return live_err;
    }
    if (workspace->live.found && workspace->live.generation == UINT32_MAX) {
        return ESP_ERR_INVALID_STATE;
    }
    if (workspace->best.found &&
        (!workspace->best.active_known ||
         !workspace->best.active_valid ||
         workspace->best.active_slot != workspace->best.best_slot)) {
        s_test_active = workspace->best.best_slot;
        s_test_active_valid = true;
        workspace->live.found = true;
        workspace->live.slot = workspace->best.best_slot;
        workspace->live.generation = workspace->best.generation;
        workspace->live.config = workspace->best.config;
    }

    const uint8_t inactive = workspace->live.found
        ? (workspace->live.slot == PROVISION_ACTIVE_B ? PROVISION_ACTIVE_A : PROVISION_ACTIVE_B)
        : PROVISION_ACTIVE_A;
    const uint32_t next_generation =
        workspace->live.found ? workspace->live.generation + 1U : 1U;
    esp_err_t err = encode_blob(config, next_generation, &workspace->blob);
    if (err != ESP_OK) {
        return err;
    }

    s_test_slots[inactive] = workspace->blob;
    s_test_slot_valid[inactive] = true;
    if (s_test_fail_next_commit) {
        s_test_fail_next_commit = false;
        return ESP_FAIL;
    }
    if (s_test_fail_next_readback) {
        s_test_fail_next_readback = false;
        return ESP_ERR_INVALID_CRC;
    }

    uint32_t readback_generation = 0;
    err = provision_store_decode(
        (const uint8_t *)&s_test_slots[inactive],
        sizeof(s_test_slots[inactive]),
        &workspace->readback,
        &readback_generation);
    if (err != ESP_OK || readback_generation != next_generation) {
        return err == ESP_OK ? ESP_ERR_INVALID_RESPONSE : err;
    }

    if (s_test_fail_next_active_commit) {
        s_test_fail_next_active_commit = false;
        return ESP_FAIL;
    }
    s_test_active = inactive;
    s_test_active_valid = true;
    return ESP_OK;
}
#endif

static esp_err_t save_nvs_atomic(
    const provision_config_t *config,
    provision_store_save_workspace_t *workspace)
{
    nvs_handle_t handle = 0;
    esp_err_t err = open_namespace(NVS_READWRITE, &handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "open namespace failed: %s", esp_err_to_name(err));
        return err;
    }

    esp_err_t best_err = read_best_nvs_slot(handle,
                                            &workspace->best,
                                            &workspace->readback);
    if (best_err != ESP_OK && best_err != ESP_ERR_NVS_NOT_FOUND) {
        ESP_LOGE(TAG, "read slots failed: %s", esp_err_to_name(best_err));
        nvs_close(handle);
        return best_err;
    }
    esp_err_t live_err = select_live_slot(&workspace->best, &workspace->live);
    if (live_err != ESP_OK && live_err != ESP_ERR_NVS_NOT_FOUND) {
        ESP_LOGE(TAG, "select live slot failed: %s", esp_err_to_name(live_err));
        nvs_close(handle);
        return live_err;
    }
    if (workspace->live.found && workspace->live.generation == UINT32_MAX) {
        nvs_close(handle);
        return ESP_ERR_INVALID_STATE;
    }
    if (workspace->best.found &&
        (!workspace->best.active_known ||
         !workspace->best.active_valid ||
         workspace->best.active_slot != workspace->best.best_slot)) {
        err = nvs_set_u8(handle, PROVISION_ACTIVE_KEY, workspace->best.best_slot);
        if (err == ESP_OK) {
            err = nvs_commit(handle);
        }
        if (err != ESP_OK) {
            nvs_close(handle);
            return err;
        }
        workspace->live.found = true;
        workspace->live.slot = workspace->best.best_slot;
        workspace->live.generation = workspace->best.generation;
        workspace->live.config = workspace->best.config;
    }

    const uint8_t inactive = workspace->live.found
        ? (workspace->live.slot == PROVISION_ACTIVE_B ? PROVISION_ACTIVE_A : PROVISION_ACTIVE_B)
        : PROVISION_ACTIVE_A;
    const char *inactive_key = inactive == PROVISION_ACTIVE_B ? PROVISION_SLOT_B : PROVISION_SLOT_A;
    const uint32_t next_generation =
        workspace->live.found ? workspace->live.generation + 1U : 1U;

    err = encode_blob(config, next_generation, &workspace->blob);
    if (err == ESP_OK) {
        err = nvs_set_blob(handle, inactive_key, &workspace->blob, sizeof(workspace->blob));
        if (err != ESP_OK) {
            ESP_LOGE(TAG,
                     "write slot failed key=%s bytes=%u: %s",
                     inactive_key,
                     (unsigned)sizeof(workspace->blob),
                     esp_err_to_name(err));
        }
    }
    if (err == ESP_OK) {
        err = nvs_commit(handle);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "commit slot failed: %s", esp_err_to_name(err));
        }
    }
    if (err == ESP_OK) {
        uint32_t readback_generation = 0;
        err = read_slot(handle, inactive_key, &workspace->readback, &readback_generation);
        if (err == ESP_OK && readback_generation != next_generation) {
            err = ESP_ERR_INVALID_RESPONSE;
        }
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "readback slot failed: %s", esp_err_to_name(err));
        }
    }
    if (err == ESP_OK) {
        err = nvs_set_u8(handle, PROVISION_ACTIVE_KEY, inactive);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "write active slot failed: %s", esp_err_to_name(err));
        }
    }
    if (err == ESP_OK) {
        err = nvs_commit(handle);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "commit active slot failed: %s", esp_err_to_name(err));
        }
    }

    nvs_close(handle);
    return err;
}

esp_err_t provision_store_save_atomic(const provision_config_t *config)
{
    if (config == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    provision_store_save_workspace_t *workspace = calloc(1, sizeof(*workspace));
    if (workspace == NULL) {
        return ESP_ERR_NO_MEM;
    }

#if CONFIG_PROVISION_STORE_TEST_BACKEND
    esp_err_t err = s_test_backend
        ? save_test_atomic(config, workspace)
        : save_nvs_atomic(config, workspace);
#else
    esp_err_t err = save_nvs_atomic(config, workspace);
#endif

    memset(workspace, 0, sizeof(*workspace));
    free(workspace);
    return err;
}

esp_err_t provision_store_reset(void)
{
#if CONFIG_PROVISION_STORE_TEST_BACKEND
    strlcpy(s_last_erased_partition, PROVISION_PARTITION, sizeof(s_last_erased_partition));
    if (s_test_backend) {
        memset(s_test_slots, 0, sizeof(s_test_slots));
        memset(s_test_slot_valid, 0, sizeof(s_test_slot_valid));
        s_test_active = PROVISION_ACTIVE_A;
        s_test_active_valid = false;
        return ESP_OK;
    }
#endif
    if (s_initialized) {
        esp_err_t err = nvs_flash_deinit_partition(PROVISION_PARTITION);
        if (err != ESP_OK && err != ESP_ERR_NVS_NOT_INITIALIZED) {
            return err;
        }
    }
    s_initialized = false;
    return nvs_flash_erase_partition(PROVISION_PARTITION);
}

#if CONFIG_PROVISION_STORE_TEST_BACKEND
void provision_store_test_reset_backend_state(void)
{
    s_test_backend = true;
    s_last_erased_partition[0] = '\0';
    memset(s_test_slots, 0, sizeof(s_test_slots));
    memset(s_test_slot_valid, 0, sizeof(s_test_slot_valid));
    s_test_active = PROVISION_ACTIVE_A;
    s_test_active_valid = false;
    s_test_fail_next_commit = false;
    s_test_fail_next_readback = false;
    s_test_fail_next_active_commit = false;
}

const char *provision_store_test_last_erased_partition(void)
{
    return s_last_erased_partition;
}

void provision_store_test_fail_next_commit(void)
{
    s_test_backend = true;
    s_test_fail_next_commit = true;
}

void provision_store_test_fail_next_readback(void)
{
    s_test_backend = true;
    s_test_fail_next_readback = true;
}

void provision_store_test_fail_next_active_commit(void)
{
    s_test_backend = true;
    s_test_fail_next_active_commit = true;
}

void provision_store_test_corrupt_active_slot(void)
{
    s_test_backend = true;
    if (s_test_active_valid && s_test_slot_valid[s_test_active]) {
        s_test_slots[s_test_active].crc32 ^= 0x12345678U;
    }
}

esp_err_t provision_store_test_seed_slot(
    int slot,
    const provision_config_t *config,
    uint32_t generation,
    bool active,
    bool corrupt)
{
    if (slot < 0 || slot > 1) {
        return ESP_ERR_INVALID_ARG;
    }
    s_test_backend = true;
    esp_err_t err = encode_blob(config, generation, &s_test_slots[slot]);
    if (err != ESP_OK) {
        return err;
    }
    if (corrupt) {
        s_test_slots[slot].crc32 ^= 0x87654321U;
    }
    s_test_slot_valid[slot] = true;
    if (active) {
        s_test_active = (uint8_t)slot;
        s_test_active_valid = true;
    }
    return ESP_OK;
}

esp_err_t provision_store_test_active_generation(uint32_t *generation_out)
{
    if (generation_out == NULL || !s_test_backend || !s_test_active_valid ||
        !s_test_slot_valid[s_test_active]) {
        return ESP_ERR_INVALID_STATE;
    }

    provision_config_t *config = calloc(1, sizeof(*config));
    if (config == NULL) {
        return ESP_ERR_NO_MEM;
    }
    esp_err_t err = provision_store_decode(
        (const uint8_t *)&s_test_slots[s_test_active],
        sizeof(s_test_slots[s_test_active]),
        config,
        generation_out);
    memset(config, 0, sizeof(*config));
    free(config);
    return err;
}
#endif
