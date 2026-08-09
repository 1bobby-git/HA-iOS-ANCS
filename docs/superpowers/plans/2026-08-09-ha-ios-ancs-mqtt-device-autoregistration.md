# HA iOS ANCS MQTT Device Autoregistration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace manual MQTT-topic setup for new entries with registry-backed ANCS device discovery, attach the notification event entity to the existing MQTT device, and reliably emit new firmware notifications without replaying retained state.

**Architecture:** Home Assistant's MQTT integration remains the owner of the discovered device and `last_notification` sensor. The custom integration stores the stable MQTT sensor unique ID plus MQTT device identifier, resolves the current entity ID at setup, listens for state changes, applies the existing ANCS filters, and exposes one native event entity on the existing `DeviceEntry`. Legacy `base_topic` entries retain the direct-MQTT runtime until explicit reconfiguration.

**Tech Stack:** Python 3.14, Home Assistant 2026.7.3 config flows and registries, MQTT Discovery entities, pytest 9, basedpyright, HACS validation, Hassfest.

---

## Baseline and constraints

- Baseline command already run:

  ```powershell
  uv run --python 3.14 --with-requirements requirements_test.txt python -m pytest tests -q
  ```

- Baseline result: `75 passed, 5 warnings`.
- Do not remove firmware-owned MQTT entities or publish new discovery payloads from the custom integration.
- Do not infer a legacy `base_topic` matches the only discovered device. Convert legacy entries only through the reconfigure flow.
- Do not fire an event for the source sensor state present at startup.
- Keep the existing `complete`, `pre_existing`, `removed`, Home Assistant echo, and relay-ID duplicate filters.
- Use one behavior-focused commit per task and the repository Lore commit trailers.

## Task 1: Model and discover compatible MQTT ANCS sources

**Files:**

- Create: `custom_components/ha_ios_ancs/source.py`
- Modify: `custom_components/ha_ios_ancs/const.py`
- Modify: `tests/conftest.py`
- Create: `tests/helpers.py`
- Create: `tests/test_source.py`

- [ ] **Step 1: Add an isolated registry-ready Home Assistant fixture**

  Add this non-autouse fixture to `tests/conftest.py`. Only registry-backed tests request it, so existing event tests that explicitly initialize the device registry are unchanged.

  ```python
  from homeassistant.helpers import device_registry as dr
  from homeassistant.helpers import entity_registry as er


  @pytest.fixture
  def registry_hass(hass: HomeAssistant, run) -> HomeAssistant:
      dr.async_setup(hass)
      run(dr.async_load(hass, load_empty=True))
      run(er.async_get(hass).async_load(load_empty=True))
      return hass
  ```

- [ ] **Step 2: Add registry test helpers**

  Add `tests/helpers.py` with a reusable MQTT registry builder. It requires the `registry_hass` fixture, creates one MQTT config entry, creates a device with `("mqtt", mqtt_device_identifier)`, and creates a sensor whose platform is `mqtt` and whose unique ID is `<identifier>_last_notification`.

  ```python
  from __future__ import annotations

  from dataclasses import dataclass
  from types import MappingProxyType
  from unittest.mock import AsyncMock, patch

  from homeassistant.config_entries import ConfigEntry
  from homeassistant.core import HomeAssistant
  from homeassistant.helpers import device_registry as dr
  from homeassistant.helpers import entity_registry as er
  from homeassistant.helpers.discovery_flow import DiscoveryKey

  EMPTY_DISCOVERY_KEYS: MappingProxyType[str, tuple[DiscoveryKey, ...]] = (
      MappingProxyType({})
  )


  @dataclass(frozen=True, slots=True)
  class RegisteredMqttSource:
      config_entry: ConfigEntry
      device: dr.DeviceEntry
      entity: er.RegistryEntry


  async def async_register_mqtt_ancs_source(
      hass: HomeAssistant,
      mqtt_device_identifier: str,
      *,
      device_name: str,
      entity_unique_id: str | None = None,
  ) -> RegisteredMqttSource:
      mqtt_entries = hass.config_entries.async_entries("mqtt")
      if mqtt_entries:
          mqtt_entry = mqtt_entries[0]
      else:
          mqtt_entry = ConfigEntry(
              version=1,
              minor_version=1,
              domain="mqtt",
              title="MQTT",
              data={},
              source="user",
              unique_id=None,
              discovery_keys=EMPTY_DISCOVERY_KEYS,
              options={},
              subentries_data={},
          )
          with patch.object(
              hass.config_entries,
              "async_setup",
              new=AsyncMock(return_value=True),
          ):
              await hass.config_entries.async_add(mqtt_entry)
              await hass.async_block_till_done()

      device_registry = dr.async_get(hass)
      entity_registry = er.async_get(hass)
      device = device_registry.async_get_or_create(
          config_entry_id=mqtt_entry.entry_id,
          identifiers={("mqtt", mqtt_device_identifier)},
          name=device_name,
      )
      entity = entity_registry.async_get_or_create(
          "sensor",
          "mqtt",
          entity_unique_id or f"{mqtt_device_identifier}_last_notification",
          config_entry=mqtt_entry,
          device_id=device.id,
          suggested_object_id=f"{mqtt_device_identifier}_last_notification",
      )
      return RegisteredMqttSource(mqtt_entry, device, entity)
  ```

- [ ] **Step 3: Write failing discovery and resolution tests**

  In `tests/test_source.py`, add these cases:

  ```python
  def test_discovery_returns_only_matching_mqtt_last_notification_sensor(
      registry_hass: HomeAssistant, run
  ) -> None:
      hass = registry_hass
      compatible = run(
          async_register_mqtt_ancs_source(
              hass,
              "ios_ancs_A1B2C3",
              device_name="iOS ANCS A1B2C3",
          )
      )
      run(
          async_register_mqtt_ancs_source(
              hass,
              "unrelated",
              device_name="Unrelated MQTT device",
              entity_unique_id="unrelated_temperature",
          )
      )

      sources = async_discover_ancs_sources(hass)

      assert sources == [
          AncsSource(
              entity_id=compatible.entity.entity_id,
              entity_unique_id="ios_ancs_A1B2C3_last_notification",
              mqtt_device_identifier="ios_ancs_A1B2C3",
              device_id=compatible.device.id,
              name="iOS ANCS A1B2C3",
          )
      ]


  def test_resolver_uses_unique_id_after_entity_id_rename(
      registry_hass: HomeAssistant, run
  ) -> None:
      hass = registry_hass
      registered = run(
          async_register_mqtt_ancs_source(
              hass,
              "ios_ancs_A1B2C3",
              device_name="iOS ANCS A1B2C3",
          )
      )
      registry = er.async_get(hass)
      registry.async_update_entity(
          registered.entity.entity_id,
          new_entity_id="sensor.renamed_ancs_notification",
      )

      source = async_resolve_ancs_source(
          hass,
          "ios_ancs_A1B2C3_last_notification",
          "ios_ancs_A1B2C3",
      )

      assert source is not None
      assert source.entity_id == "sensor.renamed_ancs_notification"
      assert source.device_id == registered.device.id


  def test_resolver_rejects_identifier_mismatch(
      registry_hass: HomeAssistant, run
  ) -> None:
      hass = registry_hass
      registered = run(
          async_register_mqtt_ancs_source(
              hass,
              "ios_ancs_A1B2C3",
              device_name="iOS ANCS A1B2C3",
          )
      )

      assert (
          async_resolve_ancs_source(
              hass,
              registered.entity.unique_id,
              "ios_ancs_DIFFERENT",
          )
          is None
      )
  ```

