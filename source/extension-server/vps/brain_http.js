#!/usr/bin/env node
/* МОЗГ НА СВОЁМ СЕРВЕРЕ (Ubuntu, за Caddy с HTTPS) — когда облачные функции Yandex недоступны. Код мозга тот же
   (brain/dist/index.js, как в облачной функции), здесь — только перевод: HTTP-запрос → событие HTTP-триггера
   Yandex Cloud Functions → handler(event, context) → HTTP-ответ.
   Событие: httpMethod, path, headers (ключи строчными), multiValueHeaders, queryStringParameters (+ multiValue…),
   body — строкой (текстовые типы) или base64 с isBase64Encoded (двоичные), requestContext.identity: sourceIp —
   первый адрес X-Forwarded-For от Caddy (если запрос пришёл с этой же машины), иначе адрес соединения; userAgent.
   context: token.access_token = IAM_TOKEN (пусто — хранилище без заголовка), functionName 'brain-vps'.
   Запуск: node vps/brain_http.js — слушает 127.0.0.1:${PORT:-8081} (снаружи — только через Caddy).
   Окружение (systemd EnvironmentFile) — то же, что у функции (см. brain/index.js: GIGACHAT_KEY, BRAIN_TOKEN, TEAM_URL,
   BUCKET, ADMIN_PASSWORD_SHA256…), плюс S3_URL (хранилище, например http://127.0.0.1:9000), по желанию BRAIN_JS
   (по умолчанию brain/dist/index.js от корня проекта), IAM_TOKEN, PORT, TIMEOUT_SEC (150).
   Тело — до 12 МБ (больше — 413). Сбой мозга — 502 JSON {ok:false, error}, нет ответа за TIMEOUT_SEC — 504.
   В журнал — одна строка на запрос: метод, имя операции, код, мс (без значений параметров, тел и токенов). */
'use strict';
const http = require('http');
const net = require('net');
const path = require('path');
const crypto = require('crypto');
const {safeProviderError}=require('../brain/ai');

const КОРЕНЬ = path.join(__dirname, '..');
const МАКС_ТЕЛО = 12 * 1024 * 1024;
const СРОК = Math.max(1, Number(process.env.TIMEOUT_SEC) || 150) * 1000;
// текстовые типы — строкой, как у Yandex; остальное (и не UTF-8) — base64
const ТЕКСТ = /^(text\/|application\/(json|javascript|xml|x-www-form-urlencoded|graphql|x-ndjson|yaml)\b|[^;]*\+(json|xml)\b)/i;
// заголовки соединения — ставит сам сервер, из ответа функции не берём
const СЛУЖЕБНЫЕ = new Set(['content-length', 'transfer-encoding', 'connection', 'keep-alive', 'upgrade', 'proxy-connection', 'trailer', 'te']);
const безДанных = (s) => String(s || '').replace(/\d{5,}/g, '#').slice(0, 80);
const журнал = (x) => console.log(JSON.stringify(x));

function загрузитьМозг() {
  const файл = path.resolve(КОРЕНЬ, process.env.BRAIN_JS || path.join('brain', 'dist', 'index.js'));
  let m;
  try { m = require(файл); } catch (e) {
    throw new Error('мозг не загружен (' + файл + '): ' + String((e && e.message) || e).split('\n')[0] + ' — собрать: cd brain && node build.js ../ext');
  }
  const h = m && (m.handler || (m.default && m.default.handler));
  if (typeof h !== 'function') throw new Error('в ' + файл + ' нет handler(event, context)');
  return { handler: h, completeLegacy:m.completeLegacy, notifyNative:m.notifyNative, файл };
}

function внутреннийДоступ(req, token=process.env.LEADBOT_SERVICE_TOKEN) {
  const address=String(req.socket.remoteAddress||'').replace(/^::ffff:/,'');
  const got=String(req.headers['x-leadbot-token']||'');
  const gotBytes=Buffer.from(got),wantBytes=Buffer.from(token||'');
  return ['127.0.0.1','::1'].includes(address) && !req.headers['x-forwarded-for']
    && !req.headers.forwarded && !!token && gotBytes.length===wantBytes.length
    && crypto.timingSafeEqual(gotBytes,wantBytes);
}

/* адрес клиента: Caddy пишет его первым в X-Forwarded-For (чужой X-Forwarded-For от клиента он заменяет своим);
   верим заголовку, только если соединение — с этой же машины */
