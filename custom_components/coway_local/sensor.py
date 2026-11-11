"""Last reported MQTT message; no guessed air-quality or filter metrics."""

from datetime import UTC, datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.entity import EntityCategory

from .entity import CowayEntity, setup_devices


async def async_setup_entry(hass, entry, async_add_entities):
    setup_devices(entry, async_add_entities, lambda service, serial: [LastSeen(service, serial)])


class LastSeen(CowayEntity, SensorEntity):
    _attr_name = "Last seen"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, service, serial):
        super().__init__(service, serial, "last_seen")

    @property
    def available(self):
        return self.service.started

    @property
    def native_value(self):
        timestamp = self.state_data.last_seen if self.state_data else None
        return datetime.fromtimestamp(timestamp, UTC) if timestamp else None
