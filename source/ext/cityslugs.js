/* ГОРОД ОБЪЯВЛЕНИЯ ПО СЛАГУ АВИТО («kurskaya_oblast_zheleznogorsk» → Железногорск, Europe/Moscow).
   LeadChat отдаёт город объявления только из своего справочника: для незнакомого слага city_name и
   city_tz пусты, остаётся латинский city_slug. Здесь копия того же справочника (LeadChat,
   app/integrations/avito/listing_url.py: CITIES и приставки областей) и слаги Leadbot (brain/avito_city.py),
   которых там нет. Разбор как в LeadChat: точный слаг → «область_город» → «город_район».
   Отличия: приставка области известна, а города нет — пояс берём по области (он у области один), имя
   переводим из латиницы; незнакомую приставку («…_oblast_…») отрезаем, пояс не угадываем.
   Одноимённые города разных поясов (Железногорск, Троицк) по имени не угадываем.
   Чистые функции: работают и в расширении, и в node для проверок. */
const LC_CITY_SLUGS = (() => {
  const ОБЛАСТИ = [
    ['Europe/Kaliningrad', 'kaliningradskaya_oblast', 'kaliningrad=Калининград'],   // Калининградская область
    ['Europe/Moscow', '', 'moskva=Москва|moskva_zelenograd=Зеленоград|scherbinka=Щербинка|moskovskaya_oblast_troitsk=Троицк|'
        + 'kommunarka=Коммунарка|moskovskaya_oblast_moskovskiy=Московский'],   // Москва
    ['Europe/Moscow', '', 'moskva_i_mo=Москва и МО'],   // Москва и область
    ['Europe/Moscow', 'moskovskaya_oblast', 'balashiha=Балашиха|himki=Химки|podolsk=Подольск|korolev=Королёв|mytischi=Мытищи|lyubercy=Люберцы|'
        + 'krasnogorsk=Красногорск|odintsovo=Одинцово|odincovo=Одинцово|domodedovo=Домодедово|serpuhov=Серпухов|'
        + 'kolomna=Коломна|elektrostal=Электросталь|noginsk=Ногинск|ramenskoe=Раменское|schelkovo=Щёлково|'
        + 'zhukovskiy=Жуковский|sergiev_posad=Сергиев Посад|orehovo-zuevo=Орехово-Зуево|dolgoprudnyy=Долгопрудный|'
        + 'reutov=Реутов|dmitrov=Дмитров|vidnoe=Видное|naro-fominsk=Наро-Фоминск|lyubertsy=Люберцы|lytkarino=Лыткарино|'
        + 'kraskovo=Красково|klin=Клин|zvenigorod=Звенигород|moskovskaya_oblast_chehov=Чехов|istra=Истра|'
        + 'solnechnogorsk=Солнечногорск|voskresensk=Воскресенск|pushkino=Пушкино|pavlovskiy_posad=Павловский Посад|'
        + 'tuchkovo=Тучково|aprelevka=Апрелевка|bronnitsy=Бронницы|kubinka=Кубинка|lobnya=Лобня|'
        + 'staraya_kupavna=Старая Купавна|fryazino=Фрязино|krasnoarmeysk=Красноармейск|dedovsk=Дедовск|monino=Монино|'
        + 'elektrogorsk=Электрогорск|malahovka=Малаховка|moskovskaya_oblast_ivanteevka=Ивантеевка|tomilino=Томилино|'
        + 'dzerzhinskiy=Дзержинский|kotelniki=Котельники|likino-dulevo=Ликино-Дулёво|sverdlovskiy=Свердловский|'
        + 'losino-petrovskiy=Лосино-Петровский|hotkovo=Хотьково'],   // Московская область
    ['Europe/Moscow', '', 'sankt-peterburg=Санкт-Петербург|sankt-peterburg_kolpino=Колпино|sankt-peterburg_krasnoye_selo=Красное Село|'
        + 'sankt-peterburg_kronstadt=Кронштадт|sankt-peterburg_peterhof=Петергоф|sankt-peterburg_sestroretsk=Сестрорецк|'
        + 'sankt-peterburg_pushkin=Пушкин|sankt-peterburg_lomonosov=Ломоносов'],   // Санкт-Петербург
    ['Europe/Moscow', 'leningradskaya_oblast', 'gatchina=Гатчина|vyborg=Выборг|leningradskaya_oblast_kommunar=Коммунар|sertolovo=Сертолово|kudrovo=Кудрово|'
        + 'vsevolozhsk=Всеволожск|koltushi=Колтуши|murino=Мурино|bugry=Бугры|yanino-1=Янино-1|'
        + 'novoe_devyatkino=Новое Девяткино'],   // Ленинградская область
    ['Europe/Moscow', 'novgorodskaya_oblast', 'velikiy_novgorod=Великий Новгород'],   // Новгородская область
    ['Europe/Moscow', 'pskovskaya_oblast', 'pskov=Псков|velikie_luki=Великие Луки'],   // Псковская область
    ['Europe/Moscow', 'murmanskaya_oblast', 'murmansk=Мурманск|severomorsk=Североморск|apatity=Апатиты'],   // Мурманская область
    ['Europe/Moscow', 'respublika_kareliya', 'petrozavodsk=Петрозаводск'],   // Республика Карелия
    ['Europe/Moscow', 'arhangelskaya_oblast', 'arhangelsk=Архангельск|severodvinsk=Северодвинск'],   // Архангельская область
    ['Europe/Moscow', 'neneckiy_ao', 'naryan-mar=Нарьян-Мар'],   // Ненецкий АО
    ['Europe/Moscow', 'respublika_komi', 'syktyvkar=Сыктывкар|uhta=Ухта'],   // Республика Коми
    ['Europe/Moscow', 'vologodskaya_oblast', 'vologda=Вологда|cherepovec=Череповец|cherepovets=Череповец'],   // Вологодская область
    ['Europe/Moscow', 'tverskaya_oblast', 'tver=Тверь'],   // Тверская область
    ['Europe/Moscow', 'smolenskaya_oblast', 'smolensk=Смоленск'],   // Смоленская область
    ['Europe/Moscow', 'bryanskaya_oblast', 'bryansk=Брянск'],   // Брянская область
    ['Europe/Moscow', 'kaluzhskaya_oblast', 'kaluga=Калуга|obninsk=Обнинск'],   // Калужская область
    ['Europe/Moscow', 'tulskaya_oblast', 'tula=Тула|novomoskovsk=Новомосковск'],   // Тульская область
    ['Europe/Moscow', 'ryazanskaya_oblast', 'ryazan=Рязань'],   // Рязанская область
    ['Europe/Moscow', 'vladimirskaya_oblast', 'vladimir=Владимир|kovrov=Ковров|aleksandrov=Александров'],   // Владимирская область
    ['Europe/Moscow', 'ivanovskaya_oblast', 'ivanovo=Иваново|ivanovskaya_oblast_shuya=Шуя'],   // Ивановская область
    ['Europe/Moscow', 'kostromskaya_oblast', 'kostroma=Кострома'],   // Костромская область
    ['Europe/Moscow', 'yaroslavskaya_oblast', 'yaroslavl=Ярославль|rybinsk=Рыбинск'],   // Ярославская область
    ['Europe/Moscow', 'orlovskaya_oblast', 'orel=Орёл'],   // Орловская область
    ['Europe/Moscow', 'kurskaya_oblast', 'kursk=Курск|kurchatov=Курчатов|kurskaya_oblast_zheleznogorsk=Железногорск'],   // Курская область
    ['Europe/Moscow', 'belgorodskaya_oblast', 'belgorod=Белгород|staryy_oskol=Старый Оскол|gubkin=Губкин'],   // Белгородская область
    ['Europe/Moscow', 'lipetskaya_oblast', 'lipeck=Липецк|elec=Елец|lipetsk=Липецк|elets=Елец'],   // Липецкая область
    ['Europe/Moscow', 'voronezhskaya_oblast', 'voronezh=Воронеж'],   // Воронежская область
    ['Europe/Moscow', 'tambovskaya_oblast', 'tambov=Тамбов'],   // Тамбовская область
    ['Europe/Moscow', 'nizhegorodskaya_oblast', 'nizhniy_novgorod=Нижний Новгород|dzerzhinsk=Дзержинск|arzamas=Арзамас|bor=Бор'],   // Нижегородская область
    ['Europe/Kirov', 'kirovskaya_oblast', 'kirov=Киров'],   // Кировская область
    ['Europe/Moscow', 'chuvashiya', 'cheboksary=Чебоксары|novocheboksarsk=Новочебоксарск'],   // Чувашская Республика
    ['Europe/Moscow', 'respublika_mariy_el', 'yoshkar-ola=Йошкар-Ола'],   // Республика Марий Эл
    ['Europe/Moscow', 'respublika_mordoviya', 'saransk=Саранск'],   // Республика Мордовия
    ['Europe/Moscow', 'penzenskaya_oblast', 'penza=Пенза'],   // Пензенская область
    ['Europe/Moscow', 'respublika_tatarstan', 'kazan=Казань|elabuga=Елабуга|naberezhnye_chelny=Набережные Челны|nizhnekamsk=Нижнекамск|almetevsk=Альметьевск|'
        + 'zelenodolsk=Зеленодольск'],   // Республика Татарстан
    ['Europe/Volgograd', 'volgogradskaya_oblast', 'volgograd=Волгоград|volzhskiy=Волжский|kamyshin=Камышин'],   // Волгоградская область
    ['Europe/Moscow', 'rostovskaya_oblast', 'rostov-na-donu=Ростов-на-Дону|bolshie_saly=Большие Салы|taganrog=Таганрог|shahty=Шахты|volgodonsk=Волгодонск|'
        + 'novocherkassk=Новочеркасск|bataysk=Батайск'],   // Ростовская область
    ['Europe/Moscow', 'krasnodarskiy_kray', 'krasnodar=Краснодар|sochi=Сочи|novorossiysk=Новороссийск|armavir=Армавир|anapa=Анапа|gelendzhik=Геленджик|'
        + 'slavyansk-na-kubani=Славянск-на-Кубани|krymsk=Крымск|tuapse=Туапсе'],   // Краснодарский край
    ['Europe/Moscow', 'stavropolskiy_kray', 'stavropol=Ставрополь|pyatigorsk=Пятигорск|kislovodsk=Кисловодск|essentuki=Ессентуки|nevinnomyssk=Невинномысск'],   // Ставропольский край
    ['Europe/Moscow', 'respublika_adygeya', 'maykop=Майкоп'],   // Республика Адыгея
    ['Europe/Moscow', 'respublika_kalmykiya', 'elista=Элиста'],   // Республика Калмыкия
    ['Europe/Moscow', 'karachaevo-cherkesiya', 'cherkessk=Черкесск'],   // Карачаево-Черкесия
    ['Europe/Moscow', 'kabardino-balkariya', 'nalchik=Нальчик'],   // Кабардино-Балкария
    ['Europe/Moscow', 'severnaya_osetiya', 'vladikavkaz=Владикавказ'],   // Северная Осетия
    ['Europe/Moscow', 'respublika_ingushetiya', 'magas=Магас|nazran=Назрань'],   // Республика Ингушетия
    ['Europe/Moscow', 'chechenskaya_respublika', 'groznyy=Грозный'],   // Чеченская Республика
    ['Europe/Moscow', 'respublika_dagestan', 'mahachkala=Махачкала|derbent=Дербент|kaspiysk=Каспийск|hasavyurt=Хасавюрт'],   // Республика Дагестан
    ['Europe/Simferopol', 'respublika_krym', 'simferopol=Симферополь|kerch=Керчь|yalta=Ялта|evpatoriya=Евпатория|feodosiya=Феодосия'],   // Республика Крым
    ['Europe/Simferopol', '', 'sevastopol=Севастополь|inkerman=Инкерман'],   // Севастополь
    ['Europe/Astrakhan', 'astrahanskaya_oblast', 'astrahan=Астрахань'],   // Астраханская область
    ['Europe/Samara', 'samarskaya_oblast', 'samara=Самара|tolyatti=Тольятти|zhigulevsk=Жигулёвск|petra_dubrava=Петра Дубрава|syzran=Сызрань|'
        + 'novokuybyshevsk=Новокуйбышевск'],   // Самарская область
    ['Europe/Samara', 'udmurtiya', 'izhevsk=Ижевск|votkinsk=Воткинск'],   // Удмуртская Республика
    ['Europe/Saratov', 'saratovskaya_oblast', 'saratov=Саратов|engels=Энгельс|balakovo=Балаково'],   // Саратовская область
    ['Europe/Ulyanovsk', 'ulyanovskaya_oblast', 'ulyanovsk=Ульяновск|dimitrovgrad=Димитровград'],   // Ульяновская область
    ['Asia/Yekaterinburg', 'sverdlovskaya_oblast', 'ekaterinburg=Екатеринбург|nizhniy_tagil=Нижний Тагил|kamensk-uralskiy=Каменск-Уральский|'
        + 'pervouralsk=Первоуральск|verhnyaya_pyshma=Верхняя Пышма'],   // Свердловская область
    ['Asia/Yekaterinburg', 'chelyabinskaya_oblast', 'chelyabinsk=Челябинск|magnitogorsk=Магнитогорск|zlatoust=Златоуст|miass=Миасс|kopeysk=Копейск|'
        + 'chelyabinskaya_oblast_troitsk=Троицк'],   // Челябинская область
    ['Asia/Yekaterinburg', 'kurganskaya_oblast', 'kurgan=Курган'],   // Курганская область
    ['Asia/Yekaterinburg', 'tyumenskaya_oblast', 'tyumen=Тюмень|tobolsk=Тобольск'],   // Тюменская область
    ['Asia/Yekaterinburg', 'hanty-mansiyskiy_ao', 'hanty-mansiysk=Ханты-Мансийск|surgut=Сургут|nizhnevartovsk=Нижневартовск|nefteyugansk=Нефтеюганск'],   // ХМАО — Югра
    ['Asia/Yekaterinburg', 'yamalo-neneckiy_ao', 'salehard=Салехард|novyy_urengoy=Новый Уренгой|noyabrsk=Ноябрьск'],   // Ямало-Ненецкий АО
    ['Asia/Yekaterinburg', 'permskiy_kray', 'perm=Пермь|berezniki=Березники|krasnokamsk=Краснокамск|solikamsk=Соликамск'],   // Пермский край
    ['Asia/Yekaterinburg', 'respublika_bashkortostan bashkortostan', 'ufa=Уфа|sterlitamak=Стерлитамак|salavat=Салават|neftekamsk=Нефтекамск|oktyabrskiy=Октябрьский|'
        + 'bashkortostan_oktyabrskiy=Октябрьский'],   // Республика Башкортостан
    ['Asia/Yekaterinburg', 'orenburgskaya_oblast', 'orenburg=Оренбург|orsk=Орск|novotroick=Новотроицк|novotroitsk=Новотроицк'],   // Оренбургская область
    ['Asia/Omsk', 'omskaya_oblast', 'omsk=Омск'],   // Омская область
    ['Asia/Novosibirsk', 'novosibirskaya_oblast', 'novosibirsk=Новосибирск|berdsk=Бердск'],   // Новосибирская область
    ['Asia/Barnaul', 'altayskiy_kray', 'barnaul=Барнаул|biysk=Бийск|rubcovsk=Рубцовск|rubtsovsk=Рубцовск|novoaltaysk=Новоалтайск'],   // Алтайский край
    ['Asia/Barnaul', 'respublika_altay', 'gorno-altaysk=Горно-Алтайск'],   // Республика Алтай
    ['Asia/Tomsk', 'tomskaya_oblast', 'tomsk=Томск|tomskaya_oblast_svetlyy=Светлый|seversk=Северск'],   // Томская область
    ['Asia/Novokuznetsk', 'kemerovskaya_oblast', 'kemerovo=Кемерово|novokuzneck=Новокузнецк|prokopevsk=Прокопьевск|mezhdurechensk=Междуреченск|'
        + 'leninsk-kuzneckiy=Ленинск-Кузнецкий|novokuznetsk=Новокузнецк|leninsk-kuznetskiy=Ленинск-Кузнецкий'],   // Кемеровская область
    ['Asia/Krasnoyarsk', 'krasnoyarskiy_kray', 'krasnoyarsk=Красноярск|norilsk=Норильск|achinsk=Ачинск|krasnoyarskiy_kray_zheleznogorsk=Железногорск|'
        + 'minusinsk=Минусинск|krasnoyarskiy_kray_sosnovoborsk=Сосновоборск'],   // Красноярский край
    ['Asia/Krasnoyarsk', 'respublika_hakasiya', 'abakan=Абакан|chernogorsk=Черногорск'],   // Республика Хакасия
    ['Asia/Krasnoyarsk', 'respublika_tyva', 'kyzyl=Кызыл'],   // Республика Тыва
    ['Asia/Irkutsk', 'irkutskaya_oblast', 'irkutsk=Иркутск|bratsk=Братск|angarsk=Ангарск|ust-ilimsk=Усть-Илимск'],   // Иркутская область
    ['Asia/Irkutsk', 'respublika_buryatiya', 'ulan-ude=Улан-Удэ'],   // Республика Бурятия
    ['Asia/Chita', 'zabaykalskiy_kray', 'chita=Чита'],   // Забайкальский край
    ['Asia/Yakutsk', 'respublika_saha_yakutiya', 'yakutsk=Якутск|neryungri=Нерюнгри'],   // Республика Саха (Якутия)
    ['Asia/Yakutsk', 'amurskaya_oblast', 'blagoveschensk=Благовещенск|svobodnyy=Свободный'],   // Амурская область
    ['Asia/Vladivostok', 'primorskiy_kray', 'vladivostok=Владивосток|ussuriysk=Уссурийск|nahodka=Находка|artem=Артём'],   // Приморский край
    ['Asia/Vladivostok', 'habarovskiy_kray', 'habarovsk=Хабаровск|komsomolsk-na-amure=Комсомольск-на-Амуре'],   // Хабаровский край
    ['Asia/Vladivostok', 'evreyskaya_ao', 'birobidzhan=Биробиджан'],   // Еврейская АО
    ['Asia/Magadan', 'magadanskaya_oblast', 'magadan=Магадан'],   // Магаданская область
    ['Asia/Sakhalin', 'sahalinskaya_oblast', 'yuzhno-sahalinsk=Южно-Сахалинск'],   // Сахалинская область
    ['Asia/Kamchatka', 'kamchatskiy_kray', 'petropavlovsk-kamchatskiy=Петропавловск-Камчатский'],   // Камчатский край
    ['Asia/Anadyr', 'chukotskiy_ao', 'anadyr=Анадырь'],   // Чукотский АО
  ];
  const ГОРОД = new Map(), ПРИСТАВКА = new Map();
  ОБЛАСТИ.forEach(([, приставки, список], r) => {
    for (const p of приставки.split(' ').filter(Boolean)) ПРИСТАВКА.set(p, r);
    for (const x of список.split('|')) { const [слаг, имя] = x.split('='); ГОРОД.set(слаг, { name: имя, r }); }
  });
  const поясОбласти = (r) => ОБЛАСТИ[r][0];
  // слова, которыми кончается название области («…_oblast», «…_kray»): такой хвост — не район города
  const СЛОВА_ОБЛАСТИ = new Set(['oblast', 'obl', 'kray', 'kraj', 'respublika', 'ao', 'okrug', 'avtonomnyy']);
  const похожНаРайон = (tail) => !!tail && !ГОРОД.has(tail) && !ПРИСТАВКА.has(tail) && !tail.split('_').some((w) => СЛОВА_ОБЛАСТИ.has(w));
  const город = (c, rest, tz) => ({ name: c ? c.name : '', rest: c ? '' : rest, tz });

  /* Слаг → {name, tz, rest}: name — город по справочнику (пусто — не знаем, rest переводить из латиницы),
     tz — пояс (пусто — не знаем). Не слаг или ничего не понятно — null. */
  function поСлагу(s) {
    const slug = String(s || '').trim().toLowerCase().replace(/\s+/g, '_');
    if (!slug || !/^[a-z0-9_-]+$/.test(slug)) return null;
    const точно = ГОРОД.get(slug);
    if (точно) return город(точно, '', поясОбласти(точно.r));
    // сама область («sverdlovskaya_oblast» — объявление на всю область): города не знаем, а пояс у области один
    if (ПРИСТАВКА.has(slug)) return { ...город(null, slug, поясОбласти(ПРИСТАВКА.get(slug))), область: true };
    const parts = slug.split('_').filter(Boolean);
    if (parts.length < 2 || parts.length > 8) return null;                // длиннее не бывает — мусор, не перебираем
    for (let cut = parts.length - 1; cut > 0; cut--) {
      const head = parts.slice(0, cut).join('_'), tail = parts.slice(cut).join('_');
      // «область_город»: город другой области с тем же именем — имя из справочника, пояс по области из слага
      if (ПРИСТАВКА.has(head)) return город(ГОРОД.get(tail), tail, поясОбласти(ПРИСТАВКА.get(head)));
      // «город_район» (moskva_butovo): район живёт в поясе города
      const c = ГОРОД.get(head);
      if (c && похожНаРайон(tail)) return город(c, '', поясОбласти(c.r));
    }
    // «город_область» (zheleznogorsk_kurskaya_oblast): область названа хвостом
    for (let cut = 1; cut < parts.length; cut++) {
      const head = parts.slice(0, cut).join('_'), tail = parts.slice(cut).join('_');
      if (ПРИСТАВКА.has(tail)) return город(ГОРОД.get(head), head, поясОбласти(ПРИСТАВКА.get(tail)));
    }
    // незнакомая область («…_oblast_город», «respublika_X_город»): приставку отрезаем, пояс не угадываем
    let i = -1;
    parts.forEach((w, k) => { if (СЛОВА_ОБЛАСТИ.has(w)) i = k; });
    if (i === 0) i = 1;
    if (i >= 0 && i < parts.length - 1) { const tail = parts.slice(i + 1).join('_'); return город(ГОРОД.get(tail), tail, ''); }
    return null;
  }

  /* Пояс по имени города («Ачинск», «г. Киров», «Протвино (Серпухов)») — только если имя однозначно:
     город с собственным слагом и одним поясом. Имена, которые Авито само уточняет областью
     («tomskaya_oblast_svetlyy» — Светлых несколько), и одноимённые города разных поясов — '' (не знаем). */
  const ключИмени = (s) => String(s || '').toLowerCase().replace(/ё/g, 'е').replace(/\s*\(.*?\)\s*/g, ' ').replace(/^\s*(г|гор|город)\.?\s+/, '')
    .replace(/[-\u2010\u2011\u2013\u2014]/g, ' ').replace(/\s+/g, ' ').trim();
  const составной = (slug) => { const p = slug.split('_'); for (let k = 1; k < p.length; k++) { const h = p.slice(0, k).join('_'); if (ПРИСТАВКА.has(h) || ГОРОД.has(h)) return true; } return false; };
  const ПО_ИМЕНИ = new Map();
  for (const [слаг, c] of ГОРОД) {
    const к = ключИмени(c.name), tz = поясОбласти(c.r);
    if (/ и /.test(c.name)) continue;                                      // «Москва и МО» — не город
    if (ПО_ИМЕНИ.has(к) && ПО_ИМЕНИ.get(к) !== tz) { ПО_ИМЕНИ.set(к, ''); continue; }   // одноимённые в разных поясах
    if (!составной(слаг) && !ПО_ИМЕНИ.has(к)) ПО_ИМЕНИ.set(к, tz);
  }
  for (const [слаг, c] of ГОРОД) {                                         // имя только с уточнением области — не однозначно
    const к = ключИмени(c.name);
    if (составной(слаг) && ПО_ИМЕНИ.has(к) && ПО_ИМЕНИ.get(к) !== поясОбласти(c.r)) ПО_ИМЕНИ.set(к, '');
  }
  const поясПоИмени = (name) => ПО_ИМЕНИ.get(ключИмени(name)) || '';

  return { поСлагу, поясПоИмени };
})();
if (typeof module !== 'undefined' && module.exports) module.exports = LC_CITY_SLUGS;
