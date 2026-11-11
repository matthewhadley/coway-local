"""The additional settings captured from the original app."""

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import EntityCategory

from .const import SETTINGS
from .entity import CowayEntity, setup_devices

LABELS = {
    "timer": "Timer",
    "lighting": "Lighting level",
    "sensitivity": "Smart mode sensitivity",
    "prefilter_cycle": "Pre-filter cleaning cycle",
}


async def async_setup_entry(hass, entry, async_add_entities):
    setup_devices(
        entry,
        async_add_entities,
        lambda service, serial: [CowaySelect(service, serial, key) for key in LABELS],
    )


class CowaySelect(CowayEntity, SelectEntity):
    def __init__(self, service, serial, key):
        super().__init__(service, serial, key)
        self.key = key
        self._attr_name = LABELS[key]
        self._attr_options = list(SETTINGS[key][2])
        if key in ("sensitivity", "prefilter_cycle"):
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def current_option(self):
        if not self.state_data:
            return None
        _, suffix, values = SETTINGS[self.key]
        wire = (
            self.state_data.prefilter_cycle
            if self.key == "prefilter_cycle"
            else self.state_data.settings.get(suffix)
        )
        return next((name for name, value in values.items() if value == wire), None)

    async def async_select_option(self, option):
        await self.set_value(self.key, option)
