"""Typed current-price components; never derive tariffs from example replies."""
import copy
import re

import assistant_prices as prices


def offer(price, messages, known):
    source = price['reply']
    amount = price['amounts']
    direction = known['direction']
    if not amount:
        return None
    if direction == 'mnc' and price.get('tariff_kind') == 'fixed_service_total':
        tariff = prices.mnc_fixed_tariff(messages, known)
        quantity = prices.tv_mount_quantity(messages, tariff)
        if (not tariff or not quantity or tariff != price.get('tariff')
                or quantity != price.get('quantity')
                or amount != [quantity['count'] * tariff['amount'], tariff['amount']]):
            return None
        return {'kind': 'structured_price', 'price_components': {'type': 'total',
            'count': quantity['count'], 'total': amount[0], 'unit_amount': amount[1]},
            'tariff': copy.deepcopy(tariff), 'quantity': copy.deepcopy(quantity)}
    if len(amount) != 1:
        return None
    value = amount[0]
    if direction == 'mnc':
        basis = prices.mnc_price_basis(messages, known)
        if basis and value == basis['amount'] and set(basis['rules']) <= set(price['rules']):
            return {'kind': 'structured_price', 'price_components': {
                'type': 'basis', 'amount': value, 'lower_bound': True,
                'unit': 'metre' if basis['kind'] == 'wire' else None}, 'basis': copy.deepcopy(basis)}
        return None
    if source.startswith(('Первичная диагностика без разбора техники',
                          'Программная диагностика без разбора техники')):
        labels = ('первичн', 'техническ') if direction == 'bt' else ('программн', 'аппаратн')
        expected = 800 if direction == 'bt' else 500
        if value == expected and {'DOC-L0759', 'DOC-L0760', 'DOC-L0761'} <= set(price['rules']):
            return {'kind': 'structured_price', 'price_components': {
                'type': 'diagnostic_split', 'amount': value, 'primary_label': labels[0],
                'technical_label': labels[1], 'free_if_work_continues': True}}
    if (direction == 'kp' and prices._partner_diagnostic_fee_applies(known)
            and source.startswith('Выезд и диагностика бесплатны при выполнении работ.')
            and value == 1000 and prices.KP_PARTNER_DIAGNOSTIC_RULE in price['rules']):
        return {'kind': 'structured_price', 'price_components': {
            'type': 'partner_refusal', 'amount': value, 'free_if_work_continues': True}}
    if (direction == 'kp' and prices.DIAGNOSTIC_ONLY_RULE in price['rules']
            and source.startswith('Диагностика без ремонта — от 500 рублей.') and value == 500):
        return {'kind': 'structured_price', 'price_components': {
            'type': 'diagnostic_only', 'amount': value, 'lower_bound': True, 'unit': None}}
    if ((direction == 'kp' and 'KP-L0484' in price['rules'] and value == 500
         and source.startswith('Такая услуга у меня от 500 рублей'))
            or (direction == 'bt' and source.startswith(f'Стоимость услуги от {value} рублей')
                and (value == 800 and prices.BT_800_RULE in price['rules']
                     or value == 2000 and 'DOC-L0419' in price['rules']))):
        return {'kind': 'structured_price', 'price_components': {
            'type': 'service', 'amount': value, 'lower_bound': True, 'unit': None}}
    if (direction == 'kp' and 'TG1-663' in price['rules']
            and source.startswith(f'Стоимость этой услуги — {value} рублей')):
        return {'kind': 'structured_price', 'price_components': {
            'type': 'service', 'amount': value, 'lower_bound': False,
            'unit': 'program' if ' за одну программу' in source else None}}
    return None


def _money(clause):
    return [int(n.replace(' ', '')) for n in prices._AMOUNT.findall(clause)]


def _lower(clause):
    return bool(re.search(r'\bот\s+\d|\bне\s+менее\s+\d', clause, re.IGNORECASE))


def _units(clause):
    return re.findall(r'(?:за\s+|/\s*)(?:(?:одну|один|одной|одного|1|погонный)\s+)?'
                      r'(?:программ\w*|метр\w*|штук\w*|шт\b|час\w*|единиц\w*|точк\w*|'
                      r'диагностик\w*|выезд\w*|м[²2]?)\b', clause)


def _work_condition(clause):
    return bool(re.search(r'\bпри\s+(?:продолжени\w*|выполнени\w*|оказани\w*)\s+(?:работ\w*|услуг\w*)',
                          clause, re.IGNORECASE)
                and not re.search(r'\bне\b|\bнет\b|отказ', clause, re.IGNORECASE))


