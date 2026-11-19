/* МОЗГ ЛИД-ЦЕНТРА (lead-centre-brain, облачная функция Node.js 22): вся логика с ИИ, картами и ключами — здесь,
   расширение и помощник AHK — оболочки с личным токеном владельца.
   POST <адрес> {op, args, v, dev} + X-Brain-Auth: <личный токен> → {ok, …, mode, budget}
   GET  <адрес>?op=admin — страница владельца (вход паролем администратора; ADMIN_HOST — только на этом адресе).
   Коды: 401 token — нет/неверный/отозван токен; 402 rules — ИИ выключен (лимит), ответ посчитан правилами;
   429 busy — слишком часто; 502 upstream — не ответил ИИ / сервер команды. В журнал — без текстов клиентов.
   Режим — в каждом ответе (mode): economy — проверки очереди (args.purpose / ctx.purpose = 'inbox') отвечены правилами
   (200, rules:true, economy:true); учёт расходов не прочитан — rules и budget.unknown (fail safe: ИИ не зовём).
   Окружение функции (ключи — только здесь): GIGACHAT_KEY, YANDEX_API_KEY (пусто — IAM-токен функции), YANDEX_FOLDER,
   YANDEX_GEOCODER_KEY, YANDEX_SUGGEST_KEY, DADATA_KEY, ADMIN_PASSWORD_SHA256, BRAIN_TOKEN, TEAM_URL, BUCKET,
   LIMIT_RUB (5000), FIXED_RUB (150); по желанию GIGA_PAID (купленные пакеты GigaChat), CHAIN_<ОПЕРАЦИЯ>, GIGACHAT_SCOPE,
   ADMIN_HOST (свой адрес страницы владельца — API Gateway), S3_URL (адрес хранилища; свой сервер — vps/brain_http.js). */
'use strict';
const { AsyncLocalStorage } = require('node:async_hooks');
const { createAssistant, parseJsonObject, coherentAssistantCandidate, jsonNormalizationNeeded } = require('./assistant');
const { создатьСеть } = require('./net');
const { создатьХранилище } = require('./store');
const { создатьБюджет } = require('./budget');
const { создатьКэш } = require('./cache');
const { создатьИИ, ЦЕПОЧКИ, ASSISTANT_MODEL_BUDGET_MS } = require('./ai');
const { создатьТокены } = require('./tokens');
const { создатьКоманду } = require('./team');
const { загрузитьМодули } = require('./modules');
const { создатьОперации } = require('./ops');
const { ЭКОНОМ_ОЧЕРЕДЬ } = require('./rules');

const ВЕРСИЯ = '2.4.242';
const ИИ_ОПЕРАЦИИ = new Set(['extract', 'address', 'checklist', 'addition', 'pick']);
const МАКС_ТЕЛО = 3.5e6;                                   // фото в Telegram: до 4 × 900 КБ base64
const ЧАСТОТА = { окно: 60e3, запросов: 150 };             // на токен в экземпляре: «Входящие» — пачками, но не сотнями
const НЕ_КЭШ = { 'Cache-Control': 'no-store', Pragma: 'no-cache' };
/* Страница владельца. Адрес functions.yandexcloud.net — ОБЩИЙ для функций всех клиентов Yandex Cloud (одно «происхождение»
   в браузере): страница чужой функции могла бы открыть нашу и читать пароль и пропуск. Поэтому страница — в песочнице
   (CSP sandbox без allow-same-origin: у неё своё, ни с кем не общее происхождение; хранилищ браузера у неё нет), пропуск —
   только в памяти страницы и короткий (tokens.js), пароль — при каждом открытии. Запросы страницы — «простые» (text/plain,
   пропуск в теле, без предзапроса), ответы на них — с Access-Control-Allow-Origin: null. Надёжно — свой адрес
   (API Gateway <id>.apigw.yandexcloud.net): ADMIN_HOST в настройках — тогда на общем адресе страницы владельца нет */
const ЗАЩИТА_СТРАНИЦЫ = (хост) => ({
  'Content-Security-Policy': "sandbox allow-scripts allow-forms allow-modals; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'"
    + (хост ? ' https://' + хост : '') + "; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
  'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff',
});

