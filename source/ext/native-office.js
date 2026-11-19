/* Current Main Run -> accepted form -> existing CRM executor. No panel lease,
   model call, Run start, Telegram send or close is exposed by this module. */
const LC_NATIVE_OFFICE=(()=>{
  const {sameRecord}=typeof LC_NATIVE_API!=='undefined'?LC_NATIVE_API:require('./native-api.js');
  const BASE='/bot-dialogs/assistant',OFFICE=BASE+'/native-office/';
  const existingRequest='crm_existing_request';
  const uuid=x=>typeof x==='string'&&/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(x);
  const hash=x=>typeof x==='string'&&/^[a-f0-9]{64}$/.test(x);
  const copy=x=>JSON.parse(JSON.stringify(x));
  const proposalKeys=['revision','form_reference','dir','lead','prep','territory','sel',
    'readiness','flags','allowLive','followup'];
  const phases=new Set(['ready','prepared','authorizing','office_reserved','consume_requested']);
  function create(deps){
    if(!deps||['identity','host','prepare','execute','load','save'].some(k=>typeof deps[k]!=='function')
        ||!deps.api||['get','post'].some(k=>typeof deps.api[k]!=='function'))throw Error('Нужен серверный исполнитель CRM');
    const now=deps.now||Date.now,delay=deps.delay||(ms=>new Promise(r=>setTimeout(r,ms)));
    let active=null,waking=null,last={state:'idle'};
    const fail=code=>Object.assign(Error('Шаг серверного исполнителя CRM остановлен'),{code});
    function session(run,executor){
      return {principal_id:run.principal_id,operator_id:run.operator_id,run_id:run.run_id,
        generation:run.generation,executor_id:executor};
    }
    const same=(a,b)=>['principal_id','operator_id','run_id','generation'].every(k=>a?.[k]===b?.[k]);
    function body(scope,work=false){
      return {expected_principal_id:scope.principal_id,operator_id:scope.operator_id,
        run_id:scope.run_id,generation:scope.generation,executor_id:scope.executor_id,
        ...(work?{work_id:scope.work_id,lease_id:scope.lease_id}:{})};
    }
    const key=s=>'native-office-local:v1:'+deps.origin+':'+s.principal_id+':'+s.work_id;
    const activeKey=principal=>'native-office-active:v1:'+deps.origin+':'+principal;
    async function persist(job,changes){
      const value={...(job.record||{}),...copy(changes),scope:copy(job.scope),version:1};
      await deps.save(key(job.scope),value);
      const stored=await deps.load(key(job.scope));
      if(!sameRecord(stored,value))throw fail('native_storage');
      const pointer={work_id:job.scope.work_id};
      await deps.save(activeKey(job.scope.principal_id),pointer);
      if(!sameRecord(await deps.load(activeKey(job.scope.principal_id)),pointer))
        throw fail('native_storage');
      job.record=value;
    }
    async function current(expected){
      const me=await deps.identity();
      if(me?.role!=='admin'||!uuid(me.id))return null;
      const run=await deps.api.get(BASE+'/native-run');
      if(run?.principal_id!==me.id||run.native_supported!==true||run.configured!==true
          ||run.state!=='running'||run.mode!=='auto'||run.auto_enabled!==true)return null;
      if(!uuid(run.run_id)||!uuid(run.operator_id)||!Number.isSafeInteger(run.generation)
          ||run.generation<1)throw fail('native_run');
      if(expected&&!same(expected,run))throw fail('native_run_changed');
      return run;
    }
    async function fresh(job){
      if(job.invalid||!await current(job.scope))throw fail('native_run_changed');
      if(now()>=job.scope.deadline*1000)throw fail('native_deadline');
    }
    function view(value,scope){
      if(!value||value.work_id!==scope.work_id||value.source_sha256!==scope.source_sha256
          ||value.cid!==scope.cid||value.deadline!==scope.deadline
          ||scope.snapshot_hash&&value.snapshot_hash!==scope.snapshot_hash
          ||value.execution_allowed!==false)throw fail('native_work_changed');
      return value;
    }
    async function post(job,operation,extra={}){
      return deps.api.post(OFFICE+operation,{...body(job.scope,true),...extra});
    }
    async function status(job){return view(await post(job,'status'),job.scope)}
    function crmOnly(job){
      const followup=job.proposal?.followup;
      return followup?.mode==='crm_only'&&followup.required===false
        &&followup.telegram_ready===false;
    }
    async function completed(job,value,report){
      if(value.state!=='completed')return false;
      if(!hash(job.scope.snapshot_hash)||!report||!/^[1-9]\d{0,11}$/.test(report.id||'')
          ||report.url!=='https://'+job.proposal?.dir+'-lead-centre.ru/admin/domain/customer-request/update?id='+report.id
          ||value.crm_request_id!==report.id||value.created_id_verified!==true
          ||value.dialog_closed!==true||value.customer_effect_confirmed!==false
          ||(crmOnly(job)?value.completion_mode!=='crm_only'||value.telegram_confirmed!==false
            :value.completion_mode==='crm_only'||value.telegram_confirmed!==true))
        throw fail('native_completion_receipt');
      await persist(job,{state:'completed',created:report,created_acknowledged:true,
        completion_mode:crmOnly(job)?'crm_only':'telegram',
        telegram_confirmed:value.telegram_confirmed,dialog_closed:true});
      return true;
    }
    async function until(job,states){
      for(let n=0;n<600;n++){
        if(now()>=job.scope.deadline*1000)throw fail('native_deadline');
        const value=await status(job);
        if(states.includes(value.state))return value;
        if(!phases.has(value.state))throw fail('native_work_stopped');
        await delay(500);
      }
      throw fail('native_deadline');
    }
    async function capture(job,report){
      if(!report||!/^[1-9]\d{0,11}$/.test(report.id||'')
          ||report.url!=='https://'+job.proposal.dir+'-lead-centre.ru/admin/domain/customer-request/update?id='+report.id)
        throw fail('native_created_id');
      if(job.record?.created&&!sameRecord(job.record.created,report))
        throw fail('native_created_id_changed');
      await persist(job,{created:report,state:'created_evidence'});
      const observed=await status(job);
      if(observed.crm_request_id===report.id){
        await persist(job,{state:observed.state,created_acknowledged:true});
        return {ok:true};
      }
      if(observed.crm_request_id||job.record.created_attempted)throw fail('native_created_unknown');
      await persist(job,{created_attempted:true,state:'created_ack_pending'});
      const saved=view(await post(job,'created',{report}),job.scope);
      if(saved.crm_request_id!==report.id)throw fail('native_created_unknown');
      await persist(job,{state:'created_unverified',created_acknowledged:true});
      return {ok:true};
    }
    async function guard(job,request){
      if(active!==job||job.invalid||request.ticket?.ticket!==job.ticket?.ticket
          ||request.ticket.work_id!==job.scope.work_id)throw fail('native_document_changed');
      if(request.phase==='created')return capture(job,request.report);
      await fresh(job);
      if(request.phase==='create_crm'){
        if(job.record.physical_attempted)throw fail('native_create_already_attempted');
        await persist(job,{state:'consume_intent_pending',consume_intent_attempted:true});
        const intent=view(await post(job,'request-create'),job.scope);
        if(intent.state!=='consume_requested')throw fail('native_consume_intent');
        for(let n=0;n<600;n++){
          await fresh(job);
          // A known pending response may be observed again. A lost/malformed
          // reply leaves physical_attempted true and is never submitted again.
          await persist(job,{state:'physical_permission_pending',physical_attempted:true});
          const permit=await post(job,'issue-create');
          if(permit?.execution_allowed===true){
            if(permit.work_id!==job.scope.work_id||permit.cid!==job.scope.cid
                ||permit.operator_id!==job.scope.operator_id||permit.source_sha256!==job.scope.source_sha256
                ||permit.snapshot_hash!==job.scope.snapshot_hash||permit.kind!=='create_crm'
                ||!Number.isFinite(permit.dispatch_before)||now()>=permit.dispatch_before*1000)
              throw fail('native_create_permission');
            await persist(job,{state:'physical_create_started'});
            return {ok:true,dispatch_before:permit.dispatch_before};
          }
          view(permit,job.scope);
          if(permit.reconciliation_only||permit.state!=='consume_requested')
            throw fail('native_create_unknown');
          await persist(job,{state:'awaiting_original_permit',physical_attempted:false});
          await delay(250);
        }
        throw fail('native_deadline');
      }
      if(!['partner_note','customer_contact'].includes(request.phase)
          ||!job.record.created_acknowledged||request.report?.id!==job.record.created?.id
          ||request.report?.dir!==job.proposal.dir)throw fail('native_followup');
      const done=job.record.followup_attempted||{};
      if(done[request.phase])throw fail('native_followup_already_attempted');
      await persist(job,{followup_attempted:{...done,[request.phase]:true}});
      const permit=await post(job,'followup',{crm_request_id:request.report.id,kind:request.phase});
      if(permit?.execution_allowed!==true||permit.kind!==request.phase
          ||permit.crm_request_id!==job.record.created.id||permit.snapshot_hash!==job.scope.snapshot_hash
          ||!Number.isFinite(permit.dispatch_before)||now()>=permit.dispatch_before*1000)
        throw fail('native_followup_permission');
      return {ok:true,dispatch_before:permit.dispatch_before};
    }
    async function confirmDuplicateStop(job,saved,report){
      if(report||job.record.physical_attempted||saved.state!=='stopped'||saved.crm_request_id!==null
          ||(saved.reason_code!==existingRequest&&!job.record.duplicate_before_create))
        return false;
      await persist(job,{state:'stopped_before_create',reason_code:existingRequest});
      last={state:'stopped_before_create',work_id:job.scope.work_id,reason_code:existingRequest};
      return true;
    }
    async function reconcile(job,hostRecord){
      const saved=await status(job);
      const report=job.record?.created||hostRecord?.created;
      if(await completed(job,saved,report))return;
      if(await confirmDuplicateStop(job,saved,report))return;
      if(saved.state==='waiting_notification'){
        await persist(job,{state:crmOnly(job)?'completion_pending':'waiting_notification'});return;
      }
      if(report&&job.proposal){
        try{await capture(job,report)}catch(_){/* Preserve original ID, never create again. */}
      }
      const state=job.record.duplicate_before_create&&!report&&!job.record.physical_attempted
        ?'before_create_stop_pending':'created_review';
      await persist(job,{state,reconciliation_only:true});
    }
    async function reportFailure(job,extra){
      if(job.record?.failure_attempted)return;
      await persist(job,{failure_attempted:true});
      return post(job,'failed',extra); // Same original Work; never a CRM/model replay.
    }
    async function process(job,envelope){
      await persist(job,{state:'preparing'});
      const recovery=await deps.host('recover',job.scope);
      if(recovery?.ok!==true)throw fail('native_host');
      if(recovery.found&&['dispatched','unknown','created'].includes(recovery.state)
          ||job.record.physical_attempted||job.record.crm_dispatched){
        job.proposal=envelope.proposal||job.record.proposal;
        if(recovery.scope)job.scope={...recovery.scope,cid:job.scope.cid};
        await reconcile(job,recovery);return;
      }
      await fresh(job);
      let proposed=envelope.proposal;
      if(!proposed){
        const candidate=await deps.prepare(envelope,job.scope);
        // Detach before crossing the async API boundary: a later UI/cache
        // edit cannot mutate the fields whose snapshot Main has accepted.
        proposed=copy(Object.fromEntries(proposalKeys.map(k=>[k,candidate[k]])));
        await persist(job,{state:'prepare_ack_pending',proposal:proposed});
        const result=view(await post(job,'prepare',{proposal:proposed}),job.scope);
        if(!hash(result.snapshot_hash))throw fail('native_proposal');
        job.scope.snapshot_hash=result.snapshot_hash;
      }else{
        if(!hash(envelope.snapshot_hash))throw fail('native_proposal');
        job.scope.snapshot_hash=envelope.snapshot_hash;
      }
      job.proposal=copy(proposed);
      if(job.proposal.form_reference!==envelope.form.form_reference
          ||job.proposal.revision!==envelope.form.revision
          ||job.proposal.allowLive!==false||job.proposal.readiness!=='ready'
          ||!Array.isArray(job.proposal.flags)||job.proposal.flags.length)
        throw fail('native_proposal');
      if((envelope.form.completion_mode==='crm_only')!==crmOnly(job)
          ||!['telegram','crm_only'].includes(envelope.form.completion_mode||'telegram'))
        throw fail('native_completion_mode');
      await persist(job,{state:'prepared',proposal:job.proposal});
      await until(job,['office_reserved']);
      await fresh(job);
      const fields={dir:job.proposal.dir,lead:copy(job.proposal.lead),
        sel:copy(job.proposal.sel),allowLive:false};
      const bound=await deps.host('bind',job.scope,fields);
      if(bound?.ok!==true||!uuid(bound.ticket?.ticket)||bound.ticket.work_id!==job.scope.work_id)
        throw fail('native_host_bound');
      job.ticket=bound.ticket;
      await persist(job,{state:'crm_dispatched',crm_dispatched:true,ticket:bound.ticket});
      const result=await deps.execute(fields,bound.ticket);
      if(result?.id&&!job.record.created){
        await capture(job,{id:String(result.id),url:result.url});
      }
      if(!result?.ok||!result.id){
        if(result?.crm_create_dispatched===false&&result.reason_code===existingRequest
            &&result.skipped===true&&!job.record.physical_attempted&&!job.record.created){
          await persist(job,{state:'before_create_stop_pending',duplicate_before_create:true});
          const response=await reportFailure(job,envelope.supports_duplicate_stop===true
            ?{stop_reason:existingRequest}:undefined);
          await confirmDuplicateStop(job,view(response,job.scope),null);
          return;
        }
        await persist(job,{state:job.record.created?'created_review':'create_result_unknown'});
        // Only an original physical unknown or a proved no-POST result.
        // Known IDs remain evidence even if an observer/report step failed.
        await reportFailure(job);
        return;
      }
      const report={
        id:String(result.id),url:result.url,form_reference:envelope.form.form_reference,
        snapshot_hash:job.scope.snapshot_hash,policy_version:envelope.form.policy_version,
        message_revision:envelope.message_revision,
        verified:result.verified,warnings:result.warnings||[],
      };
      job.finishing=true; // Do not lease a later work after a lost card ACK.
      await persist(job,{state:'card_ack_pending',card_attempted:true,card_report:report});
      const accepted=view(await post(job,'card',{report}),job.scope);
      if(accepted.duplicate_found!==false)throw fail('native_card_review');
      if(await completed(job,accepted,{id:String(result.id),url:result.url}))return;
      if(accepted.state!=='waiting_notification'||accepted.duplicate_found!==false)
        throw fail('native_card_review');
      await persist(job,{state:crmOnly(job)?'completion_pending':'waiting_notification'});
    }
    function workScope(run,executor,envelope){
      if(!hash(envelope?.work_id)||!uuid(envelope.cid)||!hash(envelope.source_sha256)
          ||!uuid(envelope.lease_id)||!Number.isFinite(envelope.deadline)
          ||envelope.deadline*1000<=now()||envelope.execution_allowed!==false)
        throw fail('native_work');
      return {...session(run,executor),work_id:envelope.work_id,cid:envelope.cid,
        lease_id:envelope.lease_id,source_sha256:envelope.source_sha256,
        snapshot_hash:envelope.snapshot_hash||null,deadline:envelope.deadline};
    }
    async function wake(){
      if(waking)return waking;
      waking=(async()=>{
        const me=await deps.identity();
        if(me?.role!=='admin'||!uuid(me.id))return {active:false,state:'idle'};
        if(!active){
          const pointer=await deps.load(activeKey(me.id));
          if(pointer?.work_id&&hash(pointer.work_id)){
            const old=await deps.load(key({principal_id:me.id,work_id:pointer.work_id}));
            if(old?.scope?.principal_id===me.id&&old.version===1
                &&(old.physical_attempted||old.crm_dispatched)
                &&!['waiting_notification','completed','stopped_before_create'].includes(old.state)){
              const job={scope:copy(old.scope),record:old,proposal:old.proposal,
                invalid:true,finishing:true,recovery_only:true};
              active=job;
              job.promise=(async()=>{
                const recovery=await deps.host('recover',job.scope);
                await reconcile(job,recovery?.ok===true?recovery:null);
              })().catch(()=>{last={state:old.duplicate_before_create?'before_create_stop_pending':'created_review',
                work_id:job.scope.work_id}})
                .finally(()=>{if(active===job)active=null});
              return {active:true,state:'reconciliation_only'};
            }
          }
        }
        if(active?.recovery_only)return {active:true,state:'reconciliation_only'};
        const run=await current();
        if(!run){if(active)active.invalid=true;return {active:false,state:'idle'}}
        const chosen=await deps.host('claim',run);
        if(chosen?.ok!==true||!uuid(chosen.executor_id))return {active:false,state:'other_executor'};
        const s=session(run,chosen.executor_id);
        await deps.onActive?.();
        const heartbeat=await deps.api.post(OFFICE+'heartbeat',body(s));
        if(heartbeat?.available!==true)return {active:false,state:'waiting_executor'};
        if(active){
          if(!same(active.scope,s)||active.scope.executor_id!==s.executor_id){
            active.invalid=true;return {active:false,state:'native_run_changed'};
          }
          if(!active.finishing){
            const observed=await deps.api.post(OFFICE+'poll',body(s));
            if(observed.work_id===active.scope.work_id){
              view(observed,active.scope);
              if(observed.lease_id&&observed.lease_id!==active.scope.lease_id)active.invalid=true;
            }
          }
          return {active:true,state:active.record?.state||'working'};
        }
        const envelope=await deps.api.post(OFFICE+'poll',body(s));
        if(!phases.has(envelope?.state))return {active:true,state:envelope?.state||'idle'};
        if(!envelope.form||envelope.form.ok!==true||envelope.form.auto_enabled!==false
            ||envelope.form.intake_form_ready!==true||!hash(envelope.form.form_reference)
            ||!hash(envelope.message_revision))throw fail('native_form');
        const scope=workScope(run,s.executor_id,envelope),record=await deps.load(key(scope));
        const job={scope,record:record||null,invalid:false,finishing:false};
        if(record&&(!same(record.scope,scope)||record.scope.source_sha256!==scope.source_sha256))
          throw fail('native_local_scope_changed');
        active=job;
        job.promise=process(job,envelope).catch(async error=>{
          const state=job.record?.created?'created_review'
            :job.record?.duplicate_before_create?'before_create_stop_pending':'observation_unknown';
          last={state,work_id:scope.work_id,
            reason_code:/^[a-z_]{1,60}$/.test(error?.code||'')?error.code:'native_step_stopped'};
          try{await persist(job,last)}catch(_){/* No permission may follow failed journal storage. */}
          if(job.record?.created){
            try{await reportFailure(job)}catch(_){/* Original status/evidence recovery only. */}
          }
        }).finally(()=>{if(active===job)active=null});
        return {active:true,state:'working'};
      })().catch(()=>({active:!!active,state:'observation_unavailable'})).finally(()=>{waking=null});
      return waking;
    }
    async function phase(request){
      const job=active;if(!job)return {ok:false};
      try{return await guard(job,request)}catch(_){return {ok:false}}
    }
    return {wake,phase,state:()=>active?.record?{state:active.record.state,work_id:active.scope.work_id}:last,
      settled:()=>active?.promise||Promise.resolve()};
  }
  return {create};
})();
if(typeof module!=='undefined')module.exports=LC_NATIVE_OFFICE;
