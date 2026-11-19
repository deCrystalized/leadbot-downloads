'use strict';
// The actual browser controllers run here. Only authority/network/storage are
// isolated doubles: no real customer, CRM, model, Telegram or Chrome transport.
const test=require('node:test'),assert=require('node:assert/strict');
const Workflow=require('../ext/workflow'),Runner=require('../ext/assistant-runner'),Native=require('../ext/assistant-native'),Intake=require('../ext/intake');
const flush=()=>new Promise(r=>setImmediate(r));
function harness(names=['first','second']){
 const contexts=new Map(names.map(id=>[id,{convId:id,clientName:'Синтетический клиент',assigneeId:'',conversationStatus:'new',crmRequestId:'',revision:id+'-client-1',stage:'reply',messages:[{id:id+'-client-1',direction:'in',sender_type:'client',body:'Нужно собрать шкаф'}]}]));
 const records=new Map(),storage=new Map(),locks=new Map(),calls=[],timers=new Map();let timerId=0,active=true,auto=false,nextCrm=9000000;
 const fields=['город','вид работ','вид услуг','тип','партнёр','дата','время','комментарий партнёра','комментарий','служебный комментарий','имя / аккаунт объявления','телефон','имя клиента'];
 const native=Native.create({operator:()=> 'actor',
  get:async path=>{const id=decodeURIComponent(path.split('/dialogs/')[1]||'');const job=records.get(id);if(!job)throw Object.assign(Error('Not enrolled'),{status:404});return structuredClone(job)},
  post:async(path,body)=>{const tail=path.split('/dialogs/')[1],id=decodeURIComponent(tail.split('/')[0]),kind=tail.split('/')[1],ctx=contexts.get(id);
   assert.equal(body.operator_id,'actor');
   if(kind==='claim'){assert.equal(ctx.assigneeId,'');calls.push([id,'claim']);ctx.assigneeId='actor';ctx.revision=id+'-claimed';const job={id,operator_id:'actor',state:'waiting',version:1};records.set(id,job);return structuredClone(job)}
   const job=records.get(id);assert.equal(body.version,job.version);
   if(kind==='messages'){assert.equal(body.expected_last_message_id,ctx.messages.at(-1).id);calls.push([id,'reply']);const message={id:id+'-reply',direction:'out',sender_type:'operator',delivery_status:'delivered',body:body.text,client_message_id:body.client_message_id};ctx.messages.push(message);ctx.revision=id+'-reply';ctx.stage='wait';job.version++;return message}
   if(kind==='complete'){assert.equal(body.telegram_confirmed,true);assert.ok(calls.some(([chat,action])=>chat===id&&action==='telegram'));calls.push([id,'close']);ctx.crmRequestId=body.crm_request_id;ctx.conversationStatus='closed';ctx.revision=id+'-closed';job.state='completed';job.version++;return structuredClone(job)}
   assert.fail('Unexpected native transport '+kind)
  }});
 const deps={visible:()=>active,snapshot:async id=>({ctx:structuredClone(contexts.get(id)),operatorId:'actor',active,mineCount:0}),
  plan:async s=>({ok:true,operator_id:'actor',auto_session_enabled:auto,mode_epoch:1,revision:s.ctx.revision,message_revision:s.ctx.revision,
   policy_version:'synthetic-policy',eligible:s.ctx.conversationStatus!=='closed',scope:s.ctx.assigneeId?'mine':'free',
   step:s.ctx.assigneeId?s.ctx.stage:'claim',operation_id:s.ctx.revision+':'+s.ctx.stage,crm_required_fields:[]}),
  intakeGuard:ctx=>Intake.inspect(ctx),replyIssue:Intake.replyIssue,
  preview:async s=>({ok:true,reply:'Здравствуйте! Схема сборки есть?',draft_id:s.ctx.convId+'-draft',needs_operator:false}),
  validate:async s=>({ok:true,reply:'Здравствуйте! Схема сборки есть?',revision:s.ctx.revision}),
  authorize:async(s,o)=>({ok:auto,auto_enabled:auto,execution_allowed:auto,mode_epoch:1,operator_id:'actor',revision:o.revision,kind:o.kind,permit:'synthetic-only',expires_at:Date.now()+10000}),
  lock:async(key,fn)=>{const task=(locks.get(key)||Promise.resolve()).then(fn);locks.set(key,task.catch(()=>{}));return task},
  read:async key=>storage.get(key),save:async(key,value)=>storage.set(key,structuredClone(value)),
  pending:async(op,id)=>[...storage].filter(([key,v])=>key.startsWith('workflow:'+op+':'+id+':')&&v.state!=='done').map(([key,v])=>({...v,key})),
  claim:async s=>native.claim(s.ctx.convId),
  sendReply:async(s,text,clientId)=>{const message=await native.reply(s.ctx.convId,text,clientId,s.ctx.messages.at(-1).id);return{confirmed:true,result:{id:message.id}}},
  prepareCRM:async()=>({synthetic:true}),checkCRM:async()=>({ok:true,ready:true,snapshot_hash:'synthetic-snapshot'}),
  createCRM:async(_proposal,s)=>{calls.push([s.ctx.convId,'create']);return{ok:true,id:String(++nextCrm),verified:{fields,diffs:[]},warnings:[],workflow:{followup:{required:true}}}},
  notifyCreated:async(s,r)=>{calls.push([s.ctx.convId,'telegram']);return{confirmed:true,result:{id:r.id,telegram_confirmed:true}}},
  linkCRM:async(s,r)=>{await native.complete(s.ctx.convId,r.id,r.service_notification);return{confirmed:true,result:{id:r.id}}},
  reconcile:async()=>({confirmed:false}),finishOnLinked:true,notifyBeforeFinish:true};
 let workflow=Workflow.create(deps);
 const runnerDeps={visible:()=>active,active:()=>active,setMode:async mode=>{auto=mode==='auto';return{ok:true,auto_enabled:auto}},
  stopWorkflow:()=>workflow.stop(),scan:async(_ids,onReady)=>{const rows=[...contexts].map(([id])=>({id,eligible:true,name:id}));for(const row of rows)onReady?.(row);return rows},
  step:id=>workflow.step(id),inspect:id=>workflow.inspect(id),schedule:(fn,delay)=>{timers.set(++timerId,{fn,delay});return timerId},clear:id=>timers.delete(id)};
 let runner=Runner.create(runnerDeps);
 return {contexts,calls,deps,get runner(){return runner},async start(){await runner.start('auto')},
  nextClient(id){const ctx=contexts.get(id);ctx.stage='prepare_crm';ctx.revision=id+'-ready';ctx.messages.push({id:ctx.revision,direction:'in',sender_type:'client',body:'Да, схема есть. Остальные данные подтверждаю.'})},
  restart(){runner.stop();workflow=Workflow.create(deps);runner=Runner.create(runnerDeps)},stop(){runner.stop();active=false},setAuto:value=>auto=value};
}

