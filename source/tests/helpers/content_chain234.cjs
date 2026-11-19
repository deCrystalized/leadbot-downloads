'use strict';
// Run the installed content adapters, create-message wrapper and Telegram
// routing. Only browser/CRM/native/Telegram I/O is replaced with isolated data.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(require.resolve('../../ext/content'),'utf8');
const {existingForm}=require('./existing_form233.cjs');
async function verifyMockCard(args,calls,options){
 const lead=args.lead,sel=args.sel,addr=lead.addr||{};
 const values={
  '_personal_workflow':'1','_advertiser_line':lead.advertiser_line||'',
  'CustomerRequest[city_id]':sel.cityId,'CustomerRequest[appliance_type_id]':sel.applId,
  'CustomerRequest[sub_type_id]':sel.subId,'CustomerRequest[type]':sel.type||'1',
  'CustomerRequest[partner_id]':lead.partner,'CustomerRequest[opened_at]':lead.visit_date,
  'cr_opened_at_time':lead.visit_time,'CustomerRequest[partner_comment]':lead.partner_note,
  'CustomerRequest[comments]':lead.comment,'CustomerRequest[comments_service]':lead.service_comment,
  'Customer[phone]':lead.phone,'Customer[first_name]':lead.name,
  'CustomerRequest[is_req_fback]':lead.review?'1':'0','CustomerRequest[is_need_call_before_visit]':lead.call_before_visit?'1':'0',
  'Customer[address_locality]':addr.locality,'Customer[address_street]':addr.street,
  'Customer[address_building]':addr.building,'Customer[address_office]':addr.office,
  'Customer[address_entrance]':addr.entrance,'Customer[address_floor]':addr.floor,
 };
 // The native advertiser metadata is an existing preparation input, never a
 // model-provided identity. This fixture supplies the serialized field marker.
 values._advertiser_line=lead.comment.split('\n').find(s=>/Денис|Георгий/.test(s))||lead.comment;
 const sent=new URLSearchParams(Object.entries(values).filter(([,v])=>v!=null&&v!=='').map(([k,v])=>[k,String(v)]));
 const elements=Object.fromEntries([...sent].map(([name,value])=>[name,{tagName:'INPUT',type:'text',value}]));
 if(options.cardMismatch)elements['Customer[phone]'].value='79990000000';
 const scope={...require('../../ext/crm')._внутр,
  fetchDoc:async url=>{calls.push({kind:'independent_card_read',url});return{querySelector:()=>({elements})}},
  полеВидаУслуг:()=>({name:'CustomerRequest[sub_type_id]'}),
 };
 vm.createContext(scope);
 const code=fs.readFileSync(require.resolve('../../ext/crm'),'utf8');
 const a=code.indexOf('  async function verifyCreated('),b=code.indexOf('  /* СОЗДАНИЕ —',a);
 assert.ok(a>=0&&b>a);vm.runInContext(code.slice(a,b)+';globalThis.verify=verifyCreated;',scope);
 return scope.verify('https://synthetic.invalid',9000001,sent);
}
function contentChain(h,options={}){
 const calls=[],data=new Map();
 const scope={...h.deps,LC_WORKFLOW:require('../../ext/workflow'),LC_TG:require('../../ext/tg'),
  workflowPrepare:(s,p,f)=>existingForm(s.ctx,options).run(s,p,f),
  assistantPanel:{personal:{state:{delegated:true,operator:'11111111-1111-4111-8111-111111111111'}}},
  assistantNative:{runnable:async cid=>h.jobs.get(cid),
   complete:async(cid,id,receipt)=>{calls.push({kind:'native_complete',cid,id,receipt});
    assert.equal(receipt.telegram_confirmed,true);
    h.effects.push({kind:'complete',cid});
    await h.rpc({op:'update',cid,changes:{crmRequestId:id,conversationStatus:'closed'}});
    return{crm_request_id:id,same_request_conversation_ids:[]};}},
  chrome:{runtime:{sendMessage:(request,callback)=>{
   calls.push(structuredClone(request));
   assert.equal(request.kind,'lcz-crm');assert.equal(request.op,'create');
   const run=async()=>{
    if(options.createUnknown){h.effects.push({kind:'create_unknown',cid:request.args.workflow_guard.conv_id});return{ok:false,unknown:true,error:'Synthetic lost CRM result'};}
    const cid=request.args.workflow_guard.conv_id;
    h.effects.push({kind:'create',cid});
    const verified=await verifyMockCard(request.args,calls,options);
    calls.push({kind:'actual_verification_result',verified});
    h.effects.push({kind:'read_card_and_dedup',cid});
    const r={ok:true,id:'9000001',verified,warnings:[]};
    if(options.readbackDuplicate)r.warnings=['Найдена другая ожидающая заявка'];
    return r;
   };
   run().then(callback,error=>callback({ok:false,unknown:true,error:error.message}));
  }}},
  alive:()=>true,покаЖиво:p=>p,УСТАРЕЛО:'Synthetic extension invalidated',
  поОдному:async(_key,fn)=>fn(),
  store:{get:async(k,fallback)=>data.has(k)?data.get(k):fallback,set:async(k,v)=>data.set(k,v)},
  деталь:async cid=>{const c=await h.rpc({op:'context',cid});return{crm_request_id:c.crmRequestId,status:c.conversationStatus}},
  assistantContext:async cid=>h.rpc({op:'context',cid}),
  группыTG:async()=>options.missingGroup?{ok:true,chats:{}}:{ok:true,chats:{'synthetic-avito':{title:'Авито-Чаты'}}},
  чатАвито:g=>g?.chats?.['synthetic-avito']?['synthetic-avito',g.chats['synthetic-avito']]:null,
  разделСозданных:async()=>options.missingTopic?null:{id:170,title:'Созданные с Авито'},
  забытьРаздел:()=>{},текстАвито:(id,code,dir)=>(id+' - '+code+' '+scope.LC_TG.ИМЯ[dir]).trim(),
  send:async request=>{
   calls.push(structuredClone(request));assert.equal(request.kind,'lcz-tg');
   assert.equal(request.args.chat,'synthetic-avito');assert.equal(request.args.reply_to,170);
   const cid=request.args.conv;
   if(options.telegramUnknown){h.effects.push({kind:'telegram_unknown',cid});return{ok:false,unknown:true,error:'Synthetic lost Telegram result'};}
   if(options.telegramReject){h.effects.push({kind:'telegram_rejected',cid});return{ok:false,error:'Synthetic rejected Telegram post'};}
   h.effects.push({kind:'telegram_confirmed',cid});return{ok:true,message_id:'synthetic-post'};
  },
 };
 vm.createContext(scope);
 for(const [start,end]of [
  ['  const безОтветаCRM =','  // где оператор:'],
  ['  async function отписатьСозданную(','  /* Что после создания НЕ отписано'],
  ['  const workflowAdapters={','  async function openAssistant()'],
 ]){const a=source.indexOf(start),b=source.indexOf(end,a);assert.ok(a>=0&&b>a,start);vm.runInContext(source.slice(a,b),scope);}
 const adapters=vm.runInContext('workflowAdapters',scope);
 h.deps.formPreview=s=>h.call('form_preview',s.ctx,{wording_mode:'neural_auto'});
 h.deps.prepareCRM=(s,p,f)=>existingForm(s.ctx,options).run(s,p,f);
 for(const name of ['createCRM','notifyCreated','linkCRM','reconcile'])h.deps[name]=(...args)=>adapters[name](...args);
 return{calls,data};
}
module.exports={contentChain};
