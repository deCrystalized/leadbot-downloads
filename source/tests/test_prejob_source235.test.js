'use strict';
// Real Runner/Workflow/bridge/native context; all external effects simulated.
const test=require('node:test'),assert=require('node:assert/strict');
const {harness}=require('./helpers/auto_harness232.cjs');

test('another staff claim before first admission skips the stale chat and preserves the other rehearsal',async t=>{
 const h=await harness(t,['first','second']);let changed=false;
 h.hooks.beforeCall=async body=>{
  if(!changed&&body.action==='research_start'&&body.ctx.convId==='first'){
   changed=true;
   const ctx=await h.rpc({op:'context',cid:'first'});
   await h.rpc({op:'update',cid:'first',changes:{
    assigneeId:'33333333-3333-4333-8333-333333333333',conversationStatus:'in_progress',
    messages:[...ctx.messages,{id:'other-claim',direction:'system',sender_type:'system',body:'Диалог принят другим сотрудником'}]}});
  }
 };
 await h.runner.start('review');
 assert.equal(changed,true,JSON.stringify({runner:h.runner.state,personal:h.personal.state.rows,wire:h.wire}));
 assert.equal(h.runner.state.mode,'review');assert.equal(h.runner.state.error,'');
 const stale=h.runner.state.rows.find(r=>r.id==='first');
 assert.equal(stale.step,'wait');assert.equal(stale.needs_operator,false);
 assert.match(stale.reason,/Диалог изменился/);
 assert.equal(h.runner.state.rows.find(r=>r.id==='second').step,'wait');
 await h.runner.tick();
 assert.ok(!h.runner.state.rows.some(r=>r.id==='first'));
 assert.equal(h.runner.state.mode,'review');assert.equal(h.runner.state.error,'');
 const evidence=await h.evidence();
 assert.equal(evidence.simulated_model_calls,0);assert.deepEqual(h.effects,[]);
 assert.ok(evidence.pending.pending.every(row=>row.chat!=='first'));
});

test('a new client message before admission drops the old preview and requires a fresh finite admission',async t=>{
 const h=await harness(t,['first']);let changed=false;
 h.hooks.beforeCall=async body=>{
  if(!changed&&body.action==='research_start'){
   changed=true;const ctx=await h.rpc({op:'context',cid:'first'});
   await h.rpc({op:'update',cid:'first',changes:{messages:[...ctx.messages,
    {id:'more-context',direction:'in',sender_type:'client',body:'Уточнение: полка на кухне.'}]}});
  }
 };
 await h.runner.start('review');
 assert.ok(h.runner.state.rows.length,JSON.stringify({runner:h.runner.state,personal:h.personal.state.rows,wire:h.wire}));
 assert.equal(h.runner.state.rows[0].step,'wait');
 assert.match(h.runner.state.rows[0].reason,/Диалог изменился/);
 await h.runner.tick();
 assert.equal(h.runner.state.mode,'review');assert.equal(h.runner.state.error,'');
 assert.equal(h.runner.state.rows[0].research_state,'awaiting_admission');
 const e=await h.evidence();assert.equal(e.simulated_model_calls,0);
 assert.equal(e.pending.pending_total,1);assert.equal(e.pending.calls_remaining,0);
 assert.deepEqual(h.effects,[]);
});