- [ ] **Step 4: Run the new test file and confirm RED**

  ```powershell
  uv run --python 3.14 --with-requirements requirements_test.txt python -m pytest tests/test_source.py -q
  ```

  Expected: collection fails because `source.py` and its symbols do not exist.

- [ ] **Step 5: Add stable source constants and registry discovery**

  Add to `custom_components/ha_ios_ancs/const.py`:

  ```python
  CONF_SOURCE_ENTITY_UNIQUE_ID = "source_entity_unique_id"
  CONF_MQTT_DEVICE_IDENTIFIER = "mqtt_device_identifier"

  MQTT_DOMAIN = "mqtt"
  LAST_NOTIFICATION_UNIQUE_ID_SUFFIX = "last_notification"
  ```

  Implement `custom_components/ha_ios_ancs/source.py` with this public surface:

  ```python
  from __future__ import annotations

  from dataclasses import dataclass

  from homeassistant.const import Platform
  from homeassistant.core import HomeAssistant, callback
  from homeassistant.helpers import device_registry as dr
  from homeassistant.helpers import entity_registry as er

  from .const import LAST_NOTIFICATION_UNIQUE_ID_SUFFIX, MQTT_DOMAIN


  @dataclass(frozen=True, slots=True)
  class AncsSource:
      entity_id: str
      entity_unique_id: str
      mqtt_device_identifier: str
      device_id: str
      name: str


  def _source_from_entries(
      entity_entry: er.RegistryEntry,
      device_entry: dr.DeviceEntry,
      mqtt_device_identifier: str,
  ) -> AncsSource | None:
      expected_unique_id = (
          f"{mqtt_device_identifier}_{LAST_NOTIFICATION_UNIQUE_ID_SUFFIX}"
      )
      if entity_entry.unique_id != expected_unique_id:
          return None
      return AncsSource(
          entity_id=entity_entry.entity_id,
          entity_unique_id=entity_entry.unique_id,
          mqtt_device_identifier=mqtt_device_identifier,
          device_id=device_entry.id,
          name=(
              device_entry.name_by_user
              or device_entry.name
              or entity_entry.name
              or entity_entry.original_name
              or mqtt_device_identifier
          ),
      )


  @callback
  def async_discover_ancs_sources(hass: HomeAssistant) -> list[AncsSource]:
      entity_registry = er.async_get(hass)
      device_registry = dr.async_get(hass)
      sources: list[AncsSource] = []
      for entity_entry in entity_registry.entities.values():
          if (
              entity_entry.domain != Platform.SENSOR
              or entity_entry.platform != MQTT_DOMAIN
              or entity_entry.device_id is None
          ):
              continue
          device_entry = device_registry.async_get(entity_entry.device_id)
          if device_entry is None:
              continue
          for identifier_domain, identifier_value in device_entry.identifiers:
              if identifier_domain != MQTT_DOMAIN:
                  continue
              source = _source_from_entries(
                  entity_entry,
                  device_entry,
                  identifier_value,
              )
              if source is not None:
                  sources.append(source)
      return sorted(sources, key=lambda source: (source.name.casefold(), source.entity_id))


  @callback
  def async_resolve_ancs_source(
      hass: HomeAssistant,
      entity_unique_id: str,
      mqtt_device_identifier: str,
  ) -> AncsSource | None:
      entity_registry = er.async_get(hass)
      entity_id = entity_registry.async_get_entity_id(
          Platform.SENSOR,
          MQTT_DOMAIN,
          entity_unique_id,
      )
      if entity_id is None:
          return None
      entity_entry = entity_registry.async_get(entity_id)
      if entity_entry is None or entity_entry.device_id is None:
          return None
      device_entry = dr.async_get(hass).async_get(entity_entry.device_id)
      if device_entry is None:
          return None
      if (MQTT_DOMAIN, mqtt_device_identifier) not in device_entry.identifiers:
          return None
      return _source_from_entries(
          entity_entry,
          device_entry,
          mqtt_device_identifier,
      )
  ```

- [ ] **Step 6: Run the source tests and confirm GREEN**

  ```powershell
  uv run --python 3.14 --with-requirements requirements_test.txt python -m pytest tests/test_source.py -q
  ```

  Expected: all source discovery tests pass.

- [ ] **Step 7: Commit Task 1**

  ```powershell
  git add custom_components/ha_ios_ancs/const.py custom_components/ha_ios_ancs/source.py tests/conftest.py tests/helpers.py tests/test_source.py
  git -c user.name="1bobby-git" -c user.email="66291955+1bobby-git@users.noreply.github.com" commit -m "Discover the existing MQTT ANCS device" -m "Constraint: MQTT Discovery remains the owner of device and sensor entities." -m "Rejected: Derive devices from user-entered topics | Registry identifiers already provide a stable source." -m "Confidence: high" -m "Scope-risk: narrow" -m "Tested: pytest tests/test_source.py" -m "Not-tested: Config flow and runtime consumption."
  ```

## Task 2: Replace new-entry topic input with device selection

**Files:**

- Modify: `custom_components/ha_ios_ancs/config_flow.py`
- Modify: `custom_components/ha_ios_ancs/translations/en.json`
- Modify: `custom_components/ha_ios_ancs/translations/ko.json`
- Create: `custom_components/ha_ios_ancs/strings.json`
- Modify: `tests/test_config_flow.py`

