#include "portal_http.h"

#include <errno.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"
#include "esp_check.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_wifi_types.h"
#include "lwip/inet.h"
#include "lwip/sockets.h"
#include "platform_identity.h"

#define PORTAL_HTTP_MAX_POST_BODY 8192
#define PORTAL_HTTP_JSON_TYPE "application/json"
#define PORTAL_HTTP_REDIRECT_URI "http://192.168.4.1"
#define PORTAL_HTTP_AP_HOST "192.168.4.1"
#define PORTAL_HTTP_SCAN_LIMIT PROVISIONING_RUNTIME_SCAN_MAX_APS

extern const unsigned char portal_html_start[] asm("_binary_portal_html_start");
extern const unsigned char portal_html_end[] asm("_binary_portal_html_end");
extern const unsigned char portal_css_start[] asm("_binary_portal_css_start");
extern const unsigned char portal_css_end[] asm("_binary_portal_css_end");
extern const unsigned char portal_js_start[] asm("_binary_portal_js_start");
extern const unsigned char portal_js_end[] asm("_binary_portal_js_end");

static const char *TAG = "portal_http";
static httpd_handle_t s_server;
static portal_http_handlers_t s_handlers;

static esp_err_t send_json(httpd_req_t *req, const char *json)
{
    httpd_resp_set_type(req, PORTAL_HTTP_JSON_TYPE);
    return httpd_resp_sendstr(req, json);
}

static esp_err_t send_error_json(httpd_req_t *req, const char *status, const char *error)
{
    httpd_resp_set_status(req, status);
    httpd_resp_set_type(req, PORTAL_HTTP_JSON_TYPE);
    char body[128];
    int written = snprintf(body, sizeof(body), "{\"ok\":false,\"error\":\"%s\"}", error);
    return httpd_resp_sendstr(req,
                              written > 0 && (size_t)written < sizeof(body)
                                  ? body
                                  : "{\"ok\":false,\"error\":\"request failed\"}");
}

static esp_err_t send_asset(httpd_req_t *req,
                            const unsigned char *start,
                            const unsigned char *end,
                            const char *content_type)
{
    httpd_resp_set_type(req, content_type);
    return httpd_resp_send(req, (const char *)start, (ssize_t)(end - start));
}

static esp_err_t handle_index_get(httpd_req_t *req)
{
    return send_asset(req, portal_html_start, portal_html_end, "text/html; charset=utf-8");
}

static esp_err_t handle_css_get(httpd_req_t *req)
{
    return send_asset(req, portal_css_start, portal_css_end, "text/css; charset=utf-8");
}

static esp_err_t handle_js_get(httpd_req_t *req)
{
    return send_asset(req, portal_js_start, portal_js_end, "application/javascript; charset=utf-8");
}

static esp_err_t send_redirect(httpd_req_t *req)
{
    httpd_resp_set_status(req, "302 Found");
    httpd_resp_set_hdr(req, "Location", PORTAL_HTTP_REDIRECT_URI);
    return httpd_resp_sendstr(req, "");
}

static esp_err_t handle_probe_redirect(httpd_req_t *req)
{
    return send_redirect(req);
}

