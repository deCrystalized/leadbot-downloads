"""Conversation-qualified facts: asking a question does not establish its answer."""

import re
from typing import Any

# Unknown prerequisites keep a free chat out of automatic admission. An owned
# chat can ask the policy-selected clarification before gathering contacts.
ACCEPTANCE_CONDITIONS = {
    'router': ['internet'], 'cable-crimp': ['cable_type', 'cable_operation'],
    'pc-special-software': ['license'], 'pc-icloud': ['owner_access'],
    'phone-access': ['owner_access'], 'coffee': ['coffee_type'], 'oven': ['gas_type'],
    'oven-portable': ['gas_type', 'induction'], 'washer-connect': ['plumbing_ready'],
    'boiler-install': ['plumbing_ready'], 'oven-connect': ['electrics_ready'],
    'floor': ['floor_ready'], 'drying': ['drying_location'], 'printer-special': ['printer_pc'],
    'tv': ['tv_type', 'screen_damage'], 'tv-channels': ['antenna'], 'tv-setup': ['tv_type'],
    'light': ['ceiling'], 'mnc-connect': ['plumbing_ready', 'electrics_ready'],
    'pc-assembly': ['pc_parts'], 'hanging': ['wall'],
    'lock': ['lock_work'],
    'lighting-symptom': ['lighting_object'],
}


def acceptance_conditions(service, state):
    keys = list(dict.fromkeys(key for item in service.get('items', [])
                              for key in ACCEPTANCE_CONDITIONS.get(item['id'], [])))
    if any(item.get('wall_mount_only') for item in service.get('items', [])):
        keys.append('wall')
    if any('screen_damage' in item.get('questions', []) for item in service.get('items', [])):
        keys.append('screen_damage')
    if state['ceiling']['status'] == 'answered' and re.search(r'натяжн', state['ceiling']['value'], re.I):
        keys.append('support')
    if state['pc_parts']['status'] == 'answered' and re.search(r'\bнет\b|\bno\b', state['pc_parts']['value'], re.I):
        keys.append('pc_purchase')
    return list(dict.fromkeys(keys))

# key: (question, answer pattern, prompt pattern, binary, required output groups)
SPECS = {
    "leak_location": (
        "Что именно протекает?",
        r"(?:теч|протек|капает).{0,35}(?:труб|смесител|сифон|унитаз|бачок|шланг)|(?:труб|смесител|сифон|унитаз|бачок|шланг).{0,35}(?:теч|протек|капает)",
        r"что.{0,12}(?:потек|потёк|протек|протёк)|откуда.{0,15}теч",
        False,
        [["что", "откуда"], ["теч", "протек", "протёк", "потек", "потёк"]],
    ),
    "countertop_material": (
        "Из какого материала столешница?",
        r"столешниц\w*.{0,30}(?:л?дсп|мдф|мрамор|гранит|акрил|кварц|дерев|камень)|(?:л?дсп|мдф|мрамор|гранит|акрил|кварц|дерев|камень).{0,30}столешниц",
        r"(?:материал|из чего).{0,25}столешниц|столешниц.{0,25}(?:материал|из чего|л?дсп|мдф|мрамор|гранит|акрил|кварц|дерев|камень)",
        False,
        [["материал", "из чего"], ["столешниц"]],
    ),
    "client_name": (
        "Как к вам обращаться?",
        r"(?:меня зовут|мо[её] имя)\s+[а-яёa-z-]{2,40}|^\s*это\s+я\s+(?-i:[А-ЯЁ][а-яё-]{1,39})(?:\s+(?-i:[А-ЯЁ][а-яё-]{1,39})){0,2}[.!\s]*$",
        r"как.{0,12}обращ|как.{0,6}вас.{0,6}зовут|вас.{0,6}как.{0,6}зовут|ваше имя",
        False,
        [["обращ", "зовут", "имя"]],
    ),
    "visit_time": (
        "На какой день и время вам удобно?",
        r"(?:сегодня|завтра|послезавтра|\d{1,2}[.]\d{1,2}).{0,30}(?:в|к|после|с)\s*\d{1,2}(?::\d{2}|\s*час)",
        r"(?:день|дат).{0,20}(?:врем|час)|когда.{0,20}удоб",
        False,
        [["день", "дат"], ["врем", "час"]],
    ),
    "furniture_problem": (
        "Что именно нужно отремонтировать?",
        r"ножк|каркас|петл|направляющ|пружин|обивк|стекл|креплен|механизм|фасад|дверц|выкатн\w*\s+ящик|сломал.{0,15}(?:доск|рейк)|доск.{0,15}слом|(?:испорч|разбит|поврежд).{0,30}(?:дырк|отверсти)",
        r"что.{0,15}(?:отремонт|слом|полом|почин)",
        False,
        [["что"], ["ремонт", "слом", "полом", "почин"]],
    ),
    "lighting_object": (
        "Что именно моргает: люстра, светильник или освещение целиком?",
        r"люстр|светиль|\bбра\b|проводк|весь\s+свет|вс[её]\s+освещени|освещени\w*\s+целиком",
        r"что\s+именно\s+моргает|люстра.{0,40}освещение\s+целиком",
        False,
        [["что"], ["моргает"], ["люстра", "светильник", "освещение"]],
    ),
    "pc_purchase": (
        "Готовы приобрести комплектующие в день приезда?",
        r"готов.{0,20}купить.{0,20}(?:сегодня|тот же день)|куплю.{0,20}(?:сегодня|тот же день)",
        r"приобрест|готов.{0,20}купить",
        True,
        [["комплектующ", "купить", "приобрест"]],
    ),
    "decision_maker": (
        "Вы будете принимать решение по работам и оплате и будете на месте?",
        (
            r"я.{0,25}(?:оплачу|оплачиваю|принимаю решение).{0,60}буду.{0,15}на месте"
            r"|буду.{0,15}на месте.{0,60}я.{0,25}(?:оплачу|оплачиваю|принимаю решение)"
        ),
        r"принима[тюь]+.{0,15}решени|решени.{0,15}оплат",
        True,
        [["решени"], ["оплат", "месте"]],
    ),
    "place": (
        "Где будут проводиться работы: квартира, частный дом или организация?",
        r"квартир|\bкв\.?\s*\d{1,4}\b|частн.{0,8}дом|дом\s+частн|\bчд\b|офис|организац|помещен",
        r"где.{0,15}работ|квартира.{0,20}частный",
        False,
        [["где", "квартир", "дом"]],
    ),
    "problem": (
        "Что у вас случилось?",
        r"(?:печати|печатает)[^.!?\n]{0,45}накладыва\w*[^.!?\n]{0,25}(?:напечатан|строк|текст)|(?:не\s+(?:бер[её]т|забира\w*|пода[её]\w*|захватыва\w*)|перестал[аои]?\s+(?:брать|забирать|подавать|захватывать))\s+бумаг\w*|не\s+(?:включ|работ|гре|слив|холод|отжим|крут|печат|проп[еи]чат|набира|суш|подключ|заряж|лов|моет)|печата\w*.{0,25}пуст\w*\s+(?:лист|страниц)|пуст\w*\s+лист\w*.{0,15}(?:выкидыва|выда|выбрасыва)|перестал[аои]?\s+(?:нагревать|греть|охлаждать|мыть)\b|блокировк\w*\s+нету?\b|\bнету?\s+блокировк|нет\s+(?:картинки|изображения|сигнала)|ч[её]рн\w*\s+экран|экран\w*[^.!?\n]{0,20}ч[её]рн|слом|разбит|теч|шум|нуж[наноы]+.{0,35}(?:замен|установ|настро|собра|подключ)|почист|переустанов",
        r"что.{0,12}случил|какая.{0,15}проблем",
        False,
        [["случ", "проблем"]],
    ),
    "error_context": (
        "При каком действии появляется эта ошибка?",
        r"при\s+(?:вход|запуск|обнов|подключ|авторизац)|когда.{0,25}(?:вхожу|запускаю|подключаю|обновляю)|вхожу.{0,20}(?:аккаунт|профил)",
        r"при\s+каком\s+действ|когда.{0,25}появля.{0,15}ошиб",
        False,
        [["действ", "когда"], ["ошиб"]],
    ),
    "model": (
        "Марку и модель подскажите?",
        r"\b(?=[a-zа-я0-9-]*[a-zа-я])(?=[a-zа-я0-9-]*\d)[a-zа-я0-9-]{3,}\b",
        r"марк|модел",
        False,
        [["марк"], ["модел"]],
    ),
    "load": (
        "Загрузка сверху или сбоку?",
        r"вертикаль|горизонталь|сверх|сбок|фронталь",
        r"загруз|сверх|сбок|вертик|горизонт",
        False,
        [["загруз", "сверх", "сбок"]],
    ),
    "connection": (
        "Техника подключена к воде и электричеству?",
        r"подключен.{0,25}(?:вод|электр)|(?:вода|воде).{0,15}электр|электр.{0,15}вод",
        r"вод.{0,20}электр|электр.{0,20}вод",
        True,
        [["вод"], ["электр"]],
    ),
    "plumbing_ready": (
        "Подвод и отвод воды уже подготовлены?",
        r"подвод.{0,25}отвод|ввод.{0,15}вывод|сантехник.{0,15}готов",
        r"подвод|отвод|ввод|вывод|сантехник.{0,15}готов",
        True,
        [["подвод", "ввод", "сантехник"], ["отвод", "вывод", "готов"]],
    ),
    "electrics_ready": (
        "Электрика подготовлена к подключению?",
        r"электрик.{0,20}готов|розетк.{0,15}(?:есть|готов)",
        r"электрик.{0,20}готов|готов.{0,20}электрик",
        True,
        [["электр"], ["готов"]],
    ),
    "gas_type": (
        "Техника электрическая или с газовыми элементами?",
        r"электрическ|газов|без газа",
        r"газов|электрическ|без\s+газа",
        False,
        [["газ", "электр"]],
    ),
    "boiler_access": (
        "К бойлеру есть свободный доступ?",
        r"(?:бойлер|водонагрев).{0,30}доступ|доступ.{0,30}(?:бойлер|водонагрев)",
        r"доступ",
        True,
        [["доступ"]],
    ),
    "coffee_vending": (
        "Это торговый кофейный автомат с терминалом оплаты?",
        r"(?!)",
        r"торгов\w*.{0,35}автомат.{0,35}терминал|кофейн\w*.{0,35}автомат.{0,35}терминал",
        True,
        [["автомат"], ["терминал"], ["оплат"]],
    ),
    "coffee_type": (
        "Кофемашина рожковая или капсульная?",
        r"рожков|капсульн|автоматическ.*кофе",
        r"рожков|капсульн",
        False,
        [["рожков", "капсульн"]],
    ),
    "ceiling": (
        "Потолок натяжной или обычный?",
        r"натяжн|обычн\w*.{0,12}потол|потол\w*.{0,12}обычн",
        r"потол|натяжн",
        False,
        [["потол", "натяж"]],
    ),
    "support": (
        "Закладная под крепление есть?",
        r"закладн\w*.{0,20}(?:есть|нет|установ|готов)|(?:есть|нет).{0,20}закладн",
        r"закладн",
        True,
        [["закладн"]],
    ),
    "height": (
        "Какая высота установки?",
        r"высот\w*.{0,15}\d|\d+(?:[,.]\d+)?\s*(?:м\b|метр)",
        r"высот",
        False,
        [["высот"]],
    ),
    "instructions": (
        "Схема или инструкция сборки есть?",
        r"\bбез\s+(?:схем|инструкц)\w*|(?:схем|инструкц)\w*.{0,20}\b(?:есть|нету?|сохрани\w*|потер\w*)\b|\b(?:есть|нету?)\b.{0,20}(?:схем|инструкц)",
        r"схем|инструкц",
        True,
        [["схем", "инструкц"]],
    ),
    "materials": (
        "Материалы и комплектующие есть?",
        r"(?:материал|комплектующ|расходник).{0,25}(?:есть|нет|куплен|налич)|(?:есть|нет|куплен|налич).{0,25}(?:материал|комплектующ|расходник)|(?:комод|шкаф|стол|тумб|кроват|мебел)\w*.{0,20}(?:приш[её]л|куплен|доставлен)\w*|(?:приш[её]л|куплен|доставлен)\w*.{0,20}(?:комод|шкаф|стол|тумб|кроват|мебел)",
        r"материал|комплектующ|вс[её].{0,10}в\s+наличии|все\s+детали.{0,25}креп[её]ж",
        True,
        [["материал", "комплектующ"]],
    ),
    "volume": (
        "Какой объём работ нужно выполнить?",
        r"(?:одн|две|два|три|четыре|\d+).{0,12}(?:розет|выключ|полк|светиль|карниз|смесител|люстр|двер|шкаф)|об[ъь]ем.{0,20}\d|(?:собрать|сборка|установить|сделать)\s+(?:один\s+)?(?:комод|шкаф|стол|тумбу|кровать)\b",
        r"об[ъь]ем|количеств|сколько",
        False,
        [["объём", "объем", "количеств", "сколько"]],
    ),
    "room": (
        "Работа нужна на кухне или в ванной?",
        r"на кухн|в ванн|для кухн|для ванн",
        r"кухн|ванн",
        False,
        [["кухн", "ванн"]],
    ),
    "wall": (
        "Из какого материала стены?",
        r"бетон|кирпич|пеноблок|монолит|гипсокартон|деревянн.*стен",
        r"стен|бетон|кирпич",
        False,
        [["стен", "бетон", "кирпич"]],
    ),
    "internet": (
        "Интернет уже проведён?",
        r"интернет.{0,20}(?:проведен|проведён|есть|подключен)|(?:проведен|проведён|есть).{0,20}интернет",
        r"интернет.{0,25}(?:проведен|проведён|првоеден|есть|подключ)",
        True,
        [["интернет"]],
    ),
    "cable_type": (
        "Это витая пара/патч-корд или оптоволоконный кабель?",
        r"вит(?:ая|ую|ой)\s+пар|патч.?корд|rj.?45|оптоволок|оптическ\w*\s+кабел",
        r"тип\s+кабел|какой\s+кабел|витая.{0,30}оптоволок",
        False,
        [["кабел", "витая", "патч"], ["оптоволок"]],
    ),
    "cable_operation": (
        "Нужно заменить коннектор на конце кабеля или соединить повреждённый провод?",
        r"обжат|обжать|обжим|коннектор|соединить|срастить|нарастить",
        r"коннектор.{0,45}(?:соединить|поврежден)|что.{0,20}(?:кабел|провод)",
        False,
        [["коннектор"], ["кабел", "провод"]],
    ),
    "tv_type": (
        "Телевизор ЖК, плазменный или кинескопный?",
        r"\bжк\b|\bled\b|oled|qled|плазмен|кинескоп|проекцион",
        r"\bтип\w*.{0,20}(?:тв|телевиз)|\bжк\b|плазмен|кинескоп",
        False,
        [["жк", "плазм", "тип"]],
    ),
    "screen_damage": (
        "Экран повреждали или на него попадала влага?",
        r"не роня|не бил|не залив|не поврежд|не попадала|не было.{0,20}(?:поврежд|влаг)|упал|удар|залил|попала вода|попадала влаг",
        r"поврежд|роня|удар|влаг|залив",
        True,
        [["поврежд", "роня", "удар"], ["влаг", "вод", "залив"]],
    ),
    "antenna": (
        "Антенна комнатная, наружная или кабельное ТВ?",
        r"комнатн.{0,12}антенн|наружн.{0,12}антенн|спутников|кабельн.{0,12}(?:тв|телевид)|антенн.{0,12}(?:комнатн|наружн)",
        r"антенн|кабельное",
        False,
        [["антенн"], ["комнат", "наруж", "кабель"]],
    ),
    "keep_data": (
        "Данные на устройстве нужно сохранить?",
        r"данн.{0,25}(?:сохран|не нужны|удал)|сохран.{0,25}данн",
        r"данн.{0,20}сохран|сохран.{0,20}данн",
        True,
        [["данн"], ["сохран"]],
    ),
    "license": (
        "Лицензионный ключ программы у вас есть?",
        r"лицензионн.{0,15}(?:ключ|есть|нет)|(?:есть|нет).{0,15}лиценз",
        r"лиценз|лицензионн.*ключ",
        True,
        [["лиценз", "ключ"]],
    ),
    "office_symptom": (
        "Что происходит при запуске программы: появляется ошибка или она не открывается?",
        r"не\s+(?:открыва|запуска|сохраня)|ошиб|завис|вылета|активаци|\bперестал[аои]?\s+(?:открываться|запускаться|сохранять)\b",
        r"что\s+происходит.{0,40}(?:программ|word|excel)|(?:какая|какую).{0,20}ошибк",
        False,
        [["программ", "word", "excel"], ["ошиб", "запуск", "открыва"]],
    ),
    "software_use": (
        "Программу нужно установить или настроить?",
        r"установ|настро|обучи",
        r"установ.{0,20}настро",
        False,
        [["установ", "настро"]],
    ),
    "pc_parts": (
        "Все комплектующие для сборки уже есть?",
        r"комплектующ.{0,25}(?:есть|нет|куплен|налич)|(?:есть|нет).{0,25}комплектующ",
        r"комплектующ",
        True,
        [["комплектующ"]],
    ),
    "has_pc": (
        "Компьютер или ноутбук у вас есть?",
        r"компьютер|ноутбук|\bпк\b|моноблок",
        r"компьютер|ноутбук|\bпк\b",
        True,
        [["компьютер", "ноутбук", "пк"]],
    ),
    "owner_access": (
        "Доступ к привязанной почте или телефону сохранился?",
        r"доступ.{0,30}(?:почт|телефон).{0,20}(?:есть|нет|сохрани)|(?:почт|телефон).{0,20}(?:помню|сохрани|есть|нет)",
        r"доступ|привязанн|сохранил",
        True,
        [["доступ", "почт", "телефон"]],
    ),
    "printer_service": (
        "Принтер нужно настроить или отремонтировать?",
        r"настро|ремонт|прошив",
        r"настро.{0,20}ремонт",
        False,
        [["настро", "ремонт"]],
    ),
    "printer_pc": (
        "Настройка будет через компьютер?",
        r"через компьютер|через пк|к компьютеру|к ноутбуку",
        r"через.{0,15}(?:компьютер|пк)",
        True,
        [["компьютер", "пк"]],
    ),
    "printer_connection": (
        "Принтер подключаем к компьютеру или телефону?",
        r"к компьютеру|к ноутбуку|к телефону|к планшету|без компьютера|без пк",
        r"принтер.{0,30}(?:компьютер|телефон)|с\s+компьютера.{0,25}телефона.{0,20}печатаете",
        False,
        [["компьютер", "телефон"]],
    ),
    "data_device": (
        "С какого устройства нужно восстановить данные?",
        r"диск|hdd|ssd|флешк|карт.{0,8}памят|телефон|планшет|компьютер|ноутбук|icloud|whatsapp|telegram",
        r"с какого.{0,15}(?:устройств|носител)",
        False,
        [["устройств", "носител"]],
    ),
    "data_condition": (
        "Само устройство исправно, включается?",
        r"исправ|включается|не включается|сгор|поврежд|разбит|не загружа",
        r"исправ|включается|поврежд",
        True,
        [["исправ", "включ"]],
    ),
    "console_service": (
        "Приставку нужно почистить, настроить или отремонтировать?",
        r"чист|термопаст|настро|ремонт|прошив",
        r"почист.{0,30}настро",
        False,
        [["чист", "настро", "ремонт"]],
    ),
    "induction": (
        "Плита индукционная?",
        r"индукцион|не индукцион|электрическ",
        r"индукцион",
        True,
        [["индукцион"]],
    ),
    "water_shutoff": (
        "Вода перекрывается в квартире или в подвале?",
        r"перекры.{0,20}(?:квартир|подвал)|(?:квартир|подвал).{0,20}перекры",
        r"перекры|подвал",
        False,
        [["перекры", "подвал"]],
    ),
    "toilet_type": (
        "Унитаз обычный или с инсталляцией?",
        r"обычн.{0,12}унитаз|унитаз.{0,12}обычн|инсталляц|инсталирован|инсталлирован",
        r"обычн.{0,15}инстал|унитаз.{0,15}обычн",
        False,
        [["обычн", "инстал"]],
    ),
    "pipe_material": (
        "Трубы пластиковые, металлические или металлопластиковые?",
        r"пластиков|полипропилен|пвх|металл|метапол|чугун|медн|медь|сталь|латун|алюмин",
        r"труб.{0,20}(?:материал|пластик)|материал.{0,20}труб",
        False,
        [["труб"], ["пластик", "металл", "материал"]],
    ),
    "pipe_replacement": (
        "Планируется замена на пластиковые трубы?",
        r"замен.{0,20}пластик|пластик.{0,20}замен",
        r"замен.{0,20}пластик",
        True,
        [["замен"], ["пластик"]],
    ),
    "switchboard": (
        "Где расположен щиток или автомат?",
        r"щиток.{0,20}(?:квартир|подъезд|коридор)|автомат.{0,20}(?:квартир|подъезд|коридор)",
        r"где.{0,20}(?:щиток|автомат)",
        False,
        [["щиток", "автомат"]],
    ),
    "floor_ready": (
        "Пол уже подготовлен к укладке?",
        r"пол.{0,20}(?:готов|ровн|выравнив)|место.{0,15}расчищ",
        r"пол.{0,20}(?:готов|подготов)|выравнив",
        True,
        [["пол"], ["готов", "выравнив"]],
    ),
    "drying_location": (
        "Сушилка будет внутри помещения или снаружи?",
        r"внутри|снаружи|наружн|на балконе",
        r"внутри.{0,20}снаружи|где.{0,20}сушил",
        False,
        [["внутри", "снаружи", "помещ"]],
    ),
    "lock_work": (
        "Нужен ремонт замка или замена?",
        r"(?!)",  # Choice is bound to the named object or an actual staff question below.
        r"(?:замок|замк|ручк).{0,70}(?:ремонт|замен|установ)|(?:ремонт|замен|установ).{0,70}(?:замок|замк|ручк)",
        False,
        [["ремонт"], ["замен"]],
    ),
    "door_type": (
        "Дверь входная или межкомнатная?",
        r"входн|межкомнатн",
        r"входн|межкомнатн",
        False,
        [["входн", "межкомнатн"]],
    ),
    "door_material": (
        "Дверь деревянная или металлическая?",
        r"деревянн|металлическ",
        r"деревянн|металлическ",
        False,
        [["дерев", "металл"]],
    ),
    "outdoor_access": (
        "На каком этаже и где расположен наружный блок?",
        r"\d.{0,5}этаж|наружн.{0,20}блок.{0,25}(?:балкон|окн)",
        r"этаж|наружн.{0,20}блок",
        False,
        [["этаж", "блок"]],
    ),
    "area": (
        "Какая площадь помещения?",
        r"\d.{0,10}(?:кв\.?\s*м|м2|метров)",
        r"площад|квадратур",
        False,
        [["площад", "квадрат"]],
    ),
    "pest_type": (
        "Каких насекомых нужно вывести?",
        r"таракан|клоп|муравь|блох",
        r"каких.{0,15}насеком",
        False,
        [["насеком", "таракан", "клоп"]],
    ),
}
YES = re.compile(
    r"^\s*(?:да(?:[,!\s]+есть)?|есть|готов[аоы]?|верно|конечно|ага|подключен[аоы]?)[.!\s]*$",
    re.IGNORECASE,
)
NO = re.compile(
    r"^\s*(?:нет(?:[,!\s]+нету)?|неа|не готов[аоы]?|не подключен[аоы]?|нету)[.!\s]*$", re.IGNORECASE
)
UNKNOWN = re.compile(
    r"не\s*знаю|не помню|не могу (?:сказать|посмотр)|без понятия|не разбираюсь|не (?:мерил[аи]?|замерял[аи]?|измерял[аи]?)",
    re.IGNORECASE,
)


