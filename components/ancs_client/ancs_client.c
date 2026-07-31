#include "ancs_client.h"

#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "ancs_protocol.h"
#include "ble_enroll.h"
#include "driver/gpio.h"
#include "esp_bt.h"
#include "esp_bt_device.h"
#include "esp_bt_main.h"
#include "esp_gap_ble_api.h"
#include "esp_gatt_common_api.h"
#include "esp_gattc_api.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "hid_server.h"
#include "notification_sink.h"
#include "platform_identity.h"
#include "nvs_flash.h"

#define ANCS_APP_ID 0
#define INVALID_HANDLE 0
#define ADV_DATA_PENDING (1U << 0)
#define SCAN_RESPONSE_PENDING (1U << 1)
#define CONTROL_REQUEST_MAX 32
#define ADVERTISING_BACKOFF_MAX_MS 4000U
#define DISCOVERY_BACKOFF_MAX_MS 5000U

static const char *const TAG = "ANCS_CLIENT";

static const uint8_t ANCS_SERVICE_UUID[16] = {
    0xD0, 0x00, 0x2D, 0x12, 0x1E, 0x4B, 0x0F, 0xA4,
    0x99, 0x4E, 0xCE, 0xB5, 0x31, 0xF4, 0x05, 0x79,
};
static const uint8_t NOTIFICATION_SOURCE_UUID[16] = {
    0xBD, 0x1D, 0xA2, 0x99, 0xE6, 0x25, 0x58, 0x8C,
    0xD9, 0x42, 0x01, 0x63, 0x0D, 0x12, 0xBF, 0x9F,
};
static const uint8_t CONTROL_POINT_UUID[16] = {
    0xD9, 0xD9, 0xAA, 0xFD, 0xBD, 0x9B, 0x21, 0x98,
    0xA8, 0x49, 0xE1, 0x45, 0xF3, 0xD8, 0xD1, 0x69,
};
static const uint8_t DATA_SOURCE_UUID[16] = {
    0xFB, 0x7B, 0x7C, 0xCE, 0x6A, 0xB3, 0x44, 0xBE,
    0xB5, 0x4B, 0xD6, 0x24, 0xE9, 0xC6, 0xEA, 0x22,
};
static uint8_t s_hid_service_uuid[2] = {0x12, 0x18};

typedef enum {
    WORK_NOTIFICATION_EVENT = 0,
    WORK_DATA_FRAGMENT,
    WORK_CONTROL_WRITE_RESULT,
    WORK_SESSION_RESET,
} work_type_t;

typedef struct {
    uint16_t length;
    uint8_t bytes[];
} data_fragment_t;

typedef struct {
    work_type_t type;
    uint32_t generation;
    union {
        ancs_notification_event_t event;
        data_fragment_t *fragment;
        int write_status;
    } data;
} work_item_t;

typedef struct {
    bool used;
    uint32_t age;
    ancs_notification_t notification;
} cache_entry_t;

typedef struct {
    ancs_client_state_t state;
    esp_gatt_if_t gattc_if;
    uint16_t conn_id;
    esp_bd_addr_t remote_bda;
    esp_ble_addr_type_t remote_addr_type;
    char device_name[32];

    bool connected;
    bool bonded;
    bool mtu_ready;
    bool discovery_in_progress;
    bool service_found;
    bool data_source_subscribed;
    bool notification_source_subscribed;
    bool ready;

    uint16_t service_start_handle;
    uint16_t service_end_handle;
    uint16_t notification_source_handle;
    uint16_t data_source_handle;
    uint16_t control_point_handle;
    uint16_t data_source_cccd_handle;
    uint16_t notification_source_cccd_handle;

    uint32_t session_id;
    uint32_t generation;
    int auth_error;

    bool advertising;
    bool advertising_starting;
    uint8_t advertising_attempt;
    uint8_t discovery_attempt;
    uint8_t adv_config_pending;

    QueueHandle_t work_queue;
    TaskHandle_t worker_task;
    esp_timer_handle_t advertising_retry_timer;
    esp_timer_handle_t discovery_retry_timer;
    esp_timer_handle_t enroll_timer;
    esp_timer_handle_t button_timer;
    bool replace_pending;
    esp_err_t last_replace_error;
    ancs_client_boot_held_callback_t boot_held_callback;
    void *boot_held_callback_context;
} client_context_t;

typedef struct {
    uint32_t generation;
    ancs_request_queue_t pending;
    bool active;
    bool active_canceled;
    uint8_t attempt;
    int64_t deadline_ms;
    ancs_notification_event_t active_event;
    ancs_notification_t active_notification;
    ancs_data_parser_t parser;
    bool last_event_valid;
    ancs_notification_event_t last_event;
    int64_t last_event_ms;
    uint32_t cache_age;
    cache_entry_t cache[CONFIG_ANCS_CACHE_CAPACITY];
} worker_context_t;

static client_context_t s_client = {
    .state = ANCS_STATE_BOOT,
    .gattc_if = ESP_GATT_IF_NONE,
};
static worker_context_t s_worker;
static ble_enroll_state_t s_enroll;
static ble_enroll_button_t s_enroll_button;
static portMUX_TYPE s_shared_state_lock = portMUX_INITIALIZER_UNLOCKED;

static esp_ble_adv_data_t s_adv_data = {
    .set_scan_rsp = false,
    .include_name = true,
    .include_txpower = false,
    .min_interval = 0,
    .max_interval = 0,
    // The HID profile supplies ESP_BLE_APPEARANCE_GENERIC_HID via the GAP service.
    // Keep the primary advertising packet small enough for the full device name.
    .appearance = 0,
    .service_uuid_len = sizeof(s_hid_service_uuid),
    .p_service_uuid = s_hid_service_uuid,
    .flag = ESP_BLE_ADV_FLAG_GEN_DISC | ESP_BLE_ADV_FLAG_BREDR_NOT_SPT,
};
static esp_ble_adv_data_t s_scan_response = {
    .set_scan_rsp = true,
};
static esp_ble_adv_params_t s_adv_params = {
    .adv_int_min = ESP_BLE_GAP_ADV_ITVL_MS(160),
    .adv_int_max = ESP_BLE_GAP_ADV_ITVL_MS(160),
    .adv_type = ADV_TYPE_IND,
    .own_addr_type = BLE_ADDR_TYPE_RPA_PUBLIC,
    .channel_map = ADV_CHNL_ALL,
    .adv_filter_policy = ADV_FILTER_ALLOW_SCAN_ANY_CON_ANY,
};

static void start_advertising(void);
static void stop_advertising(void);
static void start_discovery(void);
static int sync_existing_ble_bond(void);

static int64_t now_ms(void)
{
    return esp_timer_get_time() / 1000;
}

static ble_enroll_config_t enroll_config(void)
{
    return (ble_enroll_config_t){
        .window_ms = CONFIG_ANCS_ENROLL_WINDOW_MS,
        .boot_hold_ms = CONFIG_ANCS_ENROLL_BOOT_HOLD_MS,
        .button_debounce_ms = CONFIG_ANCS_ENROLL_BUTTON_DEBOUNCE_MS,
    };
}

static bool enroll_window_active_now(void)
{
    const int64_t now = now_ms();
    taskENTER_CRITICAL(&s_shared_state_lock);
    const bool active = ble_enroll_window_active(&s_enroll, now);
    taskEXIT_CRITICAL(&s_shared_state_lock);
    return active;
}

static bool enroll_should_advertise_now(void)
{
    const int64_t now = now_ms();
    taskENTER_CRITICAL(&s_shared_state_lock);
    if (s_enroll.window_open &&
        !ble_enroll_window_active(&s_enroll, now)) {
        ble_enroll_close_window(&s_enroll);
    }
    const bool allowed = ble_enroll_should_advertise(&s_enroll, now);
    taskEXIT_CRITICAL(&s_shared_state_lock);
    return allowed;
}

static int current_bond_count(void)
{
    const int bond_count = esp_ble_get_bond_device_num();
    return bond_count < 0 ? 0 : bond_count;
}

static bool bond_list_contains_peer(const uint8_t peer_addr[ESP_BD_ADDR_LEN])
{
    if (peer_addr == NULL) {
        return false;
    }
    const int bond_count = current_bond_count();
    if (bond_count <= 0) {
        return false;
    }
    esp_ble_bond_dev_t *bond_list =
        calloc((size_t)bond_count, sizeof(*bond_list));
    if (bond_list == NULL) {
        ESP_LOGE(TAG, "no memory to check BLE bond list");
        return false;
    }
    int list_count = bond_count;
    bool matched = false;
    if (esp_ble_get_bond_device_list(&list_count, bond_list) == ESP_OK) {
        for (int index = 0; index < list_count; ++index) {
            if (memcmp(bond_list[index].bd_addr, peer_addr, ESP_BD_ADDR_LEN) == 0) {
                matched = true;
                break;
            }
        }
    }
    free(bond_list);
    return matched;
}

static bool connection_peer_allowed(
    const uint8_t peer_addr[ESP_BD_ADDR_LEN])
{
    if (current_bond_count() > 0) {
        return bond_list_contains_peer(peer_addr);
    }
    return enroll_window_active_now();
}

static bool connection_event_matches(
    uint16_t conn_id,
    const uint8_t peer_addr[ESP_BD_ADDR_LEN])
{
    if (peer_addr == NULL) {
        return false;
    }
    taskENTER_CRITICAL(&s_shared_state_lock);
    const bool matched =
        s_client.connected && s_client.conn_id == conn_id &&
        memcmp(s_client.remote_bda, peer_addr, ESP_BD_ADDR_LEN) == 0;
    taskEXIT_CRITICAL(&s_shared_state_lock);
    return matched;
}

static bool authentication_event_matches(
    const uint8_t peer_addr[ESP_BD_ADDR_LEN])
{
    if (peer_addr == NULL) {
        return false;
    }
    taskENTER_CRITICAL(&s_shared_state_lock);
    const bool matched =
        s_client.connected &&
        memcmp(s_client.remote_bda, peer_addr, ESP_BD_ADDR_LEN) == 0;
    taskEXIT_CRITICAL(&s_shared_state_lock);
    return matched;
}

static uint32_t current_generation(void)
{
    taskENTER_CRITICAL(&s_shared_state_lock);
    const uint32_t generation = s_client.generation;
    taskEXIT_CRITICAL(&s_shared_state_lock);
    return generation;
}