function адресКлиента(req) {
  const сокет = String(req.socket.remoteAddress || '').replace(/^::ffff:/, '');
  const первый = String(req.headers['x-forwarded-for'] || '').split(',')[0].trim().replace(/^::ffff:/, '');
  const местный = сокет === '127.0.0.1' || сокет === '::1';
  return местный && net.isIP(первый) ? первый : сокет;
}

function текстТела(буфер, тип) {
  if (тип && !ТЕКСТ.test(тип.trim())) return null;
  try { return new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(буфер); } catch (_e) { return null; }
}

/* HTTP-запрос → событие, как у HTTP-триггера Yandex Cloud Functions */
function событие(req, буфер, requestId, t0) {
  const u = new URL(req.url || '/', 'http://localhost');
  const headers = {}, multiValueHeaders = {};
  for (let i = 0; i + 1 < req.rawHeaders.length; i += 2) {
    const k = req.rawHeaders[i].toLowerCase();
    if (k === '__proto__') continue;
    if (!Object.hasOwn(multiValueHeaders, k)) multiValueHeaders[k] = [];
    multiValueHeaders[k].push(req.rawHeaders[i + 1]);
  }
  for (const [k, list] of Object.entries(multiValueHeaders)) headers[k] = list.join(', ');
  const queryStringParameters = {}, multiValueQueryStringParameters = {};
  for (const [k, v] of u.searchParams) {
    if (k === '__proto__') continue;
    queryStringParameters[k] = v;
    if (!Object.hasOwn(multiValueQueryStringParameters, k)) multiValueQueryStringParameters[k] = [];
    multiValueQueryStringParameters[k].push(v);
  }
  let body = '', isBase64Encoded = false;
  if (буфер.length) {
    const s = текстТела(буфер, String(req.headers['content-type'] || ''));
    if (s === null) { body = буфер.toString('base64'); isBase64Encoded = true; } else body = s;
  }
  return {
    httpMethod: String(req.method || 'GET').toUpperCase(), path: u.pathname, headers, multiValueHeaders,
    queryStringParameters, multiValueQueryStringParameters, params: {}, pathParams: {},
    requestContext: { identity: { sourceIp: адресКлиента(req), userAgent: String(req.headers['user-agent'] || '') },
      httpMethod: String(req.method || 'GET').toUpperCase(), requestId, requestTime: new Date(t0).toUTCString(), requestTimeEpoch: Math.floor(t0 / 1000) },
    body, isBase64Encoded,
  };
}

/* ответ функции {statusCode, headers, multiValueHeaders, body, isBase64Encoded} → что отдать по HTTP */
function разобратьОтвет(r) {
  const o = r && typeof r === 'object' && !Buffer.isBuffer(r) ? r : { statusCode: 200, body: r };
  let status = o.statusCode == null ? 200 : Number(o.statusCode);
  if (!Number.isInteger(status) || status < 200 || status > 599) throw new Error('неверный statusCode');
  const заголовки = new Map();                                     // строчное имя → [имя, значение | значения]
  for (const [k, v] of Object.entries(o.headers || {})) if (v != null && !СЛУЖЕБНЫЕ.has(k.toLowerCase())) заголовки.set(k.toLowerCase(), [k, String(v)]);
  for (const [k, v] of Object.entries(o.multiValueHeaders || {})) {
    const list = (Array.isArray(v) ? v : [v]).filter((x) => x != null).map(String);
    if (list.length && !СЛУЖЕБНЫЕ.has(k.toLowerCase())) заголовки.set(k.toLowerCase(), [k, list]);
  }
  let тело;
  if (Buffer.isBuffer(o.body)) тело = o.body;
  else if (typeof o.body === 'string') тело = o.isBase64Encoded ? Buffer.from(o.body, 'base64') : Buffer.from(o.body, 'utf8');
  else if (o.body == null) тело = Buffer.alloc(0);
  else {
    тело = Buffer.from(JSON.stringify(o.body), 'utf8');
    if (!заголовки.has('content-type')) заголовки.set('content-type', ['Content-Type', 'application/json; charset=utf-8']);
  }
  if (тело.length && !заголовки.has('content-type')) заголовки.set('content-type', ['Content-Type', 'text/plain; charset=utf-8']);
  for (const [, [k, v]] of заголовки) {                             // кириллица в заголовке — сбой до отправки, а не на середине
    http.validateHeaderName(k);
    for (const x of [].concat(v)) http.validateHeaderValue(k, x);
  }
  return { status, заголовки, тело };
}

