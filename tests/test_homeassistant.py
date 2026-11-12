"""Exercise real HA config flows, registries, entities, services and reload."""

import asyncio
import base64
import json
import shutil
import time
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp.test_utils import TestClient, TestServer
from homeassistant import bootstrap, config_entries, loader
from homeassistant.auth import auth_manager_from_config
from homeassistant.components.logbook.helpers import is_sensor_continuous
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import EVENT_DATA_ENTRY_FLOW_PROGRESSED
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import frame
from homeassistant.setup import async_setup_component

from custom_components.coway_local.const import DOMAIN
from custom_components.coway_local.provisioning import EXPIRES_KEY
from custom_components.coway_local.service import ServerConfig

from .conftest import Fan, enroll, eventually, free_ports


def return_path(options):
    encoded = urlsplit(options["url"]).fragment.removeprefix("setup=")
    bundle = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    url = urlsplit(bundle["returnUrl"])
    assert url.scheme == "http" and url.netloc == "homeassistant.local:8123"
    assert bundle["certToken"] not in bundle["returnUrl"]
    return url.path + "?" + url.query


async def test_ha_config_flow_entities_services_reload(tmp_path):
    source = Path(__file__).resolve().parents[1] / "custom_components"
    shutil.copytree(source, tmp_path / "custom_components")
    hass = HomeAssistant(str(tmp_path))
    loader.async_setup(hass)
    frame.async_setup(hass)
    hass.config.skip_pip = True
    hass.config.internal_url = "http://homeassistant.local:8123"
    client = None
    browser = None
    try:
        hass.config_entries = config_entries.ConfigEntries(hass, {})
        await loader.async_get_custom_components(hass)
        assert await bootstrap.async_load_base_functionality(hass)
        hass.auth = await auth_manager_from_config(hass, [], [])
        assert await async_setup_component(hass, "homeassistant", {})
        assert await async_setup_component(hass, "persistent_notification", {})
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
            data=asdict(ServerConfig("127.0.0.1", *free_ports(), "127.0.0.1")),
        )
        assert result["type"] == "create_entry"
        entry = result["result"]
        await hass.async_block_till_done()
        assert entry.state.value == "loaded"
        browser = TestClient(TestServer(hass.http.app))
        await browser.start_server()
        service = entry.runtime_data
        await enroll(service)
        client = await asyncio.to_thread(Fan, service.root, service.config.mqtt_port)
        await asyncio.to_thread(client.open)
        await eventually(
            lambda: (
                hass.states.get("fan.test_fan") is not None
                and hass.states.get("fan.test_fan").state == "on"
            )
        )
        assert (
            len(
                [
                    s
                    for s in hass.states.async_all()
                    if s.entity_id.startswith(
                        (
                            "fan.test_fan",
                            "select.test_fan",
                            "binary_sensor.test_fan",
                            "sensor.test_fan",
                            "button.test_fan",
                        )
                    )
                ]
            )
            == 11
        )
        registry = er.async_get(hass)
        last_seen_id = registry.async_get_entity_id("sensor", DOMAIN, "LOCAL0001122334455_last_seen")
        assert last_seen_id is not None
        assert registry.async_get(last_seen_id).disabled_by is er.RegistryEntryDisabler.INTEGRATION
        assert hass.states.get(last_seen_id) is None
        assert hass.states.get("select.test_fan_pre_filter_cleaning_cycle").state == "3 weeks"
        await hass.services.async_call(
            "select", "select_option",
            {"entity_id": "select.test_fan_pre_filter_cleaning_cycle", "option": "4 weeks"},
            blocking=True,
        )
        assert hass.states.get("select.test_fan_pre_filter_cleaning_cycle").state == "4 weeks"
        expected = {
            "sensor.test_fan_pm2_5": ("0", "μg/m³", "pm25"),
            "sensor.test_fan_ambient_light": ("617", "lx", "illuminance"),
            "sensor.test_fan_pre_filter_remaining": ("75", "%", None),
            "sensor.test_fan_max2_filter_remaining": ("29", "%", None),
        }
        for entity_id in expected:
            assert hass.states.get(entity_id).state == "unknown"
        await asyncio.to_thread(
            client.report,
            {"A1020.0001": 0, "A1020.0007": 617, "A1020.0011": 25, "A1020.0012": 71},
        )
        await eventually(lambda: hass.states.get("sensor.test_fan_pm2_5").state == "0")
        for entity_id, (value, unit, device_class) in expected.items():
            state = hass.states.get(entity_id)
            assert state.state == value
            assert state.attributes["unit_of_measurement"] == unit
            assert state.attributes["state_class"] == "measurement"
            assert state.attributes.get("device_class") == device_class
            assert is_sensor_continuous(hass, registry, entity_id)
        # Partial reports preserve other measurements. Zero and 100% usage are valid.
        await asyncio.to_thread(
            client.report, {"A1020.0001": 2, "A1020.0011": 0, "A1020.0012": 100}
        )
        await eventually(lambda: hass.states.get("sensor.test_fan_pm2_5").state == "2")
        assert hass.states.get("sensor.test_fan_ambient_light").state == "617"
        assert hass.states.get("sensor.test_fan_pre_filter_remaining").state == "100"
        assert hass.states.get("sensor.test_fan_max2_filter_remaining").state == "0"
        await asyncio.to_thread(
            client.report,
            {"A1020.0001": -1, "A1020.0007": None, "A1020.0011": 101, "A1020.0012": -1},
        )
        await eventually(lambda: hass.states.get("sensor.test_fan_pm2_5").state == "unknown")
        for entity_id in expected:
            assert hass.states.get(entity_id).state == "unknown"
        await asyncio.to_thread(client.report, {"A1020.0001": 1})
        await eventually(lambda: hass.states.get("sensor.test_fan_pm2_5").state == "1")
        await hass.services.async_call(
            "fan", "set_percentage", {"entity_id": "fan.test_fan", "percentage": 100}, blocking=True
        )
        assert hass.states.get("fan.test_fan").attributes["percentage"] == 100
        await hass.services.async_call(
            "select",
            "select_option",
            {
                "entity_id": "select.test_fan_timer",
                "option": "4 hours",
            },
            blocking=True,
        )
        assert hass.states.get("select.test_fan_timer").state == "4 hours"
        await hass.services.async_call(
            "fan", "turn_off", {"entity_id": "fan.test_fan"}, blocking=True
        )
        assert hass.states.get("fan.test_fan").state == "off"
        options = await hass.config_entries.options.async_init(entry.entry_id)
        options = await hass.config_entries.options.async_configure(
            options["flow_id"], {"next_step_id": "add_fan"}
        )
        assert options["step_id"] == "pairing"
        assert options["type"] == "external" and "data_schema" not in options
        assert len(service.pairings) == 1
        back = return_path(options)
        response = await browser.get(back.replace("state=", "state=wrong"))
        assert response.status == 400
        options = await hass.config_entries.options.async_configure(options["flow_id"])
        assert options["type"] == "external"
        hass.config_entries.options.async_abort(options["flow_id"])
        assert not service.pairings
        assert (await browser.get(back)).status == 410

        # Expired callbacks cannot resume setup or leave usable credentials behind.
        expired = await hass.config_entries.options.async_init(entry.entry_id)
        expired = await hass.config_entries.options.async_configure(
            expired["flow_id"], {"next_step_id": "add_fan"}
        )
        pair = next(iter(service.pairings.values()))
        pair.expires = time.time() - 1
        hass.config_entries.options.async_get(expired["flow_id"])["context"][EXPIRES_KEY] = pair.expires
        assert (await browser.get(return_path(expired))).status == 410
        assert (await hass.config_entries.options.async_configure(expired["flow_id"]))["type"] == "external_done"
        assert (await hass.config_entries.options.async_configure(expired["flow_id"]))["reason"] == "pairing_expired"
        assert not service.pairings

        # Returning from the browser alone does not declare success.
        interrupted = await hass.config_entries.options.async_init(entry.entry_id)
        interrupted = await hass.config_entries.options.async_configure(
            interrupted["flow_id"], {"next_step_id": "add_fan"}
        )
        assert (await browser.get(return_path(interrupted))).status == 200
        progress = await hass.config_entries.options.async_configure(interrupted["flow_id"])
        assert progress["type"] == "progress" and "data_schema" not in progress
        pair = next(iter(service.pairings.values()))
        service.cancel_pairing(pair)
        await eventually(lambda: hass.config_entries.options.async_get(interrupted["flow_id"])["step_id"] == "finish")
        result = await hass.config_entries.options.async_configure(interrupted["flow_id"])
        assert result["reason"] == "pairing_interrupted"
        # Selecting Add fan opens setup directly and uses the Bluetooth name.
        naming_flow = await hass.config_entries.options.async_init(entry.entry_id)
        naming_flow = await hass.config_entries.options.async_configure(
            naming_flow["flow_id"], {"next_step_id": "add_fan"}
        )
        naming_pair = next(iter(service.pairings.values()))
        assert naming_pair.serial is None
        assert "serial" not in service.setup_bundle(naming_pair)
        await enroll(service, "LOCAL0001122334477", "001122334477", naming_pair, "AP-OTHER_334477")
        await hass.async_block_till_done()
        devices = dr.async_get(hass)
        named_device = devices.async_get_device_by_identifier((DOMAIN, "LOCAL0001122334477"), entry.entry_id)
        assert named_device.name == "AP-OTHER_334477"
        devices.async_update_device(named_device.id, name_by_user="Kitchen purifier")
        await enroll(service, "LOCAL0001122334477", "001122334477", naming_pair, "New Bluetooth name")
        await hass.async_block_till_done()
        assert devices.async_get(named_device.id).name == "New Bluetooth name"
        assert devices.async_get(named_device.id).name_by_user == "Kitchen purifier"
        hass.config_entries.options.async_abort(naming_flow["flow_id"])
        options = await hass.config_entries.options.async_init(entry.entry_id)
        options = await hass.config_entries.options.async_configure(
            options["flow_id"], {"next_step_id": "add_fan"}
        )
        pending = next(iter(service.pairings.values()))
        await enroll(service, pairing=pending)
        progressed = []
        unsubscribe = hass.bus.async_listen(EVENT_DATA_ENTRY_FLOW_PROGRESSED, progressed.append)
        back = return_path(options)
        response = await browser.get(back)
        assert response.status == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert "window.opener.focus()" in await response.text()
        options = await hass.config_entries.options.async_configure(options["flow_id"])
        assert options["type"] == "progress"
        assert (await browser.get(back)).status == 400  # Single use.
        # A newly issued token cannot be completed by the already-online session.
        assert not pending.complete
        await service.refresh(client.serial)
        assert service.states[client.serial].prefilter_cycle is None
        assert not pending.complete
        await asyncio.to_thread(client.close)
        await eventually(
            lambda: hass.states.get("sensor.test_fan_pm2_5").state == "unavailable"
        )
        await asyncio.to_thread(client.open)
        await eventually(lambda: pending.complete)
        await eventually(lambda: hass.config_entries.options.async_get(options["flow_id"])["step_id"] == "finish")
        assert any(event.data["flow_id"] == options["flow_id"] for event in progressed)
        unsubscribe()
        assert service.states[client.serial].prefilter_cycle == 168
        await eventually(lambda: hass.states.get("sensor.test_fan_pm2_5").state == "unknown")
        # This is HA's automatic frontend refresh after its progress event, not a submit.
        options = await hass.config_entries.options.async_configure(options["flow_id"])
        assert options["type"] == "abort" and options["reason"] == "fan_ready"
        assert entry.runtime_data is service
        assert not entry.options
        await hass.async_block_till_done()

        # The fan can also finish before the browser returns; skip the spinner then.
        fast = await hass.config_entries.options.async_init(entry.entry_id)
        fast = await hass.config_entries.options.async_configure(
            fast["flow_id"], {"next_step_id": "add_fan"}
        )
        pending = next(iter(service.pairings.values()))
        await enroll(service, pairing=pending)
        await asyncio.to_thread(client.close)
        await asyncio.to_thread(client.open)
        await eventually(lambda: pending.complete)
        assert (await browser.get(return_path(fast))).status == 200
        fast = await hass.config_entries.options.async_configure(fast["flow_id"])
        assert fast["type"] == "abort" and fast["reason"] == "fan_ready"
        await hass.async_block_till_done()
        await asyncio.to_thread(client.close)
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state.value == "loaded"
        assert entry.runtime_data is not service
        assert hass.states.get("fan.test_fan").state == "unavailable"
        for entity_id in expected:
            assert hass.states.get(entity_id).state == "unavailable"
        assert "LOCAL0001122334455" in entry.runtime_data.devices
        assert entry.runtime_data.states[client.serial].prefilter_cycle == 168
        assert devices.async_get(named_device.id).name_by_user == "Kitchen purifier"
        assert entry.runtime_data.devices["LOCAL0001122334477"]["name"] == "New Bluetooth name"
        final_service = entry.runtime_data
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert not final_service.started
    finally:
        if browser:
            await browser.close()
        if client:
            await asyncio.to_thread(client.close)
        await hass.async_stop(force=True)
