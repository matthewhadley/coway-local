"""Cloud-free control and provisioning of the observed Coway AP-1022K."""

from pathlib import Path

from homeassistant.components import network
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .provisioning import ProvisioningReturnView
from .service import LocalService, ServerConfig

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [
    Platform.FAN,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.BINARY_SENSOR,
]
type CowayConfigEntry = ConfigEntry[LocalService]

# The configured address, recorded once it has been seen on one of this machine's adapters.
LOCAL_HOST = "local_host"
HOST_CHANGED = "host_changed"


async def async_setup(hass: HomeAssistant, config) -> bool:
    hass.http.register_view(ProvisioningReturnView)
    return True


async def check_host(hass: HomeAssistant, entry: CowayConfigEntry, host: str):
    """Warn when the address the fans were given no longer belongs to this machine.

    An address that was never one of this machine's own (Docker bridge networking)
    is a deliberate override and never triggers the warning.
    """
    addresses = {
        ip["address"]
        for adapter in await network.async_get_adapters(hass)
        for ip in adapter["ipv4"]
    }
    network_is_up = any(not address.startswith("127.") for address in addresses)

    if host in addresses and entry.data.get(LOCAL_HOST) != host:
        # Runs before the reload listener is registered, so this does not reload.
        hass.config_entries.async_update_entry(entry, data={**entry.data, LOCAL_HOST: host})

    if host not in addresses and entry.data.get(LOCAL_HOST) == host and network_is_up:
        ir.async_create_issue(
            hass,
            DOMAIN,
            HOST_CHANGED,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=HOST_CHANGED,
            translation_placeholders={"host": host},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, HOST_CHANGED)


async def async_setup_entry(hass: HomeAssistant, entry: CowayConfigEntry) -> bool:
    settings = entry.data | entry.options
    settings.pop(LOCAL_HOST, None)
    config = ServerConfig(**settings)
    await check_host(hass, entry, config.host)

    service = LocalService(Path(hass.config.path(".storage", DOMAIN)), config)
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
