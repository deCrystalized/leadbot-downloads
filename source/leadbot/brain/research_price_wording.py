"""Source-owned price conditions and validation of the actual proposed text.

This does not grant a send, certify customer consent, or replace the separate
model review. Unknown price kinds retain the legacy exact-reply contract.
"""
import copy
import re

import assistant_prices as prices
from experienced_dialogues import digest

VERSION = 4
_COST = re.compile(r'стоим\w*|цен[аыуеой]+|сумм\w*', re.IGNORECASE)
_FREE = re.compile(r'бесплат\w*|без\s+оплат\w*|платить\s+не\s+(?:нужно|надо)', re.IGNORECASE)
_MATERIALS = re.compile(r'материал\w*|комплектующ\w*|запчаст\w*', re.IGNORECASE)
_EXCLUDED = re.compile(
    r'без\s+уч[её]та\s+(?:материал|запчаст)\w*|(?:материал|запчаст)\w*\s+(?:в\s+(?:эту\s+)?цену\s+)?'
    r'не\s+(?:включен\w*|включён\w*|вход\w*)|(?:материал|запчаст)\w*\s+(?:оплачиваются\s+)?отдельно', re.IGNORECASE)
_DIGITS = re.compile(r'\d+(?:[ \u00a0]\d{3})*')
_EXECUTION = re.compile(
    r'\b(?:заменил\w*|замен[её]н\w*|заменю|установил\w*|установлен\w*|установлю|'
    r'поменял\w*|поменяю|собрал\w*|собран\w*|соберу|выполнил\w*|выполнен\w*|выполню|'
    r'сделал\w*|сделан\w*|осмотрел\w*|определил\w*|проверил\w*|приехал\w*|'
    r'выезжа\w*|забронировал\w*|записан\w*|создан\w*|согласован\w*)\b', re.IGNORECASE)


def offer(price, messages, known):
    """Called only with the current server-built price decision, before draft."""
    direction = known.get('direction')
    if (direction not in ('mnc', 'kp', 'bt') or price.get('handoff')
            or not isinstance(price.get('reply'), str) or not price.get('rules')):
        return None
    source = price['reply']
    amounts = price.get('amounts')
    if (not isinstance(amounts, list) or any(type(n) is not int or n <= 0 for n in amounts)
            or not all(isinstance(ref, str) and ref for ref in price['rules'])):
        return None
    callout = (prices.MNC_FREE_CALLOUT_RULE in price['rules'] or 'DOC-L0757' in price['rules']) and bool(_FREE.search(source))
    after = 'после осмотра' in source.casefold() and bool(_COST.search(source))
    tariff = None
    extra = {}
    if (direction == 'kp' and not amounts
            and {'TG1-664', 'KP-L0490', 'KP-L0494'} <= set(price['rules'])
            and source == 'Не видя телевизор, точную стоимость назвать не смогу. Нужно осмотреть технику и определить объём работы.'):
        kind = 'inspection_scope_required'
    elif not amounts and after:
        kind = 'after_inspection'
    elif not amounts and callout and source == 'Выезд в черте города бесплатный.':
        kind = 'free_city_callout'
    elif direction == 'mnc' and price.get('tariff_kind') == 'fixed_service_unit':
        tariff = prices.mnc_fixed_tariff(messages, known)
        if not tariff or tariff != price.get('tariff') or amounts != [tariff['amount']]:
            return None
        kind = 'fixed_service_unit'
    elif direction == 'mnc' and (price.get('work_price_stage') or {}).get('work_price') == 'service_minimum':
        if len(amounts) != 1:
            return None
        kind = 'service_minimum'
    else:
        import research_price_components
        extra = research_price_components.offer(price, messages, known)
        if extra is None:
            return None
        kind = extra['kind']
    frame = {'version': VERSION, 'direction': direction, 'kind': kind, 'source_reply': source, 'rule_ids': list(price['rules']),
                'stage': prices.price_turns(messages), 'amounts': list(amounts), 'currency': 'RUB' if amounts else None,
                'callout_free_in_city': callout, 'work_after_inspection': after,
                'materials_excluded': bool(_EXCLUDED.search(source)), 'consent_required': '?' in source,
                 'exclusion_subject': ('parts' if re.search(r'запчаст', source, re.IGNORECASE) else 'materials') if _EXCLUDED.search(source) else None,
                'tariff': copy.deepcopy(tariff), 'source_offer_sha256': digest(price)}
    frame.update(extra)
    if kind == 'inspection_scope_required':
        frame.update(work_after_inspection=True, inspection_and_scope_required=True)
    return frame


