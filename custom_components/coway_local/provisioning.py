"""One-use browser return from the external Bluetooth wizard."""

import secrets
import time
from urllib.parse import urlsplit

from aiohttp import web
from homeassistant.components import http
from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.data_entry_flow import UnknownFlow
from homeassistant.helpers.network import get_url

from .const import DOMAIN

RETURN_PATH = "/api/coway_local/provisioning/return"
STATE_KEY = "coway_return_state"
EXPIRES_KEY = "coway_return_expires"


def frontend_url(hass):
    """Return to the frontend that opened setup, including its scheme and port."""
    request = http.current_request.get()
    base = request.headers.get("HA-Frontend-Base") if request is not None else None
    url = urlsplit(base or get_url(hass))
    if (
        url.scheme not in ("http", "https")
        or not url.hostname
        or url.username
        or url.password
        or url.path not in ("", "/")
        or url.query
        or url.fragment
    ):
        raise ValueError("Invalid Home Assistant frontend URL")
    return f"{url.scheme}://{url.netloc}"


class ProvisioningReturnView(HomeAssistantView):
    """Resume only the options flow identified by its short-lived return token."""

    url = RETURN_PATH
    name = "api:coway_local:provisioning:return"
    requires_auth = False

    async def get(self, request):
        hass = request.app[KEY_HASS]
        flow_id = request.query.get("flow_id", "")
        state = request.query.get("state", "")
        try:
            flow = hass.config_entries.options.async_get(flow_id)
        except UnknownFlow as error:
            raise web.HTTPGone(
                text="This setup ended. Start Add fan again in Home Assistant."
            ) from error
        context = flow["context"]
        entry = hass.config_entries.async_get_entry(flow["handler"])
        expected = context.get(STATE_KEY)
        if (
            entry is None
            or entry.domain != DOMAIN
            or flow["step_id"] != "pairing"
            or not expected
            or not secrets.compare_digest(state.encode(), expected.encode())
        ):
            raise web.HTTPBadRequest(text="Invalid or already used setup return link.")
        if time.time() > context[EXPIRES_KEY]:
            raise web.HTTPGone(text="Setup expired. Start Add fan again in Home Assistant.")
        # Consume before yielding, so two requests cannot resume the same flow.
        # This token only resumes the UI; MQTT authentication proves enrollment.
        context.pop(STATE_KEY)
        await hass.config_entries.options.async_configure(flow_id, {"returned": True})

        nonce = secrets.token_urlsafe(18)
        return web.Response(
            content_type="text/html",
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": f"default-src 'none'; script-src 'nonce-{nonce}'; base-uri 'none'; frame-ancestors 'none'",
            },
            text=f"""<!doctype html><html lang="en"><meta charset="utf-8">
<title>Returning to Home Assistant</title>
<p>Returning to Home Assistant. It will finish checking your fan automatically.</p>
<a href="/config/integrations/integration/coway_local">Open Coway Local</a>
<script nonce="{nonce}">
history.replaceState(null, '', location.pathname);
try {{
  if (window.opener && !window.opener.closed) {{
    window.opener.focus();
    window.close();
  }}
}} catch (_) {{}}
// Also handle a manually opened setup tab or browsers that disallow closing it.
setTimeout(() => location.replace('/config/integrations/integration/coway_local'), 100);
</script></html>""",
        )
