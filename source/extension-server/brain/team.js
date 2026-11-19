/* СТАРЫЙ СЕРВЕР КОМАНДЫ (lead-centre-team-sync): Telegram-агент, общая память (названия, ссылки для отзыва).
   Мозг ходит туда ключом «сервер-сервер» BRAIN_TOKEN (заголовок X-Brain-Token); расширение больше не ходит само.
   Как team() в фоне расширения: GET с параметрами или POST с JSON; сроки — отправка в Telegram до 75 с, остальное 30 с;
   503 — Telegram на компьютере не на связи: текст сервера уже понятный, отдаём как есть. */
'use strict';

function создатьКоманду({ запрос, env, user }) {
  const E = env || {};
  return async function team(op, query, body, o) {
    const url = E.TEAM_URL, tok = E.BRAIN_TOKEN;
    if (!url || !tok) throw new Error('сервер команды не задан (TEAM_URL / BRAIN_TOKEN в настройках мозга)');
    const u = new URL(url); u.searchParams.set('op', op);
    for (const [k, v] of Object.entries(query || {})) u.searchParams.set(k, v);
    const ms = (o && o.timeout) || (op === 'tg_send' ? 55000 : op === 'tg_scan' || op === 'tg_search' ? 58000 : 30000);
    let r, t;
    try {
      r = await запрос(u.href, { method: body ? 'POST' : 'GET', body: body ? JSON.stringify(body) : undefined, timeout: ms,
        ...(o&&typeof o.observeRaw==='function'?{redirect:'error',maxResponseBytes:200000}:{}),
        headers: { 'X-Brain-Token': tok, 'X-Team-User': String((typeof user === 'function' ? user() : user) || 'brain').replace(/[^A-Za-z0-9_\-]/g, '_').slice(0, 40) || 'brain',
          'Content-Type': 'application/json' } });
      if(o&&typeof o.observeRaw==='function'){
        const raw=Buffer.isBuffer(r.bytes)?r.bytes:Buffer.from(await r.text());
        if(raw.length>200000||raw.includes(Buffer.from(tok)))throw Error('native receipt rejected');
        const contentType=String(r.headers?.get?.('content-type')||r.headers?.['content-type']||r.headers?.['Content-Type']||'').split(';')[0];
        await o.observeRaw({status:r.status,content_type:contentType},raw);
        if(contentType!=='application/json')throw Error('native receipt rejected');
        t=new TextDecoder('utf-8',{fatal:true}).decode(raw);
      }else t = await r.text();
    } catch (e) {
      if(o&&typeof o.observeRaw==='function')throw Object.assign(new Error('Исходный ответ сервера Telegram не подтверждён'),{неизвестно:true});
      // нет ответа вовремя — неизвестно, принял ли сервер (повтор мог бы отправить второй раз)
      if (e && e.name === 'AbortError') throw Object.assign(new Error('сервер команды не ответил вовремя — проверьте интернет и попробуйте ещё раз'), { неизвестно: true });
      throw new Error('нет связи с сервером команды: ' + String((e && e.message) || e).slice(0, 80));
    }
    if (!r.ok) throw Object.assign(new Error(o&&typeof o.observeRaw==='function'?'Сервер Telegram не подтвердил исходный запрос':r.status === 503 ? String(t).slice(0, 200) : 'сервер команды: ' + (t || 'HTTP ' + r.status).slice(0, 120)), { status: r.status });
    if(o&&typeof o.parse==='function')return o.parse(t);
    try { return JSON.parse(t); } catch (_e) { return t; }
  };
}

module.exports = { создатьКоманду };
