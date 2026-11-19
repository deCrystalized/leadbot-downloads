"""Choose the next necessary question before asking a model to phrase it."""

import re
from itertools import pairwise

from contact_cities import city_by_name


def city_mentioned(text, city):
    words = re.findall(r"[А-Яа-яЁё-]+", text)
    expected = city.lower().replace("ё", "е")
    for size in (1, 2, 3):
        for start in range(len(words) - size + 1):
            parsed = city_by_name(" ".join(words[start : start + size]), declined=True)
            if parsed and parsed.name.lower().replace("ё", "е") == expected:
                return True
    return False


def provider_location_question(text):
    if re.search(r'\b(?:я|мы)\s+(?:в|из|с|живу|жив[её]м|нахожусь|находимся)\b', text, re.I):
        return False
    question = re.search(r'(?:\bвы\s+(?:же\s+)?(?:в|из|с)\s+|\b(?:работаете|находитесь|выезжаете)\s+в\s+)([а-яё-]+(?:\s+[а-яё-]+){0,3})', text, re.I)
    if not question:
        return False
    words = question[1].split()
    if any(city_by_name(' '.join(words[:n]), declined=True) for n in range(1, len(words) + 1)):
        return True
    if words[0].lower().endswith('а') and city_by_name(words[0][:-1]):
        return True
    return bool(re.search(r'край|област|республик', question[1], re.I))


def _location_statement(text, offset, quoted):
    """A mentioned place is not necessarily the requested worksite.

    This is a conservative source filter, not map or territory verification.
    Keep the original text and offsets for evidence; only an affirmative
    client/worksite statement can replace an earlier observed location.
    """
    if any(start <= offset < end for start, end in quoted):
        return False
    prefix = re.split(r'[.!?;\n,]', text[:offset])[-1]
    sentence_prefix = re.split(r'[.!?;\n]', text[:offset])[-1]
    suffix = re.split(r'[.!;\n,]', text[offset:])[0]
    if re.search(r'\bне\s*$', prefix, re.I):
        return False
    if '?' in suffix or re.search(
            r'\b(?:если|допустим|предположим|раньше|ранее|вчера)\b|'
            r'\b(?:жил[аи]?|жили|находил[аи]сь|был[аи]?|были)\b', prefix, re.I):
        return False
    if re.search(r'\b(?:сказал\w*|говорил\w*|написал\w*|утвержда\w*)\b[^.!?;\n]*\bчто\b',
                 sentence_prefix, re.I) and not re.search(r'\bно\s+(?:я|мы)\b', prefix, re.I):
        return False
    worksite = re.search(r'\b(?:нуж(?:ен|на|но|ны)|адрес|приехать|приезжайте|подъезжайте)\b', prefix, re.I)
    own = re.search(r'\b(?:я|мы)\b', prefix, re.I)
    if not (worksite or own) and re.search(
            r'\b(?:он|она|они|сам(?:а|и)?|сестр\w*|брат\w*|родител\w*|подруг\w*|сосед\w*|'
            r'мастер\w*|продавец|продавц\w*|объявлен\w*|аккаунт\w*|профил\w*|'
            r'написан\w*|сказал\w*|говорит|указан\w*)\b', prefix, re.I):
        return False
    return True


