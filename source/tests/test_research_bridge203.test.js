'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {createAssistant}=require('../extension-server/brain/assistant');
const workflow=require('../ext/workflow');
const response=data=>({ok:true,status:200,json:async()=>data});

test('trusted research profile starts a durable job without Giga or browser model/grant fields',async()=>{
 const calls=[];
 const assistant=createAssistant({env:{LEADBOT_SERVICE_TOKEN:'test-only',LEADBOT_RESEARCH_PROFILE:'sol_only'},
  запрос:async(_url,options)=>{const body=JSON.parse(options.body);calls.push(body);return response(body.action==='preview'
   ?{ok:true,pending_model:true,request_id:'rid',revision:'rev',model_task:{system:'trusted',task:'trusted'}}
   :{ok:true,pending_research:true,research_job_id:'job',request_id:'rid',revision:'rev',reply:''})},
  ai:{спросить:async()=>assert.fail('No legacy model fallback')}});
 const out=await assistant({action:'preview',wording_mode:'neural_review',ctx:{convId:'chat'},identity_proof:'proof',browser_session:'device:test',operator_id:'actor',model:'gpt-6-luna',grant_id:'mine',max_calls:999,candidate:{reply:'fake'}},'owner','model');
 assert.equal(out.pending_research,true);assert.deepEqual(calls.map(x=>x.action),['preview','research_start']);
 assert.equal(calls[1].request_id,'rid');assert.equal(calls[1].identity_proof,'proof');
 assert.deepEqual(Object.keys(calls[1]).sort(),['action','ctx','identity_proof','browser_session','operator_id','owner','request_id','revision'].sort());
 assert.equal(calls[1].browser_session,'device:test');
 for(const body of calls)for(const key of ['model','grant_id','max_calls','candidate'])assert.equal(body[key],undefined);
});

test('research status/audit/cancel relay only safe scope and no client authority fields',async()=>{
 const calls=[];const assistant=createAssistant({env:{LEADBOT_SERVICE_TOKEN:'test-only'},
  запрос:async(_url,options)=>{calls.push(JSON.parse(options.body));return response({ok:true,reply:''})},ai:{спросить:()=>assert.fail()}});
 for(const action of ['research_status','research_audit','research_cancel','research_finalize'])await assistant({action,ctx:{convId:'chat'},research_job_id:'job',request_id:'rid',revision:'rev',audit_cursor:4,audit_limit:10,owner:'another',accepted:true,reviewer:'root'},'owner','model');
 assert.equal(calls.length,4);for(const row of calls){assert.equal(row.owner,'owner');assert.equal(row.research_job_id,'job');assert.equal(row.accepted,undefined);assert.equal(row.reviewer,undefined)}
});

test('lost browser state resumes the same pending job and finalizes only an already root-accepted result',async()=>{
 const calls=[];const assistant=createAssistant({env:{LEADBOT_SERVICE_TOKEN:'test-only',LEADBOT_RESEARCH_PROFILE:'sol_only'},
  запрос:async(_url,options)=>{const b=JSON.parse(options.body);calls.push(b);return response(b.action==='preview'
   ?{ok:false,code:'pending',request_id:'rid',revision:'rev'}:b.action==='research_start'
    ?{ok:true,research_state:'accepted',research_job_id:'job',request_id:'rid',revision:'rev'}
    :{ok:true,reply:'Проверенный ответ',draft_id:'existing'})},ai:{спросить:()=>assert.fail('No Giga fallback')}});
 const out=await assistant({action:'preview',ctx:{convId:'chat'},_trusted_research_profile:'gpt-6-luna'},'owner','model');
 assert.equal(out.draft_id,'existing');assert.deepEqual(calls.map(x=>x.action),['preview','research_start','research_finalize']);
 assert.equal(calls[0]._trusted_research_profile,'sol_only');assert.equal(calls[0].wording_mode,'neural_review');
 assert.equal(calls[2].research_job_id,'job');
 assert.equal(calls[2]._trusted_research_profile,undefined);
 assert.equal(calls[2].wording_mode,undefined);
});

function fixture(){
 const calls=[],ctx={convId:'chat',assigneeId:'actor',revision:'r1'};let state='queued';
 const deps={operator:()=> 'actor',visible:()=>true,snapshot:async()=>({ctx:{...ctx},operatorId:'actor',active:true,mineCount:0}),
  plan:async s=>({ok:true,operator_id:'actor',revision:s.ctx.revision,eligible:true,step:'reply',scope:'mine'}),
  read:async()=>null,pending:async()=>[],lock:async(_key,fn)=>fn(),
  preview:async()=>{calls.push('preview');return{ok:true,reply:'',pending_research:true,research_state:'queued',research_job_id:'job',request_id:'rid',revision:ctx.revision}},
  research:async(action,s,args)=>{calls.push(action);assert.equal(args.research_job_id,'job');return action==='research_finalize'
   ?{ok:true,reply:'Материал стены подскажите?',draft_id:'draft',needs_operator:false}
   :{ok:true,reply:'',pending_research:state==='running',requires_root:state==='awaiting_root',research_state:state,research_job_id:'job',request_id:'rid',revision:'r1'}},
  authorize:async()=>assert.fail('No external action'),sendReply:async()=>assert.fail('No send')};
 return{ui:workflow.create(deps),calls,ctx,setState:value=>{state=value}};
}

