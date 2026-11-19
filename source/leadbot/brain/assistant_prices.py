"""Explicit tariff stages; prices are never learned from operator examples."""

import re
from datetime import datetime

_ASK = re.compile(r"цен[ауые]|стоим|сколько|дорого|бюджет|прайс|сумм", re.IGNORECASE)
_GREETING_ONLY = re.compile(r'\s*(?:здравствуйте|добрый\s+(?:день|вечер)|доброе\s+утро)[,.!\s]*', re.IGNORECASE)
# An observed leading-letter typo still names rubles. Do not accept the pipe
# unit «труб», thousand-ruble abbreviations, or arbitrary unknown currencies.
_RUBLE_WORD = r'(?:руб\w*|трублей\b|₽|р(?=[.\s,!?]|$))'
_AMOUNT = re.compile(r'(?<!\d)(\d[\d ]{1,6})\s*(?:руб|трублей\b|₽|р(?=[.\s,!?]|$))', re.IGNORECASE)
_NEW_INTAKE_PRICE_SCOPE = re.compile(
    r'\s*(?:нов(?:ая\s+заявка|ый\s+заказ|ое\s+обращение)|по\s+другому\s+(?:заказу|вопросу))\b', re.I)
FURNITURE_REPAIR_MIN_RULE = 'OWNER-FURNITURE-REPAIR-MIN-20261018'
KP_PARTNER_DIAGNOSTIC_RULE = 'OWNER-KP-PARTNER-DIAGNOSTIC-20261020'
DIAGNOSTIC_ONLY_RULE = 'OWNER-DIAGNOSTIC-ONLY-MIN-20261020'
MNC_FREE_CALLOUT_RULE = 'OWNER-MNC-FREE-CALLOUT-20261021'
BT_800_RULE = 'OWNER-BT-800-20261027'
BT_WORK_MINIMUM = 800
MNC_SERVICE_MINIMA = {
    'plumbing-tap': (800, 'DOC-L0264'), 'towel': (1000, 'DOC-L0268'),
    'sink': (1000, 'DOC-L0272'), 'bath': (1500, 'DOC-L0276'),
    'toilet': (1500, 'DOC-L0280'), 'plumbing-small': (800, 'DOC-L0290'),
    'sockets': (800, 'DOC-L0299'), 'light': (1000, 'DOC-L0306'),
    'furniture': (1500, 'DOC-L0326'), 'kitchen': (2000, 'DOC-L0331'),
    'hanging': (800, 'DOC-L0353'), 'tv-mount': (800, 'DOC-L0353'),
    'sport': (1000, 'DOC-L0358'),
}


def outgoing_reply_observed(message):
    """Keep posted speech distinct from service events and unavailable sends.

    An old outgoing row without delivery metadata remains compatible prior
    speech. It does not acquire a new delivery receipt from that compatibility.
    """
    delivery = str(message.get('delivery_status') or message.get('delivery') or '').lower()
    unavailable = message.get('out_pending') or delivery in (
        'failed', 'pending', 'queued', 'sending', 'error', 'cancelled', 'canceled')
    return bool(message.get('direction') == 'out' and not unavailable
                and message.get('sender_type') not in ('system', 'avito')
                and message.get('role') != 'system'
                and message.get('speaker_role') != 'service')


def _price_source_rows(messages):
    """A pricing view only; the original timeline/IDs/delivery stay untouched."""
    return [row for row in messages
            if row.get('direction') != 'out' or outgoing_reply_observed(row)]


def _mnc_callout(known, repair_note=''):
    if not known.get('city'):
        return dict(handoff='Сначала нужно уточнить город и территорию выезда',
                    rules=[MNC_FREE_CALLOUT_RULE, 'DOC-L0757'])
    return dict(reply='Выезд в черте города бесплатный.' + repair_note, amounts=[],
                rules=[MNC_FREE_CALLOUT_RULE, 'DOC-L0757'] + (['DOC-L0713'] if repair_note else []))


def _bt_diagnostic_quote(repair_note=''):
    # No observed disassembly/type is inferred from a symptom or a request
    # for diagnosis only. The two documented prices have different kinds.
    return dict(reply='Первичная диагностика без разбора техники — 800 рублей. '
                'Техническая диагностика с разбором — от 800 рублей. '
                'При продолжении работ диагностика бесплатная.' + repair_note,
                amounts=[800], rules=[BT_800_RULE, 'DOC-L0759', 'DOC-L0760', 'DOC-L0761']
                + (['DOC-L0713'] if repair_note else []))


def _bt_diagnostic_quote_verified(quoted, consent_state):
    """Verify the current typed amount; an old/unspecified floor is not enough."""
    if consent_state.get('amount') != 800:
        return False
    if not re.search(r'(?:продолжен|оказан|выполнен).{0,40}(?:работ|услуг).{0,40}бесплат', quoted, re.I):
        return False
    amounts = _AMOUNT.findall(quoted)
    if not amounts or any(int(x.replace(' ', '')) != 800 for x in amounts):
        return False
    kinds = (r'(?:первичн|техническ)\w*\s+(?:диагностик|осмотр)\w*|'
             r'диагностик\w*\s+(?:без\s+разбора|с\s+разбором)')
    prices = list(re.finditer(r'(?P<kind>' + kinds + r')(?P<qualifier>[^\d.!?\n]{0,70})'
                             r'800\s*' + _RUBLE_WORD, quoted, re.I))
    if len(prices) != len(amounts):
        return False
    for price in prices:
        kind, qualifier = price['kind'].lower(), price['qualifier'].lower()
        technical = 'техническ' in kind or 'с разбором' in kind
        has_from = bool(re.search(r'\bот\s*$', qualifier))
        if technical != has_from or re.search(r'\b(?:не|либо|или|до)\b', qualifier):
            return False
    return True


def bt_diagnostic_price_claim(text):
    """Reject conflicting own prose, preserving questions/reports of old prices.

    This checks free meaning/note/reply as well as the native fixed reply. It
    does not replace the separate semantic review or force a model receipt.
    """
    for clause in re.split(r'[.!?;\n]+', str(text or '')):
        if not re.search(r'диагност|первичн|техническ', clause, re.I):
            continue
        if (re.search(r'раньше|стар\w*\s+цен|устаревш|клиент\w*\s+(?:спраш|сказ|сообщ)|по\s+слов', clause, re.I)
                and not re.search(r'теперь|сейчас|наша\s+цена|действующ\w*\s+цен', clause, re.I)):
            continue
        money=list(re.finditer(r'(?P<amount>\d[\d ]{1,6})\s*'+_RUBLE_WORD,clause,re.I))
        for item in money:
            before=clause[:item.start()]
            if re.search(r'\bне\s+(?:стоит|от|составляет)\s*$',before,re.I):
                continue
            if int(item['amount'].replace(' ',''))!=800:
                return True
            # The closest named category before this amount binds its price.
            prefix=re.split(r'\d[\d ]{1,6}\s*'+_RUBLE_WORD,before,flags=re.I)[-1]
            primary=bool(re.search(r'первичн|без\s+разбора',prefix,re.I))
            technical=bool(re.search(r'техническ|с\s+разбором',prefix,re.I))
            from_price=bool(re.search(r'\bот\s*$',prefix,re.I))
            if primary==technical or technical!=from_price:
                return True
    return False


def diagnostic_only_applies(messages):
    messages = _price_source_rows(messages)
    import contact_facts
    enquiry = current_enquiry_messages(messages)
    if not contact_facts.standalone_diagnostic(enquiry):
        return False
    latest = next((m.get('body','') for m in reversed(enquiry) if m.get('direction') == 'in'), '')
    # A separate question about repair cost is not a diagnostic-only quote.
    return not (asks(latest) and re.search(r'ремонт|почин|заправ|подключ|настрой',latest,re.I)
                and not re.search(r'диагност',latest,re.I))


def _partner_diagnostic_fee_applies(known):
    """The partner callout/diagnosis fee belongs to KP, never BT or MNC."""
    partner = str(known.get('partner') or '').lstrip('0')
    return known.get('direction') == 'kp' and partner.isdigit() and int(partner) > 0


def current_enquiry_scope(messages):
    """Scope a declared new enquiry without rewriting the source timeline.

    An explicit closed-prior/new-request statement scopes qualification and
    prices, not operational closure. The legacy hanging-to-assembly case
    still requires a dated gap and no prior commitment or contacts. Full
    history remains available to existing-order/complaint guards and audit.
    """
    import contact_phone
    def client_row(row):
        return (row.get('direction') == 'in'
                and row.get('sender_type') not in ('system', 'avito', 'operator', 'assistant', 'bot', 'employee', 'human')
                and row.get('role') not in ('system', 'assistant', 'tool'))
    found = {}
    for index, message in enumerate(messages):
        body = str(message.get('body') or message.get('text') or '')
        if client_row(message):
            import assistant_catalog
            _, prior = assistant_catalog._without_closed_prior_work(body)
            if prior:
                found = {'start_index': index, 'message_id': message.get('id', ''), 'quote': body,
                    'text': '\n'.join(str(m.get('body') or m.get('text') or '') for m in messages[index:]
                                   if client_row(m)),
                    'reported_closed_prior_quotes': prior, 'verifies_crm_closure': False,
                    'reason': 'Явный новый запрос после названного закрытого прошлого заказа; прежнюю услугу и цену не переносим'}
                continue
        if message.get('direction') != 'in' or not re.match(
                r'^\s*(?:здравствуйте|добрый\s+(?:день|вечер)|доброе\s+утро)\b', body, re.I):
            continue
        if not re.search(r'мебел\w*.{0,25}собира|собира\w*.{0,25}мебел|'
                         r'(?:собрать|сборк\w*).{0,25}(?:шкаф|комод|кроват|тумб|стол)', body, re.I):
            continue
        if re.search(r'ту\s+же|тот\s+же|прошл|заявк|снова|повтор|передел|додел|договар', body, re.I):
            continue
        previous = [m for m in messages[:index] if m.get('direction') in ('in','out')]
        if not previous:
            continue
        try:
            now = datetime.fromisoformat(str(message.get('created_at') or '').replace('Z','+00:00'))
            before = datetime.fromisoformat(str(previous[-1].get('created_at') or '').replace('Z','+00:00'))
            if not now.tzinfo or not before.tzinfo or (now-before).total_seconds() < 7*86400:
                continue
        except (ValueError, TypeError):
            continue
        prior_client = '\n'.join(str(m.get('body') or m.get('text') or '') for m in previous if m.get('direction')=='in')
        if (not re.search(r'повес|навес|кронштейн|карниз|гардин', prior_client, re.I)
                or re.search(r'сборк|собра|собира|претензи|возврат|жалоб|прошл|заявк', prior_client, re.I)):
            continue
        committed = False
        quoted = False
        for old in previous:
            if old.get('direction') == 'out' and not outgoing_reply_observed(old):
                continue
            text = str(old.get('body') or old.get('text') or '')
            if contact_phone.find_all(text) or re.search(r'\b(?:улица|ул\.|адрес|квартира)\b',text,re.I):
                committed = True
            if old.get('direction') == 'out':
                if re.search(r'записал|приеду|подъеду|\bбуду\b|\bчерез\b|\b(?:в|к)\s*\d{1,2}',text,re.I):
                    committed = True
                quoted = quoted or bool(_AMOUNT.search(text))
            elif quoted and _accepts_price(text):
                committed = True
        if not committed:
            found = dict(start_index=index,message_id=message.get('id',''),quote=body,
                         text='\n'.join(str(m.get('body') or m.get('text') or '') for m in messages[index:] if m.get('direction')=='in'),
                         reason='Новый запрос сборки после давнего запроса навески без подтверждённой записи; прежнюю цену и условия не переносим')
    return found


def current_enquiry_messages(messages):
    scope = current_enquiry_scope(messages)
    return messages[scope['start_index']:] if scope else messages


_WRONG_CHAT = re.compile(r'\s*(?:ой[,!\s]*)?(?:не\s+вам\b|не\s+в\s+тот\s+(?:чат|диалог)\b|'
                         r'ошиб(?:ся|лась)\s+(?:чатом|диалогом)\b)', re.I)


def quote_retraction_evidence(messages):
    """A wrong-chat correction can follow a separate, empty 'ой' message.

    Only a contiguous delivered staff turn is eligible. A customer response,
    a system/note boundary or a substantive staff message ends the search;
    an accepted price cannot be erased by a later correction.
    """
    evidence = []
    for i, message in enumerate(messages):
        if (not i or not outgoing_reply_observed(message)
                or not _WRONG_CHAT.match(message.get('body', ''))):
            continue
        j = i - 1
        bridge = []
        while (j >= 0 and len(bridge) < 2 and outgoing_reply_observed(messages[j])
               and re.fullmatch(r'\s*ой[,.!\s]*', messages[j].get('body', ''), re.I)):
            bridge.insert(0, messages[j].get('id', ''))
            j -= 1
        if (j >= 0 and outgoing_reply_observed(messages[j])
                and _AMOUNT.search(messages[j].get('body', ''))):
            evidence.append(dict(quote_index=j, quote_message_id=messages[j].get('id', ''),
                                 quote=messages[j].get('body', ''), correction_message_id=message.get('id', ''),
                                 correction=message.get('body', ''), bridge_message_ids=bridge))
    evidence.extend(_resolved_choice_corrections(messages))
    return evidence


def _resolved_choice_corrections(messages):
    """Resolve an explicit two-price question, never a numeric typo guess.

    Require both prior staff quotes and the staff's unambiguous confirmation.
    A previously accepted total stays visible for operator review. A generic
    minimum is superseded only when its immediate follow-up is a price-limit
    question about that same quoted total, not a new service or visit charge.
    """
    result = []
    normalized = lambda text: re.sub(r'(?<=\d)[ \u00a0]+(?=\d)', '', str(text or ''))
    unit = r'(?:р(?:уб\w*)?\.?|₽)'
    for i, message in enumerate(messages):
        if not outgoing_reply_observed(message):
            continue
        answer = re.fullmatch(r'\s*(?:(?:я\s+же\s+написал[аи]?|нет)[,!\s]*)?(\d{3,6})\s*' + unit + r'?[.!\s]*',
                              normalized(message.get('body')), re.I)
        if not answer:
            continue
        q = i - 1
        while q >= 0 and messages[q].get('direction') == 'system':
            q -= 1
        if q < 0 or messages[q].get('direction') != 'in':
            continue
        choice = re.fullmatch(r'\s*(\d{3,6})\s*' + unit + r'?\s+или\s+(\d{3,6})\s*' + unit + r'?[?!.\s]*',
                              normalized(messages[q].get('body')), re.I)
        if not choice or choice[1] == choice[2] or answer[1] not in choice.groups():
            continue
        new_amount = int(answer[1]); old_amount = int(choice[2] if answer[1] == choice[1] else choice[1])
        def quote_amount(index):
            row = messages[index]
            amounts = _AMOUNT.findall(row.get('body', ''))
            return int(amounts[0].replace(' ', '')) if outgoing_reply_observed(row) and len(amounts) == 1 else None
        new = next((k for k in range(q-1, -1, -1) if quote_amount(k) == new_amount), None)
        old = next((k for k in range((new or 0)-1, -1, -1) if quote_amount(k) == old_amount), None)
        if new is None or old is None:
            continue
        if any(m.get('direction') == 'in' and (_accepts_price(m.get('body', ''))
               or _accepts_named_price(m.get('body', ''), old_amount, messages[old].get('body', '')))
               for m in messages[old+1:new]):
            continue
        def record(index, kind):
            return dict(kind=kind, quote_index=index, quote_message_id=messages[index].get('id', ''),
                        quote=messages[index].get('body', ''), correction_message_id=message.get('id', ''),
                        correction=message.get('body', ''), choice_message_id=messages[q].get('id', ''),
                        replacement_message_id=messages[new].get('id', ''), replacement_amount=new_amount)
        result.append(record(old, 'numeric_correction'))
        previous = next((k for k in range(old-1, -1, -1) if quote_amount(k) is not None), None)
        if previous is None:
            continue
        bare = re.fullmatch(r'\s*от\s*\d{3,6}\s*' + unit + r'(?:\s+будет)?[.!\s]*', normalized(messages[previous].get('body')), re.I)
        followups = [m.get('body', '') for m in messages[previous+1:old] if m.get('direction') == 'in']
        same_scope = bool(followups) and all(re.fullmatch(
            r'\s*(?:(?:а|и)\s+)?до\s+какой\s+суммы\s+предел[?!.\s]*(?:от\s+чего\s+зависит[?!.\s]*)?', text, re.I)
            for text in followups)
        if bare and same_scope:
            result.append(record(previous, 'superseded_generic_minimum'))
    return result


def withdrawn_quote_indexes(messages):
    return {row['quote_index'] for row in quote_retraction_evidence(messages)}


def _price_response(text):
    """A qualification or appointment question cannot answer a price objection."""
    return bool(re.search(r'\d\s*(?:руб\w*|₽|р(?=[.\s,!?]|$))|\bот\s+\d|'
                          r'нужно\s+посмотр|после\s+осмотр|обсудим\s+на\s+месте|'
                          r'\b(?:по|завис\w*\s+от)\s+об[ъь][её]м|'
                          r'(?:цен|стоим|сориентир).{0,70}(?:осмотр|мест[еу]|об[ъь][её]м)|'
                          r'(?:осмотр|об[ъь][её]м).{0,70}(?:цен|стоим)|'
                          r'\b(?:посмотрю|посмотрим|осмотрю|осмотрим)\b[^.!?\n]{0,80}\bна\s+месте\b|'
                          r'(?:на|по)\s+мест[еу].{0,80}(?:цен|стоим|сориентир|рассчита)', text, re.IGNORECASE))