test('complete isolated auto manages several contexts, replies once, creates verifies posts and closes once',async()=>{
 const f=harness();try{await f.start();assert.deepEqual(f.calls.map(x=>x.join(':')).sort(),['first:claim','first:reply','second:claim','second:reply']);
  await f.runner.tick();assert.equal(f.calls.length,4);
  f.nextClient('first');f.nextClient('second');await f.runner.tick();
  for(const id of ['first','second'])assert.deepEqual(f.calls.filter(x=>x[0]===id).map(x=>x[1]),['claim','reply','create','telegram','close']);
  await f.runner.tick();assert.equal(f.calls.length,10);assert.equal(f.contexts.get('first').conversationStatus,'closed');
 }finally{f.stop()}
});

test('unknown Telegram outcome never reposts, recreates or closes after restart',async()=>{
 const f=harness(['first']);try{await f.start();f.nextClient('first');f.deps.notifyCreated=async()=>{f.calls.push(['first','telegram']);throw Error('Synthetic missing acknowledgement')};
  await f.runner.tick();assert.equal(f.runner.state.rows[0].step,'handoff');f.restart();await f.start();
  assert.deepEqual(f.calls.map(x=>x[1]),['claim','reply','create','telegram']);assert.notEqual(f.contexts.get('first').conversationStatus,'closed');
 }finally{f.stop()}
});

test('unknown CRM result retains permanent once slot across new message and restart',async()=>{
 const f=harness(['first']);try{await f.start();f.nextClient('first');f.deps.createCRM=async()=>{f.calls.push(['first','create']);throw Error('Synthetic lost response after create')};
  await f.runner.tick();f.contexts.get('first').revision+='-another-message';f.restart();await f.start();
  assert.deepEqual(f.calls.map(x=>x[1]),['claim','reply','create']);assert.equal(f.runner.state.rows[0].step,'handoff');
 }finally{f.stop()}
});

test('existing Waiting order and system-only events cannot enter model or any transport',async()=>{
 const f=harness(['existing','system']);f.contexts.get('existing').clientName='Синтетический клиент 1091862';
 f.contexts.get('existing').messages=[{id:'late-question',direction:'in',sender_type:'client',body:'Вы приедете?'}];
 f.contexts.get('system').messages=[{id:'service',direction:'in',sender_type:'system',body:'Диалог назначен'}];
 f.deps.preview=()=>assert.fail('A guarded case reached the model');try{await f.start();assert.deepEqual(f.calls,[]);assert.ok(f.runner.state.rows.every(r=>r.step==='skip'||r.step==='wait'))}finally{f.stop()}
});

test('stop while model is pending fences the late answer without another send',async()=>{
 const f=harness(['first']);let release;f.deps.preview=()=>new Promise(resolve=>release=resolve);
 const run=f.start();await flush();assert.deepEqual(f.calls.map(x=>x[1]),['claim']);f.runner.stop();
 release({ok:true,reply:'Поздний ответ',draft_id:'late'});await run;
 assert.deepEqual(f.calls.map(x=>x[1]),['claim']);f.stop();
});

test('server mode revocation immediately before transport cancels that exact action',async()=>{
 const f=harness(['first']);const authorize=f.deps.authorize;
 f.deps.authorize=async(s,o)=>{const receipt=await authorize(s,o);f.setAuto(false);return receipt};
 try{await f.start();assert.deepEqual(f.calls,[]);
  assert.equal(f.runner.state.mode,'stopped');assert.match(f.runner.state.error,/изменились/);
  assert.equal(f.runner.state.rows.some(r=>r.needs_operator||r.step==='handoff'),false);
  await f.runner.tick();assert.deepEqual(f.calls,[]);assert.equal(f.runner.state.mode,'stopped');
 }finally{f.stop()}
});
