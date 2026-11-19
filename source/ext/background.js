/* Фон расширения 2.0 — оболочка. ИИ, карты, Telegram и общая память — на сервере «мозг» (одна функция мозг()):
   расширение знает только адрес мозга и личный токен владельца, ключей в нём нет. В браузере остаются CRM
   (рабочая сессия оператора; форму разбирает offscreen-страница — в фоне нет DOMParser) и Авито
   (страницу продавца отдаёт только браузер). Без токена или с отозванным токеном фон не делает ничего. */
importScripts('config.js', 'avito.js', 'worktype.js', 'personal-tab.js', 'personal-guard.js', 'personal-link.js', 'native-api.js', 'native-office-host.js');
const personalOrigins=(chrome.runtime.getManifest().content_scripts||[]).flatMap(s=>s.matches||[]).map(u=>new URL(u.replace(/\*$/,'')).origin);
const personalTabs=LC_PERSONAL_TAB.create(chrome,personalOrigins),personalGuard=LC_PERSONAL_GUARD.create(chrome,personalOrigins,personalTabs.isDedicated);
const personalLink=LC_PERSONAL_LINK.create(chrome,personalOrigins,personalTabs.isDedicated);
personalLink.restore().catch(()=>{});
const nativeOfficeHost=typeof LC_NATIVE_OFFICE_HOST!=='undefined'?LC_NATIVE_OFFICE_HOST.create(chrome,personalOrigins,{isObserverTab:personalTabs.isDedicated}):null;
nativeOfficeHost?.install().catch(()=>{});

/* ---------- МОЗГ ---------- */
const ВЕРСИЯ_API = '2.0.0';
// сроки — как у прежних прямых запросов: экран ждёт столько же (разбор 50 с, адрес и регламент 45, территория 9,
// выбор вида работ 25); отправка в Telegram — 75 с (мозг ждёт компьютер с Telegram до 40 с), остальное — 30 с
const СРОКИ = { assistant: 45000, extract: 50000, address: 45000, checklist: 45000, addition: 45000, territory: 9000, pick: 25000, status: 15000, tgSend: 75000, иначе: 30000 };
const НУЖЕН_ТОКЕН = 'Нужен токен: откройте настройки расширения';
const нуженТокен = (state = 'missing') => ({ ok: false, code: 'token', needToken: true, token_state: state,
  error: state === 'missing' ? НУЖЕН_ТОКЕН : 'Сервер не принял сохранённый токен — проверьте состояние в настройках расширения' });

async function прочитать(k) {
  try { return (await chrome.storage.local.get(k))[k]; } catch (_e) { return undefined; }
}
async function записать(o) {
  try { await chrome.storage.local.set(o); } catch (_e) { /* память недоступна — не страшно */ }
}
async function стереть(k) {
  try { await chrome.storage.local.remove(k); } catch (_e) { /* нечего стирать */ }
}
const токен = async () => {
  try { return String((await chrome.storage.local.get('brainToken')).brainToken || '').trim(); }
  catch (_e) { throw Object.assign(new Error('Не удалось прочитать настройки расширения — повторите проверку. Токен не удалён.'), { code: 'storage' }); }
};
// отозванный токен помним отпечатком (сам токен второй раз не храним): пока его не сменят — в мозг с ним не ходим
const отпечаток = (t) => t.length + ':' + t.slice(0, 3) + '…' + t.slice(-4);
const плохойОтпечаток = x => typeof x === 'string' ? x : x && x.fingerprint;
let ПРОВЕРКА_ТОКЕНА = null;
const отказДоступа = async () => нуженТокен(await токен() ? 'rejected' : 'missing');
async function доступ() {
  const t = await токен();
  if (!t) return false;
  const плохой = await прочитать('brainTokenBad');
  if (плохойОтпечаток(плохой) !== отпечаток(t)) return true;
  if (плохой && плохой.at && Date.now() - плохой.at < 60000) return false;
  if (!ПРОВЕРКА_ТОКЕНА || ПРОВЕРКА_ТОКЕНА.token !== t) {
    const check = { token: t };
    check.promise = (async () => {
      const [r] = await мозгРаз('status', {}, { token: t });
      if (r && r.ok === true) return true;
      if (r && r.code === 'token') return false;
      throw Object.assign(new Error((r && r.error) || 'Не удалось проверить токен: сервер не ответил'), { code: (r && r.code) || 'network' });
    })().finally(() => { if (ПРОВЕРКА_ТОКЕНА === check) ПРОВЕРКА_ТОКЕНА = null; });
    ПРОВЕРКА_ТОКЕНА = check;
  }
  return ПРОВЕРКА_ТОКЕНА.promise;
}

// устройство — для журнала входов на админ-странице (время, IP, устройство); случайный номер, без данных о компьютере
// одно обещание на всё: первые запросы разом (вкладка открылась) не заведут два разных номера
let УСТРОЙСТВО = null;
function устройство() {
  if (!УСТРОЙСТВО) УСТРОЙСТВО = (async () => {
    let d = await прочитать('brainDev');
    if (!d) {
      const b = new Uint8Array(9);
      try { crypto.getRandomValues(b); } catch (_e) { for (let i = 0; i < b.length; i++) b[i] = Math.floor(Math.random() * 256); }
      d = 'ext-' + Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
      await записать({ brainDev: d });
    }
    return d;
  })();
  return УСТРОЙСТВО;
}

// режим и расход — для настроек; пишем только при смене режима (не на каждый ответ)
let РЕЖИМ = '';
function запомнитьРежим(d) {
  if (!d || !d.mode || d.mode === РЕЖИМ) return;
  РЕЖИМ = d.mode;
  записать({ brainState: { mode: d.mode, budget: d.budget || null, at: Date.now() } });
}

