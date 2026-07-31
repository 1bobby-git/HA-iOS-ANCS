#include "ancs_state.h"
#include "unity.h"

TEST_CASE("client state follows secure data-first subscription order", "[ancs][state]")
{
    ancs_client_state_t state = ANCS_STATE_BOOT;
    state = ancs_client_state_after(state, ANCS_SIGNAL_BOOT_COMPLETE);
    TEST_ASSERT_EQUAL(ANCS_STATE_ADVERTISING, state);
    state = ancs_client_state_after(state, ANCS_SIGNAL_CONNECTED);
    TEST_ASSERT_EQUAL(ANCS_STATE_CONNECTED, state);
    state = ancs_client_state_after(state, ANCS_SIGNAL_ENCRYPTION_STARTED);
    TEST_ASSERT_EQUAL(ANCS_STATE_ENCRYPTING, state);
    state = ancs_client_state_after(state, ANCS_SIGNAL_BONDED);
    TEST_ASSERT_EQUAL(ANCS_STATE_BONDED, state);
    state = ancs_client_state_after(state, ANCS_SIGNAL_DISCOVERY_STARTED);
    TEST_ASSERT_EQUAL(ANCS_STATE_DISCOVERING_ANCS, state);
    state = ancs_client_state_after(state, ANCS_SIGNAL_DATA_SUBSCRIBE_STARTED);
    TEST_ASSERT_EQUAL(ANCS_STATE_SUBSCRIBING_DATA_SOURCE, state);
    state = ancs_client_state_after(state, ANCS_SIGNAL_DATA_SUBSCRIBED);
    TEST_ASSERT_EQUAL(ANCS_STATE_SUBSCRIBING_NOTIFICATION_SOURCE, state);
    state = ancs_client_state_after(state, ANCS_SIGNAL_NOTIFICATION_SUBSCRIBED);
    TEST_ASSERT_EQUAL(ANCS_STATE_ANCS_READY, state);
}

TEST_CASE("service changed invalidates ready state and restarts discovery", "[ancs][state]")
{
    TEST_ASSERT_EQUAL(ANCS_STATE_RECOVERING,
                      ancs_client_state_after(ANCS_STATE_ANCS_READY,
                                              ANCS_SIGNAL_SERVICE_CHANGED));
    TEST_ASSERT_EQUAL(ANCS_STATE_DISCOVERING_ANCS,
                      ancs_client_state_after(ANCS_STATE_RECOVERING,
                                              ANCS_SIGNAL_DISCOVERY_STARTED));
}

TEST_CASE("disconnect always reaches disconnected state", "[ancs][state]")
{
    for (int state = ANCS_STATE_BOOT; state <= ANCS_STATE_RECOVERING; ++state) {
        TEST_ASSERT_EQUAL(ANCS_STATE_DISCONNECTED,
                          ancs_client_state_after((ancs_client_state_t)state,
                                                  ANCS_SIGNAL_DISCONNECTED));
    }
}