static uint32_t current_session_id(void)
{
    taskENTER_CRITICAL(&s_shared_state_lock);
    const uint32_t session_id = s_client.session_id;
    taskEXIT_CRITICAL(&s_shared_state_lock);
    return session_id;
}

static ancs_client_state_t current_state(void)
{
    taskENTER_CRITICAL(&s_shared_state_lock);
    const ancs_client_state_t state = s_client.state;
    taskEXIT_CRITICAL(&s_shared_state_lock);
    return state;
}

static bool client_ready(void)
{
    taskENTER_CRITICAL(&s_shared_state_lock);
    const bool ready = s_client.ready;
    taskEXIT_CRITICAL(&s_shared_state_lock);
    return ready;
}

static void publish_state(void)
{
    taskENTER_CRITICAL(&s_shared_state_lock);
    const ancs_client_state_t state = s_client.state;
    const uint32_t session_id = s_client.session_id;
    const bool bonded = s_client.bonded;
    const bool data_source_subscribed = s_client.data_source_subscribed;
    const bool notification_source_subscribed =
        s_client.notification_source_subscribed;
    const int auth_error = s_client.auth_error;
    taskEXIT_CRITICAL(&s_shared_state_lock);

    (void)notification_sink_publish_state(
        ancs_client_state_name(state),
        session_id,
        bonded,
        data_source_subscribed,
        notification_source_subscribed,
        auth_error);
}

static void set_state(ancs_client_state_t state)
{
    taskENTER_CRITICAL(&s_shared_state_lock);
    const bool changed = s_client.state != state;
    s_client.state = state;
    taskEXIT_CRITICAL(&s_shared_state_lock);
    if (!changed) {
        return;
    }
    ESP_LOGI(TAG, "state=%s", ancs_client_state_name(state));
    publish_state();
}

static void transition(ancs_client_signal_t signal)
{
    taskENTER_CRITICAL(&s_shared_state_lock);
    const ancs_client_state_t state =
        ancs_client_state_after(s_client.state, signal);
    const bool changed = s_client.state != state;
    s_client.state = state;
    taskEXIT_CRITICAL(&s_shared_state_lock);
    if (!changed) {
        return;
    }
    ESP_LOGI(TAG, "state=%s", ancs_client_state_name(state));
    publish_state();
}

static bool uuid_equal(const esp_bt_uuid_t *uuid, const uint8_t expected[16])
{
    return uuid != NULL && uuid->len == ESP_UUID_LEN_128 &&
           memcmp(uuid->uuid.uuid128, expected, 16) == 0;
}

static void invalidate_ancs_handles_locked(void)
{
    s_client.service_found = false;
    s_client.discovery_in_progress = false;
    s_client.ready = false;
    s_client.data_source_subscribed = false;
    s_client.notification_source_subscribed = false;
    s_client.service_start_handle = INVALID_HANDLE;
    s_client.service_end_handle = INVALID_HANDLE;
    s_client.notification_source_handle = INVALID_HANDLE;
    s_client.data_source_handle = INVALID_HANDLE;
    s_client.control_point_handle = INVALID_HANDLE;
    s_client.data_source_cccd_handle = INVALID_HANDLE;
    s_client.notification_source_cccd_handle = INVALID_HANDLE;
}

static void invalidate_ancs_handles(void)
{
    taskENTER_CRITICAL(&s_shared_state_lock);
    invalidate_ancs_handles_locked();
    taskEXIT_CRITICAL(&s_shared_state_lock);
}

static void free_work_item(work_item_t *item)
{
    if (item != NULL && item->type == WORK_DATA_FRAGMENT) {
        free(item->data.fragment);
        item->data.fragment = NULL;
    }
}

static bool enqueue_work(const work_item_t *item)
{
    if (s_client.work_queue == NULL || item == NULL) {
        return false;
    }
    if (xQueueSend(s_client.work_queue, item, 0) != pdTRUE) {
        return false;
    }
    return true;
}

static void reset_worker_session(uint32_t generation)
{
    s_worker.generation = generation;
    ancs_request_queue_clear(&s_worker.pending);
    s_worker.active = false;
    s_worker.active_canceled = false;
    s_worker.last_event_valid = false;
    memset(&s_worker.active_notification, 0, sizeof(s_worker.active_notification));
    memset(&s_worker.parser, 0, sizeof(s_worker.parser));
    memset(s_worker.cache, 0, sizeof(s_worker.cache));
    ESP_LOGI(TAG, "worker session reset generation=%" PRIu32, generation);
}

static cache_entry_t *cache_find(uint32_t session_id, uint32_t uid)
{
    for (size_t index = 0; index < CONFIG_ANCS_CACHE_CAPACITY; ++index) {
        cache_entry_t *entry = &s_worker.cache[index];
        if (entry->used && entry->notification.session_id == session_id &&
            entry->notification.uid == uid) {
            return entry;
        }
    }
    return NULL;
}

static void cache_store(const ancs_notification_t *notification)
{
    cache_entry_t *target =
        cache_find(notification->session_id, notification->uid);
    if (target == NULL) {
        for (size_t index = 0; index < CONFIG_ANCS_CACHE_CAPACITY; ++index) {
            if (!s_worker.cache[index].used) {
                target = &s_worker.cache[index];
                break;
            }
        }
    }
    if (target == NULL) {
        target = &s_worker.cache[0];
        for (size_t index = 1; index < CONFIG_ANCS_CACHE_CAPACITY; ++index) {
            if (s_worker.cache[index].age < target->age) {
                target = &s_worker.cache[index];
            }
        }
    }
    target->used = true;
    target->age = ++s_worker.cache_age;
    target->notification = *notification;
}

static void publish_removed(const ancs_notification_event_t *event)
{
    ancs_notification_t removed;
    const uint32_t session_id = current_session_id();
    cache_entry_t *cached = cache_find(session_id, event->uid);
    if (cached != NULL) {
        removed = cached->notification;
        cached->used = false;
        removed.event_id = event->event_id;
        removed.event_flags = event->event_flags;
        removed.category_id = event->category_id;
        removed.category_count = event->category_count;
        removed.received_at_ms = now_ms();
        removed.complete = true;
        removed.error_code = 0;
    } else {
        ancs_notification_init(
            &removed, session_id, event, now_ms());
        removed.complete = true;
    }
    (void)notification_sink_publish(&removed, s_client.device_name);
}

static void fail_active_request(int error_code)
{
    s_worker.active_notification.complete = false;
    s_worker.active_notification.error_code = error_code;
    (void)notification_sink_publish(
        &s_worker.active_notification, s_client.device_name);
    s_worker.active = false;
    s_worker.active_canceled = false;
}

static void abandon_active_request(void)
{
    s_worker.active = false;
    s_worker.active_canceled = false;
}

static void recover_data_stream(void)
{
    taskENTER_CRITICAL(&s_shared_state_lock);
    s_client.ready = false;
    const bool connected = s_client.connected;
    esp_bd_addr_t remote_bda;
    memcpy(remote_bda, s_client.remote_bda, sizeof(remote_bda));
    taskEXIT_CRITICAL(&s_shared_state_lock);

    set_state(ANCS_STATE_RECOVERING);
    if (connected) {
        (void)esp_ble_gap_disconnect(remote_bda);
    }
}

static esp_err_t write_active_control_request(void)
{
    uint8_t request[CONTROL_REQUEST_MAX];
    size_t request_length = 0;
    const ancs_protocol_error_t protocol_error =
        ancs_build_get_notification_attributes(s_worker.active_event.uid,
                                               request,
                                               sizeof(request),
                                               &request_length);
    if (protocol_error != ANCS_PROTOCOL_OK) {
        return ESP_ERR_INVALID_SIZE;
    }

    taskENTER_CRITICAL(&s_shared_state_lock);
    const bool connection_valid =
        s_client.ready && s_client.connected &&
        s_client.generation == s_worker.generation &&
        s_client.gattc_if != ESP_GATT_IF_NONE &&
        s_client.control_point_handle != INVALID_HANDLE;
    const uint32_t session_id = s_client.session_id;
    const esp_gatt_if_t gattc_if = s_client.gattc_if;
    const uint16_t conn_id = s_client.conn_id;
    const uint16_t control_point_handle = s_client.control_point_handle;
    taskEXIT_CRITICAL(&s_shared_state_lock);
    if (!connection_valid) {
        return ESP_ERR_INVALID_STATE;
    }

    ancs_notification_init(&s_worker.active_notification,
                           session_id,
                           &s_worker.active_event,
                           now_ms());
    ancs_data_parser_init(&s_worker.parser,
                          &s_worker.active_notification,
                          s_worker.active_event.uid,
                          ANCS_ATTR_MASK_REQUIRED);
    const esp_err_t error = esp_ble_gattc_write_char(
        gattc_if,
        conn_id,
        control_point_handle,
        (uint16_t)request_length,
        request,
        ESP_GATT_WRITE_TYPE_RSP,
        ESP_GATT_AUTH_REQ_NO_MITM);
    if (error == ESP_OK) {
        s_worker.deadline_ms = now_ms() + CONFIG_ANCS_REQUEST_TIMEOUT_MS;
        ESP_LOGI(TAG,
                 "requested uid=%" PRIu32 " attempt=%u",
                 s_worker.active_event.uid,
                 (unsigned int)(s_worker.attempt + 1U));
    }
    return error;
}

static void retry_or_fail_active(int error_code)
{
    if (!s_worker.active) {
        return;
    }
    if (!client_ready()) {
        abandon_active_request();
        return;
    }
    if (s_worker.attempt < 1U) {
        s_worker.attempt++;
        const esp_err_t retry_error = write_active_control_request();
        if (retry_error == ESP_OK) {
            return;
        }
        if (retry_error == ESP_ERR_INVALID_STATE) {
            abandon_active_request();
            return;
        }
    }
    fail_active_request(error_code);
    recover_data_stream();
}

static void finish_canceled_request(void)
{
    s_worker.active = false;
    s_worker.active_canceled = false;
}

static void start_next_request(void)
{
    if (s_worker.active || !client_ready()) {
        return;
    }
    if (!ancs_request_queue_pop(&s_worker.pending, &s_worker.active_event)) {
        return;
    }
    s_worker.active = true;
    s_worker.active_canceled = false;
    s_worker.attempt = 0U;
    const esp_err_t error = write_active_control_request();
    if (error == ESP_ERR_INVALID_STATE) {
        abandon_active_request();
    } else if (error != ESP_OK) {
        retry_or_fail_active(ANCS_PROTOCOL_ERR_SEQUENCE);
    }
}

