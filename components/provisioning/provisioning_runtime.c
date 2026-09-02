#include "provisioning_runtime.h"

#include <stdio.h>
#include <string.h>

#include "esp_check.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "esp_wifi_default.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "lwip/inet.h"

#define PROVISIONING_AP_CHANNEL 6
#define PROVISIONING_AP_MAX_CLIENTS 2
#define PROVISIONING_STA_FAILURE_RETRY_COUNT 5
#define PROVISIONING_STA_MIN_RSSI -90
#define PROVISIONING_WIFI_MODE_RETRY_COUNT 6
#define PROVISIONING_WIFI_MODE_RETRY_DELAY_MS 100
#define PROVISIONING_DHCPS_DNS_OFFER 0x02
#define PROVISIONING_EVENT_QUEUE_LEN 8

static const char *TAG = "ancs_provisioning";

esp_err_t provisioning_captive_dns_start(esp_netif_t *ap_netif);
esp_err_t provisioning_captive_dns_stop(void);

typedef struct {
    provisioning_runtime_event_t event;
} provisioning_runtime_event_msg_t;

static bool s_initialized;
static bool s_event_loop_ready;
static bool s_wifi_started;
static bool s_ap_started;
static bool s_sta_started;
static bool s_sta_connecting;
static bool s_sta_has_ip;
static uint32_t s_last_wifi_disconnect_reason;
static int32_t s_last_wifi_disconnect_rssi;
static esp_event_handler_instance_t s_wifi_handler_instance;
static esp_event_handler_instance_t s_ip_handler_instance;
static esp_netif_t *s_ap_netif;
static esp_netif_t *s_sta_netif;
static SemaphoreHandle_t s_wifi_operation_mutex;
static QueueHandle_t s_event_queue;
static TaskHandle_t s_event_task;
static TaskHandle_t s_wifi_timeout_task;
static portMUX_TYPE s_state_lock = portMUX_INITIALIZER_UNLOCKED;
static uint32_t s_event_overflow_count;
static uint32_t s_next_sta_attempt_generation;
static uint32_t s_active_sta_attempt_generation;
static provisioning_event_callback_t s_callback;
static void *s_callback_context;
static char s_ap_ssid[sizeof(PROVISIONING_RUNTIME_AP_SSID_PREFIX) + 12];
static char s_ap_password[sizeof(PROVISIONING_RUNTIME_AP_PASSWORD_PREFIX) + 12];
static char s_captiveportal_uri[] = PROVISIONING_RUNTIME_CAPTIVE_URI;

static esp_err_t apply_wifi_mode(void);
static esp_err_t apply_wifi_mode_unlocked(void);

static void lock_state(void)
{
    taskENTER_CRITICAL(&s_state_lock);
}

static void unlock_state(void)
{
    taskEXIT_CRITICAL(&s_state_lock);
}

static esp_err_t lock_wifi_operation(void)
{
    ESP_RETURN_ON_FALSE(s_wifi_operation_mutex != NULL,
                        ESP_ERR_INVALID_STATE,
                        TAG,
                        "wifi operation mutex missing");
    return xSemaphoreTake(s_wifi_operation_mutex, portMAX_DELAY) == pdTRUE
               ? ESP_OK
               : ESP_ERR_TIMEOUT;
}

static void unlock_wifi_operation(void)
{
    if (s_wifi_operation_mutex != NULL) {
        (void)xSemaphoreGive(s_wifi_operation_mutex);
    }
}

static void event_callback_task(void *arg)
{
    (void)arg;
    provisioning_runtime_event_msg_t msg;
    for (;;) {
        if (xQueueReceive(s_event_queue, &msg, portMAX_DELAY) != pdTRUE) {
            continue;
        }

        lock_state();
        provisioning_event_callback_t callback = s_callback;
        void *context = s_callback_context;
        unlock_state();

        if (callback != NULL) {
            callback(&msg.event, context);
        }
    }
}

static uint32_t next_sta_attempt_generation(void)
{
    uint32_t generation = ++s_next_sta_attempt_generation;
    if (generation == 0) {
        generation = ++s_next_sta_attempt_generation;
    }
    return generation;
}

static void dispatch_event_with_generation(provisioning_event_t event,
                                           uint32_t sta_attempt_generation)
{
    if (s_event_queue == NULL) {
        return;
    }

    provisioning_runtime_event_msg_t msg = {
        .event = {
            .event = event,
            .sta_attempt_generation = sta_attempt_generation,
        },
    };
    if (xQueueSend(s_event_queue, &msg, 0) != pdTRUE) {
        lock_state();
        ++s_event_overflow_count;
        unlock_state();
    }
}

