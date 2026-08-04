#include <stdbool.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "ancs_client.h"
#include "esp_app_desc.h"
#include "esp_chip_info.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "freertos/timers.h"
#include "mqtt_relay.h"
#include "notification_sink.h"
#include "nvs_flash.h"
#include "platform_identity.h"
#include "portal_http.h"
#include "provision_store.h"
#include "provisioning_runtime.h"
#include "provisioning_state.h"

#define APP_EVENT_QUEUE_LENGTH 16
#define APP_COORDINATOR_STACK 6144
#define APP_COORDINATOR_PRIORITY 6
#define APP_MQTT_RETRY_MS 5000
#define APP_BOND_POLL_MS 1000
#define APP_RESTART_DELAY_MS 750
#define APP_CONFIG_HANDOFF_DELAY_MS 750
#define APP_WIFI_STATUS_REFRESH_MS 60000

static const char *const TAG = "ANCS_APP";

typedef enum {
    APP_EVENT_PROVISIONING = 0,
    APP_EVENT_MQTT,
    APP_EVENT_CONFIG_CHANGED,
    APP_EVENT_MQTT_RETRY,
    APP_EVENT_BOND_POLL,
    APP_EVENT_WIFI_STATUS_REFRESH,
    APP_EVENT_RESET_PROVISIONING,
} app_event_type_t;

typedef struct {
    app_event_type_t type;
    provisioning_event_t provisioning;
    mqtt_relay_event_t mqtt;
    provision_config_t *config;
    uint32_t sta_attempt_generation;
} app_event_msg_t;

typedef struct {
    provisioning_state_t state;
    provision_config_t config;
    bool config_valid;
    bool mqtt_initialized;
    bool mqtt_started;
    mqtt_relay_device_info_t device_info;
    uint32_t active_sta_attempt_generation;
} app_coordinator_state_t;

typedef struct {
    provisioning_state_t state;
    bool config_valid;
    bool mqtt_initialized;
    bool mqtt_started;
} app_runtime_snapshot_t;

static app_coordinator_state_t s_app;
static QueueHandle_t s_event_queue;
static TaskHandle_t s_event_task;
static TimerHandle_t s_recovery_timer;
static TimerHandle_t s_mqtt_retry_timer;
static TimerHandle_t s_bond_poll_timer;
static TimerHandle_t s_wifi_status_timer;
static TimerHandle_t s_restart_timer;
static portMUX_TYPE s_state_lock = portMUX_INITIALIZER_UNLOCKED;

static void app_state_lock(void)
{
    taskENTER_CRITICAL(&s_state_lock);
}

static void app_state_unlock(void)
{
    taskEXIT_CRITICAL(&s_state_lock);
}

static uint64_t app_now_us(void)
{
    return (uint64_t)esp_timer_get_time();
}

static uint64_t app_now_ms(void)
{
    return app_now_us() / 1000;
}

static mqtt_relay_device_info_t build_device_info(void)
{
    mqtt_relay_device_info_t info = {0};
    strlcpy(info.manufacturer,
            "Espressif Systems",
            sizeof(info.manufacturer));
    strlcpy(info.model, ANCS_DEVICE_MODEL, sizeof(info.model));

    const esp_app_desc_t *description = esp_app_get_description();
    if (description != NULL) {
        strlcpy(info.sw_version,
                description->version,
                sizeof(info.sw_version));
    }

    esp_chip_info_t chip = {0};
    esp_chip_info(&chip);
    (void)snprintf(info.hw_version,
                   sizeof(info.hw_version),
                   "rev %u.%u",
                   chip.revision / 100U,
                   chip.revision % 100U);
    return info;
}

static bool app_post(const app_event_msg_t *message)
{
    if (message == NULL || s_event_queue == NULL) {
        return false;
    }
    return xQueueSend(s_event_queue, message, 0) == pdTRUE;
}

