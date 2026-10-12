idf_component_register(
    SRCS
        "provisioning_state.c"
        "provisioning_retry.c"
        "provisioning_runtime.c"
        "captive_dns.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_event esp_netif esp_wifi esp_timer esp_hw_support provision_store
)
