#include "ancs_app_resolver.h"

#include <string.h>

static void clear_output(char *output, size_t output_capacity)
{
    if (output != NULL && output_capacity > 0U) {
        output[0] = '\0';
    }
}

static bool bounded_text(const char *value, size_t maximum, size_t *length)
{
    if (value == NULL || length == NULL) {
        return false;
    }
    *length = strnlen(value, maximum + 1U);
    return *length > 0U && *length <= maximum;
}

static bool copy_output(const char *value,
                        char *output,
                        size_t output_capacity)
{
    if (value == NULL || output == NULL || output_capacity == 0U) {
        return false;
    }
    const size_t length = strlen(value);
    if (length >= output_capacity) {
        output[0] = '\0';
        return false;
    }
    memcpy(output, value, length + 1U);
    return true;
}

static ancs_app_resolver_entry_t *find_entry(ancs_app_resolver_t *resolver,
                                              const char *app_id)
{
    for (size_t index = 0; index < CONFIG_ANCS_APP_CACHE_CAPACITY; ++index) {
        ancs_app_resolver_entry_t *entry = &resolver->entries[index];
        if (entry->used && strcmp(entry->app_id, app_id) == 0) {
            return entry;
        }
    }
    return NULL;
}

static ancs_app_resolver_entry_t *replacement_entry(
    ancs_app_resolver_t *resolver,
    const char *app_id)
{
    ancs_app_resolver_entry_t *target = find_entry(resolver, app_id);
    if (target != NULL) {
        return target;
    }
    for (size_t index = 0; index < CONFIG_ANCS_APP_CACHE_CAPACITY; ++index) {
        if (!resolver->entries[index].used) {
            return &resolver->entries[index];
        }
    }

    target = &resolver->entries[0];
    for (size_t index = 1; index < CONFIG_ANCS_APP_CACHE_CAPACITY; ++index) {
        if (resolver->entries[index].age < target->age) {
            target = &resolver->entries[index];
        }
    }
    return target;
}

void ancs_app_resolver_init(ancs_app_resolver_t *resolver)
{
    if (resolver != NULL) {
        memset(resolver, 0, sizeof(*resolver));
    }
}

ancs_app_resolution_t ancs_app_resolver_begin(
    ancs_app_resolver_t *resolver,
    const char *app_id,
    char *output,
    size_t output_capacity)
{
    clear_output(output, output_capacity);
    size_t app_id_length = 0U;
    if (resolver == NULL || output == NULL || output_capacity == 0U ||
        !bounded_text(app_id, CONFIG_ANCS_APP_ID_MAX, &app_id_length)) {
        return ANCS_APP_RESOLUTION_USE_FALLBACK;
    }
    (void)app_id_length;

    ancs_app_resolver_entry_t *entry = find_entry(resolver, app_id);
    if (entry == NULL) {
        return ANCS_APP_RESOLUTION_REQUEST_NATIVE;
    }
    if (!copy_output(entry->display_name, output, output_capacity)) {
        return ANCS_APP_RESOLUTION_USE_FALLBACK;
    }
    entry->age = ++resolver->age;
    return ANCS_APP_RESOLUTION_USE_NATIVE;
}

ancs_app_resolution_t ancs_app_resolver_complete(
    ancs_app_resolver_t *resolver,
    const char *app_id,
    const char *display_name,
    char *output,
    size_t output_capacity)
{
    clear_output(output, output_capacity);
    size_t app_id_length = 0U;
    size_t display_name_length = 0U;
    if (resolver == NULL || output == NULL || output_capacity == 0U ||
        !bounded_text(app_id, CONFIG_ANCS_APP_ID_MAX, &app_id_length) ||
        !bounded_text(display_name,
                      CONFIG_ANCS_APP_NAME_MAX,
                      &display_name_length) ||
        !copy_output(display_name, output, output_capacity)) {
        return ANCS_APP_RESOLUTION_USE_FALLBACK;
    }

    ancs_app_resolver_entry_t *entry = replacement_entry(resolver, app_id);
    entry->used = true;
    entry->age = ++resolver->age;
    memcpy(entry->app_id, app_id, app_id_length + 1U);
    memcpy(entry->display_name, display_name, display_name_length + 1U);
    return ANCS_APP_RESOLUTION_USE_NATIVE;
}

ancs_app_resolution_t ancs_app_resolver_fail(char *output,
                                             size_t output_capacity)
{
    clear_output(output, output_capacity);
    return ANCS_APP_RESOLUTION_USE_FALLBACK;
}