static esp_err_t require_ap_local_request(httpd_req_t *req)
{
    const int sockfd = httpd_req_to_sockfd(req);
    if (sockfd < 0) {
        ESP_LOGW(TAG, "portal mutation AP check failed: request socket unavailable");
        return ESP_FAIL;
    }

    struct sockaddr_storage local_addr = {0};
    socklen_t local_len = sizeof(local_addr);
    if (getsockname(sockfd, (struct sockaddr *)&local_addr, &local_len) != 0) {
        ESP_LOGW(TAG,
                 "portal mutation AP check failed: getsockname errno=%d",
                 errno);
        return ESP_FAIL;
    }

    const uint32_t ap_addr = inet_addr(PORTAL_HTTP_AP_HOST);
    if (local_addr.ss_family == AF_INET) {
        if (local_len < sizeof(struct sockaddr_in)) {
            ESP_LOGW(TAG,
                     "portal mutation rejected: short IPv4 local socket address len=%u",
                     (unsigned)local_len);
            return ESP_ERR_INVALID_STATE;
        }

        const struct sockaddr_in *local_ipv4 = (const struct sockaddr_in *)&local_addr;
        if (local_ipv4->sin_addr.s_addr != ap_addr) {
            ESP_LOGW(TAG,
                     "portal mutation rejected: request arrived on local IPv4 %s",
                     inet_ntoa(local_ipv4->sin_addr));
            return ESP_ERR_INVALID_STATE;
        }

        return ESP_OK;
    }

    if (local_addr.ss_family == AF_INET6) {
        if (local_len < sizeof(struct sockaddr_in6)) {
            ESP_LOGW(TAG,
                     "portal mutation rejected: short IPv6 local socket address len=%u",
                     (unsigned)local_len);
            return ESP_ERR_INVALID_STATE;
        }

        const struct sockaddr_in6 *local_ipv6 = (const struct sockaddr_in6 *)&local_addr;
        if (!IN6_IS_ADDR_V4MAPPED(&local_ipv6->sin6_addr)) {
            ESP_LOGW(TAG, "portal mutation rejected: native IPv6 local socket address");
            return ESP_ERR_INVALID_STATE;
        }
        if (memcmp(&local_ipv6->sin6_addr.s6_addr[12], &ap_addr, sizeof(ap_addr)) != 0) {
            ESP_LOGW(TAG,
                     "portal mutation rejected: IPv4-mapped local socket address is not AP");
            return ESP_ERR_INVALID_STATE;
        }

        return ESP_OK;
    }

    ESP_LOGW(TAG,
             "portal mutation rejected: local socket family=%d",
             local_addr.ss_family);
    return ESP_ERR_INVALID_STATE;
}

static esp_err_t send_ap_guard_error(httpd_req_t *req, esp_err_t err)
{
    return err == ESP_ERR_INVALID_STATE
               ? send_error_json(req, "403 Forbidden", "AP interface required")
               : send_error_json(req,
                                 "500 Internal Server Error",
                                 "AP interface check failed");
}

static const char *skip_space_const(const char *p)
{
    while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') {
        ++p;
    }
    return p;
}