def _literal_price_scope(text):
    """Quoted/conditional descriptions cannot establish the ordered work."""
    text = re.sub(r"""«[^»]*»|“[^”]*”|„[^“]*“|"[^"\n]*"|'[^'\n]*'|‘[^’]*’""", ' ', text)
    return '\n'.join(c for c in re.split(r'[.!?\n;]+', text)
                     if not re.search(r'\b(?:если|вдруг|допустим|предположим)\b|'
                                      r'\b(?:другой\s+)?(?:мастер|сосед|специалист|продавец)\w*[^,]{0,30}'
                                      r'(?:сказал|написал|предложил|спросил)', c, re.I))


# These are service prices, not minima for a whole service family. Keep the
# primary unit (including the unusual M2 for plinths) and the Moscow column.
# key, catalogue family, object, operation, ordinary, Moscow, unit, refs, label
_INSTALL = r'установ(?:ить|ите|к[ауиеой]+)|замен(?:ить|ите|[ауыеой]+)|поменять|поменяйте|поставить|поставьте|монтаж|смонтировать'
_HANG = r'повесить|повесьте|повешать|навесить|навесьте|навеск[ауи]|закрепить|прикрутить'
_LAY = r'уложить|уложите|укладк[ауи]|положить|положите|проложить|прокладк[ауи]'
_SEAL = r'герметизаци[яюи]|загерметизировать|засиликонить'
MNC_FIXED_TARIFFS = [
    ('tap', 'plumbing-tap', r'смесител\w*', _INSTALL, 2000, 3000, 'штуку', ['DOC-L0480'], 'Установка/замена смесителя'),
    ('siphon', 'plumbing-tap', r'сифон\w*', _INSTALL, 1000, 2500, 'штуку', ['DOC-L0481'], 'Установка/замена сифона'),
    ('towel', 'towel', r'полотенце\s*сушител\w*', _INSTALL, 3000, 4000, 'штуку', ['DOC-L0483'], 'Установка/замена полотенцесушителя'),
    ('sink', 'sink', r'раковин\w*|мойк\w*', _INSTALL, 3000, 5000, 'штуку', ['DOC-L0485'], 'Установка/замена раковины'),
    ('sink-seal', 'sink', r'раковин\w*|мойк\w*', _SEAL, 1000, 1000, 'точку', ['DOC-L0486'], 'Герметизация раковины'),
    ('bath-seal', 'bath', r'ванн\w*|душев\w*', _SEAL, 2000, 2000, 'точку', ['DOC-L0492'], 'Герметизация ванны/душевой'),
    ('toilet', 'toilet', r'унитаз\w*|биде|писсуар\w*', _INSTALL, 3500, 6000, 'штуку', ['DOC-L0494'], 'Установка/замена унитаза/биде/писсуара'),
    ('toilet-fitting', 'toilet', r'фурнитур\w*|арматур\w*', _INSTALL, 1500, 2500, 'штуку', ['DOC-L0495'], 'Установка/замена фурнитуры унитаза'),
    ('small-plumbing', 'plumbing-small', r'фильтр\w*|заглушк\w*|сч[её]тчик\w*|ниппел\w*|шланг\w*|подводк\w*', _INSTALL, 1500, 2000, 'штуку', ['DOC-L0497'], 'Установка/замена мелкого элемента сантехники'),
    ('socket', 'sockets', r'розетк\w*|выключател\w*', _INSTALL, 1000, 1500, 'штуку', ['DOC-L0502'], 'Установка/замена розетки/выключателя'),
    ('chandelier', 'light', r'люстр\w*', _INSTALL + '|' + _HANG, 1000, 1500, 'штуку', ['DOC-L0504'], 'Установка/замена люстры'),
    ('support', 'light', r'закладн\w*', _INSTALL, 1000, 1500, 'штуку', ['DOC-L0505'], 'Монтаж закладной'),
    ('breaker', 'electric', r'автомат\w*', _INSTALL, 1300, 1500, 'штуку', ['DOC-L0507'], 'Установка/замена автомата'),
    ('cable', 'electric', r'кабел\w*', _LAY, 150, 270, 'погонный метр', ['DOC-L0508'], 'Прокладка кабеля'),
    ('linoleum', 'floor', r'линолеум\w*', _LAY, 350, 500, 'м²', ['DOC-L0511'], 'Укладка линолеума'),
    ('laminate', 'floor', r'ламинат\w*', _LAY, 600, 800, 'м²', ['DOC-L0512'], 'Укладка ламината'),
    ('plinth-fastener', 'plinth', r'плинтус\w*|порож(?:ек|к)\w*', _INSTALL + '|' + _LAY, 400, 500, 'м²', ['DOC-L0514', 'DOC-L0515'], 'Укладка плинтуса/порожка на клипсы/саморезы'),
    ('plinth-glue', 'plinth', r'плинтус\w*|порож(?:ек|к)\w*', _INSTALL + '|' + _LAY, 500, 600, 'м²', ['DOC-L0516'], 'Укладка плинтуса/порожка на клей'),
    ('plinth-both', 'plinth', r'плинтус\w*|порож(?:ек|к)\w*', _INSTALL + '|' + _LAY, 600, 800, 'м²', ['DOC-L0517'], 'Укладка плинтуса/порожка на крепёж и клей'),
    ('ceiling-tile', 'plinth', r'потолочн\w*\s+плитк\w*', _INSTALL + '|' + _LAY, 400, 600, 'м²', ['DOC-L0518'], 'Укладка потолочной плитки'),
    ('mirror', 'hanging', r'зеркал\w*', _INSTALL + '|' + _HANG, 1000, 1500, 'штуку', ['DOC-L0521'], 'Установка зеркала'),
    ('bracket', 'tv-mount', r'кронштейн\w*', _INSTALL + '|' + _HANG, 1500, 2000, 'штуку', ['DOC-L0522'], 'Установка кронштейна'),
    ('picture-hook', 'hanging', r'картин\w*|крюч\w*', _HANG, 400, 800, 'штуку', ['DOC-L0523'], 'Навес картины/крючка'),
    ('shelf', 'hanging', r'полк\w*|вешал\w*', _HANG, 600, 1000, 'штуку', ['DOC-L0524'], 'Навес полки/вешалки'),
    ('curtain-rail', 'hanging', r'карниз\w*|гардин\w*', _INSTALL + '|' + _HANG, 800, 1300, 'штуку', ['DOC-L0525'], 'Навес карниза'),
    ('sport', 'sport', r'турник\w*|шведск\w*\s+стен\w*', _INSTALL + '|' + _HANG, 1200, 1600, 'штуку', ['DOC-L0527', 'DOC-L0528'], 'Установка турника/шведской стены'),
    ('dryer', 'drying', r'сушилк\w*', _INSTALL + '|' + _HANG, 2000, 3000, 'штуку', ['DOC-L0530', 'DOC-L0531'], 'Установка сушилки для белья'),
    ('interior-lock', 'lock', r'замок|замк\w*|ручк\w*', _INSTALL, 2500, 4000, 'штуку', ['DOC-L0533'], 'Замена/установка замка или ручки межкомнатной двери'),
    ('entrance-lock', 'lock', r'замок|замк\w*|ручк\w*', _INSTALL, 5000, 8000, 'штуку', ['DOC-L0534'], 'Замена/установка замка или ручки входной двери'),
    ('window-adjust', 'window', r'окн\w*', r'регулировк[ауи]|отрегулировать|продувк[ауи]|промывк[ауи]|промыть', 1500, 2500, 'штуку', ['DOC-L0536'], 'Регулировка/продувка/промывка окна'),
    ('window-fitting', 'window', r'ручк\w*|уплотнительн\w*\s+резинк\w*|детск\w*\s+замок', _INSTALL, 5000, 8000, 'штуку', ['DOC-L0537'], 'Установка/замена фурнитуры окна'),
]


def mnc_fixed_tariff(messages, known, *, include_ambiguity=False):
    """An explicit present operation, never a diagnosis or a customer's budget."""
    messages = _price_source_rows(messages)
    if known.get('direction') != 'mnc':
        return None
    from contact_cities import city_by_name
    import assistant_catalog
    import territory
    city = city_by_name(known.get('city'))
    if not city or city.name == 'Москва и МО':
        return None
    clauses = []
    for message in current_enquiry_messages(messages):
        if message.get('direction') != 'in' or message.get('sender_type') in ('system', 'avito', 'operator', 'assistant', 'bot'):
            continue
        for clause in _literal_price_scope(message.get('body') or message.get('text') or '').split('\n'):
            if (re.search(r'\b(?:раньше|ранее|вчера|сам|сама|сами|самостоятельно)\b|уже\s+(?:сделан|установлен|заменен|заменён)|'
                          r'\b(?:может|возможно|наверное|вероятно|предполагаю|кажется)\b|\bскорее\s+всего\b', clause, re.I)
                    or re.search(r'\bне\s+(?:(?:нужн\w*|надо|хочу|требуется)\s+)?(?:' + _INSTALL + '|' + _HANG + '|' + _LAY + '|' + _SEAL + r')\b', clause, re.I)):
                continue
            clauses.append((message.get('id', ''), clause))
    client = '\n'.join(body for _, body in clauses)
    service = assistant_catalog.choose(client, known)
    if service['status'] != 'supported' or len(service.get('items', [])) != 1:
        return None
    family = service['items'][0]['id']
    found = []
    for key, item, obj, operation, normal, moscow, unit, refs, label in MNC_FIXED_TARIFFS:
        if family != item and not (key == 'bracket' and family == 'hanging'):
            continue
        evidence = []
        if key == 'bracket' and family == 'tv-mount':
            # Owner21Oct: TV installation/hanging means mounting on a
            # bracket and shares its admission AND unit price, not two fees.
            evidence = [(mid, body) for mid, body in clauses
                        if any(x['id'] == 'tv-mount' for x in assistant_catalog.choose(body, known).get('items', []))]
            obj = r'кронштейн\w*|телевизор\w*|тв|телек\w*'
            refs = refs + ['OWNER-MNC-TV-MOUNT-PRICE-20261021']
            label = 'Установка кронштейна/навес телевизора'
        for mid, body in clauses:
            if key == 'bracket' and family == 'tv-mount':
                continue
            if key == 'bracket' and not re.search(
                    r'\b(?:' + operation + r')\s+(?:(?:нов\w*|сво\w*|этот|этого|настенн\w*|потолочн\w*)\s+){0,2}кронштейн\w*|'
                    r'(?<!на )\bкронштейн\w*\s+(?:(?:нужно|надо|необходимо|требуется|прошу)\s+)?(?:' + operation + r')\b', body, re.I):
                # For non-TV work the bracket must be the actual target.
                continue
            for match in re.finditer(
                    r'\b(?:' + operation + r')\b[^.!?\n]{0,65}?\b(?:' + obj + r')\b|'
                    r'\b(?:' + obj + r')\b[^.!?\n]{0,65}?\b(?:' + operation + r')\b', body, re.I):
                if key == 'chandelier' and re.search(r'закладн', match[0], re.I):
                    continue
                evidence.append((mid, body))
        if not evidence:
            continue
        if key == 'toilet' and re.search(r'фурнитур|арматур|механизм|кнопк', client, re.I):
            continue
        if key.startswith('plinth-'):
            screws = bool(re.search(r'клипс|саморез|шуруп', client, re.I))
            glue = bool(re.search(r'кле[йяю]|клеить', client, re.I))
            if key != ('plinth-both' if screws and glue else 'plinth-fastener' if screws else 'plinth-glue' if glue else ''):
                continue
        if key.endswith('-lock'):
            interior, entrance = bool(re.search(r'межкомнатн', client, re.I)), bool(re.search(r'входн', client, re.I))
            if interior == entrance or key != ('interior-lock' if interior else 'entrance-lock'):
                continue
        found.append(dict(key=key, amount=moscow if territory.price_column(city.name) == 'msk' else normal,
                          unit=unit, rules=refs, label=label, object_pattern=obj,
                          evidence=[dict(message_id=mid, quote=body) for mid, body in evidence]))
    if len(found) > 1 and include_ambiguity:
        return dict(handoff='В запросе несколько разных тарифов: нужно проверить состав и объём каждой работы',
                    rules=list(dict.fromkeys(ref for t in found for ref in t['rules'])))
    if len(found) != 1:
        return None
    # A tariff for one installation cannot cover a separately requested
    # repair, dismantling or assembly merely sharing that object's family.
    if re.search(r'\b(?:починить|отремонтировать|ремонт|собрать|сборка|демонтаж|демонтировать|перенести)\b', client, re.I):
        return None
    return found[0]


def tv_mount_quantity(messages, tariff):
    """A literal count bound to the current requested mounting operation."""
    if not tariff or tariff.get('key') != 'bracket' or tariff.get('unit') != 'штуку':
        return None
    import contact_facts
    rows = [message for message in _price_source_rows(messages)
            if message.get('direction') != 'in' or (
                contact_facts._client_intent_message(message)
                and message.get('speaker_role', 'client') == 'client'
                and message.get('role') not in ('system', 'assistant'))]
    context = contact_facts.item_quantity_context(rows) or {}
    state = context.get('objects', {}).get('tv', {})
    count = state.get('current_count')
    if type(count) is not int or not 2 <= count <= 99 or state.get('total_unresolved'):
        return None
    for evidence in tariff.get('evidence', []):
        if evidence['message_id'] != state.get('current_message_id'):
            continue
        if not re.search(_INSTALL + '|' + _HANG, evidence['quote'], re.I):
            continue
        if any(item['object'] == 'tv' and item['count'] == count and item['mode'] == 'asserted'
               for item in contact_facts._quantity_mentions(evidence['quote'])):
            return dict(count=count, message_id=evidence['message_id'], quote=evidence['quote'],
                        source='literal_current_mount_count', booking_confirmed=False)
    return None


def _tv_total_reply(tariff, quantity):
    count = quantity['count']
    noun = 'телевизора' if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14) else 'телевизоров'
    return (f"За {count} {noun} с установкой кронштейнов — {count * tariff['amount']} рублей, "
            f"по {tariff['amount']} рублей за штуку, без учёта материалов. Вас устраивает такая стоимость?")


def _tv_total_components(quote):
    match = re.fullmatch(
        r'\s*За (?P<count>\d{1,2}) телевизор(?:а|ов) с установкой кронштейнов [—-] '
        r'(?P<total>\d{3,6}) рублей, по (?P<unit>\d{3,6}) рублей за штуку, '
        r'без уч[её]та материалов[.]\s*(?:Вас устраивает такая стоимость[?])?\s*', quote, re.I)
    if not match:
        # Full clauses, explicit count/total/unit/materials and only the
        # price-consent question. A matching amount never admits extra text.
        match = re.fullmatch(
            r'\s*(?:Установка|Монтаж) кронштейнов (?:для|на) (?P<count>\d{1,2}) телевизор(?:а|ов) '
            r'(?:стоит|обойд[её]тся в|[—-]) (?P<total>\d{3,6}) рублей[,.]\s*'
            r'[Пп]о (?P<unit>\d{3,6}) рублей за (?:одну )?штуку[,.]\s*'
            r'(?:[Бб]ез уч[её]та материалов|[Мм]атериалы (?:не включены|оплачиваются отдельно))[.]\s*'
            r'(?:(?:Такая цена вас устроит|Вас устраивает такая стоимость|Подойд[её]т вам такая стоимость)[?])?\s*',
            quote, re.IGNORECASE)
    return {key: int(match[key]) for key in ('count', 'total', 'unit')} if match else None


def mnc_fixed_unit_mentions(quote, tariff):
    """Parse actual unit mentions; legacy implicit-single-item rules stay separate."""
    named_unit = r'(?:(?:одн\w*|[1-9]\d*|дв[ае]|три)\s+)?(?:' + tariff['object_pattern'] + r')'
    unit_scope = re.sub(re.escape(tariff['label']), '[SERVICE_LABEL]', quote, flags=re.IGNORECASE)
    units = re.findall(r'(?:за\s+|/\s*)(?:погонн\w*\s+метр\w*|метр\w*|м[²2]|кв\.?\s*м(?:етр\w*)?|час\w*|шт\.?\b|штук\w*|точк\w*|' + named_unit + ')', unit_scope, re.IGNORECASE)
    expected = {'штуку': r'(?:за\s+|/\s*)(?:шт\.?|штук\w*|(?:(?:одн\w*|1)\s+)?(?:' + tariff['object_pattern'] + '))',
                'точку': r'(?:за\s+|/\s*)точк\w*',
                'погонный метр': r'(?:за\s+|/\s*)погонн\w*\s+метр\w*',
                'м²': r'(?:за\s+|/\s*)(?:м[²2]|кв\.?\s*м(?:етр\w*)?)'}[tariff['unit']]
    return units, len(units) == 1 and bool(re.fullmatch(expected, units[0], re.IGNORECASE))


