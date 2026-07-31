idf_component_register(
    SRCS
        "provisioning_state.c"
        "provisioning_runtime.c"
        "captive_dns.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_event esp_netif esp_wifi provision_store
)
