"""Exercise real HA config flows, registries, entities, services and reload."""

import asyncio
import shutil
from dataclasses import asdict
from pathlib import Path

from homeassistant import bootstrap, config_entries, loader
from homeassistant.core import HomeAssistant
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
            == 8
        )
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
        options = await hass.config_entries.options.async_configure(
            options["flow_id"], {"serial": "TEST000002", "name": "Another fan"}
        )
        assert options["step_id"] == "pairing"
        assert "#setup=" in options["description_placeholders"]["setup_url"]
        options = await hass.config_entries.options.async_configure(options["flow_id"], {})
        assert options["errors"] == {"base": "not_connected"}
        hass.config_entries.options.async_abort(options["flow_id"])
        assert not service.pairings
        options = await hass.config_entries.options.async_init(entry.entry_id)
        options = await hass.config_entries.options.async_configure(
            options["flow_id"], {"next_step_id": "add_fan"}
        )
        options = await hass.config_entries.options.async_configure(
            options["flow_id"], {"serial": client.serial, "name": "Test fan"}
        )
        pending = next(iter(service.pairings.values()))
        await enroll(service, pairing=pending)
        # A newly issued token cannot be completed by the already-online session.
        assert not pending.complete
        await asyncio.to_thread(client.close)
        await asyncio.to_thread(client.open)
        await eventually(lambda: pending.complete)
        options = await hass.config_entries.options.async_configure(options["flow_id"], {})
        assert options["type"] == "create_entry"
        await hass.async_block_till_done()
        await asyncio.to_thread(client.close)
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state.value == "loaded"
        assert entry.runtime_data is not service
        assert hass.states.get("fan.test_fan").state == "unavailable"
        assert "TEST000001" in entry.runtime_data.devices
        final_service = entry.runtime_data
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert not final_service.started
    finally:
        if client:
            await asyncio.to_thread(client.close)
        await hass.async_stop(force=True)
