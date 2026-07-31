#include <stdio.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "unity.h"
#include "unity_test_runner.h"

void app_main(void)
{
    printf("ANCS_TEST_BOOT waiting=5000ms\n");
    vTaskDelay(pdMS_TO_TICKS(5000));
    UNITY_BEGIN();
    unity_run_all_tests();
    const int failures = UNITY_END();
    printf("ANCS_TEST_RESULT failures=%d\n", failures);
}