static void dispatch_event(provisioning_event_t event)
{
    dispatch_event_with_generation(event, 0);
}

static void schedule_wifi_timeout(uint32_t attempt_generation)
{
    if (s_wifi_timeout_task != NULL) {
        (void)xTaskNotify(s_wifi_timeout_task,
                          attempt_generation,
                          eSetValueWithOverwrite);
    }
}

static void cancel_wifi_timeout(void)
{
    schedule_wifi_timeout(0);
}

static void wifi_timeout_task(void *arg)
{
    (void)arg;
    uint32_t pending_generation = 0;
    for (;;) {
        uint32_t notification = 0;
        if (pending_generation == 0) {
            (void)xTaskNotifyWait(0, UINT32_MAX, &notification, portMAX_DELAY);
            pending_generation = notification;
            continue;
        }

        if (xTaskNotifyWait(0,
                            UINT32_MAX,
                            &notification,
                            pdMS_TO_TICKS(PROVISIONING_RUNTIME_WIFI_TIMEOUT_MS)) == pdTRUE) {
            pending_generation = notification;
            continue;
        }

        const uint32_t expired_generation = pending_generation;
        pending_generation = 0;
        bool dispatch_timeout = false;
        lock_state();
        if (s_active_sta_attempt_generation == expired_generation &&
            s_sta_started && s_sta_connecting) {
            s_sta_started = false;
            s_sta_connecting = false;
            s_sta_has_ip = false;
            s_active_sta_attempt_generation = 0;
            dispatch_timeout = true;
        }
        unlock_state();
        if (dispatch_timeout) {
            dispatch_event_with_generation(PROVISION_EVENT_WIFI_TIMEOUT, expired_generation);
        }
    }
}

static esp_err_t create_default_event_loop_once(void)
{
    esp_err_t err = esp_event_loop_create_default();
    if (err == ESP_ERR_INVALID_STATE) {
        s_event_loop_ready = true;
        return ESP_OK;
    }
    if (err == ESP_OK) {
        s_event_loop_ready = true;
    }
    return err;
}

static esp_err_t make_ap_identity(void)
{
    if (s_ap_ssid[0] != '\0') {
        return ESP_OK;
    }

    uint8_t mac[6] = {0};
    ESP_RETURN_ON_ERROR(esp_read_mac(mac, ESP_MAC_WIFI_STA),
                        TAG,
                        "read base Wi-Fi MAC");

    char ssid_suffix[7] = {0};
    char password_suffix[7] = {0};
    (void)snprintf(ssid_suffix,
                   sizeof(ssid_suffix),
                   "%02X%02X%02X",
                   mac[3],
                   mac[4],
                   mac[5]);
    (void)snprintf(password_suffix,
                   sizeof(password_suffix),
                   "%02x%02x%02x",
                   mac[3],
                   mac[4],
                   mac[5]);
    (void)snprintf(s_ap_ssid,
                   sizeof(s_ap_ssid),
                   "%s%s",
                   PROVISIONING_RUNTIME_AP_SSID_PREFIX,
                   ssid_suffix);
    (void)snprintf(s_ap_password,
                   sizeof(s_ap_password),
                   "%s%s",
                   PROVISIONING_RUNTIME_AP_PASSWORD_PREFIX,
                   password_suffix);
    return ESP_OK;
}

static void fill_ap_config(wifi_config_t *ap_config)
{
    memset(ap_config, 0, sizeof(*ap_config));
    strlcpy((char *)ap_config->ap.ssid,
            s_ap_ssid,
            sizeof(ap_config->ap.ssid));
    strlcpy((char *)ap_config->ap.password,
            s_ap_password,
            sizeof(ap_config->ap.password));
    ap_config->ap.ssid_len = strlen(s_ap_ssid);
    ap_config->ap.channel = PROVISIONING_AP_CHANNEL;
    ap_config->ap.max_connection = PROVISIONING_AP_MAX_CLIENTS;
    ap_config->ap.authmode = WIFI_AUTH_WPA2_PSK;
    ap_config->ap.pairwise_cipher = WIFI_CIPHER_TYPE_CCMP;
    ap_config->ap.pmf_cfg.capable = true;
    ap_config->ap.pmf_cfg.required = false;
}

