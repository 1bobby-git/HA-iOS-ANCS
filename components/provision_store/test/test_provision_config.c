#include <string.h>

#include "esp_err.h"
#include "nvs.h"
#include "provision_store.h"
#include "provision_store_test.h"
#include "unity.h"

static provision_config_t valid_config(void)
{
    provision_config_t config = {
        .schema_version = PROVISION_CONFIG_SCHEMA_VERSION,
        .mqtt_port = 1883,
    };
    strcpy(config.wifi_ssid, "ssid");
    strcpy(config.wifi_password, "wifi-secret");
    strcpy(config.mqtt_host, "mqtt.local");
    strcpy(config.mqtt_username, "mqtt-user");
    strcpy(config.mqtt_password, "mqtt-secret");
    strcpy(config.mqtt_client_id, "ios-ancs-c6");
    strcpy(config.mqtt_base_topic, "ios_ancs/c6");
    return config;
}

void test_provision_config_requires_wifi_and_mqtt(void)
{
    provision_config_t config = {0};
    TEST_ASSERT_EQUAL(PROVISION_CONFIG_MISSING_WIFI, provision_config_validate(&config));

    strcpy(config.wifi_ssid, "ssid");
    TEST_ASSERT_EQUAL(PROVISION_CONFIG_MISSING_MQTT_HOST, provision_config_validate(&config));

    strcpy(config.mqtt_host, "mqtt.local");
    config.mqtt_port = 1883;
    TEST_ASSERT_EQUAL(PROVISION_CONFIG_MISSING_MQTT_CLIENT_ID, provision_config_validate(&config));

    strcpy(config.mqtt_client_id, "ios-ancs-c6");
    TEST_ASSERT_EQUAL(PROVISION_CONFIG_MISSING_MQTT_BASE_TOPIC, provision_config_validate(&config));

    strcpy(config.mqtt_base_topic, "ios_ancs/c6");
    TEST_ASSERT_EQUAL(PROVISION_CONFIG_OK, provision_config_validate(&config));
}

void test_tls_requires_ca(void)
{
    provision_config_t config = valid_config();
    config.mqtt_tls = true;
    config.mqtt_ca[0] = '\0';

    TEST_ASSERT_EQUAL(PROVISION_CONFIG_TLS_CA_REQUIRED, provision_config_validate(&config));

    strcpy(config.mqtt_ca, "-----BEGIN CERTIFICATE-----\nca\n-----END CERTIFICATE-----");
    TEST_ASSERT_EQUAL(PROVISION_CONFIG_OK, provision_config_validate(&config));
}

void test_mqtt_client_id_and_base_topic_are_required(void)
{
    provision_config_t config = valid_config();
    config.mqtt_client_id[0] = '\0';
    TEST_ASSERT_EQUAL(PROVISION_CONFIG_MISSING_MQTT_CLIENT_ID, provision_config_validate(&config));

    config = valid_config();
    config.mqtt_base_topic[0] = '\0';
    TEST_ASSERT_EQUAL(PROVISION_CONFIG_MISSING_MQTT_BASE_TOPIC, provision_config_validate(&config));
}

void test_blank_secret_fields_preserve_existing_values(void)
{
    provision_config_t existing = valid_config();
    strcpy(existing.wifi_password, "old-secret");
    strcpy(existing.mqtt_password, "old-mqtt-secret");

    provision_config_t update = valid_config();
    strcpy(update.wifi_ssid, "new-ssid");
    update.wifi_password[0] = '\0';
    update.mqtt_password[0] = '\0';

    provision_config_t merged = {0};
    TEST_ASSERT_EQUAL(ESP_OK, provision_config_merge_preserving_secrets(&existing, &update, &merged));
    TEST_ASSERT_EQUAL_STRING("new-ssid", merged.wifi_ssid);
    TEST_ASSERT_EQUAL_STRING("old-secret", merged.wifi_password);
    TEST_ASSERT_EQUAL_STRING("old-mqtt-secret", merged.mqtt_password);
}

void test_provision_store_decode_rejects_corrupt_crc(void)
{
    provision_config_t config = valid_config();
    uint8_t encoded[sizeof(provision_store_slot_blob_t)] = {0};
    size_t encoded_len = sizeof(encoded);
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_encode_for_test(&config, 7, encoded, &encoded_len));

    encoded[encoded_len - 1] ^= 0x55;

    provision_config_t out = {0};
    uint32_t generation = 0;
    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_CRC, provision_store_decode(encoded, encoded_len, &out, &generation));
}

void test_provision_store_reset_targets_only_provision_partition(void)
{
    provision_store_test_reset_backend_state();
    provision_config_t config = valid_config();
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_save_atomic(&config));

    TEST_ASSERT_EQUAL(ESP_OK, provision_store_reset());
    TEST_ASSERT_EQUAL_STRING("provision", provision_store_test_last_erased_partition());

    provision_config_t loaded = {0};
    TEST_ASSERT_EQUAL(ESP_ERR_NVS_NOT_FOUND, provision_store_load(&loaded));
}

