#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "provision_store.h"

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Fingerprint of the settings that decide whether the broker accepts this
 * device: host, port, TLS mode and CA, username, password and client ID.
 * Wi-Fi settings and the base topic are not part of it. Returns 0 only for
 * a NULL config.
 */
uint32_t provision_config_mqtt_fingerprint(const provision_config_t *config);

/* True when update names a different broker (host or port) than existing. */
bool provision_config_mqtt_server_changed(const provision_config_t *existing,
                                          const provision_config_t *update);

/*
 * A stored MQTT password is never sent to a different broker. True when the
 * update moves to another broker with a username but a blank password while
 * a password is stored, so the user has to type it again.
 */
bool provision_config_mqtt_password_required(const provision_config_t *existing,
                                             const provision_config_t *update);

#ifdef __cplusplus
}
#endif
