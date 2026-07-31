#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ancs_protocol.h"
#include "esp_err.h"

typedef void (*notification_sink_observer_t)(
    const ancs_notification_t *notification,
    const char *device_name,
    void *context);

int notification_sink_format_json(const ancs_notification_t *notification,
                                  const char *device_name,
                                  char *output,
                                  size_t output_capacity);
int notification_sink_format_state_json(const char *state,
                                        uint32_t session_id,
                                        bool bonded,
                                        bool data_source_subscribed,
                                        bool notification_source_subscribed,
                                        int auth_error,
                                        char *output,
                                        size_t output_capacity);
int notification_sink_publish(const ancs_notification_t *notification,
                              const char *device_name);
esp_err_t notification_sink_register_observer(notification_sink_observer_t observer,
                                              void *context);
int notification_sink_publish_state(const char *state,
                                    uint32_t session_id,
                                    bool bonded,
                                    bool data_source_subscribed,
                                    bool notification_source_subscribed,
                                    int auth_error);
