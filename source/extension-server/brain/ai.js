/* ИИ МОЗГА: GigaChat (личный бесплатный пакет — основной) и YandexGPT Lite (запасной), по цепочкам на задачу.
   Каждый вызов учитывается в бюджете по usage из ответа API; одинаковый вопрос берётся из кэша (0 ₽).
   Цепочки — окончательно по замерам качества (MODELS.md, пакет B4); можно поменять без кода: CHAIN_<ОПЕРАЦИЯ>
   в окружении («GigaChat-2,yandexgpt-lite»). YandexGPT Pro — нигде по умолчанию (в 6 раз дороже Lite). */
'use strict';
const crypto = require('crypto');
const { ключ } = require('./cache');

const ЦЕПОЧКИ = {
  assistant: ['GigaChat-2-Pro', 'yandexgpt-lite'],
  extract: ['GigaChat-2-Pro', 'yandexgpt-lite'],
  address: ['GigaChat-2', 'yandexgpt-lite'],          // голос ИИ; второй голос — правила, третий — карта
  checklist: ['GigaChat-2', 'yandexgpt-lite'],
  addition: ['GigaChat-2', 'yandexgpt-lite'],
  pick: ['GigaChat-2', 'yandexgpt-lite'],
  ahk_chat: ['GigaChat-2-Max', 'GigaChat-2-Pro', 'yandexgpt-lite'],
};
// ответ не длиннее нужного: за выход платим так же, как за вход
const МАКС_ТОКЕНОВ = { extract: 600, checklist: 400, pick: 50, addition: 200, address: 300, ahk_chat: 800 };
// на всю цепочку (панель ждёт: разбор 50 с, адрес 45 с — после ИИ ещё карты, регламент 45 с, вид работ 25 с)
const СРОК_ЦЕПОЧКИ = { extract: 44000, address: 24000, checklist: 40000, addition: 40000, pick: 21000, ahk_chat: 50000 };
const СРОК_МОДЕЛИ = 20000;
// One structured assistant attempt, including cache/budget, queue and OAuth.
// Other operations retain their existing per-model limit.
const ASSISTANT_MODEL_BUDGET_MS = 30000;
const ПАУЗЫ_429 = [1000, 2000, 3000, 4000, 4000];      // GigaChat «занято» (429): паузы перед повторами, всего до 14 с
// ответ не по форме у всех моделей — то же состояние переписки 30 мин к ИИ не отправляем (расширение повторяет раз в минуту:
// иначе каждый повтор оплачивается заново); обрезанный по длине ответ — один повтор той же моделью с бо́льшим max_tokens
const НЕ_ПО_ФОРМЕ_НА = 30 * 60e3, МАКС_ПОВТОР = 1200;
// запас времени каждой следующей модели цепочки: зависший GigaChat не должен съесть весь срок — иначе до запасного
// YandexGPT Lite (отвечает за 2–8 с) дело не дойдёт и разбор упадёт, хотя запасной ответил бы
const ЗАПАС = { доля: 0.3, макс: 12000 };
const YANDEX_URI = { 'yandexgpt-lite': 'yandexgpt-lite/latest', 'yandexgpt': 'yandexgpt/latest' };
const GIGA_OAUTH = 'https://ngw.devices.sberbank.ru:9443/api/v2/oauth';
const GIGA_BASES = ['https://api.giga.chat/v1', 'https://gigachat.devices.sberbank.ru/api/v1'];

