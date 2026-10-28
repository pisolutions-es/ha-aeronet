"""Setup, statistics eligibility and entity surface against real HA.

These tests replace the "grep the source" style assertions with the real
thing: Home Assistant 2026.10.4 loads the integration, creates entities and
the produced state objects are inspected with HA's own rules.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from homeassistant.components.sensor import SensorStateClass
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
from homeassistant.helpers import entity_registry as er
from homeassistant.util.enum import try_parse_enum
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aeronet import coordinators, parsers
from custom_components.aeronet.const import (
    CONF_EMAIL,
    CONF_INTERVAL_MIN,
    CONF_LEVEL,
    CONF_PRODUCTS,
    CONF_SITE,
    DOMAIN,
    ENTRY_VERSION,
    PRODUCT_AOD,
    SITE_LIST_URL,
)

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8", errors="replace")


def _shift(data: parsers.AeronetData, now: dt.datetime) -> parsers.AeronetData:
    """Move a fixture payload so its newest point is 'now'.

    The fixtures are real AERONET payloads from a fixed date; the sensors
    apply a 24 h window, so an unshifted payload would be correctly reported
    as stale (unknown).
    """
    times = [p.time for p in data.points]
    if not times:
        return data
    delta = now - max(times)
    for point in data.points:
        point.time = point.time + delta
    for series in data.values.values():
        for point in series:
            point.time = point.time + delta
    return data


class FakeClient:
    """Offline stand-in for AeronetClient returning parsed fixtures."""

    def __init__(self, session=None, *, email="", level=""):
        self.email = email
        self.level = level

    async def fetch_site_list(self, url: str = SITE_LIST_URL):
        return parsers.parse_site_list(_fixture("site_list.txt"))

    async def fetch_data(self, site, now, *, days=7):
        data = parsers.parse_data_csv(
            _fixture("valladolid_aod_all.csv"),
            expected_site=site,
            channel_families=("aod",),
        )
        return _shift(data, now)

    async def fetch_daily(self, site, now, *, days=7):
        data = parsers.parse_data_csv(
            _fixture("valladolid_aod_daily.csv"),
            expected_site=site,
            column_sets={"aod_daily": ("AOD_500nm", "AOD_675nm")},
        )
        return _shift(data, now)

    async def fetch_sda(self, site, now, *, days=7):
        raise parsers.AeronetError("not configured in these tests")

    async def fetch_inversion(self, product, site, now, *, days=7):
        raise parsers.AeronetError("not configured in these tests")


@pytest.fixture
def fake_client(monkeypatch):
    monkeypatch.setattr(coordinators, "AeronetClient", FakeClient)
    return FakeClient


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        version=ENTRY_VERSION,
        title="AERONET · Valladolid",
        data={
            CONF_SITE: "Valladolid",
            CONF_EMAIL: "",
            CONF_LEVEL: "1.5",
            CONF_INTERVAL_MIN: 60,
            CONF_PRODUCTS: [PRODUCT_AOD],
        },
        entry_id="aeronet_test",
    )


async def _setup(hass) -> MockConfigEntry:
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


def _state_for(hass, entry, unique_suffix: str):
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{unique_suffix}"
    )
    assert entity_id is not None, f"no entity for unique_id {unique_suffix}"
    state = hass.states.get(entity_id)
    assert state is not None
    return state


async def test_setup_creates_sensors_with_values(hass, fake_client):
    entry = await _setup(hass)
    aod = _state_for(hass, entry, "aod")
    assert aod.state not in ("unknown", "unavailable")
    assert float(aod.state) > 0
    # The 500 nm main sensor carries the graph-ready attributes.
    assert "spectrum" in aod.attributes
    assert "recent_points_24h" in aod.attributes


async def test_every_measurement_sensor_is_statistics_eligible(hass, fake_client):
    """HA compiles long-term statistics for sensors whose state_class parses
    as a SensorStateClass (sensor/recorder.py::_get_sensor_states). Unitless
    AOD/SSA sensors are eligible; inventing a unit would break them."""
    entry = await _setup(hass)
    registry = er.async_get(hass)
    checked = 0
    for entry_entity in er.async_entries_for_config_entry(
        registry, entry.entry_id
    ):
        if entry_entity.domain != "sensor":
            continue
        state = hass.states.get(entry_entity.entity_id)
        assert state is not None
        state_class = state.attributes.get("state_class")
        if state_class is None:
            # timestamp / diagnostic sensors are not statistics candidates
            continue
        assert try_parse_enum(SensorStateClass, state_class) is not None, (
            f"{entry_entity.entity_id} has an unparseable state_class"
        )
        assert ATTR_UNIT_OF_MEASUREMENT not in state.attributes, (
            f"{entry_entity.entity_id} must not declare a unit "
            "(AOD is dimensionless)"
        )
        checked += 1
    assert checked >= 8, f"only {checked} statistics-eligible sensors found"


async def test_channel_entities_are_created_and_numeric(hass, fake_client):
    entry = await _setup(hass)
    registry = er.async_get(hass)
    channels = [
        e for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.unique_id.startswith(f"{entry.entry_id}_aod_")
    ]
    assert channels, "no wavelength channel entities were created"
    for entry_entity in channels:
        state = hass.states.get(entry_entity.entity_id)
        assert state is not None
        assert state.state not in ("unknown", "unavailable")


async def test_select_entity_exposes_stations(hass, fake_client):
    entry = await _setup(hass)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "select", DOMAIN, f"{entry.entry_id}_site"
    )
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    options = state.attributes.get("options") or []
    assert options, "the station dropdown is empty"
    assert any("Valladolid" in name for name in options)


async def test_unload_stops_the_coordinator(hass, fake_client):
    entry = await _setup(hass)
    coord = hass.data[DOMAIN][entry.entry_id]["data"]
    assert coord._unsub_refresh is not None, "the poll timer was never armed"
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    # v0.7.0 (review M3): without async_shutdown on unload the coordinator
    # kept polling NASA forever, one ghost timer per unload/reload cycle.
    assert coord._unsub_refresh is None


async def test_entity_ids_stay_stable(hass, fake_client):
    """Compatibility guard: the published entity_ids must not move.

    The station is Valladolid and the install is Spanish, so these are the
    exact ids already published by 0.6.0.
    """
    hass.config.language = "es"
    await _setup(hass)
    for entity_id in (
        "sensor.aeronet_valladolid_aod",
        "sensor.aeronet_valladolid_aod_media_24h",
        "sensor.aeronet_valladolid_aod_media_diaria",
        "sensor.aeronet_valladolid_ultimo_dato",
        "sensor.aeronet_valladolid_aod_440nm",
    ):
        assert hass.states.get(entity_id) is not None, f"{entity_id} disappeared"
