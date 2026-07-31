idf_component_register(
    SRCS
        "hid_server.c"
        "vendor/esp_hidd_prf_api.c"
        "vendor/hid_dev.c"
        "vendor/hid_device_le_prf.c"
    INCLUDE_DIRS "include"
    PRIV_INCLUDE_DIRS "vendor"
    REQUIRES bt
)

target_compile_options(${COMPONENT_LIB} PRIVATE -Wno-unused-const-variable)