// корневой сертификат «Минцифры» (как GIGA_CA в server/index.py): у Сбера он, а в облаке ему по умолчанию не доверяют
const GIGA_CA = `-----BEGIN CERTIFICATE-----
MIIFwjCCA6qgAwIBAgICEAAwDQYJKoZIhvcNAQELBQAwcDELMAkGA1UEBhMCUlUx
PzA9BgNVBAoMNlRoZSBNaW5pc3RyeSBvZiBEaWdpdGFsIERldmVsb3BtZW50IGFu
ZCBDb21tdW5pY2F0aW9uczEgMB4GA1UEAwwXUnVzc2lhbiBUcnVzdGVkIFJvb3Qg
Q0EwHhcNMjIwMzAxMjEwNDE1WhcNMzIwMjI3MjEwNDE1WjBwMQswCQYDVQQGEwJS
VTE/MD0GA1UECgw2VGhlIE1pbmlzdHJ5IG9mIERpZ2l0YWwgRGV2ZWxvcG1lbnQg
YW5kIENvbW11bmljYXRpb25zMSAwHgYDVQQDDBdSdXNzaWFuIFRydXN0ZWQgUm9v
dCBDQTCCAiIwDQYJKoZIhvcNAQEBBQADggIPADCCAgoCggIBAMfFOZ8pUAL3+r2n
qqE0Zp52selXsKGFYoG0GM5bwz1bSFtCt+AZQMhkWQheI3poZAToYJu69pHLKS6Q
XBiwBC1cvzYmUYKMYZC7jE5YhEU2bSL0mX7NaMxMDmH2/NwuOVRj8OImVa5s1F4U
zn4Kv3PFlDBjjSjXKVY9kmjUBsXQrIHeaqmUIsPIlNWUnimXS0I0abExqkbdrXbX
YwCOXhOO2pDUx3ckmJlCMUGacUTnylyQW2VsJIyIGA8V0xzdaeUXg0VZ6ZmNUr5Y
Ber/EAOLPb8NYpsAhJe2mXjMB/J9HNsoFMBFJ0lLOT/+dQvjbdRZoOT8eqJpWnVD
U+QL/qEZnz57N88OWM3rabJkRNdU/Z7x5SFIM9FrqtN8xewsiBWBI0K6XFuOBOTD
4V08o4TzJ8+Ccq5XlCUW2L48pZNCYuBDfBh7FxkB7qDgGDiaftEkZZfApRg2E+M9
G8wkNKTPLDc4wH0FDTijhgxR3Y4PiS1HL2Zhw7bD3CbslmEGgfnnZojNkJtcLeBH
BLa52/dSwNU4WWLubaYSiAmA9IUMX1/RpfpxOxd4Ykmhz97oFbUaDJFipIggx5sX
ePAlkTdWnv+RWBxlJwMQ25oEHmRguNYf4Zr/Rxr9cS93Y+mdXIZaBEE0KS2iLRqa
OiWBki9IMQU4phqPOBAaG7A+eP8PAgMBAAGjZjBkMB0GA1UdDgQWBBTh0YHlzlpf
BKrS6badZrHF+qwshzAfBgNVHSMEGDAWgBTh0YHlzlpfBKrS6badZrHF+qwshzAS
BgNVHRMBAf8ECDAGAQH/AgEEMA4GA1UdDwEB/wQEAwIBhjANBgkqhkiG9w0BAQsF
AAOCAgEAALIY1wkilt/urfEVM5vKzr6utOeDWCUczmWX/RX4ljpRdgF+5fAIS4vH
tmXkqpSCOVeWUrJV9QvZn6L227ZwuE15cWi8DCDal3Ue90WgAJJZMfTshN4OI8cq
W9E4EG9wglbEtMnObHlms8F3CHmrw3k6KmUkWGoa+/ENmcVl68u/cMRl1JbW2bM+
/3A+SAg2c6iPDlehczKx2oa95QW0SkPPWGuNA/CE8CpyANIhu9XFrj3RQ3EqeRcS
AQQod1RNuHpfETLU/A2gMmvn/w/sx7TB3W5BPs6rprOA37tutPq9u6FTZOcG1Oqj
C/B7yTqgI7rbyvox7DEXoX7rIiEqyNNUguTk/u3SZ4VXE2kmxdmSh3TQvybfbnXV
4JbCZVaqiZraqc7oZMnRoWrXRG3ztbnbes/9qhRGI7PqXqeKJBztxRTEVj8ONs1d
WN5szTwaPIvhkhO3CO5ErU2rVdUr89wKpNXbBODFKRtgxUT70YpmJ46VVaqdAhOZ
D9EUUn4YaeLaS8AjSF/h7UkjOibNc4qVDiPP+rkehFWM66PVnP1Msh93tc+taIfC
EYVMxjh8zNbFuoc7fzvvrFILLe7ifvEIUqSVIC/AzplM/Jxw7buXFeGP1qVCBEHq
391d/9RAfaZ12zkwFsl+IKwE/OZxW8AHa9i1p4GO0YSNuczzEm4=
-----END CERTIFICATE-----`;

class ОшибкаМодели extends Error {
  constructor(msg, extra) { super(msg); Object.assign(this, extra || {}); }
}

