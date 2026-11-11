// Enrollment data stays in memory. No HA access token or Wi-Fi password belongs here.
import {canonicalMac, text} from './protocol.mjs';

export function readIdentity(advertisedName, fields) {
  const mac = canonicalMac(text.decode(fields[2]));
  // FFA0 field 1 is the module SSID (COWAYxxxxxx), not the AP-1022K model.
  if (!advertisedName?.startsWith('AP-1022K') || !/^[A-F0-9]{12}$/.test(mac))
    throw new Error('Unsupported device. This page supports AP-1022K only.');
  return {name: advertisedName, mac, moduleName: text.decode(fields[1])};
}

export function validateBundle(value, now = Date.now()) {
  if (!value || value.v !== 1 || value.model !== 'AP-1022K'
      || !/^[A-Za-z0-9_-]{6,32}$/.test(value.serial ?? '')
      || !/^[A-Za-z0-9_-]{32}$/.test(value.certToken ?? '')
      || typeof value.name !== 'string' || value.name.length > 80
      || !Number.isSafeInteger(value.expiresAt)) throw new Error('Invalid setup link. Create a new one in Home Assistant.');
  if (value.expiresAt <= now) throw new Error('This setup link expired. Create a new one in Home Assistant.');
  const ca = new URL(value.caUrl), cert = new URL(value.certSvrUrl);
  if (ca.protocol !== 'http:' || cert.protocol !== 'https:'
      || ca.hostname !== cert.hostname || !/^\d+\.\d+\.\d+\.\d+$/.test(ca.hostname)
      || ca.pathname !== '/ca.pem' || cert.pathname !== '/iot/v1/cert/r0'
      || [ca, cert].some(u => u.username || u.password || u.search || u.hash
          || Number(u.port) < 1024 || Number(u.port) > 65535)
      || ca.port === cert.port) throw new Error('Invalid local server addresses in setup link.');
  return Object.freeze({
    v: 1, model: value.model, serial: value.serial, name: value.name,
    certToken: value.certToken, expiresAt: value.expiresAt,
    caUrl: ca.href, certSvrUrl: cert.href,
  });
}

export function decodeSetup(fragment, now = Date.now()) {
  const params = new URLSearchParams(fragment.replace(/^#/, ''));
  const encoded = params.get('setup');
  if (!encoded || encoded.length > 4096 || !/^[A-Za-z0-9_-]+$/.test(encoded))
    throw new Error('Open the setup link from Home Assistant → Coway Local → Configure → Add fan.');
  try {
    const bytes = Uint8Array.from(atob(encoded.replaceAll('-', '+').replaceAll('_', '/')), c => c.charCodeAt(0));
    return validateBundle(JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(bytes)), now);
  } catch (error) {
    if (error instanceof SyntaxError || error.name === 'InvalidCharacterError')
      throw new Error('Invalid setup link. Create a new one in Home Assistant.');
    throw error;
  }
}

export function wifiConfig(bundle, identity, network, password, now = Date.now()) {
  validateBundle(bundle, now);
  if (!identity?.name?.startsWith('AP-1022K') || !/^[A-F0-9]{12}$/.test(identity.mac))
    throw new Error('This setup page supports the observed AP-1022K only.');
  if (!network || !network.ssid || new TextEncoder().encode(network.ssid).length > 32
      || !/^[A-Fa-f0-9]{12}$/.test(network.bssid) || network.channel > 14)
    throw new Error('Select a 2.4 GHz Wi-Fi network from the fan’s scan.');
  const length = new TextEncoder().encode(password).length;
  if (network.security && (length < 8 || length > 63))
    throw new Error('Enter an 8–63 byte Wi-Fi password.');
  return {
    cmd: 2, type: 1, serial: bundle.serial, macAddr: identity.mac,
    ssid: network.ssid, bssid: network.bssid, pwd: password,
    caUrl: bundle.caUrl, certSvrUrl: bundle.certSvrUrl, certToken: bundle.certToken,
  };
}