def _client_city_evidence(messages):
    result, source_index = '', None
    for index, message in enumerate(messages):
        roles = {str(message.get(key) or '').casefold()
                 for key in ('sender_type', 'by', 'role', 'speaker_role')}
        if (message.get("direction") != "in" or roles & {
                'operator', 'employee', 'human', 'staff', 'manager', 'admin', 'agent',
                'system', 'avito', 'bot', 'assistant', 'automation'}
                or message.get('delivery_status') in ('failed', 'pending', 'sending', 'queued', 'out_pending')):
            continue
        text = message["body"]
        if provider_location_question(text):
            continue
        # A third-party diagnostic refusal is not a residence or visit address.
        # Keep an explicit first-person location, including in the same message.
        text = re.sub(r'\b[Вв]\s+[А-Яа-яЁё-]+\s+(?:\w+\s+){0,2}не\s+берутся\s+диагностировать', '', text)
        # Bringing a device to a proposed city does not establish an onsite
        # address there. The service-mode FAQ asks for that separately.
        text = re.sub(r'\b[Вв]\s+[А-Яа-яЁё-]+\s+(?:(?:его|е[её]|это)\s+)?привезти\b', '', text)
        # Genitive is safe only in an explicit origin statement. Applying it
        # to arbitrary tokens would turn street names such as Кирова into cities.
        quoted = [(m.start(), m.end()) for m in re.finditer(r'«[^»]*»|“[^”]*”|"[^"\n]*"', text)]
        chunks = [(m.start(), m.group(1), False) for m in re.finditer(
                r"(?:\bв|\bиз|\bгород|\bг\.)\s+([А-Яа-яЁё-]+(?:\s+[А-Яа-яЁё-]+){0,2})",
                text, re.I)]
        chunks.extend((m.start(), m.group(1), True) for m in re.finditer(
            r'\b(?:мы|я)\s+(?:из|с)\s+([А-Яа-яЁё-]+)\b', text, re.I))
        if (
            index
            and messages[index - 1].get("direction") == "out"
            and messages[index - 1].get('sender_type') not in ('client', 'bot', 'assistant', 'system', 'avito')
            and messages[index - 1].get('delivery_status') not in ('failed', 'pending', 'sending', 'queued', 'out_pending')
            and re.search(r"город|откуда", messages[index - 1]["body"], re.IGNORECASE)
        ):
            literal = text.strip(' \n.!«»“”"')
            if city_by_name(literal, declined=True):
                chunks.append((0, literal, False))
                quoted = []  # Quotation marks around a literal answer are formatting.
        for offset, chunk, origin in sorted(chunks, key=lambda item: item[0]):
            if not _location_statement(text, offset, quoted):
                continue
            words = chunk.split()
            for size in range(min(3, len(words)), 0, -1):
                city = city_by_name(" ".join(words[:size]), declined=True)
                if not city and origin and size == 1 and words[0].lower().endswith('а'):
                    city = city_by_name(words[0][:-1])
                if city:
                    result, source_index = city.name, index
                    break
    return result, source_index


def client_city(messages):
    return _client_city_evidence(messages)[0]


def outgoing_turns(messages):
    return sum(
        m.get("direction") == "out"
        and (i == 0 or messages[i - 1].get("direction") != "out")
        for i, m in enumerate(messages)
    )


def client_location(messages, known, facts):
    """Keep explicit client location separate from the default listing city.

    The listing is enough to avoid a routine city question. It does not prove
    that the client confirmed a location or that the full address passed maps.
    """
    city = known.get('city') or ''
    eligible = []
    for message in messages:
        text = message.get('body', '')
        # Asking where the master works does not locate the customer.
        provider_question = provider_location_question(text)
        self_location = re.search(r'\b(?:я|мы)\s+(?:в|из|живу|жив[её]м|нахожусь|находимся)\b', text, re.IGNORECASE)
        eligible.append(dict(message, body='' if message.get('direction') == 'in' and provider_question and not self_location else text))
    actual, source_index = _client_city_evidence(eligible)
    evidence = facts.get('evidence', {}).get('address.city', {})
    if not actual and evidence.get('message_id') and evidence['message_id'] != 'client-card':
        actual = facts.get('address', {}).get('city') or ''
    origin = 'client_message' if actual else ''
    mid = (eligible[source_index].get('id', '') if source_index is not None
           else evidence.get('message_id', '') if actual else '')
    if not actual:
        for left, right in pairwise(eligible):
            if (left.get('direction') == 'out' and right.get('direction') == 'in'
                    and city and city_mentioned(left.get('body', ''), city)
                    and '?' in left.get('body', '')
                    and re.search(r'\bвы\b|\bвас\b|\bгород\w*\b', left['body'], re.IGNORECASE)
                    and re.fullmatch(r'\s*(?:да|верно|правильно|ага)[.!\s]*', right['body'], re.IGNORECASE)):
                actual, origin, mid = city, 'city_question_answer', right.get('id', '')
    normalize = lambda value: value.casefold().replace('ё', 'е').strip()
    status = 'missing' if not actual else 'confirmed' if city and normalize(actual) == normalize(city) else 'conflict'
    return dict(status=status, city=actual, source=origin, message_id=mid,
                quote=next((m['body'][:500] for m in messages if mid and m.get('id') == mid), ''),
                advertised_city=city, map_verified=False)