- [ ] **Step 1: Replace manual-topic config-flow tests with registry-backed cases**

  Remove assertions that the user form requires `base_topic`. Keep the `normalize_base_topic` unit tests because legacy entries still use direct MQTT. Add these config-flow tests:

  ```python
  def test_user_step_auto_creates_entry_for_one_mqtt_ancs_device(
      registry_hass: HomeAssistant, run
  ) -> None:
      hass = registry_hass
      registered = run(
          async_register_mqtt_ancs_source(
              hass,
              "ios_ancs_A1B2C3",
              device_name="Kitchen iPhone Relay",
          )
      )
      with (
          patch.object(
              hass.config_entries,
              "async_setup",
              new=AsyncMock(return_value=True),
          ),
          patch(
              "custom_components.ha_ios_ancs.config_flow._async_mqtt_available",
              new=AsyncMock(return_value=True),
          ),
      ):
          result = run(
              hass.config_entries.flow.async_init(
                  DOMAIN,
                  context={"source": config_entries.SOURCE_USER},
              )
          )

      assert result["type"] is FlowResultType.CREATE_ENTRY
      assert result["title"] == "Kitchen iPhone Relay"
      assert result["data"] == {
          CONF_SOURCE_ENTITY_UNIQUE_ID: registered.entity.unique_id,
          CONF_MQTT_DEVICE_IDENTIFIER: "ios_ancs_A1B2C3",
      }


  def test_user_step_shows_device_selector_for_multiple_sources(
      registry_hass: HomeAssistant, run
  ) -> None:
      hass = registry_hass
      first = run(
          async_register_mqtt_ancs_source(
              hass,
              "ios_ancs_A1B2C3",
              device_name="Kitchen Relay",
          )
      )
      second = run(
          async_register_mqtt_ancs_source(
              hass,
              "ios_ancs_D4E5F6",
              device_name="Office Relay",
          )
      )
      with (
          patch.object(
              hass.config_entries,
              "async_setup",
              new=AsyncMock(return_value=True),
          ),
          patch(
              "custom_components.ha_ios_ancs.config_flow._async_mqtt_available",
              new=AsyncMock(return_value=True),
          ),
      ):
          form = run(
              hass.config_entries.flow.async_init(
                  DOMAIN,
                  context={"source": config_entries.SOURCE_USER},
              )
          )
          result = run(
              hass.config_entries.flow.async_configure(
                  form["flow_id"],
                  {CONF_SOURCE_ENTITY_UNIQUE_ID: second.entity.unique_id},
              )
          )

      assert form["type"] is FlowResultType.FORM
      assert form["step_id"] == "user"
      assert CONF_SOURCE_ENTITY_UNIQUE_ID in form["data_schema"].schema
      assert result["type"] is FlowResultType.CREATE_ENTRY
      assert result["data"] == {
          CONF_SOURCE_ENTITY_UNIQUE_ID: second.entity.unique_id,
          CONF_MQTT_DEVICE_IDENTIFIER: "ios_ancs_D4E5F6",
      }
      assert first.entity.unique_id != second.entity.unique_id


  def test_user_step_aborts_when_no_compatible_device_exists(
      registry_hass: HomeAssistant, run
  ) -> None:
      hass = registry_hass
      with patch(
          "custom_components.ha_ios_ancs.config_flow._async_mqtt_available",
          new=AsyncMock(return_value=True),
      ):
          result = run(
              hass.config_entries.flow.async_init(
                  DOMAIN,
                  context={"source": config_entries.SOURCE_USER},
              )
          )

      assert result["type"] is FlowResultType.ABORT
      assert result["reason"] == "no_devices_found"


  def test_user_step_aborts_when_mqtt_is_unavailable(
      registry_hass: HomeAssistant, run
  ) -> None:
      hass = registry_hass
      with patch(
          "custom_components.ha_ios_ancs.config_flow._async_mqtt_available",
          new=AsyncMock(return_value=False),
      ):
          result = run(
              hass.config_entries.flow.async_init(
                  DOMAIN,
                  context={"source": config_entries.SOURCE_USER},
              )
          )

      assert result["type"] is FlowResultType.ABORT
      assert result["reason"] == "mqtt_unavailable"
  ```

  Also add a duplicate test that preloads an HA iOS ANCS entry whose `unique_id` is the MQTT device identifier, then expects `already_configured`.

- [ ] **Step 2: Run config-flow tests and confirm RED**

  ```powershell
  uv run --python 3.14 --with-requirements requirements_test.txt python -m pytest tests/test_config_flow.py -q
  ```

  Expected: new source constants and device-driven flow assertions fail against the topic form.

- [ ] **Step 3: Implement device-driven user setup**

  Replace the user-step topic form in `config_flow.py` with:

  ```python
  from homeassistant.helpers import selector

  from .const import (
      CONF_MQTT_DEVICE_IDENTIFIER,
      CONF_SOURCE_ENTITY_UNIQUE_ID,
      DOMAIN,
  )
  from .source import AncsSource, async_discover_ancs_sources


  def _source_data(source: AncsSource) -> dict[str, str]:
      return {
          CONF_SOURCE_ENTITY_UNIQUE_ID: source.entity_unique_id,
          CONF_MQTT_DEVICE_IDENTIFIER: source.mqtt_device_identifier,
      }


  def _source_schema(sources: list[AncsSource]) -> vol.Schema:
      options = [
          {
              "value": source.entity_unique_id,
              "label": f"{source.name} ({source.mqtt_device_identifier})",
          }
          for source in sources
      ]
      return vol.Schema(
          {
              vol.Required(CONF_SOURCE_ENTITY_UNIQUE_ID): selector.SelectSelector(
                  selector.SelectSelectorConfig(
                      options=options,
                      mode=selector.SelectSelectorMode.DROPDOWN,
                  )
              )
          }
      )
  ```

  The `async_step_user` method must execute in this order:

  1. Await `_async_mqtt_available`; abort with `mqtt_unavailable` when false.
  2. Call `async_discover_ancs_sources` on every entry or submission so the list cannot go stale.
  3. Abort with `no_devices_found` when the result is empty.
  4. When there is exactly one source and `user_input is None`, create it without showing a form.
  5. For multiple sources, show `_source_schema`; if the submitted unique ID is no longer discoverable, abort with `no_devices_found` without creating an entry.
  6. Call `await self.async_set_unique_id(source.mqtt_device_identifier)` and `_abort_if_unique_id_configured()` before creation.
  7. Create the entry with `title=source.name` and `_source_data(source)`.

