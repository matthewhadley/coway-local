"""Exercise real HA config flows, registries, entities, services and reload."""

import asyncio
import base64
import json
import shutil
import time
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from aiohttp.test_utils import TestClient, TestServer
from homeassistant import bootstrap, config_entries, loader
from homeassistant.auth import auth_manager_from_config
from homeassistant.components import network
from homeassistant.components.logbook.helpers import is_sensor_continuous
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import EVENT_DATA_ENTRY_FLOW_PROGRESSED
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import frame
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component

from custom_components.coway_local import async_remove_config_entry_device
from custom_components.coway_local.const import DOMAIN
from custom_components.coway_local.provisioning import EXPIRES_KEY
from custom_components.coway_local.service import ServerConfig

from .conftest import Fan, enroll, eventually, free_ports

SERIAL = "LOCAL0001122334455"
# Entity ID: (state after the first report below, unit, device class).
SENSORS = {
    "sensor.test_fan_pm2_5": ("0", "μg/m³", "pm25"),
    "sensor.test_fan_ambient_light": ("617", "lx", "illuminance"),
    "sensor.test_fan_pre_filter_remaining": ("75", "%", None),
    "sensor.test_fan_max2_filter_remaining": ("29", "%", None),
}


@pytest.fixture
async def ha(tmp_path):
    """A real HA instance with the integration loaded and its HTTP app reachable."""
    source = Path(__file__).resolve().parents[1] / "custom_components"
    shutil.copytree(source, tmp_path / "custom_components")
    hass = HomeAssistant(str(tmp_path))
    loader.async_setup(hass)
    frame.async_setup(hass)
    hass.config.skip_pip = True
    hass.config.internal_url = "http://homeassistant.local:8123"
    browser = None
    try:
        hass.config_entries = config_entries.ConfigEntries(hass, {})
        await loader.async_get_custom_components(hass)
        assert await bootstrap.async_load_base_functionality(hass)
        hass.auth = await auth_manager_from_config(hass, [], [])
        assert await async_setup_component(hass, "homeassistant", {})
        assert await async_setup_component(hass, "persistent_notification", {})
        form = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        assert form["type"] == "form"
        advanced = asdict(ServerConfig("127.0.0.1", *free_ports(), "127.0.0.1"))
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"], {"host": advanced.pop("host"), "advanced": advanced}
        )
        assert result["type"] == "create_entry"
        entry = result["result"]
        await hass.async_block_till_done()
        assert entry.state.value == "loaded"
        browser = TestClient(TestServer(hass.http.app))
        await browser.start_server()
        yield SimpleNamespace(
            hass=hass,
            entry=entry,
            browser=browser,
            service=entry.runtime_data,
            options=hass.config_entries.options,
        )
    finally:
        if browser:
            await browser.close()
        await hass.async_stop(force=True)


@pytest.fixture
async def ha_fan(ha):
    """An enrolled, connected fan named "Test fan"."""
    await enroll(ha.service)
    client = await asyncio.to_thread(Fan, ha.service.root, ha.service.config.mqtt_port)
    await asyncio.to_thread(client.open)
    await eventually(lambda: getattr(ha.hass.states.get("fan.test_fan"), "state", None) == "on")
    yield client
    await asyncio.to_thread(client.close)


async def start_add_fan(ha):
    """Choose Add fan; return the external step and its pending pairing."""
    known = set(ha.service.pairings)
    flow = await ha.options.async_init(ha.entry.entry_id)
    flow = await ha.options.async_configure(flow["flow_id"], {"next_step_id": "add_fan"})
    assert flow["step_id"] == "pairing"
    assert flow["type"] == "external" and "data_schema" not in flow
    (token,) = set(ha.service.pairings) - known
    return flow, ha.service.pairings[token]


