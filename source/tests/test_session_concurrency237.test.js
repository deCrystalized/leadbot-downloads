'use strict';
// Real Personal lifecycle; only identity/HTTP/time are synthetic. No auto.
const test=require('node:test'),assert=require('node:assert/strict');
const {create}=require('../ext/personal');
const principal='11111111-1111-4111-8111-111111111111',other='22222222-2222-4222-8222-222222222222';
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve}};
const settle=()=>new Promise(r=>setImmediate(r));
async function fixture(t,extra={}){
 let now=1000000;const calls=[],timers=[];
 t.mock.method(global,'setInterval',(fn,ms)=>{const handle={fn,ms};timers.push(handle);return handle});
 t.mock.method(global,'clearInterval',()=>{});
 t.mock.method(Date,'now',()=>now);
 const ui=create({visible:()=>true,getIdentity:async()=>({id:principal,role:'admin',full_name:'Test'}),
  getAuthors:async()=>({principal:{id:principal},authors:[{id:principal,full_name:'Test'},{id:other,full_name:'Other'}]}),
  getProof:async actor=>({identity_proof:'synthetic-'+actor,browser_session:'synthetic-tab',expires_at:now/1000+45}),
  loadQueue:async()=>({mineCount:0,rows:[]}),loadContext:async()=>{throw Error('No histories expected')},
  send:async({args:a})=>{calls.push(a);return{ok:true,active:a.action!=='personal_stop',lease_seconds:45,auto_enabled:false}},...extra});
 return{ui,calls,timers,advance:ms=>now+=ms};
}

test('overlapping heartbeat ticks share one I/O instead of racing success and failure',async t=>{
 const pending=[],f=await fixture(t,{send:async({args:a})=>{
  if(a.action==='personal_heartbeat'){const d=deferred();pending.push(d);return d.promise}
  return{ok:true,active:a.action!=='personal_stop',lease_seconds:45,auto_enabled:false};
 }});
 await f.ui.start();const first=f.ui.heartbeat(),second=f.ui.heartbeat();await settle();
 try{assert.equal(pending.length,1,'two timer ticks must not create two independent heartbeat requests')}
 finally{for(const d of pending)d.resolve({ok:true,active:true,lease_seconds:45});await Promise.all([first,second]);await f.ui.stop()}
});

test('a previous epoch heartbeat never blocks the new connection or stops it on late failure',async t=>{
 const pending=[],f=await fixture(t,{send:async({args:a})=>{
  if(a.action==='personal_heartbeat'){const d=deferred();pending.push(d);return d.promise}
  return{ok:true,active:a.action!=='personal_stop',lease_seconds:45,auto_enabled:false};
 }});
 await f.ui.start();const first=f.ui.heartbeat();await settle();await f.ui.stop();await f.ui.start();
 const second=f.ui.heartbeat();await settle();
 try{assert.equal(pending.length,2);pending[1].resolve({ok:true,active:true,lease_seconds:45});await second;
  pending[0].resolve({ok:false,error:'old epoch failed'});await first;assert.equal(f.ui.state.active,true);assert.equal(f.ui.state.error,'')}
 finally{for(const d of pending)d.resolve({ok:true,active:true,lease_seconds:45});await Promise.all([first,second]);await f.ui.stop()}
});

test('an old actor proof request cannot be reused by a newly selected actor',async t=>{
 const pending=[],f=await fixture(t,{getProof:actor=>{const d=deferred();pending.push({actor,...d});return d.promise}});
 await f.ui.prepare();const old=f.ui.identityArgs().catch(e=>e);await settle();await f.ui.selectAuthor(other);
 const current=f.ui.identityArgs().catch(e=>e);await settle();
 try{assert.equal(pending.length,2,'the current actor needs its own proof request');assert.equal(pending[1].actor,other)}
 finally{for(const d of pending)d.resolve({identity_proof:'synthetic-'+d.actor,browser_session:'synthetic-tab',expires_at:Date.now()/1000+45});await Promise.all([old,current]);await f.ui.stop()}
});

test('completion of an old proof request cannot clear a newer pending proof',async t=>{
 const pending=[],f=await fixture(t,{getProof:actor=>{const d=deferred();pending.push({actor,...d});return d.promise}});
 await f.ui.prepare();const old=f.ui.identityArgs().catch(e=>e);await settle();await f.ui.selectAuthor(other);
 const current=f.ui.identityArgs().catch(e=>e);await settle();let third;
 try{assert.equal(pending.length,2);pending[0].resolve({identity_proof:'synthetic-old',browser_session:'synthetic-tab',expires_at:Date.now()/1000+45});await old;
  third=f.ui.identityArgs().catch(e=>e);await settle();assert.equal(pending.length,2,'old finally must not cause another proof/challenge rotation')}
 finally{for(const d of pending)d.resolve({identity_proof:'synthetic-'+d.actor,browser_session:'synthetic-tab',expires_at:Date.now()/1000+45});await Promise.all([old,current,third]);await f.ui.stop()}
});