def bound_frame(payload):
    decision = payload['decision_internal']
    frame = decision.get('price_wording_frame')
    if frame is None:
        return None
    if (not isinstance(frame, dict) or frame.get('version') != VERSION
            or frame.get('direction') not in ('mnc', 'kp', 'bt')
            or frame.get('direction') != payload.get('known', {}).get('direction')
            or frame.get('source_reply') != decision.get('approved_price_reply')
            or not decision.get('forced_reply', '').startswith(frame['source_reply'])
            or frame.get('stage') != prices.price_turns(payload['messages'])):
        raise ValueError('Original source-owned price conditions changed')
    return copy.deepcopy(frame)


def _after_inspection(clause):
    return bool(_COST.search(clause) and re.search(r'после\s+осмотра\b', clause, re.IGNORECASE)
                and re.search(r'\b(?:назов(?:у|[её]м)|назвать|скаж(?:у|ем)|сказать|'
                              r'определ(?:ю|им|ить)|оцен(?:ю|им|ить)|сориентир(?:ую|уем|овать))\b',
                              clause, re.IGNORECASE)
                and not re.search(r'\bне\b|\bнет\b|\bдо\s+осмотра|без\s+осмотра', clause, re.IGNORECASE))


def _city_callout(clause):
    affirmative = re.sub(r'платить\s+не\s+(?:нужно|надо)', '', clause, flags=re.IGNORECASE)
    return bool(_FREE.search(clause) and re.search(r'выезд\w*|приезд\w*', clause, re.IGNORECASE)
                and re.search(r'в\s+(?:черте|пределах)\s+города|по\s+городу', clause, re.IGNORECASE)
                and not re.search(r'работ\w*|ремонт\w*|материал\w*|диагност\w*|'
                                  r'за\s+(?:город|предел)|вне\s+город', clause, re.IGNORECASE)
                and not re.search(r'\bне\b|\bнет\b', affirmative, re.IGNORECASE))


def _covered_clause(clause, role, frame):
    """A recognized price atom cannot authorize arbitrary words beside it.

    This is a conservative language boundary, not a general semantic judge.
    Existing tariff/unit/stage checks and the separate review still apply.
    Unknown wording is rejected rather than silently acquiring authority.
    """
    text = clause.strip(' ,.!?;\n').casefold().replace('ё', 'е')
    text = re.sub(r'^а\s+', '', text)
    if role == 'materials':
        return _EXCLUDED.fullmatch(text) is not None
    words = re.findall(r'[а-яёa-z]+', text)
    vocabulary = {
        'after': (r'я|мы|а|после|осмотра|техники|точн\w*|окончательн\w*|'
                  r'стоим\w*|цен[ауыоеий]+|сумм\w*|работ\w*|ремонт\w*|услуг\w*|'
                  r'смогу|сможем|могу|можем|назову|назовем|назвать|скажу|скажем|сказать|'
                  r'определю|определим|определить|оценю|оценим|оценить|сориентирую|сориентируем|сориентировать'),
        'free': (r'а|выезд\w*|приезд\w*|в|черте|пределах|по|города|городу|'
                 r'бесплат\w*|без|оплаты|платить|не|нужно|надо|будет'),
        'consent': (r'такая|такую|такой|эта|эту|этой|вас|вам|вы|с|'
                    r'цен[ауыоеий]+|стоим\w*|сумм\w*|устраива\w*|устроит|подойд\w*|подход\w*|соглас\w*'),
        'numeric': (r'за|по|от|не|менее|рубл\w*|руб|р|стоим\w*|цен[ауыоеий]+|'
                    r'услуг\w*|работ\w*|сборк\w*|штук\w*|единиц\w*|одну|одного|одной|'
                    r'эта|этой|этого|будет|будут|составит|составляет|стоит|стоят|стоить|обойдется|обойдутся'),
        'undetermined': (r'не|видя|без|до|после|осмотра|осмотреть|телевиз\w*|техник\w*|'
                         r'точн\w*|стоим\w*|цен[ауыоеий]+|назвать|назову|смогу|сможем|могу|можем|'
                         r'пока|нужно|необходимо|надо|сначала|и|определить|оценить|объем|работ\w*|чтобы'),
    }
    source_words = re.findall(r'[а-яёa-z]+', frame['source_reply'].casefold().replace('ё', 'е'))
    vocabulary['structured'] = vocabulary['numeric'] + '|' + vocabulary['consent'] + r'|при|после|в|у|меня|такие|таких|таким|эти|этих|услови\w*'
    if (frame.get('price_components') or {}).get('unit') == 'metre':
        source_words.append('погонный')
    for word in words:
        if re.fullmatch(vocabulary[role], word):
            continue
        # Only the numeric subject/unit may use inflections of its exact
        # current source label. No customer/history words extend this set.
        if role in ('numeric', 'structured') and any(word == source or len(source) >= 5
                and word.startswith(source[:-2]) and len(word) <= len(source) + 1 for source in source_words):
            continue
        return False
    return bool(words)


