'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {harness}=require('./helpers/auto_harness232.cjs');
const {existingForm}=require('./helpers/existing_form233.cjs');
const Workflow=require('../ext/workflow');
const actor='11111111-1111-4111-8111-111111111111';

async function setup(t,options={}){
 const h=await harness(t,['first']);await h.rpc({op:'ready',cid:'first'});await h.rpc({op:'enable_form'});
 await h.rpc({op:'update',cid:'first',changes:{channel:'avito'}});
 h.jobs.set('first',{id:'first',operator_id:actor,state:'waiting',version:1});
 const ctx=await h.rpc({op:'context',cid:'first'}),form=existingForm(ctx,options);
 h.deps.formPreview=s=>h.call('form_preview',s.ctx,{wording_mode:'neural_auto'});
 h.deps.prepareCRM=(s,p,f)=>form.run(s,p,f);return{h,form};
}

test('actual reviewed form feeds existing readiness, CRM preparation, creation/readback/TG/close without legacy extraction',async t=>{
 const {h,form}=await setup(t);await h.runner.start('auto');
 assert.deepEqual(h.effects,[]);assert.equal(h.runner.state.rows[0]?.step,'wait',JSON.stringify(h.runner.state));
 await h.admit();await h.runner.tick();await h.rpc({op:'run_workers'});await h.runner.tick();
 assert.equal(h.effects.length,0);await h.accept();await h.runner.tick();
 assert.equal(h.runner.state.error,'',JSON.stringify(h.runner.state));
 assert.equal(h.runner.state.rows[0].step,'done',JSON.stringify({state:h.runner.state,calls:form.calls}));
 assert.deepEqual(h.effects.map(e=>e.kind),['create','read_card_and_dedup','telegram_confirmed','complete']);
 assert.ok(form.calls.some(r=>r.kind==='lcz-crm'&&r.op==='existing'));
 assert.ok(form.calls.some(r=>r.kind==='lcz-crm'&&r.op==='prepare'&&r.args.безИИ===true));
 assert.ok(form.calls.some(r=>r.kind==='lcz-checklist'));
 assert.ok(!form.calls.some(r=>r.kind==='lcz-extract'));
 assert.equal((await h.evidence()).simulated_model_calls,2);
 await h.runner.tick();assert.equal(h.effects.length,4);
});

for(const check of ['duplicate','map','checklist'])test('existing '+check+' guard still blocks creation after reviewed form',async t=>{
 const options=check==='duplicate'?{prep:{ok:true,cityText:'Чита',cityId:'1',applId:'2',subId:'3',live:'1091862'}}:
  check==='map'?{territory:{ok:true,approval:true,why:['Нужно согласование выезда']}}:
  {checklist:{ok:true,hard_block:true,reason:'Нужно согласование работы'}};
 const {h}=await setup(t,options);await h.runner.start('auto');await h.admit();await h.runner.tick();
 await h.rpc({op:'run_workers'});await h.runner.tick();await h.accept();await h.runner.tick();
 assert.ok(!h.effects.some(e=>e.kind==='create'),JSON.stringify(h.effects));
 assert.equal((await h.evidence()).simulated_model_calls,2);
});

for(const path of ['step','inspect'])test('semantic form veto is reported before CRM extraction in '+path,async t=>{
 const {h,form}=await setup(t);await h.mode('auto');
 await h.rpc({op:'provider_mode',mode:'review_rejected'});
 const workflow=Workflow.create(h.deps);
 assert.equal((await workflow[path]('first')).step,'wait');
 await h.admit();assert.equal((await workflow[path]('first')).step,'wait');
 await h.rpc({op:'run_workers'});
 const stopped=await workflow[path]('first');
 assert.equal(stopped.step,'handoff',JSON.stringify(stopped));
 assert.equal(stopped.needs_operator,true);
 assert.match(stopped.reason,/Описание заявки.*проверку/);
 assert.doesNotMatch(stopped.reason,/направлен/);
 assert.deepEqual(form.calls,[]);assert.deepEqual(h.effects,[]);
 assert.equal((await h.evidence()).simulated_model_calls,2);
 workflow.stop();
});