// ответы мозга с кодом вместо текста — понятным текстом; свой текст операции («Геокодер не ответил…») не трогаем
function текстОшибки(d, status) {
  const к = String((d && (d.code || d.error)) || status || '');
  if (/^(429|busy)$/.test(к)) return 'мозг занят — повторите через минуту';
  if (/^(502|503|504|upstream)$/.test(к)) return 'ИИ или карты не ответили мозгу — повторите';
  if (/^(400|bad)$/.test(к)) return 'мозг не понял запрос — обновите расширение';
  return 'мозг: ' + (к ? 'ошибка ' + к : 'нет ответа');
}

const НЕДОСТУПЕН = 'мозг недоступен — повторите через минуту';
/* 2.1.7: АВАРИЙНЫЙ РЕЖИМ. Мозг недоступен (11.10: авария Yandex Cloud — функции отвечали «503 Service Unavailable» через 16 с,
   и каждое действие панели ждало по 16 с). Каждый такой ответ (нет связи, шлюз 502–504) помечен «недоступен»: экран разбирает
   переписку правилами и показывает полоску «аварийный режим». Две неудачи подряд — и минуту запросы к мозгу сразу получают
   «сервер недоступен» (code 'down') без ожидания; раз в минуту один запрос идёт по-настоящему. Мозг ответил — всё как обычно.
   Без мозга работают форма (разбор правилами), CRM и заявка; в Telegram — тексты вручную (кнопка «Скопировать») */
const ЛЕЖИТ = { до: 0, подряд: 0 };
const ЛЕЖИТ_МС = 60000;
const ЛЕЖИТ_ТЕКСТ = 'сервер недоступен (сбой Yandex Cloud) — аварийный режим';
function мозгЛежит(r) {
  ЛЕЖИТ.подряд++; ЛЕЖИТ.былЛежит = true;
  записать({ brainDown: { at: Date.now() } }).catch(() => {});
  if (ЛЕЖИТ.подряд < 2) return { ...r, недоступен: true };
  ЛЕЖИТ.до = Date.now() + ЛЕЖИТ_МС;
  return { ...r, недоступен: true, down: true };
}
function мозгЖив() {
  ЛЕЖИТ.подряд = 0;
  if (!ЛЕЖИТ.до && !ЛЕЖИТ.былЛежит) return;
  ЛЕЖИТ.до = 0; ЛЕЖИТ.былЛежит = false;
  стереть('brainDown').catch(() => {});
}
/* Повтор — один раз через 1,5 с и только для ЧТЕНИЯ (разбор, адрес, регламент, территория, выбор, статус, чтение Telegram и общей
   памяти) и только при обрыве связи или странице шлюза 502/503/504 (не JSON — до мозга запрос не дошёл), если с начала прошло
   меньше 10 с. Запись (отправка в Telegram, ссылки, названия) не повторяется никогда: второе сообщение хуже ошибки */
const ЧТЕНИЕ = new Set(['extract', 'address', 'checklist', 'territory', 'pick', 'status', 'links_get', 'names_get']);
const ЧТЕНИЕ_TG = new Set(['chats', 'recent', 'replies', 'topics', 'status']);
const повторМожно = (op, args) => ЧТЕНИЕ.has(op) || (op === 'tg' && ЧТЕНИЕ_TG.has(String((args && args.action) || '')));
async function мозг(op, args, o) {
  const t0 = Date.now();
  const [r, сбой] = await мозгРаз(op, args, o);
  if (!сбой || !повторМожно(op, args) || Date.now() - t0 >= 10000) return r;
  await new Promise((res) => setTimeout(res, 1500));
  return (await мозгРаз(op, args, { ...(o || {}), повтор: true }))[0];   // повтор — часть того же запроса: мимо аварийного режима
}

/* Один запрос к мозгу: POST {op, args, v, dev} с личным токеном. Сам не повторяет (повтор чтения — в мозг()).
   Ответ — как у прежней функции фона + mode/budget; ошибка — {ok:false, error, code}, исключений нет.
   Возвращает [ответ, сбой связи — можно повторить чтение]. o.token — проверка нового токена из настроек (ещё не сохранён) */