test('a same actor proof is renewed independently after a connection epoch changes',async t=>{
 const pending=[],f=await fixture(t,{getProof:actor=>{const d=deferred();pending.push({actor,...d});return d.promise}});
 await f.ui.prepare();const old=f.ui.identityArgs().catch(e=>e);await settle();await f.ui.stop();
 const current=f.ui.identityArgs().catch(e=>e);await settle();
 try{assert.equal(pending.length,2,'epoch changes also fence a pending proof for the same actor')}
 finally{for(const d of pending)d.resolve({identity_proof:'synthetic-'+d.actor,browser_session:'synthetic-tab',expires_at:Date.now()/1000+45});await Promise.all([old,current]);await f.ui.stop()}
});

test('a start response arriving after its reported lease cannot activate the browser session',async t=>{
 const response=deferred();const f=await fixture(t,{send:async({args:a})=>a.action==='personal_start'?response.promise:{ok:true,active:false,auto_enabled:false}});
 const start=f.ui.start();await settle();f.advance(46000);response.resolve({ok:true,active:true,lease_seconds:45,auto_enabled:false});await start;
 try{assert.equal(f.ui.state.active,false);assert.match(f.ui.state.error,/связ|сесси|исте|подтверж/i)}finally{await f.ui.stop()}
});

test('a delayed heartbeat cannot report a fresh lease from an old successful response',async t=>{
 const response=deferred();const f=await fixture(t,{send:async({args:a})=>a.action==='personal_heartbeat'?response.promise:{ok:true,active:a.action!=='personal_stop',lease_seconds:45,auto_enabled:false}});
 await f.ui.start();const heartbeat=f.ui.heartbeat();await settle();f.advance(46000);response.resolve({ok:true,active:true,lease_seconds:45,auto_enabled:false});await heartbeat;
 try{assert.equal(f.ui.state.active,false);assert.match(f.ui.state.error,/связ|сесси|исте|подтверж/i);assert.equal(f.ui.state.auto,false)}finally{await f.ui.stop()}
});

test('a server-stopped session remains stopped and never starts itself while renewing',async t=>{
 const calls=[],f=await fixture(t,{send:async({args:a})=>{calls.push(a.action);return a.action==='personal_heartbeat'?{ok:false,active:false,error:'Личная сессия остановлена'}:{ok:true,active:a.action!=='personal_stop',lease_seconds:45,auto_enabled:false}}});
 await f.ui.start();await f.ui.heartbeat();await f.ui.heartbeat();assert.equal(f.ui.state.active,false);assert.equal(calls.filter(x=>x==='personal_start').length,1);assert.equal(f.ui.state.auto,false);await f.ui.stop();
});

test('a late old start only stops its exact old server epoch, never a newer session',async t=>{
 const old=deferred(),calls=[];let starts=0,serverEpoch=0,active=false;
 const f=await fixture(t,{send:async({args:a})=>{
  calls.push(a);if(a.action==='personal_start'){active=true;serverEpoch++;if(++starts===1)return old.promise;return{ok:true,active:true,lease_seconds:45,mode_epoch:serverEpoch,auto_enabled:false}}
  if(a.action==='personal_stop'&&(a.expected_mode_epoch===undefined||a.expected_mode_epoch===serverEpoch))active=false;
  return{ok:true,active,lease_seconds:45,auto_enabled:false};
 }});
 const first=f.ui.start();await settle();await f.ui.stop();const next=f.ui.start();
 old.resolve({ok:true,active:true,lease_seconds:45,mode_epoch:1,auto_enabled:false});await first;await next;
 try{assert.equal(active,true,'cleanup for epoch1 must not stop epoch2');assert.equal(f.ui.state.active,true);
  assert.ok(calls.filter(a=>a.action==='personal_stop').every(a=>a.expected_mode_epoch===1))}
 finally{await f.ui.stop()}
});

test('a late old start cannot send cleanup as the newly selected actor',async t=>{
 const old=deferred(),stops=[];let starts=0;
 const f=await fixture(t,{send:async({args:a})=>{
  if(a.action==='personal_start'&&++starts===1)return old.promise;
  if(a.action==='personal_stop')stops.push(a.operator_id);
  return{ok:true,active:a.action!=='personal_stop',lease_seconds:45,mode_epoch:1,auto_enabled:false};
 }});
 const first=f.ui.start();await settle();await f.ui.selectAuthor(other);const next=f.ui.start();
 old.resolve({ok:true,active:true,lease_seconds:45,mode_epoch:1,auto_enabled:false});await first;await next;
 try{assert.deepEqual(stops,[]);assert.equal(f.ui.state.active,true);assert.equal(f.ui.state.operator,other)}finally{await f.ui.stop()}
});

test('an obsolete start without a server epoch cannot issue a blanket stop',async t=>{
 const old=deferred(),stops=[];
 const f=await fixture(t,{send:async({args:a})=>{
  if(a.action==='personal_start')return old.promise;if(a.action==='personal_stop')stops.push(a);
  return{ok:true,active:false,auto_enabled:false};
 }});
 const first=f.ui.start();await settle();await f.ui.stop();old.resolve({ok:true,active:true,lease_seconds:45,auto_enabled:false});await first;
 assert.deepEqual(stops,[]);assert.equal(f.ui.state.active,false);
});