def return_path(flow):
    setup = urlsplit(flow["url"])
    assert setup.netloc == "scottjg.github.io" and setup.path == "/coway-local/v1/"
    encoded = setup.fragment.removeprefix("setup=")
    bundle = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    url = urlsplit(bundle["returnUrl"])
    assert url.scheme == "http" and url.netloc == "homeassistant.local:8123"
    assert bundle["certToken"] not in bundle["returnUrl"]
    return url.path + "?" + url.query


async def test_entities_and_control_services(ha, ha_fan):
    hass = ha.hass
    assert len([s for s in hass.states.async_all() if "test_fan" in s.entity_id]) == 11
    registry = er.async_get(hass)
    last_seen_id = registry.async_get_entity_id("sensor", DOMAIN, f"{SERIAL}_last_seen")
    assert registry.async_get(last_seen_id).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(last_seen_id) is None

    cycle = "select.test_fan_pre_filter_cleaning_cycle"
    assert hass.states.get(cycle).state == "3 weeks"
    await hass.services.async_call(
        "select", "select_option", {"entity_id": cycle, "option": "4 weeks"}, blocking=True
    )
    assert hass.states.get(cycle).state == "4 weeks"
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.test_fan_timer", "option": "4 hours"},
        blocking=True,
    )
    assert hass.states.get("select.test_fan_timer").state == "4 hours"
    await hass.services.async_call(
        "fan", "set_percentage", {"entity_id": "fan.test_fan", "percentage": 100}, blocking=True
    )
    assert hass.states.get("fan.test_fan").attributes["percentage"] == 100
    await hass.services.async_call("fan", "turn_off", {"entity_id": "fan.test_fan"}, blocking=True)
    assert hass.states.get("fan.test_fan").state == "off"


async def test_measurement_sensors(ha, ha_fan):
    hass = ha.hass
    registry = er.async_get(hass)

    def pm25():
        return hass.states.get("sensor.test_fan_pm2_5").state

    for entity_id in SENSORS:
        assert hass.states.get(entity_id).state == "unknown"
    await asyncio.to_thread(
        ha_fan.report, {"A1020.0001": 0, "A1020.0007": 617, "A1020.0011": 25, "A1020.0012": 71}
    )
    await eventually(lambda: pm25() == "0")
    for entity_id, (value, unit, device_class) in SENSORS.items():
        state = hass.states.get(entity_id)
        assert state.state == value
        assert state.attributes["unit_of_measurement"] == unit
        assert state.attributes["state_class"] == "measurement"
        assert state.attributes.get("device_class") == device_class
        # Routine measurement updates stay out of Activity.
        assert is_sensor_continuous(hass, registry, entity_id)

    # Partial reports preserve other measurements.
    await asyncio.to_thread(ha_fan.report, {"A1020.0001": 2, "A1020.0011": 0})
    await eventually(lambda: pm25() == "2")
    assert hass.states.get("sensor.test_fan_ambient_light").state == "617"
    assert hass.states.get("sensor.test_fan_pre_filter_remaining").state == "100"

    await asyncio.to_thread(ha_fan.report, {"A1020.0001": -1})
    await eventually(lambda: pm25() == "unknown")

    # A reconnect must not show measurements from the previous connection.
    await asyncio.to_thread(ha_fan.report, {"A1020.0001": 1})
    await eventually(lambda: pm25() == "1")
    await asyncio.to_thread(ha_fan.close)
    await eventually(lambda: pm25() == "unavailable")
    await asyncio.to_thread(ha_fan.open)
    await eventually(lambda: pm25() == "unknown")


async def test_return_link_is_validated_and_dies_with_its_flow(ha):
    flow, _ = await start_add_fan(ha)
    back = return_path(flow)
    assert (await ha.browser.get(back.replace("state=", "state=wrong"))).status == 400
    # A rejected return leaves the flow waiting.
    assert (await ha.options.async_configure(flow["flow_id"]))["type"] == "external"
    ha.options.async_abort(flow["flow_id"])
    assert not ha.service.pairings
    assert (await ha.browser.get(back)).status == 410


