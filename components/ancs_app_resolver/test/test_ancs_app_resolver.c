#include <stdio.h>
#include <string.h>

#include "ancs_app_resolver.h"
#include "unity.h"

TEST_CASE("resolver requests first name then reuses it until reset",
          "[ancs][app_resolver]")
{
    ancs_app_resolver_t resolver;
    char output[CONFIG_ANCS_APP_NAME_MAX + 1] = "stale";
    ancs_app_resolver_init(&resolver);

    TEST_ASSERT_EQUAL(
        ANCS_APP_RESOLUTION_REQUEST_NATIVE,
        ancs_app_resolver_begin(&resolver,
                                "com.iwilab.KakaoTalk",
                                output,
                                sizeof(output)));
    TEST_ASSERT_EQUAL_STRING("", output);

    TEST_ASSERT_EQUAL(
        ANCS_APP_RESOLUTION_USE_NATIVE,
        ancs_app_resolver_complete(&resolver,
                                   "com.iwilab.KakaoTalk",
                                   "KakaoTalk from iPhone",
                                   output,
                                   sizeof(output)));
    TEST_ASSERT_EQUAL_STRING("KakaoTalk from iPhone", output);

    memset(output, 0, sizeof(output));
    TEST_ASSERT_EQUAL(
        ANCS_APP_RESOLUTION_USE_NATIVE,
        ancs_app_resolver_begin(&resolver,
                                "com.iwilab.KakaoTalk",
                                output,
                                sizeof(output)));
    TEST_ASSERT_EQUAL_STRING("KakaoTalk from iPhone", output);

    ancs_app_resolver_init(&resolver);
    TEST_ASSERT_EQUAL(
        ANCS_APP_RESOLUTION_REQUEST_NATIVE,
        ancs_app_resolver_begin(&resolver,
                                "com.iwilab.KakaoTalk",
                                output,
                                sizeof(output)));
    TEST_ASSERT_EQUAL_STRING("", output);
}

TEST_CASE("resolver returns empty output for enrichment fallback",
          "[ancs][app_resolver]")
{
    ancs_app_resolver_t resolver;
    char output[CONFIG_ANCS_APP_NAME_MAX + 1] = "stale";
    ancs_app_resolver_init(&resolver);

    TEST_ASSERT_EQUAL(ANCS_APP_RESOLUTION_USE_FALLBACK,
                      ancs_app_resolver_begin(&resolver,
                                              "",
                                              output,
                                              sizeof(output)));
    TEST_ASSERT_EQUAL_STRING("", output);

    strcpy(output, "stale");
    TEST_ASSERT_EQUAL(
        ANCS_APP_RESOLUTION_USE_FALLBACK,
        ancs_app_resolver_complete(&resolver,
                                   "com.example.empty",
                                   "",
                                   output,
                                   sizeof(output)));
    TEST_ASSERT_EQUAL_STRING("", output);

    strcpy(output, "stale");
    TEST_ASSERT_EQUAL(ANCS_APP_RESOLUTION_USE_FALLBACK,
                      ancs_app_resolver_fail(output, sizeof(output)));
    TEST_ASSERT_EQUAL_STRING("", output);

    TEST_ASSERT_EQUAL(ANCS_APP_RESOLUTION_USE_FALLBACK,
                      ancs_app_resolver_begin(&resolver,
                                              "com.example.invalid",
                                              NULL,
                                              0U));
}

TEST_CASE("resolver evicts the least recently used session name",
          "[ancs][app_resolver]")
{
    ancs_app_resolver_t resolver;
    char app_id[64];
    char display_name[64];
    char output[CONFIG_ANCS_APP_NAME_MAX + 1];
    ancs_app_resolver_init(&resolver);

    for (size_t index = 0; index < CONFIG_ANCS_APP_CACHE_CAPACITY; ++index) {
        snprintf(app_id, sizeof(app_id), "com.example.app%u", (unsigned int)index);
        snprintf(display_name, sizeof(display_name), "App %u", (unsigned int)index);
        TEST_ASSERT_EQUAL(
            ANCS_APP_RESOLUTION_USE_NATIVE,
            ancs_app_resolver_complete(&resolver,
                                       app_id,
                                       display_name,
                                       output,
                                       sizeof(output)));
    }

    TEST_ASSERT_EQUAL(ANCS_APP_RESOLUTION_USE_NATIVE,
                      ancs_app_resolver_begin(&resolver,
                                              "com.example.app0",
                                              output,
                                              sizeof(output)));
    TEST_ASSERT_EQUAL_STRING("App 0", output);

    TEST_ASSERT_EQUAL(
        ANCS_APP_RESOLUTION_USE_NATIVE,
        ancs_app_resolver_complete(&resolver,
                                   "com.example.overflow",
                                   "Overflow",
                                   output,
                                   sizeof(output)));

    TEST_ASSERT_EQUAL(ANCS_APP_RESOLUTION_REQUEST_NATIVE,
                      ancs_app_resolver_begin(&resolver,
                                              "com.example.app1",
                                              output,
                                              sizeof(output)));
    TEST_ASSERT_EQUAL(ANCS_APP_RESOLUTION_USE_NATIVE,
                      ancs_app_resolver_begin(&resolver,
                                              "com.example.app0",
                                              output,
                                              sizeof(output)));
    TEST_ASSERT_EQUAL(ANCS_APP_RESOLUTION_USE_NATIVE,
                      ancs_app_resolver_begin(&resolver,
                                              "com.example.overflow",
                                              output,
                                              sizeof(output)));
}
