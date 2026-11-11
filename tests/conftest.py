import asyncio
import base64
import json
import queue
import socket
import ssl

import aiohttp
import paho.mqtt.client as mqtt
import pytest

from custom_components.coway_local.broker import subscriptions, topic
from custom_components.coway_local.service import LocalService, ServerConfig


def free_ports():
    sockets = [socket.socket() for _ in range(3)]
    try:
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


@pytest.fixture
async def service(tmp_path):
    instance = LocalService(tmp_path, ServerConfig("127.0.0.1", *free_ports(), "127.0.0.1"))
    await instance.start()
    yield instance
    await instance.stop()


async def eventually(predicate, timeout=5):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.02)


async def enroll(
    service, serial="TEST000001", mac="001122334455", pairing=None, bluetooth_name="AP-TEST_334455"
):
    pairing = pairing or service.begin_pairing(serial, "Test fan")
    context = await asyncio.to_thread(ssl.create_default_context, cafile=service.root / "ca.pem")
    encoded = base64.urlsafe_b64encode(bluetooth_name.encode()).decode().rstrip("=")
    url = service.setup_bundle(pairing)["certSvrUrl"] + "/" + encoded
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=context)) as client:
        async with client.post(
            url,
            json={
                "serial": serial,
                "macAddr": mac,
                "certToken": pairing.token,
            },
        ) as response:
            assert response.status == 200
            result = await response.json()
            assert result["payload"]["certSvrUrl"] == url
        for key in ("certUrl", "privateUrl"):
            async with client.get(result["payload"][key]) as response:
                assert response.status == 200
                assert b"-----BEGIN" in await response.read()
    return pairing, result["payload"]


class Fan:
    """A real MQTT 3.1.1/TLS client with synthetic identities and firmware replies."""

    def __init__(self, root, port, serial="TEST000001", certificate=None, respond=True):
        self.serial = serial
        self.respond = respond
        self.prefilter_reply = None
        self.port = port
        self.connections, self.subacks, self.messages = queue.Queue(), queue.Queue(), queue.Queue()
        self.settings = {"0001": 1, "0002": 0, "0003": 1, "0007": 0, "0008": 0, "000A": 3}
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=serial,
            protocol=mqtt.MQTTv311,
            reconnect_on_failure=False,
        )
        context = ssl.create_default_context(cafile=root / "ca.pem")
        credential = certificate or serial
        context.load_cert_chain(
            root / "devices" / f"{credential}.pem", root / "devices" / f"{credential}.key"
        )
        context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_2
        context.set_ciphers("AES128-SHA256")
        self.client.tls_set_context(context)
        self.client.on_connect = lambda c, u, f, r, p: self.connections.put(not r.is_failure)
        self.client.on_subscribe = lambda c, u, m, r, p: self.subacks.put([v.is_failure for v in r])
        self.client.on_message = self.message

    def open(self, accepted=True):
        self.client.connect("127.0.0.1", self.port, 20)
        self.client.loop_start()
        if accepted:
            assert self.connections.get(timeout=4)
            for name in subscriptions(self.serial):
                self.subscribe(name)
        return self

    def subscribe(self, name, accepted=True):
        self.client.subscribe(name, 1)
        failed = self.subacks.get(timeout=4)
        assert all(failed) != accepted

    def publish(self, name, payload):
        result = self.client.publish(name, payload, qos=1)
        result.wait_for_publish(timeout=4)
        assert result.is_published()

    def report(self, attributes):
        self.publish(
            topic("BEvent", self.serial),
            json.dumps(
                {"header": {"prodId": self.serial, "API_NO": "A1020"}, "attributes": attributes}
            ),
        )

    def message(self, client, userdata, message):
        body = json.loads(message.payload)
        self.messages.put(body)
        if not self.respond:
            return
        header = body["header"].copy()
        api = header["API_NO"]
        if api == "A1011":
            self.settings.update({k.split(".")[1]: v for k, v in body["attributes"].items()})
            if "A1011.0003" in body["attributes"]:
                self.settings["0002"] = 0
        reply = {"A1011": "A1010", "A1013": "A1012", "A1051": "A1050"}[api]
        header["API_NO"] = reply
        attrs = (
            {f"{reply}.{k}": v for k, v in self.settings.items()}
            if api != "A1051"
            else {
                "A1050.0001": (
                    body["attributes"]["A1051.0001"]
                    if self.prefilter_reply is None else self.prefilter_reply
                )
            }
        )
        client.publish(
            topic("BEvent", self.serial), json.dumps({"header": header, "attributes": attrs}), qos=1
        )

    def close(self):
        self.client.disconnect()
        self.client.loop_stop()


@pytest.fixture
async def fan(service):
    await enroll(service)
    client = await asyncio.to_thread(Fan, service.root, service.config.mqtt_port)
    await asyncio.to_thread(client.open)
    await eventually(lambda: bool(service.states[client.serial].settings))
    yield client
    await asyncio.to_thread(client.close)
