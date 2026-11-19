"""Versioned primary sources and code-enforced decision/output constraints."""

import json
import re
import contact_facts
import contact_phone
from functools import lru_cache
from pathlib import Path
from typing import Any

import assistant_catalog
import assistant_prices
import assistant_qualifiers
import contact_address
import filials
import qualification_state
import territory
import own_visit

VERSION = "2026-11-09.296"

_VISIT_DAY = r'\b(?:послезавтра|сегодня|завтра|понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье)\b'
WORK_DURATION_RULE = 'OWNER-WORK-DURATION-NO-ESTIMATE-20261024'
WORK_DURATION_REPLY = 'Заранее по времени работы не подскажу — зависит от объёма и сложности.'


def _visit_question_now(zone):
    from datetime import datetime
    return datetime.now(zone)


def _direct_visit_time_question(text):
    """Current customer's request, not a quote, callback or time to think."""
    text = text.casefold().replace('ё', 'е')
    if re.search(r'позвон|перезвон|звонк|созвон|стоим|цен[аыу]|подумать|не\s+(?:надо|нужно|пишите|спрашиваю)|'
                 r'время\s+пока\s+не\s+обсуждаем|\bне\s+(?:в|к)\s*\d|\b(?:вчера|позавчера)\b|'
                 r'привез|привезт|достав|забрать|материал|детал|\bесли\b|'
                 r'(?:мастер|сотрудник|сосед)\w*[^.!?]{0,30}(?:сказал|написал|спросил)|[«»“”"]', text):
        return False
    if (re.search(_VISIT_DAY, text) and re.search(r'\b(?:можете|сможете|сможите|приедете|подъедете)\b', text)
            and not re.search(r'\bне\s+(?:сегодня|завтра|послезавтра)\b', text)):
        return True
    if (re.search(_VISIT_DAY, text) and re.search(r'\b(?:в|к)\s*(?:[01]?\d|2[0-3])(?:[.:][0-5]\d)?\b', text)
            and re.search(r'\bудобно\b', text) and '?' in text
            and not re.search(r'куп|получ|покуп|продаж|\bне\s+(?:сегодня|завтра|послезавтра)\b', text)):
        return True
    return bool(re.search(
        r'\b(?:напишите|подскажите|скажите|уточните)\s*(?:,?\s*пожалуйста\s*,?\s*)?(?:во?\s+сколько|время)\b|'
        r'\b(?:когда|во\s+сколько|через\s+сколько)(?:[^.!?]{0,40})(?:приед|приеха|подъех|подъед|ждать\s+мастера)', text))


def _work_time_kind(text):
    """Work duration, arrival and an unspecified timing question differ."""
    body = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', str(text or ''))
    if re.search(r'позвон|перезвон|звонк|достав|гарант|срок\w*\s+(?:договор|оплат)|\bесли\b|'
                 r'не\s+(?:надо|нужно|спрашиваю|обсуждаем)|\b(?:вчера|раньше|прошлый)\b|'
                 r'срок\s+службы|проработает|служит|хватает|держит\s+заряд|'
                 r'(?:как\s+долго|сколько\s+времени)[^.!?]{0,30}(?:в\s+этой\s+сфере|этим\s+занимаетесь)|'
                 r'(?:мастер|сотрудник)[^.!?]{0,20}(?:был|пробыл|работал)\b',body,re.I):
        return ''
    for clause in re.split(r'[.!;\n]+',body):
        if re.search(r'(?:мастер|сосед|сотрудник)\w*[^.!?]{0,30}(?:сказал|спросил|написал)|со\s+слов',clause,re.I):
            continue
        arrival = re.search(r'приезд|до\s+приезда|дорог|доехать|добрать|ждать\s+(?:вас|мастера)',clause,re.I)
        if not arrival and re.search(
                r'сколько\s+(?:по\s+)?времени|как\s+долго|долго\s+ли|сколько\s+(?:займ[её]т|продлится)|'
                r'за\s+сколько[^.!?]{0,25}(?:сдела|выпол|почин|собра|установ|подключ)|'
                r'срок\w*\s+(?:выполнени|ремонт|работ)|'
                r'по\s+времени[^.!?]{0,30}(?:работ|ремонт|установ|настрой|сбор|займ)|'
                r'(?:сдела|выпол|почин|собра|собер|установ)\w*[^.!?]{0,25}\bдо\s*\d|'
                r'за\s+(?:час|полчаса|день)\b[^.!?]{0,20}(?:управ|сдела|почин|собра)|'
                r'(?:управ|справ|сдела|почин)\w*[^.!?]{0,15}за\s+(?:час|полчаса|день|\d+\s*(?:минут|час|дн))',clause,re.I):
            return 'duration'
        if not arrival and re.search(r'\b(?:что|как|а)\s+по\s+срокам\b|\bкакие\s+сроки\b|^\s*сроки\s*\?',clause,re.I):
            return 'ambiguous'
    return ''


def _current_work_time_question(messages):
    """Bind a short follow-up to observed speech, never the unsent question."""
    current = assistant_prices.current_enquiry_messages(messages)
    for index in range(len(current)-1,-1,-1):
        message = current[index]
        bad = (message.get('out_pending') or str(message.get('delivery_status') or '').casefold()
               in ('pending','queued','sending','failed','error','cancelled','canceled','dismissed'))
        if (message.get('direction') == 'out' and not bad
                and str(message.get('sender_type') or '').casefold()
                in ('','operator','employee','staff','human','bot','assistant')):
            break
        if not contact_facts._client_intent_message(message) or bad or not message.get('id'):
            continue
        body = str(message.get('body') or message.get('text') or '')
        kind = _work_time_kind(body)
        previous = None
        if not kind and re.fullmatch(r'\s*(?:а\s+)?(?:ну\s+)?(?:хотя\s+бы\s+)?примерно[?!.\s]*',body,re.I):
            previous = next((m for m in reversed(current[:index]) if contact_facts._client_intent_message(m)
                and not m.get('out_pending') and str(m.get('delivery_status')or'').lower()
                not in ('failed','pending','queued','sending','error','cancelled','canceled','dismissed')),None)
            spoken = [m for m in current[:index] if m.get('direction')=='out' and not m.get('out_pending')
                      and str(m.get('sender_type')or'').lower()in ('','operator','employee','staff','human','bot','assistant')
                      and str(m.get('delivery_status')or'').lower()not in ('failed','pending','queued','sending','error')]
            answer = str((spoken[-1]if spoken else{}).get('body')or'')
            if (previous and _work_time_kind(previous.get('body')or'')=='duration'
                    and re.search(r'времен|срок|быстро|точно|скажу|минут|час',answer,re.I)
                    and not re.search(r'цен|стоим|руб|₽',answer,re.I)):
                kind = 'duration'
        if kind:
            return dict(kind=kind,message_id=message['id'],quote=body,
                        source='unanswered_client_work_time_question',
                        previous_client_message_id=(previous or{}).get('id',''),
                        duration_verified=False,appointment_confirmed=False)
        if re.match(r'^\s*(?:новый|другой)\s+заказ\b|^\s*новое\s+обращение\b',body,re.I):
            return None
        if _direct_visit_time_question(body):
            return None
    return None


def current_visit_time_question(messages):
    """An unanswered actual client turn, not staff speech or a delivery plan."""
    turn = []
    for message in reversed(messages):
        if (message.get('direction') == 'out'
                and str(message.get('sender_type') or '').casefold() in ('', 'operator', 'employee', 'bot', 'assistant')
                and not message.get('out_pending')
                and str(message.get('delivery_status') or '').casefold()
                not in ('pending', 'queued', 'sending', 'failed', 'error', 'cancelled', 'canceled', 'dismissed')):
            break
        if contact_facts._client_intent_message(message):
            turn.append(message)
    turn.reverse()
    if not turn:
        return None
    quote = '\n'.join(str(m.get('body') or m.get('text') or '') for m in turn)
    if not _direct_visit_time_question(quote):
        return None
    return dict(message_id=turn[-1].get('id', ''), evidence_ids=[m.get('id', '') for m in turn],
                quote=quote, source='current_client_turn_and_branch_clock',
                availability_verified=False, appointment_confirmed=False)


def _visit_time_answer(messages, known, geo):
    """Offer a normative window, never a booking or actual crew availability.

    Called only after existing-order, geography, service and price gates.
    A later acceptance still needs a verified own-send path; ordinary human
    promises must retain the existing appointment lookup guard.
    """
    question = current_visit_time_question(messages)
    if not question:
        return None
    if geo.get('status') != 'known':
        return dict(requires_operator=True)
    city, direction = known.get('city'), known.get('direction')
    loc = None
    if known.get('latitude') is not None and known.get('longitude') is not None:
        loc = territory.locate(known['latitude'], known['longitude'], city, direction)
    loc = loc or territory.city_profile_from_map(city, direction)
    # Conflicting contours cannot be replaced by the city default. A whole-
    # city profile is usable only when all current contours agree.
    if not loc:
        names = {territory._norm(name) for name in filials.имена_города(city)} | {territory._norm(city)}
        if any(a.get('direction') == direction and territory._norm(a.get('city')) in names
               for a in (territory.zones() or {}).get('areas', [])):
            return dict(requires_operator=True)
    profile = territory.slot_profile(city, loc=loc, far_trip_ctx={'direction': direction})
    lead = profile.get('lead')
    windows = {'час-полтора': (60, 90, 'час-полтора'),
               'два, два с половиной часа': (120, 150, 'два-два с половиной часа'),
               'три, три с половиной часа': (180, 210, 'три-три с половиной часа')}
    if profile.get('needs_approval') or lead not in windows:
        return dict(requires_operator=True)
    import contact_cities
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    branch = contact_cities.city_by_name(city)
    if not branch:
        return dict(requires_operator=True)
    now = _visit_question_now(ZoneInfo(branch.tz)).astimezone(ZoneInfo(branch.tz))
    low, high, wording = windows[lead]
    start, end = now + timedelta(minutes=low), now + timedelta(minutes=high)
    earliest, latest = profile.get('earliest', '10:00'), profile.get('latest', '21:30')
    days = re.findall(_VISIT_DAY, question['quote'].casefold().replace('ё', 'е'))
    has_clock = re.search(r'\b(?:в|к)\s*\d', question['quote'], re.I)
    preference = contact_facts.requested_visit(messages)
    current_preference = preference.get('message_id') in question['evidence_ids']
    if (current_preference and re.search(r'после\s+обеда|с\s+утра|утром|вечером|дн[её]м|'
                                        r'\b(?:после|до)\s+\d|\bс\s*\d', preference['window'], re.I)):
        # A supplied period is already handled by the source-bound preference
        # acknowledgement plus the remaining qualification/price question.
        # Never replace it with an unrelated relative window or ask it again.
        return None
    if days and (days != ['сегодня'] or has_clock):
        if len(days) != 1:
            return dict(requires_operator=True)
        day = days[0]
        offsets = {'сегодня': 0, 'завтра': 1, 'послезавтра': 2}
        weekdays = ['понедельник', 'вторник', 'среду', 'четверг', 'пятницу', 'субботу', 'воскресенье']
        offset = offsets[day] if day in offsets else (weekdays.index(day) - now.weekday()) % 7
        date = (now + timedelta(days=offset)).date()
        clocks = re.findall(r'\b(?:в|к)\s*((?:[01]?\d|2[0-3])(?:[.:][0-5]\d)?)(?![\d:.])', question['quote'], re.I)
        # Bounds/ranges need their own interpretation. Never erase them and
        # replace the client's requested time with a generic day offer.
        if (has_clock and not clocks or len(clocks) > 1
                or re.search(r'\b(?:после|до|утром|вечером|ночью|днем)\b|\bс\s*\d', question['quote'], re.I)
                or re.search(r'\bследующ', question['quote'], re.I)):
            return dict(requires_operator=True)
        clock = None
        if clocks:
            parts = clocks[0].replace('.', ':').split(':')
            clock = f'{int(parts[0]):02d}:{int(parts[1]) if len(parts) == 2 else 0:02d}'
            if (not earliest <= clock <= latest
                    or date == now.date() and date.isoformat() + 'T' + clock < start.strftime('%Y-%m-%dT%H:%M')):
                return dict(requires_operator=True)
        elif date == now.date() and (end.date() != now.date() or end.strftime('%H:%M') > latest):
            return dict(requires_operator=True)
        label = 'в ' + day if day in weekdays else 'на ' + day
        reply = (f'Пожелание {label} к {clock} учту. Время визита пока не подтверждено.' if clock
                 else f'{label.capitalize()} на какое время вам удобно?')
        if current_preference and preference.get('window') == day and not clock:
            reply = f'Учту пожелание: {day}. На какое время вам удобно?'
        return dict(reply=reply, offer=None, question=dict(question, requested_day=day,
            requested_date=date.isoformat(), requested_time=clock, timezone=branch.tz,
            earliest=earliest, latest=latest))
    if start.date() != now.date() or end.date() != now.date() or not earliest <= start.strftime('%H:%M:%S') <= end.strftime('%H:%M:%S') <= latest + ':00':
        return dict(reply=f'Часы приёма — {earliest}–{latest}. На какое время вам удобно?', offer=None)
    return dict(reply=f'Через {wording} вам удобно будет?', offer=dict(
        kind='relative_window', min_minutes=low, max_minutes=high,
        city=city, direction=direction, timezone=branch.tz,
        earliest=earliest, latest=latest, requires_confirmation=True,
        appointment_confirmed=False))


def visit_offer_is_current(draft, messages, known):
    """Relative offers must still fit the current branch hours at delivery."""
    if not draft or not (draft.get('visit_offer') or draft.get('visit_time_question')):
        return True
    current = _visit_time_answer(messages, known, geography(known.get('city'),
        known.get('direction'), known.get('latitude'), known.get('longitude')))
    return bool(current and current.get('offer') == draft.get('visit_offer')
                and (not draft.get('visit_time_question')
                     or current.get('question') == draft['visit_time_question']))


def _reduced_furniture_scope(incoming):
    kitchen_seen = False
    for text in incoming:
        if kitchen_seen and re.search(r"(?:один|только)\s+шкаф\b", text, re.IGNORECASE) and not re.search(r"кухн|гарнитур", text, re.IGNORECASE):
            return True
        kitchen_seen = kitchen_seen or bool(re.search(r"(?:собра|разобра).{0,100}(?:кухн|гарнитур)|кухонн\w*\s+гарнитур", text, re.IGNORECASE))
    return False
AUTO_ENABLED = False  # Draft endpoints never execute actions; personal execution has its own owner session.


def _prior_service_refusal(messages):
    if (not messages or messages[-1].get('direction') != 'in'
            or not re.search(r'не\s+знаете|хотя\s+бы[^.!?]{0,25}подсказать|что\s+(?:же\s+)?это|'
                             r'(?:какая|в\s+ч[её]м)\s+причин|от\s+чего', messages[-1]['body'], re.I)):
        return None
    refusal = None
    for message in messages[:-1]:
        body = message.get('body', '')
        if (message.get('direction') == 'in'
                and re.search(r'новая\s+заявка|новый\s+заказ|по\s+другому\s+вопросу|теперь\s+нужно', body, re.I)):
            refusal = None
        if (message.get('direction') != 'out' or message.get('out_pending')
                or str(message.get('delivery_status') or '').lower()
                in ('pending', 'queued', 'sending', 'failed', 'error', 'cancelled', 'canceled', 'dismissed')):
            continue
        body = re.sub(r'«[^»]*»|"[^"\n]*"', '', body)
        if (re.search(r'\bесли\b|не\s+(?:говорил|писал|сказал)|(?:не|нельзя)\s+сказать', body, re.I)
                or re.search(r'\b(?:но|зато)\b', body, re.I)):
            continue
        if re.search(r'\bне\s+(?:смогу|могу)\s+(?:вам\s+)?помочь\b|\bне\s+занимаюсь\b', body, re.I):
            refusal = dict(message_id=message.get('id', ''), quote=message['body'],
                           source='prior_staff_statement_unverified', crm_write_confirmed=False)
    return refusal


def _post_service_price_complaint(messages):
    """A reported past repair dispute outranks new-order contact collection."""
    evidence = []
    for message in messages:
        if message.get('direction') != 'in':
            continue
        body = message.get('body', '')
        if re.search(r'(?:^|\n)\s*Сделка состоялась', body, re.I):
            continue  # A pasted third-party review is not this client's payment.
        priced_work = re.search(r'цен|стоим|расцен|сумм', body, re.I) and re.search(r'ремонт|прошив|мастер|работ', body, re.I)
        breakdown = re.search(r'состоял\w*[^.!?\n]{0,35}(?:цен|стоим)', body, re.I) and re.search(r'\?|расскаж|поясн|объясн', body, re.I)
        paid_dispute = re.search(r'заплатил|оплатил|взял\w*\s+с\s+меня|с\s+меня\s+взял', body, re.I) and re.search(r'почему|откуда|за\s+что|возмущ|разбират|поясн|объясн', body, re.I)
        hypothetical = re.search(r'\b(?:если|допустим|предположим)\b',body,re.I)
        paid_fee = (re.search(r'\b(?:взял[аи]?|взяли|заплатил[аи]?|оплатил[аи]?|отдал[аи]?)\b', body, re.I)
                    and re.search(r'осмотр|диагност|приезд|выезд', body, re.I)
                    and re.search(r'\b\d+(?:[ .,]\d+)*\b', body)
                    and re.search(r'почему|за\s+что|возмущ|разбират|поясн|объясн|'
                                  r'проблема\s+(?:та\s+же|не\s+решена)|не\s+бер[её]т\s+трубку', body, re.I))
        refund = re.search(r'\b(?:возвращайте|верни(?:те)?|возврати(?:те)?)\b[^.!?\n]{0,35}(?:деньг|оплат|сумм)|'
                           r'\b(?:сделайте|оформите|требую|жду|жд[её]м)\b[^.!?\n]{0,25}\bвозврат\b|'
                           r'\bвозврат\b[^.!?\n]{0,25}\b(?:жду|жд[её]м|требую)\b',body,re.I)
        document_charge = (re.search(r'\bв\s+(?:договоре|акте|квитанции)\b[^.!?\n]{0,45}\b(?:поставили|написали|указали|приписали|насчитали)\b',body,re.I)
                           and re.search(r'воровство|обман|бешен|приписк|лишн|неверн|почему|откуда',body,re.I)
                           and re.search(r'\b\d+\s*(?:руб|₽|р\b)',body,re.I))
        literal = re.sub(r'«[^»]*»|"[^"]*"|“[^”]*”', ' ', body)
        agreed_price_dispute = (
            re.search(r'\bя\s+с\s*вами\s+на\s+\d{3,6}\s+договорил\w*|'
                      r'\bмы\s+с\s*вами\s+договаривал\w*\s+на\s+\d{3,6}\b', literal, re.I)
            and re.search(r'приш[её]л|приехал|подъехал|после\s+(?:работ|визита)', literal, re.I)
            and re.search(r'не\s+в\s+курсе|не\s+знает|не\s*хорошо|плачу\s+как|расс?чит|доплат', literal, re.I))
        if (priced_work and (breakdown or paid_dispute) or refund or paid_fee or document_charge or agreed_price_dispute) and not hypothetical:
            fee_question = bool(paid_fee and re.search(r'за\s+что|почему', body, re.I)
                                and not refund and not re.search(r'проблема\s+(?:та\s+же|не\s+решена)|не\s+бер[её]т\s+трубку', body, re.I))
            evidence.append(dict(message_id=message.get('id', ''), quote=body[:500], source='client_report_unverified',
                                 kind='agreed_price_visit_dispute' if agreed_price_dispute else 'disputed_document_charge' if document_charge else 'paid_visit_fee_question' if fee_question else 'post_service_complaint'))
    if not evidence:
        # A charge and the objection can be split across consecutive client
        # messages. A provider quote alone is not a reported paid visit.
        recent = [m for m in messages if m.get('direction') == 'in' and not re.search(r'(?:^|\n)\s*Сделка состоялась', m.get('body', ''), re.I)][-6:]
        text = '\n'.join(m.get('body', '') for m in recent)
        paid = re.search(r'\b(?:взял[аи]?|взяли|заплатил[аи]?|оплатил[аи]?|отдал[аи]?)\b', text, re.I)
        work = re.search(r'ремонт|настройк|обслуживан|работ[аыу]', text, re.I)
        amount = re.search(r'\b\d+(?:[ .,]\d+)*\b', text)
        objection = re.search(r'буду[^.!?\n]{0,20}(?:писать|оставлять)[^.!?\n]{0,12}отзыв|'
                              r'думал[^.!?\n]{0,100}\bно\s+не\s+\d|возмущ|за\s+что[^.!?\n]{0,30}взял', text, re.I)
        if paid and work and amount and objection and not re.search(r'\b(?:если|допустим|предположим)\b', text, re.I):
            evidence = [dict(message_id=m.get('id', ''), quote=m.get('body', '')[:500],
                             source='client_report_unverified') for m in recent if m.get('body', '').strip()]
    if not evidence:
        previous_client = None
        arrival = None
        for message in assistant_prices.current_enquiry_messages(messages):
            body = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', message.get('body', ''))
            if message.get('direction') == 'out':
                delivered = (not message.get('out_pending') and str(message.get('delivery_status') or '').lower()
                             not in ('failed', 'error', 'pending', 'queued', 'sending', 'cancelled', 'canceled'))
                arrival_question = previous_client and re.search(r'подъезжаете|приехали|подъехали|вы\s+уже\s+на\s+месте', previous_client.get('body', ''), re.I)
                if delivered and arrival_question and re.fullmatch(r'\s*(?:я\s+)?(?:уже\s+тут|уже\s+на\s+месте|приехал)[.!\s]*', body, re.I):
                    arrival = dict(message_id=message.get('id', ''), quote=body, verified=False)
                continue
            if message.get('direction') != 'in':
                continue
            previous_client = message
            if (arrival and re.search(r'\bшок[^.!?\n]{0,25}цен|цен[^.!?\n]{0,25}\bшок', body, re.I)
                    and not re.search(r'\bесли\b|допустим|не\s+в\s+шоке|не\s+шок', body, re.I)):
                evidence = [dict(message_id=message.get('id', ''), quote=body[:500],
                                 source='client_objection_after_staff_arrival_claim_unverified',
                                 kind='post_service_complaint', arrival_claim=arrival)]
                break
    return evidence


def _property_damage_complaint(messages):
    """Preserve a client allegation, never infer liability or a paid refund."""
    for message in messages:
        if message.get('direction') != 'in':
            continue
        body = message.get('body','')
        item = r'(?:полк\w*|стен\w*|обо\w*|мебел\w*|двер\w*|стол\w*|шкаф\w*|кроват\w*)'
        damage = r'(?:пробили|повредили|испортили|сломали|поцарапали)'
        direct = re.search(
            r'\bвы\s+(?:(?:мне|нам)\s+)?' + item + r'\s+(?:(?:случайно|сильно|снова)\s+)?' + damage + r'\b|'
            r'\bвы\s+(?:(?:случайно|сильно|снова)\s+)?' + damage + r'\s+(?:(?:мне|нам|верхнюю|новую)\s+)?' + item,
            body, re.I)
        if direct:
            clause = re.split(r'[.!?\n]', body[:direct.start()])[-1] + direct[0]
            if (not re.search(r'\b(?:если|допустим|вдруг)\b', clause, re.I)
                    and not re.search(r'отверсти|штроб|\bдля\s+(?:креп|анкера|монтаж)', body, re.I)):
                return dict(message_id=message.get('id',''),quote=body[:700],source='client_report_unverified')
        if (re.search(r'после\s+(?:работ\w*|вас|визита|мастера)|ваш\s+мастер',body,re.I)
                and re.search(r'испорч\w*\s+(?:обо|стен|пол|мебел)|пробит\w*[^.!?\n]{0,25}стен|повред\w*[^.!?\n]{0,25}(?:стен|обо|пол|мебел|имуще)',body,re.I)):
            return dict(message_id=message.get('id',''),quote=body[:700],source='client_report_unverified')
    return {}


def _missed_visit_complaint(messages):
    """Client-reported non-arrival is an existing-order complaint, not intake."""
    evidence = []
    for message in messages:
        if message.get('direction') != 'in':
            continue
        body = message.get('body', '')
        if re.search(r'(?:^|\n)\s*Сделка состоялась', body, re.I):
            continue
        for clause in re.split(r'[.!?\n]+', body):
            if re.search(r'\b(?:если|допустим|вдруг)\b', clause, re.I):
                continue
            if re.search(r'\bдруг\w*\s+(?:мастер|специалист)', clause, re.I) and not re.search(r'\bваш|от\s+вас', clause, re.I):
                continue
            if re.search(r'\b(?:мастер|специалист|вы|он)\b[^.!?\n]{0,60}(?:так\s+и\s+)?не\s+(?:приехал\w*|появил\w*|приш[её]л|пришл\w*|подъехал\w*)\b|'
                         r'^\s*(?:вы\s+)?(?:так\s+и\s+)?не\s+(?:приехали|появились|пришли|подъехали)\b', clause, re.I):
                evidence.append(dict(message_id=message.get('id',''),quote=body[:700],source='client_report_unverified'))
                break
    return evidence


def _unverified_arrival_followup(messages, facts):
    """Keep a direct waiting query only through adjacent contact additions."""
    import contact_address
    import contact_phone
    def only_parts(value):
        # Reuse the address parser's validated part grammar; reject any
        # substantive prose instead of discarding a new service/question.
        return bool(contact_address.parts_only(value) and all(
            kind in ('office','entrance','floor','intercom','num') or
            (kind == 'other' and re.fullmatch(r'[,;().]', text))
            for kind,text in contact_address._звенья(value)))
    contacts = []
    query = re.compile(r'\s*(?:(?:здравствуйте|добрый\s+(?:день|вечер)|доброе\s+утро)[,!\s]+)?'
        r'(?:(?:когда\s+)?(?:(?:нам|мне)\s+)?вас\s+(?:ещ[её]\s+)?(?:ждать|ожидать)'
        r'(?:\s+(?:сегодня|завтра))?(?:\s+или\s+(?:(?:нам|мне)\s+)?(?:найти|искать)\s+'
        r'(?:кого[ -]то\s+другого|другого\s+(?:мастера|специалиста)))?'
        r'|вы\s+(?:уже\s+)?в\s+пути)[?!.\s]*', re.I)
    if not any(m.get('direction') == 'in' and query.fullmatch(str(m.get('body') or m.get('text') or ''))
               for m in messages):
        return None
    for message in reversed(messages):
        if message.get('direction') != 'in':
            continue
        if message.get('sender_type', 'client') not in ('client','customer','user','contact','lead',''):
            continue
        if (not message.get('id') or message.get('out_pending') or message.get('unread_media')
                or message.get('attachments')
                or str(message.get('delivery_status') or '').lower() in ('failed','error','pending','queued','sending','cancelled','canceled')):
            return None
        body = str(message.get('body') or message.get('text') or '')
        if query.fullmatch(body):
            return dict(message_id=message['id'], quote=body, source='client_arrival_query_unverified',
                        contact_message_ids=list(reversed(contacts)), appointment_verified=False,
                        crm_created=False, call_executed=False)
        parsed = contact_address.parse(body)
        address_prefix = bool(parsed and re.fullmatch(r'\s*(?:(?:мой\s+)?адрес(?:\s+для\s+выезда)?\s*:?\s*)?', body[:parsed.start], re.I))
        address_only = bool(parsed and parsed.street and parsed.house and address_prefix and '?' not in body
            and (not body[parsed.end:].strip(' ,.;!') or only_parts(body[parsed.end:])))
        if parsed and not address_only:
            # A literal untyped location note may accompany the address;
            # other trailing prose may introduce a different requested job.
            address_only = bool(parsed.street and parsed.house and address_prefix and '?' not in body and any(
                n.get('kind') == 'literal_address_addition' and n.get('message_id') == message['id']
                and body[parsed.end:].strip(' ,.;!').casefold() == n['quote'].casefold()
                for n in facts.get('address_notes', [])))
        phone_only = bool(re.fullmatch(r'[+\d\s()-]+', body) and len(contact_phone.find_all(body)) == 1)
        # A bare split contact fragment cannot establish a complete phone;
        # it also does not replace the preceding followup with a new job.
        contact_fragment = bool(re.fullmatch(r'\+?\s*\d(?:[\d\s()-]{0,25})', body)
                                and 1 <= len(re.sub(r'\D', '', body)) <= 11)
        if address_only or phone_only or contact_fragment or ('?' not in body and only_parts(body)):
            contacts.append(message['id'])
            continue
        return None  # A different question/task is not a continuation receipt.
    return None


def _reported_prior_conversation(messages):
    """A client report requires lookup, never proves a call's content/order."""
    recent = [m for m in messages if m.get('direction') == 'in'][-6:]
    report = re.compile(
        r'\bмы\s+(?:с\s*вами\s+)?договаривались\b|'
        r'\bя\s+(?:с\s*вами\s+(?:уже\s+)?(?:по)?говорил[аи]?|'
        r'вам\s+(?:уже\s+)?(?:по)?звонил[аи]?)\b|'
        r'\b(?:она|он)\s*[,—-]?\s*вам\s+(?:уже\s+)?(?:по)?звонил[аи]?\b|'
        r'\bмы\s+(?:с\s*вами\s+)?(?:уже\s+)?созванивались\b|'
        r'\b(?:перезвонил|позвонил)\s+(?:мне\s+|нам\s+)?мастер\b|'
        r'\bмастер\s+(?:мне\s+|нам\s+)?(?:перезвонил|позвонил)\b|'
        r'\b(?:жду|жд[её]м)\s+вас\s+(?:сегодня\s+|завтра\s+)?(?:к|в)\s*\d{1,2}(?::\d{2})?', re.IGNORECASE)
    new_request = re.compile(
        r'\b(?:новая\s+заявка|новую\s+заявку|новый\s+заказ|'
        r'теперь\s+(?:нужно|хочу)|по\s+другому\s+вопросу)\b', re.IGNORECASE)
    for index in range(len(recent) - 1, -1, -1):
        message = recent[index]
        agreement = re.search(r'\bдоговаривались\b', message['body'], re.I)
        timed_agreement = bool(agreement and not re.search(r'\bне\s*$', message['body'][:agreement.start()], re.I)
                               and re.search(r'\b(?:в|на|к)\s*\d{1,2}[.:]\d{2}|подъезжа|приед|уже\s+дома', message['body'], re.I))
        identity_question = bool(re.search(r'\bя\s+не\s+вам\s+(?:уже\s+)?(?:по)?звонил[аи]?\s*\?', message['body'], re.I))
        if report.search(message['body']) or timed_agreement or identity_question:
            if any(new_request.search(m['body']) for m in recent[index:]):
                return None
            return dict(message_id=message.get('id', ''), quote=message['body'],
                        source='client_identity_question_unverified' if identity_question else 'client_report_unverified')
    if recent and re.fullmatch(r'\s*(?:я\s+)?освободил(?:ся|ась)[,.!\s]*', recent[-1]['body'], re.I):
        previous_turn = []
        for message in reversed(messages[:-1]):
            if message.get('direction') == 'in':
                break
            if message.get('direction') == 'out':
                previous_turn.append(message)
        previous_body = '\n'.join(m.get('body', '') for m in previous_turn)
        if (re.search(r'звоню|наб[ие]рал|(?:по)?звонил', previous_body, re.I)
                and re.search(r'не\s+(?:отв\w*|отвеч\w*)', previous_body, re.I)):
            return dict(message_id=recent[-1].get('id', ''), quote=recent[-1]['body'],
                        reported_attempt_message_id=previous_turn[-1].get('id', ''), source='client_report_unverified')
    return None

KRASNOYARSK_PLUMBING_RULE = "BTMNC-20261017-KRASNOYARSK-PLUMBING"


def crm_branch_route(known, service):
    """Work-specific CRM branch, distinct from the client's physical city.

    IDs/labels verified in the live MNC create form on 17 October. Approval
    cases stay with an operator; a customer's claimed refusal never unlocks
    the fallback or automatic creation.
    """
    city = str(known.get("city") or "").strip().casefold()
    if str(known.get("channel") or "").lower().startswith("max") or known.get("direction") != "mnc" or city not in (
        "красноярск", "красноярск сантехника", "красноярск (сантехника)"
    ):
        return None
    plumbing = {"plumbing-tap", "towel", "sink-hole", "sink", "bath", "toilet",
                "pipes-riser", "pipes", "plumbing-small", "drain", "mnc-connect"}
    items = service.get("items", [])
    if not any(item.get("id") in plumbing for item in items):
        return None
    return {
        "rule_id": KRASNOYARSK_PLUMBING_RULE,
        "physical_city": "Красноярск",
        "city_id": "709", "city_text": "Красноярск сантехника",
        "work_type": "Сантехника",
        "mixed_work": any(item.get("id") not in plumbing for item in items),
        "lead_hours": [1, 1.5], "client_convenient_time_allowed": True,
        "approval_operator_required": True,
        "approval_steps": [
            {"city_id": "709", "city_text": "Красноярск сантехника", "requires": "approval_required"},
            {"city_id": "3", "city_text": "Красноярск", "requires": "verified_refusal_from_709"},
        ],
        "approval_instruction": "Сначала предложить филиалу «Красноярск сантехника». После подтверждённого отказа этого филиала обязательно направить на согласование филиалу «Красноярск». Молчание и слова клиента не подтверждают отказ филиала.",
    }
_ESCALATION = re.compile(
    r"полици|инстанци|прокуратур|претензи|жалоб|верн.*деньг|гаранти|мастер.*не прие|отмен|перенес|перенос|где мастер",
    re.IGNORECASE,
)


def _escalation_text(text):
    # This exact payment option is generated inside an Avito task form. It is
    # not a complaint about a previous repair. Keep every other sentence,
    # including a real warranty claim appended to the same form.
    normalized = re.sub(r"\s+", " ", text)
    if "Задача составлена по ответам клиента в анкете" in normalized and "Как бы хотели оплатить:" in normalized:
        cleaned = normalized.replace('Онлайн с «Защитой сделки» и бесплатной гарантией', '')
    else:
        # The retailer moving furniture delivery is not our appointment moving.
        # Remove only the named external delivery clause; retain any real complaint.
        cleaned = re.sub(r'\b(?:срок\w*\s+)?доставк\w*\s+(?:шкаф\w*|мебел\w*|комод\w*|кроват\w*)\s+перенес\w*\b', '', text, flags=re.I)
    # An explicit exclusion of electrical relocation is a work boundary. Keep
    # every appointment/cancellation/complaint token outside that exact phrase.
    electrical = r'(?:проводк|кабел|розетк|выключател)\w*'
    patterns = (
        rf'\bбез\s+перенос(?:а|ов)\s+{electrical}',
        rf'\bне\s+(?:нужно|надо|требуется)\s+переносить\s+{electrical}',
        rf'\bперенос(?:ить)?\s+{electrical}[^,.!?;\n]{{0,60}}\bне\s+(?:нужен|нужно|надо|требуется)\b',
        # The paired operation supplies the construction scope even when the
        # client omits "wiring". Do not span a visit/object or a second clause.
        r'\bперенос\s+и\s+штробление\s+не\s+(?:нужны|требуются)\b',
        r'\bне\s+(?:нужны|требуются)\s+перенос\s+и\s+штробление\b',
        r'\bбез\s+переноса\s+и\s+штробления\b',
    )
    for pattern in patterns:
        cleaned = re.sub(pattern, lambda match: re.sub(r'\bперенос(?:ить|а|ов)?\b',
            'изменение расположения', match.group(0), flags=re.I), cleaned, flags=re.I)
    return cleaned


