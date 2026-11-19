/* Browser-owned review session. No claim, customer-send or CRM-write transport. */
const LC_PERSONAL = (() => {
  function create(deps) {
    const state = {active:false,auto:false,autoAvailable:false,nonce:'',policy:'',busy:false,operator:'',principal:'',authors:[],delegated:false,name:'',max:0,rows:[],checked:0,total:0,mine:0,managed:0,error:'',log:[],offset:0,more:false,lastConfirmedAt:null,leaseExpiresAt:null,connection:{phase:'idle',trigger:'',startedAt:null,completedAt:null,durationMs:null}};
    let epoch=0,timer=0,heartbeatPending=null,pulseId='',leaseStartedAt=null,startQueue=Promise.resolve();
    Object.assign(state,{orderedControl:false,connectionEpoch:0,controlSeq:0,modeEpoch:0});
    const controlArgs=()=>state.orderedControl
      ?{connection_epoch:state.connectionEpoch,control_seq:++state.controlSeq}
      :{};
    let queueKey='';
    async function readHistory(id){
      const schedule=deps.schedule||setTimeout,clear=deps.clear||clearTimeout;let timer;
      try{return await Promise.race([deps.loadContext(id),new Promise((_,reject)=>{timer=schedule(()=>reject(Error('Чтение полной истории заняло слишком долго')),deps.historyTimeout||20000)})])}
      finally{clear(timer)}
    }
    const emit=()=>{if(deps.onChange)deps.onChange(state)};
    const note=(text)=>{state.log.unshift({at:Date.now(),text});state.log=state.log.slice(0,20)};
    const unregister=id=>Promise.resolve().then(()=>deps.stopPulse?.(id)).catch(()=>{});
    function clearPulse(){const old=pulseId;pulseId='';if(old)unregister(old)}
    function loseConnection(message){
      clearInterval(timer);timer=0;epoch++;wakeProofReaders();clearPulse();heartbeatPending=null;
      state.active=false;state.auto=false;state.apiAllowance=null;state.nonce='';state.busy=false;state.rows=[];
      state.error=message;state.connection={...state.connection,stoppedPhase:state.connection.phase,phase:'stopped',completedAt:Date.now()};note(message);emit();
    }
    function checkLease(){
      if(!state.active)return false;
      const now=Date.now();
      if(!Number.isFinite(state.leaseExpiresAt)||now>=state.leaseExpiresAt||now<leaseStartedAt){
        loseConnection('Нет свежего подтверждения связи. Сессия остановлена; подключите её заново');return false;
      }
      return true;
    }
    function acceptLease(confirmed){
      const value=confirmed.response.lease_seconds;
      // Legacy replies omitted the field; the server's existing maximum is45s.
      // A supplied invalid/zero value never gets that compatibility default.
      const seconds=value===undefined?45:value;
      if(!Number.isFinite(seconds)||seconds<=0)throw Error('Срок подтверждения связи не получен');
      const now=Date.now(),until=confirmed.sentAt+Math.min(45,seconds)*1000;
      if(now<confirmed.sentAt||now>=until)throw Error('Подтверждение связи запоздало. Подключите сессию заново');
      leaseStartedAt=confirmed.sentAt;state.leaseExpiresAt=until;state.lastConfirmedAt=now;
    }
    let proof=null,proofPending=null;
    const proofReads=new Set(),proofWaiters=new Set();
    const wakeProofReaders=()=>{for(const wake of [...proofWaiters])wake()};
    function protectedProof(){return [...proofReads].some(entry=>entry.epoch===epoch&&entry.proof===proof)}
    function identityError(message,unknown=false){return Object.assign(Error(message),{code:'research_stopped',noRetry:unknown})}
    async function waitForProof(generation,until){
      if(generation!==epoch)throw identityError('Сессия или автор изменились');
      const remaining=until-Date.now();
      if(remaining<=0)throw identityError('Проверка автора занята; запрос не отправлялся');
      await new Promise((resolve,reject)=>{
        let timer;const wake=()=>{clearTimeout(timer);proofWaiters.delete(wake);resolve()};
        proofWaiters.add(wake);timer=setTimeout(()=>{proofWaiters.delete(wake);reject(identityError('Проверка автора занята; запрос не отправлялся'))},remaining);
      });
    }
    async function identityArgs({minValidityMs=10000}={}){
      if(!state.delegated)return {};
      if(!Number.isFinite(minValidityMs)||minValidityMs<0||minValidityMs>35000)throw Error('Недопустимый срок проверки автора');
      if(proof&&proof.operator===state.operator&&proof.expires>Date.now()
          &&(proof.expires>Date.now()+minValidityMs||protectedProof()))return {identity_proof:proof.value,browser_session:proof.sid};
      if(protectedProof())throw identityError('Подтверждение автора истекло; запрос не отправлялся');
      if(!proofPending||proofPending.actor!==state.operator||proofPending.epoch!==epoch){
        const actor=state.operator,g=epoch,entry={actor,epoch:g,promise:null};proofPending=entry;
        // A challenge can revoke the old server nonce even when its reply is
        // lost/invalid. Never fall back to that cached proof after an error.
        proof=null;
        entry.promise=Promise.resolve().then(()=>deps.getProof(actor)).then(r=>{
        if(g!==epoch||actor!==state.operator)throw Error('Автор изменился');
        if(!r?.identity_proof||!Number.isFinite(r.expires_at)||r.expires_at*1000<=Date.now()+minValidityMs)throw Error('Не подтверждён достаточный срок проверки автора');
        proof={operator:actor,value:r.identity_proof,expires:r.expires_at*1000,sid:r.browser_session};return {identity_proof:proof.value,browser_session:proof.sid};
        }).finally(()=>{if(proofPending===entry)proofPending=null});
      }
      return proofPending.promise;
    }
    async function withIdentity(operation){
      // Ordinary manual/legacy operation retains its existing transport. This
      // coordination applies only to an active delegated browser session.
      if(!state.delegated||!state.active)return operation(await identityArgs());
      const generation=epoch,until=Date.now()+20000;
      while(true){
        if(generation!==epoch||!checkLease())throw identityError('Сессия или автор изменились');
        if(protectedProof()&&proof.expires<=Date.now()+35000){await waitForProof(generation,until);continue}
        let acquisitionTimer,wake;
        let args;
        try{args=await Promise.race([identityArgs({minValidityMs:35000}),new Promise((_,reject)=>{
          wake=()=>{if(generation!==epoch)reject(identityError('Сессия или автор изменились'))};
          proofWaiters.add(wake);
          acquisitionTimer=setTimeout(()=>reject(identityError('Подтверждение автора не получено; запрос не отправлялся')),Math.max(1,until-Date.now()));
        })])}finally{clearTimeout(acquisitionTimer);proofWaiters.delete(wake)}
        if(generation!==epoch||!checkLease())throw identityError('Сессия или автор изменились');
        if(!proof||proof.expires<=Date.now()+35000){await waitForProof(generation,until);continue}
        const entry={epoch:generation,proof};proofReads.add(entry);let deadline;
        try{
          const result=await Promise.race([Promise.resolve().then(()=>{
            if(generation!==epoch||!checkLease())throw identityError('Сессия или автор изменились');
            return operation(args);
          }),new Promise((_,reject)=>{deadline=setTimeout(()=>reject(identityError('Результат запроса не подтверждён. Повтор не запускался',true)),30000)})]);
          if(generation!==epoch||!checkLease()||entry.proof.expires<=Date.now())throw identityError('Сессия или автор изменились после запроса',true);
          return result;
        }finally{clearTimeout(deadline);proofReads.delete(entry);wakeProofReaders()}
      }
    }
    const sourceActions=new Set(['preview','form_preview','observe','validate','screen','personal_plan','personal_crm_check',
      'personal_call_confirm','personal_check_started','personal_media_review','personal_authorize','personal_review_authorize',
      'research_start','research_status','research_cancel','research_finalize','research_audit']);
    const identityCall=(action,operation)=>sourceActions.has(action)?withIdentity(operation):identityArgs().then(operation);
    const request=async(action,extra={})=>{
      const generation=epoch;
      if(action==='personal_heartbeat'&&!checkLease())throw Error('Личная сессия истекла');
      return identityCall(action,async identity=>{
        const args={action,operator_id:state.operator,
          ...(['personal_heartbeat','personal_status'].includes(action)&&state.orderedControl?{connection_epoch:state.connectionEpoch}:{}),
          ...extra,...identity};
        if(action==='personal_heartbeat'&&(generation!==epoch||!checkLease()))throw Error('Личная сессия истекла');
        const sentAt=Date.now();
        return {response:await deps.send({kind:'lcz-assistant',args}),sentAt};
      });
    };
    const call=async(action,extra={})=>(await request(action,extra)).response;
    const fail=(r)=>{if(!r||r.ok===false){const error=Error(r&&r.error||'Не удалось проверить личную сессию');if(typeof r?.code==='string')error.code=r.code;throw error}return r};
    async function confirm(action,extra={}){
      const value=await request(action,extra),r=fail(value.response);
      // A delayed success is not fresh permission. The server remains the
      // authority; this conservative client check never extends its lease.
      if(r.active&&Number.isFinite(r.lease_seconds)
          &&Date.now()-value.sentAt>=Math.max(0,Math.min(45,r.lease_seconds))*1000)
        throw Error('Подтверждение связи запоздало. Подключите сессию заново');
      return value;
    }
    const absorb=(r,action='')=>{
      const ordered=r.control_protocol==='ordered_v1';
      if(ordered&&(!Number.isSafeInteger(r.connection_epoch)||r.connection_epoch<1
          ||!Number.isSafeInteger(r.control_seq)||r.control_seq<0))throw Error('Не подтверждён порядок команд сессии');
      if(state.orderedControl&&(!ordered||r.connection_epoch!==state.connectionEpoch||r.control_seq<state.controlSeq))return false;
      if(Number.isSafeInteger(r.mode_epoch)&&r.mode_epoch<state.modeEpoch)return false;
      const newer=Number.isSafeInteger(r.mode_epoch)&&r.mode_epoch>state.modeEpoch;
      if(ordered){state.orderedControl=true;state.connectionEpoch=r.connection_epoch;state.controlSeq=r.control_seq}
      if(Number.isSafeInteger(r.mode_epoch))state.modeEpoch=r.mode_epoch;
      if(Number.isInteger(r.managed_dialogs))state.managed=r.managed_dialogs;
      state.auto=r.auto_enabled===true;state.autoAvailable=r.auto_available===true;
      // A manual approval can rotate this nonce without changing mode. An
      // older heartbeat must not restore the consumed approval capability.
      if(action!=='personal_heartbeat'||newer||!state.nonce)state.nonce=r.activation_nonce||state.nonce;
      state.policy=r.policy_version||state.policy;
      const a=r.research_auto;
      state.apiAllowance=a?.available===true&&a.active===true&&Number.isInteger(a.limit)&&a.limit>=4&&a.limit<=4096
        &&Number.isInteger(a.remaining_calls)&&a.remaining_calls>=0&&a.remaining_calls<=a.limit
        ?{limit:a.limit,remaining:!newer&&state.apiAllowance?.limit===a.limit?Math.min(state.apiAllowance.remaining,a.remaining_calls):a.remaining_calls,
          blocked:a.blocked===true||!newer&&state.apiAllowance?.blocked===true}:null;
      return true;
    };
    async function identity() {
      const me=await deps.getIdentity();
      if(!me||!me.id)throw Error('Войдите в свой аккаунт LeadChat');
      if(state.principal&&String(me.id)!==state.principal)throw Error('Аккаунт LeadChat изменился. Подключите помощника заново');
      return {...me,id:state.operator||String(me.id),principal_id:String(me.id)};
    }
    async function prepare(){
      const me=await deps.getIdentity();if(!me?.id)throw Error('Войдите в LeadChat');
      if(state.active&&state.principal!==String(me.id)){await stop('actor_changed');state.operator=''}
      state.principal=String(me.id);
      if(deps.getAuthors&&me.role==='admin'){
        const caps=await deps.getAuthors();
        if(caps.principal?.id!==state.principal||!Array.isArray(caps.authors))throw Error('Не подтверждён список сотрудников');
        state.authors=caps.authors;state.delegated=true;
      }else{state.authors=[];state.delegated=false}
      if(!state.operator)state.operator=state.principal;
      state.name=state.authors.find(a=>a.id===state.operator)?.full_name||me.full_name||me.name||'';
      emit();return me;
    }
    async function selectAuthor(id){
      if(!state.authors.some(a=>String(a.id)===String(id)))throw Error('Выберите действующего сотрудника');
      await stop('actor_changed');proof=null;state.operator=String(id);state.name=state.authors.find(a=>a.id===state.operator).full_name;
      state.rows=[];state.lastConfirmedAt=null;note('Автор изменён. Для работы подключите сессию и включите авто заново');emit();
    }
    async function start() {
      if(state.busy)return;
      const generation=++epoch;state.busy=true;state.error='';emit();
      const work=startQueue.then(()=>startSession(generation));startQueue=work.catch(()=>{});return work;
    }
    async function startSession(generation) {
      if(generation!==epoch)return;
      try {
        // Reconnect revokes the previous page's actor attestation. In-flight
        // starts are serialized through their scoped cleanup before a new one.
        proof=null;proofPending=null;
        Object.assign(state,{orderedControl:false,connectionEpoch:0,controlSeq:0,modeEpoch:0});
        await prepare();
        if(generation!==epoch)return;
        const originalActor=state.operator,originalPrincipal=state.principal;
        const confirmed=await confirm('personal_start',{max_dialogs:state.max,control_protocol:'ordered_v1'}),r=confirmed.response;
        if(generation!==epoch){
          // The response may belong to an older connection. A blanket stop
          // here could disconnect the new actor/session selected meanwhile.
          if(state.operator===originalActor&&state.principal===originalPrincipal
              &&Number.isSafeInteger(r.mode_epoch)&&r.mode_epoch>0)
            await call('personal_stop',{expected_mode_epoch:r.mode_epoch,stop_reason:'stale_start_cleanup',
              ...(r.control_protocol==='ordered_v1'?{connection_epoch:r.connection_epoch,control_seq:r.control_seq+1}:{})}).catch(()=>{});
          return;
        }
        state.active=!!r.active;state.name=r.owner_name||state.name;state.max=r.max_dialogs;
        if(state.active)acceptLease(confirmed);
        absorb(r,'personal_start');
        if(deps.onStart)await deps.onStart();
        if(generation!==epoch)return;
        if(!checkLease())return;
        if(deps.startPulse){
          const id=crypto.randomUUID();pulseId=id;
          let registrationTimer;
          const pendingRegistration=Promise.resolve().then(()=>deps.startPulse(id));
          pendingRegistration.then(()=>{if(generation!==epoch||pulseId!==id)unregister(id)},()=>{});
          let registration;
          try{registration=await Promise.race([pendingRegistration,new Promise((_,reject)=>{
            registrationTimer=setTimeout(()=>reject(Error('Фоновая проверка связи не ответила')),
              Math.max(1,Math.min(12000,state.leaseExpiresAt-Date.now())));
          })])}finally{clearTimeout(registrationTimer)}
          if(generation!==epoch){unregister(id);return}
          if(registration?.ok!==true||registration.connection_id!==id)throw Error('Фоновая проверка связи не подключена');
          if(!checkLease())return;
        }
        note('Подключена личная проверка. Автоматические действия выключены');
        clearInterval(timer);timer=setInterval(heartbeat,15000);
      } catch(e){if(generation===epoch){clearPulse();state.error=String(e.message||e);state.active=false;state.auto=false;state.nonce='';state.apiAllowance=null;state.connection.phase='stopped'}}
      finally{if(generation===epoch){state.busy=false;emit()}}
    }
    async function stop(reason='user_disconnect') {
      const ordered=state.orderedControl,control=controlArgs();
      if(!ordered&&state.modeEpoch>0)control.expected_mode_epoch=state.modeEpoch;
      const generation=++epoch;wakeProofReaders();clearInterval(timer);timer=0;clearPulse();const was=state.active;
      state.active=false;state.auto=false;state.apiAllowance=null;state.nonce='';state.busy=was;state.rows=[];state.checked=0;state.error='';emit();
      state.offset=0;state.more=false;queueKey='';
      if(was){
        const allowed=['user_disconnect','panel_closed','panel_not_visible','actor_changed','stale_start_cleanup','unreported'];
        note('Личная проверка остановлена');
        await call('personal_stop',{...control,stop_reason:allowed.includes(reason)?reason:'unreported'}).catch(()=>{})
      }
      if(generation===epoch){state.busy=false;emit()}
    }
    async function heartbeat(trigger='timer') {
      if(!checkLease())return;
      if(deps.visible&&!deps.visible()){await stop('panel_not_visible');return}
      if(heartbeatPending?.epoch===epoch)return heartbeatPending.promise;
      const generation=epoch,entry={epoch:generation,promise:null};heartbeatPending=entry;
      const started=Date.now();state.connection={phase:'identity',trigger,startedAt:started,completedAt:null,durationMs:null};
      entry.promise=(async()=>{
        let deadline;
        const live=()=>generation===epoch&&checkLease();
        const operation=(async()=>{
          await identity();if(!live())return null;
          state.connection.phase='server';return confirm('personal_heartbeat');
        })();
        try{
          const confirmed=await Promise.race([operation,new Promise((_,reject)=>{
            deadline=setTimeout(()=>reject(Error('Проверка связи заняла слишком долго. Сессия остановлена')),
              Math.max(1,Math.min(12000,state.leaseExpiresAt-started)));
          })]);
          if(!confirmed||!live())return;
          const r=confirmed.response;if(!r.active)throw Error('Личная сессия истекла');
          acceptLease(confirmed);absorb(r,'personal_heartbeat');
          state.connection={phase:'confirmed',trigger,startedAt:started,completedAt:Date.now(),durationMs:Math.max(0,Date.now()-started)};emit();
        }
        catch(e){if(generation===epoch)loseConnection(String(e.message||e))}
        finally{clearTimeout(deadline);if(heartbeatPending===entry)heartbeatPending=null}
      })();
      return entry.promise;
    }
    async function scan(priorityIds=[],onReady) {
      if(!checkLease()||state.busy)return;
      const generation=epoch;state.busy=true;state.error='';state.checked=0;emit();
      try{
        await identity();const data=await deps.loadQueue({offset:state.offset,priorityIds});
        if(!data||!Number.isInteger(data.mineCount)||data.mineCount<0||!Array.isArray(data.rows))throw Error('Не удалось подтвердить текущую нагрузку');
        if(data.paged&&(!Number.isInteger(data.nextOffset)||data.nextOffset<0||typeof data.more!=='boolean'))throw Error('Не подтверждена пагинация очереди');
        if(generation!==epoch)return;
        if(data.queueChanged){const reason='Состав очереди изменился: следующая проверка с начала';note(reason);await Promise.resolve(deps.logEvent?.('__queue__','skipped',{reason,operation:'queue_read_retry'})).catch(()=>{})}
        if(generation!==epoch)return;
        state.mine=data.mineCount;state.total=data.total||data.rows.length;
        const unique=[...new Map(data.rows.filter(r=>r&&r.id).map(r=>[r.id,r])).values()];
        const rows=unique.filter(r=>!r.assigneeId||String(r.assigneeId)===state.operator);
        const key=rows.map(r=>r.id).join('|');
        if(!data.paged&&(key!==queueKey||state.offset>=rows.length))state.offset=0;
        queueKey=key;const start=state.offset;
        const normal=data.paged?rows.slice(0,12):rows.slice(start,start+12),priority=new Set(Array.isArray(priorityIds)?priorityIds:[]);
        const batch=[...new Map([...rows.filter(r=>priority.has(r.id)),...normal].map(r=>[r.id,r])).values()].slice(0,12),slots=[];let next=0,closed=false;
        const current=()=>generation===epoch&&!closed&&checkLease();
        async function worker(){
          try{while(current()&&next<batch.length){
            const index=next++,row=batch[index];let screen;
            try{
              const hold=await deps.held?.(row.id);
              if(hold){screen={eligible:false,scope:row.assigneeId?'mine':'free',step:'handoff',needs_operator:true,human_hold:hold,reason:hold.reason,admission:'human_hold'}}
              else if(!row.assigneeId&&state.max>0&&state.managed>=state.max){screen={eligible:false,scope:'free',reason:'Достигнут личный лимит диалогов',admission:'capacity'};await deps.logEvent?.(row.id,'skipped',{reason:screen.reason})}
              else{
                const ctx=await readHistory(row.id);if(!current())return;
                screen=await deps.intakeGuard?.(ctx);
                if(!screen)screen=fail(await call('screen',{ctx,mine_count:state.mine}));
                if(Number.isInteger(screen.managed_dialogs))state.managed=screen.managed_dialogs;
              }
            }catch(e){
              if(e?.status===401||e?.code==='logout')throw e;
              screen={eligible:false,needs_operator:true,step:'handoff',scope:row.assigneeId?'mine':'free',
                reason:'Не удалось проверить этот диалог: '+String(e.message||e),admission:'history_unavailable'};
              await Promise.resolve(deps.logEvent?.(row.id,'read_error',{error:screen.reason})).catch(()=>{});
            }
            if(!current())return;
            slots[index]={id:row.id,name:row.name||'Клиент',...screen};state.rows=slots.filter(Boolean);state.checked=state.rows.length;emit();
            onReady?.(slots[index]);
          }}catch(e){closed=true;throw e}
        }
        await Promise.all(Array.from({length:Math.min(3,batch.length)},worker));
        if(generation===epoch){state.offset=data.paged?data.nextOffset:start+normal.filter(r=>batch.some(b=>b.id===r.id)).length;state.more=data.paged?data.more:state.offset<rows.length}
        if(generation===epoch)note('Проверено '+state.checked+' диалогов: подходят '+state.rows.filter(r=>r.eligible).length+'. Никто не взят');
      }catch(e){if(generation===epoch){state.error=String(e.message||e);await deps.logEvent?.('__queue__','read_error',{error:state.error}).catch(()=>{})}}
      finally{if(generation===epoch){state.busy=false;emit()}}
    }
    async function setMode(mode){
      if(!checkLease()||deps.visible&&!deps.visible())throw Error('Подключите личную сессию в видимой вкладке');
      const generation=epoch,ordered=state.orderedControl,control=controlArgs();
      await identity();if(generation!==epoch||!checkLease())throw Error('Личная сессия истекла');
      const r=fail(await call('personal_mode',{...control,execution_mode:mode,confirmed:mode==='auto',activation_nonce:state.nonce,policy_ack:state.policy,client_version:'2.7.0'}));
      if(generation!==epoch||!checkLease())throw Error('Сессия изменилась во время проверки режима');
      if(ordered&&control.control_seq!==state.controlSeq)throw Object.assign(Error('Команда режима заменена более новой'),{code:'personal_control_obsolete'});
      absorb(r,'personal_mode');emit();return r;
    }
    async function pulse(id){
      if(!pulseId||id!==pulseId)return {ok:false,active:false};
      if(checkLease()&&Date.now()-state.lastConfirmedAt>=10000)await heartbeat('alarm');
      return {ok:true,active:checkLease(),connection_id:id};
    }
    return {state,start,stop,scan,heartbeat,setMode,prepare,selectAuthor,identity,identityArgs,withIdentity,identityCall,call,checkLease,pulse};
  }
  return {create};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=LC_PERSONAL;