static esp_err_t read_json_body(httpd_req_t *req, cJSON **out)
{
    if (out == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    *out = NULL;
    if (req->content_len > PORTAL_HTTP_MAX_POST_BODY) {
        return ESP_ERR_INVALID_SIZE;
    }

    char *body = calloc(1, req->content_len + 1);
    if (body == NULL) {
        return ESP_ERR_NO_MEM;
    }

    size_t received = 0;
    while (received < req->content_len) {
        int read = httpd_req_recv(req,
                                  body + received,
                                  (size_t)req->content_len - received);
        if (read <= 0) {
            free(body);
            return ESP_FAIL;
        }
        received += (size_t)read;
    }

    const char *parse_end = NULL;
    cJSON *json = cJSON_ParseWithLengthOpts(body, received, &parse_end, false);
    const bool trailing_garbage = json == NULL ||
                                  skip_space_const(parse_end == NULL ? body : parse_end) !=
                                      body + received;
    free(body);
    if (trailing_garbage || !cJSON_IsObject(json)) {
        cJSON_Delete(json);
        return ESP_ERR_INVALID_ARG;
    }
    *out = json;
    return ESP_OK;
}

static bool json_copy_string(const cJSON *json,
                             const char *name,
                             char *out,
                             size_t out_size,
                             size_t max_len,
                             bool required)
{
    const cJSON *field = cJSON_GetObjectItemCaseSensitive(json, name);
    if (field == NULL) {
        if (!required) {
            out[0] = '\0';
            return true;
        }
        return false;
    }
    if (!cJSON_IsString(field) || field->valuestring == NULL ||
        strlen(field->valuestring) > max_len ||
        (required && field->valuestring[0] == '\0')) {
        return false;
    }
    strlcpy(out, field->valuestring, out_size);
    return true;
}

static bool json_u16(const cJSON *json, const char *name, uint16_t *out)
{
    const cJSON *field = cJSON_GetObjectItemCaseSensitive(json, name);
    if (!cJSON_IsNumber(field) || field->valuedouble < 1 ||
        field->valuedouble > 65535 || field->valuedouble != (double)field->valueint) {
        return false;
    }
    *out = (uint16_t)field->valueint;
    return true;
}

static bool json_bool(const cJSON *json, const char *name, bool *out)
{
    const cJSON *field = cJSON_GetObjectItemCaseSensitive(json, name);
    if (!cJSON_IsBool(field)) {
        return false;
    }
    *out = cJSON_IsTrue(field);
    return true;
}

static bool parse_config_update(const cJSON *json, provision_config_t *out)
{
    memset(out, 0, sizeof(*out));
    out->schema_version = PROVISION_CONFIG_SCHEMA_VERSION;
    return json_copy_string(json,
                            "wifi_ssid",
                            out->wifi_ssid,
                            sizeof(out->wifi_ssid),
                            PROVISION_WIFI_SSID_MAX,
                            true) &&
           json_copy_string(json,
                            "wifi_password",
                            out->wifi_password,
                            sizeof(out->wifi_password),
                            PROVISION_WIFI_PASSWORD_MAX,
                            false) &&
           json_copy_string(json,
                            "mqtt_host",
                            out->mqtt_host,
                            sizeof(out->mqtt_host),
                            PROVISION_MQTT_HOST_MAX,
                            true) &&
           json_u16(json, "mqtt_port", &out->mqtt_port) &&
           json_copy_string(json,
                            "mqtt_username",
                            out->mqtt_username,
                            sizeof(out->mqtt_username),
                            PROVISION_MQTT_USERNAME_MAX,
                            false) &&
           json_copy_string(json,
                            "mqtt_password",
                            out->mqtt_password,
                            sizeof(out->mqtt_password),
                            PROVISION_MQTT_PASSWORD_MAX,
                            false) &&
           json_bool(json, "mqtt_tls", &out->mqtt_tls) &&
           json_copy_string(json,
                            "mqtt_ca",
                            out->mqtt_ca,
                            sizeof(out->mqtt_ca),
                            PROVISION_MQTT_CA_MAX,
                            false) &&
           json_copy_string(json,
                            "mqtt_client_id",
                            out->mqtt_client_id,
                            sizeof(out->mqtt_client_id),
                            PROVISION_MQTT_CLIENT_ID_MAX,
                            true) &&
           json_copy_string(json,
                            "mqtt_base_topic",
                            out->mqtt_base_topic,
                            sizeof(out->mqtt_base_topic),
                            PROVISION_MQTT_BASE_TOPIC_MAX,
                            true);
}

static bool confirmation_matches(const cJSON *json, const char *literal)
{
    const cJSON *confirmation = cJSON_GetObjectItemCaseSensitive(json, "confirmation");
    return cJSON_IsString(confirmation) && confirmation->valuestring != NULL &&
           strcmp(confirmation->valuestring, literal) == 0;
}

static bool scope_is_all(const cJSON *json)
{
    const cJSON *scope = cJSON_GetObjectItemCaseSensitive(json, "scope");
    return cJSON_IsString(scope) && scope->valuestring != NULL &&
           strcmp(scope->valuestring, "all") == 0;
}

static bool same_config(const provision_config_t *left, const provision_config_t *right)
{
    return memcmp(left, right, sizeof(*left)) == 0;
}

static esp_err_t add_string(cJSON *object, const char *name, const char *value)
{
    return cJSON_AddStringToObject(object, name, value == NULL ? "" : value) != NULL
               ? ESP_OK
               : ESP_ERR_NO_MEM;
}

static esp_err_t add_bool(cJSON *object, const char *name, bool value)
{
    return cJSON_AddBoolToObject(object, name, value) != NULL
               ? ESP_OK
               : ESP_ERR_NO_MEM;
}

static esp_err_t add_number(cJSON *object, const char *name, double value)
{
    return cJSON_AddNumberToObject(object, name, value) != NULL
               ? ESP_OK
               : ESP_ERR_NO_MEM;
}

static esp_err_t add_item(cJSON *object, const char *name, cJSON *item)
{
    return cJSON_AddItemToObject(object, name, item)
               ? ESP_OK
               : ESP_ERR_NO_MEM;
}

static esp_err_t send_cjson(httpd_req_t *req, cJSON *root)
{
    char *printed = cJSON_PrintUnformatted(root);
    if (printed == NULL) {
        return send_error_json(req, "500 Internal Server Error", "out of memory");
    }
    httpd_resp_set_type(req, PORTAL_HTTP_JSON_TYPE);
    esp_err_t err = httpd_resp_sendstr(req, printed);
    cJSON_free(printed);
    return err;
}

static cJSON *build_status_response(void)
{
    provision_config_t *config = calloc(1, sizeof(*config));
    provision_config_status_t *redacted = calloc(1, sizeof(*redacted));
    cJSON *root = cJSON_CreateObject();
    cJSON *cfg = cJSON_CreateObject();
    cJSON *runtime_json = cJSON_CreateObject();
    cJSON *system_json = cJSON_CreateObject();
    bool cfg_attached = false;
    bool runtime_attached = false;
    bool system_attached = false;
    if (config == NULL || redacted == NULL || root == NULL || cfg == NULL ||
        runtime_json == NULL || system_json == NULL) {
        free(config);
        free(redacted);
        cJSON_Delete(root);
        cJSON_Delete(cfg);
        cJSON_Delete(runtime_json);
        cJSON_Delete(system_json);
        return NULL;
    }

    const bool has_config = provision_store_load(config) == ESP_OK &&
                            provision_config_redact_status(config, redacted) == ESP_OK;
    provisioning_runtime_status_t runtime = {0};
    (void)provisioning_runtime_get_status(&runtime);
    portal_http_system_status_t system = {0};
    if (s_handlers.status != NULL) {
        (void)s_handlers.status(&system, s_handlers.context);
    }

    if (add_string(root, "target", ANCS_TARGET_ID) != ESP_OK ||
        add_string(root, "device_family", ANCS_DEVICE_FAMILY) != ESP_OK ||
        add_bool(root, "configured", has_config) != ESP_OK ||
        add_item(root, "config", cfg) != ESP_OK) {
        goto out_of_memory;
    }
    cfg_attached = true;
    if (add_item(root, "runtime", runtime_json) != ESP_OK) {
        goto out_of_memory;
    }
    runtime_attached = true;
    if (add_item(root, "system", system_json) != ESP_OK) {
        goto out_of_memory;
    }
    system_attached = true;

    if (has_config) {
        if (add_string(cfg, "wifi_ssid", redacted->wifi_ssid) != ESP_OK ||
            add_bool(cfg,
                     "wifi_password_configured",
                     redacted->wifi_password_configured) != ESP_OK ||
            add_string(cfg, "mqtt_host", redacted->mqtt_host) != ESP_OK ||
            add_number(cfg, "mqtt_port", redacted->mqtt_port) != ESP_OK ||
            add_string(cfg, "mqtt_username", redacted->mqtt_username) != ESP_OK ||
            add_bool(cfg,
                     "mqtt_password_configured",
                     redacted->mqtt_password_configured) != ESP_OK ||
            add_bool(cfg, "mqtt_tls", redacted->mqtt_tls) != ESP_OK ||
            add_bool(cfg, "mqtt_ca_configured", redacted->mqtt_ca_configured) != ESP_OK ||
            add_string(cfg, "mqtt_client_id", redacted->mqtt_client_id) != ESP_OK ||
            add_string(cfg, "mqtt_base_topic", redacted->mqtt_base_topic) != ESP_OK) {
            goto out_of_memory;
        }
    }

    if (add_bool(runtime_json, "ap_started", runtime.ap_started) != ESP_OK ||
        add_bool(runtime_json, "sta_started", runtime.sta_started) != ESP_OK ||
        add_bool(runtime_json, "sta_connecting", runtime.sta_connecting) != ESP_OK ||
        add_bool(runtime_json, "sta_has_ip", runtime.sta_has_ip) != ESP_OK ||
        add_number(runtime_json,
                   "last_wifi_disconnect_reason",
                   runtime.last_wifi_disconnect_reason) != ESP_OK ||
        add_number(runtime_json,
                   "last_wifi_disconnect_rssi",
                   runtime.last_wifi_disconnect_rssi) != ESP_OK ||
        add_string(runtime_json, "ap_ssid", runtime.ap_ssid) != ESP_OK ||
        add_bool(system_json, "mqtt_connected", system.mqtt_connected) != ESP_OK ||
        add_bool(system_json, "ble_bonded", system.ble_bonded) != ESP_OK ||
        add_bool(system_json, "ble_connected", system.ble_connected) != ESP_OK ||
        add_bool(system_json, "enroll_window_open", system.enroll_window_open) != ESP_OK ||
        add_bool(system_json, "replace_pending", system.replace_pending) != ESP_OK ||
        add_bool(system_json, "replace_failed", system.replace_failed) != ESP_OK ||
        add_number(system_json, "replace_error_code", system.replace_error_code) != ESP_OK ||
        add_number(system_json,
                   "notifications_published",
                   system.notifications_published) != ESP_OK ||
        add_number(system_json,
                   "notifications_dropped",
                   system.notifications_dropped) != ESP_OK) {
        goto out_of_memory;
    }

    free(config);
    free(redacted);
    return root;

out_of_memory:
    free(config);
    free(redacted);
    cJSON_Delete(root);
    if (!cfg_attached) {
        cJSON_Delete(cfg);
    }
    if (!runtime_attached) {
        cJSON_Delete(runtime_json);
    }
    if (!system_attached) {
        cJSON_Delete(system_json);
    }
    return NULL;
}

static esp_err_t handle_status_get(httpd_req_t *req)
{
    cJSON *root = build_status_response();
    if (root == NULL) {
        return send_error_json(req, "500 Internal Server Error", "status unavailable");
    }
    esp_err_t err = send_cjson(req, root);
    cJSON_Delete(root);
    return err;
}

static esp_err_t handle_wifi_scan_get(httpd_req_t *req)
{
    wifi_ap_record_t *records = calloc(PORTAL_HTTP_SCAN_LIMIT, sizeof(*records));
    if (records == NULL) {
        return send_error_json(req, "500 Internal Server Error", "out of memory");
    }
    size_t count = PORTAL_HTTP_SCAN_LIMIT;
    esp_err_t err = provisioning_runtime_scan(records, &count);
    if (err != ESP_OK) {
        free(records);
        return send_error_json(req, "400 Bad Request", "scan unavailable");
    }

    cJSON *root = cJSON_CreateObject();
    cJSON *aps = cJSON_CreateArray();
    if (root == NULL || aps == NULL) {
        free(records);
        cJSON_Delete(root);
        cJSON_Delete(aps);
        return send_error_json(req, "500 Internal Server Error", "out of memory");
    }
    if (add_item(root, "aps", aps) != ESP_OK) {
        free(records);
        cJSON_Delete(root);
        cJSON_Delete(aps);
        return send_error_json(req, "500 Internal Server Error", "out of memory");
    }
    for (size_t i = 0; i < count; ++i) {
        cJSON *ap = cJSON_CreateObject();
        if (ap == NULL) {
            free(records);
            cJSON_Delete(root);
            return send_error_json(req, "500 Internal Server Error", "out of memory");
        }
        if (add_string(ap, "ssid", (const char *)records[i].ssid) != ESP_OK ||
            add_number(ap, "rssi", records[i].rssi) != ESP_OK ||
            add_number(ap, "authmode", records[i].authmode) != ESP_OK ||
            !cJSON_AddItemToArray(aps, ap)) {
            cJSON_Delete(ap);
            free(records);
            cJSON_Delete(root);
            return send_error_json(req, "500 Internal Server Error", "out of memory");
        }
    }
    free(records);

    err = send_cjson(req, root);
    cJSON_Delete(root);
    return err;
}

static esp_err_t handle_config_post(httpd_req_t *req)
{
    esp_err_t guard_err = require_ap_local_request(req);
    if (guard_err != ESP_OK) {
        return send_ap_guard_error(req, guard_err);
    }
    if (s_handlers.reconnect == NULL) {
        return send_error_json(req, "503 Service Unavailable", "reconnect unavailable");
    }

    cJSON *json = NULL;
    esp_err_t err = read_json_body(req, &json);
    if (err != ESP_OK) {
        return send_error_json(req, "400 Bad Request", "invalid JSON");
    }

    provision_config_t *update = calloc(1, sizeof(*update));
    provision_config_t *existing = calloc(1, sizeof(*existing));
    if (update == NULL || existing == NULL) {
        cJSON_Delete(json);
        free(update);
        free(existing);
        return send_error_json(req, "500 Internal Server Error", "out of memory");
    }

    if (!parse_config_update(json, update)) {
        cJSON_Delete(json);
        free(update);
        free(existing);
        return send_error_json(req, "400 Bad Request", "invalid config");
    }
    cJSON_Delete(json);

    if (provision_store_load(existing) == ESP_OK) {
        err = provision_config_merge_preserving_secrets(existing, update, update);
    } else {
        err = provision_config_validate(update) == PROVISION_CONFIG_OK ? ESP_OK
                                                                       : ESP_ERR_INVALID_ARG;
    }
    if (err == ESP_OK) {
        err = provision_store_save_atomic(update);
    }
    if (err == ESP_OK) {
        memset(existing, 0, sizeof(*existing));
        err = provision_store_load(existing);
        if (err == ESP_OK && !same_config(update, existing)) {
            err = ESP_ERR_INVALID_RESPONSE;
        }
    }
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "config save failed: %s", esp_err_to_name(err));
        free(update);
        free(existing);
        return send_error_json(req, "500 Internal Server Error", "save failed");
    }

    err = s_handlers.reconnect(update, s_handlers.context);
    free(update);
    free(existing);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "reconnect callback failed: %s", esp_err_to_name(err));
        return send_json(req, "{\"ok\":true,\"saved\":true,\"reconnect\":false}");
    }
    return send_json(req, "{\"ok\":true,\"saved\":true,\"reconnect\":true}");
}

