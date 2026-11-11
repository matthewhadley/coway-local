"""Request a fresh state report from the fan."""

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory

from .entity import CowayEntity, setup_devices


async def async_setup_entry(hass, entry, async_add_entities):
    setup_devices(entry, async_add_entities, lambda service, serial: [Refresh(service, serial)])


class Refresh(CowayEntity, ButtonEntity):
    _attr_name = "Refresh status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, service, serial):
        super().__init__(service, serial, "refresh")

    async def async_press(self):
        try:
            await self.service.command(self.serial)
        except (ConnectionError, TimeoutError) as error:
            raise HomeAssistantError("The fan did not respond to the status query") from error
