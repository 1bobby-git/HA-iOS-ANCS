idf_component_register(
    SRCS "portal_http.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_http_server esp_netif esp_wifi platform_identity provision_store provisioning espressif__cjson
    EMBED_FILES
        "portal.html"
        "portal.css"
        "portal.js"
)