static esp_err_t configure_ap_profile_before_wifi_start(void)
{
    ESP_RETURN_ON_ERROR(make_ap_identity(), TAG, "AP identity");
    ESP_RETURN_ON_ERROR(esp_wifi_set_mode(WIFI_MODE_APSTA),
                        TAG,
                        "enable AP config interface");
    ESP_RETURN_ON_ERROR(
        esp_wifi_set_protocol(
            WIFI_IF_AP,
            WIFI_PROTOCOL_11B | WIFI_PROTOCOL_11G | WIFI_PROTOCOL_11N),
        TAG,
        "set AP compatibility protocols");
    ESP_RETURN_ON_ERROR(esp_wifi_set_bandwidth(WIFI_IF_AP, WIFI_BW20),
                        TAG,
                        "set AP 20 MHz bandwidth");

    wifi_config_t ap_config;
    fill_ap_config(&ap_config);
    ESP_RETURN_ON_ERROR(esp_wifi_set_config(WIFI_IF_AP, &ap_config),
                        TAG,
                        "set AP config");
    return esp_wifi_set_mode(WIFI_MODE_NULL);
}

static esp_err_t configure_ap_ip_and_dhcp(void)
{
    ESP_RETURN_ON_FALSE(s_ap_netif != NULL, ESP_ERR_INVALID_STATE, TAG, "AP netif missing");

    esp_netif_ip_info_t ip_info = {
        .ip = { .addr = ESP_IP4TOADDR(192, 168, 4, 1) },
        .gw = { .addr = ESP_IP4TOADDR(192, 168, 4, 1) },
        .netmask = { .addr = ESP_IP4TOADDR(255, 255, 255, 0) },
    };

    ESP_ERROR_CHECK_WITHOUT_ABORT(esp_netif_dhcps_stop(s_ap_netif));
    ESP_RETURN_ON_ERROR(esp_netif_set_ip_info(s_ap_netif, &ip_info),
                        TAG,
                        "set AP IP 192.168.4.1");

    uint8_t offer_dns = PROVISIONING_DHCPS_DNS_OFFER;
    ESP_RETURN_ON_ERROR(esp_netif_dhcps_option(s_ap_netif,
                                               ESP_NETIF_OP_SET,
                                               ESP_NETIF_DOMAIN_NAME_SERVER,
                                               &offer_dns,
                                               sizeof(offer_dns)),
                        TAG,
                        "set DHCP DNS offer");
    esp_netif_dns_info_t dns = { .ip = { .u_addr = { .ip4 = ip_info.ip }, .type = ESP_IPADDR_TYPE_V4 } };
    ESP_RETURN_ON_ERROR(esp_netif_set_dns_info(s_ap_netif, ESP_NETIF_DNS_MAIN, &dns),
                        TAG,
                        "set AP DNS");

    ESP_RETURN_ON_ERROR(esp_netif_dhcps_option(s_ap_netif,
                                               ESP_NETIF_OP_SET,
                                               ESP_NETIF_CAPTIVEPORTAL_URI,
                                               s_captiveportal_uri,
                                               strlen(s_captiveportal_uri)),
                        TAG,
                        "set DHCP captive URI");
    return esp_netif_dhcps_start(s_ap_netif);
}

static void wifi_event_handler(void *arg,
                               esp_event_base_t event_base,
                               int32_t event_id,
                               void *event_data)
{
    (void)arg;

    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        const wifi_event_sta_disconnected_t *disconnected = event_data;
        bool reconnect = false;
        bool start_reconnect_timeout = false;
        lock_state();
        const bool had_ip = s_sta_has_ip;
        const uint32_t attempt_generation = s_active_sta_attempt_generation;
        s_sta_has_ip = false;
        if (disconnected != NULL) {
            s_last_wifi_disconnect_reason = disconnected->reason;
            s_last_wifi_disconnect_rssi = disconnected->rssi;
        } else {
            s_last_wifi_disconnect_reason = 0;
            s_last_wifi_disconnect_rssi = 0;
        }
        if (had_ip) {
            if (s_sta_started) {
                s_sta_connecting = true;
                reconnect = true;
                start_reconnect_timeout = true;
            }
        } else if (s_sta_started && s_sta_connecting) {
            s_sta_connecting = true;
            reconnect = true;
        }
        unlock_state();
        ESP_LOGW(TAG, "STA disconnected reason=%u rssi=%d",
                 (unsigned)s_last_wifi_disconnect_reason,
                 (int)s_last_wifi_disconnect_rssi);
        if (start_reconnect_timeout) {
            schedule_wifi_timeout(attempt_generation);
        }
        if (reconnect) {
            if (lock_wifi_operation() != ESP_OK) {
                return;
            }
            lock_state();
            const bool reconnect_still_valid =
                s_sta_started && s_sta_connecting &&
                s_active_sta_attempt_generation == attempt_generation;
            unlock_state();
            if (reconnect_still_valid) {
                const esp_err_t reconnect_error = esp_wifi_connect();
                if (reconnect_error != ESP_OK &&
                    reconnect_error != ESP_ERR_WIFI_CONN) {
                    ESP_LOGW(TAG,
                             "STA reconnect start failed: %s",
                             esp_err_to_name(reconnect_error));
                }
            }
            unlock_wifi_operation();
        }
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        lock_state();
        const bool accept_ip = s_sta_started && s_sta_connecting;
        const uint32_t attempt_generation = s_active_sta_attempt_generation;
        if (!accept_ip) {
            unlock_state();
            return;
        }
        s_sta_connecting = false;
        s_sta_has_ip = true;
        s_last_wifi_disconnect_reason = 0;
        s_last_wifi_disconnect_rssi = 0;
        unlock_state();
        cancel_wifi_timeout();
        dispatch_event_with_generation(PROVISION_EVENT_WIFI_CONNECTED, attempt_generation);
    }
}

