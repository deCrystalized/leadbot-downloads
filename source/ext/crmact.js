/* 1.20 «Все действия с заявкой» — ядро CRM (offscreen: DOMParser и cookie CRM здесь).
   snap — снимок карточки заявки БЕЗ личных данных: статус, кнопки, галочки, время визита, число переносов.
   act — одно действие ТЕМ ЖЕ СПОСОБОМ, что кнопка CRM (crm_actions_live.md, раздел 0):
     A — вся #customerRequestForm + скрытый флаг saveAndClose; B — вся форма на адрес ссылки с data-confirm (как yii.handleAction);
     C — AJAX update?id=N отдельными полями; M — форма модалки; G — переход по ссылке.
   Порядок в act: замок по заявке → свежий GET → журнал ключей → sig превью → «уже сделано?» → кнопка в карточке → тело
   (от исходной формы отличаются только свои поля) → запись без повтора (2 мин без ответа — «не знаю, прошло ли») →
   разбор ответа (редирект / ошибки формы / запрос причины / вход) → GET и сверка. Ответ CRM сам по себе успехом не считается.

   Рецепты (recipe) и params:
     fields    {set:{urgent, callCheck, callBeforeVisit, zakrep, fback, farRide: bool, type: 10|20|30, city: id}, date?, time?, reason?,
                addComment?, addService?, addPartner?} — «Сохранить» (в модерации с expect:{statusCode:[1]} — «Сохранить → Ожидает»)
     move      {date?:'ГГГГ-ММ-ДД', time?:'ЧЧ:ММ', reason:'Клиент'|'Диспетчер'|'Директор', addComment?, addService?}
     flag      {code: 2|10|11|20|21|22|25|26|30|60 или [2, 21] (первый, чья кнопка есть), changeType?: status_change_type,
                server?: ключ сервера (код 30), date?, time?, reason? (код 22 — «Ожидает» с временем), addComment?, addService?, addPartner?}
     link      {link:'take'|'release'|'toNotTaken', addPartner?, changeType?}
     goto      {} — «Отправить в город» (promote-moderation-to-city)
     comments  {addComment?, addService?, addPartner?, comments?, comments_service?, partner_comment?} — «Сохранить комментарий»
     noanswer  {} — «Не отвечает»
     modalBranchComment {text};  modalFeedback {link?, type: 601|600, comment?}
     claim     {typeNo?, comment?, category?: 590|591|592|593, skipIfExists?} — проверенный createClaim (GET create-claim, как в 1.18)
     awaitFromCancel {} / backToWork {} — 2.2.9: как кнопка CRM (B) — POST всей формы на адрес ссылки cancel-transaction(&state=1);
                CRM не принимает POST (405) — переходом по ссылке (GET), как в 1.18
     city      {cityId} — город после создания: есть в карточке «Сохранить город» (#actSaveCity) — как она (C: AJAX update?id=N
                {_csrf, city_id} → {result, errorMessage}); нет кнопки (Ожидает, В пути, На уточнении) — «Сохранить» всей формой (A)
     worktype  {applId, subId?} — вид работ и вид услуг: «Сохранить» всей формы (A); список видов услуг для нового вида работ —
                как форма CRM (GET update?id=N&_get_appltype=1&get_subappltypes=1…), вид услуг — только из него
   snap({dir, id, details?, claims?, subFor?}) — только чтение: details — «Что в заявке» (комментарии, «Переносы», адрес — с маской
     телефонов; списки городов и видов работ карточки), claims — претензии по заявке с № и статусом (список ОКК), subFor — виды услуг
     для вида работ. Карточка (card) от этого не меняется: личного в ней по-прежнему нет.
     у всех: expect?: {statusCode, held, flags, type, visitDate, visitTime, changesCountPlus} — цель плана: statusCode заменяет табличную,
       остальное сверяется ВДОБАВОК к цели рецепта (expect можно и рядом с params — так шлёт экран).
     2.2.5 у рецептов с формой (fields, move, flag, link, city «Сохранить», worktype): заполнить?: {'CustomerRequest[…]': значение} (рядом
       с params или внутри) — оператор выбрал в уведомлении; подставляем ТОЛЬКО в пустые обязательные поля, select — только вариант формы.
       Отказ «пусто» отдаёт поля: [{name, label, kind: 'select'|'text', options: [{value, text}]}] — что выбрать. Завершающее действие
       (отмены, «Не оформлена», «Не создана», «Отказались») с пустым «Дальний выезд» — «Нет» само; в итоге заполнено[] и заметки[].
   Словарь плана (actions.js) тоже понимаем — нормПарамы(): flag {flag:'cancel_kc', value, set, comment, partner, service, reason},
     link/goto {href:'take-to-work'…}, fields {flags, fields:{'CustomerRequest[…]'}, type, service, save, cityId}, comments {append|replace},
     modalBranchComment {comment}, второй клик причины — status_change_type.
   act({…, check:true}) — ничего не пишет: перечитать карточку и сказать, стоит ли уже цель («Проверить» после «не знаю, прошло ли»).
   2.2.9 (жалоба 14.10 «не работает ни одна отмена»): ответ CRM с ошибкой у поля (Yii .has-error / .is-invalid) — «пусто» с полями
     (что выбрать), а не общий «отказ»; при любой неудаче — crmReply (что ответила CRM: код, страница, ошибки у полей, надписи — без
     личных данных); завершающие — пустой город «39» сам; отмены — цель «Отмена КЦ»/«Отмена» и «Отмена Филиала»/«Готов ОФ»;
     «устарело» — только если изменилось важное действию (before — снимок превью от экрана); второй шаг причины — обычной отправкой.
   Журнал «никогда дважды» — по ключу задания + рецепту шага (экран шлёт один key на все шаги задания).
   held.mine: true — видно, что у вас (имя в навигации CRM или «Взять» из расширения), false — у другого, null — не видно:
     тогда «Взять»/«Вернуть» не нажимаем. */

