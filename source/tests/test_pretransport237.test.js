'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const Workflow=require('../ext/workflow');
const {harness}=require('./helpers/auto_harness232.cjs');
const actor='11111111-1111-4111-8111-111111111111';

test('real authority expiry before claim waits without takeover; next pass obtains a fresh permit',async t=>{
 const h=await harness(t,['first']),plan=h.deps.plan,clock=Date.now;let reads=0;
 h.deps.plan=async s=>{const p=await plan(s);if(++reads===2)Date.now=()=>clock()+60000;return p};
 try{await h.runner.start('auto')}finally{Date.now=clock}
 assert.equal(reads,2);assert.equal(h.runner.state.error,'',JSON.stringify(h.runner.state));
 assert.equal(h.runner.state.mode,'auto');assert.equal(h.runner.state.rows[0]?.step,'wait');
 assert.equal(h.runner.state.rows[0]?.needs_operator,false);assert.deepEqual(h.effects,[]);
 const entry=[...h.storage.values()].find(v=>v.kind==='claim');
 assert.equal(entry?.state,'not_started');assert.equal(entry.transport_started,false);
 assert.equal(entry.preflight_rejected,true);
 h.deps.plan=plan;await h.runner.tick();
 assert.deepEqual(h.effects.map(v=>v.kind),['claim'],JSON.stringify({runner:h.runner.state,personal:h.personal.state,storage:[...h.storage]}));
 assert.equal(h.runner.state.rows[0]?.step,'wait');
 assert.equal((await h.evidence()).simulated_model_calls,0);
});

test('new client pause during preflight is rescreened without claiming or parking the conversation',async t=>{
 const h=await harness(t,['first']),plan=h.deps.plan;let reads=0;
 h.deps.plan=async s=>{
  if(++reads===2){const ctx=await h.rpc({op:'context',cid:'first'});
   await h.rpc({op:'update',cid:'first',changes:{messages:[...ctx.messages,
    {id:'pause-before-claim',direction:'in',sender_type:'client',body:'Секунду, подождите.'}]}});
   s={...s,ctx:await h.rpc({op:'context',cid:'first'})};
  }return plan(s);
 };
 await h.runner.start('auto');assert.equal(h.runner.state.error,'',JSON.stringify(h.runner.state));
 assert.equal(h.runner.state.mode,'auto');assert.equal(h.runner.state.rows[0]?.step,'wait');
 assert.deepEqual(h.effects,[]);h.deps.plan=plan;await h.runner.tick();
 assert.deepEqual(h.effects,[]);assert.equal((await h.evidence()).simulated_model_calls,0);
 assert.equal([...h.storage.keys()].some(k=>k.startsWith('human-hold:')),false);
});

test('actual auto revocation before transport stops the runner without takeover or auto restart',async t=>{
 const h=await harness(t,['first']),plan=h.deps.plan;let reads=0;
 h.deps.plan=async s=>{if(++reads===2)await h.mode('review');return plan(s)};
 await h.runner.start('auto');assert.equal(h.runner.state.mode,'stopped',JSON.stringify(h.runner.state));
 assert.match(h.runner.state.error,/изменились|выключен/);assert.deepEqual(h.effects,[]);
 assert.equal([...h.storage.keys()].some(k=>k.startsWith('human-hold:')),false);
 assert.equal((await h.call('personal_status')).auto_enabled,false);
});

test('failed durable no-start save retains pending uncertainty and cannot retry after restart',async t=>{
 const h=await harness(t,['first']),plan=h.deps.plan,save=h.deps.save,clock=Date.now;let reads=0;
 await h.mode('auto');
 h.deps.plan=async s=>{const p=await plan(s);if(++reads===2)Date.now=()=>clock()+60000;return p};
 h.deps.save=async(k,v)=>{if(v.state==='not_started')throw Error('synthetic durable save failed');return save(k,v)};
 try{await assert.rejects(Workflow.create(h.deps).step('first'),/durable save failed/)}finally{Date.now=clock}
 assert.equal([...h.storage.values()].find(v=>v.kind==='claim')?.state,'pending');
 h.deps.plan=plan;h.deps.save=save;
 await assert.rejects(Workflow.create(h.deps).step('first'),/Предыдущее действие/);
 assert.deepEqual(h.effects,[]);
});

