/* 1.20 ПОДСКАЗКИ И НАПОМИНАНИЯ ПО ЗАЯВКАМ (разделы 4.3 и 4.1–4.2 проекта): расширение само замечает, что пора что-то сделать,
   и показывает уведомление с готовым действием. САМО НИЧЕГО НЕ ДЕЛАЕТ: запись в CRM / Telegram — только по клику оператора
   («Сделать» → бегунок LC_ACT_UI.исполнить, «Открыть» → карточка действия с превью).
   • модерация: нажали «Не отвечает» (в расширении в любой вкладке или прямо в CRM) → через 10–15 мин «Позвонить ещё раз (2/6)»;
     6 попыток или 1,5 ч — «Не оформлена» с «клиент не выходит на связь»; после 24:00 — звонки в 8:00 и 10:00 по городу (рег:799–802);
   • «На уточнении» (создана нами): 2 ч клиент не перезвонил — «позвоните сами» (рег:1206–1208); почти 48 ч — закрыть (штраф 300, рег:1566);
   • прозвон: время звонка наступило (±15 мин по городу) — «Взять прозвон», потом «Договорились / Не ответил / Вернуть»;
     взяли и 20 мин ничего — «вернуть?» (рег:1438–1451);
   • визит прошёл > 10 мин (Ожидает / В пути) — только бейдж для сетки, без уведомления;
   • статус сменили другие (Отмена Филиала, Отказ, Готов) — тихое уведомление без действия;
   • правила регламента по снимку созданной заявки (4.2, например МНЧ на 2+ дня без «Прозвона перед выездом») и подсказки из
     переписки (4.1, хост зовёт подсказать()) — тем же уведомлением.
   Что сделали из расширения — узнаём из журнала бегунка (actLog, общий для всех вкладок): действие могли нажать в другой вкладке.
   Опрос CRM — только ведущая видимая вкладка, только заявки из «создано» за 12 ч и из напоминаний;
   снимок не чаще 1 раза в 5 мин на заявку и не больше 20 за 5 мин; сессия CRM истекла — пауза 10 мин.
   «Позже» и «Не нужно» запоминаются (chrome.storage, ключ actWatch) — другая вкладка и перезагрузка их не забывают.
   Сроки регламента — из одной таблицы actions.js (LC_ACT.НАСТРОЙКИ.пороги); здесь только запасные и технические.
   Личных данных не храним: база, №, диалог, город, время и коды статусов. */
