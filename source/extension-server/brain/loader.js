/* Загрузчик мозга (то, что лежит в самой облачной функции). Код мозга и его настройки — в закрытом хранилище
   (S3 brain/code.js, brain/config.json): так мозг обновляется без консоли. Записать их можно только ключом выкладки
   (x-deploy-key; в функции — только его sha256). Остальные запросы уходят в сам мозг. */
const crypto = require('crypto');
const DEPLOY_SHA = '4080ef4f291000a0c7bbb4dc582968dbd915c035d0e4f0f8f69613a7c06f038e';
const BUCKET = process.env.BUCKET || 'lc-team-b1g1hrbbp0j5';
const S3 = 'https://storage.yandexcloud.net/' + BUCKET;
let мозг = null, загружен = 0, етег = '', конфиг = null;
const sha = (s) => crypto.createHash('sha256').update(s).digest('hex');
const ответ = (code, body, origin) => ({ statusCode: code, headers: { 'Content-Type': 'application/json; charset=utf-8', ...(origin ? { 'Access-Control-Allow-Origin': origin, 'Vary': 'Origin' } : {}) }, body: JSON.stringify(body) });
async function s3(method, path, iam, body, extra) {
  return fetch(S3 + path, { method, headers: { 'X-YaCloud-SubjectToken': iam, ...(extra || {}) }, body });
}
function тело(event) { const b = event.body || ''; return event.isBase64Encoded ? Buffer.from(b, 'base64').toString('utf8') : b; }
async function загрузить(iam, сразу) {
  if (мозг && !сразу && Date.now() - загружен < 120000) return;
  const c = await s3('GET', '/brain/config.json', iam);
  if (c.ok) { конфиг = await c.json(); for (const [k, v] of Object.entries(конфиг || {})) if (typeof v === 'string') process.env[k] = v; }
  const r = await s3('GET', '/brain/code.js', iam, undefined, мозг && етег && !сразу ? { 'If-None-Match': етег } : {});
  загружен = Date.now();
  if (r.status === 304) return;
  if (!r.ok) throw new Error('код мозга не загружен в хранилище (' + r.status + ')');
  const код = await r.text();
  const m = { exports: {} };
  new Function('module', 'exports', 'require', '__filename', '__dirname', код)(m, m.exports, require, '/function/code/brain.js', '/function/code');
  мозг = m.exports; етег = r.headers.get('etag') || '';
}
exports.handler = async (event, context) => {
  const q = event.queryStringParameters || {}, h = {};
  for (const [k, v] of Object.entries(event.headers || {})) h[k.toLowerCase()] = v;
  const origin = /^http:\/\/127\.0\.0\.1:\d+$/.test(h.origin || '') ? h.origin : '';
  const iam = context && context.token && context.token.access_token;
  if (q.op === 'code_put' || q.op === 'setup') {
    if (event.httpMethod === 'OPTIONS') return { statusCode: 204, headers: { 'Access-Control-Allow-Origin': origin || 'null', 'Access-Control-Allow-Methods': 'POST, OPTIONS', 'Access-Control-Allow-Headers': 'content-type, x-deploy-key', 'Access-Control-Max-Age': '600' }, body: '' };
    const k = String(h['x-deploy-key'] || '');
    if (!k || sha(k) !== DEPLOY_SHA) { await new Promise((r) => setTimeout(r, 500)); return ответ(401, { ok: false, error: 'нужен ключ выкладки' }, origin); }
    const b = тело(event);
    if (q.op === 'code_put') {
      if (b.length < 1000) return ответ(400, { ok: false, error: 'пустой код' }, origin);
      const w = await s3('PUT', '/brain/code.js', iam, b, { 'Content-Type': 'application/javascript; charset=utf-8' });
      if (!w.ok) return ответ(502, { ok: false, error: 'хранилище: ' + w.status }, origin);
      мозг = null; await загрузить(iam, true);
      return ответ(200, { ok: true, sha256: sha(b), size: b.length, v: мозг && мозг.ВЕРСИЯ }, origin);
    }
    let нов; try { нов = JSON.parse(b); } catch (_e) { return ответ(400, { ok: false, error: 'нужен JSON' }, origin); }
    const старый = await s3('GET', '/brain/config.json', iam); const было = старый.ok ? await старый.json() : {};
    const итог = { ...было }; for (const [kk, v] of Object.entries(нов || {})) if (/^[A-Z][A-Z0-9_]{1,40}$/.test(kk) && typeof v === 'string' && v.trim()) итог[kk] = v.trim();
    const w = await s3('PUT', '/brain/config.json', iam, JSON.stringify(итог), { 'Content-Type': 'application/json' });
    if (!w.ok) return ответ(502, { ok: false, error: 'хранилище: ' + w.status }, origin);
    for (const [kk, v] of Object.entries(итог)) process.env[kk] = v;
    return ответ(200, { ok: true, keys: Object.keys(итог).sort() }, origin);
  }
  try { await загрузить(iam); } catch (e) { return ответ(503, { ok: false, error: String(e.message || e) }); }
  return мозг.handler(event, context);
};
