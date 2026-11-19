/* LeadChat → Заявка: «слух» на сокет самой страницы LeadChat. Мир страницы (world: MAIN), document_start.
   Вставить скрипт в страницу иначе нельзя: CSP LeadChat пускает только свой встроенный скрипт по хешу.
   ТОЛЬКО СЛУШАЕТ входящие кадры сокета LeadChat (/api/v1/ws): ничего не отправляет, не подписывается,
   своих сокетов не открывает — человек не становится «в сети» дважды и «зрителем» диалога.
   Исходящие кадры LeadChat не читаем и не пересылаем; узнаём только, что ушёл ping (короткий кадр {"type":"ping"…} —
   по началу строки, без разбора), и что LeadChat сам бросает сокет (close()): нет pong'а за 10 с — WsClient.ts
   закрывает сокет и переподключается, не дожидаясь onclose, — расширение тоже узнаёт об этом сразу (rt:closing).
   Наружу (в мир расширения) уходит только выжимка без текста сообщений, имён и телефонов:
   тип, id диалога, флажки, время. Исключение одно — inbox:new / inbox:released: строка очереди «Входящих» целиком
   (та же, что отдаёт GET /inbox и что LeadChat сам вставляет в свой список) — новый диалог проверяем без лишнего запроса.
   Ещё — «адрес страницы сменился» (rt:route, без самого адреса): LeadChat — одностраничный, content.js сразу сверяет диалог.
   Канал — случайное имя, его знают только этот файл и rt.js (узнаёт до скриптов страницы).
   Любая наша ошибка глотается здесь же: LeadChat не должен заметить, что мы есть. */
