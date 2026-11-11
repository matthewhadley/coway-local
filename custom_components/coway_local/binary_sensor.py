"""Broker connection availability."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.helpers.entity import EntityCategory

from .entity import CowayEntity, setup_devices


async def async_setup_entry(hass, entry, async_add_entities):
    setup_devices(entry, async_add_entities, lambda service, serial: [Connection(service, serial)])


class Connection(CowayEntity, BinarySensorEntity):
    _attr_name = "Connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, service, serial):
        super().__init__(service, serial, "connection")

    @property
    def available(self):
        return self.service.started

    @property
    def is_on(self):
        return bool(self.state_data and self.state_data.online)
