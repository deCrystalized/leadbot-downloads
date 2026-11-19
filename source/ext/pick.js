/* ВЫБОР ВИДА РАБОТ И ВИДА УСЛУГ ПО РЕГЛАМЕНТУ. ИИ получает раздел регламента своей базы,
   суть заявки и ТОЛЬКО варианты из списка CRM (с подсказками CRM) и называет номер варианта.
   Номера, которого нет в списке, не бывает: такой ответ отбрасывается. */
const LC_PICK = (() => {
  const РАЗДЕЛ = { kp: ['kp'], mnc: ['mnc', 'bt'], bt: ['bt'] };   // в МНЧ «Бытовая техника» и «Телевизоры» — по правилам БТ
  const ИМЯ = { kp: 'КП', mnc: 'МНЧ', bt: 'БТ' };

  function prompt(o) {
    const R = (typeof LC_REGLAMENT !== 'undefined' ? LC_REGLAMENT : o.reglament) || {};
    const рег = (РАЗДЕЛ[o.dir] || []).map((k) => R[k] || '').join('\n\n') + (R.extra ? '\n\n' + R.extra : '');
    const что = o.level === 'sub' ? 'вид услуг' : 'вид работ';
    const sys = 'Ты старший диспетчер лид-центра. Выбираешь ' + что + ' для заявки в CRM строго по регламенту компании. '
      + 'Выбирать можно только из перечисленных вариантов. Ответ — один JSON без пояснений вокруг.';
    const варианты = o.list.map((x) => `${x.id} — ${x.text}` + (o.hints && o.hints[x.id] ? ` (подсказка CRM: ${o.hints[x.id]})` : '')).join('\n');
    const task = [
      'Регламент «Виды работ» базы ' + (ИМЯ[o.dir] || '') + ':', рег.slice(0, 16000), '',
      'Заявка:',
      o.problem ? 'Суть: ' + o.problem : '',
      o.topics && o.topics.length ? 'Предметы: ' + o.topics.join(', ') : '',
      o.client ? 'Слова клиента: ' + o.client.slice(-1500) : '',
      o.level === 'sub' && o.applText ? 'Вид работ уже выбран: ' + o.applText : '',
      '',
      'Варианты (' + что + '):', варианты, '',
      'Выбери вариант, к которому регламент относит именно эту работу. Важно: навес кронштейна (в т.ч. для телевизора), гардин, полок, зеркал — «Мелкие работы»; '
        + 'ремонт и настройка телевизора — «Телевизоры» (или «ЖК ТВ…» в КП); подключение бытовой техники к воде — сантехника, к электричеству — электрика; '
        + '«Прочая» — только если ни один вариант не подходит.',
      'Ответ: {"id": "номер варианта", "why": "по какому пункту регламента, до 12 слов"}',
    ].filter((x) => x !== '').join('\n');
    return { sys, task };
  }

  function parse(raw, list) {
    const t = String(raw || '').replace(/```(?:json)?/gi, '');
    let id = '', why = '';
    const a = t.indexOf('{'), b = t.lastIndexOf('}');
    if (a >= 0 && b > a) { try { const d = JSON.parse(t.slice(a, b + 1)); id = String(d.id ?? '').trim(); why = String(d.why || '').trim(); } catch (_e) { /* ниже по цифрам */ } }
    if (!id) id = (t.match(/\b\d{2,6}\b/) || [''])[0];
    const ok = (list || []).find((x) => x.id === id);
    return ok ? { id, why: why.slice(0, 120) } : { id: '', why: '' };
  }
  return { prompt, parse };
})();
if (typeof module !== 'undefined' && module.exports) module.exports = LC_PICK;
