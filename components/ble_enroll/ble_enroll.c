#include "ble_enroll.h"

#include <string.h>

static uint32_t enroll_window_ms(ble_enroll_config_t config)
{
    return config.window_ms == 0U ? 120000U : config.window_ms;
}

static uint32_t boot_hold_ms(ble_enroll_config_t config)
{
    return config.boot_hold_ms == 0U ? 3000U : config.boot_hold_ms;
}

static uint32_t debounce_ms(ble_enroll_config_t config)
{
    return config.button_debounce_ms == 0U ? 20U : config.button_debounce_ms;
}

void ble_enroll_init(ble_enroll_state_t *state, ble_enroll_config_t config)
{
    if (state == NULL) {
        return;
    }
    memset(state, 0, sizeof(*state));
    state->config = config;
}

esp_err_t ble_enroll_open_window(ble_enroll_state_t *state, int64_t now_ms)
{
    if (state == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    if (state->has_bond) {
        ble_enroll_close_window(state);
        return ESP_ERR_INVALID_STATE;
    }
    state->window_open = true;
    state->window_deadline_ms = now_ms + (int64_t)enroll_window_ms(state->config);
    return ESP_OK;
}

void ble_enroll_close_window(ble_enroll_state_t *state)
{
    if (state == NULL) {
        return;
    }
    state->window_open = false;
    state->window_deadline_ms = 0;
}

bool ble_enroll_window_active(const ble_enroll_state_t *state, int64_t now_ms)
{
    return state != NULL && state->window_open &&
           now_ms < state->window_deadline_ms;
}

bool ble_enroll_should_advertise(const ble_enroll_state_t *state, int64_t now_ms)
{
    return state != NULL &&
           (state->has_bond || ble_enroll_window_active(state, now_ms));
}

bool ble_enroll_pairing_allowed(const ble_enroll_state_t *state,
                                const uint8_t peer_addr[BLE_ENROLL_ADDR_LEN],
                                int64_t now_ms)
{
    if (state == NULL || peer_addr == NULL) {
        return false;
    }
    if (ble_enroll_window_active(state, now_ms)) {
        return true;
    }
    return state->has_bond &&
           memcmp(state->bonded_addr, peer_addr, BLE_ENROLL_ADDR_LEN) == 0;
}

void ble_enroll_note_bonded(ble_enroll_state_t *state,
                            const uint8_t peer_addr[BLE_ENROLL_ADDR_LEN])
{
    if (state == NULL || peer_addr == NULL) {
        return;
    }
    memcpy(state->bonded_addr, peer_addr, BLE_ENROLL_ADDR_LEN);
    state->has_bond = true;
    ble_enroll_close_window(state);
}

void ble_enroll_clear_bond(ble_enroll_state_t *state)
{
    if (state == NULL) {
        return;
    }
    memset(state->bonded_addr, 0, sizeof(state->bonded_addr));
    state->has_bond = false;
}

bool ble_enroll_has_bond(const ble_enroll_state_t *state)
{
    return state != NULL && state->has_bond;
}

esp_err_t ble_enroll_request_replace(ble_enroll_state_t *state,
                                     bool confirmed,
                                     int64_t now_ms)
{
    if (state == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    if (!confirmed) {
        return ESP_ERR_INVALID_STATE;
    }
    ble_enroll_clear_bond(state);
    return ble_enroll_open_window(state, now_ms);
}

void ble_enroll_button_init(ble_enroll_button_t *button,
                            ble_enroll_config_t config)
{
    if (button == NULL) {
        return;
    }
    memset(button, 0, sizeof(*button));
    button->config = config;
}

bool ble_enroll_button_update(ble_enroll_button_t *button,
                              bool pressed,
                              int64_t now_ms)
{
    if (button == NULL) {
        return false;
    }
    if (pressed != button->last_sample_pressed) {
        button->last_sample_pressed = pressed;
        button->last_change_ms = now_ms;
    }
    if (now_ms - button->last_change_ms < (int64_t)debounce_ms(button->config)) {
        return false;
    }
    if (button->stable_pressed != pressed) {
        button->stable_pressed = pressed;
        button->fired = false;
        button->pressed_since_ms = pressed ? now_ms : 0;
    }
    if (!button->stable_pressed || button->fired) {
        return false;
    }
    if (now_ms - button->pressed_since_ms >= (int64_t)boot_hold_ms(button->config)) {
        button->fired = true;
        return true;
    }
    return false;
}
