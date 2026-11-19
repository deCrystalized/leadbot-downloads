/* LeadChat → Заявка: кнопка «Заявка» в карточке «Клиент» LeadChat и панель с проверенными полями.
   Данные берутся из API самого LeadChat (как его же экран): диалог, сообщения, карточка
   клиента с адресом по карте. ИИ разбирает только то, чего в карточке нет: время, суть,
   озвученные цены. Создание — в CRM лид-центра рабочей сессией оператора.
   v1.3.0: интерфейс по макету Claude Design; цвета — переменные темы LeadChat (--lc-*),
   поэтому панель сама светлая/тёмная и в цвете пресета оператора; при LeadChat Style — в его акценте
   (--lc-theme-accent + контрастный --lc-theme-accent-contrast, парой). */
(async () => {
  if (window.__lczLoaded) return;
  window.__lczLoaded = true;
  const заявленаЛичнаяВкладка=new URLSearchParams(location.search).get('lcz-assistant')==='1';
  const личнаяВкладка=await chrome.runtime.sendMessage({kind:'lcz-personal-surface'}).then(r=>r?.dedicated===true||заявленаЛичнаяВкладка).catch(()=>заявленаЛичнаяВкладка);
  let assistantSelectedId='';

  const DIRS = [['mnc', 'МНЧ'], ['kp', 'КП'], ['bt', 'БТ']];
  /* Расширение обновили или перезагрузили, а вкладка LeadChat старая — связи с ним больше нет.
     Ничего не ломаем: просим обновить страницу (F5). */
  const УСТАРЕЛО = 'Расширение обновилось — обновите страницу LeadChat (F5)';
  const alive = () => { try { return !!(chrome.runtime && chrome.runtime.id); } catch (_e) { return false; } };
  // только наш текст про F5: у LeadChat свои «…обновите страницу» (404, 409, 422) — это не «расширение обновилось»
  const устарело = (e) => !alive() || /context invalidated|Extension context|УСТАРЕЛО|обновите страницу LeadChat/i.test(String((e && e.message) || e || ''));
  const send = (msg) => new Promise((res) => {
    if (!alive()) return res({ ok: false, error: УСТАРЕЛО });
    try {
      chrome.runtime.sendMessage(msg, (r) => res(мозгОтвет(r || { ok: false, error: (alive() ? chrome.runtime.lastError?.message : УСТАРЕЛО) || 'нет ответа от расширения' })));   /* 2.0: мозг */
    } catch (e) { res({ ok: false, error: устарело(e) ? УСТАРЕЛО : String(e.message || e) }); }
  });
  /* 2.0: мозг — точка 1 «Нужен токен». Фон без личного токена (или с отозванным) ничего не делает и отвечает code:'token':
     одно уведомление с кнопкой «Открыть настройки» — панель, «Готовые» и карточка показывают ту же ошибку в своих строках.
     Первый удачный ответ (токен снова принят) уведомление убирает. Ответ идёт дальше как есть */
  const МОЗГ_ЭКРАН = { токен: null, токенПоказан: false, полоска: null, показано: '', режим: '', режимAt: 0, авария: null };
  function мозгОтвет(r) {
    try {
      // режим ИИ из последнего ответа мозга (каждый ответ мозга несёт mode): «Готовые» в economy/rules идут без ИИ
      if (r && typeof r.mode === 'string' && r.mode) { МОЗГ_ЭКРАН.режим = r.mode; МОЗГ_ЭКРАН.режимAt = Date.now(); }
      if (r && r.code === 'token') нуженТокен(r);
      else if (r && r.ok === true && r.auth_validated === true) {
        if (МОЗГ_ЭКРАН.токен) МОЗГ_ЭКРАН.токен.remove();
        МОЗГ_ЭКРАН.токен = null; МОЗГ_ЭКРАН.токенПоказан = false;
      }
      if (r && (r.mode === 'economy' || r.mode === 'rules')) полоскаРежима(r.mode, r.budget).catch(() => {});
      if (r && (r.down || r.недоступен)) полоскаАварии();
      else if (r && r.ok !== false && МОЗГ_ЭКРАН.авария) снятьАварию();
    } catch (_e) { /* экран ещё не готов — ответ важнее */ }
    return r;
  }
  /* 2.1.7: АВАРИЙНЫЙ РЕЖИМ — сервер (мозг) недоступен (11.10: авария Yandex Cloud). Строка над уведомлениями: что работает,
     что делать руками. Убирается сама, когда фон снова достучался до сервера (brainDown стёрт) */
  function полоскаАварии() {
    if (МОЗГ_ЭКРАН.авария && МОЗГ_ЭКРАН.авария.isConnected) return;
    const el = h('div', { class: 'lcz-mode tst-low bad', role: 'status', 'data-mode': 'down' },
      h('span', { class: 'lcz-mode-t' }, 'Сервер недоступен (сбой Yandex Cloud) — аварийный режим: переписка разбирается правилами (проверяйте поля), '
        + 'заявка в CRM создаётся; в Telegram пишите вручную — тексты с кнопкой «Скопировать». Сервер заработает — всё вернётся само.'),
      h('button', { 'aria-label': 'Закрыть', title: 'Скрыть', onclick: () => el.remove() }, '×'));
    МОЗГ_ЭКРАН.авария = el;
    СЛОТ_РЕЖИМА.prepend(el);
  }
  function снятьАварию() {
    chrome.storage.local.get('brainDown').then((x) => {
      if (x && x.brainDown) return;
      if (МОЗГ_ЭКРАН.авария) { МОЗГ_ЭКРАН.авария.remove(); МОЗГ_ЭКРАН.авария = null; }
    }).catch(() => {});
  }
  /* режим ИИ — свежее из двух: ответ мозга в этой вкладке или brainState фона (фон пишет его при смене режима, для всех вкладок) */
  async function режимМозга() {
    let фон = null;
    try { фон = (await chrome.storage.local.get('brainState')).brainState; } catch (_e) { /* память недоступна — свой ответ */ }
    return фон && фон.mode && (Number(фон.at) || 0) > МОЗГ_ЭКРАН.режимAt ? String(фон.mode) : МОЗГ_ЭКРАН.режим;
  }
  function нуженТокен(r = {}) {
    if (МОЗГ_ЭКРАН.токенПоказан) return;
    МОЗГ_ЭКРАН.токенПоказан = true;
    const rejected = r.token_state === 'rejected';
    МОЗГ_ЭКРАН.токен = тост({ kind: 'warn', позже: false, label: rejected ? 'Проверка токена' : 'Нужен токен',
      title: rejected ? 'Сервер не принял сохранённый токен' : 'Нужен токен: откройте настройки расширения', keep: true,
      lines: [h('div', { class: 'tst-d' }, rejected ? 'Токен остаётся в настройках. Нажмите «Проверить и сохранить», чтобы повторно проверить доступ.' : 'Вставьте личный токен в настройках расширения.')],
      actions: [h('button', { class: 'sm pri', onclick: () => send({ kind: 'lcz-options' }) }, 'Открыть настройки')] });
  }
  /* 2.0: мозг — точка 2: тонкая полоска режима ИИ (economy — к лимиту месяца, rules — лимит исчерпан, ИИ выключен).
     Раз в смену: на каждый режим — один раз в день, во всех вкладках (память расширения); закрывается крестиком */
  const ЛИМИТ_ЗАПАС = 5000;                                          // сервер не сообщил лимит — прежний по договору
  async function полоскаРежима(mode, budget) {
    const ключ = mode + '|' + new Date().toLocaleDateString('sv-SE');
    if (МОЗГ_ЭКРАН.показано === ключ) return;
    МОЗГ_ЭКРАН.показано = ключ;
    try {
      if ((await store.get('brainModeShown', '')) === ключ) return;
      await store.set('brainModeShown', ключ);
    } catch (_e) { /* без памяти — покажем в этой вкладке */ }
    const руб = (x) => Math.round(Number(x) || 0).toLocaleString('ru-RU');
    // 2.1: лимит — тот, что прислал сервер (раньше в тексте стояло зашитое «5000 ₽»)
    const лимит = 'лимит ' + руб(budget && Number(budget.limit) > 0 ? budget.limit : ЛИМИТ_ЗАПАС) + ' ₽';
    const потрачено = budget && budget.spent !== undefined ? ' · потрачено ' + руб(budget.spent) + ' ₽' : '';
    const текст = mode === 'rules' ? 'ИИ выключен до 1-го числа: ' + лимит + потрачено + ' — разбор по правилам, проверяйте поля'
      : 'ИИ в экономном режиме: ' + лимит + потрачено;
    if (МОЗГ_ЭКРАН.полоска) МОЗГ_ЭКРАН.полоска.remove();
    // 2.1: строка-сведения в своём месте над стопкой: полоса слева, цвет — по режиму; закрывается крестиком (до следующей смены)
    const el = h('div', { class: 'lcz-mode tst-low ' + (mode === 'rules' ? 'bad' : 'warn'), role: 'status', 'data-mode': mode },
      h('span', { class: 'lcz-mode-t' }, текст),
      h('button', { 'aria-label': 'Закрыть', title: 'Закрыть до следующей смены', onclick: () => el.remove() }, '×'));
    МОЗГ_ЭКРАН.полоска = el;
    СЛОТ_РЕЖИМА.replaceChildren(...(МОЗГ_ЭКРАН.авария && МОЗГ_ЭКРАН.авария.isConnected ? [МОЗГ_ЭКРАН.авария] : []), el);   // своё место над стопкой
    try { drawReadyTab(); drawReadySoon(); } catch (_e) { /* «Готовые» ещё не готовы */ }
  }
  const convIdNow = () => (location.pathname.match(/\/chats\/([^/?#]+)/) || [])[1] || '';
  const fmtPhone = (p) => (p && p.length === 10 ? '+7 ' + p.slice(0, 3) + '-' + p.slice(3, 6) + '-' + p.slice(6) : '');

  /* ---------- API LeadChat ----------
     Токен — через POST /auth/refresh под тем же замком «lc-auth-refresh», что и сам LeadChat:
     сервер меняет cookie при каждом обновлении, и два обновления разом выкидывают человека
     из всех вкладок. Держим токен до конца срока (expires_in − 60 с).
     БЕЗ ЗАВИСАНИЙ: у каждого запроса срок 15 с (и у ожидания замка тоже) — дальше понятная ошибка, а не вечное «Проверяем…».
     Ошибку LeadChat читаем из его конверта {error:{code,message,details}}: текст — русский текст сервера,
     в полях status / code / details — чтобы «Взять» отличало «уже ваш» (409 mine) от «взял другой».
     nginx при перегрузке отвечает 429 too_many_requests (запрос до LeadChat не дошёл) — ждём 1 с и повторяем один раз. */
  const LC_СРОК = 15000;
  const пауза = (ms) => new Promise((r) => setTimeout(r, ms));
  const ошибкаLC = (text, extra) => Object.assign(new Error(text), { lc: true, status: 0, code: '', details: {} }, extra || {});
  async function fetchСрок(url, init, ms) {
    ms = ms || LC_СРОК;
    const ctl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    let t = 0;
    const срок = new Promise((_, rej) => { t = setTimeout(() => { if (ctl) ctl.abort(); rej(ошибкаLC('LeadChat не ответил за ' + Math.round(ms / 1000) + ' с — проверьте связь и повторите', { code: 'timeout' })); }, ms); });
    try {
      return await Promise.race([fetch(url, ctl ? { ...init, signal: ctl.signal } : init), срок]);
    } catch (e) {
      if (e && e.lc) throw e;
      if (e && e.name === 'AbortError') throw ошибкаLC('LeadChat не ответил за ' + Math.round(ms / 1000) + ' с — проверьте связь и повторите', { code: 'timeout' });
      throw ошибкаLC('Нет связи с LeadChat (' + String((e && e.message) || e).slice(0, 60) + ') — проверьте интернет и повторите', { code: 'network' });
    } finally { clearTimeout(t); }
  }
  // тело ответа — тоже со сроком: заголовки пришли, а тело «застряло» — не ждём вечно
  async function jsonСрок(r) {
    let t = 0;
    try { return await Promise.race([r.json(), new Promise((_, rej) => { t = setTimeout(() => rej(ошибкаLC('LeadChat не дослал ответ за 15 с — повторите', { code: 'timeout' })), LC_СРОК); })]); }
    finally { clearTimeout(t); }
  }
  async function ошибкаОтвета(r, path) {
    let e = null;
    try { const j = await jsonСрок(r); e = j && j.error; } catch (_e) { /* не JSON — страница nginx */ }
    return ошибкаLC((e && e.message) || ('LeadChat: HTTP ' + r.status + ' (' + String(path).split('?')[0] + ')'),
      { status: r.status, code: (e && e.code) || '', details: (e && e.details) || {} });
  }
  // повтор с тем же client_message_id: LeadChat вернул уже записанное (200 + X-Idempotent-Replay), нового не создал
  const повторОтвета = (r) => { try { return !!(r && r.headers && typeof r.headers.get === 'function' && /^true$/i.test(String(r.headers.get('X-Idempotent-Replay') || ''))); } catch (_e) { return false; } };
  /* заметка с этим client_message_id уже есть, но с другим текстом (409 idempotency_mismatch; LeadChat помнит id 24 ч) —
     её уже записали раньше: не ошибка */
  const ужеЗаписано = (e) => !!(e && e.status === 409 && e.code === 'idempotency_mismatch');
  // замок, общий с LeadChat: ждём его не дольше срока — иначе наш запрос «висел» бы вместе с чужим обновлением
  async function подЗамком(name, fn) {
    const ctl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    const t = ctl ? setTimeout(() => ctl.abort(), LC_СРОК) : 0;
    try { return await navigator.locks.request(name, ctl ? { signal: ctl.signal } : {}, () => { clearTimeout(t); return fn(); }); }
    catch (e) { if (e && e.name === 'AbortError') throw ошибкаLC('LeadChat долго обновляет доступ — повторите через минуту', { code: 'timeout' }); throw e; }
    finally { clearTimeout(t); }
  }
  const LC = {
    token: '', until: 0, me: null, обновление: null,
    async tok(force, failed) {
      if (!force && this.token && Date.now() < this.until) return this.token;
      // 401 на старом токене, а его уже обновил соседний запрос — берём новый, второй раз не обновляем
      if (force && failed && this.token && this.token !== failed && Date.now() < this.until) return this.token;
      // несколько запросов разом получили 401 — обновляем доступ один раз на всех
      if (this.обновление) return this.обновление;
      const work = async () => {
        const r = await fetchСрок('/api/v1/auth/refresh', { method: 'POST', credentials: 'include' });
        if (!r.ok) throw ошибкаLC('LeadChat не выдал доступ (HTTP ' + r.status + ') — обновите страницу', { status: r.status });
        return jsonСрок(r);
      };
      const p = this.обновление = (async () => {
        const d = navigator.locks?.request ? await подЗамком('lc-auth-refresh', work) : await work();
        // доступ выдан другому человеку (вышел один — вошёл другой, страница та же): всё «моё» — заново, под него
        const uid = d && d.user && d.user.id ? String(d.user.id) : '';
        if (uid && this.me && this.me.id && uid !== this.me.id) новыйВход();
        this.token = (d && d.access_token) || '';
        this.until = Date.now() + Math.max(60, (Number(d && d.expires_in) || 300) - 60) * 1000;
        if (!this.token) throw ошибкаLC('LeadChat не вернул токен');
        return this.token;
      })();
      try { return await p; } finally { if (this.обновление === p) this.обновление = null; }
    },
    /* полный (postFull) — ответ вместе с кодом и признаком повтора: { data, status, replay }. replay — LeadChat узнал client_message_id
       и вернул записанное раньше (200 + X-Idempotent-Replay: true): нового сообщения нет — «отправлено» было бы неправдой */
    async req(method, path, body, полный) {
      // страница LeadChat на входе (вышли): прежним доступом ничего не читаем и не берём — диалоги ушли бы на вышедшего
      if (наВходе()) { новыйВход(); throw ошибкаLC('Вы вышли из LeadChat — войдите снова', { code: 'logout' }); }
      const go = async (t) => fetchСрок('/api/v1' + path, { method, headers: { Authorization: 'Bearer ' + t, ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
        ...(body !== undefined ? { body: JSON.stringify(body) } : {}) });
      const t0 = await this.tok();
      let r = await go(t0);
      if (r.status === 401) r = await go(await this.tok(true, t0));
      if (r.status === 429) {
        // повторяем, только если запрос не дошёл до LeadChat (отказ nginx) или это чтение; тело то же — client_message_id тот же
        const e0 = await ошибкаОтвета(r, path);
        if (method !== 'GET' && e0.code && e0.code !== 'too_many_requests') throw e0;
        await пауза(1000);
        r = await go(await this.tok());
      }
      if (!r.ok) throw await ошибкаОтвета(r, path);
      const итог = (data) => (полный ? { data, status: r.status, replay: повторОтвета(r) } : data);
      if (r.status === 204) return итог({});
      try { return итог(await jsonСрок(r)); } catch (e) {
        if (method === 'GET') throw e && e.code === 'timeout' ? e : ошибкаLC('LeadChat прислал непонятный ответ (' + String(path).split('?')[0] + ') — повторите', { status: r.status });
        return итог({});                                              // действие выполнено (2xx), тело не нужно
      }
    },
    get(path) { return this.req('GET', path); },
    post(path, body) { return this.req('POST', path, body || {}); },
    postFull(path, body) { return this.req('POST', path, body || {}, true); },
    patch(path, body) { return this.req('PATCH', path, body || {}); },
    put(path, body) { return this.req('PUT', path, body); },
  };
  /* ВЫХОД / ДРУГОЙ ЧЕЛОВЕК в той же вкладке: LeadChat выходит без перезагрузки страницы (/login), а его доступ живёт ещё ~15 мин.
     Доступ, «кто я» и всё, что решали за прежнего человека (проверки, взятые, лимит, «Готовые», «молчит»), — забываем */
  const наВходе = () => /^\/login(\/|$)/.test(location.pathname);
  function новыйВход() {
    LC.token = ''; LC.until = 0; LC.me = null;
    try {
      AUTO.checked.clear(); AUTO.capped = false; AUTO.countKey = ''; AUTO.away = false; AUTO.taken = []; AUTO.skipAcc.clear(); AUTO.err = ''; AUTO.толькоЧтение = false;
      if (assistantPanel) assistantPanel.stop();
      МГН.взяты.clear(); МГН.вернул.clear(); МГН.тост.clear(); МГН.presenceAt = 0; МГН.countKey = '';
      READY.items = []; READY.gone = new Set(); READY.at = 0; READY.note = null;
      МОЛЧИТ.list = []; МОЛЧИТ.shown = ''; if (МОЛЧИТ.el) { МОЛЧИТ.el.remove(); МОЛЧИТ.el = null; }
      drawReadyTab(); тостНовые(null);
    } catch (_e) { /* ещё не запущено — забывать нечего */ }
  }
  // кто я в LeadChat — один раз на вкладку (нагрузка «мои», сторож «молчит», передачи)
  async function моёId() {
    if (LC.me && LC.me.id) return LC.me.id;
    const m = await LC.get('/auth/me');
    LC.me = m && m.id ? { ...m, id: String(m.id), name: m.full_name || '' } : null;
    return LC.me ? LC.me.id : '';
  }
  const новыйId = () => ((typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID() : 'lcz-' + Date.now() + '-' + Math.random().toString(36).slice(2, 10));

  /* Номер заявки — в имя клиента LeadChat (так операторы помечают оформленных: «алан 2603481»).
     Уже стоит этот номер — не трогаем; в конце номер прошлой заявки — меняем на новый. */
  function nameWithId(name, id) {
    const n = String(name || '').trim();
    if (!id) return n;
    if (new RegExp('(^|\\s)' + id + '$').test(n)) return n;
    // LeadChat берёт имя не длиннее 100 знаков (иначе 422 и номер не допишется): длинное имя (профиль Авито) — короче, с «…»; номер — целиком
    const имя = n.replace(/\s\d{6,8}$/, '').replace(/\s+/g, ' ');
    const место = ИМЯ_LC - String(id).length - 1;
    return (имя ? обрезать(имя, место) + ' ' : '') + id;
  }
  /* обрезать до n знаков с «…» на конце. Знаки — как считает LeadChat (Python: символы, а не половинки эмодзи):
     ни лимит не превысим, ни эмодзи пополам не разрежем */
  const ИМЯ_LC = 100, КОММЕНТАРИЙ_LC = 1000;
  function обрезать(text, n) {
    const t = String(text || ''), z = [...t];
    if (z.length <= n) return t;
    return z.slice(0, Math.max(0, n - 1)).join('').trimEnd() + '…';
  }

  /* № ЗАЯВКИ В САМОМ ДИАЛОГЕ LeadChat (12.10, be2f017: crm_request_id / crm_request_at в строке списка и в детали).
     Пишем PUT /conversations/{id}/crm-request {request_id} (право как у ответа клиенту) — после создания заявки и когда диалог
     привязали к заявке (вернули в «Ожидает», действие с № в имени). Тот же № второй раз — не изменение (повтор после обрыва можно).
     В ответе — другие диалоги с этим же номером (same_request_conversation_ids): есть — похоже на дубль, говорим оператору.
     Итог: { ok, id, twins } | { ok: false, error } | null — LeadChat старше (404 / 405, ручки нет): молча пропускаем. Не бросает */
  async function номерВДиалог(conv, n) {
    if (!conv || !n) return null;
    try {
      const r = await LC.put('/conversations/' + encodeURIComponent(conv) + '/crm-request', { request_id: String(n) });
      const twins = (Array.isArray(r && r.same_request_conversation_ids) ? r.same_request_conversation_ids : []).map(String).filter((x) => x && x !== String(conv));
      return { ok: true, id: String((r && r.crm_request_id) || n), twins };
    } catch (e) {
      if (e && (e.status === 404 || e.status === 405)) return null;
      return { ok: false, error: String((e && e.message) || e).slice(0, 160) };
    }
  }
  /* Прочитать: у диалога в LeadChat уже стоит № заявки, а своей записи о ней нет (создали в другом браузере, другой оператор,
     лид-центр по автозаявке) — «по этому диалогу заявка уже создана», источник — LeadChat. Базу заявки LeadChat не хранит (dir пуст) */
  const заявкаLC = (conv) => {
    const n = String((conv && conv.crm_request_id) || '').trim();
    return n ? { id: n, dir: '', url: '', at: Date.parse((conv && conv.crm_request_at) || '') || 0, изLC: true } : null;
  };

  /* conv0 — строка списка («Входящие», «Мои»): в ней уже клиент, канал, объявление с поясом, статус, бот, передача.
     Обычный GET /conversations/{id} в LeadChat не «чтение»: он гасит оператору флажок «⚑ передан вам» и ставит в очередь
     дозапрос профиля. С 12.10 (LeadChat be2f017) есть тихое чтение ?peek=true — тот же ответ, флажок не гаснет, профиль не
     дозапрашивается. Расширение читает деталь ТОЛЬКО так (путьДиалога): «открыл» диалог оператор, а не мы. Строку списка,
     если она есть, всё равно берём вместо детали — запросом меньше. */
  const путьДиалога = (id) => '/conversations/' + encodeURIComponent(id) + '?peek=true';
  // прочитанная деталь помечена (скрытым полем): по ней видно, что это деталь, а не строка списка — второй раз не читаем
  const деталь = (id) => LC.get(путьДиалога(id)).then((d) => { if (d && typeof d === 'object') Object.defineProperty(d, '__деталь', { value: true }); return d; });
  const полнаяСтрока = (r) => !!(r && r.id && 'account' in r && 'client' in r && 'item' in r);
  /* Быстро: сообщения и карточка клиента — параллельно (клиент известен из строки). первая — уже прочитанная страница
     сообщений (наблюдение за открытым диалогом её только что получило) — второй раз не просим.
     Переписка — последние 100 сообщений ОДНИМ запросом (больше LeadChat за раз не отдаёт; раньше — две страницы по 50) */
  const ЛЕНТА_N = 100;
  const лента = (id, n) => LC.get('/conversations/' + encodeURIComponent(id) + '/messages?limit=' + (n || ЛЕНТА_N));
  async function loadDialog(id, conv0, первая) {
    const conv = полнаяСтрока(conv0) ? conv0 : await деталь(id);
    const [page, identity] = await Promise.all([
      первая ? Promise.resolve(первая) : лента(id),
      // карточка не открылась — разберём по переписке
      conv.client && conv.client.id ? LC.get('/clients/' + encodeURIComponent(conv.client.id) + '/identity').catch(() => null) : null]);
    const msgs = ((page && page.items) || []).slice();
    msgs.sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
    // диалог MAX: партнёр, источник, город с поясом и ссылка для отзыва — из диалога Авито этого клиента (conv.авито)
    if (LC_EXTRACT.каналMAX(conv)) conv.авито = await авитоКлиента(conv, msgs, identity).catch(() => null);
    return { conv, msgs, identity, messagePage:page?.page };
  }
  // последнее сообщение диалога — одним сообщением (limit=1: LeadChat отдаёт самые новые), а не страницей ради его id
  const последнееИз = (page) => ((page && page.items) || []).slice().sort((x, y) => Date.parse(x.created_at) - Date.parse(y.created_at)).pop() || null;

  /* ДИАЛОГ MAX (LeadChat с 10–11.10: бот MAX или личный номер). У него нет объявления Авито (item всегда null), партнёра и источника
     канала (lead_partner_number / lead_origin пусты и не задаются), название канала — просто имя бота или номера (один бот на все базы).
     Клиент приходит в MAX по приглашению из своего диалога Авито — партнёр, источник, город с поясом и ссылка для отзыва берутся оттуда.
     LeadChat с 12.10 находит этот диалог сам — max_source в детали диалога MAX (app/services/conversations.py max_source_view):
     по приглашению (invite), по той же карточке клиента (same_client), по основному телефону (phone); null — искал и не нашёл
     (клиент пришёл в MAX сам) — тогда и мы по номеру не ищем. В строках списков max_source нет — деталь читаем тихо (?peek=true).
     LeadChat до 12.10 (ключа max_source нет вовсе) — ищем сами по номеру клиента (tab=any — и закрытые): самый свежий диалог Авито,
     где телефон клиента — этот номер.
     conv.авито: { id, account, item, found_by } — нашёлся; null — номера нет или диалога Авито не нашлось. conv.новыйLC: true — LeadChat
     отдал max_source (с 12.10: он же расшифровывает голосовые MAX), false — не отдал (до 12.10), нет поля — не узнали.
     Канал MAX (его id и название) не идёт ни в базу, ни в ссылку для отзыва, ни в общую память команды */
  const АВИТО_КЛИЕНТА = new Map(), АВИТО_МС = 10 * 60e3, АВИТО_НЕТ_МС = 2 * 60e3, АВИТО_ЖДЁМ = 6000;
  const десятьЦифр = (p) => String(p || '').replace(/\D/g, '').slice(-10);
  // max_source LeadChat → conv.авито (те же поля, что у поиска по номеру; у канала — ещё ссылка для отзыва и ключ источника)
  function изИсточника(ms) {
    if (!ms || !ms.conversation_id) return null;
    const a = ms.account || {}, it = ms.item;
    return { id: String(ms.conversation_id), found_by: String(ms.found_by || ''),
      account: { id: String(a.id || ''), title: a.title || '', lead_origin: a.lead_origin || '', lead_partner_number: a.lead_partner_number || '',
        review_url: a.review_url || '', lead_src_key: a.lead_src_key || '' },
      item: it ? { url: it.url || '', title: it.title || '', city_name: it.city_name || '', city_slug: it.city_slug || '', city_tz: it.city_tz || '' } : null };
  }
  // диалог Авито клиента MAX: найденный при чтении (conv.авито) или, у детали LeadChat, которую не разбирали, — её max_source
  const авитоДиалога = (conv) => (!conv ? null : conv.авито !== undefined ? conv.авито : 'max_source' in conv ? изИсточника(conv.max_source) : null);
  // деталь диалога (GET /conversations/{id}), а не строка списка: у строк этих полей нет
  const детальДиалога = (c) => c.__деталь === true || 'bot_vars' in c || 'participants' in c;
  const ИСТОЧНИК_LC = { нет: false };                                 // LeadChat до 12.10: max_source не отдаёт — деталь ради него не читаем
  /* { r } — ответ LeadChat (r: диалог Авито или null — искал и не нашёл); null — LeadChat его не даёт (до 12.10). Строка списка —
     деталь тихо (?peek=true: без «⚑ передан вам» и дозапроса профиля), ответ — в кэш на тот же срок, что и поиск по номеру */
  async function источникLC(conv) {
    if ('max_source' in conv) return { r: изИсточника(conv.max_source) };
    if (ИСТОЧНИК_LC.нет || детальДиалога(conv)) { ИСТОЧНИК_LC.нет = true; return null; }
    const k = 'max_source|' + conv.id, был = АВИТО_КЛИЕНТА.get(k);
    if (был && Date.now() - был.at < (был.r ? АВИТО_МС : АВИТО_НЕТ_МС)) return { r: был.r };
    const d = await сТаймаутом(LC.get('/conversations/' + encodeURIComponent(conv.id) + '?peek=true'), АВИТО_ЖДЁМ, 'LeadChat не ответил за ' + АВИТО_ЖДЁМ / 1000 + ' с');
    if (!d || typeof d !== 'object' || !('max_source' in d)) { ИСТОЧНИК_LC.нет = true; return null; }
    const r = изИсточника(d.max_source);
    АВИТО_КЛИЕНТА.set(k, { at: Date.now(), r });
    return { r };
  }
  // номер клиента — тем же правилом, что и у заявки: карточка LeadChat, контакт MAX, номер в словах клиента
  function номерКлиента(conv, msgs, identity) {
    const cl = conv.client || {};
    return десятьЦифр(LC_EXTRACT.номерДляПоиска({ messages: сообщенияРазбора(msgs), identity, cardPhone: cl.phone, convId: conv.id,
      link: { confidence: cl.link_confidence || '', conflict: cl.link_phone_conflict === true } }).phone);
  }
  async function авитоКлиента(conv, msgs, identity) {
    // LeadChat с 12.10 искал сам (приглашение, карточка, телефон) — его ответ, и «не нашёл» тоже: по номеру больше не ищем
    let ист;
    try { ист = await источникLC(conv); } catch (_e) { ист = undefined; }   // деталь не прочиталась — ищем по номеру, как раньше
    if (ист) { conv.новыйLC = true; return ист.r; }
    if (ист === null) conv.новыйLC = false;
    const phone = номерКлиента(conv, msgs, identity);
    if (phone.length !== 10) return null;
    const k = conv.id + '|' + phone, был = АВИТО_КЛИЕНТА.get(k);
    if (был && Date.now() - был.at < (был.r ? АВИТО_МС : АВИТО_НЕТ_МС)) return был.r;
    const page = await сТаймаутом(LC.get('/conversations?tab=any&q=' + phone + '&limit=20'), АВИТО_ЖДЁМ, 'LeadChat не ответил за ' + АВИТО_ЖДЁМ / 1000 + ' с');
    const когда = (r) => Date.parse((r.last_message && r.last_message.created_at) || r.last_message_at || r.updated_at || r.created_at || '') || 0;
    const s = ((page && page.items) || []).filter((r) => r && r.id && r.id !== conv.id && !LC_EXTRACT.каналMAX(r) && десятьЦифр(r.client && r.client.phone) === phone)
      .sort((a, b) => когда(b) - когда(a))[0];
    const a = (s && s.account) || {}, it = s && s.item;
    // review_url — ссылка для отзыва канала Авито (LeadChat 12.10): её и берём вместо похода на Авито
    const r = s ? { id: String(s.id), phone, found_by: 'phone', account: { id: String(a.id || ''), title: a.title || '', lead_origin: a.lead_origin || '', lead_partner_number: a.lead_partner_number || '',
      review_url: typeof a.review_url === 'string' ? a.review_url : '' },
      item: it ? { url: it.url || '', title: it.title || '', city_name: it.city_name || '', city_slug: it.city_slug || '', city_tz: it.city_tz || '' } : null } : null;
    АВИТО_КЛИЕНТА.set(k, { at: Date.now(), r });
    for (const [kk, v] of АВИТО_КЛИЕНТА) if (Date.now() - v.at > АВИТО_МС) АВИТО_КЛИЕНТА.delete(kk);
    return r;
  }
  // как найден диалог Авито клиента MAX — словами для формы
  const КАК_НАЙДЕН = { invite: 'по приглашению', same_client: 'та же карточка клиента', phone: 'по телефону' };
  const какНайден = (a) => (a && КАК_НАЙДЕН[a.found_by] ? ' (' + КАК_НАЙДЕН[a.found_by] + ')' : '');
  // MAX, а диалога Авито этого клиента нет: партнёр, источник и город не определены
  const maxБезАвито = (conv) => LC_EXTRACT.каналMAX(conv) && !авитоДиалога(conv);

  /* ---------- память расширения ---------- */
  const store = {
    async get(k, d) { if (!alive()) throw new Error(УСТАРЕЛО); return (await chrome.storage.local.get(k))[k] ?? d; },
    async set(k, v) { if (!alive()) throw new Error(УСТАРЕЛО); await chrome.storage.local.set({ [k]: v }); },
  };

  /* ---------- стили: токены LeadChat с запасными значениями его тёмной темы ---------- */
  const CSS = `
    :host{all:initial}
    .lcz{--bg:var(--lc-bg-panel,#0b0e0d);--sunk:var(--lc-bg-selected,#141b18);--raise:var(--lc-bg-raise,#1a221e);
      --line:var(--lc-border,#2a332e);--t1:var(--lc-text-1,#e7ede9);--t2:var(--lc-text-2,#c7d2c9);--t3:var(--lc-text-3,#949e97);
      --t4:var(--lc-text-4,#7c877f);--acc:var(--lc-theme-accent,var(--lc-primary,#3cc13b));--acc-h:var(--lc-theme-accent,var(--lc-primary-hover,#57ca55));
      --on-acc:var(--lc-theme-accent-contrast,var(--lc-on-primary,#04160a));--ok:var(--lc-success-text,#7ed77c);--ok-bg:var(--lc-success-subtle,#10240f);
      --ok-line:var(--lc-success-solid,#2c9c2b);--warn:var(--lc-warning-text,#d9a94e);--warn-bg:var(--lc-warning-subtle,#241a05);
      --bad:var(--lc-danger-text,#ff9ea1);--bad-bg:var(--lc-danger-subtle,#2a1213);--bad-line:var(--lc-danger,#e5484d);
      --sh:var(--lc-shadow-3,0 24px 60px rgba(0,0,0,.5));--sh2:var(--lc-shadow-2,0 10px 30px rgba(0,0,0,.35));
      --warn-line:var(--lc-warning-border,color-mix(in srgb,var(--warn) 40%,var(--line)));
      --info:var(--lc-info-text,color-mix(in srgb,#6aa9f0 72%,var(--t1)));--info-bg:var(--lc-info-subtle,color-mix(in srgb,#6aa9f0 13%,var(--bg)));
      --info-line:var(--lc-info-border,color-mix(in srgb,#6aa9f0 38%,var(--line)));
      font-family:var(--lc-font,Inter,-apple-system,"Segoe UI",sans-serif);color:var(--t1);font-size:14px;line-height:1.5;-webkit-font-smoothing:antialiased}
    .lcz *{box-sizing:border-box;font-family:inherit;scrollbar-color:var(--line) transparent;scrollbar-width:thin}
    button{font:inherit;cursor:pointer}
    svg{flex:none}
    a{color:var(--ok)}a:hover{color:var(--acc-h)}
    /* кнопка (плавающая — запасная, когда карточки «Клиент» нет на экране) */
    .pill{height:30px;padding:0 12px;border:0;border-radius:999px;background:var(--acc);color:var(--on-acc);
      font:600 12px/1 var(--lc-font,Inter,sans-serif);letter-spacing:0;display:inline-flex;align-items:center;gap:6px;white-space:nowrap}
    .pill:hover{background:var(--acc-h)}
    .pill.ready{box-shadow:0 0 0 4px color-mix(in srgb,var(--acc) 28%,transparent);animation:lczp 1.6s ease-in-out 3}
    .pill.done{background:var(--ok-bg);color:var(--ok);box-shadow:inset 0 0 0 1px var(--ok-line)}
    .pill.busy{background:var(--raise);color:var(--t1);box-shadow:inset 0 0 0 1px var(--line)}.pill.busy .dot{animation:lczb2 1s ease-in-out infinite}
    @keyframes lczb2{50%{opacity:.25}}
    .pill .dot{width:7px;height:7px;border-radius:999px;background:currentColor}
    @keyframes lczp{50%{box-shadow:0 0 0 7px color-mix(in srgb,var(--acc) 18%,transparent)}}
    .fab{position:fixed;right:20px;bottom:96px;height:40px;padding:0 16px;font-size:14px;box-shadow:var(--sh2)}
    .rb{position:fixed;right:20px;top:12px;height:30px;padding:0 12px;background:var(--raise);color:var(--t1);border:1px solid var(--line);box-shadow:var(--sh2);font-weight:600}
    .rb:hover{background:var(--sunk);border-color:var(--acc)}
    .rb.auto{border-color:var(--acc);color:var(--ok)}
    .panel.open~.rb,.lcz:has(.panel.open) .rb,.lcz:has(.panel.open) .personal-launch{display:none}
    /* панель — выезжает справа во всю высоту */
    .panel{position:fixed;top:0;right:0;height:100vh;width:440px;max-width:100vw;background:var(--bg);
      border-left:1px solid var(--line);box-shadow:var(--sh);display:none;flex-direction:column}
    .panel.open{display:flex}
    .ph{padding:16px 16px 12px;display:flex;flex-direction:column;gap:12px;border-bottom:1px solid var(--line)}
    .ph .top{display:flex;align-items:flex-start;gap:8px}
    .ph .ttl{flex:1;min-width:0}
    .ph .t{font-size:16px;font-weight:600;line-height:1.25}
    .ph .sub{font-size:12px;color:var(--t3);margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .ib{width:40px;height:40px;border:0;border-radius:10px;background:transparent;color:var(--t3);display:flex;align-items:center;justify-content:center;flex:none}
    .ib:hover{background:var(--sunk);color:var(--t1)}
    .seg{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:4px;padding:4px;background:var(--sunk);border-radius:12px}
    .seg button{height:36px;border:0;border-radius:8px;background:transparent;color:var(--t2);font-weight:600;font-size:14px}
    .seg button.on{background:var(--acc);color:var(--on-acc)}
    .chips{display:flex;flex-wrap:wrap;gap:6px}
    .chip{display:inline-flex;align-items:center;gap:5px;min-height:24px;padding:2px 9px;border-radius:999px;font-size:11.5px;font-weight:500;line-height:1.3;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .chip.ok{background:var(--ok-bg);color:var(--ok)}.chip.warn{background:var(--warn-bg);color:var(--warn)}
    .chip.bad{background:var(--bad-bg);color:var(--bad)}.chip.info{background:var(--sunk);color:var(--t2)}
    .pb{flex:1;min-height:0;overflow:auto;padding:12px 14px 16px;display:flex;flex-direction:column;gap:10px;scrollbar-width:thin}
    .pf{padding:12px 16px 16px;border-top:1px solid var(--line);background:var(--bg);display:flex;flex-direction:column;gap:8px}
    .pf .row{display:flex;gap:8px}
    /* почему «Создать» не нажимается — строкой под кнопкой, ссылка ведёт к полю; намеренные пропуски отписки — приглушённо */
    .lk{border:0;background:none;padding:0;color:var(--acc);font:inherit;text-decoration:underline;cursor:pointer}
    .box.mut{color:var(--t4)}.box.mut>span:first-child{color:var(--t4)}.plr.mut{color:var(--t4)}.plr.mut .d{background:var(--t4)}
    .box .row.pa{display:flex;gap:6px;flex-wrap:wrap;margin-top:4px}.box .row.pa .sm.pri{background:var(--acc);border-color:var(--acc);color:var(--on-acc);font-weight:600}
    .go{flex:1;height:44px;border:0;border-radius:12px;background:var(--acc);color:var(--on-acc);font-size:15px;font-weight:600}
    .go:hover{background:var(--acc-h)}.go:disabled{opacity:.45;cursor:default}
    .sq{width:44px;height:44px;border:1px solid var(--line);border-radius:12px;background:transparent;color:var(--t2);display:flex;align-items:center;justify-content:center}
    .sq:hover{background:var(--sunk)}
    .kb{font-size:12px;color:var(--t4);text-align:center}
    /* «заявка создана»: карточка-итог, три действия плитками, что отписано */
    .hero{background:var(--sunk);border:1px solid var(--line);border-radius:12px;padding:16px;display:flex;flex-direction:column;gap:14px;flex:none}
    .hero-h{display:flex;align-items:center;gap:12px}
    .badge{width:40px;height:40px;border-radius:12px;background:var(--ok-bg);color:var(--ok);display:flex;align-items:center;justify-content:center;flex:none}
    .big{font-size:20px;font-weight:600;line-height:1.25;font-variant-numeric:tabular-nums}
    .dl{display:grid;grid-template-columns:88px minmax(0,1fr);row-gap:8px;column-gap:12px;font-size:13px;margin:0}
    .dl dt{color:var(--t3)}.dl dd{margin:0;color:var(--t1);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .dl dd.warn{color:var(--warn);font-weight:600}.dl.wrap dd{white-space:normal;overflow:visible;overflow-wrap:anywhere}
    .cap{margin:2px 0 0}
    .acts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;flex:none}
    .act{height:64px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--t1);font:inherit;font-size:12.5px;font-weight:500;
      display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;cursor:pointer;min-width:0}
    .act:hover{border-color:var(--acc)}.act>span:first-child{color:var(--t3)}.act:disabled{opacity:.6;cursor:default}
    .plog{display:flex;flex-direction:column;gap:8px}
    .plr{display:flex;align-items:flex-start;gap:10px;font-size:13px;color:var(--t2);min-width:0}
    .plr .d{width:8px;height:8px;border-radius:50%;background:var(--ok);flex:none;margin-top:6px}.plr.bad .d{background:var(--bad-line)}
    .plr .tx{min-width:0;overflow-wrap:anywhere}
    .go2{flex:1;height:44px;border-radius:12px;border:1px solid var(--line);background:transparent;color:var(--t1);font-size:14px;font-weight:600;cursor:pointer}
    .go2:hover{background:var(--sunk)}
    .lnkgo{display:flex;align-items:center;justify-content:center;gap:8px;text-decoration:none;font-size:14px}
    .lnkgo:hover{color:var(--on-acc)}
    .sec{background:var(--sunk);border:1px solid var(--line);border-radius:14px;padding:12px 14px 14px;display:flex;flex-direction:column;gap:10px}
    .sec.hl{border-color:color-mix(in srgb,var(--warn) 45%,var(--line))}
    .sh .st{font-size:12px;display:inline-flex;align-items:center;gap:4px;text-align:right;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:65%}
    .sh .st.ok{color:var(--ok)}.sh .st.warn{color:var(--warn)}.sh .st.mut{color:var(--t4)}
    .sh{display:flex;align-items:center;justify-content:space-between;gap:8px}
    .sh h3,.set-h h3,.cap{margin:0;font-size:12px;font-weight:600;letter-spacing:.04em;color:var(--t3);text-transform:uppercase}
    .g2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
    .g3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
    .gsh{display:grid;grid-template-columns:minmax(0,1fr) 88px;gap:10px}
    .f{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--t3);min-width:0}
    .post{display:flex;flex-direction:column;gap:2px;margin-bottom:8px}
    input,select,textarea{height:36px;padding:0 10px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--t1);font-size:14px;width:100%}
    select{padding:0 8px}
    textarea{height:auto;min-height:104px;padding:8px 10px;font-size:13px;line-height:1.5;resize:vertical}
    input:focus,select:focus,textarea:focus{outline:none;border-color:var(--acc);box-shadow:0 0 0 3px color-mix(in srgb,var(--acc) 25%,transparent)}
    .bad-f{border-color:var(--bad-line)!important;box-shadow:0 0 0 3px color-mix(in srgb,var(--bad-line) 22%,transparent)!important}
    .ck{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--t2)}
    .ck input{width:16px;height:16px;padding:0;accent-color:var(--acc)}
    .cks{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));grid-auto-flow:row dense;gap:8px}
    .cks .ck{height:36px;padding:0 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);min-width:0;white-space:nowrap;overflow:hidden;cursor:pointer}
    .cks .ck.wide{grid-column:1/-1}
    .cks.one{grid-template-columns:minmax(0,1fr)}
    .cks .ck:has(input:checked){border-color:var(--acc);color:var(--t1)}
    .cks .ck>span{min-width:0;overflow:hidden;text-overflow:ellipsis}
    .n{font-size:12px;line-height:1.4}.n.ok{color:var(--ok)}.n.warn{color:var(--warn)}.n.mut{color:var(--t4)}.n.bad{color:var(--bad)}
    .box .sm,.sec .sm{height:30px;padding:0 12px;border-radius:8px;border:1px solid var(--line);background:var(--raise);color:var(--t1);font-size:12.5px;font-weight:500;cursor:pointer}
    .sec .sm.pri{background:var(--acc);border-color:var(--acc);color:var(--on-acc);font-weight:600}
    .sec .sm:hover{border-color:var(--t4)}.sec .sm.pri:hover{background:var(--acc-h)}
    .tseg{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:4px;padding:3px;background:var(--bg);border:1px solid var(--line);border-radius:10px}
    .tseg button{height:30px;border:0;border-radius:7px;background:transparent;color:var(--t3);font-size:13px;font-weight:500}
    .tseg button.on{background:var(--raise);color:var(--t1);font-weight:600}
    .lnk{height:36px;display:flex;align-items:center;gap:6px;padding:0 10px;border-radius:8px;background:var(--ok-bg);font-size:13px;text-decoration:none;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
    /* подсказки — спокойные «выноски» с цветной полоской слева, текст основного цвета */
    .box{border-radius:10px;padding:10px 12px;font-size:12.5px;line-height:1.45;display:flex;gap:10px;align-items:flex-start;
      border:1px solid var(--line);background:var(--bg);color:var(--t2)}
    .box>span:first-child{margin-top:1px}
    .box.warn{background:var(--warn-bg);border-color:color-mix(in srgb,var(--warn) 38%,var(--line))}.box.warn>span:first-child{color:var(--warn)}
    .box.bad{background:var(--bad-bg);border-color:color-mix(in srgb,var(--bad-line) 50%,var(--line))}.box.bad>span:first-child{color:var(--bad)}
    .box.ok{background:var(--ok-bg);border-color:color-mix(in srgb,var(--ok-line) 55%,var(--line))}.box.ok>span:first-child{color:var(--ok)}
    /* варианты (посёлки, чаты) — строки списка одной высоты: название слева, метка справа */
    .opts{display:flex;flex-direction:column;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:var(--bg)}
    .opt{display:flex;align-items:center;gap:10px;min-height:44px;padding:0 12px;border:0;border-top:1px solid var(--line);background:transparent;color:var(--t1);
      font:inherit;font-size:13px;text-align:left;cursor:pointer;width:100%}
    .opt:first-child{border-top:0}.opt:hover{background:var(--sunk)}
    .opt .nm{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .opt .tag{flex:none;font-size:11.5px;padding:2px 8px;border-radius:999px}.opt .tag.ok{background:var(--ok-bg);color:var(--ok)}.opt .tag.mut{background:var(--raise);color:var(--t3)}
    .opt input{flex:none;width:16px;height:16px;margin:0;accent-color:var(--acc)}
    .box .c{display:flex;flex-direction:column;gap:5px;min-width:0;flex:1}
    .box b{color:var(--t1);font-weight:600}
    .box .n.mut{color:var(--t3)}
    .jr{display:flex;gap:10px;align-items:flex-start;padding:8px 2px;border-bottom:1px solid var(--line);font-size:13px}.jr a{color:var(--acc)}
    .jt{font-variant-numeric:tabular-nums;color:var(--t3);min-width:42px}
    .tst{width:360px;max-width:calc(100vw - 32px);background:var(--raise);border:1px solid var(--line);border-radius:14px;
      box-shadow:var(--sh2);padding:12px 14px 14px;display:flex;flex-direction:column;gap:6px;font-size:13px;line-height:1.45;color:var(--t1)}
    .tst-k{display:flex;align-items:center;gap:8px;font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--t3)}
    .tst-k .dot{width:8px;height:8px;border-radius:50%;flex:none;background:var(--ok)}
    .tst.warn .tst-k .dot{background:var(--warn)}.tst.info .tst-k .dot{background:var(--acc)}.tst.tst-low .tst-k .dot{background:var(--t4)}
    .tst-k .x{margin-left:auto;width:24px;height:24px;border:0;border-radius:6px;background:transparent;color:var(--t3);display:flex;align-items:center;justify-content:center;padding:0;cursor:pointer}
    .tst-k .x:hover{background:var(--sunk);color:var(--t1)}
    .tst-t{font-weight:600;font-size:13.5px;color:var(--t1);overflow-wrap:anywhere}
    .tst-d{font-size:12px;color:var(--t3);overflow-wrap:anywhere}.tst-d.warn{color:var(--warn)}.tst-d.ok{color:var(--ok)}
    .tst-q{padding:8px 10px;border-radius:8px;background:var(--sunk);color:var(--t1);font-size:12.5px;overflow-wrap:anywhere}
    .tst-a{display:flex;align-items:center;gap:6px;margin-top:6px;flex-wrap:wrap}
    .tst .sm{height:32px;padding:0 12px;white-space:nowrap;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--t1);font-size:12.5px;font-weight:500;cursor:pointer}
    .tst .sm.pri{background:var(--acc);border-color:var(--acc);color:var(--on-acc);font-weight:600}.tst .sm.pri:hover{background:var(--acc-h)}
    .tst .sm.ghost{flex:none;height:24px;background:transparent;border-color:transparent;color:var(--t3);padding:0 2px;font-size:11.5px;text-decoration:underline;text-underline-offset:2px}.tst .sm.ghost:hover{color:var(--t1)}
    .tst .sm:disabled{opacity:.6;cursor:default}
    .tst-f{display:flex;align-items:center;justify-content:space-between;gap:10px;font-size:11.5px;line-height:1.4;color:var(--t4);border-top:1px solid var(--line);padding-top:7px;margin-top:6px}
    /* стопка: развёрнуты самое новое и важные (keep), остальные — строкой 36 px (клик — развернуть); «Пропущено: N»; полоска режима — своё место */
    .tst.tst-c{flex-direction:row;align-items:center;gap:10px;height:36px;padding:0 12px;border-radius:10px;cursor:pointer;overflow:hidden;flex:none}
    .tst.tst-c>:not(.tst-k):not(.tst-t){display:none}.tst.tst-c .tst-k{flex:none}.tst.tst-c .tst-k .x{display:none}
    .tst.tst-c .tst-t{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:12.5px;font-weight:500}
    .tst.tst-c:hover{border-color:var(--t4)}
    .tst-r{display:flex;align-items:center;justify-content:space-between;gap:8px;min-width:0}.tst-r>div{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px}
    .tst-r b{color:var(--t1);font-weight:500}.tst .tst-r .sm{flex:none;height:28px}
    .tst-slot:empty{display:none}
    .tst-miss{align-self:flex-start;flex:none;height:28px;padding:0 12px;border-radius:999px;border:1px solid var(--line);background:var(--raise);color:var(--t2);font-size:12px;font-weight:500;box-shadow:var(--sh2);cursor:pointer}
    .tst-miss:hover{color:var(--t1);border-color:var(--t4)}
    .chip{display:inline-flex;align-items:center;height:20px;padding:0 8px;margin-left:6px;border-radius:999px;font-size:11px;font-weight:600;letter-spacing:0;text-transform:none;vertical-align:middle;background:var(--warn-bg);color:var(--warn)}
    .chip.bad{background:var(--bad-bg);color:var(--bad)}

    /* «Готовые»: настройки и списки — строки одной высоты, всё по двум линиям (текст слева, управление справа) */
    .sec.set{padding:0;gap:0;overflow:hidden;flex:none}
    .pb>*{flex-shrink:0}
    .set-h{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:12px 14px}
    .set-h .st{font-size:12px}.set-h .st.ok{color:var(--ok)}.set-h .st.mut{color:var(--t4)}
    .set-r{display:flex;align-items:center;gap:14px;padding:11px 14px;border-top:1px solid var(--line);min-height:58px;cursor:pointer}
    .set-r .tx{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px}
    .set-r .tt,.lst-r .tt{font-size:13px;font-weight:600;color:var(--t1);line-height:1.3}
    .set-r .ds,.lst-r .ds{font-size:12px;line-height:1.4;color:var(--t4)}
    .set-r.off{cursor:default}.set-r.off .tx{opacity:.45}
    .set-f{padding:10px 14px 12px;border-top:1px solid var(--line);font-size:12px;line-height:1.45;color:var(--t4);display:flex;flex-direction:column;gap:4px}
    .set-f .ok{color:var(--ok)}
    .sw{-webkit-appearance:none;appearance:none;flex:none;width:36px;height:20px;margin:0;padding:0;border:0;border-radius:999px;
      background:var(--line);position:relative;cursor:pointer;transition:background .15s}
    .sw::after{content:'';position:absolute;top:2px;left:2px;width:16px;height:16px;border-radius:50%;background:var(--t2);transition:transform .15s,background .15s}
    .sw:checked{background:var(--acc)}.sw:checked::after{transform:translateX(16px);background:var(--on-acc)}
    .sw:focus-visible{outline:2px solid var(--acc);outline-offset:2px}.sw:disabled{opacity:.5;cursor:default}
    input.num{flex:none;width:64px;height:30px;padding:0 6px;text-align:center;font-variant-numeric:tabular-nums}
    .lst{display:flex;flex-direction:column;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--bg);flex:none}
    .lst-h,.lst-d>summary{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:9px 14px;font-size:12px;font-weight:600;
      letter-spacing:.04em;text-transform:uppercase;color:var(--t3);background:var(--sunk)}
    .cnt{font-variant-numeric:tabular-nums;letter-spacing:0;color:var(--t2);min-width:20px;text-align:right}
    .lst-r{display:flex;align-items:center;gap:14px;padding:10px 14px;border-top:1px solid var(--line);min-height:56px}
    .lst-r .tx{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px}
    .lst-r .tt{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .lst-r .ds{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.lst-r .ds.warn,.lst-r .ds .w{color:var(--warn)}
    .lst .sm{flex:none;min-width:76px;height:30px;padding:0 12px;border-radius:8px;border:1px solid var(--line);background:var(--raise);color:var(--t1);font-size:12.5px;font-weight:500;cursor:pointer}
    .lst .sm.pri{background:var(--acc);border-color:var(--acc);color:var(--on-acc);font-weight:600}.lst .sm.pri:hover{background:var(--acc-h)}
    .lst-d{border-top:1px solid var(--line)}.lst-h+.lst-d{border-top:1px solid var(--line)}
    .lst-d>summary{list-style:none;cursor:pointer;background:transparent;text-transform:none;letter-spacing:0;font-size:13px;color:var(--t2);font-weight:500;min-height:42px}
    .lst-d>summary::-webkit-details-marker{display:none}
    .lst-d>summary>span:first-child{display:inline-flex;align-items:center;gap:10px}
    .lst-d>summary>span:first-child::before{content:'';width:6px;height:6px;border-right:1.5px solid var(--t4);border-bottom:1.5px solid var(--t4);transform:rotate(-45deg);transition:transform .15s}
    .lst-d[open]>summary>span:first-child::before{transform:rotate(45deg)}
    .lst-s{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 12px;padding:8px 14px 8px 30px;border-top:1px dashed var(--line);font-size:12px}
    .lst-s .tt{color:var(--t1);font-weight:500;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .lst-s .ds{grid-column:1;color:var(--t4);line-height:1.4}.lst-s a{grid-column:2;grid-row:1;color:var(--acc);text-decoration:none}

    .box .sm{height:28px;padding:0 10px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--t1);font-size:12px;font-weight:500;cursor:pointer}
    .box .sm:disabled{opacity:.6;cursor:default}.box a{color:inherit}
    .steps{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:4px}
    .steps li{display:flex;align-items:center;gap:12px;padding:10px 12px;border-radius:10px;color:var(--t3)}
    .steps li.done{color:var(--t1)}.steps li.now{background:var(--sunk);border:1px solid var(--line);color:var(--t1);font-weight:500}
    .steps .ic{width:24px;height:24px;border-radius:999px;display:flex;align-items:center;justify-content:center;flex:none}
    .steps li.done .ic{background:var(--ok-bg);color:var(--ok)}
    .steps li.now .ic{border:2px solid var(--line);border-top-color:var(--acc);animation:lczs .8s linear infinite}
    .steps li.wait .ic{border:2px solid var(--line)}
    @keyframes lczs{to{transform:rotate(360deg)}}
    .bar{height:2px;background:linear-gradient(90deg,transparent,var(--acc),transparent);background-size:200% 100%;animation:lczb 1s linear infinite}
    @keyframes lczb{from{background-position:200% 0}to{background-position:-200% 0}}
    .win{background:var(--ok-bg);border:1px solid var(--ok-line);border-radius:14px;padding:16px;display:flex;flex-direction:column;gap:12px}
    .win .hd{display:flex;align-items:center;gap:12px}
    .win .big{width:40px;height:40px;border-radius:999px;background:var(--acc);color:var(--on-acc);display:flex;align-items:center;justify-content:center}
    .win .num{font-size:24px;font-weight:700;letter-spacing:-.01em;line-height:1.2}
    .win .row{display:flex;gap:8px}
    .opencrm{flex:1;height:40px;display:flex;align-items:center;justify-content:center;gap:6px;border-radius:10px;background:var(--acc);color:var(--on-acc)!important;font-weight:600;text-decoration:none}
    .ghost{height:40px;padding:0 14px;border:1px solid var(--ok-line);border-radius:10px;background:transparent;color:var(--ok);font-size:14px;font-weight:500}
    /* карточка «Заявку можно создавать» */
    .card{position:fixed;right:20px;bottom:144px;width:360px;max-width:calc(100vw - 40px);background:var(--raise);
      border:1px solid var(--ok-line);border-radius:16px;box-shadow:var(--sh2);padding:14px 16px 16px;display:none;flex-direction:column;gap:12px}
    .card.show{display:flex}
    .card.top{top:64px;bottom:auto}
    .card .hd{display:flex;align-items:center;gap:10px}
    .card .ok-ic{width:28px;height:28px;border-radius:999px;background:var(--ok-bg);color:var(--ok);display:flex;align-items:center;justify-content:center}
    .card .tt{flex:1;font-size:15px;font-weight:600}
    .kv{display:grid;grid-template-columns:76px minmax(0,1fr);row-gap:6px;column-gap:10px;font-size:13px}
    .kv .k{color:var(--t3)}.kv .v{min-width:0;overflow-wrap:anywhere}
    .kv .v .ok{color:var(--ok)}.kv .v .warn{color:var(--warn)}
    .card .row{display:flex;gap:8px}
    .card .go{height:40px;font-size:14px;border-radius:10px}
    .card .sq{width:auto;height:40px;padding:0 14px;border-radius:10px;font-size:14px}
    /* 1.20: действия по заявке — сетка (6 основных плиток 3×2 по 48 px, «Ещё» мелкими 4 в ряд), чипы галочек, карточка с превью */
    /* поле «по условию» (согласовано — только при «Директор», время звонка — только при «Прозвон»): .f/.ck с display:flex иначе перебивают hidden */
    [data-afw][hidden],[data-ac][hidden],.ag-why[hidden]{display:none}
    .ag{display:flex;flex-direction:column;gap:8px;flex:none;min-width:0}
    .ag-st{font-size:12.5px;color:var(--t2);overflow-wrap:anywhere}.ag-st b{color:var(--t1);font-weight:600}
    .ag-chips{display:flex;flex-wrap:wrap;gap:6px}
    .ag-chip{height:24px;padding:0 9px;border-radius:999px;border:1px solid var(--line);background:transparent;color:var(--t3);font-size:11.5px;font-weight:500;cursor:pointer}
    .ag-chip.on{background:var(--ok-bg);color:var(--ok);border-color:var(--ok-line)}.ag-chip:disabled{cursor:default;opacity:.7}
    .ag-tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}
    .ag-t{position:relative;height:48px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--t1);font-size:12px;font-weight:500;
      display:flex;align-items:center;justify-content:center;gap:6px;padding:0 6px;min-width:0;cursor:pointer}
    .ag-t>span:first-child{color:var(--t3)}.ag-t:hover{border-color:var(--acc)}.ag-t:disabled,.ag-s:disabled{opacity:.5;cursor:default}
    .ag-t .lb,.ag-s .lb{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .ag-t.hint,.ag-s.hint{border-color:var(--acc);box-shadow:0 0 0 2px color-mix(in srgb,var(--acc) 25%,transparent)}
    .ag-hint{position:absolute;top:-7px;right:6px;padding:0 5px;border-radius:999px;background:var(--acc);color:var(--on-acc);font-size:10px;line-height:14px}
    .ag-more>summary{cursor:pointer;font-size:12.5px;color:var(--t2);list-style:none;padding:2px 0}.ag-more>summary::-webkit-details-marker{display:none}
    .ag-g{display:flex;flex-direction:column;gap:4px;margin-top:6px}.ag-gh{font-size:11px;color:var(--t4);text-transform:uppercase;letter-spacing:.04em}
    .ag-sm{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px}
    .ag-s{position:relative;height:32px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--t1);font-size:11.5px;padding:0 4px;min-width:0;cursor:pointer}
    .ag-s:hover{border-color:var(--acc)}
    .ag-q{display:flex;flex-direction:column;gap:2px}.ag-qb{align-self:flex-start;width:22px;height:22px;border-radius:999px;border:1px solid var(--line);background:transparent;color:var(--t3);font-size:12px;cursor:pointer;padding:0}
    .ac-other{height:30px;font-size:12.5px;padding:0 8px}
    /* 2.2.5: «Заполнить и повторить» — выбор пустых обязательных полей карточки CRM в итоге действия и в уведомлении */
    .ac-fill{display:flex;flex-direction:column;gap:8px;margin:8px 0 2px}.ac-fill .f{gap:4px}.ac-fill .lb{font-size:12.5px;color:var(--t2)}
    .ac-pv{display:flex;flex-direction:column;gap:6px;border:1px solid var(--line);border-radius:10px;padding:8px 10px;background:var(--bg);font-size:12.5px}
    .ac-r{display:flex;flex-direction:column;gap:3px;min-width:0}.ac-k{color:var(--t3);font-size:12px}.ac-v{color:var(--t1);overflow-wrap:anywhere}
    .card{max-height:calc(100vh - 160px);overflow:auto}.card.top{max-height:calc(100vh - 80px)}
    /* 2.0: окно действия по проекту Claude Design «2.0 — все действия с заявкой» — шапка и кнопка прилипают, поля крупные */
    .card:has(>.hd[data-act-card]){width:400px;padding:0 16px;gap:14px;border-color:var(--line)}
    .card>.hd[data-act-card]{position:sticky;top:0;z-index:2;margin:0 -16px;padding:14px 16px 12px;background:var(--raise);border-bottom:1px solid var(--line)}
    .ac-ic{width:32px;height:32px;border-radius:10px;background:color-mix(in srgb,var(--acc) 18%,transparent);color:var(--acc);display:flex;align-items:center;justify-content:center;flex:none}
    .ac-ic.bad{background:var(--bad-bg);color:var(--bad)}
    .card .ttl{flex:1;min-width:0}.card .ttl .tt{font-size:15px;font-weight:600;line-height:1.3}
    .card .ttl .sub{font-size:12px;color:var(--t3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .ac-hint{background:color-mix(in srgb,var(--acc) 12%,var(--bg));border:1px solid color-mix(in srgb,var(--acc) 40%,var(--line));border-radius:12px;padding:10px 12px;font-size:13px;color:var(--t2);flex:none}
    .ac-hint b{color:var(--t1);font-weight:600}
    .card .f{gap:6px;flex:none}.card .f>.lb{font-size:12.5px;font-weight:500;color:var(--t2)}
    .card .f>input,.card .f>select{height:40px;border-radius:10px;background:var(--sunk)}.card .f>textarea{border-radius:10px;background:var(--sunk)}
    .swl{display:flex;flex-direction:column;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--sunk);flex:none}
    .ck.swr{gap:12px;padding:10px 14px;min-height:54px;border-top:1px solid var(--line);margin-top:-1px;cursor:pointer;color:var(--t1)}
    .swr .tx{flex:1;min-width:0;display:flex;flex-wrap:wrap;align-items:baseline;column-gap:6px;row-gap:1px}
    .swr .nm{font-size:14px;font-weight:500}.swr .ds{flex-basis:100%;font-size:12px;color:var(--t3);line-height:1.35}
    .swr .chg{font-size:11px;font-weight:600;color:var(--acc);background:color-mix(in srgb,var(--acc) 16%,transparent);border-radius:6px;padding:1px 6px}
    .swr .chg[hidden]{display:none}.swr.off{cursor:default}.swr.off .tx{opacity:.5}
    .ck.swr input.sw{width:40px;height:24px}.ck.swr input.sw::after{top:3px;left:3px;width:18px;height:18px}
    .sg{display:grid;gap:4px;padding:3px;background:var(--sunk);border:1px solid var(--line);border-radius:10px}
    .cityclock{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--t2);margin:-2px 0 2px}.cityclock b{font-size:15px;color:var(--t1);font-variant-numeric:tabular-nums}
    .sg-o{position:relative;min-height:34px;border-radius:8px;display:flex;align-items:center;justify-content:center;text-align:center;padding:4px 6px;font-size:13px;font-weight:500;color:var(--t2);cursor:pointer;line-height:1.2;min-width:0}
    .sg-o.on{background:var(--raise);color:var(--t1);box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--acc) 55%,var(--line))}
    .sg-o input,.rl-o input{position:absolute;opacity:0;width:1px;height:1px;margin:0;padding:0;pointer-events:none}
    .sg-o:has(input:focus-visible),.rl-o:has(input:focus-visible){outline:2px solid var(--acc);outline-offset:1px}
    .sg-o.off,.rl-o.off{cursor:default;opacity:.6}
    .rl{display:flex;flex-direction:column;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--sunk)}
    .rl-o{position:relative;display:flex;align-items:center;gap:10px;min-height:42px;padding:8px 14px;font-size:13.5px;color:var(--t2);cursor:pointer;line-height:1.3}
    .rl-o+.rl-o{border-top:1px solid var(--line)}.rl-o:hover{background:color-mix(in srgb,var(--raise) 60%,var(--sunk))}
    .rl-o .rd{width:18px;height:18px;border-radius:50%;border:2px solid var(--t4);flex:none}
    .rl-o.on{color:var(--t1)}.rl-o.on .rd{border-color:var(--acc);background:var(--acc);box-shadow:inset 0 0 0 3px var(--sunk)}
    .rl-o .nm{min-width:0;overflow-wrap:anywhere}
    .vh{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0 0 0 0)!important;border:0!important}
    .dq{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}
    .dq-d{height:50px;border-radius:10px;border:1px solid var(--line);background:var(--sunk);color:var(--t1);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1px;padding:0}
    .dq-d .w{font-size:11px;color:var(--t3)}.dq-d .d{font-size:14px;font-weight:600;font-variant-numeric:tabular-nums}
    .dq-d.on{background:var(--acc);border-color:var(--acc);color:var(--on-acc)}.dq-d.on .w{color:var(--on-acc);opacity:.85}
    .tq{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px}
    .tq-t{height:36px;border-radius:10px;border:1px solid var(--line);background:var(--sunk);color:var(--t1);font-size:13px;font-weight:500;font-variant-numeric:tabular-nums;padding:0}
    .tq-t.on{background:color-mix(in srgb,var(--acc) 22%,var(--sunk));border-color:var(--acc)}
    .dq-d:hover,.tq-t:hover{border-color:var(--acc)}.dq-d:disabled,.tq-t:disabled{opacity:.5;cursor:default}
    .ac-wrap{display:flex;flex-direction:column;gap:8px;flex:none}
    .card .cap{font-size:11.5px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--t3)}
    .ac-wrap .ac-pv{gap:12px;border-radius:12px;padding:14px;background:var(--sunk);font-size:13px}
    .ac-pv .ac-r{flex-direction:row;gap:10px;align-items:flex-start}
    .ac-n{width:22px;height:22px;border-radius:6px;background:var(--raise);color:var(--t3);display:flex;align-items:center;justify-content:center;flex:none;font-size:11px;font-weight:700}
    .ac-b{flex:1;min-width:0;display:flex;flex-direction:column;gap:6px}
    .ac-b .ac-k{color:var(--t1);font-weight:600;font-size:13px}.ac-b .ac-v{color:var(--t2)}
    textarea.code{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-size:12.5px;background:var(--bg);border-radius:8px}
    .ac-ck{display:flex;flex-direction:column;gap:8px;padding-top:10px;border-top:1px solid var(--line)}
    .ac-ck textarea{min-height:40px}
    .aw{display:flex;gap:8px;align-items:flex-start;background:var(--warn-bg);border-radius:10px;padding:10px 12px;font-size:12.5px;line-height:1.45;color:var(--warn)}
    .aw .c{color:color-mix(in srgb,var(--warn) 60%,var(--t1))}.aw>span:first-child{margin-top:1px}
    .card .row.acf{position:sticky;bottom:0;z-index:2;margin:0 -16px;padding:12px 16px 16px;background:var(--raise);border-top:1px solid var(--line);flex:none}
    .card .acf .go{height:auto;min-height:46px;padding:6px 12px;border-radius:12px;font-size:14px;line-height:1.25}.card .acf .sq{height:46px;border-radius:12px;padding:0 16px}
    .go.bad{background:var(--bad-line);color:#fff}.go.bad:hover{background:color-mix(in srgb,var(--bad-line) 85%,#fff)}
    .card .steps li{padding:8px 10px;min-height:40px;font-size:13.5px}
    .box.res{flex-direction:column;gap:10px;padding:14px;border-radius:12px;flex:none}
    .res-h{display:flex;align-items:center;gap:12px}
    .res-i{width:40px;height:40px;border-radius:12px;display:flex;align-items:center;justify-content:center;flex:none}
    .box.res.ok .res-i{background:color-mix(in srgb,var(--ok) 18%,transparent);color:var(--ok)}
    .box.res.warn .res-i{background:color-mix(in srgb,var(--warn) 18%,transparent);color:var(--warn)}
    .box.res.bad .res-i{background:color-mix(in srgb,var(--bad) 18%,transparent);color:var(--bad)}
    .res-t{font-size:15px;font-weight:600;color:var(--t1)}
    .res-l{display:flex;flex-direction:column;gap:6px}
    .res-l .ln{display:flex;gap:10px;align-items:flex-start;font-size:13px;color:var(--t2)}
    .res-l .d{width:8px;height:8px;border-radius:50%;margin-top:6px;flex:none;background:var(--ok)}
    .box.res.warn .res-l .d{background:var(--warn)}.box.res.bad .res-l .d{background:var(--bad-line)}
    .res-l .tx{min-width:0;overflow-wrap:anywhere}
    /* 2.0: сетка действий и подсказки — крупнее, как в проекте */
    .ag{gap:10px}
    .ag-tiles{gap:8px}
    .ag-t{height:66px;flex-direction:column;gap:6px;border-radius:12px;font-size:12.5px;text-align:center;line-height:1.2}
    .ag-t .lb{max-width:100%}
    .ag-t.hint{background:color-mix(in srgb,var(--acc) 14%,var(--bg))}.ag-t.hint>span:first-child{color:var(--acc)}
    .ag-chip{height:26px;padding:0 10px;font-size:12px}
    .ag-chip.on{background:color-mix(in srgb,var(--acc) 18%,transparent);color:var(--t1);border-color:color-mix(in srgb,var(--acc) 55%,var(--line))}
    .ag-more>summary{display:flex;align-items:center;justify-content:center;height:38px;border:1px dashed var(--line);border-radius:10px;font-size:13px;font-weight:500}
    .ag-more>summary:hover{border-color:var(--acc)}
    .ag-s{height:34px;border-radius:9px}
    .tst-k{font-size:12px;letter-spacing:0;text-transform:none}
    .tst-t{font-size:14.5px}
    .tst-q{border:1px solid var(--line)}
    .tst .sm{height:34px;border-radius:10px;font-size:13px}
    /* 2.0.1: карточка «У клиента есть актуальная заявка» — тем же видом, что окно действий */
    .card:has(>.hd[data-ex-card]){width:400px;padding:0 16px;gap:12px;border-color:var(--line)}
    .card>.hd[data-ex-card]{position:sticky;top:0;z-index:2;margin:0 -16px;padding:14px 16px 12px;background:var(--raise);border-bottom:1px solid var(--line)}
    .ac-ic.warn{background:var(--warn-bg);color:var(--warn)}
    .exr{background:var(--sunk);border:1px solid var(--line);border-radius:14px;padding:14px;display:flex;flex-direction:column;gap:10px;flex:none}
    .exr-h{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
    .exr-b{font-size:11.5px;font-weight:700;letter-spacing:.04em;color:var(--t3);background:var(--raise);border-radius:6px;padding:2px 7px}
    .exr-n{font-size:17px;font-weight:600;font-variant-numeric:tabular-nums;color:var(--t1)}
    .exr-st{margin-left:auto;font-size:12px;font-weight:600;border-radius:999px;padding:3px 10px;white-space:nowrap}
    .exr-st.info{background:color-mix(in srgb,var(--acc) 16%,transparent);color:var(--t1)}
    .exr-st.ok{background:var(--ok-bg);color:var(--ok)}.exr-st.bad{background:var(--bad-bg);color:var(--bad)}
    .exr-m{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:13px;color:var(--t2)}
    .exr-m span{display:inline-flex;align-items:center;gap:6px}.exr-m svg{color:var(--t3)}
    .exr-acts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
    .exr-a{height:60px;border-radius:12px;border:1px solid var(--line);background:var(--bg);color:var(--t1);font-size:12.5px;font-weight:600;
      display:flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;padding:0 4px;min-width:0}
    .exr-a>span:first-child{color:var(--t3)}.exr-a:hover{border-color:var(--acc)}
    .exr-a.bad>span:first-child{color:var(--bad)}.exr-a.bad:hover{border-color:var(--bad-line);background:var(--bad-bg)}
    .exr-row{display:flex;flex-wrap:wrap;gap:6px}
    .exr-l{height:34px;display:inline-flex;align-items:center;gap:6px;padding:0 12px;border-radius:10px;border:1px solid var(--line);background:transparent;
      color:var(--t2);font-size:12.5px;font-weight:500;text-decoration:none;cursor:pointer}
    .exr-l:hover{border-color:var(--acc);color:var(--t1)}.exr-l.on{border-color:var(--ok-line);color:var(--ok)}
    .exr-a{position:relative}.exr-a.hint{border-color:var(--acc);background:color-mix(in srgb,var(--acc) 14%,var(--bg));box-shadow:0 0 0 2px color-mix(in srgb,var(--acc) 25%,transparent)}
    .exr-a.hint>span:first-child{color:var(--acc)}.exr-a:disabled{opacity:.6;cursor:default}
    .exr-say{font-size:13px;color:var(--t2);background:var(--sunk);border:1px solid var(--line);border-radius:10px;padding:8px 10px;overflow-wrap:anywhere}
    .ac-tgr{display:flex;align-items:center;gap:8px;min-width:0}.ac-tgl{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:13px;color:var(--t1)}
    .ac-ed{flex:none;height:26px;padding:0 8px;border-radius:8px;border:1px solid var(--line);background:transparent;color:var(--t2);font-size:12px}.ac-ed:hover{border-color:var(--acc);color:var(--t1)}
    .ac-c1{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.ac-dt summary{cursor:pointer;font-size:12px;color:var(--t3)}.ac-dt[open] summary{margin-bottom:4px}
    .ac-cf{font-size:12px}.ac-sec{color:var(--t3);font-variant-numeric:tabular-nums}.tq-t.past{text-decoration:line-through}
    .exr [data-act-here]:not([hidden]){border-top:1px solid var(--line);padding-top:10px}
    /* 2.0.4: кнопка «Действия» и выбор заявки по номеру */
    .pill.pact{background:var(--raise);color:var(--t1);box-shadow:inset 0 0 0 1px var(--line);flex-direction:row}.pill.pact:hover{background:var(--sunk);box-shadow:inset 0 0 0 1px var(--acc)}
    .pill.pact svg{flex:none}.pill.pact:disabled{opacity:.7;cursor:default}
    .exr-grid{padding:8px 14px 10px;border-top:1px dashed var(--line)}.exr-grid[hidden]{display:none}
    .exr-man{border:1px solid var(--line);border-radius:12px;background:var(--sunk);padding:10px 12px;display:flex;flex-direction:column;gap:8px;flex:none}
    .exr-man>summary{cursor:pointer;font-size:13px;font-weight:500;color:var(--t2)}
    .exr-manrow{display:flex;gap:6px;align-items:center;margin-top:8px}
    .exr-sel{width:78px;flex:none;height:34px;border-radius:10px}.exr-num{flex:1;height:34px;border-radius:10px;font-variant-numeric:tabular-nums}
    .card .acf .go2{height:46px;border-radius:12px;font-size:14px}
    /* 2.0.1: календарь вместо системного (поле даты остаётся — можно напечатать) */
    input[type="date"]{cursor:pointer}
    input[type="date"]::-webkit-calendar-picker-indicator{display:none}
    .cal{position:fixed;z-index:2147483002;width:300px;background:var(--raise);border:1px solid var(--line);border-radius:14px;box-shadow:var(--sh);padding:12px;display:flex;flex-direction:column;gap:8px}
    .cal-h{display:flex;align-items:center;gap:6px}
    .cal-t{flex:1;text-align:center;font-size:14px;font-weight:600;color:var(--t1)}
    .cal-n{width:32px;height:32px;border:0;border-radius:8px;background:transparent;color:var(--t2);font-size:20px;line-height:1;padding:0}
    .cal-n:hover{background:var(--sunk);color:var(--t1)}
    .cal-g{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:2px}
    .cal-w span{text-align:center;font-size:11px;font-weight:600;color:var(--t4);padding:2px 0}
    .cal-d{height:36px;border:0;border-radius:9px;background:transparent;color:var(--t1);font-size:13px;font-weight:500;font-variant-numeric:tabular-nums;padding:0}
    .cal-d:hover{background:var(--sunk)}
    .cal-d.we{color:var(--t2)}.cal-d.out{color:var(--t4)}.cal-d.past{opacity:.45}
    .cal-d.today{box-shadow:inset 0 0 0 1.5px var(--acc)}
    .cal-d.on{background:var(--acc);color:var(--on-acc);opacity:1}
    .cal-qs{display:flex;gap:6px;padding-top:8px;border-top:1px solid var(--line)}
    .cal-q{flex:1;height:32px;border:1px solid var(--line);border-radius:8px;background:var(--sunk);color:var(--t1);font-size:12.5px;font-weight:500;padding:0 6px;white-space:nowrap}
    .cal-q:hover{border-color:var(--acc)}.cal-q.on{background:var(--acc);border-color:var(--acc);color:var(--on-acc)}
    /* ===== 2.1 форма ===== */
    /* шкала: шрифт 12/13/14/16/20 (часы 22), радиусы 6/10/14/круглые; цвет «нужно действие» — warn, «сведения» — info, «сделано» — ok */
    .ph.fm{padding:14px 16px 12px;gap:12px}
    .ph.fm .top{align-items:center;gap:6px}
    .ph.fm .t{font-size:20px;font-weight:600;line-height:1.25}
    .ph.fm .sub{font-size:13px;margin-top:2px}
    .ph.fm .ib{width:36px;height:36px;border:1px solid var(--line);border-radius:10px;background:var(--sunk);color:var(--t2)}
    .ph.fm .ib:hover{color:var(--t1);border-color:var(--t4)}
    .ph.fm .seg{padding:3px;gap:4px;border-radius:10px;background:var(--sunk);border:1px solid var(--line)}
    .ph.fm .seg button{height:36px;border-radius:8px;color:var(--t3);font-weight:500;font-size:14px}
    .ph.fm .seg button.on{background:var(--raise);color:var(--t1);font-weight:600;box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--ok-line) 60%,var(--line))}
    .ph.fm .seg button:focus-visible{outline:2px solid var(--acc);outline-offset:1px}
    .fz-dn{font-size:13px;line-height:1.4;color:var(--t2)}.fz-dn.warn{color:var(--warn)}.fz-dn.info{color:var(--info)}
    .pb.fm{padding:12px 16px 16px;gap:12px}
    .pb.fm .n{font-size:13px;line-height:1.4}
    .pb.fm .n.info{color:var(--info)}
    .pb.fm .box{font-size:13px;border-radius:10px}
    .pb.fm .box.warn{border-color:var(--warn-line)}
    .pb.fm .sm,.pf.fm .sm{height:32px;padding:0 12px;border-radius:10px;font-size:13px}
    .pb.fm .box .sm{height:32px}
    /* одна строка «что дальше»: что мешает создать — списком, у каждого «к полю →» */
    .fs{border-radius:14px;padding:12px 14px;display:flex;flex-direction:column;gap:8px;border:1px solid var(--line);flex:none}
    .fs.warn{background:var(--warn-bg);border-color:var(--warn-line)}
    .fs.ok{background:var(--ok-bg);border-color:color-mix(in srgb,var(--ok-line) 55%,var(--line))}
    .fs.mut{background:var(--sunk)}
    .fs-h{display:flex;align-items:center;gap:8px;font-size:16px;font-weight:600;color:var(--t1);line-height:1.3}
    .fs.warn .fs-h>span:first-child{color:var(--warn)}.fs.ok .fs-h>span:first-child{color:var(--ok)}.fs.mut .fs-h>span:first-child{color:var(--t3)}
    .fs-l{display:flex;flex-direction:column;gap:4px;padding-left:22px}
    .fs-r{display:flex;justify-content:space-between;align-items:baseline;gap:10px;font-size:13px;line-height:1.4;color:var(--t1)}
    .fs-r .tx{min-width:0;overflow-wrap:anywhere}
    .fs-r.mut .tx{color:var(--t2)}
    .fs-go{flex:none;border:0;background:none;padding:2px 0;color:var(--warn);font-size:13px;white-space:nowrap;cursor:pointer}
    .fs-go:hover,.fs-go:focus-visible{text-decoration:underline;outline:none}
    .fs-x{font-size:13px;color:var(--t2);padding-left:22px}
    /* факты: не больше трёх */
    .fz-chips{display:flex;flex-wrap:wrap;gap:6px}
    .fc{display:inline-flex;align-items:center;gap:6px;height:28px;padding:0 10px;border-radius:999px;font-size:12px;font-weight:500;max-width:100%;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;background:var(--sunk);color:var(--t2)}
    .fc.ok{background:var(--ok-bg);color:var(--ok)}.fc.warn{background:var(--warn-bg);color:var(--warn)}.fc.info{background:var(--info-bg);color:var(--info)}
    /* секции */
    .pb.fm .sec{padding:14px;gap:10px;border-radius:14px}
    .pb.fm .sec.hl{border-color:var(--warn-line)}
    .pb.fm .sh{align-items:baseline}
    .pb.fm .sh h3{font-size:16px;font-weight:600;letter-spacing:0;text-transform:none;color:var(--t1)}
    .pb.fm .sh .st{font-size:12px;max-width:62%}
    .pb.fm .sh .st.info{color:var(--info)}
    .pb.fm .f{font-size:12px;color:var(--t3);gap:4px}
    .pb.fm input:not([type=checkbox]):not([type=radio]):not([type=hidden]),.pb.fm select{height:40px;border-radius:10px;padding:0 12px;font-size:14px}
    .pb.fm select{padding:0 10px}
    .pb.fm textarea{border-radius:10px;padding:10px 12px;font-size:14px;line-height:1.45}
    .pb.fm .g2,.pb.fm .g3{gap:8px}
    .pb.fm .gsh{grid-template-columns:minmax(0,3fr) minmax(0,1fr);gap:8px}
    .pb.fm .cks .ck{height:40px;border-radius:10px;font-size:14px}
    .pb.fm .ck{font-size:14px;color:var(--t2)}
    .pb.fm .tseg{border-radius:10px}.pb.fm .tseg button{height:32px;border-radius:8px}
    .fz-lb{font-size:12px;color:var(--t3);margin-bottom:-4px}
    .fz-more{align-self:flex-start;height:32px;padding:0 10px;border-radius:10px;border:1px dashed var(--line);background:transparent;color:var(--t2);font-size:13px}
    .fz-more:hover{border-color:var(--t4);color:var(--t1)}
    .fz-open[hidden],.fz-more[hidden],.fz-det[hidden],.fz-hide{display:none!important}
    .fz-open{display:flex;flex-direction:column;gap:10px}
    .fz-hist{font-size:13px;color:var(--t2);display:flex;flex-direction:column;gap:4px}
    .fz-hist>summary{cursor:pointer;color:var(--t1);list-style:none}.fz-hist>summary::-webkit-details-marker{display:none}
    .fz-hist>summary::after{content:' ▾';color:var(--t3)}.fz-hist[open]>summary::after{content:' ▴'}
    .fz-hist a,.pb.fm .box a,.pb.fm .n a{color:var(--ok)}
    /* территория — одной строкой, подробности по «почему?» */
    .fz-terr{display:flex;gap:10px;align-items:flex-start;padding:10px 12px;border-radius:10px;background:var(--bg);border:1px solid var(--line);font-size:13px;line-height:1.4;color:var(--t2)}
    .fz-terr>span:first-child{color:var(--info);margin-top:2px}.fz-terr.warn{border-color:var(--warn-line)}.fz-terr.warn>span:first-child{color:var(--warn)}
    .fz-terr .c{flex:1;min-width:0;display:flex;flex-direction:column;gap:4px}
    .fz-terr b{color:var(--t1);font-weight:600}
    .fz-why{flex:none;height:28px;padding:0 8px;border:0;border-radius:6px;background:transparent;color:var(--t3);font-size:12px}
    .fz-why:hover,.fz-why[aria-expanded="true"]{color:var(--t1);background:var(--sunk)}
    .fz-det{white-space:pre-line;font-size:12px;color:var(--t3)}
    /* визит: часы города, дни, часы, «как договорились» */
    .fz-clock{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 12px;border-radius:10px;background:var(--bg);border:1px solid var(--line)}
    .fz-clock .cc-t{font-size:13px;color:var(--t3);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .fz-clock b{font-size:22px;font-weight:700;line-height:1.1;color:var(--t1);font-variant-numeric:tabular-nums}
    .fz-q{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px}
    .fz-qb{height:36px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--t1);font-size:13px;padding:0 4px;min-width:0;
      white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-variant-numeric:tabular-nums}
    .fz-qb:hover{border-color:var(--t4)}
    .fz-qb.on{border-color:color-mix(in srgb,var(--ok-line) 60%,var(--line));background:var(--ok-bg);font-weight:600}
    .fz-qb.soft{color:var(--t2)}.fz-qb.past{color:var(--t4);text-decoration:line-through}
    .fz-qb.info{background:var(--info-bg);border-color:var(--info-line);color:var(--info);font-weight:600}
    .fz-qb:focus-visible,.fz-seg button:focus-visible,.fz-more:focus-visible,.fz-why:focus-visible{outline:2px solid var(--acc);outline-offset:1px}
    .fz-seg{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:4px;padding:3px;border-radius:10px;background:var(--bg);border:1px solid var(--line)}
    .fz-seg button{height:34px;border:0;border-radius:8px;background:transparent;color:var(--t3);font-size:13px;font-weight:500;padding:0 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .fz-seg button.on{background:var(--raise);color:var(--t1);font-weight:600;box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--ok-line) 60%,var(--line))}
    /* комментарий: текст клиента — в поле, служебное — чипами (стереть случайно нельзя) */
    .fz-tags{display:flex;flex-wrap:wrap;gap:6px}
    .fz-tag{display:inline-flex;align-items:center;height:28px;padding:0 10px;border-radius:999px;background:var(--raise);border:1px solid var(--line);font-size:12px;color:var(--t2);max-width:100%;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
    .fz-tag.warn{color:var(--warn);border-color:var(--warn-line)}.fz-tag.bad{color:var(--bad);border-color:color-mix(in srgb,var(--bad-line) 50%,var(--line))}
    /* футер: одна большая кнопка, под ней — что осталось */
    .pf.fm{padding:12px 16px 16px;gap:10px}
    .pf.fm .post{margin-bottom:0;gap:4px}.pf.fm .post .ck{font-size:13px}
    .pf.fm .go{height:48px;border-radius:12px;font-size:16px}
    .fz-foot{display:flex;justify-content:space-between;gap:10px;font-size:12px;color:var(--t3);line-height:1.4}
    .fz-foot>span:first-child{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.fz-foot.ok>span:first-child{color:var(--ok)}
    .fz-foot>span:last-child{flex:none;color:var(--t4)}
    /* выбор времени — как календарь у даты: поле остаётся (можно напечатать 15:37), окно только ставит значение */
    input[type="time"]{cursor:pointer}
    input[type="time"]::-webkit-calendar-picker-indicator{display:none}
    .tp{position:fixed;z-index:2147483002;width:320px;background:var(--raise);border:1px solid var(--line);border-radius:14px;box-shadow:var(--sh);padding:14px;display:flex;flex-direction:column;gap:10px}
    .tp-h{display:flex;align-items:baseline;justify-content:space-between;gap:8px}
    .tp-h span{font-size:13px;color:var(--t3);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .tp-h b{font-size:20px;font-weight:700;color:var(--t1);font-variant-numeric:tabular-nums}
    .tp-lb{font-size:12px;color:var(--t3)}
    .tp-g{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;font-variant-numeric:tabular-nums}
    .tp-g.q{grid-template-columns:repeat(3,minmax(0,1fr))}
    .tp-b{height:36px;border-radius:10px;border:1px solid var(--line);background:var(--sunk);color:var(--t1);font-size:13px;padding:0 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-variant-numeric:tabular-nums}
    .tp-b:hover{border-color:var(--t4)}
    .tp-b:focus-visible{outline:2px solid var(--acc);outline-offset:1px}
    .tp-b.q2{height:46px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1px;line-height:1.2}
    .tp-b.q2 .w{font-size:12px;color:var(--t3)}.tp-b.q2 .d{font-size:14px;font-weight:600}.tp-b.q2.info .w{color:var(--info)}
    .tp-b.info{background:var(--info-bg);border-color:var(--info-line);color:var(--info);font-weight:600}
    .tp-b.soft{border-style:dashed;background:transparent;color:var(--t4)}
    .tp-b.past{background:transparent;color:var(--t4);text-decoration:line-through}
    .tp-b.on{border-style:solid;border-color:color-mix(in srgb,var(--ok-line) 60%,var(--line));background:var(--ok-bg);color:var(--t1);font-weight:700;text-decoration:none}
    .tp-f{font-size:12px;color:var(--t3);line-height:1.4}
    /* ===== /2.1 форма ===== */
    /* ===== 2.1 действия ===== */
    /* проект Claude Design «Действия», «Отмена», «Уведомления»: сетка, «Что в заявке», карточка действия, ход и итог, карточка «есть заявка».
       Цвета — из темы LeadChat; «сведения» (синий) и жёлтая черта — свои имена, чтобы не задеть общие токены */
    .card,.panel,.toasts,.ag{--ac-info:var(--info,#6aa9f0);--ac-info-bg:var(--info-bg,#0f1d2c);--ac-info-line:var(--info-line,#23415f);
      --ac-info-t:color-mix(in srgb,var(--ac-info) 55%,var(--t1));--ac-warn-line:var(--warn-line,#5b4721);--ac-bad-line:color-mix(in srgb,var(--bad-line) 45%,var(--line))}
    .card [hidden],.ag [hidden],.toasts .ac-tmore [hidden]{display:none!important}
    /* метка статуса заявки */
    .ac-pill{display:inline-flex;align-items:center;height:28px;padding:0 12px;border-radius:999px;font-size:13px;font-weight:600;white-space:nowrap;flex:none;margin-left:0}
    .ac-pill.info{background:var(--ac-info-bg);color:var(--ac-info-t)}.ac-pill.ok{background:var(--ok-bg);color:var(--ok)}
    .ac-pill.bad{background:var(--bad-bg);color:var(--bad)}.ac-pill.warn{background:var(--warn-bg);color:var(--warn)}
    /* строки-сообщения: «сведения» — синяя плашка, предупреждение — жёлтая строка у места */
    .ac-line{display:flex;gap:8px;align-items:flex-start;font-size:13px;line-height:1.4;color:var(--t2);flex:none;min-width:0;overflow-wrap:anywhere}
    .ac-line>span:first-child{flex:none;margin-top:1px}
    .ac-line.info{padding:10px 12px;border-radius:12px;background:var(--ac-info-bg);border:1px solid var(--ac-info-line);display:block}.ac-line.info b{color:var(--ac-info-t);font-weight:600}
    .ac-line.warn{color:var(--warn)}
    .ac-hint{background:var(--ac-info-bg);border:1px solid var(--ac-info-line);border-radius:12px;padding:10px 12px;font-size:13px;line-height:1.4;color:var(--t2)}.ac-hint b{color:var(--ac-info-t)}
    .ac-sug{display:flex;gap:10px;align-items:center;padding:10px 12px;border-radius:12px;background:var(--ac-info-bg);border:1px solid var(--ac-info-line);flex:none}
    .ac-sug .tx{flex:1;min-width:0;font-size:13px;line-height:1.4;color:var(--t2);overflow-wrap:anywhere}.ac-sug .tx b{color:var(--ac-info-t);font-weight:600}
    .ac-sug-b{flex:none;height:32px;padding:0 12px;border:0;border-radius:10px;background:var(--ac-info);color:#06121f;font-size:13px;font-weight:600;display:inline-flex;align-items:center}
    .ac-sug-b:hover{background:color-mix(in srgb,var(--ac-info) 85%,#fff)}.ac-sug-b:disabled{opacity:.6;cursor:default}
    .cap.ag-cap,.ag .cap{font-size:12px;font-weight:500;letter-spacing:.06em;text-transform:uppercase;color:var(--t3);margin:0}
    /* сетка: шапка, 6 больших плиток 3×2, «Ещё (N)» капсулами, «Нет здесь — почему» */
    .ag{gap:12px}
    .ag-st{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:14px;color:var(--t1)}
    .ag-st>b{font-size:16px;font-weight:600;font-variant-numeric:tabular-nums}.ag-st .chip{margin-left:0}
    .ag-upd{margin-left:auto;height:28px;padding:0 6px;border:0;border-radius:8px;background:transparent;color:var(--t3);font-size:12px}
    .ag-upd:hover{color:var(--t1);background:var(--sunk)}
    .ag-tiles{grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
    .ag-t{height:72px;border-radius:12px;border:1px solid var(--line);background:var(--sunk);color:var(--t1);font-size:13px;font-weight:500;flex-direction:column;gap:6px;padding:0 6px;line-height:1.2}
    .ag-t>span:first-child{color:var(--t2)}.ag-t:hover{border-color:var(--t4);background:color-mix(in srgb,var(--raise) 60%,var(--sunk))}
    .ag-t.bad{border-color:var(--ac-bad-line);color:var(--bad)}.ag-t.bad>span:first-child{color:var(--bad)}.ag-t.bad:hover{border-color:var(--bad-line);background:var(--bad-bg)}
    .ag-t.hint,.ag-s.hint{border-color:var(--ac-info);background:var(--ac-info-bg);box-shadow:none}.ag-t.hint>span:first-child{color:var(--ac-info-t)}
    .ag-more{display:flex;flex-direction:column;gap:8px}
    .ag-pills{display:flex;flex-wrap:wrap;gap:6px}
    .ag-s{height:32px;padding:0 12px;border-radius:999px;border:1px solid var(--line);background:var(--sunk);color:var(--t1);font-size:13px;font-weight:400;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .ag-s:hover{border-color:var(--t4)}.ag-s.bad{color:var(--bad);border-color:var(--ac-bad-line)}
    .ag-q{display:flex;flex-direction:column;gap:6px}
    .ag-no{font-size:13px;line-height:1.45;color:var(--t3)}
    .ag-qb{display:inline;width:auto;height:auto;padding:0 2px;border:0;border-radius:4px;background:transparent;color:var(--t2);font-size:13px;text-decoration:underline;text-underline-offset:2px;align-self:auto}
    .ag-qb:hover{color:var(--t1)}
    .ag-why{display:flex;flex-direction:column;gap:4px;padding:10px 12px;border-radius:10px;background:var(--sunk);border:1px solid var(--line);font-size:12.5px;line-height:1.4;color:var(--t3)}
    .ag-why b{color:var(--t2);font-weight:600}
    .ag-chips{gap:6px}
    .ag-chip{height:28px;padding:0 10px;border-radius:999px;font-size:12.5px}
    /* «Что в заявке» — карточка CRM двумя колонками */
    .ac-info{display:flex;flex-direction:column;gap:10px;padding:14px;border-radius:14px;background:var(--sunk);border:1px solid var(--line);flex:none;min-width:0}
    .ai-h{display:flex;align-items:baseline;justify-content:space-between;gap:8px}
    .ai-h h2{margin:0;font-size:16px;font-weight:600;color:var(--t1);line-height:1.3}
    .ai-crm{flex:none;font-size:12px;color:var(--t3);text-decoration:none;white-space:nowrap}.ai-crm:hover{color:var(--t1)}
    .ai-dl{display:grid;grid-template-columns:104px minmax(0,1fr);gap:6px 12px;margin:0;font-size:13px;line-height:1.4}
    .card .ai-dl{grid-template-columns:96px minmax(0,1fr)}
    .ai-dl dt{color:var(--t3)}.ai-dl dd{margin:0;min-width:0;color:var(--t1);overflow-wrap:anywhere;font-variant-numeric:tabular-nums}.ai-dl dd b{font-weight:600}
    .ai-dl .ag-chips{margin:-2px 0}
    .ai-mut{color:var(--t3)}.ai-warn{color:var(--warn)}
    .ai-list{display:flex;flex-direction:column;gap:2px}
    .ai-txt{white-space:pre-wrap;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden;cursor:pointer}.ai-txt.open{display:block}
    .ai-more>summary{list-style:none;cursor:pointer;height:28px;display:inline-flex;align-items:center;padding:0 8px;margin-left:-8px;border-radius:8px;font-size:12px;color:var(--t2)}
    .ai-more>summary::-webkit-details-marker{display:none}.ai-more>summary:hover{background:var(--raise);color:var(--t1)}
    .ai-more[open]>summary{margin-bottom:6px}
    /* карточка действия (проект «Отмена»): шапка с иконкой, поля 40 px с подписью 12 px, «Что произойдёт» по шагам, футер с одной главной */
    .card:has(>.hd[data-act-card]),.card:has(>.hd[data-ex-card]){width:440px;gap:14px}
    .card>.hd[data-act-card],.card>.hd[data-ex-card]{gap:10px}
    .card>.hd[data-act-card] .ac-ic,.card>.hd[data-ex-card] .ac-ic{width:36px;height:36px;border-radius:10px}
    .card>.hd[data-act-card] .ttl .tt,.card>.hd[data-ex-card] .ttl .tt{font-size:20px;font-weight:600;line-height:1.25}
    .card>.hd[data-act-card] .ttl .sub,.card>.hd[data-ex-card] .ttl .sub{font-size:13px;color:var(--t3);font-variant-numeric:tabular-nums}
    .card>.hd[data-act-card] .ib,.card>.hd[data-ex-card] .ib{width:36px;height:36px;border-radius:10px;border:1px solid var(--line);background:var(--sunk);color:var(--t2);flex:none}
    .card>.hd[data-act-card] .ib:hover,.card>.hd[data-ex-card] .ib:hover{color:var(--t1);border-color:var(--t4)}
    .card .f{gap:6px}.card .f>.lb{font-size:12px;font-weight:400;color:var(--t3);letter-spacing:0}
    .card .f>.lb .req{color:var(--warn)}
    .card .f>input,.card .f>select{height:40px;border-radius:10px}
    .f-ds{font-size:13px;line-height:1.4;color:var(--t3)}
    .card .swr .nm{font-size:14px}.card .swr .ds{font-size:13px}
    .ac-other{align-self:flex-start;width:auto;max-width:100%;height:32px;border-radius:10px;background:transparent;color:var(--t2);font-size:13px}
    .ac-who .ac-opts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
    .ac-opt{min-height:64px;padding:10px 12px;border-radius:12px;border:1px solid var(--line);background:var(--sunk);color:var(--t1);text-align:left;display:flex;flex-direction:column;justify-content:flex-start;gap:4px;font:inherit;cursor:pointer;min-width:0}
    .ac-opt b{font-size:15px;font-weight:600;line-height:1.25}.ac-opt .ds{font-size:12px;line-height:1.35;color:var(--t3);overflow-wrap:anywhere}
    .ac-opt:hover{border-color:var(--t4)}
    .ac-opt.on{border-color:var(--bad-line);background:var(--bad-bg)}.ac-opt.on .ds{color:var(--t2)}
    .ac-opt:focus-visible{outline:2px solid var(--bad-line);outline-offset:2px}
    .ac-opt.off,.ac-opt:disabled{opacity:.55;cursor:default}.ac-opt.on:disabled{opacity:1}
    .ac-wrap{gap:10px}
    .ac-wrap .ac-pv{gap:12px;padding:14px;border-radius:14px;background:var(--sunk);border:1px solid var(--line);font-size:13px}
    .ac-pv .ac-r{flex-direction:row;gap:10px;align-items:flex-start}
    .ac-pv .ac-r.off .ac-b,.ac-pv .ac-r.off .ac-n{opacity:.45}
    .ac-pv .ac-n{width:22px;height:22px;border-radius:6px;background:var(--raise);color:var(--t2);font-size:12px;font-weight:500}
    .ac-b .ac-k{font-size:13px;font-weight:600;color:var(--t1)}.ac-b .ac-v{font-size:13px;color:var(--t2)}
    .ac-sw{flex:none;display:flex;align-items:center;gap:6px;font-size:12px;color:var(--t2);white-space:nowrap;cursor:pointer;padding-top:1px}
    .ac-sw input{width:16px;height:16px;margin:0;padding:0;accent-color:var(--acc)}
    .ac-cf{font-size:12px;line-height:1.4;color:var(--t3)}
    .ac-tgl{color:var(--t2)}
    .ac-wl{display:flex;gap:8px;align-items:flex-start;font-size:13px;line-height:1.4;color:var(--warn);flex:none}.ac-wl>span:first-child{flex:none;margin-top:1px}
    .ac-wl[title]{cursor:help}.ac-why{color:var(--t3);text-decoration:underline dotted;text-underline-offset:2px;white-space:nowrap}
    .ac-need{font-size:13px;line-height:1.4}
    .card .row.acf{gap:8px}
    .card .acf .sq{flex:1;width:auto;height:48px;padding:0 12px;border-radius:12px;background:var(--sunk);color:var(--t1);font-size:15px;font-weight:500}
    .card .acf .go{flex:2;min-height:48px;border-radius:12px;font-size:15px}
    .card .acf .go2{height:48px;border-radius:12px;font-size:15px}
    /* ход действия: строка на шаг — готово / идёт / в очереди */
    .ac-run{display:flex;flex-direction:column;gap:10px;padding:14px;border-radius:14px;background:var(--sunk);border:1px solid var(--line);flex:none}
    .ac-run-h{display:flex;align-items:baseline;justify-content:space-between;gap:8px;font-size:14px;color:var(--t1)}
    .ac-run-l{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:6px;font-size:13px}
    .ac-run-l li{display:flex;justify-content:space-between;gap:10px;color:var(--t2)}.ac-run-l li.now{color:var(--t1)}
    .ac-run-l li .tx{min-width:0;overflow-wrap:anywhere}
    .ac-st{flex:none;font-size:12px;white-space:nowrap}
    .ac-run-l li.done .ac-st{color:var(--ok)}.ac-run-l li.now .ac-st,.ac-st.info{color:var(--ac-info-t)}.ac-run-l li.wait .ac-st{color:var(--t3)}
    .ac-foot{font-size:12px;color:var(--t3)}
    /* итог: каждая строка своим цветом и знаком справа; у строки — свои кнопки; внизу одна главная */
    .box.res{background:var(--sunk);border-radius:14px;gap:10px}
    .box.res.ok{border-color:color-mix(in srgb,var(--ok-line) 45%,var(--line))}.box.res.warn{border-color:var(--ac-warn-line)}.box.res.bad{border-color:var(--ac-bad-line)}
    .res-l{gap:8px}
    .res-l .ac-ln,.tst .ac-ln{display:grid;grid-template-columns:minmax(0,1fr) auto;column-gap:8px;row-gap:6px;align-items:start;font-size:13px;line-height:1.4;color:var(--t2)}
    .ac-ln .tx{grid-column:1;grid-row:1;min-width:0;overflow-wrap:anywhere}
    .ac-ln .mk{grid-column:2;grid-row:1;min-width:16px;text-align:center;font-weight:700}
    .ac-ln .ln-a{grid-column:1/-1;grid-row:2;display:flex;gap:6px;flex-wrap:wrap;align-items:center}
    .ac-ln.ok .mk{color:var(--ok)}.ac-ln.warn .mk{color:var(--warn)}.ac-ln.bad .mk{color:var(--bad)}.ac-ln.mut .mk{color:var(--t4)}
    .ac-ln.ok .tx{color:var(--t2)}.ac-ln.warn .tx{color:var(--warn)}.ac-ln.bad .tx{color:var(--bad)}.ac-ln.mut .tx{color:var(--t3)}
    .tst .ac-ln{font-size:12.5px}
    .res-a{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
    .box.res .sm,.box .res-a .sm,.ac-ln .sm{height:32px;padding:0 12px;border-radius:10px;border:1px solid var(--line);background:transparent;color:var(--t1);font-size:13px;font-weight:500;display:inline-flex;align-items:center;text-decoration:none}
    .box.res .sm.pri,.box .res-a .sm.pri{background:var(--acc);border-color:var(--acc);color:var(--on-acc);font-weight:600}
    .ac-ln .sm{height:28px;padding:0 10px;font-size:12.5px}
    .ac-ln .sm[data-ac-act="note"]{height:auto;padding:0 2px;border:0;color:var(--warn);text-decoration:underline;text-underline-offset:2px;background:transparent}
    .ac-crm{display:inline-flex;align-items:center;text-decoration:none}.ac-crm::after{content:'↗';margin-left:4px}
    .card .acf .go.quiet{background:transparent;border:1px solid var(--line);color:var(--t1);font-weight:500}.card .acf .go.quiet:hover{background:var(--sunk)}
    .card[tabindex="-1"]:focus{outline:none}
    .ac-tmore>summary{list-style:none;cursor:pointer;height:32px;display:inline-flex;align-items:center;padding:0 12px;border-radius:10px;border:1px dashed var(--line);color:var(--t2);font-size:13px}
    .ac-tmore>summary::-webkit-details-marker{display:none}.ac-tmore>summary:hover{color:var(--t1);border-color:var(--t4)}
    .ac-tmore[open]{flex-basis:100%}.ac-tmore-l{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
    /* карточка «есть заявка» / «Действия»: № крупно, метка статуса, прошлые заявки списком, «Открыть по номеру…» */
    .ex-upd{border:0;background:transparent;padding:0;color:inherit;font:inherit;cursor:pointer}.ex-upd:hover{color:var(--t1);text-decoration:underline}
    .card>.hd[data-ex-card] .exr-st{margin-left:0}
    .ex-foot{margin-top:-4px}
    .ex-follow{height:28px;display:inline-flex;align-items:center;gap:6px;padding:0 8px;margin-left:-8px;border:0;border-radius:8px;background:transparent;color:var(--t3);font-size:12px}
    .ex-follow:hover{color:var(--t1);background:var(--sunk)}.ex-follow.on{color:var(--ok)}.ex-follow:disabled{cursor:default}
    .exr-st.ac-pill{margin-left:auto;height:24px;padding:0 10px;font-size:12px}
    .ex-past{display:flex;flex-direction:column;gap:8px;padding:14px;border-radius:14px;background:var(--sunk);border:1px solid var(--line);flex:none}
    .ex-past>summary{list-style:none;cursor:pointer;display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:16px;font-weight:600;color:var(--t1);min-height:0;padding:0;background:transparent;letter-spacing:0;text-transform:none}
    .ex-past>summary::-webkit-details-marker{display:none}.ex-past[open]>summary{margin-bottom:4px}
    .ex-past>summary .cnt{font-size:13px;font-weight:500;color:var(--t3)}
    .ex-pw{display:flex;flex-direction:column;gap:6px}
    .ex-pr{display:flex;align-items:baseline;gap:8px;font-size:13px;min-width:0}
    .ex-pr .l{flex:none;color:var(--t1);font-variant-numeric:tabular-nums}
    .ex-pr .r{flex:1;min-width:0;text-align:right;color:var(--t3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .ex-pa{flex:none;height:24px;padding:0 4px;border:0;border-radius:6px;background:transparent;color:var(--t2);font-size:12px;text-decoration:underline;text-underline-offset:2px;cursor:pointer;display:inline-flex;align-items:center}
    .ex-pa:hover{color:var(--t1)}
    .ex-past .exr-grid{padding:8px 0 4px;border-top:1px dashed var(--line)}
    .ex-past .exr-man{border:0;background:transparent;padding:0;gap:6px}
    .ex-past .exr-man>summary{list-style:none;height:28px;display:inline-flex;align-items:center;padding:0 8px;margin-left:-8px;border-radius:8px;font-size:12px;color:var(--t2)}
    .ex-past .exr-man>summary::-webkit-details-marker{display:none}.ex-past .exr-man>summary:hover{background:var(--raise);color:var(--t1)}
    .exr-sel,.exr-num{height:40px}
    /* ===== /2.1 действия ===== */
    /* ===== 2.1 уведомления ===== */
    /* свои имена цветов: «сведения» (синий) и линии warn/bad/ok — из токенов темы, если они есть (--info…, --warn-line), иначе — тёмная тема LeadChat */
    .lcz{--n-info:var(--info,#6aa9f0);--n-info-bg:var(--info-bg,#0f1d2c);--n-info-line:var(--info-line,#23415f);--n-info-t:color-mix(in srgb,var(--n-info) 60%,#fff);
      --n-warn-line:var(--warn-line,#5b4721);--n-bad-line:color-mix(in srgb,var(--bad-line) 48%,var(--bg));--n-ok-line:color-mix(in srgb,var(--ok-line) 55%,var(--bg));
      --n-on-warn:#1b1302}
    /* уведомление: полоса слева, метка и время справа; фон и рамка — по виду */
    .toasts .tst{position:relative;padding:12px 14px 12px 28px;border-radius:14px;gap:6px;background:var(--raise)}
    .toasts .tst::before{content:'';position:absolute;left:12px;top:12px;bottom:12px;width:6px;border-radius:3px;background:var(--t4)}
    .toasts .tst.ok{background:var(--ok-bg);border-color:var(--n-ok-line)}.toasts .tst.ok::before{background:var(--acc)}
    .toasts .tst.warn{background:var(--warn-bg);border-color:var(--n-warn-line)}.toasts .tst.warn::before{background:var(--warn)}
    .toasts .tst.bad{background:var(--bad-bg);border-color:var(--n-bad-line)}.toasts .tst.bad::before{background:var(--bad-line)}
    .toasts .tst.info{background:var(--n-info-bg);border-color:var(--n-info-line)}.toasts .tst.info::before{background:var(--n-info)}
    .toasts .tst.tst-low::before{opacity:.6}
    .toasts .tst.tst-h{display:none}
    .tst .tst-k{min-height:20px;gap:8px;font-size:12px;font-weight:500;letter-spacing:0;text-transform:none;color:var(--t3)}
    .tst .tst-k .dot{display:none}
    .tst .tst-k .tst-l{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .tst .tst-tm{flex:none;margin-left:auto;font-size:12px;font-weight:400;color:var(--t3);font-variant-numeric:tabular-nums;white-space:nowrap}
    .tst .tst-k .x{margin-left:0;width:22px;height:22px}
    .tst .tst-t{font-size:14px;font-weight:600;line-height:1.35}
    .tst .tst-d{font-size:13px;line-height:1.45;color:var(--t2)}.tst .tst-d.ok{color:var(--ok)}.tst .tst-d.warn{color:var(--warn)}.tst .tst-d.bad{color:var(--bad)}.tst .tst-d.mut{color:var(--t3)}
    .tst .tst-q{background:color-mix(in srgb,var(--bg) 70%,transparent);border-color:color-mix(in srgb,var(--line) 70%,transparent);font-size:13px}
    .tst .tst-a{gap:8px;margin-top:4px}.tst .tst-a:empty{display:none}
    .tst .sm{height:32px;padding:0 12px;border-radius:10px;border:1px solid var(--line);background:transparent;color:var(--t1);font-size:13px;font-weight:500}
    .tst .sm:hover{border-color:var(--t4)}
    .tst .sm.pri{background:var(--acc);border-color:var(--acc);color:var(--on-acc);font-weight:600}
    .tst.warn .sm.pri{background:var(--warn);border-color:var(--warn);color:var(--n-on-warn)}.tst.warn .sm.pri:hover{background:color-mix(in srgb,var(--warn) 85%,#fff)}
    .tst.warn .sm:not(.pri):not(.ghost){border-color:var(--n-warn-line)}
    .tst.bad .sm.pri{background:transparent;border-color:var(--n-bad-line);color:var(--bad)}.tst.bad .sm.pri:hover{background:color-mix(in srgb,var(--bad-line) 14%,transparent)}
    .tst.info .sm.pri{background:var(--n-info);border-color:var(--n-info);color:#04111f}
    .tst .sm.later{border-color:transparent;color:var(--t3)}.tst .sm.later:hover{color:var(--t1);border-color:var(--line)}
    .tst .tst-r .sm{height:28px}
    .tst-det{font-size:12px;color:var(--t3)}.tst-det>summary{cursor:pointer;width:max-content}.tst-det>summary:hover{color:var(--t1)}
    .tst-det[open]>summary{margin-bottom:4px}.tst-det>div{overflow-wrap:anywhere;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11.5px}
    .tst-bar{display:flex;align-items:center;gap:8px;flex:none}.tst-bar:not(:has(>button:not([style*="none"]))){display:none}
    .tst-more{flex:1;min-width:0;height:32px;padding:0 12px;border-radius:10px;border:1px dashed var(--line);background:var(--bg);color:var(--t2);font-size:13px;
      white-space:nowrap;overflow:hidden;text-overflow:ellipsis;box-shadow:var(--sh2)}
    .tst-more:hover{color:var(--t1);border-color:var(--t4)}
    .tst-bar .tst-miss{align-self:center;height:32px;border-radius:10px}
    /* ход создания и итог: карточка со строками «что — состояние» (готово / сейчас / отправляю… / в очереди / не ушло) */
    .nx-card{background:var(--raise);border:1px solid var(--line);border-radius:14px;padding:14px;display:flex;flex-direction:column;gap:10px;flex:none}
    .nx-h{display:flex;align-items:baseline;justify-content:space-between;gap:8px}.nx-h b{font-size:15px;font-weight:600;color:var(--t1)}
    .nx-sum{font-size:12px;color:var(--t3);white-space:nowrap}
    .nx-steps li{display:flex;align-items:center;gap:10px}.nx-steps li .tx{flex:1;min-width:0;overflow-wrap:anywhere}
    .nx-steps .nx-s{flex:none;font-size:12px;color:var(--t3)}.nx-steps li.done .nx-s{color:var(--ok)}.nx-steps li.now .nx-s{color:var(--n-info-t)}
    .nx-lines{display:flex;flex-direction:column;gap:6px;font-size:13px}
    .nx-ln{display:flex;align-items:baseline;justify-content:space-between;gap:12px;min-width:0}
    .nx-ln .tx{flex:1;min-width:0;color:var(--t2);overflow-wrap:anywhere}.nx-ln .tx a{color:var(--acc)}
    .nx-ln .nx-s{flex:none;font-size:12.5px;color:var(--t3);white-space:nowrap}
    .nx-ln.ok .nx-s{color:var(--ok)}.nx-ln.info .nx-s{color:var(--n-info-t)}.nx-ln.warn .nx-s{color:var(--warn)}.nx-ln.bad .nx-s{color:var(--bad)}
    .nx-ln.mut .tx,.nx-ln.mut .nx-s{color:var(--t4)}
    .tst .nx-lines.sm{gap:2px;font-size:12.5px}.tst .nx-lines.sm .nx-ln .nx-s{font-size:12px}
    .nx-crm{flex:none;font-size:12px;font-weight:600;color:var(--ok);align-self:flex-start}
    .nx-todo{display:flex;flex-direction:column;gap:8px;flex:none}
    /* «Готовые»: шапка, фильтр из трёх, карточки готовых, строки «почти» */
    .rd{gap:12px}
    .rd-h{display:flex;align-items:center;gap:8px;flex:none}.rd-ht{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px}
    .rd-title{font-size:20px;font-weight:600;line-height:1.2;color:var(--t1)}.rd-sub{font-size:13px;color:var(--t3)}
    .rd-h .sm{flex:none;height:36px;padding:0 12px;border-radius:10px;border:1px solid var(--line);background:var(--sunk);color:var(--t1);font-size:13px;font-weight:500;cursor:pointer}
    .rd-h .sm:hover{border-color:var(--t4)}
    .rd-seg{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:4px;padding:3px;border-radius:10px;background:var(--sunk);border:1px solid var(--line);flex:none}
    .rd-seg-b{height:32px;border:0;border-radius:8px;background:transparent;color:var(--t3);font-size:13px;font-weight:500;padding:0 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .rd-seg-b:hover{color:var(--t1)}.rd-seg-b[aria-pressed="true"]{background:var(--raise);color:var(--t1);font-weight:600;box-shadow:0 1px 2px rgba(0,0,0,.2)}
    .rd-pane{display:flex;flex-direction:column;gap:8px;flex:none}.rd-pane[hidden]{display:none}
    .rd-empty{padding:18px 12px;text-align:center;font-size:13px;color:var(--t3);border:1px dashed var(--line);border-radius:14px}
    .rd .rd-list{border:0;background:transparent;overflow:visible;gap:8px}
    .rd .rd-list>.lst-h{padding:0 2px;background:transparent;border:0;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--t3)}
    .rd .rd-card{flex-direction:column;align-items:stretch;gap:8px;padding:12px 14px;min-height:0;border:1px solid var(--n-ok-line);border-radius:14px;background:var(--sunk)}
    .rd .rd-card .tt,.rd .rd-row .tt{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:14px}
    .rd .rd-card .ds{-webkit-line-clamp:1;font-size:13px;color:var(--t2)}.rd .rd-card .ds.warn,.rd .rd-row .ds.warn{color:var(--warn);-webkit-line-clamp:2}
    .rd-top{display:flex;align-items:baseline;justify-content:space-between;gap:8px;min-width:0}
    .rd-wait{flex:none;font-size:12px;color:var(--t3);white-space:nowrap}.rd-wait.w{color:var(--warn)}
    .rd-chips{display:flex;gap:6px;flex-wrap:wrap}.rd-chips:empty{display:none}
    .rd-chip{height:24px;padding:0 8px;border-radius:999px;background:var(--raise);font-size:12px;color:var(--t2);display:inline-flex;align-items:center;white-space:nowrap}
    .rd-chip.ok{background:var(--ok-bg);color:var(--ok)}.rd-chip.info{background:var(--n-info-bg);color:var(--n-info-t)}.rd-chip.warn{background:var(--warn-bg);color:var(--warn)}
    .rd-act{display:flex;gap:8px}
    .rd .rd-act .sm{height:36px;border-radius:10px;font-size:13px;min-width:0}.rd .rd-act .sm.pri{flex:1}
    .rd .rd-row{gap:10px;padding:12px 14px;min-height:0;border:1px solid var(--line);border-radius:14px;background:var(--sunk)}
    .rd-side{flex:none;display:flex;flex-direction:column;align-items:flex-end;gap:6px}
    .rd .rd-row .sm{height:36px;border-radius:10px;font-size:13px}
    .rd .lst-r .rd-wait:empty{display:none}
    /* полоска режима ИИ — сведения над стопкой */
    .lcz-mode{position:relative;display:flex;align-items:center;gap:8px;max-width:360px;padding:6px 6px 6px 22px;border-radius:10px;font-size:12.5px;line-height:1.4;
      border:1px solid var(--line);box-shadow:var(--sh2);background:var(--raise);color:var(--t2)}
    .lcz-mode::before{content:'';position:absolute;left:9px;top:7px;bottom:7px;width:4px;border-radius:2px;background:var(--warn)}
    .lcz-mode.warn{background:var(--warn-bg);border-color:var(--n-warn-line)}.lcz-mode.bad{background:var(--bad-bg);border-color:var(--n-bad-line)}.lcz-mode.bad::before{background:var(--bad-line)}
    .lcz-mode-t{flex:1;min-width:0}
    .lcz-mode>button{flex:none;border:0;background:transparent;color:var(--t3);font-size:15px;line-height:1;padding:2px 6px;cursor:pointer}.lcz-mode>button:hover{color:var(--t1)}
    /* карточка готовности: строка «что дальше» под заголовком */
    .cd-next{font-size:13px;line-height:1.4;padding:8px 10px;border-radius:10px;background:var(--sunk);color:var(--t2);border-left:4px solid var(--t4)}
    .cd-next.ok{border-left-color:var(--acc);color:var(--ok)}.cd-next.warn{border-left-color:var(--warn);color:var(--warn)}
    .card .ok-ic.warn{background:var(--warn-bg);color:var(--warn)}
    /* «Заявка уже создана»: статус сообщения словом, «Создать ещё одну» — ссылкой с подтверждением на месте */
    .plr .nx-s{margin-left:auto;flex:none;font-size:12px;color:var(--ok);white-space:nowrap}.plr.bad .nx-s{color:var(--bad)}.plr.mut .nx-s{color:var(--t4)}
    .nx-again{align-items:center;gap:8px;justify-content:center}
    .nx-again .sm{height:30px;padding:0 10px;border-radius:8px;border:1px solid var(--line);background:transparent;color:var(--t2);font-size:12.5px;cursor:pointer}
    .nx-again .sm.ghost{border-color:transparent;color:var(--t3);text-decoration:underline;text-underline-offset:2px}.nx-again .sm.ghost:hover{color:var(--t1)}
    /* ===== /2.1 уведомления ===== */
    /* ===== 2.1.1 ровные сетки: группы кнопок — одинаковой ширины и высоты, ровными рядами и колонками (просьба владельца 10.10).
       Подпись не обрезается: длинная («Комментарий филиала») — в две строки по центру, и тогда все ряды той же высоты ===== */
    .ag-pills{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));grid-auto-rows:1fr;gap:8px}                 /* тот же шаг, что у плиток: колонки на одних линиях */
    .ag-pills>.ag-s{width:100%;max-width:none;height:auto;min-height:40px;padding:4px 6px;border-radius:10px;display:flex;align-items:center;justify-content:center;
      text-align:center;white-space:normal;line-height:1.2;font-size:12.5px;overflow:hidden;text-overflow:clip;overflow-wrap:normal;hyphens:auto}
    .ag-pills>.ag-s .lb{white-space:normal;overflow:visible;text-overflow:clip}
    .ag-chips{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));grid-auto-rows:1fr;gap:6px}
    .ag-chips>.ag-chip{width:100%;height:auto;min-height:28px;padding:3px 8px;border-radius:8px;display:flex;align-items:center;justify-content:center;text-align:center;white-space:normal;line-height:1.2}
    .ac-tmore-l{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));grid-auto-rows:1fr;gap:6px}
    .ac-tmore-l>*{width:100%;min-width:0;height:auto;min-height:32px;justify-content:center;text-align:center;white-space:normal;line-height:1.2}
    .exr-row{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(0,1fr);gap:6px}
    .exr-row>*{min-width:0;justify-content:center;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
    /* «Добавится само» под комментарием — строками одной ширины, а не капсулами вразброс */
    .fz-tags{display:grid;grid-template-columns:minmax(0,1fr);gap:6px}
    .fz-tags>.fz-tag{display:flex;width:100%;border-radius:8px}
    /* ===== /2.1.1 ровные сетки ===== */
    /* 2.1.6 согласование: выбранные чаты, поиск */
    .opt.on{background:color-mix(in srgb,var(--acc) 10%,var(--bg))}
    .tg-found{display:flex;flex-direction:column;gap:6px}.tg-found:empty{display:none}
    input[data-tg="q"]{height:40px;border-radius:10px;padding:0 12px}
    .tg-acts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}.tg-acts.wide>.pri{grid-column:1/-1}.tg-acts>button{width:100%;min-width:0}
    /* ===== 2.3 компактная заявка (Claude Design «Лид-центр — компактно»: Create, CreateIssues, Ready, Notices) — панель 440, тёмная тема LeadChat.
       Что в порядке — строкой 40 px (метка 84 · значение и пояснение · ✎), раскрыто — только то, где нужно решение; одна главная кнопка внизу ===== */
    .ph.fm.cz{padding:12px 14px;gap:6px}
    .ph.fm.cz .top{align-items:center;gap:8px}
    .ph.fm.cz .t{font-size:16px;font-weight:600;line-height:1.25}
    .ph.fm.cz .sub{font-size:12px;margin-top:2px}
    .ph.fm.cz .seg{display:flex;padding:2px;gap:0;border-radius:10px;background:var(--sunk);border:1px solid var(--line);flex:none}
    .ph.fm.cz .seg button{height:34px;min-width:40px;padding:0 10px;border-radius:8px;font-size:12px;font-weight:500;color:var(--t2);background:transparent}
    .ph.fm.cz .seg button.on{background:var(--acc);color:var(--on-acc);font-weight:600;box-shadow:none}
    .ph.fm.cz .ib{width:40px;height:40px;border-radius:10px;border:1px solid var(--line);background:var(--sunk);color:var(--t2);flex:none}
    .ph.fm.cz .fz-dn,.ph.fm.cz .n{font-size:12px}
    .cz-more{position:relative;flex:none}
    .cz-more>summary{list-style:none;width:40px;height:40px;border-radius:10px;border:1px solid var(--line);background:var(--sunk);color:var(--t2);display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:16px;line-height:1;user-select:none}
    .cz-more>summary::-webkit-details-marker{display:none}
    .cz-more>summary:hover,.cz-more[open]>summary{color:var(--t1);border-color:var(--t4)}
    .cz-more>summary:focus-visible{outline:2px solid var(--acc);outline-offset:1px}
    .cz-menu{position:absolute;right:0;top:44px;z-index:5;min-width:210px;display:flex;flex-direction:column;padding:4px;border-radius:12px;background:var(--raise);border:1px solid var(--line);box-shadow:var(--sh2)}
    .cz-mi{min-height:40px;padding:6px 10px;border:0;border-radius:8px;background:transparent;color:var(--t1);font-size:13px;text-align:left;white-space:nowrap}
    .cz-mi:hover,.cz-mi:focus-visible{background:var(--sunk);outline:none}
    .pb.fm.cz{padding:8px 14px;gap:5px}
    /* полоса сверху: «Всё есть — проверьте и создайте» / «Осталось N: время визита, согласование» (пункты — к секции) */
    .cz-st{display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:10px;border:1px solid var(--line);font-size:13px;font-weight:500;line-height:1.4;flex:none}
    .cz-st>span:first-child{flex:none}
    .cz-st.ok{background:var(--ok-bg);border-color:color-mix(in srgb,var(--ok-line) 55%,var(--line));color:var(--ok)}
    .cz-st.warn{background:var(--warn-bg);border-color:var(--warn-line);color:var(--warn);align-items:flex-start}
    .cz-st.warn>span:first-child{margin-top:2px}
    .cz-st.mut{background:var(--sunk);color:var(--t3);min-height:36px}
    .cz-st-t{min-width:0}
    .cz-go{border:0;background:none;padding:0;color:inherit;font:inherit;text-decoration:underline;text-decoration-style:dotted;text-underline-offset:3px;cursor:pointer}
    .cz-go:hover,.cz-go:focus-visible{text-decoration-style:solid;outline:none}
    .cz-it.block .cz-go{font-weight:600}
    /* секция: строкой (метка · значение / пояснение · ✎) или раскрыта (заголовок, замечание справа, ▴) */
    .pb.fm .sec.cz{padding:0;gap:0;border-radius:10px;background:var(--sunk);border:1px solid var(--line)}
    .pb.fm .sec.cz.open{padding:10px;gap:8px;border-radius:12px}
    .pb.fm .sec.cz.open.warn{border-color:var(--warn-line)}
    .cz-row{display:grid;grid-template-columns:84px minmax(0,1fr) 40px;align-items:center;gap:8px;min-height:44px;padding:2px 2px 2px 10px;min-width:0}
    .cz-row[hidden],.cz-body[hidden],.cz-tg [hidden]{display:none!important}
    .cz-l{font-size:12px;color:var(--t3)}
    .cz-v{display:flex;flex-direction:column;gap:1px;min-width:0}
    .cz-v1{font-size:13px;font-weight:500;line-height:1.3;color:var(--t1);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-variant-numeric:tabular-nums}
    .cz-v2{font-size:11.5px;line-height:1.3;color:var(--t3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .cz-v2.warn{color:var(--warn)}.cz-v2 .st{font-size:inherit}.cz-v2 .st.ok,.cz-v2 .st.mut{color:var(--t3)}.cz-v2 .st.warn{color:var(--warn)}
    .cz-ed,.cz-up{width:40px;height:40px;border:0;border-radius:10px;background:transparent;color:var(--t3);display:flex;align-items:center;justify-content:center;padding:0;flex:none}
    .cz-ed:hover,.cz-up:hover,.cz-ed:focus-visible,.cz-up:focus-visible{background:var(--raise);color:var(--t1);outline:none}
    .cz-body{display:flex;flex-direction:column;gap:8px;min-width:0}
    .pb.fm .cz-body>.sh{align-items:center;min-width:0}
    .pb.fm .cz-body>.sh h3{font-size:13px;font-weight:600;flex:none}
    .cz-sh{display:flex;align-items:center;gap:2px;min-width:0;justify-content:flex-end}
    .pb.fm .cz-sh .st{max-width:none;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .cz-sh .cz-up{width:40px;height:40px}
    .pb.fm .cz-body input:not([type=checkbox]):not([type=radio]):not([type=hidden]),.pb.fm .cz-body select{height:40px;border-radius:10px;padding:0 10px;font-size:13px}
    .pb.fm .cz-body .f{font-size:11px;gap:3px}
    .pb.fm .cz-body .g2,.pb.fm .cz-body .g3{gap:6px}
    .pb.fm .cz-body .n{font-size:12px}
    .pb.fm .cz-body .box{font-size:12.5px;padding:8px 10px}
    .pb.fm .cz-body .cks .ck{height:32px;font-size:13px;border-radius:8px}
    .pb.fm .cz-body .tseg button{height:28px}
    .pb.fm .cz-body .fz-more{height:28px;font-size:12px}
    .cz-addr{display:grid;grid-template-columns:minmax(0,1fr) 60px 52px 64px 52px;gap:6px}
    /* визит: дни, часы 10–21 по 6 в ряд, :00/:30 и «как договорились» одной строкой, «Выбрано: …» */
    .cz-days{display:flex;gap:6px;flex-wrap:wrap}
    .cz-days .fz-qb{height:40px;padding:0 10px;border-radius:10px;font-size:12.5px;flex:none}
    .cz-hours{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:5px}
    .cz-hours .fz-qb{height:40px;border-radius:10px;font-size:13px}
    .cz-body .fz-qb.on{border-color:var(--acc);background:var(--ok-bg);color:var(--ok);font-weight:700}
    .cz-body .fz-qb.soft{color:var(--t4)}
    .cz-vrow{display:flex;align-items:center;gap:6px;justify-content:space-between;flex-wrap:wrap}
    .cz-vrow .fz-seg{display:flex;padding:2px;gap:0;border-radius:9px;background:var(--bg)}
    .cz-vrow .fz-seg button{height:36px;padding:0 10px;border-radius:8px;font-size:12px}
    .cz-vrow .fz-seg button.on,.cz-vrow .fz-seg button[aria-pressed="true"]{background:var(--raise);color:var(--t1);font-weight:600}
    .cz-sel{font-size:12px;color:var(--t2)}.cz-sel b{color:var(--t1);font-weight:600}
    .cz-notes{display:flex;flex-direction:column;gap:4px}.cz-notes:empty{display:none}
    .pb.fm .cz-body .fz-clock{padding:6px 10px}.pb.fm .cz-body .fz-clock b{font-size:16px}
    /* согласование одной кнопкой: «В «МНЧ Москва»: текст» и «Отправить в «…»»; «другой чат», «изменить текст» — прежнее окно */
    .cz-tg{display:flex;flex-direction:column;gap:8px}
    .cz-tg-t{padding:8px 10px;border-radius:10px;background:var(--bg);border:1px solid var(--line);font-size:12.5px;line-height:1.45;color:var(--t1);
      display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden;white-space:pre-line}
    .cz-tg-k{color:var(--t3)}
    .cz-tg-a{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
    .cz-tg-a .lk{color:var(--t2);font-size:12.5px;text-decoration-style:dotted;text-underline-offset:3px}
    .cz-tg-a .lk:hover{color:var(--t1)}
    /* «Сообщение» — последнее слово клиента, ↻ — прочитать заново; комментарий; «Добавится само: …» строкой */
    .cz-row.cz-msg{border:1px solid var(--line);border-radius:10px;background:var(--sunk);flex:none}
    .cz-cm{display:flex;flex-direction:column;gap:4px;margin-top:4px;flex:none}
    .cz-cm>.f{font-size:12px;color:var(--t3)}
    .pb.fm .cz-cm textarea{min-height:0;height:auto;resize:vertical;padding:8px 10px;border-radius:10px;font-size:13px;line-height:1.45;background:var(--sunk)}
    .pb.fm .sec.cz.lite:not(.open){background:transparent;border-color:transparent}
    .sec.cz.lite:not(.open) .cz-row{grid-template-columns:auto minmax(0,1fr) 40px;gap:4px;min-height:40px;padding:0 0 0 2px;align-items:center}
    .sec.cz.lite:not(.open) .cz-l{font-size:11.5px;line-height:1.45}.sec.cz.lite:not(.open) .cz-l::after{content:':'}
    .sec.cz.lite:not(.open) .cz-v1{font-size:11.5px;font-weight:400;color:var(--t3);white-space:normal;line-height:1.45}
    .sec.cz.lite .cz-ed{width:40px;height:40px}
    .sec.cz.ad-review{border-color:var(--warn-line)}
    .sec.cz.ad-review .cz-v2{color:var(--warn)}
    .ad-link{display:inline-flex;align-items:center;gap:6px;align-self:flex-start;min-height:40px;padding:6px 10px;border:1px solid var(--line);border-radius:10px;text-decoration:none;font-size:13px}
    .ad-link:hover{border-color:var(--acc)}
    .cz-v1 .fz-tags{display:inline}
    .cz-v1 .fz-tags>.fz-tag,.cz-v1 .fz-tag{display:inline;width:auto;height:auto;padding:0;border:0;border-radius:0;background:none;font-size:inherit;color:inherit;white-space:normal}
    .cz-v1 .fz-tag.bad{color:var(--bad)}
    /* футер: «После создания: …» строкой, пояснение ситуации, главная кнопка с надписью по ситуации (или две — варианты), «или Ctrl+Enter» */
    .pf.fm.cz{padding:10px 14px 14px;gap:8px}
    .pf.fm.cz .post{gap:4px;margin:0}
    .pf.fm.cz .post .ck{font-size:12.5px;color:var(--t2);align-items:flex-start;line-height:1.4}
    .pf.fm.cz .post .ck input{margin-top:1px;flex:none}
    .pf.fm.cz .post .n{font-size:12px}
    .cz-main{display:flex;flex-direction:column;gap:6px}
    .cz-mn{font-size:12.5px;line-height:1.4;color:var(--t2)}.cz-mn a{color:var(--ok)}
    .pf.fm.cz .go{min-height:44px;height:auto;padding:6px 12px;border-radius:12px;font-size:15px;font-weight:700;line-height:1.25}
    .pf.fm.cz .go.long{font-size:13.5px}.pf.fm.cz .go.warn{background:var(--warn);color:#1b1302}.pf.fm.cz .go.warn:hover{background:color-mix(in srgb,var(--warn) 85%,#fff)}
    .cz-main .row.two{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
    .cz-main .row.two .go,.cz-main .row.two .go2{min-height:44px;height:auto;padding:6px 10px;font-size:13.5px;line-height:1.25}
    .panel :is(button,a,summary):focus-visible{outline:2px solid var(--acc);outline-offset:2px}
    .panel .post .ck{min-height:40px;cursor:pointer}
    @media(max-width:420px){
      .ph.fm.cz .top{flex-wrap:wrap}.ph.fm.cz .ttl{flex-basis:calc(100% - 112px)}
      .ph.fm.cz .seg{order:4;width:100%;justify-content:center}
      .cz-row{grid-template-columns:72px minmax(0,1fr) 40px;gap:6px}
      .cz-addr{grid-template-columns:repeat(2,minmax(0,1fr))}.cz-addr>:first-child{grid-column:1/-1}
      .cz-hours{grid-template-columns:repeat(4,minmax(0,1fr))}.cz-main .row.two{grid-template-columns:1fr}
    }
    @media(prefers-reduced-motion:reduce){.lcz *,.lcz *::before,.lcz *::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
    .cz-kb{text-align:center;font-size:11.5px;color:var(--t3);line-height:1.35}
    /* «Готовые» 2.3: строки 2 линии + кнопка справа, заголовки списков «Можно создать · N», «Остальные (N) ▾», автоприём строкой */
    .ph.rd-ph{padding:12px 14px;gap:0}
    .ph.rd-ph .top{align-items:center;gap:8px}
    .ph.rd-ph .t{font-size:16px;font-weight:600;display:flex;align-items:center;gap:6px}
    .ph.rd-ph .sub{font-size:12px}
    .ph.rd-ph .ib{width:32px;height:32px;border-radius:9px;border:1px solid var(--line);background:var(--sunk);color:var(--t2);flex:none}
    .ph.rd-ph .ib svg{width:14px;height:14px}
    .pb.rd{padding:10px 14px;gap:6px}
    .rd .rd-list{gap:6px}
    .rd .rd-list>.lst-h{padding:0 2px;margin-top:2px;justify-content:flex-start;gap:0;font-size:12px}
        .rd .lst-r.rd-card,.rd .lst-r.rd-row{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:10px;padding:8px 8px 8px 12px;min-height:0;border-radius:11px;background:var(--sunk);border:1px solid var(--line);flex-direction:row}
    .rd .lst-r .tx{display:flex;flex-direction:column;gap:2px;min-width:0}
    .rd-who{display:flex;gap:6px;align-items:baseline;min-width:0}
    .rd-name{border:0;background:none;padding:0;color:var(--t1);font:inherit;font-size:13px;font-weight:600;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
    .rd-name:hover{text-decoration:underline}
    .rd-who b.tt{font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
    .rd-ch{flex:none;font-size:12px;color:var(--t3);white-space:nowrap}
    .rd-who .rd-wait{margin-left:auto;font-size:11.5px}
    .rd .lst-r .ds{font-size:12.5px;color:var(--t2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block;-webkit-line-clamp:unset}
    .rd .lst-r .ds.mut{color:var(--t3);font-size:12px}.rd .lst-r .ds.warn{color:var(--warn)}
    .rd .lst-r>.sm{height:34px;padding:0 14px;border-radius:10px;font-size:13px;min-width:0}
    .rd .lst-r>.sm.pri{font-weight:700}.rd .lst-r>.sm:not(.pri){background:transparent}
    .rd-rest{border:0;background:transparent;overflow:visible}
    .rd-rest>.rd-rest-s{list-style:none;cursor:pointer;display:flex;align-items:baseline;gap:8px;height:auto;min-height:32px;padding:6px 10px;border-radius:9px;color:var(--t2);font-size:12.5px;text-transform:none;letter-spacing:0;background:transparent;font-weight:500}
    .rd-rest>.rd-rest-s::-webkit-details-marker{display:none}
    .rd-rest>.rd-rest-s>span:first-child::after{content:' ▾';color:var(--t3)}.rd-rest[open]>.rd-rest-s>span:first-child::after{content:' ▴'}
    .rd-rest>.rd-rest-s .ds{color:var(--t3);font-weight:400;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .rd-rest>.rd-rest-s:hover{background:var(--sunk);color:var(--t1)}
    .rd-rest[open]{border:1px solid var(--line);border-radius:11px;background:var(--bg)}
    .rd-div{flex:1 1 auto;min-height:4px}
    .rd-auto{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:11px;background:var(--sunk);border:1px solid var(--line);font-size:12.5px;color:var(--t2);flex:none}
    .rd-auto>span{flex:1;min-width:0}.rd-auto b{color:var(--t1);font-weight:600}.rd-auto b.ok{color:var(--ok)}
    .rd-auto .sm{flex:none;height:30px;padding:0 10px;border:1px solid var(--line);border-radius:9px;background:transparent;color:var(--t2);font-size:12.5px}
    .rd-auto .sm:hover{color:var(--t1);border-color:var(--t4)}
    /* ===== /2.3 компактная заявка ===== */
    /* LeadChat operations design: one compact hierarchy across every surface. */
    .lcz{font-family:var(--lc-font,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif);font-size:13px;line-height:1.45;
      --radius:8px;--radius-panel:12px;--focus:var(--acc);font-variant-numeric:tabular-nums}
    .lcz :is(button,a,summary,input,select,textarea){-webkit-tap-highlight-color:transparent}
    .lcz :is(button,a,summary){transition:background-color 120ms ease,border-color 120ms ease,color 120ms ease,box-shadow 120ms ease}
    .lcz :is(button,a,summary):focus-visible{outline:2px solid var(--focus);outline-offset:2px}
    .lcz button:not(:disabled):active{filter:brightness(.94)}
    .lcz button:disabled{cursor:not-allowed;opacity:.55;filter:none}
    .lcz :is(input,textarea)::placeholder{color:var(--t3);opacity:1}
    .lcz :is(input,select,textarea):disabled{color:var(--t3);background:var(--sunk);cursor:not-allowed}
    .lcz :is(button,summary){overflow-wrap:anywhere}
    .panel{height:100dvh;max-height:100dvh;width:440px;isolation:isolate}
    .ph,.ph.fm,.ph.fm.cz,.ph.rd-ph{padding:12px 14px;gap:8px;background:var(--bg)}
    .ph .top,.ph.fm .top{align-items:center;min-width:0}
    .ph .t,.ph.fm .t,.ph.fm.cz .t,.ph.rd-ph .t{font-size:16px;line-height:1.3;font-weight:650;letter-spacing:-.015em}
    .ph .sub,.ph.fm .sub{font-size:12px;line-height:1.4;color:var(--t3)}
    .ph .ib,.ph.fm .ib,.ph.fm.cz .ib,.ph.rd-ph .ib,.cz-more>summary{width:40px;height:40px;border-radius:8px;border:1px solid var(--line);background:transparent}
    .pb,.pb.fm,.pb.fm.cz,.pb.rd{padding:12px 14px;gap:8px;overscroll-behavior:contain;scrollbar-gutter:stable;scroll-padding-block:12px}
    .pf,.pf.fm,.pf.fm.cz{padding:10px 14px max(12px,env(safe-area-inset-bottom));gap:8px;flex-shrink:0;background:var(--bg)}
    .go,.go2,.pf.fm .go,.pf.fm.cz .go,.sq{border-radius:8px;min-height:44px;height:auto;padding:8px 12px;font-size:14px;line-height:1.35;font-weight:600}
    .sq{flex-shrink:0;padding:8px}
    .go{box-shadow:inset 0 0 0 1px rgba(0,0,0,.08)}
    .go2{background:transparent}
    .seg,.ph.fm .seg,.ph.fm.cz .seg,.tseg,.fz-seg,.rd-seg{border-radius:8px;padding:3px;gap:3px;background:var(--sunk);border:1px solid var(--line)}
    .seg button,.ph.fm .seg button,.ph.fm.cz .seg button,.tseg button,.fz-seg button,.rd-seg-b{min-height:36px;height:auto;border-radius:5px;font-size:12.5px;padding:6px 8px;line-height:1.3;white-space:normal}
    .seg button.on,.ph.fm .seg button.on,.ph.fm.cz .seg button.on,.rd-seg-b[aria-pressed="true"]{background:var(--raise);color:var(--t1);box-shadow:inset 0 -2px var(--acc);font-weight:600}
    .lcz .chip,.lcz .fc,.lcz .fz-tag,.lcz .rd-chip{height:auto;min-height:22px;max-width:100%;padding:2px 7px;border-radius:5px;margin-left:0;font-size:11.5px;line-height:1.35;white-space:normal;overflow-wrap:anywhere}
    .sec,.pb.fm .sec{border-radius:8px;padding:12px;gap:8px;background:var(--bg)}
    .sh h3,.set-h h3,.cap,.pb.fm .sh h3{font-size:12px;font-weight:650;line-height:1.4;letter-spacing:0;text-transform:none;color:var(--t2)}
    .pb.fm .sec.cz{border-radius:8px;background:transparent}
    .pb.fm .sec.cz.open{border-radius:8px;background:var(--sunk);padding:10px;gap:8px}
    .cz-row{grid-template-columns:76px minmax(0,1fr) 40px;min-height:48px;padding-left:10px}
    .cz-l{font-size:12px;color:var(--t3)}
    .cz-v1{font-size:13px;font-weight:500;white-space:normal;overflow:visible;overflow-wrap:anywhere;line-height:1.4}
    .cz-v2{font-size:12px;white-space:normal;overflow:visible;overflow-wrap:anywhere;line-height:1.4}
    .cz-ed,.cz-up{border-radius:6px}
    .cz-row.cz-msg{background:var(--sunk);border-radius:8px}
    .pb.fm .cz-body .f,.pb.fm .f{font-size:12px;line-height:1.4;color:var(--t2);gap:4px}
    .pb.fm .cz-body :is(input:not([type=checkbox]):not([type=radio]):not([type=hidden]),select),.pb.fm :is(input:not([type=checkbox]):not([type=radio]):not([type=hidden]),select){height:40px;border-radius:6px;font-size:13px;padding:0 10px}
    .pb.fm textarea,.pb.fm .cz-cm textarea,input,select,textarea{border-radius:6px}
    .cz-addr{grid-template-columns:minmax(0,1fr) 56px 48px 60px 48px}
    .pb.fm .cz-body .cks .ck,.pb.fm .cks .ck{min-height:40px;height:auto;border-radius:6px;padding:6px 8px;font-size:12.5px;white-space:normal}
    .cks .ck>span{overflow:visible;text-overflow:clip;overflow-wrap:anywhere}
    .ck input{flex-shrink:0}.ck{min-height:32px}
    .pb.fm .cz-body .tseg button,.pb.fm .cz-body .fz-more{min-height:36px;height:auto}
    .cz-body .sh,.sh{flex-wrap:wrap}
    .pb.fm .cz-sh .st,.sh .st{white-space:normal;overflow-wrap:anywhere}
    .cz-sh{margin-left:auto}
    .cz-st,.fs,.fz-terr,.box,.pb.fm .box{border-radius:7px;font-size:12.5px;line-height:1.5;overflow-wrap:anywhere}
    .cz-st{padding:8px 10px}
    .cz-st.bad{background:var(--bad-bg);color:var(--bad);border-color:var(--bad-line);align-items:flex-start}
    .box.warn,.box.bad,.box.ok{border-left-width:3px}
    .cz-tg-t{display:block;max-height:150px;overflow:auto;-webkit-line-clamp:unset;border-radius:6px;overflow-wrap:anywhere}
    .fz-clock,.pb.fm .cz-body .fz-clock{border:0;border-radius:0;background:transparent;padding:4px 0}
    .fz-clock b{font-size:18px}
    .fz-qb,.cz-days .fz-qb,.cz-hours .fz-qb,.tq-t,.tp-b,.dq-d{border-radius:6px;min-height:40px}
    .cz-days .fz-qb{flex:1;white-space:normal;min-width:70px}
    .cz-notes,.cz-mn,.fz-foot,.cz-kb{overflow-wrap:anywhere}
    .cz-menu{border-radius:9px;max-width:calc(100vw - 28px);padding:4px}
    .cz-mi{border-radius:5px;white-space:normal;line-height:1.4}
    .ag{gap:8px}.ag-tiles{gap:6px}
    .ag-t{min-height:52px;height:auto;flex-direction:row;gap:6px;padding:8px;border-radius:7px;font-size:12.5px;line-height:1.35}
    .ag-t .lb,.ag-s .lb{white-space:normal;overflow:visible;text-overflow:clip;overflow-wrap:anywhere}
    .ag-sm{grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}
    .ag-s{min-height:40px;height:auto;padding:6px;border-radius:6px;font-size:12px;line-height:1.35}
    .ag-more>summary{min-height:40px;height:auto;border-style:solid;border-radius:7px;padding:8px}
    .ag-chip{min-height:32px;height:auto;padding:5px 9px;border-radius:6px;font-size:12px}
    .ag-hint{border-radius:4px;top:-6px;font-size:10px;max-width:calc(100% - 12px)}
    .card{border-radius:12px;right:16px;max-width:calc(100vw - 32px);overscroll-behavior:contain;scrollbar-width:thin}
    .card:has(>.hd[data-act-card]),.card:has(>.hd[data-ex-card]){width:420px;gap:10px;background:var(--bg);border-radius:12px}
    .card:has(>.hd[data-act-key="edit"]){top:16px;bottom:16px;max-height:calc(100dvh - 32px);width:440px}
    .card>.hd[data-act-card],.card>.hd[data-ex-card],.card .row.acf{background:var(--bg);padding-top:10px;padding-bottom:10px}
    .card .ttl .tt{font-size:15px;overflow-wrap:anywhere}
    .card .ttl .sub{white-space:normal;overflow-wrap:anywhere;line-height:1.4}
    .card .acf .go,.card .acf .go2,.card .acf .sq{border-radius:8px;min-height:44px;height:auto;font-size:13px;line-height:1.35;padding:8px 10px}
    .card .f>input,.card .f>select,.card .f>textarea{border-radius:6px;background:var(--bg)}
    .ac-opt{border-radius:7px;min-height:60px;padding:10px}.ac-opt b{font-size:13px}.ac-opt .ds{font-size:12px}
    .ac-hint,.aw,.swl,.rl,.ac-wrap .ac-pv,.ac-run,.exr,.ex-past,.box.res,.nx-card,.hero,.win{border-radius:8px;padding:10px 12px;gap:8px}
    .ac-wrap .ac-pv,.ac-run,.ex-past,.nx-card,.hero{background:transparent;border:0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);border-radius:0;padding:12px 0}
    .ac-wrap .ac-pv .ac-r+.ac-r{border-top:1px solid var(--line);padding-top:8px}
    .swl,.rl{padding:0;gap:0}.ck.swr{min-height:48px;padding:8px 10px}
    .ac-tgl,.ac-c1{white-space:normal;overflow-wrap:anywhere}
    .ac-ed,.ac-other,.ac-tmore>summary,.ex-follow,.ex-pa,.ex-past .exr-man>summary{min-height:36px;height:auto}
    .exr-a,.act{min-height:48px;height:auto;padding:8px 6px;border-radius:7px;font-size:12px;line-height:1.4}
    .exr-st{white-space:normal;overflow-wrap:anywhere;border-radius:5px}
    .exr-say,.exr-man{border-radius:7px}
    .ex-past>summary{font-size:13px;min-height:36px}
    .ex-pr{flex-wrap:wrap}.ex-pr .r{white-space:normal;overflow-wrap:anywhere}
    .jr{padding:10px 0;gap:10px;line-height:1.5;overflow-wrap:anywhere}
    .jr>*{min-width:0}.jt{flex-shrink:0;min-width:42px;font-size:12px}
    .rd .rd-list{gap:0;border-top:1px solid var(--line)}
    .rd .lst-r.rd-card,.rd .lst-r.rd-row{padding:10px 2px;gap:10px;border:0;border-bottom:1px solid var(--line);border-radius:0;background:transparent}
    .rd .lst-r:hover{background:var(--sunk)}
    .rd .lst-r .ds{white-space:normal;overflow:visible;line-height:1.4;overflow-wrap:anywhere}
    .rd .lst-r>.sm{min-height:40px;height:auto;padding:7px 10px;border-radius:6px;white-space:normal;max-width:112px;line-height:1.35}
    .rd-who{flex-wrap:wrap;gap:2px 6px}.rd-name,.rd-who b.tt{white-space:normal;overflow-wrap:anywhere}
    .rd-who .rd-wait{margin-left:0}.rd-ch{font-size:11.5px}
    .rd-auto{border-radius:7px;padding:8px 10px;line-height:1.45}
    .rd-auto .sm{min-height:36px;height:auto;border-radius:6px}
    .rd-empty{border:0;border-block:1px solid var(--line);border-radius:0;padding:24px 12px;line-height:1.6}
    .rd-rest>.rd-rest-s{min-height:40px;align-items:center;flex-wrap:wrap}
    .rd-rest>.rd-rest-s .ds{white-space:normal;overflow-wrap:anywhere}
    .toasts .tst{padding:10px 12px 10px 20px;border-radius:9px;gap:6px;max-height:min(70dvh,560px);overflow:auto;overscroll-behavior:contain}
    .toasts .tst::before{left:7px;top:12px;bottom:12px;width:3px;border-radius:2px}
    .tst .tst-k{font-size:11.5px}.tst .tst-t{font-size:13px;line-height:1.45}
    .tst .tst-k .x{width:36px;height:36px;flex-shrink:0;border-radius:6px}
    .tst .tst-q{background:transparent;border:0;border-left:2px solid var(--line);border-radius:0;padding:4px 0 4px 10px;font-size:12.5px}
    .tst .sm,.tst .tst-r .sm,.tst .sm.ghost{min-height:36px;height:auto;white-space:normal;border-radius:6px;padding:6px 10px;line-height:1.35}
    .tst .sm.ghost{padding-inline:4px}.tst-det>summary{min-height:36px;max-width:100%;width:auto;display:flex;align-items:center}
    .toasts .tst.tst-c{min-height:40px;height:auto;padding:8px 12px 8px 20px}.toasts .tst.tst-c .tst-t{white-space:normal}
    .tst-more,.tst-bar .tst-miss,.tst-miss{min-height:36px;height:auto;border-radius:7px}
    .bar{background:var(--acc);animation:lczb2 1.2s ease-in-out infinite}
    .pill.ready{animation:none;box-shadow:0 0 0 2px color-mix(in srgb,var(--acc) 30%,transparent)}
    .cal,.tp{border-radius:10px;max-width:calc(100vw - 24px);max-height:calc(100dvh - 24px);overflow:auto;overscroll-behavior:contain}
    .cal-n{width:40px;height:40px}.cal-q{min-height:36px;height:auto;white-space:normal}.cal-d{min-height:36px}
    .manual-confirm-backdrop{position:absolute;inset:0;z-index:30;display:flex;align-items:center;justify-content:center;padding:14px;background:rgba(0,0,0,.48)}
    .manual-confirm{display:flex;flex-direction:column;gap:12px;width:100%;max-height:100%;min-height:0;overflow:hidden;padding:16px;background:var(--bg);border:1px solid var(--warn-line);border-radius:12px;box-shadow:var(--sh);color:var(--t1);font-size:13px;line-height:1.45}
    .manual-confirm :is(h2,h3),.manual-confirm-title{margin:0;font-size:16px;line-height:1.35;font-weight:650;overflow-wrap:anywhere}
    .manual-confirm-summary{display:grid;grid-template-columns:70px minmax(0,1fr);gap:4px 10px;margin:0;padding-block:10px;border-block:1px solid var(--line);font-size:12px;flex-shrink:0}
    .manual-confirm-summary dt{color:var(--t3)}.manual-confirm-summary dd{margin:0;overflow-wrap:anywhere;color:var(--t1)}
    .manual-confirm-list{margin:0;padding:0 4px 0 24px;min-height:48px;overflow:auto;overscroll-behavior:contain;scrollbar-width:thin;color:var(--bad);line-height:1.5;overflow-wrap:anywhere}
    .manual-confirm-list li+li{margin-top:8px}.manual-confirm-list li::marker{font-weight:650}
    .manual-confirm-note{margin:0;color:var(--t2);font-size:12px;line-height:1.45;overflow-wrap:anywhere;flex-shrink:0}
    .manual-confirm-actions{display:grid;grid-template-columns:1fr 1.4fr;gap:8px;flex-shrink:0;padding-top:10px;border-top:1px solid var(--line)}
    .manual-confirm-actions button{min-height:44px;height:auto;border-radius:7px;padding:8px 10px;font-size:13px;line-height:1.35;white-space:normal}
    @media(max-width:420px){
      .ph,.ph.fm,.ph.fm.cz,.pb,.pb.fm,.pb.fm.cz,.pb.rd{padding-inline:12px}
      .pf,.pf.fm,.pf.fm.cz{padding-inline:12px}
      .cz-row{grid-template-columns:68px minmax(0,1fr) 40px;gap:6px}
      .cz-addr{grid-template-columns:repeat(2,minmax(0,1fr))}.cz-addr>:first-child{grid-column:1/-1}
      .ag-tiles,.ag-sm,.exr-acts{grid-template-columns:repeat(2,minmax(0,1fr))}
      .g3{grid-template-columns:repeat(2,minmax(0,1fr))}.g3>:last-child{grid-column:1/-1}
      .rd .lst-r.rd-card,.rd .lst-r.rd-row{gap:8px}.rd .lst-r>.sm{max-width:96px}
      .manual-confirm-backdrop{padding:10px}.manual-confirm{padding:12px;gap:10px}
    }
    @media(max-height:600px){
      .ph,.ph.fm,.ph.fm.cz,.pf,.pf.fm,.pf.fm.cz{padding-block:8px}
      .card,.card.top{top:12px;bottom:auto;max-height:calc(100dvh - 24px)}
      .manual-confirm{gap:8px;padding:12px}.manual-confirm-summary{padding-block:6px;gap:2px 8px}
      .manual-confirm-note{font-size:11.5px}.manual-confirm-actions{padding-top:8px}
    }
    @media(prefers-reduced-motion:reduce){.lcz *,.lcz *::before,.lcz *::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}}

    .act-editor{display:flex;flex-direction:column;gap:10px;min-width:0;padding:12px 0;border-block:1px solid var(--line)}
    .act-quick{display:flex;flex-wrap:wrap;gap:6px;min-width:0}
    .act-quick button{min-height:40px;height:auto;flex:1 1 110px;padding:8px 10px;border:1px solid var(--line);border-radius:7px;background:transparent;color:var(--t1);font-size:12.5px;line-height:1.4;white-space:normal}
    .act-quick button:hover:not(:disabled){background:var(--sunk);border-color:var(--t3)}
    .act-quick button[aria-pressed="true"]{background:var(--ok-bg);border-color:var(--ok-line);color:var(--ok)}
    .act-field-summary{font-size:12.5px;line-height:1.5;color:var(--t2);overflow-wrap:anywhere;min-width:0}
    .act-field-summary b{font-weight:600;color:var(--t1)}
    /* Карточка: спокойные поверхности, крупные цели нажатия, минимум визуального шума. */
    .pb.fm.cz{gap:7px;scrollbar-gutter:stable;-webkit-font-smoothing:antialiased}
    .pb.fm .sec.cz{border-radius:12px;transition:border-color 120ms ease,background-color 120ms ease,box-shadow 120ms ease}
    .sec.cz:not(.open)>.cz-row{cursor:pointer;min-height:48px}
    .sec.cz:not(.open):hover{border-color:var(--t4);background:var(--raise)}
    .sec.cz:focus-within{box-shadow:0 0 0 1px color-mix(in srgb,var(--acc) 50%,transparent)}
    .cz-ed,.cz-up{width:44px;height:44px;border-radius:9px}
    .cz-ed:focus-visible,.cz-up:focus-visible{outline:2px solid var(--acc);outline-offset:-3px}
    .cz-row{grid-template-columns:72px minmax(0,1fr) 44px}
    .cz-v1{font-weight:550;line-height:1.4}.cz-v2{line-height:1.4}
    .cz-body>.sh h3{letter-spacing:.01em;text-wrap:balance}
    .cz-body .box,.cz-tg,.cz-mn{text-wrap:pretty}
    .tg-acts button{min-height:40px;line-height:1.3;white-space:normal}
    .cz-tg-t{border-radius:8px;-webkit-line-clamp:3}
    .pf.fm.cz{border-top:1px solid var(--line);box-shadow:0 -8px 20px #0000000c}
    .panel :is(button,input,select,textarea){font-variant-numeric:tabular-nums}
    .panel button:not(:disabled):active{filter:brightness(.94)}
    @media(max-width:420px){.cz-row{grid-template-columns:62px minmax(0,1fr) 44px;gap:6px}.pb.fm.cz,.pf.fm.cz{padding-inline:10px}}

  `;
  const I = {
    check: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5L20 7"/></svg>',
    warn: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>',
    list: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/></svg>',
    gear: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>',
    close: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    chev: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 6 6 6-6 6"/></svg>',
    edit: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h4L19 9l-4-4L4 16v4z"/></svg>',
    up: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 15 6-6 6 6"/></svg>',
    cal: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>',
    stop: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="m15 9-6 6M9 9l6 6"/></svg>',
    redo: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/></svg>',
    pin: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/></svg>',
    link: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/></svg>',
    ext: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 4h6v6M20 4l-9 9"/><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/></svg>',
    clip: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 4h6v3H9z"/><path d="M9 5H6a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V6a1 1 0 0 0-1-1h-3"/><path d="M12 11v6M9 14h6"/></svg>',
  };
  const svg = (name, big) => { const s = document.createElement('span'); s.style.display = 'inline-flex'; s.innerHTML = big ? I[name].replace(/width="1[46]" height="1[46]"/, 'width="22" height="22"') : I[name]; return s; };

  /* ---------- оболочка (Shadow DOM — стили LeadChat и наши не мешают друг другу) ---------- */
  const host = document.createElement('div');
  host.style.cssText = 'position:fixed;z-index:2147483000;right:0;top:0;width:0;height:0';
  document.documentElement.appendChild(host);
  const root = host.attachShadow({ mode: 'open' });
  root.innerHTML = `<style>${CSS}</style><div class="lcz"><div class="card" role="dialog" aria-label="Заявку можно создавать"></div>
    <button class="pill fab" title="Собрать заявку из этого диалога"></button>
    <button class="pill rb" title="«Входящие»: готовые к созданию диалоги и автоприём">✓ Готовые</button>
    <aside class="panel" aria-label="Заявка в CRM"></aside><div class="toasts" aria-live="polite"></div></div>`;
  const fab = root.querySelector('.fab');
  const panel = root.querySelector('.panel');
  const card = root.querySelector('.card');
  const toasts = root.querySelector('.toasts');
  const readyBtn = root.querySelector('.rb');
  const personalBtn = document.createElement('button');
  personalBtn.type='button';personalBtn.id='lcz-personal-launch';personalBtn.className='lc-rail__item';
  personalBtn.setAttribute('aria-label','Личный помощник');personalBtn.setAttribute('data-tip','Личный помощник');
  personalBtn.title='Личный помощник · открыть отдельную вкладку';
  personalBtn.innerHTML='<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z"/><path d="M20 2v4m-2-2h4"/></svg><span class="lc-rail__label">Помощник</span>';
  personalBtn.addEventListener('click',()=>openAssistant().catch(e=>alertBox(String(e?.message||e))));
  const handoffBtn=document.createElement('button');
  handoffBtn.type='button';handoffBtn.className='lc-rail__item';handoffBtn.id='lcz-assistant-handoff';
  handoffBtn.textContent='Передать боту';handoffBtn.title='Передать выбранный диалог боту';
  handoffBtn.addEventListener('click',()=>handoffDialog().catch(e=>alertBox(String(e?.message||e))));
  const mountPersonalLauncher=()=>{
    handoffBtn.disabled=!convIdNow();
    if(личнаяВкладка||personalBtn.isConnected)return;
    const nav=document.querySelector('nav.lc-rail[aria-label="Основная навигация"]');
    const chats=nav&&[...nav.querySelectorAll('.lc-rail__zone a[href]')].find(a=>{try{return new URL(a.href,location.origin).pathname==='/chats'}catch(_e){return false}});
    if(chats){chats.after(personalBtn);personalBtn.after(handoffBtn)}
  };
  mountPersonalLauncher();
  if(!личнаяВкладка)new MutationObserver(mountPersonalLauncher).observe(document.documentElement,{childList:true,subtree:true});
  readyBtn.addEventListener('click', () => { if (panel.classList.contains('open') && READY.at && !S) { closePanel(); return; } showReady(); });
  // не выше половины экрана: стопка не закрывает список диалогов LeadChat (лишнее — прокруткой, новое — внизу)
  toasts.style.cssText = 'position:fixed;left:12px;bottom:12px;display:flex;flex-direction:column;gap:8px;max-width:368px;max-height:50vh;overflow-y:auto;padding:4px;z-index:2147483001';
  fab.style.display = 'none';

  /* 2.0.1: свой календарь для всех полей даты (форма заявки, перенос, действия): месяц сеткой, сегодня/завтра одним нажатием.
     Само поле остаётся (можно и напечатать дату) — календарь только ставит значение и шлёт input/change, как ввод с клавиатуры */
  (function календарь() {
    const МЕС = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];
    const НЕД = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
    const iso = (d) => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    // «сегодня» — у клиента (поле несёт data-today — его дату), иначе — по часам компьютера
    const сегодня = () => {
      const t = /^(\d{4})-(\d{2})-(\d{2})$/.exec((поле && поле.getAttribute('data-today')) || '');
      if (t) return new Date(+t[1], +t[2] - 1, +t[3], 12);
      const d = new Date(); d.setHours(12, 0, 0, 0); return d;
    };
    let pop = null, поле = null, вид = null;
    const закрыть = () => { if (pop) pop.remove(); pop = null; поле = null; };
    const поставить = (v) => {
      const x = поле;
      закрыть();
      if (!x || x.disabled) return;
      x.value = v;
      x.dispatchEvent(new Event('input', { bubbles: true }));
      x.dispatchEvent(new Event('change', { bubbles: true }));
    };
    function нарисовать() {
      const выбр = (поле && поле.value) || '', сег = iso(сегодня());
      const перв = new Date(вид.getFullYear(), вид.getMonth(), 1, 12);
      const сдвиг = (перв.getDay() + 6) % 7;                     // неделя с понедельника
      const старт = new Date(перв.getTime() - сдвиг * 864e5);
      const дни = [];
      for (let i = 0; i < 42; i++) {
        const d = new Date(старт.getTime() + i * 864e5); d.setHours(12, 0, 0, 0);
        const v = iso(d);
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'cal-d' + (d.getMonth() !== вид.getMonth() ? ' out' : '') + (v === сег ? ' today' : '') + (v === выбр ? ' on' : '') + (v < сег ? ' past' : '') + ((i % 7) > 4 ? ' we' : '');
        b.textContent = String(d.getDate());
        b.addEventListener('click', () => поставить(v));
        дни.push(b);
      }
      const шаг = (n) => { вид = new Date(вид.getFullYear(), вид.getMonth() + n, 1, 12); нарисовать(); };
      const кн = (cls, txt, fn, label) => { const b = document.createElement('button'); b.type = 'button'; b.className = cls; b.textContent = txt; if (label) b.setAttribute('aria-label', label); b.addEventListener('click', fn); return b; };
      const быстро = [0, 1, 2].map((n) => { const d = new Date(сегодня().getTime() + n * 864e5); const v = iso(d);
        return кн('cal-q' + (v === выбр ? ' on' : ''), n === 0 ? 'Сегодня' : n === 1 ? 'Завтра' : НЕД[(d.getDay() + 6) % 7] + ' ' + String(d.getDate()).padStart(2, '0') + '.' + String(d.getMonth() + 1).padStart(2, '0'), () => поставить(v)); });
      const шапка = document.createElement('div'); шапка.className = 'cal-h';
      const тит = document.createElement('div'); тит.className = 'cal-t'; тит.textContent = МЕС[вид.getMonth()] + ' ' + вид.getFullYear();
      шапка.append(кн('cal-n', '‹', () => шаг(-1), 'Предыдущий месяц'), тит, кн('cal-n', '›', () => шаг(1), 'Следующий месяц'));
      const нед = document.createElement('div'); нед.className = 'cal-g cal-w';
      for (const t of НЕД) { const x = document.createElement('span'); x.textContent = t; нед.append(x); }
      const сетка = document.createElement('div'); сетка.className = 'cal-g'; сетка.append(...дни);
      const низ = document.createElement('div'); низ.className = 'cal-qs'; низ.append(...быстро);
      pop.replaceChildren(шапка, нед, сетка, низ);
    }
    function открыть(x) {
      закрыть();
      поле = x;
      const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(x.value || '');
      вид = m ? new Date(+m[1], +m[2] - 1, 1, 12) : сегодня();
      pop = document.createElement('div');
      pop.className = 'cal';
      pop.setAttribute('role', 'dialog');
      pop.setAttribute('aria-label', 'Календарь');
      pop.addEventListener('mousedown', (e) => e.preventDefault());   // поле не теряет фокус, клик по дню доходит
      нарисовать();
      root.querySelector('.lcz').append(pop);
      const r = x.getBoundingClientRect(), w = 300, hgt = pop.offsetHeight || 340;
      const left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8));
      const вниз = r.bottom + 6 + hgt < window.innerHeight || r.top < hgt + 6;
      pop.style.left = left + 'px';
      pop.style.top = (вниз ? r.bottom + 6 : Math.max(8, r.top - hgt - 6)) + 'px';
    }
    root.addEventListener('click', (e) => {
      const x = e.composedPath ? e.composedPath()[0] : e.target;
      if (x && x.tagName === 'INPUT' && x.type === 'date' && !x.disabled && !x.readOnly) { if (поле !== x) открыть(x); return; }
      if (pop && !(e.composedPath ? e.composedPath() : []).includes(pop)) закрыть();
    });
    root.addEventListener('keydown', (e) => { if (pop && e.key === 'Escape') { e.stopPropagation(); закрыть(); } }, true);
    // 2.1: Esc закрывает только календарь — раньше обработчик документа (он раньше корня) закрывал заодно всю панель
    window.addEventListener('keydown', (e) => { if (pop && e.key === 'Escape') { e.stopPropagation(); e.preventDefault(); закрыть(); } }, true);
    document.addEventListener('mousedown', (e) => { if (pop && !e.composedPath().includes(host)) закрыть(); });
    window.addEventListener('resize', закрыть);
    root.addEventListener('scroll', закрыть, true);
  })();

  /* 2.1: свой выбор времени для всех полей времени (форма, перенос, действия) — как календарь у даты: щелчок открывает окно (2.3: фокус — нет),
     поле остаётся (можно напечатать 15:37), окно только ставит значение и шлёт input/change, как ввод с клавиатуры.
     Что поле может сказать о городе: data-tz (пояс — часы живые) или data-now="ЧЧ:ММ" (+ data-now-at, мс — когда снято),
     data-where («в Москве»), data-today (сегодня у клиента), data-earliest / data-latest (без согласования с филиалом; по умолчанию —
     регламент 10:00–21:30, пустое значение — без границы), data-date (день визита; нет — поле даты рядом). Ничего нет — часы компьютера */
  const ТИХИЙ_ФОКУС = { on: false };                                 // фокус вернули после перерисовки формы — окно не открываем
  const ВЫБОР_ВРЕМЕНИ = (function выборВремени() {
    const ДН = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];
    const ЧАСЫ = Array.from({ length: 16 }, (_, i) => i + 7);       // 07…22
    const мин = (s) => { const m = /^(\d{1,2}):(\d{2})/.exec(String(s || '')); return m ? +m[1] * 60 + +m[2] : NaN; };
    const чм = (n) => { n = ((n % 1440) + 1440) % 1440; return String(Math.floor(n / 60)).padStart(2, '0') + ':' + String(n % 60).padStart(2, '0'); };
    const isoМест = (d) => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    const деньИз = (iso) => (/^\d{4}-\d{2}-\d{2}$/.test(iso || '') ? ДН[new Date(iso + 'T12:00:00Z').getUTCDay()] + ' ' + iso.slice(8, 10) + '.' + iso.slice(5, 7) : '');
    let pop = null, поле = null, час = null;
    // сейчас + плюс минут (вверх до минуты, как «Через час» в CRM): { hm, iso } — по поясу поля, по его data-now или по компьютеру
    function когда(x, плюс) {
      const tz = x.getAttribute('data-tz'), мс = Math.ceil((Date.now() + плюс * 60e3) / 60e3) * 60e3;
      if (tz && typeof LC_EXTRACT !== 'undefined' && LC_EXTRACT.localParts) {
        try { const p = LC_EXTRACT.localParts(new Date(плюс ? мс : Date.now()), tz); return { hm: p.hm, iso: p.iso, город: true }; } catch (_e) { /* пояс не понят — дальше */ }
      }
      const now = мин(x.getAttribute('data-now'));
      if (!isNaN(now)) {
        const at = +x.getAttribute('data-now-at') || 0, прошло = at ? Math.max(0, Math.floor((Date.now() - at) / 60e3)) : 0;
        const всего = now + прошло + плюс, сег = x.getAttribute('data-today') || '';
        const iso = /^\d{4}-\d{2}-\d{2}$/.test(сег) ? new Date(Date.parse(сег + 'T12:00:00Z') + Math.floor(всего / 1440) * 864e5).toISOString().slice(0, 10) : '';
        return { hm: чм(всего), iso, город: true };
      }
      const d = new Date(плюс ? мс : Date.now());
      return { hm: чм(d.getHours() * 60 + d.getMinutes()), iso: isoМест(d), город: false };
    }
    const граница = (x, k, def) => (x.hasAttribute(k) ? мин(x.getAttribute(k)) : мин(def));
    // день визита: data-date или поле даты рядом (в той же группе полей)
    function деньВизита(x) {
      if (x.hasAttribute('data-date')) return x.getAttribute('data-date') || '';
      let a = x.parentElement;
      for (let i = 0; a && i < 5; i++, a = a.parentElement) { const d = a.querySelector('input[type="date"]'); if (d) return d.value || ''; }
      return '';
    }
    const закрыть = () => { if (pop) pop.remove(); pop = null; поле = null; час = null; };
    const поставить = (v, оставить) => {
      const x = поле;
      if (!x || x.disabled || !x.isConnected) { закрыть(); return; }
      const былФокус = !!(pop && root.activeElement && pop.contains(root.activeElement));
      x.value = v;
      x.dispatchEvent(new Event('input', { bubbles: true }));
      x.dispatchEvent(new Event('change', { bubbles: true }));
      if (оставить && pop && поле === x) { нарисовать(); if (былФокус) { const b = pop.querySelector('[data-tp="m"].on') || pop.querySelector('[data-tp="m"]'); if (b) b.focus(); } return; }
      закрыть();
      if (былФокус && x.isConnected) { ТИХИЙ_ФОКУС.on = true; try { x.focus(); } finally { ТИХИЙ_ФОКУС.on = false; } }
    };
    function кнопка(cls, txt, label, title, fn, tp) {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'tp-b' + (cls ? ' ' + cls : ''); b.textContent = txt;
      if (label) b.setAttribute('aria-label', label);
      if (title) b.title = title;
      if (tp) b.setAttribute('data-tp', tp);
      if (/\bon\b/.test(cls || '')) b.setAttribute('aria-pressed', 'true');
      b.addEventListener('click', fn);
      return b;
    }
    function нарисовать() {
      const x = поле;
      if (!x || !x.isConnected) { закрыть(); return; }
      const сейчас = когда(x, 0), сейчасМ = мин(сейчас.hm), знач = мин(x.value);
      const ран = граница(x, 'data-earliest', '10:00'), позд = граница(x, 'data-latest', '21:30');
      const сег = x.getAttribute('data-today') || сейчас.iso, день = деньВизита(x);
      const сегодня = !!день && день === сег && !isNaN(сейчасМ);
      const выбЧас = час !== null ? час : !isNaN(знач) ? Math.floor(знач / 60) : null;
      const где = x.getAttribute('data-where') || '';
      const шапка = document.createElement('div'); шапка.className = 'tp-h';
      const s = document.createElement('span');
      s.textContent = 'Сейчас ' + (сейчас.город ? (где ? где + ' · ' : '') : 'на компьютере · ') + деньИз(сейчас.iso || сег);
      const b = document.createElement('b'); b.textContent = сейчас.hm;
      шапка.append(s, b);
      const быстро = document.createElement('div'); быстро.className = 'tp-g q';
      for (const [n, txt] of [[60, 'Через час'], [120, '+2 ч'], [240, '+4 ч']]) {
        const t = когда(x, n).hm;
        const b = кнопка('q2' + (n === 60 ? ' info' : ''), '', txt + ': ' + t, '', () => поставить(t), 'q');
        const w = document.createElement('span'), dd = document.createElement('span'), sep = document.createElement('span');
        w.className = 'w'; w.textContent = txt; sep.className = 'vh'; sep.textContent = ' · '; dd.className = 'd'; dd.textContent = t;
        b.append(w, sep, dd);
        быстро.append(b);
      }
      const лч = document.createElement('div'); лч.className = 'tp-lb'; лч.textContent = 'Час';
      const часы = document.createElement('div'); часы.className = 'tp-g'; часы.setAttribute('role', 'group'); часы.setAttribute('aria-label', 'Час');
      for (const ч of ЧАСЫ) {
        const до = !isNaN(ран) && ч * 60 + 59 < ран, после = !isNaN(позд) && ч * 60 > позд, прошёл = сегодня && ч * 60 + 59 < сейчасМ;
        const cls = [ч === выбЧас ? 'on' : '', прошёл ? 'past' : до || после ? 'soft' : ''].filter(Boolean).join(' ');
        const title = до ? 'раньше ' + чм(ран) + ' — по согласованию с филиалом' : после ? 'позже ' + чм(позд) + ' — по согласованию с филиалом' : прошёл ? 'уже прошло' : '';
        часы.append(кнопка(cls, String(ч).padStart(2, '0'), String(ч).padStart(2, '0') + ' ч' + (title ? ' — ' + title : ''), title, () => {
          час = ч;
          поставить(чм(ч * 60 + (isNaN(знач) ? 0 : знач % 60)), true);
        }, 'h'));
      }
      pop.replaceChildren(шапка, быстро, лч, часы);
      if (выбЧас !== null) {
        const лм = document.createElement('div'); лм.className = 'tp-lb'; лм.textContent = 'Минуты для ' + выбЧас + ' ч';
        const минуты = document.createElement('div'); минуты.className = 'tp-g'; минуты.setAttribute('role', 'group'); минуты.setAttribute('aria-label', 'Минуты');
        for (const м of [0, 15, 30, 45]) {
          const t = выбЧас * 60 + м, до = !isNaN(ран) && t < ран, после = !isNaN(позд) && t > позд, прошло = сегодня && t < сейчасМ;
          const title = до ? 'раньше ' + чм(ран) + ' — по согласованию с филиалом' : после ? 'позже ' + чм(позд) + ' — по согласованию с филиалом' : прошло ? 'уже прошло' : '';
          минуты.append(кнопка([t === знач ? 'on' : '', прошло ? 'past' : до || после ? 'soft' : ''].filter(Boolean).join(' '), чм(t), чм(t) + (title ? ' — ' + title : ''), title, () => поставить(чм(t)), 'm'));
        }
        pop.append(лм, минуты);
      }
      const сноска = document.createElement('div'); сноска.className = 'tp-f';
      сноска.textContent = 'Пунктир — по согласованию с филиалом' + (!isNaN(ран) || !isNaN(позд) ? ' (' + [!isNaN(ран) ? 'раньше ' + чм(ран) : '', !isNaN(позд) ? 'позже ' + чм(позд) : ''].filter(Boolean).join(', ') + ')' : '')
        + '. Зачёркнутое — уже прошло сегодня. Своё время можно набрать в поле: 15:37. Esc — закрыть.';
      pop.append(сноска);
    }
    function место() {
      if (!pop || !поле) return;
      if (!поле.isConnected) { закрыть(); return; }
      const r = поле.getBoundingClientRect(), w = 320, hgt = pop.offsetHeight || 420;
      const left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8));
      const вниз = r.bottom + 6 + hgt < window.innerHeight || r.top < hgt + 6;
      pop.style.left = left + 'px';
      pop.style.top = (вниз ? r.bottom + 6 : Math.max(8, r.top - hgt - 6)) + 'px';
    }
    function открыть(x) {
      закрыть();
      поле = x;
      pop = document.createElement('div');
      pop.className = 'tp';
      pop.setAttribute('role', 'dialog');
      pop.setAttribute('aria-label', 'Выбор времени');
      pop.addEventListener('mousedown', (e) => e.preventDefault());   // поле не теряет фокус, щелчок доходит
      нарисовать();
      root.querySelector('.lcz').append(pop);
      место();
    }
    const времяЛи = (x) => !!x && x.tagName === 'INPUT' && x.type === 'time' && !x.disabled && !x.readOnly;
    root.addEventListener('click', (e) => {
      const путь = e.composedPath ? e.composedPath() : [], x = путь[0] || e.target;
      if (времяЛи(x)) { if (поле !== x) открыть(x); return; }
      if (pop && !путь.includes(pop)) закрыть();
    });
    // 2.3: фокус (Tab) окно не открывает — только щелчок по полю (окно само выскакивало и закрывало соседние поля)
    root.addEventListener('focusout', (e) => {
      if (!pop) return;
      const к = e.relatedTarget;
      if (к && (к === поле || pop.contains(к))) return;
      // щелчок по окну фокус не уводит (mousedown); Tab из поля или из окна — закрываем
      setTimeout(() => { const a = root.activeElement; if (pop && !(a && (a === поле || pop.contains(a)))) закрыть(); }, 0);
    });
    // напечатали в поле — подсветка часа и минут следом
    root.addEventListener('input', (e) => { if (pop && e.target === поле) { час = null; нарисовать(); } });
    // клавиши: ↓ из поля — в окно; стрелки — по кнопкам (сетки по 3 и 4 в ряд), Enter / пробел — выбрать (обычное нажатие кнопки), Esc — закрыть
    window.addEventListener('keydown', (e) => {
      if (!pop) return;
      const a = root.activeElement;
      if (e.key === 'Escape') {
        e.stopPropagation(); e.preventDefault();
        const x = поле, изОкна = !!(a && pop.contains(a));
        закрыть();
        if (изОкна && x && x.isConnected) { ТИХИЙ_ФОКУС.on = true; try { x.focus(); } finally { ТИХИЙ_ФОКУС.on = false; } }
        return;
      }
      if (!/^Arrow(Up|Down|Left|Right)$/.test(e.key) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (a === поле) {
        if (e.key !== 'ArrowDown') return;
        e.preventDefault(); e.stopPropagation();
        const b = pop.querySelector('[data-tp="h"].on') || pop.querySelector('[data-tp="h"]:not(.past):not(.soft)') || pop.querySelector('.tp-b');
        if (b) b.focus();
        return;
      }
      if (!a || !pop.contains(a) || !a.classList.contains('tp-b')) return;
      e.preventDefault(); e.stopPropagation();
      const сетки = [...pop.querySelectorAll('.tp-g')].map((g) => ({ g, кн: [...g.querySelectorAll('.tp-b')], кол: g.classList.contains('q') ? 3 : 4 }));
      const gi = сетки.findIndex((s) => s.кн.includes(a)), s = сетки[gi], i = s.кн.indexOf(a);
      let к = null;
      if (e.key === 'ArrowLeft') к = s.кн[i - 1] || (сетки[gi - 1] && сетки[gi - 1].кн.slice(-1)[0]);
      else if (e.key === 'ArrowRight') к = s.кн[i + 1] || (сетки[gi + 1] && сетки[gi + 1].кн[0]);
      else if (e.key === 'ArrowUp') {
        if (i - s.кол >= 0) к = s.кн[i - s.кол];
        else if (сетки[gi - 1]) { const п = сетки[gi - 1], ряд = Math.floor((п.кн.length - 1) / п.кол) * п.кол; к = п.кн[Math.min(ряд + (i % s.кол), п.кн.length - 1)]; }
        else if (поле) { ТИХИЙ_ФОКУС.on = true; try { поле.focus(); } finally { ТИХИЙ_ФОКУС.on = false; } return; }
      } else if (e.key === 'ArrowDown') {
        if (i + s.кол < s.кн.length) к = s.кн[i + s.кол];
        else if (сетки[gi + 1]) { const сл = сетки[gi + 1]; к = сл.кн[Math.min(i % s.кол, сл.кн.length - 1)]; }
      }
      if (к) к.focus();
    }, true);
    document.addEventListener('mousedown', (e) => { if (pop && !e.composedPath().includes(host)) закрыть(); });   // щелчок мимо панели
    window.addEventListener('resize', закрыть);
    root.addEventListener('scroll', место, true);                       // прокрутили панель — окно едет за полем
    return { закрыть, открыть, открыто: () => (pop ? поле : null) };
  })();

  // страховка для кнопок и полей: ошибка в обработчике не оставляет кнопку «Делаем…» навсегда — кнопка снова активна, ошибка видна
  const страховка = (fn) => function (e) {
    const btn = e && e.currentTarget && e.currentTarget.tagName === 'BUTTON' ? e.currentTarget : null, был = btn ? btn.textContent : '';
    const упало = (err) => {
      if (btn && btn.isConnected) { btn.disabled = false; btn.textContent = был; }
      const msg = 'Не получилось: ' + String((err && err.message) || err).slice(0, 160) + (устарело(err) ? '' : ' — попробуйте ещё раз');
      try {
        if (panel.classList.contains('open')) alertBox(устарело(err) ? УСТАРЕЛО : msg);
        else {
          // 2.1: понятная фраза, техника — под «Подробнее»; следующий шаг — «Повторить» (то же нажатие), а не исчезающее окно без кнопок
          const ч = человечно(err), повтор = btn && btn.isConnected && !устарело(err) ? btn : null;
          const el = тост({ kind: 'bad', label: 'Ошибка', title: устарело(err) ? УСТАРЕЛО : 'Не получилось: ' + String(ч.text).slice(0, 160),
            подробно: ч.тех || '', жить: повтор ? 0 : 20e3,
            actions: [повтор ? h('button', { class: 'sm pri', onclick: () => { el.remove(); повтор.click(); } }, 'Повторить') : '',
              устарело(err) ? h('button', { class: 'sm pri', onclick: () => location.reload() }, 'Обновить страницу') : ''] });
        }
      } catch (_e) { /* панели нет */ }
    };
    let r;
    try { r = fn.call(this, e); } catch (err) { упало(err); return undefined; }
    if (r && typeof r.then === 'function') r.catch(упало);
    return r;
  };
  const h = (tag, attrs = {}, ...kids) => {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false && !['checked', 'disabled', 'selected', 'indeterminate'].includes(k)) continue;
      if (k === 'class') el.className = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), страховка(v));
      else if (k === 'checked' || k === 'disabled' || k === 'selected' || k === 'indeterminate') el[k] = !!v;
      else if (k === 'value') el.value = v ?? '';
      else el.setAttribute(k, v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false && kid !== '') el.append(kid.nodeType ? kid : String(kid));
    return el;
  };

  let S = null;               // состояние текущей сборки
  let собираю = false;        // идёт разбор диалога (collect) — второй не начинаем; создание заявки его не держит
  /* создаваемые заявки по диалогам (conv → задача): создание идёт само, оператор может уйти в другой чат */
  const ЗАДАЧИ = new Map();
  const задачаИдёт = (conv) => { const j = conv ? ЗАДАЧИ.get(conv) : null; return j && !j.ход.конец ? j : null; };
  /* 1.20: действия — экран действий по заявке (actions-ui.js): сетка, карточка с превью и общий бегунок. Нет модуля
     (старая страница, тесты прежних пакетов) — всё по-прежнему, как в 1.19 */
  let ACT = null;

  /* ---------- шапка, шаги загрузки, ошибки ---------- */
  // o (2.1, форма): title — заголовок экрана, redo — «Прочитать диалог заново» в шапке (у формы — не рядом с «Создать»), ready: false — без «Готовых»
  function header(sub, o) {
    o = o || {};
    if(личнаяВкладка&&o.title==='Личный помощник')return h('div',{class:'top'},h('div',{class:'ttl'},h('div',{class:'t'},'LeadBot · центр управления'),h('div',{class:'sub'},'Диалоги, ответы и контроль в одном окне')),
      h('button',{class:'ib','aria-label':'В отдельное окно',title:'Вынести на другой монитор',onclick:()=>send({kind:'lcz-personal-tab',action:'detach'})},'↗'),
      h('button',{class:'ib','aria-label':'Настройки',onclick:()=>send({kind:'lcz-options'})},svg('gear')),
      h('button',{class:'ib','aria-label':'Закрыть помощника',onclick:closePanel},svg('close')));
    return h('div', { class: 'top' },
      h('div', { class: 'ttl' }, h('div', { class: 't' }, o.title || 'Заявка в CRM'), sub ? h('div', { class: 'sub', title: typeof sub === 'string' ? sub : undefined }, sub) : ''),
      h('button', { class: 'ib', 'aria-label': 'Личный помощник', title: 'Личная очередь и ответы по регламенту', onclick: openAssistant }, '✦'),
      o.redo ? h('button', { class: 'ib', 'aria-label': 'Прочитать диалог заново', title: 'Прочитать диалог заново', 'data-redo': '1', onclick: o.redo }, svg('redo')) : '',
      o.ready === false ? '' : h('button', { class: 'ib', 'aria-label': 'Готовые к созданию', title: 'Готовые к созданию: диалоги, где всё есть и не нужно согласование', onclick: () => showReady() }, svg('check')),
      h('button', { class: 'ib', 'aria-label': 'Журнал за смену', title: 'Журнал заявок за смену', onclick: () => showJournal() }, svg('list')),
      h('button', { class: 'ib', 'aria-label': 'Настройки', title: 'Настройки', onclick: () => send({ kind: 'lcz-options' }) }, svg('gear')),
      h('button', { class: 'ib', 'aria-label': 'Закрыть', title: 'Закрыть (Esc)', onclick: closePanel }, svg('close')));
  }
  let assistantPanel = null;
  chrome.runtime.onMessage.addListener((msg,from,reply)=>{
    if(msg?.kind!=='lcz-personal-pulse')return;
    if(from.id!==chrome.runtime.id||from.tab){reply({ok:false,active:false});return}
    Promise.resolve(assistantPanel?.personal?.pulse(msg.connection_id))
      .then(value=>reply(value||{ok:false,active:false}),()=>reply({ok:false,active:false}));
    return true;
  });
  async function personalDialog(id){const d=await loadDialog(id);d.msgs=await LC_WORKFLOW.readHistory({items:d.msgs,page:d.messagePage},cursor=>LC.get('/conversations/'+encodeURIComponent(id)+'/messages?limit=100&before='+encodeURIComponent(cursor)));return d}
  async function assistantContext(id) {
    const dialog = await personalDialog(id);
    const ctx = ctxOf(dialog), account = каналИсточника(dialog.conv);
    const advert = LC_EXTRACT.withAdvertiser({}, ctx);
    const identity = LC_EXTRACT.fromIdentity(dialog.identity, id);
    const addressProved = identity.addr && identity.addrConv === String(id);
    let actorAccess=null;
    if(assistantPanel?.personal?.state.delegated&&!dialog.conv.crm_request_id){try{actorAccess=await assistantNative.access(id)}catch(_e){actorAccess={allowed:false}}}
    return { ...ctx, messages: dialog.msgs.map((m) => ({ id: m.id, direction: m.direction, sender_type: m.sender_type,
        created_at: m.created_at, sender:{id:m.sender?.id||''}, client_message_id:m.client_message_id||'', delivery_status: m.delivery_status || m.delivery || '', body: LC_EXTRACT.сКонтактом(m), voice_transcript: m.voice_transcript || '', attachments: m.attachments || [] })),
      dir: LC_EXTRACT.базаКанала(dialog.conv) || (S && S.id === id ? S.dir : ''),
      dirBasis:LC_EXTRACT.базаКанала(dialog.conv)?'account':(S&&S.id===id&&S.dir?'operator':''), accountId: account.id || '',
      origin: account.lead_origin || '', adIdentity: advert.ad_identity || '', introducedName: advert.introduced_as || '',
      cardPhone: identity.phone && !identity.mergedUnproven ? (ctx.cardPhone || '+7' + identity.phone) : '',
      cardAddress: addressProved ? { ...identity.addr, city: identity.locality || '' } : {}, cardAddressVerified: !!addressProved,
      crmRequestId: dialog.conv.crm_request_id || '',
      assigneeId: (dialog.conv.assignee && dialog.conv.assignee.id) || dialog.conv.assignee_id || (dialog.conv.claimed_by && dialog.conv.claimed_by.id) || dialog.conv.claimed_by_id || '',
      assignmentKnown:['assignee','assignee_id','claimed_by','claimed_by_id'].some(k=>Object.prototype.hasOwnProperty.call(dialog.conv,k)),
      conversationStatus: dialog.conv.status || '',botActive:typeof dialog.conv.bot_active==='boolean'?dialog.conv.bot_active:null,
      hasTransfer:Object.prototype.hasOwnProperty.call(dialog.conv,'transfer')?!!dialog.conv.transfer:null,
      channelAssigned: actorAccess?actorAccess.allowed===true:!!(LC.me && Array.isArray(LC.me.permissions) && LC.me.permissions.includes('messages:send') &&
        (LC.me.inbox_account_ids===null || (Array.isArray(LC.me.inbox_account_ids)&&LC.me.inbox_account_ids.includes(String(account.id))))),
      hasCrmJob:!!(await создаётсяПоДиалогу(id)) };
  }
  async function personalIdentity() {
    const me=await LC.get('/auth/me');
    LC.me=me&&me.id?{...me,id:String(me.id),name:me.full_name||''}:null;
    return me;
  }
  const nativeTransport=typeof LC_NATIVE_API!=='undefined'?LC_NATIVE_API.create({
    fetch:(...args)=>fetch(...args),token:()=>LC.tok(),loggedOut:()=>наВходе(),
  }):null;
  const assistantNative=LC_ASSISTANT_NATIVE.create({get:path=>LC.get(path),post:(path,body)=>LC.post(path,body),send,operator:()=>assistantPanel?.personal?.state.operator||''});
  async function handoffDialog(){
    const id=convIdNow();if(!id)throw Error('Откройте диалог для передачи');
    const me=await personalIdentity();if(me?.role!=='admin')throw Error('Передача боту доступна администратору');
    const [caps,dialog]=await Promise.all([assistantNative.authors(),деталь(id)]);
    if(id!==convIdNow())throw Error('Диалог изменился. Выберите его заново');
    if(dialog.crm_request_id)throw Error('Заявка уже создана. Бот закончил работу с диалогом');
    const holder=dialog.assignee?.id||dialog.assignee_id||dialog.claimed_by?.id||dialog.claimed_by_id||'';
    const initial=caps.authors.some(a=>a.id===holder)?holder:String(me.id);
    const author=h('select',{'aria-label':'Автор ответов бота'},...caps.authors.map(a=>h('option',{value:a.id,selected:a.id===initial},a.full_name+(a.id===me.id?' (вы)':''))));
    const note=h('div',{class:'n mut',role:'status'},'Если авто выключено, диалог будет ждать вашего запуска. После передачи откроется панель наблюдения, а рабочая вкладка вернётся к списку диалогов.');
    const submit=h('button',{class:'go',type:'button',onclick:async()=>{
      submit.disabled=true;
      try{
        if(convIdNow()!==id)throw Error('Открыт другой диалог. Начните передачу заново');
        if([...document.querySelectorAll('.composer textarea')].some(el=>el.value.trim())||document.querySelector('.composer__chip,.composer__reply'))throw Error('В поле ответа есть черновик или вложение. Сначала сохраните или отправьте его вручную');
        const selectedAuthor=author.value;
        const returnedJob=await assistantNative.handoff(id,selectedAuthor,holder);
        const resumed=await send({kind:'lcz-assistant',args:{action:'resume',ctx:await assistantContext(id)}});
        if(!resumed?.ok)throw Error('Диалог передан, но помощник пока недоступен. Откройте панель и проверьте подключение');
        await LC_WORKFLOW.releaseHumanHold(workflowAdapters,selectedAuthor,id,returnedJob);
        if(convIdNow()!==id)throw Error('Диалог передан; откройте панель помощника вручную');
        const opened=await send({kind:'lcz-personal-tab',action:'open'});
        if(!opened?.ok)throw Error('Диалог передан. Панель помощника пока не открылась');
        location.assign('/chats');
      }catch(e){note.textContent=String(e.message||e);submit.disabled=false}
    }},'Передать боту и открыть наблюдение');
    panel.replaceChildren(h('div',{class:'ph'},header('Выбранный диалог', {title:'Передать боту'})),
      h('div',{class:'pb'},h('label',{},'От чьего имени отвечать',author),note,submit));panel.classList.add('open');
  }
  const personalQueueReader=LC_PERSONAL_QUEUE.create({get:path=>LC.get(path),identity:async()=>assistantPanel?.personal?.state.operator||await моёId(),detail:деталь,
    minePath:actor=>'/conversations?tab='+(assistantPanel?.personal?.state.delegated?'all':'mine')+'&assignee_id='+encodeURIComponent(actor),
    freePath:actor=>assistantPanel?.personal?.state.delegated?'/bot-dialogs/assistant/queue?operator_id='+encodeURIComponent(actor):'/inbox'});
  const personalQueue=async options=>{const page=await personalQueueReader.load(options);return assistantPanel?.personal?.state.delegated?assistantNative.queue(page):page};
  // Read-only intake preflight, also repeated immediately before a write by
  // workflow.decision. Do not reuse a stale CRM result across send attempts.
  const personalIntakeGuard=ctx=>LC_INTAKE.check(ctx,phone=>спросить({kind:'lcz-crm',op:'existing',args:{phone,name:ctx.clientName||'',dir:ctx.dir||''}},40e3,'CRM (проверка до приёма)'),LC_EXTRACT.номерДляПоиска(ctx));
  async function workflowPrepare(s,p,form) {
    const draft=form;
    const extraction=LC_WORKFLOW.formExtraction(draft,p.revision);
    const dir=LC_WORKFLOW.draftDirection(draft,p.revision);
    if(!/^[1-9]\d{0,5}$/.test(String(draft.lead?.partner||'')))throw Error('Партнёр источника не подтверждён мозгом');
    if(!draft.facts)throw Error('Контакты не подтверждены мозгом');
    const d=await personalDialog(s.ctx.convId);
    const r=await разобратьГотовность(d,{id:s.ctx.convId,name:d.conv.client?.name||''},{вДиалоге:true,личноеНаправление:dir,личныйЧерновик:draft,проверенныйРазбор:extraction});
    const A=r.A;if(!A)throw Error(r.why||'Нет проверенного снимка заявки');
    if(r.st!=='ready')throw Error(r.why||'Проверка готовности формы оставила замечания');
    if(r.dir&&r.dir!==dir)throw Error('Проверка заявки вернула другое направление');
    const lead=withSource({...копия(A.lead),partner:draft.lead.partner},A.conv,dir);
    // Existing source formatting may derive another display label. The
    // accepted native identity/work comment remains authoritative; retain the
    // existing source URL separately rather than rewriting the reviewed form.
    lead.ad_identity=extraction.lead.ad_identity;
    lead.comment=[extraction.lead.comment,lead.src_url].filter(Boolean).join('\n');
    // Server-extracted contacts are authoritative over legacy extraction/card data.
    lead.phone=draft.facts.contact_phone_to_use;lead.addr=копия(draft.facts.address);
    lead.comment=LC_WORKFLOW.contactComment(lead.comment,draft.facts);
    Object.assign(lead,LC_WORKFLOW.projectAcceptedVisit(lead,draft));
    lead.call_check=false;lead.call_before_visit=!!draft.crm_flags?.callbefore||наДваДня(lead);
    lead.service_comment=[lead.service_comment,location.origin+'/chats/'+encodeURIComponent(s.ctx.convId)].filter(Boolean).join('\n');
    const [prep,terr]=await Promise.all([
      send({kind:'lcz-crm',op:'prepare',args:{...LC_WORKFLOW.crmPrepareArgs(dir,lead,draft),безИИ:true}}),
      территория({dir,city:lead.city,...lead.addr,partner:lead.partner,tech:техника(lead),...LC_EXTRACT.точкаАдреса(lead)})]);
    const followup=LC_WORKFLOW.crmFollowup(draft,s.ctx.channel,LC_TG.кодИсточника(lead.partner_note)||партнёрКодом(lead.partner));
    if(followup.required){const groups=await группыTG(),chat=groups?.ok?чатАвито(groups):null;followup.telegram_ready=!!(followup.code&&chat&&await разделСозданных(chat[0]))}
    return {revision:p.revision,form_reference:draft.form_reference,dir,lead,prep,territory:terr,readiness:r.st,flags:r.флаги||[],allowLive:false,
      followup,sel:{cityId:prep.cityId,applId:prep.applId,subId:prep.subId,appl:prep.appl,sub:prep.sub,type:prep.type},advertiserCtx:копия(A.ctx)};
  }
  const workflowAdapters={
    finishOnLinked:true,
    notifyBeforeFinish:true,
    pauseForHuman:async(id,operator)=>{
      if(assistantPanel?.personal?.state.delegated!==true||assistantPanel.personal.state.operator!==operator)
        throw Error('Не подтверждён администратор для закрепления ручной паузы');
      return assistantNative.pauseForHuman(id);
    },
    prepareCRM:workflowPrepare,
    // Unlike manual CRM creation, the personal chain requires a browser-wide lock.
    lock:(key,fn)=>{if(!navigator.locks?.request)throw Error('Блокировка браузера недоступна');return navigator.locks.request(key,fn)},
    read:async key=>(await chrome.storage.local.get(key))[key],
    save:async(key,value)=>{await chrome.storage.local.set({[key]:value})},
    queueAudit:async(s,event)=>поОдному('workflow-audit',async()=>{const key='workflowAuditOutbox:'+s.operatorId,rows=await store.get(key,[]);rows.push({ctx:{convId:s.ctx.convId},operator_id:s.operatorId,audit_event:event});await store.set(key,rows)}),
    flushAudit:async(operator,deliver)=>поОдному('workflow-audit',async()=>{const key='workflowAuditOutbox:'+operator,rows=await store.get(key,[]);while(rows.length){const r=await deliver(rows[0]);if(!r?.ok)throw Error(r?.error||'Журнал ожидает связи с сервером');rows.shift();await store.set(key,rows)}}),
    pending:async(operator,conv)=>Object.entries(await chrome.storage.local.get(null)).filter(([k,v])=>k.startsWith('workflow:'+operator+':'+conv+':')&&v&&v.state!=='done').map(([key,v])=>({...v,key})),
    claim:s=>assistantPanel?.personal?.state.delegated?assistantNative.claim(s.ctx.convId):взятьДиалог({id:s.ctx.convId}),
    sendReply:async(s,text,clientId)=>{
      const path='/conversations/'+encodeURIComponent(s.ctx.convId)+'/messages';
      const ack=assistantPanel?.personal?.state.delegated?await assistantNative.reply(s.ctx.convId,text,clientId,s.ctx.messages.at(-1)?.id):await LC.post(path,{text,client_message_id:clientId});
      return LC_WORKFLOW.waitForDelivery({clientId,initial:ack,read:()=>LC.get(path+'?limit=50')});
    },
    createCRM:(proposal,s,p)=>поОдному('lcz-create',async()=>{
      const nativeJob=assistantPanel?.personal?.state.delegated?await assistantNative.runnable(s.ctx.convId,s.ctx):null;
      if(assistantPanel?.personal?.state.delegated&&!nativeJob)throw Error('Диалог сначала должен быть передан боту');
      const result=await отправитьСоздание({dir:proposal.dir,lead:proposal.lead,sel:proposal.sel,allowLive:false,personalWorkflow:true,workflow_guard:{conv_id:s.ctx.convId,operator_id:s.operatorId,revision:p.revision,generation:p.run_generation,...(nativeJob?{native_job_version:nativeJob.version}:{})},advertiserCtx:proposal.advertiserCtx});
      if(result.сбой)throw Error(result.сбой);return {...result.r,workflow:{followup:proposal.followup,dir:proposal.dir,city:proposal.prep.cityText}};
    }),
    linkCRM:async(s,r)=>{
      const linked=assistantPanel?.personal?.state.delegated?await assistantNative.complete(s.ctx.convId,r.id,r.service_notification):await номерВДиалог(s.ctx.convId,r.id),conv=await деталь(s.ctx.convId);
      if(linked?.same_request_conversation_ids?.length)return {confirmed:false,result:{id:r.id,reason:'В LeadChat есть другие диалоги с этим номером'}};
      if(linked?.twins?.length)return {confirmed:false,result:{id:r.id,reason:'В LeadChat есть другие диалоги с этим номером'}};
      if(String(conv.crm_request_id)!==String(r.id))return {confirmed:false};
      if(assistantPanel?.personal?.state.delegated&&conv.status!=='closed')return {confirmed:false};
      await поОдному('lcz-created',async()=>{const c=await store.get('created',{});c[s.ctx.convId]={id:r.id,url:r.url,dir:r.workflow?.dir||s.ctx.dir,at:Date.now()};await store.set('created',c)});
      return {confirmed:true,result:{id:r.id}};
    },
    renameClient:async(s,r)=>{const d=await loadDialog(s.ctx.convId),client=d.conv.client;if(!client?.id)throw Error('Нет карточки клиента LeadChat');const name=nameWithId(client.name||'',r.id);if(name!==client.name)await LC.put('/clients/'+encodeURIComponent(client.id)+'/name',{name});const fresh=await loadDialog(s.ctx.convId);return {confirmed:fresh.conv.client?.name===name,result:{id:r.id}}},
    notifyCreated:async(s,r)=>{const w=r.workflow;if(!w?.followup?.required)return {confirmed:false,result:{id:r.id,telegram_confirmed:false}};const posts=await отписатьСозданную(r.id,{avito:true,reply:false,zakrepNot:false},w.followup.code,[],s.ctx.convId,w.dir,w.city);const confirmed=!!(posts.length&&posts.every(p=>p.ok));return {confirmed,result:{id:r.id,posts,telegram_confirmed:confirmed}}},
    reconcile:async(kind,entry,s)=>{
      const ctx=await assistantContext(s.ctx.convId);
      if(kind==='claim')return {confirmed:ctx.assigneeId===s.operatorId,result:{claimed:true}};
      if(kind==='rename_client'){const id=entry.operation_id.split(':').pop();return {confirmed:new RegExp('(?:^|\\D)'+id+'(?:\\D|$)').test(ctx.clientName||''),result:{id}}}
      if(kind==='reply'){
        const m=ctx.messages.find(x=>x.client_message_id==='lcp:'+entry.operation_id);
        return {confirmed:!!(m&&['sent','delivered','read'].includes(m.delivery_status)),result:{id:m?.id||''}};
      }
      if(kind==='link_crm')return {confirmed:!!(entry.result?.id&&String(ctx.crmRequestId)===String(entry.result.id)),result:entry.result};
      // A phone search alone cannot prove which attempt created a CRM record.
      // An unknown create remains stopped; never create another automatically.
      return {confirmed:false};
    }
  };
  async function openAssistant() {
    if(!личнаяВкладка){const r=await send({kind:'lcz-personal-tab',action:'open'});if(!r?.ok)throw Error(r?.error||'Не удалось открыть вкладку помощника');return}
    await personalIdentity();if(!LC.me)throw Error('Войдите в LeadChat');
    document.documentElement.classList.add('lcz-personal-page');
    const helperTitle='✦ Личный помощник · LeadChat';document.title=helperTitle;panel.setAttribute('aria-label','Личный помощник');
    if(!openAssistant._titleObserver){openAssistant._titleObserver=new MutationObserver(()=>{if(document.title!==helperTitle)document.title=helperTitle});openAssistant._titleObserver.observe(document.head,{childList:true,subtree:true})}
    if(!root.querySelector('[data-personal-layout]')){
      const style=document.createElement('style');style.dataset.personalLayout='1';style.textContent='.panel{width:100vw;max-width:100vw;border:0;box-shadow:none}.panel .ph{padding:20px 28px}.panel .pb{padding:24px;max-width:1180px;width:100%;margin:0 auto}.fab,.rb,.personal-launch,.card,.toasts{display:none!important}.assistant-view>*{min-width:0}@media(min-width:900px){.assistant-view{grid-template-columns:320px minmax(0,1fr);align-items:start}.assistant-view>[data-personal]{grid-column:1;grid-row:1/span 12}.assistant-view>:not([data-personal]){grid-column:2}}';root.append(style);
      const outside=document.createElement('style');outside.textContent='html.lcz-personal-page body{background:#0b0e0d!important}html.lcz-personal-page body>*{visibility:hidden!important}';document.head.append(outside);
    }
    if (формаЭтого()) await запомнитьДиалог().catch(() => {});
    hideCard();
    if (!assistantPanel) assistantPanel = LC_ASSISTANT_UI.create({ h, panel, header, send, currentId:()=>assistantSelectedId,
      loadContext: assistantContext, latestId: последнееСообщение,intakeGuard:personalIntakeGuard,replyIssue:LC_INTAKE.replyIssue,
      getIdentity:personalIdentity,getAuthors:()=>assistantNative.authors(),getProof:actor=>assistantNative.proof(actor),
      nativeRun:LC.me?.role==='admin'&&nativeTransport?nativeTransport:null,
      startPulse:личнаяВкладка?id=>send({kind:'lcz-personal-link',action:'start',connection_id:id}):undefined,
      stopPulse:личнаяВкладка?id=>send({kind:'lcz-personal-link',action:'stop',connection_id:id}):undefined,
      observer:LC.me?.role==='admin'?{list:options=>assistantNative.list(options),listCandidates:(source,options)=>assistantNative.candidates(source,options),
        openCandidate:id=>window.open(location.origin+'/chats/'+encodeURIComponent(id),'_blank','noopener'),takeover:row=>assistantNative.takeover(row)}:null,
      assertRunnable:(id,ctx)=>assistantPanel?.personal?.state.delegated?assistantNative.runnable(id,ctx):Promise.resolve(),
      loadQueue:personalQueue,onOpenDialog:async id=>{assistantSelectedId=id;return true},workflow:workflowAdapters,
      assertUnoccupied:async id=>{const r=await send({kind:'lcz-personal-occupied'});if(!r?.ok||!Array.isArray(r.ids))throw Error('Не удалось проверить ручную работу в браузере');if(r.ids.includes(id))throw Object.assign(Error('Диалог открыт вручную в основном LeadChat — бот ждёт освобождения'),{code:'manual_occupied'})},
      onPersonalStart:async()=>{AUTO.on=false;AUTO.gen++;await store.set('autoClaim',{on:false,max:AUTO.max,almost:AUTO.almost,followOn:AUTO.follow});rbLabel()},
      onUseFacts:null });
    await assistantPanel.open();
    if(!assistantPanel._eventsBound&&window.__lczRt?.on){assistantPanel._eventsBound=true;window.__lczRt.on(e=>assistantPanel?.wake(e))}
  }

  const STEPS = ['Диалог и карточка клиента', 'Разбор переписки (ИИ)', 'Форма CRM и номер по базам'];
  let stepT0 = 0, stepTimes = [], stepTimer = 0;
  function steps(i, label) {
    if (i === 0) { stepTimes = []; stepT0 = Date.now(); }
    else if (stepTimes.length < i) { stepTimes.push(((Date.now() - stepT0) / 1000).toFixed(1).replace('.', ',') + ' с'); stepT0 = Date.now(); }
    // текущий шаг — живые секунды: видно, что идёт, а не зависло (ИИ думает до 50 с)
    clearInterval(stepTimer);
    const сек = () => { const n = Math.floor((Date.now() - stepT0) / 1000); return n >= 1 ? n + ' с' : ''; };
    const идёт = h('span', { class: 'n mut' }, сек());
    panel.replaceChildren(h('div', { class: 'ph' }, header()),
      h('div', { class: 'pb' },
        h('ol', { class: 'steps' }, ...STEPS.map((t, k) => h('li', { class: k < i ? 'done' : k === i ? 'now' : 'wait' },
          h('span', { class: 'ic' }, k < i ? svg('check') : ''), h('span', { style: 'flex:1' }, k === i && label ? label : t),
          k === i ? идёт : k < i && stepTimes[k] ? h('span', { class: 'n mut' }, stepTimes[k]) : ''))),
        h('div', { class: 'n mut' }, 'Ничего не создаётся без вашего нажатия.')));
    const t = setInterval(() => { if (!идёт.isConnected) { clearInterval(t); return; } идёт.textContent = сек(); }, 1000);
    stepTimer = t;
  }
  function failed(text, code) {
    if (устарело(text)) {
      panel.replaceChildren(h('div', { class: 'ph' }, header()),
        h('div', { class: 'pb' }, h('div', { class: 'box warn' }, svg('warn'), h('div', { class: 'c' }, УСТАРЕЛО + '. Данные диалога не потеряются.'))),
        h('div', { class: 'pf' }, h('div', { class: 'row' }, h('button', { class: 'go', onclick: () => location.reload() }, 'Обновить страницу'))));
      return;
    }
    clearInterval(stepTimer);
    // нет токена мозга — «ещё раз» не поможет: кнопка ведёт в настройки (после сохранения токена вкладка узнает сама)
    const токен = code === 'token' || /Нужен токен/.test(String(text || ''));
    panel.replaceChildren(h('div', { class: 'ph' }, header()),
      h('div', { class: 'pb' }, h('div', { class: 'box bad' }, svg('warn'), h('div', { class: 'c' }, text))),
      h('div', { class: 'pf' }, h('div', { class: 'row' }, токен
        ? h('button', { class: 'go', onclick: () => send({ kind: 'lcz-options' }) }, 'Открыть настройки')
        : h('button', { class: 'go', onclick: () => collect() }, 'Попробовать ещё раз'))));
  }
  function closePanel() {
    if(личнаяВкладка){if(assistantPanel)assistantPanel.stop();send({kind:'lcz-personal-tab',action:'close'});return}
    // Закрытие и возврат в том же чате тоже сохраняют правки, как переход между диалогами.
    if (формаЭтого()) запомнитьДиалог().catch(() => {});
    panel.classList.remove('open');
    if(assistantPanel)assistantPanel.stop();
    const f = root.activeElement;
    if (f && panel.contains(f)) f.blur();                            // фокус в спрятанной панели — снимаем, LeadChat снова слышит свои клавиши
    if (!root.activeElement) слойLeadChat(false);
    if (ЗАДАЧИ.size) задачиНаВиду();                                 // панель закрыли посреди создания — ход в уведомлении
  }

  /* ---------- сборка ---------- */
  function ctxOf(d) {
    const conv = d.conv, item = объявлениеДиалога(conv);           // MAX — объявление диалога Авито этого клиента
    const cl = conv.client || {};
    return {
      messages: сообщенияРазбора(d.msgs, conv),
      // диалог и надёжность связи карточки: номер карточки мог назвать другой человек (LeadChat сам такой в заявку не отдаёт)
      convId: conv.id || '', link: { confidence: cl.link_confidence || '', conflict: cl.link_phone_conflict === true },
      identity: d.identity, cardPhone: conv.client && conv.client.phone,
      clientName: conv.client && conv.client.name, city: городОбъявления(item), cityRaw: сыройГород(item), knownCities: ГОРОДА_CRM, tz: поясОбъявления(item),
      itemTitle: item.title || '', itemUrl: item.url || '', accountTitle: каналИсточника(conv).title || '',
      channel: LC_EXTRACT.канал(conv), sourceAvailable: !!авитоДиалога(conv),
      sellerName: (conv.__lczAdvertiser || {}).sellerName || item.seller_name || '', adDescription: (conv.__lczAdvertiser || {}).description || '',
      partner: каналИсточника(conv).lead_partner_number || '', accountId: каналИсточника(conv).id || '',
      origin: каналИсточника(conv).lead_origin || '',
    };
  }

  /* сообщения для разбора: контакт MAX (номер во вложении) — словами клиента. Голосовое MAX с 12.10 LeadChat расшифровывает — ждём
     текст, как у Авито; диалог MAX от LeadChat до 12.10 (conv.новыйLC === false) — состояние у голосового MAX не передаём вовсе:
     расшифровки не будет, сразу «прослушайте» (LC_EXTRACT.голосовые) */
  const сообщенияРазбора = (msgs, conv) => {
    const безРасшифровкиMAX = !!conv && conv.новыйLC === false;
    return (msgs || []).map((m) => {
      const max = LC_EXTRACT.голосовоеMAX(m);
      return { id: m.id || '', direction: m.direction, sender_type: m.sender_type, body: LC_EXTRACT.сКонтактом(m), voice_transcript: m.voice_transcript,
        delivery_status: m.delivery_status || m.delivery || '', attachments: m.attachments || [],
        ...(max && безРасшифровкиMAX ? {} : { voice_transcript_status: m.voice_transcript_status || '' }), voice: LC_EXTRACT.голосовое(m),
        ...(max ? { voice_max: true } : {}), created_at: m.created_at };
    });
  };
  // голосовые диалога (ждём расшифровку / прослушайте) — по тем же сообщениям, что и разбор
  const голосовыеДиалога = (msgs, conv) => LC_EXTRACT.голосовые(сообщенияРазбора(msgs, conv));
  // объявление и канал-источник диалога: у Авито — свои; у MAX — диалога Авито этого клиента (не нашёлся — пусто)
  const объявлениеДиалога = (conv) => (LC_EXTRACT.каналMAX(conv) ? (авитоДиалога(conv) || {}).item || {} : (conv && conv.item) || {});
  const каналИсточника = (conv) => (LC_EXTRACT.каналMAX(conv) ? (авитоДиалога(conv) || {}).account || {} : (conv && conv.account) || {});

  /* Разбор диалога: LeadChat → ИИ → проверка. Возвращает {conv, lead, checks, lastId} */
  /* 2.0.9: разбор ИИ одного и того же состояния диалога — один на всех. Фоновая проверка открытого диалога и форма спрашивали ИИ
     каждая сама (открыл «Заявку», пока проверка ещё шла, — второй разбор, 5–30 с). Ключ — диалог и его последнее сообщение:
     клиент написал ещё — новый разбор. Запрос, уже идущий, форма просто дожидается (отмена проверки его не обрывает) */
  const РАЗБОРЫ = new Map();
  // (в ключе — и карточка LeadChat: адрес в неё LeadChat дописывает сам через ~90 с — тогда разбор нужен новый)
  const хэшСтроки = (t) => { let h = 5381; for (let i = 0; i < t.length; i++) h = ((h << 5) + h + t.charCodeAt(i)) | 0; return (h >>> 0).toString(36); };
  /* 2.1.7: сервер недоступен — разбор правилами здесь же, как это делает мозг без ИИ (brain/rules.js): телефон, адрес, время,
     голосовые; суть работы — пусто, проверка это покажет. Оператор видит пометку и проверяет поля */
  const БЕЗ_СЕРВЕРА = 'Сервер недоступен (сбой Yandex Cloud) — разобрано правилами без ИИ, проверьте поля';
  function разборПравилами(ctx0) {
    const ctx = { ...(ctx0 || {}), now: new Date() };
    const raw = ctx.cityRaw || ctx.city;
    if (LC_EXTRACT.латиницейГород(raw)) { const g = LC_EXTRACT.городПоРусски(raw, ctx.knownCities || ГОРОДА_CRM); ctx.cityRaw = raw; ctx.city = g.city; if (!ctx.tz && g.tz) ctx.tz = g.tz; }
    const msgs = (ctx.messages || []).filter(LC_EXTRACT.речь);
    const rr = LC_ADDR_RULES.parse(msgs, ctx.city);
    const ai = rr ? { street: rr.street, building: rr.house, settlement: rr.settlement, office: rr.flat, entrance: rr.entrance, floor: rr.floor, intercom: !!rr.intercom } : {};
    const r = LC_EXTRACT.validate(ai, ctx);
    return { ok: true, lead: r.lead, checks: [...r.checks, { field: 'ai', ok: false, note: БЕЗ_СЕРВЕРА }], rules: true, offline: true };
  }
  function разборИИ(id, lastId, ctx) {
    // голосовое расшифровалось (последнее сообщение то же, а текст у него появился) — разбор новый, а не прежний «ещё расшифровывается»
    const голос = (ctx.messages || []).filter((m) => m && m.voice).map((m) => (m.voice_transcript_status || '') + ':' + String(m.voice_transcript || '').length).join(',');
    const k = id + '|' + lastId + '|' + хэшСтроки(JSON.stringify({ ...ctx, messages: undefined, голос })), был = РАЗБОРЫ.get(k);
    if (был && Date.now() - был.at < 10 * 60e3) return был.p;
    const p = send({ kind: 'lcz-extract', ctx }).then((ex) => {
      if (ex && ex.ok === false && (ex.down || ex.недоступен)) { try { ex = разборПравилами(ctx); } catch (_e) { /* правила не справились — покажем ошибку сервера */ } }
      if (!ex || !ex.ok || ex.rules) РАЗБОРЫ.delete(k);                 // сбой или разбор правилами — следующий раз спросим заново
      return ex;
    }, (e) => { РАЗБОРЫ.delete(k); throw e; });
    РАЗБОРЫ.set(k, { p, at: Date.now() });
    for (const [kk, v] of РАЗБОРЫ) if (Date.now() - v.at > 10 * 60e3) РАЗБОРЫ.delete(kk);
    return p;
  }
  // conv0 — деталь, уже прочитанная перед разбором (collect): второй раз не просим
  function послеРазбора(ex,ctx){
    const refined=LC_EXTRACT.послеМозга(ex,ctx);
    if(!ex?.ok||!ex.contact_facts)return refined;
    // Legacy time/price refinements may rebuild the comment. Restore the
    // shared proven fields before initial form/customer preparation.
    return LC_WORKFLOW.projectContactFacts(refined,{ok:true,reviewed_policy:true,auto_enabled:false,
      facts:ex.contact_facts,policy_version:ex.policy_version},LC_EXTRACT.fromIdentity(ctx.identity,ctx.convId).rejected||[]);
  }
  async function analyze(id, onStep, conv0) {
    onStep && onStep(0);
    const d = await loadDialog(id, conv0);
    onStep && onStep(1);
    const c0 = ctxOf(d);
    const last0 = d.msgs[d.msgs.length - 1];
    const ex = послеРазбора(await разборИИ(id, last0 ? last0.id : '', c0), c0);   // «через час» до минуты, озвучки
    if (!ex.ok) throw new Error(ex.error);
    const last = d.msgs[d.msgs.length - 1];
    return { id, conv: d.conv, lead: ex.lead, checks: ex.checks, lastId: last ? last.id : '', ctx: ctxOf(d) };
  }

  async function уточнитьПодпись(A) {
    let conv = A.conv;
    const item = объявлениеДиалога(conv);
    const ctx = { ...(A.ctx || {}), accountTitle: каналИсточника(conv).title || '', itemTitle: item.title || '', itemUrl: item.url || '',
      channel: LC_EXTRACT.канал(conv), sourceAvailable: !!авитоДиалога(conv),
      sellerName: (conv.__lczAdvertiser || {}).sellerName || item.seller_name || '', adDescription: (conv.__lczAdvertiser || {}).description || '' };
    const r = await спросить({ kind: 'lcz-advertiser', args: { ctx, lead: A.lead } }, 15000, 'Подпись объявления').catch(() => null);
    if (r && r.ok && r.rule === 'jivo-2026-10-15-v1' && r.lead) {
      conv = { ...conv, __lczAdvertiser: r };
      return { ...A, conv, ctx: { ...ctx, sellerName: r.sellerName || ctx.sellerName, adDescription: r.description || ctx.adDescription }, lead: r.lead };
    }
    return { ...A, conv, ctx, lead: LC_EXTRACT.withAdvertiser(A.lead, ctx) };
  }

  // вид техники для территории: у ТВ нет дальнего выезда (принимаем только на филиал или спутник)
  const техника = (L, applText) => [L && L.device, ...((L && L.topics) || []), applText].filter(Boolean).join(', ');
  // территория по карте: не ждём дольше 9 с — и пишем, что карта не ответила, а не молчим
  const ТЕРР_ЖДЁМ = 9000;
  const территория = (args) => Promise.race([send({ kind: 'lcz-territory', args }), new Promise((res) => setTimeout(() => res({ ok: false, timeout: true,
    error: 'карта не ответила за ' + ТЕРР_ЖДЁМ / 1000 + ' с — проверьте территорию сами по карте' }), ТЕРР_ЖДЁМ))]);

  /* города CRM по базе — помним, чтобы знать спутники («Ачинск (Красноярск)» → основной филиал Красноярск) */
  const безСкобокГород = (x) => String(x || '').toLowerCase().replace(/ё/g, 'е').replace(/\s*\(.*?\)\s*/g, ' ').replace(/[\s\-–]+$/, '').replace(/\s+/g, ' ').trim();
  async function городCRM(dir, city) {
    const list = ((await store.get('crmCities', {}).catch(() => ({}))) || {})[dir] || [];
    // закрытый филиал («Белогорск (Благовещенск) -») сам не выбираем
    return list.find((t) => /\(/.test(t) && !LC_TERRITORY.закрытыйГород(t) && безСкобокГород(t) === безСкобокГород(city)) || '';
  }
  /* 2.0.7: есть ли город в базе dir (список городов CRM запоминается при каждой подготовке формы). null — список ещё не известен */
  async function городВБазе(dir, city) {
    const list = ((await store.get('crmCities', {}).catch(() => ({}))) || {})[dir];
    if (!Array.isArray(list) || !list.length || !city) return null;
    const c = безСкобокГород(city);
    return list.some((t) => !LC_TERRITORY.закрытыйГород(t) && безСкобокГород(t) === c);
  }
  // все города CRM всех направлений — чтобы «protvino» из LeadChat стало «Протвино» ещё до разбора
  let ГОРОДА_CRM = [];
  const городаВсе = (all) => [...new Set(Object.values(all || {}).flat().filter(Boolean))];
  store.get('crmCities', {}).then((all) => { ГОРОДА_CRM = городаВсе(all); }).catch(() => {});
  // город объявления: имя из справочника LeadChat; слага нет в справочнике — city_name пуст, берём сам слаг (латиницей)
  const сыройГород = (item) => String((item && (item.city_name || item.city_slug)) || '');
  const городОбъявления = (item) => LC_EXTRACT.городПоРусски(сыройГород(item), ГОРОДА_CRM).city;
  // пояс: из LeadChat; нет — по слагу из справочника расширения; нет и там — '' (подберётся по названию города, а не Москва молча)
  const поясОбъявления = (item) => (item && item.city_tz) || LC_EXTRACT.городПоРусски(сыройГород(item), []).tz || '';
  function запомнитьГородаCRM(dir, cities) {
    store.get('crmCities', {}).then((all) => {
      const texts = cities.map((o) => o.text).filter(Boolean);
      ГОРОДА_CRM = городаВсе({ ...all, [dir]: texts });
      if (!all[dir] || all[dir].length !== texts.length) return store.set('crmCities', { ...all, [dir]: texts });
    }).catch(() => {});
  }

  /* ПАМЯТЬ ДИАЛОГОВ: вышли из чата и вернулись — панель как была (поля, выбор, согласование), без нового разбора ИИ.
     В памяти вкладки — всё; на случай F5 — поля заявки и выбор в хранилище расширения (12 часов, до 40 диалогов). */
  const ПАМЯТЬ = new Map(), ПАМЯТЬ_МС = 12 * 3600e3;
  async function запомнитьДиалог() {
    if (!S || !S.id || !S.lead) return;
    try { keepEdits(); if (S.tg) keepTg(); } catch (_e) { /* панель уже закрыта */ }
    const state = S, id = state.id, at = Date.now();
    ПАМЯТЬ.set(id, { S: state, at });
    // Пока хранилище отвечает, оператор уже может открыть другой диалог.
    const draft = копия({ at, lead: state.lead, checks: state.checks, dir: state.dir, accId: state.accId || '', keepSel: state.keepSel || null, zkChoice: state.zkChoice || '', zkChoiceKey: (state.zakrep && state.zakrep.key) || state.zkChoiceKey || '', lastId: state.lastId || '',
      dirChosen: !!state.dirChosen, dirAuto: state.dirAuto || null, dirAutoChecked: !!state.dirAutoChecked, dirHint: state.dirHint || null });
    try {
      const all = await store.get('drafts', {});
      all[id] = draft;
      const keep = Object.keys(all).filter((k) => all[k] && Date.now() - all[k].at < ПАМЯТЬ_МС).sort((a, b) => all[b].at - all[a].at).slice(0, 40);
      await store.set('drafts', Object.fromEntries(keep.map((k) => [k, all[k]])));
    } catch (_e) { /* не запомнили — разберём заново */ }
  }
  async function последнееСообщение(id) {
    try { const m = последнееИз(await лента(id, 1)); return m ? m.id : ''; } catch (_e) { return ''; }
  }
  async function восстановить(id) {
    // по диалогу создаётся заявка — не форма (её уже отправили), а ход создания
    const идёт = задачаИдёт(id);
    if (идёт && convIdNow() === id) { hideCard(); показатьХод(идёт); return true; }
    const m = ПАМЯТЬ.get(id);
    let st = m && Date.now() - m.at < ПАМЯТЬ_МС ? m.S : null;
    if (!st) {
      const dr = (await store.get('drafts', {}))[id];
      if (!dr || !dr.lead || Date.now() - dr.at > ПАМЯТЬ_МС) return false;
      let dlg; try { dlg = await loadDialog(id); } catch (_e) { return false; }
      st = { id, conv: dlg.conv, lead: dr.lead, checks: dr.checks || [], dir: dr.dir, prep: null, accId: dr.accId, keepSel: dr.keepSel || undefined,
        zkChoice: dr.zkChoice || undefined, zkChoiceKey: dr.zkChoiceKey || '', lastId: dr.lastId, ctx: ctxOf(dlg), dirChosen: !!dr.dirChosen, dirAuto: dr.dirAuto || undefined, dirAutoChecked: !!dr.dirAutoChecked, dirHint: dr.dirHint || undefined };
      try { const rec = await tgSentGet(id); if (rec) st.tgSent = rec; } catch (_e) { /* без согласования */ }
    }
    if (convIdNow() !== id) return true;
    // своей записи о заявке нет — № из LeadChat (12.10: crm_request_id диалога; кадр сокета обновляет st.conv)
    st.created = (await store.get('created', {}))[id] || заявкаLC(st.conv);
    // форма из хранилища (после F5) не помнит, откуда ссылка для отзыва: ссылка канала LeadChat — снова она (видно, откуда)
    if (!st.autoLink && ссылкаКанала(st.conv) && (!st.lead.src_url || st.lead.src_url === ссылкаКанала(st.conv))) ссылкаИзКанала(st);
    const lastNow = await последнееСообщение(id);
    // пока ждали LeadChat, оператор ушёл в другой чат (форму возвращает и итог создания в фоне) — форму поверх чужого диалога не открываем
    if (convIdNow() !== id) return true;
    st.newer = !!(lastNow && st.lastId && lastNow !== st.lastId);     // клиент написал после разбора
    const advertiser = await уточнитьПодпись(st);
    if (convIdNow() !== id) return true;
    Object.assign(st, advertiser);
    S = st;
    // Черновик старой версии тоже получает новое правило, ручные уточнения сохраняются.
    S.lead = { ...LC_EXTRACT.withAdvertiser(S.lead, { ...ctxOf({ conv: S.conv, msgs: [] }), ...(S.ctx || {}) }),
      ad_identity_required: !LC_EXTRACT.каналMAX(S.conv) || !!авитоДиалога(S.conv) };
    // 13.10: «Прозвон» сам не ставится — разбор до 2.2.3 (черновик в памяти) ставил его сам: без щелчка оператора галочки нет
    if (S.lead && S.lead.call_check && !S.lead.call_marks_manual) S.lead = { ...S.lead, call_check: false };
    if (визитАвто(S.lead)) S.lead = сБлижайшимФормы(S.lead);            // своё время (ближайшее) не трогали — от «сейчас», а не от прошлого раза
    hideCard();
    panel.classList.add('open');
    if (S.prep && S.prep.ok && !S.готовлю) render(); else await prepare();   // ушли посреди подготовки формы — готовим заново
    if (S.tgSent) pollReplies().catch(() => {});
    return true;
  }
  /* «Где мастер?»: сколько сейчас в городе заявки, на когда она стоит и насколько мастер опаздывает */
  const ПОЯС_ДИАЛОГА = new Map();
  async function поясДиалога(id) {
    if (!id) return '';
    if (ПОЯС_ДИАЛОГА.has(id)) return ПОЯС_ДИАЛОГА.get(id);
    try {
      // пояс строки «Входящих» уже в кэше; деталь диалога (GET) — только если он открыт у оператора.
      // Пояса нет у LeadChat (город не из справочника) — по слагу объявления
      const c = (W.conv === id && W.meta && W.meta.conv) || (S && S.id === id && S.conv)
        || (convIdNow() === id ? await сТаймаутом(деталь(id), 4000, 'долго') : null);
      if (!c) return '';
      const tz = (c && поясОбъявления(объявлениеДиалога(c))) || '';
      ПОЯС_ДИАЛОГА.set(id, tz);
      return tz;
    } catch (_e) { return ''; }                                         // не запомнили — спросим в следующий раз; пока пояс по названию города
  }
  let ЖИВОЙ_ТАЙМЕР = 0;
  const сколько = (m) => (m >= 60 ? Math.floor(m / 60) + ' ч' + (m % 60 ? ' ' + (m % 60) + ' мин' : '') : m + ' мин');
  function визитСейчас(cr, tzДиалога) {
    const город = LC_TERRITORY.чистыйГород(cr.city || '');
    // пояс из объявления диалога надёжнее таблицы названий («Железногорск» бывает и Курский, и Красноярский)
    const tz = LC_EXTRACT.clientTz(tzДиалога || '', город).tz;
    const now = LC_EXTRACT.localParts(new Date(), tz);
    const out = { now: now.hm, city: город, visit: '', late: null, far: '' };
    const v = String(cr.visit || '');
    let m = v.match(/(\d{4})-(\d{2})-(\d{2})/), iso = '';
    if (m) iso = m[1] + '-' + m[2] + '-' + m[3];
    else if ((m = v.match(/(\d{1,2})[.-](\d{1,2})[.-](\d{4})/))) iso = m[3] + '-' + m[2].padStart(2, '0') + '-' + m[1].padStart(2, '0');   // CRM: «06-10-2026»
    if (!iso) return out;
    const t = (String(cr.visitTime || '').match(/^(\d{1,2}):(\d{2})/) || v.match(/(\d{1,2}):(\d{2})/) || [])[0] || '';
    const дни = Math.round((Date.parse(iso) - Date.parse(now.iso)) / 864e5);
    out.visit = (дни === 0 ? 'сегодня' : дни === 1 ? 'завтра' : дни === -1 ? 'вчера' : iso.slice(8, 10) + '.' + iso.slice(5, 7)) + (t ? ' в ' + t.padStart(5, '0') : '');
    if (!t) return out;
    const мин = Math.round((Date.parse(iso + 'T' + t.padStart(5, '0') + ':00Z') - Date.parse(now.iso + 'T' + now.hm + ':00Z')) / 60000);
    if (Math.abs(мин) > 12 * 60) out.far = мин < 0 ? 'дата визита прошла — проверьте перенос' : 'визит ещё не скоро';
    else out.late = -мин;                                              // > 0 — мастер опаздывает на столько минут
    return out;
  }
  function визитСтроки(cr, tz) {
    const x = визитСейчас(cr, tz);
    return [['В городе', x.now + (x.city ? ' · ' + x.city : '')],
      ['Заявка на', x.visit || 'время в CRM не нашлось'],
      x.late !== null ? [x.late > 0 ? 'Опоздание' : 'До визита', x.late > 0 ? сколько(x.late) : x.late === 0 ? 'время визита — сейчас' : сколько(-x.late), x.late > 0 ? 'warn' : ''] : null,
      x.far ? ['', x.far, 'warn'] : null,
      cr.status ? ['Статус', cr.status + (cr.prozvon ? ' · прозвон' : '')] : null].filter(Boolean);
  }
  const dlСтрок = (rows, attrs) => h('dl', { class: 'dl', ...(attrs || {}) }, ...rows.flatMap(([k, v, cls]) => [h('dt', {}, k), h('dd', { title: v, class: cls || '' }, v)]));

  /* по диалогу уже создана заявка — не форма создания, а итог: номер, CRM, действия.
     cr.изLC — своей записи нет, № стоит у диалога в LeadChat (заявкаLC): базы LeadChat не знает — вместо действий по базе
     «Найти заявку в CRM» (как кнопка «Действия»: заявки клиента по номеру во всех базах) */
  /* 2.2.3: № заявки из LeadChat без базы — база по CRM сама: заявки клиента по номеру во всех базах (как «Найти заявку в CRM»),
     среди них — с этим №. Ровно одна — запоминаем как свою запись (с базой и ссылкой) и сразу показываем действия по ней
     (отмена, перенос…), без лишнего нажатия. Не нашлась или № есть в двух базах — не угадываем, кнопка «Найти заявку в CRM» */
  const БАЗА_LC = new Map();
  function базаДляНомераLC(id, cr) {
    const k = id + '|' + cr.id, был = БАЗА_LC.get(k);
    if (был && Date.now() - был.at < 10 * 60e3) return был.p;
    const p = (async () => {
      const d = await loadDialog(id);
      const p10 = String(LC_EXTRACT.номерДляПоиска(ctxOf(d)).phone || '').replace(/\D/g, '').slice(-10);
      if (p10.length !== 10) return null;
      const x = await спросить({ kind: 'lcz-crm', op: 'existing', args: { phone: p10 } }, 60000, 'CRM');
      const f = ((x && x.ok && x.found) || []).filter((r) => String(r.id) === String(cr.id));
      if (f.length !== 1 || !f[0].dir) return null;
      const r = f[0];
      const rec = { ...cr, id: String(r.id), dir: r.dir, url: r.url || cr.url || '', status: r.status || cr.status || '', city: r.city || cr.city || '',
        visit: r.visit || cr.visit || '', visitTime: r.visitTime || cr.visitTime || '', изLC: true };
      try { const all = (await store.get('created', {})) || {}; if (!(all[id] && all[id].dir)) { all[id] = rec; await store.set('created', all); } } catch (_e) { /* только в памяти */ }
      return rec;
    })();
    БАЗА_LC.set(k, { at: Date.now(), p });
    p.then((r) => { if (!r) БАЗА_LC.set(k, { at: Date.now() - 8 * 60e3, p: Promise.resolve(null) }); }, () => БАЗА_LC.delete(k));
    return p;
  }
  function showCreated(id, cr) {
    panel.classList.add('open');
    if (cr && cr.изLC && cr.id && !cr.dir && !cr.базаИщем) {
      const ищем = { ...cr, базаИщем: true };
      базаДляНомераLC(id, cr).then((rec) => {
        if (convIdNow() !== id || S || !panel.classList.contains('open') || !panel.querySelector('.hero')) return;
        showCreated(id, rec || { ...cr, базаИщем: 'нет' });
      }).catch(() => { if (convIdNow() === id && !S && panel.querySelector('.hero')) showCreated(id, { ...cr, базаИщем: 'нет' }); });
      cr = ищем;
    }
    // пояс города диалога пришёл позже — перерисовываем, если панель всё ещё про эту заявку
    if (!ПОЯС_ДИАЛОГА.has(id)) поясДиалога(id).then((tz) => { if (tz && ПОЯС_ДИАЛОГА.has(id) && convIdNow() === id && !S && panel.classList.contains('open') && panel.querySelector('.hero')) showCreated(id, cr); }).catch(() => {});
    const когда = cr.at ? new Date(cr.at).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }).replace(',', ' в') : '';
    const визит = cr.visit ? cr.visit.replace(/^(\d{4})-(\d{2})-(\d{2})\s*/, '$3.$2 ').replace(/ (\d{2}:\d{2})$/, ' в $1').trim() : '';
    // перенос / отмена / где мастер — сразу карточка действия по этой заявке (статус и СД — из CRM)
    const действие = (intent, label, icon) => h('button', { class: 'act', onclick: async (e) => {
      const b = e.currentTarget; b.disabled = true; b.lastChild.textContent = 'Смотрю в CRM…';
      const i = await send({ kind: 'lcz-crm', op: 'info', args: { dir: cr.dir, id: cr.id } });
      if (convIdNow() !== id) return;                                  // ушёл в другой диалог, пока CRM отвечала: его панель не закрываем
      const info = (i && i.ok && i.info) || {};
      const r = { ...info, dir: cr.dir, id: String(cr.id), url: cr.url || info.url || '', city: cr.city || info.city || '', status: info.cardStatus || cr.status || '' };
      closePanel();
      showAdditionCard(id, { id: r.id, dir: r.dir, city: r.city, url: r.url, status: r.status, phone10: r.phone10 || '', prozvon: !!r.prozvon, service: r.serviceComment || '',
        visit: r.visit || cr.visit || '', visitTime: r.visitTime || cr.visitTime || '', at: Date.now(), seenAt: Date.now(), linked: true }, { intent, summary: '' }, Date.now());
    } }, svg(icon), h('span', {}, label));
    /* 1.20: действия — сетка по статусу заявки в CRM (снимок карточки); снимок не прочитался или модуля нет — прежние три плитки */
    const плитки = () => h('div', { class: 'acts' }, действие('перенос', 'Перенос', 'cal'), действие('отмена', 'Отмена', 'stop'), действие('где_мастер', 'Где мастер?', 'pin'));
    const сетка = ACT && cr.id && cr.dir ? ACT.сетка(cr, { where: 'created', conv: id, запасное: плитки }) : null;
    const найти = () => h('div', { class: 'acts' }, h('button', { class: 'act', 'data-lc-find': '1', title: 'Заявки клиента по номеру во всех базах CRM — и действия по ним', onclick: onActClick }, svg('pin'), h('span', {}, 'Найти заявку в CRM')));
    const откуда = [когда ? 'создана ' + когда : '', cr.изLC ? 'из LeadChat' : ''].filter(Boolean).join(' · ');
    const x = визитСейчас(cr, ПОЯС_ДИАЛОГА.get(id) || '');
    const строки = [['Город', cr.city], ['Визит', визит], визит && x.late !== null && x.late > -180 ? [x.late > 0 ? 'Опоздание' : 'До визита', x.late > 0 ? сколько(x.late) : сколько(-x.late)] : null,
      cr.city ? ['В городе', x.now] : null, ['Работа', cr.work], ['Источник', cr.src], ['Клиент CRM', cr.customerNote]].filter((r) => r && r[1]);
    panel.replaceChildren(h('div', { class: 'ph' }, header('заявка уже создана')),
      h('div', { class: 'pb' },
        h('section', { class: 'hero' },
          h('div', { class: 'hero-h' }, h('span', { class: 'badge' }, svg('check', true)),
            h('div', { style: 'min-width:0' }, h('div', { class: 'big' }, (cr.dir ? dirName(cr.dir) + ' № ' : 'Заявка № ') + (cr.id || '—')), откуда ? h('div', { class: 'n mut', ...(cr.изLC ? { 'data-src': 'lc' } : {}) }, откуда) : '')),
          строки.length ? h('dl', { class: 'dl' }, ...строки.flatMap(([k, v]) => [h('dt', {}, k), h('dd', { title: v }, v)])) : ''),
        h('p', { class: 'cap' }, сетка ? 'Действия по заявке' : 'Что сделать по заявке'),
        сетка || (cr.dir ? плитки() : cr.базаИщем === true ? h('div', { class: 'n mut', 'data-lc-base': 'busy' }, 'Ищу заявку № ' + cr.id + ' в CRM — какая база…') : найти()),
        // 2.1: сообщения в Telegram — строкой и словом (не только цветом точки)
        (cr.posts || []).length ? h('p', { class: 'cap' }, 'Сообщения в Telegram') : '',
        (cr.posts || []).length ? h('div', { class: 'plog' }, ...cr.posts.map((x) => h('div', { class: 'plr' + (x.off ? ' mut' : x.ok ? '' : ' bad') }, h('span', { class: 'd' }),
          h('span', { class: 'tx' }, x.text), h('span', { class: 'nx-s' }, x.off ? 'не отправлялось' : x.ok ? 'готово' : 'не ушло')))) : '',
        h('div', { class: 'n mut' }, cr.изLC && cr.dir ? 'Создавать заново не нужно: номер заявки стоит у диалога в LeadChat (её завели не в этом браузере), базу нашли в CRM.'
          : cr.изLC ? 'Создавать заново не нужно: номер заявки стоит у диалога в LeadChat (её завели не в этом браузере).' + (cr.базаИщем === 'нет' ? ' В CRM по номеру клиента заявка с этим № не нашлась сама — найдите её кнопкой.' : '')
          : 'Создавать заново не нужно. Если клиент допишет, перенесёт или отменит — расширение подскажет само.')),
      h('div', { class: 'pf' }, h('div', { class: 'row', style: 'gap:8px' },
        cr.url ? h('a', { class: 'go lnkgo', href: cr.url, target: '_blank', rel: 'noopener' }, 'Открыть в CRM', svg('ext')) : '',
        ПАМЯТЬ.has(id) ? h('button', { class: 'go2', onclick: () => восстановить(id) }, 'Показать форму') : ''),
        // вторая заявка — редкость: ссылкой и с подтверждением прямо здесь (без системного окна браузера)
        h('div', { class: 'row nx-again', 'data-again': '1' }, h('button', { class: 'sm ghost', onclick: (e) => {
          const box = e.currentTarget.closest('[data-again]');
          box.replaceChildren(h('span', { class: 'n warn', style: 'flex:1' }, 'По этому диалогу заявка уже есть. Собрать ещё одну?'),
            h('button', { class: 'sm', onclick: () => collect(null, true, true) }, 'Да, собрать'),
            h('button', { class: 'sm', onclick: () => showCreated(id, cr) }, 'Не надо'));
        } }, 'Создать ещё одну'))));
  }

  const РАЗБОР_СВЕЖ = 5 * 60e3;                                       // готовое из проверки готовности — форме не старше 5 мин
  // ещё — оператор уже подтвердил «Создать ещё одну» (итог «заявка уже создана»): «Создать» в форме второй раз не спрашивает
  async function collect(pre, fresh, ещё) {
    const id = convIdNow();
    if (!id || собираю) return;
    // по диалогу сейчас создаётся заявка — показываем ход создания: ни формы, ни нового разбора ИИ
    const идёт = задачаИдёт(id);
    if (идёт) { hideCard(); показатьХод(идёт); return; }
    // уже создана — показываем итог; была открыта раньше — возвращаем как была (без нового разбора). И из «Готовых» / карточки (pre):
    // заявку могли создать после их разбора (в фоне), а форму — поправить (правки оператора не подменяем разбором ИИ)
    if (!fresh) {
      try {
        const cr = (await store.get('created', {}))[id];
        if (cr && cr.id) { hideCard(); showCreated(id, cr); return; }
        if (await восстановить(id)) return;
      } catch (e) { if (устарело(e)) { panel.classList.add('open'); failed(УСТАРЕЛО); return; } /* иначе — разбираем заново */ }
    }
    собираю = true;
    hideCard();
    panel.classList.add('open');
    try {
      // разбор из «Готовых» / карточки устарел: клиент написал после проверки — форму по старому разбору не строим, разбираем заново
      if (pre && pre.id === id) {
        steps(0);
        const lastNow = await последнееСообщение(id);
        if (lastNow && pre.lastId && lastNow !== pre.lastId) pre = null;
      }
      // 12.10: своей записи о заявке нет (смотрели выше), а в LeadChat у диалога уже стоит № заявки (создали в другом браузере, другой
      // оператор, лид-центр) — итог «заявка уже создана», а не форма и не разбор ИИ. Деталь — тихим чтением, и разбору — она же
      // (второго запроса нет). Строку из «Готовых» сверяем и со свежей строкой «Входящих» (№ мог прийти кадром сокета). «Создать ещё одну» — fresh
      let conv0 = null;
      if (!fresh) {
        const изРазбора = pre && pre.id === id ? pre.conv : null;
        if (!изРазбора) { steps(0); conv0 = await деталь(id).catch(() => null); }
        const лц = conv0 ? заявкаLC(conv0) : заявкаLC(МГН.строки.get(id)) || заявкаLC(изРазбора);   // свежая деталь — главнее строк
        if (лц) { if (convIdNow() === id) showCreated(id, лц); return; }
      }
      const A = await уточнитьПодпись((pre && pre.id === id && !pre.поПравилам) ? pre : await analyze(id, steps, conv0));
      if (convIdNow() !== id) return;
      const conv = A.conv;
      const accId = conv.account && conv.account.id;
      // 2.1.1: источник (канал) к базе не привязан — выбор базы оператором больше не запоминается за каналом.
      // База канала — только если она в его названии («МНЧ …», «Компьютерная …»); нет — по смыслу работы
      // MAX — никогда: название — имя бота или номера (один бот на все базы)
      const dirКанала = LC_EXTRACT.базаКанала(conv) || '';
      // проверка «Входящих» уже выбрала базу по смыслу (работа не этой базы) — форма сразу в ней
      const выбор = ((await store.get('dirChoice', {}).catch(() => ({}))) || {})[id];
      // канал без базы в названии — база по смыслу работы сразу (и без проверки «Входящих»)
      const рекБ = выбор || typeof LC_WORK === 'undefined' ? null : !dirКанала ? базаПоСмыслу(A.lead, conv)
        : A.dir && A.dir !== dirКанала ? LC_WORK.направление(A.lead, dirКанала) : null;
      const dir = выбор && выбор.dir ? выбор.dir : рекБ && (!dirКанала || рекБ.dir === A.dir) ? рекБ.dir : dirКанала;
      // клиент время не назвал — ближайшее по регламенту (зона — из проверки готовности, если она той же базы; иначе пересчёт в prepare)
      S = { id, conv, lead: сБлижайшим(withSource(A.lead, conv, dir), A.dir === dir ? A.terr : null, A.dir === dir ? A.prep : null), checks: A.checks, dir, prep: null, accId, created: (await store.get('created', {}))[id] || заявкаLC(conv), ctx: A.ctx, lastId: A.lastId,
        ещёОк: !!ещё, ...(выбор && выбор.dir ? { dirChosen: true } : dir !== dirКанала ? { dirAuto: { from: dirКанала, to: dir, why: рекБ.why, работа: рекБ.работа } } : {}) };
      // проверка готовности (до 5 мин назад, та же база) уже подготовила форму CRM и территорию и искала номер — форма сразу, без второго круга
      if (A.prep && A.prep.ok && A.dir === dir && Date.now() - (A.at || 0) < РАЗБОР_СВЕЖ) { S.изРазбора = { prep: A.prep, terr: A.terr || null }; S.known = A.known ? { ...A.known, at: A.at } : null; }
      const ac = A.checks.find((c) => c.field === 'address');
      if (A.ctx && (!ac || !ac.ok || A.lead.addr_warn)) findAddr();      // LeadChat адрес не подтвердил — ищут два ИИ
      // источника нет в списке — ссылка канала из LeadChat (review_url; MAX — канала диалога Авито этого клиента); её нет — со страницы
      // продавца на Авито (MAX — по объявлению диалога Авито этого клиента; его нет — только вручную)
      if (!S.lead.src_url && !ссылкаИзКанала(S) && объявлениеДиалога(conv).url) getReviewLink();
      tgSentGet(id).then((rec) => { if (S && S.id === id && rec) { S.tgSent = rec; pollReplies(); } }).catch(() => {});
      await prepare();
    } catch (e) {
      failed('Не получилось: ' + (e.message || e));
    } finally {
      собираю = false;
    }
  }

  /* Источник канала LeadChat → «Комментарий партнёра»; ссылка для отзыва → строка 🟢ссылка🟢 в комментарии
     (формат «Чатерского»); партнёры 7/723/740/340/748 → галочка «Отзыв»; 723 и «Белый …» → 🔴БЕЛАЯ ЗАЯВКА🔴 */
  function linkLines(text, src, white) {
    const body = String(text || '').split('\n')
      .filter((l) => !/^🟢.*🟢$/.test(l.trim()) && !/БЕЛАЯ ЗАЯВКА/.test(l)).join('\n').trim();
    return [white ? '🔴БЕЛАЯ ЗАЯВКА🔴' : '', body, src && src.url ? '🟢' + src.url + '🟢' : ''].filter(Boolean).join('\n');
  }
  /* 2.1.1: в названии канала базы нет (за каналом её больше не запоминаем) — база по смыслу работы: стиральная — БТ, ноутбук — КП,
     смеситель — МНЧ. Белая заявка в БТ не уходит (регламент партнёра 723) — тогда базу выбирает оператор */
  function базаПоСмыслу(lead, conv) {
    if (typeof LC_WORK === 'undefined') return null;
    const w = LC_WORK.работа(lead || {});
    if (!w || !w.дом) return null;
    if (w.дом === 'bt' && белаяНаБТ(withSource(lead || {}, conv || {}, 'bt'), 'bt')) return null;
    return { dir: w.дом, why: w.что + ' — по регламенту это ' + dirName(w.дом), работа: w.что };
  }
  function withSource(lead, conv, dir) {
    const item = объявлениеДиалога(conv);
    lead = LC_EXTRACT.withAdvertiser(lead, { accountTitle: каналИсточника(conv).title || '', itemTitle: item.title || '',
      sellerName: (conv.__lczAdvertiser || {}).sellerName || item.seller_name || '', adDescription: (conv.__lczAdvertiser || {}).description || '' });
    // метка: что уже стоит в поле (оператор мог поправить), иначе источник канала LeadChat
    const origin = lead.partner_note_set ? lead.partner_note : (каналИсточника(conv).lead_origin || '');   // MAX — источник диалога Авито клиента
    const partner = lead.partner;
    const src = LC_LINKS.find(origin, dir, partner);
    const полный = src && !src.partner ? src.label : (src && src.partner && !origin ? src.label : String(origin).trim() || (src ? src.label : ''));
    // регламент 09.10: в «Комментарий партнёра» — только код источника («Б7 / С74.2 / В43»), без «источник», «белый» и т.п.
    // Поправленное оператором (partner_note_set) не трогаем. «Белый» запоминаем отдельно — по нему отзыв и запрет БТ
    const код = lead.partner_note_set ? '' : LC_TG.кодИсточника(полный);
    const note = код || полный;
    const белый = lead.partner_note_set ? !!lead.partner_note_white || белыйИсточник(note) : белыйИсточник(полный);
    return { ...lead, ad_identity_required: !LC_EXTRACT.каналMAX(conv) || !!авитоДиалога(conv), partner_note: note, partner_note_white: белый,
      partner_note_set: true, src_url: src ? src.url : '',
      review: LC_LINKS.requiresReview(partner) || (lead.review_set ? lead.review : отзывНужен(partner, src, полный)),
      comment: linkLines(lead.comment, src, LC_LINKS.isWhite(partner, src)) };
  }
  // источник «Белый Б6» / «723 парт Белый Б6» — белая заявка, даже если в списке этой базы его нет
  const белыйИсточник = (note) => /^\s*(?:723\s*парт\S*\s+)?белый(?![а-яё])/i.test(String(note || ''));
  // «Отзыв»: партнёры автоотзыва (7/723/740/340/748/624) и белые источники («Белый …», 723) — решение владельца
  const отзывНужен = (partner, src, note) => LC_LINKS.needsReview(partner) || LC_LINKS.isWhite(partner, src) || белыйИсточник(note);
  // белая заявка (партнёр 723 / источник «Белый …») на БТ не создаётся — только КП и МНЧ (регламент партнёра 723);
  // решение владельца: не молчаливый запрет, а предупреждение с «всё равно создать»
  const белаяНаБТ = (L, dir) => dir === 'bt' && !!L && (LC_LINKS.isWhite(L.partner, LC_LINKS.find(L.partner_note, dir, L.partner)) || белыйИсточник(L.partner_note) || !!L.partner_note_white);
  function render2keep() { keepEdits(); render(); }
  /* На экране форма ИМЕННО этого диалога. Закрытая панель (Esc, смена диалога) держит в DOM поля прежнего диалога —
     их нельзя ни читать в заявку нового (keepEdits), ни считать «формой уже на экране» (prepare, ответы фона) */
  const формаЭтого = () => !!S && !!panel.querySelector('[data-f="phone"]') && panel.dataset.conv === String(S.id || '');

  // что из формы уходит в заявку — одной строкой: поправил оператор форму после «Создать» или нет
  const отпечатокФормы = (f, dir) => { const L = f.lead || {}, a = L.addr || {}, x = f.sel || {};
    return JSON.stringify([dir, x.cityId, x.applId, x.subId, x.type, L.phone, L.name, (L.phones_extra || []).join(','), a.settlement, a.street, a.building, a.office, a.entrance, a.floor, !!a.intercom,
      L.visit_date, L.visit_time, !!L.call_check, !!L.call_before_visit, !!L.far_ride, !!L.urgent, L.comment, L.partner_note, !!L.review, !!L.phone_ok, !!f.allowLive]); };
  // правки оператора в полях не теряются, когда панель перерисовывается (смена города, вида работ…)
  // 2.1.1: адрес из прошлого обращения (addr_prev) — в силе, пока в форме тот же дом и оператор не подтвердил его у клиента
  const ФРАЗА_ПРОШЛЫЙ = /;?\s*адрес из прошлого обращения клиента[^;]*/;
  const прошлыйКарточки = (L) => { const p = L && L.addr_prev, a = (L && L.addr) || {}; if (!p || L.addr_prev_ok) return false;
    const н = (x) => String(x || '').toLowerCase().replace(/ё/g, 'е').replace(/[^а-яa-z0-9]/g, '');
    return н(a.street) === н(p.street) && н(a.building) === н(p.building) && н(a.settlement) === н(p.settlement); };
  /* 2.1.3 (рег:665, 775): у «Повтора» и «Гарантии» адрес сверяют с клиентом. Назван в этом диалоге (клиентом или оператором с ответом
     клиента) — сверен; нет (из карточки, вписан вручную) — тот же вопрос и то же «Клиент подтвердил», что у адреса из прошлого обращения */
  const адресНазван = (a, msgs) => !(a && (a.street || a.settlement)) || !Array.isArray(msgs) || LC_EXTRACT.названВДиалоге(a, msgs.filter(LC_EXTRACT.речь));
  const адресПовтора = (L) => !!L && !L.addr_prev_ok && !!S && !!S.ctx && /^(Повтор|Гарантия)$/.test(типЗаявки()) && !адресНазван(L.addr, S.ctx.messages);
  const прошлыйАдрес = (L) => прошлыйКарточки(L) || адресПовтора(L);
  function снятьПрошлый(ok) {
    if (!S || !S.lead || (!S.lead.addr_prev && !ok)) return;
    if (ok) S.lead.addr_prev_ok = true; else S.lead.addr_prev = null;
    S.lead.addr_warn = String(S.lead.addr_warn || '').replace(ФРАЗА_ПРОШЛЫЙ, '').replace(/^\s*;\s*/, '').trim();
  }
  function keepEdits() {
    if (!формаЭтого()) return;
    const f = readForm();
    S.отпечаток = отпечатокФормы(f, S.dir);                           // чем форма была при последнем чтении (сравнить со снимком «Создать»)
    const былПрозвон = { call_check: S.lead.call_check, call_before_visit: S.lead.call_before_visit };
    S.lead = { ...S.lead, ...f.lead };
    // галочки прозвона в разборе — как решили разбор и регламент (2+ дня — по дате); оператор щёлкнул сам — его выбор.
    // Иначе галочка «2+ дня» прилипала бы как «клиент просил» и не снималась при смене даты на завтра
    if (!S.lead.call_marks_manual) Object.assign(S.lead, былПрозвон);
    // «Дальний выезд» сам — от территории: адрес сменили, территорию пересчитали — галочка за новым расчётом.
    // Щёлкнул оператор — его выбор (far_ride_manual) не трогаем
    if (!S.lead.far_ride_manual) delete S.lead.far_ride;
    if (S.lead.addr_prev && !S.lead.addr_prev_ok && !прошлыйКарточки(S.lead)) снятьПрошлый(false);   // вписал другой адрес — вопрос снят
    // черновик согласования (текст, отмеченные чаты, выбор в списке) — тоже: фото клиента, ответ регламента не сбрасывают его
    if (S.tg && !S.tg.sending) keepTg();
  }

  /* ---------- журнал заявок за смену ---------- */
  async function showJournal(all) {
    if (формаЭтого()) запомнитьДиалог().catch(() => {});
    panel.classList.add('open');
    let j = [];
    try { j = await store.get('journal', []); } catch (e) { failed('Не получилось: ' + (e.message || e)); return; }
    const since = Date.now() - 14 * 3600 * 1000;                       // смена — последние 14 часов (и ночная тоже)
    const list = (all ? j : j.filter((x) => x.at >= since)).slice().reverse();
    const hm = (t) => new Date(t).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
    const dm = (t) => new Date(t).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' });
    const по = {}; for (const x of list) по[x.dir] = (по[x.dir] || 0) + 1;
    const итог = DIRS.filter(([d]) => по[d]).map(([d, n]) => n + ': ' + по[d]).join(' · ');
    /* 2.2.9: действия с заявками, которые CRM НЕ сделала (отказ, не всё, не знаю, заявка изменилась), — с ответом CRM: следующая жалоба
       «не работает отмена» — уже с причиной. Журнал действий (actLog) — без слов клиента; номер — заявки, телефоны маскированы */
    let действия = [];
    try {
      const a = (await store.get('actLog', {})) || {};
      действия = Object.values(a).filter((x) => x && x.at && (all || x.at >= since) && /^(отказ|частично|неясно|устарело|нет|причина)$/.test(x.state || ''))
        .sort((x, y) => y.at - x.at).slice(0, 30);
    } catch (_e) { действия = []; }
    const СОСТ = { отказ: 'не сделано', частично: 'сделано не всё', неясно: 'не знаю, прошло ли', устарело: 'заявка изменилась', нет: 'не сделано', причина: 'CRM просит причину' };
    const строкаДействия = (x) => [hm(x.at), dirName(x.dir), x.id ? '№' + x.id : '', x.title || x.act || 'действие', СОСТ[x.state] || x.state, x.итог || ''].filter(Boolean).join(' · ');
    const отчёт = () => [(all ? 'Заявки (все в журнале)' : 'Заявки за смену') + ': ' + list.length + (итог ? ' (' + итог + ')' : '')]
      .concat(list.slice().reverse().map((x) => [hm(x.at), dirName(x.dir), x.id ? '№' + x.id : 'без №', x.name, x.city, x.appl,
        x.manualReview ? 'Ручное создание с предупреждениями: '+x.manualReview.warnings.join('; ') : ''].filter(Boolean).join(' · ')))
      .concat(действия.length ? ['', 'Действия, которые CRM не сделала: ' + действия.length, ...действия.map(строкаДействия)] : []).join('\n');
    const rows = list.map((x) => h('div', { class: 'jr' },
      h('div', { class: 'jt' }, (all ? dm(x.at) + ' ' : '') + hm(x.at)),
      h('div', { style: 'min-width:0;flex:1' },
        h('div', {}, h('b', {}, dirName(x.dir) + ' '), x.id ? h('a', { href: x.url, target: '_blank', rel: 'noopener' }, '№ ' + x.id) : 'без номера',
          x.warns ? h('span', { class: 'n warn' }, ' · ⚠ ' + x.warns) : ''),
        h('div', { class: 'n mut' }, [x.name, x.city, x.sub || x.appl, x.visit ? 'визит ' + x.visit : ''].filter(Boolean).join(' · ')),
        x.manualReview ? h('details', { 'data-manual-review':'1',class:'n warn' },h('summary',{},'Создано с предупреждениями'),
          ...x.manualReview.warnings.map(t=>h('div',{},t)),h('div',{class:'mut'},'Решение оператора · регламент '+x.manualReview.policy_version)) : '')));
    const строкиДействий = действия.map((x) => h('div', { class: 'jr', 'data-act-fail': x.state },
      h('div', { class: 'jt' }, (all ? dm(x.at) + ' ' : '') + hm(x.at)),
      h('div', { style: 'min-width:0;flex:1' },
        h('div', {}, h('b', {}, dirName(x.dir) + ' '), x.id ? '№ ' + x.id + ' · ' : '', x.title || x.act || 'действие', h('span', { class: 'n warn' }, ' · ' + (СОСТ[x.state] || x.state))),
        x.итог ? h('div', { class: 'n mut' }, x.итог) : '')));
    panel.replaceChildren(h('div', { class: 'ph' }, header(all ? 'все заявки в журнале' : 'за смену (14 часов)')),
      h('div', { class: 'pb' },
        h('div', { class: 'box ' + (list.length ? 'ok' : 'warn') }, svg(list.length ? 'check' : 'warn'),
          h('div', { class: 'c' }, h('b', {}, (list.length || 'Нет') + (list.length ? ' — создано' : ' созданных заявок')), итог ? h('div', {}, итог) : '')),
        ...rows,
        ...(строкиДействий.length ? [h('div', { class: 'box warn', 'data-ac': 'act-fails' }, svg('warn'), h('div', { class: 'c' }, h('b', {}, 'Действия, которые CRM не сделала: ' + строкиДействий.length),
          h('div', {}, 'с ответом CRM — его можно скопировать «Скопировать отчёт» и прислать'))), ...строкиДействий] : [])),
      h('div', { class: 'pf' }, h('div', { class: 'row', style: 'gap:8px' },
        h('button', { class: 'go', onclick: async (e) => { try { await navigator.clipboard.writeText(отчёт()); e.target.textContent = 'Отчёт скопирован ✓'; } catch (_e) { e.target.textContent = 'Не скопировалось'; } } }, 'Скопировать отчёт'),
        h('button', { class: 'sq', title: all ? 'Только за смену' : 'Показать все', 'aria-label': 'Переключить период', onclick: () => showJournal(!all) }, all ? '14ч' : 'все'),
        S && S.lead ? h('button', { class: 'sq', title: 'Назад к заявке', 'aria-label': 'Назад к заявке', onclick: () => render() }, '←') : '')));
  }

  /* ---------- готовые к созданию: открытые диалоги, где есть всё и не нужно согласование ---------- */
  const READY = { run: 0, items: [], tab: 'mine', done: 0, total: 0, at: 0, gone: new Set(), note: null, ждёт: new Map(), каналы: new Map(), настройки: false };
  // 2.3: канал строки «Входящих» для «Готовых» — «Avito С74.2» / «MAX В43» (код источника канала; нет кода — название канала)
  function каналСтроки(id) {
    const x = READY.каналы.get(id) || ((МГН && МГН.строки && МГН.строки.get(id)) ? { account: МГН.строки.get(id).account, channel: МГН.строки.get(id).channel } : null);
    const a = x && x.account;
    if (!a) return '';
    const вид = /max/i.test(String(x.channel || '')) ? 'MAX' : 'Avito';
    const код = LC_TG.кодИсточника(a.lead_origin || '') || '';
    return вид + ' ' + (код || String(a.title || '').slice(0, 24));
  }
  // 5: с какого момента клиент ждёт ответа (waiting_since строки «Входящих»): из «слуха» или последнего чтения списка — только память вкладки
  function ждётС(id) {
    const r = МГН.строки.get(id);
    return Date.parse((r && r.waiting_since) || '') || READY.ждёт.get(id) || 0;
  }
  // 8: «почти» только из-за регламента в экономном режиме — это готово (регламент сверит форма); режим в строках не повторяем
  const толькоРегламент = (x) => !!x && x.st === 'almost' && /^добить: регламент — ИИ [^;]* — сверка при открытии формы$/.test(x.why || '');
  const безРежима = (x) => (толькоРегламент(x) ? 'готово, регламент — в форме' : String((x && x.why) || '').replace(/;\s*регламент — ИИ [^;]* — сверка при открытии формы/, ''));
  const ПОЧЕМУ = { phone: 'телефон', address: 'адрес', house: 'номер дома', time: 'дата/время', problem: 'суть проблемы', voice: 'прослушать голосовое',
    phone_check: 'сверить номер (карточка LeadChat под сомнением)', price: 'цена', lpr: 'нет ЛПР на адресе', territory: 'территория', reglament: 'регламент',
    intent: 'клиент ещё не согласился на выезд' };
  // визит строкой списка: «визит 08.10 15:00»; время не договорено — уже словами («ближайшее, визит ~19:30» → «визит ~19:30 (ближайшее)»)
  const визитСтрокой = (x) => { if (!x.time) return '';
    if (!/^(ближайшее|прозвон)/.test(x.time)) return 'визит ' + x.time;
    const с = x.time.replace(/^(ближайшее|прозвон),?\s*/, '');
    return с ? с + ' (ближайшее)' : 'визит — ближайшее'; };
  // оператор уже отказал клиенту («Не смогу туда приехать, к сожалению») — диалог не «готовый», не берём и не предлагаем
  const ОТКАЗ_ОПЕРАТОРА = /не\s+(с)?мо(жем|гу|жет)\s+(вам\s+|к\s+вам\s+|туда\s+|сейчас\s+|в\s+ваш\s+\S+\s+)*(приехать|выехать|подъехать|помочь|взяться)(?![^.!?]{0,20}(раньше|позже|сегодня|завтра|утром|дн[её]м|вечером|в\s*\d|к\s*\d|до\s*\d|после|удобно))|не\s+(выезжа|обслужива|работаем\s+(с|по|в)\s)|вынужден\S*\s+отказ|отказываемся|к\s+сожалению[^.!?]{0,40}\sне\s+(с)?мо/i;
  // не отказ, а встречное предложение: «к сожалению, в 10 не сможет, давайте в 12?», «не сможем сегодня, есть окно завтра»
  const ВСТРЕЧНОЕ = /(давайте|можем|могу|предлагаю|есть\s+(время|окно|мастер)|подойд[её]т|удобно|в\s*\d{1,2}|к\s*\d{1,2}|после\s*\d|раньше|позже|завтра|послезавтра|сегодня|утром|дн[её]м|вечером)/i;
  // «не можем», «не удобно» — не предложение
  const встречное = (t) => [...String(t || '').matchAll(new RegExp(ВСТРЕЧНОЕ.source, 'gi'))].some((x) => !/(^|[^а-яё])не\s*$/i.test(String(t).slice(Math.max(0, x.index - 4), x.index)));
  // условие, а не отказ: «Если мастер не сможет приехать вовремя — предупредит», «В случае если не сможем приехать, сообщим»
  const УСЛОВИЕ = /(^|[^а-яё])(если|в\s+случае|вдруг|чтобы)(?![а-яё])/i;
  const условие = (t, at) => УСЛОВИЕ.test(t.slice(0, at).split(/[.!?]/).pop());
  // Только собственная речь сотрудника: служебное событие, неотправленный текст
  // и цитата не доказывают ни отказ, ни уже созданную нами заявку.
  function наблюдённаяРечьОператора(msgs) {
    const неРечьОператора = new Set(['system', 'bot', 'avito', 'assistant', 'client', 'customer', 'user', 'contact', 'lead']);
    const неОтправлено = new Set(['pending', 'queued', 'sending', 'failed', 'error', 'cancelled', 'canceled']);
    return (msgs || []).filter((m) => m && m.direction === 'out' && LC_EXTRACT.речь(m)
      && [m.sender_type, m.role, m.speaker_role].every((role) => !неРечьОператора.has(String(role || '').toLowerCase()))
      && !неОтправлено.has(String(m.delivery_status || m.delivery || '').trim().toLowerCase())
      && String(m.body || '').trim()).map((m) => ({ ...m,
      literal: String(m.body).replace(/«[^»]*»|“[^”]*”|"[^"\n]*"|^>[^\n]*$/gm, (quote) => ' '.repeat(quote.length)) }));
  }
  function отказалОператор(msgs) {
    const out = наблюдённаяРечьОператора(msgs).slice(-3);
    for (let k = 0; k < out.length; k++) {
      const t = out[k].literal.trim();
      const x = [...t.matchAll(new RegExp(ОТКАЗ_ОПЕРАТОРА.source, 'gi'))].find((y) => !условие(t, y.index) && !встречное(t.slice(y.index + y[0].length)));
      if (!x || /\?\s*$/.test(t)) continue;
      // после отказа оператор сам предложил другое время («Завтра в 12 можем») — это встречное предложение
      if (out.slice(k + 1).some((y) => встречное(y.literal) && /\d/.test(y.literal))) continue;
      return String(out[k].body).trim().slice(0, 80);
    }
    return '';
  }
  /* ЛИД-БОТ: в CRM заявку заводит очередь лид-бота (расширение «Автозаявки») — и только по диалогам, которые он сам
     признал собранными (LeadChat: bot_vars.lead_ready, заметка «🤖 Лид-бот считает заявку собранной», сводка
     «заявка собрана — бот закрыл»). Тогда наша заявка может стать дублем: автоприём такой диалог не берёт,
     а перед созданием номер ещё раз ищется во всех базах CRM. Подсказки бота (заметки «Подсказка бота: …»),
     приветствия сценариев и передача диалога человеку дублем не грозят — это обычные диалоги. */
  /* заметка бота при закрытии собранной заявки (LeadChat app/bots/engine.py, close_by_leadbot): «🤖 Заявка собрана и передана —
     диалог закрыт ботом». bot_vars.lead_ready LeadChat сам не пишет (оставлено — вреда нет, вдруг начнёт) */
  const ЛИДБОТ_ГОТОВ = /Лид-бот считает заявку собранной|заявка собрана\s*[—–-]\s*бот закрыл|заявка собрана и передана\s*[—–-]\s*диалог закрыт ботом/i;
  function лидБот(msgs, conv) {
    const m = msgs || [], bv = (conv && conv.bot_vars) || {};
    const готов = m.some((x) => ЛИДБОТ_ГОТОВ.test(String(x.body || ''))) || !!bv.lead_ready;
    if (!готов) return null;
    return { готов, why: 'лид-бот считает заявку собранной — её мог уже завести он' };
  }
  // заявка в «Модерации» — не просто «есть заявка»: регламент велит взять её в работу и сохранить
  const естьЗаявка = (o) => 'у клиента есть заявка № ' + o.id + ' (' + dirName(o.dir) + ')' + (/^Модерац/i.test(o.status || '') ? ' в Модерации — возьмите её в работу и сохраните' : '');
  /* БЕЗ ЗАВИСАНИЙ: у каждого запроса к фону свой срок. Не ответил — понятная ошибка «… не ответил за N с» (проверю ещё раз),
     а не вечное «Проверяем…». Таймер снимается сразу после ответа */
  function спросить(msg, мс, что) {
    let t = 0;
    const срок = new Promise((res) => { t = setTimeout(() => res({ ok: false, timeout: true, error: что + (/^CRM/.test(что) ? ' не ответила' : ' не ответил') + ' за ' + Math.round(мс / 1000) + ' с' }), мс); });
    return Promise.race([send(msg), срок]).finally(() => clearTimeout(t));
  }
  /* ШАГИ ПРОВЕРКИ — общий кэш (обещание на ключ): «Готовые», автоприём и карточка в диалоге не спрашивают CRM и карту
     дважды за одно и то же. Неудача (ok:false, ошибка) не запоминается — в следующий раз спросим снова.
     Заявки клиента — 3 мин; территория, подготовка формы CRM и регламент — 10 мин (регламент — до нового сообщения) */
  const ШАГИ = new Map();
  // заявка по номеру создалась (или могла): прежние ответы поиска CRM по нему (ключи 'ex|<10 цифр>|…') — устарели
  function забытьПоискCRM(phone) {
    const p10 = String(phone || '').replace(/\D/g, '').slice(-10);
    if (p10.length !== 10) return;
    for (const k of [...ШАГИ.keys()]) if (k.startsWith('ex|' + p10 + '|')) ШАГИ.delete(k);
  }
  function шаг(ключ, мс, fn) {
    const now = Date.now(), был = ШАГИ.get(ключ);
    if (был && now - был.at < был.мс) return был.p;
    if (ШАГИ.size > 300) for (const [k, v] of ШАГИ) if (now - v.at > 10 * 60e3) ШАГИ.delete(k);
    const запись = { at: now, мс, p: null };
    const убрать = () => { if (ШАГИ.get(ключ) === запись) ШАГИ.delete(ключ); };
    запись.p = Promise.resolve().then(fn);
    запись.p.когда = now;                                             // когда спросили: ответ из кэша — не «сейчас»
    запись.p.then((r) => { if (!r || r.ok === false) убрать(); }, убрать);
    ШАГИ.set(ключ, запись);
    return запись.p;
  }
  const когдаШаг = (p) => (p && p.когда) || Date.now();
  const исход = (base, st, why, extra) => ({ ...base, st, why: String(why || ''), флаги: [], ...(extra || {}) });
  const СОМНЕНИЕ = { цена: 'цена не принята', подумает: 'клиент сказал, что подумает', выбирает: 'клиент ещё выбирает мастера' };
  async function проверитьДиалог(row, стоп) {
    const id = row.id, base = { id, name: (row.client && row.client.name) || row.client_name || '', inbox: !!(row._inbox || row.in_inbox) };
    const мояЗаявка = (await store.get('created', {}))[id];
    // 12.10: у строки уже № заявки в LeadChat — «заявка уже есть» без чтения переписки, CRM и ИИ (то же правило — в разобратьГотовность)
    const лц = !мояЗаявка && заявкаLC(row);
    if (лц) return исход(base, 'exists', 'в LeadChat у диалога уже стоит № ' + лц.id, { добрать: [], crmLC: лц.id });
    const d = await loadDialog(id, row);                            // строка «Входящих» и есть диалог — без GET /conversations/{id}
    return разобратьГотовность(d, base, { мояЗаявка, стоп });
  }
  /* ГОТОВНОСТЬ ДИАЛОГА — один разбор для «Готовых», автоприёма и карточки в открытом диалоге. Правило владельца (26.08, Leadbot):
     заявка — телефон, адрес и договорённое время («полная») или телефон и адрес, а время клиент поручил созвону (вид «прозвон»: 13.10 —
     заявка на ближайшее по регламенту, «Прозвон» оператор ставит сам, если нужно).
     Регламент: цена «от N» озвучена и принята, ЛПР на адресе, юрлицо по счёту — согласование. Лучше «почти», чем неверное «готова».
     Порядок: передача → ждём → заявка уже есть / дописал по заявке → оператор отказал → клиент отказался → клиент думает →
     согласование → не хватает данных → почти → готово; сбой CRM / ИИ / карты / регламента — «ошибка, проверю ещё раз».
     o: { мояЗаявка, стоп — {да:true} отменяет устаревшую проверку, безПоиска — оператор сказал «создать новую»,
          вДиалоге — карточка открытого диалога: сначала CRM, ИИ — только если заявки нет (и без разбора «дописал») } */
  // номер → когда CRM последний раз нашла по нему открытую заявку (в памяти вкладки; только время, без данных клиента)
  const ОТКРЫТАЯ_У_НОМЕРА = new Map();
  async function разобратьГотовность(d, base, o) {
    o = o || {};
    if(o.личноеНаправление&&!['kp','bt','mnc'].includes(o.личноеНаправление))throw Error('Неизвестное направление личной заявки');
    const стоп = () => { if (o.стоп && o.стоп.да) throw new Error('проверка отменена — устарела'); };
    const id = base.id;
    { const tz0 = поясОбъявления(объявлениеДиалога(d.conv)); if (tz0) ПОЯС_ДИАЛОГА.set(id, tz0); }
    base.name = base.name || (d.conv.client && d.conv.client.name) || '';
    const флаги = [], добрать = [];
    let направление = '';                                            // известно после канала — в итог (карточке нужен источник)
    let смысл = null;                                                // 2.1.1: заявка ли это по смыслу (правила) — в итог: { вид, тип, согласие, сила }
    const пометить = (t) => { if (t && !флаги.includes(t)) флаги.push(t); };
    const итог = (st, why, extra) => исход(base, st, why, { флаги: флаги.slice(), добрать: добрать.slice(), ...(направление ? { dir: направление } : {}), ...(смысл ? { заявка: смысл } : {}), ...(extra || {}) });
    // 12.10: своей записи нет, а в LeadChat у диалога уже стоит № заявки (crm_request_id: создали в другом браузере, другой оператор,
    // лид-центр) — «заявка уже есть» сразу: без поиска в CRM, без ИИ и без ожидания расшифровки. «Дописал по заявке» не разбираем —
    // базы заявки LeadChat не знает (своя запись есть — как раньше, ниже: по ней и «дописал»)
    const лц = !o.мояЗаявка && заявкаLC(d.conv);
    if (лц) return итог('exists', 'в LeadChat у диалога уже стоит № ' + лц.id, { crmLC: лц.id });
    // голосовое ещё расшифровывается — в нём может быть номер, адрес или перенос: разбирать рано (и в CRM пока не ходим)
    if (голосовыеДиалога(d.msgs, d.conv).wait) return итог('wait', 'голосовое ещё расшифровывается — посмотрю через минуту', { retry: true });
    if (o.мояЗаявка) {
      const f = o.мояЗаявка.id && await поЗаявке(d, base, [{ ...o.мояЗаявка, open: true, status: '' }]);
      стоп();
      return f ? { флаги: [], добрать: [], ...f } : итог('exists', 'заявка уже создана');
    }
    const отказ = отказалОператор(d.msgs);
    if (отказ) return итог('refused', 'оператор уже отказал клиенту: «' + отказ + '»');

    // --- чтение без ИИ и без сети: последнее слово клиента, номер (то же правило, что у заявки), похоже ли на адрес
    const ctx = ctxOf(d);
    if(o.личноеНаправление)Object.assign(ctx,{dir:o.личноеНаправление,dirBasis:'server',partner:o.личныйЧерновик?.lead?.partner||ctx.partner,personalPolicy:o.личныйЧерновик?.policy_version||''});
    const Ч = LC_EXTRACT.прочитатьДиалог(ctx.messages, { now: Date.now() });
    // 2.1.1 по смыслу, а не «есть номер»: ищет работу, реклама, спам, товар, только совет, не туда, не наша услуга — не заявка (ИИ не зовём);
    // заявка — беда и шаг к выезду (просит мастера, согласился, дал адрес / время на вопрос оператора)
    const З = LC_EXTRACT.заявкаЛи(ctx.messages, { now: Date.now(), чтение: Ч });
    смысл = { вид: З.вид, тип: З.тип, согласие: З.согласие, сила: З.сила };
    const номер = o.личныйЧерновик?.facts ? {phone:o.личныйЧерновик.facts.contact_phone_to_use||'',сомнение:!!o.личныйЧерновик.facts.phone_needs_confirmation} : LC_EXTRACT.номерДляПоиска(ctx);
    const phone10 = String(номер.phone || '').replace(/\D/g, '').slice(-10);
    // направление — по каналу (нужно заранее: база этого направления обязана ответить)
    // строка «Входящих» (не открытый диалог): мозг знает, что это очередь (purpose:'inbox'); в economy / rules — без ИИ:
    // разбор правилами (мозг), без выбора вида работ ИИ и без регламента (он — при открытии формы)
    const режимИИ = o.вДиалоге ? '' : await режимМозга();
    const безИИ = !!o.проверенныйРазбор||/^(economy|rules)$/.test(режимИИ);
    стоп();
    // 2.1.1: база канала — только по его названию (за каналом выбор оператора не запоминается); нет в названии — по смыслу, после разбора
    let dir = o.личноеНаправление || LC_EXTRACT.базаКанала(d.conv) || '';                  // MAX — база только по смыслу
    направление = dir;
    // № заявки в имени клиента (так чатеры подписывают после создания) или оператор уже писал о созданной заявке
    const номераИмени = [...new Set(String(base.name).match(/(?<!\d)\d{6,8}(?!\d)/g) || [])];
    const номерВИмени = номераИмени[0] || '';
    const текстОператора = наблюдённаяРечьОператора(d.msgs).map((m) => m.literal).join('\n');
    const операторПисал = /заявк\S*\s*(№|номер)?\s*\d{6,8}(?!\d)|заявк\S*\s+(создан|оформлен)|(создал|оформил)\S*\s+заявк/i.test(текстОператора);
    // какие номера заявок оператор назвал клиенту («Заявка № 1055000 создана»)
    const номераОператора = [...new Set([...текстОператора.matchAll(/заявк\S*\s*(?:№|номер)?\s*(\d{6,8})(?!\d)/gi)].map((x) => x[1]))];
    const речь = ctx.messages.filter(LC_EXTRACT.речь);
    const входящих = речь.filter((m) => m.direction === 'in').length;
    // адрес в карточке или распознанный LeadChat в ЭТОМ диалоге; иначе — похоже на адрес в словах клиента, голосовых и заметках
    const hasAddr = !!o.личныйЧерновик?.facts?.address?.building || LC_EXTRACT.адресВКарточке(d.identity, id)
      || LC_EXTRACT.естьАдрес(речь.filter((m) => m.direction === 'in' || m.direction === 'note').map((m) => (m.body || '') + ' ' + (m.voice_transcript || '')).join('\n'));

    // --- параллельно: заявки клиента в CRM (все базы) и разбор ИИ (в открытом диалоге ИИ — только когда заявки нет)
    // ключи шагов — всё, от чего зависит ответ (имя — номера заявок в нём; диалог — его слова у формы и регламента): чужой ответ не берём
    const искать = (p10, безИмени) => шаг('ex|' + p10 + '|' + (безИмени ? '' : base.name) + '|' + dir, 3 * 60e3,
      () => спросить({ kind: 'lcz-crm', op: 'existing', args: { phone: p10, name: безИмени ? '' : base.name, dir } }, 40e3, 'CRM'));
    const exiP = !o.безПоиска && (phone10.length === 10 || номерВИмени) ? искать(phone10) : null;
    // номер карточки, который НЕ взят (карточка под сомнением, взят номер этого диалога): живая заявка по нему — может быть, тот же человек
    const другой10 = String(номер.другой || '').replace(/\D/g, '').slice(-10);
    const другойP = !o.безПоиска && другой10.length === 10 && другой10 !== phone10 ? искать(другой10, true) : null;
    // открытый диалог — тот же разбор, что возьмёт форма (разборИИ); строка «Входящих» — свой (purpose: inbox)
    const последнее = d.msgs[d.msgs.length - 1];
    const разобрать = () => o.проверенныйРазбор?Promise.resolve(копия(o.проверенныйРазбор)):(o.вДиалоге
      ? сТаймаутом(разборИИ(id, последнее ? последнее.id : '', ctx), 50e3, 'ИИ (разбор переписки) не ответил за 50 с')
        .catch((e) => ({ ok: false, timeout: /не ответил/.test(String(e && e.message)), error: String((e && e.message) || e) }))   // как спросить()
      : спросить({ kind: 'lcz-extract', ctx: { ...ctx, purpose: 'inbox' } }, 50e3, 'ИИ (разбор переписки)'))
      // 2.1.7: сервер недоступен — «Входящие» разбираются правилами здесь же (аварийный режим)
      .then((ex) => (ex && ex.ok === false && (ex.down || ex.недоступен) ? разборПравилами(ctx) : ex))
      .then((ex) => послеРазбора(ex, ctx));                                             // «через час» до минуты, озвучки

    // ИИ вместе с CRM — ради скорости новой заявки. Но у номера недавно была открытая заявка (прошлая проверка этой строки) или в имени /
    // словах оператора уже № заявки — почти наверняка «заявка уже есть»: сначала CRM, разбор ИИ (платный) — только если её нет
    const скорееЕсть = (phone10.length === 10 && Date.now() - (ОТКРЫТАЯ_У_НОМЕРА.get(phone10) || 0) < 30 * 60e3) || !!номерВИмени || операторПисал;
    const aiP = !o.вДиалоге && !скорееЕсть && phone10.length === 10 && (hasAddr || входящих >= 2) && !Ч.отказ && !Ч.сомнение && З.вид !== 'не_заявка' ? разобрать() : null;
    // запущенное заранее может не понадобиться (заявка уже есть, отказ) — его сбой не «необработанный»; где ждём — там и узнаем
    for (const p of [aiP, другойP]) if (p) p.catch(() => {});

    // --- заявки клиента
    const неБазы = (x) => (x.unchecked || []).filter((u) => !dir || u.dir === dir);
    const ошибкаCRM = (x) => (!x || !x.ok ? итог('error', 'CRM не ответила (' + String((x && x.error) || 'нет ответа').slice(0, 60) + ') — не беру, вдруг заявка уже есть; проверю ещё раз', { retry: true })
      : неБазы(x).length ? итог('error', 'база ' + неБазы(x).map((u) => dirName(u.dir)).join(', ') + ' не проверилась (' + String(неБазы(x)[0].error || '').slice(0, 50) + ') — не беру, вдруг заявка уже есть; проверю ещё раз', { retry: true }) : null);
    const другиеБазы = (x) => { for (const u of (x.unchecked || []).filter((y) => dir && y.dir !== dir)) пометить('база ' + dirName(u.dir) + ' не проверена (' + String(u.error || '').slice(0, 50) + ') — сверьте вручную'); };
    let exi0 = null, rows = [];
    if (exiP) {
      exi0 = await exiP;
      стоп();
      const сбой = ошибкаCRM(exi0);
      if (сбой) return сбой;
      другиеБазы(exi0);
      rows = exi0.found || [];
      if (phone10.length === 10) { if (rows.some((r) => r.open)) ОТКРЫТАЯ_У_НОМЕРА.set(phone10, Date.now()); else ОТКРЫТАЯ_У_НОМЕРА.delete(phone10); }
      if (rows.length) {
        const o1 = rows.find((r) => r.open);
        // номер карточки под сомнением: по нему заявку не продолжаем и не связываем — только «сверьте номер»
        if (номер.сомнение) { if (o1) return итог('exists', 'номер карточки LeadChat под сомнением: по нему есть заявка № ' + o1.id + ' (' + dirName(o1.dir) + ') — сверьте номер с клиентом', { crm: exi0, dir }); }
        else {
          if (!o.вДиалоге) {
            const f = await поЗаявке(d, base, rows);
            стоп();
            if (f) return { флаги: флаги.slice(), добрать: [], ...f, crm: exi0, dir: f.dir || dir };
          }
          if (o1) return итог('exists', естьЗаявка(o1), { crm: exi0, dir });
        }
      }
    }
    // № в имени клиента (правило владельца 04.10) или оператор писал о заявке: CRM подтвердила, а заявки закрыты — это клиент
    // с прошлыми заявками (Повтор), идём дальше; не подтвердила — заявка уже есть (не создаём вторую). Подтвердить — КАЖДЫЙ
    // названный номер (в имени и в словах оператора): «Заявка № 1055000 создана», а CRM нашла только старую закрытую — это не Повтор
    const нашлась = (n) => rows.some((r) => String(r.id) === n);
    const неНайден = номераИмени.find((n) => !нашлась(n)) || '';
    const подтверждено = !неНайден && (!операторПисал || (номераОператора.length ? номераОператора.every(нашлась) : rows.length > 0));
    if (!o.безПоиска && (номерВИмени || операторПисал) && !подтверждено) return итог('exists', неНайден ? 'в имени клиента № ' + неНайден + ' — заявка уже создана'
      : 'оператор уже писал о созданной заявке' + (номераОператора.length ? ' (№ ' + номераОператора.join(', ') + ')' : ''));
    // названная заявка (в имени или словами оператора) — САМАЯ СВЕЖАЯ из найденных CRM. Отменена / «Не оформлена» — это не «клиент с
    // прошлыми заявками»: её только что убрали в отмену (или клиент снова хочет мастера) — новую не создаём, по регламенту её возвращают
    // в «Ожидает». Выполнена / закрыта — как раньше: Повтор, идём дальше
    const названные = new Set([...номераИмени, ...номераОператора]);
    const свежая = rows.filter((r) => названные.has(String(r.id))).sort((p, q) => Number(q.id) - Number(p.id))[0];
    if (!o.безПоиска && свежая && /отмен|не оформлен|не создан/i.test(свежая.status || '')) return итог('exists', 'по клиенту заявка № ' + свежая.id + ' — «' + свежая.status
      + '»: новую не создаём. Клиент снова хочет мастера — по регламенту верните № ' + свежая.id + ' в «Ожидает» (или создайте новую в панели)', { crm: exi0, dir });
    // последнее слово клиента — после CRM: «отмените» по уже созданной заявке — это «дописал по заявке», а не отказ
    if (Ч.отказ) return итог('declined', 'клиент отказался: «' + Ч.отказ + '» — заявку не создаём (исход «Не создана»)');
    if (Ч.сомнение) return итог('doubt', СОМНЕНИЕ[Ч.сомнение.вид] + ': «' + Ч.сомнение.text + '»');
    // не заявка по смыслу — «Остальные», не берём, ИИ не тратим (и номер, и адрес тут ничего не решают)
    if (З.вид === 'не_заявка') return итог('other', 'не заявка: ' + (LC_EXTRACT.ТИП_НЕ_ЗАЯВКИ[З.тип] || З.тип) + (З.text ? ' — «' + З.text.slice(0, 90) + '»' : ''));
    if (phone10.length !== 10) return итог('missing', 'нет телефона', { ttl: 120e3 });
    if (!hasAddr && входящих < 2) return итог('missing', 'нет адреса', { ttl: 120e3 });

    // --- разбор ИИ
    const ex = await (aiP || разобрать());
    стоп();
    if (!ex || !ex.ok) return итог('error', 'разбор ИИ не удался (' + String((ex && ex.error) || 'нет ответа').slice(0, 80) + ') — проверю ещё раз', { retry: true });
    const L0 = копия(ex.lead || {});
    if(o.личныйЧерновик?.lead?.partner)L0.partner=o.личныйЧерновик.lead.partner;
    if(o.личныйЧерновик?.facts){L0.phone=o.личныйЧерновик.facts.contact_phone_to_use;L0.addr=копия(o.личныйЧерновик.facts.address);L0.comment=LC_WORKFLOW.contactComment(L0.comment,o.личныйЧерновик.facts)}
    if(o.личныйЧерновик?.accepted_visit)Object.assign(L0,LC_WORKFLOW.projectAcceptedVisit(L0,o.личныйЧерновик));
    const last = d.msgs[d.msgs.length - 1];
    // разбор правилами (economy / rules): «Взять» строит форму разбором заново — работа оператора идёт с ИИ
    const A = { id, conv: d.conv, lead: L0, checks: ex.checks, lastId: last ? last.id : '', ctx, ...(ex.rules ? { поПравилам: true } : {}) };
    if (L0.stance && L0.stance.вид === 'отказ') return итог('declined', 'клиент отказался: «' + L0.stance.text + '» — заявку не создаём (исход «Не создана»)', { A });
    if (L0.stance && (L0.stance.вид === 'думает' || L0.stance.вид === 'цена')) return итог('doubt', СОМНЕНИЕ[L0.stance.вид === 'цена' ? 'цена' : 'подумает'] + ': «' + L0.stance.text + '»', { A });

    // --- чего не хватает. Жёсткое (считается): телефон, адрес/дом, время (не договорено и не прозвон), суть, голосовое,
    //     сверить номер, цена «от N», ЛПР. Мягкое (только «почти»): территория не определилась
    const чек = (f) => {
      const facts=o.личныйЧерновик?.facts;
      if(facts&&f==='phone')return{ok:!!facts.contact_phone_to_use&&!facts.phone_needs_confirmation,note:''};
      if(facts&&f==='address')return{ok:!!(facts.address?.building&&(facts.address.street||facts.address.settlement||facts.address.area))&&!facts.address_needs_confirmation,note:''};
      if(f==='time'&&o.личныйЧерновик?.accepted_visit)return{ok:!!L0.visit_time,note:'Согласованное окно помощника'};
      return (ex.checks || []).find((c) => c.field === f) || { ok: false, note: '' };
    };
    const gaps = [];
    if (!чек('phone').ok) gaps.push({ k: 'phone' });
    if (!чек('address').ok) gaps.push(Ч.место ? { k: 'address', detail: '«' + Ч.место + '» — место встречи, а нужен адрес дома или работы' } : { k: /нет номера дома/.test(чек('address').note) ? 'house' : 'address' });
    else if (Ч.место) пометить('место встречи: «' + Ч.место + '» — по регламенту выезд только на адрес дома или работы');
    let вид = '', прозвон = '', ttl = 0;
    const позвонить = Ч.время && Ч.время.вид === 'позвонить';
    if (чек('time').ok) вид = 'полная';
    else if (L0.call_words || L0.time_call || позвонить) { вид = 'прозвон'; прозвон = 'клиент просит созвониться: «' + (позвонить ? Ч.время.text : L0.call_words || L0.time_call) + '» — «Прозвон» поставьте сами, если нужно'; }
    else if (Ч.время && Ч.время.вид === 'выбирает') {
      const возраст = Date.now() - Ч.время.at;
      // клиент «уточню и напишу» и молчит 15 минут — можно создавать (ближайшее по регламенту, «Прозвон» — сами); раньше — ждём его ответа
      if (возраст >= 15 * 60e3) { вид = 'прозвон'; прозвон = 'клиент не решил время: «' + Ч.время.text + '» — «Прозвон» поставьте сами, если нужно'; }
      else { gaps.push({ k: 'time', detail: 'клиент ещё выбирает время: «' + Ч.время.text + '»' }); ttl = Math.max(60e3, 15 * 60e3 - возраст); }
    } else {
      /* 13.10 (решение владельца): время не договорено — «Готовые» берут на ближайшее по регламенту, если по контексту оно годится:
         • клиент передумал по времени или назвал другой день / часть дня без часа («в среду», «вечером») — нужна договорённость;
         • оператор предложил свой час («завтра в 15, удобно?»), а клиент не ответил — ждём ответа (ближайшее спорило бы с предложением);
         • оператор спросил «Когда удобно?», а клиент время не назвал — ждём ответа 15 мин, молчит — ближайшее;
         • время не обсуждали, «сегодня», «срочно», «в любое время» — ближайшее сразу */
      const сегодня = (клиентСейчас(L0) || {}).iso || '';
      const сказал = String(L0.time_text || '').trim();
      const вопрос = LC_EXTRACT.вопросВремени(d.msgs);
      const тишина = last && Date.parse(last.created_at) ? Date.now() - Date.parse(last.created_at) : Infinity;
      if (L0.time_veto) gaps.push({ k: 'time', detail: 'клиент передумал: «' + L0.time_veto + '»' });
      else if (L0.time_wait) gaps.push({ k: 'time', detail: 'ждём ответа клиента на «' + L0.time_wait + '»' });
      // 2.2.7: клиент назвал окно («до 15», «завтра до 12», «с 10 до 14») — ближайшее в окне; успеваем ли до срока — ниже, по территории
      else if (окноКлиента(L0)) вид = 'ближайшее';
      else if ((L0.visit_date && L0.visit_date !== сегодня) || !LC_EXTRACT.ближайшееГодится(сказал)) {
        gaps.push({ k: 'time', detail: 'нет точного часа («' + (сказал || L0.visit_date).slice(0, 60) + '»): предложите окно цифрами (или «Прозвон» — сами)' });
      } else if (вопрос && !сказал && тишина < 15 * 60e3) {           // «в любое время», «сегодня» — это и есть ответ: не ждём
        gaps.push({ k: 'time', detail: 'ждём ответа клиента на «' + вопрос + '»' }); ttl = Math.max(60e3, 15 * 60e3 - тишина);
      } else {
        вид = 'ближайшее';
        прозвон = сказал ? 'клиент: «' + сказал.slice(0, 40) + '» — время ближайшее по регламенту'
          : вопрос ? 'на «' + вопрос + '» клиент время не назвал (молчит 15+ мин) — время ближайшее по регламенту' : 'время не обсуждали — ближайшее по регламенту';
      }
    }
    if (!чек('problem').ok) gaps.push({ k: 'problem' });
    if ((ex.checks || []).some((c) => c.field === 'voice' && !c.ok)) gaps.push({ k: 'voice' });
    if (L0.phone_confirm) gaps.push({ k: 'phone_check' });
    if (Ч.лпр) gaps.push({ k: 'lpr', detail: 'договоритесь на время, когда он будет: «' + Ч.лпр + '»' });
    const части = (list) => list.map((g) => ПОЧЕМУ[g.k] + (g.detail ? ' — ' + g.detail : ''));
    const нехватка = () => итог('missing', 'не хватает: ' + части(gaps).join('; '), { A, ...(ttl ? { ttl } : {}) });
    if (gaps.some((g) => g.k === 'phone') || gaps.length > 1) return нехватка();

    // --- номер из разбора другой — заявки ещё раз (тем же правилом: сбой — ошибка, живая — «заявка уже есть»)
    const p10 = String(L0.phone || '').replace(/\D/g, '').slice(-10);
    let exiЛида = exi0 && p10 === phone10 ? exi0 : null, exiAt = exiP ? когдаШаг(exiP) : Date.now();
    if (!o.безПоиска && p10 !== phone10 && p10.length === 10) {
      const exiPr = искать(p10);
      exiAt = когдаШаг(exiPr);
      const exi = await exiPr;
      стоп();
      const сбой = ошибкаCRM(exi);
      if (сбой) return сбой;
      другиеБазы(exi);
      const o2 = (exi.found || []).find((r) => r.open);
      if (o2) return итог('exists', естьЗаявка(o2), { crm: exi, dir });
      exiЛида = exi;
    }
    // номер карточки (не взятый) — живая заявка по нему: возможно, тот же человек с другим номером — не «готово», сверить
    if (другойP) {
      const x = await другойP;
      стоп();
      const o3 = x && x.ok ? (x.found || []).find((r) => r.open) : null;
      if (o3) gaps.push({ k: 'phone_check', detail: 'по номеру карточки ' + fmtPhone(другой10) + ' есть заявка № ' + o3.id + ' (' + dirName(o3.dir) + ') — это тот же клиент?' });
      else if (!x || !x.ok) пометить('номер карточки ' + fmtPhone(другой10) + ' в CRM не проверен (' + String((x && x.error) || 'нет ответа').slice(0, 50) + ') — сверьте вручную');
      if (gaps.length > 1) return нехватка();
    }
    if (!dir) {
      const б = базаПоСмыслу(L0, d.conv);
      if (б && (await городВБазе(б.dir, L0.city)) !== false) { пометить('база по смыслу — ' + dirName(б.dir) + ': ' + б.работа + ' (в названии канала базы нет)'); dir = б.dir; направление = dir; }
      else return итог('missing', 'не понятно направление (МНЧ / КП / БТ) — откройте и выберите базу', { A });
    }
    // 2.0.7: направление по смыслу — работа не этой базы (стиральная в МНЧ там, где есть филиал БТ; компьютер в МНЧ…) — готовим в нужной.
    // Город в той базе знаем по списку городов CRM (запоминается формой); не знаем — остаёмся, форма при открытии решит сама.
    // КП по регламенту чужую технику сперва согласует со своим филиалом — только пометка
    { const рек = !o.личноеНаправление&&typeof LC_WORK !== 'undefined' ? LC_WORK.направление(L0, dir) : null;
      if (рек && рек.совет) пометить('похоже на ' + dirName(рек.dir) + ': ' + рек.работа + ' — по регламенту сначала согласуйте с филиалом ' + dirName(dir) + ', откажет — в ' + dirName(рек.dir));
      else if (рек && !(рек.dir === 'bt' && белаяНаБТ(withSource(L0, d.conv, 'bt'), 'bt')) && (await городВБазе(рек.dir, L0.city)) === true) { пометить('база по смыслу — ' + dirName(рек.dir) + ': ' + рек.работа + ' (канал ' + dirName(dir) + ')'); dir = рек.dir; направление = dir; } }

    // --- территория и форма CRM — параллельно; форма берёт найденные заявки клиента (не ищет номер по базам второй раз)
    const lead = withSource(L0, d.conv, dir);
    const a = lead.addr || {};
    const terrArgs = { dir, city: lead.city, settlement: a.settlement, street: a.street, building: a.building, partner: lead.partner, tech: техника(lead), ...LC_EXTRACT.точкаАдреса(lead) };
    // деревня без улицы («деревня Ложки, 12») — тоже по карте: за чертой города — согласование
    const terrP = a.street || a.settlement ? шаг('terr|' + [id, dir, lead.city, a.settlement, a.street, a.building, terrArgs.tech, terrArgs.pt ? terrArgs.pt.join(',') : '', lead.partner,o.личныйЧерновик?.form_reference||''].join('|'), 10 * 60e3, () => территория(terrArgs)) : null;
    const known = exiЛида && exiЛида.ok ? { phone10: p10, found: exiЛида.found || [], unchecked: exiЛида.unchecked || [] } : null;
    let prepAt = Date.now();
    const подготовить = (city) => { const p = шаг('prep|' + [id, dir, p10, city, (lead.topics || []).join(','), lead.partner, lead.repeat_hint, безИИ ? 'безИИ' : '',o.личныйЧерновик?.crm_route?.city_id||'',o.личныйЧерновик?.policy_version||'',o.личныйЧерновик?.form_reference||''].join('|'), 10 * 60e3,
      () => спросить({ kind: 'lcz-crm', op: 'prepare', args: { dir, phone: lead.phone, city, cityFallback: lead.city, topics: lead.topics, partner: lead.partner, problem: lead.problem,
        ...(o.личныйЧерновик?{...LC_WORKFLOW.crmPrepareArgs(dir,lead,o.личныйЧерновик),cityFallback:undefined}:{}),
        client: lead.client_words, device: lead.device || '', repeat_hint: lead.repeat_hint, known, ...(безИИ ? { безИИ: true } : {}) } }, 60e3, 'CRM (подготовка заявки)'));
    prepAt = когдаШаг(p); return p; };
    let [terr, prep] = await Promise.all([terrP, подготовить(lead.city)]);
    стоп();
    // форма по этому разбору («Можно создавать», «Взять») берёт готовое: территорию, форму CRM, найденные заявки.
    // A.at — когда спрошено самое старое из них (ответ кэша шагов бывает до 10 мин давности), а не «сейчас»
    const кФорме = () => { if (prep && prep.ok) Object.assign(A, { prep, terr, known, at: Math.min(prepAt, terrP ? когдаШаг(terrP) : Infinity, known ? exiAt : Infinity), dir }); else delete A.prep; };
    кФорме();
    let террПометка = '';
    if (terr) {
      if (terr.ok && terr.approval) return итог('approval', (terr.why || []).join('; '), { A });
      // карта не ответила — согласование не проверено: сам не беру (как и при молчании CRM), проверю ещё раз
      if (terr.timeout) return итог('error', 'территория не проверена (' + String(terr.error || '').split(' — ')[0] + ') — не беру, вдруг нужно согласование; проверю ещё раз', { retry: true, A });
      // дома нет на карте, карта не загрузилась, нас. пункт не определился — «почти»: оператор сверит по карте в форме
      if (!terr.ok) террПометка = terr.error || 'адрес не нашёлся на карте';
      else if (terr.noMap) террПометка = 'карта территорий не загрузилась';
      else if (!terr.hours) террПометка = (terr.why || []).join('; ') || 'территория не определилась';
      // филиал по карте («Мытищи (МСК)») — другой город CRM: форму готовим под него
      if (terr.ok && terr.branch && безСкобокГород(terr.branch) !== безСкобокГород(prep && prep.cityText) && безСкобокГород(terr.branch) !== безСкобокГород(lead.city)) {
        prep = await подготовить(terr.branch);
        стоп();
        кФорме();
      }
    }
    if (!prep || !prep.ok) return итог('error', 'CRM не подготовила заявку (' + String((prep && prep.error) || 'нет ответа').slice(0, 80) + ') — проверю ещё раз', { retry: true, A });
    if (!prep.cityId) return итог('missing', prep.cityClosed ? 'филиал «' + prep.cityClosed + '» закрыт (в CRM «-»)' : 'город не нашёлся в CRM', { A });
    // оператор на карточке заявки выбрал «Всё равно создать новую» (безПоиска) — живую заявку он видел: пометка, а не «заявка уже есть»
    if (prep.moderation) { if (!o.безПоиска) return итог('exists', prep.moderation.text, { A }); пометить(prep.moderation.text + ' — вы выбрали создать новую'); }
    if (prep.live) { if (!o.безПоиска) return итог('exists', 'есть живая заявка «' + prep.live + '»', { A }); пометить('есть живая заявка «' + prep.live + '» — вы выбрали создать новую'); }
    другиеБазы({ unchecked: (prep.unchecked || []).filter((u) => u.dir !== dir) });
    if ((prep.unchecked || []).some((u) => u.dir === dir)) пометить('база ' + dirName(dir) + ' не проверена при подготовке формы — сверьте вручную');
    const applText = ((prep.appl || []).find((x) => x.id === prep.applId) || {}).text || '';
    const terrТВ = LC_TERRITORY.сТВ(terr, applText);                    // ТВ: без приёма до 36 км
    if (terrТВ !== terr) return итог('approval', (terrТВ.why || []).join('; '), { A });
    // история клиента по регламенту: отказ (повтор по согласованию), вторая гарантия, «Отмена КЦ» ≤ 3 дн. — вернуть старую
    const R = историяПо(prep, dir, lead, {}, ctx.messages);
    if (R && R.approval) return итог('approval', R.approval, { A });
    if (R && R.action === 'вернуть') {
      const вернуть = R.notes[0] || 'по регламенту прошлую заявку вернуть в «Ожидает», новую не создавать';
      if (!o.безПоиска) return итог('exists', вернуть, { A });
      пометить(вернуть);
    }
    // 2.1.3 (рег:665, 775): «Повтор» / «Гарантия» — адрес сверяют с клиентом; в этом диалоге его не называли — не «готово» (форма спросит то же)
    { const тип = (R && R.type) || prep.type || '';
      if (/^(Повтор|Гарантия)$/.test(тип) && чек('address').ok && !адресНазван(lead.addr, ctx.messages)) gaps.push({ k: 'address', detail: 'тип «' + тип + '»: адрес в этом диалоге не называли — по регламенту сверьте его с клиентом' }); }
    // регламент по виду услуг: согласование, «не наш профиль», «проверьте» (сомнительно — тоже согласование), цена «от N»
    const subText = ((prep.sub || []).find((x) => x.id === prep.subId) || {}).text || '';
    const ck = await шаг('ck|' + [id, dir, applText, subText, A.lastId, ctx.partner, ctx.origin,o.личныйЧерновик?.form_reference||''].join('|'), 60e3,
      () => спросить({ kind: 'lcz-checklist', args: { dir, applText, subText, ctx } }, 45e3, 'ИИ (регламент)'));
    стоп();
    if (ck && ck.ok) A.ck = ck;
    if (!ck || !ck.ok) return итог('error', 'согласование по регламенту не проверено (' + String((ck && ck.error) || 'нет ответа').slice(0, 80) + ') — проверю ещё раз', { retry: true, A });
    if (ck.hard_block) return итог('approval', ck.reason || ck.refuse || ck.approval, { A });
    if (ck.approval) return итог('approval', ck.approval, { A });
    if (ck.refuse) return итог('approval', 'по регламенту не наш профиль: ' + ck.refuse + ' — спросить филиал', { A });
    if (ck.maybe) return итог('approval', 'проверьте, нужно ли согласование: ' + ck.maybe + (ck.maybeWhy ? ' — ' + ck.maybeWhy : ''), { A });
    const пункты = [];
    for (const r of (ck.results || []).filter((x) => x && !x.done)) {
      const цена = String(r.item || '').match(/^Озвучить «от (\d+)»\s*(\([^)]*\))?/);
      if (цена) gaps.push({ k: 'price', detail: 'озвучьте «от ' + цена[1] + '»' + (цена[2] ? ' ' + цена[2] : '') + ' и получите согласие клиента' });
      else if (r.item && пункты.length < 3) пункты.push(String(r.item));
    }
    if (gaps.length > 1) return нехватка();
    // юрлицо по счёту — согласование с филиалом; организация, «нет денег», белая на БТ, номер — пометки (не мешают)
    if (Ч.юрлицо && Ч.юрлицо.счёт) return итог('approval', 'юрлицо, оплата по счёту — по согласованию с филиалом: «' + Ч.юрлицо.text + '»', { A });
    if (Ч.юрлицо) пометить('организация — уточните оплату: по счёту (согласование) или переводом/наличными');
    if (Ч.денег) пометить('нет денег сейчас: «' + Ч.денег + '» — по регламенту Прозвон на дату, когда появятся');
    if (белаяНаБТ(lead, dir)) пометить('белая заявка на БТ — по правилу партнёра 723 не создаётся; создать можно только «всё равно»');
    if (lead.phone_warn && !lead.phone_confirm) пометить('телефон: ' + lead.phone_warn);
    if ((lead.addr_need || []).length) добрать.push('полный адрес: ' + lead.addr_need.join(', '));
    добрать.push(...пункты);
    const мягкие = террПометка ? [{ k: 'territory', detail: террПометка + ' — проверьте по карте' }] : [];
    /* 2.2.7 окно клиента: визит — ближайшее по регламенту (зона — по территории) в окне: не раньше начала, не позже срока минус 30 мин.
       Успеваем — «можно создавать» на ближайшее; не успеваем — «почти»: договориться о другом времени/дне. Время = начало окна («после 12»),
       а ближайшее позже — показываем ближайшее (форма поставит его) */
    const окноЛ = окноКлиента(lead);
    let вОкне = null;
    if (окноЛ && (вид === 'ближайшее' || (вид === 'полная' && окноЛ.from && lead.visit_time === окноЛ.from))) {
      const з = зонаБлижайшего(lead, terr, prep);
      вОкне = lead.clock ? LC_EXTRACT.времяВОкне(lead.clock, окноЛ, { плюс: з.плюс, ранняя: з.ранняя, день: lead.visit_date || '' }) : null;
      if (вОкне && !вОкне.ок) мягкие.push({ k: 'time', detail: окноЛ.until ? 'клиент может только до ' + окноЛ.until + ' — не успеваем по регламенту'
        : 'клиент: ' + LC_EXTRACT.окноСловами(окноЛ) + ' сегодня — по регламенту сегодня уже не успеваем' });
      else if (вОкне && вид === 'ближайшее') прозвон = 'клиент: ' + LC_EXTRACT.окноСловами(окноЛ) + ' — ближайшее по регламенту ' + вОкне.time;
      if (вОкне && вОкне.ок && вид === 'полная' && вОкне.date === lead.visit_date && вОкне.time <= lead.visit_time) вОкне = null;   // начало окна не раньше ближайшего — как есть
    }
    // регламент не сверен (ИИ в экономном режиме или выключен) — не «готово»: автоприём сам не создаёт, сверка — в форме
    if (безИИ&&!o.проверенныйРазбор) мягкие.push({ k: 'reglament', detail: (режимИИ === 'rules' ? 'ИИ выключен до 1-го числа' : 'ИИ в экономном режиме') + ' — сверка при открытии формы' });
    /* 2.1.1 по смыслу: «можно создавать» и автоприём «почти» — только если клиент идёт к выезду: по правилам «заявка» с явным шагом (просит
       мастера, согласился, дал адрес / время на вопрос) или ИИ нашёл договорённость — время визита или просьбу созвониться — и суть есть
       (кроме случаев, когда правила видят другое: только спросил цену, думает, пишет о прежней заявке). Иначе — «почти» с пометкой */
    // 13.10: время не обсуждали, а клиент сам дал суть, адрес и телефон — тоже шаг к выезду («ближайшее»; тип «цена», «думает»… — нет)
    const поИИ = (чек('time').ok || вид === 'прозвон' || вид === 'ближайшее') && чек('problem').ok && !/^(цена|думает|по_заявке|пусто|вопрос)$/.test(З.тип);
    const согласен = (З.вид === 'заявка' && З.сила === 'сильно') || поИИ;
    if (!согласен) мягкие.push({ k: 'intent', detail: З.тип === 'цена' ? 'пока только спросил цену — предложите выезд и время' : 'уточните' });
    const st = gaps.length || мягкие.length ? 'almost' : 'ready';
    const dm = lead.visit_date ? lead.visit_date.slice(8, 10) + '.' + lead.visit_date.slice(5, 7) : '';
    // 13.10: время не договорено — форма поставит ближайшее по регламенту (день назвал клиент без часа — время не выдумывает)
    const безЧаса = вид === 'прозвон' || вид === 'ближайшее';
    const сег = (клиентСейчас(lead) || {}).iso;
    const бл = вОкне ? (вОкне.ок ? вОкне : null) : безЧаса && !lead.visit_time && (!lead.visit_date || lead.visit_date === сег)
      ? LC_EXTRACT.ближайшееПоРегламенту(lead.clock, зонаБлижайшего(lead, terr, prep)) : null;
    const днм = (x) => x.slice(8, 10) + '.' + x.slice(5, 7);
    const бот = лидБот(d.msgs, d.conv);
    return итог(st, st === 'almost' ? 'добить: ' + части(gaps.concat(мягкие)).join('; ') : прозвон, {
      вид, dir, city: prep.cityText || lead.city,
      time: вОкне && !вОкне.ок ? 'не успеваем ' + (окноЛ.until ? 'до ' + окноЛ.until : 'сегодня')
        : безЧаса ? (бл ? 'ближайшее, визит ~' + (бл.date !== сег ? днм(бл.date) + ' ' : '') + бл.time : dm ? dm + ' (час — с клиентом)' : 'ближайшее')
          : бл ? [днм(бл.date), бл.time].join(' ') : [dm, lead.visit_time].filter(Boolean).join(' '),
      problem: lead.problem, appl: [applText, subText].filter(Boolean).join(' / '), hours: terr && terr.ok ? terr.hours : '', bot: !!бот, botWhy: бот ? бот.why : '',
      пробелы: gaps.concat(мягкие).map((g) => g.k), согласен, A, ...(ttl ? { ttl } : {}) });
  }
  /* Клиент с уже созданной заявкой пишет во «Входящие». Берём сообщения клиента после последнего ответа оператора,
     ИИ определяет намерение. Претензия — к выполненной заявке, остальное — к незакрытой. */
  const ДЕЙСТВИЕ = { перенос: 'Перенос', отмена: 'Отмена', где_мастер: 'Где мастер?', претензия: 'Претензия', отдел_авито: 'В отдел Авито', дополнение: 'Дописал' };
  async function поЗаявке(d, base, rows) {
    // контакт MAX (номер во вложении, текста нет) — тоже слова клиента
    const msgs = d.msgs.map((m) => ({ ...m, body: LC_EXTRACT.сКонтактом(m) })).filter((m) => (m.body || '').trim() || m.voice_transcript);
    let k = msgs.length;
    while (k > 0 && msgs[k - 1].direction === 'in') k--;
    const fresh = msgs.slice(k).slice(-12);
    if (!fresh.length) return null;                                   // последним писал оператор — клиент ничего не ждёт
    // клиент пишет несколькими сообщениями подряд — ждём, пока допишет, и читаем всё целиком
    if (Date.now() - Date.parse(fresh[fresh.length - 1].created_at) < 90e3) return { ...base, st: 'wait', why: 'клиент ещё пишет — посмотрю через минуту', retry: true };
    const before = msgs.slice(0, msgs.length - fresh.length);
    const item = объявлениеДиалога(d.conv);
    const pick = (m) => ({ direction: m.direction, sender_type: m.sender_type, body: m.body, voice_transcript: m.voice_transcript, created_at: m.created_at });
    // проверка строки очереди (purpose:'inbox'): в экономном режиме мозг разбирает правилами — перенос, отмена, «где мастер?» видны и так
    const r = await спросить({ kind: 'lcz-addition', args: { purpose: 'inbox', ctx: { city: городОбъявления(item), tz: поясОбъявления(item), before: before.map(pick), fresh: fresh.map(pick) } } }, 45e3, 'ИИ (что дописал клиент)');
    if (!r || !r.ok || !r.important || !ДЕЙСТВИЕ[r.intent]) return null;
    const open = rows.filter((x) => x.open);
    const t = r.intent === 'претензия' || r.intent === 'отдел_авито' ? (rows.find((x) => !x.open && /выполн|закрыт|оплач|готов/i.test(x.status || '')) || open[0] || rows[0]) : open[0];
    if (!t) return null;
    const last = fresh[fresh.length - 1];
    r.from = Date.parse(fresh[0].created_at) || 0;                     // с какого сообщения клиента — новое (адрес по заявке)
    let инфо = t;
    if (r.intent === 'претензия') { const c = await спросить({ kind: 'lcz-crm', op: 'claims', args: { dir: t.dir, id: t.id } }, 40e3, 'CRM'); if (c && c.ok) инфо = { ...инфо, hasClaim: c.count > 0 }; }
    if ((r.intent === 'где_мастер' && (!t.status || t.phone10 === undefined)) || (r.intent === 'перенос' && !t.visitTime)) {   // «где мс?» — от статуса (СД, прозвон); перенос — «с» из CRM
      const i = await спросить({ kind: 'lcz-crm', op: 'info', args: { dir: t.dir, id: t.id } }, 40e3, 'CRM');
      if (i && i.ok && i.info) инфо = { ...t, ...i.info, status: t.status || i.info.cardStatus };
    }
    const cr = { id: t.id, dir: t.dir, city: t.city || '', url: t.url || '', chat: t.chat, chatTitle: t.chatTitle, at: t.at || Date.now(), seenAt: Date.parse(last.created_at) - 1, linked: true,
      status: инфо.status || инфо.cardStatus || '', phone10: инфо.phone10 || '', prozvon: !!инфо.prozvon, service: инфо.serviceComment || '', hasClaim: инфо.hasClaim,
      visit: инфо.visit || '', visitTime: инфо.visitTime || '' };
    const dm = r.date ? r.date.slice(8, 10) + '.' + r.date.slice(5, 7) : '';
    const что = { перенос: [dm, r.time].filter(Boolean).join(' ') || 'время не назвал', отмена: r.reason || '', претензия: r.summary || '', дополнение: r.summary || '', где_мастер: '' }[r.intent] || '';
    return { ...base, st: 'follow', intent: r.intent, dir: t.dir, city: t.city || '', crId: t.id, cr, why: ДЕЙСТВИЕ[r.intent] + ' № ' + t.id + (что ? ' — ' + что : ''),
      F: { r, seen: Date.parse(last.created_at), lastId: last.id, text: fresh.map((m) => String(m.body || m.voice_transcript || '').trim()).filter(Boolean).join(' / ').slice(0, 260) } };
  }
  // для проверок в node: тест заранее кладёт window.__lczTest = true — получает разбор готовности. Это изолированный мир
  // расширения: страница LeadChat сюда не дотянется, в работе крючок пуст
  if (window.__lczTest === true) window.__lczTest = { проверитьДиалог, разобратьГотовность, ШАГИ };

  /* «Входящие»: какие диалоги готовы к созданию; автоприём — сам берёт готовые (без согласования) на оператора.
     Быстро и без лишних запросов: автоприём ведёт ОДНА вкладка (замок lcz-leader); «Входящие» — одним запросом (до 200 строк; больше — страницами, до 600);
     полный список читаем, только когда изменился счётчик GET /inbox/count (и не реже раза в 4 минуты), а пока во «Входящих» есть
     диалоги, которые следующее сообщение клиента может сделать готовыми, — каждый круг; моя нагрузка — одно
     число page.total; «Отошёл» — не берём; передачи «мне» и диалоги лид-бота автоприём не берёт никогда. */
  // «по созданным заявкам» — только если оператор сам включил (в 1.13.0–1.13.3 было включено по умолчанию — старое значение не берём)
  // толькоЧтение — LeadChat ответил 403 read_only_role: в эту сессию вкладки не берём (новый вход — заново)
  const AUTO = { on: false, max: 8, almost: true, follow: false, checked: new Map(), busy: false, busyAt: 0, gen: 0, taken: [], толькоЧтение: false,
    countKey: '', fullAt: 0, capped: false, ждём: false, retryAt: 0, away: false, err: '', skipAcc: new Set(), идут: new Map() };
  const ПОЛНЫЙ_СПИСОК_МС = 4 * 60e3, ПРОВЕРКА_МС = 120e3, ЗАВИС_МС = 5 * 60e3;
  /* МГНОВЕННО: «слух» на сокет самой страницы LeadChat (rt-main.js → rt.js → сюда). Событие — повод проверить СЕЙЧАС, а не через 40 с.
     inbox:new / inbox:released несут строку очереди целиком (как GET /inbox) — новый диалог проверяем без лишних запросов к LeadChat;
     событиям без строки — один GET /inbox на пачку. Проверяет и берёт только видимая ведущая вкладка (по два диалога, новые первыми);
     остальные вкладки лишь убирают из «Готовых» взятых и закрытых. Брать — по одному за раз (круг и события), лимит — перед каждым.
     Нет «слуха» (страницу не обновили после обновления расширения, Chrome старше 111) — всё как в 1.18: круг раз в 40 с. */
  const RTX = window.__lczRt || null;
  const МГН = {
    строки: new Map(),        // id → последняя известная строка «Входящих»
    клиент: new Map(),        // client_id → id
    анонс: new Map(),         // id → когда пришёл inbox:new (детектор «глухоты»)
    очередь: new Map(),       // id → строка, ждёт проверки
    отложено: new Map(),      // ≤50: пришло, пока вкладка в фоне / не ведущая
    работают: 0, разбор: false, ждут: new Map(),   // ждут: id → таймер «проверить чуть позже» (карточка, расшифровка)
    ids: new Set(), idsT: 0,  // id без строки — дочитать одним GET /inbox
    дочитатьПотом: false,     // такие пришли, пока вкладка была в фоне / не ведущей — сверка при возврате
    пишет: new Map(), повтор: new Map(), взяты: new Map(),
    вернул: new Map(),        // id → { by, at }: кто вернул диалог в очередь (inbox:released) — свой возврат автоприём не забирает обратно
    сброс: new Map(),         // id → когда разбор устарел без смены строки (расшифровка голосового, карточка клиента)
    приём: Promise.resolve(),
    presenceAt: 0, пропуски: 0, ктоP: null,
    сверкаT: 0, сверкаК: 0, сверкаAt: 0, сверкаИдёт: false,
    countKey: '', fullAt: 0, watchT: 0,
    сразу: true, с: Date.now(),
    тост: new Map(), тостEl: null, тостКлюч: '', тостСкрыт: '',
  };
  const мгновенно = () => !!(RTX && RTX.живой && RTX.живой()) && МГН.пропуски < 2;
  // свой ключ в памяти: store.set('autoClaim', …) его не сбрасывает
  const мгнНастройка = store.get('instantCfg', {}).then((v) => { МГН.сразу = !(v && v.off); }).catch(() => {});
  const автоНастройка = store.get('autoClaim', null).then((v) => { if (v) { AUTO.on = !личнаяВкладка && !!v.on; AUTO.max = Number(v.max) || 8; AUTO.almost = v.almost !== false; AUTO.follow = v.followOn === true; } rbLabel(); }).catch(() => {});
  // строку проверяем заново, если изменилось что-то из этого (unread_count — личный счётчик, last_message.id и updated_at в строке нет).
  // Имя и телефон клиента — тоже: № заявки в имени («Иван 2603481») — это «заявка уже есть»
  // № заявки у диалога (LeadChat 12.10) — тоже: появился — разбор прежний не годится («заявка уже есть»)
  const ключСтроки = (r) => [r.last_message_at, r.last_message && r.last_message.created_at, r.waiting_since, r.status, r.bot_active,
    r.client && r.client.name, r.client && r.client.phone, r.crm_request_id]
    .map((x) => (x === undefined || x === null ? '' : String(x))).join('|');
  // передача, предложенная мне: диалог ещё за коллегой — «Взять» (/claim) для неё всегда 409; принимать — /transfer/accept
  const передачаМне = (r) => r.transferred_to_me === true || !!(r.transfer && r.transfer.to && LC.me && String(r.transfer.to.id) === LC.me.id);
  /* «Входящие» — страницами: сервер отдаёт не больше 200 строк за раз (и total), дальше — по offset. Обычно это один запрос.
     Больше 600 — дальше не читаем: последняя страница полная — список НЕПОЛНЫЙ (rows.неполный): кого в нём нет, тот не «ушёл
     из очереди» — из «Готовых» и строк «Входящих» его не убираем */
  const ВХОДЯЩИЕ_СТР = 200, ВХОДЯЩИЕ_МАКС = 600;
  async function входящие() {
    const t0 = Date.now();
    const seen = new Set(), rows = [];
    let неполный = false;
    for (let offset = 0; ; offset += ВХОДЯЩИЕ_СТР) {
      const page = await LC.get('/inbox?limit=' + ВХОДЯЩИЕ_СТР + (offset ? '&offset=' + offset : ''));
      const items = (page && page.items) || [];
      for (const r of items) if (r && r.id && r.status !== 'closed' && !seen.has(r.id) && seen.add(r.id)) rows.push({ ...r, _inbox: true, _transfer: передачаМне(r) });
      const total = page && page.page && typeof page.page.total === 'number' ? page.page.total : null;
      if (items.length < ВХОДЯЩИЕ_СТР || (total !== null && offset + items.length >= total)) break;   // это была последняя страница
      if (offset + ВХОДЯЩИЕ_СТР >= ВХОДЯЩИЕ_МАКС) { неполный = true; break; }
    }
    if (неполный) rows.неполный = true;
    for (const r of rows) if (r.account) READY.каналы.set(r.id, { account: r.account, channel: r.channel || '' });
    // ожидание — по строкам этого чтения; список неполный — прежние значения непрочитанных не забываем
    READY.ждёт = new Map([...(неполный ? [...READY.ждёт].filter(([id]) => !seen.has(id)) : []), ...rows.map((r) => [r.id, Date.parse(r.waiting_since || '') || 0])]);
    if (RTX) {
      // о каких диалогах событие пришло, пока шёл запрос, — ответ мог их ещё не застать: не теряем (список неполный — никого не теряем)
      const свежие = [...МГН.строки.values()].filter((r) => (неполный || (МГН.анонс.get(r.id) || 0) >= t0) && !seen.has(r.id));
      МГН.строки = new Map(rows.concat(свежие).map((r) => [r.id, r]));
      for (const r of rows) if (r.client && r.client.id) МГН.клиент.set(String(r.client.id), r.id);
      // ушли из очереди без события (обрыв, пропуск) — из «Готовых» тоже: туда пишут и фоновые проверки
      if (READY.items.some((x) => !МГН.строки.has(x.id))) { READY.items = READY.items.filter((x) => МГН.строки.has(x.id)); drawReadySoon(); drawReadyTab(); тостНовые(null); }
      сверитьАнонсы(rows);
    }
    return rows;
  }
  // сколько диалогов на мне как на ответственном — одно число (гости и предложенные мне передачи не в счёт)
  async function сколькоУМеня() {
    const me = await моёId();
    if (!me) throw ошибкаLC('LeadChat не сказал, кто вы (/auth/me)');
    const q = '/conversations?tab=mine&assignee_id=' + encodeURIComponent(me);
    const page = await LC.get(q + '&limit=1');
    if (page && page.page && typeof page.page.total === 'number') return page.page.total;
    const all = await LC.get(q + '&limit=200');                         // ответ без total — считаем строки
    return (all.items || []).filter((r) => r && r.status !== 'closed').length;
  }
  /* p11: по диалогу сейчас создаётся заявка — в этой вкладке или в другой (её запись 'jobs' жива: держит замок задачи или свежий «пульс»).
     Вкладку с задачей перезагрузили посреди создания в CRM — создалась ли, неизвестно (10 мин): тоже не «можно создавать» и не берём */
  async function создаётсяПоДиалогу(conv) {
    if (задачаИдёт(conv)) return 'заявка по этому диалогу сейчас создаётся';
    try {
      const x = ((await store.get('jobs', {})) || {})[conv];
      // CRM не ответила на создание (504, обрыв): заявка могла создаться или ещё сохраняется — 15 мин не «можно создавать»
      // (поиск CRM её может ещё не видеть), пока «Найти в CRM по номеру» не скажет, что её нет
      if (x && x.state === 'unknown' && Date.now() - (x.unknownAt || x.beat || 0) < НЕЯСНО_МС) return НЕЯСНО_ТЕКСТ;
      if (!x || x.state !== 'run' || x.tab === ВКЛАДКА) return '';
      const возраст = Date.now() - (x.beat || x.at || 0);
      if (возраст < 30e3 || держит(await замкиЗадач(), x)) return 'заявка по этому диалогу сейчас создаётся в другой вкладке';
      if ((x.crmDone || /^(create|name|tg)$/.test(x.stage || '')) && возраст < 10 * 60e3) return 'создание заявки по этому диалогу прервалось (перезагрузка страницы) — создалась ли, неизвестно: проверьте CRM';
    } catch (_e) { /* хранилище недоступно — знаем только эту вкладку */ }
    return '';
  }
  // запись о заявке по диалогу появилась в момент «от» или позже — разбор, начатый раньше, о ней не знал
  async function созданаПосле(conv, от) {
    try { const cr = ((await store.get('created', {})) || {})[conv]; return cr && (cr.at || 0) >= (от || 0) ? cr : null; } catch (_e) { return null; }
  }
  /* o.свежее (мс) — результат старше этого проверяем заново («Проверить «Входящие»» — старше минуты).
     Один диалог — одна проверка за раз: строка та же — ждём ту же проверку; изменилась (клиент дописал) — ждём, пока закончится
     идущая, и проверяем заново (двух проверок одного диалога разом не бывает). */
  async function проверитьКэш(row, o) {
    const создаётся = await создаётсяПоДиалогу(row.id);                // p11: создаётся (здесь или в другой вкладке) — как созданная, не берём
    if (создаётся) return исход({ id: row.id, name: (row.client && row.client.name) || '', inbox: true }, 'exists', создаётся);
    if (row._transfer) {                                                // передачу не разбираем: её принимает человек
      const t = row.transfer || {};
      return { id: row.id, name: (row.client && row.client.name) || '', inbox: true, st: 'transfer', transfer: true, transferBy: String((t.by && t.by.id) || ''),
        why: 'передаёт ' + ((t.by && t.by.full_name) || 'коллега') + (t.comment ? ': «' + String(t.comment).slice(0, 120) + '»' : '') };
    }
    const k = ключСтроки(row), c = AUTO.checked.get(row.id), сброс = МГН.сброс.get(row.id) || 0;
    const срок = Math.min(15 * 60e3, (c && c.res && c.res.ttl) || 15 * 60e3, (o && o.свежее) || Infinity);
    // заявку по диалогу создали (или связали) после этой проверки — её итог устарел, проверяем заново (p11)
    if (c && c.key === k && Date.now() - c.at < срок && (c.от || 0) >= сброс && !(await созданаПосле(row.id, c.от || 0))) return c.res;
    // «Готовые», автоприём и события проверяют один и тот же диалог разом — разбор (ИИ, CRM) один на всех
    const идёт = AUTO.идут.get(row.id);
    if (идёт) {
      if (идёт.key === k && идёт.от >= сброс) return идёт.p;
      await идёт.p.catch(() => {});
      return проверитьКэш(row, o);
    }
    const стоп = { да: false }, от = Date.now();                       // проверка не уложилась в срок — её шаги дальше не идут
    const p = (async () => {
      let res;
      try { res = await сТаймаутом(проверитьДиалог(row, стоп), ПРОВЕРКА_МС, 'проверка не уложилась в 2 минуты — посмотрю в следующий раз'); }
      catch (e) {
        стоп.да = true;
        const t = String((e && e.message) || e);
        // сбой связи с LeadChat (срок, сеть, 5xx, 429) — не запоминаем на 15 минут, проверим на следующем круге
        const сбой = /не уложилась/.test(t) || !!(e && e.lc && (/^(timeout|network)$/.test(e.code) || e.status >= 500 || e.status === 429));
        res = { id: row.id, name: (row.client && row.client.name) || '', inbox: true, st: 'error', why: t.slice(0, 120), retry: сбой };
      }
      // p11: пока шла проверка, по диалогу начали создавать заявку (здесь или в другой вкладке) или создали — по разбору «до» не предлагаем
      // и не берём; не запоминаем: идёт — ответит проверка на входе, создана — новая проверка (уже с заявкой)
      const поздно = res.st === 'exists' ? '' : (await создаётсяПоДиалогу(row.id)) || ((await созданаПосле(row.id, от)) ? 'заявка по этому диалогу только что создана' : '');
      if (поздно) res = исход({ id: row.id, name: res.name || (row.client && row.client.name) || '', inbox: true }, 'exists', поздно);
      res._key = k; res._от = от;                                       // по какой строке и когда решено: клиент дописал после — не берём по старому
      if (!res.retry && !поздно) AUTO.checked.set(row.id, { key: k, at: Date.now(), от, res });
      else {                                                            // и «создаётся» — через минуту проверим снова (создание в другой вкладке кончится)
        AUTO.retryAt = Date.now() + 60e3;                               // «клиент ещё пишет» — через минуту список прочитаем, даже если счётчик тот же
        if (RTX) повторитьПозже(row.id);                                // а со «слухом» — проверим сами, не дожидаясь круга
      }
      return res;
    })();
    const запись = { key: k, от, p };
    AUTO.идут.set(row.id, запись);
    try { return await p; } finally { if (AUTO.идут.get(row.id) === запись) AUTO.идут.delete(row.id); }
  }
  // результат «посмотрю через минуту» — через минуту и смотрим (один таймер на диалог)
  function повторитьПозже(id) {
    if (МГН.повтор.has(id)) return;
    МГН.повтор.set(id, setTimeout(() => {
      МГН.повтор.delete(id);
      const r = МГН.строки.get(id);
      if (r && !READY.gone.has(id)) вОчередь(r);
    }, 60e3));
  }
  // диалог взят (или его уже нет): из «Готовых» убираем сразу и не возвращаем запоздавшим результатом проверки
  function убратьИзГотовых(id) {
    READY.gone.add(id);
    READY.items = READY.items.filter((y) => y.id !== id);
    drawReadySoon();
    drawReadyTab();
    if (RTX && МГН.тост.has(id)) тостНовые(null);
  }
  /* p11: по диалогу начали создавать заявку или создание кончилось — «Готовые», число на кнопке, окошко «Новые» и кэш проверки узнают
     сразу, а не через 15 минут. why — «заявка уже есть» с этой причиной (и в кэш, пока строка та же); пусто — прежний итог забыть
     и проверить диалог заново */
  function заявкаПоДиалогуСменилась(conv, why) {
    if (!conv) return;
    if (why) взятыйУшёл(conv);                                          // 4: строка «Взяты автоприёмом» — уже создаётся / создана
    сброситьПроверку(conv);
    const row = МГН.строки.get(conv), i = READY.items.findIndex((x) => x.id === conv);
    const был = i >= 0 ? READY.items[i] : null;
    let res = null;
    if (why) {
      res = исход({ id: conv, name: (был && был.name) || (row && row.client && row.client.name) || '', inbox: true, ...(был && был.dir ? { dir: был.dir } : {}) }, 'exists', why);
      const now = Date.now();
      if (row) { res._key = ключСтроки(row); res._от = now; AUTO.checked.set(conv, { key: res._key, at: now, от: now, res }); }
      if (i >= 0) READY.items[i] = res;
    } else if (i >= 0) READY.items.splice(i, 1);
    if (i < 0 && !RTX) return;
    drawReadySoon();
    drawReadyTab();
    тостНовые(res);
    if (!why && row && !READY.gone.has(conv)) вОчередь(row, 1500);
  }
  // список «Готовых» ведут события, только если новые проверяются сразу и проверяет эта вкладка (ведущая): с выключенной
  // «Проверять новые сразу» и во второй видимой вкладке новые в него не попадают — там через 2 минуты читаем заново, как в 1.18
  const списокЖивой = () => мгновенно() && МГН.сразу && (!!ВЕДУЩАЯ.on || !(navigator.locks && navigator.locks.request));
  /* «Готовые»: открыли снова в течение 2 минут или список живой (его ведут события) — показываем как есть;
     иначе проверяем «Входящие» заново. «Проверить «Входящие»» (again) — с нуля, и результаты старше минуты — заново. */
  async function showReady(again) {
    if (формаЭтого()) запомнитьДиалог().catch(() => {});                // «Готовые» заменят форму: сохраняем её для возврата
    panel.classList.add('open');
    if (МГН.тостКлюч !== МГН.тостСкрыт) { МГН.тостСкрыт = МГН.тостКлюч; drawReadyTab(); rbLabel(); }   // 2.3: новые увидели — число без подсветки
    режимМозга().then((m) => { if (m !== РЕЖИМ.m) { РЕЖИМ.m = m; РЕЖИМ.at = Date.now(); drawReadySoon(); drawReadyTab(); } }).catch(() => {});
    if (!again && READY.at && (Date.now() - READY.at < 2 * 60e3 || списокЖивой())) { drawReady(true); return; }
    const my = ++READY.run;
    if (again || !READY.at) { READY.items = []; READY.gone = new Set(); READY.note = null; }
    READY.done = 0; READY.total = 0; READY.at = Date.now(); READY.err = '';
    drawReady(true);
    try {
      const rows = await входящие();
      if (READY.run !== my) return;
      // открыли снова через 2 минуты: кого уже нет во «Входящих» — из списка (без «слуха» их некому было убрать); список неполный — не знаем
      const есть = new Set(rows.map((r) => r.id));
      if (!rows.неполный && READY.items.some((x) => !есть.has(x.id))) READY.items = READY.items.filter((x) => есть.has(x.id));
      READY.total = rows.length;
      drawReady();
      let i = 0;
      const worker = async () => {
        while (i < rows.length && READY.run === my) {
          const res = await проверитьКэш(rows[i++], again ? { свежее: 60e3 } : undefined);
          if (READY.run !== my) return;
          READY.done++;
          вГотовые(res, true);
        }
      };
      await Promise.all([worker(), worker()]);           // по два диалога одновременно
      if (READY.run === my) drawReady();
    } catch (e) { if (READY.run === my) { READY.err = String(e.message || e); drawReady(); } }
  }
  // как сейчас узнаём о новых во «Входящих» — честно, в строке настроек «Готовых»
  function строкаСвязи() {
    if (мгновенно()) return 'Новые во «Входящих» проверяет сразу (события LeadChat), сверка раз в 40 секунд';
    if (RTX && RTX.канал && МГН.пропуски >= 2) return 'События LeadChat приходят не все — проверяет «Входящие» раз в 40 секунд';
    if (RTX && RTX.канал) return 'Нет связи с LeadChat в реальном времени — проверяет «Входящие» раз в 40 секунд';
    return 'Проверяет «Входящие» раз в 40 секунд (обновите страницу LeadChat — F5, чтобы проверять сразу)';
  }
  // список перерисовываем не чаще 4 раз в секунду (200 строк — не 200 полных перерисовок панели)
  let drawT = 0;
  function drawReadySoon() { if (drawT) return; drawT = setTimeout(() => { drawT = 0; drawReady(); }, 250); }
  // причина для глаз оператора: без служебных «добить» / «добрать» (сами причины — данные проверки — те же)
  const показПричины = (t) => String(t || '').replace(/^добить: /, 'не хватает: ').replace(/(^|;\s*|·\s*)добрать: /g, '$1уточнить: ');
  /* «Готовые»: шапка «Готовые · проверено X из Y», ↻ — проверить снова; передачи и «по созданным» — всегда сверху (ждут человека);
     2.3: дальше без фильтра — «Можно создать · N», «Почти · N», «Остальные (N) ▾» свёрнуто; уведомления — свёрнуто; автоприём — строкой.
     force — открыть список; без него перерисовываем, только если на экране именно он (а не форма заявки, открытая поверх) */
  function drawReady(force) {
    if (!panel.classList.contains('open') || !READY.at) return;
    const было = panel.querySelector('[data-ready]');
    if (!force && !было) return;
    // оператор вписывает лимит — не перерисовываем у него под рукой (введённое пропало бы), повторим чуть позже
    const ф = root.activeElement;
    if (!force && ф && было.contains(ф) && ф.type === 'number') { drawReadySoon(); return; }
    // перерисовка (раз в 40 с после автоприёма, по ходу проверки) не сворачивает открытые «Не взяты» и не прыгает наверх
    const прокрутка = было ? было.scrollTop : 0;
    // 2.3: какие свёрнутые списки открыты — по ключу списка («Остальные (N)» меняет число), группы внутри — по названию
    const ключДет = (d) => d.getAttribute('data-list') || (d.hasAttribute('data-notes') ? 'notes' : '') || ((d.querySelector(':scope > summary > span') || {}).textContent || '');
    const открыты = new Set(было ? [...было.querySelectorAll('details[open]')].map(ключДет) : []);
    // 5: в каждом списке — кто дольше ждёт, тот выше
    const поОчереди = (l) => l.slice().sort((a, b) => (ждётС(a.id) || 9e15) - (ждётС(b.id) || 9e15));
    // 8: режим — один раз, чипом в шапке
    const by = (st) => поОчереди(READY.items.filter((x) => x.st === st && !(st === 'almost' && толькоРегламент(x))));
    const сРегламентом = поОчереди(READY.items.filter(толькоРегламент));
    const ready = поОчереди(by('ready').concat(сРегламентом)), almost = by('almost');
    const режим = режимСейчас(), чип = чипРежима(режим);
    const ждёт = (x) => { const t = ждётС(x.id); if (!t) return ''; const м = Math.max(0, Math.floor((Date.now() - t) / 60e3)); return h('span', { class: 'rd-wait' + (м >= 10 ? ' w' : '') }, 'ждёт ' + м + ' мин'); };
    const идёт = READY.done < READY.total;
    const saveAuto = async () => { AUTO.countKey = ''; try { await store.set('autoClaim', { on: AUTO.on, max: AUTO.max, almost: AUTO.almost, followOn: AUTO.follow }); } catch (_e) { /* устарело */ } rbLabel(); };
    // строку уже берут (первое нажатие ещё идёт) — кнопка выключена и после перерисовки
    const кнопка = (fn, tip, label, x, cls) => (x && БЕРЁМ.has(x.id) ? h('button', { class: cls || 'sm pri', title: tip, disabled: true }, x.transfer ? 'Принимаю…' : 'Беру…')
      : h('button', { class: cls || 'sm pri', title: tip, onclick: fn }, label || 'Взять'));
    const сБотом = (x) => (x.bot ? h('div', { class: 'ds warn' }, '⚠ ' + (x.botWhy || 'диалог вёл лид-бот') + ' — проверьте CRM') : '');
    const пометки = (x) => [...(x.флаги || []).map((f) => h('div', { class: 'ds warn' }, '⚠ ' + f)),
      (x.добрать || []).length ? h('div', { class: 'ds' }, 'уточнить: ' + x.добрать.join('; ')) : ''].filter(Boolean);
    const адрес = (x) => { const a = (x.A && x.A.lead && x.A.lead.addr) || {}; return [a.street, a.building, a.office ? 'кв ' + a.office : ''].filter(Boolean).join(' ').replace(/ (\d)/, ' $1'); };
    /* 2.3 (Claude Design, лист «Готовые»): «Можно создать · N» — строка на диалог: имя · канал · ждёт N мин, одна строка сути, «Создать»
       прямо в строке (берёт диалог и открывает его форму; заявку создаёт только «Создать» в форме); «Почти · N» — причина строкой и «Открыть»;
       «Остальные (N) ▾» — свёрнуто; автоприём — одной строкой «Автоприём: выключен · Настроить» */
    const канал = (x) => каналСтроки(x.id) || dirName(x.dir);
    const кто = (x) => h('div', { class: 'rd-who' },
      h('button', { type: 'button', class: 'rd-name tt', title: 'Открыть диалог, не забирая его', onclick: () => перейти(x.id) }, x.name || 'клиент'),
      канал(x) ? h('span', { class: 'rd-ch' }, канал(x)) : '', ждёт(x));
    const почему = (x) => [x.вид === 'прозвон' ? 'просит созвониться' : x.вид === 'ближайшее' ? 'ближайшее время' : '', толькоРегламент(x) ? 'регламент — в форме' : ''].filter(Boolean).join(' · ');
    const суть2 = (x) => [x.problem, адрес(x), визитСтрокой(x)].filter(Boolean).join(' · ').slice(0, 220);
    // готовая — строкой: кто, суть, «Создать»
    // строка готовой — две линии (кто, суть); что уточнить и чем клиент согласился — в подсказке строки, ⚠ и лид-бот — видно сразу
    const подсказка = (x) => [x.заявка && x.заявка.согласие && x.заявка.сила === 'сильно' ? 'клиент согласился: «' + x.заявка.согласие + '»' : '',
      (x.добрать || []).length ? 'уточнить: ' + x.добрать.join('; ') : ''].filter(Boolean).join('\n') || undefined;
    const карточка = (x) => h('div', { class: 'lst-r rd-card', title: подсказка(x) },
      h('div', { class: 'tx' }, кто(x),
        суть2(x) ? h('div', { class: 'ds', title: суть2(x) }, суть2(x)) : '',
        почему(x) ? h('div', { class: 'ds mut' }, почему(x)) : '', сБотом(x), ...(x.флаги || []).map((f) => h('div', { class: 'ds warn' }, '⚠ ' + f))),
      кнопка((e) => открытьГотовую(x, e.currentTarget), 'Принять диалог и открыть форму заявки — создаёт только «Создать» в форме', 'Создать', x));
    // «почти» — причина строкой и «Открыть»
    const строкаПочти = (x) => h('div', { class: 'lst-r rd-row' },
      h('div', { class: 'tx' }, кто(x), h('div', { class: 'ds warn' }, показПричины(безРежима(x))), сБотом(x), ...пометки(x)),
      кнопка((e) => открытьГотовую(x, e.currentTarget), 'Принять диалог и открыть форму — дописать недостающее', 'Открыть', x, 'sm'));
    // ждут человека: передачи и клиенты по созданным заявкам
    const строкаЖдёт = (x, title, desc, btn) => h('div', { class: 'lst-r rd-row' }, h('div', { class: 'tx' }, h('div', { class: 'rd-who' }, h('b', { class: 'tt', title }, title), ждёт(x)), desc ? h('div', { class: 'ds' }, desc) : ''), btn);
    const список = (title, items, make, attrs) => (items.length ? h('div', { class: 'lst rd-list', ...(attrs || {}) },
      h('div', { class: 'lst-h' }, h('span', {}, title + ' · ' + items.length)), ...items.map(make)) : '');
    const свод = [['approval', 'Нужно согласование'], ['doubt', 'Клиент думает / цена не принята'], ['declined', 'Клиент отказался'], ['exists', 'Заявка уже есть'],
      ['refused', 'Оператор отказал клиенту'], ['wait', 'Клиент ещё пишет'], ['missing', 'Не хватает данных'], ['other', 'Не заявка (работа, реклама, спам…)'], ['error', 'Ошибки — проверю ещё раз']]
      .map(([st, title]) => [title, by(st)]).filter(([, l]) => l.length);
    const остальных = свод.reduce((n, [, l]) => n + l.length, 0);
    const кратко = { 'Нужно согласование': 'согласование', 'Клиент думает / цена не принята': 'думают', 'Клиент отказался': 'отказались', 'Заявка уже есть': 'уже создана',
      'Оператор отказал клиенту': 'вы отказали', 'Клиент ещё пишет': 'клиент пишет', 'Не хватает данных': 'не хватает данных', 'Не заявка (работа, реклама, спам…)': 'не заявка',
      'Ошибки — проверю ещё раз': 'ошибка проверки' };
    const пусто = (t) => h('div', { class: 'rd-empty' }, t);
    const настройка = (k, title, hint) => {
      const off = k !== 'on' && !AUTO.on;
      return h('label', { class: 'set-r' + (off ? ' off' : '') },
        h('div', { class: 'tx' }, h('div', { class: 'tt' }, title), h('div', { class: 'ds' }, off ? hint + ' · сначала включите автоприём' : hint)),
        h('input', { type: 'checkbox', class: 'sw', checked: AUTO[k], disabled: off, 'aria-label': title, onchange: async (e) => {
          AUTO[k] = e.target.checked; await saveAuto(); drawReady(); if (k === 'on' && AUTO.on) автоприём(); } }));
    };
    const состояние = !AUTO.on ? 'выключен' : AUTO.толькоЧтение ? 'не берёт: ' + ТОЛЬКО_ЧТЕНИЕ : AUTO.away ? 'ждёт: вы «Отошёл»' : 'включён';
    const когда = READY.at ? часыМинуты(new Date(READY.at)) : '';
    const настроить = !!READY.настройки;
    panel.replaceChildren(h('div', { class: 'ph rd-ph' },
      h('div', { class: 'top' },
        h('div', { class: 'ttl' }, h('div', { class: 't' }, 'Готовые', чип ? ' ' : '', чип),
          h('div', { class: 'sub rd-sub' }, 'Проверено ' + READY.done + ' из ' + READY.total + (идёт ? '…' : '') + ' во «Входящих»' + (когда && !идёт ? ' · ' + когда : ''))),
        S && S.lead ? h('button', { class: 'ib', title: 'Назад к заявке', 'aria-label': 'Назад к заявке', onclick: () => render() }, '←') : '',
        h('button', { class: 'ib', 'data-ready-again': '1', 'aria-label': идёт ? 'Начать заново' : 'Проверить снова', title: 'Проверить «Входящие» заново', onclick: () => showReady(true) }, svg('redo')),
        менюЕщё(true),
        h('button', { class: 'ib', 'aria-label': 'Закрыть', title: 'Закрыть (Esc)', onclick: closePanel }, svg('close')))),
      h('div', { class: 'pb rd', 'data-ready': '1' },
        READY.err ? h('div', { class: 'box bad' }, svg('warn'), h('div', { class: 'c' }, 'Не прочитались «Входящие»: ' + человечно(READY.err).text,
          человечно(READY.err).тех ? подробнее(человечно(READY.err).тех) : '')) : '',
        READY.note ? h('div', { class: 'box ' + (READY.note.kind || 'bad'), role: 'alert' }, svg('warn'), h('div', { class: 'c' }, READY.note.text)) : '',
        список('Передали вам — примите передачу', by('transfer'), (x) => строкаЖдёт(x, x.name || 'клиент', x.why,
          кнопка((e) => открытьГотовую(x, e.currentTarget), 'Принять диалог, который вам передал коллега', 'Принять передачу', x))),
        список('По созданным заявкам', by('follow'), (x) => строкаЖдёт(x, ДЕЙСТВИЕ[x.intent] + ' · ' + (x.name || 'клиент'), x.why.slice(0, 200),
          кнопка((e) => открытьПоЗаявке(x, true, e.currentTarget), 'Принять диалог и открыть карточку действия', '', x))),
        ready.length ? список('Можно создать', ready, карточка, { 'data-list': 'ready' })
          : пусто(идёт ? 'Проверяем «Входящие»…' : READY.total ? 'Готовых без согласования нет' + (almost.length ? ' — посмотрите «Почти»' : '') : '«Входящие» пусты'),
        сРегламентом.length ? h('div', { class: 'n mut' }, сРегламентом.length === ready.length ? 'Регламент для них проверите в форме (ИИ экономит)' : 'Из них ' + сРегламентом.length + ' — регламент проверите в форме (ИИ экономит)') : '',
        almost.length ? список('Почти', almost, строкаПочти, { 'data-list': 'almost' }) : '',
        остальных ? h('details', { class: 'lst rd-rest', 'data-list': 'rest' },
          h('summary', { class: 'rd-rest-s' }, h('span', {}, 'Остальные (' + остальных + ')'), h('span', { class: 'ds' }, свод.map(([t]) => кратко[t]).join(', '))),
          ...свод.map(([title, l]) => h('details', { class: 'lst-d' },
            h('summary', {}, h('span', {}, title), h('span', { class: 'cnt' }, String(l.length))),
            ...l.map((x) => h('div', { class: 'lst-s' }, h('span', { class: 'tt' }, x.name || 'клиент'), h('span', { class: 'ds' }, показПричины(x.why) + ((x.флаги || []).length ? ' · ⚠ ' + x.флаги.join('; ') : '')),
              h('a', { href: '/chats/' + x.id, onclick: (e) => { e.preventDefault(); перейти(x.id); } }, 'Открыть')))))) : '',
        // 2: «Пропущено» — уведомления, которые вытеснили другие или закрыли ×; «Вернуть» — то же уведомление с его кнопками
        ПРОПУЩЕНО.length ? h('details', { class: 'lst rd-rest', 'data-notes': '1' },
          h('summary', { class: 'rd-rest-s' }, h('span', {}, 'Уведомления (' + ПРОПУЩЕНО.length + ')'), h('span', { class: 'ds' }, 'закрытые и вытесненные')),
          ...ПРОПУЩЕНО.map((x) => h('div', { class: 'lst-r' }, h('div', { class: 'tx' }, h('div', { class: 'tt', title: x.t || x.l || 'уведомление' }, x.t || x.l || 'уведомление'),
            h('div', { class: 'ds' }, [x.l, { вытеснено: 'вытеснено другими', закрыто: 'закрыто', само: 'ушло само', позже: 'напомню позже' }[x.почему] || '', назад(x.at)].filter(Boolean).join(' · '))),
            h('button', { class: 'sm', title: 'Показать это уведомление снова', onclick: () => { вСтопку(x.el, true); drawReady(); } }, 'Вернуть')))) : '',
        h('div', { class: 'rd-div' }),
        // автоприём — одной строкой; «Настроить» раскрывает настройки (как в 2.1)
        h('div', { class: 'rd-auto', 'data-auto-line': '1' },
          h('span', {}, 'Автоприём: ', h('b', { class: AUTO.on && !AUTO.away && !AUTO.толькоЧтение ? 'ok' : '' }, состояние)),
          h('button', { type: 'button', class: 'sm', 'aria-expanded': String(настроить), onclick: () => { READY.настройки = !READY.настройки; drawReady(); } }, настроить ? 'Свернуть' : 'Настроить')),
        // связь с LeadChat не «сразу» (нет «слуха», события теряются) — честно строкой и при свёрнутых настройках
        !настроить && !мгновенно() ? h('div', { class: 'n mut', 'data-link-note': '1' }, строкаСвязи()) : '',
        настроить ? h('section', { class: 'sec set' + (AUTO.on ? ' hl' : '') },
          h('div', { class: 'set-h' }, h('h3', {}, 'Автоприём'), h('span', { class: 'st ' + (AUTO.on && !AUTO.away ? 'ok' : 'mut') }, (AUTO.on ? '● ' : '') + состояние)),
          настройка('on', 'Новые клиенты — всё есть', 'Всё для заявки есть, согласование не нужно'),
          настройка('almost', 'Новые клиенты — не хватает одного', 'Клиент согласен на выезд, нет времени, номера дома или цены — допишете'),
          настройка('follow', 'Клиенты с созданной заявкой', 'Перенос, отмена, «где мастер?» — «Сделать»'),
          h('div', { class: 'set-r' + (AUTO.on ? '' : ' off') },
            h('div', { class: 'tx' }, h('div', { class: 'tt' }, 'Не больше диалогов на мне'), h('div', { class: 'ds' }, 'Больше этого новые не берёт · от 1 до 200')),
            h('input', { type: 'number', class: 'num', min: 1, max: 200, value: AUTO.max, 'aria-label': 'Не больше диалогов на мне', disabled: !AUTO.on,
              onchange: async (e) => { AUTO.max = Math.max(1, Math.min(200, Number(e.target.value) || 8)); e.target.value = AUTO.max; await saveAuto(); } })),
          h('div', { class: 'set-f' }, h('div', {}, строкаСвязи() + ' — работает в одной вкладке LeadChat.'),
            h('div', {}, 'Не берёт: где нужно согласование, передачи вам, диалоги лид-бота и не заявки (ищут работу, реклама, только спросили цену). В статусе «Отошёл» — ждёт.'),
            AUTO.on && AUTO.err ? h('div', {}, 'Последняя попытка: ' + человечно(AUTO.err).text) : '',
            AUTO.taken.length ? h('div', { class: 'ok' }, 'Взято с открытия вкладки: ' + AUTO.taken.slice(-5).map((x) => x.name || 'клиент').join(', ')) : '')) : '',
        настроить ? h('section', { class: 'sec set' },
          // автоприём включён — события разбираются всегда (без них он не мгновенный); выключен — галочка решает, тратить ли ИИ и CRM на новые
          h('label', { class: 'set-r' }, h('div', { class: 'tx' }, h('div', { class: 'tt' }, 'Проверять новые сразу'), h('div', { class: 'ds' }, 'Новый диалог во «Входящих» разбирается за секунды, без ручной проверки — число на кнопке «Готовые»')),
            h('input', { type: 'checkbox', class: 'sw', checked: МГН.сразу, 'aria-label': 'Проверять новые сразу', onchange: async (e) => {
              МГН.сразу = e.target.checked; await store.set('instantCfg', МГН.сразу ? {} : { off: true }).catch(() => {});
              if (МГН.сразу) { if (RTX) сверкаСкоро(300); return; }
              if (!AUTO.on) { МГН.очередь.clear(); МГН.отложено.clear(); }   // выключили — ждущие проверки не запускаем
              тостНовые(null); } })),
          h('label', { class: 'set-r' },
            h('div', { class: 'tx' }, h('div', { class: 'tt' }, 'Предлагать «Решён» молчащим'), h('div', { class: 'ds' }, 'Клиент молчит 5 минут после вашего ответа — одно окно со списком')),
            h('input', { type: 'checkbox', class: 'sw', checked: !МОЛЧИТ.off, 'aria-label': 'Предлагать «Решён» молчащим', onchange: async (e) => {
              МОЛЧИТ.off = !e.target.checked; await store.set('silentCfg', МОЛЧИТ.off ? { off: true } : {}).catch(() => {}); } }))) : ''));
    const стало = было && panel.querySelector('[data-ready]');
    if (стало) {
      for (const d of стало.querySelectorAll('details')) if (открыты.has(ключДет(d))) d.open = true;
      стало.scrollTop = прокрутка;
    }
  }
  function rbLabel() {
    const n = READY.items.filter((x) => x.st === 'ready' || x.st === 'almost' || x.st === 'follow' || x.st === 'transfer').length, нов = новыхНеВидели();
    readyBtn.textContent = (AUTO.on ? '✓ Готовые · авто' : '✓ Готовые') + (n ? ' · ' + n : '');
    readyBtn.classList.toggle('auto', AUTO.on); readyBtn.classList.toggle('ready', нов > 0);
    if (typeof drawReadyTab === 'function') drawReadyTab();
  }

  /* ОДНА ВЕДУЩАЯ ВКЛАДКА: автоприём, «клиент молчит», ответы филиалов — только в ней. Иначе две вкладки LeadChat
     брали диалоги параллельно (лимит «не больше N» превышался) и вдвое чаще спрашивали LeadChat и Telegram.
     Замок «lcz-leader» берёт видимая вкладка (ifAvailable — без ожидания); ушла в фон — отдаёт его, возьмёт видимая. */
  const ВЕДУЩАЯ = { on: false, отпустить: null, ждём: null };
  function ведущая() {
    if(личнаяВкладка)return Promise.resolve(false);
    if (ВЕДУЩАЯ.on) return Promise.resolve(true);
    if (!(navigator.locks && navigator.locks.request)) return Promise.resolve(true);   // без замков — одна вкладка сама себе ведущая
    if (document.visibilityState !== 'visible') return Promise.resolve(false);
    if (ВЕДУЩАЯ.ждём) return ВЕДУЩАЯ.ждём;
    ВЕДУЩАЯ.ждём = new Promise((res) => {
      let решено = false;
      const итог = (v) => { if (!решено) { решено = true; res(v); } };
      const t = setTimeout(() => итог(false), 3000);
      const моя = {};
      let запрос;
      try {
        запрос = navigator.locks.request('lcz-leader', { ifAvailable: true }, (lock) => {
          clearTimeout(t);
          // вкладку успели скрыть, пока шёл запрос, — замок не держим: иначе скрытая вкладка заперла бы автоприём для видимой
          if (!lock || решено || document.visibilityState !== 'visible') { итог(false); return undefined; }
          ВЕДУЩАЯ.on = моя; итог(true);
          // держим, пока вкладка видна. Расширение обновили / выключили, а вкладка осталась: её скрипт уже ничего не ведёт, а замок
          // держал бы до закрытия вкладки — и автоприём не вела бы ни одна вкладка. Раз в 5 с проверяем связь и тогда отдаём замок
          return new Promise((done) => {
            const t = setInterval(() => { if (!alive()) отпустить(); }, 5000);
            const отпустить = () => {
              clearInterval(t);
              if (ВЕДУЩАЯ.on === моя) { ВЕДУЩАЯ.on = false; ВЕДУЩАЯ.отпустить = null; }
              done();
            };
            ВЕДУЩАЯ.отпустить = отпустить;
          });
        });
      } catch (_e) { clearTimeout(t); итог(true); return; }           // замки недоступны — как раньше, без ведущей
      запрос.catch(() => { clearTimeout(t); итог(false); })
        .then(() => { if (ВЕДУЩАЯ.on === моя) { ВЕДУЩАЯ.on = false; ВЕДУЩАЯ.отпустить = null; } });
    }).finally(() => { ВЕДУЩАЯ.ждём = null; });
    return ВЕДУЩАЯ.ждём;
  }
  document.addEventListener('visibilitychange', () => {
    // вернулись во вкладку: что пришло, пока она была в фоне, — разобрать сразу. Сокет жил всё это время — события дошли и в фоне,
    // «Входящие» не перечитываем (оператор ходит CRM ↔ LeadChat весь день: GET /inbox на каждый возврат — лишняя нагрузка на LeadChat);
    // сверка — если сокет не живой, в фоне была причина сверяться (переподключение, событие без строки) или прошлой не было 4 минуты
    if (document.visibilityState === 'visible' && RTX) {
      if (!мгновенно() || МГН.дочитатьПотом || Date.now() - МГН.сверкаAt > ПОЛНЫЙ_СПИСОК_МС) сверкаСкоро(300);
      else if (МГН.отложено.size) setTimeout(отложенныеВОчередь, 300);
    }
    if (document.visibilityState === 'visible' || !ВЕДУЩАЯ.отпустить) return;
    const done = ВЕДУЩАЯ.отпустить;
    ВЕДУЩАЯ.on = false; ВЕДУЩАЯ.отпустить = null;
    done();
  });
  // страницу вернули из кэша «назад/вперёд»: что пришло, пока она спала, сокет не повторит — сверяемся
  window.addEventListener('pageshow', (e) => { if (e.persisted && RTX) сверкаСкоро(500); });

  /* «Взять» из «Входящих»: передача — POST /transfer/accept, остальное — /claim. Итог словами, а не «HTTP 409»:
     409 и «уже ваш» (details.mine) — успех; 409 чужой — «Диалог уже принят: Имя»; 403 «вы не ведёте диалоги» — выключить автоприём. */
  async function взятьДиалог(x) {
    const id = encodeURIComponent(x.id);
    const передача = !!(x.transfer || x._transfer);
    try {
      await LC.post('/conversations/' + id + (передача ? '/transfer/accept' : '/claim'));
      return { ok: true };
    } catch (e) {
      const d = (e && e.details) || {}, reason = d.reason || '', why = String((e && e.message) || e);
      if (e && e.status === 409 && d.mine) return { ok: true, already: true };
      // передачи уже нет: её приняли — может, я сам (второй щелчок, другая вкладка) — или коллега; или её отменили / истекла.
      // Кто ведёт диалог — скажет сам диалог; не узнали — как раньше («передачи нет», из списка убираем)
      if (передача && e && e.status === 422 && reason === 'no_pending_transfer') {
        try {
          const c = await деталь(x.id);
          const a = c && c.assignee;
          const я = await моёId();
          if (a && я && String(a.id) === String(я)) return { ok: true, already: true };
          // ведёт тот, кто передавал, — передачу отменили или она истекла, а не «приняли»
          const от = (x.transfer && x.transfer.by && x.transfer.by.id) || x.transferBy;
          if (a && от && String(a.id) === String(от)) return { ok: false, drop: true, why: 'передачу отменили или она истекла — диалог у ' + (a.full_name || 'коллеги') };
          return { ok: false, drop: true, why: a ? 'передачу уже приняли: ' + (a.full_name || 'коллега') : 'передачу отменили или она истекла' };
        } catch (_e) { /* не узнали — как раньше */ }
      }
      if (e && e.status === 409) return { ok: false, drop: true, why: d.claimed_by && d.claimed_by.full_name ? 'Диалог уже принят: ' + d.claimed_by.full_name : why };
      if (reason === 'does_not_handle_conversations' || reason === 'cannot_answer_clients') return { ok: false, stop: true, why };
      // 403 read_only_role (руководитель — «режим просмотра», details.reason нет): брать нельзя ни один диалог — не повторяем каждый круг
      if (e && e.status === 403 && e.code === 'read_only_role') return { ok: false, readOnly: true, why: ТОЛЬКО_ЧТЕНИЕ };
      if (reason === 'channel_not_assigned') return { ok: false, channel: String(d.account_id || (x.account && x.account.id) || ''), why };
      if (/^(not_in_inbox|conversation_closed|owner_changed|no_pending_transfer|not_your_transfer)$/.test(reason) || (e && e.status === 404)) return { ok: false, drop: true, why };
      return { ok: false, why };
    }
  }
  /* роль только для чтения: автоприём до конца сессии вкладки (новый вход — заново) больше не берёт; сказать — один раз */
  const ТОЛЬКО_ЧТЕНИЕ = 'роль только для чтения — брать диалоги нельзя';
  function толькоЧтение() {
    if (AUTO.толькоЧтение) return;
    AUTO.толькоЧтение = true;
    rbLabel();
    тост({ kind: 'warn', label: 'Автоприём не берёт', title: 'Автоприём: ' + ТОЛЬКО_ЧТЕНИЕ,
      lines: [h('div', { class: 'tst-d' }, 'У вашей учётной записи в LeadChat режим просмотра (руководитель). «Готовые» показываю, а брать диалоги — нет; повторять не буду. Нужна другая роль — спросите администратора.')] });
  }
  async function выключитьАвтоприём(why) {
    AUTO.on = false;
    try { await store.set('autoClaim', { on: false, max: AUTO.max, almost: AUTO.almost, followOn: AUTO.follow }); } catch (_e) { /* устарело */ }
    rbLabel();
    const el = тост({ kind: 'warn', label: 'Автоприём выключен', title: 'Автоприём выключен: LeadChat не даёт брать диалоги из очереди',
      lines: [why ? h('div', { class: 'tst-q' }, 'LeadChat: «' + String(why).slice(0, 200) + '»') : '',
        h('div', { class: 'tst-d' }, 'Это настройка вашей учётной записи в LeadChat — спросите администратора. Включить автоприём снова — в «Готовых».')],
      actions: [h('button', { class: 'sm pri', onclick: () => { el.remove(); showReady(); } }, 'Открыть «Готовые»')] });
  }
  const drawReadyIfOpen = () => { if (panel.classList.contains('open') && panel.querySelector('[data-ready]')) drawReady(); };
  // автоприём: новые входящие → проверка → готовые без согласования берём на себя (до лимита)
  async function автоприём() {
    if (!AUTO.on || !alive() || document.visibilityState !== 'visible') return;
    // прошлый круг завис (CRM или ИИ не ответили) — через 5 минут начинаем новый; старый уже ничего не возьмёт (gen)
    if (AUTO.busy && Date.now() - AUTO.busyAt < ЗАВИС_МС) return;
    if (!(await ведущая())) return;                                     // автоприём ведёт другая вкладка LeadChat
    const my = ++AUTO.gen;
    AUTO.busy = true; AUTO.busyAt = Date.now();
    try {
      // лимит был занят — пока занят, «Входящие» читать незачем (одно число page.total); освободился — список читаем сразу
      if (AUTO.capped) {
        if (await сколькоУМеня() >= AUTO.max) { AUTO.err = ''; return; }
        AUTO.capped = false; AUTO.countKey = '';
      }
      // во «Входящих» ничего не изменилось — список не читаем (целиком — не реже раза в 4 минуты): обычно это один лёгкий запрос.
      // Но счётчик не меняется от нового сообщения клиента: если там ждут диалоги, которые оно сделает готовыми
      // (не хватало телефона, адреса…), или прошлый приём сорвался — читаем список каждый круг, как раньше
      let key = '';
      // «слух» жив — диалоги, которые следующее сообщение клиента может сделать готовыми, перепроверят их же события
      // (сообщение, расшифровка, карточка); «клиент ещё пишет» и сбои — по AUTO.retryAt, как и раньше
      if (!(AUTO.ждём && !мгновенно())) {
        // старый LeadChat без /inbox/count (404) — просто читаем список
        const c = await LC.get('/inbox/count').catch((e) => { if (e && e.status === 404) return null; throw e; });
        key = c && typeof c.count === 'number' ? c.count + '|' + (Number(c.escalated) || 0) : '';
        if (key && c.count === 0) { AUTO.countKey = key; AUTO.fullAt = Date.now(); AUTO.err = ''; return; }
        if (key && key === AUTO.countKey && Date.now() - AUTO.fullAt < ПОЛНЫЙ_СПИСОК_МС && !(AUTO.retryAt && Date.now() >= AUTO.retryAt)) { AUTO.err = ''; return; }
      }
      // «Отошёл» — LeadChat сам новых не даёт; и мы не берём (спрашиваем, только когда есть что брать)
      const pr = await LC.get('/presence').catch(() => null);
      AUTO.away = !!(pr && pr.status === 'away');
      МГН.presenceAt = Date.now();
      if (AUTO.away) { AUTO.countKey = ''; AUTO.err = ''; return; }    // вернётся «на месте» — список прочитаем сразу
      const rows = await входящие();
      if (my !== AUTO.gen) return;
      if (!RTX && !rows.неполный) {                                     // со «слухом» это делает входящие(); неполный список — не знаем, кто ушёл
        const есть = new Set(rows.map((r) => r.id));
        if (READY.items.some((x) => !есть.has(x.id))) { READY.items = READY.items.filter((x) => есть.has(x.id)); drawReadySoon(); drawReadyTab(); }
      }
      AUTO.countKey = key; AUTO.fullAt = Date.now(); AUTO.retryAt = 0; AUTO.capped = false;
      for (const [id, c] of AUTO.checked) if (Date.now() - c.at > 30 * 60e3) AUTO.checked.delete(id);   // старые проверки — из памяти
      // диалог ещё может стать нашим от следующего сообщения клиента (или проверка / приём сорвались) — список читаем и на следующем круге
      // «doubt» — клиент думает, торгуется: может и согласиться
      const можетСтать = (st) => st === 'missing' || st === 'almost' || st === 'wait' || st === 'error' || st === 'doubt' || (AUTO.follow && st === 'exists');
      let ждём = false;
      for (const row of rows) {                                        // все входящие (раньше — первые 10)
        if (!AUTO.on || my !== AUTO.gen) break;
        // передачу принимает человек — кнопкой «Принять передачу»; диалог ещё ведёт бот — «взять» оборвало бы его на полуслове
        if (row._transfer || row.bot_active) continue;
        if (row.account && AUTO.skipAcc.has(String(row.account.id))) continue;   // канал ведут другие (403 channel_not_assigned)
        const res = await проверитьКэш(row);
        if (my !== AUTO.gen) break;
        вГотовые(res);                                                  // «Готовые» и число на кнопке — свежие и при автоприёме
        // не берём; ждём следующего круга, если сообщение клиента может это изменить (вёл лид-бот — не изменит, как в 1.18)
        if (!берётся(res)) { if (можетСтать(res.st) && !(res.bot && берётся({ ...res, bot: false }))) ждём = true; continue; }
        // брать — по одному за раз (круг и события LeadChat), нагрузку — заново перед каждым приёмом
        const итогП = await взятьЕслиМожно(row, res, my);
        if (итогП === 'stop' || итогП === 'capped') break;
        if (итогП === 'retry' || итогП === 'later') ждём = true;         // сбой связи / LeadChat — повторим на следующем круге, а не через 4 минуты
      }
      if (my === AUTO.gen) AUTO.ждём = ждём;
      AUTO.err = '';
    } catch (e) {
      AUTO.err = String((e && e.message) || e).slice(0, 140);
      AUTO.countKey = '';                                               // LeadChat не ответил посреди круга — в следующий раз список читаем заново
    }
    finally { if (my === AUTO.gen) AUTO.busy = false; drawReadyIfOpen(); }
  }
  /* 2.1 уведомления: у всех одно строение — цветная полоса слева, метка и время справа, заголовок, строки, кнопки, подпись.
     Вид — только четыре: warn «Нужно действие», bad «Ошибка — и что делать», ok «Сделано», info — сведения.
     Кнопка-главная (.pri) — одна: остальные становятся обычными. Техника (сырые ошибки, пути) — под «Подробнее» (o.подробно), не в тексте.
     o.low — второстепенное, o.keep — итог, по которому нужно действие (не вытесняется), o.due — «пора» (число в заголовке скрытой вкладки),
     o.жить — мс до ухода в «Пропущено» (наведение мыши останавливает); у «Сделано» вместо времени — «уйдёт через N с» */
  // СТОПКА: видно не больше трёх — сначала то, что ждёт действия, потом новое; остальные живы, но спрятаны: счётчик «ещё N — …»
  // (нажатие показывает следующие). Совсем много (больше 12) — лишние уходят в «Пропущено» (сначала второстепенные; keep — никогда;
  // последние 30, только память вкладки). × — тоже в «Пропущено»; «Вернуть» ставит тот же элемент с его кнопками обратно и на виду.
  // el.remove() владельца — насовсем (и из «Пропущено»)
  const ВИДНО = 3, ВСЕГО = 12, РУКА_МС = 5 * 60e3;
  const ПРОПУЩЕНО = [];                                               // { el, at, почему, t, l }
  const ОТЛОЖЕНЫ = new Map();                                         // el → диалог: «Позже», вернётся через 15 мин
  const ОТВЕТЫ = new Map();                                           // ответы филиалов: conv → { el, n, q: [] } (ниже, notifyReply)
  const СЛОТ_РЕЖИМА = h('div', { class: 'tst-slot' });
  const ЕЩЁ = h('button', { class: 'tst-more', type: 'button', title: 'Показать следующие уведомления', style: 'display:none', onclick: () => листать() });
  const ПИЛЮЛЯ = h('button', { class: 'tst-miss', type: 'button', title: 'Уведомления, которые вытеснили другие или закрыли, — в «Готовых»', style: 'display:none',
    onclick: () => { showReady(); setTimeout(() => { const x = panel.querySelector('[data-notes]'); if (x && x.scrollIntoView) x.scrollIntoView({ block: 'nearest' }); }, 60); } });
  const НИЗ = h('div', { class: 'tst-bar' }, ЕЩЁ, ПИЛЮЛЯ);
  toasts.append(СЛОТ_РЕЖИМА, НИЗ);
  const снять = (el) => { if (el && el.parentNode) el.parentNode.removeChild(el); };
  const тостыСтопки = () => [...toasts.children].filter((x) => x.classList.contains('tst'));
  function изИстории(el) { const i = ПРОПУЩЕНО.findIndex((x) => x.el === el); if (i >= 0) { ПРОПУЩЕНО.splice(i, 1); пропущеноСменилось(); } }
  function вИсторию(el, почему) {
    if (!el) return;
    снять(el);
    el._рука = 0;
    const i = ПРОПУЩЕНО.findIndex((x) => x.el === el);
    if (i >= 0) ПРОПУЩЕНО.splice(i, 1);
    const т = (sel) => String((el.querySelector(sel) || {}).textContent || '').trim();
    ПРОПУЩЕНО.unshift({ el, at: Date.now(), почему, t: т(':scope > .tst-t'), l: т(':scope > .tst-k .tst-l') });
    if (ПРОПУЩЕНО.length > 30) ПРОПУЩЕНО.length = 30;
    пропущеноСменилось();
  }
  function пропущеноСменилось() {
    ПИЛЮЛЯ.textContent = 'Пропущено: ' + ПРОПУЩЕНО.length;
    ПИЛЮЛЯ.style.display = ПРОПУЩЕНО.length ? '' : 'none';
    try { drawReadyIfOpen(); } catch (_e) { /* «Готовые» ещё не готовы */ }
  }
  // совсем много (больше 12) — уходят сначала второстепенные («молчит», «Новые во «Входящих»», в том числе только что пришедшее):
  // окошко «Новые…» не должно выталкивать ответ филиала или «Взят диалог». Итог, по которому нужно действие (keep: «Заявка не создана»,
  // «Не знаю, создалась ли», «прервалось», создана с предупреждениями), — не вытесняется никогда: уходит самое старое из остальных.
  // беречь — «Вернуть» из «Пропущено»: возвращённое не уходит сразу обратно
  function вытеснить(новое, беречь) {
    for (;;) {
      const все = тостыСтопки();
      if (все.length <= ВСЕГО) return;
      const low = (y) => y.classList.contains('tst-low');
      const x = все.find((y) => y !== новое && low(y)) || (беречь ? null : все.find(low)) || все.find((y) => y !== новое && !y.classList.contains('tst-keep'));
      if (!x) return;
      вИсторию(x, 'вытеснено');
    }
  }
  // поставить в стопку самым новым (и вернуть из «Пропущено» / «Позже»); беречь — показать сейчас (вернул сам оператор)
  function вСтопку(el, беречь) {
    if (!el) return;
    изИстории(el); ОТЛОЖЕНЫ.delete(el); clearTimeout(el._позже);
    el.classList.remove('tst-c');
    el._ключ = Date.now();
    if (беречь) el._рука = Date.now();
    toasts.insertBefore(el, НИЗ.parentNode === toasts ? НИЗ : null);
    if (el._жить) el._жить();                                          // вернули / обновили — снова полный срок
    вытеснить(el, беречь);
    разложить();
  }
  // что на виду: «показать» оператора (счётчик, «Вернуть») → ждёт действия (keep, «пора», warn/bad) → обычное → второстепенное;
  // внутри — новое выше. Видно три, остальные спрятаны (.tst-h) и посчитаны в «ещё N — …»
  const ждётДействия = (x) => x.classList.contains('tst-keep') || x.classList.contains('tst-due')
    || (!x.classList.contains('tst-low') && (x.classList.contains('warn') || x.classList.contains('bad')));
  function порядокСтопки(все) {
    const now = Date.now();
    const рука = (x) => (x._рука && now - x._рука < РУКА_МС ? x._рука : 0);
    const ранг = (x) => (рука(x) ? 3 : ждётДействия(x) ? 2 : x.classList.contains('tst-low') ? 0 : 1);
    return все.map((x, i) => ({ x, i, р: ранг(x), к: рука(x) || x._ключ || 0 })).sort((a, b) => b.р - a.р || b.к - a.к || b.i - a.i).map((y) => y.x);
  }
  const скл = (n, a, b, c) => { const д = n % 100, е = n % 10; return д >= 11 && д <= 14 ? c : е === 1 ? a : е >= 2 && е <= 4 ? b : c; };
  function разложить() {
    const все = тостыСтопки();
    const видно = new Set(порядокСтопки(все).slice(0, ВИДНО));
    for (const x of все) { x.classList.toggle('tst-h', !видно.has(x)); x.classList.remove('tst-c'); }
    const спрятаны = все.filter((x) => !видно.has(x));
    if (!спрятаны.length) { ЕЩЁ.style.display = 'none'; ЕЩЁ.textContent = ''; }
    else {
      const сколько = (k) => спрятаны.filter((x) => x.classList.contains(k)).length;
      const части = [[сколько('warn'), (n) => n + ' ' + скл(n, 'ждёт', 'ждут', 'ждут') + ' действия'], [сколько('bad'), (n) => n + ' ' + скл(n, 'ошибка', 'ошибки', 'ошибок')],
        [сколько('ok'), (n) => n + ' готово'], [сколько('info'), (n) => n + ' сведения']].filter(([n]) => n).map(([n, f]) => f(n));
      ЕЩЁ.textContent = 'ещё ' + спрятаны.length + (части.length ? ' — ' + части.join(', ') : '');
      ЕЩЁ.style.display = '';
    }
    if (toasts.scrollHeight > toasts.clientHeight) toasts.scrollTop = toasts.scrollHeight;
  }
  // «ещё N»: следующие три спрятанных — на виду (сначала ждущие действия), показанные — уступают место
  function листать() {
    const все = тостыСтопки(), спрятаны = все.filter((x) => x.classList.contains('tst-h'));
    if (!спрятаны.length) return;
    const now = Date.now();
    все.forEach((x) => { if (!x.classList.contains('tst-h')) x._рука = 0; });
    порядокСтопки(спрятаны).slice(0, ВИДНО).forEach((x, i) => { x._рука = now - i; });
    разложить();
  }
  try { new MutationObserver(разложить).observe(toasts, { childList: true }); } catch (_e) { /* без наблюдателя — раскладываем при вСтопку */ }
  // уведомление обновляется на месте (тот же элемент и кнопки): заголовок, метка, вид, строки, кнопки
  function обновитьТост(el, o) {
    if (!el) return;
    const q = (sel) => el.querySelector(':scope > ' + sel);
    if (o.kind) for (const k of ['ok', 'warn', 'info', 'bad']) el.classList.toggle(k, k === o.kind);
    if (o.label !== undefined) { const l = q('.tst-k > .tst-l'); if (l) l.textContent = o.label; }
    const t = q('.tst-t'), a = q('.tst-a');
    if (o.title !== undefined && t) t.textContent = o.title;
    if (o.lines && t && a) { while (t.nextSibling && t.nextSibling !== a) t.nextSibling.remove(); a.before(...o.lines.filter(Boolean), ...(o.подробно ? [подробнее(o.подробно)] : [])); }
    if (o.actions && a) a.replaceChildren(...однаГлавная(o.actions.filter(Boolean)));
    if (el._жить) el._жить();
    if (el.isConnected) разложить();
  }
  // «Позже»: то же уведомление вернётся через 15 мин — если по диалогу за это время не начали создавать заявку и не создали
  function позже(el, conv) {
    const от = Date.now();
    снять(el); изИстории(el);
    ОТЛОЖЕНЫ.set(el, conv || '');
    clearTimeout(el._позже);                                           // «Позже» дважды — считаем от последнего
    el._позже = setTimeout(async () => {
      if (!ОТЛОЖЕНЫ.has(el) || el.isConnected || !alive()) return;
      ОТЛОЖЕНЫ.delete(el);
      if (conv && ((await создаётсяПоДиалогу(conv)) || (await созданаПосле(conv, от)))) return;
      вСтопку(el);
    }, 15 * 60e3);
  }
  /* 2.3 (Claude Design, лист «Уведомления»): одно «✕» = «позже» — то же уведомление вернётся через 15 минут (если по диалогу за это время
     не начали создавать и не создали), а пока лежит в «Готовых» → «Уведомления» с «Вернуть». Отдельных «Позже» / «Скрыть» больше нет.
     «Сделано» и второстепенное (и где «позже» не к месту, o.позже === false) — ✕ просто убирает (в «Пропущено») */
  function крестик(el) {
    if (!el) return;
    if (!el._позже || el.classList.contains('ok') || el.classList.contains('tst-low')) { вИсторию(el, 'закрыто'); return; }
    позже(el, el._conv || '');
    const т = (sel) => String((el.querySelector(sel) || {}).textContent || '').trim();
    ПРОПУЩЕНО.unshift({ el, at: Date.now(), почему: 'позже', t: т(':scope > .tst-t'), l: т(':scope > .tst-k .tst-l') });
    if (ПРОПУЩЕНО.length > 30) ПРОПУЩЕНО.length = 30;
    пропущеноСменилось();
  }
  // время в углу уведомления (часы компьютера оператора)
  const часыМинуты = (d) => String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  // само уходит в «Пропущено» через мс; мышь на уведомлении — ждёт. «Сделано» (ok) показывает в углу «уйдёт через N с»
  // el._жить() — снова полный срок (вернули из «Пропущено», обновили на месте)
  function жить(el, мс) {
    let t = 0, с = 0, осталось = мс, над = false, тик = 0;
    const tm = el.querySelector(':scope > .tst-k > .tst-tm');
    const время = tm ? tm.textContent : '';
    const счёт = () => {
      clearTimeout(тик); тик = 0;
      if (!tm) return;
      if (!el.classList.contains('ok')) { tm.textContent = время; return; }
      const ост = над || !t ? осталось : осталось - (Date.now() - с);
      tm.textContent = 'уйдёт через ' + Math.max(1, Math.ceil(ост / 1000)) + ' с';
      if (t && el.isConnected) тик = setTimeout(счёт, 1000);
    };
    const пуск = () => { clearTimeout(t); с = Date.now(); t = setTimeout(() => { t = 0; clearTimeout(тик); if (el.isConnected) вИсторию(el, 'само'); }, Math.max(1000, осталось)); счёт(); };
    el.addEventListener('mouseenter', () => { над = true; if (t) { clearTimeout(t); t = 0; осталось -= Date.now() - с; } счёт(); });
    el.addEventListener('mouseleave', () => { над = false; пуск(); });
    el._жить = () => { осталось = мс; clearTimeout(t); t = 0; if (!над) пуск(); else счёт(); };
    пуск();
  }
  // 11: итог действия по строкам: «не сделано» — первыми (⚠, var(--warn)), сделанное — ✓ (var(--ok)); части текста — через « · »
  // плохо — ⚠ или явный сбой («не отправлено», «не записалась»…), а не любое «не»/«нет» («клиент не ответил на звонок» — сделано)
  const ПЛОХО_ИТОГ = /⚠|ошибк|неизвестн|не удал|(^|[\s(])не (отправ|записал|дописал|ушл|писали|найден|сохран|поставлен|отмечен|сделан)/i;
  function строкиИтога(text, ok) {
    const л = String(text || '').split(/\s+·\s+|\n/).map((x) => x.trim()).filter(Boolean).map((x) => ({ t: x.replace(/^[✓⚠]\s*/, ''), bad: ПЛОХО_ИТОГ.test(x) }));
    if (!л.length) л.push({ t: ok ? 'Сделано' : 'Не сделано', bad: !ok });
    if (!ok && !л.some((x) => x.bad)) л.forEach((x) => { x.bad = true; });
    return л.sort((x, y) => y.bad - x.bad).map((x) => h('div', { class: 'tst-d ' + (x.bad ? 'warn' : 'ok') }, (x.bad ? '⚠ ' : '✓ ') + x.t));
  }
  // одна главная кнопка на уведомление: вторая и дальше «главные» — обычные
  function однаГлавная(list) {
    let была = false;
    for (const b of list) if (b && b.classList && b.classList.contains('pri')) { if (была) b.classList.remove('pri'); была = true; }
    return list;
  }
  // техника — под «Подробнее»: сырой текст ошибки, путь, код
  const подробнее = (x) => h('details', { class: 'tst-det' }, h('summary', {}, 'Подробнее'),
    ...[].concat(x).filter(Boolean).map((y) => (typeof y === 'string' ? h('div', {}, y) : y)));
  /* сырой текст ошибки → понятная фраза + техника отдельно (для «Подробнее»): английские ошибки браузера, HTTP-пути, обрывы связи */
  function человечно(e) {
    const сырое = String((e && e.message) || e || '').trim();
    if (!сырое) return { text: '', тех: '' };
    if (сырое === УСТАРЕЛО || /обновите страницу LeadChat \(F5\)/.test(сырое)) return { text: УСТАРЕЛО, тех: '' };
    if (/message port closed|Receiving end does not exist|Extension context|context invalidated|нет ответа от расширения/i.test(сырое)) return { text: 'связь с расширением оборвалась', тех: сырое };
    if (/Failed to fetch|NetworkError|Load failed|ERR_|net::/i.test(сырое)) return { text: 'нет связи', тех: сырое };
    if (/HTTP\s*\d{3}|\/api\/|\(\/[a-z]/i.test(сырое)) return { text: сырое.replace(/\s*\((?:\/|HTTP)[^)]*\)/g, '').replace(/:\s*HTTP\s*\d{3}/i, ' ответил ошибкой').trim() || 'сервер ответил ошибкой', тех: сырое };
    if (/^[\x20-\x7e]+$/.test(сырое)) return { text: 'непредвиденная ошибка', тех: сырое };   // только латиница — английская ошибка браузера
    return { text: сырое, тех: '' };
  }
  function тост(o) {
    const el = h('div', { class: 'tst ' + (o.kind || 'ok') },
      h('div', { class: 'tst-k' }, h('span', { class: 'dot' }), h('span', { class: 'tst-l' }, o.label), h('span', { class: 'tst-tm' }, часыМинуты(new Date())),
        h('button', { class: 'x', 'aria-label': o.позже === false ? 'Закрыть' : 'Позже', title: o.позже === false ? 'Закрыть это уведомление' : 'Позже — напомню через 15 минут (до того — в «Готовых» → «Уведомления»)', onclick: (e) => крестик(e.currentTarget.closest('.tst')) }, svg('close'))),
      h('div', { class: 'tst-t' }, o.title),
      ...(o.lines || []).filter(Boolean),
      o.подробно ? подробнее(o.подробно) : '',
      h('div', { class: 'tst-a' }, ...однаГлавная((o.actions || []).filter(Boolean))),
      o.foot ? h('div', { class: 'tst-f' }, ...[].concat(o.foot)) : '');
    if (o.low) el.classList.add('tst-low');
    if (o.keep) el.classList.add('tst-keep');
    el._conv = o.conv || ''; el._позже = o.позже !== false;
    if (o.due) el.classList.add('tst-due');
    el.remove = () => { изИстории(el); ОТЛОЖЕНЫ.delete(el); снять(el); };   // убрал владелец — насовсем
    вСтопку(el);
    if (o.жить) жить(el, o.жить);
    return el;
  }
  /* 4: автоприём взял диалоги — ОДНО живое уведомление «Взяты автоприёмом: N», строка на диалог с «Открыть и создать».
     Строка уходит, когда её открыли или по диалогу начали создавать заявку (в любой вкладке) */
  const ВЗЯТЫ = { el: null, list: new Map(), выпало: 0 };
  function notifyTaken(x) {
    ВЗЯТЫ.list.delete(x.id); ВЗЯТЫ.list.set(x.id, x);
    // больше 12 — самые старые строки уходят, но не молча: «ещё N — во вкладке «Мои»» (диалоги уже на операторе)
    if (ВЗЯТЫ.list.size > 12) { ВЗЯТЫ.list.delete(ВЗЯТЫ.list.keys().next().value); ВЗЯТЫ.выпало++; }
    рисоватьВзятые(true);
  }
  function взятыйУшёл(id) { if (ВЗЯТЫ.list.delete(id)) рисоватьВзятые(false); }
  function рисоватьВзятые(новый) {
    const все = [...ВЗЯТЫ.list.values()];
    if (!все.length) { if (ВЗЯТЫ.el) ВЗЯТЫ.el.remove(); ВЗЯТЫ.el = null; ВЗЯТЫ.выпало = 0; return; }
    const строка = (x) => h('div', { class: 'tst-r' },
      h('div', {}, h('div', { class: 'tst-d' }, h('b', {}, x.name || 'клиент'), x.dir ? ' · ' + dirName(x.dir) : ''),
        x.st === 'almost' ? h('div', { class: 'tst-d' + (толькоРегламент(x) ? '' : ' warn') }, показПричины(безРежима(x))) : '',
        x.st === 'ready' && (x.вид === 'прозвон' || x.вид === 'ближайшее') && x.why ? h('div', { class: 'tst-d' }, x.why) : '',
        ...(x.флаги || []).map((f) => h('div', { class: 'tst-d warn' }, '⚠ ' + f)),
        h('div', { class: 'tst-d' }, [x.city, визитСтрокой(x), x.problem].filter(Boolean).join(' · ').slice(0, 160))),
      // недописанный ответ в открытом диалоге — строку не убираем: подсказка «нажмите ещё раз» — про эту кнопку
      h('button', { class: 'sm pri', onclick: async () => { if (черновикМешает(x.id)) return; взятыйУшёл(x.id); if (await перейти(x.id)) await collect(x.A); } }, 'Открыть и создать'));
    // взятые ждут оператора («Открыть и создать») — «Нужно действие»
    const o = { kind: 'warn', label: все.length === 1 ? 'Взят диалог' : 'Взяты диалоги',
      title: 'Взяты автоприёмом: ' + все.length, lines: все.map(строка).concat(ВЗЯТЫ.выпало ? [h('div', { class: 'tst-d mut' }, 'ещё ' + ВЗЯТЫ.выпало + ' — во вкладке «Мои» LeadChat')] : []),
      actions: [] };
    if (!ВЗЯТЫ.el) { ВЗЯТЫ.el = тост(o); return; }
    обновитьТост(ВЗЯТЫ.el, o);
    if (новый) вСтопку(ВЗЯТЫ.el);                                       // новый взятый — самым новым (и из «Пропущено» / «Позже»)
  }
  async function связатьСЗаявкой(x) {
    await правитьCreated((all) => { all[x.id] = { ...(all[x.id] || {}), ...x.cr }; });
  }
  /* Взят диалог по созданной заявке: в уведомлении уже всё готово — одна кнопка «Сделать» */
  /* 1.20: действия — намерения ИИ, которые ведут в карточку действия каталога, а не в прежнее «дополнение» (tg.js: поле «намерение») */
  const НОВЫЕ_НАМЕРЕНИЯ = ['позвоните', 'срочно', 'адрес', 'другое_направление', 'jivo_claim_reply'];
  // 2.1: целыми фразами (раньше склеивалось «Клиент новый адрес / телефон / имя — …»)
  const ПРО_НОВОЕ = { позвоните: 'Клиент просит позвонить или не знает, когда удобно — нужен Прозвон', срочно: 'Клиент просит срочно — нужна «Срочная»',
    адрес: 'Клиент дал новый адрес, телефон или имя — поправьте карточку клиента', другое_направление: 'Техника другого направления — нужен перевод в другую базу',
    jivo_claim_reply: 'Ответ Jivo по претензии — сообщите в группу претензий' };
  function notifyFollow(x) {
    const p = планПоЗаявке(x.cr, x.F.r, x.F.seen);
    // новое намерение: «Сделать» прежнего «дополнения» здесь не то действие — только «Открыть» (карточка с превью, запись по кнопке в ней)
    const новое = !!ACT && !!x.F.r && НОВЫЕ_НАМЕРЕНИЯ.includes(x.F.r.намерение);
    const нужноВремя = (p.intent === 'перенос' && !p.time) || !!p.transfer || новое;
    const что = [p.move ? 'перенести в CRM' : '', p.cancel ? '«Отмена КЦ» в CRM' : '', p.claim ? 'претензия в CRM' : '',
      p.tg ? (p.chat === 'claims' ? 'в чат претензий' : 'в чат города') + ': ' + (p.move ? '№ + строка «Переносы»' : '«' + p.tg + '»') : ''].filter(Boolean).join(' → ');
    const итог = h('div', { class: 'tst-d' }, новое ? ПРО_НОВОЕ[x.F.r.намерение] + '. Откройте — карточка действия заполнена'
      : p.transfer ? 'По регламенту — передать диалог отделу Авито: откройте и выберите сотрудника' : нужноВремя ? 'Клиент не назвал время — откройте и поставьте' : 'Сделаю: ' + что);
    // клиент пишет по созданной заявке — ждёт решения оператора («Сделать» / «Открыть»): «Нужно действие»
    const el = тост({ kind: 'warn', label: 'По созданной заявке',
      title: (x.name || 'клиент') + ' · ' + x.why.slice(0, 120),
      lines: [x.F.text ? h('div', { class: 'tst-q' }, 'Клиент: «' + x.F.text + '»') : '', итог,
        p.cancel && p.by !== 'branch' ? h('div', { class: 'tst-d warn' }, '«Отмена КЦ» списывает 60 ₽ — может, перенос?') : ''],
      actions: [нужноВремя ? '' : h('button', { class: 'sm pri', onclick: async (e) => {
          const b = e.currentTarget;
          // «Всё равно сделать» — решение по тому чату, что был 2 мин назад; уведомление вернули позже («Позже» / «Пропущено») — проверяем чат заново
          if (p.force && Date.now() - (p.forceAt || 0) > 120e3) p.force = false;
          b.disabled = true; b.textContent = p.force ? 'Отправляем…' : 'Делаем…';
          /* 1.20: действия — тот же бегунок, что у карточек; закрыли уведомление посреди дела — итог придёт новым уведомлением */
          const res = await сделатьПоЗаявке(x.id, x.cr, p, { наВиду: () => el.isConnected });
          // в чате города ждёт ответа просьба филиала (или чат не проверился) — ничего не сделано; второе нажатие — всё равно сделать
          if (res.guard) { итог.className = 'tst-d warn'; итог.textContent = res.text; p.force = true; p.forceAt = Date.now(); b.disabled = false; b.textContent = res.guard.nocheck ? 'Сделать без проверки' : 'Всё равно сделать'; return; }
          await markSeen(x.id, x.F.seen);
          итог.className = 'tst-d'; итог.replaceChildren(...строкиИтога(res.text, res.ok));   // 11: не сделанное — первым
          b.remove();
          if (res.ok) setTimeout(() => el.remove(), 20000);
        } }, 'Сделать'),
        h('button', { class: 'sm', onclick: () => { el.remove(); открытьПоЗаявке(x, false); } }, 'Открыть')],
      conv: x.id,
      foot: [h('span', {}, 'Взят автоприёмом: клиент пишет по созданной заявке'),
        h('button', { class: 'sm ghost', title: 'Выключить «Клиенты с созданной заявкой» в Автоприёме', onclick: async (e) => {
          const b = e.currentTarget;
          AUTO.follow = false; try { await store.set('autoClaim', { on: AUTO.on, max: AUTO.max, almost: AUTO.almost, followOn: false }); } catch (_e) { /* устарело */ }
          b.textContent = 'больше не беру'; b.disabled = true; } }, 'Не брать такие')] });
  }
  /* «Взять» руками (список «Готовые»): кнопка не нажимается дважды, итог — в шапке списка, а не «HTTP 409».
     БЕРЁМ — диалоги, которые сейчас берутся и открываются: список перерисовывается (идёт проверка), и новая кнопка
     той же строки второй запрос не шлёт (двойной щелчок попадал во вторую кнопку). */
  const БЕРЁМ = new Set();
  async function взятьРуками(x, btn) {
    if (btn) { btn.disabled = true; btn.textContent = x.transfer ? 'Принимаю…' : 'Беру…'; }
    const r = await взятьДиалог(x);
    if (r.ok) { AUTO.checked.delete(x.id); убратьИзГотовых(x.id); READY.note = null; return true; }
    if (r.drop) убратьИзГотовых(x.id);
    if (r.stop && AUTO.on) await выключитьАвтоприём(r.why);
    if (r.readOnly && AUTO.on) толькоЧтение();
    READY.note = { kind: r.drop ? 'warn' : 'bad', text: (x.name ? x.name + ': ' : '') + (r.drop ? r.why : 'не получилось ' + (x.transfer ? 'принять передачу' : 'взять диалог') + ' — ' + r.why) };
    if (btn && btn.isConnected) { btn.disabled = false; btn.textContent = x.transfer ? 'Принять передачу' : 'Взять'; }
    БЕРЁМ.delete(x.id);                                                 // не взяли — кнопку снова можно нажать
    drawReadyIfOpen();
    return false;
  }
  async function открытьПоЗаявке(x, claim, btn) {
    if (БЕРЁМ.has(x.id)) return;                                        // уже берём / открываем — второе нажатие ничего не шлёт
    БЕРЁМ.add(x.id);
    try {
      if (claim && x.inbox !== false) {
        if (convIdNow() !== x.id && черновикЗдесь()) { сказатьПроЧерновик(x.id); return; }
        if (!(await взятьРуками(x, btn))) return;
      }
      await связатьСЗаявкой(x);
      убратьИзГотовых(x.id);
      closePanel();
      if (!(await перейти(x.id))) return;
      showAdditionCard(x.id, x.cr, { ...x.F.r, text: x.F.text }, x.F.seen);
    } finally { БЕРЁМ.delete(x.id); }
  }
  // раз в 40 с: автоприём — как раньше; без него — только со «слухом» и «Проверять новые сразу»: сверка «Входящих»
  setInterval(() => {
    if(личнаяВкладка)return;
    if (RTX && (МГН.отложено.size || МГН.дочитатьПотом) && document.visibilityState === 'visible') { сверкаСкоро(0); return; }   // ждут с тех пор, как вкладка не была ведущей
    if (AUTO.on) { автоприём().catch(() => {}); return; }
    if (!RTX || !МГН.сразу) return;                                    // без «слуха» — как в 1.18
    if (!мгновенно()) сверкаБезАвто().catch(() => {});
    else if (Date.now() - МГН.сверкаAt > ПОЛНЫЙ_СПИСОК_МС) сверкаСкоро(0);
  }, 40000);

  /* ---------- МГНОВЕННО: что делаем по событию LeadChat ----------
     Проверять и брать — ТОЛЬКО видимая ведущая вкладка (lcz-leader); пришло в фоне — ждёт (≤50) и разбирается, как только вкладка
     снова видна и ведущая, вместе со сверкой. Проверки — по две разом, новые первыми; брать — по одному за раз (и круг, и события),
     нагрузку — заново перед каждым; по результату, который клиент уже «перерос» новым сообщением, не берём. */
  // что автоприём берёт: готовые; «почти» и «по созданной» — если включено; вёл лид-бот, «думает», отказался, не заявка — никогда.
  // 2.1.1 «почти» — только когда клиент по смыслу идёт к выезду (согласен) и не хватает мелочи: времени, номера дома, согласия с ценой «от N»
  // (территория и регламент «в форме» — как раньше); не хватает адреса, сути, телефона или неясно, нужен ли выезд, — не берём
  const МЕЛОЧЬ = ['time', 'house', 'price', 'territory', 'reglament'];
  const почтиБерётся = (res) => res.согласен === true && Array.isArray(res.пробелы) && res.пробелы.every((k) => МЕЛОЧЬ.includes(k))
    && res.пробелы.filter((k) => k !== 'territory' && k !== 'reglament').length <= 1;
  function берётся(res) { return !!res && !res.bot && (res.st === 'ready' || (AUTO.almost && res.st === 'almost' && почтиБерётся(res)) || (AUTO.follow && res.st === 'follow')); }
  // результат проверки — в «Готовые» (заменить строку, а не добавить вторую) и в число на кнопке
  function вГотовые(res, изСписка) {
    if (!res || !res.id || READY.gone.has(res.id)) return;
    const i = READY.items.findIndex((y) => y.id === res.id);
    if (i >= 0) READY.items[i] = res;
    else { READY.items.push(res); if (!изСписка && READY.at) { READY.total++; READY.done++; } }
    drawReadySoon();
    drawReadyTab();
    if (!изСписка || МГН.тост.has(res.id)) тостНовые(res);
  }
  // приём — по одному за раз: круг 40 с и события не берут параллельно (лимит «не больше N» не превысим, дважды не возьмём)
  function взятьЕслиМожно(row, res, my) {
    const p = МГН.приём.then(() => взятьСейчас(row, res, my));
    МГН.приём = p.catch(() => {});
    return p;
  }
  // итог: 'ok' | 'skip' | 'later' (клиент дописал — решит новая проверка) | 'retry' | 'capped' | 'stop'
  async function взятьСейчас(row, res, my) {
    const свой = () => my === undefined || my === AUTO.gen;              // круг, начавший приём, не сменился
    if (!AUTO.on || !alive() || document.visibilityState !== 'visible' || !свой()) return 'skip';
    if (AUTO.толькоЧтение) return 'skip';                              // роль только для чтения: в эту сессию не берём
    if (!(await ведущая())) return 'skip';
    // «Отошёл» — не берём; статус знаем из круга или события presence, иначе спрашиваем (не чаще раза в 5 минут)
    if (Date.now() - МГН.presenceAt > 5 * 60e3) {
      const pr = await LC.get('/presence').catch(() => null);
      AUTO.away = !!(pr && pr.status === 'away'); МГН.presenceAt = Date.now();
    }
    if (AUTO.away) return 'skip';
    if (!берётся(res) || row._transfer || row.bot_active || БЕРЁМ.has(row.id) || (row.account && AUTO.skipAcc.has(String(row.account.id)))) return 'skip';
    // со «слухом»: уже не во «Входящих» (взяли, закрыли) или брали сами за последние 30 минут — второй раз не берём
    const ушёл = () => !!RTX && (READY.gone.has(row.id) || (МГН.взяты.get(row.id) || 0) > Date.now() - 30 * 60e3);
    // клиент написал после разбора (в строке другое время) или пришла расшифровка / карточка — по старому разбору не берём: решит новая проверка
    const устарел = () => { const свежая = МГН.строки.get(row.id); return !!(свежая && res._key && ключСтроки(свежая) !== res._key) || (res._от !== undefined && (МГН.сброс.get(row.id) || 0) > res._от); };
    if (ушёл()) return 'skip';
    if (устарел()) return 'later';
    // со «слухом» разбор успевает раньше лид-бота: даём ему ответить (до 15 с) — его заметку «считает заявку собранной» услышим и
    // разберём заново (тогда не берём), а нет — возьмём по этому же разбору
    const бот = RTX ? ждётБота(res) : 0;
    if (бот) { вОчередь(МГН.строки.get(row.id) || row, бот + 300); return 'later'; }
    // нагрузку — заново перед каждым приёмом: диалоги могли взять или закрыть в другом окне
    const у = await сколькоУМеня();
    // сам вернул его в очередь за последние 30 минут («я не тот, кто нужен») — обратно на себя не берём (LC.me теперь известен)
    const вернул = МГН.вернул.get(row.id);
    if (вернул && LC.me && вернул.by === LC.me.id && Date.now() - вернул.at < 30 * 60e3) { МГН.взяты.set(row.id, вернул.at); return 'skip'; }
    if (!AUTO.on || !свой() || ушёл()) return 'skip';
    if (устарел()) return 'later';
    if (у >= AUTO.max) { AUTO.capped = true; return 'capped'; }        // лимит — для всех диалогов
    // p11: пока шли проверка, бот и лимит, по диалогу начали создавать заявку (здесь или в другой вкладке) или создали — не берём
    if ((await создаётсяПоДиалогу(row.id)) || (await созданаПосле(row.id, res._от || 0))) return 'later';
    if (!AUTO.on || !свой() || ушёл()) return 'skip';
    const r = await взятьДиалог(row);
    AUTO.checked.delete(row.id);
    if (!r.ok) {
      if (r.drop) убратьИзГотовых(row.id);
      if (r.channel) AUTO.skipAcc.add(r.channel);                       // канал ведут другие (403 channel_not_assigned)
      if (r.stop) { await выключитьАвтоприём(r.why); return 'stop'; }
      if (r.readOnly) { толькоЧтение(); return 'stop'; }               // не «повторим на следующем круге»: роль не сменится сама
      if (!r.drop && !r.channel) { AUTO.retryAt = Date.now() + 40e3; return 'retry'; }   // сбой связи / LeadChat — повторим на следующем круге
      return 'skip';
    }
    for (const [id, t] of МГН.взяты) if (Date.now() - t > 30 * 60e3) МГН.взяты.delete(id);
    for (const [id, x] of МГН.вернул) if (Date.now() - x.at > 30 * 60e3) МГН.вернул.delete(id);
    МГН.взяты.set(row.id, Date.now());
    AUTO.taken.push(res);
    убратьИзГотовых(row.id);
    if (AUTO.follow && res.st === 'follow') { await связатьСЗаявкой(res); notifyFollow(res); } else notifyTaken(res);
    return 'ok';
  }
  // строка — на проверку. мс — подождать (LeadChat пишет телефон и адрес в несколько шагов; не дольше 20 с от первого повода)
  function вОчередь(row, мс) {
    if (!row || !row.id || READY.gone.has(row.id) || row.status === 'closed') return;
    // «Проверять новые сразу» выключено, а брать сейчас некому (автоприём выкл, «Отошёл», лимит) — ИИ и CRM не тратим; догонит круг
    if (!МГН.сразу && (!AUTO.on || AUTO.away || AUTO.capped)) return;
    if (мс) {
      const было = МГН.ждут.get(row.id), первый = было ? было.first : Date.now();
      if (было) clearTimeout(было.t);
      МГН.ждут.set(row.id, { first: первый, t: setTimeout(() => { МГН.ждут.delete(row.id); вОчередь(МГН.строки.get(row.id) || row); },
        Math.max(0, Math.min(мс, первый + 20e3 - Date.now()))) });
      return;
    }
    МГН.очередь.delete(row.id);                                         // в конец: разбираем новые первыми
    МГН.очередь.set(row.id, row);
    разобратьОчередь();
  }
  // один разборщик, до двух проверок разом; не видна или не ведущая — всё в «отложено» (без запросов)
  async function разобратьОчередь() {
    if (МГН.разбор) return;
    МГН.разбор = true;
    try {
      while (МГН.очередь.size && МГН.работают < 2) {
        if (!alive()) { МГН.очередь.clear(); return; }
        if (document.visibilityState !== 'visible' || !(await ведущая())) { отложить(); return; }
        if (!МГН.очередь.size || МГН.работают >= 2) break;
        const [id, row] = [...МГН.очередь].pop();                      // самый новый
        МГН.очередь.delete(id);
        МГН.работают++;
        разобратьСтроку(row).catch(() => {}).finally(() => { МГН.работают--; разобратьОчередь(); });
      }
    } finally { МГН.разбор = false; }
  }
  function отложить() {
    for (const [id, row] of МГН.очередь) { МГН.отложено.delete(id); МГН.отложено.set(id, row); }
    МГН.очередь.clear();
    // самые старые — их догонит сверка при возврате во вкладку (без отметки сверки при возврате могло и не быть: сокет жив)
    while (МГН.отложено.size > 50) { МГН.отложено.delete(МГН.отложено.keys().next().value); МГН.дочитатьПотом = true; }
  }
  function отложенныеВОчередь() {
    if (!МГН.отложено.size || document.visibilityState !== 'visible') return;
    const l = [...МГН.отложено.values()];
    МГН.отложено.clear();
    for (const r of l) вОчередь(МГН.строки.get(r.id) || r);
  }
  async function разобратьСтроку(row) {
    const r = МГН.строки.get(row.id) || row;                            // самая свежая строка этого диалога
    const res = await проверитьКэш(r);
    if (READY.gone.has(r.id)) return;                                   // пока проверяли — взяли или закрыли
    вГотовые(res);
    if (!(AUTO.on && берётся(res))) return;
    try { await взятьЕслиМожно(r, res); }
    catch (e) { AUTO.err = String((e && e.message) || e).slice(0, 140); AUTO.retryAt = Date.now() + 40e3; drawReadyIfOpen(); }   // повторит круг
  }
  // событие без строки — дочитать «Входящие»: один GET /inbox на всю пачку (400 мс)
  function дочитать(id) {
    if (!id) return;
    МГН.ids.add(id);
    if (!МГН.idsT) МГН.idsT = setTimeout(() => { МГН.idsT = 0; дочитатьСейчас().catch(() => {}); }, 400);
  }
  async function дочитатьСейчас() {
    if (!МГН.ids.size) return;
    if (!alive() || document.visibilityState !== 'visible' || !(await ведущая())) { МГН.ids.clear(); МГН.дочитатьПотом = true; return; }   // догонит сверка при возврате
    const ids = [...МГН.ids];
    МГН.ids.clear();
    let rows;
    try { rows = await входящие(); } catch (_e) { сверкаСкоро(15e3); return; }   // LeadChat не ответил — сверимся чуть позже
    const по = new Map(rows.map((r) => [r.id, r]));
    for (const id of ids) { const r = по.get(id); if (r) вОчередь(r); else if (!rows.неполный) убратьИзГотовых(id); }
  }
  // сверка через REST: у сокета нет повтора пропущенного (обрыв, новая вкладка, вернулись во вкладку)
  function сверкаСкоро(мс) {
    const срок = Date.now() + мс;
    if (МГН.сверкаT && МГН.сверкаК <= срок) return;                   // уже назначена на раньше
    clearTimeout(МГН.сверкаT);
    МГН.сверкаК = срок;
    МГН.сверкаT = setTimeout(() => { МГН.сверкаT = 0; сверкаСейчас().catch(() => {}); }, мс);
  }
  async function сверкаСейчас() {
    if (!alive()) return;
    // вкладка в фоне или не ведущая — сверимся, когда её покажут и она станет ведущей (сокет мог переоткрыться в фоне)
    if (document.visibilityState !== 'visible' || !(await ведущая())) { МГН.дочитатьПотом = true; return; }
    if (МГН.сверкаИдёт) { сверкаСкоро(2000); return; }
    МГН.сверкаAt = Date.now();
    МГН.дочитатьПотом = false;
    отложенныеВОчередь();
    try {
      if (AUTO.on) { AUTO.countKey = ''; await автоприём(); return; }   // круг сам прочитает список и возьмёт
      МГН.сверкаИдёт = true;
      if (МГН.сразу) новыеВОчередь(await входящие());
      else if (READY.items.length) await входящие();                    // только убрать из «Готовых» ушедших
    } catch (_e) { /* LeadChat не ответил — следующий круг повторит */ }
    finally { МГН.сверкаИдёт = false; }
  }
  // «слух» есть, но сокет молчит, автоприём выключен: раз в 40 с — по счётчику, как круг автоприёма
  async function сверкаБезАвто() {
    if (AUTO.on || !RTX || мгновенно() || !МГН.сразу || МГН.сверкаИдёт || !alive() || document.visibilityState !== 'visible') return;
    if (!(await ведущая())) return;
    МГН.сверкаИдёт = true;
    try {
      // старый LeadChat без /inbox/count (404) — просто читаем список
      const c = await LC.get('/inbox/count').catch((e) => { if (e && e.status === 404) return null; throw e; });
      const key = c && typeof c.count === 'number' ? c.count + '|' + (Number(c.escalated) || 0) : '';
      if (key && key === МГН.countKey && Date.now() - МГН.fullAt < ПОЛНЫЙ_СПИСОК_МС) return;
      const rows = await входящие();
      МГН.countKey = key; МГН.fullAt = Date.now();
      новыеВОчередь(rows);
    } finally { МГН.сверкаИдёт = false; }
  }
  /* Сверка без автоприёма: что уже проверено с той же строкой — в «Готовые»; на проверку — только новые (во «Входящих» с открытия
     страницы, −10 минут) и те, что уже в «Готовых». Старые проверятся, когда оператор откроет «Готовые»: иначе 13 вкладок разом
     после F5 гоняли бы ИИ по всей очереди. */
  function новыеВОчередь(rows) {
    const с = МГН.с - 10 * 60e3;
    for (const r of rows) {
      if (r._transfer) { вОчередь(r); continue; }                       // «Передали вам» — без разбора
      const c = AUTO.checked.get(r.id);
      if (c && c.key === ключСтроки(r)) { вГотовые(c.res); continue; }
      const t = Math.max(Date.parse(r.offered_at || '') || 0, Date.parse(r.waiting_since || '') || 0);
      if (t >= с || READY.items.some((x) => x.id === r.id)) вОчередь(r);
    }
  }
  /* «Глухой» сокет: в моих «Входящих» появился диалог, о котором события не было (пришёл, пока сокет был открыт).
     Два раза подряд — не верим сокету, работаем как раньше (раз в 40 с) и пишем об этом в «Готовых». Молча не ломаемся. */
  function сверитьАнонсы(rows) {
    if (!RTX || !RTX.открыт || !RTX.открытAt) return;
    const now = Date.now();
    let новых = 0, пропущено = 0;
    for (const r of rows) {
      const t = Date.parse(r.offered_at || '');
      if (r._transfer || !t || t < RTX.открытAt + 60e3 || now - t < 10e3) continue;   // 60 с — запас на расхождение часов
      новых++;
      if (!МГН.анонс.has(r.id)) пропущено++;
      МГН.анонс.set(r.id, МГН.анонс.get(r.id) || now);
    }
    if (пропущено) МГН.пропуски++;
    else if (новых) МГН.пропуски = 0;
    // забываем через час — но не тех, кто всё ещё во «Входящих»: диалог, который ждёт дольше часа, иначе считался бы
    // «пропущенным» событием, и исправный сокет объявлялся бы «глухим»
    const есть = new Set(rows.map((r) => r.id));
    for (const [id, at] of МГН.анонс) if (now - at > 60 * 60e3 && !есть.has(id) && !rows.неполный) МГН.анонс.delete(id);
    for (const [id, at] of МГН.сброс) if (now - at > 60 * 60e3) МГН.сброс.delete(id);
  }
  const воВходящих = (id) => МГН.строки.has(id) || МГН.анонс.has(id) || AUTO.checked.has(id) || READY.items.some((x) => x.id === id);
  // расшифровка, карточка клиента: строка та же, а разбор устарел — забыть его (и идущую сейчас проверку тоже)
  function сброситьПроверку(id) { AUTO.checked.delete(id); МГН.сброс.set(id, Date.now()); }
  // заметка в диалоге «Входящих» — проверить заново (клиент пишет — проверка и так будет после его тишины)
  function заметкаВоВходящих(id) {
    const r = МГН.строки.get(id);
    if (!r || r._transfer) return;
    сброситьПроверку(id);
    if (!МГН.пишет.has(id)) вОчередь(r, 1500);
  }
  /* Лид-бот подсказывает в этом диалоге (его заметки есть), а на последнее сообщение клиента ещё не ответил — сколько мс подождать
     (до 15 с от сообщения клиента; лид-бот отвечает за ~9 с). По событию разбор готов раньше бота, и признай он заявку собранной
     («Лид-бот считает заявку собранной» — её заведёт он) уже после нашего «Взять», вышел бы дубль. */
  function ждётБота(res) {
    const m = (res && res.A && res.A.ctx && res.A.ctx.messages) || [];
    const бота = (x) => x && x.direction === 'note' && x.sender_type === 'bot';
    if (!m.some(бота)) return 0;
    let i = m.length - 1;
    while (i >= 0 && m[i].direction !== 'in') i--;
    if (i < 0 || m.slice(i + 1).some(бота)) return 0;                  // бот уже ответил на последнее сообщение клиента
    const t = Date.parse(m[i].created_at);
    return t ? Math.max(0, Math.min(15e3, t + 15e3 - Date.now())) : 0;
  }
  // клиент пишет несколько сообщений подряд — проверяем через 5 с тишины (но не позже 20 с от первого)
  function клиентПишет(id) {
    const было = МГН.пишет.get(id), первый = было ? было.first : Date.now();
    if (было) clearTimeout(было.t);
    const ждать = Math.max(0, Math.min(5000, первый + 20e3 - Date.now()));
    МГН.пишет.set(id, { first: первый, t: setTimeout(() => { МГН.пишет.delete(id); const r = МГН.строки.get(id); if (r) вОчередь(r); }, ждать) });
  }
  // открытый диалог: новое сообщение или расшифровка — смотрим сразу, а не через 20 с
  function watchСкоро(мс) {
    clearTimeout(МГН.watchT);
    МГН.watchT = setTimeout(() => { if (watching || !alive()) return; watching = true; watch().catch(() => {}).finally(() => { watching = false; }); }, мс);
  }
  // клиент ответил — «молчит» по нему уже неправда: убираем, пока оператор не нажал «Решён»
  function молчитОтветил(id) {
    if (!МОЛЧИТ.list.some((x) => x.id === id)) return;
    МОЛЧИТ.list = МОЛЧИТ.list.filter((x) => x.id !== id);
    МОЛЧИТ.shown = МОЛЧИТ.list.map((x) => x.id).join(',');
    if (!МОЛЧИТ.list.length) { if (МОЛЧИТ.el) МОЛЧИТ.el.remove(); МОЛЧИТ.el = null; } else notifySilent();
  }
  /* 2.3 (лист «Уведомления»): справочное «Новые во «Входящих»» — не уведомлением, а числом на кнопке «Готовые»: новое, чего вы ещё не видели, —
     подсвечено, пока «Готовые» не откроете. Состав — как у прежнего окошка: «можно создать», «почти», передачи (без автоприёма). МГН.тостEl
     остаётся пустым: прежние места, что убирали окошко, ничего не ломают */
  function тостНовые(res) {
    if (!RTX) return;
    if (res && res.id) {
      МГН.тост.delete(res.id);
      if (/^(ready|almost|transfer)$/.test(res.st) && !READY.gone.has(res.id)) МГН.тост.set(res.id, res);
    }
    if (AUTO.on || !МГН.сразу) МГН.тост.clear();
    for (const id of [...МГН.тост.keys()]) if (READY.gone.has(id) || !READY.items.some((x) => x.id === id)) МГН.тост.delete(id);
    if (МГН.тостEl) { МГН.тостEl.remove(); МГН.тостEl = null; }
    const ключ = [...МГН.тост.keys()].sort().join(',');
    if (ключ === МГН.тостКлюч) return;
    МГН.тостКлюч = ключ;
    drawReadyTab(); rbLabel();
  }
  // новые (ещё не видели в «Готовых») — сколько
  const новыхНеВидели = () => { const видели = new Set(String(МГН.тостСкрыт || '').split(',')); return [...МГН.тост.keys()].filter((id) => !видели.has(id)).length; };
  // кто я в LeadChat — для presence; узнаём один раз, и только ведущая видимая вкладка (остальные LeadChat не спрашивают)
  function ктоЯ() {
    if (LC.me && LC.me.id) return Promise.resolve(LC.me.id);
    if (document.visibilityState !== 'visible') return Promise.resolve('');
    if (!МГН.ктоP) МГН.ктоP = ведущая().then((v) => (v ? моёId() : '')).catch(() => '').finally(() => { МГН.ктоP = null; });
    return МГН.ктоP;
  }
  // взяли, закрыли, отказался — из всех очередей и «Готовых», без единого запроса (в любой вкладке)
  function убратьСобытием(id) {
    МГН.очередь.delete(id); МГН.отложено.delete(id); МГН.строки.delete(id); МГН.ids.delete(id);
    AUTO.checked.delete(id);
    убратьИзГотовых(id);
  }
  /* 12.10: кадр сокета — у диалога появился (или стёрт) № заявки лид-центра. Строка «Входящих» и деталь открытого диалога — с ним
     (следующая проверка и форма увидят «заявка уже есть»). Открытая форма этого диалога без своей записи о заявке — сразу плашка
     «по этому диалогу заявка уже создана — № … (из LeadChat)» и «Создать ещё одну»; кнопка у диалога — «№ …». Свою запись не трогаем */
  function номерЗаявкиКадром(id, n, at) {
    const поля = { crm_request_id: n || null, crm_request_at: n ? at || new Date().toISOString() : null };
    const r = МГН.строки.get(id);
    if (r) МГН.строки.set(id, { ...r, ...поля });
    if (W.conv === id && W.meta && W.meta.conv) W.meta.conv = { ...W.meta.conv, ...поля };
    const ст = ПАМЯТЬ.get(id);
    for (const x of new Set([S, ст && ст.S])) {
      if (!x || x.id !== id || !x.conv) continue;
      x.conv = { ...x.conv, ...поля };
      if (x.created && !x.created.изLC) continue;                        // своя запись о заявке — главнее
      x.created = заявкаLC(x.conv);
      if (x === S && формаЭтого()) render2keep();
    }
    if (convIdNow() === id && !задачаИдёт(id)) store.get('created', {}).then((all) => {
      if ((all || {})[id] || convIdNow() !== id || задачаИдёт(id)) return;
      btnState({ done: !!n, ready: false, id: n || null });
    }).catch(() => {});
  }
  function наСобытиеLC(e) {
    if (!alive() || !e || !e.t) return;
    const я = (LC.me && LC.me.id) || '';
    const id = e.id || '';
    switch (e.t) {
      // новый сокет — сверка (с разбросом: вкладки всей смены не бьют разом); сеть «моргает» и сокет переоткрывается каждые
      // пару секунд — сверка не чаще раза в 15 с, а не на каждое открытие
      case 'rt:open': сверкаСкоро(Math.max(2000 + Math.random() * 6000, МГН.сверкаAt + 15e3 - Date.now())); drawReadyIfOpen(); return;
      // rt:closing — LeadChat сам бросил сокет (нет pong'а) или pong'а нет 12 с: строка связи «не сразу» — без ожидания onclose
      case 'rt:close': case 'rt:closing': drawReadyIfOpen(); return;
      // адрес сменился (pushState / replaceState / «назад»): диалог сверяем сразу, а не обходом; тот же путь (поиск, якорь) — не повод
      case 'rt:route': if (location.pathname !== маршрутБыл) { маршрутБыл = location.pathname; if (tickT) { clearTimeout(tickT); tickT = 0; } tickSafe(); } return;
      case 'inbox:new': case 'inbox:released': {
        if (!e.can_claim || !id) return;                                 // руководитель и наблюдатель очередь видят, но не берут
        МГН.анонс.set(id, Date.now());
        if (e.client) МГН.клиент.set(String(e.client), id);
        READY.gone.delete(id);                                           // снова в очереди (вернули, истёк отказ)
        const row = e.row && полнаяСтрока(e.row) && e.row.id === id ? { ...e.row, _inbox: true, _transfer: передачаМне(e.row) } : null;
        if (row) { МГН.строки.set(id, row); МГН.ids.delete(id); }
        // оператор сам вернул диалог в очередь («я не тот, кто нужен») — автоприём не отдаёт его ему же обратно через секунду
        if (e.t === 'inbox:released' && я && e.by === я) МГН.взяты.set(id, Date.now());
        // кто я, вкладка может ещё не знать (после F5, не была ведущей) — помним, кто вернул: проверит приём, когда узнает
        if (e.t === 'inbox:released' && e.by) МГН.вернул.set(id, { by: e.by, at: Date.now() });
        // брали его сами за последние 30 минут (вернули в очередь, повтор кадра) — снова не разбираем: не возьмём, а ИИ потратим
        if ((МГН.взяты.get(id) || 0) > Date.now() - 30 * 60e3) return;
        if (row) вОчередь(row); else дочитать(id);                       // строки нет (больше 64 КБ, не та) — один GET /inbox на пачку
        return;
      }
      case 'inbox:claimed':                                              // взял кто-то (или я в другой вкладке) — из «Готовых» сразу, в любой вкладке
        if (id) убратьСобытием(id);
        return;
      case 'inbox:declined':                                             // мой отказ (или его отмена) — из другой вкладки или из LeadChat
        if (!id) return;
        if (e.undone) { READY.gone.delete(id); const r = МГН.строки.get(id); if (r) вОчередь(r); else дочитать(id); }
        else { МГН.очередь.delete(id); МГН.отложено.delete(id); МГН.ids.delete(id); убратьИзГотовых(id); }   // строку помним — вдруг отменит отказ
        return;
      case 'conversation:updated': {
        if (!id) return;
        if (e.crm !== undefined) номерЗаявкиКадром(id, e.crm, e.crm_at);   // 12.10: № заявки у диалога — форма, «Готовые», кнопка
        const r0 = МГН.строки.get(id);
        // «Передали вам»: диалог за коллегой (in_inbox=false) — уходит, только когда передача решилась или диалог закрыли
        if ((r0 && r0._transfer) || READY.items.some((x) => x.id === id && x.st === 'transfer')) { if (e.status === 'closed' || e.transfer) убратьСобытием(id); return; }
        // диалог взял бот — из очереди ушёл (LeadChat убирает строку так же, applyWsEvent.ts: bot_active === true);
        // сообщения клиента боту — не повод проверять. Отдаст людям — придёт inbox:new со строкой
        if (e.in_inbox === false || e.status === 'closed' || e.bot === true) { if (воВходящих(id)) убратьСобытием(id); }
        // клиента переименовали (№ заявки в имени — «заявка уже есть») или у диалога появился / стёрт № заявки (12.10): прежний разбор
        // забыть, строку (с новым именем / номером) — дочитать и проверить
        else if ((e.cl || e.crm !== undefined) && воВходящих(id)) { сброситьПроверку(id); дочитать(id); }
        // in_inbox: true без строки не дочитываем: в очередь диалог ставят кадром inbox:new / inbox:released со строкой и только
        // операторам его канала (lc: inbound.py, reclaim.py, handoff.py, users.py, routes/conversations.py), а conversation:updated
        // уходит всем — GET /inbox на каждый такой патч был бы почти всегда про чужой канал
        return;
      }
      case 'conversation:assigned':
        if (id && e.for_me && e.offer) { READY.gone.delete(id); дочитать(id); }   // передача мне — строка «Передали вам»
        return;
      case 'message:new': {
        if (!id) return;
        // заметка в диалоге «Входящих»: оператора (адрес, время) или лид-бота «считает заявку собранной» (заявку заведёт он — автоприём
        // такой не берёт) — разбор устарел. Подсказки бота («Подсказка бота: …») в разбор не идут — не повод
        if (e.dir === 'note') { if ((e.from !== 'bot' || e.lb) && !e.owner) заметкаВоВходящих(id); return; }
        if (e.dir !== 'in') return;
        const r0 = МГН.строки.get(id);
        if (я && e.owner === я) молчитОтветил(id);
        if (e.owner) { if (r0 && !r0._transfer) убратьСобытием(id); }    // у диалога есть ответственный — из очереди он ушёл
        else if (воВходящих(id)) {
          // строку — как её отдаст GET /inbox (тот же ключ): проверка по старой строке не возьмёт, новая — решит
          if (r0) {
            const r = { ...r0, last_message_at: e.lm || e.at || r0.last_message_at,
              last_message: { ...(r0.last_message || {}), created_at: e.at || (r0.last_message || {}).created_at, direction: 'in', sender_type: 'client' } };
            if (e.ws === null || e.ws) r.waiting_since = e.ws;
            if (e.status) r.status = e.status;
            МГН.строки.set(id, r);
          }
          if (!e.voice) клиентПишет(id);                                  // голосовое — после расшифровки (message:transcript)
        }
        if (convIdNow() === id && !e.voice) watchСкоро(1500);
        return;
      }
      case 'message:transcript': {
        if (!id || e.st === 'running') return;
        сброситьПроверку(id);                                            // строка та же, а текст у голосового появился
        const r = МГН.строки.get(id);
        if (r && воВходящих(id) && !МГН.пишет.has(id)) вОчередь(r, 400);
        if (convIdNow() === id) watchСкоро(500);
        return;
      }
      case 'client:updated': {                                           // LeadChat дописал в карточку телефон или адрес (часто в несколько шагов)
        const cid = id || МГН.клиент.get(String(e.client || '')) || '';
        if (!cid || !воВходящих(cid)) return;
        сброситьПроверку(cid);
        const r = МГН.строки.get(cid);
        if (r && !МГН.пишет.has(cid)) вОчередь(r, 1500);
        return;
      }
      case 'presence:online': {
        if (!e.user) return;
        const применить = (моё) => {
          if (!моё || e.user !== моё) return;
          const был = AUTO.away;
          AUTO.away = e.status === 'away';
          МГН.presenceAt = Date.now();
          if (был && !AUTO.away) { AUTO.countKey = ''; сверкаСкоро(500); }   // снова на месте — список сразу
          drawReadyIfOpen();
        };
        if (я) применить(я); else ктоЯ().then(применить).catch(() => {});
        return;
      }
      default:
    }
  }

  /* Переход к диалогу внутри LeadChat (без перезагрузки страницы).
     LeadChat сам возвращает человека в диалог с недописанным ответом, если переход сделал не он (выборДиалога.ts) —
     поэтому: черновик есть — не уходим и говорим почему; ушли — через 400 мс проверяем, что LeadChat не вернул назад. */
  function черновикЗдесь() {
    const id = convIdNow();
    if (!id) return '';
    try {
      const s = JSON.parse(localStorage.getItem('leadchat-chat-ui') || 'null');
      const d = s && s.state && s.state.drafts && s.state.drafts[id];
      return String((d && d.text) || '').trim();
    } catch (_e) { return ''; }
  }
  // одно уведомление на все попытки: повторный щелчок обновляет его (куда перейти) и ставит на виду, а не плодит такие же
  let черновикEl = null;
  function сказатьПроЧерновик(id) {
    const o = { kind: 'warn', label: 'Недописанный ответ', title: 'В открытом диалоге недописанный ответ — LeadChat не даст из него уйти',
      lines: [h('div', { class: 'tst-d' }, 'Отправьте или сотрите его и нажмите ещё раз. Или откройте нужный диалог в новой вкладке.')],
      actions: [h('button', { class: 'sm pri', onclick: () => { if (черновикEl) черновикEl.remove(); черновикEl = null; window.open('/chats/' + encodeURIComponent(id), '_blank', 'noopener'); } }, 'Открыть в новой вкладке'),
      ], позже: false };
    if (черновикEl && тостЖив(черновикEl)) { обновитьТост(черновикEl, o); вСтопку(черновикEl, true); return; }
    черновикEl = тост(o);
  }
  // переход из тоста: недописанный ответ в открытом диалоге — тост НЕ убираем (подсказка «нажмите ещё раз» — про его кнопку)
  function черновикМешает(id) {
    if (convIdNow() === id || !черновикЗдесь()) return false;
    сказатьПроЧерновик(id);
    return true;
  }
  async function перейти(id) {
    if (convIdNow() !== id) {
      if (черновикЗдесь()) { сказатьПроЧерновик(id); return false; }
      history.pushState({}, '', '/chats/' + encodeURIComponent(id));
      window.dispatchEvent(new PopStateEvent('popstate'));
      await пауза(400);
      if (convIdNow() !== id) {
        const el = тост({ kind: 'warn', label: 'Переход', title: 'LeadChat не открыл диалог', lines: [h('div', { class: 'tst-d' }, 'Откройте его в списке диалогов или в новой вкладке.')],
          actions: [h('button', { class: 'sm pri', onclick: () => { el.remove(); window.open('/chats/' + encodeURIComponent(id), '_blank', 'noopener'); } }, 'Открыть в новой вкладке')], жить: 30e3 });
        return false;
      }
    }
    // панель и кнопка — уже про новый диалог: смену разбирает обход; начатую раньше (обход раз в 800 мс, наблюдатель) ждём до конца,
    // иначе она закрыла бы форму, которую откроют сразу после перехода. Уже на месте — тоже: адрес мог смениться до обхода
    try { await tick(); if (смена) await смена; } catch (_e) { /* вкладка устарела — скажет сборка */ }
    return true;
  }
  async function открытьГотовую(x, btn) {
    if (БЕРЁМ.has(x.id)) return;                                        // уже берём / открываем — второе нажатие ничего не шлёт
    БЕРЁМ.add(x.id);
    try {
      if (x.inbox !== false) {
        // в открытом диалоге недописанный ответ — LeadChat не отпустит; диалог не берём, пока оператор не решит
        if (convIdNow() !== x.id && черновикЗдесь()) { сказатьПроЧерновик(x.id); return; }
        if (!(await взятьРуками(x, btn))) return;
      }
      убратьИзГотовых(x.id);
      if (!(await перейти(x.id))) return;
      await collect(x.A);                                  // уже разобрано — сразу форма (передача — разбор заново)
    } finally { БЕРЁМ.delete(x.id); }
  }

  /* ---------- что уточнить по регламенту ---------- */
  async function runChecklist() {
    const P = S && S.prep && S.prep.ok ? S.prep : null;
    if (!P || !P.applId) return;
    const subId = (S.keepSel && S.keepSel.subId && (P.sub || []).some((o) => o.id === S.keepSel.subId)) ? S.keepSel.subId : P.subId;
    const key = [S.dir, P.cityText, P.applId, subId, S.lastId, S.ctx && S.ctx.partner, S.ctx && S.ctx.origin].join('|');
    if (S.checkKey === key) return;
    const my = S;
    S.checkKey = key;
    S.check = { busy: true };
    const applText = ((P.appl || []).find((o) => o.id === P.applId) || {}).text || '';
    const subText = ((P.sub || []).find((o) => o.id === subId) || {}).text || '';
    // тот же ключ, что у проверки готовности: регламент по этому сообщению уже сверен — ИИ второй раз не спрашиваем
    const r0 = await шаг('ck|' + [S.id, S.dir, P.cityText, applText, subText, S.lastId, S.ctx.partner, S.ctx.origin].join('|'), 60e3, () => send({ kind: 'lcz-checklist', args: { dir: S.dir, applText, subText, ctx: { ...S.ctx, city:LC_TERRITORY.чистыйГород(P.cityText||S.lead.city), crmCity:P.cityText, dirBasis: S.dirChosen ? 'operator' : 'account' } } }));
    if (S !== my || S.checkKey !== key) return;
    const r = r0 && { ...r0, results: (r0.results || []).map((x) => ({ ...x })) };   // общий ответ (кэш шагов) не правим
    // модель/производитель уже разобраны из переписки — пункт выполнен
    if (r && r.results) for (const x of r.results) {
      if (/модель и производитель/i.test(x.item) && (S.lead.brand || S.lead.model)) { x.done = true; x.answer = x.answer || [S.lead.brand, S.lead.model].filter(Boolean).join(' '); }
    }
    S.check = r || { ok: false, error: 'нет ответа', results: [] };
    const route = S.check.crm_route;
    if (S.check.ok && route && route.city_id && !route.mixed_work && String(P.cityId) !== String(route.city_id)) {
      keepEdits();
      await prepare({ cityId: String(route.city_id), city: route.city_text, cityFallback: undefined });
      return;
    }
    // ответы клиента по пунктам регламента — сразу в комментарий (перед строкой со ссылкой для отзыва);
    // что уже есть в описании (модель в сути: «Телевизор Xiaomi Mi S Pro…»), второй раз не пишем
    const ta = panel.querySelector('[data-f="comment"]');
    const текст = ta ? ta.value : S.lead.comment;
    const ответы = (S.check.results || []).filter((x) => x.done && x.answer).map((x) => x.answer);
    const новые = ответы.filter((a) => !ужеВТексте(a, безУточнено(текст)));
    S.check.dup = ответы.length - новые.length;
    // нет ответов (ИИ не ответил, у вида услуг нет пунктов) — комментарий не трогаем, прежняя строка остаётся
    if (ответы.length) {
      const стало = вставитьСтроку(текст, новые.length ? 'Уточнено: ' + новые.join('; ') + '.' : '');
      if (стало !== String(текст || '').trim()) { if (ta) ta.value = стало; else S.lead.comment = стало; }
    }
    S.check.added = новые.length > 0;
    if (формаЭтого()) render2keep();
    группыЗаранее();
  }
  const безУточнено = (text) => String(text || '').split('\n').filter((l) => !/^Уточнено: /.test(l.trim()) && !/^🟢.*🟢$/.test(l.trim())).join('\n');
  // ответ уже есть в тексте: его значимые слова (с точностью до окончаний) там встречаются;
  // «да», «нет», «есть» сами по себе ничего не значат — такие ответы пишем всегда
  const словаОтвета = (t) => String(t || '').toLowerCase().replace(/ё/g, 'е').match(/[a-zа-я0-9]+/g) || [];
  const ПУСТЫЕ = new Set(['да', 'нет', 'есть', 'не', 'без', 'был', 'была', 'было', 'были', 'будет', 'уже', 'еще', 'тоже', 'только', 'все', 'всё']);
  function ужеВТексте(answer, text) {
    const есть = new Set(словаОтвета(text).map((w) => w.slice(0, 6)));
    const w = словаОтвета(answer).filter((x) => /\d/.test(x) || (x.length >= 3 && !ПУСТЫЕ.has(x)));
    return w.length > 0 && w.filter((x) => есть.has(x.slice(0, 6))).length >= Math.ceil(w.length * 0.8);
  }
  function вставитьСтроку(text, line) {
    const parts = String(text || '').split('\n').filter((l) => !/^Уточнено: /.test(l.trim()));   // прежняя строка «Уточнено» заменяется
    const i = parts.findIndex((l) => /^🟢.*🟢$/.test(l.trim()));
    if (!line) { /* нечего дописывать — только убрать прежнюю */ } else if (i >= 0) parts.splice(i, 0, line); else parts.push(line);
    return parts.filter((l, k) => l.trim() || k < parts.length - 1).join('\n').trim();
  }
  /* «Не наш профиль» по регламенту («…газовые элементы не работаем», «вскрытием замков не занимаемся») — только
     предупреждение: отказать клиенту, не спросив филиал, регламент запрещает. Решает оператор */
  function неПрофильBox() {
    const c = S.check;
    if (c && !c.busy && c.hard_block) return h('div', { class: 'box bad', 'data-policy-block': '1' }, svg('warn'), h('div', { class: 'c' },
      h('div', {}, c.refuse || c.reason || c.approval),
      c.price_service_conflict?.quote ? h('div', { class: 'n mut' }, 'В переписке: «' + c.price_service_conflict.quote + '»') : '',
      c.price_review?.quote ? h('div', { class: 'n mut' }, 'В переписке: «' + c.price_review.quote + '»') : '',
      c.price_review?.recovery ? h('div', { class: 'n', 'data-price-recovery': '1' }, 'Уточнение для клиента: «' + c.price_review.recovery + '»') : '',
      h('div', { class: 'n mut' }, 'Регламент ' + (c.policy_version || 'не проверен') + ' · решение оператора')));
    if (!c || c.busy || !c.refuse) return '';
    const t = S.tg;
    return h('div', { class: 'box warn', 'data-refuse': '1' }, svg('warn'), h('div', { class: 'c' },
      h('div', {}, h('b', {}, 'По регламенту не наш профиль: '), '«' + c.refuse + '».'),
      h('div', { class: 'n mut' }, 'Сами не отказывайте — отказ без вопроса филиалу запрещён. Спросите филиал в чате города.'),
      h('div', { class: 'row', style: 'gap:6px;margin-top:4px;flex-wrap:wrap' },
        h('button', { class: 'sm pri', disabled: !!(t && t.busy), onclick: () => { S.check = { ...S.check, approval: S.check.approval || 'по регламенту не наш профиль: ' + c.refuse, refuse: '' }; openApproval(); } }, t && t.busy ? 'Открываем чаты…' : 'Отправить в чат города'),
        h('button', { class: 'sm', title: 'Работа клиента под это правило не подходит', onclick: () => { S.check = { ...S.check, refuse: '' }; render2keep(); } }, 'Не тот случай'))));
  }

  /* ДУБЛЬ ВНУТРИ LEADCHAT: тот же клиент пишет и в другой канал — заявку может завести другой оператор.
     Поиск LeadChat по номеру (tab=any — и закрытые), сверяем только строки, где телефон клиента — этот номер;
     текущий диалог и закрытые не в счёт. Заодно — история карточки этого клиента (GET /conversations/{id}/client-history:
     его же прошлые диалоги в других каналах, даже когда телефона в них нет; LeadChat сам грузит её при каждом открытии диалога,
     запрос дешёвый). Оба запроса разом, ждём не больше 6 с; поиск не ответил — серая строка и «ещё раз»; история не ответила
     (старый LeadChat) — без неё */
  const ДУБЛИ_МС = 6000;
  async function дублиLC(again) {
    const my = S, phone = String((S && S.lead && S.lead.phone) || '').replace(/\D/g, '').slice(-10);
    if (!my || phone.length !== 10 || (my.lcDup && my.lcDup.phone === phone && (!again || my.lcDup.busy))) return;
    const было = my.lcDup && !my.lcDup.busy && ((my.lcDup.rows || []).length || my.lcDup.error);   // что сейчас на экране
    my.lcDup = { phone, busy: true, rows: [] };
    let res;
    try {
      const срок = 'LeadChat не ответил за ' + ДУБЛИ_МС / 1000 + ' с';
      const история = my.id ? сТаймаутом(LC.get('/conversations/' + encodeURIComponent(my.id) + '/client-history'), ДУБЛИ_МС, срок).catch(() => null) : Promise.resolve(null);
      const [page, ист] = await Promise.all([сТаймаутом(LC.get('/conversations?tab=any&q=' + phone + '&limit=20'), ДУБЛИ_МС, срок), история]);
      const я = my.conv && my.conv.assignee && my.conv.assignee.id;
      // 2.2.1: диалог MAX — диалог Авито, из которого клиент пришёл (conv.авито), у этого же оператора — не дубль (одна заявка,
      // оформляет тот же человек). У другого оператора — предупреждаем: две заявки на одного клиента
      const откуда = LC_EXTRACT.каналMAX(my.conv) && авитоДиалога(my.conv) ? авитоДиалога(my.conv).id : '';
      const rows = ((page && page.items) || []).filter((r) => r && r.id && r.id !== my.id && r.status !== 'closed'
        && String((r.client && r.client.phone) || '').replace(/\D/g, '').slice(-10) === phone
        && !(откуда && r.id === откуда && я && r.assignee && r.assignee.id === я));
      // история карточки — тот же клиент (строки без телефона: id, status, account, assignee); закрытые и уже найденные не в счёт
      for (const r of (ист && ист.items) || []) if (r && r.id && r.id !== my.id && r.status !== 'closed' && !rows.some((x) => x.id === r.id)
        && !(откуда && r.id === откуда && я && r.assignee && r.assignee.id === я)) rows.push(r);
      res = { phone, rows: rows.slice(0, 3).map((r) => ({ id: r.id, who: (r.assignee && r.assignee.full_name) || '', mine: !!(я && r.assignee && r.assignee.id === я),
        channel: (r.account && r.account.title) || '' })) };
    } catch (e) { res = { phone, rows: [], error: String(e.message || e).slice(0, 80) }; }
    if (!my.lcDup || my.lcDup.phone !== phone) return;               // номер поменяли — ответ не наш
    my.lcDup = res;                       // ушли в другой диалог — ответ всё равно сохраняем: форма вернётся из памяти не с вечным «ищем»
    if (S === my && (res.rows.length || res.error || было) && формаЭтого()) render2keep();
  }
  function дублиLCBox() {
    const d = S && S.lcDup;
    if (!d || d.busy) return '';
    if (d.error) return h('div', { class: 'n mut' }, 'Другие диалоги клиента в LeadChat не проверились (' + d.error + ') ',
      h('button', { class: 'sm', style: SMALL, onclick: (e) => { e.target.disabled = true; дублиLC(true).catch(() => {}); } }, 'ещё раз'));
    if (!d.rows.length) return '';
    return h('div', { class: 'box warn', 'data-dup': '1' }, svg('warn'), h('div', { class: 'c' },
      ...d.rows.map((r) => h('div', {}, h('b', {}, 'Клиент уже в работе ' + (r.mine ? 'у вас' : r.who ? 'у ' + r.who : 'без ответственного (в очереди)')),
        ' в канале «' + (r.channel || '—') + '» ', h('a', { href: '/chats/' + encodeURIComponent(r.id), target: '_blank', rel: 'noopener' }, 'Открыть диалог'))),
      h('div', { class: 'n mut' }, 'Договоритесь, кто оформляет, — иначе будет две заявки.')));
  }
  function checkBox() {
    const c = S.check;
    if (!c) return '';
    if (c.busy) return h('div', { class: 'n mut' }, 'Сверяем с регламентом, что нужно уточнить…');
    const res = c.results || [];
    if (!res.length) return '';
    const нет = res.filter((x) => !x.done);
    const ответы = res.filter((x) => x.done && x.answer).map((x) => x.answer);
    const кратко = (t) => String(t).replace(/^(Если|В случае)[^,]*,\s*/i, '').replace(/^(нужно|необходимо)\s+(сразу\s+)?/i, '').replace(/^уточнять\s+/i, 'уточнить ').slice(0, 90);
    return h('div', { style: 'display:flex;flex-direction:column;gap:8px' }, res.length ? h('div', { class: 'box ' + (нет.length ? 'warn' : 'ok'), 'data-check': '1', tabindex: '-1' }, svg(нет.length ? 'warn' : 'check'), h('div', { class: 'c' },
      h('div', {}, h('b', {}, нет.length ? 'Уточните у клиента:' : 'По регламенту всё уточнено')),
      ...нет.map((x) => h('div', { title: x.item }, '• ' + кратко(x.item))),
      ответы.length ? h('div', { class: 'n mut', title: res.filter((x) => x.done).map((x) => x.item + ' — «' + x.answer + '»').join('\n') }, '✓ ' + ответы.join('; ').slice(0, 90)
        + (c.added ? ' — в комментарии' : c.dup ? ' — уже есть в описании' : '')) : '',
      c.error ? h('div', { class: 'n mut' }, c.error) : '')) : '');
  }

  /* ---------- Telegram: согласование с филиалом в чате города ---------- */
  const tgSentGet = async (conv) => ((await store.get('tgSent', {}))[conv]) || null;
  const sentList = (rec) => (!rec ? [] : rec.chats ? rec.chats : rec.chat ? [{ chat: rec.chat, title: rec.title, msg: rec.msg }] : []);
  /* группы Telegram (список чатов) — одни на вкладку, 10 мин: окно согласования и отписка после создания не ждут их заново.
     Неудача не запоминается (шаг). Только чтение списка — отправка по-прежнему по нажатию */
  const группыTG = () => шаг('tg|chats', 10 * 60e3, () => send({ kind: 'lcz-tg', args: { action: 'chats' } }));
  // форма показала, что нужно согласование, — список групп заранее: «Спросить филиал» откроется сразу
  function группыЗаранее() {
    if (S && S.prep && S.prep.ok && ((S.check && (S.check.approval || S.check.refuse || S.check.maybe)) || terrReason() || repeatReason())) группыTG().catch(() => {});
  }
  // Операции двух карточек могут завершиться одновременно. Не теряем соседнюю запись при read → modify → write.
  let tgStoreTail = Promise.resolve();
  function tgSentUpdate(change) {
    const task = tgStoreTail.then(async () => { const m = await store.get('tgSent', {}); change(m); await store.set('tgSent', m); });
    tgStoreTail = task.catch(() => {});
    return task;
  }
  const tgSentSet = (conv, rec) => tgSentUpdate((m) => { m[conv] = rec; });
  const TG_BUSY = new Set();
  function workText() {
    const P = S.prep || {};
    const subId = (S.keepSel && S.keepSel.subId) || P.subId;
    return [((P.appl || []).find((o) => o.id === P.applId) || {}).text, ((P.sub || []).find((o) => o.id === subId) || {}).text].filter(Boolean).join(' / ');
  }
  // любая ошибка при подготовке — текстом в панели, а не вечное «Открываем чаты…»
  async function openApproval() {
    const my = S;
    try { await открытьСогласование(my); }
    catch (e) {
      if (S !== my) return;
      S.tg = { ...(S.tg && S.tg.chats ? S.tg : {}), busy: false, error: 'Не получилось подготовить согласование: ' + String((e && e.message) || e).slice(0, 150) + ' — выберите чат вручную или нажмите ещё раз' };
      render2keep();
    }
  }
  async function открытьСогласование(my) {
    keepEdits();
    my.tgЗаранее = true;                                               // 2.3: окно открыли (сами или заранее) — «Отмена» его само снова не откроет
    const прежний = S.tg && S.tg.offline && S.tg.text ? S.tg.text : '';    // «Проверить группы снова» — правки текста не теряем
    S.tg = { busy: true };
    render2keep();
    const r = await группыTG();
    if (S !== my) return;
    // 2.1.7: группы не получены (сервер недоступен, Telegram на ПК не на связи) — окно всё равно с текстом согласования:
    // скопировать и отправить в чат города вручную (раньше — только ошибка, текста не было)
    const нетГрупп = !r || !r.ok;
    const chats = нетГрупп ? {} : r.chats || {};
    S.tg = { busy: true, chats };
    const L = S.lead, P = S.prep || {};
    const city = P.cityText || L.city || '';
    let m = LC_TG.matchChat(chats, S.dir, city);
    // особые правила (электрика Хабаровск, партнёрские СПб/Екатеринбург): сначала их чат, при отказе — следующий
    const особыеЧаты = ((S.terr && S.terr.special) || []).flatMap((x) => x.chats || []);
    if (особыеЧаты.length) {
      const ids = особыеЧаты.flatMap((src) => Object.entries(chats).filter(([, c]) => new RegExp(src, 'i').test(String(c.title).toLowerCase().replace(/ё/g, 'е'))).map(([id]) => id));
      const opts = [...new Set([...ids, ...((m && m.options) || [])])];
      if (opts.length) m = { id: opts[0], title: chats[opts[0]].title, exact: true, options: opts, several: opts.length > 1 };
    }
    const dm = L.visit_date ? L.visit_date.slice(8, 10) + '.' + L.visit_date.slice(5, 7) : '';
    const text = LC_TG.approvalText({ dir: S.dir, city, addr: L.addr, work: workText(), problem: L.problem, name: L.name,
      technika: [L.brand, L.model].filter(Boolean).join(' '), visit: визитАвто(L) ? L.time_text : [dm, L.visit_time].filter(Boolean).join(' в ') || L.time_text,
      voiced: L.voiced, rule: S.check && S.check.approval });
    const R0 = историяКлиента();
    if (R0 && R0.okk) { const cc = LC_TG.claimChat(chats, S.dir); if (cc) m = { id: cc.id, title: cc.title, exact: true, options: [cc.id], several: false }; }
    S.tg = { chats, chat: m ? m.id : '', matched: m, city, picked: m ? [m.id] : [], авто: true, text: прежний || (R0 && R0.approval && R0.tg ? R0.tg : text), photos: [],
      ...(нетГрупп ? { offline: true, error: 'Группы Telegram не получены (' + String((r && r.error) || 'нет ответа').slice(0, 120) + '). Текст согласования — ниже: скопируйте и отправьте в чат города вручную' } : {}) };
    render2keep();
    // фото клиента из диалога — миниатюры с галочками, уйдут вместе с согласованием
    фотоКлиента(my.id).then((ph) => { if (S === my && S.tg && ph.length) { S.tg.photos = ph; render2keep(); } }).catch(() => {});
  }
  function keepTg() {
    const ta = panel.querySelector('[data-tg="text"]');
    if (!ta || !S || !S.tg) return;
    S.tg.text = ta.value;
    // поиск чата (S.tg.q) обновляется при наборе — из поля не перечитываем
    // 2.1.6: выбранные чаты — состоянием окна (S.tg.picked, по порядку: первый — куда уйдёт); отметки в окне — только его отражение
    if (!Array.isArray(S.tg.picked)) S.tg.picked = [...panel.querySelectorAll('[data-tg="pick"]:checked')].map((x) => x.value);
  }
  /* 2.1.6: отметить / снять чат согласования. Выбор оператора главнее чата, который расширение отметило само:
     отметил другой — согласование уходит туда, а отмеченный сам встаёт следующим «при отказе»
     (раньше уходило в отмеченный сам, а выбранный оператором вставал в очередь). Дальше — по порядку отметок */
  function отметитьЧат(id, on, изПоиска) {
    keepTg();
    const t = S.tg; let p = (t.picked || []).filter((x) => x !== id);
    if (изПоиска && on) t.q = '';                                       // нашёл и отметил — поиск очищаем
    if (on) p = t.авто ? [id, ...p] : p.concat(id);
    t.picked = p; t.авто = false; t.всем = false;
    render2keep();
  }
  // поиск чата: слова — части названия; «мнч / кп / бт», «быт», «комп» — направление чата
  const АЛИАС_БАЗЫ = { мнч: 'mnc', мастер: 'mnc', 'муж на час': 'mnc', кп: 'kp', комп: 'kp', компьютер: 'kp', компьютерная: 'kp', бт: 'bt', быт: 'bt', бытовая: 'bt', техника: 'bt' };
  const нормЧата = (x) => String(x || '').toLowerCase().replace(/ё/g, 'е').replace(/[^а-яa-z0-9]+/g, ' ').trim();
  function найтиЧаты(chats, q) {
    const слова = нормЧата(q).split(' ').filter(Boolean);
    if (!слова.length) return [];
    // «питер» = «спб», «екб» = «екатеринбург»: те же сокращения городов, что и при подборе чата города
    const варианты = (w) => [...new Set([w, ...(LC_TG.cityKeys ? LC_TG.cityKeys(w) : []).map(нормЧата)])].filter((x) => x.length >= 2);
    return Object.entries(chats || {}).filter(([, c]) => {
      const tt = ' ' + нормЧата(c.title), базы = LC_TG.базыЧата ? LC_TG.базыЧата(String(c.title || '').toLowerCase()) : [];
      // слово — начало слова в названии («моск», «бт сочи»); город в другом падеже — без 1–2 последних букв
      const есть = (x) => tt.includes(' ' + x) || (x.length >= 5 && tt.includes(' ' + x.slice(0, -1))) || (x.length >= 6 && tt.includes(' ' + x.slice(0, -2)));
      return слова.every((w) => (АЛИАС_БАЗЫ[w] ? базы.includes(АЛИАС_БАЗЫ[w]) || есть(w) : варианты(w).some(есть)));
    }).sort((a, b) => (LC_TG.СЛУЖЕБНЫЕ.test(a[1].title.toLowerCase()) - LC_TG.СЛУЖЕБНЫЕ.test(b[1].title.toLowerCase())) || a[1].title.localeCompare(b[1].title, 'ru'));
  }
  async function фотоКлиента(conv) {
    const page = await LC.get('/conversations/' + encodeURIComponent(conv) + '/messages?limit=50');
    const list = (page.items || []).filter((m) => m.direction === 'in').flatMap((m) => (m.attachments || [])
      .filter((a) => a && a.url && (a.kind === 'image' || /\.(jpe?g|png|webp)(\?|$)/i.test(String(a.url) + ' ' + String(a.name || ''))))
      .map((a) => ({ url: a.url, name: a.name || 'фото', at: m.created_at })));
    const out = [];
    for (const x of list.slice(-6)) {
      try { const blob = await картинка(x.url); out.push({ ...x, blob, src: URL.createObjectURL(blob), on: true }); } catch (_e) { /* не загрузилось */ }
    }
    out.forEach((x, i) => { x.on = i >= out.length - 4; });          // по умолчанию — последние 4
    return out;
  }
  // фото с сервера LeadChat (любой его адрес: sslip, chat.partner-lead-centre.ru); токен — только своему же адресу, срок — 30 с
  const свойАдрес = (url) => { try { return new URL(url, location.href).origin === location.origin; } catch (_e) { return false; } };
  async function картинка(url) {
    let r = await fetchСрок(url, { credentials: 'include' }, 30000);
    if ((r.status === 401 || r.status === 403) && свойАдрес(url)) r = await fetchСрок(url, { headers: { Authorization: 'Bearer ' + await LC.tok() } }, 30000);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return сТаймаутом(r.blob(), 30000, 'фото не догрузилось за 30 с');   // заголовки пришли, а тело «застряло» — не ждём вечно
  }
  const сТаймаутом = (p, ms, msg) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error(msg)), ms))]);
  const вBase64 = async (blob) => {
    const buf = new Uint8Array(await blob.arrayBuffer());
    let bin = ''; for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
    return btoa(bin);
  };
  /* Фото для Telegram: JPEG до 600 КБ уходит как есть; остальное — уменьшаем до 1280 px и в JPEG.
     На Windows обычный canvas.toBlob иногда не отвечает вовсе — поэтому сначала OffscreenCanvas, и на всё — таймаут. */
  async function вJpeg(blob) {
    if (/jpe?g/i.test(blob.type || '') && blob.size > 0 && blob.size < 600000) return вBase64(blob);
    const bmp = await сТаймаутом(createImageBitmap(blob), 8000, 'картинка не открылась');
    const k = Math.min(1, 1280 / Math.max(bmp.width, bmp.height));
    const w = Math.max(1, Math.round(bmp.width * k)), hh = Math.max(1, Math.round(bmp.height * k));
    let out = null;
    if (typeof OffscreenCanvas !== 'undefined') {
      try {
        const oc = new OffscreenCanvas(w, hh);
        oc.getContext('2d').drawImage(bmp, 0, 0, w, hh);
        out = await сТаймаутом(oc.convertToBlob({ type: 'image/jpeg', quality: 0.8 }), 8000, 'сжатие не ответило');
      } catch (_e) { out = null; }
    }
    if (!out) {
      const cv = document.createElement('canvas');
      cv.width = w; cv.height = hh;
      cv.getContext('2d').drawImage(bmp, 0, 0, w, hh);
      out = await сТаймаутом(new Promise((res) => cv.toBlob(res, 'image/jpeg', 0.8)), 8000, 'сжатие не ответило');
    }
    if (!out) throw new Error('сжатие не удалось');
    return вBase64(out);
  }
  // любая ошибка — видна в панели, кнопка не залипает на «Отправляем…»
  async function sendApproval() {
    const my = S;
    if (!my || TG_BUSY.has(my.id)) return;
    TG_BUSY.add(my.id);
    try { await sendApproval0(); }
    catch (e) {
      if (S === my && S.tg) { S.tg = { ...S.tg, sending: false, error: 'Не отправилось: ' + (устарело(e) ? УСТАРЕЛО : String((e && e.message) || e).slice(0, 200)) }; render2keep(); }
    } finally { TG_BUSY.delete(my.id); }
  }
  // ссылка на сообщение согласования в Telegram (супергруппа «-100…»): https://t.me/c/<id>/<msg> — в заметку диалога LeadChat
  const ссылкаTG = (chat, msg) => { const m = String(chat || '').match(/^-100(\d+)$/); return m && msg ? 'https://t.me/c/' + m[1] + '/' + msg : ''; };
  async function заметкаСогласования(conv, chat, msg) {
    const url = ссылкаTG(chat, msg);
    if (!url || !conv) return false;
    // id от сообщения Telegram: повтор (сеть, 429) не даст второй заметки — LeadChat вернёт ту же
    const id = ('lcz-tg-' + chat + '-' + msg).slice(0, 64);
    // 409 idempotency_mismatch — заметка с этим id уже есть: записана раньше
    try { await LC.post('/conversations/' + encodeURIComponent(conv) + '/notes', { text: url, client_message_id: id }); return true; } catch (e) { return ужеЗаписано(e); }
  }
  /* ЗАЩИТА ОТ ПЕРЕКРЫТИЯ: перед сообщением в чат города смотрим его последние сообщения — если сотрудник
     филиала написал просьбу («1055805 перенос на 14:00») и ему ещё не ответили, своё поверх не пишем. */
  /* o.заранее — 2.1.3: проверка, начатая заранее (карточка действия открылась), годится минуту: к нажатию ответ уже есть.
     null — не проверено (программа Telegram не ответила): не мешает ни CRM, ни сообщению */
  const ЧАТ_ЗАРАНЕЕ = new Map();                                       // chat → { at, p }
  async function просьбыВЧате(chat, o) {
    if (!chat) return null;
    const з = ЧАТ_ЗАРАНЕЕ.get(String(chat));
    if (o && o.заранее && з && Date.now() - з.at < 60e3) return з.p;
    const p = сТаймаутом(send({ kind: 'lcz-tg', args: { action: 'recent', chat, n: 30, since: Math.floor(Date.now() / 1000) - 1800 } }), 25000, 'нет ответа')
      .catch(() => null).then((r) => (!r || !r.ok || !Array.isArray(r.messages) ? null : LC_TG.просьбыФилиала(r.messages, { now: Date.now() / 1000 })));
    ЧАТ_ЗАРАНЕЕ.set(String(chat), { at: Date.now(), p });
    p.then((g) => { if (g === null && ЧАТ_ЗАРАНЕЕ.get(String(chat)) && ЧАТ_ЗАРАНЕЕ.get(String(chat)).p === p) ЧАТ_ЗАРАНЕЕ.delete(String(chat)); });
    return p;
  }
  /* 2.1.3: отправка в чат города с проверкой — ОДНИМ заданием программы Telegram (сама смотрит чат и сразу отправляет; ждёт просьба
     филиала — не отправляет и отдаёт её). Старая программа (old_agent) — как раньше: проверка, потом отправка. Возврат — как у send,
     плюс guard: [...] (не отправлено, ждёт просьба) */
  const ПРОГРАММА = { старая: 0, умеет: null, умеетAt: 0 };
  /* мозг и сервер команды умеют guard (status.guard_ok)? Пока нет (не выложены) — guard ушёл бы обычной отправкой БЕЗ проверки чата,
     поэтому без подтверждения — только по-старому. Ответ помним 10 мин (да) / 2 мин (нет, сбой) */
  async function умеетСПроверкой() {
    if (ПРОГРАММА.умеет !== null && Date.now() - ПРОГРАММА.умеетAt < (ПРОГРАММА.умеет ? 10 : 2) * 60e3) return ПРОГРАММА.умеет;
    let r = null;
    try { r = await сТаймаутом(send({ kind: 'lcz-tg', args: { action: 'status' } }), 8000, 'нет ответа'); } catch (_e) { r = null; }
    ПРОГРАММА.умеет = !!(r && r.guard_ok === true); ПРОГРАММА.умеетAt = Date.now();
    return ПРОГРАММА.умеет;
  }
  // o.строго — действия: чат не проверить (старая программа не ответила на проверку) — не отправляем: { ok: false, неПроверен: true }
  async function отправитьСПроверкой(args, o) {
    if (Date.now() - ПРОГРАММА.старая > 30 * 60e3 && (await умеетСПроверкой())) {
      const r = await send({ kind: 'lcz-tg', args: { action: 'send', ...args, guard: true, n: 30, since: Math.floor(Date.now() / 1000) - 1800 } });
      if (!(r && r.old_agent)) return r && Array.isArray(r.guard) && r.guard.length ? { ok: false, guard: r.guard } : r;
      ПРОГРАММА.старая = Date.now();                                  // полчаса не спрашиваем: обновят программу — заработает само
    }
    const g = await просьбыВЧате(args.chat);
    if (g && g.length) return { ok: false, guard: g };
    if (g == null && o && o.строго) return { ok: false, неПроверен: true, error: 'не смог проверить чат на просьбы филиала (программа Telegram не ответила)' };
    return send({ kind: 'lcz-tg', args: { action: 'send', ...args } });
  }
  // ответом на конкретное сообщение — не перекрывает (это и есть ответ); force — оператор видел просьбу и всё равно пишет
  async function вЧатГорода(args, o) {
    if (!(o && o.force) && !args.reply_to) {
      const r = await отправитьСПроверкой(args);
      if (r && r.guard) return { ok: false, guard: { list: r.guard, title: (o && o.title) || '' }, error: 'ждёт ответа просьба филиала — ' + LC_TG.просьбаКратко(r.guard[r.guard.length - 1]) };
      return r;
    }
    return send({ kind: 'lcz-tg', args: { action: 'send', ...args } });
  }
  function перекрытиеBox(g, onRecheck, onForce, всёРавно) {
    // 1.20: действия — программа Telegram не ответила на проверку чата: тоже ничего не делали, выбор за оператором
    if (g && g.nocheck) return h('div', { class: 'box warn' }, svg('warn'), h('div', { class: 'c', style: 'width:100%' },
      h('div', {}, h('b', {}, 'Не смог проверить «' + (g.title || 'чат города') + '» на просьбы филиала'), ' (программа Telegram не на связи). Ничего не делали.'),
      h('div', { class: 'row', style: 'gap:6px;flex-wrap:wrap;margin-top:4px' },
        h('button', { class: 'sm pri', onclick: onRecheck }, 'Проверить снова'),
        h('button', { class: 'sm', onclick: onForce }, 'Сделать без проверки'))));
    return h('div', { class: 'box warn' }, svg('warn'), h('div', { class: 'c', style: 'width:100%' },
      h('div', {}, h('b', {}, 'В «' + (g.title || 'чате города') + '» ждёт ответа просьба филиала'), ' — ваше сообщение её перекроет:'),
      ...g.list.slice(-3).map((m) => h('div', { class: 'n' }, LC_TG.просьбаКратко(m))),
      h('div', { class: 'n mut' }, 'Ответьте филиалу в Telegram (ответом на его сообщение), затем «Проверить снова». Пока ничего не делали.'),
      h('div', { class: 'row', style: 'gap:6px;flex-wrap:wrap;margin-top:4px' },
        h('button', { class: 'sm pri', onclick: onRecheck }, 'Проверить снова'),
        h('button', { class: 'sm', onclick: onForce }, всёРавно || 'Всё равно отправить'))));
  }
  // сообщение после создания заявки не ушло из-за просьбы филиала — окно: проверить и отправить / всё равно отправить
  function тостОтложено(args, g) {
    const d = h('div', { class: 'tst-d warn' }, 'Не отправил «' + String(args.text).slice(0, 80) + '», чтобы не перекрыть:');
    const отправить = async (b, force) => {
      const кнопки = [...el.querySelectorAll('.tst-a button')];
      if (кнопки.some((x) => x.disabled)) return;                    // уже проверяем / отправляем
      кнопки.forEach((x) => { x.disabled = true; });
      const было = b.textContent; b.textContent = force ? 'Отправляем…' : 'Проверяем…';
      const r = await вЧатГорода(args, { title: g.title, force });
      if (r && r.ok) { d.className = 'tst-d ok'; d.textContent = '✓ Отправлено: ' + String(args.text).slice(0, 80); const a = el.querySelector('.tst-a'); if (a) a.remove(); setTimeout(() => el.remove(), 15000); return; }
      кнопки.forEach((x) => { x.disabled = false; }); b.textContent = было;
      d.textContent = r && r.guard ? 'Просьба филиала всё ещё без ответа — ответьте ей в Telegram:' : 'Не отправилось: ' + ((r && r.error) || 'ошибка');
    };
    const el = тост({ kind: 'warn', label: 'Просьба филиала ждёт ответа', title: g.title ? '«' + g.title + '»' : 'Чат города',
      lines: [d, ...g.list.slice(-3).map((m) => h('div', { class: 'tst-q' }, LC_TG.просьбаКратко(m)))],
      actions: [h('button', { class: 'sm pri', onclick: (e) => отправить(e.currentTarget, false) }, 'Проверить и отправить'),
        h('button', { class: 'sm', onclick: (e) => отправить(e.currentTarget, true) }, 'Всё равно отправить'),
        h('button', { class: 'sm', onclick: () => el.remove() }, 'Не отправлять')] });
    return el;
  }
  async function sendApproval0() {
    if (S && S.tg && S.tg.sending) return;                          // уже отправляем — второе нажатие не шлёт ещё раз
    keepEdits();
    const locationIssue=LC_WORKFLOW.territoryIssue(S.terr,S.lead,{beforeApproval:true,clientLocation:S.check?.facts?.client_location});
    if(locationIssue){S.tg={...S.tg,error:locationIssue};render2keep();return;}
    const ta = panel.querySelector('[data-tg="text"]');
    const text = ta ? ta.value.trim() : '';
    keepTg();
    // 2.1.6: куда — выбранные оператором по порядку (состояние окна; отметки в окне — его отражение)
    const выбраны = [...new Set((Array.isArray(S.tg.picked) ? S.tg.picked : [...panel.querySelectorAll('[data-tg="pick"]:checked')].map((x) => x.value))
      .filter((id) => (S.tg.chats || {})[id]))];
    if (!выбраны.length || !text) { S.tg = { ...S.tg, error: !выбраны.length ? 'Не выбран чат: отметьте чат или найдите его поиском' : 'Пустой текст согласования' }; render2keep(); return; }
    // регламент: согласовывать одновременно с несколькими филиалами нельзя (штраф 500 ₽) — первый, при отказе следующий;
    // «Во все отмеченные» — явный выбор оператора (второе нажатие кнопки)
    const всем = !!S.tg.всем && выбраны.length > 1;
    const chats = всем ? выбраны : выбраны.slice(0, 1);
    const запас = всем ? [] : [...new Set(выбраны.slice(1).concat(((S.tg && S.tg.matched && S.tg.matched.options) || []).filter((x) => x !== выбраны[0])))];
    keepEdits();
    const my = S;
    S.tg = { ...S.tg, guard: null, text, chat: chats[0], sending: true, stage: '' };
    render2keep();
    const этап = (t) => { if (S === my && S.tg) { S.tg.stage = t; const b = panel.querySelector('[data-tg="go"]'); if (b) b.textContent = t; } };
    S.tg.picked = выбраны;
    const sent = [], errs = [], warns = [], неясно = [];
    const photos = [];
    const выбрано = my.tg.noPhotos ? [] : (my.tg.photos || []).filter((x) => x.on).slice(0, 4);
    // просьбы филиала в чате и фото — параллельно (фото только сжимаем; отправка — ниже, по этому же нажатию)
    // «Всё равно отправить» действует только на тот чат, где оператор видел просьбу
    const можно = my.tg.force || [];                                // чаты, где оператор видел просьбу и нажал «Всё равно отправить»
    const проверить = chats.some((c) => !можно.includes(c));
    этап(проверить ? 'Проверяем чат города' + (выбрано.length ? ' и готовим фото…' : '…') : 'Готовим фото…');
    // во все отмеченные — каждый чат проверяем на просьбы филиала (параллельно)
    const [gs, сжатые] = await Promise.all([Promise.all(chats.map((c) => (можно.includes(c) ? null : просьбыВЧате(c)))),
      Promise.all(выбрано.map((x) => сТаймаутом(вJpeg(x.blob), 15000, 'не успело').then((b64) => ({ name: x.name, b64 }), (e) => ({ name: x.name, e }))))]);
    if (S !== my) return;
    const гi = gs.findIndex((g) => g && g.length);
    if (гi >= 0) { S.tg = { ...S.tg, sending: false, stage: '', chat: chats[гi], guard: { list: gs[гi], title: ((my.tg.chats || {})[chats[гi]] || {}).title || '' } }; render2keep(); return; }
    S.tg.force = null;
    for (const x of сжатые) {
      if (x.e) warns.push('фото «' + x.name + '» не ушло (' + String((x.e && x.e.message) || x.e).slice(0, 40) + ')');
      else photos.push({ name: x.name, b64: x.b64 });
    }
    for (const chat of chats) {
      const title = ((my.tg.chats || {})[chat] || {}).title || '';
      этап('Отправляем в «' + (title || 'чат') + '»' + (photos.length ? ' с фото' : '') + '…');
      const r = await сТаймаутом(send({ kind: 'lcz-tg', args: { action: 'send', chat, text, conv: my.id, photos } }), 90000, 'нет ответа 90 секунд')
        .catch((e) => ({ ok: false, unknown: true, error: String(e.message || e) }));
      // ответа нет (срок, связь, «не ответил вовремя» — фон пометил unknown): могло уйти — не «не отправилось», а «не знаю»
      if (r && r.ok) sent.push({ chat, title, msg: r.message_id });
      else if (!r || r.unknown) неясно.push('«' + title + '»');
      else errs.push('«' + title + '»: ' + ((r && (r.error || r.description)) || 'не отправилось'));
    }
    const незнаю = неясно.length ? 'Не знаю, ушло ли в ' + неясно.join(', ') + ' (нет ответа от Telegram) — посмотрите чат, прежде чем отправлять ещё раз' : '';
    if (!sent.length) { my.tg = { ...my.tg, sending: false, stage: '', error: [незнаю, ...(errs.length ? ['Не отправилось: ' + errs.join('; ')] : []), ...warns].filter(Boolean).join(' · '), withPhotos: photos.length > 0 }; if (S === my) render2keep(); return; }
    const rec = { chats: sent, at: Date.now(), name: my.lead.name || '', city: (my.prep && my.prep.cityText) || my.lead.city || '', replies: {}, seen: 0,
      text, queue: запас.map((id) => ({ chat: id, title: ((my.tg.chats || {})[id] || {}).title || '' })) };
    await tgSentSet(my.id, rec);
    const заметка = await заметкаСогласования(my.id, sent[0].chat, sent[0].msg);
    const итог = (незнаю ? [незнаю] : []).concat(errs.length ? ['Не отправилось: ' + errs.join('; ')] : []).concat(warns.length ? ['Отправлено без части фото: ' + warns.join('; ')] : [])
      .concat(выбраны.length > 1 && !всем ? ['Отправлено только в «' + (sent[0] && sent[0].title) + '»: сразу в несколько филиалов нельзя (регламент). Если откажут — кнопка «Отказали → в …»'] : []);
    my.tgSent = { ...rec, note: заметка }; my.tg = итог.length ? { error: итог.join(' · ') } : null; my.tgReplies = [];
    if (S !== my) return;
    render2keep();
    pollReplies();
  }
  async function следующемуФилиалу(btn) {
    const my = S, rec = my && my.tgSent;
    if (!rec || !(rec.queue || []).length || TG_BUSY.has(my.id)) return;
    if (rec.nextUnknown) return;
    TG_BUSY.add(my.id);
    try {
    const next = rec.queue[0];
    const force = btn.dataset.force === String(next.chat);
    btn.disabled = true; btn.textContent = force ? 'Отправляем в «' + next.title + '»…' : 'Проверяем «' + next.title + '»…';
    const r = await вЧатГорода({ chat: next.chat, text: rec.text || '', conv: my.id }, { title: next.title, force }).catch(() => ({ unknown: true }));
    if (r && r.guard) { btn.disabled = false; btn.dataset.force = String(next.chat); btn.title = r.guard.list.map(LC_TG.просьбаКратко).join('\n'); btn.textContent = 'В «' + next.title + '» ждёт ответа просьба филиала — ответьте ей; нажать ещё раз = отправить всё равно'; return; }
    if (!r || r.unknown) { rec.nextUnknown = next.chat; await tgSentSet(my.id, rec); if (S === my) render2keep(); return; }
    if (!r || !r.ok) { btn.disabled = false; btn.textContent = !r || r.unknown ? 'Не знаю, ушло ли в «' + next.title + '» — посмотрите чат, прежде чем нажимать ещё раз' : 'Не ушло: ' + ((r && r.error) || 'ошибка').slice(0, 60); return; }
    rec.chats = sent2(rec.chats, { chat: next.chat, title: next.title, msg: r.message_id }); rec.queue = rec.queue.slice(1);
    // Подтверждение сохраняем исходному диалогу, даже если оператор уже открыл другой.
    await tgSentSet(my.id, rec);
    await заметкаСогласования(my.id, next.chat, r.message_id);
    if (S !== my || my.tgSent !== rec) return;
    render2keep(); pollReplies();
    } catch (e) {
      btn.disabled = false; btn.textContent = 'Проверьте результат в Telegram';
      btn.title = String(e.message || e);
    } finally { TG_BUSY.delete(my.id); }
  }
  const sent2 = (list, x) => (list || []).concat([x]);
  // итог согласования — ответом на условия филиала (или на своё согласование, если ответа нет)
  async function итогСогласования(btn, текст) {
    const my = S, rec = my && my.tgSent;
    if (!rec || TG_BUSY.has(my.id)) return;
    TG_BUSY.add(my.id);
    try {
    btn.disabled = true; btn.textContent = 'Отписываем…';
    const res = [];
    rec.outcomes = rec.outcomes || {};
    rec.outcomeUnknown = rec.outcomeUnknown || {};
    for (const x of sentList(rec)) {
      const key = x.chat + ':' + x.msg;
      if (rec.outcomes[key] === текст) { res.push(true); continue; }
      if (rec.outcomeUnknown[key]) { res.push(false); continue; }
      let на = x.msg;
      try { const rr = await send({ kind: 'lcz-tg', args: { action: 'replies', chat: x.chat, msg: x.msg } }); const п = ((rr && rr.replies) || []).filter((y) => y.id).pop(); if (п) на = п.id; } catch (_e) { /* ответов нет */ }
      const r = await send({ kind: 'lcz-tg', args: { action: 'send', chat: x.chat, reply_to: на, text: текст, conv: my.id } }).catch(() => ({ unknown: true }));
      res.push(r && r.ok);
      if (r && r.ok) { rec.outcomes[key] = текст; await tgSentSet(my.id, rec); }
      else if (!r || r.unknown) { rec.outcomeUnknown[key] = true; await tgSentSet(my.id, rec); }
    }
    // Частичный результат не выдаём за завершённый: повтор пропустит уже подтверждённые чаты.
    if (res.length && res.every(Boolean)) { rec.done = текст; delete rec.outcomeError; }
    else { delete rec.done; rec.outcomeError = 'Итог отправлен не во все чаты — проверьте Telegram'; }
    await tgSentSet(my.id, rec);
    if (S !== my || my.tgSent !== rec) return;
    render2keep();
    } catch (e) {
      btn.disabled = false; btn.textContent = 'Проверьте результат в Telegram'; btn.title = String(e.message || e);
    } finally { TG_BUSY.delete(my.id); }
  }
  // ответы филиалов по всем чатам, куда ушло согласование
  async function repliesFor(rec) {
    const out = [];
    for (const x of sentList(rec)) {
      const r = await send({ kind: 'lcz-tg', args: { action: 'replies', chat: x.chat, msg: x.msg } });
      if (r && r.ok) for (const y of r.replies || []) out.push({ ...y, chat: x.chat, approvalMsg: x.msg, chatTitle: x.title });
    }
    return out.sort((p, q) => p.at - q.at);
  }
  async function pollReplies() {
    if (!S || !S.tgSent || !panel.classList.contains('open')) return;
    const my = S, rec = S.tgSent, before = JSON.stringify(S.tgReplies || []);
    const rep = await repliesFor(rec);
    if (S !== my || S.tgSent !== rec) return;
    S.tgReplies = rep;
    if (JSON.stringify(rep) !== before && формаЭтого()) render2keep();
  }
  function approvalBox() {
    const c = S.check || {};
    const hm = (t) => new Date(t).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
    if (S.tgSent) {
      const rep = S.tgReplies || [];
      const куда = sentList(S.tgSent).map((x) => '«' + x.title + '»').join(', ');
      return h('div', { class: 'box ' + (rep.length ? 'ok' : 'warn') }, svg(rep.length ? 'check' : 'warn'), h('div', { class: 'c' },
        h('div', {}, 'Отправлено на согласование в ' + куда + ' в ' + hm(S.tgSent.at)),
        S.tgSent.note ? h('div', { class: 'n mut' }, 'Ссылка на сообщение — в заметке диалога') : '',
        S.tg && S.tg.error ? h('div', { class: 'n warn' }, S.tg.error) : '',
        rep.length ? rep.map((x) => h('div', {}, h('b', {}, (sentList(S.tgSent).length > 1 ? x.chatTitle + ' — ' : '') + 'ответ' + (x.from ? ' (' + x.from + ')' : '') + ' ' + hm(x.at * 1000) + ': '), x.text))
          : h('div', { class: 'n mut' }, 'Ждём ответ филиала — он появится здесь (ответ на ваше сообщение в чате).'),
        S.tgSent.done ? h('div', { class: 'n ok' }, 'Итог отписан: ' + S.tgSent.done) : '',
        S.tgSent.outcomeError ? h('div', { class: 'n warn' }, S.tgSent.outcomeError) : '',
        S.tgSent.nextUnknown || Object.keys(S.tgSent.outcomeUnknown || {}).length ? h('div', { class: 'n warn' }, 'Результат отправки неизвестен. Проверьте сообщение в Telegram; повторная отправка остановлена.') : '',
        h('div', { class: 'row', style: 'gap:6px;margin-top:4px;flex-wrap:wrap' },
          (S.tgSent.queue || []).length ? h('button', { class: 'sm', disabled: !!S.tgSent.nextUnknown, title: 'Филиал отказал — то же согласование следующему филиалу', onclick: (e) => следующемуФилиалу(e.currentTarget) }, 'Отказали → в «' + (S.tgSent.queue[0].title || 'следующий') + '»') : '',
          !S.tgSent.done ? h('button', { class: 'sm', title: 'Итог согласования — обязательно по регламенту. Почему: без итога — штраф 300 ₽', onclick: (e) => итогСогласования(e.currentTarget, 'клиент отказался от условий выезда') }, 'Клиент отказался от условий') : '',
          // стирает отметку об отправленном согласовании — только вторым нажатием в течение 3 с
          h('button', { class: 'sm', onclick: async (e) => {
            const b = e.currentTarget;
            if (!(Date.now() - (+b.dataset.at || 0) < 3000)) { b.dataset.at = String(Date.now()); b.textContent = 'Нажмите ещё раз, чтобы стереть отметку';
              setTimeout(() => { if (b.isConnected && Date.now() - (+b.dataset.at || 0) >= 3000) b.textContent = 'Согласовать заново'; }, 3100); return; }
            S.tgSent = null; S.tgReplies = []; await tgSentSet(S.id, null); openApproval();
          } }, 'Согласовать заново'))));
    }
    const t = S.tg;
    if (t && (t.chats || t.error)) {
      /* 2.1.6: куда — выбранные чаты по порядку (первый — куда уйдёт), подходящие чаты города, этот город в других направлениях
         (МНЧ / КП / БТ одним нажатием) и поиск по всем группам — без листания длинного списка */
      const подх = (t.matched && t.matched.options) || [];
      const ДИР_ИМЯ = { mnc: 'МНЧ', kp: 'КП', bt: 'БТ' };
      const есть = (id) => !!(t.chats || {})[id];
      const picked = (Array.isArray(t.picked) ? t.picked : подх.slice(0, 1)).filter(есть);
      const другие = Object.keys(ДИР_ИМЯ).filter((d) => d !== S.dir).flatMap((d) => { const m = t.city ? LC_TG.matchChat(t.chats || {}, d, t.city) : null;
        return m ? (m.options || [m.id]).filter(есть).map((id) => ({ id, d })) : []; }).filter((x) => !подх.includes(x.id));
      const имя = (id) => ((t.chats || {})[id] || {}).title || id;
      const строка = (id, tag, cls, изПоиска) => h('label', { class: 'opt' + (cls ? ' ' + cls : '') }, h('input', { type: 'checkbox', 'data-tg': 'pick', value: id, checked: picked.includes(id), onchange: (e) => отметитьЧат(id, e.target.checked, изПоиска) }),
        h('span', { class: 'nm' }, имя(id)), h('span', { class: 'tag mut' }, tag));
      const всего = Object.keys(t.chats || {}).length;
      const найдено = h('div', { class: 'tg-found', 'data-tg': 'found' });
      const показатьНайденное = (q) => {
        const все = найтиЧаты(t.chats, q), r = все.filter(([id]) => !picked.includes(id));
        найдено.replaceChildren(r.length ? h('div', { class: 'opts' }, ...r.slice(0, 12).map(([id, c]) => строка(id, (LC_TG.базыЧата ? LC_TG.базыЧата(String(c.title).toLowerCase()) : []).map((d) => ДИР_ИМЯ[d]).join('/') || 'чат', '', true))) : '',
          r.length > 12 ? h('div', { class: 'n mut' }, 'ещё ' + (r.length - 12) + ' — уточните поиск') : String(q || '').trim() && !все.length ? h('div', { class: 'n mut' }, 'Ничего не нашлось — другое слово (город, «мнч», «бт», «кп»)')
            : String(q || '').trim() && !r.length ? h('div', { class: 'n mut' }, 'Найденное уже отмечено') : '');
      };
      показатьНайденное(t.q || '');
      return h('div', { class: 'box warn' }, svg('warn'), h('div', { class: 'c', style: 'width:100%' },
        h('div', {}, h('b', {}, 'Согласование в чат города')),
        t.error ? h('div', { class: 'n warn' }, t.error) : '',
        t.guard && !t.sending ? перекрытиеBox(t.guard, () => { keepTg(); S.tg.guard = null; sendApproval(); }, () => { keepTg(); S.tg.force = [...(S.tg.force || []), t.chat]; S.tg.guard = null; sendApproval(); }) : '',
        picked.length ? h('div', { class: 'opts', 'data-tg': 'picked' }, ...picked.map((id, i) => строка(id, picked.length > 1 ? (i === 0 ? 'уйдёт первым' : 'при отказе — ' + (i + 1) + '-м') : 'уйдёт сюда', 'on'))) : '',
        подх.filter((id) => !picked.includes(id)).length ? h('div', { class: 'opts' }, ...подх.filter((id) => !picked.includes(id)).map((id) => строка(id, подх.indexOf(id) === 0 ? 'чат города' : 'тоже подходит'))) : '',
        другие.filter((x) => !picked.includes(x.id)).length ? h('div', { class: 'n mut' }, 'Этот город в других направлениях') : '',
        другие.filter((x) => !picked.includes(x.id)).length ? h('div', { class: 'opts', 'data-tg': 'other-dirs' }, ...другие.filter((x) => !picked.includes(x.id)).map((x) => строка(x.id, ДИР_ИМЯ[x.d]))) : '',
        t.offline ? '' : всего ? h('input', { type: 'search', 'data-tg': 'q', value: t.q || '', placeholder: 'Найти чат: «сочи», «бт сочи»…', title: 'Поиск по ' + всего + ' группам Telegram: город, направление (мнч, бт, кп)', autocomplete: 'off',
          oninput: (e) => { S.tg.q = e.target.value; показатьНайденное(e.target.value); } }) : h('div', { class: 'n warn' }, 'Список групп Telegram пуст — компьютер с Telegram не на связи?'),
        найдено,
        !picked.length && всего ? h('div', { class: 'n warn' }, t.matched ? 'Отметьте чат, куда отправить' : 'Чат города не нашёлся — найдите его поиском') :
          t.matched && t.matched.several && t.авто ? h('div', { class: 'n warn' }, 'Подходит несколько чатов — отметьте нужный') : '',
        picked.length > 1 ? h('div', { class: 'n mut' }, 'По регламенту — один филиал за раз: уйдёт в «' + имя(picked[0]) + '», остальные — по очереди, если откажут.') : '',
        h('textarea', { 'data-tg': 'text', value: t.text || '', style: 'min-height:120px;text-transform:none;letter-spacing:0;font-weight:400;color:var(--t1)' }),
        (t.photos || []).length ? h('div', { style: 'display:flex;flex-wrap:wrap;gap:6px' }, ...t.photos.map((ph) => h('label', { title: ph.name, style: 'position:relative;cursor:pointer' },
          h('img', { src: ph.src, alt: ph.name, style: 'width:64px;height:64px;object-fit:cover;border-radius:6px;border:2px solid ' + (ph.on ? 'var(--acc)' : 'var(--line)') + ';opacity:' + (ph.on ? 1 : 0.5) }),
          h('input', { type: 'checkbox', checked: ph.on, style: 'position:absolute;left:4px;top:4px', onchange: (e) => { ph.on = e.target.checked; keepTg(); render2keep(); } })))) : '',
        (t.photos || []).length ? h('div', { class: 'n mut' }, 'Отмеченные фото уйдут в Telegram вместе с текстом (в CRM фото не попадают)') : '',
        // 2.1.7: групп нет (аварийный режим) — скопировать текст и проверить группы снова
        t.offline ? h('div', { class: 'tg-acts wide' },
          h('button', { class: 'sm pri', 'data-tg': 'copy', onclick: async (e) => {
            const b = e.currentTarget, ta = panel.querySelector('[data-tg="text"]'), v = ta ? ta.value : '';
            try { await navigator.clipboard.writeText(v); b.textContent = 'Скопировано ✓ — вставьте в чат города'; }
            catch (_e) { if (ta) { ta.focus(); ta.select(); } b.textContent = 'Выделено — нажмите Ctrl+C'; } } }, 'Скопировать текст'),
          h('button', { class: 'sm', onclick: () => { keepTg(); openApproval(); } }, 'Проверить группы снова'),
          h('button', { class: 'sm', onclick: () => { S.tg = null; render2keep(); } }, 'Отмена')) :
        // кнопки ровной сеткой: «Отправить» во всю ширину, когда под ним ещё две
        h('div', { class: 'tg-acts' + (!t.sending && picked.length > 1 ? ' wide' : '') },
          h('button', { class: 'sm pri', 'data-tg': 'go', disabled: !!t.sending, onclick: () => { S.tg.всем = false; sendApproval(); } }, t.sending ? (t.stage || 'Отправляем…') : 'Отправить в чат города'),
          // 2.1.6: сразу во все отмеченные — только явно (регламент: одновременно с несколькими филиалами нельзя, штраф 500 ₽)
          !t.sending && picked.length > 1 ? h('button', { class: 'sm', 'data-tg': 'go-all', title: 'Сразу во все отмеченные чаты. По регламенту согласовывать одновременно с несколькими филиалами нельзя — штраф 500 ₽',
            onclick: (e) => { const b = e.currentTarget; if (!(Date.now() - (+b.dataset.at || 0) < 4000)) { b.dataset.at = String(Date.now()); b.textContent = 'Точно? Штраф 500 ₽';
                setTimeout(() => { if (b.isConnected && Date.now() - (+b.dataset.at || 0) >= 4000) b.textContent = 'Во все (' + picked.length + ')'; }, 4100); return; }
              keepTg(); S.tg.всем = true; sendApproval(); } }, 'Во все (' + picked.length + ')') : '',
          !t.sending && t.error && t.withPhotos ? h('button', { class: 'sm', title: 'Отправить только текст', onclick: () => { S.tg.noPhotos = true; sendApproval(); } }, 'Отправить без фото') : '',
          h('button', { class: 'sm', onclick: () => { S.tg = null; render2keep(); } }, 'Отмена'))));
    }
    const причина = c.approval || terrReason() || repeatReason();
    // ИИ не нашёл, но клиент описывает неисправность, а ремонт этой техники — по согласованию: решает оператор
    if (!причина && c.maybe) return h('div', { class: 'box warn' }, svg('warn'), h('div', { class: 'c' },
      h('div', {}, h('b', {}, 'Проверьте, нужно ли согласование: '), (c.maybeWhy || 'клиент описывает неисправность, а ремонт этой техники — по согласованию') + '.'),
      h('div', { class: 'n mut' }, 'По согласованию: «' + c.maybe + '»'),
      h('div', { class: 'row', style: 'gap:6px;margin-top:4px;flex-wrap:wrap' },
        h('button', { class: 'sm pri', disabled: !!(t && t.busy), onclick: () => { S.check = { ...S.check, approval: c.maybe, maybe: '' }; openApproval(); } }, t && t.busy ? 'Открываем чаты…' : 'Отправить в чат города'),
        h('button', { class: 'sm', title: 'Это настройка, а не ремонт — согласование не нужно', onclick: () => { S.check = { ...S.check, maybe: '' }; render2keep(); } }, 'Не нужно, это настройка'))));
    if (!причина) return h('div', { class: 'row', style: 'gap:6px' },
      h('button', { class: 'sm', disabled: !!(t && t.busy), onclick: openApproval }, t && t.busy ? 'Открываем чаты…' : 'Всё равно спросить'));
    return h('div', { class: 'box warn' }, svg('warn'), h('div', { class: 'c' },
      h('div', {}, h('b', {}, 'Нужно согласование с филиалом: '), причина),
      h('div', { class: 'row', style: 'gap:6px;margin-top:4px' },
        h('button', { class: 'sm pri', disabled: !!(t && t.busy), onclick: openApproval }, t && t.busy ? 'Открываем чаты…' : 'Отправить в чат города'))));
  }


  /* ---------- ссылка для отзыва: список источников → ссылка канала из LeadChat → Авито (страница продавца → clck.ru) ---------- */
  /* 12.10: у канала LeadChat своя ссылка для отзыва (account.review_url — её оператор и так отправляет клиенту). Источника нет в списке —
     сначала она: без Авито (он режет такие запросы) и без clck.ru. MAX — ссылка канала диалога Авито этого клиента (каналИсточника),
     не канала MAX. Пусто — как раньше, со страницы продавца на Авито. Список источников по-прежнему первый (withSource) */
  const КАК_КАНАЛ = 'ссылка канала из LeadChat';
  const ссылкаКанала = (conv) => { const u = String((conv && каналИсточника(conv).review_url) || '').trim(); return /^https?:\/\/\S+$/i.test(u) ? u : ''; };
  // ставит ссылку канала в заявку my (как удачная ссылка с Авито: src_url и строка 🟢…🟢 в комментарии); false — у канала её нет
  function ссылкаИзКанала(my) {
    const url = my && my.conv ? ссылкаКанала(my.conv) : '';
    if (!url) return false;
    const inForm = S === my && формаЭтого();
    if (inForm) keepEdits();
    my.autoLink = { ok: true, short: url, how: КАК_КАНАЛ, канал: true };
    // оператор за это время выбрал источник из списка — его ссылку не трогаем
    if (!LC_LINKS.find(my.lead.partner_note, my.dir, my.lead.partner)) {
      my.lead.src_url = url;
      my.lead.comment = linkLines(my.lead.comment, { url }, LC_LINKS.isWhite(my.lead.partner, null));
    }
    if (inForm) render();
    return true;
  }
  // o.показать — открыть объявление видимой вкладкой (Авито спросил «не робот?»), o.ручная — ссылку вставил оператор
  async function getReviewLink(fresh, o = {}) {
    const my = S;
    // у канала LeadChat есть своя ссылка — она, без Авито (вставленная оператором — как раньше: это его выбор)
    if (!o.ручная && ссылкаИзКанала(my)) return;
    // MAX без диалога Авито этого клиента: объявления нет — сама ссылка не делается, только вставленная оператором. Запоминается она
    // под самой ссылкой: не за каналом MAX (один бот на всех клиентов) и не в общей памяти команды
    const безАвито = maxБезАвито(S.conv);
    if (безАвито && !o.ручная) return;
    S.autoLink = { busy: true, показать: !!o.показать };
    if (формаЭтого()) render2keep();
    const it = объявлениеДиалога(S.conv), acc = каналИсточника(S.conv);   // MAX — объявление и канал диалога Авито этого клиента
    const r = await send({ kind: 'lcz-reviewlink', args: { itemUrl: безАвито ? o.ручная : it.url || '', accountId: безАвито ? '' : acc.id || '',
      origin: S.lead.partner_note || '', dir: S.dir || '', fresh: !!fresh, показать: !!o.показать, ручная: o.ручная || '' } });
    if (S !== my) return;
    S.autoLink = r || { ok: false, error: 'нет ответа' };
    const inForm = формаЭтого();
    if (inForm) keepEdits();
    // оператор за это время выбрал источник из списка — его ссылку не трогаем
    if (r && r.ok && r.short && !LC_LINKS.find(S.lead.partner_note, S.dir, S.lead.partner)) {
      S.lead.src_url = r.short;
      S.lead.comment = linkLines(S.lead.comment, { url: r.short }, LC_LINKS.isWhite(S.lead.partner, null));
    }
    if (inForm) render();
  }

  /* ---------- адрес: два ИИ + карта ---------- */
  const setCheck = (field, ok, note) => {
    S.checks = S.checks.filter((c) => c.field !== field).concat([{ field, ok, note }]);
  };
  // целиком — адрес другого диалога или карточки: нас. пункт этого диалога к чужой улице не подмешиваем
  function applyAddr(a, how, warn, целиком) {
    keepEdits();
    S.lead.addr = { ...S.lead.addr, street: a.street || '', building: a.house || a.building || '', office: a.flat || a.office || '',
      entrance: a.entrance || '', floor: a.floor || '', settlement: a.settlement || (целиком ? '' : S.lead.addr.settlement) || '' };
    S.lead.address = [S.lead.addr.settlement, S.lead.addr.street, S.lead.addr.building].filter(Boolean).join(', ');
    S.lead.addr_warn = warn || '';
    setCheck('address', true, how);
    адресВФорму();
  }
  /* Адрес сменили кодом («подставить», карта, LeadChat), а форма на экране ждёт prepare() (полоска, без перерисовки):
     поля адреса в форме — сразу новые. Иначе ответ фона в это время (регламент, дубли, ссылка → render2keep → keepEdits)
     прочитал бы из формы прежний адрес и молча вернул его в заявку, а территорию посчитали бы уже по новому. */
  function адресВФорму(поля) {
    if (!формаЭтого()) return;
    const a = S.lead.addr || {};
    for (const k of поля || ['street', 'building', 'office', 'entrance', 'floor', 'settlement']) {
      const el = panel.querySelector('[data-f="' + k + '"]');
      if (el) el.value = a[k] || '';
    }
  }
  const osmWarn = (r) => (r.osm && r.osm.status === 'exact' ? '' : 'адрес из переписки, карты и реестр дом не подтвердили');
  // другой ли адрес: улица (без «ул.»), номер дома, нас. пункт
  const другойАдрес = (cur, b) => {
    const у = (x) => String(x || '').toLowerCase().replace(/ё/g, 'е').replace(/(^|\s)(ул|улица|пр|проспект|пер|переулок|тер|территория|снт)\.?(?=\s|$)/g, ' ').replace(/[^а-яa-z0-9]/g, '');
    const д = (x) => String(x || '').toLowerCase().replace(/^(д|дом)\.?\s*/, '').replace(/\s+(г|гор|город)\.?$/, '').replace(/\s+/g, '');
    cur = cur || {}; b = b || {};
    return у(cur.street) !== у(b.street) || д(cur.building) !== д(b.house || b.building) || (!!b.settlement && !LC_TERRITORY.тотЖеНП(cur.settlement || '', b.settlement));
  };
  const osmNote = (r) => 'нашли ' + r.by.join(' и ') + (r.agree ? ' (совпали)' : '') + (r.osm ? ' · ' + r.osm.text : '');
  async function findAddr() {
    const my = S, conv = S.id;
    const исходный = { ...(S.lead.addr || {}) };                      // адрес, с которым начали искать
    S.addrAI = { busy: true };
    if (формаЭтого()) render();
    const r = await send({ kind: 'lcz-address', ctx: my.ctx });
    if (S !== my || S.id !== conv) return;
    S.addrAI = r;
    // пока ИИ искали, оператор вписал адрес сам (или поправил дом, кв…) — его не затираем: ответ ИИ только предлагаем кнопкой.
    // Сами подставляем, лишь пока на экране форма этого диалога (или она ещё собирается) и заявка по нему не создаётся:
    // на итоге создания, ходе, «Готовых» ответ только запоминаем («Подставить в заявку» — в форме)
    if (формаЭтого()) keepEdits();
    const правил = ['street', 'building', 'office', 'entrance', 'floor'].some((k) => String(исходный[k] || '').trim() !== String((S.lead.addr || {})[k] || '').trim());
    const можно = (формаЭтого() || (собираю && convIdNow() === conv)) && !задачаИдёт(conv) && !правил;
    if (r && r.ok && r.best) {
      const cur = S.lead.addr || {};
      // поля пустые — подставляем сами; адрес уже есть — предлагаем кнопкой
      if (!cur.street || !cur.building) { if (можно) applyAddr(r.best, osmNote(r), osmWarn(r)); }
      else if (r.osm && r.osm.status === 'exact' && (cur.street || '').toLowerCase().includes(String(r.best.street).toLowerCase().replace(/^(ул|улица)\.?\s+/, '').slice(0, 4))
        && String(cur.building).replace(/\D/g, '') === String(r.best.house).replace(/\D/g, '')) {
        S.lead.addr_warn = '';                                         // тот же адрес — карта его подтвердила
        setCheck('address', true, osmNote(r));
      } else if (можно && формаЭтого() && r.osm && r.osm.status === 'exact' && S.terr && !S.terr.ok && S.terr.mismatch !== undefined && другойАдрес(cur, r.best)) {
        // (только «дома нет на карте»: карта не ответила или сбой сети — это не повод менять адрес карточки)
        // адрес из карточки карта не нашла, а этот дом есть на карте — берём его и проверяем территорию заново
        applyAddr(r.best, osmNote(r), ''); S.terr = null; S.addrFix = true;
        prepare(); return;
      }
    }
    if (формаЭтого()) render();
  }
  /* АДРЕС → КАРТОЧКА LEADCHAT. Правильный путь — «принять распознанный адрес» этого диалога (resolve, decision 'replace'):
     LeadChat кладёт его своей цепочкой «разбор → карта», точка и проверка — его. PUT адреса — только по явной кнопке «как есть»:
     такой адрес LeadChat не разбирает, картой не проверяет и автоматикой больше не трогает (lc/app/api/routes/clients.py) —
     ждать от него проверки бесполезно, поэтому и не ждём. Каждый запрос — с пределом по времени. */
  async function writeAddrToLeadChat(a, line, how) {
    const cid = S.conv && S.conv.client && S.conv.client.id;
    if (!cid) { alertBox('В LeadChat нет карточки клиента'); return; }
    if (S.addrAI && S.addrAI.writing) return;                            // уже пишем — второй раз не отправляем
    keepEdits();
    const my = S, r0 = S.addrAI || {}, base = '/clients/' + encodeURIComponent(cid);
    S.addrAI = { ...r0, writing: true, lc: '' };
    render();
    const итог = (lc, ok) => { S.addrAI = { ...S.addrAI, writing: false, saved: true, lc, lcOk: !!ok }; };
    // адрес из ответа LeadChat — в заявку (и точка дома для территории); сменился — территорию заново
    const взять = (f, lc) => {
      const есть = !!(f.addr && (f.addr.street || f.addr.settlement) && f.addr.building);
      const сменился = есть && другойАдрес(S.lead.addr, { ...f.addr, house: f.addr.building });
      if (есть) {
        applyAddr({ ...a, ...f.addr, house: f.addr.building, flat: f.addr.office || a.flat }, 'записан в LeadChat · ' + f.geoNote, f.geoOk ? '' : f.geoNote);
        S.lead.geo_pt = f.pt ? { ...f.pt, street: S.lead.addr.street, building: S.lead.addr.building, settlement: S.lead.addr.settlement } : null;
      }
      итог(lc + (f.geoNote ? ' · ' + f.geoNote : ''), f.geoOk);
      return сменился;
    };
    try {
      // карточка заново (один запрос, до 8 с): решение по адресу могла уже принять автоматика (пишет через ~90 с тишины).
      // Тот же адрес уже в карточке — не перезаписываем (PUT «как есть» заморозил бы проверенный автоадрес);
      // LeadChat успел распознать этот адрес в диалоге — принимаем его (resolve), а не пишем «как есть»
      const idn = await сТаймаутом(LC.get(base + '/identity'), 8000, 'LeadChat не ответил за 8 с');
      if (S !== my) return;
      S.ctx = { ...S.ctx, identity: idn };
      const уже = LC_EXTRACT.карточкаСАдресом(idn, a);
      const c = уже ? null : (idn.address_candidates || []).find((x) => x && x.id === (how && how.id) && (!x.status || x.status === 'pending')) || LC_EXTRACT.кандидатАдреса(idn, S.id, a);
      if (уже) { if (взять(LC_EXTRACT.fromIdentity(idn, S.id), 'в карточке LeadChat уже этот адрес')) { S.terr = null; prepare(); return; } }
      else if (!c && how && how.asIs) {
        await сТаймаутом(LC.put(base + '/address', { address: line, conversation_id: S.id }), 10000, 'LeadChat не ответил за 10 с');
        if (S !== my) return;
        const сменился = другойАдрес(S.lead.addr, a);
        if (сменился) applyAddr(a, osmNote(r0), osmWarn(r0));
        итог('записан в карточку LeadChat как есть — LeadChat его картой не проверяет и сам больше не меняет', false);
        if (сменился) { S.terr = null; prepare(); return; }
      } else {
        if (!c) throw new Error('распознанного адреса этого диалога в LeadChat уже нет — откройте карточку клиента');
        const body = how && how.variant != null ? { decision: 'replace', variant: how.variant } : { decision: 'replace' };
        let res, f;
        try {
          res = await сТаймаутом(LC.post(base + '/address-candidates/' + encodeURIComponent(c.id) + '/resolve', body), 10000, 'LeadChat не ответил за 10 с');
          f = LC_EXTRACT.fromIdentity({ address: res && res.address, address_source: 'dialog', address_geo: res && res.candidate && res.candidate.geo,
            address_evidence: res && res.candidate ? { parts: res.candidate.parts, conversation_id: res.candidate.conversation_id, locality: res.candidate.locality } : null }, S.id);
        } catch (e) {
          // 409 «решение уже принято» — запрос дошёл раньше (ответ потерялся) или успела автоматика: смотрим карточку, не шлём второй раз
          if (!(e && e.status === 409) && !/409/.test(String((e && e.message) || e))) throw e;
          const idn2 = await сТаймаутом(LC.get(base + '/identity'), 8000, 'LeadChat не ответил за 8 с');
          if (!LC_EXTRACT.карточкаСАдресом(idn2, a)) throw new Error('по этому адресу в LeadChat уже принято другое решение');
          f = LC_EXTRACT.fromIdentity(idn2, S.id);
        }
        if (S !== my) return;
        if (взять(f, 'LeadChat принял адрес')) { S.terr = null; prepare(); return; }
      }
    } catch (e) {
      if (S === my) { S.addrAI = { ...S.addrAI, writing: false, saved: false, lc: 'не записалось в LeadChat: ' + ((e && e.message) || e), lcOk: false }; render2keep(); }
      return;
    } finally {
      if (my.addrAI && my.addrAI.writing) my.addrAI = { ...my.addrAI, writing: false };   // ушли в другой диалог — кнопка не «зависает»
    }
    if (S === my) render();
  }
  // кнопки «в карточку LeadChat»: принять распознанный LeadChat адрес этого диалога (или вариант карты), иначе — «как есть», явно
  function кнопкиLeadChat(r, line) {
    if (r.writing) return [h('button', { class: 'sm', disabled: true }, 'Записываем в LeadChat…')];
    if (r.saved) return [];                                             // уже записано — второй раз не предлагаем
    const idn = S.ctx && S.ctx.identity;
    if (LC_EXTRACT.карточкаСАдресом(idn, r.best)) return [h('span', { class: 'n ok', style: 'align-self:center' }, '✓ в карточке LeadChat уже этот адрес')];
    const c = LC_EXTRACT.кандидатАдреса(idn, S.id, r.best);
    const варианты = c && c.geo && Array.isArray(c.geo.variants) ? c.geo.variants.map((v, i) => [v, i]).filter(([v]) => v && v.formatted).slice(0, 4) : [];
    if (c && варианты.length) return варианты.map(([v, i]) => h('button', { class: 'sm', title: 'LeadChat примет адрес этого диалога с выбранным домом карты',
      onclick: () => writeAddrToLeadChat(r.best, line, { id: c.id, variant: i }) }, 'В LeadChat: ' + v.formatted));
    if (c) return [h('button', { class: 'sm', title: 'LeadChat примет распознанный им адрес этого диалога — проверка картой и точка дома останутся за LeadChat',
      onclick: () => writeAddrToLeadChat(r.best, line, { id: c.id }) }, 'Принять адрес в LeadChat')];
    return [h('button', { class: 'sm', title: 'Адрес в карточке клиента LeadChat заменится на этот. Записанный руками адрес LeadChat картой не проверяет и сам больше не меняет',
      onclick: () => writeAddrToLeadChat(r.best, line, { asIs: true }) }, 'Записать как есть (LeadChat больше не будет проверять и заменять адрес)')];
  }
  function addrBox() {
    const r = S.addrAI;
    if (!r) return '';
    if (r.busy) return h('div', { class: 'n mut', title: 'YandexGPT, GigaChat и правила; Яндекс.Карты и ФИАС' }, 'Ищем адрес в переписке и проверяем по карте…');
    if (!r.ok) return h('div', { class: 'n warn' }, 'Поиск адреса ИИ: ' + (r.error || 'не получилось'));
    // адрес первым написал оператор (мастерская, пункт приёма) — не адрес клиента; подставить можно только явно
    if (!r.best && r.echo) return h('div', { class: 'box warn' }, svg('warn'), h('div', { class: 'c' },
      h('div', {}, h('b', {}, 'Адрес от оператора: '), r.echo.line || LC_ADDRESS_LINE(r.echo)),
      h('div', { class: 'n mut' }, 'Его первым написал оператор («' + r.echo.quote + '»), клиент только повторил — это не адрес клиента.'),
      h('div', { class: 'row', style: 'gap:6px;margin-top:4px' }, h('button', { class: 'sm', onclick: () => {
        applyAddr(r.echo, 'адрес от оператора — подставлен вручную', 'адрес первым написал оператор — проверьте, что это адрес клиента'); S.terr = null; prepare(); } }, 'Это адрес клиента — подставить'))));
    if (!r.best) return h('div', { class: 'n warn' }, 'Адрес в переписке не найден' + (r.notes && r.notes.length ? ' (' + r.notes.join('; ') + ')' : ''));
    const line = r.line || LC_ADDRESS_LINE(r.best);
    const ok = r.osm && r.osm.status === 'exact';
    const уЗаявкиЭтот = !другойАдрес(S.lead.addr, r.best);
    const kids = [
      h('div', {}, 'Адрес из переписки: ', h('b', {}, line)),
      h('div', { class: 'n ' + (r.agree ? 'ok' : 'mut') }, r.agree ? r.by.join(' и ') + ' — одно и то же' : 'нашёл ' + r.by.join(', ') + ', другие не согласились'),
      r.notes && r.notes.length ? h('div', { class: 'n mut' }, r.notes.join('; ')) : '',
      r.osm ? h('div', { class: 'n ' + (ok ? 'ok' : 'warn') }, (ok ? 'Дом найден: ' + r.osm.confirmed.join(', ') : r.osm.text) + ' ',
        ok && r.osm.map ? h('a', { href: r.osm.map, target: '_blank', rel: 'noopener' }, 'на карте') : '') : '',
      r.osm && r.osm.fixedStreet ? h('div', { class: 'n mut' }, 'Опечатку в улице исправил Яндекс: ' + r.osm.fixedStreet) : '',
      r.alt ? h('div', { class: 'n mut' }, 'Другой вариант (' + r.altBy + '): ' + LC_ADDRESS_LINE(r.alt) + ' ',
        h('button', { class: 'sm', onclick: () => { applyAddr(r.alt, 'вариант ' + r.altBy, 'адрес под вопросом: ИИ разошлись'); S.terr = null; prepare(); } }, 'Подставить')) : '',
      r.lc ? h('div', { class: 'n ' + (r.lcOk ? 'ok' : 'warn') }, r.lc) : '',
      уЗаявкиЭтот ? h('div', { class: 'n ok' }, '✓ этот адрес уже в заявке') : '',
      h('div', { class: 'row', style: 'gap:6px;flex-wrap:wrap;margin-top:4px' },
        уЗаявкиЭтот ? '' : h('button', { class: 'sm' + (ok ? ' pri' : ''), title: 'Подставить этот адрес в заявку', onclick: () => { applyAddr(r.best, osmNote(r), osmWarn(r)); S.terr = null; prepare(); } }, 'Подставить'),
        ...кнопкиLeadChat(r, line)),
    ];
    return h('div', { class: 'box ' + (ok ? 'ok' : 'warn') }, svg(ok ? 'check' : 'warn'), h('div', { class: 'c' }, ...kids));
  }
  const LC_ADDRESS_LINE = (a) => [a.street, a.house, a.settlement || a.city, a.flat ? 'кв ' + a.flat : ''].filter(Boolean).join(', ');

  let prepSeq = 0;
  async function prepare(extra) {
    дублиLC().catch(() => {});                // тот же клиент в другом диалоге LeadChat — параллельно, панель не ждёт
    if (S) S.подтв = {};                     // 2.3: форма CRM заново (база, город, номер) — подтверждения кнопкой («вторая заявка» и т. п.) спросим заново
    if (!S.dir) { S.prep = null; render(); return; }
    const inForm = формаЭтого();
    if (inForm) {                            // форма уже на экране — не мигаем, полоска сверху и кнопка ждёт
      const go = panel.querySelector('.go');
      if (go) { go.disabled = true; go.textContent = 'Открываю форму CRM ' + dirName(S.dir) + '…'; }
      const ph = panel.querySelector('.ph');
      if (ph && !ph.querySelector('.bar')) ph.prepend(h('div', { class: 'bar' }));
    } else {
      steps(2, 'Форма CRM ' + dirName(S.dir) + ' и номер по базам');
    }
    // ответ учитываем только для последнего запроса: база могла смениться, пока CRM отвечала
    const my = ++prepSeq, dir = S.dir, conv = S.id;
    S.готовлю = my;                          // пока форма CRM этой базы не пришла, S.prep и списки формы — прежние: «Создать» (и Ctrl+Enter) ждёт
    // территория по карте направления: филиал, время приёма, согласование — и сразу нужный город в CRM
    // точка дома из карточки LeadChat (карта подтвердила дом) — территория без второго геокодирования, пока адрес тот же
    const точка = LC_EXTRACT.точкаАдреса(S.lead);
    const поКарте = !(extra && (extra.cityId || extra.city)) && S.lead.addr && (S.lead.addr.street || точка.pt);
    // номер только что искала проверка готовности (до 5 мин) — CRM не ищет его по базам второй раз
    const p10 = String(S.lead.phone || '').replace(/\D/g, '').slice(-10), k = S.known;
    const known = !extra && k && k.phone10 === p10 && Date.now() - (k.at || 0) < РАЗБОР_СВЕЖ ? { phone10: k.phone10, found: k.found, unchecked: k.unchecked } : null;
    const подготовить = (city) => send({ kind: 'lcz-crm', op: 'prepare', args: {
      dir, phone: S.lead.phone, city, cityFallback: S.lead.city, topics: S.lead.topics, partner: S.lead.partner,
      problem: S.lead.problem, client: S.lead.client_words, device: S.lead.device || '',
      repeat_hint: S.lead.repeat_hint, ...(known ? { known } : {}), ...(extra || {}) } });
    // готовое из проверки готовности (collect) — один раз и только при первом открытии; карта не ответила тогда — спросим её сейчас
    const готово = !extra && S.изРазбора && (S.изРазбора.terr ? !S.изРазбора.terr.timeout : !поКарте) ? S.изРазбора : null;
    S.изРазбора = null;
    let r;
    if (готово) { S.terr = готово.terr; S.terrCity = S.lead.city; r = готово.prep; }
    else if (поКарте) {
      // город так, как он записан в CRM: «Ачинск (Красноярск)» — спутник, расстояние от основного филиала
      const crmCity = await городCRM(dir, S.lead.city);
      S.terrCity = crmCity || S.lead.city;
      // территория по карте и форма CRM — параллельно; филиал по карте другой — форму готовим ещё раз под него (ниже)
      [S.terr, r] = await Promise.all([территория({ dir, city: S.terrCity, settlement: S.lead.addr.settlement,
        street: S.lead.addr.street, building: S.lead.addr.building, partner: S.lead.partner, tech: техника(S.lead), ...точка }), подготовить(S.lead.city)]);
      if (my !== prepSeq || !S || S.dir !== dir || S.id !== conv) return;
    } else r = await подготовить(S.lead.city);
    if (поКарте) {
      const ai = S.addrAI;
      // (только когда дома нет на карте — mismatch; карта не ответила или сбой сети — второй запрос ничего не даст)
      if (S.terr && !S.terr.ok && S.terr.mismatch !== undefined && !S.addrFix && ai && ai.ok && ai.best && ai.osm && ai.osm.status === 'exact' && другойАдрес(S.lead.addr, ai.best)) {
        S.addrFix = true;                                              // адрес карточки не нашёлся, а дом из переписки карта подтвердила
        applyAddr(ai.best, osmNote(ai), '');
        S.terr = await территория({ dir, city: S.lead.city, settlement: S.lead.addr.settlement,
          street: S.lead.addr.street, building: S.lead.addr.building, partner: S.lead.partner, tech: техника(S.lead) });
        if (my !== prepSeq || !S || S.dir !== dir || S.id !== conv) return;
      }
      // карта не нашла дом из карточки, а адрес в переписке ещё не искали — ищем (найдётся подтверждённый — подставится сам)
      if (S.terr && !S.terr.ok && S.terr.mismatch !== undefined && !S.addrAI && S.ctx) findAddr();
      // местное название нас. пункта («рудник») → официальное («посёлок Мазульский») — сразу в форму
      if (S.terr && S.terr.ok && S.terr.settlementFixed) { S.lead.addr = { ...S.lead.addr, settlement: S.terr.settlementFixed }; адресВФорму(['settlement']); }
      const sp = S.terr && S.terr.ok && (S.terr.special || []).find((x) => !/электрик/i.test(x.note));
      const ветка = S.terr && S.terr.ok ? (sp && sp.branch) || S.terr.branch : '';
      // филиал по карте («Мытищи (МСК)») — другой город CRM: форму под него (как проверка готовности)
      if (ветка && безСкобокГород(ветка) !== безСкобокГород(r && r.ok && r.cityText) && безСкобокГород(ветка) !== безСкобокГород(S.lead.city)) {
        r = await подготовить(ветка);
        if (my !== prepSeq || !S || S.dir !== dir || S.id !== conv) return;
      }
    }
    if (my !== prepSeq || !S || S.dir !== dir || S.id !== conv) return;
    S.prep = r;
    поясПоГородуCRM(r);                     // MAX без пояса: город CRM известен — часы клиента и время визита по его поясу
    if (S.готовлю === my) S.готовлю = 0;
    if (r && r.ok && (r.cities || []).length) запомнитьГородаCRM(dir, r.cities);
    const видРабот = r && r.ok ? ((r.appl || []).find((o) => o.id === r.applId) || {}).text || '' : '';
    // в CRM город оказался спутником («Ачинск (Красноярск)»), а территорию считали без этого — пересчитываем
    if (r && r.ok && /\(/.test(r.cityText || '') && S.terrCity !== r.cityText && S.lead.addr && (S.lead.addr.street || LC_EXTRACT.точкаАдреса(S.lead).pt) && !(extra && extra.cityId)) {
      S.terrCity = r.cityText;
      const t2 = await территория({ dir, city: r.cityText, settlement: S.lead.addr.settlement,
        street: S.lead.addr.street, building: S.lead.addr.building, partner: S.lead.partner, tech: техника(S.lead, видРабот), ...LC_EXTRACT.точкаАдреса(S.lead) });
      if (my !== prepSeq || !S || S.dir !== dir || S.id !== conv) return;
      if (t2 && !t2.timeout) S.terr = t2;                              // не ответила — остаётся прежний расчёт
    }
    // вид работ «ЖК ТВ» / «Телевизоры» стал известен только из CRM: у ТВ нет приёма до 36 км без согласования
    // (оператор сменил вид работ на не ТВ — возвращаем расчёт как был)
    if (r && r.ok && S.terr && S.terr.ok) S.terr = LC_TERRITORY.сТВ(S.terr.безТВ || S.terr, видРабот);
    // особые филиалы по виду работ (электрика в Хабаровске → «Хабаровск электрика») — когда вид работ уже выбран
    if (r && r.ok && r.applId && !(extra && extra.cityId) && S.specialFor !== conv + dir) {
      const applText = ((r.appl || []).find((o) => o.id === r.applId) || {}).text || '';
      const sp = LC_TERRITORY.особые(dir, r.cityText || S.lead.city, applText, S.lead.partner).find((x) => x.appl);
      if (sp && !/электрик/i.test(r.cityText || '')) {
        S.specialFor = conv + dir;
        S.terr = { ...(S.terr || { ok: true, why: [] }), special: [{ branch: sp.branch, note: sp.note, chats: sp.chats.map((x) => x.source) }] };
        return prepare({ city: sp.branch, applId: r.applId });
      }
    }
    // 2.0.7: направление по смыслу — один раз на диалог, пока оператор сам базу не выбирал. Работа не этой базы (по виду работ
    // CRM этого города: «Бытовая Техника» в МНЧ — значит, филиала БТ в городе нет и МНЧ её берёт) — форма в нужной базе.
    // В нужной базе города нет — возвращаемся. КП (регламент: чужую технику сперва согласует свой филиал) — только подсказка
    if (r && r.ok && !S.dirChosen && !(extra && (extra.cityId || extra.applId)) && typeof LC_WORK !== 'undefined') {
      if (S.dirAuto && S.dirAuto.to === dir && !r.cityId && !S.dirAuto.назад) {
        S.dirAuto = { ...S.dirAuto, назад: true };
        S.dir = S.dirAuto.from; S.lead = withSource(S.lead, S.conv, S.dir);
        return prepare();
      }
      if (!S.dirAuto && !S.dirAutoChecked && r.cityId) {
        S.dirAutoChecked = true;                                       // один раз на диалог: дальше база — как есть (адрес, город, вид работ её не трогают)
        let рек = LC_WORK.направление(S.lead, dir, r.appl);
        // белая заявка (723 / «Белый …») в БТ не создаётся — в БТ её не переводим, только подсказка
        if (рек && !рек.совет && рек.dir === 'bt' && белаяНаБТ(withSource(S.lead, S.conv, 'bt'), 'bt')) рек = { ...рек, совет: true, белая: true };
        S.dirHint = рек && рек.совет ? { ...рек, from: dir } : null;
        if (рек && !рек.совет) {
          S.dirAuto = { from: dir, to: рек.dir, why: рек.why, работа: рек.работа };
          S.dir = рек.dir; S.lead = withSource(S.lead, S.conv, рек.dir);
          return prepare();
        }
      }
    }
    // 13.10: территория и город CRM известны — своё время визита (ближайшее по регламенту, оператор не правил) — по их зоне
    пересчитатьБлижайшее();
    render();
    runChecklist();
    загрузитьЗакреп();
    группыЗаранее();
    адресLCНаФорме();
  }
  function выбратьЗакреп(value) {
    if (!['', 'none', 'by', 'not'].includes(value)) return;
    keepEdits();
    S.zkChoice = value;
    S.zkChoiceKey = (S.zakrep && S.zakrep.key) || '';
    S.lead.is_zakrep = value === 'by';
    S.zkAsked = 0;
    if (value !== 'by') применитьЗакреп(S.lead);
    render();
  }
  function применитьЗакреп(lead) {
    const text = S.zakrep && S.zakrep.text;
    lead.is_zakrep = !!(S.zkChoice === 'by' && text);
    if (lead.is_zakrep) {
      const line = 'Закреп: ' + text;
      if (!String(lead.service_comment || '').split('\n').includes(line)) lead.service_comment = [lead.service_comment, line].filter(Boolean).join('\n');
    } else if (text && lead.service_comment) {
      lead.service_comment = String(lead.service_comment).split('\n').filter((line) => line !== 'Закреп: ' + text).join('\n');
    }
  }
  function закрепФорма() {
    if (!(S.zakrep && S.zakrep.text)) return '';
    return h('div', { class: 'cz-notes', 'data-zakrep-choice': '1' },
      h('div', { class: 'n' }, 'Закреп города: ' + S.zakrep.text),
      h('div', { class: 'fz-seg', role: 'group', 'aria-label': 'Закреп города' },
        ...[['none', 'Без закрепа'], ['by', 'По закрепу'], ['not', 'Не по закрепу']].map(([value, label]) => h('button', {
          type: 'button', class: (S.zkChoice || 'none') === value ? 'on' : '', 'aria-pressed': (S.zkChoice || 'none') === value ? 'true' : 'false',
          title: value === 'none' ? 'Без галочки, текста закрепа и отписки «Не по закрепу»' : value === 'by' ? 'Галочка «Закреп» и текст закрепа в служебном комментарии' : 'Без галочки; после создания — отписка «Не по закрепу» в город',
          onclick: () => выбратьЗакреп(value) }, label))));
  }
  // закреп города на дату визита (условия филиала под шкалой времени CRM)
  async function загрузитьЗакреп() {
    const my = S, P = S && S.prep;
    if (!P || !P.ok || !P.cityId) return;
    const key = [S.dir, P.cityId, S.lead.visit_date || ''].join('|');
    if (S.zakrep && S.zakrep.key === key) return;
    const r = await send({ kind: 'lcz-crm', op: 'zakrep', args: { dir: S.dir, cityId: P.cityId, date: S.lead.visit_date || '', time: S.lead.visit_time || '' } });
    if (S !== my || [S.dir, S.prep && S.prep.cityId, S.lead.visit_date || ''].join('|') !== key) return;
    if ((S.zakrep && S.zakrep.key !== key) || (S.zkChoice && (S.zkChoiceKey || (S.zakrep && S.zakrep.key)) !== key)) { S.zkChoice = ''; S.lead.is_zakrep = false; S.zkAsked = 0; }
    S.zkChoiceKey = key;
    S.zakrep = { key, text: (r && r.ok && r.text) || '' };
    if (S.zakrep.text && формаЭтого()) render2keep();
  }
  // согласование нужно по адресу (карта / черта города) — в дополнение к регламенту
  /* история клиента по регламенту (отказ / отмены / гарантия) — см. repeat.js */
  const кодБезНомера = (s) => (LC_TG.кодИсточника(s || '') || '').replace(/\.\d$/, '');
  // P — подготовленная форма CRM (prepare: прошлые заявки клиента в found), keep — выбор оператора (вид услуг, тип).
  // 2.1.3: и переписка (msgs) — к какому мастеру обращается клиент и гарантия ли это по его словам; ИИ — подсказкой (repeat_hint)
  const прочтения = new WeakMap();                                    // переписка → { ключ истории → прочтение }: панель зовёт историю много раз
  function историяПо(P, dir, lead, keep, msgs) {
    if (!P || !P.ok || !dir || typeof LC_REPEAT === 'undefined') return null;
    keep = keep || {};
    const applText = ((P.appl || []).find((o) => o.id === P.applId) || {}).text || '';
    const subId = keep.subId && (P.sub || []).some((o) => o.id === keep.subId) ? keep.subId : P.subId;
    const subText = ((P.sub || []).find((o) => o.id === subId) || {}).text || '';
    const prev = (P.found || []).map((r) => ({ ...r, src: кодБезНомера(r.src) || '' }));
    let dialog;
    if (Array.isArray(msgs) && LC_REPEAT.кКомуОбращается) {
      const свои = prev.filter((r) => r.dir === dir), ключ = свои.map((r) => [r.id, r.master, r.appl, r.sub, r.status].join('/')).join('|') + '#' + ((lead && lead.name) || '');
      const м = прочтения.get(msgs) || new Map();
      if (!м.has(ключ)) м.set(ключ, LC_REPEAT.кКомуОбращается(msgs, { masters: свои.map((r) => r.master), prev: свои.filter((r) => /готов|выполн|оплач/i.test(r.status || '')), client: lead && lead.name }));
      прочтения.set(msgs, м); dialog = м.get(ключ);
    }
    return LC_REPEAT.оценить(prev, { dir, appl: applText, sub: subText, partner: String((lead && lead.partner) || ''),
      src: кодБезНомера(lead && lead.partner_note), wantType: keep.type || '', ai: (lead && lead.repeat_hint) || '', ...(dialog ? { dialog } : {}) });
  }
  function историяКлиента() {
    if (!S || !S.prep || !S.prep.ok) return null;
    return историяПо(S.prep, S.dir, S.lead, S.keepSel || {}, S.ctx && S.ctx.messages);
  }
  // тип заявки в форме: выбор оператора → по истории клиента → по CRM (как в разделе «Работа»)
  function типЗаявки() {
    const P = S && S.prep && S.prep.ok ? S.prep : null;
    if (!P) return '';
    const R = историяКлиента();
    return (S.keepSel && S.keepSel.type) || (R && R.type) || P.type || 'Впервые';
  }
  function repeatReason() { const R = историяКлиента(); return R && R.approval ? R.approval : ''; }
  function terrReason() {
    const t = S.terr;
    return t && t.ok && t.approval ? 'адрес — ' + (t.why || []).filter((x) => /соглас|черт|границ/.test(x)).map((x) => x.replace(/\s*—\s*по согласованию$/, '').replace(/^зона «по согласованию» на карте$/, 'зона «по согласованию» на карте')).join('; ') : '';
  }
  function terrBox() {
    const t = S.terr;
    if (!t) return '';
    // карта нашла такую улицу в другом месте — не делаем выводов, предлагаем подставить нас. пункт
    const ai = S.addrAI && S.addrAI.ok && S.addrAI.best && S.addrAI.osm && S.addrAI.osm.status === 'exact' && другойАдрес(S.lead.addr, S.addrAI.best) ? S.addrAI : null;
    if (!t.ok && t.mismatch && ai) return h('div', { class: 'box warn' }, svg('warn'), h('div', { class: 'c' },
      h('div', {}, h('b', {}, 'Адрес из карточки LeadChat на карте не нашёлся'), ' (' + [S.lead.addr.street, S.lead.addr.building].filter(Boolean).join(', ') + ').'),
      h('div', { class: 'n ok' }, 'В переписке другой адрес, и его дом на карте есть: ' + LC_ADDRESS_LINE(ai.best)),
      h('div', { class: 'row', style: 'gap:6px;margin-top:4px' }, h('button', { class: 'sm pri', onclick: () => { applyAddr(ai.best, osmNote(ai), ''); S.terr = null; prepare(); } }, 'Подставить его и проверить территорию'))));
    if (!t.ok && t.mismatch) return h('div', { class: 'box warn' }, svg('warn'), h('div', { class: 'c' },
      h('div', {}, h('b', {}, 'Дом не найден на карте. '), (t.candidates || []).length ? 'Скорее всего, клиент живёт в посёлке рядом — уточните или выберите:' : 'Уточните у клиента нас. пункт.'),
      h('div', { class: 'n mut' }, t.error),
      (t.candidates || []).length ? h('div', { class: 'opts' }, ...t.candidates.map((c) => h('button', { class: 'opt', title: c.text || c.locality, onclick: async () => {
        keepEdits();
        const было = (S.lead.addr && S.lead.addr.settlement) || '';
        // местное слово клиента («рудник») → официальное название: запоминаем для этого города — у себя и для всей команды
        if (было && !LC_TERRITORY.тотЖеНП(было, c.locality))
          send({ kind: 'lcz-name-learn', args: { city: (S.prep && S.prep.cityText) || S.lead.city, word: было, official: c.locality } });
        S.lead.addr = { ...S.lead.addr, settlement: c.locality }; адресВФорму(['settlement']); S.terr = null; await prepare(); } },
        h('span', { class: 'nm' }, c.locality), h('span', { class: 'tag ' + (c.house ? 'ok' : 'mut') }, c.house ? 'дом есть' : 'только улица'), svg('chev')))) : '',
      (t.candidates || []).length ? h('div', { class: 'n mut' }, 'Выбранный посёлок подставлю в адрес и запомню для этого города — для всей команды.') : ''));
    if (!t.ok) return h('div', { class: 'n ' + (t.timeout ? 'warn' : 'mut') }, 'Территория: ' + (t.error || 'не определилась'));
    const P = S.prep && S.prep.ok ? S.prep : null;
    const head = [t.branch ? 'филиал по карте: ' + t.branch : '', t.satelliteOf ? 'спутник ' + t.satelliteOf : '', t.hours ? 'принимаем за ' + t.hours + ' ч' : '',
      t.earliest && t.earliest !== '10:00' ? 'не раньше ' + t.earliest : ''].filter(Boolean).join(' · ');
    // часов нет (город или нас. пункт не определился) или карта не загрузилась — это «проверьте», а не зелёная «черта города»
    const warn = t.approval || t.far || !t.hours || t.noMap;
    const lines = [...(t.why || []), ...((t.special || []).map((x) => x.note))];
    if (P && t.branch && P.cityText && !new RegExp('^' + t.branch.split(/[\s(]/)[0].replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i').test(P.cityText) && !(t.special || []).length)
      lines.push('В CRM выбран город «' + P.cityText + '», а по карте адрес относится к «' + t.branch + '» — проверьте');
    const важное = lines.filter((x) => /соглас|проверьте|пропуск|электрик|СПБ|Екатеринбург/i.test(x) && !/«Дальний выезд»/.test(x));
    const подробно = [t.found ? 'На карте: ' + t.found : '', ...lines, t.mapTitle ? 'Карта: «' + t.mapTitle.trim() + '»' + (t.mapUpdated ? ', обновлена ' + new Date(t.mapUpdated * 1000).toLocaleDateString('ru-RU') : '') : ''].filter(Boolean).join('\n');
    // 2.1: территория — одной строкой; подробности (карта, дата обновления, все причины) — по «почему?», а не только во всплывающей подсказке
    const детали = подробно ? h('div', { class: 'fz-det', hidden: true, 'data-terr-det': '1' }, подробно) : '';
    return h('div', { class: 'fz-terr' + (warn ? ' warn' : ''), 'data-terr': '1', title: подробно }, svg(warn ? 'warn' : 'pin'), h('div', { class: 'c' },
      h('div', {}, h('b', {}, t.approval ? 'По согласованию' : 'Территория'), ': ' + (head || (t.inMap ? 'на карте' : 'не определилась — проверьте по карте'))),
      ...важное.map((x) => h('div', { class: 'n warn' }, x.replace(/ — по согласованию$/, ''))),
      t.far ? h('div', { class: 'n mut' }, '«Дальний выезд» отмечен в заявке') : '',
      детали),
      детали ? h('button', { type: 'button', class: 'fz-why', 'aria-expanded': 'false', title: 'Почему так: карта, правила, все причины', onclick: (e) => {
        детали.hidden = !детали.hidden; e.currentTarget.setAttribute('aria-expanded', String(!детали.hidden)); } }, 'почему?') : '');
  }
  /* время визита против правил приёма (регламент «Территориальные правила»): самая ранняя — 10:00 (спутник и «за 2+ ч» — 11:00),
     самая поздняя — 21:30, раньше и позже — по согласованию; сегодня — не раньше чем через час (в черте города), «за 2–2,5 ч» — через 2.
     Дату и время можно передать из полей формы: подсказка обновляется, пока оператор их правит */
  function terrTimeWarn(date, time) {
    // своё время («Прозвон» +4 ч по галочке оператора) тоже сверяем: «завтра 10:00» на город-спутник — раньше 11:00
    const t = S.terr && S.terr.ok ? S.terr : null, L = S.lead;
    const vt = String(time !== undefined ? time : L.visit_time || ''), vd = date !== undefined ? date : L.visit_date;
    const пусто = h('div', { 'data-terr-time': '1', style: 'display:none' });
    // визит в прошлом / без даты-времени и без «Прозвона» — строкой здесь же (обновляется, пока правят поля)
    const вп = визитПроблема({ ...L, visit_date: vd, visit_time: vt, ...(date !== undefined ? галочкиПрозвона() : {}) });
    const сВизитом = (el) => { if (!вп.block && !вп.warn) return el; el.removeAttribute('data-terr-time');
      return h('div', { 'data-terr-time': '1', style: 'display:flex;flex-direction:column;gap:4px' },
        h('div', { class: 'n ' + (вп.block ? 'bad' : 'warn'), 'data-visit-warn': вп.block ? 'block' : 'warn', 'data-window-miss': вп.окно ? '1' : null }, вп.block || вп.warn), el.style.display === 'none' ? '' : el); };
    if (!/^\d{2}:\d{2}/.test(vt)) return сВизитом(пусто);
    const мин = (x) => Number(String(x).slice(0, 2)) * 60 + Number(String(x).slice(3, 5));
    const out = [];
    const ранняя = (t && t.earliest) || '10:00';
    if (мин(vt) < мин(ранняя)) out.push(t ? 'по правилам территории — не раньше ' + ранняя + ', иначе по согласованию' : 'раньше 10:00 — только по согласованию с филиалом');
    if (мин(vt) > мин('21:30')) out.push('позже 21:30 — только по согласованию с филиалом');
    const часы = t ? parseFloat(String(t.hours || '').split('–')[0].replace(',', '.')) : NaN;
    const c = клиентСейчас(L);
    const today = !!(c && vd && c.iso && vd === c.iso);
    // ближайшее по регламенту (своё, не правленое) при создании пересчитается от «сейчас» — «слишком близко» на него не пишем
    const ближ = визитАвто({ ...L, visit_date: vd, visit_time: vt }) && L.visit_auto.kind === 'ближайшее';
    if (today && c.now && !ближ) {
      const до = мин(vt) - мин(c.now);
      // ближе минимума — при создании время само станет «сейчас + минимум» до минуты (неБлижеМинимума)
      if (часы >= 2 && до < часы * 60) out.push('сюда принимаем за ' + t.hours + ' ч — время визита слишком близко, при создании поставлю через ' + t.hours + ' ч от времени отправки');
      else if (!(часы >= 2) && до < 60) out.push('ставим не раньше чем через час от времени в городе — при создании поставлю ровно через час от времени отправки');
    }
    return сВизитом(out.length ? h('div', { class: 'n warn', 'data-terr-time': '1' }, out.join('; ')) : пусто);   // 2.1: одной строкой под полем, без второго «⚠»
  }
  /* регламент: сегодня — не раньше чем через час от времени в городе (территория «за 2–2,5 ч» — через 2). Пока шли разбор, проверки
     и очередь, минуты убегают: прямо перед отправкой в CRM время визита ближе минимума — ставим ровно «сейчас + минимум», вверх
     до минуты, как «Через час» в CRM. Иначе заявка уходит «за 59 минут». Не сегодня или без часового пояса — не трогаем */
  function минимумДоВизита(terr) {
    const ч = terr && terr.ok ? parseFloat(String(terr.hours || '').split('–')[0].replace(',', '.')) : NaN;
    return ч >= 2 ? Math.round(ч * 60) : 60;
  }
  const неБлижеМинимума = (lead, минДо, nowMs) => LC_EXTRACT.неБлижеМинимума(lead, минДо, nowMs);
  // клиент сам просит срочно — «Срочная» отмечена (в словах клиента, не оператора; «не срочно» — нет)
  const срочноПоСловам = (L) => { const t = String((L && L.client_words) || '').toLowerCase(); return /(срочно|прямо\s+сейчас|как\s+можно\s+(скорее|быстрее)|побыстрее)/.test(t) && !/не\s+(очень\s+)?срочно/.test(t); };
  /* 2.0.9: часы города у полей визита — живые (раз в 15 с), с днём недели: время визита ставят по городу клиента, а не по ПК.
     2.1: «Сейчас в Москве · пт 09.10» и время крупно (проект «2.1 — визит») */
  const ДН_КР = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];
  /* «в Москве», «в Мытищах», «в Нижнем Новгороде», «во Владимире» — по окончаниям; не знаем как — пусто (покажем «Сейчас · Город») */
  function вГороде(city) {
    const c = String(city || '').replace(/\s*\(.*?\)\s*/g, ' ').replace(/\s+-\s*$/, '').replace(/\s+/g, ' ').trim();
    if (!c || /\d/.test(c)) return '';
    const сущ = (w, одно) => {
      const l = w.toLowerCase();
      if (/^(сочи|тольятти)$/.test(l)) return w;
      if (/[оеёуюэ]$/.test(l)) return одно && /^[а-яё]+$/.test(l) ? w : null;   // Пушкино, Иваново — не склоняем
      if (/ия$/.test(l)) return w.slice(0, -1) + 'и';
      if (/[ая]$/.test(l)) return w.slice(0, -1) + 'е';
      if (/[бвмп]ль$/.test(l)) return w.slice(0, -1) + 'е';            // Ярославль → Ярославле
      if (/ь$/.test(l)) return w.slice(0, -1) + 'и';                     // Казань, Пермь, Тверь
      if (/й$/.test(l)) return w.slice(0, -1) + 'е';
      if (/ы$/.test(l)) return w.slice(0, -1) + 'ах';                    // Люберцы, Чебоксары
      if (/[кгхжшщч]и$/.test(l)) return w.slice(0, -1) + 'ах';           // Химки, Мытищи
      if (/и$/.test(l)) return null;
      return /[бвгджзклмнпрстфхцчшщ]$/.test(l) ? w + 'е' : null;          // Новосибирск, Королёв, Екатеринбург
    };
    const прил = (w) => {
      const l = w.toLowerCase();
      if (/ний$/.test(l)) return w.slice(0, -2) + 'ем';
      if (/(ий|ый|ой)$/.test(l)) return w.slice(0, -2) + 'ом';
      if (/яя$/.test(l)) return w.slice(0, -2) + 'ей';
      if (/ая$/.test(l)) return w.slice(0, -2) + 'ой';
      if (/ые$/.test(l)) return w.slice(0, -2) + 'ых';
      if (/ие$/.test(l)) return w.slice(0, -2) + 'их';
      return null;
    };
    let out;
    if (/-на-/i.test(c) && !/\s/.test(c)) { const [a, ...b] = c.split(/(?=-на-)/i); const x = сущ(a, true); out = x && x + b.join(''); }
    else {
      const сл = c.split(' ');
      const послед = сл.pop();
      const части = послед.split('-');
      const x = сущ(части.pop(), !сл.length);
      const перед = сл.map(прил);
      out = x && !перед.includes(null) ? [...перед, [...части, x].join('-')].join(' ') : null;
      // «Набережные Челны», «Великие Луки»: перед — прилагательные во мн. числе, последнее — во мн. числе
    }
    if (!out) return '';
    return (/^[вф][^аеёиоуыэюя]/i.test(out) ? 'во ' : 'в ') + out;
  }
  const городФормы = (L) => ((S && S.prep && S.prep.ok && S.prep.cityText) || (L && L.city) || '');
  // город для глаз: «Королёв (Мытищи)» → «Королёв»
  const городКратко = (x) => String(x || '').replace(/\s*\(.*?\)\s*/g, ' ').replace(/\s+-\s*$/, '').replace(/\s+/g, ' ').trim();
  function текстЧасовГорода(L) {
    const c = клиентСейчас(L);
    if (!c || !c.now) return '';
    const д = c.iso ? ДН_КР[new Date(c.iso + 'T12:00:00Z').getUTCDay()] + ' ' + c.iso.slice(8, 10) + '.' + c.iso.slice(5, 7) : '';
    const город = городФормы(L), где = вГороде(город);
    return { время: c.now, строка: 'Сейчас ' + (где || (город ? '· ' + город.replace(/\s*\(.*?\)\s*/g, ' ').trim() : 'у клиента')) + (д ? ' · ' + д : '') };
  }
  function часыГорода(L) {
    const т = текстЧасовГорода(L);
    if (!т) return '';
    return h('div', { class: 'fz-clock', 'data-city-clock': '1', title: 'Сейчас в городе клиента' + (L.clock && L.clock.how ? ' — пояс ' + L.clock.how : '') },
      h('span', { class: 'cc-t', 'data-cc': 'город' }, т.строка), h('b', { 'data-cc': 'время' }, т.время));
  }
  setInterval(() => {
    try {
      if (!S || !S.lead || !panel.classList.contains('open')) return;
      const т = текстЧасовГорода(S.lead);
      if (!т) return;
      for (const el of root.querySelectorAll('[data-city-clock]')) {
        const a = el.querySelector('[data-cc="время"]'), b = el.querySelector('[data-cc="город"]');
        if (a && a.textContent !== т.время) a.textContent = т.время;
        if (b && b.textContent !== т.строка) b.textContent = т.строка;
      }
    } catch (_e) { /* панель закрыта */ }
  }, 15e3);
  // галочки «Прозвон» / «Позвонить перед выездом» — как сейчас в форме (нет формы — как в заявке)
  function галочкиПрозвона() {
    const o = {};
    for (const k of ['call_check', 'call_before_visit']) { const e = формаЭтого() && panel.querySelector('[data-f="' + k + '"]'); if (e) o[k] = e.checked; }
    return o;
  }
  /* Перед «Создать» (и строкой в «Визите»): визит раньше, чем сейчас у клиента, — не создаём (block, поле — красным);
     нет даты или времени и «Прозвон» не отмечен — только предупреждение (warn). field — какое поле подсветить */
  function визитПроблема(L) {
    const out = { block: '', warn: '', field: '' };
    if (!L) return out;
    const d = String(L.visit_date || ''), t = String(L.visit_time || '').slice(0, 5), c = клиентСейчас(L);
    const дм = (x) => x.slice(8, 10) + '.' + x.slice(5, 7);
    if (c && c.iso && /^\d{4}-\d{2}-\d{2}$/.test(d) && (d < c.iso || (d === c.iso && /^\d{2}:\d{2}$/.test(t) && c.now && t < c.now))) {
      out.block = 'визит ' + дм(d) + (t ? ' в ' + t : '') + ' уже прошёл: у клиента сейчас ' + (d < c.iso ? дм(c.iso) + ' ' : '') + c.now + ' — поставьте дату и время впереди';
      out.field = d < c.iso ? 'visit_date' : 'visit_time';
    } else if (!L.call_check && промахОкна(L)) {
      // 2.2.7: клиент может только до срока, а по регламенту не успеваем — время не ставим, договориться о другом (не создаём)
      out.warn = промахОкна(L); out.окно = true; out.field = 'visit_time';
    } else if ((!d || !t) && !L.call_check) {
      out.warn = (!d && !t ? 'нет даты и времени визита' : !d ? 'нет даты визита' : 'нет времени визита') + ', «Прозвон» не отмечен — договоритесь о времени или отметьте «Прозвон»';
      out.field = !d ? 'visit_date' : 'visit_time';
    }
    return out;
  }
  const dirName = (d) => (DIRS.find((x) => x[0] === d) || [, ''])[1];

  /* ---------- форма ---------- */
  // подпись над «Визитом»: что нашёл разбор, а если оператор заполнил сам — «указано»
  function визитСтатус(tc, d, t) {
    // Ближайшее по регламенту; отметка «Прозвон» не меняет нормативный интервал.
    if (S && визитАвто({ ...S.lead, visit_date: d, visit_time: t })) {
      const a = S.lead.visit_auto;
      if (a.kind === 'ближайшее') return h('span', { class: 'st ' + (a.завтра ? 'warn' : 'mut'), title: 'Клиент время не называл — ' + текстБлижайшего(a), 'data-visit-st': '1' }, 'ближайшее по регламенту');
      return h('span', { class: 'st warn', title: 'Время с клиентом не согласовано. Прозвон; время заявки — ближайшее по нормативу города', 'data-visit-st': '1' }, 'прозвон · ближайшее');
    }
    const сам = !!(d && t) && !(tc && tc.ok);
    // 2.1: разбор нашёл время, а поле стёрли и «Прозвон» не отмечен — не держим старую подпись «завтра в 15»
    const пз = формаЭтого() ? галочкиПрозвона() : {};
    if (tc && tc.ok && (!d || !t) && !(пз.call_check !== undefined ? пз.call_check : S && S.lead.call_check)) {
      const нет = !d && !t ? 'нет даты и времени' : !d ? 'нет даты' : 'нет времени';
      return h('span', { class: 'st warn', title: нет + ' визита', 'data-visit-st': '1' }, нет);
    }
    const text = сам ? 'указано: ' + d.slice(8, 10) + '.' + d.slice(5, 7) + ' в ' + t : (tc && tc.note) || '';
    return text ? h('span', { class: 'st ' + ((tc && tc.ok) || сам ? (/проверьте/.test(text) ? 'warn' : 'ok') : 'warn'), title: text, 'data-visit-st': '1' }, text) : h('span', { 'data-visit-st': '1' });
  }
  // «Прозвон» отметили / сняли — строка про визит без даты-времени обновляется сразу
  panel.addEventListener('change', (e) => { const f = e.target && e.target.getAttribute && e.target.getAttribute('data-f'); if (f === 'call_check' || f === 'call_before_visit') обновитьВизит(); });
  // 2.1: любая правка формы — строка «что дальше» и строка под «Создать» следом (что мешает, видно до нажатия)
  for (const тип of ['input', 'change']) panel.addEventListener(тип, (e) => { const t = e.target; if (t && t.closest && t.closest('.pb.fm, .pf.fm')) обновитьСтатус(); });
  function обновитьВизит() {
    const st = panel.querySelector('[data-visit-st]'), d = (panel.querySelector('[data-f="visit_date"]') || {}).value || '', t = (panel.querySelector('[data-f="visit_time"]') || {}).value || '';
    if (st && S) st.replaceWith(визитСтатус(S.checks.find((c) => c.field === 'time'), d, t));
    const tw = panel.querySelector('[data-terr-time]');
    if (tw && S) tw.replaceWith(terrTimeWarn(d, t));
    const va = panel.querySelector('[data-visit-auto]');
    if (va && S) va.replaceChildren(...строкиБлижайшего(d, t));
    // 2.0.8: МНЧ, визит на 2+ дня вперёд — «Позвонить перед выездом» обязательно; дату поменяли — галочка следует за ней
    // (клиент сам просил предупредить — остаётся всегда; оператор щёлкнул сам — его выбор не трогаем).
    // 13.10: «Прозвон» при этом сам не ставится и не возвращается — только галочкой оператора
    const cb = panel.querySelector('[data-f="call_before_visit"]'), cc = panel.querySelector('[data-f="call_check"]');
    if (cb && S && !S.lead.call_marks_manual) {
      const надо = !!S.lead.call_before_visit || наДваДня({ ...S.lead, visit_date: d });
      if (cb.checked !== надо) { cb.checked = надо; if (надо && cc) cc.checked = false; }
    }
    // 2.1: переключатель «Как договорились», подсказка под ним, быстрые дни и часы — по полям (2.3: и строка свёрнутого «Визита»)
    if (S && формаЭтого()) { обновитьЗвонок(d, t); обновитьБыстрые(d, t); обновитьСтатус(); }
  }

  /* 2.1: «Как договорились» — один переключатель из трёх положений вместо двух галочек. Галочки call_check / call_before_visit
     остаются в форме (скрыто): их читает заявка, на них — правила 2.0.8 (МНЧ на 2+ дня — «Перед выездом» сам, следом за датой) */
  const ЗВОНОК = [
    ['exact', 'Точно', 'Точное время: время визита договорено — звонков не нужно'],
    ['prozvon', 'Прозвон', 'Прозвон: созвониться, чтобы выбрать время визита. Ставите только вы (сам не ставится): если клиент сам попросил или не знает точного времени — '
      + 'без названного времени заявка встаёт на ближайшее по регламенту. '
      + 'Если время точное — самим предлагать созвониться нельзя. Почему: не поставил / не убрал — штраф 500 ₽ (1500 ₽ при отмене)'],
    ['before', 'Перед выездом', 'Позвонить перед выездом: время визита точное, клиент сам попросил предупредить перед выездом мастера (сами не предлагаем). '
      + 'МНЧ: заявка на 2+ дня вперёд — обязательно'],
  ];
  const режимЗвонка = (cc, cb) => (cb ? 'before' : cc ? 'prozvon' : 'exact');
  function выбратьЗвонок(k) {
    const cc = panel.querySelector('[data-f="call_check"]'), cb = panel.querySelector('[data-f="call_before_visit"]');
    if (!cc || !cb) return;
    // как щелчок оператора по галочке: их обработчики помечают выбор ручным (call_marks_manual) и снимают вторую
    for (const [el, надо] of [[cb, k === 'before'], [cc, k === 'prozvon']]) {
      if (el.checked === надо) continue;
      el.checked = надо;
      el.dispatchEvent(new Event('change', { bubbles: true }));
    }
    обновитьВизит();
  }
  function строкиЗвонка(d, t, cc, cb) {
    const L = S.lead, out = [];
    const сДатой = { ...L, visit_date: d, visit_time: t };
    // 13.10: «Прозвон» сам не ставится — клиент просит созвониться: подсказка, решает оператор
    if (L.call_words) out.push(!cc && !cb
      ? h('div', { class: 'n info', 'data-call-ask': '1', title: '«Прозвон» сам не ставится (решение владельца 13.10): нужен — отметьте сами' }, 'Клиент просит созвониться: «' + L.call_words + '» — поставьте «Прозвон» сами, если нужно')
      : h('div', { class: 'n mut' }, 'Про звонок клиент написал: «' + L.call_words + '»'));
    if (cc && визитАвто(сДатой) && L.visit_auto.kind === 'прозвон' && L.clock) out.push(h('div', { class: 'n warn' }, 'Прозвон. Время не согласовано; в заявке — ближайшее по нормативу.'));
    else if (cc && t && !наДваДня(сДатой)) out.push(h('div', { class: 'n warn', title: 'Почему: не поставил / лишний прозвон — штраф 500 ₽' }, 'Прозвон при точном времени — только если клиент сам просил созвониться и выбрать время'));
    if (наДваДня(сДатой)) out.push(cb
      ? h('div', { class: 'n info' }, L.call_marks_manual ? 'МНЧ: заявка на 2+ дня вперёд — «Перед выездом» обязательно (регламент)' : 'Поставлено само: МНЧ, заявка на 2+ дня вперёд (регламент). Поменяете дату на ближе — снимется само.')
      : h('div', { class: 'n warn' }, 'МНЧ: заявка на 2+ дня вперёд — «Перед выездом» обязательно (регламент)'));
    return out;
  }
  // «ближайшее по регламенту: +1 ч (в городе)» / «+2 ч (за чертой | город-спутник | Москва)» — почему время такое
  const текстБлижайшего = (a) => 'ближайшее по регламенту: ' + (a.плюс >= 120 ? '+2 ч' : '+1 ч') + ' (' + (a.где || 'в городе') + ')';
  /* под полями визита: своё время (ближайшее по регламенту) — почему такое; позже 21:30 — на завтра, уточнить у клиента.
     Оператор поправил время — строк нет (его время главнее) */
  // 2.3: строка окна клиента — в шапке «Визита» (шапкаВизита), здесь — только почему время такое
  function строкиБлижайшего(d, t) {
    const L = S && S.lead;
    if (!L || !визитАвто({ ...L, visit_date: d, visit_time: t }) || L.visit_auto.kind !== 'ближайшее') return [];
    const a = L.visit_auto, out = [], w = a.окно ? окноКлиента(L) : null;
    const пока = a.плюс >= 120 || a.известна ? '' : a.нет ? ' — территория не определилась: за чертой и в городе-спутнике — +2 ч, проверьте по карте'
      : ' — территория ещё проверяется: за чертой или спутник — пересчитаю';
    out.push(h('div', { class: 'n mut', 'data-auto-note': '1', title: 'Клиент точного времени визита не назвал — по регламенту ближайшее: в черте города через 1 ч от времени в городе («Через час» в CRM), филиалы Москвы, за чертой и город-спутник — через 2 ч («+2ч»)'
      + (w ? '; в окне клиента — не раньше начала и не позже срока минус 30 минут' : '') + '. «Прозвон» сам не ставится' },
      (w && a.отОкна ? 'с начала окна клиента (' + w.from + '): по регламенту можно и раньше' : текстБлижайшего(a) + (w && w.until ? ', в окне клиента — до ' + w.until : ''))
      + (a.раньше ? ', раньше ' + a.ранняя + ' не принимаем — поставлено на ' + a.ранняя : '') + пока + '. Клиент назовёт время — поправьте'));
    if (a.завтра) out.push(h('div', { class: 'n warn', 'data-auto-late': '1' }, 'позже 21:30 — по регламенту только по согласованию; поставлено на завтра ' + (a.ранняя || '10:00') + ' — уточните у клиента'));
    return out;
  }
  /* Решение владельца19.10: «Прозвон» сохраняет ближайшее по нормативу филиала.
     Точный час клиента и ручную правку не меняем. Другой день без часа не угадываем. */
  function автоПоЗвонку() {
    if (!S || !S.lead || !формаЭтого()) return;
    const cc = panel.querySelector('[data-f="call_check"]'), вд = panel.querySelector('[data-f="visit_date"]'), вт = panel.querySelector('[data-f="visit_time"]');
    if (!cc || !вд || !вт) return;
    const L = { ...S.lead, visit_date: вд.value || '', visit_time: вт.value || '' };
    const авто = визитАвто(L), вид = авто ? S.lead.visit_auto.kind : '';
    const base = авто ? L.visit_auto.base || '' : L.visit_date;
    let N = null;
    if (cc.checked && (!L.visit_time || (авто && вид !== 'прозвон'))) N = своёВремя(L, 'прозвон', base, зонаБлижайшего(L, S.terr, S.prep));
    else if (!cc.checked && авто && вид === 'прозвон') N = своёВремя(L, 'ближайшее', base, зонаБлижайшего(L, S.terr, S.prep));
    if (!N) return;
    S.lead.visit_auto = N.visit_auto; S.lead.clock = N.clock;
    вПоле('visit_date', N.visit_date); вПоле('visit_time', N.visit_time);
  }
  function обновитьЗвонок(d, t) {
    const cc = panel.querySelector('[data-f="call_check"]'), cb = panel.querySelector('[data-f="call_before_visit"]');
    if (!cc || !cb) return;
    const k = режимЗвонка(cc.checked, cb.checked);
    for (const b of panel.querySelectorAll('[data-call]')) { const on = b.getAttribute('data-call') === k; b.classList.toggle('on', on); b.setAttribute('aria-checked', on ? 'true' : 'false'); b.tabIndex = on ? 0 : -1; }
    const кк = panel.querySelector('[data-visit-call]'); if (кк) кк.textContent = ' · ' + ЗВОНОК_КР[k];
    const п = panel.querySelector('[data-call-hint]');
    if (п) п.replaceChildren(...строкиЗвонка(d, t, cc.checked, cb.checked));
  }
  // поле формы — как ввод с клавиатуры (обработчики полей и подсказки следом)
  function вПоле(name, v) {
    const el = panel.querySelector('[data-f="' + name + '"]');
    if (!el || el.disabled) return;
    el.value = v;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }
  const минЧ = (s) => { const m = /^(\d{1,2}):(\d{2})/.exec(String(s || '')); return m ? +m[1] * 60 + +m[2] : NaN; };
  const чмЧ = (n) => String(Math.floor(n / 60) % 24).padStart(2, '0') + ':' + String(n % 60).padStart(2, '0');
  // сейчас у клиента + минут (вверх до минуты, как «Через час» в CRM и как при создании — неБлижеМинимума)
  function черезУКлиента(L, минут) {
    const мс = Math.ceil((Date.now() + минут * 60e3) / 60e3) * 60e3;
    const tz = L && L.clock && L.clock.tz;
    if (tz) { const p = LC_EXTRACT.localParts(new Date(мс), tz); return { date: p.iso, time: p.hm }; }
    const d = new Date(мс);
    return { date: d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'), time: чмЧ(d.getHours() * 60 + d.getMinutes()) };
  }
  // быстрые дни (по часам клиента): сегодня, завтра и ещё два — «чт 16» (2.3: другой день — «Ещё…», календарь)
  function быстрыеДни(L) {
    const c = клиентСейчас(L);
    const база = c && c.iso ? Date.parse(c.iso + 'T12:00:00Z') : (() => { const d = new Date(); return Date.UTC(d.getFullYear(), d.getMonth(), d.getDate(), 12); })();
    return [0, 1, 2, 3].map((n) => { const iso = new Date(база + n * 864e5).toISOString().slice(0, 10);
      return [iso, n === 0 ? 'Сегодня' : n === 1 ? 'Завтра' : ДН_КР[new Date(iso + 'T12:00:00Z').getUTCDay()] + ' ' + Number(iso.slice(8, 10))]; });
  }
  /* 2.3: часы визита сеткой 10–21 (6 в ряд) и минуты :00 / :30 — как в CRM. Час ставит «ЧЧ:мм» с выбранными минутами (не выбраны — :00);
     своё время до минуты (15:40 — ближайшее по регламенту) — в поле «Время» за «Ещё…». Час сегодня уже прошёл — зачёркнут; раньше начала
     приёма, позже 21:30 и вне окна клиента — приглушён (по согласованию / клиент не может) */
  const ЧАСЫ_СЕТКИ = Array.from({ length: 12 }, (_, i) => String(i + 10).padStart(2, '0'));
  const минутыСейчас = () => { const t = (panel.querySelector('[data-f="visit_time"]') || {}).value || ''; const m = String(t).slice(3, 5);
    return m === '00' || m === '30' ? m : (S && S.минуты) || '00'; };
  function поставитьЧас(ч) {
    if (!S) return;
    const L = S.lead, d = (panel.querySelector('[data-f="visit_date"]') || {}).value || '';
    if (!d) { const c = клиентСейчас(L); if (c && c.iso) вПоле('visit_date', c.iso); }
    вПоле('visit_time', ч + ':' + минутыСейчас());
  }
  function поставитьМинуты(м) {
    if (!S) return;
    S.минуты = м;
    const t = (panel.querySelector('[data-f="visit_time"]') || {}).value || '';
    if (/^\d{2}:\d{2}/.test(t)) вПоле('visit_time', t.slice(0, 2) + ':' + м);
    else обновитьБыстрые((panel.querySelector('[data-f="visit_date"]') || {}).value || '', '');
  }
  function обновитьБыстрые(d, t) {
    const L = S.lead, c = клиентСейчас(L), сег = c && c.iso === d && c.now ? минЧ(c.now) : NaN;
    const дни = [...panel.querySelectorAll('[data-day]')].map((x) => x.getAttribute('data-day'));
    for (const b of panel.querySelectorAll('[data-day]')) {
      const v = b.getAttribute('data-day');
      const on = v === 'cal' ? !!d && !дни.includes(d) : v === d;
      b.classList.toggle('on', on); b.setAttribute('aria-pressed', on ? 'true' : 'false');
      if (v === 'cal') b.textContent = on ? деньСловом(L, d) : 'Ещё…';
    }
    const ран = минЧ((S.terr && S.terr.ok && S.terr.earliest) || '10:00'), w = окноКлиента(L);
    const вОкне = !!(w && (!w.date || w.date === d));
    const чs = String(t || '').slice(0, 2);
    for (const b of panel.querySelectorAll('[data-hour]')) {
      const v = b.getAttribute('data-hour'), н = Number(v) * 60;
      const прошло = !isNaN(сег) && н + 30 < сег;
      const рано = !isNaN(ран) && н + 30 < ран, поздно = н > 21 * 60 + 30;
      const внеОкна = вОкне && ((w.until && н > минЧ(w.until) - 30) || (w.from && н + 30 < минЧ(w.from)));
      b.classList.toggle('on', v === чs); b.setAttribute('aria-pressed', v === чs ? 'true' : 'false');
      b.classList.toggle('past', прошло); b.classList.toggle('soft', !прошло && (рано || поздно || внеОкна));
      b.title = прошло ? 'уже прошло' : рано ? 'раньше ' + чмЧ(ран) + ' — по согласованию с филиалом' : поздно ? 'позже 21:30 — по согласованию с филиалом' : внеОкна ? 'вне окна клиента (' + LC_EXTRACT.окноСловами(w) + ')' : '';
    }
    const м = /^\d{2}:(\d{2})/.exec(String(t || '')), мм = м ? м[1] : (S.минуты || '');
    for (const b of panel.querySelectorAll('[data-min]')) { const on = b.getAttribute('data-min') === мм && (!м || мм === '00' || мм === '30'); b.classList.toggle('on', on); b.setAttribute('aria-pressed', on ? 'true' : 'false'); }
    // строка свёрнутого «Визита», «Выбрано: …» и шапка (окно клиента / «не успеваем») — следом за полями
    const val = panel.querySelector('[data-visit-val]'); if (val) val.textContent = визитСловами(L, d, t);
    const sl = panel.querySelector('[data-visit-sel]'); if (sl) sl.replaceChildren(...строкаВыбрано(d, t).filter((x) => x !== ''));
    const hd = panel.querySelector('[data-visit-head]'); if (hd) hd.replaceChildren(...[шапкаВизита(d, t)].filter((x) => x !== ''));
  }
  // поле времени формы несёт часы города: окно выбора времени считает «сейчас», «Через час» и границы приёма по ним
  function атрибутыВремени(L) {
    const c = клиентСейчас(L), город = городФормы(L);
    return { 'data-tz': (L.clock && L.clock.tz) || undefined, 'data-now': c && !(L.clock && L.clock.tz) ? c.now : undefined, 'data-now-at': c && !(L.clock && L.clock.tz) ? String(Date.now()) : undefined,
      'data-today': c ? c.iso : undefined, 'data-where': вГороде(город) || (город ? '· ' + город.replace(/\s*\(.*?\)\s*/g, ' ').trim() : undefined),
      'data-earliest': (S.terr && S.terr.ok && S.terr.earliest) || '10:00', 'data-latest': '21:30' };
  }

  /* 2.1: комментарий — в поле только текст для CRM; служебные строки, которые код дописывает сам (🔴БЕЛАЯ ЗАЯВКА🔴, 🟢ссылка🟢,
     «Уточнено: …»), — чипами под ним: стереть случайно нельзя. Полный текст живёт в скрытом [data-f="comment"] — его читает заявка
     (readForm), как и раньше: в CRM уходит ровно то же. Правка текста собирает полный: белая — сверху, «Уточнено» и ссылка — внизу */
  const служебнаяСтрока = (l) => /БЕЛАЯ ЗАЯВКА/.test(l) || /^🟢.*🟢$/.test(String(l).trim()) || /^Уточнено: |^Объявление: «/.test(String(l).trim());
  const текстКомментария = (full) => String(full || '').split('\n').filter((l) => !служебнаяСтрока(l)).join('\n').replace(/^\s*\n+/, '').replace(/\n+\s*$/, '');
  function собратьКомментарий(текст, full) {
    const стр = String(full || '').split('\n');
    const верх = стр.filter((l) => /БЕЛАЯ ЗАЯВКА/.test(l));
    const rank = (l) => /^Объявление: «/.test(l.trim()) ? 0 : /^🟢/.test(l.trim()) ? 2 : 1;
    const низ = стр.filter((l) => !/БЕЛАЯ ЗАЯВКА/.test(l) && служебнаяСтрока(l))
      .sort((a, b) => rank(a) - rank(b));     // подпись, затем «Уточнено», ссылка — последней
    return [...верх, String(текст || '').replace(/\s+$/, ''), ...низ].filter((x) => String(x).trim()).join('\n');
  }
  /* что добавится к заявке само (в комментарий, служебный, «Комментарий партнёра») — 2.3: словами одной строкой под комментарием
     («Добавится само: ссылка на диалог, источник С74.2, ссылка для отзыва»), что именно — в подсказке; в CRM уходит то же, что раньше */
  function служебныеЧипы(L) {
    const out = [], стр = String(L.comment || '').split('\n').map((x) => x.trim()).filter(служебнаяСтрока);
    for (const l of стр.filter((x) => /БЕЛАЯ ЗАЯВКА/.test(x))) out.push(['bad', 'белая заявка', l]);
    out.push(['', 'ссылка на диалог', 'В «Служебный комментарий»: ' + location.origin + '/chats/' + encodeURIComponent(S.id || '')]);
    if (S.zkChoice === 'by' && S.zakrep && S.zakrep.text) out.push(['', 'закреп', 'В «Служебный комментарий»: Закреп: ' + S.zakrep.text]);
    const R = историяКлиента();
    if (R && R.comment) out.push(['', 'история: ' + R.comment, 'В комментарий и служебный — по регламенту истории клиента' + (R.why ? ' (' + R.why + ')' : '')]);
    const код = LC_TG.кодИсточника(L.partner_note || '');
    if (L.partner_note) out.push(['', 'источник ' + (код || L.partner_note), 'В «Комментарий партнёра» — только код источника']);
    for (const l of стр.filter((x) => /^Уточнено: /.test(x))) out.push(['', 'у' + (l.length > 60 ? l.slice(1, 58) + '…' : l.slice(1)), 'Ответы клиента по регламенту — строкой в комментарии: ' + l]);
    for (const l of стр.filter((x) => /^🟢.*🟢$/.test(x))) out.push(['', 'ссылка для отзыва', 'Ссылка для отзыва — строкой в комментарии: ' + l.replace(/🟢/g, '')]);
    return out.map(([cls, t, title]) => h('span', { class: 'fz-tag' + (cls ? ' ' + cls : ''), title }, t));
  }
  const подписьПроверить = (L) => !!(L.ad_identity && !L.ad_identity_set && !L.ad_identity_from_ad);
  const текстПодписи = (L) => L.ad_identity || (L.ad_identity_required ? 'Имя / аккаунт не указаны' : 'Исходного объявления нет');
  const пояснениеПодписи = (L) => !L.ad_identity ? (L.ad_identity_required ? 'укажите до создания заявки' : 'заполните вручную, если известно')
    : [подписьПроверить(L) ? 'подставлен канал — проверьте' : L.ad_identity_set ? 'уточнено оператором' : 'из объявления',
      L.introduced_as ? 'представились: ' + L.introduced_as : 'в комментарий CRM'].join(' · ');
  function правкаПодписи() {
    if (!формаЭтого()) return;
    keepEdits();
    panel.querySelector('[data-f="comment"]').value = S.lead.comment;
    const tags = panel.querySelector('[data-cm-tags]');
    if (tags) tags.replaceChildren(...служебныеЧипы(S.lead).flatMap((x, i) => [i ? ', ' : '', x]));
    const sec = panel.querySelector('[data-sec="advertiser"]');
    if (sec) {
      sec.classList.toggle('ad-review', подписьПроверить(S.lead));
      const value = sec.querySelector('[data-row-val]'), note = sec.querySelector('[data-row-note]');
      if (value) { value.textContent = текстПодписи(S.lead); value.title = S.lead.ad_identity || ''; }
      if (note) { note.textContent = пояснениеПодписи(S.lead); note.title = LC_EXTRACT.advertiserLine(S.lead); }
      const warning = sec.querySelector('[data-advertiser-fallback]');
      if (warning) warning.hidden = !подписьПроверить(S.lead);
    }
    кнопкаФормы();
  }

  /* 2.1: что мешает создать или что нужно сделать до «Создать» — одним списком под шапкой (правила создания не меняются:
     те же проверки, что у createNow, почемуНет и регламента, — только видно сразу и у каждого «к полю →») */
  const пунктКратко = (t) => String(t).replace(/^(Если|В случае)[^,]*,\s*/i, '').replace(/^(нужно|необходимо)\s+(сразу\s+)?/i, '').replace(/^уточнять\s+/i, '').slice(0, 70);
  function чтоМешает(f) {
    const out = [], P = S.prep && S.prep.ok ? S.prep : null, L = f.lead;
    const add = (k, текст, к, block, коротко, действие) => out.push({ k, текст, к, block: !!block, коротко: коротко || текст, действие });
    if (!S.dir) add('dir', 'Выберите базу вверху: МНЧ, КП или БТ', '.ph .seg button', true, 'база');
    else if (S.prep && !S.prep.ok) add('prep', 'Форма CRM не загрузилась — «Повторить» в сообщении CRM', '[data-prep-err] button', true, 'форма CRM');
    else if (!S.prep) add('prep', 'Форма CRM ещё не загружена', '', true, 'форма CRM');
    else if (!P.cityId) add('city', 'Выберите город в CRM', '[data-f="cityId"]', true, 'город');
    if (String(L.phone || '').length !== 10) add('phone', 'Телефон клиента — 10 цифр', '[data-f="phone"]', true, 'телефон');
    if (L.ad_identity_required && !L.ad_identity) add('advertiser', 'Укажите имя мастера из объявления или название аккаунта', '[data-f="ad_identity"]', true, 'имя / аккаунт объявления');
    if (!(L.addr && (L.addr.street || L.addr.settlement))) add('addr', 'Адрес — улица или нас. пункт', '[data-f="street"]', true, 'адрес');
    const вп = визитПроблема(L);
    if (вп.block) add('visit', 'Визит уже прошёл — поставьте дату и время впереди', '[data-f="' + вп.field + '"]', true, 'дата визита');
    if (L.phone_risky && L.phone === L.phone_risky && !L.phone_ok) add('phoneOk', 'Сверьте номер с клиентом и отметьте «номер сверил»', '[data-f="phoneOk"]', true, 'номер');
    if (белаяНаБТ(L, S.dir) && !S.allowWhite) add('white', 'Белая заявка на БТ — создаём в КП или МНЧ', '[data-f="allowWhite"]', true, 'белая на БТ');
    const R = историяКлиента();
    if (R && R.action === 'вернуть' && !f.allowNew) add('return', 'По регламенту — вернуть № ' + R.ref.id + ' в «Ожидает», а не создавать новую', '[data-return]', true, 'вернуть № ' + R.ref.id);
    if (P && P.moderation && !f.allowLive) add('moder', 'Заявка в «Модерации» — возьмите её в работу, новую не создавайте', '[data-f="allowLive"]', true, 'модерация');
    else if (P && P.live && !f.allowLive) add('live', 'У клиента уже есть заявка «' + P.live + '» — вторую без отметки не создаю', '[data-f="allowLive"]', true, 'живая заявка');
    // 2.1.1: клиент уже есть в CRM — адрес заявки берётся из ЕГО карточки; без номера дома расширение её не трогает, и в заявке остался бы
    // прежний адрес (штраф КП 2684667: мастер поехал на адрес прошлой заявки). Создавать — только с домом
    if (P && P.customer && P.customer.id && L.addr && (L.addr.street || L.addr.settlement) && !String(L.addr.building || '').trim())
      add('house_cust', 'Номер дома — клиент уже есть в CRM: без дома в заявке останется его прежний адрес', '[data-f="building"]', true, 'дом');
    if (P && P.customer && P.customer.count > 1) add('many', 'В CRM несколько клиентов с этим номером (' + P.customer.count + ') — заведите вручную', '[data-f="phone"]', true, 'клиенты в CRM');
    if (S.botCheck && !S.botCheck.ok && !f.allowBot) add('bot', 'Лид-бот мог завести заявку — проверьте CRM', '[data-f="allowBot"]', true, 'лид-бот');
    // дальше — создать не мешает, но регламент требует до «Создать»
    // 2.2.7: клиент может только до срока, а по регламенту не успеваем — не создаём, пока не договоритесь о другом времени / дне
    if (вп.окно) add('window', 'Клиент может только до ' + ((окноКлиента(L) || {}).until || '') + ' — не успеваем: договоритесь о другом времени/дне', '[data-f="' + вп.field + '"]', true, 'окно клиента');
    else if (вп.warn) add('time', 'Время визита — договоритесь или «Прозвон»', '[data-f="' + вп.field + '"]', false, 'время визита');
    const нужно = (S.check && S.check.approval) || terrReason() || repeatReason();
    const ответили = (S.tgReplies || []).length > 0;
    if (P && P.cityId) {
      if (нужно && !S.tgSent) add('tg', 'Согласование с филиалом — отправьте в чат города', '[data-sec="tg"] button', false, 'согласование');
      else if (S.tgSent && !ответили && !S.tgSent.done) add('tgwait', 'Ждём ответ филиала на согласование — по регламенту создаём после ответа', '[data-sec="tg"]', false, 'ответ филиала');
      else if (!нужно && S.check && S.check.refuse) add('refuse', 'Не наш профиль? Спросите филиал в чате города', '[data-refuse] button', false, 'профиль');
      else if (!нужно && !S.tgSent && S.check && S.check.maybe) add('maybe', 'Проверьте, нужно ли согласование', '[data-sec="tg"] button', false, 'согласование');
    }
    if (S.адресLC && S.адресLC.text && !S.addrAsked) add('lcaddr', 'LeadChat ещё проверяет адрес — ~1–2 мин', '[data-addr-lc] button', false, 'адрес в LeadChat');
    else if (прошлыйАдрес(L)) add('addrprev', прошлыйКарточки(L) ? 'Адрес из прошлого обращения — спросите клиента, актуален ли' : типЗаявки() + ' — сверьте адрес с клиентом: в этом диалоге его не называли', '[data-addr-prev] button', true, 'адрес');
    else if (L.addr_warn) add('addrq', 'Адрес не точный: ' + (L.addr_warn.length > 90 ? L.addr_warn.slice(0, 88) + '…' : L.addr_warn), '[data-addr-warn]', false, 'адрес');
    else if (S.terr && !S.terr.ok && S.terr.mismatch) add('house', 'Дом не найден на карте — уточните нас. пункт', '[data-terr] button, [data-f="settlement"]', false, 'нас. пункт');
    const нет = S.check && !S.check.busy ? (S.check.results || []).filter((x) => !x.done) : [];
    for (const x of нет.slice(0, 3)) add('ck', 'Уточнить: ' + пунктКратко(x.item), '[data-check]', false, 'регламент');
    if (нет.length > 3) add('ck', 'И ещё ' + (нет.length - 3) + ' по регламенту', '[data-check]', false, 'регламент');
    if (S.lcDup && (S.lcDup.rows || []).length) add('dup', 'Клиент в другом диалоге — договоритесь, кто оформляет', '[data-dup] a', false, 'другой диалог');
    if (L.voice && L.voice.note) add('voice', 'Голосовое: ' + L.voice.note, '', false, 'голосовое',
      L.voice.wait ? { t: 'Прочитать заново', title: 'Прочитать диалог заново — голосовое могло расшифроваться', fn: () => collect(null, true) } : null);
    if (!/[a-zа-яё]/i.test(L.name || '') && !(P && P.customer && P.customer.id)) add('name', 'Имя клиента — уточните', '[data-f="name"]', false, 'имя');
    return out;
  }
  /* 2.3: подтверждения — их решает надпись главной кнопки («Создать вторую заявку — у клиента № …», «Номер сверил — создать»…),
     а не галочка + повторное «Создать». В общем списке «Осталось N» их нет: то же замечание второй раз не повторяем */
  const ПОДТВЕРЖДЕНИЯ = new Set(['phoneOk', 'white', 'return', 'moder', 'live', 'bot', 'zk', 'lcaddr', 'addrprev']);
  // скрытая часть формы («+ второй номер», «+ посёлок», «Ещё…» у визита) и свёрнутая в строку секция — открыть, чтобы показать поле
  function открытьСкрытое(el) {
    if (!el || !el.closest) return;
    const sec = el.closest('section.cz');
    if (sec && !sec.classList.contains('open')) открытьСекцию(sec, true);
    const w = el.closest('.fz-open[hidden]');
    if (!w) return;
    w.hidden = false;
    const m = panel.querySelector('[data-more="' + w.getAttribute('data-open') + '"]');
    if (m) m.hidden = true;
  }
  /* 2.3 (Claude Design «Лид-центр — компактно», листы Create / CreateIssues): секция, где всё в порядке, — одной строкой
     (метка · значение · пояснение мелко · ✎). ✎ раскрывает поля (как в 2.1), ▴ сворачивает обратно. Сразу раскрыты только секции
     с проблемой или решением (⚠). Поля свёрнутой секции остаются в форме (скрыты): их читает заявка, подсказки и проверки — как раньше.
     Выбор оператора (раскрыл / свернул, начал править поле) помним до новой формы диалога: перерисовка его не теряет */
  const ДВИЖЕНИЯ_СЕКЦИЙ = new WeakMap();
  function плавноСекцию(sec, change) {
    const from = sec.getBoundingClientRect().height;
    const previous = ДВИЖЕНИЯ_СЕКЦИЙ.get(sec);
    if (previous) { previous.animation.cancel(); sec.style.overflow = previous.overflow; }
    change();
    if (!sec.animate || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const to = sec.getBoundingClientRect().height;
    if (Math.abs(from - to) < 1) return;
    const overflow = sec.style.overflow;
    sec.style.overflow = 'hidden';
    const animation = sec.animate([{ height: from + 'px' }, { height: to + 'px' }], { duration: to > from ? 180 : 130, easing: 'cubic-bezier(.2,.8,.2,1)' });
    ДВИЖЕНИЯ_СЕКЦИЙ.set(sec, { animation, overflow });
    animation.onfinish = animation.oncancel = () => {
      if (ДВИЖЕНИЯ_СЕКЦИЙ.get(sec)?.animation !== animation) return;
      ДВИЖЕНИЯ_СЕКЦИЙ.delete(sec); sec.style.overflow = overflow;
    };
  }
  function открытьСекцию(sec, on) {
    if (!sec) return;
    const key = sec.getAttribute('data-sec');
    const row = sec.querySelector(':scope > .cz-row'), body = sec.querySelector(':scope > .cz-body');
    const вернутьФокус = !on && body && body.contains(root.activeElement);
    плавноСекцию(sec, () => {
      sec.classList.toggle('open', !!on);
      if (row) row.hidden = !!on;
      if (body) body.hidden = !on;
    });
    const ed = sec.querySelector(':scope > .cz-row .cz-ed');
    if (ed) ed.setAttribute('aria-expanded', String(!!on));
    if (S && key) S.раскрыто = { ...(S.раскрыто || {}), [key]: !!on };
    if (вернутьФокус && ed) ed.focus({ preventScroll: true });
  }
  const открыта = (key, проблема) => (S.раскрыто && Object.prototype.hasOwnProperty.call(S.раскрыто, key) ? !!S.раскрыто[key] : !!проблема);
  // оператор начал править поле раскрытой секции — она остаётся раскрытой и после того, как замечание ушло (ответы фона перерисуют форму)
  panel.addEventListener('focusin', (e) => {
    const t = e.target, sec = t && t.closest && t.closest('section.cz.open');
    if (!sec || !S || !t.matches('input, select, textarea')) return;
    const key = sec.getAttribute('data-sec');
    if (key && !(S.раскрыто && S.раскрыто[key])) S.раскрыто = { ...(S.раскрыто || {}), [key]: true };
  });
  function секция(key, o, ...kids) {
    const откр = открыта(key, o.проблема);
    const sec = h('section', { class: 'sec cz' + (откр ? ' open' : '') + (o.проблема ? ' warn' : '') + (o.класс ? ' ' + o.класс : ''), 'data-sec': key });
    const кн = o.кнопка || h('button', { type: 'button', class: 'cz-ed', 'aria-label': 'Изменить: ' + o.метка, 'aria-expanded': String(откр), 'aria-controls': 'lcz-section-' + key, title: 'Изменить — раскрыть поля',
      onclick: () => {
        открытьСекцию(sec, true);
        const x = sec.querySelector('.cz-body input:not([type=hidden]):not([type=checkbox]):not([type=radio]), .cz-body select, .cz-body textarea:not([hidden])');
        if (x && !x.closest('[hidden]')) { ТИХИЙ_ФОКУС.on = true; try { x.focus({ preventScroll: true }); } finally { ТИХИЙ_ФОКУС.on = false; } }
        if (sec.scrollIntoView) sec.scrollIntoView({ block: 'nearest' });
      } }, svg('edit'));
    sec.append(
      h('div', { class: 'cz-row', hidden: откр, onclick: (e) => {
        // Вся строка открывает секцию. Ссылки и собственные действия сохраняют своё поведение.
        if (!e.target.closest('button,a,input,select,textarea,label')) кн.click();
      } },
        h('div', { class: 'cz-l' }, o.метка),
        h('div', { class: 'cz-v' },
          h('div', { class: 'cz-v1', 'data-row-val': key, title: typeof o.значение === 'string' ? o.значение : undefined }, o.значение || '—'),
          o.пояснение ? h('div', { class: 'cz-v2', 'data-row-note': key, title: typeof o.пояснение === 'string' ? o.пояснение : undefined }, o.пояснение) : ''),
        кн),
      h('div', { class: 'cz-body', id: 'lcz-section-' + key, hidden: !откр },
        h('div', { class: 'sh' }, h('h3', {}, o.заголовок || o.метка), h('div', { class: 'cz-sh' }, o.шапка || '',
          h('button', { type: 'button', class: 'cz-up', 'aria-label': 'Свернуть: ' + o.метка, title: 'Свернуть в строку', onclick: () => открытьСекцию(sec, false) }, svg('up')))),
        ...kids));
    return sec;
  }
  // «Осталось N: …» — пункт: короткое имя, нажатие — к секции и полю (секция раскрывается)
  function строкаСтатуса(x) {
    const к = x.к ? () => { const el = panel.querySelector(x.к); if (el) { открытьСкрытое(el); кПолю(el); } } : null;
    // своё действие у пункта (голосовое ещё расшифровывается — «Прочитать заново») — словом после него
    return h('span', { class: 'cz-it' + (x.block ? ' block' : ''), 'data-why': x.k },
      к ? h('button', { type: 'button', class: 'cz-go', title: x.текст, 'aria-label': 'К полю: ' + x.текст, onclick: к }, x.коротко) : h('span', { title: x.текст }, x.коротко),
      x.действие ? h('span', {}, ' · ', h('button', { type: 'button', class: 'cz-go', title: x.действие.title || '', onclick: x.действие.fn }, x.действие.t)) : '');
  }
  function полосаСтатуса(items) {
    // одно и то же замечание — один пункт (три пункта регламента — «регламент» один раз)
    const сп = [], было = new Set();
    for (const x of items) if (!ПОДТВЕРЖДЕНИЯ.has(x.k) && !было.has(x.коротко)) { было.add(x.коротко); сп.push(x); }
    if (!сп.length) return h('div', { class: 'cz-st ok', role: 'status', 'data-status': 'ok' }, svg('check'), h('span', {}, 'Всё есть — проверьте и создайте'));
    return h('div', { class: 'cz-st warn', role: 'status', 'data-status': String(сп.length), title: сп.map((x) => x.текст).join('\n') }, svg('warn'),
      h('span', { class: 'cz-st-t' }, 'Осталось ' + сп.length + ': ', ...сп.flatMap((x, i) => [i ? ', ' : '', строкаСтатуса(x)])));
  }
  // по форме на экране (правки оператора), а пока формы нет — по разбору
  function формаДляСтатуса() {
    if (!формаЭтого()) return { lead: S.lead, allowLive: false, allowNew: false, allowBot: false };
    const f = readForm(), ck = (k) => { const e = panel.querySelector('[data-f="' + k + '"]'); return !!(e && e.checked); };
    return { ...f, allowNew: ck('allowNew'), allowBot: ck('allowBot') };
  }
  function обновитьСтатус() {
    if (!S || !формаЭтого()) return;
    const items = чтоМешает(формаДляСтатуса());
    const old = panel.querySelector('[data-status]');
    if (old) {
      const фок = root.activeElement && old.contains(root.activeElement) ? root.activeElement.closest('[data-why]') : null;
      const нов = полосаСтатуса(items);
      old.replaceWith(нов);
      if (фок) { const b = нов.querySelector('[data-why="' + фок.getAttribute('data-why') + '"] button'); if (b) b.focus({ preventScroll: true }); }
    }
    обновитьГлавную();
  }

  /* 2.3 ГЛАВНАЯ КНОПКА говорит, что будет: одно явное нажатие = подтверждение (раньше — галочка «Всё равно создать» и второе «Создать»).
     Порядок — как у проверок createNow; подтвердил одно, а есть следующее — кнопка меняет надпись (без создания). Проверки и запреты
     прежние: галочки остаются в форме (скрыто) — их ставит кнопка, читают readForm / createNow / CRM.
     Закреп выбирается отдельно в форме, по умолчанию без отметок. Ctrl+Enter — обычное «Создать» (createNow): подтверждения он сам не ставит */
  const отмечено = (k) => { const e = формаЭтого() && panel.querySelector('[data-f="' + k + '"]'); return e ? !!e.checked : !!(S.подтв && S.подтв[k]); };
  function отметить(k) {
    S.подтв = { ...(S.подтв || {}), [k]: true };
    const e = формаЭтого() && panel.querySelector('[data-f="' + k + '"]');
    if (e && !e.checked) { e.checked = true; e.dispatchEvent(new Event('change', { bubbles: true })); }
  }
  // заявка клиента «в работе» словами для кнопки: «№ 4242 «В работе»» (номер — из поиска по базам)
  function живаяСловами(P) {
    const st = String(P.live || ''), m = /№\s*(\d+)/.exec(st);
    const r = (P.found || []).find((x) => x.status && (st.startsWith(x.status) || (m && String(x.id) === m[1])));
    const статус = st.replace(/\s*\(.*\)\s*$/, '');
    return (r ? '№ ' + r.id + ' ' : m ? '№ ' + m[1] + ' ' : '') + '«' + статус + '»';
  }
  function главнаяКнопка() {
    const P = S.prep && S.prep.ok ? S.prep : null, где = S.dir ? ' в ' + dirName(S.dir) : '';
    const j = задачаИдёт(S.id);
    if (j) return { label: j.ход.текст, disabled: true };
    if (!P || !P.cityId) return { label: 'Создать заявку' + где, disabled: true };
    const L = формаЭтого() ? readForm().lead : S.lead;
    const R = историяКлиента();
    if (L.phone_risky && L.phone === L.phone_risky && !L.phone_ok)
      return { k: 'phoneOk', label: 'Номер ' + fmtPhone(L.phone) + ' сверил — создать', note: L.phone_warn || 'Номер из карточки LeadChat под сомнением — сверьте с клиентом',
        why: 'Нажатие = «номер сверил с клиентом, это его номер»', set: () => { S.lead.phone_ok = true; отметить('phoneOk'); } };
    if (прошлыйАдрес(L))
      return { k: 'addrprev', label: 'Клиент подтвердил адрес — создать', note: (прошлыйКарточки(L) ? 'Адрес из прошлого обращения клиента' : 'Тип «' + типЗаявки() + '» — адрес сверяют с клиентом')
        + ': в этом диалоге его не называли. Спросите, куда нужен мастер сейчас; другой — впишите в «Адресе».', why: 'Нажатие = «клиент подтвердил: адрес тот же»',
      set: () => { снятьПрошлый(true); const b = panel.querySelector('[data-addr-prev]'); if (b) b.remove(); } };
    if (белаяНаБТ(L, S.dir) && !отмечено('allowWhite'))
      return { k: 'white', label: 'Всё равно создать в БТ — белая заявка', warn: true, note: 'Белая заявка (партнёр 723 / источник «Белый …»): по регламенту только в КП и МНЧ — базу можно сменить вверху.',
        why: 'Нажатие = «да, белую — в БТ»', set: () => { S.allowWhite = true; отметить('allowWhite'); } };
    if (R && R.action === 'вернуть' && !отмечено('allowNew')) {
      const когда = S.lead.visit_date || S.lead.visit_time ? ' на ' + [S.lead.visit_date ? S.lead.visit_date.slice(8, 10) + '.' + S.lead.visit_date.slice(5, 7) : '', S.lead.visit_time].filter(Boolean).join(' ') : '';
      return { k: 'return', note: 'По регламенту новую не создаём — верните № ' + R.ref.id + ' в «Ожидает» с новым временем.', link: R.ref.url ? { url: R.ref.url, t: 'Открыть № ' + R.ref.id } : null,
        variants: [{ label: 'Вернуть № ' + R.ref.id + ' в «Ожидает»' + когда, ret: 1, fn: (b) => вернутьВОжидает(R.ref, b) },
          { label: 'Создать новую', set: () => отметить('allowNew') }] };
    }
    if (P.moderation && !отмечено('allowLive'))
      return { k: 'moder', label: 'Создать новую — у клиента ' + (P.moderation.id ? '№ ' + P.moderation.id + ' ' : 'заявка ') + 'в «Модерации»', warn: true,
        note: 'У клиента заявка в «Модерации»' + (P.moderation.id ? ' ' + dirName(P.moderation.dir) + ' № ' + P.moderation.id : '') + ' — возьмите её в работу («Взять в работу») и сохраните, новую не создавайте (будет дубль).', link: P.moderation.url ? { url: P.moderation.url, t: 'Открыть № ' + P.moderation.id } : null,
        why: 'Нажатие = «да, новая заявка нужна»', set: () => отметить('allowLive') };
    if (P.live && !отмечено('allowLive'))
      return { k: 'live', label: 'Создать вторую заявку — у клиента ' + живаяСловами(P), note: 'У клиента уже есть заявка ' + живаяСловами(P) + '.',
        why: 'Нажатие = «да, вторая заявка нужна»', set: () => отметить('allowLive') };
    if (S.botCheck && !S.botCheck.ok && !отмечено('allowBot'))
      return { k: 'bot', label: 'Проверил в CRM — создать заявку', warn: true, note: S.botCheck.text || 'Лид-бот мог завести заявку — проверьте CRM', why: 'Нажатие = «проверил в CRM, заявки нет»', set: () => отметить('allowBot') };
    if (S.адресLC && S.адресLC.text && !S.addrAsked)
      return { k: 'lcaddr', label: 'Создать, не дожидаясь проверки адреса', note: 'LeadChat ещё проверяет адрес по карте (~1–2 мин) — «Подождать» в «Адресе».', why: 'Нажатие = «создать с адресом, как в форме»',
        set: () => { S.addrAsked = true; } };
    if (S.created) return { k: 'again', label: 'Создать ещё одну — по диалогу уже есть' + (S.created.id ? ' № ' + S.created.id : ''), why: 'Нажатие = «да, ещё одна заявка»', set: () => { S.ещёОк = true; } };
    if (S.адресСпросили) return { label: 'Создать с адресом, как в форме', note: 'LeadChat ещё проверял адрес по карте — «↻» возьмёт проверенный.' };
    const review = LC_WORKFLOW.manualCreationReview(S.check,S.terr,L);
    if (review.available && review.warnings.length) return { k:'policyManual',label:'Создать с предупреждениями',warn:true,
      note:'Создание с замечаниями.',why:'Ручное создание' };
    return { label: 'Создать заявку' + где };
  }
  const кратко = (t, n) => { t = String(t || ''); return t.length > n ? t.slice(0, n - 1) + '…' : t; };
  // нажатие главной (или варианта): подтвердить и создать; есть следующее подтверждение — только новая надпись
  function нажатьГлавную(i) {
    if (!S || !формаЭтого() || S.готовлю || задачаИдёт(S.id) || !(S.prep && S.prep.ok)) { createNow(); return; }
    const к = главнаяКнопка(), x = к.variants ? к.variants[i || 0] : к;
    if (x && x.ret) return;                                            // «Вернуть в «Ожидает»» — своя кнопка (fn), не создание
    if (x && x.set) x.set();
    if (!формаЭтого()) return;
    const дальше = главнаяКнопка();
    if (дальше.k && дальше.k !== к.k && дальше.k !== 'again' && ПОДТВЕРЖДЕНИЯ.has(дальше.k)) { обновитьГлавную(); return; }
    createNow();
  }
  // футер: надпись главной, пояснение над ней, варианты — по ситуации; создаётся — шаг и не нажимается
  function главнаяБлок() {
    const к = главнаяКнопка();
    const кнопки = к.variants
      ? к.variants.map((v, i) => h('button', { class: i ? 'go2' : 'go', 'data-main': String(i), title: v.title || '', onclick: v.ret ? (e) => v.fn(e.currentTarget) : () => нажатьГлавную(i) }, v.label))
      : [h('button', { class: 'go' + (к.warn ? ' warn' : '') + (String(к.label).length > 40 ? ' long' : ''), 'data-main': '0', disabled: !!к.disabled, onclick: () => нажатьГлавную(0) }, к.label)];
    return h('div', { class: 'cz-main', 'data-main-k': к.k || '' },
      к.note ? h('div', { class: 'cz-mn', 'data-main-note': к.k || '1' }, к.note, к.link ? h('span', {}, ' ', h('a', { href: к.link.url, target: '_blank', rel: 'noopener' }, к.link.t)) : '') : '',
      h('div', { class: 'row' + (к.variants ? ' two' : '') }, ...кнопки),
      h('div', { class: 'cz-kb', 'data-foot': '1' }, к.why || (к.disabled ? '' : 'или Ctrl+Enter')));
  }
  function обновитьГлавную() {
    if (!S || !формаЭтого()) return;
    const old = panel.querySelector('.pf .cz-main');
    if (!old) return;
    const фок = root.activeElement && old.contains(root.activeElement);
    const нов = главнаяБлок();
    if (old.getAttribute('data-main-k') === нов.getAttribute('data-main-k') && old.textContent === нов.textContent) {
      const a = old.querySelector('.go'), b = нов.querySelector('.go');
      if (a && b) a.disabled = b.disabled;
      return;
    }
    old.replaceWith(нов);
    if (фок) { const b = нов.querySelector('.go'); if (b && !b.disabled) b.focus({ preventScroll: true }); }
  }

  /* 2.3 визит одним окном: строка «Сегодня 15:40 · ближайшее…», раскрыто — дни (Сегодня / Завтра / ещё два / «Ещё…» → календарь),
     часы 10–21 сеткой, :00 / :30 и «Точно / Прозвон / Перед выездом». Поля «Дата» и «Время» — за «Ещё…» (там же «Срочная», «Дальний выезд») */
  const деньСловом = (L, d) => { const c = клиентСейчас(L) || {};
    if (!d) return '';
    if (c.iso && d === c.iso) return 'сегодня';
    if (c.iso && d === new Date(Date.parse(c.iso + 'T12:00:00Z') + 864e5).toISOString().slice(0, 10)) return 'завтра';
    return ДН_КР[new Date(d + 'T12:00:00Z').getUTCDay()] + ' ' + d.slice(8, 10) + '.' + d.slice(5, 7); };
  const сБольшой = (t) => (t ? t[0].toUpperCase() + t.slice(1) : t);
  function визитСловами(L, d, t) {
    if (!d && !t) return 'нет даты и времени';
    if (!d) return 'время ' + t + ', нет даты';
    return сБольшой(деньСловом(L, d)) + (t ? ' ' + t : ', нет времени');
  }
  const ЗВОНОК_КР = { exact: 'точно', prozvon: 'прозвон', before: 'позвонить перед выездом' };
  // приём сюда: «+2 ч», «с 11:00» — для строки «Выбрано: …»
  function зонаСловами() {
    const t = S.terr && S.terr.ok ? S.terr : null, мин = минимумДоВизита(S.terr);
    return [мин >= 120 ? (t && t.satelliteOf ? 'спутник' : t && (t.approval || t.far) ? 'за чертой' : 'приём') + ': +' + String(мин / 60).replace('.', ',') + ' ч' : '',
      t && t.earliest && t.earliest !== '10:00' ? 'с ' + t.earliest : ''].filter(Boolean).join(', ');
  }
  function строкаВыбрано(d, t) {
    const L = S.lead, з = зонаСловами();
    return [d || t ? 'Выбрано: ' : 'Не выбрано', d || t ? h('b', {}, [деньСловом(L, d), t].filter(Boolean).join(', ')) : '', з ? ' · ' + з : ''];
  }
  // шапка раскрытого «Визита»: окно клиента и «не успеваем» — строкой (сами подробности — ниже, у часов)
  function шапкаВизита(d, t) {
    const L = S.lead, w = окноКлиента(L);
    if (!w) return '';
    const c = клиентСейчас(L) || {}, дм = w.date && c.iso && w.date !== c.iso ? w.date.slice(8, 10) + '.' + w.date.slice(5, 7) + ', ' : '';
    const промах = !!промахОкна({ ...L, visit_date: d, visit_time: t, ...галочкиПрозвона() });
    return h('span', { class: 'st ' + (промах ? 'warn' : 'mut') }, h('span', { class: 'n mut', 'data-window': '1', title: 'Клиент назвал окно' + (w.text ? ': «' + w.text + '»' : '') + '. Срок — не время визита: визит не позже срока минус 30 минут, не раньше начала окна. В заявку не пишется' },
      'окно клиента: ' + дм + LC_EXTRACT.окноСловами(w)), промах ? ' · не успеваем' : '');
  }

  function render() {
    const L = S.lead, P = S.prep && S.prep.ok ? S.prep : null;
    const chk = (f) => S.checks.find((c) => c.field === f) || { ok: false, note: '' };
    const inp = (name, value, attrs = {}) => h('input', { 'data-f': name, value, ...attrs });
    const fld = (label, el, attrs) => h('label', { class: 'f', ...(attrs || {}) }, label, el);
    const sel = (name, list, value, onchange, empty) => h('select', { 'data-f': name, onchange },
      empty ? h('option', { value: '' }, empty) : null,
      ...(list || []).map((o) => h('option', { value: o.id, selected: o.id === value }, o.text)));
    const box = (cls, ...kids) => h('div', { class: 'box ' + cls }, svg(cls === 'ok' ? 'check' : 'warn'), h('div', { class: 'c' }, ...kids));
    const через = (...xs) => xs.filter(Boolean).join(' · ');
    // «+ второй номер», «+ посёлок / СНТ · домофон»: свёрнуто, пока пусто; есть значение — открыто само
    const скрытое = (key, label, открыто, ...kids) => {
      const w = h('div', { class: 'fz-open', 'data-open': key, hidden: !открыто }, ...kids);
      const b = h('button', { type: 'button', class: 'fz-more', 'data-more': key, hidden: открыто, 'aria-expanded': 'false', onclick: () => {
        S.открыто = { ...(S.открыто || {}), [key]: true }; w.hidden = false; b.hidden = true;
        const x = w.querySelector('input, select, textarea'); if (x) x.focus(); } }, label);
      return [b, w];
    };

    // --- шапка: «Новая заявка», имя · канал, база одним переключателем, «⋯» (Готовые, журнал, настройки), ✕
    const канал = S.conv && S.conv.account && S.conv.account.title, видКанала = LC_EXTRACT.канал(S.conv);
    // MAX: «MAX «бот»» / «MAX · номер «…»» (как значок канала в LeadChat), Авито — «Авито «канал»»
    const имяКанала = видКанала === 'max_user' ? 'MAX · номер' : видКанала === 'max_bot' ? 'MAX' : 'Авито';
    const sub = [L.name, канал ? имяКанала + ' «' + канал + '»' : видКанала !== 'avito' ? имяКанала : ''].filter(Boolean).join(' · ');
    const ph = h('div', { class: 'ph fm cz' },
      h('div', { class: 'top' },
        h('div', { class: 'ttl' }, h('div', { class: 't' }, 'Новая заявка'), sub ? h('div', { class: 'sub', title: sub }, sub) : ''),
        h('div', { class: 'seg', role: 'group', 'aria-label': 'В какую базу создать' }, ...DIRS.map(([id, text]) => h('button', {
          class: S.dir === id ? 'on' : '', 'data-dir': id, 'aria-pressed': S.dir === id ? 'true' : 'false', onclick: async () => {
            if (собираю || задачаИдёт(S.id)) return;                     // заявка уже создаётся в этой базе — базу не меняем
            keepEdits();
            // 2.0.7: база этого диалога — выбор оператора (по смыслу больше не переключаем). 2.1.1: только этого диалога — за каналом
            // (источником) база не запоминается: канал Авито ведёт любые направления
            S.dirChosen = true; S.dirHint = null;
            // выбор оператора по этому диалогу помним и после «Прочитать заново» / «Создать ещё одну» (новый разбор — новый S)
            try { const м = await store.get('dirChoice', {}); м[S.id] = { dir: id, at: Date.now() };
              for (const [k, v] of Object.entries(м)) if (Date.now() - ((v && v.at) || 0) > 7 * 864e5) delete м[k];
              await store.set('dirChoice', м); } catch (_e) { /* без памяти выбора */ }
            S.dir = id;
            S.lead = withSource(S.lead, S.conv, id);       // у каждой базы свои источники и ссылки
            await prepare();
          } }, text))),
        менюЕщё(),
        h('button', { class: 'ib', 'aria-label': 'Закрыть', title: 'Закрыть (Esc)', onclick: closePanel }, svg('close'))),
      // 2.0.7: база по смыслу — почему не та, что у канала (переключить обратно — кнопкой базы выше)
      S.dirAuto && !S.dirChosen ? h('div', { class: 'fz-dn ' + (S.dirAuto.назад ? 'warn' : 'info'), 'data-dir-note': '1' }, S.dirAuto.назад
        ? 'По смыслу — ' + dirName(S.dirAuto.to) + ' (' + S.dirAuto.работа + '), но там нет филиала в городе — ' + (S.dir ? 'оставил ' + dirName(S.dir) : 'выберите базу')
        : 'База по смыслу: ' + dirName(S.dirAuto.to) + ' — ' + S.dirAuto.работа + (S.dirAuto.from ? ' (канал ' + dirName(S.dirAuto.from) + ')'
          : видКанала !== 'avito' ? ' (диалог MAX: база — только по смыслу работы)' : ' (в названии канала базы нет)')) : '',
      // MAX: откуда партнёр, источник и город (диалог Авито этого клиента и как он найден) — или что их нет и время визита — по городу клиента
      видКанала === 'avito' ? '' : авитоДиалога(S.conv)
        ? h('div', { class: 'n mut', 'data-max-note': 'avito', 'data-found-by': авитоДиалога(S.conv).found_by || '' },
          'Диалог MAX: партнёр, источник и город — из диалога Авито этого клиента' + какНайден(авитоДиалога(S.conv)))
        : h('div', { class: 'n warn', 'data-max-note': 'none' }, 'Диалог MAX: партнёр, источник и город не определены — выберите источник вручную; время визита проверьте по городу клиента'),
      S.dirHint && !S.dirChosen ? h('div', { class: 'fz-dn warn', 'data-dir-note': '1' }, S.dirHint.белая
        ? 'По смыслу — ' + dirName(S.dirHint.dir) + ' (' + S.dirHint.работа + '), но белая заявка в БТ не создаётся — оставил ' + dirName(S.dirHint.from)
        : 'Похоже на ' + dirName(S.dirHint.dir) + ' (' + S.dirHint.работа + '): по регламенту сначала согласуйте с филиалом ' + dirName(S.dirHint.from) + ', откажет — выберите ' + dirName(S.dirHint.dir)) : '');

    // --- «Всё есть — проверьте и создайте» / «Осталось N: …» — заполнит обновитьСтатус()
    const body = [h('div', { class: 'cz-st mut', 'data-status': '0' })];
    // 2.1.7: аварийный режим — переписку разобрали правилами без сервера: суть, вид работ и согласование — проверить самому
    if ((S.checks || []).some((c) => c.field === 'ai' && c.note === БЕЗ_СЕРВЕРА)) body.push(box('warn', h('div', { 'data-offline': '1' }, h('b', {}, 'Без ИИ. '),
      БЕЗ_СЕРВЕРА + ': суть работы, вид работ и нужно ли согласование — проверьте сами.')));
    if (S.newer) body.push(h('div', { class: 'box warn' }, svg('warn'), h('div', { class: 'c' },
      h('div', {}, h('b', {}, 'Клиент написал ещё. '), 'Ваши правки сохранены. Перечитать переписку?'),
      h('div', { class: 'row pa' }, h('button', { class: 'sm pri', onclick: () => collect(null, true) }, 'Прочитать заново'),
        h('button', { class: 'sm', onclick: () => { S.newer = false; render2keep(); } }, 'Оставить как есть')))));
    const bb = ботBox();
    if (bb) body.push(bb);
    if (S.created) body.push(box('ok', 'По этому диалогу заявка уже создана' + (S.created.id ? ' — № ' + S.created.id : '') + (S.created.изLC ? ' (из LeadChat)' : '') + '. ',
      S.created.url ? h('a', { href: S.created.url, target: '_blank', rel: 'noopener' }, 'Открыть в CRM') : ''));
    if (S.prep && !S.prep.ok) body.push(h('div', { class: 'box bad', 'data-prep-err': '1' }, svg('warn'), h('div', { class: 'c' }, 'CRM: ' + S.prep.error,
      h('div', { class: 'row pa' }, h('button', { class: 'sm', title: 'Ещё раз открыть форму CRM (разбор переписки не повторяется)', onclick: () => prepare() }, 'Повторить')))));
    const R = P ? историяКлиента() : null;

    // Пример карточки клиента с телефоном из диалога.
    const pc = chk('phone');
    const ещё = (L.phones_extra || []).length > 0 || !!(S.открыто && S.открыто.phone2);
    const found = P ? P.found || [] : [];
    const безИмени = !/[a-zа-яё]/i.test(L.name || '') && !(P && P.customer && P.customer.id);
    const дубли = !!(S.lcDup && (S.lcDup.rows || []).length);
    const заявок = (n) => n + (n === 1 ? ' заявка' : n < 5 ? ' заявки' : ' заявок');
    body.push(секция('client', {
      метка: 'Клиент', значение: через(fmtPhone(L.phone) || (L.phone ? L.phone : 'нет номера'), L.name),
      пояснение: через(P ? (P.customer && P.customer.id ? 'есть в CRM' + (found.length ? ': ' + заявок(found.length) : '') : found.length ? 'номер в базах: ' + заявок(found.length) : 'новый клиент') : '',
        pc.note ? 'номер ' + кратко(pc.note.replace(/ — .*$/, ''), 40) : '', безИмени ? 'имени нет' : '', дубли ? 'пишет и в другом диалоге' : ''),
      проблема: String(L.phone || '').length !== 10 || !!L.phone_warn || (L.phones_notes || []).length > 0 || !!(P && ((P.customer && P.customer.count > 1) || (P.unchecked || []).length)) || безИмени || дубли,
      шапка: pc.note ? h('span', { class: 'st ' + (pc.ok ? 'ok' : 'warn'), title: pc.note }, pc.note) : '',
    },
    fld('Телефон', inp('phone', fmtPhone(L.phone), { inputmode: 'tel', autocomplete: 'off', onchange: async () => {
      keepEdits();                       // другой номер — заново проверить его по всем базам
      if (S.lead.phone.length === 10) await prepare(P && P.cityId ? { cityId: P.cityId, applId: P.applId } : {});
    } })),
    // связь карточки LeadChat под сомнением или номер из голосового — сверить; «номер сверил» — надписью главной кнопки
    L.phone_warn ? h('div', { class: 'box warn' }, svg('warn'), h('div', { class: 'c' }, h('div', {}, L.phone_warn),
      L.phone_risky ? h('div', { class: 'n mut' }, L.phone_ok ? 'Номер сверен с клиентом ✓' : 'Сверили с клиентом — кнопка внизу «Номер … сверил — создать»') : '')) : '',
    ...(L.phones_notes || []).map((t) => h('div', { class: 'n warn' }, t)),
    // номера, которые LeadChat ещё не подтвердил, — в заявку только по нажатию
    ...(L.phones_pending || []).map((x) => h('div', { class: 'n mut' }, fmtPhone(x.phone) + ' — ' + x.note + ' ',
      h('button', { class: 'sm', style: SMALL, title: 'В «Доп. телефон»', onclick: () => { keepEdits(); const был = S.lead.phones_extra || []; if (!был.includes(x.phone)) S.lead.phones_extra = [...был, x.phone].slice(-3); render(); } }, 'Подставить'))),
    ...(P ? (P.unchecked || []).map((u) => h('div', { class: 'n warn' }, dirName(u.dir) + ': номер не проверен — ' + u.error)) : []),
    P && P.customer && P.customer.count > 1 ? h('div', { class: 'n bad' }, 'В CRM несколько клиентов с этим номером (' + P.customer.count + ') — автоматически не создам, заведите вручную.') : '',
    // история клиента — свёрнута; раскрыта, если по ней регламент что-то требует
    found.length ? h('details', { class: 'fz-hist', open: P.live || (R && (R.approval || R.action || R.why)) ? '' : undefined },
      h('summary', {}, 'История клиента: ' + заявок(found.length)),
      ...found.slice(0, 6).map((r) => h('div', {}, dirName(r.dir) + ' № ' + r.id + ' — «' + r.status + '»' + (r.when || r.closedAt ? ', ' + (r.closedAt || r.when) : '') + (r.appl ? ', ' + r.appl : '') + ' ',
        h('a', { href: r.url, target: '_blank', rel: 'noopener' }, 'Открыть'))),
      ...(R ? [R.approval ? h('div', { class: 'n warn' }, 'По регламенту: ' + R.approval + '. Тип «' + R.type + '».') : '',
        ...R.notes.map((t) => h('div', { class: 'n ' + (R.action ? 'warn' : 'mut') }, t))] : [])) : '',
    fld('Имя (как в LeadChat)', inp('name', L.name, { autocomplete: 'off' })),
    // в имени одни цифры (№ заявки) или пусто — имени нет (регламент: «не уточнил имя клиента» — штраф 200 ₽)
    // (клиент уже есть в CRM — имя берётся из его карточки, как и в crm.create)
    безИмени ? h('div', { class: 'n warn', title: 'Почему: не уточнил имя клиента — штраф 200 ₽ (регламент)' }, 'Имени нет — уточните у клиента') : '',
    P && P.customer && P.customer.id && P.customer.count === 1 ? h('div', { class: 'n mut' }, 'Клиент есть в CRM ' + dirName(S.dir) + ' — имя возьмётся из его карточки') : '',
    // регламент: «если клиент диктует дополнительный номер — в следующую графу „Телефон“ как дополнительный»
    ...скрытое('phone2', '+ второй номер клиента', ещё,
      fld('Доп. телефон' + ((L.phones_extra || []).length ? ' — ещё номер клиента' : ''), inp('phone2', (L.phones_extra || []).map(fmtPhone).join(', '),
        { inputmode: 'tel', autocomplete: 'off', placeholder: 'если клиент дал второй номер' }))),
    дублиLCBox()));

    // --- Адрес: «Москва, Мира 5, кв 2 · подъезд 1, этаж 4 · карта подтвердила дом»
    const ac = chk('address');
    const нп = !!(L.addr.settlement || L.addr.intercom) || !!(S.открыто && S.открыто.settlement);
    const a = L.addr || {};
    const нетАдреса = !(a.street || a.settlement);
    const T0 = S.terr && S.terr.ok ? S.terr : null;
    const терВАдресе = !!(S.terr && !S.terr.ok);                     // дом не найден / карта не ответила — это про адрес
    const ai = S.addrAI;
    const аиРешить = !!(ai && ai.ok && ((ai.best && другойАдрес(L.addr, ai.best)) || (!ai.best && ai.echo)));
    const домКлиента = !!(P && P.customer && P.customer.id && !нетАдреса && !String(a.building || '').trim());
    const адресLCждёт = !!(S.адресLC && S.адресLC.text && !S.addrAsked);
    body.push(секция('addr', {
      метка: 'Адрес', значение: нетАдреса ? 'нет адреса' : через([P && P.cityText ? городКратко(P.cityText) : L.city, a.settlement, [a.street, a.building].filter(Boolean).join(' '), a.office ? 'кв ' + a.office : ''].filter(Boolean).join(', ')),
      пояснение: через(a.entrance ? 'подъезд ' + a.entrance : '', a.floor ? 'этаж ' + a.floor : '', S.terr && !S.terr.ok && S.terr.mismatch ? 'дом не найден на карте' : ac.note ? кратко(ac.note.replace(/^из карточки LeadChat · /, ''), 48) : ''),
      проблема: нетАдреса || !!(P && !P.cityId) || прошлыйАдрес(L) || !!L.addr_warn || терВАдресе || домКлиента || адресLCждёт || !!(L.addr_echo && !(S.addrAI && S.addrAI.echo)) || аиРешить,
      шапка: S.terr && !S.terr.ok && S.terr.mismatch
        ? h('span', { class: 'st warn', title: S.terr.error || '' }, 'дом не найден на карте')
        : L.addr_warn ? h('span', { class: 'st warn', title: L.addr_warn }, 'не точный: ' + кратко(L.addr_warn, 60))
          : ac.note ? h('span', { class: 'st ' + (ac.ok ? 'ok' : 'warn'), title: ac.note }, ac.note.replace(/^из карточки LeadChat · /, '')) : '',
    },
    P ? fld('Город в CRM', sel('cityId', P.cities, P.cityId, async (e) => { keepEdits(); await prepare({ cityId: e.target.value }); }, 'выберите город…')) : '',
    P && !P.cityId ? h('div', { class: 'n warn' }, P.cityClosed ? 'Филиал «' + P.cityClosed + '» в CRM помечен закрытым («-») — сам не выбираю. Уточните, куда передать заявку, и выберите город'
      : 'Город «' + (L.city || '—') + '» не нашёлся в списке CRM — выберите') : '',
    h('div', { class: 'cz-addr' }, fld('Улица', inp('street', a.street, { autocomplete: 'off' })), fld('Дом', inp('building', a.building, { autocomplete: 'off' })),
      fld('Кв', inp('office', a.office, { autocomplete: 'off', 'aria-label': 'Кв / офис' })), fld('Подъезд', inp('entrance', a.entrance, { autocomplete: 'off' })),
      fld('Этаж', inp('floor', a.floor, { autocomplete: 'off' }))),
    ...скрытое('settlement', '+ посёлок / СНТ · домофон', нп,
      fld('Нас. пункт (село, СНТ)', inp('settlement', a.settlement, { placeholder: 'если не в самом городе', autocomplete: 'off' })),
      h('label', { class: 'ck' }, h('input', { type: 'checkbox', 'data-f': 'intercom',
        checked: Object.prototype.hasOwnProperty.call(a, 'has_intercom') ? a.has_intercom === true : !!a.intercom,
        indeterminate: Object.prototype.hasOwnProperty.call(a, 'has_intercom') && a.has_intercom === null,
        title: a.has_intercom === null ? 'Клиент не указал, есть ли домофон. Сохранённое значение в CRM не меняем.' : '',
        onchange: (e) => { e.target.indeterminate = false; S.lead.addr.has_intercom = !!e.target.checked; S.lead.addr.intercom = !!e.target.checked; }
      }), h('span', {}, 'Домофон есть'))),
    // адрес первым написал оператор — ИИ его не взял; адреса других диалогов клиента — только по нажатию
    L.addr_echo && !(S.addrAI && S.addrAI.echo) ? h('div', { class: 'n warn' }, 'Не взят адрес от оператора «' + L.addr_echo + '» — его первым написал оператор, это не адрес клиента') : '',
    ...(L.addr_other || []).filter((x) => другойАдрес(L.addr, x)).map((x) => h('div', { class: 'n mut' }, 'Адрес из другого диалога клиента: ' + x.line + ' ',
      h('button', { class: 'sm', style: SMALL, onclick: () => {
        applyAddr({ ...x, house: x.building }, 'адрес из другого диалога клиента — подставлен вручную', 'адрес из другого диалога клиента — сверьте', true);
        S.terr = null; prepare(); } }, 'Подставить'))),
    // 2.1.1: адрес из прошлого обращения — не создаём, пока оператор не спросит клиента (штраф КП 2684667: мастер поехал на старый адрес).
    // 2.3: «Клиент подтвердил: адрес тот же» — надписью главной кнопки (одно нажатие — подтвердить и создать)
    прошлыйАдрес(L) ? h('div', { class: 'box warn', 'data-addr-prev': '1' }, svg('warn'), h('div', { class: 'c' },
      прошлыйКарточки(L) ? h('div', {}, h('b', {}, 'Адрес из прошлого обращения клиента'), ' — в этом диалоге его не называли. Клиент мог переехать (офис, студия, дача): спросите, куда нужен мастер сейчас.')
        : h('div', {}, h('b', {}, 'Тип «' + типЗаявки() + '» — адрес сверяют с клиентом'), ' (регламент): в этом диалоге его не называли. Спросите, куда нужен мастер сейчас.'),
      h('div', { class: 'row', style: 'gap:6px;flex-wrap:wrap;margin-top:4px' },
        h('button', { class: 'sm', onclick: () => кПолю(panel.querySelector('[data-f="street"]')) }, 'Другой адрес — вписать')))) : '',
    домКлиента ? h('div', { class: 'n warn' }, 'Номер дома — клиент уже есть в CRM: без дома в заявке останется его прежний адрес') : '',
    addrBox(),
    терВАдресе ? terrBox() : '',
    адресLCBox(),
    // 2.2.3: сомнение в адресе — уведомлением здесь, в заявку не пишется (создал — значит проверил)
    L.addr_warn ? h('div', { class: 'box warn', role: 'alert', 'data-addr-warn': '1' }, svg('warn'), h('div', { class: 'c' },
      h('div', {}, h('b', {}, 'Адрес не точный'), ' — ' + L.addr_warn + '.'),
      h('div', { class: 'mut' }, 'Проверьте с клиентом. В заявку это не пишется.'))) : ''));

    // --- Визит: «Сегодня 15:40 · ближайшее по регламенту · точно»; раскрыто — дни, часы, минуты, «как договорились»
    const tc = chk('time');
    const вп0 = визитПроблема(L);
    const ccOn = !!(L.call_check && !(L.call_before_visit || наДваДня(L))), cbOn = !!(L.call_before_visit || наДваДня(L));
    const сег = быстрыеДни(L), часы = ЧАСЫ_СЕТКИ;
    const звонок = режимЗвонка(ccOn, cbOn);
    const срочно = L.urgent_manual ? !!L.urgent : срочноПоСловам(L);
    const далеко = L.far_ride_manual && L.far_ride !== undefined ? L.far_ride : !!(S.terr && S.terr.ok && S.terr.far);
    const авто = визитАвто(L) ? L.visit_auto : null;
    const tw0 = terrTimeWarn();
    const визитЕщё = !!(S.открыто && S.открыто.visitmore);
    body.push(секция('visit', {
      метка: 'Визит', значение: h('span', { 'data-visit-val': '1' }, визитСловами(L, L.visit_date || '', L.visit_time || '')),
      пояснение: h('span', { 'data-visit-note': '1' }, визитСтатус(tc, L.visit_date, L.visit_time), h('span', { 'data-visit-call': '1' }, ' · ' + ЗВОНОК_КР[звонок]),
        срочно ? ' · срочная' : '', далеко ? ' · дальний выезд' : ''),
      проблема: !!(вп0.block || вп0.warn) || tw0.style.display !== 'none' || !!(авто && авто.завтра) || !!(L.call_words && !ccOn && !cbOn) || (наДваДня(L) && !cbOn),
      шапка: h('span', { 'data-visit-head': '1' }, шапкаВизита(L.visit_date || '', L.visit_time || '')),
    },
    h('div', { class: 'cz-days', role: 'group', 'aria-label': 'День визита' },
      ...сег.map(([iso, t]) => h('button', { type: 'button', class: 'fz-qb', 'data-day': iso, 'aria-pressed': 'false', onclick: () => вПоле('visit_date', iso) }, t)),
      h('button', { type: 'button', class: 'fz-qb soft', 'data-day': 'cal', 'aria-pressed': 'false', title: 'Другой день — календарь; там же поля даты и времени (своё время до минуты), «Срочная», «Дальний выезд»', onclick: (e) => {
        e.stopPropagation();                                       // щелчок не должен закрыть только что открытый календарь
        const w = panel.querySelector('[data-open="visitmore"]'); if (w) w.hidden = false;
        S.открыто = { ...(S.открыто || {}), visitmore: true };
        const d = panel.querySelector('[data-f="visit_date"]'); if (d) { d.focus({ preventScroll: true }); d.click(); } } }, 'Ещё…')),
    h('div', { class: 'cz-hours', role: 'group', 'aria-label': 'Час визита' },
      ...часы.map((ч) => h('button', { type: 'button', class: 'fz-qb', 'data-hour': ч, 'aria-pressed': 'false', onclick: () => поставитьЧас(ч) }, ч))),
    h('div', { class: 'cz-vrow' },
      h('div', { class: 'fz-seg cz-min', role: 'group', 'aria-label': 'Минуты' },
        ...['00', '30'].map((м) => h('button', { type: 'button', 'data-min': м, 'aria-pressed': 'false', onclick: () => поставитьМинуты(м) }, ':' + м))),
      h('div', { class: 'fz-seg cz-call', role: 'radiogroup', 'aria-label': 'Как договорились', 'data-call-seg': '1', onkeydown: (e) => {
        if (!/^Arrow(Left|Right|Up|Down)$/.test(e.key)) return;
        e.preventDefault();
        const i = ЗВОНОК.findIndex(([k]) => k === (e.target.getAttribute && e.target.getAttribute('data-call')));
        if (i < 0) return;
        const k = ЗВОНОК[(i + (/Left|Up/.test(e.key) ? 2 : 1)) % 3][0];
        выбратьЗвонок(k);
        const b = panel.querySelector('[data-call="' + k + '"]'); if (b) b.focus();
      } }, ...ЗВОНОК.map(([k, t, title]) => h('button', { type: 'button', role: 'radio', 'data-call': k, title, class: k === звонок ? 'on' : '',
        'aria-checked': k === звонок ? 'true' : 'false', tabindex: k === звонок ? '0' : '-1', onclick: () => выбратьЗвонок(k) }, t)))),
    h('div', { class: 'cz-sel', 'data-visit-sel': '1' }, ...строкаВыбрано(L.visit_date || '', L.visit_time || '')),
    // галочки — для заявки и правил (скрыто): переключатель выше ставит их, как щелчок оператора
    h('div', { class: 'fz-hide', 'aria-hidden': 'true' },
      h('input', { type: 'checkbox', 'data-f': 'call_check', tabindex: '-1', checked: ccOn,
        onchange: (e) => { S.lead.call_marks_manual = true; if (e.target.checked) { const o = panel.querySelector('[data-f="call_before_visit"]'); if (o) o.checked = false; } автоПоЗвонку(); } }),
      h('input', { type: 'checkbox', 'data-f': 'call_before_visit', tabindex: '-1', checked: cbOn,
        onchange: (e) => { S.lead.call_marks_manual = true; if (e.target.checked) { const o = panel.querySelector('[data-f="call_check"]'); if (o) o.checked = false; } автоПоЗвонку(); } })),
    tw0,
    закрепФорма(),
    h('div', { 'data-visit-auto': '1', class: 'cz-notes' }, ...строкиБлижайшего(L.visit_date || '', L.visit_time || '')),
    h('div', { 'data-call-hint': '1', class: 'cz-notes' }, ...строкиЗвонка(L.visit_date || '', L.visit_time || '', ccOn, cbOn)),
    // «Ещё…»: поля даты и времени (своё время до минуты — окно выбора времени по щелчку), часы города, «Срочная», «Дальний выезд»
    h('div', { class: 'fz-open', 'data-open': 'visitmore', hidden: !визитЕщё },
      часыГорода(L),
      h('div', { class: 'g2' },
        fld('Дата', inp('visit_date', L.visit_date, { type: 'date', 'data-today': L.clock ? клиентСейчас(L).iso : '', 'aria-label': 'Дата визита', oninput: обновитьВизит, onchange: обновитьВизит })),
        fld('Время', inp('visit_time', L.visit_time, { type: 'time', ...атрибутыВремени(L), 'aria-label': 'Время визита', oninput: обновитьВизит, onchange: обновитьВизит }),
          { title: L.clock ? 'Сейчас у клиента ' + клиентСейчас(L).now + (L.city ? ' (' + L.city + ')' : '') + ' — ' + L.clock.how : '' })),
      h('div', { class: 'cks' },
        // 2.0.9: «Срочная» — сразу при создании (раньше — только действием после). Клиент пишет «срочно» — отмечено, снять можно
        h('label', { class: 'ck', title: 'Срочная: клиент ждёт мастера в течение часа (спутник — 2 ч)' }, h('input', { type: 'checkbox', 'data-f': 'urgent',
          checked: срочно, onchange: (e) => { S.lead.urgent_manual = true; S.lead.urgent = e.target.checked; } }), h('span', {}, 'Срочная')),
        // щёлкнул оператор — его выбор сразу в заявку (far_ride_manual): перерисовка без keepEdits (ответ поиска адреса) его не теряет
        h('label', { class: 'ck', title: 'Ставится само, если по карте адрес вне территории филиала' }, h('input', { type: 'checkbox', 'data-f': 'far_ride',
          checked: далеко, onchange: (e) => { S.lead.far_ride_manual = true; S.lead.far_ride = e.target.checked; } }), h('span', {}, 'Дальний выезд'))))));

    // --- Работа: «Сантехника · Смесители/Сифоны · Впервые»
    const нужно = (S.check && S.check.approval) || terrReason() || repeatReason();
    // «не наш профиль» по регламенту — тоже «проверьте», а не зелёное «без согласования» (филиал спросить обязательно)
    const проверить = !нужно && S.check && (S.check.maybe || S.check.refuse);
    if (P && P.cityId) {
      const keep = S.keepSel || {};
      const subNow = keep.subId && (P.sub || []).some((o) => o.id === keep.subId) ? keep.subId : P.subId;
      const typeNow = keep.type || (R && R.type) || P.type || 'Впервые';
      const typeInp = h('input', { type: 'hidden', 'data-f': 'type', value: typeNow,
        onchange: (e) => { S.keepSel = { ...(S.keepSel || {}), type: e.target.value }; render2keep(); } });
      const c = S.check, нет = c && !c.busy ? (c.results || []).filter((x) => !x.done).length : 0;
      const стРаботы = !c ? '' : c.busy ? 'сверяем с регламентом…' : !c.ok ? 'регламент не проверен' : нет ? 'уточнить: ' + нет : 'по регламенту ✓';
      const текст = (list, id) => ((list || []).find((o) => o.id === id) || {}).text || '';
      const видПроверьте = !!(P.applHow && /проверьте|не выбрал/.test(P.applHow)) || !!(P.subHow && P.sub && P.sub.length > 1 && /проверьте/.test(P.subHow)) || !!P.subDiag;
      body.push(секция('work', {
        метка: 'Работа', значение: через(текст(P.appl, P.applId) || 'вид работ не выбран', текст(P.sub, subNow)),
        пояснение: через(typeNow, стРаботы, видПроверьте ? 'вид работ — проверьте' : ''),
        проблема: нет > 0 || !!(c && !c.busy && c.refuse) || видПроверьте || !P.applId,
        шапка: стРаботы ? h('span', { class: 'st ' + (c.busy ? 'mut' : нет ? 'warn' : 'ok') }, стРаботы) : '',
      },
      h('div', { class: P.sub && P.sub.length ? 'g2' : '' },
        fld('Вид работ', sel('applId', P.appl, P.applId, async (e) => { keepEdits(); await prepare({ cityId: P.cityId, applId: e.target.value }); })),
        P.sub && P.sub.length ? fld('Вид услуг', sel('subId', P.sub, subNow, (e) => { S.keepSel = { ...keep, subId: e.target.value }; runChecklist(); })) : ''),
      P.applHow ? h('div', { class: 'n ' + (/проверьте|не выбрал/.test(P.applHow) ? 'warn' : 'mut'), title: P.applHow }, 'Вид работ: ' + кратко(P.applHow, 70)) : '',
      P.subHow && P.sub && P.sub.length > 1 ? h('div', { class: 'n ' + (/проверьте/.test(P.subHow) ? 'warn' : 'mut') }, 'Вид услуг: ' + P.subHow) : '',
      P.subDiag ? h('div', { class: 'n warn', title: P.subDiag }, 'Вид услуг: в CRM нет списка для этого вида работ') : '',
      checkBox(),
      c && c.operator_review && !c.hard_block ? h('div', { class: 'n warn' }, 'Проверка оператора: ' + c.operator_review) : '',
      c && c.reviewed_policy ? h('div', { class: 'n mut', 'data-policy-version': c.policy_version,
        title: c.geography && c.geography.satellite_of ? c.geography.physical_city + ' — спутник ' + c.geography.satellite_of + '; общие правила приёма по видам работ' : '' },
        'Регламент: ' + c.policy_version + (c.geography && c.geography.acceptance_city ? ' · приём: ' + c.geography.acceptance_city : ' · общие правила с помощником')) : '',
      неПрофильBox(),
      typeInp,
      h('div', { class: 'tseg', role: 'group', 'aria-label': 'Тип заявки' }, ...['Впервые', 'Повтор', 'Гарантия'].map((t) => h('button', {
        type: 'button', class: t === typeNow ? 'on' : '', 'aria-pressed': t === typeNow ? 'true' : 'false',
        onclick: () => { typeInp.value = t; typeInp.dispatchEvent(new Event('change')); } }, t)))));

      // --- Филиал: «Москва · без согласования» / «нужно согласование»; раскрыто — территория и согласование одной кнопкой
      const t = S.tg, отв = S.tgReplies || [];
      const куда = S.tgSent ? sentList(S.tgSent).map((x) => '«' + x.title + '»').join(', ') : '';
      const статус = S.tgSent ? (отв.length ? 'филиал ответил' : 'отправлено в ' + куда + ' · ждём ответ') : нужно ? 'нужно согласование' : проверить ? 'проверьте согласование'
        : S.check && !S.check.busy ? 'без согласования' : 'сверяем с регламентом…';
      const тер = T0 ? через(T0.inMap ? '' : '', T0.hours ? 'принимаем за ' + T0.hours + ' ч' : '', T0.earliest && T0.earliest !== '10:00' ? 'не раньше ' + T0.earliest : '', T0.far ? 'дальний выезд' : '')
        : S.terr ? 'территория: ' + кратко(S.terr.error || 'не определилась', 40) : 'территорию проверяем…';
      const терПроверьте = !!(T0 && (!T0.hours || T0.noMap));
      const короткое = согласованиеКратко();
      body.push(секция('tg', {
        метка: 'Филиал', значение: через(T0 && T0.branch ? T0.branch : городКратко(P.cityText), статус),
        пояснение: отв.length ? 'ответ: «' + кратко(отв[отв.length - 1].text, 60) + '»' : тер,
        проблема: (!!нужно && !S.tgSent) || !!проверить || !!(t && (t.chats || t.error || t.busy)) || терПроверьте,
        шапка: нужно && !S.tgSent ? h('span', { class: 'st warn', title: нужно }, кратко(нужно, 60)) : S.tgSent ? h('span', { class: 'st ' + (отв.length ? 'ok' : 'warn') }, отв.length ? 'есть ответ' : 'ждём ответ')
          : проверить ? h('span', { class: 'st warn' }, 'проверьте') : '',
      },
      T0 ? terrBox() : '',
      короткое || approvalBox() || ''));
    }

    // --- Сообщение: последнее слово клиента; ↻ — прочитать диалог заново
    const посл = последнееКлиента(), голос = L.voice && L.voice.note ? L.voice.note : '';
    body.push(h('div', { class: 'cz-row cz-msg', 'data-sec': 'msg' },
      h('div', { class: 'cz-l' }, 'Сообщение'),
      h('div', { class: 'cz-v' }, h('div', { class: 'cz-v1', title: посл ? посл.text : '' }, посл ? '«' + кратко(посл.text, 90) + '»' : голос ? 'голосовое' : 'от клиента пока ничего'),
        // голосовое клиента — здесь же: прослушайте / ещё расшифровывается (↻ справа — прочитать заново)
        голос ? h('div', { class: 'cz-v2 warn', 'data-voice': '1', title: 'Голосовое: ' + голос }, 'Голосовое: ' + голос) : посл && посл.note ? h('div', { class: 'cz-v2' }, посл.note) : ''),
      h('button', { type: 'button', class: 'cz-ed', 'aria-label': 'Прочитать диалог заново', title: 'Прочитать диалог заново (клиент дописал, LeadChat проверил адрес)', 'data-redo': '1', onclick: () => collect(null, true) }, svg('redo'))));

    // Обязательные сведения объявления видны рядом с основным комментарием, отдельно от редких настроек источника.
    const adUrl = объявлениеДиалога(S.conv).url || '';
    body.push(секция('advertiser', {
      метка: 'Объявление', значение: текстПодписи(L), пояснение: пояснениеПодписи(L),
      проблема: !!(L.ad_identity_required && !L.ad_identity), класс: подписьПроверить(L) ? 'ad-review' : '',
      заголовок: 'Имя мастера и аккаунт объявления',
    },
    fld('Имя мастера из объявления / название аккаунта', inp('ad_identity', L.ad_identity || '', { maxlength: 160, autocomplete: 'off',
      placeholder: 'Например: Алексей или КомпХелп КП', oninput: правкаПодписи })),
    fld('Каким именем представились клиенту', inp('introduced_as', L.introduced_as || '', { maxlength: 160, autocomplete: 'off',
      placeholder: 'Если называли имя в диалоге', oninput: правкаПодписи })),
    h('div', { class: 'n mut' }, 'Имя / аккаунт объявления и названное клиенту имя добавятся к технике и проблеме в основной комментарий CRM.'),
    подписьПроверить(L) ? h('div', { class: 'n warn', 'data-advertiser-fallback': '1' }, 'Объявление не прочитано. Подставлен канал LeadChat — сверьте имя мастера и при необходимости исправьте.') : '',
    /^https:\/\/(?:www\.|m\.)?avito\.ru\//i.test(adUrl) ? h('a', { class: 'ad-link', href: adUrl, target: '_blank', rel: 'noopener noreferrer' }, svg('link'), 'Открыть объявление') : ''));

    // --- Комментарий: текст — в поле; что добавится само (служебное, источник, отзыв) — строкой под ним, ✎ — источник и ссылка
    const src = LC_LINKS.find(L.partner_note, S.dir, L.partner);
    const ссылка = src || (S.autoLink && S.autoLink.ok && S.autoLink.short) || ссылкаКанала(S.conv);
    const полный = h('textarea', { 'data-f': 'comment', value: L.comment, hidden: true, 'aria-hidden': 'true', tabindex: '-1' });
    body.push(h('div', { class: 'cz-cm', 'data-sec': 'comment' },
      h('label', { class: 'f', for: 'lcz-cm' }, 'Комментарий'),
      полный,
      h('textarea', { id: 'lcz-cm', 'data-fx': 'comment-text', 'aria-label': 'Комментарий для CRM', value: текстКомментария(L.comment), rows: 3,
        oninput: (e) => { полный.value = собратьКомментарий(e.target.value, полный.value); } })));
    // --- Источник и отзыв: свёрнуто в строку «Добавится само: …»; нет ссылки для отзыва / партнёр не найден — раскрыто
    body.push(секция('src', {
      метка: 'Добавится само', класс: 'lite',
      значение: h('span', { class: 'fz-tags', 'data-cm-tags': '1' }, ...служебныеЧипы(L).flatMap((x, i) => [i ? ', ' : '', x])),
      пояснение: '',
      проблема: (!ссылка && !(S.autoLink && S.autoLink.busy)) || !!(L.partner && P && !P.partnerFound),
      заголовок: 'Источник и отзыв',
      шапка: L.partner && P ? h('span', { class: 'st ' + (P.partnerFound ? 'ok' : 'warn') }, 'партнёр ' + L.partner + (P.partnerFound ? ' найден' : ' не найден в CRM')) : '',
    },
    h('div', { style: 'display:grid;grid-template-columns:110px minmax(0,1fr);gap:8px;align-items:end' },
      fld('Источник', inp('partner_note', L.partner_note, { autocomplete: 'off', onchange: (e) => {
        // другой источник — другая ссылка для отзыва в комментарии
        const ta = panel.querySelector('[data-f="comment"]');
        const s2 = LC_LINKS.find(e.target.value, S.dir, S.lead.partner);
        ta.value = linkLines(ta.value, s2, LC_LINKS.isWhite(S.lead.partner, s2));
        S.lead.partner_note = e.target.value.trim();
        // «белый» — по тому, что вписал оператор: «Белый Б6» — белый, «С74» — нет (прежняя отметка разбора не держится)
        S.lead.partner_note_white = белыйИсточник(S.lead.partner_note);
        const rv = panel.querySelector('[data-f="review"]');
        if (rv && !S.lead.review_set) rv.checked = отзывНужен(S.lead.partner, s2, S.lead.partner_note);
        render2keep();
      } })),
      h('div', { class: 'f' }, 'Ссылка для отзыва', src ? h('a', { class: 'lnk', href: src.url, target: '_blank', rel: 'noopener', title: 'Ссылка для отзыва' + (src.partner ? ' (партнёр ' + L.partner + ')' : '') + ': ' + src.url }, svg('link'),
        src.url.replace(/^https?:\/\//, ''))
        : autoLinkEl(L))),
    h('label', { class: 'ck' }, h('input', { type: 'checkbox', 'data-f': 'review',
      checked: L.review || LC_LINKS.requiresReview(L.partner), disabled: LC_LINKS.requiresReview(L.partner),
      onchange: () => { S.lead.review_set = true; } }), 'Запрос отзыва')));

    const идёт = задачаИдёт(S.id);
    // после создания — отписать, как чатеры: «№ код» в «Авито-Чаты» и номер ответом на своё согласование. 2.3 — одной строкой над кнопкой
    const код = кодАккаунта(L);
    // «№ создал» — только когда филиал уже ответил на согласование (его условия); до ответа писать некому
    const согл = (S.tgReplies || []).length ? sentList(S.tgSent).slice(-1) : [];
    const pf = h('div', { class: 'pf fm cz' },
      h('div', { class: 'post' },
        код ? h('label', { class: 'ck' }, h('input', { type: 'checkbox', 'data-post': 'avito', checked: S.postAvito !== false, onchange: (e) => { S.postAvito = e.target.checked; } }),
          h('span', {}, 'После создания: «' + текстАвито('№', код, S.dir) + '» в «Созданные с Авито»'))
          : h('div', { class: 'n warn', 'data-post-none': 'avito' }, нетКода(S.conv)),
        согл.length ? h('label', { class: 'ck' }, h('input', { type: 'checkbox', 'data-post': 'reply', checked: S.postReply !== false, onchange: (e) => { S.postReply = e.target.checked; } }),
          h('span', {}, 'Филиал ответил — после создания ответить ему «№ создал» в ' + согл.map((x) => '«' + (x.title || 'чат') + '»').join(', '))) : ''),
      // подтверждения — галочками, как раньше (их читают readForm / createNow / CRM); ставит их главная кнопка
      h('div', { class: 'fz-hide', 'aria-hidden': 'true' },
        h('input', { type: 'checkbox', 'data-f': 'phoneOk', tabindex: '-1', checked: !!L.phone_ok }),
        h('input', { type: 'checkbox', 'data-f': 'allowWhite', tabindex: '-1', checked: !!S.allowWhite, onchange: (e) => { S.allowWhite = e.target.checked; } }),
        h('input', { type: 'checkbox', 'data-f': 'allowNew', tabindex: '-1', checked: !!(S.подтв && S.подтв.allowNew) }),
        h('input', { type: 'checkbox', 'data-f': 'allowLive', tabindex: '-1', checked: !!(S.подтв && S.подтв.allowLive) }),
        h('input', { type: 'checkbox', 'data-f': 'allowBot', tabindex: '-1', checked: !!(S.подтв && S.подтв.allowBot) })),
      главнаяБлок(),
      идёт ? h('div', { class: 'n mut', 'data-job-hint': '1' }, МОЖНО_УЙТИ) : '');
    // перерисовка этой же формы (ответы фона: регламент, ссылка, адрес, ответы филиала) — прокрутка и курсор в поле остаются на месте
    const былаФорма = формаЭтого(), pb0 = былаФорма ? panel.querySelector('.pb') : null, прокрутка = pb0 ? pb0.scrollTop : 0;
    const фок = былаФорма ? чейФокус(root.activeElement) : null;
    const первый = !S.показан; S.показан = true;
    if (первый && S.id) ОТВЕТЫ.delete(String(S.id));                    // форму диалога открыли — следующий ответ филиала считаем заново
    const окноБыло = ВЫБОР_ВРЕМЕНИ.открыто(), окноПоле = окноБыло && окноБыло.getAttribute('data-f');   // окно времени у поля формы
    panel.dataset.conv = String(S.id || '');                          // чья это форма (формаЭтого)
    panel.replaceChildren(ph, h('div', { class: 'pb fm cz' }, ...body), pf);
    обновитьЗвонок(L.visit_date || '', L.visit_time || '');
    обновитьБыстрые(L.visit_date || '', L.visit_time || '');
    обновитьСтатус();
    if (pb0) panel.querySelector('.pb').scrollTop = прокрутка;
    if (фок) вернутьФокус(фок);
    // поле времени перерисовано (ответ фона): курсор в нём — окно выбора снова у нового поля, иначе не висит над пустым местом
    if (окноБыло && !окноБыло.isConnected) {
      const x = окноПоле && panel.querySelector('[data-f="' + окноПоле + '"]');
      if (x && root.activeElement === x) ВЫБОР_ВРЕМЕНИ.открыть(x); else ВЫБОР_ВРЕМЕНИ.закрыть();
    }
    else if (первый && panel.classList.contains('open') && фокусСвободен()) {
      // форма нового диалога: курсор — в первое пустое обязательное поле, всё есть — на саму панель (Ctrl+Enter — «Создать»);
      // на «Создать» кодом не ставим: форма приходит через десятки секунд, случайный пробел / Enter создал бы заявку
      const пусто = первоеПустое();
      if (!panel.hasAttribute('tabindex')) panel.setAttribute('tabindex', '-1');
      if (пусто) { открытьСкрытое(пусто); пусто.focus(); } else panel.focus({ preventScroll: true });
    }
    // 2.3: согласование нужно — чат города и текст подбираем сразу (только чтение групп Telegram): в «Филиале» одна кнопка «Отправить в «…»»
    согласованиеЗаранее();
    // заявка не создалась, пока оператор был в другом чате или закрыл панель, — почему, сверху формы (один раз, когда её видно:
    // перерисовка закрытой панели — ответ поиска адреса, проверки — причину не «съедает»)
    if (S.createErr && panel.classList.contains('open')) { const e = S.createErr; S.createErr = null; alertBox(e()); }
  }
  // «⋯» в шапке формы: редкое — «Готовые», журнал за смену, настройки (раньше — три значка рядом с ✕)
  function менюЕщё(безГотовых) {
    const пункт = (t, label, fn) => h('button', { type: 'button', class: 'cz-mi', 'aria-label': label, onclick: (e) => { const d = e.currentTarget.closest('details'); if (d) d.open = false; fn(); } }, t);
    return h('details', { class: 'cz-more' }, h('summary', { 'aria-label': 'Ещё', title: безГотовых ? 'Ещё: журнал, настройки' : 'Ещё: «Готовые», журнал, настройки' }, '⋯'),
      h('div', { class: 'cz-menu' },
        безГотовых ? '' : пункт('Готовые во «Входящих»', 'Готовые к созданию', () => showReady()),
        пункт('Журнал за смену', 'Журнал за смену', () => showJournal()),
        пункт('Настройки', 'Настройки', () => send({ kind: 'lcz-options' }))));
  }
  // щелчок мимо открытого «⋯» — закрыть его
  root.addEventListener('click', (e) => { const путь = e.composedPath ? e.composedPath() : []; for (const d of root.querySelectorAll('details.cz-more[open]')) if (!путь.includes(d)) d.open = false; });
  // последнее сообщение клиента — строкой «Сообщение» (и согласен ли он на выезд — по смыслу, без ИИ)
  const ПОСЛЕДНЕЕ = new WeakMap();
  function последнееКлиента() {
    const msgs = (S && S.ctx && S.ctx.messages) || [];
    if (!msgs.length) return null;
    if (ПОСЛЕДНЕЕ.has(msgs)) return ПОСЛЕДНЕЕ.get(msgs);
    let out = null;
    try {
      const m = msgs.filter((x) => x && x.direction === 'in' && String(x.body || '').trim()).pop();
      if (m) {
        let note = '';
        try { const З = LC_EXTRACT.заявкаЛи(msgs, { now: Date.now() }); if (З && З.согласие && З.сила === 'сильно') note = 'клиент согласен на выезд'; } catch (_e) { /* без смысла — только время */ }
        const t = Date.parse(m.created_at || '');
        out = { text: String(m.body).replace(/\s+/g, ' ').trim(), note: note || (t ? 'написал в ' + часыМинуты(new Date(t)) : '') };
      }
    } catch (_e) { out = null; }
    ПОСЛЕДНЕЕ.set(msgs, out);
    return out;
  }
  /* 2.3: согласование одной кнопкой. Чат города и текст подобраны заранее — «В «МНЧ Москва»: …» и «Отправить в «МНЧ Москва»»;
     «другой чат» и «изменить текст» — прежнее окно выбора (поиск, несколько чатов, фото, «Во все»). Отправка — та же sendApproval:
     проверка просьб филиала в чате, один филиал за раз (остальные — по очереди при отказе), «Во все» — только в окне и с подтверждением */
  function согласованиеКратко() {
    const t = S.tg;
    if (!t || !t.chats || t.полное || t.error || t.guard || t.offline) return null;
    const picked = (Array.isArray(t.picked) ? t.picked : []).filter((id) => (t.chats || {})[id]);
    if (picked.length !== 1) return null;                              // чата нет или отмечено несколько — окно выбора
    const имя = t.chats[picked[0]].title || 'чат города';
    const вОкно = (что) => () => { keepTg(); S.tg.полное = true; render2keep();
      const x = panel.querySelector(что === 'text' ? '[data-tg="text"]' : '[data-tg="q"]'); if (x) x.focus(); };
    const фото = (t.photos || []).filter((x) => x.on).length;
    return h('div', { class: 'cz-tg', 'data-tg-short': '1' },
      h('div', { class: 'cz-tg-t', title: t.text || '' }, h('span', { class: 'cz-tg-k' }, 'В «' + имя + '»: '), String(t.text || '').trim()),
      h('textarea', { 'data-tg': 'text', value: t.text || '', hidden: true, 'aria-hidden': 'true', tabindex: '-1' }),
      t.matched && t.matched.several && t.авто ? h('div', { class: 'n warn' }, 'Подходит несколько чатов — проверьте, что этот; другой — «другой чат»') : '',
      фото ? h('div', { class: 'n mut' }, 'С фото клиента: ' + фото + ' (в CRM фото не попадают)') : '',
      h('div', { class: 'cz-tg-a' },
        h('button', { class: 'sm pri', 'data-tg': 'go', disabled: !!t.sending, onclick: () => { S.tg.всем = false; sendApproval(); } }, t.sending ? (t.stage || 'Отправляем…') : 'Отправить в «' + имя + '»'),
        t.sending ? '' : h('button', { type: 'button', class: 'lk', 'data-tg': 'other', onclick: вОкно('chat') }, 'другой чат'),
        t.sending ? '' : h('button', { type: 'button', class: 'lk', 'data-tg': 'edit', onclick: вОкно('text') }, 'изменить текст')));
  }
  // нужно согласование, а окна ещё нет — открываем его заранее (группы Telegram — только чтение, отправка — по нажатию). Один раз на форму
  function согласованиеЗаранее() {
    if (!S || S.tgЗаранее || S.tg || S.tgSent || !S.prep || !S.prep.ok || !S.prep.cityId || !S.check || S.check.busy) return;
    if (!((S.check && S.check.approval) || terrReason() || repeatReason())) return;
    S.tgЗаранее = true;
    const my = S;
    setTimeout(() => { if (S === my && !S.tg && !S.tgSent && формаЭтого()) openApproval(); }, 0);
  }

  // поле с фокусом — чем его найти после перерисовки (data-f / data-tg, у галочек чатов — значение) и где стоял курсор
  function чейФокус(el) {
    if (!el || !panel.contains(el)) return null;
    if (el.matches('.pf .go')) return null;                             // на «Создать» после перерисовки курсор не возвращаем
    const f = el.getAttribute('data-f'), tg = el.getAttribute('data-tg'), fx = el.getAttribute('data-fx');   // fx — поле без своего data-f (текст комментария)
    if (!f && !tg && !fx) return null;
    let s0 = null, s1 = null;
    try { s0 = el.selectionStart; s1 = el.selectionEnd; } catch (_e) { /* у этого поля курсора нет */ }
    return { f, tg, fx, v: el.type === 'checkbox' || el.type === 'radio' ? el.value : null, s0, s1 };
  }
  function вернутьФокус(x) {
    if (x.go) { const go = panel.querySelector('.pf .go'); if (go && !go.disabled) go.focus({ preventScroll: true }); return; }
    const el = x.fx ? panel.querySelector('[data-fx="' + x.fx + '"]')
      : [...panel.querySelectorAll(x.f ? '[data-f]' : '[data-tg]')].find((e) => (x.f ? e.getAttribute('data-f') === x.f : e.getAttribute('data-tg') === x.tg) && (x.v === null || e.value === x.v));
    if (!el || el.disabled) return;
    ТИХИЙ_ФОКУС.on = true;                                             // курсор вернули после перерисовки — окно времени само не открываем
    try { el.focus({ preventScroll: true }); } finally { ТИХИЙ_ФОКУС.on = false; }
    if (x.s0 !== null && x.s0 !== undefined) try { el.setSelectionRange(x.s0, x.s1); } catch (_e) { /* дата, время, список — без курсора */ }
  }
  // фокус ничей или на наших кнопках («Заявка», «Готовые») — можно ставить в форму; оператор печатает в LeadChat
  // или в поле нашей панели (заметка, ответ в уведомлении) — не отнимаем
  const полеВвода = (a) => !!a && (a.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName));
  const нашФокус = (a) => !!a && (a === host || (a.hasAttribute && a.hasAttribute('data-lcz'))) && !полеВвода(a.shadowRoot && a.shadowRoot.activeElement);
  const фокусСвободен = () => { const a = document.activeElement; return !a || a === document.body || a === document.documentElement || нашФокус(a); };
  // обязательные поля по порядку формы: телефон, адрес, город в CRM
  function первоеПустое() {
    const v = (f) => { const e = panel.querySelector('[data-f="' + f + '"]'); return e ? { e, x: String(e.value || '').trim() } : null; };
    const p = v('phone'), st = v('street'), se = v('settlement'), c = v('cityId');
    if (p && p.x.replace(/\D/g, '').length < 10) return p.e;
    if (st && !st.x && !(se && se.x)) return st.e;
    if (c && !c.x) return c.e;
    return null;
  }
  // к полю: прокрутить к нему и поставить курсор
  function кПолю(el) {
    if (!el) return;
    if (typeof открытьСкрытое === 'function') открытьСкрытое(el);   // поле в свёрнутом «+ …» — сначала открыть
    if (el.scrollIntoView) el.scrollIntoView({ block: 'center' });
    el.focus({ preventScroll: true });
  }
  const SMALL = 'height:22px;padding:0 6px;border:1px solid var(--line);border-radius:6px;background:transparent;color:var(--t3);font-size:11px;cursor:pointer';
  function autoLinkEl(L) {
    const a = S.autoLink || (ссылкаКанала(S.conv) ? { ok: true, short: ссылкаКанала(S.conv), how: КАК_КАНАЛ, канал: true } : null);
    const нет = L.partner_note ? '«' + L.partner_note + '» нет в списке источников'
      : !LC_EXTRACT.каналMAX(S.conv) ? 'У канала LeadChat не указан источник'
      : авитоДиалога(S.conv) ? 'У диалога Авито этого клиента не указан источник' : 'Диалог MAX: источник не определён (диалога Авито этого клиента нет)';
    const объявление = объявлениеДиалога(S.conv).url;                 // MAX — объявление диалога Авито этого клиента
    if (a && a.ok && a.short) {
      return h('div', { style: 'display:flex;flex-direction:column;gap:4px;min-width:0' },
        h('a', { class: 'lnk', href: a.short, target: '_blank', title: a.profile || a.short }, svg('link'), a.short.replace(/^https?:\/\//, '') + ' — ссылка для отзыва'),
        h('div', { class: 'n mut', 'data-review': a.канал ? 'channel' : 'avito' }, нет + (a.канал ? ' — ' + КАК_КАНАЛ + ' ' : ' — ссылка со страницы продавца на Авито (' + (a.how || '') + ') '),
          объявление && !a.канал ? h('button', { class: 'sm', style: SMALL, onclick: () => getReviewLink(true) }, 'обновить') : '', ' ',
          h('button', { class: 'sm', style: SMALL, title: 'Строка в формате списка источников — вставьте её в общий список в Telegram', onclick: async (e) => {
            const line = (L.partner_note || 'источник') + ' -\n' + a.short;
            try { await navigator.clipboard.writeText(line); e.target.textContent = 'скопировано ✓'; } catch (_e) { e.target.textContent = line.replace('\n', ' '); }
          } }, 'скопировать для списка источников')));
    }
    if (a && a.busy) return h('div', { class: 'n mut', style: 'min-height:36px;display:flex;align-items:center' }, нет + (a.показать
      ? ' — открыли объявление на Авито: если спросит «не робот?», подтвердите — ссылка сделается сама и вкладка закроется'
      : ' — делаем ссылку: страница продавца на Авито → clck.ru…'));
    /* 2.1.6: сама не сделалась — открыть объявление видимой вкладкой (Авито пускает живого человека) или вставить ссылку вручную:
       на продавца (avito.ru/brands/…), на объявление или готовую clck.ru — короткую сделаем и запомним для всей команды */
    const кн = 'height:28px;padding:0 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--t1);font-size:12px;cursor:pointer';
    const вставить = (e) => { const el = e.target, v = String(el.value || '').trim();
      if (/^https?:\/\//i.test(v) && el.dataset.sent !== v) { el.dataset.sent = v; getReviewLink(true, { ручная: v }); } };
    return h('div', { class: 'n warn', 'data-review': 'none', style: 'display:flex;flex-direction:column;gap:6px;min-width:0' },
      h('div', {}, нет + ' — ссылки для отзыва нет' + (a && a.error ? ' (' + a.error + ')' : '')),
      h('div', { style: 'display:flex;gap:6px;flex-wrap:wrap' },
        объявление ? h('button', { class: 'sm', 'data-review': 'auto', style: кн, onclick: () => getReviewLink(true) }, 'Сделать с Авито') : '',
        объявление ? h('button', { class: 'sm', 'data-review': 'open', style: кн, title: 'Откроется объявление; ссылка на продавца найдётся сама, вкладка закроется', onclick: () => getReviewLink(true, { показать: true }) }, 'Открыть объявление') : ''),
      h('input', { type: 'url', 'data-review': 'paste', placeholder: 'или вставьте ссылку на продавца / clck.ru', autocomplete: 'off', style: 'height:32px;font-size:12.5px',
        onpaste: (e) => setTimeout(() => вставить(e), 0), onkeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); вставить(e); } }, onchange: вставить }));
  }

  function readForm() {
    const v = (f) => { const el = panel.querySelector('[data-f="' + f + '"]'); return el ? (el.type === 'checkbox' ? el.checked : el.value.trim()) : ''; };
    const L = S.lead;
    const lead = {
      ...L,
      phone: v('phone').replace(/\D/g, '').slice(-10), name: v('name'),
      phones_extra: v('phone2').split(/[,;]/).map((x) => x.replace(/\D/g, '').slice(-10)).filter((x) => x.length === 10).slice(0, 3),
      addr: { settlement: v('settlement'), street: v('street'), building: v('building'), office: v('office'),
        entrance: v('entrance'), floor: v('floor'), ...LC_WORKFLOW.readIntercomField(L.addr, panel.querySelector('[data-f="intercom"]')) },
      visit_date: v('visit_date'), visit_time: v('visit_time'),
      call_check: v('call_check'), call_before_visit: v('call_before_visit'), far_ride: v('far_ride'), urgent: v('urgent'), comment: v('comment'), phone_ok: v('phoneOk'),
      partner_note: v('partner_note'), review: LC_LINKS.requiresReview(L.partner) || v('review'),
      ad_identity: v('ad_identity'), introduced_as: v('introduced_as'),
      ad_identity_set: !!L.ad_identity_set || v('ad_identity') !== (L.ad_identity || ''),
      introduced_as_set: !!L.introduced_as_set || v('introduced_as') !== (L.introduced_as || ''),
    };
    lead.comment = LC_EXTRACT.advertiserComment(lead, lead.comment);
    Object.assign(lead, LC_WORKFLOW.callbackComment(lead));
    const P = S.prep;
    const sel = { cityId: v('cityId'), applId: v('applId'), subId: v('subId'), type: v('type') || 'Впервые',
      appl: (P && P.appl) || [], sub: (P && P.sub) || [] };
    return { lead, sel, allowLive: v('allowLive') };
  }

  /* Код источника для «Созданные с Авито»: «С74.2» из источника заявки или метки канала. У каналов партнёра 748 такого кода нет —
     пишем номер партнёра: «794232 - 748 БТ» (владелец 07.10). Другим партнёрам коды не придумываем: нет кода — не пишем, но говорим об этом */
  const ПАРТНЁРЫ_БЕЗ_КОДА = ['748'];
  const партнёрКодом = (p) => { const n = String(p == null ? '' : p).trim().replace(/^0+(?=\d)/, ''); return ПАРТНЁРЫ_БЕЗ_КОДА.includes(n) ? n : ''; };
  // MAX — источник и партнёр диалога Авито этого клиента (его нет — кода нет)
  const кодАккаунта = (L) => { const acc = S && S.conv ? каналИсточника(S.conv) : {};
    return LC_TG.кодИсточника((L && L.partner_note) || '') || LC_TG.кодИсточника(acc.lead_origin || '') || партнёрКодом(L && L.partner) || партнёрКодом(acc.lead_partner_number); };
  // почему кода нет: у диалога MAX своего источника не бывает — «у канала нет кода» сбивало бы с толку
  const безКода = (conv) => (maxБезАвито(conv) ? 'диалог MAX, а диалога Авито этого клиента нет — источник не определён' : 'у канала нет кода источника');
  const нетКода = (conv) => 'В «Созданные с Авито» не отпишу: ' + безКода(conv) + ' — напишите вручную «№ - …»';
  /* Созданную заявку — в группы, как чатеры: «№ - С85 МНЧ» в «Авито-Чаты» → раздел «Созданные с Авито»,
     «№» ответом на согласование в чате города. «Авито-Чаты» — группа с разделами: без раздела сообщение
     падает в общий («Вопросы по Авито»), поэтому пишем ответом на номер раздела, а раздел не нашёлся — не пишем вовсе. */
  const текстАвито = (id, код, dir) => (id + ' - ' + код + (LC_TG.ИМЯ[dir] ? ' ' + LC_TG.ИМЯ[dir] : '')).trim();
  /* 2.1.1: раздел «Созданные с Авито» — тема форума, она не меняется: помним сутки (в памяти вкладки и в хранилище). Раньше каждая
     заявка спрашивала программу Telegram заново — лишний круг «сервер → ПК → сервер» (3–4 с) перед отпиской. Отписка в раздел
     не ушла — забываем (забытьРаздел), следующая спросит свежий */
  const РАЗДЕЛЫ = new Map(), РАЗДЕЛ_МС = 864e5;
  async function разделСозданных(chatId) {
    const key = String(chatId), m = РАЗДЕЛЫ.get(key);
    if (m && Date.now() - m.at < РАЗДЕЛ_МС) return m.p;
    try {
      const x = ((await store.get('tgTopics', {})) || {})[key];
      if (x && x.id && Date.now() - (x.at || 0) < РАЗДЕЛ_МС) { const v = { id: x.id, title: x.title || '' }; РАЗДЕЛЫ.set(key, { at: x.at, p: Promise.resolve(v) }); return v; }
    } catch (_e) { /* без памяти — спросим */ }
    const p = (async () => {
      const r = await send({ kind: 'lcz-tg', args: { action: 'topics', chat: chatId } });
      if (!r || !r.ok) throw new Error(/неизвестное задание/.test(String(r && r.error)) ? 'обновите программу Telegram на компьютере (tg_agent.py) — старая не видит разделы' : (r && r.error) || 'разделы не получены');
      const t = (r.topics || []).find((x) => /созданн/i.test(x.title || '')) || null;
      if (!t) { РАЗДЕЛЫ.delete(key); return null; }                    // раздела нет — не запоминаем: его могут завести
      try { const all = (await store.get('tgTopics', {})) || {}; all[key] = { id: t.id, title: t.title || '', at: Date.now() }; await store.set('tgTopics', all); } catch (_e) { /* только в памяти */ }
      return t;
    })();
    РАЗДЕЛЫ.set(key, { at: Date.now(), p });
    p.catch(() => { if (РАЗДЕЛЫ.get(key) && РАЗДЕЛЫ.get(key).p === p) РАЗДЕЛЫ.delete(key); });
    return p;
  }
  function забытьРаздел(chatId) {
    const key = String(chatId);
    РАЗДЕЛЫ.delete(key);
    store.get('tgTopics', {}).then((m) => { if (m && m[key]) { delete m[key]; return store.set('tgTopics', m); } return null; }).catch(() => {});
  }
  const чатАвито = (c) => (c && c.ok ? Object.entries(c.chats || {}).find(([, ch]) => /^\s*авито[\s-]*чаты\s*$/i.test(ch.title || '')) : null) || null;
  // последний ответ филиала на наше согласование («условия выезда») — «№ создал» уходит ответом на него
  const последнийОтвет = (x) => send({ kind: 'lcz-tg', args: { action: 'replies', chat: x.chat, msg: x.msg } })
    .then((rr) => ((rr && rr.replies) || []).filter((y) => y.id).pop() || null).catch(() => null);
  /* 2.1.1: всё, что для отписок можно узнать без номера заявки, — заранее, пока идут проверки и CRM (несколько секунд):
     группы Telegram, раздел «Созданные с Авито», ответы филиала на согласование. С номером остаётся одна отправка на сообщение */
  function заранееTG(job) {
    const w = job.отписать || {};
    if (!((w.avito && job.кодП) || w.reply || w.zakrepNot)) return null;
    const группы = группыTG().catch(() => null);
    return { at: Date.now(), группы,
      раздел: w.avito && job.кодП ? группы.then((c) => { const ch = чатАвито(c); return ch ? разделСозданных(ch[0]) : null; }).catch(() => null) : null,
      ответы: w.reply ? (job.соглП || []).map((x) => последнийОтвет(x)) : [] };
  }
  // city — город заявки (из задачи создания): «№ не по закрепу» — в чат ЕЁ города, а не открытого сейчас диалога.
  // 2.1: следить(ключ, состояние, итог) — для экрана: строка «отправляю…» → «готово» / «не ушло» (порядок и данные отписок те же)
  /* 2.1.1: «Созданные с Авито» — отдельный чат: уходит одновременно с сообщениями в чат города (раньше — строго по очереди, и каждое
     ждало предыдущее). В чате города порядок прежний: «№ создал», потом «№ не по закрепу». заранее — из заранееTG (до номера заявки) */
  async function отписатьСозданную(id, what, код, согл, conv, dir, city, следить, заранее) {
    const сл = (k, st, x) => { try { if (следить) следить(k, st, x); } catch (_e) { /* экран — не главное */ } };
    const итогСтроки = (k, x) => сл(k, !x ? 'bad' : x.ok ? 'ok' : /ждёт/.test(x.text || '') ? 'hold' : x.unknown ? 'unknown' : 'bad', x);
    const свежее = заранее && Date.now() - заранее.at < 3 * 60e3 ? заранее : null;   // узнанное заранее — не старше 3 мин
    const [авито, город] = await Promise.all([
      what.avito && код ? отписатьАвито() : Promise.resolve([]),
      отписатьГород()]);
    return авито.concat(город);

    async function отписатьАвито() {
      const out = [];
      сл('avito', 'send');
      const текст = текстАвито(id, код, dir);
      const c = (свежее && (await свежее.группы)) || await группыTG();
      const chat = чатАвито(c);
      let раздел = null, почему = '';
      if (chat) { try { раздел = (свежее && свежее.раздел && (await свежее.раздел)) || await разделСозданных(chat[0]); if (!раздел) почему = 'в «Авито-Чаты» нет раздела «Созданные с Авито»'; } catch (e) { почему = String(e.message || e); } }
      // группы Telegram не получены (сервер, сеть) — так и говорим, а не «не найден»
      // item / manual — какая это отписка и её текст: на экране итога «Скопировать» и «Отправить ещё раз» только её
      const м = { item: 'avito', manual: текст };
      if (!c || !c.ok) out.push({ ok: false, ...м, text: 'В «Созданные с Авито» не отправлено: группы Telegram не получены (' + ((c && c.error) || 'нет ответа') + '). Напишите вручную: ' + текст });
      else if (!chat) out.push({ ok: false, ...м, text: 'В «Созданные с Авито» не отправлено: «Авито-Чаты» не найден среди групп Telegram. Напишите вручную: ' + текст });
      else if (!раздел) out.push({ ok: false, ...м, text: 'В «Созданные с Авито» не отправлено: ' + почему + '. Напишите вручную: ' + текст });
      else {
        const r = await send({ kind: 'lcz-tg', args: { action: 'send', chat: chat[0], reply_to: раздел.id, text: текст, conv } });
        if (!(r && r.ok) && !(r && r.unknown)) забытьРаздел(chat[0]);   // раздел могли пересоздать — следующая спросит свежий
        out.push(r && r.ok ? { ok: true, text: 'В «' + раздел.title + '»: ' + текст } : { ok: false, ...м, unknown: !!(r && r.unknown), text: 'В «' + раздел.title + '» не отправилось: ' + ((r && (r.error || r.description)) || 'ошибка') + '. Напишите вручную: ' + текст });
      }
      итогСтроки('avito', out[out.length - 1]);
      return out;
    }
    async function отписатьГород() {
      const out = [];
      // регламент: итог согласования — ответом на условия выезда филиала: «12345 создал»
      // (раньше «не по закрепу»: это ответ на условия филиала, иначе защита от перекрытия приняла бы их за просьбу)
      if (what.reply) for (const [i, x] of согл.entries()) {
        сл('reply:' + i, 'send');
        let на = x.msg;
        const послед = await ((свежее && свежее.ответы && свежее.ответы[i]) || последнийОтвет(x));
        if (послед) на = послед.id;
        const r = await send({ kind: 'lcz-tg', args: { action: 'send', chat: x.chat, reply_to: на, text: id + ' создал', conv } });
        out.push(r && r.ok ? { ok: true, text: 'В «' + (x.title || 'чат') + '»: ' + id + ' создал (ответом на ' + (на !== x.msg ? 'условия филиала' : 'согласование') + ')' } : { ok: false, item: 'reply', unknown: !!(r && r.unknown), manual: id + ' создал', text: 'В «' + (x.title || 'чат') + '» не отправилось: ' + ((r && (r.error || r.description)) || 'ошибка') });
        итогСтроки('reply:' + i, out[out.length - 1]);
      }
      // регламент: приняли не по закрепу — пишем в город «№ не удобно принять по закрепу, ждет в ближайшее время» (рег:1073)
      /* 1.20: действия — через общий бегунок (журнал, защита от перекрытия); просьба филиала — окно с выбором, как раньше */
      if (what.zakrepNot && ACT) {
        сл('zakrepNot', 'send');
        const x = await ACT.неПоЗакрепу({ id, dir, city, conv, согл });
        // ждёт ответа просьба филиала — отправит окно с выбором, повтор отсюда не нужен (ушло бы дважды)
        out.push(x && !x.ok && !/ждёт/.test(x.text || '') ? { ...x, item: 'zakrepNot', unknown: !!(x.unknown || x.состояние === 'неясно' || (x.tg && x.tg.unknown)), manual: ((x.text || '').match(/^«(\d[^»]*)»/) || [])[1] || id + ' не по закрепу' } : x);
        итогСтроки('zakrepNot', out[out.length - 1]);
      }
      else if (what.zakrepNot) {
        сл('zakrepNot', 'send');
        const c = await группыTG();
        const m = c && c.ok ? LC_TG.matchChat(c.chats, dir, city || '') : null;
        const chat = (согл[0] && согл[0].chat) || (m && m.id);
        if (!chat) out.push({ ok: false, item: 'zakrepNot', manual: id + ' не по закрепу', text: '«№ не по закрепу» не отправлено: чат города не найден' });
        else {
          const r = await вЧатГорода({ chat, text: id + ' не по закрепу', conv }, { title: (согл[0] && согл[0].title) || (m && m.title) || '' });
          if (r && r.guard) { тостОтложено({ chat, text: id + ' не по закрепу', conv }, r.guard); out.push({ ok: false, text: '«' + id + ' не по закрепу» ждёт: в чате города просьба филиала без ответа — см. уведомление «Просьба филиала ждёт ответа»' }); }
          else out.push(r && r.ok ? { ok: true, text: 'В чат города: ' + id + ' не по закрепу' } : { ok: false, item: 'zakrepNot', unknown: !!(r && r.unknown), manual: id + ' не по закрепу', text: '«не по закрепу» не отправилось: ' + ((r && r.error) || 'ошибка') });
        }
        итогСтроки('zakrepNot', out[out.length - 1]);
      }
      return out;
    }
  }
  /* Что после создания НЕ отписано и почему — на экран «Заявка создана» (молча ничего не пропускаем):
     нет кода источника, галочка снята, филиал ещё не ответил на согласование, CRM не сообщила номер.
     Галочку снял оператор (reason 'off') — его решение, не сбой: ok, на экране приглушённо, в «не отписано» не считается */
  function неОтписано(id, what, код, ответил, согл, ждём, dir, почему) {
    const out = [], номер = id || '№';
    const вЧаты = (x) => '«' + ((x && x.title) || 'чат') + '»';
    if (!код) out.push({ ok: false, skip: true, text: 'В «Созданные с Авито» не отписано: ' + (почему || 'у канала нет кода источника') + ' — напишите вручную «' + номер + ' - …' + (LC_TG.ИМЯ[dir] ? ' ' + LC_TG.ИМЯ[dir] : '') + '»' });
    else if (!what.avito) out.push({ ok: true, skip: true, reason: 'off', manual: текстАвито(номер, код, dir), text: 'В «Созданные с Авито» не отписано: галочка снята. Если нужно — вручную: ' + текстАвито(номер, код, dir) });
    else if (!id) out.push({ ok: false, skip: true, text: 'В «Созданные с Авито» не отписано: CRM не сообщила номер заявки — напишите вручную «№ - ' + код + (LC_TG.ИМЯ[dir] ? ' ' + LC_TG.ИМЯ[dir] : '') + '»' });
    if (ответил && !what.reply) out.push({ ok: true, skip: true, reason: 'off', manual: номер + ' создал', text: '«' + номер + ' создал» не отправлено: галочка снята — ответьте филиалу вручную в ' + согл.map(вЧаты).join(', ') });
    else if (ответил && !id) out.push({ ok: false, skip: true, text: '«№ создал» не отправлено: CRM не сообщила номер заявки — ответьте филиалу вручную в ' + согл.map(вЧаты).join(', ') });
    if (ждём) out.push({ ok: false, skip: true, text: '«' + номер + ' создал» не отправлено: филиал ещё не ответил на согласование — ответьте ему в ' + ждём.map(вЧаты).join(', ') + ', когда ответит' });
    if (what.zakrepNot && !id) out.push({ ok: false, skip: true, text: '«№ не по закрепу» не отправлено: CRM не сообщила номер заявки — напишите в чат города вручную' });
    return out;
  }

  /* БЛИЖАЙШЕЕ ПО РЕГЛАМЕНТУ (решение владельца 13.10, вместо «Прозвон без договорённого времени: +4 ч»): клиент время визита
     не назвал — заявка на ближайшее время по регламенту, на точное — если клиент назвал; «Прозвон» ставит только оператор.
     Регламент «Территориальные правила»: в черте города — через 1 ч от времени в городе (кнопка CRM «Через час», до минуты);
     филиалы Москвы, за чертой и город-спутник — через 2 ч («+2ч»). Раньше 10:00 (спутник и «за 2 ч» — 11:00) — к началу приёма,
     позже 21:30 — завтра к началу приёма (позже — только по согласованию с филиалом). Зона — по территории (terr) и городу CRM (prep);
     пока территории нет — +1 ч (Москва — +2 ч по городу), придёт — пересчёт своего времени (prepare). Правка оператора и время,
     которое клиент назвал потом («завтра в 15» — новый разбор), главнее: своё время (visit_auto) трогаем, только пока его не меняли */
  const москва = (x) => {
    const s = String(x || '');
    if (!s.trim()) return false;
    if (typeof LC_TERRITORY !== 'undefined') return LC_TERRITORY.городаИмени(s).includes('москва');
    return /^\s*(москва|мск)(\s*\d+)?\s*$/i.test(s.replace(/\s*\(.*?\)\s*/g, ' '));
  };
  // { плюс: 60 | 120, ранняя: '10:00' | '11:00', где: 'в городе' | 'за чертой' | 'город-спутник' | 'Москва', известна, нет }
  function зонаБлижайшего(L, terr, prep) {
    const t = terr && terr.ok ? terr : null, P = prep && prep.ok ? prep : null;
    const ранняя = (t && t.earliest) || '10:00';
    const часы = t ? parseFloat(String(t.hours || '').split('–')[0].replace(',', '.')) : NaN;
    if (t && t.satelliteOf) return { плюс: 120, ранняя, где: 'город-спутник', известна: true };
    if (t && часы >= 2) return { плюс: 120, ранняя, где: 'за чертой', известна: true };
    // филиалы Москвы — за 2–2,5 ч и в черте города (регламент): по городу CRM, филиалу по карте или городу объявления
    if (москва((P && P.cityText) || (t && t.branch) || (L && L.city))) return { плюс: 120, ранняя, где: 'Москва', известна: !!(t || P) };
    return { плюс: 60, ранняя, где: 'в городе', известна: !!t, нет: !!(terr && !terr.ok) };
  }
  /* своё время визита от «сейчас» у клиента (а не от разбора: он мог полежать в «Готовых» или в памяти диалога до 12 ч):
     Ближайшее и прозвон используют один норматив филиала. base — день, который назвал
     клиент без часа: другой день («в среду») — время не выдумываем, решает оператор. null — не ставим */
  function своёВремя(L, вид, base, зона) {
    if (!L || !L.clock) return null;
    const ч = L.clock.tz ? LC_EXTRACT.localParts(new Date(), L.clock.tz) : null;
    const clock = ч ? { ...L.clock, now: ч.hm, iso: ч.iso } : L.clock;
    const окно = окноКлиента(L), kind = вид === 'прозвон' ? 'прозвон' : 'ближайшее';
    if (base && base !== clock.iso && !окно) return null;
    const з = зона || зонаБлижайшего(L, null, null);
    if (окно) {
      /* 2.2.7 окно клиента: ближайшее по регламенту, но не раньше начала окна и не позже срока минус 30 мин; окно на другой день
         («завтра до 12») — начало приёма того дня (или начало окна). Не успеваем — время НЕ ставим (у «Визита» — предупреждение) */
      const p = LC_EXTRACT.времяВОкне(clock, окно, { плюс: з.плюс, ранняя: з.ранняя, день: base });
      if (!p) return null;
      if (!p.ок) return { ...L, clock, visit_date: L.visit_date || окно.date || '', visit_time: '', visit_auto: null };
      return { ...L, clock, visit_date: p.date, visit_time: p.time, visit_auto: { date: p.date, time: p.time, плюс: p.плюс, завтра: p.завтра, раньше: p.раньше,
        base: base || окно.date || '', kind, где: з.где, ранняя: з.ранняя, известна: !!з.известна, нет: !!з.нет, окно: true, отОкна: p.отОкна } };
    }
    const p = LC_EXTRACT.ближайшееПоРегламенту(clock, { плюс: з.плюс, ранняя: з.ранняя });
    return p ? { ...L, clock, visit_date: p.date, visit_time: p.time, visit_auto: { ...p, base: base || '', kind, где: з.где, ранняя: з.ранняя, известна: !!з.известна, нет: !!з.нет } } : null;
  }
  // заявка из разбора: клиент время не назвал — ближайшее по регламенту. Своё время (оператор не правил) — пересчёт от «сейчас»;
  // своё время оператор поправил или стёр — не трогаем
  function сБлижайшим(L, terr, prep) {
    if (!L || !L.clock) return L;
    const авто = визитАвто(L);
    // 2.2.7: визит — начало окна клиента («после 12»), а сегодня по регламенту ближайшее позже — ближайшее (в окне; не успеваем до срока —
    // время снимаем, у «Визита» предупреждение). Начало окна позже ближайшего — время клиента как есть
    const окно = окноКлиента(L);
    if (!авто && !L.visit_auto && окно && окно.from && L.visit_time === окно.from) {
      const N = своёВремя(L, 'ближайшее', L.visit_date || '', зонаБлижайшего(L, terr, prep));
      return N && (!N.visit_time || N.visit_date > (L.visit_date || '') || (N.visit_date === L.visit_date && N.visit_time > L.visit_time)) ? N : L;
    }
    if (!авто && (L.visit_time || L.visit_auto)) return L;
    const base = авто ? L.visit_auto.base || '' : L.visit_date || '';
    // Сохраняем отметку прозвона при пересчёте того же нормативного времени.
    const вид = авто && L.visit_auto.kind === 'прозвон' && L.call_check ? 'прозвон' : 'ближайшее';
    return своёВремя(L, вид, base, зонаБлижайшего(L, terr, prep)) || L;
  }
  // зона текущей формы: территория и город CRM этого диалога
  const сБлижайшимФормы = (L) => сБлижайшим(L, S && S.terr, S && S.prep);
  // пришла территория (или город CRM): своё время — по новой зоне, от «сейчас». Форма на экране — сверяем с её полями:
  // оператор поправил время — его правка главнее
  function пересчитатьБлижайшее() {
    if (!S || !S.lead) return;
    const эл = (k) => формаЭтого() && panel.querySelector('[data-f="' + k + '"]');
    const d = эл('visit_date'), t = эл('visit_time'), cc = эл('call_check');
    const L = !d || !t ? S.lead : { ...S.lead, visit_date: d.value || '', visit_time: t.value || '', ...(cc ? { call_check: cc.checked } : {}) };
    if (!визитАвто(L)) return;
    const N = сБлижайшимФормы(L);
    if (N !== L) S.lead = { ...S.lead, clock: N.clock, visit_date: N.visit_date, visit_time: N.visit_time, visit_auto: N.visit_auto };
  }
  /* ДИАЛОГ MAX БЕЗ ДИАЛОГА АВИТО: у диалога нет ни пояса, ни города объявления, а город клиента в адресе не назван — разбор считал
     часы по Москве. Форма CRM подобрала город (P.cityText) — часы клиента, своё время визита (ближайшее / «Прозвон» +4 ч) и время, посчитанное от сообщения
     («через час»), — по поясу этого города. Один раз на город; поправленное оператором время не трогаем */
  const смещениеПояса = (tz, ms) => { const м = Math.floor(ms / 60e3) * 60e3, p = LC_EXTRACT.localParts(new Date(м), tz); return Math.round((Date.parse(p.iso + 'T' + p.hm + ':00Z') - м) / 60e3); };
  function поясПоГородуCRM(P) {
    const L = S && S.lead;
    if (!L || !L.clock || !P || !P.ok || !P.cityText || !maxБезАвито(S.conv) || !/московск/i.test(L.clock.how || '')) return;
    const город = LC_TERRITORY.чистыйГород(P.cityText) || P.cityText;
    const z = LC_EXTRACT.clientTz('', город);
    if (z.how !== 'пояс по названию города' || S.поясCRM === город) return;
    S.поясCRM = город;
    const наЭкране = формаЭтого();
    if (наЭкране) keepEdits();                                       // правки оператора в полях — не теряем
    const было = S.lead.clock.tz, now = Date.now();
    const ч = LC_EXTRACT.localParts(new Date(now), z.tz);
    let lead = { ...S.lead, clock: { ...S.lead.clock, tz: z.tz, now: ч.hm, iso: ч.iso, how: 'пояс по городу CRM (' + город + ')' } };
    const сдвиг = смещениеПояса(z.tz, now) - смещениеПояса(было || 'Europe/Moscow', now);
    const tc = (S.checks || []).find((c) => c.field === 'time');
    // «через час» / «через 2 часа» — посчитано от времени сообщения по Москве: тот же миг, часы — города клиента (форма ещё не на экране)
    if (сдвиг && !наЭкране && tc && /посчитано от времени сообщения/.test(tc.note || '') && /^\d{4}-\d{2}-\d{2}$/.test(lead.visit_date || '') && /^\d{2}:\d{2}$/.test(lead.visit_time || '')) {
      const t = new Date(Date.parse(lead.visit_date + 'T' + lead.visit_time + ':00Z') + сдвиг * 60e3).toISOString();
      lead = { ...lead, visit_date: t.slice(0, 10), visit_time: t.slice(11, 16) };
      setCheck('time', tc.ok, tc.note + ' · по поясу города CRM');
    }
    S.lead = сБлижайшимФормы(lead);                                  // своё время (ближайшее, не правленое) — по часам этого города
  }
  /* сейчас у клиента — по его поясу (L.clock.tz), а не часы на момент разбора: форма и «Готовые» могут полежать.
     Пояса нет (старый разбор) — часы разбора как есть */
  function клиентСейчас(L) {
    const c = L && L.clock;
    if (!c) return null;
    if (!c.tz) return c;
    const ч = LC_EXTRACT.localParts(new Date(Date.now()), c.tz);
    return { ...c, now: ч.hm, iso: ч.iso };
  }
  const визитАвто = (L) => !!(L && L.visit_auto && L.visit_date === L.visit_auto.date && L.visit_time === L.visit_auto.time);
  // 2.2.7 окно клиента из разбора: { from, until, date, text } — есть начало или срок; нет — null
  const окноКлиента = (L) => { const w = L && L.time_window; return w && (w.from || w.until) ? w : null; };
  // 2.2.7: при отправке ближайшее (или «не ближе часа») ушло за срок окна — не создаём. когда — 'ГГГГ-ММ-ДД ЧЧ:ММ' по часам клиента
  const срокНеУспеваем = (w, когда) => 'Не создал: клиент может только до ' + w.until + (w.date ? ' (' + w.date.slice(8, 10) + '.' + w.date.slice(5, 7) + ')' : '')
    + ' — по регламенту ближайшее уже ' + когда.slice(8, 10) + '.' + когда.slice(5, 7) + ' в ' + когда.slice(11, 16) + ', не успеваем; за срок время не сдвигаю. Договоритесь о другом времени/дне';
  /* 2.2.7: у окна клиента есть срок («до 15»), время пустое или своё (ближайшее, начало окна), а по регламенту уже не успеваем
     (ближайшее позже срока минус 30 мин) — текст предупреждения; успеваем, срока нет или время поставил оператор — '' */
  function промахОкна(L, terr, prep) {
    const w = окноКлиента(L);
    if (!w || !w.until || !L.clock) return '';
    const t = String(L.visit_time || '').slice(0, 5);
    if (t && !визитАвто(L) && t !== w.from) return '';
    const c = клиентСейчас(L) || {};
    const з = зонаБлижайшего(L, terr !== undefined ? terr : S && S.terr, prep !== undefined ? prep : S && S.prep);
    const p = LC_EXTRACT.времяВОкне(L.clock, w, { плюс: з.плюс, ранняя: з.ранняя, день: L.visit_date || '' });
    if (!p || p.ок) return '';
    const дм = (x) => x.slice(8, 10) + '.' + x.slice(5, 7), день = w.date || L.visit_date || c.iso || '';
    const другой = !!(день && c.iso && день !== c.iso);
    return 'Клиент может только до ' + w.until + (другой ? ' (' + дм(день) + ')' : '') + ' — по регламенту '
      + (другой ? 'приём с ' + p.time : p.date !== c.iso ? 'ближайшее уже завтра ' + p.time : 'ближайшее ' + p.time) + ', не успеваем. Договоритесь о другом времени/дне';
  }
  // регламент МНЧ: заявка создаётся на два и более дня вперёд — «Прозвон перед выездом» ставим всегда
  function наДваДня(L) {
    const c = клиентСейчас(L);
    if (!S || S.dir !== 'mnc' || !L || !L.visit_date || !c || !c.iso) return false;
    return (Date.parse(L.visit_date) - Date.parse(c.iso)) / 864e5 >= 2;
  }
  /* вернуть отменённую заявку в «Ожидает» (регламент) — вместо новой: CRM, новое время, чат города, имя в LeadChat */
  async function вернутьВОжидает(ref, btn) {
    keepEdits();
    const L = S.lead, my = S;
    if (!btn.dataset.label) btn.dataset.label = btn.textContent;     // надпись — вернуть кнопке, если ничего не сделали
    btn.disabled = true; btn.textContent = 'Возвращаем в «Ожидает»…';
    if (ACT) return вернутьБегунком(ref, btn, my, false);
    const r = await send({ kind: 'lcz-crm', op: 'returnToAwait', args: { dir: ref.dir, id: ref.id, date: L.visit_date || '', time: L.visit_time || '' } });
    if (S !== my) return;
    if (!r || !r.ok) { btn.disabled = false; btn.textContent = 'Не вернулось: ' + ((r && r.error) || 'ошибка').slice(0, 70); return; }
    const res = ['№ ' + ref.id + ' — снова «' + (r.status || 'Ожидает') + '»' + (r.moved ? ', время перенесено' : r.moveError ? ' (время не перенеслось: ' + r.moveError + ')' : '')];
    // в чат города — как пишут: «№ вернул в ожидает» (+ строка переноса)
    const c = await send({ kind: 'lcz-tg', args: { action: 'chats' } });
    const m = c && c.ok ? LC_TG.matchChat(c.chats, ref.dir, (S.prep && S.prep.cityText) || L.city || '') : null;
    if (m) {
      const text = ref.id + ' вернул в ожидает' + (r.lastChange ? '\n' + ref.id + ' ' + r.lastChange : '');
      const t = await вЧатГорода({ chat: m.id, text, conv: S.id }, { title: m.title });
      if (t && t.guard) { тостОтложено({ chat: m.id, text, conv: S.id }, t.guard); res.push('в «' + m.title + '» пока не писали: там ждёт ответа просьба филиала — см. уведомление «Просьба филиала ждёт ответа»'); }
      else res.push(t && t.ok ? 'в «' + m.title + '»: ' + text.replace('\n', ' · ') : 'в чат не ушло: ' + ((t && t.error) || 'ошибка'));
    } else res.push('чат города не найден — напишите «' + ref.id + ' вернул в ожидает» вручную');
    // диалог — к этой заявке; номер — в имя клиента LeadChat
    const сид = S.id, рек = { id: ref.id, url: ref.url, dir: ref.dir, at: Date.now(), city: (S.prep && S.prep.cityText) || L.city || '', returned: true };
    await правитьCreated((all) => { all[сид] = рек; });
    S.created = рек;
    const вДиалогP = номерВДиалог(сид, ref.id);                          // 12.10: № и в сам диалог LeadChat — вместе с именем
    const cl = S.conv && S.conv.client;
    if (cl && cl.id) { try { const want = nameWithId(cl.name || L.name || '', ref.id); if (want !== String(cl.name || '').trim()) await LC.put('/clients/' + encodeURIComponent(cl.id) + '/name', { name: want }); res.push('имя в LeadChat: «' + want + '»'); } catch (_e) { res.push('номер к имени в LeadChat не дописался'); } }
    const вДиалоге = await вДиалогP;
    if (вДиалоге) res.push(вДиалоге.ok ? 'в LeadChat: номер заявки записан в диалог' : 'в LeadChat номер заявки в диалог не записался');
    if (вДиалоге && (вДиалоге.twins || []).length) res.push('этот номер уже стоит у других диалогов LeadChat (' + вДиалоге.twins.length + ')');
    alertBox('Готово: ' + res.join(' · '), 'ok');
    btn.textContent = 'Возвращено ✓';
  }
  /* 1.20: действия — «Вернуть в «Ожидает»» через общий бегунок: защита от перекрытия чата города — ДО CRM (раньше CRM уже была
     сделана, а в чат не писали); замок и журнал — второе нажатие не вернёт дважды. Итог — сверху формы, как раньше */
  async function вернутьБегунком(ref, btn, my, force) {
    const L = my.lead, city = (my.prep && my.prep.cityText) || L.city || '', cl = my.conv && my.conv.client;
    const r = await ACT.вернутьВОжидает({ ref, conv: my.id, city, date: L.visit_date || '', time: L.visit_time || '', force,
      client: cl && cl.id ? { id: String(cl.id), name: cl.name || L.name || '' } : null,
      наВиду: () => S === my && panel.classList.contains('open') && convIdNow() === my.id,
      // CRM вернула — диалог к этой заявке (раньше Telegram: дальше расширение следит за сообщениями клиента)
      послеCRM: async () => {
        const рек = { id: ref.id, url: ref.url, dir: ref.dir, at: Date.now(), city, returned: true };
        await правитьCreated((all) => { all[my.id] = рек; });
        my.created = рек;
      } });
    if (S !== my) return;
    if (r.guard) {
      btn.disabled = false; btn.textContent = btn.dataset.label || 'Вернуть № ' + ref.id + ' в «Ожидает»';
      const pb = panel.querySelector('.pb'), box = перекрытиеBox(r.guard, () => { box.remove(); вернутьВОжидает(ref, btn); },
        () => { box.remove(); btn.disabled = true; btn.textContent = 'Возвращаем в «Ожидает»…'; вернутьБегунком(ref, btn, my, true); });
      if (pb) { pb.prepend(box); pb.scrollTop = 0; }
      return;
    }
    // уже вернули этим же нажатием (журнал действий) — кнопка не зовёт вернуть ещё раз
    if (r.состояние === 'уже') { btn.textContent = 'Уже возвращено ✓'; alertBox(r.text, 'ok'); return; }
    if (!r.ok && r.состояние !== 'частично') { btn.disabled = false; btn.textContent = 'Не вернулось: ' + String(r.text || 'ошибка').slice(0, 70); if (r.состояние === 'неясно') alertBox(r.text); return; }
    alertBox('Готово: ' + r.text, r.ok ? 'ok' : 'warn');
    btn.textContent = 'Возвращено ✓';
  }
  /* LeadChat ещё проверяет адрес картой — узнаём при открытии формы, а не только на «Создать»: строка в «Адресе» с «Подождать»
     (проверю ещё раз через минуту) и «Создать с адресом как в форме». Проверка при создании остаётся */
  async function адресLCНаФорме(again) {
    const my = S, cid = S && S.conv && S.conv.client && S.conv.client.id;
    if (!my || !cid || my.addrAsked || (!again && my.адресLC)) return;
    const было = (my.адресLC && my.адресLC.text) || '';
    my.адресLC = { busy: true, text: было };
    const text = await адресВПроверке(String(cid), my.id);
    my.адресLC = { text, done: !!было && !text };
    if (S === my && формаЭтого() && (text || было)) render2keep();
  }
  function адресLCBox() {
    const a = S && S.адресLC, my = S;
    if (!a || S.addrAsked) return '';
    if (a.done) return h('div', { class: 'n ok' }, 'LeadChat проверил адрес — нажмите ↻ «Прочитать диалог заново», чтобы взять проверенный');
    if (!a.text) return '';
    return h('div', { class: 'box warn', 'data-addr-lc': '1' }, svg('warn'), h('div', { class: 'c' },
      h('div', {}, h('b', {}, 'LeadChat ещё проверяет адрес по карте'), ' — это ~1–2 мин. Подождите — проверенный адрес возьмёт ↻ «Прочитать диалог заново».'),
      h('div', { class: 'row', style: 'gap:6px;margin-top:4px;flex-wrap:wrap' },
        h('button', { class: 'sm', disabled: !!(a.busy || a.wait), onclick: () => { a.wait = true; render2keep(); setTimeout(() => { if (S === my) адресLCНаФорме(true); }, 60e3); } },
          a.busy || a.wait ? 'Жду проверку LeadChat…' : 'Подождать'),
        // 2.3: «создать с адресом, как в форме» — надписью главной кнопки («Создать, не дожидаясь проверки адреса»)
        h('span', { class: 'n mut', style: 'align-self:center' }, 'или «Создать, не дожидаясь проверки» внизу'))));
  }
  /* Перед созданием: LeadChat ещё проверяет адрес картой (pending, error, blocked) — через ~1–2 мин он запишет или поправит адрес.
     Один запрос карточки, не дольше 5 с; LeadChat не ответил — не мешаем созданию. Клиент и диалог — из задачи, а не открытого чата */
  async function адресВПроверке(cid, conv) {
    if (!cid) return '';
    let idn = null;
    try { idn = await сТаймаутом(LC.get('/clients/' + encodeURIComponent(cid) + '/identity'), 5000, 'LeadChat не ответил'); } catch (_e) { return ''; }
    return LC_EXTRACT.адресПроверяется(idn, conv) ? 'LeadChat ещё проверяет адрес по карте — это ~1–2 мин. Подождите и нажмите ↻ «Прочитать диалог заново», чтобы взять проверенный адрес, или нажмите «Создать» ещё раз — создам с адресом, как в форме.' : '';
  }

  /* ---------- СОЗДАНИЕ В ФОНЕ: нажал «Создать» — можно уходить в другой чат ----------
     Нажатие снимает с формы ЗАДАЧУ — снимок полей, выбора, отписок и клиента LeadChat ЭТОГО диалога. Дальше задача идёт сама
     и не читает ни S, ни поля панели, ни открытый диалог: оператор мог уйти в другой чат, и запись о заявке, № в имени
     и отписка попали бы не в тот диалог (или пропали). Заявки в CRM создаются строго по одной на весь браузер (замок lcz-create):
     crm.create прямо перед созданием ищет номер во всех базах — вторая заявка на тот же номер дождётся первой и будет отклонена.
     Создание НИКОГДА не повторяется само: CRM не ответила вовсе — «не знаю, создалась ли», проверить по номеру. */
  const ЭТАПЫ = { start: 'Создаю заявку…', addr: 'Проверяю адрес в LeadChat…', bot: 'Проверяю номер в CRM (лид-бот)…',
    queue: 'Жду: создаётся предыдущая заявка…', create: 'Создаю заявку в CRM…', name: 'Пишу № в имя клиента LeadChat…', tg: 'Пишу в Telegram…' };
  const МОЖНО_УЙТИ = 'Можно перейти в другой чат — заявка создастся сама, итог придёт уведомлением.';
  const ВКЛАДКА = новыйId();                                         // чья запись в store 'jobs': чужая вкладка — не мы
  const ЗАДАЧИ_МС = 12 * 3600e3;
  // «не знаю, создалась ли» (CRM не ответила на создание) помним 15 мин: запись 'jobs' {state:'unknown'} — для всех вкладок
  const НЕЯСНО_МС = 15 * 60e3, НЕЯСНО_ТЕКСТ = 'не знаю, создалась ли заявка по этому диалогу — проверьте CRM по номеру';
  const копия = (x) => (x === undefined || x === null ? x : JSON.parse(JSON.stringify(x)));   // снимок не меняется вместе с формой
  const ПОДРЯД = new Map();
  // замок на весь браузер (navigator.locks); замков нет — по очереди в этой вкладке. fn не запускается дважды (это создание заявки)
  async function поОдному(name, fn) {
    let начато = false;
    const go = () => { начато = true; return fn(); };
    if (typeof navigator !== 'undefined' && navigator.locks && navigator.locks.request) {
      try { return await navigator.locks.request(name, go); } catch (e) { if (начато) throw e; /* замки недоступны — очередь вкладки */ }
    }
    const p = (ПОДРЯД.get(name) || Promise.resolve()).then(go);
    ПОДРЯД.set(name, p.catch(() => {}));
    return p;
  }

  /* запись в store 'jobs' — для других вкладок (не создать второй раз) и для перезагрузки посреди создания (сказать, на чём прервалось) */
  const записьЗадачи = (job) => ({ tab: ВКЛАДКА, key: job.key, state: 'run', at: job.at, beat: Date.now(), stage: job.ход.этап, conv: job.conv, name: job.name,
    ...(job.manualReview ? {manualReview:копия(job.manualReview)} : {}),
    phone: job.lead.phone || '', dir: job.dir, city: job.cityText, crmDone: !!job.ход.crmDone, id: job.ход.id || '', url: job.ход.url || '' });
  // другая вкладка начала (или кончила) создавать заявку по диалогу — «Готовые» и кэш проверки этой вкладки узнают сразу:
  // список, который ведут события, сам не перечитывается
  try {
    if (chrome.storage.onChanged) chrome.storage.onChanged.addListener((ch, area) => {
      if (area !== 'local' || !ch.jobs || !alive()) return;
      const было = ch.jobs.oldValue || {}, стало = ch.jobs.newValue || {};
      for (const [conv, x] of Object.entries(стало)) if (x && x.state === 'run' && x.tab !== ВКЛАДКА && !x.ack && !(было[conv] && было[conv].key === x.key)) заявкаПоДиалогуСменилась(conv, 'заявка по этому диалогу сейчас создаётся в другой вкладке');
      // другая вкладка: CRM не ответила на создание — «не знаю, создалась ли», а не «можно создавать»
      for (const [conv, x] of Object.entries(стало)) if (x && x.state === 'unknown' && x.tab !== ВКЛАДКА && !(было[conv] && было[conv].state === 'unknown' && было[conv].key === x.key)) { забытьПоискCRM(x.phone); заявкаПоДиалогуСменилась(conv, НЕЯСНО_ТЕКСТ); }
      for (const [conv, x] of Object.entries(было)) if (x && x.tab !== ВКЛАДКА && !стало[conv] && !задачаИдёт(conv)) заявкаПоДиалогуСменилась(conv, '');
    });
  } catch (_e) { /* без слежения — узнаем при следующей проверке */ }
  // токен вставили в настройках — уведомление «Нужен токен» убираем и проверяем открытый диалог заново (страницу обновлять не нужно)
  try {
    if (chrome.storage.onChanged) chrome.storage.onChanged.addListener((ch, area) => {
      if (area !== 'local' || !ch.brainToken || !ch.brainToken.newValue || !alive()) return;
      if (МОЗГ_ЭКРАН.токен) { МОЗГ_ЭКРАН.токен.remove(); МОЗГ_ЭКРАН.токен = null; }
      W.lastId = ''; W.at = 0; W.retryAt = 0;
      watchСкоро(500);
    });
  } catch (_e) { /* без слежения — узнаем при следующей проверке */ }
  /* задача жива, пока держит свой замок «lcz-job:<key>»: вкладку закрыли или перезагрузили — замок отпущен сам.
     Так фоновая вкладка, где таймеры «пульса» браузер придержал, не считается умершей; «пульс» — запасной признак (замков нет) */
  function держатьЗамокЗадачи(job) {
    if (typeof navigator === 'undefined' || !navigator.locks || !navigator.locks.request) return Promise.resolve();
    return new Promise((взят) => {
      try {
        navigator.locks.request('lcz-job:' + job.key, () => { взят(); return new Promise((r) => { job.ход.отпустить = r; }); }).catch(() => взят());
      } catch (_e) { взят(); }
    });
  }
  async function замкиЗадач() {
    try { const q = navigator.locks && navigator.locks.query ? await navigator.locks.query() : null; return q ? new Set((q.held || []).map((x) => x.name)) : null; } catch (_e) { return null; }
  }
  const держит = (held, x) => !!(held && x && held.has('lcz-job:' + x.key));
  async function занятьЗадачу(job) {
    try {
      return await поОдному('lcz-jobs', async () => {
        const all = (await store.get('jobs', {})) || {}, now = Date.now();
        const x = all[job.conv];
        // другая вкладка создаёт по этому диалогу и жива (держит замок задачи или «пульс» свежий) — не создаём
        if (x && x.state === 'run' && x.tab !== ВКЛАДКА && (now - (x.beat || x.at || 0) < 30e3 || держит(await замкиЗадач(), x))) return false;
        // вкладку с этой задачей перезагрузили посреди создания в CRM (форма могла уйти, а ответа нет): молча не перехватываем —
        // это нажатие говорит «проверьте CRM», запись помечаем; следующее (оператор проверил) — создаёт
        if (x && x.state === 'run' && x.tab !== ВКЛАДКА && !x.ack && (x.crmDone || /^(create|name|tg)$/.test(x.stage || ''))) {
          all[job.conv] = { ...x, ack: true, shown: true };
          await store.set('jobs', all);
          return { прервано: x };
        }
        for (const k of Object.keys(all)) if (!all[k] || now - (all[k].at || 0) > ЗАДАЧИ_МС || (all[k].state === 'unknown' && now - (all[k].unknownAt || all[k].beat || 0) > НЕЯСНО_МС)) delete all[k];
        all[job.conv] = записьЗадачи(job);
        await store.set('jobs', all);
        job.ход.запись = true;
        return true;
      });
    } catch (_e) { return true; }   // хранилище недоступно — другие вкладки не проверить; в этой вкладке задача по диалогу и так одна
  }
  async function снятьНеясно(conv) {
    let было = false;
    await поОдному('lcz-jobs', async () => {
      const all = (await store.get('jobs', {})) || {};
      if (!all[conv] || all[conv].state !== 'unknown') return;
      delete all[conv]; было = true;
      await store.set('jobs', all);
    });
    if (было) заявкаПоДиалогуСменилась(conv, '');
  }
  function записатьЗадачу(job, patch) {
    if (!job.ход.запись) return Promise.resolve();
    return поОдному('lcz-jobs', async () => {
      const all = (await store.get('jobs', {})) || {};
      const x = all[job.conv];
      if (!x || x.key !== job.key) return;                            // запись уже чужая (новая задача) — не трогаем
      if (patch === null) delete all[job.conv]; else all[job.conv] = { ...x, ...patch, beat: Date.now() };
      await store.set('jobs', all);
    }).catch(() => {});
  }
  function пульс(job) {
    clearTimeout(job.ход.пульсT);
    job.ход.пульсT = setTimeout(() => { if (job.ход.конец) return; записатьЗадачу(job, {}); пульс(job); }, 10e3);
  }
  // перезагрузка или закрытие вкладки посреди создания — браузер переспросит (иначе № в имени и отписка потерялись бы)
  const неУходить = (e) => { e.preventDefault(); e.returnValue = ''; return ''; };
  let уходСлушаю = false;
  function обновитьУход() {
    const идут = [...ЗАДАЧИ.values()].some((j) => !j.ход.конец);
    if (идут === уходСлушаю) return;
    уходСлушаю = идут;
    if (идут) window.addEventListener('beforeunload', неУходить); else window.removeEventListener('beforeunload', неУходить);
  }

  /* Расширение обновили или выключили посреди задачи — ответ фона сюда уже не придёт (обратный вызов может не вызваться вовсе):
     не ждём вечно («Создаю…» и вопрос при закрытии вкладки навсегда), а отдаём нет(). Срока на сам ответ нет — смотрим только,
     жива ли связь с расширением (раз в 2 с) */
  function покаЖиво(p, нет) {
    return new Promise((res, rej) => {
      let готово = false, t = 0;
      const конец = (f, x) => { if (готово) return; готово = true; clearTimeout(t); f(x); };
      const следить = () => { if (готово) return; if (!alive()) { конец(res, нет()); return; } t = setTimeout(следить, 2000); };
      Promise.resolve(p).then((x) => конец(res, x), (e) => конец(rej, e));
      t = setTimeout(следить, 2000);
    });
  }
  /* «не создана» от фона, но это сбой связи, а не ответ CRM: порт фон → CRM закрылся посреди создания или сеть оборвалась
     на отправке формы — заявка могла создаться. Отказ CRM (ошибки формы, «уже в работе», модерация, «вслепую не создаю»; refused —
     форма в CRM не уходила, даже если в тексте «Failed to fetch» с чтения) — как раньше */
  const безОтветаCRM = (r) => !r.ok && !r.skipped && !r.refused && !r.moderation && (!!r.unknown   // unknown: шлюз 5xx на отправке
    || (!(r.errors || []).length && !/вслепую не создаю/.test(String(r.error || ''))
      && /message port closed|context invalidated|Failed to fetch|NetworkError|Load failed/i.test(String(r.error || ''))));
  /* создание — без срока на клиенте (медленную удачную заявку не повторяем); ответа нет вовсе — это «не знаю», а не «не создана» */
  function отправитьСоздание(args) {
    if (!alive()) return Promise.resolve({ r: { ok: false, error: УСТАРЕЛО } });   // не отправляли — точно не создана
    return покаЖиво(new Promise((res) => {
      try {
        chrome.runtime.sendMessage({ kind: 'lcz-crm', op: 'create', args }, (r) => {
          if (r && typeof r === 'object') return res(безОтветаCRM(r) ? { сбой: String(r.error) } : { r });
          let why = '';
          try { why = alive() ? ((chrome.runtime.lastError && chrome.runtime.lastError.message) || '') : УСТАРЕЛО; } catch (_e) { why = УСТАРЕЛО; }
          res({ сбой: why || 'нет ответа от расширения' });
        });
      } catch (e) { res({ сбой: устарело(e) ? УСТАРЕЛО : String((e && e.message) || e) }); }
    }), () => ({ сбой: УСТАРЕЛО }));                                   // ушло в фон, а связи больше нет — создалась ли, неизвестно
  }

  // где оператор: на форме этого диалога / на ходе этой задачи (диалог открыт тот же — иначе обход вот-вот закроет панель)
  const наФормеЗадачи = (job) => panel.classList.contains('open') && convIdNow() === job.conv && !!S && S.id === job.conv && формаЭтого();
  const наХодеЗадачи = (job) => panel.classList.contains('open') && convIdNow() === job.conv && !!panel.querySelector('[data-job="' + job.key + '"]');
  // состояние диалога задачи: открытый S или запомненный (ПАМЯТЬ) — только для экрана, данные задача берёт из снимка
  const состояниеДиалога = (conv) => (S && S.id === conv ? S : (ПАМЯТЬ.get(conv) || {}).S || null);

  // кнопка «Создать» формы этого диалога: создаётся — шаг и не нажимается; нет — как обычно
  function кнопкаФормы() {
    if (!S || !формаЭтого()) return;
    const go = panel.querySelector('.pf .go');
    if (!go) return;
    const j = задачаИдёт(S.id);
    // 2.3: надпись — по ситуации (главнаяКнопка): создаётся — шаг и не нажимается, иначе «Создать…» / «Создать вторую…» и т. п.
    const old = go.closest('.cz-main');
    if (old) { const нов = главнаяБлок(); old.replaceWith(нов); }
    else { go.disabled = !!j || !(S.prep && S.prep.ok && S.prep.cityId); go.textContent = j ? j.ход.текст : 'Создать заявку' + (S.dir ? ' в ' + dirName(S.dir) : ''); }
    const go2 = panel.querySelector('.pf .go');
    const hint = panel.querySelector('[data-job-hint]');
    if (j && !hint && go2 && go2.closest('.cz-main')) go2.closest('.cz-main').after(h('div', { class: 'n mut', 'data-job-hint': '1' }, МОЖНО_УЙТИ));
    else if (!j && hint) hint.remove();
  }
  function этап(job, k) {
    const ход = job.ход;
    if (ход.конец) return Promise.resolve();
    ход.этап = k; ход.текст = ЭТАПЫ[k] || k;
    if (k === 'queue') ход.ждал = true;
    const запись = записатьЗадачу(job, { stage: k });                 // обещание — тому, кому важно, чтобы запись успела (шаг «в CRM»)
    try {                                                              // экран — не главное: сбой отрисовки не останавливает создание
      if (наФормеЗадачи(job)) кнопкаФормы();
      else if (наХодеЗадачи(job)) показатьХод(job);
      const d = ход.el && ход.el.querySelector('[data-job-stage]');
      if (d) d.textContent = ход.текст;                               // уведомление о ходе — то же, текст на месте
      задачиНаВиду();
    } catch (_e) { /* на следующем шаге или в итоге экран обновится */ }
    return запись;
  }
  // вернулся в диалог, пока создаётся: ход создания вместо формы (форма уже ушла в CRM). 2.1: строка на шаг — слева что, справа
  // «готово» / «сейчас» / «в очереди»; «Сообщения в Telegram» — только если они будут. Заявка уже в CRM (идут отписки) — итог
  function показатьХод(job) {
    const ход = job.ход;
    if (ход.создана && ход.r) { showDone(job, ход.r); return; }
    if (формаЭтого()) keepEdits();                                   // правки формы — в память диалога: форма уходит с экрана
    const телеграм = !!((job.отписать.avito && job.кодП) || job.отписать.reply || job.отписать.zakrepNot);
    const шаги = [job.addrAsked ? null : ['addr', 'Адрес в LeadChat'], job.needBotCheck ? ['bot', 'Номер в CRM (лид-бот)'] : null,
      ход.ждал ? ['queue', 'Очередь: предыдущая заявка'] : null, ['create', 'CRM: заявка, комментарии, клиент'],
      job.client.id ? ['name', '№ в имени клиента LeadChat'] : null, телеграм ? ['tg', 'Сообщения в Telegram'] : null].filter(Boolean);
    const i = Math.max(0, шаги.findIndex(([k]) => k === ход.этап));   // «start» (замок, запись) — это ещё первый шаг
    panel.classList.add('open');
    panel.dataset.conv = job.conv;
    panel.replaceChildren(h('div', { class: 'ph' }, header([job.name, dirName(job.dir), job.cityText].filter(Boolean).join(' · '))),
      h('div', { class: 'pb', 'data-job': job.key },
        h('section', { class: 'nx-card', role: 'status' },
          h('div', { class: 'nx-h' }, h('b', {}, 'Заявка создаётся'), h('span', { class: 'nx-sum' }, 'шаг ' + (i + 1) + ' из ' + шаги.length)),
          h('ol', { class: 'steps nx-steps' }, ...шаги.map(([k, t], n) => h('li', { class: n < i ? 'done' : n === i ? 'now' : 'wait' },
            h('span', { class: 'ic' }, n < i ? svg('check') : ''), h('span', { class: 'tx' }, n === i && k === ход.этап ? ход.текст : t),
            h('span', { class: 'nx-s' }, n < i ? 'готово' : n === i ? 'сейчас' : 'в очереди')))),
          h('div', { class: 'n mut' }, 'Можно уйти в другой диалог — доделаю сам и скажу, если что-то не получится. «Создать» второй раз нажимать не нужно.'))));
    задачиНаВиду();
  }
  // оператор не смотрит на задачу (закрыл панель, ушёл в другой чат) — одно тихое уведомление о ходе; вернулся — убираем.
  // Заявка уже в CRM (идут отписки) — вместо хода уведомление «Заявка № … создана» (рано)
  function задачиНаВиду() {
    for (const job of ЗАДАЧИ.values()) {
      const ход = job.ход;
      if (ход.конец || ход.создана) continue;
      if (наФормеЗадачи(job) || наХодеЗадачи(job)) { if (ход.el) { ход.el.remove(); ход.el = null; } }
      else if (!ход.el) ход.el = тостХода(job);                        // закрыл крестиком — второй раз не навязываем
    }
  }
  function тостХода(job) {
    return тост({ kind: 'info', low: true, label: 'Заявка создаётся', title: ['Создаётся заявка', job.name, job.cityText, dirName(job.dir)].filter(Boolean).join(' · '),
      lines: [h('div', { class: 'tst-d', 'data-job-stage': '1' }, job.ход.текст)],
      actions: [h('button', { class: 'sm', onclick: () => открытьДиалогЗадачи(job.conv, null, false) }, 'Открыть диалог')] });
  }
  /* 2.1 «СОЗДАНА» РАНЬШЕ: заявка есть в CRM и № — в имени LeadChat — сразу «Заявка № … создана»; сообщения в Telegram идут дальше
     в фоне, каждая строка обновляется на месте: «в очереди» → «отправляю…» → «готово» / «не ушло». Порядок и данные — те же
     (отписки после имени, запись о заявке, журнал); задача жива до конца отписок — вопрос при закрытии вкладки остаётся */
  function планОтписок(job, id) {
    const w = job.отписать || {}, out = [];
    if (w.avito && job.кодП) out.push({ k: 'avito', t: '«Созданные с Авито»' });
    if (w.reply) (job.соглП || []).forEach((x, i) => out.push({ k: 'reply:' + i, t: 'Ответ филиалу «' + id + ' создал»' + (x && x.title ? ' в «' + x.title + '»' : '') }));
    if (w.zakrepNot) out.push({ k: 'zakrepNot', t: '«' + id + ' не по закрепу» — в чат города' });
    return out.map((x) => ({ ...x, st: 'wait' }));
  }
  const СОСТ_ОТПИСКИ = { wait: ['в очереди', 'mut'], send: ['отправляю…', 'info'], ok: ['готово', 'ok'], bad: ['не ушло', 'bad'],
    hold: ['ждёт ответа филиала', 'warn'], unknown: ['не знаю, ушло ли', 'warn'] };
  /* 12.10: № заявки в самом диалоге LeadChat — строкой итога: записан / не записался (почему); тот же № уже у других диалогов —
     предупреждение со ссылками «Открыть» на них (переход внутри LeadChat). LeadChat старше (ручки нет, r.lcCrm = null) — строки нет */
  const ссылкиДвойников = (twins) => twins.slice(0, 5).flatMap((id, i) => [i ? ', ' : '',
    h('a', { href: '/chats/' + encodeURIComponent(id), 'data-lc-twin': id, onclick: (e) => { e.preventDefault(); перейти(id).catch(() => {}); } }, twins.length > 1 ? 'Открыть ' + (i + 1) : 'Открыть')]);
  function строкиНомераLC(r, ln) {
    const x = r && r.lcCrm;
    if (!x) return [];
    const out = [x.ok ? ln('В LeadChat: номер заявки записан в диалог', 'готово', 'ok', { 'data-lc-crm': 'ok' })
      : ln('В LeadChat: номер заявки в диалог не записался — ' + String(x.error || 'ошибка').slice(0, 120), 'не вышло', 'warn', { 'data-lc-crm': 'bad' })];
    if ((x.twins || []).length) out.push(h('div', { class: 'nx-ln warn', 'data-lc-twins': x.twins.join(',') },
      h('span', { class: 'tx' }, 'Этот номер уже стоит у других диалогов LeadChat: ', ...ссылкиДвойников(x.twins)), h('span', { class: 'nx-s' }, 'проверьте')));
    return out;
  }
  // строки «что сделано» по задаче: CRM, имя в LeadChat, карточка клиента, сообщения в Telegram (по плану — с их состоянием)
  function строкиПлана(job, r, кратко) {
    const ln = (t, st, cls, attrs) => h('div', { class: 'nx-ln ' + (cls || ''), ...(attrs || {}) }, h('span', { class: 'tx' }, t), h('span', { class: 'nx-s' }, st));
    return [
      кратко ? '' : ln('CRM: заявка, комментарии, клиент', 'готово', 'ok'),
      r.lcName ? ln('Имя в LeadChat «' + r.lcName.name + '»', r.lcName.ok ? 'готово' : 'не дописалось', r.lcName.ok ? 'ok' : 'warn') : '',
      ...строкиНомераLC(r, ln),
      !кратко && карточкаКлиента(r) ? ln(карточкаКлиента(r), 'готово', 'ok') : '',
      ...(job.ход.план || []).map((x) => { const [st, cls] = СОСТ_ОТПИСКИ[x.st] || СОСТ_ОТПИСКИ.wait; return ln(x.t, st, cls, { 'data-plan-line': x.k }); })];
  }
  // блок строк, который обновляется по ходу отписок (экран итога и уведомление — оба)
  function планБлок(job, r, кратко) {
    const box = h('div', { class: 'nx-lines' + (кратко ? ' sm' : ''), 'data-plan': job.key }, ...строкиПлана(job, r, кратко));
    box._кратко = !!кратко;
    (job.ход.планы = job.ход.планы || new Set()).add(box);
    return box;
  }
  function шагОтписки(job, k, st, x) {
    const ход = job.ход, п = (ход.план || []).find((y) => y.k === k);
    if (!п) return;
    п.st = st; if (x) п.x = x;
    обновитьПланы(job);
  }
  // строки «что сделано» на экране итога и в уведомлении — заново (сообщение ушло, № записан в диалог LeadChat)
  function обновитьПланы(job) {
    const ход = job.ход;
    for (const box of [...(ход.планы || [])]) {
      // блок ушёл с экрана насовсем (итог перерисован, уведомление убрано) — не держим
      if (!box.isConnected && !(ход.готовоEl && ход.готовоEl.contains(box))) { ход.планы.delete(box); continue; }
      box.replaceChildren(...строкиПлана(job, ход.r || {}, box._кратко));
    }
  }
  function рано(job, r) {
    const ход = job.ход;
    const наФорме = наФормеЗадачи(job), наХоде = наХодеЗадачи(job);
    ход.создана = true; ход.r = r;
    try {
      if (ход.el) { ход.el.remove(); ход.el = null; }
      if (convIdNow() === job.conv) btnState({ creating: false, done: true, ready: false, id: r.id || null });
      if (наФорме || наХоде) showDone(job, r); else ход.готовоEl = тостГотово(job, r);
    } catch (_e) { /* экран — не главное: отписки идут дальше */ }
  }
  // по диалогу идёт создание и заявки в CRM ещё нет (после «создана» кнопка — «№ …», а не «Создаётся…»)
  const идётДоCRM = (conv) => { const j = задачаИдёт(conv); return j && !j.ход.создана ? j : null; };

  // This permission lives only during the dialog's confirm callback. It is
  // neither saved with drafts nor usable by the personal assistant.
  let ручноеРазрешение = null, ручноеПодтверждение = null;
  function показатьРучноеПодтверждение(review, f, proceed) {
    if (ручноеПодтверждение) ручноеПодтверждение.close(false);
    const before = root.activeElement, inert = [...panel.children].map(el=>({el,value:el.inert}));
    let done = false, observer;
    const close = (restore = true) => {
      if (done) return; done=true;
      observer?.disconnect(); layer.remove();
      for (const item of inert) item.el.inert=item.value;
      if (ручноеПодтверждение?.el===layer) ручноеПодтверждение=null;
      if (restore && before?.isConnected) before.focus({preventScroll:true});
    };
    const cancel = h('button',{class:'go2',type:'button',onclick:()=>close()},'Назад');
    const submit = h('button',{class:'go warn',type:'button',onclick:()=>{if(done)return;close(false);proceed();}},'Создать');
    const list = h('ol',{class:'manual-confirm-list',tabindex:'0','aria-label':'Предупреждения'},...review.warnings.map(t=>h('li',{},t)));
    const field = (label,value) => [h('dt',{},label),h('dd',{},value||'Не указано')];
    const layer = h('div',{class:'manual-confirm-backdrop'},h('div',{
      class:'manual-confirm',role:'alertdialog','aria-modal':'true','aria-labelledby':'manual-confirm-title','aria-describedby':'manual-confirm-note',tabindex:'-1'},
      h('h3',{id:'manual-confirm-title',class:'manual-confirm-title'},'Создать с предупреждениями?'),
      h('dl',{class:'manual-confirm-summary'},...field('База',dirName(S.dir)),...field('Город',S.prep.cityText||f.lead.city),
        ...field('Работа',(S.prep.appl||[]).find(x=>x.id===f.sel.applId)?.text||f.lead.problem),...field('Телефон',fmtPhone(f.lead.phone))),
      list,
      h('p',{id:'manual-confirm-note',class:'manual-confirm-note'},'Ручное создание. Замечания останутся в журнале.'),
      h('div',{class:'manual-confirm-actions'},cancel,submit)));
    for(const item of inert)item.el.inert=true;
    panel.append(layer);
    const key = e => {
      if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close();return true;}
      if(e.key==='Tab'){
        e.preventDefault();e.stopPropagation();
        const targets=[list,cancel,submit],index=targets.indexOf(root.activeElement);
        targets[index<0?1:(index+(e.shiftKey?-1:1)+targets.length)%targets.length].focus();return true;
      }
      if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();e.stopPropagation();return true;}
      return false;
    };
    ручноеПодтверждение={el:layer,close,key};
    // Async form refresh or navigation invalidates the displayed review.
    observer=new MutationObserver(()=>{if(!layer.isConnected||!panel.classList.contains('open')||!формаЭтого())close(false);});
    observer.observe(panel,{childList:true,attributes:true,attributeFilter:['class','data-conv']});
    cancel.focus({preventScroll:true});
  }
  function createNow() {
    const once=arguments[0];
    if (!S || !S.prep || !S.prep.ok || !формаЭтого()) return;   // на экране форма другого диалога — из неё не создаём
    // форма CRM ещё готовится (сменили базу, вид работ, город): город, вид работ и услуг в форме — от прежней подготовки, не создаём
    if (S.готовлю) return;
    if (!S.check || S.check.busy || !S.check.ok || S.check.reviewed_policy !== true) {
      alertBox('Проверка действующего регламента ещё не завершена. Дождитесь результата или повторите проверку.');
      return;
    }
    if (S.check.hard_block && S.check.manual_creation?.available !== true) { alertBox(S.check.refuse || S.check.reason || S.check.approval || 'Создание остановлено действующим правилом'); return; }
    // по диалогу заявка уже создаётся — второе нажатие и Ctrl+Enter ничего не шлют, только показывают ход
    if (задачаИдёт(S.id)) { кнопкаФормы(); return; }
    const f = readForm();
    const выбранныйФилиал = String(f.sel.cityId || '');
    const подготовленныйФилиал = String(S.prep.cityId || '');
    const маршрут = S.check.crm_route?.city_id;
    if (маршрут && (выбранныйФилиал !== String(маршрут) || подготовленныйФилиал !== String(маршрут))) {
      alertBox('Филиал в форме не совпадает с маршрутом по регламенту. Перечитайте диалог и проверьте филиал.'); return;
    }
    if (выбранныйФилиал && выбранныйФилиал !== подготовленныйФилиал) {
      alertBox('Филиал в форме изменился после подготовки. Обновите форму и проверьте филиал.'); return;
    }
    const manualReview = LC_WORKFLOW.manualCreationReview(S.check,S.terr,f.lead);
    const locationIssue=LC_WORKFLOW.territoryIssue(S.terr,f.lead);
    if((S.check.hard_block||locationIssue)&&!manualReview.available){alertBox(locationIssue||S.check.reason||'Ручное подтверждение недоступно. Обновите проверку регламента.');return;}
    if (!маршрут && выбранныйФилиал && !locationIssue && S.terr?.ok && S.terr.address_verified === true) {
      const филиалКарты = (S.terr.special || []).find(x => x.branch)?.branch || S.terr.branch;
      if (филиалКарты && безСкобокГород(филиалКарты) !== безСкобокГород(S.prep.cityText)) {
        alertBox('Филиал по карте «' + филиалКарты + '» не совпадает с выбранным филиалом. Проверьте адрес и выберите нужный филиал.'); return;
      }
    }
    const форма = отпечатокФормы(f, S.dir);                             // до правок снимка ниже (закреп, регламент)
    panel.querySelectorAll('.bad-f').forEach((e) => e.classList.remove('bad-f'));
    // всё, что не пускает, — одним сообщением; курсор — в первое такое поле формы (а не наверх), подсветка уходит с первой правкой поля
    const стоп = [], плохие = [], miss = [];
    const mark = (k) => { const e = panel.querySelector('[data-f="' + k + '"]'); if (e) { e.classList.add('bad-f'); плохие.push(e); } return !!e; };
    if (f.lead.phone.length !== 10) { miss.push('телефон'); mark('phone'); }
    if (!f.lead.addr.street && !f.lead.addr.settlement) { miss.push('адрес'); mark('street'); }
    if (!f.sel.cityId) { miss.push('город'); mark('cityId'); }
    if (f.lead.ad_identity_required && !f.lead.ad_identity) { miss.push('имя мастера из объявления / название аккаунта'); mark('ad_identity'); }
    if (miss.length) стоп.push('Не хватает: ' + miss.join(', ') + '.');
    { const вп = визитПроблема(f.lead); if (вп.block) { mark(вп.field); стоп.push('Не создаю: ' + вп.block + '.'); }
      // 2.2.7: окно клиента со сроком, а по регламенту уже не успеваем — на позднее время молча не создаём
      else if (вп.окно) { mark(вп.field); стоп.push('Не создаю: ' + вп.warn + '.'); } }
    // 2.1.1 (штраф КП 2684667): адрес из прошлого обращения, в этом диалоге его не называли — сначала спросить клиента
    if (прошлыйАдрес(f.lead)) { стоп.push((прошлыйКарточки(f.lead) ? 'Адрес — из прошлого обращения клиента, в этом диалоге его не называли.' : 'Тип «' + типЗаявки() + '» — по регламенту адрес сверяют с клиентом, а в этом диалоге его не называли.')
      + ' Спросите, куда нужен мастер сейчас: «Клиент подтвердил: адрес тот же» или впишите новый.'); mark('street'); }
    // клиент уже есть в CRM: адрес заявки — из его карточки; без номера дома карточку не правим — уехал бы прежний адрес
    else if (S.prep.customer && S.prep.customer.id && (f.lead.addr.street || f.lead.addr.settlement) && !String(f.lead.addr.building || '').trim()) {
      стоп.push('Номер дома: клиент уже есть в CRM — без дома в заявке останется его прежний адрес.'); mark('building'); }
    // номер карточки LeadChat под сомнением (объединена, связь «предположительно») — только после отметки «сверил»
    if (f.lead.phone_risky && f.lead.phone === f.lead.phone_risky && !f.lead.phone_ok) {
      стоп.push('Номер ' + fmtPhone(f.lead.phone) + ' — из карточки LeadChat, а она под сомнением: ' + (f.lead.phone_warn || '') + '. Сверьте номер с клиентом и отметьте «номер сверил».');
      mark('phoneOk') || mark('phone');
    }
    if (белаяНаБТ(f.lead, S.dir) && !S.allowWhite) { стоп.push('Белая заявка (партнёр 723 / источник «Белый …») — на БТ не создаём, только КП и МНЧ. Если всё же нужно в БТ — отметьте «всё равно создать в БТ».'); mark('allowWhite'); }
    const R = историяКлиента();
    const allowNewEl = panel.querySelector('[data-f="allowNew"]');
    if (R && R.action === 'вернуть' && !(allowNewEl && allowNewEl.checked)) { стоп.push('По регламенту верните заявку № ' + R.ref.id + ' в «Ожидает», а не создавайте новую. Если всё же нужна новая — отметьте «всё равно создать новую».'); mark('allowNew'); }
    if (стоп.length) {
      for (const e of плохие) { const снять = () => { e.classList.remove('bad-f'); e.removeEventListener('input', снять); e.removeEventListener('change', снять); }; e.addEventListener('input', снять); e.addEventListener('change', снять); }
      const первое = плохие.slice().sort((a, b) => (a.compareDocumentPosition(b) & 4 ? -1 : 1))[0];   // 4 — b после a
      alertBox(стоп.length === 1 ? стоп[0] : h('div', { style: 'display:flex;flex-direction:column;gap:4px' }, ...стоп.map((t) => h('div', {}, t))), '', первое);
      return;
    }
    // No persistent waiver: every attempt reviews the current form's warnings.
    // This never answers a question, marks consent, or enables the assistant.
    if (manualReview.available && manualReview.warnings.length) {
      const signature=JSON.stringify([S.id,S.lastId,форма,manualReview]);
      if (!once || once!==ручноеРазрешение || once.state!==S || once.check!==S.check || once.signature!==signature) {
        const state=S,check=S.check;
        показатьРучноеПодтверждение(manualReview,f,()=>{
          if(S!==state||S.check!==check||!формаЭтого()||signature!==JSON.stringify([S.id,S.lastId,отпечатокФормы(readForm(),S.dir),LC_WORKFLOW.manualCreationReview(S.check,S.terr,readForm().lead)])){
            alertBox('Данные или предупреждения изменились. Проверьте заявку и нажмите «Создать» снова.');return;
          }
          const permit={state,check,signature};ручноеРазрешение=permit;
          try{createNow(permit)}finally{ручноеРазрешение=null}
        });
        return;
      }
      manualReview.operator_confirmed=true;
      manualReview.confirmed_at=Date.now();
      manualReview.last_message_id=S.lastId||'';
    }
    // Owner 17.10: an unset choice is neutral, not a forced pin/exception.
    применитьЗакреп(f.lead);
    // кв/подъезд/этаж не заполнены — не останавливаем создание (оператор просил убрать окно с повторным нажатием)
    // «Создать ещё одну» уже подтверждено на экране «заявка уже создана» — второй раз не спрашиваем (один раз)
    if (S.created && !S.ещёОк && !confirm('По этому диалогу заявка уже создана. Создать ещё одну?')) return;
    S.ещёОк = false;
    if (R && R.comment) {
      if (!new RegExp(R.comment.replace(/[!.]/g, '\\$&'), 'i').test(f.lead.comment || '')) f.lead.comment = [String(f.lead.comment || '').replace(/\s+$/, ''), R.comment].filter(Boolean).join('\n');
      f.lead.service_comment = [R.comment, f.lead.service_comment].filter(Boolean).join('\n');
    }
    // регламент 09.10 (работа в чатах): ссылка на диалог с клиентом — обязательно в «Служебный комментарий»
    { const ссылка = location.origin + '/chats/' + encodeURIComponent(S.id);
      if (!String(f.lead.service_comment || '').includes(ссылка)) f.lead.service_comment = [f.lead.service_comment, ссылка].filter(Boolean).join('\n'); }
    // регламент 09.10: в «Комментарий партнёра» — только код (Б7 / С74.2 / В43), без «источник», «белый» и т.п.
    { const код = LC_TG.кодИсточника(f.lead.partner_note); if (код) f.lead.partner_note = код; }
    const pc = (k) => { const e = panel.querySelector('[data-post="' + k + '"]'); return !!(e && e.checked); };
    // «создал» — тому филиалу, который согласовал (последний в очереди; отказавшим не пишем)
    const отписать = { avito: pc('avito'), reply: pc('reply') && (S.tgReplies || []).length > 0, zakrepNot: S.zkChoice === 'not' }, кодП = кодАккаунта(f.lead), соглП = sentList(S.tgSent).slice(-1);
    // согласование отправлено, филиал ещё не ответил — «создал» писать некому; после создания скажем об этом
    const ответилП = (S.tgReplies || []).length > 0 && соглП.length > 0, ждёмП = !ответилП && соглП.length && !(S.tgSent && S.tgSent.done) ? соглП : null;
    // ЛИД-БОТ: «проверил в CRM — всё равно создать» не отмечено — номер ещё раз ищется во всех базах (уже в задаче)
    const allowBotEl = panel.querySelector('[data-f="allowBot"]');
    const P = S.prep, cl = (S.conv && S.conv.client) || {};
    const текстИз = (list, id) => ((list || []).find((o) => o.id === id) || {}).text || '';
    // СНИМОК: дальше задача не читает ни S, ни форму, ни открытый диалог
    запустить({ key: новыйId(), conv: S.id, dir: S.dir, lead: копия(f.lead), sel: копия(f.sel), allowLive: f.allowLive,
      advertiserCtx: копия(S.ctx || {}),
      ...(manualReview.operator_confirmed ? {manualReview:копия(manualReview)} : {}),
      отписать, кодП, безКодаП: кодП ? '' : безКода(S.conv), соглП: копия(соглП), ответилП, ждёмП: ждёмП ? копия(ждёмП) : null,
      client: { id: String(cl.id || ''), name: cl.name || '' }, leadName: S.lead.name || '', name: f.lead.name || cl.name || 'клиент',
      cityText: P.cityText || f.lead.city || '', applText: текстИз(P.appl, f.sel.applId), subText: текстИз(P.sub, f.sel.subId),
      минДо: минимумДоВизита(S.terr),
      // своё время (ближайшее по регламенту, не правленое) — пересчитать от момента отправки (зона — как сейчас в форме)
      ближайшее: визитАвто(f.lead) && f.lead.visit_auto.kind === 'ближайшее' ? (({ плюс, ранняя }) => ({ плюс, ранняя }))(зонаБлижайшего(f.lead, S.terr, S.prep)) : null,
      // 2.2.7: окно клиента — при отправке за срок не сдвигаем (своё время пересчитывается в окне, «не ближе часа» — не позже срока − 30 мин)
      окно: окноКлиента(f.lead) ? копия(окноКлиента(f.lead)) : null,
      needBotCheck: !!(лидБот(S.ctx && S.ctx.messages, S.conv) && !(allowBotEl && allowBotEl.checked)), addrAsked: !!S.addrAsked, at: Date.now(), форма,
      послАт: Math.max(0, ...((S.ctx && S.ctx.messages) || []).map((m) => Date.parse(m.created_at) || 0)) });   // последнее сообщение снимка (часы LeadChat)
  }
  // снимок → задача: в список, кнопка — «создаётся», дальше сама (оператор может уйти)
  function запустить(snap) {
    if (задачаИдёт(snap.conv)) return null;
    const job = Object.freeze({ ...snap, ход: { этап: 'start', текст: ЭТАПЫ.start, конец: '', el: null } });
    ЗАДАЧИ.set(job.conv, job);
    обновитьУход();
    const наФорме = наФормеЗадачи(job);
    if (наФорме) запомнитьДиалог().catch(() => {});                     // форма как есть — в память (до первого шага задачи): уйдёт и вернётся (или не создастся) — правки на месте
    // задача стартует раньше экрана: сбой отрисовки не должен оставить её «создаётся» навсегда
    выполнить(job).catch((e) => завершить(job, job.ход.crmDone ? { итог: 'ok', r: job.ход.r }
      : { итог: 'fail', r: { ok: false, error: 'Не получилось: ' + String((e && e.message) || e).slice(0, 160) } }));
    try {
      заявкаПоДиалогуСменилась(job.conv, 'заявка по этому диалогу сейчас создаётся');   // «Готовые», автоприём, окошко «Новые» — уже не «можно создавать»
      // диалог открыт: карточка «Заявку можно создавать» (запуск из уведомления «Создать как есть») — убираем, кнопка «Создаётся…»
      if (convIdNow() === job.conv) { hideCard(); btnState({ creating: true }); }
      if (наФорме) кнопкаФормы();
      задачиНаВиду();
    } catch (_e) { /* экран — не главное, задача уже идёт */ }
    return job;
  }
  async function выполнить(job) {
    const ход = job.ход;
    await держатьЗамокЗадачи(job);                                     // сначала замок, потом запись: запись без живого замка — признак обрыва
    const занята = await занятьЗадачу(job);
    if (!занята) return завершить(job, { итог: 'чужая', текст: 'Заявка по этому диалогу уже создаётся в другой вкладке' });
    if (занята.прервано) {
      const x = занята.прервано;
      if (x.crmDone && x.id) return завершить(job, { итог: 'fail', r: { ok: false, skipped: true, error: 'по этому диалогу заявка № ' + x.id + ' уже создана (до перезагрузки страницы) — вторую не создаю. № в имени LeadChat и отписку в Telegram проверьте вручную' } });
      return завершить(job, { итог: 'неясно', текст: 'прошлое «Создать» по этому диалогу прервалось перезагрузкой страницы на шаге «' + String(ЭТАПЫ[x.stage] || x.stage || '—').replace(/…$/, '')
        + '». Нет в CRM — нажмите «Создать» ещё раз' });
    }
    пульс(job);
    job.tgЗаранее = заранееTG(job);                                     // 2.1.1: Telegram готовится, пока идут проверки и CRM
    // карточка LeadChat заново: адрес ещё проверяется картой — сказать один раз («Создать» ещё раз — создать как есть)
    if (!job.addrAsked) {
      этап(job, 'addr');
      const ждёт = await адресВПроверке(job.client.id, job.conv);
      if (ждёт) return завершить(job, { итог: 'адрес', текст: ждёт });
    }
    // ЛИД-БОТ: бот-диалоги заводит в CRM его очередь — прямо перед созданием ещё раз ищем номер во всех базах
    if (job.needBotCheck) {
      этап(job, 'bot');
      const chk = await проверкаЛидБота(job.lead, job.dir);
      if (!chk.ok) return завершить(job, { итог: 'бот', chk });
      const st = состояниеДиалога(job.conv);
      if (st) st.botCheck = chk;
      if (наФормеЗадачи(job)) { const bb = panel.querySelector('[data-bot]'); if (bb) bb.replaceWith(ботBox()); }
    }
    // в CRM — по одной заявке на весь браузер; ждём предыдущую — так и пишем
    const ждём = setTimeout(() => этап(job, 'queue'), 300);
    let ответ = null, отказОкна = '';
    try {
      await поОдному('lcz-create', async () => {
        clearTimeout(ждём);
        // 13.10: своё время (ближайшее по регламенту, оператор не правил) — от момента отправки, как «Через час» / «+2ч» в CRM:
        // пока шли проверки и очередь, минуты убежали. Не раньше прежнего; позже 21:30 — на завтра к началу приёма.
        // 2.2.7: окно клиента — ближайшее в окне; ушло за срок минус 30 мин — не создаём (молча на позднее время нельзя)
        const w = job.окно;
        const бл = job.ближайшее && job.lead.clock ? (w ? LC_EXTRACT.времяВОкне(job.lead.clock, w, { ...job.ближайшее, день: job.lead.visit_date }) : LC_EXTRACT.ближайшееПоРегламенту(job.lead.clock, job.ближайшее)) : null;
        if (бл && w && !бл.ок) { отказОкна = срокНеУспеваем(w, бл.date + ' ' + бл.ближ); return; }
        // «не ближе часа» (территория «за 2 ч» — двух) тоже не сдвигает за срок окна
        const заСрок = (x) => !!(w && w.until && x && (!w.date || x.date === w.date) && минЧ(x.time) > минЧ(w.until) - 30);
        { const до = бл && (бл.date > job.lead.visit_date || (бл.date === job.lead.visit_date && бл.time > job.lead.visit_time)) ? бл : job.lead;
          const с = неБлижеМинимума({ ...job.lead, visit_date: до.date || до.visit_date, visit_time: до.time || до.visit_time }, job.минДо);
          if (заСрок(с)) { отказОкна = срокНеУспеваем(w, с.date + ' ' + с.time); return; } }
        // запись «в CRM» — до отправки: вкладку перезагрузят посреди создания — другая (и эта после F5) знают, что форма могла уйти
        await этап(job, 'create');
        if (бл && (бл.date > job.lead.visit_date || (бл.date === job.lead.visit_date && бл.time > job.lead.visit_time))) {
          job.lead.visit_date = бл.date; job.lead.visit_time = бл.time;
          if (бл.завтра) ход.ближайшееЗавтра = бл;
          if (наФормеЗадачи(job)) for (const [k, v] of [['visit_date', бл.date], ['visit_time', бл.time]]) { const e = panel.querySelector('[data-f="' + k + '"]'); if (e) e.value = v; }
        }
        const сдвиг = неБлижеМинимума(job.lead, job.минДо);
        if (сдвиг) {
          job.lead.visit_date = сдвиг.date; job.lead.visit_time = сдвиг.time; ход.сдвигВремени = сдвиг;
          if (наФормеЗадачи(job)) { const e = panel.querySelector('[data-f="visit_time"]'); if (e) e.value = сдвиг.time; }
        }
        ответ = await отправитьСоздание({ dir: job.dir, lead: job.lead, sel: job.sel, allowLive: job.allowLive, advertiserCtx: job.advertiserCtx });
      });
    } finally { clearTimeout(ждём); }
    if (отказОкна) return завершить(job, { итог: 'окно', текст: отказОкна });
    if (ответ.сбой) return завершить(job, { итог: 'неясно', текст: ответ.сбой });   // НЕ повторяем: заявка могла создаться
    const r = ответ.r;
    if (!r.ok) return завершить(job, { итог: 'fail', r });
    if (job.manualReview?.operator_confirmed) (r.warnings=r.warnings||[]).push('Создано вручную с предупреждениями: '+job.manualReview.warnings.join('; '));
    ход.crmDone = true; ход.id = r.id || ''; ход.url = r.url || ''; ход.r = r;
    if (ход.сдвигВремени) (r.warnings = r.warnings || []).push('время визита — ' + ход.сдвигВремени.time + ' вместо ' + ход.сдвигВремени.было
      + ': до визита оставалось меньше ' + (ход.сдвигВремени.минДо === 60 ? 'часа' : (ход.сдвигВремени.минДо / 60).toString().replace('.', ',') + ' ч') + ' (регламент)');
    if (ход.ближайшееЗавтра) (r.warnings = r.warnings || []).push('время визита — завтра ' + ход.ближайшееЗавтра.time + ': ближайшее по регламенту уже позже 21:30 (позже — только по согласованию) — уточните у клиента');
    записатьЗадачу(job, { crmDone: true, id: ход.id, url: ход.url });
    const at = Date.now();
    // seenAt — миг нажатия «Создать» (снимок формы): что клиент написал после него (пока шли проверки, очередь, CRM), в заявку не вошло —
    // наблюдение «клиент дописал / перенёс / отменил» разберёт это как новое, а не как давно прочитанное. «Создать как есть» шлёт прежний
    // снимок — миг первого «Создать» (снят). Сравнивается с created_at LeadChat — поэтому в часах LeadChat: последнее сообщение снимка
    // (послАт); часы ПК (снят / at) — только когда в снимке сообщений нет. Часы ПК спешат — дописанное во время создания не пропадёт;
    // написанное между сборкой формы и «Создать» покажется лишней карточкой «дописал» — это безопасно
    const rec = { id: r.id, url: r.url, dir: job.dir, at, seenAt: job.послАт > 0 ? job.послАт : (job.снят || job.at), city: job.cityText,
      visit: [job.lead.visit_date, job.lead.visit_time].filter(Boolean).join(' '), src: job.lead.partner_note || '',
      work: [job.applText, job.subText].filter(Boolean).join(' · '), ...(карточкаКлиента(r) ? { customerNote: карточкаКлиента(r) } : {}) };
    try {
      await поОдному('lcz-created', async () => { const created = await store.get('created', {}); created[job.conv] = rec; await store.set('created', created); });
    } catch (e) { (r.warnings = r.warnings || []).push('расширение не запомнило, что заявка по диалогу создана (' + String((e && e.message) || e).slice(0, 80) + ')'); }
    // журнал смены: что создано, где, с какими предупреждениями
    try {
      await поОдному('lcz-created', async () => {
        const j = await store.get('journal', []);
        j.push({ at, id: r.id || null, url: r.url || '', dir: job.dir, conv: job.conv, name: job.lead.name || '', city: job.cityText,
          appl: job.applText, sub: job.subText, visit: rec.visit, warns: (r.warnings || []).length,
          ...(job.manualReview ? {manualReview:копия(job.manualReview)} : {}) });
        await store.set('journal', j.slice(-300));
      });
    } catch (_e) { /* журнал — не главное */ }
    const st = состояниеДиалога(job.conv);
    if (st) st.created = rec;
    // 12.10: № заявки — и в сам диалог LeadChat (crm_request_id): второй заявки на того же человека там не заведут. Параллельно с именем
    // и Telegram — ничего не ждёт; итог — строкой на экране «Заявка создана» (тот же № у других диалогов — предупреждение со ссылками)
    const вДиалогP = r.id ? номерВДиалог(job.conv, r.id).then((x) => { r.lcCrm = x; try { обновитьПланы(job); } catch (_e) { /* экран — не главное */ } return x; }) : null;
    // 2.1.1: сообщения в Telegram — сразу с номером заявки, одновременно с именем в LeadChat (друг от друга не зависят)
    r.posts = [];
    const телеграм = !!(r.id && ((job.отписать.avito && job.кодП) || job.отписать.reply || job.отписать.zakrepNot));
    let отпискиP = null;
    if (телеграм) {
      ход.план = планОтписок(job, r.id);
      отпискиP = покаЖиво(отписатьСозданную(r.id, job.отписать, job.кодП, job.соглП || [], job.conv, job.dir, job.cityText, (k, st, x) => шагОтписки(job, k, st, x), job.tgЗаранее),
        () => [{ ok: false, text: 'Сообщения в Telegram не завершены: ' + УСТАРЕЛО + ' — проверьте «Созданные с Авито» и чат города, допишите вручную' }])
        .catch((e) => [{ ok: false, text: 'В Telegram не отправилось: ' + (e.message || e) }]);
    }
    // номер заявки — в имя клиента LeadChat ЭТОГО диалога (за основу — имя, как оно в LeadChat)
    if (r.id && job.client.id) {
      этап(job, 'name');
      const want = nameWithId(job.client.name || job.leadName || '', r.id);
      try {
        if (want !== String(job.client.name || '').trim()) await LC.put('/clients/' + encodeURIComponent(job.client.id) + '/name', { name: want });
        r.lcName = { ok: true, name: want };
      } catch (e) { r.lcName = { ok: false, name: want, error: String(e.message || e) }; }
    }
    if (телеграм) {
      этап(job, 'tg');
      // 2.1: в CRM есть, № в имени — «Заявка № … создана» видно уже сейчас; сообщения в Telegram — уже идут, строка на каждое
      рано(job, r);
      r.posts = await отпискиP;
      // строки, которые так и остались «в очереди» / «отправляю…» (связь оборвалась посреди) — не ушли
      for (const x of ход.план) if (x.st === 'wait' || x.st === 'send') x.st = 'bad';
    }
    // что не отписано и почему — тоже на экран: пропуск никогда не молчит
    r.posts = (r.posts || []).concat(неОтписано(r.id, job.отписать, job.кодП, job.ответилП, job.соглП || [], job.ждёмП, job.dir, job.безКодаП));
    // что отписано — в запись о заявке: видно на экране «Заявка создана» и после возврата в чат
    if (r.posts.length) {
      try {
        await поОдному('lcz-created', async () => {
          const c2 = await store.get('created', {});
          if (c2[job.conv]) { c2[job.conv].posts = записьОтписок(r.posts); await store.set('created', c2); }
        });
      } catch (_e) { /* не сохранили — не страшно */ }
    }
    if (вДиалогP) await вДиалогP;                                       // обычно давно готово (идёт вместе с именем); итог — с этой строкой
    завершить(job, { итог: 'ok', r });
  }

  /* итог задачи: смотрит на неё — в панели (как раньше); нет — уведомлением, а форма диалога помнит, почему не создана */
  function завершить(job, res) {
    const ход = job.ход;
    if (ход.конец) return;
    const наФорме = наФормеЗадачи(job), наХоде = наХодеЗадачи(job);
    ход.конец = res.итог;
    clearTimeout(ход.пульсT);
    if (ЗАДАЧИ.get(job.conv) === job) ЗАДАЧИ.delete(job.conv);
    обновитьУход();
    // «Готовые», кэш проверки, автоприём — по итогу: создана, неизвестно, создаёт другая вкладка — «заявка уже есть»; не создана — проверить
    // заново. № в имени клиента — и его другие диалоги во «Входящих» проверить заново (имя в их строках прежнее)
    try {
      заявкаПоДиалогуСменилась(job.conv, res.итог === 'ok' ? 'заявка по этому диалогу создана' + (res.r && res.r.id ? ' — № ' + res.r.id : '')
        : res.итог === 'неясно' ? 'не знаю, создалась ли заявка по этому диалогу — проверьте CRM по номеру'
          : res.итог === 'чужая' ? 'заявка по этому диалогу сейчас создаётся в другой вкладке' : '');
      if (res.итог === 'ok' && job.client.id) for (const [id, r] of МГН.строки) if (id !== job.conv && r && r.client && String(r.client.id) === job.client.id) { сброситьПроверку(id); дочитать(id); }
    } catch (_e) { /* «Готовые» — не главное: итог задачи важнее */ }
    // поиск заявок CRM по этому номеру, сделанный ДО создания (кэш шагов 3 мин), — больше не ответ: следующая проверка ищет заново
    забытьПоискCRM(job.lead.phone);
    // замок задачи отпускаем, когда запись уже убрана: иначе другая вкладка могла бы застать запись без замка и сказать «прервалось».
    // CRM не ответила (могла создать) — запись не убираем, а помечаем «не знаю» (15 мин): ни эта, ни другие вкладки не скажут
    // «можно создавать», пока оператор не проверит CRM; новое «Создать» оператора её заменит
    записатьЗадачу(job, res.итог === 'неясно' ? { state: 'unknown', unknownAt: Date.now(), stage: ход.этап, name: '', city: '' } : null).finally(() => { if (ход.отпустить) ход.отпустить(); });
    if (ход.el) { ход.el.remove(); ход.el = null; }
    if (convIdNow() === job.conv) btnState(res.итог === 'ok' ? { creating: false, done: true, ready: false, id: res.r.id || null } : { creating: false });
    if (res.итог === 'ok') {
      if (ход.создана) { готовоДописано(job, res.r); return; }          // «создана» уже на экране — дописываем итог отписок на месте
      if (наФорме || наХоде) showDone(job, res.r); else тостГотово(job, res.r);
      return;
    }
    const st = состояниеДиалога(job.conv);
    if (st && res.итог === 'адрес') { st.addrAsked = true; st.адресСпросили = true; }   // второе «Создать» — создать с адресом, как в форме (так и написано на кнопке)
    if (st && res.итог === 'бот') st.botCheck = res.chk;
    const причина = () => (res.итог === 'fail' ? ошибкаСоздания(res.r) : res.итог === 'неясно' ? неЗнаюВПанели(job, res.текст) : res.текст);
    if (наФорме) {                                                     // на форме — как раньше: сообщение сверху, кнопка снова «Создать»
      if (res.итог === 'бот') {
        const bb = panel.querySelector('[data-bot]');
        if (bb) bb.replaceWith(ботBox()); else alertBox(res.chk.text);
        const pb = panel.querySelector('.pb'); if (pb) pb.scrollTop = 0;
      } else alertBox(причина());
      кнопкаФормы();
      return;
    }
    // форма этого диалога в панели, панель закрыта (Esc) — правки после «Создать» в память диалога: вернётся — они на месте
    if (st && st === S && формаЭтого()) keepEdits();
    if (st && res.итог !== 'бот') st.createErr = причина;             // лид-бот — в плашке формы (ботBox), остальное — сверху формы
    if (наХоде) {
      // смотрел на ход создания — вместо него форма диалога с причиной сверху; формы нет (памяти нет, ушёл) — причина уведомлением
      восстановить(job.conv).then((ok) => {
        if (ok && st && S === st && формаЭтого()) return;
        тостНеСоздана(job, res);
        if (!ok && convIdNow() === job.conv) return collect();
      }).catch(() => тостНеСоздана(job, res));
      return;
    }
    тостНеСоздана(job, res);
  }
  const ошибкаСоздания = (r) => h('span', {}, (r.skipped ? '' : 'Не создана: ') + (r.error || (r.errors || []).join('; ') || 'CRM не приняла форму'),
    r.moderation && r.moderation.url ? h('span', {}, ' ', h('a', { href: r.moderation.url, target: '_blank', rel: 'noopener' }, 'Открыть № ' + r.moderation.id)) : '');
  // ответа CRM нет вовсе — заявка могла создаться: сами не повторяем, «Проверить в CRM» ищет по номеру. Сырой текст сбоя — под «Подробнее»
  function неЗнаю(phone, dir, текст, cls, conv) {
    const box = h('div', { class: 'nx-found', style: 'display:flex;flex-direction:column;gap:4px' });
    const btn = h('button', { class: 'sm' + (cls === 'tst-d' ? ' pri' : ''), title: 'Найти заявки по номеру клиента во всех базах CRM', onclick: (e) => найтиПоНомеру(phone, dir, box, e.currentTarget, cls, conv) }, 'Проверить в CRM');
    const ч = человечно(текст);
    return { text: 'Не знаю, создалась ли заявка: ' + String(ч.text || 'CRM не ответила').replace(/[.\s]+$/, '') + '. Проверьте CRM по номеру ' + (fmtPhone(phone) || phone || '—'), тех: ч.тех, box, btn };
  }
  function неЗнаюВПанели(job, текст) {
    const x = неЗнаю(job.lead.phone, job.dir, текст, 'n', job.conv);
    return h('div', { style: 'display:flex;flex-direction:column;gap:6px' }, h('div', {}, x.text),
      h('div', { class: 'n mut' }, 'Повторно не создаю — сначала проверьте, есть ли она в CRM.'), h('div', { class: 'row', style: 'gap:6px' }, x.btn), x.box,
      x.тех ? подробнее(x.тех) : '');
  }
  async function найтиПоНомеру(phone, dir, box, btn, cls, conv) {
    btn.disabled = true; btn.textContent = 'Проверяю в CRM…';
    const x = await спросить({ kind: 'lcz-crm', op: 'existing', args: { phone, dir } }, 60000, 'CRM');
    btn.disabled = false; btn.textContent = 'Проверить в CRM';
    if (!x || !x.ok) { const ч = человечно((x && x.error) || 'нет ответа'); box.replaceChildren(h('div', { class: cls + ' warn' }, 'CRM не ответила (' + String(ч.text).slice(0, 120) + ') — откройте CRM и найдите по номеру ' + (fmtPhone(phone) || phone) + ' сами'), ч.тех ? подробнее(ч.тех) : ''); return; }
    const rows = x.found || [];
    // во всех базах проверено и заявки нет — «не знаю, создалась ли» по диалогу снимаем: его снова можно проверять и создавать
    if (conv && !rows.length && !(x.unchecked || []).length) снятьНеясно(conv).catch(() => {});
    box.replaceChildren(...(rows.length ? rows.slice(0, 6).map((r) => h('div', { class: cls }, dirName(r.dir) + ' № ' + r.id + ' — «' + (r.status || '—') + '»' + (r.when ? ', ' + r.when : '') + ' ',
      r.url ? h('a', { href: r.url, target: '_blank', rel: 'noopener' }, 'Открыть') : ''))
      : [h('div', { class: cls }, 'По номеру ' + (fmtPhone(phone) || phone) + ' заявок в CRM не нашлось')]),
    ...(x.unchecked || []).map((u) => h('div', { class: cls + ' warn' }, dirName(u.dir) + ': не проверено — ' + человечно(u.error).text)));
  }
  // из уведомления — в диалог: недописанный ответ — не уходим (уведомление остаётся); форма — та, что была (с причиной сверху)
  async function открытьДиалогЗадачи(conv, el, форма) {
    if (черновикМешает(conv)) return;
    if (convIdNow() !== conv && !(await перейти(conv))) return;      // LeadChat не открыл диалог — уведомление остаётся
    if (el) el.remove();
    // форма этого диалога уже на экране (вернулся сам кнопкой «Заявка») — открывать нечего: перерисовка стёрла бы его правки
    if (panel.classList.contains('open') && S && S.id === conv && формаЭтого()) return;
    if (форма && !задачаИдёт(conv) && await восстановить(conv)) return;
    await collect();
  }
  // копирование №: «Скопировано» / «Не вышло», через 2 с — снова «Копировать №» (одинаково в уведомлении и на экране итога)
  function кнопкаКопировать(id, cls) {
    const b = h('button', { class: cls, onclick: async () => {
      try { await navigator.clipboard.writeText(String(id)); b.textContent = 'Скопировано'; } catch (_e) { b.textContent = 'Не вышло'; }
      clearTimeout(b._t); b._t = setTimeout(() => { b.textContent = 'Копировать №'; }, 2000);
    } }, 'Копировать №');
    return b;
  }
  // какое это сообщение в Telegram (для коротких строк): «Созданные с Авито» / ответ филиалу / «не по закрепу»
  const видОтписки = (x) => { const t = String((x && x.text) || ''), i = (x && x.item) || '';
    return i === 'avito' || /Созданные с Авито/.test(t) ? 'avito' : i === 'zakrepNot' || /не по закрепу/.test(t) ? 'zakrepNot' : i === 'reply' || /создал/.test(t) ? 'reply' : ''; };
  const ПОДПИСЬ_ОТПИСКИ = { avito: '«Созданные с Авито»', zakrepNot: '«№ не по закрепу»', reply: 'ответ филиалу «№ создал»' };
  const подписьОтписки = (x) => ПОДПИСЬ_ОТПИСКИ[видОтписки(x)] || 'сообщение в Telegram';
  /* итог создания уведомлением. Пока идут сообщения в Telegram (рано) — строки с их состоянием; в конце (было — то же уведомление):
     всё чисто — «Сделано», уходит само через минуту («уйдёт через N с»); есть что доделать руками — жёлтое, висит, не вытесняется */
  /* 2.3: на итоге создания — «Решён» (закрыть диалог в LeadChat), если не ждём ответ филиала на согласование: клиенту всё сказали.
     Только по нажатию; уже закрыт (коллега, бот) — тоже «Решён ✓» */
  const УСПЕХ_МС = 12e3;
  function кнопкаРешён(job, r, cls) {
    if (!r || !r.id || job.ждёмП) return '';
    return h('button', { class: cls, 'data-resolve': '1', title: 'Закрыть диалог в LeadChat как «Решён» — заявка создана, клиенту всё сказали', onclick: async (e) => {
      const b = e.currentTarget;
      if (b.disabled) return;
      b.disabled = true; b.textContent = 'Закрываю…';
      try { await закрытьДиалог(job.conv); b.textContent = 'Решён ✓'; }
      catch (er) { b.disabled = false; b.textContent = 'Решён'; b.title = 'Не закрылся: ' + человечно(er).text.slice(0, 120) + ' — нажмите ещё раз'; }
    } }, 'Решён');
  }
  function тостГотово(job, r, было) {
    const ход = job.ход, идёт = !!(ход.создана && !ход.конец);
    const w = r.warnings || [], плохие = идёт ? [] : (r.posts || []).filter((x) => !x.ok);
    const имяПлохо = !!(r.lcName && !r.lcName.ok);
    // 12.10: тот же № уже у других диалогов LeadChat — проверить, не дубль ли (висит); не записался в диалог — строкой, без «доделать»
    const двойники = !идёт && r.lcCrm && r.lcCrm.ok ? r.lcCrm.twins || [] : [];
    const доделать = !идёт && (!r.id || !!w.length || плохие.length > 0 || имяПлохо || двойники.length > 0);
    const кратко = !идёт && !доделать ? [r.lcName && r.lcName.ok ? 'имя в LeadChat ✓' : '', r.lcCrm && r.lcCrm.ok ? '№ в диалоге LeadChat ✓' : '',
      ...(r.posts || []).filter((x) => x.ok && x.reason !== 'off').map((x) => подписьОтписки(x) + ' ✓')].filter(Boolean).join(' · ') : '';
    let el = было || null;
    const o = { kind: доделать ? 'warn' : 'ok', label: 'Заявка создана',
      title: (r.id ? 'Заявка № ' + r.id + ' создана' : 'Заявка создана') + ' · ' + job.name,
      lines: [h('div', { class: 'tst-d' }, [dirName(job.dir), job.cityText].filter(Boolean).join(' · ')),
        идёт ? планБлок(job, r, true) : кратко ? h('div', { class: 'tst-d' }, кратко) : '',
        !r.id ? h('div', { class: 'tst-d warn' }, 'Номер заявки CRM не сообщила — проверьте карточку клиента в CRM') : '',
        w.length ? h('div', { class: 'tst-d warn' }, 'Предупреждений: ' + w.length + ' — ' + String(w[0]).replace(/^⚠\s*/, '') + (w.length > 1 ? '; остальные — в «Итоге»' : '')) : '',
        имяПлохо ? h('div', { class: 'tst-d warn' }, 'Номер не дописался к имени в LeadChat — впишите «' + r.lcName.name + '» вручную') : '',
        !идёт && r.lcCrm && !r.lcCrm.ok ? h('div', { class: 'tst-d warn', 'data-lc-crm': 'bad' }, 'В LeadChat: номер заявки в диалог не записался') : '',
        двойники.length ? h('div', { class: 'tst-d warn', 'data-lc-twins': двойники.join(',') }, 'Этот номер уже стоит у других диалогов LeadChat: ', ...ссылкиДвойников(двойники)) : '',
        карточкаКлиента(r) ? h('div', { class: 'tst-d' }, карточкаКлиента(r)) : '',
        плохие.length ? h('div', { class: 'tst-d warn' }, 'Не ушло в Telegram: ' + [...new Set(плохие.map(подписьОтписки))].join(', ') + ' — в «Итоге» текст для копирования и «Отправить ещё раз»') : ''],
      actions: [h('button', { class: 'sm pri', onclick: async () => {
          if (convIdNow() !== job.conv) { if (черновикМешает(job.conv)) return; if (!(await перейти(job.conv))) return; }
          el.remove(); hideCard(); showDone(job, r);
        } }, 'Итог'),
        r.url ? h('a', { class: 'sm', href: r.url, target: '_blank', rel: 'noopener', style: 'display:inline-flex;align-items:center;text-decoration:none' }, 'Открыть в CRM') : '',
        кнопкаРешён(job, r, 'sm'),
        r.id ? кнопкаКопировать(r.id, 'sm ghost') : ''], conv: job.conv };
    // 2.3: «Сделано» без дел — уходит само (12 с, мышь на уведомлении — ждёт); есть что доделать — висит
    if (!el) return (el = тост({ ...o, keep: доделать, low: !идёт && !доделать, жить: !идёт && !доделать ? УСПЕХ_МС : 0 }));
    // то же уведомление — итог отписок: чистый — второстепенный и уйдёт сам; есть что доделать — висит (закрыли × — вернётся на виду)
    обновитьТост(el, o);
    el.classList.toggle('tst-keep', доделать); el.classList.toggle('tst-low', !доделать);
    if (!доделать) { if (el._жить) el._жить(); else жить(el, УСПЕХ_МС); }
    else if (!el.isConnected) вСтопку(el, true);
    if (el.isConnected) разложить();
    return el;
  }
  // отписки кончились, а «создана» уже на экране (рано): итог на месте — экран итога перерисовать, уведомление дописать;
  // смотрел итог и закрыл — итог отписок уведомлением (как без «рано»)
  function готовоДописано(job, r) {
    const ход = job.ход;
    try {
      const наИтоге = panel.classList.contains('open') && !!panel.querySelector('[data-done="' + job.key + '"]');
      if (наИтоге) showDone(job, r);
      if (ход.готовоEl && тостЖив(ход.готовоEl)) тостГотово(job, r, ход.готовоEl);
      else if (!наИтоге) ход.готовоEl = тостГотово(job, r);
    } catch (_e) { /* экран — не главное */ }
  }
  function тостНеСоздана(job, res) {
    let el = null;
    if (res.итог === 'неясно') {
      const x = неЗнаю(job.lead.phone, job.dir, res.текст, 'tst-d', job.conv);
      el = тост({ kind: 'warn', label: 'Проверьте CRM', keep: true, title: 'Не знаю, создалась ли заявка · ' + job.name,
        lines: [h('div', { class: 'tst-d' }, x.text), h('div', { class: 'tst-d mut' }, 'Повторно не создаю — заявка могла пройти.'), x.box],
        подробно: x.тех || '',
        actions: [x.btn, h('button', { class: 'sm', onclick: () => открытьДиалогЗадачи(job.conv, null, true) }, 'Открыть диалог')] });
      return el;
    }
    const адрес = res.итог === 'адрес';
    // адрес ещё проверяется картой — коротко и два пути (подождать в диалоге или создать как есть)
    const why = res.итог === 'fail' ? ошибкаСоздания(res.r) : res.итог === 'бот' ? res.chk.text
      : адрес ? 'LeadChat ещё проверяет адрес по карте (1–2 мин). Откройте диалог и подождите — или создайте с адресом, как в форме.' : res.текст;
    el = тост({ kind: адрес || res.итог === 'бот' ? 'warn' : 'bad', label: адрес || res.итог === 'бот' ? 'Нужно действие' : 'Ошибка', keep: true, title: 'Заявка не создана · ' + job.name,
      lines: [h('div', { class: 'tst-d' }, why)],
      actions: [h('button', { class: 'sm pri', onclick: () => открытьДиалогЗадачи(job.conv, el, true) }, 'Открыть диалог'),
        // адрес ещё проверяется картой: как второе «Создать» на форме — создать с адресом, как в форме (нажатие оператора)
        адрес ? h('button', { class: 'sm', title: 'Создать с адресом, как в форме, не дожидаясь проверки LeadChat', onclick: async (e) => {
          const b = e.currentTarget;
          if (b.disabled) return;
          b.disabled = true;
          // по диалогу уже создают или успели создать (вернулся и нажал «Создать» в форме) — второй не запускаем
          const cr = ((await store.get('created', {}).catch(() => ({}))) || {})[job.conv];
          if (задачаИдёт(job.conv)) { b.textContent = 'Уже создаётся…'; return; }
          if (cr && cr.at > job.at) { b.textContent = 'Уже создана' + (cr.id ? ' № ' + cr.id : ''); return; }
          // форма этого диалога на экране — оператор мог её поправить: создаём из формы (как «Создать» в ней), а не по старому снимку;
          // форма не пустила (не хватает полей, отказ в вопросе) — уведомление остаётся, причина — в форме
          if (panel.classList.contains('open') && convIdNow() === job.conv && S && S.id === job.conv && формаЭтого()) {
            S.addrAsked = true; createNow();
            if (задачаИдёт(job.conv)) el.remove(); else b.disabled = false;
            return;
          }
          // форма не на экране, а её поправили после первого «Создать» (вернулся, поправил, ушёл) — старый снимок не шлём:
          // открываем диалог с его формой и создаём из неё (как «Создать» в форме); форма не открылась — уведомление остаётся
          const st = состояниеДиалога(job.conv);
          if (st && st === S && формаЭтого()) keepEdits();
          if (st && st.отпечаток && job.форма && st.отпечаток !== job.форма) {
            await открытьДиалогЗадачи(job.conv, null, true);
            if (panel.classList.contains('open') && convIdNow() === job.conv && S && S.id === job.conv && формаЭтого()) {
              S.addrAsked = true; createNow();
              if (задачаИдёт(job.conv)) { el.remove(); return; }
            }
            b.disabled = false;
            return;
          }
          el.remove();
          запустить({ ...job, key: новыйId(), addrAsked: true, at: Date.now(), снят: job.снят || job.at });   // снимок — от первого «Создать»
        } }, 'Создать как есть') : ''] });
    return el;
  }

  /* ПЕРЕЗАГРУЗКА ПОСРЕДИ СОЗДАНИЯ: запись задачи осталась «идёт», а «пульс» давно не обновлялся (> 60 с) — вкладку перезагрузили или закрыли.
     Говорим один раз (ведущая видимая вкладка), на каком шаге прервалось; сами ничего не создаём и не отписываем.
     Смотрим при запуске и дальше раз в минуту: создававшую вкладку могли закрыть, а ведущая — другая, давно открытая */
  async function показатьПрерванные() {
    let ждать = 0;
    const показать = [];
    await поОдному('lcz-jobs', async () => {
      const all = (await store.get('jobs', {})) || {}, now = Date.now(), held = await замкиЗадач();
      let изм = false;
      for (const [conv, x] of Object.entries(all)) {
        if (!x || now - (x.at || 0) > ЗАДАЧИ_МС) { delete all[conv]; изм = true; continue; }
        // «не знаю, создалась ли» — только 15 мин: дальше поиск CRM видит заявку сам; номер дольше не храним
        if (x.state === 'unknown' && now - (x.unknownAt || x.beat || 0) > НЕЯСНО_МС) { delete all[conv]; изм = true; continue; }
        if (x.state !== 'run' || x.tab === ВКЛАДКА || x.shown) continue;
        if (держит(held, x)) { ждать = Math.max(ждать, 60e3); continue; }   // другая вкладка ещё создаёт
        const возраст = now - (x.beat || x.at || 0);
        // вкладка жива или перезагрузилась только что — посмотрим, когда «пульс» устареет
        if (возраст <= 60e3) { ждать = Math.max(ждать, 60e3 - возраст + 3000); continue; }
        all[conv] = { ...x, shown: true }; изм = true; показать.push({ ...x, conv });
      }
      if (изм) await store.set('jobs', all);
    });
    показать.forEach(тостПрервано);
    return ждать;
  }
  async function прерванныеЗадачи() {
    if (!alive()) return;                                              // расширение обновили — эта вкладка уже ничего не скажет
    let ждать = 60e3;
    try { if (document.visibilityState === 'visible' && (await ведущая())) ждать = (await показатьПрерванные()) || 60e3; } catch (_e) { /* хранилище недоступно — в следующий раз */ }
    setTimeout(() => { прерванныеЗадачи().catch(() => {}); }, Math.max(3000, Math.min(ждать, 60e3)));
  }
  function тостПрервано(x) {
    const имя = x.name || 'клиент';
    let el = null;
    const открыть = h('button', { class: 'sm', onclick: () => открытьДиалогЗадачи(x.conv, el, false) }, 'Открыть диалог');
    if (x.crmDone && x.id) {
      el = тост({ kind: 'warn', label: 'Создание прервалось', keep: true, title: 'Заявка № ' + x.id + ' создана, но не всё доделано · ' + имя,
        lines: [h('div', { class: 'tst-d warn' }, 'Заявка № ' + x.id + ' в CRM есть, но страница перезагрузилась посреди создания. Проверьте и сделайте вручную: № в имени клиента LeadChat и сообщения в Telegram')],
        actions: [x.url ? h('a', { class: 'sm pri', href: x.url, target: '_blank', rel: 'noopener', style: 'display:inline-flex;align-items:center;text-decoration:none' }, 'Открыть в CRM') : '', открыть] });
      return el;
    }
    // форма в CRM ещё не уходила (шаг «create» пишется в запись ДО отправки): проверка адреса, лид-бот — заявки нет, искать нечего.
    // «В очереди» — тоже до отправки, но запись шага «create» могла не записаться: там — осторожное «неизвестно»
    if (!x.crmDone && !/^(queue|create|name|tg)$/.test(x.stage || '')) {
      el = тост({ kind: 'warn', label: 'Создание прервалось', keep: true, title: 'Создание заявки прервалось до CRM (перезагрузка страницы) · ' + имя,
        lines: [h('div', { class: 'tst-d' }, 'Остановилось на шаге: «' + String(ЭТАПЫ[x.stage] || x.stage || '—').replace(/…$/, '') + '»' + (x.dir ? ' · ' + dirName(x.dir) : '') + (x.city ? ' · ' + x.city : '')),
          h('div', { class: 'tst-d' }, 'В CRM форма не уходила — заявка не создана. Откройте диалог и нажмите «Создать» ещё раз')],
        actions: [открыть] });
      return el;
    }
    const n = неЗнаю(x.phone || '', x.dir || '', '', 'tst-d', x.conv);
    el = тост({ kind: 'warn', label: 'Создание прервалось', keep: true, title: 'Создание заявки прервалось (перезагрузка страницы) · ' + имя,
      lines: [h('div', { class: 'tst-d' }, 'Остановилось на шаге: «' + String(ЭТАПЫ[x.stage] || x.stage || '—').replace(/…$/, '') + '»' + (x.dir ? ' · ' + dirName(x.dir) : '') + (x.city ? ' · ' + x.city : '')),
        // CRM создала, но № не сообщила — это не «неизвестно»: найти по номеру и дописать вручную
        h('div', { class: 'tst-d warn' }, (x.crmDone ? 'Заявка создана, но CRM не сообщила № — найдите её по номеру ' + (fmtPhone(x.phone) || x.phone || '—') + '; № в имени LeadChat и сообщения в Telegram сделайте вручную'
          : 'Создалась ли заявка — неизвестно: проверьте CRM по номеру ' + (fmtPhone(x.phone) || x.phone || '—'))), n.box],
      actions: [x.phone ? n.btn : '', открыть] });
    return el;
  }
  setTimeout(() => { прерванныеЗадачи().catch(() => {}); }, 1500);

  // перепроверка номера в CRM для диалога лид-бота: ответ CRM не пришёл или база не проверилась — тоже не создаём молча
  async function проверкаЛидБота(lead, dir) {
    const x = await сТаймаутом(send({ kind: 'lcz-crm', op: 'existing', args: { phone: lead.phone, name: lead.name, dir } }), 60000, 'CRM не ответила за минуту')
      .catch((e) => ({ ok: false, error: String((e && e.message) || e) }));
    if (!x || !x.ok) return { ok: false, text: 'Не получилось перепроверить номер в CRM (' + String((x && x.error) || 'нет ответа').slice(0, 80) + '). Заявку мог уже завести лид-бот — проверьте CRM.' };
    const есть = (x.found || []).filter((r) => r.open);
    if (есть.length) return { ok: false, text: 'В CRM уже есть заявка: ' + есть.slice(0, 3).map((r) => dirName(r.dir) + ' № ' + r.id + ' «' + (r.status || '—') + '»').join(', ') + ' — скорее всего, её завёл лид-бот. Вторую не создаю.' };
    const несверено = (x.unchecked || []).filter((u) => !dir || u.dir === dir);
    if (несверено.length) return { ok: false, text: 'База ' + несверено.map((u) => dirName(u.dir)).join(', ') + ' не проверилась (' + String(несверено[0].error || '').slice(0, 60) + '). Заявку мог уже завести лид-бот — проверьте CRM.' };
    return { ok: true };
  }
  function ботBox() {
    const бот = S && лидБот(S.ctx && S.ctx.messages, S.conv);
    if (!бот) return '';
    const c = S.botCheck;
    return h('div', { class: 'box ' + (c && !c.ok ? 'bad' : 'warn'), 'data-bot': '1' }, svg('warn'), h('div', { class: 'c' },
      h('div', {}, h('b', {}, 'Лид-бот: '), бот.why + '.'),
      c && !c.ok ? h('div', {}, c.text) : h('div', { class: 'n mut' }, c && c.ok ? 'Номер в CRM перепроверен — заявки нет.' : 'Перед созданием ещё раз проверю номер во всех базах CRM.'),
      // 2.3: «Проверил в CRM — создать заявку» — надписью главной кнопки (галочка allowBot — в форме, скрыто)
      c && !c.ok ? h('div', { class: 'n mut' }, 'Проверили в CRM и заявки нет — кнопка внизу «Проверил в CRM — создать заявку».') : ''));
  }

  // CRM обновила карточку существующего клиента (адрес, кв, доп. номера) — строкой для итога; не обновила — это в предупреждениях
  const карточкаКлиента = (r) => (r && r.customer && r.customer.ok && (r.customer.changed || []).length && r.customerNote ? String(r.customerNote).replace(/^в /, 'В ') : '');
  /* итог создания — по задаче (имя, база, отписки), а не по открытому сейчас диалогу. 2.1: сверху — «Заявка создана в … / № …»;
     дальше — «Сделайте вручную» (что не получилось: № не сообщён, имя, не ушедшие сообщения с «Скопировать» / «Отправить ещё раз»,
     предупреждения CRM), ниже — «Что сделано» строками со статусом. Сообщения в Telegram ещё идут — строки обновляются на месте */
  const строкаИтога = (t, st, cls, attrs) => h('div', { class: 'nx-ln ' + (cls || ''), ...(attrs || {}) }, h('span', { class: 'tx' }, t), h('span', { class: 'nx-s' }, st));
  function showDone(job, r) {
    const v = r.verified || { checked: 0, diffs: [], fields: [] };
    const ход = job.ход, идёт = !!(ход.создана && !ход.конец);
    const дальше = готовыеДальше(job.conv).length;
    const posts = идёт ? [] : (r.posts || []);
    const вручную = [
      !r.id ? h('div', { class: 'box warn' }, svg('warn'), h('div', { class: 'c' }, 'Номер заявки CRM не сообщила — проверьте карточку клиента в CRM')) : '',
      r.lcName && !r.lcName.ok ? h('div', { class: 'box warn' }, svg('warn'), h('div', { class: 'c' }, 'Номер не дописался к имени в LeadChat — впишите «' + r.lcName.name + '» вручную',
        r.lcName.error ? подробнее(String(r.lcName.error)) : '')) : '',
      ...posts.filter((x) => !x.ok).map((x) => строкаОтписки(job, r, x)),
      ...(r.warnings || []).map((w) => h('div', { class: 'box ' + (/^АДРЕС НЕ ТОТ:/.test(w) ? 'bad' : 'warn'), ...(/^АДРЕС НЕ ТОТ:/.test(w) ? { 'data-addr-bad': '1' } : {}) }, svg('warn'), h('div', { class: 'c' }, w.replace(/^⚠\s*/, ''))))].filter(Boolean);
    const сделано = идёт ? планБлок(job, r, false) : h('div', { class: 'nx-lines' },
      строкаИтога('CRM: заявка, комментарии, клиент', 'готово', 'ok'),
      r.lcName && r.lcName.ok ? строкаИтога('Имя в LeadChat: «' + r.lcName.name + '»', 'готово', 'ok') : '',
      ...строкиНомераLC(r, строкаИтога),
      // что изменилось в карточке существующего клиента CRM (адрес общий для всех его заявок); сбой — уже в предупреждениях
      карточкаКлиента(r) ? h('div', { class: 'nx-ln ok' }, h('span', { class: 'tx' }, карточкаКлиента(r) + ' ',
        r.customer && r.customer.url ? h('a', { href: r.customer.url, target: '_blank', rel: 'noopener' }, 'Карточка клиента') : ''), h('span', { class: 'nx-s' }, 'готово')) : '',
      ...posts.filter((x) => x.ok).map((x) => (x.reason === 'off' ? строкаИтога(x.text, 'не отправлялось', 'mut', { 'data-post-line': 'off' })
        : строкаИтога(x.text, 'готово', 'ok', { 'data-post-ok': видОтписки(x) || 'post' }))));
    const расходится = new Set((v.diffs || []).map((d) => String(d).split(/[:(]/)[0].replace(/\s+в карточке клиента$/, '').trim()).filter(Boolean));
    panel.classList.add('open');
    panel.dataset.conv = job.conv;
    panel.replaceChildren(h('div', { class: 'ph' }, header(job.name)),
      h('div', { class: 'pb', 'data-done': job.key },                   // итог этой задачи: кнопка «№ заявки» его закрывает (onBtnClick)
        h('div', { class: 'win', role: 'status' },
          h('div', { class: 'hd' }, h('span', { class: 'big' }, svg('check', true)),
            h('div', { style: 'flex:1;min-width:0' }, h('div', { class: 'n ok' }, 'Заявка создана в ' + dirName(job.dir)),
              h('div', { class: 'num' }, r.id ? '№ ' + r.id : 'Заявка создана')),
            h('span', { class: 'nx-crm' }, 'CRM ✓')),
          h('div', { class: 'row' }, r.url ? h('a', { class: 'opencrm', href: r.url, target: '_blank' }, 'Открыть в CRM', svg('ext')) : '', кнопкаРешён(job, r, 'ghost'), r.id ? кнопкаКопировать(r.id, 'ghost') : '')),
        вручную.length ? h('section', { class: 'nx-todo' }, h('h3', { class: 'cap' }, 'Сделайте вручную'), ...вручную) : '',
        h('section', { class: 'nx-card' }, h('div', { class: 'nx-h' }, h('b', {}, 'Что сделано'), идёт ? h('span', { class: 'nx-sum' }, 'сообщения ещё отправляются') : ''),
          сделано,
          идёт ? h('div', { class: 'n mut' }, 'Можно уйти в другой диалог — допишу сам и скажу, если что-то не ушло.') : ''),
        v.checked ? h('section', { class: 'sec' }, h('h3', { class: 'cap' }, расходится.size ? 'Проверено в карточке CRM — есть расхождения' : 'Проверено в карточке CRM'),
          h('div', { class: 'chips' }, ...(v.fields && v.fields.length ? v.fields : ['полей: ' + v.checked]).map((t) => h('span', { class: 'chip ' + (расходится.has(t) ? 'warn' : 'ok') }, t)),
            ...[...расходится].filter((t) => !(v.fields || []).includes(t)).map((t) => h('span', { class: 'chip warn' }, t + ' — расходится')))) : ''),
      // дальше — следующий готовый диалог (принять и открыть форму) или закрыть
      h('div', { class: 'pf' }, h('div', { class: 'row' },
        h('button', { class: 'go', 'data-next': '1', title: дальше ? 'Принять следующий готовый диалог и открыть форму заявки' : 'Готовые к созданию во «Входящих»', onclick: (e) => {
          const след = готовыеДальше(job.conv);
          return след.length ? открытьГотовую(след[0], e.currentTarget) : showReady();
        } }, дальше ? 'Следующий готовый (' + дальше + ')' : 'К списку «Готовые»'),
        h('button', { class: 'go2', title: 'Закрыть (Esc)', onclick: closePanel }, 'Закрыть'))));
  }
  // как в списке «Готовые»: готово и «почти» только из-за регламента (сверка в форме)
  const готовыеДальше = (conv) => READY.items.filter((x) => (x.st === 'ready' || толькоРегламент(x)) && x.id !== conv);
  // отписки — в запись о заявке (экран «заявка уже создана» и после возврата в чат); намеренный пропуск — off
  const записьОтписок = (posts) => posts.map((x) => ({ ok: !!x.ok, text: String(x.text || '').slice(0, 200), at: Date.now(), ...(x.reason === 'off' ? { off: true } : {}) }));
  // не ушедшее сообщение в итоге: «Скопировать» текст для ручной отправки и «Отправить ещё раз» только его; ушло — итог перерисовывается
  function строкаОтписки(job, r, x) {
    const кнопки = [];
    if (!x.ok && x.manual) кнопки.push(h('button', { class: 'sm', onclick: async (e) => {
      const b = e.currentTarget;
      try { await navigator.clipboard.writeText(x.manual); b.textContent = 'Скопировано'; }
      catch (_e) { const i = h('input', { value: x.manual, readonly: 'readonly', 'aria-label': 'Текст для ручной отправки', style: 'height:28px;font-size:12px;width:auto;flex:1' }); b.replaceWith(i); i.focus(); i.select(); }
    } }, 'Скопировать'));
    // «не знаю, ушло ли» — повтор мог бы отправить дважды: только «Скопировать», проверить чат глазами
    if (!x.ok && x.item && r.id && !x.unknown) кнопки.push(h('button', { class: 'sm', onclick: async (e) => {
      const b = e.currentTarget;
      if (b.disabled) return;
      b.disabled = true; b.textContent = 'Отправляю…';
      const res = await отписатьСозданную(r.id, { [x.item]: true }, job.кодП, job.соглП || [], job.conv, job.dir, job.cityText)
        .catch((err) => [{ ok: false, item: x.item, manual: x.manual, text: 'В Telegram не отправилось: ' + String((err && err.message) || err).slice(0, 120) }]);
      const i = (r.posts || []).indexOf(x);
      if (i >= 0) r.posts.splice(i, 1, ...res);
      // на экране этот итог — перерисовать (ушедшее — в «Что сделано»); иначе — строку на месте
      if (panel.querySelector('[data-done="' + job.key + '"]') && el.isConnected) showDone(job, r);
      else if (el.isConnected) el.replaceWith(...res.map((y) => строкаОтписки(job, r, y)));
      поОдному('lcz-created', async () => { const c2 = await store.get('created', {}); if (c2[job.conv]) { c2[job.conv].posts = записьОтписок(r.posts || []); await store.set('created', c2); } }).catch(() => {});
    } }, 'Отправить ещё раз'));
    const el = h('div', { class: 'box ' + (x.ok ? 'ok' : 'warn'), 'data-post-line': x.item || '' }, svg(x.ok ? 'check' : 'warn'),
      h('div', { class: 'c' }, x.text, кнопки.length ? h('div', { class: 'row pa' }, ...кнопки) : ''));
    return el;
  }

  // сообщение сверху формы: новое заменяет прежнее (не копятся); поле — прокрутить к нему и поставить курсор, иначе — наверх
  function alertBox(text, kind, поле) {
    const pb = panel.querySelector('.pb');
    [...(pb || panel).children].filter((x) => x.hasAttribute('data-alert')).forEach((x) => x.remove());
    const b = h('div', { class: 'box ' + (kind || 'bad'), role: 'alert', 'data-alert': '1' }, svg(kind === 'ok' ? 'check' : 'warn'), h('div', { class: 'c' }, text));
    if (pb) { pb.prepend(b); if (поле) кПолю(поле); else pb.scrollTop = 0; } else panel.append(b);
  }
  /* ---------- клавиши: Esc — закрыть, Ctrl+Enter — создать (только когда фокус в панели) ---------- */
  document.addEventListener('keydown', (e) => {
    if (!panel.classList.contains('open')) return;
    if (ручноеПодтверждение?.el.isConnected) {ручноеПодтверждение.key(e);return;}
    const inPanel = e.composedPath().includes(panel);
    // панель только что открыта нашей кнопкой («Заявка», «Готовые») — фокус на ней: клавиши тоже наши
    const кнопка = !inPanel && нашФокус(document.activeElement) && !e.composedPath().includes(toasts) && !e.composedPath().includes(card);
    // Esc из нашей панели — только наш: дальше не идёт (иначе LeadChat закрывал заодно свою карточку клиента)
    if (e.key === 'Escape' && (inPanel || кнопка || !document.activeElement || document.activeElement === document.body)) {
      const menu = panel.querySelector('details.cz-more[open]');
      if (menu) { e.preventDefault(); e.stopPropagation(); menu.open = false; menu.querySelector('summary').focus({ preventScroll: true }); return; }
      if (inPanel || кнопка) e.stopPropagation(); closePanel();
    }
    else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && (inPanel || кнопка)) { e.preventDefault(); e.stopPropagation(); if (!e.repeat) createNow(); }
  }, true);
  /* Клавиши, нажатые в наших полях, — не для LeadChat. Наша панель в shadow DOM: LeadChat видит вместо поля ввода наш корневой div
     и не понимает, что человек печатает: «?» открывал его справку (символ не печатался), Tab у тех, у кого «Принять» на Tab,
     забирал из очереди следующий диалог, Esc закрывал заодно карточку LeadChat.
     1) из наших полей клавиша дальше корня не всплывает (после нашей обработки Esc и Ctrl+Enter выше);
     2) пока фокус у нас, host помечен role="dialog": LeadChat поверх «окна» свои сочетания не трогает — в том числе
        перехват Tab на window, который срабатывает раньше любого нашего обработчика. */
  root.addEventListener('keydown', (e) => { const t = e.composedPath()[0]; if (t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || '')) e.stopPropagation(); });
  const слойLeadChat = (on) => { if (on) { if (host.getAttribute('role') !== 'dialog') host.setAttribute('role', 'dialog'); } else if (host.hasAttribute('role')) host.removeAttribute('role'); };
  // «окно» — фокус в панели или карточке, либо в нашем поле ввода (в уведомлении); на кнопках «Заявка» / «Готовые» и кнопках уведомлений — нет
  root.addEventListener('focusin', (e) => { const t = e.composedPath()[0]; слойLeadChat(!!(t && t.closest && (t.closest('.panel, .card') || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || '')))); });
  root.addEventListener('focusout', (e) => { if (!e.relatedTarget || !root.contains(e.relatedTarget)) слойLeadChat(false); });
  // фокус ушёл в LeadChat (или поле с фокусом исчезло при перерисовке) — пометку снимаем, его клавиши снова работают
  document.addEventListener('focusin', (e) => { if (e.target !== host) слойLeadChat(false); }, true);

  /* ---------- наблюдение: «заявку можно создавать» ----------
     Пока открыт диалог, раз в 20 с смотрим, не пришли ли новые сообщения (лёгкий запрос). Новое — тот же разбор
     готовности, что у «Готовых» (CRM, ИИ, карта, регламент; не чаще раза в 45 с), и карточка по его итогу: «можно создавать»,
     «почти», «согласование», «клиент думает»… Сбой CRM никогда не показывает «можно создавать». Не хватало данных / ждали /
     сбой — через минуту проверяем снова и без нового сообщения (LeadChat пишет адрес в карточку сам, через ~90 с). Создаёт — человек.
     Без нового сообщения «не хватает» / «ждём» перепроверяем не больше 3 раз (1, 2, 4 мин): разбор ИИ не дёргаем каждую минуту,
     пока диалог просто открыт; сбой — каждую минуту, пока не пройдёт. */
  const W = { conv: '', lastId: '', at: 0, dismissed: '', meta: null, retryAt: 0, повторы: 0 };
  // карточка готовности по диалогу (до 30): что показали и по какому сообщению — смена диалога её прячет, вернулся — показываем снова
  const ПОКАЗАНО = new Map();
  const ПОВТОРОВ_БЕЗ_НОВОГО = 3;

  function hideCard() { card.classList.remove('show'); btnState({ ready: false }); }

  const ЗАГОЛОВОК_КАРТЫ = { ready: 'Заявку можно создавать', almost: 'Почти готово', approval: 'Нужно согласование', doubt: 'Клиент ещё не решился',
    declined: 'Клиент отказался', exists: 'Заявка уже есть' };
  /* A — разбор (поля заявки), res — итог проверки готовности (без него — как раньше: «можно создавать»), ключ — до какого
     сообщения «Скрыть» */
  function showCard(A, res, ключ) {
    const st = res ? res.st : 'ready';
    const L = A && A.lead;
    const c = (f) => ((A && A.checks) || []).find((x) => x.field === f) || { ok: false, note: '' };
    const row = (k, ...v) => [h('div', { class: 'k' }, k), h('div', { class: 'v' }, ...v)];
    // 2.1: каждое замечание — один раз: у своего поля (время, адрес, телефон, суть), в общем блоке — только то, чего в полях нет
    const miss = [];
    let kv = '';
    if (L) {
      const a = L.addr || {};
      const addr = [a.settlement, a.street, a.building, a.office && 'кв ' + a.office, a.entrance && 'подъезд ' + a.entrance,
        a.floor && 'этаж ' + a.floor].filter(Boolean).join(', ');
      const dm = L.visit_date ? L.visit_date.slice(8, 10) + '.' + L.visit_date.slice(5, 7) : '';
      const time = L.visit_date && L.visit_time ? dm + ' в ' + L.visit_time : '';
      // клиент просит созвониться: время и не договорено — это не замечание (форма поставит ближайшее по регламенту)
      const прозвон = !!(res && (res.вид === 'прозвон' || res.вид === 'ближайшее'));
      const нетВремени = !c('time').ok && !прозвон;
      // клиент назвал день без часа («в среду») — ближайшее форма не ставит: час — с клиентом
      // 2.2.7: окно клиента («до 15», «завтра до 12») — время ставит форма: ближайшее в окне
      const окноК = окноКлиента(L);
      const деньБезЧаса = !окноК && !!(L.visit_date && !L.visit_time && L.visit_date !== (клиентСейчас(L) || {}).iso);
      const бот = лидБот(A.ctx && A.ctx.messages, A.conv);
      if (бот) miss.push(бот.why + ' — перед созданием проверю номер в CRM');
      if (L.voice && L.voice.note) miss.push(L.voice.note);
      const адресЗаметка = c('address').note.replace(/^из карточки LeadChat · /, '');
      kv = h('div', { class: 'kv' },
        ...row('Телефон', fmtPhone(L.phone), c('phone').note ? h('span', { class: 'ok' }, ' · ' + c('phone').note) : '', L.phone_warn ? h('span', { class: 'warn' }, ' · ' + L.phone_warn) : ''),
        ...row('Адрес', addr + (L.city ? ' · ' + L.city : ''), адресЗаметка ? h('span', { class: !c('address').ok || L.addr_warn ? 'warn' : 'ok' }, ' · ' + адресЗаметка) : '',
          L.addr_warn ? h('span', { class: 'warn' }, ' · ' + L.addr_warn) : ''),
        ...row('Визит', time || (прозвон ? h('span', {}, (деньБезЧаса ? dm + ', час — с клиентом' : 'ближайшее по регламенту') + (res.вид === 'ближайшее'
          ? (окноК ? ' в окне клиента (' + LC_EXTRACT.окноСловами(окноК) + ')' + (res.time && /^(ближайшее, визит ~|не успеваем)/.test(res.time) ? ' — ' + res.time.replace(/^ближайшее, /, '') : '') : ' — время с клиентом не договорено')
          : ' — клиент просит созвониться («Прозвон» — сами, если нужно)'))
          : h('span', { class: 'warn' }, (!res && !деньБезЧаса ? 'не договорено — поставлю ближайшее по регламенту' : 'не договорено') + (нетВремени && c('time').note ? ' — ' + c('time').note : ''))),
          time && L.time_text ? h('span', { style: 'color:var(--t3)' }, ' (' + L.time_text + ')') : ''),
        ...row('Проблема', L.problem || h('span', { class: 'warn' }, 'не найдена — уточните у клиента')),
        ...(res && res.заявка && res.заявка.согласие && res.заявка.сила === 'сильно' && (st === 'ready' || st === 'almost') ? row('Согласие', 'клиент: «' + res.заявка.согласие + '»') : []),
        ...(L.voiced && L.voiced.length ? row('Озвучено', L.voiced.join('; ')) : []),
        ...(L.name ? row('Имя', L.name) : []),
        ...(L.partner_note ? row('Источник', L.partner_note, h('span', { class: L.src_url ? 'ok' : 'warn' }, L.src_url ? ' · ссылка для отзыва есть' : ' · ссылки для отзыва нет')) : []));
    }
    if (res) {
      for (const f of res.флаги || []) if (!miss.includes(f) && !(L && f === 'телефон: ' + L.phone_warn)) miss.push(f);   // «телефон: …» — уже у поля
      if ((res.добрать || []).length) miss.push('уточнить: ' + res.добрать.join('; '));
    }
    const dismiss = () => { W.dismissed = ключ !== undefined ? ключ : (A && A.lastId) || ''; hideCard(); };
    const скрыть = h('button', { class: 'sq', title: 'Скрыть до нового сообщения клиента', onclick: dismiss }, 'Скрыть');
    const кнопки = st === 'ready' || st === 'almost' ? [h('button', { class: 'go', onclick: () => collect(A) }, 'Проверить и создать'), скрыть]
      : st === 'approval' ? [h('button', { class: 'go', onclick: () => collect(A || null) }, 'Открыть форму'), скрыть]
        : st === 'doubt' ? [h('button', { class: 'sq', onclick: () => collect(A || null) }, 'Открыть форму'), скрыть] : [скрыть];
    const заголовок = st === 'ready' && res && res.вид === 'прозвон' ? 'Заявку можно создавать — клиент просит созвониться'
      : st === 'ready' && res && res.вид === 'ближайшее' ? 'Заявку можно создавать — на ближайшее время' : ЗАГОЛОВОК_КАРТЫ[st] || ЗАГОЛОВОК_КАРТЫ.ready;
    // одна строка «что дальше» под заголовком
    const дальше = st === 'ready' ? ['ok', res && (res.вид === 'прозвон' || res.вид === 'ближайшее') ? 'Всё есть, время — ближайшее по регламенту («Прозвон» — сами, если нужно): проверьте поля и создайте' : 'Всё есть — проверьте поля и создайте']
      : st === 'almost' ? ['warn', показПричины(res && res.why ? безРежима(res) : 'не всё есть')]
        : st === 'approval' ? ['warn', 'Сначала согласование с филиалом — откройте форму']
          : st === 'doubt' ? ['warn', 'Клиент ещё не решил — уточните или подождите'] : null;
    card.replaceChildren(
      h('div', { class: 'hd', 'data-ready-key': String(ключ !== undefined ? ключ : (A && A.lastId) || '') }, h('span', { class: 'ok-ic' + (st === 'ready' ? '' : ' warn') }, svg(st === 'ready' ? 'check' : 'warn')),
        h('div', { class: 'tt' }, заголовок),
        h('button', { class: 'ib', 'aria-label': 'Скрыть до нового сообщения', title: 'Скрыть до нового сообщения', onclick: dismiss }, svg('close'))),
      дальше ? h('div', { class: 'cd-next ' + дальше[0] }, дальше[1]) : '',
      res && st !== 'ready' && st !== 'almost' && res.why ? h('div', { class: 'box ' + (st === 'declined' || st === 'exists' ? 'bad' : 'warn') }, svg('warn'), h('div', { class: 'c' }, показПричины(res.why))) : '',
      kv,
      miss.length ? h('div', { class: 'box warn' }, svg('warn'), h('div', { class: 'c' }, ...miss.map((t) => h('div', {}, t)))) : '',
      h('div', { class: 'row' }, ...кнопки));
    card.classList.toggle('top', !!inlineBtn);           // кнопка в карточке «Клиент» — подсказка сверху, рядом с ней
    card.classList.add('show');
    btnState({ ready: st === 'ready' });
  }
  /* итог проверки → карточка: у клиента живая заявка — карточка заявки (перенос / отмена / «где мастер»); ready … exists — карточка
     с заголовком по итогу; не хватает / ждём / оператор отказал — карточку прячем; сбой — карточку не трогаем, причина — на кнопке */
  function показатьРезультат(id, res, lastId) {
    for (const b of [fab, inlineBtn]) if (b) b.title = res.st === 'error' ? 'проверка не удалась: ' + res.why : 'Собрать заявку из этого диалога';
    if (res.st === 'error') {
      // сбой — карточку не трогаем (не мигает при повторе); но карточка готовности по ПРЕЖНЕМУ сообщению («можно создавать»),
      // а клиент уже написал новое — её убираем: устаревшее «можно создавать» не показываем
      const hd = card.querySelector('[data-ready-key]');
      if (card.classList.contains('show') && hd && hd.getAttribute('data-ready-key') !== String(lastId || '')) hideCard();
      return;
    }
    const живые = res.crm && (res.crm.found || []).some((r) => r.open);
    if ((res.st === 'exists' || res.st === 'follow') && живые) {
      showExistingCard(id, res.crm, withSource({}, (W.meta && W.meta.conv) || {}, res.dir || '').partner_note || '', res.st === 'follow' && res.F ? { ...res.F, crId: res.crId } : null);
      return;
    }
    if (/^(ready|almost|approval|doubt|declined|exists)$/.test(res.st)) {
      const ключ = (res.A && res.A.lastId) || lastId;
      // в карточке — источник и ссылка для отзыва, как в заявке (форма из карточки их тоже получит)
      const A = res.A ? { ...res.A, lead: res.dir ? withSource(res.A.lead, res.A.conv, res.dir) : res.A.lead } : null;
      if (W.dismissed !== ключ) showCard(A, res, ключ);
      return;
    }
    hideCard();
  }

  /* ---------- у клиента уже есть заявка: не создаём вторую, а предлагаем перенос / отмену / «где мастер» ----------
     F — что клиент написал по этой заявке (проверка «по заявке», st 'follow': {r, seen, text, crId}): его плитка — «предлагаю», слова — строкой */
  // режим 'действия' — открыта кнопкой «Действия»: заголовок про действия, у прошлых заявок — их действия, ввод № вручную, без «создать новую»
  function showExistingCard(id, ex, curSource, F, режим) {
    const дРежим = режим === 'действия';
    const все = ex.found || [];
    const актуальные = все.filter((r) => r.open).slice(0, 3);
    const прошлые = все.filter((r) => !r.open);
    const hm = (v) => String(v || '').replace(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}:\d{2}).*$/, '$3.$2 $4');
    const crOf = (r) => ({ id: r.id, dir: r.dir, city: r.city || '', url: r.url || '', status: r.status || r.cardStatus || '', phone10: r.phone10 || '', prozvon: !!r.prozvon, service: r.serviceComment || '',
      visit: r.visit || '', visitTime: r.visitTime || (String(r.visit || '').match(/(\d{1,2}:\d{2})/) || [])[1] || '', at: Date.now(), seenAt: Date.now(), linked: true });
    async function связать(r) {
      await правитьCreated((all) => { all[id] = { ...(all[id] || {}), ...crOf(r) }; });
    }
    const актуально = !!(ACT && ACT.готов());
    const fR = F && F.r && typeof F.r === 'object' ? F.r : null;
    // разобранное — про эту заявку (№ из проверки; без номера — про первую актуальную)
    const чьё = (r) => !!fR && (F.crId ? String(F.crId) === String(r.id) : r === актуальные[0]);
    const слова = fR ? String(fR.summary || F.text || '').trim() : '';
    /* 1.20: плитка — карточка действия каталога (превью = подтверждение), заполненная словами клиента, если он писал об этом:
       поНамерению (подсказка каталога по статусу), не предложил — карточка действия плитки. Прежняя карточка «по заявке» —
       без каталога, для дописки и отдела Авито, и когда клиент назвал адрес (сверка с карточкой клиента в CRM — только там) */
    const КЛЮЧИ = { перенос: 'move', отмена: 'cancel_kc', где_мастер: 'where' };
    async function действие(r, intent, b) {
      if (b && b.disabled) return;
      const своё = чьё(r) && fR.intent === intent;
      const rr = своё ? { ...fR, text: F.text || fR.text || '' } : { intent, summary: '' };
      const seen = своё && F.seen ? F.seen : Date.now();
      const прежняя = !актуально || !ACT.готов() || !КЛЮЧИ[intent] || (своё && адресВСловах(intent, rr));
      // пока смотрим CRM — плитка неактивна и говорит об этом; ничего не показали — как была
      const lb = b && b.querySelector('.lb'), было = lb ? lb.textContent : '';
      if (b) { b.disabled = true; if (lb) lb.textContent = 'Смотрю в CRM…'; }
      let показана = false;
      try {
        await связать(r);
        if (прежняя) { показана = (await showAdditionCard(id, crOf(r), rr, seen)) !== false; return; }
        const cr = crOf(r);
        показана = await ACT.поНамерению(id, cr, { ...rr, intent, намерение: intent }, seen).catch(() => false);
        if (!показана) {
          const ввод = {}; for (const k of ['date', 'time', 'summary']) if (rr[k]) ввод[k] = rr[k];
          показана = (await ACT.карточка(id, cr, КЛЮЧИ[intent], ввод, { from: 'existing', seen }).catch(() => false)) !== false;
        }
      } finally {
        if (b && b.isConnected && !показана) { b.disabled = false; if (lb) lb.textContent = было; }
      }
    }
    const когда = (r) => r.when || (r.visit ? hm(r.visit) : '');
    const ПРОЧЕЕ = { дополнение: 'Дописал', отдел_авито: 'В отдел Авито', претензия: 'Претензия' };
    // 2.1 (проект «Действия»): статус — меткой своего цвета; «обновлено N с назад»; «Предлагаю …» — строкой с одной кнопкой
    const цвет = (ст) => (/отмен|отказ|не оформ|не созд/i.test(String(ст || '')) ? 'bad' : /работ|пути|выполн|готов/i.test(String(ст || '')) ? 'ok' : 'info');
    const назад = (at) => { const с = Math.max(0, Math.round((Date.now() - at) / 1000)); return 'обновлено ' + (с < 60 ? с + ' с' : Math.round(с / 60) + ' мин') + ' назад'; };
    const ПРЕДЛАГАЮ = { перенос: 'перенос', отмена: 'отмену', где_мастер: 'спросить «Где мастер?»', дополнение: 'дописать в заявку', отдел_авито: 'передать в отдел Авито', претензия: 'претензию' };
    // клиент написал о другом (дописал, отдел Авито, претензия) — прежняя карточка «по заявке» с его словами
    async function прочее(r, b) {
      if (b && b.disabled) return;
      const lb = b && b.querySelector('.lb'), было = lb ? lb.textContent : '';
      if (b) { b.disabled = true; if (lb) lb.textContent = 'Смотрю в CRM…'; }
      let показана = false;
      try { await связать(r); показана = (await showAdditionCard(id, crOf(r), { ...fR, text: F.text || fR.text || '' }, F.seen || Date.now())) !== false; }
      finally { if (b && b.isConnected && !показана) { b.disabled = false; if (lb) lb.textContent = было; } }
    }
    // строка «Предлагаю перенос: клиент написал «…»» и одна кнопка «Открыть» — то, о чём писал клиент по этой заявке
    const подсказкаКлиента = (r) => (!чьё(r) || !ПРЕДЛАГАЮ[fR.intent] ? null : { текст: 'Предлагаю ' + ПРЕДЛАГАЮ[fR.intent], почему: слова ? 'клиент написал «' + слова.slice(0, 160) + '»' : '',
      кнопка: () => h('button', { class: 'ac-sug-b', 'data-ex-act': fR.intent, onclick: (e) => (КЛЮЧИ[fR.intent] ? действие(r, fR.intent, e.currentTarget) : прочее(r, e.currentTarget)) }, h('span', { class: 'lb' }, 'Открыть')) });
    const следить = (r, cls) => h('button', { class: cls || 'ex-follow', title: 'Связать этот диалог с заявкой: новые сообщения клиента — подсказками по ней',
      onclick: async (e) => { const b = e.currentTarget; await связать(r); b.textContent = 'Подсказываю по новым сообщениям ✓'; b.classList.add('on'); b.disabled = true; } }, svg('link'), 'Подсказывать по новым сообщениям клиента');
    const другойИсточник = (r) => { const x = LC_TG.другойИсточник(r.source || '', curSource); return x ? h('div', { class: 'ac-line warn' }, svg('warn'), h('span', {}, 'Заявка создана по ' + x.было + ', а клиент сейчас пишет на ' + x.сейчас)) : ''; };
    // актуальная заявка (их несколько или экрана действий нет): всё, что можно сделать по ней, — кнопками
    const живая = (r) => {
      /* 1.20: действия — «Все действия ▾» раскрывает сетку действий этой заявки (по статусу в CRM); плитка сначала связывает диалог с заявкой */
      const место = h('div', { 'data-act-here': r.dir + ':' + r.id, hidden: true });
      const раскрыть = актуально ? h('button', { class: 'exr-l', title: 'Все действия по заявке: по статусу в CRM', 'aria-expanded': 'false', onclick: (e) => {
        if (!место.firstChild) место.append(ACT.сетка(crOf(r), { where: 'existing', conv: id, перед: () => связать(r) }) || '');
        место.hidden = !место.hidden;
        e.currentTarget.setAttribute('aria-expanded', место.hidden ? 'false' : 'true');
      } }, 'Все действия ▾') : '';
      // 2.0.1: номер крупно, статус меткой, дата и город с иконками, главные действия плитками
      const ст = String(r.status || '—');
      const предлагаю = (intent) => чьё(r) && fR.intent === intent;
      const плитка = (icon, текст, intent, cls) => h('button', { class: 'exr-a' + (cls ? ' ' + cls : '') + (предлагаю(intent) ? ' hint' : ''), 'data-ex-act': intent,
        title: предлагаю(intent) && слова ? 'Клиент: «' + слова + '»' : undefined, onclick: (e) => действие(r, intent, e.currentTarget) },
      svg(icon), h('span', { class: 'lb' }, текст), предлагаю(intent) ? h('span', { class: 'ag-hint' }, 'предлагаю') : '');
      // клиент написал о другом (дописал, отдел Авито, претензия) — своей плиткой «предлагаю»: прежняя карточка «по заявке» с его словами
      const прочееП = чьё(r) && !КЛЮЧИ[fR.intent] && ПРОЧЕЕ[fR.intent] ? h('button', { class: 'exr-a hint', 'data-ex-act': fR.intent, onclick: (e) => прочее(r, e.currentTarget) },
        svg('warn'), h('span', { class: 'lb' }, ПРОЧЕЕ[fR.intent]), h('span', { class: 'ag-hint' }, 'предлагаю')) : '';
      return h('div', { class: 'exr' },
        h('div', { class: 'exr-h' }, h('span', { class: 'exr-b' }, dirName(r.dir)), h('span', { class: 'exr-n' }, '№ ' + r.id), h('span', { class: 'exr-st ac-pill ' + цвет(ст) }, ст)),
        когда(r) || r.city ? h('div', { class: 'exr-m' }, когда(r) ? h('span', {}, svg('cal'), когда(r)) : '', r.city ? h('span', {}, svg('pin'), r.city) : '') : '',
        r.source ? h('div', { class: 'n mut' }, 'Источник: ' + r.source.split('\n')[0].slice(0, 60)) : '',
        другойИсточник(r),
        r.lastChange ? h('div', { class: 'n mut' }, 'Последний перенос: ' + r.lastChange.slice(0, 80)) : '',
        чьё(r) && слова ? h('div', { class: 'exr-say', 'data-ex-say': '1' }, 'Клиент: «' + слова.slice(0, 200) + '»') : '',
        h('div', { class: 'exr-acts' }, плитка('cal', 'Перенос', 'перенос'), плитка('stop', 'Отмена', 'отмена', 'bad'), плитка('pin', 'Где мастер?', 'где_мастер'), прочееП),
        h('div', { class: 'exr-row' }, раскрыть, следить(r, 'exr-l'), h('a', { class: 'exr-l', href: r.url, target: '_blank', rel: 'noopener' }, svg('ext'), 'Открыть в CRM')),
        место);
    };
    // сетка действий заявки — под строкой / под полем ввода (по статусу в CRM); диалог связывается с заявкой перед действием
    const сеткаВ = (место, r) => { место.replaceChildren(ACT.сетка(crOf(r), { where: 'existing', conv: id, перед: () => связать(r) }) || ''); место.hidden = false; };
    // прошлая заявка — строкой: «МНЧ № 1049210 · 12.09» и «статус · город»; справа — её действия / претензия / CRM
    const прошлая = (r) => {
      const место = h('div', { class: 'exr-grid', hidden: true });
      const дата = (String(когда(r)).match(/\d{2}\.\d{2}/) || [])[0] || '';
      const ссылка = дРежим && актуально ? h('button', { class: 'ex-pa', 'aria-expanded': 'false', onclick: (e) => { if (место.hidden || !место.firstChild) сеткаВ(место, r); else место.hidden = true; e.currentTarget.setAttribute('aria-expanded', место.hidden ? 'false' : 'true'); } }, 'Действия')
        : /выполн|готов|оплач/i.test(r.status || '') ? h('button', { class: 'ex-pa', onclick: () => действие(r, 'претензия') }, 'Претензия')
          : r.url ? h('a', { class: 'ex-pa', href: r.url, target: '_blank', rel: 'noopener' }, 'В CRM ↗') : '';
      return h('div', { class: 'ex-pw' }, h('div', { class: 'ex-pr' },
        h('span', { class: 'l' }, dirName(r.dir) + ' № ' + r.id + (дата ? ' · ' + дата : '')),
        h('span', { class: 'r', title: [r.status, когда(r), r.city].filter(Boolean).join(' · ') }, [r.status || '—', r.city].filter(Boolean).join(' · ')), ссылка), место);
    };
    // другая заявка — по номеру и базе (клиент назвал № / заявка на другой номер телефона)
    const вручную = () => {
      const место = h('div', { class: 'exr-grid', hidden: true });
      const база = h('select', { class: 'exr-sel', 'aria-label': 'База' }, ...['kp', 'bt', 'mnc'].map((d) => h('option', { value: d, selected: d === (W.dir || (все[0] && все[0].dir) || 'kp') }, dirName(d))));
      const номер = h('input', { class: 'exr-num', inputmode: 'numeric', placeholder: '№ заявки', 'aria-label': 'Номер заявки' });
      const ош = h('div', { class: 'n warn', hidden: true });
      const открыть = () => {
        const n = String(номер.value || '').replace(/\D/g, '');
        if (!/^\d{6,8}$/.test(n)) { ош.textContent = 'Номер заявки — 6–8 цифр'; ош.hidden = false; номер.focus(); return; }
        ош.hidden = true;
        сеткаВ(место, { id: n, dir: база.value, open: true, status: '', url: '' });
      };
      номер.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); открыть(); } });
      return h('details', { class: 'exr-man', open: !все.length },
        h('summary', {}, 'Открыть по номеру…'),
        h('div', { class: 'exr-manrow' }, база, номер, h('button', { class: 'exr-l', onclick: открыть }, 'Открыть')), ош, место);
    };
    // «Прошлые заявки клиента» (проект «Действия»): списком; в окне «Действия» — открыты, при проверке перед созданием — свёрнуты
    const прошлыеБлок = () => {
      const ручной = дРежим && актуально ? вручную() : '';
      if (!прошлые.length) return ручной ? h('div', { class: 'ex-past' }, ручной) : '';
      return h('details', { class: 'ex-past lst-d', open: дРежим, 'data-ex-past': '1' },
        h('summary', {}, h('span', {}, 'Прошлые заявки клиента'), h('span', { class: 'cnt' }, String(прошлые.length))),
        ...прошлые.slice(0, 8).map(прошлая),
        прошлые.length > 8 ? h('div', { class: 'n mut' }, 'ещё ' + (прошлые.length - 8) + ' — в CRM') : '',
        ручной);
    };
    const скрыть = h('button', { class: 'ib', 'aria-label': 'Скрыть', title: 'Скрыть до нового сообщения (Esc)', onclick: () => card.classList.remove('show') }, svg('close'));
    const создатьНовую = () => h('div', { class: 'row acf' },
      h('button', { class: актуальные.length ? 'go2' : 'go', onclick: () => { W.exSkip = id; W.lastId = ''; card.classList.remove('show'); } }, актуальные.length ? 'Всё равно создать новую' : 'Создать новую'));
    const непроверены = (ex.unchecked || []).length ? h('div', { class: 'n mut' }, 'Не проверены: ' + ex.unchecked.map((u) => dirName(u.dir) + ' (' + u.error + ')').join(', ')) : '';
    if (актуальные.length === 1 && актуально) {
      /* одна актуальная заявка (проект «Действия»): шапка — «МНЧ № N» крупно, имя клиента и «обновлено N с назад», статус меткой;
         ниже — сетка действий этой заявки («Что в заявке», «Предлагаю …», 6 плиток, «Ещё (N)», «Нет здесь»), прошлые заявки, «Открыть по номеру…» */
      const r = актуальные[0];
      const метка = h('span', { class: 'ac-pill exr-st ' + цвет(r.status), 'data-ex-st': '1' }, String(r.status || '—'));
      const обн = h('button', { class: 'ex-upd', title: 'Перечитать заявку в CRM', hidden: true });
      const имя = имяКлиента(id);
      let at = 0;
      const тик = () => { if (!обн.isConnected || !at) return; обн.textContent = назад(at); setTimeout(тик, 15000); };
      const место = h('div', { 'data-act-here': r.dir + ':' + r.id });
      место.append(ACT.сетка(crOf(r), { where: 'existing', conv: id, перед: () => связать(r), безШапки: true, подсказка: подсказкаКлиента(r), выделить: чьё(r) && fR ? КЛЮЧИ[fR.intent] || '' : '',
        наСнимок: ({ snap, at: a, обновить }) => {
          const был = at; at = a || Date.now();
          метка.textContent = (snap && snap.statusName) || r.status || '—'; метка.className = 'ac-pill exr-st ' + цвет(метка.textContent);
          обн.hidden = false; обн.textContent = назад(at); обн.onclick = () => обновить();
          if (!был) setTimeout(тик, 15000);
        } }) || '');
      card.replaceChildren(
        h('div', { class: 'hd', 'data-ex-card': '1' }, дРежим ? '' : h('span', { class: 'ac-ic warn' }, svg('warn')),
          h('div', { class: 'ttl' }, h('div', { class: 'tt ex-num' }, dirName(r.dir) + ' № ' + r.id), h('div', { class: 'sub', 'data-ex-sub': '1' }, имя ? имя + ' · ' : '', обн)),
          метка, скрыть),
        дРежим ? '' : h('div', { class: 'ac-line warn', 'data-ex-dup': '1' }, svg('warn'), h('span', {}, 'У клиента уже есть эта заявка — сначала решите по ней, новая будет дублем')),
        r.source ? h('div', { class: 'n mut' }, 'Источник: ' + r.source.split('\n')[0].slice(0, 60)) : '',
        другойИсточник(r),
        место,
        h('div', { class: 'exr-row ex-foot' }, следить(r)),
        прошлыеБлок(),
        непроверены,
        дРежим ? '' : создатьНовую());
    } else {
      card.replaceChildren(
        h('div', { class: 'hd', 'data-ex-card': '1' }, h('span', { class: дРежим ? 'ac-ic' : 'ac-ic warn' }, svg(дРежим ? 'list' : 'warn')),
          h('div', { class: 'ttl' }, h('div', { class: 'tt' }, дРежим ? (актуальные.length ? 'Действия по заявке' : все.length ? 'Заявки клиента' : 'Заявок клиента не нашёл')
            : актуальные.length ? 'У клиента есть актуальная заявка' : 'У клиента были заявки'),
            h('div', { class: 'sub' }, дРежим ? (актуальные.length ? 'Открытых заявок ' + актуальные.length + ' — выберите нужную' : все.length ? 'Открытых нет — действия по прошлой или по номеру' : 'Введите номер заявки ниже')
              : актуальные.length ? 'Сначала решите по ней — новая будет дублем' : 'Нашёл в CRM по этому клиенту')),
          скрыть),
        ...актуальные.map(живая),
        прошлыеБлок(),
        непроверены,
        дРежим ? '' : создатьНовую());
    }
    card.classList.toggle('top', !!inlineBtn);
    card.classList.add('show');
    card.scrollTop = 0;
    // Esc — скрыть (как крестик), пока на экране эта карточка
    card.onkeydown = (e) => { if (e.key === 'Escape' && card.querySelector('[data-ex-card]')) { e.preventDefault(); card.classList.remove('show'); } };
    // снимки CRM заранее (только чтение): плитка и сетка откроются без ожидания. Одна заявка — её сетка уже читает сама
    if (актуально && актуальные.length > 1) for (const r of актуальные) { try { Promise.resolve(ACT.снимок(crOf(r), false)).catch(() => {}); } catch (_e) { /* не страшно */ } }
    btnState({ ready: false });
  }

  /* ---------- клиент дописал после создания заявки ---------- */
  // разобранное ИИ «по заявке», которое не показали (оператор в это время смотрел другой диалог или открыл панель), — до показа:
  // вернётся в диалог — карточка (без второго разбора). Новое сообщение клиента — разбор заново
  const ДОПИСКИ = new Map();
  function показатьДописку(id, cr, r, seen, last) {
    showAdditionCard(id, cr, r, seen).then((показана) => { if (показана === false) ДОПИСКИ.set(id, { last, r, seen }); }).catch(() => {});
  }
  /* каждые 20 с — сначала только последнее сообщение (limit=1). После «видели» ничего нет или с прошлого круга ничего не
     изменилось, а дописка уже разобрана (или ИИ ещё рано звать) — всю страницу не читаем; иначе — как раньше, 50 последних */
  async function watchAdditions(id, cr) {
    const since = cr.seenAt || cr.at || 0;
    const last0 = последнееИз(await лента(id, 1));
    const last = last0 && { ...last0, body: LC_EXTRACT.сКонтактом(last0) };      // контакт MAX — словами
    if (!last || !(Date.parse(last.created_at) > since)) return;   // новее «видели» ничего — и дописок нет
    // снимок: тот же диалог, то же «видели», то же последнее сообщение (и его расшифровка) — что разобрали на прошлом круге
    const снимок = [id, since, last.id, (String(last.body || '').trim() || last.voice_transcript) ? 1 : 0].join('|');
    const был = W.addSnap && W.addSnap.k === снимок ? W.addSnap : null;
    if (был) {
      if (!был.lastFresh) return;                                  // новых слов клиента нет
      const ж = ДОПИСКИ.get(id);
      if (!(ж && ж.last === был.lastFresh) && (W.addLast === был.lastFresh || Date.now() - (W.addAt || 0) < 45000)) return;
    }
    const page = await лента(id, 50);
    const items = (page.items || []).map((m) => ({ ...m, body: LC_EXTRACT.сКонтактом(m) })).sort((x, y) => Date.parse(x.created_at) - Date.parse(y.created_at));   // контакт MAX — словами
    const incoming = items.filter((m) => m.direction === 'in' && m.sender_type !== 'system'
      && !(typeof LC_EXTRACT.служебное === 'function' && LC_EXTRACT.служебное(m)) && Date.parse(m.created_at) > since);
    if (incoming.length && ACT && ['kp', 'bt', 'mnc'].includes(cr.dir)) {
      if (!W.meta || W.conv !== id) { W.conv = id; W.meta = { conv: await деталь(id) }; }
      const conv = W.meta.conv || {}, channel = conv.channel || (conv.account || {}).channel || cr.channel;
      // Канал берём из метаданных, не угадываем Jivo по словам клиента или имени аккаунта.
      if (String(channel || '').toLowerCase() === 'jivo') {
        let hasClaim = cr.claimMsg ? true : cr.hasClaim;
        if (hasClaim === undefined || hasClaim === null) {
          const claims = await send({ kind: 'lcz-crm', op: 'claims', args: { dir: cr.dir, id: cr.id } });
          if (claims && claims.ok) hasClaim = claims.count > 0;
        }
        const message = incoming[incoming.length - 1];
        const notice = LC_REQUEST_NOTES.claimReply({ id: cr.id, channel, hasClaim, incoming: true, messageId: message.id });
        if (notice) {
          const r = { ok: true, important: true, намерение: 'jivo_claim_reply', rule_action: true,
            channel: 'jivo', incoming: true, messageId: message.id, hasClaim: true, summary: String(message.body || '').slice(0, 500) };
          const seen = Date.parse(message.created_at);
          cr = { ...cr, hasClaim: true };
          const pending = ДОПИСКИ.get(id);
          if (W.addLast === message.id && !(pending && pending.last === message.id)) return;
          W.addLast = message.id;
          if (convIdNow() !== id || panel.classList.contains('open')) ДОПИСКИ.set(id, { last: message.id, r, seen });
          else { ДОПИСКИ.delete(id); показатьДописку(id, cr, r, seen, message.id); }
          return; // Даже «спасибо» и вложение требуют отписки: решение модели о важности не подменяет это правило.
        }
      }
    }
    const fresh = items.filter((m) => m.direction === 'in' && Date.parse(m.created_at) > since && ((m.body || '').trim() || m.voice_transcript));
    // голосовое клиента ещё без расшифровки (а последним уже стоит другое сообщение) — снимок не запоминаем: читаем каждый круг, как раньше
    const безТекста = items.some((m) => m.direction === 'in' && Date.parse(m.created_at) > since && !((m.body || '').trim() || m.voice_transcript)
      && (m.voice_transcript_status ? !/^(done|failed|too_long)$/.test(String(m.voice_transcript_status)) : LC_EXTRACT.голосовое(m)));
    W.addSnap = безТекста ? null : { k: снимок, lastFresh: fresh.length ? fresh[fresh.length - 1].id : '' };
    if (!fresh.length) return;
    const lastFresh = fresh[fresh.length - 1];
    const ждёт = ДОПИСКИ.get(id);
    if (ждёт && ждёт.last === lastFresh.id) {                       // разобрано, а показать не успели — показываем сейчас
      if (convIdNow() !== id || panel.classList.contains('open')) return;
      ДОПИСКИ.delete(id);
      показатьДописку(id, cr, ждёт.r, ждёт.seen, ждёт.last);
      return;
    }
    if (W.addLast === lastFresh.id) return;                        // это уже разбирали
    if (Date.now() - (W.addAt || 0) < 45000) return;               // ИИ не чаще раза в 45 с
    W.addAt = Date.now();
    if (!W.meta || W.conv !== id) { W.conv = id; W.meta = { conv: await деталь(id) }; }
    const item = объявлениеДиалога(W.meta.conv);
    const pick = (m) => ({ direction: m.direction, sender_type: m.sender_type, body: m.body, voice_transcript: m.voice_transcript, created_at: m.created_at });
    const r = await send({ kind: 'lcz-addition', args: { ctx: { city: городОбъявления(item), tz: поясОбъявления(item),
      before: items.filter((m) => Date.parse(m.created_at) <= since).map(pick), fresh: fresh.map(pick) } } });
    W.addLast = lastFresh.id;
    // слова клиента — карточке: назвал адрес — она сверит его с карточкой клиента в CRM
    // и время первого из них (часы LeadChat): адрес, распознанный LeadChat после него, — новый
    if (r && typeof r === 'object') { r.text = fresh.map((m) => String(m.body || m.voice_transcript || '').trim()).filter(Boolean).join(' / ').slice(0, 500); r.from = Date.parse(fresh[0].created_at) || 0; }
    const seen = Date.parse(lastFresh.created_at);
    ДОПИСКИ.delete(id);                                             // прежний неразобранный итог — про более раннее
    if (!r || !r.ok || !r.important) { await markSeen(id, seen); return; }
    // оператор ушёл в другой диалог или открыл панель, пока ИИ читал: не теряем — покажем, когда вернётся
    if (convIdNow() !== id || panel.classList.contains('open')) { ДОПИСКИ.set(id, { last: lastFresh.id, r, seen }); return; }
    показатьДописку(id, cr, r, seen, lastFresh.id);
  }
  async function markSeen(id, t) {
    await правитьCreated((all) => { if (!all[id]) return false; all[id].seenAt = Math.max(all[id].seenAt || 0, t); });
  }
  /* запись 'created' (диалог → его заявка) правят многие: создание в фоне, наблюдение, «где мастер», действия. Каждая правка —
     чтение → изменение → запись под одним замком 'lcz-created': иначе две правки разом (создание A и наблюдение за B) читают
     один старый список, и вторая запись стирает первую. fn(all) меняет all на месте; false — ничего не писать.
     Внутри fn — без await других правок 'created' (замок один) */
  function правитьCreated(fn) {
    return поОдному('lcz-created', async () => {
      const all = (await store.get('created', {})) || {};
      if ((await fn(all)) !== false) await store.set('created', all);
      return all;
    });
  }
  const ЗАГОЛОВОК = { перенос: 'Клиент просит перенести заявку № ', отмена: 'Клиент отменяет заявку № ', где_мастер: 'Клиент спрашивает, где мастер (№ ',
    претензия: 'Клиент жалуется по заявке № ', отдел_авито: 'Диалог — отделу Авито (заявка № ', дополнение: 'Клиент дописал к заявке № ' };
  /* План по заявке: что делаем в CRM и что пишем в какой чат — как делают чатеры (разобрано по чатам и Чатерскому) */
  function планПоЗаявке(cr, r, seen) {
    const intent = ЗАГОЛОВОК[r.intent] ? r.intent : 'дополнение';
    const hm = new Date(seen || Date.now()).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
    const p = { intent, date: r.date || '', time: r.time || '', tg: '', crm: '', move: false, cancel: false, claim: false, chat: 'city' };
    if (intent === 'перенос') {
      p.move = true; p.fromDate = cr.visit || ''; p.fromTime = cr.visitTime || '';
      p.tg = LC_TG.followText({ id: cr.id, intent, date: r.date, time: r.time, fromDate: p.fromDate, fromTime: p.fromTime });
    }
    if (intent === 'отмена') { p.cancel = true; p.tg = LC_TG.followText({ id: cr.id, intent }); p.reason = LC_TG.причинаОтмены((r.reason || '') + ' ' + (r.summary || '')); p.crm = 'Отмена, ' + p.reason; p.service = 'Отмена с Авито'; }
    if (intent === 'где_мастер') {
      p.tg = LC_TG.followText({ id: cr.id, intent, status: cr.status, phone: cr.phone10, prozvon: cr.prozvon, service: cr.service });
      // СД: служебный комментарий — оператору на глаза (там бывает «звонить только на второй номер»)
      if (/в работе сд/i.test(cr.status || '') && cr.service) p.note = 'Служебный комментарий: «' + cr.service.slice(0, 200) + '»';
    }
    if (intent === 'претензия') { p.claim = true; p.chat = 'claims'; p.tg = LC_TG.followText({ id: cr.id, intent }); p.crm = 'Претензия клиента ' + hm + ': ' + (r.summary || '');
      p.claimType = LC_TG.типПретензии((r.summary || '') + ' ' + (r.reason || '')); p.claimComment = 'Со слов клиента (чат ' + hm + '): ' + (r.summary || '');
      // претензия уже есть — регламент: «№ снова звонит, описание» ответом на прежнее сообщение в чате претензий
      if (cr.hasClaim) { p.claim = false; p.again = true; p.tg = cr.id + ' снова звонит, ' + (r.summary || 'по претензии'); p.crm = 'Снова обращается по претензии ' + hm + ': ' + (r.summary || ''); p.replyTo = cr.claimMsg && cr.claimMsg.msg; p.note = 'Претензия по заявке уже есть — пишем «снова звонит»' + (p.replyTo ? ' ответом на «новая претензия»' : ''); } }
    if (intent === 'дополнение') { p.tg = LC_TG.followText({ id: cr.id, intent, summary: r.summary }); p.crm = 'Доп. от клиента ' + hm + ': ' + (r.summary || ''); }
    // регламент: хвалит мастера / хочет отзыв / пишет не по теме — диалог передают отделу Авито (негатив без отзыва — это претензия)
    if (intent === 'отдел_авито') { p.transfer = true; p.reason = (r.summary || 'отзыв о мастере') + ' (заявка № ' + cr.id + ')'; }
    return p;
  }
  /* НОВЫЙ АДРЕС ПО ЗАЯВКЕ. Адрес в CRM — у клиента (карточка клиента), а не у заявки. Клиент назвал адрес (или кв, подъезд, этаж) —
     разбираем диалог тем же разбором, что заявку (ИИ + карта LeadChat), и сверяем с карточкой клиента в CRM (план, без записи).
     Отличается — в карточке «по заявке» галочка «Сменить адрес…»: адрес подтверждён картой / проверками — стоит, нет — снята, «сверьте».
     Пишем только по «Сделать». Разбор ИИ — только когда в словах клиента есть адрес (не на каждое «спасибо») */
  const АДРЕС_ДЛЯ = new Set(['дополнение', 'перенос', 'где_мастер']);
  // слова адреса; «слово + число» (LC_EXTRACT.естьАдрес) — только в дополнении: в переносе это «в 12 часов», а не дом
  const АДРЕС_СЛОВАМИ = /адрес|переех|подъезд|этаж|домофон|квартир|улиц|проспект|переул|шоссе|бульвар|микрорайон|деревн|пос[её]лок|(^|[^а-яё])(?:ул|мкр|снт)(?![а-яё])|(^|[^а-яё])(?:кв|д)\.?\s*\d/i;
  const адресВСловах = (intent, r) => { const t = [r && r.summary, r && r.text].filter(Boolean).join('\n');
    return АДРЕС_ДЛЯ.has(intent) && (АДРЕС_СЛОВАМИ.test(t) || (intent === 'дополнение' && LC_EXTRACT.естьАдрес(t))); };
  /* Адрес, который LeadChat распознал в ЭТОМ диалоге из новых сообщений клиента (от — время первого из них, часы LeadChat) и ещё
     не принял. Разбор берёт адрес карточки LeadChat, а прежний адрес там держится, пока LeadChat не примет новый (~90 с тишины):
     карточка «по заявке» к этому времени уже показана — без кандидата новый адрес сверился бы как старый, и галочки не было бы */
  function новыйАдресLeadChat(A, id, от) {
    const после = Number(от) || 0;
    const idn = A && A.ctx && A.ctx.identity;
    if (!после || !idn) return null;
    const свежие = (idn.address_candidates || []).filter((c) => c && (!c.status || c.status === 'pending') && String(c.conversation_id || '') === String(id)
      && (Date.parse(c.detected_at) || 0) >= после);
    if (!свежие.length) return null;
    const f = LC_EXTRACT.fromIdentity({ address_candidates: свежие }, id);
    const a = f.addr;
    if (!a || !a.building || !(a.street || a.settlement)) return null;
    // город точки («Москва») — не нас. пункт: в карточку клиента идёт только нас. пункт (как при создании)
    return { addr: { street: a.street || '', building: a.building, office: a.office || '', entrance: a.entrance || '', floor: a.floor || '', intercom: !!a.intercom, settlement: a.settlement || '' },
      ok: !!f.geoOk, note: f.geoOk ? '' : 'LeadChat ещё не принял этот адрес' + (f.geoNote ? ' (' + f.geoNote + ')' : '') };
  }
  async function адресПоЗаявке(id, cr, от) {
    const A = await analyze(id);
    let a = (A.lead && A.lead.addr) || {};
    const чек = (A.checks || []).find((c) => c.field === 'address') || {};
    let верно = !!чек.ok && !A.lead.addr_warn, почему = String(A.lead.addr_warn || чек.note || 'адрес не подтверждён картой');
    const н = новыйАдресLeadChat(A, id, от);
    const тотЖе = (x, y) => LC_EXTRACT.тотЖеАдрес(x, y) || (!x.street && !y.street && !!x.settlement
      && String(x.settlement).toLowerCase() === String(y.settlement || '').toLowerCase() && LC_EXTRACT.домКлюч(x.building) === LC_EXTRACT.домКлюч(y.building || ''));
    if (н && !тотЖе(н.addr, a)) { a = н.addr; верно = н.ok; почему = н.note; }
    if (!a.building || !(a.street || a.settlement)) return null;      // дома нет — менять не на что
    const план = await send({ kind: 'lcz-crm', op: 'customerAddress', args: { dir: cr.dir, id: cr.id, addr: a, dry: true } });
    if (!план || !план.ok) return { error: String((план && план.error) || 'нет ответа').slice(0, 100), url: (план && план.url) || '' };
    if (!(план.changed || []).length) return null;                    // в карточке клиента уже этот адрес
    return { addr: a, line: план.line || '', was: план.was || '', house: !!план.house, changed: план.changed, url: план.url || '', on: верно,
      сверьте: верно ? '' : почему,
      // в чат города — только другой дом и без кв (точный адрес — в CRM); кв/подъезд/этаж того же дома чат не меняют
      tg: план.house ? LC_TG.followText({ id: cr.id, intent: 'адрес', address: [a.settlement, a.street, a.building].filter(Boolean).join(', ') }) : '' };
  }
  // куда писать по заявке: чат претензий / ответом на своё согласование / чат, где создавали / чат города
  async function чатПоЗаявке(id, cr, p) {
    const c = await send({ kind: 'lcz-tg', args: { action: 'chats' } });
    const tgRec = p.intent === 'дополнение' ? (sentList(await tgSentGet(id))[0] || null) : null;
    let chat = '', title = '', reply;
    if (p.chat === 'claims') { const m = c && c.ok ? LC_TG.claimChat(c.chats, cr.dir) : null; chat = m && m.id; title = m && m.title; if (p.replyTo && cr.claimMsg && cr.claimMsg.chat === chat) reply = p.replyTo; }
    else if (tgRec) { chat = tgRec.chat; title = tgRec.title; reply = tgRec.msg; }
    else if (cr.chat) { chat = cr.chat; title = cr.chatTitle; }
    else { const m = c && c.ok ? LC_TG.matchChat(c.chats, cr.dir, cr.city || '') : null; chat = m && m.id; title = m && m.title; }
    return { chat, title, reply };
  }
  /* Сделать по плану: сначала CRM (перенос / Отмена КЦ / претензия), и только если CRM приняла — сообщение в чат */
  async function сделатьПоЗаявке(id, cr, p, o) {
    const res = [];
    let tg = p.tg;
    if (p.intent === 'перенос' && p.move && !p.date && !p.time) return { ok: false, text: 'поставьте новую дату и время (спросите у клиента) — без них не переносим, в чат не писали' };
    /* 1.20: действия — через общий бегунок: замок заявки, журнал «никогда дважды», защита от перекрытия до CRM, без авто-повтора,
       заметка в диалог. Передача диалога отделу Авито — только LeadChat, её делает код ниже */
    if (ACT && !p.transfer) return ACT.поПлану(id, cr, p, o);
    // защита от перекрытия — до любых действий в CRM (иначе перенос/отмена сделаны, а в чат не написали)
    let куда = null;
    if (tg && p.tgOn !== false) {
      куда = await чатПоЗаявке(id, cr, p);
      if (куда.chat && !куда.reply && !p.force && p.chat !== 'claims') {
        const g = await просьбыВЧате(куда.chat);
        if (g && g.length) return { ok: false, guard: { list: g, title: куда.title || '' },
          text: 'В «' + (куда.title || 'чат города') + '» ждёт ответа просьба филиала: ' + LC_TG.просьбаКратко(g[g.length - 1]) + '. Ничего не делали — ответьте филиалу или «Всё равно отправить»' };
      }
    }
    // новый адрес — в карточку клиента CRM (своего адреса у заявки нет) — ПЕРВЫМ из CRM: не сменился — в CRM ничего не сделано, и
    // «Сделать» ещё раз начнёт с чистого листа (перенос вторым нажатием отказал бы: «в заявке уже стоит это время»). Сменился, а дальше
    // сбой — итог помним: повтор CRM не спрашивает (там уже новый адрес, «поменялось» было бы пусто) и строк об адресе не теряет
    let адресВКомментарий = '', домВЧат = '';
    if (p.адрес && p.addrOn) {
      const c = p.адресИтог && p.адресИтог.для === p.адрес ? p.адресИтог.c
        : await send({ kind: 'lcz-crm', op: 'customerAddress', args: { dir: cr.dir, id: cr.id, addr: p.адрес.addr } });
      if (!c || !c.ok) return { ok: false, text: 'адрес в карточке клиента CRM не сменился: ' + ((c && c.error) || 'ошибка') + (c && c.url ? ' (' + c.url + ')' : '') + ' — в CRM больше ничего не делали, в чат не писали' };
      const строка = c.line || p.адрес.line;
      res.push((c.changed || []).length ? 'в карточке клиента CRM: ' + c.changed.join(', ') + ' — ' + строка : 'в карточке клиента CRM уже этот адрес');
      res.push(...(c.warnings || []));
      if ((c.changed || []).length) {
        p.адресИтог = { для: p.адрес, c: { ...c, warnings: [] } };
        адресВКомментарий = 'Адрес изменён клиентом ' + p.адрес.hm + ': ' + строка;
        if (p.адрес.tg && p.intent !== 'дополнение') домВЧат = p.адрес.tg;
      }
    }
    if (p.move) {
      const m = await send({ kind: 'lcz-crm', op: 'reschedule', args: { dir: cr.dir, id: cr.id, date: p.date || '', time: p.time || '', reason: 'Клиент' } });
      if (!m || !m.ok) return { ok: false, text: res.concat('в CRM не перенесено: ' + ((m && m.error) || 'ошибка') + ' — в чат не писали').join(' · ') };
      res.push('в CRM перенесено' + (m.now ? ' (' + m.now.trim() + ')' : ''));
      if (m.lastChange && p.tgAuto !== false) tg = LC_TG.followText({ id: cr.id, intent: 'перенос', crmLine: m.lastChange });
    }
    // строка-заготовка с «…» (нового времени нет) в чат не уходит
    if (p.intent === 'перенос' && /"…|…"/.test(tg || '')) { res.push('в чат не писали: нет нового времени'); tg = ''; }
    if (p.cancel) {
      const c = await send({ kind: 'lcz-crm', op: 'cancelKc', args: { dir: cr.dir, id: cr.id, comment: p.crm || '', service: p.service || '', by: p.by || 'kc' } });
      if (!c || !c.ok) return { ok: false, text: res.concat('в CRM не отменено: ' + ((c && c.error) || 'ошибка') + ' — в чат не писали').join(' · ') };
      res.push(c.already ? 'в CRM уже «' + c.status + '»' : 'в CRM «' + (c.status || (p.by === 'branch' ? 'Отмена Филиал' : 'Отмена КЦ')) + '»');
    }
    if (p.claim) {
      const c = await send({ kind: 'lcz-crm', op: 'claim', args: { dir: cr.dir, id: cr.id, typeNo: p.claimType, comment: p.claimComment } });
      if (!c || !c.ok) return { ok: false, text: res.concat('претензия не создана: ' + ((c && c.error) || 'ошибка') + ' — в чат не писали').join(' · ') };
      res.push((c.already ? 'претензия уже была' : 'претензия создана' + (c.claimId ? ' №' + c.claimId : '')) + (c.typed ? ', тип: ' + c.type : '') + (c.warn ? ' (' + c.warn + ')' : ''));
    }
    // строка нового дома — второй строкой того же сообщения в чат (перенос / «где мастер»; в дополнении она уже в тексте)
    if (домВЧат && tg && !tg.includes(домВЧат)) tg = tg + '\n' + домВЧат;
    if (p.transfer) {
      if (!p.assignee) return { ok: false, text: 'не выбран сотрудник отдела Авито' };
      // передача диалога, у которого есть ответственный, в LeadChat — ПРЕДЛОЖЕНИЕ: диалог наш, пока коллега не примет (до 15 мин)
      let ответ;
      // комментарий передачи LeadChat берёт до 1000 знаков (длиннее — 422 и диалог не передан): длинную причину — с «…»
      try { ответ = await LC.post('/conversations/' + encodeURIComponent(id) + '/assign', { assignee_id: p.assignee, comment: обрезать('Передаю отделу Авито: ' + (p.reason || ''), КОММЕНТАРИЙ_LC) }); }
      catch (e) { return { ok: false, text: 'не передалось: ' + String(e.message || e).slice(0, 120) }; }
      const кому = p.assigneeName || 'отдел Авито';
      if (ответ && ответ.conversation && ответ.conversation.transfer) {
        res.push('предложено ' + кому + ', ждёт принятия (до 15 мин) — если не примут, скажу');
        await запомнитьПередачу(id, { toName: кому, name: имяКлиента(id) });
      } else res.push('диалог передан: ' + кому);
    }
    let failed = false;
    // строка о смене адреса — часть действия «Сменить адрес» (идёт и при снятой «Дописать в комментарий»)
    const вКомментарий = [p.crm && !p.cancel && p.crmOn !== false ? p.crm : '', адресВКомментарий].filter(Boolean).join('\n');
    if (вКомментарий) {
      const r = await send({ kind: 'lcz-crm', op: 'comments', args: { dir: cr.dir, id: cr.id, change: { addComment: вКомментарий } } });
      if (!(r && r.ok)) failed = true;
      res.push(r && r.ok ? 'в комментарий дописано' : 'в комментарий не дописалось: ' + ((r && r.error) || 'ошибка'));
    }
    if (tg && p.tgOn !== false) {
      const { chat, title, reply } = куда || await чатПоЗаявке(id, cr, p);
      if (!chat) { failed = true; res.push('в Telegram не отправлено: ' + (p.chat === 'claims' ? 'чат претензий' : 'чат города «' + (cr.city || '?') + '»') + ' не найден'); }
      else {
        const r = await send({ kind: 'lcz-tg', args: { action: 'send', chat, reply_to: reply || undefined, conv: id, text: tg } });
        if (!(r && r.ok)) failed = true;
        else if (p.intent === 'претензия' && p.claim && r.message_id) {   // «новая претензия» — чтобы потом отвечать «снова звонит»
          try { await правитьCreated((all) => { all[id] = { ...(all[id] || cr), claimMsg: { chat, msg: r.message_id, at: Date.now() } }; }); } catch (_e) { /* не критично */ }
        }
        else if (p.intent === 'где_мастер' && r.message_id) {          // ждём ответ города — передать клиенту
          try { await правитьCreated((all) => { all[id] = { ...(all[id] || cr), whereMsg: { chat, title, msg: r.message_id, at: Date.now(), seen: Math.floor(Date.now() / 1000), crId: cr.id, dir: cr.dir } }; }); } catch (_e) { /* не критично */ }
        }
        res.push(r && r.ok ? 'в «' + (title || 'чат') + '»: ' + tg : 'в Telegram не отправлено: ' + ((r && (r.error || r.description)) || 'ошибка'));
      }
    }
    return { ok: !failed, text: res.join(' · ') || 'ничего не выбрано' };
  }
  // сотрудники LeadChat, кому можно передать диалог: сначала отдел Авито / партнёрский
  // presence: «online» — на месте, «away» — отошёл (передать можно), null — не в сети: LeadChat такому передать не даст (422)
  let ПОЛЬЗОВАТЕЛИ = null, ПОЛЬЗОВАТЕЛИ_ЗА = 0;
  const неВСети = (x) => x.presence === null || x.is_online === false;
  function сотрудникиАвито(p) {
    const sel = h('select', { 'data-add': 'assignee' }, h('option', { value: '' }, 'загружаем…'));
    (async () => {
      // кто в сети — меняется: список не старше минуты
      try { if (!ПОЛЬЗОВАТЕЛИ || Date.now() - ПОЛЬЗОВАТЕЛИ_ЗА > 60e3) { const u = await LC.get('/users/assignable'); ПОЛЬЗОВАТЕЛИ = (Array.isArray(u) ? u : u.items || u.users || []).filter((x) => x && x.is_active !== false); ПОЛЬЗОВАТЕЛИ_ЗА = Date.now(); } }
      catch (e) { sel.replaceChildren(h('option', { value: '' }, 'список сотрудников не загрузился: ' + String((e && e.message) || e).slice(0, 60))); return; }
      const отдел = (x) => String((x.department && (x.department.name || x.department.title)) || x.department || '');
      const ранг = (x) => (неВСети(x) ? 2 : x.presence === 'away' ? 1 : 0);
      const авито = ПОЛЬЗОВАТЕЛИ.filter((x) => /авито|партн/i.test(отдел(x) + ' ' + (x.full_name || '')));
      const список = (авито.length ? авито : ПОЛЬЗОВАТЕЛИ).slice().sort((a, b) => ранг(a) - ранг(b)).slice(0, 40);
      const вСети = авито.filter((x) => !неВСети(x));
      sel.replaceChildren(h('option', { value: '' }, авито.length ? (вСети.length ? 'выберите сотрудника отдела Авито' : 'отдел Авито сейчас не в сети — передать некому') : 'отдел Авито не найден — выберите вручную'),
        ...список.map((x) => h('option', { value: x.id, 'data-name': x.full_name || x.email || '', disabled: неВСети(x) },
          (x.full_name || x.email || x.id) + (отдел(x) ? ' · ' + отдел(x) : '') + (неВСети(x) ? ' — не в сети' : x.presence === 'away' ? ' — отошёл' : ''))));
      if (вСети.length === 1) { sel.value = вСети[0].id; p.assignee = вСети[0].id; p.assigneeName = вСети[0].full_name || ''; }
    })();
    return sel;
  }
  // имя клиента диалога без запроса: из открытой формы, наблюдения или списка «Готовые»
  function имяКлиента(id) {
    const c = (S && S.id === id && S.conv) || (W.conv === id && W.meta && W.meta.conv) || null;
    const x = READY.items.find((y) => y.id === id) || AUTO.taken.find((y) => y.id === id);
    return String((c && c.client && c.client.name) || (x && x.name) || '');
  }
  /* карточку держат (мышь над ней или оператор сам поставил фокус внутрь после итога) — автозакрытие ждёт.
     Слежка одна на карточку и общая с экраном действий (actions-ui.js ставит ту же card._рука) */
  function рукаКарточки() {
    if (card._рука) return card._рука;
    const р = card._рука = { наведено: false, фокус: 0, сам: false };
    card.addEventListener('mouseenter', () => { р.наведено = true; });
    card.addEventListener('mouseleave', () => { р.наведено = false; });
    card.addEventListener('focusin', () => { if (!р.сам) р.фокус = Date.now(); });
    card.addEventListener('focusout', (e) => { if (!e.relatedTarget || !card.contains(e.relatedTarget)) р.фокус = 0; });
    return р;
  }
  function автоЗакрытьКарточку(своя, мс) {
    const с = Date.now(), р = рукаКарточки();
    const внутри = () => { try { const a = card.getRootNode().activeElement; return !!a && card.contains(a); } catch (_e) { return false; } };
    const тик = () => {
      if (!своя()) return;
      let над = р.наведено; try { над = над || card.matches(':hover'); } catch (_e) { /* без :hover */ }
      if (над || (р.фокус > с && внутри())) { setTimeout(тик, 1500); return; }
      card.classList.remove('show');
    };
    setTimeout(тик, мс);
  }
  async function showAdditionCard(id, cr, r, seen) {
    рукаКарточки();
    if (typeof r === 'string') r = { intent: 'дополнение', summary: r };
    // Отписка по правилу не превращается при сбое карточки в обычное сообщение городу.
    if (r && r.rule_action === true && r.намерение === 'jivo_claim_reply')
      return ACT ? ACT.поНамерению(id, cr, r, seen).catch(() => false) : false;
    /* 1.20: действия — новые намерения ИИ (позвоните → Прозвон, срочно → Срочная, адрес, другое направление): карточка действия
       каталога, уже заполненная по словам клиента. Каталог не предложил — прежняя карточка «дополнение» */
    if (ACT && r && НОВЫЕ_НАМЕРЕНИЯ.includes(r.намерение) && (await ACT.поНамерению(id, cr, r, seen).catch(() => false))) return;
    if (r.intent === 'претензия' && cr && cr.id && cr.hasClaim === undefined) {
      const c = await send({ kind: 'lcz-crm', op: 'claims', args: { dir: cr.dir, id: cr.id } });
      if (c && c.ok) cr = { ...cr, hasClaim: c.count > 0 };
      const all = await store.get('created', {}); if (all[id] && all[id].claimMsg) cr = { ...cr, claimMsg: all[id].claimMsg };
    }
    // перенос: «с» — текущее время из CRM; «Прозвон» — для предупреждения о переносе на 2+ суток
    if (r.intent === 'перенос' && cr && cr.id && (!cr.visitTime || cr.prozvon === undefined)) {
      const i = await send({ kind: 'lcz-crm', op: 'info', args: { dir: cr.dir, id: cr.id } });
      if (i && i.ok && i.info) cr = { ...cr, visit: cr.visitTime ? cr.visit : i.info.visit || '', visitTime: cr.visitTime || i.info.visitTime || '', status: cr.status || i.info.cardStatus || '',
        prozvon: cr.prozvon !== undefined ? cr.prozvon : !!i.info.prozvon };
    }
    if (r.intent === 'где_мастер' && cr && cr.id) {
      const i = await send({ kind: 'lcz-crm', op: 'info', args: { dir: cr.dir, id: cr.id } });
      if (i && i.ok && i.info) cr = { ...cr, status: i.info.cardStatus || cr.status || '', phone10: i.info.phone10 || cr.phone10 || '', prozvon: !!i.info.prozvon,
        service: i.info.serviceComment || cr.service || '', visit: i.info.visit || cr.visit || '', visitTime: i.info.visitTime || cr.visitTime || '' };
    }
    // время города, визит, опоздание — «где мс?» (обновляется раз в 30 секунд, пока карточка открыта)
    const tzД = r.intent === 'где_мастер' ? await поясДиалога(id) : '';
    // пока спрашивали CRM, оператор ушёл в другой диалог (или открыл панель) — карточку диалога A поверх B не показываем (false — не показана)
    if (convIdNow() !== id || panel.classList.contains('open')) return false;
    // закрыли карточку — снова откроется кнопкой «№ заявки» в карточке клиента
    if (cr && cr.id && convIdNow() === id) btnState({ done: true, ready: false, id: cr.id });
    const summary = r.summary || '';
    const p = планПоЗаявке(cr, r, seen);
    const intent = p.intent;
    const state = { busy: false, done: '', ok: false, guard: null };
    // новый адрес клиента: сверка с CRM идёт после показа карточки (ИИ + CRM — секунды), галочка появляется в карточке сама
    const адрес = { идёт: !!(cr && cr.id && cr.dir) && адресВСловах(intent, r), x: null };
    const tgБезАдреса = p.tg;
    const hmКлиента = new Date(seen || Date.now()).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
    // дополнение: в чат — строка нового дома вместо пересказа (пока оператор текст не правил); галочку сняли — пересказ обратно
    function адресВЧат() {
      const ta2 = card.querySelector('[data-add="tgtext"]');
      if (intent !== 'дополнение' || !адрес.x || !адрес.x.tg || !ta2 || ta2.value.trim() !== String(p.tg || '').trim()) return;
      p.tg = p.addrOn ? адрес.x.tg : tgБезАдреса;
      ta2.value = p.tg;
    }
    const адресБлок = () => {
      const x = адрес.x;
      if (адрес.идёт) return h('div', { class: 'n mut', 'data-add': 'addrbox' }, 'Клиент назвал адрес — сверяю с карточкой клиента в CRM…');
      if (!x) return h('div', { 'data-add': 'addrbox', hidden: true });
      if (x.error) return h('div', { class: 'n warn', 'data-add': 'addrbox' }, 'Клиент назвал адрес, а сверить его с карточкой клиента в CRM не вышло (' + x.error + ') — проверьте адрес в CRM сами');
      // «Сделать» нажали раньше, чем пришла сверка, — адрес этим нажатием не менялся: только сказать
      if (x.поздно) return h('div', { class: 'n warn', 'data-add': 'addrbox' }, 'Клиент назвал новый адрес: ' + x.line + ' (в CRM: ' + (x.was || 'адреса нет') + ') — смените в карточке клиента: ',
        h('a', { href: x.url, target: '_blank', rel: 'noopener' }, 'открыть'));
      return h('div', { 'data-add': 'addrbox' },
        h('label', { class: 'ck' }, h('input', { type: 'checkbox', 'data-add': 'addr', checked: !!p.addrOn, onchange: (e) => { p.addrOn = e.target.checked; адресВЧат(); } }),
          'Сменить адрес в карточке клиента CRM: ' + x.line),
        h('div', { class: 'n mut' }, 'Сейчас в CRM: ' + (x.was || 'адреса нет') + ' · поменяется: ' + x.changed.join(', ') + ' · в комментарий заявки — «Адрес изменён клиентом»'),
        x.сверьте ? h('div', { class: 'n warn' }, 'Сверьте адрес с клиентом: ' + x.сверьте) : '',
        x.tg && intent !== 'дополнение' ? h('div', { class: 'n mut' }, 'В чат допишется: «' + x.tg + '»') : '');
    };
    const idВопроса = новыйId();                                      // «Спросить у клиента время»: id один на карточку
    /* 1.20: действия — ИИ мог ошибиться: «Другое действие ▾» открывает карточку любого доступного действия (превью пересобирается).
       Метка карточки: ушёл в другой диалог или закрыл её посреди «Сделать» — итог придёт уведомлением */
    const другое = ACT ? ACT.другоеДействие(id, cr, r, seen) : '';
    const мояДоп = {};
    const наВиду = () => card._доп === мояДоп && card.classList.contains('show');
    const ta = (k, v) => h('textarea', { 'data-add': k, value: v, style: 'min-height:40px;text-transform:none;letter-spacing:0;font-weight:400;color:var(--t1)' });
    const ck = (k, on, text) => h('label', { class: 'ck' }, h('input', { type: 'checkbox', 'data-add': k, checked: on }), text);
    // регламент (штраф 27): заявку «на прозвоне» двинуть на 2-е сутки и дальше — штраф 200 ₽; сегодня — по часам клиента
    const поясЗаявки = LC_EXTRACT.clientTz(ПОЯС_ДИАЛОГА.get(id) || '', LC_TERRITORY.чистыйГород((cr && cr.city) || '')).tz;   // 2.1: и окну выбора времени
    const сегодняКлиента = LC_EXTRACT.localParts(new Date(), поясЗаявки).iso;
    const прозвонДалеко = (d) => !!(cr && cr.prozvon && /^\d{4}-\d{2}-\d{2}$/.test(d || '') && (Date.parse(d) - Date.parse(сегодняКлиента)) / 864e5 >= 2);
    // перенос: дата и время сразу меняют строку для чата (формат «Переносов» CRM)
    function обновитьПеренос() {
      const q = (k) => card.querySelector('[data-add="' + k + '"]');
      const d = (q('date') || {}).value || '', t = (q('time') || {}).value || '';
      const пз = q('prozvon2'); if (пз) пз.hidden = !прозвонДалеко(d);
      const ta2 = q('tgtext');
      if (ta2 && (p.tgAuto !== false) && ta2.value.trim() === String(p.tg || '').trim()) {
        p.tg = LC_TG.followText({ id: cr.id, intent: 'перенос', date: d, time: t, fromDate: p.fromDate, fromTime: p.fromTime });
        ta2.value = p.tg;
      }
      const nt = q('notime'); if (nt) nt.hidden = !!t;
    }
    const read = () => {
      const qa = card.querySelector('[data-add="assignee"]');
      if (qa) { const o = qa.selectedOptions[0]; p.assignee = qa.value; p.assigneeName = (o && (o.getAttribute('data-name') || o.textContent)) || ''; }
      const q = (k) => card.querySelector('[data-add="' + k + '"]');
      if (q('date')) p.date = q('date').value || '';
      if (q('time')) p.time = q('time').value || '';
      if (q('move')) p.move = q('move').checked;
      if (q('cancel')) p.cancel = q('cancel').checked;
      if (q('cby')) p.by = q('cby').value;
      if (q('claim')) p.claim = q('claim').checked;
      if (q('ctype')) p.claimType = Number(q('ctype').value) || p.claimType;
      if (q('creason')) p.reason = q('creason').value || p.reason;          // причина и комментарий — всегда вместе
      if (q('tgtext')) { const v = q('tgtext').value.trim(); if (v !== p.tg) { p.tgAuto = false; p.tg = v; } }   // правка оператора не теряется при перерисовке
      if (q('tg')) p.tgOn = q('tg').checked;
      if (q('text')) p.crm = q('text').value.trim();
      if (q('crm')) p.crmOn = q('crm').checked;
      if (q('addr')) p.addrOn = q('addr').checked;
    };
    // карточка одна на всех: после «Сделать» рисуем итог, только если она всё ещё наша (её первый узел) и диалог тот же — иначе итог уведомлением
    let мойУзел = null;
    const draw = () => { card.replaceChildren(
      h('div', { class: 'hd' }, h('span', { class: 'ok-ic' }, svg('warn')),
        h('div', { class: 'tt' }, ЗАГОЛОВОК[intent] + (cr.id || '') + (intent === 'где_мастер' ? ')' : '')),
        h('button', { class: 'ib', 'aria-label': 'Не нужно', title: 'Не нужно', onclick: async () => { await markSeen(id, seen); card.classList.remove('show'); } }, svg('close'))),
      другое ? h('div', { class: 'row', style: 'justify-content:flex-end' }, другое) : '',
      summary ? h('div', { class: 'n mut' }, 'Клиент: «' + summary + '»') : '',
      intent === 'где_мастер' ? dlСтрок(визитСтроки(cr, tzД), { class: 'dl wrap', 'data-add': 'live' }) : '',
      p.note ? h('div', { class: 'n warn' }, p.note) : '',
      intent === 'перенос' && p.fromDate ? h('div', { class: 'n mut' }, 'Сейчас в CRM: ' + p.fromDate.replace(/-/g, '.') + (p.fromTime ? ' в ' + p.fromTime : '')) : '',
      intent === 'перенос' ? h('div', { class: 'g2' },
        h('label', { class: 'f' }, 'Новая дата', h('input', { type: 'date', 'data-add': 'date', value: p.date, oninput: обновитьПеренос, onchange: обновитьПеренос })),
        h('label', { class: 'f' }, 'Время', h('input', { type: 'time', 'data-add': 'time', value: p.time, 'data-tz': поясЗаявки, 'data-today': сегодняКлиента,
          'data-where': вГороде(LC_TERRITORY.чистыйГород((cr && cr.city) || '')) || undefined, oninput: обновитьПеренос, onchange: обновитьПеренос }))) : '',
      intent === 'перенос' && cr.prozvon ? h('div', { class: 'n warn', 'data-add': 'prozvon2', hidden: !прозвонДалеко(p.date) }, 'Заявка «на прозвоне»: перенос на 2-е сутки и дальше — штраф 200 ₽ (регламент)') : '',
      intent === 'перенос' && !p.time ? h('div', { class: 'box warn', 'data-add': 'notime' }, svg('warn'), h('div', { class: 'c' },
        h('div', {}, h('b', {}, 'Клиент не назвал новое время. '), 'Переносим только на согласованное время — спросите у клиента или поставьте сами.'),
        h('div', { class: 'row', style: 'gap:6px;flex-wrap:wrap' }, h('button', { class: 'sm', onclick: async (e) => {
          const b = e.currentTarget; b.disabled = true; b.textContent = 'Спрашиваем…';
          // один id на карточку: повтор после ошибки сети LeadChat узнает и второго сообщения клиенту не будет
          try { await LC.post('/conversations/' + encodeURIComponent(id) + '/messages', { text: 'Подскажите, пожалуйста, на какой день и время вам удобно перенести визит мастера?', client_message_id: idВопроса }); b.textContent = 'Спросили ✓'; }
          catch (er) { b.disabled = false; b.textContent = 'Не отправилось — ещё раз'; }
        } }, 'Спросить у клиента время')))) : '',
      intent === 'перенос' ? ck('move', p.move, 'Перенести в CRM (причина «Клиент»)') : '',
      intent === 'отмена' ? ck('cancel', p.cancel, 'Отменить в CRM') : '',
      intent === 'отмена' ? h('label', { class: 'f' }, 'Как отменить', h('select', { 'data-add': 'cby', onchange: (e) => { const n = card.querySelector('[data-add="kcnote"]'); if (n) n.hidden = e.target.value === 'branch'; } },
        h('option', { value: 'kc', selected: p.by !== 'branch' }, 'Отмена КЦ — отказался клиент'),
        h('option', { value: 'branch', selected: p.by === 'branch' }, 'Отмена Филиал — отказал филиал'))) : '',
      intent === 'отмена' ? h('div', { class: 'n mut' }, 'В служебный комментарий — «Отмена с Авито» (при любой отмене)') : '',
      // «Отмена КЦ» стоит денег (оплаченная заявка списывается обратно) — сначала предложить клиенту перенос
      intent === 'отмена' ? h('div', { class: 'n warn', 'data-add': 'kcnote', hidden: p.by === 'branch' }, '«Отмена КЦ» списывает 60 ₽ — может, перенос?') : '',
      intent === 'отмена' ? h('label', { class: 'f' }, 'Причина (в комментарий и комментарий партнёра)', h('select', { 'data-add': 'creason', onchange: (e) => { const t = card.querySelector('[data-add="text"]'); if (t) t.value = 'Отмена, ' + e.target.value; } },
        ...LC_TG.ПРИЧИНЫ_ОТМЕНЫ.map((x) => h('option', { value: x, selected: p.reason === x }, x)))) : '',
      intent === 'отдел_авито' ? h('label', { class: 'f' }, 'Кому передать (отдел Авито)', сотрудникиАвито(p)) : '',
      intent === 'претензия' && !p.again ? ck('claim', p.claim, 'Создать претензию в CRM') : '',
      intent === 'претензия' && !p.again ? h('label', { class: 'f' }, 'Тип претензии', h('select', { 'data-add': 'ctype' },
        ...LC_TG.ТИПЫ_ПРЕТЕНЗИЙ.map((t, i) => h('option', { value: String(i + 1), selected: p.claimType === i + 1 }, (i + 1) + ') ' + t)))) : '',
      p.tg ? h('label', { class: 'f' }, intent === 'претензия' ? 'В чат претензий' : 'В чат города', ta('tgtext', p.tg)) : '',
      intent === 'перенос' ? h('div', { class: 'n mut' }, 'После переноса в чат уйдёт строка из «Переносов» CRM: «№ Перенос с "…" на "…" Клиент»') : '',
      p.tg ? ck('tg', p.tgOn !== false, 'Отправить в Telegram') : '',
      p.crm ? h('label', { class: 'f' }, 'В комментарий CRM', ta('text', p.crm)) : '',
      p.crm && intent !== 'отмена' ? ck('crm', p.crmOn !== false, 'Дописать в комментарий заявки') : '',
      адресБлок(),
      state.guard ? перекрытиеBox(state.guard, () => { state.guard = null; go(); }, () => { state.guard = null; p.force = true; go(); }, 'Всё равно сделать') : '',
      state.done ? h('div', { class: 'box ' + (state.ok ? 'ok' : 'warn') }, svg(state.ok ? 'check' : 'warn'), h('div', { class: 'c' }, state.done)) : '',
      h('div', { class: 'row' },
        h('button', { class: 'go', disabled: state.busy, onclick: go }, state.busy ? 'Делаем…' : 'Сделать'),
        h('button', { class: 'sq', onclick: async () => { await markSeen(id, seen); card.classList.remove('show'); } }, 'Не нужно')),
      cr.id ? h('div', { class: 'n mut' }, 'Закроете — снова откроется кнопкой «№ ' + cr.id + '» в карточке клиента') : ''); мойУзел = card.firstChild; };
    const своя = () => card.firstChild === мойУзел && card.classList.contains('show') && convIdNow() === id;
    // оператор ушёл, пока делали (карточка уже про другой диалог или спрятана): итог — уведомлением, чужую карточку не трогаем
    const итогУведомлением = (text, ok) => тост({ kind: ok ? 'ok' : 'warn', label: 'По заявке № ' + (cr.id || ''), keep: !ok, conv: id, жить: ok ? УСПЕХ_МС : 0,   // 2.3: успех уходит сам
      title: ЗАГОЛОВОК[intent] + (cr.id || '') + (intent === 'где_мастер' ? ')' : '') + (имяКлиента(id) ? ' · ' + имяКлиента(id) : ''),
      lines: строкиИтога(text, ok),                                    // 11: не сделанное — первым
      actions: ok ? [] : [h('button', { class: 'sm', onclick: (e) => { const t = e.currentTarget.closest('.tst'); if (черновикМешает(id)) return; if (t) t.remove(); перейти(id); } }, 'Открыть диалог')] });
    async function go() {
      if (state.busy) return;
      read();
      if (intent === 'перенос' && p.move && !p.time && !p.date) { state.done = 'Поставьте новую дату и время (спросите у клиента) — без них не переносим, в чат ничего не уходит'; draw(); return; }
      state.busy = true; state.done = ''; draw();
      const res = await сделатьПоЗаявке(id, cr, p, { наВиду });
      if (res.guard) { state.busy = false; state.guard = res.guard; if (своя()) draw(); else итогУведомлением(res.text, false); return; }   // просьба филиала без ответа — ничего не делали
      p.force = false;
      await markSeen(id, seen);
      state.busy = false; state.ok = res.ok; state.done = res.text;
      if (!своя()) { итогУведомлением(res.text, res.ok); return; }
      draw();
      const узел = мойУзел;
      // успех закрывается сам — но не с предупреждением «⚠ …» и не пока карточку держат (мышь над ней, фокус внутри)
      const строкиИтога = (res.итог && res.итог.строки) || String(res.text || '').split(' · ');
      if (res.ok && !строкиИтога.some((t) => /^\s*⚠/.test(String(t || '')))) автоЗакрытьКарточку(() => card.firstChild === узел && card.classList.contains('show'), 5000);
    }
    draw();
    // Esc — закрыть (не во время «Делаем…»), пока на экране эта карточка; снова откроется кнопкой «№ заявки»
    card.onkeydown = (e) => { if (e.key === 'Escape' && card.firstChild === мойУзел && !state.busy) { e.preventDefault(); card.classList.remove('show'); } };
    card._доп = мояДоп; card._act = null;                             // 1.20: действия — карточка действия больше не на экране
    const мояАдрес = {}; card._addr = мояАдрес;                      // карточка одна: сверка прежней в новую не попадёт
    if (адрес.идёт) {
      адресПоЗаявке(id, cr, r.from).catch((e) => ({ error: String((e && e.message) || e).slice(0, 100) })).then((x) => {
        if (card._addr !== мояАдрес) return;
        адрес.идёт = false;
        // «Сделать» уже идёт (p в работе) или прошло успешно (карточка вот-вот закроется): галочку не подставляем — адрес без ведома
        // оператора не меняем, только говорим. После сбоя или подсказки — галочка: оператор увидит её до следующего «Сделать»
        адрес.x = x && !x.error && (state.busy || (!!state.done && state.ok)) ? { ...x, поздно: true } : x;
        if (адрес.x && !адрес.x.error && !адрес.x.поздно) {
          p.адрес = { addr: x.addr, line: x.line, tg: x.tg, house: x.house, hm: hmКлиента };
          p.addrOn = x.on;
        }
        const box = card.querySelector('[data-add="addrbox"]');
        if (box) box.replaceWith(адресБлок());
        if (p.адрес) адресВЧат();
      });
    }
    clearInterval(ЖИВОЙ_ТАЙМЕР);                                     // карточка одна — прежний таймер больше не её
    if (intent === 'где_мастер') {
      const моя = {}; card._live = моя;
      const t = setInterval(() => {
        const el = card.querySelector('[data-add="live"]');
        if (card._live !== моя || !el || !card.classList.contains('show')) return clearInterval(t);
        el.replaceWith(dlСтрок(визитСтроки(cr, tzД), { class: 'dl wrap', 'data-add': 'live' }));
      }, 30000);
      ЖИВОЙ_ТАЙМЕР = t;
    } else card._live = null;
    card.classList.toggle('top', !!inlineBtn);
    card.classList.add('show');
    return true;
  }

  async function watch() {
    const id = convIdNow();
    if (!id || собираю || задачаИдёт(id) || document.visibilityState !== 'visible' || panel.classList.contains('open')) return;
    const cr = (await store.get('created', {}))[id];
    if (cr) {                                                   // заявка уже есть — следим, не дописал ли клиент
      if (card.classList.contains('show') && card.querySelector('[data-ready-key]')) hideCard();   // карточка готовности — про «до заявки» (p11)
      await watchAdditions(id, cr); return;
    }
    if (W.conv !== id) { W.conv = id; W.lastId = ''; W.meta = null; W.dismissed = ''; W.retryAt = 0; W.at = 0; W.повторы = 0; }
    // каждые 20 с — только последнее сообщение (limit=1): обычно нового нет, и всю переписку читать незачем
    const last = последнееИз(await лента(id, 1));
    let lastId = last ? last.id : '';
    // нового нет — ждём; но не хватало данных / ждали / был сбой — через минуту проверяем снова (адрес мог появиться в карточке)
    const повтор = !!W.retryAt && Date.now() >= W.retryAt;
    // вернулся из другого диалога (обход спрятал карточку), нового сообщения нет — та же карточка снова на экране, без новой проверки
    const п = ПОКАЗАНО.get(id);
    // Обход прошёл в другом диалоге (W сброшен): показанное — лишь пока свежо (15 мин, как кэш «Входящих») и не подошёл срок
    // повторной проверки («клиент выбирает время» → Прозвон); иначе — проверка заново, как до p11
    const свежо = п && (W.lastId ? W.lastId === lastId && !повтор : Date.now() - п.at < 15 * 60e3 && !(п.retryAt && Date.now() >= п.retryAt));
    if (lastId && п && п.спрятано && п.lastId === lastId && свежо) {
      п.спрятано = false;
      if (!W.lastId) { W.retryAt = п.retryAt; W.повторы = п.повторы; }
      W.lastId = lastId;
      if (!card.classList.contains('show') && !(await создаётсяПоДиалогу(id)) && convIdNow() === id && !panel.classList.contains('open')) {
        показатьРезультат(id, п.res, lastId);
        п.узел = card.classList.contains('show') ? card.firstChild : null;
      }
      return;
    }
    if (!lastId || (lastId === W.lastId && !повтор)) return;
    if (Date.now() - W.at < 45000) return;                     // ИИ не чаще раза в 45 с — дойдём на следующем круге
    // новое сообщение (или пора перепроверить) — вся переписка одним запросом; она же — страница для разбора.
    // Не прочиталась — не молчим: причина на кнопке (ниже, как сбой разбора), через минуту — снова
    let page = null, ошибкаЛенты = null;
    try { page = await лента(id); } catch (e) { if (устарело(e)) throw e; ошибкаЛенты = e; }
    if (convIdNow() !== id) return;
    if (page) {
      const items = (page.items || []).slice().sort((x, y) => Date.parse(x.created_at) - Date.parse(y.created_at));
      // голосовое ещё расшифровывается: текст придёт к тому же сообщению — «можно создавать» не показываем, смотрим на следующем круге
      if (голосовыеДиалога(items, W.meta && W.meta.conv).wait) return;
      if (items.length) lastId = items[items.length - 1].id;   // пока читали, клиент дописал — разбор про это сообщение
    }
    W.at = Date.now();
    if (!W.meta) W.meta = { conv: await деталь(id) };
    if (convIdNow() !== id) return;
    // 12.10: своей записи нет, а у диалога в LeadChat № заявки — на кнопке «№ …», как после своего создания (проверка ниже скажет «уже есть»)
    { const лц = заявкаLC(W.meta.conv); if (лц && !BTN.done && !задачаИдёт(id)) btnState({ done: true, ready: false, id: лц.id }); }
    let res;
    // оператор ушёл в другой диалог или открыл форму — дальше шаги этой проверки не делаем (CRM, карта, регламент): следующий
    // диалог не ждёт, пока досчитается прежний
    const стоп = { get да() { return convIdNow() !== id || panel.classList.contains('open'); } };
    try {
      if (ошибкаЛенты) throw ошибкаЛенты;
      const d = await loadDialog(id, W.meta.conv, page);       // переписка уже есть — не просим второй раз
      res = await разобратьГотовность(d, { id, name: (W.meta.conv.client && W.meta.conv.client.name) || '', inbox: false },
        { безПоиска: W.exSkip === id, вДиалоге: true, стоп });
    } catch (e) {
      if (стоп.да) return;                                      // проверка отменена — устарела; вернёмся — проверим заново
      // LeadChat не отдал диалог или карточку — не молчим: причина на кнопке, через минуту проверим снова
      if (устарело(e)) throw e;
      res = { id, st: 'error', why: 'LeadChat: ' + String((e && e.message) || e).slice(0, 100) + ' — проверю ещё раз', retry: true, флаги: [] };
    }
    if (W.conv !== id) return;
    W.повторы = lastId === W.lastId ? W.повторы + 1 : 0;
    W.lastId = lastId;
    // сбой — через минуту; не хватало / ждали — 1, 2, 4 мин после сообщения; «клиент ещё выбирает время» — когда истечёт его срок
    // (через 15 мин — Прозвон)
    const через = res.st === 'error' ? 60e3 : /^(missing|wait)$/.test(res.st) && W.повторы < ПОВТОРОВ_БЕЗ_НОВОГО ? 60e3 * 2 ** W.повторы : 0;
    const сроки = [через, (res.A && res.ttl) || 0].filter((x) => x > 0);
    W.retryAt = сроки.length ? Date.now() + Math.min(...сроки) : 0;
    // p11: пока шла проверка, по диалогу начали создавать заявку (здесь — «Создать как есть» из уведомления, или в другой вкладке)
    // или уже создали — разбор «до заявки» не показываем, а показанную карточку готовности убираем
    if ((await создаётсяПоДиалогу(id)) || (await store.get('created', {}))[id]) {
      if (convIdNow() === id && card.classList.contains('show') && card.querySelector('[data-ready-key]')) hideCard();
      return;
    }
    if (convIdNow() === id && !panel.classList.contains('open') && !задачаИдёт(id)) {   // p11: по диалогу создаётся заявка — карточку не показываем
      показатьРезультат(id, res, lastId);
      // что показали (её первый узел): спрячет смена диалога — вернётся, покажем снова без новой проверки
      ПОКАЗАНО.delete(id);
      ПОКАЗАНО.set(id, { lastId, res, узел: card.classList.contains('show') ? card.firstChild : null, спрятано: false, at: Date.now(), retryAt: W.retryAt, повторы: W.повторы });
      if (ПОКАЗАНО.size > 30) ПОКАЗАНО.delete(ПОКАЗАНО.keys().next().value);
    }
  }
  /* ---------- наблюдение за согласованиями: ответы филиалов по всем диалогам ---------- */
  /* 9: одно уведомление на диалог: новые ответы дописываются (последние 3 цитаты и «+N»), счётчик, уведомление — самым новым.
     Только память вкладки */
  // уведомление ещё живо: на экране, в «Пропущено» или «Позже»; иначе — новая группа (и отпущенные элементы не держим)
  const тостЖив = (el) => !!el && (el.isConnected || ОТЛОЖЕНЫ.has(el) || ПРОПУЩЕНО.some((x) => x.el === el));
  const ответов = (n) => { const д = n % 100, е = n % 10; return д >= 11 && д <= 14 ? 'ответов' : е === 1 ? 'ответ' : е >= 2 && е <= 4 ? 'ответа' : 'ответов'; };
  function notifyReply(conv, rec, x) {
    for (const [k, v] of ОТВЕТЫ) if (!тостЖив(v.el)) ОТВЕТЫ.delete(k);
    const z = ОТВЕТЫ.get(conv) || { el: null, n: 0, q: [] };
    ОТВЕТЫ.set(conv, z);
    z.n++; z.q = z.q.concat(x).slice(-3);
    const уйти = () => { ОТВЕТЫ.delete(conv); if (z.el) z.el.remove(); };
    // филиал ответил — решать оператору: «Нужно действие», висит до решения («Открыть диалог» / «Позже»)
    const o = { kind: 'warn', label: 'Ответ по согласованию' + (z.n > 1 ? ' (' + z.n + ')' : ''),
      title: (rec.name ? rec.name.replace(/\s*\d{6,8}/g, '') : 'Клиент') + (rec.city ? ', ' + rec.city : ''),
      lines: [h('div', { class: 'tst-d' }, x.chatTitle || ''),
        z.n > z.q.length ? h('div', { class: 'tst-d' }, '+' + (z.n - z.q.length) + ' ' + ответов(z.n - z.q.length) + ' раньше') : '',
        ...z.q.map((y) => h('div', { class: 'tst-q' }, (y.from ? y.from + ': ' : '') + String(y.text || '').slice(0, 300)))],
      // 2.3: «Создать заявку» — диалог и его форма (ответ филиала — в «Филиале», курсор — на главную кнопку; заявку создаёт только она);
      // «Открыть диалог» — только переход. Переход внутри LeadChat, без перезагрузки страницы
      actions: [h('button', { class: 'sm pri', 'data-reply-create': '1', title: 'Открыть форму заявки этого диалога — ответ филиала уже в ней; создаёт «Создать» в форме', onclick: async () => {
          if (черновикМешает(conv)) return; уйти();
          if (convIdNow() !== conv) { if (!(await перейти(conv))) return; await collect(); }
          else if (panel.classList.contains('open') && S && S.id === conv && формаЭтого()) render2keep();
          else if (S && S.id === conv && формаЭтого()) { panel.classList.add('open'); render2keep(); }
          else await collect();
          const go = формаЭтого() && panel.querySelector('.pf .go');
          if (go && !go.disabled) go.focus({ preventScroll: true });
        } }, 'Создать заявку'),
        h('button', { class: 'sm', onclick: async () => { if (черновикМешает(conv)) return; уйти(); if (convIdNow() !== conv) await перейти(conv); } }, 'Открыть диалог')],
      conv };
    if (z.el) { обновитьТост(z.el, o); вСтопку(z.el); } else z.el = тост(o);
  }
  async function watchApprovals() {
    if (document.visibilityState !== 'visible') return;
    if (!(await ведущая())) return;                                     // ответы филиалов смотрит одна вкладка
    const all = await store.get('tgSent', {});
    const recs = Object.entries(all).filter(([, r]) => r && sentList(r).length && Date.now() - r.at < 8 * 3600e3).slice(-12);
    const upd = {};
    for (const [conv, rec] of recs) {
      const rep = await repliesFor(rec);
      if (rep.length > (rec.seen || 0)) {
        upd[conv] = rep.length;
        const мой = S && S.id === conv && panel.classList.contains('open');
        if (мой) { S.tgReplies = rep; if (формаЭтого()) render2keep(); }
        else for (const x of rep.slice(rec.seen || 0)) notifyReply(conv, rec, x);
      }
    }
    if (Object.keys(upd).length) {
      await tgSentUpdate((fresh) => { for (const [conv, n] of Object.entries(upd)) if (fresh[conv]) fresh[conv].seen = n; });
    }
  }
  /* ответ города на «№ где мс?» → клиенту в чат (регламент: «город пишет, что задержится — предупреждаем клиента»),
     опоздание 5–30 минут → в служебный «Мастер опаздывает на N минут» */
  const WHERE_TOASTS = new Map();
  let whereWatching = false;
  async function watchWhere() {
    if (document.visibilityState !== 'visible') return;
    if (!(await ведущая())) return;
    if (whereWatching) return;
    whereWatching = true;
    try {
    const created = await store.get('created', {});
    const list = Object.entries(created).filter(([, c]) => c && c.whereMsg && Date.now() - c.whereMsg.at < 4 * 3600e3).slice(-10);
    for (const [conv, c] of list) {
      const r = await send({ kind: 'lcz-tg', args: { action: 'replies', chat: c.whereMsg.chat, msg: c.whereMsg.msg } });
      if (!(r && r.ok && Array.isArray(r.replies))) continue;
      let last = null;
      await правитьCreated((all) => {
        const w = all[conv] && all[conv].whereMsg;
        if (!w || w.msg !== c.whereMsg.msg || w.chat !== c.whereMsg.chat) return false;
        const picked = LC_CITY_REPLY.select(r.replies, w);
        Object.assign(w, picked.cursor); last = picked.latest;
      });
      if (last) notifyWhere(conv, c, last);
    }
    } finally { whereWatching = false; }
  }
  function минутыОпоздания(text) {
    const t = String(text || '').toLowerCase();
    const m = t.match(/(\d{1,3})\s*(мин|м\b|минут)/) || t.match(/мин[а-яё]*\s*(?:на|через)?\s*(\d{1,3})/) || t.match(/через\s*(\d{1,3})/) || t.match(/(?:опаздыва|задерж)[а-яё]*\s*(?:на)?\s*(\d{1,3})/);
    if (m) return Number(m[1]);
    if (/полчаса/.test(t)) return 30;
    if (/час/.test(t) && !/\d/.test(t)) return 60;
    return 0;
  }
  function текстКлиенту(text) {
    return LC_CITY_REPLY.describe(text).reply;
  }
  function notifyWhere(conv, c, x) {
    const n = LC_CITY_REPLY.describe(x.text).lateMinutes;
    const previous = WHERE_TOASTS.get(conv);
    if (previous) previous.remove();
    const ta = h('textarea', { style: 'width:100%;min-height:52px;margin-top:4px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--t1);padding:6px 8px;font:12.5px/1.4 inherit' });
    ta.value = текстКлиенту(x.text);
    const итог = h('div', { class: 'tst-d' }, '');
    // повтор после ошибки — с тем же client_message_id (LeadChat вернёт уже отправленное); текст поправили — новый id
    let отправка = null;
    const el = тост({ kind: 'warn', позже: false, label: 'Ответ города: где мастер', title: '№ ' + c.whereMsg.crId + (c.whereMsg.title ? ' · ' + c.whereMsg.title : ''),
      lines: [h('div', { class: 'tst-q' }, (x.from ? x.from + ': ' : '') + String(x.text || '').slice(0, 300)), h('div', { class: 'tst-d' }, 'Клиенту в чат:'), ta, итог],
      // кнопку берём сразу: после await у события из shadow DOM target уже пустой (кнопка оставалась бы выключенной)
      actions: [h('button', { class: 'sm pri', onclick: async (e) => {
          const b = e.currentTarget;
          b.disabled = true;
          const text = ta.value.trim();
          if (!text) { b.disabled = false; итог.textContent = 'Ответ города не содержит подтверждённого обещания. Впишите проверенный текст.'; return; }
          if (!отправка || отправка.text !== text) отправка = { text, id: новыйId() };
          try { await LC.post('/conversations/' + encodeURIComponent(conv) + '/messages', { text, client_message_id: отправка.id }); итог.className = 'tst-d ok'; итог.textContent = '✓ Отправлено клиенту'; b.remove(); }
          catch (er) { b.disabled = false; итог.className = 'tst-d warn'; итог.textContent = 'Не отправилось: ' + человечно(er).text.slice(0, 120) + ' — нажмите ещё раз'; }
        } }, 'Отправить клиенту'),
        n >= 5 && n <= 30 ? h('button', { class: 'sm', title: 'Регламент: опоздание 5–30 минут — отметка в служебном комментарии', onclick: async (e) => {
          const b = e.currentTarget;
          b.disabled = true;
          const r = await send({ kind: 'lcz-crm', op: 'comments', args: { dir: c.whereMsg.dir, id: c.whereMsg.crId, change: { addService: 'Мастер опаздывает на ' + n + ' минут' } } });
          b.textContent = r && r.ok ? 'В служебном ✓' : 'Не записалось — ещё раз';
          if (!(r && r.ok)) b.disabled = false;
        } }, 'В служебный: «опаздывает на ' + n + ' мин»') : '',
        h('button', { class: 'sm', onclick: () => { if (черновикМешает(conv)) return; el.remove(); перейти(conv); } }, 'Открыть диалог')], conv });
    WHERE_TOASTS.set(conv, el);
    if (WHERE_TOASTS.size > 100) WHERE_TOASTS.delete(WHERE_TOASTS.keys().next().value);
  }
  /* регламент чатов: «если после вашего ответа клиент не отвечает 5 минут — помечаем диалог «Решён» и выходим» */
  // спрашиваем один раз на каждое «молчание» (помним и после F5), ✕ — этот список больше не показываем, «не напоминать» — выключено
  const МОЛЧИТ = { asked: new Map(), el: null, list: [], loaded: false };
  async function молчитНастройки() {
    if (!МОЛЧИТ.loaded) {
      МОЛЧИТ.loaded = true;
      const a = await store.get('silentAsked', {}).catch(() => ({}));
      for (const [k, v] of Object.entries(a || {})) МОЛЧИТ.asked.set(k, v);
    }
    const cfg = await store.get('silentCfg', {}).catch(() => ({})) || {};
    МОЛЧИТ.off = !!cfg.off;
    return cfg;
  }
  async function молчитЗапомнить() {
    const o = {}; for (const [k, v] of [...МОЛЧИТ.asked].slice(-300)) o[k] = v;
    await store.set('silentAsked', o).catch(() => {});
  }
  // мои диалоги как ответственного — один запрос в минуту (только ведущая вкладка): «клиент молчит» и судьба моих передач
  async function моиСтроки() {
    const me = await моёId();
    if (!me) return null;
    const at = Date.now();
    const page = await LC.get('/conversations?tab=mine&assignee_id=' + encodeURIComponent(me) + '&limit=100');
    return { me, at, items: ((page && page.items) || []).filter((r) => r && r.id), total: page && page.page && typeof page.page.total === 'number' ? page.page.total : null };
  }
  async function watchSilent() {
    if (document.visibilityState !== 'visible' || !alive()) return;
    if (!(await ведущая())) return;                                     // сторожит одна вкладка
    const cfg = await молчитНастройки();
    const выкл = !!(cfg.off || (cfg.until && Date.now() < cfg.until));
    // «молчит» выключен или на паузе, а передач на проверке нет — LeadChat не спрашиваем вовсе (как до 1.18)
    if (выкл && !Object.keys((await store.get('transferOffers', {}).catch(() => ({}))) || {}).length) return;
    const page = await моиСтроки();
    if (!page) return;
    await проверитьПередачи(page).catch(() => {});
    if (выкл) return;
    const now = Date.now(), sent = await store.get('tgSent', {});
    /* решаем по строке списка, без запроса сообщений: последним писал ОПЕРАТОР (не вопрос системы об адресе, не бот),
       клиент ответа не ждёт, диалог мой (не гостевой) и не предложен другому — гостю LeadChat закрыть не даст */
    const молчит = (r, добавить) => {
      const lm = r.last_message;
      // undelivered — наш ответ не дошёл до клиента (доставка провалилась): клиент не «молчит», а нас не слышал
      if (r.status === 'closed' || !lm || lm.direction !== 'out' || lm.sender_type !== 'operator' || r.waiting_since || r.undelivered === true) return '';
      if (!r.assignee || String(r.assignee.id) !== page.me || r.transfer) return '';
      const at = lm.created_at || r.last_message_at, t = Date.parse(at);
      if (!(now - t >= 5 * 60e3 && now - t <= 90 * 60e3)) return '';
      if (sent[r.id] && !sent[r.id].done && now - sent[r.id].at < 2 * 3600e3) return '';      // ждём ответ филиала — не закрываем
      if (добавить && S && S.id === r.id && panel.classList.contains('open')) return '';   // этот диалог сейчас открыт в панели
      return at;
    };
    const строки = new Map(page.items.map((r) => [r.id, r]));
    // клиент ответил, диалог закрыли или передали — из окна убираем (не видно в первой сотне — оставляем как было)
    МОЛЧИТ.list = МОЛЧИТ.list.filter((x) => (строки.has(x.id) ? !!молчит(строки.get(x.id)) : page.total !== null && page.items.length < page.total));
    let новых = 0;
    for (const r of page.items) {
      const since = молчит(r, true), ключ = r.last_message_at || since;
      if (!since || МОЛЧИТ.asked.get(r.id) === ключ) continue;
      МОЛЧИТ.asked.set(r.id, ключ);
      новых++;
      if (!МОЛЧИТ.list.some((x) => x.id === r.id)) МОЛЧИТ.list.push({ id: r.id, name: (r.client && r.client.name) || 'клиент', since });
    }
    if (новых) await молчитЗапомнить();
    // окно — только когда список изменился; если тот же — не трогаем (раньше всплывало каждую минуту)
    const ключ = МОЛЧИТ.list.map((x) => x.id).join(',');
    if (!МОЛЧИТ.list.length) { if (МОЛЧИТ.el) МОЛЧИТ.el.remove(); МОЛЧИТ.el = null; МОЛЧИТ.shown = ''; return; }
    // 7: закрыли × — этот же список больше не показываем; вытеснили — он в «Пропущено». Снова — только когда список сменился
    if (ключ !== МОЛЧИТ.shown) { МОЛЧИТ.shown = ключ; if (ключ !== МОЛЧИТ.скрыт) notifySilent(); }
  }
  /* ПЕРЕДАЧА — ЭТО ПРЕДЛОЖЕНИЕ: диалог остаётся моим, пока коллега не примет (через 15 минут оно сгорает).
     Предложенные из расширения передачи помним (видит любая вкладка) и сверяем со списком «Мои»:
     ушёл из списка — приняли; остался без предложения — отказали или сгорело: говорим оператору. */
  async function запомнитьПередачу(id, o) {
    try { const all = await store.get('transferOffers', {}); all[id] = { ...o, at: Date.now() }; await store.set('transferOffers', all); } catch (_e) { /* не критично */ }
  }
  async function проверитьПередачи(page) {
    const all = (await store.get('transferOffers', {})) || {};
    const ids = Object.keys(all);
    if (!ids.length) return;
    const полный = page.total === null || page.items.length >= page.total;
    let изменилось = false;
    for (const id of ids) {
      const o = all[id] || {}, r = page.items.find((x) => x.id === id), старое = Date.now() - (o.at || 0) > 40 * 60e3;
      if ((o.at || 0) >= page.at) continue;                             // предложили, пока список шёл, — он ещё не про это
      if (r && r.transfer && !старое) continue;                         // ещё ждёт принятия
      if (!r && !полный && !старое) continue;                           // не видно в первой сотне — подождём
      if (r && !r.transfer && !старое) тостПередача(id, o);             // остался у меня без предложения: отказали или сгорело
      delete all[id]; изменилось = true;
    }
    if (изменилось) await store.set('transferOffers', all);
  }
  function тостПередача(id, o) {
    const el = тост({ kind: 'warn', label: 'Передачу не приняли', title: (o.name || 'Клиент') + ' — диалог по-прежнему у вас',
      lines: [h('div', { class: 'tst-d' }, 'Передачу не принял' + (o.toName ? 'и: ' + o.toName : 'и') + ' — отказ или прошло 15 минут. Передайте другому или ответьте сами.')],
      actions: [h('button', { class: 'sm pri', onclick: () => { if (черновикМешает(id)) return; el.remove(); перейти(id); } }, 'Открыть диалог')], conv: id });
  }
  /* закрыть диалог в LeadChat. Уже закрыт (закрыл коллега, бот, другая вкладка) — 422 same_status «Диалог уже в этом статусе»:
     это успех (так и сам LeadChat с 12.10), а не «Не закрылся» */
  async function закрытьДиалог(id) {
    try { await LC.patch('/conversations/' + encodeURIComponent(id) + '/status', { status: 'closed' }); return { ok: true }; }
    catch (e) { if (e && e.status === 422 && e.details && e.details.reason === 'same_status') return { ok: true, already: true }; throw e; }
  }
  async function закрытьРешён(id) {
    await закрытьДиалог(id);
    МОЛЧИТ.list = МОЛЧИТ.list.filter((x) => x.id !== id);
    МОЛЧИТ.shown = МОЛЧИТ.list.map((x) => x.id).join(',');
  }
  function notifySilent() {
    if (МОЛЧИТ.el) МОЛЧИТ.el.remove();
    const мин = (t) => Math.round((Date.now() - Date.parse(t)) / 60e3);
    const одна = МОЛЧИТ.list.length === 1;
    // строка: имя · молчит N мин и «Решён»; не вышло — причина строкой под ней (не только во всплывающей подсказке)
    const rows = МОЛЧИТ.list.map((x) => {
      const ош = h('div', { class: 'tst-d warn', style: 'display:none' });
      return h('div', {}, h('div', { class: 'tst-d', style: 'display:flex;align-items:center;gap:8px;justify-content:space-between' },
        h('span', { style: 'min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap' }, h('b', { style: 'color:var(--t1);font-weight:500' }, x.name), ' · молчит ' + мин(x.since) + ' мин'),
        h('button', { class: 'sm' + (одна ? ' pri' : ''), style: 'height:28px', onclick: async (e) => { const b = e.currentTarget; b.disabled = true; ош.style.display = 'none';
          try { await закрытьРешён(x.id); b.textContent = 'Закрыт ✓'; }
          catch (er) { b.disabled = false; b.textContent = 'Решён'; ош.textContent = 'Не закрылся: ' + человечно(er).text.slice(0, 120); ош.style.display = ''; } } }, 'Решён')), ош);
    });
    const убрать = () => { МОЛЧИТ.list = []; МОЛЧИТ.shown = ''; if (МОЛЧИТ.el) МОЛЧИТ.el.remove(); МОЛЧИТ.el = null; };
    const итог = h('div', { class: 'tst-d warn', style: 'display:none' });
    МОЛЧИТ.el = тост({ kind: 'warn', low: true, label: 'Клиент молчит 5+ минут', title: 'Закрыть как «Решён»?',
      lines: rows.concat(итог), actions: [
        // «Закрыть все»: кто не закрылся — строкой, а не молча
        !одна ? h('button', { class: 'sm pri', onclick: async (e) => { const b = e.currentTarget; b.disabled = true; const не = [];
          for (const x of МОЛЧИТ.list.slice()) { try { await закрытьРешён(x.id); } catch (er) { не.push(x.name + ' (' + человечно(er).text.slice(0, 60) + ')'); } }
          if (!не.length) { if (МОЛЧИТ.el) МОЛЧИТ.el.remove(); МОЛЧИТ.el = null; return; }
          b.disabled = false; итог.textContent = 'Не закрылись: ' + не.join(', '); итог.style.display = ''; } }, 'Закрыть все (' + МОЛЧИТ.list.length + ')') : '',
      ],
      foot: [h('span', {}, 'Регламент: после вашего ответа клиент молчит 5 минут — диалог «Решён». Где ждём ответ филиала — не трогаем.'),
        h('button', { class: 'sm ghost', title: 'Больше не предлагать закрывать молчащие диалоги. Включить снова — в «Готовых» → «Настроить»', onclick: async () => { убрать(); МОЛЧИТ.off = true; await store.set('silentCfg', { off: true }).catch(() => {}); } }, 'не напоминать')] });
    const x = МОЛЧИТ.el.querySelector('.x');
    if (x) x.addEventListener('click', () => { МОЛЧИТ.скрыт = МОЛЧИТ.list.map((y) => y.id).join(','); });
  }
  let silentBusy = false;
  setInterval(() => { if (silentBusy || !alive()) return; silentBusy = true; watchSilent().catch(() => {}).finally(() => { silentBusy = false; }); }, 60000);
  let approvalsBusy = false;
  setInterval(() => {
    if (approvalsBusy || !alive()) return;
    approvalsBusy = true;
    watchApprovals().then(() => watchWhere()).catch(() => {}).finally(() => { approvalsBusy = false; });
  }, 45000);

  let watching = false;
  setInterval(() => { if (alive() && S && S.tgSent && panel.classList.contains('open')) pollReplies().catch(() => {}); }, 15000);
  setInterval(() => {
    if (watching || !alive()) return;
    watching = true;
    watch().catch(() => {}).finally(() => { watching = false; });
  }, 20000);

  // список источников из настроек (⚙ → «Источники») важнее встроенного
  // 13.10: только если он сохранён не раньше даты встроенного списка — иначе старые ссылки перебивали бы новые
  Promise.all([store.get('sourcesText', ''), store.get('sourcesSavedAt', '')])
    .then(([t, когда]) => { if (t && LC_LINKS.свежийСписок(когда)) LC_LINKS.use(t, 'список из настроек'); }).catch(() => {});
  // 2.1.1: база за каналом больше не запоминается — прежние привязки («канал → база» до 2.1.1) стираем, чтобы не решали за смысл
  try { if (alive() && chrome.storage.local.remove) Promise.resolve(chrome.storage.local.remove('accountDir')).catch(() => {}); } catch (_e) { /* нет — и не надо */ }

  /* ---------- кнопка «Заявка» в карточке «Клиент» LeadChat (справа от заголовка) ----------
     LeadChat перерисовывает карточку — кнопку возвращаем на место (наблюдатель за страницей + запасной обход раз в 800 мс).
     Карточки нет (рабочая область уже 1360 px — LeadChat её прячет) — кнопка в шапке переписки, перед «Клиент»;
     нет и шапки — плавающая кнопка. Состояния: обычная / «Можно создавать» / «✓ № заявки». */
  let inlineHost = null, inlineBtn = null;
  // creating — по ЭТОМУ (открытому) диалогу сейчас создаётся заявка: ставит только тот, кто знает, что диалог открыт
  const BTN = { done: false, ready: false, id: null, creating: false };
  function btnState(ch) {
    Object.assign(BTN, ch);
    for (const b of [fab, inlineBtn]) {
      if (!b) continue;
      b.classList.toggle('busy', BTN.creating);
      b.classList.toggle('done', BTN.done && !BTN.creating);
      b.classList.toggle('ready', BTN.ready && !BTN.done && !BTN.creating);
      b.replaceChildren(...(BTN.creating ? [h('span', { class: 'dot' }), 'Создаётся…'] : BTN.done ? [svg('check'), BTN.id ? '№ ' + BTN.id : 'Заявка создана']
        : BTN.ready ? [h('span', { class: 'dot' }), 'Можно создавать'] : [svg('clip'), 'Заявка']));
      b.setAttribute('aria-label', BTN.creating ? 'Заявка создаётся' : BTN.done ? 'Заявка создана' : 'Собрать заявку из этого диалога');
    }
  }
  /* Якоря в разметке LeadChat: сначала классы (как были), потом запасные — по подписям для экранного диктора, они меняются
     реже классов (ClientCardPane.tsx: <aside aria-label="Карточка клиента"> → <section> с <h3>Клиент</h3>; ChatThreadPane.tsx:
     <section aria-label="Переписка"> → <header>, кнопка <button aria-label="Карточка клиента" aria-pressed> — открыта ли карточка
     поверх ленты на узком месте) */
  function заголовокКлиента() {
    const t = document.querySelector('section.card-section--client .card-section__title');
    if (t) return t;
    const aside = document.querySelector('aside[aria-label="Карточка клиента"]');
    if (!aside) return null;
    // «Клиент» — первый блок карточки; пустая карточка («Выберите диалог», «Карточка недоступна») — без заголовка, мимо
    for (const sec of [...aside.querySelectorAll('section.card-section'), ...aside.querySelectorAll('section')]) {
      const h3 = sec.querySelector(':scope > h3');
      if (h3 && h3.textContent.trim() === 'Клиент') return h3;
    }
    return null;
  }
  const шапкаПереписки = () => document.querySelector('section.chat-thread-pane > header.thread-header') || document.querySelector('section[aria-label="Переписка"] > header');
  const кнопкаКарточки = (head) => [...head.children].find((el) => el.classList.contains('thread-header__card-toggle'))
    || [...head.children].find((el) => el.matches('button[aria-label="Карточка клиента"]')) || null;
  // карточку открыли / закрыли кнопкой «Клиент» (aria-pressed) — кнопку «Заявка» переставить сразу, а не обходом
  let карточкаНажата = null;
  const нажатаКарточка = () => { const h = шапкаПереписки(), b = h && кнопкаКарточки(h); return b ? b.getAttribute('aria-pressed') : null; };
  function местоКнопки() {
    карточкаНажата = нажатаКарточка();
    const title = заголовокКлиента();
    if (title) return { box: title, before: null, css: 'margin-left:auto' };
    const head = шапкаПереписки();
    if (head) return { box: head, before: кнопкаКарточки(head), css: 'margin-left:6px;flex:none;align-self:center' };
    return null;
  }
  function placeInline() {
    const m = местоКнопки();
    if (!m) { inlineBtn = null; return false; }
    if (inlineHost && inlineHost.isConnected && inlineHost.parentNode === m.box) {
      // LeadChat перерисовал шапку («Загрузка…» → данные диалога): его узлы встали после нашей кнопки — ставим её снова перед «Клиент»
      if (m.before && inlineHost.nextElementSibling !== m.before) m.box.insertBefore(inlineHost, m.before);
      if (!inlineBtn) { inlineBtn = inlineHost.shadowRoot.querySelector('button'); btnState({}); }   // блок вернули тем же узлом
      return true;
    }
    if (inlineHost) inlineHost.remove();                              // кнопка была в другом месте (карточку открыли или спрятали) — одна, не две
    inlineHost = document.createElement('span');
    inlineHost.setAttribute('data-lcz', 'btn');
    inlineHost.style.cssText = m.css + ';display:inline-flex;letter-spacing:0;text-transform:none';
    const sr = inlineHost.attachShadow({ mode: 'open' });
    sr.innerHTML = `<style>${CSS}</style><span class="lcz" style="display:inline-flex;gap:6px"><button class="pill" title="Собрать заявку из этого диалога"></button>`
      + `<button class="pill pact" data-lcz-act="1" title="Действия по заявке этого клиента: перенос, отмена, галочки, претензия…">${I.list.replace(/width="18" height="18"/, 'width="14" height="14"')}Действия</button></span>`;
    inlineBtn = sr.querySelector('button');
    inlineBtn.addEventListener('click', onBtnClick);
    sr.querySelector('[data-lcz-act]').addEventListener('click', onActClick);
    m.box.insertBefore(inlineHost, m.before);
    btnState({});
    return true;
  }
  /* 2.0.4: «Действия» — все действия по заявке этого диалога одной кнопкой: связанная заявка (создана / связана здесь) — сразу её
     действия; нет — заявки клиента по номеру во всех базах; ничего — ввод № заявки и базы. Записей нет: только чтение CRM */
  async function onActClick(e) {
    const b = e && e.currentTarget, id = convIdNow();
    if (!id || (b && b.disabled)) return;
    if (!(ACT && ACT.готов())) { тост({ kind: 'bad', label: 'Действия', title: 'Действия по заявке недоступны', lines: [h('div', { class: 'tst-d' }, 'Каталог действий не загрузился — обновите страницу')],
      actions: [h('button', { class: 'sm pri', onclick: () => location.reload() }, 'Обновить страницу')] }); return; }
    const было = b ? b.innerHTML : '';
    if (b) { b.disabled = true; b.textContent = 'Ищу заявку…'; }
    try {
      const cr = ((await store.get('created', {})) || {})[id];
      let ex = { found: [], unchecked: [] };
      if (cr && cr.id && cr.dir) ex.found = [{ id: String(cr.id), dir: cr.dir, status: cr.status || '', open: true, url: cr.url || '', city: cr.city || '', visit: cr.visit || '', visitTime: cr.visitTime || '' }];
      else {
        const d = await loadDialog(id);
        const номер = LC_EXTRACT.номерДляПоиска(ctxOf(d));
        const p10 = String(номер.phone || '').replace(/\D/g, '').slice(-10);
        if (p10.length === 10) {
          const x = await спросить({ kind: 'lcz-crm', op: 'existing', args: { phone: p10 } }, 60000, 'CRM');
          if (x && x.ok) ex = { found: x.found || [], unchecked: x.unchecked || [] };
          else ex.unchecked = [{ dir: '', error: String((x && x.error) || 'CRM не ответила').slice(0, 80) }];
        }
      }
      if (convIdNow() !== id) return;                                   // пока искали, оператор ушёл в другой диалог
      // 2.2.3: № заявки стоит у диалога в LeadChat — она первой (действия по ней чаще всего)
      const лц = !(cr && cr.dir) && заявкаLC((W.meta && W.conv === id && W.meta.conv) || МГН.строки.get(id));
      if (лц) ex.found = [...ex.found.filter((r) => String(r.id) === String(лц.id)), ...ex.found.filter((r) => String(r.id) !== String(лц.id))];
      showExistingCard(id, ex, '', null, 'действия');
    } catch (err) {
      // поиск сорвался (LeadChat / CRM): понятная фраза, техника — под «Подробнее», следующий шаг — «Повторить»
      const ч = человечно(err);
      const el = тост({ kind: 'bad', label: 'Действия', title: 'Не получилось найти заявку', lines: [h('div', { class: 'tst-d' }, String(ч.text).slice(0, 160))], подробно: ч.тех || '',
        actions: [b ? h('button', { class: 'sm pri', onclick: () => { el.remove(); if (b.isConnected) b.click(); } }, 'Повторить') : ''] });
    } finally { if (b) { b.disabled = false; b.innerHTML = было; } }
  }
  function onBtnClick() {
    const id = convIdNow();
    // открыта панель этого диалога (форма, ход создания или его итог) — кнопка её закрывает
    if (panel.classList.contains('open') && (формаЭтого() || (panel.dataset.conv === id && panel.querySelector('[data-job], [data-done]')))) { closePanel(); return; }
    collect(разборКарточки(id));
  }
  // карточка «Можно создавать» уже разобрала диалог (ИИ, CRM, карта, регламент) — форма по этому разбору, а не платный разбор заново.
  // Только пока последнее сообщение то же; collect() ещё раз сверит его с LeadChat
  function разборКарточки(id) {
    const п = ПОКАЗАНО.get(id), A = п && п.res && п.res.A;
    if (!A || A.id !== id || !A.lastId || п.lastId !== A.lastId) return undefined;
    return W.conv === id && W.lastId && W.lastId !== A.lastId ? undefined : A;
  }

  let lastConv = '';
  /* кнопка «✓ Готовые» — в панели фильтров списка диалогов, сразу после «Входящие» (своя вкладка в стиле LeadChat) */
  let readyHost = null;
  function placeReadyTab() {
    // вкладки списка: класс LeadChat, запасной — подпись (ChatListPane.tsx: role="tablist" aria-label="Фильтры диалогов")
    const tabs = document.querySelector('.chat-tabs') || document.querySelector('[role="tablist"][aria-label="Фильтры диалогов"]');
    if (!tabs || !tabs.parentElement) return false;
    if (readyHost && readyHost.isConnected && readyHost.previousElementSibling === tabs) { drawReadyTab(); return true; }
    if (readyHost) readyHost.remove();
    readyHost = document.createElement('span');
    readyHost.setAttribute('data-lcz', 'ready');
    readyHost.style.cssText = 'display:inline-flex;align-items:center;margin-left:6px;flex:none';
    const sr = readyHost.attachShadow({ mode: 'open' });
    sr.innerHTML = `<style>
      button{all:unset;box-sizing:border-box;cursor:pointer;display:inline-flex;align-items:center;gap:6px;height:28px;padding:0 10px;border-radius:8px;
        font:600 12.5px/1 var(--lc-font,Inter,-apple-system,"Segoe UI",sans-serif);color:var(--lc-text-2,#c7d2c9);
        background:var(--lc-bg-raise,#1a221e);border:1px solid var(--lc-border,#2a332e);white-space:nowrap}
      button:hover{color:var(--lc-text-1,#e7ede9);border-color:var(--lc-theme-accent,var(--lc-primary,#3cc13b))}
      button.auto{border-color:var(--lc-theme-accent,var(--lc-primary,#3cc13b));color:var(--lc-success-text,#7ed77c)}
      .n{min-width:18px;height:18px;padding:0 5px;border-radius:999px;display:inline-flex;align-items:center;justify-content:center;
        background:var(--lc-theme-accent,var(--lc-primary,#3cc13b));color:var(--lc-theme-accent-contrast,var(--lc-on-primary,#04160a));font-size:11px}
      .d{width:7px;height:7px;border-radius:999px;background:currentColor}
      button.new{border-color:var(--lc-theme-accent,var(--lc-primary,#3cc13b));color:var(--lc-text-1,#e7ede9);box-shadow:0 0 0 3px color-mix(in srgb,var(--lc-theme-accent,var(--lc-primary,#3cc13b)) 25%,transparent)}
    </style><button type="button" title="Готовые к созданию во «Входящих» и автоприём"></button>`;
    sr.querySelector('button').addEventListener('click', () => { if (panel.classList.contains('open') && READY.at && !S) { closePanel(); return; } showReady(); });
    tabs.insertAdjacentElement('afterend', readyHost);
    drawReadyTab();
    return true;
  }
  /* 8: режим ИИ — один раз: чип в шапке «Готовых» и на кнопке (а не в каждой строке). Свежее из двух: ответ мозга в этой вкладке
     или brainState фона (читаем при открытии «Готовых»). Заливка чипа — --lc-*-subtle LeadChat (lc-vars.css, у светлой темы свои);
     --lc-*-bg LeadChat не объявляет — с ними светлая тема получала тёмную запасную заливку */
  const РЕЖИМ = { m: '', at: 0 };
  const режимСейчас = () => (МОЗГ_ЭКРАН.режимAt >= РЕЖИМ.at ? МОЗГ_ЭКРАН.режим : РЕЖИМ.m) || '';
  const ЧИП = { economy: ['ИИ эконом', 'ИИ в экономном режиме: регламент сверяется при открытии формы'], rules: ['ИИ выкл.', 'ИИ выключен до 1-го числа: разбор по правилам, регламент — в форме'] };
  const чипРежима = (m) => (ЧИП[m] ? h('span', { class: 'chip' + (m === 'rules' ? ' bad' : ''), title: ЧИП[m][1] }, ЧИП[m][0]) : '');
  const назад = (t) => { const м = Math.floor((Date.now() - t) / 60e3); return м < 1 ? 'только что' : м + ' мин назад'; };
  function drawReadyTab() {
    const b = readyHost && readyHost.shadowRoot && readyHost.shadowRoot.querySelector('button');
    if (!b) return;
    const n = READY.items.filter((x) => x.st === 'ready' || x.st === 'almost' || x.st === 'follow' || x.st === 'transfer').length;
    const m = режимСейчас(), нов = новыхНеВидели();
    const key = [AUTO.on, n, m, нов].join('|');
    if (b.dataset.k === key) return;
    b.dataset.k = key;
    b.classList.toggle('auto', AUTO.on);
    b.classList.toggle('new', нов > 0);
    b.title = 'Готовые к созданию во «Входящих» и автоприём' + (нов ? ' — новых: ' + нов : '');
    b.innerHTML = (AUTO.on ? '<span class="d"></span>' : '✓') + ' Готовые' + (AUTO.on ? ' · авто' : '') + (n ? ' <span class="n"' + (нов ? ' data-new="' + нов + '"' : '') + '>' + n + '</span>' : '')
      + (ЧИП[m] ? ' <span title="' + ЧИП[m][1] + '" style="font-weight:500;font-size:11px;padding:2px 6px;border-radius:999px;'
        + (m === 'rules' ? 'background:var(--lc-danger-subtle,rgba(220,60,60,.15));color:var(--lc-danger-text,#e26d6d)' : 'background:var(--lc-warning-subtle,rgba(230,170,40,.15));color:var(--lc-warning-text,#e0b04a)')
        + '">' + (m === 'rules' ? 'ИИ выкл.' : 'эконом') + '</span>' : '');
  }

  /* ---------- 1.20: действия — хост для экрана действий (actions-ui.js) и подсказок (watch-act.js) ----------
     Модули берут отсюда всё, что им нужно от LeadChat, панели и Telegram, и не трогают внутренности content.js */
  const ХОСТ = { h, svg, send, LC, store, card, panel, тост, перекрытиеBox, просьбыВЧате, отправитьСПроверкой, чатПоЗаявке, nameWithId, номерВДиалог, convIdNow, markSeen, правитьCreated, tgSentGet, sentList,
    новыйId, ведущая, поясДиалога, визитСейчас, dirName, closePanel, alertBox, сТаймаутом, поОдному, перейти, черновикМешает, fmtPhone, alive, устарело, УСТАРЕЛО,
    ПОЯС: (conv) => ПОЯС_ДИАЛОГА.get(conv) || '',
    показатьКарточку: () => { card.classList.toggle('top', !!inlineBtn); card.classList.add('show'); },
  };
  // уведомлениям подсказок (watch-act.js): имя клиента из памяти вкладки, обновить уведомление на месте, поставить его самым новым
  Object.assign(ХОСТ, { имяКлиента, обновитьТост, вСтопку, вГороде });
  try { if (typeof LC_ACT_UI !== 'undefined') ACT = LC_ACT_UI.создать(ХОСТ); } catch (_e) { ACT = null; /* модуль не поднялся — работаем как в 1.19 */ }
  // для проверок в node (как разбор готовности выше): экран действий и точки встраивания — тесту, который заранее положил __lczTest
  if (window.__lczTest && typeof window.__lczTest === 'object') Object.assign(window.__lczTest, { ACT, ХОСТ, markSeen, правитьCreated, проверитьКэш, showAdditionCard, notifyFollow, showExistingCard, showCreated, сделатьПоЗаявке, showJournal });
  /* подсказки по заявкам (watch-act.js): только ведущая видимая вкладка. Модуль создаём один раз — когда вкладка впервые стала ведущей;
     ведущая может смениться, поэтому модуль сам спрашивает хост.ведущая() перед каждым опросом CRM */
  let ПОДСКАЗКИ = null, подсказкиЖдём = false;
  async function запуститьПодсказки() {
    // подсказкиЖдём: ведущая() может думать до 3 с — второй круг не создаст второй модуль (двойные опросы CRM и тосты)
    if (ПОДСКАЗКИ || подсказкиЖдём || !ACT || typeof LC_ACT_WATCH === 'undefined' || !alive() || document.visibilityState !== 'visible') return;
    подсказкиЖдём = true;
    try { if (await ведущая() && !ПОДСКАЗКИ) ПОДСКАЗКИ = LC_ACT_WATCH.создать(ХОСТ, ACT) || {}; } catch (_e) { /* попробуем на следующем круге */ } finally { подсказкиЖдём = false; }
  }
  if (ACT && typeof LC_ACT_WATCH !== 'undefined') {
    setTimeout(() => { запуститьПодсказки().catch(() => {}); }, 2000);
    setInterval(() => { запуститьПодсказки().catch(() => {}); }, 31000);
  }

  let tickAt = 0, tickT = 0, нетМеста = false, смена = null;
  async function tick() {
    if(личнаяВкладка)return;
    tickAt = Date.now();
    if (наВходе() && (LC.token || LC.me)) новыйВход();                // вышли из LeadChat — прежний доступ и «кто я» забываем сразу
    const id = convIdNow();
    const rb = placeReadyTab() ? 'none' : '';
    if (readyBtn.style.display !== rb) readyBtn.style.display = rb;    // пишем в стиль, только если поменялось
    const inl = !!id && placeInline();
    нетМеста = !!id && !inl;
    const fd = id && !inl ? 'inline-flex' : 'none';
    if (fab.style.display !== fd) fab.style.display = fd;
    // поле с фокусом пропало при перерисовке или спрятано вместе с панелью / карточкой — снять пометку, клавиши снова у LeadChat
    if (host.hasAttribute('role') && (!root.activeElement || root.activeElement.closest('.panel:not(.open), .card:not(.show)'))) слойLeadChat(false);
    if (id !== lastConv) {
      lastConv = id;
      // смену диалога ждёт и перейти(): иначе этот обход, начатый раньше, закрыл бы форму, открытую уже для нового диалога
      const p = смена = (async () => {
        if (S && S.id && S.id !== id) await запомнитьДиалог();
        closePanel();
        panel.replaceChildren(); delete panel.dataset.conv;              // поля прежнего диалога в DOM не оставляем
        // карточку готовности прячет смена диалога, а не оператор — вернётся в тот диалог, покажем её снова
        if (card.classList.contains('show')) for (const x of ПОКАЗАНО.values()) if (x.узел && card.firstChild === x.узел) x.спрятано = true;
        hideCard();
        if (id && ПОКАЗАНО.has(id) && ПОКАЗАНО.get(id).спрятано) watchСкоро(500);
        S = null;
        const created = id ? (await store.get('created', {}))[id] : null;
        btnState({ done: !!created, ready: false, id: created ? created.id : null, creating: !!идётДоCRM(id) });   // 2.1: в CRM уже есть — «№ …»
      })();
      try { await p; } finally { if (смена === p) смена = null; }
    }
    if (ЗАДАЧИ.size) задачиНаВиду();                                   // ушёл / вернулся — уведомление о ходе создания
  }
  fab.addEventListener('click', onBtnClick);
  const tickSafe = () => { if (!alive()) return; try { Promise.resolve(tick()).catch(() => {}); } catch (_e) { /* вкладка устарела */ } };
  /* Наблюдатель: LeadChat перерисовал карточку или шапку, сменил диалог — кнопку на место сразу, а не через 800 мс.
     Работает, только когда нашей кнопки нет на месте, сменился диалог или карточку открыли / закрыли кнопкой «Клиент»
     (не чаще 4 раз в секунду, без места — раз в секунду); обход раз в 800 мс — запасной: адрес страницы LeadChat меняет без событий,
     видимых расширению. Со «слухом» (rt-main.js подменил history — rt:route) смену адреса узнаём сразу, обход — раз в ~2 с. */
  let маршрутБыл = location.pathname;
  const неНаМесте = () => convIdNow() !== lastConv || !(readyHost && readyHost.isConnected) || (!!convIdNow() && !(inlineHost && inlineHost.isConnected))
    || (!!convIdNow() && нажатаКарточка() !== карточкаНажата);
  try {
    new MutationObserver(() => {
      if (tickT || !alive() || !неНаМесте()) return;
      tickT = setTimeout(() => { tickT = 0; tickSafe(); }, Math.max(30, (нетМеста ? 1000 : 250) - (Date.now() - tickAt)));
    }).observe(document.body || document.documentElement, { childList: true, subtree: true });
  } catch (_e) { /* без наблюдателя — обход раз в 800 мс */ }
  setInterval(() => { if (RTX && RTX.маршрут && Date.now() - tickAt < 1900) return; tickSafe(); }, 800);
  tickSafe();
  /* 12: вкладка LeadChat скрыта — «✓N · » в заголовке: напоминания «пора» (только хранилище actWatch, CRM не читаем) и важные уведомления
     в стопке; раз в минуту. Вкладку открыли — убираем. Знак свой, не «(N)»: LeadChat сам пишет в начало заголовка «(N)» — непрочитанные
     и «[N]» — очередь (badges.ts formatDocumentTitle); снимаем только то, что поставили сами, — его числа не трогаем */
  const ЗАГОЛОВОК_ВКЛ = { преф: '' };
  async function заголовокВкладки() {
    const убрать = () => { if (ЗАГОЛОВОК_ВКЛ.преф && document.title.startsWith(ЗАГОЛОВОК_ВКЛ.преф)) document.title = document.title.slice(ЗАГОЛОВОК_ВКЛ.преф.length); ЗАГОЛОВОК_ВКЛ.преф = ''; };
    if (document.visibilityState === 'visible' || !alive()) { убрать(); return; }
    let n = toasts.querySelectorAll(':scope > .tst-keep, :scope > .tst-due').length;
    try { if (typeof LC_ACT_WATCH !== 'undefined' && LC_ACT_WATCH.пора) n += LC_ACT_WATCH.пора(await store.get('actWatch', null), Date.now(), визитСейчас); } catch (_e) { /* хранилище недоступно — только стопка */ }
    if (document.visibilityState === 'visible') { убрать(); return; }
    const преф = n ? '✓' + n + ' · ' : '';
    if (преф === ЗАГОЛОВОК_ВКЛ.преф && document.title.startsWith(преф)) return;
    убрать();
    if (преф) { document.title = преф + document.title; ЗАГОЛОВОК_ВКЛ.преф = преф; }
  }
  setInterval(() => { заголовокВкладки().catch(() => {}); }, 60000);
  document.addEventListener('visibilitychange', () => { заголовокВкладки().catch(() => {}); });
  // «слух»: подписываемся последними (накопленное отдаётся сразу, а обработчики трогают watching и МОЛЧИТ) и после настроек —
  // иначе первые события решали бы без «Автоприёма» и «Проверять новые сразу»
  if (!личнаяВкладка && RTX && RTX.on) Promise.all([мгнНастройка, автоНастройка]).then(() => RTX.on((e) => { try { наСобытиеLC(e); } catch (_e) { /* событие пропустим — сверка догонит */ } }));
  chrome.runtime.onMessage.addListener((msg,from,reply)=>{
    if(msg?.kind!=='lcz-personal-check')return;
    const guard=msg.guard;
    const valid=()=>личнаяВкладка&&from?.id===chrome.runtime.id&&assistantPanel?.personal?.state.active&&assistantPanel.canSubmit(guard?.generation);
    (async()=>{
      if(!valid())throw Error('Личная цепочка остановлена');
      const me=await assistantPanel.personal.identity();
      if(String(me.id)!==guard.operator_id)throw Error('Автор изменился');
      const ctx=await assistantContext(guard.conv_id),mine=await personalQueue({countOnly:true});
      if(assistantPanel.personal.state.delegated){
        const job=await assistantNative.runnable(guard.conv_id,ctx);
        if(!job||job.version!==guard.native_job_version)throw Error('Диалог забран вручную или передан заново');
      }
      const r=await assistantPanel.personal.call('personal_check_started',{ctx,revision:guard.revision,mine_count:mine.mineCount});
      if(!valid()||!r?.execution_allowed)throw Error(r?.error||'Разрешение истекло');
      return {ok:true};
    })().then(reply).catch(e=>reply({ok:false,error:String(e.message||e)}));return true;
  });
  // Native office belongs to an ordinary authenticated LeadChat document.
  // The dedicated observer can close without owning this executor or Run.
  const nativeOfficeClient=!личнаяВкладка&&nativeTransport&&typeof LC_NATIVE_OFFICE!=='undefined'
    ?LC_NATIVE_OFFICE.create({
      origin:location.origin,api:nativeTransport,identity:personalIdentity,
      host:(action,scope,fields)=>chrome.runtime.sendMessage({
        kind:'lcz-native-office-host',action,scope,...(fields?{fields}:{}),
      }),
      load:async key=>(await chrome.storage.local.get(key))[key],
      save:(key,value)=>chrome.storage.local.set({[key]:value}),
      prepare:async(envelope,scope)=>{
        const dialog=await personalDialog(scope.cid);
        return workflowPrepare({ctx:{convId:scope.cid,channel:dialog.conv.channel},
          operatorId:scope.operator_id},{revision:envelope.form.revision},envelope.form);
      },
      execute:async(fields,ticket)=>{
        const value=await отправитьСоздание({...fields,nativeOffice:ticket});
        if(value?.сбой)throw Object.assign(Error('Результат исходной отправки CRM не подтверждён'),
          {code:'native_crm_unknown'});
        return value?.r;
      },
      onActive:async()=>{
        if(!AUTO.on)return;
        AUTO.on=false;AUTO.gen++;
        await store.set('autoClaim',{on:false,max:AUTO.max,almost:AUTO.almost,followOn:AUTO.follow});
        rbLabel();
      },
    }):null;
  chrome.runtime.onMessage.addListener((msg,from,reply)=>{
    if(!['lcz-native-office-wake','lcz-native-office-phase'].includes(msg?.kind))return;
    if(from?.id!==chrome.runtime.id||from.tab||!nativeOfficeClient){
      reply({ok:false,active:false});return;
    }
    const request=msg.kind==='lcz-native-office-wake'
      ?nativeOfficeClient.wake():nativeOfficeClient.phase(msg);
    request.then(reply,()=>reply({ok:false,active:false}));return true;
  });
  if(nativeOfficeClient)nativeOfficeClient.wake().catch(()=>{});
  if(личнаяВкладка)openAssistant().catch(()=>{document.documentElement.classList.remove('lcz-personal-page')});
})();
