idf_component_register(
    SRCS "provision_store.c" "provision_policy.c"
    INCLUDE_DIRS "include"
    REQUIRES nvs_flash
)
