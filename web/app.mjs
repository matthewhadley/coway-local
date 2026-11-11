import {bytes,uuid,p001,p002,randomLetters,fragments,Reassembler,decodeProto,parseScan,STATUS,FAILURE_CODES} from './protocol.mjs';
import {decodeSetup,readIdentity,requestFan,wifiConfig} from './bootstrap.mjs?v=0.2.5';

// Strip the fragment before any Bluetooth interaction; do not persist it.
let setupFragment = location.hash;
history.replaceState(null, '', location.pathname + location.search);

const $ = id => document.getElementById(id);
const INFO=uuid('ffa0'), SCAN=uuid('ffa1'), CONFIG=uuid('ffa2'), DATA=uuid('ff00');
const stages=['fan','wifi','review','connect'];
let saved, device, identity, channels=new Map(), busy=false, phase='idle', stage='fan';
let networks=[], generation=0, expiryTimer;
const connected=()=>!!device?.gatt?.connected && !!identity;
const selectedNetwork=()=>networks[Number($('network').value)];
function log(message) {
  $('diagnostics').hidden=false;
  $('log').textContent+=`${new Date().toLocaleTimeString()}  ${message}\n`;
  $('log').scrollTop=$('log').scrollHeight;
}
function status(message='', style='') {
  $('status').textContent=message;
  $('status').className=style;
  $('status').hidden=!message;
}
function showStage(next, focus=true) {
  stage=next;
  for(const section of document.querySelectorAll('.card > section')) section.hidden=section.id!==`panel-${next}`;
  for(const item of document.querySelectorAll('[data-stage]')) {
    const current=item.dataset.stage===next;
    if(current) item.setAttribute('aria-current','step'); else item.removeAttribute('aria-current');
    item.classList.toggle('done',stages.indexOf(item.dataset.stage)<stages.indexOf(next));
  }
  $(`panel-${next}`).querySelector('[data-status-slot]').append($('status'));
  status();
  if(focus) $(`title-${next}`).focus({preventScroll:true});
  controls();
}
function progress(name) {
  if(name) document.querySelector(`[data-step="${name}"]`).classList.add('done');
  let active=false;
  for(const item of document.querySelectorAll('[data-step]')) {
    const current=!active && !item.classList.contains('done');
    item.classList.toggle('active',current);
    if(current) active=true;
    item.setAttribute('aria-label',`${item.textContent.trim()}: ${item.classList.contains('done')?'complete':current?'in progress':'waiting'}`);
  }
}
function controls() {
  const ready=!!saved && connected() && !busy;
  $('connect').hidden=connected();
  $('connect').disabled=!saved || busy || !navigator.bluetooth;
  $('continue-wifi').hidden=!connected();
  $('continue-wifi').disabled=!ready;
  $('disconnect').hidden=!connected();
  $('disconnect').disabled=busy;
  $('scan').disabled=!ready;
  $('network').disabled=!ready || !networks.length;
  $('password').disabled=!ready;
  $('show-password').disabled=!ready;
  $('review').disabled=!ready || !selectedNetwork();
  $('provision').disabled=!ready || !selectedNetwork();
  $('back-fan').disabled=busy;
  $('back-wifi').disabled=busy;
  $('retry').disabled=busy;
}
function clearPassword() {
  $('password').value='';
  $('password').type='password';
  $('show-password').checked=false;
}
function releaseConnection() {
  generation++;
  const previous=device;
  device=null; identity=null; networks=[];
  for(const channel of channels.values()) {
    channel.close(new Error('Bluetooth connection ended.'));
    channel.remove();
  }
  channels=new Map();
  previous?.gatt?.disconnect();
  clearPassword();
  $('network').replaceChildren();
  $('device').hidden=true;
}
function unavailable(error) {
  saved=null;busy=false;phase='unavailable';
  clearTimeout(expiryTimer);
  releaseConnection();
  showStage('unavailable');
  status(error.message || String(error),'error');
  $('expiry').textContent='';
}
function ensureLink() {
  if(!saved || saved.expiresAt<=Date.now()) {
    unavailable(new Error('This setup link expired. Create a new Bluetooth setup link in Home Assistant.'));
    return false;
  }
  return true;
}
function fail(error) {
  busy=false;
  if(!ensureLink()) return;
  if(stage==='connect') {
    phase='error';
    $('title-connect').textContent='The fan could not connect';
    $('connect-help').textContent='Review your network and password, then try again. If the fan left setup mode, put it back into setup mode and reconnect.';
    $('retry-actions').hidden=false;
    for(const item of document.querySelectorAll('[data-step]')) {
      item.classList.remove('active');
      if(!item.classList.contains('done')) item.setAttribute('aria-label',`${item.textContent.trim()}: not completed`);
    }
  }
  status(error.message || String(error),'error');
  log(`${error.name || 'Error'}: ${error.message || error}`);
  controls();
}
function networkFields() {
  const network=selectedNetwork();
  $('password-fields').hidden=!network || !network.security;
  $('open-network').hidden=!network || !!network.security;
  controls();
}
function options(items) {
  const previous=selectedNetwork()?.bssid;
  networks=items.filter(n=>n.ssid && n.channel<=14).sort((a,b)=>b.rssi-a.rssi);
  $('network').replaceChildren();
  networks.forEach((network,index)=>{
    const option=document.createElement('option');option.value=String(index);
    option.textContent=`${network.ssid}${network.channel ? ` · ch ${network.channel}` : ''}`;
    $('network').append(option);
  });
  if(networks.length) $('network').value=String(Math.max(0,networks.findIndex(n=>n.bssid===previous)));
  else {
    const option=document.createElement('option');option.value='';option.textContent='No 2.4 GHz networks found';
    $('network').append(option);
  }
  if(selectedNetwork()?.bssid!==previous) clearPassword();
  networkFields();
}
class Channel {
  constructor(characteristic, name) {
    this.characteristic=characteristic;this.name=name;this.queue=[];this.waiters=[];this.assembler=new Reassembler();this.count=0;this.error=null;
    this.listener=event=>this.feed(event.target.value);
    characteristic.addEventListener('characteristicvaluechanged',this.listener);
  }
  feed(value) {
    this.count++;
    const data=bytes(value);
    if((this.name===INFO || this.name===SCAN) && data.length===1 && data[0]===255) return;
    try {
      const complete=this.assembler.feed(data);
      if(complete) {
        const waiter=this.waiters.shift();
        if(waiter) waiter.resolve(complete); else this.queue.push(complete);
      }
    } catch(error) { this.close(error); }
  }
  receive(timeout) {
    if(this.queue.length) return Promise.resolve(this.queue.shift());
    if(this.error) return Promise.reject(this.error);
    return new Promise((resolve,reject)=>{
      const waiter={resolve:data=>{clearTimeout(timer);resolve(data);},reject:error=>{clearTimeout(timer);reject(error);}};
      const timer=setTimeout(()=>{this.waiters=this.waiters.filter(w=>w!==waiter);reject(new Error(`Timed out waiting for ${this.name===INFO?'fan identity':this.name===SCAN?'Wi-Fi scan':'setup progress'}`));},timeout);
      this.waiters.push(waiter);
    });
  }
  async read() {
    const before=this.count;
    const value=await this.characteristic.readValue();
    // Chrome emits characteristicvaluechanged for reads. Avoid feeding twice.
    if(this.count===before) this.feed(value);
  }
  close(error) { this.error=error; for(const waiter of this.waiters.splice(0)) waiter.reject(error); }
  remove() { this.characteristic.removeEventListener('characteristicvaluechanged',this.listener); }
}

