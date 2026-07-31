#pragma once

#include "mqtt_relay.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef int (*mqtt_relay_publish_for_test_t)(const char *topic,
                                             const char *payload,
                                             int length,
                                             int qos,
                                             int retain);

esp_err_t mqtt_relay_reset_for_test(const provision_config_t *config);
void mqtt_relay_set_publish_for_test(mqtt_relay_publish_for_test_t publish);
void mqtt_relay_simulate_connected_for_test(bool connected);
void mqtt_relay_drain_for_test(void);
void mqtt_relay_simulate_published_for_test(int msg_id);
void mqtt_relay_simulate_disconnect_for_test(void);

#ifdef __cplusplus
}
#endif