static void app_post_provisioning(provisioning_event_t event,
                                  uint32_t sta_attempt_generation)
{
    const app_event_msg_t message = {
        .type = APP_EVENT_PROVISIONING,
        .provisioning = event,
        .sta_attempt_generation = sta_attempt_generation,
    };
    if (!app_post(&message)) {
        ESP_LOGW(TAG, "coordinator queue full event=%d", event);
    }
}

static void provisioning_event_callback(const provisioning_runtime_event_t *runtime_event,
                                        void *context)
{
    (void)context;
    if (runtime_event == NULL) {
        return;
    }
    app_post_provisioning(runtime_event->event,
                          runtime_event->sta_attempt_generation);
}

static void mqtt_event_callback(mqtt_relay_event_t event, void *context)
{
    (void)context;
    const app_event_msg_t message = {
        .type = APP_EVENT_MQTT,
        .mqtt = event,
    };
    if (!app_post(&message)) {
        ESP_LOGW(TAG, "coordinator queue full mqtt_event=%d", event);
    }
}

static void boot_held_callback(void *context)
{
    (void)context;
    app_post_provisioning(PROVISION_EVENT_BOOT_HELD_3S, 0);
}

static void recovery_timer_callback(TimerHandle_t timer)
{
    (void)timer;
    app_post_provisioning(PROVISION_EVENT_PORTAL_IDLE_TIMEOUT, 0);
}

static void mqtt_retry_timer_callback(TimerHandle_t timer)
{
    (void)timer;
    const app_event_msg_t message = {
        .type = APP_EVENT_MQTT_RETRY,
    };
    (void)app_post(&message);
}

static void bond_poll_timer_callback(TimerHandle_t timer)
{
    (void)timer;
    const app_event_msg_t message = {
        .type = APP_EVENT_BOND_POLL,
    };
    (void)app_post(&message);
}

static void wifi_status_timer_callback(TimerHandle_t timer)
{
    (void)timer;
    const app_event_msg_t message = {
        .type = APP_EVENT_WIFI_STATUS_REFRESH,
    };
    (void)app_post(&message);
}

static void restart_timer_callback(TimerHandle_t timer)
{
    (void)timer;
    esp_restart();
}

static app_runtime_snapshot_t app_runtime_snapshot(void)
{
    app_state_lock();
    const app_runtime_snapshot_t snapshot = {
        .state = s_app.state,
        .config_valid = s_app.config_valid,
        .mqtt_initialized = s_app.mqtt_initialized,
        .mqtt_started = s_app.mqtt_started,
    };
    app_state_unlock();
    return snapshot;
}

static void app_store_reducer_state(provisioning_state_t state)
{
    app_state_lock();
    s_app.state = state;
    app_state_unlock();
}

