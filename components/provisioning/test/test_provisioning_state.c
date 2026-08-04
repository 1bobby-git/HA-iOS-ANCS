#include "provisioning_state.h"
#include "unity.h"

TEST_CASE("no config starts AP without a button", "[provisioning_state]")
{
    provisioning_state_t state =
        provisioning_reduce(provisioning_initial(),
                            PROVISION_EVENT_BOOT_NO_CONFIG,
                            0);

    TEST_ASSERT_TRUE(state.ap_required);
    TEST_ASSERT_FALSE(state.sta_required);
    TEST_ASSERT_FALSE(state.valid_config);
}

TEST_CASE("valid config starts STA without a competing setup AP",
          "[provisioning_state]")
{
    provisioning_state_t state =
        provisioning_reduce(provisioning_initial(),
                            PROVISION_EVENT_BOOT_VALID_CONFIG,
                            0);

    TEST_ASSERT_TRUE(state.sta_required);
    TEST_ASSERT_FALSE(state.ap_required);

    state = provisioning_reduce(state, PROVISION_EVENT_WIFI_CONNECTED, 10);
    state = provisioning_reduce(state, PROVISION_EVENT_MQTT_CONNECTED, 20);
    TEST_ASSERT_FALSE(state.ap_required);

    state = provisioning_reduce(state, PROVISION_EVENT_BOND_PRESENT, 30);
    TEST_ASSERT_FALSE(state.ap_required);
}

TEST_CASE("wifi timeout and mqtt failure require recovery AP",
          "[provisioning_state]")
{
    provisioning_state_t state =
        provisioning_reduce(provisioning_initial(),
                            PROVISION_EVENT_BOOT_VALID_CONFIG,
                            0);
    state = provisioning_reduce(state, PROVISION_EVENT_WIFI_CONNECTED, 1);
    state = provisioning_reduce(state, PROVISION_EVENT_MQTT_CONNECTED, 2);
    state = provisioning_reduce(state, PROVISION_EVENT_BOND_PRESENT, 3);
    TEST_ASSERT_FALSE(state.ap_required);

    state = provisioning_reduce(state, PROVISION_EVENT_WIFI_TIMEOUT, 4);
    TEST_ASSERT_TRUE(state.ap_required);
    TEST_ASSERT_TRUE(state.sta_required);
    TEST_ASSERT_FALSE(state.wifi_connected);
    TEST_ASSERT_FALSE(state.mqtt_connected);

    state = provisioning_reduce(state, PROVISION_EVENT_WIFI_CONNECTED, 5);
    state = provisioning_reduce(state, PROVISION_EVENT_MQTT_CONNECTED, 6);
    TEST_ASSERT_FALSE(state.ap_required);

    state = provisioning_reduce(state, PROVISION_EVENT_MQTT_FAILED, 7);
    TEST_ASSERT_TRUE(state.ap_required);
    TEST_ASSERT_TRUE(state.wifi_connected);
    TEST_ASSERT_FALSE(state.mqtt_connected);
}

TEST_CASE("bond removal does not reopen the setup AP",
          "[provisioning_state]")
{
    provisioning_state_t state =
        provisioning_reduce(provisioning_initial(),
                            PROVISION_EVENT_BOOT_VALID_CONFIG,
                            0);
    state = provisioning_reduce(state, PROVISION_EVENT_WIFI_CONNECTED, 1);
    state = provisioning_reduce(state, PROVISION_EVENT_MQTT_CONNECTED, 2);
    state = provisioning_reduce(state, PROVISION_EVENT_BOND_PRESENT, 3);
    TEST_ASSERT_FALSE(state.ap_required);

    state = provisioning_reduce(state, PROVISION_EVENT_BOND_REMOVED, 4);
    TEST_ASSERT_FALSE(state.ap_required);
    TEST_ASSERT_FALSE(state.has_bond);
}

TEST_CASE("boot hold opens bounded recovery without deleting bond",
          "[provisioning_state]")
{
    provisioning_state_t state =
        provisioning_reduce(provisioning_initial(),
                            PROVISION_EVENT_BOOT_VALID_CONFIG,
                            0);
    state = provisioning_reduce(state, PROVISION_EVENT_WIFI_CONNECTED, 1);
    state = provisioning_reduce(state, PROVISION_EVENT_MQTT_CONNECTED, 2);
    state = provisioning_reduce(state, PROVISION_EVENT_BOND_PRESENT, 3);

    state = provisioning_reduce(state, PROVISION_EVENT_BOOT_HELD_3S, 1000);
    TEST_ASSERT_TRUE(state.recovery_window);
    TEST_ASSERT_TRUE(state.ap_required);
    TEST_ASSERT_TRUE(state.has_bond);
    TEST_ASSERT_TRUE(
        state.recovery_deadline_ms ==
        (uint64_t)(1000 + PROVISION_RECOVERY_WINDOW_MS));

    state = provisioning_reduce(state,
                                PROVISION_EVENT_PORTAL_IDLE_TIMEOUT,
                                state.recovery_deadline_ms - 1);
    TEST_ASSERT_TRUE(state.recovery_window);
    TEST_ASSERT_TRUE(state.ap_required);

    state = provisioning_reduce(state,
                                PROVISION_EVENT_PORTAL_IDLE_TIMEOUT,
                                state.recovery_deadline_ms);
    TEST_ASSERT_FALSE(state.recovery_window);
    TEST_ASSERT_FALSE(state.ap_required);
    TEST_ASSERT_TRUE(state.has_bond);
}
