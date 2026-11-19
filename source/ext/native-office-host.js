/* One native CRM dispatch per original work. This is local ownership only:
   Main's fresh Run/source and original Root permit remain the authority. */
const LC_NATIVE_OFFICE_HOST=(()=>{
  const {sameRecord}=typeof LC_NATIVE_API!=='undefined'?LC_NATIVE_API:require('./native-api.js');
  const ACTIVE='native-office-host:v1',WORK='native-office-work:v1:',INDEX='native-office-index:v1:';
  const ALARM='lcz-native-office',TTL=90000;
  const uuid=x=>typeof x==='string'&&/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(x);
  const hash=x=>typeof x==='string'&&/^[a-f0-9]{64}$/.test(x);
  const copy=x=>JSON.parse(JSON.stringify(x));
  function create(api,origins,options={}){
    const allowed=new Set(origins),now=options.now||Date.now,random=options.uuid||(()=>crypto.randomUUID());
    let chain=Promise.resolve(),waking=null;
    const serial=fn=>{const p=chain.then(fn);chain=p.catch(()=>{});return p};
    const denied=()=>({ok:false,error:'Исходный серверный исполнитель CRM не подтверждён'});
    const read=async key=>(await api.storage.local.get(key))[key];
    async function save(key,value){
      await api.storage.local.set({[key]:value});
      if(!sameRecord(await read(key),value))throw Error('Память серверного исполнителя CRM недоступна');
    }
    function sender(from){
      try{
        if(from?.id!==api.runtime.id||!Number.isInteger(from.tab?.id)||from.frameId!==0
            ||typeof from.documentId!=='string'||!from.documentId||from.documentId.length>200)return null;
        const origin=new URL(from.url).origin;
        if(!allowed.has(origin)||new URL(from.url).searchParams.get('lcz-assistant')==='1')return null;
        return {tab_id:from.tab.id,document_id:from.documentId,origin};
      }catch(_){return null}
    }
    const sameDoc=(a,b)=>a&&b&&a.tab_id===b.tab_id&&a.document_id===b.document_id&&a.origin===b.origin;
    const sameScope=(a,b)=>['principal_id','operator_id','run_id','generation'].every(k=>a?.[k]===b?.[k]);
    function scope(value){
      return value&&typeof value==='object'&&!Array.isArray(value)
        &&['principal_id','operator_id','run_id'].every(k=>uuid(value[k]))
        &&Number.isSafeInteger(value.generation)&&value.generation>0;
    }
    const fields=args=>({dir:args.dir,lead:args.lead,sel:args.sel,allowLive:args.allowLive});
    const token=t=>t&&typeof t==='object'&&uuid(t.ticket)&&hash(t.work_id)
      &&Object.keys(t).length===2;
    async function claim(from,value){
      return serial(async()=>{
        const doc=sender(from);if(!doc||!scope(value))return denied();
        if(options.isObserverTab&&await options.isObserverTab(doc.tab_id))return denied();
        const active=await read(ACTIVE),at=now();
        if(active!==undefined&&(!scope(active)||!uuid(active.executor_id)||!Number.isFinite(active.seen)))
          return denied(); // Corrupt ownership is not an empty slot.
        if(active&&at-active.seen<TTL&&(!sameDoc(active,doc)||!sameScope(active,value)))
          return {ok:false,busy:true};
        const chosen={
          ...doc,principal_id:value.principal_id,operator_id:value.operator_id,
          run_id:value.run_id,generation:value.generation,
          executor_id:active&&sameDoc(active,doc)&&sameScope(active,value)?active.executor_id:random(),
          seen:at,
        };
        await save(ACTIVE,chosen);
        return {ok:true,executor_id:chosen.executor_id};
      });
    }
    async function bind(from,value,args){
      return serial(async()=>{
        const doc=sender(from),active=await read(ACTIVE);
        if(!doc||!sameDoc(active,doc)||!scope(value)||!sameScope(active,value)
            ||active.executor_id!==value.executor_id||now()-active.seen>=TTL
            ||!hash(value.work_id)||!hash(value.source_sha256)||!hash(value.snapshot_hash)
            ||!uuid(value.lease_id)||!Number.isFinite(value.deadline)||value.deadline*1000<=now()
            ||args?.allowLive!==false||!['kp','mnc','bt'].includes(args?.dir)
            ||!args.lead||!args.sel)return denied();
        const index=INDEX+active.principal_id+':'+value.work_id;
        const previous=await read(index);
        if(previous){
          if(!token(previous))return denied();
          const old=await read(WORK+previous.ticket);
          if(!old||old.state!=='bound')return {ok:false,reconciliation_only:true};
          // A bound ticket has never dispatched CRM. Seal it before replacing
          // local ownership; delayed old-tab messages can no longer use it.
          old.state='superseded_before_dispatch';
          await save(WORK+previous.ticket,old);
        }
        const ticket={ticket:random(),work_id:value.work_id};
        const record={...active,scope:copy(value),ticket,fields:copy(fields(args)),state:'bound'};
        // Index precedes dispatch too. A partial storage failure may block an
        // unstarted work, but cannot silently mint a replacement ticket.
        await save(index,ticket);
        await save(WORK+ticket.ticket,record);
        return {ok:true,ticket};
      });
    }
    async function authorize(from,args){
      return serial(async()=>{
        const doc=sender(from),t=args?.nativeOffice;
        if(!doc||!token(t)||args.personalWorkflow)return denied();
        const active=await read(ACTIVE),record=await read(WORK+t.ticket);
        if(!record||!sameDoc(record,doc)||!sameDoc(active,doc)||!sameScope(active,record)
            ||record.ticket.work_id!==t.work_id||record.state!=='bound'
            ||active.executor_id!==record.executor_id||now()-active.seen>=TTL
            ||!sameRecord(fields(args),record.fields))return denied();
        record.state='dispatched';
        await save(WORK+t.ticket,record); // Never repeat after lost offscreen ACK.
        return {ok:true};
      });
    }
    async function phase(from,request){
      const prepared=await serial(async()=>{
        if(from?.id!==api.runtime.id||from.tab||from.url!==api.runtime.getURL('offscreen.html')
            ||!token(request?.ticket))return null;
        const record=await read(WORK+request.ticket.ticket);
        if(!record||record.state!=='dispatched'||record.ticket.work_id!==request.ticket.work_id
            ||!sameRecord(request.fields,record.fields)
            ||!['create_crm','partner_note','customer_contact','created'].includes(request.phase))return null;
        if(request.phase==='created'){
          const report=request.report,base='https://'+record.fields.dir+'-lead-centre.ru';
          if(!report||Object.keys(report).length!==2||!/^[1-9]\d{0,11}$/.test(report.id||'')
              ||report.url!==base+'/admin/domain/customer-request/update?id='+report.id
              ||record.created&&!sameRecord(record.created,report))return null;
          record.created=copy(report);
          await save(WORK+request.ticket.ticket,record); // ID evidence before content callback.
        }else{
          const active=await read(ACTIVE);
          if(!sameDoc(active,record)||!sameScope(active,record)
              ||active.executor_id!==record.executor_id||now()-active.seen>=TTL)return null;
          if(request.phase!=='create_crm'&&(!record.created||request.report?.id!==record.created.id
              ||request.report?.dir!==record.fields.dir))return null;
        }
        return copy(record);
      });
      if(!prepared)return denied();
      let reply;
      try{
        // Document-specific routing cannot target a new login/reloaded tab.
        // No local storage lock is held while the authenticated content code
        // waits for Main's original command/permission.
        reply=await api.tabs.sendMessage(prepared.tab_id,{
          kind:'lcz-native-office-phase',ticket:prepared.ticket,phase:request.phase,
          ...(request.report?{report:request.report}:{}),
        },{documentId:prepared.document_id});
      }catch(_){return denied()}
      if(request.phase==='created')return reply?.ok===true?{ok:true}:denied();
      return serial(async()=>{
        const active=await read(ACTIVE),record=await read(WORK+prepared.ticket.ticket);
        return reply?.ok===true&&sameDoc(active,prepared)&&sameScope(active,prepared)
          &&active.executor_id===prepared.executor_id&&record?.state==='dispatched'
          &&Number.isFinite(reply.dispatch_before)&&now()<reply.dispatch_before*1000
          ?{ok:true,dispatch_before:reply.dispatch_before}:denied();
      });
    }
    async function finish(from,t,result){
      return serial(async()=>{
        const doc=sender(from);if(!doc||!token(t))return denied();
        const record=await read(WORK+t.ticket);
        if(!record||!sameDoc(record,doc)||record.ticket.work_id!==t.work_id)return denied();
        if(record.state!=='dispatched')return {ok:false,reconciliation_only:true};
        record.state=result?.crm_create_dispatched===false?'no_write'
          :result?.ok===true&&/^[1-9]\d{0,11}$/.test(String(result.id||''))?'created':'unknown';
        record.result={
          state:record.state,crm_create_dispatched:result?.crm_create_dispatched===true,
          id:/^[1-9]\d{0,11}$/.test(String(result?.id||''))?String(result.id):null,
        };
        await save(WORK+t.ticket,record);
        return {ok:true};
      });
    }
    async function recover(from,value){
      const doc=sender(from);if(!doc||!scope(value)||!hash(value.work_id))return denied();
      const t=await read(INDEX+value.principal_id+':'+value.work_id);
      if(!token(t))return {ok:true,found:false};
      const row=await read(WORK+t.ticket);
      if(!row||row.principal_id!==value.principal_id||row.origin!==doc.origin)return denied();
      return {ok:true,found:true,state:row.state,scope:row.scope,
        ...(row.created?{created:row.created}:{}),ticket:row.ticket};
    }
    async function wake(){
      if(waking)return waking;
      waking=(async()=>{
        const active=await read(ACTIVE);
        if(active?.tab_id!==undefined&&allowed.has(active.origin)&&now()-active.seen<TTL){
          try{
            const r=await api.tabs.sendMessage(active.tab_id,{kind:'lcz-native-office-wake'},
              {documentId:active.document_id});
            if(r?.active===true)return;
          }catch(_){/* Read observation only; no permission or Run stop inferred. */}
        }
        const tabs=await api.tabs.query({url:[...allowed].map(o=>o+'/*')});
        for(const tab of (tabs||[]).slice(0,10)){
          try{
            if(!Number.isInteger(tab.id)||!allowed.has(new URL(tab.url).origin)
                ||new URL(tab.url).searchParams.get('lcz-assistant')==='1'
                ||options.isObserverTab&&await options.isObserverTab(tab.id))continue;
            const r=await api.tabs.sendMessage(tab.id,{kind:'lcz-native-office-wake'},{frameId:0});
            if(r?.active===true)return;
          }catch(_){/* Try another actual allowed surface, never another provider. */}
        }
      })().finally(()=>{waking=null});
      return waking;
    }
    async function install(){
      if(!await api.alarms.get(ALARM))await api.alarms.create(ALARM,{periodInMinutes:0.5});
    }
    api.alarms?.onAlarm?.addListener(alarm=>{if(alarm.name===ALARM)wake().catch(()=>{})});
    return {claim,bind,authorize,phase,finish,recover,wake,install};
  }
  return {create};
})();
if(typeof module!=='undefined')module.exports=LC_NATIVE_OFFICE_HOST;
