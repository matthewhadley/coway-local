"""Cloud-free control and provisioning of the observed Coway AP-1022K."""

from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .provisioning import ProvisioningReturnView
from .service import LocalService, ServerConfig

PLATFORMS = [
    Platform.FAN,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.BINARY_SENSOR,
]
type CowayConfigEntry = ConfigEntry[LocalService]


async def async_setup(hass: HomeAssistant, config) -> bool:
    hass.http.register_view(ProvisioningReturnView)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: CowayConfigEntry) -> bool:
    service = LocalService(
        Path(hass.config.path(".storage", DOMAIN)),
        ServerConfig(**(entry.data | entry.options)),
    )
    try:
        await service.start()
    except Exception as error:
        raise ConfigEntryNotReady(
            "Could not start Coway local listeners. Check the configured address, "
            "port conflicts and certificate storage."
        ) from error
    entry.runtime_data = service

    def update_device_name(serial):
        record = service.devices.get(serial)
        registry = dr.async_get(hass)
        device = registry.async_get_device_by_identifier((DOMAIN, serial), entry.entry_id)
        if record and device and device.name != record["name"]:
            # HA's independent name_by_user override is deliberately untouched.
            registry.async_update_device(device.id, name=record["name"])

    entry.async_on_unload(service.subscribe(update_device_name))

    async def stop(event):
        await service.stop()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop))
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await service.stop()
        raise
    return True


async def async_reload_entry(hass: HomeAssistant, entry: CowayConfigEntry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: CowayConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.stop()
    return True


async def async_remove_config_entry_device(hass, entry, device_entry) -> bool:
    for domain, serial in device_entry.identifiers:
        if domain == DOMAIN:
            await entry.runtime_data.remove(serial)
            return True
    return False
