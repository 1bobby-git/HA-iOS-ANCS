idf_component_register(
    SRCS
        "mqtt_payload.c"
        "mqtt_relay.c"
    INCLUDE_DIRS "include"
    REQUIRES ancs_protocol notification_sink platform_identity provision_store relay_policy espressif__mqtt freertos esp_timer
)
