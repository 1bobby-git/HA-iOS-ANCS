#include "relay_policy.h"

#include <stdio.h>
#include <string.h>

static const char *const HA_APP_ID = "io.robbie.HomeAssistant";

typedef struct {
    uint32_t state[8];
    uint64_t bit_count;
    uint8_t buffer[64];
    size_t buffer_len;
} sha256_context_t;

static const uint32_t SHA256_K[64] = {
    0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U,
    0x3956c25bU, 0x59f111f1U, 0x923f82a4U, 0xab1c5ed5U,
    0xd807aa98U, 0x12835b01U, 0x243185beU, 0x550c7dc3U,
    0x72be5d74U, 0x80deb1feU, 0x9bdc06a7U, 0xc19bf174U,
    0xe49b69c1U, 0xefbe4786U, 0x0fc19dc6U, 0x240ca1ccU,
    0x2de92c6fU, 0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU,
    0x983e5152U, 0xa831c66dU, 0xb00327c8U, 0xbf597fc7U,
    0xc6e00bf3U, 0xd5a79147U, 0x06ca6351U, 0x14292967U,
    0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU, 0x53380d13U,
    0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U,
    0xa2bfe8a1U, 0xa81a664bU, 0xc24b8b70U, 0xc76c51a3U,
    0xd192e819U, 0xd6990624U, 0xf40e3585U, 0x106aa070U,
    0x19a4c116U, 0x1e376c08U, 0x2748774cU, 0x34b0bcb5U,
    0x391c0cb3U, 0x4ed8aa4aU, 0x5b9cca4fU, 0x682e6ff3U,
    0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U,
    0x90befffaU, 0xa4506cebU, 0xbef9a3f7U, 0xc67178f2U,
};

static uint32_t rotr32(uint32_t value, unsigned int bits)
{
    return (value >> bits) | (value << (32U - bits));
}

static uint32_t load_be32(const uint8_t *bytes)
{
    return ((uint32_t)bytes[0] << 24U) |
           ((uint32_t)bytes[1] << 16U) |
           ((uint32_t)bytes[2] << 8U) |
           (uint32_t)bytes[3];
}

static void store_be32(uint32_t value, uint8_t *out)
{
    out[0] = (uint8_t)(value >> 24U);
    out[1] = (uint8_t)(value >> 16U);
    out[2] = (uint8_t)(value >> 8U);
    out[3] = (uint8_t)value;
}

static void sha256_transform(sha256_context_t *ctx, const uint8_t block[64])
{
    uint32_t w[64];
    for (size_t index = 0; index < 16U; ++index) {
        w[index] = load_be32(block + (index * 4U));
    }
    for (size_t index = 16U; index < 64U; ++index) {
        const uint32_t s0 = rotr32(w[index - 15U], 7U) ^
                            rotr32(w[index - 15U], 18U) ^
                            (w[index - 15U] >> 3U);
        const uint32_t s1 = rotr32(w[index - 2U], 17U) ^
                            rotr32(w[index - 2U], 19U) ^
                            (w[index - 2U] >> 10U);
        w[index] = w[index - 16U] + s0 + w[index - 7U] + s1;
    }

    uint32_t a = ctx->state[0];
    uint32_t b = ctx->state[1];
    uint32_t c = ctx->state[2];
    uint32_t d = ctx->state[3];
    uint32_t e = ctx->state[4];
    uint32_t f = ctx->state[5];
    uint32_t g = ctx->state[6];
    uint32_t h = ctx->state[7];

    for (size_t index = 0; index < 64U; ++index) {
        const uint32_t s1 = rotr32(e, 6U) ^ rotr32(e, 11U) ^ rotr32(e, 25U);
        const uint32_t ch = (e & f) ^ ((~e) & g);
        const uint32_t temp1 = h + s1 + ch + SHA256_K[index] + w[index];
        const uint32_t s0 = rotr32(a, 2U) ^ rotr32(a, 13U) ^ rotr32(a, 22U);
        const uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
        const uint32_t temp2 = s0 + maj;
        h = g;
        g = f;
        f = e;
        e = d + temp1;
        d = c;
        c = b;
        b = a;
        a = temp1 + temp2;
    }

    ctx->state[0] += a;
    ctx->state[1] += b;
    ctx->state[2] += c;
    ctx->state[3] += d;
    ctx->state[4] += e;
    ctx->state[5] += f;
    ctx->state[6] += g;
    ctx->state[7] += h;
}

