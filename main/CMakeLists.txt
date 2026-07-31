idf_component_register(
    SRCS "app_main.c"
    INCLUDE_DIRS "."
    REQUIRES
        ancs_client
        mqtt_relay
        notification_sink
        nvs_flash
        portal_http
        provision_store
        provisioning
)
