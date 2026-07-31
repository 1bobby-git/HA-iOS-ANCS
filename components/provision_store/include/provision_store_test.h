#pragma once

#include "sdkconfig.h"

#if CONFIG_PROVISION_STORE_TEST_BACKEND

#ifdef __cplusplus
extern "C" {
#endif

void provision_store_test_reset_backend_state(void);
const char *provision_store_test_last_erased_partition(void);
void provision_store_test_fail_next_commit(void);
void provision_store_test_fail_next_readback(void);
void provision_store_test_fail_next_active_commit(void);
void provision_store_test_corrupt_active_slot(void);
esp_err_t provision_store_test_seed_slot(
    int slot,
    const provision_config_t *config,
    uint32_t generation,
    bool active,
    bool corrupt);
esp_err_t provision_store_test_active_generation(uint32_t *generation_out);

#ifdef __cplusplus
}
#endif

#endif
