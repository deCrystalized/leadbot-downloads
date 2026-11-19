'use strict';
const crypto = require('crypto');
const RULE = 'jivo-2026-10-15-v1';

// Сервер читает объявление, определяет подпись и собирает обязательную строку перед записью CRM.
function создатьПравило({ M, запрос, store, now }) {
  const X = M.LC_EXTRACT, A = M.LC_AVITO, clock = now || Date.now;
  const memory = new Map(), pending = new Map();
  function urlOf(value) {
    try {
      const u = new URL(String(value || ''));
      if (u.protocol !== 'https:' || !['avito.ru', 'www.avito.ru', 'm.avito.ru'].includes(u.hostname) || u.username || u.password || u.port || !A.объявление(u.href)) return '';
      u.hostname = 'www.avito.ru'; u.search = ''; u.hash = '';
      return u.href;
    } catch (_e) { return ''; }
  }
  async function read(url) {
    const key = 'brain/advertisers/' + crypto.createHash('sha256').update(url).digest('hex') + '.json';
    let rec = memory.get(url);
    if (!rec) try { rec = await store.get(key, null); } catch (_e) { /* публичные данные можно прочитать без кэша */ }
    if (rec && clock() - rec.at < (rec.ok ? 864e5 : 120e3)) { memory.set(url, rec); return rec; }
    if (pending.has(url)) return pending.get(url);
    const p = (async () => {
      let result = { ok: false, at: clock() };
      try {
        // redirect:manual не позволяет объявлению перенаправить сервер на посторонний адрес.
        const r = await запрос(url, { method: 'GET', timeout: 4000, redirect: 'manual' });
        const html = await r.text();
        if (r.ok && !A.заблокировано(html, r.status)) {
          const data = A.advertiserFromHtml(html);
          if (data.sellerName || data.description) result = { ok: true, ...data, at: clock() };
        }
      } catch (_e) { /* защита сайта / срок: оператор видит подставленное название канала */ }
      memory.set(url, result);
      if (memory.size > 200) memory.delete(memory.keys().next().value);
      try { await store.put(key, result); } catch (_e) { /* ошибка кэша не запрещает ручное уточнение */ }
      return result;
    })();
    pending.set(url, p);
    try { return await p; } finally { pending.delete(url); }
  }
  async function prepare(ctx, fetchAd = true) {
    const next = { ...(ctx || {}) };
    const url = urlOf(next.itemUrl);
    if (url && fetchAd) {
      const rec = await read(url);
      if (rec.ok) { next.sellerName = rec.sellerName || ''; next.adDescription = rec.description || ''; }
    }
    return next;
  }
  function decorate(lead, ctx) {
    const required = !/^max_(bot|user)$/.test(String(ctx && ctx.channel || '')) || !!(ctx && ctx.sourceAvailable);
    return { ...X.withAdvertiser(lead || {}, ctx || {}), ad_identity_required: required, advertiser_rule: RULE };
  }
  async function apply(args) {
    const a = args || {}, ctx = await prepare(a.ctx, !(a.lead && a.lead.ad_identity_set));
    const lead = decorate(a.lead, ctx);
    if (a.final && lead.ad_identity_required && !lead.ad_identity)
      return { ok: false, code: 'advertiser_missing', rule: RULE, error: 'Укажите имя мастера из объявления или название аккаунта.' };
    return { ok: true, rule: RULE, lead, sellerName: ctx.sellerName || '', description: ctx.adDescription || '' };
  }
  return { prepare, decorate, apply };
}
module.exports = { создатьПравило, RULE };
