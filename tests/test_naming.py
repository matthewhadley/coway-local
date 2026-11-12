import asyncio
import base64
import copy
import ssl

import aiohttp

from .conftest import enroll


async def test_bluetooth_names_are_stored_and_follow_reenrollment(service):
    pairing, _ = await enroll(service, bluetooth_name="AP-1022K_334455")
    other, _ = await enroll(service, mac="001122334466", bluetooth_name="Purifier · 空气")
    assert service.devices[pairing.serial]["name"] == "AP-1022K_334455"
    await enroll(service, bluetooth_name="Renamed purifier")
    await service.stop()
    await service.start()
    assert service.devices[pairing.serial]["name"] == "Renamed purifier"
    assert service.devices[other.serial]["name"] == "Purifier · 空气"


async def test_malformed_names_are_rejected_without_changing_the_device(service):
    pairing, _ = await enroll(service)
    before = copy.deepcopy(service.devices)
    tls = await asyncio.to_thread(ssl.create_default_context, cafile=service.root / "ca.pem")
    base = f"https://127.0.0.1:{service.config.https_port}/n/"
    body = {"certToken": pairing.token, "serial": pairing.serial, "macAddr": pairing.mac}
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=tls)) as client:
        for data in (b"", b"\xff", b"\0name", b"x" * 81, b"  "):
            label = base64.urlsafe_b64encode(data).decode().rstrip("=") or "="
            async with client.post(base + label, json=body) as response:
                assert response.status == 400
    assert service.devices == before