def mnc_fixed_quote(messages, known, consent_state):
    """Verify a human's service price, separately from the client's consent."""
    messages = _price_source_rows(messages)
    index = next((i for i, m in enumerate(messages) if m.get('direction') == 'out'
                  and m.get('id') == consent_state.get('message_id')), None)
    if index is None:
        return None
    before = messages[:index]
    tariff = mnc_fixed_tariff(before, known)
    current = mnc_fixed_tariff(messages, known)
    if not tariff or not current or current['key'] != tariff['key']:
        return None
    quote = messages[index].get('body', '')
    total = _tv_total_components(quote)
    if total:
        before_count = tv_mount_quantity(before, tariff)
        current_count = tv_mount_quantity(messages, current)
        if (not before_count or not current_count or total['count'] != before_count['count']
                or current_count['count'] != before_count['count']
                or total['unit'] != tariff['amount'] or current['amount'] != tariff['amount']
                or total['total'] != total['count'] * total['unit']
                or consent_state.get('amount') != total['total']):
            return None
        return dict(tariff, amount=total['total'], unit_amount=total['unit'], quantity=before_count,
                    message_id=consent_state['message_id'], quote=quote)
    amounts = _AMOUNT.findall(quote)
    if (len(amounts) != 1 or int(amounts[0].replace(' ', '')) != tariff['amount']
            or consent_state.get('amount') != tariff['amount']
            or re.search(r'\b(?:от|до|около|примерно|максимум|диагност\w*|ремонт\w*|почин\w*|выезд|вызов)\b|'
                         r'за\s+(?:вс[её]|весь\s+объ[её]м)|итогов|окончатель|без\s+доплат|вс[её]\s+включено|'
                         r'\b(?:с|со)\s+(?:(?:уч[её]том|всеми|вашими|нашими)\s+)?(?:материал|запчаст)\w*|'
                         r'за\s+(?:[2-9]\d*|дв[ае]|три|четыре|пять|несколько)\b|комплект|оптом|'
                         r'(?:материал|запчаст)\w*\s+(?:(?:все|уже|тоже|также)\s+)?(?:включен|включён|вход\w*|бесплат)|'
                         r'(?<!не )\b(?:включен|включён|включая)\w*\s+(?:все\s+)?(?:материал|запчаст)', quote, re.I)):
        return None
    # Named other work is not this service, even when both cost 1000.
    import assistant_catalog
    quote_scope = re.sub(r'(?:за\s+|/\s*)(?:(?:один|одну|одно|1)\s+)?(?:' + tariff['object_pattern'] + r')\b',
                         '[UNIT]', quote, flags=re.I)
    # A recognized currency typo is not a requested plumbing pipe.
    quote_scope = _AMOUNT.sub('[MONEY]', quote_scope)
    named = assistant_catalog.choose(quote_scope, known)
    source_ids = {x['id'] for x in assistant_catalog.choose('\n'.join(m.get('body', '') for m in before if m.get('direction') == 'in'), known).get('items', [])}
    if {x['id'] for x in named.get('items', [])} - source_ids:
        return None
    named_tariff = mnc_fixed_tariff([dict(direction='in', body=quote)], known)
    if named_tariff and named_tariff['key'] != tariff['key']:
        return None
    # The canonical label "розетки/выключателя" names service alternatives.
    # Only that exact label is removed; real price units and bundles remain.
    units, unit_valid = mnc_fixed_unit_mentions(quote, tariff)
    if units and not unit_valid:
        return None
    client = '\n'.join(m.get('body', '') for m in before if m.get('direction') == 'in')
    multiple = re.search(r'\b(?:[2-9]\d*|дв[ае]|три|четыре|пять|несколько)\s+(?:[а-яё]+\s+){0,2}(?:' + tariff['object_pattern'] + r')', client, re.I)
    multiple = multiple or re.search(r'\b(?:' + tariff['object_pattern'] + r')\s*(?:и|,)\s*'
                                    r'(?:' + tariff['object_pattern'] + r')\b', client, re.I)
    if not units and (tariff['unit'] != 'штуку' or multiple):
        return None
    return dict(tariff, message_id=consent_state['message_id'], quote=quote)


def mnc_price_basis(messages, known):
    """Bind a documented minimum and unit to the customer's present work.

    A switch is the location of the requested wire operation; a mixer is the
    connection of the named hose. Neither establishes another ordered job.
    """
    messages = _price_source_rows(messages)
    if known.get('direction') != 'mnc' or diagnostic_only_applies(messages):
        return None
    import assistant_catalog
    import qualification_state
    client = '\n'.join(_literal_price_scope(m.get('body') or m.get('text') or '')
                       for m in current_enquiry_messages(messages) if m.get('direction') == 'in')
    service = assistant_catalog.choose(client, known)
    ids = {item['id'] for item in service.get('items', [])}
    if service['status'] != 'supported':
        return None
    wire = r'(?:провод|кабел)\w*'
    operation = r'(?:нараст\w*|наращ\w*|опресс?ова\w*|обжать|соединить)'
    active_wire = any(re.search(operation + r'[^.!?\n]{0,35}' + wire + r'|' + wire + r'[^.!?\n]{0,65}' + operation, c, re.I)
                      and not re.search(r'\bне\s+(?:нужно|надо|хочу|требуется)|\bне\s+' + operation, c, re.I)
                      for c in client.split('\n'))
    if (active_wire and ids and ids <= {'electric', 'sockets'}
            and not re.search(r'интернет|оптоволок|вит\w*\s+пар|rj.?45|патч.?корд|сетев\w*\s+кабел|'
                              r'\b(?:еще|ещё|отдельно|также)\b[^.!?\n]{0,45}(?:розетк|выключател|щит|автомат)', client, re.I)):
        return dict(kind='wire', amount=800, unit=' за метр', rules=['DOC-L0308', 'DOC-L0313'])
    tap_work = any(re.search(r'(?:заменить|поменять|установить|ремонтировать|починить)\s+(?:сам\s+)?(?:смесител|кран)\w*|'
                             r'(?:смесител|кран)\w*[^.!?\n]{0,25}(?:заменить|поменять|установить|ремонтировать|починить)', c, re.I)
                   and not re.search(r'\bне\s+(?:нужно|нудно|надо|хочу|требуется)|\bне\s+(?:менять|заменять)', c, re.I)
                   for c in client.split('\n'))
    if (ids and ids <= {'plumbing-tap', 'plumbing-small'} and not tap_work
            and qualification_state.named_hose_work_match(client)):
        return dict(kind='hose', amount=800, unit='', rules=['DOC-L0289', 'DOC-L0290'])
    return None


def _hose_scope_price_objection(text, previous):
    """A same-hose explanation after deferring its price is a follow-up.

    Excluding mixer replacement is not a refusal of the requested hose.
    Require the client's earlier price ask and actual staff price response.
    """
    previous = _price_source_rows(previous)
    import qualification_state
    literal = _literal_price_scope(text)
    if (re.search(r'«|»|“|”|"|\u0027|‘|’|„|\b(?:если|вдруг|допустим|предположим)\b', text, re.I)
            or '?' in text or not qualification_state.named_hose_work_match(literal)
            or not re.search(r'ничего\s+особенного|\bтолько\b|\bвсего\b|нужен\s+ключ', literal, re.I)
            or re.search(r'отказыва|передумал|больше\s+не\s+нуж|не\s+(?:нужно|надо)\s+менять\s+шланг', literal, re.I)):
        return False
    staff = next((i for i in range(len(previous)-1, -1, -1)
                  if previous[i].get('direction') in ('in', 'out')), None)
    if (staff is None or previous[staff].get('direction') != 'out' or previous[staff].get('out_pending')
            or not _price_response(previous[staff].get('body') or previous[staff].get('text') or '')
            or _AMOUNT.search(previous[staff].get('body') or previous[staff].get('text') or '')):
        return False
    earlier = [m.get('body') or m.get('text') or '' for m in previous[:staff] if m.get('direction') == 'in']
    return bool(any(asks(t) for t in earlier) and any(qualification_state.named_hose_work_match(_literal_price_scope(t)) for t in earlier))


def mnc_basis_quote(messages, known, consent_state):
    """An amount alone never verifies the unit or a quote about other work."""
    messages = _price_source_rows(messages)
    index = next((i for i in range(len(messages)-1, -1, -1)
                  if messages[i].get('direction') == 'out' and not messages[i].get('out_pending')
                  and messages[i].get('id') == consent_state.get('message_id')), None)
    if index is None:
        return False
    basis = mnc_price_basis(messages[:index], known)
    if not basis or basis != mnc_price_basis(messages, known):
        return False
    quote = messages[index].get('body') or messages[index].get('text') or ''
    amounts = _AMOUNT.findall(quote)
    if (len(amounts) != 1 or int(amounts[0].replace(' ', '')) != 800 or consent_state.get('amount') != 800
            or re.search(r'«|»|“|”|"|\u0027|‘|’|„|\bне\b|друг\w*\s+мастер|диагност|выезд|вызов|'
                         r'за\s+(?:вс[её]|весь\s+объ[её]м)|итогов|окончатель|фиксирован|ровно|максимум|'
                         r'квадрат|\bм[²2]\b|\bдо\s*\d', quote, re.I)
            or not re.search(r'\bот\s+800\s*(?:руб\w*|₽|р(?=[.\s,!?]|$))', quote, re.I)):
        return False
    # A numerically matching statement about another named job is not this tariff.
    if basis['kind'] == 'wire' and re.search(
            r'(?:замен|установ|ремонт)\w*[^.!?\n]{0,20}(?:розетк|выключател)|'
            r'шланг|смесител|мебел|шкаф|навеск|светильник', quote, re.I):
        return False
    if basis['kind'] == 'hose' and re.search(
            r'провод|кабел|розетк|выключател|мебел|шкаф|навеск|'
            r'(?:замен|установ|ремонт)\w*[^.!?\n]{0,20}смесител', quote, re.I):
        return False
    units = re.findall(r'(?:за\s+|/\s*)(?:погонн\w*\s+метр\w*|метр\w*|м[²2]?\b|час\w*|шт\b|штук\w*|единиц\w*|точк\w*)', quote, re.I)
    if basis['kind'] == 'wire':
        return len(units) == 1 and bool(re.fullmatch(r'за\s+(?:погонн\w*\s+)?метр', units[0], re.I))
    return not units


def _price_followup(text, previous):
    previous = _price_source_rows(previous)
    if _hose_scope_price_objection(text, previous):
        return True
    advance_estimate = (
        r'\s*(?:(?:понял[аи]?|спасибо|хорошо)[.!]\s*)?(?:а\s+)?(?:если\s+)?(?:пока\s+)?(?:только\s+)?'
        r'(?:примерно|ориентировочно|приблизительно),?\s+до\s+(?:выезда|приезда)\s*\?\s*')
    approximate_before_visit = bool(re.fullmatch(advance_estimate, text, re.I))
    expanded = False
    if not approximate_before_visit:
        # A voiced confirmation can precede its own terminal question.
        parts = re.split(r'(?<=[.!])\s+', text.strip())
        prefix = ' '.join(parts[:-1])
        if (re.match(r'\s*(?:да|верно|точно)\b', prefix, re.I)
                and not re.search(
                    r'[?«»“”"]|\b(?:если|теперь|вместо|отмен\w*|друг\w*|'
                    r'мастер\w*|сосед\w*|сказал\w*|спросил\w*|написал\w*)\b|'
                    r'\bне\s+(?:спрашива\w*|интерес\w*)|\b(?:цен[ауые]|стоимост\w*)\b',
                    prefix, re.I)):
            expanded = approximate_before_visit = bool(re.fullmatch(advance_estimate, parts[-1], re.I))
    if not approximate_before_visit and not re.fullmatch(r'\s*(?:(?:а|ну)\s+)?(?:хотя\s+бы\s+)?(?:(?:по)?точнее(?:\s+можно)?|примерно|приблизительно|ориентировочно|(?:я\s+)?(?:люблю|хочу)\s+конкретику)[?!.\s]*', text, re.I):
        return False
    from dialogue_lifecycle import _pause_request
    turn = []
    crossed_pause = False
    for index in range(len(previous) - 1, -1, -1):
        message = previous[index]
        if message.get('direction') == 'in':
            pause = _pause_request(message) if approximate_before_visit and not turn else None
            if not pause or pause.get('completed_information_quote'):
                break
            crossed_pause = True
        if message.get('direction') == 'out':
            turn.append((index, message))
    if expanded or crossed_pause:
        withdrawn = withdrawn_quote_indexes(previous)
        correction = next((i for i, m in turn if _WRONG_CHAT.match(m.get('body', ''))
                           and str(m.get('delivery_status') or m.get('delivery') or '').lower()
                           in ('sent', 'delivered', 'read')), -1)
        turn = [(i, m) for i, m in turn if i > correction and i not in withdrawn
                and str(m.get('delivery_status') or m.get('delivery') or '').lower() in ('sent', 'delivered', 'read')]
    return any(_price_response(m.get('body') or m.get('text') or '') for _, m in turn)


def _city_callout_only_question(question):
    """Separate a city travel fee from other charges in the same turn."""
    literal=re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', str(question or ''))
    if re.search(r'за\s+город|за\s+чертой|километр|\d\s*км\b|'
                 r'сосед\w*|мастер\w*[^.!?]{0,35}(?:сказ|писа)|'
                 r'не\s+(?:спрашива\w*|интересует)',literal,re.I):
        return False
    questions=[c for c in re.split(r'[.!?;\n]+',literal) if asks(c)]
    return bool(questions and all(re.search(r'\bвыезд\b',c,re.I)
                and not re.search(r'\b(?:работ|монтаж|ремонт|диагност|сборк|установ)\w*',c,re.I)
                for c in questions))


def _free_city_callout_answer(text, question):
    """A delivered free city callout does not answer an open work price."""
    return bool(re.search(r'\bвыезд\s+в\s+черте\s+города\s+бесплатн\w*',text,re.I)
                and _city_callout_only_question(question))


def _unanswered_price(messages):
    messages = _price_source_rows(messages)
    pending = False
    pending_question = ''
    withdrawn = withdrawn_quote_indexes(messages)
    for i, m in enumerate(messages):
        body = str(m.get('body') or m.get('text') or '')
        if m.get('direction') == 'in':
            if re.fullmatch(r'\s*\?+[!.\s]*', body):
                continue  # Repeated punctuation is a reminder, not a new ask.
            if asks(body) or _price_followup(body, messages[:i]):
                pending = True
                pending_question = body
            elif ('?' in body or re.search(r'не\s+актуаль|не\s+нуж|передумал|до\s+свидания|позже\s+напиш|пока\s+не\s+надо', body, re.IGNORECASE)):
                pending = False  # A different current question or closure wins.
        elif (i not in withdrawn and m.get('direction') == 'out'
              and (_price_response(body) or _free_city_callout_answer(body,pending_question))):
            pending = False
    return pending


def asks(text):
    # A separate duration question must not erase an explicit price question.
    # For this additional path, quoted/attributed or negated price words are
    # not an independent request. Existing tariff recognition stays below.
    own = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', text)
    callout = r'(?:выезд|вызов|приезд)'
    if re.search(rf'(?:^|[.!?;\n])\s*(?:а\s+)?(?:'
                 rf'{callout}\s+(?:отдельно\s+)?(?:не\s+)?оплачивается(?:\s+отдельно)?'
                 rf'|оплачивается\s+ли\s+{callout}(?:\s+отдельно)?)\s*\?', own, re.I):
        return True
    for clause in re.split(r'[.!?;\n]+',own):
        match = re.search(r'\bсколько\s+(?:будет\s+)?сто(?:ит|ят|ить)\b|'
                          r'\bот\s+скольк(?:и|их)\s+(?:руб\w*|₽)(?=\W|$)', clause, re.I)
        if (match and not re.search(r'не\s+(?:спрашиваю|нужно|интересует)|'
                r'(?:мастер|сосед|сотрудник)\w*[^.!?]{0,30}(?:сказал|спросил|написал)',clause[:match.start()],re.I)):
            return True
    if re.search(r'\bбер[её]те\b[^.!?\n]{0,25}\b(?:деньги|оплату)\b[^.!?\n]{0,20}(?:выезд|вызов|приезд)', text, re.I):
        return True
    if re.search(r'диагност\w*.{0,20}\d+\s*(?:руб\w*|р\.?|₽)\s*\?', text, re.IGNORECASE):
        return True
    if re.search(r"(?:за\s+)?(?:выезд|вызов|диагностик\w*).{0,20}(?:бер[её]те|платн|бесплат|оплат)|(?:платн|бесплат|оплат).{0,20}(?:выезд|вызов|диагностик)", text, re.IGNORECASE):
        return True
    if re.search(r"цен[ауые]|стоим|дорого|бюджет|прайс|сумм", text, re.IGNORECASE):
        return True
    # Remove only the temporal ask; a second independent "сколько стоит"
    # must still be answered. Arrival words are not a service price.
    price_text = re.sub(r'\b(?:во|через)\s+сколько\b[^.!?;\n]{0,35}?'
                        r'(?:приед\w*|приеха\w*|подъех\w*|подъед\w*|ждать\b)',
                        '', text, flags=re.IGNORECASE)
    return bool(
        re.search(r"сколько|\bот\s+скольки\b", price_text, re.IGNORECASE)
        and not re.search(
            r"сколько.{0,18}(?:времен|час|минут|лет|ид[её]т|длится)",
            price_text,
            re.IGNORECASE,
        )
    )


def _confirmed_diagnostic_price_question(messages):
    """A client can clarify that an unanswered price ask concerns diagnosis."""
    messages = _price_source_rows(messages)
    if len(messages)<2 or messages[-1].get('direction')!='in':return ''
    last=str(messages[-1].get('body') or messages[-1].get('text') or '')
    previous=messages[-2];prompt=str(previous.get('body') or previous.get('text') or '')
    if (previous.get('direction')=='out' and not previous.get('out_pending')
            and re.fullmatch(r'\s*(?:выезд\s+и\s+)?диагностик[аи]\s*\?[.!\s]*',prompt,re.I)
            and re.fullmatch(r'\s*(?:да|ага|конечно)(?:[,!\s]+конечно)?[.!\s]*',last,re.I)
            and _unanswered_price(messages[:-2])):
        return 'Сколько стоит диагностика?'
    return ''