async function scan() {
  status('Looking for nearby Wi-Fi networks…');
  await channels.get(SCAN).read();
  const result=parseScan(await channels.get(SCAN).receive(25000));
  options(result);
  log(`Wi-Fi scan returned ${result.filter(n=>n.ssid).length} named access points.`);
  status(networks.length?'':'No 2.4 GHz networks were found. Check that your router is nearby and scan again.');
}
async function scanNetworks() {
  if(!ensureLink()) return;
  const attempt=generation;
  busy=true;controls();
  try {await scan();} catch(error) {if(attempt===generation) fail(error);}
  finally {if(attempt===generation) {busy=false;controls();}}
}
$('connect').addEventListener('click',async()=>{
  if(!ensureLink()) return;
  releaseConnection();
  const attempt=generation;
  busy=true;phase='connecting';controls();
  status('Choose your fan in the Bluetooth picker.');
  try {
    // Keep requestDevice directly inside this click's transient activation.
    const selected=await requestFan(navigator.bluetooth);
    if(attempt!==generation) return;
    device=selected;
    device.addEventListener('gattserverdisconnected',()=>{
      if(device!==selected) return;
      releaseConnection();busy=false;
      if(phase!=='complete') {
        phase='idle';showStage('fan');
        status('Bluetooth disconnected. Put the fan back into setup mode, then choose it again.','error');
      }
      log('Bluetooth link closed.');controls();
    },{once:true});
    log(`Selected ${device.name || 'Coway fan'} in Chrome.`);
    status('Connecting to your fan…');
    const gatt=await selected.gatt.connect();
    if(attempt!==generation) {selected.gatt.disconnect();return;}
    try {
      const main=await gatt.getPrimaryService(uuid('ffc0'));
      const extra=await gatt.getPrimaryService(uuid('ffc1'));
      for(const [service,name] of [[main,INFO],[main,SCAN],[main,CONFIG],[extra,DATA]]) {
        const characteristic=await service.getCharacteristic(name);
        if(attempt!==generation) return;
        const channel=new Channel(characteristic,name);channels.set(name,channel);
        await characteristic.startNotifications();
      }
    } catch(error) {
      if(error.name==='NotFoundError' || error.name==='NotSupportedError')
        throw new Error('This device does not expose the expected Coway setup services. Put your fan in Wi-Fi setup mode and choose it again.');
      throw error;
    }
    if(attempt!==generation) return;
    await channels.get(INFO).read();
    const info=decodeProto(await channels.get(INFO).receive(12000));
    if(attempt!==generation) return;
    identity=readIdentity(selected.name,info);phase='connected';
    if(saved.useBluetoothName) $('target').textContent=identity.name;
    $('device').textContent=`${identity.name} · Bluetooth connected`;$('device').hidden=false;
    log('Device identity read; notification channels ready.');
    showStage('wifi');networkFields();
    await scan();
  } catch(error) {
    if(attempt!==generation) return;
    if(!identity) {
      releaseConnection();busy=false;showStage('fan');
    }
    if(error.name==='NotFoundError' && /cancel/i.test(error.message)) {
      phase='idle';status('No fan selected. Choose your fan when it is in setup mode.');
      log('Device chooser canceled; no settings sent.');
    } else fail(error);
  } finally {
    if(attempt===generation) busy=false;
    controls();
  }
});
$('continue-wifi').addEventListener('click',()=>{
  if(!ensureLink()) return;
  showStage('wifi');
  if(!networks.length) scanNetworks();
});
$('scan').addEventListener('click',scanNetworks);
$('disconnect').addEventListener('click',()=>{
  releaseConnection();phase='idle';
  if(saved?.useBluetoothName) $('target').textContent='Your Coway fan';
  showStage('fan');
});
$('back-fan').addEventListener('click',()=>showStage('fan'));
$('back-wifi').addEventListener('click',()=>showStage('wifi'));
$('retry').addEventListener('click',()=>{
  if(!ensureLink()) return;
  showStage(connected()?'wifi':'fan');
});
$('network').addEventListener('change',()=>{clearPassword();networkFields();status();});
$('show-password').addEventListener('change',()=>{$('password').type=$('show-password').checked?'text':'password';});
$('wifi-form').addEventListener('submit',event=>{
  event.preventDefault();
  if(busy || !ensureLink()) return;
  try {
    wifiConfig(saved,identity,selectedNetwork(),$('password').value);
    $('review-fan').textContent=saved.useBluetoothName?identity.name:saved.name;
    $('review-network').textContent=selectedNetwork().ssid;
    showStage('review');
  } catch(error) {
    fail(error);
    if(selectedNetwork()?.security) $('password').focus();
  }
});