const PROVIDER_STAGES=new Set(['oauth','upload','completion','completion_body','queue','cache','budget','unknown']);
const PROVIDER_CATEGORIES=new Set(['network_timeout','network_error','invalid_response','rate_limited','upstream','queue_timeout','deadline_exceeded']);
function safeProviderError(value) {
  if (!value || typeof value!=='object' || Array.isArray(value)) return null;
  try {
    const {provider,status,stage,category,retry_after_seconds:retry}=value;
    if (provider!=='gigachat' || !PROVIDER_STAGES.has(stage) || !PROVIDER_CATEGORIES.has(category)
        || !(status===null || Number.isInteger(status)&&status>=100&&status<=599)
        || !(retry===null || Number.isInteger(retry)&&retry>=0&&retry<=86400)) return null;
    return {provider,status,stage,category,retry_after_seconds:retry};
  } catch (_) { return null; }
}
function ошибкаТранспорта(stage,error) {
  const category=error && (error.name==='AbortError'||error.name==='TimeoutError'||error.code==='ETIMEDOUT')
    ? 'network_timeout' : error && error.name==='SyntaxError' ? 'invalid_response' : 'network_error';
  // Never carry the underlying message, URL, headers or request body into logs.
  return new ОшибкаМодели('GigaChat: '+stage+' / '+category,
    {providerError:{provider:'gigachat',status:null,stage,category,retry_after_seconds:null}});
}