async function мозгРаз(op, args, o) {
  o = o || {};
  const url = String(CONFIG.brainUrl || '').trim();
  if (!/^https:\/\/\S+$/.test(url)) return [{ ok: false, code: 'config', error: 'в расширении не задан адрес мозга (config.js) — нужна сборка от ведущего' }];
  const tok = o.token !== undefined ? String(o.token || '').trim() : await токен();
  if (!tok) return [нуженТокен()];
  // сервер недоступен — минуту не ждём его по 16 с на каждое действие (статус в настройках проверяет по-настоящему)
  if (Date.now() < ЛЕЖИТ.до && op !== 'status' && o.token === undefined && !o.повтор) return [{ ok: false, code: 'down', down: true, недоступен: true, error: ЛЕЖИТ_ТЕКСТ }];
  const ms = o.timeout || СРОКИ[op] || СРОКИ.иначе;
  const ctl = typeof AbortController !== 'undefined' ? new AbortController() : null;
  let timer = 0, вышло = false;
  // срок — на весь ответ, с телом: заголовки пришли, а тело застряло — тоже не ждём вечно
  const срок = new Promise((_res, rej) => { timer = setTimeout(() => { вышло = true; if (ctl) ctl.abort(); rej(new Error('срок')); }, ms); });
  срок.catch(() => {});
  let r = null, text = '';
  try {
    r = await Promise.race([fetch(url, {
      method: 'POST', cache: 'no-store', credentials: 'omit',
      headers: { 'X-Brain-Auth': tok, 'Content-Type': 'application/json' },   // не Authorization: его забирает себе Yandex Cloud (403)
      body: JSON.stringify({ op, args: args || {}, v: ВЕРСИЯ_API, dev: await устройство() }),
      ...(ctl ? { signal: ctl.signal } : {}),
    }), срок]);
    text = await Promise.race([r.text(), срок]);
  } catch (e) {
    if (вышло || (e && e.name === 'AbortError')) return [{ ok: false, code: 'timeout', error: 'мозг не ответил за ' + Math.round(ms / 1000) + ' с — проверьте интернет и повторите' }];
    return [мозгЛежит({ ok: false, code: 'network', error: НЕДОСТУПЕН }), true];
  } finally { if (typeof clearTimeout === 'function') clearTimeout(timer); }
  let d = null;
  try { d = JSON.parse(text); } catch (_e) { /* не JSON — страница шлюза */ }
  const к = d && String(d.code || '');
  if (r.status === 401 && d && d.ok === false && к === 'token') {
    if (await токен() === tok) await записать({ brainTokenBad: { fingerprint: отпечаток(tok), at: Date.now() } });
    return [нуженТокен('rejected')];
  }
  // страница шлюза вместо ответа мозга (502/503/504 не JSON) — мозг недоступен; чтение можно повторить
  if ((!d || typeof d !== 'object') && /^50[234]$/.test(String(r.status))) return [мозгЛежит({ ok: false, code: r.status, error: НЕДОСТУПЕН }), true];
  // ответ самой платформы, а не мозга: {"errorCode":503,"errorMessage":"Service Unavailable","errorType":"ServerError"} — мозг не запускался
  // (текст ошибки — прежний; без повтора, как раньше: такой ответ приходит через 16 с)
  if (d && typeof d === 'object' && d.ok === undefined && (d.errorCode || d.errorType) && /^50[234]$/.test(String(r.status))) {
    return [мозгЛежит({ ok: false, code: r.status, error: текстОшибки(null, r.status) })];
  }
  мозгЖив();                                                         // любой другой ответ — сервер на связи
  if (!d || typeof d !== 'object' || Array.isArray(d)) return [{ ok: false, code: r.status, error: текстОшибки(null, r.status) }];
  // успех — только 2xx (и 402 «по правилам» с ok:true): JSON шлюза или упавшей функции ({errorMessage}, 502/403) без ok — ошибка, не данные
  const принят = (r.status >= 200 && r.status < 300) || (r.status === 402 && d.ok !== false);
  if (d.ok === false || !принят) {
    if (к === 'token') return [{ ok: false, code: 'upstream_auth', error: 'Сервис операции не принял свой токен. Личный токен расширения сохранён.' }];
    const свой = d.ok === false && d.error && !/^(busy|upstream|bad|token|\d+)$/.test(String(d.error)) ? d.error : '';
    return [{ ...(d.ok === false ? d : {}), ok: false, code: d.code || r.status, error: свой || текстОшибки(d.ok === false ? d : null, r.status) }];
  }
  // мозг принял этот токен (проверка в настройках) — отметка «отозван» снята: 401 мог быть сбоем мозга, а токен показан один раз
  // (новый токен из настроек снимает отметку сразу — настройки тут же его сохраняют; отозванный старый всё равно снова получит 401)
  if (d.ok === true && await токен() === tok && плохойОтпечаток(await прочитать('brainTokenBad')) === отпечаток(tok)) await стереть('brainTokenBad');
  запомнитьРежим(d);
  return [{ ...d, ...(d.ok === true ? { auth_validated: true } : {}) }];
}

/* TELEGRAM — через мозг (он ходит на сервер команды): чаты, отправка, ответы филиала, разделы, последние сообщения */
/* отправка без ясного ответа: срок, обрыв связи, шлюз мозга (502/503/504 не JSON), сервер команды или программа на ПК «не ответили
   вовремя» — задание могло уже уйти в чат. Это «не знаю, ушло ли» (unknown), а не «повторите»: повтор дал бы второе сообщение.
   Ясно «не ушло»: программа не на связи (задание не ставили), ошибка самого Telegram, токен, занят, неверный запрос */
function отправкаНеясна(r) {
  if (!r || r.ok !== false) return false;
  if (r.unknown || r.timeout) return true;
  const к = String(r.code == null ? '' : r.code), e = String(r.error || '');
  if (/^(timeout|network|502|503|504)$/.test(к)) return true;
  return /не ответил[аи]? вовремя|не ответил за|нет связи с сервером команды|сервер команды: (HTTP )?5\d\d|Failed to fetch/i.test(e);
}
function tg(a) {
  if (a.action === 'send') {
    const photos = (a.photos || []).slice(0, 4).filter((x) => x && x.b64 && x.b64.length < 900000);
    const args = { ...a };
    delete args.photos;
    if (photos.length) args.photos = photos;
    return мозг('tg', args, { timeout: СРОКИ.tgSend }).then((r) => (!отправкаНеясна(r) ? r : {
      ...r, ok: false, unknown: true,
      error: 'нет ответа (' + String(r.error || r.code || 'ошибка').replace(/\s*[—-]?\s*(проверьте интернет и )?(повторите( через минуту)?|попробуйте ещё раз)\.?\s*$/i, '').replace(/\s*[—-]\s*$/, '').slice(0, 120)
        + ') — не знаю, ушло ли сообщение: сначала посмотрите чат, потом отправляйте ещё раз',
    }));
  }
  return мозг('tg', a);
}

