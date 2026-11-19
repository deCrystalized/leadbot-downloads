"""Read-only lifecycle recommendations; never delivery, CRM writes or grants.

The caller supplies the existing policy decision. Delivery needs an explicit
sent/delivered/read status (not merely out_pending=False), or a confirmed
workflow receipt with kind=outgoing_delivered and its message_id. Verified
branch warranty refusal uses kind=branch_warranty_refusal. Receipts require
confirmed=True and receipt_id; unverified transport flags are insufficient.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math
import re

VERSION = '1'
KP_FOLLOWUP_REPLY = 'Подскажите, вопрос ещё актуален?'
SHORT_PAUSE_GRACE_SECONDS = 60  # Conversation pacing, not a regulatory deadline.
MAX_EXPLICIT_PAUSE_SECONDS = 3600  # Longer requests need review, not silent shortening.
_KP_TIMER_RULES = ['OWNER-KP-SILENCE-20261019', 'KP-L1598']
_UTC = timezone.utc
_CONFIRMED = {'sent', 'delivered', 'read'}
_FAILED = {'failed', 'error', 'cancelled', 'canceled'}
_PENDING = {'pending', 'queued', 'sending'}
_NO_CALLBACK = re.compile(r'не\s+звоните|не\s+(?:надо|нужно)\s+звонить|не\s+хочу\s+звонков|без\s+звонков|только\s+чат|удобнее\s+чат|не\s+беспокойте|не\s+привезли|не\s+доставили|пока\s+нет|сам\w*\s+(?:решил|собрал)', re.I)
_EXISTING_GUARDS = {
    'VERIFY_EXISTING_APPOINTMENT', 'VERIFY_CHANGED_APPOINTMENT',
    'VERIFY_EXISTING_REQUEST', 'VERIFY_PRIOR_CONVERSATION',
    'VERIFY_EQUIPMENT_READINESS', 'VERIFY_EXISTING_COMPLAINT',
    'VERIFY_VISIT_COUNTERPROPOSAL',
}
_EXISTING_FIELDS = (
    'existing_visit_evidence', 'visit_counterproposal_evidence', 'staff_booking_claim', 'withdrawn_visit_evidence',
    'prior_conversation_evidence', 'equipment_readiness_evidence',
    'existing_price_complaint_evidence', 'existing_visit_complaint_evidence',
    'property_damage_complaint_evidence',
)


def _unique(values):
    return list(dict.fromkeys(str(v) for v in values if v))


def _date(value):
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, _UTC) if math.isfinite(value) else None
        if isinstance(value, str):
            if re.fullmatch(r'\d+(?:\.\d+)?', value):
                return _date(float(value))
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None:
            return value.astimezone(_UTC)
    except (ValueError, OverflowError, TypeError, OSError):
        pass
    return None


def _iso(value):
    return value.isoformat().replace('+00:00', 'Z')


def _messages(messages):
    return [m for m in messages if isinstance(m, dict)
            and m.get('direction') in ('in', 'out')
            and not (m.get('direction') == 'in' and (m.get('out_pending')
                     or str(m.get('delivery_status') or m.get('delivery') or '').lower() in _FAILED | _PENDING))
            and m.get('sender_type') not in ('system', 'avito')
            and not (m.get('direction') == 'in' and m.get('sender_type')
                     in ('bot', 'assistant', 'operator', 'employee'))]


def _body(message):
    return str(message.get('body') or '')


def _receipt(ctx, kind, message_id=None):
    return next((r for r in ctx.get('workflow_receipts', []) or []
                 if isinstance(r, dict) and r.get('kind') == kind
                 and r.get('confirmed') is True and r.get('receipt_id')
                 and (message_id is None or r.get('message_id') == message_id)), None)


def extension_context(ctx, operator_id):
    """Public transport cannot assert a verified server workflow receipt."""
    context = dict(ctx) if isinstance(ctx, dict) else {}
    context.pop('workflow_receipts', None)
    context['assignedToCurrentOperator'] = bool(
        operator_id and context.get('assigneeId') == operator_id)
    return context


def observe_deliveries(store, scope, chat, messages, now=None):
    """Attach server-observed anchors; no raw client timestamp is accepted."""
    instant = datetime.now(_UTC) if now is None else _date(now)
    if instant is None:
        return
    from assistant_store import digest
    confirmed, reset = [], []
    outgoing = [message for message in messages if message.get('direction') == 'out']
    for message in outgoing:
        message['delivery_clock_unverified'] = True
    for message in outgoing[-2:]:
        created = _date(message.get('created_at'))
        if message.get('id') and created and created <= instant:
            identity = digest([message['id'], message['created_at'], _body(message)])
            delivery = _delivery(message, {})
            if delivery == 'confirmed':
                confirmed.append((identity, message))
            elif delivery in ('pending', 'failed'):
                reset.append(identity)
    anchors = store.observe_deliveries(scope, chat, [identity for identity, _ in confirmed], instant.timestamp(), reset)
    for identity, message in confirmed:
        message['delivery_confirmed_at'] = _iso(_date(anchors[identity]))
        message['delivery_clock_source'] = 'server_first_confirmed_observation'


def _delivery_time(message):
    # Pure callers may provide a known real send time in created_at. The public
    # adapter always marks queue time unverified and supplies its own anchor.
    return (_date(message.get('delivery_confirmed_at'))
            or (None if message.get('delivery_clock_unverified') else _date(message.get('created_at'))))


def _delivery(message, ctx):
    status = str(message.get('delivery_status') or message.get('delivery') or '').lower()
    if message.get('out_pending') or status in _PENDING:
        return 'pending'
    if status in _FAILED:
        return 'failed'
    if message.get('sender_type') in ('bot', 'assistant') or message.get('by') == 'bot':
        return 'bot'
    human = message.get('sender_type') in ('operator', 'human', 'employee') or message.get('by') == 'operator'
    if human and (status in _CONFIRMED or _receipt(ctx, 'outgoing_delivered', message.get('id'))):
        return 'confirmed'
    return 'unknown'


def _timer(messages, known, ctx, now):
    timer = dict(status='not_applicable')
    outgoing = [(i, m) for i, m in enumerate(messages) if m.get('direction') == 'out']
    if not outgoing:
        return timer
    index, last = outgoing[-1]
    kp = known.get('direction') == 'kp'
    followup = _is_kp_followup(last)
    timer.update(reply_message_id=last.get('id', ''),
                 rule_id=_KP_TIMER_RULES[0] if kp else 'DOC-L1626')
    if kp:
        timer.update(rule_ids=list(_KP_TIMER_RULES),
                     phase='after_followup' if followup else 'initial_wait')
    newer = [m for m in messages[index + 1:] if m.get('direction') == 'in']
    if newer:
        timer.update(status='cancelled_by_incoming', incoming_message_ids=_unique(m.get('id') for m in newer))
        return timer
    delivery = _delivery(last, ctx)
    if delivery == 'pending':
        if kp and followup:
            timer['phase'] = 'followup_pending'
        return timer
    if delivery != 'confirmed':
        timer.update(status='unavailable', unavailable_reason='delivery_or_human_sender_unconfirmed')
        return timer
    instants = [_date(m.get('created_at')) for m in messages]
    if (now is None or any(t is None or t > now for t in instants)
            or any(a > b for a, b in zip(instants, instants[1:]))):
        timer.update(status='unavailable', unavailable_reason='timestamp_or_order_unconfirmed')
        return timer
    anchor = _delivery_time(last)
    if anchor is None or anchor > now or anchor < instants[index]:
        timer.update(status='unavailable', unavailable_reason='delivery_time_unconfirmed')
        return timer
    timer.update(anchor_at=_iso(anchor), anchor_source=last.get('delivery_clock_source', 'caller_confirmed_send_time'))
    if kp:
        if followup:
            prior = outgoing[-2] if len(outgoing) > 1 else None
            if (prior is None or not last.get('id') or not prior[1].get('id')
                    or last.get('id') == prior[1].get('id')
                    or _is_kp_followup(prior[1])
                    or _delivery(prior[1], ctx) != 'confirmed'
                    or any(m.get('direction') == 'in' for m in messages[prior[0] + 1:index])
                    or _delivery_time(prior[1]) is None
                    or anchor - _delivery_time(prior[1]) < timedelta(seconds=300)):
                timer.update(status='unavailable', unavailable_reason='kp_followup_anchor_unconfirmed')
                return timer
            due = anchor + timedelta(seconds=600)
            timer.update(status='elapsed' if now >= due else 'waiting', due_at=_iso(due),
                         initial_reply_message_id=prior[1]['id'], followup_message_id=last['id'])
        else:
            due = anchor + timedelta(seconds=300)
            timer.update(status='followup_due' if now >= due else 'waiting', due_at=_iso(due))
        return timer
    if known.get('direction') not in ('bt', 'mnc'):
        timer.update(status='unavailable', unavailable_reason='direction_not_confirmed')
        return timer
    due = anchor + timedelta(seconds=300)
    timer.update(status='elapsed' if now >= due else 'waiting', due_at=_iso(due))
    return timer


def _is_kp_followup(message):
    # Recognize only complete, short questions about continuing this enquiry.
    # This is intent recognition, not delivery proof: _timer still verifies
    # the human sender, delivered status, actual clock and prior reply chain.
    # Quotes, refusals, repair questions and extra sentences do not match.
    text = re.sub(r'\s+', ' ', _body(message).strip()).casefold().replace('ё', 'е')
    return bool(re.fullmatch(
        r'(?:подскажите(?:,\s*пожалуйста)?,\s*)?'
        r'(?:(?:еще\s+)?актуально|(?:ваш\s+)?вопрос\s+еще\s+актуален|'
        r'помощь(?:\s+по\s+вашему\s+запросу)?\s+еще\s+актуальна|'
        r'вам\s+еще\s+нужна\s+помощь|нужна\s+ли\s+(?:вам\s+)?еще\s+помощь)\?',
        text))


def silence_timer(messages, known, ctx=None, now=None):
    """Pure clock calculation, independent of assignment or a policy action.

    KP: wait five minutes, propose one approved follow-up, then wait ten
    minutes from that follow-up's confirmed real timestamp. No sent follow-up
    means no close deadline, even fifteen minutes after the initial reply.
    The caller still applies policy stop branches and execution gates.
    """
    ctx = ctx if isinstance(ctx, dict) else {}
    known = known if isinstance(known, dict) else {}
    instant = datetime.now(_UTC) if now is None else _date(now)
    return _timer(_messages(messages or []), known, ctx, instant)


def _pause_request(message):
    """Separate the client's request, stated duration and own pending action.

    This is a bounded conversational timer, not a work/arrival deadline.
    A substantive question, quotation or another person's instruction does
    not become a wait just because it contains a time word.
    """
    sender = message.get('sender_type') or message.get('by') or ''
    if (message.get('direction') != 'in' or sender not in ('', 'client', 'customer', 'contact', 'user', 'lead')
            or message.get('role') in ('system', 'assistant')
            or message.get('speaker_role', 'client') != 'client'):
        return None
    text = re.sub(r'\s+', ' ', _body(message).strip()).casefold().replace('ё', 'е')
    if re.search(r'[«»“”"]|\b(?:если|сосед\w*|мастер\w*|сказал\w*|написал\w*|спросил\w*)\b', text):
        return None
    text = re.sub(r'\bпожалуйста\b[,\s]*', '', text).strip(' ,')
    exact = _pause_clause(text)
    if exact:
        return exact
    # The client's completed information does not cancel a later explicit
    # request to wait. Keep the earlier factual text as evidence, not a new
    # questionnaire answer invented from the pending action.
    for boundary in re.finditer(r'[,;.!]\s*', text):
        prefix = text[:boundary.start()].strip(' ,;.!')
        rest = text[boundary.end():].strip()
        if not prefix or '?' in prefix:
            continue
        request = _pause_clause(rest)
        if not request:
            continue
        head = request['request_quote']
        explicit = bool(re.match(r'(?:подождите|погодите|дайте|можно)\b', head))
        brief = head in ('секунду', 'секундочку', 'минуту', 'минутку')
        duration_report = re.search(r'\b(?:занял\w*|займет|длит\w*|гор\w*|гас\w*|свет\w*|включ\w*)\b', prefix)
        if not explicit and not request['purpose_quote'] and (not brief or duration_report):
            continue
        return dict(request, completed_information_quote=prefix)
    # A client may explicitly promise to check and report back without the
    # literal word «секунду». Do not infer any result of that future check.
    if ('?' not in text and re.fullmatch(
            r'сейчас\s+(?:я\s+)?(?:уточню|узнаю|посмотрю|проверю|найду|поищу)\b.{0,180}'
            r'\b(?:и\s+)?(?:дам\s+(?:вам\s+)?знать|сообщу\s+вам|напишу\s+вам)[.!… ]*', text)
            and not re.search(r'\bне\s+(?:уточню|узнаю|посмотрю|проверю|найду|поищу|дам|сообщу|напишу)\b',text)):
        return dict(grace_seconds=SHORT_PAUSE_GRACE_SECONDS,duration_explicit=False,
                    request_quote=text.strip('.!… '),purpose_quote=text.strip('.!… '))
    return None


def _pause_clause(text):
    """Parse one explicit request; no role/quote authority supplied here."""
    head, *tail = re.split(r'[,;.!]\s*', text.rstrip('.!… '), maxsplit=1)
    if not tail:
        head = head.rstrip('? ')
    purpose = tail[0].strip() if tail else ''
    if purpose:
        # The adjunct must describe the client's own pending action. A
        # question or a completed answer resumes the enquiry instead.
        own_action = r'найду|поищу|посмотрю|загляну|уточню|проверю|сверю|отвечу|пришлю|отправлю|напишу|освобожусь|уточняю|проверяю|сверяю|ищу|смотрю'
        if ('?' in purpose or not re.search(r'\b(?:' + own_action + r')\b', purpose)
                or re.search(r'\bне\s+(?:' + own_action + r')\b|\bвы\b', purpose)):
            return None
    number = r'\d{1,4}|одну|одна|один|две|два|пару|три|четыре|пять|шесть|семь|восемь|девять|десять'
    units = r'секунд\w*|минут\w*'
    request = re.fullmatch(
        r'(?:(?:подождите|погодите|дайте|можно)\s*)?'
        r'(?:(?:(?:еще\s+)?(?P<n>' + number + r')\s+)?(?P<u>' + units + r')'
        r'|(?P<reverse>минут|секунд)\s+(?P<rn>' + number + r'))|'
        r'(?P<bare>(?:подождите|погодите)(?:\s+немного)?)', head.strip())
    if not request:
        return None
    words = dict(одну=1, одна=1, один=1, две=2, два=2, пару=2, три=3, четыре=4, пять=5,
                 шесть=6, семь=7, восемь=8, девять=9, десять=10)
    stated = request['n'] or request['rn']
    amount = int(stated) if stated and stated.isdigit() else words.get(stated)
    unit = request['u'] or request['reverse'] or ''
    seconds = amount * (60 if unit.startswith('минут') else 1) if amount is not None else SHORT_PAUSE_GRACE_SECONDS
    # Colloquial «пару» supplies a bounded grace period, not an exact promise.
    return dict(grace_seconds=seconds, duration_explicit=bool(stated and stated != 'пару'),
                request_quote=head.strip(), purpose_quote=purpose)


def _short_pause_message(messages):
    rows = [m for m in _messages(messages or []) if not m.get('out_pending')
            and str(m.get('delivery_status') or m.get('delivery') or '').lower()
            not in _FAILED | _PENDING]
    if not rows:
        return None
    message = rows[-1]
    return message if _pause_request(message) else None


def observe_short_pause(store, scope, chat, messages, now=None):
    """Public callers cannot backdate the short pause with a browser field."""
    message = _short_pause_message(messages)
    if message is None:
        return
    message['short_pause_clock_unverified'] = True
    instant = datetime.now(_UTC) if now is None else _date(now)
    if instant is None or not message.get('id'):
        return
    from assistant_store import digest
    identity = digest([message['id'], message.get('created_at'), _body(message)])
    anchor = store.observe_short_pause(scope, chat, identity, instant.timestamp())
    message['short_pause_observed_at'] = _iso(_date(anchor))


def short_client_pause(messages, now=None):
    """One bounded grace period, cancelled by any newer substantive turn.

    Pure historical callers use the source timestamp. The public adapter
    marks it unverified and attaches a stable server-first-observed anchor.
    Missing/unverifiable time asks for review, never an endless waiting loop.
    """
    message = _short_pause_message(messages)
    if message is None:
        return dict(status='not_applicable')
    request = _pause_request(message)
    result = dict(status='unavailable', message_id=message.get('id', ''),
                  quote=_body(message)[:160], **request)
    if not 0 < request['grace_seconds'] <= MAX_EXPLICIT_PAUSE_SECONDS:
        result['unavailable_reason'] = 'explicit_pause_outside_operational_bound'
        return result
    instant = datetime.now(_UTC) if now is None else _date(now)
    anchor = (_date(message.get('short_pause_observed_at'))
              or (None if message.get('short_pause_clock_unverified') else _date(message.get('created_at'))))
    if instant is None or anchor is None or anchor > instant:
        return result
    due = anchor + timedelta(seconds=request['grace_seconds'])
    result.update(status='waiting' if instant < due else 'elapsed',
                  anchor_at=_iso(anchor), due_at=_iso(due),
                  anchor_source='server_first_observed' if message.get('short_pause_clock_unverified') else 'historical_or_pure_caller_timestamp')
    return result


def _unquoted(text):
    return re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', text).casefold().replace('ё', 'е')


def _routing_signals(incoming):
    """Small, conservative routing layer, not a second service qualifier.

    A positive/negative review requires a client assertion about our past
    work. Quoted, hypothetical and future descriptions do not establish it.
    Unrecognized wording stays with the already calculated policy decision.
    """
    signals, review_intent = {}, None
    past_verb = r'собрал\w*|сделал\w*|отремонтировал\w*|установил\w*|взял\w*|пробил\w*|повредил\w*|испортил\w*|сломал\w*|приезжал\w*|приходил\w*'
    for message in incoming:
        text = _unquoted(_body(message))
        statements = [s for s in re.split(r'[.!?\n]', text)
                      if not re.search(r'\bесли\b|\bдопустим\b|\bпредположим\b', s)]
        actual = '. '.join(statements)
        ours = bool(re.search(r'\bваш\w*\s+мастер\w*[^.!?\n]{0,100}(?:' + past_verb + r')\b|после\s+вашего\s+(?:ремонта|обслуживания)|по\s+вашей\s+заявке[^.!?\n]{0,80}приезжал', actual))
        bad = bool(re.search(r'\bплохо\b|недовол\w*|возмущ\w*|пробил\w*|повредил\w*|испортил\w*|сломал\w*|ничего\s+не\s+сделал|не\s+(?:собрал|устранил)|завысил\w*|некачествен\w*', actual))
        if ours:
            signals['past_service'] = message
            if bad:
                signals['complaint'] = message
            elif re.search(r'все\s+(?:отлично|хорошо)|прекрасн\w*|спасибо|благодар\w*|доволен\w*', actual):
                signals['positive_review'] = message
        intent = re.search(r'(?:напишу|оставлю|опубликую|хочу\s+(?:написать|оставить))[^.!?\n]{0,60}(?:отрицательн\w*|негативн\w*|плох\w*)\s+отзыв|(?:отрицательн\w*|негативн\w*|плох\w*)\s+отзыв[^.!?\n]{0,40}(?:напишу|оставлю|опубликую)', text)
        negated = re.search(r'не\s+(?:хочу|буду|собираюсь|стану|напишу|оставлю)[^.!?\n]{0,45}(?:отзыв|писать)|отзыв[^.!?\n]{0,25}(?:не\s+хочу|не\s+буду)', text)
        if negated:
            review_intent = None
        elif intent:
            review_intent = message
        warranty = bool(re.search(r'\b(?:нужна|нужен|нужно|хочу|требую|можно)[^.!?\n]{0,35}гаранти|по\s+гарантии[^.!?\n]{0,35}(?:посмотр|помощ|исправ|приех)', text))
        if warranty and not re.search(r'\bесли\b|какая\s+гаранти|гарантия\s+на\s+работу\s+будет', text):
            if re.search(r'\bбыла\s+претензи|\bпретензи\w*\s+в\s+окк', actual):
                signals['warranty_after_complaint'] = message
            if re.search(r'уже[^.!?\n]{0,60}(?:раз|ранее)[^.!?\n]{0,50}(?:приезжал|был)[^.!?\n]{0,25}по\s+гарантии', actual):
                signals['repeat_warranty'] = message
        if (re.search(r'\b(?:ранее|раньше|уже|вчера)\b[^.!?\n]{0,35}(?:общал\w*|разговаривал\w*|обсуждал\w*)', actual)
                and re.search(r'(?:сотрудник\w*[^.!?\n]{0,35}отдел\w*\s+авито|партнерск\w*\s+отдел)', actual)
                and not re.search(r'не\s+(?:общал|разговаривал|обсуждал)', actual)):
            signals['prior_avito_department'] = message
    if signals.get('complaint') and review_intent:
        signals['negative_review_intent'] = review_intent
    return signals


def _context_blocked(ctx):
    return (not ctx or ctx.get('conversationStatus') not in ('in_progress', 'open')
            or ctx.get('assignmentKnown') is not True
            or not ctx.get('assigneeId') or ctx.get('channelAssigned') is not True
            or ctx.get('assignedToCurrentOperator') is False
            or ctx.get('botActive') is True or ctx.get('hasTransfer') is True)


def _existing(decision, known, ctx):
    guards = {g.get('id') for g in decision.get('decision_guards', []) if isinstance(g, dict)}
    return bool(known.get('crm_request_id') or ctx.get('hasCrmJob')
                or guards & _EXISTING_GUARDS or any(decision.get(k) for k in _EXISTING_FIELDS))


def _callback(messages, known, decision, ctx):
    if _existing(decision, known, ctx) or _context_blocked(ctx):
        return None
    if (decision.get('crm_flags', {}).get('customer_declined')
            or decision.get('visit_time_confirmed') or ctx.get('visit_time_confirmed')
            or decision.get('service', {}).get('status') in ('approval', 'agree', 'refuse', 'excluded')):
        return None
    text = '\n'.join(_body(m) for m in messages if m.get('direction') == 'in')
    if _NO_CALLBACK.search(text):
        return None
    # Reuse the one existing parser, never recover a contact with new regexes.
    from contact_facts import collect
    facts = collect(messages, known)
    address = facts.get('address') or {}
    if (not facts.get('contact_phone_to_use') or facts.get('phone_needs_confirmation')
            or facts.get('address_needs_confirmation') or not address.get('building')
            or not (address.get('street') or address.get('settlement'))):
        return None
    return dict(mode='callback', status='operator_review', ready=False,
                time_policy='nearest_branch_normative', visit_time_confirmed=False,
                can_create_automatically=False, requires_full_qualification_check=True,
                rule_ids=['DIRECT-USER-SILENCE-CALLBACK', 'DOC-L1159'],
                intent_message_ids=_unique(m.get('id') for m in messages if m.get('direction') == 'in'))


def classify(messages, known, decision, ctx=None, now=None):
    """Return a recommendation and evidence without mutating any input."""
    known = known if isinstance(known, dict) else {}
    decision = decision if isinstance(decision, dict) else {}
    ctx = ctx if isinstance(ctx, dict) else {}
    messages = _messages(messages or [])
    now = datetime.now(_UTC) if now is None else _date(now)
    timer = _timer(messages, known, ctx, now)
    result = dict(version=VERSION, disposition='operator_review', reason='',
                  rule_ids=deepcopy(decision.get('rule_ids') or []), message_ids=[], required_actions=[],
                  evidence=[],
                  decision_guards=deepcopy(decision.get('decision_guards') or []),
                  decision_evidence={k: deepcopy(v) for k, v in decision.items() if k.endswith('_evidence') or k in _EXISTING_FIELDS},
                  timer=timer, crm_preparation=deepcopy(decision.get('crm_preparation')),
                  auto_enabled=False, execution_allowed=False)
    followup = decision.get('conditional_claim_followup')
    if isinstance(followup, dict):
        result['conditional_followups'] = [deepcopy(followup)]
    if timer.get('rule_id'):
        result['rule_ids'].append(timer['rule_id'])
    result['rule_ids'] += timer.get('rule_ids', [])
    for guard in result['decision_guards']:
        if isinstance(guard, dict):
            result['message_ids'] += guard.get('message_ids', [])
    if timer.get('reply_message_id'):
        result['message_ids'].append(timer['reply_message_id'])
    result['message_ids'] += timer.get('incoming_message_ids', [])
    if isinstance(result['crm_preparation'], dict):
        result['rule_ids'] += result['crm_preparation'].get('rule_ids', [])
        result['message_ids'] += result['crm_preparation'].get('intent_message_ids', [])

    def done(disposition, reason, rules=(), evidence=(), required=(), preserve_preparation=False):
        result.update(disposition=disposition, reason=reason, required_actions=list(required))
        result['rule_ids'] = _unique([*result['rule_ids'], *rules])
        result['message_ids'] = _unique([*result['message_ids'], *[m.get('id') for m in evidence]])
        if not preserve_preparation:
            result['crm_preparation'] = None
        return result

    incoming = [m for m in messages if m.get('direction') == 'in']
    service = decision.get('service') or {}
    ids = {service.get('id'), *[item.get('id') for item in service.get('items', []) if isinstance(item, dict)]}
    if str(known.get('channel') or '').lower().startswith('max'):
        return done('excluded', 'MAX исключён владельцем', ['OWNER-MAX-20261016'])
    if 'cleaning' in ids or 'DIRECT-USER-CLEANING-EXCLUDED' in result['rule_ids']:
        return done('excluded', 'Клининг исключён владельцем', ['DIRECT-USER-CLEANING-EXCLUDED'])
    signals = _routing_signals(incoming)
    result['evidence'] = [dict(kind=kind, message_id=m.get('id', ''), source='client_assertion_unverified')
                          for kind, m in signals.items()]
    refusal = _receipt(ctx, 'branch_warranty_refusal')
    if refusal:
        result['message_ids'] += refusal.get('message_ids', [])
        return done('notify_okk', 'Подтверждён отказ филиала от гарантии: оператор передаёт претензию ОКК',
                    ['DOC-L0686', 'DOC-L1408'], required=['operator_review'])
    if signals.get('warranty_after_complaint'):
        return done('operator_review', 'Гарантия/повтор после претензии требует согласования ОКК',
                    ['DOC-L1407'], [signals['warranty_after_complaint']], ['okk_approval'])
    if signals.get('complaint'):
        if signals.get('negative_review_intent'):
            return done('transfer_avito', 'Претензия и намерение отрицательного отзыва: сохранить обе обязанности',
                        ['DOC-L1631', 'DOC-L0823'], [signals['complaint'], signals['negative_review_intent']], ['notify_okk'])
        return done('notify_okk', 'Недовольство прежней работой/ценой: передать сведения ОКК',
                    ['DOC-L0823', 'DOC-L1631', 'DOC-L1419', 'DOC-L1463'], [signals['complaint']])
    if signals.get('positive_review'):
        return done('transfer_avito', 'Позитивный отзыв о нашей прежней работе',
                    ['DOC-L1629', 'DOC-L1630'], [signals['positive_review']])
    if signals.get('prior_avito_department'):
        return done('transfer_avito', 'Клиент сообщает прежнее общение с отделом Авито',
                    ['DOC-L1633'], [signals['prior_avito_department']])
    if (known.get('listing_profile') == 'non_profile'
            or re.search(r'кредит\w*\s+в\s+дурак\w*\s+онлайн', str(known.get('title') or ''), re.I)):
        return done('transfer_avito', 'Источник — явно непрофильное объявление', ['DOC-L1632'], incoming[-1:])
    if signals.get('repeat_warranty'):
        return done('branch_approval', 'Последующая гарантия требует проверки истории и согласования филиала',
                    ['DOC-L0684'], [signals['repeat_warranty']], ['operator_review'])
    if service.get('status') in ('approval', 'agree'):
        return done('branch_approval', 'Конкретная услуга уже классифицирована как требующая согласования',
                    [*service.get('rules', []), 'OWNER-CHATBOOKING-20261016'], incoming[-1:], ['operator_review'])
    if _context_blocked(ctx):
        return done('operator_review', 'Текущее назначение, статус или доступ требуют проверки')
    if not incoming:
        return done('operator_review', 'Нет клиентского обращения')
    dates = [_date(m.get('created_at')) for m in messages]
    known_dates = [d for d in dates if d is not None]
    if (now is None or any(d > now for d in known_dates)
            or any(a > b for a, b in zip(known_dates, known_dates[1:]))):
        return done('operator_review', 'Временной порядок сообщений не подтверждён')
    if _existing(decision, known, ctx):
        return done('operator_review', 'Проверить существующую заявку/договорённость; новый приём не подтверждён',
                    ['DOC-L0818', 'DOC-L0819'])
    unread = [m for m in messages if m.get('direction') == 'in' and m.get('unread_media')]
    if unread and all(m.get('awaiting_voice_transcript') is True for m in unread):
        return done('wait', 'Ожидаем завершения расшифровки голосового сообщения', evidence=unread)
    if unread:
        return done('operator_review', 'Необходимо проверить клиентское вложение', evidence=incoming[-1:])
    action = decision.get('action')
    wait_intent = decision.get('client_wait_intent')
    declined = (wait_intent == 'declined'
                or decision.get('crm_flags', {}).get('customer_declined')
                or decision.get('flags', {}).get('customer_declined'))
    resolved = wait_intent == 'resolved' or decision.get('service_resolution_evidence')
    stopped = wait_intent == 'deferred' or declined or resolved
    preparation = result['crm_preparation']
    if (preparation is not None and action == 'wait'
            and not (known.get('direction') == 'kp' and (declined or resolved))):
        safe_preparation = (isinstance(preparation, dict) and preparation.get('mode') == 'callback'
                            and preparation.get('status') == 'operator_review'
                            and preparation.get('ready') is False
                            and preparation.get('can_create_automatically') is False
                            and preparation.get('visit_time_confirmed') is False
                            and preparation.get('requires_full_qualification_check') is True
                            and not decision.get('crm_flags', {}).get('customer_declined')
                            and not _NO_CALLBACK.search('\n'.join(_body(m) for m in incoming)))
        if not safe_preparation:
            result['decision_evidence']['rejected_crm_preparation'] = deepcopy(preparation)
            return done('operator_review', 'Подготовка CRM противоречит контракту review-only')
    if action == 'wait' and messages and messages[-1].get('direction') == 'out':
        if known.get('direction') == 'kp' and stopped:
            result['timer']['suppressed_by_client_wait_intent'] = wait_intent or 'declined_or_resolved'
            return done('wait', 'Отсрочка, отказ или решение клиента не превращаются в новый вопрос',
                        preserve_preparation=wait_intent == 'deferred' and not (declined or resolved))
        if timer['status'] in ('source_conflict', 'unavailable'):
            return done('operator_review', 'Таймер не подтверждён или нормы источников расходятся')
        if timer['status'] == 'followup_due':
            result.update(suggested_reply=KP_FOLLOWUP_REPLY, requires_operator_review=True)
            return done('reply', 'После пяти минут молчания КП предложить один вежливый уточняющий вопрос',
                        _KP_TIMER_RULES)
        if timer['status'] in ('waiting', 'elapsed'):
            result['crm_preparation'] = _callback(messages, known, decision, ctx)
            if result['crm_preparation']:
                result['rule_ids'] += result['crm_preparation']['rule_ids']
            if str(known.get('channel')) == 'jivo' and known.get('direction') == 'mnc' and re.search(r'не\s+смогу\s+помочь|таким\s+не\s+занимаюсь', _body(messages[-1]), re.I):
                result['rule_ids'].append('TGAVITO-19880')
            return done('close' if timer['status'] == 'elapsed' else 'wait',
                        'Рекомендация пометить только чат «Решён»' if timer['status'] == 'elapsed' else 'Ожидаем ответ клиента',
                        preserve_preparation=True)
    if action == 'wait':
        return done('wait', decision.get('reason') or 'Ожидаем следующий ход клиента',
                    preserve_preparation=True)
    if action in ('draft', 'question', 'price', 'refuse'):
        return done('reply', 'Использовать следующий ответ из готового policy decision', evidence=incoming[-1:])
    return done('operator_review', 'Policy decision требует оператора; назначение передачи из общего handoff не следует')