- [ ] **Step 4: Update config strings without topic fields**

  Create `strings.json` as the English source of truth, and make `translations/en.json` match it. Use this config block:

  ```json
  {
    "title": "HA iOS ANCS",
    "config": {
      "step": {
        "user": {
          "description": "Select the existing MQTT-discovered HA iOS ANCS device.",
          "data": {
            "source_entity_unique_id": "MQTT device"
          }
        },
        "reconfigure": {
          "description": "Select the MQTT-discovered device for this HA iOS ANCS entry.",
          "data": {
            "source_entity_unique_id": "MQTT device"
          }
        }
      },
      "abort": {
        "already_configured": "This HA iOS ANCS MQTT device is already configured.",
        "mqtt_unavailable": "Set up the Home Assistant MQTT integration before adding HA iOS ANCS.",
        "no_devices_found": "No compatible MQTT-discovered HA iOS ANCS device was found.",
        "reconfigure_successful": "The HA iOS ANCS device was updated."
      }
    },
    "entity": {
      "event": {
        "notification": {
          "name": "Notification"
        }
      }
    }
  }
  ```

  Make `translations/ko.json` structurally identical with these Korean values. Save and read all three files as UTF-8 so the exact Hangul below is preserved:

  - User description: `기존 MQTT 검색으로 등록된 HA iOS ANCS 기기를 선택하세요.`
  - Reconfigure description: `이 HA iOS ANCS 항목에 연결할 MQTT 검색 기기를 선택하세요.`
  - Field: `MQTT 기기`
  - Already configured: `이 HA iOS ANCS MQTT 기기는 이미 설정되어 있습니다.`
  - MQTT unavailable: `HA iOS ANCS를 추가하기 전에 Home Assistant MQTT 통합을 설정하세요.`
  - No device: `호환되는 MQTT 검색 HA iOS ANCS 기기를 찾지 못했습니다.`
  - Reconfigure success: `HA iOS ANCS 기기를 변경했습니다.`
  - Event entity: `알림`

- [ ] **Step 5: Run config-flow tests and confirm GREEN**

  ```powershell
  uv run --python 3.14 --with-requirements requirements_test.txt python -m pytest tests/test_config_flow.py -q
  ```

  Expected: single-device, multi-device, no-device, unavailable-MQTT, duplicate, and legacy normalization tests pass.

- [ ] **Step 6: Commit Task 2**

  ```powershell
  git add custom_components/ha_ios_ancs/config_flow.py custom_components/ha_ios_ancs/strings.json custom_components/ha_ios_ancs/translations/en.json custom_components/ha_ios_ancs/translations/ko.json tests/test_config_flow.py
  git -c user.name="1bobby-git" -c user.email="66291955+1bobby-git@users.noreply.github.com" commit -m "Register ANCS from its MQTT device" -m "Constraint: New setup must not expose MQTT topic internals." -m "Rejected: Keep base_topic as an advanced field | The discovered registry already identifies the source." -m "Confidence: high" -m "Scope-risk: moderate" -m "Tested: pytest tests/test_config_flow.py" -m "Not-tested: Legacy reconfiguration and event delivery."
  ```

## Task 3: Add explicit legacy reconfiguration without duplicate entities

**Files:**

- Modify: `custom_components/ha_ios_ancs/config_flow.py`
- Modify: `tests/test_config_flow.py`

- [ ] **Step 1: Write failing reconfigure tests**

  Add a test that registers one source, adds a legacy entry with `data={CONF_BASE_TOPIC: "ios_ancs/legacy"}`, and pre-creates the legacy event registry entity with unique ID `ios_ancs/legacy:notification`. Start `SOURCE_RECONFIGURE`, assert a form is shown even for one source, submit the source unique ID, and assert:

  ```python
  assert result["type"] is FlowResultType.ABORT
  assert result["reason"] == "reconfigure_successful"
  assert legacy_entry.data == {
      CONF_SOURCE_ENTITY_UNIQUE_ID: registered.entity.unique_id,
      CONF_MQTT_DEVICE_IDENTIFIER: "ios_ancs_A1B2C3",
  }
  assert legacy_entry.unique_id == "ios_ancs_A1B2C3"
  assert legacy_entry.title == "Kitchen iPhone Relay"
  migrated = er.async_get(hass).async_get(legacy_event_entity_id)
  assert migrated is not None
  assert migrated.unique_id == "ios_ancs_A1B2C3:notification"
  assert migrated.device_id == registered.device.id
  ```

  Add a second test with another HA iOS ANCS entry already using `unique_id="ios_ancs_A1B2C3"`; selecting that source must abort with `already_configured` and leave the legacy entry data and event unique ID unchanged.

- [ ] **Step 2: Run the reconfigure tests and confirm RED**

  ```powershell
  uv run --python 3.14 --with-requirements requirements_test.txt python -m pytest tests/test_config_flow.py -k reconfigure -q
  ```

  Expected: `async_step_reconfigure` is absent.

- [ ] **Step 3: Implement explicit reconfiguration**

  Add `async_step_reconfigure` that always shows the selector before modifying a legacy entry. On submission:

  1. Re-discover current sources and validate the selected unique ID.
  2. Reject any other config entry using the chosen MQTT device identifier.
  3. Look up the current event entity with `entity_registry.async_get_entity_id(Platform.EVENT, DOMAIN, f"{base_topic}:notification")`.
  4. If present, update it with `new_unique_id=f"{source.mqtt_device_identifier}:notification"` and `device_id=source.device_id` so reload reuses the existing MQTT device association.
  5. Replace the config entry data, unique ID, and title atomically through:

  ```python
  return self.async_update_reload_and_abort(
      entry,
      data=_source_data(source),
      unique_id=source.mqtt_device_identifier,
      title=source.name,
      reason="reconfigure_successful",
  )
  ```

  Do not migrate a legacy entry from `async_setup_entry` and do not auto-submit the reconfigure flow when only one source exists.

- [ ] **Step 4: Run the entire config-flow file and confirm GREEN**

  ```powershell
  uv run --python 3.14 --with-requirements requirements_test.txt python -m pytest tests/test_config_flow.py -q
  ```

- [ ] **Step 5: Commit Task 3**

  ```powershell
  git add custom_components/ha_ios_ancs/config_flow.py tests/test_config_flow.py
  git -c user.name="1bobby-git" -c user.email="66291955+1bobby-git@users.noreply.github.com" commit -m "Make legacy ANCS conversion explicit" -m "Constraint: A legacy topic cannot prove which discovered device it belongs to." -m "Rejected: Bind a legacy entry to the only candidate | That can redirect a working configuration." -m "Confidence: high" -m "Scope-risk: narrow" -m "Directive: Preserve event registry identity while replacing legacy config data." -m "Tested: pytest tests/test_config_flow.py" -m "Not-tested: Runtime startup with converted data."
  ```