function страницаВладельца() {
  /* global __LC_ADMIN */
  if (typeof __LC_ADMIN !== 'undefined') return __LC_ADMIN;
  return require('fs').readFileSync(require('path').join(__dirname, 'admin.html'), 'utf8');
}
// в журнал — без цифр длиннее 4 (телефоны, номера заявок) и не длиннее 80 знаков
const безДанных = (s) => String(s || '').replace(/\d{5,}/g, '#').slice(0, 80);
/* системная часть помощника AHK: правила + стиль + примеры оператора + РЕГЛАМЕНТ КОМПАНИИ (он — последним, обычно 6–17 тыс.
   знаков). Берём целиком до 24 000 знаков (≈ 8 тыс. токенов: GigaChat-2 и YandexGPT Lite столько принимают; расход
   считается по usage ответа API). Длиннее — режем середину (примеры), а не хвост: регламент и цены не теряем */
const СИСТЕМА_AHK = 24000;
function системаПомощника(x) {
  const s = String(x || '');
  if (s.length <= СИСТЕМА_AHK) return s;
  const вставка = '\n…\n', голова = 6000;
  return s.slice(0, голова) + вставка + s.slice(s.length - (СИСТЕМА_AHK - голова - вставка.length));
}

function создать(deps0) {
  const d = deps0 || {};
  const env = d.env || process.env;
  const запрос = d.запрос || создатьСеть();
  const now = d.now || (() => Date.now());
  const sleep = d.sleep;
  const log = d.log || ((x) => console.log(JSON.stringify(x)));
  let iamТокен = '';
  const principals = new AsyncLocalStorage();
  const iam = () => iamТокен;
  const store = d.store || создатьХранилище({ запрос, bucket: env.BUCKET || 'lc-team-b1g1hrbbp0j5', iam, s3: env.S3_URL });
  const team = создатьКоманду({ запрос, env, user: () => principals.getStore()?.user || 'brain' });
  // о переходе в экономный / выключенный режим — владельцу в «Избранное» Telegram (через программу на ПК)
  const уведомить = (text) => team('tg_send', null, { chat: 'me', text: 'Мозг лид-центра: ' + text, conv: 'brain' }, { timeout: 8000 });
  const budget = создатьБюджет({ store, env, now, уведомить, log, id: d.id, sleep });
  const cache = создатьКэш({ store, now, log });
  const ai = создатьИИ({ запрос, env, budget, cache, iam, log, now, sleep });
  const assistant = createAssistant({ env, запрос, ai, now });
  let M = d.M || null, ops = null;
  const операции = () => {
    if (!ops) { M = M || загрузитьМодули(d.extDir); ops = создатьОперации({ M, ai, team, запрос, store, env, now, sleep, log, таймауты: d.таймауты, policyGeo: assistant.geography }); }
    return ops;
  };
  const tokens = создатьТокены({ store, env, now, sleep, rand: d.rand });
  const частота = new Map();

  function ответ(status, obj, cors, extra) {
    return { statusCode: status, headers: { 'Content-Type': 'application/json; charset=utf-8', ...НЕ_КЭШ, ...(cors || {}), ...(extra || {}) },
      body: JSON.stringify(obj), isBase64Encoded: false };
  }
  function часто(id) {
    const t = now(), list = (частота.get(id) || []).filter((x) => t - x < ЧАСТОТА.окно);
    list.push(t); частота.set(id, list);
    return list.length > ЧАСТОТА.запросов;
  }
  const бюджетКратко = (s) => (s.unknown ? { month: s.month || '', unknown: true } : { spent: Math.round(s.spent * 100) / 100, limit: s.limit, month: s.month });

  /* страница владельца: вход паролем → пропуск на 20 минут → токены, входы, расход, режим, лимит */
  async function владелец(args, h, ip, dev) {
    const a = args || {};
    if (a.action === 'login') return tokens.войти(a.password, { ip, dev });
    if (!tokens.пропуск(h['x-admin-session'] || a.session)) return { ok: false, code: 'session', error: 'войдите заново' };
    if (a.action === 'overview' || a.action === 'summary') {
      const s = await budget.состояние();
      const входы = (await tokens.входы()).slice(-50).reverse();
      const неверные = await tokens.неверныеПароли().catch(() => []);
      return { ok: true, budget: s, summary: await budget.сводка(a.month), tokens: await tokens.список(), logins: входы, seen: await tokens.гдеТокены(),
        fails: { day: неверные.filter((x) => now() - x.at < 24 * 3600e3).length, last: неверные.slice(-10).reverse() }, events: (await budget.события()).reverse(),
        chains: Object.fromEntries(Object.keys(ЦЕПОЧКИ).map((k) => [k, ai.цепочка(k)])),
        setup: { gigachat: !!env.GIGACHAT_KEY, yandex: !!(env.YANDEX_FOLDER || env.FOLDER_ID), yandexKey: !!env.YANDEX_API_KEY, geocoder: !!env.YANDEX_GEOCODER_KEY,
          dadata: !!env.DADATA_KEY, suggest: !!env.YANDEX_SUGGEST_KEY, team: !!(env.TEAM_URL && env.BRAIN_TOKEN), gigaPaid: String(env.GIGA_PAID || '') }, v: ВЕРСИЯ };
    }
    if (a.action === 'issue') return { ok: true, ...(await tokens.выпустить(a.label)) };
    if (a.action === 'revoke') return { ok: await tokens.отозвать(String(a.id || '')) };
    if (a.action === 'label') return { ok: await tokens.метка(String(a.id || ''), a.label) };
    if (a.action === 'mode') { await budget.задатьРежим(a.mode === 'auto' ? null : a.mode); return { ok: true, budget: await budget.состояние() }; }
    if (a.action === 'limit') { await budget.задатьЛимит(a.rub); return { ok: true, budget: await budget.состояние() }; }
    return { ok: false, error: 'неизвестное действие' };
  }

  const handle = async function handle(event, context) {
    const t0 = now();
    const ev = event || {};
    if (context && context.token && context.token.access_token) iamТокен = context.token.access_token;
    const h = {};
    for (const [k, v] of Object.entries(ev.headers || {})) h[k.toLowerCase()] = String(v);
    const origin = h.origin || '';
    // CORS — только запросам фона расширения (страница владельца — со своего адреса, ей не нужно)
    const cors = /^chrome-extension:\/\/[a-p]{32}$/.test(origin) ? { 'Access-Control-Allow-Origin': origin, Vary: 'Origin',
      'Access-Control-Allow-Headers': 'X-Brain-Auth, Authorization, Content-Type', 'Access-Control-Allow-Methods': 'POST, OPTIONS', 'Access-Control-Max-Age': '600' } : {};
    const method = String(ev.httpMethod || 'GET').toUpperCase();
    const q = ev.queryStringParameters || {};
    const хост = /^[a-z0-9.-]{3,253}(:\d{1,5})?$/.test(String(h['x-forwarded-host'] || h.host || '').split(',')[0].trim().toLowerCase())
      ? String(h['x-forwarded-host'] || h.host).split(',')[0].trim().toLowerCase() : '';
    const свойАдрес = String(env.ADMIN_HOST || '').trim().toLowerCase();
    const владельцуЗдесь = !свойАдрес || хост === свойАдрес;
    // ответы странице владельца из песочницы (происхождение «null»)
    const corsВладельца = origin === 'null' ? { 'Access-Control-Allow-Origin': 'null', Vary: 'Origin' } : {};
    if (method === 'OPTIONS') return { statusCode: cors['Access-Control-Allow-Origin'] ? 204 : 403, headers: { ...cors, ...НЕ_КЭШ }, body: '' };
    if (method === 'GET') {
      if (q.op === 'admin' && !владельцуЗдесь) return ответ(404, { ok: false, error: 'страница владельца — по своему адресу (ADMIN_HOST)', code: 'admin_host' });
      if (q.op === 'admin') return { statusCode: 200, headers: { 'Content-Type': 'text/html; charset=utf-8', ...НЕ_КЭШ, ...ЗАЩИТА_СТРАНИЦЫ(хост) }, body: страницаВладельца(), isBase64Encoded: false };
      return ответ(200, { ok: true, service: 'lead-centre-brain', v: ВЕРСИЯ }, cors);
    }
    if (method !== 'POST') return ответ(405, { ok: false, error: 'нужен POST', code: 'method' }, cors);
    let raw = ev.body || '';
    if (ev.isBase64Encoded) raw = Buffer.from(raw, 'base64').toString('utf8');
    if (raw.length > МАКС_ТЕЛО) return ответ(413, { ok: false, error: 'слишком большой запрос', code: 'too_big' }, cors);
    let body;
    try { body = JSON.parse(raw || '{}'); } catch (_e) { body = null; }
    if (!body || typeof body !== 'object' || Array.isArray(body)) return ответ(400, { ok: false, error: 'нужен JSON {op, args}', code: 'bad_json' }, cors);
    const op = String(body.op || q.op || '');
    const ip = String(((ev.requestContext || {}).identity || {}).sourceIp || (h['x-forwarded-for'] || '').split(',')[0] || '').trim();
    const dev = String(body.dev || '').slice(0, 40);

    if (op === 'admin') {
      if (!владельцуЗдесь) return ответ(404, { ok: false, error: 'страница владельца — по своему адресу (ADMIN_HOST)', code: 'admin_host' });
      try {
        const r = await владелец(body.args, h, ip, dev);
        log({ op: 'admin', action: String((body.args || {}).action || '').slice(0, 20), ok: !!r.ok, ms: now() - t0 });
        return ответ(r.ok ? 200 : r.code === 'busy' ? 429 : r.code === 'session' || r.code === 'password' ? 401 : 400, r, corsВладельца);
      } catch (e) { return ответ(502, { ok: false, error: безДанных(e.message || e), code: 'upstream' }, corsВладельца); }
    }

    // Authorization у облачной функции — служебный заголовок Yandex Cloud (чужой токен там → 403 ещё до мозга); личный токен — в X-Brain-Auth
    const tok = String(h['x-brain-auth'] || h.authorization || '').replace(/^Bearer\s+/i, '').trim();
    let v;
    try { v = await tokens.проверить(tok, { ip, dev }); }
    catch (e) { log({ op, status: 502, err: безДанных(e.message) }); return ответ(502, { ok: false, error: 'мозг не прочитал список токенов — попробуйте ещё раз', code: 'upstream' }, cors); }
    if (!v.ok) { log({ op, status: 401 }); return ответ(401, { ok: false, error: 'нужен токен: откройте настройки расширения', code: 'token' }, cors); }
    principals.getStore().user = 'brain-' + v.rec.id;              // только в контексте этого запроса
    if (часто(v.rec.id)) return ответ(429, { ok: false, error: 'слишком много запросов — подождите минуту', code: 'busy' }, cors);

    let сост;
    // сбой чтения учёта / состояния — ещё раз; не прочиталось — ИИ нельзя (fail safe): не знаем, сколько потрачено
    // и не выключил ли владелец ИИ вручную. Ответ — правилами (402 rules), budget.unknown — для расширения
    try { сост = await budget.состояние(); } catch (_e) {
      try { сост = await budget.состояние(); } catch (e2) {
        log({ ev: 'учёт', ok: false, err: безДанных(e2 && e2.message) });
        сост = { mode: 'rules', spent: undefined, limit: undefined, month: '', unknown: true };
      }
    }
    const режим = сост.mode;
    const args = body.args && typeof body.args === 'object' ? body.args : {};
    let res, status = 200;
    try {
      if (op === 'status') {
        const пакеты = {};
        for (const m of ['GigaChat-2', 'GigaChat-2-Pro', 'GigaChat-2-Max']) { const p = await budget.пакет(m); пакеты[m] = { left: p.left, total: p.total, free: p.free }; }
        res = { ok: true, v: ВЕРСИЯ, models: { chains: Object.fromEntries(Object.keys(ЦЕПОЧКИ).map((k) => [k, ai.цепочка(k)])), packages: пакеты },
          token: { label: v.rec.label, created: v.rec.created }, auto: сост.auto, manual: сост.manual };
      } else if (op === 'ahk_chat') {
        if (режим === 'rules') { status = 402; res = { ok: false, error: сост.unknown ? 'ИИ временно выключен: мозг не прочитал учёт расходов — попробуйте через минуту' : 'ИИ выключен до 1-го числа: лимит ' + (сост.total || 5000) + ' ₽', code: 'rules' }; }
        else {
          const system = системаПомощника(args.system), task = String(args.task || '').slice(0, 30000);
          // снимок окна (как слал помощник сам: GigaChat — картинкой, YandexGPT — текстом после распознавания)
          const im = args.image && typeof args.image.b64 === 'string' && args.image.b64.length > 100 && args.image.b64.length < 2.5e6
            ? { b64: args.image.b64.replace(/^data:[^,]*,/, ''), type: String(args.image.type || 'image/jpeg') } : null;
          if (args.kind === 'ocr') {
            if (!im) { status = 400; res = { ok: false, error: 'нет снимка', code: 'bad_args' }; }
            else res = { ok: true, text: await ai.текстСнимка('ahk_chat', im), model: 'vision-ocr' };
          } else if (!task) { status = 400; res = { ok: false, error: 'пустой task', code: 'bad_args' }; }
          else {
            const max = Math.max(1, Math.min(800, Number(args.max_tokens) || 0)) || undefined;
            const temp = args.temperature == null || args.temperature === '' ? undefined : Math.max(0, Math.min(1, Number(args.temperature) || 0));
            const r = await ai.спросить('ahk_chat', system, task, { режим, image: im, maxTokens: args.max_tokens ? max : undefined, temperature: temp });
            res = { ok: true, text: r.text, model: r.model, cached: r.cached };
          }
        }
      } else if (op === 'checklist') {
        // Both the normal CRM form and the personal assistant use the same
        // reviewed server catalog. No legacy model prompt or write grant here.
        const ctx={...(args.ctx||{}),dir:args.dir||(args.ctx||{}).dir};
        res = await assistant({ action: 'checklist', ctx }, v.rec.id, режим);
        const address=res?.facts?.address;
        if(res?.ok&&res.reviewed_policy&&address?.settlement&&address?.building){
          let territory;
          try{territory=await операции().прочие.territory({dir:res.routing.direction,city:ctx.city,
            settlement:address.settlement,street:address.street,building:address.building,partner:ctx.partner});}
          catch(_e){territory={ok:false,qualified_location_unverified:true,error:'Карта не ответила: полный адрес с населённым пунктом или микрорайоном не проверен'};}
          res={...res,territory_review:territory};
          if(!territory.ok||territory.address_verified!==true||territory.mismatch||territory.qualified_location_unverified){
            const reason=territory.error||'Карта не подтвердила полный адрес: проверьте город и филиал до создания и согласования';
            res={...res,hard_block:true,operator_review:reason,reason:res.refuse||reason,
              rule_ids:[...new Set([...(res.rule_ids||[]),'DOC-L0611','DOC-L0623','DOC-L0642','DOC-L0646'])]};
          }
        }
      } else if (op === 'assistant') {
        res = await assistant(args, v.rec.id, режим);
        if (res && ['personal_owner','personal_identity','auto_disabled','auto_activation'].includes(res.code)) status = 403;
      } else if (ИИ_ОПЕРАЦИИ.has(op)) {
        // экономный режим: проверки очереди («Готовые», мгновенная проверка «Входящих» — purpose:'inbox') — без ИИ, правилами;
        // работа оператора в панели — с ИИ. Ответ 200 с rules:true и economy:true (не 402: ИИ не выключен)
        const очередь = args.purpose === 'inbox' || !!(args.ctx && args.ctx.purpose === 'inbox');
        const безИИ = режим === 'economy' && очередь;
        res = await операции().ии[op](op === 'extract' || op === 'address' ? (body.args && body.args.ctx) || body.ctx || args : args,
          безИИ ? 'rules' : режим, безИИ ? { почему: ЭКОНОМ_ОЧЕРЕДЬ } : undefined);
        if(op==='extract'&&res?.ok!==false&&res?.lead){
          const ctx=(body.args&&body.args.ctx)||body.ctx||args;
          const reviewed=await assistant({action:'checklist',ctx},v.rec.id,режим);
          const rejected=M.LC_EXTRACT.fromIdentity(ctx.identity,ctx.convId).rejected||[];
          res=M.LC_WORKFLOW.projectContactFacts(res,reviewed,rejected);
        }
        if (режим === 'rules' && res && res.ok !== false) { status = 402; res = { ...res, code: 'rules' }; }
        else if (безИИ && res && res.ok !== false) res = { ...res, rules: true, economy: true };
      } else if (Object.prototype.hasOwnProperty.call(операции().прочие, op)) {
        res = await операции().прочие[op](args);
      } else { status = 400; res = { ok: false, error: 'неизвестная операция: ' + op.slice(0, 30), code: 'bad_op' }; }
    } catch (e) {
      status = 502;
      res = { ok: false, error: String((e && e.message) || e).slice(0, 300), code: e && e.rules ? 'rules' : 'upstream' };
    }
    try { await budget.сохранить(); } catch (e) { log({ ev: 'учёт', ok: false, err: безДанных(e.message) }); }
    let после = сост;
    try { после = await budget.состояние(); } catch (_e) { /* как было */ }
    log({ op, status, ok: !!(res && res.ok), mode: режим, ms: now() - t0, tok: v.rec.id });
    return ответ(status, { ...(res || {}), mode: после.mode || режим, budget: бюджетКратко(после) }, cors);
  };
  const handler = (event, context) => principals.run({ user: 'brain' }, () => handle(event, context));
  let nativeNotifications=null;
  // Only the existing authenticated loopback service route exposes this.
  // No public operation, model tool or browser token can reach it.
  handler.notifyNative=async(args)=>{
    if(env.LEADBOT_NATIVE_NOTIFICATIONS_ENABLED!=='1')
      return {ok:false,state:'disabled',telegram_confirmed:false};
    const allowed=args?.action==='prepare'?['action','payload']:['action','payload','send_before'];
    if(!['prepare','send'].includes(args?.action)||Object.keys(args).sort().join()!==allowed.sort().join())
      throw Error('Неверный контракт служебной отписки');
    if(!nativeNotifications)nativeNotifications=require('./native-notifications').create({
      enabled:true,team,now,
      directory:env.LEADBOT_NATIVE_NOTIFICATIONS_DIR||'/opt/lead-centre/runtime/native-notifications',
    });
    return principals.run({user:'native_'+String(args.payload?.principal_id||'').replace(/-/g,'').slice(0,32)},
      ()=>args.action==='prepare'?nativeNotifications.prepare(args.payload)
        :nativeNotifications.send(args.payload,args.send_before));
  };
  // Called only by the authenticated loopback HTTP route, never by public ops.
  handler.completeLegacy = async (args) => {
    if (!args || typeof args.system !== 'string' || typeof args.task !== 'string'
        || args.system.length > 140000 || args.task.length > 140000
        || !Number.isInteger(args.max_tokens) || args.max_tokens < 1 || args.max_tokens > 1200
        || (args.deadline_ms !== undefined && (!Number.isInteger(args.deadline_ms)
          || args.deadline_ms < 1 || args.deadline_ms > ASSISTANT_MODEL_BUDGET_MS)))
      throw Error('Неверный контракт внутреннего запроса');
    const deadline = now() + (args.deadline_ms ?? ASSISTANT_MODEL_BUDGET_MS);
    const state = await budget.состояние();
    if (state.unknown || state.mode === 'rules') throw Error('ИИ выключен или бюджет не подтверждён');
    const remaining = deadline - now();
    if (remaining < 1500) throw Error('Истёк срок внутреннего запроса');
    let rejected = null, generation = null, result;
    try {
      result = await ai.спросить('assistant', args.system, args.task,
        {режим:state.mode, maxTokens:args.max_tokens, срок:remaining, singleAttempt:true,
         ...(args.response_format !== undefined ? {responseFormat:args.response_format} : {}),
         годен:(text,meta)=>{if(meta)generation=meta; const value=parseJsonObject(text);
           const valid=!!value && coherentAssistantCandidate(value,args.response_format);
           if(!valid)rejected=String(text); return valid;}});
    } catch (error) {
      if (error.неПоФорме && rejected !== null) {
        // This evidence is returned only by the authenticated loopback route,
        // never written to the shared journal or exposed through public ops.
        error.modelFormatDiagnostics = {
          text: rejected.slice(0, 6000), chars: rejected.length, truncated: rejected.length > 6000,
          sha256: require('crypto').createHash('sha256').update(rejected).digest('hex'),
          ...(generation ? {generation} : {}),
        };
      }
      try { await budget.сохранить(); }
      catch (saveError) { log({ev:'учёт',ok:false,err:безДанных(saveError.message)}); }
      throw error;
    }
    await budget.сохранить();
    return {ok:true,text:JSON.stringify(parseJsonObject(result.text)),model:result.model,cached:!!result.cached,
      model_json_normalized:jsonNormalizationNeeded(result.text),
      ...(result.generation ? {generation:result.generation} : {}),auto_enabled:false};
  };
  return handler;
}

let готовый = null;
/* точка входа Yandex Cloud Functions: index.handler */
async function handler(event, context) {
  if (!готовый) готовый = создать();
  return готовый(event, context);
}
async function completeLegacy(args) {
  if (!готовый) готовый = создать();
  return готовый.completeLegacy(args);
}

async function notifyNative(args){
  if(!готовый)готовый=создать();
  return готовый.notifyNative(args);
}

module.exports = { handler, completeLegacy, notifyNative, создать, ВЕРСИЯ, системаПомощника, СИСТЕМА_AHK };