def _decision_maker_absent(messages):
    absent = False
    for message in messages:
        if message.get("direction") != "in":
            continue
        text = message["body"]
        if re.search(r"\bя\s+(?:не\s+смогу\s+присутствовать|не\s+буду\s+(?:на\s+месте|на\s+адресе)|в\s+другом\s+городе)\b", text, re.IGNORECASE):
            absent = True
        elif (re.search(r'\bя\s+не\s+живу\s+там\b', text, re.I)
              and re.search(r'\b(?:показ\w*|встрет\w*|принять)\b[^.!?\n]{0,35}\bне\s+(?:получится|смогу)\b', text, re.I)):
            absent = True  # Explicit inability, not an inference from a different residence alone.
        elif re.search(r"(?:^|[.!?]\s*)я\s+(?:смогу\s+присутствовать|буду\s+(?:на\s+месте|на\s+адресе))[.!\s]*$", text.strip(), re.IGNORECASE):
            absent = False
    return absent


def _equipment_return_request(incoming):
    text = '\n'.join(body for body in incoming if not re.search(r'(?:^|\n)\s*Сделка состоялась', body, re.IGNORECASE))
    if re.search(r'\bзабрать\s+сво[йюеё]\s+(?:принтер|ноутбук|телевизор|компьютер|техник)\w*', text, re.IGNORECASE):
        return True
    device = r'(?:телевизор|ноутбук|принтер|компьютер|техник)\w*'
    return_verb = r'(?:привез[её]те|верн[её]те|возвратите)'
    return bool(re.search(r'\bкогда\b[^.!?\n]{0,50}(?:' + device + r'[^.!?\n]{0,25}' + return_verb
                         + r'|' + return_verb + r'[^.!?\n]{0,25}' + device + r')', text, re.IGNORECASE))


def _service_readiness_request(messages):
    """A customer's readiness enquiry needs the existing card, not new intake.

    It proves only what the client asks/reports. It does not establish receipt,
    repair completion, a deadline, or responsibility for another workshop.
    """
    device = r'(?:принтер|мфу|ноутбук|телевизор|компьютер|техник|холодильник|машин)\w*'
    for index in range(len(messages)-1, -1, -1):
        message = messages[index]
        if message.get('direction') != 'in':
            continue
        body = message.get('body', '')
        if (re.search(r'(?:^|\n)\s*Сделка состоялась', body, re.I)
                or re.search(r'\b(?:если|допустим|предположим)\b|'
                             r'\b(?:сдам|отдам|закажу|привезу|куплю)\b|'
                             r'\b(?:другой|другого|другую)\s+(?:сервис|мастер|мастерск)\w*', body, re.I)):
            continue
        progress = re.search(r'\b(?:есть|появилось)\s+понимание\s+по\s+срокам\s+ремонта\b[^.!?\n]{0,45}\b' + device, body, re.I)
        enquiry = progress or re.search(r'\bкогда\s+(?:будет|будут)\s+готов\w*\b[^.!?\n]{0,75}\b' + device, body, re.I)
        if not enquiry:
            continue
        own_device = re.search(r'\b(?:мой|моя|мо[её]|мои|наш|наша|наше|наши)\b[^.!?\n]{0,25}\b' + device, body, re.I)
        handed = next((m for m in messages[:index+1] if m.get('direction') == 'in'
                       and not re.search(r'\b(?:если|допустим|предположим|не)\b|'
                                         r'\bдруг\w*\s+(?:сервис|мастер|мастерск)\w*', m.get('body',''), re.I)
                       and re.search(r'\b(?:сдал[аи]?|отдал[аи]?|передал[аи]?|прив[её]з[лаи]*)\b[^.!?\n]{0,45}\b(?:вам|у\s+вас|вашему\s+мастеру)\b|'
                                     r'\b(?:вам|у\s+вас|вашему\s+мастеру)\b[^.!?\n]{0,45}\b(?:сдал[аи]?|отдал[аи]?|передал[аи]?|прив[её]з[лаи]*)\b', m.get('body',''), re.I)), None)
        if not (own_device or handed or progress):
            continue
        return dict(message_id=message.get('id',''), quote=body[:500],
                    source='client_report_unverified', kind='equipment_readiness_enquiry',
                    crm_receipt_confirmed=False, repair_completion_confirmed=False)
    return None


def _prospective_warranty_question(messages):
    """An isolated future-terms question does not establish prior service."""
    incoming = [m.get('body', '') for m in messages if m.get('direction') == 'in']
    return bool(incoming and re.fullmatch(
        r'\s*(?:а\s+)?гарантия\s+(?:имеется|есть|будет)\s+после\s+ремонта\s*\?\s*', incoming[-1], re.I)
        and not _reported_service_return(incoming[:-1])
        and not _staff_booking_claim(messages))


def _reported_service_return(incoming):
    # A pasted Avito review describes somebody else's transaction. Keep it
    # available for the pricing/trust handoff, without attributing its visit
    # or payment to this customer.
    text = "\n".join(body for body in incoming if not re.search(r'(?:^|\n)\s*Сделка состоялась', body, re.IGNORECASE))
    if _equipment_return_request(incoming):
        return True
    if re.search(r'\bуслуг\w*\s+(?:мне\s+)?не\s+оказан\w*|\b(?:работу|ремонт)\s+не\s+(?:делал[аи]?|сделал[аи]?|выполнил[аи]?)\b|\bнеустойк\w*', text, re.IGNORECASE):
        return True
    if re.search(r"\bмастер\b.{0,40}\bвернуться\b|\bверните\b.{0,20}\bмастера\b", text, re.IGNORECASE):
        return True
    if re.search(r'\bмастер\b.{0,60}(?:ничего\s+не\s+сделал|не\s+помог)', text, re.IGNORECASE):
        return True
    own_repair = re.search(r"\b(?<!не )(?:ремонтировал[аи]?|чинил[аи]?)\s+у\s+вас\b|\bвы\b.{0,35}\b(?:ремонтировали|починили|чинили)\b", text, re.IGNORECASE)
    failure = re.search(r"(?:снова|опять|до\s+сих\s+пор).{0,45}(?:не\s+(?:работ|мороз|показыв)|пропал|отключ|теч|слом)", text, re.IGNORECASE)
    paid_visit = re.search(r"\b(?:я\s+)?(?:заплатил[аи]?|оплатил[аи]?|отдал[аи]?)\b", text, re.IGNORECASE)
    diagnostic_dispute = re.search(r"за\s+что.{0,30}(?:не\s*понятно|заплат)|в\s+объявлении.{0,80}бесплат|ремонту\s+не\s+подлежит", text, re.IGNORECASE)
    own_visit = re.search(r'\b(?:вы\s+)?(?:приезжали|приходили)\s+к\s+нам\b|\bвы\s+(?:уже\s+)?(?:приезжали|приходили)\b', text, re.IGNORECASE)
    parts_status = re.search(r'\b(?:нашли|наш[её]л|нашла)\b[^.!?\n]{0,35}(?:запчаст|деталь)|\b(?:запчаст|деталь)\w*[^.!?\n]{0,35}(?:нашли|наш[её]л|нашла)', text, re.IGNORECASE)
    return bool(own_repair and failure or paid_visit and diagnostic_dispute or own_visit and parts_status)


def _photo_submission_permission(body):
    """A question about sending a photo is neither an attachment nor a quote."""
    return bool(re.search(r'фото|фотограф|снимок', body, re.I)
                and re.search(r'\b(?:можно|могу|можем)\b[^.!?\n]{0,45}\b(?:отправить|прислать|скинуть)|'
                              r'\b(?:отправить|прислать|скинуть)\b[^.!?\n]{0,35}\bможно\b', body, re.I)
                and not re.search(r'сколько|какая\s+цен|во\s+сколько|что\s+стоит|'
                                  r'новая\s+заявка|по\s+другому\s+вопросу|'
                                  r'(?:теперь|ещ[её]|также)\s+(?:нуж\w*|надо|хочу)', body, re.I)
                and body.count('?') <= 1)


def _photo_upload_unblock(messages):
    """Bind a request for our reply to the client's pending photo upload."""
    current = assistant_prices.current_enquiry_messages(messages)
    anchor = None
    for message in current:
        if message.get('direction') != 'in' or message.get('sender_type', 'client') not in ('client', ''):
            continue
        body = str(message.get('body') or '')
        if message.get('attachments') or message.get('media_reviewed'):
            anchor = None
            continue
        if re.search(r'[«»“”"]|сказал|написал|цитат|если|цен[аыуе]|стоим|сколько', body, re.I):
            anchor = None
            continue
        photo = re.search(r'фото|фотограф|снимок', body, re.I)
        write = re.search(r'\bнапишите\s+мне\b|\bпока\s+вы\s+не\s+(?:напиш(?:ете|ите)|ответите)\b|\bответьте\b', body, re.I)
        send = re.search(r'\b(?:отправлю|отправить|прислать|пришлю|скинуть|скину)\b', body, re.I)
        if write and send and (photo or anchor):
            anchor = dict(message_id=message.get('id', ''), quote=body,
                          source='client_message', upload_received=False)
        elif body.strip():
            # Only the immediate short continuation can inherit the photo.
            anchor = None
    return anchor


def _photo_address_only(body, known, facts):
    """Ignore only an already parsed address/contact, never a named job."""
    text = str(body or '').casefold().replace('ё', 'е')
    address = facts.get('address') or {}
    street = str(address.get('street') or '').casefold().replace('ё', 'е')
    if not street or street not in text:
        return False
    for phone in reversed(contact_phone.find_all(text)):
        text = text[:phone.start] + ' ' + text[phone.end:]
    text = text.replace(street, ' ')
    city = str(known.get('city') or '').casefold().replace('ё', 'е')
    if city:
        text = re.sub(r'\b' + re.escape(city) + r'\b', ' ', text)
    text = re.sub(r'\b(?:улица|ул|дом|д|кв|квартира|подъезд|под|п|этаж|эт|корпус|корп|к|строение|стр|г)(?=\b|\d)', ' ', text)
    return bool(re.fullmatch(r'[\d\s.,:;+/()—-]*', text))


def photo_reply_progress(messages, known, facts):
    """Observed staff speech can answer a write-first request, not prove upload."""
    current = assistant_prices.current_enquiry_messages(messages)
    request = None
    response = None
    for position, message in enumerate(current):
        body = str(message.get('body') or '').strip()
        role = message.get('sender_type', 'client' if message.get('direction') == 'in' else 'operator')
        if message.get('direction') == 'out':
            if (request and role in ('operator', 'employee', 'human', 'staff', '') and body
                    and not message.get('out_pending')
                    and str(message.get('delivery_status') or message.get('delivery') or '').lower()
                    not in ('failed', 'error', 'pending', 'queued', 'sending', 'cancelled', 'canceled')
                    and not re.search(r'[«»“”"]|\b(?:сказал|написал|цитата)\b', body, re.I)):
                response = dict(message_id=message.get('id', ''), quote=body,
                                source='observed_delivered_staff_response')
            continue
        if message.get('direction') != 'in' or role not in ('client', ''):
            continue
        if message.get('attachments') or message.get('media_reviewed') or message.get('media_signature'):
            request = response = None
            continue
        anchor = _photo_upload_unblock(current[:position + 1])
        if anchor and anchor['message_id'] == message.get('id', ''):
            request, response = anchor, None  # A renewed client complaint needs an answer.
        elif body and not _photo_address_only(body, known, facts):
            request = response = None  # A new question/job is not silent photo coordination.
    if request and response:
        return dict(request=request, response=response, status='reply_observed_photo_pending',
                    upload_received=False, upload_permission_verified=False,
                    meaning='Сотрудник уже ответил на просьбу написать. Фото ещё не получено; '
                            'техническая возможность его отправки не проверена. '
                            'Новый адрес не возобновляет просьбу о первом ответе.')
    return None


def photo_first_reply_pending_claim(text):
    """Only the stale first-reply prerequisite, not every awaited answer."""
    for clause in re.split(r'[,;.!?\n]+', str(text or '')):
        if re.search(r'не\s+(?:жд[её]т|ожидает)|уже\s+(?:ответил|получил)|больше\s+не|не\s+требуется', clause, re.I):
            continue
        if (re.search(r'фото|отправк|отправить|отправит', clause, re.I)
                and re.search(r'(?:ожидает|жд[её]т|после|пока|без)[^.!?]{0,55}\bответ\w*', clause, re.I)):
            return True
    return False


def _remote_service_question(body):
    """A work-method question, including the understandable single-н typo."""
    if re.search(r'[«»“”"]|\b(?:если|сказал|написал|спросил|спрашивал|цитата)\b', str(body or ''), re.I):
        return False
    for clause in re.split(r'[,;.!\n]+', str(body or '')):
        if (re.search(r'[«»“”"]|\b(?:если|сказал|написал|спрашивал|цитата)\b', clause, re.I)
                or re.search(r'\bне\s+(?:нужно|надо|хочу)|удал[её]н{1,2}о\s+не\s+нуж', clause, re.I)):
            continue
        if (re.search(r'\b(?:удал[её]н{1,2}о|дистанционно)\b', clause, re.I)
                and (re.search(r'\b(?:можно|можете|возможно)\b', clause, re.I)
                     or '?' in clause and re.search(r'\b(?:вы\s+)?работа(?:ете|ешь)', clause, re.I)
                     or '?' in clause and re.search(r'\bили\s+с\s+выездом\b', clause, re.I))
                and not re.search(r'удал[её]н{1,2}о\s+(?:приложение|файл|програм|фото)', clause, re.I)):
            return True
    return False


def _logistics_defer_anchor(messages):
    """Preserve the client's logistics pause only through neutral continuations."""
    anchor = None
    for message in messages or []:
        if (message.get('direction') != 'in'
                or message.get('sender_type') in ('operator', 'bot', 'system', 'avito')):
            continue
        body = re.sub(r'«[^»]*»|"[^"\n]*"', '', message.get('body', ''))
        if re.search(r'^\s*\[Системное сообщение\]', body, re.I):
            continue
        if (re.search(r'\bвернусь\b[^.!?\n]{0,50}\bкогда\b[^.!?\n]{0,35}\bнайду\b', body, re.I)
                and re.search(r'грузчик|перевозчик|транспорт', body, re.I)
                and not re.search(r'не\s+вернусь|\?|сказал|написал|цитат', body, re.I)):
            anchor = message
            continue
        neutral = re.fullmatch(r'\s*(?:(?:хорошо|отлично|спасибо|благодарю|ок|понял[аи]?|договорились)[,! .]*)+', body, re.I)
        future_coordination = re.fullmatch(r'\s*надо\s+будет\s+по\s+времени\s+(?:правильно\s+)?сориентироваться[.!\s]*', body, re.I)
        if not (neutral or future_coordination or _photo_submission_permission(body)):
            anchor = None
    return anchor


def _client_deferred(incoming, messages=None):
    """Pause intake only on the client's current intent, never forever."""
    if not incoming:
        return False
    def explicit(body):
        # Match only the client's positive assertion. Keep the original
        # messages intact for evidence; quoted or negated future contact
        # cannot turn a current enquiry into a pause.
        body = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', body)
        body = re.sub(r'\bне\s+(?:напишу|напишем|отпишусь|отпишемся|отпишу|свяжусь|свяжемся|'
                      r'спишемся|позвоню|позвоним|наберу|перезвоню|отвечу|пришлю|отправлю|скину|вышлю)\b',
                      ' ', body, flags=re.I)
        conditional_confirmation = (re.search(r'\b(?:скажу|подтвержу|сообщу)\b', body, re.I)
                                    and re.search(r'\bточно\b|окончательно', body, re.I)
                                    and re.search(r'\bпока\b|\b(?:может|найду|попробую)\b', body, re.I))
        if (conditional_confirmation
                and not re.search(r'сколько|стоим|цен[аыуе]|подскаж|когда\s+(?:приед|подъед)', body, re.I)):
            return True  # A proposed hour awaits a later explicit confirmation.
        # Asking whether one may return later after declining today's budget
        # is a pause, not another request to quote or collect contact details.
        if (re.search(r'пока.{0,25}не\s+(?:потяну|могу\s+оплатить)|пока\s+дорого', body, re.IGNORECASE)
                and re.search(r'позже.{0,30}(?:обратиться|напишу|свяжусь)', body, re.IGNORECASE)):
            return True
        if (re.search(r'пока\s+не\s+(?:заселил|переехал)|заранее\s+ищу', body, re.IGNORECASE)
                and re.search(r'скоро.{0,25}воспользуюсь|в\s+будущем|позже', body, re.IGNORECASE)
                and not re.search(r'\?|нужно\s+(?:сейчас|сегодня)', body, re.IGNORECASE)):
            return True
        later_contact = re.search(r'\b(?:напишу|отпишусь|свяжусь|спишемся|позвоню|наберу|перезвоню|отвечу)\b', body, re.I)
        past_price_interest = re.search(r'\bпросто\b[^.!?\n]{0,40}\bузнать\s+цен', body, re.I)
        if (later_contact and past_price_interest and '?' not in body
                and not re.search(r'подскаж|скажите|озвуч|какая\s+цена|сколько', body, re.I)):
            return True
        if re.search(r"\?|сколько|стоим|цен[аыуе]|подскажите", body, re.IGNORECASE):
            return False  # answer the current question before waiting
        # A whole first-person conditional decision is a pause, not consent.
        # Do not match quoted speech, negation, another person's instruction
        # or a message that also requests current work.
        if re.fullmatch(
                r'\s*(?:(?:спасибо|хорошо|благодарю)[,.!\s]+)*'
                r'(?:если|когда|как)\s+(?:(?:я|мы)\s+)?'
                r'(?:надумаю|надумаем|решусь|решимся|определюсь|определимся)'
                r'\s*[,—-]?\s*(?:то\s+)?(?:(?:я|мы|сам|сама|сами)\s+){0,2}'
                r'(?:вам\s+)?(?:напишу|напишем|отпишусь|отпишемся|свяжусь|свяжемся|позвоню|позвоним)'
                r'(?:\s+вам)?[.!\s)]*', body, re.I):
            return True
        if (re.search(r'\b(?:пришлю|отправлю|скину|вышлю)\b', body, re.I)
                and re.search(r'фото|сфот|фотограф|снимк', body, re.I)
                and re.search(r'позже|потом|вечером|утром|завтра|когда|как\s+сфот|как\s+фотограф', body, re.I)
                and not re.search(r'запиш|позвоните|приезж|приед|подъед|нужно\s+(?:сейчас|сегодня)', body, re.I)):
            return True
        if (re.search(r'\bвернусь\b[^.!?\n]{0,50}\bкогда\b[^.!?\n]{0,35}\bнайду\b', body, re.I)
                and re.search(r'грузчик|перевозчик|транспорт', body, re.I)):
            return True  # The next step depends on the client's own logistics.
        if later_contact and re.search(r'\bпока\s+не\s+(?:нужно|надо)\b|\bесли\s+что\b', body, re.I):
            return True
        if later_contact and re.search(r'\bкогда\s+(?:я\s+)?(?:смогу|освобожусь)\b|'
                                       r'\b(?:уточню|узнаю|согласую)\b[^.!?\n]{0,60}'
                                       r'(?:врем\w*|мам\w*|пап\w*|руководител\w*|заказчик\w*)', body, re.I):
            return True
        if re.search(r'если[^.!?\n]{0,35}не\s+получится[^.!?\n]{0,25}(?:наберу|напишу)|'
                     r'(?:наберу|напишу)[^.!?\n]{0,25}если[^.!?\n]{0,35}не\s+получится|'
                     r'я\s+вас\s+(?:завтра|сегодня|позже)\s+с\s*ориентирую', body, re.I):
            return True
        if later_contact and re.search(r'\bкогда\b[^.!?\n]{0,40}\bпланир\w*[^.!?\n]{0,20}\bприехать\b|'
                                       r'\b(?:мама|папа|муж|жена|заказчик)\b[^.!?\n]{0,25}\bпросн[её]тся\b', body, re.I):
            return True
        future = re.search(r"позже|потом|на\s+днях|завтра|вечер(?:ом|у)|утром|приеду|понадоб|возможн|если\s+(?:нужно|понадоб)|(?:начал|конц).{0,15}недел|как.{0,20}решу|(?:прид[её]т|получу|доставят|привезут)|(?:муж|жена|заказчик).{0,20}ответит|(?:в|к)\s+(?:понедельник\w*|вторник\w*|сред[уе]|четверг\w*|пятниц[еу]|суббот[еу]|воскресень[еу]|выходны[ем])", body, re.IGNORECASE)
        contact = re.search(r"\b(?:напишу|отпишусь|отпишу|свяжусь|спишемся|позвоню|перезвоню|отвечу)\b|\b(?:пришлю|отправлю)\b[^.!?\n]{0,25}\b(?:фото|видео)\b", body, re.IGNORECASE)
        bare = re.fullmatch(r"\s*(?:я\s+)?(?:напишу|отпишусь)(?:\s+вам)?[.!\s]*", body, re.IGNORECASE)
        thinking = re.fullmatch(r"\s*(?:(?:я|мы|хорошо|спасибо|благодарю)[,!\s]+)*(?:(?:по|об)дума(?:ю|ем)|надо\s+подумать)(?:[,!\s]+(?:спасибо|благодарю))?[.!\s)]*", body, re.IGNORECASE)
        self_call = re.fullmatch(r'\s*(?:я\s+)?сам[аи]?\s+(?:вам\s+)?(?:по|через)\s+авито\s+позвоню[.!\s]*', body, re.I)
        return bool(thinking or bare or self_call or (contact and future) or re.search(r"\bспишемся[.!\s)]*$", body, re.IGNORECASE))
    last = incoming[-1]
    if _logistics_defer_anchor(messages):
        return True
    if explicit(last):
        return True
    if (len(incoming) > 1 and re.search(r'\bнет(?:у)?\s+(?:столько|денег)|не\s+могу\s+оплатить', last, re.I)
            and re.fullmatch(r'\s*(?:можно|давайте|тогда|лучше)(?:\s+тогда)?\s+после\s+\d{1,2}\s+числа[.?!\s]*', incoming[-2], re.I)):
        return True
    if (len(incoming)>1 and explicit(incoming[-2])
            and re.fullmatch(r'\s*точнее\s+(?:уже\s+)?(?:сегодня|завтра)[.!\s]*', last, re.I)):
        return True
    if (len(incoming)>1 and explicit(incoming[-2])
            and re.search(r'позвоню|перезвоню|напишу|отпишусь', incoming[-2], re.I)
            and re.fullmatch(r'\s*(?:в|к|после)\s*\d{1,2}(?::\d{2})?[.!\s]*',last,re.I)):
        previous_out=next((m['body'] for m in reversed(messages or []) if m.get('direction')=='out'),'')
        if not re.search(r'приеду|подъеду|визит|приезд',previous_out,re.I):
            return True  # The clock refines a callback, not a visit.
    # A short follow-up such as 'Позже' preserves the immediately preceding
    # client deferral. A new question, photo or concrete request releases it.
    return bool(len(incoming) > 1 and explicit(incoming[-2]) and re.fullmatch(
        r"\s*(?:позже|потом|хорошо|отлично|спасибо|благодарю|ок|договорились|понял[аи]?)[.!\s]*", last, re.IGNORECASE))


def _callback_phone_usable(messages, facts):
    """A later neutral turn cannot reinstate an explicitly retracted number."""
    if not facts.get('contact_phone_to_use') or facts.get('phone_needs_confirmation'):
        return False
    phone_retracted = False
    for message in messages:
        if (message.get('direction') != 'in'
                or message.get('sender_type') in ('operator', 'employee', 'human', 'bot', 'assistant', 'system', 'avito')):
            continue
        body = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', message.get('body', ''))
        if contact_phone.find_all(body):
            phone_retracted = False
        elif (re.search(r'номер|телефон', body, re.I)
              and re.search(r'неверн|ошиб|перепутал', body, re.I)):
            phone_retracted = True
    return not phone_retracted


def _recontact_callback_preparation(messages, facts, furniture_wait=None):
    """Owner-approved preparation is separate from the client's wait action.

    This is an operator review instruction, not a completed qualification or
    a CRM grant. Actual conditions, map, duplicates and the prepared snapshot
    still need their existing checks. Never fabricate an agreed visit hour.
    """
    if not _callback_phone_usable(messages, facts) or facts.get('address_needs_confirmation'):
        return None
    address = facts.get('address') or {}
    if not address.get('building') or not (address.get('street') or address.get('settlement')):
        return None
    incoming = [m for m in messages if m.get('direction') == 'in'][-2:]
    text = '\n'.join(m.get('body', '') for m in incoming)
    logistics = _logistics_defer_anchor(messages)
    if not (logistics or furniture_wait) and (not re.search(r'\b(?:напишу|отпишусь|позвоню|перезвоню|наберу)\b', text, re.I)
            or not re.search(r'\b(?:сегодня|завтра|послезавтра)\b|\b(?:после|в|к)\s*\d{1,2}(?!\d)', text, re.I)
            or re.search(r'привезут|доставят|получу|прид[её]т|если\s+что|не\s+понадоб|пока\s+не\s+(?:надо|нужно)', text, re.I)):
        return None
    return dict(mode='callback', status='operator_review', ready=False,
                time_policy='nearest_branch_normative', visit_time_confirmed=False,
                can_create_automatically=False, requires_full_qualification_check=True,
                intent_message_ids=list(dict.fromkeys(([logistics.get('id', '')] if logistics else [])
                                                      + ((furniture_wait or {}).get('evidence_ids', []))
                                                      + [m.get('id', '') for m in incoming])),
                rule_ids=['OWNER-RECONTACT-CALLBACK-20261019', 'DOC-L1159'],
                reason='Готовить на прозвон с ближайшим временем по нормативу филиала; '
                       'время визита не подтверждено. Проверить остальные условия, карту и дубли с оператором.')


def _visit_counterproposal(messages):
    """A replacement hour answers the staff's proposed visit, not intake.

    The evidence preserves a requested slot; it confirms neither availability
    nor a CRM booking. Numbers in questions about quantity/price are excluded.
    """
    if not messages or messages[-1].get('direction') != 'in':
        return None
    hour = r'(?:[01]?\d|2[0-3])(?:[.:][0-5]\d)?'
    choice = re.fullmatch(
        r'\s*(?:а\s+)?(?:можно|давайте|лучше)(?:\s+(?:в|к|на))?\s*(' + hour + r')'
        r'(?:\s*час(?:а|ов)?)?[.?!\s]*', messages[-1]['body'], re.I)
    if not choice:
        return None
    previous = next((m for m in reversed(messages[:-1]) if m.get('direction') == 'out'), None)
    relative_visit = bool(previous and re.search(
        r'\bчерез\s+(?:час(?:\s*[-–]?\s*полтора)?|полтора\s+часа|\d+(?:[.,]\d+)?\s*[-–]\s*\d+(?:[.,]\d+)?\s*час\w*)\b',
        previous['body'], re.I)
        and re.search(r'буду|приед|подъед|удобно|подойд[её]т', previous['body'], re.I)
        and not re.search(r'\bне\s*(?:буду|приед|подъед|удобно|подойд[её]т)', previous['body'], re.I)
        and previous.get('delivery_status', '').lower() not in ('failed', 'error', 'pending', 'queued', 'sending', 'cancelled', 'canceled'))
    if (not previous or previous.get('out_pending')
            or not (relative_visit or re.search(r'\b(?:в|к|на)\s*' + hour + r'(?!\d)', previous['body'], re.I))
            or not (relative_visit or re.search(r'удобно|подойд[её]т|приед|подъед|визит|приезд', previous['body'], re.I))
            or re.search(r'позвон|созвон|перезвон|напиш|стоим|цен[аыуе]|руб|\bштук', previous['body'], re.I)):
        return None
    return dict(proposal_message_id=previous.get('id', ''), proposal_quote=previous['body'],
                requested_message_id=messages[-1].get('id', ''), requested_quote=messages[-1]['body'],
                requested_time=choice[1], visit_confirmed=False, crm_write_confirmed=False)


def _client_declined(last, previous_out):
    # Quoted refusals belong to the quoted speaker, not this client. This
    # local matching view never replaces the original source or evidence.
    last = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', last)
    if contact_facts.explicit_help_withdrawal(last):
        return True
    terminal_clause = next((s.strip() for s in reversed(re.split(r'[.!?\n]+', last)) if s.strip()), '')
    if re.search(r'(?:^|[,;])\s*(?:но\s+)?(?:ваша\s+)?(?:помощь|услуга)\s+(?:мне\s+)?(?:уже\s+)?не\s+нужна(?:[,\s]+отказываюсь)?(?:[,\s]+спасибо)?$', terminal_clause, re.I):
        return True  # A final explicit withdrawal outranks an earlier question.
    if re.search(r'\bпередумал[аи]?\b[^.!?\n]{0,35}\b(?:вс[её]\s+же|теперь)\s+'
                 r'(?:нужен\s+мастер|нужна\s+помощь)[.!?\s]*$', last, re.I):
        return False  # An explicit final reactivation reverses the earlier plan.
    if ('?' not in last
            and re.search(r'\b(?:уже\s+)?наш(?:[её]л|ла|ли)\s+(?:другого\s+)?мастера\b',last,re.I)
            and not re.search(r'\bне\s+наш(?:[её]л|ла|ли)\b',last,re.I)
            and re.search(r'если[^.!?\n]{0,55}не\s+договорим\w*[^.!?\n]{0,45}(?:свяжусь|напишу|обращусь)',last,re.I)):
        return True  # The price condition concerns the other provider.
    if ('?' not in last and re.search(r'рассчитывал\w*\s+на\s*\d+',last,re.I)
            and re.search(r'прошу\s+извинить|за\s+беспокойство',last,re.I)
            and not re.search(r'\bно\b|готов\w*|соглас\w*|помогите|нужна\s+помощь|вс[её]\s+равно',last,re.I)):
        return True
    if re.fullmatch(r'\s*(?:спасибо[,!\s]*(?:но\s+)?)?(?:ваша\s+)?услуга\s+уже\s+не\s+нужна[.!\s]*', last, re.I):
        return True
    if (not re.search(r'\?|не\s+едет|с\s+вашим|с\s*вами', last, re.I)
            and re.search(r'извините|за\s+беспокойство', last, re.I)
            and re.search(r'объявился\s+мастер\b[^.!?\n]{0,70}договаривал', last, re.I)
            and re.search(r'он\s+уже\s+едет', last, re.I)):
        return True
    prerequisite_question = (re.search(r'инструкци|схем|материал|комплектующ|интернет|кабел|картридж|детал', previous_out, re.I)
                             and re.search(r'есть|имеет|налич|провед|куплен|готов', previous_out, re.I))
    if '?' not in last:
        closing_clause = next((s.strip() for s in reversed(re.split(r'[.!\n]+', last)) if s.strip()), '')
        if (re.fullmatch(r'(?:(?:понятно|тогда|спасибо|благодарю)[,!\s]+)*(?:не\s*надо|не\s*нужно|нет[,!\s]+тогда)(?:[,!\s]+(?:спасибо|благодарю))?', closing_clause, re.I)
                and (not prerequisite_question or re.search(r'не\s*(?:надо|нужно)',closing_clause,re.I))):
            return True
    if not prerequisite_question and re.fullmatch(r'\s*(?:спасибо|благодарю)[,!\s]+нет[.!\s]*', last, re.I):
        return True
    if re.fullmatch(r'\s*дорого[,!\s]+(?:спасибо|благодарю)[.!\s]*', last, re.I):
        return True
    if ('?' not in last and re.search(r'\bдорого\b|не\s+по\s+карману',last,re.I)
            and not re.search(r'\bне\s+(?:(?:так|очень)\s+)?дорого\b',last,re.I)
            and re.search(r'(?:спасибо|благодарю)[.!\s]*$',last,re.I)
            and not re.search(r'вс[её]\s+равно|готов\w*|соглас\w*|приезж|подскаж|скажите|сколько|почему|можете',last,re.I)):
        return True
    if (re.search(r'\b(?:мне\s+)?уже\s+(?:сделали|починили|настроили)\b', last, re.I)
            and re.search(r'\bне\s+(?:надо|нужно)\b', last, re.I)
            and not re.search(r'\?|\bно\b|не\s+работ|теперь\s+нужно|нужна\s+помощь', last, re.I)):
        return True
    if not re.search(r'\?|сколько|стоим|цен[аыуе]', last, re.I):
        if re.search(r'\bс\s+друг(?:им|ой)\b[^.!?\n]{0,25}догов[ао]рил|'
                     r'догов[ао]рил[^.!?\n]{0,25}\bс\s+друг(?:им|ой)\b', last, re.I):
            return True
        if (re.search(r'извините|за\s+беспокойство', last, re.I)
                and re.search(r'\bуже\s+договорил', last, re.I)
                and not re.search(r'с\s*вами|с\s+вашим', last, re.I)):
            return True
        if (re.fullmatch(r'\s*нашли[.!\s]*', last, re.I)
                and re.search(r'стен\w*[^.!?\n]{0,15}каки|каки[^.!?\n]{0,15}стен', previous_out, re.I)):
            return True
    if (re.search(r'\b(?:пока\s+)?не\s+актуально\b',last,re.I)
            and not re.search(r'\?|подскаж|скажите|сколько|какая\s+цен',last,re.I)):
        return True
    if (re.fullmatch(r'\s*нет[.!\s]*',last,re.I)
            and re.search(r'у\s+себя.{0,25}прин|прин.{0,25}у\s+себя',previous_out,re.I)):
        return True
    if (re.search(r'\bсам[аи]?\s+справлюсь\b|\b(?:вчера|сегодня|уже)\b[^.!?\n]{0,30}\bсправил(?:ся|ась)\b', last, re.I)
            and not re.search(r'\?|\bно\b|не\s+справ|не\s+работ|нужна\s+помощь|теперь\s+нужно|еще\s+нужно',last,re.I)):
        return True
    if re.fullmatch(r'\s*(?:пока\s+)?не\s+(?:надо|нужно)(?:\s+(?:тогда|уже|больше))?(?:[,!\s]+(?:спасибо|благодарю))?[.!\s]*',last,re.I):
        return True
    if (re.search(r'\bполучилось\s+сам(?:ому|ой|им)?\s+(?:настроить|подключить|починить|сделать|разобраться)\b',last,re.I)
            and not re.search(r'\?|\bно\b|не\s+работ|теперь\s+нужно|нужна\s+помощь|еще\s+нужно',last,re.I)):
        return True
    if not re.search(r'\?|\bно\b|\bесли\b|нужна\s+помощь|теперь\s+нужно', last, re.IGNORECASE):
        if (re.search(r'\bсам[а]?\s+(?:сделаю|починю|установлю|соберу)\b', last, re.IGNORECASE)
                and not any(re.search(r'\bсам[а]?\s+(?:сделаю|починю|установлю|соберу)\b', clause, re.I)
                            and re.search(r'\b(?:мне\s+кажется|наверно\w*|может|возможно|думаю)\b', clause, re.I)
                            for clause in re.split(r'[.!?\n]+', last))):
            return True
        if re.fullmatch(r'\s*(?:найду|наду|поищу)\s+другого(?:\s+(?:мастера|специалиста))?[.!\s]*', last, re.IGNORECASE):
            return True
        if (re.fullmatch(r'\s*(?:спасибо[,!\s]*нет|нет[,!\s]*спасибо)[.!\s]*', last, re.IGNORECASE)
                and re.search(r'помо[щш]ь.{0,25}(?:требуется|нужна)|нужна.{0,25}помо[щш]ь|(?:вам|вас).{0,25}помочь', previous_out, re.IGNORECASE)):
            return True
    if (re.search(r'\b(?:поищу|найду)\s+другого\s+(?:мастера|специалиста|исполнителя)\b', last, re.IGNORECASE)
            and re.search(r'не\s+(?:надо|нужно)|отказываюсь', last, re.IGNORECASE)):
        return True
    if (re.search(r'\b(?:я\s+)?уже\s+сам(?:а)?\s+(?:сделал[аи]?|починил[аи]?|установил[аи]?|разобрал[аи]?ся)\b', last, re.IGNORECASE)
            and not re.search(r'\?|\bно\b|не\s+работ|теперь\s+нужно|нужна\s+помощь|еще\s+нужно', last, re.IGNORECASE)):
        return True
    if '?' not in last:
        first = re.split(r'[\n.!?]', last.strip(), maxsplit=1)[0]
        if re.fullmatch(r'\s*(?:(?:нет|спасибо|благодарю|хорошо|тогда)[,!\s]*)*(?:уже\s+)?не\s+(?:нужно|надо)(?:\s+ничего)?(?:[,!\s]+(?:уже|спасибо|благодарю))?[,!\s]*', first, re.IGNORECASE):
            return True
        if not re.search(r'\bесли\b|\bне\s+обращусь\b', last, re.IGNORECASE) and re.search(r'\bобращусь\s+к\s+друг\w*\s+специалист\w*', last, re.IGNORECASE):
            return True
    if re.search(r"\?|сколько|стоим|цен[аыуе]", last, re.IGNORECASE):
        return False
    declines = re.finditer(r"уже не нужно|не актуально|передумал|уже починили|\bне\s+нуждаемся\b|(?:уже\s+)?наш(?:[её]л|ла|ли).{0,20}(?:мастера|электрика|сантехника)|(?:записал(?:ся|ась|ись)|договорил(?:ся|ась|ись)|наш[её]л|нашла|нашли).{0,35}друг\w*.{0,20}(?:мастер|матсер|специалист)", last, re.IGNORECASE)
    if any(not re.search(r'\bне\s*$', last[:match.start()], re.I) for match in declines):
        return True
    if re.fullmatch(r"\s*(?:спасибо[,!\s]*)?уже\s+наш(?:[её]л|ла|ли)[.!\s)]*", last, re.IGNORECASE):
        return bool(re.search(r"смогу\s+помочь|могу\s+сборку\s+сделать|давайте\s+(?:подъед|приед)|когда.{0,20}принять|по\s+объ[её]му\s+работ|(?:стоим|цен).{0,60}(?:сборк|разборк|на\s+месте)|(?:сборк|разборк).{0,60}(?:стоим|цен)", previous_out, re.IGNORECASE))
    if re.search(r"\bдругой\s+мастер\s+(?:сейчас\s+)?приедет\b", last, re.IGNORECASE) and not re.search(r"не\s+приедет|нужна\s+ваша\s+помощь", last, re.IGNORECASE):
        return True
    return bool(re.fullmatch(r"\s*от\s+вас\s+нет[.!\s]*", last, re.IGNORECASE) and re.search(r"(?:у\s+себя|принять|приеха|подъех)", previous_out, re.IGNORECASE))


