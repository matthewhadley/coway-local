"""Enrollment initialization and durable, device-confirmed cleaning intervals."""

import asyncio
import json

from custom_components.coway_local import pki
from custom_components.coway_local.broker import topic
from custom_components.coway_local.service import LocalService

from .conftest import Fan, enroll, eventually


async def test_later_choice_survives_new_service_without_default_replay(service, fan):
    assert service.states[fan.serial].prefilter_cycle == 168
    assert not service.devices[fan.serial].get("prefilter_default_pending")
    await service.set(fan.serial, "prefilter_cycle", "2 weeks")
    await asyncio.to_thread(fan.close)
    await service.stop()
    replacement = LocalService(service.root, service.config)
    try:
        await replacement.start()
        assert replacement.states[fan.serial].prefilter_cycle == 112
        while not fan.messages.empty():
            fan.messages.get_nowait()
        await asyncio.to_thread(fan.open)
        await eventually(lambda: bool(replacement.states[fan.serial].settings))
        await replacement.refresh(fan.serial)
        while not fan.messages.empty():
            assert fan.messages.get_nowait()["header"]["API_NO"] == "A1013"
        assert replacement.states[fan.serial].prefilter_cycle == 112
    finally:
        await asyncio.to_thread(fan.close)
        await replacement.stop()


async def test_enrollment_requires_matching_default_acknowledgement(service):
    pairing, _ = await enroll(service)
    client = await asyncio.to_thread(Fan, service.root, service.config.mqtt_port, respond=False)
    try:
        await asyncio.to_thread(client.open)
        await eventually(lambda: not client.messages.empty())
        request = client.messages.get_nowait()
        assert request["header"]["API_NO"] == "A1051"
        assert request["attributes"] == {"A1051.0001": 168}
        assert pairing.connected and not pairing.complete
        assert service.states[client.serial].prefilter_cycle is None
        assert not service.downloads
        reply = {
            "header": {**request["header"], "API_NO": "A1050", "requestId": "unrelated"},
            "attributes": {"A1050.0001": 168},
        }
        await asyncio.to_thread(client.publish, topic("BEvent", client.serial), json.dumps(reply))
        await eventually(lambda: service.states[client.serial].prefilter_cycle == 168)
        assert not pairing.complete
        assert service.devices[client.serial]["prefilter_default_pending"]
        reply["header"]["requestId"] = request["header"]["requestId"]
        client.respond = True
        await asyncio.to_thread(client.publish, topic("BEvent", client.serial), json.dumps(reply))
        await eventually(lambda: pairing.complete)
        stored = pki.load_state(service.root)["devices"][client.serial]
        assert stored["prefilter_cycle"] == 168
        assert "prefilter_default_pending" not in stored
    finally:
        await asyncio.to_thread(client.close)


async def test_unconfirmed_default_retries_after_restart(service):
    pairing, _ = await enroll(service)
    client = await asyncio.to_thread(Fan, service.root, service.config.mqtt_port, respond=False)
    try:
        await asyncio.to_thread(client.open)
        await eventually(lambda: not client.messages.empty())
        assert client.messages.get_nowait()["header"]["API_NO"] == "A1051"
        assert not pairing.complete
        await asyncio.to_thread(client.close)
        await service.stop()
        assert pki.load_state(service.root)["devices"][client.serial]["prefilter_default_pending"]
        await service.start()
        assert service.states[client.serial].prefilter_cycle is None
        client.respond = True
        await asyncio.to_thread(client.open)
        await eventually(lambda: bool(service.states[client.serial].settings))
        assert service.states[client.serial].prefilter_cycle == 168
        assert client.messages.get_nowait()["header"]["API_NO"] == "A1051"
        assert not service.devices[client.serial].get("prefilter_default_pending")
    finally:
        await asyncio.to_thread(client.close)


async def test_wrong_value_does_not_complete_enrollment(service):
    pairing, _ = await enroll(service)
    client = await asyncio.to_thread(Fan, service.root, service.config.mqtt_port)
    client.prefilter_reply = 224
    try:
        await asyncio.to_thread(client.open)
        await eventually(lambda: service.states[client.serial].prefilter_cycle == 224)
        assert not pairing.complete
        assert service.devices[client.serial]["prefilter_default_pending"]
        client.prefilter_reply = None
        await service.refresh(client.serial)
        assert pairing.complete
        assert service.states[client.serial].prefilter_cycle == 168
    finally:
        await asyncio.to_thread(client.close)
