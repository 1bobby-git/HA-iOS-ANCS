idf_component_register(
    SRCS "ancs_client.c"
    INCLUDE_DIRS "include"
    REQUIRES device_credentials ancs_protocol ancs_app_resolver ancs_state notification_sink platform_identity hid_server ble_enroll bt nvs_flash esp_timer esp_hw_support esp_driver_gpio
)
