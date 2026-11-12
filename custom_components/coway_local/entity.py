"""Push-driven entities for each independently enrolled fan."""

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, MODEL


def setup_devices(entry, async_add_entities, factory):
    service = entry.runtime_data
    known = set()

    def changed(serial=None):
        # Forget removed fans, so one that is enrolled again gets entities again.
        known.intersection_update(service.devices)
        for device_id in service.devices:
            if device_id not in known:
                known.add(device_id)
                async_add_entities(factory(service, device_id))

    entry.async_on_unload(service.subscribe(changed))
    changed()


class CowayEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, service, serial, key):
        self.service = service
        self.serial = serial
        self._attr_unique_id = f"{serial}_{key}"

    @property
    def state_data(self):
        return self.service.states.get(self.serial)

    @property
    def available(self):
        return bool(self.service.started and self.state_data and self.state_data.online)

    @property
    def device_info(self):
        record = self.service.devices.get(self.serial, {})
        return DeviceInfo(
            identifiers={(DOMAIN, self.serial)},
            name=record.get("name", "Coway"),
            manufacturer="Coway",
            model=record.get("model", MODEL),
            sw_version=self.state_data.firmware if self.state_data else None,
        )

    async def async_added_to_hass(self):
        def updated(serial):
            if serial == self.serial:
                self.async_write_ha_state()

        self.async_on_remove(self.service.subscribe(updated))

    async def set_value(self, setting, selection):
        try:
            await self.service.set(self.serial, setting, selection)
        except (TimeoutError, ConnectionError, ValueError) as error:
            raise HomeAssistantError(f"Coway command failed: {error}") from error