def applicable_service_questions(messages, known, facts, service):
    """Keep form and conversational qualification on the same requested work."""
    keys = list(dict.fromkeys(key for item in service.get('items', []) for key in item.get('questions', [])))
    if known.get('direction') != 'kp':
        return keys
    if facts.get('standalone_printer_diagnostic'):
        keys = [key for key in keys if key != 'printer_connection']
    client = '\n'.join(m.get('body', '') for m in messages if m.get('direction') == 'in'
                       and m.get('sender_type', 'client') in ('client', ''))
    import assistant_catalog
    if ({item['id'] for item in service.get('items', [])} == {'pc'}
            and assistant_catalog.ordinary_office_work(client)):
        keys = [key for key in keys if key not in ('model', 'keep_data')]
        if assistant_catalog.office_fault_request(client) and 'office_symptom' not in keys:
            keys.insert(0, 'office_symptom')
    windows = re.search(r'(?:установ|переустанов)\w*[^.!?\n]{0,30}(?:windows|винд\w*)|'
                        r'(?:windows|винд\w*)[^.!?\n]{0,25}(?:установ|переустанов)', client, re.I)
    named_host = re.search(r'ноутбук|компьютер|моноблок|\bпк\b', client, re.I)
    physical_work = re.search(r'не\s+включа|залил|разбил|сгорел|сломал|разъ[её]м|питани|матриц|'
                              r'термопаст|чистк|замен|помен|пайк|перепа|ремонт', client, re.I)
    if windows and named_host and not physical_work and {item['id'] for item in service.get('items', [])} == {'pc'}:
        keys = [key for key in keys if key != 'model']
    return keys


def countertop_cut_requested(client):
    """A requested cut in the worktop, not an existing opening or sink hole."""
    client = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', client)
    cut = r'(?:врез\w*|выпил\w*|пропил\w*|вырез\w*|отрез\w*|прорез\w*)'
    for clause in re.split(r'[.!?;\n]+', client):
        if not re.search(cut, clause, re.I):
            continue
        # Preserve the old explicit cutting verbs. The new noun 'прорезь'
        # must refer to a worktop, not a slot in another object.
        if re.search(r'прорез', clause, re.I) and not re.search(r'столешниц', clause, re.I):
            continue
        if re.search(r'\bне\s+(?:надо|нужно|требуется)[^.!?\n]{0,35}' + cut + r'|'
                     + cut + r'[^.!?\n]{0,30}(?:не\s+нуж|уже\s+(?:есть|сделан|готов))|'
                     r'\b(?:я|мы)\s+сам[аи]?\s+(?:выреж|выпил|прореж)', clause, re.I):
            continue
        return True
    return False


def additional_work_question(messages):
    import contact_facts
    if not messages or not contact_facts._client_intent_message(messages[-1]):
        return False
    body = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', messages[-1].get('body', ''))
    return bool(re.search(r'только[^.!?\n]{0,90}\bили\b', body, re.I)
                and re.search(r'электрик|сантехник', body, re.I)
                and re.search(r'можете|сможете|помочь|занимаетесь', body, re.I)
                and not re.search(r'в\s+будущем|на\s+будущее|когда-нибудь|не\s+нуж|'
                                  r'заменить|установить|подключить|повесить|вкрутить|поменять', body, re.I))