async def test_expired_setup_cannot_be_resumed(ha):
    flow, pairing = await start_add_fan(ha)
    pairing.expires = time.time() - 1
    ha.options.async_get(flow["flow_id"])["context"][EXPIRES_KEY] = pairing.expires
    assert (await ha.browser.get(return_path(flow))).status == 410
    assert (await ha.options.async_configure(flow["flow_id"]))["type"] == "external_done"
    assert (await ha.options.async_configure(flow["flow_id"]))["reason"] == "pairing_expired"
    assert not ha.service.pairings


async def test_browser_return_alone_does_not_declare_success(ha):
    flow, pairing = await start_add_fan(ha)
    assert (await ha.browser.get(return_path(flow))).status == 200
    progress = await ha.options.async_configure(flow["flow_id"])
    assert progress["type"] == "progress" and "data_schema" not in progress
    ha.service.cancel_pairing(pairing)
    await eventually(lambda: ha.options.async_get(flow["flow_id"])["step_id"] == "finish")
    result = await ha.options.async_configure(flow["flow_id"])
    assert result["reason"] == "pairing_interrupted"


async def test_device_takes_bluetooth_name_but_keeps_user_rename(ha):
    hass = ha.hass
    serial, mac = "LOCAL0001122334477", "001122334477"
    flow, pairing = await start_add_fan(ha)
    await enroll(ha.service, serial, mac, pairing, "AP-OTHER_334477")
    await hass.async_block_till_done()
    devices = dr.async_get(hass)
    device = devices.async_get_device_by_identifier((DOMAIN, serial), ha.entry.entry_id)
    assert device.name == "AP-OTHER_334477"

    devices.async_update_device(device.id, name_by_user="Kitchen purifier")
    await enroll(ha.service, serial, mac, pairing, "New Bluetooth name")
    await hass.async_block_till_done()
    assert devices.async_get(device.id).name == "New Bluetooth name"
    assert devices.async_get(device.id).name_by_user == "Kitchen purifier"

    ha.options.async_abort(flow["flow_id"])
    await hass.config_entries.async_reload(ha.entry.entry_id)
    await hass.async_block_till_done()
    assert devices.async_get(device.id).name_by_user == "Kitchen purifier"
    assert ha.entry.runtime_data.devices[serial]["name"] == "New Bluetooth name"


async def test_enrollment_finishes_when_the_fan_reconnects_after_the_return(ha, ha_fan):
    hass, service = ha.hass, ha.service
    flow, pairing = await start_add_fan(ha)
    await enroll(service, pairing=pairing)
    progressed = []
    unsubscribe = hass.bus.async_listen(EVENT_DATA_ENTRY_FLOW_PROGRESSED, progressed.append)
    back = return_path(flow)
    response = await ha.browser.get(back)
    assert response.status == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "window.opener.focus()" in await response.text()
    assert (await ha.options.async_configure(flow["flow_id"]))["type"] == "progress"
    assert (await ha.browser.get(back)).status == 400  # Single use.

    # The session from before this enrollment cannot complete the new token.
    await service.refresh(SERIAL)
    assert service.states[SERIAL].prefilter_cycle is None
    assert not pairing.complete

    await asyncio.to_thread(ha_fan.close)
    await eventually(lambda: not service.states[SERIAL].online)
    await asyncio.to_thread(ha_fan.open)
    await eventually(lambda: pairing.complete)
    await eventually(lambda: ha.options.async_get(flow["flow_id"])["step_id"] == "finish")
    assert any(event.data["flow_id"] == flow["flow_id"] for event in progressed)
    unsubscribe()
    assert service.states[SERIAL].prefilter_cycle == 168
    # HA's frontend refreshes after the progress event; there is no submit.
    result = await ha.options.async_configure(flow["flow_id"])
    assert result["type"] == "abort" and result["reason"] == "fan_ready"
    assert ha.entry.runtime_data is service
    assert not ha.entry.options


