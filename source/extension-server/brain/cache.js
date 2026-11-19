/* КЭШ ОТВЕТОВ ИИ: тот же вопрос — тот же ответ, 0 ₽. В памяти экземпляра — 500 последних, в хранилище —
   brain/cache/<sha>.json на 14 дней (старше — не берём; удаляет правило жизненного цикла бакета).
   Храним сырой ответ модели, а не итог операции: итог считается заново с текущим временем (разбор «сегодня/завтра»). */
'use strict';
const crypto = require('crypto');

const СРОК = 14 * 24 * 3600e3, В_ПАМЯТИ = 500;
const ключ = (...части) => crypto.createHash('sha256').update(части.map((x) => (typeof x === 'string' ? x : JSON.stringify(x))).join('\u0001')).digest('hex');

function создатьКэш({ store, now, log }) {
  const сейчас = now || (() => Date.now());
  const память = new Map();
  const запомнить = (k, v) => {
    память.delete(k); память.set(k, v);
    while (память.size > В_ПАМЯТИ) память.delete(память.keys().next().value);
  };
  async function взять(k) {
    const m = память.get(k);
    if (m && сейчас() - m.at < СРОК) { запомнить(k, m); return m; }
    if (!store) return null;
    try {
      const v = await store.get('brain/cache/' + k + '.json', null);
      if (v && v.at && сейчас() - v.at < СРОК) { запомнить(k, v); return v; }
    } catch (e) { if (log) log({ ev: 'кэш', ok: false, err: String(e.message || e).slice(0, 60) }); }
    return null;
  }
  async function положить(k, v) {
    const rec = { ...v, at: сейчас() };
    запомнить(k, rec);
    if (!store) return;
    try { await store.put('brain/cache/' + k + '.json', rec); }
    catch (e) { if (log) log({ ev: 'кэш', ok: false, err: String(e.message || e).slice(0, 60) }); }
  }
  return { взять, положить, размер: () => память.size };
}

module.exports = { создатьКэш, ключ, СРОК };
