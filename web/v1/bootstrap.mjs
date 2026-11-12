// Enrollment data stays in memory. No HA access token or Wi-Fi password belongs here.
import { canonicalMac, localSerial, text, uuid } from './protocol.mjs?v=0.5.1';

// Setup-link format served by this directory (v1/). Must match SETUP_FORMAT in const.py.
export const FORMAT = 1;

export function requestFan(bluetooth) {
  // Keep this synchronous so Chrome's chooser retains the click's user activation.
  return bluetooth.requestDevice({
    // IoCare's normal-device scan parser accepts these manufacturer layouts.
    // Zero mask bytes leave model/product bytes unrestricted but require length.
    // See BLE_DISCOVERY.md; names and Coway's cloud catalog are not gates here.
    filters: [
      {
        manufacturerData: [{
          companyIdentifier: 0x0639,
          dataPrefix: new Uint8Array([0, 0x40, 0, 0, 0, 0, 0]),
          mask: new Uint8Array([0, 0xff, 0, 0, 0, 0, 0]),
        }]
      },
      {
        manufacturerData: [{
          companyIdentifier: 0xffff,
          dataPrefix: new Uint8Array(8),
          mask: new Uint8Array(8),
        }]
      },
    ],
    optionalServices: [uuid('ffc0'), uuid('ffc1'), uuid('ffc3')],
  });
}

export function readIdentity(advertisedName, fields) {
  if (!(fields?.[2] instanceof Uint8Array)
    || (fields[1] !== undefined && !(fields[1] instanceof Uint8Array)))
    throw new Error('The device did not return a valid Coway Bluetooth identity.');
  const mac = canonicalMac(text.decode(fields[2]));
  if (!/^[A-F0-9]{12}$/.test(mac))
    throw new Error('The device did not return a valid Wi-Fi MAC address.');
  // Names are display labels, not evidence of protocol compatibility.
  // FFA0 field 1 is the module SSID (often COWAYxxxxxx), not the product model.
  const moduleName = fields[1] ? text.decode(fields[1]) : '';
  const name = typeof advertisedName === 'string' && advertisedName.trim()
    ? advertisedName : moduleName || 'Unnamed device';
  return { name, mac, moduleName };
}

export function validateBundle(value, now = Date.now()) {
  if (value?.v !== FORMAT) throw new Error('This setup page does not match your Coway Local version. Create a new setup link in Home Assistant.');
  if (!value || typeof value.model !== 'string'
    || !value.model.trim() || value.model.length > 80
    || !/^[A-Za-z0-9_-]{32}$/.test(value.certToken ?? '')
    || !Number.isSafeInteger(value.expiresAt))
    throw new Error('Invalid setup link. Create a new one in Home Assistant.');
  if (value.expiresAt <= now) throw new Error('This setup link expired. Create a new one in Home Assistant.');
  const ca = new URL(value.caUrl), cert = new URL(value.certSvrUrl);
  if (ca.protocol !== 'http:' || cert.protocol !== 'https:'
    || ca.hostname !== cert.hostname || !/^\d+\.\d+\.\d+\.\d+$/.test(ca.hostname)
    || ca.pathname !== '/ca.pem' || cert.pathname !== '/n'
    || [ca, cert].some(u => u.username || u.password || u.search || u.hash
      || Number(u.port) < 1024 || Number(u.port) > 65535)
    || ca.port === cert.port) throw new Error('Invalid local server addresses in setup link.');
  const back = new URL(value.returnUrl);
  if (!['http:', 'https:'].includes(back.protocol) || !back.hostname
    || back.username || back.password || back.hash
    || back.pathname !== '/api/coway_local/provisioning/return'
    || [...back.searchParams.keys()].sort().join(',') !== 'flow_id,state'
    || !/^[a-f0-9]{32}$/.test(back.searchParams.get('flow_id') ?? '')
    || !/^[A-Za-z0-9_-]{32}$/.test(back.searchParams.get('state') ?? ''))
    throw new Error('Invalid Home Assistant return address. Create a new setup link.');
  return Object.freeze({
    v: FORMAT, model: value.model,
    certToken: value.certToken, expiresAt: value.expiresAt,
    caUrl: ca.href, certSvrUrl: cert.href,
    returnUrl: back.href,
  });
}

export function decodeSetup(fragment, now = Date.now()) {
  const params = new URLSearchParams(fragment.replace(/^#/, ''));
  const encoded = params.get('setup');
  if (!encoded || encoded.length > 4096 || !/^[A-Za-z0-9_-]+$/.test(encoded))
    throw new Error('Open the setup link from Home Assistant → Coway Local → Configure → Add fan.');
  try {
    const bytes = Uint8Array.from(atob(encoded.replaceAll('-', '+').replaceAll('_', '/')), c => c.charCodeAt(0));
    return validateBundle(JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)), now);
  } catch (error) {
    if (error instanceof SyntaxError || error.name === 'InvalidCharacterError')
      throw new Error('Invalid setup link. Create a new one in Home Assistant.');
    throw error;
  }
}

export function wifiConfig(bundle, identity, network, password, now = Date.now()) {
  validateBundle(bundle, now);
  if (!/^[A-F0-9]{12}$/.test(identity?.mac ?? ''))
    throw new Error('Read a valid device identity before sending Wi-Fi settings.');
  if (!network || !network.ssid || new TextEncoder().encode(network.ssid).length > 32
    || !/^[A-Fa-f0-9]{12}$/.test(network.bssid) || network.channel > 14)
    throw new Error('Select a 2.4 GHz Wi-Fi network from the fan’s scan.');
  const length = new TextEncoder().encode(password).length;
  if (network.security && (length < 8 || length > 63))
    throw new Error('Enter an 8–63 byte Wi-Fi password.');
  // The fan carries this label in its existing authenticated enrollment POST.
  // No browser-to-HA request, extra token, or change to credential URLs is needed.
  const name = identity.name?.trim();
  if (!name || [...name].length > 80 || /[\u0000-\u001f\u007f-\u009f]/u.test(name))
    throw new Error('The Bluetooth device must return a name of 1–80 characters without control characters.');
  const encoded = btoa(String.fromCharCode(...new TextEncoder().encode(name)))
    .replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '');
  const url = new URL(bundle.certSvrUrl);
  url.pathname += '/' + encoded;
  return {
    cmd: 2, type: 1, serial: localSerial(identity.mac), macAddr: identity.mac,
    ssid: network.ssid, bssid: network.bssid, pwd: password,
    caUrl: bundle.caUrl, certSvrUrl: url.href, certToken: bundle.certToken,
  };
}
