/* ОПЕРАЦИИ МОЗГА — перенос серверной части фона расширения 1.19 (ext/background.js) один к одному:
   разбор переписки, адрес (ИИ + правила + карты/ФИАС/OSM), территория (карта направления + Геокодер), регламент,
   «что дописал клиент», выбор вида работ, местные названия, прокси к серверу команды (Telegram, общая память).
   Формат аргументов и ответа — как у функций фона: расширение-оболочка подменяет сообщение фона запросом к мозгу.
   Отличия от 1.19 (по проекту 2.0): ИИ — по цепочкам (ai.js), один голос ИИ в адресе вместо двух,
   в разборе — последние 40 строк переписки, режим rules — ответы правилами (rules.js). */
'use strict';
const { создатьПравила } = require('./rules');
const { создатьПравило } = require('./advertiser');

const НП_ОБНОВЛЯТЬ = 30 * 60e3;
const СТРОК = { normal: 40, economy: 25 };              // переписка для ИИ: экономия входа (было 80)

function создатьОперации(deps) {
  const { M, ai, team, запрос, store, log } = deps;
  const E = deps.env || {};
  const { LC_EXTRACT, LC_ADDRESS, LC_ADDR_RULES, LC_CHECK, LC_TG, LC_TERRITORY, LC_PICK } = M;
  const правила = deps.правила || создатьПравила(M);
  const сейчас = deps.now || (() => Date.now());
  const advertiser = создатьПравило({ M, запрос, store, now: сейчас });
  const пауза = deps.sleep || ((ms) => new Promise((r) => setTimeout(r, ms)));
  const журнал = log || (() => {});
  // без ответа не ждём: геокодер — 8 с на запрос; карта грузится не дольше 15 с, а ждём её не дольше 5 с (панель ждёт
  // всю территорию 9 с — карта не должна съедать это время); срок — на весь ответ, с телом
  const ТАЙМАУТЫ = { map: 15000, mapЖдём: 5000, mapПауза: 5 * 60e3, geo: 8000, check: 10000, osm: 8000, ...(deps.таймауты || {}) };

  async function запросСрок(url, init, ms, как) {
    const r = await запрос(url, { ...(init || {}), timeout: ms });
    return как === 'json' ? r.json() : r.text();
  }
  const рядСтрок = (режим) => СТРОК[режим] || СТРОК.normal;
  /* хвост переписки, дающий не больше n строк для ИИ (служебные сообщения строк не дают — их не считаем) */
  function хвост(messages, n, tz) {
    const list = messages || [];
    let k = list.length, строк = 0;
    while (k > 0 && строк < n) { k--; строк += LC_EXTRACT.dialogLines([list[k]], tz).length; }
    return list.slice(k);
  }

  /* ---------- Геокодер ---------- */
  async function геокодМного(text, n) {
    if (!E.YANDEX_GEOCODER_KEY || !text) return [];
    const u = 'https://geocode-maps.yandex.ru/1.x/?apikey=' + encodeURIComponent(E.YANDEX_GEOCODER_KEY) + '&format=json&results=' + (n || 1) + '&lang=ru_RU&geocode=' + encodeURIComponent(text);
    let d;
    try { d = await запросСрок(u, null, ТАЙМАУТЫ.geo, 'json'); }
    catch (e) { throw new Error(e && e.name === 'AbortError' ? 'Яндекс Геокодер не ответил за ' + ТАЙМАУТЫ.geo / 1000 + ' с' : String((e && e.message) || e)); }
    return ((((d.response || {}).GeoObjectCollection || {}).featureMember) || []).map((g) => {
      const o = g.GeoObject, md = (o.metaDataProperty || {}).GeocoderMetaData || {};
      const comps = ((md.Address || {}).Components) || [];
      const pos = String((o.Point || {}).pos || '').split(' ').map(Number);
      return { pt: pos.length === 2 ? pos : null, precision: md.precision || '', kind: md.kind || '',
        locality: (comps.filter((c) => c.kind === 'locality').pop() || {}).name || '', text: md.text || '',
        localities: comps.filter((c) => c.kind === 'locality').map((c) => c.name),           // «Иркутск» → «СНТ Желдорфармация»: СНТ внутри города
        districts: comps.filter((c) => c.kind === 'district').map((c) => c.name),
        // микрорайон без улиц («мкр 140Б, 1») у Яндекса — район (district): им и сравниваем вместо улицы
        мкр: (comps.find((c) => c.kind === 'district' && /микрорайон|мкр|квартал/i.test(c.name || '')) || {}).name || '',
        street: (comps.find((c) => c.kind === 'street') || {}).name || '', house: (comps.find((c) => c.kind === 'house') || {}).name || '' };
    }).filter((x) => x.pt);
  }
  async function геокод(text) { return (await геокодМного(text, 1))[0] || null; }

  /* Город объявления латиницей («protvino»): города CRM → справочник слагов Авито → Яндекс.Карты («Протвино») → транслит.
     Справочник знает город — карта не нужна. Карта — не дольше 5 с: не ответила — транслит. */
  async function городОбъявления(ctx) {
    const raw = ctx.cityRaw || ctx.city;
    if (!LC_EXTRACT.латиницейГород(raw)) return;
    ctx.cityRaw = raw;
    const r = LC_EXTRACT.городПоРусски(raw, ctx.knownCities);
    ctx.city = r.city;
    if (!ctx.tz && r.tz) ctx.tz = r.tz;
    if (r.how === 'crm' || r.how === 'slug' || r.how === 'region') return;
    let timer = 0;
    try {
      const q = /_/.test(raw) ? r.city : raw, к = [LC_EXTRACT.скелетГорода(raw), LC_EXTRACT.скелетГорода(r.city)];
      const list = await Promise.race([геокодМного(q, 5), new Promise((res) => { timer = setTimeout(() => res([]), 5000); })]);
      const g = list.find((x) => x.kind === 'locality' && x.locality && к.includes(LC_EXTRACT.скелетГорода(x.locality)));
      if (g) ctx.city = g.locality;
    } catch (_e) { /* без карты — транслит */ } finally { clearTimeout(timer); }
  }

  /* ---------- разбор переписки ---------- */
  // ключ кэша — состояние диалога (сообщения и карточка), без времени запроса: повторная проверка того же — 0 ₽
  const ключРазбора = (ctx) => ({
    m: (ctx.messages || []).map((m) => [m.id || '', m.direction || '', m.sender_type || '', m.body || '', m.voice_transcript || '', m.id ? '' : (m.created_at || '')]),
    c: [ctx.city || '', ctx.cityRaw || '', ctx.tz || '', ctx.itemTitle || '', ctx.clientName || ''],
    v: M.версияРазбора || '',
  });
  async function extract(ctx, режим, o) {
    ctx = await advertiser.prepare(ctx || {}, !(ctx && ctx.purpose === 'inbox'));
    const finish = (r) => ({ ...r, lead: advertiser.decorate(r.lead, ctx) });
    ctx.now = new Date(сейчас());
    await городОбъявления(ctx);
    if (режим === 'rules') return finish(правила.extract(ctx, o && o.почему));
    const tz = LC_EXTRACT.clientTz(ctx.tz, ctx.city).tz;
    const p = LC_EXTRACT.buildPrompt({ ...ctx, messages: хвост(ctx.messages, рядСтрок(режим), tz) });
    let r;
    try { r = await ai.спросить('extract', p.sys, p.task, { режим, ключКэша: ключРазбора(ctx), годен: (t) => !!LC_EXTRACT.parseJson(t) }); }
    catch (e) {
      if (e.rules) return finish(правила.extract(ctx));
      // 2.0.9: ИИ ответил пусто / не по форме (журнал 10.10: GigaChat на ~3 % переписок отдаёт пустой ответ — фильтр) — не ошибка
      // «заполните вручную», а разбор правилами: телефон, адрес, время, озвучки правила находят сами; оператор видит пометку
      if (e.неПоФорме || /не по форме/.test(e.message)) return finish(правила.extract(ctx, 'ИИ не разобрал эту переписку (пустой ответ) — разобрано правилами, проверьте поля; ИИ попробует снова после нового сообщения клиента или через 30 мин'));
      // 2.2.0: ИИ недоступен (ни одна модель не ответила, ключей нет — свой сервер до переноса настроек) — не ошибка «форма не открылась»,
      // а разбор правилами с пометкой: телефон, адрес, время, озвучки правила находят сами
      if (e instanceof Error && /ИИ не ответил/.test(e.message)) return finish(правила.extract(ctx, 'ИИ сейчас недоступен — разобрано правилами, проверьте поля (' + String(e.message).replace(/^ИИ не ответил\s*/, '').slice(0, 120) + ')'));
      throw e;
    }
    const v = LC_EXTRACT.validate(LC_EXTRACT.parseJson(r.text), ctx);
    return finish({ ok: true, lead: v.lead, checks: v.checks });
  }

  /* ---------- адрес ---------- */
  /* ПРОВЕРКА АДРЕСА: Яндекс.Карты → ФИАС (DaData) → опечатка в улице (Геосаджест) → OpenStreetMap.
     Подтвердил хоть один источник дом — адрес подтверждён. Ничего не записывает. */
  async function verifyAddress(a, city) {
    const res = { status: 'not_found', confirmed: [], checks: [], map: '', fixedStreet: '' };
    const add = (j) => { res.checks.push(j); if (j.status === 'exact') { res.confirmed.push(j.by); res.status = 'exact'; res.map = res.map || j.map; } };
    const jget = async (url, init) => { const r = await запрос(url, { ...(init || {}), timeout: ТАЙМАУТЫ.check }); if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); };
    const яндекс = async (x) => { try { return LC_ADDRESS.ygeoJudge(await jget(LC_ADDRESS.ygeoUrl(x, city, E.YANDEX_GEOCODER_KEY)), x, city); } catch (e) { return { status: 'error', by: 'Яндекс.Карты', text: 'Яндекс.Карты не ответили (' + e.message + ')' }; } };
    const фиас = async (x) => { try { return LC_ADDRESS.dadataJudge(await jget('https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/address', {
      method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json', Authorization: 'Token ' + E.DADATA_KEY }, body: LC_ADDRESS.dadataBody(x, city) }), x, city); }
      catch (e) { return { status: 'error', by: 'ФИАС (DaData)', text: 'DaData не ответила (' + e.message + ')' }; } };
    const run = async (x) => {
      const [y, d] = await Promise.all([E.YANDEX_GEOCODER_KEY ? яндекс(x) : null, E.DADATA_KEY ? фиас(x) : null]);
      return [y, d].filter(Boolean);
    };
    const checks = await run(a);
    checks.forEach(add);
    // улица не найдена ни там, ни там — возможно, опечатка: спрашиваем Геосаджест и проверяем ещё раз
    if (res.status !== 'exact' && E.YANDEX_SUGGEST_KEY && a.street && checks.every((c) => c.status !== 'house_missing')) {
      try {
        const fixed = LC_ADDRESS.ysugFix(await jget(LC_ADDRESS.ysugUrl(a, city, E.YANDEX_SUGGEST_KEY)), a, city);
        if (fixed && LC_ADDRESS.полнаяУлица(fixed).toLowerCase() !== LC_ADDRESS.полнаяУлица(a.street).toLowerCase()) {
          const b = { ...a, street: fixed };
          const again = await run(b);
          if (again.some((c) => c.status === 'exact')) { res.checks = []; res.fixedStreet = fixed; again.forEach(add); }
        }
      } catch (_e) { /* без исправления */ }
    }
    if (res.status !== 'exact') {
      try {
        for (const free of [false, true]) {
          if (free) await пауза(1100);                                   // OpenStreetMap: не чаще 1 запроса в секунду
          // OSM требует понятного User-Agent от сервера (браузер слал свой сам)
          const r = await запрос(LC_ADDRESS.osmUrl(a, city, free), { headers: { Accept: 'application/json', 'User-Agent': 'lead-centre-brain/2.0 (address check)' }, timeout: ТАЙМАУТЫ.osm });
          if (!r.ok) break;
          const j = { ...LC_ADDRESS.osmJudge(await r.json(), a, city), by: 'OpenStreetMap' };
          if (j.status === 'exact' || free) { add(j); break; }
        }
      } catch (_e) { /* OSM недоступен */ }
      if (res.status !== 'exact' && res.checks.some((c) => c.status === 'house_missing')) res.status = 'house_missing';
    }
    const ок = res.checks.find((c) => c.status === 'exact');
    res.text = ок ? 'дом найден: ' + res.confirmed.join(', ') : (res.checks.map((c) => c.text).join('; ') || 'проверить негде');
    res.street = (res.checks.find((c) => c.status === 'exact' && c.street) || {}).street || '';
    return res;
  }

  /* АДРЕС ГОЛОСАМИ: ИИ (GigaChat, запасной — YandexGPT Lite) и правила без ИИ. Согласны — адрес принят.
     Потом проверка по картам и реестру */
  async function address(ctx, режим) {
    ctx = ctx || {};
    const tz = LC_EXTRACT.clientTz(ctx.tz, ctx.city).tz;
    // служебные строки (подсказка бота, «[Системное сообщение]», вопрос LeadChat) — не переписка: адрес из них не берём
    const msgs = (ctx.messages || []).filter(LC_EXTRACT.речь);
    const lines = LC_EXTRACT.dialogLines(msgs, tz);
    const text = msgs.map((m) => (m.body || '') + ' ' + (m.voice_transcript || '')).join('\n');
    const notes = [];
    let gi = null, голос = 'GigaChat';
    if (режим === 'rules') notes.push('ИИ выключен до 1-го числа (лимит) — адрес по правилам');
    else {
      const p = LC_ADDRESS.prompt(lines.slice(-рядСтрок(режим)), ctx);
      try {
        const r = await ai.спросить('address', p.sys, p.task, { режим });
        голос = /^GigaChat/i.test(r.model) ? 'GigaChat' : 'YandexGPT';
        gi = LC_ADDRESS.ground(LC_ADDRESS.parse(r.text), text);
      } catch (e) { notes.push(e.rules ? 'ИИ выключен до 1-го числа (лимит) — адрес по правилам' : 'ИИ: ' + String(e.message || e).slice(0, 70)); }
    }
    const rr = LC_ADDR_RULES.parse(msgs, ctx.city);
    const ru = rr ? { ...rr, ok: !!((rr.street || rr.settlement) && rr.house) } : null;
    // адрес, который первым написал оператор (мастерская, пункт приёма), а клиент повторил, — не адрес клиента
    let echo = null;
    const безЭха = (a, by) => {
      const e = a && a.ok ? LC_EXTRACT.эхоОператора(a, msgs) : '';
      if (!e) return a;
      if (!echo) { echo = { ...a, by, quote: e, line: LC_ADDRESS.toLine(a, ctx.city) }; notes.push('адрес «' + [a.street, a.house].join(', ') + '» первым написал оператор — это не адрес клиента'); }
      return null;
    };
    const c = LC_ADDRESS.combineMany([[безЭха(gi, голос), голос], [безЭха(ru, 'правила'), 'правила']]);
    const out = { ok: true, ...c, notes, osm: null, altOsm: null, echo };
    if (!c.best) return out;
    // имя человека («Татьяна» отдельным сообщением) — не нас. пункт
    for (const k of ['best', 'alt']) if (c[k] && c[k].settlement && LC_EXTRACT.этоИмя(c[k].settlement, [ctx.clientName])) c[k] = { ...c[k], settlement: '' };
    // местное название вместо официального («рудник» в Ачинске → посёлок Мазульский)
    for (const k of ['best', 'alt']) {
      const x = c[k], p2 = x && x.settlement && await местноеНазвание(ctx.city, x.settlement).catch(() => '');
      if (p2) { c[k] = { ...x, settlement: p2 }; if (k === 'best') notes.push('«' + x.settlement + '» — это ' + p2); }
    }
    if (c.best !== out.best) out.best = c.best;
    if (c.alt !== out.alt) out.alt = c.alt;
    const v = await verifyAddress(c.best, ctx.city);
    out.osm = v;
    if (v.status !== 'exact' && c.alt) {
      const v2 = await verifyAddress(c.alt, ctx.city);
      out.altOsm = v2;
      if (v2.status === 'exact') {                                       // карта подтвердила второй вариант — он главный
        [out.best, out.alt, out.osm, out.altOsm, out.by, out.altBy] = [c.alt, c.best, v2, v, [c.altBy], c.by.join(', ')];
      }
    }
    if (out.osm.fixedStreet) out.best = { ...out.best, street: out.osm.fixedStreet };
    else if (out.osm.street && out.osm.status === 'exact') out.best = { ...out.best, street: out.osm.street };
    out.best = { ...out.best, street: LC_ADDR_RULES.normStreet(out.best.street) };    // «Профсоюзная улица» → «ул Профсоюзная»
    out.line = LC_ADDRESS.toLine(out.best, ctx.city);
    return out;
  }

  /* ---------- регламент ---------- */
  async function checklist(a, режим) {
    a = a || {};
    const ctx = a.ctx || {};
    // только переписка: «Подсказка бота: …» и «[Системное сообщение]» клиент не видел — цены и «фреон» из них не в счёт
    const речь = (ctx.messages || []).filter(LC_EXTRACT.речь);
    const text = речь.map((m) => (m.body || '') + ' ' + (m.voice_transcript || '')).join('\n');
    const клиент = (речь.filter((m) => m.direction === 'in').map((m) => m.body || '').join('\n')) + '\n' + (a.problem || '');
    const c = LC_CHECK.items(a.dir, a.applText || '', a.subText || '', undefined, { text: text + '\n' + (a.problem || ''), client: клиент });
    if (!c.items.length && !c.rules.length && !c.refuse.length) return { ok: true, section: c.section, results: [], approval: '' };
    if (режим === 'rules') return правила.checklist(c, клиент);
    const tz = LC_EXTRACT.clientTz(ctx.tz, ctx.city).tz;
    const lines = LC_EXTRACT.dialogLines(ctx.messages, tz);
    const p = LC_CHECK.prompt(c.items, lines.slice(-рядСтрок(режим)), c.rules, c.free, c.refuse);
    try {
      const raw = (await ai.спросить('checklist', p.sys, p.task, { режим })).text;
      const итог = LC_CHECK.итогСогласования(LC_CHECK.approval(raw, c.rules), c.rules, c.free, клиент);
      return { ok: true, section: c.section, results: LC_CHECK.parse(raw, c.items, text), approval: итог.approval, maybe: итог.maybe, maybeWhy: итог.why, rules: c.rules,
        refuse: LC_CHECK.refuse(raw, c.refuse) };
    } catch (e) {
      if (e.rules) return правила.checklist(c, клиент);
      return { ok: false, section: c.section, error: 'ИИ не ответил: ' + (e.message || e), results: c.items.map((item) => ({ item, done: false, answer: '' })), approval: '' };
    }
  }

  /* ---------- клиент дописал после создания заявки ---------- */
  async function addition(a, режим) {
    a = a || {};
    const ctx = a.ctx || {};
    const tz = LC_EXTRACT.clientTz(ctx.tz, ctx.city).tz;
    const before = LC_EXTRACT.dialogLines(ctx.before || [], tz);
    const neu = LC_EXTRACT.dialogLines(ctx.fresh || [], tz);
    if (!neu.length) return { ok: true, important: false };
    const d = new Date(сейчас());
    const today = new Intl.DateTimeFormat('sv-SE', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);
    const wd = new Intl.DateTimeFormat('ru-RU', { timeZone: tz, weekday: 'long' }).format(d);
    if (режим === 'rules') return { ok: true, today, ...правила.addition(ctx.fresh) };
    const p = LC_TG.additionPrompt(neu, before.slice(-рядСтрок(режим)), today + ' (' + wd + ')');
    let raw;
    try { raw = (await ai.спросить('addition', p.sys, p.task, { режим })).text; }
    catch (e) { if (e.rules) return { ok: true, today, ...правила.addition(ctx.fresh) }; throw e; }
    const r = LC_TG.additionParse(raw, (ctx.fresh || []).map((m) => (m.body || '') + ' ' + (m.voice_transcript || '')).join('\n'));
    return { ok: true, today, ...r };
  }

  /* ---------- вид работ / вид услуг по регламенту (CRM-список готовит расширение) ---------- */
  async function pick(a, режим) {
    a = a || {};
    const level = a.kind || a.level || 'appl', x = a.a || {};
    const list = Array.isArray(a.list) ? a.list : [];
    if (режим === 'rules') return { ok: true, id: '', why: '', rules: true };
    const p = LC_PICK.prompt({ level, dir: a.dir, list, hints: a.hints, problem: x.problem, topics: x.topics, client: x.client, applText: a.applText });
    let raw;
    try { raw = (await ai.спросить('pick', p.sys, p.task, { режим })).text; }
    catch (e) { if (e.rules) return { ok: true, id: '', why: '', rules: true }; throw e; }
    return { ok: true, ...LC_PICK.parse(raw, list) };
  }

  /* ---------- территория ---------- */
  /* Загрузка карты — одна на направление. Не загрузилась — виджет не дёргаем ТАЙМАУТЫ.mapПауза */
  const картаИдёт = {}, картаСбой = {}, картаПамять = {};
  const ключКарты = (dir) => 'brain/maps/' + String(dir).replace(/[^a-z0-9_-]/gi, '_') + '.json';
  async function картаСохранённая(dir) {
    if (картаПамять[dir]) return картаПамять[dir];
    try { const c = await store.get(ключКарты(dir), null); if (c && c.map) картаПамять[dir] = c; return c; } catch (_e) { return null; }
  }
  function загрузитьКарту(dir) {
    if (!картаИдёт[dir]) {
      картаИдёт[dir] = (async () => {
        try {
          const html = await запросСрок(LC_TERRITORY.widgetUrl(LC_TERRITORY.MAPS[dir]), null, ТАЙМАУТЫ.map, 'text');
          const um = LC_TERRITORY.userMapFromHtml(html);
          if (um && um.features && um.features.length) {
            const map = LC_TERRITORY.parseMap(um);
            const rec = { at: сейчас(), map };
            картаПамять[dir] = rec;
            await store.put(ключКарты(dir), rec).catch(() => {});        // не сохранилась — работаем по загруженной
            return map;
          }
        } catch (_e) { /* нет сети — берём, что было */ }
        картаСбой[dir] = сейчас();
        return null;
      })().finally(() => { delete картаИдёт[dir]; });
    }
    return картаИдёт[dir];
  }
  /* Карта направления: свежая (12 ч) — из памяти; устарела — отвечаем по сохранённой сразу, новую грузим в фоне;
     сохранённой нет — ждём загрузку не дольше ТАЙМАУТЫ.mapЖдём */
  async function картаНаправления(dir, fresh) {
    const id = LC_TERRITORY.MAPS[dir];
    if (!id) return null;
    const cached = await картаСохранённая(dir);
    if (!fresh && cached && сейчас() - cached.at < 12 * 3600e3) return cached.map;
    if (!fresh && сейчас() - (картаСбой[dir] || 0) < ТАЙМАУТЫ.mapПауза) return cached ? cached.map : null;
    const идёт = загрузитьКарту(dir);
    if (cached && !fresh) return cached.map;
    let timer = null;
    const map = await Promise.race([идёт, new Promise((res) => { timer = setTimeout(() => res(null), ТАЙМАУТЫ.mapЖдём); })]);
    clearTimeout(timer);
    return map || (cached ? cached.map : null);
  }

  /* ВЫУЧЕННЫЕ МЕСТНЫЕ НАЗВАНИЯ нас. пунктов: оператор однажды выбрал «рудник» → «посёлок Мазульский».
     Свои — в хранилище мозга (brain/names_own.json), общие для команды — на сервере команды (обновляем раз в 30 минут) */
  let свои = null, своиПри = 0, команды = null, командыПри = 0;
  async function своиНазвания() {
    if (свои && сейчас() - своиПри < НП_ОБНОВЛЯТЬ) return свои;
    try { свои = await store.get('brain/names_own.json', {}) || {}; своиПри = сейчас(); } catch (_e) { свои = свои || {}; }
    return свои;
  }
  async function названияКоманды() {
    if (команды && сейчас() - командыПри < НП_ОБНОВЛЯТЬ) return команды;
    try {
      const t = await team('names_get');
      if (t && typeof t === 'object') {
        const data = {};                                                  // сервер: {город: {слово: {to, by, at}}} → {город: {слово: название}}
        for (const [city, words] of Object.entries(t)) for (const [w, v] of Object.entries(words || {}))
          if (v && v.to) (data[LC_TERRITORY.нпНорм(city)] = data[LC_TERRITORY.нпНорм(city)] || {})[LC_TERRITORY.нпНорм(w)] = String(v.to);
        команды = data; командыПри = сейчас();
        return data;
      }
    } catch (_e) { /* сервер не ответил — берём, что было */ }
    return команды || {};
  }
  async function местноеНазвание(city, word) {
    if (!word) return '';
    const встроено = LC_TERRITORY.псевдоним(city, word);
    if (встроено) return встроено;
    const г = LC_TERRITORY.нпНорм(LC_TERRITORY.чистыйГород(city)), w = LC_TERRITORY.нпНорм(word);
    const мои = ((await своиНазвания())[г] || {});
    if (мои[w]) return мои[w];
    return ((await названияКоманды())[г] || {})[w] || '';
  }
  async function выучитьНазвание(a) {
    a = a || {};
    const г = LC_TERRITORY.нпНорм(LC_TERRITORY.чистыйГород(a.city)), w = LC_TERRITORY.нпНорм(a.word), official = String(a.official || '').trim();
    if (!г || !w || !official || LC_TERRITORY.тотЖеНП(w, official)) return { ok: false, error: 'нечего запоминать' };
    const all = await store.get('brain/names_own.json', {}) || {};
    all[г] = { ...(all[г] || {}), [w]: official };
    await store.put('brain/names_own.json', all);
    свои = all; своиПри = сейчас();
    // в общий список команды; в памяти — сразу, чтобы не ждать обновления
    if (команды) команды[г] = { ...(команды[г] || {}), [w]: official };
    try { await team('names_put', null, { city: г, word: w, official }); return { ok: true, team: true }; }
    catch (e) { return { ok: true, team: false, error: String(e.message || e) }; }
  }

  async function territory(a) {
    a = a || {};
    const map = await картаНаправления(a.dir);
    // город филиала без скобок («Ачинск (Красноярск)» → «Ачинск»), местное название нас. пункта → официальное
    const город = LC_TERRITORY.чистыйГород(a.city);
    // «2 г» — дом 2 и «г.» (город), а не литера «г»
    if (a.building) a = { ...a, building: String(a.building).replace(/^(д|дом)\.?\s*/i, '').replace(/\s+(г|гор|город)\.?$/, '').trim() };
    // точка дома из карточки LeadChat (его карта подтвердила дом, точка точная) — адрес второй раз не геокодируем
    const точка = Array.isArray(a.pt) && a.pt.length === 2 && a.pt.every((x) => typeof x === 'number' && isFinite(x)) && (a.pt[0] || a.pt[1]) ? a.pt : null;
    // нас. пункт точки неизвестен — не подставляем город филиала (вышло бы ложное «в черте города»): геокодируем как обычно
    if (точка && a.ptLocality && !a.settlement) return итогТерритории(a, map, { pt: точка, locality: a.ptLocality, localities: (a.ptLocalities || []).filter(Boolean),
      text: 'точка из карточки LeadChat' + (a.ptText ? ': ' + a.ptText : '') }, a.settlement || '', false);
    const нп = (await местноеНазвание(город, a.settlement).catch(() => '')) || a.settlement || '';
    // The customer may have opened another city's listing. Search the stated
    // place first, without city bias; never drop it to accept a similar house.
    const варианты = [...new Set((нп ? [[нп, a.street, a.building], [город, нп, a.street, a.building]] : [[город, a.street, a.building]])
      .filter(Boolean).map((x) => x.filter(Boolean).join(', ')))];
    // годится только тот же адрес: та же улица, тот же дом; центр города — не адрес
    const ключА = a.street ? LC_ADDRESS.ключУлицы(LC_ADDRESS.полнаяУлица(a.street)) : '';
    const улицаТа = (x) => !a.street || [x.street, x.мкр].some((s) => s && LC_ADDRESS.ключУлицы(s) === ключА);
    const домТот = (x) => !a.building ? /exact|number|near|street/.test(x.precision)
      : /exact|number|near/.test(x.precision) && LC_ADDRESS.домКлюч(x.house) === LC_ADDRESS.домКлюч(a.building);
    const вНП = (x, name) => [x.locality,x.мкр,...(x.localities || []),...(x.districts || [])].some((l) => LC_TERRITORY.тотЖеНП(l, name));
    async function проверитьКандидатов(names) {
      const out = [];
      for (const l of names) {
        let list = [];
        try { list = (await геокодМного([l, a.street, a.building].filter(Boolean).join(', '), 3)).filter(рядом); } catch (_e) { /* без проверки */ }
        const hit = list.find((x) => улицаТа(x) && домТот(x) && LC_TERRITORY.тотЖеНП(x.locality, l));
        out.push({ locality: l, house: !!hit, text: hit ? hit.text : '' });
      }
      return out.sort((p, q) => Number(q.house) - Number(p.house));
    }
    // только рядом с городом филиала (≈120 км): одноимённые посёлки и улицы в других регионах — не наши
    let городТочка = LC_TERRITORY.центр(город);
    if (!городТочка) try { const c0 = await геокод(город); городТочка = c0 && c0.pt; } catch (_e) { /* без проверки расстояния */ }
    const рядом = (x) => !городТочка || !x.pt || LC_TERRITORY.km(городТочка, x.pt) <= 120;
    const все = [], похожие = [];
    let g = null;
    for (const q of варианты) {
      const raw = await геокодМного(q, 5);
      const remote = нп ? raw.filter((x) => улицаТа(x) && домТот(x) && вНП(x, нп) && !рядом(x)) : [];
      if (remote.length) return { ok:false,mismatch:true,qualified_location_unverified:true,
        error:'Указанный клиентом адрес найден в другом регионе: проверьте город и филиал до согласования и создания',
        candidates:remote.map((x)=>({locality:x.locality,house:true,text:x.text})) };
      const list0 = raw.filter(рядом);
      похожие.push(...list0.filter(улицаТа));
      const list = list0.filter((x) => улицаТа(x) && домТот(x));
      все.push(...list);
      g = list.find((x) => вНП(x, нп || город)) || null;
      if (g) break;
    }
    if (!g && map && !нп) g = все.find((x) => LC_TERRITORY.classify(map, x.pt).inMap) || null;
    let безДома = false;
    if (!g) { g = похожие.find((x) => /street|exact|number|near|range/.test(x.precision) && вНП(x, нп || город)) || null; безДома = !!g; }
    if (!g) {
      if (нп) return {ok:false,mismatch:true,qualified_location_unverified:true,
        error:'Карта не подтвердила населённый пункт или микрорайон «'+нп+'» вместе с улицей и домом: проверьте адрес и город клиента',candidates:[]};
      if (!все.length) {
        const где = [...new Set(похожие.filter((x) => !вНП(x, город)).map((x) => x.locality).filter(Boolean))].slice(0, 5);
        return { ok: false, mismatch: где.length > 0, error: 'на карте нет дома «' + [a.street, a.building].filter(Boolean).join(', ') + '» в «' + (нп || город) + '»',
          candidates: await проверитьКандидатов(где) };
      }
      const seen = new Set(), candidates = [];
      for (const x of все) { const k = LC_TERRITORY.нпНорм(x.locality); if (x.locality && !seen.has(k) && !вНП(x, город)) { seen.add(k); candidates.push({ locality: x.locality, text: x.text }); } }
      return { ok: false, mismatch: true, error: 'на карте «' + [a.street, a.building].filter(Boolean).join(', ') + '» в «' + (нп || город) + '» не нашлось', candidates: await проверитьКандидатов(candidates.slice(0, 5).map((c) => c.locality)) };
    }
    return итогТерритории(a, map, g, нп, безДома, городТочка);
  }
  async function итогТерритории(a, map, g, нп, безДома, городТочка) {
    const город = LC_TERRITORY.чистыйГород(a.city);
    let главный = String(a.mainCity || (String(a.city || '').match(/\(([^)]+)\)/) || [])[1] || '').replace(/\s+мск$/i, '').trim();
    let satellitePolicy = null, satelliteError = false;
    if (/^Евпатория$/i.test(город)) {
      try {
        if (!deps.policyGeo) throw new Error('Нет реестра');
        satellitePolicy = await deps.policyGeo({ city: a.city, dir: a.dir });
        const p = satellitePolicy && satellitePolicy.policy;
        if (!p || p.status !== 'known' || p.physical_city !== 'Евпатория' || p.main_branch !== 'Симферополь') throw new Error('Нет подтверждённого спутника');
        главный = p.main_branch;
      } catch (_e) { satelliteError = true; }
    }
    const cls = map ? LC_TERRITORY.classify(map, g.pt) : { inMap: false, zones: [], noMap: true };
    let cityPt = городТочка || LC_TERRITORY.центр(город) || null;
    if (!cityPt && !cls.inMap && город) { try { const c = await геокод(город); cityPt = c && c.pt; } catch (_e) { /* без расстояния */ } }
    let mainPt = null;
    if (!cls.inMap && главный && !LC_TERRITORY.центр(главный)) { try { const c = await геокод(главный); mainPt = c && c.pt; } catch (_e) { /* без расстояния */ } }
    const tv = LC_TERRITORY.этоТВ([a.tech, a.appl].filter(Boolean).join(', '));
    const d = LC_TERRITORY.decide(a.dir, cls, { locality: g.locality, localities: g.localities || [], city: город, pt: g.pt, cityPt, mainCity: главный, mainPt, tv });
    if (satellitePolicy && !satelliteError) {
      d.policyVersion = satellitePolicy.policy_version;
      d.acceptanceCity = satellitePolicy.policy.acceptance_city;
      d.why.push('Евпатория — спутник Симферополя; правила приёма по видам работ общие с Симферополем');
    }
    if (satelliteError) { d.approval = true; d.why.push('Не удалось подтвердить основной филиал Евпатории — проверьте филиал'); }
    const affected = /^(Ковров|Феодосия|Курган|Мытищи|Элиста|Дудинка|Зеленодольск|Златоуст|Ульяновск|Ставрополь|Невинномысск)$/i;
    const policyCity = /мытищи/i.test(cls.branch || '') ? 'Мытищи' : affected.test(g.locality || '') ? g.locality : город;
    if (deps.policyGeo && /^(Ковров|Феодосия|Курган|Мытищи|Элиста|Дудинка|Зеленодольск|Златоуст|Ульяновск|Ставрополь|Невинномысск)$/i.test(policyCity)) {
      try {
        const result = await deps.policyGeo({ city: policyCity, dir: a.dir, latitude: g.pt && g.pt[1], longitude: g.pt && g.pt[0] });
        const p = result && result.policy;
        if (!p) throw new Error('Нет данных реестра');
        d.policyVersion = result.policy_version;
        if (['closed', 'unknown', 'needs_zone', 'needs_confirmation'].includes(p.status)) { d.approval = true; d.why.push(p.reason); }
        else {
          if (p.lead) d.hours = p.zone === 'north' ? '3–3,5' : '2–2,5';
          if (p.earliest) d.earliest = p.earliest;
          if (p.far_trip) d.far = true;
          if ((p.rule_ids || []).length) d.why.push('Уточнение регламента: ' + (p.zone === 'north' ? 'северная зона Мытищей, 3–3,5 часа' : p.zone === 'south' ? 'южная зона Мытищей, 2–2,5 часа' : policyCity));
        }
      } catch (_e) { d.approval = true; d.why.push('Не удалось проверить последнее изменение регламента — проверьте филиал'); }
    }
    const special = LC_TERRITORY.особые(a.dir, a.city || g.locality, a.appl || '', a.partner);
    return { ok: true, ...d, tv, inMap: cls.inMap, zones: cls.zones, locality: g.locality, found: g.text + (безДома ? ' (дома ' + a.building + ' на карте нет — определено по улице)' : ''), settlementFixed: нп !== (a.settlement || '') ? нп : '', satelliteOf: d.satelliteOf || cls.satelliteOf || '',
      address_verified:!безДома,checkedAddress:{city:a.city||'',settlement:a.settlement||'',street:a.street||'',building:a.building||''},verifiedSettlement:нп,
      special: special.map((x) => ({ branch: x.branch, note: x.note, chats: x.chats.map((r) => r.source) })),
      mapTitle: map ? map.title : '', mapUpdated: map ? map.updated : 0 };
  }

  /* ---------- сервер команды ---------- */
  async function tg(a) {
    a = a || {};
    if (a.action === 'chats') return { ok: true, chats: await team('tg_chats', a.fresh ? { fresh: '1' } : null) };
    if (a.action === 'send') {
      // «Избранное» владельца («me») — только для уведомлений самого мозга о лимите, не для запросов расширения
      if (!/^-?\d+$/.test(String(a.chat == null ? '' : a.chat).trim())) return { ok: false, error: 'неверный чат' };
      const photos = (a.photos || []).slice(0, 4).filter((x) => x && x.b64 && x.b64.length < 900000);
      // 2.1.3: guard — программа Telegram сама проверяет чат города на просьбу филиала и сразу отправляет (одно задание вместо двух);
      // ждёт просьба — { ok: false, guard: [...] }; старая программа — { old_agent: true }: расширение сделает по-старому
      const guard = !!a.guard && !a.reply_to;
      let r;
      try {
        r = await team('tg_send', null, { chat: a.chat, text: a.text, reply_to: a.reply_to || undefined, conv: a.conv || '', ...(photos.length ? { photos } : {}),
          ...(guard ? { guard: 1, since: Number(a.since) || 0, n: Math.min(Number(a.n) || 30, 50) } : {}) });
      } catch (e) {
        if (guard && e && e.status === 409) { журнал({ op: 'tg', action: 'send', guard, old_agent: true }); return { ok: false, old_agent: true, error: 'программа Telegram на ПК старая' }; }
        throw e;
      }
      // журнал без текста: куда и чем кончилось
      журнал({ op: 'tg', action: 'send', ok: !!(r && r.ok), guard, blocked: !!(r && r.guard), len: String(a.text || '').length, photos: photos.length });
      return typeof r === 'object' ? r : { ok: false, error: String(r) };
    }
    if (a.action === 'replies') return { ok: true, ...(await team('tg_replies', { chat: a.chat, msg: a.msg })) };
    // последние сообщения чата города — нет ли неотвеченной просьбы филиала (защита от перекрытия)
    if (a.action === 'recent') {
      try { return { ok: true, ...(await team('tg_recent', { chat: a.chat, n: a.n || 30, since: a.since || 0 })) }; }
      catch (e) { return { ok: false, error: String(e.message || e) }; }
    }
    if (a.action === 'topics') return { ok: true, ...(await team('tg_topics', { chat: a.chat })) };
    // 2.1.3: guard_ok — и мозг, и сервер команды умеют «проверить и отправить» одним заданием (старый мозг этого поля не даёт:
    // расширение тогда проверяет и отправляет по-старому, двумя заданиями — иначе guard ушёл бы обычной отправкой без проверки)
    if (a.action === 'status') { const s = await team('tg_status'); return { ok: true, ...s, guard_ok: !!(s && s.guard === true) }; }
    if (a.action === 'ping') return { ok: true, ...(await team('tg_ping')) };
    if (a.action === 'scan') return { ok: true, result: await team('tg_scan', { from: a.from || 0, n: a.n || 8, depth: a.depth || 200 }) };
    if (a.action === 'search') return { ok: true, result: await team('tg_search', { q: String(a.q || ''), limit: a.limit || 60 }) };
    return { ok: false, error: 'неизвестное действие' };
  }
  async function links_get(a) {
    const t = await team('links_get', { account: String((a || {}).account || '') });
    return { ok: true, ...(t && typeof t === 'object' ? t : {}) };
  }
  async function links_put(a) {
    a = a || {};
    await team('links_put', null, { account: a.account, short: a.short, profile: a.profile, origin: a.origin || '', dir: a.dir || '' });
    return { ok: true };
  }
  async function names_get() { return { ok: true, names: await названияКоманды() }; }

  return {
    // с ИИ (режим влияет): ответ правилами в режиме rules
    ии: { extract, address, checklist, addition, pick },
    // без ИИ
    прочие: { advertiser: advertiser.apply, territory, name_learn: выучитьНазвание, names_get, links_get, links_put, tg },
    // для тестов и разбора
    внутр: { verifyAddress, геокодМного, картаНаправления, местноеНазвание, хвост, ТАЙМАУТЫ },
  };
}

module.exports = { создатьОперации };