/* ССЫЛКА ДЛЯ ОТЗЫВА ПО ОБЪЯВЛЕНИЮ: страница продавца на Авито → clck.ru. Запоминаем на аккаунт LeadChat:
   у одного аккаунта одна страница продавца, Авито открываем только первый раз. Авито и clck.ru — из браузера
   (Авито не пускает сервер), общая память команды — через мозг. */
// 2.1.6: ссылка из LeadChat — «avito.ru/…» без www. Авито перенаправляет на www, а расширению разрешён www.avito.ru:
// запрос по ссылке без www не проходил (перенаправление на другой адрес без разрешения) — сразу идём на www
const наWww = (u) => String(u || '').trim().replace(/^https?:\/\/(?:m\.)?avito\.ru\//i, 'https://www.avito.ru/');
/* Продавец — со страницы объявления, открытой во вкладке (как открывает оператор): блок продавца в живой странице,
   иначе разметка целиком (LC_AVITO.sellerFromHtml). Продавец дорисовывается скриптом — проверяем раз в 1–1,5 с, пока не появится.
   Скрытая вкладка: защита Авито («не робот?») — сразу выходим, капчу там никто не пройдёт. Видимая (оператор нажал
   «Открыть объявление»): ждём до 2 минут — оператор подтверждает «не робот», ссылка делается сама, вкладка закрывается */
async function продавецЧерезВкладку(url, o = {}) {
  const tab = await chrome.tabs.create({ url, active: !!o.показать, ...(o.откуда ? { openerTabId: o.откуда } : {}) });
  const t0 = Date.now(), до = t0 + (o.показать ? 120000 : 25000);
  let загружена = 0, html = '';
  try {
    for (let i = 0; Date.now() < до; i++) {
      await new Promise((r) => setTimeout(r, i ? 1500 : 800));
      let x;
      try {
        const [r] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: () => {
          const re = /\/(?:brands\/[A-Za-z0-9_\-]{2,64}|user\/[0-9a-f]{16,64}\/profile)(?=[?#\/]|$)/i;
          const a = [...document.querySelectorAll('[data-marker="seller-link/link"][href], [data-marker^="seller-info"] a[href], [data-marker*="seller"] a[href], [data-marker*="seller"][href]')]
            .find((e) => re.test(e.getAttribute('href') || ''));
          const готова = document.readyState === 'complete';
          return { href: a ? a.getAttribute('href') : '', готова, html: a || !готова ? document.title : document.documentElement.outerHTML };
        } });
        x = r && r.result;
      } catch (e) {
        if (/no tab with id|tab.*(closed|removed)/i.test(String((e && e.message) || e))) return { закрыта: true };   // оператор закрыл вкладку сам
        continue;                                                      // страница ещё грузится или перешла (капча → объявление)
      }
      if (typeof x === 'string') x = { html: x, готова: true };
      if (!x) continue;
      html = x.html || '';
      const profile = (x.href && LC_AVITO.чистый(x.href)) || (x.готова ? LC_AVITO.sellerFromHtml(html) : '');
      if (profile) return { profile };
      if (LC_AVITO.заблокировано(html, 200)) { if (!o.показать) return { blocked: true }; continue; }
      if (x.готова && !загружена) загружена = Date.now();
      if (загружена && Date.now() - загружена > (o.показать ? 15000 : 6000)) break;   // загрузилась, а продавца нет
    }
  } finally {
    chrome.tabs.remove(tab.id).catch(() => {});
  }
  return { blocked: LC_AVITO.заблокировано(html, 200) };
}
const БЛОК_АВИТО = 'Авито не пустил проверку без вас (защита от роботов) — нажмите «Открыть объявление»: если спросит «не робот?», подтвердите, ссылка сделается сама';
async function запомнитьСсылку(a, key, cache, rec) {
  if (key) { cache[key] = rec; await chrome.storage.local.set({ reviewLinks: cache }); }
  if (a.accountId) мозг('links_put', { account: a.accountId, short: rec.short, profile: rec.profile, origin: a.origin || '', dir: a.dir || '' }).catch(() => {});
}
async function сократить(profile) {
  try { return LC_AVITO.короткая(await (await fetch(LC_AVITO.clckUrl(profile))).text()); } catch (_e) { return ''; }
}
async function reviewLink(a) {
  const key = a.accountId || a.itemUrl;
  const cache = (await chrome.storage.local.get('reviewLinks')).reviewLinks || {};
  // 2.1.6: оператор вставил ссылку сам — короткую clck.ru, на продавца или на объявление
  const ручная = String(a.ручная || '').trim();
  if (ручная) {
    if (LC_AVITO.короткая(ручная)) { const rec = { short: LC_AVITO.короткая(ручная), profile: '', at: Date.now() }; await запомнитьСсылку(a, key, cache, rec); return { ok: true, ...rec, how: 'вставлена вручную' }; }
    const профиль = LC_AVITO.чистый(ручная);
    if (профиль) {
      const short = await сократить(профиль);
      if (!short) return { ok: false, error: 'clck.ru не сократил ссылку', profile: профиль };
      const rec = { short, profile: профиль, at: Date.now() }; await запомнитьСсылку(a, key, cache, rec);
      return { ok: true, ...rec, how: 'страница продавца вставлена вручную' };
    }
    if (!LC_AVITO.объявление(ручная)) return { ok: false, error: 'это не ссылка Авито на продавца или объявление (нужна avito.ru/brands/… или avito.ru/user/…/profile)' };
    a = { ...a, itemUrl: ручная, fresh: true };
  }
  if (key && cache[key] && cache[key].short && !a.fresh) return { ok: true, ...cache[key], how: 'запомнено для этого аккаунта' };
  // общая память команды: ссылку для этого аккаунта мог уже сделать другой оператор (мозг отдаёт запись сервера команды)
  if (a.accountId && !a.fresh) {
    const r = await мозг('links_get', { account: a.accountId });
    const t = r && r.ok !== false ? (r.short ? r : r.link || r.data || null) : null;
    if (t && t.short && LC_AVITO.короткая(t.short)) {
      cache[key] = { short: t.short, profile: t.profile, at: Date.now() };
      await chrome.storage.local.set({ reviewLinks: cache });
      return { ok: true, ...cache[key], how: 'из общей памяти команды' };
    }
  }
  if (!LC_AVITO.объявление(a.itemUrl)) return { ok: false, error: 'у диалога нет ссылки на объявление Авито' };
  const item = наWww(a.itemUrl);
  let profile = '', how = '';
  if (!a.показать) {
    try {
      const r = await fetch(item, { credentials: 'include' });
      const html = await r.text();
      if (r.ok && !LC_AVITO.заблокировано(html, r.status)) { profile = LC_AVITO.sellerFromHtml(html); how = 'со страницы объявления'; }
    } catch (_e) { /* ниже — через вкладку */ }
  }
  if (!profile) {
    let v;
    try { v = await продавецЧерезВкладку(item, { показать: !!a.показать, откуда: a.откуда }); }
    catch (e) { return { ok: false, error: 'не открылось объявление: ' + (e.message || e) }; }
    if (!v.profile) return v.закрыта ? { ok: false, error: 'вкладку с объявлением закрыли раньше, чем нашёлся продавец — нажмите «Открыть объявление» ещё раз или вставьте ссылку' }
      : v.blocked ? { ok: false, blocked: true, error: БЛОК_АВИТО }
      : { ok: false, error: 'на странице объявления не нашлась ссылка на продавца — вставьте её вручную (страница продавца на Авито)' };
    profile = v.profile; how = a.показать ? 'с открытого объявления' : 'через вкладку с объявлением';
  }
  const short = await сократить(profile);
  if (!short) return { ok: false, error: 'clck.ru не сократил ссылку', profile };
  const rec = { short, profile, at: Date.now() };
  await запомнитьСсылку(a, key, cache, rec);
  return { ok: true, ...rec, how };
}

/* offscreen-страница с разбором формы CRM: одна на всё расширение */
let creating = null;
async function ensureOffscreen() {
  if (typeof chrome.offscreen.hasDocument === 'function') {
    if (await chrome.offscreen.hasDocument()) return;
  } else {
    // getContexts поддерживается объявленным минимумом Chrome120.
    // hasDocument появился позднее; отсутствие метода не означает сбой CRM.
    const url = chrome.runtime.getURL('offscreen.html');
    const contexts = await chrome.runtime.getContexts({ contextTypes: ['OFFSCREEN_DOCUMENT'], documentUrls: [url] });
    if (!Array.isArray(contexts)) throw Error('Chrome не подтвердил состояние фоновой страницы CRM');
    if (contexts.some(c => c.contextType === 'OFFSCREEN_DOCUMENT' && c.documentUrl === url)) return;
  }
  if (!creating) {
    creating = chrome.offscreen.createDocument({
      url: 'offscreen.html', reasons: ['DOM_PARSER'],
      justification: 'Разбор HTML-формы создания заявки в CRM лид-центра',
    }).finally(() => { creating = null; });
  }
  await creating;
}

// Offscreen поддерживает только runtime API. Неизвестную отправку сохраняет фон:
// перезапуск offscreen/браузера не даёт повторно отправить ту же форму по номеру.
const СОЗДАНИЯ_ИДУТ = new Set();
async function созданиеСЖурналом(args, send) {
  const phone = String(args?.lead?.phone || '').replace(/\D/g, '').slice(-10);
  if (phone.length !== 10) return { ok: false, refused: true, error: 'Нет телефона клиента — заявка не отправлена' };
  const key = 'crm-create-pending-v1:' + phone;
  const blocked = () => ({ ok: false, unknown: true, error: 'Предыдущая отправка заявки по этому номеру ещё не подтверждена. Проверьте CRM; повторная отправка остановлена.' });
  if (СОЗДАНИЯ_ИДУТ.has(key)) return blocked();
  СОЗДАНИЯ_ИДУТ.add(key);
  let dispatched = false;
  try {
    if ((await chrome.storage.local.get(key))[key]) return blocked();
    const record = { version: 1, dir: args.dir, at: Date.now(), state: 'pending' };
    await chrome.storage.local.set({ [key]: record });
    const stored = (await chrome.storage.local.get(key))[key];
    if (!stored || stored.version !== 1 || stored.at !== record.at || stored.dir !== record.dir)
      throw Error('Не удалось подтвердить сохранение журнала CRM');
    dispatched = true;
    const result = await send();
    // Только доказанное отсутствие POST либо подтверждённый номер снимают запись.
    // Ошибка порта, таймаут и старый ответ без метки её не снимают.
    const known = result && (result.crm_create_dispatched === false || result.crm_create_rejected === true ||
      (result.ok === true && /^\d{1,12}$/.test(String(result.id || '')) && Number(result.id) > 0));
    if (known) {
      try { await chrome.storage.local.remove(key); }
      catch (_e) {
        return { ...result, warnings: [...(result.warnings || []), 'Журнал повторной отправки сохранён: перед следующим созданием проверьте CRM.'] };
      }
      return result;
    }
    return result ? { ...result, unknown: true } : blocked();
  } catch (_e) {
    return dispatched ? blocked() : { ok: false, refused: true,
      error: 'Журнал создания CRM недоступен — форма не отправлена. Проверьте доступ к памяти расширения.' };
  } finally { СОЗДАНИЯ_ИДУТ.delete(key); }
}

async function crm(op, args) {
  if (op === 'create' && !args?.nativeOffice) {
    const a = args || {};
    const r = await мозг('advertiser', { final: true, lead: a.lead || {}, ctx: a.advertiserCtx || {} });
    if (!r || !r.ok || r.rule !== 'jivo-2026-10-15-v1' || !r.lead)
      return { ok: false, refused: true, code: r && r.code || 'advertiser_unavailable', error: r && r.error || 'Сервер не проверил имя / аккаунт объявления — заявку не отправляю. Повторите после восстановления связи с мозгом.' };
    args = { ...a, lead: r.lead };
  }
  try { await ensureOffscreen(); }
  catch (error) {
    if (op !== 'create') throw error;
    return { ok: false, refused: true, crm_create_dispatched: false,
      error: 'Не удалось открыть фоновую страницу CRM. Форма заявки не отправлена.' };
  }
  const send = () => chrome.runtime.sendMessage({ target: 'lcz-offscreen', op, args });
  return op === 'create' ? созданиеСЖурналом(args, send) : send();
}

/* ВЫБОР ИИ — на 30 мин: подготовка той же заявки повторяется (проверка готовности, форма, смена города туда и обратно), а вход тот же —
   второй раз ИИ не спрашиваем. Ключ — отпечаток ВСЕГО, что уходит мозгу (вид, база, список CRM с номерами и названиями, подсказки, суть,
   предметы, слова клиента, вид работ): другое слово — другой ключ. Помним только годный ответ (номер из списка CRM); ошибку, «не выбрал»
   и чужой номер — нет. Память — chrome.storage.session (живёт, пока открыт браузер, переживает засыпание фона), без неё — в памяти фона */
const ВЫБОР_МС = 30 * 60e3;
const ВЫБОР_ПАМЯТЬ = new Map();          // память фона: быстрее session и запасная, если её нет
const ВЫБОР_ИДЁТ = new Map();            // вопросы, ответ на которые ещё идёт: два одинаковых разом — один запрос к мозгу
const сессия = () => (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.session) || null;
async function отпечатокВыбора(args) {
  const s = JSON.stringify(args);
  try {
    const h = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s));
    return 'pick:' + Array.from(new Uint8Array(h), (x) => x.toString(16).padStart(2, '0')).join('');
  } catch (_e) {
    // нет WebCrypto — два независимых 32-битных хеша и длина: совпадение ключей у разных входов практически невозможно
    let h1 = 0x811c9dc5, h2 = 0x9747b28c;
    for (let i = 0; i < s.length; i++) { const c = s.charCodeAt(i); h1 = Math.imul(h1 ^ c, 16777619); h2 = Math.imul(h2 ^ c, 2246822519) ^ (h2 >>> 13); }
    return 'pick:' + (h1 >>> 0).toString(16) + (h2 >>> 0).toString(16) + ':' + s.length;
  }
}
async function выборИзПамяти(k) {
  let x = ВЫБОР_ПАМЯТЬ.get(k);
  const ss = сессия();
  if (!x && ss) { try { x = (await ss.get(k))[k]; } catch (_e) { x = undefined; } }
  if (x && Date.now() - x.at < ВЫБОР_МС) return x;
  if (x) { ВЫБОР_ПАМЯТЬ.delete(k); if (ss) { try { await ss.remove(k); } catch (_e) { /* нечего стирать */ } } }
  return null;
}
async function выборВПамять(k, r) {
  const x = { id: r.id, why: r.why || '', at: Date.now() };
  ВЫБОР_ПАМЯТЬ.set(k, x);
  for (const [kk, v] of ВЫБОР_ПАМЯТЬ) if (Date.now() - v.at >= ВЫБОР_МС) ВЫБОР_ПАМЯТЬ.delete(kk);
  const ss = сессия();
  if (ss) { try { await ss.set({ [k]: x }); } catch (_e) { /* память сессии недоступна — хватит памяти фона */ } }
}
/* Подготовка заявки + выбор вида работ и вида услуг по регламенту (ИИ выбирает только из списка CRM).
   Выбор оператора в панели важнее: вид работ, выбранный вручную, ИИ не меняет.
   Списки CRM готовит браузер (рабочая сессия), выбирает мозг; ему уходят только суть, предметы и слова клиента */
