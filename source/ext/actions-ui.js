/* LeadChat → Заявка 1.20 «Все действия с заявкой» — ЭКРАН ДЕЙСТВИЙ.
   Сетка «Действия по заявке» → карточка действия с превью (превью и есть подтверждение) → одна кнопка → бегунок.
   Бегунок у всех действий один: замок заявки → журнал («никогда дважды») → защита от перекрытия чата города → вкладка CRM →
   CRM (шаг за шагом; каждый проверяет сама CRM-часть повторным чтением карточки) → Telegram (только если CRM проверена) → LeadChat.
   Без клика оператора ничего не пишет; запись в CRM сама не повторяется: ответа нет — «не знаю, прошло ли» и кнопка «Проверить».
   Как создание в p11: задание идёт само — оператор может уйти в другой диалог, ход и итог придут уведомлением.
   Каталог, правила, тексты и пороги — LC_ACT (actions.js); CRM — операции фона 'snap' / 'act' (crmact.js в offscreen),
   карточка клиента — 'custAct' (PE). Поля карточки и дочитка для превью — из каталога (КАТАЛОГ[key].поля / .подготовить), иначе свои.
   Прежние карточки «по заявке», «Вернуть в «Ожидает»» и «не по закрепу» идут через этот же бегунок (поПлану, вернутьВОжидает, неПоЗакрепу).
   Подсказки (watch-act.js) — через исполнить / карточка / превью / подписаться. Личных данных не храним: журнал и заметки — с маской телефона. */
