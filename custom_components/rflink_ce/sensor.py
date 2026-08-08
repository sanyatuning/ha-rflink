"""Support for RFLink CE sensor devices."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import PERCENTAGE, UnitOfPressure, UnitOfSpeed, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ENTITY_DOMAIN,
    ENTITY_DOMAIN_SENSOR,
    EVENT_KEY_SENSOR,
    EVENT_KEY_VALUE,
    SIGNAL_NEW_DEVICE,
    SIGNAL_NEW_SENSOR_FIELD,
    SUBENTRY_TYPE_DEVICE,
)
from .entity import RflinkCeEntity
from .hub import RflinkCeConfigEntry

SENSOR_TYPES: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    SensorEntityDescription(
        key="humidity",
        translation_key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
    ),
    SensorEntityDescription(
        key="battery",
        translation_key="battery",
        icon="mdi:battery",
    ),
    SensorEntityDescription(
        key="barometric_pressure",
        translation_key="barometric_pressure",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.HPA,
    ),
    SensorEntityDescription(
        key="windspeed",
        translation_key="windspeed",
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
    ),
    SensorEntityDescription(
        key="update_time",
        translation_key="update_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

SENSOR_TYPES_BY_KEY = {description.key: description for description in SENSOR_TYPES}


def _coerce_value(field: str, value: Any) -> Any:
    """Convert a raw field value to what its device_class expects."""
    if field == "update_time":
        return dt_util.utc_from_timestamp(int(value))
    return value


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RflinkCeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up RFLink CE sensors, adding entities as new fields are observed."""

    @callback
    def _add_field(subentry: ConfigSubentry, event: dict[str, Any]) -> None:
        async_add_entities(
            [RflinkCeSensor(entry, subentry, event[EVENT_KEY_SENSOR], event)],
            config_subentry_id=subentry.subentry_id,
        )

    @callback
    def _on_new_device(subentry: ConfigSubentry) -> None:
        if (
            subentry.subentry_type == SUBENTRY_TYPE_DEVICE
            and subentry.data[CONF_ENTITY_DOMAIN] == ENTITY_DOMAIN_SENSOR
        ):
            entry.async_on_unload(
                async_dispatcher_connect(
                    hass,
                    SIGNAL_NEW_SENSOR_FIELD.format(subentry.subentry_id),
                    callback(lambda event: _add_field(subentry, event)),
                )
            )

    for subentry in entry.subentries.values():
        _on_new_device(subentry)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, SIGNAL_NEW_DEVICE.format(entry.entry_id), _on_new_device
        )
    )


class RflinkCeSensor(RflinkCeEntity, SensorEntity):
    """One measurement field reported by an RFLink CE Device classified as sensor."""

    def __init__(
        self,
        entry: RflinkCeConfigEntry,
        subentry: ConfigSubentry,
        field: str,
        initial_event: dict[str, Any],
    ) -> None:
        """Initialize the sensor for a single field of the Device."""
        super().__init__(entry, subentry, unique_id_suffix=f"_{field}")
        self._field = field
        if description := SENSOR_TYPES_BY_KEY.get(field):
            self.entity_description = description
        else:
            self._attr_translation_key = field
        self._attr_native_value = _coerce_value(field, initial_event[EVENT_KEY_VALUE])

    @property
    def event_type(self) -> str:
        """Sensors react to sensor readings, not remote commands."""
        return EVENT_KEY_SENSOR

    def _handle_event(self, event: dict[str, Any]) -> None:
        """Update this field's value from an incoming RF Signal."""
        if event[EVENT_KEY_SENSOR] == self._field:
            self._attr_native_value = _coerce_value(self._field, event[EVENT_KEY_VALUE])