def _staff_refusal_ack(messages, *, allow_generic=False):
    """An acknowledged staff refusal ends this exchange, not service policy."""
    if not messages:
        return None
    current = messages[-1]
    if (current.get('direction') != 'in'
            or str(current.get('sender_type') or '').casefold() not in ('', 'client', 'customer', 'contact', 'user', 'lead')
            or not re.fullmatch(r'\s*(?:(?:ок|хорошо|ясно|понятно|понял[аи]?(?:\s+вас)?|принято|'
                                r'(?:спасибо|благодарю)(?:\s+за\s+(?:информацию|ответ))?)'
                                r'[,.!()\s]*)+', current.get('body', ''), re.I)):
        return None
    turn = []
    for previous in reversed(messages[:-1]):
        if previous.get('direction') == 'in':
            break
        if previous.get('direction') != 'out':
            continue
        if (previous.get('out_pending')
                or str(previous.get('delivery_status') or previous.get('delivery') or '').casefold()
                in ('pending', 'queued', 'sending', 'failed', 'error', 'cancelled', 'canceled', 'dismissed')
                or str(previous.get('sender_type') or '').casefold()
                not in ('', 'operator', 'manager', 'admin', 'agent', 'staff', 'human', 'bot', 'assistant', 'automation')):
            return None
        turn.append(previous)
    turn.reverse()
    body = '\n'.join(m.get('body', '') for m in turn)
    organization = r'(?:организаци(?:ями|ей)|компани(?:ями|ей)|посредник(?:ами|ом)|юридическ(?:ими\s+лицами|им\s+лицом)|юр\.?\s*лицами)'
    organizations = organization + r'(?:\s*(?:,|и|или)\s*' + organization + r')*'
    business = re.fullmatch(r'\s*(?:здравствуйте[!,.\s]*)?(?:к\s+сожалению[,!.\s]*)?'
                        r'(?:(?:я|мы)\s+)?(?:не\s+работа(?:ю|ем)\s+с\s+' + organizations +
                        r'|с\s+' + organizations + r'\s+не\s+работа(?:ю|ем))[.!\s]*', body, re.I)
    generic = allow_generic and re.fullmatch(
        r'\s*(?:здравствуйте[!,.\s]*)?(?:к\s+сожалению[,!.\s]*)?(?:(?:я|мы)\s+)?'
        r'не\s+(?:смогу|могу|сможем|можем)\s+(?:вам\s+)?(?:тогда\s+)?помочь'
        r'(?:[,!.\s]+(?:извините|простите))?[.!\s]*', body, re.I)
    if not (business or generic):
        return None
    return dict(staff_message_ids=[m.get('id', '') for m in turn], staff_quote=body,
                client_message_id=current.get('id', ''), client_quote=current['body'],
                admission_rule=False, crm_closure_confirmed=False)


def _organization_refusal_ack(messages):
    """Compatibility helper limited to a staff's business-only refusal."""
    return _staff_refusal_ack(messages)


def _personal_access_document_request(messages):
    """Coordinate identity/access with an operator, not by inventing documents.

    This is an execution/data-disclosure boundary, not an extra ban on a
    repair or on companies. A customer's explicit withdrawal clears it.
    """
    current = None
    for message in assistant_prices.current_enquiry_messages(messages):
        if message.get('direction') != 'in' or message.get('sender_type', 'client') not in ('client', ''):
            continue
        body = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', message.get('body', ''))
        documents = r'паспортн\w*\s+данн\w*|данн\w*\s+(?:вашего\s+)?паспорт\w*|паспорт\s+мастер\w*'
        if re.search(r'(?:' + documents + r')\s+(?:больше\s+)?не\s+(?:нуж\w*|требу\w*)|'
                     r'не\s+(?:нуж\w*|требу\w*)[^.!?;\n]{0,15}(?:' + documents + r')', body, re.I):
            current = None
            continue
        literal = '\n'.join(clause for clause in re.split(r'[.!?;\n]+', body)
                            if not re.search(r'\bесли\b(?!\s+что\b)|допустим|в\s+объявлени|сосед\w*\s+(?:сказал|попросил)', clause, re.I))
        if re.search(documents, literal, re.I) and re.search(r'пропуск|допуск|для\s+входа', literal, re.I):
            current = dict(message_id=message.get('id', ''), source='client_message',
                           permission_to_disclose=False, access_confirmed=False)
    return current


def _conversation_closed(last, previous_out, previous_client=''):
    if (re.fullmatch(r'\s*(?:ок|хорошо|договорились|понял[аи]?)[.!\s]*', last, re.I)
            and re.search(r'напиш(?:ите|и)|свяжитесь|сообщите', previous_out, re.I)
            and re.search(r'\b(?:как|когда|после)\b[^.!?\n]{0,60}'
                          r'(?:будете|верн[её]тесь|приедете|забер[её]те)', previous_out, re.I)
            and not re.search(r'запис|заявк|заказ|приеду|подъеду|визит', previous_out, re.I)):
        return True
    if re.fullmatch(r'\s*(?:(?:понятно|ясно|хорошо|спасибо|благодарю)[,.!\s]*)*'
                    r'(?:до\s+свидания|до\s+свиданья|всего\s+доброго)[.!\s]*', last, re.I):
        return True
    if (re.fullmatch(r'\s*(?:ок|хорошо|договорились|понял[аи]?)[.!\s]*',last,re.I)
            and _client_declined(previous_client,'') and re.search(r'пишите|обращайтесь',previous_out,re.I)
            and not re.search(r'\?|\d|запис|приед|подъед|\bбуду\b',previous_out,re.I)):
        return True
    if re.fullmatch(r'\s*(?:ну[,!\s]*)?(?:тогда[,!\s]*)?ладно[,.!\s]*(?:спасибо|благодарю)[.!\s]*', last, re.I):
        return True
    if (re.fullmatch(r'\s*(?:ок|хорошо|понял[аи]?)[.!\s]*',last,re.I)
            and re.search(r'телефон|контакт',previous_client,re.I)
            and re.search(r'\b(?:в\s+)?шапк\w*\s+профил\w*\b',previous_out,re.I)
            and not re.search(r'\?|цен|стоим|устраив|запис|визит|когда',previous_out,re.I)):
        return True
    if (re.search(r'(?:спасибо|благодарю)\s+за\s+ответ[.!\s👍👌🙏🙂😊]*$', last, re.I)
            and re.search(r'не\s+работаю\s+с\s+подрядчик|не\s+смогу\s+(?:вам\s+)?помочь', previous_out, re.I)
            and not re.search(r'\?|подскаж|скажите|сколько|\bно\b|теперь\s+нужно', last, re.I)):
        return True
    if re.fullmatch(r'\s*(?:(?:спасибо|благодарю|извините)[,!\s]*)?(?:до\s*(?:встречи|завтра|свидания|свиданья)|всего\s+(?:доброго|хорошего))[.!\s]*', last, re.I):
        return True
    if re.fullmatch(r'\s*(?:(?:спасибо|благодарю)[,!\s]*)?спокойной\s+ночи[.!\s]*', last, re.IGNORECASE):
        return True
    if (last.strip() and not re.search(r'[\w?]', last)
            and re.fullmatch(r'\s*(?:вам\s+)?(?:спасибо|благодарю)(?:\s+вам)?[.!\s]*', previous_out, re.IGNORECASE)):
        return True
    if re.fullmatch(r'\s*(?:хорошего|доброго)\s+(?:дня|вечера)[.!\s]*', last, re.IGNORECASE):
        return True
    if re.fullmatch(r'\s*(?:(?:я\s+)?понял[аи]?(?:\s+вас)?[,.!\s]*)?(?:спасибо|благодарю)\s+за\s+(?:информацию|ответ)[.!\s👍👌🙏🙂😊]*', last, re.IGNORECASE):
        return True
    if (re.fullmatch(r'\s*(?:ну[,!\s]*)?(?:тогда[,!\s]*)?ладно[,.!\s]*(?:спасибо|благодарю)[.!\s]*',last,re.I)
            and re.search(r'(?:никак|ничем)\s+не\s+помогу|не\s+смогу\s+(?:вам\s+)?помочь',previous_out,re.I)):
        return True
    if re.fullmatch(r'\s*(?:ок|хорошо|ясно|понял[аи]?|спасибо|договорились|принято)[.!\s]*', last, re.IGNORECASE):
        if (re.search(r'(?:^|\n)\s*нет[.!\s]*(?:\n|$)', previous_out, re.I)
                and re.search(r'проще\s+(?:(?:вам|будет)\s+)?нов(?:ый|ую|ое)\s+купить', previous_out, re.I)):
            return True
        refusal = re.search(r'с\s+(?:этим|таким).{0,15}(?:не\s+помогу|не\s+смогу\s+помочь)|не\s+смогу\s+(?:вам\s+)?помочь|не\s+занимаюсь|не\s+принимаем|'
                            r'\b(?:выехать|приехать|подъехать)\s+не\s+смогу\b', previous_out, re.IGNORECASE)
        if re.search(r'\bесли\s+(?:что|понадобится\s+помощь)\b[^.!?\n]{0,25}\bпишите\b', previous_out, re.I):
            return True
        return_later = re.search(r'\b(?:напишите|отпишитесь|свяжитесь)\b.{0,30}(?:позже|ближе\s+к\s+(?:этому\s+времени|[а-яё]+)|после\s+\d|в\s+(?:понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье))', previous_out, re.IGNORECASE)
        if re.search(r'приед|подъед|визит|запис|буду\s+у\s+вас', previous_out, re.I):
            return_later = None
        return_avito_call = re.search(r'\b(?:наберите|позвоните)\s+(?:на|через)\s+авито\b', previous_out, re.I)
        if refusal or return_later or return_avito_call:
            return True
    if re.fullmatch(r'\s*(?:(?:ок|хорошо)[,!\s]*)?понял[аи]?[,!\s]+(?:спасибо|благодарю)(?:\s+за\s+ответ)?[.!\s]*', last, re.IGNORECASE):
        return True
    if re.fullmatch(r'\s*(?:хорошо[,!\s]*)?(?:спасибо|благодарю)(?:\s+(?:большое|вам))?[.!()\s]*', last, re.IGNORECASE):
        farewell = re.search(r'если\s+(?:надумаете|что).{0,25}пишите|до\s*свидания|до\s+встречи|всего\s+(?:доброго|хорошего)|прощайте|не\s+ремонтируется|не\s+смогу\s+помочь|не\s+занимаюсь', previous_out, re.IGNORECASE)
        factual_answer = (previous_out and '?' not in previous_out
                          and not re.search(r'\d\s*(?:руб|₽|р(?=[.\s,!?]|$))|когда|удобно|устраив|соглас|подход|'
                                            r'оставьте|напишите|подскажите|\bбуду\b|\bмогу\b|\bсмогу\b', previous_out, re.I))
        return bool(farewell or factual_answer)
    return bool(re.fullmatch(r'\s*ясно[.!\s]*', last, re.IGNORECASE) and re.search(r'с\s+таким\s+не\s+помогу|не\s+смогу\s+помочь|не\s+занимаюсь|не\s+принимаем', previous_out, re.IGNORECASE))


def _staff_withdraws_visit(body):
    clock = re.search(r'\b(?:в|к)\s*\d{1,2}(?:[.: ]\d{2})?', body, re.I)
    contact_only = (re.search(r'позвон|перезвон|созвон|напис|спиш', body, re.I)
                    and not re.search(r'приед|подъед|визит|приезд|запис|буду\s+у\s+вас', body, re.I))
    arrival = re.search(r'\b(?:приехать|подъехать|приеду|подъеду)\b', body, re.I)
    return bool((clock or arrival) and not contact_only and re.search(
        r'\bне\s+(?:смогу|сможем|сможет|получится|приеду|подъеду)\b', body, re.I))


def _previous_staff_turn(messages):
    last_client = next((i for i in range(len(messages) - 1, -1, -1) if messages[i].get('direction') == 'in'), len(messages))
    turn = []
    for message in reversed(messages[:last_client]):
        if message.get('direction') == 'in':
            break
        if message.get('direction') == 'out':
            turn.append(message['body'])
    return '\n'.join(reversed(turn))


def _service_reported_resolved(last):
    return bool(re.search(r'спасибо|благодарю', last, re.I)
                and re.search(r'вс[её]\s+(?:хорошо|работает)|теперь\s+работает|вс[её]\s+починили', last, re.I)
                and not re.search(r'\?|\bно\b|снова|опять|не\s+работ|верните|вернут|деньг|оплат|стоим|за\s+что', last, re.I))


def _unresolved_trapped_animal(incoming):
    animal = r'(?:хомяк|кот[её]нок|кот|кошка|щенок|животное)'
    for body in reversed(incoming):
        live_mouse = bool(re.search(r'\bмышь\b', body, re.I) and re.search(r'живая|не\s+может\s+выбраться|питомец', body, re.I))
        subject = r'(?:' + animal + (r'|мышь' if live_mouse else '') + r')'
        if re.search(r'\b' + subject + r'\b[^.!?\n]{0,35}(?:выбрался|выбралась|достали|освободили)', body, re.I):
            return False
        if (re.search(r'принтер|мфу|стиральн', body, re.I)
                and re.search(r'\b' + subject + r'\b[^.!?\n]{0,35}застрял[ао]?|'
                              r'застрял[ао]?[^.!?\n]{0,35}\b' + subject + r'\b', body, re.I)):
            return True
    return False


def _withdrawn_staff_visit(messages):
    """Withdrawal changes the chat agreement, not the unknown CRM record."""
    withdrawal = None
    for i, message in enumerate(messages):
        body = message['body']
        if message.get('direction') == 'in' and re.search(
                r'\b(?:новая\s+заявка|новый\s+заказ|по\s+другому\s+вопросу|теперь\s+нужно)\b', body, re.I):
            withdrawal = None
        if (message.get('direction') == 'out' and not message.get('out_pending')
                and _staff_withdraws_visit(body)
                and (previous := _accepted_staff_visit(messages[:i], include_later_questions=True))):
            withdrawal = dict(previous_agreement=previous, withdrawal_message_id=message['id'],
                              withdrawal_quote=body, crm_cancellation_confirmed=False)
    return withdrawal


def _staff_booking_claim(messages):
    """A staff claim is lookup evidence, never proof of a CRM write."""
    claim = None
    for message in messages:
        body = message.get('body','')
        if (message.get('direction')=='in' and re.search(
                r'\b(?:новая\s+заявка|новый\s+заказ|по\s+другому\s+вопросу|теперь\s+нужно)\b',body,re.I)):
            claim = None
        if message.get('direction')!='out' or message.get('out_pending'):
            continue
        for clause in re.split(r'[.!\n]+',body):
            found=re.search(r'\b(?:записал[аи]?\s+вас|вы\s+записаны|'
                            r'записал[аи]?\s+(?:на\s+(?:сегодня|завтра)|[кв]\s*\d{1,2}))\b',clause,re.I)
            if (found and '?' not in clause
                    and not re.search(r'\bесли\b|\bне\s*$',clause[:found.start()],re.I)):
                claim=dict(message_id=message['id'],quote=body,source='staff_statement_unverified',crm_write_confirmed=False)
    return claim


def _accepted_staff_visit(messages, include_later_questions=False):
    """A timed exchange, in either direction, is historical lookup evidence.

    This never turns staff words into a dated client fact or a new appointment.
    Two binary questions make a bare yes ambiguous.
    """
    accepted = None
    clock = re.compile(r'\b(?:в|к)\s*\d{1,2}(?:[.: ]\d{2})?(?:\s*[-–—]\s*\d{1,2}(?:[.: ]\d{2})?)?'
                       r'|\bна\s*(?:[01]?\d|2[0-3])[.: ](?:[0-5]\d)\b', re.IGNORECASE)
    relative = re.compile(r'\bчерез\s+(?:час(?:[-–— ]полтора)?|\d+(?:[-–—]\d+)?\s+(?:минут|час)|'
                          r'(?:один|два|две|три|полтора)(?:\s*[-–—]\s*(?:два|три|полтора))?(?:\s+с\s+половиной)?\s+час)'
                          r'|\bв\s+течени[еи]\s+часа?(?:[-–— ]полутора)?\b', re.IGNORECASE)
    latest_proposal = None
    binary_question = re.compile(r'\b(?:есть|готов\w*|будете|будет|удобно|подойд[её]т|можете|сможете|согласны|актуальн\w*)\b|\bвы\s+(?:тут|здесь|на\s+связи)\b',re.I)
    def clock_key(match):
        if re.search(r'[-–—]',match[0]):
            return ('range',re.sub(r'\s+','',match[0]))
        numbers=re.findall(r'\d+',match[0])
        return ('point',int(numbers[0]),int(numbers[1]) if len(numbers)>1 else 0)
    def discussion_only(body):
        contact = re.search(r'спишемся|позвон\w*|перезвон\w*|созвон\w*|свяжемся|напиш(?:у|ите|те|ем)', body, re.I)
        discussion = re.search(r'\bобсудим\b', body, re.I) and not re.search(r'\bна\s+месте\b', body, re.I)
        return ((contact or discussion)
                and not re.search(r'приед|подъед|визит|приезд|запис|буду\s+у\s+вас', body, re.I))
    weekdays = r'понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье'
    day_mention = re.compile(r'\b(?:(следующую|следующий|эту|этот)\s+)?(' + weekdays + r')\b', re.I)
    day_answer = re.compile(r'(?:(?:давайте|тогда|хорошо|да|договорились)[,\s]+)*(?:в|на)\s+'
                            r'(?:(следующую|следующий|эту|этот)\s+)?(' + weekdays + r')', re.I)
    def accepts_weekday(answer, proposal):
        # A named day can acknowledge one delivered, timed visit. It does
        # not choose between multiple hours/days or turn contact time into a visit.
        parts = re.split(r'([.!?\n])', answer, maxsplit=1)
        choice = day_answer.fullmatch(parts[0].strip())
        if not choice or len(parts) > 1 and parts[1] == '?':
            return False
        days = list(day_mention.finditer(proposal))
        times = list(clock.finditer(proposal))
        if (not days or len({m[2].lower() for m in days}) != 1
                or len({clock_key(m) for m in times}) != 1
                or not times or clock_key(times[0])[0] != 'point'
                or choice[2].lower() != days[0][2].lower()):
            return False
        if (choice[1] and ('следующ' in choice[1].lower()) != any(m[1] and 'следующ' in m[1].lower() for m in days)):
            return False
        if clock.search(answer) or re.search(r'\b(?:но|пока\s+не|если\s+(?:смогу|получится))\b', answer, re.I):
            return False
        return True
    for i, message in enumerate(messages):
        body = message['body'].strip()
        if message.get('direction') == 'out':
            if not message.get('out_pending') and _staff_withdraws_visit(body):
                # A later "хорошо" to discussing a replacement must not
                # revive the previously accepted but withdrawn appointment.
                accepted, latest_proposal = None, None
                continue
            previous_client=next((m for m in reversed(messages[:i]) if m.get('direction')=='in'),None)
            if (not message.get('out_pending') and previous_client and clock.search(previous_client['body'])
                    and re.search(r'удобно|сможете|сможем|не\s+поздно\s+будет|давайте|\bможно\s+(?:в|к|после)\s*\d',previous_client['body'],re.I)
                    and not re.search(r'позвон|напиш|перезвон|отпиш',previous_client['body'],re.I)
                    and re.match(r'^(?:да|подходит|хорошо|смогу)(?=$|[,.!\s])',body,re.I)
                    and not re.fullmatch(r'да[,!\s]+(?:смогу|могу)\s+(?:вам\s+)?помочь[.!\s]*',body,re.I)
                    and not re.search(r'\b(?:не|но|нет)\b',body,re.I)):
                accepted=dict(proposal_message_id=previous_client['id'],proposal_quote=previous_client['body'],
                              answer_message_id=message['id'],answer_quote=message['body'])
            if not message.get('out_pending') and not discussion_only(body) and (clock.search(body) or relative.search(body)):
                latest_proposal = message
            continue
        if message.get('direction') != 'in':
            continue
        if (message.get('sender_type') in ('operator', 'assistant', 'bot', 'employee', 'staff', 'system', 'avito')
                or message.get('role') == 'assistant'):
            continue
        if re.search(r'\b(?:новая\s+заявка|новый\s+заказ|по\s+другому\s+вопросу|теперь\s+нужно)\b', body, re.IGNORECASE):
            accepted, latest_proposal = None, None
            continue
        relative_echo = re.fullmatch(r'\s*(через\s+час)\s*[,—-]?\s*(?:мне\s+)?удобно(?:\s+будет)?[.!\s]*', body, re.I)
        if (relative_echo and latest_proposal and not latest_proposal.get('out_pending')
                and re.search(r'\bчерез\s+час(?:[-–— ]полтора)?\b', latest_proposal['body'], re.I)
                and re.search(r'удобно|подойд[её]т|приед|подъед|\bбуду\b', latest_proposal['body'], re.I)
                and not discussion_only(latest_proposal['body'])
                and not (re.search(r'готов|займ[её]т|занимает|достав|привез', latest_proposal['body'], re.I)
                         and not re.search(r'приед|подъед|буду\s+у\s+вас', latest_proposal['body'], re.I))):
            # A literal hour accepted inside a delivered hour/hour-and-half
            # offer is existing-visit evidence, never a new CRM booking.
            accepted = dict(proposal_message_id=latest_proposal['id'], proposal_quote=latest_proposal['body'],
                            answer_message_id=message['id'], answer_quote=message['body'])
            continue
        expectation = contact_facts.explicit_visit_expectation(body)
        if expectation and latest_proposal:
            proposal = latest_proposal['body']
            times = {clock_key(m) for m in clock.finditer(proposal)}
            days = re.findall(r'\bсегодня\b|\bзавтра\b|\bпослезавтра\b|\b(?:' + weekdays + r')\b', proposal, re.I)
            stated_day = re.sub(r'^в\s+', '', expectation['day'])
            expected_time = ('point', *map(int, expectation['time'].split(':')))
            if (times == {expected_time} and (not stated_day or {d.casefold() for d in days} == {stated_day})
                    and not re.search(r'[«»"?].*[«»"]|\b(?:если|возможно|не\s+смогу)\b', proposal, re.I)):
                accepted = dict(proposal_message_id=latest_proposal['id'], proposal_quote=proposal,
                                answer_message_id=message['id'], answer_quote=message['body'])
                continue
        if (latest_proposal and clock.search(body) and clock.search(latest_proposal['body'])
                and re.fullmatch(r'\s*(?:(?:утром|вечером|давайте|тогда)\s+)*(?:в|к)\s*\d{1,2}(?:[.:]\d{2})?[.!\s]*', body, re.I)
                and clock_key(clock.search(body)) == clock_key(clock.search(latest_proposal['body']))):
            accepted = dict(proposal_message_id=latest_proposal['id'], proposal_quote=latest_proposal['body'],
                            answer_message_id=message['id'], answer_quote=message['body'])
            continue
        answer = body
        phone_prefix = contact_phone.find_all(answer)
        if len(phone_prefix)==1 and not answer[:phone_prefix[0].start].strip(' ,;:()'):
            answer = answer[phone_prefix[0].end:].lstrip(' ,;:()')
        weekday_confirmation = bool(latest_proposal and accepts_weekday(answer, latest_proposal['body']))
        if weekday_confirmation:
            proposal_index = next(j for j, m in enumerate(messages[:i]) if m['id'] == latest_proposal['id'])
            weekday_confirmation = not any(m.get('out_pending') for m in messages[proposal_index + 1:i])
        yes = re.match(r'^(?:давайте|да|ага|ок|конечно|подходит|удобно|хорошо|отлично|договорились|[👌👍✅])(?=$|[.!\s,()+\d])[,!.\s()]*', answer, re.IGNORECASE)
        if not yes and not weekday_confirmation:
            continue
        tail = '' if weekday_confirmation else re.sub(r'^(?:спасибо|благодарю)[,!\s]*', '', answer[yes.end():], flags=re.IGNORECASE).strip('.! ()\n')
        polite_tail=re.fullmatch(r'(?:было\s+бы\s+)?(?:конечно|замечательно|отлично|хорошо|(?:очень\s+)?удобно|подходит|жду(?:\s+вас)?|жд[её]м(?:\s+вас)?|вас\s+жд[её]м|буду\s+ждать(?:\s+вас)?)(?:[,!\s]+(?:спасибо|благодарю))?',tail,re.I)
        polite_phone = re.fullmatch(r'(?:удобно|подходит|буду\s+ждать)[,.!\s]+([+()\d\s-]+)', tail, re.I)
        access_person = re.fullmatch(r'(?:по\s+адресу|на\s+месте)\s+будет\s+(?:прод[а]?вец|мама|папа|супруг[а]?|взрослый)', tail, re.I)
        polite_followup=(re.match(r'^конечно[,!\s]+',tail,re.I) and '?' in tail
                         and not re.search(r'\b(?:но|не|если)\b|цен|стоим|сколько|дорог',tail,re.I))
        address_tail = (re.search(r'\b(?:квартира|кв\.?|под[ъь]езд|этаж)\s*[№:#]?\s*\d+',tail,re.I)
                        and not clock.search(tail) and not relative.search(tail))
        if tail and not polite_followup and (re.search(r'\?|\bно\b|\bне\b', tail, re.IGNORECASE) or not (polite_tail or
                re.fullmatch(r'[+()\d\s-]+', tail) and len(contact_phone.find_all(tail)) == 1
                or polite_phone and len(contact_phone.find_all(polite_phone[1])) == 1 or access_person
                or address_tail or any(contact_facts.collect([message]).get('address', {}).get(key)
                       for key in ('street','building','office','entrance','floor','settlement')))):
            continue
        turn = []
        for previous in reversed(messages[:i]):
            if previous.get('direction') != 'out':
                break
            if previous.get('out_pending'):
                turn=[]
                break
            turn.append(previous)
        turn.reverse()
        if not turn and latest_proposal:
            # A separate pure phone reply can precede an unambiguous yes to
            # the same timed proposal. Other questions/details stop this path.
            proposal_index=next(j for j,m in enumerate(messages[:i]) if m['id']==latest_proposal['id'])
            intervening=messages[proposal_index+1:i]
            contact_only=lambda m: (m.get('direction')=='in' and re.fullmatch(r'[+()\d\s-]+',m['body'].strip())
                                    and len(contact_phone.find_all(m['body']))==1)
            if (intervening and all(contact_only(m) if m.get('direction')=='in' else
                                   m.get('direction')=='out' and re.search(r'номер|телефон|адрес',m['body'],re.I)
                                   and not re.search(r'\b(?:есть|готов|будете|согласны)\b',m['body'],re.I)
                                   for m in intervening)):
                turn=[latest_proposal]
        # A staff correction explicitly withdraws the preceding slot. A later
        # bare clock ("К 14") is then the actual proposal, not 13:30.
        slots = []
        for previous in turn:
            if _staff_withdraws_visit(previous['body']) or re.search(r'(?:извините|ищвините)[,!\s]+нет', previous['body'], re.IGNORECASE):
                slots.clear()
            elif not discussion_only(previous['body']) and (clock.search(previous['body']) or (relative.search(previous['body']) and re.search(r'удобно|подойд[её]т|могу|приед|подъед|\bбуду\b', previous['body'], re.IGNORECASE))):
                slots.append(previous)
        # Repeating the same hour/hour-and-a-half in one staff turn is one
        # proposal. Distinct slots still require an explicit client choice.
        unique_slots = {}
        for slot in slots:
            match = clock.search(slot['body']) or relative.search(slot['body'])
            signature = re.sub(r'[^а-яё\d]', '', match[0].lower())
            unique_slots[signature] = slot
        slot_messages = slots
        slots = list(unique_slots.values())
        other_binary = [m for m in turn if m not in slots and binary_question.search(m['body'])]
        other_binary = [m for m in other_binary if m not in slot_messages]
        # A slot and a second binary question in the same message are also
        # ambiguous. A phone request is not a second yes/no question.
        slot_binary = any(binary_question.search(clause)
                          and not clock.search(clause) and not relative.search(clause)
                          for m in slots for clause in re.split(r'[?!.\n]+', m['body']))
        day_slot_matches = not weekday_confirmation or all(accepts_weekday(answer, slot['body']) for slot in slot_messages)
        if len(slots) == 1 and not other_binary and not slot_binary and day_slot_matches:
            accepted = dict(proposal_message_id=slots[0]['id'], proposal_quote=slots[0]['body'],
                            answer_message_id=message['id'], answer_quote=message['body'])
    if accepted and not include_later_questions:
        current_index = next((i for i in range(len(messages) - 1, -1, -1) if messages[i].get('direction') == 'in'), -1)
        answer_index = next(i for i, m in enumerate(messages) if m['id'] == accepted['answer_message_id'])
        current = messages[current_index] if current_index >= 0 else {}
        if (current_index >= answer_index
                and re.search(r'\?|сколько|стоим|будут\s+ли|есть\s+ли', current.get('body',''), re.IGNORECASE)):
            # A question accompanying acceptance, or a later one, can still receive a safe factual answer. It
            # does not itself request a second appointment or prove a booking.
            return None
    if accepted:
        # A staff "yes" to the client's proposed hour is reciprocal lookup
        # evidence, not the client accepting a staff offer. Keep the actual
        # speakers alongside the original IDs/quotes, without proving a CRM
        # booking or asserting that an old preference is still current.
        proposals = [m for m in messages if m.get('id') == accepted['proposal_message_id']]
        answers = [m for m in messages if m.get('id') == accepted['answer_message_id']]
        if len(proposals) != 1 or len(answers) != 1:
            return None
        proposal_role = 'client' if contact_facts._client_intent_message(proposals[0]) else 'staff'
        answer_role = 'client' if contact_facts._client_intent_message(answers[0]) else 'staff'
        if proposal_role == answer_role:
            return None
        accepted = dict(accepted, proposal_speaker=proposal_role, answer_speaker=answer_role,
                        source='observed_historical_timed_exchange',
                        current_availability_verified=False, crm_write_confirmed=False)
    return accepted


def _document_question(messages):
    """An issuance/payment question, not every question about document files.

    Keep the unresolved source request across unrelated turns. A file-saving
    problem neither orders a receipt nor withdraws an earlier receipt request.
    """
    request = None
    receipt = re.compile(r'квитанц\w*|кассов\w*\s+чек|\bчек\b|\bбсо\b', re.I)
    generic = re.compile(r'\bдокумент\w*', re.I)
    financial = re.compile(r'оплат\w*|плат[её]ж\w*|бухгалтер\w*|отч[её]тност\w*|'
                           r'оказанн\w*\s+услуг\w*|выполненн\w*\s+работ\w*', re.I)
    issuance = re.compile(r'\b(?:да[её]те|дадите|выда[её]те|выдадите|предоставите|предоставляете|'
                          r'оставите|оставляете|оформите|оформляете)\b|'
                          r'\bпосле\s+(?:работ\w*|ремонт\w*|услуг\w*)\b', re.I)
    files = re.compile(r'\b(?:word|excel|файл\w*|ноутбук\w*|компьютер\w*|электронн\w*|'
                       r'сохран\w*|удал\w*|восстанов\w*|распечат\w*|печат\w*|скан\w*)\b', re.I)
    file_operation = re.compile(r'\b(?:сохран\w*|удал\w*|восстанов\w*|распечат\w*|'
                                r'печат\w*|откры\w*|форматир\w*)\b', re.I)
    withdrawn = re.compile(r'(?:квитанц\w*|документ\w*|чек|бсо)\s+(?:(?:мне|нам)\s+)?не\s+нуж|'
                           r'не\s+нуж\w*.{0,20}(?:квитанц|документ|чек|бсо)', re.I)
    for message in messages:
        if message.get('out_pending') or str(message.get('delivery_status') or message.get('delivery') or '').lower() in (
                'failed', 'error', 'pending', 'queued', 'sending', 'processing', 'cancelled', 'canceled'):
            continue
        text = str(message.get('body') or '')
        if (contact_facts._client_intent_message(message)
                and message.get('speaker_role', 'client') == 'client'
                and message.get('role') not in ('system', 'assistant')):
            # A quoted name in "выдаёте «кассовый чек»?" remains the object
            # of the client's own question. Reported questions are different.
            if re.search(r'\b(?:сосед|мастер|сотрудник|клиент)\w*[^.!?\n]{0,35}'
                         r'(?:сказал|написал|спросил)|\bцитат\w*', text, re.I):
                text = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', text)
            elif re.fullmatch(r'\s*(?:«[^»]*»|“[^”]*”|"[^"\n]*")\s*[.!?]?\s*', text):
                continue
            clauses = re.split(r'(?<=[.!?;\n])|,\s*(?=(?:а|но)\s+(?:кассов|бсо|квитанц|документ))', text, flags=re.I)
            for clause in clauses:
                explicit = bool(receipt.search(clause))
                paper = bool(generic.search(clause))
                financial_paper = paper and (financial.search(clause) and not file_operation.search(clause)
                    or issuance.search(clause) and (financial.search(clause) or not files.search(clause)))
                # A bare withdrawal may refer to a previous generic issuance
                # question, but an electronic file has its own subject.
                cancellation = withdrawn.search(clause) and (explicit or paper and not files.search(clause))
                if cancellation:
                    request = None
                elif (explicit or financial_paper) and (issuance.search(clause) or re.search(
                        r'\?|нуж(?:ен|на|ны)|требует', clause, re.I)):
                    request = dict(message_id=message['id'], quote=message['body'],
                        explicit_type=bool(re.search(r'кассов\w*\s+чек|\bбсо\b', clause, re.I)))
        elif (message.get('direction') == 'out'
              and str(message.get('sender_type') or '').lower() in ('', 'operator', 'staff', 'human', 'employee', 'manager')
              and (receipt.search(text) or generic.search(text) and not files.search(text)) and '?' not in text):
            # An explicit human answer remains a commitment to inspect; it
            # does not establish authority to promise a cash receipt.
            if request:
                request['staff_answer'] = text
    return request


