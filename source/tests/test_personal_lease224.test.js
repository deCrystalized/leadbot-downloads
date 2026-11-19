'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {create}=require('../ext/personal');
const {panelHarness}=require('./helpers/panel_harness236.cjs');

function fixture(overrides={}){
 const calls=[],deps={getIdentity:async()=>({id:'operator',full_name:'Operator'}),visible:()=>true,
  send:async({args})=>{calls.push(args.action);return{ok:true,active:args.action!=='personal_stop',lease_seconds:45,auto_enabled:false,mode_epoch:7}},...overrides};
 return{ui:create(deps),calls};
}

test('redraw after an unconfirmed lease cannot retain Connected or enable Auto',async t=>{
 const h=await panelHarness();t.after(()=>h.stop());
 const first=h.ui.personal.state.lastConfirmedAt;t.mock.method(Date,'now',()=>first+46000);
 h.ui.draw();
 assert.equal(h.ui.personal.state.active,false);
 assert.doesNotMatch(h.panel.textContent,/Подключён · авто выключено/);
 const auto=h.panel.querySelectorAll('button').find(b=>b.textContent==='Запустить авто');
 assert.equal(auto.disabled,true);assert.equal(h.ui.runner.state.mode,'stopped');assert.deepEqual(h.effects,[]);
});

test('identity completing after lease expiry cannot send another heartbeat or revive it',async t=>{
 let now=1000000,release;t.mock.method(Date,'now',()=>now);
 const held=new Promise(r=>{release=r});
 const slow=fixture({getIdentity:async()=>{if(now>1000000)return held;return{id:'operator'}}});
 await slow.ui.start();t.after(()=>slow.ui.stop());now+=15000;
 const pending=slow.ui.heartbeat();await new Promise(r=>setImmediate(r));
 now+=31000;release({id:'operator'});await pending;
 assert.equal(slow.calls.filter(a=>a==='personal_heartbeat').length,0);
 assert.equal(slow.ui.state.active,false);assert.equal(slow.ui.state.auto,false);
});

test('an unresolved identity cannot hold the heartbeat and green state indefinitely',async t=>{
 t.mock.timers.enable({apis:['setTimeout','Date'],now:1000000});
 let release,slow=false;const held=new Promise(r=>{release=r});
 const f=fixture({getIdentity:async()=>slow?held:{id:'operator'}});
 await f.ui.start();t.after(()=>f.ui.stop());slow=true;
 const pending=f.ui.heartbeat();await new Promise(r=>setImmediate(r));
 t.mock.timers.tick(12001);await new Promise(r=>setImmediate(r));
 try{assert.equal(f.ui.state.active,false);assert.equal(f.ui.state.auto,false)}
 finally{release({id:'operator'});await pending}
});

test('server lease is conservative from request start, not response receipt',async t=>{
 let now=1000000;t.mock.method(Date,'now',()=>now);
 const f=fixture({send:async()=>{now+=5000;return{ok:true,active:true,lease_seconds:45}}});
 await f.ui.start();t.after(()=>f.ui.stop());assert.equal(f.ui.state.lastConfirmedAt,1005000);assert.equal(f.ui.state.leaseExpiresAt,1045000);
 now=1045000;assert.equal(f.ui.checkLease(),false);assert.equal(f.ui.state.auto,false);
});
test('invalid supplied lease and rollback of the clock cannot keep a green session',async t=>{
 let now=1000000;t.mock.method(Date,'now',()=>now);
 for(const lease of [0,-1,'45',NaN,Infinity]){
  const f=fixture({send:async()=>({ok:true,active:true,lease_seconds:lease})});await f.ui.start();assert.equal(f.ui.state.active,false);await f.ui.stop();
 }
 const f=fixture();await f.ui.start();now--;assert.equal(f.ui.checkLease(),false);await f.ui.stop();
});
test('stale and concurrent pulses cannot generate extra session starts or duplicate I/O',async()=>{
 let id,release,held=false;const calls=[];
 const f=fixture({startPulse:async v=>{id=v;return{ok:true,connection_id:v}},stopPulse:async()=>{},
  send:async({args})=>{calls.push(args.action);if(held&&args.action==='personal_heartbeat')await new Promise(r=>{release=r});return{ok:true,active:true,lease_seconds:45}}});
 await f.ui.start();try{
  assert.equal((await f.ui.pulse('foreign')).active,false);assert.deepEqual(calls,['personal_start']);
  // A current alarm arriving just after a real response reuses freshness.
  assert.equal((await f.ui.pulse(id)).active,true);assert.deepEqual(calls,['personal_start']);
  held=true;const one=f.ui.heartbeat(),two=f.ui.heartbeat();await new Promise(r=>setImmediate(r));
  assert.equal(calls.filter(x=>x==='personal_heartbeat').length,1);release();await Promise.all([one,two]);
 }finally{await f.ui.stop()}
 assert.equal((await f.ui.pulse(id)).active,false);assert.equal(calls.filter(x=>x==='personal_start').length,1);
});
test('late mode response after Stop cannot revive Auto or its allowance',async()=>{
 let release;const f=fixture({send:async({args})=>{
  if(args.action==='personal_mode')return new Promise(r=>{release=r});
  return{ok:true,active:args.action!=='personal_stop',lease_seconds:45,auto_enabled:false};
 }});
 await f.ui.start();const mode=f.ui.setMode('auto');await new Promise(r=>setImmediate(r));await f.ui.stop();
 release({ok:true,active:true,auto_enabled:true,research_auto:{available:true,active:true,limit:128,remaining_calls:128}});
 await assert.rejects(mode);assert.equal(f.ui.state.active,false);assert.equal(f.ui.state.auto,false);assert.equal(f.ui.state.apiAllowance,null);
});

test('registration timeout stops locally and late registration is cleaned without reconnect',async t=>{
 t.mock.timers.enable({apis:['setTimeout','Date'],now:1000000});let release,id;const stopped=[];
 const f=fixture({startPulse:async v=>{id=v;return new Promise(r=>{release=r})},stopPulse:async v=>{stopped.push(v)}});
 const start=f.ui.start();await new Promise(r=>setImmediate(r));t.mock.timers.tick(12001);await start;
 assert.equal(f.ui.state.active,false);assert.equal(f.ui.state.auto,false);assert.equal(f.ui.state.busy,false);
 release({ok:true,connection_id:id});await new Promise(r=>setImmediate(r));assert.ok(stopped.includes(id));assert.equal(f.calls.filter(x=>x==='personal_start').length,1);
});

test('a synchronous cleanup hook failure cannot prevent Stop from clearing local authority',async()=>{
 let fail=true;const f=fixture({startPulse:async id=>({ok:true,connection_id:id}),stopPulse:()=>{if(fail)throw Error('synthetic cleanup failure')}});
 await f.ui.start();try{await f.ui.stop();assert.equal(f.ui.state.active,false);assert.equal(f.ui.state.auto,false)}
 finally{fail=false;await f.ui.stop()}
});
test('a synchronous cleanup hook failure cannot leave an expired lease green',async t=>{
 let now=1000000,fail=true;t.mock.method(Date,'now',()=>now);
 const f=fixture({startPulse:async id=>({ok:true,connection_id:id}),stopPulse:()=>{if(fail)throw Error('synthetic cleanup failure')}});
 await f.ui.start();try{now+=46000;assert.equal(f.ui.checkLease(),false);assert.equal(f.ui.state.active,false);assert.equal(f.ui.state.auto,false)}
 finally{fail=false;await f.ui.stop()}
});