def check(text, payload, frame, *, covered, after_inspection, excluded):
    """Check every component and the original native quote independently."""
    component = frame['price_components']
    kind = component['type']
    if kind == 'total':
        actual = prices._tv_total_components(text)
        expected = {key: component[key] for key in ('count', 'total')}
        expected['unit'] = component['unit_amount']
        if (actual != expected or frame['consent_required'] and not text.rstrip().endswith('?')):
            return ['price_wording_total_changed'], ''
        return _native_check(text, payload, frame), ''
    counts = {'numeric': 0, 'primary': 0, 'technical': 0, 'free': 0,
              'materials': 0, 'after': 0, 'consent': 0}
    rest, parts, errors = [], [], []
    for match in re.finditer(r'[^,.!?;\n]+[,.!?;\n]*', text):
        clause = match.group(0).strip()
        if not clause:
            continue
        clean = clause.strip(' ,.!?;\n').casefold().replace('ё', 'е')
        role = None
        if re.search(r'бесплат\w*|без\s+оплат\w*', clean):
            role = 'free'
            scope = (bool(re.search(r'диагност', clean))
                     and (kind != 'partner_refusal' or bool(re.search(r'выезд', clean))))
            if (kind not in ('diagnostic_split', 'partner_refusal') or not scope
                    or not _work_condition(clean) or re.search(r'\b(?:ремонт|материал|запчаст)\w*', clean)
                    or kind == 'diagnostic_split' and re.search(r'выезд', clean)):
                errors.append('price_wording_diagnostic_free_condition_changed')
        elif excluded.search(clean):
            role = 'materials'
            expected_subject = frame.get('exclusion_subject')
            subject = 'parts' if re.search(r'запчаст', clean) else 'materials'
            if not frame['materials_excluded'] or subject != expected_subject or not covered(clause, 'materials', frame):
                errors.append('price_wording_excluded_subject_changed')
        elif after_inspection(clause):
            role = 'after'
            if not frame['work_after_inspection'] or not covered(clause, 'after', frame):
                errors.append('price_wording_stage_changed')
        elif (clause.endswith('?') and re.search(r'цен|стоим|услови', clean)
              and re.search(r'устраива\w*|устро\w*|подход\w*|подойд\w*|соглас\w*', clean)):
            role = 'consent'
            if not frame['consent_required']:
                errors.append('price_wording_extra_consent_question')
        elif _money(clause):
            amounts = _money(clause)
            if amounts != [component['amount']]:
                errors.append('price_wording_amount_changed')
            units = _units(clean)
            wanted_unit = component.get('unit')
            if (wanted_unit == 'program' and not (len(units) == 1 and 'программу' in units[0])
                    or wanted_unit == 'metre' and not (len(units) == 1 and units[0].endswith('метр'))
                    or wanted_unit is None and units):
                errors.append('price_wording_service_unit_changed')
            if kind == 'diagnostic_split':
                if (re.search(component['primary_label'] + r'\w*\s+диагност', clean)
                        and re.search(r'без\s+разбора', clean)):
                    role = 'primary'
                    if _lower(clean):
                        errors.append('price_wording_primary_must_be_fixed')
                elif (re.search(component['technical_label'] + r'\w*\s+диагност', clean)
                      and re.search(r'(?<!без )\bс\s+разбором', clean)):
                    role = 'technical'
                    if not _lower(clean):
                        errors.append('price_wording_technical_must_be_minimum')
                else:
                    errors.append('price_wording_diagnostic_type_changed')
                    role = 'numeric'
            else:
                role = 'numeric'
                if kind == 'partner_refusal':
                    if _lower(clean) or not re.search(r'при\s+отказе\s+от\s+работ', clean) or re.search(r'\bза\b', clean):
                        errors.append('price_wording_refusal_fee_changed')
                else:
                    if _lower(clean) != component['lower_bound']:
                        errors.append('price_wording_tariff_kind_changed')
                    if kind == 'diagnostic_only' and not re.search(r'диагностик\w*\s+без\s+ремонта', clean):
                        errors.append('price_wording_diagnostic_scope_changed')
        if role is None:
            rest.append(clause)
            continue
        counts[role] += 1
        if role not in ('materials', 'after') and not covered(clause, 'structured', frame):
            errors.append('price_wording_unbound_price_clause')
        if re.search(r'\bне\b|\bнет\b', excluded.sub('', clean)) and role != 'materials':
            errors.append('price_wording_negated_price')
        parts.append(clause)
    wanted = {'numeric': int(kind != 'diagnostic_split'),
              'primary': int(kind == 'diagnostic_split'), 'technical': int(kind == 'diagnostic_split'),
              'free': int(kind in ('diagnostic_split', 'partner_refusal')),
              'materials': int(frame['materials_excluded']), 'after': int(frame['work_after_inspection']),
              'consent': int(frame['consent_required'])}
    if counts != wanted:
        errors.append('price_wording_component_missing_or_repeated')
    errors.extend(_native_check(' '.join(parts), payload, frame))
    return list(dict.fromkeys(errors)), ' '.join(rest)


def _native_check(text, payload, frame):
    mid = 'local-structured-price-validation-not-an-observed-send'
    rows = payload['messages'] + [{'id': mid, 'direction': 'out', 'sender_type': 'operator',
        'delivery_status': 'delivered', 'body': text}]
    state = {'message_id': mid, 'amount': frame['amounts'][0]}
    if not prices.prior_quote_verified(rows, payload['known'], state):
        return ['price_wording_tariff_not_verified']
    return []