async function pickByRules(level, dir, list, hints, a, applText) {
  const args = { kind: level, dir, list, hints: hints || {}, a: { problem: a.problem || '', topics: a.topics || [], client: a.client || '' }, applText: applText || '' };
  const k = await отпечатокВыбора(args);
  const был = await выборИзПамяти(k);
  let r = был;
  if (!r) {
    if (!ВЫБОР_ИДЁТ.has(k)) ВЫБОР_ИДЁТ.set(k, мозг('pick', args).finally(() => ВЫБОР_ИДЁТ.delete(k)));
    r = await ВЫБОР_ИДЁТ.get(k);
  }
  if (!r || r.ok === false) throw new Error((r && r.error) || 'мозг не ответил');
  // номер — только из списка CRM, даже если мозг ошибся
  const id = String(r.id ?? '').trim(), есть = (list || []).find((x) => x.id === id);
  if (есть && !был) await выборВПамять(k, { id, why: String(r.why || '') });
  return есть ? { id, why: String(r.why || '').slice(0, 120) } : { id: '', why: '' };
}
async function prepareSmart(a) {
  const r = await crm('prepare', a);
  if (!r || !r.ok || !r.cityId) return r;
  if (!a.problem && !(a.topics || []).length) return r;
  // строка «Входящих» в economy / rules: вид работ — подсказкой CRM, без выбора ИИ (выберет форма при открытии)
  if (a.безИИ) { delete r.hints; return r; }
  const hints = r.hints || { appl: {}, sub: {} };
  const суть = { problem: a.problem || '', topics: a.topics || [], device: a.device || '' };
  const ошибкиИИ = [];
  // 2.0.7: вид работ решили правила регламента (worktype.js) — ИИ не спрашиваем (быстрее, дешевле, одинаково каждый раз)
  if (!a.applId && !r.applRule && (r.appl || []).length > 1) {
    try {
      const pk = await pickByRules('appl', a.dir, r.appl, hints.appl, a);
      if (pk.id) {
        if (pk.id !== r.applId) {
          const s = await crm('sub', { dir: a.dir, cityId: r.cityId, applId: pk.id, appl: r.appl, hasPartner: r.hasPartner });
          r.applId = pk.id;
          r.sub = (s && s.list) || [];
          const applText = ((r.appl || []).find((x) => x.id === r.applId) || {}).text || '';
          const пу = typeof LC_WORK !== 'undefined' ? LC_WORK.видУслуг(a.dir, r.sub, суть, applText, r.appl) : { id: '' };
          r.subId = пу.id || (r.sub[0] ? r.sub[0].id : '');
          r.subRule = !!пу.уверенно;
          r.subHow = пу.уверенно ? пу.how : r.sub.length > 1 ? 'первый из списка — проверьте' : '';
          r.subDiag = r.sub.length ? '' : 'для этого вида работ CRM не дала список видов услуг';
        }
        r.applHow = 'по регламенту' + (pk.why ? ': ' + pk.why : '');
      }
    } catch (e) { ошибкиИИ.push(String(e.message || e).slice(0, 60)); }
  }
  if ((r.sub || []).length > 1 && !a.subId && !r.subRule) {
    try {
      const applText = ((r.appl || []).find((x) => x.id === r.applId) || {}).text || '';
      const ps = await pickByRules('sub', a.dir, r.sub, hints.sub, a, applText);
      if (ps.id) { r.subId = ps.id; r.subHow = 'по регламенту' + (ps.why ? ': ' + ps.why : ''); }
    } catch (e) { ошибкиИИ.push('вид услуг — ' + String(e.message || e).slice(0, 60)); }
  }
  if (ошибкиИИ.length) r.applHow = (r.applHow || '') + ' · ИИ не выбрал по регламенту: ' + ошибкиИИ.join('; ');
  delete r.hints;
  return r;
}