static bool duplicate_event(const ancs_notification_event_t *event, int64_t timestamp)
{
    const bool duplicate =
        s_worker.last_event_valid &&
        s_worker.last_event.event_id == event->event_id &&
        s_worker.last_event.uid == event->uid &&
        s_worker.last_event.event_flags == event->event_flags &&
        s_worker.last_event.category_count == event->category_count &&
        timestamp - s_worker.last_event_ms <= CONFIG_ANCS_DUPLICATE_WINDOW_MS;
    s_worker.last_event = *event;
    s_worker.last_event_ms = timestamp;
    s_worker.last_event_valid = true;
    return duplicate;
}

static void process_notification_event(const ancs_notification_event_t *event)
{
    const int64_t timestamp = now_ms();
    if (duplicate_event(event, timestamp)) {
        ESP_LOGI(TAG,
                 "duplicate suppressed event=%u uid=%" PRIu32,
                 (unsigned int)event->event_id,
                 event->uid);
        return;
    }
    if (event->event_id == 2U) {
        (void)ancs_request_queue_cancel_uid(&s_worker.pending, event->uid);
        if (s_worker.active && s_worker.active_event.uid == event->uid) {
            ESP_LOGI(TAG,
                     "active request canceled; draining response uid=%" PRIu32,
                     event->uid);
            s_worker.active_canceled = true;
        }
        publish_removed(event);
        return;
    }

    if (!ancs_request_queue_push(&s_worker.pending, event)) {
        ancs_notification_t failed;
        ancs_notification_init(
            &failed, current_session_id(), event, timestamp);
        failed.error_code = ANCS_PROTOCOL_ERR_OVERFLOW;
        (void)notification_sink_publish(&failed, s_client.device_name);
        ESP_LOGE(TAG, "request queue full uid=%" PRIu32, event->uid);
    }
}

static void process_data_fragment(data_fragment_t *fragment)
{
    if (fragment == NULL || !s_worker.active) {
        return;
    }
    const ancs_parser_result_t result =
        ancs_data_parser_feed(&s_worker.parser, fragment->bytes, fragment->length);
    if (result == ANCS_PARSER_COMPLETE) {
        if (s_worker.active_canceled) {
            finish_canceled_request();
        } else {
            (void)notification_sink_publish(
                &s_worker.active_notification, s_client.device_name);
            cache_store(&s_worker.active_notification);
            s_worker.active = false;
        }
    } else if (result == ANCS_PARSER_ERROR) {
        if (s_worker.active_canceled) {
            finish_canceled_request();
        } else {
            retry_or_fail_active(s_worker.parser.error_code);
        }
    }
}

static void worker_task(void *argument)
{
    (void)argument;
    ancs_request_queue_init(&s_worker.pending);
    s_worker.generation = current_generation();

    for (;;) {
        const uint32_t generation = current_generation();
        if (s_worker.generation != generation) {
            reset_worker_session(generation);
        }

        work_item_t item = {0};
        if (xQueueReceive(s_client.work_queue, &item, pdMS_TO_TICKS(50)) == pdTRUE) {
            if (item.generation != current_generation()) {
                free_work_item(&item);
                continue;
            }
            switch (item.type) {
            case WORK_NOTIFICATION_EVENT:
                process_notification_event(&item.data.event);
                break;
            case WORK_DATA_FRAGMENT:
                process_data_fragment(item.data.fragment);
                break;
            case WORK_CONTROL_WRITE_RESULT:
                if (item.data.write_status != ESP_GATT_OK) {
                    if (s_worker.active_canceled) {
                        finish_canceled_request();
                    } else {
                        retry_or_fail_active(item.data.write_status);
                    }
                }
                break;
            case WORK_SESSION_RESET:
                reset_worker_session(item.generation);
                break;
            default:
                break;
            }
            free_work_item(&item);
        }

        if (s_worker.active && now_ms() >= s_worker.deadline_ms) {
            if (s_worker.active_canceled) {
                finish_canceled_request();
                recover_data_stream();
            } else {
                retry_or_fail_active(ANCS_PROTOCOL_ERR_TIMEOUT);
            }
        }
        start_next_request();
    }
}

static void advertising_retry_callback(void *argument)
{
    (void)argument;
    start_advertising();
}

static void enroll_timeout_callback(void *argument)
{
    (void)argument;
    taskENTER_CRITICAL(&s_shared_state_lock);
    ble_enroll_close_window(&s_enroll);
    const bool has_bond = ble_enroll_has_bond(&s_enroll);
    taskEXIT_CRITICAL(&s_shared_state_lock);
    if (!has_bond) {
        stop_advertising();
    }
}

static void enroll_button_callback(void *argument)
{
    (void)argument;
    const bool pressed = gpio_get_level(CONFIG_ANCS_ENROLL_BOOT_GPIO) == 0;
    bool should_open = false;
    ancs_client_boot_held_callback_t boot_held_callback = NULL;
    void *boot_held_callback_context = NULL;
    taskENTER_CRITICAL(&s_shared_state_lock);
    should_open = ble_enroll_button_update(&s_enroll_button, pressed, now_ms());
    if (should_open) {
        boot_held_callback = s_client.boot_held_callback;
        boot_held_callback_context = s_client.boot_held_callback_context;
    }
    taskEXIT_CRITICAL(&s_shared_state_lock);
    if (should_open) {
        if (boot_held_callback != NULL) {
            boot_held_callback(boot_held_callback_context);
        }
        (void)ancs_client_request_enroll();
    }
}

static void discovery_retry_callback(void *argument)
{
    (void)argument;
    start_discovery();
}

static void schedule_advertising_retry(void)
{
    taskENTER_CRITICAL(&s_shared_state_lock);
    if (s_client.connected || s_client.advertising ||
        s_client.advertising_starting ||
        !ble_enroll_should_advertise(&s_enroll, now_ms())) {
        taskEXIT_CRITICAL(&s_shared_state_lock);
        return;
    }
    const uint32_t shift =
        s_client.advertising_attempt < 4U ? s_client.advertising_attempt : 4U;
    uint32_t delay_ms = 250U << shift;
    if (delay_ms > ADVERTISING_BACKOFF_MAX_MS) {
        delay_ms = ADVERTISING_BACKOFF_MAX_MS;
    }
    if (s_client.advertising_attempt < UINT8_MAX) {
        s_client.advertising_attempt++;
    }
    taskEXIT_CRITICAL(&s_shared_state_lock);
    (void)esp_timer_stop(s_client.advertising_retry_timer);
    (void)esp_timer_start_once(
        s_client.advertising_retry_timer, (uint64_t)delay_ms * 1000U);
}

static void schedule_discovery_retry(void)
{
    taskENTER_CRITICAL(&s_shared_state_lock);
    if (!s_client.connected || s_client.discovery_in_progress) {
        taskEXIT_CRITICAL(&s_shared_state_lock);
        return;
    }
    const uint32_t shift =
        s_client.discovery_attempt < 3U ? s_client.discovery_attempt : 3U;
    uint32_t delay_ms = 500U << shift;
    if (delay_ms > DISCOVERY_BACKOFF_MAX_MS) {
        delay_ms = DISCOVERY_BACKOFF_MAX_MS;
    }
    if (s_client.discovery_attempt < UINT8_MAX) {
        s_client.discovery_attempt++;
    }
    taskEXIT_CRITICAL(&s_shared_state_lock);
    (void)esp_timer_stop(s_client.discovery_retry_timer);
    (void)esp_timer_start_once(
        s_client.discovery_retry_timer, (uint64_t)delay_ms * 1000U);
}

static void start_advertising(void)
{
    taskENTER_CRITICAL(&s_shared_state_lock);
    if (s_client.connected || s_client.advertising ||
        s_client.advertising_starting || s_client.adv_config_pending != 0U ||
        !ble_enroll_should_advertise(&s_enroll, now_ms())) {
        taskEXIT_CRITICAL(&s_shared_state_lock);
        return;
    }
    if (!hid_server_is_ready()) {
        taskEXIT_CRITICAL(&s_shared_state_lock);
        schedule_advertising_retry();
        return;
    }
    s_client.advertising_starting = true;
    taskEXIT_CRITICAL(&s_shared_state_lock);
    const esp_err_t error = esp_ble_gap_start_advertising(&s_adv_params);
    if (error != ESP_OK) {
        taskENTER_CRITICAL(&s_shared_state_lock);
        s_client.advertising_starting = false;
        taskEXIT_CRITICAL(&s_shared_state_lock);
        ESP_LOGE(TAG, "advertising start call failed: %s", esp_err_to_name(error));
        schedule_advertising_retry();
    }
}

static void stop_advertising(void)
{
    taskENTER_CRITICAL(&s_shared_state_lock);
    const bool active = s_client.advertising || s_client.advertising_starting;
    s_client.advertising = false;
    s_client.advertising_starting = false;
    taskEXIT_CRITICAL(&s_shared_state_lock);
    if (active) {
        (void)esp_ble_gap_stop_advertising();
    }
}

static void maybe_start_discovery(void)
{
    start_discovery();
}

static void start_discovery(void)
{
    taskENTER_CRITICAL(&s_shared_state_lock);
    if (!s_client.connected || !s_client.bonded || !s_client.mtu_ready ||
        s_client.ready || s_client.gattc_if == ESP_GATT_IF_NONE ||
        s_client.discovery_in_progress) {
        taskEXIT_CRITICAL(&s_shared_state_lock);
        return;
    }
    const esp_gatt_if_t gattc_if = s_client.gattc_if;
    const uint16_t conn_id = s_client.conn_id;
    s_client.ready = false;
    s_client.data_source_subscribed = false;
    s_client.notification_source_subscribed = false;
    s_client.notification_source_handle = INVALID_HANDLE;
    s_client.data_source_handle = INVALID_HANDLE;
    s_client.control_point_handle = INVALID_HANDLE;
    s_client.data_source_cccd_handle = INVALID_HANDLE;
    s_client.notification_source_cccd_handle = INVALID_HANDLE;
    s_client.service_found = false;
    s_client.discovery_in_progress = true;
    taskEXIT_CRITICAL(&s_shared_state_lock);

    esp_bt_uuid_t uuid = {
        .len = ESP_UUID_LEN_128,
    };
    memcpy(uuid.uuid.uuid128, ANCS_SERVICE_UUID, sizeof(ANCS_SERVICE_UUID));
    transition(ANCS_SIGNAL_DISCOVERY_STARTED);
    const esp_err_t error =
        esp_ble_gattc_search_service(gattc_if, conn_id, &uuid);
    if (error != ESP_OK) {
        taskENTER_CRITICAL(&s_shared_state_lock);
        s_client.discovery_in_progress = false;
        taskEXIT_CRITICAL(&s_shared_state_lock);
        ESP_LOGE(TAG, "ANCS search start failed: %s", esp_err_to_name(error));
        set_state(ANCS_STATE_RECOVERING);
        schedule_discovery_retry();
    }
}