function отдать(req, res, { status, заголовки, тело }, закрыть) {
  if (res.headersSent || res.destroyed) return;
  for (const [, [k, v]] of заголовки) res.setHeader(k, v);
  const безТела = status === 204 || status === 304;
  if (!безТела) res.setHeader('Content-Length', тело.length);
  if (закрыть) res.setHeader('Connection', 'close');
  res.writeHead(status);
  res.end(безТела || req.method === 'HEAD' ? undefined : тело);
}

function отдатьJSON(req, res, status, obj, закрыть) {
  отдать(req, res, { status, заголовки: new Map([['content-type', ['Content-Type', 'application/json; charset=utf-8']], ['cache-control', ['Cache-Control', 'no-store']]]),
    тело: Buffer.from(JSON.stringify(obj), 'utf8') }, закрыть);
}

// имя операции для журнала: из тела JSON (как берёт мозг), иначе ?op= — только буквы, цифры, «_»
function имяОперации(ev) {
  let op = '';
  if (ev && ev.body && !ev.isBase64Encoded && ev.body.length < 4e6) {
    try { const b = JSON.parse(ev.body); if (b && typeof b.op === 'string') op = b.op; } catch (_e) { /* не JSON */ }
  }
  if (!op && ev) op = String((ev.queryStringParameters || {}).op || '');
  return op.replace(/[^A-Za-z0-9_]/g, '').slice(0, 30) || '-';
}

function создатьСервер(мозг) {
  const сервер = http.createServer((req, res) => {
    const t0 = Date.now();
    const requestId = crypto.randomUUID();
    let ev = null, готово = false;
    const итог = (status, err) => {
      if (готово) return;
      готово = true;
      журнал({ http: String(req.method || '').slice(0, 10), op: имяОперации(ev), status, ms: Date.now() - t0, ...(err ? { err } : {}) });
    };
    const слишкомБольшой = () => {
      отдатьJSON(req, res, 413, { ok: false, error: 'слишком большой запрос (больше 12 МБ)', code: 'too_big' }, true);
      итог(413);
    };
    if (Number(req.headers['content-length'] || 0) > МАКС_ТЕЛО) return слишкомБольшой();
    const куски = [];
    let размер = 0, много = false;
    req.on('data', (c) => {
      if (много) return;
      размер += c.length;
      if (размер > МАКС_ТЕЛО) { много = true; куски.length = 0; слишкомБольшой(); return; }
      куски.push(c);
    });
    req.on('error', () => итог(499, 'обрыв запроса'));
    req.on('end', async () => {
      if (много) return;
      let r, status = 502, authenticatedCompletion = false;
      try {
        if(new URL(req.url||'/', 'http://localhost').pathname==='/internal/leadbot/notification'){
          if(req.method!=='POST'||!внутреннийДоступ(req)){
            отдатьJSON(req,res,403,{ok:false,code:'internal_only'});итог(403);return;
          }
          if(размер>16000||typeof мозг.notifyNative!=='function'){
            отдатьJSON(req,res,400,{ok:false,code:'internal_contract'});итог(400);return;
          }
          try{
            const args=require('../brain/native-notifications').strictJSON(Buffer.concat(куски).toString('utf8'));
            const result=await мозг.notifyNative(args);
            отдатьJSON(req,res,200,result);итог(200);
          }catch(_){отдатьJSON(req,res,502,{ok:false,code:'native_notification_unknown'});итог(502)}
          return;
        }
        if (new URL(req.url||'/', 'http://localhost').pathname==='/internal/leadbot/completion') {
          if (req.method!=='POST' || !внутреннийДоступ(req)) {
            отдатьJSON(req,res,403,{ok:false,code:'internal_only'});итог(403);return;
          }
          authenticatedCompletion = true;
          if (размер>300000 || typeof мозг.completeLegacy!=='function') {
            отдатьJSON(req,res,400,{ok:false,code:'internal_contract'});итог(400);return;
          }
          const result=await мозг.completeLegacy(JSON.parse(Buffer.concat(куски).toString('utf8')));
          отдатьJSON(req,res,200,result);итог(200);return;
        }
        ev = событие(req, Buffer.concat(куски), requestId, t0);
        const ctx = { token: { access_token: process.env.IAM_TOKEN || '', expires_in: 0, token_type: 'Bearer' }, functionName: 'brain-vps', requestId };
        let таймер = null;
        const срок = new Promise((_ok, нет) => { таймер = setTimeout(() => нет(Object.assign(new Error('мозг не ответил за ' + СРОК / 1000 + ' с'), { срок: true })), СРОК); });
        try { r = разобратьОтвет(await Promise.race([Promise.resolve().then(() => мозг.handler(ev, ctx)), срок])); } finally { clearTimeout(таймер); }
        status = r.status;
        отдать(req, res, r);
        итог(status);
      } catch (e) {
        status = e && e.срок ? 504 : 502;
        // клиенту — текст ошибки; в журнал — без данных (только вид ошибки и короткий текст без длинных чисел)
        const diagnostics = authenticatedCompletion && e && e.modelFormatDiagnostics;
        const safeError=safeProviderError(e && e.providerError);
        const providerError = authenticatedCompletion && safeError;
        const modelError=authenticatedCompletion || !!(e && e.providerError);
        const detail=modelError
          ? safeError ? 'GigaChat: '+safeError.stage+' / '+safeError.category : 'Не удалось завершить нейросетевую проверку'
          : String((e && e.message) || e).slice(0,200);
        try { отдатьJSON(req, res, status, { ok: false, error: 'мозг: ' + detail, code: 'upstream',
          ...(diagnostics ? {model_format_diagnostics:diagnostics} : {}),
          ...(providerError ? {provider_error:providerError} : {}) }); } catch (_e) { res.destroy(); }
        итог(status, (modelError ? 'ModelError' : (e && e.name) || 'Error') + ': ' + безДанных(detail));
      }
    });
  });
  // соединения с Caddy держим дольше, чем держит он сам (2 мин): иначе он может послать запрос в уже закрытое соединение
  сервер.keepAliveTimeout = 130e3;
  сервер.headersTimeout = 140e3;
  return сервер;
}