## Task 4: Reuse notification validation for sensor attributes

**Files:**

- Modify: `custom_components/ha_ios_ancs/notification.py`
- Modify: `tests/test_notification.py`

- [ ] **Step 1: Add failing mapping-parser tests**

  Import `parse_notification_data` and test that a mapping payload is copied, accepted relay IDs enter the window, and rejected relay IDs do not. Use the existing `payload()` helper:

  ```python
  def test_parse_notification_data_accepts_mapping_and_copies() -> None:
      seen = RelayIdWindow()
      original = payload(extra={"nested": True})

      parsed = parse_notification_data(original, seen)

      assert parsed == original
      assert parsed is not original
      assert "relay-1" in seen


  def test_parse_notification_data_rejected_value_does_not_consume_id() -> None:
      seen = RelayIdWindow()

      assert parse_notification_data(payload(complete=False), seen) is None
      assert parse_notification_data(payload(), seen) is not None
  ```

- [ ] **Step 2: Run notification tests and confirm RED**

  ```powershell
  uv run --python 3.14 --with-requirements requirements_test.txt python -m pytest tests/test_notification.py -q
  ```

  Expected: import fails because `parse_notification_data` is absent.

- [ ] **Step 3: Extract the mapping validator**

  Implement:

  ```python
  def parse_notification_data(
      data: Mapping[str, Any],
      seen: RelayIdWindow,
  ) -> dict[str, Any] | None:
      relay_id = data.get("relay_id")
      if not isinstance(relay_id, str) or not relay_id.strip():
          return None
      if data.get("complete") is not True:
          return None
      if data.get("pre_existing") is True:
          return None
      if data.get("event") == "removed":
          return None
      if data.get("app_id") == HA_ECHO_APP_ID:
          return None
      if relay_id in seen:
          return None
      seen.add(relay_id)
      return dict(data)
  ```

  Keep JSON and UTF-8 decoding in `parse_notification`, then return `parse_notification_data(data, seen)` after the existing `Mapping` check.

- [ ] **Step 4: Run notification tests and confirm GREEN**

  ```powershell
  uv run --python 3.14 --with-requirements requirements_test.txt python -m pytest tests/test_notification.py -q
  ```

- [ ] **Step 5: Commit Task 4**

  ```powershell
  git add custom_components/ha_ios_ancs/notification.py tests/test_notification.py
  git -c user.name="1bobby-git" -c user.email="66291955+1bobby-git@users.noreply.github.com" commit -m "Validate ANCS sensor attributes consistently" -m "Constraint: Raw MQTT and MQTT sensor states must share one filter contract." -m "Rejected: Duplicate the filters in the source runtime | Divergent filters would reintroduce missing or repeated events." -m "Confidence: high" -m "Scope-risk: narrow" -m "Tested: pytest tests/test_notification.py" -m "Not-tested: Home Assistant state-change delivery."
  ```

## Task 5: Consume the existing MQTT sensor without replaying startup state

**Files:**

- Modify: `custom_components/ha_ios_ancs/runtime.py`
- Modify: `tests/test_runtime.py`

- [ ] **Step 1: Add source-runtime tests with a complete firmware payload**

  Define this fixture in `tests/test_runtime.py` so the integration contract matches firmware output:

  ```python
  def firmware_notification(**overrides: object) -> dict[str, object]:
      data: dict[str, object] = {
          "schema_version": 1,
          "target": "esp32c6",
          "source": "esp32c6_ancs",
          "relay_id": "boot1-1-42-aabbcc",
          "device_name": "IOS-ANCS-C6-AB12",
          "session_id": 1,
          "event": "added",
          "event_id": 0,
          "uid": 42,
          "app_id": "com.example.chat",
          "title": "Private title",
          "subtitle": "",
          "message": "Private message",
          "complete": True,
          "pre_existing": False,
          "published_at_ms": 123456,
      }
      data.update(overrides)
      return data
  ```

  Add tests that prove:

  - setup resolves a renamed entity ID from the stored unique ID;
  - an already-present valid state passes through `parse_notification_data`, seeds the relay-ID window, but calls no notification listener;
  - an already-present rejected state with `complete=False`, `pre_existing=True`, `event="removed"`, or the Home Assistant echo app ID does not consume its relay ID, so a later valid update with the same ID emits once;
  - a later new state emits the full firmware attribute mapping with `friendly_name` removed;
  - missing `relay_id` in attributes falls back to the sensor state string;
  - `unknown`, `unavailable`, and removed source states set availability false without notification;
  - restoring the same relay ID does not emit, while a new relay ID after restore does;
  - incomplete, pre-existing, removed, Home Assistant echo, and duplicate values are independently rejected;
  - `async_stop` removes only the state listener and does not remove the MQTT entity state or registry entry;
  - a missing registry source raises `ConfigEntryNotReady` containing the missing unique ID.

  Use a parameterized startup-rejection regression test with these recovery pairs:

  ```python
  @pytest.mark.parametrize(
      ("rejected", "recovered"),
      [
          ({"complete": False}, {"complete": True}),
          ({"pre_existing": True}, {"pre_existing": False}),
          ({"event": "removed"}, {"event": "added"}),
          (
              {"app_id": HA_ECHO_APP_ID},
              {"app_id": "com.example.chat"},
          ),
      ],
  )
  def test_source_runtime_rejected_startup_state_does_not_consume_relay_id(
      registry_hass: HomeAssistant,
      run,
      rejected: dict[str, object],
      recovered: dict[str, object],
  ) -> None:
      hass = registry_hass
      registered = run(
          async_register_mqtt_ancs_source(
              hass,
              "ios_ancs_A1B2C3",
              device_name="Kitchen Relay",
          )
      )
      hass.states.async_set(
          registered.entity.entity_id,
          "boot1-1-42-aabbcc",
          firmware_notification(**rejected),
      )
      runtime = AncsSourceRuntime(
          hass,
          registered.entity.unique_id,
          "ios_ancs_A1B2C3",
      )
      notifications: list[dict[str, Any]] = []
      runtime.async_add_notification_listener(notifications.append)

      run(runtime.async_start())
      assert notifications == []

      hass.states.async_set(
          registered.entity.entity_id,
          "boot1-1-42-aabbcc",
          firmware_notification(**recovered),
      )
      run(hass.async_block_till_done())

      assert notifications == [firmware_notification(**recovered)]
  ```

