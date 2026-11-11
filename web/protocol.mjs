// Coway FFC0/P001/P002 codec. No browser UI or network dependencies.
export const utf8 = new TextEncoder();
export const text = new TextDecoder();
export const uuid = short => `0000${short}-0000-1000-8000-00805f9b34fb`;
export const FIELDS = {1:'cmd',2:'ssid',3:'pwd',4:'bssid',5:'type',6:'ip',7:'gateway',8:'subnet',9:'dns',10:'macAddr',11:'caUrl',12:'certSvrUrl',13:'certToken',14:'serial',15:'caFile'};
export const FAILURE_CODES = new Set([1,2,3,4,5,6,11,12,21,22,23,24,25,26,27,28,29,30,31,41,42,43,44,51,52,73]);
export const STATUS = {1:'Wi-Fi association failed',2:'Wi-Fi association failed',3:'Wi-Fi association failed',4:'Wi-Fi association failed',5:'DHCP failed',6:'Configuration rejected',10:'Wi-Fi connected',11:'CA server unreachable',12:'CA download failed',20:'CA downloaded',21:'Certificate server unreachable',30:'Certificate token rejected',40:'Certificate server accepted setup',41:'Certificate download unreachable',42:'Certificate download failed',43:'Private-key download unreachable',44:'Private-key download failed',50:'Device credentials downloaded',51:'Broker DNS failed',52:'Broker connection failed',61:'Local MQTT broker connected',71:'Setup initialized',72:'Bluetooth key accepted',73:'Bluetooth key rejected'};

export function bytes(value) {
  if (value instanceof DataView) return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  if (value instanceof Uint8Array) return value;
  if (typeof value === 'string') return utf8.encode(value);
  return new Uint8Array(value);
}
export function concat(...parts) {
  const data = parts.map(bytes);
  const result = new Uint8Array(data.reduce((n, p) => n + p.length, 0));
  let offset = 0;
  for (const part of data) { result.set(part, offset); offset += part.length; }
  return result;
}
export const base64 = data => btoa(Array.from(bytes(data), b => String.fromCharCode(b)).join(''));
export const unbase64 = data => Uint8Array.from(atob(data), c => c.charCodeAt(0));
export const hex = data => Array.from(bytes(data), b => b.toString(16).padStart(2,'0')).join('');