static esp_err_t ensure_runtime_ready(void)
{
    if (s_initialized) {
        return ESP_OK;
    }

    bool event_queue_created = false;
    bool event_task_created = false;
    bool timeout_task_created = false;
    bool ap_netif_created = false;
    bool sta_netif_created = false;
    bool mutex_created = false;
    bool wifi_initialized = false;
    bool wifi_handler_registered = false;
    bool ip_handler_registered = false;

    esp_err_t err = esp_netif_init();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "netif init failed: %s", esp_err_to_name(err));
        goto init_failed;
    }
    err = create_default_event_loop_once();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "event loop failed: %s", esp_err_to_name(err));
        goto init_failed;
    }

    s_event_queue = xQueueCreate(PROVISIONING_EVENT_QUEUE_LEN,
                                 sizeof(provisioning_runtime_event_msg_t));
    if (s_event_queue == NULL) {
        err = ESP_ERR_NO_MEM;
        ESP_LOGE(TAG, "event queue failed: %s", esp_err_to_name(err));
        goto init_failed;
    }
    event_queue_created = true;
    BaseType_t task_ok = xTaskCreate(event_callback_task,
                                     "provision_events",
                                     3072,
                                     NULL,
                                     5,
                                     &s_event_task);
    if (task_ok != pdPASS) {
        err = ESP_ERR_NO_MEM;
        ESP_LOGE(TAG, "event task failed: %s", esp_err_to_name(err));
        goto init_failed;
    }
    event_task_created = true;
    task_ok = xTaskCreate(wifi_timeout_task,
                          "provision_wifi_timeout",
                          3072,
                          NULL,
                          5,
                          &s_wifi_timeout_task);
    if (task_ok != pdPASS) {
        err = ESP_ERR_NO_MEM;
        ESP_LOGE(TAG, "wifi timeout task failed: %s", esp_err_to_name(err));
        goto init_failed;
    }
    timeout_task_created = true;

    s_ap_netif = esp_netif_create_default_wifi_ap();
    if (s_ap_netif == NULL) {
        err = ESP_FAIL;
        ESP_LOGE(TAG, "create AP netif failed: %s", esp_err_to_name(err));
        goto init_failed;
    }
    ap_netif_created = true;
    s_sta_netif = esp_netif_create_default_wifi_sta();
    if (s_sta_netif == NULL) {
        err = ESP_FAIL;
        ESP_LOGE(TAG, "create STA netif failed: %s", esp_err_to_name(err));
        goto init_failed;
    }
    sta_netif_created = true;

    s_wifi_operation_mutex = xSemaphoreCreateMutex();
    if (s_wifi_operation_mutex == NULL) {
        err = ESP_ERR_NO_MEM;
        ESP_LOGE(TAG, "wifi operation mutex failed: %s", esp_err_to_name(err));
        goto init_failed;
    }
    mutex_created = true;

    wifi_init_config_t wifi_init = WIFI_INIT_CONFIG_DEFAULT();
    err = esp_wifi_init(&wifi_init);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "wifi init failed: %s", esp_err_to_name(err));
        goto init_failed;
    }
    wifi_initialized = true;
    err = configure_ap_profile_before_wifi_start();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "AP profile failed: %s", esp_err_to_name(err));
        goto init_failed;
    }
    err = esp_event_handler_instance_register(WIFI_EVENT,
                                              ESP_EVENT_ANY_ID,
                                              wifi_event_handler,
                                              NULL,
                                              &s_wifi_handler_instance);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "wifi event handler failed: %s", esp_err_to_name(err));
        goto init_failed;
    }
    wifi_handler_registered = true;
    err = esp_event_handler_instance_register(IP_EVENT,
                                              IP_EVENT_STA_GOT_IP,
                                              wifi_event_handler,
                                              NULL,
                                              &s_ip_handler_instance);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "ip event handler failed: %s", esp_err_to_name(err));
        goto init_failed;
    }
    ip_handler_registered = true;

    s_initialized = true;
    return ESP_OK;

