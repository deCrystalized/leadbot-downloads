const $ = (id) => document.getElementById(id);

/* ---------- 2.0: личный токен мозга ---------- */
const РЕЖИМЫ = {
  normal: 'обычный',
  economy: 'экономный — расход близок к лимиту месяца: только бесплатный GigaChat и YandexGPT Lite, «Готовые» без ИИ',
  rules: 'ИИ выключен до 1-го числа — лимит месяца исчерпан, разбор по правилам',
};
const адресЕсть = () => typeof CONFIG !== 'undefined' && /^https:\/\/\S+$/.test(String(CONFIG.brainUrl || '').trim());
const руб = (x) => (Math.round((Number(x) || 0) * 100) / 100).toLocaleString('ru-RU');
// к мозгу ходит только фон (одна функция мозг()); настройки спрашивают его статус через фон
const спросить = (msg) => new Promise((res) => {
  try { chrome.runtime.sendMessage(msg, (r) => res(r || { ok: false, error: (chrome.runtime.lastError && chrome.runtime.lastError.message) || 'фон расширения не ответил' })); }
  catch (e) { res({ ok: false, error: String((e && e.message) || e) }); }
});
const естьТокен = async () => !!(await chrome.storage.local.get('brainToken')).brainToken;
// дата выпуска токена: мозг отдаёт миллисекунды (или строку даты) — показываем «08.10.2026»
function дата(x) {
  const d = new Date(typeof x === 'number' || /^\d+$/.test(String(x)) ? Number(x) : String(x));
  return isNaN(d.getTime()) ? '' : d.toLocaleDateString('ru-RU');
}
const число = (x) => (Number(x) || 0).toLocaleString('ru-RU');
// модели мозга: {chains: {операция: [модель, …]}, packages: {модель: {left, total, free}}} — строками, без «[object Object]»
function строкиМоделей(m) {
  if (Array.isArray(m)) return ['Модели: ' + m.map(String).join(', ')];
  const out = [];
  if (m.chains && typeof m.chains === 'object') {
    const ц = Object.entries(m.chains).map(([op, ch]) => op + ': ' + (Array.isArray(ch) ? ch.map(String).join(' → ') : String(ch)));
    if (ц.length) out.push('Цепочки ИИ — ' + ц.join('; '));
  }
  if (m.packages && typeof m.packages === 'object') {
    const п = Object.entries(m.packages).map(([мод, x]) => {
      if (!x || typeof x !== 'object') return мод + ': ' + String(x);
      if (!Number(x.total)) return мод + ': пакета нет';
      return мод + ': осталось ' + число(x.left) + ' из ' + число(x.total) + ' токенов' + (x.free === false ? ' (пакет на исходе — модель пропускается)' : '');
    });
    if (п.length) out.push('Пакеты GigaChat — ' + п.join('; '));
  }
  return out;
}
function статус(text, bad) { $('st').textContent = text; $('st').className = bad ? 'bad' : ''; }
// ответ мозга — только текстом (textContent), без разметки
function показать(r, есть) {
  const box = $('state');
  box.replaceChildren();
  box.className = 'box';
  const строка = (t) => { const d = document.createElement('div'); d.textContent = t; box.appendChild(d); };
  if (!адресЕсть()) { box.className = 'box bad'; строка('В этой сборке не задан адрес мозга (config.js) — нужна сборка от ведущего.'); return; }
  if (!есть) { box.className = 'box warn'; строка('Токена нет — расширение ничего не делает: ни разбора, ни CRM, ни Telegram.'); return; }
  if (!r) { строка('Токен сохранён.'); return; }
  if (r.code === 'token') { box.className = 'box bad'; строка('Мозг не принимает сохранённый токен (отозван или неверный) — вставьте новый.'); return; }
  if (!r.ok) { box.className = 'box warn'; строка('Мозг сейчас не ответил: ' + String(r.error || '').slice(0, 160)); return; }
  if (r.token) строка('Токен: ' + (r.token.label || 'без метки') + (дата(r.token.created) ? ', выпущен ' + дата(r.token.created) : ''));
  строка('Режим ИИ: ' + (РЕЖИМЫ[r.mode] || r.mode || '—'));
  if (r.budget) строка('Расход за ' + (r.budget.month || 'месяц') + ': ' + руб(r.budget.spent) + ' из ' + руб(r.budget.limit) + ' ₽');
  // модели и пакеты — для ведущего: свёрнуто в «Подробно»
  const модели = r.models && typeof r.models === 'object' ? строкиМоделей(r.models) : [];
  if (модели.length) {
    const det = document.createElement('details'), sum = document.createElement('summary');
    sum.textContent = 'Подробно';
    det.appendChild(sum);
    модели.forEach((t) => { const d = document.createElement('div'); d.textContent = t; det.appendChild(d); });
    box.appendChild(det);
  }
  if (r.mode === 'rules') box.className = 'box bad';
  else if (r.mode === 'economy') box.className = 'box warn';
}
/* ---------- «Состояние»: мозг, компьютер с Telegram, вход в CRM — одним взглядом и что сделать ---------- */
const САЙТЫ = { kp: ['КП', 'https://kp-lead-centre.ru/'], bt: ['БТ', 'https://bt-lead-centre.ru/'], mnc: ['МНЧ', 'https://mnc-lead-centre.ru/'] };
const ЗАПУСТИТЬ = '«Запустить Telegram для лид-центра.bat»';
function когда(sec) {
  const d = new Date(Number(sec) * 1000);
  if (!Number(sec) || isNaN(d.getTime())) return '';
  const чч = d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
  return d.toDateString() === new Date().toDateString() ? 'сегодня в ' + чч : d.toLocaleDateString('ru-RU') + ' в ' + чч;
}
// ответ tg status (мозг → сервер команды): {agent, seen, name, state: ok|tg_down|offline, why}; старый сервер — без state
function строкаTelegram(t) {
  if (!t || t.ok === false) return { ok: false, text: 'Компьютер с Telegram: не удалось узнать (' + String((t && t.error) || 'нет ответа').slice(0, 120) + ')' };
  const state = t.state || (t.agent ? 'ok' : 'offline');
  const пк = t.name ? ' «' + String(t.name).slice(0, 40) + '»' : '', был = когда(t.seen);
  if (state === 'ok') return { ok: true, text: 'Компьютер с Telegram' + пк + ': на связи' + (был ? ', отмечался ' + был : '') };
  if (state === 'tg_down') {
    return { ok: false, text: 'Компьютер с Telegram' + пк + ': программа запущена, но Telegram не подключается' + (был ? ' (отмечался ' + был + ')' : ''),
      hint: t.why === 'auth' ? 'Вход в Telegram больше не действует: на том компьютере «Забыть вход в Telegram.bat», затем ' + ЗАПУСТИТЬ + ' и войдите.'
        : 'На том компьютере запустите tg-ws-proxy или VPN — программа подключится сама. Проверка: «Проверить связь с Telegram.bat».' };
  }
  return { ok: false, text: 'Компьютер с Telegram' + пк + ': не на связи' + (был ? ' (последний раз ' + был + ')' : ''),
    hint: 'На том компьютере запустите ' + ЗАПУСТИТЬ + '.' };
}
function показатьСостояние(rows) {
  const box = $('health');
  box.replaceChildren();
  box.className = rows.every((x) => x.ok !== false) ? 'box' : 'box warn';
  for (const x of rows) {
    const d = document.createElement('div'), mk = document.createElement('span');
    mk.className = 'mk ' + (x.ok === true ? 'ok' : x.ok === false ? 'no' : 'wait');
    mk.textContent = x.ok === true ? '✓' : x.ok === false ? '✗' : '…';
    d.append(mk, document.createTextNode(x.text));
    if (x.link) {
      const a = document.createElement('a');
      a.href = x.link; a.target = '_blank'; a.rel = 'noopener'; a.textContent = 'открыть сайт';
      d.append(document.createTextNode(' — '), a);
    }
    box.appendChild(d);
    if (x.hint) { const h = document.createElement('div'); h.className = 'hint'; h.textContent = x.hint; box.appendChild(h); }
  }
}
// r — ответ мозга на status (уже получен). Без токена или адреса мозга остальное не спрашиваем: фон без токена ничего не делает
let проверка = 0;
async function состояние(r, есть) {
  const моя = ++проверка;
  if (!адресЕсть()) { показатьСостояние([{ ok: false, text: 'Мозг: в этой сборке не задан адрес (config.js) — нужна сборка от ведущего' }]); return; }
  if (!есть) { показатьСостояние([{ ok: false, text: 'Мозг: токена нет — вставьте токен ниже' }]); return; }
  const мозг = !r ? { ok: null, text: 'Мозг: проверяю…' } : r.code === 'token' ? { ok: false, text: 'Мозг: токен не принят — вставьте новый ниже' }
    : r.ok ? { ok: true, text: 'Мозг: на связи' } : { ok: false, text: 'Мозг: не ответил (' + String(r.error || '').slice(0, 120) + ')' };
  if (!r || !r.ok) { показатьСостояние([мозг]); return; }
  показатьСостояние([мозг, { ok: null, text: 'Компьютер с Telegram: проверяю…' }, { ok: null, text: 'CRM КП, БТ, МНЧ: проверяю вход…' }]);
  const [tg, crm] = await Promise.all([спросить({ kind: 'lcz-tg', args: { action: 'status' } }), спросить({ kind: 'lcz-crm', op: 'session', args: {} })]);
  if (моя !== проверка) return;                                   // уже идёт новая проверка
  const строки = [мозг, строкаTelegram(tg)];
  for (const [dir, [имя, сайт]] of Object.entries(САЙТЫ)) {
    const b = crm && crm.ok !== false && crm.bases ? crm.bases[dir] : null;
    if (!b) строки.push({ ok: null, text: 'CRM ' + имя + ': не проверено (' + String((crm && crm.error) || 'нет ответа').slice(0, 80) + ')', link: сайт });
    else if (b.in === true) строки.push({ ok: true, text: 'CRM ' + имя + ': вход есть' });
    else if (b.in === false) строки.push({ ok: false, text: 'CRM ' + имя + ': войдите на сайт лид-центра ' + имя, link: сайт });
    else строки.push({ ok: null, text: 'CRM ' + имя + ': не проверено (' + String(b.error || 'нет ответа').slice(0, 80) + ')', link: сайт });
  }
  показатьСостояние(строки);
}

