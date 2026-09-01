idf_component_register(
    SRCS "device_credentials.c"
    INCLUDE_DIRS "include"
    REQUIRES nvs_flash esp_hw_support
)
