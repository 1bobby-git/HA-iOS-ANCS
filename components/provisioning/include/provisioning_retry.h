#pragma once

#include <stdbool.h>
#include <stdint.h>

/* Clock-only policy: callers serialize access and perform all driver I/O. */
#define PROVISION_RETRY_ATTEMPT_MS UINT64_C(20000)
#define PROVISION_RETRY_RECOVERY_MS UINT64_C(45000)
#define PROVISION_RETRY_STABLE_MS UINT64_C(30000)
#define PROVISION_RETRY_AUTH_MS UINT32_C(300000)

#define PROVISION_RETRY_CONNECT (1U << 0)
#define PROVISION_RETRY_ABORT (1U << 1)
#define PROVISION_RETRY_OPEN_AP (1U << 2)

typedef struct {
    uint32_t generation;
    bool enabled;
    bool paused;
    bool online;
    bool in_flight;
    bool recovery_announced;
    uint8_t backoff;
    uint8_t auth_failures;
    uint32_t attempts;
    uint64_t outage_since_ms;
    uint64_t stable_since_ms;
    uint64_t next_attempt_ms;
    uint64_t attempt_deadline_ms;
} provisioning_retry_t;

void provisioning_retry_start(provisioning_retry_t *retry, uint32_t generation,
                              uint64_t now_ms);
void provisioning_retry_stop(provisioning_retry_t *retry);
void provisioning_retry_pause(provisioning_retry_t *retry);
bool provisioning_retry_matches(const provisioning_retry_t *retry,
                                uint32_t generation);
void provisioning_retry_connected(provisioning_retry_t *retry, uint64_t now_ms);
void provisioning_retry_failed(provisioning_retry_t *retry, uint64_t now_ms,
                               bool authentication_failure, uint32_t random_value);
unsigned provisioning_retry_poll(provisioning_retry_t *retry, uint64_t now_ms,
                                 uint32_t random_value);
uint32_t provisioning_retry_remaining_ms(const provisioning_retry_t *retry,
                                         uint64_t now_ms);
