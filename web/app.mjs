import {bytes,text,utf8,uuid,hex,canonicalMac,p001,p002,randomLetters,fragments,Reassembler,decodeProto,parseScan,STATUS,FAILURE_CODES} from './protocol.mjs';

import {decodeSetup, wifiConfig} from './bootstrap.mjs';

// Strip the fragment before any Bluetooth interaction; do not persist it.
let setupFragment = location.hash;
history.replaceState(null, '', location.pathname + location.search);

const $ = id => document.getElementById(id);
const INFO=uuid('ffa0'), SCAN=uuid('ffa1'), CONFIG=uuid('ffa2'), DATA=uuid('ff00');
let saved, device, identity, channels=new Map(), busy=false, phase='idle', networks=[], observedProgress=[];
function log(message) {
  const line=`${new Date().toLocaleTimeString()}  ${message}`;
  $('log').textContent+=line+'\n'; $('log').scrollTop=$('log').scrollHeight;
}
function status(message, style='') { $('status').textContent=message; $('status').className=style; }
function step(name) { document.querySelector(`[data-step="${name}"]`).classList.add('done'); }
function controls() {
  const connected=!!device?.gatt?.connected && !!identity;
  $('connect').disabled=!saved || busy || connected || !navigator.bluetooth;
  $('disconnect').disabled=!device?.gatt?.connected || busy;
  $('scan').disabled=!connected || busy;
  $('network').disabled=busy || !saved;
  $('password').disabled=busy || !saved;
  $('provision').disabled=!connected || busy || !networks.length;
}
function fail(error) {
  phase='error'; busy=false;
  status(error.message || String(error),'error');
  log(`${error.name || 'Error'}: ${error.message || error}`,'error'); controls();
}
function options(items) {
  const current=networks[Number($('network').value)]?.bssid || saved.bssid;
  networks=items.filter(n=>n.ssid && n.channel<=14).sort((a,b)=>b.rssi-a.rssi);
  $('network').replaceChildren();
  networks.forEach((network,index)=>{
    const option=document.createElement('option'); option.value=String(index);
    option.textContent=`${network.ssid}${network.channel ? ` · ch ${network.channel}` : ''}`;
    $('network').append(option);
  });
  let index=networks.findIndex(n=>n.bssid===current);
  if(index<0) index=networks.findIndex(n=>n.ssid===saved.ssid && n.channel<=14);
  $('network').value=String(Math.max(index,0)); controls();
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
  status('The fan is scanning for nearby Wi-Fi networks…');
  await channels.get(SCAN).read();
  const result=parseScan(await channels.get(SCAN).receive(25000));
  options(result);log(`Wi-Fi scan returned ${result.filter(n=>n.ssid).length} named access points.`,'scan');
  status('Fan connected. Check the Wi-Fi network, then start setup.');
}

$('connect').addEventListener('click',async()=>{
  busy=true;phase='connecting';identity=null;controls();
  for(const element of document.querySelectorAll('[data-step]')) element.classList.remove('done');
  try {
    // Keep requestDevice directly inside this click's transient activation.
    device=await navigator.bluetooth.requestDevice({filters:[{namePrefix:'AP-1022K'}],optionalServices:[uuid('ffc0'),uuid('ffc1'),uuid('ffc3')]});
    for(const channel of channels.values()) channel.remove(); channels=new Map();
    device.addEventListener('gattserverdisconnected',()=>{
      for(const channel of channels.values()) channel.close(new Error('Bluetooth disconnected. Put the fan back into setup mode and reconnect.'));
      if(phase!=='complete') $('device').textContent='Bluetooth disconnected';
      $('password').value='';
      log('Bluetooth link closed.','disconnected');controls();
    },{once:true});
    log(`Selected ${device.name || 'Coway fan'} in Chrome.`,'selected');status('Connecting over Bluetooth…');
    const gatt=await device.gatt.connect();
    const main=await gatt.getPrimaryService(uuid('ffc0'));
    const extra=await gatt.getPrimaryService(uuid('ffc1'));
    for(const [service,name] of [[main,INFO],[main,SCAN],[main,CONFIG],[extra,DATA]]) {
      const characteristic=await service.getCharacteristic(name);
      const channel=new Channel(characteristic,name);channels.set(name,channel);
      await characteristic.startNotifications();
    }
    await channels.get(INFO).read();
    const info=decodeProto(await channels.get(INFO).receive(12000));
    const mac=canonicalMac(text.decode(info[2]));
    if(!/^[A-F0-9]{12}$/.test(mac) || !text.decode(info[1]).startsWith('AP-1022K')) throw new Error('Unsupported device. This page supports AP-1022K only.');
    identity={mac,name:text.decode(info[1])};phase='connected';
    $('device').textContent=`${identity.name} · Bluetooth connected`;step('bluetooth');
    log('Fan model and address read; notification channels ready.','identity');
    await scan();
  } catch(error) {
    if(error.name==='NotFoundError' && /cancel/i.test(error.message)) {
      phase='idle';status('Device selection canceled. Connect again when the fan is in setup mode.');
      log('Device chooser canceled; no settings sent.','canceled');
    } else fail(error);
    if(device?.gatt?.connected && !identity) device.gatt.disconnect();
  }
  finally {busy=false;controls();}
});

