/* ЛИЧНЫЕ ТОКЕНЫ И ВХОД ВЛАДЕЛЬЦА.
   Токен — 32 случайных байта (base64url); в хранилище только sha256 + метка + дата + отозван (brain/tokens.json),
   сам токен показывается один раз при выпуске. Сравнение — по sha256 с постоянным временем; неверный — пауза 300 мс.
   Пароль администратора задаёт владелец: в окружении только его sha256 (ADMIN_PASSWORD_SHA256).
   Вход на страницу владельца — подписанный пропуск на 20 минут (без хранения: экземпляров функции несколько); страница
   держит его только в памяти — адрес функций общий для всех клиентов Yandex Cloud, короткий пропуск меньше стоит при утечке. */
'use strict';
const crypto = require('crypto');

const sha = (s) => crypto.createHash('sha256').update(String(s), 'utf8').digest('hex');
const b64url = (buf) => Buffer.from(buf).toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
function равныHex(a, b) {
  const x = Buffer.from(String(a || ''), 'hex'), y = Buffer.from(String(b || ''), 'hex');
  if (x.length !== 32 || y.length !== 32) { crypto.timingSafeEqual(Buffer.alloc(32), Buffer.alloc(32)); return false; }
  return crypto.timingSafeEqual(x, y);
}

const СВЕЖ = 30e3, ПРОПУСК = 20 * 60e3, ВХОДОВ = 100, ОТМЕТКА = 10 * 60e3;
const ПОПЫТОК = 5, ВСЕГО_ПОПЫТОК = 20, ОКНО = 10 * 60e3, СЛОТ_ПРОВЕРКА = 400;
// где видели каждый токен (адрес + устройство, первый и последний раз) — не больше 50 пар на токен;
// адреса удачных входов владельца — до 20, на 180 дней (им не мешает общий запрет входа после чужого перебора)
const ПАР_НА_ТОКЕН = 50, СВОИХ_АДРЕСОВ = 20, СВОЙ_АДРЕС_НА = 180 * 24 * 3600e3;