void test_atomic_save_keeps_prior_active_when_commit_fails(void)
{
    provision_store_test_reset_backend_state();

    provision_config_t old_config = valid_config();
    strcpy(old_config.wifi_ssid, "old-ssid");
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_save_atomic(&old_config));

    provision_config_t new_config = valid_config();
    strcpy(new_config.wifi_ssid, "new-ssid");
    provision_store_test_fail_next_commit();
    TEST_ASSERT_NOT_EQUAL(ESP_OK, provision_store_save_atomic(&new_config));

    provision_config_t loaded = {0};
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_load(&loaded));
    TEST_ASSERT_EQUAL_STRING("old-ssid", loaded.wifi_ssid);
}

void test_atomic_save_switches_active_only_after_inactive_readback(void)
{
    provision_store_test_reset_backend_state();

    provision_config_t old_config = valid_config();
    strcpy(old_config.wifi_ssid, "old-ssid");
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_save_atomic(&old_config));

    provision_config_t new_config = valid_config();
    strcpy(new_config.wifi_ssid, "new-ssid");
    provision_store_test_fail_next_readback();
    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_CRC, provision_store_save_atomic(&new_config));

    provision_config_t loaded = {0};
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_load(&loaded));
    TEST_ASSERT_EQUAL_STRING("old-ssid", loaded.wifi_ssid);

    TEST_ASSERT_EQUAL(ESP_OK, provision_store_save_atomic(&new_config));
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_load(&loaded));
    TEST_ASSERT_EQUAL_STRING("new-ssid", loaded.wifi_ssid);
}

void test_load_falls_back_to_other_valid_slot_when_active_is_corrupt(void)
{
    provision_store_test_reset_backend_state();

    provision_config_t older = valid_config();
    strcpy(older.wifi_ssid, "older");
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_save_atomic(&older));

    provision_config_t newer = valid_config();
    strcpy(newer.wifi_ssid, "newer");
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_save_atomic(&newer));

    provision_store_test_corrupt_active_slot();

    provision_config_t loaded = {0};
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_load(&loaded));
    TEST_ASSERT_EQUAL_STRING("older", loaded.wifi_ssid);
}

void test_valid_active_pointer_wins_over_higher_generation_inactive_slot(void)
{
    provision_store_test_reset_backend_state();

    provision_config_t active = valid_config();
    strcpy(active.wifi_ssid, "active-gen1");
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_test_seed_slot(0, &active, 1, true, false));

    provision_config_t inactive = valid_config();
    strcpy(inactive.wifi_ssid, "inactive-gen2");
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_test_seed_slot(1, &inactive, 2, false, false));

    provision_config_t loaded = {0};
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_load(&loaded));
    TEST_ASSERT_EQUAL_STRING("active-gen1", loaded.wifi_ssid);
}

void test_save_uses_fallback_generation_when_active_slot_is_corrupt(void)
{
    provision_store_test_reset_backend_state();

    provision_config_t fallback = valid_config();
    strcpy(fallback.wifi_ssid, "fallback");
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_test_seed_slot(0, &fallback, 9, false, false));

    provision_config_t corrupt_active = valid_config();
    strcpy(corrupt_active.wifi_ssid, "corrupt-active");
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_test_seed_slot(1, &corrupt_active, 10, true, true));

    provision_config_t replacement = valid_config();
    strcpy(replacement.wifi_ssid, "replacement");
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_save_atomic(&replacement));

    provision_config_t loaded = {0};
    uint32_t generation = 0;
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_load(&loaded));
    TEST_ASSERT_EQUAL_STRING("replacement", loaded.wifi_ssid);
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_test_active_generation(&generation));
    TEST_ASSERT_EQUAL_UINT32(10, generation);
}

void test_active_pointer_commit_failure_keeps_old_fallback_loadable(void)
{
    provision_store_test_reset_backend_state();

    provision_config_t fallback = valid_config();
    strcpy(fallback.wifi_ssid, "fallback");
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_test_seed_slot(0, &fallback, 9, false, false));

    provision_config_t corrupt_active = valid_config();
    strcpy(corrupt_active.wifi_ssid, "corrupt-active");
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_test_seed_slot(1, &corrupt_active, 10, true, true));

    provision_config_t replacement = valid_config();
    strcpy(replacement.wifi_ssid, "replacement");
    provision_store_test_fail_next_active_commit();
    TEST_ASSERT_NOT_EQUAL(ESP_OK, provision_store_save_atomic(&replacement));

    provision_config_t loaded = {0};
    uint32_t generation = 0;
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_load(&loaded));
    TEST_ASSERT_EQUAL_STRING("fallback", loaded.wifi_ssid);
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_test_active_generation(&generation));
    TEST_ASSERT_EQUAL_UINT32(9, generation);
}