/* 1.20: вкладки CRM — открыта ли заявка во вкладке CRM (бегунок actions-ui.js и подсказки watch-act.js: «обновите ту вкладку (F5),
   иначе её «Сохранить» вернёт старое»). Отдельный блок со своим слушателем: остальной фон его не касается и он — остального.
   Стоит ПЕРЕД основным слушателем: заглушки chrome в старых проверках фона (bg_test и др.) помнят только последний слушатель.
   Хватает host_permissions баз (без права «tabs»). Наружу — только число вкладок: адрес и заголовок (там бывает имя клиента) не отдаём */
(() => {
  const БАЗЫ = { bt: 'https://bt-lead-centre.ru', kp: 'https://kp-lead-centre.ru', mnc: 'https://mnc-lead-centre.ru' };
  const ПУТЬ = '/admin/domain/customer-request/update';
  async function вкладкиЗаявки(a) {
    const base = БАЗЫ[a.dir], id = String(a.id || '');
    if (!base || !/^\d{1,12}$/.test(id)) return { ok: false, error: 'нет базы или номера заявки' };
    if (!chrome.tabs || !chrome.tabs.query) return { ok: false, error: 'вкладки недоступны' };
    const tabs = await chrome.tabs.query({ url: base + ПУТЬ + '*' });
    // шаблон адреса ловит и «id=12345» для «id=123» — сверяем номер точно
    const наши = (tabs || []).filter((t) => {
      try { const u = new URL(t.url || t.pendingUrl || ''); return u.origin === base && u.pathname === ПУТЬ && u.searchParams.get('id') === id; } catch (_e) { return false; }
    });
    return { ok: true, open: наши.length, active: наши.some((t) => !!t.active) };
  }
  chrome.runtime.onMessage.addListener((msg, _sender, respond) => {
    if (!msg || msg.kind !== 'lcz-act-tabs' || msg.target === 'lcz-offscreen') return undefined;
    вкладкиЗаявки(msg.args || {}).then(respond).catch((e) => respond({ ok: false, error: String((e && e.message) || e) }));
    return true;
  });
})();
/* /1.20: вкладки CRM */

