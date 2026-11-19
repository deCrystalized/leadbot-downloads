"""Read-only retrieval of reviewed full staff dialogues, not a policy source.

The private index retains complete source messages for traceability. Only a
bounded, de-identified question example can leave it for the wording model.
Retrieval never marks a conversation read, trains model weights or sends anything.
"""
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

INDEX_SCHEMA = 'reviewed_history_v1_ru_suffix_insertion_order'

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def terms(text, limit=40):
    stop = {'это', 'как', 'для', 'или', 'что', 'мне', 'вам', 'вас', 'его',
            'при', 'здравствуйте', 'подскажите', 'нужно', 'нужен', 'хочу'}
    def stem(word):
        if re.search(r'[а-яё]', word) and len(word) > 4:
            word = re.sub(r'(?:иями|ами|ями|ого|ему|ому|ыми|ими|ией|ого|ий|ый|ой|ая|яя|ое|ее|ые|ие|ом|ем|ия|ии|ию|а|я|ы|и|у|ю|е|о)$', '', word)
        return word[:9]
    ordered = list(dict.fromkeys(stem(word) for word in re.findall(r'[а-яёa-z]{3,}', text.casefold()) if word not in stop))
    return ordered if limit is None else ordered[:limit]


def safe_text(text, *, names=(), approved_words=()):
    """Conservative transport filter, not a general-purpose anonymizer."""
    text = str(text or '')
    if re.search(r'https?://|www\.|@|(?:ул\.|улиц|проспект|переул|квартир|подъезд|домофон|телефон|мой\s+номер)', text, re.I):
        return ''
    for name in names:
        for part in re.findall(r'[а-яёa-z]{3,}', str(name).casefold()):
            text = re.sub(r'(?<!\w)' + re.escape(part) + r'(?!\w)', '[имя]', text, flags=re.I)
    text = re.sub(r'\d[\d\s()+.\-]{4,}\d', '[данные]', text)
    text = re.sub(r'\d+', '[число]', text)
    safe_initials = {'Здравствуйте', 'Добрый', 'Доброе', 'Подскажите', 'Уточните', 'Напишите',
                     'Какой', 'Какая', 'Какие', 'Как', 'Что', 'Сколько', 'Когда', 'Где', 'Есть',
                     'Можете', 'Можно', 'Нужна', 'Нужно', 'Это', 'Схема', 'Инструкция', 'Да',
                     'Нет', 'Хорошо', 'Принтер', 'Компьютер', 'Ноутбук', 'Вы', 'Вам', 'У', 'А',
                     'На', 'Для', 'С', 'И', 'В', 'По', 'Если', 'Я', 'Мы', 'Давайте'}
    text = re.sub(r'(?<!\w)[А-ЯЁA-Z][а-яёa-z]{1,}(?!\w)',
                  lambda m: m[0] if m[0] in safe_initials or m[0].casefold() in approved_words else '[название]', text)
    if re.search(r'ignore\s+(?:all|previous)|system\s*prompt|игнорир\w*\s+(?:правил|инструкц)|selected_step_fits', text, re.I):
        return ''
    return text.strip()[:500]


