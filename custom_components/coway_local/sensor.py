"""Device-reported measurements and an optional last-seen diagnostic."""

from datetime import UTC, datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import LIGHT_LUX, PERCENTAGE, UnitOfDensity
from homeassistant.helpers.entity import EntityCategory

from .entity import CowayEntity, setup_devices

SENSORS = (
    SensorEntityDescription(
        key="pm25",
        name="PM2.5",
        device_class=SensorDeviceClass.PM25,
        native_unit_of_measurement=UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="illuminance",
        name="Ambient light",
        device_class=SensorDeviceClass.ILLUMINANCE,
        native_unit_of_measurement=LIGHT_LUX,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="prefilter_remaining",
        name="Pre-filter remaining",
        icon="mdi:air-filter",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="max2_remaining",
        name="MAX2 filter remaining",
        icon="mdi:air-filter",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    setup_devices(
        entry,
        async_add_entities,
        lambda service, serial: [
            *(Measurement(service, serial, description) for description in SENSORS),
            LastSeen(service, serial),
        ],
    )


class Measurement(CowayEntity, SensorEntity):
    def __init__(self, service, serial, description):
        super().__init__(service, serial, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        state = self.state_data
        return state.telemetry.get(self.entity_description.key) if state else None


class LastSeen(CowayEntity, SensorEntity):
    _attr_name = "Last seen"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    # Every MQTT message changes this timestamp and creates an Activity entry.
    # Keep it available for troubleshooting without enabling that noise by default.
    _attr_entity_registry_enabled_default = False

    def __init__(self, service, serial):
        super().__init__(service, serial, "last_seen")

    @property
    def available(self):
        return self.service.started

    @property
    def native_value(self):
        timestamp = self.state_data.last_seen if self.state_data else None
        return datetime.fromtimestamp(timestamp, UTC) if timestamp else None