static void sha256_init(sha256_context_t *ctx)
{
    ctx->state[0] = 0x6a09e667U;
    ctx->state[1] = 0xbb67ae85U;
    ctx->state[2] = 0x3c6ef372U;
    ctx->state[3] = 0xa54ff53aU;
    ctx->state[4] = 0x510e527fU;
    ctx->state[5] = 0x9b05688cU;
    ctx->state[6] = 0x1f83d9abU;
    ctx->state[7] = 0x5be0cd19U;
    ctx->bit_count = 0;
    ctx->buffer_len = 0;
}

static void sha256_update(sha256_context_t *ctx, const uint8_t *data, size_t length)
{
    if (length == 0U) {
        return;
    }
    ctx->bit_count += (uint64_t)length * 8U;
    size_t offset = 0;
    while (offset < length) {
        const size_t space = sizeof(ctx->buffer) - ctx->buffer_len;
        const size_t copy_len = (length - offset) < space ? (length - offset) : space;
        memcpy(ctx->buffer + ctx->buffer_len, data + offset, copy_len);
        ctx->buffer_len += copy_len;
        offset += copy_len;
        if (ctx->buffer_len == sizeof(ctx->buffer)) {
            sha256_transform(ctx, ctx->buffer);
            ctx->buffer_len = 0;
        }
    }
}

static void sha256_finish(sha256_context_t *ctx, uint8_t digest[32])
{
    uint8_t length_bytes[8];
    for (size_t index = 0; index < sizeof(length_bytes); ++index) {
        length_bytes[sizeof(length_bytes) - 1U - index] =
            (uint8_t)(ctx->bit_count >> (index * 8U));
    }

    const uint8_t one = 0x80U;
    sha256_update(ctx, &one, 1U);
    uint8_t zero = 0;
    while (ctx->buffer_len != 56U) {
        sha256_update(ctx, &zero, 1U);
    }
    sha256_update(ctx, length_bytes, sizeof(length_bytes));

    for (size_t index = 0; index < 8U; ++index) {
        store_be32(ctx->state[index], digest + (index * 4U));
    }
}

static void hash_byte(sha256_context_t *hash, uint8_t value)
{
    sha256_update(hash, &value, 1U);
}

static void hash_cstr(sha256_context_t *hash, const char *value)
{
    const char *safe_value = value != NULL ? value : "";
    sha256_update(hash, (const uint8_t *)safe_value, strlen(safe_value) + 1U);
}

static void hash_u32(sha256_context_t *hash, uint32_t value)
{
    hash_byte(hash, (uint8_t)(value & 0xFFU));
    hash_byte(hash, (uint8_t)((value >> 8U) & 0xFFU));
    hash_byte(hash, (uint8_t)((value >> 16U) & 0xFFU));
    hash_byte(hash, (uint8_t)((value >> 24U) & 0xFFU));
}

static bool is_home_assistant_notification(const ancs_notification_t *notification)
{
    return strcmp(notification->app_id, HA_APP_ID) == 0;
}

static bool recent_cache_contains(const relay_recent_cache_t *cache,
                                  const char *relay_id)
{
    if (cache == NULL || relay_id == NULL) {
        return false;
    }
    for (size_t index = 0; index < cache->count; ++index) {
        if (strcmp(cache->relay_ids[index], relay_id) == 0) {
            return true;
        }
    }
    return false;
}

static void recent_cache_store(relay_recent_cache_t *cache, const char *relay_id)
{
    if (cache == NULL || relay_id == NULL) {
        return;
    }
    const size_t index = cache->next_index % RELAY_POLICY_RECENT_CAPACITY;
    (void)strlcpy(cache->relay_ids[index], relay_id, sizeof(cache->relay_ids[index]));
    cache->next_index = (index + 1U) % RELAY_POLICY_RECENT_CAPACITY;
    if (cache->count < RELAY_POLICY_RECENT_CAPACITY) {
        cache->count++;
    }
}

