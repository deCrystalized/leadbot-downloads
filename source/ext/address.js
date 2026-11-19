/* ПОИСК АДРЕСА ДВУМЯ ИИ + ПРОВЕРКА ПО КАРТЕ.
   Когда LeadChat не подтвердил адрес, YandexGPT и GigaChat НЕЗАВИСИМО ищут его в переписке
   (собирают по кускам, исправляют опечатки). Каждая часть проверяется по тексту переписки:
   улицы и номера дома, которых клиент не писал, не бывает. Потом — OpenStreetMap: есть ли такой дом.
   Чистые функции: работают и в расширении (importScripts), и в node для проверок. */
const LC_ADDRESS = (() => {
  const low = (s) => String(s || '').toLowerCase().replace(/ё/g, 'е');
  const digits = (s) => String(s || '').replace(/\D/g, '');
  // тип улицы/садоводства не часть названия: «тер. СНТ Желдорфармация» = «территория СНТ Желдорфармация» = «СНТ Желдорфармация»
  const ТИПЫ = /(^|\s)(садоводческое некоммерческое товарищество|садовое некоммерческое товарищество|садоводческое товарищество|садовые участки|территория|тер|снт|днт|тсн|сот|днп|улица|ул|проспект|пр-кт|пр-т|пр|переулок|пер|шоссе|ш|бульвар|б-р|бул|проезд|пр-д|площадь|пл|набережная|наб|микрорайон|мкр|мкрн|тупик|аллея|квартал|кв-л|линия|тракт)\.?(?=\s|$)/g;
  // порядковые и слитные числа к одному виду: «3я», «3-я», «1й» → «3», «1»; «40лет» → «40 лет»; «140Б» остаётся
  const числоВид = (s) => String(s || '').replace(/(\d+)(?:-(?:ая|ья|я|ой|ий|ый|й|го|е|ое)|(?:ая|ья|я|ой|ий|ый|й|го))(?![а-яёa-z])/gi, '$1')
    .replace(/(\d)([а-яёa-z]{2,})/gi, '$1 $2');
  // номер в названии важен: «микрорайон 12» ≠ «микрорайон 13», «1-я Линия» ≠ «2-я Линия»
  const слова = (street) => low(числоВид(street)).replace(ТИПЫ, ' ').split(/[^a-zа-я0-9]+/).filter((w) => w.length >= 3 || /^\d+$/.test(w));
  const основа = (w) => w.slice(0, Math.max(4, Math.min(6, w.length - 2)));

  function prompt(lines, ctx) {
    const sys = 'Ты внимательно читаешь переписку с клиентом и находишь АДРЕС, куда ехать мастеру. '
      + 'Бери только то, что написано в переписке (клиентом, оператором или в заметке). Ничего не придумывай. '
      + 'Ответ — один JSON без пояснений.';
    const task = [
      ctx.city ? 'Город из объявления: ' + ctx.city + ' (если клиент назвал другой город или посёлок — бери его).' : '',
      'Переписка:', ...lines.slice(-80), '',
      'Собери адрес, даже если он написан по частям в разных сообщениях или с опечатками (исправь опечатку в названии улицы, но не меняй номер дома).',
      'Верни JSON: {"city":"город","settlement":"посёлок/село/СНТ, если не город","street":"улица с типом: ул Пушкина, пр-кт Мира",'
        + '"house":"номер дома с корпусом/строением: 12к2, 5/1","flat":"квартира","entrance":"подъезд","floor":"этаж",'
        + '"quote":"дословно кусок сообщения, где назван дом"}. Чего нет — пустая строка.',
    ].filter(Boolean).join('\n');
    return { sys, task };
  }

  function parse(raw) {
    const t = String(raw || '').replace(/```(?:json)?/gi, '');
    const a = t.indexOf('{'), b = t.lastIndexOf('}');
    if (a < 0 || b <= a) return null;
    try {
      const d = JSON.parse(t.slice(a, b + 1));
      const s = (k) => String(d[k] ?? '').trim().replace(/\s+/g, ' ').slice(0, 80);
      return { city: s('city'), settlement: s('settlement'), street: s('street'), house: s('house').replace(/^(дом|д\.?)\s*/i, ''),
        flat: s('flat').replace(/^(кв\.?|квартира)\s*/i, ''), entrance: s('entrance'), floor: s('floor'), quote: s('quote') };
    } catch (_e) { return null; }
  }

  /* Каждая часть — только если она есть в переписке. Улица — по основе слова (опечатку ИИ мог
     исправить: «пушкено» → «Пушкина»); дом, квартира, подъезд, этаж — цифрами, как написал клиент. */
  /* «дом двадцать пять» → «дом 25»: номера словами тоже считаются написанными */
  const ЕД = { 'один': 1, 'одна': 1, 'два': 2, 'две': 2, 'три': 3, 'четыре': 4, 'пять': 5, 'шесть': 6, 'семь': 7, 'восемь': 8, 'девять': 9 };
  const ДЕС = { 'десять': 10, 'одиннадцать': 11, 'двенадцать': 12, 'тринадцать': 13, 'четырнадцать': 14, 'пятнадцать': 15, 'шестнадцать': 16,
    'семнадцать': 17, 'восемнадцать': 18, 'девятнадцать': 19, 'двадцать': 20, 'тридцать': 30, 'сорок': 40, 'пятьдесят': 50,
    'шестьдесят': 60, 'семьдесят': 70, 'восемьдесят': 80, 'девяносто': 90, 'сто': 100 };
  const ДЕСЯТКИ = 'двадцать|тридцать|сорок|пятьдесят|шестьдесят|семьдесят|восемьдесят|девяносто';
  function числаСловами(text) {
    let t = low(text);
    t = t.replace(new RegExp('(^|[^а-я])(' + ДЕСЯТКИ + ')\\s+(' + Object.keys(ЕД).join('|') + ')(?![а-я])', 'g'), (m, b, a, c) => b + (ДЕС[a] + ЕД[c]));
    t = t.replace(/[а-я]+/g, (w) => (ДЕС[w] ? String(ДЕС[w]) : ЕД[w] ? String(ЕД[w]) : w));
    return t;
  }
  /* Улица «есть в переписке», даже если клиент написал с опечаткой: «Пушкено» ≈ «Пушкина» (до 2 букв разницы) */
  function похоже(a, b) {
    if (Math.abs(a.length - b.length) > 2) return false;
    const d = Array.from({ length: b.length + 1 }, (_, i) => i);
    for (let i = 1; i <= a.length; i++) {
      let prev = d[0]; d[0] = i;
      for (let j = 1; j <= b.length; j++) { const tmp = d[j]; d[j] = Math.min(d[j] + 1, d[j - 1] + 1, prev + (a[i - 1] === b[j - 1] ? 0 : 1)); prev = tmp; }
    }
    return d[b.length] <= (a.length >= 7 ? 2 : 1);
  }
  function естьСлово(w, T) {
    if (T.includes(основа(w))) return true;
    if (w.length < 5) return false;
    return (T.match(/[а-яa-z]{4,}/g) || []).some((x) => x[0] === w[0] && (похоже(x, w) || похоже(x.slice(0, w.length), w)));
  }
  function ground(a, text) {
    if (!a) return null;
    text = String(text || '') + '\n' + числаСловами(text);
    const T = low(text), D = digits(text);
    const out = { ...a, notes: [] };
    const sw = слова(a.street);
    // улица в переписке: есть слово названия; если в названии одни числа («мкр 12») — то же число отдельно, а не кусок телефона или цены
    const буквы = sw.filter((w) => !/^\d+$/.test(w)), числаУл = sw.filter((w) => /^\d+$/.test(w));
    const улицаЕсть = буквы.length ? буквы.some((w) => естьСлово(w, T)) : числаУл.some((w) => new RegExp('(^|\\D)' + w + '(\\D|$)').test(T));
    if (a.street && !улицаЕсть) { out.notes.push('улицы «' + a.street + '» нет в переписке'); out.street = ''; }
    const hd = (String(a.house).match(/\d+/) || [''])[0];            // основной номер дома: «5к2» → 5
    if (a.house && (!hd || !new RegExp('(^|\\D)' + hd + '(\\D|$)').test(String(text).replace(/\s+/g, ' ')))) { out.notes.push('дома «' + a.house + '» нет в переписке'); out.house = ''; }
    for (const k of ['flat', 'entrance', 'floor']) if (out[k] && (!digits(out[k]) || !D.includes(digits(out[k])))) out[k] = '';
    if (out.settlement && !слова(out.settlement).some((w) => естьСлово(w, T))) out.settlement = '';
    if (out.city && !слова(out.city).some((w) => естьСлово(w, T))) out.city = '';
    out.ok = !!(out.street && out.house) || !!(out.settlement && out.house);
    return out;
  }

  const ключУлицы = (s) => слова(s).map(основа).sort().join(' ');
  function same(a, b) {
    if (!a || !b || !a.ok || !b.ok) return false;
    return ключУлицы(a.street || a.settlement) === ключУлицы(b.street || b.settlement) && домКлюч(a.house) === домКлюч(b.house);
  }

  /* Вместе: совпали — берём, дополняя квартирой/подъездом от того, у кого они есть.
     Не совпали — главный тот, кого подтвердит карта; второй показываем оператору. */
  /* Голосов три: YandexGPT, GigaChat, правила. Двое согласны — адрес принят. */
  function combineMany(voices) {
    const ok = voices.filter(([a]) => a && a.ok);
    for (let i = 0; i < ok.length; i++) {
      const group = ok.filter(([b]) => same(ok[i][0], b));
      if (group.length >= 2) {
        const m = { ...group[0][0] };
        for (const [b] of group.slice(1)) for (const k of ['flat', 'entrance', 'floor', 'settlement', 'city']) if (!m[k] && b[k]) m[k] = b[k];
        const rest = ok.filter((x) => !group.includes(x));
        return { best: m, alt: rest[0] ? rest[0][0] : null, altBy: rest[0] ? rest[0][1] : '', agree: true, by: group.map((x) => x[1]) };
      }
    }
    if (!ok.length) return { best: null, alt: null, agree: false, by: [] };
    return { best: ok[0][0], alt: ok[1] ? ok[1][0] : null, altBy: ok[1] ? ok[1][1] : '', agree: false, by: [ok[0][1]] };
  }
  function combine(y, g) {
    if (same(y, g)) {
      const m = { ...y };
      for (const k of ['flat', 'entrance', 'floor', 'settlement', 'city']) if (!m[k] && g[k]) m[k] = g[k];
      return { best: m, alt: null, agree: true, by: ['YandexGPT', 'GigaChat'] };
    }
    const list = [y && y.ok ? [y, 'YandexGPT'] : null, g && g.ok ? [g, 'GigaChat'] : null].filter(Boolean);
    if (!list.length) return { best: null, alt: null, agree: false, by: [] };
    return { best: list[0][0], alt: list[1] ? list[1][0] : null, agree: false, by: [list[0][1]], altBy: list[1] ? list[1][1] : '' };
  }

  /* OpenStreetMap (Nominatim): структурный поиск «дом + улица, город» */
  const ПОЛНО = [[/(^|\s)пр-кт\.?(?=\s|$)|(^|\s)пр-т\.?(?=\s|$)|(^|\s)пр\.(?=\s|$)/i, ' проспект '], [/(^|\s)пер\.?(?=\s|$)/i, ' переулок '],
    [/(^|\s)ш\.?(?=\s|$)/i, ' шоссе '], [/(^|\s)б-р\.?(?=\s|$)|(^|\s)бул\.?(?=\s|$)/i, ' бульвар '], [/(^|\s)пр-д\.?(?=\s|$)/i, ' проезд '],
    [/(^|\s)наб\.?(?=\s|$)/i, ' набережная '], [/(^|\s)пл\.?(?=\s|$)/i, ' площадь '], [/(^|\s)мкр\.?(?=\s|$)|(^|\s)мкрн\.?(?=\s|$)/i, ' микрорайон ']];
  const полнаяУлица = (s) => { let t = ' ' + String(s || '') + ' '; for (const [rx, w] of ПОЛНО) t = t.replace(rx, w); return t.replace(/(^|\s)(ул|улица)\.?\s+/i, ' ').replace(/\s+/g, ' ').trim(); };
  function osmUrl(a, city, free) {
    const u = new URL('https://nominatim.openstreetmap.org/search');
    const street = полнаяУлица(a.street);
    if (free) {
      u.searchParams.set('q', [street, a.house, a.settlement || a.city || city].filter(Boolean).join(', '));
      for (const [k, v] of [['countrycodes', 'ru'], ['format', 'jsonv2'], ['addressdetails', '1'], ['limit', '5'], ['accept-language', 'ru']]) u.searchParams.set(k, v);
      return u.href;
    }
    if (street) u.searchParams.set('street', (a.house ? a.house + ' ' : '') + street);
    const c = a.settlement || a.city || city || '';
    if (c) u.searchParams.set('city', c.replace(/^(г|город|пос[её]лок|пгт|п|с|село|д|деревня)\.?\s+/i, ''));
    u.searchParams.set('countrycodes', 'ru');
    u.searchParams.set('format', 'jsonv2');
    u.searchParams.set('addressdetails', '1');
    u.searchParams.set('limit', '5');
    u.searchParams.set('accept-language', 'ru');
    return u.href;
  }
  // OSM: дом засчитываем, только если он в нужном населённом пункте (свободный поиск находит такую же улицу в другом регионе)
  const местаOSM = (ad) => [ad.city, ad.town, ad.village, ad.hamlet, ad.suburb, ad.city_district, ad.municipality, ad.county].filter(Boolean);
  const тамЖе = (names, want) => !want.length || names.some((n) => want.some((w) => { const x = нп(n).replace(/\s*(муниципальный|городской)?\s*(округ|район)$/, ''), y = нп(w);
    return x === y || (y.length >= 5 && x.length >= 5 && (x.startsWith(y.slice(0, y.length - 1)) || y.startsWith(x.slice(0, x.length - 1)))); }));
  function osmJudge(results, a, city) {
    const hd = домКлюч(a.house);
    const sk = ключУлицы(полнаяУлица(a.street));
    const want = [a.settlement, a.city || city].filter(Boolean).map((x) => String(x).replace(/\s*\(.*?\)\s*/g, ' ').trim());
    let street = null;
    for (const r of results || []) {
      const ad = r.address || {};
      if (!тамЖе(местаOSM(ad), want)) continue;
      const road = ad.road || ad.pedestrian || ad.residential || r.name || '';
      const roadOk = !sk || ключУлицы(road) === sk || слова(road).some((w) => sk.split(' ').includes(основа(w)));
      if (!roadOk) continue;
      if (ad.house_number && домКлюч(ad.house_number) === hd) {
        return { status: 'exact', text: [road, ad.house_number, ad.city || ad.town || ad.village || ''].filter(Boolean).join(', '),
          map: 'https://yandex.ru/maps/?pt=' + r.lon + ',' + r.lat + '&z=17' };
      }
      street = street || r;
    }
    if (street) return { status: 'house_missing', text: 'улица есть на карте, дома ' + a.house + ' в OpenStreetMap нет' };
    return { status: 'not_found', text: 'OpenStreetMap такой адрес не нашёл' };
  }

  /* ---------- проверка по картам и реестру ---------- */
  // Точное подтверждение сохраняет дробь, корпус, строение и букву. Условный ключ старого поиска здесь не подходит.
  let ключДома = null;
  const домКлюч = (h) => {
    if (!ключДома) {
      let R = typeof LC_ADDR_RULES !== 'undefined' ? LC_ADDR_RULES : null;
      try { R = R || (typeof require === 'function' ? require('./addrrules.js') : null); } catch (_e) { R = null; }
      ключДома = R ? R.точныйКлючДома : (x) => low(x).replace(/\s+/g, '').replace(/^(д\.?|дом)/, '');
    }
    return ключДома(h);
  };
  const числа = (s) => (low(числоВид(полнаяУлица(s))).match(/\d+(?:[а-яa-z](?![а-яa-z]))?/g) || []).sort().join(' ');
  const улицаСовпала = (a, name) => !a.street || ((!числа(a.street) || !числа(name) || числа(a.street) === числа(name))
    && (ключУлицы(полнаяУлица(a.street)) === ключУлицы(полнаяУлица(name))
    || слова(полнаяУлица(name)).some((w) => ключУлицы(полнаяУлица(a.street)).split(' ').includes(основа(w)))));
  const где = (a, city) => a.settlement || a.city || city || '';
  // тот же населённый пункт: «Абакан» ≠ «Усть-Абакан»; тип («г», «д», «пос») не важен
  const нп = (x) => low(x).replace(/^(г|город|гор|пос[её]лок|пос|п|пгт|рп|д|дер|деревня|с|село|снт|днп|днт|тсн|кп|ст-ца|станица|х|хутор|аул)\.?\s+/, '').replace(/[«»"]/g, '').trim();
  const тотЖеНП = (a, city, name) => { const want = нп(где(a, city)); return !want || !name || нп(name) === want; };

  // Геокодер Яндекса: точность exact + тот же дом
  function ygeoUrl(a, city, key) {
    const q = [где(a, city), полнаяУлица(a.street), a.house].filter(Boolean).join(', ');
    return 'https://geocode-maps.yandex.ru/1.x/?apikey=' + encodeURIComponent(key) + '&format=json&results=3&lang=ru_RU&geocode=' + encodeURIComponent(q);
  }
  function ygeoJudge(j, a, city) {
    const list = (((j || {}).response || {}).GeoObjectCollection || {}).featureMember || [];
    let street = null;
    for (const f of list) {
      const g = f.GeoObject || {}, md = (g.metaDataProperty || {}).GeocoderMetaData || {};
      const comp = (md.Address || {}).Components || [];
      // микрорайон без улиц («Улан-Удэ, мкр 140Б, 1») Яндекс пишет районом (district), а не улицей
      const мкр = (comp.find((c) => c.kind === 'district' && /микрорайон|мкр|квартал/i.test(c.name || '')) || {}).name || '';
      let road = (comp.find((c) => c.kind === 'street') || {}).name || '';
      const house = (comp.find((c) => c.kind === 'house') || {}).name || '';
      const locality = (comp.find((c) => c.kind === 'locality') || {}).name || '';
      if (мкр && !(road && улицаСовпала(a, road)) && улицаСовпала(a, мкр)) road = мкр;
      if (!улицаСовпала(a, road || locality)) continue;
      if (!тотЖеНП(a, city, locality)) continue;
      const pos = String((g.Point || {}).pos || '').split(' ');
      if (house && домКлюч(house) === домКлюч(a.house) && (md.precision === 'exact' || md.precision === 'number')) {
        return { status: 'exact', by: 'Яндекс.Карты', text: md.text || '', map: pos.length === 2 ? 'https://yandex.ru/maps/?pt=' + pos[0] + ',' + pos[1] + '&z=17' : '', street: road };
      }
      street = street || { road, house };
    }
    if (street) return { status: 'house_missing', by: 'Яндекс.Карты', text: 'Яндекс.Карты: улица есть, дома ' + a.house + ' нет' + (street.house ? ' (ближайший — ' + street.house + ')' : '') };
    return { status: 'not_found', by: 'Яндекс.Карты', text: 'Яндекс.Карты не нашли такой адрес' };
  }

  // DaData (ФИАС): подсказка до уровня дома (fias_level 8) с тем же номером
  function dadataBody(a, city) {
    return JSON.stringify({ query: [где(a, city), полнаяУлица(a.street), a.house ? 'д ' + a.house : ''].filter(Boolean).join(' '), count: 5 });
  }
  function dadataJudge(j, a, city) {
    let street = null;
    for (const s of (j && j.suggestions) || []) {
      const d = s.data || {};
      if (!улицаСовпала(a, d.street_with_type || d.street || d.settlement_with_type || '')) continue;
      // микрорайон без улиц в ФИАС — «поселение» внутри города («г Улан-Удэ, мкр 140Б, д 1»): город сверяем по city
      const мкр = !d.street_with_type && !d.street && /^(мкр|микрорайон|мкрн|кв-л|квартал)(?=[\s.]|$)/i.test(d.settlement_with_type || '');
      if (!тотЖеНП(a, city, мкр ? (d.city || '') : (d.settlement || d.city || ''))) continue;
      // дом есть в реестре: уровень «дом» и свой код. Несуществующий DaData возвращает эхом (уровень «улица», без кода)
      if (!(Number(d.fias_level) >= 8 && (d.house_fias_id || d.house_kladr_id))) { street = street || s; continue; }
      const house = [d.house, d.block ? (d.block_type || 'к') + d.block : ''].filter(Boolean).join('');
      if (d.house && домКлюч(house) === домКлюч(a.house)) {
        return { status: 'exact', by: 'ФИАС (DaData)', text: s.value, street: d.street_with_type || '',
          map: d.geo_lat ? 'https://yandex.ru/maps/?pt=' + d.geo_lon + ',' + d.geo_lat + '&z=17' : '' };
      }
      street = street || s;
    }
    if (street) return { status: 'house_missing', by: 'ФИАС (DaData)', text: 'в реестре ФИАС улица есть, дома ' + a.house + ' нет' };
    return { status: 'not_found', by: 'ФИАС (DaData)', text: 'в реестре ФИАС такого адреса нет' };
  }

  // Геосаджест Яндекса: исправить опечатку в улице («Пушкено» → «улица Пушкина»), только если похоже
  function ysugUrl(a, city, key) {
    return 'https://suggest-maps.yandex.ru/v1/suggest?apikey=' + encodeURIComponent(key) + '&lang=ru&results=5&print_address=1&types=street&text='
      + encodeURIComponent([где(a, city), полнаяУлица(a.street)].filter(Boolean).join(' '));
  }
  function ysugFix(j, a, city) {
    const мои = слова(полнаяУлица(a.street));
    const c = low(где(a, city));
    for (const r of (j && j.results) || []) {
      const comps = ((r.address || {}).component || []);
      const st = (comps.find((x) => (x.kind || []).includes('STREET')) || {}).name || '';
      const loc = low((comps.find((x) => (x.kind || []).includes('LOCALITY')) || {}).name || '');
      if (!st || (c && loc && !loc.endsWith(c.replace(/^(г|город)\.?\s+/, '')) && !c.includes(loc))) continue;
      const их = слова(полнаяУлица(st));
      if (мои.length && мои.every((w) => их.some((x) => x === w || похоже(x, w)))) return st;
    }
    return '';
  }

  /* Строка для карточки LeadChat — как он сам пишет: «ул Мира, 42, Мытищи, кв 7, подъезд 2, этаж 15» */
  function toLine(a, city) {
    return [a.street, a.house, a.settlement || a.city || city, a.flat ? 'кв ' + a.flat : '', a.entrance ? 'подъезд ' + a.entrance : '',
      a.floor ? 'этаж ' + a.floor : ''].filter(Boolean).join(', ');
  }

  return { prompt, parse, ground, same, combine, combineMany, osmUrl, osmJudge, toLine, ygeoUrl, ygeoJudge, dadataBody, dadataJudge, ysugUrl, ysugFix, полнаяУлица, ключУлицы, домКлюч };
})();
if (typeof module !== 'undefined' && module.exports) module.exports = LC_ADDRESS;
