#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

#define BLE_ENROLL_ADDR_LEN 6

typedef struct {
    uint32_t window_ms;
    uint32_t boot_hold_ms;
    uint32_t button_debounce_ms;
} ble_enroll_config_t;

typedef struct {
    ble_enroll_config_t config;
    bool has_bond;
    uint8_t bonded_addr[BLE_ENROLL_ADDR_LEN];
    bool window_open;
    int64_t window_deadline_ms;
} ble_enroll_state_t;

typedef struct {
    ble_enroll_config_t config;
    bool stable_pressed;
    bool last_sample_pressed;
    bool fired;
    int64_t last_change_ms;
    int64_t pressed_since_ms;
} ble_enroll_button_t;

void ble_enroll_init(ble_enroll_state_t *state, ble_enroll_config_t config);
esp_err_t ble_enroll_open_window(ble_enroll_state_t *state, int64_t now_ms);
void ble_enroll_close_window(ble_enroll_state_t *state);
bool ble_enroll_window_active(const ble_enroll_state_t *state, int64_t now_ms);
bool ble_enroll_should_advertise(const ble_enroll_state_t *state, int64_t now_ms);
bool ble_enroll_pairing_allowed(const ble_enroll_state_t *state,
                                const uint8_t peer_addr[BLE_ENROLL_ADDR_LEN],
                                int64_t now_ms);
void ble_enroll_note_bonded(ble_enroll_state_t *state,
                            const uint8_t peer_addr[BLE_ENROLL_ADDR_LEN]);
void ble_enroll_clear_bond(ble_enroll_state_t *state);
bool ble_enroll_has_bond(const ble_enroll_state_t *state);
esp_err_t ble_enroll_request_replace(ble_enroll_state_t *state,
                                     bool confirmed,
                                     int64_t now_ms);

void ble_enroll_button_init(ble_enroll_button_t *button,
                            ble_enroll_config_t config);
bool ble_enroll_button_update(ble_enroll_button_t *button,
                              bool pressed,
                              int64_t now_ms);

#ifdef __cplusplus
}
#endif
