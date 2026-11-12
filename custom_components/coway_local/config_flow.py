"""Server setup and temporary Bluetooth enrollment links."""

import asyncio
import secrets
import time
from dataclasses import asdict
from urllib.parse import urlencode

import probatio as vol
from homeassistant import config_entries
from homeassistant.components import network
from homeassistant.core import callback
from homeassistant.helpers.network import NoURLAvailableError

from .const import DEFAULT_PORTS, DOMAIN, PROVISIONER_URL
from .provisioning import EXPIRES_KEY, RETURN_PATH, STATE_KEY, frontend_url
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
        self.setup_url = None
        self.verify_task = None

    @callback
    def async_remove(self):
        self.context.pop(STATE_KEY, None)
        if self.pairing and self.pairing_service:
            self.pairing_service.cancel_pairing(self.pairing)

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(step_id="init", menu_options=["add_fan", "server"])

    async def async_step_add_fan(self, user_input=None):
        service = self.config_entry.runtime_data
        try:
            base = frontend_url(self.hass)
            self.pairing = service.begin_pairing()
            self.pairing_service = service
        except ValueError, ConnectionError, NoURLAvailableError:
            return self.async_abort(reason="cannot_start_pairing")
        state = secrets.token_urlsafe(24)
        self.context[STATE_KEY] = state
        self.context[EXPIRES_KEY] = self.pairing.expires
        query = urlencode({"flow_id": self.flow_id, "state": state})
        self.setup_url = service.setup_url(self.pairing, f"{base}{RETURN_PATH}?{query}")
        return await self.async_step_pairing()

    async def async_step_pairing(self, user_input=None):
        if user_input and user_input.get("returned"):
            return self.async_external_step_done(next_step_id="verify")
        if self.pairing.finished.is_set() or time.time() > self.pairing.expires:
            return self.async_external_step_done(next_step_id="finish")
        return self.async_external_step(
            step_id="pairing",
            url=self.setup_url,
        )

    async def _wait_for_pairing(self):
        try:
            async with asyncio.timeout(max(0, self.pairing.expires - time.time())):
                await self.pairing.finished.wait()
        except TimeoutError:
            self.pairing_service.cancel_pairing(self.pairing)

    async def async_step_verify(self, user_input=None):
        if self.verify_task is None:
            if self.pairing.finished.is_set() or time.time() > self.pairing.expires:
                return await self.async_step_finish()
            self.verify_task = self.hass.async_create_background_task(
                self._wait_for_pairing(), "Coway Local enrollment verification"
            )
        if self.verify_task.done():
            return self.async_show_progress_done(next_step_id="finish")
        return self.async_show_progress(
            step_id="verify",
            progress_action="verify_connection",
            progress_task=self.verify_task,
        )

    async def async_step_finish(self, user_input=None):
        if self.pairing.complete:
            return self.async_create_entry(title="", data=dict(self.config_entry.options))
        reason = "pairing_expired" if time.time() >= self.pairing.expires else "pairing_interrupted"
        return self.async_abort(reason=reason)

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