test('an attempted transport remains unknown and cannot replay even after a new source revision',async t=>{
 const h=await harness(t,['first']);await h.mode('auto');let attempts=0;
 h.deps.claim=async()=>{attempts++;throw Error('synthetic lost response after transport')};
 await assert.rejects(Workflow.create(h.deps).step('first'),/мог выполниться/);
 assert.equal([...h.storage.values()].find(v=>v.kind==='claim')?.state,'unknown');
 const ctx=await h.rpc({op:'context',cid:'first'});
 await h.rpc({op:'update',cid:'first',changes:{messages:[...ctx.messages,
  {id:'followup',direction:'in',sender_type:'client',body:'Можно сегодня?'}]}});
 await assert.rejects(Workflow.create(h.deps).step('first'),/Предыдущее действие/);
 assert.equal(attempts,1);assert.equal((await h.evidence()).simulated_model_calls,0);
});

test('lost final authorization reply cannot release the permanent server grant or repeat claim',async t=>{
 const h=await harness(t,['first']),authorize=h.deps.authorize;await h.mode('auto');let finals=0;
 h.deps.authorize=async(s,op)=>{const r=await authorize(s,op);if(!op.preflight_only){finals++;throw Error('synthetic lost final grant response')}return r};
 await assert.rejects(Workflow.create(h.deps).step('first'),e=>e.code==='workflow_permission');
 assert.equal(finals,1);assert.deepEqual(h.effects,[]);
 assert.equal([...h.storage.values()].find(v=>v.kind==='claim')?.state,'pending');
 h.deps.authorize=authorize;
 await assert.rejects(Workflow.create(h.deps).step('first'),/Предыдущее действие/);
 assert.deepEqual(h.effects,[]);
});

test('CRM preparation rejected before dispatch can be inspected and created once on a fresh pass',async t=>{
 const h=await harness(t,['first']);await h.rpc({op:'ready',cid:'first'});
 h.jobs.set('first',{id:'first',operator_id:actor,state:'waiting',version:1});
 const plan=h.deps.plan,clock=Date.now;let reads=0;
 h.deps.plan=async s=>{const p=await plan(s);if(++reads===4)Date.now=()=>clock()+60000;return p};
 try{await h.runner.start('auto')}finally{Date.now=clock}
 assert.equal(h.runner.state.error,'',JSON.stringify(h.runner.state));
 assert.equal(h.runner.state.rows[0]?.step,'wait');assert.deepEqual(h.effects,[]);
 const entry=[...h.storage.values()].find(v=>v.kind==='create_crm');assert.equal(entry?.state,'not_started');
 h.deps.plan=plan;const preview=await Workflow.create(h.deps).inspect('first');
 assert.equal(preview.step,'prepare_crm');assert.deepEqual(h.effects,[]);
 await h.runner.tick();assert.equal(h.runner.state.error,'',JSON.stringify(h.runner.state));
 assert.equal(h.runner.state.rows[0]?.step,'done',JSON.stringify(h.runner.state));
 assert.deepEqual(h.effects.map(v=>v.kind),['create','read_card_and_dedup','telegram_confirmed','complete']);
 await h.runner.tick();assert.equal(h.effects.length,4);
 assert.equal((await h.evidence()).simulated_model_calls,0);
});

for(const [name,change] of [
 ['legacy blocked',{state:'blocked'}],['legacy aborted',{state:'aborted'}],
 ['missing no-transport marker',{transport_started:undefined}],
 ['attempted marker',{transport_started:true}],['different owner',{operator:'another'}],
 ['different conversation',{conv:'another'}],['missing preflight marker',{preflight_rejected:undefined}],
 ['known result',{result:{id:'known-created-id'}}]
])test(name+' journal cannot be reclassified as permission to retry',async t=>{
 const h=await harness(t,['first']);await h.mode('auto');
 h.storage.set('workflow:'+actor+':first:claim:original',{
  state:'not_started',transport_started:false,preflight_rejected:true,
  kind:'claim',operator:actor,conv:'first',revision:'old',operation_id:'original',at:Date.now(),...change});
 await assert.rejects(Workflow.create(h.deps).step('first'),/Предыдущее действие/);
 assert.deepEqual(h.effects,[]);assert.equal((await h.evidence()).simulated_model_calls,0);
});
