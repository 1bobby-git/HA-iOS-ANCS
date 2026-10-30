"""Run the 0.4.0 MQTT retry and stored-secret policies on the host with GCC.

The reducer and the policy helpers are plain C, so the rules that decide
when the setup AP opens can be checked without a board.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
CFLAGS = ["-std=c11", "-Wall", "-Wextra", "-Werror"]


def _compiler() -> str:
    compiler = shutil.which("cc") or shutil.which("gcc")
    if compiler is None:
        pytest.skip("host C compiler is unavailable; CI requires GCC")
    return compiler


def _build_and_run(tmp_path, name, sources, includes, main_source, extra=()):
    main = tmp_path / f"{name}_main.c"
    main.write_text(main_source, encoding="utf-8")
    exe = tmp_path / name
    command = [_compiler(), *CFLAGS, *extra]
    for include in includes:
        command += ["-I", str(include)]
    command += [str(source) for source in sources] + [str(main), "-o", str(exe)]
    built = subprocess.run(command, capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(exe)], capture_output=True, text=True)
    assert ran.returncode == 0, ran.stdout + ran.stderr


REDUCER_MAIN = r'''
#include <assert.h>
#include "provisioning_state.h"

#define MINUTE_MS (60ULL * 1000ULL)

static provisioning_state_t verified_online(uint64_t t)
{
    provisioning_state_t s = provisioning_reduce(
        provisioning_initial(), PROVISION_EVENT_BOOT_VALID_CONFIG, t);
    s = provisioning_reduce(s, PROVISION_EVENT_WIFI_CONNECTED, t);
    return provisioning_reduce(s, PROVISION_EVENT_MQTT_CONNECTED, t);
}

int main(void)
{
    /* First install or a typo: settings that never connected open the AP. */
    provisioning_state_t s = provisioning_reduce(
        provisioning_initial(), PROVISION_EVENT_BOOT_VALID_CONFIG, 0);
    s = provisioning_reduce(s, PROVISION_EVENT_WIFI_CONNECTED, 1);
    s = provisioning_reduce(s, PROVISION_EVENT_MQTT_FAILED, 2);
    assert(s.ap_required && !s.mqtt_settings_verified);
    s = provisioning_reduce(
        provisioning_initial(), PROVISION_EVENT_BOOT_VALID_CONFIG, 0);
    s = provisioning_reduce(s, PROVISION_EVENT_WIFI_CONNECTED, 1);
    s = provisioning_reduce(s, PROVISION_EVENT_MQTT_REJECTED, 2);
    assert(s.ap_required);

    /* Proven settings: a broker or network outage only retries, for hours. */
    s = verified_online(1);
    assert(s.mqtt_settings_verified && !s.ap_required);
    for (uint64_t t = 2; t < 6ULL * 60ULL * MINUTE_MS; t += MINUTE_MS) {
        s = provisioning_reduce(s, PROVISION_EVENT_MQTT_FAILED, t);
        assert(!s.ap_required && !s.mqtt_connected && s.wifi_connected);
    }

    /* The stored marker proves the settings again after a reboot. */
    s = provisioning_reduce(
        provisioning_initial(), PROVISION_EVENT_BOOT_VALID_CONFIG, 0);
    s = provisioning_reduce(s, PROVISION_EVENT_MQTT_SETTINGS_VERIFIED, 0);
    s = provisioning_reduce(s, PROVISION_EVENT_WIFI_CONNECTED, 1);
    s = provisioning_reduce(s, PROVISION_EVENT_MQTT_FAILED, 2);
    assert(s.mqtt_settings_verified && !s.ap_required);

    /* Continuous refusals of proven settings open the AP after 10 minutes.
     * Each refused attempt is a refusal plus the disconnect that ends it. */
    s = verified_online(1);
    const uint64_t start = 5 * MINUTE_MS;
    for (uint64_t t = start; t < start + PROVISION_MQTT_REJECTED_RECOVERY_MS;
         t += MINUTE_MS) {
        s = provisioning_reduce(s, PROVISION_EVENT_MQTT_REJECTED, t);
        s = provisioning_reduce(s, PROVISION_EVENT_MQTT_FAILED, t + 5);
        assert(!s.ap_required && s.mqtt_rejecting);
    }
    s = provisioning_reduce(s, PROVISION_EVENT_MQTT_REJECTED,
                            start + PROVISION_MQTT_REJECTED_RECOVERY_MS);
    assert(s.ap_required && s.mqtt_refusal_recovery);
    s = provisioning_reduce(s, PROVISION_EVENT_MQTT_FAILED,
                            start + PROVISION_MQTT_REJECTED_RECOVERY_MS + 5);
    assert(s.ap_required);
    /* Once ten minutes of refusals opened it, a later outage keeps it open. */
    s = provisioning_reduce(s, PROVISION_EVENT_MQTT_FAILED,
                            start + PROVISION_MQTT_REJECTED_RECOVERY_MS + MINUTE_MS);
    assert(s.ap_required);
    /* A successful connection closes it and restarts the rule. */
    s = provisioning_reduce(s, PROVISION_EVENT_MQTT_CONNECTED, start + 20 * MINUTE_MS);
    assert(!s.ap_required && !s.mqtt_rejecting && !s.mqtt_refusal_recovery);

    /* One refusal followed by a plain outage never opens the AP. */
    s = verified_online(1);
    s = provisioning_reduce(s, PROVISION_EVENT_MQTT_REJECTED, MINUTE_MS);
    s = provisioning_reduce(s, PROVISION_EVENT_MQTT_FAILED, MINUTE_MS + 5);
    for (uint64_t t = 2 * MINUTE_MS; t <= 30 * MINUTE_MS; t += MINUTE_MS) {
        s = provisioning_reduce(s, PROVISION_EVENT_MQTT_FAILED, t);
        assert(!s.ap_required);
    }
    assert(!s.mqtt_rejecting);

    /* An outage between refusals restarts the ten minutes. */
    s = verified_online(1);
    s = provisioning_reduce(s, PROVISION_EVENT_MQTT_REJECTED, 2);
    s = provisioning_reduce(s, PROVISION_EVENT_MQTT_FAILED, 7);
    for (uint64_t t = MINUTE_MS; t <= 8 * MINUTE_MS; t += MINUTE_MS) {
        s = provisioning_reduce(s, PROVISION_EVENT_MQTT_FAILED, t);
    }
    for (uint64_t t = 9 * MINUTE_MS; t < 19 * MINUTE_MS; t += MINUTE_MS) {
        s = provisioning_reduce(s, PROVISION_EVENT_MQTT_REJECTED, t);
        s = provisioning_reduce(s, PROVISION_EVENT_MQTT_FAILED, t + 5);
        assert(!s.ap_required);
    }
    s = provisioning_reduce(s, PROVISION_EVENT_MQTT_REJECTED, 19 * MINUTE_MS);
    assert(s.ap_required);

    /* A refusal before a Wi-Fi outage does not hold the AP open afterwards. */
    s = verified_online(1);
    s = provisioning_reduce(s, PROVISION_EVENT_MQTT_REJECTED, MINUTE_MS);
    s = provisioning_reduce(s, PROVISION_EVENT_MQTT_FAILED, MINUTE_MS + 5);
    s = provisioning_reduce(s, PROVISION_EVENT_WIFI_TIMEOUT, 2 * MINUTE_MS);
    assert(s.ap_required);
    s = provisioning_reduce(s, PROVISION_EVENT_WIFI_CONNECTED, 15 * MINUTE_MS);
    s = provisioning_reduce(s, PROVISION_EVENT_MQTT_FAILED, 15 * MINUTE_MS);
    assert(!s.ap_required);

    /* A refusal at uptime 0 still starts the timer. */
    s = provisioning_reduce(
        provisioning_initial(), PROVISION_EVENT_BOOT_VALID_CONFIG, 0);
    s = provisioning_reduce(s, PROVISION_EVENT_MQTT_SETTINGS_VERIFIED, 0);
    s = provisioning_reduce(s, PROVISION_EVENT_WIFI_CONNECTED, 0);
    s = provisioning_reduce(s, PROVISION_EVENT_MQTT_REJECTED, 0);
    s = provisioning_reduce(s, PROVISION_EVENT_MQTT_FAILED, 5);
    assert(!s.ap_required && s.mqtt_rejecting);
    s = provisioning_reduce(s, PROVISION_EVENT_MQTT_REJECTED,
                            PROVISION_MQTT_REJECTED_RECOVERY_MS);
    assert(s.ap_required);

    /* The Wi-Fi rule is unchanged; once Wi-Fi is back, a broker outage
     * with proven settings closes the automatic AP. */
    s = verified_online(1);
    s = provisioning_reduce(s, PROVISION_EVENT_WIFI_TIMEOUT, 2);
    assert(s.ap_required);
    s = provisioning_reduce(s, PROVISION_EVENT_MQTT_FAILED, 3);
    assert(s.ap_required && !s.wifi_connected);
    s = provisioning_reduce(s, PROVISION_EVENT_WIFI_CONNECTED, 4);
    s = provisioning_reduce(s, PROVISION_EVENT_MQTT_FAILED, 5);
    assert(!s.ap_required);

    /* Boot events in either order on the coordinator end verified: the
     * coordinator re-applies the stored marker after BOOT_VALID_CONFIG. */
    s = provisioning_reduce(
        provisioning_initial(), PROVISION_EVENT_BOOT_VALID_CONFIG, 0);
    assert(!s.mqtt_settings_verified);
    s = provisioning_reduce(s, PROVISION_EVENT_MQTT_SETTINGS_VERIFIED, 0);
    assert(s.mqtt_settings_verified);
    s = provisioning_reduce(
        provisioning_initial(), PROVISION_EVENT_MQTT_SETTINGS_VERIFIED, 0);
    assert(!s.mqtt_settings_verified); /* No valid config yet: ignored. */
    s = verified_online(1);

    /* BOOT 3 s and the post-save verification window still open it. */
    s = provisioning_reduce(s, PROVISION_EVENT_BOOT_HELD_3S, 10);
    s = provisioning_reduce(s, PROVISION_EVENT_MQTT_FAILED, 11);
    assert(s.ap_required && s.recovery_window);

    /* New settings must connect once before the retry-only rule applies. */
    s = provisioning_reduce(s, PROVISION_EVENT_BOOT_VALID_CONFIG, 20);
    assert(!s.mqtt_settings_verified && !s.mqtt_rejecting);
    s = provisioning_reduce(s, PROVISION_EVENT_WIFI_CONNECTED, 21);
    s = provisioning_reduce(s, PROVISION_EVENT_MQTT_FAILED, 22);
    assert(s.ap_required);

    /* Erasing the settings clears verification. */
    s = provisioning_reduce(s, PROVISION_EVENT_BOOT_NO_CONFIG, 30);
    assert(s.ap_required && !s.mqtt_settings_verified && !s.mqtt_rejecting);
    return 0;
}
'''


def test_mqtt_failures_with_proven_settings_only_retry(tmp_path):
    _build_and_run(
        tmp_path,
        "reducer",
        [ROOT / "components/provisioning/provisioning_state.c"],
        [ROOT / "components/provisioning/include"],
        REDUCER_MAIN,
    )


STUB_HEADERS = {
    "esp_err.h": r'''
#pragma once
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERR_NO_MEM 0x101
#define ESP_ERR_INVALID_ARG 0x102
#define ESP_ERR_INVALID_STATE 0x103
#define ESP_ERR_INVALID_SIZE 0x104
#define ESP_ERR_NOT_FOUND 0x105
#define ESP_ERR_INVALID_RESPONSE 0x108
#define ESP_ERR_INVALID_CRC 0x109
#define ESP_ERR_INVALID_VERSION 0x10A
const char *esp_err_to_name(esp_err_t code);
''',
    "esp_check.h": r'''
#pragma once
#include "esp_err.h"
#define ESP_LOGE(tag, ...) ((void)(tag))
#define ESP_RETURN_ON_ERROR(x, tag, ...) do { \
        esp_err_t err_rc_ = (x); (void)(tag); \
        if (err_rc_ != ESP_OK) { return err_rc_; } \
    } while (0)
''',
    "nvs.h": r'''
#pragma once
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"
typedef uint32_t nvs_handle_t;
typedef enum { NVS_READONLY, NVS_READWRITE } nvs_open_mode_t;
#define ESP_ERR_NVS_NOT_INITIALIZED 0x1101
#define ESP_ERR_NVS_NOT_FOUND 0x1102
#define ESP_ERR_NVS_NO_FREE_PAGES 0x110d
#define ESP_ERR_NVS_NEW_VERSION_FOUND 0x1110
esp_err_t nvs_open_from_partition(const char *part, const char *ns,
                                  nvs_open_mode_t mode, nvs_handle_t *handle);
esp_err_t nvs_get_blob(nvs_handle_t handle, const char *key, void *out, size_t *len);
esp_err_t nvs_set_blob(nvs_handle_t handle, const char *key, const void *value, size_t len);
esp_err_t nvs_get_u8(nvs_handle_t handle, const char *key, uint8_t *out);
esp_err_t nvs_set_u8(nvs_handle_t handle, const char *key, uint8_t value);
esp_err_t nvs_get_u32(nvs_handle_t handle, const char *key, uint32_t *out);
esp_err_t nvs_set_u32(nvs_handle_t handle, const char *key, uint32_t value);
esp_err_t nvs_commit(nvs_handle_t handle);
void nvs_close(nvs_handle_t handle);
''',
    "nvs_flash.h": r'''
#pragma once
#include "esp_err.h"
esp_err_t nvs_flash_init_partition(const char *part);
esp_err_t nvs_flash_erase_partition(const char *part);
esp_err_t nvs_flash_deinit_partition(const char *part);
''',
    "sdkconfig.h": "#pragma once\n#define CONFIG_PROVISION_STORE_TEST_BACKEND 0\n",
    "host_strlcpy.h": r'''
#pragma once
#include <stddef.h>
size_t provision_host_strlcpy(char *dst, const char *src, size_t size);
#define strlcpy provision_host_strlcpy
''',
}

STUB_SOURCE = r'''
#include <string.h>
#include "nvs.h"
#include "nvs_flash.h"
const char *esp_err_to_name(esp_err_t code) { (void)code; return "stub"; }
size_t provision_host_strlcpy(char *dst, const char *src, size_t size)
{
    size_t length = strlen(src);
    if (size > 0) {
        size_t copy = length < size - 1 ? length : size - 1;
        memcpy(dst, src, copy);
        dst[copy] = '\0';
    }
    return length;
}
esp_err_t nvs_open_from_partition(const char *part, const char *ns,
                                  nvs_open_mode_t mode, nvs_handle_t *handle)
{ (void)part; (void)ns; (void)mode; *handle = 1; return ESP_OK; }
esp_err_t nvs_get_blob(nvs_handle_t h, const char *k, void *o, size_t *l)
{ (void)h; (void)k; (void)o; (void)l; return ESP_ERR_NVS_NOT_FOUND; }
esp_err_t nvs_set_blob(nvs_handle_t h, const char *k, const void *v, size_t l)
{ (void)h; (void)k; (void)v; (void)l; return ESP_OK; }
esp_err_t nvs_get_u8(nvs_handle_t h, const char *k, uint8_t *o)
{ (void)h; (void)k; (void)o; return ESP_ERR_NVS_NOT_FOUND; }
esp_err_t nvs_set_u8(nvs_handle_t h, const char *k, uint8_t v)
{ (void)h; (void)k; (void)v; return ESP_OK; }
static uint32_t s_u32;
static int s_u32_set;
esp_err_t nvs_get_u32(nvs_handle_t h, const char *k, uint32_t *o)
{ (void)h; (void)k; if (!s_u32_set) return ESP_ERR_NVS_NOT_FOUND; *o = s_u32; return ESP_OK; }
esp_err_t nvs_set_u32(nvs_handle_t h, const char *k, uint32_t v)
{ (void)h; (void)k; s_u32 = v; s_u32_set = 1; return ESP_OK; }
esp_err_t nvs_commit(nvs_handle_t h) { (void)h; return ESP_OK; }
void nvs_close(nvs_handle_t h) { (void)h; }
esp_err_t nvs_flash_init_partition(const char *p) { (void)p; return ESP_OK; }
esp_err_t nvs_flash_erase_partition(const char *p) { (void)p; s_u32_set = 0; return ESP_OK; }
esp_err_t nvs_flash_deinit_partition(const char *p) { (void)p; return ESP_OK; }
'''

POLICY_MAIN = r'''
#include <assert.h>
#include <string.h>
#include "nvs.h"
#include "provision_policy.h"
#include "provision_store.h"

static provision_config_t base(void)
{
    provision_config_t c;
    memset(&c, 0, sizeof(c));
    c.schema_version = PROVISION_CONFIG_SCHEMA_VERSION;
    c.mqtt_port = 1883;
    strcpy(c.wifi_ssid, "home");
    strcpy(c.wifi_password, "wifi-secret");
    strcpy(c.mqtt_host, "mqtt.local");
    strcpy(c.mqtt_username, "relay");
    strcpy(c.mqtt_password, "mqtt-secret");
    strcpy(c.mqtt_client_id, "ios_ancs_a1b2c3");
    strcpy(c.mqtt_base_topic, "ios_ancs/a1b2c3");
    return c;
}

int main(void)
{
    const provision_config_t stored = base();
    const uint32_t fp = provision_config_mqtt_fingerprint(&stored);
    assert(fp != 0U);
    assert(provision_config_mqtt_fingerprint(NULL) == 0U);

    /* Wi-Fi and topic changes keep the MQTT settings proven. */
    provision_config_t other = base();
    strcpy(other.wifi_ssid, "office");
    strcpy(other.wifi_password, "x");
    strcpy(other.mqtt_base_topic, "other/topic");
    assert(provision_config_mqtt_fingerprint(&other) == fp);

    /* Every setting the broker checks changes the fingerprint. */
    other = base(); strcpy(other.mqtt_host, "mqtt2.local");
    assert(provision_config_mqtt_fingerprint(&other) != fp);
    other = base(); other.mqtt_port = 8883;
    assert(provision_config_mqtt_fingerprint(&other) != fp);
    other = base(); strcpy(other.mqtt_username, "other");
    assert(provision_config_mqtt_fingerprint(&other) != fp);
    other = base(); strcpy(other.mqtt_password, "other");
    assert(provision_config_mqtt_fingerprint(&other) != fp);
    other = base(); other.mqtt_tls = true; strcpy(other.mqtt_ca, "ca");
    assert(provision_config_mqtt_fingerprint(&other) != fp);
    other = base(); strcpy(other.mqtt_client_id, "other");
    assert(provision_config_mqtt_fingerprint(&other) != fp);

    /* Moving characters between adjacent fields is a different setting. */
    provision_config_t left = base(), right = base();
    strcpy(left.mqtt_username, "ab");
    strcpy(left.mqtt_password, "c");
    strcpy(right.mqtt_username, "a");
    strcpy(right.mqtt_password, "bc");
    assert(provision_config_mqtt_fingerprint(&left) !=
           provision_config_mqtt_fingerprint(&right));

    /* Same server: a blank password keeps the stored one. */
    provision_config_t update = base();
    update.mqtt_password[0] = '\0';
    assert(!provision_config_mqtt_server_changed(&stored, &update));
    assert(provision_config_mqtt_password_rule(&stored, &update, true) ==
           PROVISION_MQTT_PASSWORD_KEEP);

    /* Proven settings, new host or port, username set: type it again. */
    strcpy(update.mqtt_host, "attacker.example");
    assert(provision_config_mqtt_server_changed(&stored, &update));
    assert(provision_config_mqtt_password_rule(&stored, &update, true) ==
           PROVISION_MQTT_PASSWORD_REQUIRED);
    /* Settings that never connected keep the first-install shortcut. */
    assert(provision_config_mqtt_password_rule(&stored, &update, false) ==
           PROVISION_MQTT_PASSWORD_KEEP);
    update = base();
    update.mqtt_password[0] = '\0';
    update.mqtt_port = 1884;
    assert(provision_config_mqtt_password_rule(&stored, &update, true) ==
           PROVISION_MQTT_PASSWORD_REQUIRED);

    /* Typed password, anonymous broker, nothing stored, first install. */
    update = base();
    strcpy(update.mqtt_host, "new.local");
    assert(provision_config_mqtt_password_rule(&stored, &update, true) ==
           PROVISION_MQTT_PASSWORD_KEEP);
    update.mqtt_password[0] = '\0';
    update.mqtt_username[0] = '\0';
    assert(provision_config_mqtt_password_rule(&stored, &update, true) ==
           PROVISION_MQTT_PASSWORD_DROP);
    provision_config_t no_secret = base();
    no_secret.mqtt_password[0] = '\0';
    update = base();
    strcpy(update.mqtt_host, "new.local");
    update.mqtt_password[0] = '\0';
    assert(provision_config_mqtt_password_rule(&no_secret, &update, true) ==
           PROVISION_MQTT_PASSWORD_KEEP);
    assert(provision_config_mqtt_password_rule(NULL, &update, true) ==
           PROVISION_MQTT_PASSWORD_KEEP);

    /* The merge itself is unchanged: blank fields keep stored secrets. */
    provision_config_t merged;
    memset(&merged, 0, sizeof(merged));
    update = base();
    update.wifi_password[0] = '\0';
    update.mqtt_password[0] = '\0';
    assert(provision_config_merge_preserving_secrets(&stored, &update, &merged) == ESP_OK);
    assert(strcmp(merged.mqtt_password, "mqtt-secret") == 0);
    assert(strcmp(merged.wifi_password, "wifi-secret") == 0);
    update = base();
    strcpy(update.mqtt_host, "new.local");
    update.mqtt_password[0] = '\0';
    assert(provision_config_merge_preserving_secrets(&stored, &update, &update) == ESP_OK);
    assert(strcmp(update.mqtt_password, "mqtt-secret") == 0);

    /* The verified marker round-trips and is erased with the settings. */
    uint32_t marker = 1;
    assert(provision_store_load_mqtt_verified(&marker) == ESP_ERR_NVS_NOT_FOUND);
    assert(marker == 0U);
    assert(provision_store_save_mqtt_verified(fp) == ESP_OK);
    assert(provision_store_load_mqtt_verified(&marker) == ESP_OK && marker == fp);
    assert(provision_store_reset() == ESP_OK);
    assert(provision_store_load_mqtt_verified(&marker) == ESP_ERR_NVS_NOT_FOUND);
    return 0;
}
'''


def test_stored_mqtt_password_is_never_sent_to_a_new_server(tmp_path):
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, text in STUB_HEADERS.items():
        (stubs / name).write_text(text, encoding="utf-8")
    stub_source = tmp_path / "stubs.c"
    stub_source.write_text(STUB_SOURCE, encoding="utf-8")
    _build_and_run(
        tmp_path,
        "policy",
        [
            ROOT / "components/provision_store/provision_store.c",
            ROOT / "components/provision_store/provision_policy.c",
            stub_source,
        ],
        [stubs, ROOT / "components/provision_store/include"],
        POLICY_MAIN,
        extra=("-include", str(stubs / "host_strlcpy.h")),
    )


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _section(source: str, start: str, end: str) -> str:
    return source.split(start, 1)[1].split(end, 1)[0]


def test_coordinator_classifies_mqtt_failures_and_remembers_proven_settings():
    app = _read("main/app_main.c")
    handler = _section(app, "static void handle_mqtt_event", "static void handle_config_changed")
    connected = _section(handler, "if (event == MQTT_RELAY_EVENT_CONNECTED)", "return;")
    rejected = _section(app, "static bool mqtt_settings_rejected", "static void suspend_mqtt_for_wifi")

    assert "remember_verified_mqtt_settings();" in connected
    assert "mqtt_settings_rejected(&connection)" in handler
    assert "PROVISION_EVENT_MQTT_REJECTED" in handler
    assert "MQTT_ERROR_TYPE_CONNECTION_REFUSED" in rejected
    assert "MQTT_CONNECTION_REFUSE_SERVER_UNAVAILABLE" in rejected

    provisioning = _section(app, "static void handle_provisioning_event", "static void handle_mqtt_event")
    retry_cases = _section(provisioning, "case PROVISION_EVENT_MQTT_FAILED:", "break;")
    assert "case PROVISION_EVENT_MQTT_REJECTED:" in retry_cases
    assert "schedule_mqtt_retry();" in retry_cases

    remember = _section(app, "static void remember_verified_mqtt_settings", "static bool mqtt_settings_rejected")
    assert "provision_store_save_mqtt_verified(fingerprint)" in remember
    assert remember.index("return; /* Write NVS only") < remember.index("provision_store_save_mqtt_verified")


def test_stored_marker_is_applied_at_boot_and_after_a_settings_change():
    app = _read("main/app_main.c")
    boot = app.split("void app_main(void)", 1)[1]
    # The marker is read before the runtime queues BOOT_VALID_CONFIG.
    assert boot.index("provision_store_load_mqtt_verified(&verified_fingerprint)") < boot.index(
        "error = provisioning_runtime_init(config_valid ? &s_app.config : NULL,"
    )
    assert "PROVISION_EVENT_MQTT_SETTINGS_VERIFIED" not in boot

    # The coordinator re-applies it right after reducing BOOT_VALID_CONFIG, so
    # the order of the two queues cannot lose it.
    provisioning = _section(app, "static void handle_provisioning_event", "static void handle_mqtt_event")
    reduced = provisioning.index("provisioning_state_t state = reduce_app_state(event);")
    reapplied = provisioning.index("reduce_app_state(PROVISION_EVENT_MQTT_SETTINGS_VERIFIED)")
    assert reduced < reapplied < provisioning.index("switch (event)")
    assert "event == PROVISION_EVENT_BOOT_VALID_CONFIG" in provisioning

    changed = _section(app, "static void handle_config_changed", "static void handle_reset_provisioning")
    valid = changed.index("reduce_app_state(PROVISION_EVENT_BOOT_VALID_CONFIG)")
    verified = changed.index("reduce_app_state(PROVISION_EVENT_MQTT_SETTINGS_VERIFIED)")
    applied = changed.index("apply_reducer_requirements(state);")
    assert valid < verified < applied

    reset = _section(app, "static void handle_reset_provisioning", "static void reconcile_network_state")
    assert "s_app.mqtt_verified_fingerprint = 0U" in reset


def test_portal_mqtt_test_connects_now():
    app = _read("main/app_main.c")
    test = _section(app, "static esp_err_t portal_mqtt_test", "static esp_err_t portal_test_notification")
    coordinator = _section(app, "static void coordinator_task", "static esp_err_t initialize_coordinator")
    connect_now = _section(coordinator, "case APP_EVENT_MQTT_CONNECT_NOW:", "break;")

    assert ".type = APP_EVENT_MQTT_CONNECT_NOW" in test
    assert "APP_EVENT_MQTT_RETRY" not in test
    assert "cancel_mqtt_retry();" in connect_now
    assert "start_or_reconnect_mqtt();" in connect_now


def test_portal_requires_the_mqtt_password_for_a_new_server():
    portal = _read("components/portal_http/portal_http.c")
    script = _read("components/portal_http/portal.js")
    html = _read("components/portal_http/portal.html")
    handler = _section(portal, "static esp_err_t handle_config_post", "static esp_err_t handle_empty_action_post")
    verified = _section(portal, "static bool stored_mqtt_settings_verified", "static esp_err_t handle_config_post")

    rule = handler.index("provision_config_mqtt_password_rule(")
    merge = handler.index("provision_config_merge_preserving_secrets(existing, update, update)")
    drop = handler.index("password_rule == PROVISION_MQTT_PASSWORD_DROP")
    assert rule < merge < drop
    assert "stored_mqtt_settings_verified(existing)" in handler
    assert '"400 Bad Request", "mqtt_password_required"' in handler
    assert "memset(update->mqtt_password, 0, sizeof(update->mqtt_password))" in handler
    assert "provision_store_load_mqtt_verified(&marker)" in verified
    assert "provision_config_mqtt_fingerprint(existing)" in verified
    assert "mqtt_password_required:" in script
    assert "API_ERROR_MESSAGES[body.error]" in script
    assert "연결된 적이 있는 MQTT 서버의 주소나 포트를 바꿀 때는 MQTT 비밀번호를 다시 입력해야 합니다." in html

    cmake = _read("components/provision_store/CMakeLists.txt")
    assert '"provision_policy.c"' in cmake
