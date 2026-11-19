/* СЕТЬ МОЗГА: один вызов на всё — запрос(url, {method, headers, body, timeout, ca}).
   Срок — на весь ответ вместе с телом (как в фоне расширения: заголовки пришли, а тело зависло — тоже срок).
   ca — свой корневой сертификат (GigaChat: «Минцифры», в облаке ему по умолчанию не доверяют) — тогда через https,
   иначе — обычный fetch Node 22. В тестах вместо этого — фейк с тем же видом ответа. */
'use strict';
const https = require('https');
const tls = require('tls');

class СрокИстёк extends Error {
  constructor(ms) { super('нет ответа за ' + Math.round(ms / 1000) + ' с'); this.name = 'AbortError'; }
}

function черезHttps(url, o) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const body = o.body == null ? null : Buffer.isBuffer(o.body) ? o.body : Buffer.from(String(o.body), 'utf8');
    const req = https.request({
      method: o.method || 'GET', hostname: u.hostname, port: u.port || 443, path: u.pathname + u.search,
      headers: { ...(o.headers || {}), ...(body ? { 'Content-Length': body.length } : {}) },
      // свой корень + обычные: у api.giga.chat может оказаться и общедоступный сертификат
      ca: [o.ca, ...tls.rootCertificates],
    }, (res) => {
      const parts = [];let size=0;
      res.on('data', (c) => {
        size+=c.length;
        if(o.maxResponseBytes!==undefined&&size>o.maxResponseBytes){
          res.destroy(new Error('bounded response exceeded'));return;
        }
        parts.push(c);
      });
      res.on('end', () => {
        const bytes=Buffer.concat(parts),text=bytes.toString('utf8');
        resolve({ status: res.statusCode, ok: res.statusCode >= 200 && res.statusCode < 300, headers: res.headers,
          ...(o.maxResponseBytes!==undefined?{bytes}:{}),text: async () => text, json: async () => JSON.parse(text) });
      });
      res.on('error', reject);
    });
    req.on('error', reject);
    if (o.signal) o.signal.addEventListener('abort', () => req.destroy(new СрокИстёк(o.timeout || 0)));
    if (body) req.write(body);
    req.end();
  });
}

async function черезFetch(url, o) {
  const r = await fetch(url, { method: o.method || 'GET', headers: o.headers || {}, body: o.body == null ? undefined : o.body, signal: o.signal, redirect: o.redirect || 'follow' });
  let bytes,text;
  if(o.maxResponseBytes!==undefined){
    const reader=r.body?.getReader(),parts=[];let size=0;
    if(reader){
      try{while(true){const chunk=await reader.read();if(chunk.done)break;
        size+=chunk.value.byteLength;if(size>o.maxResponseBytes){await reader.cancel();throw Error('bounded response exceeded')}
        parts.push(Buffer.from(chunk.value));}}
      finally{reader.releaseLock()}
    }
    bytes=Buffer.concat(parts);text=bytes.toString('utf8');
  }else text=await r.text();
  return { status: r.status, ok: r.ok, headers: Object.fromEntries(r.headers.entries()),
    ...(bytes?{bytes}:{}),text: async () => text, json: async () => JSON.parse(text) };
}

/* Настоящая сеть. Ответ уже прочитан целиком (text/json — без ожидания), поэтому срок покрывает и тело */
function создатьСеть() {
  return async function запрос(url, opt) {
    const o = { ...(opt || {}) };
    if(o.maxResponseBytes!==undefined&&(!Number.isSafeInteger(o.maxResponseBytes)||o.maxResponseBytes<1||o.maxResponseBytes>2000000))
      throw Error('finite response budget required');
    const ms = o.timeout || 20000;
    const ctl = new AbortController();
    o.signal = ctl.signal;
    let timer = null;
    const срок = new Promise((_res, rej) => { timer = setTimeout(() => { ctl.abort(); rej(new СрокИстёк(ms)); }, ms); });
    try {
      return await Promise.race([o.ca ? черезHttps(url, o) : черезFetch(url, o), срок]);
    } catch (e) {
      if (e && (e.name === 'AbortError' || e.name === 'TimeoutError')) throw new СрокИстёк(ms);
      throw e;
    } finally { clearTimeout(timer); }
  };
}

module.exports = { создатьСеть, СрокИстёк };