function создатьИИ({ запрос, env, budget, cache, iam, log, now, sleep }) {
  const E = env || {};
  const сейчас = now || (() => Date.now());
  const пауза = sleep || ((ms) => new Promise((r) => setTimeout(r, ms)));
  const журнал = log || (() => {});
  const giga = { token: '', exp: 0, base: '' };
  let tokenFlight = null;
  let gigaTail = Promise.resolve(); // all ops share the personal API's one generation stream
  const идут = new Map();                                   // один и тот же вопрос одновременно — один вызов

  const цепочка = (op) => {
    const env1 = String(E['CHAIN_' + op.toUpperCase()] || '').split(',').map((s) => s.trim()).filter(Boolean);
    return env1.length ? env1 : (ЦЕПОЧКИ[op] || ЦЕПОЧКИ.checklist);
  };
  const этоГига = (m) => /^GigaChat/i.test(m);

  async function доСрока(promise, deadline, stage) {
    let timer;
    try {
      const value = await Promise.race([promise, new Promise((_, reject) => {
        timer = setTimeout(() => reject(ошибкаСрока(stage)), Math.max(0, deadline - сейчас()));
      })]);
      if (deadline <= сейчас()) throw ошибкаСрока(stage);
      return value;
    } finally { clearTimeout(timer); }
  }

  function ошибкаГиги(status, headers, stage) {
    const raw = headers && (typeof headers.get === 'function' ? headers.get('retry-after')
      : Object.entries(headers).find(([key]) => key.toLowerCase() === 'retry-after')?.[1]);
    let seconds = null;
    if (typeof raw === 'string' || typeof raw === 'number') {
      const text = String(raw).trim();
      const value = /^\d+(?:\.\d+)?$/.test(text) ? Number(text) : (Date.parse(text) - сейчас()) / 1000;
      if (Number.isFinite(value) && value >= 0 && value <= 86400) seconds = Math.ceil(value);
    }
    return new ОшибкаМодели('GigaChat ' + (stage === 'oauth' ? 'получение токена: ' : '') + 'HTTP ' + status,
      {providerError:{provider:'gigachat',status,stage,
        category:status === 429 ? 'rate_limited' : 'upstream',retry_after_seconds:seconds}});
  }

  async function слотГиги(run, deadline) {
    const before = gigaTail;
    let release;
    const slot = new Promise(resolve => { release = resolve; });
    gigaTail = before.then(() => slot);
    const expired = () => new ОшибкаМодели('GigaChat: истёк срок ожидания очереди',
      {providerError:{provider:'gigachat',status:null,stage:'queue',category:'queue_timeout',retry_after_seconds:null}});
    let timer;
    try {
      await Promise.race([before, new Promise((_, reject) => {
        timer = setTimeout(() => reject(expired()), Math.max(0, deadline - сейчас() - 1000));
      })]);
    } catch (error) {
      // An expired waiter must not release a later request ahead of the active one.
      before.then(release);
      throw error;
    } finally { clearTimeout(timer); }
    try {
      const left = deadline - сейчас();
      if (left < 1000) throw expired();
      return await run(left);
    } finally { release(); }
  }

  async function гигаТокен(срок) {
    if (giga.token && giga.exp - 60e3 > сейчас()) return giga.token;
    if (tokenFlight) return tokenFlight;
    if (!E.GIGACHAT_KEY) throw new ОшибкаМодели('не задан ключ GigaChat (GIGACHAT_KEY)', { skip: true });
    tokenFlight = (async()=>{
    const r = await запрос(GIGA_OAUTH, { method: 'POST', ca: GIGA_CA, timeout: Math.min(15000, срок),
      headers: { Authorization: 'Basic ' + E.GIGACHAT_KEY, RqUID: crypto.randomUUID(), 'Content-Type': 'application/x-www-form-urlencoded', Accept: 'application/json' },
      body: 'scope=' + encodeURIComponent(E.GIGACHAT_SCOPE || 'GIGACHAT_API_PERS') });
    if (!r.ok) throw ошибкаГиги(r.status, r.headers, 'oauth');
    const d = await r.json();
    giga.token = d.access_token || '';
    const expires = Number(d.expires_at);
    giga.exp = expires ? (expires < 1e12 ? expires * 1000 : expires) : сейчас() + 25 * 60e3;
    if (!giga.token) throw new ОшибкаМодели('GigaChat не выдал токен',
      {providerError:{provider:'gigachat',status:r.status,stage:'oauth',category:'invalid_response',retry_after_seconds:null}});
    return giga.token;
    })();
    try { return await tokenFlight; } finally { tokenFlight = null; }
  }

  /* снимок окна помощника AHK — файлом в хранилище GigaChat (картинки понимают Pro и Max); после ответа удаляем */
  async function гигаФайл(base, image, срок) {
    const граница = '----LeadCentreBrain' + crypto.randomBytes(6).toString('hex');
    const тип = /png/i.test(image.type || '') ? 'image/png' : 'image/jpeg';
    const тело = Buffer.concat([
      Buffer.from('--' + граница + '\r\nContent-Disposition: form-data; name="purpose"\r\n\r\ngeneral\r\n--' + граница
        + '\r\nContent-Disposition: form-data; name="file"; filename="screen.' + (тип === 'image/png' ? 'png' : 'jpg') + '"\r\nContent-Type: ' + тип + '\r\n\r\n', 'utf8'),
      Buffer.from(image.b64, 'base64'), Buffer.from('\r\n--' + граница + '--\r\n', 'utf8')]);
    const r = await запрос(base + '/files', { method: 'POST', ca: GIGA_CA, timeout: Math.min(15000, срок), body: тело,
      headers: { Authorization: 'Bearer ' + giga.token, 'Content-Type': 'multipart/form-data; boundary=' + граница, Accept: 'application/json' } });
    if (!r.ok) throw ошибкаГиги(r.status,r.headers,'upload');
    const fileId=(await r.json()).id;
    if (typeof fileId!=='string' || !fileId) throw new ОшибкаМодели('GigaChat: не получен идентификатор снимка',
      {providerError:{provider:'gigachat',status:r.status,stage:'upload',category:'invalid_response',retry_after_seconds:null}});
    return fileId;
  }
  const картинкиПонимает = (m) => /^GigaChat-2-(Pro|Max)$/i.test(m);

  async function гига(model, sys, task, max, срок, доп) {
    return слотГиги(left => гигаВПотоке(model, sys, task, max, left, доп), сейчас() + срок);
  }

  async function гигаВПотоке(model, sys, task, max, срок, доп) {
    const d0 = доп || {};
    const конец = сейчас() + срок;
    let файл = '';
    const тело = () => JSON.stringify({ model, temperature: d0.temperature == null ? 0.01 : d0.temperature, max_tokens: max,
      ...(d0.responseFormat ? {response_format:d0.responseFormat} : {}),
      messages: [{ role: 'system', content: sys }, { role: 'user', content: task, ...(файл ? { attachments: [файл] } : {}) }] });
    let последняя = null, повторТокен = false, занято = 0, гдеФайл = '';
    // снимок клиента в хранилище Сбера не оставляем — ни после ответа, ни после ошибки
    const удалитьФайл = () => (файл ? запрос(гдеФайл + '/files/' + encodeURIComponent(файл) + '/delete', { method: 'POST', ca: GIGA_CA, timeout: 3000,
      headers: { Authorization: 'Bearer ' + giga.token, Accept: 'application/json' } }).catch(() => {}) : null);
    try {
      // рабочий адрес — первым; второй — запасной (api.giga.chat бывает недоступен)
      for (let i = 0; i < (d0.singleAttempt ? 1 : 4); i++) {
        const base = [...GIGA_BASES].sort((a, b) => (a === giga.base ? -1 : b === giga.base ? 1 : 0))[i % 2];
        const осталось = конец - сейчас();
        if (осталось < 1000) break;
        let r, stage='oauth';
        try {
          const t = await гигаТокен(осталось);
          if (конец - сейчас() < 1000) throw ошибкаСрока('oauth');
          if (d0.image && !файл) { stage='upload'; файл = await гигаФайл(base, d0.image, конец - сейчас()); гдеФайл = base; }
          if (конец - сейчас() < 1000) throw ошибкаСрока('upload');
          stage='completion';
          r = await запрос(base + '/chat/completions', { method: 'POST', ca: GIGA_CA, timeout: Math.min(конец - сейчас(), d0.modelTimeoutMs || СРОК_МОДЕЛИ),
            headers: { Authorization: 'Bearer ' + t, 'Content-Type': 'application/json', Accept: 'application/json' }, body: тело() });
        } catch (e) {
          if (e instanceof ОшибкаМодели) throw e;
          if (d0.singleAttempt) {
            if (конец <= сейчас() && !['AbortError','TimeoutError'].includes(e && e.name)) throw ошибкаСрока(stage);
            throw ошибкаТранспорта(stage,e);
          }
          последняя = new ОшибкаМодели(base.split('/')[2] + ': ' + String(e.message || e).slice(0, 60));
          continue;                                            // сеть / срок — другой адрес
        }
        if (конец <= сейчас()) throw ошибкаСрока('completion');
        if (r.status === 401) {
          giga.token = '';
          if (!d0.singleAttempt && !повторТокен) { повторТокен = true; i--; continue; }
        }
        if (r.status === 402) throw new ОшибкаМодели('GigaChat: пакет ' + model + ' исчерпан (402)', { исчерпан: true });
        // личный пакет — запросы по одному: занято (параллельный вопрос: «Готовые» по два диалога, помощник AHK) — ждём
        // с нарастающей паузой, пока хватает срока этой модели (запас следующих моделей уже вычтен): бесплатный ответ
        // через несколько секунд лучше платного YandexGPT Lite сразу. Срок вышел — следующая модель
        if (!d0.singleAttempt && r.status === 429 && занято < ПАУЗЫ_429.length && конец - сейчас() - ПАУЗЫ_429[занято] >= 3000) {
          await пауза(ПАУЗЫ_429[занято++]); i--; continue;
        }
        if (!r.ok) throw ошибкаГиги(r.status, r.headers, 'completion');
        giga.base = base;
        let d;
        try { d = await r.json(); }
        catch (error) { if(d0.singleAttempt)throw ошибкаТранспорта('completion_body',error);throw error; }
        if (конец <= сейчас()) throw ошибкаСрока('completion');
        const u = d.usage || {};
        return { text: ((((d.choices || [])[0] || {}).message) || {}).content || '', inTok: Number(u.prompt_tokens) || 0, outTok: Number(u.completion_tokens) || 0,
          finish: ((d.choices || [])[0] || {}).finish_reason || '',
          observedUsage: {prompt_tokens: Number.isInteger(u.prompt_tokens) && u.prompt_tokens >= 0 ? u.prompt_tokens : null,
            completion_tokens: Number.isInteger(u.completion_tokens) && u.completion_tokens >= 0 ? u.completion_tokens : null} };
      }
      throw последняя || new ОшибкаМодели('GigaChat не ответил');
    } finally { await удалитьФайл(); }
  }

  const доступЯндекса = () => {
    const folder = E.YANDEX_FOLDER || E.FOLDER_ID || '';
    const ключAPI = E.YANDEX_API_KEY || '';
    const токен = ключAPI ? '' : (typeof iam === 'function' ? iam() : iam);
    return { folder, ok: !!(folder && (ключAPI || токен)), headers: { Authorization: ключAPI ? 'Api-Key ' + ключAPI : 'Bearer ' + токен, 'x-folder-id': folder } };
  };
  /* текст со снимка окна (Yandex Vision OCR) — для моделей, которые картинок не понимают */
  async function распознать(op, image, срок) {
    const y = доступЯндекса();
    if (!y.ok) throw new ОшибкаМодели('распознавание снимка: не задан каталог (YANDEX_FOLDER) или доступ', { skip: true });
    const t1 = сейчас();
    const r = await запрос('https://ocr.api.cloud.yandex.net/ocr/v1/recognizeText', { method: 'POST', timeout: Math.min(15000, срок),
      headers: { ...y.headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({ mimeType: /png/i.test(image.type || '') ? 'PNG' : 'JPEG', languageCodes: ['ru', 'en'], model: 'page', content: image.b64 }) });
    if (!r.ok) throw new ОшибкаМодели('распознавание снимка: HTTP ' + r.status);
    const d = await r.json();
    const rub = budget.записать({ op, model: 'vision-ocr', inTok: 0, outTok: 0 });
    журнал({ op, model: 'vision-ocr', rub, ms: сейчас() - t1, ok: true });
    return String((((d.result || {}).textAnnotation) || {}).fullText || '');
  }

  async function яндекс(model, sys, task, max, срок, доп) {
    const d0 = доп || {};
    const y = доступЯндекса();
    if (!y.ok) throw new ОшибкаМодели('YandexGPT: не задан каталог (YANDEX_FOLDER) или доступ', { skip: true });
    const тело = JSON.stringify({ modelUri: 'gpt://' + y.folder + '/' + (YANDEX_URI[model] || model), completionOptions: { stream: false, temperature: d0.temperature == null ? 0 : d0.temperature, maxTokens: String(max) },
      messages: [{ role: 'system', text: sys }, { role: 'user', text: task }] });
    const конец = сейчас() + срок;
    let последняя = '';
    for (let i = 0; i < 2; i++) {
      if (i) await пауза(1500);
      const осталось = конец - сейчас();
      if (осталось < 1000) break;
      let r;
      try {
        r = await запрос('https://llm.api.cloud.yandex.net/foundationModels/v1/completion', { method: 'POST', timeout: Math.min(осталось, СРОК_МОДЕЛИ),
          headers: { ...y.headers, 'Content-Type': 'application/json' }, body: тело });
      } catch (e) { последняя = String(e.message || e).slice(0, 60); continue; }
      if (r.status === 401 || r.status === 403) throw new ОшибкаМодели('YandexGPT не принял доступ (HTTP ' + r.status + ')');
      if (r.ok) {
        const d = await r.json();
        const res = d.result || {}, u = res.usage || {};
        return { text: ((((res.alternatives || [])[0] || {}).message) || {}).text || '', inTok: Number(u.inputTextTokens) || 0, outTok: Number(u.completionTokens) || 0,
          finish: (((res.alternatives || [])[0] || {}).status) || '' };
      }
      последняя = 'HTTP ' + r.status;
    }
    throw new ОшибкаМодели('YandexGPT не ответил (' + последняя + ')');
  }

  /* Вопрос по цепочке op. режим: normal | economy (только пакет GigaChat и YandexGPT Lite) | rules (ИИ нельзя).
     годен(text) — ответ по форме; нет — следующая модель (обрезанный JSON, чужой формат). */
  async function спросить(op, sys, task, o) {
    const opt = o || {};
    const structuredAttempt = op === 'assistant' && opt.singleAttempt;
    const duration = opt.срок || СРОК_ЦЕПОЧКИ[op] || 30000;
    const конец = сейчас() + (structuredAttempt ? Math.min(duration, ASSISTANT_MODEL_BUDGET_MS) : duration);
    let encodedFormat = '', responseFormat;
    if (opt.responseFormat !== undefined) {
      try { encodedFormat = JSON.stringify(opt.responseFormat); responseFormat = JSON.parse(encodedFormat); }
      catch (_) { throw new ОшибкаМодели('Неверный контракт структурированного ответа', {skip:true}); }
      if (!responseFormat || Array.isArray(responseFormat) || encodedFormat.length > 24000
          || responseFormat.type !== 'json_schema' || responseFormat.strict !== true
          || !responseFormat.schema || responseFormat.schema.type !== 'object'
          || !responseFormat.schema.properties || typeof responseFormat.schema.properties !== 'object'
          || Array.isArray(responseFormat.schema.properties) || !Array.isArray(responseFormat.schema.required)
          || !responseFormat.schema.required.length
          || !responseFormat.schema.required.every(key => typeof key === 'string'
            && Object.prototype.hasOwnProperty.call(responseFormat.schema.properties,key))
          || responseFormat.schema.additionalProperties !== false)
        throw new ОшибкаМодели('Неверный контракт структурированного ответа', {skip:true});
    }
    if (opt.режим === 'rules') throw new ОшибкаМодели('ИИ выключен до 1-го числа: лимит', { rules: true });
    const список = opt.singleAttempt ? цепочка(op).slice(0, 1) : цепочка(op);
    const снимок = opt.image && opt.image.b64 ? crypto.createHash('sha256').update(opt.image.b64).digest('hex') : '';
    const baseKey = opt.ключКэша ? ключ(op, список.join(','), opt.ключКэша) : ключ(op, список.join(','), sys, task, снимок, opt.temperature == null ? '' : String(opt.temperature), opt.maxTokens || '');
    const k0 = responseFormat ? ключ(baseKey, 'response_format', encodedFormat) : baseKey;
    // экономный ответ (короче переписка, только пакет GigaChat и YandexGPT Lite) — под своим ключом: в обычном режиме
    // его не берём (иначе худший ответ жил бы в кэше 14 дней после возврата обычного режима); в экономном — сначала
    // обычный ответ (он лучше и уже оплачен), потом экономный
    const k = opt.режим === 'economy' ? ключ(k0, 'economy') : k0;
    // «ещё вариант» у помощника (температура высокая) — каждый раз новый ответ, из кэша не берём
    const кэшировать = !(opt.temperature >= 0.5);
    const годенВ = (x) => x && typeof x.text === 'string' && (!x.bad || !!opt.годен) && (!opt.годен || opt.годен(x.text, x.generation));
    let в = null;
    if (кэшировать) {
      в = k !== k0 ? await доСрока(cache.взять(k0), конец, 'cache') : null;
      if (!годенВ(в)) в = (await доСрока(cache.взять(k), конец, 'cache')) || (в && typeof в.text === 'string' ? в : null);
    }
    if (конец <= сейчас()) throw ошибкаСрока('cache');
    if (structuredAttempt && в && !в.bad && typeof в.text === 'string' && opt.годен && !годенВ(в)) {
      // An older syntactic-only validator may have cached this as success.
      // Retain its raw evidence as a held result, never silently regenerate.
      await доСрока(cache.положить(k, {...в, bad:true}), конец, 'cache');
      журнал({op,cache:'bad',ok:false,validation:'format'});
      throw new ОшибкаМодели('Сохранённый ответ ИИ не соответствует текущему контракту', {неПоФорме:true,кэш:true});
    }
    if (в && в.bad && opt.годен && !годенВ(в) && сейчас() - (в.at || 0) < НЕ_ПО_ФОРМЕ_НА) {
      журнал({ op, cache: 'bad', ok: false });
      throw new ОшибкаМодели('ИИ ответил не по форме на эту переписку (повтор — после нового сообщения или через '
        + Math.max(1, Math.ceil((НЕ_ПО_ФОРМЕ_НА - (сейчас() - в.at)) / 60e3)) + ' мин)', { неПоФорме: true, кэш: true });
    }
    if (годенВ(в)) {
      budget.записать({ op, hit: true });
      журнал({ op, cache: true, model: в.model, ok: true, ...(в.bad ? {recovered_format:true} : {}) });
      return { text: в.text, model: в.model, cached: true, rub: 0,
        ...(в.generation ? {generation:в.generation} : {}) };
    }
    if (кэшировать && идут.has(k)) return доСрока(идут.get(k), конец, 'queue');
    const p = (async () => {
      const t0 = сейчас();
      const причины = [];
      let providerError = null;
      let неПоФорме = 0, больше = 0, rejected = null;          // ответов не по форме; повтор обрезанного (один на вопрос)
      let текстСнимка = null;                                  // распознаём не больше одного раза за вопрос
      const сТекстом = async (осталось) => {
        if (!opt.image) return task;
        if (текстСнимка == null) { try { текстСнимка = await распознать(op, opt.image, осталось); } catch (e) { текстСнимка = ''; причины.push(String(e.message || e).slice(0, 60)); } }
        return текстСнимка ? task + '\n\nТекст со снимка окна (распознан):\n' + текстСнимка.slice(0, 6000) : task;
      };
      const запас = Math.min(ЗАПАС.макс, Math.round((конец - t0) * ЗАПАС.доля));
      for (let j = 0; j < список.length; j++) {
        const model = список[j];
        if (responseFormat && !этоГига(model)) { причины.push(model + ': строгий формат поддерживается только GigaChat'); continue; }
        const всего = конец - сейчас();
        if (всего < 1500) { причины.push('нет времени'); break; }
        const д = await доСрока(budget.доступ(model), конец, 'budget');
        const осталось = конец - сейчас() - запас * (список.length - 1 - j);
        if (осталось < 1500) throw ошибкаСрока('budget');
        if (!д.можно) { причины.push(model + ': вне пакета'); continue; }
        if (opt.режим === 'economy' && !(этоГига(model) ? д.free : model === 'yandexgpt-lite')) { причины.push(model + ': экономный режим'); continue; }
        const t1 = сейчас();
        try {
          const max0 = opt.maxTokens || МАКС_ТОКЕНОВ[op] || 400;
          const повтор = больше === 1;
          if (повтор) больше = 2;
          const max = повтор ? Math.max(max0, Math.min(МАКС_ПОВТОР, Math.round(max0 * 1.5))) : max0;
          const доп = { temperature: opt.temperature, singleAttempt: !!opt.singleAttempt,
            ...(structuredAttempt ? {modelTimeoutMs:ASSISTANT_MODEL_BUDGET_MS} : {}),
            ...(responseFormat ? {responseFormat} : {}) };
          let r;
          if (этоГига(model) && (!opt.image || картинкиПонимает(model))) r = await гига(model, sys, task, max, осталось, { ...доп, image: opt.image });
          else if (этоГига(model)) r = await гига(model, sys, await сТекстом(осталось), max, Math.max(1000, осталось - (сейчас() - t1)), доп);
          else r = await яндекс(model, sys, await сТекстом(осталось), max, Math.max(1000, осталось - (сейчас() - t1)), доп);
          const rub = budget.записать({ op, model, inTok: r.inTok, outTok: r.outTok, free: д.free });
          const generation = {finish_reason:typeof r.finish === 'string' && /^[a-z_]{1,40}$/i.test(r.finish) ? r.finish : null,
            requested_max_tokens:max, prompt_tokens:r.observedUsage ? r.observedUsage.prompt_tokens : r.inTok,
            completion_tokens:r.observedUsage ? r.observedUsage.completion_tokens : r.outTok};
          const valid = !opt.годен || opt.годен(r.text, generation);
          журнал({ op, model, in: r.inTok, out: r.outTok, rub, ms: сейчас() - t1, ok: !!valid,
            ...(!valid ? {validation:'format'} : {}), ...(r.finish && r.finish !== 'stop' ? { finish: r.finish } : {}) });
          if (!valid) {
            неПоФорме++;
            // Keep bounded original output in the existing private response
            // cache. A future validator may accept its syntax without another
            // generation; unchanged invalid output still hits the same hold.
            rejected = typeof r.text === 'string' && r.text.length <= 6000
              ? {text:r.text,model,...(structuredAttempt ? {generation} : {})} : null;
            const обрезан = /^length$|TRUNCATED/i.test(String(r.finish || ''));
            // обрезан по длине — ещё раз той же моделью с запасом длины (дешевле, чем следующая платная модель)
            if (!opt.singleAttempt && обрезан && !больше && max < МАКС_ПОВТОР) { больше = 1; причины.push(model + ': ответ обрезан — повтор длиннее'); j--; continue; }
            причины.push(model + ': ответ не по форме'); continue;
          }
          const metadata = structuredAttempt ? {generation} : {};
          if (кэшировать) await доСрока(cache.положить(k, { text: r.text, model, ...metadata }), конец, 'cache');
          return { text: r.text, model, cached: false, rub, ...metadata };
        } catch (e) {
          if (opt.singleAttempt && e.providerError) providerError = e.providerError;
          журнал({ op, model, ms: сейчас() - t1, ok: false, err: String(e.message || e).slice(0, 80) });
          if (e.исчерпан) await budget.отметитьИсчерпан(model).catch(() => {});
          причины.push(String(e.message || e).slice(0, 70));
        }
      }
      // хоть одна модель ответила (и мы заплатили), но не по форме — запомнить отказ: повтор того же — без вызовов
      if (неПоФорме && кэшировать && opt.годен) await доСрока(cache.положить(k, { bad: true, model: '', ...(rejected || {}) }), конец, 'cache');
      throw new ОшибкаМодели('ИИ не ответил (' + (причины.join('; ') || 'нет моделей') + ')',
        {...(неПоФорме ? {неПоФорме:true} : {}), ...(providerError ? {providerError} : {})});
    })();
    if (!кэшировать) return p;
    идут.set(k, p);
    try { return await p; } finally { идут.delete(k); }
  }

  /* только текст со снимка (помощник AHK, kind: 'ocr') */
  async function текстСнимка(op, image) {
    const д = await budget.доступ('vision-ocr');
    if (!д.можно) throw new ОшибкаМодели('распознавание недоступно');
    return распознать(op, image, 15000);
  }

  return { спросить, цепочка, текстСнимка, ЦЕПОЧКИ };
}

function ошибкаСрока(stage) {
  return new ОшибкаМодели('GigaChat: истёк общий срок запроса',
    {providerError:{provider:'gigachat',status:null,stage,category:'deadline_exceeded',retry_after_seconds:null}});
}

module.exports = { создатьИИ, ЦЕПОЧКИ, МАКС_ТОКЕНОВ, ОшибкаМодели, GIGA_CA, ASSISTANT_MODEL_BUDGET_MS, safeProviderError };