function подсказкаПоля(есть) { $('tok').placeholder = есть ? 'токен сохранён — вставьте новый, чтобы заменить' : 'вставьте токен'; }

(async () => {
  const есть = await естьТокен();
  подсказкаПоля(есть);
  показать(null, есть);
  состояние(null, есть);
  if (есть && адресЕсть()) {
    const r = await спросить({ kind: 'lcz-brain', op: 'status' });
    показать(r, true);
    await состояние(r, true);
  }
})();

$('check').onclick = async () => {
  const t = $('tok').value.trim(), b = $('check');
  b.disabled = true;
  статус('Проверяю…');
  try {
    if (!t) {
      if (!(await естьТокен())) { статус('Вставьте токен', true); return; }
      const r = await спросить({ kind: 'lcz-brain', op: 'status' });
      показать(r, true);
      статус('');
      await состояние(r, true);
      return;
    }
    // токен мозга — 32 байта base64url (43 знака); пробел или кусок — частая ошибка копирования
    if (!/^[A-Za-z0-9_-]{20,200}$/.test(t)) { статус('Это не похоже на токен: скопируйте его целиком, без пробелов', true); return; }
    const r = await спросить({ kind: 'lcz-brain', op: 'status', token: t });
    if (r.code === 'token') { статус('Мозг не принял токен — скопируйте его целиком или выпустите новый', true); return; }
    if (r.code === 'config') { показать(r, true); статус('', false); return; }
    // мозг не ответил (сеть) — токен всё равно сохраняем: неверный покажет себя первым же запросом («Нужен токен»)
    await chrome.storage.local.set({ brainToken: t });
    await chrome.storage.local.remove('brainTokenBad');
    $('tok').value = '';
    подсказкаПоля(true);
    показать(r, true);
    // открытые вкладки LeadChat узнают о новом токене сами (storage.onChanged) — обновлять страницу не нужно
    статус(r.ok ? 'Токен принят и сохранён' : 'Токен сохранён, но мозг сейчас не ответил — проверьте позже', !r.ok);
    await состояние(r, true);
  } finally { b.disabled = false; }
};
$('logout').onclick = async () => {
  if (!confirm('Стереть токен с этого компьютера? Расширение перестанет работать, пока не вставите токен снова.')) return;
  await chrome.storage.local.remove(['brainToken', 'brainTokenBad', 'brainState']);
  подсказкаПоля(false);
  показать(null, false);
  состояние(null, false);
  статус('Токен стёрт', false);
};

