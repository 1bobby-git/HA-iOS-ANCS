#include <string.h>

#include "ble_enroll.h"
#include "unity.h"
#include "unity_test_runner.h"

static const uint8_t PEER_A[6] = {0x10, 0x20, 0x30, 0x40, 0x50, 0x60};
static const uint8_t PEER_B[6] = {0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF};

static ble_enroll_config_t test_config(void)
{
    return (ble_enroll_config_t){
        .window_ms = 120000,
        .boot_hold_ms = 3000,
        .button_debounce_ms = 20,
    };
}

TEST_CASE("unbonded boot stays dark until explicit enroll window",
          "[ble_enroll]")
{
    ble_enroll_state_t state;
    ble_enroll_init(&state, test_config());

    TEST_ASSERT_FALSE(ble_enroll_should_advertise(&state, 0));
    TEST_ASSERT_FALSE(ble_enroll_pairing_allowed(&state, PEER_A, 0));

    TEST_ASSERT_EQUAL(ESP_OK, ble_enroll_open_window(&state, 1000));
    TEST_ASSERT_TRUE(ble_enroll_should_advertise(&state, 1000));
    TEST_ASSERT_TRUE(ble_enroll_pairing_allowed(&state, PEER_A, 1000));

    ble_enroll_note_bonded(&state, PEER_A);
    TEST_ASSERT_FALSE(ble_enroll_window_active(&state, 1001));
    TEST_ASSERT_TRUE(ble_enroll_should_advertise(&state, 1001));
    TEST_ASSERT_TRUE(ble_enroll_pairing_allowed(&state, PEER_A, 1001));
    TEST_ASSERT_FALSE(ble_enroll_pairing_allowed(&state, PEER_B, 1001));
}

TEST_CASE("enroll timeout closes unbonded advertising and pairing",
          "[ble_enroll]")
{
    ble_enroll_state_t state;
    ble_enroll_init(&state, test_config());

    TEST_ASSERT_EQUAL(ESP_OK, ble_enroll_open_window(&state, 5000));
    TEST_ASSERT_TRUE(ble_enroll_should_advertise(&state, 124999));
    TEST_ASSERT_FALSE(ble_enroll_window_active(&state, 125001));
    TEST_ASSERT_FALSE(ble_enroll_should_advertise(&state, 125001));
    TEST_ASSERT_FALSE(ble_enroll_pairing_allowed(&state, PEER_A, 125001));
}

TEST_CASE("plain enroll with an existing bond keeps new pairing closed",
          "[ble_enroll]")
{
    ble_enroll_state_t state;
    ble_enroll_init(&state, test_config());
    ble_enroll_note_bonded(&state, PEER_A);

    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_STATE,
                      ble_enroll_open_window(&state, 7000));
    TEST_ASSERT_FALSE(ble_enroll_window_active(&state, 7000));
    TEST_ASSERT_TRUE(ble_enroll_should_advertise(&state, 7000));
    TEST_ASSERT_TRUE(ble_enroll_pairing_allowed(&state, PEER_A, 7000));
    TEST_ASSERT_FALSE(ble_enroll_pairing_allowed(&state, PEER_B, 7000));
}

TEST_CASE("replace requires confirmation and clears known peer",
          "[ble_enroll]")
{
    ble_enroll_state_t state;
    ble_enroll_init(&state, test_config());
    ble_enroll_note_bonded(&state, PEER_A);

    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_STATE,
                      ble_enroll_request_replace(&state, false, 7000));
    TEST_ASSERT_TRUE(ble_enroll_has_bond(&state));
    TEST_ASSERT_FALSE(ble_enroll_pairing_allowed(&state, PEER_B, 7000));

    TEST_ASSERT_EQUAL(ESP_OK, ble_enroll_request_replace(&state, true, 7000));
    TEST_ASSERT_FALSE(ble_enroll_has_bond(&state));
    TEST_ASSERT_TRUE(ble_enroll_should_advertise(&state, 7000));
    TEST_ASSERT_TRUE(ble_enroll_pairing_allowed(&state, PEER_B, 7000));
}

TEST_CASE("boot button long press fires once after debounce",
          "[ble_enroll]")
{
    ble_enroll_button_t button;
    ble_enroll_button_init(&button, test_config());

    TEST_ASSERT_FALSE(ble_enroll_button_update(&button, true, 0));
    TEST_ASSERT_FALSE(ble_enroll_button_update(&button, false, 10));
    TEST_ASSERT_FALSE(ble_enroll_button_update(&button, true, 100));
    TEST_ASSERT_FALSE(ble_enroll_button_update(&button, true, 119));
    TEST_ASSERT_FALSE(ble_enroll_button_update(&button, true, 120));
    TEST_ASSERT_FALSE(ble_enroll_button_update(&button, true, 3119));
    TEST_ASSERT_TRUE(ble_enroll_button_update(&button, true, 3120));
    TEST_ASSERT_FALSE(ble_enroll_button_update(&button, true, 5000));
    TEST_ASSERT_FALSE(ble_enroll_button_update(&button, false, 5010));
    TEST_ASSERT_FALSE(ble_enroll_button_update(&button, true, 6000));
}

TEST_CASE("policy keeps unbonded boot silent over time",
          "[ble_enroll]")
{
    ble_enroll_state_t state;
    ble_enroll_init(&state, test_config());

    TEST_ASSERT_FALSE(ble_enroll_should_advertise(&state, 0));
    TEST_ASSERT_FALSE(ble_enroll_should_advertise(&state, 1));
    TEST_ASSERT_FALSE(ble_enroll_should_advertise(&state, 120000));
    TEST_ASSERT_FALSE(ble_enroll_should_advertise(&state, 600000));
    TEST_ASSERT_FALSE(ble_enroll_pairing_allowed(&state, PEER_A, 600000));
}

TEST_CASE("policy enrollment window advertises until deadline then stops",
          "[ble_enroll]")
{
    ble_enroll_state_t state;
    ble_enroll_init(&state, test_config());

    TEST_ASSERT_EQUAL(ESP_OK, ble_enroll_open_window(&state, 5000));
    TEST_ASSERT_TRUE(ble_enroll_should_advertise(&state, 5000));
    TEST_ASSERT_TRUE(ble_enroll_should_advertise(&state, 124999));
    TEST_ASSERT_FALSE(ble_enroll_should_advertise(&state, 125000));
    TEST_ASSERT_FALSE(ble_enroll_pairing_allowed(&state, PEER_A, 125000));
}

TEST_CASE("policy stored bond auto advertises only for bonded peer",
          "[ble_enroll]")
{
    ble_enroll_state_t state;
    ble_enroll_init(&state, test_config());
    ble_enroll_note_bonded(&state, PEER_A);

    TEST_ASSERT_FALSE(ble_enroll_window_active(&state, 0));
    TEST_ASSERT_TRUE(ble_enroll_should_advertise(&state, 0));
    TEST_ASSERT_TRUE(ble_enroll_should_advertise(&state, 600000));
    TEST_ASSERT_TRUE(ble_enroll_pairing_allowed(&state, PEER_A, 600000));
    TEST_ASSERT_FALSE(ble_enroll_pairing_allowed(&state, PEER_B, 600000));
}