async def test_enrollment_finishes_when_the_fan_connects_before_the_return(ha, ha_fan):
    flow, pairing = await start_add_fan(ha)
    await enroll(ha.service, pairing=pairing)
    await asyncio.to_thread(ha_fan.close)
    await asyncio.to_thread(ha_fan.open)
    await eventually(lambda: pairing.complete)
    assert (await ha.browser.get(return_path(flow))).status == 200
    result = await ha.options.async_configure(flow["flow_id"])
    assert result["type"] == "abort" and result["reason"] == "fan_ready"


async def test_reload_keeps_devices_and_unload_stops_the_service(ha, ha_fan):
    hass, entry = ha.hass, ha.entry
    await asyncio.to_thread(ha_fan.close)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state.value == "loaded"
    reloaded = entry.runtime_data
    assert reloaded is not ha.service
    assert hass.states.get("fan.test_fan").state == "unavailable"
    for entity_id in SENSORS:
        assert hass.states.get(entity_id).state == "unavailable"
    assert reloaded.states[SERIAL].prefilter_cycle == 168
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not reloaded.started


async def test_repair_notice_when_the_machine_loses_the_configured_address(ha, monkeypatch):
    hass, entry = ha.hass, ha.entry
    issues = ir.async_get(hass)

    async def reload_with_addresses(*addresses):
        async def adapters(hass):
            return [{"ipv4": [{"address": address} for address in addresses]}]

        monkeypatch.setattr(network, "async_get_adapters", adapters)
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state.value == "loaded"
        return issues.async_get_issue(DOMAIN, "host_changed")

    # Setup saw the configured address on this machine's loopback adapter.
    assert entry.data["local_host"] == "127.0.0.1"
    assert await reload_with_addresses("192.0.2.5") is not None
    # No notice while the network is still coming up.
    assert await reload_with_addresses() is None
    assert await reload_with_addresses("192.0.2.5") is not None
    assert await reload_with_addresses("127.0.0.1") is None

    # An address this machine never had is a deliberate override (Docker bridge).
    data = {key: value for key, value in entry.data.items() if key != "local_host"}
    monkeypatch.setattr(network, "async_get_adapters", lambda hass: asyncio.sleep(0, []))
    hass.config_entries.async_update_entry(entry, data=data)
    assert await reload_with_addresses("192.0.2.5") is None
    assert "local_host" not in entry.data


async def test_server_settings_form_accepts_the_advanced_section(ha):
    flow = await ha.options.async_init(ha.entry.entry_id)
    flow = await ha.options.async_configure(flow["flow_id"], {"next_step_id": "server"})
    advanced = asdict(ha.service.config)
    host = advanced.pop("host")

    rejected = await ha.options.async_configure(
        flow["flow_id"], {"host": host, "advanced": advanced | {"mqtt_port": advanced["http_port"]}}
    )
    assert rejected["errors"] == {"base": "invalid_server"}
    saved = await ha.options.async_configure(flow["flow_id"], {"host": host, "advanced": advanced})
    assert saved["type"] == "create_entry"
    assert saved["data"] == asdict(ha.service.config)


async def test_fan_removed_and_enrolled_again_gets_its_entities_back(ha, ha_fan):
    hass, service = ha.hass, ha.service
    devices = dr.async_get(hass)
    device = devices.async_get_device_by_identifier((DOMAIN, SERIAL), ha.entry.entry_id)

    # What Home Assistant does when the user deletes the device.
    await asyncio.to_thread(ha_fan.close)
    assert await async_remove_config_entry_device(hass, ha.entry, device)
    devices.async_remove_device(device.id)
    await hass.async_block_till_done()
    assert hass.states.get("fan.test_fan") is None

    await enroll(service)
    again = await asyncio.to_thread(Fan, service.root, service.config.mqtt_port)
    try:
        await asyncio.to_thread(again.open)
        await eventually(lambda: getattr(hass.states.get("fan.test_fan"), "state", None) == "on")
        assert devices.async_get_device_by_identifier((DOMAIN, SERIAL), ha.entry.entry_id)
    finally:
        await asyncio.to_thread(again.close)