def create_index(path, records, *, approved_cids):
    """Build a new immutable snapshot; caller must guard identities first."""
    path = Path(path)
    if path.exists():
        raise FileExistsError('Experience snapshots are immutable')
    allowed = set(approved_cids)
    ids = [r['cid'] for r in records]
    if len(ids) != len(set(ids)) or set(ids) != allowed:
        raise ValueError('The exact reviewed CID roster is required')
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript('''
          CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE dialogues (cid TEXT PRIMARY KEY, case_no INTEGER NOT NULL,
            source_sha256 TEXT NOT NULL, client_group TEXT NOT NULL,
            metadata TEXT NOT NULL, messages TEXT NOT NULL, review_flags TEXT NOT NULL);
          CREATE TABLE turns (id INTEGER PRIMARY KEY, cid TEXT NOT NULL,
            cut INTEGER NOT NULL, client_text TEXT NOT NULL, staff_reply TEXT NOT NULL,
            search_terms TEXT NOT NULL, direction TEXT NOT NULL, eligible INTEGER NOT NULL);
          CREATE INDEX turns_by_direction ON turns(direction, eligible);
        ''')
        source_versions = []
        for record in records:
            messages = record['messages']
            if not isinstance(messages, list) or not messages:
                raise ValueError('A complete nonempty source is required')
            metadata = record.get('metadata') or {}
            flags = record.get('review_flags') or {}
            source_hash = digest(messages)
            source_versions.append([record['cid'], source_hash, flags, metadata,
                                    record['direction'], record['client_group']])
            db.execute('INSERT INTO dialogues VALUES (?,?,?,?,?,?,?)',
                       (record['cid'], record['case'], source_hash, record['client_group'],
                        json.dumps(metadata, ensure_ascii=False), json.dumps(messages, ensure_ascii=False),
                        json.dumps(flags, ensure_ascii=False)))
            prior_client = ''
            for cut, message in enumerate(messages, 1):
                sender = message.get('sender_type') or ''
                body = message.get('body') or message.get('text') or ''
                if sender in ('system', 'avito', 'bot', 'assistant') or message.get('direction') in ('note', 'system'):
                    continue
                if '[Системное сообщение]' in body or 'Ассистент Авито ответил:' in body:
                    continue
                if message.get('direction') == 'in' and sender in ('', 'client', 'customer', 'user'):
                    prior_client = body
                elif message.get('direction') == 'out' and sender in ('operator', 'employee', 'human'):
                    delivery = str(message.get('delivery_status') or message.get('delivery') or '')
                    # Keep full original above; do not teach failed, indeterminate
                    # delivery, service notices, or the assistant's own repetitions.
                    eligible = bool(flags.get('text_reviewed') is True and flags.get('media_reviewed') is True
                                    and delivery in ('delivered', 'read')
                                    and message.get('author') in metadata.get('experienced_authors', [])
                                    and not str(message.get('client_message_id') or '').startswith('lcp:')
                                    and '?' in body and body.count('?') == 1)
                    db.execute('INSERT INTO turns(cid,cut,client_text,staff_reply,search_terms,direction,eligible) VALUES (?,?,?,?,?,?,?)',
                               (record['cid'], cut, prior_client, body,
                                ' '.join(terms(prior_client + ' ' + str(metadata.get('item_title') or ''), limit=None)),
                                record['direction'], int(eligible)))
        version = digest([INDEX_SCHEMA, sorted(source_versions, key=lambda x: x[0])])
        db.executemany('INSERT INTO metadata VALUES (?,?)', [('version', version), ('dialogues', str(len(records))), ('schema', INDEX_SCHEMA)])
    path.chmod(0o600)
    return {'version': version, 'dialogues': len(records), 'weights_trained': False}


class Reader:
    def __init__(self, path):
        self.path = Path(path)

    def version(self):
        with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            row = db.execute("SELECT value FROM metadata WHERE key='version'").fetchone()
            schema = db.execute("SELECT value FROM metadata WHERE key='schema'").fetchone()
        if not schema or schema[0] != INDEX_SCHEMA:
            raise ValueError('Historical experience schema is not current')
        if not row or not re.fullmatch(r'[a-f0-9]{64}', row[0]):
            raise ValueError('Historical experience version is not confirmed')
        return row[0]

    def search(self, query, direction, *, current_cid='', client_group='', phone_hash='', limit=3,
               question_pattern=None, validator=None, approved_words=()):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 4:
            raise ValueError('Bounded retrieval required')
        dictionary = {word.casefold() for word in approved_words}
        words = set(terms(query)) & set(terms(' '.join(dictionary), limit=None))
        with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            version = db.execute("SELECT value FROM metadata WHERE key='version'").fetchone()[0]
            rows = db.execute('''SELECT t.*,d.client_group,d.metadata FROM turns t JOIN dialogues d ON d.cid=t.cid
                WHERE t.direction=? AND t.eligible=1 AND t.cid<>? AND d.client_group<>?''',
                              (direction, current_cid, client_group)).fetchall()
        selected = []
        for row in rows:
            overlap = words & set(row['search_terms'].split())
            if not overlap:
                continue
            reply = row['staff_reply']
            if question_pattern and not re.search(question_pattern, reply, re.I):
                continue
            metadata = json.loads(row['metadata'])
            if phone_hash and phone_hash in metadata.get('phone_hashes', []):
                continue
            reply = safe_text(reply, names=metadata.get('names', []), approved_words=dictionary)
            lexical = set(re.findall(r'[а-яёa-z]+', reply.casefold()))
            if not reply or '[' in reply or not lexical.issubset(dictionary) or validator and not validator(reply):
                continue
            score = len(overlap) / max(1, len(words | set(row['search_terms'].split())))
            selected.append((score, row['cid'], row['cut'], dict(
                case_id=row['cid'], cut=row['cut'], matched_topic_terms=sorted(overlap), staff_question=reply,
                authority='historical_example_only_not_current_customer_facts_or_policy')))
        selected.sort(key=lambda row: (-row[0], row[1], row[2]))
        examples, seen = [], set()
        for _, _, _, example in selected:
            normalized = re.sub(r'\W', '', example['staff_question'].casefold())
            if normalized in seen:
                continue
            seen.add(normalized);examples.append(example)
            if len(examples) == limit:
                break
        return {'version': version, 'examples': examples, 'retrieval': 'local_reviewed_staff_history'}