def _inspection_scope_check(text, frame):
    costs, scopes, rest, errors = 0, 0, [], []
    for match in re.finditer(r'[^.!?;\n]+[.!?;\n]*', text):
        clause = match.group(0).strip()
        if not clause:
            continue
        body = clause.casefold().replace('ё', 'е')
        # Resolve only a contiguous, source-owned work reference in this
        # clause. The original reply remains untouched. An unbound «её»
        # (cost, diagnostics, materials, another object) gains no authority.
        body = re.sub(
            r'(\b(?:стоимость|цену|цена)\s+работы\s+не\s+(?:назвать|определить)\s*'
            r'[—–,:-]\s*(?:нужно|необходимо|надо)\s+(?:сначала\s+)?'
            r'(?:определить|оценить)\s+)ее\s+объем\b',
            r'\1объем работы', body)
        unavailable = bool(_COST.search(body)
            and re.search(r'\b(?:не\s+видя\s+телевиз\w*|(?:без|до)\s+осмотра\s+(?:техник\w*|телевиз\w*))', body)
            and re.search(r'(?:назвать|определить).{0,20}\bне\s+(?:могу|можем|смогу|сможем)\b|'
                          r'\bне\s+(?:могу|можем|смогу|сможем).{0,20}(?:назвать|определить)|'
                          r'\bне\s+(?:назвать|определить)\b', body))
        scope = bool(re.search(r'\b(?:нужно|необходимо|надо)\b', body)
                     and (unavailable or re.search(r'\bосмотреть\s+(?:техник\w*|телевиз\w*)', body))
                     and re.search(r'\b(?:определить|оценить)\s+объем\s+работ\w*', body))
        price = unavailable or _after_inspection(clause) or bool(
            scope and _COST.search(body) and re.search(r'\bчтобы\s+(?:назвать|определить)\b', body))
        if not price and not scope:
            rest.append(clause)
            continue
        affirmative = body
        if unavailable:
            # Only the source's inability to quote before inspection may be
            # negative. A negated inspection/scope is a different condition.
            affirmative = re.sub(r'\bне\s+видя\b', 'видя', affirmative, count=1)
            affirmative = re.sub(r'\bне\s+(могу|можем|смогу|сможем|назвать|определить)\b',
                                 r'\1', affirmative, count=1)
        modals = re.findall(r'\b(?:могу|можем|смогу|сможем)\b', body)
        negated_modals = re.findall(r'\bне\s+(?:могу|можем|смогу|сможем)\b', body)
        if (re.search(r'\bне\b|\bнет\b', affirmative) or len(modals) > 1
                or unavailable and len(modals) != len(negated_modals)):
            errors.append('price_wording_inspection_scope_changed')
        if '?' in clause or not _covered_clause(body, 'undetermined', frame):
            errors.append('price_wording_unbound_price_clause')
        costs += int(price)
        scopes += int(scope)
    if costs != 1 or scopes != 1:
        errors.append('price_wording_inspection_scope_changed')
    return list(dict.fromkeys(errors)), ' '.join(rest)


