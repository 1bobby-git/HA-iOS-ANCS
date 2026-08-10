#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ancs_protocol.h"

#ifndef CONFIG_ANCS_APP_CACHE_CAPACITY
#define CONFIG_ANCS_APP_CACHE_CAPACITY 16
#endif

typedef enum {
    ANCS_APP_RESOLUTION_REQUEST_NATIVE = 0,
    ANCS_APP_RESOLUTION_USE_NATIVE,
    ANCS_APP_RESOLUTION_USE_FALLBACK,
} ancs_app_resolution_t;

typedef struct {
    bool used;
    uint32_t age;
    char app_id[CONFIG_ANCS_APP_ID_MAX + 1];
    char display_name[CONFIG_ANCS_APP_NAME_MAX + 1];
} ancs_app_resolver_entry_t;

typedef struct {
    uint32_t age;
    ancs_app_resolver_entry_t entries[CONFIG_ANCS_APP_CACHE_CAPACITY];
} ancs_app_resolver_t;

void ancs_app_resolver_init(ancs_app_resolver_t *resolver);
ancs_app_resolution_t ancs_app_resolver_begin(
    ancs_app_resolver_t *resolver,
    const char *app_id,
    char *output,
    size_t output_capacity);
ancs_app_resolution_t ancs_app_resolver_complete(
    ancs_app_resolver_t *resolver,
    const char *app_id,
    const char *display_name,
    char *output,
    size_t output_capacity);
ancs_app_resolution_t ancs_app_resolver_fail(char *output,
                                             size_t output_capacity);
