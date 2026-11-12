// Browser test adapter only. All identities, Wi-Fi networks and tokens are synthetic.
import {encodeProto,fragments,Reassembler,concat,utf8,text,uuid} from '/protocol.mjs';

const fixture=document.createElement('fieldset');
fixture.innerHTML='<legend>Preview · simulated fan</legend><label for="scenario">Test scenario</label><select id="scenario"><option value="success">Successful setup</option><option value="cancel">Cancel Bluetooth picker</option><option value="unsupported">Unsupported device</option><option value="empty">No Wi-Fi networks</option><option value="wifi-failure">Wi-Fi connection fails</option><option value="disconnect">Disconnect during setup</option></select><button id="drop-link" class="secondary" type="button">Simulate Bluetooth disconnect</button><p><a href="/preview?expired=1">Open expired link</a> · <a href="/">Open without setup link</a></p>';
document.querySelector('main').append(fixture);
const scenario=()=>document.getElementById('scenario').value;
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let fan;
function scanData() {
  const rows=scenario()==='empty'?[]:[
    ['Home Wi-Fi', 'aabbccddeeff', -32, 4, 6],
    ['Guest Wi-Fi', 'aabbccddeefe', -48, 0, 11],
    ['5 GHz only', 'aabbccddeefd', -28, 4, 36],
  ];
  return concat('*ICT*SCANRESULT:', ...rows.map(([ssid,mac,rssi,security,channel])=>{
    const item=new Uint8Array(48), view=new DataView(item.buffer), name=utf8.encode(ssid);
    view.setUint16(2,name.length,true);item.set(name,4);
    item.set(mac.match(/../g).map(b=>parseInt(b,16)),36);
    view.setInt32(42,rssi,true);item[46]=security;item[47]=channel;
    return item;
  }));
}
class Characteristic extends EventTarget {
  constructor(name,owner) {super();this.name=name;this.owner=owner;this.assembler=new Reassembler();}
  async startNotifications() {return this;}
  emit(data) {
    if(!this.owner.gatt.connected) return;
    for(const packet of fragments(data)) {
      this.value=new DataView(packet.buffer);
      this.dispatchEvent(new Event('characteristicvaluechanged'));
    }
  }
  async readValue() {
    await sleep(180);
    this.emit(this.name===uuid('ffa0')?encodeProto({1:'COWAY334455',2:'001122334455'}):scanData());
    return new DataView(new Uint8Array([255]).buffer);
  }
  async writeValueWithResponse(packet) {
    const message=this.assembler.feed(packet);
    if(!message) return;
    if(text.decode(message.slice(0,4))==='P001') {
      setTimeout(()=>this.emit(encodeProto({1:1,2:1,3:72})),80);
      return;
    }
    if(scenario()==='disconnect') {setTimeout(()=>this.owner.gatt.disconnect(),300);return;}
    if(scenario()==='wifi-failure') {setTimeout(()=>this.emit(encodeProto({1:2,2:0,3:1})),350);return;}
    [10,20,40,50,61].forEach((code,index)=>setTimeout(()=>this.emit(encodeProto({1:2,2:1,3:code})),500*(index+1)));
  }
}
class Fan extends EventTarget {
  constructor() {
    super();this.name='AP-1022K_DEMO';this.characteristics=new Map();
    this.gatt={
      connected:false,
      connect:async()=>{await sleep(100);this.gatt.connected=true;return this.gatt;},
      disconnect:()=>{if(this.gatt.connected){this.gatt.connected=false;this.dispatchEvent(new Event('gattserverdisconnected'));}},
      getPrimaryService:async()=>{
        if(scenario()==='unsupported') throw new DOMException('Service missing','NotFoundError');
        return {getCharacteristic:async name=>{
          if(!this.characteristics.has(name)) this.characteristics.set(name,new Characteristic(name,this));
          return this.characteristics.get(name);
        }};
      },
    };
  }
}
Object.defineProperty(navigator,'bluetooth',{configurable:true,value:{requestDevice:async()=>{
  if(scenario()==='cancel') throw new DOMException('User cancelled the requestDevice() chooser.','NotFoundError');
  fan=new Fan();return fan;
}}});
document.getElementById('drop-link').addEventListener('click',()=>fan?.gatt.disconnect());
const bundle={v:1,model:'AP-1022K',
  returnUrl:location.origin+'/api/coway_local/provisioning/return?flow_id='+'b'.repeat(32)+'&state='+'c'.repeat(32),
  caUrl:'http://192.0.2.1:8080/ca.pem',certSvrUrl:'https://192.0.2.1:9443/n',certToken:'a'.repeat(32),
  expiresAt:Date.now()+(new URLSearchParams(location.search).has('expired')?-1000:900000)};
history.replaceState(null,'',location.pathname+location.search+'#setup='+btoa(JSON.stringify(bundle)).replaceAll('+','-').replaceAll('/','_').replaceAll('=',''));
