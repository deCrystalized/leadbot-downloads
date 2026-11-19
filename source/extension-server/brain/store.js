/* ХРАНИЛИЩЕ: Object Storage (S3) того же бакета, что у сервера команды, всё мозга — под brain/.
   Доступ — IAM-токеном функции (заголовок X-YaCloud-SubjectToken, как _s3 в server/index.py); токена нет (свой сервер,
   хранилище на нём же) — запрос без заголовка. Адрес хранилища — S3_URL в окружении (по умолчанию Object Storage Yandex;
   на своём сервере — например http://127.0.0.1:9000).
   Нет файла (404/403 — бакет отдаёт 403 на несуществующий ключ без права list) — значение по умолчанию. */
'use strict';
const S3 = 'https://storage.yandexcloud.net';

function создатьХранилище({ запрос, bucket, iam, s3 }) {
  const база = String(s3 || S3).trim().replace(/\/+$/, '') || S3;
  const url = (path, q) => база + '/' + bucket + '/' + String(path).replace(/^\/+/, '') + (q || '');
  const заголовки = () => {
    const t = typeof iam === 'function' ? iam() : iam;
    return t ? { 'X-YaCloud-SubjectToken': t } : {};
  };
  async function get(path, def) {
    const r = await запрос(url(path), { method: 'GET', headers: заголовки(), timeout: 10000 });
    if (r.status === 404 || r.status === 403) return def;
    if (!r.ok) throw new Error('хранилище: HTTP ' + r.status);
    const t = await r.text();
    if (!String(t).trim()) return def;
    // испорченный / оборванный ответ — ошибка, а не «файла нет»: иначе следующая запись затрёт настоящий файл
    try { return JSON.parse(t); } catch (_e) { throw new Error('хранилище: не JSON в ' + String(path).slice(0, 40)); }
  }
  async function put(path, obj) {
    const r = await запрос(url(path), { method: 'PUT', headers: { ...заголовки(), 'Content-Type': 'application/json; charset=utf-8' },
      body: JSON.stringify(obj), timeout: 10000 });
    if (!r.ok) throw new Error('хранилище: запись HTTP ' + r.status);
  }
  async function del(path) {
    const r = await запрос(url(path), { method: 'DELETE', headers: заголовки(), timeout: 10000 });
    if (!r.ok && r.status !== 404) throw new Error('хранилище: удаление HTTP ' + r.status);
  }
  return { get, put, del };
}

module.exports = { создатьХранилище, S3 };
