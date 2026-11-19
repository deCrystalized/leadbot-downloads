/* Personal assistant controls; live execution requires explicit activation. */
const LC_ASSISTANT_UI = (() => {
  function captureAssistantView(panel) {
    const view=panel.querySelector('.assistant-view'),active=panel.getRootNode().activeElement;
    return {scroll:panel.querySelector('.pb')?.scrollTop||0,
      focus:view?.contains(active)?(active===view?view.dataset.assistantLastFocus:active.getAttribute?.('data-assistant-focus'))||'':'',
      selection:typeof active?.selectionStart==='number'?[active.selectionStart,active.selectionEnd,active.selectionDirection]:null,
      inside:!!view?.contains(active),
      observerScroll:[...(view?.querySelectorAll('[data-observer-id]')||[])].filter(el=>el.dataset.observerId).map(el=>{const box=el.querySelector('.observer-messages');return [el.dataset.observerId,box?.scrollTop||0,box?box.scrollHeight-box.clientHeight-box.scrollTop<12:false]}),
      details:[...(view?.querySelectorAll('details')||[])].map(el=>[el.dataset.assistantDisclosure||el.querySelector('summary')?.textContent||'',el.open])};
  }
  function restoreAssistantView(panel,memory) {
    if(!memory){for(const card of panel.querySelector('.assistant-view')?.querySelectorAll('[data-observer-id]')||[]){const box=card.dataset.observerId&&card.querySelector('.observer-messages');if(box)box.scrollTop=box.scrollHeight}return}
    const view=panel.querySelector('.assistant-view'),body=panel.querySelector('.pb');if(!view)return;
    for(const el of view.querySelectorAll('details')){
      const match=memory.details.find(([key])=>key===(el.dataset.assistantDisclosure||el.querySelector('summary')?.textContent));
      if(match)el.open=match[1];
    }
    if(memory.inside){
      const control=memory.focus&&view.querySelector('[data-assistant-focus="'+memory.focus+'"]');
      if(control&&!control.disabled){control.focus({preventScroll:true});if(memory.selection&&typeof control.setSelectionRange==='function')try{control.setSelectionRange(...memory.selection)}catch(_e){/* Non-text controls cannot have a caret. */}}
      else {view.tabIndex=-1;view.dataset.assistantLastFocus=memory.focus;view.focus({preventScroll:true});}
    }
    if(body)body.scrollTop=memory.scroll;
    for(const card of view.querySelectorAll('[data-observer-id]')){if(!card.dataset.observerId)continue;const box=card.querySelector('.observer-messages'),saved=(memory.observerScroll||[]).find(([id])=>id===card.dataset.observerId);if(box)box.scrollTop=!saved||saved[2]?box.scrollHeight:saved[1]}
  }
  function create(deps) {
    const { h:baseH, panel, header, send, currentId, latestId, onUseFacts, onRequest } = deps;
    const h=typeof LC_STABLE_DOM!=='undefined'?LC_STABLE_DOM.factory(baseH,error=>{state.error=String(error.message||error);draw()}):baseH;
    async function loadContext(id){try{return await deps.loadContext(id)}catch(e){await recordEvent(id,'read_error',{error:String(e.message||e)}).catch(()=>{});throw e}}
    async function recordEvent(id,kind,data){const operator=personal?.state.operator;if(!operator)return;const event={kind,data,event_id:crypto.randomUUID()};const s={operatorId:operator,ctx:{convId:id}};const r=await personal.call('personal_event',{ctx:s.ctx,audit_event:event});if(!r?.ok)await deps.workflow?.queueAudit?.(s,event)}
    const state = { id: '', ctx: null, result: null, workflow:null, activation:null, audit:[],auditExpanded:new Set(),auditBusy:false,auditError:'',auditMore:null, busy: false, paused: false, stale: false, error: '', epoch: 0, rendered:false, skipsOpen:false, wordingMode:'reviewed' };
    let workflow=null,runner=null,observer=null;
    const researchAudit={job:'',rows:[],busy:false,error:''};
    const personal = deps.getIdentity && deps.loadQueue && typeof LC_PERSONAL !== 'undefined' ? LC_PERSONAL.create({
      send,getIdentity:deps.getIdentity,getAuthors:deps.getAuthors,getProof:deps.getProof,loadQueue:deps.loadQueue,loadContext,intakeGuard:deps.intakeGuard,onStart:deps.onPersonalStart,logEvent:recordEvent,startPulse:deps.startPulse,stopPulse:deps.stopPulse,
      held:id=>workflow?.held(id,personal.state.operator),
      visible:()=>visible(),onChange:()=>{if(!personal.state.active||runner?.state.mode==='auto'&&!personal.state.auto){runner?.stop();workflow?.stop()}if(observer)observer.update(personal.state.rows);else draw()}}) : null;
    const nativeRequested=!!deps.nativeRun;
    const nativeRun=nativeRequested&&personal&&typeof LC_ASSISTANT_NATIVE!=='undefined'&&typeof LC_ASSISTANT_NATIVE.createRun==='function'?LC_ASSISTANT_NATIVE.createRun({
      ...deps.nativeRun,identity:deps.getIdentity,principal:()=>personal.state.principal,
      operator:()=>personal.state.operator,onChange:()=>{draw();syncNativeObservation().catch(error=>{state.error=error.message;draw()})}
    }):null;
    if(personal)personal.nativeRun=nativeRun;
    let nativeSync=null;
    async function syncNativeObservation(){
      const live=nativeRun?.state.view,p=personal?.state;
      if(!live||live.principal_id!==p?.principal||live.state!=='running')return;
      if(runner&&runner.state.mode!=='stopped'){runner.stop();workflow?.stop()}
      if(live.operator_id===p.operator||!p.authors.some(a=>a.id===live.operator_id))return;
      if(nativeSync)return nativeSync;
      nativeSync=(async()=>{await personal.selectAuthor(live.operator_id);observer?.reset();await observer?.refresh(0)})();
      try{await nativeSync}finally{nativeSync=null}
    }
    const style = document.createElement('style');
    style.textContent = `
      .assistant-view{display:grid;gap:16px;font:inherit;color:var(--t1,#e7ede9);min-width:0;align-content:start}
      .assistant-view>*{min-width:0}
      .assistant-status{display:flex;align-items:center;gap:8px;padding:8px 0;font-size:12px;color:var(--t2,#c7d2c9);line-height:1.5;overflow-wrap:anywhere}
      .assistant-dot{width:7px;height:7px;border-radius:50%;background:var(--t3,#949e97);flex:none}
      .assistant-actions{display:flex;gap:8px;flex-wrap:wrap;align-items:stretch}
      .assistant-actions .go{flex:1;min-width:140px}
      .assistant-view .btn{min-height:40px;height:auto;padding:8px 12px;border-radius:7px;border:1px solid var(--line,#2a332e);background:transparent;color:var(--t1,#e7ede9);cursor:pointer;font:inherit;font-size:12.5px;line-height:1.4;white-space:normal;overflow-wrap:anywhere;transition:background-color 120ms ease,border-color 120ms ease,color 120ms ease}
      .assistant-view .btn:hover:not(:disabled){background:var(--sunk,#141b18);border-color:var(--t3,#949e97)}
      .assistant-view button:active:not(:disabled){filter:brightness(.94)}
      .assistant-view button:disabled{opacity:.55;cursor:not-allowed;filter:none}
      .assistant-section{display:grid;gap:10px;padding:14px 0;border:0;border-top:1px solid var(--line,#2a332e);border-radius:0;min-width:0}
      .assistant-section .assistant-section{padding:10px 0 0;margin:0;background:transparent}
      .assistant-label{font-size:13px;font-weight:650;color:var(--t1,#e7ede9);line-height:1.45;overflow-wrap:anywhere}
      .assistant-reason,.assistant-foot,.assistant-empty{font-size:12px;line-height:1.6;color:var(--t3,#949e97);overflow-wrap:anywhere}
      .assistant-empty{padding:16px 0;border-block:1px solid var(--line,#2a332e)}
      .assistant-draft{padding:12px 14px;border-radius:7px;border:1px solid var(--line,#2a332e);border-left:3px solid var(--acc,#3cc13b);background:var(--sunk,#141b18);font-size:13px;line-height:1.7;white-space:pre-wrap;overflow-wrap:anywhere;user-select:text;min-width:0}
      .assistant-facts{display:grid;grid-template-columns:minmax(68px,90px) minmax(0,1fr);gap:6px 12px;margin:0;font-size:12.5px;line-height:1.5}
      .assistant-facts dt{color:var(--t3,#949e97);overflow-wrap:anywhere}.assistant-facts dd{margin:0;overflow-wrap:anywhere;min-width:0;color:var(--t1,#e7ede9)}
      .assistant-sources{font-size:12px;color:var(--t2,#c7d2c9);line-height:1.6;overflow-wrap:anywhere;min-width:0}
      .assistant-sources summary{cursor:pointer;padding:9px 6px;min-height:40px;border-radius:6px;color:var(--t2,#c7d2c9);line-height:1.5;transition:background-color 120ms ease,color 120ms ease}
      .assistant-sources summary:hover{background:var(--sunk,#141b18);color:var(--t1,#e7ede9)}
      .assistant-sources[open]>summary{color:var(--t1,#e7ede9);font-weight:600}
      .assistant-quote{display:grid;gap:4px;margin-top:0;padding:10px 0;border-top:1px solid var(--line,#2a332e);min-width:0;overflow-wrap:anywhere}
      .assistant-quote>b{color:var(--t1,#e7ede9);font-weight:600}
      .assistant-quote small{font-size:11.5px;color:var(--t3,#949e97);opacity:1}
      .assistant-quote>.btn{justify-self:start;max-width:100%}
      .assistant-notice{padding:10px 12px;border-radius:7px;border:1px solid var(--warn-line,#5b4721);border-left:3px solid var(--warn,#d9a94e);background:var(--warn-bg,#241a05);color:var(--t1,#e7ede9);font-size:12.5px;line-height:1.5;overflow-wrap:anywhere}
      .assistant-notice.ok,.assistant-notice.success{background:var(--ok-bg,#10240f);border-color:var(--ok-line,#2c9c2b);color:var(--ok,#7ed77c)}
      .assistant-notice.bad,.assistant-notice.error{background:var(--bad-bg,#2a1213);border-color:var(--bad-line,#e5484d);color:var(--bad,#ff9ea1)}
      .assistant-notice.info{background:var(--sunk,#141b18);border-color:var(--line,#2a332e);color:var(--t2,#c7d2c9)}
      .assistant-notice p{margin:8px 0}.assistant-notice .assistant-actions{margin-top:10px}
      .assistant-view :is(button,summary,input,select,textarea):focus-visible,.assistant-draft:focus-visible{outline:2px solid var(--acc,#3cc13b);outline-offset:2px}
      .assistant-view [data-personal]{padding-top:0;border-top:0}
      :host-context(.lcz-personal-page) .panel .ph{padding:14px 24px;border-bottom:1px solid var(--line)}
      :host-context(.lcz-personal-page) .panel .pb{padding:20px 24px;max-width:1180px}
      @media(min-width:900px){
        :host-context(.lcz-personal-page) .assistant-view{grid-template-columns:300px minmax(0,1fr);column-gap:32px;row-gap:14px}
        :host-context(.lcz-personal-page) .assistant-view>[data-personal]{padding:0 24px 0 0;border-right:1px solid var(--line);border-top:0}
        :host-context(.lcz-personal-page) .assistant-view>[data-workflow]{padding-top:0;border-top:0}
        :host-context(.lcz-personal-page) .assistant-view>[data-personal]>.assistant-label{font-size:15px}
      }
      @media(max-width:600px){
        :host-context(.lcz-personal-page) .panel .ph{padding:12px 14px}
        :host-context(.lcz-personal-page) .panel .pb{padding:14px}
        .assistant-actions>.btn{flex:1 1 120px}.assistant-facts{grid-template-columns:76px minmax(0,1fr);gap:6px 10px}
      }
      @media(prefers-reduced-motion:reduce){.assistant-view *{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
    `;
    if(deps.observer&&typeof LC_OBSERVER!=='undefined')style.textContent+=LC_OBSERVER.style;
    panel.getRootNode().appendChild(style);
    let timer = 0, last = '', checking = false;
    const visible = () => panel.classList.contains('open') && panel.dataset.assistant === state.id && !!state.id
      && (!state.rendered || !!panel.querySelector('.assistant-view'));
    const identified=(action,operation)=>personal?personal.identityCall(action,identity=>
      operation({operator_id:personal.state.operator,...identity})):operation({});
    const call = (action, extra = {}) => identified(action,identity=>send({ kind: 'lcz-assistant', args: { action, ctx: state.ctx, ...extra,...identity } }));
    const workflowCall=(action,s,extra={})=>identified(action,identity=>send({kind:'lcz-assistant',args:{action,ctx:s.ctx,operator_id:s.operatorId,mine_count:s.mineCount,...extra,...identity}}));
    if(personal&&deps.workflow&&typeof LC_WORKFLOW!=='undefined')workflow=LC_WORKFLOW.create({
      ...deps.workflow,visible:()=>visible(),
      operator:()=>personal.state.operator,
      intakeGuard:deps.intakeGuard,replyIssue:deps.replyIssue,
      snapshot:async(id)=>{
        const selectedEpoch=state.epoch;
        if(!personal.state.active)throw Error('Подключите личную сессию');
        await deps.assertUnoccupied?.(id);
        const me=await personal.identity();
        const lease=await personal.call('personal_status');
        if(!lease?.ok||!lease.active)throw Error('Личная сессия истекла');
        const queue=await deps.loadQueue({countOnly:true}),ctx=await loadContext(id);
        await deps.assertRunnable?.(id,ctx);
        if(state.epoch===selectedEpoch&&state.id===id&&currentId()===id)state.ctx=ctx;
        return {operatorId:String(me.id),active:true,mineCount:queue.mineCount,ctx};
      },
      plan:s=>workflowCall('personal_plan',s),preview:s=>workflowCall('preview',s,{wording_mode:state.wordingMode}),
      formPreview:s=>workflowCall('form_preview',s,{wording_mode:state.wordingMode}),
      research:(action,s,args)=>workflowCall(action,s,args),
      onResearchCancelError:message=>{state.error=message;draw()},
      validate:(s,d)=>workflowCall('validate',s,{draft_id:d.draft_id}),
      checkCRM:(s,proposal)=>workflowCall('personal_crm_check',s,{proposal}),
      audit:async(s,event)=>{
        const audit_event={...event,event_id:crypto.randomUUID()};
        const r=await workflowCall('personal_event',s,{audit_event});
        if(r?.ok)return r;
        await deps.workflow.queueAudit(s,audit_event);return {ok:true,queued:true};
      },
      authorize:(s,operation)=>workflowCall('personal_authorize',s,{operation}),
      reviewAuthorize:async(s,operation,confirmation)=>{
        const r=await workflowCall('personal_review_authorize',s,{operation,...confirmation});
        if(r?.ok&&r.activation_nonce)personal.state.nonce=r.activation_nonce;
        return r;
      }
    });
    if(workflow&&typeof LC_ASSISTANT_RUNNER!=='undefined')runner=LC_ASSISTANT_RUNNER.create({
      visible:()=>visible(),active:()=>personal.state.active,
      operator:()=>personal.state.operator,
      setMode:mode=>personal.setMode(mode),stopWorkflow:()=>workflow.stop(),
      scan:async(ids,onReady)=>{await personal.scan(ids,onReady);if(personal.state.error)throw Error(personal.state.error);return personal.state.rows},
      inspect:id=>workflow.inspect(id),step:id=>workflow.step(id),onChange:()=>{if(observer)observer.update([...personal.state.rows,...runner.state.rows]);else draw()},
      park:(id,result)=>workflow.park(id,result,personal.state.operator),
      log:data=>recordEvent('__runner__','cycle',{operation:data.mode,duration_ms:data.duration_ms,reason:'Проверено '+data.checked+', планов '+data.actions})
    });
    if(deps.observer&&typeof LC_OBSERVER!=='undefined')observer=LC_OBSERVER.create({
      h,list:deps.observer.list,listCandidates:deps.observer.listCandidates,openCandidate:deps.observer.openCandidate,loadContext,
      loadHold:row=>workflow?.held(row.id,row.operator_id),
      authorName:id=>personal.state.authors.find(a=>a.id===id)?.full_name,
      takeover:async row=>{await deps.observer.takeover(row);if(state.id===row.id){state.epoch++;state.result=null;state.workflow=null;state.paused=true;state.busy=false}},
      inspect:openReviewedDialog,onChange:()=>draw()
    });
    if(observer)window.addEventListener('keydown',event=>{if(visible())observer.key(event)});
    const button = (text, fn, disabled = false, main = false, key = '') => h('button', { class: main ? 'go' : 'btn', type: 'button', disabled, onclick: fn,
      'data-assistant-focus':(Array.from(key||String(fn)).reduce((n,c)=>((n*33)^c.charCodeAt(0))>>>0,5381)).toString(16) }, text);
    const statusText = () => state.paused ? 'Подсказки на паузе' : state.busy ? 'Проверяю диалог…' : state.stale ? 'Диалог изменился — обновите ответ' : 'Автоматические отправки выключены';
    function draw() {
      if (!visible()) return;
      personal?.checkLease();
      const memory=state.rendered?captureAssistantView(panel):null;
      const result = state.result, facts = result && result.facts;
      const callbackReview=typeof LC_WORKFLOW!=='undefined'&&typeof LC_WORKFLOW.callerIdCallReview==='function'
        ?LC_WORKFLOW.callerIdCallReview(result):null;
      const overview=observer&&state.id==='__personal__';
      const awaitingAdmission=personal?.state.active&&runner?.state.mode!=='stopped'
        &&runner?.state.rows.some(row=>row.research_state==='awaiting_admission');
      const admissionNotice=()=>awaitingAdmission?h('div',{class:'assistant-notice',role:'status'},
        h('div',{class:'assistant-label'},'Ответы пока не запущены'),
        h('p',{},'Диалоги приняты, но проверка ответов через API ждёт допуска. Это ожидание разрешения, а не работа модели. Отправки ещё нет.')):'';
      const allowanceNotice=()=>personal?.state.auto&&personal.state.apiAllowance?h('div',{class:'assistant-foot',role:'status','data-api-allowance':'1'},
        personal.state.apiAllowance.blocked?'Допуск API остановлен. Проверьте журнал перед новым запуском.':
          'Допуск API на этот запуск: '+personal.state.apiAllowance.remaining+' из '+personal.state.apiAllowance.limit+' вызовов. Это резерв вызовов, не остаток денег на балансе.') : '';
      const box = overview?h('div',{class:'assistant-view'},personalView(),admissionNotice(),allowanceNotice(),observer.view(),
        state.error?h('div',{class:'assistant-notice',role:'alert'},state.error):'',
        state.notice?h('div',{class:'assistant-notice ok',role:'status'},state.notice):'',
        h('details',{class:'assistant-sources','data-assistant-disclosure':'observer-audit'},h('summary',{},'Журнал событий'),auditView())):h('div', { class: 'assistant-view' },
        personal ? personalView() : '',
        admissionNotice(),
        allowanceNotice(),
        observer ? observer.view() : '',
        workflow ? workflowView() : '',
        !personal||state.busy||state.paused||state.stale ? h('div', { class: 'assistant-status', role: 'status', 'aria-live': 'polite' }, h('span', { class: 'assistant-dot' }), statusText()) : '',
        h('div', { class: 'assistant-actions' }, button(state.busy ? 'Готовлю…' : 'Подготовить ответ', preview, state.busy || state.paused || state.id==='__personal__', true),
          button(state.paused ? 'Продолжить' : 'Пауза', togglePause, state.busy || state.id==='__personal__')),
        state.error ? h('div', { class: 'assistant-notice', role: 'alert' }, state.error) : '',
        state.notice ? h('div', { class: 'assistant-notice ok', role: 'status', 'aria-live':'polite' }, state.notice) : '',
        result ? h('div', { class: 'assistant-section' }, h('div', { class: 'assistant-label' }, result.needs_operator ? 'Нужен оператор' : 'Ответ по регламенту'),
          result.reason ? h('div', { class: 'assistant-reason' }, result.reason) : '',
          result.reply ? h('div', { class: 'assistant-draft', tabindex: '0' }, result.reply) : '',
          result.reply ? button('Скопировать ответ', copy, state.stale || state.paused || state.busy) : '',
          h('div', { class: 'assistant-foot' }, personal?.state.auto?'Авто включён. Ручной ответ — в LeadChat.':'Черновик · без отправки')) :
          h('div', { class: 'assistant-empty' }, state.id==='__personal__'?'Выберите диалог.':'Подготовьте ответ.'),
        callbackReview?h('div',{class:'assistant-section','data-caller-id-review':'1'},
          h('div',{class:'assistant-label'},callbackReview.status),
          callbackReview.phone?h('div',{class:'assistant-quote'},'Номер для звонка: '+callbackReview.phone):'',
          ...callbackReview.timing.map(text=>h('div',{class:'assistant-quote'},text)),
          h('div',{class:'assistant-foot'},callbackReview.instruction)):'',
        facts ? h('div', { class: 'assistant-section' }, h('div', { class: 'assistant-label' }, 'Данные из переписки'),
          h('dl', { class: 'assistant-facts' }, h('dt', {}, 'Телефон'), h('dd', {}, facts.contact_phone_to_use || (facts.phone_needs_confirmation ? 'Уточнить номер для связи' : 'Не указан')),
            h('dt', {}, 'Адрес'), h('dd', {}, Object.entries(facts.address || {}).map(([k, v]) => ({ street: 'ул.', building: 'дом', office: 'кв./ЧД', settlement: 'нас. пункт', entrance: 'подъезд', floor: 'этаж', intercom: 'домофон' }[k] || k) + ': ' + v).join(', ') || 'Не указан')),
          evidence(facts),
          onUseFacts ? button('В заявку', useFacts, state.stale || state.busy || state.paused || facts.phone_needs_confirmation || facts.address_needs_confirmation) : '') : '',
        result ? h('details', { class: 'assistant-sources' }, h('summary', {}, 'Основания решения'),
          h('div', {}, 'Регламент ' + result.policy_version),
          ...(result.sources || []).map((source) => h('div', { class: 'assistant-quote' }, source.text)),
          (result.validation || []).length ? h('div', {}, 'Ответ не прошёл проверку. Требуется решение оператора.') : '') : '',
        personal&&result?.media_review_required?.length?mediaReviewView(result.media_review_required):'',
        researchAuditView(),
        personal?auditView():'',
        onRequest?button('Перейти к заявке', () => { stop(); panel.dataset.assistant = ''; onRequest(); }, state.busy || state.id==='__personal__'):'');
      const nodes=[h('div', { class: 'ph' }, header(personal?.state.auto?'Авто · '+personal.state.name:'Проверка · автоматические действия выключены', { title: 'Личный помощник' })), h('div', { class: 'pb' }, box)];
      if(typeof LC_STABLE_DOM!=='undefined'&&state.rendered)LC_STABLE_DOM.children(panel,nodes);else panel.replaceChildren(...nodes);
      restoreAssistantView(panel,memory);
      state.rendered=true;
    }
    const auditLabels={cycle:'Цикл помощника',read:'Прочитал переписку',decision:'Что решил',draft:'Подготовил ответ',session:'Личная сессия',crm_check:'Проверил заявку',authorization:'Проверил разрешение',call_confirmation:'Подтверждение звонка оператором',media_review:'Подтвердил просмотр изображения',intent:'Намерен выполнить',transport_started:'Начал запрос',transport_result:'Проверил результат',unknown:'Результат неизвестен',reconciled:'Восстановил результат',stopped:'Остановился',read_error:'Не смог прочитать',skipped:'Пропустил'};
    const auditOperations={claim:'Взять диалог',reply:'Отправить ответ',create_crm:'Создать заявку',link_crm:'Привязать заявку к диалогу',rename_client:'Добавить номер заявки к имени',notify_created:'Сообщить о созданной заявке'};
    function researchAuditView(){
      const job=state.result?.research_job_id;if(!job)return '';
      const rows=researchAudit.job===job?researchAudit.rows:[];
      const labels={context_observed:'Прочитал контекст',source_tool_requested:'Поиск или чтение источника',source_tool_result:'Получил источники',
        decision_basis:'Основание ответа · утверждение модели',review_result:'Отдельная проверка ответа',root_accepted:'Контролёр принял ответ',
        root_denied:'Контролёр отклонил ответ',legacy_validation_result:'Проверка рабочего маршрута',raw_fsynced:'Сохранён исходный ответ',
        provider_request_saved:'Сохранён запрос к модели',research_stopped:'Исследование остановлено',research_complete:'Исследование завершено'};
      return h('details',{class:'assistant-sources','data-assistant-disclosure':'research-audit-'+job},
        h('summary',{},'Как бот подготовил ответ'),
        h('div',{class:'assistant-actions'},button(researchAudit.busy?'Загружаю…':'Открыть журнал',loadResearchAudit,researchAudit.busy)),
        researchAudit.error?h('div',{role:'alert'},researchAudit.error):'',
        ...rows.map(row=>h('details',{'data-assistant-disclosure':'research-event-'+job+'-'+row.sequence},
          h('summary',{},new Date(row.at*1000).toLocaleTimeString()+' · '+(labels[row.event]||row.event)),
          row.detail.summary?h('div',{class:'assistant-reason'},row.detail.summary):'',
          row.detail.proposed_reply?h('div',{class:'assistant-quote'},row.detail.proposed_reply):'',
          row.detail.arguments?.query?h('div',{},'Запрос: '+row.detail.arguments.query):'',
          h('pre',{style:'white-space:pre-wrap;overflow:auto;max-height:320px;font-size:11px'},JSON.stringify(row.detail,null,2)))));
    }
    async function loadResearchAudit(){
      const selected=state.result;if(!selected?.research_job_id||researchAudit.busy)return;
      const epoch=state.epoch;researchAudit.busy=true;researchAudit.error='';draw();
      try{
        const out=await call('research_audit',{research_job_id:selected.research_job_id,request_id:selected.request_id,
          revision:selected.revision,audit_cursor:0,audit_limit:100});
        if(epoch!==state.epoch||state.result?.research_job_id!==selected.research_job_id)return;
        if(!out?.chain_valid||!Array.isArray(out.events))throw Error(out?.error||'Журнал не подтверждён');
        researchAudit.job=selected.research_job_id;researchAudit.rows=out.events;
      }catch(error){if(epoch===state.epoch)researchAudit.error=String(error.message||error)}
      finally{researchAudit.busy=false;draw()}
    }
    function auditView(){return h('div',{class:'assistant-section','data-audit':'1'},h('div',{class:'assistant-label'},'Журнал'),

      h('div',{class:'assistant-actions'},button(state.auditBusy?'Загружаю…':'Обновить',()=>loadAudit(false),state.auditBusy),state.auditMore?button('Ранее',()=>loadAudit(true),state.auditBusy):''),
      state.auditError?h('div',{class:'assistant-notice'},state.auditError):'',
      ...state.audit.map(event=>h('details',{class:'assistant-sources','data-assistant-disclosure':'audit-'+event.id,...(state.auditExpanded.has(event.id)?{open:''}:{}),ontoggle:e=>{if(e.currentTarget.open)state.auditExpanded.add(event.id);else state.auditExpanded.delete(event.id)}},h('summary',{},new Date(event.at*1000).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',second:'2-digit'})+' · '+(auditLabels[event.kind]||event.kind)),
        h('div',{class:'assistant-quote'},event.data.messages_read!==undefined?'Прочитано сообщений: '+event.data.messages_read+' из '+event.data.messages_received+' · проверок: '+event.checks:'',
          event.data.reason||event.data.error||'',event.data.duration_ms!==undefined?'Время: '+(event.data.duration_ms/1000).toFixed(2)+' с':'',event.data.reply?h('div',{class:'assistant-draft'},event.data.reply):'',
          event.data.text?h('div',{class:'assistant-draft'},event.data.text):'',
          event.data.operation?h('div',{},'Действие: '+(auditOperations[event.data.operation]||event.data.operation)):'',
          event.data.id?h('div',{},'Подтверждённый номер: '+event.data.id):'',
          event.data.unread_media?h('div',{},'Не понял вложения: '+event.data.unread_media+' — требуется просмотр оператором'):'',
          event.data.confirmed===true?'Расширение подтвердило результат чтением':event.data.authorized===false?'Действие запрещено':'',
          ...(event.data.reasons||[]).map(t=>h('div',{},t)),
          event.data.facts?h('div',{},'Контакты: '+([event.data.facts.contact_phone_to_use?'телефон '+event.data.facts.contact_phone_to_use:'телефон пока не получен',Object.entries(event.data.facts.address||{}).map(([k,v])=>({street:'улица',building:'дом',office:'квартира',entrance:'подъезд',floor:'этаж',settlement:'посёлок'}[k]||k)+': '+v).join(', ')||'адрес пока не получен'].join(' · '))):'',
          event.data.understood?h('div',{},'Подтверждено из ответов: '+Object.entries(event.data.understood).map(([k,v])=>({client_name:'Имя',model:'Марка / модель',visit_time:'Время визита',decision_maker:'ЛПР и присутствие',problem:'Проблема',place:'Место работ'}[k]||v.label||k)+': '+(v.value==='yes'?'да':v.value==='no'?'нет':v.quote||v.value)).join('; ')):'',
          event.data.next_question?h('div',{},'Нужно уточнить: '+event.data.next_question):'',
          event.data.sources?.length?h('div',{},...event.data.sources.map(source=>h('div',{class:'assistant-quote'},source.text))):event.data.rule_ids?.length?h('div',{},'Основания: '+event.data.rule_ids.join(', ')):'',
          event.kind==='read'?button('Сообщения',()=>auditDetail(event.id),state.auditBusy,false,'audit-read-'+event.id):'',
          event.messages?h('div',{},...event.messages.map(m=>h('div',{class:'assistant-quote'},h('b',{},m.direction==='in'?'Клиент':'Оператор'),h('span',{},m.body),m.voice_transcript?h('span',{},'Расшифровка: '+m.voice_transcript):'',m.analysis_used===false?h('span',{},'Служебное или не доставлено: не использовано при решении'):'',m.unread_media?h('span',{},'Вложение не расшифровано — нужно просмотреть вручную'):''))):''))));}
    async function auditRequest(extra={}){
      const me=await personal.identity();
      await deps.workflow?.flushAudit?.(String(me.id),args=>personal.call('personal_event',args));
      const r=await personal.call('personal_audit',{ctx:state.id==='__personal__'?{}:{convId:state.id},...extra});
      if(!r?.ok)throw Error(r?.error||'Журнал недоступен');return r;
    }
    async function loadAudit(older){const epoch=state.epoch;state.auditBusy=true;state.auditError='';draw();try{const r=await auditRequest(older?{audit_before:state.auditMore}:{});if(epoch===state.epoch){state.audit=older?state.audit.concat(r.events):r.events;state.auditMore=r.next_before}}catch(e){if(epoch===state.epoch)state.auditError=String(e.message||e)}finally{if(epoch===state.epoch){state.auditBusy=false;draw()}}}
    async function auditDetail(id){const epoch=state.epoch;state.auditBusy=true;draw();try{const r=await auditRequest({audit_event_id:id});if(epoch===state.epoch){const item=state.audit.find(e=>e.id===id);if(item)item.messages=r.event.messages}}catch(e){if(epoch===state.epoch)state.auditError=String(e.message||e)}finally{if(epoch===state.epoch){state.auditBusy=false;draw()}}}
    function conversationReview(ctx){
      if(!ctx?.convId||ctx.convId!==state.id||!Array.isArray(ctx.messages))return '';
      const messages=ctx.messages;
      return h('details',{class:'assistant-sources','data-assistant-disclosure':'current-history-'+ctx.convId,
        ...(messages.length<=8?{open:''}:{})},h('summary',{},'Переписка · '+messages.length),
        ctx.itemTitle?h('div',{class:'assistant-foot'},ctx.itemTitle):'',
        ...messages.map(m=>h('div',{class:'assistant-quote'},h('b',{},m.direction==='in'?'Клиент':m.direction==='out'?'Сотрудник':'Служебное'),
          h('span',{},String(m.body||m.text||m.content||'')),
          m.voice_transcript?h('span',{},'Расшифровка: '+m.voice_transcript):'',
          (m.attachments||[]).length?h('small',{},'Вложения: '+m.attachments.length+' · проверить перед ответом'):'',
          ['pending','queued','sending','failed','error','cancelled','canceled'].includes(String(m.delivery_status||m.status||'').toLowerCase())?
            h('small',{},'Не подтверждена доставка'):'',
          m.created_at?h('small',{},new Date(m.created_at).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})):'')));
    }
    function workflowView() {
      const w=state.workflow,labels={claim:'Взять на мой аккаунт',reply:'Ответить',prepare_crm:'Проверить заявку',create_crm:'Создать заявку',link_crm:'Привязать заявку',rename_client:'Добавить номер к имени',notify_created:'Отписаться о заявке',reviewed_action_done:'Проверенный шаг выполнен',handoff:'Нужен оператор',wait:'Ждём клиента',done:'Заявка сверена'};
      return h('div',{class:'assistant-section','data-workflow':'1'},h('div',{class:'assistant-label'},(state.ctx?.clientName||personal.state.rows.find(r=>r.id===state.id)?.name||'Полная цепочка')+' · проверка'),
        h('div',{class:'assistant-foot'},'Диалог → Ответ → Заявка'),
        state.ctx?h('div',{class:'assistant-foot'},[state.ctx.channel?.toUpperCase(),state.ctx.accountTitle,state.ctx.city].filter(Boolean).join(' · ')):'',
        h('div',{class:'assistant-notice'},personal.state.auto?'Авто включено только в этой сессии. Согласования и неизвестные условия остаются тебе.':'Автоматический режим выключен. Проверка ничего не берёт, не отправляет и не создаёт.'),
        conversationReview(state.ctx),
        button(state.busy?'Проверяю…':'Проверить всю цепочку',inspectWorkflow,state.busy||!personal.state.active||state.id==='__personal__'),
        w?h('div',{class:'assistant-reason',role:'status'},'Следующий шаг: '+(labels[w.crm?.step||w.step]||w.step),w.reason?' · '+w.reason:''):'',
        w?.reply?h('div',{class:'assistant-draft'},w.reply):'',
        w?.proposal?proposalView(w.proposal):'',
        w?.receipt?.verified?h('div',{class:'assistant-foot'},'Сверено полей: '+w.receipt.verified.checked+' · расхождений: '+(w.receipt.verified.diffs?.length||0)):'',
        ...(w?.crm?.reasons||[]).map(reason=>h('div',{class:'assistant-reason'},'• '+reason)),
        w?.crm?.requires_call?button('Звонок проведён, данные подтверждены',confirmCall,state.busy||!personal.state.active):'',
        w?.crm?.ready?h('div',{class:'assistant-foot'},personal.state.auto?'Готово к созданию':'Готово · без создания'):'',
        w&&['claim','reply','prepare_crm','link_crm','rename_client','notify_created'].includes(w.step)&&!w.needs_operator?h('div',{class:'assistant-actions'},
          button('Проверено по регламенту: '+(w.step==='reply'?'отправить этот ответ'+(state.ctx?.accountTitle?' · '+state.ctx.accountTitle:''):w.step==='prepare_crm'?'создать эту заявку':labels[w.step]),executeReviewed,state.busy||!personal.state.active||personal.state.auto||w.step==='prepare_crm'&&!w.crm?.ready)):'',
        w?h('div',{class:'assistant-foot'},'Один шаг · авто выключен') :''
      );
    }
    function proposalView(p){
      const l=p.lead,a=l.addr||{},label=(rows,id)=>rows?.find(x=>String(x.id)===String(id))?.text||'Не подтверждено';
      const fields=[['Город',p.prep.cityText],['Работа',label(p.prep.appl,p.prep.applId)],['Услуга',label(p.prep.sub,p.prep.subId)],['Тип',p.sel.type||'Впервые'],['Партнёр',l.partner],
        ['Имя',l.name],['Телефон',l.phone],['Улица',a.street||a.settlement],['Дом',a.building],['Квартира / ЧД',a.office],['Дата',l.visit_date?.split('-').reverse().join('.')],['Время',l.visit_time],
        ['Источник',l.partner_note],['Комментарий',l.comment],['Служебный комментарий',l.service_comment],['Отзыв',l.review?'Да':'Нет'],['Звонок до выезда',l.call_before_visit?'Да':'Нет'],['Объявление',l.ad_identity]];
      return h('div',{class:'assistant-section'},h('div',{class:'assistant-label'},'Поля заявки перед созданием'),h('dl',{class:'assistant-facts'},...fields.flatMap(([key,value])=>[h('dt',{},key),h('dd',{style:'white-space:pre-wrap'},value||'—')])));
    }
    function mediaDraft(item){
      const key=JSON.stringify([state.id,state.result?.revision,item.message_id,item.signature]);
      state.mediaFacts ||= new Map();
      if(!state.mediaFacts.has(key))state.mediaFacts.set(key,{model:'',brand:'',content_kind:'',visual:'',error_code:'',error_system:'',contact_role:'',contact_phone:''});
      return state.mediaFacts.get(key);
    }
    function mediaReviewView(items){
      return h('div',{class:'assistant-section'},h('div',{class:'assistant-label'},'Просмотр изображений'),
        h('div',{class:'assistant-foot'},'Подтвердите просмотр всех изображений конкретного сообщения. Это не подтверждает цену, размеры или условия заявки.'),
        ...items.map(item=>{
          const raw=(state.ctx?.messages||[]).find(m=>String(m.id)===item.message_id);
          const single=(raw?.attachments||[]).length===1,draft=mediaDraft(item);
          return h('div',{class:'assistant-quote'},h('span',{},'Сообщение '+(item.created_at?new Date(item.created_at).toLocaleString('ru-RU'):item.message_id)),
            ...(raw?.attachments||[]).filter(a=>/^https:\/\//i.test(a.url||'')).map(a=>h('a',{href:a.url,target:'_blank',rel:'noopener noreferrer'},h('img',{src:a.url,alt:a.name||'Изображение клиента',style:'max-width:100%;max-height:320px;object-fit:contain'}))),
            single&&!['contact_note','document_image'].includes(draft.content_kind)?h('label',{},'Модель, если отчётливо видна',h('input',{type:'text',maxlength:80,value:draft.model,'aria-label':'Модель с изображения','data-assistant-focus':'media-model-'+item.message_id,
              oninput:e=>{draft.model=e.target.value},style:'box-sizing:border-box;width:100%;padding:8px;border-radius:6px;background:transparent;color:inherit;border:1px solid var(--lc-border,#394057)'})):'',
            single&&['','product_photo','device_label'].includes(draft.content_kind)?h('label',{},'Марка · если видна',h('input',{type:'text',maxlength:60,value:draft.brand,'aria-label':'Марка с изображения','data-assistant-focus':'media-brand-'+item.message_id,
              oninput:e=>{draft.brand=e.target.value},style:'box-sizing:border-box;width:100%;padding:8px;border-radius:6px;background:transparent;color:inherit;border:1px solid var(--lc-border,#394057)'})):'',
            single?h('label',{},'Что изображено',h('select',{'aria-label':'Тип изображения','data-assistant-focus':'media-content-'+item.message_id,onchange:e=>{draft.content_kind=e.target.value;if(!['','product_photo','device_label'].includes(draft.content_kind))draft.brand='';if(['device_message','contact_note','document_image'].includes(draft.content_kind))draft.visual='';if(['contact_note','document_image'].includes(draft.content_kind))draft.model='';if(draft.content_kind!=='device_message'){draft.error_code='';draft.error_system=''}if(draft.content_kind!=='contact_note'){draft.contact_role='';draft.contact_phone=''}draw()},
              style:'box-sizing:border-box;width:100%;padding:8px;background:var(--lc-bg-secondary,#202432);color:inherit;border:1px solid var(--lc-border,#394057)'},
              ...[['','Не указано'],['product_photo','Фото товара'],['product_card','Карточка товара'],['assembly_diagram','Схема сборки'],['device_label','Шильдик / маркировка'],['device_message','Сообщение на экране'],['contact_note','Телефон на фото'],['document_image','Документ / скриншот'],['other','Другое']].map(([value,label])=>h('option',{value,selected:value===draft.content_kind},label)))):'',
            single&&draft.content_kind==='contact_note'?h('label',{},'Чей номер',h('select',{'aria-label':'Принадлежность телефона на фото','data-assistant-focus':'media-contact-role-'+item.message_id,onchange:e=>{draft.contact_role=e.target.value},style:'box-sizing:border-box;width:100%;padding:8px;background:var(--lc-bg-secondary,#202432);color:inherit;border:1px solid var(--lc-border,#394057)'},
              ...[['','Выберите'],['customer','Клиента'],['supplier','Производителя / сервиса'],['unknown','Неясно']].map(([value,label])=>h('option',{value,selected:value===draft.contact_role},label)))):'',
            single&&draft.content_kind==='contact_note'?h('label',{},'Номер',h('input',{type:'tel',maxlength:40,value:draft.contact_phone,'aria-label':'Телефон с изображения','data-assistant-focus':'media-contact-phone-'+item.message_id,oninput:e=>{draft.contact_phone=e.target.value},style:'box-sizing:border-box;width:100%;padding:8px;border-radius:6px;background:transparent;color:inherit;border:1px solid var(--lc-border,#394057)'})):'',
            single&&draft.content_kind==='device_message'?h('label',{},'Система',h('select',{'aria-label':'Система сообщения','data-assistant-focus':'media-system-'+item.message_id,onchange:e=>{draft.error_system=e.target.value},style:'box-sizing:border-box;width:100%;padding:8px;background:var(--lc-bg-secondary,#202432);color:inherit;border:1px solid var(--lc-border,#394057)'},
              ...[['','Выберите'],['xbox_live','Xbox Live'],['windows','Windows'],['printer','Принтер']].map(([value,label])=>h('option',{value,selected:value===draft.error_system},label)))):'',
            single&&draft.content_kind==='device_message'?h('label',{},'Код, если отчётливо виден',h('input',{type:'text',maxlength:40,value:draft.error_code,'aria-label':'Код ошибки с изображения','data-assistant-focus':'media-error-'+item.message_id,oninput:e=>{draft.error_code=e.target.value},style:'box-sizing:border-box;width:100%;padding:8px;border-radius:6px;background:transparent;color:inherit;border:1px solid var(--lc-border,#394057)'})):'',
            single&&!['device_message','contact_note','document_image'].includes(draft.content_kind)?h('label',{},'Основной предмет на фото',h('select',{'aria-label':'Видимые признаки техники','data-assistant-focus':'media-visual-'+item.message_id,onchange:e=>{draft.visual=e.target.value},
              style:'box-sizing:border-box;width:100%;padding:8px;background:var(--lc-bg-secondary,#202432);color:inherit;border:1px solid var(--lc-border,#394057)'},
              ...[['','Не определён'],['pc','Компьютер / системный блок'],['pc_component','Отдельная комплектующая ПК'],['monitor','Монитор'],['tv','Телевизор'],['tv_bands','Телевизор: видны полосы'],['tv_cracks','Телевизор: видны трещины на экране'],['monitor_bands','Монитор: видны полосы'],['rj45','Сетевой кабель: виден RJ45'],['oven','Духовка / плита с духовкой'],['bed_joint','Кровать: разъединён узел'],['wardrobe_holes','Шкаф: повреждены отверстия креплений'],['drawer_front','Ящик: отделился фасад']].map(([value,label])=>h('option',{value,selected:value===draft.visual},label)))):'',
            button('Изображения просмотрены: продолжить проверку',()=>confirmMedia(item),state.busy||!personal.state.active||personal.state.auto,false,'media-confirm-'+item.message_id+'-'+item.signature));
        }));
    }
    async function confirmMedia(item){
      const epoch=state.epoch,id=state.id,revision=state.result?.revision;
      if(state.busy||!revision||!personal.state.active||personal.state.auto)return;
      const draft=mediaDraft(item),observations={};
      if(!['contact_note','document_image'].includes(draft.content_kind)&&draft.model.trim())observations.model=draft.model.trim();
      if(draft.content_kind)observations.content_kind=draft.content_kind;
      if(['','product_photo','device_label'].includes(draft.content_kind)&&draft.brand.trim()){
        observations.brand=draft.brand.trim();
        observations.content_kind=draft.content_kind||'product_photo';
      }
      if(draft.content_kind==='device_message'){
        if(draft.error_code.trim())observations.error_code=draft.error_code.trim();
        if(draft.error_system)observations.error_system=draft.error_system;
      }
      if(draft.content_kind==='contact_note'){
        observations.contact_role=draft.contact_role;
        observations.contact_phone=draft.contact_phone.trim();
      }
      const visible={pc:{device_kind:'pc'},pc_component:{device_kind:'pc_component'},monitor:{device_kind:'monitor'},tv:{device_kind:'tv'},
        tv_bands:{device_kind:'tv',visible_symptom:'tv_screen_bands'},tv_cracks:{device_kind:'tv',visible_symptom:'screen_cracks'},monitor_bands:{device_kind:'monitor',visible_symptom:'screen_bands'},
        rj45:{device_kind:'ethernet_cable',connector_type:'RJ45'},oven:{device_kind:'oven'},
        bed_joint:{device_kind:'bed',visible_symptom:'detached_bed_joint'},
        wardrobe_holes:{device_kind:'wardrobe',visible_symptom:'damaged_fastener_holes'},
        drawer_front:{device_kind:'dresser',visible_symptom:'detached_drawer_front'}}[draft.visual];
      if(visible&&!['device_message','contact_note','document_image'].includes(draft.content_kind))Object.assign(observations,{content_kind:draft.content_kind||'product_photo'},visible);
      state.busy=true;state.error='';state.notice='';draw();
      try{
        const me=await personal.identity();
        const ctx=await loadContext(id),queue=await deps.loadQueue();
        const r=await workflowCall('personal_media_review',{ctx,operatorId:String(me.id),mineCount:queue.mineCount},
          {confirmed:true,revision,message_id:item.message_id,media_signature:item.signature,
           observations,activation_nonce:personal.state.nonce,policy_ack:personal.state.policy,client_version:chrome.runtime.getManifest().version});
        if(!r?.ok)throw Error(r?.error||'Подтверждение просмотра устарело');
        if(epoch===state.epoch){personal.state.nonce=r.activation_nonce;state.result=null;state.workflow=null;state.ctx=ctx;state.stale=true;state.notice='Просмотр сохранён. Подготовьте ответ заново.'}
      }catch(e){if(epoch===state.epoch)state.error=String(e.message||e)}
      finally{if(epoch===state.epoch){state.busy=false;draw()}}
    }
    async function executeReviewed(){
      const epoch=state.epoch,id=state.id,view=state.workflow,p=personal.state;
      if(!view||state.busy||!p.active||p.auto||!visible())return;
      runner?.stop();state.busy=true;state.error='';state.notice='';draw();
      try{const result=await workflow.reviewOne(id,view,{confirmed:true,activation_nonce:p.nonce,policy_ack:p.policy});if(epoch===state.epoch){state.workflow=result;state.result=null}}
      catch(e){if(epoch===state.epoch)state.error=String(e.message||e)}
      finally{if(epoch===state.epoch){state.busy=false;draw()}}
    }
    async function inspectWorkflow() {
      const epoch=state.epoch,id=state.id;state.busy=true;state.error='';state.workflow=null;draw();
      try{const result=await workflow.inspect(id);if(epoch===state.epoch&&currentId()===id)state.workflow=result}
      catch(e){if(epoch===state.epoch)state.error=String(e.message||e)}
      finally{if(epoch===state.epoch){state.busy=false;draw()}}
    }
    async function confirmCall() {
      const epoch=state.epoch,id=state.id;state.busy=true;draw();
      try{
        const me=await personal.identity();
        const ctx=await loadContext(id),queue=await deps.loadQueue();
        const r=await workflowCall('personal_call_confirm',{ctx,operatorId:String(me.id),mineCount:queue.mineCount},{confirmed:true,revision:state.workflow?.revision});
        if(!r?.ok)throw Error(r?.error||'Диалог изменился. Повторите проверку');
        if(epoch===state.epoch){state.error='';state.notice='Звонок подтверждён для текущих данных на 10 минут';state.workflow=null}
      }catch(e){if(epoch===state.epoch)state.error=String(e.message||e)}
      finally{if(epoch===state.epoch){state.busy=false;draw()}}
    }
    async function changeAuthor(event){
      const selectedAuthor=event.currentTarget.value;
      const controlled=personal.nativeRun?.state;
      if(controlled&&(controlled.busy||controlled.stale||controlled.unknown||controlled.view?.state==='running')){
        state.error='Сначала подтвердите остановку серверного бота';draw();return;
      }
      runner?.stop();workflow?.stop();state.epoch++;state.busy=false;state.ctx=null;state.activation=null;state.result=null;state.workflow=null;
      observer?.reset();await personal.selectAuthor(selectedAuthor);await observer?.refresh(0);
    }
    function personalView() {
      const p=personal.state;
      if(nativeRequested)return nativeControls(p);
      if(observer)return observerControls(p);
      return h('div',{class:'assistant-section','data-personal':'1'},
        h('div',{class:'assistant-label'},p.name||'Только для владельца'),
        p.authors.length?h('label',{},'От чьего имени отвечать ',h('select',{'aria-label':'От чьего имени отвечать','data-assistant-focus':'author-selector',value:p.operator,disabled:p.busy,onchange:changeAuthor},...p.authors.map(author=>h('option',{value:author.id,selected:author.id===p.operator},author.full_name+(author.id===p.principal?' (вы)':'')+(p.authors.filter(a=>a.full_name===author.full_name).length>1?' · '+String(author.id).slice(0,8):''))))):'',
        h('div',{class:'assistant-reason',role:'status'},p.active?'Сессия активна':'Сессия остановлена'),
        h('div',{class:'assistant-foot'},'Мои + свободные · Avito/Jivo'),
        h('details',{class:'assistant-sources','data-assistant-disclosure':'work-rules'},h('summary',{},'Правила работы'),h('div',{class:'assistant-foot'},'Без согласований. MAX исключён. Число диалогов не ограничено.')),
        h('div',{class:'assistant-actions'},button(p.active?'Остановить':'Подключить',()=>p.active?personal.stop():personal.start(),!p.active&&p.busy),
          button(p.busy?'Проверяю…':p.more?'Далее':'Проверить очередь',()=>personal.scan(),!p.active||p.busy),
          button(state.wordingMode==='neural_review'?'ИИ · тест':'ИИ · выкл',()=>{
            runner?.stop();workflow?.stop();state.epoch++;
            state.wordingMode=state.wordingMode==='neural_review'?'reviewed':'neural_review';
            state.result=null;state.workflow=null;state.stale=false;
            state.notice=state.wordingMode==='neural_review'?'Каждый ответ ИИ требует отдельной проверки.':'';draw();
          },state.busy||p.auto,false,'neural-review-mode')),
        runner?h('div',{class:'assistant-actions'},button('Репетиция',()=>startRunner('review'),!p.active||p.busy||runner.state.mode==='review'),
          button(p.auto?'Выключить авто':'Включить авто · '+(p.name||'мой аккаунт'),()=>p.auto?stopRunner():requestAuto(),!p.auto&&(!p.active||!p.autoAvailable||p.busy))):'',
        state.activation&&p.active&&!p.auto?h('div',{class:'assistant-notice',role:'alert'},
          h('div',{class:'assistant-label'},'Включить работу от аккаунта «'+p.name+'»?'),
          h('p',{},'Помощник будет брать свободные профильные диалоги, отвечать клиентам и создавать заявки. Репетиция выполняется без отправок.'),
          h('div',{class:'assistant-actions'},button('Отмена',()=>{state.activation=null;draw()}),
            button('Подтверждаю: включить рабочий авто',confirmAuto,p.busy))):'',
        runner?h('div',{class:'assistant-foot',role:'status'},runner.state.mode==='auto'?'Авто включено':runner.state.mode==='review'?'Репетиция · без отправок':runner.state.mode==='starting'?'Подтверждаю режим…':'Цикл остановлен',runner.state.lastMs?' · последняя проверка '+(runner.state.lastMs/1000).toFixed(1)+' с':''):'',
        runner?.state.error?h('div',{class:'assistant-notice'},runner.state.error):'',
        !observer&&runner?.state.rows.length?h('details',{class:'assistant-sources',open:''},h('summary',{},'Действия'),...runner.state.rows.map(r=>h('div',{class:'assistant-quote'},h('b',{},r.name||'Клиент'),
          h('span',{},(r.executed?'Результат: ':'План: ')+({claim:'взять диалог',reply:'ответить',wait:r.reply?'ответ отправлен, ждём клиента':'ждём клиента',prepare_crm:'создать и сверить заявку',done:'заявка создана и сверена',handoff:'нужен оператор',created_review:'проверь созданную заявку'}[r.step]||r.step)),
          r.reply?h('div',{class:'assistant-draft'},r.reply):'',r.crm_id&&['done','created_review'].includes(r.step)?h('span',{},'Заявка № '+r.crm_id):'',
          r.reason||'',...(r.reasons||r.crm?.reasons||[]).map(t=>h('span',{},t)),button('Посмотреть',()=>openReviewedDialog(r.id),false,false,'runner-open-'+r.id)))):'',
        p.error?h('div',{class:'assistant-notice',role:'alert'},p.error):'',
        p.checked?h('div',{class:'assistant-reason'},'Проверено '+p.offset+' из '+p.total+' · у помощника '+p.managed+' · назначено аккаунту '+p.mine):'',
        !observer&&p.rows.length?h('details',{class:'assistant-sources','data-assistant-disclosure':'queue',...(!state.result?{open:''}:{})},
          h('summary',{},'Очередь · подходят '+p.rows.filter(r=>r.eligible).length+' · пропущены '+p.rows.filter(r=>!r.eligible).length),
          ...p.rows.filter(r=>r.eligible).map(queueRow),
          p.rows.some(r=>!r.eligible)?h('details',{class:'assistant-sources',...(state.skipsOpen?{open:''}:{}),ontoggle:e=>{state.skipsOpen=e.currentTarget.open}},h('summary',{},'Почему пропущены'),...p.rows.filter(r=>!r.eligible).map(queueRow)):''):'',
        p.log.length?h('details',{class:'assistant-sources'},h('summary',{},'События сессии'),...p.log.map(e=>h('div',{class:'assistant-quote'},new Date(e.at).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})+' · '+e.text))):'');
    }
    function nativeControls(p){
      const s=nativeRun?.state,live=s?.view?.principal_id===p.principal?s.view:null;
      const active=live?.state==='running',busy=!!s?.busy,unknown=!!s?.unknown;
      const auto=active&&live.mode==='auto';
      const working=auto&&live.configured&&live.worker_ready;
      const confirmed=!!live&&!s.stale,review=runner?.state.mode==='review';
      const canStart=confirmed&&!active&&!unknown&&live.start_available&&!busy&&!!p.operator;
      const author=p.authors.find(a=>a.id===(active?live.operator_id:p.operator));
      const authorName=a=>a.full_name+(p.authors.filter(other=>other.full_name===a.full_name).length>1?' · '+a.id.slice(0,8):'');
      const label=!live?'Состояние сервера не подтверждено':s.stale
        ?auto?'Последнее подтверждение: бот работал · связь потеряна':'Связь потеряна · состояние может измениться'
        :working?'Бот работает на сервере':auto?'Авто включено · работа обработчика не подтверждена':active?'Серверный запуск без авто · отправки выключены':live.state==='blocked'?'Запуск остановлен после ошибки':'Серверный бот остановлен';
      return h('div',{class:'assistant-section','data-personal':'1'},
        h('div',{class:'observer-controls-main'},
          h('div',{class:'observer-owner'},h('small',{},'LeadChat · серверный бот'),h('strong',{},author?authorName(author):active?'Автор недоступен':'Выберите автора'),
            h('span',{class:'observer-session'+(confirmed&&working?' running':''),role:'status'},h('i',{'aria-hidden':'true'}),label)),
          p.authors.length?h('label',{class:'observer-author'},'От чьего имени отвечать',h('select',{
            'aria-label':'От чьего имени отвечать','data-assistant-focus':'author-selector',value:active?live.operator_id:p.operator,
            disabled:!confirmed||active||busy||unknown||p.busy,onchange:changeAuthor},
            ...p.authors.map(a=>h('option',{value:a.id,selected:a.id===(active?live.operator_id:p.operator)},authorName(a)+(a.id===p.principal?' (вы)':''))))):''),
        h('div',{class:'observer-control-actions'},
          button(unknown?'Проверяем команду…':active?auto?'Остановить авто':'Остановить запуск':'Запустить авто',()=>active?stopRunner():requestAuto(),busy||unknown||(!active&&!canStart),!active,'observer-auto'),
          button('Обновить состояние',()=>nativeRun?.inspect().catch(()=>{}),busy,false,'native-refresh'),
          runner?button('Репетиция',()=>startRunner('review'),!confirmed||active||unknown||!p.active||p.busy||busy||review):'',
          button(p.active?'Отключить репетицию':'Подключить репетицию',()=>p.active?personal.stop():personal.start(),p.busy,false,'observer-connect')),
        h('div',{class:'assistant-foot'},'Репетиция: '+(p.active?'подключена':'отключена')+' · закрытие панели не останавливает серверного бота'),
        state.activation?.native?h('div',{class:'assistant-notice',role:'alert'},
          h('div',{class:'assistant-label'},'Запустить авто от имени «'+(author?.full_name||p.name)+'»?'),
          h('p',{},'Бот будет отвечать клиентам и доводить новые обращения до заявки. Уже созданные заявки, переносы и претензии остаются сотрудникам.'),
          h('div',{class:'assistant-actions'},button('Отмена',()=>{state.activation=null;draw()}),
            button('Подтверждаю: включить рабочий авто',confirmAuto,busy))):'',
        s?.error?h('div',{class:'assistant-notice',role:'alert'},s.error):'',
        !nativeRun?h('div',{class:'assistant-notice',role:'alert'},'Обновите расширение: серверное управление не загружено'):'',
        confirmed&&!active&&!live.start_available?h('div',{class:'assistant-reason'},'Серверный запуск ещё не подготовлен. Авто не включено'):'',
        Number.isFinite(s?.lastConfirmedAt)?h('div',{class:'assistant-foot'},'Сервер проверен: '+new Date(s.lastConfirmedAt).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',second:'2-digit'})):'',
        p.error?h('div',{class:'assistant-notice',role:'alert'},p.error):'',
        h('details',{class:'assistant-sources','data-assistant-disclosure':'work-rules'},h('summary',{},'Условия работы'),
          h('div',{class:'assistant-foot'},'Панель нужна для наблюдения и управления. Для остановки бота используйте «Остановить авто». Репетиция выполняется отдельно, без отправок.')));
    }
    function observerControls(p){
      const mode=runner?.state.mode,active=mode==='auto',review=mode==='review';
      return h('div',{class:'assistant-section','data-personal':'1'},
        h('div',{class:'observer-controls-main'},
          h('div',{class:'observer-owner'},h('small',{},'Управление'),h('strong',{},p.authors.find(a=>a.id===p.principal)?.full_name||'Администратор'),
            h('span',{class:'observer-session'+(active?' running':''),role:'status'},h('i',{'aria-hidden':'true'}),active?'Авто включено':review?'Репетиция · без отправок':p.active?'Подключён · авто выключено':'Авто выключено')),
          p.authors.length?h('label',{class:'observer-author'},'От чьего имени отвечать',h('select',{'aria-label':'От чьего имени отвечать','data-assistant-focus':'author-selector',value:p.operator,disabled:p.busy,onchange:changeAuthor},...p.authors.map(author=>h('option',{value:author.id,selected:author.id===p.operator},author.full_name+(author.id===p.principal?' (вы)':'')+(p.authors.filter(a=>a.full_name===author.full_name).length>1?' · '+String(author.id).slice(0,8):''))))):''),
        h('div',{class:'observer-control-actions'},
          !p.active?button(p.busy?'Подключаю…':'Подключить',()=>personal.start(),p.busy,true,'observer-connect'):
            button('Отключить',()=>personal.stop(),p.busy,false,'observer-disconnect'),
          runner?button('Репетиция',()=>startRunner('review'),!p.active||p.busy||review):'',
          runner?button(p.auto?'Остановить авто':'Запустить авто',()=>p.auto?stopRunner():requestAuto(),!p.auto&&(!p.active||!p.autoAvailable||p.busy),!p.auto,'observer-auto'):''),
        state.activation&&p.active&&!p.auto?h('div',{class:'assistant-notice',role:'alert'},
          h('div',{class:'assistant-label'},'Запустить авто от имени «'+p.name+'»?'),
          h('p',{},'Бот будет принимать свободные профильные диалоги, отвечать клиентам и создавать заявки. После сверки заявки и служебной отписки в Telegram диалог закрывается. Переносы и претензии остаются сотрудникам.'),
          h('div',{class:'assistant-actions'},button('Отмена',()=>{state.activation=null;draw()}),button('Подтверждаю: включить рабочий авто',confirmAuto,p.busy))):'',
        runner?.state.error?h('div',{class:'assistant-notice',role:'alert'},runner.state.error):'',
        p.error?h('div',{class:'assistant-notice',role:'alert'},p.error):'',
        Number.isFinite(p.lastConfirmedAt)?h('div',{class:'assistant-foot'},'Последняя связь: '+new Date(p.lastConfirmedAt).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',second:'2-digit'})):'',
        p.active&&!p.autoAvailable?h('div',{class:'assistant-reason'},'Авто ещё не доступно для этой сессии. Можно выполнить проверку без отправок.'):'',
        h('details',{class:'assistant-sources','data-assistant-disclosure':'work-rules'},h('summary',{},'Условия работы'),h('div',{class:'assistant-foot'},'Только доступные профильные диалоги. MAX и согласования исключены. Смена автора останавливает авто. В «Репетиции» отправок и создания заявок нет.')));
    }
    async function requestAuto(){
      if(nativeRequested){
        state.activation=null;runner?.stop();workflow?.stop();
        try{if(!nativeRun)throw Error('Серверное управление ещё не загружено');state.error='';state.activation={native:await nativeRun.prepareStart()}}
        catch(error){state.error=error.message}draw();return;
      }
      const p=personal.state;if(!p.active||!p.autoAvailable||p.auto||p.busy)return;
      runner.stop();state.activation={operator:p.operator,policy:p.policy,nonce:p.nonce,expires:Date.now()+60000};draw();
    }
    async function confirmAuto(){
      const a=state.activation,p=personal.state;state.activation=null;
      if(nativeRequested){
        try{if(!a?.native||!nativeRun)throw Error('Подтверждение устарело');state.error='';
          await deps.onPersonalStart?.();await nativeRun.start(a.native)}
        catch(error){state.error=error.message}draw();return;
      }
      if(!a||a.expires<=Date.now()||!p.active||!p.autoAvailable||a.operator!==p.operator||a.policy!==p.policy||a.nonce!==p.nonce){state.error='Подтверждение устарело. Проверьте аккаунт и повторите включение';draw();return}
      await startRunner('auto');
    }
    async function startRunner(mode){
      state.activation=null;
      try{
        if(nativeRequested){
          if(mode!=='review'||!nativeRun)throw Error('Рабочий авто запускается только на сервере');
          const live=await nativeRun.inspect();
          if(!live||nativeRun.state.stale||nativeRun.state.unknown||live.state==='running')throw Error('Сначала подтвердите остановку серверного бота');
        }
        if(mode==='auto')state.wordingMode='neural_auto';else if(state.wordingMode==='neural_auto')state.wordingMode='neural_review';
        state.error='';await runner.start(mode);
      }catch(e){state.error=String(e.message||e);draw()}
    }
    async function stopRunner(){
      runner?.stop();workflow?.stop();
      try{if(nativeRequested){if(!nativeRun)throw Error('Серверное управление не загружено');await nativeRun.stop()}
        else await personal.setMode('review')}
      catch(e){state.error=String(e.message||e)}draw();
    }
    async function openReviewedDialog(id){
      await deps.onOpenDialog(id);await open();
      if(workflow&&state.id===id&&currentId()===id)await inspectWorkflow();
    }
    function queueRow(row) {
      return h('div',{class:'assistant-quote'},h('b',{},row.name+' · '+(row.scope==='mine'?'Мой':'Свободный')),
        h('span',{},row.eligible?'Подходит для личного помощника':row.reason),
        row.eligible&&row.planned_actions?h('span',{},'План: '+row.planned_actions.join(' → ')):'',
        deps.onOpenDialog?button('Открыть диалог',()=>openReviewedDialog(row.id),false,false,'queue-open-'+row.id):'');
    }
    function evidence(facts) {
      return h('details', { class: 'assistant-sources' }, h('summary', {}, 'Откуда взяты данные'),
        ...Object.entries(facts.evidence || {}).map(([field, value]) => h('div', { class: 'assistant-quote' },
          h('b', {}, ({ contact_phone_to_use: 'Номер для связи', 'address.street': 'Улица', 'address.building': 'Дом', 'address.office': 'Квартира / ЧД' })[field] || field),
          h('span', {}, value.quote || ''), h('small', {}, 'Сообщение ' + value.message_id))));
    }
    async function open() {
      stop(false); last = ''; state.epoch++; state.id = currentId() || (personal?'__personal__':''); state.result = null;state.workflow=null;state.mediaFacts=new Map();state.audit=[];state.auditExpanded.clear();state.auditMore=null;state.auditBusy=false;state.auditError=''; state.ctx = null; state.error = '';state.notice=''; state.stale = false; state.paused = false; state.busy = false;state.rendered=false;
      panel.classList.add('open'); panel.dataset.assistant = state.id;
      if (!state.id) { panel.replaceChildren(h('div', { class: 'ph' }, header('', { title: 'Помощник' })), h('div', { class: 'pb' }, 'Выберите диалог клиента.')); return; }
      draw();
      if(deps.getAuthors&&personal)try{await personal.prepare()}catch(e){state.error=String(e.message||e);draw()}
      if(nativeRun){try{await nativeRun.inspect();await syncNativeObservation()}catch(_error){/* Stale server state stays visible. */}nativeRun.watch()}
      if(observer)await observer.refresh();
      timer = setInterval(checkLatest, 5000);
    }
    async function preview() {
      if (state.busy || state.paused || !visible()) return;
      const epoch = ++state.epoch, id = state.id;
      state.busy = true; state.error = '';state.notice=''; draw();
      try {
        const ctx = await loadContext(id);
        if (epoch !== state.epoch || currentId() !== id) return;
        state.ctx = ctx;
        last = (ctx.messages || []).slice(-1)[0]?.id || '';
        const previous=state.result;
        const saved=(previous?.research_job_id||previous?.pending_admission)&&previous.request_id&&previous.revision
          ?{research_job_id:previous.research_job_id,request_id:previous.request_id,revision:previous.revision}:null;
        if(saved&&state.stale){
          const cancelled=await call('research_cancel',saved);
          if(cancelled?.ok===false&&cancelled.code!=='research_stopped')throw Error('Отмена прежнего исследования не подтверждена');
        }
        let result = saved&&!state.stale?await call('research_status',saved):await call('preview', {wording_mode:state.wordingMode});
        if(result?.research_state==='accepted')result=await call('research_finalize',{...saved,research_job_id:result.research_job_id});
        if(result?.visual_observation_ready===true)result=await call('preview',{wording_mode:state.wordingMode});
        if (epoch !== state.epoch || currentId() !== id) return;
        if (!result || result.ok === false) {if(result?.code==='paused')state.paused=true;throw new Error(result?.error || 'Не удалось подготовить ответ');}
        state.result = result; state.stale = result.code === 'stale';
        await checkLatest(true);
      } catch (error) { if (epoch === state.epoch) state.error = String(error.message || error); }
      finally { if (epoch === state.epoch) { state.busy = false; draw(); } }
    }
    async function checkLatest(force) {
      const epoch=state.epoch,id=state.id;
      if(observer&&visible())await observer.refresh();
      if(epoch!==state.epoch||id!==state.id)return;
      if (visible() && (currentId() || (personal?'__personal__':'')) !== state.id) { await open(); return; }
      if ((!visible() || !state.ctx || checking || state.stale) && !force) { if (!visible()) stop(); return; }
      checking = true;
      try {
        const now = await latestId(id);
        if(epoch!==state.epoch||id!==state.id)return;
        if (now && now !== last) {
          state.stale = true;
          const fresh = await loadContext(id);
          if(epoch!==state.epoch||id!==state.id)return;
          const observed=await identified('observe',identity=>{
            if(epoch!==state.epoch||id!==state.id)throw Error('Открыт другой диалог');
            return send({ kind: 'lcz-assistant', args: { action: 'observe', ctx: fresh,...identity } });
          });
          if(epoch!==state.epoch||id!==state.id)return;
          if(!observed||observed.ok===false)throw Error('Свежесть источника не подтверждена');
          draw();
        }
      } catch (_e) { if(epoch===state.epoch&&id===state.id){state.stale = true; state.error = 'Не удалось проверить свежесть диалога. Подготовьте ответ заново.'; draw();} }
      finally { checking = false; }
      if(epoch!==state.epoch||id!==state.id)return;
      if(!force&&!state.busy&&!state.stale&&!state.paused&&visible()
          &&(state.result?.pending_research||state.result?.requires_root))await preview();
    }
    async function validate() {
      if (!state.result || state.stale || state.paused) throw new Error('Ответ устарел или подсказки остановлены');
      const epoch=state.epoch,id=state.id,selected=state.result;
      const current=()=>epoch===state.epoch&&id===state.id&&currentId()===id&&state.result===selected&&!state.stale&&!state.paused;
      const ctx = await loadContext(id);
      if (!current()) throw new Error('Открыт другой диалог или ответ изменился');
      const result = await identified('validate',identity=>{
        if(!current())throw Error('Открыт другой диалог или ответ изменился');
        return send({ kind: 'lcz-assistant', args: { action: 'validate', ctx, draft_id: selected.draft_id,...identity } });
      });
      if(!current())throw Error('Открыт другой диалог или ответ изменился');
      if (!result || result.ok === false) { state.stale = true; throw new Error('Диалог изменился. Подготовьте ответ заново.'); }
      return result;
    }
    async function copy() {
      state.error='';state.notice='';
      try { const result = await validate(); await navigator.clipboard.writeText(result.reply); state.notice = 'Ответ скопирован'; }
      catch (error) { state.error = String(error.message || error); }
      draw();
    }
    async function useFacts() {
      try { await validate(); stop(); panel.dataset.assistant = ''; await onUseFacts(state.id, state.result); }
      catch (error) { state.error = String(error.message || error); draw(); }
    }
    async function togglePause() {
      if (state.busy || currentId() !== state.id) return;
      const epoch = state.epoch;
      workflow?.stop();
      state.busy = true; draw();
      try {
        if (!state.ctx) state.ctx = await loadContext(state.id);
        if (epoch !== state.epoch || currentId() !== state.id) return;
        const action = state.paused ? 'resume' : 'takeover';
        const result = await call(action);
        if (!result || result.ok === false) throw new Error(result?.error || 'Не удалось изменить состояние');
        if (epoch !== state.epoch || currentId() !== state.id) return;
        state.paused = !state.paused; state.stale = true; state.result = null; state.error = '';
      } catch (error) { if (epoch === state.epoch) state.error = String(error.message || error); }
      finally { if (epoch === state.epoch) { state.busy = false; draw(); } }
    }
    function stop(endPersonal=true) { state.activation=null;clearInterval(timer); timer = 0;nativeRun?.unwatch();if(endPersonal){runner?.stop();workflow?.stop();if(personal)personal.stop('panel_closed').catch(()=>{})} }
    window.addEventListener('pagehide',()=>{nativeRun?.unwatch();runner?.stop();personal?.stop().catch(()=>{})});
    const wakeConnection=()=>{if(personal?.checkLease())personal.heartbeat('wake').catch(()=>{});else draw()};
    window.addEventListener('focus',wakeConnection);
    window.addEventListener('online',wakeConnection);
    document.addEventListener?.('visibilitychange',()=>{if(!document.hidden)wakeConnection()});
    return { open, stop, state, draw, preview, validate, togglePause,personal,runner,nativeRun,wake:event=>runner?.wake(event),canSubmit:stamp=>workflow?.isCurrent(stamp)===true };
  }
  return { create };
})();
if (typeof module !== 'undefined' && module.exports) module.exports = LC_ASSISTANT_UI;