@lru_cache(maxsize=1)
def registry():
    return json.loads(Path(__file__).with_name("policy_registry.json").read_text())


def _words(text):
    return {w[:6] for w in re.findall(r"[а-яёa-z]{3,}", text.lower())}


def _explicit_settlement(messages):
    """Catch a typed locality even when a long contact message was not parsed.

    Locality types or an explicit residence statement are required. Do not
    guess a map location from a model or an ordinary capitalized word.
    """
    for message in reversed(messages):
        if message.get("direction") != "in":
            continue
        residence = contact_facts.residence_place([message])
        if residence:
            return residence['value']
        for fragment in reversed(re.split(r"[.!?;\n]+", message["body"])):
            origin = re.search(r'\b(?:мы|я)\s+(?:из|с)\s+([а-яё-]{4,40})\s*$', fragment, re.IGNORECASE)
            if (origin and re.search(r'привез|приеха|\bжив[её]м\b|\bживу\b',message['body'],re.IGNORECASE)
                    and origin[1].casefold() not in ('вами','ним','ней','работы','другом','мастером')):
                # A bare self-reported locality is a lookup hint, never a
                # guessed nominative place, coordinate or service territory.
                return origin[1]
            marker = re.search(r"\b(?:пгт|пос[её]лок|село|деревня)\s+", fragment, re.IGNORECASE)
            if marker:
                candidate = fragment[marker.start():].strip()
                tail = re.search(r'\s+(?:не\s+)?(?:выезж\w*|прие[дз]\w*|смож\w*|можно)\b', candidate, re.IGNORECASE)
                if tail:
                    candidate = candidate[:tail.start()].strip()
                place = contact_address.parse_place(candidate)
                if place and place.settlement:
                    return place.settlement
    return ""


def retrieve(query, limit=6, refs=(), direction="", applied_only=False):
    all_sources = [s for s in registry()["sources"] + assistant_catalog.data()["owner_amendments"] if s.get("active_primary") is not False]
    by_id = {source["id"]: source for source in all_sources}
    direct = [by_id[ref] for ref in dict.fromkeys(refs) if ref in by_id]
    if direct or applied_only:
        return direct[:limit]
    words = _words(query)
    eligible = [
        source
        for source in all_sources
        if direction == "kp" or source.get("type") != "kp_document"
    ]
    scored = [
        (len(words & _words(source["text"])), source["id"], source)
        for source in eligible
    ]
    return [
        source for score, _, source in sorted(scored, reverse=True)[:limit] if score
    ]


def geography(city, direction, lat=None, lon=None):
    city = filials.physical_city(city, direction)
    if direction not in ("kp", "bt", "mnc") or not city:
        return {"status": "unknown", "reason": "Не определены город и направление"}
    operational = {
        "Элиста": (
            "TG1-651",
            "В канале есть закрытие Элисты, в текущей CRM город доступен",
        ),
        "Ульяновск": (
            "TG1-510",
            "В канале закрыт приём новых/повторных заявок, локальный справочник отмечает филиал",
        ),
    }
    if direction == "kp" and city in operational:
        ref, reason = operational[city]
        return {
            "status": "needs_confirmation",
            "reason": reason + ". Статус должен подтвердить оператор.",
            "rule_ids": [ref],
        }
    if direction == "kp" and city in ("Дудинка", "Зеленодольск"):
        parent = "Норильск" if city == "Дудинка" else "Казань"
        return {
            "status": "known",
            "crm_city": parent,
            "settlement": city,
            "far_trip": city == "Дудинка",
            "rule_ids": ["TG1-553"],
            **({"lead": 2.5} if city == "Зеленодольск" else {}),
        }
    if direction == "kp" and city == "Златоуст":
        return {
            "status": "needs_confirmation",
            "reason": "Златоуст больше не спутник: нужно согласование с Челябинском",
            "crm_city": "Челябинск",
            "settlement": "Златоуст",
            "rule_ids": ["TG1-577"],
        }
    if filials.suspended(city, direction):
        return {"status": "closed", "reason": "Филиал временно закрыт"}
    if not filials.known(city, direction):
        return {
            "status": "unknown",
            "reason": "Нужно проверить филиал или населённый пункт",
        }
    parent = filials.satellite_of(city, direction)
    result = {
        "status": "known",
        "crm_city": parent or city,
        "settlement": city if parent else "",
        "far_trip": bool(
            parent and direction == "kp" and city in ("Ковров", "Воткинск")
        ),
        "rule_ids": [],
    }
    if city.casefold() == 'евпатория' and parent == 'Симферополь':
        # Owner 17.10: inherit service acceptance, keep the satellite CRM city.
        # Travel remains governed by satellite rules, not the parent's centre.
        result.update(physical_city='Евпатория', crm_city='Евпатория',
                      crm_label='Евпатория (Симферополь)', main_branch=parent,
                      satellite_of=parent, acceptance_city=parent,
                      lead_hours=[2, 2.5], earliest='11:00')
        result['rule_ids'].append('OWNER-EVPATORIA-SIMFEROPOL-20261017')
    key = city.lower().replace("ё", "е")
    sid = {"ковров": "TG1-669", "феодосия": "TG1-675", "курган": "TG1-674"}.get(key)
    if direction == "kp" and sid:
        result["rule_ids"].append(sid)
    if direction == 'kp' and city in ('Ставрополь', 'Невинномысск'):
        result['rule_ids'].append('TG1-586')  # Later reopening supersedes584.
    if direction == "kp" and key == "феодосия":
        result["crm_label"] = (
            "Керчь-Феодосия"  # Read from the live CRM city selector 15.10.2026.
        )
    if direction == "kp" and key == "мытищи":
        result["rule_ids"].append("TG1-670")
        loc = (
            territory.locate(lat, lon, city, direction)
            if lat is not None and lon is not None
            else None
        )
        if not loc or loc.get("city") != "Мытищи" or loc.get("zone") == "outside":
            result.update(
                status="needs_zone",
                reason="Для Мытищей нужно определить точную зону по адресу",
            )
        else:
            result.update(
                lead=loc.get("lead"),
                earliest=loc.get("earliest"),
                zone=loc.get("policy_zone", ""),
            )
    return result


def crew_composition_question(messages):
    """A current question about workers is not a confirmed two-worker request.

    Staff legends and future replies cannot establish actual availability.
    Keep this fact check separate from technical service/branch approval.
    """
    turn = []
    for message in reversed(messages):
        if message.get('direction') == 'out' and str(message.get('sender_type') or '').casefold() in (
                '', 'operator', 'employee', 'bot', 'assistant'):
            break
        if contact_facts._client_intent_message(message):
            turn.append(message)
    active = None
    one = r'од(?:ин|на|ни)'
    number = re.compile(
        r'\bвы\s+(?:не\s+)?' + one + r'\s*(?=$|[?!,]|работаете\b|работаешь\b|будете\b)|'
        r'\bвы\s+(?:не\s+)?(?:приедете|приезжаете|работаете|будете)\s+(?:не\s+)?(?:' + one + r'|вдвоем)\b|'
        r'\b(?:' + one + r'|вдвоем)\s+(?:будете|приедете|работаете)\b|'
        r'\b(?:вы\s+)?с\s+напарник\w*\s+(?:приедете|приезжаете|работаете)\b|'
        r'\bу\s+вас\s+(?:есть\s+)?напарник\b|'
        r'\bсколько\s+(?:человек|мастеров|исполнителей)\s+(?:будет|приедет|приедут|придет|придут|работает)\b|'
        r'\bсколько\s+вас\s+(?:будет|приедет|приедут)\b|'
        r'\bвам\s+одному\s+(?:под\s+силу|по\s+силам)\b', re.I)
    for message in reversed(turn):
        body = str(message.get('body') or message.get('text') or '')
        literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', body).casefold().replace('ё', 'е')
        for clause in re.split(r'[.!?;\n]+', literal):
            if re.search(r'\bне\s+(?:важно|принципиально|спрашиваю)\b|'
                         r'\bколичеств\w*\s+(?:мастер\w*|людей)\s+не\s+важ', clause):
                active = None
                continue
            if re.search(r'\b(?:мастер|специалист|сосед|он|она)\w*\b[^.!?]{0,40}'
                         r'\b(?:спросил|спросила|сказал|сказала|написал|написала)\b', clause):
                continue
            if number.search(clause):
                active = dict(message_id=message.get('id', ''), quote=body,
                              source='current_client_turn', current_availability_verified=False,
                              requested_worker_count=None)
    return active


def optional_avito_payment_choice(messages, known):
    """Ignore only the optional questionnaire selection, not payment questions."""
    if known.get('channel') != 'avito':
        return None
    for message in reversed(messages):
        if not contact_facts._client_intent_message(message):
            continue
        body = str(message.get('body') or message.get('text') or '')
        if not re.search(r'Задача\s+составлена\s+по\s+ответам\s+клиента\s+в\s+анкете', body, re.I):
            continue
        choice = re.search(r'Как\s+бы\s+хотели\s+оплатить\s*:[ \t]*\n([^\n]+)', body, re.I)
        if choice and re.fullmatch(r'\s*Онлайн\s+с\s+[«“"]?Защитой\s+сделки[»”"]?\s*', choice[1], re.I):
            return dict(message_id=message.get('id', ''), selection_quote=choice[1],
                        source='client_questionnaire_selection',
                        rule_id='OWNER-AVITO-QUESTIONNAIRE-PAYMENT-20261023',
                        ignore_selection_only=True, explicit_other_questions_remain=True,
                        payment_made_confirmed=False, payment_service_confirmed=False)
    return None


def intake_question_context(messages, known, service):
    """A current process/help question about an observed ordinary job.

    This describes intake, never a repair result. Shared lifecycle, route and
    service guards decide whether the answer may reach the customer.
    """
    if service.get('status') != 'supported' or not service.get('items'):
        return None
    current = assistant_prices.current_enquiry_messages(messages)
    def client(message):
        return (contact_facts._client_intent_message(message)
                and message.get('role') not in ('system', 'assistant')
                and message.get('speaker_role','client')=='client'
                and not message.get('out_pending')
                and str(message.get('delivery_status') or message.get('delivery') or '').lower()
                not in ('failed', 'error', 'pending', 'queued', 'sending', 'cancelled', 'canceled'))
    starts = [i for i, m in enumerate(current) if client(m)
              and re.match(r'\s*(?:новая\s+заявка|новый\s+заказ|по\s+другому\s+вопросу)\b', m.get('body', ''), re.I)]
    if starts:
        current = current[starts[-1]:]
    clients = [m for m in current if client(m)]
    # A service event or an undelivered send does not answer the client.
    # Use the same delivered speech boundary as the other current questions.
    tail = _current_client_question_rows(current)
    if not tail:
        return None
    foreign = r'\b(?:сосед\w*|мастер\w*|сотрудник\w*)[^.!?;\n]{0,35}(?:сказал|спросил|написал|говорит)|\bсоседу\b'
    def clauses(body):
        literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', body)
        return [part for part in re.split(r'[.!?;\n]+', literal)
                if not re.search(foreign, part, re.I)
                and not re.search(r'не\s+(?:спрашива\w*|надо\s+рассказывать|хочу\s+узнать)|'
                                  r'если\s+(?:понадобится|потребуется|захочу|решу|соберусь)|'
                                  r'\[системное\s+сообщение\]|ассистент\s+авито', part, re.I)]
    work_ids = []
    selected = {item['id'] for item in service['items']}
    for message in clients:
        for part in clauses(message.get('body', '')):
            part = re.split(r'\bесли\b', part, maxsplit=1, flags=re.I)[0]
            if (not part.strip() or re.search(r'не\s+(?:нужно|надо|требуется)|\b(?:раньше|вчера|вдруг|возможно)\b', part, re.I)
                    or not (re.search(r'нужно|надо|требуется|собрать|установить|заменить|починить|настроить|'
                                     r'слом|медленн|плох\w*\s+смыва|не\s+(?:работ|включ|отжим|печат|слива)|'
                                     r'засор|теч[её]т|капает|протека|гудит|шумит', part, re.I)
                            or assistant_catalog.office_fault_request(part))):
                continue
            anchored = assistant_catalog.choose(part, known)
            if selected & {item['id'] for item in anchored.get('items', [])}:
                work_ids.append(message.get('id', ''))
    if not work_ids:
        return None
    process_pattern = (r'\bкак\s+(?:(?:у\s+вас|вообще|это|вс[её]|дальше)\s+){0,4}'
                       r'(?:(?:будет|будут)\s+)?(?:происход\w*|проход\w*|будет)\b|'
                       r'\bкак\s+(?:мне\s+)?оформить\s+(?:заявку|заказ)\b|'
                       r'\bпорядок\s+оформления\b')
    capability_pattern = (r'\b(?:можете|сможете)(?:\s+(?:ли|вы|мне|тоже|с\s+этим|в\s+этом\s+вопросе)){0,4}\s+помочь\b|'
                          r'\b(?:поможете|возьм[её]тесь|возьмитесь)\b')
    query_ids, kinds = [], set()
    for message in tail:
        for part in clauses(message.get('body', '')):
            if (re.search(process_pattern, part, re.I)
                    and re.search(r'процедур|оформ|заявк|порядок|\bкак\s+(?:это|вс[её]|у\s+вас)\b|'
                                  r'^\s*как\s+происходит\s*$', part, re.I)
                    and not re.search(r'как\s+долго|сколько\s+(?:по\s+)?времени|'
                                      r'биос|bios|удалени\w*\s+прилож|алгоритм|сверлен|крепить|проводов', part, re.I)):
                kinds.add('process');query_ids.append(message.get('id', ''))
            if (re.search(capability_pattern, part, re.I)
                    and not re.search(r'купить|привез|достав|детал|креп[её]ж|материал|схем|инструкц|выбрать|найти|гарант|'
                                      r'точно|100\s*%|за\s+один|вс[её]\s+почин', part, re.I)):
                kinds.add('capability');query_ids.append(message.get('id', ''))
        if query_ids and message.get('body', '').strip() == '?':
            query_ids.append(message.get('id', ''))
    if not kinds:
        return None
    query_ids = list(dict.fromkeys(query_ids));work_ids = list(dict.fromkeys(work_ids))
    if any(not mid or sum(m.get('id') == mid for m in current) != 1 for mid in query_ids + work_ids):
        return None
    return dict(kind='_and_'.join(sorted(kinds)), questioner='client', respondent='service',
                query_message_ids=query_ids, work_message_ids=work_ids,
                query_quotes=[m['body'] for m in tail if m.get('id') in query_ids],
                source='literal_current_client_question_and_work', independent_model_understanding=False,
                service_execution_verified=False, appointment_confirmed=False,
                planned_service_question_is_client_goal=False)


outgoing_reply_observed = assistant_prices.outgoing_reply_observed


def first_reply_required(messages):
    return not any(outgoing_reply_observed(row)
                   for row in assistant_prices.current_enquiry_messages(messages))


def _current_client_question_rows(messages):
    """Only the current delivered client turn can ask a new question."""
    turn = []
    for message in reversed(assistant_prices.current_enquiry_messages(messages)):
        delivery = str(message.get('delivery_status') or message.get('delivery') or '').lower()
        unavailable = message.get('out_pending') or delivery in ('failed', 'pending', 'queued', 'sending', 'error', 'cancelled', 'canceled')
        if outgoing_reply_observed(message):
            break
        if (contact_facts._client_intent_message(message) and not unavailable
                and message.get('role') not in ('system', 'assistant')
                and message.get('speaker_role', 'client') == 'client'):
            turn.append(message)
            literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', str(message.get('body') or ''))
            if re.search(r'\bнов(?:ая\s+заявка|ый\s+заказ|ое\s+обращение)\b', literal, re.I):
                break
    return list(reversed(turn))


def _current_client_question_text(messages):
    return ' '.join(str(m.get('body') or m.get('text') or '')
                    for m in _current_client_question_rows(messages)).casefold().replace('ё', 'е')


def _assembly_diagram_answer(messages, service):
    """Answer a current question about an accepted diagram and its limits."""
    if [item['id'] for item in service['items']] != ['furniture']:
        return ''
    import research_vision

    turn = _current_client_question_rows(messages)
    images = [observation for row in turn if (observation := research_vision.qualification_observation(row))]
    if len(images) != 1 or images[0].get('content_kind') != 'assembly_diagram' or not images[0].get('instructions'):
        return ''
    text = ' '.join(str(row.get('body') or row.get('text') or '') for row in turn).casefold().replace('ё', 'е')
    if re.search(r'[«»“”"]|\b(?:сказал\w*|спросил\w*|не\s+(?:спрашива\w*|прос\w*))\b', text):
        return ''
    questions = re.findall(r'[^.!?;\n]+\?', text)
    scheme, inventory = False, False
    for clause in questions:
        if assistant_prices.asks(clause) or re.search(r'\b(?:когда|приед\w*|выезд|привез\w*|возьм\w*)\b', clause):
            return ''
        if re.search(r'\bэто\s+(?:схем|инструкци)\w*|\b(?:схем|инструкци)\w*[^?]{0,24}\s+или\s+', clause):
            scheme = True
        elif (re.search(r'\b(?:по\s+(?:ней|схеме|фото)\s+)?(?:можно\s+(?:ли\s+)?(?:понять|проверить|сказать)|видно\s+ли)\b', clause)
              and re.search(r'комплект|все\s+ли\s+детал|все\s+детал\w*[^?]{0,50}\b(?:есть|на месте|в коробке)\b', clause)):
            inventory = True
        else:
            return ''
    if inventory:
        return 'На изображении схема сборки. По ней нельзя проверить комплектность коробки.'
    return 'На изображении схема сборки.' if scheme else ''


def diagnostic_continuation_question(messages, known):
    """A question about continued-work billing never authorizes that work."""
    if known.get('direction') not in ('bt', 'kp'):
        return None
    rows = _current_client_question_rows(messages)
    text = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', ' '.join(
        str(m.get('body') or m.get('text') or '') for m in rows)).casefold().replace('ё', 'е')
    if re.search(r'невозмож\w*|невыгод|нецелесообраз|неремонтопригод|не\s+подлежит\s+ремонту|'
                 r'не\s+(?:получится|сможете|сможет)', text):
        return None
    for clause in re.findall(r'[^.!?;\n]+[.!?;\n]?', text):
        if (not clause.rstrip().endswith('?') or not re.search(r'\bдиагностик\w*', clause)
                or not re.search(r'оплач|плат|стоим|бесплат|отдельн|доплат', clause)
                or re.search(r'\b(?:сосед\w*|мастер\w*|сотрудник\w*|оператор\w*|специалист\w*)'
                             r'[^.!?]{0,45}(?:сказ|писа|ответ|спрос|предлож)|'
                             r'не\s+(?:спрашива\w*|интересует)|друг(?:ой|ого)\s+(?:заказ|мастер|прибор)', clause)
                or re.search(r'\bне\s+(?:буду|будем|соглашусь|согласимся|закажу|закажем|продолжим)\b', clause)):
            continue
        continued = re.search(r'\bпри\s+(?:продолжении|выполнении|оказании)\s+(?:работ|услуг)\b', clause)
        conditional = re.search(
            r'\b(?:если|когда)\b[^.!?;\n]{0,75}\b'
            r'(?:соглашусь|согласимся|закажу|закажем|продолжим|буду\s+делать|будем\s+делать)'
            r'\b[^.!?;\n]{0,35}\b(?:ремонт|работ)\w*', clause)
        if continued or conditional:
            return dict(message_ids=[m.get('id', '') for m in rows], quote=clause.strip(),
                        source='current_delivered_client_question',
                        repair_consent=False, execution_verified=False)
    return None


def contact_collection_deferred(messages):
    """A current contact deferral does not cancel the price discussion."""
    text = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', _current_client_question_text(messages))
    for clause in re.split(r'[.!?;\n]+', text):
        if (re.search(r'\b(?:если|сосед\w*|сказал\w*|написал\w*|спросил\w*)\b', clause)
                or re.search(r'номер\s+(?:модел|дом|квартир|заказ|заявк|карт[аы])', clause)):
            continue
        contact = r'(?:номер\w*|телефон\w*|контакт\w*)'
        delay = r'(?:не\s+(?:хочу|буду)\s+(?:оставлять|давать|сообщать)|не\s+(?:дам|оставлю|сообщу))'
        if (re.search(contact + r'[^.!?;]{0,30}' + delay + r'|' + delay + r'[^.!?;]{0,25}' + contact, clause)
                or re.search(contact + r'[^.!?;]{0,25}\b(?:потом|позже)\b|'
                             r'\b(?:потом|позже)\b[^.!?;]{0,25}(?:дам|сообщу|оставлю)[^.!?;]{0,15}' + contact, clause)):
            return True
    return False


DATA_PRESERVATION_REPLY = ('Сохранность файлов заранее гарантировать не могу. '
                           'Перед работой нужно проверить причину сбоя и согласовать действия с данными.')


def office_data_preservation_question(messages):
    """A current file-safety question about an observed Office fault.

    This does not diagnose the problem, approve deleting data or request a
    backup/reinstallation. Service, territory and action guards still apply.
    """
    current = assistant_prices.current_enquiry_messages(messages)
    clients = [m for m in current if contact_facts._client_intent_message(m)
               and m.get('speaker_role', 'client') == 'client'
               and m.get('role') not in ('system', 'assistant')
               and not m.get('out_pending')
               and str(m.get('delivery_status') or m.get('delivery') or '').lower()
               not in ('failed', 'error', 'pending', 'queued', 'sending', 'cancelled', 'canceled')]
    starts = [i for i, m in enumerate(clients) if re.match(
        r'\s*(?:новая\s+заявка|новый\s+заказ|по\s+другому\s+вопросу)\b', m.get('body', ''), re.I)]
    if starts:
        clients = clients[starts[-1]:]
    context = '\n'.join(str(m.get('body') or '') for m in clients)
    if not assistant_catalog.ordinary_office_work(context):
        return False
    for message in _current_client_question_rows(current):
        if message not in clients:
            continue
        text = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', str(message.get('body') or ''))
        for clause in re.findall(r'[^.!?;\n]+[.!?;\n]?', text):
            if (not clause.rstrip().endswith('?')
                    or re.search(r'\b(?:сказал\w*|написал\w*|спросил\w*|сосед\w*)\b|'
                                 r'не\s+(?:спрашива\w*|интересует|прошу)', clause, re.I)):
                continue
            if re.search(r'(?:без\s+потер\w*|сохран\w*|не\s+потер\w*|не\s+пропад\w*)[^.!?]{0,45}'
                         r'(?:файл\w*|данн\w*|документ\w*)|'
                         r'(?:файл\w*|данн\w*|документ\w*)[^.!?]{0,45}'
                         r'(?:сохран\w*|не\s+потер\w*|не\s+пропад\w*)', clause, re.I):
                return True
    return False


def _direct_modal_supply_request(text, parts):
    """Second-person procurement requests need not end in a question mark.

    Bind the purchase verb to concrete parts in the same short clause. A
    nearby shortage alone cannot turn buying an entire device into supply.
    This grants only an uncertainty disclosure, never an inventory fact.
    """
    verb = r'(?:купить|докупить|привезти|доставить|захватить|взять)'
    modal = r'(?:вы\s+)?(?:можете|сможете)'
    item = r'(?:(?:эти|нужные|недостающие)\s+)?' + parts
    patterns = (
        modal + r'\s+' + verb + r'\s+' + item,
        item + r'\s+(?:вы\s+)?' + verb + r'\s+' + modal,
        verb + r'\s+' + item + r'\s+' + modal,
        modal + r'\s+' + item + r'\s+' + verb,
        verb + r'\s+' + modal + r'\s+' + item,
    )
    literal = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', text)
    for sentence in re.split(r'[.!?;\n]+', literal):
        if re.search(r'\b(?:если|допустим|например|вдруг|сосед\w*|сказал\w*|'
                     r'написа\w*|спросил\w*|сообщил\w*|утвержда\w*)\b', sentence):
            continue
        for clause in re.split(r'[:,]', sentence):
            if re.search(r'\bне\s+(?:можете|сможете|купить|докупить|привезти|'
                         r'доставить|захватить|взять)\b', clause):
                continue
            if any(re.search(r'\b' + pattern + r'\b', clause) for pattern in patterns):
                return True
    return False