def toilet_drain_clarification(messages, known, service, facts):
    """A slow flush describes a symptom, not toilet installation or a diagnosis.

    Confirm the requested drain work before asking about installation type.
    Keep the literal customer source; the proposed question is not an answer.
    Explicit replacement/tank work and an already answered clog question retain
    their own qualification. Shared lifecycle guards run before this helper.
    """
    import assistant_prices
    import contact_facts

    if (known.get('direction') != 'mnc' or service.get('status') != 'supported'
            or {item['id'] for item in service.get('items', [])} != {'toilet'}
            or facts.get('confirmed_clog')):
        return None
    current = assistant_prices.current_enquiry_messages(messages)
    is_client = lambda m: (contact_facts._client_intent_message(m)
                           and m.get('role') not in ('assistant', 'system'))
    starts = [i for i, m in enumerate(current) if is_client(m)
              and re.search(r'\bновая\s+заявка\b|\bновый\s+заказ\b|'
                            r'по\s+другому\s+вопросу|\bтеперь\s+нужно\b', m.get('body', ''), re.I)
              and not re.search(r'«|»|“|”|"|\bесли\b|\bне\s+нуж', m.get('body', ''), re.I)]
    if starts:
        current = current[starts[-1]:]
    clients = [m for m in current if is_client(m)]
    evidence = None
    for message in clients:
        body = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', message.get('body', ''))
        if re.search(r'\b(?:если|допустим|раньше|прежде)\b|'
                     r'\b(?:сосед|мастер|продавец)\w*[^.!?\n]{0,35}(?:сказал|написал|говорит)|'
                     r'уже\s+(?:вс[её]\s+)?(?:исправ|почин|работает|нормально)|'
                     r'помощь\s+не\s+нуж|не\s+(?:медленн|плох\w*\s+смыва)|'
                     r'засор\w*\s+нет|не\s+засор|нет\s+засор', body, re.I):
            evidence = None
            continue
        operation = r'(?:замен|помен|меня|установ|постав|став|снят|демонт|перестав|почин|ремонт)\w*'
        work = ' '.join(part for part in re.split(r'[.!?;,\n]+', body)
                        if not re.search(r'\bне\s+(?:(?:нужно|надо|требуется)\s+)?' + operation
                                         + r'|' + operation + r'[^.!?;,\n]{0,35}не\s+нуж', part, re.I))
        if re.search(operation + r'[^.!?\n]{0,35}(?:унитаз|бачок)|'
                     r'(?:унитаз|бачок)\w*[^.!?\n]{0,35}'
                     + operation + r'|'
                     r'наб[ио]ра|наполня|бачок|кнопк|арматур', work, re.I):
            return None
        if (re.search(r'унитаз', body, re.I)
                and re.search(r'медленн|плох\w*\s+смыва', body, re.I)
                and re.search(r'смыв|смыва|уход|уходит|слив', body, re.I)):
            evidence = dict(message_id=message.get('id', ''), quote=message.get('body', ''))
    if not evidence:
        return None
    asked = [m for m in current if contact_facts.observed_clog_question(m)]
    previous_question = None
    for message in current:
        if message.get('direction') == 'out':
            previous_question = message if message in asked else None
        elif is_client(message):
            if previous_question and re.fullmatch(r'\s*нет[.!\s]*', message.get('body', ''), re.I):
                return None
            previous_question = None
    uncertain = (facts.get('clog_work_context') or {}).get('uncertain_reports', [])
    return dict(evidence, asked=len(asked), fact='slow_drain_symptom', clog_confirmed=False,
                cause_unknown=bool(uncertain))