init_failed:
    if (ip_handler_registered) {
        (void)esp_event_handler_instance_unregister(IP_EVENT,
                                                    IP_EVENT_STA_GOT_IP,
                                                    s_ip_handler_instance);
        s_ip_handler_instance = NULL;
    }
    if (wifi_handler_registered) {
        (void)esp_event_handler_instance_unregister(WIFI_EVENT,
                                                    ESP_EVENT_ANY_ID,
                                                    s_wifi_handler_instance);
        s_wifi_handler_instance = NULL;
    }
    if (wifi_initialized) {
        (void)esp_wifi_deinit();
    }
    if (sta_netif_created) {
        esp_netif_destroy_default_wifi(s_sta_netif);
        s_sta_netif = NULL;
    }
    if (ap_netif_created) {
        esp_netif_destroy_default_wifi(s_ap_netif);
        s_ap_netif = NULL;
    }
    if (mutex_created) {
        vSemaphoreDelete(s_wifi_operation_mutex);
        s_wifi_operation_mutex = NULL;
    }
    TaskHandle_t current_task = xTaskGetCurrentTaskHandle();
    if (timeout_task_created && s_wifi_timeout_task != NULL &&
        s_wifi_timeout_task != current_task) {
        vTaskDelete(s_wifi_timeout_task);
        s_wifi_timeout_task = NULL;
    }
    if (event_task_created && s_event_task != NULL &&
        s_event_task != current_task) {
        vTaskDelete(s_event_task);
        s_event_task = NULL;
    }
    if (event_queue_created && s_event_queue != NULL) {
        vQueueDelete(s_event_queue);
        s_event_queue = NULL;
    }
    s_initialized = false;
    s_event_loop_ready = false;
    s_wifi_started = false;
    s_ap_started = false;
    s_sta_started = false;
    s_sta_connecting = false;
    s_sta_has_ip = false;
    s_event_overflow_count = 0;
    s_active_sta_attempt_generation = 0;
    return err;
}

static esp_err_t ensure_wifi_started_unlocked(void)
{
    if (s_wifi_started) {
        return ESP_OK;
    }

    ESP_RETURN_ON_ERROR(esp_wifi_set_mode(WIFI_MODE_NULL), TAG, "set wifi null mode");
    ESP_RETURN_ON_ERROR(esp_wifi_start(), TAG, "start wifi");
    s_wifi_started = true;
    return ESP_OK;
}

static esp_err_t ensure_wifi_started(void)
{
    ESP_RETURN_ON_ERROR(lock_wifi_operation(), TAG, "lock wifi operation");
    esp_err_t err = ensure_wifi_started_unlocked();
    unlock_wifi_operation();
    return err;
}

static wifi_mode_t select_wifi_mode_from_flags(void)
{
    lock_state();
    bool ap_started = s_ap_started;
    bool sta_started = s_sta_started;
    unlock_state();

    wifi_mode_t mode = WIFI_MODE_NULL;
    if (ap_started && sta_started) {
        mode = WIFI_MODE_APSTA;
    } else if (ap_started) {
        mode = WIFI_MODE_AP;
    } else if (sta_started) {
        mode = WIFI_MODE_STA;
    }
    return mode;
}

static esp_err_t set_wifi_mode_with_retry(wifi_mode_t mode)
{
    esp_err_t err = ESP_OK;
    for (uint8_t attempt = 0;
         attempt < PROVISIONING_WIFI_MODE_RETRY_COUNT;
         ++attempt) {
        err = esp_wifi_set_mode(mode);
        if (err != ESP_ERR_WIFI_STOP_STATE) {
            return err;
        }
        if (attempt + 1U < PROVISIONING_WIFI_MODE_RETRY_COUNT) {
            vTaskDelay(pdMS_TO_TICKS(PROVISIONING_WIFI_MODE_RETRY_DELAY_MS));
        }
    }
    return err;
}

static esp_err_t apply_wifi_mode_unlocked(void)
{
    return set_wifi_mode_with_retry(select_wifi_mode_from_flags());
}

static esp_err_t apply_wifi_mode(void)
{
    ESP_RETURN_ON_ERROR(lock_wifi_operation(), TAG, "lock wifi operation");
    esp_err_t err = apply_wifi_mode_unlocked();
    unlock_wifi_operation();
    return err;
}

