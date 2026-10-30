#include "provision_policy.h"

#include <stddef.h>
#include <string.h>

#define FNV1A_OFFSET UINT32_C(2166136261)
#define FNV1A_PRIME UINT32_C(16777619)

static size_t bounded_length(const char *text, size_t capacity)
{
    size_t length = 0;
    while (length < capacity && text[length] != '\0') {
        ++length;
    }
    return length;
}

static uint32_t fnv1a(uint32_t hash, const void *data, size_t length)
{
    const uint8_t *bytes = data;
    for (size_t index = 0; index < length; ++index) {
        hash ^= bytes[index];
        hash *= FNV1A_PRIME;
    }
    return hash;
}

static uint32_t hash_text(uint32_t hash, const char *text, size_t capacity)
{
    /* The length prefix keeps "ab"+"c" and "a"+"bc" apart. */
    const uint32_t length = (uint32_t)bounded_length(text, capacity);
    const uint8_t prefix[4] = {
        (uint8_t)length,
        (uint8_t)(length >> 8),
        (uint8_t)(length >> 16),
        (uint8_t)(length >> 24),
    };
    hash = fnv1a(hash, prefix, sizeof(prefix));
    return fnv1a(hash, text, length);
}

uint32_t provision_config_mqtt_fingerprint(const provision_config_t *config)
{
    if (config == NULL) {
        return 0U;
    }
    const uint8_t port[2] = {
        (uint8_t)config->mqtt_port,
        (uint8_t)(config->mqtt_port >> 8),
    };
    const uint8_t tls = config->mqtt_tls ? 1U : 0U;

    uint32_t hash = FNV1A_OFFSET;
    hash = hash_text(hash, config->mqtt_host, sizeof(config->mqtt_host));
    hash = fnv1a(hash, port, sizeof(port));
    hash = fnv1a(hash, &tls, sizeof(tls));
    hash = hash_text(hash, config->mqtt_ca, sizeof(config->mqtt_ca));
    hash = hash_text(hash, config->mqtt_username, sizeof(config->mqtt_username));
    hash = hash_text(hash, config->mqtt_password, sizeof(config->mqtt_password));
    hash = hash_text(hash, config->mqtt_client_id, sizeof(config->mqtt_client_id));
    return hash == 0U ? 1U : hash;
}

bool provision_config_mqtt_server_changed(const provision_config_t *existing,
                                          const provision_config_t *update)
{
    if (existing == NULL || update == NULL) {
        return true;
    }
    return existing->mqtt_port != update->mqtt_port ||
           strncmp(existing->mqtt_host, update->mqtt_host,
                   sizeof(existing->mqtt_host)) != 0;
}

provision_mqtt_password_rule_t provision_config_mqtt_password_rule(
    const provision_config_t *existing,
    const provision_config_t *update,
    bool existing_verified)
{
    if (existing == NULL || update == NULL || !existing_verified ||
        update->mqtt_password[0] != '\0' ||
        existing->mqtt_password[0] == '\0' ||
        !provision_config_mqtt_server_changed(existing, update)) {
        return PROVISION_MQTT_PASSWORD_KEEP;
    }
    return update->mqtt_username[0] != '\0' ? PROVISION_MQTT_PASSWORD_REQUIRED
                                            : PROVISION_MQTT_PASSWORD_DROP;
}