static esp_err_t handle_empty_action_post(httpd_req_t *req,
                                          esp_err_t (*handler)(void *context),
                                          const char *unavailable,
                                          const char *failed)
{
    esp_err_t guard_err = require_ap_local_request(req);
    if (guard_err != ESP_OK) {
        return send_ap_guard_error(req, guard_err);
    }
    if (handler == NULL) {
        return send_error_json(req, "503 Service Unavailable", unavailable);
    }
    cJSON *json = NULL;
    esp_err_t err = read_json_body(req, &json);
    if (err != ESP_OK) {
        return send_error_json(req, "400 Bad Request", "invalid JSON");
    }
    cJSON_Delete(json);

    err = handler(s_handlers.context);
    return err == ESP_OK ? send_json(req, "{\"ok\":true}")
                         : send_error_json(req, "500 Internal Server Error", failed);
}

static esp_err_t handle_mqtt_test_post(httpd_req_t *req)
{
    return handle_empty_action_post(req,
                                    s_handlers.mqtt_test,
                                    "mqtt test unavailable",
                                    "mqtt test failed");
}

static esp_err_t handle_ble_enroll_post(httpd_req_t *req)
{
    return handle_empty_action_post(req,
                                    s_handlers.ble_enroll,
                                    "enroll unavailable",
                                    "enroll failed");
}

