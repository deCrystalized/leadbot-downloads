/* ССЫЛКА ДЛЯ ОТЗЫВА, КОГДА ИСТОЧНИКА НЕТ В СПИСКЕ — как делает оператор руками:
   объявление на Авито (по нему идёт диалог) → страница продавца (аккаунта) → короткая ссылка clck.ru.
   Чистые функции: работают и в расширении (importScripts), и в node для проверок. */
const LC_AVITO = (() => {
  const BASE = 'https://www.avito.ru';
  // \u002F, \/, &amp; и %2F (данные страницы Авито закодированы как адрес: window.__initialData__ = "%7B%22…")
  const раскрыть = (s) => String(s || '').replace(/\\u002F/gi, '/').replace(/\\\//g, '/').replace(/&amp;/g, '&').replace(/%2F/gi, '/').replace(/%3F/gi, '?').replace(/%22/g, '"');
  // путь страницы продавца → полный адрес без хвостов (?src=item, #…)
  function чистый(path) {
    const p = раскрыть(path).replace(/^https?:\/\/(?:www\.|m\.)?avito\.ru/i, '').split(/[?#"]/)[0];
    let m;
    if ((m = p.match(/^\/brands\/([A-Za-z0-9_\-]{2,64})\/?$/))) return BASE + '/brands/' + m[1];
    if ((m = p.match(/^\/user\/([0-9a-f]{16,64})\/profile\/?$/i))) return BASE + '/user/' + m[1] + '/profile';
    return '';
  }
  /* Ссылка на продавца со страницы объявления:
     1) блок продавца (data-marker="seller-link/link", "seller-info/name") — надёжнее всего;
     2) данные страницы (sellerUrl / profileUrl / shopUrl);
     3) иначе — ссылка /brands/… или /user/…/profile, которая встречается чаще всех (имя, аватар, «все объявления»). */
  function sellerFromHtml(html) {
    const t = String(html || '');
    if (!t) return '';
    const marker = t.match(/data-marker="seller-(?:link\/link|info\/name)"[^>]*>(?:[^<]*<[^>]+>){0,6}?[^<]*?href="([^"]+)"/i)
      || t.match(/href="([^"]+)"[^>]*data-marker="seller-(?:link\/link|info\/name)"/i)
      || t.match(/data-marker="seller-link\/link"[^>]*href="([^"]+)"/i);
    if (marker && чистый(marker[1])) return чистый(marker[1]);
    const json = t.match(/"(?:sellerUrl|profileUrl|shopUrl|sellerProfileUrl)"\s*:\s*"([^"]+)"/i);
    if (json && чистый(json[1])) return чистый(json[1]);
    const счёт = new Map();
    for (const m of раскрыть(t).matchAll(/(?:https?:\/\/(?:www\.|m\.)?avito\.ru)?(\/(?:brands\/[A-Za-z0-9_\-]{2,64}|user\/[0-9a-f]{16,64}\/profile))(?=[?"'#\/\s])/gi)) {
      const u = чистый(m[1]);
      if (u) счёт.set(u, (счёт.get(u) || 0) + 1);
    }
    let best = '', n = 0;
    for (const [u, c] of счёт) if (c > n) { best = u; n = c; }
    return best;
  }
  const заблокировано = (html, status) => status === 429 || status === 403 || /Доступ ограничен|captcha|firewall-container|Подтвердите, что вы не робот/i.test(String(html || '').slice(0, 20000));
  // Только помеченные блоки текущего объявления: имена из похожих объявлений и скриптов не берём.
  function advertiserFromHtml(html) {
    const t = String(html || '');
    const block = (marker) => {
      const start = new RegExp('<([a-z][a-z0-9]*)\\b[^>]*data-marker=["\']' + marker + '["\'][^>]*>', 'i').exec(t);
      if (!start) return '';
      const tags = new RegExp('</?' + start[1] + '\\b[^>]*>', 'gi');
      tags.lastIndex = start.index + start[0].length;
      let depth = 1, end;
      while ((end = tags.exec(t))) {
        depth += /^<\//.test(end[0]) ? -1 : /\/>$/.test(end[0]) ? 0 : 1;
        if (!depth) return t.slice(start.index + start[0].length, end.index);
      }
      return '';
    };
    const plain = (s) => s.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '').replace(/<[^>]*>/g, ' ')
      .replace(/&#(x[\da-f]+|\d+);/gi, (_, n) => { const k = n[0].toLowerCase() === 'x' ? parseInt(n.slice(1), 16) : Number(n); return k > 0 && k <= 0x10ffff ? String.fromCodePoint(k) : ''; })
      .replace(/&(amp|quot|apos|nbsp|lt|gt);/g, (_, n) => ({ amp: '&', quot: '"', apos: "'", nbsp: ' ', lt: '<', gt: '>' })[n]).replace(/\s+/g, ' ').trim();
    return { sellerName: plain(block('seller-info/name') || block('seller-link/link')).slice(0, 160),
      description: plain(block('item-view/item-description')).slice(0, 4000) };
  }
  const объявление = (url) => /^https?:\/\/(?:www\.|m\.)?avito\.ru\/.+_\d{6,}/i.test(String(url || ''));
  const clckUrl = (u) => 'https://clck.ru/--?url=' + encodeURIComponent(u);
  const короткая = (text) => { const s = String(text || '').trim(); return /^https:\/\/clck\.ru\/[A-Za-z0-9_\-]{3,20}$/.test(s) ? s : ''; };
  return { advertiserFromHtml, sellerFromHtml, чистый, заблокировано, объявление, clckUrl, короткая };
})();
if (typeof module !== 'undefined' && module.exports) module.exports = LC_AVITO;
