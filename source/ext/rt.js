/* LeadChat → Заявка: приёмник «слуха» (мир расширения, document_start).
   Узнаёт у rt-main.js случайное имя канала ДО скриптов страницы, копит выжимки и состояние сокета
   до запуска content.js (document_idle; не больше 300 событий). Сам ничего не делает: решает content.js, и только ведущая вкладка. */
(() => {
  if (window.__lczRt) return;
  // маршрут: rt-main.js подменил history — о смене адреса скажет событием rt:route (content.js обходит страницу реже)
  const RT = window.__lczRt = { канал: '', n: 0, открыт: false, кадрAt: 0, открытAt: 0, закрытAt: 0, код: 0, событий: 0, плохих: 0,
    маршрут: false, буфер: [], слушатели: [] };
  const ПРИВЕТ = 'lcz-rt-hello', ЗОВ = 'lcz-rt-ask', ЕСТЬ = 'lcz-rt-ok';
  const ИД = /^[\w-]{1,64}$/;
  function наСобытие(ev) {
    let e;
    try { e = JSON.parse(String(ev.detail || '')); } catch (_e) { RT.плохих++; return; }
    if (!e || typeof e.t !== 'string' || (e.id && !ИД.test(e.id))) { RT.плохих++; return; }
    const now = Date.now();
    if (/^rt:/.test(e.t)) {
      if (typeof e.n === 'number' && e.n < RT.n) return;                 // старый сокет (переподключение) — его закрытие не про нас
      RT.n = e.n || RT.n;
      if (e.t === 'rt:open') { RT.открыт = true; RT.открытAt = now; RT.кадрAt = now; }
      if (e.t === 'rt:alive') RT.кадрAt = now;
      if (e.t === 'rt:close') { RT.открыт = false; RT.закрытAt = now; RT.код = e.code || 0; }
      // LeadChat сам бросил сокет (нет pong'а — WsClient.ts; ошибка; выход) или pong'а нет 12 с: «не открыт» сразу, не ждём onclose
      // (на мёртвом пути он приходит через минуту). Закрытие старого сокета (n меньше) отсеяно выше
      if (e.t === 'rt:closing') { RT.открыт = false; RT.закрытAt = now; }
      if (e.t === 'rt:socket') RT.открыт = false;
      // смена адреса до запуска content.js не копится: он сам сверит диалог при запуске
      if (e.t === 'rt:route' && !RT.слушатели.length) return;
    } else { RT.кадрAt = now; RT.событий++; }
    // строка очереди — только объект того же диалога (иначе content.js дочитает её сам)
    if (e.row && (typeof e.row !== 'object' || e.row.id !== e.id)) delete e.row;
    e.пришло = now;                                                      // когда услышали (e.at — время самого сообщения LeadChat)
    if (!RT.слушатели.length) { RT.буфер.push(e); if (RT.буфер.length > 300) RT.буфер.shift(); return; }
    for (const fn of RT.слушатели) { try { fn(e); } catch (_e) { /* сбой обработчика не роняет приём */ } }
  }
  function наПривет(ev) {
    try {
      const m = JSON.parse(String(ev.detail || ''));
      if (RT.канал || !m || m.v !== 1 || !/^lcz-rt-[0-9a-f-]{32,36}$/.test(String(m.канал))) return;
      RT.канал = m.канал; RT.маршрут = m.маршрут === true;
      document.removeEventListener(ПРИВЕТ, наПривет, true);
      document.addEventListener(RT.канал, наСобытие, true);
      document.dispatchEvent(new CustomEvent(ЕСТЬ));
    } catch (_e) { /* нет канала — content.js останется на опросе */ }
  }
  document.addEventListener(ПРИВЕТ, наПривет, true);
  document.dispatchEvent(new CustomEvent(ЗОВ));
  // content.js подписывается, когда запустится; накопленное отдаём сразу и по порядку
  RT.on = (fn) => { RT.слушатели.push(fn); for (const e of RT.буфер.splice(0)) { try { fn(e); } catch (_e) { /* дальше */ } } };
  // «сокет жив»: открыт и кадры шли последние 75 с (LeadChat шлёт ping раз в 25 с, сервер отвечает pong)
  RT.живой = () => !!(RT.канал && RT.открыт && Date.now() - RT.кадрAt < 75e3);
})();