static esp_err_t portal_status(portal_http_system_status_t *out, void *context)
{
    (void)context;
    if (out == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    const app_runtime_snapshot_t app = app_runtime_snapshot();
    const ancs_client_enrollment_status_t ble =
        ancs_client_get_enrollment_status();
    mqtt_relay_counters_t counters = {0};
    mqtt_relay_get_counters(&counters);

    *out = (portal_http_system_status_t) {
        .mqtt_connected = app.state.mqtt_connected,
        .ble_bonded = ble.has_bond,
        .ble_connected = ble.connected,
        .enroll_window_open = ble.enroll_active,
        .replace_pending = ble.replace_pending,
        .replace_failed = ble.last_replace_error != ESP_OK,
        .replace_error_code = ble.last_replace_error,
        .notifications_published = counters.published_ack,
        .notifications_dropped = counters.dropped_offline +
                                 counters.dropped_enqueue +
                                 counters.dropped_policy,
    };
    return ESP_OK;
}

static esp_err_t portal_mqtt_test(void *context)
{
    (void)context;
    const app_runtime_snapshot_t app = app_runtime_snapshot();
    if (!app.config_valid || !app.state.wifi_connected) {
        return ESP_ERR_INVALID_STATE;
    }
    if (app.state.mqtt_connected) {
        return ESP_OK;
    }

    const app_event_msg_t message = {
        .type = APP_EVENT_MQTT_RETRY,
    };
    return app_post(&message) ? ESP_OK : ESP_ERR_TIMEOUT;
}

static esp_err_t portal_reconnect(const provision_config_t *config, void *context)
{
    (void)context;
    if (provision_config_validate(config) != PROVISION_CONFIG_OK) {
        return ESP_ERR_INVALID_ARG;
    }

    provision_config_t *copy = malloc(sizeof(*copy));
    if (copy == NULL) {
        return ESP_ERR_NO_MEM;
    }
    *copy = *config;

    const app_event_msg_t message = {
        .type = APP_EVENT_CONFIG_CHANGED,
        .config = copy,
    };
    if (!app_post(&message)) {
        free(copy);
        return ESP_ERR_TIMEOUT;
    }
    return ESP_OK;
}

static esp_err_t portal_ble_replace(void *context)
{
    (void)context;
    return ancs_client_replace_enrollment(true);
}

static esp_err_t schedule_restart(void)
{
    if (s_restart_timer == NULL) {
        return ESP_ERR_INVALID_STATE;
    }
    return xTimerReset(s_restart_timer, 0) == pdPASS ? ESP_OK : ESP_ERR_TIMEOUT;
}

static esp_err_t portal_restart(void *context)
{
    (void)context;
    return schedule_restart();
}

static esp_err_t portal_reset_provisioning(void *context)
{
    (void)context;
    const app_event_msg_t message = {
        .type = APP_EVENT_RESET_PROVISIONING,
    };
    return app_post(&message) ? ESP_OK : ESP_ERR_TIMEOUT;
}

static const portal_http_handlers_t s_portal_handlers = {
    .status = portal_status,
    .mqtt_test = portal_mqtt_test,
    .reconnect = portal_reconnect,
    .ble_replace = portal_ble_replace,
    .restart = portal_restart,
    .reset_provisioning = portal_reset_provisioning,
    .reset_all_data = NULL,
    .context = NULL,
};

static esp_err_t start_recovery_portal(void)
{
    esp_err_t error = provisioning_runtime_start_ap();
    if (error != ESP_OK) {
        ESP_LOGE(TAG, "recovery AP start failed: %s", esp_err_to_name(error));
        return error;
    }
    error = portal_http_init(&s_portal_handlers);
    if (error != ESP_OK) {
        ESP_LOGE(TAG, "recovery portal start failed: %s", esp_err_to_name(error));
        (void)provisioning_runtime_stop_ap();
    }
    return error;
}

static void stop_recovery_portal(void)
{
    esp_err_t error = portal_http_stop();
    if (error != ESP_OK) {
        ESP_LOGW(TAG, "portal stop failed: %s", esp_err_to_name(error));
    }
    error = provisioning_runtime_stop_ap();
    if (error != ESP_OK) {
        ESP_LOGW(TAG, "AP stop failed: %s", esp_err_to_name(error));
    }
}

static void apply_reducer_requirements(provisioning_state_t state)
{
    if (state.ap_required) {
        (void)start_recovery_portal();
    } else {
        stop_recovery_portal();
    }
}

static void stop_mqtt(void)
{
    if (s_wifi_status_timer != NULL) {
        (void)xTimerStop(s_wifi_status_timer, 0);
    }
    app_state_lock();
    const bool initialized = s_app.mqtt_initialized;
    s_app.mqtt_started = false;
    s_app.mqtt_initialized = false;
    app_state_unlock();

    if (initialized) {
        mqtt_relay_set_wifi_connected(false);
        (void)mqtt_relay_deinit();
    }
}

static void schedule_mqtt_retry(void)
{
    if (s_mqtt_retry_timer != NULL) {
        (void)xTimerReset(s_mqtt_retry_timer, 0);
    }
}

static esp_err_t refresh_wifi_status(void)
{
    provisioning_wifi_snapshot_t snapshot = {0};
    const esp_err_t snapshot_error =
        provisioning_runtime_get_wifi_snapshot(&snapshot);

    mqtt_relay_wifi_status_t status = {0};
    if (snapshot_error == ESP_OK && snapshot.connected) {
        status.connected = true;
        status.rssi = snapshot.rssi;
        strlcpy(status.ssid, snapshot.ssid, sizeof(status.ssid));
        strlcpy(status.ip, snapshot.ip, sizeof(status.ip));
    }

    const esp_err_t update_error = mqtt_relay_update_wifi_status(&status);
    return snapshot_error != ESP_OK ? snapshot_error : update_error;
}

static esp_err_t refresh_ble_status(void)
{
    const ancs_client_enrollment_status_t status =
        ancs_client_get_enrollment_status();
    return mqtt_relay_update_ble_status(status.connected, status.has_bond);
}

static esp_err_t start_or_reconnect_mqtt(void)
{
    const app_runtime_snapshot_t app = app_runtime_snapshot();
    if (!app.config_valid || !app.state.wifi_connected) {
        return ESP_ERR_INVALID_STATE;
    }

    esp_err_t error = ESP_OK;
    if (!app.mqtt_initialized) {
        error = mqtt_relay_init(&s_app.config, &s_app.device_info);
        if (error == ESP_OK) {
            error = mqtt_relay_register_event_callback(mqtt_event_callback, NULL);
        }
        if (error == ESP_OK) {
            error = refresh_ble_status();
        }
        if (error == ESP_OK) {
            mqtt_relay_set_wifi_connected(true);
            const esp_err_t status_error = refresh_wifi_status();
            if (status_error != ESP_OK) {
                ESP_LOGW(TAG,
                         "initial Wi-Fi status refresh failed: %s",
                         esp_err_to_name(status_error));
            }
            error = mqtt_relay_start();
        }
        if (error == ESP_OK) {
            app_state_lock();
            s_app.mqtt_initialized = true;
            s_app.mqtt_started = true;
            app_state_unlock();
            return ESP_OK;
        }
        (void)mqtt_relay_deinit();
    } else {
        mqtt_relay_set_wifi_connected(true);
        const esp_err_t status_error = refresh_wifi_status();
        if (status_error != ESP_OK) {
            ESP_LOGW(TAG,
                     "Wi-Fi status refresh before reconnect failed: %s",
                     esp_err_to_name(status_error));
        }
        error = app.mqtt_started ? mqtt_relay_reconnect()
                                 : mqtt_relay_start();
        if (error == ESP_OK) {
            app_state_lock();
            s_app.mqtt_started = true;
            app_state_unlock();
            return ESP_OK;
        }
    }

    ESP_LOGW(TAG, "MQTT connect start failed: %s", esp_err_to_name(error));
    schedule_mqtt_retry();
    return error;
}

static provisioning_state_t reduce_app_state(provisioning_event_t event)
{
    app_state_lock();
    provisioning_state_t current = s_app.state;
    app_state_unlock();

    provisioning_state_t next =
        provisioning_reduce(current, event, app_now_ms());
    app_store_reducer_state(next);
    return next;
}

static void enter_wifi_timeout_recovery(void)
{
    app_state_lock();
    s_app.active_sta_attempt_generation = 0;
    app_state_unlock();
    esp_err_t recovery_error = provisioning_runtime_enter_stable_recovery();
    if (recovery_error != ESP_OK) {
        ESP_LOGW(TAG,
                 "stable recovery entry failed: %s",
                 esp_err_to_name(recovery_error));
    }
    mqtt_relay_set_wifi_connected(false);
    app_state_lock();
    const bool mqtt_initialized = s_app.mqtt_initialized;
    s_app.mqtt_started = false;
    app_state_unlock();
    if (mqtt_initialized) {
        (void)mqtt_relay_stop();
    }
}

static void handle_provisioning_event(provisioning_event_t event,
                                      uint32_t sta_attempt_generation)
{
    if (event == PROVISION_EVENT_WIFI_TIMEOUT) {
        app_state_lock();
        const uint32_t active_generation = s_app.active_sta_attempt_generation;
        app_state_unlock();
        if (sta_attempt_generation == 0 ||
            sta_attempt_generation != active_generation) {
            ESP_LOGW(TAG, "stale Wi-Fi timeout ignored");
            return;
        }
    }

    provisioning_state_t state = reduce_app_state(event);

    switch (event) {
    case PROVISION_EVENT_BOOT_NO_CONFIG:
        stop_mqtt();
        (void)provisioning_runtime_stop_sta();
        app_state_lock();
        s_app.active_sta_attempt_generation = 0;
        app_state_unlock();
        break;

    case PROVISION_EVENT_WIFI_CONNECTED:
        mqtt_relay_set_wifi_connected(true);
        (void)start_or_reconnect_mqtt();
        break;

    case PROVISION_EVENT_WIFI_TIMEOUT: {
        enter_wifi_timeout_recovery();
        break;
    }

    case PROVISION_EVENT_MQTT_CONNECTED:
        if (s_mqtt_retry_timer != NULL) {
            (void)xTimerStop(s_mqtt_retry_timer, 0);
        }
        break;

    case PROVISION_EVENT_MQTT_FAILED:
        if (s_wifi_status_timer != NULL) {
            (void)xTimerStop(s_wifi_status_timer, 0);
        }
        schedule_mqtt_retry();
        break;

    case PROVISION_EVENT_BOOT_HELD_3S:
        if (s_recovery_timer != NULL) {
            (void)xTimerReset(s_recovery_timer, 0);
        }
        break;

    case PROVISION_EVENT_PORTAL_IDLE_TIMEOUT:
        if (s_recovery_timer != NULL) {
            (void)xTimerStop(s_recovery_timer, 0);
        }
        break;

    default:
        break;
    }

    apply_reducer_requirements(state);
}

static void handle_mqtt_event(mqtt_relay_event_t event)
{
    if (event == MQTT_RELAY_EVENT_RESTART_REQUEST) {
        const esp_err_t error = schedule_restart();
        if (error != ESP_OK) {
            ESP_LOGW(TAG,
                     "MQTT restart request failed: %s",
                     esp_err_to_name(error));
        }
        return;
    }

    if (event == MQTT_RELAY_EVENT_ENROLL_REQUEST) {
        const esp_err_t error = ancs_client_request_enroll();
        if (error != ESP_OK) {
            ESP_LOGW(TAG,
                     "MQTT enrollment request failed: %s",
                     esp_err_to_name(error));
        }
        return;
    }

    if (event == MQTT_RELAY_EVENT_CONNECTED) {
        handle_provisioning_event(PROVISION_EVENT_MQTT_CONNECTED, 0);
        if (s_wifi_status_timer != NULL) {
            (void)xTimerReset(s_wifi_status_timer, 0);
        }
        return;
    }

    handle_provisioning_event(PROVISION_EVENT_MQTT_FAILED, 0);
}

static void handle_config_changed(provision_config_t *config)
{
    if (config == NULL) {
        return;
    }

    vTaskDelay(pdMS_TO_TICKS(APP_CONFIG_HANDOFF_DELAY_MS));

    stop_mqtt();
    (void)provisioning_runtime_stop_sta();

    app_state_lock();
    s_app.config = *config;
    s_app.config_valid = true;
    s_app.active_sta_attempt_generation = 0;
    app_state_unlock();
    free(config);

    provisioning_state_t state =
        reduce_app_state(PROVISION_EVENT_BOOT_VALID_CONFIG);
    apply_reducer_requirements(state);

    esp_err_t error = provisioning_runtime_start_sta(&s_app.config);
    if (error != ESP_OK) {
        ESP_LOGW(TAG, "STA reconnect start failed: %s", esp_err_to_name(error));
        state = reduce_app_state(PROVISION_EVENT_WIFI_TIMEOUT);
        enter_wifi_timeout_recovery();
        apply_reducer_requirements(state);
        return;
    }

    provisioning_runtime_status_t runtime = {0};
    if (provisioning_runtime_get_status(&runtime) == ESP_OK) {
        app_state_lock();
        s_app.active_sta_attempt_generation = runtime.sta_attempt_generation;
        app_state_unlock();
    }
}

static void handle_reset_provisioning(void)
{
    const esp_err_t error = provision_store_reset();
    if (error != ESP_OK) {
        ESP_LOGE(TAG,
                 "provisioning reset failed: %s",
                 esp_err_to_name(error));
        return;
    }

    stop_mqtt();
    (void)provisioning_runtime_stop_sta();

    app_state_lock();
    s_app.config = (provision_config_t) {0};
    s_app.config_valid = false;
    s_app.active_sta_attempt_generation = 0;
    app_state_unlock();

    handle_provisioning_event(PROVISION_EVENT_BOOT_NO_CONFIG, 0);
}

static void handle_bond_poll(void)
{
    const ancs_client_enrollment_status_t ble =
        ancs_client_get_enrollment_status();
    const bool has_bond = ble.has_bond;
    const esp_err_t relay_error =
        mqtt_relay_update_ble_status(ble.connected, ble.has_bond);
    if (relay_error != ESP_OK) {
        ESP_LOGW(TAG,
                 "BLE status publish failed: %s",
                 esp_err_to_name(relay_error));
    }
    const app_runtime_snapshot_t app = app_runtime_snapshot();
    if (has_bond != app.state.has_bond) {
        handle_provisioning_event(has_bond ? PROVISION_EVENT_BOND_PRESENT
                                           : PROVISION_EVENT_BOND_REMOVED,
                                  0);
    }
}

static void coordinator_task(void *argument)
{
    (void)argument;
    app_event_msg_t message;
    for (;;) {
        if (xQueueReceive(s_event_queue, &message, portMAX_DELAY) != pdTRUE) {
            continue;
        }

        switch (message.type) {
        case APP_EVENT_PROVISIONING:
            handle_provisioning_event(message.provisioning,
                                      message.sta_attempt_generation);
            break;
        case APP_EVENT_MQTT:
            handle_mqtt_event(message.mqtt);
            break;
        case APP_EVENT_CONFIG_CHANGED:
            handle_config_changed(message.config);
            break;
        case APP_EVENT_MQTT_RETRY:
            (void)start_or_reconnect_mqtt();
            break;
        case APP_EVENT_BOND_POLL:
            handle_bond_poll();
            break;
        case APP_EVENT_WIFI_STATUS_REFRESH: {
            const esp_err_t error = refresh_wifi_status();
            if (error != ESP_OK) {
                ESP_LOGW(TAG,
                         "periodic Wi-Fi status refresh failed: %s",
                         esp_err_to_name(error));
            }
            break;
        }
        case APP_EVENT_RESET_PROVISIONING:
            handle_reset_provisioning();
            break;
        default:
            free(message.config);
            break;
        }
    }
}

static esp_err_t initialize_coordinator(void)
{
    s_app.state = provisioning_initial();
    s_app.device_info = build_device_info();
    s_event_queue = xQueueCreate(APP_EVENT_QUEUE_LENGTH, sizeof(app_event_msg_t));
    if (s_event_queue == NULL) {
        return ESP_ERR_NO_MEM;
    }

    if (xTaskCreate(coordinator_task,
                    "ancs_coordinator",
                    APP_COORDINATOR_STACK,
                    NULL,
                    APP_COORDINATOR_PRIORITY,
                    &s_event_task) != pdPASS) {
        vQueueDelete(s_event_queue);
        s_event_queue = NULL;
        return ESP_ERR_NO_MEM;
    }

    s_recovery_timer = xTimerCreate("recovery_portal",
                                    pdMS_TO_TICKS(PROVISION_RECOVERY_WINDOW_MS),
                                    pdFALSE,
                                    NULL,
                                    recovery_timer_callback);
    s_mqtt_retry_timer = xTimerCreate("mqtt_retry",
                                      pdMS_TO_TICKS(APP_MQTT_RETRY_MS),
                                      pdFALSE,
                                      NULL,
                                      mqtt_retry_timer_callback);
    s_bond_poll_timer = xTimerCreate("bond_poll",
                                     pdMS_TO_TICKS(APP_BOND_POLL_MS),
                                     pdTRUE,
                                     NULL,
                                     bond_poll_timer_callback);
    s_wifi_status_timer = xTimerCreate("wifi_status",
                                      pdMS_TO_TICKS(APP_WIFI_STATUS_REFRESH_MS),
                                      pdTRUE,
                                      NULL,
                                      wifi_status_timer_callback);
    s_restart_timer = xTimerCreate("restart",
                                   pdMS_TO_TICKS(APP_RESTART_DELAY_MS),
                                   pdFALSE,
                                   NULL,
                                   restart_timer_callback);
    if (s_recovery_timer == NULL || s_mqtt_retry_timer == NULL ||
        s_bond_poll_timer == NULL || s_wifi_status_timer == NULL ||
        s_restart_timer == NULL) {
        if (s_recovery_timer != NULL) {
            (void)xTimerDelete(s_recovery_timer, 0);
            s_recovery_timer = NULL;
        }
        if (s_mqtt_retry_timer != NULL) {
            (void)xTimerDelete(s_mqtt_retry_timer, 0);
            s_mqtt_retry_timer = NULL;
        }
        if (s_bond_poll_timer != NULL) {
            (void)xTimerDelete(s_bond_poll_timer, 0);
            s_bond_poll_timer = NULL;
        }
        if (s_wifi_status_timer != NULL) {
            (void)xTimerDelete(s_wifi_status_timer, 0);
            s_wifi_status_timer = NULL;
        }
        if (s_restart_timer != NULL) {
            (void)xTimerDelete(s_restart_timer, 0);
            s_restart_timer = NULL;
        }
        vTaskDelete(s_event_task);
        s_event_task = NULL;
        vQueueDelete(s_event_queue);
        s_event_queue = NULL;
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}

static void log_error(const char *operation, esp_err_t error)
{
    if (error != ESP_OK) {
        ESP_LOGE(TAG, "%s failed: %s", operation, esp_err_to_name(error));
    }
}

void app_main(void)
{
    esp_err_t error = nvs_flash_init();
    log_error("default NVS init", error);

    const esp_err_t provision_error = provision_store_init();
    log_error("provision store init", provision_error);

    error = initialize_coordinator();
    if (error != ESP_OK) {
        log_error("coordinator init", error);
        (void)provisioning_runtime_init(NULL, NULL, NULL);
        (void)start_recovery_portal();
        return;
    }

    const bool config_valid =
        provision_error == ESP_OK &&
        provision_store_load(&s_app.config) == ESP_OK &&
        provision_config_validate(&s_app.config) == PROVISION_CONFIG_OK;
    app_state_lock();
    s_app.config_valid = config_valid;
    app_state_unlock();

    error = notification_sink_register_observer(
        mqtt_relay_observe_notification, NULL);
    log_error("relay observer registration", error);

    error = provisioning_runtime_init(config_valid ? &s_app.config : NULL,
                                      provisioning_event_callback,
                                      NULL);
    if (error != ESP_OK) {
        log_error("provisioning runtime init", error);
        app_post_provisioning(PROVISION_EVENT_BOOT_NO_CONFIG, 0);
        (void)start_recovery_portal();
    } else if (config_valid) {
        provisioning_runtime_status_t runtime = {0};
        if (provisioning_runtime_get_status(&runtime) == ESP_OK) {
            app_state_lock();
            s_app.active_sta_attempt_generation = runtime.sta_attempt_generation;
            app_state_unlock();
        }
    }

    error = ancs_client_init();
    log_error("ANCS client init", error);
    if (error == ESP_OK) {
        log_error("BOOT callback registration",
                  ancs_client_register_boot_held_callback(
                      boot_held_callback, NULL));
        app_post_provisioning(ancs_client_has_bond()
                                  ? PROVISION_EVENT_BOND_PRESENT
                                  : PROVISION_EVENT_BOND_REMOVED,
                              0);
        (void)xTimerStart(s_bond_poll_timer, 0);
    }
}
