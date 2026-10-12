#include "provisioning_retry.h"

#include <limits.h>
#include <string.h>

static uint64_t after(uint64_t now_ms, uint64_t delay_ms)
{
    return now_ms > UINT64_MAX - delay_ms ? UINT64_MAX : now_ms + delay_ms;
}

void provisioning_retry_start(provisioning_retry_t *retry, uint32_t generation,
                              uint64_t now_ms)
{
    memset(retry, 0, sizeof(*retry));
    retry->generation = generation;
    retry->enabled = generation != 0;
    retry->outage_since_ms = now_ms;
    retry->next_attempt_ms = now_ms;
}

void provisioning_retry_stop(provisioning_retry_t *retry)
{
    memset(retry, 0, sizeof(*retry));
}

void provisioning_retry_pause(provisioning_retry_t *retry)
{
    retry->paused = true;
    retry->next_attempt_ms = 0;
}

bool provisioning_retry_matches(const provisioning_retry_t *retry,
                                uint32_t generation)
{
    return retry->enabled && !retry->paused && generation != 0 &&
           retry->generation == generation;
}

void provisioning_retry_connected(provisioning_retry_t *retry, uint64_t now_ms)
{
    if (!retry->enabled || retry->paused) {
        return;
    }
    retry->online = true;
    retry->in_flight = false;
    retry->attempt_deadline_ms = 0;
    retry->next_attempt_ms = 0;
    retry->stable_since_ms = now_ms;
    retry->recovery_announced = false;
}

void provisioning_retry_failed(provisioning_retry_t *retry, uint64_t now_ms,
                               bool authentication_failure, uint32_t random_value)
{
    if (!retry->enabled || retry->paused ||
        (!retry->in_flight && !retry->online)) {
        return; /* Duplicate / intentional disconnect, not another attempt. */
    }
    if (retry->online) {
        retry->online = false;
        retry->in_flight = false;
        retry->outage_since_ms = now_ms;
        retry->stable_since_ms = 0;
        retry->recovery_announced = false;
        retry->next_attempt_ms = now_ms; /* First reconnect is immediate. */
        return;
    }
    retry->in_flight = false;
    retry->attempt_deadline_ms = 0;
    if (authentication_failure) {
        if (retry->auth_failures < UINT8_MAX) {
            ++retry->auth_failures;
        }
    } else {
        retry->auth_failures = 0;
    }
    static const uint32_t delays[] = {5000, 15000, 30000, 60000};
    uint32_t delay_ms = delays[retry->backoff < 3 ? retry->backoff : 3];
    if (retry->backoff < 3) {
        ++retry->backoff;
    }
    if (retry->auth_failures >= 3) {
        delay_ms = PROVISION_RETRY_AUTH_MS;
    }
    const uint32_t jitter_max = delay_ms / 10 < 5000 ? delay_ms / 10 : 5000;
    retry->next_attempt_ms = after(now_ms, delay_ms + random_value % (jitter_max + 1));
}

unsigned provisioning_retry_poll(provisioning_retry_t *retry, uint64_t now_ms,
                                 uint32_t random_value)
{
    if (!retry->enabled || retry->paused) {
        return 0;
    }
    if (retry->online) {
        if (now_ms >= retry->stable_since_ms &&
            now_ms - retry->stable_since_ms >= PROVISION_RETRY_STABLE_MS) {
            retry->backoff = 0;
            retry->auth_failures = 0;
        }
        return 0;
    }
    unsigned actions = 0;
    if (!retry->recovery_announced && now_ms >= retry->outage_since_ms &&
        now_ms - retry->outage_since_ms >= PROVISION_RETRY_RECOVERY_MS) {
        retry->recovery_announced = true;
        actions |= PROVISION_RETRY_OPEN_AP;
    }
    if (retry->in_flight && now_ms >= retry->attempt_deadline_ms) {
        provisioning_retry_failed(retry, now_ms, false, random_value);
        actions |= PROVISION_RETRY_ABORT;
    }
    if (!retry->in_flight && now_ms >= retry->next_attempt_ms) {
        retry->in_flight = true;
        retry->attempt_deadline_ms = after(now_ms, PROVISION_RETRY_ATTEMPT_MS);
        retry->next_attempt_ms = 0;
        if (retry->attempts < UINT32_MAX) {
            ++retry->attempts;
        }
        actions |= PROVISION_RETRY_CONNECT;
    }
    return actions;
}

uint32_t provisioning_retry_remaining_ms(const provisioning_retry_t *retry,
                                         uint64_t now_ms)
{
    if (!retry->enabled || retry->paused || retry->online || retry->in_flight ||
        now_ms >= retry->next_attempt_ms) {
        return 0;
    }
    uint64_t remaining = retry->next_attempt_ms - now_ms;
    return remaining > UINT32_MAX ? UINT32_MAX : (uint32_t)remaining;
}
