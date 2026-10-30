#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "provision_store.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    /* Merge as before: a blank password keeps the stored one. */
    PROVISION_MQTT_PASSWORD_KEEP = 0,
    /* Refuse the save and ask the user to type the password again. */
    PROVISION_MQTT_PASSWORD_REQUIRED,
    /* New broker without a username: save without a password. */
    PROVISION_MQTT_PASSWORD_DROP,
} provision_mqtt_password_rule_t;

/*
 * Fingerprint of the settings that decide whether the broker accepts this
 * device: host, port, TLS mode and CA, username, password and client ID.
 * Wi-Fi settings and the base topic are not part of it. Returns 0 only for
 * a NULL config.
 */
uint32_t provision_config_mqtt_fingerprint(const provision_config_t *config);

/* True when update names a different broker address (host or port). */
bool provision_config_mqtt_server_changed(const provision_config_t *existing,
                                          const provision_config_t *update);

/*
 * Whether a blank MQTT password in update may reuse the stored one.
 * Settings that already connected (existing_verified) never send their
 * password to a different broker address. Settings that never connected keep
 * the old behaviour so fixing a first-install typo stays one step.
 */
provision_mqtt_password_rule_t provision_config_mqtt_password_rule(
    const provision_config_t *existing,
    const provision_config_t *update,
    bool existing_verified);

#ifdef __cplusplus
}
#endif
