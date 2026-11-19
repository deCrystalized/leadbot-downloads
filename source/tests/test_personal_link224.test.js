'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {create}=require('../ext/personal-link');
const Personal=require('../ext/personal');
const KEY='lczPersonalLink',NAME='lcz-personal-link',ID='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',NEW='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

function fixture(){
 const data={},alarms=new Map(),messages=[],handlers={},tabs=new Map([[7,{id:7,url:'https://lead.test/chats?lcz-assistant=1'}]]);
 const api={runtime:{id:'extension'},storage:{session:{get:async k=>({[k]:structuredClone(data[k])}),set:async x=>Object.assign(data,structuredClone(x))}},
  alarms:{get:async n=>alarms.get(n),create:async(n,v)=>alarms.set(n,v),clear:async n=>alarms.delete(n),onAlarm:{addListener:fn=>{handlers.alarm=fn}}},
  tabs:{get:async id=>{if(!tabs.has(id))throw Error('closed');return tabs.get(id)},sendMessage:async(id,msg)=>{messages.push({id,msg});return{ok:true,active:true,connection_id:msg.connection_id}},onRemoved:{addListener:fn=>{handlers.remove=fn}}}};
 const dedicated=async(id,url)=>tabs.has(id)&&new URL(url).searchParams.get('lcz-assistant')==='1';
 return{api,data,alarms,messages,tabs,handlers,dedicated,link:create(api,['https://lead.test'],dedicated),sender:{id:'extension',frameId:0,url:tabs.get(7).url,tab:{id:7}}};
}

test('alarm registration schedules only a tab-bound pulse, not model/action work',async()=>{
 const f=fixture();assert.deepEqual(await f.link.action('start',f.sender,ID),{ok:true,connection_id:ID});
 assert.deepEqual(f.alarms.get(NAME),{periodInMinutes:0.5});await f.link.tick();
 assert.deepEqual(f.messages,[{id:7,msg:{kind:'lcz-personal-pulse',connection_id:ID}}]);
 assert.deepEqual(f.data[KEY],{schema:1,rows:{7:{origin:'https://lead.test',connection_id:ID}}});
});
test('foreign origin, frame, extension, non-tab and ordinary work tab cannot register',async()=>{
 const f=fixture();for(const patch of [{id:'other'},{frameId:1},{url:'https://evil.test/chats?lcz-assistant=1'},{tab:null},{url:'https://lead.test/chats/work'}])
  await assert.rejects(f.link.action('start',{...f.sender,...patch},ID));
 assert.deepEqual(f.messages,[]);assert.equal(f.data[KEY],undefined);
});
test('a changed actual tab URL rejects the old otherwise-valid sender',async()=>{
 const f=fixture();f.tabs.get(7).url='https://evil.test/';await assert.rejects(f.link.action('start',f.sender,ID));assert.equal(f.alarms.size,0);
});
test('invalid connection IDs cannot store or schedule anything',async()=>{
 const f=fixture();for(const id of ['',null,7,'x','a'.repeat(81),'../'+ID])await assert.rejects(f.link.action('start',f.sender,id));assert.equal(f.alarms.size,0);
});
test('old stop cannot remove a replacement registration',async()=>{
 const f=fixture();await f.link.action('start',f.sender,ID);await f.link.action('start',f.sender,NEW);
 await f.link.action('stop',f.sender,ID);assert.equal(f.data[KEY].rows[7].connection_id,NEW);assert.equal(f.alarms.size,1);
 await f.link.action('stop',f.sender,NEW);assert.deepEqual(f.data[KEY].rows,{});assert.equal(f.alarms.size,0);
});
test('worker restart restores only scheduling; browser restart with empty session storage clears alarm',async()=>{
 const f=fixture();await f.link.action('start',f.sender,ID);f.alarms.clear();
 const restarted=create(f.api,['https://lead.test'],f.dedicated);await restarted.restore();assert.equal(f.alarms.size,1);assert.deepEqual(f.messages,[]);
 delete f.data[KEY];await restarted.restore();assert.equal(f.alarms.size,0);assert.deepEqual(f.messages,[]);
});
test('closed or navigated helper is removed before any content pulse',async()=>{
 for(const close of [true,false]){const f=fixture();await f.link.action('start',f.sender,ID);
  if(close)f.tabs.delete(7);else f.tabs.get(7).url='https://lead.test/chats/work';
  await f.link.tick();assert.deepEqual(f.data[KEY].rows,{});assert.equal(f.alarms.size,0);assert.deepEqual(f.messages,[])}
});
test('tab removal stops its alarm without touching other registrations',async()=>{
 const f=fixture();await f.link.action('start',f.sender,ID);f.handlers.remove(7);await new Promise(r=>setImmediate(r));
 assert.deepEqual(f.data[KEY].rows,{});assert.equal(f.alarms.size,0);
});
test('missing, mismatched, stopped and rejected pulse replies remove authority-free registration',async()=>{
 for(const reply of [undefined,{ok:true,active:false,connection_id:ID},{ok:true,active:true,connection_id:NEW},{ok:false}]){
  const f=fixture();await f.link.action('start',f.sender,ID);f.api.tabs.sendMessage=async()=>reply;await f.link.tick();assert.deepEqual(f.data[KEY].rows,{});assert.equal(f.alarms.size,0)}
});
test('concurrent alarm deliveries cannot start duplicate heartbeats for one tab',async()=>{
 const f=fixture();await f.link.action('start',f.sender,ID);let release;
 f.api.tabs.sendMessage=async()=>{f.messages.push('pulse');return new Promise(r=>{release=r})};
 const one=f.link.tick();await new Promise(r=>setImmediate(r));await f.link.tick();assert.equal(f.messages.length,1);
 release({ok:true,active:true,connection_id:ID});await one;
});
test('late old pulse result cannot clear a newer connection',async()=>{
 const f=fixture();await f.link.action('start',f.sender,ID);let release;
 f.api.tabs.sendMessage=async()=>new Promise(r=>{release=r});const old=f.link.tick();await new Promise(r=>setImmediate(r));
 await f.link.action('start',f.sender,NEW);release({ok:false});await old;assert.equal(f.data[KEY].rows[7].connection_id,NEW);
});
test('registration racing worker restore cannot lose the new alarm',async()=>{
 const f=fixture();let release;f.api.alarms.clear=async n=>{await new Promise(r=>{release=r});f.alarms.delete(n)};
 const restore=f.link.restore();await new Promise(r=>setImmediate(r));const start=f.link.action('start',f.sender,ID);
 await new Promise(r=>setImmediate(r));release();await Promise.all([restore,start]);assert.equal(f.alarms.size,1);assert.equal(f.data[KEY].rows[7].connection_id,ID);
});
test('malformed persisted scheduling data cannot start pulses or leave its alarm alive',async()=>{
 for(const value of [{schema:2,rows:{}},{schema:1,rows:{7:{origin:'https://evil.test',connection_id:ID}}},{schema:1,rows:[]},{schema:1,rows:{999999999999999999999:{origin:'https://lead.test',connection_id:ID}}}]){
  const f=fixture();f.data[KEY]=value;f.alarms.set(NAME,{});await f.link.restore();assert.equal(f.alarms.size,0);assert.deepEqual(f.messages,[])}
});
test('registration capacity is bounded and unknown operations cannot register',async()=>{
 const f=fixture();await assert.rejects(f.link.action('enable_auto',f.sender,ID));
 for(let id=7;id<15;id++){f.tabs.set(id,{id,url:f.sender.url});await f.link.action('start',{...f.sender,tab:{id}},ID)}
 f.tabs.set(15,{id:15,url:f.sender.url});await assert.rejects(f.link.action('start',{...f.sender,tab:{id:15}},ID));assert.equal(Object.keys(f.data[KEY].rows).length,8);
});
test('an unanswered content pulse has a bounded deadline and is not retried',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});const f=fixture();await f.link.action('start',f.sender,ID);
 let calls=0;f.api.tabs.sendMessage=async()=>{calls++;return new Promise(()=>{})};const run=f.link.tick();await new Promise(r=>setImmediate(r));
 t.mock.timers.tick(12001);await run;assert.equal(calls,1);assert.deepEqual(f.data[KEY].rows,{});assert.equal(f.alarms.size,0);
});

