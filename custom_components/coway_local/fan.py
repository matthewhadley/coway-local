"""Power, three manual speeds, smart mode and sleep mode."""

import math

from homeassistant.components.fan import FanEntity, FanEntityFeature

from .entity import CowayEntity, setup_devices


async def async_setup_entry(hass, entry, async_add_entities):
    setup_devices(entry, async_add_entities, lambda service, serial: [CowayFan(service, serial)])


class CowayFan(CowayEntity, FanEntity):
    _attr_name = None
    _attr_speed_count = 3
    _attr_preset_modes = ["manual", "smart", "sleep"]
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )

    def __init__(self, service, serial):
        super().__init__(service, serial, "fan")

    @property
    def is_on(self):
        power = self.state_data.settings.get("0001") if self.state_data else None
        return bool(power) if power is not None else None

    @property
    def percentage(self):
        if self.is_on is False:
            return 0
        speed = self.state_data.settings.get("0003") if self.state_data else None
        return round(speed * 100 / 3) if speed in (1, 2, 3) else None

    @property
    def preset_mode(self):
        mode = self.state_data.settings.get("0002") if self.state_data else None
        return {0: "manual", 1: "smart", 2: "sleep"}.get(mode)

    async def async_set_percentage(self, percentage):
        if percentage == 0:
            await self.async_turn_off()
        else:
            if self.is_on is False:
                await self.set_value("power", "on")
            await self.set_value("speed", str(max(1, min(3, math.ceil(percentage * 3 / 100)))))

    async def async_set_preset_mode(self, preset_mode):
        if preset_mode == "manual":
            speed = self.state_data.settings.get("0003", 1)
            await self.set_value("speed", str(speed if speed in (1, 2, 3) else 1))
        else:
            await self.set_value("mode", preset_mode)

    async def async_turn_on(self, percentage=None, preset_mode=None, **kwargs):
        await self.set_value("power", "on")
        if preset_mode is not None:
            await self.async_set_preset_mode(preset_mode)
        elif percentage is not None:
            await self.async_set_percentage(percentage)

    async def async_turn_off(self, **kwargs):
        await self.set_value("power", "off")
