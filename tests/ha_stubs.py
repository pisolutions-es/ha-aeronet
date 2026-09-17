"""Minimal Home Assistant module stubs for importing the full package.

The host test env has no Home Assistant; these stand-ins are enough to
``import custom_components.aeronet`` (and its sensor/select platforms) so
unit tests can assert on module-level API surface (async_migrate_entry),
entity descriptions, and class attributes without a running HA.

Installation is additive: entries already provided by other test files'
lighter stubs are kept.
"""
from __future__ import annotations

import enum
import sys
import types


def _mod(name: str) -> types.ModuleType:
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    m = types.ModuleType(name)
    sys.modules[name] = m
    parent, _, leaf = name.rpartition(".")
    if parent and parent in sys.modules:
        setattr(sys.modules[parent], leaf, m)
    return m


def install() -> None:
    # voluptuous: schemas are never *called* by the tests we run here, only
    # referenced while building class bodies / module-level schemas.
    vol = _mod("voluptuous")
    if not hasattr(vol, "Schema"):
        class _Any:
            def __init__(self, *a, **k):
                pass

            def __call__(self, *a, **k):
                return None

        vol.Schema = lambda *a, **k: a[0] if a and len(a) == 1 else None
        vol.Optional = lambda *a, **k: _Any()
        vol.Required = lambda *a, **k: _Any()
        vol.In = lambda *a, **k: _Any()
        vol.All = lambda *a, **k: _Any()
        vol.Coerce = lambda *a, **k: _Any()
        vol.boolean = bool
        vol.string = str

    ha = _mod("homeassistant")

    core = _mod("homeassistant.core")
    if not hasattr(core, "HomeAssistant"):
        class HomeAssistant:
            def async_create_task(self, coro):
                coro.close()
        core.HomeAssistant = HomeAssistant
    if not hasattr(core, "callback"):
        core.callback = lambda func: func

    def _flow_result(*a, **k):
        return {"type": "done", "flow_id": "test", **k}

    flow = _mod("homeassistant.data_entry_flow")
    if not hasattr(flow, "FlowResult"):
        flow.FlowResult = dict
        flow.data_entry_flow = None  # type placeholder

    ce = _mod("homeassistant.config_entries")
    if not hasattr(ce, "ConfigEntry"):
        ce.ConfigEntry = type("ConfigEntry", (), {})
    if not hasattr(ce, "ConfigFlow"):
        class ConfigFlow:
            DOMAIN = None

            def __init_subclass__(cls, domain=None, **kw):
                super().__init_subclass__(**kw)
                cls.DOMAIN = domain

            hass = None

            async def async_set_unique_id(self, uid):
                pass

            def _abort_if_unique_id_configured(self):
                pass

            def async_create_entry(self, **kw):
                return _flow_result(**kw)

            def async_show_form(self, **kw):
                return _flow_result(**kw)

            def async_abort(self, **kw):
                return _flow_result(reason=kw.get("reason"), **kw)
        ce.ConfigFlow = ConfigFlow
    if not hasattr(ce, "OptionsFlow"):
        class OptionsFlow:
            def __init__(self, *a, **k):
                pass

            def async_show_form(self, **kw):
                return _flow_result(**kw)

            def async_create_entry(self, **kw):
                return _flow_result(**kw)
        ce.OptionsFlow = OptionsFlow
    if not hasattr(ce, "OptionsFlowWithConfigEntry"):
        ce.OptionsFlowWithConfigEntry = ce.OptionsFlow

    const = _mod("homeassistant.const")
    if not hasattr(const, "Platform"):
        class Platform(str, enum.Enum):
            SENSOR = "sensor"
            SELECT = "select"
        const.Platform = Platform
    if not hasattr(const, "EntityCategory"):
        class EntityCategory(str, enum.Enum):
            CONFIG = "config"
            DIAGNOSTIC = "diagnostic"
        const.EntityCategory = EntityCategory

    helpers = _mod("homeassistant.helpers")

    sel = _mod("homeassistant.helpers.selector")
    if not hasattr(sel, "SelectSelector"):
        class _Sel:
            def __init__(self, config=None, **kw):
                self.config = config

        sel.SelectSelector = sel.NumberSelector = sel.TextSelector = _Sel

        class _Cfg:
            def __init__(self, **kw):
                self.__dict__.update(kw)

        sel.SelectSelectorConfig = sel.NumberSelectorConfig = (
            sel.TextSelectorConfig
        ) = _Cfg

        sel.SelectSelectorMode = types.SimpleNamespace(
            DROPDOWN="dropdown", LIST="list"
        )
        sel.NumberSelectorMode = types.SimpleNamespace(BOX="box")
        sel.TextSelectorType = types.SimpleNamespace(EMAIL="email")

    aiohc = _mod("homeassistant.helpers.aiohttp_client")
    if not hasattr(aiohc, "async_get_clientsession"):
        aiohc.async_get_clientsession = lambda hass, *a, **k: None

    stor = _mod("homeassistant.helpers.storage")
    if not hasattr(stor, "Store"):
        class Store:
            def __init__(self, hass, version, key, private=False):
                self.key = key

            async def async_load(self):
                return None

            async def async_save(self, payload):
                pass
        stor.Store = Store

    upd = _mod("homeassistant.helpers.update_coordinator")
    if not hasattr(upd, "DataUpdateCoordinator"):
        class DataUpdateCoordinator:
            def __init__(self, hass, logger=None, name=None, update_interval=None):
                self.hass = hass
                self.data = None

            async def async_refresh(self):
                pass

        class UpdateFailed(Exception):
            pass

        class CoordinatorEntity:
            def __init__(self, coordinator=None):
                self.coordinator = coordinator

            def async_write_ha_state(self):
                pass

        upd.DataUpdateCoordinator = DataUpdateCoordinator
        upd.UpdateFailed = UpdateFailed
        upd.CoordinatorEntity = CoordinatorEntity

    devreg = _mod("homeassistant.helpers.device_registry")
    if not hasattr(devreg, "DeviceInfo"):
        devreg.DeviceEntryType = types.SimpleNamespace(SERVICE="service")
        devreg.DeviceInfo = lambda **kw: kw

    entplat = _mod("homeassistant.helpers.entity_platform")
    if not hasattr(entplat, "AddEntitiesCallback"):
        entplat.AddEntitiesCallback = list  # type alias stand-in

    comps = _mod("homeassistant.components")
    sensor_c = _mod("homeassistant.components.sensor")
    if not hasattr(sensor_c, "SensorDeviceClass"):
        class SensorDeviceClass(str, enum.Enum):
            DISTANCE = "distance"
            TIMESTAMP = "timestamp"
        class SensorStateClass(str, enum.Enum):
            MEASUREMENT = "measurement"
        class _Desc:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
            def __setattr__(self, k, v):  # frozen stand-in: allow in tests only
                object.__setattr__(self, k, v)
        class SensorEntity:
            entity_description = None

            def async_write_ha_state(self):
                pass
        sensor_c.SensorDeviceClass = SensorDeviceClass
        sensor_c.SensorStateClass = SensorStateClass
        sensor_c.SensorEntity = SensorEntity
        sensor_c.SensorEntityDescription = _Desc

    select_c = _mod("homeassistant.components.select")
    if not hasattr(select_c, "SelectEntity"):
        class SelectEntity:
            def async_write_ha_state(self):
                pass
        select_c.SelectEntity = SelectEntity

    aiohttp_mod = _mod("aiohttp")
    if not hasattr(aiohttp_mod, "ClientSession"):
        aiohttp_mod.ClientError = Exception
        aiohttp_mod.ClientSession = object
        aiohttp_mod.ClientTimeout = lambda **kw: None

    # HA's real SelectEntity marks options as unrecorded; mirror the base so
    # our explicit integration-side declaration can be tested against MRO.
    if "homeassistant.components.select" in sys.modules:
        SelectEntity = select_c.SelectEntity
        if not hasattr(SelectEntity, "_entity_component_unrecorded_attributes"):
            SelectEntity._entity_component_unrecorded_attributes = frozenset(
                {"options"}
            )
