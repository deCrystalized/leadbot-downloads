/* Заявка в CRM лид-центра — механика расширения «Лид-бот → Заявки» (её проверенные приёмы
   перенесены сюда без изменений): GET формы создания → ставим только свои поля → отправляем
   ВСЮ форму с save_close. Работает рабочей сессией оператора (cookie сайта лид-центра).
   Отличие: шаг prepare — заранее открыть форму и показать оператору, что будет выбрано
   (город, вид работ, вид услуг, тип), и есть ли у клиента живая заявка. */

const CRM = (() => {
  const NOTES = typeof LC_REQUEST_NOTES !== 'undefined' ? LC_REQUEST_NOTES : require('./request-notes.js');
  const ВЕРСИЯ = (typeof chrome !== 'undefined' && chrome.runtime && chrome.runtime.getManifest) ? chrome.runtime.getManifest().version : '';
  const BASES = {
    bt: 'https://bt-lead-centre.ru',
    kp: 'https://kp-lead-centre.ru',
    mnc: 'https://mnc-lead-centre.ru',
  };
  const CREATE = '/admin/domain/customer-request/create';
  const ИМЯ = { mnc: 'МНЧ', kp: 'КП', bt: 'БТ' };
  // база по адресу («https://kp-lead-centre.ru/…» → «КП») — для текстов ошибок
  const имяПоАдресу = (url) => ИМЯ[Object.keys(BASES).find((k) => String(url || '').startsWith(BASES[k]))] || '';
  /* вход в CRM истёк — один текст везде (что открыть и что потом сделать) */
  const СЕССИЯ = (б) => 'Сессия в CRM ' + (б ? б + ' ' : '') + 'истекла — откройте сайт лид-центра' + (б ? ' ' + б : '') + ', войдите и нажмите ещё раз';
  // суть ошибки для скобок «(…)» в составных текстах: у обрыва связи — исходное «Failed to fetch», без нашей подсказки
  const суть = (e) => String((e && (e.кратко || e.message)) || e || 'ошибка');
  const norm = (s) => (s || '').toLowerCase().replace(/ё/g, 'е').trim();

  /* Совпадение с начала слова: «кран» не находится внутри «экрана» */
  function начинаетсяСоСлова(текст, основа) {
    let i = текст.indexOf(основа);
    while (i >= 0) {
      const слева = i > 0 ? текст[i - 1] : '';
      if (!слева || !/[a-zа-яё]/.test(слева)) return true;
      i = текст.indexOf(основа, i + 1);
    }
    return false;
  }

  /* Клиент и справочник CRM говорят разными словами. Синонимы — после самой темы, до «прочей».
     Первое подходящее правило решает, поэтому бытовая техника — раньше электрики и мебели («духовой шкаф»,
     «электроплита», «стиральная машина автомат»), а короткие корни — с начала слова (Б — граница слова,
     \b кириллицу не видит): «столько» — не стол, «подушка» — не душ, «плитку положить» — не плита,
     «трубка домофона» — не труба, «диванные» — не ванна. */
  const Б = '(?:^|[^а-яё])';
  const СИНОНИМЫ = [
    [/^телевизор|^телек|^тв$|плазм|кинескоп|кронштейн/i, ['жк тв', 'тв', 'телевиз', 'навес']],
    [/^ноутбук|^компьютер|^пк$|моноблок|систем.?ник|материнск|виндовс|windows|винд/i, ['компьютер', 'ноутбук', 'моноблок']],
    [/^принтер|^мфу|печат|картридж/i, ['принтер', 'мфу']],
    [/^смартфон|^телефон|^айфон|^планшет/i, ['смартфон', 'планшет']],
    [/^роутер|вай.?фай|wi.?fi|^интернет/i, ['роутер', 'обжим']],
    [/^монитор|видеокарт/i, ['монитор', 'видеокарт']],
    [/пристав|playstation|^ps[0-9]?$|xbox|nintendo|steam/i, ['playstation', 'xbox', 'nintendo', 'steam']],
    [/жестк.?диск|флеш|восстанов.*(информ|данн)|^ssd$|^hdd$/i, ['восстановление информации', 'восстановление']],
    [new RegExp('смесител|' + Б + 'кран|унитаз|раковин|засор|канализ|' + Б + 'труб(?:а|ы|у|е|ой|ами|ах)?(?![а-яё])|трубопровод|бойлер|водонагрев|сифон|'
      + Б + 'ванн|' + Б + 'душ(?![а-яё])|душев|инсталляц|полотенцесуш|счетчик\\S*\\s+(?:\\S+\\s+)?вод|водосчетчик', 'i'), ['сантехн']],
    // бытовая техника — по прибору: на МНЧ «Подключение бытовой техники», на БТ — вид работ этого прибора
    // (электроплита — «Духовки/…/Электроплиты», вытяжка — «Вытяжки», микроволновка — «Прочая»), а не «Стиральные машины» для всех
    [new RegExp('духов|варочн|электроплит|' + Б + 'плит(?:а|ы|у|е|ой)?(?![а-яё])', 'i'), ['подключение бытовой', 'бытов', 'духов', 'электроплит']],
    [/вытяжк/i, ['подключение бытовой', 'бытов', 'вытяжк']],
    [/холодильн|морозильн/i, ['подключение бытовой', 'бытов', 'холодильн', 'морозил']],
    [/посудомо/i, ['подключение бытовой', 'бытов', 'посудомо']],
    [/стиральн|сушильн/i, ['подключение бытовой', 'бытов', 'стиральн']],
    [/микроволн/i, ['подключение бытовой', 'бытов']],
    [/розетк|выключател|люстр|светильн|проводк|электр|автомат|счетчик|счётчик|лампочк|бра$/i, ['электр', 'светильн', 'люстр']],
    [new RegExp('шкаф|' + Б + 'кроват|кухн|мебел|комод|' + Б + '(?:стол|стул)(?:а|у|ы|ом|е|ов|ья|ьев|ик|ики|ешниц[аеуы]?)?(?![а-яё])|диван|тумб|гардероб', 'i'), ['мебел', 'сборк']],
    [/полк|карниз|зеркал|картин|штор|гардин|вешал|сушилк/i, ['навес', 'мелкий', 'муж на час', 'мастер на час']],
    [/двер|замок|замк|ручк/i, ['двер', 'замк']],
    [/кондиционер|сплит/i, ['кондиц']],
  ];
  function синонимыТемы(тема) {
    const t = norm(тема);
    if (!t) return [];
    for (const [rx, варианты] of СИНОНИМЫ) if (rx.test(t)) return варианты;
    return [];
  }

  function pickOption(select, ...wanted) {
    if (!select) return '';
    for (const w of wanted) {
      const wl = norm(w);
      if (!wl) continue;
      for (const o of select.options || select.querySelectorAll('option')) {
        if (o.value && начинаетсяСоСлова(norm(o.textContent), wl)) return o.value;
      }
    }
    return '';
  }

  /* Город: сначала точное название («Иркутск»), потом начало («Иркутск 2»), и только в крайнем случае — в скобках:
     «Ангарск (Иркутск)» — это Ангарск, а не Иркутск, хотя в списке он раньше.
     Закрытый филиал («Домодедово -»: минус в конце — филиал закрыт) сам не выбираем; закрытые=true — ищем только среди них */
  const закрытый = (t) => /\S\s*[-–—]\s*$/.test(String(t || '').trim());
  function pickCity(select, wanted, закрытые) {
    const безСкобок = (s) => norm(s).replace(/\s*\(.*?\)\s*/g, ' ').replace(/[\s\-–—]+$/, '').replace(/\s+/g, ' ').trim();
    const wl = безСкобок(wanted);
    if (!select || !wl) return '';
    const opts = [...(select.options || select.querySelectorAll('option'))].filter((o) => o.value && закрытый(o.textContent) === !!закрытые);
    const o = opts.find((x) => norm(x.textContent) === norm(wanted)) || opts.find((x) => безСкобок(x.textContent) === wl)
      || opts.find((x) => безСкобок(x.textContent).startsWith(wl) && !/[a-zа-яё]/.test(безСкобок(x.textContent)[wl.length] || ''))
      || opts.find((x) => начинаетсяСоСлова(безСкобок(x.textContent), wl)) || opts.find((x) => начинаетсяСоСлова(norm(x.textContent), wl))
      // «protvino» или транслит «Брацк» — по скелету звучания («Протвино», «Братск»)
      || (скелет(wanted).length >= 4 && opts.find((x) => скелет(x.textContent) === скелет(wanted)));
    return o ? o.value : '';
  }
  const В_ЛАТ = { а: 'a', б: 'b', в: 'v', г: 'g', д: 'd', е: 'e', ё: 'e', ж: 'zh', з: 'z', и: 'i', й: 'y', к: 'k', л: 'l', м: 'm', н: 'n',
    о: 'o', п: 'p', р: 'r', с: 's', т: 't', у: 'u', ф: 'f', х: 'h', ц: 'ts', ч: 'ch', ш: 'sh', щ: 'sch', ъ: '', ы: 'y', ь: '', э: 'e', ю: 'yu', я: 'ya' };
  const скелет = (s) => String(s || '').toLowerCase().replace(/\s*\(.*?\)\s*/g, ' ').replace(/[а-яё]/g, (c) => В_ЛАТ[c])
    .replace(/kh/g, 'h').replace(/shch/g, 'sch').replace(/tz|ts/g, 'c').replace(/[jy]/g, 'i').replace(/w/g, 'v').replace(/[^a-z0-9]/g, '').replace(/i+/g, 'i');

  /* Номер партнёра — числом: «007» = «7», а «_197» ≠ «7» */
  function pickNumber(select, номер) {
    if (!select) return '';
    const n = String(номер || '').replace(/\D/g, '').replace(/^0+/, '');
    if (!n) return '';
    for (const o of select.options || select.querySelectorAll('option')) {
      if (!o.value) continue;
      const ц = (o.textContent || '').replace(/\D/g, '').replace(/^0+/, '');
      if (ц && ц === n) return o.value;
    }
    return '';
  }

  const опции = (sel) => (sel ? [...sel.querySelectorAll('option')] : [])
    .filter((o) => o.value).map((o) => ({ id: o.value, text: (o.textContent || '').trim() }));

  /* Запрос как у jQuery .load на странице CRM: без заголовка X-Requested-With сервер отдаёт всю страницу, а не список */
  const AJAX = { 'X-Requested-With': 'XMLHttpRequest', Accept: 'text/html, */*; q=0.01' };
  /* БЕЗ ЗАВИСАНИЙ — только для ЧТЕНИЯ (GET): страница CRM не пришла за 15 с (ни ответ, ни его тело) — ошибка, а не вечное ожидание.
     Отправку (создание, сохранение, перенос, отмена, претензия) сроком НЕ ограничиваем: CRM могла заявку уже создать —
     повтор по сроку дал бы вторую. Возвращает ответ с уже прочитанным текстом (status, ok, url, text()) */
  async function getСрок(url, init, мс = 15000) {
    const ctl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    const ошибка = () => new Error('CRM не ответила за ' + Math.round(мс / 1000) + ' с');
    let t = 0;
    const срок = new Promise((_, rej) => { t = setTimeout(() => { if (ctl) ctl.abort(); rej(ошибка()); }, мс); });
    срок.catch(() => {});
    try {
      const r = await Promise.race([fetch(url, ctl ? { ...(init || {}), signal: ctl.signal } : init), срок]);
      const text = await Promise.race([r.text(), срок]);
      return { status: r.status, ok: r.ok, url: r.url, headers: r.headers, text: async () => text };
    } catch (e) {
      if (e && e.name === 'AbortError') throw ошибка();
      // fetch не дошёл до CRM (нет сети, сайт недоступен) — TypeError «Failed to fetch»: понятный текст, слово «Failed to fetch»
      // остаётся (по нему экран узнаёт обрыв связи)
      if (e && e.name === 'TypeError') {
        const б = имяПоАдресу(url);
        throw Object.assign(new Error('нет связи с CRM' + (б ? ' ' + б : '') + ' (' + String(e.message || 'Failed to fetch') + ') — проверьте интернет и нажмите ещё раз'), { кратко: String(e.message || 'Failed to fetch') });
      }
      throw e;
    } finally { clearTimeout(t); }
  }
  async function getAjax(url) {
    const r = await getСрок(url, { credentials: 'include', headers: AJAX });
    const text = await r.text();
    return { status: r.status, text };
  }
  /* Ответ — список <option> или (если сервер всё же отдал страницу) поле name в этой странице */
  function опцииОтвета(text, name) {
    const t = String(text || '');
    if (/<html|<body|<form/i.test(t)) {
      const d = new DOMParser().parseFromString(t, 'text/html');
      const el = d.querySelector('select[name="' + name + '"]');
      return el ? опции(el).filter((o) => /^\d+$/.test(o.id)) : [];
    }
    return разобратьСписок(t);
  }
  const кратко = (r) => r ? 'HTTP ' + r.status + ', ' + (/<html|<body/i.test(r.text) ? 'вся страница' : (r.text.match(/<option/gi) || []).length + ' вариантов') : 'нет ответа';

  async function fetchDoc(url) {
    const r = await getСрок(url, { credentials: 'include' });
    const text = await r.text();
    const doc = new DOMParser().parseFromString(text, 'text/html');
    doc.__finalUrl = r.url;
    if (doc.querySelector('input[type="password"], [name^="LoginForm["]')) {
      throw new Error(СЕССИЯ(имяПоАдресу(url)));
    }
    // страница ошибки (502/503/504 шлюза, 500 Yii, 403 без прав) — не «заявок нет», а «не прочитано», как при сроке
    if (r.ok === false || r.status >= 400) { const e = new Error('CRM ответила ошибкой ' + r.status); e.status = r.status; throw e; }
    return doc;
  }

  function setVal(form, name, value) {
    let el = form.elements[name];
    if (!el) return false;
    // Yii: скрытый input + checkbox с одним именем — ставим в checkbox
    if (el.length !== undefined && el.tagName === undefined) {
      el = [...el].find((x) => x.type === 'checkbox' || x.type === 'radio') || el[el.length - 1];
    }
    if (el.type === 'checkbox') el.checked = value === '1' || value === true;
    else el.value = value;
    return true;
  }

  function serializeForm(form) {
    const body = new URLSearchParams();
    for (const el of form.elements) {
      if (!el.name || el.disabled || (typeof el.matches === 'function' && el.matches(':disabled'))) continue;
      // Как успешные поля настоящей формы: без нажатия кнопки браузер её
      // не отправляет. Нужный submitter вызывающий добавляет явно (save_close).
      if (el.tagName === 'BUTTON' || /^(submit|reset|button|image|file)$/i.test(el.type || '')) continue;
      if (el.type === 'checkbox' || el.type === 'radio') {
        if (el.checked) body.append(el.name, el.value || '1');
      } else if (el.tagName === 'SELECT' && el.multiple) {
        for (const o of el.selectedOptions) body.append(el.name, o.value);
      } else {
        body.append(el.name, el.value ?? '');
      }
    }
    return body;
  }

  function formErrors(doc) {
    const out = [];
    for (const fb of doc.querySelectorAll('.invalid-feedback, .help-block-error')) {
      const t = fb.textContent.trim();
      if (t) out.push(t);
    }
    for (const a of doc.querySelectorAll('.alert-danger, .alert-error')) {
      const t = a.textContent.trim();
      if (t) out.push(t.slice(0, 200));
    }
    return out;
  }

  /* Поле формы по подписи, как её видит человек («Вид услуг», «Нас.пункт»): <label for=id> */
  function полеПоПодписи(form, rx) {
    const doc = form.ownerDocument;
    for (const l of form.querySelectorAll('label')) {
      if (!rx.test((l.textContent || '').replace(/\s+/g, ' '))) continue;
      const id = l.getAttribute('for');
      const el = (id && doc.getElementById(id)) || l.querySelector('select, input, textarea')
        || (l.parentElement && l.parentElement.querySelector('select, input:not([type=hidden]), textarea'));
      if (el && el.name) return el;
    }
    return null;
  }

  /* «Вид услуг» — вторая ступень после «Вида работ». Имя поля в CRM точно не известно, поэтому:
     1) имя с sub…appl (sub_appliance_type_id, subappliance…, subappl_id), 2) подпись «Вид услуг». */
  function полеВидаУслуг(form) {
    const byName = [...form.elements].find((e) => e.name && e.tagName === 'SELECT' && /sub[_-]?appl/i.test(e.name));
    if (byName) return byName;
    const byLabel = полеПоПодписи(form, /вид\s+услуг/i);
    if (byLabel && byLabel.name !== 'CustomerRequest[appliance_type_id]') return byLabel;
    return null;
  }
  function селектыФормы(form) {
    return [...form.querySelectorAll('select')].filter((e) => e.name).map((e) => {
      const l = e.id && form.querySelector('label[for="' + e.id + '"]');
      return e.name + (l ? ' «' + l.textContent.trim().slice(0, 30) + '»' : '');
    }).slice(0, 15).join(', ');
  }

  /* Лёгкое сохранение комментариев в карточке — ровно как кнопка «Сохранить комментарий» в CRM:
     она шлёт ВСЕ четыре поля (комментарий, служебный, дата изменений, комментарий партнёра).
     Поле, которое не прислали, CRM может очистить — поэтому остальные берём из карточки как есть.
     ch: { partner_comment?, comments?, comments_service? } — что меняем; addComment — дописать строку в конец комментария. */
  async function saveCardComments(base, id, ch, beforeSubmit) {
    const url = base + '/admin/domain/customer-request/update?id=' + id;
    const doc = await fetchDoc(url);
    const param = doc.querySelector('meta[name="csrf-param"]')?.content || '_csrf-frontend';
    const token = doc.querySelector('meta[name="csrf-token"]')?.content || '';
    const val = (sel) => { const el = doc.querySelector(sel); return el ? (el.value ?? el.textContent ?? '') : null; };
    const now = { comments: val('#customerrequest-comments'), comments_service: val('#customerrequest-comments_service'),
      date_changes: val('#customerrequest-date_changes'), partner_comment: val('#customerrequest-partner_comment') };
    if (now.comments === null && now.partner_comment === null) return { ok: false, error: 'в карточке нет полей комментариев' };
    const next = { ...now };
    if (ch.partner_comment !== undefined) next.partner_comment = ch.partner_comment;
    if (ch.comments_service !== undefined) next.comments_service = ch.comments_service;
    if (ch.comments !== undefined) next.comments = ch.comments;
    if (ch.addComment) next.comments = [String(next.comments || '').replace(/\s+$/, ''), ch.addComment].filter(Boolean).join('\n');
    if (ch.addService) next.comments_service = [String(next.comments_service || '').replace(/\s+$/, ''), ch.addService].filter(Boolean).join('\n');
    const body = new URLSearchParams();
    body.set(param, token);
    body.set('_comments_only', 'true');
    for (const k of ['comments', 'comments_service', 'date_changes', 'partner_comment']) if (next[k] !== null) body.set(k, next[k] || '');
    if(beforeSubmit){const guard=await beforeSubmit();if(!guard?.ok)return {ok:false,error:guard?.error||'Личная сессия остановлена'}}
    const r = await fetch(url, { method: 'POST', credentials: 'include', body, headers: { 'X-Requested-With': 'XMLHttpRequest' } });
    let res = null; try { res = await r.json(); } catch (_e) { /* не JSON */ }
    return { ok: r.status < 400 && (!res || res.result !== false), comments: next.comments };
  }
  async function saveComments(base, id, partnerNote, beforeSubmit) {
    try { return (await saveCardComments(base, id, { partner_comment: partnerNote }, beforeSubmit)).ok; } catch (_e) { return false; }
  }

  /* Варианты номера — по РАЗОМ запросов одновременно, а не по одному (поиск нового клиента — 4–6 чтений подряд). Решаем всё равно
     по порядку вариантов: решить(вариант, {r} | {e}) — итог или undefined («дальше»), поэтому итог тот же, что у поиска по одному.
     Новый запрос начинаем, только когда ждём ещё не пришедший ответ (пришедший решаем сразу — может, он и есть итог); лишние уже
     начатые — просто чтение, их ответ не нужен */
  const РАЗОМ = 3;
  async function поПорядку(варианты, запрос, решить) {
    const ответы = [], пришёл = [];
    const начать = () => {
      const i = ответы.length, v = варианты[i];
      ответы.push(new Promise((res) => res(запрос(v))).then((r) => { пришёл[i] = true; return { r }; }, (e) => { пришёл[i] = true; return { e }; }));
    };
    for (let i = 0; i < варианты.length; i++) {
      if (!пришёл[i]) while (ответы.length < Math.min(варианты.length, i + РАЗОМ)) начать();
      const итог = решить(варианты[i], await ответы[i]);
      if (итог !== undefined) return итог;
    }
    return undefined;
  }
  // чтение начать сейчас, а ошибку отдать там, где его ждут (как при чтении по очереди): заранее(p)() — результат или исключение
  const заранее = (p) => {
    const x = Promise.resolve(p).then((v) => ({ v }), (e) => ({ e }));
    return async () => { const r = await x; if (r.e) throw r.e; return r.v; };
  };

  /* наПервомНет — первый вариант номера клиента не нашёл (скорее всего клиент новый): вызывающий сразу начинает чтение, нужное новому
     клиенту (форму создания без клиента), — не дожидаясь остальных вариантов и не читая её зря, когда клиент нашёлся сразу */
  async function findCustomerId(base, phone, наПервомНет) {
    const full = String(phone || '').replace(/\D/g, '');
    const p10 = full.slice(-10);
    if (p10.length < 10) return { id: '', count: 0, tried: [] };
    const masked = '+7 ' + p10.slice(0, 3) + '-' + p10.slice(3, 6) + '-' + p10.slice(6);
    const cands = [...new Set([masked, p10, '7' + p10, '8' + p10])];
    const tried = [];
    let ответов = 0, сбой = '', сбойСервера = false;
    const искать = async (q) => {
      const r = await getСрок(base + '/api/customer/search?q=' + encodeURIComponent(q) + '&_serverKey=', {
        credentials: 'include', headers: { 'X-Requested-With': 'XMLHttpRequest' },
      });
      return { r, raw: await r.text() };
    };
    const решить = (q, ответ) => {
      try {
        if (ответ.e) throw ответ.e;
        const { r, raw } = ответ.r;
        let d = null;
        try { d = JSON.parse(raw); } catch (_e) { d = null; }
        // вход истёк (вместо JSON — страница входа): «нажмите ещё раз» не поможет — нужен вход, как сказал бы fetchDoc
        if (!d && (/\/login/.test(r.url || '') || /name="LoginForm\[|type="password"/i.test(raw))) return { id: '', count: 0, tried, сбой: 'нет входа', вход: true };
        // не JSON (страница 502/500 шлюза) или код ошибки — это не «клиента нет», а сбой поиска
        if (!d || typeof d !== 'object' || r.ok === false || r.status >= 400) {
          const why = r.status >= 400 ? 'CRM ответила ошибкой ' + r.status : 'CRM ответила не JSON';
          tried.push(q + '→' + why);
          сбой = сбой || why;
          if (r.status >= 500) сбойСервера = true;
          return undefined;
        }
        ответов++;
        const items = d?.results || d?.items || (Array.isArray(d) ? d : []);
        tried.push(q + '→' + items.length);
        if (items.length) return { id: String(items[0].id ?? items[0].value ?? ''), count: items.length, tried };
      } catch (e) {
        tried.push(q + '→' + суть(e));
        сбой = сбой || суть(e);
        сбойСервера = true;
      }
      return undefined;
    };
    const найден = await поПорядку(cands, искать, (q, ответ) => {
      const итог = решить(q, ответ);
      if (итог === undefined && q === cands[0] && наПервомНет) наПервомНет();
      return итог;
    });
    if (найден) return найден;
    // ни один поиск не ответил, или какой-то упал на стороне CRM (срок, сеть, 5xx) — «клиента нет» не доказано (клиент мог найтись
    // именно этим вариантом номера): сбой отдаём, создание вслепую не пойдёт. Вариант, на который CRM отвечает не-JSON/4xx, при
    // ответивших остальных — не сбой (так было и раньше)
    return { id: '', count: 0, tried, ...(ответов && !сбойСервера ? {} : { сбой: сбой || 'поиск клиента не ответил' }) };
  }

  /* История клиента в CRM: статусы его заявок короткими ячейками */
  async function customerStatuses(base, custId) {
    const out = [];
    try {
      const doc = await fetchDoc(base + '/admin/domain/customer/update?id=' + custId);
      for (const tr of doc.querySelectorAll('tr')) {
        if (!tr.querySelector('a[href*="customer-request/update?id="]')) continue;
        for (const td of tr.querySelectorAll('td')) {
          const t = (td.textContent || '').trim();
          if (t && t.length <= 30) out.push(t);
        }
      }
    } catch (_e) { /* история не прочиталась — не блокируем */ }
    return out;
  }
  // «Модерация» — тоже живая заявка: регламент велит взять её в работу и сохранить, а новая будет дублем («НФ, дубль»).
  // «На уточнении» (код 3) — живая, как в СТАТУСЫ crmact/crmcust: её возвращают в «Ожидает», вторая — дубль
  const ЖИВЫЕ = /^(?:Ожидает|В работе|Назначен|Принят|Подтвержд|Едет|В пути|Согласован|Модерац|На уточнени)/i;
  const МОДЕРАЦИЯ = /^Модерац/i;
  const модерацияТекст = (r) => 'у клиента заявка в Модерации' + (r && r.id ? ' ' + (ИМЯ[r.dir] || '') + ' №' + r.id : '')
    + ' — возьмите её в работу («Взять в работу») и сохраните, новую не создавайте';
  const ЗАКРЫТЫЕ = /^(?:Готов|Выполнен|Отказ)/i;

  /* ПОИСК НОМЕРА ВО ВСЕХ БАЗАХ — способ «Чатерского расширения»: список заявок базы с фильтром
     CRSearch[phone], номер в нескольких записях. Строка = ссылка на заявку, статус, город, дата.
     База без входа не «пустая», а «не проверена» — так и говорим. */
  function вариантыНомера(phone) {
    const d = String(phone || '').replace(/\D/g, '');
    const p10 = d.slice(-10);
    if (p10.length < 10) return [];
    const w = '7' + p10;
    return [...new Set([`+7 ${p10.slice(0, 3)}-${p10.slice(3, 6)}-${p10.slice(6, 8)}-${p10.slice(8)}`,
      `+7 ${p10.slice(0, 3)}-${p10.slice(3, 6)}-${p10.slice(6)}`, '+' + w, w, '8' + p10, p10])];
  }

  async function searchBase(dir, phone) {
    const base = BASES[dir];
    const clean = (el) => (el?.textContent || '').replace(/\s+/g, ' ').trim();
    let ошибкаCRM = null;                   // страница ошибки на одном варианте номера: другие ещё могут найти; не нашли — «не проверено»
    try {
      // варианты номера — по РАЗОМ одновременно, решение — по порядку вариантов (как раньше по одному)
      const найдено = await поПорядку(вариантыНомера(phone), (v) => {
        const url = new URL(base + '/admin/domain/customer-request/index');
        url.searchParams.set('CRSearch[phone]', v);
        return fetchDoc(url.href);
      }, (_v, ответ) => {
        if (ответ.e) { const e = ответ.e; if (!(e && e.status)) throw e; ошибкаCRM = ошибкаCRM || e; return undefined; }
        const doc = ответ.r;
        const rows = [];
        const seen = new Set();
        // колонка «Статус» — строго по классу col__req_status или по заголовку (у «Времени заявки» есть похожий col__req_status_awaitOnly)
        const заголовки = [...doc.querySelectorAll('table thead tr:first-child th')].map((th) => clean(th));
        const колонка = (tr, имя) => { const i = заголовки.findIndex((t) => t === имя); return i >= 0 && tr ? tr.children[i] : null; };
        const статусИз = (tr) => tr ? ([...tr.children].find((td) => td.classList.contains('col__req_status')) || колонка(tr, 'Статус')) : null;
        const времяИз = (tr) => tr ? ([...tr.children].find((td) => td.classList.contains('col__openedAt')) || колонка(tr, 'Время заявки')) : null;
        for (const a of doc.querySelectorAll('td.col__id a[href*="update?id="], a[href*="/admin/domain/customer-request/update?id="]')) {
          const id = ((a.getAttribute('href') || '').match(/[?&]id=(\d+)/) || [])[1];
          if (!id || seen.has(id)) continue;
          seen.add(id);
          const tr = a.closest('tr');
          rows.push({ dir, id, url: base + '/admin/domain/customer-request/update?id=' + id,
            status: clean(статусИз(tr)) || '—', when: clean(времяИз(tr)) || '', closedAt: clean(колонка(tr, 'Закрыто')) || '',
            city: clean(tr && tr.querySelector('td.--fullwidth a, td.--fullwidth, td[class*="city"]')) || '' });
          if (rows.length >= 5) break;
        }
        return rows.length ? { dir, rows } : undefined;
      });
      if (найдено) return найдено;
      if (ошибкаCRM) throw ошибкаCRM;
      return { dir, rows: [] };
    } catch (e) {
      return { dir, rows: [], error: /Сессия/.test(String(e.message)) ? 'нет входа в CRM ' + ИМЯ[dir] : String(e.message || e).slice(0, 80) };
    }
  }

  async function searchAllBases(phone) {
    if (String(phone || '').replace(/\D/g, '').length < 10) return { found: [], unchecked: [] };
    const res = await Promise.all(Object.keys(BASES).map((d) => searchBase(d, phone)));
    return { found: res.flatMap((r) => r.rows), unchecked: res.filter((r) => r.error).map((r) => ({ dir: r.dir, error: r.error })) };
  }

  /* КАРТОЧКА ЗАЯВКИ: город, источник (комментарий партнёра), визит, последний перенос — для «у клиента уже есть заявка» */
  async function requestInfo(dir, id) {
    return карточкаИз(dir, id, await fetchDoc(BASES[dir] + '/admin/domain/customer-request/update?id=' + id));
  }
  // то же по уже прочитанной карточке: перенос и отмена берут статус из той же страницы, что и форму, — второй раз её не читаем
  function карточкаИз(dir, id, doc) {
    const base = BASES[dir];
    const el = (n) => doc.querySelector('[name="' + n + '"]');
    const txt = (n) => { const e = el(n); if (!e) return ''; if (e.tagName === 'SELECT') { const o = [...e.options].find((x) => x.selected || x.hasAttribute('selected')); return o && o.value ? o.textContent.replace(/\s+/g, ' ').trim() : ''; } return String(e.value ?? e.getAttribute('value') ?? e.textContent ?? '').trim(); };
    const area = (sel) => { const e = doc.querySelector(sel); return e ? String(e.value ?? e.textContent ?? '').trim() : ''; };
    if (!el('CustomerRequest[city_id]') && !doc.querySelector('#customerrequest-partner_comment')) return null;   // не карточка заявки
    const переносы = area('#customerrequest-date_changes').split('\n').map((x) => x.trim()).filter(Boolean);
    const phone = (txt('Customer[phone]') || (doc.body.textContent.match(/\+7[\s(]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}/) || [''])[0]).replace(/\D/g, '').slice(-10);
    // статус: само поле статуса (если его можно менять) или строка «Статус: Ожидает» в шапке карточки.
    // Другие поля со словом status в имени не берём: там бывают условия выезда («Выезд бесплатный.»)
    const stEl = doc.querySelector('select[name="CustomerRequest[req_status]"], select[name="CustomerRequest[status]"], select[name="CustomerRequest[status_id]"]');
    const шапка = [...doc.querySelectorAll('span')].find((e) => /^\s*Статус:\s*$/.test(e.textContent || ''));
    const status = (stEl ? txt(stEl.name) : '') || (шапка && шапка.parentElement ? шапка.parentElement.textContent.replace(/\s+/g, ' ').replace(/^\s*Статус:\s*/, '').trim().slice(0, 40) : '');
    return { dir, id: String(id), url: base + '/admin/domain/customer-request/update?id=' + id, city: txt('CustomerRequest[city_id]'), cardStatus: status,
      source: area('#customerrequest-partner_comment'), partner: txt('CustomerRequest[partner_id]'), appl: txt('CustomerRequest[appliance_type_id]'),
      visit: txt('CustomerRequest[opened_at]'), visitTime: ((doc.querySelector('#cr_opened_at_time') || {}).value || '').slice(0, 5), lastChange: переносы[переносы.length - 1] || '', phone10: phone,
      // галочка «Прозвон» (как её находит Чатерское): при статусе «Ожидает»/«В пути» в чат пишут «№ на прозвоне»
      sub: (() => { const f = doc.querySelector('#customerRequestForm'); const e = f && полеВидаУслуг(f); return e ? txt(e.name) : ''; })(),
      typeText: txt('CustomerRequest[type]'), rk: txt('CustomerRequest[advert_id]'), customerId: клиентЗаявкиИз(doc),   // адрес — в карточке этого клиента
      // служебный комментарий: «звонить только на второй номер» — для «свяжитесь по сд» номер берём оттуда
      serviceComment: area('#customerrequest-comments_service').slice(0, 500),
      // 2.1.3 (повтор и гарантия): мастер и «Гарантия ОКК» — строка этой заявки в «Истории заказов клиента»; сумма — «Сумма, оплаченная клиентом»
      ...строкаИстории(doc, id), paid: оплачено(doc),
      prozvon: !!(doc.querySelector('input[type="checkbox"][name="CustomerRequest[is_need_call_check]"]') || {}).checked
        || !!(doc.querySelector('input[type="checkbox"][name="CustomerRequest[is_need_call_check]"][checked]')) };
  }
  const ЗАКРЫТО = /закрыт|выполнен|отмен|не оформлен|не создан|отказ|брак|оплачен|готов/i;
  const НЕ_СТАТУС = /^(—|-|\d{1,2}\.\d{1,2}\.\d{2,4}.*)$/;          // в колонку попала дата — статус возьмём из карточки
  /* ВСЕ ЗАЯВКИ КЛИЕНТА: по номеру во всех базах + номера заявок из имени в LeadChat («Людмила 1046552 1052370») */
  async function existing(a) {
    const phone10 = String(a.phone || '').replace(/\D/g, '').slice(-10);
    const x = phone10.length === 10 ? await searchAllBases(phone10) : { found: [], unchecked: [] };
    const rows = x.found.slice();
    const ids = [...new Set((String(a.name || '').match(/(?<!\d)\d{6,8}(?!\d)/g) || []))].filter((id) => !rows.some((r) => r.id === id)).slice(0, 4);
    // номера из имени — разом; базы для одного номера — по очереди, как раньше (первая подошедшая решает); строки — в порядке номеров
    const изИмени = await Promise.all(ids.map(async (id) => {
      for (const dir of [a.dir, ...Object.keys(BASES).filter((d) => d !== a.dir)].filter(Boolean)) {
        try {
          const info = await requestInfo(dir, id);
          if (info && (!phone10 || !info.phone10 || info.phone10 === phone10)) return { ...info, status: info.cardStatus || '—', fromName: true };
        } catch (_e) { /* нет входа в эту базу или нет такой заявки */ }
      }
      return null;
    }));
    for (const r of изИмени) if (r) rows.push(r);
    // подробности — для первых трёх (сначала незакрытые); карточки разные — читаем разом
    rows.sort((p, q) => (ЗАКРЫТО.test(p.status) ? 1 : 0) - (ЗАКРЫТО.test(q.status) ? 1 : 0) || Number(q.id) - Number(p.id));
    await Promise.all(rows.slice(0, 3).filter((r) => r.source === undefined).map(async (r) => {
      try { const i = await requestInfo(r.dir, r.id); if (i) Object.assign(r, { ...i, status: НЕ_СТАТУС.test(r.status || '—') ? (i.cardStatus || r.status) : r.status, city: r.city || i.city }); } catch (_e) { /* нет подробностей */ }
    }));
    // статус так и не узнали (за пределами первых трёх) — дочитываем карточку, чтобы не принять старую заявку за живую
    await Promise.all(rows.filter((x) => НЕ_СТАТУС.test(x.status || '—') && x.source === undefined).slice(0, 4).map(async (r) => {
      try { const i = await requestInfo(r.dir, r.id); if (i && i.cardStatus) r.status = i.cardStatus; } catch (_e) { /* нет подробностей */ }
    }));
    rows.sort((p, q) => (ЗАКРЫТО.test(p.status) ? 1 : 0) - (ЗАКРЫТО.test(q.status) ? 1 : 0) || Number(q.id) - Number(p.id));
    return { ok: true, found: rows.map((r) => ({ ...r, open: !ЗАКРЫТО.test(r.status || '') })), unchecked: x.unchecked };
  }

  /* СПРАВОЧНИКИ CRM — на 30 мин (offscreen живёт долго, а заявки идут в тех же городах): виды работ — на (базу, город, партнёр),
     виды услуг — на (базу, город, вид работ, партнёр). Кладём только непустой список, полученный от CRM: сбой, пустой ответ и список
     из самой формы не запоминаем (и забываем прежний) — в следующий раз спросим CRM. Живое (клиент, дубли, карточки) не кэшируем */
  const СПРАВОЧНИК_МС = 30 * 60e3;
  const СПРАВОЧНИК = new Map();
  function изСправочника(k) {
    const x = СПРАВОЧНИК.get(k);
    if (x && Date.now() - x.at < СПРАВОЧНИК_МС) return { ...x, list: x.list.map((o) => ({ ...o })) };
    if (x) СПРАВОЧНИК.delete(k);
    return null;
  }
  function вСправочник(k, list, how) {
    if (!list || !list.length) { СПРАВОЧНИК.delete(k); return; }
    for (const [kk, x] of СПРАВОЧНИК) if (Date.now() - x.at >= СПРАВОЧНИК_МС) СПРАВОЧНИК.delete(kk);
    СПРАВОЧНИК.set(k, { list: list.map((o) => ({ ...o })), how: how || '', at: Date.now() });
  }

  /* Виды работ для города: подгрузка формы (с has_partner=0, затем 1), иначе список из самой формы */
  async function applTypes(base, cityId, form, hasPartner) {
    const тянуть = async (hasPartner, applId) => {
      const q = new URLSearchParams({ _get_appltype: 1, city_id: cityId, appl_id: applId || '', subappl_id: '', has_partner: hasPartner });
      const r = await getAjax(base + CREATE + '?' + q);
      return списокВSelect(опцииОтвета(r.text, 'CustomerRequest[appliance_type_id]'));
    };
    const hp = hasPartner ? 1 : 0;
    const ключ = 'appl|' + base + '|' + cityId + '|' + hp;
    const было = изСправочника(ключ);
    if (было) { const sel = списокВSelect(было.list); return { list: опции(sel), sel, тянуть }; }
    let sel = await тянуть(hp);
    if (!опции(sel).length) sel = await тянуть(1 - hp);
    вСправочник(ключ, опции(sel));                                   // ответ CRM; пустой — не запоминаем
    if (!опции(sel).length && form) sel = form.elements['CustomerRequest[appliance_type_id]'];
    return { list: опции(sel), sel, тянуть };
  }

  /* Список из ответа CRM: JSON ({output:[{id,name}]}, {results:[{id,text}]}, [{value,label}], {id: name}) или <option> */
  function разобратьСписок(text) {
    const t = String(text || '').trim();
    if (/^[\[{]/.test(t)) {
      try {
        const d = JSON.parse(t);
        let arr = Array.isArray(d) ? d : (d.output || d.results || d.items || d.data || d.list || null);
        if (arr && !Array.isArray(arr) && typeof arr === 'object') arr = Object.entries(arr).map(([id, name]) => ({ id, name }));
        if (!arr && typeof d === 'object') arr = Object.entries(d).filter(([, v]) => typeof v === 'string').map(([id, name]) => ({ id, name }));
        return (arr || []).flatMap((o) => (o && Array.isArray(o.children) ? o.children : [o]))
          .map((o) => (o && typeof o === 'object' ? { id: String(o.id ?? o.value ?? o.key ?? ''), text: String(o.name ?? o.text ?? o.label ?? o.title ?? '').trim() } : null))
          .filter((o) => o && /^\d+$/.test(o.id) && o.text && !/[<>]/.test(o.text));   // в CRM номера услуг — целые числа
      } catch (_e) { return []; }
    }
    const sel = new DOMParser().parseFromString('<select>' + t + '</select>', 'text/html').querySelector('select');
    return опции(sel).filter((o) => /^\d+$/.test(o.id));
  }
  const тотЖеСписок = (a, b) => a.length && b && b.length && a.length === b.length && a.every((x, i) => x.id === b[i].id);

  /* Как форма CRM подгружает «Вид услуг»: адрес из настроек самого поля (DepDrop Yii: data-krajee-depdrop)
     и из кода формы рядом с ним. Только чтение: адреса сохранения/удаления не трогаем. */
  const способВидаУслуг = {};
  const справочникURL = (u) => typeof u === 'string' && u.length <= 2000
    && /^\/(?!\/)[\w\-\/.]*(\?.*)?$/.test(u) && !u.includes('#')
    && !/save|create|update|delete|remove|logout|login|employee|user|partner|customer\/search/i.test(u)
    && /sub|appl|depdrop|type|service|uslug|child|list/i.test(u);
  function кандидатыВидаУслуг(doc, subEl) {
    const out = [];
    const ok = справочникURL;
    const scripts = [...doc.querySelectorAll('script')].map((x) => x.textContent || '');
    const dep = subEl.getAttribute('data-krajee-depdrop');
    if (dep) {
      for (const sc of scripts) {
        const i = sc.indexOf(dep);
        if (i < 0) continue;
        const m = sc.slice(i, i + 3000).match(/"url"\s*:\s*"([^"]+)"/);
        if (m) out.push({ url: m[1].replace(/\\\//g, '/'), depdrop: true, parentId: (sc.slice(i, i + 3000).match(/"depends"\s*:\s*\[\s*"([^"]+)"/) || [])[1] || '' });
      }
    }
    for (const a of subEl.attributes) if (/url|href|src|ajax/i.test(a.name) && ok(a.value)) out.push({ url: a.value });
    const keys = [subEl.id, subEl.name, 'subappl', 'sub_appl', 'subappliance', 'sub_appliance'].filter(Boolean);
    for (const sc of scripts) {
      if (!keys.some((k) => sc.includes(k))) continue;
      for (const m of sc.matchAll(/["'](\/[\w\-\/.]+(?:\?[^"'\s]*)?)["']/g)) if (ok(m[1])) out.push({ url: m[1] });
    }
    const seen = new Set();
    return out.filter((c) => ok(c.url) && !seen.has(c.url + c.depdrop) && seen.add(c.url + c.depdrop)).slice(0, 6);
  }

  async function subTypes(base, cityId, applId, applList, doc, subEl, hasPartner) {
    const ключ = 'sub|' + base + '|' + cityId + '|' + applId + '|' + (hasPartner ? 1 : 0);
    const было = изСправочника(ключ);
    if (было) return { list: было.list, sel: null, how: было.how };
    const r = await видыУслуг(base, cityId, applId, applList, doc, subEl, hasPartner);
    вСправочник(ключ, r.list, r.how);                                 // список от CRM; пустой — не запоминаем
    return r;
  }
  async function видыУслуг(base, cityId, applId, applList, doc, subEl, hasPartner) {
    // 1) как сама форма CRM: ?_get_appltype=1&get_subappltypes=1&city_id&appl_id&subappl_id&has_partner
    let list = [], ответ = null;
    for (const hp of hasPartner ? [1, 0] : [0, 1]) {
      const q = new URLSearchParams({ _get_appltype: 1, get_subappltypes: 1, city_id: cityId, appl_id: applId, subappl_id: '', has_partner: hp });
      try { ответ = await getAjax(base + CREATE + '?' + q); } catch (_e) { ответ = null; continue; }
      list = опцииОтвета(ответ.text, 'CustomerRequest[appliance_sub_type_id]');
      if (list.length && !тотЖеСписок(list, applList)) return { list, sel: null, how: 'подгрузка формы' };
    }
    if (!doc || !subEl) return { list: [], sel: null, how: '', diag: 'CRM не дала список видов услуг: ' + кратко(ответ) };
    // 2) способ, найденный в форме (запоминаем на базу)
    const csrfP = doc.querySelector('meta[name="csrf-param"]')?.content || '_csrf-frontend';
    const csrfT = doc.querySelector('meta[name="csrf-token"]')?.content || '';
    const found = кандидатыВидаУслуг(doc, subEl);
    const mem = способВидаУслуг[base];
    // запомненный способ — первым; не сработал — ищем заново в форме
    const cands = mem ? [mem, ...found.filter((c) => c.url !== mem.url || c.depdrop !== mem.depdrop)] : found;
    for (const c of cands) {
      try {
        if (!справочникURL(c.url) || new URL(c.url, base).origin !== new URL(base).origin) continue;
        let r;
        if (c.depdrop) {
          const body = new URLSearchParams();
          body.set('depdrop_parents[0]', applId);
          body.set('depdrop_all_params[' + (c.parentId || 'customerrequest-appliance_type_id') + ']', applId);
          body.set(csrfP, csrfT);
          r = await getСрок(new URL(c.url, base).href, { method: 'POST', credentials: 'include', redirect: 'error', body, headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        } else {
          const u = new URL(c.url, base);
          for (const [k, v] of [['id', applId], ['appl_id', applId], ['appliance_type_id', applId], ['city_id', cityId]]) if (!u.searchParams.has(k)) u.searchParams.set(k, v);
          r = await getСрок(u.href, { credentials: 'include', redirect: 'error', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        }
        if (!r.ok) continue;
        list = разобратьСписок(await r.text());
        if (list.length && !тотЖеСписок(list, applList)) { способВидаУслуг[base] = c; return { list, sel: null, how: c.url }; }
      } catch (_e) { /* следующий способ */ }
    }
    const attrs = [...subEl.attributes].filter((a) => a.name !== 'class' && a.name !== 'style').map((a) => a.name + '=' + String(a.value).slice(0, 60)).join(' ');
    return { list: [], sel: null, how: '', diag: 'CRM не дала список видов услуг (v' + ВЕРСИЯ + '). Запрос формы get_subappltypes: ' + кратко(ответ)
      + (cands.length ? '. Ещё проверено: ' + cands.map((c) => c.url).join(', ') : '') + '. Поле: ' + attrs };
  }

  /* Подсказки CRM к видам работ и услуг (var applianceTypes / applianceSubTypes в коде формы):
     цена «от» и что уточнять — ИИ по ним и по регламенту выбирает вид работ и услуг */
  function подсказки(doc) {
    const out = { appl: {}, sub: {} };
    for (const sc of doc.querySelectorAll('script')) {
      const t = sc.textContent || '';
      for (const [k, v] of [['appl', 'applianceTypes'], ['sub', 'applianceSubTypes']]) {
        const m = t.match(new RegExp('var\\s+' + v + '\\s*=\\s*(\\{[\\s\\S]*?\\});'));
        if (m) { try { Object.assign(out[k], JSON.parse(m[1])); } catch (_e) { /* не JSON — без подсказок */ } }
      }
    }
    for (const k of ['appl', 'sub']) for (const id of Object.keys(out[k])) out[k][id] = String(out[k][id] || '').replace(/\s+/g, ' ').slice(0, 300);
    return out;
  }

  function pickByTopics(sel, topics, withOther) {
    let id = '';
    for (const t of topics || []) { id = pickOption(sel, t); if (id) return { id, how: 'по теме «' + t + '»' }; }
    for (const t of topics || []) {
      const v = синонимыТемы(t);
      if (v.length) id = pickOption(sel, ...v);
      if (id) return { id, how: 'по синониму темы «' + t + '»' };
    }
    if (withOther) { id = pickOption(sel, 'проч'); if (id) return { id, how: '«Прочая» — тема не нашлась' }; }
    return { id: '', how: '' };
  }

  function списокВSelect(list) {
    const sel = new DOMParser().parseFromString('<select></select>', 'text/html').querySelector('select');
    for (const o of list || []) { const op = sel.ownerDocument.createElement('option'); op.value = o.id; op.textContent = o.text; sel.append(op); }
    return sel;
  }
  function selectFrom(list, id) { const o = list.find((x) => x.id === id); return o ? o.text : ''; }

  // служебные пункты CRM («ТЕСТ», «test») — не для настоящих заявок
  const безТеста = (list) => (list || []).filter((o) => !/^\s*(тест|test)(?![а-яa-z])/i.test(String(o.text || '')));
  /* ПОДГОТОВКА: что будет в заявке — по настоящей форме CRM */
  async function prepare(p) {
    const base = BASES[p.dir];
    if (!base) return { ok: false, error: 'не выбрано направление (МНЧ / КП / БТ)' };
    // параллельно: номер во всех трёх базах. Проверка готовности только что искала этот же номер (known) — не ищем второй раз
    const xbase = p.known && p.known.phone10 === String(p.phone || '').replace(/\D/g, '').slice(-10) && Array.isArray(p.known.found)
      ? Promise.resolve({ found: p.known.found.map((r) => ({ ...r })), unchecked: p.known.unchecked || [] }) : searchAllBases(p.phone);
    // прошлые заявки этой базы (до 4 свежих): вид работ/услуг, партнёр, источник, тип — для правил повторов (отказ, отмены, гарантия).
    // Читаем, как только пришёл поиск по базам, — пока идут форма и справочники; карточка и претензии одной заявки — тоже разом
    const xПодробно = xbase.then(async (x) => {
      await Promise.all(x.found.filter((r) => r.dir === p.dir).sort((a, b) => Number(b.id) - Number(a.id)).slice(0, 4).map(async (r) => {
        const претензии = заранее(claimsFor(r.dir, r.id));
        try {
          const i = await requestInfo(r.dir, r.id);
          if (i) Object.assign(r, { appl: i.appl, sub: i.sub, partner: i.partner, src: i.source ? (i.source.split('\n')[0] || '').trim() : '', typeText: i.typeText, visit: i.visit, master: i.master, paid: i.paid, okk: i.okk,
            status: НЕ_СТАТУС.test(r.status || '—') ? (i.cardStatus || r.status) : r.status });
          try { const c = await претензии(); r.hasClaim = c.count > 0; } catch (_e) { /* нет доступа к ОКК — не знаем */ }
        } catch (_e) { /* без подробностей — правила поймут меньше */ }
      }));
      return x;
    });
    // форма создания без клиента — как только первый вариант номера клиента не нашёл (новому клиенту нужна она), не дожидаясь остальных
    let формаБезКлиента = null;
    const безКлиента = () => формаБезКлиента || (формаБезКлиента = заранее(fetchDoc(base + CREATE)));
    const cust = await findCustomerId(base, p.phone, безКлиента);
    let live = '', type = 'Впервые';
    // клиент нашёлся — форма с ним и его история разом
    const форма = cust.id ? заранее(fetchDoc(base + CREATE + '?customer_id=' + cust.id)) : безКлиента();
    if (cust.id) {
      const st = await customerStatuses(base, cust.id);
      live = st.find((t) => ЖИВЫЕ.test(t)) || '';
      if (st.some((t) => ЗАКРЫТЫЕ.test(t))) type = 'Повтор';
    }
    if (p.repeat_hint === 'гарантия') type = 'Гарантия';
    const doc = await форма();
    const form = doc.querySelector('#customerRequestForm') || doc.querySelector('form');
    if (!form || !form.elements['CustomerRequest[city_id]']) return { ok: false, error: 'форма создания заявки не открылась' };
    const citySel = form.elements['CustomerRequest[city_id]'];
    const cities = опции(citySel);
    let cityId = p.cityId || pickCity(citySel, p.city) || (p.cityFallback ? pickCity(citySel, p.cityFallback) : '') || '';
    // нашёлся только закрытый филиал — не выбираем, но говорим оператору, что он закрыт
    const cityClosed = cityId ? '' : selectFrom(cities, pickCity(citySel, p.city, true) || (p.cityFallback ? pickCity(citySel, p.cityFallback, true) : ''));
    const partnerSel0 = form.elements['CustomerRequest[partner_id]'];
    const hasPartner = !!(p.partner && pickNumber(partnerSel0, p.partner));
    let appl = [], applId = '', applHow = '', sub = [], subId = '', subDiag = '', subHow = '', applRule = false, subRule = false;
    if (cityId) {
      const a = await applTypes(base, cityId, form, hasPartner);
      appl = безТеста(a.list);
      // 2.0.7: сначала правила по регламенту и настоящим названиям CRM (worktype.js); не решили — прежний подбор по темам
      const суть = { problem: p.problem || '', topics: p.topics || [], device: p.device || '' };
      const правило = !p.applId && typeof LC_WORK !== 'undefined' ? LC_WORK.видРабот(p.dir, appl, суть) : { id: '' };
      const pk = p.applId ? { id: p.applId, how: 'выбрано вами' } : правило.id ? { id: правило.id, how: правило.how } : pickByTopics(a.sel, p.topics, true);
      applId = (pk.id && appl.some((o) => o.id === pk.id) ? pk.id : '') || (appl[0] ? appl[0].id : '');
      applHow = pk.id ? pk.how : (appl[0] ? 'первый из списка — проверьте' : '');
      applRule = !!(правило.уверенно && правило.id === applId);
      const subEl = полеВидаУслуг(form);
      if (applId && subEl) {
        const s = await subTypes(base, cityId, applId, appl, doc, subEl, hasPartner);
        sub = безТеста(s.list);
        if (!sub.length && опции(subEl).length) sub = безТеста(опции(subEl));   // подгрузка пуста — список из самой формы
        const subSel = списокВSelect(sub);
        const applText = (appl.find((o) => o.id === applId) || {}).text || '';
        const правилоУ = typeof LC_WORK !== 'undefined' ? LC_WORK.видУслуг(p.dir, sub, суть, applText, appl) : { id: '' };
        const pkSub = правилоУ.id || pickByTopics(subSel, p.topics, false).id;
        subId = (p.subId && sub.some((o) => o.id === p.subId) ? p.subId : '') || (pkSub && sub.some((o) => o.id === pkSub) ? pkSub : '') || (sub[0] ? sub[0].id : '');
        subRule = !!(правилоУ.уверенно && правилоУ.id === subId);
        subHow = p.subId && subId === p.subId ? 'выбрано вами' : subRule ? правилоУ.how : pkSub && subId === pkSub ? 'по теме' : 'первый из списка — проверьте';
        if (!sub.length) subDiag = s.diag || 'для этого вида работ CRM не дала список видов услуг';
      }                                   // поля «Вид услуг» в форме нет — выбирать нечего, это не ошибка
    }
    const partnerSel = form.elements['CustomerRequest[partner_id]'];
    const partnerId = p.partner ? pickNumber(partnerSel, p.partner) : '';
    const dateEl = form.elements['CustomerRequest[opened_at]'];
    const x = await xПодробно;
    const liveAny = x.found.find((r) => ЖИВЫЕ.test(r.status));
    if (!live && liveAny) live = liveAny.status + ' (' + ИМЯ[liveAny.dir] + ' №' + liveAny.id + ')';
    // заявка в «Модерации» — не вторую создавать, а взять её в работу (номер и ссылка — из поиска по базам)
    const мод = x.found.find((r) => МОДЕРАЦИЯ.test(r.status || ''));
    const moderation = мод ? { dir: мод.dir, id: мод.id, url: мод.url, text: модерацияТекст(мод) }
      : МОДЕРАЦИЯ.test(live) ? { dir: p.dir, id: '', url: '', text: модерацияТекст(null) } : null;
    if (type === 'Впервые' && x.found.some((r) => r.dir === p.dir && ЗАКРЫТЫЕ.test(r.status))) type = 'Повтор';
    return {
      ok: true, base, cities, cityId, cityText: selectFrom(cities, cityId), cityClosed, found: x.found, unchecked: x.unchecked,
      appl, applId, applHow, applRule, sub, subId, subHow, subRule, subDiag, type, hints: подсказки(doc), hasPartner,
      customer: { id: cust.id, count: cust.count }, live, moderation,
      partner: p.partner || '', partnerFound: !!partnerId,
      dateSample: dateEl ? (dateEl.value || dateEl.getAttribute('placeholder') || '') : '',
      hasTime: !!form.elements['cr_opened_at_time'],
    };
  }

  /* КАРТОЧКА КЛИЕНТА. Адрес и доп. номера CRM хранит у КЛИЕНТА, а не у заявки. В форме создания поля Customer[*] — блок
     «новый клиент»: выбран существующий клиент — CRM сама очищает блок и не проверяет его поля, и новый адрес молча теряется
     (у заявки остаётся старый адрес клиента). Поэтому существующему клиенту адрес правим в его карточке
     (/admin/domain/customer/update?id=N, form#w0) — всю форму, как она пришла, меняем только поля адреса и пустую строку телефона. */
  const URL_КЛИЕНТА = (base, custId) => base + '/admin/domain/customer/update?id=' + encodeURIComponent(custId);
  const АДРЕС_КЛИЕНТА = { locality: 'Customer[address_locality]', street: 'Customer[address_street]', building: 'Customer[address_building]',
    office: 'Customer[address_office]', entrance: 'Customer[address_entrance]', floor: 'Customer[address_floor]' };
  const ЧАСТИ_АДРЕСА = { office: 'квартира', entrance: 'подъезд', floor: 'этаж' };
  const ДОМОФОН = 'Customer[address_has_intercom]';
  // одно поле формы (не список одноимённых: скрытое + галочка)
  const полеФормы = (form, n) => { const e = form && form.elements[n]; return e && e.tagName ? e : null; };
  function intercomWanted(addr) {
    const a = addr || {};
    if (Object.prototype.hasOwnProperty.call(a, 'has_intercom')) return typeof a.has_intercom === 'boolean' ? a.has_intercom : null;
    return a.intercom ? true : null;
  }
  function intercomElement(form) {
    const e = form && form.elements[ДОМОФОН];
    return e && e.tagName ? e : e && [...e].find(x => x.type === 'checkbox') || null;
  }
  function intercomValue(el, value) {
    if (!el) return null;
    if (el.type === 'checkbox') return value === undefined ? (el.checked ? '1' : '0') : String(value);
    const raw = value === undefined ? el.value : value;
    const option = el.tagName === 'SELECT' && [...el.options].find(o => String(o.value) === String(raw));
    const label = String(option && (option.text || option.label || option.textContent) || '').replace(/\s+/g, ' ').trim().toLowerCase();
    // CRM: «Есть домофон» = 1, «Нет домофона» = 2. Numeric option ids are
    // transport values, not booleans; normalize only explicit known labels.
    if (['да', 'yes', 'есть домофон'].includes(label)) return '1';
    if (['нет', 'no', 'нет домофона'].includes(label)) return '0';
    return el.tagName === 'SELECT' ? null : ['0', '1'].includes(String(raw)) ? String(raw) : null;
  }
  function intercomChoice(form, addr) {
    const wanted = intercomWanted(addr);
    if (wanted === null) return { wanted, value: null, error: '' };
    const el = intercomElement(form);
    if (!el) return { wanted, value: null, error: 'в карточке клиента нет поля «Домофон»' };
    if (el.disabled) return { wanted, value: null, error: 'поле «Домофон» недоступно для изменения' };
    if (el.tagName === 'SELECT') {
      const option = [...el.options].find(o => !o.disabled && intercomValue(el, o.value) === (wanted ? '1' : '0'));
      return option ? { wanted, value: String(option.value), error: '' }
        : { wanted, value: null, error: 'в поле «Домофон» нет варианта «' + (wanted ? 'Да' : 'Нет') + '»' };
    }
    return { wanted, value: wanted ? '1' : '0', error: '' };
  }
  function формаКлиента(doc) {
    const все = [...doc.querySelectorAll('form')];
    return все.find((f) => f.id === 'w0' && полеФормы(f, АДРЕС_КЛИЕНТА.street)) || все.find((f) => полеФормы(f, АДРЕС_КЛИЕНТА.street)) || null;
  }
  // строка заявки в «Истории заказов клиента» на её карточке: колонка «Мастер», «Гарантия ОКК» (класс строки bg-is_okk_guarantee)
  function строкаИстории(doc, id) {
    const грид = doc.querySelector('#customer-requests-grid table') || doc.querySelector('table');
    const tr = грид && грид.querySelector('tr[data-key="' + id + '"]');
    if (!tr) return {};
    const заголовки = [...грид.querySelectorAll('thead tr:first-child th')].map((th) => (th.textContent || '').replace(/\s+/g, ' ').trim());
    const i = заголовки.findIndex((t) => /^мастер$/i.test(t));
    const master = i >= 0 && tr.children[i] ? (tr.children[i].textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60) : '';
    return { master, okk: /is_okk_guarantee/.test(tr.getAttribute('class') || '') };
  }
  // «Сумма, оплаченная клиентом: 2 500 р.» → 2500; нет строки — undefined (не знаем)
  function оплачено(doc) {
    const b = [...doc.querySelectorAll('b, strong')].find((e) => /Сумма,?\s+оплаченная\s+клиентом/i.test(e.textContent || ''));
    if (!b || !b.parentElement) return undefined;
    const m = (b.parentElement.textContent || '').replace(/[\s\u00a0]+/g, ' ').match(/оплаченная\s+клиентом:?\s*(\d[\d ]*(?:[.,]\d+)?)/i);
    return m ? Math.round(Number(m[1].replace(/ /g, '').replace(',', '.'))) : undefined;
  }
  // клиент заявки — в её карточке: CustomerRequest[customer_id] (select, в карточке disabled) или ссылка «Карточка клиента»
  function клиентЗаявкиИз(doc) {
    const e = doc.querySelector('[name="CustomerRequest[customer_id]"]');
    let v = '';
    if (e && e.tagName === 'SELECT') { const o = [...e.options].find((x) => x.selected || x.hasAttribute('selected')); v = (o && o.value) || e.value || ''; }
    else if (e) v = e.value || e.getAttribute('value') || '';
    if (!/^\d+$/.test(String(v))) { const a = doc.querySelector('a[href*="/customer/update?id="]'); v = a ? ((a.getAttribute('href') || '').match(/[?&]id=(\d+)/) || [])[1] || '' : ''; }
    return /^\d+$/.test(String(v)) ? String(v) : '';
  }
  /* Адрес для сравнения: регистр, «ё», «ул./улица/пр-т/проспект/пер./д./дом», точки и запятые не важны.
     Улица — по основам слов (падеж: «Невская» = «Невской», «1-я» = «1»), дом — без пробелов («5 к 2» = «5к2» = «5 корп 2»),
     нас. пункт — без типа («деревня Сосново» = «д. Сосново»). Ложное «другой дом» стоило бы клиенту квартиры (её чистим) */
  const ТИП_АДРЕСА = '(?:улица|ул|проспект|пр-кт|пр-т|переулок|пер|дом|д)';
  const адресКлюч = (s) => norm(s).replace(new RegExp('(^|[\\s,])' + ТИП_АДРЕСА + '\\.(?=[^\\s,.])', 'g'), '$1 ')
    .replace(new RegExp('(^|[\\s,])' + ТИП_АДРЕСА + '\\.?(?=[\\s,]|$|\\d)', 'g'), '$1 ').replace(/[,.«»"]/g, ' ').replace(/\s+/g, ' ').trim();
  const основа = (w) => (/^\d/.test(w) ? w : w.length <= 4 ? w.slice(0, 3) : w.slice(0, Math.max(4, Math.min(6, w.length - 2))));
  /* Улица: тип — отдельно от названия (типы — как в extract.js / LeadChat street_core). «пр. Мира» = «Мира»: иначе тот же дом
     сочли бы другим и стёрли кв / подъезд / этаж. Но тип, названный с ОБЕИХ сторон, и род названия различают улицы:
     «ул. Мира» ≠ «пр-т Мира», «Октябрьская» ≠ «Октябрьский пр-т» (основа одна) — иначе клиенту остался бы старый адрес */
  const ТИП_УЛИЦЫ = { улица: 'ул', ул: 'ул', проспект: 'пр', просп: 'пр', пр: 'пр', 'пр-кт': 'пр', 'пр-т': 'пр', переулок: 'пер', пер: 'пер', шоссе: 'ш', ш: 'ш',
    бульвар: 'б', 'б-р': 'б', бул: 'б', проезд: 'прд', 'пр-д': 'прд', площадь: 'пл', пл: 'пл', набережная: 'наб', наб: 'наб', тупик: 'туп', туп: 'туп',
    аллея: 'ал', линия: 'лин', тракт: 'тр', территория: 'тер', тер: 'тер', микрорайон: 'мкр', мкр: 'мкр', мкрн: 'мкр', квартал: 'квл', 'кв-л': 'квл', сектор: 'сек' };
  // звание и «имени» в названии: «им. Ленина» = «Ленина», «Маршала Жукова» = «Жукова», «Академика Королёва» = «Королёва»
  const ЗВАНИЕ = /^(?:им|имени|маршала|генерала|адмирала|академика|героя|космонавта|летчика|писателя|поэта|композитора|профессора|архитектора|художника|полководца|капитана|лейтенанта|майора|полковника|сержанта)$/;
  function улицаЧасти(s) {
    const слова = norm(s).replace(/(\d+)[\s-]*лет(?:ия|ию|ием|ии)?(?![а-я])/g, '$1лет')      // «50 лет Октября» = «50-летия Октября»
      .split(/[^0-9a-zа-я-]+/).map((w) => w.replace(/^-+|-+$/g, '').replace(/^(\d+)-?(?:ая|ья|я|ой|ий|ый|й|го|е|ое)$/, '$1')).filter(Boolean);
    const безТипа = слова.filter((w) => !ТИП_УЛИЦЫ[w]);
    const ядро = безТипа.some((w) => !ЗВАНИЕ.test(w)) ? безТипа.filter((w) => !ЗВАНИЕ.test(w)) : безТипа;
    return { ядро: ядро.length ? ядро : слова, тип: ядро.length ? [...new Set(слова.filter((w) => ТИП_УЛИЦЫ[w]).map((w) => ТИП_УЛИЦЫ[w]))].sort().join(',') : '' };
  }
  const улицаКлюч = (s) => улицаЧасти(s).ядро.map(основа).sort().join(' ');
  // род — только по явному окончанию им. падежа («-ой» бывает и «Невской», и «Большой» — не считаем)
  const род = (w) => (/(ая|яя)$/.test(w) ? 'ж' : /(ий|ый)$/.test(w) ? 'м' : /(ое|ее)$/.test(w) ? 'с' : '');
  /* Слова названия — попарно: та же основа или сокращение («К.» = «Карла», «Н.» = «Нижняя», «Ст.» = «Старая»: 1–2 буквы — начало
     слова; «Б.» ≠ «Малая»). И имя перед фамилией можно опустить («Карла Маркса» = «Маркса», «Льва Толстого» = «Толстого»): одно лишнее
     слово впереди — не число, не прилагательное («Большая Садовая» ≠ «Садовая», «1-я Тверская-Ямская» ≠ «Тверская-Ямская»), не вид
     улицы, которого нет в типах («спуск Чкалова» ≠ «Чкалова»); «Алексея Толстого» ≠ «Льва Толстого» */
  const сокращение = (a, b) => a.length <= 2 && b.length > 2 && !/\d/.test(a + b) && b.startsWith(a);
  const словоТоже = (a, b) => основа(a) === основа(b) || сокращение(a, b) || сокращение(b, a);
  const НЕ_ИМЯ = /^(?:спуск|въезд|съезд|заезд|разъезд|дорога|просека|кольцо|луч|городок|парк|сквер|сад|станция|слобода|роща|поляна|гора|горка|вал|ряд|остров|берег|км|километр)$/;
  function словаСовпадают(x, y) {
    if (x.length > y.length) [x, y] = [y, x];
    if (!x.length || y.length - x.length > 1) return false;
    const свободны = y.slice();
    const взять = (w, f) => { const i = свободны.findIndex((v) => f(w, v)); if (i < 0) return false; свободны.splice(i, 1); return true; };
    if (!x.filter((w) => !взять(w, (a, b) => основа(a) === основа(b))).every((w) => взять(w, словоТоже))) return false;
    if (!свободны.length) return true;
    const лишнее = свободны[0];
    // при опущенном слове остальные — слово в слово, не по основе: «Панфилова» ≠ «Героев Панфиловцев» (основа одна), и не прилагательное
    // в род. падеже: «Ленинского Комсомола» ≠ «Комсомола», «Красного Октября» ≠ «Октября»
    return x.every((w) => y.includes(w)) && лишнее !== y[y.length - 1] && лишнее.length >= 3 && !/\d/.test(лишнее) && !/(?:ая|яя|ий|ый|ой|ое|ее|ые|ие|ых|их|ого|его)$/.test(лишнее)
      && !НЕ_ИМЯ.test(лишнее) && x.some((w) => w.length >= 4 && !/\d/.test(w));
  }
  /* Инициалы имени можно опустить: «К. Маркса» = «Маркса», «В.И. Ленина» = «Ленина», «М. Горького» = «Горького» — если инициалы
     только с одной стороны (до двух), остальные слова те же и среди них нет прилагательного: «Б. Садовая» (Большая) ≠ «Садовая»,
     «Б. Полянка» ≠ «М. Полянка», «Л. Толстого» ≠ «Алексея Толстого» */
  const инициал = (w) => w.length === 1 && /[а-яё]/.test(w);
  function безИнициалов(x, y) {
    const ix = x.filter(инициал).length, iy = y.filter(инициал).length;
    if (!ix === !iy || ix + iy > 2) return false;
    const a = (ix ? x : y).filter((w) => !инициал(w)), b = ix ? y : x;
    const ключ = (s) => s.map(основа).sort().join(' ');
    return a.length === b.length && ключ(a) === ключ(b) && a.some((w) => w.length >= 4 && !/\d/.test(w))
      && !a.some((w) => /(?:ая|яя|ий|ый|ое|ее|ой)$/.test(w));
  }
  function таЖеУлица(a, b) {
    const x = улицаЧасти(a), y = улицаЧасти(b);
    if (улицаКлюч(a) !== улицаКлюч(b) && !словаСовпадают(x.ядро, y.ядро) && !безИнициалов(x.ядро, y.ядро)) return false;
    if (x.тип && y.тип && x.тип !== y.тип) return false;
    return !родаРазные(x.ядро, y.ядро);
  }
  // слово с той же основой, но другого рода: «Октябрьская» / «Октябрьский», «посёлок Октябрьский» / «село Октябрьское»
  function родаРазные(x, y) {
    const роды = new Map(x.map((w) => [основа(w), род(w)]));
    return y.some((w) => { const р1 = роды.get(основа(w)), р2 = род(w); return !!р1 && !!р2 && р1 !== р2; });
  }
  const домКлюч = (s) => адресКлюч(s).replace(/(?:корпус|корп|кор)\s*/g, 'к').replace(/(?:строение|стр)\s*/g, 'с').replace(/(?:литера|лит)\s*/g, '')
    // Дробь — часть написанного номера, а не доказанный корпус: 5/2 ≠ 5к2.
    .replace(/\s+/g, '').replace(/^0+(?=\d)/, '');
  const словаНП = (s) => адресКлюч(s).replace(/(^|\s)(?:пос[её]лок|пос|п|пгт|рп|деревня|дер|село|с|снт|днп|днт|тсн|станица|хутор|х|город|гор|г)(?=\s|$)/g, ' ')
    .split(' ').filter(Boolean);
  const нпКлюч = (s) => словаНП(s).map(основа).sort().join(' ');
  const КЛЮЧ = { locality: нпКлюч, street: улицаКлюч, building: домКлюч, office: адресКлюч, entrance: адресКлюч, floor: адресКлюч };
  // одно и то же значение части адреса (улица — с типом и родом, остальное — по ключу)
  const одно = (k, a, b) => (k === 'street' ? таЖеУлица(a || '', b || '') : КЛЮЧ[k](a || '') === КЛЮЧ[k](b || '')
    && (k !== 'locality' || !родаРазные(словаНП(a || ''), словаНП(b || ''))));
  const строкаАдреса = (a) => [a.locality, a.street, a.building, a.office && 'кв ' + a.office, a.entrance && 'подъезд ' + a.entrance, a.floor && 'этаж ' + a.floor]
    .filter(Boolean).join(', ');
  const маскаТел = (d) => '+7 ' + d.slice(0, 3) + '-' + d.slice(3, 6) + '-' + d.slice(6);
  const тел10 = (s) => String(s || '').replace(/\D/g, '').slice(-10);
  const телефоныКлиента = (form) => [...form.elements].filter((e) => /^Customer\[contact_phones\]\[[^\]]+\]\[v\]$/.test(e.name || '')).map((e) => тел10(e.value)).filter((p) => p.length === 10);

  /* План правки карточки клиента (без записи): какие поля поставить, что поменяется словами, адрес до и после.
     ДРУГОЙ ДОМ (нас. пункт / улица / дом) — пишем весь адрес, и кв / подъезд / этаж тоже: старые принадлежали старому дому
     (нет в новом — очищаем); ФИАС и точку старого дома очищаем. ТОТ ЖЕ ДОМ — только кв / подъезд / этаж, которые клиент назвал
     и они другие. Домофон — явное «да» или «нет»; неизвестное состояние не меняем. Адреса без дома нет — адрес не трогаем */
  function планКлиента(form, addr, phonesExtra) {
    const a = addr || {};
    const s = (v) => String(v || '').trim();
    const нов = { locality: s(a.settlement), street: s(a.street), building: s(a.building), office: s(a.office), entrance: s(a.entrance), floor: s(a.floor) };
    const было = {};
    for (const [k, n] of Object.entries(АДРЕС_КЛИЕНТА)) { const e = полеФормы(form, n); было[k] = e ? s(e.value) : null; }
    const out = { ставим: {}, changed: [], house: false, line: '', was: строкаАдреса(Object.fromEntries(Object.entries(было).map(([k, v]) => [k, v || '']))), error: '', неВлезли: [] };
    const поставить = (k, v) => { out.ставим[АДРЕС_КЛИЕНТА[k]] = v; };
    const иначе = (k) => !одно(k, нов[k], было[k]);
    const итог = { ...Object.fromEntries(Object.entries(было).map(([k, v]) => [k, v || ''])) };
    if (нов.building && (нов.street || нов.locality)) {
      if (было.street === null || было.building === null) out.error = 'в карточке клиента нет полей адреса';
      else {
        out.house = иначе('street') || иначе('building') || (!!нов.locality && иначе('locality'));
        const какие = out.house ? Object.keys(АДРЕС_КЛИЕНТА) : Object.keys(ЧАСТИ_АДРЕСА).filter((k) => нов[k]);
        for (const k of какие) {
          if (было[k] === null) { if (нов[k]) out.error = 'в карточке клиента нет поля «' + (ЧАСТИ_АДРЕСА[k] || k) + '»'; continue; }
          if (!иначе(k)) continue;
          поставить(k, нов[k]); итог[k] = нов[k];
          const слово = ЧАСТИ_АДРЕСА[k] || 'адрес';
          if (!out.changed.includes(слово)) out.changed.push(слово);
        }
        if (out.house) {
          // ФИАС и точка на карте описывают старый дом
          for (const n of ['Customer[address_fias]', 'Customer[location]']) { const e = полеФормы(form, n); if (e && s(e.value)) out.ставим[n] = ''; }
        }
      }
    }
    const dom = intercomChoice(form, a);
    if (dom.error && typeof a.has_intercom === 'boolean') out.error = dom.error;
    if (dom.value !== null && intercomValue(intercomElement(form)) !== (dom.wanted ? '1' : '0')) {
      out.ставим[ДОМОФОН] = dom.value; out.changed.push('домофон');
    }
    // доп. номера: которых у клиента ещё нет — первый в пустую строку «добавить телефон», остальные — оператору
    const есть = new Set(телефоныКлиента(form));
    const доп = [...new Set((phonesExtra || []).map(тел10))].filter((p) => p.length === 10 && !есть.has(p));
    const пустая = полеФормы(form, 'Customer[contact_phones][0][v]');
    if (доп.length && пустая && !s(пустая.value)) {
      out.ставим['Customer[contact_phones][0][v]'] = маскаТел(доп.shift());
      if (полеФормы(form, 'Customer[contact_phones][0][title]')) out.ставим['Customer[contact_phones][0][title]'] = '';
      out.changed.push('доп. номер');
    }
    out.неВлезли = доп;
    out.line = строкаАдреса(итог);
    return out;
  }

  /* Запись карточки клиента — со сроком 20 с, без повтора: зависшая CRM не держит ответ «заявка создана» (заявка уже есть).
     Правка идемпотентна (тот же адрес второй раз — то же самое), поэтому срок здесь безопасен — в отличие от создания заявки */
  // как кнопки самой CRM (saveAndClose → form.submit()): обычной отправкой формы, без X-Requested-With — фоновым запросом CRM правку не сохраняла (09.10)
  const АДРЕС_НЕ_ТОТ = 'АДРЕС НЕ ТОТ: ';                                  // начало предупреждения — экран итога красит его красным
  const записьКлиента = (url, body) => getСрок(url, { method: 'POST', credentials: 'include', body }, 20000);

  // что из записанного карточка НЕ держит. ФИАС и точку не сверяем — CRM может сама заполнить их заново
  function несохранено(f2, ставим) {
    const не = [];
    for (const [n, v] of Object.entries(ставим)) {
      const k = Object.keys(АДРЕС_КЛИЕНТА).find((x) => АДРЕС_КЛИЕНТА[x] === n);
      if (k) { const e = полеФормы(f2, n); if (!e || !одно(k, e.value, v)) не.push((ЧАСТИ_АДРЕСА[k] || { locality: 'нас. пункт', street: 'улица', building: 'дом' }[k]) + ' «' + (e ? e.value : '—') + '»'); }
      else if (n === ДОМОФОН) { const e = intercomElement(f2), want = intercomValue(e, v); if (want === null || intercomValue(e) !== want) не.push('домофон'); }
      else if (n === 'Customer[contact_phones][0][v]' && !телефоныКлиента(f2).includes(тел10(v))) не.push('доп. номер ' + v);
    }
    return не;
  }
  /* Запись по заявке ушла без ответа (срок 20 с, сеть, 5xx шлюза, сверка не прочиталась) — CRM могла сохранить. Помним 30 мин, что
     меняли: повтор «Сделать» (или карточка, открытая заново) найдёт в карточке клиента уже новый адрес — и всё равно скажет, что
     поменялось, чтобы строка «Адрес изменён клиентом» в комментарий и новый дом в чат не потерялись. Только для той же заявки */
  const БЕЗ_ОТВЕТА = new Map();
  function записьБезОтвета(base, custId, заявка, form) {
    const н = заявка ? БЕЗ_ОТВЕТА.get(base + '|' + custId) : null;
    return н && н.заявка === заявка && Date.now() - н.at < 30 * 60e3 && !несохранено(form, н.ставим).length ? н : null;
  }

  /* ПРАВКА КАРТОЧКИ КЛИЕНТА: o = { addr, phonesExtra, заявка }. Ничего не меняется — без POST. После записи — читаем карточку снова и сверяем.
     Возвращает { ok, changed: ['адрес','квартира',…,'доп. номер'], line: адрес после, was: адрес до, house, url, error, warnings } */
  async function обновитьКлиента(base, custId, o) {
    o = o || {};
    const url = URL_КЛИЕНТА(base, custId);
    const out = { ok: false, changed: [], line: '', was: '', house: false, url, error: '', warnings: [] };
    try {
      const doc = await fetchDoc(url);
      const form = формаКлиента(doc);
      if (!form) return { ...out, error: 'карточка клиента не открылась' };
      const план = планКлиента(form, o.addr, o.phonesExtra);
      Object.assign(out, { line: план.line, was: план.was, house: план.house });
      if (план.неВлезли.length) out.warnings.push('доп. номер ' + план.неВлезли.map(маскаТел).join(', ') + ' не поместился — добавьте в карточке клиента');
      if (план.error) return { ...out, error: план.error };
      const kБО = base + '|' + custId;
      if (!Object.keys(план.ставим).length) {                                          // в карточке уже это — не пишем
        const н = записьБезОтвета(base, custId, o.заявка, form);                        // …а записали её мы, без ответа CRM
        if (н) { БЕЗ_ОТВЕТА.delete(kБО); return { ...out, ok: true, changed: н.changed, house: н.house, was: н.was }; }
        return { ...out, ok: true };
      }
      for (const [n, v] of Object.entries(план.ставим)) setVal(form, n, v);
      // форма — как пришла (имя, возраст, чёрный список, город, комментарий не трогаем); кнопки браузер без нажатия не шлёт
      const body = serializeForm(form);
      for (const e of form.elements) if (e.name && (e.tagName === 'BUTTON' || e.type === 'submit')) body.delete(e.name);
      // ответа нет (срок 20 с, сеть) или 5xx шлюза — CRM могла сохранить: не «не сменился», а сверка чтением.
      // Адрес формы относительный («/admin/…»): внутри расширения — дополняем адресом базы
      let resp = null, безОтвета = '';
      if(o.beforeSubmit){const guard=await o.beforeSubmit();if(!guard?.ok)return {...out,error:guard?.error||'Личная сессия остановлена'}}
      try { resp = await записьКлиента(new URL(form.getAttribute('action') || url, base).href, body); }
      catch (e) { безОтвета = суть(e).slice(0, 80); }
      if (resp) {
        // обычная отправка: CRM ответила 302, fetch прошёл по нему сам (resp.redirected) — это и есть «сохранила»; вход — сессия
        const redirectTo = (resp.headers && resp.headers.get('X-Redirect')) || (resp.redirected ? resp.url || '' : '');
        if (/default\/index|\/login/.test(redirectTo)) return { ...out, error: СЕССИЯ(имяПоАдресу(base)) };
        if (!(resp.status === 302 || redirectTo)) {
          const errors = formErrors(new DOMParser().parseFromString(await resp.text(), 'text/html'));
          if (errors.length || (resp.status >= 400 && resp.status < 500)) return { ...out, error: errors.slice(0, 2).join('; ') || 'CRM ответила ' + resp.status };
          if (resp.status >= 500) безОтвета = 'CRM ответила ошибкой ' + resp.status;
        }
      }
      // не знаем, сохранила ли (или запись ещё дойдёт): по заявке помним, что меняли — повтор не потеряет строк об адресе
      const помнить = () => { if (o.заявка) БЕЗ_ОТВЕТА.set(kБО, { заявка: o.заявка, ставим: план.ставим, changed: план.changed, house: план.house, was: план.was, at: Date.now() }); };
      const неясно = (почему) => { помнить(); return { ...out, error: почему + ' — не знаю, сохранила ли CRM: проверьте карточку клиента' }; };
      // сверка: CRM могла ответить «успех» и не сохранить
      let f2 = null;
      try { f2 = формаКлиента(await fetchDoc(url)); }
      catch (e) { return неясно((безОтвета ? безОтвета + '; ' : 'сохранение отправлено, ') + 'карточка клиента не перечиталась (' + суть(e).slice(0, 60) + ')'); }
      if (!f2) return неясно((безОтвета ? безОтвета + '; ' : '') + 'после сохранения карточка клиента не открылась');
      const не = несохранено(f2, план.ставим);
      if (не.length && безОтвета) { помнить(); return { ...out, error: безОтвета }; }       // пока не сохранила, но запись может ещё дойти
      if (не.length) return { ...out, error: 'CRM не сохранила: ' + не.join(', ') };
      БЕЗ_ОТВЕТА.delete(kБО);
      return { ...out, ok: true, changed: план.changed };
    } catch (e) {
      return { ...out, error: суть(e).slice(0, 100) };
    }
  }

  /* АДРЕС КЛИЕНТА ПО ЗАЯВКЕ — клиент назвал новый адрес уже созданной заявке: a = { dir, id (№ заявки), addr, dry }.
     Клиента берём из карточки заявки (у заявки он не меняется — помним 10 мин), правим его карточку.
     dry — только план (что поменяется), без записи: для карточки «по заявке» до нажатия «Сделать» */
  const КЛИЕНТ_ЗАЯВКИ = new Map();
  async function клиентЗаявки(base, id) {
    const k = base + '|' + id, c = КЛИЕНТ_ЗАЯВКИ.get(k);
    if (c && Date.now() - c.at < 10 * 60e3) return c.id;
    const custId = клиентЗаявкиИз(await fetchDoc(base + '/admin/domain/customer-request/update?id=' + encodeURIComponent(id)));
    if (custId) КЛИЕНТ_ЗАЯВКИ.set(k, { id: custId, at: Date.now() });
    return custId;
  }
  async function customerAddress(a) {
    a = a || {};
    const base = BASES[a.dir];
    if (!base || !a.id) return { ok: false, error: 'нет заявки' };
    const custId = await клиентЗаявки(base, a.id);
    if (!custId) return { ok: false, error: 'в карточке заявки № ' + a.id + ' не нашёлся клиент' };
    const заявка = String(a.id);
    if (!a.dry) return обновитьКлиента(base, custId, { addr: a.addr, заявка });
    const url = URL_КЛИЕНТА(base, custId);
    const form = формаКлиента(await fetchDoc(url));
    if (!form) return { ok: false, error: 'карточка клиента не открылась', url };
    const план = планКлиента(form, a.addr, []);
    // прошлая запись по этой заявке ушла без ответа, а CRM её сохранила — план говорит, что тогда меняли (см. БЕЗ_ОТВЕТА)
    const н = !план.error && !Object.keys(план.ставим).length ? записьБезОтвета(base, custId, заявка, form) : null;
    if (н) return { ok: true, dry: true, changed: н.changed, line: план.line, was: н.was, house: н.house, url, error: '' };
    return { ok: !план.error, dry: true, changed: план.changed, line: план.line, was: план.was, house: план.house, url, error: план.error };
  }

  /* ПРОВЕРКА ПОСЛЕ СОЗДАНИЯ: открываем созданную заявку и сверяем, что CRM сохранила то, что мы
     отправили. Поле, которого нет в карточке, не считаем ошибкой; расхождение — предупреждение.
     Адреса в карточке заявки нет (он у клиента) — его сверяем по карточке клиента; не вышло — так и говорим, молча не пропускаем. */
  // видели (необязательно) — сюда кладём, что карточка показала по каждому сверенному полю (create решает по нему, нужна ли дозапись)
  async function verifyCreated(base, id, sent, видели) {
    const out = { checked: 0, diffs: [], fields: [] };
    try {
      const doc = await fetchDoc(base + '/admin/domain/customer-request/update?id=' + id);
      const form = doc.querySelector('#customerRequestForm') || doc.querySelector('form');
      if (!form) {
        if (sent.get('_advertiser_line')) out.diffs.push('Имя / аккаунт объявления проверить не удалось: карточка заявки не открылась.');
        if (sent.has('_intercom_presence_expected')) out.diffs.push('Домофон проверить не удалось: карточка заявки не открылась.');
        if (sent.get('_required_partner_review') === '1') out.diffs.push('Отзыв проверить не удалось: карточка заявки не открылась.');
        return out;
      }
      const advertiserLine = sent.get('_advertiser_line');
      if (advertiserLine) {
        const comments = form.elements['CustomerRequest[comments]'];
        const normalize = (s) => String(s || '').replace(/\s+/g, ' ').trim();
        out.checked++;
        if (comments && normalize(comments.value).includes(normalize(advertiserLine))) out.fields.push('имя / аккаунт объявления');
        else out.diffs.push('имя / аккаунт объявления в комментарии не сохранились: ожидалось «' + advertiserLine + '», в CRM «' + (comments ? comments.value : 'нет поля комментария') + '»');
      }
      const NAMES = { 'CustomerRequest[city_id]': 'город', 'CustomerRequest[appliance_type_id]': 'вид работ',
        'CustomerRequest[type]': 'тип', 'CustomerRequest[partner_id]': 'партнёр', 'Customer[address_street]': 'улица',
        'Customer[address_building]': 'дом', 'Customer[address_office]': 'квартира', 'CustomerRequest[opened_at]': 'дата',
        'cr_opened_at_time': 'время', 'CustomerRequest[partner_comment]': 'комментарий партнёра',
        'CustomerRequest[is_zakrep]': 'закреп' };
      const strict = sent.get('_personal_workflow') === '1';
      const intercomExpected = sent.get('_intercom_presence_expected');
      if (intercomExpected === '0' || intercomExpected === '1') NAMES[ДОМОФОН] = 'домофон';
      if(strict)Object.assign(NAMES,{'CustomerRequest[comments]':'комментарий','CustomerRequest[comments_service]':'служебный комментарий',
        'CustomerRequest[is_req_fback]':'отзыв','CustomerRequest[is_need_call_before_visit]':'звонок перед выездом',
        'Customer[phone]':'телефон','Customer[first_name]':'имя клиента',
        'Customer[address_locality]':'населённый пункт','Customer[address_entrance]':'подъезд','Customer[address_floor]':'этаж'});
      if (sent.get('_required_partner_review') === '1') NAMES['CustomerRequest[is_req_fback]'] = 'отзыв';
      const subEl = полеВидаУслуг(form);
      if (subEl && sent.get(subEl.name)) NAMES[subEl.name] = 'вид услуг';
      const цифры = (s) => String(s || '').replace(/\D/g, '');
      const уКлиента = [];                                             // поля адреса, которых в карточке заявки нет
      for (const [name, label] of Object.entries(NAMES)) {
        const strictField = strict || name === 'CustomerRequest[is_zakrep]' || name === 'CustomerRequest[is_req_fback]';
        const want = name === ДОМОФОН ? intercomExpected : name === 'CustomerRequest[partner_comment]' ? (sent.get(name) || sent.get('_partner_note')) : strictField ? sent.getAll(name).slice(-1)[0] : sent.get(name);
        if (!want) continue;
        if (name === ДОМОФОН) { уКлиента.push([name, label, want]); continue; }
        let el = form.elements[name];
        if(strictField&&el&&el.length!==undefined&&el.tagName===undefined)el=[...el].find(x=>x.type==='checkbox')||el[el.length-1];
        if (!el && /^Customer\[(?:address_|phone\]|first_name\])/.test(name)) { уКлиента.push([name, label, want]); continue; }
        if (!el || el.length !== undefined && el.tagName === undefined) {if(strictField)out.diffs.push(label+': поле CRM не найдено');continue;}
        let got = strictField&&el.type==='checkbox'?(el.checked?'1':'0'):(el.value || '');
        if (видели) видели[name] = got;
        if (el.tagName === 'SELECT' && !got) {if(strict)out.diffs.push(label+': поле CRM пустое');continue;}
        out.checked++;
        const same = name === 'CustomerRequest[opened_at]'
          ? (цифры(got).includes(цифры(want)) || цифры(got).includes(цифры(want).replace(/^(\d{2})(\d{2})(\d{4})$/, '$3$2$1')))
          : name === 'cr_opened_at_time' ? цифры(got).startsWith(цифры(want))
          : name === 'Customer[phone]' ? цифры(got).slice(-10)===цифры(want).slice(-10)
          : name === 'CustomerRequest[partner_comment]' ? got.toLowerCase().includes(want.trim().toLowerCase())
          : got.trim().toLowerCase() === want.trim().toLowerCase();
        if (!same) out.diffs.push(label + ': в CRM «' + got + '», отправлено «' + want + '»');
        else out.fields.push(label);
      }
      // адрес — в карточке клиента этой заявки (существующему клиенту его ставит обновитьКлиента — сверяем, что стоит там)
      if (уКлиента.length) {
        const custId = клиентЗаявкиИз(doc);
        let f2 = null, почему = custId ? '' : 'в карточке заявки нет клиента';
        if (custId) { try { f2 = формаКлиента(await fetchDoc(URL_КЛИЕНТА(base, custId))); if (!f2) почему = 'карточка клиента не открылась'; } catch (e) { почему = суть(e).slice(0, 60); } }
        const нет = [];
        for (const [name, label, want] of f2 ? уКлиента : []) {
          const el = name === ДОМОФОН ? intercomElement(f2) : полеФормы(f2, name);
          if (!el) { нет.push(label); continue; }
          out.checked++;
          const k = Object.keys(АДРЕС_КЛИЕНТА).find((x) => АДРЕС_КЛИЕНТА[x] === name);
          if (name === ДОМОФОН && видели) видели[name] = intercomValue(el);
          if (name === ДОМОФОН ? intercomValue(el) === want : k ? одно(k, el.value, want) : name==='Customer[phone]' ? цифры(el.value).slice(-10)===цифры(want).slice(-10) : String(el.value||'').trim().toLowerCase()===String(want).trim().toLowerCase()) out.fields.push(label);
          else out.diffs.push(label + ' в карточке клиента: в CRM «' + (el.value || '') + '», отправлено «' + want + '»');
        }
        if (!f2 || нет.length) out.diffs.push('адрес клиента проверить не удалось (' + (почему || 'в карточке клиента нет поля: ' + нет.join(', ')) + ')');
      }
    } catch (e) {
      out.diffs.push('проверить созданную заявку не удалось: ' + String(e.message || e).slice(0, 80));
    }
    return out;
  }

  /* СОЗДАНИЕ — по номеру одно за раз. Этот документ (offscreen) живёт дольше вкладки: оператор нажал «Создать», обновил страницу (F5)
     и нажал снова — первое создание ещё идёт здесь (замки вкладки перезагрузка отпустила), а CRM поиском не видит заявку, которую
     ещё сохраняет: вышла бы вторая. Второе по тому же номеру не начинаем. Отказ до отправки формы (в том числе сбой сети на чтении) —
     refused: заявка точно не создана (а не «не знаю, создалась ли») */
  const СОЗДАЮТСЯ = new Map();                                        // номер (10 цифр) → когда начали
  async function customerRequestIds(base, customerId) {
    try {
      const doc = await fetchDoc(base + '/admin/domain/customer/update?id=' + encodeURIComponent(customerId));
      if (doc.querySelector('input[type="password"], [name^="LoginForm["]')) return null;
      if (!формаКлиента(doc)) return null;
      if (doc.__finalUrl) {
        const source = new URL(doc.__finalUrl);
        if (source.origin !== base || source.pathname !== '/admin/domain/customer/update' || source.searchParams.get('id') !== String(customerId)) return null;
      }
      const ids = new Set();
      for (const link of doc.querySelectorAll('a[href*="customer-request/update"]')) {
        const u = new URL(link.getAttribute('href') || '', base);
        if (u.origin !== base || u.pathname !== '/admin/domain/customer-request/update') continue;
        const id = u.searchParams.get('id');
        if (/^\d{1,12}$/.test(id || '') && Number(id) > 0) ids.add(Number(id));
      }
      return [...ids];
    } catch (_e) { return null; }
  }
  async function recoverRequestId(base, customerId, before, sent) {
    if (!Array.isArray(before)) return null;
    const after = await customerRequestIds(base, customerId);
    if (!after) return null;
    const fresh = after.filter(id => !before.includes(id));
    if (fresh.length !== 1) return null;
    try {
      const id = fresh[0], doc = await fetchDoc(base + '/admin/domain/customer-request/update?id=' + id);
      if (doc.__finalUrl) {
        const source = new URL(doc.__finalUrl);
        if (source.origin !== base || source.pathname !== '/admin/domain/customer-request/update' || source.searchParams.get('id') !== String(id)) return null;
      }
      if (String(клиентЗаявкиИз(doc) || '') !== String(customerId)) return null;
      const form = doc.querySelector('#customerRequestForm');
      if (!form) return null;
      const names = ['CustomerRequest[city_id]', 'CustomerRequest[appliance_type_id]', 'CustomerRequest[partner_id]',
        'CustomerRequest[type]', 'CustomerRequest[comments]', 'CustomerRequest[opened_at]', 'cr_opened_at_time'];
      const sub = полеВидаУслуг(form); if (sub) names.push(sub.name);
      const normalize = value => String(value ?? '').replace(/\s+/g, ' ').trim();
      let checked = 0;
      for (const name of names) {
        const want = sent.get(name); if (!want) continue;
        const field = form.elements[name]; if (!field || !field.tagName) return null;
        const got = normalize(field.value);
        if (name === 'CustomerRequest[opened_at]') {
          const digits = value => value.replace(/\D/g, '');
          if (![digits(want), digits(want).replace(/^(\d{2})(\d{2})(\d{4})$/, '$3$2$1')].includes(digits(got))) return null;
        } else if (name === 'cr_opened_at_time') {
          if (got.slice(0, 5) !== normalize(want).slice(0, 5)) return null;
        } else if (got !== normalize(want)) return null;
        checked++;
      }
      return checked >= 4 ? id : null;
    } catch (_e) { return null; }
  }
  function наблюдатьОтправку(promise, ход) {
    if (!ход.срок) ход.срок = Date.now() + 120000;
    let timer;
    const deadline = new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('CRM не подтвердила отправку за 120 с; повтор запрещён')), Math.max(0, ход.срок - Date.now()));
    });
    // Не abort: сервер мог уже сохранить форму. Поздний fetch только завершает
    // исходное обещание, а код после await при таймауте больше не выполняется.
    return Promise.race([promise, deadline]).finally(() => clearTimeout(timer));
  }
  async function create(p) {
    const d10 = String((p && p.lead && p.lead.phone) || '').replace(/\D/g, '').slice(-10);
    const было = d10.length === 10 ? СОЗДАЮТСЯ.get(d10) : 0;
    if (было) return { ok: false, skipped: true, refused: true,
      error: 'по этому номеру заявка ещё создаётся (прошлое нажатие «Создать» — до перезагрузки страницы) — вторую не создаю. Подождите минуту и проверьте CRM по номеру' };
    const t = Date.now(), ход = { отправлено: false };
    ход.наблюдать = promise => наблюдатьОтправку(promise, ход);
    if (d10.length === 10) СОЗДАЮТСЯ.set(d10, t);
    let outcome;
    try {
      outcome = await создатьЗаявку(p, ход);
      return { ...outcome, crm_create_dispatched: ход.отправлено };
    }
    catch (e) {
      const msg = String((e && e.message) || e).slice(0, 120);
      if (!ход.отправлено) return { ok: false, refused: true, crm_create_dispatched: false, error: msg };
      // форма ушла в CRM, дальше исключение (оборвалось чтение ответа — «network error», сеть, поиск №): итог — «не знаю, создалась ли»,
      // а не «не создана» по словам ошибки браузера (оператор нажал бы «Создать» ещё раз — вторая заявка)
      return { ok: false, unknown: true, crm_create_dispatched: true, ...(ход.id ? { id: ход.id } : {}), errors: [], warnings: [], url: ход.id ? BASES[p.dir] + '/admin/domain/customer-request/update?id=' + ход.id : '',
        error: 'сбой после отправки формы в CRM (' + msg + ') — заявка ' + (ход.id ? '№' + ход.id + ' ' : '') + 'могла создаться' };
    }
    finally {
      if ((!ход.отправлено || outcome?.ok === true || outcome?.crm_create_rejected === true) && СОЗДАЮТСЯ.get(d10) === t) СОЗДАЮТСЯ.delete(d10);
    }
  }
  /* lead — проверенные поля, sel — выбор оператора (cityId, applId, subId, type); ход.отправлено — форма ушла в CRM */
  async function создатьЗаявку(p, ход) {
    const { dir, lead, sel } = p;
    const controlled=!!(p.personalWorkflow||p.nativeOffice);
    const requiredReview = String(lead.partner || '').replace(/\D/g, '').replace(/^0+/, '') === '624';
    if (controlled && requiredReview && lead.review !== true)
      return {ok:false,refused:true,error:'Для партнёра 624 отметка «Отзыв» обязательна в подтверждённой заявке'};
    if(p.nativeOffice&&(p.personalWorkflow||typeof p._beforeSubmit!=='function'||typeof p._created!=='function'))
      return {ok:false,refused:true,error:'Не подключена проверка серверного исполнителя CRM'};
    const base = BASES[dir];
    const warnings = [];
    if (!base) return { ok: false, error: 'не выбрано направление' };
    if (lead.ad_identity_required && !String(lead.ad_identity || '').trim())
      return { ok: false, refused: true, error: 'Укажите имя мастера из объявления или название аккаунта.' };
    if (lead.ad_identity && !String(lead.comment || '').includes('Объявление: «' + lead.ad_identity + '».'))
      return { ok: false, refused: true, error: 'Имя / аккаунт объявления отсутствуют в комментарии — откройте форму заявки заново.' };
    // чтения перед отправкой — разом, а не по очереди: поиск клиента, номер во всех базах (свежим чтением CRM, без кэша) и форма
    // создания. Решения — в прежнем порядке и все до POST; сбой чтения всплывает там же, где всплыл бы при чтении по очереди
    const поискВБазах = p.allowLive ? null : заранее(searchAllBases(lead.phone));
    // форма без клиента — как только первый вариант номера клиента не нашёл (см. findCustomerId)
    let формаБезКлиента = null;
    const безКлиента = () => формаБезКлиента || (формаБезКлиента = заранее(fetchDoc(base + CREATE)));
    const cust = await findCustomerId(base, lead.phone, безКлиента);
    // CRM не ответила на поиск клиента (срок чтения 15 с, сеть) — не знаем, есть ли он и его заявки: вслепую не создаём
    if (cust.вход) return { ok: false, error: СЕССИЯ(ИМЯ[dir]) };
    if (cust.сбой) return { ok: false, refused: true, error: 'CRM ' + ИМЯ[dir] + ' не ответила на поиск клиента по номеру (' + cust.сбой.slice(0, 60) + ') — вслепую не создаю, нажмите «Создать» ещё раз' };
    if (cust.count > 1) return { ok: false, error: 'в CRM ' + cust.count + ' клиента с этим телефоном — создайте вручную' };
    const createUrl = base + CREATE + (cust.id ? '?customer_id=' + cust.id : '');
    // клиент есть — форма с ним, вместе с его историей
    const форма = cust.id ? заранее(fetchDoc(createUrl)) : безКлиента();
    if (!p.allowLive) {
      const живая = cust.id ? (await customerStatuses(base, cust.id)).find((t) => ЖИВЫЕ.test(t)) : '';
      if (живая) return { ok: false, skipped: true, reason_code: 'crm_existing_request', error: МОДЕРАЦИЯ.test(живая) ? модерацияТекст(null) : 'у клиента уже есть заявка «' + живая + '» — вторую не создаю' };
      // повторная проверка номера во всех базах прямо перед созданием (начата вместе с поиском клиента)
      const x = await поискВБазах();
      // своя база не проверилась (CRM не ответила за срок) — «заявки нет» не доказано: вторую вслепую не создаём
      const своя = (x.unchecked || []).find((u) => u.dir === dir);
      if (своя && !/нет входа/.test(своя.error || '')) return { ok: false, refused: true, error: 'номер в CRM ' + ИМЯ[dir] + ' не проверился перед созданием (' + String(своя.error || '').slice(0, 60) + ') — вслепую не создаю, нажмите «Создать» ещё раз' };
      const мод = x.found.find((r) => МОДЕРАЦИЯ.test(r.status || ''));
      if (мод) return { ok: false, skipped: true, reason_code: 'crm_existing_request', moderation: { dir: мод.dir, id: мод.id, url: мод.url }, error: модерацияТекст(мод) };
      const l = x.found.find((r) => ЖИВЫЕ.test(r.status));
      if (l) return { ok: false, skipped: true, reason_code: 'crm_existing_request', error: 'номер уже в работе: ' + ИМЯ[l.dir] + ' №' + l.id + ' «' + l.status + '» — вторую не создаю' };
      if (p.nativeOffice && (x.unchecked.length || x.found.some((r) => НЕ_СТАТУС.test(r.status?.trim() || '—')))) {
        return { ok: false, refused: true, error: 'Историю заявок по номеру не удалось проверить полностью — новая заявка не отправлена' };
      }
    }
    const doc = await форма();
    const form = doc.querySelector('#customerRequestForm') || doc.querySelector('form');
    if (!form) return { ok: false, error: 'форма создания не найдена' };

    if (!sel.cityId) return { ok: false, error: 'не выбран город' };
    setVal(form, 'CustomerRequest[city_id]', sel.cityId);

    // вид работ и вид услуг: опции переносим значением и текстом (без чужой разметки)
    const ставить = (name, list, id, label) => {
      const el = form.elements[name];
      if (!el || !id) return false;
      el.replaceChildren();
      for (const o of list || []) el.append(new Option(o.text, o.id));
      el.value = id;
      if (el.value !== id) { el.append(new Option(label, id, true, true)); el.value = id; }
      return true;
    };
    if (!ставить('CustomerRequest[appliance_type_id]', sel.appl, sel.applId, 'вид работ')) warnings.push('вид работ не поставлен');
    if (sel.subId && !/^\d+$/.test(String(sel.subId))) {
      warnings.push('вид услуг не поставлен: CRM ждёт номер, а пришло «' + String(sel.subId).slice(0, 30) + '» — выберите в карточке');
      sel.subId = '';
    }
    if (sel.subId) {
      const subEl = полеВидаУслуг(form);
      if (subEl) ставить(subEl.name, sel.sub, sel.subId, 'вид услуг');
      else warnings.push('вид услуг не поставлен: поля нет в форме');
    }
    // источник — в «Комментарий партнёра», отзыв — галочкой (как «автоотзыв» Чатерского)
    if (lead.partner_note) setVal(form, 'CustomerRequest[partner_comment]', lead.partner_note);
    if (lead.review || requiredReview) setVal(form, 'CustomerRequest[is_req_fback]', '1');

    // телефон — строго маской базы «+7 999-999-9999»
    const d10 = String(lead.phone || '').replace(/\D/g, '').slice(-10);
    if (d10.length !== 10) return { ok: false, error: 'нет телефона клиента' };
    const phoneMasked = '+7 ' + d10.slice(0, 3) + '-' + d10.slice(3, 6) + '-' + d10.slice(6);
    if (cust.id) setVal(form, 'CustomerRequest[customer_id]', cust.id);
    else {
      setVal(form, 'Customer[phone]', phoneMasked);
      if (lead.name) setVal(form, 'Customer[first_name]', lead.name);
      // имя — как в LeadChat, с № заявки (правило владельца); но одни цифры — это не имя (регламент: «не уточнил имя» — штраф)
      if (!/[a-zа-яё]/i.test(String(lead.name || ''))) warnings.push('имя клиента не указано — уточните у клиента и впишите в карточке');
    }
    // доп. номера клиента — в свободные «Телефон (доп.1–3)» (регламент), без повторов. Только новому клиенту: у существующего
    // CRM эти поля формы не сохраняет — его номера идут в карточку клиента (обновитьКлиента после создания)
    if (!cust.id) {
      const маска = (d) => '+7 ' + d.slice(0, 3) + '-' + d.slice(3, 6) + '-' + d.slice(6);
      const поля = ['Customer[phone_extra_1]', 'Customer[phone_extra_2]', 'Customer[phone_extra_3]'];
      const есть = new Set([d10, ...поля.map((k) => String((form.elements[k] || {}).value || '').replace(/\D/g, '').slice(-10)).filter(Boolean)]);
      const доп = [...new Set((lead.phones_extra || []).map((p) => String(p).replace(/\D/g, '').slice(-10)))].filter((p) => p.length === 10 && !есть.has(p));
      for (const k of поля) { if (!доп.length) break; const el = form.elements[k]; if (el && !String(el.value || '').trim()) setVal(form, k, маска(доп.shift())); }
      if (доп.length) warnings.push('доп. номер ' + доп.map(маска).join(', ') + ' не поместился — свободных граф «Телефон (доп.)» нет');
    }

    // адрес — по своим полям карточки
    const addr = lead.addr || {};
    if (addr.settlement) {
      const нп = [...form.elements].map((e) => e.name).find((n) => n && /settlement|nas_?punkt|locality/i.test(n));
      if (нп) setVal(form, нп, addr.settlement);
      else warnings.push('нас. пункт «' + addr.settlement + '» некуда положить');
    }
    const положено = { street: addr.street || '', building: addr.building || '', office: addr.office || '',
      entrance: addr.entrance || '', floor: addr.floor || '' };
    const непринятые = [];
    for (const [k, v] of Object.entries(положено)) if (v && !setVal(form, 'Customer[address_' + k + ']', v)) непринятые.push(k);
    const intercom = intercomChoice(form, addr);
    if (intercom.value !== null) setVal(form, ДОМОФОН, intercom.value);
    else if (intercom.error && !cust.id && typeof addr.has_intercom === 'boolean') return { ok: false, refused: true, error: intercom.error };
    if (непринятые.length) warnings.push('поля адреса не найдены в форме: ' + непринятые.join(', '));

    // дата и время визита — в формате поля CRM
    const dateEl = form.elements['CustomerRequest[opened_at]'];
    if (lead.visit_date && dateEl) {
      const [y, m, d] = lead.visit_date.split('-');
      dateEl.value = /^\d{4}-/.test(dateEl.value || '') ? lead.visit_date : `${d}.${m}.${y}`;
    }
    if (lead.visit_time) setVal(form, 'cr_opened_at_time', lead.visit_time);

    // 2.2.3: сомнение в адресе (addr_warn) в заявку не пишем — оператор видит его в панели до «Создать»: создал — значит проверил
    const comment = String(lead.comment || '');
    if (comment && !setVal(form, 'CustomerRequest[comments]', comment) && lead.ad_identity)
      return { ok: false, refused: true, error: 'В форме CRM нет поля комментария: имя / аккаунт объявления некуда записать.' };
    if (lead.service_comment) setVal(form, 'CustomerRequest[comments_service]', NOTES.service(lead.service_comment));
    // Explicit zero also clears a checkbox preselected by the CRM template.
    setVal(form, 'CustomerRequest[is_zakrep]', lead.is_zakrep ? '1' : '0');

    // тип: Впервые / Повтор / Гарантия
    const typeSel = form.elements['CustomerRequest[type]'];
    if (typeSel) {
      const хотим = sel.type || 'Впервые';
      const тип = pickOption(typeSel, хотим) || { 'Гарантия': '30', 'Повтор': '20', 'Впервые': '10' }[хотим];
      setVal(form, 'CustomerRequest[type]', тип);
    }
    // «Дальний выезд» — когда адрес вне территории филиала (по карте / регламенту) или отмечено вручную
    if (lead.far_ride) { if (!setVal(form, 'CustomerRequest[is_far_ride]', '1')) warnings.push('в форме CRM нет поля «Дальний выезд» — отметьте вручную'); }
    // 2.0.9: «Срочная» сразу при создании
    if (lead.urgent) { if (!setVal(form, 'CustomerRequest[is_urgent]', '1')) warnings.push('в форме CRM нет поля «Срочная» — отметьте вручную'); }
    if (lead.call_before_visit) setVal(form, 'CustomerRequest[is_need_call_before_visit]', '1');
    else if (lead.call_check) setVal(form, 'CustomerRequest[is_need_call_check]', '1');
    let requiredPartnerId = '';
    if (lead.partner) {
      const pid = pickNumber(form.elements['CustomerRequest[partner_id]'], lead.partner);
      if (pid) setVal(form, 'CustomerRequest[partner_id]', pid);
      else warnings.push('партнёр ' + lead.partner + ' не найден в справочнике CRM — поле пустое');
      if (requiredReview) requiredPartnerId = pid;
    }

    // Снимок до POST нужен только для безопасного восстановления после /index.
    // Не удалось прочитать историю — обычный точный ID всё ещё пригоден,
    // но выбирать последнюю старую заявку вместо новой запрещено.
    const beforeRequestIds = cust.id ? await customerRequestIds(base, cust.id) : [];
    const body = serializeForm(form);
    const cities = body.getAll('CustomerRequest[city_id]');
    if (!cities.length || cities.some(city => city !== String(sel.cityId)))
      return {ok:false,refused:true,error:'Выбранный филиал не подтверждён полем CRM. Заявка не отправлена.'};
    const partners = body.getAll('CustomerRequest[partner_id]');
    if (requiredReview && (!requiredPartnerId || !partners.length || partners.some(id => id !== requiredPartnerId)))
      return {ok:false,refused:true,error:'Партнёр 624 не подтверждён полем CRM. Заявка не отправлена.'};
    if (requiredReview && body.getAll('CustomerRequest[is_req_fback]').at(-1) !== '1')
      return {ok:false,refused:true,error:'CRM не приняла обязательную отметку «Отзыв» для партнёра 624. Заявка не отправлена.'};
    if(controlled){if(typeof p._beforeSubmit!=='function')return {ok:false,refused:true,error:'Не подключена проверка личного аккаунта'};const guard=await p._beforeSubmit({phase:'create_crm',dir});if(!guard?.ok||p.nativeOffice&&(!Number.isFinite(guard.dispatch_before)||Date.now()>=guard.dispatch_before*1000))return {ok:false,refused:true,error:guard?.error||'Личный аккаунт, данные или срок разрешения изменились — заявка не отправлена'}}
    body.set('save_close', '1');
    ход.отправлено = true;                                            // дальше сбой — «не знаю, создалась ли», а не «не создана»
    const observe = ход.наблюдать || (promise => promise);
    const resp = await observe(fetch(createUrl, { method: 'POST', credentials: 'include', body,
      headers: { 'X-Requested-With': 'XMLHttpRequest' } }));
    const адресВхода = (url) => {
      try { return /(?:^|\/)(?:login|default\/index)(?:\/|$)/i.test(new URL(url, base).pathname); }
      catch (_e) { return false; }
    };
    const номерКарточки = (url) => {
      try {
        const u = new URL(url, base);
        if (u.origin !== base || !/^\/admin\/domain\/customer-request\/(?:update|view)\/?$/.test(u.pathname)) return null;
        const id = u.searchParams.get('id');
        return /^\d{1,12}$/.test(id || '') && Number(id) > 0 ? Number(id) : null;
      } catch (_e) { return null; }
    };
    if (адресВхода(resp.url || '')) return { ok: false, unknown: true, error: СЕССИЯ(имяПоАдресу(base)) };
    const text = await observe(resp.text());
    const resDoc = new DOMParser().parseFromString(text, 'text/html');
    if (resDoc.querySelector('input[type="password"], [name^="LoginForm["]'))
      return { ok: false, unknown: true, error: СЕССИЯ(имяПоАдресу(base)) };
    const errors = formErrors(resDoc);
    const beforeFollowup = async (phase) => {
      if (ход.срок && Date.now() >= ход.срок) return { ok: false, error: 'Срок подтверждения CRM истёк; дозапись остановлена' };
      const guard=controlled?await p._beforeSubmit({phase,dir,id:String(ход.id||'')}):{ok:true};
      return p.nativeOffice&&(!Number.isFinite(guard?.dispatch_before)||Date.now()>=guard.dispatch_before*1000)
        ?{ok:false,error:'Срок разрешения на дозапись истёк'}:guard;
    };
    // Только для чтения сохранённой карточки: эта метка не отправляется в CRM.
    const advertiserLine = lead.ad_identity ? 'Объявление: «' + lead.ad_identity + '».' : '';
    if (advertiserLine) body.set('_advertiser_line', advertiserLine);
    if (controlled) body.set('_personal_workflow','1'); // Verification-only; never sent to CRM.
    if (requiredReview) body.set('_required_partner_review','1');
    if (intercomWanted(lead.addr) !== null) body.set('_intercom_presence_expected', intercomWanted(lead.addr) ? '1' : '0');
    // клиент уже был — адрес и доп. номера ставим в его карточку (форма создания их ему не сохранила). Только после созданной
    // заявки и один раз; сбой — предупреждение со ссылкой на карточку, заявка остаётся созданной (create не повторяем)
    // w — куда складывать предупреждения (при записи разом с комментарием — свой список, чтобы порядок предупреждений был прежним)
    const клиент = async (w) => {
      if (!cust.id) return {};
      const доп = (lead.phones_extra || []).filter((p) => тел10(p) !== d10);
      const ад = lead.addr || {};
      if (!ад.building && intercomWanted(ад) === null && !доп.length) return {};      // ставить в карточку клиента нечего — её и не открываем
      let c;
      try { c = await observe(обновитьКлиента(base, cust.id, { addr: lead.addr || {}, phonesExtra: доп, beforeSubmit: ()=>beforeFollowup('customer_contact') })); }
      catch (e) { c = { ok: false, changed: [], line: '', url: URL_КЛИЕНТА(base, cust.id), error: суть(e).slice(0, 100), warnings: [] }; }
      w.push(...(c.warnings || []));
      if (!c.ok) w.push('адрес клиента в CRM не обновился (' + (c.error || 'ошибка') + ') — поменяйте в карточке клиента: ' + c.url);
      // вторую заявку создали при живой («всё равно создать»): адрес у клиента общий для всех его заявок — сменился и в той
      else if (p.allowLive && c.house && (c.changed || []).includes('адрес')) w.push('адрес клиента сменился на «' + c.line
        + '» — он общий для всех заявок клиента: в его другой живой заявке теперь тоже этот адрес, проверьте её');
      return { customer: { ok: !!c.ok, changed: c.changed || [], line: c.line || '', url: c.url, error: c.error || '' },
        customerNote: !c.ok ? 'адрес клиента в CRM не обновился: ' + (c.error || 'ошибка')
          : (c.changed || []).length ? 'в карточке клиента обновлено: ' + c.changed.join(', ') + (c.line ? ' — ' + c.line : '') : '' };
    };
    // Yii может вернуть X-Redirect, но это ещё не подтверждение создания:
    // статус, тело, origin и точный номер проверяются до любых дозаписей.
    const responseAccepted = resp.status >= 200 && resp.status < 400;
    const redirectTo = responseAccepted ? (resp.headers.get('X-Redirect') || '') : '';
    let finalURL;
    try { finalURL = new URL(resp.url || createUrl, base); } catch (_e) { /* неизвестный результат */ }
    if (!finalURL || finalURL.origin !== base || !/^\/admin\/domain\/customer-request\/(?:create|update|view|index)\/?$/.test(finalURL.pathname))
      return { ok: false, unknown: true, warnings, errors: [], url: '', error: 'Адрес ответа CRM не подтверждён. Проверьте результат; повтор запрещён.' };
    if (responseAccepted && !errors.length && (redirectTo || номерКарточки(resp.url || '') || finalURL.pathname === '/admin/domain/customer-request/index')) {
      if (адресВхода(redirectTo)) return { ok: false, error: СЕССИЯ(имяПоАдресу(base)) };
      if (redirectTo) {
        let u;
        try { u = new URL(redirectTo, base); } catch (_e) { /* непонятный ответ — без служебных записей */ }
        if (!u || u.origin !== base || !/^\/admin\/domain\/customer-request\/(?:update|view|index)\/?$/.test(u.pathname))
          return { ok: false, unknown: true, warnings, errors: [], url: '', error: 'CRM вернула неподтверждённый адрес результата. Создалась ли заявка, нужно проверить; повтор запрещён.' };
      }
      const fromHeader = номерКарточки(redirectTo), fromURL = номерКарточки(resp.url || '');
      if (fromHeader && fromURL && fromHeader !== fromURL)
        return { ok: false, unknown: true, warnings, errors: [], url: '', error: 'Номера заявки в адресе и заголовке CRM различаются. Проверьте результат; повтор запрещён.' };
      let rid = fromHeader || fromURL;
      if (!rid && /\/customer-request\/index\/?$/.test(new URL(redirectTo || finalURL.href, base).pathname)) {
        const currentCustomer = cust.id ? cust : await findCustomerId(base, lead.phone);
        if (currentCustomer.id && !(currentCustomer.count > 1))
          rid = await recoverRequestId(base, currentCustomer.id, beforeRequestIds, body);
      }
      ход.id = rid || '';
      if (!rid) return { ok: false, unknown: true, warnings, errors: [], url: '',
        error: 'CRM перенаправила после отправки, но номер созданной заявки не подтверждён. Проверьте CRM; повтор запрещён.' };
      // Persist the actual new ID BEFORE any same-ID followup. A failed
      // callback leaves the original creation fenced; it is never a reason
      // to submit another request or continue writing without authority.
      if(p.nativeOffice){
        const saved=await p._created({id:String(rid),url:base+'/admin/domain/customer-request/update?id='+rid});
        if(saved?.ok!==true)throw Error('Номер созданной заявки не подтверждён серверным исполнителем; дозапись остановлена');
      }
      // комментарий партнёра: в форме создания поля может не быть — дозаписываем в карточку, как «Лид-бот → Заявки» (чтение + запись).
      // Поле было в форме и ушло с заметкой — дозапись нужна, только если сверка ниже не увидит заметку в карточке
      const неДописан = 'комментарий партнёра («' + lead.partner_note + '») не дописался — впишите в карточке';
      const вФорме = !!lead.partner_note && body.get('CustomerRequest[partner_comment]') === lead.partner_note;
      const дозапись = rid && lead.partner_note && !вФорме ? observe(saveComments(base, rid, lead.partner_note, ()=>beforeFollowup('partner_note'))) : null;
      // карточка клиента — другая карточка: её правим разом с дозаписью. Обе — до сверки: сверка читает адрес из карточки клиента
      const уКлиента = [];
      const [дописан, кл] = await Promise.all([дозапись, клиент(уКлиента)]);
      if (дозапись && !дописан) warnings.push(неДописан);
      warnings.push(...уКлиента);
      let verified = null;
      if (rid) {
        if (lead.partner_note) body.set('_partner_note', lead.partner_note);
        const видели = {};
        verified = await verifyCreated(base, rid, body, видели);
        // ушла в форме, а в карточке её нет (или карточка не прочиталась) — дозаписываем, как раньше, и сверяем заново
        if (вФорме && String(видели['CustomerRequest[partner_comment]'] ?? '').trim() !== String(lead.partner_note).trim()) {
          if (!(await observe(saveComments(base, rid, lead.partner_note, ()=>beforeFollowup('partner_note'))))) warnings.push(неДописан);
          verified = await verifyCreated(base, rid, body);
        }
        // 2.1.2 (штраф КП 2684667): адрес заявки CRM берёт из карточки клиента — расхождение там одним заметным предупреждением:
        // мастер поедет по адресу карточки. Остальные расхождения — как раньше, строками
        const адресНе = verified.diffs.filter((d) => /в карточке клиента|адрес клиента проверить не удалось/.test(d));
        for (const d of verified.diffs) if (!адресНе.includes(d)) warnings.push('⚠ ' + d);
        if (адресНе.length) {
          const кл0 = (кл && кл.customer && кл.customer.url) || (cust.id ? URL_КЛИЕНТА(base, cust.id) : '');
          warnings.push(АДРЕС_НЕ_ТОТ + адресНе.join('; ') + '. Мастер поедет по адресу из карточки клиента — исправьте её' + (кл0 ? ': ' + кл0 : ' в CRM'));
        }
      }
      return { ok: true, id: rid, warnings, verified, url: rid ? base + '/admin/domain/customer-request/update?id=' + rid : '', ...кл };
    }
    if (errors.length && [200, 400, 422].includes(resp.status) && !resp.headers.get('X-Redirect') &&
        finalURL.pathname === '/admin/domain/customer-request/create' && resDoc.querySelector('#customerRequestForm'))
      return { ok: false, refused: true, crm_create_rejected: true, errors: errors.slice(0, 6), warnings, url: '',
        error: 'CRM отклонила форму: ' + errors.slice(0, 3).join('; ') };
    return { ok: false, unknown: true, errors: errors.slice(0, 6), warnings, url: '',
      error: (errors.length ? 'CRM вернула ошибки формы' : 'CRM не подтвердила номер созданной заявки') +
        ' (статус ' + resp.status + '). Проверьте результат; повторная отправка остановлена.' };
  }

  /* ЗАКРЕП ГОРОДА — условия филиала под шкалой времени (расписание города на дату визита).
     Регламент: принимаем по закрепу (текст закрепа — в служебный комментарий) или пишем в город «№ не по закрепу». */
  async function zakrep(a) {
    const base = BASES[a.dir];
    if (!base || !a.cityId) return { ok: false, error: 'нет города' };
    const now = new Date();
    const d = /^\d{4}-\d{2}-\d{2}$/.test(a.date || '') ? a.date.slice(8, 10) + '-' + a.date.slice(5, 7) + '-' + a.date.slice(0, 4)
      : String(now.getDate()).padStart(2, '0') + '-' + String(now.getMonth() + 1).padStart(2, '0') + '-' + now.getFullYear();
    const t = /^\d{1,2}:\d{2}$/.test(a.time || '') ? a.time.padStart(5, '0') : '10:00';
    const doc = await fetchDoc(base + '/admin/domain/customer-request/city-timetable?city_id=' + encodeURIComponent(a.cityId) + '&on_date=' + d + '&on_time=' + t + '&cur_time=' + t);
    const text = ((doc.querySelector('.blockquote-small') || {}).textContent || '').replace(/\s+/g, ' ').trim();
    return { ok: true, text: text.slice(0, 600), date: a.date || '' };
  }

  /* ПЕРЕНОС В КАРТОЧКЕ — как оператор в CRM: новая дата + время, «Причина изменения времени» (Директор / Клиент / Диспетчер)
     уходит в CustomerRequest[cr_form_extra][timeChangeReason] текстом, строку в «Переносы» CRM дописывает сама.
     a: { dir, id, date: 'ГГГГ-ММ-ДД', time: 'ЧЧ:ММ', reason: 'Клиент' } */
  /* Свои переносы (пока работает расширение, 12 ч): «Сделать» перенесло, а дальше сбой (чат, комментарий, сверка не прочиталась) —
     повтор находит в карточке уже это время. Это не отказ: перенос сделан — ok, already и строка «Переносы» CRM для чата.
     Время, которое стояло и без нас («перенесите на то же»), — по-прежнему «в заявке уже стоит это время» */
  const ПЕРЕНОСЫ = new Map();
  const датаЦифрами = (v) => { const d = String(v || '').replace(/\D/g, ''); return /^\d{4}-/.test(String(v || '')) ? d.slice(6, 8) + d.slice(4, 6) + d.slice(0, 4) : d; };
  function reschedule(a) { return перенести(a, null); }
  // прочитана — карточка, которую вызывающий только что прочитал (возврат в «Ожидает»): второй раз подряд её не читаем
  async function перенести(a, прочитана) {
    const base = BASES[a.dir];
    if (!base || !a.id) return { ok: false, error: 'нет заявки' };
    if (!/^\d{4}-\d{2}-\d{2}$/.test(a.date || '') && !/^\d{1,2}:\d{2}$/.test(a.time || '')) return { ok: false, error: 'клиент не назвал новую дату или время' };
    const url = base + '/admin/domain/customer-request/update?id=' + a.id;
    const doc = прочитана || await fetchDoc(url);
    const form = doc.querySelector('#customerRequestForm');
    if (!form) return { ok: false, error: 'карточка заявки не открылась' };
    // статус и «Переносы» — из этой же страницы (до правки полей формы), а не вторым чтением той же карточки
    let before = null;
    try { before = карточкаИз(a.dir, a.id, doc); } catch (_e) { before = null; }
    if (before && ЗАКРЫТО.test(before.cardStatus || '')) return { ok: false, error: 'заявка уже «' + before.cardStatus + '» — переносить нечего' };
    const dateEl = form.elements['CustomerRequest[opened_at]'], timeEl = form.elements['cr_opened_at_time'];
    const reasonEl = form.elements['CustomerRequest[cr_form_extra][timeChangeReason]'];
    if (!dateEl || !timeEl) return { ok: false, error: 'в карточке нет полей даты и времени' };
    const былоДата = dateEl.value || '', былоВремя = timeEl.value || '';
    if (a.date) {
      const [y, m, d] = a.date.split('-');
      // формат — как в самом поле: «05-10-2026», «05.10.2026» или «2026-10-05»
      dateEl.value = /^\d{4}-/.test(былоДата) ? a.date : d + (/^\d{2}-/.test(былоДата) ? '-' : '.') + m + (/^\d{2}-/.test(былоДата) ? '-' : '.') + y;
    }
    if (a.time) timeEl.value = a.time.padStart(5, '0');
    const ключ = base + '|' + a.id, свой = ПЕРЕНОСЫ.get(ключ);
    if (dateEl.value === былоДата && timeEl.value === былоВремя) {
      if (!свой || свой.дата !== былоДата || свой.время !== былоВремя || Date.now() - свой.at > 12 * 3600e3) return { ok: false, error: 'в заявке уже стоит это время' };
      const last = (before && before.lastChange) || '', на = (last.match(/на\s*"([^"]+)"/) || [])[1] || '';
      return { ok: true, already: true, url, was: свой.было, now: былоДата + ' ' + былоВремя,
        lastChange: на.replace(/\D/g, '') === датаЦифрами(былоДата) + былоВремя.replace(/\D/g, '').slice(0, 4) ? last : '' };
    }
    if (reasonEl) reasonEl.value = a.reason || 'Клиент';
    const body = serializeForm(form);
    // до отправки: ответа может и не быть (сеть, 5xx шлюза), а CRM — перенести
    ПЕРЕНОСЫ.set(ключ, { дата: dateEl.value, время: timeEl.value, было: былоДата + ' ' + былоВремя, at: Date.now() });
    // адрес формы в CRM относительный («/admin/…»): внутри расширения его надо дополнить адресом базы, иначе «Failed to fetch»
    // как кнопка «Сохранить» CRM — обычной отправкой (фоновым запросом перенос в CRM не вставал, 09.10); итог решает перечитанная карточка
    const resp = await fetch(new URL(form.getAttribute('action') || url, base).href, { method: 'POST', credentials: 'include', body });
    const redirectTo = resp.headers.get('X-Redirect') || (resp.redirected && !/customer-request\/update/.test(resp.url || '') ? resp.url : '');
    if (/default\/index|\/login/.test(redirectTo)) { ПЕРЕНОСЫ.delete(ключ); return { ok: false, error: СЕССИЯ(имяПоАдресу(base)) }; }
    if (!(resp.status === 302 || redirectTo)) {
      const errors = formErrors(new DOMParser().parseFromString(await resp.text(), 'text/html'));
      if (errors.length || (resp.status >= 400 && resp.status < 500)) ПЕРЕНОСЫ.delete(ключ);     // CRM отказала — точно не перенесено
      if (errors.length || resp.status >= 400) return { ok: false, error: (errors.slice(0, 3).join('; ') || 'CRM ответила ' + resp.status) };
    }
    // сверяем перечитанной карточкой (одно чтение на всё): в ней новая дата/время и строка в «Переносах»
    const doc2 = await fetchDoc(url).catch(() => null);
    let after = null;
    try { after = doc2 ? карточкаИз(a.dir, a.id, doc2) : null; } catch (_e) { after = null; }
    if (!after) return { ok: false, error: 'перенос отправлен, а карточка заявки не перечиталась — проверьте время в CRM (повторное «Сделать» второй раз не перенесёт)', url };
    const цифры = (s) => String(s || '').replace(/\D/g, '');
    const стоит = after && (!a.date || цифры(after.visit).includes(a.date.slice(8, 10) + a.date.slice(5, 7)) || цифры(after.visit).includes(цифры(a.date)));
    const время2 = doc2.querySelector('#cr_opened_at_time') ? doc2.querySelector('#cr_opened_at_time').value : '';
    const времяОк = !a.time || !время2 || цифры(время2).startsWith(цифры(a.time.padStart(5, '0')));
    if (!стоит || !времяОк) { ПЕРЕНОСЫ.delete(ключ); return { ok: false, error: 'CRM не приняла перенос: в карточке ' + ((after && after.visit) || '?') + ' ' + время2, url }; }
    // строка «Переносы» — ровно её чатеры кидают в чат («Скопировать перенос» Чатерского: № + последняя строка)
    return { ok: true, url, was: былоДата + ' ' + былоВремя, now: (after.visit || '') + ' ' + время2, lastChange: after.lastChange && after.lastChange !== (before && before.lastChange) ? after.lastChange : '' };
  }

  /* 2.2.9: ссылка «Вернуть …» у отменённой заявки (cancel-transaction с data-confirm ВНУТРИ формы) — как кнопка CRM: yii.handleAction шлёт
     POST ВСЕЙ формы на адрес ссылки, обычной отправкой (не GET, как было с 1.18: принимает ли CRM GET — не проверялось). CRM не
     принимает POST (405) — ничего не сделано: тогда переходом по ссылке (GET), как раньше. Ссылки в карточке нет — как раньше (GET) */
  async function ссылкаОтмены(base, id, doc, сState) {
    const form = doc && doc.querySelector('#customerRequestForm');
    const a = form && [...form.querySelectorAll('a[href*="cancel-transaction"]')].find((x) => {
      const h = x.getAttribute('href') || '';
      return new RegExp('[?&]id=' + id + '(?!\\d)').test(h) && /[?&]state=1(?!\d)/.test(h) === !!сState;
    });
    const адрес = a ? new URL(a.getAttribute('href'), base).href : base + '/admin/domain/customer-request/cancel-transaction?id=' + encodeURIComponent(id) + (сState ? '&state=1' : '');
    if (!a) return fetch(адрес, { credentials: 'include' });
    const body = serializeForm(form);
    for (const e of form.elements) if (e.name && (e.tagName === 'BUTTON' || /^(submit|button|reset|image)$/i.test(e.type || ''))) body.delete(e.name);
    const r = await fetch(адрес, { method: 'POST', credentials: 'include', body });
    return r && r.status === 405 ? fetch(адрес, { credentials: 'include' }) : r;
  }

  /* ВЕРНУТЬ В «ОЖИДАЕТ» — кнопка CRM у отменённой заявки («Вернуть в работу отмененную заявку?»): cancel-transaction&state=1,
     потом новое время с причиной «Клиент». Регламент: отмена КЦ ≤ 3 дней / отмена филиала в том же месяце, тот же источник. */
  async function returnToAwait(a) {
    const base = BASES[a.dir];
    if (!base || !a.id) return { ok: false, error: 'нет заявки' };
    const url = base + '/admin/domain/customer-request/update?id=' + a.id;
    const doc0 = await fetchDoc(url);
    const before = карточкаИз(a.dir, a.id, doc0);
    if (!before) return { ok: false, error: 'карточка заявки не открылась' };
    if (!/отмен/i.test(before.cardStatus || '')) return { ok: false, error: 'заявка не в отмене — статус «' + (before.cardStatus || '?') + '»' };
    await ссылкаОтмены(base, a.id, doc0, true);
    // перечитанная после возврата карточка — и сверка статуса, и форма для переноса (перенос её второй раз не читает)
    const docA = await fetchDoc(url);
    const after = карточкаИз(a.dir, a.id, docA);
    if (!after || !/ожида/i.test(after.cardStatus || '')) return { ok: false, error: 'CRM не вернула: статус «' + ((after && after.cardStatus) || '?') + '»', url };
    let moved = null;
    if (a.date || a.time) { try { moved = await перенести({ dir: a.dir, id: a.id, date: a.date || '', time: a.time || '', reason: 'Клиент' }, docA); } catch (e) { moved = { ok: false, error: String(e.message || e) }; } }
    return { ok: true, url, status: after.cardStatus, moved: !!(moved && moved.ok), moveError: moved && !moved.ok ? moved.error : '', lastChange: (moved && moved.lastChange) || '' };
  }

  /* ВЕРНУТЬ В РАБОТУ — вторая кнопка CRM у отменённой заявки (cancel-transaction без state): заявка возвращается туда, где была
     до отмены (В пути / В работе). Как «Вернуть в «Ожидает»» — тем же запросом CRM, затем статус перечитываем */
  async function backToWork(a) {
    const base = BASES[a.dir];
    if (!base || !a.id) return { ok: false, error: 'нет заявки' };
    const url = base + '/admin/domain/customer-request/update?id=' + a.id;
    const doc0 = await fetchDoc(url);
    const before = карточкаИз(a.dir, a.id, doc0);
    if (!before) return { ok: false, error: 'карточка заявки не открылась' };
    if (!/отмен/i.test(before.cardStatus || '')) return { ok: false, error: 'заявка не в отмене — статус «' + (before.cardStatus || '?') + '»' };
    await ссылкаОтмены(base, a.id, doc0, false);
    const after = await requestInfo(a.dir, a.id);
    if (!after || /отмен/i.test(after.cardStatus || '')) return { ok: false, error: 'CRM не вернула: статус «' + ((after && after.cardStatus) || '?') + '»', url };
    return { ok: true, url, status: after.cardStatus };
  }

  /* ОТМЕНА КЦ — кнопка «Отмена КЦ» в карточке: форма целиком + cancel_kc=1 (пустой статус → 1, как делает сама CRM).
     Клиент отказался через нас — отменяет КЦ; в чат потом «№ Отмена» (как копирует Чатерское по статусу «Отмена КЦ»). */
  async function cancelKc(a) {
    const base = BASES[a.dir];
    if (!base || !a.id) return { ok: false, error: 'нет заявки' };
    const url = base + '/admin/domain/customer-request/update?id=' + a.id;
    // статус и форма — из одного чтения карточки (раньше читали её дважды подряд)
    const doc = await fetchDoc(url);
    const before = карточкаИз(a.dir, a.id, doc);
    if (!before) return { ok: false, error: 'карточка заявки не открылась' };
    if (/отмен/i.test(before.cardStatus || '')) return { ok: true, already: true, status: before.cardStatus, url };
    if (ЗАКРЫТО.test(before.cardStatus || '')) return { ok: false, error: 'заявка уже «' + before.cardStatus + '» — отменять нельзя' };
    const form = doc.querySelector('#customerRequestForm');
    if (!form) return { ok: false, error: 'карточка заявки не открылась' };
    // регламент: причину отмены пишем в «Комментарий» и в «Комментарий партнёра» (если партнёр есть)
    if (a.comment) {
      const c = form.elements['CustomerRequest[comments]'];
      if (c) c.value = [String(c.value || '').replace(/\s+$/, ''), a.comment].filter(Boolean).join('\n');
      const pc = form.elements['CustomerRequest[partner_comment]'], pid = form.elements['CustomerRequest[partner_id]'];
      if (pc && ((pid && pid.value) || String(pc.value || '').trim())) pc.value = [String(pc.value || '').replace(/\s+$/, ''), a.comment].filter(Boolean).join('\n');
    }
    // отмена из чата Авито — «Отмена с Авито» в служебный комментарий (как «отмена с дживы» в регламенте); при КЦ и при Филиале
    if (a.service) {
      const sc = form.elements['CustomerRequest[comments_service]'];
      if (sc && !String(sc.value || '').toLowerCase().includes(String(a.service).toLowerCase())) sc.value = [String(sc.value || '').replace(/\s+$/, ''), a.service].filter(Boolean).join('\n');
    }
    const st = form.elements['CustomerRequest[status]'];
    if (st && !st.value) st.value = '1';
    const body = serializeForm(form);
    // кнопки CRM: «Отмена КЦ» — cancel_kc=1, «Отмена Филиал» — cancel_branch=2 (как saveAndClose в карточке)
    if (a.by === 'branch') body.set('cancel_branch', '2'); else body.set('cancel_kc', '1');
    // адрес формы в CRM относительный («/admin/…»): внутри расширения его надо дополнить адресом базы, иначе «Failed to fetch»
    // как кнопки самой CRM (saveAndClose → form.submit()): обычной отправкой формы, без X-Requested-With — фоновым запросом CRM правку не сохраняла (09.10)
    const resp = await fetch(new URL(form.getAttribute('action') || url, base).href, { method: 'POST', credentials: 'include', body });
    const redirectTo = resp.headers.get('X-Redirect') || (resp.redirected && !/customer-request\/update/.test(resp.url || '') ? resp.url : '');
    if (/default\/index|\/login/.test(redirectTo)) return { ok: false, error: СЕССИЯ(имяПоАдресу(base)) };
    const after = await requestInfo(a.dir, a.id).catch(() => null);
    if (!after || !/отмен/i.test(after.cardStatus || '')) {
      let errors = [];
      if (!(resp.status === 302 || redirectTo)) { try { errors = formErrors(new DOMParser().parseFromString(await resp.text(), 'text/html')); } catch (_e) { /* не HTML */ } }
      return { ok: false, error: 'CRM не отменила: статус «' + ((after && after.cardStatus) || '?') + '»' + (errors.length ? ' — ' + errors.slice(0, 2).join('; ') : ''), url };
    }
    return { ok: true, status: after.cardStatus, by: a.by === 'branch' ? 'branch' : 'kc', url };
  }

  /* ПРЕТЕНЗИИ ПО ЗАЯВКЕ — список ОКК с фильтром по номеру заявки */
  async function claimsFor(dir, id) {
    const base = BASES[dir];
    if (!base || !id) return { count: 0, ids: [] };
    const doc = await fetchDoc(base + '/admin/domain/cr-claim/index?CrClaimSearch%5Bcr_id%5D=' + encodeURIComponent(id));
    const ids = [...new Set([...doc.querySelectorAll('table tbody tr a[href*="cr-claim/view?id="]')].map((a) => (a.getAttribute('href').match(/id=(\d+)/) || [])[1]).filter(Boolean))];
    // строка «Ничего не найдено» — пусто; иначе — номера претензий
    return { count: ids.length, ids };
  }

  /* ПРЕТЕНЗИЯ — кнопка «Претензия» в карточке: ссылка create-claim?id=… (в CRM — после «Создать претензию?»).
     Потом в чат «<база> Претензии/ Обратная связь…» пишут «№ новая претензия». */
  async function createClaim(a) {
    const base = BASES[a.dir];
    if (!base || !a.id) return { ok: false, error: 'нет заявки' };
    // одна претензия на заявку (регламент: есть — «снова звонит»): повтор «Сделать» после сбоя чата / комментария вторую не создаёт.
    // Список ОКК не прочитался (срок, 5xx) — вслепую не создаём; нет доступа к ОКК (4xx) — проверить нечем, как раньше
    try {
      const есть = await claimsFor(a.dir, a.id);
      if (есть.count) {
        const claimId = String(Math.max(...есть.ids.map(Number)));
        return { ok: true, already: true, url: base + '/admin/domain/cr-claim/view?id=' + claimId, claimId, typed: false };
      }
    } catch (e) {
      if (/Сессия/.test(String(e && e.message))) return { ok: false, error: СЕССИЯ(имяПоАдресу(base)) };
      if (!(e && e.status >= 400 && e.status < 500)) return { ok: false, error: 'не проверил, есть ли уже претензия по заявке (' + суть(e).slice(0, 60) + ') — вслепую не создаю, нажмите ещё раз' };
    }
    const r = await fetch(base + '/admin/domain/customer-request/create-claim?id=' + encodeURIComponent(a.id), { credentials: 'include', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
    const redirectTo = r.headers.get('X-Redirect') || '';
    const final = redirectTo || r.url || '';
    if (/default\/index|\/login/.test(final)) return { ok: false, error: СЕССИЯ(имяПоАдресу(base)) };
    let text = ''; try { text = await r.text(); } catch (_e) { /* пусто */ }
    const doc = new DOMParser().parseFromString(text || '', 'text/html');
    if (doc.querySelector('input[type="password"], [name^="LoginForm["]')) return { ok: false, error: СЕССИЯ(имяПоАдресу(base)) };
    const errors = [...doc.querySelectorAll('.alert-danger, .alert-error')].map((x) => x.textContent.trim().slice(0, 160)).filter(Boolean);
    if (r.status >= 400 || errors.length) return { ok: false, error: errors[0] || 'CRM ответила ' + r.status };
    const уже = /уже\s+(есть|создан)/i.test(text);
    // номер созданной претензии: адрес «cr-claim/view?id=…» или заголовок «Претензия: №45790 …»
    const claimId = ((final.match(/cr-claim\/view\?id=(\d+)/) || [])[1]) || ((doc.title || '').match(/Претензия:\s*№\s*(\d+)/) || [])[1] || '';
    const url = claimId ? base + '/admin/domain/cr-claim/view?id=' + claimId : (/claim/i.test(final) ? final : base + '/admin/domain/cr-claim/index');
    if (!claimId || (!a.typeNo && !a.comment)) return { ok: true, already: уже, url, claimId, typed: false };
    // тип и комментарий — как оператор в режиме редактирования претензии («Сохранить изменения»)
    try {
      const ed = await fetchDoc(base + '/admin/domain/cr-claim/view?id=' + claimId + '&_edit_mode=1');
      const form = [...ed.querySelectorAll('form')].find((f) => /_update=1/.test(f.getAttribute('action') || ''));
      if (!form) return { ok: true, already: уже, url, claimId, typed: false, warn: 'форма претензии не открылась — тип выберите в CRM' };
      const sel = form.elements['CrClaim[type]'];
      const opt = sel && [...sel.options].find((o) => new RegExp('^\\s*' + Number(a.typeNo) + '\\)').test(o.text));
      if (opt) sel.value = opt.value;
      const cm = form.elements['CrClaim[comment]'];
      if (cm && a.comment) cm.value = [String(cm.value || '').trim(), a.comment].filter(Boolean).join('\n').slice(0, 3000);
      const resp = await fetch(new URL(form.getAttribute('action'), base).href, { method: 'POST', credentials: 'include', body: serializeForm(form), headers: { 'X-Requested-With': 'XMLHttpRequest' } });
      const check = await fetchDoc(base + '/admin/domain/cr-claim/view?id=' + claimId + '&_edit_mode=1');
      const s2 = check.querySelector('select[name="CrClaim[type]"]');
      const typed = !!(opt && s2 && s2.value === opt.value);
      return { ok: true, already: уже, url, claimId, typed, type: opt ? opt.text.trim() : '', warn: typed ? '' : 'тип претензии не сохранился (ответ ' + resp.status + ') — выберите в CRM' };
    } catch (e) {
      return { ok: true, already: уже, url, claimId, typed: false, warn: 'тип не проставлен: ' + String(e.message || e).slice(0, 80) };
    }
  }

  return { prepare, create, saveCardComments, searchAllBases, reschedule, cancelKc, createClaim, zakrep, returnToAwait, backToWork, claimsFor, requestInfo, existing, applTypes, subTypes, pickOption, pickCity, pickNumber, синонимыТемы, начинаетсяСоСлова, BASES,
    customerAddress, обновитьКлиента, verifyCreated,
    subFor: async (dir, cityId, applId, appl, hasPartner) => безТеста((await subTypes(BASES[dir], cityId, applId, appl, null, null, hasPartner)).list), подсказки, разобратьСписок, кандидатыВидаУслуг,
    applFor: async (dir, cityId) => безТеста((await applTypes(BASES[dir], cityId, null)).list), безТеста,
    // 1.20: помощники для ядра действий (crmact.js) и карточки клиента (crmcust.js) — те же функции, без копий
    _внутр: { BASES, fetchDoc, serializeForm, formErrors, setVal, getСрок, обновитьКлиента, планКлиента, несохранено, intercomWanted, intercomChoice, intercomValue, ДОМОФОН,
      // для проверок: порядок вариантов при поиске разом; справочники забыть (тест подменил «CRM» целиком — это другая CRM)
      поПорядку, РАЗОМ, забытьСправочники: () => СПРАВОЧНИК.clear() } };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = CRM;
