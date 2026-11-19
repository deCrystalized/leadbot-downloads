'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {randomUUID}=require('node:crypto');
const Native=require('../ext/native-office'),Host=require('../ext/native-office-host'),CRM=require('../ext/crm');
const BASE='/bot-dialogs/assistant',PATH=BASE+'/native-office/';
const P=randomUUID(),O=randomUUID(),RUN=randomUUID(),CID=randomUUID(),LEASE=randomUUID();
const H='a'.repeat(64),SOURCE='b'.repeat(64),FORM='c'.repeat(64),SNAP='d'.repeat(64),MSGS='e'.repeat(64);
const ORIGIN='https://chat.partner-lead-centre.ru';

function coreFixture(options){
  // Reuse only the existing synthetic transport fixture, without importing
  // its tests or replacing the actual CRM create implementation.
  const code=fs.readFileSync(require.resolve('./test_crm_results234.test.js'),'utf8');
  const start=code.indexOf('function field('),end=code.indexOf("\ntest('CRM serializer");
  assert.ok(start>=0&&end>start);
  const scope={CRM,fs,vm,assert,URL,URLSearchParams,structuredClone,require};
  vm.createContext(scope);vm.runInContext(code.slice(start,end)+';this.fixture=fixture;',scope);
  return scope.fixture(options||{});
}
function setup(options={}){
  const f={now:1000000,events:[],calls:[],store:new Map(),physical:0,card:0,created:0,
    role:'admin',principal:P,pending:options.pending||0,permissions:0,execCalls:0};
  f.run={principal_id:P,operator_id:O,run_id:RUN,generation:1,state:'running',mode:'auto',
    auto_enabled:true,native_supported:true,configured:true,worker_ready:true};
  f.meta={work_id:H,cid:CID,state:'ready',source_sha256:SOURCE,snapshot_hash:null,
    deadline:f.now/1000+300,execution_allowed:false,crm_request_id:null,
    telegram_confirmed:false,dialog_closed:false};
  f.scope={principal_id:P,operator_id:O,run_id:RUN,generation:1};
  f.sender={id:'synthetic-office-extension',frameId:0,documentId:randomUUID(),
    tab:{id:7},url:ORIGIN+'/chats/'+CID};
  f.offscreen={id:f.sender.id,url:'chrome-extension://'+f.sender.id+'/offscreen.html'};
  const storage={
    get:async key=>({[key]:structuredClone(f.store.get(key))}),
    set:async values=>{
      if(options.failStore&&Object.values(values).some(v=>v?.state===options.failStore))
        throw Error('synthetic storage unavailable');
      for(const [key,value]of Object.entries(values))f.store.set(key,structuredClone(value));
    },
  };
  let client;
  const chrome={runtime:{id:f.sender.id,getURL:p=>'chrome-extension://'+f.sender.id+'/'+p},
    storage:{local:storage},alarms:{onAlarm:{addListener:fn=>{f.alarm=fn}},
      get:async()=>({name:'lcz-native-office'}),create:async()=>{}},
    tabs:{query:async()=>[{id:7,url:f.sender.url}],sendMessage:async(id,message,where)=>{
      assert.equal(id,7);
      if(message.kind==='lcz-native-office-phase'){
        assert.equal(where.documentId,f.sender.documentId);
        if(options.phaseReply)return options.phaseReply(f,message);
        return client.phase(message);
      }
      return client.wake();
    }}};
  f.host=Host.create(chrome,[ORIGIN],{now:()=>f.now,uuid:randomUUID});
  f.chrome=chrome;
  f.core=coreFixture(options.note?{note:'Проверенный комментарий',omitPartnerField:true}:{});
  f.core.scope.Date={now:()=>f.now};
  const originalFetch=f.core.scope.fetch;
  f.core.scope.fetch=async(...args)=>{f.physical++;f.events.push('CRM_POST');return originalFetch(...args)};
  const required=['город','вид работ','вид услуг','тип','партнёр','дата','время',
    'комментарий партнёра','комментарий','служебный комментарий','имя / аккаунт объявления',
    'телефон','имя клиента'];
  f.core.scope.verifyCreated=async()=>{f.events.push('CARD_READ');
    return{checked:required.length,diffs:options.diff?['Не совпал дом']:[],fields:required}};
  const form={ok:true,auto_enabled:false,revision:'rev-original',intake_form_ready:true,
    form_reference:FORM,research_job_id:'synthetic-ready-form',policy_version:'synthetic-policy',
    routing:{direction:'mnc'},facts:{},form_extraction:{ok:true,lead:{problem:'Сборка шкафа'}}};
  f.proposal=structuredClone({revision:form.revision,form_reference:FORM,dir:'mnc',lead:f.core.params.lead,
    sel:f.core.params.sel,prep:{},territory:{},readiness:'ready',flags:[],allowLive:false,
    followup:{required:true,telegram_ready:true,code:'7'}});
  function envelope(){return{...f.meta,lease_id:LEASE,lease_until:f.now/1000+90,
    form,proposal:f.meta.snapshot_hash?structuredClone(f.proposal):null,
    required_fields:required,message_revision:MSGS}}
  const api={
    get:async path=>{assert.equal(path,BASE+'/native-run');f.calls.push(['GET',path]);return{...f.run}},
    post:async(path,body)=>{
      body=JSON.parse(JSON.stringify(body)); // Actual HTTP JSON boundary, not VM array prototypes.
      const operation=path.slice(PATH.length);
      assert.ok(path.startsWith(PATH));
      f.calls.push(['POST',operation,structuredClone(body)]);
      assert.equal(body.expected_principal_id,P);assert.equal(body.operator_id,O);
      assert.equal(body.run_id,RUN);assert.equal(body.generation,1);
      if(operation==='heartbeat')return{available:true,state:'idle',run_started:false};
      if(operation==='poll')return envelope();
      assert.equal(body.work_id,H);assert.equal(body.lease_id,LEASE);
      if(operation==='prepare'){
        assert.deepEqual(body.proposal,f.proposal);f.events.push('PREPARED');
        if(options.mutateCandidateAfterAck)f.candidate.lead.comment='Unapproved later local edit';
        f.meta.state='office_reserved';f.meta.snapshot_hash=SNAP;return{...f.meta};
      }
      if(operation==='status')return{...f.meta};
      if(operation==='request-create'){
        f.events.push('CONSUME_INTENT');f.meta.state='consume_requested';return{...f.meta};
      }
      if(operation==='issue-create'){
        f.events.push('ISSUE_ATTEMPT');
        if(f.pending-->0)return{...f.meta};
        if(f.meta.state!=='consume_requested')return{...f.meta,reconciliation_only:true};
        f.permissions++;f.meta.state='create_started';
        if(options.lose==='issue-create')throw Error('synthetic lost issue ACK');
        return{...f.meta,execution_allowed:true,kind:'create_crm',operator_id:O,
          dispatch_before:f.now/1000+10};
      }
      if(operation==='created'){
        f.created++;assert.equal(body.report.id,'1234567');
        f.events.push('ID_RECORDED');f.meta.crm_request_id=body.report.id;
        f.meta.state='created_unverified';
        if(options.lose==='created')throw Error('synthetic lost ID evidence ACK');
        return{...f.meta};
      }
      if(operation==='followup'){
        assert.equal(body.crm_request_id,'1234567');
        assert.ok(['partner_note','customer_contact'].includes(body.kind));
        assert.ok(f.events.includes('ID_RECORDED'));
        f.events.push('FOLLOWUP_'+body.kind);
        return{...f.meta,execution_allowed:true,kind:body.kind,crm_request_id:'1234567',
          dispatch_before:f.now/1000+10};
      }
      if(operation==='card'){
        f.card++;assert.equal(body.report.id,'1234567');
        assert.equal(body.report.snapshot_hash,SNAP);assert.equal(body.report.form_reference,FORM);
        assert.equal(body.report.policy_version,form.policy_version);
        assert.equal(body.report.message_revision,MSGS);
        assert.deepEqual(body.report.verified.diffs,[]);
        assert.deepEqual(body.report.warnings,[]);
        f.events.push('CARD_RECORDED');f.meta.state='waiting_notification';
        if(options.lose==='card')throw Error('synthetic lost card ACK');
        return{...f.meta,duplicate_found:false};
      }
      if(operation==='failed'){
        if(f.meta.state==='waiting_notification')return{...f.meta};
        f.meta.state='created_review';f.run.state='blocked';f.run.auto_enabled=false;f.run.generation=2;
        return{...f.meta};
      }
      throw Error('No customer/model/Telegram/start/close route');
    },
  };
  const offscreenCode=fs.readFileSync(require.resolve('../ext/offscreen.js'),'utf8');
  let offscreen;
  const off={CRM:{create:args=>f.core.scope.executeCreate(args)},
    chrome:{runtime:{id:f.sender.id,onMessage:{addListener:fn=>{offscreen=fn}},
      // Chrome runtime messaging serializes across the offscreen/content
      // realms; do not pass VM object prototypes directly to Main's client.
      sendMessage:message=>f.host.phase(f.offscreen,JSON.parse(JSON.stringify(message)))}}};
  vm.createContext(off);vm.runInContext(offscreenCode,off);
  f.offscreenListener=offscreen;
  const execute=async(fields,ticket)=>{
    f.execCalls++;
    if(options.mutate)fields.lead={...fields.lead,comment:'Changed after approved snapshot'};
    const admission=await f.host.authorize(f.sender,{...fields,nativeOffice:ticket});
    if(!admission.ok)return{ok:false,refused:true,crm_create_dispatched:false};
    const result=await new Promise(resolve=>offscreen(
      {target:'lcz-offscreen',op:'create',args:{...fields,nativeOffice:ticket}},
      {id:f.sender.id},resolve,
    ));
    await f.host.finish(f.sender,ticket,result);
    return result;
  };
  f.deps={origin:ORIGIN,api,identity:async()=>({id:f.principal,role:f.role}),
    host:(action,scope,fields)=>f.host[action](f.sender,scope,fields),
    prepare:async()=>{if(options.prepare)await options.prepare(f);
      f.candidate=structuredClone(f.proposal);return f.candidate},
    execute,load:async key=>(await storage.get(key))[key],save:async(key,value)=>storage.set({[key]:value}),
    now:()=>f.now,delay:async ms=>{f.now+=ms}};
  f.client=client=Native.create(f.deps);
  f.runJob=async()=>{const value=await client.wake();await client.settled();return value};
  f.restart=()=>{f.client=client=Native.create(f.deps)};
  return f;
}