esp_err_t provisioning_runtime_init(const provision_config_t *config,
                                    provisioning_event_callback_t callback,
                                    void *context)
{
    ESP_RETURN_ON_ERROR(ensure_runtime_ready(), TAG, "runtime ready");

    lock_state();
    s_callback = callback;
    s_callback_context = context;
    unlock_state();

    if (provision_config_validate(config) == PROVISION_CONFIG_OK) {
        esp_err_t err = provisioning_runtime_start_sta(config);
        if (err != ESP_OK) {
            return err;
        }
        dispatch_event(PROVISION_EVENT_BOOT_VALID_CONFIG);
        return ESP_OK;
    }

    esp_err_t err = provisioning_runtime_start_ap();
    if (err != ESP_OK) {
        return err;
    }
    dispatch_event(PROVISION_EVENT_BOOT_NO_CONFIG);
    return ESP_OK;
}

esp_err_t provisioning_runtime_start_ap(void)
{
    ESP_RETURN_ON_ERROR(ensure_runtime_ready(), TAG, "runtime ready");
    ESP_RETURN_ON_ERROR(lock_wifi_operation(), TAG, "lock wifi operation");
    esp_err_t err = ensure_wifi_started_unlocked();
    if (err != ESP_OK) {
        unlock_wifi_operation();
        return err;
    }
    lock_state();
    bool ap_started = s_ap_started;
    unlock_state();
    if (ap_started) {
        unlock_wifi_operation();
        return ESP_OK;
    }

    lock_state();
    s_ap_started = true;
    unlock_state();
    err = apply_wifi_mode_unlocked();
    if (err != ESP_OK) {
        lock_state();
        s_ap_started = false;
        unlock_state();
        unlock_wifi_operation();
        return err;
    }
    err = configure_ap_ip_and_dhcp();
    if (err != ESP_OK) {
        lock_state();
        s_ap_started = false;
        unlock_state();
        (void)apply_wifi_mode_unlocked();
        unlock_wifi_operation();
        return err;
    }

    err = provisioning_captive_dns_start(s_ap_netif);
    if (err != ESP_OK) {
        lock_state();
        s_ap_started = false;
        unlock_state();
        (void)apply_wifi_mode_unlocked();
        unlock_wifi_operation();
        return err;
    }
    unlock_wifi_operation();
    ESP_LOGI(TAG, "setup AP started ssid=%s ip=192.168.4.1", s_ap_ssid);
    return ESP_OK;
}

esp_err_t provisioning_runtime_stop_ap(void)
{
    ESP_RETURN_ON_ERROR(lock_wifi_operation(), TAG, "lock wifi operation");
    lock_state();
    bool ap_started = s_ap_started;
    unlock_state();
    if (!ap_started) {
        unlock_wifi_operation();
        return ESP_OK;
    }

    esp_err_t err = provisioning_captive_dns_stop();
    if (err != ESP_OK) {
        unlock_wifi_operation();
        return err;
    }
    lock_state();
    s_ap_started = false;
    unlock_state();
    err = apply_wifi_mode_unlocked();
    unlock_wifi_operation();
    return err;
}

esp_err_t provisioning_runtime_start_sta(const provision_config_t *config)
{
    ESP_RETURN_ON_FALSE(provision_config_validate(config) == PROVISION_CONFIG_OK,
                        ESP_ERR_INVALID_ARG,
                        TAG,
                        "invalid config");
    ESP_RETURN_ON_ERROR(ensure_runtime_ready(), TAG, "runtime ready");
    ESP_RETURN_ON_ERROR(lock_wifi_operation(), TAG, "lock wifi operation");
    esp_err_t err = ensure_wifi_started_unlocked();
    if (err != ESP_OK) {
        unlock_wifi_operation();
        return err;
    }

    wifi_config_t sta_config = {0};
    strlcpy((char *)sta_config.sta.ssid, config->wifi_ssid, sizeof(sta_config.sta.ssid));
    strlcpy((char *)sta_config.sta.password, config->wifi_password, sizeof(sta_config.sta.password));
    sta_config.sta.scan_method = WIFI_ALL_CHANNEL_SCAN;
    sta_config.sta.sort_method = WIFI_CONNECT_AP_BY_SIGNAL;
    sta_config.sta.threshold.rssi = PROVISIONING_STA_MIN_RSSI;
    sta_config.sta.threshold.authmode = WIFI_AUTH_OPEN;
    sta_config.sta.failure_retry_cnt = PROVISIONING_STA_FAILURE_RETRY_COUNT;
    sta_config.sta.sae_pwe_h2e = WPA3_SAE_PWE_BOTH;

    lock_state();
    const uint32_t attempt_generation = next_sta_attempt_generation();
    s_sta_started = true;
    s_sta_connecting = true;
    s_sta_has_ip = false;
    s_active_sta_attempt_generation = attempt_generation;
    s_last_wifi_disconnect_reason = 0;
    s_last_wifi_disconnect_rssi = 0;
    unlock_state();
    err = apply_wifi_mode_unlocked();
    if (err == ESP_OK) {
        err = esp_wifi_set_ps(WIFI_PS_NONE);
    }
    if (err == ESP_OK) {
        err = esp_wifi_set_protocol(
            WIFI_IF_STA,
            WIFI_PROTOCOL_11B | WIFI_PROTOCOL_11G | WIFI_PROTOCOL_11N);
    }
    if (err == ESP_OK) {
        err = esp_wifi_set_bandwidth(WIFI_IF_STA, WIFI_BW20);
    }
    if (err == ESP_OK) {
        err = esp_wifi_set_config(WIFI_IF_STA, &sta_config);
    }
    if (err != ESP_OK) {
        lock_state();
        s_sta_started = false;
        s_sta_connecting = false;
        s_sta_has_ip = false;
        s_active_sta_attempt_generation = 0;
        unlock_state();
        (void)apply_wifi_mode_unlocked();
        unlock_wifi_operation();
        return err;
    }
    schedule_wifi_timeout(attempt_generation);
    err = esp_wifi_connect();
    if (err != ESP_OK) {
        cancel_wifi_timeout();
        lock_state();
        s_sta_started = false;
        s_sta_connecting = false;
        s_sta_has_ip = false;
        s_active_sta_attempt_generation = 0;
        unlock_state();
        (void)apply_wifi_mode_unlocked();
        unlock_wifi_operation();
        return err;
    }
    unlock_wifi_operation();
    ESP_LOGI(TAG, "STA connect started ssid=%s", config->wifi_ssid);
    return ESP_OK;
}