- [ ] **Step 2: Run focused source-runtime tests and confirm RED**

  ```powershell
  uv run --python 3.14 --with-requirements requirements_test.txt python -m pytest tests/test_runtime.py -k source -q
  ```

  Expected: `AncsSourceRuntime` does not exist.

- [ ] **Step 3: Define the shared runtime contract**

  In `runtime.py`, add an `AncsRuntime` protocol exposing:

  ```python
  class AncsRuntime(Protocol):
      @property
      def available(self) -> bool | None:
          raise NotImplementedError

      @property
      def unique_id(self) -> str:
          raise NotImplementedError

      @property
      def device_entry(self) -> dr.DeviceEntry | None:
          raise NotImplementedError

      async def async_start(self) -> None:
          raise NotImplementedError

      async def async_stop(self) -> None:
          raise NotImplementedError

      def async_add_notification_listener(
          self,
          listener: NotificationListener,
      ) -> CALLBACK_TYPE:
          raise NotImplementedError

      def async_add_availability_listener(
          self,
          listener: AvailabilityListener,
      ) -> CALLBACK_TYPE:
          raise NotImplementedError
  ```

  Add to `AncsMqttRuntime`:

  ```python
  @property
  def unique_id(self) -> str:
      return f"{self._base_topic}:notification"

  @property
  def device_entry(self) -> dr.DeviceEntry | None:
      return None
  ```

- [ ] **Step 4: Implement `AncsSourceRuntime`**

  Constructor inputs are `hass`, `source_entity_unique_id`, and `mqtt_device_identifier`. The runtime must:

  - resolve through `async_resolve_ancs_source` during `async_start`;
  - raise `ConfigEntryNotReady` with the unique ID when resolution fails;
  - expose `unique_id` as `<mqtt_device_identifier>:notification`;
  - expose the resolved MQTT `DeviceEntry` through `device_entry`;
  - read the current source state once, normalize it exactly like a callback state, pass it through `parse_notification_data`, discard the returned notification instead of calling listeners, and thereby seed only an accepted current relay ID;
  - register `async_track_state_change_event` for the resolved entity ID;
  - treat absent, `unknown`, and `unavailable` states as unavailable;
  - copy `new_state.attributes`, remove `ATTR_FRIENDLY_NAME`, and set `relay_id` from `new_state.state` only when the attribute is missing;
  - pass the mapping to `parse_notification_data` and notify listeners only for accepted data;
  - make `async_start` and `async_stop` idempotent;
  - clear integration listeners on stop while leaving MQTT state and registries untouched.

  Seed startup state without dispatch using this exact ordering, with no `await` between the state read and listener registration:

  ```python
  current_state = self._hass.states.get(source.entity_id)
  if current_state is None or current_state.state in (
      STATE_UNKNOWN,
      STATE_UNAVAILABLE,
  ):
      self._set_available(False)
  else:
      self._set_available(True)
      parse_notification_data(
          self._notification_data_from_state(current_state),
          self._seen,
      )
  self._unsubscribe = async_track_state_change_event(
      self._hass,
      source.entity_id,
      self._handle_source_state_change,
  )
  ```

  Use this callback shape:

  ```python
  @staticmethod
  def _notification_data_from_state(state: State) -> dict[str, Any]:
      data = dict(state.attributes)
      data.pop(ATTR_FRIENDLY_NAME, None)
      relay_id = data.get("relay_id")
      if not isinstance(relay_id, str) or not relay_id.strip():
          data["relay_id"] = state.state
      return data


  @callback
  def _handle_source_state_change(
      self,
      event: Event[EventStateChangedData],
  ) -> None:
      new_state = event.data["new_state"]
      if new_state is None or new_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
          self._set_available(False)
          return

      self._set_available(True)
      data = self._notification_data_from_state(new_state)
      notification = parse_notification_data(data, self._seen)
      if notification is None:
          return
      for listener in tuple(self._notification_listeners):
          listener(notification)
  ```

- [ ] **Step 5: Run all runtime and parser tests and confirm GREEN**

  ```powershell
  uv run --python 3.14 --with-requirements requirements_test.txt python -m pytest tests/test_runtime.py tests/test_notification.py -q
  ```

- [ ] **Step 6: Commit Task 5**

  ```powershell
  git add custom_components/ha_ios_ancs/runtime.py tests/test_runtime.py
  git -c user.name="1bobby-git" -c user.email="66291955+1bobby-git@users.noreply.github.com" commit -m "Deliver ANCS events from the MQTT sensor" -m "Constraint: Retained sensor state must not replay as a new notification after startup." -m "Rejected: Subscribe to the notification topic twice | MQTT already owns and restores the source entity." -m "Confidence: high" -m "Scope-risk: moderate" -m "Directive: Seed relay identity before installing the state listener." -m "Tested: pytest tests/test_runtime.py tests/test_notification.py" -m "Not-tested: Event entity device attachment."
  ```

## Task 6: Select the runtime by config data and preserve legacy behavior

**Files:**

- Modify: `custom_components/ha_ios_ancs/__init__.py`
- Create: `tests/test_init.py`
- Modify: `tests/test_event.py`

