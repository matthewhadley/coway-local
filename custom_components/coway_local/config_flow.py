"""Server setup and temporary Bluetooth enrollment links."""

import time
from dataclasses import asdict

import probatio as vol
from homeassistant import config_entries
from homeassistant.components import network
from homeassistant.core import callback

from .const import DEFAULT_PORTS, DOMAIN, PROVISIONER_URL
from .service import ServerConfig


def server_schema(defaults):
    fields = {
        vol.Required("host", default=defaults.get("host", "")): str,
        vol.Optional(
            "provisioner_url", default=defaults.get("provisioner_url", PROVISIONER_URL)
        ): str,
    }
    for key, port in DEFAULT_PORTS.items():
        fields[vol.Required(key, default=defaults.get(key, port))] = vol.All(
            vol.Coerce(int), vol.Range(min=1024, max=65535)
        )
    fields[vol.Optional("bind_host", default=defaults.get("bind_host", "0.0.0.0"))] = str
    return vol.Schema(fields)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        errors = {}
        defaults = user_input or {}
        if user_input is not None:
            try:
                config = ServerConfig(**user_input).validate()
            except ValueError, TypeError:
                errors["base"] = "invalid_server"
            else:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Coway Local", data=asdict(config))
        else:
            try:
                defaults["host"] = await network.async_get_source_ip(self.hass)
            except Exception:
                defaults["host"] = ""
        return self.async_show_form(
            step_id="user", data_schema=server_schema(defaults), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlow()


class OptionsFlow(config_entries.OptionsFlow):
    def __init__(self):
        self.pairing = None
        self.pairing_service = None

    @callback
    def async_remove(self):
        if self.pairing and self.pairing_service:
            self.pairing_service.cancel_pairing(self.pairing)

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(step_id="init", menu_options=["add_fan", "server"])

    async def async_step_add_fan(self, user_input=None):
        service = self.config_entry.runtime_data
        errors = {}
        if user_input is not None:
            try:
                self.pairing = service.begin_pairing(user_input.get("name", ""))
                self.pairing_service = service
            except ValueError, ConnectionError:
                errors["base"] = "cannot_start_pairing"
            else:
                return await self.async_step_pairing()
        return self.async_show_form(
            step_id="add_fan",
            data_schema=vol.Schema(
                {
                    vol.Optional("name", default=""): str,
                }
            ),
            errors=errors,
        )

    async def async_step_pairing(self, user_input=None):
        service = self.config_entry.runtime_data
        if self.pairing is None:
            return await self.async_step_add_fan()
        if self.pairing.complete:
            return self.async_create_entry(title="", data=dict(self.config_entry.options))
        if time.time() > self.pairing.expires:
            service.cancel_pairing(self.pairing)
            return self.async_abort(reason="pairing_expired")
        return self.async_show_form(
            step_id="pairing",
            data_schema=vol.Schema({}),
            description_placeholders={
                "setup_url": service.setup_url(self.pairing),
                "name": self.pairing.name or "your fan",
            },
            errors={"base": "not_connected"} if user_input is not None else {},
        )

    async def async_step_server(self, user_input=None):
        defaults = self.config_entry.data | self.config_entry.options
        errors = {}
        if user_input is not None:
            try:
                config = ServerConfig(**user_input).validate()
            except ValueError, TypeError:
                errors["base"] = "invalid_server"
                defaults = user_input
            else:
                return self.async_create_entry(title="", data=asdict(config))
        return self.async_show_form(
            step_id="server", data_schema=server_schema(defaults), errors=errors
        )
