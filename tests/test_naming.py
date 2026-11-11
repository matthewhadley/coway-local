import asyncio
import base64
import copy
import ssl

import aiohttp
import pytest

from custom_components.coway_local import pki
from custom_components.coway_local.naming import catalog_name

from .conftest import enroll

ICON_SERIAL = "00002FJ30000000001"


def test_verified_catalog_uses_only_the_documented_serial_position():
    assert catalog_name(ICON_SERIAL) == "Coway Airmega IconS"
    assert catalog_name("00002F9R0000000001") == "Coway Airmega 250S"
    for serial in ("TEST000001", "02FJ3", "02FJ300000000000000", "000XXXXX02FJ300001"):
        assert catalog_name(serial) is None


async def test_authenticated_enrollment_uses_catalog_then_bluetooth(service):
    pairing = service.begin_pairing(ICON_SERIAL)
    assert pairing.name == "Coway Airmega IconS"
    assert service.setup_bundle(pairing)["bluetoothNameInUrl"]
    assert not service.setup_bundle(pairing)["useBluetoothName"]
    await enroll(service, serial=ICON_SERIAL, pairing=pairing, bluetooth_name="AP-1022K_334455")
    record = service.devices[ICON_SERIAL]
    assert record["name"] == "Coway Airmega IconS"
    assert record["name_source"] == "catalog"
    assert record["bluetooth_name"] == "AP-1022K_334455"
    other = service.begin_pairing("OTHER00001")
    assert service.setup_bundle(other)["useBluetoothName"]
    await enroll(service, "OTHER00001", "001122334466", other, "Purifier · 空气")
    assert service.devices[other.serial]["name"] == "Purifier · 空气"
    assert service.devices[other.serial]["name_source"] == "bluetooth"
    await service.stop()
    await service.start()
    assert service.devices[ICON_SERIAL]["name"] == "Coway Airmega IconS"
    assert service.devices[other.serial]["name"] == "Purifier · 空气"


async def test_custom_names_and_bluetooth_names_survive_reenrollment(service):
    pairing = service.begin_pairing("TEST000001")
    await enroll(service, pairing=pairing, bluetooth_name="AP-OTHER_334455")
    pairing = service.begin_pairing("TEST000001")
    await enroll(service, pairing=pairing, bluetooth_name="Renamed purifier")
    assert service.devices[pairing.serial]["name"] == "Renamed purifier"
    pairing = service.begin_pairing("TEST000001", "Bedroom")
    await enroll(service, pairing=pairing, bluetooth_name="AP-OTHER_334455")
    pairing = service.begin_pairing("TEST000001", "")
    assert pairing.name == "Bedroom"
    assert not service.setup_bundle(pairing)["useBluetoothName"]
    await enroll(service, pairing=pairing, bluetooth_name="Different Bluetooth label")
    assert service.devices[pairing.serial]["name"] == "Bedroom"
    assert service.devices[pairing.serial]["name_source"] == "custom"
    # Explicit choices also outrank the catalog, including an intentional "Coway".
    custom = service.begin_pairing(ICON_SERIAL, "Coway")
    await enroll(service, ICON_SERIAL, "001122334466", custom, "AP-1022K_334466")
    await service.stop()
    await service.start()
    assert service.devices[ICON_SERIAL]["name"] == "Coway"
    assert service.devices[pairing.serial]["name"] == "Bedroom"


async def test_old_generic_names_migrate_without_touching_credentials_or_custom_names(service):
    pairing = service.begin_pairing(ICON_SERIAL)
    await enroll(service, serial=ICON_SERIAL, pairing=pairing)
    await enroll(service, "OTHER00001", "001122334466")
    await service.stop()
    saved = pki.load_state(service.root)
    for serial, record in saved["devices"].items():
        for key in ("name_source", "custom_name", "bluetooth_name"):
            record.pop(key, None)
        record["name"] = "Coway" if serial == ICON_SERIAL else "Study fan"
    fingerprints = {key: value["fingerprint"] for key, value in saved["devices"].items()}
    pki.save_state(service.root, saved)
    await service.start()
    assert service.devices[ICON_SERIAL]["name"] == "Coway Airmega IconS"
    assert service.devices["OTHER00001"]["name"] == "Study fan"
    assert {key: value["fingerprint"] for key, value in service.devices.items()} == fingerprints
    assert pki.load_state(service.root)["devices"] == service.devices
    assert service.begin_pairing("OTHER00001").name == "Study fan"


async def test_name_transport_requires_valid_identity_and_rejects_malformed_labels(service):
    pairing = service.begin_pairing("TEST000001")
    await enroll(service, pairing=pairing, bluetooth_name="AP-OTHER_334455")
    before = copy.deepcopy(service.devices)
    tls = await asyncio.to_thread(ssl.create_default_context, cafile=service.root / "ca.pem")
    base = f"https://127.0.0.1:{service.config.https_port}/n/"
    body = {"certToken": pairing.token, "serial": pairing.serial, "macAddr": pairing.mac}
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=tls)) as client:
        for data in (b"", b"\xff", b"\0name", b"x" * 81, b"  "):
            label = base64.urlsafe_b64encode(data).decode().rstrip("=") or "="
            async with client.post(base + label, json=body) as response:
                assert response.status == 400
        for bad_body in ({}, {**body, "certToken": "wrong"}, {**body, "macAddr": "001122334466"}):
            async with client.post(base + "TmV3IG5hbWU", json=bad_body) as response:
                assert response.status == 403
        http = base.replace("https:", "http:").replace(
            str(service.config.https_port), str(service.config.http_port)
        )
        async with client.post(http + "TmV3IG5hbWU", json=body) as response:
            assert response.status == 404
    assert service.devices == before
    for name in ("x" * 81, "Bad\nname"):
        with pytest.raises(ValueError):
            service.begin_pairing("OTHER00002", name)