- [ ] **Step 1: Move setup lifecycle tests into `tests/test_init.py` and add source cases**

  Preserve the existing lifecycle assertions from `tests/test_event.py` in the new file. Define both entry shapes explicitly:

  ```python
  def make_source_entry() -> ConfigEntry:
      return ConfigEntry(
          version=1,
          minor_version=1,
          domain=DOMAIN,
          title="Kitchen iPhone Relay",
          data={
              CONF_SOURCE_ENTITY_UNIQUE_ID: (
                  "ios_ancs_A1B2C3_last_notification"
              ),
              CONF_MQTT_DEVICE_IDENTIFIER: "ios_ancs_A1B2C3",
          },
          source="user",
          unique_id="ios_ancs_A1B2C3",
          discovery_keys=EMPTY_DISCOVERY_KEYS,
          options={},
          subentries_data={},
      )


  def make_legacy_entry() -> ConfigEntry:
      return ConfigEntry(
          version=1,
          minor_version=1,
          domain=DOMAIN,
          title="HA iOS ANCS (ios_ancs/legacy)",
          data={CONF_BASE_TOPIC: "ios_ancs/legacy"},
          source="user",
          unique_id="ios_ancs/legacy",
          discovery_keys=EMPTY_DISCOVERY_KEYS,
          options={},
          subentries_data={},
      )
  ```

  Then add:

  ```python
  def test_setup_entry_uses_source_runtime_for_device_data(
      hass: HomeAssistant, run
  ) -> None:
      entry = make_source_entry()
      with patch("custom_components.ha_ios_ancs.AncsSourceRuntime") as runtime_cls:
          runtime = runtime_cls.return_value
          runtime.async_start = AsyncMock()
          runtime.async_stop = AsyncMock()
          hass.config_entries.async_forward_entry_setups = AsyncMock()

          assert run(async_setup_entry(hass, entry)) is True

      runtime_cls.assert_called_once_with(
          hass,
          "ios_ancs_A1B2C3_last_notification",
          "ios_ancs_A1B2C3",
      )
      runtime.async_start.assert_awaited_once()
      assert entry.runtime_data is runtime


  def test_setup_entry_keeps_legacy_direct_mqtt_runtime(
      hass: HomeAssistant, run
  ) -> None:
      entry = make_legacy_entry()
      with patch("custom_components.ha_ios_ancs.AncsMqttRuntime") as runtime_cls:
          runtime = runtime_cls.return_value
          runtime.async_start = AsyncMock()
          runtime.async_stop = AsyncMock()
          hass.config_entries.async_forward_entry_setups = AsyncMock()

          assert run(async_setup_entry(hass, entry)) is True

      runtime_cls.assert_called_once_with(hass, "ios_ancs/legacy")
      runtime.async_start.assert_awaited_once()
  ```

  Keep tests that stop a started runtime after platform-forward failure, stop the runtime only after successful platform unload, retain the runtime when platform unload fails, and raise `ConfigEntryNotReady` when the selected source is missing.

- [ ] **Step 2: Run init tests and confirm RED**

  ```powershell
  uv run --python 3.14 --with-requirements requirements_test.txt python -m pytest tests/test_init.py -q
  ```

  Expected: source config data still indexes `CONF_BASE_TOPIC`.

- [ ] **Step 3: Branch setup by stored config shape**

  Implement one helper in `__init__.py`:

  ```python
  def _runtime_from_entry(hass: HomeAssistant, entry: ConfigEntry) -> AncsRuntime:
      if source_unique_id := entry.data.get(CONF_SOURCE_ENTITY_UNIQUE_ID):
          return AncsSourceRuntime(
              hass,
              source_unique_id,
              entry.data[CONF_MQTT_DEVICE_IDENTIFIER],
          )
      return AncsMqttRuntime(hass, entry.data[CONF_BASE_TOPIC])
  ```

  Keep the existing start, forward, cleanup-on-error, unload ordering, and config-entry-owned event-state removal.

- [ ] **Step 4: Run init and legacy event lifecycle tests and confirm GREEN**

  ```powershell
  uv run --python 3.14 --with-requirements requirements_test.txt python -m pytest tests/test_init.py tests/test_event.py -q
  ```

- [ ] **Step 5: Commit Task 6**

  ```powershell
  git add custom_components/ha_ios_ancs/__init__.py tests/test_init.py tests/test_event.py
  git -c user.name="1bobby-git" -c user.email="66291955+1bobby-git@users.noreply.github.com" commit -m "Keep legacy ANCS entries working during upgrade" -m "Constraint: Existing topic entries must remain loadable until explicit reconfiguration." -m "Rejected: Require immediate migration | Device correspondence is not provable from legacy data." -m "Confidence: high" -m "Scope-risk: moderate" -m "Tested: pytest tests/test_init.py tests/test_event.py" -m "Not-tested: Existing-device event registry attachment."
  ```

## Task 7: Attach the native event entity to the MQTT device

**Files:**

- Modify: `custom_components/ha_ios_ancs/event.py`
- Modify: `tests/test_event.py`

- [ ] **Step 1: Extend the runtime stub and write failing device tests**

  Give `RuntimeStub` explicit `unique_id` and `device_entry` values. Add a source-entry test that creates an MQTT device, sets the runtime's `device_entry`, sets up the event platform, and asserts:

  ```python
  registry_entry = entity_registry.async_get(hass).async_get(entity_id)
  assert registry_entry is not None
  assert registry_entry.unique_id == "ios_ancs_A1B2C3:notification"
  assert registry_entry.device_id == mqtt_device.id
  assert len(device_registry.async_get(hass).devices) == 1
  ```

  Add `test_reconfigured_legacy_event_reuses_registry_entry_on_mqtt_device`. It must set up the legacy event first, record its registry entry ID and legacy device ID, run the real reconfigure flow, unload and set up the event platform with the source runtime, then assert:

  ```python
  migrated = entity_registry.async_get(hass).async_get(entity_id)
  assert migrated is not None
  assert migrated.id == original_registry_entry_id
  assert migrated.unique_id == "ios_ancs_A1B2C3:notification"
  assert migrated.device_id == mqtt_device.id
  assert len(
      er.async_entries_for_config_entry(
          entity_registry.async_get(hass),
          entry.entry_id,
      )
  ) == 1
  assert not [
      item
      for item in er.async_entries_for_device(
          entity_registry.async_get(hass),
          legacy_device_id,
          include_disabled_entities=True,
      )
      if item.domain == Platform.EVENT
  ]
  ```

  The test intentionally requires the old integration-owned device to have no event entities, but does not delete the empty device registry record because it can contain user-assigned name or area metadata.

  Keep a legacy test asserting its unique ID remains `<base_topic>:notification` and its existing `DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})` behavior remains intact.

  Update the notification payload assertion to compare the complete firmware fixture, including `schema_version`, `target`, `source`, `relay_id`, `device_name`, `session_id`, `event`, `event_id`, `uid`, `app_id`, `title`, `subtitle`, `message`, `complete`, `pre_existing`, and `published_at_ms`.

- [ ] **Step 2: Run event tests and confirm RED**

  ```powershell
  uv run --python 3.14 --with-requirements requirements_test.txt python -m pytest tests/test_event.py -q
  ```

  Expected: the event entity still creates a separate integration device and derives its unique ID from `base_topic`.

- [ ] **Step 3: Consume the runtime identity in `event.py`**

  Type `entry.runtime_data` as `AncsRuntime`. Set `_attr_unique_id = runtime.unique_id`. Assign the public Home Assistant entity field directly, then set legacy `DeviceInfo` only when it is `None`:

  ```python
  self.device_entry = runtime.device_entry
  if self.device_entry is None:
      self._attr_device_info = DeviceInfo(
          identifiers={(DOMAIN, entry.entry_id)},
          name=entry.title,
      )
  ```

  `EntityPlatform` reads `entity.device_entry` when `device_info` is absent and records that device ID on the event registry entry. Do not create or update a `DeviceEntry` in the event platform.