def asks_current(messages):
    """Keep an unanswered price ask through qualification, never a new question."""
    messages = _price_source_rows(messages)
    incoming = [str(m.get('body') or m.get('text') or '') for m in messages if m.get('direction') == 'in']
    if not incoming:
        return False
    if _confirmed_diagnostic_price_question(messages):
        return True
    state = consent(messages)
    agreed = next((m for m in messages if m.get('id') == state.get('accepted_message_id')), {})
    if state.get('status') == 'accepted' and agreed:
        quote = next((m.get('body') or m.get('text') or '' for m in messages if m.get('id') == state.get('message_id')), '')
        first, *tail = re.split(r'[.!;\n]+', agreed.get('body') or agreed.get('text') or '', maxsplit=1)
        statement = dict(agreed, body=first)
        index = messages.index(agreed)
        if (_accepts_named_price(first, state['amount'], quote)
                or _accepts_bt_primary_terms(statement, state['amount'], quote)
                or _accepts_tv_total_terms(statement, state['amount'], quote)
                or _accepts_assembly_minimum(messages, index, state['message_id'], state['amount'], quote)
                or _accepts_curtain_unit(messages, index, state['message_id'], state['amount'], quote)):
            if not tail or not asks(tail[0]):
                # Only this boolean predicate gets a semantic price view.
                # The original source, IDs/delivery and model input are never
                # rewritten. A later readiness turn must not revive the price
                # word in an already recognized consent as an unanswered ask.
                messages = [dict(m, body=tail[0] if tail else '', text=tail[0] if tail else '') if m is agreed else m for m in messages]
                incoming = [str(m.get('body') or m.get('text') or '') for m in messages if m.get('direction') == 'in']
    if asks(incoming[-1]):
        return True
    current_index = next(i for i in range(len(messages)-1, -1, -1) if messages[i].get('direction') == 'in')
    if _price_followup(incoming[-1], messages[:current_index]):
        return True
    if re.fullmatch(r'\s*(?:(?:а|ну)\s+)?(?:хотя\s+бы\s+)?(?:примерно|приблизительно|ориентировочно)[?!.\s]*', incoming[-1], re.IGNORECASE):
        seen_latest = False
        for message in reversed(messages):
            if message.get('direction') == 'out':
                if _GREETING_ONLY.fullmatch(str(message.get('body') or message.get('text') or '')):
                    continue
                break
            if message.get('direction') != 'in':
                continue
            body = str(message.get('body') or message.get('text') or '')
            if not seen_latest:
                seen_latest = True
                continue
            if asks(body) or '?' in body:
                return asks(body)
    previous_out = next((str(m.get('body') or m.get('text') or '') for m in reversed(messages) if m.get('direction') == 'out'), '')
    if ('?' in incoming[-1] and re.search(r"за\s+(?:вс[её]|\d+\s*шт|одн[уа]|единиц)", incoming[-1], re.IGNORECASE)
            and re.search(r"\d[\d ]*\s*(?:руб|₽|р(?=[.\s,!?]|$))", previous_out, re.IGNORECASE)):
        return True
    if re.fullmatch(r"\s*(?:на\s+)?(?:мой\s+)?вопрос\s+ответьте(?:\s+(?:пжл|пожалуйста))?[.!\s]*", incoming[-1], re.IGNORECASE):
        previous = next((body for body in reversed(incoming[:-1]) if '?' in body or asks(body)), '')
        return asks(previous)
    latest = next((m for m in reversed(messages) if m.get('direction') == 'in'), {})
    # A text answer about availability/materials, like a picture, supplements
    # the still unanswered request. A different question/closure resets it in
    # _unanswered_price; this is not permission to ignore that newer question.
    if incoming[-1].strip() or latest.get('attachments') or latest.get('media_signature') or latest.get('media_reviewed'):
        return _unanswered_price(messages)
    return False


def conditional_diagnostic_question(messages):
    messages = _price_source_rows(messages)
    incoming = [m.get('body', '') for m in messages if m.get('direction') == 'in']
    if not incoming:
        return False
    last = incoming[-1]
    conditional = re.search(r"если|допустим|не\s*выгод|не\s*целесообраз|не\s*ремонтопригод|не\s*получится", '\n'.join(incoming[-3:]), re.IGNORECASE)
    payment = re.search(r"(?:плат|оплат|отда|должен|нужно\s+будет).{0,40}\d|\d.{0,40}(?:плат|оплат|отда|должен)|диагностик", last, re.IGNORECASE)
    price_refusal = re.search(r'если.{0,30}не\s+(?:подойд[её]т|устроит).{0,20}(?:цен|стоим)|'
                              r'если.{0,30}(?:цен|стоим).{0,25}не\s+(?:подойд[её]т|устроит)', last, re.I)
    unresolved_repair = re.search(r'не\s*выгод|не\s*целесообраз|не\s*ремонтопригод|не\s*(?:получится|сможете|сможет)|'
                                  r'невозможн|не\s+подлежит\s+ремонту', '\n'.join(incoming[-3:]), re.I)
    voluntary_refusal = re.search(
        r'\b(?:ремонт\w*\s+(?:делать\s+)?не\s+буд(?:у|ем)|'
        r'(?:я|мы)\s+не\s+буд(?:у|ем)\s+(?:делать\s+)?ремонт\w*|'
        r'(?:я|мы)\s+откаж(?:усь|емся)\s+от\s+ремонт\w*)\b', last, re.I)
    if (price_refusal or voluntary_refusal) and not unresolved_repair:
        return False  # TG1-611 explicitly covers voluntarily declining work.
    return bool(conditional and payment and ('?' in last or asks(last)))


def current_price_question(messages):
    messages = _price_source_rows(messages)
    clarified=_confirmed_diagnostic_price_question(messages)
    if clarified:return clarified
    incoming = [str(m.get('body') or m.get('text') or '') for m in messages if m.get('direction') == 'in']
    last = incoming[-1] if incoming else ''
    if not asks_current(messages):
        return last
    turn = []
    for message in reversed(messages):
        if message.get('direction') == 'out':
            break
        if message.get('direction') == 'in':
            turn.append(str(message.get('body') or message.get('text') or ''))
    current = '\n'.join(reversed(turn))
    if asks(current):
        return current  # Cost + travel-fee asks may be separate chat bubbles.
    return next((body for body in reversed(incoming[:-1]) if asks(body)), last)


def price_question_subject(text):
    """A device diagnostic/status screen does not ask for a diagnostic fee."""
    text = re.sub(r'\bдиогност','диагност',text,flags=re.I)
    text = re.sub(r'\b(?:вызов|приезд(?:а|у|ом|е)?)\b', 'выезд', text, flags=re.I)
    return re.sub(r'\b(?:(?:в|при|на)\s+)?диагностик[аеуи]\s+(?:пишет|показывает|выда[её]т|сообщает)\b',
                  '[DEVICE_STATUS]', text, flags=re.I)


