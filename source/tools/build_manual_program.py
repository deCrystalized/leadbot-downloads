"""Freeze disjoint client cohorts for 1000 manual development + 1000 final checks.

Identity parsing and metadata selection are mechanical; neither is counted as
manual review. This tool never replays the final cohort or changes the bot.
Private inputs stay local. Existing manifests are immutable on rerun.
"""
import collections
import hashlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'test-artifacts'
OUT = ART / 'human-practice/manual-program-1000'
sys.path.insert(0, str(ROOT / 'leadbot/brain'))
import contact_phone

EXPERTS = ('Мамонтов Георгий', 'Скороход Илья', 'Востриков Глеб', 'Казахбаев Зухратдин')
SEED = 'leadbot-manual1000-and-final1000-v1-20261017'


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def write_private(path, value):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def write_protection(path, value):
    # This derived index may gain identity hashes; the frozen rosters may not.
    assert path.name == 'final-protected-dialogues-private.json'
    if path.exists():
        old = json.loads(path.read_text())
        assert old['protected_cids'] == value['protected_cids']
        assert old['source_final_manifest_sha256'] == value['source_final_manifest_sha256']
    temp = path.with_suffix('.refresh.tmp')
    write_private(temp, value)
    os.replace(temp, path)


def main():
    global OUT
    rotating = '--rotate-final-after-contact-audit' in sys.argv
    if not rotating:
        from manual_program_guard import active_program_path
        OUT = active_program_path()
    OUT.mkdir(mode=0o700, exist_ok=True)
    paths = [OUT / n for n in ('development-private.json', 'final-holdout-private.json', 'manifest.json')]
    existing = any(p.exists() for p in paths)
    if rotating:
        assert existing and not (OUT / 'active-validation.json').exists(), 'Rotation already activated or original split missing'
        assert (OUT / 'validation-rotation-incident-private.json').exists(), 'Document the exposure first'
    protected_path = OUT / 'final-protected-dialogues-private.json'
    if existing:
        assert all(p.exists() for p in paths), 'Incomplete split: inspect before recovery'
        m = json.loads(paths[-1].read_text())
        assert sha(paths[0].read_text()) == m['development_manifest_sha256']
        assert sha(paths[1].read_text()) == m['final_manifest_sha256']
        if protected_path.exists() and '--refresh-protection' not in sys.argv and not rotating:
            print(json.dumps(m, ensure_ascii=False))
            return
    db = sqlite3.connect('file:' + str(ART / 'all-history/history-private.sqlite') + '?mode=ro', uri=True)
    db.execute('PRAGMA query_only=ON')
    conversations = {cid: json.loads(raw) for cid, raw in db.execute('SELECT id,data FROM conversations')}
    by_hash = {sha(cid): cid for cid in conversations}
    parent = {}

    def find(k):
        parent.setdefault(k, k)
        if parent[k] != k:
            parent[k] = find(parent[k])
        return parent[k]

    def union(keys):
        roots = [find(k) for k in keys]
        root = min(roots)
        for k in roots:
            parent[k] = root

    for cid, raw in db.execute('SELECT cid,data FROM contacts'):
        row = json.loads(raw)
        keys = [sha('dialog:' + cid)]
        if row.get('client_id'):
            keys.append(sha('client:' + str(row['client_id'])))
        phone = contact_phone.normalize(row.get('phone'))
        if phone:
            keys.append(sha('phone:' + phone[-10:]))
        union(keys)
    department = {r['message_id']: r.get('department') for r in map(json.loads, (ART / 'human-practice/message-departments-private.jsonl').open()) if r['kind'] == 'message_department'}
    stats = collections.defaultdict(lambda: {'messages': 0, 'chars': 0, 'media': 0, 'voices': 0, 'experts': collections.Counter()})
    for mid, cid, raw in db.execute('SELECT id,cid,data FROM messages'):
        m = json.loads(raw)
        row = stats[cid]
        row['messages'] += 1
        text = m.get('text') or m.get('transcript') or ''
        row['chars'] += len(text)
        row['media'] += len(m.get('attachment_types') or [])
        row['voices'] += bool(m.get('transcript'))
        if m.get('direction') == 'out' and m.get('author') in EXPERTS and department.get(mid) == 'Чатер':
            row['experts'][m['author']] += 1
        if m.get('direction') == 'in':
            # Identity only: no target/reply evaluation of the held-out cohort.
            for phone in contact_phone.find_all(text):
                union([sha('dialog:' + cid), sha('phone:' + phone.value[-10:])])
    groups = {cid: find(sha('dialog:' + cid)) for cid in conversations}
    if existing and not rotating:
        final = json.loads(paths[1].read_text())
        assert all(groups[r['cid']] == r['client_group'] for r in final), 'Identity source changed'
        final_groups = {r['client_group'] for r in final}
        protected = sorted(cid for cid in conversations if groups[cid] in final_groups)
        identity_keys = sorted(key for key in parent if find(key) in final_groups)
        write_protection(protected_path, {'protected_cids': protected, 'protected_identity_keys': identity_keys, 'source_final_manifest_sha256': sha(paths[1].read_text()), 'all_known_alias_dialogues_protected': True})
        print(json.dumps({'final_dialogues': len(final), 'protected_alias_dialogues': len(protected), 'auto_enabled': False}))
        return
    old_cids, old_aliases = set(), set()
    completed = []
    for folder in ('manual-batch20', 'manual-batch21-40', 'manual-batch41-60'):
        rows = json.loads((ART / 'human-practice' / folder / 'sources-private.json').read_text())
        completed.extend(rows)
        old_cids.update(r['cid'] for r in rows)
    assert len(old_cids) == 60 and len(completed) == 60
    # Exclude previous training partitions and evaluated slices. Merely
    # archived reserved candidates were never used as wording or replayed.
    for name in ('train_candidates.jsonl', 'evaluation_unseen_clients.jsonl'):
        for r in map(json.loads, (ART / 'private-candidates' / name).open()):
            if r.get('source_dialog') in by_hash:
                old_cids.add(by_hash[r['source_dialog']])
            if r.get('client_group'):
                old_aliases.add(r['client_group'])
    for name in ('offline-learning/expert-turns-private.jsonl', 'all-history/frozen-new-client-cases-private.jsonl'):
        for r in map(json.loads, (ART / name).open()):
            if r.get('partition') == 'reserved':
                continue
            if r.get('source_dialog') in by_hash:
                old_cids.add(by_hash[r['source_dialog']])
            if r.get('client_group'):
                old_aliases.add(r['client_group'])
    for name in ('personal/real-cases-private.json', 'human-practice/review-samples-private.json', 'disputed-round/disputed-contact-review-private.json'):
        path = ART / name
        if not path.exists():
            continue
        for r in walk(json.loads(path.read_text())):
            for k in ('cid', 'chat_id', 'convId'):
                if r.get(k) in conversations:
                    old_cids.add(r[k])
            if r.get('source_dialog') in by_hash:
                old_cids.add(by_hash[r['source_dialog']])
            if r.get('client_group'):
                old_aliases.add(r['client_group'])
    for r in json.loads((ROOT / 'leadbot/brain/style_examples.json').read_text())['examples']:
        old_aliases.add(r['source_client_group'])
        if r.get('source_dialog_sha256') in by_hash:
            old_cids.add(by_hash[r['source_dialog_sha256']])
    # Every linked-contact audit is development data too, even when it was
    # never used for reply style. Never reserve such identities as unseen.
    old_cids.update(cid for cid, source in conversations.items() if source.get('crm_request_id'))
    excluded_final = {groups[cid] for cid in old_cids} | {find(k) for k in old_aliases}
    references = collections.defaultdict(set)
    for r in json.loads((ART / 'human-practice/crm-references-private.json').read_text()):
        if r['direction'] == 'note':
            references[r['cid']].add(r['crm_id_candidate'])
    candidates = []
    for cid, row in stats.items():
        source = conversations.get(cid, {})
        if not row['experts'] or source.get('channel') != 'avito':
            continue
        author, count = row['experts'].most_common(1)[0]
        max_messages, max_chars, max_media = (240, 120000, 16) if rotating else (140, 60000, 8)
        if count < 3 or not 8 <= row['messages'] <= max_messages or row['chars'] > max_chars or row['media'] > max_media:
            continue
        if re.search(r'клининг|уборк', (source.get('account_title') or '') + ' ' + (source.get('item_title') or ''), re.I):
            continue
        if not any(v in (source.get('account_title') or '') for v in ('КП', 'МНЧ', 'БТ')):
            continue
        refs = sorted(references.get(cid, set()) | ({str(source['crm_request_id'])} if source.get('crm_request_id') else set()))
        candidates.append({'cid': cid, 'client_group': groups[cid], 'expert': author, 'messages': row['messages'], 'media': row['media'], 'voice_transcripts': row['voices'], 'crm_candidates': refs})
    if rotating:
        previous = json.loads(paths[2].read_text())
        development = json.loads(paths[0].read_text())
        retired = json.loads(paths[1].read_text())
        excluded_final.update(groups[r['cid']] for r in development + retired)
        rotation_seed = 'leadbot-final1000-v2-after-contact-audit-20261017'
    else:
        rotation_seed = SEED
    final, selected_groups = [], set()
    # The unseen Skorokhod pool is smaller after excluding both old cohorts
    # and prior diagnostics. Keep1000 unique clients without reusing them;
    # distribute the15 remaining slots equally among the other three experts.
    quotas = {expert: (235 if expert == 'Скороход Илья' else 255) for expert in EXPERTS} if rotating else dict.fromkeys(EXPERTS, 250)
    order = ('Скороход Илья', 'Мамонтов Георгий', 'Востриков Глеб', 'Казахбаев Зухратдин') if rotating else EXPERTS
    for expert in order:
        pool = sorted((r for r in candidates if r['expert'] == expert and r['client_group'] not in excluded_final), key=lambda r: sha(rotation_seed + ':final:' + r['cid']))
        picked = []
        for row in pool:
            if row['client_group'] in selected_groups:
                continue
            picked.append(row)
            selected_groups.add(row['client_group'])
            if len(picked) == quotas[expert]:
                break
        assert len(picked) == quotas[expert], (expert, len(picked), 'Insufficient uncontaminated final cohort')
        final.extend(picked)
    final_groups = set(selected_groups)
    if rotating:
        new = OUT / 'validation-v2-20261017'
        new.mkdir(mode=0o700)
        # Preserve development bytes exactly: reviewed batches and their
        # identities are unchanged. All original validation files stay intact.
        development_bytes = paths[0].read_bytes()
        with os.fdopen(os.open(new / 'development-private.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
            stream.write(development_bytes)
        write_private(new / 'final-holdout-private.json', final)
        final_sha = sha((new / 'final-holdout-private.json').read_text())
        manifest = dict(previous, schema=2, seed=rotation_seed, final_manifest_sha256=final_sha,
                        previous_final_manifest_sha256=previous['final_manifest_sha256'],
                        previous_final_retired=True, rotation_reason='21 identities were processed by a legacy contact-only audit; no semantic grading; new final group excludes all170 linked dialogs and the entire previous final cohort',
                        known_retired_final_group_overlap=0, known_linked_contact_group_overlap=0,
                        candidate_dialogues=len(candidates), final_eligibility={'messages_min': 8, 'messages_max': 240, 'chars_max': 120000, 'media_max': 16, 'chatter_expert_outbound_min': 3},
                        final_per_expert=quotas,
                        previously_used_groups_excluded_from_final=len(excluded_final))
        write_private(new / 'manifest.json', manifest)
        protected = sorted(cid for cid in conversations if groups[cid] in final_groups)
        identity_keys = sorted(key for key in parent if find(key) in final_groups)
        write_protection(new / 'final-protected-dialogues-private.json', {'protected_cids': protected, 'protected_identity_keys': identity_keys, 'source_final_manifest_sha256': final_sha, 'all_known_alias_dialogues_protected': True})
        assert sha((new / 'development-private.json').read_text()) == previous['development_manifest_sha256']
        assert not final_groups & {groups[r['cid']] for r in development + retired}
        write_private(OUT / 'active-validation.json', {'directory': new.name, 'manifest_sha256': sha((new / 'manifest.json').read_text()), 'reason': 'Audited final-cohort rotation after legacy contact audit exposure; old files preserved'})
        print(json.dumps({'new_final_dialogues': len(final), 'protected_alias_dialogues': len(protected), 'final_manifest_sha256': final_sha, 'development_manifest_sha256': previous['development_manifest_sha256'], 'retired_and_development_group_overlap': 0, 'linked_contact_group_overlap': 0, 'heldout_replayed': False, 'heldout_opened_for_manual_review': False, 'auto_enabled': False}))
        return
    development, selected_groups = [], {groups[r['cid']] for r in completed}
    for expert in EXPERTS:
        pool = sorted((r for r in candidates if r['expert'] == expert and r['client_group'] not in final_groups), key=lambda r: sha(SEED + ':development:' + r['cid']))
        picked = []
        for row in pool:
            if row['client_group'] in selected_groups:
                continue
            picked.append(row)
            selected_groups.add(row['client_group'])
            if len(picked) == 235:
                break
        assert len(picked) == 235, (expert, len(picked))
        development.extend(picked)
    assert len(final) == 1000 and len(development) == 940
    assert not final_groups & selected_groups
    write_private(paths[0], development)
    write_private(paths[1], final)
    manifest = {'schema': 1, 'seed': SEED, 'source_snapshot': json.loads(db.execute("SELECT data FROM metadata WHERE key='snapshot'").fetchone()[0]), 'completed_at_start': 60, 'development_goal': 1000, 'remaining_development': 940, 'final_validation': 1000, 'development_per_expert_remaining': 235, 'final_per_expert': 250, 'batch_size': 40, 'last_development_batch': 20, 'known_client_and_phone_group_overlap': 0, 'previously_used_groups_excluded_from_final': len(excluded_final), 'candidate_dialogues': len(candidates), 'development_manifest_sha256': sha(paths[0].read_text()), 'final_manifest_sha256': sha(paths[1].read_text()), 'heldout_replayed': False, 'heldout_opened_for_manual_review': False, 'reserved_candidate_indexing_is_not_manual_review_or_training': True, 'auto_enabled': False, 'identity_limitation': 'Unknown aliases or phones never present in the snapshot cannot be linked.'}
    write_private(paths[2], manifest)
    protected = sorted(cid for cid in conversations if groups[cid] in final_groups)
    identity_keys = sorted(key for key in parent if find(key) in final_groups)
    write_protection(protected_path, {'protected_cids': protected, 'protected_identity_keys': identity_keys, 'source_final_manifest_sha256': sha(paths[1].read_text()), 'all_known_alias_dialogues_protected': True})
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == '__main__':
    main()