test('actual client/host/offscreen/CRM create/readback reach only unconfirmed Telegram state',async()=>{
  const f=setup();assert.equal((await f.runJob()).active,true);
  assert.equal(f.physical,1,JSON.stringify({state:f.client.state(),events:f.events,operations:f.calls.map(c=>c[1])}));
  assert.equal(f.permissions,1);assert.equal(f.created,1);assert.equal(f.card,1);
  assert.equal(f.meta.state,'waiting_notification');
  assert.equal(f.meta.telegram_confirmed,false);assert.equal(f.meta.dialog_closed,false);
  assert.ok(f.events.indexOf('CRM_POST')<f.events.indexOf('ID_RECORDED'));
  assert.ok(f.events.indexOf('ID_RECORDED')<f.events.indexOf('CARD_READ'));
  assert.ok(f.calls.every(c=>!c[1].includes('start')&&!c[1].includes('stop')));
});
test('ID reaches Main before actual partner-note followup and card read',async()=>{
  const f=setup({note:true});await f.runJob();
  assert.equal(f.physical,1);assert.equal(f.meta.state,'waiting_notification');
  assert.ok(f.events.indexOf('ID_RECORDED')<f.events.indexOf('FOLLOWUP_partner_note'));
  assert.ok(f.events.indexOf('FOLLOWUP_partner_note')<f.events.indexOf('CARD_READ'));
});
test('known pending permission responses never duplicate the actual create',async()=>{
  const f=setup({pending:2});await f.runJob();
  assert.equal(f.permissions,1);assert.equal(f.physical,1);
  assert.equal(f.calls.filter(c=>c[1]==='issue-create').length,3);
  assert.equal(f.calls.filter(c=>c[1]==='request-create').length,1);
});
test('lost physical-permission ACK cannot POST CRM and cannot be issued again after restart',async()=>{
  const f=setup({lose:'issue-create'});await f.runJob();
  assert.equal(f.permissions,1);assert.equal(f.physical,0);
  f.restart();await f.runJob();
  assert.equal(f.permissions,1);assert.equal(f.physical,0);
  assert.equal(f.calls.filter(c=>c[1]==='issue-create').length,1);
});
test('lost created-ID evidence ACK preserves actual ID and never recreates on restart',async()=>{
  const f=setup({lose:'created'});await f.runJob();
  assert.equal(f.physical,1);assert.equal(f.created,1);
  f.restart();await f.runJob();
  assert.equal(f.physical,1);assert.equal(f.created,1);
  assert.ok([...f.store.values()].some(v=>v?.created?.id==='1234567'));
});
test('lost card ACK is reconciled by the same original status without resubmitting card or CRM',async()=>{
  const f=setup({lose:'card'});await f.runJob();assert.equal(f.meta.state,'waiting_notification');
  f.restart();await f.runJob();
  assert.equal(f.physical,1);assert.equal(f.card,1);
  assert.ok([...f.store.values()].some(v=>v?.state==='waiting_notification'));
});
test('failed durable journal before critical permission blocks both permission and CRM POST',async()=>{
  const f=setup({failStore:'physical_permission_pending'});await f.runJob();
  assert.equal(f.permissions,0);assert.equal(f.physical,0);
  assert.equal(f.calls.filter(c=>c[1]==='issue-create').length,0);
});
test('changed actual prepared fields cannot pass background ownership guard',async()=>{
  const f=setup({mutate:true});await f.runJob();
  assert.equal(f.permissions,0);assert.equal(f.physical,0);
});
test('current role change after preparing prevents CRM dispatch',async()=>{
  const f=setup({prepare:async f=>{f.role='manager'}});await f.runJob();
  assert.equal(f.physical,0);assert.equal(f.execCalls,0);assert.equal(f.permissions,0);
});
test('stopped native Run makes no executor claim/model/CRM call',async()=>{
  const f=setup();f.run.state='stopped';f.run.auto_enabled=false;
  assert.equal((await f.runJob()).active,false);
  assert.equal(f.execCalls,0);assert.equal(f.physical,0);
  assert.ok(f.calls.every(c=>c[0]==='GET'));
});
test('later edits of the preparation object cannot alter the already submitted native fields',async()=>{
  const f=setup({mutateCandidateAfterAck:true});await f.runJob();
  assert.equal(f.physical,1);
  const sent=f.core.calls.find(c=>c.kind==='POST').body.get('CustomerRequest[comments]');
  assert.equal(sent,f.proposal.lead.comment);
});
test('actual mismatching card read is kept for review and never triggers a second CRM or Telegram step',async()=>{
  const f=setup({diff:true});await f.runJob();
  assert.equal(f.physical,1);assert.equal(f.meta.crm_request_id,'1234567');
  assert.equal(f.meta.state,'created_review');assert.equal(f.run.state,'blocked');
  assert.equal(f.calls.filter(c=>c[1]==='failed').length,1);
  assert.ok([...f.store.values()].some(v=>v?.card_report?.verified?.diffs?.length));
  f.restart();await f.runJob();assert.equal(f.physical,1);
});

