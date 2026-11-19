"""Versioned, source-bound experience index; never a policy or customer transport.

Only a trusted external review manifest can activate an exact record. Refresh
automatically incorporates newly approved cases and revocations. Search results
are examples, not facts about the current customer or changed model weights.
"""
import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path


FIELDS = {'id', 'case_id', 'client_group', 'direction', 'stage', 'situation',
          'action', 'boundary', 'source_sha256'}
DIRECTIONS = {'mnc', 'kp', 'bt'}
CHECKS = ('full_history_reviewed', 'originals_reviewed', 'experienced_staff',
          'current_rules_checked', 'no_unresolved_conflict', 'privacy_checked')
OWNER_CHECKS = ('owner_instruction_verified', 'current_rules_checked',
                'no_unresolved_conflict', 'privacy_checked')
NEGATIVE_CHECKS = ('full_history_reviewed', 'originals_reviewed', 'root_denial_verified',
                   'current_rules_checked', 'no_unresolved_conflict', 'privacy_checked')
SOURCE_CHECKS = {'reviewed_staff_case': CHECKS, 'owner_correction': OWNER_CHECKS,
                 'root_reviewed_negative': NEGATIVE_CHECKS}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def validate(record):
    if not isinstance(record, dict) or set(record) != FIELDS:
        return False
    if not all(isinstance(value, str) for value in record.values()):
        return False
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', record['id']):
        return False
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', record['case_id']):
        return False
    if not all(re.fullmatch(r'[a-f0-9]{64}', record[key])
               for key in ('source_sha256', 'client_group')):
        return False
    if record['direction'] not in DIRECTIONS or not re.fullmatch(r'[a-z_]{1,60}', record['stage']):
        return False
    for key in ('situation', 'action', 'boundary'):
        text = record[key]
        if not text.strip() or len(text) > 700:
            return False
        # Admissions remain human-reviewed; these are additional hard filters,
        # not a claim of general automatic de-identification or semantic truth.
        if re.search(r'https?://|www\.|@|\d|\b(?:рубл|руб|улиц|квартир|подъезд|домофон)\w*', text, re.I):
            return False
        if re.search(r'ignore\s+(?:all|previous)|system\s*prompt|игнорир\w*\s+(?:правил|инструкц)|selected_step_fits', text, re.I):
            return False
    return True


def tokens(text):
    # Local lexical ranking, no hidden embedding/provider requests. Russian
    # inflection stemming is intentionally conservative and is not semantics.
    stop = {'как', 'что', 'это', 'для', 'или', 'при', 'его', 'она', 'они', 'уже',
            'клиент', 'клиента', 'нужно', 'после', 'перед', 'будет'}
    return {word[:7] for word in re.findall(r'[а-яёa-z_]{3,}', text.casefold()) if word not in stop}


def lesson_stages(decision):
    """Relevant stages from a server decision, never a browser/model label."""
    result = []
    action = decision.get('action')
    if decision.get('approved_price_reply') or action == 'price':
        result.append('price')
    selected = (decision.get('next_question') or {}).get('kind')
    if selected:
        result.append(selected)
    elif not result and action:
        result.append('crm' if action == 'ready' else action)
    result.append('intake')
    if any(not isinstance(s, str) or not re.fullmatch(r'[a-z_]{1,60}', s) for s in result):
        raise ValueError('Exact server lesson stages required')
    return tuple(dict.fromkeys(result))