- [ ] **Step 4: Run event and init tests and confirm GREEN**

  ```powershell
  uv run --python 3.14 --with-requirements requirements_test.txt python -m pytest tests/test_event.py tests/test_init.py -q
  ```

- [ ] **Step 5: Commit Task 7**

  ```powershell
  git add custom_components/ha_ios_ancs/event.py tests/test_event.py
  git -c user.name="1bobby-git" -c user.email="66291955+1bobby-git@users.noreply.github.com" commit -m "Place ANCS notifications on the MQTT device" -m "Constraint: MQTT Discovery owns the canonical device registry entry." -m "Rejected: Create a second HA iOS ANCS device | It splits one physical relay across two devices." -m "Confidence: high" -m "Scope-risk: narrow" -m "Tested: pytest tests/test_event.py tests/test_init.py" -m "Not-tested: Live Home Assistant UI rendering."
  ```

## Task 8: Document the new setup contract and bump the integration release

**Files:**

- Modify: `README.md`
- Modify: `README.en.md`
- Modify: `custom_components/ha_ios_ancs/manifest.json`
- Modify: `tools/tests/test_documentation_contract.py`
- Modify: `tests/test_config_flow.py`

- [ ] **Step 1: Add failing documentation and translation contract tests**

  Add assertions that:

  - `strings.json`, English translation, and Korean translation have identical config key structure;
  - no config-flow data block contains `base_topic`;
  - both README files state that adding HA iOS ANCS discovers the existing MQTT device automatically;
  - both README files explain that more than one relay produces a device selector;
  - both README files explain that existing manual-topic entries use Reconfigure to attach to a device;
  - the manifest version is `0.5.0`.

- [ ] **Step 2: Run contract tests and confirm RED**

  ```powershell
  uv run --python 3.14 --with-requirements requirements_test.txt python -m pytest tests/test_config_flow.py tools/tests/test_documentation_contract.py -q
  ```

- [ ] **Step 3: Update public documentation**

  In the Home Assistant and HACS section of both README files, document this exact behavior:

  - MQTT Discovery must already show the HA iOS ANCS relay device and `last_notification` sensor.
  - Adding the HACS integration no longer asks for an MQTT base topic.
  - One compatible device is selected automatically.
  - Multiple compatible devices are shown as device names in a selector.
  - The native `Notification` event entity is added to the existing MQTT device.
  - The event entity fires only for new complete notifications and does not replay retained startup state.
  - A legacy topic entry remains operational until the user chooses Reconfigure and selects its MQTT device.

  Keep examples general-purpose; do not add personal broker addresses, MAC addresses, SSIDs, ports, or entity IDs.

- [ ] **Step 4: Bump the manifest version**

  Change only:

  ```json
  "version": "0.5.0"
  ```

- [ ] **Step 5: Run documentation and config contract tests and confirm GREEN**

  ```powershell
  uv run --python 3.14 --with-requirements requirements_test.txt python -m pytest tests/test_config_flow.py tools/tests/test_documentation_contract.py -q
  ```

- [ ] **Step 6: Commit Task 8**

  ```powershell
  git add README.md README.en.md custom_components/ha_ios_ancs/manifest.json tests/test_config_flow.py tools/tests/test_documentation_contract.py
  git -c user.name="1bobby-git" -c user.email="66291955+1bobby-git@users.noreply.github.com" commit -m "Explain automatic ANCS device registration" -m "Constraint: Public setup instructions must match registry-backed behavior and remain general-purpose." -m "Rejected: Preserve topic-entry instructions | New entries no longer accept a topic." -m "Confidence: high" -m "Scope-risk: narrow" -m "Tested: pytest tests/test_config_flow.py tools/tests/test_documentation_contract.py" -m "Not-tested: Published HACS release rendering."
  ```

## Task 9: Run full verification and review the final diff

**Files:**

- Review: all files changed in Tasks 1 through 8
- Modify only if a verification failure proves a defect

- [ ] **Step 1: Run the integration test suite**

  ```powershell
  uv run --python 3.14 --with-requirements requirements_test.txt python -m pytest tests -q
  ```

  Expected: all tests pass; the five existing Home Assistant or aiohttp warnings may remain if their warning text is unchanged.

- [ ] **Step 2: Run firmware and documentation contract tests**

  ```powershell
  uv run --python 3.14 --with-requirements requirements_test.txt python -m pytest tools/tests -q
  ```

  Expected: all contract tests pass.

- [ ] **Step 3: Run static type checking**

  ```powershell
  uv run --python 3.14 --with-requirements requirements_test.txt --with basedpyright basedpyright custom_components\ha_ios_ancs tests --level error
  ```

  Expected: zero errors.

- [ ] **Step 4: Validate JSON and whitespace**

  ```powershell
  python -m json.tool custom_components\ha_ios_ancs\manifest.json > $null
  python -m json.tool custom_components\ha_ios_ancs\strings.json > $null
  python -m json.tool custom_components\ha_ios_ancs\translations\en.json > $null
  python -m json.tool custom_components\ha_ios_ancs\translations\ko.json > $null
  git diff --check origin/main...HEAD
  ```

  Expected: every command exits successfully with no diff-check output.

- [ ] **Step 5: Review invariants in the final diff**

  Confirm from `git diff origin/main...HEAD` that:

  - new entries contain no `base_topic`;
  - legacy entries still instantiate `AncsMqttRuntime`;
  - no setup path automatically migrates legacy entries;
  - the source runtime resolves by unique ID rather than stored entity ID;
  - startup seeds relay identity without triggering listeners;
  - event entities use the MQTT `DeviceEntry` and do not create a second device;
  - unload removes only integration listeners and states owned by the custom config entry;
  - no personal hardware or network values were introduced.

- [ ] **Step 6: Run the repository's hosted validators after push**

  Push only after local verification. Confirm the existing `.github/workflows/validate.yml` HACS and Hassfest jobs pass for the pushed commit. If remote credentials or GitHub Actions access are unavailable, report this as an external verification gap instead of claiming it passed.

- [ ] **Step 7: Record live-validation boundaries**

  Report separately:

  - verified locally: registry matching, config flow, reconfigure migration, state-to-event delivery, dedupe, availability, unload, docs, types, and contracts;
  - not verified without the user's running system: a real ESP32, paired iPhone ANCS delivery, broker traffic, and Home Assistant device-page rendering.