/* Сообщения экрана → дела фона. Разбор, адрес, регламент, «дописал», территория, местные названия и Telegram —
   операции мозга 1:1 (формат запроса и ответа прежний); CRM и Авито — здесь, в браузере */
const ДЕЛА = {
  'lcz-extract': (m) => мозг('extract', m.ctx || {}),
  'lcz-address': (m) => мозг('address', m.ctx || {}),
  'lcz-checklist': (m) => мозг('checklist', m.args || {}),
  'lcz-addition': (m) => мозг('addition', m.args || {}),
  'lcz-territory': (m) => мозг('territory', m.args || {}),
  'lcz-name-learn': (m) => мозг('name_learn', m.args || {}),
  'lcz-tg': (m) => tg(m.args || {}),
  'lcz-reviewlink': (m, от) => reviewLink({ ...(m.args || {}), откуда: от && от.tab ? от.tab.id : undefined }),   // видимая вкладка Авито — закрылась, вернулись в LeadChat
  'lcz-advertiser': (m) => мозг('advertiser', m.args || {}),
  'lcz-crm': (m,from) => {
    const args={...(m.args||{})};
    if(m.op==='create'&&args.nativeOffice)return (async()=>{
      if(!nativeOfficeHost)return {ok:false,refused:true,crm_create_dispatched:false,error:'Серверный исполнитель CRM не загружен'};
      const admission=await nativeOfficeHost.authorize(from,args);
      if(admission?.ok!==true)return {ok:false,refused:true,crm_create_dispatched:false,error:admission?.error||'Серверный исполнитель CRM не подтверждён'};
      const result=await crm(m.op,args);
      await nativeOfficeHost.finish(from,args.nativeOffice,result);
      return result;
    })();
    if(m.op==='create'&&args.personalWorkflow){if(!Number.isInteger(from?.tab?.id))throw Error('Нет вкладки личного помощника');args.workflow_guard={...(args.workflow_guard||{}),tab_id:from.tab.id}}
    return m.op==='prepare'?prepareSmart(args):crm(m.op,args);
  },
};