def inventory_answer(text):
    """Short inventory wording only; never alter the general yes/no grammar."""
    text = re.sub(r'^\s*(?:здравствуйте|добрый\s+(?:день|вечер)|доброе\s+утро)[,!\.\s]*',
                  '', text, flags=re.I).strip()
    negative = re.fullmatch(r'(?:(?:пока|ещ[её])\s+)?(?:нет(?:[,\s]+(?:ни\s*чего|не\s+чего|ещ[её]))?'
                            r'|(?:ни\s*чего|не\s+чего)\s+(?:пока\s+)?нет)[.!\s]*', text, re.I)
    if '?' in text:
        return None
    positive = re.fullmatch(r'(?:да[,!\s]+)?вс[её]\s+(?:уже\s+)?(?:есть|в\s+наличии|куплено|приобретено)[.!\s]*', text, re.I)
    return 'yes' if YES.fullmatch(text) or positive else 'no' if NO.fullmatch(text) or negative else None


def material_statements(text):
    """Mask questions/contractor inventory, retaining offsets and client assertions.

    Separate clauses matter: «У меня материалов нет, что делать?» states a lack,
    whereas «У вас материалов нет?» asks about the contractor and states nothing.
    """
    result = list(text)
    for sentence in re.finditer(r'[^.!?;\n]+[.!?;\n]?', text):
        whole = sentence.group(0)
        tag_question = re.search(r',\s*(?:верно|правильно|да|нет)\s*\?\s*$', whole, re.I)
        for clause in re.finditer(r'[^,]+(?:,|$)', whole):
            value = clause.group(0)
            question = ('?' in value or re.search(r'\b(?:есть|нет)\s+ли\b', value, re.I))
            contractor = re.search(r'\bу\s+(?:вас|мастера)\b|\bвы\s+(?:привез|приобрет|куп|предостав)', value, re.I)
            if tag_question or question or contractor:
                start = sentence.start() + clause.start()
                result[start:sentence.start() + clause.end()] = ' ' * len(value)
    return ''.join(result)


def named_hose_material_match(text):
    """Only the stated hose/liner, never all fittings or their compatibility."""
    masked = re.sub(
        r'\b(?:другой\s+)?(?:мастер|специалист|сосед|продавец|инструкци)\w*[^.!?\n«“"]{0,35}'
        r'\b(?:спросил|сказал|написал|написан|ответил)\w*\s*[:,-]?\s*(?:«[^»]*»|“[^”]*”|"[^"\n]*")',
        lambda match: ' ' * len(match[0]), text, flags=re.I)
    masked = material_statements(masked)
    for match in re.finditer(
            r'\b(?:шланг\w*|шланчик\w*|подводк\w*)\s+'
            r'(?:(?:уже|новый|нужный|у\s+меня|у\s+нас)\s+){0,2}'
            r'(?:нету?|не\s+(?:имеется|имеются|куплен\w*)|имеется|имеются|есть|в\s+наличии|куплен\w*)\b',
            masked, re.I):
        prefix = re.split(r'[.!?;\n]', masked[:match.start()])[-1]
        tail = re.split(r'[.!?;\n]', masked[match.end():], maxsplit=1)[0]
        if re.search(r'\b(?:если|вдруг|предположим|допустим)\b', prefix, re.I):
            continue
        if (re.search(r'\b(?:сосед|мастер|продавец|инструкци)\w*', prefix, re.I)
                and not re.search(r'\bу\s+(?:меня|нас)\b', prefix, re.I)):
            continue
        if re.search(r'\bу\s+(?:сосед|мастер|продавц)\w*', tail, re.I):
            continue
        return match
    return None


def named_client_stock(message):
    """A named installed supply is not a statement that the whole kit exists."""
    if (not _answer_client(message) or message.get('role') in ('system', 'assistant')
            or message.get('speaker_role', 'client') != 'client'):
        return None
    body = message.get('body', '')
    literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', body)
    uncertain_prefix = bool(re.match(r'^\s*не\s+(?:уверен\w*|знаю)\s*,', literal, re.I))
    for clause in re.findall(r'[^.!?;,\n]+[.!?;,]?', literal):
        # A price question in the same turn is not future or uncertain stock.
        clause = re.split(r'\b(?:и|а)\s+(?:сколько|что\s+по\s+цене)\b', clause, maxsplit=1, flags=re.I)[0]
        if (re.search(r'\?|\b(?:если|вдруг|возможно|наверн\w*|кажется|вроде|будут|будет|'
                      r'сказал\w*|говорит|написал\w*|по\s+словам)\b|'
                      r'\b(?:у\s+(?:мастер\w*|сосед\w*|продавц\w*|вас)|для\s+друг\w*\s+заказ\w*)', clause, re.I)):
            continue
        # "All details" is a statement about those details only. It does
        # not verify fasteners, compatibility or a complete assembly kit.
        details = re.search(r'\b(?:все\s+(?:нужные\s+)?детали|детали\s+все)\s+'
                            r'(?:уже\s+)?(?:есть|на\s+месте|в\s+наличии)\b', clause, re.I)
        if (details and not re.search(r'\bне\s+все\b|\bсосед\w*|\bмастер\w*|'
                                      r'\b(?:для|от)\s+(?:друг\w*|стар\w*)\s+(?:шкаф|комод|мебел)\w*', clause, re.I)):
            return dict(status='answered', value=details[0], quote=body[:300],
                        message_id=message.get('id', ''), evidence_source='client_message',
                        availability_scope='client_named_item_only', availability_subject='детали')
        named = r'\bплинтус\w*'
        if re.search(named, clause, re.I) and (uncertain_prefix or re.search(r'\b(?:не\s+уверен\w*|не\s+знаю)\b', clause, re.I)):
            return dict(status='uncertain', value='', quote=body[:300],
                        message_id=message.get('id', ''), evidence_source='client_message',
                        availability_scope='client_named_item_only', availability_subject='плинтус')
        if re.search(named + r'\s+(?:пока\s+|ещ[её]\s+)?нет\b|\bнет\s+' + named, clause, re.I):
            return dict(status='answered', value=clause.strip(), quote=body[:300],
                        message_id=message.get('id', ''), evidence_source='client_message',
                        availability_scope='client_named_item_only', availability_subject='плинтус')
        stock = r'(?:есть|куплен\w*|приобретен\w*|приобретён\w*|в\s+наличии)'
        match = re.search(named + r'\s+(?:(?:уже|у\s+меня|у\s+нас)\s+)?' + stock + r'\b|'
                          r'\b' + stock + r'\s+(?:у\s+меня\s+)?' + named, clause, re.I)
        if match:
            return dict(status='answered', value=match[0], quote=body[:300],
                        message_id=message.get('id', ''), evidence_source='client_message',
                        availability_scope='client_named_item_only', availability_subject='плинтус')
    return None


def coordinated_client_stock(message):
    """Retain a literal named purchase list, never completeness or our stock."""
    if (not _answer_client(message) or message.get('role') in ('system', 'assistant')
            or message.get('speaker_role', 'client') != 'client'
            or (message.get('voice_transcript_status')
                and message['voice_transcript_status'] not in ('ready', 'done', 'completed'))):
        return None
    body = message.get('body', '')
    literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', lambda m: ' ' * len(m[0]), body)
    item = (r'(?:смесител\w*|кран\w*|карниз\w*|гардин\w*|полк\w*|турник\w*|кронштейн\w*|'
            r'люстр\w*|светиль\w*|замок|замк\w*|ручк\w*|креп[её]ж\w*|креплен\w*|'
            r'саморез\w*|шуруп\w*|материал\w*|комплектующ\w*|панел[ьи]|дверц\w*|пакетик\s+креп[её]ж\w*)')
    named = r'(?P<items>\b' + item + r'(?:\s*,\s*' + item + r')*\s*,?\s+и\s+' + item + r')'
    present = r'(?:куплены|приобретены|есть|в\s+наличии)'
    patterns = (named + r'\s+(?:уже\s+)?' + present + r'\b',
                r'\b' + present + r'\s+(?:уже\s+)?' + named,
                named + r'\s+у\s+(?:меня|нас)\s+(?:уже\s+)?есть\b')
    for clause in re.findall(r'[^.!?;\n]+[.!?;]?', literal):
        if re.search(r'\?|\b(?:не|нет|если|вдруг|возможно|кажется|наверн\w*|будут|будет|'
                     r'сосед\w*|мастер\w*|продавц\w*|сказал\w*|написал\w*|говорит)\b|'
                     r'\bдля\s+друг\w*\s+(?:заказ|работ|клиент)\w*|'
                     r'\bу\s+вас\b', clause, re.I):
            continue
        match = next((m for pattern in patterns if (m := re.search(pattern, clause, re.I))), None)
        if match:
            return dict(status='answered', value=match[0], quote=body[:300],
                        message_id=message.get('id', ''), evidence_source='client_message',
                        availability_scope='client_named_item_only', availability_subject=match['items'])
    return None


def siphon_supply_statement(message):
    """Keep a direct client report separate from physical verification."""
    if (not _answer_client(message) or message.get('role') in ('system', 'assistant')
            or message.get('speaker_role', 'client') != 'client'
            or (message.get('voice_transcript_status')
                and message['voice_transcript_status'] not in ('ready', 'done', 'completed'))):
        return None
    body = message.get('body', '')
    literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', lambda m: ' ' * len(m[0]), body)
    for clause in re.findall(r'[^.!?;\n]+[.!?;]?', literal):
        if re.search(r'\?|\b(?:если|вдруг|возможно|кажется|наверн\w*|может|допустим|предположим|'
                     r'мастер\w*|сосед\w*|продавц\w*|сказал\w*|говорит|написал\w*|'
                     r'раньше|вчера)\b|\bу\s+вас\b|\bдля\s+друг\w*\s+заказ\w*', clause, re.I):
            continue
        if re.fullmatch(r'\s*сифон\s+покупать\s+не\s+буду[.!\s]*', clause, re.I):
            return dict(purchase_plan_cancelled=True)
        if re.search(r'\b(?:не|нет)\b', clause, re.I):
            continue
        present = re.search(r'\bсифон\s+(?:уже\s+)?куплен\b', clause, re.I)
        if present:
            return dict(status='answered', value=present[0], quote=body[:300],
                        message_id=message.get('id', ''), evidence_source='client_message',
                        availability_scope='client_named_item_only', availability_subject='сифон',
                        availability_status='client_reported_present')
        match = re.search(r'\bсифон\s+(?:я\s+)?куплю(?:\s+сам[аои]?)?\b|'
                          r'\b(?:я\s+)?(?:сам[аои]?\s+)?куплю\s+(?:сам[аои]?\s+)?сифон\b', clause, re.I)
        if match:
            return dict(status='answered', value='План покупки: сифон; наличие не подтверждено',
                        quote=body[:300], message_id=message.get('id', ''), evidence_source='client_message',
                        availability_scope='client_named_item_purchase_plan', availability_subject='сифон',
                        availability_status='planned_purchase', present_stock_confirmed=False,
                        completeness_confirmed=False)
    return None


def basin_supply_statement(message):
    """Keep the customer's basin report scoped to that item."""
    if (not _answer_client(message) or message.get('role') in ('system', 'assistant')
            or message.get('speaker_role', 'client') != 'client'
            or (message.get('voice_transcript_status')
                and message['voice_transcript_status'] not in ('ready', 'done', 'completed'))):
        return None
    body = message.get('body', '')
    literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', body)
    basin_work = False
    stock = None
    fittings = ''
    for sentence in re.findall(r'[^.!?;\n]+[.!?;]?', literal):
        if re.search(r'\b(?:если|вдруг|возможно|кажется|вроде|наверн\w*|'
                     r'сказал\w*|написал\w*|по\s+словам|раньше|вчера)\b|'
                     r'\bу\s+(?:вас|мастер\w*|сосед\w*|продавц\w*)\b|'
                     r'\bдля\s+друг\w*\s+заказ\w*', sentence, re.I):
            basin_work = False
            continue
        text = sentence.strip().rstrip('.!;')
        if re.fullmatch(r'не\s+(?:знаю|уверен\w*)[\s,]+(?:есть\s+ли|куплена\s+ли)\s+'
                        r'(?:новая\s+)?раковина', text, re.I):
            stock = ('uncertain', text, 'client_reported_uncertain')
        for clause in material_statements(sentence).split(','):
            clause = clause.strip().rstrip('.!;')
            if re.fullmatch(r'(?:ново[йя]\s+)?раковин[аы]\s+(?:(?:пока|ещ[её])\s+)?'
                            r'(?:нет|не\s+куплена)', clause, re.I):
                stock = ('answered', clause, 'client_reported_absent')
            present = r'\s+(?:(?:у\s+меня|у\s+нас)\s+)?(?:уже\s+)?(?:дома|есть|в\s+наличии|куплена)'
            if (re.fullmatch(r'(?:новая\s+)?раковина' + present, clause, re.I)
                    or basin_work and re.fullmatch(r'новая' + present, clause, re.I)):
                stock = ('answered', clause if re.search(r'раковина', clause, re.I)
                         else re.sub(r'^новая', 'Новая раковина', clause, flags=re.I), 'client_reported_present')
            if re.fullmatch(r'(?:но\s+)?креп[её]ж\s+(?:(?:пока|ещ[её])\s+)?не\s+провер[ия]л[аи]?', clause, re.I):
                fittings = clause
        basin_work = bool(
            re.search(r'\b(?:заменить|поменять)\s+(?:(?:одну|старую)\s+){0,2}раковину\b', text, re.I)
            and not re.search(r'\b(?:не|ни|смесител\w*|сифон\w*|кран\w*|унитаз\w*|мойк\w*|ванну)\b|\?', sentence, re.I))
    if stock is None:
        return None
    status, value, availability = stock
    if fittings and availability == 'client_reported_present':
        value += '; ' + fittings
    return dict(status=status, value=value, quote=body[:300], message_id=message.get('id', ''),
                evidence_source='client_message', availability_scope='client_named_item_only',
                availability_subject='раковина', availability_status=availability, completeness_confirmed=False)


def named_hose_work_match(text):
    """Keep a specified hose operation instead of asking its volume again."""
    masked = re.sub(
        r'\b(?:другой\s+)?(?:мастер|специалист|сосед|продавец)\w*[^.!?\n«“"]{0,35}'
        r'\b(?:спросил|сказал|написал|ответил)\w*\s*[:,-]?\s*(?:«[^»]*»|“[^”]*”|"[^"\n]*")',
        lambda match: ' ' * len(match[0]), text, flags=re.I)
    operation = r'\b(?:заменить|поменять|сменить)\s+'
    item = r'(?:шланг|шланчик)'
    pattern = (operation + r'(?:(?:один|старый|новый|гибкий|мой)\s+){0,2}' + item + r'\b|'
               + operation + r'(?:два|три|четыре|пять|[1-9]\d{0,2})\s+' + item + r'(?:а|и|ов)\b|'
               r'\bзамена\s+(?:одного\s+)?шланга\b')
    for match in re.finditer(pattern, masked, re.I):
        prefix = re.split(r'[.!?;\n]', masked[:match.start()])[-1]
        tail = masked[match.end():]
        if (re.search(r'\b(?:если|вдруг|предположим|допустим)\b', prefix, re.I)
                or re.search(r'\bне(?:\s+(?:нужно|надо|хочу|требуется))?\s*$', prefix, re.I)
                or re.match(r'\s+не\s+(?:нужно|надо|требуется|будем)\b', tail, re.I)):
            continue
        if (re.search(r'\b(?:мастер|сосед|продавец)\w*', prefix, re.I)
                and not re.search(r'\b(?:хочу|прошу)\b', prefix, re.I)):
            continue
        return match
    return None


def forget_inventory_question(row):
    for field in ('question_message_id', 'question_quote', 'check_intent_message_id',
                  'availability_scope', 'availability_subject', 'availability_status',
                  'present_stock_confirmed', 'completeness_confirmed'):
        row.pop(field, None)


def tv_mount_brackets(messages):
    """Current client report about brackets, with fastener readiness left open."""
    from assistant_catalog import choose

    if not any(re.search(r'кронштейн', message.get('body', ''), re.I) for message in messages):
        return None
    evidence = None
    context = []
    for message in messages:
        if (not _answer_client(message) or message.get('role') in ('system', 'assistant')
                or message.get('speaker_role', 'client') != 'client'
                or message.get('voice_transcript_status') in ('pending', 'queued', 'processing', 'transcribing')
                or str(message.get('delivery_status') or message.get('delivery') or '').lower() == 'processing'):
            continue
        body = message.get('body', '')
        literal = re.sub(r"""«[^»]*»|“[^”]*”|"[^"\n]*"|'[^'\n]*'""", ' ', body)
        if re.search(r'\bнов(?:ая\s+заявка|ый\s+заказ|ое\s+обращение)\b', literal, re.I):
            evidence = None
            context = []
        context.append(literal)
        for sentence in re.split(r'[.!;\n]+', material_statements(literal)):
            if re.search(r'\b(?:если|вдруг|раньше|вчера|сосед\w*|мастер\w*|продав\w*|'
                         r'сказал\w*|говорит|написал\w*)\b', sentence, re.I):
                continue
            for clause in sentence.split(','):
                part = clause.strip()
                if re.fullmatch(
                        r'(?:(?:мы|я)\s+)?(?:(?:оба\s+)?кронштейн\w*\s+(?:уже\s+)?'
                        r'(?:купил[аи]?|куплены?|приобретены?|есть|в\s+наличии|на\s+месте)|'
                        r'(?:уже\s+)?купил[аи]?\s+(?:оба\s+)?кронштейн\w*)'
                        r'(?:\s+для\s+(?:этих\s+)?телевизор\w*)?', part, re.I):
                    evidence = dict(present=True, message_id=message.get('id', ''), quote=part)
                elif re.search(r'кронштейн', part, re.I) and re.search(
                        r'\b(?:не\s+куп\w*|нету?|вернул\w*|купим|куплю|не\s+уверен\w*|не\s+знаю)\b',
                        part, re.I) and not re.search(r'\b(?:для|от)\s+(?:друг\w*|стар\w*)\b', part, re.I):
                    evidence = dict(present=False, message_id=message.get('id', ''), quote=part)
    service = choose('\n'.join(context), {'direction': 'mnc'})
    if service['status'] == 'supported' and {item['id'] for item in service['items']} == {'tv-mount'}:
        return evidence or dict(present=False)
    return None


def tv_fastener_question(reply):
    """One availability question about suitable fasteners for this TV mount."""
    questions = re.findall(r'[^.!?;\n]+\?', reply)
    if len(questions) != 1:
        return False
    question = questions[0]
    return (bool(re.search(r'креп[её]ж', question, re.I) and re.search(r'\bподходящ\w*', question, re.I)
                 and re.search(r'навес|телевизор', question, re.I)
                 and re.search(r'\b(?:есть|купил[аи]?|куплен\w*)\b|в\s+наличии', question, re.I))
            and not re.search(r'кронштейн|материал|комплектующ|[«»“”"]|\b(?:не|или)\b|'
                              r'\bу\b(?!\s+вас\b)\s+|\b(?:наш\w*|мастер\w*|сосед\w*|продав\w*|магазин\w*|склад\w*)\b|'
                              r'\bдля\s+друг\w*',
                              question, re.I))


def tv_mount_client_stock(messages, index):
    """Client reports both the brackets and all fasteners for this TV job."""
    import contact_facts
    message = messages[index]
    if (not _answer_client(message) or message.get('role') in ('system', 'assistant')
            or message.get('speaker_role', 'client') != 'client'
            or str(message.get('delivery_status') or message.get('delivery') or '').lower() == 'processing'
            or (message.get('voice_transcript_status')
                and message['voice_transcript_status'] not in ('ready', 'done', 'completed'))
            or not contact_facts.tv_mount_work_volume(messages[:index + 1])):
        return None
    body = message.get('body', '')
    literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', body)
    bracket = tv_mount_brackets(messages[:index + 1])
    if bracket and bracket['present']:
        # Read the named suitable parts in their own assertion. A following
        # price question does not revoke this client-reported availability.
        for clause in re.split(r'(?<=[.!?;])|\n', literal):
            named = re.fullmatch(
                r'\s*подходящие\s+(?:для\s+(?:(?:кирпичн|бетонн|деревянн|гипсокартонн)\w*\s+)?стен\w*\s+)?'
                r'дюбели\s+и\s+(?:винты|саморезы|шурупы)\s+(?:в\s+(?:коробке|комплекте)\s+)?'
                r'(?:уже\s+)?(?:есть|куплены|в\s+наличии)[.!\s]*', clause, re.I)
            if named:
                return dict(status='answered', value=clause.strip(), message_id=message.get('id', ''),
                            quote=clause.strip()[:300], evidence_source='client_message',
                            availability_scope='client_reported_hanging_parts_only',
                            availability_subject='подходящий крепёж для навеса телевизоров')
    if re.search(r'\?|\b(?:не|нет|если|вдруг|возможно|вроде|кажется|наверн\w*|будет|будут|'
                 r'купим|куплю|раньше|сосед\w*|мастер\w*|продавц\w*|говорит|сообщил\w*|'
                 r'по\s+словам|сказал\w*|написал\w*)\b', literal, re.I):
        return None
    fasteners = re.search(r'\bвесь\s+креп[её]ж\s+(?:уже\s+)?(?:куплен|приобрет[её]н|есть|в\s+наличии)\b', literal, re.I)
    brackets = re.search(r'\bкронштейн\w*\s+(?:и\s+телевизор\w*\s+)?(?:уже\s+)?'
                         r'(?:на\s+месте|куплены|приобретены|есть|в\s+наличии)\b', literal, re.I)
    if not fasteners or not brackets:
        return None
    return dict(status='answered', value=fasteners[0] + '; ' + brackets[0],
                message_id=message.get('id', ''), quote=body[:500], evidence_source='client_message',
                availability_scope='client_reported_hanging_parts_only',
                availability_subject='кронштейны и крепёж для навеса телевизоров')