static esp_err_t write_cccd(uint16_t characteristic_handle, uint16_t *saved_handle)
{
    taskENTER_CRITICAL(&s_shared_state_lock);
    const esp_gatt_if_t gattc_if = s_client.gattc_if;
    const uint16_t conn_id = s_client.conn_id;
    const uint16_t service_start_handle = s_client.service_start_handle;
    const uint16_t service_end_handle = s_client.service_end_handle;
    taskEXIT_CRITICAL(&s_shared_state_lock);

    uint16_t count = 0;
    esp_gatt_status_t status = esp_ble_gattc_get_attr_count(
        gattc_if,
        conn_id,
        ESP_GATT_DB_DESCRIPTOR,
        service_start_handle,
        service_end_handle,
        characteristic_handle,
        &count);
    if (status != ESP_GATT_OK || count == 0U) {
        return ESP_ERR_NOT_FOUND;
    }

    esp_gattc_descr_elem_t *descriptors =
        calloc(count, sizeof(esp_gattc_descr_elem_t));
    if (descriptors == NULL) {
        return ESP_ERR_NO_MEM;
    }
    status = esp_ble_gattc_get_all_descr(gattc_if,
                                         conn_id,
                                         characteristic_handle,
                                         descriptors,
                                         &count,
                                         0);
    uint16_t cccd_handle = INVALID_HANDLE;
    if (status == ESP_GATT_OK) {
        for (uint16_t index = 0; index < count; ++index) {
            if (descriptors[index].uuid.len == ESP_UUID_LEN_16 &&
                descriptors[index].uuid.uuid.uuid16 ==
                    ESP_GATT_UUID_CHAR_CLIENT_CONFIG) {
                cccd_handle = descriptors[index].handle;
                break;
            }
        }
    }
    free(descriptors);
    if (cccd_handle == INVALID_HANDLE) {
        return ESP_ERR_NOT_FOUND;
    }

    const uint8_t enable_notification[2] = {0x01, 0x00};
    *saved_handle = cccd_handle;
    return esp_ble_gattc_write_char_descr(gattc_if,
                                          conn_id,
                                          cccd_handle,
                                          sizeof(enable_notification),
                                          (uint8_t *)enable_notification,
                                          ESP_GATT_WRITE_TYPE_RSP,
                                          ESP_GATT_AUTH_REQ_NO_MITM);
}

static void begin_data_source_subscription(void)
{
    taskENTER_CRITICAL(&s_shared_state_lock);
    const esp_gatt_if_t gattc_if = s_client.gattc_if;
    const uint16_t data_source_handle = s_client.data_source_handle;
    esp_bd_addr_t remote_bda;
    memcpy(remote_bda, s_client.remote_bda, sizeof(remote_bda));
    taskEXIT_CRITICAL(&s_shared_state_lock);

    transition(ANCS_SIGNAL_DATA_SUBSCRIBE_STARTED);
    const esp_err_t error = esp_ble_gattc_register_for_notify(
        gattc_if, remote_bda, data_source_handle);
    if (error != ESP_OK) {
        ESP_LOGE(TAG, "Data Source register failed: %s", esp_err_to_name(error));
        set_state(ANCS_STATE_RECOVERING);
        schedule_discovery_retry();
    }
}

static void begin_notification_source_subscription(void)
{
    taskENTER_CRITICAL(&s_shared_state_lock);
    const esp_gatt_if_t gattc_if = s_client.gattc_if;
    const uint16_t notification_source_handle =
        s_client.notification_source_handle;
    esp_bd_addr_t remote_bda;
    memcpy(remote_bda, s_client.remote_bda, sizeof(remote_bda));
    taskEXIT_CRITICAL(&s_shared_state_lock);

    const esp_err_t error = esp_ble_gattc_register_for_notify(
        gattc_if,
        remote_bda,
        notification_source_handle);
    if (error != ESP_OK) {
        ESP_LOGE(TAG,
                 "Notification Source register failed: %s",
                 esp_err_to_name(error));
        set_state(ANCS_STATE_RECOVERING);
        schedule_discovery_retry();
    }
}

static void discover_characteristics(void)
{
    taskENTER_CRITICAL(&s_shared_state_lock);
    const bool discovery_valid =
        s_client.connected && s_client.service_found &&
        s_client.gattc_if != ESP_GATT_IF_NONE;
    const uint32_t generation = s_client.generation;
    const esp_gatt_if_t gattc_if = s_client.gattc_if;
    const uint16_t conn_id = s_client.conn_id;
    const uint16_t service_start_handle = s_client.service_start_handle;
    const uint16_t service_end_handle = s_client.service_end_handle;
    taskEXIT_CRITICAL(&s_shared_state_lock);
    if (!discovery_valid) {
        return;
    }

    uint16_t count = 0;
    esp_gatt_status_t status = esp_ble_gattc_get_attr_count(
        gattc_if,
        conn_id,
        ESP_GATT_DB_CHARACTERISTIC,
        service_start_handle,
        service_end_handle,
        INVALID_HANDLE,
        &count);
    if (status != ESP_GATT_OK || count == 0U) {
        set_state(ANCS_STATE_RECOVERING);
        schedule_discovery_retry();
        return;
    }

    esp_gattc_char_elem_t *characteristics =
        calloc(count, sizeof(esp_gattc_char_elem_t));
    if (characteristics == NULL) {
        set_state(ANCS_STATE_RECOVERING);
        schedule_discovery_retry();
        return;
    }
    status = esp_ble_gattc_get_all_char(gattc_if,
                                        conn_id,
                                        service_start_handle,
                                        service_end_handle,
                                        characteristics,
                                        &count,
                                        0);
    uint16_t notification_source_handle = INVALID_HANDLE;
    uint16_t data_source_handle = INVALID_HANDLE;
    uint16_t control_point_handle = INVALID_HANDLE;
    if (status == ESP_GATT_OK) {
        for (uint16_t index = 0; index < count; ++index) {
            const esp_gattc_char_elem_t *characteristic = &characteristics[index];
            if (uuid_equal(&characteristic->uuid, NOTIFICATION_SOURCE_UUID) &&
                (characteristic->properties & ESP_GATT_CHAR_PROP_BIT_NOTIFY) != 0U) {
                notification_source_handle = characteristic->char_handle;
            } else if (uuid_equal(&characteristic->uuid, DATA_SOURCE_UUID) &&
                       (characteristic->properties &
                        ESP_GATT_CHAR_PROP_BIT_NOTIFY) != 0U) {
                data_source_handle = characteristic->char_handle;
            } else if (uuid_equal(&characteristic->uuid, CONTROL_POINT_UUID) &&
                       (characteristic->properties &
                        ESP_GATT_CHAR_PROP_BIT_WRITE) != 0U) {
                control_point_handle = characteristic->char_handle;
            }
        }
    }
    free(characteristics);

    if (notification_source_handle == INVALID_HANDLE ||
        data_source_handle == INVALID_HANDLE ||
        control_point_handle == INVALID_HANDLE) {
        ESP_LOGW(TAG, "ANCS service is missing required characteristics");
        invalidate_ancs_handles();
        set_state(ANCS_STATE_RECOVERING);
        schedule_discovery_retry();
        return;
    }
    taskENTER_CRITICAL(&s_shared_state_lock);
    const bool still_valid =
        s_client.connected && s_client.generation == generation &&
        s_client.service_start_handle == service_start_handle &&
        s_client.service_end_handle == service_end_handle;
    if (still_valid) {
        s_client.notification_source_handle = notification_source_handle;
        s_client.data_source_handle = data_source_handle;
        s_client.control_point_handle = control_point_handle;
        s_client.discovery_attempt = 0U;
    }
    taskEXIT_CRITICAL(&s_shared_state_lock);
    if (!still_valid) {
        return;
    }
    begin_data_source_subscription();
}

static void reset_connection_session(void)
{
    taskENTER_CRITICAL(&s_shared_state_lock);
    s_client.connected = false;
    s_client.bonded = false;
    s_client.mtu_ready = false;
    const uint32_t generation = ++s_client.generation;
    invalidate_ancs_handles_locked();
    taskEXIT_CRITICAL(&s_shared_state_lock);
    work_item_t reset = {
        .type = WORK_SESSION_RESET,
        .generation = generation,
    };
    (void)enqueue_work(&reset);
}

static void handle_service_changed(void)
{
    ESP_LOGW(TAG, "GATT Service Changed received; invalidating ANCS handles");
    taskENTER_CRITICAL(&s_shared_state_lock);
    const uint32_t generation = ++s_client.generation;
    invalidate_ancs_handles_locked();
    taskEXIT_CRITICAL(&s_shared_state_lock);
    work_item_t reset = {
        .type = WORK_SESSION_RESET,
        .generation = generation,
    };
    (void)enqueue_work(&reset);
    transition(ANCS_SIGNAL_SERVICE_CHANGED);
    start_discovery();
}

