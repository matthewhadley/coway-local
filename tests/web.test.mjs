import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {decodeSetup, readIdentity, validateBundle, wifiConfig} from '../web/bootstrap.mjs';
import {p001, p002, utf8, hex, fragments, Reassembler, decodeProto} from '../web/protocol.mjs';

const now = 1800000000000;
const bundle = {
  v: 1, model: 'AP-1022K', name: 'Test fan', serial: 'TEST000001',
  certToken: 'a'.repeat(32), expiresAt: now + 900000,
  caUrl: 'http://192.0.2.1:8080/ca.pem',
  certSvrUrl: 'https://192.0.2.1:9443/iot/v1/cert/r0',
};
test('P001 and AES-CBC P002 match the independently generated protocol fixture', async () => {
  const fixture = JSON.parse(await readFile(new URL('protocol-fixture.json', import.meta.url)));
  assert.equal(hex(p001(utf8.encode(fixture.key))), fixture.p001);
  const message = await p002(fixture.config, utf8.encode(fixture.key), utf8.encode(fixture.iv));
  assert.equal(hex(message), fixture.p002);
  const assembler = new Reassembler();
  const packets = fragments(message);
  assert.ok(packets.every(p => p.length <= 20));
  for (const packet of packets.slice(0, -1)) assert.equal(assembler.feed(packet), null);
  assert.equal(hex(assembler.feed(packets.at(-1))), fixture.p002);
});
test('fragment decoder supports UTF-8 without putting credentials in a query', () => {
  const input = {...bundle, name: 'Bedroom · 空气'};
  const encoded = Buffer.from(JSON.stringify(input)).toString('base64url');
  assert.deepEqual(decodeSetup('#setup=' + encoded, now), input);
});
test('expired and malformed destinations are rejected before Bluetooth writes', () => {
  for (const patch of [
    {expiresAt: now}, {v: 2}, {serial: '../../secret'}, {certToken: 'bad'},
    {certSvrUrl: 'http://192.0.2.1:9443/iot/v1/cert/r0'},
    {certSvrUrl: 'https://192.0.2.2:9443/iot/v1/cert/r0'},
    {caUrl: 'http://user:secret@192.0.2.1:8080/ca.pem'},
    {caUrl: 'http://192.0.2.1:8080/ca.pem?secret=x'},
  ]) assert.throws(() => validateBundle({...bundle, ...patch}, now));
});
test('only tested model, valid scanned 2.4 GHz network, and current token can be sent', () => {
  const identity = {name: 'AP-1022K_TEST', mac: '001122334455'};
  const network = {ssid: 'Example', bssid: 'aabbccddeeff', channel: 6, security: 4};
  const config = wifiConfig(bundle, identity, network, 'testwifi', now);
  assert.equal(config.pwd, 'testwifi');
  assert.equal(config.certToken, bundle.certToken);
  assert.throws(() => wifiConfig(bundle, identity, {...network, channel: 36}, 'testwifi', now));
  assert.throws(() => wifiConfig(bundle, {...identity, name: 'OTHER'}, network, 'testwifi', now));
  assert.throws(() => wifiConfig(bundle, identity, network, 'testwifi', now + 900001));
});
test('malformed BLE frames and protobuf fail closed', () => {
  assert.throws(() => decodeProto(new Uint8Array([0x12, 0xff])));
  const frames = fragments(utf8.encode('a'.repeat(100)));
  assert.throws(() => new Reassembler().feed(frames[1]));
});
test('the module SSID differs from the advertised product model', () => {
  const identity = readIdentity('AP-1022K_334455', {
    1: utf8.encode('COWAY334455'), 2: utf8.encode('001122334455'),
  });
  assert.equal(identity.name, 'AP-1022K_334455');
  assert.equal(identity.moduleName, 'COWAY334455');
  assert.equal(identity.mac, '001122334455');
  assert.throws(() => readIdentity('AP-OTHER_334455', {
    1: utf8.encode('COWAY334455'), 2: utf8.encode('001122334455'),
  }));
});
