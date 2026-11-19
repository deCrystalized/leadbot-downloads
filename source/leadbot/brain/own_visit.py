"""Own visit offers: server authorization + matching browser API readback.

No customer transport. Browser receipts and raw context flags cannot authorize
an offer. The persistent anchor is created only by the one-use grant transaction.
"""
import json
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from assistant_store import digest
import territory as territory_rules


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS workflow_reply_anchors (
        scope TEXT, chat TEXT, op TEXT, operator TEXT, account TEXT,
        source_hash TEXT, source_count INTEGER, payload TEXT,
        issued REAL, expires REAL, message TEXT, observed REAL,
        PRIMARY KEY(scope,chat,op))''')


def source_hash(messages):
    # Delivery status can advance sent -> read. Message identity/body/author
    # cannot change after review without invalidating the exact prefix.
    return digest([{k: m.get(k, '') for k in ('id', 'direction', 'body',
        'created_at', 'sender_id', 'client_message_id')} for m in messages])


def anchor(db, scope, chat, operator, account, op, draft, messages, now, expires):
    schema(db)
    if not draft.get('visit_offer'):
        return
    db.execute('INSERT INTO workflow_reply_anchors VALUES (?,?,?,?,?,?,?,?,?,?,NULL,NULL)',
        (scope, chat, op, operator, account, source_hash(messages), len(messages),
         json.dumps(dict(reply=draft['reply'], offer=draft['visit_offer'], policy_version=draft['policy_version']), ensure_ascii=False), now, expires))


def _timestamp(value):
    try:
        date = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return date.timestamp() if date.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def apply(store, scope, chat, messages, known):
    """Attach derived evidence, never copy an incoming approval field.

    sender_id and client_message_id come from the extension's actual message
    readback. They only corroborate a pre-existing server authorization, not a
    browser event or an arbitrary claimed sender_type.
    """
    import assistant_policy
    if (known.get('bot_active') is not False
            or known.get('transfer_active') is not False):
        return
    now = time.time()
    with store.connect() as db:
        schema(db)
        rows = db.execute('SELECT * FROM workflow_reply_anchors WHERE scope=? AND chat=?',
                          (scope, chat)).fetchall()
        verified = {}
        for row in rows:
            if row['operator'] != known.get('assignee_id') or row['account'] != known.get('account_id'):
                continue
            matches = [(i, m) for i, m in enumerate(messages)
                       if m.get('client_message_id') == 'lcp:' + row['op']]
            if len(matches) != 1:
                continue
            index, message = matches[0]
            payload = json.loads(row['payload']); offer = payload['offer']
            stamp = _timestamp(message.get('created_at'))
            if (message.get('direction') != 'out' or message.get('sender_id') != row['operator']
                    or message.get('body') != payload['reply'] or not message.get('id')
                    or sum(m['id'] == message['id'] for m in messages) != 1
                    or message.get('delivery_status') not in ('sent', 'delivered', 'read')
                    or stamp is None or not row['issued'] - 2 <= stamp <= min(row['expires'], now + 2)
                    or index != row['source_count'] or source_hash(messages[:index]) != row['source_hash']
                    or offer.get('city') != known.get('city') or offer.get('direction') != known.get('direction')):
                continue
            if row['message'] and row['message'] != message['id']:
                continue
            if row['observed'] is None:
                # A late first read cannot establish timely delivery of a
                # relative promise. The browser observes immediately after send.
                if not stamp <= now <= stamp + 60:
                    continue
                db.execute('UPDATE workflow_reply_anchors SET message=?,observed=? WHERE scope=? AND chat=? AND op=?',
                    (message['id'], now, scope, chat, row['op']))
            verified[message['id']] = (row, offer, stamp)
    accepted = assistant_policy._accepted_staff_visit(messages, include_later_questions=True)
    if not accepted or accepted['proposal_message_id'] not in verified:
        return
    proposal_index = next(i for i, m in enumerate(messages) if m['id'] == accepted['proposal_message_id'])
    answer_index = next(i for i, m in enumerate(messages) if m['id'] == accepted['answer_message_id'])
    row, offer, stamp = verified[accepted['proposal_message_id']]
    answer_stamp = _timestamp(messages[answer_index].get('created_at'))
    if answer_stamp is None or not stamp <= answer_stamp <= now + 2:
        return
    # A new offer, withdrawal, new job or customer time change supersedes the
    # original acceptance. Never revive it from a later bare yes.
    for m in messages[proposal_index + 1:]:
        body = m['body']
        if m.get('direction') == 'out' and (assistant_policy._staff_withdraws_visit(body)
                or re.search(r'\bне\s+(?:получится|смогу|сможем)\b|\bчерез\s+(?:час|два|три|\d)|\b[вк]\s*\d{1,2}(?::\d\d)?\b', body, re.I)):
            return
        if m.get('direction') == 'in' and re.search(
                r'отмен|перенес|передум|новая\s+заявка|новый\s+заказ|по\s+другому\s+вопросу|теперь\s+нужно|'
                r'\b(?:лучше|давайте|можно|не)\s+(?:завтра|сегодня|после|в\s*\d|к\s*\d)|'
                r'\bне\s+(?:смож|удоб|надо|нуж|приезж)', body, re.I):
            return
    low, high = offer.get('min_minutes'), offer.get('max_minutes')
    if not isinstance(low, int) or not isinstance(high, int) or not 0 < low <= high <= 210:
        return
    evidence = dict(accepted, source='authorized_extension_reply', operation_id=row['op'],
        offer_policy_version=json.loads(row['payload']).get('policy_version', ''),
        earliest_at=stamp + low * 60, latest_at=stamp + high * 60,
        min_minutes=low, max_minutes=high, timezone=offer['timezone'],
        city=offer['city'], direction=offer['direction'], appointment_created=False)
    known['_accepted_own_visit'] = evidence
    messages[answer_index]['_accepted_own_visit'] = evidence


def matches(known, evidence):
    own = known.get('_accepted_own_visit') or {}
    return bool(evidence and own and time.time() + own['min_minutes'] * 60 <= own['latest_at']
        and all(own.get(k) == evidence.get(k) for k in
        ('proposal_message_id', 'proposal_quote', 'answer_message_id', 'answer_quote')))


def check_time(accepted, known, lead, territory, now):
    """Independent of the form's proposed clock and its claimed approval flags."""
    try:
        zone = ZoneInfo(accepted['timezone'])
        visit = datetime.fromisoformat(lead['visit_date'] + 'T' + lead['visit_time']).replace(tzinfo=zone)
        stamp = visit.timestamp()
        earliest = territory.get('earliest') or '10:00'
        latest = territory.get('latest') or '21:30'
        loc = None
        if known.get('latitude') is not None and known.get('longitude') is not None:
            loc = territory_rules.locate(known['latitude'], known['longitude'], known['city'], known['direction'])
        loc = loc or territory_rules.city_profile_from_map(known['city'], known['direction'])
        profile = territory_rules.slot_profile(known['city'], loc=loc, far_trip_ctx={'direction': known['direction']})
        lead_minutes = {'час-полтора': 60, 'два, два с половиной часа': 120,
                        'три, три с половиной часа': 180}.get(profile.get('lead'))
        if not lead_minutes or profile.get('needs_approval'):
            return ['Норматив территории изменился или требует согласования']
        earliest = max(earliest, profile.get('earliest') or '10:00')
        latest = min(latest, profile.get('latest') or '21:30')
        if (accepted['city'] != known['city'] or accepted['direction'] != known['direction']
                or not accepted['earliest_at'] <= stamp <= accepted['latest_at']
                or visit < now + timedelta(minutes=max(accepted['min_minutes'], lead_minutes))
                or not earliest <= visit.strftime('%H:%M:%S') <= latest + ':00'):
            return ['Время вне согласованного окна, норматива подготовки или часов приёма']
        return []
    except (KeyError, ValueError, TypeError):
        return ['Не подтверждено согласованное окно визита']
