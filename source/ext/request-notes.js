/* Уточнения владельца 23.10.2026. Только подготовка текста, без отправок и новых фактов о клиенте. */
const LC_REQUEST_NOTES = (() => {
  const PHONE = '(?:\\+?7|8)?[\\s(\\-]*\\d{3}[\\s)\\-]*\\d{3}[\\s\\-]*\\d{2}[\\s\\-]*\\d{2}';
  const ORDINAL = '(?:[1-3](?:[ -]?(?:й|ой|ый))?|первый|второй|третий|основной|дополнительный)\\s+номер';
  const DIRECTIVE = new RegExp('^((?:Звонить|Перезвонить)\\s+(?:на|по)\\s+(?:' + ORDINAL + '|номер\\s+' + PHONE + '|' + PHONE + '))(?![\\dа-яё])', 'i');
  function split(text) {
    const notes = [], calls = [];
    for (const raw of String(text || '').replace(/\r\n?/g, '\n').split('\n')) {
      const line = raw.trim(), m = line.match(DIRECTIVE);
      // Не меняем отрицание, вопрос или цитату в указание звонить.
      if (!m || /^[\s,.!;:—-]*(?:не\s+(?:надо|нужно|звонить)|нельзя|\?)/i.test(line.slice(m[0].length))) { if (line) notes.push(line); continue; }
      calls.push(m[1]);
      const rest = line.slice(m[0].length).replace(/^[\s,.!;:—-]+/, '').trim();
      if (rest) notes.push(rest);
    }
    return { calls: [...new Set(calls)], notes };
  }
  function service(text) {
    const { calls, notes } = split(text);
    if (!calls.length) return String(text || '');
    return [calls[0], ...calls.slice(1).map(x => 'Ранее: ' + x), ...notes].join('\n');
  }
  function mergeService(previous, addition) {
    if (!String(addition || '').trim()) return service(previous);
    const newText = String(addition).trim(), old = service(previous);
    if (old.includes(newText)) return old;
    const before = split(old), next = split(newText);
    const extra = next.notes.filter(line => !before.notes.includes(line));
    if (!extra.length && next.calls.every(line => before.calls.includes(line))) return old;
    // Явное новое указание оператора главнее прежнего; прежнее сохраняется ниже как история.
    return service(next.calls.length ? [...next.calls, ...before.calls, ...extra, ...before.notes].join('\n')
      : [old, ...extra].filter(Boolean).join('\n'));
  }
  function claimReply({ id, channel, hasClaim, incoming, messageId } = {}) {
    if (!/^[1-9]\d*$/.test(String(id || '')) || String(channel || '').toLowerCase() !== 'jivo'
        || hasClaim !== true || incoming !== true || !String(messageId || '').trim()) return null;
    return { kind: 'claims', text: id + ': Клиент ответил в диалоге на авито',
      event_key: 'jivo-claim-reply:' + id + ':' + messageId, on: true, requires_confirmation: true };
  }
  return { service, mergeService, claimReply };
})();
if (typeof module !== 'undefined' && module.exports) module.exports = LC_REQUEST_NOTES;
