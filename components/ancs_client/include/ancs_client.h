#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "ancs_state.h"
#include "esp_err.h"

typedef struct {
    bool enroll_active;
    bool replace_pending;
    bool has_bond;
    bool connected;
    bool pairing_repair_required;
    uint8_t auth_failure_count;
    int auth_error;
    int bond_count;
    esp_err_t last_replace_error;
} ancs_client_enrollment_status_t;

typedef void (*ancs_client_boot_held_callback_t)(void *context);

esp_err_t ancs_client_init(void);
/* Runs from the esp_timer task; callback implementations must only enqueue
 * work and return without blocking. Passing NULL unregisters the callback. */
esp_err_t ancs_client_register_boot_held_callback(
    ancs_client_boot_held_callback_t callback,
    void *context);
esp_err_t ancs_client_request_enroll(void);
esp_err_t ancs_client_replace_enrollment(bool confirmed);
uint32_t ancs_client_ble_passkey(void);
ancs_client_enrollment_status_t ancs_client_get_enrollment_status(void);
esp_err_t ancs_client_start_advertising(void);
esp_err_t ancs_client_stop_advertising(void);
void ancs_client_set_pairing_allowed(bool allowed);
bool ancs_client_enroll_active(void);
bool ancs_client_replace_pending(void);
esp_err_t ancs_client_last_replace_error(void);
int ancs_client_bond_count(void);
bool ancs_client_has_bond(void);
bool ancs_client_is_connected(void);