esp_err_t provisioning_runtime_stop_sta(void)
{
    ESP_RETURN_ON_ERROR(lock_wifi_operation(), TAG, "lock wifi operation");
    lock_state();
    bool sta_started = s_sta_started;
    unlock_state();
    if (!sta_started) {
        unlock_wifi_operation();
        return ESP_OK;
    }

    cancel_wifi_timeout();
    lock_state();
    s_sta_started = false;
    s_sta_connecting = false;
    s_sta_has_ip = false;
    s_active_sta_attempt_generation = 0;
    unlock_state();
    esp_err_t err = esp_wifi_disconnect();
    if (err == ESP_ERR_WIFI_NOT_CONNECT) {
        err = ESP_OK;
    }
    esp_err_t mode_err = apply_wifi_mode_unlocked();
    unlock_wifi_operation();
    return err == ESP_OK ? mode_err : err;
}

esp_err_t provisioning_runtime_enter_stable_recovery(void)
{
    ESP_RETURN_ON_ERROR(ensure_runtime_ready(), TAG, "runtime ready");
    ESP_RETURN_ON_ERROR(ensure_wifi_started(), TAG, "wifi started");

    ESP_RETURN_ON_ERROR(provisioning_runtime_stop_sta(), TAG, "stop STA for recovery");
    return provisioning_runtime_start_ap();
}

static esp_err_t finish_scan_restore_if_needed(bool restore_ap_only, esp_err_t primary_err)
{
    if (!restore_ap_only) {
        return primary_err;
    }

    esp_err_t restore_err = apply_wifi_mode_unlocked();
    if (primary_err != ESP_OK) {
        return primary_err;
    }
    return restore_err;
}

