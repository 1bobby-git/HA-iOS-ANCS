idf_component_register(
    SRCS
        "test_main.c"
        "../../test/test_ancs_notification_source.c"
        "../../test/test_ancs_data_parser.c"
        "../../components/ancs_app_resolver/test/test_ancs_app_resolver.c"
        "../../test/test_json_output.c"
        "../../test/test_ancs_client_state.c"
        "../../components/relay_policy/test/test_relay_policy.c"
        "../../components/provision_store/test/test_provision_config.c"
        "../../components/provisioning/test/test_provisioning_state.c"
        "../../components/ble_enroll/test/test_ble_enroll.c"
        "../../components/mqtt_relay/test/test_mqtt_payload.c"
    INCLUDE_DIRS "."
    REQUIRES unity ancs_protocol ancs_app_resolver ancs_state notification_sink relay_policy provision_store provisioning ble_enroll mqtt_relay
    WHOLE_ARCHIVE
)
