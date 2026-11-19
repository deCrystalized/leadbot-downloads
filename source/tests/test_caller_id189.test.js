'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {callerIdCallReview}=require('../ext/workflow');
const plan=()=>({ok:true,auto_enabled:false,caller_id_callback:{rule_id:'OWNER-CALLER-ID-SAVE-CALLBACK-20261024',
  status:'operator_review',customer_contact_verified:true,contact_phone:'79000000001',
  timing_constraints:[{quote:'Звоните после 17.00'}],execution_allowed:false,call_executed:false}});
test('manual review preserves recipient and quoted time without inventing a call action',()=>{
  const result=plan(),before=structuredClone(result),v=callerIdCallReview(result);
  assert.equal(v.phone,'79000000001');assert.deepEqual(v.timing,['Звоните после 17.00']);
  assert.match(v.instruction,/Если можете позвонить/);assert.match(v.instruction,/Пару минут, наберу вам/);
  assert.deepEqual(result,before);assert.equal(v.execute,undefined);
});
test('missing contact cannot display a future contact or immediate call promise',()=>{
  const result=plan();Object.assign(result.caller_id_callback,{status:'awaiting_contact',customer_contact_verified:false});
  const v=callerIdCallReview(result);assert.equal(v.phone,'');assert.match(v.instruction,/Сначала получите номер/);
  assert.doesNotMatch(v.instruction,/наберу/);
});
test('reported visibility and cancellation remove the repeated callback instruction',()=>{
  for(const status of ['client_reported_visible','cancelled']){
    const result=plan();result.caller_id_callback.status=status;const v=callerIdCallReview(result);
    assert.equal(v.phone,'');assert.deepEqual(v.timing,[]);assert.doesNotMatch(v.instruction,/Пару минут/);
  }
});
test('untrusted or executable result cannot be presented as this read-only manual plan',()=>{
  for(const result of [{},{...plan(),auto_enabled:true},{...plan(),ok:false},
    {...plan(),caller_id_callback:{...plan().caller_id_callback,execution_allowed:true}},
    {...plan(),caller_id_callback:{...plan().caller_id_callback,call_executed:true}}])assert.equal(callerIdCallReview(result),null);
});
