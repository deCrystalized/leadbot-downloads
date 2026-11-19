'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {create}=require('../ext/workflow');
const {readHistory}=require('../ext/workflow');
const intake219=require('../ext/intake');
function fixture(overrides={}) {
  const db=new Map(),calls=[],locks=new Map();
  let ctx={convId:'chat',assigneeId:'',conversationStatus:'in_progress',crmRequestId:'',stage:'reply',revision:'r1'},active=true,operator='george';
  const deps={
    snapshot:async()=>({ctx:{...ctx},operatorId:operator,active,mineCount:0}),visible:()=>true,
    plan:async s=>({ok:true,operator_id:'george',auto_session_enabled:true,mode_epoch:1,revision:s.ctx.revision,operation_id:s.ctx.revision+':'+s.ctx.stage,eligible:s.ctx.assigneeId!=='colleague',crm_required_fields:['улица','дом','квартира','отзыв','звонок перед выездом'],scope:s.ctx.assigneeId?'mine':'free',step:s.ctx.assigneeId?s.ctx.stage:'claim'}),
    preview:async()=>({ok:true,reply:'Марку и модель подскажите?',draft_id:'draft',needs_operator:false}),
    validate:async s=>({ok:true,reply:'Марку и модель подскажите?',revision:s.ctx.revision}),
    // Isolated authority double. Production Python always returns auto_disabled.
    authorize:async(s,o)=>({ok:true,auto_enabled:true,execution_allowed:true,mode_epoch:1,operator_id:s.operatorId,revision:o.revision,kind:o.kind,permit:'test-only',expires_at:Date.now()+10000}),
    lock:async(k,fn)=>{const p=(locks.get(k)||Promise.resolve()).then(fn);locks.set(k,p.catch(()=>{}));return p},
    read:async k=>db.get(k),save:async(k,v)=>{db.set(k,structuredClone(v))},
    pending:async(op,id)=>[...db].filter(([k,v])=>k.startsWith('workflow:'+op+':'+id+':')&&v.state!=='done').map(([key,v])=>({...v,key})),
    claim:async()=>{calls.push('claim');ctx.assigneeId='george';ctx.revision='r2';return{ok:true}},
    sendReply:async(s,text,key)=>{calls.push('reply');assert.match(key,/^lcp:/);ctx.stage='wait';ctx.revision='r3';return{confirmed:true,result:{id:'m2'}}},
    prepareCRM:async()=>({lead:{phone:'synthetic'},revision:ctx.revision}),
    checkCRM:async()=>({ok:true,ready:true,snapshot_hash:'snapshot'}),
    createCRM:async()=>{calls.push('create');return{ok:true,id:'1234567',verified:{checked:11,fields:['город','вид работ','вид услуг','тип','партнёр','дата','время','комментарий партнёра','комментарий','служебный комментарий','имя / аккаунт объявления','телефон','имя клиента','улица','дом','квартира','отзыв','звонок перед выездом'],diffs:[]},warnings:[]}},
    linkCRM:async(s,r)=>{calls.push('link');ctx.crmRequestId=r.id;ctx.revision='r5';return{confirmed:true,result:{id:r.id}}},
    renameClient:async(s,r)=>{calls.push('rename');return{confirmed:true,result:{id:r.id}}},
    notifyCreated:async(s,r)=>{calls.push('notify');return{confirmed:true,result:{id:r.id}}},
    reconcile:async()=>({confirmed:false}),...overrides
  };
  return {ui:create(deps),deps,db,calls,ctx,setActive:v=>active=v,setOperator:v=>operator=v};
}
test('existing order label prevents claim, preview and every write despite an otherwise eligible plan',async()=>{
 const f=fixture({intakeGuard:ctx=>intake219.inspect(ctx)});f.ctx.clientName='Наталья1091862';f.ctx.messages=[{direction:'in',sender_type:'client',body:'Вы приедете?'}];
 assert.equal((await f.ui.step('chat')).step,'skip');assert.deepEqual(f.calls,[]);assert.equal(f.ctx.crmRequestId,'');
});
test('photo promise and system-only update return wait without preview or operator escalation',async()=>{
 const f=fixture({intakeGuard:ctx=>intake219.inspect(ctx),preview:()=>assert.fail('No model needed')});f.ctx.assigneeId='george';
 f.ctx.messages=[{direction:'out',sender_type:'operator',delivery_status:'delivered',body:'Схема сборки есть?'},{direction:'in',sender_type:'client',body:'Да, картинку скину сейчас'}];
 assert.equal((await f.ui.step('chat')).step,'wait');assert.deepEqual(f.calls,[]);
 f.ctx.messages.push({direction:'out',sender_type:'operator',body:'Хорошо',delivery_status:'delivered'},{direction:'in',sender_type:'system',body:'Статус изменён'});
 assert.equal((await f.ui.step('chat')).step,'wait');assert.deepEqual(f.calls,[]);
});
test('model paraphrase of a previously delivered instructions question cannot be sent',async()=>{
 const f=fixture({replyIssue:intake219.replyIssue,preview:async()=>({ok:true,reply:'У вас есть инструкция по сборке?',draft_id:'draft'})});f.ctx.assigneeId='george';
 f.ctx.messages=[{direction:'out',sender_type:'operator',body:'Схема или инструкция сборки есть?',delivery_status:'delivered'},{direction:'in',sender_type:'client',body:'Да, есть'}];
 assert.equal((await f.ui.step('chat')).step,'handoff');assert.deepEqual(f.calls,[]);
});
test('complete multi-turn chain: claim, validated reply, wait, CRM create, verify and link once',async()=>{
 const f=fixture();assert.equal((await f.ui.step('chat')).step,'wait');assert.deepEqual(f.calls,['claim','reply']);
 await f.ui.step('chat');assert.equal(f.calls.length,2);
 f.ctx.stage='prepare_crm';f.ctx.revision='r4';assert.equal((await f.ui.step('chat')).step,'done');
 await f.ui.step('chat');assert.deepEqual(f.calls,['claim','reply','create','link','rename','notify']);
});
test('owner intake ends after the confirmed order link without rename notify or another reply',async()=>{
 const f=fixture({finishOnLinked:true});f.ctx.assigneeId='george';f.ctx.stage='prepare_crm';
 assert.equal((await f.ui.step('chat')).step,'done');
 assert.deepEqual(f.calls,['create','link']);
 assert.equal(f.ctx.crmRequestId,'1234567');
});
test('production disabled authority prevents even the first claim',async()=>{
 const f=fixture({authorize:async()=>({ok:false,code:'auto_disabled',error:'Автоматический режим выключен'})});await assert.rejects(f.ui.step('chat'),/выключен/);assert.deepEqual(f.calls,[]);
});
test('read-only inspection never invokes a write, even with a permissive authority double',async()=>{
 const f=fixture();assert.equal((await f.ui.inspect('chat')).step,'claim');f.ctx.assigneeId='george';assert.match((await f.ui.inspect('chat')).reply,/модель/);f.ctx.stage='prepare_crm';assert.equal((await f.ui.inspect('chat')).crm.ready,true);assert.deepEqual(f.calls,[]);
});
test('a colleague, closed gate or full queue cannot be claimed',async()=>{
 const f=fixture({plan:async()=>({ok:true,operator_id:'george',revision:'r1',eligible:false,step:'handoff',reason:'Согласование'})});await f.ui.step('chat');assert.deepEqual(f.calls,[]);
});
test('different operator and expired lease both fail before transport',async()=>{
 const f=fixture();f.setOperator('colleague');await assert.rejects(f.ui.step('chat'),/Владелец/);f.setOperator('george');f.setActive(false);await assert.rejects(f.ui.step('chat'),/сессия/);assert.deepEqual(f.calls,[]);
});
test('stop while preview is running fences the late answer',async()=>{
 let resolve;const f=fixture({preview:async()=>new Promise(r=>resolve=r)});f.ctx.assigneeId='george';const run=f.ui.step('chat');await new Promise(r=>setImmediate(r));f.ui.stop();resolve({ok:true,reply:'Тест',draft_id:'d'});await assert.rejects(run,/остановлена/);assert.deepEqual(f.calls,[]);
});
test('manual takeover/new message while wording is prepared invalidates it',async()=>{
 const f=fixture();f.ctx.assigneeId='george';f.deps.preview=async()=>{f.ctx.revision='new';return{ok:true,reply:'Тест',draft_id:'d'}};await assert.rejects(f.ui.step('chat'),/устарел/);assert.deepEqual(f.calls,[]);
});
test('manual pause after permission but before transport blocks the same message revision',async()=>{const f=fixture();const auth=f.deps.authorize;f.deps.authorize=async(s,o)=>{const r=await auth(s,o);f.deps.plan=async()=>({ok:true,operator_id:'george',revision:'r1',code:'paused',eligible:false,step:'handoff'});return r};await assert.rejects(f.ui.step('chat'),/изменились/);assert.deepEqual(f.calls,[])});
test('server mode revocation after permission fences transport without a message change',async()=>{const f=fixture();const auth=f.deps.authorize,plan=f.deps.plan;f.deps.authorize=async(s,o)=>{const r=await auth(s,o);f.deps.plan=async s=>({...await plan(s),auto_session_enabled:false,mode_epoch:2});return r};await assert.rejects(f.ui.step('chat'),/изменились/);assert.deepEqual(f.calls,[])});
test('draft validation rejection and mutation are never sent',async()=>{
 for(const valid of [{ok:false,error:'stale'},{ok:true,reply:'Другой текст',revision:'r1'}]){const f=fixture({validate:async()=>valid});f.ctx.assigneeId='george';await assert.rejects(f.ui.step('chat'));assert.deepEqual(f.calls,[])}
});
test('model handoff never becomes a customer reply',async()=>{
 const f=fixture({preview:async()=>({ok:true,reply:'Ответ',needs_operator:true})});f.ctx.assigneeId='george';assert.equal((await f.ui.step('chat')).step,'handoff');assert.deepEqual(f.calls,[]);
});
test('storage failure occurs before any external write',async()=>{
 const f=fixture({save:async()=>{throw Error('storage')}});await assert.rejects(f.ui.step('chat'),/storage/);assert.deepEqual(f.calls,[]);
});
test('claim race cannot send a reply under another employee',async()=>{
 const f=fixture();f.deps.claim=async()=>{f.calls.push('claim');f.ctx.assigneeId='colleague';return{ok:true}};await assert.rejects(f.ui.step('chat'),/не подтверждён/);assert.deepEqual(f.calls,['claim']);
});
test('unknown message delivery survives restart and blocks a changed revision',async()=>{
 const f=fixture({sendReply:async()=>{throw Error('network')}});f.ctx.assigneeId='george';await assert.rejects(f.ui.step('chat'),/мог выполниться/);f.ctx.revision='new';
 const restarted=create(f.deps);await assert.rejects(restarted.step('chat'),/Предыдущее/);assert.deepEqual(f.calls,[]);
});
test('positive message reconciliation allows progression without a second send',async()=>{
 let sent=0;const f=fixture({sendReply:async()=>{sent++;throw Error('network')},reconcile:async()=>({confirmed:true,result:{id:'delivered'}})});f.ctx.assigneeId='george';await assert.rejects(f.ui.step('chat'));await f.ui.step('chat');assert.equal(sent,1);
});
test('two concurrent cycles cannot create twice',async()=>{
 const f=fixture();f.ctx.assigneeId='george';f.ctx.stage='prepare_crm';await Promise.all([f.ui.step('chat'),f.ui.step('chat')]);assert.equal(f.calls.filter(x=>x==='create').length,1);
});
test('different dialogs queue CRM creation before authorization while replies can use separate workers',async()=>{const locks=new Map();const lock=async(k,fn)=>{const run=(locks.get(k)||Promise.resolve()).then(fn);locks.set(k,run.catch(()=>{}));return run};let active=0,max=0;const a=fixture({lock}),b=fixture({lock});for(const [f,id] of [[a,'a'],[b,'b']]){f.ctx.convId=id;f.ctx.assigneeId='george';f.ctx.stage='prepare_crm';const createCRM=f.deps.createCRM;f.deps.createCRM=async()=>{max=Math.max(max,++active);await new Promise(r=>setImmediate(r));const r=await createCRM();active--;return r}}await Promise.all([a.ui.step('a'),b.ui.step('b')]);assert.equal(max,1);assert.equal(a.calls.filter(x=>x==='create').length,1);assert.equal(b.calls.filter(x=>x==='create').length,1)});
test('missing call or ambiguous CRM fields stop before creation',async()=>{
 const f=fixture({checkCRM:async()=>({ok:true,ready:false,reasons:['Нужен звонок']})});f.ctx.assigneeId='george';f.ctx.stage='prepare_crm';assert.deepEqual((await f.ui.step('chat')).reasons,['Нужен звонок']);assert.deepEqual(f.calls,[]);
});
test('unknown CRM outcome is permanent across revision/restart',async()=>{
 let count=0;const f=fixture({createCRM:async()=>{count++;throw Error('lost reply')}});f.ctx.assigneeId='george';f.ctx.stage='prepare_crm';await assert.rejects(f.ui.step('chat'));f.ctx.revision='new';await assert.rejects(create(f.deps).step('chat'));assert.equal(count,1);
});
test('known CRM ID with mismatched fields is created_review, never another create',async()=>{
 const f=fixture({createCRM:async()=>({ok:true,id:'1234567',verified:{checked:8,diffs:['адрес']}})});f.ctx.assigneeId='george';f.ctx.stage='prepare_crm';assert.equal((await f.ui.step('chat')).step,'created_review');assert.equal((await f.ui.step('chat')).step,'created_review');assert.deepEqual(f.calls,[]);
});
test('link failure after successful CRM creation never creates again',async()=>{
 let n=0;const f=fixture({linkCRM:async()=>{n++;throw Error('link network')}});f.ctx.assigneeId='george';f.ctx.stage='prepare_crm';await assert.rejects(f.ui.step('chat'));await assert.rejects(f.ui.step('chat'));assert.equal(f.calls.filter(x=>x==='create').length,1);assert.equal(n,1);
});
test('stale or mismatched permit cannot authorize a customer write',async()=>{
 for(const change of [{auto_enabled:false},{expires_at:0},{operator_id:'other'},{revision:'old'},{kind:'create_crm'},{permit:''}]){const f=fixture();const auth=f.deps.authorize;f.deps.authorize=async(s,o)=>({...await auth(s,o),...change});await assert.rejects(f.ui.step('chat'));assert.deepEqual(f.calls,[])}
});
test('batch is bounded, unique and records a handoff without aborting other reviews',async()=>{
 const f=fixture({authorize:async()=>({ok:false,error:'off'})});const r=await f.ui.cycle(Array.from({length:30},(_,i)=>'chat'+i));assert.equal(r.length,12);assert.ok(r.every(x=>x.step==='handoff'));assert.deepEqual(f.calls,[]);
});
test('pagination reads all previous messages once and preserves the latest version of duplicates',async()=>{
 const pages={older:{items:[{id:'a',created_at:'2026-10-01',body:'first'},{id:'b',created_at:'2026-10-02',body:'old'}],page:{has_more_before:false}}};
 const rows=await readHistory({items:[{id:'b',created_at:'2026-10-02',body:'new'},{id:'c',created_at:'2026-10-03'}],page:{has_more_before:true,prev_cursor:'older'}},async c=>pages[c]);assert.deepEqual(rows.map(m=>m.id),['a','b','c']);assert.equal(rows[1].body,'new');
});
test('unknown pagination, repeated cursor, missing message IDs or excess history are never silently truncated',async()=>{
 for(const first of [{items:[],page:{}},{items:[{}],page:{has_more_before:false}},{items:[],page:{has_more_before:true}}])await assert.rejects(readHistory(first,async()=>first));
 const loop={items:[{id:'a'}],page:{has_more_before:true,prev_cursor:'same'}};await assert.rejects(readHistory(loop,async()=>loop));
 const rows=Array.from({length:301},(_,i)=>({id:String(i)}));await assert.rejects(readHistory({items:rows,page:{has_more_before:false}},async()=>null),/300/);
});
test('a journal failure blocks transport before claiming a conversation',async()=>{
 const f=fixture({audit:async()=>({ok:false,error:'journal unavailable'})});await assert.rejects(f.ui.step('chat'),/journal/);assert.deepEqual(f.calls,[]);
});
test('permit expiry while persisting the start event stops before transport',async()=>{
 let expiry=Date.now()+10000;
 const f=fixture({audit:async(s,event)=>{if(event.kind==='transport_started')expiry=0;return{ok:true}},authorize:async(s,o)=>({ok:true,auto_enabled:true,execution_allowed:true,mode_epoch:1,operator_id:s.operatorId,revision:o.revision,kind:o.kind,permit:'isolated',get expires_at(){return expiry}})});
 await assert.rejects(f.ui.step('chat'),/истекло/);assert.deepEqual(f.calls,[]);
});
test('unknown service notification never repeats CRM creation or renaming',async()=>{
 let n=0;const f=fixture({notifyCreated:async()=>{n++;throw Error('telegram timeout')}});f.ctx.assigneeId='george';f.ctx.stage='prepare_crm';await assert.rejects(f.ui.step('chat'));await assert.rejects(f.ui.step('chat'));assert.equal(n,1);assert.equal(f.calls.filter(c=>c==='create').length,1);assert.equal(f.calls.filter(c=>c==='rename').length,1);
});
function reviewedFixture(){
 const f=fixture(),plan=f.deps.plan;
 f.deps.plan=async s=>({...await plan(s),auto_session_enabled:false,message_revision:'same-messages',policy_version:'policy'});
 f.deps.reviewAuthorize=async(s,o)=>({ok:true,auto_enabled:false,reviewed:true,execution_allowed:true,mode_epoch:1,operator_id:s.operatorId,revision:o.revision,kind:o.kind,permit:'reviewed-once',expires_at:Date.now()+10000});
 return f;
}
test('reviewed claim and reply need separate approvals and never start a loop',async()=>{
 const f=reviewedFixture(),claim=await f.ui.inspect('chat');
 await f.ui.reviewOne('chat',claim,{confirmed:true});assert.deepEqual(f.calls,['claim']);
 await assert.rejects(f.ui.reviewOne('chat',claim,{confirmed:true}),/изменился/);
 const reply=await f.ui.inspect('chat');await f.ui.reviewOne('chat',reply,{confirmed:true});assert.deepEqual(f.calls,['claim','reply']);
});
test('reviewed reply cannot silently change wording or approve a different revision',async()=>{
 for(const change of [{reply:'Другой ответ'},{revision:'old'},{mode_epoch:2},{step:'claim'}]){const f=reviewedFixture();f.ctx.assigneeId='george';const view=await f.ui.inspect('chat');await assert.rejects(f.ui.reviewOne('chat',{...view,...change},{confirmed:true}));assert.deepEqual(f.calls,[])}
});
test('reviewed CRM and every followup execute one operation per approval',async()=>{
 const f=reviewedFixture();f.ctx.assigneeId='george';f.ctx.stage='prepare_crm';
 for(const [i,expected] of ['create','link','rename','notify'].entries()){
  const view=await f.ui.inspect('chat');await f.ui.reviewOne('chat',view,{confirmed:true});
  assert.equal(f.calls.length,i+1);assert.equal(f.calls[i],expected);
 }
 assert.equal((await f.ui.inspect('chat')).step,'done');
});
test('single-action approval cannot reuse an auto permit or ignore revocation',async()=>{
 for(const bad of [{reviewed:false,auto_enabled:true},{mode_epoch:2},{expires_at:0}]){
  const f=reviewedFixture();const auth=f.deps.reviewAuthorize;f.deps.reviewAuthorize=async(s,o)=>({...await auth(s,o),...bad});
  await assert.rejects(f.ui.reviewOne('chat',await f.ui.inspect('chat'),{confirmed:true}));assert.deepEqual(f.calls,[]);
 }
 const f=reviewedFixture(),auth=f.deps.reviewAuthorize;f.deps.reviewAuthorize=async(s,o)=>{const r=await auth(s,o);f.ui.stop();return r};await assert.rejects(f.ui.reviewOne('chat',await f.ui.inspect('chat'),{confirmed:true}));assert.deepEqual(f.calls,[]);
});
test('independent conversations execute concurrently while each conversation remains locked',async()=>{
 const locks=new Map();let running=0,max=0;const fs=[];
 const lock=(k,fn)=>{const p=(locks.get(k)||Promise.resolve()).then(fn);locks.set(k,p.catch(()=>{}));return p};
 for(let i=0;i<4;i++){const f=fixture({lock});f.ctx.convId='parallel-'+i;f.ctx.assigneeId='george';f.deps.sendReply=async()=>{max=Math.max(max,++running);await new Promise(r=>setTimeout(r,15));running--;return{confirmed:true,result:{id:'reply'}}};fs.push(f)}
 await Promise.all(fs.map(f=>f.ui.step(f.ctx.convId)));assert.equal(max,4);
});
test('real asynchronous send waits for the same pending message without posting again',async()=>{
 const {waitForDelivery}=require('../ext/workflow');let reads=0,clock=0;
 const initial={id:'m',client_message_id:'approved',direction:'out',delivery_status:'pending'};
 const r=await waitForDelivery({clientId:'approved',initial,now:()=>clock,wait:async ms=>{clock+=ms},read:async()=>({items:[{...initial,delivery_status:++reads<3?'pending':'delivered'}]})});
 assert.equal(r.confirmed,true);assert.equal(r.result.id,'m');assert.equal(reads,3);
});
test('failed, timed-out or unrelated delivery cannot confirm an approved reply',async()=>{
 const {waitForDelivery}=require('../ext/workflow'),initial={id:'m',client_message_id:'approved',direction:'out',delivery_status:'pending'};
 let clock=0;const timeout=await waitForDelivery({clientId:'approved',initial,timeoutMs:1000,now:()=>clock,wait:async ms=>{clock+=ms},read:async()=>({items:[{...initial,id:'other',delivery_status:'delivered'}]})});assert.equal(timeout.confirmed,false);assert.equal(timeout.result.id,'m');assert.equal(clock,1000);
 const failed=await waitForDelivery({clientId:'approved',initial,read:async()=>({items:[{...initial,delivery_status:'failed'}]})});assert.equal(failed.confirmed,false);assert.equal(failed.result.delivery_status,'failed');
 const wrong=await waitForDelivery({clientId:'other-key',initial,read:async()=>{throw Error('must not read')}});assert.equal(wrong.confirmed,false);
});

