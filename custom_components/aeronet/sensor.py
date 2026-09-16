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

from .const import DOMAIN
from .coordinators import AeronetDataCoordinator
from .parsers import daily_series, latest_point, mean_last_24h, recent_points

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
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement="°",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="longitude",
        translation_key="longitude",
        device_class=SensorDeviceClass.DISTANCE,
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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coord: AeronetDataCoordinator = hass.data[DOMAIN][entry.entry_id]["data"]
    async_add_entities(
        AeronetSensor(coord, entry, description) for description in SENSORS
    )


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
        if data is None or self.entity_description.key != "aod":
            return None
        p = latest_point(data)
        return {
            "site": data.meta.name or self._coord.site,
            "wavelength": p.wavelength if p else None,
            "point_count": len(data.points),
            "daily_mean_aod": daily_series(data),
            "recent_points_24h": recent_points(data, hours=24),
        }