def furniture_work_question(messages, known, facts, service):
    """Clarify an object-only enquiry without choosing the client's operation."""
    import assistant_catalog
    import assistant_prices
    import contact_facts

    if (known.get('direction') != 'mnc' or service.get('status') != 'supported'
            or {item['family'] for item in service.get('items', [])} != {'furniture'}):
        return None
    current = assistant_prices.current_enquiry_messages(messages)
    start = max((index for index, row in enumerate(current)
        if contact_facts._client_intent_message(row) and re.match(
            r'^\s*(?:новая\s+заявка|новый\s+заказ|по\s+другому\s+вопросу)\b', row.get('body', ''), re.I)), default=0)
    current = current[start:]
    clients = [row for row in current if contact_facts._client_intent_message(row)]
    literal = '\n'.join(row.get('body', '') for row in clients)
    literal = assistant_catalog._assembly_intent_text(literal)
    literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', literal)
    operation = (r'\b(?:дособрать|собрать|собирать|собираете|собер[её]те|сборк\w*|'
                 r'разобрать|разбирать|разборк\w*|ремонт\w*|отремонт\w*|почин\w*|'
                 r'установить|установк\w*|повесить|повесите|навесить|закрепить|'
                 r'прикрутить|отрегулир\w*|регулиров\w*|заменить|поменять)\b')
    literal = re.sub(r'\bне\s+(?:нуж\w*|надо|требуется)\s+' + operation, '', literal, flags=re.I)
    for clause in assistant_catalog._requested_work_clauses(literal, operation):
        if re.search(r'\b(?:если|допустим|раньше|вчера|сам|сама|сами)\b|'
                     r'объявлен|по\s+словам|сказал|говорит|написал', clause, re.I):
            continue
        return None
    symptom_text = '\n'.join(clause for clause in re.split(r'[,.!;\n]+', literal)
        if not re.search(r'\bне\s+(?:нуж\w*|надо|требуется)\s+(?:ремонт|почин)|'
                         r'\bремонт\w*\s+не\s+(?:нуж\w*|надо|требуется)|'
                         r'объявлен|по\s+словам|сказал|говорит|написал', clause, re.I))
    if assistant_catalog.furniture_repair_request(symptom_text):
        return None
    completion = facts.get('confirmed_furniture_completion') or {}
    asked = next((row for row in current if row.get('id') == completion.get('question_message_id')), {})
    if (completion and asked.get('sender_type', 'operator') in ('operator', 'employee', 'human', '')
            and not asked.get('out_pending') and str(asked.get('delivery_status') or asked.get('delivery') or '').lower()
            not in ('pending', 'queued', 'sending', 'failed', 'error', 'cancelled', 'canceled')):
        return None
    attempts = sum(bool(assistant_prices.outgoing_reply_observed(row)) and bool(re.search(
        r'что\s+(?:именно\s+)?(?:нужно|требуется)\s+сделать\s+с\s+мебелью', row.get('body', ''), re.I))
        for row in current)
    return dict(kind='furniture_work', question='Что именно нужно сделать с мебелью?',
                groups=[['что'], ['нужно', 'требуется'], ['сделать']],
                evidence_message_ids=[row.get('id', '') for row in clients],
                unanswered_attempts=attempts, requires_operator=attempts >= 2,
                rule_ids=['DOC-L0699', 'DOC-L0700'])