def _pc_transfer_scope(text):
    if device(text) != 'pc' or not re.search(r"перен[ое]с\w*.{0,25}данн", text, re.IGNORECASE):
        return None
    volumes = [float(v.replace(',', '.')) for v in re.findall(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(?:гб|gb|гиг\w*)\b", text, re.IGNORECASE)]
    # Include upper endpoints expressed as '20–30 ГБ' or 'гигов 20–30'.
    volumes += [float(v.replace(',', '.')) for v in re.findall(r"\bгиг\w*\s+(\d+(?:[.,]\d+)?)", text, re.IGNORECASE)]
    volumes += [float(v.replace(',', '.')) for v in re.findall(r"\bгиг\w*\s+\d+(?:[.,]\d+)?\s*[-–—]\s*(\d+(?:[.,]\d+)?)", text, re.IGNORECASE)]
    carrier = r"(?:hdd\b|ssd\b|ж[её]стк\w*\s+диск\w*|диск\w*)"
    from_to = re.search(r"\bс(?:о)?\s+(?:стар\w*\s+)?" + carrier + r".{0,25}\bна\s+(?:нов\w*\s+)?" + carrier, text, re.IGNORECASE)
    if any(v > 10 for v in volumes) or re.search(r"\d\s*(?:тб|tb|терабайт)|больше\s+10|свыше\s+10", text, re.IGNORECASE):
        return 'over_limit'
    if not volumes or not from_to:
        return 'unconfirmed'
    return 'within_limit'


def asks_to_confirm_previous_total(messages):
    """A prior human quote is a commitment to inspect, not a new tariff question."""
    messages = _price_source_rows(messages)
    last = next((m.get("body", "") for m in reversed(messages) if m.get("direction") == "in"), "")
    if not (asks(last) or "?" in last or re.search(r"правильн|верно|уточн|подтверд", last, re.IGNORECASE)):
        return False
    reported_our_quote = re.search(
        r'\bвы\s+(?:(?:мне|нам|уже|раньше|ранее|вчера)\s+){0,3}'
        r'(?:обещали|называли|назвали|говорили|сказали|писали|озвучивали|озвучили)\b', last, re.I)
    price_reference = re.search(r'\d[\d ]*\s*(?:руб\w*|₽|р(?=[.\s,!?]|$))|\b(?:цен\w*|стоим\w*|сумм\w*)\b', last, re.I)
    if reported_our_quote and price_reference:
        return True  # A client's report is not proof of our earlier promise.
    if not re.search(r"за\s+вс[её]|итого|итогов|окончатель|сумм|больше|ровно|максимум|максимальн|не\s+более|без.{0,12}доплат", last, re.IGNORECASE):
        return False
    quoted_total = any(
        m.get("direction") == "out" and re.search(r"\d[\d ]*\s*(?:руб|₽|р(?=[.\s]|$))|\bот\s*\d+\b(?!\s*(?:час|минут|дн|день|метр|шт\b))", m.get("body", ""), re.IGNORECASE)
        and not re.search(r'\bот\s+\d', m.get('body', ''), re.I)
        for m in messages
    )
    asks_for_commitment = re.search(r'за\s+вс[её]|итого|итогов|окончатель|ровно|максимум|максимальн|не\s+более|без.{0,12}доплат', last, re.I)
    return bool(quoted_total or asks_for_commitment and any(
        m.get('direction') == 'out' and re.search(r'\d\s*(?:руб|₽)|\bот\s+\d', m.get('body', ''), re.I) for m in messages))


def unqualified_price_range(messages):
    """A bare range after a cost answer has no confirmed currency or scale."""
    messages = _price_source_rows(messages)
    last = next((m.get('body', '') for m in reversed(messages) if m.get('direction') == 'in'), '')
    previous = next((m.get('body', '') for m in reversed(messages) if m.get('direction') == 'out'), '')
    return bool(re.fullmatch(r'\s*от\s*\d+(?:[.,]\d+)?\s*до\s*\d+(?:[.,]\d+)?[?!.\s]*', last, re.I)
                and _price_response(previous)
                and not re.search(r'когда|во\s+сколько|в\s+какое\s+время', previous, re.I))


# Current KP document, price table. Each scope disambiguates identical services.
TARIFFS = [
    ("windows", "pc", r"windows|\bвинд(?:оус|овс|а|у|ы|е|ой|ою)\b|виндоус|установ.*\bос\b", 2000, "KP-L0538"),
    ("office", "pc", r"office|майкрософт.*офис|пакет.*офис", 2000, "KP-L0539"),
    ("cleaning", "pc", r"чистк|термопаст", 2000, "KP-L0540"),
    ("drivers", "pc", r"драйвер", 3000, "KP-L0541"),
    ("antivirus", "pc", r"антивирус", 1000, "KP-L0542"),
    (
        "pc_assembly",
        "pc",
        r"сборк.*(?:пк|компьютер)|собра[тть].*(?:пк|компьютер)",
        3000,
        "KP-L0543",
    ),
    (
        "pc_part",
        "pc",
        r"замен.*(?:ssd|ссд|ж[её]стк.*диск|оперативн|блок питан)",
        1000,
        "KP-L0544",
    ),
    (
        "pc_apps",
        "pc",
        r"установ.*(?:программ|браузер|winrar|архиватор)",
        1000,
        "KP-L0545",
    ),
    ("bios", "pc", r"bios|биос", 3500, "KP-L0546"),
    (
        "pc_transfer",
        "pc",
        r"перен[ое]с.*данн.*(?<!\d)(?:[1-9]|10)\s*(?:гб|gb)\b",
        1500,
        "KP-L0547",
    ),
    ("tv_channels", "tv", r"настро.*канал", 1500, "KP-L0549"),
    ("tv_firmware", "tv", r"прошив|прошит", 2500, "KP-L0550"),
    ("tv_box", "tv", r"настро.*(?:приставк|ресивер|тюнер)", 1500, "KP-L0551"),
    ("printer_setup", "printer", r"подключ|настрой|настроит", 1000, "KP-L0553"),
    ("printer_service", "printer", r"обслужив|профилактик", 4000, "KP-L0554"),
    ("printer_head", "printer", r"чист.*(?:головк|дюз)", 1500, "KP-L0555"),
    ("printer_counter", "printer", r"памперс|счетчик|сч[её]тчик", 2000, "KP-L0556"),
    ("phone_apps", "phone", r"установ.*приложен", 1000, "KP-L0561"),
    (
        "phone_setup",
        "phone",
        r"настро.*(?:телефон|планшет|смартфон)|сброс.*настро|созда.*аккаунт",
        2500,
        "KP-L0562",
    ),
    ("phone_transfer", "phone", r"перен[ое]с.*данн", 1500, "KP-L0563"),
]


def device(text):
    text = re.sub(r'\bпо\s+телефону\b', '[COMMUNICATION]', text, flags=re.IGNORECASE)
    import assistant_catalog
    if assistant_catalog.gpu_software_only(text):
        return 'pc'
    for name, pattern in [
        ("printer", r"принтер|мфу|(?:сброс|обнул).{0,30}памперс"),
        ("phone", r"смартфон|телефон|планшет|айфон|iphone|ipad"),
        ("tv", r"телевиз|\bтв\b|ресивер|тюнер|тв.приставк"),
        ("pc", r"компьютер|ноутбук|\bпк\b|моноблок|windows|office|bios|\bвинд(?:оус|овс|а|у|ы|е|ой|ою)\b"),
    ]:
        if re.search(pattern, text, re.IGNORECASE):
            return name
    if assistant_catalog.office_installation_request(text):
        return 'pc'
    return ""


def select_tariff(text):
    kind = device(text)
    found = [
        (name, amount, ref)
        for name, scope, pattern, amount, ref in TARIFFS
        if scope == kind and re.search(pattern, text, re.IGNORECASE)
        and (name != 'pc_transfer' or _pc_transfer_scope(text) == 'within_limit')
    ]
    import assistant_catalog
    if kind == 'pc' and assistant_catalog.office_installation_request(text) and not any(row[0] == 'office' for row in found):
        found.append(('office', 2000, 'KP-L0539'))
    if kind == 'pc' and _multiple_pc_replacements(text):
        # KP-L0543 includes replacing several components, even when the
        # customer never calls the job an assembly. One-part pricing must not
        # compete with that same job. Independent software services still do.
        found = [row for row in found if row[0] not in ('pc_part', 'pc_assembly')]
        found.append(('pc_assembly', 3000, 'KP-L0543'))
    return found[0] if len(found) == 1 else None


def _multiple_pc_replacements(text):
    """A positive replacement list, not an inventory or a repair diagnosis."""
    parts = {
        'psu': r'(?:блок\s+питания|бп)',
        'cpu': r'процессор\w*',
        'board': r'(?:мат(?:еринск\w*)?\s*плат\w*)',
        'ram': r'(?:оперативн\w*\s+памят\w*|озу|ram)',
        'ssd': r'(?:ssd|ссд)',
        'hdd': r'(?:hdd|ж[её]стк\w*\s+диск\w*)',
    }
    part = r'\b(?:' + '|'.join(parts.values()) + r')\b'
    for clause in re.split(r'[.!?;\n]+', text):
        request = re.search(r'\b(?:поменять|заменить|замена)\b(.{0,200})', clause, re.I)
        if not request:
            continue
        body = request[1]
        if re.search(r'\b(?:не|или|либо|только|оставить|оставляем|уже|есть|имеется|имеются|исправ\w*|в\s+наличии)\b', body, re.I):
            continue
        if not re.search(part + r'\s*(?:,\s*(?:и\s+)?|и\s+)' + part, body, re.I):
            continue
        categories = {key for key, pattern in parts.items()
                      if re.search(r'\b' + pattern + r'\b', body, re.I)}
        if len(categories) >= 2:
            return True
    return False


def clarify_named_tariff(messages, known):
    """Correct a human's approximate amount only against the current exact scope.

    This is not permission to certify an old total, bundle, or different amount.
    Normal first-time pricing stages remain unchanged.
    """
    messages = _price_source_rows(messages)
    if known.get('direction') == 'bt':
        latest = next((m.get('body', '') for m in reversed(messages) if m.get('direction') == 'in'), '')
        state = consent(messages)
        quoted = manual_service_minimum(messages, known, state)
        money = _AMOUNT.findall(latest)
        if (quoted and '?' in latest and len(money) == 1
                and int(money[0].replace(' ', '')) == quoted['amount']
                and re.match(r'\s*(?:(?:то\s+есть|это|получается)\s+)?\d', latest, re.I)):
            return dict(reply='От 800 рублей — минимальная стоимость работы, а не фиксированная цена замены. '
                              'Объём ремонта и точную стоимость определю после осмотра.',
                        amounts=[800], rules=[BT_800_RULE, 'DOC-L0713', 'DOC-L0774'])
    diagnostic = _partner_diagnostic_clarification(messages, known)
    if diagnostic:
        return diagnostic
    if known.get('direction') != 'kp':
        return None
    incoming = [m['body'] for m in messages if m.get('direction') == 'in']
    if not incoming:
        return None
    match = re.fullmatch(r'\s*в\s+районе\s+или\s+(\d{3,5})\s*(?:рублей|руб|р|₽)?[?.!\s]*', incoming[-1], re.IGNORECASE)
    tariff = select_tariff('\n'.join(incoming))
    if not match or not tariff or tariff[0] != 'windows' or int(match[1]) != tariff[1]:
        return None
    previous = next((m['body'] for m in reversed(messages) if m.get('direction') == 'out'), '')
    quote = re.fullmatch(r'\s*(?:в\s+районе|примерно|около)\s+(\d{3,5})\s*(?:рублей|руб|р|₽)\.?\s*(?:будет)?[.!\s]*', previous, re.IGNORECASE)
    if not quote or int(quote[1]) != tariff[1]:
        return None
    return dict(reply='Установка Windows — 2000 рублей. Вас устраивает такая стоимость?',
                amounts=[2000], rules=['KP-L0538', 'TG1-663'])


def _partner_diagnostic_clarification(messages, known):
    messages = _price_source_rows(messages)
    if diagnostic_only_applies(messages):
        return None
    if not _partner_diagnostic_fee_applies(known):
        return None
    state = consent(messages)
    if state['status'] != 'pending' or state['amount'] != 1000:
        return None
    index = next((i for i, m in enumerate(messages) if m.get('direction') == 'out' and m.get('id') == state['message_id']), None)
    if index is None:
        return None
    quoted = messages[index].get('body', '')
    if (not re.search(r'диагност', quoted, re.I) or not re.search(r'бесплат', quoted, re.I)
            or len(_AMOUNT.findall(quoted)) != 1
            or not re.search(r'при\s+отказе\s*[,—-]?\s*1000\s*(?:руб|₽|р)', quoted, re.I)
            or re.search(r'ремонт|работ|услуг', quoted, re.I)
            or not re.search(r'выезд|диагност', price_question_subject(current_price_question(messages[:index])), re.I)):
        return None
    return dict(reply='Выезд и диагностика — 1000 рублей. При выполнении работ они бесплатны. Такие условия вас устраивают?',
                amounts=[1000], rules=['DOC-L0812','DOC-L0813','TG1-611', KP_PARTNER_DIAGNOSTIC_RULE])


def price_turns(messages):
    messages = _price_source_rows(messages)
    messages = current_enquiry_messages(messages)
    turns, pending = 0, False
    prefix = []
    withdrawn = withdrawn_quote_indexes(messages)
    for i, message in enumerate(messages):
        prefix.append(message)
        body = str(message.get('body') or message.get('text') or message.get('content') or '')
        incoming = message.get("direction") == "in" or message.get("role") in (
            "user",
            "client",
        )
        if message.get('direction') == 'out':
            if i not in withdrawn and pending and _price_response(body):
                turns += 1
                pending = False
        elif incoming:
            if _NEW_INTAKE_PRICE_SCOPE.match(body) and _delivered_intake_consent(message):
                turns, pending = 0, False
                prefix = [message]
            pending |= asks(body) or asks_current(prefix)
    return turns + int(pending)




def mandatory(messages, known, client_text):
    messages = _price_source_rows(messages)
    import assistant_catalog
    import contact_facts
    direction = known.get("direction")
    text = client_text.lower()
    clog_messages = current_enquiry_messages(messages)
    clog_context = contact_facts.clog_work_context(clog_messages)
    clog_text = contact_facts.scoped_clog_text(text, clog_context)
    amount, topic, unit = 0, "", ""
    if (
        direction == "kp"
        and "видеокарт" in text
        and not re.search(r"чист|термопаст|термопроклад", text)
        and not assistant_catalog.gpu_software_only(text)
        and contact_facts.graphics_device_scope(current_enquiry_messages(messages)).get('kind') not in ('host_diagnostic','device_uncertain','standalone_diagnostic')
    ):
        amount, topic = 5000, "видеокарт"
    elif (
        direction == "kp"
        and re.search(r"playstation|\bps[345]?\b|\bпс\s*[345]\b|nintendo|steam.deck|xbox", text)
        and re.search(r"чистк|почист|настро", text)
        and any(item['family'] == 'console' for item in assistant_catalog.choose(client_text, known).get('items', []))
    ):
        amount, topic = 1500, "чистка"
    elif re.search(r"телевиз|\bтв\b", text) and re.search(
        r"пайк|гн[её]зд|разъ[её]м|(?:замен|перепа).{0,35}(?:чип|emmc|микросхем)|(?:чип|emmc|микросхем).{0,35}(?:замен|перепа)", text
    ):
        amount, topic = 5000, "пайка"
    elif direction == "mnc" and (re.search(r"засор|прочист.*(?:канализ|труб)", clog_text)
                                 or contact_facts.confirmed_clog(clog_messages, clog_context)):
        amount = 800 if known.get("city") == "Москва" else 500
        topic, unit = "засор", " за погонный метр"
    if not amount:
        return None
    previous = "\n".join(
        str(m.get("body") or m.get("text") or "")
        for m in messages
        if m.get("direction") == "out"
    )
    if topic == 'засор':
        # DOC-L0499 mandates the unit. An unrelated 500-ruble quote or a
        # total without a running-metre basis cannot satisfy this condition.
        quoted = any(re.search(r'(?<!\d)' + str(amount) + r'\s*(?:руб\w*|₽|р\b)\.?[^!?\n]{0,30}погонн\w*\s+метр',
                               str(m.get('body') or m.get('text') or ''), re.I)
                     for m in messages if m.get('direction') == 'out' and not m.get('out_pending'))
    else:
        quoted = bool(re.search(str(amount) + r"\s*(?:руб|₽)", previous, re.IGNORECASE))
    if quoted:
        return None
    refs = {
        "видеокарт": ["DOC-L0152"],
        "чистка": ["DOC-L0243", "DOC-L0244"],
        "пайка": ["DOC-L0195", "DOC-L0426"],
        "засор": ["DOC-L0499"],
    }[topic]
    if not refs:
        return {"handoff": "Обязательную стоимость нужно сверить с первоисточником"}
    reply = (
        f"Устранение засора — {amount} рублей за погонный метр. Такая стоимость вас устраивает?"
        if topic == "засор"
        else f"Стоимость этой услуги от {amount} рублей{unit}, без учёта запчастей. Такая стоимость вас устраивает?"
    )
    return {"reply": reply, "amounts": [amount], "rules": refs}


def quoted_service_conflict(messages, consent_state):
    """Report only an explicit wrong-service quote, retaining its evidence.

    An amount that matches the general KP minimum does not establish which
    service it buys. Mixed client jobs remain subject to the existing checks;
    they are not labelled a proven contradiction by this narrow detector.
    """
    messages = _price_source_rows(messages)
    index = next((i for i in range(len(messages) - 1, -1, -1)
                  if messages[i].get('direction') == 'out'
                  and messages[i].get('id') == consent_state.get('message_id')), None)
    if index is None:
        return {}
    before = current_enquiry_messages(messages[:index])
    client = '\n'.join(str(m.get('body') or m.get('text') or '')
                       for m in before if m.get('direction') == 'in')
    if device(client) != 'tv' or re.search(r'подшипник|стиральн|посудомо|холодильник|сушильн', client, re.I):
        return {}
    quote = str(messages[index].get('body') or messages[index].get('text') or '')
    amount = _AMOUNT.search(quote)
    if not amount or not re.search(
            r'(?:^|[.!?\n])\s*(?:стоимость\s+)?(?:замен[аыуе]|ремонт[а]?)\s+'
            r'подшипник\w*\s*[:—-]?\s*(?:(?:от|стоит|будет|обойд[её]тся)\s*)?$',
            quote[:amount.start()], re.I):
        return {}
    return dict(message_id=messages[index].get('id'), quote=quote,
                client_service='телевизор', quoted_service='замена подшипников',
                reason='Названа цена за замену подшипников, а клиент обращается по телевизору. '
                       'Уточните ошибочную озвучку с клиентом до создания заявки; стоимость подсветки по прайсу не обещаем.',
                rules=['TG1-664', 'KP-L0490', 'DOC-L0774', 'DOC-L0777'])


def _backlight_price_stage(messages):
    """Only an actual price response advances the scoped backlight flow.

    Questions about damage, contacts or visit time do not answer a customer's
    price objection. TG1-664 still forbids a fixed tariff at every stage.
    """
    messages = _price_source_rows(messages)
    completed, pending = 0, False
    withdrawn = withdrawn_quote_indexes(messages)
    for i, message in enumerate(messages):
        body = str(message.get('body') or message.get('text') or '')
        if message.get('direction') == 'in':
            pending = pending or asks(body)
        elif i not in withdrawn and message.get('direction') == 'out' and pending:
            general = re.search(r'после\s+осмотра|(?:на|по)\s+мест[еу].{0,45}(?:цен|стоим|сориентир|обсуд)|(?:цен|стоим).{0,50}(?:осмотр|смотр|объ[её]м)',body,re.IGNORECASE)
            money = re.search(r'\d\s*(?:руб|₽|р(?=[\s.!?,]|$))',body,re.IGNORECASE)
            minimum = re.search(r'\bот\s+500\s*(?:руб|₽|р(?=[\s.!?,]|$))',body,re.IGNORECASE)
            conflict = quoted_service_conflict(messages[:i+1], dict(message_id=message.get('id')))
            if not conflict and (completed == 0 and general and not money or completed == 1 and minimum):
                completed += 1
                pending = False
    return min(3, completed + 1)


def _mnc_work_answer(messages, known, client_text, last):
    """One price-stage path for both work-only and combined callout questions."""
    import assistant_catalog
    service = assistant_catalog.choose(client_text, known)
    if service['status'] != 'supported' or not service['items']:
        return {'handoff': 'Вид работ и условия приёма не подтверждены'}
    floors = dict(MNC_SERVICE_MINIMA)
    if assistant_catalog.furniture_repair_request(client_text):
        floors['furniture'] = (1500, FURNITURE_REPAIR_MIN_RULE)
    elif not assistant_catalog.furniture_assembly_request(client_text):
        floors.pop('furniture')
    matches = [floors[item['id']] for item in service['items'] if item['id'] in floors]
    stage = price_turns(messages)
    tariff = mnc_fixed_tariff(messages, known, include_ambiguity=True) if stage >= 3 else None
    if tariff:
        if tariff.get('handoff'):
            return tariff
        quantity = tv_mount_quantity(messages, tariff)
        if quantity and re.search(r'\bоба\b|\bобоих\b|\bдвух\b|вместе|общ\w*\s+стоим|за\s+вс[еёх]', last, re.I):
            total = quantity['count'] * tariff['amount']
            return dict(reply=_tv_total_reply(tariff, quantity), amounts=[total, tariff['amount']],
                        rules=tariff['rules'] + ['DOC-L0738'], tariff_kind='fixed_service_total',
                        tariff=tariff, quantity=quantity)
        return dict(reply=f"{tariff['label']} — {tariff['amount']} рублей за {tariff['unit']}, без учёта материалов. Вас устраивает такая стоимость?",
                    amounts=[tariff['amount']], rules=tariff['rules'] + ['DOC-L0738'],
                    tariff_kind='fixed_service_unit', tariff=tariff)
    basis = mnc_price_basis(messages, known)
    # A repeat objection about this explicit work needs its actual minimum,
    # preserving the documented unit rather than suggesting a job total.
    if basis and stage >= 2:
        label = 'Работы с проводами' if basis['kind'] == 'wire' else 'Замена шланга'
        return dict(reply=f"{label} — от {basis['amount']} рублей{basis['unit']}. Точную стоимость скажу после осмотра. Вас устраивают такие условия?",
                    amounts=[basis['amount']], rules=basis['rules'] + ['DOC-L0739', 'DOC-L0740', 'DOC-L0741'])
    if stage == 2 and known.get('city') and len(service['items']) == 1:
        stage_rules = ['DOC-L0718', 'DOC-L0719', 'DOC-L0720', 'DOC-L0721', 'DOC-L0722']
        later_rules = ['DOC-L0736', 'DOC-L0737', 'DOC-L0739', 'DOC-L0740']
        return dict(reply='До осмотра могу сориентировать только по выезду. Выезд в черте города бесплатный, а стоимость работы смогу назвать после осмотра.',
                    amounts=[], rules=['DOC-L0722', 'DOC-L0757', MNC_FREE_CALLOUT_RULE],
                    work_price_stage=dict(stage=2, work_price='after_inspection',
                                          rule_ids=stage_rules, later_rule_ids=later_rules))
    if stage < 3:
        return {
            "reply": "Точную стоимость скажу после осмотра.",
            "amounts": [],
            "rules": ["DOC-L0713", "DOC-L0715", "DOC-L0736", "DOC-L0741"],
        }
    if not matches:
        return {"handoff": "Не подтверждены вид работ и единица расчёта"}
    if len(matches) != 1 or len(service["items"]) != 1:
        return {"handoff": "Нельзя назвать цену одной услуги за весь список работ: стоимость и единицы расчёта проверяет оператор"}
    amount, ref = matches[0]
    stage_rules = ['DOC-L0736', 'DOC-L0737', 'DOC-L0739', 'DOC-L0740', ref]
    return {
        "reply": f"Стоимость услуги от {amount} рублей, без учёта материалов. Такая стоимость вас устраивает?",
        "amounts": [amount],
        "rules": [ref],
        "work_price_stage": dict(stage=3, work_price='service_minimum', rule_ids=stage_rules),
    }


def answer(messages, known, client_text):
    """Return an approved text+rule, or a reason requiring an operator."""
    messages = _price_source_rows(messages)
    partner = str(known.get("partner") or "").lstrip("0")
    direction = known.get("direction")
    if direction == 'bt':
        # The existing diagnosis-only scope must not swallow a new question
        # about city travel. It does not make the diagnosis itself free.
        import contact_facts
        latest = next((m for m in reversed(messages)
                       if contact_facts._client_intent_message(m)
                       and m.get('role') not in ('system', 'assistant')
                       and m.get('speaker_role', 'client') == 'client'
                       and not m.get('out_pending')
                       and str(m.get('delivery_status') or m.get('delivery') or '').lower()
                       not in ('failed', 'pending', 'queued', 'sending', 'error', 'cancelled', 'canceled')), {})
        if _city_callout_only_question(latest.get('body')):
            if not known.get('city'):
                return dict(handoff='Сначала нужно уточнить город и территорию выезда',rules=['DOC-L0757'])
            return dict(reply='Выезд в черте города бесплатный.', amounts=[], rules=['DOC-L0757'])
    if direction == 'mnc' and diagnostic_only_applies(messages):
        return _mnc_callout(known)
    if direction in ('kp','bt') and diagnostic_only_applies(messages):
        latest = next((m.get('body','') for m in reversed(messages) if m.get('direction') == 'in'), '')
        repair_question = any(asks(c) and re.search(r'ремонт|почин', c, re.I)
                              and not re.search(r'диагност', c, re.I) for c in re.split(r'[.!?\n]+',latest))
        note = ' Стоимость ремонта определю после осмотра.' if repair_question else ''
        if direction == 'bt':
            return _bt_diagnostic_quote(note)
        return dict(reply='Диагностика без ремонта — от 500 рублей.' + note, amounts=[500],
                    rules=[DIAGNOSTIC_ONLY_RULE,'DOC-L0257'] + (['DOC-L0713'] if repair_question else []))
    tariff = select_tariff(client_text)
    last = price_question_subject(current_price_question(messages))
    if direction == 'kp' and asks_current(messages):
        import contact_facts
        if contact_facts.standalone_printer_diagnostic(current_enquiry_messages(messages)):
            latest = next((m.get('body', '') for m in reversed(messages) if m.get('direction') == 'in'), '')
            if (asks(latest) and re.search(r'ремонт|почин|заправ|подключ|настрой', latest, re.I)
                    and not re.search(r'диагност|выезд', latest, re.I)):
                last = price_question_subject(latest)
            elif not re.search(r'диагност|выезд|ремонт|почин|заправ|подключ|настрой', last, re.I):
                last = 'Сколько стоит диагностика?'
    if direction == 'kp':
        transfer = _pc_transfer_scope(client_text)
        if transfer == 'over_limit':
            return {'handoff': 'Объём переноса данных превышает 10 ГБ: тариф 1500 и общий минимум не подтверждают стоимость этой работы', 'rules': ['KP-L0547']}
        if transfer == 'unconfirmed':
            return {'reply': 'Подскажите, какой объём данных нужно перенести и с какого носителя на какой?', 'amounts': [], 'rules': ['KP-L0547']}
    if re.search(r"выезд|диагност", last, re.IGNORECASE):
        repair_price_too = any(asks(clause)
                               and not re.search(r'диагност|выезд', clause, re.I)
                               for clause in re.split(r'[.!?\n]+', last))
        repair_price_too = repair_price_too or bool(re.search(r'\bремонт\b(?:\s+[а-яё-]+){0,2}\s+(?:или|и)\s+диагност',last,re.I))
        repair_price_too = repair_price_too or bool(re.search(r'диагностик\w*[^.!?\n]{0,45}\bи\s+сколько\s+(?:стоит\s+)?ремонт',last,re.I))
        repair_note = (' Стоимость ' + ('работы' if direction == 'mnc' else 'ремонта') + ' определю после осмотра.') if repair_price_too else ''
        if _partner_diagnostic_fee_applies(known):
            return {
                "reply": "Выезд и диагностика бесплатны при выполнении работ. При отказе от работ стоимость составит 1000 рублей." + repair_note,
                "amounts": [1000],
                "rules": ["DOC-L0805", "DOC-L0812", "DOC-L0813", "TG1-611", KP_PARTNER_DIAGNOSTIC_RULE] + (['DOC-L0713'] if repair_price_too else []),
            }
        if direction == 'mnc':
            if repair_price_too and known.get('city'):
                # The travel question must not bypass the same work-price
                # stage, service/unit and consent gates used without travel.
                # Keep the original source timeline, including delivery state.
                work = _mnc_work_answer(messages, known, client_text, last)
                if work.get('handoff'):
                    return work
                callout = _mnc_callout(known)
                if not work.get('amounts'):
                    # Preserve the existing combined first/second-stage
                    # disclosure; add its missing normative context, not a
                    # silently rewritten price or extra qualification step.
                    work['reply'] = callout['reply'] + repair_note
                else:
                    work['reply'] = callout['reply'] + ' ' + work['reply']
                work['rules'] = list(dict.fromkeys(callout['rules'] + work['rules']))
                return work
            return _mnc_callout(known, repair_note)
        if direction in ('bt','kp') and re.search(r'диагност', last, re.IGNORECASE):
            if direction == 'bt':
                return _bt_diagnostic_quote(repair_note)
            kinds = ('Программная диагностика', 'Аппаратная диагностика') if direction == 'kp' else ('Первичная диагностика', 'Техническая диагностика')
            return {'reply': kinds[0] + ' без разбора техники — 500 рублей. ' + kinds[1] + ' с разбором — от 500 рублей. При продолжении работ диагностика бесплатная.' + repair_note,
                    'amounts': [500], 'rules': ['DOC-L0759', 'DOC-L0760', 'DOC-L0761', KP_PARTNER_DIAGNOSTIC_RULE]}
        if direction in ('bt','mnc','kp') and re.search(r'выезд', last, re.I):
            if not known.get('city'):
                return {'handoff': 'Сначала нужно уточнить город и территорию выезда', 'rules': ['DOC-L0757']}
            return {"reply": "Выезд в черте города бесплатный." + repair_note, "amounts": [], "rules": ["DOC-L0757", KP_PARTNER_DIAGNOSTIC_RULE] + (['DOC-L0713'] if repair_price_too else [])}
        return {
            "handoff": "Условия выезда/диагностики зависят от источника и территории"
        }
    if direction == "kp":
        backlight = bool(re.search(r"подсветк",client_text,re.IGNORECASE) and device(client_text)=='tv')
        stage = _backlight_price_stage(messages) if backlight else price_turns(messages)
        if stage <= 1:
            return {
                "reply": "Точную стоимость смогу назвать после осмотра техники.",
                "amounts": [],
                "rules": ["KP-L0474"],
            }
        if stage == 2:
            return {
                "reply": "Такая услуга у меня от 500 рублей, без учёта запчастей. Такая стоимость вас устраивает?",
                "amounts": [500],
                "rules": ["KP-L0484"],
            }
        if backlight:
            # TG1-664 prohibits quoting a fixed backlight tariff. General
            # first/second-stage replies remain governed by KP474–484;
            # KP490–494 explicitly covers work without a fixed price.
            return {
                'reply': 'Не видя телевизор, точную стоимость назвать не смогу. Нужно осмотреть технику и определить объём работы.',
                'amounts': [], 'rules': ['TG1-664','KP-L0490','KP-L0494'],
            }
        if tariff:
            name, amount, source = tariff
            unit = " за одну программу" if name == "pc_apps" else ""
            return {
                "reply": f"Стоимость этой услуги — {amount} рублей{unit}, без учёта запчастей. Вас устраивает такая стоимость?",
                "amounts": [amount],
                "rules": ["USER-20261015-723", "TG1-663", source]
                if partner == "723"
                else ["TG1-663", source],
            }
        return {
            "handoff": "Точная услуга отсутствует в прайсе либо требуется уточнить объём работ",
            "rules": ["TG1-663"],
        }
    if direction == "bt":
        specific = bool(
            re.search(r"подшипник|фреон|компрессор", client_text, re.IGNORECASE)
        )
        if not specific and price_turns(messages) < 3:
            if price_turns(messages) == 2:
                return dict(reply='Выезд в черте города бесплатный, стоимость ремонта определю после осмотра.',
                            amounts=[], rules=['DOC-L0722', 'DOC-L0757', BT_800_RULE])
            return {
                "reply": "Точную стоимость скажу после осмотра техники.",
                "amounts": [],
                "rules": ["DOC-L0713", "DOC-L0715", "DOC-L0736", BT_800_RULE],
            }
        amount = 2000 if specific else BT_WORK_MINIMUM
        return {
            "reply": f"Стоимость услуги от {amount} рублей, без учёта запчастей. Такая стоимость вас устраивает?",
            "amounts": [amount],
            "rules": ["DOC-L0419", "DOC-L0449", "DOC-L0450"]
            if specific
            else [BT_800_RULE],
        }
    if direction == "mnc":
        return _mnc_work_answer(messages, known, client_text, last)
    return {
        "handoff": "Для МНЧ нужно проверить конкретный вид работ, объём и обязательную озвучку"
    }


def manual_plinth_quote(messages, known, consent_state):
    """Verify the primary per-area tariff, independently of bot speech stages.

    The document explicitly says M2 (514–517). Do not silently reinterpret it
    as a running metre, a room total, or a price for additional floor work.
    This validates the human's words, never the customer's acceptance.
    """
    messages = _price_source_rows(messages)
    if known.get('direction') != 'mnc' or not known.get('city'):
        return None
    index = next((i for i in range(len(messages)-1, -1, -1)
                  if messages[i].get('direction') == 'out'
                  and messages[i].get('id') == consent_state.get('message_id')), None)
    if index is None:
        return None
    client = '\n'.join(m.get('body', '') for m in messages[:index] if m.get('direction') == 'in')
    quoted = messages[index].get('body', '')
    import assistant_catalog
    service = assistant_catalog.choose(client, known)
    if service['status'] != 'supported' or [item['id'] for item in service.get('items', [])] != ['plinth']:
        return None
    if (not re.search(r'плинтус|порож', quoted, re.IGNORECASE)
            or re.search(r'за\s+(?:вс[её]|весь\s+объ[её]м)|итогов|окончатель|\bот\s+\d|погон|\bп\.?\s*м\b', quoted, re.IGNORECASE)
            or not re.search(r'(?:₽|руб\w*|р\.?)(?:\s*[/·]\s*|\s+(?:за\s+)?|\s*)(?:м[²2]|кв\.?\s*м(?:етр\w*)?|квадратн\w*\s+метр\w*)(?!\w)', quoted, re.IGNORECASE)):
        return None
    screws = re.search(r'клипс|саморез|шуруп', quoted, re.IGNORECASE)
    glue = re.search(r'клей|клеить', quoted, re.IGNORECASE)
    if not screws and not glue:
        return None
    import territory
    moscow = territory.price_column(known.get('city')) == 'msk'
    amount, refs = ((800 if moscow else 600, ['DOC-L0517']) if screws and glue else
                    (500 if moscow else 400, ['DOC-L0514', 'DOC-L0515']) if screws else
                    (600 if moscow else 500, ['DOC-L0516']))
    # A second money amount in the same message could be another service or
    # a total. Leave that ambiguous statement for a human.
    money = re.findall(r'(?<!\d)(\d[\d ]{1,6})\s*(?:руб\w*|₽|р(?=[.\s,!?]|$))', quoted, re.IGNORECASE)
    if len(money) != 1 or int(money[0].replace(' ', '')) != amount or consent_state['amount'] != amount:
        return None
    return dict(amount=amount, unit='м²', rules=refs, message_id=consent_state['message_id'])


def furniture_minimum_quote(messages, known, consent_state):
    """A scoped documented minimum is independent of speech order and consent."""
    messages = _price_source_rows(messages)
    if known.get('direction') != 'mnc':
        return None
    index = next((i for i in range(len(messages)-1, -1, -1)
                  if messages[i].get('direction') == 'out'
                  and messages[i].get('id') == consent_state.get('message_id')), None)
    if index is None:
        return None
    import assistant_catalog
    client = '\n'.join(m.get('body', '') for m in messages[:index] if m.get('direction') == 'in')
    service = assistant_catalog.choose(client, known)
    if service['status'] != 'supported' or [item['id'] for item in service.get('items', [])] != ['furniture']:
        return None
    repair = assistant_catalog.furniture_repair_request(client)
    if not repair and not assistant_catalog.furniture_assembly_request(client):
        return None
    quoted = messages[index].get('body', '')
    amounts = _AMOUNT.findall(quoted)
    if (len(amounts) != 1 or int(amounts[0].replace(' ', '')) != 1500 or consent_state['amount'] != 1500
            or not re.search(r'\bот\s+1500\s*(?:руб\w*|₽|р(?=[.\s,!?]|$))', quoted, re.I)
            or re.search(r'за\s+(?:вс[её]|весь\s+объ[её]м)|итогов|окончатель|'
                         r'(?:за\s+|/\s*)(?:час|метр|м[²2]?\b|шт\b|единиц|штук)|погон|квадратн', quoted, re.I)):
        return None
    return dict(amount=1500, rules=[FURNITURE_REPAIR_MIN_RULE if repair else 'DOC-L0326'],
                message_id=consent_state['message_id'])


def door_minimum_quote(messages, known, consent_state):
    """DOC0367/0368 minima for one confirmed ordinary door-fitting service."""
    messages = _price_source_rows(messages)
    if known.get('direction') != 'mnc':
        return None
    index = next((i for i in range(len(messages)-1, -1, -1)
                  if messages[i].get('direction') == 'out' and messages[i].get('id') == consent_state.get('message_id')), None)
    if index is None:
        return None
    import assistant_catalog
    before = messages[:index]
    client = '\n'.join(m.get('body', '') for m in before if m.get('direction') == 'in')
    service = assistant_catalog.choose(client, known)
    if service['status'] != 'supported' or [item['id'] for item in service.get('items', [])] != ['lock']:
        return None
    interior, entrance = bool(re.search(r'межкомнатн', client, re.I)), bool(re.search(r'входн', client, re.I))
    if interior == entrance:
        return None
    amount, ref = (800, 'DOC-L0367') if interior else (1000, 'DOC-L0368')
    quoted = messages[index].get('body', '')
    amounts = _AMOUNT.findall(quoted)
    if (len(amounts) != 1 or int(amounts[0].replace(' ', '')) != amount or consent_state['amount'] != amount
            or not re.search(r'\bот\s+' + str(amount) + r'\s*(?:руб\w*|₽|р(?=[.\s,!?]|$))', quoted, re.I)
            or re.search(r'за\s+(?:вс[её]|весь\s+объ[её]м)|итогов|окончатель|(?:за\s+|/\s*)(?:час|метр|м[²2]?\b|шт\b|единиц|штук)|погон|квадратн', quoted, re.I)):
        return None
    return dict(amount=amount, rules=[ref], message_id=consent_state['message_id'])


def quote_requires_acceptance(messages, consent_state):
    messages = _price_source_rows(messages)
    quote = next((m.get('body', '') for m in messages
                  if m.get('direction') == 'out' and m.get('id') == consent_state.get('message_id')), '')
    return bool(re.search(r'\bот\s+\d', quote, re.I))


def manual_service_minimum(messages, known, consent_state):
    """Verify a human's documented minimum without importing bot script order.

    One hanging job uses DOC0353; ordinary printer repair uses DOC0743.
    This does not verify a fixed total, travel/diagnostic fee or acceptance.
    """
    messages = _price_source_rows(messages)
    index = next((i for i in range(len(messages)-1, -1, -1)
                  if messages[i].get('direction') == 'out'
                  and messages[i].get('id') == consent_state.get('message_id')), None)
    if index is None:
        return None
    before = current_enquiry_messages(messages[:index])
    client = '\n'.join(m.get('body', '') for m in before if m.get('direction') == 'in')
    import assistant_catalog
    service = assistant_catalog.choose(client, known)
    if service['status'] != 'supported' or len(service.get('items', [])) != 1:
        return None
    item = service['items'][0]
    if known.get('direction') == 'mnc' and item['id'] in MNC_SERVICE_MINIMA and item['id'] != 'furniture':
        amount, ref = MNC_SERVICE_MINIMA[item['id']]
    elif (known.get('direction') == 'kp' and item['family'] == 'printer'
          and not select_tariff(client) and not mandatory(before, known, client)):
        amount, ref = 500, 'DOC-L0743'
    elif (known.get('direction') == 'bt' and not select_tariff(client)
          and not re.search(r'подшипник|фреон|компрессор', client, re.I)
          and not mandatory(before, known, client)):
        amount, ref = BT_WORK_MINIMUM, BT_800_RULE
    else:
        return None
    quoted = messages[index].get('body', '')
    quoted_items = assistant_catalog.choose(_AMOUNT.sub('[MONEY]', quoted), known).get('items', [])
    if {quoted_item['id'] for quoted_item in quoted_items} - {item['id']}:
        return None
    amounts = _AMOUNT.findall(quoted)
    if (len(amounts) != 1 or int(amounts[0].replace(' ', '')) != amount
            or consent_state.get('amount') != amount
            or not re.search(r'\bот\s+' + str(amount) + r'\s*' + _RUBLE_WORD, quoted, re.I)
            or re.search(r'за\s+(?:вс[её]|весь\s+объ[её]м)|итогов|окончатель|фиксирован|'
                         r'(?:за\s+|/\s*)(?:час|метр|м[²2]?\b|шт\b|единиц|штук)|погон|квадратн|'
                         r'диагност|выезд|вызов|не\s+(?:более|больше|дороже)|максимум', quoted, re.I)):
        return None
    return dict(amount=amount, rules=[ref], message_id=consent_state['message_id'])


def manual_price_review(messages, known, consent_state):
    """Explain the exact quote; never silently turn an old total into 'from'."""
    messages = _price_source_rows(messages)
    quoted = next((m.get('body', '') for m in messages if m.get('direction') == 'out'
                   and m.get('id') == consent_state.get('message_id')), '')
    if not quoted:
        return {}
    client = '\n'.join(m.get('body', '') for m in current_enquiry_messages(messages)
                       if m.get('direction') == 'in')
    import assistant_catalog
    service = assistant_catalog.choose(client, known)
    if (known.get('direction') == 'mnc' and service['status'] == 'supported'
            and len(service.get('items', [])) == 1
            and service['items'][0]['id'] in ('hanging', 'tv-mount')
            and consent_state.get('amount') == 800 and not quote_requires_acceptance(messages, consent_state)):
        return dict(message_id=consent_state['message_id'], quote=quoted, amount=800,
                    rule_ids=['DOC-L0353', 'DOC-L0777'],
                    reason='Озвучено 800 рублей как фиксированная цена. По регламенту навеска — от 800 рублей. Уточните условие стоимости у клиента и получите согласие до создания.',
                    recovery='Уточню по стоимости: работа — от 800 рублей, точная сумма зависит от объёма. Вас устраивают такие условия?')
    return {}


def partner_visit_terms(messages, known):
    """A repair minimum cannot answer the customer's separate visit-fee ask."""
    messages = _price_source_rows(messages)
    if not _partner_diagnostic_fee_applies(known) or diagnostic_only_applies(messages):
        return None
    asked = None
    answer = None
    for message in current_enquiry_messages(messages):
        text = price_question_subject(message.get('body', ''))
        fee_question = any(asks(clause) and re.search(r'выезд|вызов|вызыва|диагност', clause, re.I)
                           for clause in re.split(r'[.!?\n]+', text))
        if message.get('direction') == 'in' and fee_question:
            asked = message
            answer = None
        elif asked and message.get('direction') == 'out' and re.search(r'выезд|диагност', text, re.I):
            free_work = re.search(r'(?:при|в\s+случае)[^.!?\n]{0,40}(?:ремонт|выполнен|продолжен|оказан)[^.!?\n]{0,40}бесплат|'
                                  r'бесплат\w*[^.!?\n]{0,40}(?:при|в\s+случае)[^.!?\n]{0,25}(?:ремонт|выполнен|продолжен|оказан)', text, re.I)
            refusal_fee = re.search(r'при\s+отказе[^.!?\n]{0,70}1000\s*(?:руб\w*|₽|р\b)|'
                                    r'1000\s*(?:руб\w*|₽|р\b)[^.!?\n]{0,70}при\s+отказе', text, re.I)
            if free_work and refusal_fee:
                answer = message
    if asked is None:
        return None
    return dict(done=answer is not None, question_message_id=asked['id'],
                answer_message_id=answer['id'] if answer else '',
                item='Условия выезда и диагностики партнёра: бесплатно при выполнении работ, 1000 рублей при отказе. Территорию выезда проверьте отдельно',
                rules=['DOC-L0812', 'DOC-L0813', 'TG1-611', KP_PARTNER_DIAGNOSTIC_RULE])


def prior_quote_verified(messages, known, consent_state, *, manual=False):
    """An archived human amount is not an approved tariff by itself.

    Re-evaluate the available context immediately before that quote against
    today's explicit stage/rule. Never derive a tariff from the later answer.
    """
    messages = _price_source_rows(messages)
    index = next((i for i in range(len(messages) - 1, -1, -1)
                  if messages[i].get("direction") == "out"
                  and messages[i].get("id") == consent_state.get("message_id")), None)
    if index is None:
        return False
    before = messages[:index]
    quoted = messages[index].get('body', '')
    if re.search(r'\b(?:с|со)\s+(?:(?:уч[её]том|всеми|нашими)\s+)?(?:материал|запчаст)\w*\b'
                 r'(?!\s+(?:клиента|заказчика)\b)|'
                 r'(?:материал|запчаст)\w*\s+(?:(?:все|уже|тоже|также)\s+)?(?:включен|включён|вход\w*|бесплат)|'
                 r'(?<!не )\b(?:включен|включён|включая)\w*\s+(?:все\s+)?(?:материал|запчаст)', quoted, re.I):
        return False  # A work tariff does not authorize a parts/materials promise.
    fixed_quote = mnc_fixed_quote(messages, known, consent_state)
    if fixed_quote:
        return True
    fixed = mnc_fixed_tariff(before, known)
    if fixed and fixed['key'] == 'bracket' and (len(_AMOUNT.findall(quoted)) > 1 or re.search(
            r'\bза\s+(?:[2-9]\d*|дв[ае]|двух|три|четыре|пять)\b|итого|за\s+вс[её]|комплект', quoted, re.I)):
        return False  # An unverified aggregate cannot fall back to amount membership.
    if mnc_price_basis(before, known):
        return mnc_basis_quote(messages, known, consent_state)
    if known.get('direction') == 'mnc' and re.search(r'диагност', quoted, re.I):
        # Preserve the historic quote for review; never certify a paid MNC
        # diagnostic after the owner's scoped correction.
        return False
    if known.get('direction') == 'kp' and diagnostic_only_applies(before):
        return bool(consent_state.get('amount') == 500 and re.search(r'диагност', quoted, re.I)
                    and re.search(r'\bот\s+500\s*(?:руб\w*|₽|р(?=[\s.!?,]|$))',quoted,re.I)
                    and not re.search(r'1000|бесплат',quoted,re.I)
                    and all(int(x.replace(' ','')) == 500 for x in _AMOUNT.findall(quoted)))
    if quoted_service_conflict(messages, consent_state):
        return False
    if known.get('direction') == 'bt' and manual_service_minimum(messages, known, consent_state):
        return True
    if manual and manual_plinth_quote(messages, known, consent_state):
        return True
    if manual and door_minimum_quote(messages, known, consent_state):
        return True
    if manual and manual_service_minimum(messages, known, consent_state):
        return True
    if known.get('direction') == 'mnc' and not quote_requires_acceptance(messages, consent_state):
        # A general family minimum must not certify an undocumented fixed
        # amount, unit, bundle or diagnosis. Known fixed services were checked
        # above, independently of the bot's objection stages.
        return False
    if known.get('direction') in ('bt','mnc','kp') and re.search(r'диагност', quoted, re.IGNORECASE):
        if known.get('direction') == 'bt':
            return _bt_diagnostic_quote_verified(quoted, consent_state)
        if _partner_diagnostic_fee_applies(known):
            complete = re.search(r'(?:в\s+случае|при).{0,30}(?:ремонт|продолжен|выполнен|оказан).{0,40}бесплат|'
                                 r'бесплатн.{0,45}(?:при|в\s+случае).{0,20}(?:ремонт|продолжен|выполнен|оказан)', quoted, re.I)
            amounts = _AMOUNT.findall(quoted)
            asked = re.search(r'выезд|диагност', price_question_subject(current_price_question(before)), re.I) or _partner_diagnostic_clarification(before, known)
            return bool(consent_state['amount'] == 1000 and len(amounts) == 1 and complete
                        and not re.search(r'\bот\s+1000\b', quoted, re.I) and (asked or manual))
        complete = bool(re.search(r'(?:продолжен|оказан).{0,40}(?:работ|услуг).{0,40}бесплат', quoted, re.IGNORECASE))
        primary = re.search(r'диагностик\w*\s+без\s+разбора|(?:первичн|программн)\w*\s+(?:диагностик|осмотр)', quoted, re.IGNORECASE)
        technical = re.search(r'(?:техническ|аппаратн)\w*\s+диагност|диагностик\w*.{0,20}с\s+разбором', quoted, re.IGNORECASE)
        technical_from = not technical or bool(re.search(r'(?:(?:техническ|аппаратн)\w*\s+диагност|с\s+разбором)[^.!?\n]{0,70}\bот\s+500', quoted, re.IGNORECASE))
        primary_fixed = not primary or not re.search(r'(?:(?:первичн|программн)\w*\s+(?:диагностик|осмотр)|без\s+разбора)[^.!?\n]{0,50}\bот\s+500', quoted, re.IGNORECASE)
        return bool(consent_state['amount'] == 500 and complete and (primary or technical) and technical_from and primary_fixed)
    client = "\n".join(m.get("body", "") for m in before if m.get("direction") == "in")
    # A documented service minimum is a valid human quote even when the bot
    # would first have used a non-numeric objection response. Keep the bot's
    # wording stages, but do not turn them into a ban on an accepted minimum.
    if known.get('direction') in ('mnc', 'kp'):
        import assistant_catalog
        service = assistant_catalog.choose(client, known)
        items = service.get('items', [])
        if service['status'] == 'supported' and len(items) == 1:
            if known.get('direction') == 'mnc' and items[0]['id'] == 'furniture':
                return bool(furniture_minimum_quote(messages, known, consent_state))
            if known.get('direction') == 'mnc' and items[0]['id'] in ('hanging', 'light'):
                # The documented human minimum already verified by the
                # normal form does not depend on the bot's objection order.
                # It is not a fixed total, unit price or client acceptance.
                return bool(manual_service_minimum(messages, known, consent_state))
            from qualification_state import printer_stated_scope
            if (known.get('direction') == 'kp' and items[0]['family'] == 'printer'
                    and printer_stated_scope(before)
                    and printer_stated_scope(messages) == printer_stated_scope(before)
                    and not select_tariff(client)
                    and not mandatory(before, known, client)):
                # Same documented ordinary-service minimum as the manual
                # verifier: still reject a fixed total, fee, wrong unit or task.
                return bool(manual_service_minimum(messages, known, consent_state))
            if manual and (known.get('direction') == 'mnc' and items[0]['id'] in ('hanging', 'tv-mount')
                           or known.get('direction') == 'kp' and items[0]['family'] == 'printer'
                           and not select_tariff(client) and not mandatory(before, known, client)):
                return bool(manual_service_minimum(messages, known, consent_state))
    current = clarify_named_tariff(before, known) or mandatory(before, known, client) or answer(before, known, client)
    return not current.get("handoff") and consent_state["amount"] in current.get("amounts", [])


def _repeated_currency_minimum(messages, index):
    """A literal same-minimum repeat can refer to an earlier ruble quote.

    This resolves only the missing currency. It does not approve a tariff,
    change the quote ID, confirm acceptance or turn the minimum into a total.
    """
    text = messages[index].get('body', '')
    short = re.fullmatch(r'\s*от\s+(\d{2,6})(?:\s+(?:такая\s+услуга|за\s+работу))?[.!\s]*', text, re.I)
    if not short:
        return False
    withdrawn = withdrawn_quote_indexes(messages[:index])
    for pos in range(index - 1, -1, -1):
        row = messages[pos]
        if not outgoing_reply_observed(row) or pos in withdrawn:
            continue
        body = row.get('body', '')
        if re.search(r'доллар|евро|\busd\b|\beur\b|[$€]', body, re.I):
            return False
        amounts = _AMOUNT.findall(body)
        if amounts:
            return (len(amounts) == 1 and int(amounts[0].replace(' ', '')) == int(short[1])
                    and bool(re.search(r'\bот\s+' + short[1] + r'\s*(?:руб|₽|р\b)', body, re.I)))
    return False


def unverified_bare_quote(messages):
    messages = _price_source_rows(messages)
    messages = current_enquiry_messages(messages)
    latest = False
    for index, message in enumerate(messages):
        if message.get('direction') != 'out':
            continue
        body = message.get('body', '')
        if re.search(r'\d+\s*(?:руб\w*|₽|р(?=[.\s]|$))', body, re.IGNORECASE):
            latest = False
        elif re.search(r'\bот\s+\d{2,6}\s+стоит\s+(?:прошивк|ремонт|установк|настройк|сборк|чистк)|'
                       r'\bот\s+\d{2,6}\s+работ[аы]\s+(?:будет|стоит|обойд)|'
                       r'\b(?:в\s+районе|примерно|около)\s*\d{2,6}\s+работ[аы]\s+(?:будет|стоит|обойд)|'
                       r'\b(?:работа|сборка|ремонт|установка|настройка|чистка)\s+(?:будет\s+)?от\s+\d{2,6}(?!\d|\s*(?:мм|см|метр))', body, re.IGNORECASE):
            latest = True
        elif re.fullmatch(r'\s*от\s+\d{2,6}(?:\s+(?:такая\s+услуга|за\s+работу))?[\\.!\s]*', body, re.I):
            latest = not _repeated_currency_minimum(messages, index)
    return latest


def consent(messages):
    """Only an explicit client answer after a price establishes acceptance."""
    messages = _price_source_rows(messages)
    messages = current_enquiry_messages(messages)
    amount = 0
    status = "not_quoted"
    quoted_at = None
    accepted_at = None
    quote_text = ''
    answering_price = False
    budget_limit = None
    budget_ambiguity = None
    withdrawn = withdrawn_quote_indexes(messages)
    for i, message in enumerate(messages):
        text = str(message.get("body") or message.get("text") or "")
        if message.get("direction") == "out":
            if i in withdrawn:
                continue
            explanation = (_price_response(text) or _repeated_currency_minimum(messages, i)
                           or bool(re.search(r'\b(?:приеду|подъеду)\b.{0,25}\bпосмотрю\b|'
                                             r'выезд[^.!?\n]{0,30}бесплат|бесплат\w*[^.!?\n]{0,30}выезд', text, re.I)))
            timed_proposal = re.search(r'(?:сегодня|завтра).{0,15}\d|\b(?:в|к)\s*\d{1,2}|\bчерез\b', text, re.I)
            explaining_price = answering_price and explanation and '?' not in text and not timed_proposal
            answering_price = explaining_price or bool(re.search(r"(?:стоимост|цен[аыуе]).{0,25}(?:устраив|соглас|подход)|(?:устраив|соглас).{0,25}(?:стоимост|цен[аыуе])", text, re.IGNORECASE))
            match = _AMOUNT.search(text)
            if match:
                answering_price = True
                amount = int(match.group(1).replace(" ", ""))
                status = "pending"
                quoted_at = message.get("id")
                quote_text = text
                accepted_at = None
        elif message.get('direction') == 'in':
            if re.search(r'\b(?:снимаю|убираю)\s+ограничени|ограничени\w*\s+по\s+(?:бюджету|сумме)\s+нет', text, re.IGNORECASE):
                budget_limit = None
                budget_ambiguity = None
            decimal = re.search(r'\b(?:бюджет|не\s+больше|не\s+более|не\s*дороже|максимум)\s*(\d{1,3}[,.]\d{1,2})(?!\d)',text,re.I)
            if decimal and not re.match(r'\s*(?:мм|см|метр\w*|м2|м²|гб|gb)\b',text[decimal.end():],re.I):
                budget_ambiguity = dict(raw_value=decimal[1],message_id=message.get('id'),quote=text,
                                        reason='Дробная сумма бюджета требует подтверждения единицы и точной суммы')
            thousands=re.search(r'\b(?:бюджет|до|не\s+больше|не\s+более|не\s*дороже|максимум|уложимся\s+в)\s*(\d{1,3}(?:[,.]\d{1,2})?)\s*(?:тыс\w*|тысяч\w*|[кk])\b',text,re.I)
            if thousands:
                cap_amount=round(float(thousands[1].replace(',','.'))*1000)
                if 100<=cap_amount<=999999:
                    budget_limit=dict(amount=cap_amount,message_id=message.get('id'),quote=text)
                    budget_ambiguity=None
            limit = re.search(r'\b(?:бюджет|не\s+больше|не\s+более|не\s*дороже|максимум|если\s+в|уложимся\s+в)\s*(\d[\d \u00a0]{1,8}\d|тысяч[ау])\b', text, re.IGNORECASE)
            quantity = limit and re.match(r'\s*(?:мм|см|метр\w*|кв\.?\s*м|м2|м²|гб|gb)\b', text[limit.end():], re.IGNORECASE)
            if limit and not quantity and (amount > 0 or re.search(r'руб|₽|бюджет|цен|сумм|улож|не\s*дороже', text, re.IGNORECASE)):
                raw_amount = re.sub(r'[ \u00a0]', '', limit[1]).lower()
                cap_amount = 1000 if raw_amount in ('тысяча', 'тысячу') else int(raw_amount)
                if 100 <= cap_amount <= 999999:
                    budget_limit = dict(amount=cap_amount, message_id=message.get('id'), quote=text)
                    budget_ambiguity = None
            # A short monetary shortage is a cap, not acceptance of a minimum.
            # Without a prior price or explicit currency, do not infer rubles.
            literal = re.sub(r'«[^»]*»|"[^"]*"|“[^”]*”', ' ', text)
            shortage = re.search(r'\bбольше\s+(\d[\d \u00a0]{1,8}\d|тысяч[ау])\s*'
                                 r'(?:(?:руб\w*|₽|р[.]?)\s*)?(?:(?:у\s+меня|у\s+нас)\s+)?нет\b', literal, re.I)
            if shortage:
                prefix = re.split(r'[.!?;\n]', literal[:shortage.start()])[-1]
                reported = re.search(r'\b(?:мастер|специалист|сосед|продавец|он|она)\w*\s+'
                                     r'(?:сказал|написал|сообщил|говорит)\w*', prefix, re.I)
                own = re.search(r'\bу\s+(?:меня|нас)\s*$', prefix, re.I) or re.search(r'\bу\s+(?:меня|нас)\b', shortage[0], re.I)
                denied = re.search(r'\bесли\b|\bдопустим\b|не\s+(?:правда|верно|говорил|писал|означает)', prefix, re.I)
                money = amount > 0 or re.search(r'руб|₽|денег|бюджет', shortage[0] + prefix, re.I)
                if money and not denied and (not reported or own):
                    cap = re.sub(r'[ \u00a0]', '', shortage[1]).lower()
                    cap_amount = 1000 if cap in ('тысяча', 'тысячу') else int(cap)
                    if 100 <= cap_amount <= 999999:
                        budget_limit = dict(amount=cap_amount, message_id=message.get('id'), quote=text)
                        budget_ambiguity = None
            if status not in ('pending', 'declined'):
                continue
            other_provider = (re.search(r'друг\w*\s+(?:мастер|специалист)|созвонил\w*.{0,40}специалист', text, re.I)
                              and (_AMOUNT.search(text) or re.search(r'(?:цен|стоим)[^.!?\n]{0,35}(?<!\d)\d{3,6}(?!\d)', text, re.I))
                              and not re.search(r'\bваш|\bу\s+вас\b|(?<!\d)' + str(amount) + r'(?!\d)', text, re.I))
            if not other_provider and re.search(
                r"\b(?:не\s+соглас|не\s+устраив|не\s+подходит|отказыва)", text, re.IGNORECASE
            ):
                status = "declined"
            elif ((answering_price and (_accepts_price(text) or _accepts_diagnostic_terms(message, quote_text)))
                  or _accepts_named_price(text, amount, quote_text)
                  or _accepts_posted_work_terms(messages, i, quoted_at, amount, quote_text)
                  or _accepts_assembly_minimum(messages, i, quoted_at, amount, quote_text)
                  or _accepts_curtain_unit(messages, i, quoted_at, amount, quote_text)
                  or _accepts_bt_primary_terms(message, amount, quote_text)
                  or _accepts_tv_total_terms(message, amount, quote_text)
                  or _accepts_tv_unit_terms(messages, i, quoted_at, amount, quote_text)):
                status = "accepted"
                accepted_at = message.get('id')
    return {"status": 'conditional' if budget_limit or budget_ambiguity else status, "amount": amount, "message_id": quoted_at,
            **({'accepted_message_id': accepted_at} if status == 'accepted' and accepted_at else {}),
            **({'budget_limit': budget_limit} if budget_limit else {}),
            **({'budget_ambiguity': budget_ambiguity} if budget_ambiguity else {})}


def _accepts_posted_work_terms(messages, index, quote_id, amount, quote_text):
    """Extract a fixed work-price agreement, not authorization of its tariff.

    An explicit same-price sentence may name the quoted work and preserve its
    materials exclusion before ordinary contact details. Current-primary and
    scope validation remains the separate prior_quote_verified gate.
    """
    if not quote_id or not _delivered_intake_consent(messages[index]):
        return False
    if _intake_quote_position(messages, index, quote_id) is None:
        return False
    quoted_amounts = list(_AMOUNT.finditer(quote_text))
    if len(quoted_amounts) != 1 or int(quoted_amounts[0][1].replace(' ', '')) != amount:
        return False
    before_amount = quote_text[:quoted_amounts[0].start()]
    if (re.search(r'\b(?:от|до|около|примерно|максимум)\s*$', before_amount, re.I)
            or re.search(r'диагност|осмотр|выезд|приезд', quote_text, re.I)):
        return False
    text = str(messages[index].get('body') or messages[index].get('text') or '')
    matches = list(_AMOUNT.finditer(text))
    if len(matches) != 1 or int(matches[0][1].replace(' ', '')) != amount:
        return False
    # Bind whose agreement this is before content-word matching removes
    # pronouns. Possessives inside the work label remain separate evidence.
    agreement = re.search(r'\b(?:(?P<subject>меня|нас|мне|нам|его|её|ее|их|ему|ей|им|'
                          r'вас|вам|тебя|тебе)\s+)?(?:устраивает|подходит)\b', text, re.I)
    if (not agreement or matches[0].end() > agreement.start()
            or (agreement['subject'] and agreement['subject'].casefold() not in ('меня', 'нас', 'мне', 'нам'))
            or re.search(r'[?«»“”"]|\bне\s+(?:устраив|подход)', text[:agreement.end()], re.I)
            or text[agreement.end():].lstrip().startswith('?')):
        return False
    prefix = text[:matches[0].start()]
    if not re.fullmatch(r'\s*(?:да[,!\s]+)?(?:(?:цена|стоимость(?:\s+(?:услуги|работы))?)\s*)?', prefix, re.I):
        return False
    work = text[matches[0].end():agreement.start()]
    # Retrieval tokens omit short function words. Keep literal denial and
    # conditional scope before comparing the quoted work's content words.
    if re.search(r'\b(?:не|ни|нет|если)\b', work, re.I):
        return False
    work = re.sub(r'^(?:лей|ля|ль)(?=\W|$)', '', work, flags=re.I)
    if re.search(r'без\s+уч[её]та\s+материал', quote_text, re.I):
        work = re.sub(r'(?:,\s*)?(?:материал\w*\s+отдельно|без\s+(?:уч[её]та\s+)?материалов)',
                      '', work, flags=re.I)
    work = work.strip(' ,:—–-!\n')
    if work:
        if not re.match(r'за\s+', work, re.I):
            return False
        work = re.sub(r'^за\s+', '', work, count=1, flags=re.I)
        if (re.search(r'\b(?:оба|обе|вс[её]|итого|вместе|дв[ае]|двух|три|четыре|пять)\b', work, re.I)
                or any(int(n) != 1 for n in re.findall(r'\d+', work))):
            return False
        work = re.sub(r'\b(?:один|одного|одну|одной|1)\b', ' ', work, flags=re.I)
        # A first-person possessive does not change the priced operation or
        # establish decision-maker authority; LPR remains a separate guard.
        work = re.sub(r'\b(?:моего|моей|нашего|нашей)\b', ' ', work, flags=re.I)
        from experienced_dialogues import terms

        label = re.split(r'[.!?\n]', before_amount)[-1]
        tail = quote_text[quoted_amounts[0].end():]
        unit = re.search(r'\bза\s+([^,.!?]+)', tail, re.I)
        allowed = set(terms(label + ' ' + (unit[1] if unit else '')))
        allowed.update(terms('работа услуга указанная озвученная'))
        if not set(terms(work)).issubset(allowed):
            return False
    details = text[agreement.end():].lstrip(' .!,;\n')
    return _intake_consent_details(messages, index, details)


def _accepts_assembly_minimum(messages, index, quote_id, amount, quote_text):
    """Recognize an assembly minimum with contact details and one visit preference."""
    if amount != 1500 or not quote_id:
        return False
    message = messages[index]
    text = str(message.get('body') or message.get('text') or '')
    agreement, _, details = text.partition('.')
    match = re.fullmatch(r'\s*(?:да[,\s]+)?сборка(?:\s+мебели)?\s+от\s+1[ \u00a0]?500\s+'
                         r'(?:рублей|рубля|рубль|₽)\s+(?:(?:меня|нас)\s+)?'
                         r'(?:подходит|устраивает)\s*!?\s*', agreement, re.I)
    desk = re.fullmatch(r'\s*(?:да[,\s]+)?на\s+сборку\s+(?:(?:этого|письменного)\s+)?стола\s+'
                        r'по\s+цене\s+от\s+1[ \u00a0]?500\s+(?:рублей|рубля|рубль|₽)\s+'
                        r'соглас(?:ен|на|ны)\s*!?\s*', agreement, re.I)
    direct = re.fullmatch(r'\s*(?:я\s+)?соглас(?:ен|на)\s+на\s+сборку\s+(?:по\s+цене\s+)?'
                          r'от\s+1[ \u00a0]?500\s+(?:рублей|рубля|рубль|₽)\s*!?\s*',
                          agreement, re.I)
    reordered = re.fullmatch(r'\s*(?:да[,\s]+)?от\s+1[ \u00a0]?500'
                             r'(?:\s+(?:рублей|рубля|рубль|₽))?\s+за\s+сборку(?:\s+мебели)?\s+'
                             r'(?:(?:меня|нас)\s+)?(?:подходит|устраивает)\s*!?\s*', agreement, re.I)
    if not (match or desk or direct or reordered) or re.search(r'[?«»“”"]', text):
        return False
    if not re.match(r'\s*(?:стоимость\s+(?:услуги|сборки)|сборка)'
                    r'(?:\s+(?:мебели|шкафа))?\s*(?:[—–:-]\s*)?от\s+', quote_text, re.I):
        return False
    if not _delivered_intake_consent(message):
        return False
    position = _intake_quote_position(messages, index, quote_id)
    if position is None:
        return False
    if desk:
        from qualification_state import explicit_one_work

        if not any((work := explicit_one_work(row)) and re.search(r'\bстол\s*$', work[0], re.I)
                   for row in messages[:position]):
            return False
    quote = furniture_minimum_quote(messages[:index], {'direction': 'mnc'},
                                    dict(message_id=quote_id, amount=amount))
    if not quote or quote['rules'] != ['DOC-L0326']:
        return False
    return _intake_consent_details(messages, index, details)


def _delivered_intake_consent(message):
    from contact_facts import _client_intent_message

    transcript = str(message.get('voice_transcript_status') or '').lower()
    delivery = str(message.get('delivery_status') or message.get('delivery') or '').lower()
    return (_client_intent_message(message)
            and message.get('role') not in ('system', 'assistant')
            and message.get('speaker_role', 'client') == 'client'
            and not message.get('out_pending')
            and delivery not in ('failed', 'error', 'pending', 'queued', 'sending', 'processing', 'cancelled', 'canceled')
            and (not transcript or transcript in ('ready', 'done', 'completed')))


def _intake_quote_position(messages, index, quote_id):
    position = next((i for i in range(index - 1, -1, -1)
                     if messages[i].get('id') == quote_id and outgoing_reply_observed(messages[i])), None)
    if position is None:
        return None
    for row in messages[position + 1:index]:
        if _NEW_INTAKE_PRICE_SCOPE.match(str(row.get('body') or row.get('text') or '')) and _delivered_intake_consent(row):
            return None
    return position


def _accepts_curtain_unit(messages, index, quote_id, amount, quote):
    """Resolve a reference to the posted curtain-rail price, without changing its unit."""
    quoted = re.fullmatch(r'\s*Навес карниза\s*[—–-]\s*(800|1300)\s+' + _RUBLE_WORD
                          + r'\s+за\s+штуку,\s*без уч[её]та материалов\.\s*'
                            r'Вас устраивает такая стоимость\?\s*', quote, re.I)
    if not quoted or int(quoted[1]) != amount or not quote_id:
        return False
    message = messages[index]
    if not _delivered_intake_consent(message):
        return False
    text = str(message.get('body') or message.get('text') or '')
    agreement, _, details = text.partition('.')
    if (re.search(r'[?«»“”"]', text)
            or not re.fullmatch(r'\s*(?:да[,\s]+)?(?:озвученная|указанная|эта)\s+стоимость\s+'
                                r'навеса(?:\s+карниза)?\s+(?:(?:мне|нам)\s+)?'
                                r'(?:подходит|устраивает)\s*!?\s*', agreement, re.I)):
        return False
    position = _intake_quote_position(messages, index, quote_id)
    if position is None or any(map(outgoing_reply_observed, messages[position + 1:index])):
        return False
    from qualification_state import singular_hanging_work

    return (any(work and re.search(r'\bкарниз\b', work[0], re.I)
                for work in map(singular_hanging_work, current_enquiry_messages(messages[:position])))
            and _intake_consent_details(messages, index, details))


def _intake_consent_details(messages, index, details):
    from contact_facts import named_visit_preference

    visit = named_visit_preference(messages, index)
    if visit and visit['status'] == 'requested':
        # Only remove a complete first-person preference. A condition, extra
        # request or alternative time must still fail the contact-only check.
        preference = r'(?:^|(?<=\.))\s*(?:(?:мне|нам)\s+)?удобно\s+' + re.escape(visit['window']) + r'\s*(?:\.|$)'
        details = re.sub(preference, '', details, count=1, flags=re.I)
    return all(_intake_consent_contact(part.strip()) for part in details.rstrip('. \n').split('.')
               if part.strip())


def _intake_consent_contact(text):
    if re.fullmatch(r'запишите(?:\s+меня)?(?:,?\s+пожалуйста)?\s*!?', text, re.I):
        return True
    if re.fullmatch(r'(?:оплачиваю\s+и\s+решаю|решаю\s+и\s+оплачиваю)\s+я,\s*(?:дома\s+буду|буду\s+дома)', text, re.I):
        return True
    from qualification_state import (contact_name_age_fragment, first_person_home_responsibility,
                                     named_self_introduction)

    if first_person_home_responsibility(text):
        return True

    if named_self_introduction(text):
        return True
    if contact_name_age_fragment(text):
        return True
    if re.fullmatch(r'меня\s+зовут\s+[а-яё-]+(?:\s+[а-яё-]+){0,2}'
                    r'(?:,\s*(?:мне\s+)?\d{1,3}\s+(?:лет|года?))?', text, re.I):
        return True
    import contact_phone
    phone = re.fullmatch(r'(?:(?:мой\s+)?телефон|(?:номер\s+)?для\s+связи)\s*:?\s*([+\d() -]+)', text, re.I)
    if phone:
        found = contact_phone.find_all(phone[1].strip())
        return len(found) == 1 and found[0].raw == phone[1].strip()
    # Restrict this suffix to address syntax. The actual address/territory
    # validation is still a separate condition for preparing the form.
    address_text = re.sub(r'^адрес\s*:\s*', '', text, count=1, flags=re.I)
    address = re.fullmatch(r'(?:([а-яё -]+),\s*)?(?:улица|переулок|проспект)\s+[а-яё0-9 -]+'
                           r',\s*дом\s+\d+[а-яё]?(?:,\s*квартира\s+\d+)?', address_text, re.I)
    if not address or not address[1]:
        return bool(address)
    import filials
    return filials.known(address[1].strip(), 'mnc')


def _accepts_tv_unit_terms(messages, index, quote_id, amount, quote):
    """Bind explicit named consent to a delivered, single TV installation quote."""
    import contact_facts

    work = (r'(?:монтаж|установк(?:а|у))\s+кронштейна\s*(?:/|и\s+|с\s+)'
            r'\s*(?:навес(?:ом)?|установк(?:а|у|ой))\s+(?:(?:одного|этого)\s+)?телевизора')
    quoted = re.fullmatch(r'\s*' + work + r'\s+[—–-]\s+(\d[\d ]*)\s+' + _RUBLE_WORD
                          + r'\s+за\s+штуку(?:,\s*без уч[её]та материалов)?[.]'
                            r'(?:\s*(?:Вас устраивает такая стоимость|Такая стоимость вас устраивает)[?])?\s*',
                          quote, re.I)
    if not quoted or int(quoted[1].replace(' ', '')) != amount:
        return False
    message = messages[index]
    if (not contact_facts._client_intent_message(message)
            or message.get('role') in ('system', 'assistant') or message.get('speaker_role', 'client') != 'client'
            or message.get('out_pending') or str(message.get('delivery_status') or message.get('delivery') or '').lower()
            in ('failed', 'error', 'pending', 'queued', 'sending', 'processing', 'cancelled', 'canceled')):
        return False
    text = str(message.get('body') or message.get('text') or '')
    agreement, *tail = re.split(r'[.!;\n]+', text, maxsplit=1)
    accepted = re.fullmatch(r'\s*(?:да\s*,\s*)?соглас(?:ен|на|ны)\s+на\s+(\d[\d ]*)\s+'
                            + _RUBLE_WORD + r'\s+за\s+' + work + r'\s*', agreement, re.I)
    if (not accepted or int(accepted[1].replace(' ', '')) != amount
            or re.search(r'[?«»“”"]|\b(?:если|только|кроме|передумал\w*)\b|'
                         r'цен[ауые]|стоимост|доплат|сумм|бюджет|не\s+соглас|'
                         r'нов(?:ая\s+заявка|ый\s+заказ|ое\s+обращение)', ' '.join(tail), re.I)):
        return False
    position = next((i for i, row in enumerate(messages[:index])
                     if quote_id and row.get('id') == quote_id and outgoing_reply_observed(row)), None)
    if position is None:
        return False
    return all((contact_facts.tv_mount_work_volume(prefix) or {}).get('count') == 1
               for prefix in (messages[:position], messages[:index + 1]))


def _accepts_tv_total_terms(message, amount, quote):
    """Explicit named work consent; source/tariff verification remains separate."""
    import contact_facts
    import assistant_catalog
    total = _tv_total_components(quote)
    if (not total or total['total'] != amount or not contact_facts._client_intent_message(message)
            or message.get('role') in ('system', 'assistant') or message.get('speaker_role', 'client') != 'client'
            or message.get('out_pending') or str(message.get('delivery_status') or message.get('delivery') or '').lower()
            in ('failed', 'error', 'pending', 'queued', 'sending', 'processing', 'cancelled', 'canceled')):
        return False
    text = str(message.get('body') or message.get('text') or '')
    if '?' in text or re.search(r'[«»“”"]', text):
        return False
    clause, *tail = re.split(r'[.!;\n]+', text, maxsplit=1)
    if (not re.fullmatch(r'\s*(?:озвученную|указанную|эту)\s+стоимость\s+\d[\d ]*\s+рублей\s+за\s+.+\s+принимаю\s*', clause, re.I)
            or re.search(r'\b(?:не|но|если|только|кроме)\b', clause, re.I)
            or re.search(r'ремонт|почин|настрой|подключ|собрать|сборк|демонтаж|демонтир|\bснять\b', clause, re.I)
            or tail and re.search(r'\b(?:если|только|кроме)\b|цен|стоим|доплат|сумм|бюджет', tail[0], re.I)):
        return False
    money = _AMOUNT.findall(clause)
    if len(money) != 1 or int(money[0].replace(' ', '')) != amount:
        return False
    items = assistant_catalog.choose(clause, dict(direction='mnc')).get('items', [])
    counts = [item for item in contact_facts._quantity_mentions(clause) if item['object'] == 'tv']
    return (len(items) == 1 and items[0]['id'] == 'tv-mount' and len(counts) == 1
            and counts[0]['mode'] == 'asserted' and counts[0]['count'] == total['count'])


def _accepts_bt_primary_terms(message, amount, quote):
    """Accept the fixed named primary category, not the neighbouring technical floor."""
    import contact_facts
    if (amount != 800 or not _bt_diagnostic_quote_verified(quote, dict(amount=800))
            or not re.search(r'первичн\w*\s+(?:диагностик|осмотр)\w*[^.!?\n]{0,45}800', quote, re.I)
            or not contact_facts._client_intent_message(message)
            or message.get('speaker_role', 'client') != 'client'
            or message.get('role') in ('system', 'assistant') or message.get('out_pending')
            or str(message.get('delivery_status') or message.get('delivery') or '').lower()
            in ('failed', 'error', 'pending', 'queued', 'sending', 'cancelled', 'canceled')):
        return False
    text = str(message.get('body') or message.get('text') or '')
    if re.search(r'[?«»“"]', text):
        return False
    agreement, *tail = re.split(r'[.!;\n]+', text, maxsplit=1)
    match = re.fullmatch(
        r'\s*(?:да[,!\s]*)?первичн\w*\s+(?:диагностика|осмотр)\s+без\s+разбора\s+за\s+'
        r'800\s*(?:рублей|рубля|рубль|₽)\s+(?:(?:мне|нам|меня|нас)\s+)?(?:подходит|устраивает)\s*',
        agreement, re.I)
    remainder = tail[0] if tail else ''
    remainder = re.sub(r'\bоформляйте\s+только\s+е[её]\b', '', remainder, flags=re.I)
    return bool(match and not re.search(r'\b(?:если|но|не|кроме|только)\b|цен|стоим|доплат|бюджет|'
                                        r'ремонт|замен|разбор', remainder, re.I))


def _accepts_diagnostic_terms(message, quote):
    """Explicit diagnostic terms, not ``принимаю решение`` or a repair fee.

    The caller still requires a pending observed monetary quote and an active
    price-answer turn. This does not certify the quote or authorize a repair.
    """
    import contact_facts
    if (not contact_facts._client_intent_message(message)
            or message.get('speaker_role', 'client') != 'client'
            or message.get('role') in ('system', 'assistant') or message.get('out_pending')
            or str(message.get('delivery_status') or message.get('delivery') or '').lower()
            in ('failed', 'error', 'pending', 'queued', 'sending', 'cancelled', 'canceled')):
        return False
    money = [clause for clause in re.split(r'[.!?;,\n]+', quote) if _AMOUNT.search(clause)]
    if (not re.search(r'\bдиагностик\w*', quote, re.I) or len(_AMOUNT.findall(quote)) != 1
            or len(money) != 1 or re.search(r'\bот\s+\d', money[0], re.I)
            or not re.search(r'диагност|выезд|при\s+отказ|в\s+случае\s+отказ', money[0], re.I)):
        return False
    text = str(message.get('body') or message.get('text') or '')
    if '?' in text:
        return False
    parts = re.split(r'[.!?;\n]+', text, maxsplit=1)
    agreement = re.fullmatch(
        r'\s*(?:да[,\s]*)?(?:(?:эти|такие|озвученные|указанные)\s+)?условия\s+'
        r'(?:(?:выезда|выезда\s+и)\s+)?диагностики\s+(?:я\s+)?принимаю\s*', parts[0], re.I)
    remainder = parts[1] if len(parts) > 1 else ''
    return bool(agreement and not re.search(r'\bно\b|\bне\b|если|кроме|только|бюджет|дорого|'
                                            r'цен|стоим|сумм|доплат|отказ', remainder, re.I))


def _accepts_named_price(text, amount, quote):
    """A later explicit same-price agreement need not repeat a staff question.

    Preserve the minimum qualifier. A fixed budget or a different amount
    cannot become consent to an open-ended price.
    """
    matches = list(_AMOUNT.finditer(text))
    if len(matches) != 1 or int(matches[0][1].replace(' ', '')) != amount or not quote:
        return False
    if re.search(r'\bот\s*' + str(amount) + r'(?!\d)', quote, re.I) and not re.search(r'\bот\s*' + str(amount) + r'(?!\d)', text, re.I):
        return False
    named = text[:matches[0].start()] + '[SUM]' + text[matches[0].end():]
    # _AMOUNT intentionally matches the currency stem, so retain its ending.
    named = re.sub(r'\[SUM\](?:лей|ля|ль)?', '[SUM]', named, flags=re.I)
    money = r'(?:(?:цен[аы]|стоимость)(?:\s+услуги)?\s*)?(?:от\s*)?\[SUM\]'
    agreement = r'(?:(?:меня|нас)\s+)?(?:устраивает|подходит)'
    return bool(re.fullmatch(r'\s*(?:да[,!\s]*)?(?:' + money + r'\s+' + agreement + r'|'
                             + agreement + r'\s+' + money + r')[.!\s]*', named, re.I))


def _accepts_price(text):
    if re.fullmatch(r'\s*(?:да[,!\s]*)?(?:(?:такая|эта|данная)\s+)?(?:стоимость|цена)\s+'
                    r'(?:меня\s+)?(?:устраивает|подходит)[.!\s]*', text, re.I):
        return True
    yes = r'(?:да|согласен|согласна|согласны|устраивает|подходит|хорошо|ок|окей|да[, ]+(?:соглас[а-я]*|устраивает|подходит))'
    if re.fullmatch(r'\s*' + yes + r'[.!\s]*', text, re.I):
        return True
    acknowledgement = re.match(r'\s*(?:понял[аи]?[,!\s]+)?' + yes + r'[,!.\s]+', text, re.I)
    if not acknowledgement:
        return False
    tail = text[acknowledgement.end():]
    # A separate explanation of the equipment problem is not a rejection of
    # the price. Keep every actual condition, money question or objection.
    conditions = re.sub(r'\bне\s+знаю\s*,?\s*(?:как\s+(?:починить|включить|настроить)|'
                        r'что\s+с\s+(?:ним|ней|техникой|принтером|телевизором)\s+делать)\b', '', tail, flags=re.I)
    return bool(re.match(r'(?:(?:а|вам)\s+)?(?:завтра|сегодня|когда|во\s*сколько)\b', tail, re.I)
                and not re.search(r'\bно\b|\bне\b|если|цен|стоим|сумм|доплат|бюджет|дорого', conditions, re.I))