def service_expectation_questions(messages):
    """Read the current client turn, including a separately sent question mark.

    Asking about our inventory is different from reporting the client's parts.
    The answer defers an unverified outcome, never changes service acceptance.
    """
    text = _current_client_question_text(messages)
    # An explicitly attributed question from another worker is not the
    # current client's request about our stock. Keep any direct question
    # after that quote, and un-attributed/client-owned quoted wording.
    text = re.sub(
        r'(\b(?:другой\s+)?(?:мастер|специалист|сосед)\w*[^.!?\n«“"]{0,30}'
        r'\b(?:спросил|сказал|написал|ответил)\w*\s*[:,-]?\s*)'
        r'(?:«[^»]*»|“[^”]*”|"[^"\n]*")', r'\1[чужая цитата]', text)
    text = re.sub(r'\bне\s+(?:спрашива\w*|прос\w*|надо|нужно)[^.!?;\n]*(?:[.!?;\n]|$)', ' ', text)
    parts = r'(?:запчаст\w*|детал\w*|материал\w*|комплектующ\w*|крепеж\w*|креплен\w*|саморез\w*|шуруп\w*|дюбел\w*|провод\w*|кабел\w*|розетк\w*|герметик\w*|направляющ\w*)'
    turn = _current_client_question_rows(messages)
    staff_anchor = ''
    if turn:
        current = assistant_prices.current_enquiry_messages(messages)
        index = next((i for i,m in enumerate(current) if m is turn[0]), None)
        previous = contact_facts.preceding_staff_speech(current, index) if index is not None else None
        new_enquiry = any(re.search(r'\bнов(?:ая\s+заявка|ый\s+заказ|ое\s+обращение)\b',
                                   re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', str(m.get('body') or '')), re.I) for m in turn)
        if previous and not new_enquiry:
            question = previous[1]
            delivered = str(question.get('delivery_status') or question.get('delivery') or '').lower() in ('sent', 'delivered', 'read')
            body = str(question.get('body') or '').casefold().replace('ё', 'е')
            if delivered and body.rstrip().endswith('?') and re.search(parts, body):
                staff_anchor = body
    inventory = bool(re.search(
        r'(?:у\s+вас|у\s+мастера|с\s+собой)[^.!?]{0,65}' + parts + r'|'
        + parts + r'[^.!?]{0,65}(?:у\s+вас|у\s+мастера|с\s+собой|\b(?:привезете|возьмете)\b)|'
        r'\b(?:привезете|возьмете|купите)\b[^.!?]{0,55}' + parts, text))
    inventory |= _direct_modal_supply_request(text, parts)
    # A deictic question can refer to parts named in the preceding sentence.
    # It is a question about our supply, not evidence of an actual shortage.
    clauses = re.findall(r'[^.!?;\n]+[.!?;\n]?', text)
    parts_sale = False
    for index, clause in enumerate(clauses):
        if (not clause.rstrip().endswith('?')
                or re.search(r'\b(?:сказал\w*|написал\w*|спросил\w*|сосед\w*)\b|'
                             r'\bне\s+(?:спрашива\w*|прос\w*|надо|нужно)', clause)):
            continue
        infinitive = r'(?:купить|докупить|привезти|доставить|захватить|взять)'
        procurement_object = (r'(?:(?:недостающ\w*|нужн\w*|эти)\s+)?' + parts
                              + r'|(?:это|их|его|недостающее)')
        supply = re.search(r'\b(?:привезете|возьмете|купите|докупите|доставите|захватите)\b|'
                           r'\b(?:сможете|можете)\s+' + infinitive + r'\b|'
                           r'\b' + infinitive + r'\s+(?:сможете|можете)\b|'
                           r'\b' + infinitive + r'\s+(?:' + procurement_object + r')'
                           r'\s+(?:вы\s+)?(?:сможете|можете)\b', clause)
        # The client may address our service through its worker: «мастер
        # привезёт свой?». This asks about unverified supply, not an actual
        # shortage or a promise. A named different worker remains foreign.
        if not supply and not re.search(
                r'\b(?:другой|мой|свой|соседск\w*|частный|прежний)\s+(?:мастер|специалист)\b', clause):
            supply = re.search(
                r'\b(?:ваш\s+)?(?:мастер|специалист)\s+'
                r'(?:(?:привезет|возьмет|купит|докупит|доставит|захватит)\b|'
                r'(?:сможет|может)\s+' + infinitive + r'\b)', clause)
            sale = re.search(
                r'\b(?:ваш\s+)?(?:мастер|специалист)\s+'
                r'(?:(?:сможет|может)\s+продать|продаст)\s+'
                r'(?:(?:свои\s+)?' + parts + r'\b|свои(?=\s*(?:или\b|\?)))', clause)
            parts_sale |= bool(sale and re.search(parts, clause))
        deictic = re.search(r'\b(?:это|их|его|недостающее)\b', clause)
        anchor = re.search(parts, ' '.join(clauses[max(0,index-2):index+1]))
        if not anchor and staff_anchor and re.search(r'^\s*(?:нет|нету|не\s+подготовлены)\b', text):
            anchor = re.search(parts, staff_anchor)
        other_object = re.search(r'\b(?:телевизор|принтер|ноутбук|холодильник|шкаф|комод|диван|кровать)\w*', clause)
        if supply and anchor and (deictic or re.search(infinitive, clause) or clause.rstrip().endswith('?')) and (not other_object or re.search(parts, clause)):
            inventory = True
    on_site = bool(re.search(
        r'(?:сдела\w*|почин\w*|ремонт\w*|выполн\w*)[^.!?]{0,50}(?:на\s+месте|дома\s+сразу|за\s+один\s+(?:выезд|визит))|'
        r'(?:на\s+месте|дома\s+сразу|за\s+один\s+(?:выезд|визит))[^.!?]{0,50}(?:сдела\w*|почин\w*|ремонт\w*|выполн\w*)|'
        r'(?:точно|100\s*%|гарантируете)[^.!?]{0,35}(?:сдела\w*|почин\w*|устран\w*)', text))
    replies = []
    capability = bool(re.search(r'\b(?:возьметесь|возьмитесь)\s*[?!.]*\s*$|'
                                r'\b(?:возьметесь|возьмитесь)\s+за\s+(?:работ|замен|ремонт|установ|сборк|проводк)\w*', text))
    procurement = re.search(r'\b(?:привезти|доставить|купить|докупить|закупк\w*|доставк\w*)\b', text)
    if capability and not inventory and not parts_sale and not procurement:
        # Only a supported service consumes this reply. Agreeing to take
        # the named job is not an inventory or completed-outcome promise.
        replies.append('Да, помогу.')
    if parts_sale:
        replies.append('Наличие подходящего крепежа у мастера заранее подтвердить не могу.')
    elif inventory:
        replies.append('По материалам смогу сориентировать после осмотра.')
    if on_site:
        replies.append('Возможность ремонта на месте определю после осмотра.')
    if office_data_preservation_question(messages):
        replies.append(DATA_PRESERVATION_REPLY)
    return replies


def service_expectation_violations(reply):
    """Do not turn an intake answer into an inventory or outcome promise."""
    text = str(reply or '').casefold().replace('ё', 'е')
    parts = r'(?:запчаст\w*|детал\w*|материал\w*|комплектующ\w*|крепеж\w*|креплен\w*|саморез\w*|шуруп\w*|дюбел\w*|провод\w*|кабел\w*|розетк\w*|герметик\w*|направляющ\w*)'
    errors = []
    for clause in re.split(r'[.!?;\n]+|\bно\b', text):
        negated = re.search(r'не\s+(?:обещаю|гарантирую|подтверждаю)|не\s+могу\s+(?:обещать|гарантировать|подтвердить)', clause)
        if negated:
            continue
        if re.search(r'(?:(?:постараюсь|попробую)\s+(?:взять|привезти|захватить|купить|докупить)|привезу|возьму|захвачу|закуплю|куплю|докуплю)[^.!?]{0,55}' + parts + r'|'
                     + parts + r'[^.!?]{0,55}(?:привезу|возьму|захвачу|закуплю|куплю|докуплю)|'
                     r'(?:все\s+есть|есть\s+все|у\s+меня\s+есть|у\s+мастера\s+есть|в\s+наличии|будут\s+с\s+собой|будет\s+с\s+собой)[^.!?]{0,55}' + parts + r'|'
                     + parts + r'[^.!?]{0,55}(?:есть\s+у\s+меня|у\s+меня\s+есть|в\s+наличии|будут\s+с\s+собой)', clause):
            errors.append('unconfirmed_materials_promise')
        if re.search(r'\bвсе\s+' + parts + r'[^.!?]{0,25}\bесть\b|'
                     r'\b(?:шланг\w*|подводк\w*|детал\w*|комплектующ\w*)[^.!?]{0,35}'
                     r'\bточно\s+(?:подход\w*|совместим\w*)', clause):
            errors.append('unconfirmed_materials_promise')
        if re.search(r'(?:точно|обязательно|100\s*%|гарантирую)[^.!?]{0,50}(?:сдела\w*|почин\w*|отремонтир\w*|устран\w*)|'
                     r'(?:сделаю|починю|отремонтирую|устраню)[^.!?]{0,50}(?:на\s+месте|за\s+один\s+(?:выезд|визит)|сразу)|'
                     r'(?:на\s+месте|за\s+один\s+(?:выезд|визит))[^.!?]{0,50}(?:сделаю|починю|отремонтирую|устраню)', clause):
            errors.append('unconfirmed_repair_outcome')
    return list(dict.fromkeys(errors))


def _client_requested_callback(messages):
    """Explicit operator-call preference; no executed call or visit evidence."""
    active = None
    last_client_id = None
    for message in messages:
        if message.get('direction') == 'out':
            if (message.get('sender_type') in ('operator', 'employee', 'human')
                    and message.get('delivery_status') in ('sent', 'delivered', 'read')
                    and not message.get('out_pending')
                    and '?' in str(message.get('body') or '')):
                active = None
            continue
        if (message.get('direction') != 'in'
                or message.get('sender_type') in ('operator', 'employee', 'human', 'bot', 'assistant', 'system', 'avito')):
            continue
        body = str(message.get('body') or message.get('text') or '')
        last_client_id = message.get('id', '')
        if active and re.fullmatch(r'\s*(?:хорошо|ок|понял[аи]?|спасибо|благодарю|да|👍|🙏|🙂)[.!\s]*', body, re.I):
            continue
        active = None
        text = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', body)
        # An age assertion unparsed by the canonical age guard must not gain
        # this shortcut. Keep the ordinary qualification path, without
        # guessing an age or changing the shared age parser.
        if (re.search(r'\bмне\s*\d+\s*(?:лет|год)', text, re.I)
                and qualification_state.client_age([message])['status'] == 'missing'):
            continue
        if assistant_prices.asks(body) or re.search(r'\bтеперь\b|\bдополнительно\b|\bеще\s+нужно\b', text, re.I):
            continue
        for match in re.finditer(r'\b(?:позвоните|перезвоните|наберите|звоните)\b', text, re.I):
            before = re.split(r'[.!?\n]', text[:match.start()])[-1]
            if (re.search(r'\bне(?:\s+(?:надо|нужно))?\s*$', before, re.I)
                    or re.search(r'\b(?:мама|отец|мастер|сотрудник)\b.{0,50}(?:сказал|попросил|просил|написал)', before, re.I)):
                continue
            request_tail = re.split(r'[.!?;\n]', text[match.end():], maxsplit=1)[0]
            if re.search(r'\b(?:перед|до)\s+(?:выезд\w*|приезд\w*|приход\w*|визит\w*)|'
                         r'\b(?:когда|как)\s+(?:вы\s+)?(?:подъед\w*|приед\w*|будете\s+подъезж\w*)', request_tail, re.I):
                continue  # Reminder before a visit, not a new operator callback.
            interval = re.search(r'\bчерез\s+(?:пол\s*часа|полчаса|(\d{1,3})\s*минут\w*)', text[match.end():], re.I)
            minutes = (int(interval[1]) if interval and interval[1] else 30) if interval else None
            if minutes is not None and not 0 < minutes <= 180:
                continue
            preferred = None
            if minutes is not None:
                from datetime import datetime, timedelta, timezone
                try:
                    anchor = datetime.fromisoformat(str(message.get('created_at') or '').replace('Z', '+00:00'))
                    if anchor.tzinfo is not None and anchor.utcoffset() is not None:
                        preferred = (anchor + timedelta(minutes=minutes)).astimezone(timezone.utc).isoformat()
                except (ValueError, TypeError, OverflowError):
                    pass
            active = dict(message_id=message.get('id', ''), quote=body,
                          source='explicit_client_callback_request', requested_actor='operator',
                          after_minutes=minutes, source_created_at=message.get('created_at', ''),
                          preferred_at=preferred, time_is_preference_only=True,
                          visit_time_confirmed=False, execution_confirmed=False)
            break
    return dict(active, latest_is_request=active['message_id'] == last_client_id) if active else None



def photo_work_unspecified(messages, known, facts=None):
    """A viewed image and a pointer/capability phrase do not order an operation.

    This bounded MNC clarification does not classify image contents or grant
    admission. Media trust must already be established by personal_media.apply.
    """
    if known.get('direction') != 'mnc' or not messages:
        return None
    current = assistant_prices.current_enquiry_messages(messages)
    clients = [m for m in current if m.get('direction') == 'in'
               and m.get('sender_type', 'client') in ('client', '')]
    if not clients:
        return None
    latest = clients[-1]
    if (not latest.get('media_reviewed') or latest.get('unread_media')
            or not latest.get('reviewable_image') or not latest.get('media_signature')):
        return None
    # Do not replace specialized device-code/label/contact reasoning.
    if latest.get('media_observation', {}).get('content_kind') not in (None, 'product_photo', 'other'):
        return None
    fragments = r'(?:здравствуйте|добрый\s+(?:день|вечер)|доброе\s+утро|привет|спасибо|'
    fragments += r'вот(?:\s+(?:так|фото|этот\s+участок))?|это\s+оно|сможете\s+помочь|можете\s+помочь|'
    fragments += r'что\s+с\s+этим\s+делать|проводка|провода|розетка|выключатель|материалы\s+есть)'
    for message in clients:
        body = str(message.get('body') or '').casefold().replace('ё', 'е')
        prefix = current[:current.index(message) + 1]
        if _photo_upload_unblock(prefix) or _photo_address_only(body, known, facts or {}):
            continue
        if not re.fullmatch(r'[\s!?. ,:;]*' + r'(?:' + fragments + r'[\s!?. ,:;]*)*', body):
            return None  # A named operation/condition must retain its own rules.
    observation = latest.get('media_observation') or {}
    return dict(message_id=latest['id'], signature=latest['media_signature'],
                source_rule='DOC-L0700', requested_action='unspecified',
                observed_subject=dict(content_kind=observation.get('content_kind') or 'unspecified',
                                      device_kind=observation.get('device_kind') or None),
                client_literal_subject_context='\n'.join(str(m.get('body') or '') for m in clients))


def photo_unobserved_subject_claims(value, subject, client_literal):
    """A recognized device noun needs reviewed metadata or literal client text.

    This is a bounded extra guard for photo-only turns, not an image classifier.
    An advertisement, staff suggestion or an older image never supplies the
    current image's subject. Unknown nouns still require the manual review.
    """
    names = {
        'wardrobe': r'\b(?:шкаф|гардероб)\w*',
        'bed': r'\b(?:кроват|изголов)\w*',
        'dresser': r'\b(?:комод|тумб)\w*',
        'oven': r'\bдухов\w*',
        'tv': r'\bтелевиз\w*|\bтв\b',
        'monitor': r'\bмонитор\w*',
        'pc': r'\b(?:компьютер|ноутбук|моноблок)\w*|\bпк\b',
        'pc_component': r'\bвидеокарт\w*|\bматеринск\w*\s+плат\w*|\bпроцессор\w*',
        'ethernet_cable': r'\bвит\w*\s+пар\w*|\bоптоволок\w*|\b(?:сетев\w*|интернет)\s*кабел\w*',
        'wiring': r'\bпровод(?:к\w*|а|ов|ами|ы)?\b|\bраспаяч\w*',
    }
    for kind, pattern in names.items():
        if (re.search(pattern, str(value or ''), re.I)
                and subject.get('device_kind') != kind
                and not re.search(pattern, str(client_literal or ''), re.I)):
            return ['photo_subject_not_observed']
    return []


def photo_unspecified_work_claims(value, *, as_goal=False):
    """Reject an asserted operation/diagnosis that the photo-only turn lacks."""
    for clause in re.split(r'[.!?;\n]+|\bно\b|,\s*(?=(?:клиент|нужно|требуется|мастер|я|вероятно|возможно|предположительно|скорее)\b)', str(value or '').casefold().replace('ё', 'е')):
        if re.search(r'не\s+(?:указан|назван|заказан|подтвержден|просит|требует|доказан|доказывает|определяет|показывает|устанавливает)|'
                     r'нет\s+(?:запроса|данных|подтверждения)|неизвест|не\s+установлен', clause):
            continue
        # A tentative repair goal is still an inference. The typed proof
        # requested_action=unspecified must agree with the free-form review,
        # including claims about why the client sent the image.
        operation = r'ремонт\w*|почин\w*|собра\w*|сборк\w*|разобра\w*|разборк\w*|установ\w*|навес\w*|реставрац\w*'
        if as_goal and re.search(r'\b(?:' + operation + r')', clause):
            return ['photo_unstated_work_or_diagnosis']
        if re.search(r'\bдля\s+(?:(?:его|е[её]|дальнейш\w*|последующ\w*)\s+)?(?:' + operation + r')', clause):
            return ['photo_unstated_work_or_diagnosis']
        if re.search(r'(?:сообщить|сообщает|описать|описывает|выяснить|определить)[^.!?;]{0,30}'
                     r'(?:проблем|поломк|неисправ)|'
                     r'(?:просит|заказ\w*|хочет|нужен|нужна|требуется|вероятно|возможно|предположительно|скорее)[^.!?;]{0,65}'
                     r'(?:ремонт\w*|почин\w*|собра\w*|сборк\w*|разборк\w*|установ\w*|навес\w*|реставрац\w*|поломк\w*|неисправ\w*)', clause):
            return ['photo_unstated_work_or_diagnosis']
        if re.search(r'поменя\w*|замен\w*|распаяч\w*|распайк\w*|отделк\w*|'
                     r'высоковольт\w*|промышленн\w*\s+напряж|коротк\w*\s+замыкан|'
                     r'вс[ею]\s+проводк\w*|\bдиагноз\b|точно\s+неисправ', clause):
            return ['photo_unstated_work_or_diagnosis']
    return []



def furniture_logistics_state(messages, known):
    """Separate a client's furniture pickup request from assembly and own travel."""
    if known.get('direction') != 'mnc':
        return None
    current = assistant_prices.current_enquiry_messages(messages)
    clients = [m for m in current if m.get('direction') == 'in'
               and m.get('sender_type', 'client') in ('client', '')]
    if not clients:
        return None
    def plain(body):
        return re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', body).casefold().replace('ё', 'е')
    clean = [plain(m.get('body', '')) for m in clients]
    whole = ' '.join(clean)
    furniture = bool(re.search(r'шкаф|комод|мебел', whole))
    if not furniture:
        return None
    defer = r'вернемся\s+к\s+разговору[^.!?]{0,35}(?:позже|позднее|потом)|перенесем\s+разговор|обсудим\s+(?:позже|позднее|потом)'
    waiting = None
    for message in clients:
        body = plain(message.get('body', '')).strip()
        photo_question = _photo_submission_permission(body)
        callback = _client_requested_callback([message])
        substantive = (re.search(r'\?|сколько|стоим|цен[аыуе]|теперь\s+нуж|по\s+другому\s+вопросу', body)
                       and not (photo_question or callback))
        if re.search(defer, body) and not substantive:
            waiting = message
        elif not (re.fullmatch(r'\s*(?:(?:хорошо|понятно|спасибо|ладно|ок|благодарю)[,!\s.)🙂]*)+', body)
                  or photo_question or callback):
            waiting = None
    if waiting:
        return dict(kind='deferred', evidence_ids=[waiting.get('id', '')],
                    latest_is_defer=waiting is clients[-1])
    job = re.sub(r'\bсборк\w*\s+не\s+нуж\w*|не\s+нуж\w*\s+сборк\w*', '', whole)
    assembly = bool(re.search(r'собра\w*|собер\w*|сборк\w*', job))
    turn = _current_client_question_rows(current)
    pickup = r'\b(?:забрат\w*|забер\w*|принес\w*|принест\w*|перевез\w*|перевоз\w*|доставк\w*|доставит\w*)'
    evidence = []
    for message in turn:
        for clause in re.split(r'[.!;\n]+', plain(message.get('body', ''))):
            if not re.search(pickup, clause):
                continue
            if re.search(r'\b(?:сам|сама|сами|магазин|продавец|курьер)\b|не\s+нуж\w*|не\s+надо|не\s+требуется|доставк\w*\s+перенес', clause):
                continue
            if not re.search(r'\?|помоч|смож|может|можно|желател|чтобы|если|нужно|требуется|сколько|цен|стоим|собрать|сборка', clause):
                continue
            evidence.append(message.get('id', ''))
    if not evidence:
        return None
    return dict(kind='pickup', assembly=assembly, mandatory=bool(re.search(r'только\s+если', ' '.join(plain(m.get('body', '')) for m in turn))), evidence_ids=list(dict.fromkeys(evidence)),
                source_ids=['DOC-L0323', 'DOC-L0453'])


def pickup_delivery_violations(reply):
    text = str(reply or '').casefold().replace('ё', 'е')
    errors = []
    if re.search(r'\b(?:заберу|заберем|привезу|доставлю|доставим|перевезу|принесу|перенесу)\b', text):
        errors.append('unconfirmed_pickup_delivery_promise')
    for clause in re.split(r'[.!?;\n]+', text):
        if (re.search(r'машин|автомобил', clause) and re.search(r'\b(?:есть|нет|будет|приедет)\b', clause)
                and not re.search(r'не\s+(?:знаю|подтверждаю)|неизвест|не\s+установлен', clause)):
            errors.append('unverified_vehicle_fact')
    if re.search(r'собер\w*[^.!?]{0,55}(?:за\s+один\s+(?:визит|выезд)|точно)|точно[^.!?]{0,40}собер', text):
        errors.append('unconfirmed_repair_outcome')
    return errors



def conditional_claim_followup(messages, known):
    """Prepare the Jivo obligation without trusting an unverified claim flag."""
    request_id = str(known.get('crm_request_id') or '')
    if (known.get('channel') != 'jivo' or known.get('direction') not in ('kp', 'bt', 'mnc')
            or not re.fullmatch(r'[1-9]\d{0,19}', request_id) or not messages):
        return None
    message = messages[-1]
    if (message.get('direction') != 'in' or not message.get('id')
            or message.get('sender_type') in ('operator', 'assistant', 'bot', 'employee', 'staff', 'system', 'avito')
            or message.get('role') == 'assistant'):
        return None
    return dict(kind='notify_existing_claim_reply', direction=known['direction'], chat_kind='claims',
                crm_request_id=request_id, message_id=message['id'],
                event_key='jivo-claim-reply:' + request_id + ':' + message['id'],
                text=request_id + ': Клиент ответил в диалоге на авито',
                rule_id='OWNER-JIVO-CLAIM-REPLY-20261023',
                requires=['verified_existing_claim', 'reviewed_single_action_permission'],
                existing_claim_verified=False, execution_allowed=False)


def caller_id_save_request(messages, facts):
    """Retain a literal save-number purpose, never authority to make a call.

    A delivered staff offer is only an offer. A client's report of seeing the
    number is only that report; neither is a telephony execution receipt.
    """
    current = assistant_prices.current_enquiry_messages(messages)
    active = None
    client_messages = []
    timing = []
    save_offer_pending = False
    visibility_question = False
    for message in current:
        body = str(message.get('body') or '')
        text = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', body)
        if message.get('direction') == 'out':
            if (message.get('sender_type', 'operator') in ('operator', 'employee', 'human', '')
                    and not message.get('out_pending')
                    and message.get('delivery_status') not in ('pending', 'queued', 'sending', 'failed', 'error', 'cancelled', 'canceled')):
                visibility_question = bool(
                    re.fullmatch(r'\s*(?:увидели|видите)\s+(?:мой\s+)?номер\s*\?[\s!]*', text, re.I)
                    or (save_offer_pending and re.fullmatch(r'\s*(?:увидели|видите)\s*\?[\s!]*', text, re.I)))
                save_offer_pending = bool(
                    re.search(r'\b(?:дозвон\s+сделаю|позвоню|наберу)\b', text, re.I)
                    and re.search(r'\b(?:запишите|сохраните)\b', text, re.I)
                    and not re.search(r'\b(?:не|если|раньше)\b|сказал|написал', text, re.I))
                if (not active and re.search(r'\b(?:дозвон\s+сделаю|позвоню|наберу)\b', text, re.I)
                        and re.search(r'\b(?:запишите|сохраните)\b', text, re.I)
                        and not re.search(r'\b(?:не|если|раньше)\b|сказал|написал', text, re.I)):
                    active = dict(message_id=message.get('id', ''), quote=body,
                                  intent_source='staff_offer', client_accepted=False)
            continue
        if (message.get('direction') != 'in' or message.get('sender_type', 'client')
                not in ('client', 'customer', 'user', 'contact', 'lead', '')):
            continue
        client_messages.append(message)
        if (not re.search(r'\b(?:если|сказал\w*|написал\w*)\b', text, re.I)
                and re.search(r'^\s*(?:новая\s+заявка|новый\s+заказ|по\s+другому\s+вопросу)\b', text, re.I)):
            active = None
            timing = []
            save_offer_pending = False
            visibility_question = False
        if re.search(r'(?:звон|набер)[^.!?\n]{0,35}(?:после|до|через|утром|вечером|завтра)|'
                     r'\bне\s+(?:надо\s+)?(?:звон|набир)', text, re.I):
            timing.append(dict(message_id=message.get('id', ''), quote=body))
        report_or_condition = re.search(r'\b(?:сказал\w*|написал\w*|спросил\w*|раньше|если)\b', text, re.I)
        other_number = re.search(r'номер\s+(?:карт[ыыу]|заказ\w*|заявк\w*|модел\w*|дом\w*|квартир\w*)', text, re.I)
        if active and not report_or_condition:
            cancel = re.search(r'\b(?:не\s+(?:надо|нужно)\s+(?:звонить|сохранять|записывать)|'
                               r'не\s+звоните|не\s+набирайте|номер\s+не\s+нужен)\b', text, re.I)
            # Negated questions about completion do not establish visibility.
            visible = (not other_number and '?' not in text and
                       re.search(r'\b(?:вижу\s+ваш\s+номер|ваш\s+номер\s+вижу|'
                                 r'(?:ваш\s+)?номер\s+(?:сохранил[аи]?|записал[аи]?)|'
                                 r'(?:сохранил[аи]?|записал[аи]?)\s+(?:ваш\s+)?номер)\b', text, re.I)
                       and not re.search(r'\bне\s|неизвест', text, re.I))
            short_seen = bool(visibility_question and re.fullmatch(r'\s*да[.!\s]*', text, re.I))
            if cancel or visible or short_seen:
                active.update(status='cancelled' if cancel else 'client_reported_visible',
                              resolution=dict(message_id=message.get('id', ''), quote=body,
                                              source='client_message', independent_call_log=False))
            elif active['intent_source'] == 'staff_offer' and re.fullmatch(r'\s*(?:ок|хорошо|да)[.!\s]*', text, re.I):
                active['client_accepted'] = True
        if (not re.fullmatch(r'\s*(?:ок|хорошо|да|спасибо)[.!\s]*', text, re.I)
                or message.get('attachments') or message.get('voice_transcript')):
            save_offer_pending = False
        visibility_question = False
        if report_or_condition or other_number:
            continue
        # Elliptical "ваш" is bound only to this literal phone antecedent,
        # not to an unrelated number, device, address or quoted speaker.
        explicit_own = re.search(r'\bваш\s+(?:номер|телефон)\b|\b(?:номер|телефон)\s+ваш\b', text, re.I)
        ellipsis = (re.search(r'\bномер\b[^.!?\n]{0,90}\b(?:нужен|нужен\s+будет)\s+ваш\b', text, re.I))
        purpose = re.search(r'\b(?:сохранить|записать)\b|неизвестн\w*[^.!?\n]{0,35}блок|'
                            r'вызов[^.!?\n]{0,40}(?:в\s+блок|блокир)', text, re.I)
        if ((explicit_own or ellipsis) and purpose
                and not re.search(r'\bне\s+(?:нужен|хочу|буду|надо)|\bне\s+(?:сохран|запис)', text, re.I)):
            active = dict(message_id=message.get('id', ''), quote=body,
                          intent_source='client_request', client_accepted=True)
    if not active:
        return None
    contact = facts.get('contact_phone_to_use')
    verified = bool(contact and _callback_phone_usable(current, facts))
    contact_evidence = facts.get('evidence', {}).get('contact_phone_to_use') or {}
    latest = client_messages[-1] if client_messages else {}
    latest_text = str(latest.get('body') or '')
    contact_only = re.sub(r'[\s\d+()\-.]+', '', latest_text).casefold() in ('', 'этомой', 'мойномер', 'мойтелефон')
    latest_is_contact = bool(verified and contact_evidence.get('message_id') == latest.get('id') and contact_only)
    status = active.get('status') or ('operator_review' if verified else 'awaiting_contact')
    active.update(rule_id='OWNER-CALLER-ID-SAVE-CALLBACK-20261024', purpose='save_contractor_caller_id',
                  status=status, customer_contact_verified=verified,
                  contact_phone=contact if verified else None, contact_evidence=contact_evidence if verified else {},
                  timing_constraints=timing, recipient_review_required=True,
                  reply_due=(active['intent_source'] == 'client_request'
                             and status in ('awaiting_contact', 'operator_review')
                             and (latest.get('id') == active['message_id'] or latest_is_contact)),
                  suggested_operator_phrase='Пару минут, наберу вам',
                  requires_manual_call=True, execution_available=False, execution_allowed=False,
                  call_executed=False, contractor_phone_shared=False, visit_confirmed=False)
    return active


def caller_id_call_violations(value, plan):
    """No unexecutable promise or unobserved completed call in free wording."""
    if not plan:
        return []
    for clause in re.split(r'[.!?;\n]+', re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', '', str(value))):
        for claim in re.finditer(r'\b(?:наберу|позвоню|перезвоню|позвоним|перезвоним|набер[её]м)\b|'
                                 r'\b(?:сейчас|уже)\s+звоню\b', clause, re.I):
            if not re.search(r'\bне\s+$|\bне\s+обещаю\s*,?\s*(?:что\s+)?$', clause[:claim.start()], re.I):
                return ['caller_id_call_not_executable']
        for claim in re.finditer(r'\b(?:я|мы)\s+(?:уже\s+)?(?:позвонил[аи]?|набрал[аи]?|дозвонил[аи]?сь)|'
                                 r'\bзвонок\s+(?:уже\s+)?(?:выполнен|соверш[её]н|провед[её]н)', clause, re.I):
            if re.search(r'\b(?:неизвестно|не\s+подтвержд\w*)\s*,?\s*(?:что\s*)?$', clause[:claim.start()], re.I):
                continue
            return ['caller_id_call_execution_not_observed']
    return []


def phone_exchange_request(messages, known, facts):
    """Literal current contact request; no inferred phone or performed call."""
    clients = [m for m in assistant_prices.current_enquiry_messages(messages)
               if m.get('direction') == 'in' and m.get('sender_type', 'client')
               in ('client', 'customer', 'user', 'contact', 'lead', '')]
    if not clients:
        return None
    message = clients[-1]
    body = str(message.get('body') or '')
    text = re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', body)
    if (re.search(r'\b(?:сказал|написал|спросил|раньше)\w*\b|\bесли\b', text, re.I)
            or re.search(r'номер\s+(?:карт[ыыу]|заказ\w*|заявк\w*|модел\w*|дом\w*|квартир\w*)', text, re.I)):
        return None
    verified = bool(facts.get('contact_phone_to_use') and not facts.get('phone_needs_confirmation'))
    kind = None
    own = re.search(r'\b(?:можно|дайте|подскажите|напишите|пришлите|скиньте|сообщите)\s*,?\s*'
                    r'(?:(?:пожалуйста|мне|ваш|свой)\s*,?\s+){0,3}(?:номер(?:\s+телефона)?|телефон)\b|'
                    r'\bваш\s+(?:номер(?:\s+телефона)?|телефон)\s*\?|'
                    r'\bконтактами\s+(?:поменяться|обменяться)\b', text, re.I)
    if own and not re.search(r'\bне\s+(?:надо|нужно|давайте|давать)\b|телефон\s+не\s+включ', text, re.I):
        kind = 'contractor_number_request'
    elif re.search(r'\b(?:можно|могу)\s+(?:вам\s+)?позвонить\b|\bпозвонить\s+вам\s+можно\b', text, re.I):
        kind = 'avito_call_request'
    previous = contact_facts.preceding_staff_speech(messages, messages.index(message))
    question = previous[1] if previous else {}
    contact_question = bool(re.search(r'(?:номер|телефон)', question.get('body', ''), re.I)
                            and re.search(r'остав|подскаж|напиш|сообщ|дайте', question.get('body', ''), re.I))
    if not kind and not verified and not assistant_prices.asks(text):
        for clause in re.split(r'[.!;\n]+', text):
            if '?' in clause:
                continue
            refusal = re.search(r'\bне\s+(?:даю|дам|буду\s+(?:давать|сообщать|оставлять)|'
                                r'хочу\s+(?:давать|сообщать|оставлять))\s+(?:(?:вам|свой)\s+){0,2}'
                                r'(?:номер\w*|телефон\w*)\b|'
                                r'\b(?:номер|телефон)\s+(?:вам\s+)?не\s+(?:дам|даю)\b|'
                                r'\b(?:приезжайте|подъезжайте)\s+без\s+(?:номера|телефона)\b', clause, re.I)
            short = contact_question and re.fullmatch(r'\s*(?:не\s+хочу|не\s+дам|не\s+буду)\s*', clause, re.I)
            if refusal or short:
                kind = 'client_contact_refusal'
                break
    if not kind or kind == 'avito_call_request' and known.get('channel') != 'avito':
        return None
    return dict(kind=kind, message_id=message.get('id', ''), quote=body,
                question_message_id=question.get('id', '') if contact_question else '',
                source='owner_policy_and_client_message', rule_id='OWNER-CLIENT-PHONE-AVITO-CALL-20261024',
                avito_call_available=known.get('channel') == 'avito',
                customer_contact_verified=verified, contractor_phone_shared=False,
                call_executed=False, visit_confirmed=False)


def assess(messages, known, facts):
    incoming_messages = [m for m in messages
        if m.get("direction") == "in" or m.get("role") in ("user", "client")
    ]
    incoming = [str(m.get("body") or m.get("text") or m.get("content") or "")
                for m in incoming_messages]
    text = "\n".join(incoming)
    # Some real client messages use Latin diaeresis instead of Cyrillic yo.
    # Keep the original messages/evidence; normalize only intent matching.
    last = incoming[-1].translate(str.maketrans("ëË", "ёЁ")) if incoming else ""
    direction = known.get("direction") or ""
    partner = assistant_catalog.canonical_partner(known.get("partner"))
    channel = str(known.get('channel') or '').strip().lower()
    title = str(known.get("title") or "")
    current_enquiry = assistant_prices.current_enquiry_messages(messages)
    result: dict[str, Any] = {
        "action": "draft",
        "reason": "",
        "rule_ids": [],
        "required_text": [],
        "allowed_prices": [],
        "missing": [],
        "decision_guards": [],
        "greeting_allowed": first_reply_required(messages),
        "greeting_required": first_reply_required(messages),
        "crm_flags": {
            "callbefore": (partner == "619" and channel != 'avito') or bool(facts.get("call_before_visit")),
            "review": partner in ("7", "340", "624", "723", "748") or bool(known.get("white")),
        },
    }

    callback_request = _client_requested_callback(messages) if direction == 'mnc' else None
    if callback_request:
        result['client_callback_evidence'] = callback_request
        result['client_wait_intent'] = 'deferred'

    # Keep this evidence even when territory, an existing order or a complaint
    # stops the reply. A contact plan must not bypass those earlier safeguards.
    caller_id = caller_id_save_request(messages, facts)
    if caller_id:
        result['caller_id_callback'] = caller_id

    # Preserve an operator's branch plan even if contacts/territory stop the
    # dialogue before service qualification. It grants no permission to act.
    route_service = None
    if direction == "mnc" and str(known.get("city") or "").strip().casefold() in ("красноярск", "красноярск сантехника", "красноярск (сантехника)"):
        route_service = assistant_catalog.choose(contact_facts.intent_text(text, facts), known)
        route = crm_branch_route(known, route_service)
        if route:
            result["crm_route"] = route

    followup = conditional_claim_followup(messages, known)
    if followup:
        result['conditional_claim_followup'] = followup

    def stop(reason, ids=(), action="handoff", reply="", guard=""):
        route = result.get("crm_route")
        if action == "handoff" and route and "согласован" in reason and route["approval_instruction"] not in reason:
            reason += ". " + route["approval_instruction"]
            ids = [*ids, route["rule_id"]]
        guards = result['decision_guards'] + ([dict(id=guard, message_ids=[m.get('id', '') for m in messages[-3:] if m.get('direction') in ('in', 'out')])] if guard else [])
        if followup:
            ids = [*ids, followup['rule_id']]
        if facts.get('service_comment_instruction'):
            ids = [*ids, 'OWNER-CONTACT-FIRST-LINE-20261023']
        return dict(result, action=action, reason=reason, rule_ids=list(ids), forced_reply=reply, decision_guards=guards)

    if str(known.get("channel") or "").lower().startswith("max"):
        return stop("MAX исключён владельцем: помощник здесь не работает", ("OWNER-MAX-20261016",))
    if not incoming:
        return stop("Нет сообщения клиента")
    if known.get('conversation_status') == 'closed' and messages[-1].get('direction') == 'out':
        return stop('Диалог уже закрыт: не возобновляем его напоминанием после ответа сотрудника', action='wait')
    printer_scope = qualification_state.printer_stated_scope(messages)
    if printer_scope:
        result['printer_stated_scope'] = printer_scope
        if (known.get('channel') == 'avito'
                and re.search(r'можете\s+(?:(?:дать|подсказать)\s+)?номер', last, re.I)):
            result['required_text'].append('Позвонить можно через Авито — кнопка звонка в этом чате.')
    logistics = furniture_logistics_state(messages, known)
    furniture_deferred = bool(logistics and logistics['kind'] == 'deferred')
    escalation_last = _escalation_text(last)
    if furniture_deferred:
        escalation_last = re.sub(r'\bперенес[её]м\s+разговор\b', 'отложим обсуждение', escalation_last, flags=re.I)
    booking_claim=_staff_booking_claim(messages)
    if booking_claim:
        result['staff_booking_claim']=booking_claim
    if messages[-1].get('out_pending'):
        return stop('Предыдущий ответ ещё отправляется: ожидаем результат', action='wait')
    refusal = _prior_service_refusal(messages)
    if refusal:
        result['staff_service_refusal_evidence'] = refusal
        return stop('Клиент просит объяснить неисправность после прежнего отказа сотрудника: '
                    'оператор проверяет контекст; не возобновляем сбор контактов и не угадываем причину',
                    ('DOC-L0699', 'DOC-L0700'), guard='VERIFY_PRIOR_SERVICE_REFUSAL')
    if (re.search(r'разговаривал\w*\s+с\s+вами|мы\s+(?:с\s+вами\s+)?разговаривал',last,re.I)
            and '?' in last and any(m.get('direction')=='out' and re.search(r'наб[ие]рал|звонил|позвонил',m['body'],re.I) for m in messages)):
        return stop('Клиент уточняет прежний разговор: оператор проверяет происхождение звонка, разговор не подтверждаем по словам сотрудника',('DOC-L0699','DOC-L0700'),guard='VERIFY_PRIOR_CALL')
    if re.search(r'\b(?:это\s+)?вы\s+(?:мне\s+|нам\s+)?(?:вчера\s+|сегодня\s+)?(?:позвонили|звонили)\b|\bс\s+ваш(?:ей|его)\s+(?:фирмы|компании|сервиса)\b.{0,60}\b(?:позвонили|звонили)\b', last, re.IGNORECASE):
        return stop('Клиент уточняет личность или компанию звонившего: оператор проверяет происхождение звонка, чужую личность не подтверждаем', ('DOC-L0699', 'DOC-L0700'))
    price_complaint = _post_service_price_complaint(messages)
    if price_complaint:
        result['existing_price_complaint_evidence'] = price_complaint
        simple_fee_lookup = (all(e.get('kind') == 'paid_visit_fee_question' for e in price_complaint)
                             and not re.search(r'\bверни(?:те)?\b|возврат|требую|жалоб|отзыв|полици|прокуратур', '\n'.join(incoming), re.I))
        if simple_fee_lookup and not facts.get('contact_phone_to_use'):
            choices = facts.get('phone_values') or []
            reply = ('На какой из указанных номеров была оформлена заявка?' if len(choices) > 1 else
                     'Подскажите, пожалуйста, полный номер телефона для проверки предыдущей заявки.')
            return stop('Претензия по прежнему визиту: нужен номер для проверки заявки и передачи в ОКК, новую заявку не создаём',
                        ('DOC-L0818', 'DOC-L0823'), action='question', reply=reply, guard='VERIFY_EXISTING_COMPLAINT')
        return stop('Ценовая претензия по прежнему визиту: проверить существующую заявку и передать в ОКК, новую заявку не создаём', ('DOC-L0823',))
    missed_visit = _missed_visit_complaint(messages)
    if missed_visit:
        result['existing_visit_complaint_evidence'] = missed_visit
        return stop('Клиент сообщает о неприезде мастера: проверить существующую заявку и передать претензию в ОКК, новую заявку не создаём',
                    ('DOC-L0818','DOC-L0823'),guard='VERIFY_EXISTING_COMPLAINT')
    property_damage = _property_damage_complaint(messages)
    if property_damage:
        result['property_damage_complaint_evidence'] = property_damage
        return stop('Клиент сообщает о повреждении имущества после работ: проверить существующую заявку и передать претензию в ОКК; оплату ремонта не обещаем',
                    ('DOC-L0818','DOC-L0823'),guard='VERIFY_EXISTING_COMPLAINT')
    readiness = _service_readiness_request(messages)
    if readiness:
        result['equipment_readiness_evidence'] = readiness
        return stop('Клиент спрашивает о готовности ранее сданной техники: проверить историю и статус существующей заявки, затем действовать по статусу и передать вопрос ответственному сотруднику; новую заявку не создаём, срок готовности не обещаем',
                    ('DOC-L0818','DOC-L0819','DOC-L1248','DOC-L1249','DOC-L1254','DOC-L1257'),guard='VERIFY_EQUIPMENT_READINESS')
    if _unresolved_trapped_animal(incoming):
        return stop('Клиент сообщает о застрявшем животном: это помощь животному вне профиля обычного ремонта, нужен оператор; плановый визит и самостоятельную разборку не предлагаем', ('DOC-L0250', 'DOC-L0251'), guard='VERIFY_NONPROFILE_ANIMAL')
    if _service_reported_resolved(last):
        result['service_resolution_evidence'] = dict(message_id=next((m.get('id', '') for m in reversed(messages) if m.get('direction') == 'in'), ''),
                                                      quote=last, crm_completion_confirmed=False)
        return stop('Клиент сообщил, что всё работает, и поблагодарил: не возобновляем сбор; завершение записи CRM этим не подтверждено', action='wait')
    if known.get("crm_note_references"):
        return stop("В служебной заметке указан возможный номер заявки: сначала проверить CRM и существующую договорённость", ('DOC-L0818', 'DOC-L0820'))
    refusal_ack = _staff_refusal_ack(messages, allow_generic=True)
    if (refusal_ack and not known.get('crm_request_id')
            and not _accepted_staff_visit(messages) and not _withdrawn_staff_visit(messages)):
        result['staff_refusal_closure'] = refusal_ack
        return stop('Клиент завершил разговор после отказа сотрудника; слова сотрудника не являются запретом приёма или подтверждением закрытия CRM',
                    ('DOC-L0800', 'DOC-L0801', 'DOC-L0802') if _organization_refusal_ack(messages) else (), action='wait')
    if facts.get('business_payment',{}).get('kind')=='invoice':
        return stop('Клиент запросил оплату юридическому лицу по счёту: требуется согласование с филиалом',('DOC-L0800','DOC-L0801','DOC-L0804'))
    access_documents = _personal_access_document_request(messages)
    if access_documents:
        result['access_document_request'] = access_documents
        return stop('Клиент запросил персональные паспортные данные для доступа: нужен ответственный сотрудник; пропуск и передачу данных автоматически не подтверждаем',
                    guard='VERIFY_PERSONAL_ACCESS_DOCUMENTS')
    call_permission = facts.get('client_call_permission')
    if call_permission and channel == 'avito':
        result['client_call_permission'] = call_permission
        return stop('Клиент спрашивает, можно ли ему позвонить сервису; это не просьба об обратном звонке или новом визите',
                    ('DOC-L0699', 'DOC-L0700'), action='question',
                    reply='Можете позвонить через Авито — кнопка звонка находится в этом чате.')
    passenger_pickup = facts.get('passenger_pickup_request') or {}
    if passenger_pickup.get('latest_is_request'):
        result['passenger_pickup_request'] = passenger_pickup
        return stop('Клиент просит забрать его: перевозку и наличие транспорта проверяет оператор; обычные работы не отвергаем',
                    ('DOC-L0323', 'DOC-L0453'), guard='VERIFY_PASSENGER_TRANSPORT')
    if (direction=='kp' and re.search(r'принтер|мфу',text,re.I) and re.search(r'картридж',text,re.I)
            and re.search(r'без\s+(?:них|картридж\w*)[^.!?\n]{0,25}смож\w*[^.!?\n]{0,25}(?:понять|проверить|диагност)',last,re.I)):
        return stop('Клиент спрашивает о проверке принтера без тестовых картриджей: техническую возможность и наличие деталей проверяет оператор',('DOC-L0181','DOC-L0700'),guard='VERIFY_DIAGNOSTIC_FEASIBILITY')
    if facts.get('active_service_scope', {}).get('prior_numeric_quote'):
        return stop('Клиент сузил объём после прежней озвучки: оператор проверяет действующую цену и договорённость', ('DOC-L0774', 'DOC-L0777'))
    if (messages[-1].get('direction') == 'in' and re.fullmatch(
            r'\s*мастер\s+(?:уже\s+)?приехал(?:\s*[,—-]\s*[А-ЯЁ][а-яё]+)?[.!\s]*', last, re.IGNORECASE)):
        return stop('Клиент сообщил о приезде мастера без нового вопроса: не открываем новую заявку', action='wait')
    if _reduced_furniture_scope(incoming):
        return stop("После кухни клиент уточнил сборку одного шкафа: оператор проверяет актуальный объём, прежний состав нельзя переносить автоматически")
    age = facts.get('client_age') or qualification_state.client_age(messages)
    adult = facts.get('adult_presence') or qualification_state.adult_presence(messages)
    if age['status'] == 'minor':
        result['adult_presence'] = adult
        adult_refs = ('DOC-L1572', 'DOC-L1573')
        why_adult = re.search(r'зачем\s+(?:они|родител\w*|взросл\w*)|'
                              r'почему.{0,20}(?:родител|взросл)|для\s+чего.{0,20}(?:они|родител|взросл)|'
                              r'вопрос\s+к\s+чему|зачем.{0,15}возраст', last, re.I)
        if why_adult:
            return stop('Объясняем условие взрослого для документов; прежняя заявка и изменение CRM не подтверждены', adult_refs,
                        action='question', reply='Документы должен заполнить совершеннолетний. Когда кто-то из взрослых сможет присутствовать?',
                        guard='VERIFY_ADULT_PRESENCE')
        if adult['status'] != 'confirmed':
            if booking_claim:
                return stop('Условие взрослого при существующем визите больше не подтверждено: оператор проверяет заявку, время и возможный перенос; изменение CRM не подтверждено',
                            adult_refs, guard='VERIFY_ADULT_PRESENCE')
            if adult['status'] == 'impossible':
                return stop('Присутствие взрослого невозможно: оператор проверяет оформление «Не оформлено» по регламенту; закрытие CRM не подтверждено',
                            adult_refs, guard='VERIFY_ADULT_PRESENCE')
            service_for_age = assistant_catalog.choose(contact_facts.intent_text(text, facts), known)
            if service_for_age['status'] == 'supported':
                result['service'] = service_for_age
                if assistant_prices.asks_current(messages):
                    return stop('Несовершеннолетний клиент: отвечаем на вопрос цены, присутствие взрослого ещё не подтверждено',
                                adult_refs, action='price', guard='VERIFY_ADULT_PRESENCE')
                question = qualification_state.adult_presence_question(adult)
                result['next_question'] = question
                reply = question['question']
                if re.search(r'(?:сможете|можете|сможешь|можешь).{0,30}(?:решить|починить|помочь|отремонтировать)', last, re.I):
                    reply = 'Сначала нужно осмотреть ' + ('компьютер' if any(r['family']=='pc' for r in service_for_age['items']) else 'технику') + '. ' + reply
                return stop('Несовершеннолетний клиент: уточняем, когда взрослый сможет присутствовать для оформления документов',
                            adult_refs, action='question', reply=reply, guard='VERIFY_ADULT_PRESENCE')
            return stop('Несовершеннолетний клиент: оператор проверяет услугу и присутствие взрослого', adult_refs,
                        guard='VERIFY_ADULT_PRESENCE')
    wait_subject = contact_facts._ARRIVAL_CALL.sub('[CALL_CONDITION]',last)
    client_waits = re.search(r"жд[её]м|жду|когда.{0,12}(?:приед|подъед|прийд|прид)|уже.{0,15}договорил|во\s+сколько.{0,25}(?:подойд|прийд|прид)|вс[её]\s+в\s+силе|вас.{0,25}ждать|\bвы\s+(?:(?:сегодня|завтра)\s+)?(?:(?:после\s+обеда|утром|вечером|дн[её]м|с\s+утра)\s+)?(?:подойд[её]те|приедете|будете)\b", wait_subject, re.IGNORECASE)
    promised_visit = any(re.search(
        r"\b(?:приеду|подъеду)\b|буду.{0,20}(?:у вас|через|завтра|сегодня|\bк\s*\d)|\bчерез[^.!?\n]{0,20}\bбуду\b|\b\d{1,2}(?::\d{2})?(?:\s*[-–]\s*\d{1,2}(?::\d{2}|\s+\d{2})?)?\s+буду\b|записал[аи]? вас|вы записаны",
        m["body"], re.IGNORECASE
    ) for m in messages if m.get("direction") == "out")
    if client_waits and promised_visit:
        return stop("Клиент уточняет ранее обещанный выезд: оператор проверяет существующую договорённость", guard='VERIFY_EXISTING_APPOINTMENT')
    if re.search(r"\bподъезжайте\b|\bприезжайте\b", last, re.IGNORECASE) and any(
        m.get('direction') == 'out' and re.search(r"могу\s+через\s+(?:час|\d)|(?:приеду|подъеду).{0,25}(?:час|\d)", m['body'], re.IGNORECASE)
        for m in messages):
        return stop("Клиент подтвердил предложенный выезд: оператор проверяет существующую договорённость и наличие заявки", guard='VERIFY_EXISTING_APPOINTMENT')
    previous_out = next((m["body"] for m in reversed(messages) if m.get("direction") == "out"), "")
    counterproposal = _visit_counterproposal(messages)
    if counterproposal:
        result['visit_counterproposal_evidence'] = counterproposal
        return stop('Клиент предложил другое время визита: оператор проверяет возможность и актуальную договорённость; '
                    'не повторяем сбор уже известных данных', guard='VERIFY_VISIT_COUNTERPROPOSAL')
    if re.search(r'\b(?:мастер\s+)?[А-ЯЁ][а-яё-]+\s+от\s+вас\s+(?:приходил|приезжал)\b|\bпишу\s+[А-ЯЁ][а-яё-]+[^.!?\n]{0,45}\bприходит\s+[А-ЯЁ][а-яё-]+\b', last):
        return stop('Клиент уточняет личность приходившего мастера: оператор проверяет назначенного исполнителя и историю заявки', guard='VERIFY_ASSIGNED_TECHNICIAN')
    if (re.fullmatch(r'[А-Яа-яЁёA-Za-z-]{2,40}\s*\?', last.strip())
            and not re.fullmatch(r'(?:когда|сколько|почему|зачем|как|где|что|какой|какая)\s*\?', last.strip(), re.IGNORECASE)
            and any(m.get('direction') == 'out' and re.search(r'\b(?:набрал|позвонил|звонил)\s+вам\b', m['body'], re.IGNORECASE) for m in messages)):
        return stop('Клиент уточняет личность или компанию после заявленного звонка: оператор проверяет происхождение звонка, чужую личность не подтверждаем', ('DOC-L0699', 'DOC-L0700'))
    reported_visit = any(re.search(r'\b(?:вы\s+)?(?:по)?обещали\b.{0,100}(?:приед|подъед|приехат|подъех|не\s+приехали|не\s+позвонили)', body, re.IGNORECASE) for body in incoming)
    prospective_warranty = (not known.get('crm_request_id') and _prospective_warranty_question(messages)
                            and assistant_catalog.choose(contact_facts.intent_text(text, facts), known)['status'] == 'supported')
    if _ESCALATION.search(escalation_last) and not prospective_warranty:
        refs = ('TG1-677',) if re.search(r'полици|инстанци|прокуратур', last, re.IGNORECASE) else ('TG2-166',) if re.search(r'отмен', last, re.IGNORECASE) else ('DOC-L0823',) if re.search(r'претензи|жалоб|верн.*деньг', last, re.IGNORECASE) else ()
        return stop('Обращение по существующей заявке или эскалация — нужен оператор', refs, guard='' if refs else 'VERIFY_EXISTING_REQUEST')
    if known.get('crm_request_id'):
        return stop('Обращение по существующей заявке — нужен оператор', ('DOC-L0818', 'DOC-L0819'))
    if prospective_warranty:
        return stop('Вопрос об условиях гарантии на будущие работы: гарантийная заявка этим не подтверждена',
                    ('DOC-L0693',), action='question',
                    reply='Гарантия распространяется на оказанные услуги. Её условия будут указаны в документах.')
    if reported_visit:
        return stop('Обращение по возможной существующей заявке: оператор проверяет ранее обещанный выезд и договорённость', guard='VERIFY_EXISTING_APPOINTMENT')
    if _reported_service_return(incoming):
        refs = ('DOC-L1248', 'DOC-L1249', 'DOC-L1254', 'DOC-L1257') if _equipment_return_request(incoming) else ('DOC-L1051', 'DOC-L1052')
        return stop('Клиент сообщает о проблеме после прежнего ремонта или обслуживания, просит вернуть мастера или свою технику: проверить существующую заявку и передать ответственному сотруднику', refs)
    if (re.search(r'\b(?:у\s+меня\s+)?приняли\s+заявку\b|\bзаявку\s+(?:уже\s+)?приняли\b',last,re.I)
            and not re.search(r'\?|\bне\b',last,re.I)):
        result['crm_flags']['client_reported_existing_intake']=True
        return stop('Клиент сообщил об уже принятой заявке: не возобновляем сбор новой',
                    action='handoff' if re.search(r'\bу\s+вас\b|\bваш',last,re.I) else 'wait')
    visit_followup=re.search(r'\bвы\s+где\b|\bгде\s+вы\b|\bкогда\s+(?:вас|мастера)\s+ожидать\b|'
                            r'\b(?:вас|мастера)\s+ждать\b|\bвы\s+(?:сегодня\s+|завтра\s+)?(?:подойд[её]те|приедете|будете)\b|'
                            r'\bкто(?:-нибудь)?\b[^.!?\n]{0,35}\b(?:сегодня|завтра)\b[^.!?\n]{0,20}\bбудет\b|'
                            r'цен[аыуе]|стоим|по\s+деньгам|сколько\s+за\s+работ|сколько\s+(?:будет\s+)?(?:стоить|денег)',last,re.I)
    clock = r'(?:[01]?\d|2[0-3])(?:[.:][0-5]\d)?(?!\d)'
    time_change = re.search(r'\b(?:можно|сможете|давайте|лучше)\b[^.!?\n]{0,30}\b(?:в|к|после)\s*'+clock+
                            r'|\b(?:в|к|после)\s*'+clock+r'[^.!?\n]{0,25}\b(?:можно|сможете)\b',last,re.I)
    availability_followup = re.search(r'\b(?:сможете|можете)\s+(?:сегодня\s+|завтра\s+)?(?:подъех|приех)|'
                                     r'\b(?:сегодня|завтра)\b[^.!?\n]{0,90}\b(?:подъех|приех)', last, re.I)
    if visit_followup or time_change or availability_followup or _direct_visit_time_question(last):
        latest_client_index = next((i for i in range(len(messages) - 1, -1, -1) if messages[i].get('direction') == 'in'), -1)
        earlier_visit = _accepted_staff_visit(messages[:latest_client_index], include_later_questions=True)
        if earlier_visit and not own_visit.matches(known, earlier_visit):
            result['existing_visit_evidence']=earlier_visit
            return stop('Вопрос о переносе после принятого времени визита: оператор проверяет существующую договорённость и заявку' if time_change
                        else 'Вопрос после принятого времени визита: оператор проверяет существующую договорённость и заявку',guard='VERIFY_EXISTING_APPOINTMENT')
    provider_history = '\n'.join(body for body in incoming if not re.search(r'(?:^|\n)\s*Сделка состоялась', body, re.IGNORECASE))
    if (re.search(r'(?:приезжал|был).{0,20}(?:один\s+|другой\s+)?(?:специалист|мастер)', provider_history, re.IGNORECASE)
            and re.search(r'ничего.{0,25}(?:не\s+смог|не\s+сделал)|не\s+помог', provider_history, re.IGNORECASE)
            and re.search(r'деньги\s+взял|заплатил|оплатил', provider_history, re.IGNORECASE)):
        return stop('Клиент описывает неудачный оплаченный визит предыдущего специалиста: оператор проверяет связь с нашей заявкой и объём работ; гарантию автоматически не назначаем', ('DOC-L1051', 'DOC-L1052'))
    # Waiting/declining does not require diagnosing an unread attachment. It
    # authorizes no send or CRM change. Existing requests and complaints still
    # require the operator rather than disappearing into a waiting queue.
    deferred = _client_deferred(incoming,messages) or furniture_deferred
    photo_permission = _photo_submission_permission(last)
    provider_choice = contact_facts.other_provider_choice(incoming_messages[-1])
    declined = _client_declined(last, previous_out) or bool(provider_choice)
    decline_message = incoming_messages[-1] if declined else None
    if (not declined and len(incoming)>1 and _client_declined(incoming[-2], '')
            and re.match(r'^\s*спасибо\b', last, re.I)
            and not re.search(r'\?|нужна?\s+помощь|помогите|подскажите|теперь\s+нужно', last, re.I)):
        declined = True
        decline_message = incoming_messages[-2]
    if deferred or declined:
        result['client_wait_intent'] = 'declined' if declined else 'deferred'
        if declined:
            result['client_decline_evidence'] = provider_choice or dict(message_id=decline_message.get('id', ''),
                quote=str(decline_message.get('body') or decline_message.get('text') or decline_message.get('content') or ''),
                source='client_message', crm_cancellation_confirmed=False)
            if provider_choice:
                result['crm_flags']['customer_declined'] = True
            if provider_choice and provider_choice['arrival_reported'] and messages[-1].get('direction') != 'out':
                return stop('Клиент сообщил о приезде и выбрал другого специалиста: оператор проверяет прежнюю заявку и отказ; '
                            'приезд и отмена в CRM независимо не подтверждены',
                            ('DOC-L0818','DOC-L0819'), guard='VERIFY_CHANGED_APPOINTMENT')
        rescheduling = any(re.search(r"перенес(?:ти|[её]м).{0,35}(?:встреч|визит|приезд|заявк)|(?:встреч|визит|приезд|заявк).{0,35}перенес", body, re.IGNORECASE) for body in incoming)
        firm_appointment = any(m.get('direction') == 'out' and re.search(
            r'записал[аи]?\s+вас|вы\s+записаны|\b(?:в|к)\s*\d{1,2}(?::\d{2})?\s+буду|\b(?:приеду|подъеду)\s+(?:сегодня\s+|завтра\s+)?(?:в|к)\s*\d', m['body'], re.IGNORECASE) for m in messages)
        accepted_visit = _accepted_staff_visit(messages)
        prior_commitment = (declined and promised_visit) or (deferred and firm_appointment)
        if booking_claim:
            if facts['phone_needs_confirmation']:
                return stop('Нужно выбрать номер для проверки заявленной сотрудником записи',('TG1-668','TG2-304'),
                            action='question',reply='На какой из указанных номеров вам звонить?',guard='VERIFY_EXISTING_APPOINTMENT')
            return stop('Сотрудник сообщил о записи: оператор проверяет реальную заявку и прежнюю договорённость; слова сотрудника не подтверждают запись в CRM',
                        ('DOC-L0818','DOC-L0820'),guard='VERIFY_EXISTING_APPOINTMENT')
        if known.get("crm_request_id") or rescheduling or _ESCALATION.search(escalation_last) or accepted_visit or (prior_commitment and facts.get('contact_phone_to_use') and facts.get('address', {}).get('building')):
            reason = ('Клиент отказался от помощи: оператор проверяет существующую заявку, договорённость и отмену; изменение CRM не подтверждено'
                      if declined else 'Изменение намерения по существующей заявке или эскалация: оператор проверяет договорённость')
            return stop(reason, guard='VERIFY_CHANGED_APPOINTMENT')
        if furniture_deferred and not declined:
            if channel == 'avito' and partner not in assistant_catalog.AVITO_PARTNERS:
                return stop('Партнёр Avito не входит в подтверждённый владельцем список 7, 723, 748, 340, 624: оператор проверяет настройки канала', ('OWNER-AVITO-PARTNERS-20261017',))
            if not title or not known.get('account_name'):
                return stop('Не заполнены данные объявления или аккаунта: сначала проверить источник')
            city_messages = [dict(m, body=re.sub(r'(?m)^Город\b', 'город', m.get('body', ''))) for m in messages]
            wait_city = assistant_qualifiers.client_city(city_messages)
            if wait_city and known.get('city') and wait_city.casefold().replace('ё', 'е') != known['city'].casefold().replace('ё', 'е'):
                return stop('Клиент назвал другой город: оператор проверяет источник, филиал и территорию', ('DOC-L0809', 'DOC-L0810'))
            wait_geo = geography(known.get('city'), direction, known.get('latitude'), known.get('longitude'))
            result['geography'] = wait_geo
            if wait_geo['status'] in ('closed', 'unknown', 'needs_confirmation'):
                return stop(wait_geo['reason'], wait_geo.get('rule_ids', []))
        if declined:
            result["crm_flags"]["customer_declined"] = True
        elif not photo_permission and not callback_request:
            preparation = _recontact_callback_preparation(messages, facts, logistics if furniture_deferred else None)
            if preparation:
                result['crm_preparation'] = preparation
        if declined or not (photo_permission or callback_request):
            return stop("Клиент отказался либо решил проблему: не продолжаем сбор новой заявки" if declined else "Клиент отложил решение и сам напишет: не продолжаем сбор заявки", action="wait",
                        reply='Хорошо, напишите, когда будете готовы продолжить разговор.' if furniture_deferred and not declined and logistics.get('latest_is_defer') else '')
    withdrawn_visit = None if _accepted_staff_visit(messages) else _withdrawn_staff_visit(messages)
    if withdrawn_visit:
        result['withdrawn_visit_evidence'] = withdrawn_visit
        return stop('Ранее принятое время визита отозвано сотрудником; новый визит и отмена записи в CRM не подтверждены: оператор проверяет существующую заявку без повторного сбора данных', guard='VERIFY_EXISTING_APPOINTMENT')
    if _conversation_closed(last, _previous_staff_turn(messages) or previous_out, incoming[-2] if len(incoming)>1 else ''):
        return stop('Клиент завершил разговор: не возобновляем сбор заявки', action='wait')
    if (re.fullmatch(r'\s*(?:ок|хорошо|понял[аи]?|договорились)[.!\s]*', last, re.I)
            and re.search(r'\b(?:обсудим|сориентирую|спишемся|пишется)\b', previous_out, re.I)
            and re.search(r'\b(?:в|к)\s*\d{1,2}\b', previous_out, re.I)
            and not re.search(r'приед|подъед|визит|приезд|запис|буду\s+у\s+вас', previous_out, re.I)):
        return stop('Клиент согласился связаться и обсудить время позднее: это не подтверждённый визит', action='wait')
    if channel == 'avito' and partner not in assistant_catalog.AVITO_PARTNERS:
        return stop('Партнёр Avito не входит в подтверждённый владельцем список 7, 723, 748, 340, 624: оператор проверяет настройки канала', ('OWNER-AVITO-PARTNERS-20261017',))
    if any(re.search(r'(?:^|\n)\s*Сделка состоялась', body, re.IGNORECASE) for body in incoming) and re.search(r'по\s+такому\s+принципу|так\s+же.{0,30}(?:цен|стоим)|почему.{0,30}(?:цен|стоим)', last, re.IGNORECASE):
        return stop('Клиент привёл чужой отзыв и сомневается в порядке согласования цены: оператор разъясняет стоимость без неподтверждённых обещаний', ('DOC-L0713', 'DOC-L0715'))
    if facts.get('visual_context_conflict'):
        return stop('Основная техника на просмотренном фото расходится со словами клиента: оператор сопоставляет контекст без диагноза и отказа', guard='VERIFY_VISUAL_CONTEXT')
    # An explicit current symptom can establish the owner's refusal without
    # diagnosing an earlier model photo. A newer unread attachment or another
    # requested job still requires review; no media approval is invented.
    if direction == 'kp' and messages[-1].get('direction') == 'in' and not messages[-1].get('unread_media'):
        band_scope = assistant_catalog.choose(contact_facts.intent_text(text, facts), known)
        band_items = band_scope.get('items', [])
        if (band_scope.get('status') == 'refuse' and len(band_items) == 1
                and band_items[0]['id'] == 'tv-bands'):
            result['service'] = band_scope
            return stop(band_scope['reason'], band_scope['rules'], 'refuse',
                        'К сожалению, с такой неисправностью телевизора не смогу помочь.')
    unread = [m for m in messages if m.get('direction') == 'in' and m.get('unread_media')]
    if unread and all(m.get('awaiting_voice_transcript') is True for m in unread):
        return stop('Ожидаем завершения расшифровки голосового сообщения', action='wait', guard='AWAIT_VOICE_TRANSCRIPT')
    if unread:
        return stop(
            "В диалоге есть вложение без расшифровки: сначала просмотреть или прослушать его оператору",
            guard='UNREAD_MEDIA'
        )
    if messages[-1].get("out_pending"):
        return stop(
            "Предыдущий ответ ещё отправляется: ожидаем результат", action="wait"
        )
    if messages[-1].get("direction") == "out":
        if direction == 'kp':
            import dialogue_lifecycle
            timer = dialogue_lifecycle.silence_timer(messages, known)
            if timer.get('status') == 'followup_due':
                result['silence_followup'] = timer
                result['requires_operator_review'] = True
                return stop('Клиент молчит 5 минут: один уточняющий вопрос по правилу КП',
                            ('OWNER-KP-SILENCE-20261019', 'KP-L1598'), 'question',
                            dialogue_lifecycle.KP_FOLLOWUP_REPLY, guard='SILENCE_FOLLOWUP')
        return stop("Ожидаем ответа клиента", action="wait")
    accepted_visit = _accepted_staff_visit(messages)
    if accepted_visit and not own_visit.matches(known, accepted_visit):
        result['existing_visit_evidence'] = accepted_visit
        if facts['phone_needs_confirmation']:
            return stop('Нужно выбрать номер для проверки существующей договорённости и звонка',('TG1-668','TG2-304'),
                        action='question',reply='На какой из указанных номеров вам звонить?',guard='VERIFY_EXISTING_APPOINTMENT')
        # A bare acceptance of a staff's time offer does not prove a CRM
        # booking. Collect the missing contact once, without releasing the
        # existing-appointment guard or issuing a second booking.
        if (not booking_claim and not facts.get('phone_values')
                and accepted_visit['answer_speaker'] == 'client'
                and accepted_visit['answer_message_id'] == messages[-1].get('id')
                and sum(m.get('direction') == 'out' and (i == 0 or messages[i-1].get('direction') != 'out')
                        for i, m in enumerate(messages)) >= 2
                and facts.get('address', {}).get('street') and facts['address'].get('building')
                and assistant_catalog.choose(contact_facts.intent_text(text, facts), known)['status'] == 'supported'
                and not any(re.search(r'номер|телефон', m.get('body', ''), re.I)
                            for m in messages[:-1])):
            return stop('Клиент принял предложение времени, но контакта ещё нет: уточняем номер, сохраняя проверку договорённости',
                        ('DOC-L0818', 'DOC-L0820'), action='question',
                        reply='Подскажите, пожалуйста, номер телефона для связи.',
                        guard='VERIFY_EXISTING_APPOINTMENT')
        exchange = ('Сотрудник ответил на предложение времени клиента' if accepted_visit['answer_speaker'] == 'staff'
                    else 'Ранее клиент принял предложение времени сотрудника')
        return stop(exchange + ': оператор проверяет прежнюю переписку, актуальную договорённость и заявку; '
                    'запись в CRM и текущая доступность не подтверждены', guard='VERIFY_EXISTING_APPOINTMENT')
    if booking_claim:
        if facts['phone_needs_confirmation']:
            return stop('Нужно выбрать номер для проверки заявленной сотрудником записи',('TG1-668','TG2-304'),
                        action='question',reply='На какой из указанных номеров вам звонить?',guard='VERIFY_EXISTING_APPOINTMENT')
        return stop('Сотрудник сообщил о записи: оператор проверяет реальную заявку и прежнюю договорённость; слова сотрудника не подтверждают запись в CRM',
                    ('DOC-L0818','DOC-L0820'),guard='VERIFY_EXISTING_APPOINTMENT')
    arrival_followup = _unverified_arrival_followup(messages, facts)
    prior_conversation = _reported_prior_conversation(messages) or arrival_followup
    if prior_conversation:
        result['prior_conversation_evidence'] = prior_conversation
        if arrival_followup and prior_conversation is arrival_followup:
            if facts.get('contact_phone_to_use'):
                return stop('Клиент уточняет ожидаемый выезд: оператор проверяет возможную прежнюю договорённость по уже указанному номеру; '
                            'визит и заявка не подтверждены', ('DOC-L0818','DOC-L0819'), guard='VERIFY_PRIOR_CONVERSATION')
            return stop('Клиент уточняет ожидаемый выезд: нужен номер только для проверки возможной прежней договорённости; '
                        'новую заявку и приезд не подтверждаем', ('DOC-L0818','DOC-L0867','DOC-L0868'),
                        action='question', reply='Подскажите, пожалуйста, номер для проверки предыдущей договорённости.',
                        guard='VERIFY_PRIOR_CONVERSATION')
        if facts.get('contact_phone_to_use'):
            return stop('Клиент сообщает о предыдущем разговоре: оператор проверяет предыдущую договорённость по уже указанному номеру; содержание звонка не подтверждено', guard='VERIFY_PRIOR_CONVERSATION')
        return stop('Клиент сообщает о предыдущем разговоре: запрашиваем только номер для проверки, новую заявку не подтверждаем',
                    action='question', reply='Подскажите, пожалуйста, номер для проверки предыдущей договорённости.',
                    guard='VERIFY_PRIOR_CONVERSATION')
    import dialogue_lifecycle
    short_pause = dialogue_lifecycle.short_client_pause(messages)
    if short_pause['status'] in ('waiting', 'unavailable'):
        result['client_short_pause_evidence'] = short_pause
        result['service'] = assistant_catalog.choose(contact_facts.intent_text(text, facts), known)
        pause_refs = result['service'].get('rules', [])
        if short_pause['status'] == 'unavailable':
            return stop('Клиент просит немного подождать, но время паузы не подтверждено: нужен оператор',
                        pause_refs, guard='VERIFY_SHORT_PAUSE_CLOCK')
        result['client_wait_intent'] = 'short_pause'
        return stop('Клиент попросил немного подождать: пока не повторяем вопрос', pause_refs, action='wait')
    if (re.search(r'\bраз\s+в\s+неделю\b|\bеженедельн\w*', text, re.IGNORECASE)
            and re.search(r'\b(?:ип|ооо|ндс)\b|физ\.?\s*лиц|третьих\s+лиц|третих\s+лиц', text, re.IGNORECASE)
            and re.search(r'\b(?:кабел|монтаж|работ|коробк|штроб)\w*', text, re.IGNORECASE)):
        return stop('Клиент предлагает подряд с еженедельной оплатой и условиями договора: оператор проверяет объём, оплату и согласование с филиалом; это не обычный разовый выезд',
                    ('DOC-L0452','DOC-L0453','DOC-L0803','DOC-L0804'),guard='VERIFY_CONTRACT_SCOPE')
    if (re.search(r'ищу\s+мастер\w*\s+для\s+регулярн\w*\s+заявок|привожу\s+вам\s+клиент', text, re.I)
            and re.search(r'переда(?:ть|ю|вать)[^.!?\n]{0,40}(?:вам|заявк)|\bподрядчик', text, re.I)):
        return stop('Предложено регулярное подрядное сотрудничество и передача заявок: оператор согласует условия, обычный прайс не подтверждает подряд',
                    ('DOC-L0453','DOC-L0803','DOC-L0804'),guard='VERIFY_CONTRACT_SCOPE')
    if re.search(r'\bвас\b.{0,25}\bне\s+(?:пустят|пропустят)\b', last, re.IGNORECASE):
        return stop('Клиент прямо исключил доступ на объект: оператор проверяет допустимое место обслуживания; выезд и мастерскую не обещаем',
                    guard='VERIFY_SITE_ACCESS')
    farewell = r"(?:до\s*свидания|всего\s+(?:доброго|хорошего)|прощайте|пока)"
    if re.fullmatch(r"\s*(?:(?:спасибо|благодарю|понял|поняла)[,!\s]*)?" + farewell + r"[.!\s]*", last, re.IGNORECASE):
        return stop("Клиент завершил разговор: не возобновляем сбор заявки", action="wait")
    previous_out = next((m["body"] for m in reversed(messages) if m.get("direction") == "out"), "")
    if re.fullmatch(r"\s*(?:спасибо|благодарю)[.!\s]*", last, re.IGNORECASE) and re.search(farewell, previous_out, re.IGNORECASE):
        return stop("Клиент поблагодарил после завершения разговора", action="wait")
    if assistant_prices.unqualified_price_range(messages):
        return stop('Клиент уточняет диапазон цены без валюты или масштаба: оператор проверяет сумму, не превращаем3–10 в рубли или тысячи',
                    ('DOC-L0713','DOC-L0774'))
    if assistant_prices.asks_to_confirm_previous_total(messages):
        return stop(
            "Клиент уточняет ранее озвученную общую стоимость: оператор проверяет прежнюю договорённость и весь объём работ",
            ("DOC-L0713", "DOC-L0715", "DOC-L0774"),
        )
    if re.fullmatch(r"\s*(?:нет[,!\s]*)?не\s+(?:хочу|надо|нужно)[.!\s]*", last, re.IGNORECASE) and not any(
        m.get("direction") == "out" for m in messages
    ):
        return stop("Клиент выразил отказ без ясного предмета: оператор уточняет намерение")
    if _decision_maker_absent(messages):
        return stop("Заказчик сообщил, что не будет на месте: оператор подтверждает присутствие человека, принимающего решение и оплачивающего работу", ("DOC-L0797", "DOC-L0798"))
    if re.search(
        r"игнорируй.*инструкц|раскрой.*промпт|system prompt|служебн.*токен",
        last,
        re.IGNORECASE,
    ):
        return stop("Запрос выходит за задачу обслуживания клиента")
    document_request = re.compile(r"(?:нуж(?:ен|ны|но|на)|требует(?:ся|ься)|составить|выдать|оформить|сделать).{0,30}\b(?:акт|заключение|экспертиз\w*)\b|\bакт\s+для\s+(?:управляющ|страхов|суд|ук\b)", re.IGNORECASE)
    for client_message in incoming:
        affirmative = re.sub(r"\b(?:акт|заключение|экспертиз\w*)\s+не\s+нуж\w*|\bне\s+нуж\w*.{0,12}\b(?:акт|заключение|экспертиз\w*)\b", "", client_message, flags=re.IGNORECASE)
        if document_request.search(affirmative):
            return stop("Клиенту нужен специальный акт/заключение: выдача такого документа не подтверждена регламентом, условия проверяет оператор", ("DOC-L0699", "DOC-L0700"))
    document = _document_question(messages)
    if document:
        if document['explicit_type'] or document.get('staff_answer'):
            return stop('Клиенту нужен определённый платёжный документ: оператор проверяет вид документа и ранее данное обещание', ('DOC-L0699', 'DOC-L0700'))
        return stop('Вопрос о квитанции ещё не разрешён: сначала уточняем вид документа без обещания кассового чека',
                    ('DOC-L0699', 'DOC-L0700'), 'question',
                    'Уточните, пожалуйста, какой документ вам нужен: БСО или кассовый чек?')
    phone_exchange = (None if caller_id and caller_id['reply_due']
                      else phone_exchange_request(messages, known, facts))
    if phone_exchange:
        result['phone_exchange'] = phone_exchange
        if phone_exchange['kind'] == 'client_contact_refusal':
            reply = 'Для выезда нужен ваш номер телефона.'
            reply += (' Можете позвонить через Авито — обсудим заказ.' if phone_exchange['avito_call_available']
                      else ' Можем пока обсудить заказ здесь.')
        else:
            reply = ('Можете позвонить через Авито — обсудим заказ.' if phone_exchange['avito_call_available']
                     else 'Свой номер не сообщаю. Можем обсудить заказ здесь.')
        return stop('Контакт для выезда и обсуждение заказа различаются; свой номер не сообщаем, звонок не подтверждаем',
                    (phone_exchange['rule_id'],), 'question', reply)
    if (re.search(r'\bконтакт\w*\b[^.!?\n]{0,45}\bкто\b[^.!?\n]{0,45}(?:оказывает|занимается|делает)', last, re.I)
            and re.search(r'не\s+смогу\s+помочь|помочь\s+не\s+смогу|не\s+занимаюсь', previous_out, re.I)):
        return stop('Клиент просит контакт другого исполнителя: проверенной рекомендации в контексте нет, контакт и передачу не придумываем',
                    ('DOC-L0699', 'DOC-L0700'), action='question', reply='К сожалению, не могу подсказать проверенный контакт по таким работам.')
    if (direction == 'kp' and re.search(r'\bgpon\b', text, re.I) and re.search(r'розетк', text, re.I)
            and not re.search(r'обж[аи]м|коннектор|замен|пролож|ремонт|поврежд|обрыв', text, re.I)
            and not any(m.get('direction') == 'out' and re.search(r'оптоволок|кабел|разъ[её]м|оборудован|розетк', m['body'], re.I) for m in messages)):
        return stop('GPON-розетка названа без конкретной операции: отличаем настройку оборудования от физической работы с оптикой',
                    ('DOC-L0699', 'DOC-L0700', 'DOC-L0164', 'DOC-L0165', 'DOC-L0170'), action='question',
                    reply='Нужна настройка оборудования или работа с оптоволоконным кабелем и разъёмом?')
    if (direction == 'kp' and re.search(r'\b(?:впн|vpn)\b', text, re.I)
            and re.search(r'вай[ -]?фа[йяю]|wi[ -]?fi', text, re.I)
            and not re.search(r'роутер|router|компьютер|ноутбук|\bпк\b|телевиз|\bтв\b|телефон|смартфон', text, re.I)):
        # A question about the callout fee must not be replaced by the still
        # unanswered device question. Quoting that fee does not accept the
        # service, establish compatibility or confirm a visit.
        fee_question = assistant_prices.price_question_subject(assistant_prices.current_price_question(messages))
        fee_scope = assistant_catalog.choose(contact_facts.intent_text(text, facts), known)
        if (assistant_prices.asks_current(messages) and re.search(r'выезд|диагност', fee_question, re.I)
                and fee_scope['status'] in ('supported', 'unknown')):
            return stop('Сначала отвечаем на вопрос об оплате выезда; устройство настройки и приём ещё не подтверждены',
                        ('DOC-L0699', 'DOC-L0700'), action='price', guard='VERIFY_VPN_SCOPE')
        return stop('VPN разрешён, но устройство настройки ещё не указано: уточняем только область работы',
                    ('DOC-L0134', 'DOC-L0171'), action='question',
                    reply='VPN нужно настроить на роутере или на компьютере?')
    ambiguous_time = re.search(r'\b(?:до|после|к)\s+(\d{3})(?!\d|\s*(?:руб|₽|метр|мм|см|км))\b', last, re.I)
    if ambiguous_time and (re.search(r'жду|врем|час|приед|приеха', last, re.I)
                           or re.search(r'когда|час|удобно', previous_out, re.I)):
        return stop('В ограничении времени три цифры без понятного формата: уточняем, не назначаем час по догадке',
                    ('DOC-L0700',), action='question', reply='Уточните, пожалуйста, до какого времени вы сможете принять мастера?', guard='VERIFY_TIME_FORMAT')
    place_candidate = facts.get('untyped_place_candidate') or {}
    stated_settlement = (facts.get("address") or {}).get("settlement") or _explicit_settlement(messages) or place_candidate.get('value','')
    if (stated_settlement and known.get("city")
            and stated_settlement.casefold().replace("ё", "е").strip() != known["city"].casefold().replace("ё", "е").strip()
            and not assistant_qualifiers.city_mentioned(stated_settlement, known['city'])):
        result['service'] = assistant_catalog.choose(contact_facts.intent_text(text, facts), known)
        result['qualification'] = qualification_state.inspect(messages)
        result['stated_place'] = facts.get('stated_place') or place_candidate or dict(value=stated_settlement)
        location_reason = ("В адресе есть неподтверждённый населённый пункт: оператор проверяет его по карте до дальнейшего сбора заявки" if place_candidate
                           else "Клиент назвал населённый пункт: оператор проверяет точную территорию до дальнейшего сбора заявки")
        location_refs = ['DOC-L0623','DOC-L0630','DOC-L0809']
        prior_price = assistant_prices.consent(messages)
        if prior_price['status'] in ('pending','accepted') and not assistant_prices.prior_quote_verified(messages,known,prior_price):
            location_reason = 'Ранее названная стоимость не подтверждена текущим правилом; '+location_reason
            location_refs += ['DOC-L0713','DOC-L0774','DOC-L0777']
        return stop(location_reason,location_refs)
    if facts.get('required_crew_count', 0) and facts['required_crew_count'] > 1:
        return stop('Клиенту нужны два исполнителя: оператор проверяет состав бригады и возможность выезда без обещания доступности', guard='VERIFY_REQUIRED_CREW')
    crew_question = crew_composition_question(messages)
    if crew_question:
        crew_question.update(reply_source='owner_approved_standard_wording',
                             rule_id='OWNER-CREW-STANDARD-WORDING-20261023')
        result['crew_composition_question'] = crew_question
        result['required_text'].append('Я работаю один.')
    target = re.search(r'(?:\bвы\s+|\bв\s+)([А-ЯЁ][а-яё-]+(?:\s+[А-ЯЁ][а-яё-]+){0,2})\s+(?:сможете\s+)?(?:приехать|выезжаете|приедете)', last, re.IGNORECASE)
    if target:
        target_city = assistant_qualifiers.client_city([dict(direction='in', body='город ' + target[1])])
        if target_city and known.get('city') and target_city != known['city']:
            return stop('Клиент спросил о выезде в другой город: оператор проверяет точную территорию до сбора заявки', ('DOC-L0809', 'DOC-L0810'))
    if (direction == 'kp' and re.search(r'приставк', text, re.IGNORECASE)
            and re.search(r'smart\s*tv|телевизор|\bтв\b', text, re.IGNORECASE)
            and not re.search(r'xbox|playstation|nintendo|игров\w*\s+приставк', text, re.IGNORECASE)):
        choice = ''
        for i, message in enumerate(messages):
            if message.get('direction') == 'in' and i and messages[i-1].get('direction') == 'out' and re.search(r'телевизор.{0,45}отдельн.{0,15}приставк', messages[i-1]['body'], re.IGNORECASE):
                if re.search(r'приставк', message['body'], re.IGNORECASE) and not re.search(r'телевизор', message['body'], re.IGNORECASE):
                    choice = 'box'
                elif re.search(r'телевизор', message['body'], re.IGNORECASE) and not re.search(r'приставк', message['body'], re.IGNORECASE):
                    choice = 'tv'
        if choice == 'box':
            return stop('Уточнена отдельная ТВ-приставка: оператор проверяет, нужна разрешённая настройка или аппаратный ремонт', ('DOC-L0197',))
        if not choice:
            return stop('Smart TV и приставка названы неоднозначно: сначала уточняем устройство', ('DOC-L0197',), 'question',
                        'Подскажите, речь о телевизоре или отдельной ТВ-приставке?')
    region_disclaimer = re.compile(r"не\s+ваш\w*\s+(?:регион|город)|друг(?:ой|ом)\s+регион|ошиб(?:ся|лась).{0,15}(?:город|регион)", re.IGNORECASE)
    region_index = next((i for i in range(len(messages) - 1, -1, -1) if messages[i].get("direction") == "in" and region_disclaimer.search(messages[i]["body"])), None)
    if region_index is not None:
        confirmed_city = assistant_qualifiers.client_city(messages[region_index + 1:])
        if not confirmed_city or confirmed_city.casefold().replace("ё", "е") != str(known.get("city") or "").casefold().replace("ё", "е"):
            return stop("Клиент сообщил о другом регионе: оператор проверяет город и территорию до запроса контактов", ("DOC-L0809", "DOC-L0810"))
    if assistant_qualifiers.provider_location_question(last) and known.get('city'):
        return stop('Клиент уточняет город исполнителя: называем только город объявления, адрес клиента этим не подтверждён',
                    ('DOC-L0699','DOC-L0809'), action='question',
                    reply='Объявление размещено в городе ' + known['city'] + '. По какому адресу нужна помощь?')
    if re.search(r"\b[а-яё-]+\s+(?:край|област[ьи]|обл\.)\b|\bреспублик[ае]\s+[а-яё-]+", last, re.IGNORECASE) and not assistant_qualifiers.client_city(messages):
        return stop("Указан регион без подтверждённого города: оператор проверяет территорию", ("DOC-L0809", "DOC-L0810"))
    scope = assistant_catalog.choose(contact_facts.intent_text(text, facts), known)
    if scope.get('operator_scope'):
        return stop(scope['reason'], scope['rules'])
    if (logistics and logistics['kind'] == 'pickup'
            and not photo_permission and not callback_request
            and scope['status'] == 'supported'
            and scope.get('items') and all(item['family'] == 'furniture' for item in scope['items'])):
        result['service'] = scope
        result['rule_ids'] = list(dict.fromkeys(scope['rules'] + logistics['source_ids']))
        answer = 'Получение и перенос мебели нужно уточнить у филиала; пока не подтверждаю.'
        if not logistics['assembly']:
            return stop('Отдельная перевозка не подтверждена профильным правилом сборки: требуется уточнение филиала',
                        ('DOC-L0453',), action='handoff', reply=answer)
        result['required_text'] = ['Со сборкой мебели помогу.', answer]
        result['pickup_delivery_condition'] = logistics
        if logistics['mandatory']:
            return stop('Клиенту нужна сборка только вместе с неподтверждённым получением: сначала уточнение филиала',
                        result['rule_ids'], action='handoff',
                        reply='Заказ на оба условия пока не подтверждён.')
        result['next_question'] = dict(kind='pickup_condition',
            question='Нужна сборка отдельно от получения?', groups=[['сборк'], ['отдельно'], ['получен']])
        price_clauses = re.split(r'[.!?;\n]+', last)
        if any(re.search(r'цен|стоим|сколько', clause, re.I)
               and not re.search(r'достав|получен|перевоз|забрат|забер|перенос', clause, re.I)
               for clause in price_clauses):
            result.update(action='price', mandatory_price=dict(
                reply='Сборка мебели — от 1500 рублей. Нужна сборка отдельно от получения?',
                rules=['DOC-L0326'], amounts=[1500]))
        return result
    if facts["phone_needs_confirmation"]:
        return stop(
            "Нужно выбрать номер, на который звонить",
            ("TG1-668", "TG2-304"),
            "question",
            "На какой из указанных номеров вам звонить?",
        )
    if facts["address_needs_confirmation"]:
        expectation_ids = []
        expectation_replies = service_expectation_questions(messages)
        if (expectation_replies and assistant_catalog.choose(
                contact_facts.intent_text(text, facts), known)['status'] == 'supported'):
            # Answer the current question before clarifying the address.
            # The address conflict never verifies our inventory or outcome.
            result['required_text'] += expectation_replies
            expectation_ids = ['OWNER-NO-PARTS-OR-ONSITE-GUARANTEE-20261020']
        if facts.get("conflicts") and all(c["kind"] == "private_house_with_unit" for c in facts["conflicts"]):
            unit = facts["address"].get("office", "")
            return stop("Указаны и частный дом, и номер квартиры/части дома: нужно уточнить обозначение адреса", expectation_ids, action="question",
                        reply=f"Вы указали квартиру {unit} и частный дом. Уточните, пожалуйста, как обозначена квартира или часть дома для выезда.")
        if facts.get("address_ambiguities") and not facts.get("conflicts"):
            unit = facts["address_ambiguities"][0]["value"]
            return stop("Число после дома не подписано — нужно уточнить квартиру или офис",
                        expectation_ids,
                        action="question", reply=f"Подскажите, пожалуйста, {unit} — это номер квартиры или офиса?")
        current_address = facts.get('address') or {}
        field_evidence = facts.get('evidence') or {}
        literal_complete = (current_address.get('street') and current_address.get('building')
            and facts.get('conflicts') and all(c['kind'] == 'address_changed' for c in facts['conflicts'])
            and all(field_evidence.get('address.' + key, {}).get('message_id') not in (None, '', 'client-card')
                    for key in ('street','building')))
        address_reply = "Уточните, пожалуйста, окончательный адрес для выезда."
        if literal_complete:
            target = current_address['street'] + ', дом ' + current_address['building']
            if len(target) <= 140 and not re.search(r'[\r\n?]', target):
                address_reply = 'Адрес для выезда: ' + target + ', верно?'
        return stop(
            "В переписке менялся адрес — нужно подтвердить итоговый",
            expectation_ids,
            action="question",
            reply=address_reply,
        )
    actual_city = assistant_qualifiers.client_city(messages)
    if (
        actual_city
        and known.get("city")
        and actual_city.lower().replace("ё", "е")
        != known["city"].lower().replace("ё", "е")
    ):
        return stop(
            "Клиент назвал другой город: оператор проверяет источник, филиал и территорию",
            ("DOC-L0809", "DOC-L0810"),
        )
    geo = geography(
        known.get("city"), direction, known.get("latitude"), known.get("longitude")
    )
    result["geography"] = geo
    destination = facts.get('work_destination_hint') or {}
    if destination.get('status') == 'unverified_work_destination':
        geo.update(work_destination_hint=destination, work_address_pending=True,
                   work_location_verified=False, far_trip=None)
        if geo['status'] not in ('closed', 'unknown', 'needs_confirmation'):
            geo.update(status='work_destination_unverified', routing_city=geo.get('crm_city'),
                       routing_city_source='listing_or_branch',
                       reason='Известен филиал объявления; точное место работ и территория не подтверждены')
    result["rule_ids"] += geo.get("rule_ids", [])
    if geo["status"] in ("closed", "unknown", "needs_confirmation"):
        return stop(geo["reason"], result["rule_ids"])
    if not title or not known.get("account_name"):
        return stop(
            "Не заполнены данные объявления или аккаунта: сначала проверить источник"
        )
    if partner == "620" and not any(
        re.search(
            r"частн.*мастер|не.*(?:жкх|управляющ|\bук\b)",
            str(m.get("body") or m.get("text") or ""),
            re.IGNORECASE,
        )
        for m in messages
        if not (m.get("direction") == "in" or m.get("role") in ("client", "user"))
    ):
        result["required_text"].append(
            "Вы обратились к частному мастеру, а не в управляющую компанию."
        )
        result["rule_ids"].append("TG2-198")
    if partner == "619":
        result["rule_ids"].append("TG1-646")
    if known.get("channel") == "jivo" and not (
        known.get("advertiser_name") or known.get("account_name")
    ):
        return stop(
            "Для Jivo обязательно имя мастера или название аккаунта", ("JIVO-IDENTITY",)
        )
    if re.search(
        r"как.{0,15}(?:вас|мастера).{0,15}зовут|ваше имя|имя мастера",
        last,
        re.IGNORECASE,
    ):
        if known.get("introduced_name"):
            return stop(
                "Используем уже названное клиенту имя",
                ("JIVO-IDENTITY",),
                "question",
                "Меня зовут " + known["introduced_name"] + ".",
            )
        return stop(
            "Имя нужно сверить с объявлением либо выбрать оператору и сохранить в комментарии",
            ("JIVO-IDENTITY",),
        )
    pickup_faq = direction=='kp' and bool(re.search(r'\bвы\s+сам(?:и)?\s+забер[её]те\b|'
                                                  r'(?:вам\s+забирать|забирать\s+(?:его|е[её]))|'
                                                  r'(?:сделать|ремонт)\s+дома\s+сразу',last,re.I))
    bring_faq = direction == 'kp' and bool(re.search(
        r'к\s+вам.{0,25}(?:прийти|привезти|принести)|'
        r'\bвам\b.{0,25}(?:привезти|принести)|(?:привезти|принести).{0,25}\bвам\b|'
        r'куда.{0,25}(?:привезти|принести)|(?:можно|могу|хочу|хотел\w*)\s+(?:сам\w*\s+)?(?:привезти|принести)',
        last, re.I))
    remote_faq = direction == 'kp' and _remote_service_question(last)
    onsite_faq = pickup_faq or bring_faq or remote_faq or direction == "kp" and bool(re.search(
        r"где\s+(?:вы\s+)?ремонтируете|к\s+вам.{0,20}(?:прийти|привезти)|\bвам\b.{0,25}(?:привезти|принести)|(?:привезти|принести).{0,25}\bвам\b|вам.{0,25}(?:материнк|плат|ноутбук|принтер|телевизор).{0,15}отда(?:ть|л)|у\s+вас\s+выезд|вы\s+(?:на\s+)?выезд|выезжаете\s+на\s+(?:дом|адрес)|(?:только\s+)?на\s+выездах\s+(?:работаете|работаешь)",
        last, re.IGNORECASE,
    ))
    if onsite_faq:
        # Explain the offered service mode without inventing a workshop,
        # address, available slot or completed dispatch.
        result["required_text"].append("Мастер выезжает на адрес к клиенту.")
        result['rule_ids'].append('OWNER-KP-ONSITE-ONLY-20261020')
        service_mode_reply = 'Мастер выезжает на адрес к клиенту.'
        if bring_faq:
            service_mode_reply += ' Привоз техники не принимаем.'
        if re.search(r'иногородн|из\s+другого\s+города|не\s+в\s+городе', last, re.I):
            return stop('Объясняем выездной формат иногороднему; фактическое место ещё нужно проверить',
                        ('OWNER-KP-ONSITE-ONLY-20261020', 'DOC-L0809'), action='question',
                        reply=service_mode_reply + ' В каком населённом пункте нужен выезд?')
        if bring_faq:
            return stop('КП работает только на выезде: прямо отвечаем на вопрос о привозе без выдуманной мастерской',
                        ('OWNER-KP-ONSITE-ONLY-20261020',), action='question', reply=service_mode_reply)
        if pickup_faq:
            reply='Мастер выезжает на адрес к клиенту.'
            if assistant_prices.asks(last) or assistant_prices.asks_current(messages):
                reply+=' Стоимость работы можно определить после осмотра.'
            return stop('Объясняем выездной формат и порядок оценки стоимости',('OWNER-KP-ONSITE-ONLY-20261020','KP-L0474'),action='question',reply=reply)
        if remote_faq and not assistant_prices.asks_current(messages):
            return stop('Прямо отвечаем на вопрос об удалённом или выездном формате КП',
                        ('OWNER-KP-ONSITE-ONLY-20261020',), action='question',
                        reply=service_mode_reply)
        if (known.get('city') == 'Екатеринбург' and not facts.get('address', {}).get('building')
                and any(re.search(r'\bв\s+(?:екб|екатеринбург)\b.{0,30}\bпривезти\b', body, re.IGNORECASE)
                        for body in incoming[-4:])):
            return stop('Клиент предложил привезти технику в Екатеринбург: уточняем адрес именно для выезда, мастерскую не обещаем',
                        action='question', reply='Есть ли у вас адрес для выезда в Екатеринбурге?', guard='VERIFY_ONSITE_ADDRESS')
        consent = assistant_prices.consent(messages)
        if consent['status'] in ('pending','accepted') and not assistant_prices.prior_quote_verified(messages,known,consent):
            return stop('Объясняем выездной формат без подтверждения прежней цены, записи или наличия мастерской',
                        ('OWNER-KP-ONSITE-ONLY-20261020',),action='question',reply='Мастер выезжает на адрес к клиенту.')
    graphics=facts.get('graphics_scope',{})
    if direction=='kp' and graphics.get('kind') in ('device_uncertain','standalone_diagnostic'):
        result['rule_ids']+=['DOC-L0124','DOC-L0152','DOC-L0699','DOC-L0700']
        if graphics['kind']=='standalone_diagnostic' or graphics.get('unavailable') or graphics.get('host_confirmation_negative') or graphics.get('asked',0)>=2:
            return stop('Не подтверждена проверка ПК с этой видеокартой: оператор уточняет нужную услугу; диагноз и цену отдельного ремонта не объявляем',result['rule_ids'],guard='VERIFY_GRAPHICS_SCOPE')
        return stop('Упомянут компонент и отсутствие изображения: уточняем, нужна диагностика ПК или отдельная услуга по видеокарте',
                    result['rule_ids'],action='question',reply='Видеокарта установлена в компьютере?',guard='VERIFY_GRAPHICS_SCOPE')
    service = route_service or assistant_catalog.choose(contact_facts.intent_text(text, facts), known)
    optional = facts.get('mixed_optional_work')
    if optional and not route_service:
        service = optional['primary_service']
        result['mixed_optional_work'] = optional
        if optional['disclosure']:
            result['required_text'].append(optional['disclosure'])
        result['rule_ids'] += [optional['rule_id'], 'DOC-L0463']
        result['rule_ids'] += [ref for extra in optional['extras'] for ref in extra['execution_rules']]
    result["service"] = service
    result["rule_ids"] += service["rules"]
    transport_operations = facts.get('furniture_transport_operations')
    if direction == 'mnc' and transport_operations:
        result['furniture_transport_operations'] = transport_operations
        result['service'] = dict(status='unknown',items=[],operator_scope='furniture_transport',
            reason='Запрошены разборка или упаковка мебели: отдельно проверяем допуск и цену с филиалом; будущая сборка их не отменяет',
            rules=['DOC-L0452','DOC-L0453'])
        return stop(result['service']['reason'],['DOC-L0452','DOC-L0453'],guard='VERIFY_FURNITURE_TRANSPORT_SCOPE')
    if (any(item['family'] in ('tv','monitor','printer') for item in service.get('items', []))
            and re.search(r'где\s+(?:это\s+|е[её]\s+|его\s+|остальное\s+)?(?:можно\s+)?(?:посмотр|найти)|остальное\s+где\s+посмотр', last, re.I)
            and re.search(r'модел', previous_out, re.I)):
        return stop('Клиент спрашивает, где посмотреть модель техники: отвечаем на вопрос без повторного запроса известной марки',
                    result['rule_ids'], action='question',
                    reply='Модель обычно указана на наклейке сзади или снизу корпуса. Посмотрите, пожалуйста, что там написано.')
    route = crm_branch_route(known, service)
    if route:
        result["crm_route"] = route
        result["rule_ids"].append(route["rule_id"])
        if route["mixed_work"]:
            return stop("Сантехника и другие работы Красноярска требуют разделения по филиалам оператором", result["rule_ids"])
    withdrawn = {s["id"] for s in registry()["sources"] if s.get("active_primary") is False}
    if withdrawn.intersection(service["rules"]):
        return stop("Правило изменилось в первоисточнике: нужна проверка оператора", result["rule_ids"])
    photo_clarification = photo_work_unspecified(messages, known, facts)
    if photo_clarification and service['status'] in ('unknown', 'supported'):
        result['service'] = dict(status='unknown', items=[],
            reason='Желаемое действие по просмотренному фото пока не названо', rules=['DOC-L0699', 'DOC-L0700'])
        result['photo_work_clarification'] = photo_clarification
        result['next_question'] = dict(kind='photo_requested_work', question='Что требуется сделать?',
                                       groups=[['что'], ['сдела']])
        result['rule_ids'] = ['DOC-L0699', 'DOC-L0700', 'OWNER-CLIENT-REPORTED-SCOPE-20261019']
        return result
    generic = bool(
        re.fullmatch(
            r"[\s!?. ,]*(?:(?:здравствуйте|добрый (?:день|вечер)|доброе утро|привет)[\s!?. ,]*)?"
            r"(?:здравствуйте|добрый (?:день|вечер)|доброе утро|привет|можно (?:задать )?вопрос|вы на связи|вы мастер|"
            r"нужен (?:мастер|сантехник|электрик)|можете помочь|какая информация от меня нужна для работы)[\s!?. ,]*",
            re.sub(r'\s+', ' ', last),
            re.IGNORECASE,
        )
    )
    first_question = [m for m in current_enquiry if m.get('direction') == 'in']
    if (len(first_question) == 1 and not any(m.get('direction') == 'out' for m in current_enquiry)
            and not first_question[0].get('attachments')
            and re.fullmatch(r'\s*(?:(?:здравствуйте|добрый\s+день|доброе\s+утро|добрый\s+вечер)[,!.\s]*)?'
                             r'(?:подскажите[,\s]*(?:пожалуйста[,\s]*)?)?'
                             r'(?:это\s+вс[её][,!?\s]*)?(?:уже\s+)?ничего\s+'
                             r'(?:не\s+сделать|нельзя\s+сделать|сделать\s+нельзя)\s*[?!.,]*\s*', last, re.I)):
        generic = True  # The actual problem is still missing, not a diagnosis from the listing.
    generic = generic or bool(re.search(r'\bна\s+когда\s+можно\s+записаться\b', last, re.I))
    callout_words = set(re.findall(r'[а-яё]+', last.lower()))
    callout_only = bool(direction == 'mnc' and re.search(r'вызов|выезд|приехать|приезд', last, re.I)
            and assistant_prices.asks_current(messages)
            and callout_words <= {'здравствуйте','доброе','утро','добрый','день','вечер','подскажите','пожалуйста',
                'за','вызов','выезд','приехать','приезд','сколько','цена','стоимость','без','работы','стоит',
                'будет','у','вас','один','только','на','дом','по','цене','вы','деньги','берете','берёте',
                'бесплатно','бесплатный','бесплатная','бесплатен','платный','платная','оплата','платить',
                'стоят','стоить','за','ли','это','а','и','скажите','платно','нужно','рублей','рубля','руб','р'})
    if callout_only:
        generic = True
    if (service['status'] == 'unknown' and re.search(r'за\s+городом\s+выезжаете|выезжаете\s+за\s+город', last, re.I)):
        return stop('Населённый пункт и задача ещё не названы: не обещаем территорию или время выезда',
                    ('DOC-L0623','DOC-L0700'), action='question', reply='В каком населённом пункте нужна помощь и что требуется сделать?')
    self_introduction = bool(re.fullmatch(r'\s*это\s+я\s+(?-i:[А-ЯЁ][а-яё-]{1,39})(?:\s+(?-i:[А-ЯЁ][а-яё-]{1,39})){0,2}[.!\s]*', last, re.IGNORECASE))
    if service["status"] == "unknown" and (generic or onsite_faq or self_introduction):
        state = qualification_state.inspect(messages)
        if state["problem"]["asked"] >= 2:
            return stop(
                "Не удалось уточнить проблему: нужен оператор",
                ("DOC-L0699", "DOC-L0700"),
            )
        result["next_question"] = qualification_state.question("problem", state)
        if callout_only:
            price = assistant_prices.answer(messages, known, text)
            if price.get('handoff'):
                return stop(price['handoff'], price.get('rules', ['DOC-L0757']))
            result['next_question'].update(question='Что требуется сделать?', groups=[['что'], ['сдела']])
            result.update(action='price', mandatory_price=dict(price,
                reply=price['reply'] + ' ' + result['next_question']['question']))
        result["greeting_allowed"] = first_reply_required(messages)
        result["rule_ids"] = ["DOC-L0699", "DOC-L0700"]
        return result
    if service['status']=='unknown' and direction=='mnc':
        if (re.search(r'сантехник', title, re.I)
                and re.search(r'течь|протек|затопил', text, re.I)):
            state = qualification_state.inspect(messages)
            if state['leak_location']['asked']>=2 or state['leak_location']['status']=='unavailable':
                return stop('Не удалось уточнить источник течи: оператор проверяет состав сантехнических работ', ('DOC-L0700','DOC-L0282'))
            result['next_question']=qualification_state.question('leak_location',state)
            result['rule_ids']=['DOC-L0700','DOC-L0282']
            return result
        if (re.search(r'электрик', title, re.I)
                and re.search(r'вырвал[^.!?\n]{0,20}из\s+стен', text, re.I)):
            asked=sum(m.get('direction')=='out' and bool(re.search(r'что\s+именно.{0,20}замен|что\s+именно.{0,20}вырв',m['body'],re.I)) for m in messages)
            if asked>=2:
                return stop('Не удалось уточнить предмет электротехнической работы: нужен оператор', ('DOC-L0700',))
            result['next_question']=dict(kind='electrical_object',question='Что именно нужно заменить?',groups=[['что'],['замен']])
            result['rule_ids']=['DOC-L0700']
            return result
    if service['status']=='unknown' and direction=='kp':
        question = None
        # A viewed image has no body. Preserve the client's unresolved task,
        # without turning image metadata or the listing into a requested job.
        clarification_text = next((body for body in reversed(incoming) if body.strip()),'') if messages[-1].get('media_reviewed') else last
        if re.search(r'диагностик', last, re.I) and assistant_prices.asks(last):
            question = dict(kind='diagnostic_device',question='Для какой техники нужна диагностика?',groups=[['техник'],['диагност']])
        elif re.search(r'программ', last, re.I) and re.search(r'уставить|установ|поставить', last, re.I):
            question = dict(kind='software_task',question='Какую программу и на какое устройство нужно установить?',groups=[['программ'],['устройств']])
        elif re.search(r'такая\s+проблема|эта\s+проблема|такой\s+случай',last,re.I):
            state = qualification_state.inspect(messages)
            if state['problem']['asked']>=2:
                return stop('Не удалось уточнить проблему: нужен оператор',('DOC-L0699','DOC-L0700'))
            question = qualification_state.question('problem',state)
        elif (re.search(r'роутер|wi[-\s]?fi|вай.?фай',title,re.I)
              and re.search(r'wi[-\s]?fi|вай.?фай',clarification_text,re.I)):
            if sum(m.get('direction')=='out' and bool(re.search(r'подключ.*роутер|настро.*wi.?fi',m['body'],re.I)) for m in messages)>=2:
                return stop('Не уточнена задача Wi-Fi: нужен оператор',('DOC-L0699','DOC-L0700'))
            question = dict(kind='router_task',question='Что требуется: подключить роутер или настроить Wi-Fi?',groups=[['подключ','настро'],['роутер','wi-fi']])
        elif (re.search(r'разблок',text,re.I) and re.search(r'андроид|android',text,re.I)
              and not re.search(r'ми\s*аккаунт|mi\s*account|icloud|google|экран.{0,15}парол|парол.{0,15}экрана',text,re.I)):
            if sum(m.get('direction')=='out' and bool(re.search(r'экран.{0,35}аккаунт|аккаунт.{0,35}экран',m['body'],re.I)) for m in messages)>=2:
                return stop('Не удалось уточнить тип блокировки телефона: нужен оператор',('DOC-L0699','DOC-L0700'))
            question = dict(kind='phone_lock',question='Что заблокировано: экран телефона или аккаунт?',groups=[['экран'],['аккаунт']])
        if question:
            result['next_question']=question
            result['rule_ids']=['DOC-L0699','DOC-L0700']
            return result
    if (service['status']=='unknown' and direction=='mnc' and re.search(r'мебел|сборк',title,re.I)
            and re.search(r'модул',last,re.I) and re.search(r'скрин|фото',last,re.I)):
        attempts=sum(m.get('direction')=='out' and bool(re.search(r'собрать.{0,25}отремонтировать|отремонтировать.{0,25}собрать',m['body'],re.I)) for m in messages)
        if attempts>=2:
            return stop('Не уточнена задача по мебели: нужен оператор',('DOC-L0699','DOC-L0700'))
        result['next_question']=dict(kind='furniture_task',question='Что требуется: собрать или отремонтировать мебель?',groups=[['собра'],['отремонт','мебел']])
        result['rule_ids']=['DOC-L0699','DOC-L0700']
        return result
    if (service['status'] == 'unknown' and direction == 'kp'
            and re.search(r'блок\w*\s+питани', text, re.I) and re.search(r'ремонт|почин', last, re.I)):
        # A named component/model does not establish its appliance type. This
        # is one clarification, not approval; unknown services stay ineligible
        # for personal automatic intake and the manual form remains unverified.
        if any(m.get('direction') == 'out' and re.search(r'(?:для|от)\s+какой\s+техник', m['body'], re.I) for m in messages):
            return stop('Не уточнена техника для ремонта блока питания: оператор проверяет условия приёма', ('DOC-L0250', 'DOC-L0251'))
        result['next_question'] = dict(kind='component_device', question='Для какой техники требуется ремонт блока питания?', groups=[['какой', 'какая'], ['техник', 'устройств']])
        result['rule_ids'] = ['DOC-L0699', 'DOC-L0700', 'DOC-L0250']
        return result
    if (service['status'] in ('mixed', 'unknown') and direction == 'kp'
            and re.search(r'провод|кабел', text, re.I) and re.search(r'отключить|отрезать|убрать', last, re.I)
            and not re.search(r'интернет|вит\w*\s+пар|оптоволок|сетев\w*\s+кабел|силов|220|высоковольт', text, re.I)):
        return stop('Назначение оставшихся проводов не указано: уточняем область работы, отключение и обрезку не обещаем',
                    ('DOC-L0699','DOC-L0700','DOC-L0311'), action='question',
                    reply='Какие это провода: сетевые или электрические?')
    if (direction == 'mnc' and re.search(r'\bтолько\s+перевезти\b', last, re.I)
            and re.search(r'сборк\w*[^.!?\n]{0,35}не\s+нуж|разборк\w*[^.!?\n]{0,35}не\s+нуж', last, re.I)):
        return stop('Запрошена только перевозка: возможность услуги проверяется отдельно; сборка и разборка клиенту не нужны', ('DOC-L0323',))
    upload = _photo_upload_unblock(messages)
    address_before_photo = (not any(m.get('attachments') or m.get('media_signature') or m.get('media_reviewed')
                                   for m in current_enquiry)
                            and _photo_address_only(last, known, facts)
                            and any(_photo_upload_unblock(current_enquiry[:i + 1])
                                    for i in range(len(current_enquiry) - 1)))
    upload_context_only = all(
        _photo_upload_unblock(current_enquiry[:i + 1])
        or _photo_address_only(m.get('body'), known, facts)
        or re.fullmatch(r'\s*(?:здравствуйте|добрый\s+(?:день|вечер)|доброе\s+утро)?[!.\s]*', m.get('body', ''), re.I)
        for i, m in enumerate(current_enquiry)
        if m.get('direction') == 'in' and m.get('sender_type', 'client') in ('client', ''))
    if (direction in ('mnc', 'kp') and service['status'] in ('unknown', 'supported')
            and (service['status'] == 'supported' or upload_context_only)
            and not assistant_prices.asks_current(messages) and (upload or address_before_photo)):
        if photo_reply_progress(messages, known, facts):
            return stop('На просьбу написать уже есть ответ сотрудника; адрес сохранён, ожидаем обещанное фото',
                        ('DOC-L0699', 'DOC-L0700'), action='wait')
        return stop('Клиенту нужен ответ для отправки фото: принимаем фото, вид работ ещё не подтверждён',
                    ('DOC-L0699', 'DOC-L0700'), action='question',
                    reply='Пришлите, пожалуйста, фото.')
    if service["status"] in ("agree", "conflict", "route", "unknown", "mixed"):
        reason = service["reason"] + (". " + route["approval_instruction"] if route else "")
        return stop(reason, result["rule_ids"])
    if service["status"] == "refuse":
        family = service["items"][0]["family"]
        if (service['items'][0]['id'] == 'gas'
                and re.search(r'какого|какому|кого', last, re.I)
                and re.search(r'мастер|специалист', last, re.I)
                and re.search(r'искать|обрат|нужен', last, re.I)):
            return stop('Газовая работа исключена: клиент спрашивает категорию профильного мастера',
                        result['rule_ids'], 'refuse', 'Нужен мастер по газовому оборудованию.')
        reply = (
            "К сожалению, с такой неисправностью телевизора не смогу помочь."
            if service['items'][0]['id'] == 'tv-bands'
            else
            "К сожалению, ремонтом матрицы телевизора не занимаюсь."
            if family == "tv"
            else "К сожалению, с газовым оборудованием не работаю."
            if service["items"][0]["id"] == "gas"
            else "К сожалению, вскрытием замков не занимаюсь."
        )
        return stop(service["reason"], result["rule_ids"], "refuse", reply)
    if (known.get('white') or partner == '723') and direction == 'bt':
        return stop('Белая заявка не создаётся в БТ: оператор проверяет допустимое направление', ('TGAVITO-16610',))
    if known.get('channel') == 'jivo' and direction == 'bt':
        return stop('Jivo БТ: оператор проверяет филиал БТ 2; первый филиал только после подтверждённого отказа второго', ('TGAVITO-18',))
    if (caller_id and caller_id['reply_due'] and not assistant_prices.asks_current(messages)):
        if not caller_id['customer_contact_verified']:
            return stop('Клиент хочет сохранить номер для приёма звонка: сначала нужен его контакт, отказа нет',
                        (caller_id['rule_id'],), action='question',
                        reply='Подскажите, пожалуйста, ваш номер телефона?')
        return stop('Номер получен для дозвона и сохранения: оператор проверяет получателя, время и возможность позвонить; затем «Пару минут, наберу вам» и звонок',
                    (caller_id['rule_id'],), guard='VERIFY_CALLER_ID_MANUAL_CALL')
    if service['status'] == 'supported':
        if direction == 'mnc' and (diagram_answer := _assembly_diagram_answer(messages, service)):
            return stop('Отвечаем по проверенной схеме, комплектность по изображению не подтверждаем',
                        ('DOC-L0324', 'OWNER-NO-PARTS-OR-ONSITE-GUARANTEE-20261020'),
                        action='question', reply=diagram_answer)
        if (direction == 'mnc' and any(item['family'] == 'furniture' for item in service['items'])
                and re.search(r'перевоз|перевезти|привезти', last, re.I)
                and re.search(r'разобрать|разборк', last, re.I) and re.search(r'собрать|сборк', last, re.I)
                and not re.search(r'перевоз\w*[^.!?\n]{0,30}(?:сам|не\s+нуж|организую)|не\s+нуж\w*[^.!?\n]{0,30}перевоз', last, re.I)):
            result['required_text'].append('Разборку и сборку мебели принимаем. Возможность перевозки нужно согласовать отдельно.')
            result['rule_ids'].append('DOC-L0323')
        result['rule_ids'].append('OWNER-CLIENT-REPORTED-ACCEPTANCE-20261020')
        expectation_replies = service_expectation_questions(messages)
        if expectation_replies:
            result['required_text'] += expectation_replies
            result['rule_ids'].append('OWNER-NO-PARTS-OR-ONSITE-GUARANTEE-20261020')
    if service['status'] == 'supported' and direction == 'mnc' and assistant_qualifiers.additional_work_question(messages):
        result['next_question'] = dict(kind='additional_work', question='Какие ещё работы нужно выполнить?', groups=[['какие'], ['работ']])
        result['rule_ids'] += ['DOC-L0699', 'DOC-L0700', 'DOC-L0459']
        return result
    intake_question = intake_question_context(messages, known, service)
    if intake_question:
        result['intake_question_context'] = intake_question
        if 'process' in intake_question['kind']:
            result['required_text'].append('Работаем с выездом. До оформления заявки уточним условия работы.')
        if ('capability' in intake_question['kind']
                and not any(re.search(r'помогу|помочь', phrase, re.I) for phrase in result['required_text'])):
            result['required_text'].append('С такой задачей могу помочь.')
        result['rule_ids'] += ['DOC-L0699', 'DOC-L0700']
    drain_clarification = assistant_qualifiers.toilet_drain_clarification(messages, known, service, facts)
    clog_context = facts.get('clog_work_context') or {}
    if (direction == 'mnc' and service['status'] == 'supported'
            and any(item['id'] in ('toilet', 'sink', 'tap', 'pipes', 'drain') for item in service['items'])
            and messages and contact_facts._client_intent_message(messages[-1])
            and any(row.get('message_id') == messages[-1].get('id')
                    and row.get('reason') == 'conditional'
                    for row in clog_context.get('excluded_reports', []))
            and re.search(r'сколько|стоимост|цен[аыу]', last, re.I)):
        amount = 800 if known.get('city') == 'Москва' else 500
        return stop('Условный вопрос о цене прочистки не подтверждает причину и заказ этой работы',
                    ('DOC-L0499', 'DOC-L0699', 'DOC-L0700'), action='question',
                    reply=f'Если потребуется устранение засора, стоимость — {amount} рублей за погонный метр. По описанию точную причину не определить.')
    if drain_clarification:
        result['clog_clarification_evidence'] = drain_clarification
        if drain_clarification['asked'] >= 2:
            return stop('Не удалось уточнить, требуется ли устранение засора: оператор проверяет описанную проблему',
                        ('DOC-L0699', 'DOC-L0700', 'DOC-L0292'))
        if drain_clarification['cause_unknown']:
            result['required_text'].append('По описанию точную причину не определить.')
        else:
            result['next_question'] = dict(kind='clog_confirmation', question='У вас засор в унитазе?',
                                           groups=[['засор']])
            result['rule_ids'] += ['DOC-L0699', 'DOC-L0700', 'DOC-L0292']
            return result
    state = qualification_state.inspect(messages)
    error_images=[(i,m['media_observation']) for i,m in enumerate(messages)
                  if m.get('direction')=='in' and m.get('media_reviewed') and m.get('media_observation',{}).get('content_kind')=='device_message']
    families={item['family'] for item in service['items']}
    if error_images:
        index,error=error_images[-1]
        relevant={'xbox_live':'console','windows':'pc','printer':'printer'}.get(error.get('error_system')) in families
        new_request=any(m.get('direction')=='in' and re.search(r'новая\s+заявка|новый\s+заказ|по\s+другому\s+вопросу|теперь\s+нужно',m['body'],re.I) for m in messages[index+1:])
        context=state['error_context']
        if relevant and not new_request and context['status']!='answered':
            if context['status']=='unavailable' or context['asked']>=2:
                return stop('Не удалось уточнить действие, при котором появляется сообщение устройства: нужен оператор',('DOC-L0699','DOC-L0700'))
            result['qualification']=state
            result['next_question']=qualification_state.question('error_context',state)
            result['rule_ids']+=['DOC-L0699','DOC-L0700']
            return result
    if (any(item['family']=='console' for item in service['items']) and state['problem']['status']=='missing'
            and any(m.get('direction')=='in' and m.get('media_reviewed') and m.get('media_observation',{}).get('content_kind')=='other' for m in messages)):
        return stop('На просмотренном изображении не сохранены признаки сообщения устройства: оператор разбирает ошибку без догадок о поломке',('DOC-L0699','DOC-L0700'),guard='VERIFY_REVIEWED_DEVICE_MESSAGE')
    if (any(item['id']=='tv' for item in service['items'])
            and re.search(r'пропал\w*\s+сигнал|не\s+ловит|нет\s+сигнала',text,re.I)
            and not re.search(r'разбит|матриц|гнезд|пайк|сгор',text,re.I)
            and not any(m.get('direction')=='out' and re.search(r'от\s+чего\s+канал|через\s+что.{0,20}канал|канал.{0,35}(?:приставк|антенн|интернет)',m['body'],re.I) for m in messages)):
        result['next_question']=dict(kind='tv_signal_source',question='Каналы у вас через приставку, антенну или интернет?',groups=[['канал'],['приставк','антенн','интернет']])
        result['rule_ids']+=['DOC-L0197','DOC-L0203','DOC-L0205']
        return result
    if qualification_state.needs_client_age(known, service):
        age = qualification_state.client_age(messages)
        result['rule_ids'].append('TGAVITO-23005')
        if age['status'] == 'minor' and adult['status'] != 'confirmed':
            return stop('Клиент несовершеннолетний: оператор уточняет присутствие совершеннолетнего для оформления документов', ('TGAVITO-23005', 'DOC-L1572', 'DOC-L1573'))
        if age['status'] == 'unavailable' or age['asked'] >= 2 and age['status'] not in ('adult', 'minor'):
            return stop('Не удалось подтвердить возраст клиента: нужен оператор', ('TGAVITO-23005',))
    issue = assistant_catalog.condition_issue(service, state, text)
    if issue:
        reason = issue[0] + (". " + route["approval_instruction"] if route and "согласован" in issue[0] else "")
        return stop(reason, result["rule_ids"] + issue[1])
    if (any('support' in item.get('questions', []) for item in service['items'])
            and state['support']['status'] == 'uncertain'):
        if state['support']['asked'] >= 2:
            return stop('Наличие закладной не удалось подтвердить: оператор проверяет условия крепления', ('DOC-L0304',))
        result['next_question'] = dict(kind='support', question='Сможете проверить, есть ли закладная под люстру?', groups=[['закладн'], ['провер']])
        result['rule_ids'] += ['DOC-L0304']
        return result
    if (any(item['id'] == 'pipes' for item in service['items'])
            and re.search(r'(?:слив\w*\s+унитаз|с\s+унитаз\w*[^.!?\n]{0,30}мест\w*\s+соединен)', text, re.I)
            and re.search(r'замен\w*[^.!?\n]{0,40}пластик', text, re.I)
            and not re.search(r'стояк|только\s+(?:соединен|участок)|участок\s+труб', text, re.I)):
        attempts = sum(m.get('direction') == 'out' and bool(re.search(r'соединен[^.!?\n]{0,40}стояк', m['body'], re.I)) for m in messages)
        if attempts >= 2:
            return stop('Не уточнено, отдельное соединение или стояк: оператор проверяет объём замены трубы', ('DOC-L0284','DOC-L0285'))
        return stop('Металлическая труба меняется на пластиковую: уточняем только границу работ, не отказываем по материалу',
                    ('DOC-L0284','DOC-L0285'), action='question', reply='Нужно заменить соединение унитаза или сам стояк?')
    if (any('height' in item.get('questions', []) for item in service['items'])
            and state['height']['status'] == 'unavailable'):
        return stop('Клиент не знает высоту: оператор проверяет условия, неизвестное значение не угадываем и не переспрашиваем', ('DOC-L0303', 'DOC-L0316'))
    result["qualification"] = {
        key: {"status": row["status"], "asked": row["asked"], "value": row.get("value", ""),
              "message_id": row.get("message_id", ""), "evidence_source": row.get("evidence_source", ""),
              **({field: row[field] for field in ('components', 'missing_components', 'responsibility_scope')
                    if field in row} if key == 'decision_maker' else {}),
              **({field: row[field] for field in ('question_message_id', 'question_quote', 'quote',
                    'availability_subject', 'availability_scope', 'availability_status',
                    'present_stock_confirmed', 'completeness_confirmed') if field in row} if key == 'materials' else {}),
              **({field: row[field] for field in ('model', 'manufacturer_source_url', 'interpretation')
                    if field in row} if row.get('evidence_source') in ('manufacturer_model_code', 'manufacturer_model_reference') else {})}
        for key, row in state.items()
        if row["status"] != "missing" or row["asked"]
    }
    result["greeting_allowed"] = first_reply_required(messages)
    critical = [key for item in service['items'] for key in item.get('questions', []) if key in ('coffee_vending', 'coffee_type', 'cable_type', 'cable_operation', 'lighting_object')]
    for key in critical:
        if state[key]['status'] in ('missing', 'uncertain', 'unavailable'):
            result['next_question'] = qualification_state.question(key, state)
            if state[key]['status'] == 'unavailable' or state[key]['asked'] >= 2:
                return stop('Не удалось получить обязательное уточнение типа техники/работы: нужен оператор', result['rule_ids'])
            return result
    if (service['status'] == 'supported' and any(item['family'] == 'furniture' for item in service['items'])
            and re.search(r'в\s+будущем', last, re.IGNORECASE) and re.search(r'возможност|можно|позвать', last, re.IGNORECASE)):
        result['crm_flags']['future_only'] = True
        return stop('Клиент спрашивает об услуге на будущее: отвечаем о сборке, не собираем заявку сейчас', result['rule_ids'], 'question',
                    'По сборке мебели можно обратиться. Напишите, когда понадобится услуга.')
    if (direction == 'kp' and facts.get('standalone_printer_diagnostic')
            and re.search(r'\bформат\w*\s*[аa][012]\b', facts['standalone_printer_diagnostic']['quote'], re.I)
            and not re.search(r'\bне\s+формат\w*\s*[аa][012]\b', facts['standalone_printer_diagnostic']['quote'], re.I)):
        return stop('Указан формат принтера вне явно разрешённых А3/А4: оператор проверяет допустимость диагностики',
                    ('DOC-L0181', 'DOC-L0182', 'DOC-L0257'))
    if (direction == 'kp' and service['status'] == 'supported'
            and facts.get('standalone_printer_diagnostic') and not assistant_prices.asks_current(messages)
            and re.search(r'\b(?:можете|сможете|можно|проводите|делаете|принимаете)\b[^.!?\n]{0,100}диагностик|'
                          r'диагностик\w*[^.!?\n]{0,70}\b(?:можете|сможете|можно)\b', last, re.I)):
        # A supported diagnostic request needs an answer before intake. This
        # accepts the service, never the outcome, inventory or a booked visit.
        result['required_text'].append('Диагностику провести можно.')
        cartridge_reports = [m['body'] for m in current_enquiry if m.get('direction') == 'in'
                             and re.search(r'картридж', m['body'], re.I)]
        if cartridge_reports and re.search(r'без\s+картридж|картридж\w*\s+(?:у\s+меня\s+)?нет|'
                                            r'нет\s+(?:у\s+меня\s+)?картридж', cartridge_reports[-1], re.I):
            result['required_text'].append('Полную работоспособность без картриджей заранее не подтверждаю.')
        result['rule_ids'] += [ref for ref in ('DOC-L0257', 'TG1-611', assistant_prices.DIAGNOSTIC_ONLY_RULE)
                               if ref not in result['rule_ids']]
    if (direction == 'kp' and service['status'] == 'supported'
            and assistant_catalog.ordinary_office_installation(last)
            and not assistant_prices.asks_current(messages)
            and re.search(r'\b(?:вы\s+)?(?:устанавливаете|ставите)|'
                          r'\b(?:можете|сможете|можно)\b[^.!?\n]{0,45}(?:установ|постав)', last, re.I)):
        result['required_text'].append('С установкой программ могу помочь.')
        result['rule_ids'] += ['DOC-L0125', 'DOC-L0541']
    if (direction == 'kp' and service['status'] == 'supported'
            and assistant_catalog.ordinary_office_work(last)
            and assistant_catalog.office_fault_request(last)
            and re.search(r'\b(?:можете|сможете|можно)\b[^.!?\n]{0,30}помо[чг]', last, re.I)):
        result['required_text']=[text for text in result['required_text'] if text!='С такой задачей могу помочь.']
        result['required_text'].append('С программами могу помочь.')
        result['rule_ids'] += ['DOC-L0125']
    clarification = assistant_prices.clarify_named_tariff(messages, known)
    if clarification:
        result.update(action='price', mandatory_price=clarification)
        return result
    if assistant_prices.unverified_bare_quote(messages):
        return stop('Ранее явно названа стоимость без обозначения валюты: оператор проверяет прежнюю озвучку и договорённость', ('DOC-L0713', 'DOC-L0774'))
    consent = assistant_prices.consent(messages)
    result["crm_flags"]["price_consent"] = consent["status"]
    furniture_quote = assistant_prices.furniture_minimum_quote(messages, known, consent)
    if furniture_quote:
        result['rule_ids'] += [ref for ref in furniture_quote['rules'] if ref not in result['rule_ids']]
    if consent['status'] == 'conditional':
        return stop('Клиент согласен только при ограничении бюджета: максимальная стоимость не подтверждена, оператор проверяет потолок цены', ('DOC-L0774', 'DOC-L0777'))
    if consent["status"] == "declined":
        return stop(
            "Клиент не согласен с озвученной стоимостью: заявку не подтверждаем",
            ("DOC-L0774", "DOC-L0776", "DOC-L0777"),
        )
    if consent["status"] in ("pending", "accepted") and not assistant_prices.prior_quote_verified(messages, known, consent):
        conflict = assistant_prices.quoted_service_conflict(messages, consent)
        if conflict:
            result['price_service_conflict'] = conflict
            return stop(conflict['reason'], conflict['rules'])
        return stop("Ранее названная стоимость не подтверждена текущим правилом и этапом: оператор проверяет договорённость", ("DOC-L0713", "DOC-L0774", "DOC-L0777"))
    if (furniture_quote and consent['status'] == 'pending'
            and (assistant_prices.asks_current(messages) or re.search(r'ценник', last, re.I))
            and re.search(r'ценник|мне\s+надо\s+сейчас\s+знать\s+по\s+цене', last, re.I)):
        # An unresolved objection to an open-ended assembly price is not
        # consent, a fixed total, a visit request or the next phone question.
        result.update(action='price', mandatory_price=dict(
            reply='Сборка — от 1500 рублей. Это минимум; итоговая стоимость определяется после осмотра.',
            amounts=[1500], rules=furniture_quote['rules']))
        return result
    if (consent['status'] == 'pending' and printer_scope
            and printer_scope['kind'] == 'adf_cover'
            and assistant_prices.prior_quote_verified(messages, known, consent)):
        turn = []
        for message in reversed(messages):
            if message.get('direction') == 'out':
                break
            if message.get('direction') == 'in':
                turn.append(message['body'])
        if re.search(r'до\s+скольк|диап[ао][зщ]он|верхн\w*[^.!?]{0,25}(?:цен|стоим|границ)', ' '.join(turn), re.I):
            return stop('Клиент спрашивает верхнюю границу, а не принимает минимум; потолок без осмотра не подтверждён',
                        ('DOC-L0713', 'DOC-L0743', 'DOC-L0774'), action='question',
                        reply='Верхнюю границу стоимости заранее не подтверждаю. Точную стоимость определю после осмотра.')
    # A topical acknowledgement is considered only after the common existing
    # request, complaint, source, media and prior-price guards above.
    if (printer_scope and printer_scope['kind'] == 'adf_cover'
            and re.fullmatch(r'\s*ясно[.!\s]*', last, re.I)
            and consent['status'] == 'pending'
            and assistant_prices.prior_quote_verified(messages, known, consent)):
        return stop('Краткое понимание после озвучки не является новым заказом или согласием на визит',
                    ('DOC-L0743', 'DOC-L0774'), action='wait',
                    reply='Понял. Если помощь понадобится, напишите.')
    if (service['status'] == 'supported'
            and re.fullmatch(r'\s*(?:а\s+)?(?:вы\s+(?:фирма|компания)|это\s+(?:фирма|компания))[?! .]*', last, re.I)
            and re.search(r'выезд|на\s+дому', title, re.I)):
        return stop('Отвечаем о подтверждённом выездном формате; юридический статус и личность не выдумываем',
                    ('DOC-L0713', 'DOC-L0757'), action='question',
                    reply='Ремонтируем с выездом на адрес, стоимость согласуем до начала работ.')
    work_time = _current_work_time_question(messages)
    if work_time:
        result['rule_ids'] = list(dict.fromkeys(result['rule_ids']+[WORK_DURATION_RULE]))
        if (assistant_prices.asks_current(messages)
                or assistant_prices.mandatory(messages,known,text)
                or consent['status']=='pending'):
            # Preserve the scoped price stage and its consent/approval guards.
            # The statement adds no numeric duration or future estimate.
            result['required_text'].append(WORK_DURATION_REPLY)
        elif work_time['kind']=='ambiguous':
            result['next_question'] = dict(kind='timing_scope',
                question='Вы про время приезда или сколько займёт работа?',
                groups=[['приезда'],['работ']],source_question=work_time)
            return result
        else:
            question = assistant_qualifiers.next_question(messages,dict(known,service=service),facts)
            reply = WORK_DURATION_REPLY
            if question and not question.get('requires_operator') and question.get('unanswered_attempts',0)<2:
                result['next_question'] = question
                result['required_text'].append(WORK_DURATION_REPLY)
                return result
            return stop('Длительность работ заранее не оцениваем, даже примерно',
                        result['rule_ids'],'question',reply)
    diagnostic_question = diagnostic_continuation_question(messages, known)
    if diagnostic_question:
        result['diagnostic_continuation_question'] = diagnostic_question
        reply = 'При продолжении работ диагностика бесплатная.'
        result['approved_price_reply'] = reply
        return stop('Отвечаем об оплате диагностики при продолжении работ; ремонт ещё не заказан',
                    ('DOC-L0761',), action='question', reply=reply)
    if assistant_prices.conditional_diagnostic_question(messages):
        return stop("Клиент уточняет оплату диагностики при невозможном или невыгодном ремонте: оператор проверяет условия и прежнюю озвучку", ("TG1-611", "DOC-L0774"))
    if consent["status"] == "pending" and not assistant_prices.asks_current(messages):
        timing = _visit_time_answer(messages, known, geo)
        if timing:
            if timing.get('requires_operator'):
                return stop('Перед ответом о времени нужно проверить территорию, норматив или запрошенный интервал',
                            ('DOC-L0809', 'DOC-L0810', 'DOC-L0619'), guard='VERIFY_VISIT_TIME_TERRITORY')
            result['visit_offer'] = timing['offer']
            if timing.get('question'):
                result['visit_time_question'] = timing['question']
            return stop('Отвечаем на вопрос о времени; согласие на цену ещё требуется, запись не подтверждена',
                        ('DOC-L0615', 'DOC-L0619', 'DOC-L0774'), action='question', reply=timing['reply'])
        reply = "Такая стоимость вас устраивает?"
        requested = facts.get('requested_visit') or {}
        if (requested.get('message_id') == messages[-1].get('id')
                and requested.get('status') == 'requested' and requested.get('window')):
            # A time wish is not a price answer. Keep it while obtaining the
            # missing acceptance, without inventing a booked/available slot.
            reply = 'Учту пожелание: ' + requested['window'] + '. ' + reply
        return stop(
            "Нужно явное согласие на уже озвученную стоимость",
            ("DOC-L0774", "DOC-L0777"),
            "question",
            reply,
        )
    mandatory = assistant_prices.mandatory(messages, known, text)
    if mandatory:
        if len(service["items"]) > 1:
            if (direction == 'mnc' and service['status'] == 'supported'
                    and any(item['id'] == 'drain' for item in service['items'])):
                mandatory = dict(mandatory, reply=mandatory['reply'] + ' Остальные работы оцениваются отдельно после осмотра.')
            else:
                return stop("Несколько работ с обязательной стоимостью: оператор проверяет отдельные цены и единицы расчёта", result["rule_ids"])
        result["mandatory_price"] = mandatory
        result["action"] = "price"
        return result
    if photo_permission:
        if deferred:
            preparation = _recontact_callback_preparation(messages, facts, logistics if furniture_deferred else None)
            if preparation:
                result['crm_preparation'] = preparation
        return stop('Клиент спрашивает разрешение прислать фото; содержимое и стоимость по нему ещё не подтверждены',
                    (), 'question', 'Да, можете прислать фото объявления.' if re.search(r'объявлен', last, re.I)
                    else 'Да, можете прислать фото.')
    clarification = qualification_state.client_question_clarification(messages)
    if clarification:
        result['observed_question_clarification'] = clarification
        return stop('Клиент уточняет смысл доставленного вопроса: сначала поясняем нужные сведения о принтерах',
                    ('DOC-L0699', 'DOC-L0700'), action='question', reply=clarification['reply'])
    if assistant_prices.asks_current(messages) and not (drain_clarification and drain_clarification['cause_unknown']):
        return stop("Озвучка цены по текущему этапу", (), "price")
    if callback_request and facts.get('contact_phone_to_use'):
        if not _callback_phone_usable(messages, facts):
            return stop('Номер для обратного звонка отозван и не заменён: оператор уточняет пригодный контакт без подтверждения звонка или записи',
                        guard='VERIFY_CALLBACK_CONTACT')
        preparation = _recontact_callback_preparation(messages, facts, logistics if furniture_deferred else None) if deferred else None
        callback_preparation = dict(
            mode='callback', status='operator_review', ready=False,
            time_policy='client_requested_callback_review', visit_time_confirmed=False,
            can_create_automatically=False, requires_full_qualification_check=True,
            callback_preference=callback_request,
            intent_message_ids=[callback_request['message_id']],
            rule_ids=['DOC-L1290', 'DOC-L1293'],
            reason='Просьба клиента об обратном звонке; выполнение, визит и изменение CRM не подтверждены.')
        if preparation:
            # Preparation time and requested contact time describe different
            # things. Keep the nearest branch normative without erasing the
            # explicit callback's actor, timestamp, interval or source message.
            callback_preparation = dict(preparation, callback_preference=callback_request,
                intent_message_ids=list(dict.fromkeys(preparation['intent_message_ids'] + [callback_request['message_id']])),
                rule_ids=list(dict.fromkeys(preparation['rule_ids'] + callback_preparation['rule_ids'])))
        result['crm_preparation'] = callback_preparation
        reply = ('Понял, сейчас не отвлекаю.' if callback_request['after_minutes'] is not None
                 else 'Понял, нужен обратный звонок.') if callback_request['latest_is_request'] else ''
        return stop('Клиент просит обратный звонок: сохранить номер и предпочтение времени для проверки оператором',
                    ('DOC-L1290', 'DOC-L1293'), action='wait', reply=reply,
                    guard='VERIFY_CLIENT_CALLBACK_REQUEST')
    if geo["status"] == "needs_zone":
        result["missing"].append("map_zone")
    if not facts["contact_phone_to_use"]:
        result["missing"].append("phone")
    if not facts["address"].get("building"):
        result["missing"].append("address")
    if (any(item['family'] == 'fridge' for item in service['items'])
            and re.search(r'неремонтопригод|не\s+подлежит\s+ремонту|ремонт\s+невозможен', last, re.I)
            and re.search(r'\?|это\s+так\b|правда\s+ли\b|верно\s+ли\b', last, re.I)):
        # A question about another technician's conclusion needs an answer
        # before the ordinary model/contact question. It is not our diagnosis,
        # a repair promise, or evidence of a previous order with this service.
        result['required_text'].append('Без осмотра подтвердить, что холодильник не подлежит ремонту, нельзя.')
        result['rule_ids'] += ['DOC-L0699', 'DOC-L0700']
    consultation = (qualification_state.printer_consultation_question(messages)
                    if direction == 'kp' and service['status'] == 'supported'
                    and any(item['family'] == 'printer' for item in service['items']) else None)
    if consultation:
        # Answer the client's actual question before gathering contacts. A
        # hypothesis about drivers and a past cartridge change do not order
        # those operations or establish a faulty component.
        uncertainty = 'По переписке причину точно не определить. Нужно проверить работу принтера.'
        if qualification_state.inspect(messages)['model']['status'] == 'answered':
            return stop('Отвечаем на текущий вопрос о возможной причине, не ставим диагноз и не запрашиваем контакты вместо ответа',
                        ('DOC-L0181', 'DOC-L0700', 'DOC-L1624', 'DOC-L1628'),
                        action='question', reply=uncertainty)
        result['required_text'].append(uncertainty)
        result['rule_ids'] += ['DOC-L0181', 'DOC-L0700', 'DOC-L1624', 'DOC-L1628']
    if known.get('channel') == 'jivo':
        result['rule_ids'].append('JIVO-IDENTITY')
    else:
        result['decision_guards'].append(dict(id='CONTACT-EVIDENCE', message_ids=[m.get('id', '') for m in messages if m.get('direction') == 'in'][-3:]))
    alternative_day = contact_facts.alternative_visit_day_preference(messages)
    if alternative_day and not booking_claim:
        # Answer the current scheduling turn before returning to unfinished
        # qualifications. Their state is preserved; a day preference grants
        # neither service admission nor permission to create an appointment.
        result['visit_day_choice_context'] = alternative_day
        result['next_question'] = dict(kind='visit_day_preference',
            question='На какой день вам будет удобно?', groups=[['какой'], ['день'], ['удобно']])
        result['rule_ids'] = list(dict.fromkeys(result['rule_ids'] + ['DOC-L0699', 'DOC-L0700']))
        return result
    next_question = assistant_qualifiers.next_question(
        messages, dict(known, service=service), facts
    )
    if next_question:
        result['rule_ids'] = list(dict.fromkeys(result['rule_ids'] + next_question.get('rule_ids', [])))
        if next_question.get('kind') == 'materials' and 'materials' not in result['qualification']:
            # A correctly zero attempt count used to hide the sparse missing
            # row. Keep the selected unknown explicit without inventing an ask.
            row = state['materials']
            result['qualification']['materials'] = dict(status=row['status'], asked=row['asked'],
                value=row.get('value',''), message_id=row.get('message_id',''),
                evidence_source=row.get('evidence_source',''))
        if next_question.get('kind') == 'city' and next_question.get('requires_operator'):
            return stop('Клиент прямо указал другой город: оператор проверяет город и территорию выезда по карте, повторять вопрос о городе не нужно',
                        ('DOC-L0809', 'DOC-L0810'), guard='VERIFY_CLIENT_CITY')
    if next_question and (
        next_question.get("requires_operator")
        or next_question.get("unanswered_attempts", 0) >= 2
    ):
        return stop(
            "Обязательное уточнение не удалось получить: нужен оператор",
            result["rule_ids"],
        )
    timing = _visit_time_answer(messages, known, geo)
    if timing:
        if timing.get('requires_operator'):
            return stop('Перед предложением времени нужно проверить территорию и норматив приёма',
                        ('DOC-L0809', 'DOC-L0810'), guard='VERIFY_VISIT_TIME_TERRITORY')
        result['visit_offer'] = timing['offer']
        if timing.get('question'):
            result['visit_time_question'] = timing['question']
        return stop('Отвечаем на прямой вопрос о времени до сбора следующих контактов; визит ещё не подтверждён',
                    ('DOC-L0615', 'DOC-L0619', 'DOC-L0633', 'DOC-L0637'),
                    action='question', reply=timing['reply'])
    if not next_question:
        return stop("Данные собраны: оператор проверяет условия и подтверждает заявку")
    result["next_question"] = next_question
    if (service['status'] == 'supported' and direction == 'bt'
            and any(item['id'] == 'boiler' for item in service['items'])
            and assistant_catalog.service_capability_question(last)):
        result['required_text'].append('Электрические бойлеры ремонтируем.')
        result['rule_ids'] = list(dict.fromkeys(result['rule_ids'] + ['DOC-L0387', 'DOC-L0389']))
    if (service['status'] == 'supported'
            and any(item['id'] == 'furniture' for item in service['items'])
            and assistant_catalog.furniture_parts_replacement_request(text)
            and assistant_catalog.service_capability_question(last)):
        # Answer the direct capability question without promising manufacture,
        # parts in stock, a visit or a successful repair of an unseen item.
        result['required_text'].append('Готовые детали заменить можно.')
        result['rule_ids'] = list(dict.fromkeys(result['rule_ids'] + ['DOC-L0323', 'DOC-L0459']))
    requested = facts.get('requested_visit') or {}
    if (requested.get('message_id') == messages[-1].get('id')
            and requested.get('status') == 'requested' and requested.get('window')
            and next_question.get('kind') not in ('visit', 'time', 'city')):
        # Acknowledge the requested period without promising availability or
        # treating it as a booking. Existing appointment gates run above.
        result['required_text'].append('Учту пожелание: ' + requested['window'] + '.')
    return result


def requests_contact(reply):
    return bool(
        re.search(
            r"номер для связи|контактн\w* (?:номер|телефон)|телефон\w* для связи|ваш\w* телефон|(?:подскажите|оставьте|напишите|назовите|дайте)\s+(?:ваш\s+)?(?:телефон\b|номер\b(?!\s+(?:модел|дом|квартир|комнат|серийн|детал|заказ|заявк)))|созвон|встрет|подъех",
            reply,
            re.IGNORECASE,
        )
    )


GREETING_START = re.compile(
    r"^\s*(?:здравствуйте|добрый (?:день|вечер)|доброе утро)[!,.\s]*",
    re.IGNORECASE,
)


def greeting_violations(reply, decision):
    violations = []
    if decision.get("greeting_required") and not GREETING_START.match(reply or ""):
        violations.append("missing_first_greeting")
    if not decision.get("greeting_allowed", True) and re.search(
        r"здравств|добрый (?:день|вечер)|доброе утро", reply or "", re.IGNORECASE
    ):
        violations.append("repeated_greeting")
    return violations


def compose_reply(reply, decision):
    """Add mandatory first-turn greeting and disclosures on every response path."""
    body = reply.strip()
    if not body:
        return ""
    greeting = ""
    if decision.get("greeting_required"):
        body = GREETING_START.sub("", body, count=1)
        greeting = "Здравствуйте! "
    prefix = [text for text in decision.get("required_text", []) if text not in body]
    return greeting + " ".join(prefix + [body])


def validate_reply(reply, decision, facts):
    violations = []
    if not isinstance(reply, str) or not reply.strip() or len(reply) > 280:
        violations.append("empty_or_long_reply")
        return violations
    violations.extend(service_expectation_violations(reply))
    violations.extend(caller_id_call_violations(reply, decision.get('caller_id_callback')))
    if (contact_phone.find_all(reply)
            and re.search(r'\b(?:мой|наш|свой)\s+(?:номер|телефон)\b',reply,re.I)):
        violations.append('contractor_phone_disclosure')
    optional = decision.get('mixed_optional_work') or facts.get('mixed_optional_work')
    if optional:
        if optional['disclosure'] not in reply:
            violations.append('optional_inspection_caveat_missing')
        if assistant_catalog.optional_execution_claim(reply, optional):
            violations.append('optional_inspection_promoted_to_execution')
    stated_kind = decision.get('printer_stated_scope', {}).get('kind')
    if stated_kind in ('adf_cover', 'dry_ink'):
        for clause in re.split(r'[.!?;\n]+|\bно\b', reply, flags=re.I):
            if re.search(r'не\s+(?:означает|заказыв|прос|треб|подтвержд)|нет\s+запроса', clause, re.I):
                continue
            conversion = stated_kind == 'adf_cover' and re.search(r'переделк|конверси', clause, re.I)
            component = stated_kind == 'dry_ink' and re.search(
                r'(?:замен|помен|заправ|ремонт|прошив)\w*[^.!?]{0,30}(?:картридж|тонер)|'
                r'(?:картридж|тонер)\w*[^.!?]{0,30}(?:замен|помен|заправ|ремонт|прошив)|'
                r'установ\w*[^.!?]{0,30}снпч|снпч[^.!?]{0,30}установ', clause, re.I)
            if conversion or component:
                violations.append('unrequested_printer_component_job')
    if decision.get('printer_stated_scope', {}).get('kind') == 'adf_cover':
        for clause in re.split(r'[.!?;\n]+|\bно\b', reply, flags=re.I):
            if re.search(r'не\s+(?:обещаю|гарантирую|подтверждаю)|не\s+могу\s+(?:обещать|гарантировать|подтвердить)', clause, re.I):
                continue
            if re.search(r'стекл\w*[^.!?]{0,45}(?:останется|сохранится|будет\s+цел|не\s+повредится)|'
                         r'(?:сохраним|сохраню|не\s+повредим|не\s+поврежу)[^.!?]{0,30}стекл', clause, re.I):
                violations.append('unconfirmed_printer_operation_outcome')
        if (re.search(r'(?:мой|мастер\w*|исполнител\w*)[^.!?]{0,30}(?:номер|телефон)|'
                      r'(?:номер|телефон)[^.!?]{0,30}(?:мастер|исполнител)', reply, re.I)
                and contact_phone.find_all(reply)):
            violations.append('unverified_provider_phone')
    if decision.get('photo_work_clarification'):
        violations.extend(photo_unspecified_work_claims(reply))
    if decision.get('pickup_delivery_condition'):
        violations.extend(pickup_delivery_violations(reply))
    if re.search(
        r"\b(?:я|мы)\s+(?:позвоню|перезвоню|перезвоним|свяжусь|свяжемся)|уже\s+(?:позвонил|передал|создал|записал|отправил)|записал вас|вы записаны|заявк\w*.{0,30}(?:оформлена|создана|собрана|передана)|мастер.{0,15}(?:точно|уже|будет|приедет|подъедет|выехал)|подъеду|приеду|могу\s+(?:приехать|подъехать)|"
        r"\bбуду\s+(?:у\s+вас|через|(?:сегодня|завтра)\b|в\s+\d)|"
        r"\b(?:сейчас\s+)?(?:свободен|свободна)\b|"
        r"\b(?:снимаю|сниму|оформлю|оформляю|создам|создаю|отменил|отменю|передам|передаю)\b",
        reply,
        re.IGNORECASE,
    ):
        violations.append("unconfirmed_action_or_visit")
    # Explicit inability to guarantee an outcome is not an affirmative
    # guarantee. Remove only that verb's negated span, so another assertion
    # ("не гарантирую срок, но точно починю") is still checked below.
    diagnosis_view = re.sub(
        r'\bне\s+(?:(?:могу|можем|буду|будем|стану|станем)\s+)?гарантир\w*\b|'
        r'\bгарантировать\s+не\s+(?:могу|можем|буду|будем)\b',
        ' [отказ от гарантии] ', reply, flags=re.I)
    if re.search(
        r"скорее всего|вероятно|понадобится заменить|нужно менять|причина.{0,25}\bв\b|несложно|без проблем|гарантир|"
        r"похоже\s+на|контакты\s+(?:отошли|окисл)|это\s+обычно\s+(?:сервис|голов|подсветк|инвертор)|"
        r"\b(?:починю|исправлю|отремонтирую|сделаю)\b|это\s+чиню|с\s+головой\s+разберусь",
        diagnosis_view,
        re.IGNORECASE,
    ):
        violations.append("unsupported_diagnosis")
    if re.search(
        r"бесплатн|\d+\s*(?:руб|₽|р\b)|(?:стоим|цен[аыу]).{0,25}\d",
        reply,
        re.IGNORECASE,
    ):
        violations.append("unapproved_price")
    if facts["contact_phone_to_use"] and requests_contact(reply):
        violations.append("repeated_phone_request")
    violations.extend(greeting_violations(reply, decision))
    if reply.count("?") > 2:
        violations.append("too_many_questions")
    if re.search(
        r"(?:я|меня зовут)\s+(?:ChatGPT|Claude|бот)|штраф|партн[её]р\s*№|системн.*промпт",
        reply,
        re.IGNORECASE,
    ):
        violations.append("internal_details")
    if decision["action"] != "refuse" and re.search(
        r"не занимаюсь|не работаю|не делаю|не смогу помочь", reply, re.IGNORECASE
    ):
        violations.append("unapproved_refusal")
    question = decision.get("next_question") or {}
    if not qualification_state.question_matches(reply, question):
        violations.append('required_question_missing')
    if (question and 'площад' not in question.get('question', '').lower()
            and re.search(r'\bплощад\w*|\bквадратур\w*', reply, re.I)):
        violations.append('unselected_measurement_question')
    if question and question.get("kind") != "city" and (
        assistant_qualifiers.provider_location_question(reply)
        or re.search(r'в\s+каком\s+городе|какой\s+(?:у\s+вас\s+)?город|ваш\s+город|'
                     r'город\s+(?:вашего\s+)?местоположения|где\s+вы\s+находитесь|вы\s+откуда|'
                     r'(?:подскажите|скажите|укажите|назовите|напишите)[^.!?\n]{0,30}\bгород\b',
                     reply, re.I)
    ):
        violations.append("unselected_city_question")
    for required in decision.get("required_text", []):
        if required not in reply:
            violations.append("missing_required_disclosure")
    return violations