def next_question(messages, known, facts):
    client = "\n".join(m["body"] for m in messages if m.get("direction") == "in")
    turns = outgoing_turns(messages)
    city = known.get("city") or ""
    actual_city = facts["address"].get("city")
    if (
        actual_city
        and city
        and actual_city.lower().replace("ё", "е") != city.lower().replace("ё", "е")
    ):
        return {
            "kind": "city",
            "question": "Уточните город выезда.",
            "groups": [["город"]],
            "requires_operator": True,
        }
    import qualification_state as qs

    state = qs.inspect(messages)
    import assistant_catalog

    service = known.get("service") or assistant_catalog.choose(client, known)
    age = facts.get('client_age') or qs.client_age(messages)
    adult = facts.get('adult_presence') or qs.adult_presence(messages)
    if age['status'] == 'minor' and adult['status'] != 'confirmed':
        return qs.adult_presence_question(adult)
    if facts.get('business_customer') and not facts.get('business_payment'):
        asked = sum(m.get('direction') == 'out' and not m.get('out_pending')
                    and '?' in m['body'] and bool(re.search(r'оплат\w*[^.!?\n]{0,60}(?:сч[её]т|налич|перевод)', m['body'], re.I))
                    for m in messages)
        question = 'Оплата будет по счёту для организации или наличными/переводом?'
        if state['decision_maker']['status'] != 'answered':
            question += ' Кто будет принимать решение и оплачивать работу на месте?'
        return dict(kind='business_payment', question=question, groups=[['оплат'], ['счёт', 'налич', 'перевод']],
                    requires_operator=asked >= 2, unanswered_attempts=asked,
                    rule_ids=['DOC-L0800', 'DOC-L0801', 'DOC-L0802', 'DOC-L0804'])
    if qs.needs_client_age(known, service):
        age = qs.client_age(messages)
        if age['status'] not in ('adult', 'minor'):
            return dict(kind='client_age', question='А можете подсказать свой возраст?', groups=[['возраст']],
                        requires_operator=age['status'] in ('minor', 'unavailable') or age['asked'] >= 2,
                        unanswered_attempts=age['asked'])
    keys = applicable_service_questions(messages, known, facts, service)
    # Resolve acceptance prerequisites before collecting contacts or inviting.
    priority = list(dict.fromkeys([
        'has_pc', 'internet', 'gas_type', 'countertop_material', 'coffee_type', 'cable_type', 'cable_operation',
        *qs.acceptance_conditions(service, state), 'door_type', 'door_material',
    ]))
    for key in priority:
        if key == 'countertop_material' and not countertop_cut_requested(client):
            continue
        if key == 'gas_type' and re.search(r'электроплит|электродух|индукцион', client, re.IGNORECASE):
            continue
        if key == 'screen_damage' and not re.search(r'экран|изображ|картинк|подсветк|полос', client, re.I):
            continue
        if key in keys and state[key]['status'] in ('missing', 'uncertain', 'unavailable'):
            question = qs.question(key, state)
            if state[key]['status'] == 'unavailable' or state[key]['asked'] >= 2:
                question['requires_operator'] = True
            return question
    furniture_work = furniture_work_question(messages, known, facts, service)
    if furniture_work:
        return furniture_work
    if any(item["family"] == "furniture" for item in service.get("items", [])) and re.search(
        r"ремонт|почин|слом", client, re.IGNORECASE
    ):
        keys = ["furniture_problem"] + keys
    if (
        any(
            item["family"]
            in ("pc", "washer", "dishwasher", "boiler", "printer", "phone", "monitor")
            for item in service.get("items", [])
        )
        and state["problem"]["status"] == "missing"
        and not facts.get('standalone_printer_diagnostic')
        and not assistant_catalog.ordinary_office_work(client)
        and not re.search(
            r"чист|настро|установ|собра|сборк|подключ|замен|помен|прошив|обнов|\bBIOS\b|биос", client, re.IGNORECASE
        )
    ):
        keys = ["problem"] + keys
    if not keys and not service.get("items"):
        keys = ["problem"]
    if known.get('direction') == 'kp' and keys and keys[0] == 'problem' and state['problem']['status'] == 'missing':
        return qs.question('problem', state)
    # OWNER-LISTING-CITY-20261019: use the advertised city by default. Requiring
    # the client to repeat it adds a redundant turn. Actual other-city/address
    # conflicts are handled above and by policy/map checks, not assumed away.
    if known.get("partner") and not city and not actual_city:
        return {"kind": "city", "question": "Подскажите, в каком городе вы находитесь?", "groups": [["город"]]}
    if known.get("direction") == "mnc":
        keys += ["materials", "volume", "place"]
    destination = facts.get('work_destination_hint') or {}
    if destination.get('status') == 'unverified_work_destination':
        return dict(kind='work_address', question='Подскажите улицу и дом, где нужно выполнить работы.',
                    groups=[['улиц'], ['дом']], requires_operator=bool(facts['address'].get('building')),
                    evidence_message_ids=[destination['message_id']], rule_ids=['DOC-L0631', 'DOC-L0809'])
    unanswered = any(
        state[key]["status"] == "missing" and state[key]["asked"] for key in keys
    )
    if turns >= 2 and not facts["contact_phone_to_use"] and not unanswered:
        return {
            "kind": "phone",
            "question": "Номер для связи подскажите?",
            "groups": [["номер", "телефон"]],
        }
    # Conditions are evaluated from actual client answers, never from our question.
    for key in keys:
        if key == "countertop_material" and not countertop_cut_requested(client):
            continue
        if key == "keep_data" and not re.search(
            r"windows|\bвинд(?:оус|овс|а|у|ы|е|ой|ою)\b|переустанов", client, re.IGNORECASE
        ):
            continue
        if (
            key == "pc_parts"
            and state["pc_parts"]["status"] == "answered"
            and re.search(r"no|\bнет\b", state["pc_parts"]["value"], re.IGNORECASE)
            and state["pc_purchase"]["status"] == "missing"
        ):
            return qs.question("pc_purchase", state)
        if key == "support" and not (
            state["ceiling"]["status"] == "answered"
            and re.search(r"натяжн", state["ceiling"]["value"], re.IGNORECASE)
            and not re.search(r"не натяжн", state["ceiling"]["value"], re.IGNORECASE)
        ):
            continue
        if key == "pipe_replacement" and re.search(
            r"пластиков|полипропилен|пвх",
            state["pipe_material"]["value"],
            re.IGNORECASE,
        ):
            continue
        if key == "screen_damage" and not re.search(
            r"экран|изображ|картинк|подсветк|полос", client, re.IGNORECASE
        ):
            continue
        if key == "gas_type" and re.search(
            r"электроплит|электродух|индукцион", client, re.IGNORECASE
        ):
            continue
        if key == "place" and facts["address"].get("office"):
            continue
        row = state[key]
        if row["status"] == "missing":
            if (key == 'materials' and row.get('tv_brackets') and known.get('direction') == 'mnc'
                    and {item['id'] for item in service.get('items', [])} == {'tv-mount'}):
                return dict(qs.question(key, state), question='Подходящий крепёж для навеса уже есть?',
                            groups=[['крепёж', 'крепеж'], ['подход'], ['навес', 'телевизор']],
                            wording_scope='tv_mount_fasteners_only',
                            evidence_message_ids=[row['tv_brackets']['message_id']])
            if key == 'printer_connection':
                evidence = qs.current_printer_printing_evidence(messages)
                if evidence:
                    return dict(qs.question(key, state), question='С компьютера или телефона сейчас печатаете?',
                                current_printing_evidence=evidence)
            if (key == 'materials' and known.get('direction') == 'mnc'
                    and {item['family'] for item in service.get('items', [])} == {'furniture'}
                    and assistant_catalog.furniture_assembly_request(client)):
                return dict(qs.question(key, state), alternative_groups=[[
                    ['все'], ['детал'], ['крепёж', 'крепеж'], ['есть', 'налич', 'комплект']]],
                    wording_scope='current_furniture_kit_only')
            return qs.question(key, state)
        if row["status"] == "unavailable" and key in (
            "license",
            "owner_access",
            "plumbing_ready",
            "electrics_ready",
            "floor_ready",
            "gas_type",
            "coffee_type",
            "data_condition",
            "countertop_material",
        ):
            return dict(qs.question(key, state), requires_operator=True)
    if turns >= 2 and not facts["contact_phone_to_use"]:
        return {
            "kind": "phone",
            "question": "Номер для связи подскажите?",
            "groups": [["номер", "телефон"]],
        }
    if turns >= 2 and not facts["address"].get("building"):
        return {
            "kind": "address",
            "question": "Номер дома подскажите?"
            if facts["address"].get("street")
            else "Адрес подскажите?",
            "groups": [["дом"]]
            if facts["address"].get("street")
            else [["адрес", "улиц"]],
        }
    if facts["address"].get("building") and not facts["address"].get("office"):
        if re.search(r'общежит|общаг|гостиниц|хостел|\bотел', client, re.I):
            return {"kind": "office", "question": "Номер комнаты подскажите?", "groups": [["комнат"]]}
        return {
            "kind": "office",
            "question": "Это квартира или частный дом? Если квартира, подскажите номер квартиры.",
            "groups": [["квартир"], ["дом"]],
        }
    if state["decision_maker"]["status"] != "answered":
        return qs.question("decision_maker", state)
    if state["client_name"]["status"] != "answered" and not qs.client_name_profile_value(state['client_name'], known.get('client_name')):
        return qs.question("client_name", state)
    if state["visit_time"]["status"] != "answered":
        return qs.question("visit_time", state)
    return None
