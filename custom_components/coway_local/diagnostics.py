"""Diagnostics exclude identities and provisioning secrets."""


async def async_get_config_entry_diagnostics(hass, entry):
    return entry.runtime_data.diagnostics()