static void gap_event_handler(esp_gap_ble_cb_event_t event,
                              esp_ble_gap_cb_param_t *parameter)
{
    switch (event) {
    case ESP_GAP_BLE_SET_LOCAL_PRIVACY_COMPLETE_EVT:
        if (parameter->local_privacy_cmpl.status != ESP_BT_STATUS_SUCCESS) {
            ESP_LOGE(TAG,
                     "local privacy configuration failed status=0x%x",
                     parameter->local_privacy_cmpl.status);
            s_adv_params.own_addr_type = BLE_ADDR_TYPE_PUBLIC;
        }
        taskENTER_CRITICAL(&s_shared_state_lock);
        s_client.adv_config_pending = ADV_DATA_PENDING | SCAN_RESPONSE_PENDING;
        taskEXIT_CRITICAL(&s_shared_state_lock);
        if (esp_ble_gap_config_adv_data(&s_adv_data) != ESP_OK) {
            taskENTER_CRITICAL(&s_shared_state_lock);
            s_client.adv_config_pending &= (uint8_t)~ADV_DATA_PENDING;
            taskEXIT_CRITICAL(&s_shared_state_lock);
        }
        if (esp_ble_gap_config_adv_data(&s_scan_response) != ESP_OK) {
            taskENTER_CRITICAL(&s_shared_state_lock);
            s_client.adv_config_pending &= (uint8_t)~SCAN_RESPONSE_PENDING;
            taskEXIT_CRITICAL(&s_shared_state_lock);
        }
        start_advertising();
        break;

    case ESP_GAP_BLE_ADV_DATA_SET_COMPLETE_EVT:
        taskENTER_CRITICAL(&s_shared_state_lock);
        s_client.adv_config_pending &= (uint8_t)~ADV_DATA_PENDING;
        taskEXIT_CRITICAL(&s_shared_state_lock);
        start_advertising();
        break;

    case ESP_GAP_BLE_SCAN_RSP_DATA_SET_COMPLETE_EVT:
        taskENTER_CRITICAL(&s_shared_state_lock);
        s_client.adv_config_pending &= (uint8_t)~SCAN_RESPONSE_PENDING;
        taskEXIT_CRITICAL(&s_shared_state_lock);
        start_advertising();
        break;

    case ESP_GAP_BLE_ADV_START_COMPLETE_EVT: {
        const bool start_succeeded =
            parameter->adv_start_cmpl.status == ESP_BT_STATUS_SUCCESS;
        taskENTER_CRITICAL(&s_shared_state_lock);
        s_client.advertising_starting = false;
        const bool connected = s_client.connected;
        const bool allowed =
            ble_enroll_should_advertise(&s_enroll, now_ms());
        const bool stop_disallowed = start_succeeded && !connected && !allowed;
        if (start_succeeded && !connected && allowed) {
            s_client.advertising = true;
            s_client.advertising_attempt = 0U;
        } else {
            s_client.advertising = false;
        }
        taskEXIT_CRITICAL(&s_shared_state_lock);

        if (start_succeeded) {
            if (connected || stop_disallowed) {
                (void)esp_ble_gap_stop_advertising();
            } else if (current_state() == ANCS_STATE_BOOT) {
                transition(ANCS_SIGNAL_BOOT_COMPLETE);
            } else {
                set_state(ANCS_STATE_ADVERTISING);
            }
        } else {
            ESP_LOGE(TAG,
                     "advertising failed status=0x%x",
                     parameter->adv_start_cmpl.status);
            schedule_advertising_retry();
        }
        break;
    }

    case ESP_GAP_BLE_SEC_REQ_EVT:
    {
        const int64_t now = now_ms();
        taskENTER_CRITICAL(&s_shared_state_lock);
        const bool active_enroll = ble_enroll_window_active(&s_enroll, now);
        taskEXIT_CRITICAL(&s_shared_state_lock);
        const bool allowed =
            active_enroll ||
            bond_list_contains_peer(parameter->ble_security.ble_req.bd_addr);
        (void)esp_ble_gap_security_rsp(
            parameter->ble_security.ble_req.bd_addr, allowed);
        if (!allowed) {
            ESP_LOGW(TAG, "rejected security request from unknown peer");
            (void)esp_ble_gap_disconnect(parameter->ble_security.ble_req.bd_addr);
        }
        break;
    }

    case ESP_GAP_BLE_AUTH_CMPL_EVT:
        if (!authentication_event_matches(
                parameter->ble_security.auth_cmpl.bd_addr)) {
            ESP_LOGW(TAG, "ignored authentication event from stale peer");
            break;
        }
        if (parameter->ble_security.auth_cmpl.success) {
            taskENTER_CRITICAL(&s_shared_state_lock);
            s_client.bonded = true;
            s_client.auth_error = 0;
            ble_enroll_note_bonded(
                &s_enroll, parameter->ble_security.auth_cmpl.bd_addr);
            taskEXIT_CRITICAL(&s_shared_state_lock);
            (void)esp_timer_stop(s_client.enroll_timer);
            stop_advertising();
            transition(ANCS_SIGNAL_BONDED);
            ESP_LOGI(TAG,
                     "encryption and bonding complete auth_mode=0x%x addr_type=%u",
                     parameter->ble_security.auth_cmpl.auth_mode,
                     parameter->ble_security.auth_cmpl.addr_type);
            maybe_start_discovery();
        } else {
            taskENTER_CRITICAL(&s_shared_state_lock);
            s_client.auth_error =
                parameter->ble_security.auth_cmpl.fail_reason;
            const int auth_error = s_client.auth_error;
            taskEXIT_CRITICAL(&s_shared_state_lock);
            ESP_LOGE(TAG,
                     "authentication failed reason=0x%x",
                     auth_error);
            reset_connection_session();
            set_state(ANCS_STATE_RECOVERING);
            publish_state();
            (void)esp_ble_gap_disconnect(
                parameter->ble_security.auth_cmpl.bd_addr);
            schedule_advertising_retry();
        }
        break;

    case ESP_GAP_BLE_REMOVE_BOND_DEV_COMPLETE_EVT: {
        if (parameter->remove_bond_dev_cmpl.status != ESP_BT_STATUS_SUCCESS) {
            taskENTER_CRITICAL(&s_shared_state_lock);
            s_client.replace_pending = false;
            s_client.last_replace_error = ESP_FAIL;
            taskEXIT_CRITICAL(&s_shared_state_lock);
            const int remaining = sync_existing_ble_bond();
            ESP_LOGE(TAG,
                     "BLE bond removal failed status=0x%x",
                     parameter->remove_bond_dev_cmpl.status);
            if (remaining > 0) {
                start_advertising();
            }
            break;
        }
        const int remaining = sync_existing_ble_bond();
        bool should_open = false;
        taskENTER_CRITICAL(&s_shared_state_lock);
        if (remaining == 0) {
            should_open = s_client.replace_pending;
            s_client.replace_pending = false;
            s_client.last_replace_error = ESP_OK;
        }
        taskEXIT_CRITICAL(&s_shared_state_lock);
        if (should_open) {
            const esp_err_t enroll_error = ancs_client_request_enroll();
            if (enroll_error != ESP_OK) {
                taskENTER_CRITICAL(&s_shared_state_lock);
                s_client.last_replace_error = enroll_error;
                taskEXIT_CRITICAL(&s_shared_state_lock);
            }
        }
        break;
    }

    case ESP_GAP_BLE_UPDATE_CONN_PARAMS_EVT:
        ESP_LOGI(TAG,
                 "connection parameters status=0x%x requested=%u-%u "
                 "interval_units=%u interval_us=%" PRIu32
                 " latency=%u timeout_ms=%" PRIu32,
                 parameter->update_conn_params.status,
                 parameter->update_conn_params.min_int,
                 parameter->update_conn_params.max_int,
                 parameter->update_conn_params.conn_int,
                 (uint32_t)parameter->update_conn_params.conn_int * 1250U,
                 parameter->update_conn_params.latency,
                 (uint32_t)parameter->update_conn_params.timeout * 10U);
        break;

    case ESP_GAP_BLE_NC_REQ_EVT:
        ESP_LOGE(TAG,
                 "unexpected numeric comparison request passkey=%06" PRIu32,
                 parameter->ble_security.key_notif.passkey);
        (void)esp_ble_confirm_reply(
            parameter->ble_security.ble_req.bd_addr, false);
        break;

    case ESP_GAP_BLE_PASSKEY_NOTIF_EVT:
        ESP_LOGI(TAG,
                 "passkey=%06" PRIu32,
                 parameter->ble_security.key_notif.passkey);
        break;

    default:
        break;
    }
}