function создатьТокены({ store, env, now, sleep, rand }) {
  const E = env || {};
  const сейчас = now || (() => Date.now());
  const пауза = sleep || ((ms) => new Promise((r) => setTimeout(r, ms)));
  const случай = rand || ((n) => crypto.randomBytes(n));
  let файл = null, файлПри = 0;
  const последний = new Map();                    // id токена → {ip, dev, at} последней записи о входе
  const неудачи = new Map();                      // ip → [время неудачных входов владельца]

  async function загрузить(force) {
    if (!force && файл && сейчас() - файлПри < СВЕЖ) return файл;
    файл = await store.get('brain/tokens.json', { tokens: [] });
    файл.tokens = файл.tokens || [];
    файлПри = сейчас();
    return файл;
  }
  async function сохранить(f) { await store.put('brain/tokens.json', f); файл = f; файлПри = сейчас(); }

  /* Журналы раздельно: brain/logins.json — входы по токенам и удачные входы владельца (без токена или пароля туда
     не попасть); brain/admin_fail.json — неверные пароли (их может слать кто угодно — они не вытесняют следы токенов);
     brain/token_seen.json — для каждого токена все пары «адрес + устройство» (первый и последний раз): чужие записи
     их не вытесняют, владелец видит, где ещё работал токен */
  const журнал = async (путь) => (await store.get(путь, { list: [] })).list || [];
  async function дописать(путь, rec) {
    try {
      const f = await store.get(путь, { list: [] });
      f.list = [...(f.list || []), rec].slice(-ВХОДОВ);
      await store.put(путь, f);
    } catch (_e) { /* журнал входов — не повод отказать в работе */ }
  }
  const входы = () => журнал('brain/logins.json');
  const отметитьВход = (rec) => дописать('brain/logins.json', rec);
  const неверныеПароли = () => журнал('brain/admin_fail.json');
  async function отметитьТокен(id, ip, dev) {
    try {
      const f = (await store.get('brain/token_seen.json', {})) || {};
      const list = Array.isArray(f[id]) ? f[id] : [];
      const п = list.find((x) => x.ip === ip && x.dev === dev);
      if (п) п.last = сейчас(); else list.push({ ip, dev, first: сейчас(), last: сейчас() });
      f[id] = list.sort((a, b) => b.last - a.last).slice(0, ПАР_НА_ТОКЕН);
      await store.put('brain/token_seen.json', f);
    } catch (_e) { /* не повод отказать в работе */ }
  }
  async function гдеТокены() { try { return (await store.get('brain/token_seen.json', {})) || {}; } catch (_e) { return {}; } }
  const хешАдреса = (ip) => sha('lc-ip|' + String(ip || '')).slice(0, 32);
  async function свойАдрес(ip) {
    if (!ip) return false;
    try {
      const f = await store.get('brain/admin_known.json', { list: [] });
      return (f.list || []).some((x) => x.h === хешАдреса(ip) && сейчас() - x.at < СВОЙ_АДРЕС_НА);
    } catch (_e) { return false; }
  }
  async function запомнитьАдрес(ip) {
    if (!ip) return;
    try {
      const f = await store.get('brain/admin_known.json', { list: [] });
      const h = хешАдреса(ip);
      f.list = [...(f.list || []).filter((x) => x.h !== h && сейчас() - x.at < СВОЙ_АДРЕС_НА), { h, at: сейчас() }].slice(-СВОИХ_АДРЕСОВ);
      await store.put('brain/admin_known.json', f);
    } catch (_e) { /* не запомнили — в следующий раз */ }
  }

  /* проверка токена запроса: сравниваем со ВСЕМИ записями (время не зависит от того, какая совпала) */
  async function проверить(token, { ip, dev } = {}) {
    const t = String(token || '').trim();
    let f = null;
    // Свежий кэш уже обработан в загрузить. После его срока сбой обновления
    // не даёт бессрочно работать токену, который владелец мог отозвать.
    try { f = await загрузить(); } catch (_e) { throw new Error('хранилище токенов недоступно'); }
    if (!f) throw new Error('хранилище токенов недоступно');
    const h = sha(t);
    let found = null;
    for (const rec of f.tokens) { const да = равныHex(h, rec.sha); if (да && !found) found = rec; }
    if (!t || t.length < 20 || !found || found.revoked) { await пауза(300); return { ok: false }; }
    // вход: новое устройство / адрес или 10 минут с прошлой отметки — в журнал (без текстов, только кто и откуда)
    const п = последний.get(found.id);
    if (!п || п.ip !== ip || п.dev !== dev || сейчас() - п.at > ОТМЕТКА) {
      последний.set(found.id, { ip, dev, at: сейчас() });
      const ip1 = String(ip || '').slice(0, 45), dev1 = String(dev || '').slice(0, 40);
      await отметитьВход({ at: сейчас(), id: found.id, label: found.label, ip: ip1, dev: dev1 });
      await отметитьТокен(found.id, ip1, dev1);
    }
    return { ok: true, rec: found };
  }

  async function выпустить(label) {
    const f = await загрузить(true);
    const token = b64url(случай(32));
    const id = 't' + b64url(случай(4)).slice(0, 6);
    const rec = { id, sha: sha(token), label: String(label || 'устройство').trim().slice(0, 40) || 'устройство', created: сейчас(), revoked: 0 };
    f.tokens.push(rec);
    await сохранить(f);
    return { token, id, label: rec.label, created: rec.created };
  }
  async function изменить(id, fn) {
    const f = await загрузить(true);
    const rec = f.tokens.find((x) => x.id === id);
    if (!rec) return false;
    fn(rec);
    await сохранить(f);
    return true;
  }
  const отозвать = (id) => изменить(id, (r) => { r.revoked = сейчас(); });
  const метка = (id, label) => изменить(id, (r) => { r.label = String(label || '').trim().slice(0, 40) || r.label; });
  async function список() {
    const f = await загрузить(true);
    return f.tokens.map(({ id, label, created, revoked }) => ({ id, label, created, revoked }));
  }

  /* --- владелец --- */
  const ключПропуска = () => sha('lc-brain-admin|' + String(E.ADMIN_PASSWORD_SHA256 || '').trim().toLowerCase() + '|' + String(E.BRAIN_TOKEN || ''));
  const подпись = (p) => b64url(crypto.createHmac('sha256', ключПропуска()).update(p).digest());
  /* Попытка входа — занять место (слот) в хранилище ДО проверки пароля: brain/login/<окно 10 мин>/<адрес>-0..4 и all-0..19.
     Запись поверх чужой проверяется повторным чтением: из одновременных претендентов место получает один, остальные
     ищут следующее. Свободных нет — «подождите». Так параллельные экземпляры функции не дают больше 5 проверок пароля
     с адреса и 20 всего за окно (журнал входов read-modify-write параллельные неудачи терял). В ключе — не адрес, а его хеш */
  async function занятьМесто(префикс, n) {
    for (let круг = 0; круг < n + 3; круг++) {
      const места = await Promise.all(Array.from({ length: n }, (_, i) => store.get(префикс + i + '.json', null)));
      const i = места.findIndex((x) => !x);
      if (i < 0) return '';
      const путь = префикс + i + '.json', метка = b64url(случай(9));
      await store.put(путь, { m: метка, at: сейчас() });
      await пауза(СЛОТ_ПРОВЕРКА);
      const v = await store.get(путь, null);
      if (v && v.m === метка) return путь;
    }
    return '';
  }
  // свой адрес (владелец уже входил с него) — только место адреса: общий запрет не для него
  async function местоДляВхода(ip, свой) {
    const окно = 'brain/login/' + Math.floor(сейчас() / ОКНО) + '/';
    const адрес = await занятьМесто(окно + 'ip' + sha('lc-ip|' + String(ip || '')).slice(0, 16) + '-', ПОПЫТОК);
    if (!адрес) return null;
    if (свой) return [адрес];
    const всего = await занятьМесто(окно + 'all-', ВСЕГО_ПОПЫТОК);
    return всего ? [адрес, всего] : null;
  }
  function занятИП(ip) {
    const list = (неудачи.get(ip) || []).filter((t) => сейчас() - t < ОКНО);
    неудачи.set(ip, list);
    return list.length >= ПОПЫТОК;
  }
  async function войти(password, { ip, dev } = {}) {
    const нужно = String(E.ADMIN_PASSWORD_SHA256 || '').trim().toLowerCase();
    if (!/^[0-9a-f]{64}$/.test(нужно)) return { ok: false, code: 'no_admin', error: 'пароль администратора не задан (ADMIN_PASSWORD_SHA256 в настройках функции)' };
    // неудачи — и в памяти экземпляра, и в журнале неверных паролей (экземпляров несколько: перебор по разным не пройдёт);
    // 20 неудач с любых адресов за 10 минут — вход закрыт на 10 минут для всех, КРОМЕ адресов, с которых владелец уже
    // входил: чужой перебор с разных адресов не запирает владельца (иначе он не отзовёт украденный токен).
    // С каждого адреса (и своего) — не больше 5 попыток за 10 минут
    const недавно = (await неверныеПароли().catch(() => [])).filter((x) => сейчас() - x.at < ОКНО);
    const свой = await свойАдрес(ip);
    if (занятИП(ip) || недавно.filter((x) => x.ip === String(ip || '').slice(0, 45)).length >= ПОПЫТОК || (!свой && недавно.length >= ВСЕГО_ПОПЫТОК)) {
      await пауза(300); return { ok: false, code: 'busy', error: 'слишком много неверных попыток — подождите 10 минут' };
    }
    const места = await местоДляВхода(ip, свой);
    if (!места) { await пауза(300); return { ok: false, code: 'busy', error: 'слишком много попыток входа — подождите 10 минут' }; }
    if (!password || !равныHex(sha(password), нужно)) {
      неудачи.get(ip).push(сейчас());
      await дописать('brain/admin_fail.json', { at: сейчас(), id: 'admin', label: 'владелец: неверный пароль', ip: String(ip || '').slice(0, 45), dev: String(dev || '').slice(0, 40), bad: true });
      await пауза(300);
      return { ok: false, code: 'password', error: 'неверный пароль' };
    }
    // верный пароль — места освобождаем: входы владельца не закрывают ему же вход
    if (store.del) await Promise.all(места.map((m) => store.del(m).catch(() => {})));
    await отметитьВход({ at: сейчас(), id: 'admin', label: 'владелец', ip: String(ip || '').slice(0, 45), dev: String(dev || '').slice(0, 40) });
    await запомнитьАдрес(ip);
    const p = b64url(Buffer.from((сейчас() + ПРОПУСК) + '.' + b64url(случай(12))));
    return { ok: true, session: p + '.' + подпись(p), until: сейчас() + ПРОПУСК };
  }
  function пропуск(session) {
    const s = String(session || '');
    const [p, sig] = s.split('.');
    if (!p || !sig || !/^[0-9a-f]{64}$/.test(String(E.ADMIN_PASSWORD_SHA256 || '').trim().toLowerCase())) return false;
    const a = Buffer.from(sig), b = Buffer.from(подпись(p));
    if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return false;
    const exp = Number(Buffer.from(p.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString('utf8').split('.')[0]);
    return exp > сейчас();
  }

  return { проверить, выпустить, отозвать, метка, список, входы, неверныеПароли, гдеТокены, войти, пропуск, сброситьКэш: () => { файлПри = 0; } };
}

module.exports = { создатьТокены, sha, равныHex };