def check(reply, payload, frame):
    """Return errors and the still-unvalidated selected clarification.

    Every clause must be accounted for. A matching amount or the candidate's
    self-reported conditions never exempts arbitrary additional text.
    """
    if not isinstance(reply, str) or frame != bound_frame(payload):
        return ['price_wording_binding_changed'], ''
    import assistant_policy as policy
    text = policy.GREETING_START.sub('', reply.strip(), count=1)
    execution_text = text
    if (frame.get('price_components') or {}).get('free_if_work_continues'):
        # A conditional noun is not a reported completed operation. Only
        # these explicit conditional terms are projected out; actual verbs
        # and the original text still go through all component checks.
        execution_text = re.sub(r'\bпри\s+(?:продолжении|выполнении|оказании)\s+(?:работ|услуг)\b',
                                '', text, flags=re.IGNORECASE)
    if _EXECUTION.search(execution_text):
        return ['price_wording_unconfirmed_execution'], ''
    for required in payload['decision_internal'].get('required_text', []):
        if text.count(required) != 1:
            return ['proposal_required_text_missing'], ''
        text = text.replace(required, '', 1).strip()
    numbers = [int(n.replace(' ', '').replace('\u00a0', '')) for n in _DIGITS.findall(text)]
    expected = [int(n.replace(' ', '').replace('\u00a0', '')) for n in _DIGITS.findall(frame['source_reply'])]
    if (sorted(numbers) != sorted(expected) if frame.get('price_components') else numbers != expected):
        return ['price_wording_amount_changed'], ''
    if frame['kind'] == 'inspection_scope_required':
        return _inspection_scope_check(text, frame)
    if frame.get('price_components'):
        import research_price_components
        return research_price_components.check(text, payload, frame, covered=_covered_clause,
            after_inspection=_after_inspection, excluded=_EXCLUDED)
    counts = {'after': 0, 'free': 0, 'materials': 0, 'consent': 0, 'numeric': 0}
    rest, price_parts, errors = [], [], []
    for match in re.finditer(r'[^,.!?;\n]+[,.!?;\n]*', text):
        clause = match.group(0).strip()
        if not clause:
            continue
        classified = False
        if _FREE.search(clause):
            if not frame['callout_free_in_city'] or not _city_callout(clause):
                errors.append('price_wording_free_scope_changed')
            counts['free'] += 1
            if not _covered_clause(clause, 'free', frame):
                errors.append('price_wording_unbound_price_clause')
            classified = True
        elif _MATERIALS.search(clause) and _EXCLUDED.search(clause):
            if not frame['materials_excluded']:
                errors.append('price_wording_extra_material_terms')
            counts['materials'] += 1
            subject = 'parts' if re.search(r'запчаст', clause, re.IGNORECASE) else 'materials'
            if subject != frame['exclusion_subject']:
                errors.append('price_wording_excluded_subject_changed')
            if not _covered_clause(clause, 'materials', frame):
                errors.append('price_wording_unbound_price_clause')
            classified = True
        elif _after_inspection(clause):
            if not frame['work_after_inspection']:
                errors.append('price_wording_stage_changed')
            counts['after'] += 1
            if not _covered_clause(clause, 'after', frame):
                errors.append('price_wording_unbound_price_clause')
            classified = True
        elif (clause.endswith('?') and _COST.search(clause)
              and re.search(r'устраива\w*|устро\w*|подход\w*|подойд\w*|соглас\w*', clause, re.IGNORECASE)
              and not re.search(r'\bуже\b|подтверд\w*|\bне\b|\bнет\b', clause, re.IGNORECASE)):
            if not frame['consent_required']:
                errors.append('price_wording_extra_consent_question')
            counts['consent'] += 1
            if not _covered_clause(clause, 'consent', frame):
                errors.append('price_wording_unbound_price_clause')
            classified = True
        elif prices._AMOUNT.search(clause):
            if not frame['amounts']:
                errors.append('price_wording_early_amount')
            counts['numeric'] += 1
            if not _covered_clause(clause, 'numeric', frame):
                errors.append('price_wording_unbound_price_clause')
            classified = True
        elif (frame['callout_free_in_city'] and frame['work_after_inspection']
              and clause.rstrip(',.!?;\n ') == 'До осмотра могу сориентировать только по выезду'
              and clause.rstrip(',.!?;\n ') in frame['source_reply']):
            # Optional current-source scope disclosure; no new price or fact.
            classified = True
        if classified:
            price_parts.append(clause)
        else:
            rest.append(clause)
    for name, wanted in (('after', frame['work_after_inspection']), ('free', frame['callout_free_in_city']),
                         ('materials', frame['materials_excluded']), ('consent', frame['consent_required']),
                         ('numeric', bool(frame['amounts']))):
        if counts[name] != int(wanted):
            errors.append('price_wording_' + name + '_conditions_changed')
    if frame['amounts']:
        price_text = ' '.join(price_parts)
        # Reject negated prices while retaining the actual materials exclusion
        # and the explicit lower-bound operator, not a general "no" exception.
        affirmative = _EXCLUDED.sub('', price_text)
        affirmative = re.sub(r'\bне\s+менее\b', 'от', affirmative, flags=re.IGNORECASE)
        if re.search(r'\bне\b|\bнет\b', affirmative, re.IGNORECASE):
            errors.append('price_wording_negated_price')
        lower_bound = bool(re.search(r'\bот\s+\d|\bне\s+менее\s+\d', price_text, re.IGNORECASE))
        if lower_bound != (frame['kind'] == 'service_minimum'):
            errors.append('price_wording_tariff_kind_changed')
        mid = 'local-price-wording-validation-not-an-observed-send'
        rows = payload['messages'] + [{'id': mid, 'direction': 'out', 'sender_type': 'operator',
                                         'delivery_status': 'delivered', 'body': price_text}]
        state = {'message_id': mid, 'amount': frame['amounts'][0]}
        if not prices.prior_quote_verified(rows, payload['known'], state):
            errors.append('price_wording_tariff_not_verified')
        if frame['kind'] == 'fixed_service_unit':
            quoted = prices.mnc_fixed_quote(rows, payload['known'], state)
            units, unit_valid = prices.mnc_fixed_unit_mentions(price_text, frame['tariff'])
            if (not unit_valid or len(units) != 1
                    or not quoted or quoted['key'] != frame['tariff']['key']
                    or quoted['unit'] != frame['tariff']['unit']
                    or quoted['amount'] != frame['tariff']['amount']):
                errors.append('price_wording_service_unit_changed')
    return list(dict.fromkeys(errors)), ' '.join(rest)
