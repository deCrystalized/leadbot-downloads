/* КАРТОЧКА КЛИЕНТА — действия «Верный адрес», «Другой номер», «Имя клиента» (1.20, PE) для сетки «Действия по заявке».
   Здесь — каталог, превью (план) и тексты; пишет в CRM crmcust.js в offscreen (op 'custSnap' — чтение, 'custAct' — запись).
   Регистрируются в LC_ACT через LC_ACT.добавить (actions.js грузится раньше). Записи — только по клику оператора на превью.
   Владелец 08.10: В8 — в «Ожидает», «В пути», «На уточнении», «Модерация»; текст адреса в город утверждён (§11 п.2).
   Все тексты и пороги — в НАСТРОЙКИ (одна таблица): поменять после ответа владельца можно здесь, не трогая код. */
const LC_ACT_CUST = (() => {
  const НАСТРОЙКИ = {
    включено: true,
    статусы: [1, 4, 3, 2],               // В8: Ожидает, В пути, На уточнении, Модерация
    адресВФормеЗаявки: [2, 3],          // в этих статусах адрес клиента есть и в форме заявки (живой CRM, раздел 4)
    квартираЗаМин: 10,                   // рег:1357: квартиру городу — за 10 мин до визита или когда мастер на адресе
    территорияЖдёмМс: 9000,              // как у создания: карта не ответила — пишем об этом, а не ждём
    группа: 'Клиент',
    подписи: { addr: 'Верный адрес', phone_add: 'Другой номер', name: 'Имя клиента' },
    иконки: { addr: 'pin', phone_add: 'phone', name: 'user' },
    тексты: {
      адресВЧат: (id, дом) => id + ' верный адрес: ' + дом,                   // владелец 08.10 (§11 п.2)
      точка: (pt) => 'https://yandex.ru/maps/?pt=' + pt[0] + ',' + pt[1] + '&z=17',   // рег:1351–1357: ссылка на точку
      номерВЧат: (id) => id + ' у клиента другой номер — внесли в карточку клиента',  // сам номер — только «Стык» (рег:865–883)
      комментарийАдреса: 'Адрес изменён клиентом{время}: {адрес}',             // как p12; {адрес} подставит CRM-шаг
      служебныйНомер: 'Звонить по второму номеру',                              // рег:1091
      полиция: (id) => 'Мент по ' + id,                                         // рег:1272–1275
      клиентуАдрес: (стр) => 'Записал адрес: ' + стр + '.',                      // В7: по галочке, по умолчанию выкл.
      клиентуНомер: 'Записал ваш номер — мастер позвонит на него.',
    },
    предупреждения: {
      штрафАдреса: 'ошибка адреса — штраф 300–1500 ₽ (рег:1552–1555, 1624–1627): сверьте адрес с клиентом',
      штрафНомера: 'неверный номер — штраф 500 ₽ (рег:1579): сверьте цифры с клиентом',
      безИмени: 'если клиент не назвался — «М» или «Ж» (рег:1034–1035)',
      полиция: 'рег:1272–1275: в имени клиента — «Мент по <ID>»; номер звонившего — ответом на «Новая претензия» в чат претензий (впишите сами)',
    },
  };
  const Т = НАСТРОЙКИ.тексты, П = НАСТРОЙКИ.предупреждения;
  const СТАТУС_ИМЯ = { 1: 'Ожидает', 4: 'В пути', 3: 'На уточнении', 2: 'Модерация' };

  const картаИз = (snap) => (snap && snap.card ? snap.card : snap || {});
  const тел10 = (s) => { const d = String(s || '').replace(/\D/g, ''); return d.length === 10 ? d : d.length === 11 && /^[78]/.test(d) ? d.slice(1) : ''; };
  const видНомера = (d) => '+7 ' + d.slice(0, 3) + '-' + d.slice(3, 6) + '-' + d.slice(6, 8) + '-' + d.slice(8);
  const маска = (d) => (d && d.length === 10 ? '+7 ' + d[0] + '••-•••-••' + d.slice(8) : '—');
  const чисто = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const чистыйАдрес = (a) => {
    a = a || {};
    const out = { settlement: чисто(a.settlement), street: чисто(a.street), building: чисто(a.building), office: чисто(a.office),
      entrance: чисто(a.entrance), floor: чисто(a.floor), intercom: !!a.intercom };
    return out;
  };
  const сДомом = (a) => !!(a && a.building && (a.street || a.settlement));
  /* Ввод адреса — в ввод.addr; экран (PC) отдаёт поля плоско («street») или с точкой («addr.street») — сводим в одно */
  const ЧАСТИ = ['settlement', 'locality', 'street', 'building', 'office', 'entrance', 'floor', 'intercom', 'pt', 'ptLocality'];
  function нормВвод(ввод) {
    const в = { ...(ввод || {}) };
    const a = { ...(в.addr && typeof в.addr === 'object' ? в.addr : {}) };
    for (const k of ЧАСТИ) for (const n of ['addr.' + k, k]) if (в[n] !== undefined && a[k] === undefined) a[k] = в[n];
    if (a.settlement === undefined && a.locality !== undefined) a.settlement = a.locality;
    if (Object.keys(a).length) в.addr = a;
    return в;
  }
  // для какого ввода прочитано превью: оператор поправил адрес/номер, а экран не перечитал — превью не то, что уйдёт в CRM
  function ключВвода(key, ввод) {
    ввод = нормВвод(ввод);
    if (key === 'addr') { const a = чистыйАдрес(ввод.addr); return сДомом(a) ? JSON.stringify(a) : ''; }
    if (key === 'phone_add') return тел10(ввод.phone) ? тел10(ввод.phone) + '|' + String(ввод.replace || '') : '';
    return '';
  }
  // для какого ввода прочитано: ctx.для, а если экран переложил в ctx только cust — метка в самом чтении (cust.для)
  const превьюНеТо = (key, ввод, ctx) => {
    const для = !ctx ? undefined : ctx.для !== undefined ? ctx.для : ctx.cust && ctx.cust.для;
    return для !== undefined && для !== ключВвода(key, ввод) ? 'ввод изменился — обновляю превью…' : '';
  };
  const статусРазрешён = (card) => НАСТРОЙКИ.статусы.includes(Number(card.statusCode));
  const можноГде = () => НАСТРОЙКИ.статусы.map((k) => '«' + СТАТУС_ИМЯ[k] + '»').join(', ');
  const стоит = (v) => v === true || v === 1 || v === '1';

  // один и тот же город: «Мытищи (МСК)» = «Мытищи», «СПБ 2» = «Санкт-Петербург» (имена — как у карты территорий)
  function тотЖеГород(a, b) {
    const T = typeof LC_TERRITORY !== 'undefined' ? LC_TERRITORY : null;
    if (T && T.городаИмени && T.чистыйГород) { const x = T.городаИмени(T.чистыйГород(a)), y = T.городаИмени(T.чистыйГород(b)); return x.some((n) => y.includes(n)); }
    const n = (s) => String(s || '').toLowerCase().replace(/ё/g, 'е').replace(/\s*\(.*?\)\s*/g, ' ').replace(/\s*\d+\s*$/, '').trim();
    return !!n(a) && n(a) === n(b);
  }

  /* ТЕРРИТОРИЯ НОВОГО АДРЕСА (расчёт background lcz-territory) против заявки: филиал, «Дальний выезд», согласование.
     Только предупреждения и предложение следующего действия — флаги заявки здесь не пишем */
  function территорияАдреса(terr, card, cust) {
    const out = { warnings: [], follow: null };
    if (!terr) return out;
    if (!terr.ok) { out.warnings.push('территорию нового адреса проверить не удалось (' + чисто(terr.error || 'карта не ответила').slice(0, 80) + ') — проверьте по карте: филиал и «Дальний выезд»'); return out; }
    const город = card.cityName || (cust && cust.card && cust.card.cityName) || '';
    const почему = (terr.why || []).join('; ');
    // карта не загрузилась / город не известен — решение по черте города или наугад: снимать «Дальний выезд» по нему нельзя
    const неТочно = !!terr.noMap || (terr.why || []).some((w) => /проверьте территорию/i.test(w));
    if (неТочно) out.warnings.push('территория нового адреса определена неточно (' + (почему || 'карта').slice(0, 120) + ') — филиал и «Дальний выезд» проверьте по карте');
    if (terr.branch && город && !тотЖеГород(terr.branch, город)) {
      out.warnings.push('новый адрес — на территории «' + terr.branch + '», а заявка в городе «' + город + '»: согласуйте с городом, какой филиал поедет');
    }
    if (terr.approval) out.warnings.push('новый адрес — по согласованию с филиалом' + (почему ? ': ' + почему : ''));
    // «Дальний выезд» (только КП, поле есть и не disabled): снимок заявки PA (flags/flagsEnabled), иначе — карточка из custSnap
    const ф = card.flags || {};
    let есть = ф.farRide !== undefined && ф.farRide !== null, сейчас = стоит(ф.farRide);
    if (есть && card.flagsEnabled && card.flagsEnabled.farRide === false) есть = false;
    if (!есть && cust && cust.card && cust.card.farRide && !cust.card.farRide.disabled) { есть = true; сейчас = cust.card.farRide.value === '1'; }
    if (есть && terr.far && !сейчас) {
      out.warnings.push('новый адрес — за чертой: нужен «Дальний выезд», а в заявке его нет — поставьте следующим действием');
      out.follow = { key: 'flags', ввод: { farRide: true }, почему: 'новый адрес за чертой — «Дальний выезд»' };
    } else if (есть && !terr.far && сейчас && !terr.satelliteOf && !неТочно) {
      out.warnings.push('в заявке стоит «Дальний выезд», а новый адрес в черте — снимите его, если город согласен');
      out.follow = { key: 'flags', ввод: { farRide: false }, почему: 'новый адрес в черте — «Дальний выезд» не нужен' };
    } else if (!есть && terr.far && card.dir === 'kp') out.warnings.push('новый адрес — за чертой («Дальний выезд»), а поле в заявке недоступно — сообщите городу');
    const низ = parseFloat(String(terr.hours || '').replace(',', '.'));
    if (низ >= 2) out.warnings.push('по новому адресу принимают за ' + terr.hours + ' ч' + (terr.earliest ? ', с ' + terr.earliest : '') + ' — проверьте время визита');
    return out;
  }

  /* ── общее ── */
  // почему кнопка «Сделать» неактивна ('' — можно)
  function ожидание(card, ctx) {
    const cust = ctx && ctx.cust;
    if (!НАСТРОЙКИ.включено) return 'действия с карточкой клиента выключены';
    if (!статусРазрешён(card)) return 'карточку клиента меняем только в ' + можноГде() + ' (сейчас «' + (card.statusName || '?') + '»)';
    if (!cust) return 'читаю карточку клиента…';
    if (!cust.ok) return String(cust.error || 'карточка клиента не прочиталась');
    return '';
  }
  function ожидаемое(card, cust) {
    const c = (cust && cust.cust) || {};
    return { custSig: c.sig || '', custWas: { line: c.line || '', name: c.name || '', phones: (c.phones || []).length }, statuses: НАСТРОЙКИ.статусы.slice(), statusCode: card.statusCode };
  }
  /* Шаг движка: op 'custAct' (crmcust.js). Всё нужное — в params: бегунок PC для op не 'act' шлёт {dir, id, ...params}.
     expect шага — пусто: бегунок кладёт его в журнал (chrome.storage) как «цель», а в подписи превью — адрес и имя клиента */
  const ШАГ = { addr: 'адрес в карточке клиента', phone_add: 'номер в карточке клиента', name: 'имя в карточке клиента' };
  const шагКарточки = (card, action, params, cust) => ({ op: 'custAct', action, title: ШАГ[action], name: ШАГ[action],
    params: { recipe: action, ...params, expect: ожидаемое(card, cust) }, expect: null });
  function пустойПлан(key, card, title) {
    const crmLines = [];
    return { key, title, steps: [], tg: { kind: null, text: '', reply: null, on: false }, lc: { note: '', name: null }, client: { text: '', on: false }, warnings: [], button: '', crmConfirm: '',
      crmLines, crm: crmLines, invalid: '', already: false, follow: null, card: { dir: card.dir, id: card.id } };
  }

  /* ВЕРНЫЙ АДРЕС: ввод = { addr: {settlement, street, building, office, entrance, floor, intercom, pt?}, сКвартирой?, мастерНаМесте?,
     комментарий? (по умолч. да), вЧат?, время? ('чч:мм' сообщения клиента), addrNote? (адрес не подтверждён картой) } */
  function планАдреса(snap, ввод, ctx) {
    const card = картаИз(snap);
    ввод = нормВвод(ввод); ctx = ctx || {};
    const p = пустойПлан('addr', card, НАСТРОЙКИ.подписи.addr);
    const a = чистыйАдрес(ввод.addr);
    p.invalid = ожидание(card, ctx);
    if (!сДомом(a)) p.invalid = p.invalid || 'нужен адрес с домом (улица или нас. пункт и дом)';
    const d = (ctx.cust && ctx.cust.dry && ctx.cust.dry.addr) || null;
    const c = (ctx.cust && ctx.cust.cust) || {};
    if (!p.invalid && !d) p.invalid = 'читаю карточку клиента…';
    p.invalid = p.invalid || превьюНеТо('addr', ввод, ctx);
    if (!p.invalid && d && d.error) p.invalid = 'адрес не сменить: ' + d.error;
    // квартира городу — только за N мин до визита или когда мастер на адресе (рег:1357)
    const мин = typeof ctx.минутДоВизита === 'number' ? ctx.минутДоВизита : null;
    const квМожно = !!ввод.мастерНаМесте || (мин !== null && мин <= НАСТРОЙКИ.квартираЗаМин);
    const сКв = !!a.office && квМожно && ввод.сКвартирой !== false;
    if (ввод.сКвартирой && !квМожно && a.office) p.warnings.push('квартиру в чат города — только за ' + НАСТРОЙКИ.квартираЗаМин + ' мин до визита или когда мастер на адресе (рег:1357): в чат уйдёт без неё');
    const дом = [a.settlement, a.street, a.building].filter(Boolean).join(', ') + (сКв ? ', кв ' + a.office : '');
    const pt = Array.isArray(ввод.addr && ввод.addr.pt) && ввод.addr.pt.length === 2 && ввод.addr.pt.every((x) => typeof x === 'number' && isFinite(x)) ? ввод.addr.pt : null;
    const текстЧат = Т.адресВЧат(card.id, дом) + (pt ? '\n' + Т.точка(pt) : '');
    const changed = (d && d.changed) || [];
    const кваОбновилась = changed.some((x) => x === 'квартира');
    p.already = !!d && !d.error && !changed.length;
    // в город — другой дом всегда; тот же дом — только если меняется квартира и её уже можно передать
    const вЧатПоУмолч = !!d && (d.house || (кваОбновилась && сКв));
    const tgOn = ввод.вЧат === undefined ? вЧатПоУмолч : !!ввод.вЧат;
    p.tg = { kind: 'city', text: текстЧат, reply: null, on: tgOn && сДомом(a) };
    if (p.already) {
      p.crmLines.push('В карточке клиента уже этот адрес: ' + (d.line || d.was || '—') + ' — CRM не трогаем');
      if (!p.tg.on) p.invalid = p.invalid || 'в карточке клиента уже этот адрес — менять нечего';
    } else if (d && !d.error) {
      p.crmLines.push('Карточка клиента: «' + (d.was || '—') + '» → «' + (d.line || '—') + '»');
      p.crmLines.push('Меняется: ' + changed.join(', ') + (d.house ? ' (другой дом: кв, подъезд, этаж старого дома очищаются, точка на карте — тоже)' : ''));
      const ком = ввод.комментарий !== false ? Т.комментарийАдреса.replace('{время}', ввод.время ? ' ' + чисто(ввод.время).slice(0, 5) : '') : '';
      if (ком) p.crmLines.push('В комментарий заявки: «' + ком.replace('{адрес}', d.line || '') + '»');
      p.steps.push(шагКарточки(card, 'addr', { addr: a, comment: ком }, ctx.cust));
    }
    // предупреждения: территория, общий адрес у других заявок, форма заявки в 2/3, не подтверждённый картой адрес
    const т = территорияАдреса(ctx.terr, card, ctx.cust);
    p.warnings.push(...т.warnings);
    p.follow = т.follow;
    for (const z of (c.otherLive || [])) p.warnings.push('адрес общий для всех заявок клиента: в заявке № ' + z.id + ' («' + z.statusName + '») он тоже сменится');
    if (НАСТРОЙКИ.адресВФормеЗаявки.includes(Number(card.statusCode)) && !p.already) p.warnings.push('в статусе «' + (СТАТУС_ИМЯ[card.statusCode] || '') + '» адрес есть и в форме заявки: если она открыта во вкладке CRM — обновите её (F5) перед «Сохранить», иначе вернётся старый');
    if (ввод.addrNote) p.warnings.push('адрес не подтверждён картой (' + чисто(ввод.addrNote).slice(0, 80) + ') — ' + П.штрафАдреса);
    p.lc = { note: p.already ? '' : 'адрес клиента в CRM: ' + changed.join(', '), name: null };
    p.client = { text: Т.клиентуАдрес([a.settlement, a.street, a.building].filter(Boolean).join(', ') + (a.office ? ', кв ' + a.office : '')), on: false };
    p.button = (p.already ? '' : 'Записать адрес в карточку клиента') + (p.tg.on ? (p.already ? 'Написать в город' : ' и написать в город') : '');
    p.danger = !!(d && d.house);
    if (p.invalid) p.steps = [];
    return p;
  }

  /* ДРУГОЙ НОМЕР: ввод = { phone, replace?: ключ строки (из ctx.cust.cust.phones), title?, звонитьНаНего?, вЧат? } */
  function планТелефона(snap, ввод, ctx) {
    const card = картаИз(snap);
    ввод = ввод || {}; ctx = ctx || {};
    const p = пустойПлан('phone_add', card, НАСТРОЙКИ.подписи.phone_add);
    const d = тел10(ввод.phone);
    p.invalid = ожидание(card, ctx) || (d ? '' : 'номер — 10 цифр (+7 и ещё 10)');
    const dry = (ctx.cust && ctx.cust.dry && ctx.cust.dry.phone) || null;
    const c = (ctx.cust && ctx.cust.cust) || {};
    if (!p.invalid && !dry) p.invalid = 'читаю карточку клиента…';
    p.invalid = p.invalid || превьюНеТо('phone_add', ввод, ctx);
    if (!p.invalid && dry && dry.error) p.invalid = dry.error;
    const замена = ввод.replace ? (c.phones || []).find((x) => x.key === String(ввод.replace)) : null;
    if (ввод.replace && !замена && !p.invalid) p.invalid = 'номера для замены нет в карточке клиента — обновите превью';
    const служебный = ввод.звонитьНаНего ? Т.служебныйНомер : '';
    p.already = !!dry && !!dry.already;
    if (p.already && !служебный) p.invalid = p.invalid || (dry.note || 'этот номер уже есть в карточке клиента');
    if (d) {
      p.crmLines.push(p.already ? 'В карточке клиента номер ' + видНомера(d) + ' уже есть — CRM не трогаем'
        : замена ? 'Карточка клиента: номер ' + замена.masked + ' → ' + видНомера(d) : 'Карточка клиента: добавить номер ' + видНомера(d) + (ввод.title ? ' («' + чисто(ввод.title).slice(0, 30) + '»)' : ''));
      const прочие = (c.phones || []).filter((x) => !замена || x.key !== замена.key).length;
      if (!p.already && прочие) p.crmLines.push('Остальные номера (' + прочие + ') не трогаем');
    }
    if (служебный) p.crmLines.push('В служебный заявки: «' + служебный + '»');
    if (замена && замена.main) p.warnings.push('это первый (основной) номер клиента — по нему ищут его заявки; заменяйте, только если он неверный');
    if (!p.already) p.warnings.push(П.штрафНомера);
    p.steps = p.invalid ? [] : [шагКарточки(card, 'phone_add', { phone: d, replace: замена ? замена.key : '', title: чисто(ввод.title).slice(0, 30), service: служебный }, ctx.cust)];
    // сам номер в чат города не пишем: только в разрешённых случаях «Стыка» (рег:865–883) — город видит его в CRM
    p.tg = { kind: 'city', text: Т.номерВЧат(card.id), reply: null, on: !!ввод.вЧат };
    p.lc = { note: p.already ? '' : 'номер клиента в CRM: ' + (замена ? 'заменён на ' : 'добавлен ') + маска(d), name: null };
    p.client = { text: Т.клиентуНомер, on: false };
    p.button = p.already ? 'Дописать в служебный' : (замена ? 'Заменить номер в карточке клиента' : 'Добавить номер в карточку клиента');
    p.danger = !!(замена && замена.main);
    return p;
  }

  /* ИМЯ КЛИЕНТА: ввод = { name, preset?: 'police', оставитьНомера? (по умолч. да), tgText? (полиция: номер звонившего) }.
     № заявок, которые уже стоят в имени в CRM, не теряем (если оператор не снял галочку) */
  function новоеИмя(card, ввод, текущее) {
    if (ввод.preset === 'police') return Т.полиция(card.id);
    let n = чисто(ввод.name).slice(0, 100);
    if (n && ввод.оставитьНомера !== false) {
      const номера = (String(текущее || '').match(/(?<!\d)\d{6,8}(?!\d)/g) || []).filter((x) => !n.includes(x));
      if (номера.length) n = (n + ' ' + номера.join(' ')).slice(0, 100);
    }
    return n;
  }
  function планИмени(snap, ввод, ctx) {
    const card = картаИз(snap);
    ввод = ввод || {}; ctx = ctx || {};
    const p = пустойПлан('name', card, НАСТРОЙКИ.подписи.name);
    const c = (ctx.cust && ctx.cust.cust) || {};
    const n = новоеИмя(card, ввод, c.name);
    p.invalid = ожидание(card, ctx) || (n ? '' : 'имя пустое — ' + П.безИмени);
    p.already = !p.invalid && n === чисто(c.name);
    if (p.already) p.invalid = 'в карточке клиента уже это имя';
    if (n) p.crmLines.push('Имя в карточке клиента: «' + (c.name || '—') + '» → «' + n + '»');
    if (ввод.preset === 'police') p.warnings.push(П.полиция.replace('<ID>', card.id));
    if (!n) p.warnings.push(П.безИмени);
    p.steps = p.invalid ? [] : [шагКарточки(card, 'name', { name: n }, ctx.cust)];
    // полиция: номер звонившего — ответом на «Новая претензия» (вписывает оператор, поле пустое)
    if (ввод.preset === 'police') p.tg = { kind: 'claims', text: чисто(ввод.tgText), reply: 'claimMsg', on: !!чисто(ввод.tgText), нужно: 'номер звонившего (впишите сами)' };
    p.lc = { note: p.already ? '' : 'имя клиента в CRM изменено', name: null };
    p.button = 'Записать имя в карточку клиента' + (p.tg.on ? ' и ответить в претензии' : '');
    return p;
  }

  /* Поля карточки действия — в словаре экрана (actions-ui.js, PC): имена плоские (адрес — street/building/…, план сводит в addr),
     галочка — 'check', по умолчанию — value, when(ввод) — функция, варианты select — [значение, текст]
     (пустой вариант экран добавляет сам — его подпись в «пусто»: у «Какой номер заменить» он значит «добавить новым»).
     2.1: подпись — коротко, пояснение — в hint (строка под полем), номер регламента — не в подписи */
  function поляАдреса() {
    return [{ name: 'settlement', label: 'Нас. пункт', type: 'text' }, { name: 'street', label: 'Улица', type: 'text' },
      { name: 'building', label: 'Дом', type: 'text', required: true }, { name: 'office', label: 'Кв', type: 'text' },
      { name: 'entrance', label: 'Подъезд', type: 'text' }, { name: 'floor', label: 'Этаж', type: 'text' },
      { name: 'intercom', label: 'Домофон есть', type: 'check' },
      { name: 'мастерНаМесте', label: 'Мастер уже на адресе', hint: 'тогда квартиру можно передать в чат города', type: 'check' },
      { name: 'сКвартирой', label: 'Квартиру — в чат города', hint: 'только за ' + НАСТРОЙКИ.квартираЗаМин + ' мин до визита или когда мастер на адресе', type: 'check', value: true },
      { name: 'комментарий', label: 'Строка в комментарий заявки', hint: '«' + Т.комментарийАдреса.replace('{время}', '').replace('{адрес}', '…') + '»', type: 'check', value: true }];
  }
  function поляТелефона(snap, ctx) {
    const c = (ctx && ctx.cust && ctx.cust.cust) || {};
    return [{ name: 'phone', label: 'Номер', type: 'tel', required: true, placeholder: '+7 900 000-00-00' },
      { name: 'replace', label: 'Какой номер заменить', type: 'select', пусто: 'не заменять — добавить новым', options: (c.phones || []).map((x) => [x.key, 'вместо ' + x.masked + (x.main ? ' (основной)' : '')]) },
      { name: 'title', label: 'Подпись номера', type: 'text', placeholder: 'жена, рабочий' },
      { name: 'звонитьНаНего', label: 'В служебный: «' + Т.служебныйНомер + '»', type: 'check' },
      { name: 'вЧат', label: 'Написать в город', hint: 'сам номер в чат не уходит — город видит его в CRM', type: 'check' }];
  }
  function поляИмени(snap) {
    const card = картаИз(snap);
    const полиция = (в) => !!в && в.preset === 'police';
    return [{ name: 'name', label: 'Имя', type: 'text', required: true, when: (в) => !полиция(в) },
      { name: 'preset', label: 'Шаблон имени', type: 'select', пусто: 'нет — имя выше', options: [['police', 'Полиция: «' + Т.полиция(card.id || '<ID>') + '»']] },
      { name: 'оставитьНомера', label: 'Оставить № заявок, которые уже в имени', type: 'check', value: true, when: (в) => !полиция(в) },
      { name: 'tgText', label: 'Номер звонившего — ответом на «Новая претензия»', type: 'text', when: полиция }];
  }

  /* ЧТЕНИЕ ДЛЯ ПРЕВЬЮ (без записи): карточка клиента в CRM + территория нового адреса + минуты до визита.
     Результат экран кладёт в ctx (ctx.cust, ctx.terr, ctx.минутДоВизита) и передаёт в план */
  async function подготовить(key, snap, ввод, хост) {
    const card = картаИз(snap);
    ввод = нормВвод(ввод);
    const out = { cust: null, terr: null, минутДоВизита: null, для: ключВвода(key, ввод) };
    if (!хост || typeof хост.send !== 'function') { out.cust = { ok: false, error: 'нет связи с расширением' }; return out; }
    const send = (m) => хост.send(m);
    const в = {};
    const a = чистыйАдрес(ввод.addr);
    if (key === 'addr' && сДомом(a)) в.addr = a;
    if (key === 'phone_add' && тел10(ввод.phone)) { в.phone = тел10(ввод.phone); if (ввод.replace) в.replace = String(ввод.replace); }
    const custP = Promise.resolve().then(() => send({ kind: 'lcz-crm', op: 'custSnap', args: { dir: card.dir, id: card.id, ввод: в } }))
      .catch((e) => ({ ok: false, error: String((e && e.message) || e).slice(0, 100) }));
    const terrP = key === 'addr' && в.addr ? custP.then((c) => {
      const city = card.cityName || (c && c.card && c.card.cityName) || '';
      const args = { dir: card.dir, city, settlement: a.settlement, street: a.street, building: a.building };
      const pt = ввод.addr && ввод.addr.pt;
      if (Array.isArray(pt) && pt.length === 2 && ввод.addr.ptLocality) Object.assign(args, { pt, ptLocality: ввод.addr.ptLocality });
      return Promise.race([Promise.resolve(send({ kind: 'lcz-territory', args })),
        new Promise((res) => setTimeout(() => res({ ok: false, timeout: true, error: 'карта не ответила за ' + НАСТРОЙКИ.территорияЖдёмМс / 1000 + ' с' }), НАСТРОЙКИ.территорияЖдёмМс))]);
    }).catch((e) => ({ ok: false, error: String((e && e.message) || e).slice(0, 80) })) : null;
    out.cust = (await custP) || { ok: false, error: 'нет ответа' };
    if (out.cust && typeof out.cust === 'object') out.cust = { ...out.cust, для: out.для };
    if (terrP) out.terr = await terrP;
    try {
      if (хост && typeof хост.визитСейчас === 'function') {
        const x = хост.визитСейчас({ city: card.cityName || '', visit: card.visitDate || '', visitTime: card.visitTime || '' }, '');
        if (x && typeof x.late === 'number') out.минутДоВизита = -x.late;
      }
    } catch (_e) { /* без минут — квартиру в чат не предлагаем */ }
    return out;
  }

  /* ПОДСКАЗКА: ИИ по переписке (намерение «адрес», PB) или новый адрес, распознанный LeadChat → карточка нужного действия */
  function подсказка(источник, snap, данные) {
    const card = картаИз(snap);
    данные = данные || {};
    if (!НАСТРОЙКИ.включено || !статусРазрешён(card) || card.customerId === '' || card.customerId === null) return null;
    if (!(данные.intent === 'адрес' || источник === 'leadchat-addr')) return null;
    const опора = данные.опора ? ': «' + чисто(данные.опора).slice(0, 60) + '»' : '';
    const a = чистыйАдрес(данные.addr);
    if (сДомом(a)) return { key: 'addr', ввод: { addr: { ...a, ...(данные.addr && данные.addr.pt ? { pt: данные.addr.pt, ptLocality: данные.addr.ptLocality || '' } : {}) } }, почему: 'клиент назвал другой адрес' + опора };
    if (тел10(данные.phone)) return { key: 'phone_add', ввод: { phone: тел10(данные.phone) }, почему: 'клиент дал другой номер' + опора };
    if (чисто(данные.name)) return { key: 'name', ввод: { name: чисто(данные.name) }, почему: 'клиент назвал имя' + опора };
    return null;
  }

  // доступность сверх статуса: клиент у заявки должен быть (снимок PA: customerId)
  const доступно = (snap) => {
    const card = картаИз(snap);
    if (!НАСТРОЙКИ.включено) return 'выключено';
    if (!статусРазрешён(card)) return 'карточку клиента меняем только в ' + можноГде();
    if (card.customerId === '' || card.customerId === null) return 'в карточке заявки нет клиента';
    return '';
  };

  /* план в двух видах вызова: по контракту 2.1 — план(snap, ввод, ctx) → план; из LC_ACT.план (PB) — план(p, s, v, c, помощники):
     p там уже собран (missing, ok, tg-объект) и дополняется на месте */
  function двуликий(свой) {
    return function (...a) {
      const p = a[0];
      if (typeof p === 'string') return свой(a[1], a[2], a[3]);               // как LC_ACT.план(key, snap, ввод, ctx)
      if (!(a.length >= 4 && p && Array.isArray(p.steps) && Array.isArray(p.missing))) return свой(a[0], a[1], a[2]);
      const r = свой(a[1], a[2], a[3]);
      Object.assign(p, { steps: r.steps, tg: r.tg, lc: r.lc, client: r.client, button: r.button, crm: r.crmLines, crmLines: r.crmLines,
        already: r.already, follow: r.follow, danger: !!r.danger, invalid: r.invalid });
      p.warnings.push(...r.warnings);
      if (r.invalid) { p.missing.push(r.invalid); p.ok = false; }
      return p;
    };
  }
  function описание(key, план, поля) {
    return { key, label: НАСТРОЙКИ.подписи[key], icon: НАСТРОЙКИ.иконки[key], group: НАСТРОЙКИ.группа, get statuses() { return НАСТРОЙКИ.статусы.slice(); },
      // tg — куда по умолчанию: адрес — в город; номер — в город только по галочке; имя — никуда (полиция — ответ в претензиях)
      needButton: null, crm: 'customer', tg: key === 'name' ? null : 'city', danger: key === 'addr', primary: false,
      off: !НАСТРОЙКИ.включено,                                         // в каталоге PB ключи PE скрыты (off), пока их не добавили
      доступно, правило: (snap) => доступно(snap), поля, план: двуликий(план),
      подсказка: (источник, snap, данные) => { const s = подсказка(источник, snap, данные); return s && s.key === key ? s : null; },
      подготовить: (snap, ввод, хост) => подготовить(key, snap, ввод, хост) };
  }
  const ДЕЙСТВИЯ = { addr: описание('addr', планАдреса, поляАдреса), phone_add: описание('phone_add', планТелефона, поляТелефона), name: описание('name', планИмени, поляИмени) };

  /* РЕГИСТРАЦИЯ в каталоге LC_ACT (actions.js): LC_ACT.добавить(key, описание). Таблица PE — LC_ACT.настройкиКлиента */
  function зарегистрировать(L) {
    if (!L || typeof L.добавить !== 'function' || !НАСТРОЙКИ.включено) return false;
    for (const [key, def] of Object.entries(ДЕЙСТВИЯ)) L.добавить(key, def);
    if (!L.настройкиКлиента) L.настройкиКлиента = НАСТРОЙКИ;
    return true;
  }
  if (typeof LC_ACT !== 'undefined') зарегистрировать(LC_ACT);

  return { НАСТРОЙКИ, ДЕЙСТВИЯ, зарегистрировать, подготовить, подсказка, территорияАдреса, планАдреса, планТелефона, планИмени, новоеИмя, тел10, маска };
})();
if (typeof module !== 'undefined' && module.exports) module.exports = LC_ACT_CUST;
