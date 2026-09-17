"""Sensor platform for the NASA AERONET integration."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_PRODUCTS,
    DOMAIN,
    PRODUCT_AOD,
    PRODUCT_SDA,
    PRODUCT_SSA,
    PRODUCT_VOL,
)
from .coordinators import AeronetDataCoordinator
from .parsers import (
    SDA_COARSE_SLOT,
    SDA_FINE_SLOT,
    SSA_SLOT,
    VOL_SLOT,
    daily_series,
    latest_point,
    latest_value,
    last_days_series,
    mean_last_24h,
    recent_points,
    today_series,
    value_series,
)

_LOGGER = logging.getLogger(__name__)

# Primary wavelength used for the main AOD sensor: 500 nm (fallbacks
# 551/555/560 nm are chosen automatically per site; see README).
SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="aod",
        translation_key="aod",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="aod_24h",
        translation_key="aod_24h",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="last_data",
        translation_key="last_data",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="latitude",
        translation_key="latitude",
        # No device class: "°" is not a valid unit for any numeric device
        # class (HA logs "native unit ° is not a valid unit for device
        # class distance" otherwise). Plain degree values are still shown.
        native_unit_of_measurement="°",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="longitude",
        translation_key="longitude",
        native_unit_of_measurement="°",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="elevation",
        translation_key="elevation",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement="m",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

# Sensors created only when the matching product is enabled in config.
PRODUCT_SENSORS: dict[str, tuple[SensorEntityDescription, ...]] = {
    PRODUCT_AOD: (
        SensorEntityDescription(
            key="aod_daily",
            translation_key="aod_daily",
            state_class=SensorStateClass.MEASUREMENT,
        ),
    ),
    PRODUCT_SDA: (
        SensorEntityDescription(
            key="sda_fine",
            translation_key="sda_fine",
            state_class=SensorStateClass.MEASUREMENT,
        ),
        SensorEntityDescription(
            key="sda_coarse",
            translation_key="sda_coarse",
            state_class=SensorStateClass.MEASUREMENT,
        ),
    ),
    PRODUCT_SSA: (
        SensorEntityDescription(
            key="ssa",
            translation_key="ssa",
            state_class=SensorStateClass.MEASUREMENT,
        ),
    ),
    PRODUCT_VOL: (
        SensorEntityDescription(
            key="vol",
            translation_key="vol",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement="µm³/cm³",
        ),
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coord: AeronetDataCoordinator = hass.data[DOMAIN][entry.entry_id]["data"]
    entities = [
        AeronetSensor(coord, entry, description) for description in SENSORS
    ]
    products = (
        {**entry.data, **entry.options}.get(CONF_PRODUCTS)
        or [PRODUCT_AOD]
    )
    for product in products:
        for description in PRODUCT_SENSORS.get(product, ()):
            entities.append(AeronetSensor(coord, entry, description))
    async_add_entities(entities)


class AeronetSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coord: AeronetDataCoordinator,
        entry: ConfigEntry,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coord)
        self.entity_description = description
        self._coord = coord
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"AERONET · {coord.site}",
            manufacturer="NASA AERONET",
            configuration_url="https://aeronet.gsfc.nasa.gov/",
        )

    @property
    def available(self) -> bool:
        return bool(self._coord.last_update_success and self._coord.data is not None)

    @property
    def native_value(self) -> Any:
        data = self._coord.data
        key = self.entity_description.key
        if data is None:
            return None
        if key == "aod":
            p = latest_point(data)
            return round(p.aod, 4) if p else None
        if key == "aod_24h":
            return mean_last_24h(data)
        if key == "aod_daily":
            p = latest_value(data, "aod_daily", hours=26)
            return round(p.aod, 4) if p else None
        if key == "sda_fine":
            p = latest_value(data, SDA_FINE_SLOT, hours=24)
            return round(p.aod, 4) if p else None
        if key == "sda_coarse":
            p = latest_value(data, SDA_COARSE_SLOT, hours=24)
            return round(p.aod, 4) if p else None
        if key == "ssa":
            p = latest_value(data, SSA_SLOT, hours=26)
            return round(p.aod, 4) if p else None
        if key == "vol":
            p = latest_value(data, VOL_SLOT, hours=26)
            return round(p.aod, 6) if p else None
        if key == "last_data":
            if not data.points:
                return None
            return data.points[-1].time
        if key == "latitude":
            return data.meta.latitude if data.meta.latitude > -900 else None
        if key == "longitude":
            return data.meta.longitude if data.meta.longitude > -900 else None
        if key == "elevation":
            return data.meta.elevation if data.meta.elevation > -900 else None
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self._coord.data
        if data is None:
            return None
        key = self.entity_description.key
        if key == "aod":
            p = latest_point(data)
            return {
                "site": data.meta.name or self._coord.site,
                "wavelength": p.wavelength if p else None,
                "point_count": len(data.points),
                "daily_mean_aod": daily_series(data),
                "recent_points_24h": recent_points(data, hours=24),
                "today_series": today_series(data),
            }
        if key == "aod_daily":
            return {"daily_series_7d": last_days_series(data, "aod_daily")}
        if key in ("sda_fine", "sda_coarse"):
            slot = SDA_FINE_SLOT if key == "sda_fine" else SDA_COARSE_SLOT
            attrs = {
                f"{key}_series_24h": value_series(data, slot),
            }
            fractions = data.meta.extras.get("fine_mode_fraction")
            p = latest_value(data, SDA_FINE_SLOT, hours=24)
            if fractions and p is not None:
                attrs["fine_mode_fraction"] = fractions.get(p.time.isoformat())
            return attrs
        if key == "ssa":
            p = latest_value(data, SSA_SLOT, hours=26)
            return {"wavelength": p.wavelength if p else None}
        if key == "vol":
            p = latest_value(data, VOL_SLOT, hours=26)
            attrs: dict[str, Any] = {}
            if p is not None:
                attrs["column"] = p.wavelength
                day_points = [
                    q for q in (data.values.get(VOL_SLOT) or [])
                    if q.time.date() == p.time.date()
                ]
                if day_points:
                    mean = sum(q.aod for q in day_points) / len(day_points)
                    attrs["daily_mean"] = round(mean, 6)
            return attrs
        return None