def client_inventory_question(message):
    """A delivered question about client inventory, not material or a disclosure."""
    if (message.get('direction') != 'out' or message.get('role') == 'system'
            or message.get('sender_type', 'operator') not in ('operator','employee','human','assistant','bot','')
            or message.get('out_pending')
            or message.get('delivery', message.get('delivery_status','delivered')) in
            ('pending','queued','sending','failed','error','cancelled','canceled')):
        return False
    prompt = message.get('body','')
    if tv_fastener_question(prompt):
        return True
    if (re.search(r'[«»“”"]|стен|столешниц|\bу\s+(?:нас|меня|мастера)\b|\bнаш\w*|'
                  r'\b(?:клиент\w*|сосед\w*|мастер\w*)\s+(?:сказал\w*|спросил\w*|написал\w*)',prompt,re.I)
            or not re.search(r'материал|комплектующ|детал|креп[её]ж|креплен|фурнитур',prompt,re.I)):
        return False
    # A disclosure in one sentence cannot borrow the question mark of
    # "Вас устраивает стоимость?" in another sentence of the same message.
    return any(re.search(r'материал|комплектующ|детал|креп[её]ж|креплен|фурнитур', clause, re.I)
               and re.search(r'[?]|\b(?:подскажите|уточните|проверьте|скажите|какие|каких|чего|сколько)\b|'
                             r'\b(?:есть|имеются|куплен\w*|купили)\b|в\s+наличии', clause, re.I)
               for clause in re.findall(r'[^.!?;\n]+[.!?;\n]?', prompt))


def singular_hanging_work(message):
    """A current request for one named fixture, not a width or a whole job."""
    if (not _answer_client(message) or message.get('role') in ('system', 'assistant')
            or message.get('speaker_role', 'client') != 'client'
            or (message.get('voice_transcript_status')
                and message['voice_transcript_status'] not in ('ready', 'done', 'completed'))):
        return None
    literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', message.get('body', ''))
    from assistant_catalog import choose
    scope = choose(literal, {'direction': 'mnc'})
    if scope['status'] != 'supported' or {item['family'] for item in scope['items']} != {'hanging'}:
        return None
    for sentence in re.findall(r'[^.!?;\n]+[.!?;]?', literal):
        if re.search(r'\b(?:не|нет|если|вдруг|раньше|вчера|уже|несколько|еще|ещё|также|'
                     r'сказал\w*|говорит|написал\w*|сосед\w*|мастер\w*)\b', sentence, re.I):
            continue
        match = re.search(r'^\s*(?:(?:нужно|надо|хочу|прошу|можете|можно)\s+)?'
                          r'(?:повесить|навесить)\s+(?:(?:один|одну)\s+)?'
                          r'(?:полку|картину|зеркало|(?:настенный\s+|потолочный\s+)?карниз|'
                          r'турник|кронштейн)\b', sentence, re.I)
        if match and not re.search(r'\bи\s+(?:еще\s+|ещё\s+)?(?:полк|картин|зеркал|карниз|турник|кронштейн)\w*', sentence, re.I):
            return match
    return None


def _furniture_inventory_pause(messages, index):
    from contact_facts import preceding_staff_speech
    for position in range(index - 1, -1, -1):
        row = messages[position]
        if row.get('direction') in ('note', 'system') or row.get('sender_type') in ('system', 'avito'):
            continue
        if (not _answer_client(row) or row.get('role') in ('system', 'assistant')
                or row.get('speaker_role', 'client') != 'client'
                or not re.fullmatch(r'\s*(?:(?:одну\s+минуту|минутку|секунду)[,\s]+)?'
                                    r'(?:(?:я|сейчас)\s+)*(?:проверю|посмотрю|открою)\s+'
                                    r'(?:коробку|комплект)[.!\s]*', row.get('body', ''), re.I)):
            return None
        question = preceding_staff_speech(messages, position)
        if question and client_inventory_question(question[1]):
            return dict(question_message_id=question[1].get('id', ''),
                        question_quote=question[1]['body'][:300], check_intent_message_id=row.get('id', ''))
        return None
    return None


def voluntary_furniture_inventory(messages, index):
    """An explicit complete kit can precede the questionnaire, never the job."""
    from assistant_catalog import furniture_assembly_request, choose
    message = messages[index]
    if (not _answer_client(message) or message.get('role') in ('system', 'assistant')
            or message.get('speaker_role', 'client') != 'client'
            or (message.get('voice_transcript_status')
                and message['voice_transcript_status'] not in ('ready', 'done', 'completed'))):
        return None
    body = message.get('body', '')
    stock = r'детали\s+и\s+креп[её]ж\s+(?:на\s+месте|в\s+наличии|есть)(?:[.!](?=\s|$)|$)'
    checked = re.match(r'^\s*проверил[аи]?\s+(?:коробку|комплект)\s+по\s+(?:схеме|инструкции)[.!]\s+'
                       + stock, body, re.I)
    if not checked:
        unquoted = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', lambda m: ' ' * len(m[0]), body)
        checked = re.search(r'(?:^|[.!\n])\s*(?:(?:схема|инструкция)\s+(?:уже\s+)?есть,\s*)?'
                            r'(?:вс[её]\s+)?детали\s+и\s+креп[её]ж\s+'
                            r'проверил[аи]?,\s*вс[её]\s+(?:в\s+коробк(?:ах|е)|на\s+месте)[.!](?=\s|$)',
                            unquoted, re.I)
    anchors = {}
    if not checked:
        short = re.match(r'^\s*проверил[аи]?[.!]\s+' + stock, body, re.I)
        pause = _furniture_inventory_pause(messages, index) if short else None
        if pause:
            checked, anchors = short, pause
    if not checked and not re.search(r'\b(?:все\s+(?:нужные\s+)?детали\s+и\s+(?:весь\s+)?креп[её]ж|'
                                     r'весь\s+комплект\s+деталей\s+и\s+креп[её]жа)\b', body, re.I):
        return None
    # A literal report after checking the box is independent of the previous
    # question. Short or unscoped statements still use the delivered question.
    if not checked and any(item.get('direction') == 'out' and '?' in item.get('body', '')
                           for item in messages[:index]):
        return None
    context = []
    for item in messages[:index + 1]:
        if (item.get('direction') != 'in' or item.get('sender_type', 'client') not in
                ('client', 'customer', 'user', 'contact', 'lead', '')):
            continue
        literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', item.get('body', ''))
        if re.search(r'\bнов(?:ая\s+заявка|ый\s+заказ|ое\s+обращение)\b', literal, re.I):
            context = []
        context.append(literal)
    requested = '\n'.join(context)
    scope = choose(requested, {'direction': 'mnc'})
    if (not furniture_assembly_request(requested) or scope['status'] != 'supported'
            or {item['family'] for item in scope['items']} != {'furniture'}):
        return None
    if checked:
        tail = body[checked.end():]
        if re.search(r'детал|креп[её]ж|комплект|\b(?:но|если|не\s+уверен\w*)\b|'
                     r'\bнов(?:ая\s+заявка|ый\s+заказ|ое\s+обращение)\b', tail, re.I):
            return None
        return dict(status='answered', value='yes', message_id=message.get('id', ''),
                    quote=body[:300], evidence_source='client_message',
                    availability_scope='client_reported_furniture_parts_after_check', **anchors)
    literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', body)
    for sentence in re.findall(r'[^.!?;\n]+[.!?;]?', literal):
        if re.search(r'[?]|\b(?:не|нет|если|завтра|будут|будет|возможно|кажется|наверн\w*|'
                     r'сказал\w*|говорит|написал\w*|по\s+словам)\b|\bу\s+(?:вас|мастера|сосед\w*)\b', sentence, re.I):
            continue
        if re.search(r'\b(?:для|от)\s+(?:друг\w*|стар\w*)\b', sentence, re.I):
            continue
        if re.search(r'\b(?:все\s+(?:нужные\s+)?детали\s+и\s+(?:весь\s+)?креп[её]ж|'
                     r'весь\s+комплект\s+деталей\s+и\s+креп[её]жа)\s+'
                     r'(?:уже\s+)?(?:есть|в\s+наличии|в\s+комплекте|на\s+месте)\b', sentence, re.I):
            return dict(status='answered', value='yes', message_id=message.get('id', ''),
                        quote=message.get('body', '')[:300], evidence_source='client_message',
                        availability_scope='client_stated_complete_furniture_kit')
    return None


def hanging_inventory_reply(messages, index):
    """A reported hanging kit answers its delivered client-inventory question.

    This never widens the existing complete-furniture-kit rule. It confirms
    only the client's named hanging parts, not fitment, tools or our stock.
    """
    from assistant_catalog import choose
    message = messages[index]
    if not _answer_client(message) or message.get('role') in ('system','assistant') or message.get('speaker_role','client') != 'client':
        return None
    previous = next((m for m in reversed(messages[:index])
                     if m.get('direction') not in ('note','system') and m.get('sender_type') not in ('system','avito')),None)
    if (not previous or previous.get('direction') != 'out'
            or previous.get('sender_type','operator') not in ('operator','employee','human','assistant','bot','')
            or previous.get('role') == 'system'
            or previous.get('out_pending')
            or previous.get('delivery', previous.get('delivery_status', 'delivered')) in
            ('pending', 'queued', 'sending', 'failed', 'error', 'cancelled', 'canceled')):
        return None
    prompt = previous.get('body','')
    if (prompt.count('?') != 1 or not re.search(SPECS['materials'][2],prompt,re.I)
            or not re.search(r'\bесть\b|в\s+наличии|в\s+комплекте|куплен',prompt,re.I)
            or re.search(r'схем|инструкц|оплат|модел|когда|потол|стен|телефон|номер|адрес|город|'
                         r'\bили\b|\bнет\b|\bне\b|\bмастер\w*|\bнаш\w*|\bу\s+(?:нас|меня)\b',prompt,re.I)):
        return None
    stock = explicit_hanging_stock(messages, index)
    if stock:
        stock.update(question_message_id=previous.get('id',''), question_quote=prompt[:300])
    return stock


def explicit_hanging_stock(messages, index):
    """Literal current named inventory; no invented preceding question."""
    from assistant_catalog import choose
    message = messages[index]
    if (not _answer_client(message) or message.get('role') in ('system','assistant')
            or message.get('speaker_role','client') != 'client'):
        return None
    context=[]
    for item in messages[:index+1]:
        if (not _answer_client(item) or item.get('role') in ('system', 'assistant')
                or item.get('speaker_role', 'client') != 'client'):
            continue
        literal=re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"',' ',item.get('body',''))
        if re.search(r'\bнов(?:ая\s+заявка|ый\s+заказ|ое\s+обращение)\b',literal,re.I):
            context=[]
        context.append(literal)
    service=choose('\n'.join(context),{'direction':'mnc'})
    if service['status']!='supported' or {item['family']for item in service['items']} != {'hanging'}:
        return None
    body=message.get('body','')
    literal=re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"',lambda m:' '*len(m[0]),body)
    for sentence in re.findall(r'[^.!?;\n]+[.!?;]?',literal):
        if re.fullmatch(r'\s*(?:да[,!\s]+)?(?:все\s+(?:нужные\s+)?детали\s+и\s+(?:весь\s+)?креп[её]ж|'
                        r'весь\s+комплект\s+деталей\s+и\s+креп[её]жа)\s+'
                        r'(?:уже\s+)?(?:есть|в\s+наличии|куплен(?:ы)?|в\s+комплекте)[.!\s]*',sentence,re.I):
            return dict(status='answered',value=sentence.strip(),message_id=message.get('id',''),
                        quote=body[:300],
                        evidence_source='client_message',availability_scope='client_reported_hanging_parts_only',
                        availability_subject='детали и крепёж для навесной работы')
    return None


def hanging_inventory_uncertainty(message, row):
    """A later uncertainty narrows this client's named hanging-parts report."""
    if (row.get('availability_scope') != 'client_reported_hanging_parts_only'
            or not _answer_client(message) or message.get('role') in ('system', 'assistant')
            or message.get('speaker_role', 'client') != 'client'):
        return None
    literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', message.get('body', ''))
    mount = row.get('availability_subject') == 'подходящий крепёж для навеса телевизоров'
    for sentence in re.findall(r'[^.!?;\n]+[.!?;]?', literal):
        named_mount_parts = mount and re.search(r'дюбел\w*|винт\w*|саморез\w*|шуруп\w*', sentence, re.I)
        if (not (named_mount_parts or re.search(r'детал\w*|креп[её]ж\w*', sentence, re.I))
                or re.search(r'[?]|\b(?:если|вдруг|завтра|раньше|вчера|сказал\w*|говорит|'
                             r'по\s+словам|сосед\w*|мастер\w*)\b|\bдля\s+друг\w*', sentence, re.I)):
            continue
        if (re.search(r'\b(?:не\s+уверен\w*|не\s+знаю|вроде|кажется|наверн\w*|возможно)\b', sentence, re.I)
                or named_mount_parts and re.search(r'\bне\s+(?:подход\w*|наш[её]л\w*)\b', sentence, re.I)):
            return dict(status='uncertain', value='', message_id=message.get('id', ''),
                        quote=message.get('body', '')[:300], evidence_source='client_message',
                        availability_scope='client_reported_hanging_parts_only',
                        availability_subject='детали и крепёж для навесной работы')
    return None


def material_reply(messages, index):
    """A short inventory reply answers one actual question, not every prerequisite."""
    message = messages[index]
    if message.get('direction') != 'in' or message.get('sender_type', 'client') not in (
            'client', 'customer', 'user', 'contact', 'lead', ''):
        return None
    body = message.get('body', '')
    value = inventory_answer(message.get('body', ''))
    complete_kit = re.fullmatch(
        r'\s*(?:да[,!\s]+)?(?:все\s+(?:нужные\s+)?детали\s+и\s+(?:весь\s+)?креп[её]ж|'
        r'весь\s+комплект\s+деталей\s+и\s+креп[её]жа)\s+'
        r'(?:уже\s+)?(?:есть|в\s+наличии|куплен(?:ы)?|в\s+комплекте)[.!\s]*', body, re.I)
    assembled = value is None and re.fullmatch(
        r'\s*да[,.!\s]+(?:уже\s+)?собран(?:ы|ные|а|о)[,.!\s]+только\s+повесить[.!\s]*',
        message.get('body', ''), re.I)
    if value is None and not assembled and not complete_kit:
        return None
    previous = None
    for item in reversed(messages[:index]):
        if item.get('direction') in ('note', 'system') or item.get('sender_type') in ('system', 'avito'):
            continue
        if item.get('direction') == 'in' and re.fullmatch(r'\s*(?:здравствуйте|добрый\s+(?:день|вечер)|доброе\s+утро)[,!\.\s]*', item.get('body', ''), re.I):
            continue
        previous = item
        break
    if not previous or previous.get('direction') != 'out':
        return None
    if previous.get('sender_type', 'operator') not in ('operator', 'employee', 'human', 'assistant', 'bot', ''):
        return None
    prompt = previous.get('body', '')
    kit_prompt = bool(re.search(r'\bвсе\s+детали\b[^?!\n]{0,25}\bкреп[её]ж\w*', prompt, re.I))
    if (previous.get('out_pending') or str(previous.get('delivery_status') or '').lower()
            in ('pending', 'queued', 'sending', 'failed', 'error', 'cancelled', 'canceled')):
        return None
    if value is not None and _observed_staff_question(previous) and tv_fastener_question(prompt):
        brackets = tv_mount_brackets(messages[:index])
        if (brackets and brackets['present'] and _answer_client(message)
                and message.get('role') not in ('system', 'assistant')
                and message.get('speaker_role', 'client') == 'client'):
            return dict(status='answered', value=value, message_id=message.get('id', ''),
                        question_message_id=previous.get('id', ''), quote=body[:300], question_quote=prompt[:300],
                        evidence_source='client_message', availability_scope='client_reported_hanging_parts_only',
                        availability_subject='подходящий крепёж для навеса телевизоров')
    if (prompt.count('?') != 1 or not re.search(SPECS['materials'][2], prompt, re.I)
            or not re.search(r'\bесть\b|в\s+наличии|в\s+комплекте|приобр|куплен|купили', prompt, re.I)
            or re.search(r'схем|инструкц|оплат|модел|когда|потол|стен|телефон|номер|адрес|город|подъезд|этаж|'
                         r'\bили\b|\bнет\b|\bне\b|\bкаких\b|\bкакие\b|\bчего\b|\bсколько\b', prompt, re.I)):
        return None
    if assembled:
        # The customer confirms the ready cabinets, not all unmentioned
        # fasteners, consumables or the contractor's stock.
        if not any(item.get('direction') == 'in' and re.search(
                r'\b(?:повесить|навесить)\b[^.!?]{0,40}\b(?:шкаф|тумб|модул)\w*',
                item.get('body', ''), re.I) for item in messages[:index]):
            return None
        value = 'yes'
    if complete_kit or kit_prompt:
        from assistant_catalog import furniture_assembly_request, choose
        # Keep the subject of the delivered furniture question. A spare part,
        # a different order or the contractor's stock is not this complete kit.
        context = []
        for item in messages[:index]:
            if item.get('direction') != 'in' or item.get('sender_type', 'client') not in (
                    'client', 'customer', 'user', 'contact', 'lead', ''):
                continue
            literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', item.get('body', ''))
            if re.search(r'\bнов(?:ая|ый|ое)\s+(?:заявка|заказ|обращение)\b|\bдруг(?:ая|ой)\s+проблем', literal, re.I):
                context = []
            context.append(literal)
        requested = '\n'.join(context)
        scope = choose(requested, {'direction': 'mnc'})
        if (not furniture_assembly_request(requested) or scope['status'] != 'supported'
                or {item['family'] for item in scope['items']} != {'furniture'}):
            return None
        if kit_prompt and re.search(r'\b(?:мы|наш\w*|мастер\w*)\b|\bу\s+нас\b', prompt, re.I):
            return None
        if complete_kit:
            value = 'yes'
    return dict(status='answered', value=value,
                message_id=message.get('id', ''), question_message_id=previous.get('id', ''),
                quote=message.get('body', '')[:300], question_quote=prompt[:300],
                evidence_source='client_message', availability_scope=(
                    'client_named_assembled_furniture_only' if assembled else
                    'client_stated_complete_furniture_kit' if complete_kit else 'question_subject_only'))


# Mixed letters and digits also occur in paper sizes, units and addresses.
# They are not evidence of the appliance model, even after a model question.
NON_MODEL_TOKEN = re.compile(
    r"(?:"
    r"\d+(?:[.,]\d+)?(?:[xх×*]\d+(?:[.,]\d+)?){1,2}(?:мм|см|mm|cm|углов(?:ой|ая|ые|ых)?)?"
    r"|[aаbб](?:10|[0-9])"
    r"|\d+(?:[.,]\d+)?(?:гб|gb|мб|mb|тб|tb|кб|kb|в|v|вт|w|квт|kw|гц|hz|мгц|mhz|ггц|ghz|мм|mm|см|cm|м|m|кг|kg|г|g|дюйм\w*)"
    r"|\d+(?:шт(?:ук[аи]?)?|штук|pcs|ед)"
    r"|\d+[кkсc]\d+"
    r"|(?:кв|квартира|дом|корп|стр|офис|эт|под)\d+"
    r"|(?:win|windows|android|андроид|ios)\d+"
    r")",
    re.IGNORECASE,
)
PAPER_FORMAT_TOKEN = re.compile(r"[aаbб](?:10|[0-9])", re.IGNORECASE)
DIMENSION_TOKEN = re.compile(
    r"\b\d+(?:[.,]\d+)?(?:[xх×*]\d+(?:[.,]\d+)?){1,2}"
    r"(?:мм|см|mm|cm|углов(?:ой|ая|ые|ых)?)?\b", re.IGNORECASE)
EXPLICIT_MODEL_PREFIX = re.compile(
    r"(?:модел[ьиь]\w*|samsung|самсунг|lenovo|леново|oppo|vivo|honor|хонор|asus)"
    r"\s*[:#—-]?\s*$",
    re.IGNORECASE,
)


