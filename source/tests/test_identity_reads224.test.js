'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {create}=require('../ext/personal');
const turn=()=>new Promise(r=>setImmediate(r));
async function fixture(t){
 let now=1000000,version=0;const used=[];
 t.mock.method(Date,'now',()=>now);
 const ui=create({getIdentity:async()=>({id:'admin',role:'admin'}),getAuthors:async()=>({principal:{id:'admin'},authors:[{id:'admin'}]}),
  getProof:async()=>({identity_proof:'synthetic-'+(++version),browser_session:'browser',expires_at:now/1000+45}),
  send:async({args})=>{used.push(args);return{ok:true,active:args.action!=='personal_stop',lease_seconds:45}},visible:()=>true});
 await ui.start();t.after(()=>ui.stop());
 return{ui,used,get version(){return version},advance:ms=>{now+=ms}};
}
test('source observation requests a fresh proof when only eleven seconds remain',async t=>{
 const f=await fixture(t);const first=await f.ui.identityArgs();f.advance(34000);
 const next=await f.ui.identityArgs({minValidityMs:35000});
 assert.notEqual(next.identity_proof,first.identity_proof);assert.equal(f.version,2);
});
test('concurrent bounded source reads share their proof while heartbeat cannot revoke it',async t=>{
 const f=await fixture(t);let release;const held=new Promise(r=>{release=r});const proofs=[];
 const read=f.ui.withIdentity(async args=>{proofs.push(args.identity_proof);await held;return'ok'});
 await turn();const before=f.version;
 const second=f.ui.withIdentity(async args=>{proofs.push(args.identity_proof);return'ok'});await second;
 f.advance(36000);await f.ui.heartbeat();
 assert.equal(f.version,before);assert.equal(new Set(proofs).size,1);release();assert.equal(await read,'ok');
});
test('later source read waits before sending when protected proof lacks full budget',async t=>{
 const f=await fixture(t);let release;const held=new Promise(r=>{release=r});
 const first=f.ui.withIdentity(async()=>{await held;return'first'});await turn();f.advance(15000);
 let sent=false;const second=f.ui.withIdentity(async()=>{sent=true;return'second'});await turn();
 assert.equal(sent,false);assert.equal(f.version,1);release();await first;assert.equal(await second,'second');assert.equal(f.version,2);
});
test('Stop wakes queued reads and prevents both stale responses and new sends',async t=>{
 const f=await fixture(t);let release;const held=new Promise(r=>{release=r});
 const first=f.ui.withIdentity(async()=>{await held;return'late'});const firstError=assert.rejects(first);
 await turn();f.advance(15000);let sent=false;
 const second=f.ui.withIdentity(async()=>{sent=true});const secondError=assert.rejects(second);
 await turn();await f.ui.stop();await secondError;release();await firstError;assert.equal(sent,false);assert.equal(f.ui.state.auto,false);
});
test('unknown bounded RPC result never retries or accepts a late response',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});const f=await fixture(t);let release,calls=0;
 const pending=f.ui.withIdentity(async()=>{calls++;return new Promise(r=>{release=r})});
 const rejected=assert.rejects(pending,e=>e.code==='research_stopped'&&e.noRetry===true);
 await turn();t.mock.timers.tick(30001);await rejected;release({ok:true});await turn();assert.equal(calls,1);
});
test('expired protected proof is never reused by a heartbeat',async t=>{
 const f=await fixture(t);let release;const held=new Promise(r=>{release=r});
 const read=f.ui.withIdentity(async()=>{await held});const denied=assert.rejects(read);
 await turn();f.advance(46000);await f.ui.heartbeat();assert.equal(f.ui.state.active,false);
 assert.equal(f.used.filter(x=>x.action==='personal_heartbeat').length,0);release();await denied;
});
test('ordinary manual nondelegated path keeps its legacy transport contract',async()=>{
 const ui=create({getIdentity:async()=>({id:'operator'})});let calls=0;
 assert.equal(await ui.withIdentity(async args=>{calls++;assert.deepEqual(args,{});return'legacy'}),'legacy');assert.equal(calls,1);
});
test('actual screen transport starts with a full proof budget before any source read',async t=>{
 const f=await fixture(t);f.advance(34000);await f.ui.call('screen',{ctx:{convId:'synthetic'}});
 const sent=f.used.find(x=>x.action==='screen');assert.equal(sent.identity_proof,'synthetic-2');assert.equal(f.version,2);
});
test('waiting for a protected proof has a finite pre-send deadline',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});const f=await fixture(t);let release,calls=0;
 const first=f.ui.withIdentity(async()=>new Promise(r=>{release=r}));await turn();f.advance(15000);
 const second=f.ui.withIdentity(async()=>{calls++});const rejected=assert.rejects(second);
 await turn();t.mock.timers.tick(20001);await rejected;assert.equal(calls,0);release();await first;
});
test('an unresolved fresh proof cannot leave source acquisition pending forever',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});const f=await fixture(t);f.advance(34000);
 // One proof request can be held independently of the native-source transport.
 await f.ui.stop();let release;f.ui.state.active=true;f.ui.state.delegated=true;
 // Use a new fixture whose challenge becomes pending after its initial start.
 let pending=false;const ui=create({getIdentity:async()=>({id:'admin',role:'admin'}),getAuthors:async()=>({principal:{id:'admin'},authors:[{id:'admin'}]}),
  getProof:async()=>pending?new Promise(r=>{release=r}):{identity_proof:'synthetic',browser_session:'browser',expires_at:Date.now()/1000+45},
  send:async()=>({ok:true,active:true,lease_seconds:45})});
 await ui.start();pending=true;f.advance(34000);let sent=false;
 const work=ui.withIdentity(async()=>{sent=true});const rejected=assert.rejects(work);
 await turn();t.mock.timers.tick(20001);await rejected;assert.equal(sent,false);
 release({identity_proof:'late',browser_session:'browser',expires_at:Date.now()/1000+45});await turn();await ui.stop();
});
test('failed proof refresh cannot fall back to the server-revoked cached proof',async t=>{
 let now=1000000,version=0,short=false;t.mock.method(Date,'now',()=>now);
 const ui=create({getIdentity:async()=>({id:'admin',role:'admin'}),getAuthors:async()=>({principal:{id:'admin'},authors:[{id:'admin'}]}),
  getProof:async()=>({identity_proof:'synthetic-'+(++version),browser_session:'browser',expires_at:now/1000+(short?20:45)}),
  send:async()=>({ok:true,active:true,lease_seconds:45})});
 await ui.start();t.after(()=>ui.stop());now+=34000;short=true;
 await assert.rejects(ui.identityArgs({minValidityMs:35000}));short=false;
 const args=await ui.identityArgs();assert.equal(args.identity_proof,'synthetic-3');
});