static esp_err_t handle_ble_replace_post(httpd_req_t *req)
{
    esp_err_t guard_err = require_ap_local_request(req);
    if (guard_err != ESP_OK) {
        return send_ap_guard_error(req, guard_err);
    }
    if (s_handlers.ble_replace == NULL) {
        return send_error_json(req, "503 Service Unavailable", "replace unavailable");
    }
    cJSON *json = NULL;
    esp_err_t err = read_json_body(req, &json);
    if (err != ESP_OK) {
        return send_error_json(req, "400 Bad Request", "invalid JSON");
    }
    const bool confirmed = confirmation_matches(json, PORTAL_HTTP_CONFIRM_REPLACE);
    cJSON_Delete(json);
    if (!confirmed) {
        return send_error_json(req, "400 Bad Request", "confirmation required");
    }

    err = s_handlers.ble_replace(s_handlers.context);
    return err == ESP_OK ? send_json(req, "{\"ok\":true,\"replace_requested\":true}")
                         : send_error_json(req, "500 Internal Server Error", "replace failed");
}

static esp_err_t handle_restart_post(httpd_req_t *req)
{
    return handle_empty_action_post(req,
                                    s_handlers.restart,
                                    "restart unavailable",
                                    "restart failed");
}

static esp_err_t handle_reset_post(httpd_req_t *req)
{
    esp_err_t guard_err = require_ap_local_request(req);
    if (guard_err != ESP_OK) {
        return send_ap_guard_error(req, guard_err);
    }
    cJSON *json = NULL;
    esp_err_t err = read_json_body(req, &json);
    if (err != ESP_OK) {
        return send_error_json(req, "400 Bad Request", "invalid JSON");
    }

    const bool wants_all = scope_is_all(json);
    const bool confirmed = confirmation_matches(json,
                                                wants_all ? PORTAL_HTTP_CONFIRM_RESET_ALL_DATA
                                                          : PORTAL_HTTP_CONFIRM_RESET_PROVISIONING);
    cJSON_Delete(json);
    if (!confirmed) {
        return send_error_json(req, "400 Bad Request", "confirmation required");
    }

    if (wants_all) {
        if (s_handlers.reset_all_data == NULL) {
            return send_error_json(req, "400 Bad Request", "all-data reset unavailable");
        }
        err = s_handlers.reset_all_data(s_handlers.context);
    } else if (s_handlers.reset_provisioning != NULL) {
        err = s_handlers.reset_provisioning(s_handlers.context);
    } else {
        err = provision_store_reset();
    }
    return err == ESP_OK ? send_json(req, "{\"ok\":true,\"reset_requested\":true}")
                         : send_error_json(req, "500 Internal Server Error", "reset failed");
}