def client_age(messages):
    """Explicit age only; a bare number answers the immediately preceding age question."""
    result = dict(status='missing', value=None, asked=0, message_id='')
    for i, message in enumerate(messages):
        if (message.get('direction') != 'in'
                or message.get('sender_type') in ('system', 'avito', 'operator', 'employee', 'assistant', 'bot')):
            continue
        body = (message.get('body') or '').replace('ё', 'е').replace('Ё', 'Е')
        from contact_facts import preceding_staff_speech
        previous = preceding_staff_speech(messages, i)
        question = previous[1] if previous else {}
        prompted = bool(previous and re.search(
            r'ваш.{0,8}возраст|свой\s+возраст|сколько.{0,15}лет|'
            r'вам\s+(?:(?:уже|еще)\s+)?(?:есть|исполнилось)\s+(?:18|восемнадцать)'
            r'(?:\s+лет)?(?=\s*[,?!\.\n]|$)|'
            r'вы\s+совершеннолет', question.get('body') or '', re.I))
        result['asked'] += int(prompted)
        if (prompted and re.search(r'(?:есть|исполнилось)\s+(?:18|восемнадцать)|совершеннолет', question.get('body') or '', re.I)
                and re.fullmatch(r'\s*(?:да|нет)[.!\s]*', body, re.I)):
            result.update(status='adult' if re.search(r'да', body, re.I) else 'minor', value=None,
                          message_id=message.get('id', ''))
            continue
        if re.search(r'мне\s+(?:еще\s+)?нет\s+18\b|я\s+несовершеннолетн', body, re.I):
            result.update(status='minor', value=None, message_id=message.get('id', ''))
            continue
        match = re.search(r'\bмне\s+(?:уже\s+)?(\d{1,3})\s*(?:лет|год[а]?)\b|\bмой\s+возраст\s*[:—-]?\s*(\d{1,3})\b', body, re.I)
        if not match and prompted:
            match = re.fullmatch(r'\s*(?:(?:да|нет)[,.!\s]*)?(?:мне\s+)?'
                                 r'(?:(?:пока\s+что|пока|только)\s+)*(\d{1,3})\s*(?:лет|год[а]?)?[.!\s]*', body, re.I)
            if not match:
                match = re.match(r'^\s*(?:Здравствуйте[,!\s]*)?(?:мне\s+)?(\d{1,3})\s*(?:лет)?[,.;!?]\s*'
                                 r'(?:а\s+)?(?:зачем|почему|вопрос\s+к\s+чему)', body, re.I)
        value = int(next(x for x in match.groups() if x is not None)) if match else None
        if value is None:
            introduction = _self_introduction_evidence(message)
            if introduction:
                value = int(introduction['age'])
        if value is not None and 1 <= value <= 120:
            result.update(status='adult' if value >= 18 else 'minor', value=value, message_id=message.get('id', ''))
        elif prompted and (UNKNOWN.search(body) or re.search(r'не хочу|не буду|не скажу', body, re.I)):
            result.update(status='unavailable', value=None, message_id=message.get('id', ''))
    return result


def adult_presence(messages, age=None):
    """Client evidence of an adult at a minor's visit, never a booking receipt."""
    age = age if age is not None else client_age(messages)
    result = dict(required=age['status'] == 'minor', status='missing', message_id='', quote='',
                  question_message_id='', question_quote='', window_message_ids=[],
                  appointment_confirmed=False, source='client_message')
    if not result['required']:
        result['status'] = 'not_required'
        return result
    from contact_facts import preceding_staff_speech
    person = r'\b(?:родител\w*|мам(?:а|ы|е|у|ой|ою)|пап(?:а|ы|е|у|ой|ою)|отец|мать|бабушк\w*|дедушк\w*|взросл\w*|совершеннолетн\w*)\b'
    presence = r'дома|присутств|на\s+месте|при\s+визите|будут|будет'
    window = {}
    for i, message in enumerate(messages):
        if (message.get('direction') != 'in'
                or message.get('sender_type') in ('system', 'avito', 'operator', 'employee', 'assistant', 'bot')):
            continue
        body = str(message.get('body') or '')
        old_window = dict(window)
        day = re.search(r'\b(?:сегодня|завтра|послезавтра|в\s+(?:понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье))\b', body, re.I)
        hour = re.search(r'\b(?:в|к|после|до)\s*\d{1,2}(?::\d{2})?(?:\s*[-–—]\s*\d{1,2}(?::\d{2})?)?'
                         r'(?!\d)(?!\s*(?:подъезд|этаж|квартир|дом|руб|метр|мм|см|винд))', body, re.I)
        for key, match in (('day', day), ('hour', hour)):
            if match:
                window[key] = dict(value=match[0].lower(), message_id=message.get('id', ''))
        if (result['status'] == 'confirmed' and result.get('scope') != 'any_visit'
                and {k:v['value'] for k,v in old_window.items()} != {k:v['value'] for k,v in window.items()}):
            result['prior_confirmation'] = {k:result[k] for k in ('message_id','quote','question_message_id','window_message_ids')}
            result['status'] = 'needs_reconfirmation'
        result['window_message_ids'] = [v['message_id'] for v in window.values()]
        previous = preceding_staff_speech(messages, i)
        prompt = previous[1].get('body', '') if previous else ''
        asked = bool(re.search(person, prompt, re.I) and re.search(presence, prompt, re.I)
                     and not re.search(r'ваш.{0,10}возраст|вам.{0,20}(?:18|восемнадцать)|вы\s+совершеннолет', prompt, re.I))
        yes = bool(asked and re.fullmatch(r'\s*(?:да|ага|конечно|будут|будет)[.!\s]*', body, re.I))
        no = bool(asked and re.fullmatch(r'\s*(?:нет|не\s+будут|не\s+будет)[.!\s]*', body, re.I))
        negative_prompt = bool(re.search(r'не\s+буд[еу]т|не\s+смог', prompt, re.I))
        has_person = bool(re.search(person, body, re.I))
        negative = bool(has_person and re.search(r'не\s+(?:буд[еу]т|смог\w*|мож\w*|получится|дома)|'
                                                r'взросл\w*\s+нет\b|без\s+взросл|'
                                                r'(?:буд[еу]т\s+)?(?:на\s+работе|в\s+отъезде)', body, re.I)
                        and not re.search(r'вчера|позавчера|не\s+(?:был\w*|было)', body, re.I))
        impossible = bool(has_person and re.search(r'никогда|совсем\s+невозможно|в\s+принципе\s+невозможно', body, re.I))
        possible = bool(has_person and re.search(r'\bмог[уут]\w*\s+присутств|\bсмож\w*\s+присутств|возможно|наверно', body, re.I))
        positive = bool(has_person and re.search(presence, body, re.I)
                        and not re.search(r'не\s+(?:был\w*|было)', body, re.I))
        ambiguous = bool((yes or no) and negative_prompt or has_person and '?' in body)
        state = ('possible' if ambiguous else 'impossible' if impossible else 'unavailable' if negative or no
                 else 'possible' if possible else 'confirmed' if positive or yes else '')
        if not state:
            continue
        scope = 'any_visit' if re.search(r'всегда|постоянно|при\s+визите', body if has_person else prompt, re.I) else 'requested_window'
        if state == 'confirmed' and not window and scope != 'any_visit':
            state = 'possible'
        if result['status'] == 'confirmed' and state != 'confirmed':
            result['prior_confirmation'] = {k:result[k] for k in ('message_id','quote','question_message_id','window_message_ids')}
        result.update(status=state, message_id=message.get('id', ''), quote=body[:500], scope=scope,
                      question_message_id=(previous[1].get('id', '') if asked else ''),
                      question_quote=prompt[:500] if asked else '')
    return result


def adult_presence_question(state):
    question = ('В это время кто-то из взрослых сможет присутствовать?' if state.get('window_message_ids')
                else 'Когда кто-то из взрослых сможет присутствовать?')
    return dict(kind='adult_presence', question=question, groups=[['взросл'], ['присутств']],
                rule_ids=['DOC-L1572', 'DOC-L1573'])


def needs_client_age(known, service):
    return known.get('channel') == 'jivo' and known.get('direction') == 'kp' and any(
        item.get('family') in ('pc', 'gpu') for item in service.get('items', []))


def room_statement_match(text):
    """A stated work location, preserving source offsets and uncertainty."""
    masked = re.sub(
        r'\b(?:другой\s+)?(?:мастер|специалист|сосед)\w*[^.!?\n«“"]{0,30}'
        r'\b(?:спросил|сказал|написал|ответил)\w*\s*[:,-]?\s*(?:«[^»]*»|“[^”]*”|"[^"\n]*")',
        lambda match: ' ' * len(match[0]), text, flags=re.I)
    for match in re.finditer(r'\b(?:на|в|для)\s+(?:кухн\w*|ванн\w*)\b', masked, re.I):
        prefix = re.split(r'[.!?;\n,]', masked[:match.start()])[-1]
        if (re.search(r'\bне(?:\s+(?:совсем|только))?\s*$', prefix, re.I)
                or re.search(r'\b(?:если|вдруг|предположим|допустим)\b', prefix, re.I)):
            continue
        tail = re.split(r'[.!?;\n,]', masked[match.end():], maxsplit=1)[0]
        clause = prefix + match[0] + tail
        if re.search(r'\b(?:кухн\w*|ванн\w*)\s+или\s+(?:(?:в|на|для)\s+)?(?:кухн\w*|ванн\w*)', clause, re.I):
            continue
        whole_clause = re.split(r'[.!?;\n]', masked[:match.start()])[-1] + match[0] + tail
        if re.search(r'кухонн\w*\s+(?:раковин|мойк)\w*[^.!?;\n]{0,25}\bили\b[^.!?;\n]{0,15}\bванн',
                     whole_clause, re.I):
            continue
        return match
    # A location relative to a kitchen sink is literal room evidence. Merely
    # owning a kitchen-labelled product does not establish where work is due.
    # Keep offsets by masking quoted speech rather than deleting it.
    direct = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"',
                    lambda match: ' ' * len(match[0]), text)
    for match in re.finditer(r'\b(?:под|в)\s+кухонн\w*\s+(?:раковин|мойк)\w*\b', direct, re.I):
        prefix = re.split(r'[.!?;\n]', direct[:match.start()])[-1]
        tail = re.split(r'[.!?;\n]', direct[match.end():], maxsplit=1)[0]
        clause = prefix + match[0] + tail
        if (re.search(r'\bне(?:\s+(?:совсем|только))?\s*$', prefix, re.I)
                or re.search(r'\b(?:если|вдруг|предположим|допустим|возможно|наверно\w*|'
                             r'раньше|прежде|вчера|позавчера|или|мастер\w*|специалист\w*|сосед\w*)\b|'
                             r'\bне\s+знаю\b|\bне\s+(?:нужно|надо|требуется)\b', clause, re.I)):
            continue
        next_punctuation = direct[match.end() + len(tail):match.end() + len(tail) + 1]
        if next_punctuation == '?' and not re.search(
                r'нуж\w*|замен\w*|установ\w*|подключ\w*|теч\w*|протек\w*|протёк\w*|засор\w*', clause, re.I):
            continue
        return match
    return None



def printer_problem_match(text):
    """Literal printer work/symptoms, never a diagnosis of a faulty component."""
    source = str(text or '')
    masked = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', lambda m: ' ' * len(m[0]), source)
    resets = list(re.finditer(r'новая\s+заявка|друг(?:ая|ой)\s+(?:проблема|принтер)', masked, re.I))
    if resets:
        masked = ' ' * resets[-1].start() + masked[resets[-1].start():]
    if not re.search(r'\b(?:принтер|мфу|сканер)\w*', masked, re.I):
        return None
    for clause in re.finditer(r'[^.!?;\n]+', masked):
        body = clause[0]
        if re.search(r'друг\w*\s+мастер|\bсосед\w*|в\s+объявлени|написан\w*\s+что', body, re.I):
            continue
        if re.search(r'\bне\s+(?:нужно|надо|хочу|следует)\b|\bне\s+(?:снимать|снять|отсоединять|засох)', body, re.I):
            continue
        cover = re.search(r'(?P<adf_cover>\b(?:снять|снимите|отсоединить|отсоедините)\b[^.!?;\n]{0,45}'
                          r'крышк\w*[^.!?;\n]{0,35}(?:автоподач\w*|автоподатчик\w*|\badf\b))', body, re.I)
        if cover:
            return re.compile(r'(?P<adf_cover>' + re.escape(cover[0]) + ')', re.I).search(
                source, clause.start() + cover.start(), clause.start() + cover.end())
        # Ink on a wall/table/pen, a hypothetical and a third-party statement
        # do not establish the client's printer symptom.
        if re.search(r'\bесли\b|ручк|маркер|кист|стен|стол|корпус|баноч|краск\w*\s+для', body, re.I):
            continue
        paper = re.search(r'(?P<paper_feed>\b(?:жу[её]т|заж[её]выва\w*|мн[её]т)\s+(?:бумаг|лист)\w*|'
                          r'\b(?:бумаг|лист)\w*\s+(?:застрева\w*|заж[её]выва\w*)|'
                          r'\bзамяти\w*\s+бумаг\w*)', body, re.I)
        if (paper and not re.search(r'\b(?:не|нет|без)\s*$', body[:paper.start()], re.I)
                and not re.search(r'\b(?:раньше|прежде|было|бывало)\b', body[:paper.start()], re.I)):
            return re.compile(r'(?P<paper_feed>' + re.escape(paper[0]) + ')', re.I).search(
                source, clause.start() + paper.start(), clause.start() + paper.end())
        ink = re.search(r'(?P<dry_ink>\bзасох\w*\s+(?:краск|чернил)\w*)', body, re.I)
        printer_here = re.search(r'\b(?:в\s+(?:мо[её]м\s+)?(?:принтер|мфу)\w*|принтер\w*[^.!?;\n]{0,45}:)', body, re.I)
        if ink and (printer_here or re.search(r'(?:краск|чернил)\w*\s+в\s+(?:принтер|мфу)\w*', body, re.I)):
            return re.compile(r'(?P<dry_ink>' + re.escape(ink[0]) + ')', re.I).search(
                source, clause.start() + ink.start(), clause.start() + ink.end())
    return None


def printer_conversion_request(text):
    body = re.sub(r'«[^»]*»|“[^”]*”|\"[^\"\n]*\"', '', str(text or ''))
    if re.search(r'\bне\s+передел', body, re.I):
        return False
    return bool(re.search(r'\b(?:принтер|мфу)\w*', body, re.I)
                and re.search(r'\bпередела(?:ть|йте)\b[^.!?\n]{0,100}\bиз\b[^.!?\n]{0,50}\bв\b', body, re.I))


def printer_stated_scope(messages):
    """Keep the actual client row; a staff suggestion is not an ordered job."""
    import assistant_prices
    result = None
    for message in assistant_prices.current_enquiry_messages(messages):
        if message.get('direction') != 'in' or message.get('sender_type', 'client') not in ('client', ''):
            continue
        if re.search(r'новая\s+заявка|друг(?:ая|ой)\s+(?:проблема|принтер)', message.get('body', ''), re.I):
            result = None
        match = printer_problem_match(message.get('body', ''))
        if match:
            result = dict(kind=match.lastgroup, message_id=message.get('id',''),
                          quote=message['body'], evidence_source='client_message')
    return result


def software_operation_match(text):
    """Resolve the requested operation, not a possible cause or past work."""
    literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', lambda m: ' ' * len(m[0]), text)
    operation = (r'\b(?:(?:пере)?установ(?:ить|ка|ку|ки|ите)|устанавливать|'
                 r'настро(?:ить|йка|йку|йки|йте)|настраивать|обуч(?:ить|ение|ению|ите))\b')
    software = r'\b(?:программ\w*|драйвер\w*|windows|винд\w*|office|word|ворд\w*|excel|exel|эксел\w*|autocad|photoshop|компас|premiere|битрикс|1с|3d\s*max)\b'
    for match in re.finditer(operation, literal, re.I):
        prefix = re.split(r'[.!?;\n]', literal[:match.start()])[-1]
        suffix = re.split(r'[.!?;\n]', literal[match.end():])[0]
        clause = prefix + match[0] + suffix
        if re.search(r'\b(?:может|если|возможно|не\s+знаю|сомнева\w*|пробовал\w*|пытал\w*|'
                     r'сказал\w*|говор\w*|написал\w*|по\s+словам)\b|'
                     r'\b(?:стоит|нужно|надо)\s+ли\b', clause, re.I):
            continue
        if (re.search(r'\b(?:не\s+(?:(?:нужно|надо|требуется|хочу|просил[аи]?|заказывал[аи]?)\s+)?|после\s+|до\s+)$', prefix, re.I)
                or re.search(r'\bне\s+(?:нужн\w*|требуется)\b', suffix, re.I)):
            continue
        # A direct physical object is not a choice about software, even if
        # an unrelated program was mentioned earlier in the same sentence.
        if re.match(r'\s+(?:(?:нов\w*|стар\w*)\s+)?(?:унитаз|картридж|замок|дверь|розетк)\w*\b',
                    suffix, re.I):
            continue
        terse = re.fullmatch(r'\s*' + operation + r'\s*(?:,\s*пожалуйста)?[.!?\s]*', literal, re.I)
        if re.search(software, clause, re.I) or terse:
            return match
    return None


def printer_printing_host_match(text):
    """An explicit present printing host, not software names or a future plan."""
    literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', lambda m: ' ' * len(m[0]), text)
    if re.search(r'\b(?:если|допустим|сосед\w*|сказал\w*|говорит|написал\w*|другой|второй)\b', literal, re.I):
        return None
    for clause in re.finditer(r'[^,;.!?\n]+', literal):
        if literal[clause.end():clause.end()+1] == '?':
            continue
        match = re.search(r'\b(?:печатаю|печатаем)\s+(?:с|через)\s+'
                          r'(?:компьютер[а]?|ноутбук[а]?|пк|телефон[а]?|планшет[а]?)\b', clause[0], re.I)
        if match and not re.search(r'\bне\s*$', clause[0][:match.start()], re.I):
            return re.compile(re.escape(match[0]), re.I).search(text, clause.start(), clause.end())
    return None


def current_printer_printing_evidence(messages):
    import assistant_prices
    printer = False
    result = None
    for row in assistant_prices.current_enquiry_messages(messages):
        if row.get('direction') != 'in' or row.get('sender_type', 'client') not in ('client', ''):
            continue
        text = row.get('body', '')
        literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', text)
        if re.match(r'\s*(?:новая\s+заявка|новый\s+заказ|по\s+другому\s+вопросу|теперь\s+нужно)\b', literal, re.I):
            printer = False; result = None
        if re.search(r'\b(?:другой|второй)\s+принтер\b', literal, re.I):
            printer = False; result = None
        if re.search(r'\b(?:принтер|мфу)\w*', literal, re.I):
            printer = True
        if not printer or re.search(r'\b(?:если|допустим|сосед\w*|сказал\w*|написал\w*|раньше)\b', literal, re.I):
            continue
        usage = re.search(r'\b(?:печатаю|печатаем|печатает)\b', literal, re.I)
        colour = (re.search(r'цвет|оттен|серый', literal, re.I)
                  and re.search(r'уходит|искаж|неверн|неправильн', literal, re.I))
        if usage and re.search(r'\bне\s*$', literal[:usage.start()], re.I):
            usage = None
        if usage or colour:
            result = dict(message_id=row.get('id', ''), quote=text,
                          source='client_current_printing_report', actual_host_established=False)
    return result


def answer_match(key, pattern, text):
    if key == 'client_name':
        matches = list(re.finditer(pattern, text, re.I))
        return matches[-1] if matches else None
    if key == 'instructions':
        subject = r'\b(?:схем|инструкц)\w*(?:\s+сборки)?'
        completed = r'(?:наш[её]л|нашла|нашли|нашл(?:ась|ись|ось)|получил[аи]?|скачал[аи]?|достал[аи]?|отыскал[аи]?)'
        for found in re.finditer(r'\b' + completed + r'\s+(?:уже\s+)?' + subject + r'|'
                                 + subject + r'\s+(?:уже\s+)?' + completed + r'\b', text, re.I):
            prefix = re.split(r'[.!?;\n]', text[:found.start()])[-1]
            if (not re.search(r'\bне\s*$', prefix, re.I)
                    and not re.search(r'\b(?:мастер|сосед|продавец|он|она|они)\b', prefix, re.I)):
                return found
        possession = re.search(
            subject + r'\s+(?:остал(?:ась|ись)|лежит|лежат|находится|находятся)\s+'
            r'(?:в\s+(?:коробк|упаковк)\w*|у\s+меня\b|на\s+руках\b)|'
            + subject + r'\s+у\s+меня(?:\s+на\s+руках)?\b|'
            + subject + r'(?:\s+и\s+|\s*,\s*)(?:комплект\s+креп[её]жа|все\s+детали\s+и\s+креп[её]ж)\s+есть\b', text, re.I)
        if possession:
            return possession
    if key == 'software_use':
        return software_operation_match(text)
    if key == 'room':
        return room_statement_match(text)
    if key == 'problem':
        printer = printer_problem_match(text)
        if printer:
            return printer
    if key == 'furniture_problem':
        from assistant_catalog import swollen_furniture_panels, furniture_parts_replacement_request, furniture_fitting_problem
        if furniture_parts_replacement_request(text):
            # The requested replacement itself states the job, independent
            # of which adjective describes the damaged parts. Keep its quote.
            return re.search(r'.+', text, re.S)
        panels = swollen_furniture_panels(text)
        if panels:
            return panels
        fitting = furniture_fitting_problem(text)
        if fitting:
            return fitting
    if key == 'printer_connection':
        present_host = printer_printing_host_match(text)
        if present_host:
            return present_host
        # This is an explicit client description of the connection, even
        # when it is broken. Do not ask the same computer/phone question.
        connection = re.search(r'\b(?:комп(?:ьютер)?|пк|ноутбук|телефон|планшет)\s+не\s+(?:видит|находит|определяет|распозна[её]т)\s+(?:его|принтер)\b', text, re.I)
        if connection:
            return connection
    if key == 'internet':
        # Router availability and a request to bring internet into the flat
        # do not prove an existing provider connection.
        pattern = (r'\bинтернет\s+(?:(?:уже|в\s+квартиру|в\s+квартире)\s+){0,2}(?:провед[её]н|подключ[её]н|есть|не\s+провед[её]н|нет)\b|'
                   r'\b(?:провед[её]н|подключ[её]н|есть|нет)\s+(?:(?:уже|в\s+квартиру|в\s+квартире)\s+){0,2}интернет\b')
    if key == 'gas_type':
        text = re.sub(r'электрическ\w*\s+(?:вилк|розетк|проводк|кабел)\w*', lambda m: ' ' * len(m[0]), text, flags=re.IGNORECASE)
        absent = re.search(r'\bгазов\w*\s+элемент\w*\s+нет\b', text, re.I)
        if absent:
            return absent
    if key == 'model':
        samsung_printer = re.search(r'\b(?:samsung|самсунг)\s+scx[-\s]*\d{3,5}[a-z]{0,3}(?!\w)', text, re.I)
        if samsung_printer and not re.match(r'\s*(?:руб|₽|год)', text[samsung_printer.end():], re.I):
            return samsung_printer
        printer_model = re.search(r'\b(?:hp\s+(?:deskjet(?:\s+plus)?(?:\s+ink\s+advantage)?|laserjet)\s+|canon\s+pixma\s+(?:[a-z]{1,3}\s*)?)\d{3,5}[a-z]?(?!\w)', text, re.IGNORECASE)
        if printer_model:
            return printer_model
    for match in re.finditer(pattern, text, re.IGNORECASE):
        if key == 'model' and any(size.start() <= match.start() and match.end() <= size.end()
                                  for size in DIMENSION_TOKEN.finditer(text)):
            # × and * split the generic alphanumeric matcher. Exclude a
            # dimension's trailing fragment as well as its complete token.
            continue
        if key != "model" or not NON_MODEL_TOKEN.fullmatch(match.group(0)):
            return match
        # Some devices share a paper-format code, e.g. Samsung A10.
        # Require the explicit model label or adjacent device brand in that case.
        if PAPER_FORMAT_TOKEN.fullmatch(match.group(0)) and EXPLICIT_MODEL_PREFIX.search(
            text[: match.start()]
        ):
            return match
    if key == 'model':
        # Fallback only: preserve existing contiguous model evidence. Clients
        # also write «эпсон л 3101»; a bare number/address/price is not a model.
        epson_model = re.search(r'\b(?:epson|эпсон|эспон)\s+(?:(?:xp|хр|wf|et|ew|tx|тх|px|[lлmмpпrрsсtт])[-\s]*)?\d{3,5}[a-zа-я]?(?!\w)', text, re.IGNORECASE)
        if epson_model and not re.match(r'\s*(?:руб|₽|год)', text[epson_model.end():], re.I):
            return epson_model
    return None