const LC_ACT_WATCH = (() => {
  const МИН = 60e3, ЧАС = 3600e3;
  const П0 = {
    // ТЕХНИЧЕСКИЕ (бюджет чтений CRM, частота опроса, память) — меняются только здесь
    тик: МИН,                    // как часто смотрим (ведущая вкладка)
    окно: 5 * МИН,               // бюджет чтений CRM: не больше `всегоЗаОкно` снимков за `окно`
    всегоЗаОкно: 20,
    наЗаявку: 5 * МИН,           // и не чаще одного снимка заявки за 5 мин
    опросОбычный: 15 * МИН,      // созданная заявка без близких событий — смотрим раз в 15 мин (чужая смена статуса)
    опросГорячий: 5 * МИН,       // прозвон скоро / заявка за мной — раз в 5 мин
    опросДальний: 30 * МИН,      // не из «создано» (прозвон перенесли на завтра) — раз в 30 мин, к звонку — чаще
    свежесть: 5 * МИН,           // уведомление с действием — только по снимку не старше 5 мин
    пауза: 10 * МИН,             // сессия CRM истекла — не стучимся 10 мин
    созданные: 12 * ЧАС,         // из «создано» смотрим заявки за 12 ч
    сбойПовтор: 5 * МИН,         // снимок не удался — снова через 5, 10, 20… мин (не больше часа)
    хранить: 7 * 24 * ЧАС,       // «Не нужно» и «показано» помним неделю
    прозвонХранить: 3 * 24 * ЧАС,
    повтор: 30e3,                // одно и то же «сделано» от двух источников (бегунок + уведомление) считаем один раз
    журналОкно: 2 * ЧАС,         // действия из журнала бегунка старше 2 ч — история: новых напоминаний по ним не заводим
    позже: 15 * МИН,             // «Позже»
    прозвонДо: 120,              // пропустили время звонка — напоминаем ещё 2 ч, дальше это уже не «сейчас»
    уточнениеЗаранее: 2 * ЧАС,   // «решите заявку на уточнении» — за 2 ч до срока
    срокЧтения: 60e3,            // снимок CRM не пришёл за минуту — сбой (иначе зависший ответ навсегда остановил бы опрос во вкладке)
    срокВкладок: 3000,           // «открыта ли во вкладке CRM» и пояс диалога — не дольше 3 с: уведомление не ждёт их вечно
    // «Сделать» прямо из уведомления — только эти действия (без ввода и без Telegram); остальное — «Открыть» (карточка с превью)
    сразу: ['noanswer', 'pz_take', 'take', 'pz_release', 'release'],
    // правила регламента (4.2) по снимку созданной заявки — уведомлением только эти ключи: без переписки другим правилам не хватает данных
    правилаИзОпроса: ['flags'],
    // РЕГЛАМЕНТ — запасные значения; настоящие берутся из LC_ACT.НАСТРОЙКИ.пороги (сПорогами ниже)
    модИнтервал: 12 * МИН,       // модерация: звонки с интервалом 10–15 мин (рег:800)
    модПопыток: 6,               // 5–6 звонков…
    модСерия: 90 * МИН,          // …за 1–1,5 ч
    ночьДо: 8 * 60,              // после 24:00 — в 8:00 и 10:00 по городу клиента (рег:801), минуты от полуночи
    утроВторой: 10 * 60,
    уточнениеЗвонок: 2 * ЧАС,    // «не перезванивает в течение 2-х часов — звоним сами» (рег:1206)
    уточнениеСрок: 48 * ЧАС,     // штраф 300 — за «более чем двое суток» (рег:1566)
    прозвонОкно: 15,             // время звонка ±15 мин по городу
    держуБезДела: 20 * МИН,      // взял прозвон и 20 мин ничего — «вернуть?»
    опоздание: 10,               // визит прошёл больше 10 мин — бейдж «опаздывает»
  };
  // сроки регламента — из ОДНОЙ таблицы actions.js: владелец ответил по-другому — меняется только она
  function сПорогами(база) {
    const П1 = { ...база };
    let п = null;
    try { п = typeof LC_ACT !== 'undefined' && LC_ACT.НАСТРОЙКИ && LC_ACT.НАСТРОЙКИ.пороги; } catch (_e) { п = null; }
    if (!п || typeof п !== 'object') return П1;
    const чис = (v) => (typeof v === 'number' && isFinite(v) && v > 0 ? v : null);
    const чм = (v) => { const m = /^(\d{1,2}):(\d{2})$/.exec(String(v || '')); return m ? +m[1] * 60 + +m[2] : null; };
    const взять = (куда, v, k) => { if (v !== null) П1[куда] = v * (k || 1); };
    const через = Array.isArray(п.недозвонЧерез) ? п.недозвонЧерез.map(Number).filter((x) => x > 0) : [];
    if (через.length) П1.модИнтервал = Math.floor((через[0] + через[через.length - 1]) / 2) * МИН;   // «10–15 мин» — середина
    взять('модПопыток', чис(п.недозвонПопыток));
    взять('модСерия', чис(п.недозвонОкноМин), МИН);
    взять('ночьДо', чм(п.недозвонНочьДо));
    const утро = Array.isArray(п.недозвонУтро) ? п.недозвонУтро.map(чм).filter((x) => x !== null) : [];
    if (утро.length > 1) П1.утроВторой = утро[утро.length - 1];
    взять('уточнениеЗвонок', чис(п.уточнениеПерезвонМин), МИН);
    взять('уточнениеСрок', чис(п.уточнениеСрокЧ), ЧАС);
    взять('прозвонОкно', чис(п.прозвонОкноМин));
    взять('держуБезДела', чис(п.прозвонДержуМин), МИН);
    взять('опоздание', чис(п.опозданиеОтменаМин));
    return П1;
  }
  const КЛЮЧ = 'actWatch';
  const ИМЯ = { kp: 'КП', mnc: 'МНЧ', bt: 'БТ' };
  // такие статусы ставит не оператор КЦ — о них тихо сообщаем (раздел 4.3)
  const ЧУЖИЕ = { 1002: 'Отмена Филиала', 1003: 'Отмена Регионал', 64: 'Отказ', 128: 'Готов', 1020: 'Готов ОФ' };
  // дальше этих статусов следить нечего: опрос заявки прекращаем
  const ЖИВЫЕ = { 1: 1, 4: 1, 8: 1, 9: 1, 2: 1, 3: 1 };
  // события таймеров → имена событий каталога (LC_ACT.подсказка('watch', снимок, {event…}))
  const СОБЫТИЕ = { mod_again: 'noanswer', mod_final: 'noanswer', pre_2h: 'precheck_2h', pre_48h: 'precheck_48h', pz_call: 'prozvon_time', pz_held: 'prozvon_held' };
  // составные действия: «частично» — неизвестно, какие шаги прошли; такие из журнала не учитываем
  const СОСТАВНЫЕ = { pz_agreed: 1, pz_noanswer: 1 };
  const сколько = (m) => (m >= 60 ? Math.floor(m / 60) + ' ч' + (m % 60 ? ' ' + (m % 60) + ' мин' : '') : m + ' мин');
  const чч = (t) => new Date(t).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
  // ключ подсказки для «показано / Позже / Не нужно»: без телефона (его по хэшу легко подобрать)
  function хэш(s) { let h = 0x811c9dc5; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; } return h.toString(36); }
  function канон(x) {
    if (Array.isArray(x)) return '[' + x.map(канон).join(',') + ']';
    if (x && typeof x === 'object') return '{' + Object.keys(x).filter((k) => x[k] !== undefined && !/тел|phone/i.test(k)).sort().map((k) => JSON.stringify(k) + ':' + канон(x[k])).join(',') + '}';
    return JSON.stringify(x === undefined ? null : x);
  }

  function норм(s) {
    s = s && typeof s === 'object' ? s : {};
    for (const k of ['снимки', 'напом', 'держу', 'наши', 'показано', 'позже', 'ненужно', 'учтено', 'читаю']) if (!s[k] || typeof s[k] !== 'object') s[k] = {};
    if (!Array.isArray(s.чтения)) s.чтения = [];
    s.пауза = Number(s.пауза) || 0;
    return s;
  }
  // итог действия по строкам (« · »): «не сделано» — первыми (⚠), сделанное — ✓
  // плохо — ⚠ или явный сбой («не отправлено», «не записалась»…), а не любое «не»/«нет» («клиент не ответил на звонок» — сделано)
  const ПЛОХО = /⚠|ошибк|неизвестн|не удал|(^|[\s(])не (отправ|записал|дописал|ушл|писали|найден|сохран|поставлен|отмечен|сделан)/i;
  function строкиИтога(h, text, ok) {
    const л = String(text || '').split(/\s+·\s+|\n/).map((x) => x.trim()).filter(Boolean).map((x) => ({ t: x.replace(/^[✓⚠]\s*/, ''), bad: ПЛОХО.test(x) }));
    if (!л.length) л.push({ t: ok ? 'Сделано' : 'Не сделано', bad: !ok });
    if (!ok && !л.some((x) => x.bad)) л.forEach((x) => { x.bad = true; });
    return л.sort((a, b) => b.bad - a.bad).map((x) => h('div', { class: 'tst-d ' + (x.bad ? 'warn' : 'ok') }, (x.bad ? '⚠ ' : '✓ ') + x.t));
  }
  /* 12: сколько напоминаний «пора» — только по хранилищу actWatch (без CRM): число в заголовке скрытой вкладки «(N) …».
     Показанные уже на экране (их считает хост), «Позже» и «Не нужно» — не в счёт */
  function пора(st0, now, визитСейчас) {
    const П = сПорогами(П0), st = норм(st0 && typeof st0 === 'object' ? { ...st0 } : {});
    const ждёт = (ключ) => !st.ненужно[ключ] && !((st.позже[ключ] || 0) > now);
    let n = 0;
    for (const r of Object.values(st.напом)) {
      if (!r || !r.k) continue;
      if (r.вид === 'mod' && r.next && r.next <= now && ждёт(r.k + '|mod') && !st.показано[r.k + '|mod#' + ((r.tries || 0) + 1)] && !st.показано[r.k + '|mod_final']) n++;
      if (r.вид === 'pre' && r.since) {
        if (now - r.since >= П.уточнениеСрок - П.уточнениеЗаранее) { if (ждёт(r.k + '|pre48') && !st.показано[r.k + '|pre48']) n++; }
        else if (now - r.since >= П.уточнениеЗвонок && !r.tries && ждёт(r.k + '|pre2') && !st.показано[r.k + '|pre2']) n++;
      }
    }
    for (const [k, t] of Object.entries(st.держу)) if (now - t >= П.держуБезДела && ждёт(k + '|pzheld') && !st.показано[k + '|pzheld@' + t]) n++;
    if (typeof визитСейчас === 'function') {
      for (const [k, s] of Object.entries(st.снимки)) {
        if (!s || s.code !== 1 || !s.call || s.mine || s.heldOther || !s.vt) continue;
        let x = {};
        try { x = визитСейчас({ city: s.city || '', visit: s.vd || '', visitTime: s.vt || '' }, '') || {}; } catch (_e) { x = {}; }
        const ключ = k + '|pz@' + s.vd + ' ' + s.vt;
        if (x.late !== null && x.late !== undefined && x.late >= -П.прозвонОкно && x.late <= П.прозвонДо && ждёт(ключ) && !st.показано[ключ]) n++;
      }
    }
    return n;
  }

  function создать(хост, ui, опц) {
    опц = опц || {};
    const П = { ...сПорогами(П0), ...(опц.П || {}) };
    const сейчас = опц.сейчас || (() => Date.now());
    const { h } = хост;
    const КАРТЫ = new Map();       // k → { card, at, tz } — полный снимок только в памяти вкладки (для превью)
    const ТОСТЫ = new Map();       // показ → элемент уведомления
    const ВНЕШНИЕ = new Map();     // показ → ключ действия: подсказки, которые принёс хост (подсказать) — опрос их не убирает
    const СДЕЛАНО = new Map();     // k|key → время: защита от двойного учёта одного действия
    const ЧИТАЮ = new Map();       // k → когда начали читать карточку (одна заявка — не чаще раза в 5 мин и при гонке вызовов)
    // «Позже» у подсказки хоста (4.1–4.2): через 15 мин покажем снова. Только в памяти вкладки — в данных переписки бывают слова клиента
    const ОТЛОЖЕНО = new Map();    // показ → { o, до, с, k, key }
    let идёт = false, таймер = null, живо = false;
    // уведомление закрыли × или его вытеснили другие — это «Позже» (15 мин), а не «показано навсегда».
    // ПОВОД: показ → событие; НАШИ — убрали сами (сделано, «Открыть», повода нет); ВЫТЕСНЕНЫ — отложены, но могут вернуться из «Пропущено»
    const ПОВОД = new Map(), НАШИ = new WeakSet(), ВЫТЕСНЕНЫ = new Map();
    const убрать = (el) => { if (el && el.remove) { НАШИ.add(el); el.remove(); } };
    // «· Имя, город» к заголовку: имя — из памяти вкладки хоста (форма, «Готовые»), город — из записи заявки; ничего не храним
    function кто(c) {
      let имя = '';
      try { имя = c.conv && typeof хост.имяКлиента === 'function' ? String(хост.имяКлиента(c.conv) || '') : ''; } catch (_e) { имя = ''; }
      const s = [имя.replace(/\s*\d{6,8}\b/g, '').trim(), String((c.cr && c.cr.city) || '').trim()].filter(Boolean).join(', ');
      return s ? ' · ' + s : '';
    }

    const видна = () => typeof document === 'undefined' || document.visibilityState === 'visible';
    const кл = (dir, id) => dir + ':' + id;
    const код = (card) => Number(card && card.statusCode) || 0;
    const решитьК = () => П.уточнениеСрок - П.уточнениеЗаранее;

    /* ---------- состояние: читаем/меняем под замком (вкладок несколько, «Не нужно» могут нажать в любой) ---------- */
    let очередь = Promise.resolve();
    function подЗамком(fn) {
      if (typeof navigator !== 'undefined' && navigator.locks && navigator.locks.request) return navigator.locks.request('lcz-act-watch', fn);
      const p = очередь.then(fn, fn);
      очередь = p.catch(() => {});
      return p;
    }
    const прочитать = async () => норм(await хост.store.get(КЛЮЧ, null));
    function изменить(fn) {
      return подЗамком(async () => {
        const st = норм(await хост.store.get(КЛЮЧ, null));
        const r = await fn(st);
        чистить(st, сейчас());
        await хост.store.set(КЛЮЧ, st);
        return r === undefined ? st : r;
      });
    }
    function чистить(st, now) {
      st.чтения = st.чтения.filter((t) => now - t < П.окно);
      for (const [k, t] of Object.entries(st.читаю)) if (!(now - t < П.наЗаявку)) delete st.читаю[k];
      for (const [k, t] of Object.entries(st.позже)) if (t <= now) delete st.позже[k];
      for (const m of [st.показано, st.ненужно, st.учтено]) for (const [k, t] of Object.entries(m)) if (now - t > П.хранить) delete m[k];
      for (const [k, x] of Object.entries(st.наши)) if (!x || now - x.at > П.хранить) delete st.наши[k];
      for (const [k, x] of Object.entries(st.напом)) {
        const срок = x && x.вид === 'pre' ? П.уточнениеСрок + 4 * ЧАС : x && x.вид === 'pz' ? П.прозвонХранить : П.созданные;
        if (!x || now - (x.since || x.first || x.at || 0) > срок) delete st.напом[k];
      }
      // снимки старше недели не нужны (иначе хранилище растёт сменами)
      for (const [k, x] of Object.entries(st.снимки)) if (!x || now - x.at > П.хранить) delete st.снимки[k];
    }
    // что из снимка помним между вкладками: без личных данных
    const кратко = (card, at) => ({ at, code: код(card), name: card.statusName || '', sig: card.sig || '',
      mine: !!(card.held && card.held.mine), heldOther: !!(card.held && card.held.yes && !card.held.mine),
      call: !!(card.flags && card.flags.callCheck), vd: card.visitDate || '', vt: card.visitTime || '',
      na: Number(card.noAnswerCount) || 0, city: card.cityName || '' });

    /* ---------- время по городу ---------- */
    function поГороду(city, vd, vt, tz) {
      try { return хост.визитСейчас({ city: city || '', visit: vd || '', visitTime: vt || '' }, tz || '') || {}; } catch (_e) { return {}; }
    }
    function местныеМин(city, tz) {
      const m = /^(\d{1,2}):(\d{2})/.exec(String(поГороду(city, '', '', tz).now || ''));
      return m ? +m[1] * 60 + +m[2] : 12 * 60;                         // пояс не узнали — считаем «днём»: ночное правило не сработает зря
    }
    // {date:'ГГГГ-ММ-ДД', time:'ЧЧ:ММ'} в городе заявки — каталогу (сроки «через 2+ дня», «до 21:30»). Дата — из сдвига местного времени
    // от UTC, чтобы около полуночи не взять московскую дату для Новосибирска
    function сейчасГород(city, tz) {
      const now = сейчас();
      const hm = /^(\d{1,2}):(\d{2})/.exec(String(поГороду(city, '', '', tz).now || ''));
      if (!hm) { const d = new Date(now + 3 * ЧАС).toISOString(); return { date: d.slice(0, 10), time: d.slice(11, 16) }; }   // по Москве
      const d0 = new Date(now);
      let сдвиг = (+hm[1] * 60 + +hm[2]) - (d0.getUTCHours() * 60 + d0.getUTCMinutes());
      if (сдвиг <= -12 * 60) сдвиг += 24 * 60;
      if (сдвиг > 14 * 60) сдвиг -= 24 * 60;
      return { date: new Date(now + сдвиг * МИН).toISOString().slice(0, 10), time: hm[1].padStart(2, '0') + ':' + hm[2] };
    }
    // ответ не пришёл за мс — «нет», а не вечное ожидание (опрос идёт по одному: зависший вызов остановил бы его до перезагрузки)
    function сроком(p, мс, нет) {
      let t = 0;
      return Promise.race([Promise.resolve(p).catch((e) => ({ ok: false, error: String((e && e.message) || e) })),
        new Promise((res) => { t = setTimeout(() => res(нет), мс); })]).finally(() => clearTimeout(t));
    }
    async function пояс(conv) { try { return conv && хост.поясДиалога ? (await сроком(хост.поясДиалога(conv), П.срокВкладок, '')) || '' : ''; } catch (_e) { return ''; } }

    /* ---------- модерация: следующий звонок ---------- */
    function попытка(r, t, мин) {
      r.tries = (r.tries || 0) + 1; r.last = t;
      if (r.утро === 2 && мин >= П.утроВторой - 30) { r.final = true; r.next = t; return; }   // звонок в 10:00 не помог — «Не оформлена»
      if (мин < П.ночьДо) { r.утро = 1; r.next = t + (П.ночьДо - мин) * МИН; return; }
      if (r.утро === 1) { r.утро = 2; r.next = t + Math.max(П.модИнтервал / МИН, П.утроВторой - мин) * МИН; return; }
      if (r.утро === 2) { r.next = t + Math.max(П.модИнтервал / МИН, П.утроВторой - мин) * МИН; return; }
      const м2 = мин + П.модИнтервал / МИН;
      if (м2 >= 24 * 60) { r.утро = 1; r.next = t + (24 * 60 - мин + П.ночьДо) * МИН; return; }
      r.next = t + П.модИнтервал;
    }

    /* ---------- после действия (бегунок, уведомление или журнал бегунка): запускаем / снимаем напоминания ---------- */
    // бегунку ошибки отсюда не нужны: действие уже сделано, напоминание — второстепенное
    async function послеДействия(x) { try { await послеДействия0(x); } catch (_e) { /* хранилище недоступно — без напоминания */ } }
    async function послеДействия0(x) {
      if (!x) return;
      const cr = x.cr || {};
      const dir = x.dir || cr.dir, id = String(x.id || cr.id || '');
      const key = x.key || (x.задание && x.задание.key) || '';
      const итог = x.итог || x.r || null;
      const ok = x.ok !== undefined ? !!x.ok : !!(итог && итог.ok);
      if (!dir || !id || !key || !ok) return;
      const k = кл(dir, id), now = сейчас(), t = Math.min(Number(x.at) || now, now);
      const раз = СДЕЛАНО.get(k + '|' + key);
      if (раз && now - раз < П.повтор) return;
      СДЕЛАНО.set(k + '|' + key, now);
      // бегунок отдаёт снимок после действия как «после» (PC), уведомления и тесты — как «after»
      const after = x.after || x.после || (итог && (итог.after || итог.после)) || null;
      const conv = x.conv || '';
      const tz = await пояс(conv);
      if (after && after.statusCode) КАРТЫ.set(k, { card: after, at: now, tz });
      else { const m = КАРТЫ.get(k); if (m && m.at <= t) КАРТЫ.delete(k); }   // снимок до действия устарел: по нему не напоминаем (дождёмся нового)
      const мин = местныеМин(cr.city || (after && after.cityName) || '', tz);
      const мал ={ dir, id: String(id), url: cr.url || (after && after.url) || '', city: cr.city || (after && after.cityName) || '' };
      let учли = false;
      await изменить((st) => {
        // это действие уже посчитали (уведомлением этой вкладки или прошлой ведущей) — журнал его второй раз не добавит
        if (x.изЖурнала && t <= (st.учтено[k + '|' + key] || 0)) return;
        учли = true;
        st.учтено[k + '|' + key] = x.изЖурнала ? t : now;
        st.наши[k] = { key, at: t };
        const прежний = st.снимки[k];
        let статус = after && after.statusCode ? код(after) : (прежний ? прежний.code : 0);
        // статус неизвестен (заявку ещё не снимали): «Не отвечает» без серии уточнения — считаем модерацией; снимок проверит
        if (!статус && key === 'noanswer') статус = st.напом[k + '|pre'] ? 3 : 2;
        if (after && after.statusCode) st.снимки[k] = кратко(after, now);
        if (key === 'noanswer' && статус === 2) {
          // na0 — сколько отметок «не отвечает» было до серии: потом по снимку видно, что нажали прямо в CRM
          const r = st.напом[k + '|mod'] || { вид: 'mod', k, dir, id, conv, cr: мал, first: t, tries: 0, утро: 0,
            na0: after && Number(after.noAnswerCount) > 0 && !x.безCRM ? Number(after.noAnswerCount) - 1 : null };
          // опрос мог прочесть карточку уже после этой отметки (журнал «ok» пишет позже CRM) и посчитать её как нажатую в CRM —
          // тогда второй раз не считаем. Сколько отметок в CRM после действия: из снимка «после» или из снимка опроса не раньше начала
          const вCRM = x.безCRM ? null : after && after.noAnswerCount !== undefined && after.noAnswerCount !== null ? Number(after.noAnswerCount)
            : прежний && !прежний.сбой && прежний.at >= t ? Number(прежний.na) : null;
          const ужеСчитали = st.напом[k + '|mod'] && r.na0 !== null && r.na0 !== undefined && вCRM !== null && isFinite(вCRM) && вCRM - r.na0 <= (r.tries || 0);
          if (!ужеСчитали) попытка(r, t, мин);
          st.напом[k + '|mod'] = r;
          delete st.ненужно[k + '|mod'];                                // нажали «Не отвечает» сами — серия снова нужна
        }
        // уточнение: звонили — «позвоните сами» выполнено (срок 48 ч считаем, только если заявку создали мы — иначе начало неизвестно)
        if (key === 'noanswer' && статус === 3 && st.напом[k + '|pre']) st.напом[k + '|pre'].tries = (st.напом[k + '|pre'].tries || 0) + 1;
        if (/^(mod_save|mod_to_city|mod_not_taken|mod_precheck|rejected|sama|precheck_not_created|to_not_taken)$/.test(key)) delete st.напом[k + '|mod'];
        if (/^(precheck_close|precheck_await|precheck_not_created|rejected|transfer)$/.test(key)) delete st.напом[k + '|pre'];
        // прозвон: взяли — пошли 20 минут; договорились / не ответил / вернули — заявка уже не «за мной»
        if (key === 'pz_take' || (key === 'take' && статус === 1)) {
          st.держу[k] = t;
          st.напом[k + '|pz'] = { вид: 'pz', k, dir, id, conv, cr: мал, at: t };
        } else if (/^(pz_agreed|pz_noanswer|pz_release|release)$/.test(key)) {
          delete st.держу[k];
          // «Не ответил» — перенос на следующий звонок: следим и за ним, даже если заявка не из «создано»
          if (key === 'pz_noanswer') st.напом[k + '|pz'] = { вид: 'pz', k, dir, id, conv, cr: мал, at: t };
        } else if (st.держу[k]) st.держу[k] = t;                        // любое действие по взятой заявке — она не забыта
      });
      if (!учли) return;
      for (const [п, x] of ОТЛОЖЕНО) if (x.k === k && x.key === key) ОТЛОЖЕНО.delete(п);   // отложенную подсказку уже сделали
      // действие сделано — уведомления «пора» по этой заявке больше не нужны; тихие о статусе остаются, подсказка хоста — если сделали другое
      for (const [p, el] of ТОСТЫ) {
        if (!p.startsWith(k + '|') || p.includes('|st') || (ВНЕШНИЕ.has(p) && ВНЕШНИЕ.get(p) !== key)) continue;
        убрать(el);
        ТОСТЫ.delete(p); ВНЕШНИЕ.delete(p); ПОВОД.delete(p);
      }
      for (const [p, x] of ВЫТЕСНЕНЫ) if (p.startsWith(k + '|') && !(x.e.o && x.e.p && x.e.p.key !== key)) { убрать(x.el); ВЫТЕСНЕНЫ.delete(p); }
    }

    /* ---------- журнал бегунка (actLog): что сделали из расширения в любой вкладке ---------- */
    async function изЖурнала(now) {
      let log = null;
      try { log = await хост.store.get('actLog', null); } catch (_e) { log = null; }
      if (!log || typeof log !== 'object') return;
      const st = await прочитать();
      const новые = [];
      for (const x of Object.values(log)) {
        if (!x || !ИМЯ[x.dir] || !x.id || !x.act || typeof x.act !== 'string') continue;
        const годно = x.state === 'ok' || (x.state === 'частично' && x.crmDone && !СОСТАВНЫЕ[x.act]);
        const at = Number(x.at) || 0;
        if (!годно || !(now - at < П.журналОкно) || at > now + МИН) continue;
        if (at <= (st.учтено[кл(x.dir, String(x.id)) + '|' + x.act] || 0)) continue;
        новые.push({ dir: x.dir, id: String(x.id), key: x.act, conv: typeof x.conv === 'string' ? x.conv : '', at });
      }
      новые.sort((a, b) => a.at - b.at);
      for (const x of новые) await послеДействия({ ...x, ok: true, изЖурнала: true });
    }

    /* ---------- кого смотреть ---------- */
    function кандидаты(created, st, now) {
      const m = new Map();
      for (const [conv, c] of Object.entries(created || {})) {
        if (!c || !c.id || !c.dir || !ИМЯ[c.dir] || !(now - (c.at || 0) < П.созданные)) continue;
        const k = кл(c.dir, c.id);
        if (!m.has(k)) m.set(k, { k, dir: c.dir, id: String(c.id), conv, cr: c, создана: true, напом: [] });
      }
      for (const r of Object.values(st.напом)) {
        if (!r || !r.k) continue;
        if (!m.has(r.k)) m.set(r.k, { k: r.k, dir: r.dir, id: String(r.id), conv: r.conv || '', cr: r.cr || { dir: r.dir, id: r.id }, создана: false, напом: [] });
        m.get(r.k).напом.push(r);
      }
      for (const k of Object.keys(st.держу)) if (!m.has(k)) { const [dir, id] = k.split(':'); m.set(k, { k, dir, id, conv: '', cr: { dir, id }, создана: false, напом: [] }); }
      return [...m.values()];
    }
    // когда снимать заявку: раньше всего — по сроку напоминания; «горячие» — раз в 5 мин, остальные — раз в 15
    function когдаСнять(c, st, now) {
      const s = st.снимки[c.k];
      if (!s) return now;
      if (s.сбой) return s.at + Math.min(ЧАС, П.сбойПовтор * 2 ** Math.min(4, s.сбой - 1));
      if (s.code && !ЖИВЫЕ[s.code] && !c.напом.length) return Infinity;       // отменена / готова — следить нечего
      const tz = (КАРТЫ.get(c.k) || {}).tz || '';
      let горячая = !!st.держу[c.k] || s.mine;
      if (s.call && s.code === 1) {
        const x = поГороду(s.city || (c.cr && c.cr.city), s.vd, s.vt, tz);
        if (x.late !== null && x.late !== undefined && x.late >= -30 && x.late <= П.прозвонДо) горячая = true;
      }
      // заявка не из «создано» и только с напоминанием «модерация / уточнение» — читаем лишь к сроку напоминания
      const следить = c.создана || горячая || c.напом.some((r) => r.вид === 'pz');
      let t = следить ? s.at + (горячая ? П.опросГорячий : c.создана ? П.опросОбычный : П.опросДальний) : Infinity;
      if (s.call && s.code === 1 && !горячая) {
        // звонок ещё не скоро — следующий снимок к началу окна звонка (за 30 мин), не раньше обычного
        const x = поГороду(s.city || (c.cr && c.cr.city), s.vd, s.vt, tz);
        if (x.late !== null && x.late !== undefined && x.late < -30) t = Math.min(t, Math.max(now + (-x.late - 30) * МИН, s.at + П.наЗаявку));
      }
      // к сроку напоминания — снимок сразу; уже показали (ждём оператора) — раз в 15 мин, только чтобы убрать, если повода не стало
      for (const r of c.напом) {
        let d = null, ключ = '', показан = false;
        if (r.вид === 'mod') {
          d = r.next; ключ = c.k + '|mod';
          показан = !!(st.показано[c.k + '|mod#' + ((r.tries || 0) + 1)] || st.показано[c.k + '|mod_final']);
        }
        if (r.вид === 'pre') {
          // «позвоните сами» ещё впереди (не показано, не звонили, клиент не писал) — снимок к 2 ч; иначе — к сроку «решите заявку»
          if (!r.tries && !st.показано[c.k + '|pre2'] && !st.ненужно[c.k + '|pre2'] && !клиентПисал(c.cr) && now - r.since < решитьК()) { d = r.since + П.уточнениеЗвонок; ключ = c.k + '|pre2'; }
          else { d = r.since + решитьК(); ключ = c.k + '|pre48'; показан = !!st.показано[ключ]; }
        }
        if (d === null || st.ненужно[ключ]) continue;
        d = Math.max(d, st.позже[ключ] || 0);
        t = Math.min(t, Math.max(d, s.at + (показан ? П.опросОбычный : П.наЗаявку)));
      }
      return t;
    }

    /* ---------- что показать по свежему снимку ---------- */
    function события(c, card, st, now, tz) {
      const out = [], k = c.k, s = код(card);
      const мин = местныеМин(card.cityName || (c.cr && c.cr.city), tz);
      const изм = [];                                                  // правки состояния: применим под замком
      for (const r of c.напом) {
        if (r.вид === 'mod') {
          if (s !== 2) { изм.push((x) => { delete x.напом[k + '|mod']; }); continue; }
          // «Не отвечает» нажали прямо в CRM — тоже попытка
          const копия = { ...r };
          if (копия.na0 === null || копия.na0 === undefined) копия.na0 = Math.max(0, (Number(card.noAnswerCount) || 0) - (копия.tries || 0));
          const вCRM = (Number(card.noAnswerCount) || 0) - копия.na0;
          if (копия.na0 !== r.na0) изм.push((x) => { if (x.напом[k + '|mod']) x.напом[k + '|mod'].na0 = копия.na0; });
          while (вCRM > (копия.tries || 0)) попытка(копия, now, мин);
          if (now < копия.next) { if (копия.tries !== r.tries) изм.push((x) => { x.напом[k + '|mod'] = копия; }); continue; }
          // срок пришёлся на ночь — ночью не звоним: ждём 8:00 по городу
          if (!копия.утро && мин < П.ночьДо) { копия.утро = 1; копия.next = now + (П.ночьДо - мин) * МИН; изм.push((x) => { x.напом[k + '|mod'] = копия; }); continue; }
          if (копия.tries !== r.tries) изм.push((x) => { x.напом[k + '|mod'] = копия; });
          const конец = копия.final || копия.tries >= П.модПопыток || (!копия.утро && now - копия.first >= П.модСерия);
          if (конец) out.push({ вид: 'mod_final', ключ: k + '|mod', показ: k + '|mod_final', попыток: копия.tries, first: копия.first });
          else out.push({ вид: 'mod_again', ключ: k + '|mod', показ: k + '|mod#' + (копия.tries + 1), n: копия.tries + 1, попыток: копия.tries, first: копия.first, last: копия.last, утро: копия.утро });
        }
        if (r.вид === 'pre') {
          if (s !== 3) { изм.push((x) => { delete x.напом[k + '|pre']; }); continue; }
          if (now - r.since >= решитьК()) out.push({ вид: 'pre_48h', ключ: k + '|pre48', показ: k + '|pre48', since: r.since, тихо: (Number(card.noAnswerCount) || 0) > 0 || (r.tries || 0) > 0 });
          else if (now - r.since >= П.уточнениеЗвонок && !r.tries && !клиентПисал(c.cr)) out.push({ вид: 'pre_2h', ключ: k + '|pre2', показ: k + '|pre2', since: r.since });
        }
        if (r.вид === 'pz' && !(s === 1 && card.flags && card.flags.callCheck)) изм.push((x) => { delete x.напом[k + '|pz']; delete x.держу[k]; });
      }
      // прозвон (зелёная заявка): время звонка, «за мной 20 мин»
      if (s === 1 && card.flags && card.flags.callCheck) {
        const held = card.held || {};
        if (held.yes && !held.mine) изм.push((x) => { delete x.держу[k]; });                  // прозванивает другой — не мешаем
        else if (held.mine) {
          const с = Math.max(st.держу[k] || now, (st.наши[k] || {}).at || 0);
          if (!st.держу[k]) изм.push((x) => { x.держу[k] = x.держу[k] || now; });
          if (now - с >= П.держуБезДела) out.push({ вид: 'pz_held', ключ: k + '|pzheld', показ: k + '|pzheld@' + (st.держу[k] || now), с });
        } else {
          if (st.держу[k]) изм.push((x) => { delete x.держу[k]; });
          const x = поГороду(card.cityName || (c.cr && c.cr.city), card.visitDate, card.visitTime, tz);
          if (x.late !== null && x.late !== undefined && x.late >= -П.прозвонОкно && x.late <= П.прозвонДо) {
            const когда = (card.visitDate || '') + ' ' + (card.visitTime || '');
            out.push({ вид: 'pz_call', ключ: k + '|pz@' + когда, показ: k + '|pz@' + когда, время: card.visitTime || '', late: x.late });
          }
        }
      } else if (st.держу[k]) изм.push((x) => { delete x.держу[k]; });
      // правила регламента (4.2) по снимку созданной заявки: «показано» помнится — одно уведомление, пока повод есть
      const пр = поПравилам(c, card, tz);
      if (пр) { const ключ = k + '|rules:' + пр.key + ':' + хэш(канон(пр.ввод || {})); out.push({ вид: 'rules', ключ, показ: ключ, p: пр }); }
      return { out, изм };
    }
    // клиент написал в диалог после создания — он на связи, «позвоните сами» не нужно
    const клиентПисал = (cr) => !!(cr && cr.seenAt && cr.at && cr.seenAt > cr.at + 60e3);

    /* ---------- что предложить: каталог (LC_ACT.подсказка), но в рамках события; иначе — таблица ниже ---------- */
    // по порядку: первое доступное у этой заявки (кнопки — из снимка карточки). Ввод — как в каталоге (reason, code)
    const ПО_УМОЛЧАНИЮ = {
      mod_again: () => [{ key: 'noanswer', ввод: {} }],
      mod_final: () => [{ key: 'mod_not_taken', ввод: { reason: 'клиент не выходит на связь' } }, { key: 'to_not_taken', ввод: { reason: 'клиент не выходит на связь' } }],
      pre_2h: () => [{ key: 'noanswer', ввод: {} }],
      // не дозвонились — «НФ Не отвечает» (579), иначе «НФ не акт» (517): выбор виден и меняется в карточке
      pre_48h: (e) => [e.тихо ? { key: 'precheck_close', ввод: { code: 579 } } : { key: 'precheck_close', ввод: { code: 517 } }],
      // «Взять в работу» есть не у всех зелёных заявок (V1) — тогда сразу итог звонка
      pz_call: () => [{ key: 'pz_take', ввод: {} }, { key: 'pz_agreed', ввод: {} }, { key: 'move', ввод: {} }],
      pz_held: () => [{ key: 'pz_release', ввод: {} }, { key: 'release', ввод: {} }],
    };
    function доступно(card, key, dir) {
      try { return typeof LC_ACT !== 'undefined' && (LC_ACT.доступные(card, { dir, источник: 'watch' }) || []).some((a) => a && a.key === key); } catch (_e) { return false; }
    }
    const первое = (card, список, dir) => (список || []).find((x) => доступно(card, x.key, dir)) || (список || [])[0] || null;
    const тотЖе = (a, b) => !!a && !!b && a.key === b.key && канон(a.ввод || {}) === канон(b.ввод || {});
    function данныеСобытия(e, card, c, tz) {
      const now = сейчас();
      return { event: СОБЫТИЕ[e.вид], вид: e.вид, dir: c.dir, id: c.id, источник: 'watch', попыток: e.попыток, первая: e.first, сейчасМс: now,
        сейчас: сейчасГород(card.cityName || (c.cr && c.cr.city), tz), звонили: !!e.тихо,
        часовНаУточнении: e.since ? Math.floor((now - e.since) / ЧАС) : undefined };
    }
    function ctxПлана(c, card, tz, e) {
      return { dir: c.dir, источник: 'watch', сейчас: сейчасГород(card.cityName || (c.cr && c.cr.city), tz),
        ...(e && e.since ? { часовНаУточнении: Math.floor((сейчас() - e.since) / ЧАС) } : {}) };
    }
    function сПланом(p, card, c, tz, e) {
      p = { ...p, ввод: p.ввод || {}, можно: доступно(card, p.key, c.dir) };
      try { p.план = p.можно && typeof LC_ACT !== 'undefined' ? LC_ACT.план(p.key, card, p.ввод, ctxПлана(c, card, tz, e)) : null; } catch (_e) { p.план = null; }
      return p;
    }
    function предложить(e, card, c, tz) {
      const варианты = ПО_УМОЛЧАНИЮ[e.вид] ? ПО_УМОЛЧАНИЮ[e.вид](e) : [];
      const можно = new Set(варианты.map((x) => x.key));
      let p = null;
      try { if (typeof LC_ACT !== 'undefined' && LC_ACT.подсказка && СОБЫТИЕ[e.вид]) p = LC_ACT.подсказка('watch', card, данныеСобытия(e, card, c, tz)); } catch (_e) { p = null; }
      // вид события и сроки решает этот модуль: каталог предложил другое действие — берём своё по таблице; из его вариантов
      // (p и p.ещё) — тот, что совпал с нашим первым (например, 517 «НФ не акт», когда клиенту не звонили)
      const их = [p, ...((p && p.ещё) || [])].filter((x) => x && x.key && можно.has(x.key) && доступно(card, x.key, c.dir));
      const мой = варианты.find((x) => доступно(card, x.key, c.dir)) || null;
      let выбор = их.find((x) => тотЖе(x, мой)) || их[0] || мой || варианты[0] || null;
      if (!выбор) return null;
      if (выбор !== p) выбор = { ...выбор, почему: '' };
      return сПланом(выбор, card, c, tz, e);
    }
    // правила регламента без переписки: только ключи из П.правилаИзОпроса и только у созданных нами заявок
    function поПравилам(c, card, tz) {
      if (!c.создана || typeof LC_ACT === 'undefined' || typeof LC_ACT.подсказка !== 'function') return null;
      let p = null;
      try { p = LC_ACT.подсказка('rules', card, { dir: c.dir, id: c.id, источник: 'watch', сейчас: сейчасГород(card.cityName || (c.cr && c.cr.city), tz), клиентПишет: false }); } catch (_e) { p = null; }
      if (!p || !p.key || !П.правилаИзОпроса.includes(p.key) || !доступно(card, p.key, c.dir)) return null;
      return p;
    }

    /* ---------- уведомления ---------- */
    const ТЕКСТ_ВКЛАДКА = 'обновите ту вкладку (F5) после действия, иначе её «Сохранить» вернёт старое';
    async function вкладкаCRM(dir, id) {
      try {
        const r = await сроком(хост.send({ kind: 'lcz-act-tabs', args: { dir, id: String(id) } }), П.срокВкладок, null);
        return r && r.ok && r.open ? 'Заявка № ' + id + ' открыта во вкладке CRM — ' + ТЕКСТ_ВКЛАДКА : '';
      } catch (_e) { return ''; }
    }
    const номер = (c) => (ИМЯ[c.dir] || '') + ' № ' + c.id;
    const строка = (t, cls) => h('div', { class: 'tst-d' + (cls ? ' ' + cls : '') }, t);
    function превью(p) {
      const пл = p && p.план;
      if (!пл) return [];
      return [пл.title ? строка('Сделаю: ' + пл.title) : '',
        пл.crmConfirm ? строка('CRM: «' + пл.crmConfirm + '»', 'mut') : '',
        пл.tg && пл.tg.on && пл.tg.text ? строка('В чат: «' + String(пл.tg.text).slice(0, 160) + '»') : '',
        ...(пл.warnings || []).slice(0, 2).map((w) => строка('⚠ ' + w, 'warn'))];
    }
    // «Сделать» без карточки — только действие из короткого списка, план собран полностью и никуда, кроме CRM, не пишет
    // (Telegram и сообщение клиенту — только через карточку: там видно, куда и что уйдёт)
    function можноСразу(p) {
      const пл = p && p.план;
      if (!p || !p.можно || !пл || !П.сразу.includes(p.key) || !ui || typeof ui.исполнить !== 'function') return false;
      if (пл.error || пл.invalid || (Array.isArray(пл.missing) && пл.missing.length) || пл.ok === false) return false;
      // чат задан, а текст соберётся после CRM (строка «Переносов») — тоже Telegram: только через карточку
      if (пл.tg && пл.tg.on !== false && (пл.tg.text || пл.tg.kind || пл.tg.изCRM || пл.tg.послеCRM)) return false;
      return !(пл.client && пл.client.on);
    }
    const итогТекст = (r) => String((r && (r.text || r.итог || r.error)) || (r && r.ok ? 'Сделано' : 'Не сделано'));
    function открыть(c, card, key, ввод, el) {
      убрать(el);
      try { if (ui && ui.карточка) ui.карточка(c.conv, { ...(c.cr || {}), dir: c.dir, id: c.id }, key, ввод || {}, 'watch'); } catch (_e) { /* карточку покажет сетка */ }
    }
    // «Сделать» из уведомления: тот же бегунок, что и у карточки (замок, журнал, свежий снимок, sig, CRM → проверка → Telegram)
    async function сделать(b, c, card, p, e, el, итог) {
      if (b.disabled) return;                                          // двойной щелчок — одно действие
      b.disabled = true; b.textContent = 'Делаю…';
      if (!можноСразу(p)) { открыть(c, card, p.key, p.ввод, el); return; }
      for (const [п, x] of ТОСТЫ) if (x === el) ТОСТЫ.delete(п);            // это уведомление покажет итог — уборка его не трогает
      let r;
      try {
        r = await ui.исполнить({ conv: c.conv, cr: { ...(c.cr || {}), dir: c.dir, id: c.id }, key: p.key, ввод: p.ввод, snap: card, план: p.план,
          expectSig: card.sig, источник: 'watch' });
      } catch (err) { r = { ok: false, error: String((err && err.message) || err) }; }
      b.remove();                                                      // без повтора: снова — только через карточку с новым превью
      // 11: по строкам — не сделанное первым (⚠), сделанное — ✓
      итог.className = 'tst-d';
      итог.replaceChildren(...(Array.isArray(r && r.строки) && r.строки.length ? r.строки : [итогТекст(r)])
        .flatMap((t) => строкиИтога(h, t, !!(r && r.ok))).sort((a, b) => /warn/.test(b.className) - /warn/.test(a.className)));
      if (r && r.ok) {
        const после = r.after || r.после || null;
        await послеДействия({ conv: c.conv, cr: c.cr, dir: c.dir, id: c.id, key: p.key, ввод: p.ввод, ok: true, after: после });
        if (p.key === 'pz_take') тостПрозвонЗаМной(c, после || card);
        setTimeout(() => убрать(el), 20000);
      }
    }
    async function отметить(fn) { try { await изменить(fn); } catch (_e) { /* хранилище недоступно — решение оператора не потеряется в этой вкладке */ } }
    // «Позже»: через 15 мин — снова. Подсказку хоста опрос сам не найдёт — вернём её из памяти; снимок к тому времени устареет, прочтём заново (в бюджете)
    async function отложить(e) {
      ТОСТЫ.delete(e.показ); ПОВОД.delete(e.показ); ВНЕШНИЕ.delete(e.показ);
      if (e.o) ОТЛОЖЕНО.set(e.показ, { o: { ...e.o, card: null, snap: null, подсказка: e.p }, до: сейчас() + П.позже, с: сейчас(), k: e.k, key: e.p && e.p.key });
      await отметить((st) => { st.позже[e.ключ] = сейчас() + П.позже; delete st.показано[e.показ]; });
    }
    function кнопкиРешения(e, el) {
      return [h('button', { class: 'sm later', title: 'Напомнить через 15 минут', onclick: async () => { el.remove(); await отложить(e); } }, 'Позже'),
        h('button', { class: 'sm', title: 'Больше не напоминать об этом', onclick: async () => {
          el.remove(); ТОСТЫ.delete(e.показ); ПОВОД.delete(e.показ);
          await отметить((st) => { st.ненужно[e.ключ] = сейчас(); if (e.вид === 'mod_again' || e.вид === 'mod_final') delete st.напом[e.ключ]; });
        } }, 'Не нужно')];
    }
    // галочки — по именам: «Срочная ✓», «Прозвон ✗» (как кнопка сохранения в карточке)
    const ГАЛОЧКИ = { urgent: 'Срочная', callCheck: 'Прозвон', callBeforeVisit: 'Прозвон перед выездом', zakrep: 'Закреп', fback: 'Отзыв', farRide: 'Дальний выезд' };
    const метка = (p) => {
      if (p && p.label) return p.label;
      const г = p && p.key === 'flags' ? Object.keys(ГАЛОЧКИ).filter((x) => p.ввод && typeof p.ввод[x] === 'boolean').map((x) => ГАЛОЧКИ[x] + (p.ввод[x] ? ' ✓' : ' ✗')) : [];
      if (г.length) return г.join(', ');
      try { const d = typeof LC_ACT !== 'undefined' && LC_ACT.КАТАЛОГ && LC_ACT.КАТАЛОГ[p.key]; if (d && d.label) return d.label; } catch (_e) { /* без метки */ }
      return (p && p.key) || 'подсказка';
    };
    const ЗАГОЛОВОК = {
      mod_again: (e) => 'модерация: позвоните ещё раз (' + e.n + '/' + П.модПопыток + ')',
      mod_final: () => 'модерация: клиент не выходит на связь',
      pre_2h: () => 'на уточнении ' + сколько(Math.round(П.уточнениеЗвонок / МИН)) + ' — клиент не перезвонил, позвоните сами',
      pre_48h: () => 'на уточнении почти ' + (П.уточнениеСрок === 48 * ЧАС ? '2 суток' : сколько(Math.round(П.уточнениеСрок / МИН))) + ' — решите заявку',
      pz_call: (e) => 'время прозвона' + (e.время ? ' (' + e.время + ' по городу)' : ''),
      pz_held: () => 'заявка всё ещё за вами — вернуть?',
      rules: (e) => 'по регламенту: ' + метка(e.p),
      ai: (e) => 'клиент пишет: ' + метка(e.p),
    };
    const ПОЧЕМУ = {
      mod_again: (e) => (e.утро ? 'Ночью не звоним: по регламенту после 24:00 — в 8:00 и 10:00 по городу клиента.'
        : 'Клиент не ответил' + (e.last ? ' в ' + чч(e.last) : '') + '. Регламент: 5–6 звонков с интервалом 10–15 мин за 1–1,5 ч.'),
      mod_final: (e) => (e.попыток || 0) + ' звонк(а/ов) без ответа — по регламенту «Не оформлена», партнёру: «клиент не выходит на связь».',
      pre_2h: () => 'Регламент: клиент не перезванивает в течение 2 часов — обязательно звоним сами.',
      pre_48h: () => 'Заявка на уточнении должна быть решена за двое суток (просрочка — штраф 300 ₽). Не дозвонились — «НФ Не отвечает».',
      pz_call: () => 'Зелёная заявка: возьмите её в работу и позвоните клиенту.',
      pz_held: () => 'Взяли на прозвон ' + сколько(Math.round(П.держуБезДела / МИН)) + ' назад, дальше ничего не сделано — коллеги её не возьмут.',
      rules: (e) => (e.p && e.p.почему) || '',
      ai: (e) => (e.p && e.p.почему) || '',
    };
    async function показатьСобытие(e, c, card) {
      const tz = (КАРТЫ.get(c.k) || {}).tz || '';
      const p = e.p ? сПланом(e.p, card, c, tz, e) : предложить(e, card, c, tz);
      if (!p) return null;
      const вкладка = await вкладкаCRM(c.dir, c.id);
      const итог = строка(ПОЧЕМУ[e.вид](e) || p.почему || '');
      // подсказка каталога добавляет своё «почему», если оно не повторяет заголовок
      const ещё = p.почему && !e.p && !ЗАГОЛОВОК[e.вид](e).includes(p.почему) && !итог.textContent.includes(p.почему) ? строка(p.почему, 'mut') : '';
      let el = null;
      const надпись = { noanswer: 'Не ответил — отметить', pz_take: 'Взять прозвон', take: 'Взять в работу', pz_release: 'Вернуть', release: 'Вернуть' }[p.key] || 'Сделать';
      const кнопки = [];
      // «Сделать» — только там, где ввод не нужен (отметка «Не отвечает», взять/вернуть); смена статуса — через карточку
      if (можноСразу(p)) кнопки.push(h('button', { class: 'sm pri', onclick: (ev) => сделать(ev.currentTarget, c, card, p, e, el, итог) }, (p.план && p.план.button) || надпись));
      else if (p.key === 'noanswer' && (e.вид === 'mod_again' || e.вид === 'pre_2h')) {
        // кнопки «Не отвечает» у заявки нет (не во всех базах) — звонок считаем сами, в CRM ничего не пишем
        кнопки.push(h('button', { class: 'sm pri', title: 'Отметить звонок только в расширении (в CRM ничего не пишется)', onclick: async () => {
          убрать(el); ТОСТЫ.delete(e.показ); ПОВОД.delete(e.показ);
          await послеДействия({ conv: c.conv, cr: c.cr, dir: c.dir, id: c.id, key: 'noanswer', ok: true, after: card, безCRM: true });
        } }, 'Не ответил'));
      }
      if (e.вид === 'mod_again') кнопки.push(h('button', { class: 'sm', onclick: async () => {
        await отметить((st) => { delete st.напом[c.k + '|mod']; });          // дозвонились — серия звонков закончена
        открыть(c, card, первое(card, [{ key: 'mod_save' }, { key: 'take' }], c.dir).key, {}, el);
      } }, 'Дозвонился'));
      else if (e.вид === 'pre_2h') кнопки.push(h('button', { class: 'sm', onclick: () => открыть(c, card, первое(card, [{ key: 'precheck_await' }, { key: 'move' }], c.dir).key, {}, el) }, 'Дозвонился'));
      else кнопки.push(h('button', { class: 'sm' + (кнопки.length ? '' : ' pri'), onclick: () => открыть(c, card, p.key, p.ввод, el) }, 'Открыть'));
      // 2.1: напоминание (позвонить сейчас, ещё раз, заявка за вами, срок регламента на исходе) — «Нужно действие» (warn, «пора»);
      // подсказка ИИ / правил — сведения (info)
      el = хост.тост({ kind: e.вид === 'ai' || e.вид === 'rules' ? 'info' : 'warn', due: e.вид !== 'ai' && e.вид !== 'rules',
        label: e.вид === 'ai' || e.вид === 'rules' ? 'Подсказка' : 'Напоминание',
        title: номер(c) + ' · ' + ЗАГОЛОВОК[e.вид](e) + кто(c),
        lines: [итог, ещё, ...превью(p),
          e.вид === 'mod_again' && !p.можно ? строка('Кнопки «Не отвечает» у заявки нет — отметьте звонок в CRM вручную', 'mut') : '',
          вкладка ? строка('⚠ ' + вкладка, 'warn') : ''],
        actions: кнопки.concat(кнопкиРешения(e, { remove: () => убрать(el) })) });
      if (el) ПОВОД.set(e.показ, e);
      return el;
    }
    // после «Взять прозвон»: дальше — договорились / не ответил / вернуть
    function тостПрозвонЗаМной(c, card) {
      let el = null;
      const итог = строка('Позвоните клиенту и выберите итог.');
      const p = сПланом({ key: 'pz_release', ввод: {} }, card, c, (КАРТЫ.get(c.k) || {}).tz || '');
      el = хост.тост({ kind: 'warn', due: true, label: 'Прозвон', title: номер(c) + ' · прозвон за вами' + кто(c), lines: [итог],
        actions: [h('button', { class: 'sm pri', onclick: () => открыть(c, card, 'pz_agreed', {}, el) }, 'Договорились'),
          h('button', { class: 'sm', onclick: () => открыть(c, card, 'pz_noanswer', {}, el) }, 'Не ответил'),
          можноСразу(p)
            ? h('button', { class: 'sm', onclick: (ev) => сделать(ev.currentTarget, c, card, p, { вид: 'pz_after' }, el, итог) }, 'Вернуть')
            : h('button', { class: 'sm', onclick: () => открыть(c, card, 'pz_release', {}, el) }, 'Вернуть')] });
      ТОСТЫ.set(c.k + '|pzafter', el);
      return el;
    }
    // статус сменили в CRM не через расширение — тихо, без кнопок, само уходит через 12 с (в «Пропущено»)
    const СТАЛИ_ГОТОВЫ = { el: null, список: [] };
    function тостСтатус(c, было, card) {
      const стала = номер(c) + ' стала «' + (card.statusName || ЧУЖИЕ[код(card)] || 'другой статус') + '»' + кто(c);
      if (код(card) === 128 || код(card) === 1020) return тостГотовы(c, стала);
      const el = хост.тост({ kind: 'info', low: true, жить: 12e3, label: 'Заявка', title: стала,
        lines: [строка((было ? 'Было «' + было + '». ' : '') + 'Статус сменили в CRM не через расширение.', 'mut')], actions: [] });
      ТОСТЫ.set(c.k + '|st' + код(card), el);
      return el;
    }
    // 10: «Готов» / «Готов ОФ» — одним уведомлением «Статусы сменились (N)», новое дописывается в то же
    function тостГотовы(c, стала) {
      const Г = СТАЛИ_ГОТОВЫ, живо = !!(Г.el && Г.el.isConnected);
      Г.список = (живо ? Г.список.filter((x) => x.k !== c.k) : []).concat({ k: c.k, t: стала }).slice(-8);
      const title = 'Статусы сменились (' + Г.список.length + ')';
      const строки = () => Г.список.map((x) => h('div', {}, x.t));
      if (живо) {
        const t = Г.el.querySelector('.tst-t'), я = Г.el.querySelector('[data-st]');
        if (t) t.textContent = title;
        if (я) я.replaceChildren(...строки());
        if (typeof хост.вСтопку === 'function') хост.вСтопку(Г.el);
        return Г.el;
      }
      Г.el = хост.тост({ kind: 'info', low: true, жить: 12e3, label: 'Заявки', title,
        lines: [h('div', { class: 'tst-d mut', 'data-st': '1' }, ...строки()), строка('Статус сменили в CRM не через расширение.', 'mut')], actions: [] });
      return Г.el;
    }

    /* ---------- чтение карточки CRM в бюджете ---------- */
    const сессия = (r) => !!(r && (r.session || r.code === 'session' || /сесси|войдите|login/i.test(String(r.error || ''))));
    // место в бюджете резервируем под замком ДО запроса: два вызова (опрос и подсказка) не превысят 20 за 5 мин.
    // И саму заявку (читаю[k], общее для вкладок): прежняя ведущая ещё ждёт ответа CRM, новая ту же заявку второй раз не прочтёт
    function резерв(ks) {
      return изменить((x) => {
        const now = сейчас(), out = [];
        if (x.пауза > now) return { ks: out, t: now };
        let место = П.всегоЗаОкно - x.чтения.filter((t) => now - t < П.окно).length;
        for (const k of ks) {
          if (место <= 0) break;
          if (now - (x.читаю[k] || 0) < П.наЗаявку) continue;
          x.читаю[k] = now; x.чтения.push(now); out.push(k); место--;
        }
        return { ks: out, t: now };
      }).then((r) => (r && typeof r === 'object' && Array.isArray(r.ks) ? r : { ks: [], t: 0 }));
    }
    // не использовали зарезервированное (вкладку скрыли, сессия) — возвращаем в бюджет и отпускаем заявку
    const вернуть = (x, t, ks) => {
      for (const k of ks) {
        const j = x.чтения.lastIndexOf(t); if (j >= 0) x.чтения.splice(j, 1);
        if (x.читаю[k] === t) delete x.читаю[k];
      }
    };
    const рано = (k, st, now) => now - ((st.снимки[k] || {}).at || 0) < П.наЗаявку || now - (ЧИТАЮ.get(k) || 0) < П.наЗаявку;
    async function прочестьКарту(c) {
      ЧИТАЮ.set(c.k, сейчас());
      let r;
      try { r = await сроком(хост.send({ kind: 'lcz-crm', op: 'snap', args: { dir: c.dir, id: c.id } }), П.срокЧтения, { ok: false, error: 'CRM не ответила' }); }
      catch (err) { r = { ok: false, error: String((err && err.message) || err) }; }
      if (сессия(r)) return { сессия: true, card: null };
      // статус не распознан (код 0 / нет) — это сбой чтения, а не «статус сменился»: иначе напоминания (модерация, уточнение, прозвон) пропали бы
      const card = r && r.ok && r.card && Number(r.card.statusCode) > 0 ? r.card : null;
      if (card) КАРТЫ.set(c.k, { card, at: сейчас(), tz: await пояс(c.conv) });
      return { card };
    }
    // одна карточка вне опроса (подсказка из переписки): только видимая вкладка, в общем бюджете
    async function снятьОдну(c) {
      if (!видна()) return null;
      const now = сейчас(), было = ЧИТАЮ.get(c.k);
      if (now - (было || 0) < П.наЗаявку) return null;
      ЧИТАЮ.set(c.k, now);                                             // заняли заявку сразу, до первого await: опрос её не прочтёт параллельно
      const отказ = () => { if (ЧИТАЮ.get(c.k) === now) { if (было) ЧИТАЮ.set(c.k, было); else ЧИТАЮ.delete(c.k); } return null; };
      if (now - (((await прочитать()).снимки[c.k] || {}).at || 0) < П.наЗаявку) return отказ();   // опрос снимал её меньше 5 мин назад
      const рез = await резерв([c.k]);
      if (!рез.ks.length) return отказ();
      const r = await прочестьКарту(c);
      await изменить((x) => {
        if (r.сессия) x.пауза = сейчас() + П.пауза;
        if (r.card) x.снимки[c.k] = кратко(r.card, сейчас());
      });
      return r.card;
    }

    /* ---------- один проход ---------- */
    async function проход() {
      const now = сейчас();
      let st = await прочитать();
      if (st.пауза > now) return;
      await изЖурнала(now);                                            // что нажали в других вкладках — до выбора, кого читать
      st = await прочитать();
      const created = (await хост.store.get('created', {})) || {};
      const все = кандидаты(created, st, now);
      const нужно = все.map((c) => ({ c, t: когдаСнять(c, st, now) }))
        .filter((x) => x.t <= now && !рано(x.c.k, st, now))
        .sort((a, b) => a.t - b.t || b.c.напом.length - a.c.напом.length);
      const рез = нужно.length ? await резерв(нужно.map((x) => x.c.k)) : { ks: [], t: 0 };
      const мои = new Set(рез.ks);
      const снято = [];
      let пауза = 0;
      for (const { c } of нужно.filter((x) => мои.has(x.c.k))) {
        if (!видна()) break;                                           // ушли из вкладки — дальше не читаем
        if (сейчас() - (ЧИТАЮ.get(c.k) || 0) < П.наЗаявку) continue;  // пока ждали, её прочла подсказка — место вернём в бюджет
        const r = await прочестьКарту(c);
        if (r.сессия) { пауза = сейчас() + П.пауза; снято.push({ c, card: null }); break; }
        снято.push({ c, card: r.card });
      }
      // смена статуса — сравниваем с прошлым снимком (первый снимок — только точка отсчёта)
      const статусы = [];
      // пока читали, вкладку скрыли — снимки сохраняем, а напоминаний не показываем и «показано» не ставим: покажет видимая вкладка
      // (тихое «статус сменился» остаётся здесь: снимок уже новый, второй раз его не узнать)
      const наВиду = () => видна();
      st = await изменить((x) => {
        const прочтены = new Set(снято.map((y) => y.c.k));
        вернуть(x, рез.t, рез.ks.filter((k) => !прочтены.has(k)));
        if (пауза) x.пауза = пауза;
        for (const { c, card } of снято) {
          const прежний = x.снимки[c.k];
          if (!card) { x.снимки[c.k] = { ...(прежний || {}), at: сейчас(), сбой: ((прежний && прежний.сбой) || 0) + 1 }; continue; }
          const s = кратко(card, сейчас());
          // статус сменился между прошлым снимком и этим; мы в это время что-то делали с заявкой — значит, это наше
          const наше = !!(x.наши[c.k] && прежний && x.наши[c.k].at >= (прежний.at || 0) - МИН);
          if (прежний && прежний.code && прежний.code !== s.code && ЧУЖИЕ[s.code] && !наше && !x.показано[c.k + '|st' + s.code]) {
            x.показано[c.k + '|st' + s.code] = сейчас();
            статусы.push({ c, было: прежний.name, card });
          }
          // «Не отвечает» нажали прямо в CRM у заявки в модерации — та же серия звонков, что и из расширения
          if (s.code === 2 && прежний && прежний.code === 2 && !прежний.сбой && s.na > (прежний.na || 0) && !x.напом[c.k + '|mod']) {
            const r = { вид: 'mod', k: c.k, dir: c.dir, id: c.id, conv: c.conv, cr: { dir: c.dir, id: c.id, url: (c.cr && c.cr.url) || '', city: (c.cr && c.cr.city) || '' },
              first: сейчас(), tries: 0, утро: 0, na0: прежний.na || 0 };
            const мин = местныеМин(card.cityName || (c.cr && c.cr.city), (КАРТЫ.get(c.k) || {}).tz || '');
            for (let i = 0; i < s.na - (прежний.na || 0); i++) попытка(r, сейчас(), мин);
            x.напом[c.k + '|mod'] = r;
            delete x.ненужно[c.k + '|mod'];
          }
          // «На уточнении», созданная нами: с какого момента считать 2 ч / 48 ч
          if (s.code === 3 && c.создана && !x.напом[c.k + '|pre']) {
            x.напом[c.k + '|pre'] = { вид: 'pre', k: c.k, dir: c.dir, id: c.id, conv: c.conv, cr: { dir: c.dir, id: c.id, url: c.cr.url || '', city: c.cr.city || '' },
              since: !прежний || прежний.code === 3 ? (c.cr.at || сейчас()) : сейчас(), tries: 0 };
          }
          x.снимки[c.k] = s;
        }
      });
      статусы.forEach((x) => тостСтатус(x.c, x.было, x.card));
      // напоминания — по снимку не старше 5 мин
      const n2 = сейчас();
      const показать = [], правки = [], активные = new Set(), проверены = new Set();
      for (const c of кандидаты(created, st, n2)) {
        const m = КАРТЫ.get(c.k);
        if (!m || n2 - m.at > П.свежесть) continue;
        const { out, изм } = события(c, m.card, st, n2, m.tz);
        правки.push(...изм);
        проверены.add(c.k);
        for (const e of out) {
          активные.add(e.показ);
          if (st.показано[e.показ] || (st.позже[e.ключ] || 0) > n2 || st.ненужно[e.ключ] || !наВиду()) continue;
          показать.push({ e, c, card: m.card });
        }
      }
      if (правки.length || показать.length) {
        st = await изменить((x) => {
          правки.forEach((f) => f(x));
          for (const { e } of показать) x.показано[e.показ] = сейчас();
        });
      }
      for (const { e, c, card } of показать) {
        if (ТОСТЫ.has(e.показ)) continue;
        // то же напоминание, закрытое раньше (лежит в «Пропущено»), — убираем оттуда: на экране будет свежее
        for (const [p, x] of ВЫТЕСНЕНЫ) if (x.e.ключ === e.ключ) { убрать(x.el); ВЫТЕСНЕНЫ.delete(p); }
        const el = await показатьСобытие(e, c, card);
        if (el) ТОСТЫ.set(e.показ, el);
      }
      await уборка(проверены, активные);
    }
    // повода больше нет (статус сменился, взял другой, серию сняли) — уведомление не к месту. Закрыли × или вытеснили другие —
    // это «Позже» (15 мин, под замком), а не «показано навсегда»; вернули из «Пропущено» раньше срока — снова на экране, «Позже» снят
    async function уборка(проверены, активные) {
      for (const [p, el] of ТОСТЫ) {
        const k = p.split('|')[0];
        const ещё = p.includes('|st') || ВНЕШНИЕ.has(p) || p.endsWith('|pzafter') || !проверены.has(k) || активные.has(p);
        if (!ещё) { убрать(el); ТОСТЫ.delete(p); ВНЕШНИЕ.delete(p); ПОВОД.delete(p); continue; }
        if (!el || el.isConnected !== false) continue;
        const e = ПОВОД.get(p);
        ТОСТЫ.delete(p); ВНЕШНИЕ.delete(p); ПОВОД.delete(p);
        if (e && !НАШИ.has(el)) { ВЫТЕСНЕНЫ.set(p, { el, e }); await отложить(e); }
      }
      for (const [p, x] of ВЫТЕСНЕНЫ) {
        const k = p.split('|')[0];
        if (!x.e.o && проверены.has(k) && !активные.has(p)) { убрать(x.el); ВЫТЕСНЕНЫ.delete(p); continue; }   // повода больше нет
        if (!x.el.isConnected) continue;
        ВЫТЕСНЕНЫ.delete(p); ТОСТЫ.set(p, x.el); ПОВОД.set(p, x.e);
        if (x.e.o && x.e.p) ВНЕШНИЕ.set(p, x.e.p.key);
        ОТЛОЖЕНО.delete(p);
        await отметить((st) => { delete st.позже[x.e.ключ]; st.показано[x.e.показ] = сейчас(); });
      }
    }
    async function тик() {
      if (идёт) return;
      идёт = true;
      try {
        if (!видна()) return;                                          // в фоне CRM не читаем
        if (!(await хост.ведущая())) return;                           // смотрит одна вкладка на браузер
        await отложенные();
        await проход();
      } catch (_e) { /* расширение обновили / хранилище недоступно — в следующий раз */ }
      finally { идёт = false; }
    }

    /* ---------- 4.1–4.2: подсказка уведомлением, когда карточки заявки на экране нет ----------
       o = {conv, cr:{dir,id,city,url}, источник:'ai'|'rules', данные (ответ additionParse и т. п.), card? (снимок, если уже есть), подсказка? (готовая)}.
       Ничего не делает сама: уведомление с «Сделать» (короткий список, без Telegram) / «Открыть» / «Позже» / «Не нужно» */
    // «Позже» прошло — показать снова; не вышло (бюджет чтений, вкладка в фоне) — ещё раз через 5 мин, но не дольше 2 ч
    async function отложенные() {
      const now = сейчас();
      for (const [п, x] of [...ОТЛОЖЕНО]) {
        if (x.до > now) continue;
        ОТЛОЖЕНО.delete(п);
        const r = await подсказать(x.o);
        if (r && !r.ok && /карточка|вкладка/.test(String(r.why || '')) && now - x.с < 2 * ЧАС) ОТЛОЖЕНО.set(п, { ...x, до: now + П.наЗаявку });
      }
    }
    async function подсказать(o) {
      try {
        o = o || {};
        const cr = o.cr || {}, dir = cr.dir, id = String(cr.id || '');
        if (!ИМЯ[dir] || !/^\d{1,12}$/.test(id)) return { ok: false, why: 'нет заявки' };
        if (!видна()) return { ok: false, why: 'вкладка в фоне' };       // уведомление в скрытой вкладке никто не увидит, а «показано» запомнится
        const k = кл(dir, id), c = { k, dir, id, conv: o.conv || '', cr: { ...cr, dir, id }, создана: false, напом: [] };
        const tz = await пояс(c.conv);
        let card = o.card || o.snap || null;
        if (!card) { const m = КАРТЫ.get(k); if (m && сейчас() - m.at <= П.свежесть) card = m.card; }
        if (!card) card = await снятьОдну(c);
        if (!card) return { ok: false, why: 'карточка CRM не прочитана (бюджет чтений, сессия или вкладка в фоне)' };
        if (o.card || o.snap) КАРТЫ.set(k, { card, at: сейчас(), tz });
        const источник = o.источник === 'rules' ? 'rules' : 'ai';
        let p = o.подсказка || null;
        if (!p) {
          try { p = typeof LC_ACT !== 'undefined' && LC_ACT.подсказка ? LC_ACT.подсказка(источник, card, { сейчас: сейчасГород(card.cityName || cr.city, tz), ...(o.данные || {}), dir, id }) : null; }
          catch (_e) { p = null; }
        }
        if (!p || !p.key) return { ok: false, why: 'подсказки нет' };
        const ключ = k + '|' + источник + ':' + p.key + ':' + хэш(канон(p.ввод || {}));
        const метка0 = o.данные && (o.данные.seen || o.данные.msg);
        const показ = ключ + (метка0 ? '@' + хэш(String(метка0)) : '');   // хэшем: в «msg» может прийти и текст клиента — в хранилище его не кладём
        const st = await прочитать(), now = сейчас();
        // та же подсказка уже на экране (по другому сообщению или вернулась после «Позже») — второе уведомление не нужно
        const наЭкране = [...ТОСТЫ].some(([п, el]) => (п === ключ || п.startsWith(ключ + '@')) && !(el && el.isConnected === false));
        if (st.ненужно[ключ] || (st.позже[ключ] || 0) > now || st.показано[показ] || наЭкране) return { ok: false, why: 'уже показано или «Позже» / «Не нужно»' };
        await отметить((x) => { x.показано[показ] = now; });
        for (const [п, x] of ВЫТЕСНЕНЫ) if (x.e.ключ === ключ) { убрать(x.el); ВЫТЕСНЕНЫ.delete(п); }
        const el = await показатьСобытие({ вид: источник, ключ, показ, p, o, k }, c, card);
        if (el) { ТОСТЫ.set(показ, el); ВНЕШНИЕ.set(показ, p.key); }
        return { ok: !!el };
      } catch (e) { return { ok: false, why: String((e && e.message) || e) }; }
    }

    /* ---------- бейдж «опаздывает N мин» для сетки действий (без уведомления, пока клиент не написал) ---------- */
    function бейдж(a, b) {
      const card = a && typeof a === 'object' ? a : ((КАРТЫ.get(кл(a, b)) || {}).card || null);
      const tz = a && typeof a === 'object' ? (typeof b === 'string' ? b : '') : ((КАРТЫ.get(кл(a, b)) || {}).tz || '');
      if (!card || !(код(card) === 1 || код(card) === 4) || !card.visitTime || (card.flags && card.flags.callCheck)) return null;
      const x = поГороду(card.cityName, card.visitDate, card.visitTime, tz);
      if (x.late === null || x.late === undefined || x.late <= П.опоздание) return null;
      return { мин: x.late, текст: 'опаздывает ' + сколько(x.late), первой: 'where' };
    }

    function старт() {
      if (живо) return;
      живо = true;
      const цикл = () => { if (!живо) return; тик().finally(() => { if (живо) таймер = setTimeout(цикл, П.тик); }); };
      таймер = setTimeout(цикл, 5000);
      if (typeof document !== 'undefined') document.addEventListener('visibilitychange', () => { if (живо && видна()) setTimeout(() => тик(), 2000); });
    }
    function стоп() { живо = false; if (таймер) clearTimeout(таймер); таймер = null; }

    const api = { старт, стоп, тик, послеДействия, подсказать, бейдж, вкладкаCRM, П };
    // бегунку (actions-ui.js) — сообщить о сделанном, сетке — бейдж: через хост или подписку, что найдётся
    if (хост && !хост.послеДействия) хост.послеДействия = послеДействия;
    if (хост && !хост.watch) хост.watch = api;
    try { if (ui && typeof ui.подписаться === 'function') ui.подписаться(послеДействия); } catch (_e) { /* нет подписки — хватит журнала */ }
    if (!опц.безСтарта) старт();                                       // в тестах часы и проходы — свои
    return api;
  }
  return { создать, П: П0, сПорогами, пора, строкиИтога };
})();
if (typeof module !== 'undefined' && module.exports) module.exports = LC_ACT_WATCH;