/* настройки мозга из хранилища (brain/config.json) — как загрузчик на Yandex (brain/loader.js): ключи ИИ, карт, пароль владельца.
   Переменные окружения сервера (файл настроек systemd) главнее: TEAM_URL, S3_URL, ADMIN_HOST здесь свои, не облачные */
async function настройкиИзХранилища() {
  const s3 = String(process.env.S3_URL || '').replace(/\/+$/, '');
  if (!s3) return 0;
  try {
    const r = await fetch(s3 + '/' + (process.env.BUCKET || 'lc-team-b1g1hrbbp0j5') + '/brain/config.json', { signal: AbortSignal.timeout(5000) });
    if (!r.ok) return 0;
    let n = 0;
    for (const [k, v] of Object.entries((await r.json()) || {})) if (typeof v === 'string' && !(k in process.env)) { process.env[k] = v; n++; }
    return n;
  } catch (_e) { return 0; }
}

async function запустить() {
  const изХранилища = await настройкиИзХранилища();
  if (изХранилища) журнал({ ev: 'config', keys: изХранилища });
  const мозг = загрузитьМозг();
  const порт = process.env.PORT == null || process.env.PORT === '' ? 8081 : Number(process.env.PORT);
  const сервер = создатьСервер(мозг);
  сервер.listen(порт, '127.0.0.1', () => {
    журнал({ ev: 'start', listen: '127.0.0.1:' + сервер.address().port, brain: path.relative(КОРЕНЬ, мозг.файл) || мозг.файл, s3: process.env.S3_URL || 'https://storage.yandexcloud.net' });
  });
  // остановка (systemctl stop/restart): новые не берём, идущие запросы доделываем (до 20 с)
  const стоп = () => { сервер.close(() => process.exit(0)); setTimeout(() => process.exit(0), 20e3).unref(); };
  process.on('SIGTERM', стоп);
  process.on('SIGINT', стоп);
}

if (require.main === module) {
  запустить().catch((e) => { console.error(String((e && e.message) || e)); process.exit(1); });
}

module.exports = { событие, разобратьОтвет, создатьСервер, загрузитьМозг, внутреннийДоступ, МАКС_ТЕЛО };