async function send(message,label) {
  // Web Bluetooth does not expose negotiated ATT MTU. Use 20-byte values.
  const packets=fragments(message,20);
  for(const packet of packets) await channels.get(CONFIG).characteristic.writeValueWithResponse(packet);
  log(`${label}: ${packets.length} writes, maximum 20 bytes each.`);
}
async function waitStatus(command,final,timeout) {
  const deadline=performance.now()+timeout;
  while(performance.now()<deadline) {
    const fields=decodeProto(await channels.get(CONFIG).receive(Math.max(1,deadline-performance.now())));
    const code=fields[3] ?? 0;
    const description=STATUS[code] || `Device status ${code}`;
    log(`${code}: ${description}`);
    if(fields[2]!==1 || FAILURE_CODES.has(code)) throw new Error(description);
    if(code===10) {progress('wifi');status('Getting credentials from your local server…');}
    if(code===50) {progress('certificates');status('Connecting to your local server…');}
    if(fields[1]===command && code===final) return;
  }
  throw new Error('Timed out waiting for device setup');
}
$('provision').addEventListener('click',async()=>{
  if(!ensureLink()) return;
  let config;
  try {
    if(!connected()) throw new Error('Reconnect the fan before starting setup.');
    config=wifiConfig(saved,identity,selectedNetwork(),$('password').value);
  } catch(error) {showStage('wifi');fail(error);return;}
  const attempt=generation;
  busy=true;phase='provisioning';
  $('success').hidden=true;$('progress').hidden=false;$('retry-actions').hidden=true;
  $('title-connect').textContent='Connecting your fan';
  $('connect-help').hidden=false;
  $('connect-help').textContent='Keep this tab open and stay near the fan. This can take up to two minutes.';
  for(const item of document.querySelectorAll('[data-step]')) item.classList.remove('done');
  showStage('connect');progress();status('Sending settings to your fan…');
  try {
    channels.get(CONFIG).queue=[];
    const random=randomLetters(20);
    const message=await p002(config,random);
    if(attempt!==generation) return;
    log('Starting browser-only Bluetooth provisioning.');
    await send(p001(random),'Establishing setup key');await waitStatus(1,72,15000);
    await send(message,'Sending Wi-Fi settings');
    progress('settings');status('Waiting for the fan to join Wi-Fi…');
    await waitStatus(2,61,120000);
    if(attempt!==generation) return;
    progress('mqtt');phase='complete';busy=false;
    log('Fan reported broker connection; Home Assistant will verify its authenticated session.');
    saved=null;clearTimeout(expiryTimer);releaseConnection();
    $('title-connect').textContent='Finish in Home Assistant';
    $('connect-help').hidden=true;$('progress').hidden=true;$('success').hidden=false;
    $('expiry').textContent='';status();controls();$('title-connect').focus({preventScroll:true});
  } catch(error) {if(attempt===generation) fail(error);}
  finally {if(attempt===generation) {busy=false;controls();}}
});
function initialize() {
  if(!window.isSecureContext || !navigator.bluetooth || !crypto.subtle) {
    $('environment').textContent='Chrome required';
    throw new Error('Open this setup link in Chrome on a Mac or Android phone. Use HTTPS or localhost. Safari and iPhone browsers are not supported.');
  }
  $('environment').textContent='Bluetooth ready';
  saved=decodeSetup(setupFragment);setupFragment='';
  $('server').textContent=new URL(saved.certSvrUrl).host;
  $('target').textContent=saved.useBluetoothName?'Your Coway fan':saved.name;
  $('serial').textContent='Serial '+saved.serial;
  $('expiry').textContent='Setup link expires at '+new Date(saved.expiresAt).toLocaleTimeString()+'.';
  showStage('fan',false);
  expiryTimer=setTimeout(()=>{
    // Let an in-flight enrollment finish; the server also enforces expiry.
    if(phase!=='provisioning' && phase!=='complete') ensureLink();
  },Math.min(2147483647,Math.max(0,saved.expiresAt-Date.now()+1)));
}
try {initialize();} catch(error) {setupFragment='';unavailable(error);}
window.addEventListener('pagehide',()=>{saved=null;clearTimeout(expiryTimer);releaseConnection();});
// Pasting a fresh setup link into this tab is a same-document navigation.
window.addEventListener('hashchange',()=>{if(location.hash.startsWith('#setup=')) location.reload();});