relay_decision_t relay_policy_decide(const ancs_notification_t *notification,
                                     relay_connectivity_t connectivity,
                                     relay_recent_cache_t *cache)
{
    if (notification == NULL || notification->app_id[0] == '\0') {
        return RELAY_DROP_INVALID;
    }
    if (notification->event_id != 0U && notification->event_id != 1U) {
        return RELAY_DROP_EVENT;
    }
    if (!notification->complete) {
        return RELAY_DROP_INCOMPLETE;
    }
    if (ancs_event_flag_is_set(notification->event_flags,
                               ANCS_EVENT_FLAG_PRE_EXISTING)) {
        return RELAY_DROP_PRE_EXISTING;
    }
    if (!connectivity.wifi_connected || !connectivity.mqtt_connected) {
        return RELAY_DROP_OFFLINE;
    }
    if (is_home_assistant_notification(notification)) {
        return RELAY_DROP_ECHO;
    }

    if (cache != NULL) {
        char relay_id[RELAY_POLICY_ID_MAX];
        if (relay_policy_build_id(notification,
                                  connectivity.boot_nonce,
                                  relay_id,
                                  sizeof(relay_id)) != ESP_OK) {
            return RELAY_DROP_INVALID;
        }
        if (recent_cache_contains(cache, relay_id)) {
            return RELAY_DROP_DUPLICATE;
        }
    }
    return RELAY_PUBLISH;
}

esp_err_t relay_policy_build_id(const ancs_notification_t *notification,
                                uint32_t boot_nonce,
                                char *out,
                                size_t out_size)
{
    if (notification == NULL || out == NULL || out_size < RELAY_POLICY_ID_MAX) {
        return ESP_ERR_INVALID_ARG;
    }

    sha256_context_t hash;
    uint8_t digest[32];
    sha256_init(&hash);
    hash_u32(&hash, boot_nonce);
    hash_u32(&hash, notification->session_id);
    hash_u32(&hash, notification->uid);
    hash_u32(&hash, notification->event_id);
    hash_cstr(&hash, notification->app_id);
    hash_cstr(&hash, notification->title);
    hash_cstr(&hash, notification->subtitle);
    hash_cstr(&hash, notification->message);
    hash_cstr(&hash, notification->date_raw);
    sha256_finish(&hash, digest);

    for (size_t index = 0; index < 16U; ++index) {
        (void)snprintf(out + (index * 2U), out_size - (index * 2U),
                       "%02x", digest[index]);
    }
    out[32] = '\0';
    return ESP_OK;
}

void relay_policy_recent_cache_init(relay_recent_cache_t *cache)
{
    if (cache != NULL) {
        memset(cache, 0, sizeof(*cache));
    }
}

void relay_policy_mark_recent(relay_recent_cache_t *cache, const char *relay_id)
{
    recent_cache_store(cache, relay_id);
}

void relay_policy_counters_init(relay_policy_counters_t *counters)
{
    if (counters != NULL) {
        memset(counters, 0, sizeof(*counters));
    }
}

void relay_policy_counters_record(relay_policy_counters_t *counters,
                                  relay_decision_t decision)
{
    if (counters == NULL) {
        return;
    }
    switch (decision) {
    case RELAY_PUBLISH:
        counters->published++;
        break;
    case RELAY_DROP_PRE_EXISTING:
        counters->drop_pre_existing++;
        break;
    case RELAY_DROP_OFFLINE:
        counters->drop_offline++;
        break;
    case RELAY_DROP_ECHO:
        counters->drop_echo++;
        break;
    case RELAY_DROP_DUPLICATE:
        counters->drop_duplicate++;
        break;
    case RELAY_DROP_INCOMPLETE:
        counters->drop_incomplete++;
        break;
    case RELAY_DROP_INVALID:
        counters->drop_invalid++;
        break;
    case RELAY_DROP_EVENT:
        counters->drop_event++;
        break;
    default:
        break;
    }
}

const char *relay_policy_decision_name(relay_decision_t decision)
{
    switch (decision) {
    case RELAY_PUBLISH:
        return "publish";
    case RELAY_DROP_PRE_EXISTING:
        return "drop_pre_existing";
    case RELAY_DROP_OFFLINE:
        return "drop_offline";
    case RELAY_DROP_ECHO:
        return "drop_echo";
    case RELAY_DROP_DUPLICATE:
        return "drop_duplicate";
    case RELAY_DROP_INCOMPLETE:
        return "drop_incomplete";
    case RELAY_DROP_INVALID:
        return "drop_invalid";
    case RELAY_DROP_EVENT:
        return "drop_event";
    default:
        return "unknown";
    }
}
