"""pytest harness for the *real* Home Assistant.

Run with: .venv-ha/bin/python -m pytest tests_ha -q

The unittest suite under tests/ keeps its own minimal HA stubs and is run
separately (.venv/bin/python -m unittest discover -s tests); it must never
be collected here, because importing tests/ha_stubs.py injects fake
homeassistant modules into sys.modules.
"""
import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/aeronet from the repo root."""
    yield
