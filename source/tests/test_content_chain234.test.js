'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const Workflow=require('../ext/workflow');
const {harness}=require('./helpers/auto_harness232.cjs');
const {contentChain}=require('./helpers/content_chain234.cjs');
const actor='11111111-1111-4111-8111-111111111111';
async function setup(t,options={}){
 const h=await harness(t,['first']);await h.rpc({op:'enable_form'});
 await h.rpc({op:'ready',cid:'first'});await h.rpc({op:'update',cid:'first',changes:{channel:'avito'}});
 h.jobs.set('first',{id:'first',operator_id:actor,state:'waiting',version:1});
 const chain=contentChain(h,options);return{h,chain};
}
async function acceptForm(h){
 await h.runner.start('auto');assert.ok(!h.effects.some(e=>e.kind==='create'));
 await h.admit();await h.runner.tick();await h.rpc({op:'run_workers'});await h.runner.tick();
 assert.ok(!h.effects.some(e=>e.kind==='create'));
 await h.accept();await h.runner.tick();
}
test('actual content create wrapper and Telegram route complete only after the reviewed form and card verification',async t=>{
 const {h,chain}=await setup(t);await acceptForm(h);
 assert.equal(h.runner.state.error,'',JSON.stringify(h.runner.state));
 assert.equal(h.runner.state.rows[0].step,'done',JSON.stringify({state:h.runner.state,calls:chain.calls,entries:[...h.storage.values()]}));
 assert.deepEqual(h.effects.map(e=>e.kind),['create','read_card_and_dedup','telegram_confirmed','complete']);
 const create=chain.calls.find(c=>c.op==='create');assert.equal(create.args.personalWorkflow,true);
 assert.equal(create.args.allowLive,false);assert.equal(create.args.workflow_guard.native_job_version,1);
 const tg=chain.calls.find(c=>c.kind==='lcz-tg');assert.match(tg.args.text,/9000001/);
 assert.equal(tg.args.conv,'first');assert.equal(tg.args.reply_to,170);
 await h.runner.tick();assert.equal(chain.calls.filter(c=>c.op==='create').length,1);
 assert.equal((await h.evidence()).simulated_model_calls,2);
});
for(const failure of ['createUnknown','cardMismatch','readbackDuplicate','missingGroup','missingTopic','telegramUnknown','telegramReject'])
test('content chain '+failure+' never closes or repeats creation/notification after restart',async t=>{
 const {h,chain}=await setup(t,{[failure]:true});await acceptForm(h);
 assert.ok(!h.effects.some(e=>e.kind==='complete'),JSON.stringify(h.effects));
 assert.equal(chain.calls.filter(c=>c.op==='create').length,1);
 if(failure==='createUnknown')assert.ok(h.effects.some(e=>e.kind==='create_unknown'));
 else assert.ok(h.effects.some(e=>e.kind==='read_card_and_dedup'));
 assert.equal(chain.calls.filter(c=>c.kind==='lcz-tg').length,['telegramUnknown','telegramReject'].includes(failure)?1:0);
 const before=chain.calls.filter(c=>c.op==='create'||c.kind==='lcz-tg').length;
 h.runner.stop();const recovered=Workflow.create(h.deps);await recovered.step('first');
 assert.equal(chain.calls.filter(c=>c.op==='create'||c.kind==='lcz-tg').length,before);
 assert.notEqual((await h.rpc({op:'context',cid:'first'})).conversationStatus,'closed');
});
