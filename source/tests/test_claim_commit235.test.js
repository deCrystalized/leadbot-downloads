'use strict';
// Existing native/content/workflow code; only external effects and model I/O
// are simulated. The original server failure is preserved separately.
const test=require('node:test'),assert=require('node:assert/strict');
const Workflow=require('../ext/workflow');
const {harness}=require('./helpers/auto_harness232.cjs');
const {contentChain}=require('./helpers/content_chain234.cjs');

for(const reassigned of [false,true])test('committed claim with lost HTTP response '+(reassigned?'cannot recover another assignment':'recovers without a second claim'),async t=>{
 const h=await harness(t,['first']);contentChain(h);await h.mode('auto');
 const claim=h.deps.claim;
 h.deps.claim=async s=>{await claim(s);throw Error('Synthetic committed native claim / response500')};
 await assert.rejects(Workflow.create(h.deps).step('first'),/Запрос мог выполниться/);
 assert.deepEqual(h.effects.map(e=>e.kind),['claim']);
 const original=[...h.storage.values()].find(r=>r.kind==='claim');assert.equal(original.state,'unknown');
 if(reassigned){
  await h.rpc({op:'update',cid:'first',changes:{assigneeId:'33333333-3333-4333-8333-333333333333'}});
  await assert.rejects(Workflow.create(h.deps).step('first'),/Предыдущее действие ещё не подтверждено/);
  assert.equal([...h.storage.values()].find(r=>r.kind==='claim').state,'unknown');
 }else{
  const result=await Workflow.create(h.deps).step('first');assert.equal(result.step,'wait');
  assert.equal([...h.storage.values()].find(r=>r.kind==='claim').state,'done');
  await Workflow.create(h.deps).step('first');
 }
 assert.deepEqual(h.effects.map(e=>e.kind),['claim'],'No duplicate claim, message, CRM write or Telegram');
 assert.equal((await h.evidence()).simulated_model_calls,0);
});