void test_active_commit_failure_does_not_promote_higher_generation_inactive_slot(void)
{
    provision_store_test_reset_backend_state();

    provision_config_t active = valid_config();
    strcpy(active.wifi_ssid, "active-gen1");
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_test_seed_slot(0, &active, 1, true, false));

    provision_config_t replacement = valid_config();
    strcpy(replacement.wifi_ssid, "inactive-gen2");
    provision_store_test_fail_next_active_commit();
    TEST_ASSERT_NOT_EQUAL(ESP_OK, provision_store_save_atomic(&replacement));

    provision_config_t loaded = {0};
    uint32_t generation = 0;
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_load(&loaded));
    TEST_ASSERT_EQUAL_STRING("active-gen1", loaded.wifi_ssid);
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_test_active_generation(&generation));
    TEST_ASSERT_EQUAL_UINT32(1, generation);
}

void test_generation_max_is_newer_than_zero_and_refuses_wrap(void)
{
    provision_store_test_reset_backend_state();

    provision_config_t max_config = valid_config();
    strcpy(max_config.wifi_ssid, "max-generation");
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_test_seed_slot(0, &max_config, UINT32_MAX, true, false));

    provision_config_t zero_config = valid_config();
    strcpy(zero_config.wifi_ssid, "zero-generation");
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_test_seed_slot(1, &zero_config, 0, false, false));

    provision_config_t loaded = {0};
    TEST_ASSERT_EQUAL(ESP_OK, provision_store_load(&loaded));
    TEST_ASSERT_EQUAL_STRING("max-generation", loaded.wifi_ssid);

    provision_config_t replacement = valid_config();
    strcpy(replacement.wifi_ssid, "replacement");
    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_STATE, provision_store_save_atomic(&replacement));

    TEST_ASSERT_EQUAL(ESP_OK, provision_store_load(&loaded));
    TEST_ASSERT_EQUAL_STRING("max-generation", loaded.wifi_ssid);
}

void test_redacted_status_exposes_flags_without_secret_material(void)
{
    provision_config_t config = valid_config();
    config.mqtt_tls = true;
    strcpy(config.mqtt_ca, "-----BEGIN CERTIFICATE-----secret-ca");

    provision_config_status_t status = {0};
    TEST_ASSERT_EQUAL(ESP_OK, provision_config_redact_status(&config, &status));
    TEST_ASSERT_EQUAL_STRING("ssid", status.wifi_ssid);
    TEST_ASSERT_TRUE(status.wifi_password_configured);
    TEST_ASSERT_EQUAL_STRING("mqtt.local", status.mqtt_host);
    TEST_ASSERT_EQUAL_UINT16(1883, status.mqtt_port);
    TEST_ASSERT_EQUAL_STRING("mqtt-user", status.mqtt_username);
    TEST_ASSERT_TRUE(status.mqtt_password_configured);
    TEST_ASSERT_TRUE(status.mqtt_tls);
    TEST_ASSERT_TRUE(status.mqtt_ca_configured);
}

TEST_CASE("provision config requires wifi and mqtt fields in order", "[provision_store]")
{
    test_provision_config_requires_wifi_and_mqtt();
}

TEST_CASE("provision config tls requires ca", "[provision_store]")
{
    test_tls_requires_ca();
}

TEST_CASE("provision config requires mqtt client id and base topic", "[provision_store]")
{
    test_mqtt_client_id_and_base_topic_are_required();
}

TEST_CASE("provision config blank secret fields preserve existing values", "[provision_store]")
{
    test_blank_secret_fields_preserve_existing_values();
}

TEST_CASE("provision store decode rejects corrupt crc", "[provision_store]")
{
    test_provision_store_decode_rejects_corrupt_crc();
}

TEST_CASE("provision store reset targets only provision partition", "[provision_store]")
{
    test_provision_store_reset_targets_only_provision_partition();
}

TEST_CASE("provision store atomic save keeps prior active when commit fails", "[provision_store]")
{
    test_atomic_save_keeps_prior_active_when_commit_fails();
}

TEST_CASE("provision store atomic save switches active only after readback", "[provision_store]")
{
    test_atomic_save_switches_active_only_after_inactive_readback();
}

TEST_CASE("provision store load falls back when active slot corrupt", "[provision_store]")
{
    test_load_falls_back_to_other_valid_slot_when_active_is_corrupt();
}

TEST_CASE("provision store valid active pointer wins over higher inactive", "[provision_store]")
{
    test_valid_active_pointer_wins_over_higher_generation_inactive_slot();
}

TEST_CASE("provision store save uses fallback generation when active corrupt", "[provision_store]")
{
    test_save_uses_fallback_generation_when_active_slot_is_corrupt();
}

TEST_CASE("provision store active commit failure keeps fallback loadable", "[provision_store]")
{
    test_active_pointer_commit_failure_keeps_old_fallback_loadable();
}

TEST_CASE("provision store active commit failure does not promote inactive", "[provision_store]")
{
    test_active_commit_failure_does_not_promote_higher_generation_inactive_slot();
}

TEST_CASE("provision store generation max refuses wrap", "[provision_store]")
{
    test_generation_max_is_newer_than_zero_and_refuses_wrap();
}

TEST_CASE("provision config redacted status omits secret material", "[provision_store]")
{
    test_redacted_status_exposes_flags_without_secret_material();
}