// ключ YandexGPT, вписанный в настройках 1.x, больше не нужен — стираем его с компьютера при установке и обновлении.
// Первая установка без токена — сразу настройки: без токена расширение ничего не делает, а где его вставить — неочевидно
if (chrome.runtime.onInstalled) chrome.runtime.onInstalled.addListener((d) => {
  стереть('settings');
  if (d && d.reason === 'install') токен().then((t) => { if (!t) chrome.runtime.openOptionsPage(); }).catch(() => {});
});
// щелчок по значку расширения на панели — настройки (там и «Состояние»: мозг, Telegram, вход в CRM)
if (chrome.action && chrome.action.onClicked) chrome.action.onClicked.addListener(() => { chrome.runtime.openOptionsPage(); });

chrome.runtime.onMessage.addListener((msg, _sender, respond) => {
  if (!msg || msg.target === 'lcz-offscreen') return;
  const run = (p) => { p.then(respond).catch((e) => respond({ ok: false, code: e.code || 'extension', error: String(e.message || e) })); return true; };
  if (msg.kind === 'lcz-options') { chrome.runtime.openOptionsPage(); return; }
  if (msg.kind === 'lcz-personal-tab') return run(доступ().then(yes=>yes?personalTabs.action(msg.action,_sender):отказДоступа()));
  if (msg.kind === 'lcz-personal-surface') return run(personalTabs.surface(_sender));
  if (msg.kind === 'lcz-personal-occupied') return run(personalTabs.occupied(_sender));
  if (msg.kind === 'lcz-personal-link') return run(personalLink.action(msg.action,_sender,msg.connection_id));
  if (msg.kind === 'lcz-personal-guard') return run(personalGuard(_sender,msg.guard));
  if (msg.kind === 'lcz-native-office-phase') return run(nativeOfficeHost?nativeOfficeHost.phase(_sender,msg):Promise.resolve({ok:false}));
  if (msg.kind === 'lcz-native-office-host') {
    if(!nativeOfficeHost)return run(Promise.resolve({ok:false}));
    const handlers={
      claim:()=>nativeOfficeHost.claim(_sender,msg.scope),
      bind:()=>nativeOfficeHost.bind(_sender,msg.scope,msg.fields),
      recover:()=>nativeOfficeHost.recover(_sender,msg.scope),
    };
    if(Object.hasOwn(handlers,msg.action))return run(handlers[msg.action]());
    return run(Promise.resolve({ok:false,error:'Неизвестная команда серверного исполнителя CRM'}));
  }
  // настройки: «Проверить» — статус мозга с введённым токеном (до сохранения), без него — с сохранённым
  if (msg.kind === 'lcz-brain' && msg.op === 'status') return run(мозг('status', {}, msg.token !== undefined ? { token: msg.token } : {}));
  if (msg.kind === 'lcz-assistant') {
    const url = String((_sender && _sender.url) || '');
    const allowed = (chrome.runtime.getManifest().content_scripts || []).flatMap((s) => s.matches || []).some((m) => url.startsWith(m.replace(/\*$/, '')));
    if (!allowed) { respond({ ok: false, code: 'origin', error: 'Помощник доступен только в LeadChat' }); return; }
    return run(доступ().then(async (можно) => {
      if (!можно) return отказДоступа();
      const args = { ...(msg.args || {}) };
      args.client_version = chrome.runtime.getManifest().version;
      // A page cannot pretend to be another tab or a server worker.
      if (String(args.action || '').startsWith('personal_') || args.action === 'screen' || args.identity_proof) {
        if (!_sender.tab || !Number.isInteger(_sender.tab.id)) return {ok:false,code:'personal_tab',auto_enabled:false,error:'Откройте помощника во вкладке LeadChat'};
        args.browser_session = await устройство() + ':tab:' + _sender.tab.id;
      }
      return мозг('assistant', args);
    }));
  }
  const дело = ДЕЛА[msg.kind];
  if (!дело) return;
  // без личного токена (или с отозванным) расширение ничего не делает: ни ИИ, ни CRM, ни Telegram, ни Авито
  return run(доступ().then((можно) => (можно ? дело(msg, _sender) : отказДоступа())));
});