/* ---------- созданные заявки ---------- */
(async () => {
  const c = (await chrome.storage.local.get('created')).created || {};
  $('cnt').textContent = 'Диалогов с созданной заявкой: ' + Object.keys(c).length;
})();
$('clr').onclick = async () => {
  if (!confirm('Забыть, по каким диалогам заявки уже созданы? Сами заявки в CRM не тронутся.')) return;
  await chrome.storage.local.set({ created: {} });
  $('cnt').textContent = 'Диалогов с созданной заявкой: 0';
};

/* ---------- источники и ссылки для отзыва ---------- */
(async () => {
  const st = await chrome.storage.local.get(['sourcesText', 'sourcesSavedAt']);
  const t = st.sourcesText || '';
  // 13.10: список из настроек старше встроенного — действует встроенный (иначе старые ссылки перебивали бы новые)
  const старый = !!t && !LC_LINKS.свежийСписок(st.sourcesSavedAt);
  $('sources').value = t;
  const i = LC_LINKS.info();
  $('srcInfo').textContent = старый ? 'Ваш список из настроек старее встроенного (от ' + LC_LINKS.LIST_DATE.split('-').reverse().join('.') + ') — сейчас действует встроенный: '
      + i.count + ' источников. Чтобы снова действовал ваш, нажмите «Сохранить».'
    : t ? 'Сейчас действует список из настроек.' : 'Сейчас действует встроенный список: ' + i.count + ' источников, партнёры со своей ссылкой: ' + (i.partners.join(', ') || 'нет') + '.';
})();
$('saveSrc').onclick = async () => {
  const t = $('sources').value.trim();
  if (!t) {
    await chrome.storage.local.set({ sourcesText: '' });
    $('srcSt').textContent = 'Будет использоваться встроенный список';
    return;
  }
  const d = LC_LINKS.parse(t);
  if (!d.entries.length) { $('srcSt').style.color = 'var(--danger)'; $('srcSt').textContent = 'Не удалось разобрать список — проверьте формат'; return; }
  const by = { kp: 0, bt: 0, mnc: 0 };
  d.entries.forEach((e) => e.bases.forEach((b) => { by[b]++; }));
  await chrome.storage.local.set({ sourcesText: t, sourcesSavedAt: new Date().toISOString().slice(0, 10) });
  $('srcSt').style.color = 'var(--accent)';
  $('srcSt').textContent = 'Сохранено: КП ' + by.kp + ', БТ ' + by.bt + ', МНЧ ' + by.mnc + (Object.keys(d.partners).length ? ', партнёры: ' + Object.keys(d.partners).join(', ') : '') + '. Обновите страницу LeadChat.';
};
