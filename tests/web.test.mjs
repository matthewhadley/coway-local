import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {decodeSetup, readIdentity, requestFan, validateBundle, wifiConfig} from '../web/bootstrap.mjs';
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
    {model: null}, {model: ''}, {model: 'x'.repeat(81)},
    {certSvrUrl: 'http://192.0.2.1:9443/iot/v1/cert/r0'},
    {certSvrUrl: 'https://192.0.2.2:9443/iot/v1/cert/r0'},
    {caUrl: 'http://user:secret@192.0.2.1:8080/ca.pem'},
    {caUrl: 'http://192.0.2.1:8080/ca.pem?secret=x'},
  ]) assert.throws(() => validateBundle({...bundle, ...patch}, now));
});
test('valid device identity, scanned 2.4 GHz network, and current token are required', () => {
  const identity = {name: 'AP-1022K_TEST', mac: '001122334455'};
  const network = {ssid: 'Example', bssid: 'aabbccddeeff', channel: 6, security: 4};
  const config = wifiConfig(bundle, identity, network, 'testwifi', now);
  assert.equal(config.pwd, 'testwifi');
  assert.equal(config.certToken, bundle.certToken);
  assert.throws(() => wifiConfig(bundle, identity, {...network, channel: 36}, 'testwifi', now));
  assert.throws(() => wifiConfig(bundle, {...identity, mac: 'invalid'}, network, 'testwifi', now));
  assert.throws(() => wifiConfig(bundle, null, network, 'testwifi', now));
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
});
test('discovery requests manufacturer-filtered devices synchronously with service permissions', async () => {
  const selected = {name: 'Another purifier'};
  let requested = false;
  const pending = requestFan({requestDevice(options) {
    requested = true;
    assert.equal(options.acceptAllDevices, undefined);
    assert.equal(options.filters.length, 2);
    assert.ok(options.filters.every(filter => !filter.name && !filter.namePrefix && !filter.services));
    assert.equal(options.exclusionFilters, undefined);
    assert.deepEqual(options.optionalServices, [
      '0000ffc0-0000-1000-8000-00805f9b34fb',
      '0000ffc1-0000-1000-8000-00805f9b34fb',
      '0000ffc3-0000-1000-8000-00805f9b34fb',
    ]);
    return Promise.resolve(selected);
  }});
  assert.equal(requested, true);
  assert.equal(await pending, selected);
});
test('advertisement filters admit the captured fan and alternate product codes, excluding unrelated and short data', async () => {
  let filters;
  await requestFan({requestDevice(options) { filters = options.filters; return Promise.resolve({}); }});
  // Web Bluetooth masked-prefix matching; payload excludes the company ID.
  const matches = (company, payload) => filters.some(filter => filter.manufacturerData.every(rule =>
    company === rule.companyIdentifier && payload.length >= rule.dataPrefix.length
    && rule.dataPrefix.every((byte, i) => (payload[i] & rule.mask[i]) === (byte & rule.mask[i]))));
  // Actual AP-1022K advertisement: product/material code 113439, no device identifier.
  const captured = Buffer.from('0016313133343339303030303030303030303030303030c5', 'hex');
  assert.equal(matches(0xffff, captured), true);
  const alternate = Buffer.from(captured);
  alternate.set(utf8.encode('999999'), 2);
  assert.equal(matches(0xffff, alternate), true);
  assert.equal(matches(0xffff, captured.subarray(0, 7)), false);
  const newerLayout = Uint8Array.from([0, 0x40, ...utf8.encode('ABCDE')]);
  assert.equal(matches(0x0639, newerLayout), true);
  assert.equal(matches(0x0639, newerLayout.subarray(0, 6)), false);
  newerLayout[1] = 0x41;
  assert.equal(matches(0x0639, newerLayout), false);
  for (const company of [0x004c, 0x05a7, 0x0065, 0x0ba9, 0x047f, 0x0334, 0x07e0, 0x8842])
    assert.equal(matches(company, captured), false);
});
test('different advertised names and model labels can reach Wi-Fi configuration', () => {
  const network = {ssid: 'Example', bssid: 'aabbccddeeff', channel: 6, security: 4};
  for (const name of ['AP-OTHER_334455', 'Bedroom purifier', '', undefined]) {
    const identity = readIdentity(name, {
      1: utf8.encode('COWAY334455'), 2: utf8.encode('00:11:22:33:44:55'),
    });
    const input = {...bundle, model: 'Experimental model'};
    const encoded = Buffer.from(JSON.stringify(input)).toString('base64url');
    const decoded = decodeSetup('#setup=' + encoded, now);
    const config = wifiConfig(decoded, identity, network, 'testwifi', now);
    assert.equal(identity.name, name || 'COWAY334455');
    assert.equal(config.macAddr, '001122334455');
    assert.equal(config.serial, bundle.serial);
    assert.equal(config.pwd, 'testwifi');
  }
  assert.equal(readIdentity(undefined, {2: utf8.encode('001122334455')}).name, 'Unnamed device');
});
test('matching advertised names do not bypass malformed identity responses', () => {
  for (const fields of [
    null, {}, {2: 123}, {2: utf8.encode('not a MAC')},
    {1: 123, 2: utf8.encode('001122334455')},
  ]) assert.throws(() => readIdentity('AP-1022K_334455', fields));
});