const CRM_ACT = (() => {
  const NOTES = typeof LC_REQUEST_NOTES !== 'undefined' ? LC_REQUEST_NOTES : require('./request-notes.js');
  const C = typeof CRM !== 'undefined' ? CRM : require('./crm.js');
  const { BASES, fetchDoc, serializeForm, formErrors, setVal } = C._внутр;
  const ИМЯ = { kp: 'КП', mnc: 'МНЧ', bt: 'БТ' };
  const ПУТЬ = '/admin/domain/customer-request/';
  const AJAX = { 'X-Requested-With': 'XMLHttpRequest' };

  // сроки и часы — тесты подменяют (поддельные таймеры)
  const Н = {
    срокЗаписи: 120000,                 // запись без ответа 2 мин — «не знаю, прошло ли», повтор не шлём
    памятьНеизвестных: 10 * 60e3,       // столько помним «не знаю» по ключу и висящий запрос по заявке
    памятьСделанных: 2 * 60e3,          // повтор неидемпотентного (отметка «не отвечает», претензия) — «уже сделано»
    попыткиПереноса: 3, паузаПереноса: 3000,
    таймер: (fn, мс) => setTimeout(fn, мс),
    сброс: (t) => clearTimeout(t),
    пауза: (мс) => new Promise((r) => setTimeout(r, мс)),
    сейчас: () => Date.now(),
  };

  const СТАТУСЫ = { 1: 'Ожидает', 4: 'В пути', 8: 'В работе', 9: 'В работе СД', 2: 'Модерация', 3: 'На уточнении', 20: 'Не оформлена', 48: 'Не создана',
    32: 'Отмена', 1001: 'Отмена КЦ', 1002: 'Отмена Филиала', 1003: 'Отмена Регионал', 64: 'Отказ', 128: 'Готов', 1020: 'Готов ОФ', 65: 'Склад' };
  const ОТМЕНЫ = [32, 1001, 1002, 1003];
  // длинные названия раньше коротких: «В работе СД» — не «В работе», «Отмена КЦ» — не «Отмена»
  const НАЗВАНИЯ = [['в работе сд', 9], ['в работе', 8], ['в пути', 4], ['ожидает', 1], ['модерация', 2], ['на уточнении', 3], ['не оформлена', 20],
    ['не создана', 48], ['отмена кц', 1001], ['отмена филиала', 1002], ['отмена филиал', 1002], ['отмена регионал', 1003], ['отмена', 32],
    ['отказ', 64], ['готов оф', 1020], ['готово', 128], ['готов', 128], ['склад', 65]].sort((a, b) => b[0].length - a[0].length);
  const норм = (s) => String(s || '').replace(/\r\n?/g, '\n').toLowerCase().replace(/ё/g, 'е').replace(/[ \t ]+/g, ' ').trim();
  function кодСтатуса(текст) {
    const t = норм(текст).replace(/\s+/g, ' ');
    for (const [n, код] of НАЗВАНИЯ) if (t.startsWith(n) && !/[a-zа-я0-9]/.test(t[n.length] || '')) return код;
    return 0;
  }

  const КНОПКИ = ['take', 'release', 'claim', 'toNotTaken', 'awaitFromCancel', 'backToWork', 'promote', 'noAnswer', 'saveComment', 'feedback',
    'branchComment', 'saveCity', 's1', 's2', 's10', 's11', 's20', 's21', 's22', 's25', 's26', 's30', 's60'];
  const НАДПИСЬ = { take: 'Взять в работу', release: 'Вернуть', claim: 'Претензия', toNotTaken: 'Перевести в "Не оформлена"', awaitFromCancel: 'Вернуть в «Ожидает»',
    backToWork: 'Вернуть в работу', promote: 'Отправить в город', noAnswer: 'Не отвечает', saveComment: 'Сохранить комментарий', feedback: 'Негативный отзыв', saveCity: 'Сохранить город',
    branchComment: 'Добавить комментарий', s1: 'Сохранить', s2: 'Не оформлена', s10: 'Отмена КЦ', s11: 'Отмена Филиал', s20: 'На уточнение', s21: 'Не оформлена',
    s22: 'Ожидает', s25: 'Вернуть заявку в статус «Ожидает»', s26: 'Не создана', s30: 'Отправить заявку', s60: 'Отказались' };
  const ФЛАГИ = ['urgent', 'callCheck', 'callBeforeVisit', 'zakrep', 'fback', 'farRide'];
  const ПОЛЕ = { urgent: 'CustomerRequest[is_urgent]', callCheck: 'CustomerRequest[is_need_call_check]', callBeforeVisit: 'CustomerRequest[is_need_call_before_visit]',
    zakrep: 'CustomerRequest[is_zakrep]', fback: 'CustomerRequest[is_req_fback]', farRide: 'CustomerRequest[is_far_ride]', type: 'CustomerRequest[type]', city: 'CustomerRequest[city_id]' };
  const ГАЛОЧКА = { urgent: 'Срочная', callCheck: 'Прозвон', callBeforeVisit: 'Прозвон перед выездом', zakrep: 'Закреп', fback: 'Отзыв', farRide: 'Дальний выезд', type: 'Тип', city: 'Город' };
  const КОММ = { addComment: 'CustomerRequest[comments]', addService: 'CustomerRequest[comments_service]', addPartner: 'CustomerRequest[partner_comment]' };
  /* 2.2.5 (13.10, жалоба: «В карточке не заполнено «Дальний выезд» — CRM не даст сохранить», не отменить заявку). Заявка уходит
     из работы — «Не оформлена» (20), «Не создана» (48), «Отказ» (64), любая отмена: «Дальний выезд» ей не нужен — пустой ставим «Нет» сами.
     Остальное («Вид работ», имя…) не угадываем: варианты из формы — оператору (поля), он выбирает в уведомлении */
  const ДАЛЬНИЙ = ПОЛЕ.farRide;
  const ИЗ_РАБОТЫ = new Set([20, 48, 64, ...ОТМЕНЫ]);
  const изРаботы = (коды) => Array.isArray(коды) && коды.length > 0 && коды.every((s) => ИЗ_РАБОТЫ.has(Number(s)));
  // город, тип, непрофильная — их проверяет yiiActiveForm (и у кнопок через yii.handleAction); подпись — когда у поля нет <label>
  const ОБЯЗ_YII = { 'CustomerRequest[city_id]': 'Город', 'CustomerRequest[type]': 'Тип', 'CustomerRequest[is_noncore]': 'Непрофильная' };
  /* 2.2.9: заявка уходит из работы, а «Город» пустой — ставим «39» (в CRM «КЦ» / «Город не указан»): так делает сама CRM у «На уточнение»
     (saveAndClose 20: пустой город → 39). Для отменённой / неоформленной заявки город смысла не меняет; варианта 39 в списке нет — не трогаем */
  const ГОРОД_НЕ_УКАЗАН = '39';
  /* 2.2.9: после «Отмена КЦ» в шапке «Отмена КЦ» (1001), бывает и просто «Отмена» (32); после «Отмена Филиал» — «Отмена Филиала» (1002),
     и той же надписью CRM пишет «Готов ОФ» (1020, различаем только по кнопкам). Для проверки «отменено» это одна цель */
  const ТОЖЕ_ОТМЕНА = { 1001: [1001, 32], 1002: [1002, 1020, 32] };
  const сОтменами = (коды) => [...new Set((коды || []).flatMap((x) => ТОЖЕ_ОТМЕНА[x] || [x]))];

  /* Флаги saveAndClose (раздел 9.1 живого файла): имя/значение скрытого поля, кнопка, цель по статусу.
     уже — статусы, в которых действие не нужно (любая отмена — отменять второй раз не надо) */
  const ФЛАГ = {
    2: { name: 'not_taken', value: '1', target: [20] },
    10: { name: 'cancel_kc', value: '1', target: [1001], уже: ОТМЕНЫ, статус1: true },
    11: { name: 'cancel_branch', value: '2', target: [1002], уже: ОТМЕНЫ, статус1: true },
    20: { name: 'on_precheck', value: '1', target: [3], город39: true },
    21: { name: 'precheck_to_nottaken', value: '1', target: [20], статус: '20' },
    22: { name: 'precheck_to_await', value: '1', target: [1], статус: '1', время: true },
    25: { name: 'not_taken_to_await', value: '1', target: [1], статус1: true, время: true },
    26: { name: 'to_not_created', value: '1', target: [48] },
    30: { name: 'transfer_request', value: null, target: null },
    60: { name: 'rejected_by_customer', value: '1', target: [20] },
  };
  const ССЫЛКА = { take: 'take-to-work', release: 'release-from-work', claim: 'create-claim', toNotTaken: 'cancel-to-not-taken', promote: 'promote-moderation-to-city' };
  // словарь плана: имя скрытого поля → код кнопки, адрес ссылки → вид, имя поля формы → ключ галочки
  const КОД_ПО_ФЛАГУ = Object.fromEntries(Object.entries(ФЛАГ).map(([к, ф]) => [ф.name, Number(к)]));
  const ССЫЛКА_ПО_АДРЕСУ = Object.fromEntries(Object.entries(ССЫЛКА).map(([к, а]) => [а, к]));
  const КЛЮЧ_ПОЛЯ = Object.fromEntries(Object.entries(ПОЛЕ).map(([к, n]) => [n, к]));
  const СЕРВЕР_БАЗЫ = { 'automatic.mt': 'mnc', 'automatic.kp': 'kp', 'automatic.bt': 'bt' };
  const ПРИЧИНЫ_ВРЕМЕНИ = ['Клиент', 'Диспетчер', 'Директор'];
  const НЕИДЕМПОТЕНТНЫЕ = new Set(['noanswer', 'claim', 'modalFeedback', 'modalBranchComment', 'comments']);
  // по карточке не видно, сделано ли (отметка, претензия, модалки) — «Проверить» честно говорит «не знаю»; комментарий виден
  const НЕ_ПРОВЕРИТЬ = new Set(['noanswer', 'claim', 'modalFeedback', 'modalBranchComment']);

  /* Тексты ошибок — раздел 6 проекта, слово в слово */
  const ТЕКСТ = {
    сессия: (база) => 'Сессия в CRM ' + база + ' истекла — откройте сайт лид-центра ' + база + ', войдите и нажмите ещё раз. Ничего не сделано.',
    устарело: (было, стало) => (было ? 'Пока вы смотрели, заявка изменилась: было «' + было + '», стало «' + стало + '».'
      : 'Пока вы смотрели, заявка изменилась (сейчас «' + стало + '»).') + ' Ничего не сделано — посмотрите и нажмите ещё раз.',
    нетКнопки: (id, кнопка, статус) => 'В CRM у заявки № ' + id + ' нет кнопки «' + кнопка + '» (статус «' + статус + '») — сейчас это действие недоступно.',
    отказ: (ошибки) => 'CRM не сохранила: ' + String(ошибки).replace(/[.\s]+$/, '') + '. В чат не писали.',
    неПроверилось: (что) => 'CRM ответила, но в карточке по-прежнему «' + что + '» — проверьте заявку в CRM. В чат не писали.',
    нетОтвета: 'CRM не ответила за 2 минуты — не знаю, прошло ли. Повторно не отправляю.',
    занято: (id) => 'По заявке № ' + id + ' уже выполняется действие (в этой или другой вкладке) — дождитесь итога.',
    причина: (варианты) => 'CRM просит выбрать причину: ' + варианты + '. Выберите и нажмите «Сохранить причину».',
    пусто: 'В карточке не заполнено «Город / Тип / Непрофильная» — CRM не даст сохранить. Заполните в CRM.',
    пустоПоля: (поля) => 'В карточке не заполнено «' + поля.join(', ') + '» — CRM не даст сохранить. Заполните в CRM.',
    запретОбработки: (id, з) => 'CRM не даёт обработать заявку № ' + id + (з.почему ? ': ' + з.почему : '') + (з.id ? ' (№ ' + з.id + ') — сначала обработайте её' : '') + '. Ничего не сделано.',
    неожиданно: (кратко) => 'CRM ответила не так, как ожидалось (' + кратко + '). Ничего больше не делаю — сделайте это действие в CRM.',
    токен: 'CRM не приняла запись: «Не удалось проверить переданные данные» (HTTP 400) — так бывает, если в CRM перезашли или сессия сменилась. Откройте CRM, обновите страницу (F5) и нажмите ещё раз. Ничего не сделано.',
    // 2.2.9: CRM вернула форму с ошибкой у поля (Yii: .has-error / .is-invalid + текст) — её слова и что выбрать
    отказПоля: (слова, поля) => 'CRM не сохранила: ' + String(слова).replace(/[.\s]+$/, '') + '. Выберите «' + поля.join('», «') + '» и нажмите «Заполнить и повторить» (или заполните в CRM). В чат не писали.',
    раньшеБезОтвета: (когда) => 'Прошлая попытка (в ' + когда + ') осталась без ответа CRM — не знаю, прошло ли. Повторно не отправляю: проверьте заявку в CRM.',
    // «Проверить» (act с check) — без записи
    неСделано: (сейчас) => 'В CRM этого нет: в карточке «' + сейчас + '». Можно сделать ещё раз.',
    ещёИдёт: (сейчас) => 'В CRM этого пока нет (в карточке «' + сейчас + '»), а прошлый запрос ещё не ответил — подождите пару минут и проверьте снова.',
    неПроверить: 'По карточке не видно, сделано ли это действие (отметка или претензия могла уйти) — проверьте в CRM. Повторно не отправляю.',
  };

  /* ---------- параметры плана ----------
     План (actions.js) и экран говорят своими словами — приводим к словам рецептов. Непонятное не угадываем: ошибка до записи */
  const числоЛи = (v) => v !== undefined && v !== null && v !== '' && /^\d+$/.test(String(v));
  function нормОжидание(e) {
    if (!e || typeof e !== 'object') return null;
    const o = { ...e };
    if (o.statusCode !== undefined && o.statusCode !== null) o.statusCode = [].concat(o.statusCode).map(Number).filter(Boolean);
    if (Array.isArray(o.statusCode) && !o.statusCode.length) delete o.statusCode;
    return Object.keys(o).length ? o : null;
  }
  function нормПарамы(recipe, p0, e0) {
    const p = { ...(p0 || {}) };
    const expect = нормОжидание(e0 || p.expect);
    delete p.expect;
    if (expect) p.expect = expect;
    const ош = [];
    // второй клик после «CRM просит причину» (экран шлёт status_change_type)
    if (p.status_change_type !== undefined && p.changeType === undefined) p.changeType = p.status_change_type;
    delete p.status_change_type;
    // reason: число — причина смены статуса, «Клиент/Диспетчер/Директор» — причина переноса
    if (p.reason !== undefined && recipe !== 'move' && recipe !== 'fields') {
      if (числоЛи(p.reason)) { if (p.changeType === undefined) p.changeType = String(p.reason); delete p.reason; }
      else if (!ПРИЧИНЫ_ВРЕМЕНИ.includes(p.reason)) ош.push('непонятная причина «' + String(p.reason).slice(0, 40) + '»');
    }
    const вКомментарии = () => {
      for (const [из, в] of [['comment', 'addComment'], ['partner', 'addPartner'], ['service', 'addService']]) {
        if (p[из] === undefined) continue;
        if (p[в] === undefined && String(p[из]).trim()) p[в] = String(p[из]);
        delete p[из];
      }
    };
    if (recipe === 'flag' && p.flag !== undefined) {
      const код = КОД_ПО_ФЛАГУ[p.flag];
      if (!код) ош.push('неизвестная кнопка «' + p.flag + '»');
      else {
        const ф = ФЛАГ[код];
        if (код === 30) { if (p.server === undefined) p.server = p.value; }
        else if (p.value !== undefined && String(p.value) !== ф.value) ош.push(p.flag + '=' + p.value + ' (CRM ставит ' + ф.value + ')');
        // статус, который saveAndClose ставит сам (21 → 20, 22 → 1): другой — это ошибка плана
        const st = p.set && p.set['CustomerRequest[status]'];
        if (st !== undefined && String(st) !== String(ф.статус || st)) ош.push('статус ' + st + ' для ' + p.flag);
        const лишние = Object.keys(p.set || {}).filter((n) => n !== 'CustomerRequest[status]');
        if (лишние.length) ош.push('лишние поля ' + лишние.join(', '));
        if (p.code === undefined) p.code = код;
      }
      delete p.flag; delete p.value; delete p.set;
    }
    if (recipe === 'flag') вКомментарии();
    if ((recipe === 'link' || recipe === 'goto') && p.href !== undefined) {
      const вид = ССЫЛКА_ПО_АДРЕСУ[String(p.href).replace(/^.*\//, '').replace(/\?.*$/, '')];
      if (recipe === 'goto' && вид !== 'promote') ош.push('переход «' + p.href + '» не знаю');
      if (recipe === 'link') { if (!вид || вид === 'promote' || вид === 'claim') ош.push('ссылку «' + p.href + '» не знаю'); else if (p.link === undefined) p.link = вид; }
      delete p.href;
    }
    if (recipe === 'link') вКомментарии();
    if (recipe === 'fields') {
      const set = { ...(p.set || {}) };
      const положить = (k, v, откуда) => { if (set[k] !== undefined && String(set[k]) !== String(v)) ош.push('«' + (ГАЛОЧКА[k] || k) + '» задана по-разному (' + откуда + ')'); else set[k] = v; };
      for (const [k, v] of Object.entries(p.flags || {})) положить(k, v === true || v === 1 || v === '1', 'flags');
      if (p.type !== undefined) положить('type', Number(p.type), 'type');
      if (p.cityId !== undefined && p.cityId !== '' && p.cityId !== null) положить('city', String(p.cityId), 'cityId');
      for (const [n, v] of Object.entries(p.fields || {})) {
        const k = КЛЮЧ_ПОЛЯ[n];
        // «Гарантия» → «Обычная» рецепт ставит сам, как скрипт CRM
        if (n === 'CustomerRequest[is_noncore]' && String(v) === '0' && Number(set.type || p.type) === 30) continue;
        if (!k) { ош.push('поле ' + n + ' не меняю'); continue; }
        положить(k, k === 'type' ? Number(v) : k === 'city' ? String(v) : String(v) === '1', 'fields');
      }
      if (p.service !== undefined) { if (p.addService === undefined && String(p.service).trim()) p.addService = String(p.service); delete p.service; }
      if (Object.keys(set).length) p.set = set;
      delete p.flags; delete p.fields; delete p.type; delete p.cityId; delete p.save;
    }
    if (recipe === 'comments') {
      const из = { comment: ['addComment', 'comments'], service: ['addService', 'comments_service'], partner: ['addPartner', 'partner_comment'] };
      for (const [k, v] of Object.entries(p.append || {})) { if (!из[k]) ош.push('не знаю поле «' + k + '»'); else if (p[из[k][0]] === undefined) p[из[k][0]] = String(v); }
      for (const [k, v] of Object.entries(p.replace || {})) { if (!из[k]) ош.push('не знаю поле «' + k + '»'); else if (p[из[k][1]] === undefined) p[из[k][1]] = String(v); }
      delete p.append; delete p.replace;
    }
    if (recipe === 'modalBranchComment' && p.text === undefined && p.comment !== undefined) { p.text = p.comment; delete p.comment; }
    return { p, ошибка: ош.join('; ') };
  }
  // цель плана сверх цели рецепта — только то, что видно в снимке (счётчики «+N» сверяем по снимку до действия)
  function ожиданиеСбылось(e, c, до) {
    if (!e) return true;
    if (e.statusCode && !e.statusCode.includes(c.statusCode)) return false;
    if (e.held === 'mine' && !(c.held.yes && c.held.mine !== false)) return false;
    if (e.held === false && c.held.yes) return false;
    for (const [k, v] of Object.entries(e.flags || {})) if (ФЛАГИ.includes(k) && c.flags[k] !== !!v) return false;
    if (e.type !== undefined && c.type !== Number(e.type)) return false;
    if (e.visitDate && c.visitDate !== e.visitDate) return false;
    if (e.visitTime && c.visitTime !== e.visitTime) return false;
    if (e.changesCountPlus && до && c.changesCount < до.changesCount + Number(e.changesCountPlus)) return false;
    // город, вид работ и услуг — номера из select'ов карточки (строкой)
    for (const k of ['cityId', 'applId', 'subId']) if (e[k] !== undefined && e[k] !== null && String(c[k] == null ? '' : c[k]) !== String(e[k])) return false;
    return true;
  }
  // что сейчас в карточке по пунктам цели — для «CRM ответила, но в карточке по-прежнему «…»»
  function описатьКарточку(e, c) {
    const ч = [];
    if (!e || e.statusCode) ч.push(c.statusName || '?');
    if (e && e.held !== undefined) ч.push(c.held.yes ? (c.held.mine === false ? 'в работе у другого сотрудника' : 'в работе') : 'свободна');
    for (const k of Object.keys((e && e.flags) || {})) if (ФЛАГИ.includes(k)) ч.push(ГАЛОЧКА[k] + ': ' + (c.flags[k] ? 'стоит' : 'нет'));
    if (e && e.type !== undefined) ч.push('Тип: ' + (c.type || '—'));
    if (e && (e.visitDate || e.visitTime)) ч.push(c.visitDate + ' ' + c.visitTime);
    if (e && e.changesCountPlus) ч.push('переносов ' + c.changesCount);
    if (e && e.cityId !== undefined) ч.push('город ' + (c.cityName || c.cityId || '—'));
    if (e && e.applId !== undefined) ч.push('вид работ ' + (c.applName || c.applId || '—'));
    if (e && e.subId !== undefined) ч.push('вид услуг ' + (c.subName || c.subId || '—'));
    return ч.join(', ') || c.statusName || '?';
  }

  /* ---------- снимок карточки ---------- */

  const ссылкаЗаявки = (doc, путь, id, сУсловием) => [...doc.querySelectorAll('a[href*="' + путь + '?id="]')]
    .find((a) => { const h = a.getAttribute('href') || ''; return new RegExp('[?&]id=' + id + '(?!\\d)').test(h) && (!сУсловием || сУсловием(h)); }) || null;
  const поле = (form, n) => { const e = form && form.elements[n]; if (!e) return null; return e.tagName ? e : ([...e].find((x) => x.type === 'checkbox') || e[e.length - 1]); };
  const значение = (e) => (e ? String(e.value ?? '') : '');

  function статусИзШапки(doc) {
    const тексты = [];
    for (const e of doc.querySelectorAll('#customerRequestForm h1 .ml-auto, .card-header h1 .ml-auto, h1')) тексты.push(e.textContent);
    for (const s of doc.querySelectorAll('span, b, strong, label')) if (/^\s*Статус:\s*$/.test(s.textContent || '') && s.parentElement) тексты.push(s.parentElement.textContent);
    for (const t of тексты) {
      const m = String(t || '').replace(/\s+/g, ' ').match(/Статус:\s*(.+)$/);
      const код = m ? кодСтатуса(m[1]) : 0;
      if (код) return код;
    }
    return 0;
  }

  // кто сейчас в CRM (навигация / «Выход (…)») — только для сравнения «держу ли я», имя не храним
  function текущийСотрудник(doc) {
    // только места с именем вошедшего (не любые выпадающие меню: «Справочники» приняли бы за имя → «чужая» по ошибке)
    for (const e of doc.querySelectorAll('[data-user-name], form[action*="logout"] button, a[href*="logout"], .user-name')) {
      const t = (e.getAttribute('data-user-name') || e.textContent || '').replace(/\s+/g, ' ').trim();
      const m = t.match(/\(([^)]+)\)/);
      const v = (m ? m[1] : t).replace(/^(?:выход|выйти|logout)\s*/i, '').trim();
      if (v.length >= 3 && !/^(?:выход|выйти|logout)$/i.test(v)) return v;
    }
    return '';
  }
  // «в работе у» — только в собственном тексте элемента: в комментарии (textarea внутри div) эти слова бывают у мастера;
  // таблицы (история заявки) и модалки не смотрим — там это прошлое, а не «сейчас держит»
  const свойТекст = (e) => [...e.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join(' ');
  /* Заявки, которые взяли МЫ (take из расширения, offscreen один на все вкладки): имени в навигации CRM может не быть,
     а «у вас ли» нужно знать, чтобы не нажать «Вернуть» за другого. Забываем, когда карточка показала «свободна» или прошло 3 ч */
  const ВЗЯТО = new Map();
  const взятоМной = (k) => { const t = ВЗЯТО.get(k); if (t && Н.сейчас() - t < 3 * 3600e3) return true; ВЗЯТО.delete(k); return false; };
  function держит(doc, dir, id) {
    const рядом = [...doc.querySelectorAll('div, span, p, li, small, b, strong')].find((e) => !e.closest('table, .grid-view, .modal, textarea') && /в работе у/i.test(свойТекст(e)));
    const yes = !!рядом || !!ссылкаЗаявки(doc, ССЫЛКА.release, id);
    if (!yes) { ВЗЯТО.delete(dir + ':' + id); return { yes: false, mine: false }; }
    const кто = рядом ? ((рядом.textContent || '').replace(/\s+/g, ' ').match(/в работе у\s+(.+?)(?:\s+Вернуть|\s*$)/i) || [])[1] || '' : '';
    const я = текущийСотрудник(doc);
    const фам = (s) => норм(s).split(' ')[0];
    // видно оба имени — решают они; иначе «моя», если брали мы; неизвестно — null («чужая» только когда точно видно другое имя)
    if (кто && я) return { yes: true, mine: фам(кто) === фам(я) };
    return { yes: true, mine: взятоМной(dir + ':' + id) ? true : null };
  }

  // город, тип, непрофильная — yiiActiveForm CRM без них форму не отправит
  function обязательныеЕсть(doc, безГорода) {
    const form = doc.querySelector('#customerRequestForm');
    return ['CustomerRequest[city_id]', 'CustomerRequest[type]', 'CustomerRequest[is_noncore]'].filter((n) => !безГорода || n !== 'CustomerRequest[city_id]')
      .every((n) => { const e = поле(form, n); return !e || e.disabled || значение(e) !== ''; });
  }
  function датаISO(s) {
    const t = String(s || '');
    let m = t.match(/(\d{4})-(\d{2})-(\d{2})/);
    if (m) return m[1] + '-' + m[2] + '-' + m[3];
    m = t.match(/(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})/);
    return m ? m[3] + '-' + m[2].padStart(2, '0') + '-' + m[1].padStart(2, '0') : '';
  }
  const времяЧЧММ = (s) => { const m = String(s || '').match(/(\d{1,2}):(\d{2})/); return m ? m[1].padStart(2, '0') + ':' + m[2] : ''; };
  // строка «Переносы» — только даты и причина; телефон, если вдруг вписан руками, маскируем
  const безТелефона = (s) => String(s || '').replace(/\+?\d[\d\s()-]{8,}\d/g, '•••').slice(0, 160);

  // FNV-1a: короткий и одинаковый в offscreen и в node
  function хэш(s) {
    let h = 0x811c9dc5;
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
    return h.toString(16).padStart(8, '0');
  }
  function подпись(c) {
    return хэш(JSON.stringify([c.statusCode, c.held.yes, c.held.mine, КНОПКИ.map((k) => (c.buttons[k] ? 1 : 0)).join(''),
      ФЛАГИ.map((k) => (c.flags[k] === null ? 'n' : c.flags[k] ? 1 : 0)).join(''), c.visitDate, c.visitTime, c.changesCount, c.cityId || '', c.applId || '', c.subId || '']));
  }
  /* Ключ журнала — ключ задания + рецепт шага: экран шлёт один ключ на все шаги задания, а «только что сделано» у одного шага
     («Не отвечает») не должно глушить другой шаг того же задания. Повтор шага (даже с поправленным вводом) — тот же ключ:
     вторую претензию или отметку по тому же заданию не шлём. Два шага с одним рецептом в задании — разными ключами */
  const ключШага = (key, recipe) => (key ? key + '|' + recipe : '');

  /* Разбор карточки: null — это не карточка заявки (страница входа, ошибка, список) */
  function разобрать(doc, dir, id) {
    const form = doc.querySelector('#customerRequestForm');
    if (!form) return null;
    id = String(id);
    const коды = new Set();
    for (const e of doc.querySelectorAll('[onclick*="saveAndClose"]')) { const m = (e.getAttribute('onclick') || '').match(/saveAndClose\(\s*this\s*,\s*(\d+)/); if (m) коды.add(Number(m[1])); }
    const buttons = {
      take: !!ссылкаЗаявки(doc, ССЫЛКА.take, id), release: !!ссылкаЗаявки(doc, ССЫЛКА.release, id), claim: !!ссылкаЗаявки(doc, ССЫЛКА.claim, id),
      toNotTaken: !!ссылкаЗаявки(doc, ССЫЛКА.toNotTaken, id),
      awaitFromCancel: !!ссылкаЗаявки(doc, 'cancel-transaction', id, (h) => /[?&]state=1(?!\d)/.test(h)),
      backToWork: !!ссылкаЗаявки(doc, 'cancel-transaction', id, (h) => !/[?&]state=/.test(h)),
      promote: !!ссылкаЗаявки(doc, ССЫЛКА.promote, id),
      noAnswer: !!doc.querySelector('#actSaveServiceComment'), saveComment: !!doc.querySelector('#actSaveComment'),
      feedback: !!doc.querySelector('[data-target="#crFeedbackModal"], [data-bs-target="#crFeedbackModal"]'),
      branchComment: !!doc.querySelector('#recommendationCommentModalOpen'),
      saveCity: !!doc.querySelector('#actSaveCity'),
    };
    for (const n of [1, 2, 10, 11, 20, 21, 22, 25, 26, 30, 60]) buttons['s' + n] = коды.has(n);
    const flags = {}, flagsEnabled = {};
    for (const k of ФЛАГИ) {
      const e = поле(form, ПОЛЕ[k]);
      if (!e) { flags[k] = null; flagsEnabled[k] = false; continue; }
      flagsEnabled[k] = !e.disabled;
      flags[k] = e.type === 'checkbox' ? !!e.checked : значение(e) === '1';
      if (k === 'farRide' && e.disabled) flags[k] = null;      // дальний выезд закрыт — как будто поля нет
    }
    const sel = (n) => { const e = поле(form, n); if (!e || e.tagName !== 'SELECT') return { value: значение(e), text: '' }; const o = e.options[e.selectedIndex]; return { value: e.value, text: o ? o.textContent.replace(/\s+/g, ' ').trim() : '' }; };
    const город = sel('CustomerRequest[city_id]');
    const вид = sel('CustomerRequest[appliance_type_id]'), услуги = sel('CustomerRequest[appliance_sub_type_id]');
    const открыто = (n) => { const e = поле(form, n); return !!e && !e.disabled; };
    const тип = Number(значение(поле(form, ПОЛЕ.type))) || null;
    const переносы = значение(doc.querySelector('#customerrequest-date_changes') || поле(form, 'CustomerRequest[date_changes]')).split('\n').map((x) => x.trim()).filter(Boolean);
    const служебный = значение(doc.querySelector('#customerrequest-comments_service') || поле(form, 'CustomerRequest[comments_service]'));
    let customerId = значение(поле(form, 'CustomerRequest[customer_id]'));
    if (!/^\d+$/.test(customerId)) { const a = doc.querySelector('a[href*="/customer/update?id="]'); customerId = a ? ((a.getAttribute('href') || '').match(/[?&]id=(\d+)/) || [])[1] || '' : ''; }
    const обяз = обязательныеЕсть(doc);
    let statusCode = статусИзШапки(doc);
    // «Готов ОФ» (1020) CRM в шапке пишет «Отмена Филиала»: различить можно только по кнопкам — у отмены есть «Вернуть в «Ожидает»»,
    // «Вернуть в работу» или «Не оформлена», у «Готов ОФ» — только претензия и отзыв (повтор — только через руководителя)
    if (statusCode === 1002 && !buttons.awaitFromCancel && !buttons.backToWork && !buttons.toNotTaken && (buttons.claim || buttons.feedback)) statusCode = 1020;
    const card = {
      dir, id, url: BASES[dir] + ПУТЬ + 'update?id=' + id, at: Н.сейчас(), sig: '',
      statusName: СТАТУСЫ[statusCode] || '', statusCode,
      held: держит(doc, dir, id), buttons,
      transferServers: [...doc.querySelectorAll('#crTransferServerOption option')].filter((o) => o.value).map((o) => ({ key: o.value, title: o.textContent.replace(/\s+/g, ' ').trim() })),
      flags, flagsEnabled,
      type: [10, 20, 30].includes(тип) ? тип : null,
      hasPartner: !!значение(поле(form, 'CustomerRequest[partner_id]')),
      partnerAskNoCall: значение(doc.querySelector('#__tPartnerAskNotShowPhonecall')) === '1',
      visitDate: датаISO(значение(поле(form, 'CustomerRequest[opened_at]'))),
      visitTime: времяЧЧММ(значение(doc.querySelector('#cr_opened_at_time') || поле(form, 'cr_opened_at_time'))),
      changesCount: переносы.length, lastChange: безТелефона(переносы[переносы.length - 1] || ''),
      cityId: город.value, cityName: город.text.replace(/^выберите.*$/i, ''), customerId: /^\d+$/.test(customerId) ? customerId : '',
      requiredOk: обяз, noAnswerCount: (служебный.match(/не\s*отвеча/gi) || []).length,
      // вид работ и вид услуг (номер и название из select'ов карточки; поля «Вид услуг» в КП нет — hasSub=false)
      applId: вид.value || '', applName: вид.value ? вид.text : '', subId: услуги.value || '', subName: услуги.value ? услуги.text : '',
      hasSub: !!поле(form, 'CustomerRequest[appliance_sub_type_id]'),
      cityEditable: открыто('CustomerRequest[city_id]'), applEditable: открыто('CustomerRequest[appliance_type_id]'),
    };
    card.sig = подпись(card);
    return card;
  }

  /* ---------- «Что в заявке»: подробности карточки (только чтение, только по запросу snap({details:true})) ----------
     Отдельно от снимка: в них слова клиента и адрес. Телефоны — маской (как actions-ui маска()), каждое поле — не длиннее 2000 */
  const МОБИЛЬНЫЙ = /(?<!\d)(?:\+7|8|7)?[\s(-]*9\d{2}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)/g;
  const ГОРОДСКОЙ = /(?<![\d+])(?:(?:\+7|8)[\s(-]*\d{3,5}[\s)-]*\d{1,3}(?:[\s-]*\d{1,3}){1,3}|\d{10})(?!\d)/g;
  const маскаТел = (s) => String(s == null ? '' : s).replace(МОБИЛЬНЫЙ, (m) => m.match(/^\s*/)[0] + '+7 9••-•••-••' + m.replace(/\D/g, '').slice(-2))
    .replace(ГОРОДСКОЙ, (m) => { const d = m.replace(/\D/g, ''); return d.length === 10 || (d.length === 11 && /^[78]/.test(d)) ? '+7 •••-•••-••' + d.slice(-2) : m; });
  const чисто = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
  const текстПоля = (s) => маскаТел(String(s == null ? '' : s).replace(/\r\n?/g, '\n').replace(/[ \t]+\n/g, '\n').trim()).slice(0, 2000);
  // тестовые варианты CRM («Test», «Тест…») оператору не предлагаем — кроме того, что уже выбрано
  const тестовый = (t) => /^\s*(тест|test)(?![а-яa-z])/i.test(String(t || ''));
  function вариантыСписка(form, n) {
    const e = поле(form, n);
    if (!e || e.tagName !== 'SELECT') return [];
    return [...e.options].filter((o) => /^\d+$/.test(o.value) && (o.selected || !тестовый(o.textContent))).map((o) => ({ id: o.value, name: чисто(o.textContent) }));
  }
  /* Адрес клиента: блок CRM над формой (.__customer-q-info: «Нас.пункт: …», «Улица: …», «Дом: …», «Кв/офис: …, подъезд: …, этаж: …»);
     нет блока — поля Customer[address_*] (модерация, уточнение), иначе скрытое __tCustomerAddress. Телефон и имя из блока не берём */
  function адресКлиента(doc, form) {
    const части = {};
    const блок = doc.querySelector('.__customer-q-info');
    if (блок) {
      for (const s of блок.querySelectorAll('span')) {
        const метка = норм(s.textContent).replace(/[:\s]+$/, '');
        let v = '';
        for (let n = s.nextSibling; n && !(n.nodeType === 1 && n.tagName === 'SPAN'); n = n.nextSibling) v += n.nodeType === 3 ? n.textContent : n.nodeType === 1 && !/^(A|I|DIV)$/.test(n.tagName) ? n.textContent : '';
        v = чисто(v).replace(/[,\s]+$/, '');
        if (v && !(метка in части)) части[метка] = v;
      }
    }
    const из = (k) => части[k] || '';
    const ф = (n) => чисто(значение(form && form.elements[n]));
    const нп = из('нас.пункт') || из('нас. пункт') || из('населенный пункт') || ф('Customer[address_locality]');
    const улица = из('улица') || ф('Customer[address_street]');
    const дом = из('дом') || ф('Customer[address_building]');
    const кв = из('кв/офис') || из('кв') || ф('Customer[address_office]');
    const строка = [нп, улица, дом ? 'д. ' + дом : '', кв ? 'кв/офис ' + кв : '', из('подъезд') ? 'подъезд ' + из('подъезд') : '', из('этаж') ? 'этаж ' + из('этаж') : '']
      .filter(Boolean).join(', ');
    return маскаТел(строка || чисто(значение(doc.querySelector('#__tCustomerAddress')))).slice(0, 300);
  }
  function подробностиКарточки(doc) {
    const form = doc.querySelector('#customerRequestForm');
    const т = (f) => текстПоля(значение(doc.querySelector('#customerrequest-' + f) || поле(form, 'CustomerRequest[' + f + ']')));
    const естьПоле = (f) => !!(doc.querySelector('#customerrequest-' + f) || поле(form, 'CustomerRequest[' + f + ']'));
    return {
      comment: т('comments'), service: т('comments_service'), partner: естьПоле('partner_comment') ? т('partner_comment') : null,
      changes: т('date_changes').split('\n').map((x) => x.trim()).filter(Boolean).slice(-50),
      address: адресКлиента(doc, form),
      cities: вариантыСписка(form, 'CustomerRequest[city_id]'),
      appls: вариантыСписка(form, 'CustomerRequest[appliance_type_id]'),
      subs: вариантыСписка(form, 'CustomerRequest[appliance_sub_type_id]'),
    };
  }

  /* ---------- претензии по заявке: № и статус (список ОКК, только чтение) ----------
     Колонки списка — по шапке («Статус претензии», «Тип претензии», «Дата создания»); статуса в списке нет — со страницы претензии */
  const СТАТУС_ПРЕТЕНЗИИ = { 1: 'Новая', 2: 'В работе', 3: 'Решена', 4: 'Не решена' };
  function статусПретензии(t) {
    const s = норм(t);
    if (!s) return { status: '', statusCode: 0 };
    const код = /не\s*решен/.test(s) ? 4 : /решен/.test(s) ? 3 : /в\s*работе/.test(s) ? 2 : /нов/.test(s) ? 1 : 0;
    return { status: код ? СТАТУС_ПРЕТЕНЗИИ[код] : чисто(t).replace(/\d{4,}/g, '…').slice(0, 30), statusCode: код };
  }
  function статусСоСтраницы(doc) {
    const sel = doc.querySelector('select[name="CrClaim[status]"]');
    if (sel && sel.options[sel.selectedIndex] && sel.value) return sel.options[sel.selectedIndex].textContent;
    for (const e of doc.querySelectorAll('th, dt, label, b, strong, span')) {
      if (!/^статус( претензии)?\s*:?$/.test(норм(e.textContent))) continue;
      const след = e.nextElementSibling;
      if (след && чисто(след.textContent)) return чисто(след.textContent);
      const t = чисто(e.parentElement ? e.parentElement.textContent : '').replace(/^статус( претензии)?\s*:?\s*/i, '');
      if (t) return t;
    }
    return '';
  }
  async function претензииЗаявки(к) {
    const doc = await fetchDoc(к.base + '/admin/domain/cr-claim/index?CrClaimSearch%5Bcr_id%5D=' + encodeURIComponent(к.id));
    const таблица = [...doc.querySelectorAll('table')].find((t) => t.querySelector('a[href*="cr-claim/view?id="]'));
    if (!таблица) return { count: 0, list: [] };
    const шапка = [...таблица.querySelectorAll('thead tr, tr')].find((tr) => tr.querySelector('th'));
    const колонки = шапка ? [...шапка.children].map((x) => норм(x.textContent)) : [];
    const кол = (...re) => { for (const r of re) { const i = колонки.findIndex((t) => r.test(t)); if (i >= 0) return i; } return -1; };
    const iСтатус = кол(/статус претензии/, /^статус$/), iТип = кол(/тип претензии/, /^тип$/), iДата = кол(/дата создания/);
    const list = [];
    for (const tr of таблица.querySelectorAll('tbody tr')) {
      const a = tr.querySelector('a[href*="cr-claim/view?id="]');
      const id = a ? ((a.getAttribute('href') || '').match(/[?&]id=(\d+)/) || [])[1] : '';
      if (!id || list.some((x) => x.id === id)) continue;
      const я = [...tr.children];
      const т = (i) => (i >= 0 && я[i] ? чисто(я[i].textContent) : '');
      list.push({ id, ...статусПретензии(т(iСтатус)), type: т(iТип).replace(/\d{5,}/g, '…').slice(0, 90), created: т(iДата).slice(0, 20) });
    }
    for (const x of list.filter((y) => !y.status).slice(0, 3)) {
      try { Object.assign(x, статусПретензии(статусСоСтраницы(await fetchDoc(к.base + '/admin/domain/cr-claim/view?id=' + x.id)))); } catch (_e) { /* статус не прочитан — покажем «?» */ }
    }
    list.sort((a, b) => Number(b.id) - Number(a.id));
    return { count: list.length, list };
  }

  /* ---------- виды услуг для вида работ — как форма CRM (раздел 4.21): GET update?id=N&_get_appltype=1&get_subappltypes=1&city_id&appl_id&has_partner
     (X-Requested-With) → <option> или JSON. Вся страница вместо списка, список видов РАБОТ вместо услуг — не он */
  async function видыУслуг(к, doc, card, applId) {
    const form = doc.querySelector('#customerRequestForm');
    const виды = вариантыСписка(form, 'CustomerRequest[appliance_type_id]').map((x) => x.id);
    let пусто = false, почему = '';
    for (const hp of card.hasPartner ? [1, 0] : [0, 1]) {
      const q = new URLSearchParams({ _get_appltype: '1', get_subappltypes: '1', city_id: String(card.cityId || ''), appl_id: String(applId), subappl_id: '', has_partner: String(hp) });
      const r = await C._внутр.getСрок(к.url + '&' + q, { credentials: 'include', headers: { 'X-Requested-With': 'XMLHttpRequest', Accept: 'text/html, */*; q=0.01' } });
      const text = String(await r.text());
      if (/name="LoginForm\[|type="password"/i.test(text) || /\/login/i.test(r.url || '')) throw new Error(ТЕКСТ.сессия(ИМЯ[к.dir]));
      if (r.status >= 400) { почему = 'HTTP ' + r.status; continue; }
      if (/<html|<body|customerRequestForm/i.test(text)) { почему = 'вместо списка — страница'; continue; }
      const list = C.разобратьСписок(text).map((o) => ({ id: String(o.id), name: чисто(o.text) })).filter((o) => !тестовый(o.name));
      if (list.length && list.length === виды.length && list.every((x, i) => x.id === виды[i])) { почему = 'вместо видов услуг — виды работ'; continue; }
      if (list.length) return list;
      пусто = true;
    }
    if (пусто) return [];
    throw new Error('CRM не дала список видов услуг (' + (почему || 'нет ответа') + ')');
  }

  /* Что изменилось между превью и свежей карточкой — для текста «устарело» */
  function описатьИзменение(было, стало) {
    if (!было) return ['', стало.statusName || '?'];
    if (было.statusCode !== стало.statusCode) return [было.statusName, стало.statusName];
    if (было.held && (было.held.yes !== стало.held.yes || было.held.mine !== стало.held.mine)) {
      const к = (h) => (!h.yes ? 'свободна' : h.mine === false ? 'в работе у другого сотрудника' : h.mine === true ? 'в работе у вас' : 'в работе');
      return [к(было.held), к(стало.held)];
    }
    if (было.visitDate !== стало.visitDate || было.visitTime !== стало.visitTime) return [было.visitDate + ' ' + было.visitTime, стало.visitDate + ' ' + стало.visitTime];
    for (const k of ФЛАГИ) if (было.flags && было.flags[k] !== стало.flags[k]) return [ГАЛОЧКА[k] + ': ' + (было.flags[k] ? 'стоит' : 'нет'), ГАЛОЧКА[k] + ': ' + (стало.flags[k] ? 'стоит' : 'нет')];
    if (было.changesCount !== стало.changesCount) return ['переносов ' + было.changesCount, 'переносов ' + стало.changesCount];
    if ((было.cityId || '') !== (стало.cityId || '')) return ['город ' + (было.cityName || было.cityId || '—'), 'город ' + (стало.cityName || стало.cityId || '—')];
    if ((было.applId || '') !== (стало.applId || '') || (было.subId || '') !== (стало.subId || '')) {
      const в = (c) => 'вид работ ' + (c.applName || c.applId || '—') + (c.subId ? ' / ' + (c.subName || c.subId) : '');
      return [в(было), в(стало)];
    }
    return ['кнопки CRM одни', 'кнопки CRM другие'];
  }

  /* ---------- запись и разбор ответа ---------- */

  // последние снимки по заявке (offscreen один — их видят все вкладки): по подписи превью узнаём, что было, для «устарело»
  const СНИМКИ = new Map();
  function запомнитьСнимок(c) {
    const k = c.dir + ':' + c.id;
    const a = (СНИМКИ.get(k) || []).filter((x) => x.sig !== c.sig);
    a.push(c);
    while (a.length > 5) a.shift();
    СНИМКИ.delete(k); СНИМКИ.set(k, a);
    if (СНИМКИ.size > 200) СНИМКИ.delete(СНИМКИ.keys().next().value);
  }
  const снимокПоПодписи = (dir, id, sig) => (sig && (СНИМКИ.get(dir + ':' + id) || []).find((x) => x.sig === sig)) || null;
  // для «уже сделано» счётчики «+N» не годятся: до записи они всегда «не выросли»
  const безПлюсов = (e) => { if (!e) return null; const o = { ...e }; delete o.changesCountPlus; delete o.noAnswerCountPlus; return o; };

  const ЗАНЯТО = new Set();           // заявки, по которым идёт act (offscreen один на всё расширение — значит, на все вкладки)
  const ВИСИТ = new Map();            // dir:id → {at} запрос без ответа: пока он может дойти до CRM, новых записей по заявке нет
  const ЖУРНАЛ = new Map();           // ключ действия → {at, итог: 'sent'|'ok'|'fail'|'unknown'}
  const отметить = (к, итог) => {
    if (!к.key) return;
    ЖУРНАЛ.set(к.key, { at: Н.сейчас(), итог });
    if (ЖУРНАЛ.size > 300) for (const [k, v] of ЖУРНАЛ) if (Н.сейчас() - v.at > Н.памятьНеизвестных) ЖУРНАЛ.delete(k);
  };
  const висит = (замок) => { const v = ВИСИТ.get(замок); return !!v && Н.сейчас() - v.at < Н.памятьНеизвестных; };
  const чч = (t) => { const d = new Date(t); return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); };

  /* Запись со сроком 2 мин. Запрос не обрываем — CRM могла его принять; пока не ответил, заявка «висит» (новых записей нет).
     Повтора нет нигде: ни по сроку, ни по сетевой ошибке */
  async function записать(к, работа) {
    const замок = к.dir + ':' + к.id;
    к.записано = true;
    отметить(к, 'sent');
    const запрос = Promise.resolve().then(работа);
    const метка = { at: Н.сейчас() };
    ВИСИТ.set(замок, метка);
    запрос.then(() => {}, () => {}).then(() => { if (ВИСИТ.get(замок) === метка) ВИСИТ.delete(замок); });
    let t = null;
    const срок = new Promise((res) => { t = Н.таймер(() => res({ hung: true }), Н.срокЗаписи); });
    try {
      const r = await Promise.race([запрос.then((x) => ({ x }), (e) => ({ error: e })), срок]);
      if (!r.hung && ВИСИТ.get(замок) === метка) ВИСИТ.delete(замок);
      return r;
    } finally { Н.сброс(t); }
  }
  const запросФормы = (url, init) => async () => { const r = await fetch(url, { credentials: 'include', ...init }); return { r, text: await r.text().catch(() => '') }; };

  /* былиОшибки — тексты «ошибок», что стояли на карточке ещё до записи (постоянные надписи CRM): это не отказ */
  /* 2.2.9: что ответила CRM на запись — коротко и БЕЗ личных данных (в итог оператору и в журнал действий): код ответа, куда переадресовала
     (без номеров), что за страница (карточка «статус» / список / вход / страница ошибки), ошибки у полей («Подпись»: слова CRM), красные
     надписи CRM. Цифры от 4 подряд и телефоны скрыты; «в работе у …» (имя сотрудника) и синие надписи (.alert-info) не берём */
  const безЛичного = (t) => маскаТел(чисто(t)).replace(/\d{4,}/g, '…').replace(/(в работе у)\s+[^,.;|]+/gi, '$1 …');
  // текст надписи с пробелами между её частями (<p>…</p><ul><li>…</li></ul> — не слитно)
  function текстБлоков(e) {
    const t = [];
    try { const w = e.ownerDocument.createTreeWalker(e, 4); for (let n = w.nextNode(); n; n = w.nextNode()) t.push(n.textContent); } catch (_e) { t.push(e.textContent || ''); }
    return t.join(' ');
  }
  function видСтраницы(адрес) {
    const p = String(адрес || '').replace(/^https?:\/\/[^/]+/, '');
    if (/\/login/.test(p)) return 'вход';
    if (/default\/index/.test(p)) return 'главная';
    if (/customer-request\/update/.test(p)) return 'карточка заявки';
    if (/customer-request\/index/.test(p)) return 'список заявок';
    return p.replace(/\?.*$/, '').replace(/\d{4,}/g, '…').slice(0, 60) || '?';
  }
  function описатьОтвет(x, р) {
    try {
      const r = x.r, xr = (r.headers && r.headers.get && r.headers.get('X-Redirect')) || '';
      const части = ['HTTP ' + r.status];
      if (xr) части.push('переадресация: ' + видСтраницы(xr));
      else if (r.redirected && r.url) части.push('переадресация: ' + видСтраницы(r.url));
      if (р.вид === 'json') части.push('JSON: ' + безЛичного(JSON.stringify(р.json)).slice(0, 120));
      const d = р.doc;
      if (d) {
        const карта = d.querySelector('#customerRequestForm');
        const st = карта ? статусИзШапки(d) : 0;
        const заголовок = безЛичного(((d.querySelector('.site-error h1') || d.querySelector('h1') || {}).textContent) || d.title || '').slice(0, 60);
        части.push(карта ? 'страница: карточка' + (st ? ' «' + (СТАТУСЫ[st] || st) + '»' : '') : 'страница: ' + (заголовок || 'без заголовка'));
        const поля = (р.поляОшибок || ошибкиПолей(d)).map((f) => '«' + f.label + '»' + (f.text ? ': ' + f.text : ''));
        if (поля.length) части.push('ошибки у полей: ' + поля.join('; ').slice(0, 220));
        const красные = [...d.querySelectorAll('.alert-danger, .alert-error, .alert-warning, .error-summary')].map((e) => безЛичного(текстБлоков(e))).filter(Boolean);
        if (красные.length) части.push('надписи CRM: ' + [...new Set(красные)].join(' | ').slice(0, 220));
        if (р.вид === 'причина') части.push('просит «Причину смены статуса»');
        if (!поля.length && !красные.length && р.вид !== 'причина') части.push('без сообщений об ошибке');
      }
      if (р.вид === 'непонятно' || р.вид === 'http') части.push(р.кратко || '');
      return [...new Set(части.filter(Boolean))].join(', ').slice(0, 450);
    } catch (_e) { return ''; }
  }
  /* 2.2.9: ошибки у полей в ответе CRM (Yii ActiveForm): bs4 — поле .is-invalid и текст в .invalid-feedback, bs3 — обёртка .has-error и
     .help-block; сводка ошибок / красная надпись «Необходимо заполнить «Подпись»» — поле по подписи. → [{e, name, label, text}] */
  function ошибкиПолей(doc) {
    const form = doc.querySelector('#customerRequestForm') || doc.querySelector('form');
    if (!form) return [];
    const out = [], было = new Set();
    const добавить = (e, text) => {
      if (!e || !e.name || было.has(e.name) || /^(hidden|submit|button|reset|image)$/i.test(e.type || '') || e.tagName === 'BUTTON') return;
      было.add(e.name);
      out.push({ e, name: e.name, label: подписьПоля(form, e), text: безЛичного(text).slice(0, 160) });
    };
    for (const x of doc.querySelectorAll('.has-error, .is-invalid')) {
      const полеЛи = /^(INPUT|SELECT|TEXTAREA)$/.test(x.tagName);
      const обёртка = полеЛи ? (x.closest('.form-group, [class*="field-"]') || x.parentElement) : x;
      const e = полеЛи ? x : обёртка && обёртка.querySelector('select, textarea, input:not([type="hidden"])');
      const t = обёртка && обёртка.querySelector('.invalid-feedback, .help-block-error, .help-block');
      if (e && t && чисто(t.textContent)) добавить(e, t.textContent);
      else if (e && x.matches('.has-error, .is-invalid')) добавить(e, '');
    }
    // сводка ошибок и надписи без обёртки — по подписи поля в «кавычках»
    const подписи = new Map();
    for (const e of form.elements) if (e.name && !/^(hidden|submit|button)$/i.test(e.type || '')) { const l = норм(подписьПоля(form, e)); if (l && !подписи.has(l)) подписи.set(l, e); }
    for (const a of doc.querySelectorAll('.alert-danger, .alert-error, .error-summary, .invalid-feedback, .help-block-error, .help-block')) {
      const t = String(a.textContent || '');
      for (const m of t.matchAll(/«([^»]{1,60})»/g)) { const e = подписи.get(норм(m[1])); if (e && /заполн|выбер|неверн|обязател|необходим/i.test(t)) добавить(e, t.split(/\n/).find((s) => s.includes(m[0])) || t); }
    }
    return out;
  }
  function разобратьОтвет(x, былиОшибки) {
    const r = x.r, text = String(x.text || '');
    const xr = (r.headers && r.headers.get && r.headers.get('X-Redirect')) || '';
    if (/default\/index|\/login/i.test(xr) || /\/login/i.test(r.url || '')) return { вид: 'сессия' };
    if (r.status === 302 || xr) return { вид: 'редирект', куда: xr };
    // обычная отправка: CRM ответила 302, fetch прошёл по нему сам — пришла другая страница (не та же форма с ошибками)
    if (r.redirected && r.url && !/customer-request\/update/.test(r.url)) return { вид: 'редирект', куда: r.url };
    if (r.status >= 400) {
      // страница ошибки Yii (400 «Не удалось проверить переданные данные», 403, 405, 500) — её заголовок и надпись, для итога
      let doc = null;
      if (/<html|<body|<div/i.test(text)) { try { doc = new DOMParser().parseFromString(text, 'text/html'); } catch (_e) { doc = null; } }
      return { вид: 'http', кратко: 'HTTP ' + r.status, ...(doc ? { doc } : {}) };
    }
    const t = text.trim();
    if (/^[[{]/.test(t)) { try { return { вид: 'json', json: JSON.parse(t) }; } catch (_e) { return { вид: 'непонятно', кратко: 'испорченный JSON' }; } }
    if (/<html|<body|<form|<div|<select/i.test(t)) {
      const doc = new DOMParser().parseFromString(t, 'text/html');
      if (doc.querySelector('input[type="password"], [name^="LoginForm["]')) return { вид: 'сессия' };
      const sel = doc.querySelector('select[name="CustomerRequest[status_change_type]"]');
      if (sel) return { вид: 'причина', doc, sel };
      // ошибки формы: надписи (formErrors) и ошибки у полей (bs4 и bs3) — кроме тех, что стояли на карточке до записи
      const поляОшибок = ошибкиПолей(doc).filter((f) => !(былиОшибки && f.text && былиОшибки.has(f.text)));
      const ош = [...new Set([...formErrors(doc), ...поляОшибок.map((f) => f.text || 'ошибка у поля «' + f.label + '»')])].filter((t) => !(былиОшибки && былиОшибки.has(t)));
      if (ош.length) return { вид: 'ошибки', ошибки: ош, поляОшибок, doc };
      return { вид: 'страница', doc };
    }
    return { вид: 'непонятно', кратко: t ? 'ответ не HTML и не JSON, HTTP ' + r.status : 'пустой ответ, HTTP ' + r.status };
  }

  // сделано — и что подставили перед сохранением (заполнено — без значений текстовых полей; заметки — строки итога для оператора)
  const итог = (к, o) => ({ steps: к.steps, ...(к.warnings.length ? { warnings: к.warnings } : {}), ...(o.ok && (к.заполнено || []).length ? заполненоВИтог(к) : {}), ...o });
  function заполненоВИтог(к) {
    const оп = к.заполнено.filter((x) => !x.auto), сам = к.заполнено.filter((x) => x.auto);
    return {
      заполнено: к.заполнено.map((x) => ({ name: x.name, label: x.label, auto: x.auto, ...(x.kind === 'select' ? { value: x.value, text: x.text } : {}) })),
      заметки: [...(оп.length ? ['заполнено перед сохранением: ' + оп.map((x) => x.label + ' — ' + x.text).join(', ')] : []),
        ...сам.map((x) => x.label + ' был пустой — поставил «' + x.text + '» (иначе CRM не сохраняет)')],
    };
  }
  // 2.2.9: при неудаче — и что ответила CRM (crmReply: код, страница, ошибки у полей, надписи — без личных данных), чтобы жалоба была с причиной
  function провал(к, code, error, extra) { отметить(к, 'fail'); return итог(к, { ok: false, code, error, ...(к.ответCRM ? { crmReply: к.ответCRM } : {}), ...(extra || {}) }); }
  function неизвестно(к, детали, extra) {
    отметить(к, 'unknown');
    к.steps.push({ name: 'CRM', ok: false, detail: детали });
    return итог(к, { ok: false, unknown: true, code: 'нет ответа', error: ТЕКСТ.нетОтвета, ...(extra || {}) });
  }

  /* «Запрет на обработку» (модерация, у клиента есть более ранняя заявка): CRM вместо карточки показывает страницу-запрет.
     Наружу — только номер той заявки и слова CRM из <b> (без имени клиента) */
  function запретОбработки(doc, dir, id) {
    const крошки = [...doc.querySelectorAll('.breadcrumb-item, h1, title')].some((e) => /Запрет на обработку/i.test(e.textContent || ''));
    if (!крошки) return null;
    const a = [...doc.querySelectorAll('.page-update a[href*="customer-request/update?id="], .card-body a.btn[href*="customer-request/update?id="]')]
      .map((x) => ((x.getAttribute('href') || '').match(/[?&]id=(\d+)/) || [])[1]).find((x) => x && x !== String(id));
    const почему = безТелефона(((doc.querySelector('.page-update p b') || {}).textContent || '').replace(/\s+/g, ' ').trim()).slice(0, 120);
    return { id: a || '', почему, url: a ? BASES[dir] + ПУТЬ + 'update?id=' + a : '' };
  }

  async function прочитать(к) {
    const doc = await fetchDoc(к.url);
    const card = разобрать(doc, к.dir, к.id);
    const запрет = card ? null : запретОбработки(doc, к.dir, к.id);
    if (запрет) { const e = new Error('запрет на обработку'); e.запрет = запрет; throw e; }
    if (!card) throw new Error('карточка заявки не открылась');
    запомнитьСнимок(card);
    return { doc, card };
  }
  function ошибкаЧтения(к, e) {
    const m = String((e && e.message) || e || '');
    const з = e && e.запрет;
    if (з) {
      return { ok: false, code: 'запрет', error: ТЕКСТ.запретОбработки(к.id, з), ...(з.id ? { blockedBy: { dir: к.dir, id: з.id, url: з.url } } : {}) };
    }
    if (/Сессия/i.test(m)) return { ok: false, code: 'сессия', error: ТЕКСТ.сессия(ИМЯ[к.dir]) };
    return { ok: false, code: 'чтение', error: 'Не открылась карточка заявки № ' + к.id + ' в CRM ' + ИМЯ[к.dir] + ' (' + m.slice(0, 80) + '). Ничего не сделано.' };
  }

  /* Ответ на запись → итог. цель(card, doc) — то, что должно стоять в карточке после действия */
  async function послеЗаписи(к, w, цель, о = {}) {
    if (!w || w.hung) return неизвестно(к, 'нет ответа 2 мин');
    if (w.error) return неизвестно(к, 'сеть: ' + String((w.error && w.error.message) || w.error).slice(0, 60));
    const р = разобратьОтвет(w.x, к.ошибкиБыли);
    к.ответCRM = описатьОтвет(w.x, р);                                  // что ответила CRM — в итог при неудаче (crmReply) и шагом
    к.steps.push({ name: 'ответ CRM', ok: !/^(сессия|ошибки|http|непонятно)$/.test(р.вид), detail: к.ответCRM });
    if (р.вид === 'сессия') {
      // переадресация «на главную/вход» после записи ещё не значит, что не записалось (куда CRM шлёт после новых кнопок — не проверено):
      // карточка открывается — сессия жива, решает карточка; «Ничего не сделано» говорим, только когда и чтение упёрлось во вход
      let жива = false;
      try { await прочитать(к); жива = true; } catch (_e) { /* ниже — сессия */ }
      if (жива) { к.steps.push({ name: 'CRM', ok: true, detail: 'переадресация' }); return проверить(к, цель, о); }
      к.steps.push({ name: 'CRM', ok: false, detail: 'вход' });
      return провал(к, 'сессия', ТЕКСТ.сессия(ИМЯ[к.dir]));
    }
    if (р.вид === 'ошибки') {
      // успех и отказ решает карточка, а не ответ: перечитываем — цель стоит, значит сделано (с пометкой), иначе — слова CRM
      к.steps.push({ name: 'CRM', ok: false, detail: 'ошибки формы' });
      let п = null;
      try { п = await прочитать(к); } catch (_e) { /* ниже — отказ по словам CRM */ }
      if (п && цель(п.card, п.doc) && ожиданиеСбылось(к.params.expect, п.card, к.до)) {
        к.steps.push({ name: 'проверка', ok: true, detail: 'в карточке ' + (о.описание || п.card.statusName) });
        к.warnings.push('CRM показала: «' + р.ошибки.slice(0, 2).join('; ') + '», но в карточке всё на месте');
        отметить(к, 'ok');
        return итог(к, { ok: true, after: п.card, ...(о.после ? await о.после(п) : {}) });
      }
      // 2.2.9: ошибка у пустого поля (Yii: «Необходимо заполнить «…»») — что выбрать, с вариантами из свежей карточки; оператор выбирает
      // в итоге и жмёт «Заполнить и повторить» (то же задание с заполнить). Поле не пустое (значение неверно) — только слова CRM
      const форма2 = п && п.doc.querySelector('#customerRequestForm');
      const поля = [];
      for (const f of р.поляОшибок || []) {
        const e = (форма2 && поле(форма2, f.name)) || f.e;
        if (!e || e.disabled || значение(e).trim() || поля.some((x) => x.name === f.name)) continue;
        const о = описатьПоле(форма2 || e.form || f.e.form, e);
        if (о.kind === 'select' && !о.options.length) continue;
        поля.push({ ...о, label: f.label || о.label });
      }
      const слова = р.ошибки.slice(0, 2).join('; ');
      if (поля.length) { неЗаполнено(к); запомнитьТребование(к, поля.map((x) => x.name)); return провал(к, 'пусто', ТЕКСТ.отказПоля(слова, поля.map((x) => x.label)), { поля, ...(п ? { after: п.card } : {}) }); }
      return провал(к, 'отказ', ТЕКСТ.отказ(слова), п ? { after: п.card } : {});
    }
    // 2.2.9: ссылка CRM (Вернуть в «Ожидает» / в работу) — POST формы, как браузер; сервер не принимает POST (405) — ничего не сделано:
    // как в 1.18, переходом по ссылке (GET)
    if (р.вид === 'http' && р.кратко === 'HTTP 405' && о.еслиGET) {
      к.steps.push({ name: 'CRM', ok: false, detail: 'POST не принят (405) — переходом по ссылке, как 1.18' });
      const w2 = await записать(к, запросФормы(о.еслиGET, { method: 'GET' }));
      return послеЗаписи(к, w2, цель, { ...о, еслиGET: null });
    }
    if (р.вид === 'http') {
      // 500 мог прийти и после сохранения — решает карточка (иначе «Не отвечает»/претензию можно было бы нажать второй раз)
      к.steps.push({ name: 'CRM', ok: false, detail: р.кратко });
      let п = null;
      try { п = await прочитать(к); } catch (_e) { return неизвестно(к, р.кратко + ', карточка не перечиталась'); }
      if (цель(п.card, п.doc) && ожиданиеСбылось(к.params.expect, п.card, к.до)) {
        к.steps.push({ name: 'проверка', ok: true, detail: 'в карточке ' + (о.описание || п.card.statusName) });
        к.warnings.push('CRM ответила «' + р.кратко + '», но в карточке всё на месте');
        отметить(к, 'ok');
        return итог(к, { ok: true, after: п.card, ...(о.после ? await о.после(п) : {}) });
      }
      // 2.2.9: 400 «Не удалось проверить переданные данные» — Yii не принял токен формы (в CRM перезашли / сессия сменилась): ничего не сделано
      if (р.кратко === 'HTTP 400' && р.doc && /не удалось проверить переданные данные/i.test(р.doc.body ? р.doc.body.textContent : '')) return провал(к, 'отказ', ТЕКСТ.токен, { after: п.card });
      return провал(к, 'неожиданно', ТЕКСТ.неожиданно(р.кратко), { after: п.card });
    }
    if (р.вид === 'причина') { к.steps.push({ name: 'CRM', ok: true, detail: 'просит причину' }); return причина(к, р, цель, о); }
    if (о.послеОтвета && (р.вид === 'редирект' || р.вид === 'страница')) о.послеОтвета(р);
    к.steps.push({ name: 'CRM', ok: р.вид !== 'непонятно', detail: р.вид === 'редирект' ? 'принято' : р.вид });
    return проверить(к, цель, о, р.вид === 'непонятно' ? р.кратко : '');
  }

  async function проверить(к, цель, о = {}, непонятно = '') {
    let п;
    try { п = await прочитать(к); } catch (e) { return неизвестно(к, 'перечитать карточку не удалось: ' + String((e && e.message) || e).slice(0, 60)); }
    let рецептОк = !!цель(п.card, п.doc), планОк = ожиданиеСбылось(к.params.expect, п.card, к.до);
    // CRM сохраняет с задержкой (09.10: перенос встал, а карточка сразу после записи показала прежнее время, «Не сделано»):
    // не сошлось — перечитываем ещё дважды (через 1,5 и 3 с), и только потом «не проверилось». Запись не повторяем
    for (const пауза of [1500, 3000]) {
      if (рецептОк && планОк) break;
      await new Promise((r) => setTimeout(r, к.быстро ? 1 : пауза));
      try { п = await прочитать(к); } catch (_e) { break; }
      рецептОк = !!цель(п.card, п.doc); планОк = ожиданиеСбылось(к.params.expect, п.card, к.до);
      к.steps.push({ name: 'проверка', ok: рецептОк && планОк, detail: 'перечитал через ' + (пауза / 1000) + ' с' });
    }
    const ок = рецептОк && планОк;
    const что = !рецептОк ? (о.что ? о.что(п.card, п.doc) : п.card.statusName) : описатьКарточку(к.params.expect, п.card);
    к.steps.push({ name: 'проверка', ok: ок, detail: ок ? 'в карточке ' + (о.описание || п.card.statusName) : 'в карточке «' + что + '»' });
    if (!ок) {
      if (к.ответCRM) к.warnings.push('Ответ CRM: ' + к.ответCRM);
      return провал(к, непонятно ? 'неожиданно' : 'не проверилось', непонятно ? ТЕКСТ.неожиданно(непонятно) : ТЕКСТ.неПроверилось(что), { after: п.card });
    }
    отметить(к, 'ok');
    return итог(к, { ok: true, after: п.card, ...(о.после ? await о.после(п) : {}) });
  }

  /* Двухшаговая причина status_change_type (проект 3.3.18): CRM вернула форму с выбором причины.
     Сначала GET: статус уже целевой — второй шаг не делаем. Причина из превью есть в списке и других пустых обязательных
     полей нет — ставим её и отправляем ВОЗВРАЩЁННУЮ форму (как клик по зелёной кнопке). Иначе — стоп, выбор оператору */
  async function причина(к, р, цель, о) {
    let п;
    try { п = await прочитать(к); } catch (e) { return неизвестно(к, 'перечитать карточку не удалось: ' + String((e && e.message) || e).slice(0, 60)); }
    if (цель(п.card, п.doc) && ожиданиеСбылось(к.params.expect, п.card, к.до)) { к.steps.push({ name: 'проверка', ok: true, detail: 'уже в карточке после первого шага' }); отметить(к, 'ok'); return итог(к, { ok: true, after: п.card, ...(о.после ? await о.после(п) : {}) }); }
    const sel = р.sel, form = sel.form || sel.closest('form');
    const options = [...sel.options].filter((o) => o.value).map((o) => ({ value: o.value, text: o.textContent.replace(/\s+/g, ' ').trim() }));
    if (!form || !options.length) return провал(к, 'неожиданно', ТЕКСТ.неожиданно('выбор причины без формы или без вариантов'), { after: п.card });
    const исходное = телоФормы(form);
    /* 2.2.9: другие пустые обязательные поля возвращённой формы — как в первой записи: выбор оператора (заполнить), у завершающих —
       «Дальний выезд» «Нет» и пустой город 39; что осталось пустым — оператору вместе с причиной (поля), а не «сделайте в CRM»
       (раньше в модерации с пустым «Видом работ» «Отказались» / «Не оформлена» с причиной не проходили никогда) */
    const пустыеФормы = () => {
      const m = new Map();
      for (const e of form.querySelectorAll('[required], [aria-required="true"]')) {
        if (e === sel || !e.name || e.disabled || e.type === 'hidden' || /^(checkbox|radio|submit|button)$/i.test(e.type || '') || значение(e).trim() || m.has(e.name)) continue;
        m.set(e.name, e);
      }
      return m;
    };
    const ош = вПустые(к, form, пустыеФормы(), к.завершающее);
    if (ош) return провал(к, 'ввод', 'Не делаю: ' + ош + '. Причину не отправлял.', { after: п.card });
    const пустые = пустыеФормы();
    const поля = описатьПоля(form, пустые).filter((f) => f.kind !== 'select' || f.options.length);
    const want = о.changeType == null ? '' : String(о.changeType);
    const стоп = (почему) => {
      отметить(к, 'fail');
      неЗаполнено(к);
      к.steps.push({ name: 'причина', ok: false, detail: почему });
      return итог(к, { ok: false, needReason: true, code: 'причина', options, ...(пустые.size ? { fields: [...пустые.values()].map((e) => подписьПоля(form, e)), ...(поля.length ? { поля } : {}) } : {}),
        after: п.card, ...(к.ответCRM ? { crmReply: к.ответCRM } : {}),
        error: ТЕКСТ.причина(options.map((o) => o.text).join(', ')) + (пустые.size ? ' Ещё CRM просит заполнить: ' + [...пустые.values()].map((e) => подписьПоля(form, e)).join(', ')
          + (поля.length === пустые.size ? ' — выберите вместе с причиной.' : ' — это сделайте в CRM.') : '') });
    };
    if (!want) return стоп('причина не выбрана');
    if (!options.some((o) => o.value === want)) return стоп('выбранной причины нет в списке CRM');
    if (пустые.size) return стоп('есть другие пустые поля');
    // как браузер: из кнопок уходит только нажатая (зелёная «Сохранить»)
    sel.value = want;
    const тело = телоФормы(form);
    const кн = form.querySelector('button.btn-success') || р.doc.querySelector('button.btn-success');
    const разрешено = new Set(['CustomerRequest[status_change_type]', ...к.заполнено.map((x) => x.name)]);
    if (кн && кн.name) { тело.append(кн.name, кн.value || ''); разрешено.add(кн.name); }
    const лишние = отличия(исходное, тело).filter((n) => !разрешено.has(n));
    if (лишние.length) return провал(к, 'внутренняя', 'Внутренняя ошибка: в форме причины меняется не только причина (' + лишние.join(', ') + '). Ничего не отправлено.');
    к.steps.push({ name: 'причина', ok: true, detail: options.find((o) => o.value === want).text });
    if (к.заполнено.length) к.steps.push({ name: 'заполнено', ok: true, detail: 'заполнено перед сохранением: ' + к.заполнено.map((x) => x.label + ' — ' + x.text).join(', ') });
    const адрес = new URL(form.getAttribute('action') || о.адрес || к.url, к.base).href;
    // 2.2.9: обычной отправкой, как зелёная кнопка формы (было — с X-Requested-With: на фоновый запрос Yii отвечает проверкой формы и
    // НЕ сохраняет — так 09.10 не вставал перенос; второй шаг причины так не прошёл бы никогда)
    const w = await записать(к, запросФормы(адрес, { method: 'POST', body: тело }));
    if (!w || w.hung || w.error) return послеЗаписи(к, w, цель, о);
    const р2 = разобратьОтвет(w.x, к.ошибкиБыли);
    if (р2.вид === 'причина') { к.ответCRM = описатьОтвет(w.x, р2); к.steps.push({ name: 'CRM', ok: false, detail: 'снова просит причину' }); return провал(к, 'неожиданно', ТЕКСТ.неожиданно('CRM снова просит причину')); }
    return послеЗаписи(к, w, цель, о);
  }

  /* Тело формы как у браузера: кнопки не уходят (уходит только нажатая — её имя добавляет тот, кто «нажимает») */
  const кнопкаЛи = (e) => e.tagName === 'BUTTON' || /^(submit|button|reset|image)$/i.test(e.type || '');
  function телоФормы(form) {
    const b = serializeForm(form);
    const только = new Set([...form.elements].filter((e) => e.name && кнопкаЛи(e)).map((e) => e.name));
    for (const e of form.elements) if (e.name && !кнопкаЛи(e)) только.delete(e.name);
    for (const n of только) b.delete(n);
    return b;
  }

  /* Тело формы: что поменялось по сравнению с исходной формой (имена) */
  function отличия(a, b) {
    const карта = (p) => { const m = new Map(); for (const [k, v] of p) { if (!m.has(k)) m.set(k, []); m.get(k).push(v); } return m; };
    const x = карта(a), y = карта(b), out = [];
    for (const k of new Set([...x.keys(), ...y.keys()])) if (JSON.stringify(x.get(k) || []) !== JSON.stringify(y.get(k) || [])) out.push(k);
    return out;
  }
  const естьСтрока = (текст, строка) => норм(текст).includes(норм(строка));
  const дописать = (было, строка) => (естьСтрока(было, строка) ? String(было || '') : [String(было || '').replace(/\s+$/, ''), строка].filter(Boolean).join('\n'));
  const партнёрЕсть = (form) => !!значение(поле(form, 'CustomerRequest[partner_id]')) || !!значение(поле(form, КОММ.addPartner)).trim();

  /* Дописать строки в комментарии формы (A/B). Комментарий партнёра — только когда партнёр есть (как cancelKc 1.18) */
  function комментарииВФорму(к, form, p, разрешено) {
    const вписано = {};
    for (const [k, n] of Object.entries(КОММ)) {
      if (!p[k]) continue;
      const e = поле(form, n);
      if (k === 'addPartner' && !партнёрЕсть(form)) continue;
      if (!e || e.disabled) { к.warnings.push('поля «' + { addComment: 'Комментарий', addService: 'Служебный', addPartner: 'Комментарий партнёра' }[k] + '» в карточке нет — не записано'); continue; }
      const next = k === 'addService' ? NOTES.mergeService(e.value, p[k]) : дописать(e.value, p[k]);
      if (k === 'addService' ? служебныйНаМесте(e.value, next) : естьСтрока(e.value, p[k])) continue;
      e.value = next;
      разрешено.add(n);
      вписано[k] = k === 'addService' ? e.value : p[k];
    }
    return вписано;
  }
  const нужныКомментарии = (form, p) => Object.entries(КОММ).some(([k, n]) => p[k] && (k !== 'addPartner' || партнёрЕсть(form)) && поле(form, n)
    && (k === 'addService' ? !служебныйНаМесте(значение(поле(form, n)), NOTES.mergeService(значение(поле(form, n)), p[k])) : !естьСтрока(значение(поле(form, n)), p[k])));
  const служебныйНаМесте = (actual, expected) => String(actual || '').replace(/\r\n?/g, '\n').trim() === String(expected || '').replace(/\r\n?/g, '\n').trim();
  const комментарииНаМесте = (doc, вписано) => Object.entries(вписано).every(([k, t]) => {
    const e = поле(doc.querySelector('#customerRequestForm'), КОММ[k]);
    return k === 'addService' ? !!e && служебныйНаМесте(значение(e), t) : !e || естьСтрока(значение(e), t);
  });
  const предупредитьКомментарии = (к, doc, вписано) => { if (!комментарииНаМесте(doc, вписано)) к.warnings.push('комментарий не записался — впишите в CRM: «' + Object.values(вписано).join('» / «') + '»'); };
  const своиКоды = (к) => (к.params.expect && Array.isArray(к.params.expect.statusCode) ? к.params.expect.statusCode.map(Number) : null);

  function скрытое(form, name, value) {
    let e = поле(form, name);
    if (!e) { e = form.ownerDocument.createElement('input'); e.type = 'hidden'; e.name = name; form.append(e); }
    if (e.tagName === 'SELECT' && ![...e.options].some((o) => o.value === String(value))) { const o = form.ownerDocument.createElement('option'); o.value = String(value); o.textContent = String(value); e.append(o); }
    e.value = String(value);
  }
  function поставить(form, name, value) {
    const e = поле(form, name);
    if (!e) return 'нет';
    if (e.disabled) return 'закрыто';
    if (e.type === 'checkbox') { setVal(form, name, value === true || value === 1 || value === '1' ? '1' : '0'); return ''; }
    if (e.tagName === 'SELECT' && ![...e.options].some((o) => o.value === String(value))) return 'нет варианта';
    e.value = String(value);
    return e.value === String(value) ? '' : 'не встало';
  }

  /* Кнопка type=submit (Сохранить, 20, 21, 22, 25, 26, 30): браузер не отправит форму, пока пусто поле с required
     (в модерации — «Вид работ», «Дальний выезд»). 2 и 11 шлют form.submit() сами — без проверки; 10, 60 и ссылки идут через
     yii.handleAction — только правила yiiActiveForm (город, тип, непрофильная) */
  function браузерПроверяет(doc, кнопка) {
    const код = Number(String(кнопка || '').replace(/^s/, ''));
    if (!/^s\d+$/.test(кнопка || '') || код === 2 || код === 11) return false;
    if (код === 1) return true;                                   // «Сохранить» — обычная submit-кнопка формы
    const e = doc.querySelector('[onclick*="saveAndClose(this, ' + код + ')"], [onclick*="saveAndClose(this, ' + код + ',"]');
    return !!e && (e.tagName === 'BUTTON' || e.tagName === 'INPUT') && String(e.type).toLowerCase() === 'submit';
  }
  // пустые поля с required — по форме ПОСЛЕ своих правок (город, поставленный этим же сохранением, — не пустой); по имени — одно
  function пустыеОбязательные(form) {
    const m = new Map();
    for (const e of form.querySelectorAll('[required]')) {
      if (!e.name || e.disabled || /^(hidden|checkbox|radio|submit|button)$/i.test(e.type || '') || значение(e).trim() || m.has(e.name)) continue;
      m.set(e.name, e);
    }
    return m;
  }
  // подпись поля — текст <label for> без кнопок внутри (у города в модерации там «Выбор по рейтингу», «Сохранить город»)
  function подписьПоля(form, e) {
    const l = e.id && form.ownerDocument.querySelector('label[for="' + e.id + '"]');
    let t = '';
    if (l) { const c = l.cloneNode(true); for (const x of c.querySelectorAll('a, button, select, input, textarea')) x.remove(); t = c.textContent.replace(/\s+/g, ' ').trim(); }
    return (t || ОБЯЗ_YII[e.name] || e.name).replace(/\s+/g, ' ').trim();
  }
  /* 2.2.5: поле для выбора оператором (поля в отказе «пусто»): select — варианты формы без пустого и без тестовых, остальное — текстом.
     Значений карточки наружу не отдаём (поле и так пустое) — только подпись и варианты формы */
  function описатьПоле(form, e) {
    const o = { name: e.name, label: подписьПоля(form, e), kind: e.tagName === 'SELECT' ? 'select' : 'text' };
    if (o.kind === 'select') o.options = [...e.options].filter((x) => x.value !== '' && !x.disabled && !тестовый(x.textContent)).map((x) => ({ value: x.value, text: чисто(x.textContent) }));
    return o;
  }
  const описатьПоля = (form, m) => [...m.values()].map((e) => описатьПоле(form, e));
  /* что можно заполнить: пустые [required] формы (их проверяет браузер у submit-кнопок) + пустые город / тип / непрофильная (yiiActiveForm).
     безГорода — город ставит само действие (fields с городом, «На уточнение» — 39) */
  function пустыеДляЗаполнения(form, безГорода) {
    const m = пустыеОбязательные(form);
    for (const n of Object.keys(ОБЯЗ_YII)) {
      const e = поле(form, n);
      if (e && !e.disabled && !значение(e).trim() && !m.has(n)) m.set(n, e);
    }
    if (безГорода) m.delete(ПОЛЕ.city);
    return m;
  }
  // заполнить из экрана: {имя поля формы: значение} — только строки и числа, не больше 20 полей (имена — латиница формы CRM)
  function нормЗаполнить(z) {
    if (!z || typeof z !== 'object' || Array.isArray(z)) return {};
    const out = {};
    for (const [n, v] of Object.entries(z).slice(0, 20)) if (/^[\w[\]\-.]{1,80}$/.test(n) && (typeof v === 'string' || typeof v === 'number')) out[n] = String(v).slice(0, 500);
    return out;
  }
  /* 2.2.5: перед записью — в пустые обязательные поля (и ТОЛЬКО в них): выбор оператора (к.заполнить; поле не обязательное или уже
     заполнено — молча не трогаем), select — только вариант формы. Завершающее действие с пустым «Дальний выезд» — «Нет» само
     (вариант с текстом «Нет», иначе значение 0; нет такого — не трогаем). Подставленное — к.заполнено (имена — в разрешённые отличия тела).
     Сначала проверка всего выбора, потом правки: неверный вариант — ничего не меняем. → {ошибка, поля} (поля — что было пустым до правок) */
  function заполнитьПустые(к, form, р) {
    const пустые = пустыеДляЗаполнения(form, р.форма === 'безГорода');
    const поля = описатьПоля(form, пустые);
    к.заполнено = к.заполнено || [];
    const ошибка = вПустые(к, form, пустые, р.завершающее);
    if (ошибка) return { ошибка, поля };
    if (к.заполнено.length) к.steps.push({ name: 'заполнено', ok: true, detail: 'заполнено перед сохранением: ' + к.заполнено.map((x) => x.label + ' — ' + x.text).join(', ') });
    return { ошибка: '', поля };
  }
  /* в пустые поля формы: выбор оператора (к.заполнить) — в пустые обязательные И в пустые поля, о которых CRM сказала «необходимо заполнить»
     (2.2.9: их экран берёт из ответа CRM — имя есть только у полей, что ядро само отдало); у завершающих — «Дальний выезд» «Нет»,
     пустой «Город» — 39 («КЦ», как saveAndClose у «На уточнение»). Подставленное — в к.заполнено (имена — разрешённые отличия тела).
     Сначала проверка всего выбора, потом правки: неверный вариант — ничего не меняем. → текст ошибки или '' */
  function вПустые(к, form, пустые, завершающее) {
    const план = [];
    const сказала = требовалаCRM(к);
    for (const [n, v0] of Object.entries(к.заполнить || {})) {
      let e = пустые.get(n);
      // поле без пометки «обязательное», но CRM в ответе на эту заявку сказала «необходимо заполнить» — его тоже (только пустое)
      if (!e && сказала.has(n)) { const x = поле(form, n); if (x && !x.disabled && x.type !== 'hidden' && !/^(checkbox|radio|submit|button)$/i.test(x.type || '') && !значение(x).trim()) e = x; }
      const v = String(v0 == null ? '' : v0).replace(/\s+/g, ' ').trim();
      if (!e || !v) continue;
      const о = описатьПоле(form, e);
      if (о.kind === 'select') {
        const вар = о.options.find((x) => x.value === v);
        if (!вар) return 'для «' + о.label + '» в CRM нет варианта «' + v.slice(0, 40) + '» — выберите из списка';
        план.push({ e, о, value: v, text: вар.text });
      } else план.push({ e, о, value: v.slice(0, 200), text: маскаТел(v).slice(0, 60) });
    }
    const запомнить = (x) => { if (!к.заполнено.some((y) => y.name === x.name)) к.заполнено.push(x); };
    for (const x of план) {
      x.e.value = x.value;
      if (x.e.value !== x.value) return '«' + x.о.label + '»: значение не принято';
      запомнить({ name: x.e.name, label: x.о.label, kind: x.о.kind, value: x.value, text: x.text, auto: false });
      пустые.delete(x.e.name);
    }
    if (!завершающее) return '';
    const far = пустые.get(ДАЛЬНИЙ) || ((x) => (x && !x.disabled && !значение(x).trim() ? x : null))(поле(form, ДАЛЬНИЙ));
    if (far && far.tagName === 'SELECT') {
      const вар = [...far.options];
      const нет = вар.find((x) => x.value !== '' && /^нет$/i.test(чисто(x.textContent))) || вар.find((x) => x.value === '0');
      if (нет) {
        far.value = нет.value;
        if (far.value === нет.value) { запомнить({ name: far.name, label: подписьПоля(form, far), kind: 'select', value: нет.value, text: чисто(нет.textContent) || 'Нет', auto: true }); пустые.delete(far.name); }
      }
    }
    const город = поле(form, ПОЛЕ.city);
    if (город && город.tagName === 'SELECT' && !город.disabled && !значение(город).trim()) {
      const вар = [...город.options].find((x) => x.value === ГОРОД_НЕ_УКАЗАН);
      if (вар) {
        город.value = вар.value;
        if (город.value === вар.value) { запомнить({ name: город.name, label: подписьПоля(form, город), kind: 'select', value: вар.value, text: чисто(вар.textContent) || 'КЦ', auto: true }); пустые.delete(город.name); }
      }
    }
    return '';
  }

  /* 2.2.9: поля, о которых CRM в ответе на запись по этой заявке сказала «необходимо заполнить» (ошибка у поля), — 30 мин помним: выбор
     оператора («Заполнить и повторить») подставим и в них, даже если в разметке они не помечены обязательными. Только имена полей */
  const ТРЕБОВАЛА = new Map();
  const требовалаCRM = (к) => { const x = ТРЕБОВАЛА.get(к.dir + ':' + к.id); return x && Н.сейчас() - x.at < 30 * 60e3 ? x.names : new Set(); };
  function запомнитьТребование(к, names) {
    const k = к.dir + ':' + к.id, x = ТРЕБОВАЛА.get(k);
    ТРЕБОВАЛА.set(k, { at: Н.сейчас(), names: new Set([...(x && Н.сейчас() - x.at < 30 * 60e3 ? x.names : []), ...names]) });
    if (ТРЕБОВАЛА.size > 200) ТРЕБОВАЛА.delete(ТРЕБОВАЛА.keys().next().value);
  }
  // не сохранили (ещё пусто) — подставленное в форму не «заполнено»: шаг «заполнено перед сохранением» убираем
  const неЗаполнено = (к) => { к.заполнено = []; к.steps = к.steps.filter((x) => x.name !== 'заполнено'); };

  /* A/B: собрать тело (вся форма как есть + правки + флаг), проверить «меняются только разрешённые поля», отправить */
  async function отправитьФорму(к, form, адрес, разрешено, флаг, цель, о) {
    if (к.браузер) {
      const пустые = пустыеОбязательные(form);
      // 2.2.5: что пусто — с вариантами формы (оператор выберет в уведомлении «Заполнить и повторить»); карточка — та, что прочитали
      if (пустые.size) { неЗаполнено(к); return провал(к, 'пусто', ТЕКСТ.пустоПоля([...пустые.values()].map((e) => подписьПоля(form, e))), { поля: описатьПоля(form, пустые), after: к.до }); }
    }
    // подставленное перед записью (выбор оператора, «Дальний выезд» «Нет») — тоже «своё» отличие тела
    for (const x of к.заполнено || []) разрешено.add(x.name);
    const тело = телоФормы(form);
    if (флаг) { тело.set(флаг.name, флаг.value); разрешено.add(флаг.name); }
    const лишние = отличия(к.исходное, тело).filter((n) => !разрешено.has(n));
    if (лишние.length) return провал(к, 'внутренняя', 'Внутренняя ошибка: меняется не только нужное (' + лишние.join(', ') + '). Ничего не отправлено.');
    // основная форма заявки — как кнопки самой CRM («Сохранить», saveAndClose: отмены, «Отказались»… — всё через form.submit()):
    // обычной отправкой, без пометки «фоновый запрос» (X-Requested-With). 09.10 фоновым запросом перенос в CRM не вставал
    // (МНЧ 1061894, 1061376). Окошки (отзыв, комментарий филиала, «Не отвечает», претензия) CRM и сама шлёт фоном — там как было.
    // Успех решает перечитанная карточка, не ответ
    const w = await записать(к, запросФормы(new URL(адрес, к.base).href, { method: 'POST', body: тело }));
    return послеЗаписи(к, w, цель, { ...о, адрес });
  }

  /* ---------- рецепты ----------
     Каждый: (к, doc, card) → {кнопка?, уже, запрет?, ошибка?, форма? (нужны город/тип/непрофильная), сделать: async () => итог}.
     Рецепт ничего не меняет в форме до сделать(): исходное тело снимается в act до записи */
  const действиеФормы = (doc) => doc.querySelector('#customerRequestForm').getAttribute('action') || '';

  function датаВФормат(былоДата, iso) {
    const [y, m, d] = iso.split('-');
    if (/^\d{4}-/.test(былоДата)) return iso;
    const р = /^\d{2}-/.test(былоДата) ? '-' : '.';
    return d + р + m + р + y;
  }
  /* Новые дата/время/причина в форме (как reschedule 1.18). Возвращает текст ошибки или '' */
  function времяВФорму(form, p, разрешено) {
    const dateEl = поле(form, 'CustomerRequest[opened_at]'), timeEl = form.querySelector('#cr_opened_at_time') || поле(form, 'cr_opened_at_time');
    if (!dateEl || !timeEl) return 'в карточке нет полей даты и времени';
    if (dateEl.disabled || timeEl.disabled) return 'дата и время в карточке недоступны для изменения';
    // меняем только то, что отличается; причину — только при настоящем переносе (в CRM её спрашивают, когда время сменили)
    const новаяДата = p.date && датаISO(dateEl.value) !== p.date, новоеВремя = p.time && времяЧЧММ(timeEl.value) !== p.time;
    if (новаяДата) { dateEl.value = датаВФормат(dateEl.value || '', p.date); разрешено.add(dateEl.name); }
    if (новоеВремя) { timeEl.value = p.time; разрешено.add(timeEl.name); }
    const r = поле(form, 'CustomerRequest[cr_form_extra][timeChangeReason]');
    if (r && (новаяДата || новоеВремя)) { r.value = p.reason || 'Клиент'; разрешено.add(r.name); }
    return '';
  }
  const времяСтоит = (c, p) => (!p.date || c.visitDate === p.date) && (!p.time || c.visitTime === p.time);
  function проверитьВремя(p) {
    if (p.date && !/^\d{4}-\d{2}-\d{2}$/.test(p.date)) return 'дата не в формате ГГГГ-ММ-ДД';
    if (p.time && !/^\d{2}:\d{2}$/.test(p.time)) return 'время не в формате ЧЧ:ММ';
    if (p.reason && !ПРИЧИНЫ_ВРЕМЕНИ.includes(p.reason)) return 'причина переноса — только Клиент / Диспетчер / Директор';
    return '';
  }
  const послеВремени = (к, p, до) => async (п) => {
    // время не менялось (то же, что было) — строки «Переносов» и не должно быть
    if ((!p.date || p.date === до.visitDate) && (!p.time || p.time === до.visitTime)) return {};
    if (п.card.changesCount > до.changesCount) return { lastChange: п.card.lastChange };
    к.warnings.push('строка в «Переносах» не появилась — CRM её не дописала');
    return {};
  };

  /* «Вернуть в «Ожидает»» / «Вернуть в работу» у отменённой заявки: ссылка cancel-transaction с data-confirm ВНУТРИ формы — браузер шлёт
     POST всей формы на адрес ссылки (yii.handleAction, раздел 9.6 живого файла); 405 — переходом по ссылке (GET), как было в 1.18 */
  function ссылкаОтмены(к, doc, card, кнопка, какая, цель, описание) {
    const form = doc.querySelector('#customerRequestForm');
    return {
      кнопка, форма: true, уже: цель(card),
      важно: (до, c) => до.statusCode !== c.statusCode,
      async сделать() {
        const a = ссылкаЗаявки(doc, 'cancel-transaction', к.id, какая);
        const адрес = new URL(a.getAttribute('href'), к.base).href;
        return отправитьФорму(к, form, адрес, new Set(), null, цель, { описание, что: (c) => c.statusName, еслиGET: адрес });
      },
    };
  }

  const РЕЦЕПТЫ = {
    /* Галочки и тип — «Сохранить» всей формы (A без флага). Прозвон ⇄ Перед выездом взаимоисключающие, как в Чатерском и Leadbot */
    fields(к, doc, card) {
      const p = к.params, set = { ...(p.set || {}) };
      if (set.callCheck === true && set.callBeforeVisit === undefined && card.flags.callBeforeVisit) set.callBeforeVisit = false;
      if (set.callBeforeVisit === true && set.callCheck === undefined && card.flags.callCheck) set.callCheck = false;
      const ключи = Object.keys(set).filter((k) => ПОЛЕ[k]);
      const лишние = Object.keys(set).filter((k) => !ПОЛЕ[k]);
      const form = doc.querySelector('#customerRequestForm');
      const сВременем = !!(p.date || p.time);
      const свои = своиКоды(к);
      const значениеПоля = (k) => (k === 'type' ? Number(set[k]) : k === 'city' ? String(set[k]) : (set[k] ? '1' : '0'));
      const одно = (c, k) => (k === 'type' ? c.type === Number(set[k]) : k === 'city' ? c.cityId === String(set[k]) : c.flags[k] === !!set[k]);
      const стоит = (c) => ключи.every((k) => одно(c, k)) && (!сВременем || времяСтоит(c, p)) && (!свои || свои.includes(c.statusCode));
      const есть = ключи.length || сВременем || нужныКомментарии(form, p);
      return {
        // город ставим этим же сохранением — пустой город в карточке не помеха
        кнопка: 's1', форма: set.city ? 'безГорода' : true,
        ошибка: лишние.length ? 'неизвестные поля: ' + лишние.join(', ') : !есть && !свои ? 'нечего менять' : сВременем ? проверитьВремя(p) : '',
        уже: !лишние.length && !!(есть || свои) && стоит(card) && !нужныКомментарии(form, p) && !(сВременем && проверитьВремя(p)),
        async сделать() {
          const разрешено = new Set();
          for (const k of ключи) {
            if (одно(card, k)) continue;
            const v = значениеПоля(k);
            const почему = поставить(form, ПОЛЕ[k], v);
            if (почему) return провал(к, 'нет поля', 'Не могу поменять «' + ГАЛОЧКА[k] + '»: ' + { нет: 'в карточке нет такого поля', закрыто: 'поле в CRM недоступно для изменения', 'нет варианта': 'в CRM нет такого варианта', 'не встало': 'значение не принято' }[почему] + '. Ничего не отправлено.');
            разрешено.add(ПОЛЕ[k]);
            // «Гарантия» — CRM сама ставит «Обычная» (скрипт формы), делаем так же
            const nc = поле(form, 'CustomerRequest[is_noncore]');
            if (k === 'type' && v === 30 && nc && !nc.disabled && nc.value !== '0') { nc.value = '0'; разрешено.add(nc.name); }
          }
          if (сВременем) { const почему = времяВФорму(form, p, разрешено); if (почему) return провал(к, 'нет поля', 'Не могу поставить время: ' + почему + '. Ничего не отправлено.'); }
          const вписано = комментарииВФорму(к, form, p, разрешено);
          const что = (c) => [...ключи.map((k) => ГАЛОЧКА[k] + ': ' + (k === 'type' ? c.type : k === 'city' ? (c.cityName || c.cityId || '—') : c.flags[k] ? 'стоит' : 'нет')),
            ...(сВременем ? [c.visitDate + ' ' + c.visitTime] : []), ...(свои ? [c.statusName] : [])].join(', ') || 'без изменений';
          return отправитьФорму(к, form, действиеФормы(doc), разрешено, null, стоит, {
            описание: [...ключи.map((k) => ГАЛОЧКА[k] + (k === 'type' || k === 'city' ? ' ' + set[k] : set[k] ? ' ✓' : ' ✗')), ...(сВременем ? [[p.date, p.time].filter(Boolean).join(' ')] : []),
              ...(свои ? [свои.map((x) => СТАТУСЫ[x]).join('/')] : [])].join(', ') || 'комментарий',
            что,
            после: async (п) => { предупредитьКомментарии(к, п.doc, вписано); return сВременем ? послеВремени(к, p, card)(п) : {}; },
          });
        },
      };
    },

    /* Перенос — как reschedule 1.18: дата, время, «Причина изменения времени» текстом; строку «Переносы» CRM дописывает сама */
    move(к, doc, card) {
      const p = к.params, form = doc.querySelector('#customerRequestForm');
      const ош = !p.date && !p.time ? 'не указаны новая дата или время' : проверитьВремя(p);
      const свои = своиКоды(к);
      const цель = (c) => времяСтоит(c, p) && (!свои || свои.includes(c.statusCode));
      return {
        кнопка: 's1', форма: true, ошибка: ош,
        уже: !ош && цель(card) && !нужныКомментарии(form, p),
        async сделать() {
          const разрешено = new Set();
          const почему = времяВФорму(form, { ...p, reason: p.reason || 'Клиент' }, разрешено);
          if (почему) return провал(к, 'нет поля', 'Не могу перенести: ' + почему + '. Ничего не отправлено.');
          const вписано = комментарииВФорму(к, form, p, разрешено);
          return отправитьФорму(к, form, действиеФормы(doc), разрешено, null, цель, {
            описание: [p.date, p.time].filter(Boolean).join(' '), что: (c) => c.visitDate + ' ' + c.visitTime,
            после: async (п) => { предупредитьКомментарии(к, п.doc, вписано); return послеВремени(к, p, card)(п); },
          });
        },
      };
    },

    /* Кнопки-флаги saveAndClose: отмены, «Отказались», «Не оформлена/Ожидает/Не создана» из уточнения и модерации, возврат из НФ, перевод */
    flag(к, doc, card) {
      const p = к.params;
      const коды = (Array.isArray(p.code) ? p.code : [p.code]).map(Number).filter((n) => ФЛАГ[n]);
      const код = коды.find((n) => card.buttons['s' + n]) || коды[0];
      const ф = ФЛАГ[код];
      if (!ф) return { ошибка: 'неизвестный код кнопки ' + JSON.stringify(p.code) };
      const form = doc.querySelector('#customerRequestForm');
      const сВременем = !!(ф.время && (p.date || p.time));
      let ош = сВременем ? проверитьВремя(p) : '';
      if (код === 30 && !p.server) ош = 'не выбрано, в какую базу отправить';
      else if (код === 30 && !card.transferServers.some((s) => s.key === p.server)) ош = 'в карточке нет направления «' + p.server + '» — в городе нет такой базы';
      if (код === 22 && !сВременем && (!card.visitDate || !card.visitTime)) ош = 'в заявке нет даты и времени визита — укажите их';
      const свои0 = своиКоды(к);
      // 2.2.9: отмена встала — в шапке «Отмена КЦ» или «Отмена» (32); «Отмена Филиала» — та же надпись у «Готов ОФ» (1020): одна цель
      const отмена = код === 10 || код === 11;
      const свои = свои0 && отмена ? сОтменами(свои0) : свои0;
      if (свои && свои0 && отмена && к.params.expect) к.params.expect.statusCode = свои;
      const target = свои || (отмена ? сОтменами(ф.target) : ф.target);
      const статусЦели = (c) => (target ? target.includes(c.statusCode) : (c.statusCode !== card.statusCode || !c.buttons.s30));
      const цель = (c) => статусЦели(c) && (!сВременем || времяСтоит(c, p));
      const ужеКоды = свои || (отмена ? сОтменами(ф.уже) : ф.уже) || ф.target;
      return {
        кнопка: 's' + код, форма: ф.город39 ? 'безГорода' : true, ошибка: ош,
        // заявка уходит из работы (2, 21, 60 → «Не оформлена»; 26 → «Не создана»; 10, 11 → отмены): пустой «Дальний выезд» — «Нет» сами
        завершающее: изРаботы(ф.target) && изРаботы(свои0 || ф.target),
        // 2.2.9: «устарело» — только если сменился статус (и время — у кнопок со временем, направления — у перевода); остальные кнопки
        // и галочки карточки этой кнопке не мешают
        важно: (до, c) => до.statusCode !== c.statusCode || (сВременем && (до.visitDate !== c.visitDate || до.visitTime !== c.visitTime))
          || (код === 30 && JSON.stringify(до.transferServers || []) !== JSON.stringify(c.transferServers || [])),
        уже: !!ужеКоды && ужеКоды.includes(card.statusCode) && (!сВременем || времяСтоит(card, p)),
        async сделать() {
          const разрешено = new Set();
          // поля, которые saveAndClose ставит сам: статус для 21/22, пустой статус → 1 для 10/11/25, пустой город → 39 для 20
          if (ф.статус) { скрытое(form, 'CustomerRequest[status]', ф.статус); разрешено.add('CustomerRequest[status]'); }
          const st = поле(form, 'CustomerRequest[status]');
          if (ф.статус1 && st && !st.value) { st.value = '1'; разрешено.add(st.name); }
          const город = поле(form, 'CustomerRequest[city_id]');
          if (ф.город39 && город && !город.value) { скрытое(form, 'CustomerRequest[city_id]', '39'); разрешено.add('CustomerRequest[city_id]'); }
          if (сВременем) { const почему = времяВФорму(form, p, разрешено); if (почему) return провал(к, 'нет поля', 'Не могу поставить время: ' + почему + '. Ничего не отправлено.'); }
          if (код === 30) {
            const s = doc.querySelector('#crTransferServerOption');
            if (s) { s.value = p.server; if (s.name) разрешено.add(s.name); }
            // до перевода — какие заявки клиента уже есть в целевой базе (только чтение): после перевода новая — та, которой не было
            const куда = СЕРВЕР_БАЗЫ[p.server], p10 = телефонЗаявки(doc);
            к.доПереноса = null;
            if (куда && p10.length === 10) { try { к.доПереноса = await номераВБазе(куда, p10); } catch (_e) { /* найдём вручную */ } }
          }
          const вписано = комментарииВФорму(к, form, p, разрешено);
          const флаг = { name: ф.name, value: код === 30 ? p.server : ф.value };
          return отправитьФорму(к, form, действиеФормы(doc), разрешено, флаг, цель, {
            changeType: p.changeType, описание: target ? СТАТУСЫ[target[0]] : 'перевод отправлен',
            после: async (п) => {
              предупредитьКомментарии(к, п.doc, вписано);
              const extra = сВременем ? await послеВремени(к, p, card)(п) : {};
              if (код === 30) Object.assign(extra, await найтиПеренесённую(к, doc, p.server));
              return extra;
            },
          });
        },
      };
    },

    /* Ссылки с data-confirm внутри формы (B): CRM шлёт POST всей формы на адрес ссылки (yii.handleAction) — так и делаем */
    link(к, doc, card) {
      const p = к.params, вид = p.link;
      if (!['take', 'release', 'toNotTaken'].includes(вид)) return { ошибка: 'неизвестная ссылка «' + вид + '»' };
      const form = doc.querySelector('#customerRequestForm');
      const свои = своиКоды(к);
      // «взята мной» — только когда это видно (имя или наш принятый «Взять»): «в работе у кого-то» успехом не считаем
      const цель = { take: (c) => c.held.yes && c.held.mine === true, release: (c) => !c.held.yes, toNotTaken: (c) => (свои || [20]).includes(c.statusCode) }[вид];
      // чужую заявку «Вернуть» за другого не нажимаем; взятую другим — не берём. Не видно, у кого, — тоже не трогаем
      const чужая = card.held.yes && card.held.mine === false, неясно = card.held.yes && card.held.mine === null;
      const запрет = вид === 'toNotTaken' ? ''
        : чужая ? (вид === 'release' ? 'заявку держит другой сотрудник — «Вернуть» за него не нажимаю' : 'заявку уже взял другой сотрудник')
          : неясно ? 'заявка уже «в работе» у сотрудника, а у вас ли — по карточке не видно; посмотрите в CRM' : '';
      return {
        // ссылка внутри формы идёт через yii.handleAction → submit формы → проверка yiiActiveForm (город, тип, непрофильная) — у всех трёх
        кнопка: вид, форма: true, уже: !запрет && цель(card),
        завершающее: вид === 'toNotTaken' && изРаботы(свои || [20]),
        // 2.2.9: «Взять» / «Вернуть» — важно, у кого заявка; «Не оформлена» — только статус
        важно: (до, c) => до.statusCode !== c.statusCode || (вид !== 'toNotTaken' && ((до.held || {}).yes !== (c.held || {}).yes || (до.held || {}).mine !== (c.held || {}).mine)),
        запрет,
        async сделать() {
          const a = ссылкаЗаявки(doc, ССЫЛКА[вид], к.id);
          const разрешено = new Set();
          const вписано = вид === 'toNotTaken' ? комментарииВФорму(к, form, { addPartner: p.addPartner }, разрешено) : {};
          return отправитьФорму(к, form, a.getAttribute('href'), разрешено, null, цель, {
            // CRM приняла «Взять» — заявка наша (до проверки: та же подпись у проверки и у следующего снимка); «Вернуть» — забываем
            послеОтвета: (р) => { if (вид === 'take' && р.вид === 'редирект') ВЗЯТО.set(к.dir + ':' + к.id, Н.сейчас()); if (вид === 'release') ВЗЯТО.delete(к.dir + ':' + к.id); },
            changeType: p.changeType, описание: { take: 'заявка за вами', release: 'заявка возвращена', toNotTaken: 'Не оформлена' }[вид],
            что: (c) => (вид === 'toNotTaken' ? c.statusName : c.held.yes ? 'в работе' : 'свободна'),
            // статус сменился, а комментария партнёра нет — дописываем отдельным «Сохранить комментарий» (статус уже честный)
            после: async (п) => (вписано.addPartner && !комментарииНаМесте(п.doc, вписано) ? дописатьПартнёру(к, п, вписано.addPartner) : {}),
          });
        },
      };
    },

    /* «Отправить в город» — обычный переход по ссылке (G), без data-confirm */
    goto(к, doc, card) {
      const свои = своиКоды(к);
      const цель = (c) => (свои ? свои.includes(c.statusCode) : c.statusCode !== 2);
      return {
        кнопка: 'promote', уже: свои ? цель(card) : [1, 4].includes(card.statusCode), важно: (до, c) => до.statusCode !== c.statusCode,
        async сделать() {
          const a = ссылкаЗаявки(doc, ССЫЛКА.promote, к.id);
          const w = await записать(к, запросФормы(new URL(a.getAttribute('href'), к.base).href, { method: 'GET' }));
          return послеЗаписи(к, w, цель, { описание: 'отправлена в город' });
        },
      };
    },

    /* «Сохранить комментарий» (C _comments_only): все четыре поля, как saveCardComments 1.18 — не присланное CRM может очистить */
    comments(к, doc) {
      const p = к.params;
      const val = (f) => { const e = doc.querySelector('#customerrequest-' + f); return e ? значение(e) : null; };
      const сейчас = { comments: val('comments'), comments_service: val('comments_service'), date_changes: val('date_changes'), partner_comment: val('partner_comment') };
      const след = { ...сейчас }, сверка = [];
      for (const f of ['comments', 'comments_service', 'partner_comment']) {
        if (p[f] === undefined || сейчас[f] === null) continue;
        const next = f === 'comments_service' ? NOTES.service(p[f]) : String(p[f]);
        if (f === 'comments_service' ? служебныйНаМесте(next, сейчас[f]) : норм(next) === норм(сейчас[f])) continue;
        след[f] = next; сверка.push([f, 'равно', след[f]]);
      }
      for (const [k, f] of [['addComment', 'comments'], ['addService', 'comments_service'], ['addPartner', 'partner_comment']]) {
        if (!p[k] || след[f] === null) continue;
        const next = f === 'comments_service' ? NOTES.mergeService(след[f], p[k]) : дописать(след[f], p[k]);
        if (f === 'comments_service' ? служебныйНаМесте(next, след[f]) : естьСтрока(след[f], p[k])) continue;
        след[f] = next;
        сверка.push([f, f === 'comments_service' ? 'равно' : 'есть', f === 'comments_service' ? след[f] : p[k]]);
      }
      const нет = [['addPartner', 'partner_comment'], ['partner_comment', 'partner_comment'], ['addComment', 'comments'], ['comments', 'comments'], ['addService', 'comments_service'], ['comments_service', 'comments_service']]
        .find(([k, f]) => p[k] !== undefined && p[k] !== '' && сейчас[f] === null);
      const цель = (c, d) => сверка.every(([f, как, t]) => { const v = значение(d.querySelector('#customerrequest-' + f));
        return f === 'comments_service' ? служебныйНаМесте(v, t) : как === 'есть' ? естьСтрока(v, t) : норм(v) === норм(t); });
      return {
        кнопка: 'saveComment', ошибка: нет ? 'в карточке нет поля «' + { partner_comment: 'Комментарий партнёра', comments: 'Комментарий', comments_service: 'Служебный' }[нет[1]] + '»' : '',
        уже: !нет && !сверка.length,
        async сделать() {
          const body = new URLSearchParams();
          const [param, token] = csrf(doc);
          body.set(param, token);
          body.set('_comments_only', 'true');
          for (const k of ['comments', 'comments_service', 'date_changes', 'partner_comment']) if (след[k] !== null) body.set(k, след[k] || '');
          const w = await записать(к, запросФормы(к.url, { method: 'POST', body, headers: AJAX }));
          if (w && w.x) { const р = разобратьОтвет(w.x); if (р.вид === 'json' && р.json && р.json.result === false) { к.steps.push({ name: 'CRM', ok: false, detail: 'result=false' }); return провал(к, 'отказ', ТЕКСТ.отказ('комментарий не принят')); } }
          return послеЗаписи(к, w, цель, { описание: 'комментарий на месте', что: () => 'комментарий без изменений' });
        },
      };
    },

    /* «Не отвечает» (C): служебный как есть + comments_service_no_answer=1 → JSON {result: новый служебный}; отметку CRM ставит сама */
    noanswer(к, doc, card) {
      const служебный = значение(doc.querySelector('#customerrequest-comments_service'));
      const цель = (c, d) => c.noAnswerCount === card.noAnswerCount + 1
        || (!!к.ответ && норм(значение(d.querySelector('#customerrequest-comments_service'))) === норм(к.ответ) && норм(к.ответ) !== норм(служебный));
      const о = { описание: 'отметок «не отвечает»: ' + (card.noAnswerCount + 1), что: (c) => 'отметок «не отвечает»: ' + c.noAnswerCount };
      return {
        кнопка: 'noAnswer', уже: false,
        async сделать() {
          const body = new URLSearchParams();
          const [param, token] = csrf(doc);
          body.set(param, token);
          body.set('comments_service', служебный);
          body.set('comments_service_no_answer', '1');
          const w = await записать(к, запросФормы(к.url, { method: 'POST', body, headers: AJAX }));
          const р = w && w.x ? разобратьОтвет(w.x) : null;
          if (!р || р.вид !== 'json') return послеЗаписи(к, w, цель, о);
          к.ответ = р.json && typeof р.json.result === 'string' ? р.json.result : '';
          к.steps.push({ name: 'CRM', ok: !!к.ответ, detail: к.ответ ? 'отметка поставлена' : 'пустой ответ' });
          if (!к.ответ) return провал(к, 'отказ', ТЕКСТ.отказ('CRM не поставила отметку «Не отвечает»'));
          return проверить(к, цель, о);
        },
      };
    },

    /* «Добавить комментарий» филиала (M): форма модалки → POST на её action → {success, content} */
    modalBranchComment(к) {
      const p = к.params;
      return {
        кнопка: 'branchComment', ошибка: String(p.text || '').trim() ? '' : 'нет текста комментария', уже: false,
        сделать: () => модалка(к, '_modal_cr_r_comment', '#crRecommCommentModalForm', { 'CrRCommentForm[comment]': String(p.text).trim() }, false,
          (d) => естьСтрока(значение(d.querySelector('#customerrequest-recommendation_comment')), p.text)),
      };
    },
    /* «Негативный отзыв» (M, multipart). В карточке отзыв не виден — проверка только по {success} */
    modalFeedback(к) {
      const p = к.params;
      const t = String(p.type || '');
      return {
        кнопка: 'feedback', ошибка: ['600', '601'].includes(t) ? '' : 'тип отзыва — 601 «КЦ Отзыв» или 600 «Филиал»', уже: false,
        сделать: () => модалка(к, '_modal_cr_feedback', '#crFeedbackModalForm',
          { 'CrFeedbackForm[type]': t, ...(p.link ? { 'CrFeedbackForm[feedback_link]': String(p.link) } : {}), ...(p.comment ? { 'CrFeedbackForm[comment]': String(p.comment) } : {}) }, true, null),
      };
    },

    /* Претензия — проверенный createClaim 1.18 (GET create-claim, тип и комментарий в режиме правки претензии) */
    claim(к, doc, card) {
      const p = к.params;
      const кат = p.category === undefined || p.category === null || p.category === '' ? '' : String(p.category);
      return {
        кнопка: 'claim', уже: false, ошибка: кат && !КАТЕГОРИИ[кат] ? 'категория претензии — 590 Всем / 591 Филиал / 592 ОКК / 593 Никто' : '',
        async сделать() {
          let до = null, былиId = [];
          try { const x = await C.claimsFor(к.dir, к.id); до = x.count; былиId = x.ids || []; } catch (_e) { /* список ОКК не открылся — сверим по номеру претензии */ }
          if (p.skipIfExists && до > 0) { к.steps.push({ name: 'проверка', ok: true, detail: 'претензия уже есть' }); return итог(к, { ok: true, already: true, after: card }); }
          // претензия по заявке уже есть (создана в CRM, из другого диалога, раньше): одна на заявку — новую не создаём, комментарий
          // и категорию старой не трогаем, в чат «Новая претензия» не пишем; новые слова клиента — «Снова звонит»
          const ужеЕсть = (id) => { к.steps.push({ name: 'проверка', ok: true, detail: 'претензия уже есть' + (id ? ' №' + id : '') });
            return провал(к, 'уже есть', 'По заявке № ' + к.id + ' претензия уже есть' + (id ? ' (№' + id + ')' : '') + ' — новую не создаю, комментарий и категорию не трогаю. '
              + 'Слова клиента — действием «Снова звонит».', { already: true, claim: { id: String(id || '') } }); };
          if (до > 0) return ужеЕсть(былиId.length ? String(Math.max(...былиId.map(Number))) : '');
          const w = await записать(к, () => C.createClaim({ dir: к.dir, id: к.id, typeNo: p.typeNo, comment: p.comment }));
          if (!w || w.hung || w.error) return послеЗаписи(к, w, () => false);
          const r = w.x || {};
          if (r.ok && r.already) return ужеЕсть(r.claimId);
          const сессия = /сессия/i.test(r.error || '');
          к.steps.push({ name: 'CRM', ok: !!r.ok, detail: r.ok ? 'претензия' + (r.claimId ? ' №' + r.claimId : '') : String(r.error || '').slice(0, 80) });
          let после = null;
          if (!r.ok && сессия) return провал(к, 'сессия', ТЕКСТ.сессия(ИМЯ[к.dir]));
          try { после = (await C.claimsFor(к.dir, к.id)).count; } catch (_e) { /* как выше */ }
          if (!r.ok) {
            // ошибка (500, красная надпись) могла прийти и после создания — решает список ОКК, иначе повтор дал бы вторую претензию
            if (до !== null && после !== null && после > до) к.warnings.push('CRM ответила «' + String(r.error || '').slice(0, 80) + '», но претензия в списке есть');
            else if (до === null || после === null) return неизвестно(к, 'список претензий не открылся', { error: ТЕКСТ.неожиданно(String(r.error || 'ошибка').slice(0, 80)) + ' Не знаю, создалась ли претензия, — повторно не отправляю.' });
            else return провал(к, 'отказ', ТЕКСТ.отказ(r.error || 'претензия не создана'));
          }
          const ок = !!r.claimId || (до !== null && после !== null && после > до);
          к.steps.push({ name: 'проверка', ok: ок, detail: ок ? 'претензия есть в CRM' : 'новой претензии не видно' });
          if (r.warn) к.warnings.push(r.warn);
          // CRM сказала «создано», а сверить не по чему (номера нет, список не открылся) — «не знаю», а не «не вышло»: повтор дал бы вторую
          if (!ок && (до === null || после === null)) return неизвестно(к, 'номера нет, список претензий не открылся', { error: ТЕКСТ.неПроверить });
          if (!ок) return провал(к, 'не проверилось', ТЕКСТ.неПроверилось('претензий: ' + (после === null ? '?' : после)));
          отметить(к, 'ok');
          // категория (по выбору в превью; по умолчанию не трогаем) — той же формой правки претензии, что тип
          const категория = кат && r.claimId ? await категорияПретензии(к, r.claimId, кат) : '';
          if (кат && !r.claimId) к.warnings.push('номер претензии не пришёл — категорию «' + КАТЕГОРИИ[кат] + '» поставьте в CRM');
          let after = card;
          try { after = (await прочитать(к)).card; } catch (_e) { /* карточка та же */ }
          return итог(к, { ok: true, after, claim: { id: r.claimId || '', url: r.url || '', typed: !!r.typed, type: r.type || '', ...(кат ? { category: категория } : {}) } });
        },
      };
    },

    /* 2.0.9: Вернуть в работу из отмены — туда, где заявка была до отмены (В пути / В работе): cancel-transaction без state.
       2.2.9: как кнопка CRM — ссылка с data-confirm внутри формы, yii.handleAction шлёт POST ВСЕЙ формы на адрес ссылки (B, как «Взять»,
       «Не оформлена»). Было — GET по ссылке (1.18): CRM сама так не делает, принимает ли — не проверено; не принимает (405) — тогда GET */
    backToWork(к, doc, card) {
      return ссылкаОтмены(к, doc, card, 'backToWork', (h) => !/[?&]state=/.test(h), (c) => !ОТМЕНЫ.includes(c.statusCode) && c.statusCode !== 1020, 'в работе');
    },

    /* Вернуть в «Ожидает» из отмены (cancel-transaction&state=1) без переноса (перенос — следующим шагом move). 2.2.9: POST формы на адрес
       ссылки, как кнопка CRM (было — GET, как 1.18) */
    awaitFromCancel(к, doc, card) {
      const свои = своиКоды(к);
      return ссылкаОтмены(к, doc, card, 'awaitFromCancel', (h) => /[?&]state=1(?!\d)/.test(h), (c) => (свои || [1]).includes(c.statusCode), 'Ожидает');
    },

    /* Город после создания. Есть «Сохранить город» (#actSaveCity, модерация) — как она: C, $.post(update?id=N, {_csrf, city_id}) →
       {result, errorMessage}; нет (Ожидает, В пути, На уточнении) — «Сохранить» всей формы с другим city_id (A, как оператор в CRM).
       Успех — только по перечитанной карточке (город в ней — новый) */
    city(к, doc, card) {
      const p = к.params, want = String(p.cityId == null ? '' : p.cityId).trim();
      const form = doc.querySelector('#customerRequestForm');
      const sel = поле(form, 'CustomerRequest[city_id]');
      const вариант = sel && sel.tagName === 'SELECT' ? [...sel.options].find((o) => o.value === want) : null;
      const кнопкой = card.buttons.saveCity;
      const имя = вариант ? чисто(вариант.textContent) : want;
      const цель = (c) => String(c.cityId || '') === want;
      const ош = !/^\d+$/.test(want) ? 'не выбран город' : !sel ? 'в карточке нет поля «Город»' : sel.disabled ? 'поле «Город» в CRM недоступно для изменения'
        : !вариант ? 'в CRM нет такого города (№ ' + want + ')' : '';
      const о = { описание: 'город «' + имя + '»', что: (c) => 'город ' + (c.cityName || c.cityId || '—') };
      return {
        // «Сохранить город» шлёт только city_id (проверки формы нет); «Сохранить» — вся форма: тип и непрофильная должны быть
        кнопка: кнопкой ? 'saveCity' : 's1', форма: кнопкой ? false : 'безГорода', ошибка: ош, уже: !ош && цель(card),
        async сделать() {
          if (!кнопкой) {
            const разрешено = new Set();
            const почему = поставить(form, 'CustomerRequest[city_id]', want);
            if (почему) return провал(к, 'нет поля', 'Не могу поменять город: ' + почему + '. Ничего не отправлено.');
            разрешено.add('CustomerRequest[city_id]');
            return отправитьФорму(к, form, действиеФормы(doc), разрешено, null, цель, о);
          }
          const body = new URLSearchParams();
          const [param, token] = csrf(doc);
          body.set(param, token);
          body.set('city_id', want);
          const w = await записать(к, запросФормы(к.url, { method: 'POST', body, headers: AJAX }));
          const р = w && w.x ? разобратьОтвет(w.x) : null;
          if (!р || р.вид !== 'json') return послеЗаписи(к, w, цель, о);
          const ок = !!(р.json && р.json.result);
          к.steps.push({ name: 'CRM', ok: ок, detail: ок ? '«Сохранить город»: принято' : 'город не сохранён' });
          if (!ок) {
            // CRM сказала «не сохранён» — сверяем с карточкой: стоит новый город — сделано, иначе — её слова
            let п = null;
            try { п = await прочитать(к); } catch (_e) { /* ниже — отказ по словам CRM */ }
            if (п && цель(п.card)) { к.warnings.push('CRM ответила «не сохранён», но в карточке новый город'); отметить(к, 'ok'); return итог(к, { ok: true, after: п.card }); }
            return провал(к, 'отказ', ТЕКСТ.отказ(String((р.json && (р.json.errorMessage || р.json.message)) || 'город не сохранён').slice(0, 120)), п ? { after: п.card } : {});
          }
          return проверить(к, цель, о);
        },
      };
    },

    /* Вид работ и вид услуг после создания — «Сохранить» всей формы (A). Вид услуг — только из списка, который CRM даёт для этого
       вида работ (как скрипт формы при смене «Вида работ»); сменили вид работ без вида услуг — поле очищается, как в CRM */
    worktype(к, doc, card) {
      const p = к.params;
      const appl = String(p.applId == null ? '' : p.applId).trim();
      const sub = p.subId === undefined || p.subId === null ? null : String(p.subId).trim();
      const form = doc.querySelector('#customerRequestForm');
      const aEl = поле(form, 'CustomerRequest[appliance_type_id]'), sEl = поле(form, 'CustomerRequest[appliance_sub_type_id]');
      const вариант = aEl && aEl.tagName === 'SELECT' ? [...aEl.options].find((o) => o.value === appl) : null;
      const ош = !/^\d+$/.test(appl) ? 'не выбран вид работ' : !aEl ? 'в карточке нет поля «Вид работ»' : aEl.disabled ? '«Вид работ» в CRM недоступен для изменения'
        : !вариант ? 'в CRM нет такого вида работ (№ ' + appl + ')' : sub && !/^\d+$/.test(sub) ? 'неверный вид услуг'
          : sub && !sEl ? 'в карточке нет поля «Вид услуг»' : sub && sEl.disabled ? '«Вид услуг» в CRM недоступен для изменения' : '';
      // вид работ сменили, а вид услуг не задан — CRM очищает поле: цель — пусто
      const нужныйВид = sub !== null ? sub : appl !== String(card.applId || '') && sEl ? '' : null;
      const цель = (c) => String(c.applId || '') === appl && (нужныйВид === null || String(c.subId || '') === нужныйВид);
      const имяВида = вариант ? чисто(вариант.textContent) : appl;
      return {
        кнопка: 's1', форма: true, ошибка: ош, уже: !ош && цель(card),
        async сделать() {
          const разрешено = new Set();
          if (sEl && !sEl.disabled && нужныйВид !== null) {
            const ужеЕсть = [...sEl.options].some((o) => o.value === нужныйВид);
            if (appl !== String(card.applId || '') || !ужеЕсть) {
              // как скрипт CRM: варианты «Вида услуг» — для нового вида работ
              let list = null;
              try { list = await видыУслуг(к, doc, card, appl); } catch (e) {
                if (/Сессия/.test(String(e && e.message))) return провал(к, 'сессия', ТЕКСТ.сессия(ИМЯ[к.dir]));
                if (нужныйВид) return провал(к, 'чтение', 'Список видов услуг для «' + имяВида + '» CRM не дала (' + String((e && e.message) || e).slice(0, 80) + '). Ничего не отправлено.');
              }
              if (нужныйВид && !(list || []).some((x) => x.id === нужныйВид)) return провал(к, 'ввод', 'Не делаю: у вида работ «' + имяВида + '» в CRM нет такого вида услуг (№ ' + нужныйВид + '). Ничего не сделано.');
              const d = sEl.ownerDocument, пустой = d.createElement('option');
              пустой.value = ''; пустой.textContent = 'Выберите';
              sEl.replaceChildren(пустой, ...(list || []).map((x) => { const o = d.createElement('option'); o.value = x.id; o.textContent = x.name; return o; }));
            }
            sEl.value = нужныйВид;
            if (sEl.value !== нужныйВид) return провал(к, 'нет поля', 'Не могу поставить вид услуг: значение не принято. Ничего не отправлено.');
            разрешено.add(sEl.name);
          }
          if (aEl.value !== appl) { aEl.value = appl; разрешено.add(aEl.name); }
          const вид = (c) => (c.applName || c.applId || '—') + (c.hasSub ? ' / ' + (c.subName || c.subId || 'вид услуг не выбран') : '');
          return отправитьФорму(к, form, действиеФормы(doc), разрешено, null, цель, { описание: 'вид работ «' + имяВида + '»', что: (c) => 'вид работ ' + вид(c) });
        },
      };
    },
  };

  /* Категория претензии: форма правки (#claimEditForm, _update=1) → только CrClaim[category_id] → POST → перечитать.
     Претензия уже создана — неудача здесь только предупреждение. Возвращает поставленный код или '' */
  const КАТЕГОРИИ = { 590: 'Всем', 591: 'Филиал', 592: 'ОКК', 593: 'Никто' };
  async function категорияПретензии(к, claimId, кат) {
    const адрес = к.base + '/admin/domain/cr-claim/view?id=' + claimId + '&_edit_mode=1';
    const форма = (doc) => [...doc.querySelectorAll('form')].find((f) => /_update=1/.test(f.getAttribute('action') || ''));
    const вручную = (почему) => { к.steps.push({ name: 'категория', ok: false, detail: почему }); к.warnings.push('категория претензии не поставлена (' + почему + ') — выберите «' + КАТЕГОРИИ[кат] + '» в CRM'); return ''; };
    let doc;
    try { doc = await fetchDoc(адрес); } catch (_e) { return вручную('форма претензии не открылась'); }
    const f = форма(doc), sel = f && поле(f, 'CrClaim[category_id]');
    if (!sel || ![...sel.options].some((o) => o.value === кат)) return вручную('в форме нет такой категории');
    if (sel.value === кат) { к.steps.push({ name: 'категория', ok: true, detail: КАТЕГОРИИ[кат] + ' (уже стояла)' }); return кат; }
    const исходное = телоФормы(f);
    sel.value = кат;
    const тело = телоФормы(f);
    if (отличия(исходное, тело).some((n) => n !== 'CrClaim[category_id]')) return вручную('внутренняя ошибка формы');
    const w = await записать(к, запросФормы(new URL(f.getAttribute('action'), к.base).href, { method: 'POST', body: тело, headers: AJAX }));
    отметить(к, 'ok');            // претензия есть — повтор того же ключа второй не создаст
    if (!w || w.hung || w.error) return вручную('CRM не ответила — проверьте');
    try {
      const f2 = форма(await fetchDoc(адрес)), s2 = f2 && поле(f2, 'CrClaim[category_id]');
      if (s2 && s2.value === кат) { к.steps.push({ name: 'категория', ok: true, detail: КАТЕГОРИИ[кат] }); return кат; }
    } catch (_e) { /* ниже */ }
    return вручную('после сохранения в форме другая');
  }

  function csrf(doc) {
    const param = (doc.querySelector('meta[name="csrf-param"]') || {}).content || '_csrf-frontend';
    const token = (doc.querySelector('meta[name="csrf-token"]') || {}).content || значение(doc.querySelector('#customerRequestForm input[name="' + param + '"]'));
    return [param, token];
  }

  /* Модалка: GET формы (X-Requested-With) → свои поля → POST на action формы → {success}. Отличие — только свои поля */
  async function модалка(к, параметр, селектор, поля, multipart, видноВКарточке) {
    let форма;
    try {
      const r = await C._внутр.getСрок(к.url + '&' + параметр + '=1', { credentials: 'include', headers: AJAX });
      const doc = new DOMParser().parseFromString(await r.text(), 'text/html');
      if (doc.querySelector('input[type="password"], [name^="LoginForm["]')) return провал(к, 'сессия', ТЕКСТ.сессия(ИМЯ[к.dir]));
      форма = doc.querySelector(селектор) || [...doc.querySelectorAll('form')].find((f) => Object.keys(поля).some((n) => f.elements[n]));
    } catch (e) { return итог(к, ошибкаЧтения(к, e)); }
    if (!форма) return провал(к, 'неожиданно', ТЕКСТ.неожиданно('форма модалки не открылась'));
    const исходное = телоФормы(форма);
    for (const [n, v] of Object.entries(поля)) {
      const почему = поставить(форма, n, v);
      if (почему) return провал(к, 'нет поля', 'В форме CRM нет поля «' + n + '» (' + почему + '). Ничего не отправлено.');
    }
    const тело = телоФормы(форма);
    const лишние = отличия(исходное, тело).filter((n) => !(n in поля));
    if (лишние.length) return провал(к, 'внутренняя', 'Внутренняя ошибка: меняется не только нужное (' + лишние.join(', ') + '). Ничего не отправлено.');
    let body = тело;
    if (multipart) {
      // как new FormData(form): пустое поле файла уходит пустым файлом
      body = new FormData();
      for (const e of форма.elements) {
        if (!e.name || e.disabled) continue;
        if (e.type === 'file') body.append(e.name, new Blob([], { type: 'application/octet-stream' }), '');
        else if (e.type === 'checkbox' || e.type === 'radio') { if (e.checked) body.append(e.name, e.value || '1'); }
        else if (e.tagName === 'BUTTON' || e.type === 'submit') continue;
        else body.append(e.name, e.value ?? '');
      }
    }
    const w = await записать(к, запросФормы(new URL(форма.getAttribute('action') || к.url, к.base).href, { method: 'POST', body, headers: AJAX }));
    if (!w || w.hung || w.error) return послеЗаписи(к, w, () => false);
    const р = разобратьОтвет(w.x);
    if (р.вид === 'сессия') return провал(к, 'сессия', ТЕКСТ.сессия(ИМЯ[к.dir]));
    if (р.вид === 'ошибки') { к.steps.push({ name: 'CRM', ok: false, detail: р.вид }); return провал(к, 'отказ', ТЕКСТ.отказ(р.ошибки.slice(0, 2).join('; '))); }
    // 500 или непонятный ответ: отзыв по карточке не проверить — «не знаю», тот же ключ второй раз не отправит
    if (р.вид !== 'json') return неизвестно(к, р.кратко || р.вид, { error: ТЕКСТ.неожиданно(р.кратко || р.вид) + ' Не знаю, сохранилось ли, — повторно не отправляю.' });
    const ок = !!(р.json && р.json.success);
    к.steps.push({ name: 'CRM', ok: ок, detail: ок ? 'CRM ответила: принято' : String((р.json && р.json.message) || 'success=false').slice(0, 80) });
    if (!ок) return провал(к, 'отказ', ТЕКСТ.отказ(String((р.json && р.json.message) || 'форма не принята').slice(0, 120)));
    отметить(к, 'ok');
    let п = null;
    try { п = await прочитать(к); } catch (_e) { /* принято — карточку покажем по следующему снимку */ }
    if (п && видноВКарточке && !видноВКарточке(п.doc)) к.warnings.push('CRM ответила «принято», но в карточке текста не видно — проверьте');
    return итог(к, { ok: true, ...(п ? { after: п.card } : {}) });
  }

  /* «Перевести в Не оформлена»: статус сменился, а комментария партнёра нет — отдельным «Сохранить комментарий» */
  async function дописатьПартнёру(к, п, текст) {
    const e = п.doc.querySelector('#customerrequest-partner_comment');
    if (!e) { к.warnings.push('комментарий партнёра не записан (поля нет) — впишите в CRM: «' + текст + '»'); return {}; }
    const body = new URLSearchParams();
    const [param, token] = csrf(п.doc);
    body.set(param, token);
    body.set('_comments_only', 'true');
    const v = (s) => значение(п.doc.querySelector(s));
    body.set('comments', v('#customerrequest-comments'));
    body.set('comments_service', v('#customerrequest-comments_service'));
    body.set('date_changes', v('#customerrequest-date_changes'));
    body.set('partner_comment', дописать(v('#customerrequest-partner_comment'), текст));
    const w = await записать(к, запросФормы(к.url, { method: 'POST', body, headers: AJAX }));
    let ок = false;
    if (w && w.x) { try { const d = (await прочитать(к)).doc; ок = естьСтрока(значение(d.querySelector('#customerrequest-partner_comment')), текст); } catch (_e) { /* ниже */ } }
    const неЗнаю = !w || w.hung || w.error;
    к.steps.push({ name: 'комментарий', ok: ок, detail: ок ? 'комментарий партнёра записан' : неЗнаю ? 'нет ответа CRM' : 'комментарий партнёра не записался' });
    if (!ок) к.warnings.push((неЗнаю ? 'не знаю, записался ли комментарий партнёра — проверьте в CRM' : 'комментарий партнёра не записался — впишите в CRM') + ': «' + текст + '»');
    отметить(к, 'ok');
    return {};
  }

  /* Перевод в другую базу: новую заявку ищем по телефону клиента в целевой базе (внутри offscreen; наружу — только номер) */
  const вариантыНомера = (p) => [`+7 ${p.slice(0, 3)}-${p.slice(3, 6)}-${p.slice(6, 8)}-${p.slice(8)}`, `+7 ${p.slice(0, 3)}-${p.slice(3, 6)}-${p.slice(6)}`, '7' + p, '8' + p, p];
  function телефонЗаявки(doc) {
    const e = doc.querySelector('[name="CustomerRequest[customer_id]"]');
    const m = ((e ? e.textContent : '') + ' ' + (doc.body ? doc.body.textContent : '')).match(/\+7[\s(]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}/);
    return m ? m[0].replace(/\D/g, '').slice(-10) : '';
  }
  async function номераВБазе(dir, p10) {
    const ids = new Set();
    for (const v of вариантыНомера(p10)) {
      const u = new URL(BASES[dir] + ПУТЬ + 'index');
      u.searchParams.set('CRSearch[phone]', v);
      const doc = await fetchDoc(u.href);
      for (const a of doc.querySelectorAll('a[href*="customer-request/update?id="]')) { const m = (a.getAttribute('href') || '').match(/[?&]id=(\d+)/); if (m) ids.add(m[1]); }
      if (ids.size) break;
    }
    return ids;
  }
  async function найтиПеренесённую(к, doc, server) {
    const куда = СЕРВЕР_БАЗЫ[server];
    const p10 = телефонЗаявки(doc);
    const вручную = () => { к.warnings.push('перевод отправлен, новую заявку в ' + (ИМЯ[куда] || 'другой базе') + ' найдите вручную'); return {}; };
    if (!куда || p10.length !== 10) return вручную();
    const до = к.доПереноса;
    for (let i = 0; i < Н.попыткиПереноса; i++) {
      if (i) await Н.пауза(Н.паузаПереноса);
      let ids;
      try { ids = await номераВБазе(куда, p10); } catch (_e) { continue; }
      const новые = [...ids].filter((x) => до && !до.has(x)).map(Number).sort((a, b) => b - a);
      if (новые.length) {
        к.steps.push({ name: 'новая заявка', ok: true, detail: ИМЯ[куда] + ' № ' + новые[0] });
        return { newRequest: { dir: куда, id: String(новые[0]), url: BASES[куда] + ПУТЬ + 'update?id=' + новые[0] } };
      }
    }
    return вручную();
  }

  /* ---------- вход ---------- */

  async function snap(a) {
    a = a || {};
    const к = { dir: a.dir, id: String(a.id || '') };
    if (!BASES[к.dir] || !/^\d+$/.test(к.id)) return { ok: false, code: 'нет заявки', error: 'нет заявки' };
    к.base = BASES[к.dir];
    к.url = BASES[к.dir] + ПУТЬ + 'update?id=' + к.id;
    let п;
    try { п = await прочитать(к); } catch (e) { return ошибкаЧтения(к, e); }
    const out = { ok: true, card: п.card };
    // дополнительно (только чтение): подробности для «Что в заявке», претензии с № и статусом, виды услуг для вида работ.
    // Не прочиталось дополнительное — снимок всё равно отдаём (со словами, что не так)
    if (a.details) { try { out.details = подробностиКарточки(п.doc); } catch (e) { out.details = { error: String((e && e.message) || e).slice(0, 80) }; } }
    if (a.claims) {
      try { out.claims = { ok: true, ...(await претензииЗаявки(к)) }; } catch (e) { out.claims = { ok: false, error: String((e && e.message) || e).replace(/\d{4,}/g, '…').slice(0, 100) }; }
    }
    if (a.subFor !== undefined && a.subFor !== null && a.subFor !== '') {
      const applId = String(a.subFor);
      if (!/^\d+$/.test(applId)) out.subTypes = { ok: false, applId, error: 'неверный вид работ' };
      else if (!п.card.hasSub) out.subTypes = { ok: true, applId, list: [], нетПоля: true };
      else { try { out.subTypes = { ok: true, applId, list: await видыУслуг(к, п.doc, п.card, applId) }; } catch (e) { out.subTypes = { ok: false, applId, error: String((e && e.message) || e).slice(0, 120) }; } }
    }
    return out;
  }

  /* «Проверить»: перечитать карточку и сказать, стоит ли цель. Ничего не пишет и замок не берёт.
     Не сделано и прошлый запрос уже не висит — снимаем «не знаю» в журнале: оператор может нажать ещё раз */
  async function проверитьБезЗаписи(к) {
    let п;
    try { п = await прочитать(к); } catch (e) { return { ...ошибкаЧтения(к, e), steps: [{ name: 'карточка', ok: false, detail: 'не открылась' }] }; }
    const { doc, card } = п;
    к.до = card;
    к.steps.push({ name: 'карточка', ok: true, detail: card.statusName || '?' });
    const был = к.key && ЖУРНАЛ.get(к.key);
    if (НЕ_ПРОВЕРИТЬ.has(к.recipe)) return итог(к, { ok: false, unknown: true, code: 'не проверить', error: ТЕКСТ.неПроверить, after: card });
    const р = РЕЦЕПТЫ[к.recipe](к, doc, card);
    const e = безПлюсов(к.params.expect);
    if (р.уже && ожиданиеСбылось(e, card)) {
      if (был && был.итог === 'unknown') отметить(к, 'ok');
      к.steps.push({ name: 'проверка', ok: true, detail: 'в карточке уже стоит' });
      return итог(к, { ok: true, already: true, checked: true, after: card });
    }
    const сейчас = описатьКарточку(e, card);
    const идёт = висит(к.dir + ':' + к.id);
    if (был && был.итог === 'unknown' && !идёт) ЖУРНАЛ.delete(к.key);
    к.steps.push({ name: 'проверка', ok: false, detail: 'в карточке «' + сейчас + '»' });
    return итог(к, { ok: false, notDone: true, checked: true, code: 'не сделано', error: идёт ? ТЕКСТ.ещёИдёт(сейчас) : ТЕКСТ.неСделано(сейчас), after: card });
  }

  async function act(a) {
    a = a || {};
    // 2.2.5: выбор оператора для пустых обязательных полей — рядом с params или внутри (экран кладёт в params шага)
    const p0 = { ...(a.params || {}) };
    const заполнить = нормЗаполнить(a.заполнить !== undefined ? a.заполнить : p0.заполнить);
    delete p0.заполнить;
    const н = нормПарамы(a.recipe, p0, a.expect);
    const к = { dir: a.dir, id: String(a.id || ''), recipe: a.recipe, params: н.p, key: ключШага(a.key, a.recipe), steps: [], warnings: [], заполнить };
    if (!BASES[к.dir] || !/^\d+$/.test(к.id)) return { ok: false, code: 'нет заявки', error: 'нет заявки', steps: [] };
    if (!РЕЦЕПТЫ[к.recipe]) return { ok: false, code: 'рецепт', error: 'неизвестное действие «' + к.recipe + '»', steps: [] };
    if (н.ошибка) return { ok: false, code: 'ввод', error: 'Не делаю: ' + н.ошибка + '. Ничего не сделано.', steps: [] };
    к.base = BASES[к.dir];
    к.url = к.base + ПУТЬ + 'update?id=' + к.id;
    if (a.check) return проверитьБезЗаписи(к);
    const замок = к.dir + ':' + к.id;
    const был = к.key && ЖУРНАЛ.get(к.key);
    const былБезОтвета = был && был.итог === 'unknown' && Н.сейчас() - был.at < Н.памятьНеизвестных;
    if (висит(замок) && былБезОтвета) return { ok: false, unknown: true, code: 'нет ответа', error: ТЕКСТ.раньшеБезОтвета(чч(был.at)), steps: [] };
    if (ЗАНЯТО.has(замок) || висит(замок)) return { ok: false, busy: true, code: 'занято', error: ТЕКСТ.занято(к.id), steps: [] };
    ЗАНЯТО.add(замок);
    try {
      let п;
      try { п = await прочитать(к); } catch (e) { return { ...ошибкаЧтения(к, e), steps: [{ name: 'карточка', ok: false, detail: 'не открылась' }] }; }
      const { doc, card } = п;
      к.до = card;
      к.ошибкиБыли = new Set(formErrors(doc));
      к.steps.push({ name: 'карточка', ok: true, detail: card.statusName || '?' });
      // статус по шапке не прочитался (CRM поменяла вёрстку) — «уже?» и проверка после записи ослепли: не пишем
      if (!card.statusCode) return итог(к, { ok: false, code: 'неожиданно', error: ТЕКСТ.неожиданно('в карточке не нашёл статус заявки'), after: card });
      const р = РЕЦЕПТЫ[к.recipe](к, doc, card);
      к.завершающее = !!р.завершающее;
      const уже = !!р.уже && ожиданиеСбылось(безПлюсов(к.params.expect), card);
      // журнал: прошлая запись без ответа — повтор не шлём (если уже стоит — «сделано»); неидемпотентное только что сделано — второй раз не делаем
      if (былБезОтвета) {
        if (уже) return итог(к, { ok: true, already: true, after: card });
        return итог(к, { ok: false, unknown: true, code: 'нет ответа', error: ТЕКСТ.раньшеБезОтвета(чч(был.at)), after: card });
      }
      if (был && был.итог === 'ok' && НЕИДЕМПОТЕНТНЫЕ.has(к.recipe) && Н.сейчас() - был.at < Н.памятьСделанных) {
        к.steps.push({ name: 'проверка', ok: true, detail: 'только что сделано (' + чч(был.at) + ')' });
        return итог(к, { ok: true, already: true, repeat: true, after: card });
      }
      // тот же ключ только что сделан и цель стоит (двойной щелчок по старому превью) — «уже сделано», а не «устарело»
      if (был && был.итог === 'ok' && уже) { к.steps.push({ name: 'проверка', ok: true, detail: 'уже сделано (' + чч(был.at) + ')' }); return итог(к, { ok: true, already: true, after: card }); }
      if (a.expectSig && card.sig !== a.expectSig) {
        // 2.2.9: снимок превью — от экрана (before; его подпись — та, что ждём) или из памяти offscreen
        const до = (a.before && typeof a.before === 'object' && a.before.sig === a.expectSig ? a.before : null) || снимокПоПодписи(к.dir, к.id, a.expectSig);
        const [было, стало] = описатьИзменение(до, card);
        // 2.2.9: изменилось то, что этому действию не важно (другие кнопки CRM, галочки — для отмены), — делаем; важное или «что было» не
        // знаем — как раньше, «устарело» (жалоба 14.10: отмена вставала на «кнопки CRM одни / другие», хотя отмене они не мешают)
        if (!до || !р.важно || р.важно(до, card)) return итог(к, { ok: false, stale: true, code: 'устарело', error: ТЕКСТ.устарело(было, стало), after: card });
        к.steps.push({ name: 'проверка', ok: true, detail: 'карточка изменилась (было «' + было + '», стало «' + стало + '»), но не то, что важно для действия' });
      }
      if (уже) { к.steps.push({ name: 'проверка', ok: true, detail: 'уже сделано — CRM не трогаю' }); return итог(к, { ok: true, already: true, after: card }); }
      if (р.запрет) return итог(к, { ok: false, code: 'запрет', error: 'Не делаю: ' + р.запрет + '. Ничего не сделано.', after: card });
      if (р.кнопка && !card.buttons[р.кнопка]) return итог(к, { ok: false, noButton: true, code: 'нет кнопки', error: ТЕКСТ.нетКнопки(к.id, НАДПИСЬ[р.кнопка] || р.кнопка, card.statusName || '?'), after: card });
      if (р.ошибка) return итог(к, { ok: false, code: 'ввод', error: 'Не делаю: ' + р.ошибка + '. Ничего не сделано.', after: card });
      // исходное тело — до любых правок (и до подстановки в пустые поля): отличия от него сверяем перед записью
      const form = doc.querySelector('#customerRequestForm');
      к.исходное = телоФормы(form);
      к.браузер = браузерПроверяет(doc, р.кнопка);
      if (р.форма) {
        // 2.2.5: выбор оператора и «Дальний выезд» «Нет» у завершающих — в пустые обязательные поля; неверный вариант — отказ до записи
        const з = заполнитьПустые(к, form, р);
        if (з.ошибка) return итог(к, { ok: false, code: 'ввод', error: 'Не делаю: ' + з.ошибка + '. Ничего не сделано.', ...(з.поля.length ? { поля: з.поля } : {}), after: card });
        // город / тип / непрофильная пусты — yiiActiveForm не отправит; что выбрать — списком (у submit-кнопки — и остальные пустые [required])
        if (!обязательныеЕсть(doc, р.форма === 'безГорода')) {
          const пустые = пустыеДляЗаполнения(form, р.форма === 'безГорода');
          if (!к.браузер) for (const n of [...пустые.keys()]) if (!ОБЯЗ_YII[n]) пустые.delete(n);
          неЗаполнено(к);
          return итог(к, { ok: false, code: 'пусто', error: ТЕКСТ.пусто, ...(пустые.size ? { поля: описатьПоля(form, пустые) } : {}), after: card });
        }
      }
      try { return await р.сделать(); } catch (e) {
        // сбой в коде после отправки — дошло ли, не знаем: как «нет ответа» (тот же ключ второй раз не пройдёт)
        const m = String((e && e.message) || e).slice(0, 60);
        if (к.записано) return неизвестно(к, 'сбой после записи: ' + m);
        return провал(к, 'неожиданно', ТЕКСТ.неожиданно('сбой расширения: ' + m));
      }
    } finally { ЗАНЯТО.delete(замок); }
  }

  return {
    snap, act, разобрать, подпись, кодСтатуса, описатьИзменение, СТАТУСЫ, ТЕКСТ, КНОПКИ, ФЛАГИ, РЕЦЕПТЫ: Object.keys(РЕЦЕПТЫ),
    подробности: подробностиКарточки, статусПретензии, маскаТел,
    _настройки: Н,
    нормПарамы, ожиданиеСбылось,
    _сброс: () => { ЗАНЯТО.clear(); ВИСИТ.clear(); ЖУРНАЛ.clear(); СНИМКИ.clear(); ВЗЯТО.clear(); ТРЕБОВАЛА.clear(); },
  };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = CRM_ACT;
