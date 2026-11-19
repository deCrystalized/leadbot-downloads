/* КАРТОЧКА КЛИЕНТА ИЗ LEADCHAT (1.20, PE): верный адрес, другой номер, имя — в карточку клиента CRM
   (/admin/domain/customer/update?id=K, form#w0). Адрес, телефоны и имя CRM хранит у КЛИЕНТА, а не у заявки:
   карточка общая для всех его заявок. Приёмы — как в p12 (обновитьКлиента): форма как пришла, меняем только свои поля,
   POST один раз и без повтора, успех — только по повторному чтению карточки. Работает в offscreen рядом с crm.js.
   Наружу (в LeadChat) — номера только маской, без комментариев; имя и адрес — для превью оператору. */
const CRM_CUST = (() => {
  const К = (typeof CRM !== 'undefined' && CRM) || null;
  // помощники crm.js: после PA — общие (CRM._внутр), до него — свои копии того же поведения
  const вн = (имя, свой) => (К && К._внутр && typeof К._внутр[имя] === 'function' ? К._внутр[имя] : свой);
  const БАЗЫ = () => (К && К._внутр && К._внутр.BASES) || (К && К.BASES) || {};
  const ИМЯ_БАЗЫ = { kp: 'КП', mnc: 'МНЧ', bt: 'БТ' };

  /* Пороги — в одном месте. Разрешённые статусы приходят из плана (таблица LC_ACT_CUST); здесь — запасной список */
  const НАСТРОЙКИ = {
    статусы: [1, 4, 3, 2],          // владелец 08.10 (В8): Ожидает, В пути, На уточнении, Модерация
    срокЧтенияМс: 15000,
    срокЗаписиМс: 120000,           // §6.6: 2 мин без ответа — «не знаю, прошло ли», повтора нет
    срокКомментарияМс: 30000,       // строка в комментарий заявки: зависла — не держим замок вечно
    памятьНеизвестныхМс: 600000,    // запись без ответа могла дойти: 10 мин новых записей этой карточки клиента нет
  };
  // справочник статусов (контракт 2.1); в offscreen LC_ACT нет — своя копия только для кода по шапке
  const СТАТУСЫ = { 1: 'Ожидает', 4: 'В пути', 8: 'В работе', 9: 'В работе СД', 2: 'Модерация', 3: 'На уточнении', 20: 'Не оформлена', 48: 'Не создана',
    32: 'Отмена', 1001: 'Отмена КЦ', 1002: 'Отмена Филиала', 1003: 'Отмена Регионал', 64: 'Отказ', 128: 'Готов', 1020: 'Готов ОФ', 65: 'Склад' };
  const ЖИВЫЕ = [1, 4, 8, 9, 2, 3];
  const norm = (s) => String(s || '').toLowerCase().replace(/ё/g, 'е').replace(/\s+/g, ' ').trim();
  // шапка «Статус: Ожидает [Вопрос]» → код; длинные названия первыми («В работе СД» раньше «В работе»)
  const ПО_ДЛИНЕ = Object.entries(СТАТУСЫ).map(([k, v]) => [Number(k), norm(v)]).sort((a, b) => b[1].length - a[1].length);
  function кодСтатуса(t) {
    const n = norm(t).replace(/филиал(?!а)/, 'филиала');
    const x = ПО_ДЛИНЕ.find(([, v]) => n === v || n.startsWith(v + ' '));
    return x ? x[0] : null;
  }

  /* ── сеть: как в crm.js ── */
  async function getСрокСвой(url, init, мс = НАСТРОЙКИ.срокЧтенияМс) {
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
      throw e;
    } finally { clearTimeout(t); }
  }
  const getСрок = (...a) => вн('getСрок', getСрокСвой)(...a);
  async function fetchDocСвой(url) {
    const r = await getСрок(url, { credentials: 'include' });
    const doc = new DOMParser().parseFromString(await r.text(), 'text/html');
    doc.__finalUrl = r.url;
    if (doc.querySelector('input[type="password"], [name^="LoginForm["]')) throw new Error('Сессия в CRM истекла — откройте сайт лид-центра и войдите');
    return doc;
  }
  const fetchDoc = (url) => вн('fetchDoc', fetchDocСвой)(url);
  function serializeFormСвой(form) {
    const body = new URLSearchParams();
    for (const el of form.elements) {
      if (!el.name || el.disabled || (typeof el.matches === 'function' && el.matches(':disabled'))) continue;
      if (el.tagName === 'BUTTON' || /^(?:submit|reset|button|image|file)$/i.test(el.type || '')) continue;
      if (el.type === 'checkbox' || el.type === 'radio') { if (el.checked) body.append(el.name, el.value || '1'); }
      else if (el.tagName === 'SELECT' && el.multiple) { for (const o of el.selectedOptions) body.append(el.name, o.value); }
      else body.append(el.name, el.value ?? '');
    }
    return body;
  }
  const serializeForm = (f) => вн('serializeForm', serializeFormСвой)(f);
  function formErrorsСвой(doc) {
    const out = [];
    for (const fb of doc.querySelectorAll('.invalid-feedback, .help-block-error')) { const t = fb.textContent.trim(); if (t) out.push(t); }
    for (const a of doc.querySelectorAll('.alert-danger, .alert-error')) { const t = a.textContent.trim(); if (t) out.push(t.slice(0, 200)); }
    return out;
  }
  const formErrors = (d) => вн('formErrors', formErrorsСвой)(d);
  const обновитьКлиента = (...a) => вн('обновитьКлиента', К && К.обновитьКлиента)(...a);

  /* ── тексты итога (раздел 6 проекта) ── */
  const ТЕКСТ = {
    сессия: (dir, б = ИМЯ_БАЗЫ[dir] || '') => 'Сессия в CRM ' + (б ? б + ' ' : '') + 'истекла — откройте сайт лид-центра' + (б ? ' ' + б : '') + ', войдите и нажмите ещё раз. Ничего не сделано.',
    занято: (id) => 'По заявке № ' + id + ' уже выполняется действие (в этой или другой вкладке) — дождитесь итога.',
    устарело: (что) => 'Пока вы смотрели, карточка клиента изменилась: ' + что + '. Ничего не сделано — посмотрите и нажмите ещё раз.',
    статус: (имя, можно) => 'Заявка сейчас в статусе «' + (имя || '?') + '» — карточку клиента из расширения меняем только в ' + можно + '. Ничего не сделано.',
    отказ: (ош) => 'CRM не сохранила: ' + String(ош).replace(/[.\s]+$/, '') + '. В чат не писали.',
    непроверено: (что) => 'CRM ответила, но в карточке клиента по-прежнему «' + что + '» — проверьте карточку клиента в CRM. В чат не писали.',
    нетОтвета: (мс) => 'CRM не ответила за ' + (мс >= 60000 ? Math.round(мс / 60000) + ' мин' : Math.round(мс / 1000) + ' с')
      + ' — не знаю, прошло ли. Повторно не отправляю. Нажмите «Проверить» или откройте карточку клиента в CRM.',
    неожиданно: (кратко) => 'CRM ответила не так, как ожидалось (' + кратко + '). Ничего больше не делаю — сделайте это действие в CRM.',
    непрочитано: (что) => 'CRM ответила, но перечитать карточку клиента не удалось (' + что + ') — не знаю, сохранилось ли. Повторно не отправляю — проверьте карточку клиента в CRM. В чат не писали.',
    висит: (чч) => 'Прошлая запись этой карточки клиента (' + чч + ') осталась без ответа CRM — не знаю, дошла ли. Новую не отправляю: проверьте карточку клиента в CRM.',
  };
  const текстОшибки = (dir, e) => {
    const m = String((e && e.message) || e || '');
    return /сесси|LoginForm|войдите/i.test(m) ? ТЕКСТ.сессия(dir) : m.slice(0, 160);
  };

  /* ── чтение ── */
  const URL_ЗАЯВКИ = (base, id) => base + '/admin/domain/customer-request/update?id=' + encodeURIComponent(id);
  const URL_КЛИЕНТА = (base, custId) => base + '/admin/domain/customer/update?id=' + encodeURIComponent(custId);
  const полеФормы = (form, n) => { const e = form && form.elements[n]; return e && e.tagName ? e : null; };
  const выбранное = (sel) => { if (!sel) return null; const o = [...sel.options].find((x) => x.selected || x.hasAttribute('selected')); return o || null; };

  // клиент заявки — disabled select CustomerRequest[customer_id] или ссылка «Карточка клиента» (как клиентЗаявкиИз в crm.js)
  function клиентИз(doc) {
    const e = doc.querySelector('[name="CustomerRequest[customer_id]"]');
    let v = '';
    if (e && e.tagName === 'SELECT') { const o = выбранное(e); v = (o && o.value) || e.value || ''; }
    else if (e) v = e.value || e.getAttribute('value') || '';
    if (!/^\d+$/.test(String(v))) { const a = doc.querySelector('a[href*="/customer/update?id="]'); v = a ? ((a.getAttribute('href') || '').match(/[?&]id=(\d+)/) || [])[1] || '' : ''; }
    return /^\d+$/.test(String(v)) ? String(v) : '';
  }
  function статусИз(doc) {
    const шапка = [...doc.querySelectorAll('span')].find((e) => /^\s*Статус:\s*$/.test(e.textContent || ''));
    if (шапка && шапка.parentElement) return шапка.parentElement.textContent.replace(/\s+/g, ' ').replace(/^\s*Статус:\s*/, '').trim().slice(0, 40);
    const m = String((doc.body && doc.body.textContent) || '').match(/Статус:\s*([^\n\r]{1,40})/);
    return m ? m[1].trim() : '';
  }
  /* Карточка заявки — только то, что нужно для карточки клиента: статус, клиент, город, «Дальний выезд»,
     а в «Модерации»/«На уточнении» — адрес клиента в самой форме заявки (CRM показывает его там же) */
  async function читатьЗаявку(base, id) {
    const doc = await fetchDoc(URL_ЗАЯВКИ(base, id));
    const form = doc.querySelector('#customerRequestForm');
    if (!form && !doc.querySelector('[name="CustomerRequest[city_id]"]')) return null;
    const f = form || doc;
    const город = выбранное(f.querySelector('select[name="CustomerRequest[city_id]"]'));
    const дв = f.querySelector('select[name="CustomerRequest[is_far_ride]"]');
    const statusName = статусИз(doc);
    const адресВФорме = {};
    for (const k of ['street', 'building', 'office']) { const e = f.querySelector('[name="Customer[address_' + k + ']"]'); if (e) адресВФорме[k] = String(e.value || '').trim(); }
    return { doc, statusName, statusCode: кодСтатуса(statusName), customerId: клиентИз(doc), cityName: город && город.value ? город.textContent.replace(/\s+/g, ' ').trim() : '',
      farRide: дв ? { value: дв.value || '', disabled: !!дв.disabled } : null, адресВФорме: Object.keys(адресВФорме).length ? адресВФорме : null,
      comments: String((doc.querySelector('#customerrequest-comments') || {}).value || ''),
      service: String((doc.querySelector('#customerrequest-comments_service') || {}).value || '') };
  }

  const АДРЕС = { locality: 'Customer[address_locality]', street: 'Customer[address_street]', building: 'Customer[address_building]',
    office: 'Customer[address_office]', entrance: 'Customer[address_entrance]', floor: 'Customer[address_floor]', intercom: 'Customer[address_has_intercom]' };
  const ИМЯ = 'Customer[first_name]';
  const ТЕЛ_V = /^Customer\[contact_phones\]\[([^\]]+)\]\[v\]$/;
  // форма карточки клиента: #w0 (на странице их две) с полями клиента
  function формаКлиента(doc) {
    const все = [...doc.querySelectorAll('form')];
    const клиентская = (f) => !!(полеФормы(f, АДРЕС.street) || полеФормы(f, ИМЯ) || [...f.elements].some((e) => ТЕЛ_V.test(e.name || '')));
    return все.find((f) => f.id === 'w0' && клиентская(f)) || все.find(клиентская) || null;
  }
  const тел10 = (s) => { const d = String(s || '').replace(/\D/g, ''); return d.length === 10 ? d : d.length === 11 && /^[78]/.test(d) ? d.slice(1) : ''; };
  const видCRM = (d) => '+7 ' + d.slice(0, 3) + '-' + d.slice(3, 6) + '-' + d.slice(6);   // как пишет p12 (маскаТел)
  const маска = (d) => (d && d.length === 10 ? '+7 ' + d[0] + '••-•••-••' + d.slice(8) : '—');
  const строкаАдреса = (a) => [a.locality, a.street, a.building, a.office && 'кв ' + a.office, a.entrance && 'подъезд ' + a.entrance, a.floor && 'этаж ' + a.floor]
    .filter(Boolean).join(', ');
  function состояние(form) {
    const адрес = {};
    for (const [k, n] of Object.entries(АДРЕС)) { const e = полеФормы(form, n); адрес[k] = e ? String(e.value || '').trim() : null; }
    const телефоны = [];
    let пустая = null;                                                 // строка «добавить телефон» ([0]): null — её нет
    for (const e of form.elements) {
      const m = (e.name || '').match(ТЕЛ_V);
      if (!m) continue;
      const d = тел10(e.value);
      if (m[1] === '0' && !String(e.value || '').trim()) { пустая = true; continue; }
      if (m[1] === '0') пустая = false;
      телефоны.push({ key: m[1], d, raw: String(e.value || '').trim() });
    }
    const имя = полеФормы(form, ИМЯ);
    return { адрес, телефоны, пустая, имя: имя ? String(имя.value || '').replace(/\s+/g, ' ').trim() : null };
  }
  const хэш = (s) => { let h = 0x811c9dc5; for (const ch of String(s)) { h ^= ch.codePointAt(0); h = Math.imul(h, 0x01000193) >>> 0; } return h.toString(36); };
  const подпись = (с) => хэш(JSON.stringify([с.адрес, с.телефоны.map((t) => t.key + ':' + (t.d || t.raw)), с.имя]));
  // что изменилось в карточке клиента — словами, без значений телефонов
  function чтоИзменилось(a, b) {
    const out = [];
    if (JSON.stringify(a.адрес) !== JSON.stringify(b.адрес)) out.push(['адрес', строкаАдреса(a.адрес) || '—', строкаАдреса(b.адрес) || '—']);
    if (a.телефоны.map((t) => t.d).join() !== b.телефоны.map((t) => t.d).join()) out.push(['телефоны', a.телефоны.map((t) => маска(t.d)).join(', ') || '—', b.телефоны.map((t) => маска(t.d)).join(', ') || '—']);
    if (a.имя !== b.имя) out.push(['имя', a.имя || '—', b.имя || '—']);
    return out;
  }
  // другие живые заявки клиента — из таблицы его заявок на странице карточки (только № и статус)
  function другиеЖивые(doc, id) {
    const out = [];
    for (const tr of doc.querySelectorAll('tr')) {
      const a = tr.querySelector('a[href*="customer-request/update?id="]');
      if (!a) continue;
      const n = ((a.getAttribute('href') || '').match(/[?&]id=(\d+)/) || [])[1] || '';
      if (!n || n === String(id) || out.some((x) => x.id === n)) continue;
      const td = [...tr.querySelectorAll('td')].map((x) => (x.textContent || '').trim()).find((t) => кодСтатуса(t) !== null);
      if (td && ЖИВЫЕ.includes(кодСтатуса(td))) out.push({ id: n, statusName: td.slice(0, 30) });
    }
    return out.slice(0, 5);
  }
  // наружу: номера только маской, ключ строки — чтобы оператор выбрал, какой заменить
  const наружу = (с, sig) => ({ sig, line: строкаАдреса(с.адрес), address: { ...с.адрес }, name: с.имя,
    phones: с.телефоны.filter((t) => t.d).map((t, i) => ({ key: t.key, masked: маска(t.d), main: i === 0 })), emptyRow: с.пустая === true });

  /* ── правило имени и телефона (одно и для превью, и для записи) ── */
  function разборТелефона(с, p) {
    const d = тел10(p.phone);
    if (!d) return { error: 'номер — 10 цифр (+7 и ещё 10)' };
    const есть = с.телефоны.find((t) => t.d === d);
    const replace = p.replace && String(p.replace) !== '0' ? String(p.replace) : '';
    if (replace) {
      const старый = с.телефоны.find((t) => t.key === replace);
      if (!старый) return { error: 'в карточке клиента нет номера, который нужно заменить — обновите превью' };
      if (есть) return { d, already: true, mode: 'replace', note: 'номер ' + маска(d) + ' уже есть в карточке клиента' + (есть.key !== replace ? ' — лишний ' + маска(старый.d) + ' уберите в CRM сами' : '') };
      return { d, mode: 'replace', key: replace, old: старый.d };
    }
    if (есть) return { d, already: true, mode: 'add', note: 'номер ' + маска(d) + ' уже есть в карточке клиента' };
    if (с.пустая !== true) return { error: 'в карточке клиента нет пустой строки «Добавить телефон» — добавьте номер в CRM' };
    return { d, mode: 'add', key: '0' };
  }
  const имяЧисто = (s) => String(s || '').replace(/\s+/g, ' ').trim().slice(0, 100);

  /* ── замки: заявка и карточка клиента. Set на globalThis offscreen (один на всё расширение — значит, на все вкладки);
     ключ заявки «dir:id» — как у замка crmact (PA), чтобы act и custAct по одной заявке шли по очереди, если он возьмёт этот же Set ── */
  const ЗАМКИ = (typeof globalThis !== 'undefined' && (globalThis.LCZ_ЗАМКИ = globalThis.LCZ_ЗАМКИ || new Set())) || new Set();
  // карточка клиента → когда ушла запись без ответа: пока она может дойти, вторая запись затёрла бы её (строки телефонов)
  const ВИСИТ = new Map();
  const висит = (к) => { const t = ВИСИТ.get(к); if (t && Date.now() - t < НАСТРОЙКИ.памятьНеизвестныхМс) return t; ВИСИТ.delete(к); return 0; };
  const чч = (t) => { const d = new Date(t); return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); };
  // срок для чужого запроса без своего срока (saveCardComments): ответа нет — 'нет ответа', запрос не обрываем
  const сроком = (pr, мс) => { let t = 0; return Promise.race([Promise.resolve(pr), new Promise((res) => { t = setTimeout(() => res({ ok: false, timeout: true, error: 'нет ответа за ' + Math.round(мс / 1000) + ' с' }), мс); })]).finally(() => clearTimeout(t)); };

  /* СНИМОК ДЛЯ ПРЕВЬЮ: a = { dir, id, ввод: { addr?, phone?, replace?, name? } } → { ok, card, cust, dry } */
  async function снимок(a) {
    a = a || {};
    const base = БАЗЫ()[a.dir];
    if (!base || !/^\d+$/.test(String(a.id || ''))) return { ok: false, error: 'нет заявки' };
    try {
      const з = await читатьЗаявку(base, a.id);
      if (!з) return { ok: false, error: 'карточка заявки № ' + a.id + ' не открылась' };
      const card = { dir: a.dir, id: String(a.id), statusName: з.statusName, statusCode: з.statusCode, cityName: з.cityName, customerId: з.customerId, farRide: з.farRide };
      if (!з.customerId) return { ok: false, card, error: 'в карточке заявки № ' + a.id + ' не нашёлся клиент' };
      const url = URL_КЛИЕНТА(base, з.customerId);
      const doc = await fetchDoc(url);
      const form = формаКлиента(doc);
      if (!form) return { ok: false, card, error: 'карточка клиента не открылась', url };
      const с = состояние(form);
      const cust = { customerId: з.customerId, url, ...наружу(с, подпись(с)), otherLive: другиеЖивые(doc, a.id) };
      const в = a.ввод || {};
      const dry = {};
      if (в.addr && К && typeof К.customerAddress === 'function') {
        const d = await К.customerAddress({ dir: a.dir, id: a.id, addr: в.addr, dry: true });
        dry.addr = { ok: !!(d && d.ok), changed: (d && d.changed) || [], line: (d && d.line) || '', was: (d && d.was) || '', house: !!(d && d.house), error: (d && !d.ok && d.error) || '' };
      }
      if (в.phone) {
        const т = разборТелефона(с, в);
        dry.phone = { ok: !т.error, error: т.error || '', mode: т.mode || '', already: !!т.already, note: т.note || '', masked: т.d ? маска(т.d) : '', old: т.old ? маска(т.old) : '' };
      }
      if (в.name !== undefined) { const n = имяЧисто(в.name); dry.name = { ok: !!n, was: с.имя || '', name: n, already: !!n && n === с.имя, error: n ? '' : 'пустое имя' }; }
      return { ok: true, card, cust, dry };
    } catch (e) {
      return { ok: false, error: текстОшибки(a.dir, e) };
    }
  }

  /* ЗАПИСЬ карточки клиента — один POST всей формы (как «Сохранить»; кнопки без нажатия браузер не шлёт).
     Ответ сам по себе успехом не считаем: решает повторное чтение (и при ошибках формы, и при «странном» ответе).
     Нет ответа — «не знаю», без повтора; страница входа — сессия */
  async function отправить(form, base, url) {
    const body = serializeForm(form);
    for (const e of form.elements) if (e.name && (e.tagName === 'BUTTON' || e.type === 'submit')) body.delete(e.name);
    let r;
    try {
      r = await getСрок(new URL(form.getAttribute('action') || url, base).href,
        { method: 'POST', credentials: 'include', body }, НАСТРОЙКИ.срокЗаписиМс);   // как кнопки самой CRM (saveAndClose → form.submit()): обычной отправкой формы, без X-Requested-With — фоновым запросом CRM правку не сохраняла (09.10)
    } catch (_e) {
      // ответа нет (срок, обрыв сети): запрос мог дойти до CRM — «не знаю», а не «не сохранилась»
      return { unknown: true };
    }
    // обычная отправка: CRM ответила 302, fetch прошёл по нему сам — это «сохранила» (решает перечитанная карточка)
    const redirect = (r.headers && r.headers.get && r.headers.get('X-Redirect')) || (r.redirected ? r.url || '' : '');
    const text = await r.text();
    if (/default\/index|\/login/.test(redirect) || /LoginForm\[|type="password"/.test(text)) return { session: true };
    const errors = r.status === 302 || redirect ? [] : formErrors(new DOMParser().parseFromString(text, 'text/html'));
    return { sent: true, status: r.status, errors };
  }

  // инварианты после записи: чужие номера на месте, имя и адрес не тронуты (кроме своего поля)
  function проверкаЧужого(до, после, рецепт, т) {
    const не = [];
    const оставить = до.телефоны.filter((t) => t.d && !(рецепт === 'phone_add' && т && т.mode === 'replace' && t.key === т.key));
    for (const t of оставить) if (!после.телефоны.some((x) => x.d === t.d)) не.push('пропал номер ' + маска(t.d) + ' — верните его в карточке клиента');
    if (рецепт !== 'name' && до.имя !== после.имя) не.push('изменилось имя клиента («' + (до.имя || '—') + '» → «' + (после.имя || '—') + '»)');
    if (рецепт !== 'addr' && JSON.stringify(до.адрес) !== JSON.stringify(после.адрес)) не.push('изменился адрес клиента');
    return не;
  }

  /* ДЕЙСТВИЕ: a = { dir, id, recipe: 'addr'|'phone_add'|'name', params, expect: { custSig, custWas, statuses }, key }
     или «плоско», как шлёт бегунок PC для op не 'act': { dir, id, ...params } (recipe и expect — внутри params).
     → { ok, already?, stale?, unknown?, busy?, steps: [{name, ok, detail}], custAfter, changed, line, warnings, error }.
     after (снимок ЗАЯВКИ по контракту 2.1) не отдаём: сводка карточки клиента в снимок заявки не годится */
  async function сделать(a) {
    a = a || {};
    const p = a.params && typeof a.params === 'object' ? a.params : a;
    const exp = { ...((p !== a && p.expect) || {}), ...(a.expect || {}) };
    if (a.expectCustSig) exp.custSig = a.expectCustSig;
    const рецепт = a.recipe || a.action || p.recipe;
    const out = { ok: false, steps: [], warnings: [], changed: [], line: '', recipe: рецепт };
    const шаг = (name, ok, detail) => { out.steps.push({ name, ok, detail: String(detail || '').slice(0, 200) }); };
    const base = БАЗЫ()[a.dir];
    if (!base || !/^\d+$/.test(String(a.id || ''))) return { ...out, error: 'нет заявки' };
    if (!['addr', 'phone_add', 'name'].includes(рецепт)) return { ...out, error: 'неизвестное действие с карточкой клиента: ' + рецепт };
    const можно = (Array.isArray(exp.statuses) && exp.statuses.length ? exp.statuses : НАСТРОЙКИ.статусы).map(Number);
    const ключ = a.dir + ':' + a.id;
    if (ЗАМКИ.has(ключ)) return { ...out, busy: true, error: ТЕКСТ.занято(a.id) };
    ЗАМКИ.add(ключ);
    let ключК = '';
    try {
      // 1) заявка: статус разрешён, клиент есть
      const з = await читатьЗаявку(base, a.id);
      if (!з) return { ...out, error: 'карточка заявки № ' + a.id + ' не открылась' };
      if (!можно.includes(з.statusCode)) return { ...out, error: ТЕКСТ.статус(з.statusName, можно.map((k) => '«' + СТАТУСЫ[k] + '»').join(', ')) };
      if (!з.customerId) return { ...out, error: 'в карточке заявки № ' + a.id + ' не нашёлся клиент' };
      // карточка общая для всех заявок клиента: две правки одного клиента по разным заявкам — по очереди
      ключК = 'cust:' + a.dir + ':' + з.customerId;
      if (ЗАМКИ.has(ключК)) { ключК = ''; return { ...out, busy: true, error: ТЕКСТ.занято(a.id) }; }
      ЗАМКИ.add(ключК);
      // 2) карточка клиента — свежая, такая же, как в превью
      const url = URL_КЛИЕНТА(base, з.customerId);
      const doc0 = await fetchDoc(url);
      const form = формаКлиента(doc0);
      if (!form) return { ...out, error: 'карточка клиента не открылась', url };
      const до = состояние(form);
      if (exp.custSig && exp.custSig !== подпись(до)) {
        // было/стало — по тому, что видел оператор (exp.custWas из превью), иначе — что сейчас
        const w = exp.custWas || {}, сейчас = наружу(до, '');
        const что = w.line !== undefined && w.line !== сейчас.line ? 'адрес был «' + (w.line || '—') + '», стал «' + (сейчас.line || '—') + '»'
          : w.name !== undefined && w.name !== сейчас.name ? 'имя было «' + (w.name || '—') + '», стало «' + (сейчас.name || '—') + '»'
            : w.phones !== undefined && Number(w.phones) !== сейчас.phones.length ? 'номеров было ' + w.phones + ', стало ' + сейчас.phones.length
              : 'сейчас: адрес «' + (сейчас.line || '—') + '», номеров ' + сейчас.phones.length;
        return { ...out, stale: true, error: ТЕКСТ.устарело(что), custAfter: наружу(до, подпись(до)) };
      }
      let после = null, т = null;
      // прошлая запись этой карточки без ответа могла ещё дойти — новая её затёрла бы: не пишем (чтение и «уже так» — можно)
      const неВисит = () => { const t = висит(ключК); if (!t) return null; шаг('карточка клиента', false, 'прошлая запись без ответа'); return { ...out, busy: true, error: ТЕКСТ.висит(чч(t)), url }; };
      const безОтвета = (текст) => { ВИСИТ.set(ключК, Date.now()); шаг('карточка клиента', false, 'нет ответа'); return { ...out, unknown: true, error: текст, url }; };

      if (рецепт === 'addr') {
        const в = неВисит();
        if (в) return в;
        // адрес — проверенной правкой p12: план, только адресные поля, один POST, сверка повторным чтением
        const c = await обновитьКлиента(base, з.customerId, { addr: p.addr || {} });
        if (!c || !c.ok) {
          const ош = String((c && c.error) || 'ошибка');
          if (/не ответила за/i.test(ош)) return безОтвета(ТЕКСТ.нетОтвета(((ош.match(/за (\d+) с/) || [])[1] || 20) * 1000));
          if (/сесси/i.test(ош)) return { ...out, error: ТЕКСТ.сессия(a.dir) };
          шаг('карточка клиента', false, ош);
          return { ...out, error: /^CRM не сохранила/.test(ош) ? ош + '. В чат не писали.' : 'Адрес в карточке клиента не сменился: ' + ош + '. В чат не писали.', url };
        }
        out.warnings.push(...(c.warnings || []));
        out.line = c.line || '';
        if (!(c.changed || []).length) { шаг('карточка клиента', true, 'уже этот адрес'); out.already = true; }
        else { out.changed = c.changed.slice(); шаг('карточка клиента', true, c.changed.join(', ') + ' — ' + c.line); }
        if (!out.already) {
          // адрес p12 уже сверил; здесь — что чужое (номера, имя) не задето. Не прочиталось — адрес всё равно сохранён
          let f2 = null;
          try { f2 = формаКлиента(await fetchDoc(url)); } catch (_e) { f2 = null; }
          после = f2 ? состояние(f2) : null;
          if (!f2) out.warnings.push('после сохранения карточка клиента не перечиталась — проверьте в CRM номера и имя клиента');
        }
      } else {
        const поле = рецепт === 'name' ? полеФормы(form, ИМЯ) : null;
        if (рецепт === 'name') {
          const n = имяЧисто(p.name);
          if (!n) return { ...out, error: 'пустое имя — если клиент не назвался, «М» или «Ж» (регламент)' };
          if (!поле) return { ...out, error: 'в карточке клиента нет поля имени — поменяйте в CRM' };
          if (до.имя === n) { шаг('карточка клиента', true, 'уже это имя'); out.already = true; }
          else { поле.value = n; т = { name: n }; }
        } else {
          т = разборТелефона(до, p);
          if (т.error) return { ...out, error: т.error };
          // «вместо этого номера» — ключ строки из превью: без подписи превью не знаем, тот ли номер в строке сейчас
          if (т.mode === 'replace' && !т.already && !exp.custSig) return { ...out, error: 'замена номера — только по превью карточки клиента: обновите превью и нажмите ещё раз' };
          if (т.already) { шаг('карточка клиента', true, т.note); out.already = true; if (/лишний/.test(т.note)) out.warnings.push(т.note); }
          else {
            const e = полеФормы(form, 'Customer[contact_phones][' + т.key + '][v]');
            if (!e) return { ...out, error: 'в карточке клиента нет строки телефона — добавьте номер в CRM' };
            e.value = видCRM(т.d);
            const title = полеФормы(form, 'Customer[contact_phones][' + т.key + '][title]');
            if (title && т.mode === 'add') title.value = String(p.title || '').replace(/\s+/g, ' ').trim().slice(0, 30);
          }
        }
        if (!out.already) {
          const в = неВисит();
          if (в) return в;
          const r = await отправить(form, base, url);
          if (r.unknown) return безОтвета(ТЕКСТ.нетОтвета(НАСТРОЙКИ.срокЗаписиМс));
          if (r.session) return { ...out, error: ТЕКСТ.сессия(a.dir) };
          // запись ушла и CRM ответила — успех решает только повторное чтение; не прочиталось — «не знаю», не «ошибка»
          let f2 = null, неЧитается = '';
          try { f2 = формаКлиента(await fetchDoc(url)); if (!f2) неЧитается = 'карточка не открылась'; } catch (e) { неЧитается = String((e && e.message) || e).slice(0, 80); }
          if (!f2) {
            if (/сесси|войдите/i.test(неЧитается)) return { ...out, error: ТЕКСТ.сессия(a.dir) };
            шаг('карточка клиента', false, 'не перечиталась: ' + неЧитается);
            return { ...out, unknown: true, error: ТЕКСТ.непрочитано(неЧитается), url };
          }
          после = состояние(f2);
          // не сошлось: ошибки формы — «CRM не сохранила», HTTP-ошибка — «неожиданно», иначе — «по-прежнему …»
          const неСошлось = (что) => {
            шаг('карточка клиента', false, (r.errors || []).slice(0, 2).join('; ') || ('HTTP ' + r.status));
            const error = (r.errors || []).length ? ТЕКСТ.отказ(r.errors.slice(0, 2).map((x) => x.replace(/[.\s]+$/, '')).join('; ')) : r.status >= 400 ? ТЕКСТ.неожиданно('HTTP ' + r.status) : ТЕКСТ.непроверено(что);
            return { ...out, error, custAfter: наружу(после, подпись(после)), url };
          };
          // имя CRM может привести к своему виду (регистр, пробелы, «ё») — это то же имя
          if (рецепт === 'name' && norm(после.имя) !== norm(т.name)) return неСошлось('имя: ' + (после.имя || '—'));
          if (рецепт === 'phone_add') {
            if (!после.телефоны.some((x) => x.d === т.d)) return неСошлось('номера: ' + (после.телефоны.map((x) => маска(x.d)).join(', ') || '—'));
            if (т.mode === 'replace' && после.телефоны.some((x) => x.d === т.old)) out.warnings.push('старый номер ' + маска(т.old) + ' остался в карточке клиента — уберите его в CRM, если он неверный');
          }
          // сохранилось, хотя CRM что-то показала — сохранение есть, слова CRM — оператору
          if ((r.errors || []).length || r.status >= 400) out.warnings.push('CRM при сохранении показала: ' + ((r.errors || []).slice(0, 2).join('; ') || 'HTTP ' + r.status) + ' — карточка при этом сохранилась');
          out.changed = [рецепт === 'name' ? 'имя' : т.mode === 'replace' ? 'номер заменён' : 'доп. номер'];
          шаг('карточка клиента', true, рецепт === 'name' ? 'имя: ' + т.name : out.changed[0] + ' ' + маска(т.d));
        }
      }
      // 3) чужое не задето: номера, которых мы не меняли, на месте; имя/адрес — как были
      if (после) {
        const не = проверкаЧужого(до, после, рецепт, т);
        if (не.length) { шаг('проверка карточки', false, не.join('; ')); return { ...out, error: 'CRM сохранила, но ' + не.join('; ') + '. В чат не писали.', custAfter: наружу(после, подпись(после)), url }; }
        шаг('проверка карточки', true, 'повторное чтение — сошлось');
      }
      const итог = после || до;
      out.custAfter = наружу(итог, подпись(итог));
      out.line = out.line || строкаАдреса(итог.адрес);
      // 4) строка в комментарий / служебный заявки — только после проверенной карточки и только один раз
      const строки = [];
      if (!out.already && p.comment) строки.push(['comments', String(p.comment).replace('{адрес}', out.line).trim()]);
      if (p.service) строки.push(['comments_service', String(p.service).trim()]);
      let з2 = null, дописано = false;
      for (const [поле, строка] of строки) {
        if (!строка) continue;
        const было = поле === 'comments' ? з.comments : з.service;
        if (norm(было).includes(norm(строка))) { шаг(поле === 'comments' ? 'комментарий заявки' : 'служебный', true, 'уже есть'); continue; }
        let r = null;
        // saveCardComments (crm.js) пишет без срока: зависла — не держим замки заявки и клиента вечно, повтора нет
        try { r = await сроком(К.saveCardComments(base, a.id, поле === 'comments' ? { addComment: строка } : { addService: строка }), НАСТРОЙКИ.срокКомментарияМс); } catch (e) { r = { ok: false, error: String((e && e.message) || e) }; }
        з2 = r && r.timeout ? null : await читатьЗаявку(base, a.id).catch(() => null);
        const стоит = з2 && norm(поле === 'comments' ? з2.comments : з2.service).includes(norm(строка));
        шаг(поле === 'comments' ? 'комментарий заявки' : 'служебный', !!стоит, стоит ? строка : (r && r.timeout ? 'нет ответа — не знаю, дописалось ли' : 'не дописалось') + (r && r.error && !r.timeout ? ': ' + r.error : ''));
        if (!стоит) out.warnings.push((поле === 'comments' ? 'в комментарий заявки' : 'в служебный') + (r && r.timeout ? ' CRM не ответила — проверьте, есть ли там' : ' не дописалось') + ' «' + строка + '» — если нет, допишите в CRM');
        else { дописано = true; if (поле === 'comments_service') out.changed.push('служебный'); }
      }
      // «уже» — только если CRM не трогали совсем (карточка уже такая и строк в заявку не дописывали)
      if (дописано) out.already = false;
      // 5) «Модерация»/«На уточнении»: адрес есть и в форме заявки — старый там вернёт его при «Сохранить» заявки
      if (рецепт === 'addr' && !out.already && з.адресВФорме && [2, 3].includes(з.statusCode)) {
        const з3 = з2 || await читатьЗаявку(base, a.id).catch(() => null);
        const ф = з3 && з3.адресВФорме;
        const нов = итог.адрес;
        if (!ф || norm(ф.street) !== norm(нов.street) || norm(ф.building) !== norm(нов.building)) {
          out.warnings.push('в форме заявки (' + (СТАТУСЫ[з.statusCode] || '') + ') показан прежний адрес — перед «Сохранить» заявки в CRM обновите страницу (F5), иначе вернётся старый');
        }
      }
      return { ...out, ok: true, url, statusName: з.statusName, statusCode: з.statusCode };
    } catch (e) {
      return { ...out, error: текстОшибки(a.dir, e) };
    } finally {
      ЗАМКИ.delete(ключ);
      if (ключК) ЗАМКИ.delete(ключК);
    }
  }

  return { снимок, сделать, кодСтатуса, маска, тел10, НАСТРОЙКИ, _для_тестов: { состояние, формаКлиента, подпись, разборТелефона, другиеЖивые, ЗАМКИ, ВИСИТ } };
})();

/* offscreen: свои op рядом с op crm.js (чужие op пропускаем — их обрабатывает offscreen.js) */
if (typeof chrome !== 'undefined' && chrome.runtime && chrome.runtime.onMessage) {
  chrome.runtime.onMessage.addListener((msg, _sender, respond) => {
    if (!msg || typeof msg !== 'object' || Array.isArray(msg) || msg.target !== 'lcz-offscreen') return;
    const ops = { custSnap: () => CRM_CUST.снимок(msg.args || {}), custAct: () => CRM_CUST.сделать(msg.args || {}) };
    if (typeof msg.op !== 'string' || !Object.prototype.hasOwnProperty.call(ops, msg.op)) return;
    const f = ops[msg.op];
    f().then(respond).catch((e) => respond({ ok: false, error: String((e && e.message) || e) }));
    return true;
  });
}
if (typeof module !== 'undefined' && module.exports) module.exports = CRM_CUST;
