"""Exercise real HA config flows, registries, entities, services and reload."""

import asyncio
import shutil
from dataclasses import asdict
from pathlib import Path

from homeassistant import bootstrap, config_entries, loader
from homeassistant.components.logbook.helpers import is_sensor_continuous
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import frame
from homeassistant.setup import async_setup_component

from custom_components.coway_local.const import DOMAIN
from custom_components.coway_local.service import ServerConfig

from .conftest import Fan, enroll, eventually, free_ports


async def test_ha_config_flow_entities_services_reload(tmp_path):
    source = Path(__file__).resolve().parents[1] / "custom_components"
    shutil.copytree(source, tmp_path / "custom_components")
    hass = HomeAssistant(str(tmp_path))
    loader.async_setup(hass)
    frame.async_setup(hass)
    hass.config.skip_pip = True
    client = None
    try:
        hass.config_entries = config_entries.ConfigEntries(hass, {})
        await loader.async_get_custom_components(hass)
        assert await bootstrap.async_load_base_functionality(hass)
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
        assert set(options["data_schema"].schema) == {"name"}
        options = await hass.config_entries.options.async_configure(
            options["flow_id"], {"name": "Another fan"}
        )
        assert options["step_id"] == "pairing"
        assert "#setup=" in options["description_placeholders"]["setup_url"]
        options = await hass.config_entries.options.async_configure(options["flow_id"], {})
        assert options["errors"] == {"base": "not_connected"}
        hass.config_entries.options.async_abort(options["flow_id"])
        assert not service.pairings
        # Leaving the optional name blank uses the actual Bluetooth fallback.
        naming_flow = await hass.config_entries.options.async_init(entry.entry_id)
        naming_flow = await hass.config_entries.options.async_configure(
            naming_flow["flow_id"], {"next_step_id": "add_fan"}
        )
        naming_flow = await hass.config_entries.options.async_configure(
            naming_flow["flow_id"], {}
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
        options = await hass.config_entries.options.async_configure(
            options["flow_id"], {"name": "Test fan"}
        )
        pending = next(iter(service.pairings.values()))
        await enroll(service, pairing=pending)
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
        assert service.states[client.serial].prefilter_cycle == 168
        await eventually(lambda: hass.states.get("sensor.test_fan_pm2_5").state == "unknown")
        options = await hass.config_entries.options.async_configure(options["flow_id"], {})
        assert options["type"] == "create_entry"
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
        if client:
            await asyncio.to_thread(client.close)
        await hass.async_stop(force=True)