test('missing apartment verification stops after the known CRM ID and survives restart without duplicate creation',async()=>{
 const f=fixture();const original=f.deps.createCRM;
 f.deps.createCRM=async()=>{const r=await original();r.verified.fields=r.verified.fields.filter(x=>x!=='квартира');return r};
 f.ctx.assigneeId='george';f.ctx.stage='prepare_crm';
 assert.equal((await f.ui.step('chat')).step,'created_review');
 assert.deepEqual(f.calls,['create']);
 f.deps.plan=async s=>({ok:true,operator_id:'george',revision:s.ctx.revision,eligible:false,step:'handoff'});
 assert.equal((await create(f.deps).step('chat')).step,'created_review');
 assert.deepEqual(f.calls,['create']);
});

test('primary intake posts only service Telegram before native close, without rename or client reply',async()=>{
 const f=fixture({finishOnLinked:true,notifyBeforeFinish:true});f.ctx.assigneeId='george';f.ctx.stage='prepare_crm';
 const create=f.deps.createCRM;f.deps.createCRM=async()=>{const r=await create();r.workflow={followup:{required:true}};return r};
 f.deps.notifyCreated=async(s,r)=>{f.calls.push('notify');return {confirmed:true,result:{id:r.id,telegram_confirmed:true}}};
 f.deps.linkCRM=async(s,r)=>{assert.equal(r.service_notification.telegram_confirmed,true);f.calls.push('close');f.ctx.crmRequestId=r.id;f.ctx.conversationStatus='closed';return {confirmed:true,result:{id:r.id}}};
 const result=await f.ui.step('chat');assert.equal(result.step,'done');assert.equal(result.telegram_confirmed,true);assert.deepEqual(f.calls,['create','notify','close']);
});
test('unknown Telegram post stops before close and cannot repost or recreate after restart',async()=>{
 const f=fixture({finishOnLinked:true,notifyBeforeFinish:true});f.ctx.assigneeId='george';f.ctx.stage='prepare_crm';
 const create=f.deps.createCRM;f.deps.createCRM=async()=>{const r=await create();r.workflow={followup:{required:true}};return r};
 f.deps.notifyCreated=async()=>{f.calls.push('notify');return {confirmed:false}};
 await assert.rejects(f.ui.step('chat'),/не подтверждён/);assert.deepEqual(f.calls,['create','notify']);
 await assert.rejects(require('../ext/workflow').create(f.deps).step('chat'),/Предыдущее/);assert.deepEqual(f.calls,['create','notify']);
});
test('an acknowledgement for another CRM ID never permits close',async()=>{
 const f=fixture({finishOnLinked:true,notifyBeforeFinish:true});f.ctx.assigneeId='george';f.ctx.stage='prepare_crm';
 const create=f.deps.createCRM;f.deps.createCRM=async()=>{const r=await create();r.workflow={followup:{required:true}};return r};
 f.deps.notifyCreated=async()=>({confirmed:true,result:{id:'7654321',telegram_confirmed:true}});
 assert.equal((await f.ui.step('chat')).step,'created_review');assert.deepEqual(f.calls,['create']);
});
test('missing service route never silently skips notification and closes',async()=>{
 const f=fixture({finishOnLinked:true,notifyBeforeFinish:true});f.ctx.assigneeId='george';f.ctx.stage='prepare_crm';
 assert.equal((await f.ui.step('chat')).step,'created_review');assert.deepEqual(f.calls,['create']);
});
