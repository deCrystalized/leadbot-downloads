'use strict';
// Actual Node -> Python/identity/session; no customer/model/native writes.
const test=require('node:test'),assert=require('node:assert/strict');
const{harness}=require('./helpers/auto_harness232.cjs');
test('conditional cleanup reaches the actual Python session without losing the server epoch',async t=>{
 const h=await harness(t,[]),first=await h.call('personal_status');
 await h.personal.start();const second=await h.call('personal_status');assert.ok(second.mode_epoch>first.mode_epoch);
 const result=await h.call('personal_stop',undefined,{expected_mode_epoch:first.mode_epoch,
  connection_epoch:second.connection_epoch,control_seq:1});
 assert.equal(result.stop_not_applied,true,JSON.stringify(result));
 assert.equal((await h.call('personal_status')).active,true);assert.deepEqual(h.effects,[]);
 assert.equal((await h.evidence()).simulated_model_calls,0);
});
test('a malformed conditional cleanup cannot become an unconditional stop in the bridge',async t=>{
 const h=await harness(t,[]);
 const result=await h.call('personal_stop',undefined,{expected_mode_epoch:true,
  connection_epoch:h.session.connection_epoch,control_seq:1});
 assert.equal(result.ok,false);assert.equal(result.code,'personal_stop_epoch');
 assert.equal((await h.call('personal_status')).active,true);assert.deepEqual(h.effects,[]);
});

test('the actual bridge retains ordered connection/sequence and never turns a stale command into a stop',async t=>{
 const h=await harness(t,[]),old=await h.call('personal_status');
 await h.personal.start();await h.mode('auto');
 const current=await h.call('personal_status');
 for(const extra of [
  {connection_epoch:old.connection_epoch,control_seq:900},
  {connection_epoch:current.connection_epoch,control_seq:current.control_seq},
  {connection_epoch:current.connection_epoch,control_seq:true},
 ]){
  const rejected=await h.call('personal_stop',undefined,extra);
  assert.equal(rejected.code,'personal_control_obsolete',JSON.stringify(rejected));
 }
 assert.equal((await h.call('personal_status')).auto_enabled,true);
 const stopped=await h.personal.stop();assert.equal(h.personal.state.active,false);
 assert.equal((await h.call('personal_status')).active,false);
 assert.deepEqual(h.effects,[]);assert.equal((await h.evidence()).simulated_model_calls,0);
});
