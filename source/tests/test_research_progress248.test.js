'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const workflow=require('../ext/workflow'),personal=require('../ext/personal');

function fixture(){
 const data=new Map(),effects=[];
 const ctx={convId:'chat',assigneeId:'george',conversationStatus:'in_progress',crmRequestId:'',revision:'r1'};
 let value={ok:true,pending_research:true,research_state:'running',research_job_id:'job',request_id:'request',revision:'r1'};
 const deps={snapshot:async()=>({ctx:{...ctx},operatorId:'george',active:true,mineCount:0}),visible:()=>true,
  plan:async()=>({ok:true,operator_id:'george',auto_session_enabled:true,mode_epoch:1,revision:'r1',operation_id:'op',eligible:true,scope:'mine',step:'reply'}),
  preview:async()=>structuredClone(value),research:async(action)=>{effects.push(action);return structuredClone(value)},
  lock:async(key,fn)=>fn(),read:async key=>data.get(key),save:async(key,v)=>data.set(key,v),pending:async()=>[],
  authorize:async()=>{effects.push('authorize');throw Error('No permission expected while waiting')},
  sendReply:async()=>{effects.push('send');throw Error('No send expected')},
  pauseForHuman:async()=>{effects.push('park');throw Error('No handoff expected')}};
 return {ui:workflow.create(deps),effects,set:v=>{value=v}};
}

test('waiting for the shared queue before a job exists never becomes human handoff',async()=>{
 const f=fixture();f.set({ok:true,pending_research:true,research_state:'waiting_turn',research_job_id:'',request_id:'request',revision:'r1'});
 const result=await f.ui.step('chat');assert.equal(result.step,'wait');assert.equal(result.needs_operator,false);
 assert.match(result.reason,/очеред/);assert.deepEqual(f.effects,[]);
 f.set({ok:true,pending_research:true,research_state:'running',research_job_id:'job',request_id:'request',revision:'r1',progress:{stage:'reviewing',elapsed_seconds:95}});
 const next=await f.ui.step('chat');assert.equal(next.step,'wait');assert.match(next.reason,/Проверяет ответ/);
 assert.deepEqual(f.effects,[]); // A no-job wait was not stored as a research_status cursor.
});

test('an unscoped queue response is not accepted as an ordinary wait',async()=>{
 for(const change of [{request_id:''},{revision:'old'}]){
  const f=fixture();f.set({ok:true,pending_research:true,research_state:'waiting_turn',research_job_id:'',request_id:'request',revision:'r1',...change});
  await assert.rejects(f.ui.step('chat'),/задач|контекст|сохраняем/);assert.deepEqual(f.effects,[]);
 }
});

test('an existing allocated job cannot disappear into a no-job queue wait or be generated again',async()=>{
 const f=fixture();await f.ui.step('chat');
 f.set({ok:true,pending_research:true,research_state:'waiting_turn',research_job_id:'',request_id:'request',revision:'r1'});
 await assert.rejects(f.ui.step('chat'),/очередь задачи/);
 assert.deepEqual(f.effects,['research_status']);
});

test('running review shows the actual stage and elapsed time without authorizing actions',async()=>{
 const f=fixture();f.set({ok:true,pending_research:true,research_state:'running',research_job_id:'job',request_id:'request',revision:'r1',progress:{stage:'reviewing',elapsed_seconds:95}});
 const result=await f.ui.step('chat');assert.match(result.reason,/Проверяет ответ/);assert.match(result.reason,/1:35/);
 assert.equal(result.needs_operator,false);assert.deepEqual(f.effects,[]);
});

test('raw received stage never says the reply is approved or sent',async()=>{
 const f=fixture();f.set({ok:true,pending_research:true,research_state:'running',research_job_id:'job',request_id:'request',revision:'r1',progress:{stage:'validating',elapsed_seconds:112}});
 const result=await f.ui.step('chat');assert.match(result.reason,/результат/);assert.doesNotMatch(result.reason,/одобрен|отправлен/);
 assert.equal(result.step,'wait');assert.deepEqual(f.effects,[]);
});

test('unknown stage and invalid duration cannot inject a claim, text or fake progress',async()=>{
 const f=fixture();f.set({ok:true,pending_research:true,research_state:'running',research_job_id:'job',request_id:'request',revision:'r1',progress:{stage:'<script>approved</script>',elapsed_seconds:-1}});
 const result=await f.ui.step('chat');assert.doesNotMatch(result.reason,/script|approved|-1|0:00/);assert.deepEqual(f.effects,[]);
});

function client(){
 const calls=[];let visible=true;
 const ui=personal.create({getIdentity:async()=>({id:'george',full_name:'Георгий'}),visible:()=>visible,
  send:async({args})=>{calls.push(args);return{ok:true,active:args.action!=='personal_stop',lease_seconds:45,mode_epoch:1}}});
 return {ui,calls,hide:()=>{visible=false}};
}
test('owner disconnect and panel visibility stop have different reported origins',async()=>{
 const a=client();await a.ui.start();await a.ui.stop();assert.equal(a.calls.at(-1).stop_reason,'user_disconnect');
 const b=client();await b.ui.start();b.hide();await b.ui.heartbeat();assert.equal(b.calls.at(-1).stop_reason,'panel_not_visible');
 assert.equal(b.ui.state.active,false);
});

test('unsupported stop origin is never forwarded as arbitrary private text',async()=>{
 const f=client();await f.ui.start();await f.ui.stop('arbitrary-secret-value');assert.equal(f.calls.at(-1).stop_reason,'unreported');
 assert.ok(!JSON.stringify(f.calls).includes('arbitrary-secret-value'));
});