def lock_work_choice(messages):
    """Requested work, not a diagnosis inferred from a sticking lock."""
    from contact_facts import preceding_staff_speech
    result = None
    last_subject = None
    kinds = {'repair': r'отремонт\w*|ремонт\w*|почин\w*',
             'replace': r'замен\w*|помен\w*',
             'install': r'установ\w*|устанавл\w*|постав\w*|прикрут\w*|закреп\w*'}
    noun = r'\b(?:замок|замк\w*|ручк\w*)\b'
    for i, message in enumerate(messages):
        if message.get('direction') != 'in' or message.get('sender_type') in ('system','avito','operator','employee','assistant','bot'):
            continue
        original_body = str(message.get('body') or '')
        body = re.sub(r'\b(?:магазин\w*|отдел\w*|салон\w*|павильон\w*)\s*[«"“][^»"”\n]+[»"”]',
                      '[НАЗВАНИЕ ОРИЕНТИРА]', original_body, flags=re.I)
        if re.search(noun, body, re.I):
            last_subject = 'ручка' if re.search(r'ручк',body,re.I) and not re.search(r'замок|замк',body,re.I) else 'замок'
        previous = preceding_staff_speech(messages, i)
        prompt = previous[1].get('body','') if previous else ''
        actual_question = bool(previous and prompt.count('?') == 1 and re.search(noun,prompt,re.I)
                               and re.search(r'ремонт|замен|установ',prompt,re.I))
        choices = []
        subject = 'ручка' if re.search(r'ручк',body+' '+prompt,re.I) and not re.search(r'замок|замк',body+' '+prompt,re.I) else 'замок'
        for clause in re.split(r'[.!?;\n]+|,(?!\s*если\b)|\s+и\s+(?=отремонт|почин|замен|помен|установ|постав|прикрут|закреп)',body,flags=re.I):
            named = bool(re.search(noun,clause,re.I))
            other = re.search(r'шкаф|унитаз|бачок|смесител|гусак|холодильник|стиральн|посудомо|духов',clause,re.I)
            if (re.search(r'адрес|улиц|где\s+находит',prompt,re.I)
                    and not re.search(r'нуж\w*|помен\w*|замен\w*|почин\w*|отремонтир\w*|установ\w*',clause,re.I)):
                continue
            if (named and other and re.search(r'ручк',clause,re.I)
                    and not re.search(r'замок|замк|входн|межкомнатн',clause,re.I)):
                continue
            if not named and (not actual_question or other):
                continue
            if re.search(r'\bесли\b|\bпотребуется\b|\bпонадобится\b',clause,re.I):
                continue
            for kind,pattern in kinds.items():
                for found in re.finditer(pattern,clause,re.I):
                    before,after = clause[:found.start()],clause[found.end():]
                    if re.search(r'\bне\s+$',before,re.I) or re.match(r'[^.!?]{0,20}\bне\s+(?:нуж|треб)',after,re.I):
                        continue
                    choices.append(kind)
        unique = list(dict.fromkeys(choices))
        if len(unique) == 1:
            result = dict(status='answered',value=unique[0],message_id=message.get('id',''),quote=original_body[:500],
                          question_message_id=previous[1].get('id','') if actual_question else '',
                          question_quote=prompt[:500] if actual_question else '',subject=subject,evidence_source='client_message')
    return result or (dict(subject=last_subject) if last_subject else None)


def referenced_tv_type(messages):
    """Exact, source-checked product references, never a whole model-family guess."""
    references = {
        '26PFL7332S/60': ('LCD', 'https://www.philips.ru/c-p/26PFL7332S_60/7000-series-66-cm-26-inch-lcd-hd-ready'),
    }
    incoming = [m for m in messages if m.get('direction') == 'in'
                and m.get('sender_type') not in ('system', 'avito', 'operator', 'employee', 'assistant', 'bot')]
    text = '\n'.join(m.get('body', '') for m in incoming)
    if re.search(r'монитор|ноутбук|компьютер|\bпк\b|\bне\s+(?:philips|филипс)|'
                 r'\b(?:samsung|самсунг|lg|sony|hisense|haier|tcl)\b|[«»“”"]', text, re.I):
        return None
    models = set(re.findall(r'\b\d{2}PFL[A-Z0-9]+(?:/\d{2})?(?![\w/])', text, re.I))
    found = []
    for message in incoming:
        observation = message.get('media_observation') if message.get('media_reviewed') else None
        if (observation and observation.get('source') in ('reviewed_image', 'offline_reviewed_image')
                and observation.get('device_kind') == 'tv' and observation.get('content_kind') == 'device_label'):
            model = observation.get('model', '').upper()
            models.add(model)
            if model in references:
                found.append((message, model, 'reviewed device label'))
        for model in references:
            if re.search(r'(?<![\w/])' + re.escape(model) + r'(?![\w/])', message.get('body', ''), re.I):
                found.append((message, model, 'client-supplied exact model'))
    models = {value.upper() for value in models}
    if len(models) != 1 or not found or found[-1][1] not in models:
        return None
    message, model, supplied = found[-1]
    value, url = references[model]
    return dict(status='answered', value=value, model=model, message_id=message.get('id', ''),
                quote=message.get('body') or model, evidence_source='manufacturer_model_reference',
                manufacturer_source_url=url,
                interpretation='Exact manufacturer product reference; ' + supplied + '; display type only, not diagnosis or consent')


def screen_hazards(messages):
    """Impact and moisture are independent client facts under DOC-L0223."""
    patterns = {
        'impact': r'роня\w*|урони\w*|\bупал\w*|\bпадал\w*|\bбил\w*|удар\w*|разби\w*|повре[дж]\w*|трещин\w*',
        'moisture': r'залив\w*|залил\w*|\bвод(?:а|ы|у|ой|е)\b|влаг\w*|намоч\w*',
    }
    facets = {key: dict(status='missing', asked=0) for key in patterns}
    prompts = {key: set() for key in patterns}
    unspecified = None
    screen_context = any(re.search(r'телевиз|экран|\bтв\b|плазмен|кинескоп', m.get('body', ''), re.I)
                         or m.get('media_reviewed') and (m.get('media_observation') or {}).get('device_kind') == 'tv'
                         for m in messages if m.get('direction') in ('in', 'out')
                         and m.get('sender_type') not in ('system', 'avito', 'bot', 'assistant'))
    for index, message in enumerate(messages):
        if not screen_context or message.get('direction') != 'in' or message.get('sender_type') in ('system', 'avito', 'operator', 'assistant', 'bot'):
            continue
        original = message.get('body', '')
        text = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', original)
        previous_index, previous = next(((i, m) for i, m in reversed(list(enumerate(messages[:index])))
                         if m.get('direction') not in ('note', 'system')
                         and m.get('sender_type') not in ('system', 'avito')), (-1, {}))
        delivered = not previous.get('out_pending') and previous.get('delivery_status') not in (
            'pending', 'queued', 'sending', 'failed', 'error', 'cancelled', 'canceled')
        prompt = previous.get('body', '') if previous.get('direction') == 'out' and delivered else ''
        subjects = [key for key, pattern in patterns.items() if re.search(pattern, prompt, re.I)]
        binary_yes = bool(prompt.count('?') == 1 and not re.search(r'\bне\b', prompt, re.I)
                          and re.fullmatch(r'\s*да[.!\s]*', text, re.I))
        if binary_yes and len(subjects) == 2:
            unspecified = dict(position=index, message_id=message.get('id', ''), quote=original[:300])
        for key, pattern in patterns.items():
            facet = facets[key]
            asked_here = bool('?' in prompt and re.search(pattern, prompt, re.I))
            if asked_here:
                prompts[key].add(previous_index)
                facet['asked'] = len(prompts[key])
            explicit = []
            for clause in re.split(r'(?<=[.!?\n;,])|\bно\b|\bа\b', text):
                if (clause.rstrip().endswith('?') or re.search(r'\bесли\b|возможно|\bможет\b|могл|наверно|кажется|вроде|'
                        r'не\s*зна|неизвест|не\s*уверен|непонят|подозре|\bли\b|\bили\s+нет\b', clause, re.I)
                        or (re.search(r'домофон|стираль|холодиль|пылесос|телефон|раковин|\bтруб', clause, re.I)
                            and not re.search(r'телевиз|экран|\bтв\b', clause, re.I))):
                    continue
                for match in re.finditer(pattern, clause, re.I):
                    negative = bool(re.search(r'\b(?:не|ни|без)\s*$', clause[:match.start()], re.I)
                                    or re.match(r'[\w\s]{0,20}\b(?:нет|не\s+(?:был|было|попад|залив|залил))', clause[match.end():], re.I))
                    explicit.append('no' if negative else 'yes')
            binary_no = asked_here and prompt.count('?') == 1 and re.fullmatch(r'\s*нет[.!\s]*', text, re.I)
            single_yes = binary_yes and subjects == [key]
            if explicit or binary_no or single_yes:
                facet.update(status='answered', value=('yes' if 'yes' in explicit or single_yes else 'no'),
                             position=index,
                             message_id=message.get('id', ''), quote=original[:300], evidence_source='client_message')
    both = all(row['status'] == 'answered' for row in facets.values())
    if unspecified and both and all(row.get('position', -1) > unspecified['position'] for row in facets.values()):
        unspecified = None
    positive = next((row for row in facets.values() if row.get('value') == 'yes'), None) or unspecified
    unresolved = [key for key, row in facets.items() if row['status'] != 'answered']
    evidence = positive or next((row for row in reversed(list(facets.values())) if row.get('message_id')), {})
    return dict(status='answered' if positive or both else 'missing',
                value='yes' if positive else 'no' if both else '',
                asked=max((facets[key]['asked'] for key in unresolved), default=0),
                message_id=evidence.get('message_id', ''), quote=evidence.get('quote', ''),
                evidence_source='client_message' if evidence else '',
                hazard_facts=facets, unresolved_hazards=unresolved)


def manufacturer_tv_type(messages):
    """Decode a supplied Samsung UE model code using the manufacturer's legend.

    This establishes the display type only, not model existence, a diagnosis,
    repair price, or client consent. Keep its provenance distinct from speech.
    """
    source = 'https://www.samsung.com/at/support/tv-audio-video/was-bedeutet-der-modellcode-meines-fernsehers/'
    incoming = [m for m in messages if m.get('direction') == 'in'
                and m.get('sender_type') not in ('system', 'avito', 'operator', 'employee', 'assistant', 'bot')]
    text = '\n'.join(str(m.get('body') or '') for m in incoming)
    if re.search(r'монитор|ноутбук|смартфон|телефон|клавиатур|компьют|\bпк\b|'
                 r'\b(?:lg|philips|sony|hisense|haier|tcl)\b|\bне\s+(?:samsung|самсунг)', text, re.I):
        return None
    if re.search(r'\b\d{2}PFL[A-Z0-9]+(?:/\d{2})?(?![\w/])', text, re.I):
        return None  # A distinct supplied Philips code cannot become a Samsung TV.
    if any(m.get('media_reviewed') and (o := m.get('media_observation') or {}).get('source')
           in ('reviewed_image', 'offline_reviewed_image') and o.get('model')
           and not re.fullmatch(r'UE\d{2}[A-Z]{1,2}\d{4}[A-Z0-9]{0,8}', o['model'], re.I)
           for m in incoming):
        return None
    found = []
    for message in incoming:
        match = re.search(r'\b(?:samsung|самсунг)\s+(UE\d{2}[A-Z]{1,2}\d{4}[A-Z0-9]{0,8})(?!\w)',
                          str(message.get('body') or ''), re.I)
        if match:
            found.append((message, match))
    if len({match[1].upper() for _, match in found}) != 1:
        return None
    message, match = found[-1]
    return dict(status='answered', value='LED', model=match[1].upper(),
                message_id=message.get('id', ''), quote=message['body'][:500],
                evidence_source='manufacturer_model_code', manufacturer_source_url=source,
                interpretation='Samsung U = LED, E = European market; no diagnosis or exact product verification')


def printer_quality_evidence(messages):
    """Bind a literal print-quality symptom to the current client's printer.

    A percentage, a PDF screenshot, a quotation or a staff suggestion cannot
    supply this evidence. The symptom does not identify a faulty component.
    """
    printer_context = False
    result = None
    quality = (r'\b(?:бледн\w*|тускл\w*|размыт\w*|неч[её]тк\w*|смазанн\w*)\s+(?:печать|отпечат\w*)|'
               r'\b(?:плохо|бледно|тускло|размыто|неч[её]тко|смазанно)\s+печат\w*|'
               r'\b(?:печат\w*|пропечат\w*)\s+(?:очень\s+)?'
               r'(?:плохо|бледно|тускло|размыт\w*|неч[её]тк\w*|смазанн\w*)\b')
    for message in messages:
        if (message.get('direction') != 'in'
                or message.get('sender_type', 'client') not in ('client', 'customer', 'user', 'contact', 'lead', '')):
            continue
        source = message.get('body', '')
        body = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', lambda m: ' ' * len(m[0]), source)
        if re.search(r'новая\s+заявка|друг(?:ая|ой)\s+(?:проблема|техника)|теперь\s+(?:нужно|нужен|нужна)', body, re.I):
            printer_context = False
            result = None
        if re.search(r'\b(?:принтер|мфу)\w*', body, re.I) and not re.search(r'\bне\s+(?:принтер|мфу)', body, re.I):
            printer_context = True
        if not printer_context:
            continue
        for clause in re.finditer(r'[^.!?;\n]+', body):
            if re.search(r'\bесли\b|допустим|раньше|в\s+отзыв|в\s+инструкци|сосед|другой\s+мастер', clause[0], re.I):
                continue
            match = re.search(quality, clause[0], re.I)
            if not match:
                continue
            before, after = clause[0][:match.start()], clause[0][match.end():]
            if (re.search(r'\b(?:не|нет|без)\s*$', before, re.I)
                    or re.match(r'\s+(?:нет|больше\s+нет|не\s+наблюда\w*)\b', after, re.I)):
                result = None
                continue
            result = dict(kind='print_quality', value=source[clause.start()+match.start():clause.start()+match.end()],
                          message_id=message.get('id', ''), quote=source[:300], evidence_source='client_message')
    return result