static void handle_gattc_event(esp_gattc_cb_event_t event,
                               esp_gatt_if_t gattc_if,
                               esp_ble_gattc_cb_param_t *parameter)
{
    switch (event) {
    case ESP_GATTC_REG_EVT:
        taskENTER_CRITICAL(&s_shared_state_lock);
        s_client.gattc_if = gattc_if;
        taskEXIT_CRITICAL(&s_shared_state_lock);
        ESP_ERROR_CHECK(esp_ble_gap_set_device_name(s_client.device_name));
        ESP_ERROR_CHECK(esp_ble_gap_config_local_privacy(true));
        break;

    case ESP_GATTC_CONNECT_EVT: {
        if (!connection_peer_allowed(parameter->connect.remote_bda)) {
            ESP_LOGW(TAG, "rejected connection from unauthorized peer");
            (void)esp_ble_gap_disconnect(parameter->connect.remote_bda);
            break;
        }
        taskENTER_CRITICAL(&s_shared_state_lock);
        memcpy(s_client.remote_bda,
               parameter->connect.remote_bda,
               sizeof(esp_bd_addr_t));
        s_client.remote_addr_type = parameter->connect.ble_addr_type;
        s_client.conn_id = parameter->connect.conn_id;
        s_client.connected = true;
        s_client.advertising = false;
        s_client.advertising_starting = false;
        taskEXIT_CRITICAL(&s_shared_state_lock);
        transition(ANCS_SIGNAL_CONNECTED);

        esp_ble_gatt_creat_conn_params_t connection = {0};
        memcpy(connection.remote_bda,
               parameter->connect.remote_bda,
               sizeof(esp_bd_addr_t));
        connection.remote_addr_type = parameter->connect.ble_addr_type;
        connection.own_addr_type = s_adv_params.own_addr_type;
        connection.is_direct = true;
        connection.is_aux = false;
        connection.phy_mask = 0;
        const esp_err_t error =
            esp_ble_gattc_enh_open(gattc_if, &connection);
        if (error != ESP_OK) {
            ESP_LOGE(TAG, "GATT virtual connection failed: %s", esp_err_to_name(error));
            (void)esp_ble_gap_disconnect(parameter->connect.remote_bda);
        }
        break;
    }

    case ESP_GATTC_OPEN_EVT:
        if (!connection_event_matches(
                parameter->open.conn_id,
                parameter->open.remote_bda)) {
            ESP_LOGW(TAG, "ignored GATT open event from stale peer");
            (void)esp_ble_gap_disconnect(parameter->open.remote_bda);
            break;
        }
        if (parameter->open.status != ESP_GATT_OK) {
            ESP_LOGE(TAG, "GATT open failed status=0x%x", parameter->open.status);
            (void)esp_ble_gap_disconnect(parameter->open.remote_bda);
            break;
        }
        taskENTER_CRITICAL(&s_shared_state_lock);
        s_client.conn_id = parameter->open.conn_id;
        memcpy(s_client.remote_bda,
               parameter->open.remote_bda,
               sizeof(esp_bd_addr_t));
        taskEXIT_CRITICAL(&s_shared_state_lock);
        transition(ANCS_SIGNAL_ENCRYPTION_STARTED);
        if (esp_ble_set_encryption(
                parameter->open.remote_bda, ESP_BLE_SEC_ENCRYPT_MITM) !=
            ESP_OK) {
            ESP_LOGE(TAG, "failed to start link encryption");
            (void)esp_ble_gap_disconnect(parameter->open.remote_bda);
        }
        if (esp_ble_gattc_send_mtu_req(gattc_if, parameter->open.conn_id) !=
            ESP_OK) {
            ESP_LOGE(TAG, "failed to request MTU");
        }
        break;

    case ESP_GATTC_CFG_MTU_EVT:
        taskENTER_CRITICAL(&s_shared_state_lock);
        s_client.mtu_ready = true;
        taskEXIT_CRITICAL(&s_shared_state_lock);
        if (parameter->cfg_mtu.status == ESP_GATT_OK) {
            ESP_LOGI(TAG, "negotiated MTU=%u", parameter->cfg_mtu.mtu);
            maybe_start_discovery();
        } else {
            ESP_LOGE(TAG,
                     "MTU exchange failed status=0x%x",
                     parameter->cfg_mtu.status);
            maybe_start_discovery();
        }
        break;

    case ESP_GATTC_SEARCH_RES_EVT:
        if (uuid_equal(&parameter->search_res.srvc_id.uuid,
                       ANCS_SERVICE_UUID)) {
            taskENTER_CRITICAL(&s_shared_state_lock);
            s_client.service_found = true;
            s_client.service_start_handle = parameter->search_res.start_handle;
            s_client.service_end_handle = parameter->search_res.end_handle;
            taskEXIT_CRITICAL(&s_shared_state_lock);
        }
        break;

    case ESP_GATTC_SEARCH_CMPL_EVT: {
        taskENTER_CRITICAL(&s_shared_state_lock);
        s_client.discovery_in_progress = false;
        const bool service_found = s_client.service_found;
        taskEXIT_CRITICAL(&s_shared_state_lock);
        if (parameter->search_cmpl.status != ESP_GATT_OK ||
            !service_found) {
            ESP_LOGW(TAG,
                     "ANCS service not available status=0x%x",
                     parameter->search_cmpl.status);
            set_state(ANCS_STATE_RECOVERING);
            schedule_discovery_retry();
            break;
        }
        discover_characteristics();
        break;
    }

    case ESP_GATTC_REG_FOR_NOTIFY_EVT: {
        if (parameter->reg_for_notify.status != ESP_GATT_OK) {
            ESP_LOGE(TAG,
                     "register for notify failed status=0x%x",
                     parameter->reg_for_notify.status);
            set_state(ANCS_STATE_RECOVERING);
            schedule_discovery_retry();
            break;
        }
        taskENTER_CRITICAL(&s_shared_state_lock);
        const uint16_t data_source_handle = s_client.data_source_handle;
        const uint16_t notification_source_handle =
            s_client.notification_source_handle;
        taskEXIT_CRITICAL(&s_shared_state_lock);
        if (parameter->reg_for_notify.handle == data_source_handle) {
            uint16_t cccd_handle = INVALID_HANDLE;
            const esp_err_t error =
                write_cccd(data_source_handle, &cccd_handle);
            if (error != ESP_OK) {
                ESP_LOGE(TAG,
                         "Data Source CCCD write start failed: %s",
                         esp_err_to_name(error));
                set_state(ANCS_STATE_RECOVERING);
                schedule_discovery_retry();
            } else {
                taskENTER_CRITICAL(&s_shared_state_lock);
                if (s_client.data_source_handle == data_source_handle) {
                    s_client.data_source_cccd_handle = cccd_handle;
                }
                taskEXIT_CRITICAL(&s_shared_state_lock);
            }
        } else if (parameter->reg_for_notify.handle ==
                   notification_source_handle) {
            uint16_t cccd_handle = INVALID_HANDLE;
            const esp_err_t error =
                write_cccd(notification_source_handle, &cccd_handle);
            if (error != ESP_OK) {
                ESP_LOGE(TAG,
                         "Notification Source CCCD write start failed: %s",
                         esp_err_to_name(error));
                set_state(ANCS_STATE_RECOVERING);
                schedule_discovery_retry();
            } else {
                taskENTER_CRITICAL(&s_shared_state_lock);
                if (s_client.notification_source_handle ==
                    notification_source_handle) {
                    s_client.notification_source_cccd_handle = cccd_handle;
                }
                taskEXIT_CRITICAL(&s_shared_state_lock);
            }
        }
        break;
    }

    case ESP_GATTC_WRITE_DESCR_EVT: {
        if (parameter->write.status != ESP_GATT_OK) {
            ESP_LOGE(TAG,
                     "CCCD write failed handle=0x%04x status=0x%x",
                     parameter->write.handle,
                     parameter->write.status);
            set_state(ANCS_STATE_RECOVERING);
            schedule_discovery_retry();
            break;
        }
        taskENTER_CRITICAL(&s_shared_state_lock);
        const uint16_t data_source_cccd_handle =
            s_client.data_source_cccd_handle;
        const uint16_t notification_source_cccd_handle =
            s_client.notification_source_cccd_handle;
        taskEXIT_CRITICAL(&s_shared_state_lock);
        if (parameter->write.handle == data_source_cccd_handle) {
            taskENTER_CRITICAL(&s_shared_state_lock);
            s_client.data_source_subscribed = true;
            taskEXIT_CRITICAL(&s_shared_state_lock);
            transition(ANCS_SIGNAL_DATA_SUBSCRIBED);
            begin_notification_source_subscription();
        } else if (parameter->write.handle ==
                   notification_source_cccd_handle) {
            taskENTER_CRITICAL(&s_shared_state_lock);
            s_client.notification_source_subscribed = true;
            const bool ready = s_client.data_source_subscribed;
            ++s_client.session_id;
            s_client.ready = ready;
            taskEXIT_CRITICAL(&s_shared_state_lock);
            transition(ANCS_SIGNAL_NOTIFICATION_SUBSCRIBED);
            if (!ready) {
                ESP_LOGE(TAG, "Notification Source enabled before Data Source");
                set_state(ANCS_STATE_RECOVERING);
            }
        }
        break;
    }

    case ESP_GATTC_NOTIFY_EVT: {
        taskENTER_CRITICAL(&s_shared_state_lock);
        const uint16_t notification_source_handle =
            s_client.notification_source_handle;
        const uint16_t data_source_handle = s_client.data_source_handle;
        taskEXIT_CRITICAL(&s_shared_state_lock);
        if (parameter->notify.handle == notification_source_handle) {
            ancs_notification_event_t notification_event;
            const ancs_protocol_error_t error =
                ancs_parse_notification_source(parameter->notify.value,
                                               parameter->notify.value_len,
                                               &notification_event);
            if (error != ANCS_PROTOCOL_OK) {
                ESP_LOGW(TAG,
                         "invalid Notification Source frame length=%u error=%d",
                         parameter->notify.value_len,
                         error);
                break;
            }
            work_item_t item = {
                .type = WORK_NOTIFICATION_EVENT,
                .generation = current_generation(),
                .data.event = notification_event,
            };
            if (!enqueue_work(&item)) {
                ESP_LOGE(TAG,
                         "work queue full for uid=%" PRIu32,
                         notification_event.uid);
            }
        } else if (parameter->notify.handle == data_source_handle) {
            if (parameter->notify.value_len > CONFIG_ANCS_MAX_FRAGMENT_SIZE) {
                ESP_LOGE(TAG,
                         "Data Source fragment too large length=%u",
                         parameter->notify.value_len);
                break;
            }
            data_fragment_t *fragment =
                malloc(sizeof(*fragment) + parameter->notify.value_len);
            if (fragment == NULL) {
                ESP_LOGE(TAG, "no memory for Data Source fragment");
                break;
            }
            fragment->length = parameter->notify.value_len;
            memcpy(fragment->bytes,
                   parameter->notify.value,
                   parameter->notify.value_len);
            work_item_t item = {
                .type = WORK_DATA_FRAGMENT,
                .generation = current_generation(),
                .data.fragment = fragment,
            };
            if (!enqueue_work(&item)) {
                free(fragment);
                ESP_LOGE(TAG, "work queue full for Data Source fragment");
            }
        }
        break;
    }

    case ESP_GATTC_WRITE_CHAR_EVT: {
        taskENTER_CRITICAL(&s_shared_state_lock);
        const uint16_t control_point_handle = s_client.control_point_handle;
        taskEXIT_CRITICAL(&s_shared_state_lock);
        if (parameter->write.handle != control_point_handle) {
            break;
        }
        work_item_t item = {
            .type = WORK_CONTROL_WRITE_RESULT,
            .generation = current_generation(),
            .data.write_status = parameter->write.status,
        };
        if (!enqueue_work(&item)) {
            ESP_LOGE(TAG, "work queue full for Control Point result");
        }
        break;
    }

    case ESP_GATTC_SRVC_CHG_EVT: {
        taskENTER_CRITICAL(&s_shared_state_lock);
        esp_bd_addr_t remote_bda;
        memcpy(remote_bda, s_client.remote_bda, sizeof(remote_bda));
        taskEXIT_CRITICAL(&s_shared_state_lock);
        if (memcmp(parameter->srvc_chg.remote_bda,
                   remote_bda,
                   sizeof(esp_bd_addr_t)) == 0) {
            handle_service_changed();
        }
        break;
    }

    case ESP_GATTC_DISCONNECT_EVT:
        if (!connection_event_matches(
                parameter->disconnect.conn_id,
                parameter->disconnect.remote_bda)) {
            ESP_LOGW(TAG, "ignored disconnect event from stale peer");
            break;
        }
        ESP_LOGW(TAG,
                 "disconnected reason=0x%x",
                 parameter->disconnect.reason);
        reset_connection_session();
        transition(ANCS_SIGNAL_DISCONNECTED);
        schedule_advertising_retry();
        break;

    default:
        break;
    }
}

