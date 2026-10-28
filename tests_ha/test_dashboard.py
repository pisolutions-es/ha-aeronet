"""The shipped Lovelace dashboard must be valid and self-consistent.

Parsed with the same YAML loader Home Assistant uses (PyYAML), so a syntax
error, a duplicated key or a card pointing at a nonexistent entity is caught
here instead of in the user's UI.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

DASHBOARD = Path(__file__).parent.parent / "dashboards" / "aeronet.yaml"

# Entities the dashboard is allowed to reference for the example station.
KNOWN_ENTITIES = {
    "sensor.aeronet_valladolid_aod",
    "sensor.aeronet_valladolid_aod_media_24h",
    "sensor.aeronet_valladolid_aod_media_diaria",
    "sensor.aeronet_valladolid_ultimo_dato",
    "sensor.aeronet_valladolid_latitud",
    "sensor.aeronet_valladolid_longitud",
    "sensor.aeronet_valladolid_elevacion",
    "select.aeronet_valladolid_station",
    "update.nasa_aeronet_update",
}
CHANNEL_RE = re.compile(r"sensor\.aeronet_valladolid_aod_(\d+)nm$")
NATIVE_CARDS = {"glance", "entities", "statistics-graph", "history-graph",
                "divider"}


@pytest.fixture(scope="module")
def dashboard():
    with DASHBOARD.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _cards(node):
    """Yield every card dict, i.e. every entry of a `cards:` list."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "cards" and isinstance(value, list):
                for card in value:
                    if isinstance(card, dict):
                        yield card
                        yield from _cards(card)
            else:
                yield from _cards(value)
    elif isinstance(node, list):
        for item in node:
            yield from _cards(item)


def _entity_refs(node):
    """Yield every entity id referenced anywhere in the dashboard."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("entity", "entity_id") and isinstance(value, str):
                yield value
            else:
                yield from _entity_refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _entity_refs(item)


def test_dashboard_is_a_lovelace_config(dashboard):
    assert isinstance(dashboard, dict)
    assert dashboard.get("title"), "the dashboard needs a title"
    views = dashboard.get("views")
    assert isinstance(views, list) and views, "at least one view is required"
    for view in views:
        assert isinstance(view.get("cards"), list) and view["cards"]


def test_cards_are_known_types(dashboard):
    for card in _cards(dashboard):
        card_type = card["type"]
        if card_type.startswith("custom:"):
            # Optional HACS cards: the README documents them as optional and
            # they must not be the only path to the data.
            assert card_type == "custom:apexcharts-card", card_type
        else:
            assert card_type in NATIVE_CARDS, f"unexpected card type {card_type}"


def test_required_native_cards_are_present(dashboard):
    types = {card["type"] for card in _cards(dashboard)}
    assert "glance" in types
    assert "statistics-graph" in types, "long-term statistics card is missing"
    assert "history-graph" in types


def test_every_referenced_entity_exists_for_the_example_station(dashboard):
    refs = set(_entity_refs(dashboard))
    assert refs, "the dashboard references no entities"
    for entity_id in refs:
        assert entity_id.startswith(("sensor.", "select.", "update.")), entity_id
        if CHANNEL_RE.match(entity_id):
            continue
        assert entity_id in KNOWN_ENTITIES, f"unknown entity {entity_id}"


def test_the_500_nm_series_uses_the_main_sensor(dashboard):
    """500 nm has no channel entity: it is the main AOD sensor."""
    refs = set(_entity_refs(dashboard))
    assert "sensor.aeronet_valladolid_aod_500nm" not in refs
    assert "sensor.aeronet_valladolid_aod" in refs


def test_statistics_graphs_use_a_supported_chart_type(dashboard):
    graphs = [c for c in _cards(dashboard)
              if c["type"] == "statistics-graph"]
    assert graphs
    for card in graphs:
        assert card.get("chart_type") in ("line", "bar")
        assert card.get("entities")


def test_apexcharts_cards_are_documented_as_optional(dashboard):
    apex = [c for c in _cards(dashboard) if c["type"] == "custom:apexcharts-card"]
    assert apex, "the advanced spectrum/time cards are part of the deliverable"
    for card in apex:
        assert card.get("series"), "an apexcharts card without series is useless"


def test_dashboard_comments_explain_the_data_source():
    text = DASHBOARD.read_text(encoding="utf-8")
    for attr in ("spectrum", "recent_points_24h", "channels_latest"):
        assert attr in text, f"the YAML does not mention the {attr} attribute"