def printer_consultation_question(messages):
    """A current question about a possible cause is not a diagnosis or job.

    Keep the question's source and following same-turn clarifications. A
    delivered staff reply ends this turn; old questions cannot override a
    later order, contact answer or new enquiry.
    """
    import assistant_prices
    current = assistant_prices.current_enquiry_messages(messages)
    resets = [index for index, message in enumerate(current)
              if message.get('direction') == 'in'
              and re.search(r'новая\s+заявка|друг(?:ая|ой)\s+(?:проблема|принтер|техника)|'
                            r'теперь\s+(?:нужно|нужен|нужна)',
                            re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', message.get('body', '')), re.I)]
    if resets:
        current = current[resets[-1]:]
    if not current or current[-1].get('direction') != 'in':
        return None
    clients = [m for m in current if m.get('direction') == 'in'
               and m.get('sender_type', 'client') in ('client', 'customer', 'user', 'contact', 'lead', '')]
    mask = lambda text: re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', text)
    if not any(re.search(r'\b(?:принтер|мфу)\w*', mask(m.get('body', '')), re.I) for m in clients):
        return None
    turn = []
    for message in reversed(current):
        if message.get('direction') == 'out':
            break
        if message in clients:
            turn.append(message)
    turn.reverse()
    bodies = [mask(m.get('body', '')) for m in turn]
    combined = '\n'.join(bodies)
    for clause in re.split(r'[.!?;\n]+', combined):
        if re.search(r'\b(?:может|если|стоит|ли)\b', clause, re.I):
            continue
        for request in re.finditer(r'\b(?:переустановите|установите|настройте|подключите)\b|'
                                   r'\b(?:нужно|надо|хочу|прошу)\s+(?:вам\s+)?'
                                   r'(?:переустановить|установить|настроить|подключить)\b', clause, re.I):
            if not re.search(r'\bне\s*$', clause[:request.start()], re.I):
                return None
    for message, body in reversed(list(zip(turn, bodies))):
        if re.search(r'\b(?:ноутбук|видеокарт|телевизор|стиральн)\w*', body, re.I):
            return None
        if re.search(r'\b(?:может\s+ли\s+быть|что\s+может\s+быть|в\s+ч[её]м\s+(?:может\s+быть\s+)?причин\w*|'
                     r'может\s+(?:быть\s+)?(?:стоит|надо)|хотел\w*\s+(?:просто\s+)?проконсультиров\w*)\b', body, re.I):
            return dict(kind='possible_cause_consultation', message_id=message.get('id', ''),
                        quote=message.get('body', ''), current_client_message_ids=[m.get('id', '') for m in turn],
                        diagnosis_established=False, evidence_source='client_question')
    return None


def toilet_type_answer(messages):
    """Fixture labels from the client or a delivered, unambiguous question."""
    from contact_facts import preceding_staff_speech
    noun = r'\b(?:унитаз|биде|писсуар)\w*\b'
    labels = {'floorstanding': r'\bнапольн\w*\b', 'ordinary': r'\bобычн\w*\b',
              'installation': r'\b(?:инсталляц|инсталирован|инсталлирован)\w*\b'}
    label_pattern = '|'.join(labels.values())
    other = r'покрыти|светиль|плинтус|ламп|смесител|программ|компьютер|\bэтаж\b'
    row = dict(status='missing',value='',asked=0,type_labels=[],excluded_type_labels=[])
    client = lambda m: (m.get('direction') == 'in' and m.get('sender_type','client')
                         in ('client','customer','user','contact','lead',''))
    for index,message in enumerate(messages):
        if not client(message):
            continue
        body = str(message.get('body') or '').strip()
        literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"',lambda m:' '*len(m[0]),body)
        if re.search(r'\bновая\s+заявка\b|\bдруг(?:ой|ая)\s+(?:заказ|заявка)\b',literal,re.I):
            row = dict(status='missing',value='',asked=0,type_labels=[],excluded_type_labels=[])
        previous = preceding_staff_speech(messages,index)
        prompt = previous[1].get('body','') if previous else ''
        prior_subject = bool(previous and any(client(m) and re.search(noun,m.get('body',''),re.I)
                                             for m in messages[:previous[0]]))
        actual_question = bool(previous and prompt.count('?') == 1
            and not re.search(r'[«»“”"]|куплен|материал|светиль|плинтус|\bэтаж\b',prompt,re.I)
            and (re.search(noun,prompt,re.I) or prior_subject)
            and re.search(label_pattern+r'|\b(?:тип|какой|вид)\b',prompt,re.I))
        if actual_question:
            row['asked'] += 1
        reported = bool(re.search(r'\b(?:сказал|говорил|написал|спросил)\w*\b|'
                                  r'\bу\s+(?:сосед\w*|друг\w*|знаком\w*)\b',literal,re.I))
        if reported:
            continue
        stated_subject = bool(re.search(noun,literal,re.I))
        if actual_question and UNKNOWN.search(literal) and not re.search(label_pattern,literal,re.I):
            row.update(status='unavailable',value='',type_labels=[],excluded_type_labels=[],quote=body[:500],
                       message_id=message.get('id',''),evidence_source='client_message',
                       question_message_id=previous[1].get('id',''),question_quote=prompt[:500])
            continue
        if actual_question and YES.fullmatch(literal) and not re.search(r'\bили\b|\bи\b',prompt,re.I):
            found=[key for key,pattern in labels.items() if re.search(pattern,prompt,re.I)]
            if len(found)==1 and not re.search(r'\b(?:не|без|нет|нету|отсутств\w*)\s+',prompt,re.I):
                row.update(status='answered',value=prompt.rstrip('? ').strip(),type_labels=found,excluded_type_labels=[],
                    message_id=message.get('id',''),quote=body[:500],evidence_source='client_message',
                    question_message_id=previous[1].get('id',''),question_quote=prompt[:500])
            continue
        if actual_question and NO.fullmatch(literal):
            row.update(status='uncertain',value='',type_labels=[],excluded_type_labels=[],message_id=message.get('id',''),
                       quote=body[:500],evidence_source='client_message')
            continue
        previous_doubt = False
        for clause in re.split(r'[.;\n]+|,|\s+но\s+',literal,flags=re.I):
            doubt = bool(re.fullmatch(r'\s*(?:не\s+уверен\w*|кажется|вроде|наверн\w*|возможно)\s*',clause,re.I))
            if doubt:
                previous_doubt = True
                if row.get('message_id') == message.get('id'):
                    row.update(status='uncertain',type_labels=[])
                continue
            if (not (stated_subject or actual_question) or re.search(other,clause,re.I)
                    or not re.search(label_pattern,clause,re.I)):
                if clause.strip():
                    previous_doubt = False
                continue
            # A separately identified new fixture does not inherit the old
            # one's mounting type. Keep the new item's explicit words.
            if re.search(r'\bстар\w*\b',clause,re.I) and re.search(r'\bнов\w*\b',literal,re.I):
                continue
            uncertain = previous_doubt or re.search(r'\?|\b(?:если|вроде|кажется|возможно|наверн\w*|или|либо|будет|куплю|планирую)\b|'
                                                    r'не\s+(?:уверен\w*|знаю)',clause,re.I)
            previous_doubt = False
            found=[]
            excluded=[]
            for key,pattern in labels.items():
                for match in re.finditer(pattern,clause,re.I):
                    before,after=clause[:match.start()],clause[match.end():]
                    if (re.search(r'\b(?:не(?:\s+с)?|без|нет|нету|отсутств\w*)\s+$',before,re.I)
                            or re.match(r'\s+(?:нет|нету|отсутствует|не\s+нуж\w*)\b',after,re.I)):
                        excluded.append(key)
                        if re.match(r'\s+не\s+нуж\w*',after,re.I):
                            uncertain = True  # A preference is not actual absence.
                    else:
                        found.append(key)
            # Separate exclusions in the same literal answer do not erase
            # an explicitly positive ordinary/floorstanding label.
            if row.get('message_id') == message.get('id') and not uncertain:
                prior_positive=[key for key in row['type_labels'] if key not in excluded]
                prior_negative=[key for key in row['excluded_type_labels'] if key not in found]
                found=list(dict.fromkeys([*prior_positive,*found]))
                excluded=list(dict.fromkeys([*prior_negative,*excluded]))
            found=[label for label in found if label not in excluded]
            # Excluding installation answers that explicit alternative;
            # excluding floorstanding alone leaves the actual type open.
            resolved = bool(found or 'installation' in excluded)
            row.update(status='uncertain' if uncertain or not resolved else 'answered',
                       value=clause.strip()[:120],type_labels=[] if uncertain else found,
                       excluded_type_labels=[] if uncertain else excluded,
                       message_id=message.get('id',''),quote=body[:500],evidence_source='client_message',
                       question_message_id=previous[1].get('id','') if actual_question else '',
                       question_quote=prompt[:500] if actual_question else '')
    return row


def office_symptom_answer(messages):
    """An application symptom or an answer to its delivered question only."""
    from assistant_catalog import OFFICE_APPLICATION, office_fault_request
    row = dict(status='missing', value='', asked=0)
    question = None
    subject = False
    for message in messages:
        text = message.get('body', '')
        if message.get('direction') == 'out':
            if (_observed_staff_question(message)
                    and re.search(SPECS['office_symptom'][2], text, re.I)):
                question = message
                row['asked'] += 1
            continue
        if (not _answer_client(message) or message.get('role')in('system','assistant')
                or message.get('speaker_role','client')!='client'):
            continue
        if re.search(r'\bнов(?:ая|ый|ое)\s+(?:заявка|заказ|обращение)\b|\bдруг(?:ая|ой)\s+(?:проблема|компьютер)', text, re.I):
            row, question, subject = dict(status='missing', value='', asked=0), None, False
        literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', text)
        if re.search(r'\b(?:если|допустим|сказал\w*|говорит|написал\w*|по\s+словам)\b', literal, re.I):
            continue
        subject = subject or office_fault_request(literal)
        literal=re.sub(r'\bне\s+перестал[аои]?\s+(?:открываться|запускаться|работать|сохранять)\b',' ',literal,flags=re.I)
        detail = re.search(SPECS['office_symptom'][1], literal, re.I)
        if detail and (office_fault_request(literal) or subject and question):
            # A different named object cannot answer the Office question.
            if (re.search(r'принтер|картридж|двер|замок|холодильник', literal, re.I)
                    and not re.search(OFFICE_APPLICATION, literal, re.I)):
                continue
            row.update(status='answered', value=detail[0], message_id=message.get('id', ''),
                       quote=text[:300], evidence_source='client_message')
            if question:
                row.update(question_message_id=question.get('id', ''), question_quote=question['body'])
    return row


def _answer_client(message):
    return (message.get('direction') == 'in'
            and message.get('sender_type', 'client') in ('client', 'customer', 'user', 'contact', 'lead', '')
            and not message.get('out_pending')
            and message.get('delivery', message.get('delivery_status', 'delivered'))
            not in ('failed', 'error', 'pending', 'queued', 'sending', 'cancelled', 'canceled'))


def _observed_staff_question(message):
    """Question binding uses posted staff speech, never a pending send/event."""
    from assistant_prices import outgoing_reply_observed
    return (outgoing_reply_observed(message)
            and message.get('sender_type', 'operator')
            in ('operator', 'employee', 'human', 'assistant', 'bot', ''))


def observed_question_answers(messages):
    """Literal delivered question/answer pairs, separate from our next form."""
    import assistant_prices
    from contact_facts import preceding_staff_speech
    messages = assistant_prices.current_enquiry_messages(messages)
    result = []
    for index, message in enumerate(messages):
        if not _answer_client(message):
            continue
        previous = client_turn_question(messages, index)
        if not previous or not re.search(r'\?|каки|каким|подскаж|уточни', previous[1].get('body', ''), re.I):
            continue
        if previous[1].get('sender_type', 'operator') not in ('operator', 'employee', 'human', 'assistant', 'bot', ''):
            continue
        prompt = previous[1]['body']
        topics = [key for key, spec in SPECS.items() if re.search(spec[2], prompt, re.I)]
        literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', message.get('body', ''))
        scope = 'literal_client_turn_not_automatic_confirmation'
        if re.fullmatch(r'\s*(?:модел\w*|что\s+именно|в\s+смысле)[?!.;\s]*', literal, re.I):
            scope = 'client_clarification_question'
        elif 'place' in topics and re.match(r'\s*(?:в\s+)?(?:квартир|частн\w*\s+дом|организац)', literal, re.I):
            scope = 'worksite_type_not_geographic_location'
        result.append(dict(question_message_id=previous[1].get('id', ''),
            question_quote=prompt[:500], answer_message_id=message.get('id', ''),
            answer_quote=message.get('body', '')[:500], question_topics=topics,
            answer_scope=scope, source='server_literal_delivered_exchange',
            independent_model_understanding=False))
    return result[-6:]


def client_turn_question(messages, index):
    """A delivered question can cover several adjacent client fragments."""
    from contact_facts import preceding_staff_speech
    boundary = r'\bнов(?:ая\s+заявка|ый\s+заказ|ое\s+обращение)\b|^\s*а\s+ещ[её]\b'
    if re.search(boundary, messages[index].get('body', ''), re.I):
        return None
    for pos in range(index - 1, -1, -1):
        row = messages[pos]
        if row.get('direction') in ('system', 'note') or row.get('sender_type') in ('system', 'avito'):
            continue
        if _answer_client(row):
            body = row.get('body', '')
            if re.search(boundary, body, re.I) or ('?' in body and not re.fullmatch(
                    r'\s*(?:модел\w*|марк[аиу]?|что\s+именно|в\s+смысле)[?!.;\s]*', body, re.I)):
                return None
            continue
        return preceding_staff_speech(messages, pos + 1)
    return None


def contact_name_age_fragment(text):
    """One literal name and adult age, without claims about its speaker."""
    from contact_cities import city_by_name

    match = re.fullmatch(r'\s*([А-ЯЁ][а-яё]{1,39}(?:-[А-ЯЁ]?[а-яё]+)?),\s*'
                         r'(?:мне\s+)?(\d{2,3})\s+(?:лет|года?)\s*', text)
    if (not match or not 18 <= int(match[2]) <= 110 or city_by_name(match[1])
            or match[1].casefold() in {'да', 'нет', 'завтра', 'сегодня', 'хорошо', 'спасибо',
                                     'здравствуйте', 'понятно', 'конечно', 'только', 'есть'}):
        return None
    return match[1]


def contact_bundle_name(messages, index):
    """One unambiguous self-name in the client's own phone/address turn."""
    import contact_phone
    from contact_cities import city_by_name
    def ready_client(row):
        transcript = str(row.get('voice_transcript_status') or '').lower()
        return (_answer_client(row) and row.get('role') not in ('system', 'assistant')
                and row.get('speaker_role', 'client') == 'client'
                and (not transcript or transcript in ('ready', 'done', 'completed')))

    if not ready_client(messages[index]):
        return None
    turn = []
    for row in reversed(messages[:index + 1]):
        if row.get('direction') in ('system', 'note') or row.get('sender_type') in ('system', 'avito'):
            continue
        if not ready_client(row):
            break
        body = str(row.get('body') or '')
        turn.insert(0, row)
        if re.search(r'\bнов(?:ая\s+заявка|ый\s+заказ|ое\s+обращение)\b', body, re.I):
            break
    bundle = '\n'.join(row.get('body', '') for row in turn)
    if (not contact_phone.find_all(bundle)
            or not re.search(r'\b(?:улица|ул\.?|проспект|переулок|квартал)\b', bundle, re.I)
            or not re.search(r'\b(?:дом|д\.)\s*\d', bundle, re.I)
            or re.search(r'номер\s+(?:мастера|мужа|жены|соседа)|это\s+номер\s+не\s+мой|'
                         r'для\s+друг\w*\s+заказ\w*', bundle, re.I)):
        return None
    names = []
    for row in turn:
        body = row.get('body', '')
        # Explicit introductions keep their existing parser and correction
        # semantics; this helper only fills the previously unrecognized form.
        if re.search(r'меня\s+зовут|мо[её]\s+имя', body, re.I):
            return None
        literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', body)
        for fragment in re.split(r'[.;\n]', literal):
            name = contact_name_age_fragment(fragment) or fragment.strip()
            if (re.fullmatch(r'[А-ЯЁ][а-яё]{1,39}(?:-[А-ЯЁ]?[а-яё]+)?', name)
                    and name.casefold() not in {'да', 'нет', 'завтра', 'сегодня', 'хорошо', 'спасибо',
                                               'здравствуйте', 'понятно', 'конечно', 'только', 'есть'}
                    and not city_by_name(name)):
                names.append((name, row))
    if len(names) != 1:
        return None
    name, row = names[0]
    return dict(status='answered', value=name, message_id=row.get('id', ''),
                quote=row.get('body', '')[:500], evidence_source='client_contact_bundle')


def name_reply_fragment(messages, index):
    """A self-name sentence answering our delivered name question."""
    from contact_cities import city_by_name
    message = messages[index]
    if (not _answer_client(message) or message.get('role') in ('system', 'assistant')
            or message.get('speaker_role', 'client') != 'client'):
        return None
    previous = client_turn_question(messages, index)
    if not previous:
        return None
    prompt = previous[1].get('body', '')
    if (prompt.count('?') != 1 or not re.search(SPECS['client_name'][2], prompt, re.I)
            or previous[1].get('sender_type', 'operator') not in ('operator', 'employee', 'human', 'assistant', 'bot', '')
            or previous[1].get('role') == 'system'
            or re.search(r'телефон|адрес|город|как\s+(?:мастера|мужа|жену|соседа)', prompt, re.I)):
        return None
    body = message.get('body', '')
    if re.search(r'[«»“”"]|\b(?:новая\s+заявка|новый\s+заказ|не|нет|вместо|'
                 r'муж|жена|сосед\w*|сказал\w*|говорит|зовут)\b', body, re.I):
        return None
    names = []
    for sentence in re.split(r'[.;\n]', body):
        name = sentence.strip()
        if (re.fullmatch(r'[А-ЯЁ][а-яё]{1,39}(?:-[А-ЯЁ]?[а-яё]+)?(?:\s+[А-ЯЁ][а-яё]{1,39}){0,2}', name)
                and name.casefold() not in {'да', 'нет', 'завтра', 'сегодня', 'хорошо', 'спасибо',
                    'здравствуйте', 'понятно', 'конечно', 'только', 'есть', 'подождите', 'секунду',
                    'улица', 'номер', 'адрес', 'согласен', 'согласна'}
                and not city_by_name(name)):
            names.append(name)
    if len(names) != 1:
        return None
    return dict(status='answered', value=names[0], message_id=message.get('id', ''),
                question_message_id=previous[1].get('id', ''), question_quote=prompt[:500],
                quote=body[:500], evidence_source='client_answer_to_name_question')


def client_question_clarification(messages):
    """Explain a short question about a delivered printer-identification prompt."""
    import assistant_prices
    from contact_facts import preceding_staff_speech
    messages = assistant_prices.current_enquiry_messages(messages)
    if not messages or not _answer_client(messages[-1]):
        return None
    message = messages[-1]
    if not re.fullmatch(r'\s*(?:модел\w*|марк[аиу]?|что\s+именно|в\s+смысле)[?!.;\s]*',
                        message.get('body', ''), re.I):
        return None
    previous = preceding_staff_speech(messages, len(messages) - 1)
    if (not previous or previous[1].get('sender_type', 'operator') not in
            ('operator', 'employee', 'human', 'assistant', 'bot', '')
            or not re.search(r'\?|каки|каким|подскаж', previous[1].get('body', ''), re.I)
            or not re.search(r'пр\w*интер|мфу', previous[1].get('body', ''), re.I)):
        return None
    return dict(question_message_id=previous[1].get('id', ''), question_quote=previous[1]['body'][:500],
                answer_message_id=message.get('id', ''), answer_quote=message['body'],
                reply='Подскажите марки и модели принтеров.',
                source='literal_client_clarification_of_delivered_question')


def first_person_home_responsibility(text):
    """Recognize a complete literal statement of three independent conditions."""
    return re.fullmatch(
        r'\s*я\s+(?P<decision>принимаю\s+решени[ея]),\s*'
        r'(?:сам[а]?\s+)?(?P<payment>плачу|оплачиваю)\s+и\s+(?P<presence>буду\s+дома|дома\s+буду)[.!]?\s*',
        text, re.I)


def responsibility_components(messages):
    """Three independently sourced conditions; a partial answer is not all three."""
    from contact_facts import preceding_staff_speech, tv_mount_work_volume
    components = {}
    asked_ids = set()
    residential = False
    office = False
    onsite_question = False
    home_presence = r'\b(?:(?:я\s+)?буду\s+дома|дома\s+буду(?:\s+я)?(?=\s*(?:[,.!?;\n]|$)))\b'
    self_work_agreement = (r'\b(?:я\s+(?:сам[а]?\s+)?|сам[а]?\s+)согласую\s+(?:все\s+)?'
                           r'(?:работы|ремонт|смету)(?=\s*(?:[,.;!?]|$)|'
                           r'\s+и\s+(?:сам[а]?\s+)?(?:оплачу|оплачиваю)\b)')
    subjects = dict(
        decision=r'\bреша(?:ю|ть)\b|\bрешени[ея]\b',
        payment=r'\bопла(?:ч|т)\w*|\bплатить\b',
        presence=r'\bна\s+месте\b|\bприсутств\w*|' + home_presence
                 + r'|\b(?:будет\s+дома|дома\s+будет)\b')
    positive = dict(
        decision=r'\bрешаю\b|\bрешени[ея]\s+(?:по\s+работам\s+)?(?:принимаю|приму)\b|'
                 r'\bя\s+(?:сам[а]?\s+)?(?:принимаю|приму)\s+решени[ея]\b|\bсогласовываю\b|'
                 + self_work_agreement,
        payment=r'\b(?:оплачиваю|оплачу)\b|\b(?:оплачивать|платить)\s+буду\b',
        presence=r'\bбуду\s+(?:сам[а]?\s+)?на\s+месте\b|\bна\s+месте\s+буду\b|'
                 r'\b(?:я\s+)?буду\s+присутствовать\b')
    seen = False
    for index, message in enumerate(messages):
        body = message.get('body', '')
        if message.get('direction') == 'out':
            if (not message.get('out_pending') and message.get('delivery', message.get('delivery_status', 'delivered'))
                    not in ('failed', 'pending', 'sending', 'error', 'queued')
                    and message.get('sender_type', 'operator') in ('operator', 'employee', 'human', 'assistant', 'bot', '')):
                onsite_question = onsite_question or bool(re.search(r'на\s+месте|выезд|выезжа|адрес\s+к\s+клиенту', body, re.I))
                if re.search(SPECS['decision_maker'][2], body, re.I):
                    asked_ids.add(index)
            continue
        if (not _answer_client(message) or message.get('role') in ('system', 'assistant')
                or message.get('speaker_role', 'client') != 'client'
                or (message.get('voice_transcript_status')
                    and message['voice_transcript_status'] not in ('ready', 'done', 'completed'))):
            continue
        literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', body)
        if re.search(r'\bнов(?:ая\s+заявка|ый\s+заказ|ое\s+обращение)\b', literal, re.I):
            components, asked_ids = {}, set()
            residential = office = onsite_question = False
            seen = True
        residential = residential or bool(re.search(r'\b(?:в\s+квартире|в\s+частном\s+доме|у\s+меня\s+дома)\b', literal, re.I))
        office = office or bool(re.search(r'\b(?:в\s+организации|в\s+офисе|на\s+предприятии)\b', literal, re.I))
        home_computer = re.search(
            r'(?:^|[.!?;\n])\s*это\s+(?:мой\s+)?домашний\s+(?:ноутбук|компьютер|пк)\b', literal, re.I
        ) and not re.search(r'\b(?:в\s+сервис(?:ном\s+центре|е)|в\s+мастерской|по\s+другому\s+адресу)\b',
                            literal, re.I)
        cabinet_intake = bool(re.search(
            r'(?:^|[.!;\n])\s*(?:собрать\s+(?:нужно|надо)|(?:нужно|надо)\s+собрать)'
            r'\s+один\s+шкаф\s*(?:[.!;\n]|$)', literal, re.I
        ) and not re.search(r'\b(?:на\s+даче|в\s+сервисе|в\s+мастерской|у\s+сосед\w*|'
                            r'по\s+другому\s+адресу)\b', literal, re.I))
        previous = preceding_staff_speech(messages, index)
        if previous and YES.fullmatch(literal.strip()):
            prompt = previous[1].get('body', '')
            if '?' in prompt and not re.search(r'\bне\b|\bили\b', prompt, re.I):
                for key, topic in subjects.items():
                    if re.search(topic, prompt, re.I):
                        components[key] = dict(status='confirmed', message_id=message.get('id', ''),
                            value=literal.strip(), quote=body[:300], question_message_id=previous[1].get('id', ''),
                            question_quote=prompt[:500], source='client_answer_to_delivered_question')
                        seen = True
        for sentence in re.findall(r'[^.!?;\n]+[.!?;]?', literal):
            if re.search(r'\b(?:сказал\w*|говорит|написал\w*|по\s+словам)\b', sentence, re.I):
                continue
            direct = first_person_home_responsibility(sentence)
            if direct and not office:
                for key, value in direct.groupdict().items():
                    components[key] = dict(status='confirmed', message_id=message.get('id', ''),
                        value=value, quote=body[:300], source='client_literal_component')
                seen = True
                continue
            for key, topic in subjects.items():
                # Only client statements gain this vocabulary. A short
                # "yes" to a schedule question must not confirm work rights.
                if key == 'decision':
                    topic += r'|\bсогласовыва(?:ю|ет)\b|' + self_work_agreement
                if not re.search(topic, sentence, re.I):
                    continue
                parts = [part for part in re.findall(r'[^,]+,?', sentence)
                         if re.search(topic, part, re.I)
                         or re.fullmatch(r'\s*(?:нет|если|вдруг|возможно|наверн\w*|кажется|не\s+уверен\w*)[,\s]*', part, re.I)]
                component_text = ' '.join(parts)
                uncertainty = re.search(r'\?|\b(?:если|вдруг|возможно|наверн\w*|кажется|не\s+уверен\w*|'
                                        r'попробую|постараюсь|смогу)\b', component_text, re.I)
                if (re.search(r'^\s*если\b', sentence, re.I)
                        or (key == 'presence' and re.search(r'\bдома\s+буду(?:\s+я)?\s*,\s*'
                                                            r'(?:если|но|только|возможно|при\s+условии)\b', sentence, re.I))):
                    uncertainty = True
                negative = re.search(r'\b(?:не|нет)\b', component_text, re.I)
                other_actor = re.search(r'\b(?:муж|жена|мама|папа|сосед\w*|начальник\w*|он|она|они|мы)\b',
                                        component_text, re.I)
                reassigned = (re.search(r'\bрешени[ея]\s+(?:теперь\s+)?принимает\b|\bоплачивает\b|'
                                        r'\bсогласовывает\b|'
                                        r'\b(?:будет\s+(?:на\s+месте|дома)|дома\s+будет)\b',
                                        component_text, re.I) and other_actor)
                if reassigned and key in components and not uncertainty:
                    components[key] = dict(status='withdrawn', message_id=message.get('id', ''),
                        quote=body[:300], source='client_literal_changed_actor')
                    seen = True
                    continue
                if other_actor:
                    continue
                # Unrelated negative clauses do not revoke this condition.
                relevant = re.search(positive[key], component_text, re.I)
                agreement_question = False
                if key == 'decision' and relevant and relevant[0].casefold() == 'согласовываю':
                    agreement_previous = previous or client_turn_question(messages, index)
                    prompt = agreement_previous[1].get('body', '') if agreement_previous else ''
                    agreement_question = bool(agreement_previous and _observed_staff_question(agreement_previous[1])
                        and prompt.count('?') == 1 and re.search(SPECS['decision_maker'][2], prompt, re.I)
                        and not re.search(r'\b(?:не|или)\b', prompt, re.I))
                    explicit_work = re.search(r'\bсогласовываю\s+(?:все\s+)?(?:работ|стоимост|смет|ремонт)\w*',
                                              component_text, re.I)
                    if (not explicit_work and (not agreement_question
                            or re.search(r'врем|график|дат[ау]|срок|доставк|покупк', component_text, re.I))):
                        continue
                    if re.search(r'\b(?:может|возможно|наверн\w*|кажется|допустим|предположим)\b', sentence, re.I):
                        uncertainty = True
                if not relevant and re.search(r'\b(?:я\s+буду|буду\s+я)\b', component_text, re.I):
                    shared_future = dict(decision=r'\bпринимать\s+решени[ея]\b',
                                         payment=r'\bоплачивать\b',
                                         presence=r'\bприсутствовать\b')
                    relevant = re.search(shared_future[key], component_text, re.I)
                if (key == 'decision' and relevant and relevant[0].casefold() == 'решаю'
                        and not re.search(r'опла|работ|ремонт', sentence, re.I)
                        and not (previous and re.search(SPECS['decision_maker'][2], previous[1].get('body', ''), re.I))):
                    continue
                if (key == 'payment' and re.search(r'креп[её]ж|материал|комплектующ|'
                        r'покупк|доставк|кофе|проезд', component_text, re.I)
                        and not re.search(r'\bработ\w*|\bремонт\w*|\bуслуг\w*', component_text, re.I)):
                    continue
                if key == 'presence' and not relevant and not office:
                    # A client can volunteer the three intake facts even when
                    # our preceding reply answered a different question.
                    home_intake = (
                        (home_computer or cabinet_intake or (re.search(r'\bдома\s+буду\s+я\b', sentence, re.I)
                                           and tv_mount_work_volume(messages[:index + 1])))
                        and re.search(positive['decision'], sentence, re.I)
                        and re.search(positive['payment'], sentence, re.I)
                        and re.search(r'\bи\s+(?:буду\s+дома|дома\s+буду\s+я)[.!]?\s*$', sentence, re.I)
                        and not re.search(r'\b(?:после|потом|позже|покупк\w*|материал\w*|доставк\w*|'
                                          r'друг\w*\s+адрес\w*|в\s+сервисе|в\s+мастерской)\b',
                                          sentence, re.I))
                    if residential or onsite_question or home_intake:
                        relevant = re.search(home_presence, component_text, re.I)
                if not relevant and not (negative or uncertainty):
                    continue
                if not re.search(r'\bя\b|буду|решаю|принимаю|приму|оплачу|оплачиваю|согласовываю|согласую', component_text, re.I):
                    continue
                status = 'uncertain' if uncertainty else 'withdrawn' if negative else 'confirmed'
                if relevant or key in components:
                    components[key] = dict(status=status, message_id=message.get('id', ''),
                        value=relevant[0] if relevant else '', quote=body[:300], source='client_literal_component')
                    if agreement_question:
                        components[key].update(question_message_id=agreement_previous[1].get('id', ''),
                                               question_quote=agreement_previous[1].get('body', '')[:500])
                    seen = True
    if not seen:
        return None
    confirmed = [key for key, row in components.items() if row['status'] == 'confirmed']
    missing = [key for key in subjects if key not in confirmed]
    latest = next(reversed(components.values()), {})
    return dict(status='answered' if not missing else 'uncertain' if any(
                    row['status'] != 'confirmed' for row in components.values()) else 'missing',
                value='; '.join(components[key].get('value', '') for key in confirmed)[:500],
                asked=len(asked_ids), components=components, missing_components=missing,
                message_id=latest.get('message_id', ''), quote=latest.get('quote', ''),
                evidence_source='client_message',
                responsibility_scope='client_stated_decision_payment_presence_not_booking')


def decision_responsibility_reply(messages, index):
    """First-person decision, payment responsibility and presence, not a visit."""
    message = messages[index]
    original = message.get('body', '')
    text = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', original)
    decision = re.search(r'\bрешени[ея]\s+(?:по\s+работам\s+)?(?:принимаю|приму)\b|'
                         r'\bя\s+(?:сам[а]?\s+)?(?:принимаю|приму)\s+решени[ея]\b', text, re.I)
    payment = re.search(r'\b(?:оплачиваю|оплачу)\s+(?:я|сам[а]?)\b|'
                        r'\bя\s+(?:сам[а]?\s+)?(?:оплачиваю|оплачу)\b', text, re.I)
    presence = re.search(r'\bбуду\s+на\s+месте\b|\bна\s+месте\s+буду\b|'
                         r'\bя\s+буду\s+присутствовать\b', text, re.I)
    if not all((decision, payment, presence)):
        return None
    result = dict(status='answered', value=text[:120], message_id=message.get('id', ''),
                  quote=original[:300], evidence_source='client_message',
                  responsibility_scope='client_stated_decision_payment_presence_not_booking')
    from contact_facts import preceding_staff_speech
    previous = preceding_staff_speech(messages, index)
    boundary = max((i for i, item in enumerate(messages[:index + 1])
                    if item.get('direction') == 'in' and item.get('sender_type', 'client') in
                        ('client', 'customer', 'user', 'contact', 'lead', '')
                    and re.search(r'\bнов(?:ая\s+заявка|ый\s+заказ|ое\s+обращение)\b',
                                  re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', item.get('body', '')), re.I)), default=-1)
    if (previous and previous[0] > boundary
            and re.search(SPECS['decision_maker'][2], previous[1].get('body', ''), re.I)):
        result.update(question_message_id=previous[1].get('id', ''),
                      question_quote=previous[1].get('body', '')[:300])
    return result


def instruction_evidence_text(text):
    """Present client statement, not a quoted promise or a question about it."""
    text = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', lambda m: ' ' * len(m[0]), text)
    parts = []
    for sentence in re.findall(r'[^.!?;\n]+[.!?;]?', text):
        if re.search(r'схем|инструкц', sentence, re.I) and (
                sentence.rstrip().endswith('?')
                or re.search(r'\b(?:если|вдруг|возможно|наверн\w*|кажется|не\s+уверен\w*|'
                             r'будет|будут|завтра|привезут|куплю|пришлют|раньше|вчера|'
                             r'сказал\w*|говорит|написал\w*|по\s+словам)\b|'
                             r'\b(?:от|для)\s+(?:друг\w*|стар\w*)\s+(?:шкаф\w*|заказ\w*|мебел\w*|комод\w*)', sentence, re.I)):
            parts.append(' ' * len(sentence))
        else:
            parts.append(sentence)
    return ''.join(parts)


def explicit_one_work(message):
    """An explicit single requested item, with the client's source retained."""
    if (not _answer_client(message) or message.get('role') in ('system', 'assistant')
            or message.get('speaker_role', 'client') != 'client'
            or (message.get('voice_transcript_status')
                and message['voice_transcript_status'] not in ('ready', 'done', 'completed'))):
        return None
    text = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', lambda m: ' ' * len(m[0]), message['body'])
    for clause in re.findall(r'[^.!?;\n]+[.!?;]?', text):
        if re.search(r'\b(?:если|вдруг|возможно|кажется|или|либо|наверн\w*|не|нет|сказал\w*|'
                     r'написал\w*|сосед\w*|мастер\w*|сам|сами|раньше|вчера)\b', clause, re.I):
            continue
        if '?' in clause and not re.search(r'\b(?:сколько\s+стоит|цен[ау]|стоимость)\b',clause,re.I):
            continue
        match = re.search(r'\b(?:заменить|замена|установить|установка|повесить|навесить)\s+'
                          r'один\s+(?:розет|выключ|полк|светиль|карниз|смесител|люстр|двер|шкаф)\w*',
                          clause, re.I)
        if match:
            return match
        siphon = re.search(r'\b(?:заменить|поменять|установить)\s+один\s+сифон\b|'
                           r'\b(?:замена|установка)\s+одного\s+сифона\b', clause, re.I)
        if siphon:
            return siphon
        basin = re.search(r'\b(?:заменить|поменять|установить)\s+одну\s+раковину\b|'
                          r'\b(?:замена|установка)\s+одной\s+раковины\b', clause, re.I)
        if basin and not re.search(r'\b(?:смесител\w*|сифон\w*|кран\w*|унитаз\w*|мойк\w*|ванну)\b', clause, re.I):
            return basin
        assembly = re.search(r'^\s*(?:(?:в\s+(?-i:[А-ЯЁ][а-яё-]+)\s+)?(?:нужно|надо|хочу|прошу)\s+)?'
                             r'собрать\s+(?:в\s+(?-i:[А-ЯЁ][а-яё-]+)\s+)?'
                             r'(?:один\s+(?:новый\s+)?(?:шкаф(?:-купе)?|комод|стеллаж)|'
                             r'одну\s+(?:(?:новую|прикроватную)\s+){0,2}тумбу)\b', clause, re.I)
        if not assembly:
            assembly = re.search(r'(?:^\s*|\b(?:нужно|надо|хочу|прошу)\s+)собрать\s+'
                                 r'(?:один\s+(?:[а-яё-]+(?:ый|ий|ой)\s+){0,3}стол|'
                                 r'(?:письменный|компьютерный|обеденный)\s+стол)\b',
                                 clause, re.I)
        if assembly and not re.search(r'\b(?:и|плюс|ещ[её]|также)\b', clause[assembly.end():], re.I):
            return assembly
    return None


def named_self_introduction(text):
    literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', lambda m: ' ' * len(m[0]), text)
    matches = list(re.finditer(r'(?:^|(?<=[.!;\n]))\s*[Яя]\s+(?P<name>[А-ЯЁ][а-яё-]{1,39})'
                               r',\s*(?P<age>[1-9]\d{0,2})\s+(?i:лет|год[а]?)(?=\s*(?:[.!;\n]|$))',
                               literal))
    return matches[-1] if matches and int(matches[-1]['age']) <= 120 else None


def _self_introduction_evidence(message):
    transcript = str(message.get('voice_transcript_status') or '').lower()
    if (not _answer_client(message) or message.get('role') in ('system', 'assistant')
            or message.get('speaker_role', 'client') != 'client'
            or (transcript and transcript not in ('ready', 'done', 'completed'))):
        return None
    return named_self_introduction((message.get('body') or '').strip())


def client_name_evidence_text(text, *, allow_denial=False):
    """Keep literal self-introductions, retaining original quote offsets."""
    text = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', lambda m: ' ' * len(m[0]), text)
    def literal_sentence(found):
        sentence = found[0]
        if re.search(r'меня\s+зовут|мо[её]\s+имя|\bэто\s+я\b', sentence, re.I) and (
                sentence.rstrip().endswith('?')
                or re.search(r'\b(?:если|вдруг|возможно|наверн\w*|кажется|не\s+уверен\w*|'
                             r'сказал\w*|говорит|написал\w*|цитирую|по\s+словам|раньше|вчера)\b', sentence, re.I)
                or not allow_denial and re.search(
                    r'\bне\s+(?:меня\s+зовут|мо[её]\s+имя)|'
                    r'(?:меня\s+зовут|мо[её]\s+имя)\s+(?:не|нет)\b', sentence, re.I)):
            return ' ' * len(sentence)
        return sentence
    return re.sub(r'[^.!?;\n]+[.!?;]?', literal_sentence, text)


def client_name_value(fact, source):
    """The same qualified source name for form preparation and its CRM gate."""
    if fact.get('status') != 'answered':
        return ''
    literal = client_name_evidence_text(source.get('body', ''))
    matches = list(re.finditer(r'(?:меня\s+зовут|мо[её]\s+имя|это\s+я)\s+([а-яёa-z-]{2,40})', literal, re.I))
    introduction = named_self_introduction(literal)
    if introduction and (not matches or introduction.start() >= matches[-1].start()):
        return introduction['name']
    return matches[-1][1] if matches else str(fact.get('value') or '').strip()


def client_name_profile_value(fact, profile):
    """A profile cannot restore a name explicitly revoked by this client."""
    profile = str(profile or '')
    if fact.get('status') == 'uncertain' and fact.get('evidence_source') == 'client_name_denial':
        denied = str(fact.get('denied_name') or '')
        if fact.get('invalidated_name') or denied and re.search(
                r'(?<![а-яёa-z-])' + re.escape(denied) + r'(?![а-яёa-z-])', profile, re.I):
            return ''
    return profile


def reported_device_model(messages):
    """A named model may have spaces; contact numbers are not model evidence."""
    for message in reversed(messages):
        if (not _answer_client(message) or message.get('role') in ('system', 'assistant')
                or message.get('speaker_role', 'client') != 'client'):
            continue
        text = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', str(message.get('body') or ''))
        for clause in re.split(r'[.!?;\n]+', text):
            if re.search(r'\b(?:если|возможно|наверное|сосед\w*|сказал\w*|написал\w*|предложил\w*)\b', clause, re.I):
                continue
            match = re.search(r'\bмодель\s*[:—-]?\s*(?P<value>[a-zа-яё][a-zа-яё0-9-]{1,24}'
                              r'(?:\s+[a-zа-яё0-9][a-zа-яё0-9-]{0,24}){0,2})', clause, re.I)
            if (match and re.search(r'\d', match['value'])
                    and not re.search(r'\b\d{7,}\b|\b(?:не|знаю|будет|пока|телефон|номер|дом|квартира|руб\w*)\b',
                                      match['value'], re.I)):
                return dict(message_id=message.get('id', ''), value=match['value'],
                            quote=clause.strip(), evidence_source='client_message')
    return None


def appliance_water_symptom(messages):
    """A literal own-device observation, without diagnosing why water appeared."""
    for message in reversed(messages):
        if (not _answer_client(message) or message.get('role') in ('system', 'assistant')
                or message.get('speaker_role', 'client') != 'client'):
            continue
        text = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', str(message.get('body') or ''))
        for clause in re.split(r'[.!?;\n]+', text):
            if re.search(r'\b(?:если|допустим|сосед\w*|сказал\w*|написал\w*|предложил\w*)\b', clause, re.I):
                continue
            match = re.search(r'\b(?:стиральн\w*\s+машин\w*|посудомоечн\w*\s+машин\w*)'
                              r'\b[^.!?;\n]{0,55}\bвода\s+появил\w*\s+снизу\b', clause, re.I)
            if match:
                return dict(message_id=message.get('id', ''), value=match[0], quote=clause.strip(),
                            evidence_source='client_message')
    return None


def inspect(messages):
    import assistant_prices
    messages = assistant_prices.current_enquiry_messages(messages)
    tv_brackets = tv_mount_brackets(messages)
    state: dict[str, dict[str, Any]] = {}
    for key, (_, answer, asked, binary, _) in SPECS.items():
        if key == 'office_symptom':
            state[key] = office_symptom_answer(messages)
            continue
        if key == 'toilet_type':
            # A floorstanding fixture is a source label, not an apartment
            # floor or proof of the tank's construction. Do not let the
            # generic answer matcher borrow staff/other-item adjectives.
            state[key] = toilet_type_answer(messages)
            continue
        if key == 'problem':
            # Literal client symptoms, without inferring a cause or repair.
            answer += r'|перестал[аои]?\s+(?:включаться|запускаться|работать|печатать|сливать|охлаждать)\b|медленно\s+работ|\bтормозит\b|\b(?:завис|зависла|зависло|зависли|зависает)\b'
            answer += r'|\b(?:жу[её]т|заж[её]выва\w*|замина\w*)\s+бумаг\w*|\bскрипит\b'
        row: dict[str, Any] = {"status": "missing", "value": "", "asked": 0}
        for index, message in enumerate(messages):
            if message.get("direction") != "in":
                continue
            if key in ('client_name', 'visit_time') and (not _answer_client(message)
                    or message.get('role') in ('system', 'assistant')
                    or message.get('speaker_role', 'client') != 'client'):
                continue
            if key == 'instructions' and (not _answer_client(message)
                    or message.get('role') in ('system', 'assistant')
                    or message.get('speaker_role', 'client') != 'client'):
                continue
            if key == 'client_name':
                denials = list(re.finditer(r'(?:меня\s+зовут|мо[её]\s+имя)\s+не\s+([а-яёa-z-]{2,40})',
                                          client_name_evidence_text(message['body'].strip(), allow_denial=True), re.I))
                denial = denials[-1] if denials else None
                if denial:
                    prior = next((m for m in messages[:index] if m.get('id') == row.get('message_id')), {})
                    current_name = client_name_value(row, prior)
                    if not current_name or current_name.casefold() == denial[1].casefold():
                        row.update(status='uncertain', value='', message_id=message.get('id', ''),
                                   quote=message['body'][:300], evidence_source='client_name_denial',
                                   invalidated_name=bool(current_name), denied_name=denial[1])
                bundled_name = contact_bundle_name(messages, index)
                if bundled_name:
                    row.update(bundled_name)
                    row.pop('invalidated_name', None)
                    row.pop('denied_name', None)
                    continue
                fragment_name = name_reply_fragment(messages, index)
                if fragment_name:
                    row.update(fragment_name)
                    row.pop('invalidated_name', None)
                    row.pop('denied_name', None)
                    continue
            if key in ('software_use', 'printer_connection', 'instructions') and message.get('sender_type', 'client') not in (
                    'client', 'customer', 'user', 'contact', 'lead', ''):
                continue
            text = message["body"].strip()
            if key in ('instructions', 'materials', 'client_name', 'visit_time') and re.search(
                    r'\bнов(?:ая\s+заявка|ый\s+заказ|ое\s+обращение)\b',
                    re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', text), re.I):
                row = dict(status='missing', value='', asked=0)
            if key == 'decision_maker':
                # A third person's promise, quotation or tentative future
                # does not establish this client's responsibility/presence.
                if message.get('sender_type', 'client') not in ('client', 'customer', 'user', 'contact', 'lead', ''):
                    continue
                decision_literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', text)
                if re.search(r'\bнов(?:ая\s+заявка|ый\s+заказ|ое\s+обращение)\b', decision_literal, re.I):
                    row = dict(status='missing', value='', asked=0)
                lpr_terms = r'решени|оплат|оплач|оплачу|месте|присутств'
                lpr_clauses = []
                for sentence in re.findall(r'[^.!?;\n]+[.!?;]?', decision_literal):
                    if not re.search(lpr_terms, sentence, re.I):
                        continue
                    for clause in re.findall(r'[^,]+,?', sentence):
                        if (re.search(lpr_terms, clause, re.I)
                                or re.search(r'сказал\w*|говорит|написал\w*|по\s+словам', clause, re.I)
                                or re.fullmatch(r'\s*(?:нет|возможно|наверн\w*|кажется|если|не\s+уверен\w*)[,\s]*', clause, re.I)):
                            lpr_clauses.append(clause)
                lpr_text = ' '.join(lpr_clauses)
                if re.search(r'сказал\w*|говорит|написал\w*|по\s+словам', lpr_text, re.I):
                    continue
                if re.search(r'[?«»“”"]|\b(?:не|нет|если|вдруг|возможно|наверн\w*|кажется|'
                             r'попробую|постараюсь|смогу|сказал\w*|говорит|написал\w*|'
                             r'муж|жена|мама|папа|сосед\w*|начальник\w*|он|она|они|мы)\b', lpr_text, re.I):
                    if row['status'] == 'answered' and lpr_text:
                        row = dict(status='uncertain', value='', asked=row['asked'],
                                   message_id=message.get('id', ''), quote=text[:300], evidence_source='client_message')
                    continue
                responsibility = decision_responsibility_reply(messages, index)
                if responsibility:
                    row.update(responsibility)
                    continue
            if key == 'visit_time':
                from contact_facts import client_visit_range, confirmed_visit_daypart, named_visit_preference, VISIT_RANGE
                named = named_visit_preference(messages,index)
                if named:
                    row.update(status='answered' if named['status']=='requested' and not named['requires_clarification'] else 'uncertain',
                               value=named['window'],quote=text[:300],message_id=message.get('id',''),
                               evidence_source='client_message',requires_clarification=named['requires_clarification'],
                               clarification_kind=named.get('clarification_kind',''),range_source=named)
                    for field in ('question_message_id','question_quote'):
                        row.pop(field,None)
                    continue
                clarified = confirmed_visit_daypart(messages, index, row.get('range_source', {}))
                if clarified:
                    row.update(status='answered', value=clarified['window'], quote=text[:300],
                               message_id=message.get('id', ''), requires_clarification=False,
                               clarification_kind='', range_source=clarified,
                               question_message_id=clarified['question_message_id'],
                               question_quote=clarified['question_quote'], evidence_source='client_message')
                    continue
                if VISIT_RANGE.search(text):
                    period = client_visit_range(messages, index)
                    if period:
                        row.update(status='uncertain' if period['requires_clarification'] else 'answered',
                                   value=period['window'], quote=text[:300],
                                   message_id=message.get('id', ''), evidence_source='client_message',
                                   requires_clarification=period['requires_clarification'],
                                   clarification_kind=period['clarification_kind'],
                                   range_source=period)
                        if period.get('question_message_id'):
                            row.update(question_message_id=period['question_message_id'],
                                       question_quote=period['question_quote'])
                    # Do not fall back to a truncated first clock, including
                    # ranges about a call, purchase or someone else's visit.
                    continue
            import research_vision
            model_observation=research_vision.qualification_observation(message)
            observation = (message.get('media_observation') if message.get('media_reviewed') else None) or model_observation
            model_observation = observation if observation is model_observation else None
            if observation and observation.get('source') in ('reviewed_image','offline_reviewed_image','model_reviewed_image'):
                value = observation.get('model') if key == 'model' else ('Схема на просмотренном изображении' if key == 'instructions' and observation.get('content_kind') == 'assembly_diagram' else '')
                if model_observation:
                    value=(observation.get('model','') if key=='model' else
                           observation.get('instructions','') if key=='instructions' else '')
                if key == 'cable_type' and observation.get('connector_type') == 'RJ45' and observation.get('device_kind') == 'ethernet_cable':
                    value = 'RJ45 — сетевой кабель с просмотренного изображения'
                if key=='problem' and observation.get('content_kind')=='device_message' and observation.get('error_code'):
                    value='Сообщение устройства '+observation['error_system']+', код '+observation['error_code']
                if key == 'furniture_problem':
                    import personal_media
                    if observation.get('visible_symptom') in personal_media.FURNITURE_SIGNS:
                        value = personal_media.FURNITURE_SIGNS[observation['visible_symptom']][1]
                if value:
                    if (model_observation and key=='model' and row['status']=='answered'
                            and re.sub(r'\W','',row['value']).casefold()!=re.sub(r'\W','',value).casefold()):
                        row.update(status='uncertain',value='',image_model_conflict=True,
                            model_media_evidence={k:observation[k] for k in ('message_id','media_id','signature','sha256','job')})
                        continue
                    row.update(status='answered',value=value,message_id=message.get('id',''),quote=value,evidence_source=observation['source'])
                    if model_observation:
                        row.update(not_client_literal_statement=True,human_media_review=False,
                            model_media_evidence={k:observation[k] for k in ('message_id','media_id','signature','sha256','job')})
            if key == 'instructions' and re.fullmatch(r'\s*(?:вот|это|держите)?\s*(?:инструкци\w*|схема)(?:\s+сборки)?[.!\s]*',text,re.IGNORECASE):
                image = message if observation else (messages[index-1] if index and messages[index-1].get('direction')=='in' else {})
                seen = ((image.get('media_observation') if image.get('media_reviewed') else None)
                        or research_vision.qualification_observation(image))
                if seen and seen.get('content_kind') in ('product_photo','product_card','device_label'):
                    continue
            material_text = (material_statements(text) if key == 'materials' else
                             instruction_evidence_text(text) if key == 'instructions' else
                             client_name_evidence_text(text) if key == 'client_name' else
                             decision_literal if key == 'decision_maker' else text)
            if key == 'problem' and re.search(r'домофон', text, re.I) and re.search(r'позвон|спущусь|открою', text, re.I) and not re.search(r'ремонт|почин|замен|установ', text, re.I):
                # Keep the original quote/offsets; an access condition is not
                # the fault of the appliance being serviced.
                material_text = re.sub(r'\bдомофон\w*\s+(?:не\s+работ\w*|сломан\w*)|'
                                       r'\bне\s+работ\w*\s+домофон\w*',
                                       lambda match: ' ' * len(match[0]), text, flags=re.I)
            match = answer_match(key, answer, material_text)
            if key == 'client_name':
                introduction = _self_introduction_evidence(message)
                if introduction and (not match or introduction.start() >= match.start()):
                    match = introduction
            if key == 'client_name' and match and denial and denial.start() > match.start():
                positive = client_name_value(dict(status='answered', value=match[0]), dict(body=match[0]))
                if positive.casefold() == denial[1].casefold():
                    row.update(status='uncertain', value='', message_id=message.get('id', ''),
                               quote=text[:300], evidence_source='client_name_denial',
                               invalidated_name=True, denied_name=denial[1])
                    match = None
            if key == 'materials' and not match:
                inventory = voluntary_furniture_inventory(messages, index)
                if inventory:
                    forget_inventory_question(row)
                    row.update(inventory)
            if key == 'materials' and not match:
                contextual_reply = material_reply(messages, index)
                if contextual_reply:
                    forget_inventory_question(row)
                    row.update(contextual_reply)
            if key == 'materials' and not match:
                hanging_stock = hanging_inventory_reply(messages,index)
                if not hanging_stock:
                    hanging_stock = explicit_hanging_stock(messages,index)
                if not hanging_stock:
                    hanging_stock = tv_mount_client_stock(messages,index)
                if hanging_stock:
                    forget_inventory_question(row)
                    row.update(hanging_stock)
            if key == 'materials' and not match:
                hose = named_hose_material_match(text)
                if hose:
                    forget_inventory_question(row)
                    row.update(status='answered', value=hose[0], message_id=message.get('id', ''),
                               quote=text[:300], evidence_source='client_message',
                               availability_subject='шланг / подводка',
                               availability_scope='client_named_item_only')
            if key == 'materials' and not match:
                named_stock = named_client_stock(message) or basin_supply_statement(message)
                if named_stock:
                    forget_inventory_question(row)
                    row.update(named_stock)
            if key == 'materials' and not match:
                coordinated_stock = coordinated_client_stock(message)
                if coordinated_stock:
                    forget_inventory_question(row)
                    row.update(coordinated_stock)
            if key == 'materials' and not match:
                supply = siphon_supply_statement(message)
                if supply and supply.get('purchase_plan_cancelled'):
                    if row.get('availability_status') == 'planned_purchase':
                        forget_inventory_question(row)
                        row.update(status='missing', value='', message_id=message.get('id', ''),
                                   quote=text[:300], evidence_source='client_cancelled_purchase_plan')
                elif supply:
                    forget_inventory_question(row)
                    row.update(supply)
            if key == 'materials' and not match:
                # Preserve the customer's statement about the actual item.
                # This does not establish any unmentioned fitting or tool.
                purchased = re.search(
                    r'\b(?:смесител|кран|карниз|гардин|полк|турник|кронштейн|люстр|светиль|замок|ручк)\w*'
                    r'\s+(?:(?:уже|сами|все)\s+){0,2}(?:куплен\w*|в\s+наличии|есть)\b', material_text, re.I)
                if purchased and not (tv_brackets and re.match(r'кронштейн', purchased[0], re.I)):
                    forget_inventory_question(row)
                    row.update(status='answered', value=purchased[0], message_id=message.get('id', ''),
                               quote=text[:300], evidence_source='client_message')
            if key == 'materials' and not match and inventory_answer(text) is not None:
                prompt = next((m for m in reversed(messages[:index]) if m.get('direction') == 'out'), {})
                fitting = any(m.get('direction') == 'in' and re.search(r'ручк\w*|замок|замк', m['body'], re.I)
                              for m in messages[:index])
                prompt_sent = (not prompt.get('out_pending') and str(prompt.get('delivery_status') or '').lower()
                               not in ('pending', 'queued', 'sending', 'failed', 'error', 'cancelled', 'canceled'))
                named = re.fullmatch(r'\s*(?:а\s+)?(?P<item>замок|замки|ручка|ручки)\s+(?:у\s+вас\s+)?'
                                     r'(?:(?:в\s+наличии)(?:\s+уже)?|(?:уже\s+)?есть)\s*\?\s*',
                                     prompt.get('body', ''), re.I)
                subject = 'замок' if named and named['item'].casefold().startswith('зам') else 'ручка'
                subject_pattern = r'замок|замк' if subject == 'замок' else r'ручк'
                named_from_client = bool(named and any(m.get('direction') == 'in' and re.search(subject_pattern, m['body'], re.I)
                                                      for m in messages[:index]))
                pronoun = fitting and re.fullmatch(r'\s*(?:а\s+)?(?:у\s+вас\s+)?(?:она|он|они)\s+(?:в\s+наличии\s+)?(?:уже\s+)?есть\s*[?!.]*\s*', prompt.get('body', ''), re.I)
                if prompt_sent and (named_from_client or pronoun):
                    forget_inventory_question(row)
                    row.update(status='answered', value=inventory_answer(text),
                               message_id=message.get('id', ''), question_message_id=prompt.get('id', ''),
                               quote=text[:300], evidence_source='client_message')
                    if named_from_client:
                        row['availability_subject'] = subject  # Only this fitting, never all unmentioned supplies.
            if key == 'volume' and not match:
                explicit_one = explicit_one_work(message)
                if explicit_one:
                    row.update(status='answered', value=explicit_one[0], message_id=message.get('id', ''),
                               quote=text[:300], evidence_source='client_message',
                               volume_scope='client_named_single_item_only')
                hanging_work = singular_hanging_work(message)
                if hanging_work:
                    row.update(status='answered', value=hanging_work[0].strip(), message_id=message.get('id', ''),
                               quote=text[:300], evidence_source='client_message',
                               volume_scope='client_named_hanging_item_only')
                hose_work = named_hose_work_match(text)
                if hose_work:
                    row.update(status='answered', value=hose_work[0], message_id=message.get('id', ''),
                               quote=text[:300], evidence_source='client_message',
                               volume_scope='client_named_hose_only')
                singular = re.search(r'\b(?:заменить|замена)\s+(?:(?:в\s+)?(?:межкомнатной|входной)\s+двери\s+)?ручк[уа]\b', text, re.I)
                if singular and not re.search(r'\b(?:не\s+нуж|несколько|ручки|ручек)\b', text, re.I):
                    row.update(status='answered', value=singular[0], message_id=message.get('id', ''),
                               quote=text[:300], evidence_source='client_message')
            if key == 'materials' and re.search(
                    r'\b(?:фанер|плинтус|материал|комплектующ|шуруп|саморез)\w*\s+(?:ещ[её]\s+)?(?:нет|нету)\b', material_text, re.I):
                forget_inventory_question(row)
                row.update(status='answered',value='no',message_id=message.get('id',''),quote=text[:300],evidence_source='client_message')
            if (key == 'materials' and _answer_client(message)
                    and message.get('role') not in ('system', 'assistant')
                    and message.get('speaker_role', 'client') == 'client'):
                literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', lambda m: ' ' * len(m[0]), material_text)
                statements = [s for s in re.split(r'[.!?;\n]', literal) if not re.search(
                    r'\b(?:если|вдруг|возможно|кажется|сосед\w*|мастер\w*|сказал\w*|написал\w*)\b|'
                    r'\bдля\s+друг\w*\s+(?:заказ|шкаф|комод)\w*', s, re.I)]
                missing = re.search(r'\b(?:креплен\w*|креп[её]ж\w*)\s+(?:ещ[её]\s+)?(?:нет|нету)\b', ' '.join(statements), re.I)
                if missing:
                    forget_inventory_question(row)
                    row.update(status='answered', value='no', message_id=message.get('id',''), quote=text[:300],
                               evidence_source='client_message', availability_scope='client_named_item_only',
                               availability_subject=missing[0].split()[0])
                    # A broad "materials present" match cannot overwrite
                    # the explicitly absent named fitting later in this row.
                    match = None
            if (key in ('pipe_material', 'countertop_material') and index
                    and messages[index-1].get('direction') == 'in'
                    and row.get('message_id') == messages[index-1].get('id')
                    and re.fullmatch(r'(?:вроде(?:\s+как)?|кажется|не\s+уверен\w*|скорее\s+всего)[.!\s]*', text, re.IGNORECASE)):
                row.update(status='uncertain', value=(row['value'] + ' — ' + text)[:120], message_id=message.get('id', ''))
            if key == 'materials':
                uncertainty = hanging_inventory_uncertainty(message, row)
                if uncertainty:
                    forget_inventory_question(row)
                    row.update(uncertainty)
                    match = None
            if match:
                if key == 'client_name':
                    row.pop('invalidated_name', None)
                    row.pop('denied_name', None)
                if key == 'materials':
                    forget_inventory_question(row)
                if key == 'visit_time':
                    for field in ('range_source', 'requires_clarification', 'clarification_kind',
                                  'question_message_id', 'question_quote'):
                        row.pop(field, None)
                row.update(
                    status="answered",
                    value=(
                        match.group(0)
                        if key in ("model", "software_use") or key == "problem" and match.lastgroup in ("adf_cover", "dry_ink", "paper_feed")
                        else text[max(0, match.start() - 4) : match.end()]
                    )[:120],
                    message_id=message.get("id", ""),
                    evidence_source='client_message', quote=text[:300],
                )
                if key in ("pipe_material", "countertop_material", "cable_type"):
                    uncertain = r"(?:скорее\s+всего|вроде|кажется|похоже|наверно\w*|не\s+уверен\w*)"
                    before = re.search(uncertain + r"[\s,:-]*(?:(?:это|трубы|столешница|кабель)\s+)?$", text[:match.start()], re.IGNORECASE)
                    after = re.match(r"[а-яё]*[\s,]*(?:" + uncertain + r")\s*(?:[.!?;]|$)", text[match.end():], re.IGNORECASE)
                    if before or after:
                        row.update(status="uncertain", value=text[:120])
                if key in ("plumbing_ready", "electrics_ready"):
                    uncertain_ready = r"(?:относительно|возможно|не\s+уверен\w*|вроде|кажется|наверно\w*|вероятно)"
                    if (re.search(uncertain_ready, match.group(0), re.IGNORECASE)
                            or re.search(uncertain_ready + r"[\s,:-]*$", text[:match.start()], re.IGNORECASE)
                            or re.match(r"[а-яё]*[\s,]*(?:" + uncertain_ready + r")\b", text[match.end():], re.IGNORECASE)):
                        row.update(status="uncertain", value=text[:120])
                if key == 'support' and re.search(r'вроде|кажется|наверно\w*|должна\s+быть|не\s+уверен\w*', text, re.I):
                    row.update(status='uncertain', value=text[:120])
            if key == 'floor_ready' and not match:
                prompt = next((m for m in reversed(messages[:index]) if m.get('direction') == 'out'), None)
                positive = re.match(r'^(?:да[,!.\s]*)?(?:вс[её]\s+)?готов[оыа]?\b', text, re.IGNORECASE)
                negative = re.match(r'^(?:нет[,!.\s]*)?(?:пока\s+)?не\s+готов[оыа]?\b', text, re.IGNORECASE)
                if (prompt and _observed_staff_question(prompt)
                        and _answer_client(message) and message.get('role') not in ('system', 'assistant')
                        and message.get('speaker_role', 'client') == 'client'
                        and re.search(asked, prompt['body'], re.IGNORECASE) and prompt['body'].count('?') <= 1
                        and (positive or negative) and not re.search(r'шкаф|инструкци|детал', text, re.IGNORECASE)
                        and not re.search(r'\bно\b|выравнив|выровн', text, re.IGNORECASE)):
                    row.update(status='answered', value='no' if negative else 'yes',
                               message_id=message.get('id', ''), question_message_id=prompt.get('id', ''), quote=text[:120])
                    row['asked'] = max(row['asked'], 1)
            if index == 0:
                continue
            previous = messages[index - 1]
            # Literal client facts above stand on their own. A short answer
            # below needs an actual staff question, not our unsent proposal.
            if (not _observed_staff_question(previous) or not _answer_client(message)
                    or message.get('role') in ('system', 'assistant')
                    or message.get('speaker_role', 'client') != 'client'):
                continue
            guess_about_asked_height = (key == 'height' and row['asked'] > 0 and '?' in previous['body']
                                       and answer_match(key, answer, previous['body']))
            if previous.get("direction") != "out" or not (
                    re.search(asked, previous["body"], re.IGNORECASE) or guess_about_asked_height
                    or key == 'materials' and tv_fastener_question(previous['body'])):
                continue
            if key == 'materials' and not client_inventory_question(previous):
                continue
            row["asked"] += 1
            inferred = answer_match(key, answer, previous["body"])
            if key == 'support' and re.search(r'вроде|кажется|наверно\w*|должна\s+быть|не\s+уверен\w*', text, re.I):
                row.update(status='uncertain', value=text[:120], message_id=message.get('id', ''),
                           question_message_id=previous.get('id', ''), quote=text[:300], evidence_source='client_message')
            elif UNKNOWN.search(text) and not match:
                row.update(
                    status="unavailable", value="", message_id=message.get("id", "")
                )
            elif key == "countertop_material" and re.fullmatch(r"(?:л?дсп|мдф|мрамор\w*|гранит\w*|акрил\w*(?:\s+камень)?|кварц\w*(?:\s+агломерат)?|дерев\w*|искусственный\s+камень)[.!\s]*", text, re.IGNORECASE):
                row.update(status="answered", value=text[:120], message_id=message.get("id", ""))
            elif key == 'materials':
                # Short inventory replies are handled above with their actual
                # question/delivery/scope. Do not bind them again to a failed,
                # ambiguous or merely declarative staff message.
                continue
            elif (key == 'gas_type' and previous['body'].count('?') <= 1
                  and 'или' not in previous['body'].lower()
                  and re.search(r'без\s+газа', previous['body'], re.I)
                  and (YES.fullmatch(text) or NO.fullmatch(text))):
                row.update(status='answered',value='без газа' if YES.fullmatch(text) else 'газовые элементы',
                           message_id=message.get('id',''),question_message_id=previous.get('id',''),quote=text[:300])
            elif (
                binary
                and previous["body"].count("?") <= 1
                and (YES.fullmatch(text) or NO.fullmatch(text))
            ):
                # An answer to two different subjects cannot identify which
                # one is present/missing. "Scheme or instructions" are the
                # same fact; "scheme or parts" are not. A positive answer
                # to a conjunction confirms both, a negative one does not.
                prompt = previous['body']
                mixed_assembly = (key in ('instructions', 'materials')
                                  and re.search(r'схем|инструкц', prompt, re.I)
                                  and re.search(r'детал|креп[её]ж|материал|комплектующ|расходник', prompt, re.I))
                if mixed_assembly and (re.search(r'\bили\b', prompt, re.I)
                                       or NO.fullmatch(text)):
                    continue
                row.update(
                    status="answered",
                    value="yes" if YES.fullmatch(text) else "no",
                    message_id=message.get("id", ""),
                )
                if key == 'keep_data':
                    row.update(quote=text[:300], question_message_id=previous.get('id', ''),
                               question_quote=previous['body'][:300], evidence_source='client_message')
            elif (
                not binary
                and previous["body"].count("?") <= 1
                and "или" not in previous["body"].lower()
                and inferred
                and YES.fullmatch(text)
            ):
                row.update(
                    status="answered",
                    value=inferred.group(0),
                    message_id=message.get("id", ""),
                )
            elif (
                key == "ceiling"
                and NO.fullmatch(text)
                and "или" not in previous["body"].lower()
                and "натяж" in previous["body"].lower()
            ):
                row.update(
                    status="answered",
                    value="не натяжной",
                    message_id=message.get("id", ""),
                )
            elif key == "room" and re.fullmatch(
                r"кухн\w*|ванн\w*", text, re.IGNORECASE
            ) or key == "client_name" and re.fullmatch(r"[а-яёa-z-]{2,40}(?:\s+[а-яёa-z-]{2,40}){0,2}", text, re.IGNORECASE) and not (YES.fullmatch(text) or NO.fullmatch(text) or UNKNOWN.search(text)):
                row.update(
                    status="answered", value=text, message_id=message.get("id", "")
                )
        state[key] = row
    if tv_brackets and tv_brackets['present']:
        state['materials']['tv_brackets'] = tv_brackets
    work = lock_work_choice(messages)
    if work:
        state['lock_work'].update(work)
    state['screen_damage'] = screen_hazards(messages)
    import personal_media
    crack_images = personal_media.current_tv_screen_crack_images(messages)
    if crack_images:
        image = crack_images[-1]
        observation = image['media_observation']
        quote = 'На просмотренном фото телевизора видны трещины на экране; причина не установлена'
        state['screen_damage'].update(status='answered', value='yes', message_id=image['id'],
            quote=quote, evidence_source=observation['source'],
            reviewed_screen_cracks=dict(message_id=image['id'], signature=image['media_signature'],
                quote=quote, source=observation['source']))
    if state['problem']['status'] in ('missing', 'unavailable', 'uncertain'):
        quality = printer_quality_evidence(messages)
        if quality:
            state['problem'].update(status='answered', **{k: quality[k] for k in ('value', 'message_id', 'quote', 'evidence_source')})
        elif state['office_symptom']['status']=='answered':
            symptom=state['office_symptom']
            state['problem'].update(status='answered',**{k:symptom[k]for k in('value','message_id','quote','evidence_source')})
        elif state['problem']['status']=='missing':
            symptom=appliance_water_symptom(messages)
            if symptom:
                state['problem'].update(status='answered', **symptom)
    if state['model']['status']=='missing':
        # A new literal fallback cannot resolve a conflicting image or an
        # explicitly unavailable model by reviving an older assertion.
        model=reported_device_model(messages)
        if model:
            state['model'].update(status='answered', **model)
    if state['volume']['status'] == 'missing':
        import contact_facts
        volume = contact_facts.tv_mount_work_volume(messages)
        if volume:
            state['volume'].update(status='answered', value=volume['value'],
                                   message_id=volume['message_id'], quote=volume['quote'],
                                   evidence_source='client_message', volume_scope='client_named_tv_mount_count')
    if state['tv_type']['status'] == 'missing':
        model_type = referenced_tv_type(messages) or manufacturer_tv_type(messages)
        if model_type:
            state['tv_type'].update(model_type)
    responsibility = responsibility_components(messages)
    if responsibility:
        state['decision_maker'].update(responsibility)
    # This private field is attached only after matching a durable one-use
    # server authorization with actual delivered message identity and source.
    own = next((m.get('_accepted_own_visit') for m in reversed(messages)
                if m.get('_accepted_own_visit')), None)
    if own:
        state['visit_time'].update(status='answered', value=own['answer_quote'],
            quote=own['answer_quote'], message_id=own['answer_message_id'],
            question_message_id=own['proposal_message_id'], question_quote=own['proposal_quote'],
            evidence_source='authorized_extension_reply', accepted_window=own)
    return state


def question_group_variants(question):
    return [question.get('groups', [])] + question.get('alternative_groups', [])


def question_matches(reply, question):
    if question.get('wording_scope') == 'tv_mount_fasteners_only':
        return tv_fastener_question(reply)
    text = reply.casefold()
    return any(all(any(word.casefold() in text for word in group) for group in groups)
               for groups in question_group_variants(question))


def question(key, state):
    text, _, _, _, groups = SPECS[key]
    row = state[key]
    if key == 'decision_maker' and row.get('components') and row.get('missing_components'):
        wording = dict(decision='Вы будете принимать решение по работам?',
                       payment='Вы будете оплачивать работу?',
                       presence='Вы будете на месте проведения работ?')
        text = ' '.join(wording[k] for k in row['missing_components'])
        groups = [dict(decision=['решени'], payment=['оплат', 'оплач'], presence=['месте'])[k]
                  for k in row['missing_components']]
    if key == 'screen_damage' and row.get('unresolved_hazards') == ['moisture']:
        text, groups = 'На экран попадала вода или влага?', [['вод', 'влаг']]
    elif key == 'screen_damage' and row.get('unresolved_hazards') == ['impact']:
        text, groups = 'Экран повреждали или роняли?', [['поврежд', 'роня', 'удар']]
    if key == 'lock_work' and row.get('subject') == 'ручка':
        text = 'Нужен ремонт ручки или замена?'
    if key == 'countertop_material' and row['status'] == 'uncertain':
        text = 'Уточните, пожалуйста, из какого материала столешница?'
    if key == 'visit_time' and row.get('clarification_kind') == 'daypart':
        text = 'Это время днём?'
        groups = [["врем", "днём", "днем"]]
    if key == 'visit_time' and row.get('clarification_kind') == 'range_order':
        text = 'Уточните, пожалуйста, интервал времени.'
        groups = [["врем", "интервал"]]
    if key == 'visit_time' and row.get('clarification_kind') == 'exact_clock':
        source=row.get('range_source') or {}
        if source.get('time_kind') in ('after','before') and source.get('boundary_time') and source.get('date_text'):
            bound='После' if source['time_kind']=='after' else 'До'
            text=f"{bound} {source['boundary_time']} {source['date_text']} — на какое точное время вам удобно?"
            groups=[['точное время']]
    if key == "model" and row["asked"] and row["status"] == "missing":
        text = "Модель техники сможете подсказать?"
        groups = [["модел"]]
    return {
        "kind": key,
        "question": text,
        "groups": groups,
        "unanswered_attempts": row["asked"],
    }