static void gattc_callback(esp_gattc_cb_event_t event,
                           esp_gatt_if_t gattc_if,
                           esp_ble_gattc_cb_param_t *parameter)
{
    if (event == ESP_GATTC_REG_EVT) {
        if (parameter->reg.status != ESP_GATT_OK ||
            parameter->reg.app_id != ANCS_APP_ID) {
            ESP_LOGE(TAG,
                     "GATT client registration failed status=0x%x",
                     parameter->reg.status);
            return;
        }
        taskENTER_CRITICAL(&s_shared_state_lock);
        s_client.gattc_if = gattc_if;
        taskEXIT_CRITICAL(&s_shared_state_lock);
    }
    taskENTER_CRITICAL(&s_shared_state_lock);
    const esp_gatt_if_t registered_gattc_if = s_client.gattc_if;
    taskEXIT_CRITICAL(&s_shared_state_lock);
    if (gattc_if == ESP_GATT_IF_NONE || gattc_if == registered_gattc_if) {
        handle_gattc_event(event, gattc_if, parameter);
    }
}

static int sync_existing_ble_bond(void)
{
    const int bond_count = current_bond_count();
    if (bond_count <= 0) {
        taskENTER_CRITICAL(&s_shared_state_lock);
        ble_enroll_clear_bond(&s_enroll);
        s_client.bonded = false;
        taskEXIT_CRITICAL(&s_shared_state_lock);
        return 0;
    }
    esp_ble_bond_dev_t *bond_list =
        calloc((size_t)bond_count, sizeof(*bond_list));
    if (bond_list == NULL) {
        ESP_LOGE(TAG, "no memory to load BLE bond list");
        return bond_count;
    }
    int list_count = bond_count;
    const esp_err_t error =
        esp_ble_get_bond_device_list(&list_count, bond_list);
    if (error == ESP_OK && list_count > 0) {
        taskENTER_CRITICAL(&s_shared_state_lock);
        ble_enroll_note_bonded(&s_enroll, bond_list[0].bd_addr);
        s_client.bonded = true;
        taskEXIT_CRITICAL(&s_shared_state_lock);
        ESP_LOGI(TAG, "loaded existing BLE bond count=%d", list_count);
    } else if (error == ESP_OK) {
        taskENTER_CRITICAL(&s_shared_state_lock);
        ble_enroll_clear_bond(&s_enroll);
        s_client.bonded = false;
        taskEXIT_CRITICAL(&s_shared_state_lock);
    } else {
        ESP_LOGE(TAG, "failed to read BLE bond list: %s", esp_err_to_name(error));
        list_count = bond_count;
    }
    free(bond_list);
    return list_count;
}

static void load_existing_ble_bond(void)
{
    (void)sync_existing_ble_bond();
}

static esp_err_t remove_all_ble_bonds(void)
{
    const int bond_count = esp_ble_get_bond_device_num();
    if (bond_count <= 0) {
        taskENTER_CRITICAL(&s_shared_state_lock);
        ble_enroll_clear_bond(&s_enroll);
        s_client.bonded = false;
        taskEXIT_CRITICAL(&s_shared_state_lock);
        return ESP_OK;
    }

    esp_ble_bond_dev_t *bond_list =
        calloc((size_t)bond_count, sizeof(*bond_list));
    if (bond_list == NULL) {
        return ESP_ERR_NO_MEM;
    }
    int list_count = bond_count;
    esp_err_t error = esp_ble_get_bond_device_list(&list_count, bond_list);
    if (error == ESP_OK) {
        for (int index = 0; index < list_count; ++index) {
            const esp_err_t remove_error =
                esp_ble_remove_bond_device(bond_list[index].bd_addr);
            if (remove_error != ESP_OK && error == ESP_OK) {
                error = remove_error;
            }
        }
    }
    free(bond_list);
    return error;
}

