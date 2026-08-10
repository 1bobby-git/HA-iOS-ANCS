from pathlib import Path


ROOT = Path(__file__).parents[2]
CLIENT = ROOT / "components" / "ancs_client"


def test_client_declares_two_stage_request_state_and_dependency():
    source = (CLIENT / "ancs_client.c").read_text(encoding="utf-8")
    cmake = (CLIENT / "CMakeLists.txt").read_text(encoding="utf-8")

    assert '#include "ancs_app_resolver.h"' in source
    assert "CONTROL_REQUEST_MAX (CONFIG_ANCS_APP_ID_MAX + 3U)" in source
    assert "ACTIVE_REQUEST_NOTIFICATION_ATTRIBUTES" in source
    assert "ACTIVE_REQUEST_APP_ATTRIBUTES" in source
    assert "ancs_app_data_parser_t app_parser;" in source
    assert "ancs_app_resolver_t app_resolver;" in source
    assert "ancs_app_resolver" in cmake


def test_client_resolves_before_one_shot_publication_with_safe_fallback():
    source = (CLIENT / "ancs_client.c").read_text(encoding="utf-8")

    assert "ancs_build_get_app_attributes" in source
    assert "ancs_app_data_parser_feed" in source
    assert "ancs_app_resolver_begin" in source
    assert "ancs_app_resolver_complete" in source
    assert "ancs_app_resolver_fail" in source
    assert "finalize_active_notification" in source
    assert "retry_or_fail_active" not in source
    assert source.count("notification_sink_publish(\n        &s_worker.active_notification") == 2


def test_session_reset_discards_native_app_name_cache():
    source = (CLIENT / "ancs_client.c").read_text(encoding="utf-8")
    reset = source.split("static void reset_worker_session", 1)[1].split(
        "static cache_entry_t *cache_find", 1
    )[0]

    assert "ancs_app_resolver_init(&s_worker.app_resolver);" in reset
    assert "memset(&s_worker.app_parser" in reset