const LC_ACT_UI = (() => {
  /* ---------- чистые помощники (проверяются в node) ---------- */
  // телефон в журнале и заметках — замаскирован: «+7 9••-•••-••12» (номер заявки из 6–8 цифр сюда не попадает)
  const ТЕЛЕФОН = /(?<!\d)(?:\+7|8|7)?[\s(-]*9\d{2}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)/g;
  // городской номер тоже: «+7 (3452) 12-34-56», «X XXX XXX-XX-XX» и голые 10 цифр (phone10 из CRM). Дата с временем («08-10-2026 12:00») —
  // без «+7/8» впереди и не 10 цифр подряд — не трогаем
  const ГОРОДСКОЙ = /(?<![\d+])(?:(?:\+7|8)[\s(-]*\d{3,5}[\s)-]*\d{1,3}(?:[\s-]*\d{1,3}){1,3}|\d{10})(?!\d)/g;
  const маска = (s) => String(s == null ? '' : s).replace(ТЕЛЕФОН, (m) => m.match(/^\s*/)[0] + '+7 9••-•••-••' + m.replace(/\D/g, '').slice(-2))
    .replace(ГОРОДСКОЙ, (m) => { const d = m.replace(/\D/g, ''); return d.length === 10 || (d.length === 11 && /^[78]/.test(d)) ? '+7 •••-•••-••' + d.slice(-2) : m; });
  const хэш = (s) => {
    let a = 5381, b = 52711;
    const t = String(s);
    for (let i = 0; i < t.length; i++) { const c = t.charCodeAt(i); a = Math.imul(a, 33) ^ c; b = Math.imul(b, 31) ^ c; }
    return (a >>> 0).toString(36) + (b >>> 0).toString(36);
  };
  // отпечаток сообщения в чат для журнала: сам текст (в нём слова клиента) не храним; маска — как раньше (номер в чате тот же)
  const отпечатокЧата = (t) => хэш(маска(String(t == null ? '' : t)).replace(/\s+/g, ' ').trim().slice(0, 300));
  // ввод в ключ журнала — с упорядоченными ключами: тот же ввод в другом порядке — тот же ключ
  const канон = (x) => (x === null || typeof x !== 'object' ? JSON.stringify(x === undefined ? null : x)
    : Array.isArray(x) ? '[' + x.map(канон).join(',') + ']'
      : '{' + Object.keys(x).filter((k) => x[k] !== undefined).sort().map((k) => JSON.stringify(k) + ':' + канон(x[k])).join(',') + '}');
  const чч = (t) => new Date(t).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
  const сроком = (p, ms, что) => { let t = 0; return Promise.race([Promise.resolve(p), new Promise((res) => { t = setTimeout(() => res({ ok: false, timeout: true, unknown: true, error: что || 'нет ответа' }), ms); })]).finally(() => clearTimeout(t)); };
  // сеть оборвалась посреди записи — запись могла пройти: это «не знаю», а не «CRM отказала» (как безОтветаCRM в p11)
  const обрыв = (e) => /message port closed|context invalidated|Failed to fetch|NetworkError|Load failed|нет ответа от расширения/i.test(String(e || ''));
  // дата CRM («06-10-2026», «06.10.2026», «2026-10-06») → «2026-10-06»: цель плана и карточка пишут дату по-разному
  const isoД = (d) => { const m = String(d || '').match(/(\d{4})-(\d{2})-(\d{2})|(\d{1,2})[.-](\d{1,2})[.-](\d{4})/); return !m ? '' : m[1] ? m[1] + '-' + m[2] + '-' + m[3] : m[6] + '-' + m[5].padStart(2, '0') + '-' + m[4].padStart(2, '0'); };
  // цели, которых в снимке карточки не видно (отзыв, претензия, комментарий, карточка клиента) — решает CRM-ядро или оператор
  const НЕ_ВИДНО = new Set(['success', 'claim', 'findNew', 'statusChanged', 'comment', 'comments', 'service', 'partner', 'address', 'phone', 'name', 'custSig', 'custWas', 'statuses']);
  /* сверка карточки с целью действия (expect плана): true — сделано, false — нет, null — по снимку не понять.
     {statusCode: 1001 | [20, 48]}, {flags: {urgent: true}}, {held: 'mine' | false}, {visitDate}, {changesCountPlus: 1} — «+N» от карточки до действия */
  function совпадает(card, цель, было) {
    if (!цель || typeof цель !== 'object' || !Object.keys(цель).length) return null;
    if (!card || typeof card !== 'object') return false;
    let неясно = false;
    for (const [k, v] of Object.entries(цель)) {
      if (v === undefined) continue;
      if (/Plus$/.test(k)) {
        const б = k.slice(0, -4);
        if (!было || было[б] == null) { неясно = true; continue; }
        if (!(Number(card[б]) >= Number(было[б]) + Number(v))) return false;
        continue;
      }
      if (НЕ_ВИДНО.has(k)) { неясно = true; continue; }
      if (k === 'held' && typeof v !== 'object') {
        const x = card.held || {};
        if (v === 'mine' ? !x.mine : v ? !x.yes : !!x.yes) return false;
        continue;
      }
      if (k === 'statusCode' && Array.isArray(v)) { if (!v.map(Number).includes(Number(card.statusCode))) return false; continue; }
      if (k === 'visitDate') { if (isoД(card.visitDate) !== isoД(v)) return false; continue; }
      if (v && typeof v === 'object' && !Array.isArray(v)) {
        const r = совпадает(card[k], v, было && было[k]);
        if (r === false) return false;
        if (r === null) неясно = true;
        continue;
      }
      if (String(card[k] == null ? '' : card[k]) !== String(v == null ? '' : v)) return false;
    }
    return неясно ? null : true;
  }
  /* поле карточки действия: описания из каталога (PE: checkbox, phone, default, when-объект, «addr.street») — к одному виду */
  const взять = (v, путь) => String(путь).split('.').reduce((o, k) => (o == null ? undefined : o[k]), v);
  function положить(v, путь, val) {
    const ks = String(путь).split('.');
    let o = v;
    for (const k of ks.slice(0, -1)) { if (!o[k] || typeof o[k] !== 'object') o[k] = {}; o = o[k]; }
    o[ks[ks.length - 1]] = val;
  }
  function норм(f) {
    const x = { ...(f || {}) };
    if (x.type === 'checkbox') x.type = 'check';
    if (x.type === 'phone') { x.type = 'text'; x.tel = true; }
    if (x.value === undefined && x.default !== undefined) x.value = x.default;
    if (x.when && typeof x.when === 'object') { const w = x.when; x.when = (v) => Object.entries(w).every(([k, val]) => String(взять(v, k) == null ? '' : взять(v, k)) === String(val)); }
    if (Array.isArray(x.options)) x.options = x.options.map((o) => (Array.isArray(o) ? o : o && typeof o === 'object' ? [o.value, o.text != null ? o.text : o.title != null ? o.title : o.value] : [o, o]));
    return x;
  }
  const ФЛАГИ = [['urgent', 'Срочная'], ['callCheck', 'Прозвон'], ['callBeforeVisit', 'Перед выездом'], ['zakrep', 'Закреп'], ['fback', 'Отзыв']];
  // дата CRM («06-10-2026», «2026-10-06», «06.10.2026») → «06.10»
  const дм = (d) => { const m = String(d || '').match(/(\d{4})-(\d{2})-(\d{2})|(\d{1,2})[.-](\d{1,2})[.-](\d{4})/); return !m ? '' : m[1] ? m[3] + '.' + m[2] : m[4].padStart(2, '0') + '.' + m[5].padStart(2, '0'); };
  const состояние = (c) => (!c ? '' : [c.statusName || '', [дм(c.visitDate), c.visitTime || ''].filter(Boolean).join(' '), c.held && c.held.yes ? 'взята в работу' : '',
    ФЛАГИ.filter(([k]) => c.flags && c.flags[k]).map(([, t]) => t).join(', ')].filter(Boolean).join(' · '));
  // что изменилось в карточке, пока оператор смотрел на превью (для «Пока вы смотрели…»)
  function разница(a, b) {
    const x = состояние(a) || '—', y = состояние(b) || '—';
    return x !== y ? { было: x, стало: y } : { было: x, стало: y + ' (в карточке изменились кнопки или «Переносы»)' };
  }
  /* Тексты ошибок бегунка — точные, из проекта 1.20 (раздел 6). Есть таблица каталога (LC_ACT.НАСТРОЙКИ.ошибки) — берём оттуда:
     владелец правит тексты в одной таблице actions.js; здесь — те же тексты на случай, если каталога нет */
  function изКаталога(k, v) {
    try {
      if (typeof LC_ACT !== 'undefined' && LC_ACT && typeof LC_ACT.ошибка === 'function' && LC_ACT.НАСТРОЙКИ && LC_ACT.НАСТРОЙКИ.ошибки && LC_ACT.НАСТРОЙКИ.ошибки[k]) return String(LC_ACT.ошибка(k, v || {}) || '');
    } catch (_e) { /* свой текст */ }
    return '';
  }
  const ОШИБКИ = {
    сессия: (база) => изКаталога('сессия', { база }) || 'Сессия в CRM ' + (база ? база + ' ' : '') + 'истекла — откройте сайт лид-центра' + (база ? ' ' + база : '') + ', войдите и нажмите ещё раз. Ничего не сделано.',
    устарело: (было, стало) => изКаталога('устарело', { было, стало }) || 'Пока вы смотрели, заявка изменилась: было «' + было + '», стало «' + стало + '». Ничего не сделано — посмотрите и нажмите ещё раз.',
    нетКнопки: (id, кнопка, статус) => изКаталога('нетКнопки', { id, кнопка, статус }) || 'В CRM у заявки № ' + id + ' нет кнопки «' + кнопка + '» (статус «' + статус + '») — сейчас это действие недоступно.',
    отказ: (ошибки) => изКаталога('отказ', { ошибки }) || 'CRM не сохранила: ' + ошибки + '. В чат не писали.',
    непроверено: (статус) => изКаталога('непроверено', { статус }) || 'CRM ответила, но в карточке по-прежнему «' + статус + '» — проверьте заявку в CRM. В чат не писали.',
    get нетОтвета() { return изКаталога('нетОтвета') || 'CRM не ответила за 2 минуты — не знаю, прошло ли. Повторно не отправляю.'; },
    занято: (id) => изКаталога('занято', { id }) || 'По заявке № ' + id + ' уже выполняется действие (в этой или другой вкладке) — дождитесь итога.',
    ужеБыло: (hm, итог) => изКаталога('ужеБыло', { время: hm, итог }) || 'Это уже сделано в ' + hm + ' (итог: ' + итог + '). Второй раз не делаю.',
    перекрытие: (чат, кратко) => изКаталога('перекрытие', { чат, просьба: кратко }) || 'В «' + чат + '» ждёт ответа просьба филиала: ' + кратко + '. Ничего не делали — ответьте филиалу или «Всё равно сделать».',
    неПроверено: (чат) => изКаталога('перекрытиеНеПроверено', { чат }) || 'Не смог проверить «' + чат + '» на просьбы филиала (программа Telegram не на связи). Ничего не делали.',
    tgПослеCRM: (crm, чат, ошибка, текст) => изКаталога('тгПослеCRM', { crm, чат, ошибка, текст }) || 'В CRM сделано (' + crm + '). В «' + чат + '» не отправилось: ' + ошибка + '. Текст: «' + текст + '»',
    нетЧата: (город, текст) => изКаталога('нетЧата', { город, текст }) || 'Чат города «' + город + '» не найден среди групп Telegram — напишите вручную: «' + текст + '»',
    причина: (варианты) => изКаталога('причина', { варианты }) || 'CRM просит выбрать причину: ' + варианты + '. Выберите и нажмите «Сохранить причину».',
    get пусто() { return изКаталога('пусто') || 'В карточке не заполнено «Город / Тип / Непрофильная» — CRM не даст сохранить. Заполните в CRM.'; },
    // 2.2.5: ядро дало варианты пустых обязательных полей — выбор прямо в итоге
    пустоВыбор: (поля) => изКаталога('пустоВыбор', { поля: поля.join(', ') }) || 'В карточке не заполнено «' + поля.join(', ') + '» — выберите и нажмите «Заполнить и повторить» (или заполните в CRM)',
    неожиданно: (кратко) => изКаталога('неожиданно', { кратко }) || 'CRM ответила не так, как ожидалось (' + кратко + '). Ничего больше не делаю — сделайте это действие в CRM.',
    get неясно() { return изКаталога('неясно') || 'Не знаю, прошло ли прошлое нажатие (вкладку закрыли или CRM не ответила). Повторно не делаю — нажмите «Проверить».'; },
    get неясноЧат() { return изКаталога('неясноЧат') || 'Не знаю, ушло ли прошлое сообщение в чат (вкладку закрыли посреди отправки). Повторно не отправляю — нажмите «Проверить».'; },
  };
  // пороги — из таблицы каталога (LC_ACT.НАСТРОЙКИ.пороги), иначе по проекту: «тот же ключ за 10 мин — уже сделано» (раздел 6),
  // «визит прошёл больше 10 мин — «Где мастер?» первой» (раздел 4.3)
  const порог = (имя, запас) => { try { const x = Number(LC_ACT.НАСТРОЙКИ.пороги[имя]); if (x > 0) return x; } catch (_e) { /* по умолчанию */ } return запас; };
  const повторМс = () => порог('повторКлючМин', 10) * 60e3;
  const БАЗЫ = { kp: 'КП', mnc: 'МНЧ', bt: 'БТ' };
  // сайт базы — для «Войти в CRM», когда сессия истекла (как crm.js)
  const САЙТЫ = { bt: 'https://bt-lead-centre.ru', kp: 'https://kp-lead-centre.ru', mnc: 'https://mnc-lead-centre.ru' };
  // CRM требует войти заново: код ядра или текст ответа
  const сессияЛи = (r) => { const к = String((r && (r.code || r.kind)) || ''), e = String((r && r.error) || ''); return к === 'session' || к === 'сессия' || (!e && /сесси/i.test(к)) || /сесси|войдите в|страница входа/i.test(e); };
  // итог, после которого автозакрывать нельзя: есть строка-предупреждение «⚠ …»
  const естьПредупреждение = (строки) => (строки || []).some((t) => /^\s*⚠/.test(String(t || '')));

  /* Поля карточки по ключу действия, если каталог (LC_ACT.КАТАЛОГ[key].поля) своих не дал. name — ключ во «вводе» для LC_ACT.план
     (имена — как читает план PB). Списки причин — LC_ACT.причины, если там есть; иначе — по регламенту (проект 1.20, разделы 3.3.x).
     Без значения по умолчанию там, где выбор — суть действия (случай «стыка», причина отмены): кнопка ждёт выбора оператора */
  const ПРИЧИНЫ = {
    перенос: ['Клиент', 'Диспетчер', 'Директор'],
    филиал: ['опоздание более 10 минут', 'перенос по просьбе города', 'принята по закрепу, хотя клиент мог раньше', 'клиент не согласен с переносом'],
    нф: ['НФ, не профиль', 'НФ, помощь не нужна', 'НФ, дубль', 'клиент не выходит на связь', 'отмена полиция ищет мастера'],
    уточнение: [['517', 'НФ не акт'], ['571', 'Отказался от озвучки'], ['578', 'Дубль'], ['579', 'Не отвечает']],
    стык: ['должен денег', 'гарантия дистанционно', 'техника у мастера (только СД)', 'мастер не понимает, куда идти', 'за чертой — запчасти', 'мастер не может встретиться после 2 недозвонов'],
  };
  const даты = [{ name: 'date', label: 'Дата', type: 'date', required: true }, { name: 'time', label: 'Время', type: 'time', required: true }];
  const ПОЛЯ = {
    move: [...даты, { name: 'reason', label: 'Причина переноса', type: 'select', options: 'перенос', value: 'Клиент' },
      { name: 'agreed', label: 'согласовано с клиентом', type: 'check', when: (v) => v.reason === 'Директор' }],
    late: [{ name: 'minutes', label: 'Опаздывает, минут', type: 'number', required: true }],
    flags: [...ФЛАГИ.map(([name, label]) => ({ name, label, type: 'check', flag: true, исключает: name === 'callCheck' ? 'callBeforeVisit' : name === 'callBeforeVisit' ? 'callCheck' : '' })),
      { name: 'farRide', label: 'Дальний выезд', type: 'check', flag: true },
      { name: 'type', label: 'Тип заявки', type: 'select', options: [['10', 'Впервые'], ['20', 'Повтор'], ['30', 'Гарантия']] },
      { name: 'zakrepText', label: 'Текст закрепа (в служебный)', type: 'text', when: (v) => v.zakrep === true },
      { name: 'callTime', label: 'Когда звонить', type: 'time', when: (v) => v.callCheck === true },
      { name: 'ктоЗвонит', label: 'Кто звонит', type: 'select', options: [['клиент', 'клиент позвонит сам'], ['мы', 'звоним мы']], value: 'клиент', when: (v) => v.callCheck === true }],
    comment: [{ name: 'field', label: 'Куда', type: 'select', options: [['comment', 'Комментарий'], ['service', 'Служебный'], ['partner', 'Комментарий партнёра']], value: 'comment' },
      { name: 'text', label: 'Дописать строку', type: 'textarea', required: true }],
    branch_comment: [{ name: 'text', label: 'Комментарий филиала', type: 'textarea', required: true }],
    cancel_kc: [{ name: 'reason', label: 'Причина (в комментарий и партнёру)', type: 'select', options: 'отмена', required: true },
      { name: 'виноват', label: 'Отмена из-за ошибки', type: 'select', options: [['', 'нет (клиент сам)'], ['кц', 'ошибка КЦ'], ['филиал', 'ошибка филиала']], value: '' }],
    cancel_branch: [{ name: 'reason', label: 'Причина', type: 'select', options: 'филиал', required: true }],
    rejected: [{ name: 'reason', label: 'Партнёру', type: 'select', options: 'нф', value: 'НФ, не профиль' }],
    to_not_taken: [{ name: 'reason', label: 'Причина для партнёра', type: 'select', options: 'нф', required: true }],
    precheck_close: [{ name: 'code', label: 'Причина «Не оформлена»', type: 'select', options: 'уточнение', required: true }],
    precheck_await: даты,
    mod_not_taken: [{ name: 'reason', label: 'Партнёру', type: 'select', options: 'нф', value: 'НФ, помощь не нужна' }],
    await_from_cancel: даты,
    await_from_nf: даты,
    transfer: [{ name: 'server', label: 'В какую базу', type: 'select', options: 'базы', required: true }],
    claim: [{ name: 'typeNo', label: 'Тип претензии', type: 'select', options: 'претензии', required: true },
      { name: 'text', label: 'Со слов клиента', type: 'textarea' }],
    claim_again: [{ name: 'text', label: 'Кратко, что говорит клиент', type: 'textarea', required: true }],
    feedback: [{ name: 'link', label: 'Ссылка на отзыв', type: 'text', required: true }, { name: 'type', label: 'Тип отзыва', type: 'select', options: [['601', 'КЦ Отзыв'], ['600', 'Филиал']], value: '601' },
      { name: 'comment', label: 'Комментарий', type: 'textarea' }],
    mod_save: [...даты, { name: 'городПроверен', label: 'город уточнил у клиента', type: 'check', required: true }],
    sama: [{ name: 'взять', label: 'взять заявку в работу', type: 'check', value: true }],
    pz_agreed: даты,
    pz_noanswer: [{ name: 'date', label: 'Дата звонка', type: 'date' }, { name: 'time', label: 'Время звонка', type: 'time' }],
    styk: [{ name: 'случай', label: 'Разрешённый случай (регламент)', type: 'select', options: 'стык', required: true }],
    repeat_ask: [{ name: 'вид', label: 'Что спросить', type: 'select', options: [['повтор', 'повтор поедем?'], ['гарантия', 'гарантию поедем?']], value: 'повтор' }],
  };
  const ГРУППЫ = ['Время', 'Статус', 'Галочки', 'Заявка', 'Сообщения в город', 'Претензии', 'Модерация', 'Прозвон', 'Клиент'];
  // в превью «В CRM:» — словами, что делает шаг (рецепты crmact.js)
  const РЕЦЕПТЫ = { fields: 'сохранить поля карточки', flag: 'кнопка CRM', link: 'кнопка CRM', goto: 'переход CRM', comments: 'комментарии карточки', noanswer: 'кнопка «Не отвечает»',
    modalFeedback: '«Негативный отзыв»', modalBranchComment: 'комментарий филиала', claim: 'претензия', awaitFromCancel: '«Вернуть в Ожидает»', move: 'перенос',
    city: 'город заявки', worktype: 'вид работ и услуг' };
  const ИКОНКИ = {
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    phone: '<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/>',
    flag: '<path d="M5 21V4M5 4h11l-2 4 2 4H5"/>',
    msg: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    swap: '<path d="M7 7h13l-3-3M17 17H4l3 3"/>',
    undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>',
    alert: '<path d="M12 8v5M12 16h.01"/><circle cx="12" cy="12" r="9"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    note: '<path d="M5 4h14v16H5z"/><path d="M9 9h6M9 13h6M9 17h3"/>',
    star: '<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>',
    dots: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    // 2.1 (проект «Действия»): плитки 20 px — календарь, отмена (круг с минусом), булавка, молния, перо, крестик в круге
    cal: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/>',
    stop: '<circle cx="12" cy="12" r="9"/><path d="M8 12h8"/>',
    pin: '<path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/>',
    bolt: '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>',
    pen: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    x: '<circle cx="12" cy="12" r="9"/><path d="m15 9-6 6M9 9l6 6"/>',
    redo: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
    bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/>',
  };
  /* ---------- 2.1: вид (проект Claude Design «Действия», «Отмена», «Уведомления») — только показ, в CRM / чат / LeadChat то же ---------- */
  const ТИПЫ = { 10: 'Впервые', 20: 'Повтор', 30: 'Гарантия' };
  const ДН = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];
  // «сб 10.10, 15:00» (год — только если не этот)
  function визитКратко(snap) {
    const iso = isoД(snap && snap.visitDate), t = String((snap && snap.visitTime) || '').slice(0, 5);
    if (!iso && !t) return '';
    let д = '';
    if (iso) {
      const [y, m, d] = iso.split('-').map(Number);
      д = ДН[new Date(Date.UTC(y, m - 1, d, 12)).getUTCDay()] + ' ' + iso.slice(8, 10) + '.' + iso.slice(5, 7) + (y !== new Date().getFullYear() ? '.' + y : '');
    }
    return [д, t].filter(Boolean).join(', ');
  }
  // строка «Переносов» CRM («Перенос с "06.10.2026/10:00" на "07.10.2026/12:00" Клиент») → «06.10 10:00 → 07.10 12:00 · Клиент»; иначе как есть
  function переносКратко(t) {
    const s = String(t || '').trim();
    const m = s.match(/"(\d{1,2})\.(\d{1,2})\.\d{4}\/?(\d{1,2}:\d{2})?"\s*на\s*"(\d{1,2})\.(\d{1,2})\.\d{4}\/?(\d{1,2}:\d{2})?"\s*(.*)$/);
    if (!m) return s;
    const к = (d, mm, hm) => d.padStart(2, '0') + '.' + mm.padStart(2, '0') + (hm ? ' ' + hm : '');
    return к(m[1], m[2], m[3]) + ' → ' + к(m[4], m[5], m[6]) + (m[7].trim() ? ' · ' + m[7].trim() : '');
  }
  // цвет статуса заявки (метка): отмены и отказы — красный, в работе / в пути / готово — зелёный, остальное — «сведения»
  const цветСтатуса = (t) => (/отмен|отказ|не оформ|не созд/i.test(String(t || '')) ? 'bad' : /работ|пути|выполн|готов/i.test(String(t || '')) ? 'ok' : 'info');
  // «обновлено 12 с назад» / «обновлено 3 мин назад»
  const обновлено = (at) => { const с = at ? Math.max(0, Math.round((Date.now() - at) / 1000)) : 0; return 'обновлено ' + (с < 60 ? с + ' с' : Math.round(с / 60) + ' мин') + ' назад'; };
  /* предупреждение плана — одной строкой без штрафа и номера регламента: они — в «почему» (подсказка при наведении).
     Сам текст плана (и что уйдёт в CRM / чат) не меняется — только как он показан */
  function разобратьПредупреждение(t) {
    let s = String(t == null ? '' : t).replace(/^\s*⚠\s*/, '').trim();
    const почему = [];
    s = s.replace(/^рег:\s*([\d–\-,\s]+):\s*/i, (_m, x) => { почему.push('рег:' + x.trim()); return ''; });
    s = s.replace(/\s*\((рег:[^)]*|регламент)\)/gi, (_m, x) => { почему.push(x.trim()); return ''; });
    s = s.replace(/\s*\((?:[^()]*\s)?штраф\s+[\d\s–\-]+₽[^()]*\)/gi, (m) => { почему.unshift(m.trim().replace(/^\(|\)$/g, '')); return ''; });
    s = s.replace(/\s*[—-]\s*штраф\s+([\d\s–\-]+₽)/gi, (_m, x) => { почему.unshift('штраф ' + x.trim()); return ''; });
    s = s.replace(/\s+([:;,.])/g, '$1').replace(/\s{2,}/g, ' ').trim();
    if (s) s = s[0].toUpperCase() + s.slice(1);
    return { текст: s || String(t || ''), почему: почему.join(' · ') };
  }
  const сЗаглавной = (s) => { const x = String(s == null ? '' : s); return x ? x[0].toUpperCase() + x.slice(1) : x; };
  // вид строки итога: ok — сделано, warn — не знаю / сделайте сами, bad — не получилось, mut — ничего не делали
  const ВИД_СТРОКИ = { ok: '✓', bad: '✗', warn: '!', mut: '—' };
  // строка шага CRM: «⚠ …» (предупреждение ядра) — жёлтая, остальное — сделано
  const видТекста = (t) => (/^\s*⚠/.test(String(t == null ? '' : t)) ? 'warn' : 'ok');
  // 2.2.9: строки ядра (заметки, предупреждения) — в итог: без лишних пробелов, не длиннее 200, без повторов
  const дописатьСтроки = (куда, что, знак) => {
    for (const x of что || []) {
      const t = String(x == null ? '' : x).replace(/\s+/g, ' ').trim().slice(0, 200);
      if (t && !куда.some((y) => String(y).replace(/^\s*⚠\s*/, '') === t)) куда.push((знак || '') + t);
    }
  };

  function создать(хост) {
    const { h, send, store } = хост;
    const card = хост.card;
    const ВКЛАДКА = хост.новыйId();                                      // чья запись «run» в журнале — своя или чужой вкладки
    // запись 'created' — под замком хоста (content.js: одна очередь правок со всеми писателями); нет хоста (проверки) — как было
    const правитьCreated = typeof хост.правитьCreated === 'function' ? хост.правитьCreated
      : async (fn) => { const all = (await store.get('created', {})) || {}; if ((await fn(all)) !== false) await store.set('created', all); return all; };
    const ИДУТ = new Map();                                             // замок заявки → задание этой вкладки (второй щелчок — сразу «занято»)
    const СНИМКИ = new Map();                                           // dir:id → {at, card}: сетка → карточка без второго чтения CRM
    let ЧАТЫ = null;
    const есть = () => typeof LC_ACT !== 'undefined' && LC_ACT;
    const база = (dir) => (хост.dirName && хост.dirName(dir)) || БАЗЫ[dir] || dir || '';
    const иконка = (name, размер) => {
      const р = размер || 16;
      if (ИКОНКИ[name] && typeof document !== 'undefined') { const s = document.createElement('span'); s.style.display = 'inline-flex'; s.innerHTML = '<svg width="' + р + '" height="' + р + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="' + (р > 16 ? 2 : 1.8) + '" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ИКОНКИ[name] + '</svg>'; return s; }
      try { return хост.svg(name || 'chev'); } catch (_e) { return хост.svg('chev'); }
    };
    // иконка плитки (проект «Действия»): «Срочная» — молния, «Прозвон» — телефон, «Дописать» — перо, отказы — крестик
    const иконкаПлитки = (x) => {
      const в = x.ввод || {};
      if (x.key === 'flags' && в.urgent !== undefined) return 'bolt';
      if (x.key === 'flags' && в.callCheck !== undefined) return 'phone';
      if (x.key === 'comment') return 'pen';
      return x.icon || (каталог(x.key) || {}).icon || 'chev';
    };
    const каталог = (key) => ((есть() && LC_ACT.КАТАЛОГ && LC_ACT.КАТАЛОГ[key]) || null);
    const имяДействия = (key, план) => (план && план.title) || (каталог(key) || {}).label || key;
    const поОдному = (name, fn) => (хост.поОдному ? хост.поОдному(name, fn) : fn());
    const копировать = async (text, b) => { try { await navigator.clipboard.writeText(String(text)); if (b) b.textContent = 'Скопировано'; } catch (_e) { if (b) b.textContent = 'Не вышло — выделите текст'; } };

    /* ---------- CRM: снимок карточки (без личных данных) ---------- */
    /* 2.1: вместе со снимком — подробности для «Что в заявке» (snap {details}: комментарии, «Переносы», адрес — с маской телефонов,
       списки городов и видов работ карточки). Только в памяти вкладки: ни в журнал, ни в заметки они не попадают.
       После действия снимок — из ответа CRM, подробностей в нём нет (details: null) — следующая карточка перечитает CRM */
    async function снимок(cr, свежий) {
      const k = cr.dir + ':' + cr.id, x = СНИМКИ.get(k);
      if (!свежий && x && Date.now() - x.at < 30e3 && x.details !== null) return { ok: true, card: x.card, details: x.details || null, at: x.at };
      const r = await сроком(send({ kind: 'lcz-crm', op: 'snap', args: { dir: cr.dir, id: String(cr.id), details: true } }), 60e3, 'CRM не ответила за минуту');
      if (!r || !r.ok || !r.card) return { ok: false, error: (r && r.error) || 'карточка CRM не прочиталась' };
      // подробностей CRM не дала (старое ядро) — undefined: снимок годен и без них
      const details = r.details && typeof r.details === 'object' && !r.details.error ? r.details : undefined;
      СНИМКИ.set(k, { at: Date.now(), card: r.card, details });
      return { ok: true, card: r.card, details: details || null, at: Date.now() };
    }
    const запомнитьСнимок = (cr, c) => { if (c) СНИМКИ.set(cr.dir + ':' + cr.id, { at: Date.now(), card: c, details: null }); };
    /* претензии по заявке с № и статусом (snap {claims} — список ОКК, только чтение); минуту помним */
    const ПРЕТЕНЗИИ = new Map();
    async function претензии(cr, свежие) {
      const k = cr.dir + ':' + cr.id, x = ПРЕТЕНЗИИ.get(k);
      if (!свежие && x && Date.now() - x.at < 60e3) return x.r;
      let r;
      try { r = await сроком(send({ kind: 'lcz-crm', op: 'snap', args: { dir: cr.dir, id: String(cr.id), claims: true } }), 60e3, 'CRM не ответила за минуту'); } catch (e) { r = { ok: false, error: String((e && e.message) || e) }; }
      const пр = r && r.ok && r.claims && typeof r.claims === 'object' ? r.claims : { ok: false, error: (r && r.error) || 'CRM не ответила' };
      if (пр.ok !== false) ПРЕТЕНЗИИ.set(k, { at: Date.now(), r: пр });
      return пр;
    }
    /* виды услуг для вида работ (snap {subFor} — как форма CRM при смене «Вида работ»); 5 минут помним */
    const ВИДЫ_УСЛУГ = new Map();
    async function видыУслуг(cr, applId) {
      const k = cr.dir + ':' + cr.id + ':' + applId, x = ВИДЫ_УСЛУГ.get(k);
      if (x && Date.now() - x.at < 300e3) return x.r;
      let r;
      try { r = await сроком(send({ kind: 'lcz-crm', op: 'snap', args: { dir: cr.dir, id: String(cr.id), subFor: String(applId) } }), 60e3, 'CRM не ответила за минуту'); } catch (e) { r = { ok: false, error: String((e && e.message) || e) }; }
      const t = r && r.ok && r.subTypes && typeof r.subTypes === 'object' ? r.subTypes : { ok: false, error: (r && r.error) || 'CRM не ответила' };
      const out = { applId: String(applId), ok: t.ok !== false, list: Array.isArray(t.list) ? t.list : [], error: t.error ? String(t.error).slice(0, 120) : '' };
      if (out.ok) ВИДЫ_УСЛУГ.set(k, { at: Date.now(), r: out });
      return out;
    }
    /* своя дочитка для превью (без записи), если в каталоге её нет: «Вид работ» — виды услуг для выбранного вида работ */
    const ПОДГОТОВКА = {
      async worktype(snap, ввод, o) {
        if (!snap || !snap.hasSub) return { видыУслуг: null };
        const applId = String((ввод && ввод.applId) || snap.applId || '');
        if (!applId) return { видыУслуг: null };
        // вид работ — тот, что в карточке: её же варианты, CRM не спрашиваем
        if (applId === String(snap.applId || '') && o.подр && Array.isArray(o.подр.subs)) return { видыУслуг: { applId, ok: true, list: o.подр.subs } };
        return { видыУслуг: await видыУслуг(o.cr, applId) };
      },
    };
    /* «Что в заявке» (2.1, проект «Действия»): карточка CRM двумя колонками — визит, работа, галочки, претензия, адрес, комментарий,
       «Переносы» (новые сверху); служебный и комментарий партнёра — под «+ …». В карточке действия — коротко (визит, работа, галочки,
       претензия), остальное под «+ …». Подробности — snap {details}, претензии — snap {claims}. Телефоны — маской. Только показ.
       o: {атрибут, вСетке, чипы — кнопки галочек (сетка), доВизита — «через 2 ч», претензииЖдём, безПретензии, url} */
    const ГАЛОЧКИ_ВСЕ = [...ФЛАГИ, ['farRide', 'Дальний выезд']];
    const списком = (a) => (a.length < 2 ? a.join('') : a.slice(0, -1).join(', ') + ' и ' + a[a.length - 1]);
    function претензияКратко(пр, ждём) {
      if (ждём && !пр) return h('span', { class: 'ai-mut' }, 'смотрю в CRM…');
      if (!пр || typeof пр !== 'object') return h('span', { class: 'ai-mut' }, '—');
      if (пр.ok === false) return h('span', { class: 'ai-mut' }, 'список претензий не прочитался');
      const list = Array.isArray(пр.list) ? пр.list : [];
      if (!list.length) return h('span', { class: 'ai-mut' }, 'нет');
      return [...list.slice(0, 2).map((c, i) => [i ? ', ' : '', '№ ' + c.id + ' · ', h('span', { class: /закр|выполн|решен/i.test(c.status || '') ? 'ai-mut' : 'ai-warn' }, String(c.status || 'статус не прочитан').toLowerCase())]).flat(),
        list.length > 2 ? ' и ещё ' + (list.length - 2) : ''];
    }
    function сводка(snap, подр, пр, o) {
      if (!snap) return '';
      const x = o || {}, d = подр && typeof подр === 'object' ? подр : null;
      const главное = [], ещё = [], назв = [];
      const стр = (куда, метка, ...v) => куда.push(h('dt', {}, метка), h('dd', {}, ...v));
      const нет = (t) => h('span', { class: 'ai-mut' }, t);
      const в = визитКратко(snap), город = snap.cityName || '';
      стр(главное, 'Визит', в ? h('b', {}, в) : нет('не указан'), город ? ' · ' + город : '', x.доВизита ? h('span', { class: 'ai-mut' }, ' · ' + x.доВизита) : '');
      const тип = ((есть() && LC_ACT.причины && LC_ACT.причины.тип) || {})[snap.type] || ТИПЫ[snap.type] || '';
      const работа = [snap.applName, snap.subName, тип].filter(Boolean).join(' · ');
      стр(главное, 'Работа', работа || нет('не указана'));
      const on = ГАЛОЧКИ_ВСЕ.filter(([k]) => snap.flags && (snap.flags[k] === true || snap.flags[k] === '1'));
      стр(главное, 'Галочки', x.чипы && x.чипы.length ? h('div', { class: 'ag-chips' }, ...x.чипы)
        : on.length ? on.map(([k, t], i) => [i ? ' · ' : '', k === 'urgent' ? h('span', { class: 'ai-warn' }, t) : t]).flat() : нет('нет'));
      if (!x.безПретензии && (пр || x.претензииЖдём)) стр(главное, 'Претензия', претензияКратко(пр, x.претензииЖдём));
      if (d) {
        const куда = x.вСетке ? главное : ещё;
        const адрес = String(d.address || '').trim(), ком = String(d.comment == null ? '' : d.comment).trim();
        const пер = (Array.isArray(d.changes) ? d.changes : []).map((t) => String(t).trim()).filter(Boolean).reverse();
        if (адрес) { стр(куда, 'Адрес', маска(адрес)); if (куда === ещё) назв.push('адрес'); }
        if (ком) { стр(куда, 'Комментарий', h('div', { class: 'ai-txt', title: 'Нажмите, чтобы развернуть или свернуть', onclick: (e) => e.currentTarget.classList.toggle('open') }, маска(ком))); if (куда === ещё) назв.push('комментарий'); }
        if (пер.length) {
          const строка = (t, i) => h('div', { class: i ? 'ai-mut' : '', title: маска(t) }, маска(переносКратко(t)));
          const видно = x.вСетке ? пер.slice(0, 3) : пер;
          стр(куда, 'Переносы', h('div', { class: 'ai-list' }, ...видно.map(строка)));
          if (куда === ещё) назв.push('переносы (' + пер.length + ')');
          if (x.вСетке && пер.length > 3) { стр(ещё, 'Ранние', h('div', { class: 'ai-list' }, ...пер.slice(3).map((t) => строка(t, 1)))); назв.push('ранние переносы'); }
        }
        for (const [k, метка, имя] of [['service', 'Служебный', 'служебный'], ['partner', 'Партнёру', 'комментарий партнёра']]) {
          const t = String(d[k] == null ? '' : d[k]).trim();
          if (t) { стр(ещё, метка, h('div', { class: 'ai-txt', title: 'Нажмите, чтобы развернуть или свернуть', onclick: (e) => e.currentTarget.classList.toggle('open') }, маска(t))); назв.push(имя); }
        }
      }
      const список = пр && пр.ok !== false && Array.isArray(пр.list) ? пр.list : [];
      if (список.length && !x.безПретензии) {
        стр(ещё, 'Претензии', h('div', { class: 'ai-list' }, ...список.map((c) => h('div', {}, маска('№ ' + c.id + ' — «' + (c.status || 'статус не прочитан') + '»' + (c.type ? ', ' + c.type : '') + (c.created ? ', от ' + c.created : ''))))));
        назв.push('претензии (' + список.length + ')');
      }
      const url = x.url || snap.url || '';
      return h('section', { 'data-ac': x.атрибут || 'info', class: 'ac-info' + (x.вСетке ? ' wide' : '') },
        h('div', { class: 'ai-h' }, h('h2', {}, 'Что в заявке'), /^https?:/.test(url) ? h('a', { class: 'ai-crm', href: url, target: '_blank', rel: 'noopener' }, 'открыть в CRM ↗') : ''),
        h('dl', { class: 'ai-dl' }, ...главное),
        ещё.length ? h('details', { class: 'ac-dt ai-more', 'data-ac': 'info-more' }, h('summary', {}, '+ ' + списком(назв)), h('dl', { class: 'ai-dl' }, ...ещё)) : '');
    }
    // претензия строкой («Снова звонит», «Претензия»): № и статус из CRM; нет — так и пишем
    function строкаПретензии(пр, ждём) {
      if (!есть() || typeof LC_ACT.претензииКратко !== 'function') return '';
      const t = LC_ACT.претензииКратко(пр, { претензииЖдём: ждём, иНет: true });
      return t ? h('div', { class: 'ac-line info', 'data-ac': 'claim' }, h('b', {}, 'В CRM: '), маска(t)) : '';
    }
    async function чаты(свежие) {
      if (!свежие && ЧАТЫ && Date.now() - ЧАТЫ.at < 60e3) return ЧАТЫ;
      const r = await сроком(send({ kind: 'lcz-tg', args: { action: 'chats' } }), 25e3, 'Telegram не ответил');
      if (!r || !r.ok) return { ok: false, error: (r && r.error) || 'группы Telegram не получены', chats: {} };
      ЧАТЫ = { ok: true, chats: r.chats || {}, at: Date.now() };
      return ЧАТЫ;
    }
    /* ctx для LC_ACT (доступные / план / подсказка): что знает экран о заявке и диалоге, кроме снимка CRM.
       Время в городе заявки — для предупреждений «раньше 10:00», «через час»; опоздание — «Где мастер?» первой.
       Телефон и служебный (СД, «стык») — только в памяти этой карточки, ни в журнал, ни в заметки не попадают */
    function ctxДля(conv, cr, источник, snap, доп) {
      const tz = (хост.ПОЯС && хост.ПОЯС(conv)) || '';
      const город = (snap && snap.cityName) || cr.city || '';
      let сейчас = null, опоздание = null;
      try {
        if (typeof LC_EXTRACT !== 'undefined' && LC_EXTRACT.localParts) {
          const z = LC_EXTRACT.clientTz ? LC_EXTRACT.clientTz(tz, город).tz : tz;
          const d = new Date(), n = LC_EXTRACT.localParts(d, z);
          if (n && n.iso) сейчас = { date: n.iso, time: n.hm, сек: d.getSeconds() };
        }
      } catch (_e) { /* без часов города — без предупреждений о времени */ }
      if (snap && snap.visitTime) {
        try { const x = хост.визитСейчас({ city: город, visit: snap.visitDate || '', visitTime: snap.visitTime || '' }, tz); if (x && x.late > 0) опоздание = x.late; } catch (_e) { /* без опоздания */ }
      }
      return { conv, cr, dir: cr.dir, id: String(cr.id), city: город, город, created: cr, источник: источник || null, tz, now: Date.now(), сейчас, опоздание,
        чатЗаявки: cr.chat || '', claimMsg: cr.claimMsg || null,
        // претензия есть: её сообщение в чате или CRM (op 'claims' — «по заявке» и сведения карточки); неизвестно — не «нет»
        hasClaim: cr.claimMsg ? true : cr.hasClaim === undefined || cr.hasClaim === null ? undefined : !!cr.hasClaim, закреп: cr.zakrep || '', technika: cr.work || '',
        ...(ЧАТЫ && ЧАТЫ.ok ? { чаты: ЧАТЫ.chats } : {}), ...(доп || {}) };
    }
    /* что дочитать для карточки (без записи): было ли согласование в чате города по диалогу (итог — ответом), телефон и служебный
       для СД / «стыка» (из CRM, как карточка «по заявке»), чаты Telegram (без чата «Модерации» плитки «Сама набрала» нет) */
    const НУЖЕН_ТЕЛ = (key, snap) => key === 'sd_call' || key === 'styk' || (key === 'where' && snap && snap.statusCode === 9);
    async function сведения(conv, cr, key, snap) {
      const доп = {};
      const ждём = [];
      // претензия: есть ли уже в CRM (создана там же, из другого диалога, при выключенном Telegram) — «Претензия» или «Снова звонит»
      if ((key === 'claim' || key === 'claim_again') && !cr.claimMsg && (cr.hasClaim === undefined || cr.hasClaim === null)) {
        ждём.push(сроком(send({ kind: 'lcz-crm', op: 'claims', args: { dir: cr.dir, id: String(cr.id) } }), 30e3).then((r) => { if (r && r.ok) доп.hasClaim = Number(r.count) > 0; }).catch(() => {}));
      }
      if (conv) ждём.push(Promise.resolve().then(() => хост.tgSentGet(conv)).then((rec) => { if (rec && хост.sentList(rec).length) доп.согласование = true; }).catch(() => {}));
      if (НУЖЕН_ТЕЛ(key, snap)) {
        if (cr.phone10) доп.тел = cr.phone10;
        if (cr.service) доп.служебный = cr.service;
        if (!доп.тел) ждём.push(сроком(send({ kind: 'lcz-crm', op: 'info', args: { dir: cr.dir, id: String(cr.id) } }), 30e3).then((r) => {
          const i = r && r.ok && r.info;
          if (i && i.phone10) доп.тел = i.phone10;
          if (i && i.serviceComment) доп.служебный = i.serviceComment;
        }).catch(() => {}));
      }
      чаты().catch(() => null);                                       // группы Telegram — не ждём: нужны превью чата, а не кнопке
      await Promise.all(ждём);
      return доп;
    }
    function доступные(snap, ctx) {
      if (!есть() || !snap) return [];
      try { return (LC_ACT.доступные(snap, ctx) || []).filter((x) => x && x.key); } catch (_e) { return []; }
    }
    function план(key, snap, ввод, ctx) {
      if (!есть()) return { error: 'каталог действий не загружен — обновите страницу LeadChat (F5)' };
      try { return LC_ACT.план(key, snap, ввод || {}, ctx) || { error: 'действие «' + key + '» не описано' }; }
      catch (e) { return { error: 'не получилось собрать действие: ' + String((e && e.message) || e).slice(0, 120) }; }
    }
    const ключЖурнала = (dir, id, key, ввод) => {
      if (есть() && typeof LC_ACT.ключДействия === 'function') { try { const k = LC_ACT.ключДействия(dir, String(id), key, ввод || {}); if (k) return String(k); } catch (_e) { /* свой ключ */ } }
      return 'act:' + dir + ':' + id + ':' + key + ':' + хэш(канон(ввод || {}));
    };
    const пусто = (x) => x === undefined || x === '' || x === false || x === null;
    // план не готов к исполнению: LC_ACT сказал (ok:false + missing / недоступно / invalid / error) или не заполнено обязательное поле карточки
    function чегоНет(key, план, ввод, поля) {
      const нет = [];
      if (!план) return ['действие не собрано'];
      if (план.error) нет.push(план.error);
      if (план.invalid) нет.push(typeof план.invalid === 'string' ? план.invalid : 'не всё заполнено');
      if (Array.isArray(план.missing)) нет.push(...план.missing);
      if (план.недоступно) нет.push('сейчас недоступно: ' + план.недоступно);
      if (план.ok === false && !нет.length) нет.push(план.why || 'не всё заполнено');
      // поле, уже названное планом («дата и время визита» — это и «Дата», и «Время»), второй раз не называем
      const названо = (Array.isArray(план.missing) ? план.missing : []).map((x) => String(x).toLowerCase());
      for (const f of поля || []) {
        if (!f.required || (f.when && !f.when(ввод)) || !пусто(взять(ввод, f.name))) continue;
        const м = String(f.label || f.name).toLowerCase().replace(/\s*\*$/, '');
        if (!названо.some((x) => x.includes(м))) нет.push(f.label);
      }
      const было = new Set();
      return нет.map(String).filter((x) => { const k = x.toLowerCase(); if (было.has(k)) return false; было.add(k); return true; });
    }
    /* подписчики на сделанное (подсказки watch-act: напоминания «Не отвечает», прозвон за мной…). Нет подписчиков — хост.послеДействия */
    const ПОДПИСЧИКИ = new Set();
    function подписаться(fn) { if (typeof fn === 'function') ПОДПИСЧИКИ.add(fn); return () => ПОДПИСЧИКИ.delete(fn); }
    function сообщить(x) {
      const кому = ПОДПИСЧИКИ.size ? [...ПОДПИСЧИКИ] : typeof хост.послеДействия === 'function' ? [хост.послеДействия] : [];
      for (const fn of кому) { try { Promise.resolve(fn(x)).catch(() => {}); } catch (_e) { /* подсказки — не главное */ } }
    }

    /* ---------- куда писать в Telegram ---------- */
    async function послОтветФилиала(chat, msg) {
      try { const rr = await сроком(send({ kind: 'lcz-tg', args: { action: 'replies', chat, msg } }), 20e3); const п = ((rr && rr.replies) || []).filter((y) => y.id).pop(); return п ? п.id : msg; }
      catch (_e) { return msg; }
    }
    // «снова звонит» — ответом на «Новая претензия»: помним её сообщение; нет — ищем в последних 100 сообщениях чата претензий
    async function найтиПретензию(chat, id) {
      const r = await сроком(send({ kind: 'lcz-tg', args: { action: 'recent', chat, n: 100, since: 0 } }), 25e3);
      const m = ((r && r.ok && r.messages) || []).filter((x) => String(x.text || '').includes(String(id)) && /претенз/i.test(String(x.text || ''))).pop();
      return m ? m.id : 0;
    }
    async function куда(conv, cr, tg, snap) {
      if (!tg) return null;
      const c = await чаты();
      const город = (snap && snap.cityName) || cr.city || '';
      // программа Telegram не на связи — чат города и на просьбы филиала не проверить: бегунок CRM не тронет (раздел 6, п. 3)
      if (!c.ok) return { нет: 'группы Telegram не получены (' + c.error + ')', город, тгНет: true };
      const chats = c.chats, title = (id) => ((chats[id] || {}).title || '');
      let m = null, reply = 0, заметка = '';
      if (tg.kind === 'claims') m = LC_TG.claimChat(chats, cr.dir);
      else if (tg.kind === 'moderation') m = typeof LC_TG.moderationChat === 'function' ? LC_TG.moderationChat(chats, cr.dir) : null;
      else {
        if (tg.reply === 'approval') {
          // согласование по диалогу — в первый чат, как карточка «по заявке» (content.js чатПоЗаявке)
          const rec = хост.sentList(await хост.tgSentGet(conv))[0];
          if (rec && rec.chat) { m = { id: rec.chat, title: rec.title || title(rec.chat) }; reply = await послОтветФилиала(rec.chat, rec.msg); }
        }
        if (!m && cr.chat) m = { id: cr.chat, title: cr.chatTitle || title(cr.chat) };
        if (!m) { const x = LC_TG.matchChat(chats, cr.dir, город); if (x) m = { id: x.id, title: x.title, options: x.options || [] }; }
      }
      if (!m || !m.id) return { нет: tg.kind === 'claims' ? 'чат претензий не найден' : tg.kind === 'moderation' ? 'чат модерации не найден' : ОШИБКИ.нетЧата(город || '?', '…').replace(/ — напишите.*$/, ''), город };
      if (tg.reply === 'claimMsg') {
        if (cr.claimMsg && String(cr.claimMsg.chat) === String(m.id)) reply = cr.claimMsg.msg;
        else { reply = await найтиПретензию(m.id, cr.id).catch(() => 0); if (!reply) заметка = '«Новая претензия» по заявке в чате не нашлась — уйдёт отдельным сообщением'; }
      }
      return { id: m.id, title: m.title || title(m.id), reply: reply || 0, kind: tg.kind || 'city', город,
        options: [...new Set([m.id, ...(m.options || [])])].map((id) => ({ id, title: title(id) || id })), заметка };
    }

    /* ---------- журнал действий: chrome.storage.local.actLog, 7 дней; телефоны маскируются, комментарии не пишутся ---------- */
    const ЖУРНАЛ_МС = 7 * 864e5;
    async function журнал(fn) {
      return поОдному('lcz-act-log', async () => {
        const all = (await store.get('actLog', {})) || {};
        const out = await fn(all);
        if (out && out.записать) {
          const now = Date.now();
          for (const k of Object.keys(all)) {
            if (!all[k] || now - (all[k].at || 0) > ЖУРНАЛ_МС) delete all[k];
            // записи до 2.0.0 хранили текст чата и подписи шагов со словами клиента — стираем их (остальное нужно журналу)
            else if (all[k].v !== 2) { delete all[k].tgТекст; all[k].итог = all[k].итог ? 'сделано' : ''; all[k].v = 2; }
          }
          const keys = Object.keys(all);
          if (keys.length > 500) keys.sort((a, b) => all[a].at - all[b].at).slice(0, keys.length - 500).forEach((k) => delete all[k]);
          await store.set('actLog', all);
        }
        return out && out.значение;
      }).catch(() => null);
    }
    const записать = (job, patch) => журнал((all) => {
      all[job.ключ] = { ...(all[job.ключ] || {}), v: 2, key: job.ключ, dir: job.dir, id: job.id, act: job.act, title: маска(job.title), conv: job.conv, tab: ВКЛАДКА, sig0: job.sig0 || '',
        цель: job.цель || null, at: (all[job.ключ] && all[job.ключ].state === 'run' && patch.state !== 'run' ? all[job.ключ].at : Date.now()), ...patch,
        итог: patch.итог !== undefined ? маска(patch.итог).slice(0, 200) : (all[job.ключ] || {}).итог || '' };
      return { записать: true };
    });
    // до CRM: этот же ключ недавно сделан — второй раз не делаем; «начато» без итога — не знаем, прошло ли
    async function повторЛи(job) {
      const now = Date.now();
      const x = await журнал((all) => {
        let з = all[job.ключ] || null;
        // «Не отвечает»: в ключе — счётчик отметок карточки, на которую смотрит оператор (новый звонок). Прошлое нажатие не дошло до
        // ответа (вкладку закрыли), а CRM отметку поставила — свежая карточка уже со счётчиком +1, ключ другой. Это то же нажатие:
        // «не знаю, прошло ли» и «Проверить» по ЕГО записи (счётчик до него), а не вторая отметка
        const база = String(job.ключ).replace(/:н\d+$/, '');
        if (!з && база !== job.ключ && job.snap && job.snap.noAnswerCount != null) {
          з = Object.values(all).find((y) => y && y.key && y.key !== job.ключ && String(y.key).replace(/:н\d+$/, '') === база && /^(run|неясно)$/.test(y.state)
            && now - (y.at || 0) < 12 * 3600e3 && Number((String(y.key).match(/:н(\d+)$/) || [])[1]) < Number(job.snap.noAnswerCount)) || null;
          if (з) job.ключ = з.key;
        }
        // после этой записи по той же заявке успешно сделано другое действие (Прозвон ✓ → ✗): сделанное могли отменить
        const позже = !!з && Object.values(all).some((y) => y && y.key !== job.ключ && y.dir === job.dir && String(y.id) === String(job.id) && y.at > з.at && /^(ok|частично)$/.test(y.state));
        return { значение: з ? { ...з, позже } : null };
      });
      if (!x) return null;
      // «начато» без итога (вкладку закрыли посреди действия) или «не знаю» — за полдня; старше — смена кончилась, решает оператор заново
      if ((x.state === 'run' || x.state === 'неясно') && now - x.at < 12 * 3600e3) {
        if (job.проверено) return null;
        return { состояние: 'неясно', text: (x.tgOnly ? ОШИБКИ.неясноЧат : ОШИБКИ.неясно) + (x.at ? ' (нажато в ' + чч(x.at) + ')' : ''), запись: x, проверить: true };
      }
      if (/^(ok|частично)$/.test(x.state) && now - x.at < повторМс() && !job.повтор && !сделанноеОтменено(job, x)) return { состояние: 'уже', text: ОШИБКИ.ужеБыло(чч(x.at), x.итог || 'сделано'), запись: x };
      // этот ключ уже делали (раньше окна «уже сделано», отменённое, неудачное) — это новое нажатие оператора: заметке и сообщению
      // клиенту — новые client_message_id (LeadChat помнит id навсегда: со старым он вернул бы прежнее, ничего не отправив)
      if (!job.повторМетка) job.повторМетка = now;
      return null;
    }
    /* client_message_id действия: от ключа (повтор того же хода — «повторить» у заметки, 429 — LeadChat узнает и второго не будет);
       «Сделать ещё раз» и новое нажатие по уже сделанному ключу — с меткой повтора: новая заметка, новое сообщение клиенту */
    const idLC = (job, приставка) => (приставка + хэш(job.ключ + (job.повторМетка ? ':повтор:' + job.повторМетка : ''))).slice(0, 64);
    const ужеЗаписано = (e) => !!(e && e.status === 409 && e.code === 'idempotency_mismatch');
    /* «уже сделано» — только если это правда по карточке, на которую смотрит оператор. Действие-состояние (галочки, взять / вернуть,
       статус, перенос): снимок НЕ в цели — сделанное с тех пор отменили (Прозвон ✓ → ✗ → ✓, «Взять» → «Вернуть» → «Взять») — делаем;
       от двойной записи бережёт ядро CRM (журнал ключа, «уже в цели», подпись превью). «Не отвечает»: в снимке уже есть наша отметка
       (счётчик не меньше, чем стал после неё) — это новый звонок, а не повтор. Остальное (комментарий, претензия, чат) — как было */
    const ЦЕЛЬ_СОСТОЯНИЕ = /^(statusCode|held|flags|type|visitDate|visitTime|changesCountPlus|cityId|applId|subId)$/;
    function сделанноеОтменено(job, x) {
      if (!job.snap || !(job.steps || []).length) return false;
      const цели = job.steps.map((st) => st.цель || {});
      const ключи = цели.flatMap((ц) => Object.keys(ц));
      if (!ключи.length || !ключи.every((k) => ЦЕЛЬ_СОСТОЯНИЕ.test(k) || k === 'noAnswerCountPlus')) return false;
      if (ключи.includes('noAnswerCountPlus')) return x.счётПосле != null && Number(job.snap.noAnswerCount) >= Number(x.счётПосле);
      const абс = {};
      for (const ц of цели) for (const [k, v] of Object.entries(ц)) if (!/Plus$/.test(k)) абс[k] = k === 'flags' && v && typeof v === 'object' ? { ...(абс.flags || {}), ...v } : v;
      if (!Object.keys(абс).length || совпадает(job.snap, абс) !== false) return false;
      // карточка прочитана после начала сделанного и не в цели — его отменили (и прямо в CRM: подпись тогда та же, что до него)
      if (Number(job.snap.at) > Number(x.at || 0)) return true;
      // карточка не в цели, но превью — с того же снимка, что и сделанное, и с тех пор по заявке ничего не делали: повтор старого превью
      return !(job.sig0 && x.sig0 && job.sig0 === x.sig0 && !x.позже);
    }

    /* ---------- замок заявки: navigator.locks во вкладке (offscreen держит свой) ---------- */
    async function подЗамком(name, fn) {
      if (typeof navigator !== 'undefined' && navigator.locks && navigator.locks.request) {
        let начато = false;
        try { return await navigator.locks.request(name, { ifAvailable: true }, (lock) => { начато = true; return fn(!!lock); }); }
        catch (e) { if (начато) throw e; /* замки недоступны — хватит ИДУТ этой вкладки */ }
      }
      return fn(true);
    }
    const неУходить = (e) => { e.preventDefault(); e.returnValue = ''; return ''; };
    let уходСлушаю = false;
    function обновитьУход() {
      const идут = ИДУТ.size > 0;
      if (идут === уходСлушаю) return;
      уходСлушаю = идут;
      try { if (идут) window.addEventListener('beforeunload', неУходить); else window.removeEventListener('beforeunload', неУходить); } catch (_e) { /* не страшно */ }
    }
    const занято = (cr) => !!cr && ИДУТ.has('lcz-act-' + cr.dir + '-' + cr.id);

    /* ---------- задание: снимок того, что показало превью; дальше не читает ни карточку, ни открытый диалог ---------- */
    /* шаги CRM из плана: один вид запроса для всех ядер (crmact 'act', карточка клиента PE 'custAct'): рецепт, параметры, цель,
       подпись превью (следующий шаг — с подписью карточки после предыдущего) и ключ действия (журнал ядра «не знаю — не повторяю») */
    function шагиИзПлана(з, ключ) {
      return ((з.план && з.план.steps) || []).map((s) => {
        const op = s.op || 'act', имя = s.title || s.name || описатьШаг(s);
        // 2.2.9: before — снимок карточки, к которому относится подпись (sig): ядро по нему понимает, ЧТО изменилось (для отмены другие кнопки
        // CRM не важны — «устарело» только когда сменился статус); снимок без личных данных
        const args = (sig, доп, до) => ({ dir: з.cr.dir, id: String(з.cr.id), recipe: s.action, action: s.action, params: { ...(s.params || {}), ...(доп || {}) },
          expect: s.expect || null, expectSig: sig || '', key: ключ, ...(до && sig && до.sig === sig ? { before: до } : {}) });
        return { title: имя, цель: s.expect || null, op,
          run: (sig, доп, до) => send({ kind: 'lcz-crm', op, args: args(sig, доп, до) }),
          // «Проверить» после «не знаю»: ядро CRM перечитывает карточку и сверяет с целью, ничего не пишет
          проверка: op === 'act' ? () => send({ kind: 'lcz-crm', op, args: { ...args('', null), check: true } }) : null,
          итог: (r) => (r.already ? имя + ': уже было в CRM' : (s.done || имя) + (r.lastChange ? ' (' + r.lastChange + ')' : '')),
          // журнал (7 дней в памяти расширения) — без слов клиента: в подписи шага бывают комментарий, причина, текст партнёру
          журнал: (r) => строкаЖурнала(s, имя) + (r.already ? ': уже было в CRM' : '') };
      });
    }
    /* строка журнала для шага CRM: что сделано, без свободного текста (комментарий, претензия, причина, партнёру, адрес) */
    const ПОЛЯ_ЖУРНАЛА = { comment: 'комментарий', service: 'служебный', partner: 'партнёру' };
    function строкаЖурнала(s, имя) {
      const p = s.params || {};
      if (s.op && s.op !== 'act') return String(s.title || s.name || РЕЦЕПТЫ[s.action] || s.action || 'CRM');
      switch (s.action) {
        case 'comments': return (p.replace ? 'заменено: ' : 'дописано: ') + Object.keys(p.replace || p.append || {}).map((k) => ПОЛЯ_ЖУРНАЛА[k] || 'поле').join(', ');
        case 'claim': return 'претензия' + (p.typeNo ? ' тип ' + Number(p.typeNo) : '') + (p.category ? ', категория ' + Number(p.category) : '');
        case 'modalBranchComment': return 'комментарий филиала';
        case 'modalFeedback': return 'негативный отзыв' + (p.type ? ' (' + Number(p.type) + ')' : '');
        case 'noanswer': return 'кнопка «Не отвечает»';
        case 'move': return 'перенос' + (p.date || p.time ? ' на ' + [дм(String(p.date || '')), String(p.time || '').slice(0, 5)].filter(Boolean).join(' ') : '');
        case 'fields': return String(имя || '').split(/;\s/)[0].trim() || РЕЦЕПТЫ.fields;
        default: return String(имя || '').split(/:\s|,\s|;\s|\s\+\s/)[0].trim() || РЕЦЕПТЫ[s.action] || s.action || 'CRM';
      }
    }
    function описатьШаг(s) {
      const p = s.params || {}, что = РЕЦЕПТЫ[s.action] || s.action || s.op || 'CRM';
      const где = [p.date ? String(p.date).split('-').reverse().join('.') : '', p.time || '', p.reason && typeof p.reason === 'string' ? '«' + p.reason + '»' : ''].filter(Boolean).join(' ');
      return что + (s.button ? ' «' + s.button + '»' : '') + (где ? ': ' + где : '');
    }
    const tgПлана = (п) => (п && п.tg && п.tg.kind ? п.tg : null);         // перевод в другую базу и т.п.: kind null — в чат не пишем
    // задание из карточки или из подсказки (watch-act): {conv, cr, key, ввод, план?, snap?, ctx?, чат?, tgText?, tgOn?, noteOn?, clientOn?, clientText?, источник?}
    async function собрать(з) {
      const cr = з.cr;
      if (!з.snap) { const s = await снимок(cr, true); if (!s.ok) return { ошибка: s.error }; з.snap = s.card; }
      if (!з.план) {
        const ctx = з.ctx || ctxДля(з.conv, cr, з.источник, з.snap, await сведения(з.conv, cr, з.key, з.snap));
        з.план = план(з.key, з.snap, з.ввод || {}, ctx);
      }
      const нет = чегоНет(з.key, з.план, з.ввод || {}, з.поля || []);
      if (нет.length) return { ошибка: 'не заполнено: ' + нет.join(', ') };
      const tg = tgПлана(з.план);
      if (tg && з.чат === undefined) з.чат = await куда(з.conv, cr, tg, з.snap);
      // «Не отвечает»: ввод пустой — новый звонок отличаем по счётчику отметок в карточке, на которую смотрит оператор (ключ и для
      // журнала, и для ядра CRM: его «только что сделано» иначе выдаст новый звонок за «уже было в CRM», отметки не поставив)
      const счёт = (з.план.steps || []).some((s) => s.expect && s.expect.noAnswerCountPlus) && з.snap.noAnswerCount != null && Number.isFinite(Number(з.snap.noAnswerCount))
        ? ':н' + Number(з.snap.noAnswerCount) : '';
      const ключ = з.ключ || ключЖурнала(cr.dir, cr.id, з.key, з.ввод || {}) + счёт;
      const tgOn = !!tg && (з.tgOn !== undefined && з.tgOn !== null ? !!з.tgOn : tg.on !== false);
      const цель = Object.assign({}, ...((з.план.steps || []).map((s) => s.expect || {})));
      const плТекст = String((tg && tg.text) || '');
      const правлен = з.tgText != null && String(з.tgText) !== плТекст;   // оператор поправил текст — уйдёт как есть
      const lc = з.план.lc || {};
      return { job: {
        ключ, act: з.key, dir: cr.dir, id: String(cr.id), conv: з.conv, cr, title: имяДействия(з.key, з.план), sig0: з.snap.sig || '', snap: з.snap, цель: Object.keys(цель).length ? цель : null,
        план: з.план, ввод: з.ввод || {}, steps: шагиИзПлана(з, ключ),
        tg: tg ? { on: tgOn, kind: tg.kind || 'city', chat: з.чат && з.чат.id, title: (з.чат && з.чат.title) || '', reply: (з.чат && з.чат.reply) || 0, нет: з.чат && з.чат.нет, город: (з.чат && з.чат.город) || cr.city || '',
          тгНет: !!(з.чат && з.чат.тгНет), text: правлен ? з.tgText : плТекст, изCRM: !правлен && !!(tg.fromCrm || tg.изCRM || tg.послеCRM), suffix: tg.suffix || '',
          послеОтправки: (r) => запомнитьСообщение(з, r) } : null,
        lc: { note: з.noteOn !== false && lc.note !== false, name: lc.nameNew ? 'new' : lc.name || false, noteText: typeof lc.note === 'string' ? lc.note : '',
          client: з.план.client && з.clientOn ? { on: true, text: з.clientText != null ? з.clientText : з.план.client.text } : null },
        client: з.client || null, force: з.force || false, наВиду: з.наВиду, тихо: !!з.тихо, источник: з.источник || null, з,
        сШага: з.сШага || 0, причина: з.причина, проверено: !!з.проверено, повтор: !!з.повтор, повторМетка: з.повтор ? Date.now() : 0,
        послеCRM: з.послеCRM || null,
      } };
    }
    // ответ города на «где мс?» ловит watchWhere; «снова звонит» отвечает на «Новая претензия» — сообщения запоминаем, как раньше
    async function запомнитьСообщение(з, r) {
      if (!r || !r.message_id || !з.conv) return;
      const t = (з.план && з.план.tg) || {}, chat = з.чат && з.чат.id;
      const k = з.key === 'claim' || t.запомнить === 'claimMsg' ? 'claim' : з.key === 'where' || t.ждатьОтвет ? 'where' : '';
      if (!k) return;
      try {
        await правитьCreated((all) => {
          const was = all[з.conv] || з.cr;
          all[з.conv] = k === 'claim' ? { ...was, claimMsg: { chat, msg: r.message_id, at: Date.now() } }
            : { ...was, whereMsg: { chat, title: (з.чат && з.чат.title) || '', msg: r.message_id, at: Date.now(), seen: Math.floor(Date.now() / 1000), crId: з.cr.id, dir: з.cr.dir } };
        });
      } catch (_e) { /* не критично */ }
    }

    /* ---------- БЕГУНОК ---------- */
    const ЭТАП = { guard: 'Проверяю чат города…', crm: 'CRM…', tg: 'Telegram…', lc: 'LeadChat…', prep: 'Смотрю карточку в CRM…' };
    function этап(job, k, i) {
      if (job.этап !== k || job.шаг !== (i || 0)) job.этапС = Date.now();
      job.этап = k; job.шаг = i || 0;
      job.текстЭтапа = k === 'crm' ? 'CRM: ' + ((job.steps[i] || {}).title || '') + '…' : ЭТАП[k] || k;
      try {
        // наВиду не задан — экран вызвавшего сам показывает ход (карточка «по заявке», уведомление)
        if (!job.наВиду || job.наВиду()) { if (job.el) { job.el.remove(); job.el = null; } if (job.нарисовать) job.нарисовать(); }
        else if (!job.тихо && !job.el && job.этап !== 'prep') job.el = тостХода(job);
        const d = job.el && job.el.querySelector('[data-act-stage]');
        if (d) d.textContent = job.текстЭтапа;
      } catch (_e) { /* экран — не главное */ }
    }
    function тостХода(job) {
      return хост.тост({ kind: 'info', low: true, label: 'Действие по заявке', title: job.title + ' · № ' + job.id,
        lines: [h('div', { class: 'tst-d', 'data-act-stage': '1' }, job.текстЭтапа || '')], actions: [] });
    }
    async function исполнить(з) {
      const cr = з.cr || {}, имя = 'lcz-act-' + cr.dir + '-' + cr.id;
      // второй щелчок / подсказка по той же заявке в этой вкладке — сразу, без ожидания
      if (ИДУТ.has(имя)) return { ok: false, состояние: 'занято', text: ОШИБКИ.занято(cr.id) };
      const пока = { этап: 'prep' };
      ИДУТ.set(имя, пока);
      обновитьУход();
      try {
        return await подЗамком(имя, async (взят) => {
          if (!взят) return { ok: false, состояние: 'занято', text: ОШИБКИ.занято(cr.id) };
          let job = з.job;
          if (!job) { const s = await собрать(з); if (s.ошибка) return { ok: false, состояние: 'отказ', text: s.ошибка }; job = s.job; }
          ИДУТ.set(имя, job);
          const итог = await ход(job);
          итог.after = итог.после || null;                               // подсказкам (watch-act): карточка после действия
          // сделанное — подсказкам: напоминания «Не отвечает», «заявка за вами», снять бейдж…
          if (итог.ok || job.crmDone) сообщить({ conv: job.conv, cr: job.cr, dir: job.dir, id: job.id, key: job.act, ввод: job.ввод || {}, ok: !!итог.ok, состояние: итог.состояние,
            after: итог.после || null, план: job.план || null, источник: job.источник });
          return показатьИтог(job, итог);
        });
      } finally {
        const j = ИДУТ.get(имя);
        if (j && j.el) { j.el.remove(); j.el = null; }
        ИДУТ.delete(имя);
        обновитьУход();
      }
    }
    async function ход(job) {
      const строки = [];
      // 2. журнал: тот же ключ недавно сделан или «не знаю, прошло ли» — ничего не делаем
      const повтор = await повторЛи(job);
      if (повтор) return { ok: false, ...повтор, строки: [повтор.text], виды: ['warn'] };
      const tg = job.tg;
      // 2б. действие только в чат (CRM не трогаем): текст и статус — из снимка, на который смотрел оператор. Перед отправкой —
      // свежая карточка CRM: заявку закрыли / перенесли / сменили статус — «устарело», в чат ничего (номер клиента «по сд» и т.п.)
      if (!job.steps.length && tg && tg.on && job.snap && job.sig0) {
        этап(job, 'prep');
        const св = await снимок(job.cr, true);
        if (!св.ok) return { ok: false, состояние: 'отказ', text: 'Карточка CRM не прочиталась (' + String(св.error || '').slice(0, 80) + ') — не проверить, не изменилась ли заявка. В чат ничего не отправлено, нажмите ещё раз.' };
        if (св.card.sig && св.card.sig !== job.sig0) {
          const d = разница(job.snap, св.card), text = ОШИБКИ.устарело(d.было, d.стало);
          return { ok: false, состояние: 'устарело', после: св.card, text, строки: [text], виды: ['warn'] };
        }
      }
      // 3. защита от перекрытия: в чат города (не ответом) — сначала его последние сообщения. До любой записи в CRM
      // программа Telegram не ответила даже списком групп — чат не проверить: тоже ничего не делаем, выбор за оператором
      // 2.1.3: не проверить (программа Telegram не ответила, групп нет) — больше не «ничего не делали»: CRM (отмена, перенос…) делаем,
      // а сообщение в чат придерживаем — в итоге «Всё равно отправить» / «Отправить ещё раз». Раньше без программы Telegram
      // не отменялась ни одна заявка. Ждёт ответа просьба филиала — как раньше, ничего не делаем
      if (tg && tg.on && !tg.chat && tg.тгНет && tg.kind === 'city' && !tg.reply && !job.force) job.tgНеПроверен = true;
      if (tg && tg.on && tg.chat && tg.kind === 'city' && !tg.reply && !job.force) {
        этап(job, 'guard');
        const g = await хост.просьбыВЧате(tg.chat, { заранее: true });
        if (g === null || g === undefined) job.tgНеПроверен = true;
        else if (g.length) return { ok: false, состояние: 'перекрытие', guard: { list: g, title: tg.title }, text: ОШИБКИ.перекрытие(tg.title || 'чат города', LC_TG.просьбаКратко(g[g.length - 1])) };
      }
      // 4. заявка открыта во вкладке CRM — её «Сохранить» вернёт старое; не мешает, только скажем
      const вкладка = job.steps.length ? сроком(send({ kind: 'lcz-act-tabs', args: { dir: job.dir, id: job.id } }), 3000).catch(() => null) : Promise.resolve(null);
      // счётчики карточки ДО действия (числа, без слов клиента): «Проверить» после закрытой вкладки сверяет «+1» с ними, а не со
      // снимком нового нажатия (в нём отметка уже может стоять)
      const до = job.snap ? Object.fromEntries(['noAnswerCount', 'changesCount'].filter((k) => job.snap[k] != null && Number.isFinite(Number(job.snap[k]))).map((k) => [k, Number(job.snap[k])])) : null;
      if (job.steps.length) await записать(job, { state: 'run', crmDone: false, шаг: job.сШага, ...(до && Object.keys(до).length ? { до } : {}) });
      // 5–7. CRM: шаг за шагом, следующий — с подписью карточки после предыдущего; без авто-повтора записи
      let sig = job.sig0, lastChange = '', после = null, crmТекст = [], вЖурнал = [];
      const результаты = [];
      for (let i = job.сШага; i < job.steps.length; i++) {
        const s = job.steps[i];
        // составное действие: в журнале — шаг, который сейчас идёт (вкладку закроют — «Проверить» сверит именно его)
        if (i > job.сШага) await записать(job, { state: 'run', crmDone: !!job.crmDone, шаг: i });
        этап(job, 'crm', i);
        // продолжение с шага, где CRM упёрлась: причина (второй клик) и/или выбор оператора для пустых обязательных полей (2.2.5)
        const доп0 = i === job.сШага ? { ...(job.причина != null ? { status_change_type: job.причина } : {}), ...(job.заполнить ? { заполнить: job.заполнить } : {}) } : {};
        const доп = Object.keys(доп0).length ? доп0 : null;
        let r;
        try { r = await сроком(s.run(sig, доп, i === job.сШага ? (после || job.snap) : после), 150e3, 'нет ответа 2 минуты'); } catch (e) { r = { ok: false, error: String((e && e.message) || e) }; }
        r = r && typeof r === 'object' ? r : { ok: false, unknown: true, error: 'нет ответа' };
        if (!r.ok && !r.stale && !r.needReason && обрыв(r.error)) r = { ...r, unknown: true };
        const сделано = crmТекст.slice();
        const видыДо = (последний) => [...сделано.map(видТекста), последний];
        if (r.busy) {
          // ядро CRM держит замок заявки (другая вкладка / подсказка): ничего не отправлено
          if (!job.crmDone) await записать(job, { state: 'занято', crmDone: false, итог: 'ничего не сделано: занято' });
          const t = r.error || ОШИБКИ.занято(job.id);
          return { ok: false, состояние: job.crmDone ? 'частично' : 'занято', text: [...сделано, t].join(' · '), строки: [...сделано, t], виды: видыДо('warn') };
        }
        if (r.unknown) {
          job.шагНеясно = i;
          await записать(job, { state: 'неясно', crmDone: job.crmDone || false, шаг: i, итог: 'CRM не ответила' });
          const t = r.error && !обрыв(r.error) && /не знаю|прошло ли|проверьте/i.test(r.error) ? r.error : ОШИБКИ.нетОтвета;
          return { ok: false, состояние: 'неясно', text: [...сделано, t].join(' · '), строки: [...сделано, t], виды: видыДо('warn'), проверить: true, шаг: i };
        }
        if (r.stale) {
          if (r.after) { после = r.after; запомнитьСнимок(job.cr, r.after); }
          const d = разница(job.snap, r.after);
          await записать(job, { state: i ? 'частично' : 'устарело', crmDone: !!job.crmDone, итог: i ? 'остановлено: заявка изменилась' : 'ничего не сделано' });
          // карточка клиента (PE, custAct) изменилась — у ядра свой точный текст («адрес был …, стал …»); заявка — по снимкам
          const text = s.op !== 'act' && r.error ? String(r.error) : ОШИБКИ.устарело(d.было, d.стало);
          return { ok: false, состояние: 'устарело', после: r.after || null, text: i ? сделано.join(' · ') + ' · дальше не делал: ' + text : text, строки: [...сделано, text], виды: видыДо('warn') };
        }
        if (r.needReason) {
          const варианты = (r.options || []).map((o) => (typeof o === 'object' ? o.text || o.title || o.value : String(o))).join(', ');
          await записать(job, { state: 'причина', crmDone: !!job.crmDone, шаг: i, итог: 'CRM просит причину' + (r.crmReply ? '; ответ CRM: ' + r.crmReply : '') });
          // 2.2.9: CRM просит ещё и пустые обязательные поля — их выбор вместе с причиной (ядро отдало варианты)
          const поля = поляДляВыбора(r);
          const t = String(r.error || '').trim() || ОШИБКИ.причина(варианты || '—');
          return { ok: false, состояние: 'причина', шаг: i, options: r.options || [], после: r.after || null, text: t, строки: [...сделано, t], виды: видыДо('warn'),
            ...(поля ? { поля, выбрано: { ...(job.заполнить || {}) } } : {}) };
        }
        if (!r.ok) {
          if (r.after) запомнитьСнимок(job.cr, r.after);
          const t = текстОшибки(job, s, r);
          // в журнал — не текст отказа: в нём бывают слова карточки клиента (имя, адрес) и ошибки формы CRM. 2.2.9: зато — что ответила CRM
          // (ядро отдаёт её ответ уже без личного: код, страница, ошибки у полей, красные надписи; телефоны — ещё раз маской)
          const кодОтказа = String(r.code || r.kind || '').replace(/[^\wа-яё ]/gi, '').slice(0, 30);
          const ответ = r.crmReply ? маска(String(r.crmReply)).slice(0, 300) : '';
          await записать(job, { state: job.crmDone ? 'частично' : 'отказ', crmDone: !!job.crmDone,
            итог: (job.crmDone && вЖурнал.length ? вЖурнал.join(', ') + '; дальше — ' : '') + 'отказ CRM' + (кодОтказа ? ' (' + кодОтказа + ')' : '') + (ответ ? '; ответ CRM: ' + ответ : ''),
            ...(ответ ? { ответCRM: ответ } : {}) });
          const held = ((r.after || после || job.snap || {}).held || {}).mine;
          // 2.2.5: CRM не сохранит — пусты обязательные поля, ядро дало их варианты: выбор прямо в итоге («Заполнить и повторить»,
          // с этого же шага); прежний выбор (заполнено одно из двух) — тоже в повтор. Строка отказа на экране — с подсказкой (строкиПоказа)
          const поля = поляДляВыбора(r);
          const выбор = поля ? { поля, шаг: i, пустоСтрока: /^(пусто|required)$/.test(String(r.code || '')) ? сделано.length : -1, выбрано: { ...(job.заполнить || {}) } } : {};
          // 2.2.9: что ответила CRM — отдельной строкой итога (её можно показать / прислать: «по какой причине не сделалось»)
          const строкиОтказа = [...сделано, t, ...(ответ ? ['Ответ CRM: ' + ответ] : [])];
          return { ok: false, состояние: job.crmDone ? 'частично' : 'отказ', text: строкиОтказа.join(' · '), строки: строкиОтказа, виды: [...видыДо('bad'), ...(ответ ? ['mut'] : [])], после: r.after || после || null, сессия: сессияЛи(r), ...выбор, ...(ответ ? { ответCRM: ответ } : {}),
            // «Сохранить» в модерации оставил «Модерацию» (V3) — вариант CRM «Отправить в город» отдельной карточкой
            fallback: (job.план && job.план.fallback) || '',
            // прозвон / модерация: шаг упал, а заявка всё ещё за оператором — «Вернуть заявку» отдельной кнопкой
            вернуть: !!held && !/release$/.test(job.act) };
        }
        if (!r.already) job.crmDone = true;
        результаты.push(r);
        if (r.after) { после = r.after; sig = r.after.sig || sig; запомнитьСнимок(job.cr, r.after); }
        if (r.lastChange) lastChange = r.lastChange;
        if (r.newRequest && r.newRequest.id) job.новая = r.newRequest;     // перевод в другую базу: ядро нашло новую заявку
        const t = s.итог ? s.итог(r) : s.title;
        crmТекст.push(...[].concat(t || []).filter(Boolean));
        // 2.2.5: что ядро подставило перед сохранением («Дальний выезд был пустой — поставил «Нет»», выбор оператора) — строкой итога и в заметку
        if (Array.isArray(r.заметки)) дописатьСтроки(crmТекст, r.заметки, '');
        // 2.2.9: предупреждения ядра («комментарий не записался — впишите в CRM», «CRM показала ошибку, но в карточке всё на месте») — тоже
        // строками итога (раньше терялись); знак «⚠» — жёлтая строка
        // (перевод в другую базу — своя строка ниже, «новую заявку найдите вручную»; «Ответ CRM» — только при неудаче)
        if (Array.isArray(r.warnings)) дописатьСтроки(crmТекст, r.warnings.filter((x) => !/^(Ответ CRM:|перевод отправлен)/.test(String(x || ''))), '⚠ ');
        // в журнал (хранится 7 дней) — без адреса клиента: шаг может дать свою короткую строку
        вЖурнал.push(...[].concat((s.журнал ? s.журнал(r) : t) || []).filter(Boolean));
      }
      строки.push(...crmТекст);
      const виды = crmТекст.map(видТекста);
      let tgСтрока = -1;
      if (job.steps.length) await записать(job, { state: 'run', crmDone: !!job.crmDone, шаг: job.steps.length });
      if (job.послеCRM) { try { await job.послеCRM({ lastChange, после, строки: crmТекст }); } catch (_e) { /* запись в память — не главное */ } }
      // 8. Telegram — только когда все шаги CRM проверены (или их нет)
      let tgИтог = null;
      if (tg && tg.on) {
        let text = typeof tg.text === 'function' ? tg.text({ lastChange, после, результаты }) : String(tg.text || '');
        if (typeof tg.text !== 'function') {
          // в чат — точная строка «Переносов», которую дописала CRM (как «Скопировать перенос» Чатерского), а не строка по снимку
          if (tg.изCRM && lastChange) {
            let x = '';
            if (есть() && typeof LC_ACT.текстПослеCRM === 'function' && job.план && job.план.tg && job.план.tg.послеCRM) { try { x = LC_ACT.текстПослеCRM(job.план, результаты) || ''; } catch (_e) { x = ''; } }
            text = x || (job.id + ' ' + String(lastChange).trim() + (tg.suffix || '')).trim();
          }
          text = text.replace(/\{(?:lastChange|перенос)\}/g, lastChange || '…');
        }
        text = String(text || '').trim();
        if (!text) { строки.push(tg.пусто || 'в чат не писали: нет текста'); виды.push('mut'); }
        else if (!tg.chat && tg.тгНет) { tgИтог = { ok: false, нетЧата: true, text, error: 'программа Telegram не на связи' }; tgСтрока = строки.length; виды.push('warn');
          // 2.1.3: программа Telegram на ПК не на связи (даже группы не получены) — CRM сделано, в чат напишите сами
          строки.push('В чат города не отправлено: программа Telegram на ПК не на связи. ' + (job.steps.length ? 'В CRM — сделано. ' : '') + 'Напишите в чат сами: «' + text + '»'); }
        else if (!tg.chat) { tgИтог = { ok: false, нетЧата: true, text, error: tg.нет || 'чат не найден' }; tgСтрока = строки.length; виды.push('bad'); строки.push(tg.kind === 'city' ? ОШИБКИ.нетЧата(tg.город || '?', text) : 'В Telegram не отправлено: ' + (tg.нет || 'чат не найден') + ' — напишите вручную: «' + text + '»'); }
        else {
          этап(job, 'tg');
          // действие только в чат: «начато» — до отправки (вкладку закроют посреди — второе нажатие не отправит дважды)
          // в журнал — не текст (в нём слова клиента), а его отпечаток: «Проверить» сверит с сообщениями чата
          if (!job.steps.length) { job.tgТекст = text; await записать(job, { state: 'run', crmDone: false, tgOnly: true, tgХэш: отпечатокЧата(text) }); }
          tgИтог = await отправитьTG(job, text);
          tgСтрока = строки.length; виды.push(tgИтог.ok ? 'ok' : tgИтог.unknown || tgИтог.неПроверен || tgИтог.перекрытие ? 'warn' : 'bad');
          // 2.1.3: чат не проверить (старая программа Telegram не ответила) — CRM сделано, сообщение придержали: «Отправить ещё раз» проверит и отправит
          строки.push(tgИтог.ok ? 'в «' + (tg.title || 'чат') + '»: ' + text : tgИтог.неПроверен ? 'В «' + (tg.title || 'чат города') + '» пока не отправил: не смог проверить его на просьбы филиала (программа Telegram на ПК не ответила). '
            + (job.steps.length ? 'В CRM — сделано. ' : '') + '«Отправить ещё раз» проверит чат и отправит, или напишите сами: «' + text + '»' : tgИтог.unknown ? 'В «' + (tg.title || 'чат') + '» Telegram не ответил ' + (/за 90 с/.test(tgИтог.error) ? 'за 90 с' : 'вовремя') + ' — не знаю, ушло ли. Текст: «' + text + '»'
            : (job.steps.length ? ОШИБКИ.tgПослеCRM(crmТекст.join(', ') || 'всё', tg.title || 'чат', tgИтог.error, text) : 'В «' + (tg.title || 'чат') + '» не отправилось: ' + tgИтог.error + '. Текст: «' + text + '»'));
        }
      }
      // 9. LeadChat: заметка, № в имени, сообщение клиенту — client_message_id от ключа: повтор не даст второго
      этап(job, 'lc');
      const lc = await вLeadChat(job, crmТекст, tgИтог);
      const заметкаСтрока = lc.заметкаНе >= 0 ? строки.length + lc.заметкаНе : -1;
      строки.push(...lc.строки); виды.push(...lc.виды);
      // 4 (итог): вкладка CRM с этой заявкой
      const вк = await вкладка;
      if (вк && вк.ok && (вк.open > 0 || вк.open === true || (вк.tabs || []).length)) { строки.push('⚠ Заявка № ' + job.id + ' открыта во вкладке CRM — обновите ту вкладку (F5), иначе её «Сохранить» вернёт старое'); виды.push('warn'); }
      const всё = !tgИтог || tgИтог.ok;
      job.crmТекст = crmТекст;
      const итог = { ok: всё && !lc.плохо, состояние: всё ? 'ok' : 'частично', text: строки.join(' · '), строки, виды, tgСтрока, заметкаСтрока, tg: tgИтог, после };
      // 10. журнал: итог (без комментариев и с маской телефонов). Действие только в чат (CRM не трогали): явная ошибка Telegram —
      // ничего не сделано, нажать ещё раз можно («уже сделано» было бы неправдой); ответа нет — «не знаю, ушло ли» (сначала «Проверить»)
      const толькоЧат = !job.steps.length && !!tgИтог && !tgИтог.ok;
      await записать(job, { state: всё ? 'ok' : толькоЧат ? (tgИтог.unknown ? 'неясно' : 'нет') : 'частично', crmDone: !!job.crmDone, итог: (вЖурнал.join(', ') || (tgИтог && tgИтог.ok ? 'отправлено в чат' : '')) + (всё ? '' : '; в чат не ушло'),
        // счётчик «Не отвечает» после действия: следующее нажатие по карточке, где он уже такой, — новый звонок (сделанноеОтменено)
        ...(после && после.noAnswerCount != null ? { счётПосле: Number(после.noAnswerCount) } : {}) });
      return итог;
    }
    /* текст отказа CRM: ядро (crmact) отдаёт готовый текст по таблице раздела 6 — показываем его; нет текста — по коду */
    function текстОшибки(job, s, r) {
      const код = String(r.code || r.kind || '');
      const e = String(r.error || '').trim();
      const вЧат = (t) => (job.tg && job.tg.on && !/в чат|ничего не (с|д)дела|ничего больше не делаю/i.test(t) ? t.replace(/\s*$/, '') + (/[.!]$/.test(t.trim()) ? '' : '.') + ' В чат не писали.' : t);
      if (s.ошибка) return s.ошибка(r) + (job.tg && job.tg.on && !/в чат/i.test(s.ошибка(r)) ? ' — в чат не писали' : '');
      if (код === 'session' || код === 'сессия' || (!e && /сесси/i.test(код))) return e && /Ничего не сделано/.test(e) ? e : ОШИБКИ.сессия(база(job.dir));
      if (/сесси|войдите в|страница входа/i.test(e)) return /Ничего не сделано/.test(e) ? e : ОШИБКИ.сессия(база(job.dir));
      if (код === 'noButton' || код === 'нет кнопки') return e || ОШИБКИ.нетКнопки(job.id, r.button || s.title, (job.snap && job.snap.statusName) || '—');
      if (код === 'notVerified' || код === 'не сделано' || код === 'не проверилось') return вЧат(e || ОШИБКИ.непроверено((r.after && r.after.statusName) || '—'));
      if (код === 'required' || код === 'пусто') return e || ОШИБКИ.пусто;
      if ((r.errors || []).length && (!e || код === 'form' || код === 'форма')) return ОШИБКИ.отказ((r.errors || []).slice(0, 2).join('; '));
      if (код === 'form' || код === 'форма') return вЧат(e || ОШИБКИ.отказ('ошибка формы'));
      if (код === 'unexpected' || код === 'неожиданно') return e && /Ничего больше не делаю/.test(e) ? e : ОШИБКИ.неожиданно(e.slice(0, 80) || 'непонятный ответ');
      return вЧат(e || 'CRM не сохранила');
    }
    async function отправитьTG(job, text, всёРавно) {
      const tg = job.tg;
      // 2.1.3: в чат города не ответом — программа ещё раз смотрит чат в том же задании (между проверкой до CRM и отправкой мог написать филиал)
      const сПроверкой = !всёРавно && !job.force && tg.kind === 'city' && !tg.reply;
      const простая = () => send({ kind: 'lcz-tg', args: { action: 'send', chat: tg.chat, reply_to: tg.reply || undefined, text, conv: job.conv } });
      // хост без «проверить и отправить» — проверка отдельно, как раньше (не проверить — не отправляем)
      const поСтарому = async () => { const g = await хост.просьбыВЧате(tg.chat);
        return g && g.length ? { ok: false, guard: g } : g == null ? { ok: false, неПроверен: true, error: 'не смог проверить чат на просьбы филиала (программа Telegram не ответила)' } : простая(); };
      const r = await сроком(!сПроверкой ? простая() : typeof хост.отправитьСПроверкой === 'function' ? хост.отправитьСПроверкой({ chat: tg.chat, text, conv: job.conv }, { строго: true })
        : typeof хост.просьбыВЧате === 'function' ? поСтарому() : простая(), 90e3, 'Telegram не ответил за 90 с');
      if (r && Array.isArray(r.guard) && r.guard.length) return { ok: false, перекрытие: true, guard: r.guard, text, error: 'ждёт ответа просьба филиала — ' + LC_TG.просьбаКратко(r.guard[r.guard.length - 1]) };
      if (r && r.неПроверен) return { ok: false, неПроверен: true, text, error: r.error };
      if (r && r.ok) { try { await tg.послеОтправки(r); } catch (_e) { /* не критично */ } return { ok: true, text, msg: r.message_id }; }
      // нет ясного ответа (свой срок, фон пометил unknown: срок мозга, связь, шлюз, «не ответил вовремя»; порт к фону оборвался) —
      // могло и уйти: «не знаю, ушло ли» и «Проверить чат», а не «Отправить ещё раз»
      const e = String((r && (r.error || r.description)) || 'ошибка');
      return { ok: false, unknown: !!(r && (r.timeout || r.unknown)) || !r || обрыв(e), text, error: e };
    }
    // деталь — тихим чтением (?peek=true, LeadChat 12.10): фоновое действие не гасит оператору «⚑ передан вам»
    async function клиентДиалога(job) {
      if (job.client && job.client.id) return job.client;
      try { const c = await хост.LC.get('/conversations/' + encodeURIComponent(job.conv) + '?peek=true'); return c && c.client ? { id: String(c.client.id || ''), name: c.client.name || '' } : null; } catch (_e) { return null; }
    }
    async function настройки() { try { return (await store.get('actCfg', {})) || {}; } catch (_e) { return {}; } }
    /* диалог — к этой заявке (возврат в «Ожидает», «На уточнении» → «Ожидает», новая заявка после перевода): дальше расширение
       следит за сообщениями клиента по ней, как после создания */
    async function связатьДиалог(conv, ref, city) {
      if (!conv || !ref || !ref.id) return;
      try {
        await правитьCreated((all) => {
          const was = all[conv] || {};
          if (String(was.id) === String(ref.id) && was.dir === ref.dir) return false;
          all[conv] = { id: String(ref.id), dir: ref.dir, url: ref.url || '', at: Date.now(), city: city || was.city || '', linked: true };
        });
      } catch (_e) { /* не критично: № в имени уже связывает */ }
    }
    async function вLeadChat(job, crmТекст, tgИтог) {
      // виды — цвет каждой строки итога; заметкаНе — номер строки «заметка не записалась» (у неё своя «повторить»)
      const out = { строки: [], виды: [], плохо: false, заметкаНе: -1 };
      const строка = (t, вид) => { out.строки.push(t); out.виды.push(вид); };
      if (!job.conv) return out;
      const cfg = await настройки();
      const LC = хост.LC;
      // заметка: «№<ID> · <действие> · <итог CRM> · чат «<название>»: «<текст>»» — телефоны замаскированы; id от ключа: повтор не даст второй
      // («Сделать ещё раз» после «уже сделано» — новое нажатие оператора: id с меткой повтора, иначе LeadChat счёл бы его тем же).
      // 409 idempotency_mismatch — заметка с этим id уже есть (текст итога с тех пор другой): записана раньше, не ошибка
      if (job.lc.note && cfg.notes !== false) {
        const что = String(job.lc.noteText || '').replace(/^№\s*\d+\s*·\s*/, '').trim() || job.title;
        const заметка = маска(['№' + job.id, что, crmТекст.join(', ') || (job.steps.length ? '' : 'CRM не трогали'),
          tgИтог && tgИтог.ok ? 'чат «' + (job.tg.title || '') + '»: «' + tgИтог.text + '»' : tgИтог ? 'в чат не ушло' : ''].filter(Boolean).join(' · ')).slice(0, 900);
        try { await LC.post('/conversations/' + encodeURIComponent(job.conv) + '/notes', { text: заметка, client_message_id: idLC(job, 'lcz-act-') }); }
        catch (e) {
          if (ужеЗаписано(e)) out.заметкаУже = true;
          else { out.заметкаНе = out.строки.length; строка('заметка в LeadChat не записалась', 'warn'); }
        }
      }
      // № в имени клиента: возвращённая / привязанная заявка; 'new' — новая заявка после перевода в другую базу (если ядро её нашло)
      const ref = job.lc.name === 'new' ? job.новая : job.lc.name ? { dir: job.dir, id: job.id, url: (job.snap && job.snap.url) || job.cr.url || '' } : null;
      if (job.lc.name === 'new' && !job.новая && job.crmDone) строка('перевод отправлен — новую заявку в другой базе найдите вручную', 'warn');
      if (job.lc.name === 'new' && job.новая && job.новая.id) строка('новая заявка: № ' + job.новая.id + (база(job.новая.dir) ? ' (' + база(job.новая.dir) + ')' : '') + ' — подсказки по новым сообщениям клиента теперь по ней', 'ok');
      if (ref && ref.id && job.crmDone !== false) {
        if (!job.послеCRM) await связатьДиалог(job.conv, ref, job.cr.city);
        // 12.10: № заявки — и в сам диалог LeadChat (crm_request_id), параллельно с именем; LeadChat старше (ручки нет) — молча
        const вДиалогP = typeof хост.номерВДиалог === 'function' ? хост.номерВДиалог(job.conv, ref.id).catch(() => null) : null;
        const cl = await клиентДиалога(job);
        if (cl && cl.id) {
          const want = хост.nameWithId(cl.name || '', ref.id);
          try { if (want !== String(cl.name || '').trim()) await LC.put('/clients/' + encodeURIComponent(cl.id) + '/name', { name: want }); строка('имя в LeadChat: «' + want + '»', 'ok'); }
          catch (_e) { out.плохо = true; строка('номер к имени в LeadChat не дописался — впишите «' + want + '» вручную', 'warn'); }
        }
        // не записалось — видно, но действие не «плохо»: № в имени уже есть. Тот же № у других диалогов — не молчим (дубль?)
        const вДиалоге = вДиалогP ? await вДиалогP : null;
        if (вДиалоге && вДиалоге.ok) строка('в LeadChat: номер заявки записан в диалог', 'ok');
        else if (вДиалоге) строка('в LeadChat номер заявки в диалог не записался: ' + String(вДиалоге.error || 'ошибка').slice(0, 120), 'warn');
        if (вДиалоге && (вДиалоге.twins || []).length) строка('этот номер уже стоит у других диалогов LeadChat: ' + вДиалоге.twins.slice(0, 5).map((x) => '/chats/' + x).join(', '), 'warn');
      }
      // клиенту — только по галочке оператора в превью (по умолчанию выключена, решение В7)
      // id — от ключа и метки повтора (как у заметки). LeadChat узнал id (200 + X-Idempotent-Replay) — вернул сообщение, отправленное
      // раньше: нового клиенту нет, так и говорим; тот же id с другим текстом (409 idempotency_mismatch) — тоже уже отправлено раньше
      if (job.lc.client && job.lc.client.on && job.lc.client.text) {
        const path = '/conversations/' + encodeURIComponent(job.conv) + '/messages', тело = { text: job.lc.client.text, client_message_id: idLC(job, 'lcz-act-c-') };
        try {
          const r = typeof LC.postFull === 'function' ? await LC.postFull(path, тело) : { data: await LC.post(path, тело), replay: false };
          if (r && r.replay) строка('клиенту это сообщение уже было отправлено раньше — второй раз не отправлял', 'warn');
          else строка('клиенту отправлено', 'ok');
        } catch (e) {
          if (ужеЗаписано(e)) строка('клиенту по этому действию уже писали раньше (другим текстом) — второй раз не отправлял', 'warn');
          else { out.плохо = true; строка('клиенту не отправилось: ' + String((e && e.message) || e).slice(0, 80), 'warn'); }
        }
      }
      return out;
    }
    // итог: смотрит на действие — рисует его экран; ушёл — уведомлением (как p11)
    function показатьИтог(job, итог) {
      job.итог = итог;
      if (job.el) { job.el.remove(); job.el = null; }
      const видно = job.наВиду ? job.наВиду() : true;
      // ушёл из карточки — итог уведомлением; «ждёт просьба филиала» тоже: иначе оператор не узнает, что ничего не сделано
      if (!видно && !job.тихо && !/^(занято|уже)$/.test(итог.состояние)) тостИтога(job, итог);
      // 2.2.9: карточка «по заявке» (кнопкиТостом) своих кнопок итога не рисует — CRM просит выбрать пустые поля: выбор и «Заполнить и
      // повторить» — уведомлением (иначе отмена из неё упиралась бы в «заполните в CRM»)
      else if ((!видно || job.кнопкиТостом) && (итог.состояние === 'неясно' || (job.кнопкиТостом && Array.isArray(итог.поля) && итог.поля.length))) тостИтога(job, итог);
      return итог;
    }
    /* ---------- итог (проект «Отмена» / «Уведомления»): каждая строка — своим цветом и знаком справа (✓ сделано, ! проверьте, ✗ не вышло),
       у строки чата — её кнопки, у «заметка не записалась» — «повторить»; внизу одна главная кнопка (следующий шаг), остальные — тихие ---------- */
    /* ---------- 2.2.5 «Заполнить и повторить» (жалоба 13.10: «В карточке не заполнено «Дальний выезд» — Заполните в CRM») ----------
       Ядро CRM (crmact) не сохранило: пусты обязательные поля карточки — и отдало их с вариантами формы CRM (поля). Выбор — прямо
       в итоге (карточка действия и уведомление); пишем только по нажатию оператора: то же задание с шага, где CRM упёрлась, с
       заполнить {имя поля: значение} — ядро подставит ТОЛЬКО в пустые обязательные поля и проверит вариант. «Открыть в CRM» — как было */
    // поля из ответа ядра; хоть одно не заполнить отсюда (список без вариантов, слишком много) — выбора не даём, только «Открыть в CRM»
    function поляДляВыбора(r) {
      const a = r && Array.isArray(r.поля) ? r.поля : [];
      if (!a.length || a.length > 8) return null;
      const out = [];
      for (const f of a) {
        if (!f || typeof f.name !== 'string' || !f.name) return null;
        const label = String(f.label || f.name).replace(/\s+/g, ' ').trim().slice(0, 80);
        if (f.kind !== 'select') { out.push({ name: f.name, label, kind: 'text' }); continue; }
        const options = (Array.isArray(f.options) ? f.options : []).filter((o) => o && o.value != null && String(o.value) !== '')
          .map((o) => ({ value: String(o.value), text: String(o.text == null ? o.value : o.text).replace(/\s+/g, ' ').trim().slice(0, 120) }));
        if (!options.length) return null;
        out.push({ name: f.name, label, kind: 'select', options });
      }
      return out;
    }
    // строки итога для показа: отказ «пусто» с выбором — подсказкой «выберите и нажмите «Заполнить и повторить» (или заполните в CRM)»
    const строкиПоказа = (итог) => (итог.строки || [итог.text]).map((t, i) => (итог.поля && i === итог.пустоСтрока ? ОШИБКИ.пустоВыбор(итог.поля.map((f) => f.label)) : t));
    /* выбор для каждого поля (список — варианты CRM, текст — поле ввода) и кнопка «Заполнить и повторить» (активна, когда выбрано всё).
       Выбранное живёт в самом итоге (итог.выбор): перерисовка карточки его не теряет */
    function выборПолей(итог, пуск) {
      const выбор = итог.выбор || (итог.выбор = {});
      const готово = () => итог.поля.every((f) => String(выбор[f.name] == null ? '' : выбор[f.name]).trim());
      const кнопка = h('button', { class: 'sm', 'data-ac-act': 'fill', disabled: true, title: 'Сначала выберите', onclick: (e) => {
        const b = e.currentTarget;
        if (b.disabled || !готово()) return;
        b.disabled = true; b.textContent = 'Заполняю…';
        const сейчас = {};
        for (const f of итог.поля) сейчас[f.name] = String(выбор[f.name]).trim();
        пуск({ ...(итог.выбрано || {}), ...сейчас }, b);
      } }, 'Заполнить и повторить');
      const обновить = () => { кнопка.disabled = !готово(); кнопка.title = кнопка.disabled ? 'Сначала выберите' : ''; };
      const блок = h('div', { class: 'ac-fill', 'data-ac': 'fill' }, ...итог.поля.map((f) => {
        const v = выбор[f.name] == null ? '' : String(выбор[f.name]);
        return h('label', { class: 'f' }, h('span', { class: 'lb' }, f.label),
          f.kind === 'select'
            ? h('select', { 'data-ac-fill': f.name, 'aria-label': f.label, onchange: (e) => { выбор[f.name] = e.target.value; обновить(); } },
              h('option', { value: '' }, '— выберите —'), ...f.options.map((o) => h('option', { value: o.value, selected: v === o.value }, o.text)))
            : h('input', { type: 'text', 'data-ac-fill': f.name, 'aria-label': f.label, maxlength: '200', value: v, oninput: (e) => { выбор[f.name] = e.target.value; обновить(); } }));
      }));
      обновить();
      return { блок, кнопка };
    }
    /* «Заполнить и повторить» в уведомлении (оператор ушёл из карточки): то же задание с шага отказа — копией задания (ход и итог —
       уведомлениями, карточку действия не трогаем). Журнал: прошлое — «отказ», это новое нажатие оператора (заметка — с меткой повтора) */
    async function повторитьСЗаполнением(job, итог, заполнить, el) {
      if (el) el.remove();
      const j = { ...job, сШага: итог.шаг || 0, заполнить, причина: null, проверено: true, повтор: false, повторМетка: 0, el: null, итог: null, шагНеясно: null,
        sig0: (итог.после && итог.после.sig) || job.sig0, наВиду: () => false, тихо: false, нарисовать: null };
      const r = await исполнить({ cr: j.cr, job: j });
      // «занято» / «уже» показатьИтог уведомлением не рисует (их видно в карточке) — здесь карточки нет
      if (r && /^(занято|уже)$/.test(r.состояние)) тостИтога(j, r);
      return r;
    }
    function видыИтога(итог) {
      const строки = итог.строки || [итог.text];
      const общий = итог.ok ? 'ok' : итог.состояние === 'отказ' ? 'bad' : 'warn';
      return строки.map((t, i) => (итог.виды && итог.виды[i]) || (/^\s*⚠/.test(String(t || '')) ? 'warn' : общий));
    }
    function строкаИтога(t, вид, действия, вТосте) {
      const мк = /^\s*⚠/.test(String(t || '')) ? '' : ВИД_СТРОКИ[вид] || '';
      return h('div', { class: (вТосте ? 'tst-d ' : '') + 'ln ac-ln ' + вид, 'data-kind': вид },
        h('span', { class: 'tx' }, t), действия && действия.length ? h('span', { class: 'ln-a' }, ...действия) : '', мк ? h('span', { class: 'mk', 'aria-hidden': 'true' }, мк) : '');
    }
    // следующий шаг после сделанного: отмена — «Вернуть в работу» (если CRM даёт), план предложил следующее действие (адрес за чертой — «Дальний выезд»)
    function следующийШаг(job, итог) {
      if (!итог.ok || итог.безСледующего) return null;
      const п = job.план && job.план.follow;
      if (п && п.key && каталог(п.key)) return { key: п.key, ввод: п.ввод || {}, почему: п.почему || '', label: (каталог(п.key) || {}).label || п.key };
      if (/^cancel_(kc|branch)$/.test(job.act) && каталог('back_to_work') && итог.после) {
        const можно = доступные(итог.после, ctxДля(job.conv, job.cr, 'next', итог.после)).some((x) => x.key === 'back_to_work');
        if (можно) return { key: 'back_to_work', ввод: {}, почему: '', label: (каталог('back_to_work') || {}).label || 'Вернуть в работу' };
      }
      return null;
    }
    /* действия итога: {k, у: 'tg' | 'note' | 'низ', el}. Главная — одна (класс pri): Проверить → Отправить ещё раз → Проверить чат →
       Войти в CRM → запасное действие → Вернуть заявку → следующий шаг */
    // 2.2.5: «Заполнить и повторить» (fill) — главнее всего: без него CRM не сохранит
    const ГЛАВНАЯ = ['fill', 'check', 'tgagain', 'tgcheck', 'login', 'fallback', 'вернуть', 'next'];
    function действияИтога(job, итог, место, кнопкаЗаполнить) {
      const все = [];
      const кн = (k, текст, fn, у) => все.push({ k, у: у || 'низ', el: h('button', { class: 'sm', 'data-ac-act': k, onclick: fn }, текст) });
      const ссылка = (k, href, текст) => все.push({ k, у: 'низ', el: h('a', { class: 'sm ac-crm', 'data-ac-act': k, href, target: '_blank', rel: 'noopener' }, текст) });
      if (кнопкаЗаполнить) все.push({ k: 'fill', у: 'низ', el: кнопкаЗаполнить });
      const уЧата = итог.tgСтрока >= 0 ? 'tg' : 'низ';
      if (итог.tg && !итог.tg.ok) {
        кн('copy', 'Копировать', (e) => копировать(итог.tg.text, e.currentTarget), уЧата);
        // повтор отправки — только при явной ошибке; Telegram не ответил — сначала «Проверить чат»
        if (итог.tg.unknown) кн('tgcheck', 'Проверить чат', (e) => проверитьЧат(job, итог, e.currentTarget, место), уЧата);
        else if (!итог.tg.нетЧата) кн('tgagain', 'Отправить ещё раз', (e) => отправитьЕщё(job, итог, e.currentTarget, место), уЧата);
      }
      if (итог.заметкаСтрока >= 0 && job.conv) кн('note', 'повторить', (e) => повторитьЗаметку(job, итог, e.currentTarget), 'note');
      if (итог.проверить) кн('check', 'Проверить', (e) => проверить(job, e.currentTarget, место, итог.шаг));
      const url = job.cr.url && /^https?:/.test(job.cr.url) ? job.cr.url : (job.snap && job.snap.url) || (итог.после && итог.после.url) || '';
      // сессия CRM истекла — войти на сайт базы; отказ / не всё / заявка изменилась — карточка в CRM всегда под рукой
      if (итог.сессия && САЙТЫ[job.dir]) ссылка('login', САЙТЫ[job.dir] + '/', 'Войти в CRM');
      // новым кликом оператора — отдельная карточка с превью, не продолжение этого задания
      if (итог.fallback && каталог(итог.fallback)) кн('fallback', '«' + каталог(итог.fallback).label + '»', () => карточка(job.conv, job.cr, итог.fallback, {}, { from: 'fallback' }));
      if (итог.вернуть) кн('вернуть', 'Вернуть заявку', () => карточка(job.conv, job.cr, каталог('pz_release') && /^pz_/.test(job.act) ? 'pz_release' : 'release', {}, { from: 'вернуть' }));
      const след = следующийШаг(job, итог);
      if (след) кн('next', след.label, () => карточка(job.conv, job.cr, след.key, след.ввод, { from: 'next', почему: след.почему }));
      if ((итог.проверить || /^(отказ|частично|устарело)$/.test(итог.состояние)) && url && /^https?:/.test(url)) ссылка('crm', url, 'Открыть в CRM');
      const гл = ГЛАВНАЯ.map((k) => все.find((x) => x.k === k)).find(Boolean);
      if (гл) { гл.pri = true; гл.el.className = String(гл.el.className || '') + ' pri'; }
      return все;
    }
    // «повторить» у строки «заметка в LeadChat не записалась»: та же заметка (тот же client_message_id — второй не будет), без имени и клиенту
    async function повторитьЗаметку(job, итог, b) {
      if (!b || b.disabled) return;
      const ln = b.closest('.ac-ln');
      b.disabled = true; b.textContent = 'пишу…';
      let r = null;
      try { r = await вLeadChat({ ...job, lc: { ...job.lc, name: false, client: null } }, job.crmТекст || [], итог.tg || null); } catch (_e) { r = null; }
      if (r && r.заметкаНе < 0) {
        if (ln) { ln.className = ln.className.replace(/\b(warn|bad)\b/, 'ok'); ln.setAttribute('data-kind', 'ok'); const t = ln.querySelector('.tx'); if (t) t.textContent = r.заметкаУже ? 'заметка в LeadChat уже записана' : 'заметка в LeadChat записана'; const m = ln.querySelector('.mk'); if (m) m.textContent = ВИД_СТРОКИ.ok; }
        b.remove();
        return;
      }
      b.disabled = false; b.textContent = 'повторить';
    }
    function тостИтога(job, итог) {
      const место = h('div', { class: 'tst-d' });
      const чужой = !!job.conv && хост.convIdNow() !== job.conv;
      // карточки «Отправить в город» / «Вернуть заявку» / следующий шаг — только в своём диалоге; в чужом — сначала «Открыть диалог»
      const итогК = чужой ? { ...итог, fallback: '', вернуть: false, безСледующего: true } : итог;
      // 2.2.5: пусты обязательные поля — выбор прямо в уведомлении; «Заполнить и повторить» — то же задание с шага отказа
      let el = null;
      const выбор = итог.поля ? выборПолей(итог, (заполнить) => повторитьСЗаполнением(job, итог, заполнить, el)) : null;
      const все = действияИтога(job, итогК, место, выбор && выбор.кнопка);
      if (чужой) все.push({ k: 'dialog', у: 'низ', el: h('button', { class: 'sm', onclick: async () => { if (хост.черновикМешает && хост.черновикМешает(job.conv)) return; if (хост.перейти) await хост.перейти(job.conv); } }, 'Открыть диалог') });
      // одна главная кнопка; остальные — «Ещё (N)» (не восемь кнопок разом)
      let гл = все.find((x) => x.pri);
      if (!гл) { гл = все.find((x) => x.k === 'dialog') || null; if (гл) { гл.pri = true; гл.el.className = String(гл.el.className || '') + ' pri'; } }
      const прочие = все.filter((x) => x !== гл).map((x) => x.el);
      const строки = строкиПоказа(итог), виды = видыИтога(итог);
      // не сделано / не всё — уведомление не вытесняется другими (иначе оператор не узнает, что ничего не сделано)
      el = хост.тост({ kind: итог.ok ? 'ok' : 'warn', label: 'Действие по заявке', keep: !итог.ok,
        title: (итог.ok ? 'Сделано: ' : job.crmDone || итог.состояние === 'частично' ? 'Не всё сделано: ' : 'Не сделано: ') + job.title + ' · № ' + job.id,
        lines: [...строки.map((t, i) => строкаИтога(t, виды[i], null, true)), ...(выбор ? [выбор.блок] : []), место],
        actions: [гл ? гл.el : '', ...(прочие.length <= 1 ? прочие : [h('details', { class: 'ac-tmore' }, h('summary', {}, 'Ещё (' + прочие.length + ')'), h('div', { class: 'ac-tmore-l' }, ...прочие))])] });
      if (итог.ok) setTimeout(() => el.remove(), 30000);
      return el;
    }
    async function отправитьЕщё(job, итог, b, место, всёРавно) {
      if (b.disabled) return;
      b.disabled = true;
      // в чат города (не ответом) — снова защита от перекрытия (прошлая проверка была до первой отправки, бывает — часы назад):
      // 2.1.3 программа Telegram смотрит чат и отправляет одним заданием (отправитьTG); «Всё равно отправить» — без проверки
      const tg = job.tg;
      b.textContent = !всёРавно && tg && tg.kind === 'city' && !tg.reply ? 'Проверяю чат и отправляю…' : 'Отправляем…';
      const r = await отправитьTG(job, итог.tg.text, всёРавно);
      if (r.перекрытие) {
        // не «Ничего не делали» (как перед действием): CRM-часть могла быть сделана — не делали только отправку в чат
        место.textContent = 'В «' + (tg.title || 'чат города') + '» ждёт ответа просьба филиала: ' + LC_TG.просьбаКратко(r.guard[r.guard.length - 1]) + '. В чат пока не отправлял — ответьте филиалу или «Всё равно отправить»';
        место.className = (место.className || '').split(' ')[0] + ' warn';
        b.replaceWith(h('button', { class: String(b.className || '').replace(/\s*pri\b/, ''), onclick: (e) => отправитьЕщё(job, итог, e.currentTarget, место, true) }, 'Всё равно отправить'));
        return;
      }
      if (r.неПроверен) {
        место.textContent = 'Не смог проверить «' + (tg.title || 'чат города') + '» на просьбы филиала (программа Telegram не ответила). В чат пока не отправлял — «Всё равно отправить» или напишите сами';
        место.className = (место.className || '').split(' ')[0] + ' warn';
        b.replaceWith(h('button', { class: String(b.className || '').replace(/\s*pri\b/, ''), onclick: (e) => отправитьЕщё(job, итог, e.currentTarget, место, true) }, 'Всё равно отправить'));
        return;
      }
      итог.tg = { ...итог.tg, ...r };
      место.textContent = r.ok ? '✓ Ушло в «' + (job.tg.title || 'чат') + '»' : 'Не отправилось: ' + r.error;
      место.className = (место.className.split(' ')[0]) + (r.ok ? ' ok' : ' warn');
      if (r.ok) { b.remove(); записать(job, { state: 'ok', итог: 'отправлено в чат после повтора' }); return; }
      // Telegram не ответил — могло и уйти: ещё раз не предлагаем, сначала «Проверить чат»
      if (r.unknown) { место.textContent = 'Telegram не ответил — не знаю, ушло ли'; b.replaceWith(h('button', { class: b.className.replace(/\s*pri\b/, ''), onclick: (e) => проверитьЧат(job, итог, e.currentTarget, место) }, 'Проверить чат')); return; }
      b.disabled = false; b.textContent = 'Отправить ещё раз';
    }
    /* последние сообщения чата: сервер отдаёт не больше 50, новые первыми. Вернулось 50, а самое раннее — позже «с» — окно не
       покрыто: «нет в чате» по нему сказать нельзя (в людном чате наше сообщение просто старше 50 последних) */
    const ЧАТ_N = 50;
    const окноНеполное = (r, с) => { const m = (r && r.messages) || []; return m.length >= ЧАТ_N && !(Math.min(...m.map((x) => Number(x.at) || Infinity)) <= с); };
    // Telegram не ответил: ищем свой текст в последних сообщениях чата — нашли, значит ушло
    async function проверитьЧат(job, итог, b, место) {
      b.disabled = true; b.textContent = 'Смотрю чат…';
      const с = Math.floor(Date.now() / 1000) - 3600;
      const r = await сроком(send({ kind: 'lcz-tg', args: { action: 'recent', chat: job.tg.chat, n: ЧАТ_N, since: с } }), 25e3);
      const нашли = ((r && r.ok && r.messages) || []).some((m) => m.out && String(m.text || '').trim() === итог.tg.text.trim());
      b.disabled = false; b.textContent = 'Проверить чат';
      if (!r || !r.ok) { место.textContent = 'Чат не прочитался — посмотрите в Telegram сами'; return; }
      if (!нашли && окноНеполное(r, с)) { место.textContent = 'В последних ' + ЧАТ_N + ' сообщениях «' + (job.tg.title || 'чат') + '» его нет, а чат длиннее — не знаю, ушло ли: посмотрите в Telegram сами'; return; }
      место.textContent = нашли ? '✓ Сообщение есть в «' + (job.tg.title || 'чат') + '» — ушло' : 'В «' + (job.tg.title || 'чат') + '» его нет — можно отправить';
      if (нашли) { b.remove(); итог.tg.ok = true; записать(job, { state: 'ok', итог: 'отправлено (проверил чат)' }); }
      else { итог.tg.unknown = false; b.replaceWith(h('button', { class: b.className, onclick: (e) => отправитьЕщё(job, итог, e.currentTarget, место) }, 'Отправить ещё раз')); }
    }
    /* «Проверить»: CRM не ответила или вкладку закрыли посреди действия — сверяем карточку с целью действия, ничего не пишем.
       Шаг ядра crmact — его проверкой (act с check:true: сама CRM-часть знает цель рецепта); иначе — снимком и целью плана.
       Сделано — больше не делаем; не сделано — можно нажать ещё раз (новым кликом оператора); не понять — решает оператор */
    async function проверить(job, b, место, шаг) {
      if (b) { b.disabled = true; b.textContent = 'Смотрю карточку…'; }
      const x = await журнал((all) => ({ значение: all[job.ключ] || null }));
      if (!job.steps.length && job.tg && job.tg.chat) return проверитьОтправку(job, b, место, x);
      const i = шаг != null ? шаг : job.шагНеясно != null ? job.шагНеясно : x && x.шаг != null ? x.шаг : 0;
      const st = job.steps[i];
      let да = null, после = null, ошибка = '', ждать = '';
      if (st && st.проверка) {
        const r = await сроком(st.проверка(), 60e3, 'CRM не ответила за минуту').catch((e) => ({ ok: false, error: String((e && e.message) || e) }));
        после = (r && r.after) || null;
        if (r && r.ok) да = true;
        // ядро: «пока нет, а прошлый запрос ещё висит» — это не «не сделано»: повтор сейчас мог бы сделать дважды
        else if (r && (r.notDone || r.code === 'не сделано') && /подождите|ещё не ответил/i.test(String(r.error || ''))) ждать = String(r.error);
        else if (r && (r.notDone || r.code === 'не сделано')) да = false;
        else if (!(r && r.unknown && r.after)) ошибка = (r && r.error) || 'карточка не прочиталась';
      }
      // цель этого шага (у составного действия у каждого шага своя), иначе — всего действия
      const цель = (st && st.цель) || job.цель || (x && x.цель) || null;
      if (!после && !ошибка) {
        const s = await снимок(job.cr, true);
        if (!s.ok) ошибка = s.error; else после = s.card;
      }
      // «+1» (отметки «Не отвечает», «Переносы») — от карточки ДО действия из записи «начато», не от снимка нового нажатия
      const было = x && x.до ? { ...(job.snap || {}), ...x.до } : job.snap;
      if (да === null && после) да = совпадает(после, цель, было);
      if (b) { b.disabled = false; b.textContent = 'Проверить'; }
      if (ошибка && !после) { место.textContent = 'Карточка не прочиталась: ' + ошибка; return null; }
      if (после) запомнитьСнимок(job.cr, после);
      if (ждать) { место.textContent = ждать; return null; }
      const сейчас = 'Сейчас в CRM: «' + (состояние(после) || '—') + '»';
      if (да === true) {
        /* шаг не дошёл до ответа CRM — дальше бегунок не шёл: остальные шаги и чат НЕ сделаны. Не говорим «сделано» целиком */
        const остальное = st ? job.steps.slice(i + 1).map((y) => y.title).filter(Boolean) : [];
        const чатНеБыл = !!(job.tg && job.tg.on && st);
        if (остальное.length) {
          await записать(job, { state: 'частично', crmDone: true, итог: 'проверено: ' + (st.журнал ? st.журнал({}) : 'шаг ' + (i + 1)) + ' — сделано, дальше не делал' });
          место.textContent = '✓ В CRM сделано: ' + st.title + ' (проверил карточку). Дальше не делал: ' + остальное.join(', ') + (чатНеБыл ? '; в чат не писали' : '') + '. ' + сейчас + ' — сделайте остальное отдельным действием или в CRM';
          return true;
        }
        const счёт = после && после.noAnswerCount != null ? { счётПосле: Number(после.noAnswerCount) } : {};
        if (чатНеБыл) { await чатПослеПроверки(job, после, место, сейчас); return true; }
        await записать(job, { state: 'ok', итог: 'проверено: в CRM сделано', ...счёт });
        const lc = await доделатьLeadChat(job, после, null);
        место.textContent = '✓ В CRM сделано (проверил карточку). ' + сейчас + (job.tg && job.tg.on ? '. Было ли сообщение в чат — посмотрите в Telegram' : '') + (lc.length ? ' · ' + lc.join(' · ') : '');
        return true;
      }
      if (да === false) { await записать(job, { state: 'нет', итог: 'проверено: не сделано' }); место.textContent = 'В CRM не сделано. ' + сейчас + ' — можно нажать «Сделать» ещё раз'; кнопкаОткрыть(job, место); return false; }
      место.replaceChildren(h('span', {}, сейчас + '. По карточке не понять — сделано ли действие?'), ' ',
        h('button', { class: 'sm', onclick: async () => { await записать(job, { state: 'ok', итог: 'оператор: сделано' }); const lc = await доделатьLeadChat(job, после, null); место.textContent = 'Отмечено: сделано — второй раз не сделаю' + (lc.length ? ' · ' + lc.join(' · ') : ''); } }, 'Сделано'), ' ',
        h('button', { class: 'sm', onclick: async () => { await записать(job, { state: 'нет', итог: 'оператор: не сделано' }); место.textContent = 'Отмечено: не сделано — можно нажать «Сделать» ещё раз'; } }, 'Не сделано'));
      return null;
    }

    /* «Проверить» подтвердил: CRM-часть сделана, а бегунок до LeadChat не дошёл (ответа CRM не было) — заметка, № в имени, связь
       диалога, как в конце хода (повтор не задвоит: заметка — с id от ключа, имя пишется, только если другое). Сообщение клиенту —
       нет: его отправляют только кликом «Сделать», а не «Проверить» */
    async function доделатьLeadChat(job, после, tgИтог) {
      if (!job.conv || !job.lc) return [];
      try {
        job.crmDone = true;
        if (job.послеCRM) { try { await job.послеCRM({ lastChange: '', после, строки: [] }); } catch (_e) { /* запись в память — не главное */ } }
        const r = await вLeadChat({ ...job, lc: { ...job.lc, client: null } }, job.steps.length ? ['в CRM сделано (проверил карточку)'] : [], tgИтог);
        return r.строки;
      } catch (_e) { return ['LeadChat не записался — заметку и № в имени впишите вручную']; }
    }
    /* строка «Переносов», которую сделало ЭТО действие: время в ней («на "дд.мм.гггг/чч:мм"») — то, что просили; времени в цели нет —
       строка новая против снимка до действия. Иначе (старая строка с прошлой недели, снимка нет) — не наша: в чат её не берём */
    function строкаПереноса(lc, цель, было) {
      lc = String(lc || '').trim();
      if (!lc) return '';
      const ц = цель || {};
      if (ц.visitDate || ц.visitTime) {
        const m = lc.match(/на\s*"([^"/]*)\/?([^"]*)"/);
        if (!m) return '';
        if (ц.visitDate && isoД(m[1]) !== isoД(ц.visitDate)) return '';
        if (ц.visitTime && String(m[2] || '').slice(0, 5) !== String(ц.visitTime).slice(0, 5)) return '';
        return lc;
      }
      return было && String(было.lastChange || '').trim() !== lc ? lc : '';
    }
    /* CRM-часть сделана (проверили карточку), а до чата бегунок не дошёл: текст — оператору, отправка — только его кликом */
    async function чатПослеПроверки(job, после, место, сейчас) {
      const цели = Object.assign({}, job.цель || {}, ...(job.steps || []).map((x) => x.цель || {}), job.цельЧата || {});
      // просили время, а в карточке другое (вернули, но перенос не дошёл) — в чат не предлагаем: сначала «Перенос»
      if (job.цельЧата && после && совпадает(после, job.цельЧата) === false) {
        await записать(job, { state: 'частично', crmDone: true, итог: 'проверено: в CRM сделано без переноса; в чат не писали' });
        const lc0 = await доделатьLeadChat(job, после, null);
        место.textContent = '✓ В CRM сделано, но время визита не то, что просили (' + [дм(job.цельЧата.visitDate), job.цельЧата.visitTime || ''].filter(Boolean).join(' ') + '). ' + сейчас + '. Перенесите действием «Перенос» — оно и напишет в чат. В «' + (job.tg.title || 'чат') + '» пока не писали' + (lc0.length ? ' · ' + lc0.join(' · ') : '');
        return;
      }
      const lcРаньше = await доделатьLeadChat(job, после, null);
      const tg = job.tg, lc = строкаПереноса(после && после.lastChange, цели, job.snap);
      let text = '';
      try {
        if (typeof tg.text === 'function') text = tg.text({ lastChange: lc, после, результаты: [] });
        else if (tg.изCRM) text = lc ? job.id + ' ' + String(lc).trim() + (tg.suffix || '') : '';
        else text = String(tg.text || '').replace(/\{(?:lastChange|перенос)\}/g, lc || '…');
      } catch (_e) { text = ''; }
      text = String(text || '').trim();
      const готов = !!text && !/"…|…"|\{/.test(text);                 // заготовка без строки «Переносов» в чат сама не уходит
      await записать(job, { state: 'частично', crmDone: true, итог: 'проверено: в CRM сделано; в чат не писали' });
      const итогЧата = { tg: { ok: false, text } };
      место.replaceChildren(h('span', {}, '✓ В CRM сделано (проверил карточку). ' + сейчас + '. В «' + (tg.title || 'чат') + '» ещё не писали' + (text ? ': «' + text + '»' : ' — напишите сами') + (lcРаньше.length ? ' · ' + lcРаньше.join(' · ') : '')), ' ',
        ...(text ? [h('button', { class: 'sm', onclick: (e) => копировать(text, e.currentTarget) }, 'Копировать'), ' '] : []),
        ...(готов && tg.chat ? [h('button', { class: 'sm pri', onclick: (e) => { const м = h('span', {}); e.currentTarget.after(м); отправитьЕщё(job, итогЧата, e.currentTarget, м); } }, 'Отправить в чат')] : []));
    }

    // в уведомлении «Сделать» нет: «можно ещё раз» — с кнопкой, которая открывает это действие (карточка с превью, без записи)
    function кнопкаОткрыть(job, место) {
      if (!место || typeof место.closest !== 'function' || !место.closest('.tst') || !каталог(job.act) || чужойДиалог(job.conv)) return;
      место.append(' ', h('button', { class: 'sm', onclick: () => карточка(job.conv, job.cr, job.act, job.ввод || {}, { from: 'итог' }) }, 'Открыть действие'));
    }
    /* «Проверить» для действия только в чат: есть ли наше сообщение среди последних в чате (за 12 ч). Есть — больше не шлём;
       нет — можно нажать «Сделать» ещё раз (бегунок снова проверит чат на просьбы филиала) */
    async function проверитьОтправку(job, b, место, x) {
      if (b) { b.disabled = true; b.textContent = 'Смотрю чат…'; }
      const текст = String(job.tgТекст || (typeof job.tg.text === 'string' ? job.tg.text : '') || '').trim();
      // окно — от нажатия (запись «начато» — до отправки), не полдня: и короче, и точнее
      // запас 30 мин: x.at — часы ПК, время сообщений — часы Telegram; ПК спешит — наше сообщение не выпадет из окна («нет» → второе)
      const с = x && x.at ? Math.floor(x.at / 1000) - 1800 : Math.floor(Date.now() / 1000) - 12 * 3600;
      const r = await сроком(send({ kind: 'lcz-tg', args: { action: 'recent', chat: job.tg.chat, n: ЧАТ_N, since: с } }), 25e3);
      if (b) { b.disabled = false; b.textContent = 'Проверить'; }
      const чат = '«' + (job.tg.title || 'чат') + '»';
      const был = String((x && x.tgХэш) || '');                     // в журнале — отпечаток текста (сам текст не храним)
      if (!r || !r.ok || (!текст && !был)) { if (место) место.textContent = 'Чат не прочитался — посмотрите в Telegram сами'; return null; }
      const нашли = (r.messages || []).some((m) => m.out && ((текст && String(m.text || '').trim() === текст) || (был && отпечатокЧата(m.text) === был)));
      if (нашли) {
        await записать(job, { state: 'ok', итог: 'проверено: в чате есть' });
        const lc = await доделатьLeadChat(job, null, { ok: true, text: текст });
        if (место) место.textContent = '✓ Сообщение есть в ' + чат + ' — ушло, второй раз не отправляю' + (lc.length ? ' · ' + lc.join(' · ') : '');
        return true;
      }
      if (окноНеполное(r, с)) { if (место) место.textContent = 'В последних ' + ЧАТ_N + ' сообщениях ' + чат + ' его нет, а чат с тех пор длиннее — не знаю, ушло ли: посмотрите в Telegram сами, прежде чем нажимать ещё раз'; return null; }
      await записать(job, { state: 'нет', итог: 'проверено: в чате нет' });
      if (место) { место.textContent = 'В ' + чат + ' его нет — можно нажать «Сделать» ещё раз'; кнопкаОткрыть(job, место); }
      return false;
    }

    /* ---------- СЕТКА «Действия по заявке» (2.1, проект «Действия») ----------
       Шапка (№ · статус · «обновлено N с назад»), «Что в заявке», синяя строка «Предлагаю …» с одной кнопкой, 6 больших плиток 3×2,
       «Ещё (N)» — капсулами (ничего не спрятано), «Нет здесь (статус …): … — почему».
       o.безШапки — шапку рисует хозяин (карточка «есть заявка»: № крупно), ему — o.наСнимок({snap, at, обновить});
       o.подсказка — своя строка «Предлагаю» хозяина {текст, почему, кнопка: () => элемент}; o.выделить — ключ плитки, о которой писал клиент */
    function визит(snap, cr, conv) {
      const d = (snap && snap.visitDate) || '', t = (snap && snap.visitTime) || '';
      if (!d && !t) return { text: '', late: null, до: '' };
      let x = { late: null };
      try { x = хост.визитСейчас({ city: (snap && snap.cityName) || cr.city || '', visit: d, visitTime: t }, (хост.ПОЯС && хост.ПОЯС(conv)) || ''); } catch (_e) { /* без часов города */ }
      const до = x.late === null || x.late === undefined ? '' : x.late > 0 ? 'опаздывает ' + сколько(x.late) : x.late < 0 ? 'через ' + сколько(-x.late) : 'сейчас';
      return { text: [дм(d), t].filter(Boolean).join(' ') + (до ? ' (' + до + ')' : ''), late: x.late, до };
    }
    const сколько = (m) => (m >= 60 ? Math.floor(m / 60) + ' ч' + (m % 60 ? ' ' + (m % 60) + ' мин' : '') : m + ' мин');
    // почему действия нет в сетке — по запросу оператора («почему»)
    function почемуНет(key, snap) {
      const k = каталог(key);
      if (!k) return 'нет в каталоге';
      if (Array.isArray(k.statuses) && snap && !k.statuses.includes(snap.statusCode)) return 'не для статуса «' + (snap.statusName || '—') + '»';
      if (k.needButton && snap && snap.buttons && ![].concat(k.needButton).some((b) => snap.buttons[b])) return 'в CRM нет кнопки';
      return 'не по правилам регламента для этой заявки';
    }
    const опасная = (key) => /^cancel|^rejected|not_taken$/.test(String(key || ''));
    function сетка(cr, opts) {
      if (!есть() || !cr || !cr.id || !cr.dir) return null;
      const o = opts || {}, conv = o.conv || хост.convIdNow();
      const el = h('section', { class: 'ag', 'data-act-grid': cr.dir + ':' + cr.id }, h('div', { class: 'n mut' }, 'Смотрю заявку в CRM…'));
      // «Что в заявке» — сразу под шапкой; претензия — когда о ней известно (hasClaim, сообщение в чате)
      const претензияЕсть = cr.hasClaim === true || !!cr.claimMsg;
      const ИНФО = { подр: null, пр: null, ждём: false, at: 0, собрать: null, тик: 0 };
      const нарисовать = (snap, err) => {
        if (err) {
          el.replaceChildren(h('div', { class: 'box warn' }, иконка('warn'), h('div', { class: 'c' }, h('div', {}, 'Не удалось открыть заявку в CRM: ' + err),
            h('div', { class: 'row', style: 'gap:6px;flex-wrap:wrap' }, h('button', { class: 'sm', onclick: () => загрузить(true) }, 'Повторить')))),
          ...(o.запасное ? [].concat(o.запасное()) : []));
          return;
        }
        const ctx = ctxДля(conv, cr, o.where || 'grid', snap);
        const все = доступные(snap, ctx);
        let hint = o.hint || null;
        if (!hint && !o.подсказка && typeof LC_ACT.подсказка === 'function') { try { hint = LC_ACT.подсказка('rules', snap, { ...ctx, conv, cr }) || null; } catch (_e) { hint = null; } }
        if (hint && !все.some((x) => x.key === hint.key)) hint = null;    // подсказка недоступного действия — не показываем
        const в = визит(snap, cr, conv);
        // визит прошёл > 10 мин, а статус «Ожидает»/«В пути» — «Где мастер?» первой (пассивно, без уведомления)
        const опоздание = в.late !== null && в.late > порог('опозданиеОтменаМин', 10) && (snap.statusCode === 1 || snap.statusCode === 4);
        let основные = все.filter((x) => x.primary), прочие = все.filter((x) => !x.primary);
        if (опоздание) { const w = все.find((x) => x.key === 'where'); if (w) { основные = [w, ...основные.filter((x) => x !== w)]; прочие = прочие.filter((x) => x !== w); } }
        if (основные.length > 6) { прочие = [...основные.slice(6), ...прочие]; основные = основные.slice(0, 6); }
        const flagsЕсть = все.some((x) => x.key === 'flags');
        // подсказка (ИИ/правила) — одна подсвеченная плитка: того же ключа и того же ввода, если таких плиток несколько.
        // Клиент писал о действии (o.выделить, строка хозяина) — подсвечена плитка этого действия
        const та = hint ? все.find((x) => x.key === hint.key && x.ввод && hint.ввод && канон(x.ввод) === канон(hint.ввод)) || все.find((x) => x.key === hint.key)
          : o.выделить ? все.find((x) => x.key === o.выделить && x.primary) || все.find((x) => x.key === o.выделить) : null;
        const подсвечена = (x) => !!та && x === та;
        const почемуТа = hint ? hint.почему || '' : (o.подсказка && o.подсказка.почему) || '';
        const группа = (x) => x.group || (каталог(x.key) || {}).group || 'Другое';
        const идёт = занято(cr);
        // плитка несёт свой ввод («Прозвон» — flags {callCheck}, «НФ: не отвечает» — precheck_close {code: 579}); подсказка правил — свой
        const открытьПлитку = (x) => выбрать(x.key, { ...(x.ввод || {}), ...(hint && подсвечена(x) ? hint.ввод || {} : {}) }, hint && подсвечена(x) ? { from: 'rules', почему: hint.почему || '' } : null);
        const плитка = (x, мелкая) => h('button', { class: (мелкая ? 'ag-s' : 'ag-t') + (подсвечена(x) ? ' hint' : '') + (опасная(x.key) ? ' bad' : ''), 'data-act': x.key, 'data-act-id': x.id || x.key,
          'data-group': мелкая ? группа(x) : undefined,
          title: идёт ? 'Идёт действие по заявке — дождитесь итога' : (подсвечена(x) ? почемуТа : '') || x.hint || (мелкая ? группа(x) + ': ' : '') + (x.label || ''), disabled: идёт,
          onclick: () => открытьПлитку(x) },
        мелкая ? '' : иконка(иконкаПлитки(x), 20), h('span', { class: 'lb' }, x.label || (каталог(x.key) || {}).label || x.key));
        const выбрать = async (key, ввод, ист) => {
          if (o.перед) { try { await o.перед(key); } catch (_e) { /* связь диалога с заявкой — не главное */ } }
          if (o.where === 'created' && хост.closePanel) хост.closePanel();
          карточка(conv, cr, key, ввод || {}, ист || { from: o.where || 'grid' });
        };
        // чипы галочек — в строке «Галочки» «Что в заявке»: горят — стоят; клик — карточка «Галочки» с этим переключателем, уже перевёрнутым
        let есть5 = ФЛАГИ.filter(([k]) => snap.flags && snap.flags[k] !== null && snap.flags[k] !== undefined);
        if (typeof LC_ACT.переключатели === 'function') { try { const sw = LC_ACT.переключатели(snap) || []; есть5 = есть5.filter(([k]) => sw.some((x) => x.name === k)); } catch (_e) { /* как в снимке */ } }
        const чипы = () => есть5.map(([k, t]) => {
          const нельзя = !flagsЕсть || идёт || (snap.flagsEnabled && snap.flagsEnabled[k] === false);
          return h('button', { class: 'ag-chip' + (snap.flags[k] ? ' on' : ''), 'data-flag': k, 'aria-pressed': snap.flags[k] ? 'true' : 'false', disabled: нельзя,
            title: идёт ? 'Идёт действие по заявке — дождитесь итога' : нельзя ? t + ': в CRM сейчас не изменить' : snap.flags[k] ? t + ' стоит — нажмите, чтобы снять' : t + ' не стоит — нажмите, чтобы поставить',
            onclick: () => выбрать('flags', { [k]: !snap.flags[k] }) }, (snap.flags[k] ? '✓ ' : '') + t);
        });
        ИНФО.собрать = () => сводка(snap, ИНФО.подр, ИНФО.пр, { вСетке: true, претензииЖдём: ИНФО.ждём, атрибут: 'ag-info', чипы: чипы(), доВизита: опоздание ? '' : в.до, url: cr.url && /^https?:/.test(cr.url) ? cr.url : snap.url });
        // «Ещё (N)»: все остальные доступные — капсулами по группам (порядок групп — как в CRM), ничего не спрятано
        const поГруппе = (x) => ((ГРУППЫ.indexOf(группа(x)) + 1) || 99);
        const ещё = прочие.map((x, i) => [x, i]).sort((a, b) => поГруппе(a[0]) - поГруппе(b[0]) || a[1] - b[1]).map(([x]) => x);
        // «Нет здесь (статус …): … — почему»: причины каталога (LC_ACT.недоступные), иначе — по статусу и кнопкам снимка
        let нет = [];
        if (typeof LC_ACT.недоступные === 'function') { try { нет = (LC_ACT.недоступные(snap, ctx) || []).map((x) => ({ label: x.label || (каталог(x.key) || {}).label || x.key, почему: x.почему })); } catch (_e) { нет = []; } }
        else if (LC_ACT.КАТАЛОГ) нет = Object.keys(LC_ACT.КАТАЛОГ).filter((k) => !все.some((x) => x.key === k) && !(LC_ACT.КАТАЛОГ[k] || {}).hidden && !(LC_ACT.КАТАЛОГ[k] || {}).off).map((k) => ({ label: (каталог(k) || {}).label || k, почему: почемуНет(k, snap) }));
        const имена = [...new Set(нет.map((x) => x.label))];
        const причины = new Map();
        for (const x of нет) { const к = сЗаглавной(x.почему || 'нет'); if (!причины.has(к)) причины.set(к, []); if (!причины.get(к).includes(x.label)) причины.get(к).push(x.label); }
        const почему = h('div', { class: 'ag-why', hidden: true }, ...[...причины].map(([п, l]) => h('div', { class: 'ag-why-r' }, h('b', {}, п + ': '), l.join(', '))));
        // строка «Предлагаю …» с одной кнопкой: своя у хозяина (клиент написал по заявке) или подсказка правил каталога
        const предлагаю = o.подсказка ? h('div', { class: 'ac-sug', 'data-ac': 'suggest' }, h('div', { class: 'tx' }, h('b', {}, o.подсказка.текст + ':'), o.подсказка.почему ? ' ' + o.подсказка.почему : ''),
          typeof o.подсказка.кнопка === 'function' ? o.подсказка.кнопка() : '')
          : та && hint ? h('div', { class: 'ac-sug', 'data-ac': 'suggest' }, h('div', { class: 'tx' }, h('b', {}, 'Предлагаю «' + (та.label || (каталог(та.key) || {}).label || та.key) + '»:'), hint.почему ? ' ' + hint.почему : ''),
            h('button', { class: 'ac-sug-b', disabled: идёт, onclick: () => открытьПлитку(та) }, 'Открыть')) : '';
        el.replaceChildren(
          o.безШапки ? '' : h('div', { class: 'ag-st' }, h('b', {}, база(cr.dir) + ' № ' + cr.id), h('span', { class: 'ac-pill ' + цветСтатуса(snap.statusName) }, snap.statusName || '—'),
            опоздание ? h('span', { class: 'chip warn' }, 'опаздывает ' + сколько(в.late)) : '',
            h('button', { class: 'ag-upd', 'data-ac': 'upd', title: 'Перечитать заявку в CRM', onclick: () => загрузить(true) }, обновлено(ИНФО.at))),
          ИНФО.собрать(),
          snap.held && snap.held.yes && !snap.held.mine ? h('div', { class: 'ac-line warn' }, 'Заявку сейчас держит другой сотрудник') : '',
          предлагаю,
          h('div', { class: 'cap ag-cap' }, 'Действия'),
          основные.length ? h('div', { class: 'ag-tiles' }, ...основные.map((x) => плитка(x))) : h('div', { class: 'n mut' }, 'Для статуса «' + (snap.statusName || '—') + '» действий из расширения нет — только в CRM'),
          ещё.length ? h('div', { class: 'ag-more' }, h('div', { class: 'cap ag-cap', 'data-ac': 'more-count' }, 'Ещё (' + ещё.length + ')'), h('div', { class: 'ag-pills', lang: 'ru' }, ...ещё.map((x) => плитка(x, true)))) : '',
          имена.length ? h('div', { class: 'ag-q' }, h('div', { class: 'ag-no' }, 'Нет здесь (статус «' + (snap.statusName || '—') + '»): ' + имена.slice(0, 4).join(', ') + (имена.length > 4 ? ' и ещё ' + (имена.length - 4) : '') + ' — ',
            h('button', { class: 'ag-qb', 'aria-expanded': 'false', title: 'Каких действий нет и почему', onclick: (e) => { почему.hidden = !почему.hidden; e.currentTarget.setAttribute('aria-expanded', почему.hidden ? 'false' : 'true'); } }, 'почему')), почему) : '');
        if (typeof o.наСнимок === 'function') { try { o.наСнимок({ snap, at: ИНФО.at, обновить: () => загрузить(true) }); } catch (_e) { /* шапка хозяина — не главное */ } }
      };
      // «обновлено N с назад» — живое, пока сетка на экране
      const тик = () => { ИНФО.тик = 0; if (!el.isConnected) return; const u = el.querySelector('[data-ac="upd"]'); if (u && ИНФО.at) u.textContent = обновлено(ИНФО.at); ИНФО.тик = setTimeout(тик, 15000); };
      const загрузить = async (свежий) => {
        el.replaceChildren(h('div', { class: 'n mut' }, 'Смотрю заявку в CRM…'));
        const s = await снимок(cr, свежий);
        ИНФО.подр = s.ok ? s.details : null;
        ИНФО.at = s.ok ? s.at || Date.now() : 0;
        ИНФО.ждём = s.ok && претензияЕсть && !ИНФО.пр;
        нарисовать(s.ok ? s.card : null, s.ok ? '' : s.error);
        if (s.ok && !ИНФО.тик && !o.безШапки) ИНФО.тик = setTimeout(тик, 15000);
        // № и статус претензии — вторым чтением, не задерживая сетку
        if (s.ok && претензияЕсть && !ИНФО.пр) {
          const пр = await претензии(cr).catch(() => null);
          ИНФО.пр = пр; ИНФО.ждём = false;
          const old = el.querySelector('[data-ac="ag-info"]'), n = ИНФО.собрать ? ИНФО.собрать() : '';
          if (old && n) old.replaceWith(n);
        }
      };
      el._обновить = () => загрузить(true);
      загрузить(false);
      return el;
    }

    /* ---------- КАРТОЧКА ДЕЙСТВИЯ: превью = подтверждение ---------- */
    /* поля карточки: каталог (КАТАЛОГ[key].поля — PE и др.) → LC_ACT.поля → свои (ПОЛЯ). Галочек, которых в карточке нет, не показываем */
    function поляДля(key, snap, ctx) {
      const d = каталог(key);
      let п = null;
      try {
        if (d && typeof d.поля === 'function') п = d.поля(snap, ctx);
        else if (d && Array.isArray(d.поля)) п = d.поля;
        else if (есть() && typeof LC_ACT.поля === 'function') п = LC_ACT.поля(key, snap, ctx);
      } catch (_e) { п = null; }
      let sw = null;
      if (key === 'flags' && есть() && typeof LC_ACT.переключатели === 'function') { try { sw = (LC_ACT.переключатели(snap) || []).map((x) => x.name); } catch (_e) { sw = null; } }
      return (Array.isArray(п) ? п : ПОЛЯ[key] || []).map(норм).filter((f) => !(f.flag && (sw ? !sw.includes(f.name)
        : snap && snap.flags && (snap.flags[f.name] === null || snap.flags[f.name] === undefined))));
    }
    function вариантыПоля(f, snap) {
      if (Array.isArray(f.options)) return f.options.map((x) => (Array.isArray(x) ? x : x && typeof x === 'object' ? [x.value, x.text || x.title] : [x, x]));
      const п = есть() && LC_ACT.причины ? LC_ACT.причины : {};
      const из = (list) => (Array.isArray(list) ? list : list && typeof list === 'object' ? Object.entries(list) : []).map((x) => (Array.isArray(x) ? x : typeof x === 'object' ? [x.value, x.text || x.title] : [x, x]));
      if (f.options === 'претензии') return LC_TG.ТИПЫ_ПРЕТЕНЗИЙ.map((t, i) => [String(i + 1), (i + 1) + ') ' + t]);
      if (f.options === 'базы') return ((snap && snap.transferServers) || []).map((x) => [x.key, x.title]);
      const ЗАПАС = { отмена: LC_TG.ПРИЧИНЫ_ОТМЕНЫ, перенос: ПРИЧИНЫ.перенос, филиал: ПРИЧИНЫ.филиал, нф: ПРИЧИНЫ.нф, уточнение: ПРИЧИНЫ.уточнение, стык: ПРИЧИНЫ.стык };
      const ИМЕНА = { филиал: ['филиал', 'отменаФилиал'], нф: ['нф', 'НФ'] };
      for (const k of ИМЕНА[f.options] || [f.options]) if (п[k] && (Array.isArray(п[k]) || typeof п[k] === 'object')) return из(п[k]);
      return из(ЗАПАС[f.options]);
    }
    function начальныйВвод(key, snap, ввод, поля, ctx) {
      const v = JSON.parse(JSON.stringify(ввод || {}));
      const есть0 = (x) => x !== undefined && x !== null && x !== '';
      // сначала — из слов клиента (ИИ): тип претензии, причина отмены, строка комментария; значения каталога по умолчанию
      // («помощь не требуется») — только если из слов ничего не вышло. Оператор видит и правит
      const слова = [v.summary, v.text].filter(Boolean).join(' ');
      if (key === 'claim') {
        // поля каталога — claimType / comment (actions.js), прежние — typeNo / text: заполняем обе пары одинаково
        const тип = есть0(v.claimType) ? String(v.claimType) : есть0(v.typeNo) ? String(v.typeNo) : слова ? String(LC_TG.типПретензии(слова) || '') : '';
        if (тип) { if (!есть0(v.claimType)) v.claimType = тип; if (!есть0(v.typeNo)) v.typeNo = тип; }
        const к = есть0(v.text) ? v.text : v.summary || '';
        if (!есть0(v.text) && к) v.text = к;
        if (!есть0(v.comment) && к) v.comment = к;
      }
      if (key === 'cancel_kc' && !есть0(v.reason) && v.summary) { const x = LC_TG.причинаОтмены(v.summary); if (x) v.reason = x; }
      if ((key === 'comment' || key === 'claim_again') && !есть0(v.text) && v.summary) v.text = v.summary;
      // перенос: дата — текущего визита, если он сегодня или позже (по часам города); время оператор ставит сам
      if(key==='edit'&&snap){
        if(!есть0(v.date))v.date=isoД(snap.visitDate);
        if(!есть0(v.time))v.time=String(snap.visitTime||'').slice(0,5);
      }
      if (key === 'move' && !есть0(v.date) && snap && snap.visitDate) {
        const д = isoД(snap.visitDate), сег = (ctx && ctx.сейчас && ctx.сейчас.date) || '';
        if (д && сег && д >= сег) v.date = д;
      }
      for (const f of поля) {
        if (взять(v, f.name) !== undefined) continue;
        if (f.flag && snap && snap.flags) { const x = snap.flags[f.name]; положить(v, f.name, f.type === 'check' ? !!x : x == null ? '' : typeof x === 'boolean' ? (x ? '1' : '0') : String(x)); }
        else if (f.name === 'type' && key === 'flags' && snap && snap.type) v.type = String(snap.type);
        else if (f.value !== undefined) положить(v, f.name, f.value);
      }
      // Прозвон ⇄ Перед выездом — взаимоисключающие (как Чатерское и Leadbot): включили одну — вторая снимается
      if (key === 'flags') { if (ввод && ввод.callCheck === true) v.callBeforeVisit = false; if (ввод && ввод.callBeforeVisit === true) v.callCheck = false; }
      return v;
    }
    /* карточка действия: поля → превью (что в CRM, что в чат, что в LeadChat — это и есть подтверждение) → одна кнопка.
       источник: 'watch' | {from, seen?, почему?} — откуда пришли (подсказка, ИИ, сетка); seen — пометить подсказку «сделано» */
    // на экране другой диалог: карточку диалога A поверх B не показываем (её «Сделать» ушло бы из чужого контекста)
    const чужойДиалог = (conv) => !!conv && typeof хост.convIdNow === 'function' && хост.convIdNow() !== conv;
    /* карточку «держат»: мышь над ней или оператор сам поставил фокус внутрь после итога — автозакрытие ждёт.
       Слежка — одна на карточку (её же ставит content.js для прежней карточки «по заявке»); свой фокус (после итога) не считается */
    function рука() {
      if (card._рука) return card._рука;
      const р = card._рука = { наведено: false, фокус: 0, сам: false };
      if (typeof card.addEventListener !== 'function') return р;
      card.addEventListener('mouseenter', () => { р.наведено = true; });
      card.addEventListener('mouseleave', () => { р.наведено = false; });
      card.addEventListener('focusin', () => { if (!р.сам) р.фокус = Date.now(); });
      card.addEventListener('focusout', (e) => { if (!e.relatedTarget || !card.contains(e.relatedTarget)) р.фокус = 0; });
      return р;
    }
    const фокусВнутри = () => { try { const r = card.getRootNode(), a = r && r.activeElement; return !!a && a !== card && card.contains(a); } catch (_e) { return false; } };
    const держат = (с) => { const р = рука(); let над = р.наведено; try { над = над || card.matches(':hover'); } catch (_e) { /* без :hover */ } return над || (р.фокус > с && фокусВнутри()); };
    // успех закрывается сам через мс — если на экране всё та же карточка и её не держат (иначе ждём, пока отпустят)
    function автоЗакрыть(своя, мс) {
      const с = Date.now();
      const тик = () => { if (!своя()) return; if (держат(с)) { setTimeout(тик, 1500); return; } card.classList.remove('show'); };
      setTimeout(тик, мс);
    }
    // оператор печатает где-то ещё (поле LeadChat) — фокус не отнимаем: карточка могла открыться сама (подсказка ИИ)
    const фокусСвободен = () => {
      try {
        const r = card.getRootNode(), host = r.host;
        let a = document.activeElement;
        if (!a || a === document.body || a === document.documentElement) return true;
        if (host && a === host) a = r.activeElement;                    // фокус в нашей панели: печатают в её поле — тоже не отнимаем
        return !a || !(a.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName));
      } catch (_e) { return false; }
    };
    function фокус(el) {
      if (!el || typeof el.focus !== 'function' || el.disabled) return;
      const р = рука(); р.сам = true;
      try { el.focus({ preventScroll: true }); } catch (_e) { /* не страшно */ }
      р.сам = false;
    }
    async function карточка(conv, cr, key, ввод, источник0) {
      if (!есть() || !cr || !cr.id || !cr.dir) return false;
      const источник = typeof источник0 === 'string' ? { from: источник0 } : источник0 || { from: 'grid' };
      // на экране другой диалог. Сама (подсказка ИИ, пока оператор ушёл) — не показываем. По щелчку оператора (напоминание по заявке
      // диалога A, кнопка в итоге) — сначала открываем диалог A, потом карточку; не открылся (черновик, LeadChat не перешёл) — нет
      if (чужойДиалог(conv)) {
        if (источник.авто || typeof хост.перейти !== 'function') return false;
        try { if (!(await хост.перейти(conv))) return false; } catch (_e) { return false; }
        if (чужойДиалог(conv)) return false;
      }
      const моя = {}, метка = хэш(Date.now() + ':' + Math.random());
      рука();
      card._act = моя; card._live = null; card._addr = {}; card._доп = null;   // прежние карточки и их догрузки сюда не пишут
      // карточка одна на всё: другой экран (готовность диалога, «есть заявка») перерисовал её — наши догрузки больше не рисуют
      let рисовал = false;
      const мояЛи = () => card._act === моя && (!рисовал || !!card.querySelector('[data-act-card="' + метка + '"]'));
      const S = { key, ввод: JSON.parse(JSON.stringify(ввод || {})), snap: null, snapAt: 0, err: '', план: null, поля: [], ctx: ctxДля(conv, cr, источник), доп: {}, подг: null, подгN: 0, подгT: 0,
        чат: null, чатЖдём: false, tgText: null, tgПравка: false, tgOn: null, tgOnТрогал: false, noteOn: true, clientOn: false, clientТрогал: false, clientText: null, busy: false, итог: null, job: null,
        // 2.1: «Что в заявке» — подробности карточки и претензии (№ и статус) — только показ
        подр: null, пр: null, прЖдём: false };
      const q = (k) => card.querySelector('[data-ac="' + k + '"]');
      const наВиду = () => мояЛи() && card.classList.contains('show') && (!conv || хост.convIdNow() === conv);
      // претензия по заявке: «Претензия» / «Снова звонит» — всегда, иначе — когда о ней известно (hasClaim, её сообщение в чате)
      const нужныПретензии = () => ['claim', 'claim_again'].includes(S.key) || cr.hasClaim === true || !!cr.claimMsg;
      function пересобрать() {
        const c0 = ctxДля(conv, cr, источник, S.snap, { ...S.доп, подробности: S.подр || null });
        // есть ли претензия, не известно (ни сообщения, ни ответа «claims»), а список ОКК уже прочитан — по нему («Претензия» / «Снова звонит»)
        if (c0.hasClaim === undefined && S.пр && S.пр.ok !== false && Array.isArray(S.пр.list)) c0.hasClaim = S.пр.list.length > 0;
        S.ctx = { ...c0, ...(S.подг || {}) };
        S.поля = поляДля(S.key, S.snap, S.ctx);
        S.план = S.snap ? план(S.key, S.snap, S.ввод, S.ctx) : null;
        const tg = tgПлана(S.план);
        // «отправить в Telegram» — как в плане (например, «Срочная» включили — пишем), пока оператор сам не тронул галочку
        if (tg && !S.tgOnТрогал) S.tgOn = tg.on !== false && !!String(tg.text || '').trim();
        if (S.план && S.план.client && S.clientText === null) S.clientText = S.план.client.text || '';
        // «клиенту в LeadChat» — как решил владелец (В7, план: client.on; сейчас выкл.), пока оператор сам не тронул галочку
        if (S.план && S.план.client && !S.clientТрогал) S.clientOn = !!(S.план.client.on && S.план.client.text);
      }
      const чатКлюч = () => { const tg = tgПлана(S.план); return tg ? (tg.kind || 'city') + (tg.reply || '') : ''; };
      async function чатДляПлана() {
        const tg = tgПлана(S.план);
        if (!tg) { S.чат = null; return; }
        if (S.чат && S.чат._k === чатКлюч() && !S.чат.тгНет) return;
        S.чатЖдём = true;
        const k = чатКлюч();
        const ч = await куда(conv, cr, tg, S.snap).catch((e) => ({ нет: String((e && e.message) || e) }));
        if (!мояЛи()) return;
        S.чат = { ...(ч || { нет: 'чат не найден' }), _k: k }; S.чатЖдём = false;
        // 2.1.3: чат города (не ответом) — проверка на просьбы филиала заранее, пока оператор читает карточку: к нажатию ответ готов
        if (S.чат.id && (tg.kind || 'city') === 'city' && !S.чат.reply && typeof хост.просьбыВЧате === 'function') хост.просьбыВЧате(S.чат.id, { заранее: true }).catch(() => {});
        обновитьПревью();
      }
      // карточка клиента (PE) и т.п.: каталог дочитывает CRM для превью (без записи) — в ctx; ввод поменялся — дочитать снова
      // 2.1: свои дочитки экрана (ПОДГОТОВКА: «Вид работ» — виды услуг для выбранного вида работ), если у каталога своей нет.
      // Дочитка поменяла сами поля (варианты «Вида услуг») — карточка перерисовывается (ввод и фокус сохраняются)
      const подписьПолей = () => S.поля.map((f) => f.name + ':' + (f.required ? 1 : 0) + ':' + JSON.stringify(Array.isArray(f.options) ? f.options : f.options || '')).join('|');
      async function подготовить(сразу) {
        const d = каталог(S.key);
        const своя = (!d || typeof d.подготовить !== 'function') && ПОДГОТОВКА[S.key];
        if ((!d || typeof d.подготовить !== 'function') && !своя) return;
        if (!S.snap) return;
        clearTimeout(S.подгT);
        const пуск = async () => {
          const n = ++S.подгN;
          let x;
          try { x = своя ? await своя(S.snap, S.ввод, { cr, подр: S.подр }) : await d.подготовить(S.snap, S.ввод, хост); } catch (e) { x = своя ? {} : { cust: { ok: false, error: String((e && e.message) || e).slice(0, 100) } }; }
          if (!мояЛи() || n !== S.подгN) return;
          const было = подписьПолей();
          S.подг = x || {};
          пересобрать();
          if (своя && подписьПолей() !== было && !S.busy) нарисовать(); else обновитьПревью();
        };
        if (сразу) await пуск(); else S.подгT = setTimeout(пуск, 600);
      }
      // «Что в заявке» и строка претензии — на месте, без перерисовки полей (ввод оператора не трогаем)
      function обновитьСводку() {
        if (!мояЛи()) return;
        const старая = q('info'), новая = S.snap ? сводкаКарточки() : '';
        if (старая && новая) старая.replaceWith(новая);
        const стараяП = q('claim'), новаяП = ['claim', 'claim_again'].includes(S.key) ? строкаПретензии(S.пр, S.прЖдём) : '';
        if (стараяП && новаяП) стараяП.replaceWith(новаяП); else if (стараяП && !новаяП) стараяП.remove(); else if (!стараяП && новаяП && старая) (q('info') || старая).after(новаяП);
      }
      // под названием: заявка · статус · визит · «обновлено N с назад» (было «снимок N с назад»)
      const подпись = () => [база(cr.dir) + ' № ' + cr.id, ...(S.snap ? [S.snap.statusName || '—', обновлено(S.snapAt)] : [])].filter(Boolean).join(' · ');
      // «Что в заявке» в карточке — коротко; у «Претензии» / «Снова звонит» претензия — своей строкой ниже (не дважды)
      const сводкаКарточки = () => сводка(S.snap, S.подр, S.пр, { претензииЖдём: S.прЖдём, безПретензии: ['claim', 'claim_again'].includes(S.key), url: cr.url && /^https?:/.test(cr.url) ? cr.url : '' });
      function видимость() { for (const g of S.поля) if (g.when) { const w = card.querySelector('[data-afw="' + g.name + '"]'); if (w) w.hidden = !g.when(S.ввод); } }
      // вид поля (проект «2.0 — все действия»): галочки — переключателями с пояснением и меткой «будет вкл.»; выбор из 2–3 коротких —
      // сегментами, из 4–7 — списком-радио, дата и время — быстрыми днями и сеткой часов. Сам ввод (select/input с data-af) остаётся
      // источником правды: сегменты и чипы только ставят ему значение и шлют change — логика и проверки те же
      const ОПИСАНИЯ = { urgent: 'клиент ждёт мастера в течение часа', callCheck: 'время не договорено — созвонятся и договорятся', callBeforeVisit: 'мастер позвонит перед выездом',
        zakrep: 'мастер из закрепа города', fback: 'после визита нужен отзыв' };
      const isoДня = (d) => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
      const ДНИ_НЕД = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];
      // «сейчас» в городе заявки (ctx.сейчас), а не часы компьютера: оператор в Москве, клиент в Новосибирске
      const сейчасГорода = () => {
        const x = S.ctx && S.ctx.сейчас;
        if (x && /^\d{4}-\d{2}-\d{2}$/.test(x.date || '')) return { date: x.date, мин: /^\d{1,2}:\d{2}/.test(x.time || '') ? Number(x.time.split(':')[0]) * 60 + Number(x.time.split(':')[1]) : null };
        const d = new Date();
        return { date: isoДня(d), мин: d.getHours() * 60 + d.getMinutes() };
      };
      // быстрые часы: с самой ранней по регламенту (территория / пороги каталога, иначе 9:00) до 20:00 каждый час
      function часы() {
        let ранняя = (S.ctx && S.ctx.ранняя) || '';
        if (!ранняя) { try { ранняя = String(LC_ACT.НАСТРОЙКИ.пороги.ранняя || ''); } catch (_e) { ранняя = ''; } }
        const m = String(ранняя).match(/^(\d{1,2}):(\d{2})/);
        const с = m ? Number(m[1]) + (Number(m[2]) > 0 ? 1 : 0) : 9;
        const out = [];
        for (let ч = Math.max(0, Math.min(с, 20)); ч <= 20; ч++) out.push(String(ч).padStart(2, '0') + ':00');
        return out;
      }
      // для поля времени: сейчас и сегодня в городе клиента, самая ранняя (территория / спутник / регламент) и самая поздняя по регламенту
      const времяГорода = () => {
        const x = (S.ctx && S.ctx.сейчас) || null;
        let п = {};
        try { п = (LC_ACT.НАСТРОЙКИ && LC_ACT.НАСТРОЙКИ.пороги) || {}; } catch (_e) { п = {}; }
        const ранняя = (S.ctx && S.ctx.ранняя) || (S.ctx && S.ctx.спутник && п.ранняяСпутник) || п.ранняя || '';
        // data-now-at — когда сняты часы города: окно выбора времени досчитывает минуты, пока карточка открыта; data-where — «в Москве» в шапке окна
        let где = '';
        try { где = (typeof хост.вГороде === 'function' && S.ctx && S.ctx.город && хост.вГороде(String(S.ctx.город).replace(/\s*\(.*?\)\s*/g, ' ').trim())) || ''; } catch (_e) { где = ''; }
        return { 'data-now': (x && x.time) || undefined, 'data-now-at': x && S.ctx && S.ctx.now ? String(S.ctx.now) : undefined, 'data-where': где || undefined,
          'data-today': (x && x.date) || undefined, 'data-earliest': ранняя || undefined, 'data-latest': п.поздняя || undefined };
      };
      // прошедшие сегодня (по часам города) часы — неактивны; дата другая — все доступны
      function часыПрошли() {
        const д = card.querySelector('[data-af="date"]'), н = сейчасГорода();
        const сегодня = !д || !д.value || д.value === н.date;
        for (const b of (typeof card.querySelectorAll === 'function' && card.querySelectorAll('.tq-t[data-afv]')) || []) {
          const [чч0, мм0] = String(b.dataset.v).split(':').map(Number);
          const прошёл = сегодня && н.мин != null && чч0 * 60 + мм0 <= н.мин;
          b.disabled = S.busy || прошёл || b.dataset.off === '1';
          b.classList.toggle('past', прошёл);
          b.title = прошёл ? 'В городе клиента это время уже прошло' : '';
        }
      }
      function ставить(f, val) {
        const x = card.querySelector('[data-af="' + f.name + '"]');
        if (!x || x.disabled) return;
        x.value = val;
        x.dispatchEvent(new Event('change', { bubbles: true }));
      }
      // сегменты / радио / чипы — под значение поля (после change из любого места)
      function отметить(name) {
        const x = card.querySelector('[data-af="' + name + '"]');
        if (!x) return;
        for (const b of card.querySelectorAll('[data-afv="' + name + '"]')) {
          const on = String(b.dataset.v) === String(x.value);
          b.classList.toggle('on', on);
          const r = b.querySelector('input[type="radio"]'); if (r) r.checked = on;
          if (b.tagName === 'BUTTON') b.setAttribute('aria-pressed', on ? 'true' : 'false');
        }
      }
      // «будет вкл. / будет выкл.» — галочка на экране не как в CRM
      function меткаФлага(f) {
        const w = card.querySelector('[data-afw="' + f.name + '"] .chg');
        if (!w) return;
        const было = !!(S.snap && S.snap.flags && S.snap.flags[f.name]), стало = !!взять(S.ввод, f.name);
        w.textContent = было === стало ? '' : стало ? 'будет вкл.' : 'будет выкл.';
        w.hidden = было === стало;
      }
      function поле(f) {
        const v = взять(S.ввод, f.name);
        const on = (e) => {
          const t = e.target;
          const прежнее = взять(S.ввод, f.name);
          положить(S.ввод, f.name, f.type === 'check' ? t.checked : t.value);
          // поле, зависящее от этого (вид услуг — от вида работ): значение сменилось — зависимое выбрать заново
          if (Array.isArray(f.сбрасывает) && String(прежнее == null ? '' : прежнее) !== String(взять(S.ввод, f.name) == null ? '' : взять(S.ввод, f.name))) {
            for (const n of f.сбрасывает) { положить(S.ввод, n, ''); const x = card.querySelector('[data-af="' + n + '"]'); if (x) x.value = ''; отметить(n); }
          }
          if (f.type === 'check' && t.checked && f.исключает) {
            положить(S.ввод, f.исключает, false);
            const x = card.querySelector('[data-af="' + f.исключает + '"]'); if (x) x.checked = false;
            const g = S.поля.find((y) => y.name === f.исключает); if (g) меткаФлага(g);
          }
          if (f.type === 'check') меткаФлага(f); else отметить(f.name);
          if (f.type === 'date') часыПрошли();
          if (S.итог && S.итог.состояние !== 'причина') { S.итог = null; const r = card.querySelector('[data-ac="result"], [data-ac="guard"]'); if (r) r.remove(); }
          пересобрать(); обновитьПревью(); видимость();
          подготовить(false);
        };
        const выкл = !!(f.flag && S.snap && S.snap.flagsEnabled && S.snap.flagsEnabled[f.name] === false);
        const attrs = { 'data-af': f.name, oninput: on, onchange: on, disabled: выкл || S.busy };
        const скрыт = f.when ? !f.when(S.ввод) : false;
        if (f.type === 'check') {
          const было = !!(f.flag && S.snap && S.snap.flags && S.snap.flags[f.name]), разное = f.flag && было !== !!v;
          const ds = f.hint || f.ds || (f.flag ? ОПИСАНИЯ[f.name] : '') || '';
          return h('label', { class: 'ck swr' + (выкл ? ' off' : ''), 'data-afw': f.name, hidden: скрыт, title: S.key==='edit' ? ds : undefined },
            h('span', { class: 'tx' }, h('span', { class: 'nm' }, сЗаглавной(f.label) + (выкл ? ' (в CRM недоступно)' : '')),
              f.flag ? h('span', { class: 'chg', hidden: !разное }, разное ? (v ? 'будет вкл.' : 'будет выкл.') : '') : '',
              ds && S.key!=='edit' ? h('span', { class: 'ds' }, ds) : ''),
            h('input', { type: 'checkbox', class: 'sw', ...attrs, checked: !!v }));
        }
        // подпись 12 px; «*» — обязательное (подсказка при наведении); пояснение — строкой под полем
        const подпись = h('span', { class: 'lb' }, сЗаглавной(f.label), f.required ? h('span', { class: 'req', title: 'обязательное поле' }, ' *') : '');
        const пояснение = f.hint || f.ds ? h('span', { class: 'f-ds' }, f.hint || f.ds) : '';
        if (f.type === 'select') {
          // значение из переписки (ИИ) или подсказки, которого нет в списке, — показываем как есть: что видно, то и уйдёт в CRM
          const вар = вариантыПоля(f, S.snap);
          if (v != null && v !== '' && !вар.some(([val]) => String(val) === String(v))) вар.unshift([String(v), String(v)]);
          const длина = (t) => String(t == null ? '' : t).length;
          const вид = вар.length >= 2 && вар.length <= 3 && вар.every(([, t]) => длина(t) <= 22) ? 'seg' : вар.length >= 2 && вар.length <= 7 && вар.every(([, t]) => длина(t) <= 60) ? 'list' : 'select';
          const sel = h('select', { ...attrs, class: вид === 'select' ? '' : 'vh', tabindex: вид === 'select' ? undefined : '-1', 'aria-hidden': вид === 'select' ? undefined : 'true' },
            h('option', { value: '' }, f.required ? '— выберите —' : f.пусто || '— не менять —'), ...вар.map(([val, txt]) => h('option', { value: String(val), selected: v != null && String(v) === String(val) }, txt)));
          if (вид === 'select') return h('label', { class: 'f', 'data-afw': f.name, hidden: скрыт }, подпись, sel, пояснение);
          // у поля есть смысл «пусто» («не заменять — добавить новым») — это тоже вариант выбора, а не только «— не менять —» списка
          if (f.пусто && !f.required) вар.unshift(['', f.пусто]);
          const имя = 'lcz-af-' + метка + '-' + f.name;
          const выбрано = (val) => (String(val) === '' ? v == null || v === '' : v != null && String(v) === String(val));
          const пункт = ([val, txt]) => h('label', { class: (вид === 'seg' ? 'sg-o' : 'rl-o') + (выбрано(val) ? ' on' : '') + (выкл || S.busy ? ' off' : ''), 'data-afv': f.name, 'data-v': String(val) },
            h('input', { type: 'radio', name: имя, value: String(val), checked: выбрано(val), disabled: выкл || S.busy, onchange: () => ставить(f, String(val)) }),
            вид === 'list' ? h('span', { class: 'rd' }) : '', h('span', { class: 'nm' }, String(txt)));
          return h('div', { class: 'f', 'data-afw': f.name, hidden: скрыт }, подпись,
            h('div', { class: вид === 'seg' ? 'sg' : 'rl', role: 'radiogroup', 'aria-label': f.label, style: вид === 'seg' ? 'grid-template-columns:repeat(' + вар.length + ',minmax(0,1fr))' : '' }, ...вар.map(пункт)), sel, пояснение);
        }
        let input;
        if (f.type === 'textarea') input = h('textarea', { ...attrs, value: v == null ? '' : String(v), style: 'min-height:64px' });
        // время и дата — обычные поля (общий выбор времени вешается на каждое поле времени): часы города, самая ранняя и поздняя по регламенту
        else input = h('input', { type: f.type === 'number' ? 'number' : f.tel ? 'tel' : f.type || 'text', ...attrs, value: v == null ? '' : String(v), placeholder: f.placeholder || undefined,
          ...(f.type === 'time' ? времяГорода() : f.type === 'date' ? { 'data-today': времяГорода()['data-today'] } : {}) });
        if (f.type === 'date') {
          // быстрые дни: сегодня, завтра, послезавтра — по часам города заявки (ввод ниже — точная дата)
          const [г, м, д] = сейчасГорода().date.split('-').map(Number);
          const дни = [0, 1, 2].map((n) => { const d = new Date(Date.UTC(г, м - 1, д + n, 12)); const iso = d.toISOString().slice(0, 10);
            return [iso, n === 0 ? 'сегодня' : n === 1 ? 'завтра' : ДНИ_НЕД[d.getUTCDay()], iso.slice(8, 10) + '.' + iso.slice(5, 7)]; });
          return h('div', { class: 'f', 'data-afw': f.name, hidden: скрыт }, подпись,
            h('div', { class: 'dq' }, ...дни.map(([iso, w, dm]) => h('button', { type: 'button', class: 'dq-d' + (String(v || '') === iso ? ' on' : ''), 'data-afv': f.name, 'data-v': iso, disabled: выкл || S.busy, onclick: () => ставить(f, iso) },
              h('span', { class: 'w' }, w), h('span', { class: 'd' }, dm)))), input, пояснение);
        }
        if (f.type === 'time') {
          return h('div', { class: 'f', 'data-afw': f.name, hidden: скрыт }, подпись,
            h('div', { class: 'tq' }, ...часы().map((t) => h('button', { type: 'button', class: 'tq-t' + (String(v || '').slice(0, 5) === t ? ' on' : ''), 'data-afv': f.name, 'data-v': t, 'data-off': выкл ? '1' : undefined,
              'aria-pressed': String(v || '').slice(0, 5) === t ? 'true' : 'false', disabled: выкл || S.busy, onclick: () => ставить(f, t) }, t))), input, пояснение);
        }
        return h('label', { class: 'f', 'data-afw': f.name, hidden: скрыт }, подпись, input, пояснение);
      }
      // подряд идущие галочки — одним списком переключателей (как в CRM-карточке, но крупно)
      function поляБлок() {
        const out = [];
        let гр = null;
        for (const f of S.поля) {
          const el = поле(f);
          if (f.type === 'check') { if (!гр) { гр = h('div', { class: 'swl' }); out.push(гр); } гр.append(el); }
          else { гр = null; out.push(el); }
        }
        return out;
      }
      /* «Что произойдёт» (проект «Отмена»): шаги по номерам — CRM, чат города, LeadChat, клиенту; у шага, который можно не делать, —
         своя галочка справа («писать», «записать», «отправить»); снятая — шаг приглушён. Предупреждения — строкой под шагами */
      function блокПревью() {
        const p = S.план;
        if (!S.snap) return h('div', { 'data-ac': 'preview', class: 'n mut' }, S.err ? '' : 'Смотрю карточку в CRM…');
        if (!p || p.error) return h('div', { 'data-ac': 'preview', class: 'box bad' }, иконка('warn'), h('div', { class: 'c' }, (p && p.error) || 'действие не собрано'));
        const crm = Array.isArray(p.crmLines) && p.crmLines.length ? p.crmLines : Array.isArray(p.crm) ? p.crm : (p.steps || []).map((s) => s.title || s.name || описатьШаг(s));
        const tg = tgПлана(p);
        const ч = S.чат;
        const чатИмя = !tg ? '' : S.чатЖдём || !ч ? 'Чат: ищу…' : ч.нет ? 'Чат: ' + ч.нет : 'Чат «' + ч.title + '»' + (ч.reply ? ' · ответом' : '');
        const текст = S.tgText != null ? S.tgText : (tg && tg.text) || '';
        let n = 0;
        const галочка = (attrs, подпись) => h('label', { class: 'ac-sw' }, h('input', { type: 'checkbox', ...attrs }), подпись);
        const шаг = (k, выкл, справа, имя, ...kids) => h('div', { class: 'ac-r' + (выкл ? ' off' : ''), 'data-ac-step': k }, h('span', { class: 'ac-n' }, String(++n)),
          h('div', { class: 'ac-b' }, h('span', { class: 'ac-k' }, имя), ...kids), справа || '');
        const деньги = (каталог(S.key) || {}).money && !(p.warnings || []).join(' ').includes(String(каталог(S.key).money).replace(/^[^\d]+/, '')) ? '«' + имяДействия(S.key, p) + '»: ' + каталог(S.key).money : '';
        // предупреждения — по одному разу, без «⚠» в тексте и без повтора строки «Заполните»; штраф и регламент — в подсказке «почему»
        const нужно = (S.snap ? чегоНет(S.key, S.план, S.ввод, S.поля) : []).join(' ').toLowerCase();
        const виденные = new Set();
        const предупреждения = [...(p.warnings || []), деньги].filter(Boolean).map(разобратьПредупреждение).filter((w) => {
          const k = w.текст.toLowerCase();
          if (виденные.has(k) || (нужно && нужно.includes(k.replace(/^[«"]|[.»"]$/g, '').slice(0, 40)))) return false;
          виденные.add(k); return true;
        });
        const tgВыкл = !!tg && S.tgOn === false;
        return h('div', { 'data-ac': 'preview', class: 'ac-wrap' },
          h('div', { class: 'cap' }, S.key==='edit'?'Изменения':'Что произойдёт'),
          h('div', { class: 'ac-pv' },
            шаг('crm', false, '', 'CRM', h('div', { class: 'ac-v' }, crm.length ? crmСтроки(crm) : p.already ? 'уже так — CRM не трогаем' : 'ничего не меняем'),
              // вопрос кнопки CRM — что «Сделать» и есть ответ «Да»
              p.crmConfirm ? h('div', { class: 'ac-cf', title: 'Кнопка CRM спросила бы это — нажатие главной кнопки внизу и есть ответ «Да»' }, 'CRM спросит «' + p.crmConfirm + '» — ответим «Да»') : ''),
            tg ? шаг('tg', tgВыкл, галочка({ 'data-ac': 'tgon', checked: S.tgOn !== false, onchange: (e) => { S.tgOn = e.target.checked; S.tgOnТрогал = true; const r = e.target.closest('.ac-r'); if (r) r.classList.toggle('off', !e.target.checked); кнопка(); } }, 'писать'),
              чатИмя,
              ч && (ч.options || []).length > 1 ? h('select', { 'data-ac': 'chat', onchange: (e) => { const o = ч.options.find((x) => String(x.id) === e.target.value); if (o) { S.чат = { ...ч, id: o.id, title: o.title, reply: 0 }; обновитьПревью(); } } },
                ...ч.options.map((o) => h('option', { value: String(o.id), selected: String(o.id) === String(ч.id) }, o.title))) : '',
              // текст в чат — одной строкой; «править» открывает поле (оно всегда в карточке: из него «Сделать» берёт правку)
              h('div', { class: 'ac-tgr' }, h('span', { class: 'ac-tgl', 'data-ac': 'tgline', title: текст, hidden: S.tgПравка }, текст ? '«' + текст + '»' : '—'),
                h('button', { type: 'button', class: 'ac-ed', 'data-ac': 'tgedit', 'aria-expanded': S.tgПравка ? 'true' : 'false', onclick: () => править(!S.tgПравка) }, S.tgПравка ? 'свернуть' : 'править')),
              h('textarea', { 'data-ac': 'tgtext', class: 'code', value: текст, hidden: !S.tgПравка, style: 'min-height:44px',
                oninput: (e) => { S.tgText = e.target.value; const l = q('tgline'); if (l) { l.textContent = e.target.value ? '«' + e.target.value + '»' : '—'; l.title = e.target.value; } } }),
              ч && ч.заметка ? h('div', { class: 'ac-wl' }, ч.заметка) : '',
              S.key!=='edit' && (tg.fromCrm || tg.изCRM || tg.послеCRM) ? h('div', { class: 'ac-cf' }, 'Время в сообщении — точно как CRM запишет в «Переносы»') : '') : '',
            шаг('lc', !S.noteOn, галочка({ 'data-ac': 'note', checked: S.noteOn, onchange: (e) => { S.noteOn = e.target.checked; const r = e.target.closest('.ac-r'); if (r) r.classList.toggle('off', !e.target.checked); } }, 'записать'),
              'LeadChat', h('div', { class: 'ac-v' }, 'заметка в диалоге' + (p.lc && p.lc.nameNew ? '; № новой заявки — в имя клиента' : p.lc && p.lc.name ? '; № заявки — в имя клиента' : ''))),
            p.client && p.client.text ? шаг('client', !S.clientOn, галочка({ 'data-ac': 'client', checked: S.clientOn, onchange: (e) => { S.clientOn = e.target.checked; S.clientТрогал = true; const t = q('clienttext'); if (t) t.hidden = !S.clientOn; const l = q('clientline'); if (l) l.hidden = S.clientOn; const r = e.target.closest('.ac-r'); if (r) r.classList.toggle('off', !e.target.checked); кнопка(); } }, 'отправить'),
              'Клиенту в LeadChat', h('div', { class: 'ac-tgl', 'data-ac': 'clientline', hidden: S.clientOn, title: S.clientText || p.client.text }, '«' + (S.clientText || p.client.text) + '»'),
              h('textarea', { 'data-ac': 'clienttext', hidden: !S.clientOn, value: S.clientText || '', style: 'min-height:40px', oninput: (e) => { S.clientText = e.target.value; } })) : ''),
          ...предупреждения.map((w) => h('div', { class: 'ac-wl', title: w.почему || undefined }, иконка('warn'), h('span', {}, w.текст), w.почему ? h('span', { class: 'ac-why' }, ' · почему?') : '')));
      }
      // строки «В CRM:» — коротко; длинное или много шагов — полностью под «подробнее» (и в подсказке при наведении)
      function crmСтроки(crm) {
        if(S.key==='edit')return h('div',{class:'act-field-summary'},...crm.map(text=>h('div',{},text)));
        const все = crm.map((t) => String(t == null ? '' : t)), одной = все.join('; ');
        if (одной.length <= 110 && все.length <= 2) return все.map((t) => h('div', {}, t));
        return [h('div', { class: 'ac-c1', title: одной }, все[0].length > 100 ? все[0].slice(0, 98) + '…' : все[0] + (все.length > 1 ? ' + ещё ' + (все.length - 1) : '')),
          h('details', { class: 'ac-dt' }, h('summary', {}, 'подробнее'), ...все.map((t) => h('div', {}, t)))];
      }
      function править(вкл) {
        S.tgПравка = !!вкл;
        const t = q('tgtext'), l = q('tgline'), b = q('tgedit');
        if (t) t.hidden = !вкл;
        if (l) l.hidden = !!вкл;
        if (b) { b.textContent = вкл ? 'свернуть' : 'править'; b.setAttribute('aria-expanded', вкл ? 'true' : 'false'); }
        if (вкл && t) фокус(t);
      }
      function кнопка() {
        const b = q('go');
        if (!b) return;
        const нет = S.snap ? чегоНет(S.key, S.план, S.ввод, S.поля) : ['снимок не загружен'];
        const идёт = занято(cr) && !S.busy;
        // нечего делать: CRM уже так и в чат не пишем
        const пусто0 = S.план && !(S.план.steps || []).length && !(tgПлана(S.план) && S.tgOn) && !S.clientOn;
        b.disabled = S.busy || !S.snap || нет.length > 0 || идёт || !!пусто0 || (S.итог && S.итог.состояние === 'причина');
        // после неудачи (отказ, изменилась, не всё, занято) — та же кнопка, но словами «ещё раз»
        b.textContent = S.busy ? 'Делаем…' : S.итог && !S.итог.ok && /^(отказ|устарело|частично|занято)$/.test(S.итог.состояние) ? 'Сделать ещё раз' : (S.план && S.план.button) || имяДействия(S.key, S.план);
        const n = q('need');
        if (n) { n.textContent = идёт ? 'По этой заявке уже выполняется действие — дождитесь итога' : S.snap && нет.length ? 'Заполните: ' + нет.join(', ') : пусто0 && !S.busy ? 'Нечего делать: в CRM уже так, в чат не пишем' : ''; n.hidden = !n.textContent; }
        // итог на экране: удачный или со своей главной кнопкой («Отправить ещё раз», «Проверить») — нижняя кнопка тихая, главная одна
        b.classList.toggle('quiet', !!(S.итог && !S.busy && (S.итог.ok || card.querySelector('[data-ac="result"] .pri, [data-ac="guard"] .pri, [data-ac="reason"] .pri'))));
        // неактивная кнопка — почему (подсказка при наведении); активная — клавиши
        b.title = b.disabled ? (n && n.textContent) || (!S.snap ? (S.err ? 'Заявка из CRM не открылась — «Повторить» выше' : 'Жду заявку из CRM…') : S.итог && S.итог.состояние === 'причина' ? 'Выберите причину выше' : '') : 'Ctrl+Enter';
      }
      function обновитьПревью() {
        if (!мояЛи()) return;
        const old = q('preview');
        if (old) old.replaceWith(блокПревью());
        const s = q('sub'); if (s) s.textContent = подпись();
        кнопка();
        if (tgПлана(S.план) && !S.чатЖдём && (!S.чат || S.чат._k !== чатКлюч())) чатДляПлана();
      }
      /* ход действия (проект «Уведомления»: ход создания): строка на шаг — что делаем и где оно сейчас: готово / идёт / в очереди */
      function ходБлок() {
        const job = S.job;
        if (!job || !S.busy) return '';
        const шаги = [job.tg && job.tg.on && job.tg.kind === 'city' && !job.tg.reply && !job.force ? ['guard', 'Проверяю чат города'] : null,
          ...job.steps.map((s, i) => ['crm' + i, 'CRM: ' + s.title]), job.tg && job.tg.on ? ['tg', 'Telegram' + (job.tg.title ? ': «' + job.tg.title + '»' : '')] : null, ['lc', 'LeadChat: заметка']].filter(Boolean);
        const сейчас = job.этап === 'crm' ? 'crm' + job.шаг : job.этап;
        const i = Math.max(0, шаги.findIndex(([k]) => k === сейчас));
        // CRM думает долго: с 10 с — сколько ждём на этом шаге, с минуты — что ждём до 2 мин и сами не повторяем
        const сек = job.этап === 'crm' && job.этапС ? Math.floor((Date.now() - job.этапС) / 1000) : 0;
        return h('div', { class: 'ac-run', 'data-ac': 'run' },
          h('div', { class: 'ac-run-h' }, h('b', {}, имяДействия(S.key, S.план)), h('span', { class: 'ac-st info' }, 'выполняю…')),
          h('ol', { class: 'ac-run-l' }, ...шаги.map(([k, t], n) => h('li', { class: n < i ? 'done' : n === i ? 'now' : 'wait' },
            h('span', { class: 'tx' }, t, n === i && сек >= 10 ? h('span', { class: 'ac-sec', 'data-ac': 'elapsed' }, ' · ' + сек + ' с') : ''),
            h('span', { class: 'ac-st' }, n < i ? 'готово' : n === i ? 'идёт…' : 'в очереди')))),
          сек >= 60 ? h('div', { class: 'ac-wl', 'data-ac': 'slow' }, 'CRM отвечает долго — жду до 2 мин, повторно не нажимаю') : '',
          h('div', { class: 'ac-foot' }, 'Можно перейти в другой диалог — итог придёт уведомлением.'));
      }
      function итогБокс() {
        const и = S.итог;
        if (!и) return '';
        const место = h('div', { class: 'n' });
        if (и.состояние === 'перекрытие' || и.состояние === 'не проверено') {
          return h('div', { class: 'box warn', 'data-ac': 'guard' }, иконка('warn'), h('div', { class: 'c', style: 'width:100%' },
            h('div', {}, и.text),
            ...((и.guard && и.guard.list) || []).slice(-3).map((m) => h('div', { class: 'n' }, LC_TG.просьбаКратко(m))),
            // пока окно на экране, чат перечитывается раз в 20 с (только чтение): ответили филиалу — говорим, но сами не отправляем
            и.отвечена ? h('div', { class: 'n ok', 'data-ac': 'answered' }, 'Просьба отвечена — можно «' + ((q('go') && q('go').textContent) || 'Сделать') + '»') : '',
            // те же надписи, что в прежней карточке «по заявке»; «Назад» — не путать с действием «Отмена»
            h('div', { class: 'row res-a' },
              h('button', { class: 'sm pri', onclick: () => сделать(false) }, 'Проверить снова'),
              h('button', { class: 'sm', onclick: () => сделать(true) }, и.состояние === 'перекрытие' ? 'Всё равно сделать' : 'Сделать без проверки'),
              h('button', { class: 'sm', onclick: () => { S.итог = null; нарисовать(); } }, 'Назад'))));
        }
        if (и.состояние === 'уже') {
          // тот же ключ уже сделан (10 мин): когда — заголовком; ещё раз — только новым нажатием оператора
          const когда = и.запись && и.запись.at ? чч(и.запись.at) : '';
          return h('div', { class: 'box res warn', 'data-ac': 'result' },
            h('div', { class: 'res-h' }, h('span', { class: 'res-i' }, иконка('check')),
              h('div', { class: 'c' }, h('div', { class: 'res-t' }, 'Уже сделано' + (когда ? ' в ' + когда : '')), h('div', { class: 'n mut' }, база(cr.dir) + ' № ' + cr.id))),
            h('div', { class: 'res-l' }, ...(и.строки || [и.text]).map((t) => строкаИтога(t, 'warn'))),
            h('div', { class: 'row res-a' }, h('button', { class: 'sm', 'data-ac': 'again', onclick: () => сделать(false, null, { повтор: true }) }, 'Сделать ещё раз')));
        }
        if (и.состояние === 'причина') {
          let выбор = '';
          // 2.2.9: CRM просит ещё и пустые обязательные поля — выбор здесь же (варианты CRM); «Сохранить причину» — с ними (заполнить)
          const поля = и.поля ? выборПолей(и, () => {}) : null;
          const готовы = () => !и.поля || и.поля.every((f) => String((и.выбор || {})[f.name] == null ? '' : и.выбор[f.name]).trim());
          const обновить = () => { const b = q('reasongo'); if (b) { b.disabled = !выбор || !готовы(); b.title = !выбор ? 'Сначала выберите причину' : !готовы() ? 'Сначала выберите поля выше' : ''; } };
          if (поля) { поля.блок.addEventListener('change', обновить); поля.блок.addEventListener('input', обновить); }
          return h('div', { class: 'box warn', 'data-ac': 'reason' }, иконка('warn'), h('div', { class: 'c', style: 'width:100%' },
            h('div', {}, h('b', {}, 'CRM просит причину. '), поля ? 'Выберите причину и поля ниже, затем «Сохранить причину».' : 'Выберите и нажмите «Сохранить причину».'),
            h('div', { class: 'opts' }, ...(и.options || []).map((o) => {
              const val = typeof o === 'object' ? String(o.value) : String(o), txt = typeof o === 'object' ? o.text || o.title || val : String(o);
              return h('label', { class: 'opt' }, h('input', { type: 'radio', name: 'lcz-act-reason', value: val, onchange: (e) => { выбор = e.target.value; обновить(); } }), h('span', { class: 'nm' }, txt));
            })),
            поля ? поля.блок : '',
            h('div', { class: 'row res-a' }, h('button', { class: 'sm pri', 'data-ac': 'reasongo', disabled: true, title: 'Сначала выберите причину', onclick: () => {
              if (!выбор || !готовы()) return;
              const заполнить = и.поля ? { ...(и.выбрано || {}), ...Object.fromEntries(и.поля.map((f) => [f.name, String(и.выбор[f.name]).trim()])) } : null;
              сделать(false, { причина: выбор, сШага: и.шаг || 0, ...(заполнить ? { заполнить } : {}) });
            } }, 'Сохранить причину'),
              h('button', { class: 'sm', onclick: () => { S.итог = null; нарисовать(); } }, 'Назад'))));
        }
        const ok = и.ok, вид = ok ? 'ok' : и.состояние === 'отказ' ? 'bad' : 'warn';
        // 2.2.5: пусты обязательные поля карточки CRM — выбор здесь же; «Заполнить и повторить» — продолжение задания с шага отказа
        const выбор = и.поля && S.job ? выборПолей(и, (заполнить) => сделать(false, { заполнить, сШага: и.шаг || 0 })) : null;
        const все = S.job ? действияИтога(S.job, и, место, выбор && выбор.кнопка) : [];
        const у = (k) => все.filter((x) => x.у === k).map((x) => x.el);
        const низ = все.filter((x) => x.у === 'низ').sort((a, b) => Number(!!b.pri) - Number(!!a.pri)).map((x) => x.el);
        const строки = строкиПоказа(и), виды = видыИтога(и);
        // итог: иконка и заголовок; строки — каждая своим цветом; у строки чата и заметки — свои кнопки; внизу — одна главная
        return h('div', { class: 'box res ' + вид, 'data-ac': 'result' },
          h('div', { class: 'res-h' }, h('span', { class: 'res-i' }, иконка(ok ? 'check' : 'warn')),
            h('div', { class: 'c' }, h('div', { class: 'res-t' }, ok ? 'Сделано: ' + имяДействия(S.key, S.план) : ЗАГОЛОВКИ_ИТОГА[и.состояние] || 'Проверьте'),
              h('div', { class: 'n mut' }, база(cr.dir) + ' № ' + cr.id + ' · ' + чч(Date.now())))),
          h('div', { class: 'res-l' }, ...строки.map((t, i) => строкаИтога(t, виды[i], i === и.tgСтрока ? у('tg') : i === и.заметкаСтрока ? у('note') : null))), выбор ? выбор.блок : '', место,
          низ.length ? h('div', { class: 'row res-a' }, ...низ) : '');
      }
      const ЗАГОЛОВКИ_ИТОГА = { частично: 'Сделано не всё', отказ: 'Не сделано', занято: 'Уже выполняется — дождитесь итога', устарело: 'Заявка изменилась — ничего не сделано',
        неясно: 'Не знаю, прошло ли — проверьте', нет: 'Не сделано' };
      // главная кнопка итога: «Проверить» / «Отправить ещё раз» / «Проверить снова»; после неудачи — «Сделать ещё раз»
      function кнопкаИтога() {
        const box = q('result') || q('guard') || q('reason');
        if (!box || !S.итог) return null;
        const pri = [...box.querySelectorAll('button.pri')].find((b) => !b.disabled);
        if (pri) return pri;
        if (!S.итог.ok && S.итог.состояние !== 'уже') { const g = q('go'); if (g && !g.disabled) return g; }
        return null;
      }
      function нарисовать() {
        if (!мояЛи()) return;
        // фокус переживает перерисовку: то же поле / та же кнопка
        const ф = (() => { try { const a = card.getRootNode().activeElement; if (!a || !card.contains(a)) return ''; const k = a.getAttribute('data-af') ? '[data-af="' + a.getAttribute('data-af') + '"]' : a.getAttribute('data-ac') ? '[data-ac="' + a.getAttribute('data-ac') + '"]' : ''; return k; } catch (_e) { return ''; } })();
        const досупно = S.snap ? доступные(S.snap, S.ctx) : [];
        const ключи = [...new Set(досупно.map((x) => x.key))].filter((k) => k !== S.key);
        const другое = ключи.length ? h('select', { class: 'ac-other', 'data-ac': 'other', title: 'Другое действие по этой заявке', 'aria-label': 'Другое действие', disabled: S.busy,
          onchange: (e) => { if (e.target.value) карточка(conv, cr, e.target.value, { ...переносимыйВвод(S.ввод) }, источник); } },
        h('option', { value: '' }, 'Другое действие ▾'), ...ключи.map((k) => h('option', { value: k }, (каталог(k) || {}).label || (досупно.find((x) => x.key === k) || {}).label || k))) : '';
        const естьВСетке = !S.snap || досупно.some((x) => x.key === S.key);
        const опасное = опасная(S.key);                                     // отмены и «не берём» — красная кнопка
        const отмена = /^cancel_(kc|branch)$/.test(S.key);
        // «подробнее» в «Что в заявке» раскрыто — остаётся раскрытым после перерисовки
        if (рисовал && мояЛи()) { const d0 = q('info-more'); S.инфоОткрыто = !!(d0 && d0.open); }
        const инфо = S.snap ? сводкаКарточки() : '';
        if (инфо && S.инфоОткрыто) { const d1 = инфо.querySelector('[data-ac="info-more"]'); if (d1) d1.open = true; }
        рисовал = true;
        card.replaceChildren(
          // шапка (проект «Отмена»): иконка в цветном квадрате, название, под ним заявка · статус · визит · «обновлено N с назад»
          h('div', { class: 'hd', 'data-act-card': метка, 'data-act-key':S.key }, h('span', { class: 'ac-ic' + (опасное ? ' bad' : '') }, иконка(отмена ? 'stop' : иконкаПлитки({ key: S.key, ввод: S.ввод }), 18)),
            h('div', { class: 'ttl' }, h('div', { class: 'tt' }, отмена ? 'Отмена' : имяДействия(S.key, S.план)), h('div', { class: 'sub', 'data-ac': 'sub' }, подпись())),
            h('button', { class: 'ib', 'aria-label': 'Закрыть', title: 'Закрыть (Esc)', onclick: () => card.classList.remove('show') }, иконка('close'))),
          источник.почему ? h('div', { class: 'ac-hint' }, h('b', {}, 'Предлагаю: '), источник.почему) : '',
          // 2.1: что сейчас в заявке (только показ) и, у претензий, № и статус претензии в CRM
          инфо,
          S.snap && ['claim', 'claim_again'].includes(S.key) ? строкаПретензии(S.пр, S.прЖдём) : '',
          переключательОтмены(досупно),
          другое,
          S.err ? h('div', { class: 'box bad' }, иконка('warn'), h('div', { class: 'c' }, h('div', {}, S.err), h('div', { class: 'row', style: 'gap:6px' }, h('button', { class: 'sm', onclick: () => загрузить(true) }, 'Повторить')))) : '',
          S.snap && !естьВСетке && !S.busy && !S.итог ? h('div', { class: 'ac-line warn' }, иконка('warn'), h('span', {}, 'Сейчас это действие для заявки недоступно: ' + ((S.план && S.план.недоступно) || почему(S.key)) + '. Выберите другое действие.')) : '',
          ...(S.snap ? поляБлок() : []),
          блокПревью(),
          ходБлок(),
          итогБокс(),
          h('div', { class: 'n warn ac-need', 'data-ac': 'need', hidden: true }),
          h('div', { class: 'row acf' }, h('button', { class: 'sq', onclick: async () => { if (источник.seen) await хост.markSeen(conv, источник.seen); card.classList.remove('show'); } }, 'Не нужно'),
            h('button', { class: 'go' + (опасное ? ' bad' : ''), 'data-ac': 'go', title: 'Ctrl+Enter', onclick: () => сделать(false) }, 'Сделать')));
        кнопка();
        часыПрошли();
        if (ф) фокус(card.querySelector(ф));
        // идёт или пришёл итог — его видно без прокрутки
        if (S.busy || S.итог) { const x = q('run') || q('result') || q('guard') || q('reason'); if (x && typeof x.scrollIntoView === 'function') { try { x.scrollIntoView({ block: 'nearest' }); } catch (_e) { /* не страшно */ } } }
        if (tgПлана(S.план) && !S.чатЖдём && (!S.чат || S.чат._k !== чатКлюч())) чатДляПлана();
      }
      // почему действия нет для этой заявки: каталог (LC_ACT.почемуНет — с правилами регламента), иначе по статусу и кнопкам
      const почему = (k) => { try { if (есть() && typeof LC_ACT.почемуНет === 'function') { const x = LC_ACT.почемуНет(k, S.snap, S.ctx); if (x) return String(x); } } catch (_e) { /* по снимку */ } return S.snap ? почемуНет(k, S.snap) : ''; };
      /* «Чья отмена» (проект «Отмена»): две большие карточки-варианта — «Отмена КЦ» (клиент передумал · −60 ₽) и «Отмена Филиал»
         (город не смог). Недоступный вариант — серым, причина — прямо в карточке (тип «Гарантия» — только КЦ) */
      function переключательОтмены(досупно) {
        if (!/^cancel_(kc|branch)$/.test(S.key) || S.итог) return '';
        const есть = (k) => досупно.some((x) => x.key === k);
        const вар = [['cancel_kc', 'Отмена КЦ', 'клиент передумал, помощь не нужна · −60 ₽'], ['cancel_branch', 'Отмена Филиал', 'город не смог: опоздание, перенос городом, закреп']];
        return h('div', { class: 'f ac-who' }, h('span', { class: 'lb' }, 'Чья отмена'),
          h('div', { class: 'ac-opts', role: 'radiogroup', 'aria-label': 'Чья отмена' },
            ...вар.map(([k, t, пояс]) => {
              const можно = k === S.key || есть(k), нет = можно ? '' : почему(k);
              return h('button', { type: 'button', role: 'radio', class: 'ac-opt' + (k === S.key ? ' on' : '') + (можно ? '' : ' off'), 'data-ac': 'cancel-' + k,
                'aria-checked': k === S.key ? 'true' : 'false', 'aria-pressed': k === S.key ? 'true' : 'false', disabled: S.busy || !можно,
                onclick: () => { if (k !== S.key) карточка(conv, cr, k, { ...переносимыйВвод(S.ввод) }, источник); } },
              h('b', {}, t), h('span', { class: 'ds' }, нет ? 'нельзя: ' + нет : пояс));
            })));
      }
      // в другое действие переносим то, что имеет смысл (дата/время/суть), а не галочки прежнего
      const переносимыйВвод = (v) => { const o = {}; for (const k of ['date', 'time', 'summary', 'text']) if (v[k]) o[k] = v[k]; return o; };
      async function загрузить(свежий) {
        S.err = ''; нарисовать();
        const s = await снимок(cr, свежий);
        if (!мояЛи()) return;
        if (!s.ok) { S.err = 'Не удалось открыть заявку в CRM: ' + s.error; S.snap = null; нарисовать(); return; }
        S.snap = s.card; S.snapAt = s.at || Date.now();
        S.подр = s.details || S.подр;
        S.прЖдём = нужныПретензии() && !S.пр;
        пересобрать();
        S.ввод = начальныйВвод(S.key, S.snap, S.ввод, S.поля, S.ctx);
        пересобрать();
        нарисовать();
        // клавиатура: первое пустое обязательное поле, всё заполнено — «Сделать» (Ctrl+Enter)
        // курсор кодом — никогда на кнопку записи (случайный пробел / Enter нажал бы её): поле или сама карточка, «Сделать» — Ctrl+Enter или щелчок
        if (!S.фокусДан) { S.фокусДан = true; if (фокусСвободен()) фокус(первоеПустое() || card); }
        // претензия: № и статус из CRM — не задерживая карточку (только чтение)
        if (S.прЖдём) претензии(cr).then((пр) => { S.пр = пр; S.прЖдём = false; обновитьСводку(); if (мояЛи() && !S.busy) { пересобрать(); обновитьПревью(); } }).catch(() => { S.прЖдём = false; обновитьСводку(); });
        // сведения (согласование, телефон для СД / «стыка») и чтение для превью (PE) — после первого рисунка
        const было = S.поля.map((f) => f.name).join('|');
        S.доп = await сведения(conv, cr, S.key, S.snap);
        if (!мояЛи()) return;
        пересобрать();
        if (S.поля.map((f) => f.name).join('|') !== было && !S.busy) нарисовать(); else обновитьПревью();
        await подготовить(true);
      }
      function первоеПустое() {
        for (const f of S.поля) {
          if (!f.required || (f.when && !f.when(S.ввод)) || !пусто(взять(S.ввод, f.name))) continue;
          const w = card.querySelector('[data-afw="' + f.name + '"]');
          if (!w || w.hidden) continue;
          const x = w.querySelector('input:not([type="hidden"]):not(.vh):not(:disabled), textarea:not(:disabled), select:not(.vh):not(:disabled)');
          if (x) return x;
        }
        return null;
      }
      // пока «ждёт ответа просьба филиала» на экране — раз в 20 с смотрим чат (только чтение); ответили — говорим и ставим фокус на «Сделать»
      function следитьЗаПросьбой(и) {
        const chat = S.job && S.job.tg && S.job.tg.chat;
        if (!chat || и.состояние !== 'перекрытие' || typeof хост.просьбыВЧате !== 'function') return;
        const живо = () => мояЛи() && S.итог === и && !S.busy && card.classList.contains('show') && !!q('guard');
        const тик = async () => {
          if (!живо()) return;
          let g = null;
          try { g = await хост.просьбыВЧате(chat); } catch (_e) { g = null; }
          if (!живо()) return;
          if (Array.isArray(g) && !g.length) { и.отвечена = true; нарисовать(); if (фокусСвободен()) фокус(card); return; }
          setTimeout(тик, 20e3);
        };
        setTimeout(тик, 20e3);
      }
      async function сделать(force, продолжение, опц) {
        if (S.busy) return;
        // правки оператора на экране — в задание (текст в чат); дальше — сразу «Делаем…»: второй щелчок ничего не шлёт
        const ta = q('tgtext'); if (ta && tgПлана(S.план) && ta.value !== String(tgПлана(S.план).text || '')) S.tgText = ta.value;
        S.busy = true;
        const прежнее = продолжение && S.job ? S.job : null, прежнийИтог = S.итог;
        S.итог = null;
        нарисовать();
        try {
          пересобрать();
          if (!продолжение && чегоНет(S.key, S.план, S.ввод, S.поля).length) return;
          if (tgПлана(S.план) && S.tgOn !== false && (S.чатЖдём || !S.чат || S.чат._k !== чатКлюч() || S.чат.тгНет)) { S.чат = null; S.чатЖдём = false; await чатДляПлана(); }
          const з = { conv, cr, key: S.key, ввод: JSON.parse(JSON.stringify(S.ввод)), план: S.план, snap: S.snap, поля: S.поля, чат: S.чат || null, tgText: S.tgText, tgOn: S.tgOn,
            noteOn: S.noteOn, clientOn: S.clientOn, clientText: S.clientText, источник, force: !!force, наВиду, повтор: !!(опц && опц.повтор) };
          const s = await собрать(з);
          if (s.ошибка) { S.итог = { ok: false, состояние: 'отказ', text: s.ошибка, строки: [s.ошибка] }; return; }
          S.job = s.job;
          // «Сохранить причину» — продолжение того же задания с шага, где CRM спросила причину (второй клик оператора);
          // 2.2.5 «Заполнить и повторить» — так же, с выбором оператора для пустых обязательных полей (заполнить)
          if (продолжение) {
            Object.assign(S.job, { сШага: продолжение.сШага, причина: продолжение.причина, заполнить: продолжение.заполнить || null, проверено: true, crmDone: !!(прежнее && прежнее.crmDone) });
            S.job.sig0 = (прежнийИтог && прежнийИтог.после && прежнийИтог.после.sig) || (прежнее && прежнее.sig0) || S.job.sig0;
          }
          S.job.нарисовать = () => { if (наВиду()) { const r = q('run'); const n = ходБлок(); if (r && n) r.replaceWith(n); } };
          нарисовать();
          // секунды ожидания CRM на текущем шаге — раз в секунду, пока идёт
          const job0 = S.job, тикХода = () => { if (!S.busy || S.job !== job0 || !мояЛи()) return; job0.нарисовать(); setTimeout(тикХода, 1000); };
          setTimeout(тикХода, 1000);
          const итог = await исполнить({ ...з, job: S.job });
          if (!мояЛи()) return;
          S.итог = итог;
          if (итог.состояние === 'устарело' && итог.после) {
            // превью — по новому состоянию: оператор видит, что изменилось, и решает заново
            S.snap = итог.после; S.snapAt = Date.now(); S.чат = null;
            пересобрать();
            S.ввод = начальныйВвод(S.key, S.snap, S.ввод, S.поля, S.ctx);
          }
          // изменилась карточка клиента (адрес, номер, имя), заявка та же: перечитать её (подготовка действия), иначе следующее
          // «Сделать» снова уйдёт со старой подписью карточки клиента и снова «устарело»
          if (итог.состояние === 'устарело' && !итог.после) await подготовить(true);
          if (итог.ok && источник.seen) хост.markSeen(conv, источник.seen).catch(() => {});
          // успех закрывается сам через 8 с — но не с предупреждением «⚠ …» и не пока карточку держат (мышь, фокус)
          if (итог.ok && !естьПредупреждение(итог.строки)) автоЗакрыть(() => мояЛи() && S.итог === итог && card.classList.contains('show'), 8000);
          if (итог.состояние === 'перекрытие') следитьЗаПросьбой(итог);
        } finally {
          S.busy = false;
          if (мояЛи()) { пересобрать(); нарисовать(); if (S.итог && фокусСвободен()) фокус(card); }
        }
      }
      // «снимок N с назад» — живой, пока карточка на экране
      const тик = () => { if (!мояЛи() || !card.classList.contains('show')) return; const s = q('sub'); if (s) s.textContent = подпись(); setTimeout(тик, 15000); };
      хост.показатьКарточку();
      card.scrollTop = 0;                                               // новое действие — с начала карточки
      if (typeof card.setAttribute === 'function' && !card.getAttribute('tabindex')) card.setAttribute('tabindex', '-1');   // фокус на карточке — Esc / Ctrl+Enter работают, кнопки сами не нажимаются
      // клавиатура: Esc — закрыть (не во время «Делаем…»), Ctrl/Cmd+Enter — «Сделать», только если она активна
      card.onkeydown = (e) => {
        if (!мояЛи()) return;
        if (e.key === 'Escape' && !S.busy) { e.preventDefault(); card.classList.remove('show'); }
        else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); if (e.repeat) return; const b = q('go'); if (b && !b.disabled && !S.busy) b.click(); }
      };
      setTimeout(тик, 15000);
      await загрузить(false);
      return true;
    }

    /* «Другое действие ▾» для прежней карточки «по заявке» (ИИ мог ошибиться): список доступных — по снимку CRM */
    function другоеДействие(conv, cr, r, seen) {
      if (!есть() || !cr || !cr.id || !cr.dir) return '';
      // из ответа ИИ переносим только суть и время — остальное оператор выберет в карточке
      const ввод = () => { const o = {}; for (const k of ['date', 'time', 'summary']) if (r && r[k]) o[k] = r[k]; return o; };
      const sel = h('select', { class: 'ac-other', 'data-act-other': '1', title: 'Другое действие',
        onchange: (e) => { const k = e.target.value; if (!k) return; карточка(conv, cr, k, ввод(), { from: 'ai', seen }); } },
      h('option', { value: '' }, 'Другое действие ▾'));
      снимок(cr, false).then((s) => {
        if (!s.ok || (!sel.isConnected && !sel.parentNode)) return;
        const все = доступные(s.card, ctxДля(conv, cr, 'ai', s.card));
        const ключи = [...new Set(все.map((x) => x.key))];
        sel.replaceChildren(h('option', { value: '' }, 'Другое действие ▾'), ...ключи.map((k) => h('option', { value: k }, (каталог(k) || {}).label || (все.find((x) => x.key === k) || {}).label || k)));
      }).catch(() => {});
      return sel;
    }

    /* ИИ разобрал сообщение клиента по созданной заявке (намерения 1.20: позвоните, срочно, адрес, другое направление):
       каталог (LC_ACT.подсказка 'ai') предлагает действие — открываем его карточку, уже заполненную; запись — по кнопке в ней.
       Каталог ничего не предложил (или CRM не прочиталась) — false: покажется прежняя карточка «по заявке» */
    async function поНамерению(conv, cr, r, seen) {
      if (!есть() || typeof LC_ACT.подсказка !== 'function' || !cr || !cr.id || !cr.dir || !r) return false;
      const s = await снимок(cr, false);
      if (!s.ok) return false;
      // пока читалась CRM, оператор ушёл в другой диалог или открыл панель — false: подсказка останется для A (ДОПИСКИ)
      if (чужойДиалог(conv) || (хост.panel && хост.panel.classList && хост.panel.classList.contains('open'))) return false;
      const ruleAction = r.rule_action === true && r.намерение === 'jivo_claim_reply';
      const ctx = ctxДля(conv, cr, ruleAction ? 'rule' : 'ai', s.card);
      let п = null;
      try { п = LC_ACT.подсказка(ruleAction ? 'jivo_claim_rule' : 'ai', s.card, { ...ctx, ...r, intent: r.намерение || r.intent }); } catch (_e) { п = null; }
      if (!п || !п.key || !каталог(п.key)) return false;
      return (await карточка(conv, cr, п.key, { ...(п.ввод || {}), ...(r.summary && !(п.ввод || {}).summary ? { summary: r.summary } : {}) }, { from: ruleAction ? 'rule' : 'ai', seen, почему: п.почему || '', авто: true })) !== false;
    }

    /* для подсказок (watch-act): снимок + план + чат — что покажет превью, и готово ли к «Сделать» без карточки */
    async function превью(conv, cr, key, ввод, источник) {
      const s = await снимок(cr, false);
      if (!s.ok) return { ok: false, error: s.error };
      const ист = typeof источник === 'string' ? { from: источник } : источник || { from: 'watch' };
      const доп = await сведения(conv, cr, key, s.card);
      let ctx = ctxДля(conv, cr, ист, s.card, доп);
      const поля = поляДля(key, s.card, ctx);
      const v = начальныйВвод(key, s.card, ввод, поля, ctx);
      const d = каталог(key);
      if (d && typeof d.подготовить === 'function') { try { ctx = { ...ctx, ...((await d.подготовить(s.card, v, хост)) || {}) }; } catch (_e) { /* превью без дочитки — «Открыть» */ } }
      const p = план(key, s.card, v, ctx);
      const нет = чегоНет(key, p, v, поля);
      const tg = tgПлана(p);
      const ч = tg ? await куда(conv, cr, tg, s.card) : null;
      const crm = (p && (p.crmLines && p.crmLines.length ? p.crmLines : p.crm)) || ((p && p.steps) || []).map((x) => x.title || x.name || описатьШаг(x));
      const кратко = [crm.join(', '), tg && tg.on && tg.text ? 'в чат: «' + маска(tg.text) + '»' : ''].filter(Boolean).join(' → ');
      return { ok: true, snap: s.card, ввод: v, ctx, план: p, чат: ч, готово: !нет.length && !(p && p.error), чегоНет: нет, кратко };
    }

    /* ---------- прежние действия — через этот бегунок ---------- */
    /* карточка «по заявке» и «Сделать» в уведомлении (content.js планПоЗаявке + правки оператора): шаги CRM — прежними операциями фона,
       порядок прежний (адрес → перенос → отмена → претензия → комментарий → чат); добавлены замок, журнал, «не знаю» без повтора, заметка */
    async function поПлану(conv, cr, p, o) {
      const опц = o || {};
      let адресВКомментарий = '', домВЧат = '', tg = p.tg;
      const steps = [];
      const ошибка = (что) => (r) => что + ((r && r.error) || 'ошибка');
      if (p.адрес && p.addrOn) steps.push({ title: 'адрес в карточке клиента', run: async () => {
        // адрес уже сменили прошлым нажатием (дальше был сбой) — CRM второй раз не спрашиваем
        if (p.адресИтог && p.адресИтог.для === p.адрес) return { ok: true, ...p.адресИтог.c };
        return send({ kind: 'lcz-crm', op: 'customerAddress', args: { dir: cr.dir, id: cr.id, addr: p.адрес.addr } });
      }, ошибка: (c) => 'адрес в карточке клиента CRM не сменился: ' + ((c && c.error) || 'ошибка') + (c && c.url ? ' (' + c.url + ')' : '') + ' — в CRM больше ничего не делали',
      журнал: (c) => ((c.changed || []).length ? 'адрес в карточке клиента CRM сменён' : 'в карточке клиента CRM уже этот адрес'),
      итог: (c) => {
        const строка = c.line || p.адрес.line;
        if ((c.changed || []).length) {
          p.адресИтог = { для: p.адрес, c: { ...c, warnings: [] } };
          адресВКомментарий = 'Адрес изменён клиентом ' + p.адрес.hm + ': ' + строка;
          if (p.адрес.tg && p.intent !== 'дополнение') домВЧат = p.адрес.tg;
        }
        return [(c.changed || []).length ? 'в карточке клиента CRM: ' + c.changed.join(', ') + ' — ' + строка : 'в карточке клиента CRM уже этот адрес', ...(c.warnings || [])];
      } });
      if (p.move) steps.push({ title: 'перенос', run: () => send({ kind: 'lcz-crm', op: 'reschedule', args: { dir: cr.dir, id: cr.id, date: p.date || '', time: p.time || '', reason: 'Клиент' } }),
        ошибка: ошибка('в CRM не перенесено: '), итог: (m) => { if (m.lastChange && p.tgAuto !== false) tg = LC_TG.followText({ id: cr.id, intent: 'перенос', crmLine: m.lastChange }); return 'в CRM перенесено' + (m.now ? ' (' + String(m.now).trim() + ')' : ''); } });
      // 2.2.9: отмена — ядром действий (offscreen: cancelKc → crmact); «Заполнить и повторить» — выбор оператора уходит в ядро (заполнить);
      // что ядро поставило само («Дальний выезд» «Нет», город «КЦ») — в итог
      if (p.cancel) steps.push({ title: p.by === 'branch' ? '«Отмена Филиал»' : '«Отмена КЦ»',
        run: (_sig, доп) => send({ kind: 'lcz-crm', op: 'cancelKc', args: { dir: cr.dir, id: cr.id, comment: p.crm || '', service: p.service || '', by: p.by || 'kc', ...(доп && доп.заполнить ? { заполнить: доп.заполнить } : {}) } }),
        ошибка: ошибка('в CRM не отменено: '), итог: (c) => [c.already ? 'в CRM уже «' + c.status + '»' : 'в CRM «' + (c.status || (p.by === 'branch' ? 'Отмена Филиал' : 'Отмена КЦ')) + '»', ...(c.заметки || [])] });
      // претензия по заявке уже есть (CRM.createClaim: already — создана в CRM / другим диалогом): не «создана» — дальше не идём,
      // «Новая претензия» в чат не пишем; слова клиента — «Снова звонит»
      if (p.claim) steps.push({ title: 'претензия', run: async () => { const c = await send({ kind: 'lcz-crm', op: 'claim', args: { dir: cr.dir, id: cr.id, typeNo: p.claimType, comment: p.claimComment } });
        return c && c.ok && c.already ? { ok: false, already: true, error: 'по заявке уже есть претензия' + (c.claimId ? ' №' + c.claimId : '') + ' — новую не создавал, комментарий не записан; слова клиента — «Снова звонит»' } : c; },
        ошибка: ошибка('претензия не создана: '), итог: (c) => (c.already ? 'претензия уже была' : 'претензия создана' + (c.claimId ? ' №' + c.claimId : '')) + (c.typed ? ', тип: ' + c.type : '') + (c.warn ? ' (' + c.warn + ')' : '') });
      // строка о смене адреса — часть действия «Сменить адрес» (идёт и при снятой «Дописать в комментарий»)
      const вКомментарий = () => [p.crm && !p.cancel && p.crmOn !== false ? p.crm : '', адресВКомментарий].filter(Boolean).join('\n');
      if ((p.crm && !p.cancel && p.crmOn !== false) || (p.адрес && p.addrOn)) steps.push({ title: 'комментарий', run: async () => {
        const t = вКомментарий();
        if (!t) return { ok: true, пусто: true };
        return send({ kind: 'lcz-crm', op: 'comments', args: { dir: cr.dir, id: cr.id, change: { addComment: t } } });
      }, ошибка: ошибка('в комментарий не дописалось: '), итог: (r) => (r.пусто ? '' : 'в комментарий дописано') });
      const чатНужен = !!(tg && p.tgOn !== false);
      if (!steps.length && !чатНужен) return { ok: true, text: 'ничего не выбрано', guard: null };
      const куда0 = чатНужен ? await хост.чатПоЗаявке(conv, cr, p) : null;
      // чат не нашёлся — потому что Telegram не ответил? (спрашиваем заново: память групп могла остаться с прошлой минуты)
      const тгНет = !!(чатНужен && !(куда0 && куда0.chat) && p.chat !== 'claims' && !(await чаты(true)).ok);
      const job = {
        ключ: 'act:' + cr.dir + ':' + cr.id + ':по:' + p.intent + ':' + хэш(канон({ d: p.move ? p.date : '', t: p.move ? p.time : '', c: !!p.cancel, by: p.by || '', cl: !!p.claim, ty: p.claimType || '',
          tg: чатНужен ? p.tg : '', crm: p.crmOn !== false ? p.crm || '' : '', a: p.адрес && p.addrOn ? p.адрес.line : '' })),
        act: 'по:' + p.intent, dir: cr.dir, id: String(cr.id), conv, cr, title: опц.title || ЗАГОЛОВКИ[p.intent] || 'Действие по заявке', sig0: '', snap: null, цель: null, steps,
        tg: чатНужен ? { on: true, kind: p.chat === 'claims' ? 'claims' : 'city', chat: куда0 && куда0.chat, title: (куда0 && куда0.title) || '', reply: (куда0 && куда0.reply) || 0,
          город: cr.city || '?', нет: p.chat === 'claims' ? 'чат претензий не найден' : тгНет ? 'группы Telegram не получены' : '', тгНет, пусто: 'в чат не писали: нет нового времени',
          text: () => {
            let t = tg;
            if (p.intent === 'перенос' && /"…|…"/.test(t || '')) return '';             // строка-заготовка без нового времени в чат не уходит
            if (домВЧат && t && !t.includes(домВЧат)) t = t + '\n' + домВЧат;
            return t;
          },
          послеОтправки: (r) => запомнитьСообщение({ key: p.intent === 'претензия' && p.claim ? 'claim' : p.intent === 'где_мастер' ? 'where' : '', conv, cr, чат: { id: куда0 && куда0.chat, title: куда0 && куда0.title } }, r) } : null,
        lc: { note: true, name: false, noteText: опц.title || ЗАГОЛОВКИ[p.intent] || '', client: null }, client: null, force: !!p.force, наВиду: опц.наВиду || null, тихо: !!опц.тихо, источник: { from: 'по заявке' },
        сШага: 0, причина: null, проверено: false, повтор: false, послеCRM: null, кнопкиТостом: true,
      };
      const r = await исполнить({ cr, job });
      // карточка «по заявке» показывает итог строкой, как раньше
      return { ok: !!r.ok, text: (r.строки || [r.text]).filter(Boolean).join(' · ') || 'ничего не выбрано', guard: r.guard || null, итог: r };
    }
    const ЗАГОЛОВКИ = { перенос: 'Перенос', отмена: 'Отмена', где_мастер: 'Где мастер?', претензия: 'Претензия', дополнение: 'Дополнение к заявке', отдел_авито: 'Отдел Авито' };

    /* «Вернуть в «Ожидает»» из формы создания (регламент: отменённую — вернуть, а не создавать новую). Защита от перекрытия — ДО CRM */
    async function вернутьВОжидает(o) {
      const ref = o.ref, cr = { dir: ref.dir, id: ref.id, url: ref.url || '', city: o.city || '' };
      const c = await чаты();
      const m = c.ok ? LC_TG.matchChat(c.chats, ref.dir, o.city || '') : null;
      const job = {
        ключ: 'act:' + ref.dir + ':' + ref.id + ':await_from_cancel:' + хэш(канон({ d: o.date || '', t: o.time || '' })), act: 'await_from_cancel', dir: ref.dir, id: String(ref.id), conv: o.conv, cr,
        title: 'Вернуть в «Ожидает»', sig0: '', snap: null, цель: { statusCode: 1 },
        // «Проверить» после «не знаю»: строка «Переносов» в чат — только с этим временем (иначе — старая строка карточки)
        цельЧата: o.date || o.time ? { ...(o.date ? { visitDate: o.date } : {}), ...(o.time ? { visitTime: String(o.time).slice(0, 5) } : {}) } : null,
        steps: [{ title: 'вернуть в «Ожидает»' + (o.date || o.time ? ' и перенести' : ''), run: () => send({ kind: 'lcz-crm', op: 'returnToAwait', args: { dir: ref.dir, id: ref.id, date: o.date || '', time: o.time || '' } }),
          ошибка: (r) => 'Не вернулось: ' + ((r && r.error) || 'ошибка'),
          итог: (r) => '№ ' + ref.id + ' — снова «' + (r.status || 'Ожидает') + '»' + (r.moved ? ', время перенесено' : r.moveError ? ' (время не перенеслось: ' + r.moveError + ')' : '') }],
        tg: { on: true, kind: 'city', chat: m && m.id, title: (m && m.title) || '', reply: 0, город: o.city || '?', нет: c.ok ? '' : 'группы Telegram не получены', тгНет: !c.ok,
          text: ({ lastChange }) => ref.id + ' вернул в ожидает' + (lastChange ? '\n' + ref.id + ' ' + lastChange : ''), послеОтправки: () => {} },
        lc: { note: true, name: true, noteText: 'Вернул в «Ожидает»', client: null }, client: o.client || null, force: !!o.force, наВиду: o.наВиду || null, тихо: !!o.тихо,
        источник: { from: 'форма' }, сШага: 0, причина: null, проверено: false, повтор: false, послеCRM: o.послеCRM || null, кнопкиТостом: true,
      };
      const r = await исполнить({ cr, job });
      return { ...r, text: (r.строки || [r.text]).filter(Boolean).join(' · ') };
    }

    /* «№ не удобно принять по закрепу…» после создания (регламент рег:1073) — в чат ЕЁ города; просьба филиала — окно с выбором */
    const текстЗакрепа = (id) => {
      if (есть() && LC_ACT.текст) {
        const t = LC_ACT.текст.zakrep_not || LC_ACT.текст.закреп || LC_ACT.текст.неПоЗакрепу;
        try { const x = typeof t === 'function' ? t({ id }) : typeof t === 'string' ? t.replace(/<ID>|\{id\}/g, id) : ''; if (x) return String(x); } catch (_e) { /* по умолчанию */ }
      }
      return id + ' не удобно принять по закрепу, ждет в ближайшее время';
    };
    async function неПоЗакрепу(o) {
      const c = await чаты();
      const m = c.ok ? LC_TG.matchChat(c.chats, o.dir, o.city || '') : null;
      const согл = (o.согл || [])[0];
      const chat = (согл && согл.chat) || (m && m.id), title = (согл && согл.title) || (m && m.title) || '';
      const text = текстЗакрепа(o.id);
      if (!chat) return { ok: false, text: '«' + text + '» не отправлено: чат города не найден — напишите вручную' };
      const cr = { dir: o.dir, id: o.id, city: o.city || '' };
      const сделатьЗ = (force) => ({ cr, job: { ключ: 'act:' + o.dir + ':' + o.id + ':zakrep_not:' + хэш(text), act: 'zakrep_not', dir: o.dir, id: String(o.id), conv: o.conv, cr, title: 'Не по закрепу',
        sig0: '', snap: null, цель: null, steps: [], tg: { on: true, kind: 'city', chat, title, reply: 0, город: o.city || '', text, послеОтправки: () => {} },
        lc: { note: false, name: false, client: null }, client: null, force, тихо: true, наВиду: null, источник: { from: 'создание' }, сШага: 0, причина: null, проверено: false, повтор: false, кнопкиТостом: true } });
      const r = await исполнить(сделатьЗ(false));
      if (r.guard) {
        отложено(text, title, r.guard, () => исполнить(сделатьЗ(false)), () => исполнить(сделатьЗ(true)));
        return { ok: false, text: '«' + text + '» ждёт: ' + (r.guard.nocheck ? 'чат города не проверился на просьбы филиала' : 'в чате города просьба филиала без ответа') + ' — решите в уведомлении «' + (r.guard.nocheck ? 'Чат не проверен' : 'Просьба филиала ждёт ответа') + '»' };
      }
      return r.ok ? { ok: true, text: 'В чат города: ' + text } : { ok: false, text: '«не по закрепу» не отправилось: ' + (r.text || 'ошибка') };
    }
    // не отправили из-за просьбы филиала (или чат не проверился) — окно: проверить и отправить / всё равно отправить
    function отложено(text, title, g, проверить0, всёРавно) {
      const d = h('div', { class: 'tst-d warn' }, g.nocheck ? 'Не отправил «' + text.slice(0, 80) + '»: чат не проверился на просьбы филиала (программа Telegram не на связи).' : 'Не отправил «' + text.slice(0, 80) + '», чтобы не перекрыть просьбу филиала' + ((g.list || []).length ? ':' : '.'));
      const el = хост.тост({ kind: 'warn', label: g.nocheck ? 'Чат не проверен' : 'Просьба филиала ждёт ответа', title: title ? '«' + title + '»' : 'Чат города',
        lines: [d, ...(g.list || []).slice(-3).map((m) => h('div', { class: 'tst-q' }, LC_TG.просьбаКратко(m)))],
        actions: [h('button', { class: 'sm pri', onclick: (e) => пуск(e.currentTarget, проверить0) }, 'Проверить и отправить'),
          h('button', { class: 'sm', onclick: (e) => пуск(e.currentTarget, всёРавно) }, 'Всё равно отправить'),
          h('button', { class: 'sm', onclick: () => el.remove() }, 'Не отправлять')] });
      async function пуск(b, fn) {
        const кнопки = [...el.querySelectorAll('.tst-a button')];
        if (кнопки.some((x) => x.disabled)) return;
        кнопки.forEach((x) => { x.disabled = true; });
        const было = b.textContent; b.textContent = 'Отправляем…';
        const r = await fn();
        if (r && r.ok) { d.className = 'tst-d ok'; d.textContent = '✓ Отправлено: ' + text.slice(0, 80); const a = el.querySelector('.tst-a'); if (a) a.remove(); setTimeout(() => el.remove(), 15000); return; }
        кнопки.forEach((x) => { x.disabled = false; }); b.textContent = было;
        d.textContent = r && r.guard ? (r.guard.nocheck ? 'Чат всё ещё не проверяется — можно «Всё равно отправить»' : 'Просьба филиала всё ещё без ответа — ответьте ей в Telegram') : (r && r.text) || 'Не отправилось';
      }
      return el;
    }

    return { готов: () => !!есть(), сетка, карточка, исполнить, превью, снимок, занято, поПлану, вернутьВОжидает, неПоЗакрепу, другоеДействие, поНамерению, проверить, ключЖурнала, подписаться,
      журнал: () => журнал((all) => ({ значение: { ...all } })) };
  }

  return { создать, маска, хэш, канон, совпадает, разница, норм, взять, положить, ОШИБКИ, ПОЛЯ, ПРИЧИНЫ };
})();
if (typeof module !== 'undefined' && module.exports) module.exports = LC_ACT_UI;
