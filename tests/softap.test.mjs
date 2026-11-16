// Runs web/v1/softap.sh against tests/fake-fan.mjs, and checks the fan
// receives what the setup page's wifiConfig sends for the same choices.
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { fileURLToPath } from 'node:url';
import { encodeSetup, softapCommand, wifiConfig } from '../web/v1/bootstrap.mjs';

const SCRIPT = fileURLToPath(new URL('../web/v1/softap.sh', import.meta.url));
const FAKE_FAN = fileURLToPath(new URL('./fake-fan.mjs', import.meta.url));
const MAC = '8472076294F3';

const bundle = {
  v: 1, model: 'AP-1022K',
  certToken: 'a'.repeat(16) + 'b_-9'.repeat(4), expiresAt: Date.now() + 900000,
  caUrl: 'http://192.0.2.1:8080/ca.pem',
  certSvrUrl: 'https://192.0.2.1:9443/n',
  returnUrl: 'http://homeassistant.local:8123/api/coway_local/provisioning/return?flow_id=' + 'b'.repeat(32) + '&state=' + 'c'.repeat(32),
};
// Encoded directly, so links the setup page would refuse can be made too.
const link = value => 'https://example.github.io/coway-local/v1/#setup='
  + Buffer.from(JSON.stringify(value)).toString('base64url');
// The argument the setup page's command passes.
const commandSetup = () => {
  const command = softapCommand(bundle, 'https://example.github.io/coway-local/v1/softap.sh');
  return command.match(/bash -s -- '([^']+)'$/)[1];
};

function run(args, input, env = {}) {
  const child = spawn('bash', [SCRIPT, '--host', '127.0.0.1', '--mac', MAC, '--no-open', ...args],
    { env: { ...process.env, ...env } });
  let stdout = '', stderr = '';
  child.stdout.on('data', d => { stdout += d; });
  child.stderr.on('data', d => { stderr += d; });
  child.stdin.end(input);
  return once(child, 'exit').then(([code]) => ({ code, stdout, stderr }));
}

let fan, fanOutput = '';
test.before(async () => {
  fan = spawn(process.execPath, [FAKE_FAN, MAC]);
  fan.stdout.on('data', d => { fanOutput += d; });
  while (!fanOutput.includes('listening')) await once(fan.stdout, 'data');
});
test.after(() => fan.kill());

async function provisioned(args, input, env) {
  const start = fanOutput.length;
  const result = await run(args, input, env);
  assert.equal(result.code, 0, result.stderr);
  // The fake fan prints after a short pause that marks the end of a message.
  for (let i = 0; i < 20 && !fanOutput.slice(start).includes('P002: '); i++)
    await new Promise(resolve => setTimeout(resolve, 100));
  const line = fanOutput.slice(start).split('\n').find(l => l.startsWith('P002: '));
  assert.ok(line, fanOutput.slice(start));
  return { ...result, fields: JSON.parse(line.slice(6)) };
}

const expected = (network, password, name) => Object.fromEntries(Object.entries(
  wifiConfig(bundle, { mac: MAC, name }, network, password)).filter(([, v]) => v !== ''));

test('sends the setup page settings for a secured network, strongest first', async () => {
  assert.equal(commandSetup(), encodeSetup(bundle));
  const { fields, stdout } = await provisioned([commandSetup()], '\n\n', { COWAY_WIFI_PASSWORD: 'hunter2-pass' });
  assert.match(stdout, /Setup key: cmd 1, ok 1, code 61/);
  assert.deepEqual(fields, expected({ ssid: 'home-2.4', bssid: '0A0000000001', channel: 6, security: 4 }, 'hunter2-pass', 'Coway 6294F3'));
});

test('omits the password for an open network and carries a long name', async () => {
  const name = 'N'.repeat(80);
  const { fields } = await provisioned(['--name', name, link(bundle)], '\n2\n');
  assert.equal(fields.pwd, undefined);
  assert.ok(fields.certSvrUrl.length > 127);
  assert.deepEqual(fields, expected({ ssid: 'guest', bssid: '0A0000000003', channel: 1, security: 0 }, '', name));
});

test('reads the password from its prompt', async () => {
  const { fields } = await provisioned([link(bundle)], '\n3\nsecond-pass\n');
  assert.equal(fields.pwd, 'second-pass');
  assert.equal(fields.bssid, '0A0000000002');
});

test('refuses links the setup page would refuse', async () => {
  for (const [value, message] of [
    [{ ...bundle, expiresAt: 1000 }, /expired/],
    [{ ...bundle, v: 2 }, /does not match your Coway Local version/],
    [{ ...bundle, caUrl: 'http://example.com:8080/ca.pem' }, /local server address/],
    [{ ...bundle, certSvrUrl: 'https://192.0.2.2:9443/n' }, /local server address/],
    [{ ...bundle, returnUrl: 'http://homeassistant.local:8123/elsewhere' }, /return address/],
    [{ ...bundle, certToken: 'short' }, /invalid setup link/],
  ]) {
    const { code, stderr } = await run([link(value)], '');
    assert.equal(code, 1);
    assert.match(stderr, message);
  }
  const { code, stderr } = await run(['https://example.github.io/coway-local/v1/'], '');
  assert.equal(code, 1);
  assert.match(stderr, /no #setup= part/);
});

test('refuses a short password and a name over 80 characters', async () => {
  let result = await run([link(bundle)], '\n\nshort\n');
  assert.match(result.stderr, /8-63 bytes/);
  result = await run(['--name', 'N'.repeat(81), link(bundle)], '\n');
  assert.match(result.stderr, /1-80 characters/);
});