static esp_err_t handle_not_found(httpd_req_t *req, httpd_err_code_t error)
{
    (void)error;
    return send_redirect(req);
}

static esp_err_t register_uri(httpd_handle_t server,
                              const char *uri,
                              httpd_method_t method,
                              esp_err_t (*handler)(httpd_req_t *))
{
    const httpd_uri_t descriptor = {
        .uri = uri,
        .method = method,
        .handler = handler,
        .user_ctx = NULL,
    };
    return httpd_register_uri_handler(server, &descriptor);
}

static esp_err_t register_all_routes(httpd_handle_t server)
{
    ESP_RETURN_ON_ERROR(httpd_register_err_handler(server,
                                                   HTTPD_404_NOT_FOUND,
                                                   handle_not_found),
                        TAG,
                        "404 handler");
    ESP_RETURN_ON_ERROR(register_uri(server, "/", HTTP_GET, handle_index_get), TAG, "index");
    ESP_RETURN_ON_ERROR(register_uri(server, "/portal.css", HTTP_GET, handle_css_get), TAG, "css");
    ESP_RETURN_ON_ERROR(register_uri(server, "/portal.js", HTTP_GET, handle_js_get), TAG, "js");
    ESP_RETURN_ON_ERROR(register_uri(server, "/api/status", HTTP_GET, handle_status_get), TAG, "status");
    ESP_RETURN_ON_ERROR(register_uri(server, "/api/wifi/scan", HTTP_GET, handle_wifi_scan_get), TAG, "scan");
    ESP_RETURN_ON_ERROR(register_uri(server, "/api/config", HTTP_POST, handle_config_post), TAG, "config");
    ESP_RETURN_ON_ERROR(register_uri(server, "/api/mqtt/test", HTTP_POST, handle_mqtt_test_post), TAG, "mqtt test");
    ESP_RETURN_ON_ERROR(register_uri(server, "/api/ble/enroll", HTTP_POST, handle_ble_enroll_post), TAG, "ble enroll");
    ESP_RETURN_ON_ERROR(register_uri(server, "/api/ble/replace", HTTP_POST, handle_ble_replace_post), TAG, "ble replace");
    ESP_RETURN_ON_ERROR(register_uri(server, "/api/restart", HTTP_POST, handle_restart_post), TAG, "restart");
    ESP_RETURN_ON_ERROR(register_uri(server, "/api/reset", HTTP_POST, handle_reset_post), TAG, "reset");
    ESP_RETURN_ON_ERROR(register_uri(server, "/hotspot-detect.html", HTTP_GET, handle_probe_redirect), TAG, "ios probe");
    ESP_RETURN_ON_ERROR(register_uri(server, "/library/test/success.html", HTTP_GET, handle_probe_redirect), TAG, "ios success");
    ESP_RETURN_ON_ERROR(register_uri(server, "/ncsi.txt", HTTP_GET, handle_probe_redirect), TAG, "ncsi");
    ESP_RETURN_ON_ERROR(register_uri(server, "/connecttest.txt", HTTP_GET, handle_probe_redirect), TAG, "connecttest");
    ESP_RETURN_ON_ERROR(register_uri(server, "/generate_204", HTTP_GET, handle_probe_redirect), TAG, "generate 204");
    ESP_RETURN_ON_ERROR(register_uri(server, "/gen_204", HTTP_GET, handle_probe_redirect), TAG, "gen 204");
    return ESP_OK;
}

esp_err_t portal_http_init(const portal_http_handlers_t *handlers)
{
    if (s_server != NULL) {
        return ESP_OK;
    }
    if (handlers != NULL) {
        s_handlers = *handlers;
    } else {
        memset(&s_handlers, 0, sizeof(s_handlers));
    }

    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.max_uri_handlers = 20;
    config.uri_match_fn = httpd_uri_match_wildcard;

    httpd_handle_t server = NULL;
    esp_err_t err = httpd_start(&server, &config);
    if (err != ESP_OK) {
        return err;
    }
    err = register_all_routes(server);
    if (err != ESP_OK) {
        (void)httpd_stop(server);
        s_server = NULL;
        return err;
    }
    s_server = server;
    return ESP_OK;
}

esp_err_t portal_http_stop(void)
{
    if (s_server == NULL) {
        return ESP_OK;
    }
    httpd_handle_t server = s_server;
    s_server = NULL;
    return httpd_stop(server);
}