class Memory:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS experience_versions (
                  version TEXT PRIMARY KEY, policy TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS experience_head (
                  singleton INTEGER PRIMARY KEY CHECK(singleton=1), version TEXT NOT NULL);
            ''')
        Path(path).chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=3)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def refresh(self, records, reviews, policy):
        """Atomically replace active knowledge with the exact approved snapshot.

        reviews is a separately maintained trusted manifest, never the supplied
        source text or model output. A removed review revokes its active record.
        """
        if (not isinstance(records, list) or not isinstance(reviews, dict)
                or not isinstance(policy, str) or not policy or len(policy) > 100):
            raise ValueError('A reviewed source snapshot and policy are required')
        accepted, quarantine, ids = [], [], set()
        for index, record in enumerate(records):
            if not validate(record):
                quarantine.append('invalid_record_' + str(index))
                continue
            key = record['id']
            if key in ids:
                raise ValueError('Duplicate experience identity')
            ids.add(key)
            receipt = reviews.get(key, {})
            checks = SOURCE_CHECKS.get(receipt.get('source_kind'), ()) if isinstance(receipt, dict) else ()
            admitted = (validate(record) and isinstance(receipt, dict)
                        and receipt.get('content_sha256') == digest(record)
                        and receipt.get('policy') == policy
                        and bool(checks)
                        and all(receipt.get(check) is True for check in checks))
            if admitted:
                accepted.append(record)
            else:
                quarantine.append(key)
        accepted.sort(key=lambda row: row['id'])
        snapshot = {'policy': policy, 'records': accepted}
        version = digest(snapshot)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR IGNORE INTO experience_versions VALUES (?,?,?)',
                       (version, policy, json.dumps(snapshot, ensure_ascii=False)))
            db.execute('INSERT INTO experience_head VALUES (1,?) ON CONFLICT(singleton) DO UPDATE SET version=excluded.version '
                       'WHERE experience_head.version<>excluded.version', (version,))
        return {'version': version, 'active': len(accepted), 'quarantined': quarantine,
                'model_weight_training': False}

    def retrieve(self, query, direction, stage, policy, *, case_id='', client_group='', limit=3):
        return self.retrieve_stages(query, direction, (stage,), policy,
                                   case_id=case_id, client_group=client_group, limit=limit)

    def retrieve_stages(self, query, direction, stages, policy, *, case_id='', client_group='', limit=3):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 5:
            raise ValueError('Experience retrieval is bounded')
        if (not isinstance(stages, tuple) or not 1 <= len(stages) <= 5
                or any(not isinstance(s, str) or not re.fullmatch(r'[a-z_]{1,60}', s) for s in stages)
                or len(set(stages)) != len(stages)):
            raise ValueError('Exact bounded lesson stages required')
        priority = {stage: index for index, stage in enumerate(stages)}
        with self.connect() as db:
            row = db.execute('''SELECT v.* FROM experience_versions v
                JOIN experience_head h ON h.version=v.version WHERE h.singleton=1''').fetchone()
        if row is None or row['policy'] != policy:
            return {'examples': [], 'version': None, 'source': 'no_current_reviewed_memory'}
        snapshot = json.loads(row['payload'])
        if digest(snapshot) != row['version']:
            raise ValueError('Experience snapshot integrity mismatch')
        wanted = tokens(query)
        scored = []
        for record in snapshot['records']:
            if record['direction'] != direction or record['stage'] not in priority:
                continue
            if record['case_id'] == case_id or client_group and record['client_group'] == client_group:
                continue
            terms = tokens(record['situation'])
            overlap = len(wanted & terms)
            if overlap:
                scored.append((priority[record['stage']], overlap / max(1, len(wanted | terms)), record['id'], record))
        scored.sort(key=lambda item: (item[0], -item[1], item[2]))
        selected: list[dict[str, str]] = []
        seen = set()
        # Give each applicable stage one place before filling with more of
        # the same topic. A price plus clarification step must retain both.
        for stage in stages:
            match = next((item for item in scored if item[0] == priority[stage]), None)
            if match is not None and len(selected) < limit:
                selected.append(match[3])
                seen.add(match[2])
        for item in scored:
            if len(selected) == limit:
                break
            if item[2] not in seen:
                selected.append(item[3])
                seen.add(item[2])
        return {'examples': selected, 'version': row['version'],
                'source': 'reviewed_experience', 'authority': 'examples_only_not_current_facts'}