function varint(value) {
  if (!Number.isSafeInteger(value) || value < 0) throw new Error('Invalid protobuf integer');
  const result = [];
  while (value > 127) { result.push((value % 128) | 128); value = Math.floor(value / 128); }
  return Uint8Array.from([...result, value]);
}
export function encodeProto(fields) {
  const result = [];
  for (const number of Object.keys(fields).map(Number).sort((a,b) => a-b)) {
    const value = fields[number];
    if (typeof value === 'number') {
      if (value) result.push(varint(number*8), varint(value));
    } else {
      const data = bytes(value);
      if (data.length) result.push(varint(number*8+2), varint(data.length), data);
    }
  }
  return concat(...result);
}
export function decodeProto(input) {
  const data = bytes(input), fields = {};
  let offset = 0;
  function read() {
    let value = 0, multiplier = 1;
    for (let i=0; i<8; i++) {
      if (offset >= data.length) throw new Error('Truncated protobuf integer');
      const byte = data[offset++]; value += (byte & 127)*multiplier;
      if (!Number.isSafeInteger(value)) throw new Error('Oversized protobuf integer');
      if (!(byte & 128)) return value;
      multiplier *= 128;
    }
    throw new Error('Oversized protobuf integer');
  }
  while (offset < data.length) {
    const tag = read(), field = Math.floor(tag/8), wire = tag%8;
    if (!field || Object.hasOwn(fields, field)) throw new Error('Invalid or duplicate protobuf field');
    if (wire === 0) fields[field] = read();
    else if (wire === 2) {
      const length = read();
      if (offset+length > data.length) throw new Error('Truncated protobuf field');
      fields[field] = data.slice(offset, offset+length); offset += length;
    } else throw new Error('Unsupported protobuf field');
  }
  return fields;
}
export function randomLetters(length) {
  const out = [];
  while (out.length < length) {
    for (const b of crypto.getRandomValues(new Uint8Array(32))) {
      if (b < 234) out.push(97+b%26);
      if (out.length === length) break;
    }
  }
  return Uint8Array.from(out);
}
export const canonicalMac = mac => mac.replaceAll(':','').toUpperCase();
export function p001(key) {
  if (bytes(key).length !== 20) throw new Error('Handshake key must be 20 bytes');
  return concat('P001', encodeProto({1:1,2:base64(key)}));
}
export function configProto(config) {
  const fields = {};
  for (const [number,name] of Object.entries(FIELDS)) if (name in config) fields[number] = config[name];
  fields[1] = 2; fields[5] ??= 1;
  return encodeProto(fields);
}
export async function p002(config, key, iv=randomLetters(16)) {
  const mac = canonicalMac(config.macAddr);
  if (!/^[0-9A-F]{12}$/.test(mac) || bytes(key).length !== 20 || bytes(iv).length !== 16) throw new Error('Invalid encryption inputs');
  const aes = await crypto.subtle.importKey('raw', concat(key,mac), 'AES-CBC', false, ['encrypt']);
  // Web Crypto AES-CBC applies PKCS#7 padding itself.
  const encrypted = await crypto.subtle.encrypt({name:'AES-CBC',iv:bytes(iv)}, aes, configProto(config));
  return concat('P002', base64(concat(iv,encrypted)));
}
export function fragments(input, valueSize=20) {
  const data = bytes(input), size = valueSize-4;
  if (!Number.isInteger(valueSize) || valueSize<20 || valueSize>509) throw new Error('Invalid GATT value size');
  const count = Math.ceil(data.length/size);
  if (count<1 || count>4096) throw new Error('Invalid fragment count');
  return Array.from({length:count}, (_,i) => {
    const body = data.slice(i*size,(i+1)*size), result = new Uint8Array(4+body.length);
    const view = new DataView(result.buffer);
    view.setUint16(0,count,true); view.setUint16(2,i+1,true); result.set(body,4);
    return result;
  });
}
export class Reassembler {
  constructor() { this.parts=[]; this.count=0; this.size=0; }
  feed(input) {
    const data=bytes(input);
    if (data.length<4) throw new Error('Truncated Coway fragment');
    const view=new DataView(data.buffer,data.byteOffset,data.byteLength);
    const count=view.getUint16(0,true), index=view.getUint16(2,true);
    if (count<1 || count>4096 || index<1 || index>count) throw new Error('Invalid fragment header');
    if (index===1) {
      if (this.parts.length) throw new Error('Previous message was incomplete');
      this.count=count;
    }
    if (count!==this.count || index!==this.parts.length+1) throw new Error('Out-of-order fragment');
    this.parts.push(data.slice(4)); this.size+=data.length-4;
    if (this.size>65536) throw new Error('Coway message too large');
    if (index!==count) return null;
    const result=concat(...this.parts); this.parts=[]; this.count=0; this.size=0;
    return result;
  }
}
export function parseScan(input) {
  const data=bytes(input), result=[];
  if (text.decode(data.slice(0,16))!=='*ICT*SCANRESULT:') throw new Error('Unexpected Wi-Fi scan response');
  for(let offset=16; offset+48<=data.length; offset+=48) {
    const item=data.slice(offset,offset+48);
    if (text.decode(item.slice(0,4))==='[OK]') break;
    const view=new DataView(item.buffer,item.byteOffset,item.byteLength);
    const length=view.getUint16(2,true);
    if(length>32) throw new Error('Invalid SSID length');
    result.push({ssid:text.decode(item.slice(4,4+length)),bssid:hex(item.slice(36,42)),rssi:view.getInt32(42,true),security:item[46],channel:item[47]});
  }
  return result;
}