test('five-minute research waits between browser ticks without repeated preview or human handoff',async()=>{
 const f=fixture();assert.equal((await f.ui.step('chat')).step,'wait');
 f.setState('running');assert.equal((await f.ui.step('chat')).step,'wait');
 f.setState('awaiting_root');const view=await f.ui.inspect('chat');assert.equal(view.step,'wait');assert.equal(view.needs_operator,false);
 assert.deepEqual(f.calls,['preview','research_status','research_status']);
});

test('accepted research finalizes the same job before exposing a reviewed draft',async()=>{
 const f=fixture();await f.ui.inspect('chat');f.setState('accepted');const out=await f.ui.inspect('chat');
 assert.equal(out.draft_id,'draft');assert.match(out.reply,/Материал/);assert.deepEqual(f.calls,['preview','research_status','research_finalize']);
});

test('changed revision cancels the old job and cannot send its old answer',async()=>{
 const f=fixture();await f.ui.inspect('chat');f.ctx.revision='r2';
 assert.equal((await f.ui.step('chat')).step,'wait');assert.deepEqual(f.calls,['preview','research_cancel']);
});

test('awaiting exact admission polls without a job or another preview and adopts the admitted job',async()=>{
 const calls=[],ctx={convId:'chat',revision:'r1'};let admitted=false;
 const value=()=>({ok:true,reply:'',pending_research:true,pending_admission:!admitted,
  research_state:admitted?'queued':'awaiting_admission',research_job_id:admitted?'job':'',request_id:'rid',revision:'r1'});
 const api=workflow.create({visible:()=>true,operator:()=> 'actor',snapshot:async()=>({ctx,operatorId:'actor',active:true,mineCount:0}),
  plan:async()=>({ok:true,operator_id:'actor',revision:'r1',eligible:true,step:'reply',scope:'mine'}),
  read:async()=>null,pending:async()=>[],lock:async(k,fn)=>fn(),
  preview:async()=>{calls.push('preview');return value()},
  research:async(action,s,args)=>{calls.push([action,args.research_job_id]);return value()},
  authorize:()=>assert.fail('No customer operation while waiting')});
 let out=await api.step('chat');assert.equal(out.step,'wait');assert.match(out.reason,/допуск/);
 out=await api.step('chat');assert.equal(out.step,'wait');assert.deepEqual(calls,['preview',['research_status','']]);
 admitted=true;await api.step('chat');await api.step('chat');
 assert.deepEqual(calls.at(-1),['research_status','job']);assert.equal(calls.filter(v=>v==='preview').length,1);
});

test('pending admission cancellation uses the original request without inventing a job id',async()=>{
 const calls=[],ctx={convId:'chat',revision:'r1'};
 const api=workflow.create({visible:()=>true,operator:()=> 'actor',snapshot:async()=>({ctx,operatorId:'actor',active:true,mineCount:0}),
  plan:async()=>({ok:true,operator_id:'actor',revision:ctx.revision,eligible:true,step:'reply',scope:'mine'}),
  read:async()=>null,pending:async()=>[],lock:async(k,fn)=>fn(),
  preview:async()=>({ok:true,reply:'',pending_research:true,pending_admission:true,research_state:'awaiting_admission',
    research_job_id:'',request_id:'rid',revision:'r1'}),
  research:async(action,s,args)=>{calls.push([action,args.research_job_id,args.request_id]);return{ok:true,research_state:'cancelled'}},
  authorize:()=>assert.fail('No write')});
 await api.step('chat');ctx.revision='r2';const out=await api.step('chat');assert.equal(out.step,'wait');
 assert.deepEqual(calls,[['research_cancel','','rid']]);
});

test('first admission poll can already return an accepted job and finalize uses its real identity',async()=>{
 const calls=[];
 const api=workflow.create({visible:()=>true,operator:()=> 'actor',snapshot:async()=>({ctx:{convId:'chat',revision:'r1'},operatorId:'actor',active:true,mineCount:0}),
  plan:async()=>({ok:true,operator_id:'actor',revision:'r1',eligible:true,step:'reply',scope:'mine'}),
  read:async()=>null,pending:async()=>[],lock:async(k,fn)=>fn(),
  preview:async()=>({ok:true,reply:'',pending_research:true,pending_admission:true,research_state:'awaiting_admission',research_job_id:'',request_id:'rid',revision:'r1'}),
  research:async(action,s,args)=>{calls.push([action,args.research_job_id]);return action==='research_status'
    ?{ok:true,research_state:'accepted',research_job_id:'real-job',request_id:'rid',revision:'r1'}
    :{ok:true,reply:'Проверенный ответ',draft_id:'draft',needs_operator:false}},
  authorize:()=>assert.fail('Inspection never sends')});
 await api.inspect('chat');const out=await api.inspect('chat');assert.equal(out.draft_id,'draft');
 assert.deepEqual(calls,[['research_status',''],['research_finalize','real-job']]);
});
