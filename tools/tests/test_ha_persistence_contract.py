from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "custom_components" / "ha_ios_ancs" / "__init__.py"


def test_notification_persistence_is_coalesced_and_private():
    source = SOURCE.read_text(encoding="utf-8")
    assert "private=True" in source
    assert "_STORAGE_SAVE_DELAY_SECONDS = 2.0" in source
    assert "store.async_delay_save(" in source
    assert "lambda: snapshot" in source
    assert "hass.async_create_task(store.async_save(dict(notification)))" not in source