test('a delayed tab lookup cannot dispatch a pulse after its whole-operation deadline',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});const f=fixture();await f.link.action('start',f.sender,ID);let release;
 f.api.tabs.get=async()=>new Promise(r=>{release=r});const run=f.link.tick();await new Promise(r=>setImmediate(r));
 t.mock.timers.tick(12001);await run;release(f.tabs.get(7));await new Promise(r=>setImmediate(r));assert.deepEqual(f.messages,[]);assert.deepEqual(f.data[KEY].rows,{});
});

test('actual client + alarm backstop renews the same review lease while page timers are held',async t=>{
 let now=1000000,serverUntil=0;const calls=[];t.mock.method(Date,'now',()=>now);
 const f=fixture();const client=Personal.create({visible:()=>true,getIdentity:async()=>({id:'operator'}),
  startPulse:id=>f.link.action('start',f.sender,id),stopPulse:id=>f.link.action('stop',f.sender,id),
  send:async({args:a})=>{calls.push(a.action);if(a.action==='personal_start')serverUntil=now+45000;
   if(a.action==='personal_heartbeat'){if(now>=serverUntil)return{ok:false,error:'expired'};serverUntil=now+45000}
   return{ok:true,active:a.action!=='personal_stop',lease_seconds:45,auto_enabled:false,mode_epoch:7}}});
 f.api.tabs.sendMessage=async(_id,msg)=>client.pulse(msg.connection_id);
 try{
  await client.start();for(let i=0;i<20;i++){now+=30000;if(i===8){f.link=create(f.api,['https://lead.test'],f.dedicated);await f.link.restore()}await f.link.tick();assert.equal(client.state.active,true);assert.equal(client.state.auto,false)}
  assert.equal(calls.filter(x=>x==='personal_start').length,1);assert.equal(calls.filter(x=>x==='personal_heartbeat').length,20);
  assert.equal(client.state.connection.trigger,'alarm');assert.ok(calls.every(x=>['personal_start','personal_heartbeat'].includes(x)));
  now+=46000;await f.link.tick();assert.equal(client.state.active,false);assert.equal(client.state.auto,false);assert.equal(calls.filter(x=>x==='personal_heartbeat').length,20);
 }finally{await client.stop()}
});