$('scan').addEventListener('click',async()=>{busy=true;controls();try{await scan();}catch(error){fail(error);}finally{busy=false;controls();}});
$('disconnect').addEventListener('click',()=>{device?.gatt?.disconnect();identity=null;phase='idle';status('Disconnected. Put the fan in setup mode to connect again.');controls();});
$('show-password').addEventListener('change',()=>{$('password').type=$('show-password').checked?'text':'password';});

async function send(message, label) {
  // Web Bluetooth does not expose negotiated ATT MTU. Start with 20-byte
  // characteristic values (16 payload bytes + 4 Coway framing bytes).
  const packets=fragments(message,20);
  for(let index=0;index<packets.length;index++) {
    await channels.get(CONFIG).characteristic.writeValueWithResponse(packets[index]);
    status(`${label} (${index+1}/${packets.length})…`);
  }
  log(`${label}: ${packets.length} writes, maximum 20 bytes each.`,'sent',{packetCount:packets.length});
}
async function waitStatus(command, final, timeout) {
  const deadline=performance.now()+timeout;
  while(performance.now()<deadline) {
    const fields=decodeProto(await channels.get(CONFIG).receive(Math.max(1,deadline-performance.now())));
    const code=fields[3] ?? 0;observedProgress.push(code);
    const description=STATUS[code] || `Device status ${code}`;
    log(`${code}: ${description}`,'progress',{code});status(description+'…');
    if(fields[2]!==1 || FAILURE_CODES.has(code)) throw new Error(description);
    if(code===71) step('settings');
    if(code===10) step('wifi');
    if(code===50) step('certificates');
    if(fields[1]===command && code===final) return;
  }
  throw new Error('Timed out waiting for device setup');
}

$('provision').addEventListener('click',async()=>{
  busy=true;phase='provisioning';observedProgress=[];controls();
  try {
    const network=networks[Number($('network').value)];
    if(!network || !device?.gatt?.connected) throw new Error('Connect the fan and select a network first');
    if(network.security && !$('password').value) throw new Error('Enter the Wi-Fi password');
    const config=wifiConfig(saved,identity,network,$('password').value);
    channels.get(CONFIG).queue=[];
    const random=randomLetters(20);
    const message=await p002(config,random);
    log('Starting browser-only Bluetooth provisioning.','started');
    await send(p001(random),'Establishing setup key');await waitStatus(1,72,15000);
    await send(message,'Sending Wi-Fi settings');await waitStatus(2,61,120000);
    step('mqtt');phase='complete';status('Fan reports connected. Return to Home Assistant and click Submit to confirm setup.','success');
    log('Fan reported broker connection; Home Assistant will verify its authenticated session.');
    $('password').value='';saved=null;
    device.gatt.disconnect();identity=null;
  } catch(error) {fail(error);}
  finally {busy=false;controls();}
});

async function initialize() {
  if(!window.isSecureContext || !navigator.bluetooth || !crypto.subtle) {
    $('environment').textContent='Compatible Chrome required';
    throw new Error('Use Chrome on a Mac or Android phone over HTTPS (or localhost). Safari and iPhone browsers are not supported.');
  }
  $('environment').textContent='Web Bluetooth available';
  saved=decodeSetup(setupFragment);
  setupFragment='';
  $('server').textContent=new URL(saved.certSvrUrl).host;
  $('target').textContent=saved.name+' · '+saved.model+' · '+saved.serial;
  $('expiry').textContent='Setup link expires at '+new Date(saved.expiresAt).toLocaleTimeString()+'.';
  status('Ready. Put the fan in setup mode, then connect.');controls();
}
initialize().catch(fail);
window.addEventListener('pagehide',()=>{saved=null;$('password').value='';device?.gatt?.disconnect();});
