from __future__ import annotations

import asyncio
from collections.abc import Generator

import pytest

from homeassistant.config_entries import ConfigEntries
from homeassistant.core import HomeAssistant
from homeassistant import loader
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import DATA_COMPONENTS
from homeassistant.util.unit_system import METRIC_SYSTEM


@pytest.fixture
def event_loop() -> Generator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        yield loop
    finally:
        asyncio.set_event_loop(None)
        loop.close()


@pytest.fixture
def run(event_loop: asyncio.AbstractEventLoop):
    return event_loop.run_until_complete


@pytest.fixture
def hass(event_loop: asyncio.AbstractEventLoop, tmp_path) -> Generator[HomeAssistant]:
    async def make_hass() -> HomeAssistant:
        hass = HomeAssistant(str(tmp_path))
        hass.config.units = METRIC_SYSTEM
        loader.async_setup(hass)
        from custom_components.ha_ios_ancs import config_flow

        hass.data[DATA_COMPONENTS]["ha_ios_ancs.config_flow"] = config_flow
        hass.config_entries = ConfigEntries(hass, {})
        await hass.config_entries.async_initialize()
        await hass.async_start()
        return hass

    hass = event_loop.run_until_complete(make_hass())
    try:
        yield hass
    finally:
        event_loop.run_until_complete(hass.async_stop(force=True))


@pytest.fixture
def registry_hass(hass: HomeAssistant, run) -> HomeAssistant:
    dr.async_setup(hass)
    run(dr.async_load(hass, load_empty=True))
    run(er.async_get(hass).async_load(load_empty=True))
    return hass
