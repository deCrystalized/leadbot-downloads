/* Browser executor. Every write needs the explicitly enabled owner session.
   No server sender or persisted browser enable flag. */
const LC_WORKFLOW = (() => {
  function callerIdCallReview(result){
    const p=result?.caller_id_callback;
    if(result?.ok!==true||result.auto_enabled!==false||p?.rule_id!=='OWNER-CALLER-ID-SAVE-CALLBACK-20261024'
       ||p.execution_allowed!==false||p.call_executed!==false)return null;
    if(p.status==='client_reported_visible')return {status:'Клиент сообщил, что видит номер',instruction:'Повторный дозвон для сохранения номера не предлагать.',phone:'',timing:[]};
    if(p.status==='cancelled')return {status:'Клиент отменил звонок',instruction:'Не звонить без нового запроса клиента.',phone:'',timing:[]};
    if(!['awaiting_contact','operator_review'].includes(p.status))return null;
    return {status:p.customer_contact_verified?'Дозвон для сохранения номера':'Нужен номер клиента',
      phone:p.customer_contact_verified?String(p.contact_phone||''):'',
      timing:(p.timing_constraints||[]).map(x=>String(x.quote||'')).filter(Boolean),
      instruction:p.customer_contact_verified
        ?'Проверьте получателя и удобное время. Если можете позвонить: «Пару минут, наберу вам», затем позвоните клиенту. Звонок ещё не выполнен.'
        :'Сначала получите номер клиента. Свой номер текстом не отправляйте.'};
  }
  function draftDirection(draft,revision){
    if(draft?.ok!==true||draft.auto_enabled!==false||draft.revision!==revision||!['kp','bt','mnc'].includes(draft.routing?.direction))throw Error('Мозг не подтвердил направление текущего диалога');
    return draft.routing.direction;
  }
  function formExtraction(result,revision){
    draftDirection(result,revision);
    if(result.intake_form_ready!==true||!/^\w{64}$/.test(result.form_reference||'')
       ||!result.research_job_id||result.form_extraction?.ok!==true||!result.form_extraction.lead?.problem)
      throw Object.assign(Error('Нет подтверждённой сути работ для текущей формы'),{code:'research_stopped'});
    const extraction=JSON.parse(JSON.stringify(result.form_extraction));
    // Native forms use the same confirmed client-contact projection as the
    // existing manual form. Keep the accepted model result immutable.
    extraction.lead.service_comment=serviceContactComment(extraction.lead.service_comment,result.facts);
    return extraction;
  }
  function crmPrepareArgs(dir,lead,draft){
    if(draft?.routing?.direction&&draft.routing.direction!==dir)throw Error('Направление формы не соответствует мозгу');
    if(draft?.lead?.partner&&String(lead.partner)!==String(draft.lead.partner))throw Error('Партнёр формы не соответствует источнику, проверенному мозгом');
    const args={dir,phone:lead.phone,city:lead.city,topics:lead.topics,partner:lead.partner,problem:lead.problem,device:lead.device||''};
    const route=draft?.crm_route;
    if(route){
      if(route.mixed_work||!route.city_id||!route.city_text)throw Error('Маршрут филиала требует оператора');
      // Keep the physical city in the address/map. No generic-city fallback.
      args.cityId=String(route.city_id);args.city=route.city_text;
    }
    return args;
  }
  function contactComment(comment,facts){
    const scope=facts?.mixed_optional_work;
    let text=String(comment||'');
    if(scope?.rule_id==='OWNER-MIXED-OPTIONAL-LOOK-20261023'&&Array.isArray(scope.extras)){
      // Replace only our managed conditional line. Other operator notes stay.
      // A withdrawn extra must not survive in an older editable draft.
      text=text.split(/\r?\n/).filter(line=>line===scope.comment||
        !/^Дополнительно — по возможности посмотреть .+; выполнение работ не подтверждено\.$/.test(line)).join('\n');
    }
    const lines=Array.isArray(facts?.comment_lines)?facts.comment_lines:[];
    return [text,...lines.filter(line=>typeof line==='string'&&line.trim()&&!text.includes(line))].filter(Boolean).join('\n');
  }
  function serviceContactComment(comment,facts){
    const text=String(comment||''),i=facts?.service_comment_instruction,phone=facts?.contact_phone_to_use;
    if(!i||i.source!=='client_message'||i.rule_id!=='OWNER-CONTACT-FIRST-LINE-20261023'
       ||!i.message_id||!i.quote||i.phone!==phone||facts.phone_needs_confirmation!==false
       ||!/^\+7\d{10}$/.test(phone)||!facts.phone_values?.includes(phone))return text;
    const line='Звонить на '+phone;
    return [line,...text.split(/\r?\n/).filter(x=>x.trim()!==line)].filter(Boolean).join('\n');
  }
  function projectAcceptedVisit(lead,reviewed,now=Date.now()){
    const window=reviewed?.accepted_visit;
    if(!window)return lead;
    if(reviewed.ok!==true||reviewed.auto_enabled!==false||!reviewed.policy_version
       ||window.source!=='authorized_extension_reply'||window.appointment_created!==false
       ||!window.proposal_message_id||!window.answer_message_id||!window.operation_id
       ||!window.proposal_quote||!window.answer_quote||!Number.isInteger(window.min_minutes)
       ||window.min_minutes<=0||!Number.isFinite(window.earliest_at)||!Number.isFinite(window.latest_at))throw Error('Согласованное окно не подтверждено мозгом');
    const clock=Math.ceil(Math.max(window.earliest_at*1000,now+window.min_minutes*60000)/60000)*60000;
    if(clock>window.latest_at*1000)throw Error('В согласованное окно уже не успеваем. Нужна проверка времени');
    const parts=stamp=>Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:window.timezone,
      year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(stamp)).map(x=>[x.type,x.value]));
    const p=parts(clock),end=parts(window.latest_at*1000),date=`${p.year}-${p.month}-${p.day}`,time=`${p.hour}:${p.minute}`;
    return {...lead,visit_date:date,visit_time:time,visit_auto:null,
      time_window:{date,from:time,until:`${end.hour}:${end.minute}`,text:window.proposal_quote},
      time_text:window.proposal_quote,accepted_visit:window};
  }
  function callbackComment(lead){
    const out={...lead},line='Прозвон: время с клиентом не согласовано, указано ближайшее по нормативу филиала.';
    const derived=lead.visit_auto;
    const pending=lead.call_check===true&&derived?.kind==='прозвон'
      &&derived.date===lead.visit_date&&derived.time===lead.visit_time;
    if(pending){
      const lines=String(lead.comment||'').split('\n');
      if(!lines.includes(line))lines.push(line);
      out.comment=lines.filter(Boolean).join('\n');
      out.callback_comment_auto=line;
    }else if(lead.callback_comment_auto===line){
      out.comment=String(lead.comment||'').split('\n').filter(s=>s!==line).join('\n');
      delete out.callback_comment_auto;
    }
    return out;
  }
  function territoryIssue(territory,lead,options={}){
    if(territory?.mismatch||territory?.qualified_location_unverified)return territory.error||'Адрес не совпадает с выбранным городом: проверьте адрес и филиал по карте';
    const address=lead?.addr||{};
    if(options.beforeApproval&&!(territory?.ok&&territory.address_verified===true)&&options.clientLocation?.status!=='confirmed')return 'До согласования нужно определить город клиента: проверьте полный адрес по карте или уточните город';
    if(!address.settlement)return '';
    if(!territory?.ok||territory.address_verified!==true||!territory.checkedAddress)return 'Населённый пункт или микрорайон ещё не проверен вместе с улицей и домом: проверьте адрес и город по карте';
    const norm=v=>String(v||'').toLowerCase().replace(/ё/g,'е').replace(/\s+/g,' ').trim();
    for(const k of ['settlement','street','building']){
      const allowed=[territory.checkedAddress[k],...(k==='settlement'?[territory.verifiedSettlement]:[])].map(norm);
      if(!allowed.includes(norm(address[k])))return 'Адрес изменился после проверки карты: повторно проверьте адрес и филиал';
    }
    return '';
  }
  function manualCreationReview(check,territory,lead){
    const permission=check?.manual_creation;
    const available=check?.ok===true&&check.reviewed_policy===true&&check.auto_enabled===false
      &&permission?.available===true&&permission.mode==='operator_confirmed'&&permission.auto_enabled===false
      &&permission.acknowledgement==='operator_decision_not_client_consent';
    const warnings=[];
    const add=t=>{t=String(t||'').trim();if(t&&!warnings.includes(t))warnings.push(t);};
    if(check?.hard_block)add(check.refuse||check.reason||check.operator_review||'Замечание регламента');
    add(check?.operator_review);add(check?.approval);add(check?.refuse);
    for(const row of check?.results||[])if(!row.done)add(row.item);
    add(territoryIssue(territory,lead));
    return {available,warnings,policy_version:check?.policy_version||'',rule_ids:[...(check?.rule_ids||[])]};
  }
  function projectContactFacts(extracted,reviewed,rejected=[]){
    // Initial preparation only: never reapply over a form the operator edited.
    // Server evidence, not a model's guessed contact, determines shared fields.
    if(reviewed?.ok!==true||reviewed.reviewed_policy!==true||reviewed.auto_enabled!==false||!reviewed.facts)throw Error('Мозг не подтвердил факты для формы заявки');
    const facts=reviewed.facts,evidence=facts.evidence||{},lead={...extracted.lead},checks=[...(extracted.checks||[])];
    const digits=v=>String(v||'').replace(/\D/g,'').replace(/^[78](?=\d{10}$)/,'');
    const blocked=new Set(rejected.map(digits));
    const check=(field,ok,note)=>{const i=checks.findIndex(x=>x.field===field),v={field,ok,note};if(i<0)checks.push(v);else checks[i]=v};
    const graphics=facts.graphics_scope;
    if(graphics?.kind==='host_diagnostic'&&graphics.component_fault_confirmed===false
       &&graphics.source==='client_message'&&graphics.message_id&&graphics.quote){
      // A supplied GPU is part of the reported PC diagnostic task. Correct
      // only that model-guessed item; independent jobs and source wording stay.
      if(!lead.device||/видеокарт|\bgpu\b/i.test(lead.device)){
        lead.device='компьютер';check('device',true,'Диагностика компьютера со слов клиента');
      }
      lead.topics=[...new Set([...(lead.topics||[]).map(t=>/^\s*(?:(?:ремонт|диагностика)\s+)?(?:видеокарт[а-яё]*|gpu)\s*$/i.test(String(t))?'компьютер':t),'компьютер'])];
    }
    const phone=digits(facts.contact_phone_to_use);
    if(facts.phone_needs_confirmation||blocked.has(phone)){
      lead.phone='';lead.phone_confirm=true;lead.phone_risky='';lead.phone_warn='Телефон требует проверки по переписке';
      check('phone',false,lead.phone_warn);
    }else if(/^\d{10}$/.test(phone)&&evidence.contact_phone_to_use?.message_id){
      lead.phone=phone;lead.phone_confirm=false;lead.phone_risky='';lead.phone_warn='';
      let extras=(lead.phones_extra||[]).filter(p=>digits(p)!==phone&&!blocked.has(digits(p)));
      if(facts.phone_selection?.kind==='explicit_correction'){
        const old=new Set((facts.phone_values||[]).map(digits)),backup=new Set((facts.fallback_phones||[]).map(p=>digits(p.value)));
        extras=extras.filter(p=>!old.has(digits(p))||backup.has(digits(p)));
        lead.phones_pending=[];lead.phones_notes=[];lead.phones_hint='';
      }
      lead.phones_extra=extras;check('phone',true,'Номер подтверждён сервером по переписке');
      if(evidence.contact_phone_to_use.signature){
        const proven=new Set((facts.phone_values||[]).map(digits));
        lead.phones_extra=extras.filter(p=>proven.has(digits(p)));
      }
    }else if(Object.prototype.hasOwnProperty.call(facts,'contact_phone_to_use')){
      lead.phone='';lead.phone_confirm=false;lead.phone_risky='';lead.phone_warn='Номер в переписке не подтверждён';
      lead.phones_extra=[];lead.phones_pending=[];
      check('phone',false,lead.phone_warn);
    }
    const address=facts.address||{};
    const referenceOnly=facts.worksite_address_pending===true&&!address.building
      &&(facts.address_references||[]).some(r=>['meeting','landmark','previous'].includes(r.role)&&r.message_id&&r.quote&&r.worksite_verified===false);
    if(referenceOnly){
      // The legacy extractor may have promoted this reference into a worksite.
      // Keep the source quote in the comment; initial form preparation must
      // not silently retain that guessed street/house or its access details.
      lead.addr=Object.fromEntries(Object.entries(address).filter(([k,v])=>v&&evidence['address.'+k]?.message_id));
      lead.address='';lead.addr_full=false;lead.addr_echo='';lead.addr_other=[];delete lead.addr_prev;
      lead.addr_warn=(facts.address_references||[]).some(r=>r.role==='previous')?'Указан прежний адрес, нужен адрес работ':'Указан ориентир, нужен адрес работ';check('address',false,lead.addr_warn);
    }else if(facts.address_needs_confirmation){
      lead.addr_warn='Адрес в переписке требует проверки';check('address',false,lead.addr_warn);
    }else if(address.building&&(address.street||address.settlement||address.area)
             &&evidence['address.building']?.message_id){
      lead.addr=Object.fromEntries(Object.entries(address).filter(([k])=>evidence['address.'+k]?.message_id));
      lead.address=[lead.addr.settlement,lead.addr.street,lead.addr.building].filter(Boolean).join(', ');
      lead.addr_warn='';lead.addr_echo='';lead.addr_other=[];delete lead.addr_prev;
      const labels={кв:'office',подъезд:'entrance',этаж:'floor',домофон:'intercom'};
      lead.addr_need=(lead.addr_need||[]).filter(label=>!lead.addr[labels[label]]);lead.addr_full=!lead.addr_need.length;
      check('address',true,'Адрес со слов клиента; проверка картой выполняется отдельно');
    }
    for(const row of facts.uncertain_address_fields||[]){
      if(row.field!=='entrance'||row.verified!==false||row.source!=='client_message'||!row.message_id||!row.quote||address.entrance)continue;
      // Even during an unresolved worksite conflict, a client-retracted
      // entrance must not survive in the initial model draft.
      lead.addr={...(lead.addr||{})};delete lead.addr.entrance;lead.addr_echo='';
    }
    if(Object.prototype.hasOwnProperty.call(facts,'intercom_present')){
      lead.addr={...(lead.addr||{}),has_intercom:null};
      if(typeof facts.intercom_present==='boolean'&&evidence.intercom_present?.message_id){
        lead.addr.has_intercom=facts.intercom_present;
      }
      if(lead.addr.has_intercom!==true&&typeof lead.addr.intercom==='boolean')lead.addr.intercom=false;
    }else if(lead.addr&&Object.prototype.hasOwnProperty.call(lead.addr,'has_intercom')){
      lead.addr={...lead.addr};delete lead.addr.has_intercom;
    }
    if(facts.call_before_visit)lead.call_before_visit=true;
    if(!String(lead.problem||'').trim()&&/кроват/i.test(facts.active_service_scope?.quote||'')){
      const detail=(facts.task_notes||[]).find(n=>n.kind==='bed_part_damage'&&n.written===true&&n.message_id&&n.source==='client_message'&&n.quote);
      if(detail){
        lead.problem=String(detail.quote).replace(/^\s*(?:добрый\s+день|здравствуйте)[,!\.\s]*/i,'').trim();
        lead.problem_evidence={message_id:detail.message_id,quote:detail.quote};
        check('problem',true,'Описание ремонта сохранено из письменного сообщения клиента');
      }
    }
    lead.comment=contactComment(lead.comment,facts);
    if(facts.service_comment_instruction)lead.service_comment=serviceContactComment(lead.service_comment,facts);
    return {...extracted,lead,checks,contact_facts:facts,policy_version:reviewed.policy_version,auto_enabled:false};
  }
  function readIntercomField(address,input){
    const prior=address||{},out={intercom:input?!!input.checked:prior.intercom||false};
    if(input?.indeterminate){out.has_intercom=null;return out;}
    if(Object.prototype.hasOwnProperty.call(prior,'has_intercom')){
      out.has_intercom=typeof prior.has_intercom==='boolean'&&input?!!input.checked:prior.has_intercom;
    }
    if(input?.checked)out.has_intercom=true;
    return out;
  }
  async function waitForDelivery({clientId,initial,read,wait=ms=>new Promise(r=>setTimeout(r,ms)),now=Date.now,timeoutMs=8000}){
    const result=m=>({id:m?.id||initial?.id||'',client_message_id:clientId,delivery_status:m?.delivery_status||'unknown'});
    if(!initial?.id||initial.client_message_id!==clientId||initial.direction!=='out')return{confirmed:false,result:result(initial)};
    const deadline=now()+timeoutMs;let message=initial,delay=250;
    for(;;){
      if(['sent','delivered','read'].includes(message?.delivery_status))return{confirmed:true,result:result(message)};
      if(message?.delivery_status==='failed'||now()>=deadline)return{confirmed:false,result:result(message)};
      try{const page=await read();message=Array.isArray(page?.items)?page.items.find(m=>m.id===initial.id&&m.client_message_id===clientId&&m.direction==='out'):null}
      catch(e){return{confirmed:false,result:{...result(message),error:String(e.message||e)}}}
      if(['sent','delivered','read','failed'].includes(message?.delivery_status))continue;
      const remaining=deadline-now();if(remaining<=0)return{confirmed:false,result:result(message)};
      await wait(Math.min(delay,remaining));delay=Math.min(delay*2,3000);
    }
  }
  async function readHistory(first,loadOlder,limit=300){
    let page=first;const rows=new Map(),cursors=new Set();
    for(;;){
      if(!Array.isArray(page?.items)||typeof page?.page?.has_more_before!=='boolean')throw Error('Не подтверждена полнота переписки');
      for(const m of page.items){if(!m?.id)throw Error('Нет номера сообщения');if(!rows.has(m.id))rows.set(m.id,m)}
      if(rows.size>limit||rows.size===limit&&page.page.has_more_before)throw Error('Переписка длиннее 300 сообщений — нужен оператор, обрезать её нельзя');
      if(!page.page.has_more_before)break;
      const cursor=page.page.prev_cursor;if(!cursor||cursors.has(cursor))throw Error('Не удалось дочитать всю переписку');cursors.add(cursor);
      page=await loadOlder(cursor);
    }
    return [...rows.values()].sort((a,b)=>(Date.parse(a.created_at)-Date.parse(b.created_at))||String(a.id).localeCompare(String(b.id)));
  }
  const humanHoldKey=(operator,id)=>{
    if(!/^[\w-]{1,100}$/.test(String(operator||''))||!/^[\w-]{1,100}$/.test(String(id||'')))throw Error('Не подтверждён владелец паузы');
    return 'human-hold:'+operator+':'+id;
  };
  const humanResult=hold=>({step:hold.result_step==='created_review'?'created_review':'handoff',needs_operator:true,
    reason:hold.reason,human_hold:hold,paused:true});
  async function releaseHumanHold(deps,operator,id,receipt){
    if(receipt?.ok!==true||receipt.id!==id||receipt.operator_id!==operator||receipt.state!=='waiting'||!Number.isInteger(receipt.version))
      throw Error('Нет подтверждённого ручного возврата боту');
    const key=humanHoldKey(operator,id);
    return deps.lock(key,async()=>{const hold=await deps.read(key);if(!hold||hold.state==='done')return false;
      if(hold.state!=='held'||Number.isInteger(hold.native_version)&&receipt.version<=hold.native_version)
        throw Error('Подтверждение возврата устарело');
      await deps.save(key,{...hold,state:'done',released_at:Date.now(),release_version:receipt.version});return true;
    });
  }
  function create(deps) {
    let generation=0;
    const research=new Map();
    const check=(value)=>{
      if(!value||value.ok===false){
        // Keep the server's category through the browser controller. A failed
        // technical gate is not evidence that this customer needs takeover.
        const error=Error(value?.error||'Проверка не пройдена');
        if(typeof value?.code==='string')error.code=value.code;
        throw error;
      }
      return value;
    };
    const stop=()=>{generation++;
      for(const saved of research.values())if(deps.research)Promise.resolve(deps.research('research_cancel',saved.s,saved.args)).then(r=>{
        if(r?.ok===false&&r.code!=='research_stopped')deps.onResearchCancelError?.('Серверная отмена исследования не подтверждена; проверьте журнал');
      }).catch(()=>deps.onResearchCancelError?.('Результат отмены исследования неизвестен; повторная генерация не запускалась'));
      research.clear();
    };
    const valid=(g)=>{if(g!==generation||deps.visible?.()===false)throw Error('Цепочка остановлена')};
    const researching=value=>value?.pending_research===true||value?.requires_root===true
      ||['queued','running','awaiting_root'].includes(value?.research_state);
    const researchVeto=(value,form=false)=>value?.research_state==='rejected'
      ?{step:'handoff',needs_operator:true,research_state:'rejected',research_job_id:value.research_job_id,
        reason:(form?'Описание заявки не прошло':'Ответ не прошёл')+' отдельную проверку. Откройте журнал той же задачи'}:null;
    const researchWait=value=>{
      const stages={queued:'Ожидает очереди проверки',preparing_context:'Изучает историю и правила',
        generating:'Готовит ответ',reviewing:'Проверяет ответ',validating:'Проверяет полученный результат',
        awaiting_review:'Ответ подготовлен и ожидает контрольной проверки',ready:'Ответ подготовлен',
        finalizing:'Завершает подготовку ответа',uncertain:'Результат запроса уточняется'};
      const stage=value.progress?.stage,seconds=value.progress?.elapsed_seconds;
      let reason=value.research_state==='source_changed'?'Диалог изменился. Следующая проверка прочитает его заново'
        :value.research_state==='waiting_turn'?'Ожидает очереди проверки'
        :value.pending_admission?'Ожидается допуск контролируемой API-проверки'
        :value.requires_root?'Ответ подготовлен и ожидает контрольной проверки'
        :Object.hasOwn(stages,stage)?stages[stage]:'Бот изучает историю и проверяет основания ответа';
      if(Object.hasOwn(stages,stage)&&Number.isInteger(seconds)&&seconds>=0&&seconds<=300)
        reason+=' · прошло '+Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0');
      return {step:'wait',needs_operator:false,research_job_id:value.research_job_id,
        research_state:value.research_state,reason};
    };
    async function previewModel(s,p,g,form=false){
      const id=JSON.stringify([s.operatorId,s.ctx.convId,form?'form':'reply']),saved=research.get(id);let value;
      if(saved){
        if(!deps.research)throw Error('Не подключена проверка сохраняемой задачи');
        if(saved.args.revision!==p.revision){
          const cancelled=await deps.research('research_cancel',s,saved.args);valid(g);research.delete(id);
          if(cancelled?.ok===false&&cancelled.code!=='research_stopped')throw Error('Отмена устаревшего исследования не подтверждена');
          return {ok:true,pending_research:true,research_state:'cancelled',research_job_id:saved.args.research_job_id};
        }
        value=await deps.research('research_status',s,saved.args);valid(g);
        if(value?.research_state==='accepted'){value=await deps.research('research_finalize',s,{...saved.args,research_job_id:value.research_job_id});valid(g)}
      }else{value=await (form?deps.formPreview(s):deps.preview(s));valid(g)}
      if(value?.refresh_preview===true&&value?.research_state==='source_changed'){
        research.delete(id);
        return {ok:true,pending_research:true,research_state:'source_changed',needs_operator:false,
          reply:'',auto_enabled:false,can_send_or_create:false};
      }
      if(value?.visual_observation_ready===true){
        research.delete(id);
        return {ok:true,action:'wait',reply:'',needs_operator:false,visual_observation_ready:true,
          reason:'Изображение проверено; следующий проход заново оценит текущий диалог'};
      }
      if(value?.research_state==='waiting_turn'){
        // No job/grant/provider attempt exists yet. Keep this as a queue wait,
        // never a status cursor or an operator failure. An existing job must
        // not disappear into this path and become a new generation later.
        if(saved||value.pending_research!==true||value.research_job_id||!value.request_id||value.revision!==p.revision)
          throw Error('Не подтверждена очередь задачи текущего диалога');
        return value;
      }
      if(researching(value)){
        if(!deps.research||(!value.research_job_id&&!value.pending_admission)||!value.request_id||value.revision!==p.revision)throw Error('Не подтверждена сохраняемая задача текущего диалога');
        research.set(id,{s,args:{research_job_id:value.research_job_id,request_id:value.request_id,revision:value.revision}});
      }else research.delete(id);
      return value;
    }
    async function held(id,operator=deps.operator?.()){
      if(!operator)return null;
      const row=await deps.read(humanHoldKey(operator,id));
      if(row?.state==='held')return row;
      if(row&&row.state!=='done')throw Error('Состояние ручной паузы не подтверждено');
      return null;
    }
    async function park(id,result,operator=deps.operator?.()){
      if(!result||!['handoff','created_review'].includes(result.step)&&result.needs_operator!==true)
        throw Error('Ожидание не требует передачи человеку');
      const key=humanHoldKey(operator,id);
      return deps.lock(key,async()=>{
        const previous=await held(id,operator);if(previous)return humanResult(previous);
        const hold={state:'held',operator,id,reason:String(result.reason||(result.reasons||[]).join('; ')||'Нужна проверка человека'),
                    result_step:result.step,at:Date.now(),native_sync:'pending'};
        await deps.save(key,hold); // Persist before any control request or next cycle.
        if(!deps.pauseForHuman)throw Error('Пауза сохранена локально, но серверная остановка не подтверждена');
        try{const receipt=await deps.pauseForHuman(id,operator,hold);
          if(receipt?.ok!==true||receipt.id!==id||receipt.operator_id!==operator||!['paused','completed'].includes(receipt.state))
            throw Error('Сервер не подтвердил остановку нужного диалога');
          hold.native_sync='confirmed';hold.native_version=receipt.version;await deps.save(key,hold);
        }catch(error){await deps.save(key,{...hold,native_sync:'unknown'});throw error}
        return humanResult(hold);
      });
    }
    async function audit(s,kind,data={},revision='') {
      if(deps.audit)check(await deps.audit(s,{kind,data,revision}));
    }
    async function snapshot(id,g) {
      valid(g);const s=await deps.snapshot(id);valid(g);
      if(!s?.operatorId||s.active!==true||!Number.isInteger(s.mineCount)||s.mineCount<0||s.ctx?.convId!==id)throw Error('Личная сессия или нагрузка не подтверждена');
      return s;
    }
    async function decision(id,g) {
      const s=await snapshot(id,g),p=check(await deps.plan(s));valid(g);
      if(p.operator_id!==s.operatorId||!p.revision)throw Error('Владелец или версия диалога не подтверждены');
      if(p.eligible&&['claim','reply','prepare_crm','inspect_media'].includes(p.step)){
        const guard=await deps.intakeGuard?.(s.ctx);valid(g);
        if(guard)return {s,p:{...p,...guard,operation_id:''}};
      }
      return {s,p};
    }
    // Only this new, durably recorded preflight outcome proves that no
    // transport began. Legacy blocked/aborted/pending writes remain ambiguous.
    function notStarted(entry,s,k){
      return entry?.state==='not_started'&&entry.transport_started===false&&entry.preflight_rejected===true
        &&!Object.prototype.hasOwnProperty.call(entry,'result')
        &&entry.operator===s.operatorId&&entry.conv===s.ctx.convId
        &&['claim','reply','create_crm','link_crm','rename_client','notify_created'].includes(entry.kind)
        &&typeof entry.operation_id==='string'&&!!entry.operation_id&&typeof entry.revision==='string'&&!!entry.revision
        &&Number.isFinite(entry.at)&&entry.at>0
        &&k===key(s.operatorId,s.ctx.convId,entry.kind,entry.kind==='create_crm'?'once':entry.operation_id);
    }
    const noStartError=(message,code='workflow_not_started')=>Object.assign(Error(message),{code});
    async function rejectBeforeTransport(k,entry,message,code,prepared){
      // A failed save must leave the old pending record conservative. Never
      // grant recovery merely because an in-memory rejection was observed.
      await deps.save(k,prepared?{...entry,state:'not_started',transport_started:false,preflight_rejected:true}
        :{...entry,state:'blocked'});
      throw noStartError(message,prepared?code:'workflow_permission');
    }
    async function inspect(id) {
      const hold=await held(id);if(hold)return {...humanResult(hold),preview_only:true,auto_enabled:false};
      const g=generation,{s,p}=await decision(id,g);
      const result={...p,preview_only:true,auto_enabled:false};
      if((await deps.pending(s.operatorId,id)).some(e=>!notStarted(e,s,e.key)))return {...result,step:'handoff',reason:'Результат предыдущего действия не подтверждён. Нужна ручная сверка, повтор запрещён'};
      const saved=await deps.read(key(s.operatorId,id,'create_crm','once'));valid(g);
      if(saved&&!notStarted(saved,s,key(s.operatorId,id,'create_crm','once'))){
        if(saved.state!=='done')return {...result,step:'handoff',reason:'Предыдущее создание требует ручной проверки; повтор запрещён'};
        const issue=receiptIssue(s,p,saved.result);if(issue)return {...result,...issue};
        const receipt=saved.result;
        for(const [kind,prefix] of [['link_crm','link'],['rename_client','rename'],['notify_created','notify']]){
          if(kind==='link_crm'&&String(s.ctx.crmRequestId||'')===String(receipt.id))continue;
          const op=prefix+':'+receipt.id,done=await deps.read(key(s.operatorId,id,kind,op));valid(g);
          if(done&&done.state!=='done'&&!notStarted(done,s,key(s.operatorId,id,kind,op)))return {...result,step:'handoff',reason:'Предыдущее служебное действие не подтверждено'};
          if(!done||notStarted(done,s,key(s.operatorId,id,kind,op)))return {...result,step:kind,operation_id:op,receipt,crm_id:receipt.id};
        }
        return {...result,step:'done',crm_id:receipt.id};
      }
      if(['reply','claim','inspect_media'].includes(p.step)) {
        const draft=check(await previewModel(s,p,g));valid(g);
        if(researching(draft))return {...result,...researchWait(draft)};
        if(researchVeto(draft))return {...result,...researchVeto(draft)};
        if(draft.visual_observation_ready)return {...result,step:'wait',needs_operator:false,reason:draft.reason};
        result.reply=draft.reply||'';result.needs_operator=!!draft.needs_operator;
        result.draft_id=draft.draft_id||'';
      }
      if(p.step==='prepare_crm') {
        const form=deps.formPreview?check(await previewModel(s,p,g,true)):null;valid(g);
        if(form&&researching(form))return {...result,...researchWait(form)};
        if(researchVeto(form,true))return {...result,...researchVeto(form,true)};
        const proposal=await deps.prepareCRM(s,p,form);valid(g);
        const fresh=await decision(id,g);
        if(fresh.p.revision!==p.revision)throw Error('Диалог изменился во время подготовки заявки');
        result.crm=check(await deps.checkCRM(fresh.s,proposal));valid(g);
        result.proposal=proposal;
      }
      return result;
    }
    async function permit(s,p,kind,g,extra={},review=null,prepare=false) {
      valid(g);
      const op={kind,revision:p.revision,operation_id:p.operation_id,...extra,...(prepare?{preflight_only:true}:{})};
      const a=check(await(review?deps.reviewAuthorize(s,op,review):deps.authorize(s,op)));valid(g);
      const prepared=prepare&&a.preflight_only===true;
      if((review?a.reviewed!==true||a.auto_enabled!==false:a.auto_enabled!==true)
         ||(prepared?a.execution_allowed!==false||!!a.permit:a.execution_allowed!==true||!a.permit||a.preflight_only===true)
         ||!Number.isInteger(a.mode_epoch)||a.mode_epoch!==p.mode_epoch||a.operator_id!==s.operatorId
         ||a.revision!==p.revision||a.kind!==kind||!Number.isFinite(a.expires_at))throw noStartError('Нет разрешения на этот шаг','workflow_permission');
      if(a.expires_at<=Date.now())throw noStartError('Нет разрешения на этот шаг: срок истёк до запроса',prepared?'workflow_not_started':'workflow_permission');
      return a;
    }
    const key=(operator,id,kind,operation)=>['workflow',operator,id,kind,operation].join(':');
    // Write-ahead journal survives F5 and extension worker restarts. Never delete
    // ambiguous writes on stop/reconnect. Storage errors prevent transport.
    async function write(s,p,kind,g,transport,extra={},review=null) {
      const k=key(s.operatorId,s.ctx.convId,kind,kind==='create_crm'?'once':p.operation_id);
      const previous=await deps.read(k);valid(g);
      if(previous&&!notStarted(previous,s,k)) {
        if(previous.state==='done')return previous.result;
        const recovered=await deps.reconcile(kind,previous,s);valid(g);
        if(recovered?.confirmed===true) {
          await deps.save(k,{...previous,state:'done',result:recovered.result});await audit(s,'reconciled',{operation:kind,confirmed:true,id:recovered.result?.id||''},p.revision);return recovered.result;
        }
        throw Error('Результат прошлого действия неизвестен. Повтор остановлен — проверьте вручную');
      }
      await audit(s,'intent',{operation:kind,operation_id:p.operation_id,...(review&&kind==='reply'?{text:extra.reply,draft_id:extra.draft_id,reason:'Проверен и разрешён только этот ответ'}:{})},p.revision);valid(g);
      let a=await permit(s,p,kind,g,extra,review,true);
      const entry={state:'pending',kind,operation_id:p.operation_id,operator:s.operatorId,conv:s.ctx.convId,revision:p.revision,at:Date.now()};
      await deps.save(k,entry);valid(g);
      // Recheck after the durable write, immediately before the external request.
      const fresh=await decision(s.ctx.convId,g);
      if(kind==='reply'&&deps.replyIssue?.(fresh.s.ctx,extra.reply)){
        await deps.save(k,{...entry,state:'blocked'});throw Error(deps.replyIssue(fresh.s.ctx,extra.reply));
      }
      const regular=['claim','reply','create_crm'].includes(kind);
      if((review?fresh.p.auto_session_enabled===true:fresh.p.auto_session_enabled!==true)||fresh.p.mode_epoch!==a.mode_epoch||fresh.p.code==='paused'||regular&&(!fresh.p.eligible||fresh.p.operation_id!==p.operation_id)||fresh.p.revision!==p.revision||fresh.s.operatorId!==s.operatorId||a.expires_at<=Date.now()) {
        const code=fresh.s.operatorId!==s.operatorId?'operator_identity':
          !review&&fresh.p.auto_session_enabled!==true?'auto_disabled':
          fresh.p.mode_epoch!==a.mode_epoch||review&&fresh.p.auto_session_enabled===true?'workflow_permission':'workflow_not_started';
        await rejectBeforeTransport(k,entry,'Диалог или личная сессия изменились перед действием',code,a.preflight_only===true);
      }
      let result;
      await audit(s,'transport_started',{operation:kind,operation_id:p.operation_id},p.revision);valid(g);
      if(a.expires_at<=Date.now()) {
        await rejectBeforeTransport(k,entry,'Разрешение истекло до запроса. Действие не выполнено','workflow_not_started',a.preflight_only===true);
      }
      // Only now consume the server's permanent one-shot grant. A lost final
      // authorization response leaves pending uncertainty and cannot be replayed.
      if(a.preflight_only===true){
        try{a=await permit(fresh.s,p,kind,g,extra,review)}
        catch(error){throw noStartError(String(error.message||error),'workflow_permission')}
      }
      try {result=await transport(p.operation_id,a);}
      catch(e) {await deps.save(k,{...entry,state:'unknown'});await audit(s,'unknown',{operation:kind,operation_id:p.operation_id,error:String(e.message||e)},p.revision).catch(()=>{});throw Error('Запрос мог выполниться. Повтор остановлен: '+String(e.message||e))}
      if(!result?.confirmed) {
        if(result?.no_write){await deps.save(k,{...entry,state:'aborted',result:result.result});await audit(s,'stopped',{operation:kind,reason:result.result?.error||'Форма не отправлена'},p.revision);throw Error(result.result?.error||'Форма не отправлена')}
        await deps.save(k,{...entry,state:'unknown',result:result||null});await audit(s,'unknown',{operation:kind,reason:'Результат не подтверждён; повтор запрещён'},p.revision).catch(()=>{});throw Error('Результат не подтверждён. Автоматический повтор запрещён');
      }
      await deps.save(k,{...entry,state:'done',result:result.result});valid(g);
      await audit(s,'transport_result',{operation:kind,operation_id:p.operation_id,confirmed:true,id:result.result?.id||''},p.revision);valid(g);
      // Observe confirmed API delivery while the relative offer is fresh.
      // The write journal is already done: an observation failure cannot resend.
      if(kind==='reply')await decision(s.ctx.convId,g);
      return result.result;
    }
    async function reviewOne(id,view,confirmation){
      const g=generation;
      return deps.lock('workflow:personal:'+id,async()=>{
        const current=await inspect(id);valid(g);
        if(!view||view.revision!==current.revision||view.operation_id!==current.operation_id||view.step!==current.step||view.mode_epoch!==current.mode_epoch||current.auto_session_enabled)throw Error('Просмотренный шаг изменился. Проверьте его заново');
        const {s,p}=await decision(id,g);
        if((await deps.pending(s.operatorId,id)).some(e=>!notStarted(e,s,e.key)))throw Error('Есть неподтверждённое действие; сначала нужна ручная сверка');
        if(current.step==='claim'){
          await write(s,p,'claim',g,async()=>{const r=await deps.claim(s);check(r);const fresh=await snapshot(id,g);return{confirmed:fresh.ctx.assigneeId===s.operatorId,result:{claimed:true}}},{},confirmation);
          return{step:'reviewed_action_done',last_action:'claim',reason:'Диалог взят. Ответ требует отдельной проверки'};
        }
        if(current.step==='reply'){
          if(current.needs_operator||!view.draft_id||!view.reply||view.reply!==current.reply)throw Error('Точный ответ не подтверждён');
          const approved=check(await deps.validate(s,{draft_id:view.draft_id}));valid(g);
          if(approved.reply!==view.reply||approved.revision!==p.revision)throw Error('Просмотренный ответ устарел');
          const sent=await write(s,p,'reply',g,op=>deps.sendReply(s,view.reply,'lcp:'+op),{draft_id:view.draft_id,reply:view.reply},confirmation);
          return{step:'wait',last_action:'reply',reply:view.reply,message_id:sent?.id||'',reason:'Проверенный ответ отправлен. Общий авто выключен'};
        }
        if(current.step==='prepare_crm')return deps.lock('workflow:crm-create',async()=>{
          if(!view.proposal||!view.crm?.ready||!view.crm.snapshot_hash||view.crm.snapshot_hash!==current.crm?.snapshot_hash)throw Error('Поля просмотренной заявки изменились');
          const gate=check(await deps.checkCRM(s,view.proposal));valid(g);if(!gate.ready||gate.snapshot_hash!==view.crm.snapshot_hash)throw Error('Заявка не прошла повторную проверку');
          const receipt=await write(s,p,'create_crm',g,async()=>{const r=await deps.createCRM(view.proposal,s,{...p,run_generation:g});return{confirmed:!!(r?.ok&&r.id),no_write:!!r?.refused,result:r?{...r,workflow:{...(r.workflow||{}),message_revision:p.message_revision,policy_version:p.policy_version,required_crm_fields:p.crm_required_fields||[]}}:r}},{proposal:view.proposal,snapshot_hash:gate.snapshot_hash},confirmation);
          return{step:'created_review',last_action:'create_crm',id:receipt.id,receipt,reason:'Заявка создана. Проверьте сверку полей и следующий служебный шаг'};
        });
        const transport={link_crm:deps.linkCRM,rename_client:deps.renameClient,notify_created:deps.notifyCreated}[current.step];
        if(!transport||!current.receipt)throw Error('Нет подтверждённого действия для выполнения');
        await write(s,{...p,operation_id:current.operation_id},current.step,g,()=>transport(s,current.receipt),{crm_request_id:current.receipt.id,verification:verificationProof(current.receipt)},confirmation);
        return{step:'reviewed_action_done',last_action:current.step,id:current.receipt.id,reason:'Выполнен только подтверждённый шаг. Общий авто выключен'};
      });
    }
    async function step(id) {
      const hold=await held(id);if(hold)return humanResult(hold);
      const g=generation;let latest=null;
      const run=deps.lock('workflow:personal:'+id,async()=>{
        let {s,p}=await decision(id,g);latest=s;
        for(const entry of await deps.pending(s.operatorId,id)) {
          valid(g);if(notStarted(entry,s,entry.key)||entry.kind==='create_crm')continue;
          const found=await deps.reconcile(entry.kind,entry,s);valid(g);
          if(!found?.confirmed)throw Error('Предыдущее действие ещё не подтверждено. Новые действия остановлены');
          await deps.save(entry.key,{...entry,state:'done',result:found.result});
          await audit(s,'reconciled',{operation:entry.kind,confirmed:true,id:found.result?.id||''},p.revision);
        }
        // A CRM write has one permanent slot per operator/dialogue, even when
        // later messages change the revision. Reconcile it BEFORE planning anew.
        const crmKey=key(s.operatorId,id,'create_crm','once'),saved=await deps.read(crmKey);valid(g);
        if(saved&&!notStarted(saved,s,crmKey)) {
          let receipt=saved.state==='done'?saved.result:null;
          if(!receipt) {
            const found=await deps.reconcile('create_crm',saved,s);valid(g);
            if(!found?.confirmed)throw Error('Создание заявки прервалось. Нужна ручная проверка CRM');
            receipt=found.result;await deps.save(crmKey,{...saved,state:'done',result:receipt});
          }
          return finish(s,p,receipt,g);
        }
        if(!p.eligible)return {step:p.step,reason:p.reason};
        if(p.step==='claim') {
          await write(s,p,'claim',g,async()=>{
            const r=await deps.claim(s);if(!r?.ok)throw Error(r?.why||'Диалог не принят');
            const fresh=await snapshot(id,g);
            return {confirmed:fresh.ctx.assigneeId===s.operatorId,result:{claimed:true}};
          });
          ({s,p}=await decision(id,g));
          if(!p.eligible||p.scope!=='mine')return {step:'handoff',reason:p.reason};
        }
        if(['reply','inspect_media'].includes(p.step)) {
          const draft=check(await previewModel(s,p,g));valid(g);
          if(researching(draft))return researchWait(draft);
          if(researchVeto(draft))return researchVeto(draft);
          if(draft.visual_observation_ready)return {step:'wait',needs_operator:false,reason:draft.reason};
          if(draft.needs_operator||!draft.reply||!draft.draft_id)return {step:'handoff',reason:draft.reason||'Нужен оператор'};
          const duplicate=deps.replyIssue?.(s.ctx,draft.reply);
          if(duplicate)return {step:'handoff',reason:duplicate,needs_operator:true};
          const fresh=await decision(id,g);if(fresh.p.revision!==p.revision)throw Error('Ответ устарел');
          if(!fresh.p.eligible)return {step:fresh.p.step,reason:fresh.p.reason};
          const changedDuplicate=deps.replyIssue?.(fresh.s.ctx,draft.reply);
          if(changedDuplicate)return {step:'handoff',reason:changedDuplicate,needs_operator:true};
          const approved=check(await deps.validate(fresh.s,draft));valid(g);
          if(approved.reply!==draft.reply||approved.revision!==p.revision)throw Error('Ответ изменился при проверке');
          await audit(fresh.s,'intent',{operation:'reply',text:approved.reply,draft_id:draft.draft_id},p.revision);valid(g);
          const sent=await write(fresh.s,p,'reply',g,async(op)=>deps.sendReply(fresh.s,approved.reply,'lcp:'+op),{draft_id:draft.draft_id,reply:approved.reply});
          return {step:'wait',reason:'Ответ отправлен; ждём клиента',reply:approved.reply,message_id:sent?.id||'',last_action:'reply'};
        }
        if(p.step!=='prepare_crm')return {step:p.step,reason:p.reason};
        const form=deps.formPreview?check(await previewModel(s,p,g,true)):null;valid(g);
        if(form&&researching(form))return researchWait(form);
        if(researchVeto(form,true))return researchVeto(form,true);
        // Queue BEFORE obtaining the short server grant, so parallel chats do
        // not consume a permit while waiting for another CRM form to finish.
        const creation=await deps.lock('workflow:crm-create',async()=>{
        const current=await decision(id,g);if(current.p.revision!==p.revision||current.p.step!=='prepare_crm')throw Error('Диалог изменился в очереди создания');
        const proposal=await deps.prepareCRM(s,p,form);valid(g);
        const fresh=await decision(id,g);if(fresh.p.revision!==p.revision)throw Error('Заявка устарела');
        const gate=check(await deps.checkCRM(fresh.s,proposal));valid(g);
        if(!gate.ready)return {handoff:gate.reasons};
        const receipt=await write(fresh.s,p,'create_crm',g,async()=>{
          const r=await deps.createCRM(proposal,fresh.s,{...p,run_generation:g});
          // A known ID always means created: do not create again if field
          // verification or the subsequent LeadChat link failed.
          return {confirmed:!!(r?.ok&&r.id),no_write:!!r?.refused,result:r?{...r,workflow:{...(r.workflow||{}),message_revision:p.message_revision,policy_version:p.policy_version,required_crm_fields:p.crm_required_fields||[]}}:r};
        },{snapshot_hash:gate.snapshot_hash,proposal});
        return {s:fresh.s,receipt};
        });
        if(creation.handoff)return {step:'handoff',reasons:creation.handoff};
        return finish(creation.s,p,creation.receipt,g);
      });
      try{return await run}catch(e){if(latest)await audit(latest,'stopped',{reason:String(e.message||e)}).catch(()=>{});throw e}
    }
    function receiptIssue(s,p,receipt){
      if(!receipt?.id)throw Error('Не подтверждён номер созданной заявки');
      const required=['город','вид работ','вид услуг','тип','партнёр','дата','время','комментарий партнёра','комментарий','служебный комментарий','имя / аккаунт объявления','телефон','имя клиента',...(p.crm_required_fields||[]),...(receipt.workflow?.required_crm_fields||[])];
      if(!receipt.verified||required.some(f=>!receipt.verified.fields?.includes(f))||receipt.verified.diffs?.length||receipt.warnings?.length)return {step:'created_review',id:receipt.id,reason:'Заявка создана; поля требуют проверки. Повтор запрещён'};
      if(s.ctx.crmRequestId&&String(s.ctx.crmRequestId)!==String(receipt.id))return {step:'created_review',id:receipt.id,reason:'В LeadChat другой номер заявки'};
      if(s.ctx.assigneeId!==s.operatorId||!['new','in_progress','waiting_client'].includes(s.ctx.conversationStatus))return {step:'created_review',id:receipt.id,reason:'Диалог передан или закрыт'};
      if(receipt.workflow?.message_revision&&receipt.workflow.message_revision!==p.message_revision)return {step:'created_review',id:receipt.id,reason:'Клиент дописал после создания; нужен оператор'};
      if(receipt.workflow?.policy_version&&receipt.workflow.policy_version!==p.policy_version)return {step:'created_review',id:receipt.id,reason:'Регламент изменился после создания; нужен оператор'};
      return null;
    }
    function verificationProof(receipt){return{crm_request_id:String(receipt.id),fields:receipt.verified?.fields,diffs:receipt.verified?.diffs,warnings:receipt.warnings,policy_version:receipt.workflow?.policy_version,message_revision:receipt.workflow?.message_revision}}
    async function finish(s,p,receipt,g) {
      const issue=receiptIssue(s,p,receipt);if(issue)return issue;
      if(deps.finishOnLinked&&deps.notifyBeforeFinish){
        if(!deps.notifyCreated||receipt.workflow?.followup?.required!==true)return {step:'created_review',id:receipt.id,reason:'Нет подтверждённого маршрута служебной отписки. Закрытие остановлено'};
        const notified=await write(s,{...p,operation_id:'notify:'+receipt.id},'notify_created',g,()=>deps.notifyCreated(s,receipt),{crm_request_id:receipt.id,verification:verificationProof(receipt),before_link:true});
        if(notified?.telegram_confirmed!==true||String(notified.id)!==String(receipt.id))return {step:'created_review',id:receipt.id,reason:'Служебная отписка не подтверждена. Не закрываю диалог'};
        receipt={...receipt,service_notification:notified};
      }
      // Linking the verified CRM ID is independently journalled and authorized.
      if(String(s.ctx.crmRequestId||'')!==String(receipt.id))await write(s,{...p,operation_id:'link:'+receipt.id},'link_crm',g,()=>deps.linkCRM(s,receipt),{crm_request_id:receipt.id,verification:verificationProof(receipt)});
      if(deps.finishOnLinked)return {step:'done',id:receipt.id,telegram_confirmed:receipt.service_notification?.telegram_confirmed===true,reason:deps.notifyBeforeFinish?'Заявка сверена, служебная отписка подтверждена. Диалог закрыт':'Заявка подтверждена. Бот закончил работу'};
      for(const [kind,prefix,transport] of [['rename_client','rename',deps.renameClient],['notify_created','notify',deps.notifyCreated]]){
        if(!transport)return {step:'created_review',id:receipt.id,reason:'Не подключены служебные действия после создания'};
        const fresh=await decision(s.ctx.convId,g);
        if(receipt.workflow?.message_revision&&receipt.workflow.message_revision!==fresh.p.message_revision)return {step:'created_review',id:receipt.id,reason:'Диалог изменился; служебные действия остановлены'};
        await write(fresh.s,{...fresh.p,operation_id:prefix+':'+receipt.id},kind,g,()=>transport(fresh.s,receipt),{crm_request_id:receipt.id,verification:verificationProof(receipt)});
      }
      return {step:'done',id:receipt.id};
    }
    async function cycle(ids) {
      const g=generation,out=[];
      for(const id of [...new Set(ids)].slice(0,12)){valid(g);try{out.push({id,...await step(id)})}catch(e){out.push({id,step:e?.code==='workflow_not_started'?'wait':'handoff',needs_operator:e?.code!=='workflow_not_started',reason:String(e.message||e)})}}
      return out;
    }
    return {inspect,reviewOne,step,cycle,stop,held,park,isCurrent:stamp=>stamp===generation&&deps.visible?.()!==false};
  }
  // Completion mode comes from the accepted native server form. Root checks
  // its own capability and stored form again before granting a CRM write.
  function crmFollowup(draft,channel,code){
    const mode=draft?.completion_mode;
    if(mode!==undefined&&!['telegram','crm_only'].includes(mode))throw Error('Не подтверждён режим завершения заявки');
    if(mode==='crm_only'){
      if(draft.intake_form_ready!==true||!/^[a-f0-9]{64}$/.test(draft.form_reference||''))
        throw Error('Нет принятой сервером формы для режима без Telegram');
      return {required:false,telegram_ready:false,code,mode:'crm_only'};
    }
    return {required:['avito','max'].includes(channel),telegram_ready:false,code};
  }
  return {create,releaseHumanHold,readHistory,waitForDelivery,contactComment,serviceContactComment,callbackComment,callerIdCallReview,projectContactFacts,projectAcceptedVisit,readIntercomField,crmPrepareArgs,draftDirection,formExtraction,territoryIssue,manualCreationReview,crmFollowup};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=LC_WORKFLOW;
