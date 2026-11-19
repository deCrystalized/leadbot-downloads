/* Источники и ссылки для отзыва. Список — в том виде, как его рассылают в Telegram
   («8525 - С74 - ссылка»), по разделам КП / БТ-МНЧ / партнёр. Встроенный список — ниже;
   новый можно вставить в настройках расширения (⚙ → «Источники»), он заменит встроенный.
   Метка источника → «Комментарий партнёра», ссылка → строка 🟢ссылка🟢 в комментарии заявки
   (формат «Чатерского»). Разделы списка (КП / БТ-МНЧ) источник к базе не привязывают — см. find. */
const LC_LINKS = (() => {
  // 13.10: список от владельца (новые М19, М12, М17, А4; БТ/МНЧ в виде «6012 МНЧ - С74.2»)
  const LIST_DATE = '2026-10-13';
  const DEFAULT_TEXT = "🖥КП ИСТОЧНИКИ:\n\n1933 - 723 парт Белый Б1 -\n🛑БЕЛАЯ ЗАЯВКА 🛑\nhttps://www.avito.ru/brands/komphelper\n\n3992 - 723 парт Белый Б6 -\n🛑БЕЛАЯ ЗАЯВКА 🛑\nhttps://clck.ru/3Ustqt\n\n9485 - 723 парт Белый Б7 -\n🛑БЕЛАЯ ЗАЯВКА 🛑\nhttps://clck.ru/3UtxEt\n\n8869 - 723 парт Белый Б8 -\n🛑БЕЛАЯ ЗАЯВКА 🛑\nhttps://clck.ru/3VAhwk\n\n2997 - 723 парт Белый Б9 -\n🛑БЕЛАЯ ЗАЯВКА 🛑\nhttps://clck.ru/3W7ZB9\n\n6874 - 723 парт Белый Б10 -\n🛑БЕЛАЯ ЗАЯВКА 🛑\nhttps://clck.ru/3W7ZCn\n\n3423  - 723 парт Белый М19 -\n🛑БЕЛАЯ ЗАЯВКА 🛑\nhttps://clck.ru/3WNPgb\n\n\n🪛МНЧ ИСТОЧНИКИ:\n\n_____________________________________________________________\n\n🖥КП ИСТОЧНИКИ:\n\n0815 - А5 -\nhttps://clck.ru/3T9WL7\n\n8525 - С74 -\nhttps://clc.li/LQWwl\n\n0884  - С75 -\nhttps://clc.li/ehPWa\n\n3118 - С77 -\nhttps://clck.su/xsEvX\n\n6731 - С78 -\nhttps://clck.ru/3UvY6f\n\n6913 - С82 -\nhttps://clck.ru/3TD2b2\n\n5284 - С97 -\nhttps://clck.ru/3W7ZHL\n\n8952 - В81 -\nhttps://clc.li/xkMiW\n\n6539  - В83 -\nhttps://golnk.ru/88OvG\n\n9723  - В84.2 -\nhttps://clck.ru/3SugR5\n\n6398 - В89 -\nhttps://clck.su/ziPTe\n\n0480 - М2 -\nhttps://clck.ru/3UvYB4\n\n2287 - М12\nhttps://clck.ru/3WRxTY\n\n1467 - М13 -\nhttps://clck.su/uQKRE\n\n7504 - М16 -\nhttps://clck.ru/3Vx2xR\n\n5375 - М17 -\nhttps://clck.ru/3WRxbn\n______________________________________________________________________________\n\n🪛БТ/МНЧ Источники:🔌\n\n8013  - А4 -\nhttps://clck.ru/3WJ6Mj\n\n6012  МНЧ - С74.2 -\nhttps://clc.li/PKngr\n\n4364  МНЧ - С76 -\nhttps://clc.li/PiZKM\n\n6881 МНЧ - С79.2 -\nhttps://clck.su/WSkHf\n\n6608 МНЧ - С85 -\nhttps://clck.su/iELSy\n\n8267 МНЧ - В43 -\nhttps://clc.li/fDPJY\n\n5613 БТ - В71 -\nhttps://clc.li/UFpwd\n\n5811 МНЧ - В75 -\nhttps://clck.su/DPPJJ\n\n2388 МНЧ - В80 -\nhttps://clck.su/nzMRV\n\n2392 МНЧ - В82 -\nhttps://clck.ru/3SWmcy\n\n8774 БТ - В95 -\nhttps://clc.li/OCzal\n\n1095 МНЧ - М5 -\nhttps://clck.ru/3UvYNE\n\n3054 БТ - М10 -\nhttps://clck.ru/3VwpZP\n\n9642 БТ - М15 -\nhttps://clck.ru/3WQJQV\n\n9224 БТ  - М18\nhttps://clck.ru/3W9ydE\n____________________________________________________________________\n\n748 партнер\n\n8321 БТ - 3601 КП - Авито -\nhttps://clck.ru/3UDZEu\n\n3270 БТ - Источник №3 -\nhttps://clck.ru/3WTHy6\n";

  // латинские буквы-двойники → кириллица: в LeadChat «C74.2», в списке «С74.2»
  const LAT = { A: 'А', B: 'В', C: 'С', E: 'Е', H: 'Н', K: 'К', M: 'М', O: 'О', P: 'Р', T: 'Т', X: 'Х' };
  const key = (s) => String(s || '').toUpperCase().replace(/[ABCEHKMOPTX]/g, (c) => LAT[c]).replace(/Ё/g, 'Е')
    .replace(/\s+/g, ' ').trim();
  const num = (p) => String(p || '').replace(/\D/g, '').replace(/^0+/, '');
  const BASE = { 'КП': 'kp', 'БТ': 'bt', 'МНЧ': 'mnc' };

  /* Разбор списка. Раздел «КП ИСТОЧНИКИ» → kp; «БТ/МНЧ» → bt+mnc (строка с «БТ» в начале — только bt);
     «748 партнер» → ссылка партнёра. Пометка «БЕЛАЯ ЗАЯВКА» или «Белый» → белая заявка. */
  function parse(text) {
    const out = { entries: [], partners: {} };
    let section = null, partner = '', pending = [];
    for (const raw of String(text || '').split(/\r?\n/)) {
      const line = raw.trim();
      if (!line || /^_+$/.test(line)) continue;
      if (/^https?:\/\//i.test(line)) {
        const url = line.split(/\s+/)[0];
        for (const e of pending) { e.url = url; if (partner && e.partner) (out.partners[partner] = out.partners[partner] || []).push(e); else out.entries.push(e); }
        pending = [];
        continue;
      }
      if (/БЕЛАЯ ЗАЯВКА/i.test(line)) { pending.forEach((e) => { e.white = true; }); continue; }
      // заголовок раздела — «🪛БТ/МНЧ Источники:»; строка с номером («3270 БТ - Источник №3 -») — источник, а не раздел
      if (/источник/i.test(line) && !/^\d/.test(line)) {
        const kp = /КП/i.test(line), bt = /БТ/i.test(line), mnc = /МНЧ/i.test(line);
        section = kp && !bt && !mnc ? ['kp'] : bt && mnc ? ['bt', 'mnc'] : bt ? ['bt'] : mnc ? ['mnc'] : ['kp', 'bt', 'mnc'];
        partner = '';
        continue;
      }
      let m = line.match(/^(\d{3})\s*партн[её]р/i);
      if (m) { partner = m[1]; section = null; continue; }
      if (partner) {                                   // «8321 БТ - 3601 КП - Авито -»
        const parts = line.split(/\s*[-–—]\s*/).filter(Boolean);
        const label = parts.filter((p) => !/^\d+(\s+(БТ|КП|МНЧ))?$/i.test(p)).pop() || 'партнёр ' + partner;
        const codes = parts.map((p) => p.match(/^(\d+)/)).filter(Boolean).map((x) => x[1]);
        pending = [{ label, codes, bases: ['kp', 'bt', 'mnc'], partner: true }];
        continue;
      }
      // «БТ 5613 - В71», «5613 - В71» и (13.10) «5613 БТ - В71», «6012  МНЧ - С74.2» — база до или после номера
      m = line.match(/^(?:(БТ|КП|МНЧ)\s+)?(\d{3,4})(?:\s+(БТ|КП|МНЧ))?\s*[-–—]\s*(.+?)\s*[-–—]?\s*$/i);
      if (m) {
        let label = m[4].replace(/^\d{3}\s*парт\S*\s*/i, '').trim();
        const база = m[1] || m[3];
        const bases = база ? [BASE[база.toUpperCase()]] : (section || ['kp', 'bt', 'mnc']);
        pending = [{ code: m[2], label, bases, white: /^Белый/i.test(label) || /^723\s*парт/i.test(m[4]) }];
      }
    }
    return out;
  }

  let DATA = parse(DEFAULT_TEXT);
  let FROM = 'встроенный список';
  function use(text, from) {
    const d = parse(text);
    if (d.entries.length) { DATA = d; FROM = from || 'список из настроек'; return d.entries.length; }
    return 0;
  }

  /* Источник по метке LeadChat (lead_origin), коду или метке без «Белый» — точное совпадение. 2.1.1 (решение владельца):
     источник к базе не привязан — канал Авито ведёт любые направления, и заявка в КП из канала «С74.2» (он в разделе БТ/МНЧ)
     сохраняет и источник, и ссылку для отзыва. Раздел базы — только порядок поиска: код 4364 в КП — В99, в БТ/МНЧ — С76,
     поэтому сначала ищем в разделе этой базы, не нашли — во всём списке. Партнёр со своей ссылкой (748) — его ссылка. */
  function find(origin, dir, partnerNo) {
    const p = num(partnerNo);
    const k = key(origin);
    // 13.10: у партнёра может быть несколько источников (748: «Авито», «Источник №3») — по метке или коду; не узнали — первый
    if (p && (DATA.partners[p] || []).length) {
      const все = DATA.partners[p], kd0 = k.replace(/\D/g, '');
      const e = все.find((x) => key(x.label) === k || (kd0 && /^\d{3,4}$/.test(k) && (x.codes || []).includes(kd0))) || все[0];
      return { label: e.label, url: e.url, white: false, partner: true };
    }
    if (!k) return null;
    const kd = k.replace(/\D/g, '');
    const тот = (e) => { const lk = key(e.label);
      return lk === k || lk.replace(/^БЕЛЫЙ\s+/, '') === k.replace(/^БЕЛЫЙ\s+/, '') || (e.code && /^\d{3,4}$/.test(k) && e.code === kd); };
    const e = (dir && DATA.entries.find((x) => x.bases.includes(dir) && тот(x))) || DATA.entries.find(тот);
    return e ? { label: e.label, url: e.url, white: !!e.white, code: e.code } : null;
  }

  // «Отзыв» — партнёры автоотзыва «Чатерского»; 723 и «Белый …» — белая заявка
  const REVIEW_PARTNERS = ['7', '723', '740', '340', '748', '624'];   // 624 — по просьбе владельца 14.11
  const needsReview = (partner) => REVIEW_PARTNERS.includes(num(partner));
  const requiresReview = (partner) => num(partner) === '624';
  const isWhite = (partner, src) => num(partner) === '723' || !!(src && src.white);
  const info = () => ({ from: FROM, count: DATA.entries.length, partners: Object.keys(DATA.partners) });

  // 13.10: список из настроек действует, только если сохранён не раньше даты встроенного (иначе старые ссылки перебивали бы новые)
  const свежийСписок = (сохранён) => String(сохранён || '') >= LIST_DATE;
  return { find, needsReview, requiresReview, isWhite, parse, use, info, key, LIST_DATE, свежийСписок };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = LC_LINKS;