(() => {
  'use strict';
  const Исходный = window.WebSocket;
  if (typeof Исходный !== 'function') return;
  // свои ссылки на всё, чем пользуемся: скрипты страницы могли бы подменить их позже и подслушать канал
  const apply = Reflect.apply, Событие = CustomEvent, разобрать = JSON.parse, собрать = JSON.stringify;
  const отправить = EventTarget.prototype.dispatchEvent, слушать = EventTarget.prototype.addEventListener,
    снять = EventTarget.prototype.removeEventListener, Адрес = URL, сейчас = Date.now, d = document;
  const таймер = setTimeout, снятьТаймер = clearTimeout, ПИНГ = /^\s*\{\s*"type"\s*:\s*"ping"\s*[,}]/;
  const случайное = () => {
    try {
      if (crypto.randomUUID) return crypto.randomUUID();
      const a = new Uint8Array(16); crypto.getRandomValues(a);
      return Array.from(a, (b) => b.toString(16).padStart(2, '0')).join('');
    } catch (_e) { return ''; }
  };
  const id = случайное();
  if (!id) return;                                                   // без случайного имени канала не слушаем вовсе: расширение останется на опросе
  const КАНАЛ = 'lcz-rt-' + id, ВЕРСИЯ = 1;
  const ПРИВЕТ = 'lcz-rt-hello', ЗОВ = 'lcz-rt-ask', ЕСТЬ = 'lcz-rt-ok';
  const событие = (имя, текст) => { try { apply(отправить, d, [new Событие(имя, { detail: текст })]); } catch (_e) { /* молчим: LeadChat важнее */ } };
  const передать = (o) => { try { событие(КАНАЛ, собрать(o)); } catch (_e) { /* молчим */ } };

  /* Смена адреса: LeadChat ходит по диалогам через history.pushState / replaceState, «назад» — popstate. Событие только
     «сменился» — адрес content.js читает сам. Подменяем методы прототипа History своими (то же имя, тот же результат и те же
     исключения — сначала исходный метод); не вышло — маршрут = false, content.js обходит страницу раз в 800 мс, как раньше. */
  let маршрут = false;
  try {
    const H = History.prototype, push = H.pushState, replace = H.replaceState;
    if (typeof push === 'function' && typeof replace === 'function') {
      const сменился = () => передать({ t: 'rt:route' });
      const свои = {
        pushState(...a) { const r = apply(push, this, a); сменился(); return r; },
        replaceState(...a) { const r = apply(replace, this, a); сменился(); return r; },
      };
      for (const k of ['pushState', 'replaceState']) {
        const было = Object.getOwnPropertyDescriptor(H, k) || { writable: true, enumerable: true, configurable: true };
        Object.defineProperty(H, k, { value: свои[k], writable: было.writable !== false, enumerable: !!было.enumerable, configurable: было.configurable !== false });
      }
      apply(слушать, window, ['popstate', сменился]);
      маршрут = true;
    }
  } catch (_e) { маршрут = false; /* молчим: без события адреса — обход content.js */ }

  /* Рукопожатие — до скриптов страницы. Порядок запуска двух миров не важен:
     мы первые — rt.js позовёт (ЗОВ) и мы ответим; rt.js первый — услышит ПРИВЕТ и подтвердит (ЕСТЬ).
     После ответа или подтверждения ЗОВ больше не слушаем: позже позвать нас может только страница. */
  const закрытьЗов = () => { try { apply(снять, d, [ЗОВ, наЗов, true]); apply(снять, d, [ЕСТЬ, закрытьЗов, true]); } catch (_e) { /* молчим */ } };
  // маршрут: rt:route будет (history подменён) — content.js может обходить страницу реже
  const привет = () => собрать({ v: ВЕРСИЯ, канал: КАНАЛ, маршрут });
  function наЗов() { закрытьЗов(); событие(ПРИВЕТ, привет()); }
  try { apply(слушать, d, [ЗОВ, наЗов, true]); apply(слушать, d, [ЕСТЬ, закрытьЗов, true]); } catch (_e) { return; }
  событие(ПРИВЕТ, привет());

  // сокет LeadChat: тот же хост и /api/v1/ws (или старое /api/ws); остальные сокеты (если появятся) — мимо
  const сокетLeadChat = (url) => {
    try {
      const u = new Адрес(String(url), location.href);
      return /^(wss?|https?):$/.test(u.protocol) && u.host === location.host && /^\/api\/(v1\/)?ws\/?$/.test(u.pathname);
    } catch (_e) { return false; }
  };
  // id и перечисления — короткие строки без пробелов; всё прочее (текст, имена, телефоны) не берём никогда
  const ид = (x) => (typeof x === 'string' && /^[\w-]{1,64}$/.test(x) ? x : '');
  const слово = (x) => (typeof x === 'string' && /^[a-z_]{1,24}$/.test(x) ? x : '');
  const да = (x) => x === true;
  // время ISO (как отдаёт LeadChat: 2026-10-07T10:00:00.000Z) — иначе пусто
  const ВРЕМЯ = (v) => (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T[\d:.]{5,15}(Z|[+-]\d{2}:?\d{2})?$/.test(v) ? v : '');
  const объект = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const ВЛАДЕЛЕЦ = (p) => {                                          // кто ведёт диалог: id, null — никто, undefined — кадр не сказал
    if (!p || typeof p !== 'object') return undefined;
    if ('assignee_id' in p) return p.assignee_id === null ? null : ид(p.assignee_id) || undefined;
    if ('assignee' in p) return p.assignee === null ? null : (p.assignee && ид(p.assignee.id)) || undefined;
    return undefined;
  };
  function выжимка(e) {
    const t = e && e.type, x = объект(e && e.data) || {};
    if (typeof t !== 'string') return null;
    const o = { t, id: ид(x.conversation_id), ts: typeof e.ts === 'string' ? e.ts.slice(0, 32) : '' };
    switch (t) {
      case 'inbox:new': case 'inbox:released': {
        o.can_claim = да(x.can_claim); o.returned = да(x.returned);
        o.escalated = да(x.conversation && x.conversation.escalated);
        o.client = ид(x.conversation && x.conversation.client && x.conversation.client.id);
        if (t === 'inbox:released') o.by = ид(x.released_by && x.released_by.id);   // кто вернул в очередь — только id
        // строка очереди — своя у LeadChat (services/inbox.inbox_item, как GET /inbox): уходит только в наш канал;
        // больше 64 КБ или не тот диалог — не берём, content.js дочитает её одним GET /inbox
        const c = объект(x.conversation);
        if (c && c.id === x.conversation_id) { try { const s = собрать(c); if (s.length <= 65536) o.row = разобрать(s); } catch (_e) { /* без строки — content.js дочитает списком */ } }
        return o.id ? o : null;
      }
      case 'inbox:claimed':
        o.is_mine = да(x.is_mine); return o.id ? o : null;
      case 'inbox:declined':
        o.undone = да(x.undone); return o.id ? o : null;
      case 'message:new': {
        const m = объект(x.message) || {}, p = объект(x.conversation_patch) || {};
        o.dir = слово(m.direction); o.from = слово(m.sender_type); o.msg = ид(m.id);
        // заметка «Лид-бот считает заявку собранной» (то же правило, что ЛИДБОТ_ГОТОВ в content.js) — только признак, без текста
        if (m.direction === 'note') o.lb = typeof m.body === 'string' && /Лид-бот считает заявку собранной|заявка собрана\s*[—–-]\s*бот закрыл|заявка собрана и передана\s*[—–-]\s*диалог закрыт ботом/i.test(m.body);
        o.owner = ВЛАДЕЛЕЦ(p); o.status = слово(p.status);
        // время сообщения и дельта строки — чтобы content.js обновил свою строку «Входящих» так же, как её отдаст GET /inbox
        o.at = ВРЕМЯ(m.created_at); o.lm = ВРЕМЯ(p.last_message_at);
        if ('waiting_since' in p) o.ws = p.waiting_since === null ? null : ВРЕМЯ(p.waiting_since);
        // голосовое (вложение avito_type='voice', как voice_id_of в LeadChat; MAX — max_type 'audio' / 'audioMessage', LeadChat
        // расшифровывает их с 12.10, voice_url_of): разбирать после message:transcript, не раньше
        o.voice = Array.isArray(m.attachments) && m.attachments.some((a) => a && (a.avito_type === 'voice' || a.kind === 'voice'
          || a.max_type === 'audio' || a.max_type === 'audioMessage'));
        return o.id ? o : null;
      }
      case 'message:transcript':
        o.msg = ид(x.message_id); o.st = слово(x.voice_transcript_status); return o.id ? o : null;
      case 'client:updated':
        o.client = ид(x.client_id); o.reason = слово(x.reason); return o.client || o.id ? o : null;
      case 'conversation:updated': {
        const p = объект(x.patch) || {};
        if ('in_inbox' in p) o.in_inbox = да(p.in_inbox);
        if ('status' in p) o.status = слово(p.status);
        // диалог взял бот (lc app/bots/engine.py: патч {bot_active: true}) — из очереди он ушёл, кадра inbox:* для этого нет
        if ('bot_active' in p) o.bot = да(p.bot_active);
        o.owner = ВЛАДЕЛЕЦ(p);
        if (x.transfer_outcome) o.transfer = слово(x.transfer_outcome);
        // клиента переименовали (№ заявки в имени — так помечают оформленных) — только признак, без имени
        if (объект(p.client)) o.cl = true;
        // № заявки лид-центра у диалога (LeadChat 12.10: патч {crm_request_id, crm_request_at}) — номер (id-строка) или null — стёрли;
        // открытая форма и «Готовые» узнают «заявка уже есть» сразу. Нет в патче — поля нет
        if ('crm_request_id' in p) { o.crm = p.crm_request_id === null ? null : ид(String(p.crm_request_id)) || null; o.crm_at = ВРЕМЯ(p.crm_request_at); }
        return o.id ? o : null;
      }
      case 'conversation:assigned':
        o.for_me = да(x.is_for_you); o.offer = да(x.offer); return o.id ? o : null;
      case 'presence:online':
        o.user = ид(x.user_id); o.status = слово(x.status); delete o.id; return o.user ? o : null;
      default: return null;                                          // pong, typing, зрители, уведомления — не нужны
    }
  }

  let номер = 0, живойAt = 0;
  const PONG_МС = 12e3;                                              // LeadChat ждёт pong 10 с (WsClient.ts PONG_TIMEOUT_MS), мы — чуть дольше
  function подслушать(ws) {
    const n = ++номер;
    // закрыт — LeadChat сам бросил сокет (close()) или пришло close; глух — ping ушёл, pong'а нет 12 с
    let закрыт = false, глух = false, пингT = 0;
    const снятьПинг = () => { if (пингT) { try { apply(снятьТаймер, window, [пингT]); } catch (_e) { /* молчим */ } пингT = 0; } };
    передать({ t: 'rt:socket', n });
    const наКадр = (ev) => {
      try {
        const now = сейчас();
        if (now - живойAt > 20e3) { живойAt = now; передать({ t: 'rt:alive', n }); }   // «сокет жив» — не чаще раза в 20 с (pong тоже кадр)
        const raw = ev.data;
        if (typeof raw !== 'string' || raw.length > 4e6) return;
        let e;
        try { e = разобрать(raw); } catch (_e) { return; }           // битый кадр — не наше дело, LeadChat тоже его пропустит
        if (e && e.type === 'pong') {                                // pong пришёл — сокет жив; объявили «глухим» — снова открыт
          снятьПинг();
          if (глух && !закрыт) { глух = false; живойAt = now; передать({ t: 'rt:open', n }); }
          return;
        }
        const o = выжимка(e);
        if (o) { o.n = n; передать(o); }
      } catch (_e) { /* молчим */ }
    };
    apply(слушать, ws, ['message', наКадр]);
    apply(слушать, ws, ['open', () => { живойAt = сейчас(); передать({ t: 'rt:open', n }); }]);
    apply(слушать, ws, ['close', (ev) => { закрыт = true; снятьПинг(); передать({ t: 'rt:close', n, code: Number(ev && ev.code) || 0 }); }]);
    return {
      // LeadChat закрывает сокет сам (нет pong'а, ошибка, выход) — onclose на мёртвом пути бывает через минуту, «не открыт» — сейчас
      закрывают() { if (закрыт) return; закрыт = true; снятьПинг(); if (!глух) передать({ t: 'rt:closing', n, why: 'close' }); },
      // ушёл ping: нет pong'а за 12 с — «не открыт» (LeadChat к этому времени обычно уже сам закрыл сокет — тогда тишина)
      пинг() {
        if (закрыт) return;
        снятьПинг();
        пингT = apply(таймер, window, [() => { пингT = 0; if (закрыт || глух) return; глух = true; передать({ t: 'rt:closing', n, why: 'pong' }); }, PONG_МС]);
      },
    };
  }

  // подкласс, а не обёртка: instanceof, статики (OPEN…), prototype и имя «WebSocket» у LeadChat остаются как были.
  // close / send — сначала наша пометка (без исключений наружу), потом исходный метод с теми же аргументами и его результат
  class WebSocket extends Исходный {
    #слух = null;                                                    // только у сокета LeadChat; приватное поле — странице не видно
    constructor(...args) {
      super(...args);
      try { if (сокетLeadChat(args[0])) this.#слух = подслушать(this); } catch (_e) { /* молчим */ }
    }
    close(...args) {
      try { const с = this.#слух; if (с) с.закрывают(); } catch (_e) { /* чужой this — исходный close ответит сам */ }
      return super.close(...args);
    }
    send(...args) {
      const r = super.send(...args);                                 // ошибка (сокет ещё соединяется) — LeadChat получит её как была
      // только ping: короткая строка, начинается с {"type":"ping" — остальное не читаем и никуда не передаём
      try { const с = this.#слух, x = args[0]; if (с && typeof x === 'string' && x.length <= 200 && ПИНГ.test(x)) с.пинг(); } catch (_e) { /* молчим */ }
      return r;
    }
  }
  try {
    const было = Object.getOwnPropertyDescriptor(window, 'WebSocket') || { writable: true, enumerable: false, configurable: true };
    Object.defineProperty(window, 'WebSocket', { value: WebSocket, writable: было.writable !== false, enumerable: !!было.enumerable, configurable: было.configurable !== false });
  } catch (_e) { /* не вышло — значит без мгновенных событий, расширение на опросе */ }
})();