static esp_err_t init_enroll_button(void)
{
    gpio_config_t config = {
        .pin_bit_mask = 1ULL << CONFIG_ANCS_ENROLL_BOOT_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    return gpio_config(&config);
}

static esp_err_t configure_security(void)
{
    esp_ble_auth_req_t auth_request = ESP_LE_AUTH_REQ_SC_MITM_BOND;
    esp_ble_io_cap_t io_capability = ESP_IO_CAP_OUT;
    uint8_t key_size = 16;
    uint8_t initial_keys = ESP_BLE_ENC_KEY_MASK | ESP_BLE_ID_KEY_MASK;
    uint8_t response_keys = ESP_BLE_ENC_KEY_MASK | ESP_BLE_ID_KEY_MASK;
    uint8_t auth_option = ESP_BLE_ONLY_ACCEPT_SPECIFIED_AUTH_ENABLE;
    uint8_t oob_support = ESP_BLE_OOB_DISABLE;
    uint32_t static_passkey = 123456U;

    esp_err_t error = esp_ble_gap_set_security_param(
        ESP_BLE_SM_SET_STATIC_PASSKEY,
        &static_passkey,
        sizeof(static_passkey));
    if (error == ESP_OK) {
        error = esp_ble_gap_set_security_param(
            ESP_BLE_SM_AUTHEN_REQ_MODE, &auth_request, sizeof(auth_request));
    }
    if (error == ESP_OK) {
        error = esp_ble_gap_set_security_param(
            ESP_BLE_SM_IOCAP_MODE, &io_capability, sizeof(io_capability));
    }
    if (error == ESP_OK) {
        error = esp_ble_gap_set_security_param(
            ESP_BLE_SM_MAX_KEY_SIZE, &key_size, sizeof(key_size));
    }
    if (error == ESP_OK) {
        error = esp_ble_gap_set_security_param(
            ESP_BLE_SM_ONLY_ACCEPT_SPECIFIED_SEC_AUTH,
            &auth_option,
            sizeof(auth_option));
    }
    if (error == ESP_OK) {
        error = esp_ble_gap_set_security_param(
            ESP_BLE_SM_OOB_SUPPORT, &oob_support, sizeof(oob_support));
    }
    if (error == ESP_OK) {
        error = esp_ble_gap_set_security_param(
            ESP_BLE_SM_SET_INIT_KEY, &initial_keys, sizeof(initial_keys));
    }
    if (error == ESP_OK) {
        error = esp_ble_gap_set_security_param(
            ESP_BLE_SM_SET_RSP_KEY, &response_keys, sizeof(response_keys));
    }
    return error;
}

typedef struct {
    bool controller_initialized;
    bool controller_enabled;
    bool bluedroid_initialized;
    bool bluedroid_enabled;
} init_progress_t;

static void cleanup_timer(esp_timer_handle_t *timer)
{
    if (timer == NULL || *timer == NULL) {
        return;
    }
    (void)esp_timer_stop(*timer);
    const esp_err_t error = esp_timer_delete(*timer);
    if (error != ESP_OK) {
        ESP_LOGE(TAG, "timer cleanup failed: %s", esp_err_to_name(error));
    }
    *timer = NULL;
}

static void cleanup_init_resources(const init_progress_t *progress)
{
    if (progress->bluedroid_enabled) {
        const esp_err_t error = esp_bluedroid_disable();
        if (error != ESP_OK) {
            ESP_LOGE(TAG,
                     "Bluedroid disable during cleanup failed: %s",
                     esp_err_to_name(error));
        }
    }
    if (progress->bluedroid_initialized) {
        const esp_err_t error = esp_bluedroid_deinit();
        if (error != ESP_OK) {
            ESP_LOGE(TAG,
                     "Bluedroid deinit during cleanup failed: %s",
                     esp_err_to_name(error));
        }
    }
    if (progress->controller_enabled) {
        const esp_err_t error = esp_bt_controller_disable();
        if (error != ESP_OK) {
            ESP_LOGE(TAG,
                     "BLE controller disable during cleanup failed: %s",
                     esp_err_to_name(error));
        }
    }
    if (progress->controller_initialized) {
        const esp_err_t error = esp_bt_controller_deinit();
        if (error != ESP_OK) {
            ESP_LOGE(TAG,
                     "BLE controller deinit during cleanup failed: %s",
                     esp_err_to_name(error));
        }
    }

    cleanup_timer(&s_client.button_timer);
    cleanup_timer(&s_client.enroll_timer);
    cleanup_timer(&s_client.discovery_retry_timer);
    cleanup_timer(&s_client.advertising_retry_timer);

    if (s_client.worker_task != NULL) {
        vTaskDelete(s_client.worker_task);
        s_client.worker_task = NULL;
    }
    if (s_client.work_queue != NULL) {
        work_item_t item;
        while (xQueueReceive(s_client.work_queue, &item, 0) == pdTRUE) {
            free_work_item(&item);
        }
        vQueueDelete(s_client.work_queue);
        s_client.work_queue = NULL;
    }

    taskENTER_CRITICAL(&s_shared_state_lock);
    s_client.connected = false;
    s_client.bonded = false;
    s_client.advertising = false;
    s_client.advertising_starting = false;
    s_client.gattc_if = ESP_GATT_IF_NONE;
    invalidate_ancs_handles_locked();
    taskEXIT_CRITICAL(&s_shared_state_lock);
}

esp_err_t ancs_client_init(void)
{
    init_progress_t progress = {0};
    publish_state();
    const ble_enroll_config_t config = enroll_config();
    ble_enroll_init(&s_enroll, config);
    ble_enroll_button_init(&s_enroll_button, config);

    esp_err_t error = nvs_flash_init();
    if (error != ESP_OK) {
        ESP_LOGE(TAG,
                 "NVS initialization failed; bond data was not erased: %s",
                 esp_err_to_name(error));
        goto init_failed;
    }

    uint8_t base_mac[6];
    error = esp_read_mac(base_mac, ESP_MAC_BASE);
    if (error != ESP_OK) {
        goto init_failed;
    }
    const int name_length = snprintf(s_client.device_name,
                                     sizeof(s_client.device_name),
                                     "IOS-ANCS-" ANCS_DEVICE_FAMILY "-%02X%02X",
                                     base_mac[4],
                                     base_mac[5]);
    if (name_length < 0 || (size_t)name_length >= sizeof(s_client.device_name)) {
        error = ESP_ERR_INVALID_SIZE;
        goto init_failed;
    }

    s_client.work_queue =
        xQueueCreate(CONFIG_ANCS_WORK_QUEUE_LENGTH, sizeof(work_item_t));
    if (s_client.work_queue == NULL) {
        error = ESP_ERR_NO_MEM;
        goto init_failed;
    }
    if (xTaskCreate(worker_task,
                    "ancs_worker",
                    CONFIG_ANCS_WORKER_STACK_SIZE,
                    NULL,
                    5,
                    &s_client.worker_task) != pdPASS) {
        error = ESP_ERR_NO_MEM;
        goto init_failed;
    }

    const esp_timer_create_args_t advertising_timer_args = {
        .callback = advertising_retry_callback,
        .name = "ancs_adv_retry",
    };
    error = esp_timer_create(
        &advertising_timer_args, &s_client.advertising_retry_timer);
    if (error != ESP_OK) {
        goto init_failed;
    }
    const esp_timer_create_args_t discovery_timer_args = {
        .callback = discovery_retry_callback,
        .name = "ancs_disc_retry",
    };
    error =
        esp_timer_create(&discovery_timer_args, &s_client.discovery_retry_timer);
    if (error != ESP_OK) {
        goto init_failed;
    }
    const esp_timer_create_args_t enroll_timer_args = {
        .callback = enroll_timeout_callback,
        .name = "ancs_enroll_timeout",
    };
    error = esp_timer_create(&enroll_timer_args, &s_client.enroll_timer);
    if (error != ESP_OK) {
        goto init_failed;
    }
    const esp_timer_create_args_t button_timer_args = {
        .callback = enroll_button_callback,
        .name = "ancs_enroll_button",
    };
    error = esp_timer_create(&button_timer_args, &s_client.button_timer);
    if (error != ESP_OK) {
        goto init_failed;
    }
    error = init_enroll_button();
    if (error != ESP_OK) {
        goto init_failed;
    }

    error = esp_bt_controller_mem_release(ESP_BT_MODE_CLASSIC_BT);
    if (error != ESP_OK) {
        goto init_failed;
    }
    esp_bt_controller_config_t controller_config =
        BT_CONTROLLER_INIT_CONFIG_DEFAULT();
    error = esp_bt_controller_init(&controller_config);
    if (error != ESP_OK) {
        goto init_failed;
    }
    progress.controller_initialized = true;
    error = esp_bt_controller_enable(ESP_BT_MODE_BLE);
    if (error != ESP_OK) {
        goto init_failed;
    }
    progress.controller_enabled = true;

    esp_bluedroid_config_t bluedroid_config =
        BT_BLUEDROID_INIT_CONFIG_DEFAULT();
    error = esp_bluedroid_init_with_cfg(&bluedroid_config);
    if (error != ESP_OK) {
        goto init_failed;
    }
    progress.bluedroid_initialized = true;
    error = esp_bluedroid_enable();
    if (error != ESP_OK) {
        goto init_failed;
    }
    progress.bluedroid_enabled = true;
    load_existing_ble_bond();
    error = hid_server_init();
    if (error != ESP_OK) {
        goto init_failed;
    }
    error = esp_ble_gattc_register_callback(gattc_callback);
    if (error != ESP_OK) {
        goto init_failed;
    }
    error = esp_ble_gap_register_callback(gap_event_handler);
    if (error != ESP_OK) {
        goto init_failed;
    }
    error = esp_ble_gatt_set_local_mtu(500);
    if (error != ESP_OK) {
        goto init_failed;
    }
    error = configure_security();
    if (error != ESP_OK) {
        goto init_failed;
    }
    error = esp_ble_gattc_app_register(ANCS_APP_ID);
    if (error != ESP_OK) {
        goto init_failed;
    }
    error = esp_timer_start_periodic(
        s_client.button_timer,
        (uint64_t)CONFIG_ANCS_ENROLL_BUTTON_DEBOUNCE_MS * 1000U);
    if (error != ESP_OK) {
        goto init_failed;
    }

    ESP_LOGI(TAG,
             "initialized device=%s static_notification_bytes=%u cache_entries=%u",
             s_client.device_name,
             (unsigned int)sizeof(ancs_notification_t),
             (unsigned int)CONFIG_ANCS_CACHE_CAPACITY);
    return ESP_OK;

init_failed:
    cleanup_init_resources(&progress);
    set_state(ANCS_STATE_RECOVERING);
    publish_state();
    return error;
}

esp_err_t ancs_client_register_boot_held_callback(
    ancs_client_boot_held_callback_t callback,
    void *context)
{
    taskENTER_CRITICAL(&s_shared_state_lock);
    s_client.boot_held_callback = callback;
    s_client.boot_held_callback_context = callback == NULL ? NULL : context;
    taskEXIT_CRITICAL(&s_shared_state_lock);
    return ESP_OK;
}

esp_err_t ancs_client_request_enroll(void)
{
    if (current_bond_count() > 0 || ancs_client_has_bond()) {
        (void)esp_timer_stop(s_client.enroll_timer);
        taskENTER_CRITICAL(&s_shared_state_lock);
        ble_enroll_close_window(&s_enroll);
        taskEXIT_CRITICAL(&s_shared_state_lock);
        load_existing_ble_bond();
        start_advertising();
        return ESP_OK;
    }

    const int64_t now = now_ms();
    taskENTER_CRITICAL(&s_shared_state_lock);
    const esp_err_t error = ble_enroll_open_window(&s_enroll, now);
    taskEXIT_CRITICAL(&s_shared_state_lock);
    if (error != ESP_OK) {
        return error;
    }
    (void)esp_timer_stop(s_client.enroll_timer);
    const esp_err_t timer_error = esp_timer_start_once(
        s_client.enroll_timer,
        (uint64_t)CONFIG_ANCS_ENROLL_WINDOW_MS * 1000U);
    if (timer_error != ESP_OK) {
        taskENTER_CRITICAL(&s_shared_state_lock);
        ble_enroll_close_window(&s_enroll);
        taskEXIT_CRITICAL(&s_shared_state_lock);
        return timer_error;
    }
    start_advertising();
    return ESP_OK;
}

esp_err_t ancs_client_replace_enrollment(bool confirmed)
{
    if (!confirmed) {
        taskENTER_CRITICAL(&s_shared_state_lock);
        s_client.last_replace_error = ESP_ERR_INVALID_STATE;
        taskEXIT_CRITICAL(&s_shared_state_lock);
        return ESP_ERR_INVALID_STATE;
    }
    const int bond_count = esp_ble_get_bond_device_num();
    esp_bd_addr_t connected_peer = {0};
    bool connected = false;
    taskENTER_CRITICAL(&s_shared_state_lock);
    s_client.last_replace_error = ESP_OK;
    taskEXIT_CRITICAL(&s_shared_state_lock);
    if (bond_count > 0) {
        taskENTER_CRITICAL(&s_shared_state_lock);
        s_client.replace_pending = true;
        connected = s_client.connected;
        memcpy(connected_peer, s_client.remote_bda, sizeof(connected_peer));
        taskEXIT_CRITICAL(&s_shared_state_lock);
        if (connected) {
            (void)esp_ble_gap_disconnect(connected_peer);
        }
    }
    stop_advertising();
    const esp_err_t error = remove_all_ble_bonds();
    if (error != ESP_OK) {
        taskENTER_CRITICAL(&s_shared_state_lock);
        s_client.replace_pending = false;
        s_client.last_replace_error = error;
        taskEXIT_CRITICAL(&s_shared_state_lock);
        const int remaining = sync_existing_ble_bond();
        if (remaining > 0) {
            start_advertising();
        }
        return error;
    }
    if (esp_ble_get_bond_device_num() <= 0) {
        taskENTER_CRITICAL(&s_shared_state_lock);
        s_client.replace_pending = false;
        taskEXIT_CRITICAL(&s_shared_state_lock);
        const esp_err_t enroll_error = ancs_client_request_enroll();
        taskENTER_CRITICAL(&s_shared_state_lock);
        s_client.last_replace_error = enroll_error;
        taskEXIT_CRITICAL(&s_shared_state_lock);
        return enroll_error;
    }
    return ESP_OK;
}

ancs_client_enrollment_status_t ancs_client_get_enrollment_status(void)
{
    const int64_t now = now_ms();
    const int bond_count = current_bond_count();
    taskENTER_CRITICAL(&s_shared_state_lock);
    const ancs_client_enrollment_status_t status = {
        .enroll_active = ble_enroll_window_active(&s_enroll, now),
        .replace_pending = s_client.replace_pending,
        .has_bond = bond_count > 0 || ble_enroll_has_bond(&s_enroll),
        .connected = s_client.connected,
        .bond_count = bond_count,
        .last_replace_error = s_client.last_replace_error,
    };
    taskEXIT_CRITICAL(&s_shared_state_lock);
    return status;
}

esp_err_t ancs_client_start_advertising(void)
{
    if (!enroll_should_advertise_now()) {
        return ESP_ERR_INVALID_STATE;
    }
    start_advertising();
    return ESP_OK;
}

esp_err_t ancs_client_stop_advertising(void)
{
    stop_advertising();
    return ESP_OK;
}

void ancs_client_set_pairing_allowed(bool allowed)
{
    if (allowed) {
        (void)ancs_client_request_enroll();
        return;
    }
    (void)esp_timer_stop(s_client.enroll_timer);
    taskENTER_CRITICAL(&s_shared_state_lock);
    ble_enroll_close_window(&s_enroll);
    const bool has_bond = ble_enroll_has_bond(&s_enroll);
    taskEXIT_CRITICAL(&s_shared_state_lock);
    if (!has_bond) {
        stop_advertising();
    }
}

bool ancs_client_enroll_active(void)
{
    return enroll_window_active_now();
}

bool ancs_client_replace_pending(void)
{
    return ancs_client_get_enrollment_status().replace_pending;
}

esp_err_t ancs_client_last_replace_error(void)
{
    return ancs_client_get_enrollment_status().last_replace_error;
}

int ancs_client_bond_count(void)
{
    return ancs_client_get_enrollment_status().bond_count;
}

bool ancs_client_has_bond(void)
{
    return ancs_client_get_enrollment_status().has_bond;
}

bool ancs_client_is_connected(void)
{
    taskENTER_CRITICAL(&s_shared_state_lock);
    const bool connected = s_client.connected;
    taskEXIT_CRITICAL(&s_shared_state_lock);
    return connected;
}
