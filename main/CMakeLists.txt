idf_component_register(
    SRCS "app_main.c"
    INCLUDE_DIRS "."
    REQUIRES
        ancs_client
        esp_app_format
        esp_system
        mqtt_relay
        notification_sink
        nvs_flash
        portal_http
        platform_identity
        provision_store
        provisioning
)
