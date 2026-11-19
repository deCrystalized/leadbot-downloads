/* Работа с CRM лид-центра: подготовка (что будет выбрано) и создание заявки */
chrome.runtime.onMessage.addListener((msg, _sender, respond) => {
  if (!msg || typeof msg !== 'object' || Array.isArray(msg) || msg.target !== 'lcz-offscreen') return;
  if(msg.args?.nativeOffice&&(_sender?.id!==chrome.runtime.id||_sender.tab)){
    respond({ok:false,refused:true,crm_create_dispatched:false,error:'Не подтверждён фон серверного исполнителя CRM'});return;
  }
  const nativePhase=(phase,report)=>chrome.runtime.sendMessage({
    kind:'lcz-native-office-phase',ticket:msg.args.nativeOffice,phase,
    fields:{dir:msg.args.dir,lead:msg.args.lead,sel:msg.args.sel,allowLive:msg.args.allowLive},
    ...(report?{report}:{}),
  });
  const ops = {
    prepare: () => CRM.prepare(msg.args),
    create: () => CRM.create({...msg.args,
      ...(msg.args?.personalWorkflow?{_beforeSubmit:()=>chrome.runtime.sendMessage({kind:'lcz-personal-guard',guard:msg.args.workflow_guard})}:{}),
      ...(msg.args?.nativeOffice?{
        _beforeSubmit:context=>nativePhase(context.phase,context.id?{id:context.id,dir:context.dir}:undefined),
        _created:report=>nativePhase('created',report),
      }:{}),
    }),
    existing: () => CRM.existing(msg.args || {}),
    info: async () => ({ ok: true, info: await CRM.requestInfo(msg.args.dir, msg.args.id) }),
    reschedule: () => CRM.reschedule(msg.args || {}),
    zakrep: () => CRM.zakrep(msg.args || {}),
    returnToAwait: () => CRM.returnToAwait(msg.args || {}),
    claims: async () => ({ ok: true, ...(await CRM.claimsFor(msg.args.dir, msg.args.id)) }),
    // 2.2.9: «Отмена КЦ / Филиал» из карточки «по заявке» — тем же ядром, что карточка действия (crmact: как кнопка CRM, пустой
    // «Дальний выезд» — «Нет», пустой город — «КЦ», ошибки CRM у полей — словами, ответ CRM — в итоге); ответ — в прежнем виде
    cancelKc: () => отменаЯдром(msg.args || {}),
    claim: () => CRM.createClaim(msg.args || {}),
    comments: () => CRM.saveCardComments(CRM.BASES[msg.args.dir], msg.args.id, msg.args.change || {}),
    // адрес клиента по заявке: dry — что поменяется, без записи; иначе — правка карточки клиента
    customerAddress: () => CRM.customerAddress(msg.args || {}),
    appl: async () => ({ ok: true, list: await CRM.applFor(msg.args.dir, msg.args.cityId) }),
    sub: async () => ({ ok: true, list: await CRM.subFor(msg.args.dir, msg.args.cityId, msg.args.applId, msg.args.appl, msg.args.hasPartner) }),
    // 1.20: снимок карточки без личных данных и одно действие с заявкой (замок, сверка, проверка — внутри CRM_ACT)
    snap: () => CRM_ACT.snap(msg.args || {}),
    act: () => CRM_ACT.act(msg.args || {}),
    // настройки, «Состояние»: есть ли вход в каждую базу CRM — только ЧТЕНИЕ страницы формы заявки (её же читает подготовка);
    // страница входа вместо неё — «войдите». Ничего не пишет
    session: () => сессииCRM(),
  };
  if (typeof msg.op !== 'string' || !Object.prototype.hasOwnProperty.call(ops, msg.op)) return;
  const f = ops[msg.op];
  // исключение здесь — почти всегда сеть или вход в CRM, а не форма
  f().then(respond).catch((e) => respond({ ok: false, error: String(e.message || e) }));
  return true;
});

async function сессииCRM() {
  const { BASES, getСрок } = CRM._внутр;
  const out = {};
  await Promise.all(Object.entries(BASES).map(async ([dir, base]) => {
    const x = { url: base + '/' };
    try {
      const r = await getСрок(base + '/admin/domain/customer-request/create', { credentials: 'include' }, 10000);
      const t = await r.text();
      if (/\/login/i.test(r.url || '') || /name="LoginForm\[|type="password"/i.test(t)) x.in = false;
      else if (r.ok === false || r.status >= 400) { x.in = null; x.error = 'CRM ответила ' + r.status; }
      else x.in = true;
    } catch (e) { x.in = null; x.error = String((e && e.message) || e).slice(0, 100); }
    out[dir] = x;
  }));
  return { ok: true, bases: out };
}

/* 2.2.9: прежняя «Отмена» (карточка «по заявке», ИИ понял «отмените») шла своим путём crm.js cancelKc — без «Дальнего выезда» «Нет», без
   разбора ответа CRM. Теперь — ядро действий (crmact, рецепт flag 10 / 11), итог — как ждёт экран: {ok, already, status, by, url, error} */
async function отменаЯдром(a) {
  const by = a.by === 'branch' ? 'branch' : 'kc';
  const comment = String(a.comment || '').trim(), service = String(a.service || '').trim();
  const r = await CRM_ACT.act({ dir: a.dir, id: a.id, recipe: 'flag', key: a.key || '', ...(a.заполнить ? { заполнить: a.заполнить } : {}),
    params: { code: by === 'branch' ? 11 : 10, ...(comment ? { addComment: comment, addPartner: comment } : {}), ...(service ? { addService: service } : {}) } });
  const url = CRM.BASES[a.dir] && a.id ? CRM.BASES[a.dir] + '/admin/domain/customer-request/update?id=' + a.id : '';
  if (r && r.ok) return { ok: true, already: !!r.already, status: (r.after && r.after.statusName) || '', by, url, ...(r.заметки ? { заметки: r.заметки } : {}), ...(r.warnings ? { warnings: r.warnings } : {}) };
  const e = String((r && r.error) || 'CRM не отменила');
  return { ok: false, error: e + (r && r.crmReply && !e.includes(r.crmReply) ? ' Ответ CRM: ' + r.crmReply : ''), code: (r && r.code) || '', crmReply: (r && r.crmReply) || '', url, ...(r && r.поля ? { поля: r.поля } : {}) };
}
