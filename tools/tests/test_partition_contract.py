import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _partition_rows():
    with (ROOT / "partitions.csv").open(newline="", encoding="utf-8") as partition_file:
        return {
            row["Name"]: row
            for row in csv.DictReader(
                (line for line in partition_file if not line.lstrip().startswith("#")),
                fieldnames=("Name", "Type", "SubType", "Offset", "Size", "Flags"),
            )
        }


def _partition_extents():
    with (ROOT / "partitions.csv").open(newline="", encoding="utf-8") as partition_file:
        rows = list(
            csv.DictReader(
                (line for line in partition_file if not line.lstrip().startswith("#")),
                fieldnames=("Name", "Type", "SubType", "Offset", "Size", "Flags"),
            )
        )
    return sorted(
        (int(row["Offset"], 0), int(row["Offset"], 0) + int(row["Size"], 0), row["Name"])
        for row in rows
    )


def _sdkconfig_defaults():
    return (ROOT / "sdkconfig.defaults").read_text(encoding="utf-8")


def _dependency_lock_text():
    return (ROOT / "dependencies.lock").read_text(encoding="utf-8")


def test_partition_table_preserves_required_offsets_and_app_size():
    partitions = _partition_rows()

    assert partitions["nvs"] == {
        "Name": "nvs",
        "Type": "data",
        "SubType": "nvs",
        "Offset": "0x9000",
        "Size": "0x6000",
        "Flags": "",
    }
    assert partitions["phy_init"]["Offset"] == "0xf000"
    assert partitions["factory"]["Offset"] == "0x10000"
    assert partitions["factory"]["Size"] == "0x200000"


def test_provision_nvs_and_coredump_follow_factory_application():
    partitions = _partition_rows()

    assert partitions["provision"]["Type"] == "data"
    assert partitions["provision"]["SubType"] == "nvs"
    assert partitions["provision"]["Offset"] == "0x210000"
    assert partitions["provision"]["Size"] == "0x20000"
    assert partitions["coredump"]["Type"] == "data"
    assert partitions["coredump"]["SubType"] == "coredump"
    assert partitions["coredump"]["Offset"] == "0x230000"
    assert partitions["coredump"]["Size"] == "0x10000"


def test_defaults_select_4mb_custom_partition_coexistence_and_certificate_bundle():
    defaults = _sdkconfig_defaults()

    for setting in (
        "CONFIG_ESPTOOLPY_FLASHSIZE_4MB=y",
        "CONFIG_PARTITION_TABLE_CUSTOM=y",
        'CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions.csv"',
        "CONFIG_ESP_COEX_SW_COEXIST_ENABLE=y",
        "CONFIG_MBEDTLS_CERTIFICATE_BUNDLE=y",
    ):
        assert setting in defaults
    assert "CONFIG_IDF_TARGET=" not in defaults


def test_active_sdkconfig_uses_expected_flash_and_partition_table_when_present():
    active_sdkconfig = ROOT / "sdkconfig"
    if not active_sdkconfig.exists():
        return

    config = active_sdkconfig.read_text(encoding="utf-8")
    assert "CONFIG_ESPTOOLPY_FLASHSIZE_4MB=y" in config
    assert "CONFIG_PARTITION_TABLE_CUSTOM=y" in config
    assert 'CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions.csv"' in config


def test_component_manifest_uses_official_mqtt_and_cjson_dependencies():
    manifest = (ROOT / "main" / "idf_component.yml").read_text(encoding="utf-8")

    assert "dependencies:" in manifest
    assert "idf:" in manifest
    assert ">=6.0.2,<6.1" in manifest
    assert "espressif/mqtt:" in manifest
    assert "^1.0.0" in manifest
    assert "espressif/cjson:" in manifest
    assert "^1.7.19" in manifest


def test_all_partition_extents_are_sorted_non_overlapping_and_fit_flash():
    extents = _partition_extents()

    assert [name for _, _, name in extents] == ["nvs", "phy_init", "factory", "provision", "coredump"]
    assert all(current_start >= previous_end for (_, previous_end, _), (current_start, _, _) in zip(extents, extents[1:]))
    assert extents[-1][1] <= 0x400000


def test_dependency_lock_resolves_official_mqtt_and_cjson_for_esp32c6_idf_602():
    lock = _dependency_lock_text()
    cjson_section = lock.split("  espressif/cjson:\n", 1)[1].split("  espressif/mqtt:\n", 1)[0]
    mqtt_section = lock.split("  espressif/mqtt:\n", 1)[1].split("  idf:\n", 1)[0]
    idf_section = lock.split("  idf:\n", 1)[1].split("direct_dependencies:", 1)[0]
    direct_section = lock.split("direct_dependencies:\n", 1)[1].split("manifest_hash:", 1)[0]

    assert "- espressif/cjson\n" in direct_section
    assert "- espressif/mqtt\n" in direct_section
    assert "    version: 1.7.19" in cjson_section
    assert "      registry_url: https://components.espressif.com/" in cjson_section
    assert "    version: 1.0.0" in mqtt_section
    assert "      registry_url: https://components.espressif.com/" in mqtt_section
    assert "    version: 6.0.2" in idf_section
    assert "target: esp32c6" in lock


def test_unity_harness_stack_covers_large_provision_config_test_vectors():
    defaults = (ROOT / "test_app" / "sdkconfig.defaults").read_text(
        encoding="utf-8"
    )
    stack_line = next(
        line
        for line in defaults.splitlines()
        if line.startswith("CONFIG_ESP_MAIN_TASK_STACK_SIZE=")
    )

    assert int(stack_line.split("=", 1)[1]) >= 65536