async function boundOnly(f){
  const chosen=await f.host.claim(f.sender,f.scope);
  const scope={...f.scope,executor_id:chosen.executor_id,work_id:H,cid:CID,
    source_sha256:SOURCE,snapshot_hash:SNAP,deadline:f.meta.deadline,lease_id:LEASE};
  const fields={dir:f.proposal.dir,lead:f.proposal.lead,sel:f.proposal.sel,allowLive:false};
  const bound=await f.host.bind(f.sender,scope,fields);
  assert.equal(bound.ok,true);return{scope,fields,ticket:bound.ticket};
}
test('background dispatch journal refuses a second create even after serviceworker restart',async()=>{
  const f=setup(),b=await boundOnly(f),args={...b.fields,nativeOffice:b.ticket};
  assert.equal((await f.host.authorize(f.sender,args)).ok,true);
  assert.equal((await f.host.authorize(f.sender,args)).ok,false);
  const restarted=Host.create(f.chrome,[ORIGIN],{now:()=>f.now,uuid:randomUUID});
  assert.equal((await restarted.authorize(f.sender,args)).ok,false);
  assert.equal(f.physical,0);
});
test('dedicated observer, foreign extension, wrong origin or frame cannot become CRM executor',async()=>{
  const f=setup();
  for(const from of [
    {...f.sender,url:ORIGIN+'/chats?lcz-assistant=1'},
    {...f.sender,id:'foreign-extension'},
    {...f.sender,url:'https://external.invalid/chats'},
    {...f.sender,frameId:1},
  ])assert.equal((await f.host.claim(from,f.scope)).ok,false);
  assert.equal(f.physical,0);assert.equal(f.calls.length,0);
});
test('another document cannot submit the original bound ticket',async()=>{
  const f=setup(),b=await boundOnly(f);
  assert.equal((await f.host.authorize({...f.sender,documentId:randomUUID()},
    {...b.fields,nativeOffice:b.ticket})).ok,false);
});
test('only a proved undispatched binding can be superseded on recovery',async()=>{
  const f=setup(),a=await boundOnly(f),b=await f.host.bind(f.sender,a.scope,a.fields);
  assert.equal(b.ok,true);assert.notEqual(b.ticket.ticket,a.ticket.ticket);
  assert.equal((await f.host.authorize(f.sender,{...a.fields,nativeOffice:a.ticket})).ok,false);
  assert.equal((await f.host.authorize(f.sender,{...a.fields,nativeOffice:b.ticket})).ok,true);
  assert.equal((await f.host.bind(f.sender,a.scope,a.fields)).reconciliation_only,true);
});
test('offscreen phase rejects forged sender and expired permit',async()=>{
  const f=setup({phaseReply:async()=>({ok:true,dispatch_before:1})}),b=await boundOnly(f);
  await f.host.authorize(f.sender,{...b.fields,nativeOffice:b.ticket});
  const request={ticket:b.ticket,fields:b.fields,phase:'create_crm'};
  assert.equal((await f.host.phase({...f.offscreen,id:'foreign'},request)).ok,false);
  assert.equal((await f.host.phase(f.offscreen,request)).ok,false);
});
test('actual ID is durable before forwarding evidence and cannot be replaced by another ID',async()=>{
  const f=setup({phaseReply:async(f,message)=>{
    assert.ok([...f.store.values()].some(v=>v?.created?.id==='1234567'));
    assert.equal(message.phase,'created');return{ok:true};
  }}),b=await boundOnly(f);
  await f.host.authorize(f.sender,{...b.fields,nativeOffice:b.ticket});
  const report={id:'1234567',url:CRM.BASES.mnc+'/admin/domain/customer-request/update?id=1234567'};
  assert.equal((await f.host.phase(f.offscreen,{ticket:b.ticket,fields:b.fields,phase:'created',report})).ok,true);
  assert.equal((await f.host.phase(f.offscreen,{ticket:b.ticket,fields:b.fields,phase:'created',
    report:{id:'7654321',url:CRM.BASES.mnc+'/admin/domain/customer-request/update?id=7654321'}})).ok,false);
});
test('awaiting original Main permission does not lock out executor heartbeat', {timeout:1000},async()=>{
  let release;
  const f=setup({phaseReply:()=>new Promise(resolve=>{release=resolve})}),b=await boundOnly(f);
  await f.host.authorize(f.sender,{...b.fields,nativeOffice:b.ticket});
  const pending=f.host.phase(f.offscreen,{ticket:b.ticket,fields:b.fields,phase:'create_crm'});
  await new Promise(setImmediate);
  assert.equal((await f.host.claim(f.sender,f.scope)).ok,true);
  release({ok:true,dispatch_before:f.now/1000+10});
  assert.equal((await pending).ok,true);
});
test('two ordinary tabs share one local host and produce only one physical CRM request',async()=>{
  let release;
  const f=setup({prepare:()=>new Promise(resolve=>{release=resolve})});
  await f.client.wake();await new Promise(setImmediate);
  const other={...f.sender,documentId:randomUUID(),tab:{id:8}};
  const second=Native.create({...f.deps,
    host:(action,scope,fields)=>f.host[action](other,scope,fields)});
  const status=await second.wake();
  assert.equal(status.active,false);assert.equal(status.state,'other_executor');
  release();await f.client.settled();
  assert.equal(f.physical,1);assert.equal(f.permissions,1);
});
test('native offscreen entry rejects a tab or foreign extension before CRM parsing',async()=>{
  const f=setup(),args={...f.core.params,nativeOffice:{ticket:randomUUID(),work_id:H}};
  for(const from of [{id:f.sender.id,tab:{id:7}},{id:'foreign-extension'}]){
    const r=await new Promise(resolve=>f.offscreenListener(
      {target:'lcz-offscreen',op:'create',args},from,resolve));
    assert.equal(r.refused,true);assert.equal(r.crm_create_dispatched,false);
  }
  assert.equal(f.physical,0);assert.equal(f.calls.length,0);
});