esp_err_t provisioning_runtime_scan(wifi_ap_record_t *records, size_t *count)
{
    ESP_RETURN_ON_FALSE(records != NULL && count != NULL, ESP_ERR_INVALID_ARG, TAG, "bad scan args");
    ESP_RETURN_ON_FALSE(*count > 0, ESP_ERR_INVALID_ARG, TAG, "empty scan buffer");
    ESP_RETURN_ON_ERROR(ensure_runtime_ready(), TAG, "runtime ready");
    ESP_RETURN_ON_ERROR(lock_wifi_operation(), TAG, "lock wifi operation");
    esp_err_t err = ensure_wifi_started_unlocked();
    if (err != ESP_OK) {
        unlock_wifi_operation();
        return err;
    }

    lock_state();
    bool sta_connecting = s_sta_connecting;
    unlock_state();
    if (sta_connecting) {
        unlock_wifi_operation();
        return ESP_ERR_INVALID_STATE;
    }

    wifi_mode_t original_mode = WIFI_MODE_NULL;
    err = esp_wifi_get_mode(&original_mode);
    if (err != ESP_OK) {
        unlock_wifi_operation();
        return err;
    }
    const bool restore_ap_only = original_mode == WIFI_MODE_AP;
    if (restore_ap_only) {
        err = esp_wifi_set_mode(WIFI_MODE_APSTA);
        if (err != ESP_OK) {
            unlock_wifi_operation();
            return err;
        }
    }

    wifi_scan_config_t scan_config = {
        .show_hidden = false,
        .scan_type = WIFI_SCAN_TYPE_ACTIVE,
        .home_chan_dwell_time = 30,
        .coex_background_scan = true,
    };
    err = esp_wifi_scan_start(&scan_config, true);
    if (err != ESP_OK) {
        err = finish_scan_restore_if_needed(restore_ap_only, err);
        unlock_wifi_operation();
        return err;
    }

    uint16_t ap_count = 0;
    err = esp_wifi_scan_get_ap_num(&ap_count);
    if (err != ESP_OK) {
        (void)esp_wifi_clear_ap_list();
        err = finish_scan_restore_if_needed(restore_ap_only, err);
        unlock_wifi_operation();
        return err;
    }

    uint16_t requested = (uint16_t)(*count > UINT16_MAX ? UINT16_MAX : *count);
    if (requested > PROVISIONING_RUNTIME_SCAN_MAX_APS) {
        requested = PROVISIONING_RUNTIME_SCAN_MAX_APS;
    }
    if (requested > ap_count) {
        requested = ap_count;
    }
    if (requested == 0) {
        *count = 0;
        (void)esp_wifi_clear_ap_list();
        err = finish_scan_restore_if_needed(restore_ap_only, ESP_OK);
        unlock_wifi_operation();
        return err;
    }

    err = esp_wifi_scan_get_ap_records(&requested, records);
    if (err != ESP_OK) {
        (void)esp_wifi_clear_ap_list();
        err = finish_scan_restore_if_needed(restore_ap_only, err);
        unlock_wifi_operation();
        return err;
    }
    *count = requested;
    (void)esp_wifi_clear_ap_list();
    err = finish_scan_restore_if_needed(restore_ap_only, ESP_OK);
    unlock_wifi_operation();
    return err;
}

esp_err_t provisioning_runtime_notify_mqtt_failed(void)
{
    dispatch_event(PROVISION_EVENT_MQTT_FAILED);
    return ESP_OK;
}

esp_err_t provisioning_runtime_notify_mqtt_connected(void)
{
    dispatch_event(PROVISION_EVENT_MQTT_CONNECTED);
    return ESP_OK;
}

esp_err_t provisioning_runtime_get_status(provisioning_runtime_status_t *out)
{
    ESP_RETURN_ON_FALSE(out != NULL, ESP_ERR_INVALID_ARG, TAG, "missing status");
    memset(out, 0, sizeof(*out));
    lock_state();
    out->initialized = s_initialized && s_event_loop_ready;
    out->ap_started = s_ap_started;
    out->sta_started = s_sta_started;
    out->sta_connecting = s_sta_connecting;
    out->sta_has_ip = s_sta_has_ip;
    out->last_wifi_disconnect_reason = s_last_wifi_disconnect_reason;
    out->last_wifi_disconnect_rssi = s_last_wifi_disconnect_rssi;
    out->event_overflow_count = s_event_overflow_count;
    out->sta_attempt_generation = s_active_sta_attempt_generation;
    strlcpy(out->ap_ssid, s_ap_ssid, sizeof(out->ap_ssid));
    unlock_state();
    return ESP_OK;
}

esp_err_t provisioning_runtime_get_wifi_snapshot(provisioning_wifi_snapshot_t *out)
{
    ESP_RETURN_ON_FALSE(out != NULL, ESP_ERR_INVALID_ARG, TAG, "missing Wi-Fi snapshot");
    memset(out, 0, sizeof(*out));

    lock_state();
    const bool has_ip = s_sta_has_ip;
    esp_netif_t *sta_netif = s_sta_netif;
    unlock_state();
    if (!has_ip) {
        return ESP_OK;
    }

    ESP_RETURN_ON_FALSE(sta_netif != NULL,
                        ESP_ERR_INVALID_STATE,
                        TAG,
                        "station netif missing");

    wifi_ap_record_t ap_info = {0};
    ESP_RETURN_ON_ERROR(esp_wifi_sta_get_ap_info(&ap_info), TAG, "read station AP info");

    esp_netif_ip_info_t ip_info = {0};
    ESP_RETURN_ON_ERROR(esp_netif_get_ip_info(sta_netif, &ip_info),
                        TAG,
                        "read station IP info");
    ESP_RETURN_ON_FALSE(esp_ip4addr_ntoa(&ip_info.ip, out->ip, sizeof(out->ip)) != NULL,
                        ESP_FAIL,
                        TAG,
                        "format station IP");

    strlcpy(out->ssid, (const char *)ap_info.ssid, sizeof(out->ssid));
    out->rssi = ap_info.rssi;
    out->connected = true;
    return ESP_OK;
}
