'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const workflow=require('../ext/workflow');

function fixture({scope='mine',intake=null}={}){
  const calls=[],ctx={convId:'chat',assigneeId:scope==='mine'?'actor':'',revision:'r1'};
  let ready=false;
  const deps={visible:()=>true,operator:()=> 'actor',
    snapshot:async()=>({ctx:structuredClone(ctx),operatorId:'actor',active:true,mineCount:0}),
    plan:async()=>({ok:true,operator_id:'actor',revision:ctx.revision,eligible:true,step:'inspect_media',scope}),
    intakeGuard:()=>intake,read:async()=>null,pending:async()=>[],lock:async(k,fn)=>fn(),
    preview:async()=>{calls.push('preview');return {ok:true,pending_research:true,research_state:'queued',
      research_job_id:'job',request_id:'rid',revision:ctx.revision,reply:''}},
    research:async(action)=>{calls.push(action);return action==='research_finalize'
      ?{ok:true,visual_observation_ready:true,refresh_preview:true,human_media_review:false,action:'wait',reply:''}
      :{ok:true,research_state:ready?'accepted':'running',pending_research:!ready,
        research_job_id:'job',request_id:'rid',revision:'r1'}},
    authorize:()=>assert.fail('Observation never authorizes a write'),claim:()=>assert.fail('No claim before photo'),
    sendReply:()=>assert.fail('No visual note to client'),prepareCRM:()=>assert.fail('No order'),save:()=>assert.fail('No customer operation journal')};
  return {api:workflow.create(deps),calls,ctx,complete:()=>{ready=true}};
}

test('visual phase waits without taking a free conversation or sending a description',async()=>{
  const f=fixture({scope:'free'});const r=await f.api.step('chat');
  assert.equal(r.step,'wait');assert.equal(r.needs_operator,false);assert.deepEqual(f.calls,['preview']);
});

test('paired visual completion returns wait and drops old job before a fresh preview',async()=>{
  const f=fixture();await f.api.step('chat');f.complete();
  const ready=await f.api.step('chat');assert.equal(ready.step,'wait');assert.equal(ready.needs_operator,false);
  assert.deepEqual(f.calls,['preview','research_status','research_finalize']);
  f.ctx.revision='r2';await f.api.step('chat');assert.equal(f.calls.at(-1),'preview');
  assert.equal(f.calls.filter(x=>x==='research_cancel').length,0);
});

test('read-only inspect does not hand visual completion off to a human',async()=>{
  const f=fixture();await f.api.inspect('chat');f.complete();
  const r=await f.api.inspect('chat');assert.equal(r.step,'wait');assert.equal(r.needs_operator,false);
});

test('existing order intake guard precedes any paid photo processing',async()=>{
  const f=fixture({intake:{eligible:false,step:'handoff',needs_operator:true,reason:'Existing Waiting order'}});
  const r=await f.api.step('chat');assert.equal(r.step,'handoff');assert.deepEqual(f.calls,[]);
});
