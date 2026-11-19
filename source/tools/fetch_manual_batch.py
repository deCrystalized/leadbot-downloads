"""Refresh a selected manual batch using an enforced read-only SQL transaction."""
import collections
import json
import re
import shlex
import sqlite3
import subprocess
import sys
from pathlib import Path
from manual_program_guard import assert_development_dialogues, assert_development_phones

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'leadbot/brain'))
import contact_phone


def main():
    assert len(sys.argv) == 2 and re.fullmatch(r'\d+-\d+', sys.argv[1])
    out = ROOT / ('test-artifacts/human-practice/manual-batch' + sys.argv[1])
    selected = json.loads((out / 'selection-private.json').read_text())
    ids = [r['cid'] for r in selected]
    assert_development_dialogues(ids)
    assert len(ids) == len(set(ids)) and all(re.fullmatch('[a-f0-9-]{36}', cid) for cid in ids)
    inids = ','.join("'" + cid + "'::uuid" for cid in ids)
    sql = 'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\nSELECT json_build_object(\'kind\',\'snapshot\',\'at\',now());\n'
    sql += "SELECT json_build_object('kind','conversation','id',c.id,'channel',c.channel,'account',c.account_id,'status',c.status,'item_title',c.item_title,'city',c.item_city_slug,'crm_at',c.crm_request_at,'crm_request_id',c.crm_request_id,'last_message_at',c.last_message_at,'account_title',a.title,'origin',a.lead_origin,'partner',a.lead_partner_number) FROM conversations c LEFT JOIN avito_accounts a ON a.id=c.account_id WHERE c.id IN(" + inids + ');\n'
    sql += "SELECT json_build_object('kind','message','id',m.id,'cid',m.conversation_id,'direction',m.direction,'sender_type',m.sender_type,'author',u.full_name,'current_department',u.department,'text',m.body,'ts',m.created_at,'delivery',m.delivery_status,'transcript',m.voice_transcript,'attachments',m.attachments) FROM messages m LEFT JOIN users u ON u.id=m.sender_user_id WHERE m.conversation_id IN(" + inids + ') ORDER BY m.created_at,m.id;\nCOMMIT;\n'
    inner = 'exec psql -X -q -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -At'
    remote = 'docker exec -i -e ' + shlex.quote('PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=60000 -c lock_timeout=500') + ' leadchat-postgres-1 sh -c ' + shlex.quote(inner)
    p = out / 'fresh-source-private.jsonl'
    with p.open('w') as f:
        p.chmod(0o600)
        subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', 'leadchat', remote], input=sql, text=True, stdout=f, stderr=subprocess.PIPE, check=True, timeout=65)
    fresh = [json.loads(line) for line in p.read_text().splitlines() if line.startswith('{')]
    sources = {r['id']: r for r in fresh if r['kind'] == 'conversation'}
    messages = collections.defaultdict(list)
    for row in fresh:
        if row['kind'] == 'message':
            messages[row['cid']].append(row)
    rows = [{'number': r['number'], 'cid': r['cid'], 'expert': r['expert'], 'crm_candidates': r['crm_candidates'], 'source': sources[r['cid']], 'messages': messages[r['cid']]} for r in selected]
    assert_development_phones(phone.value for r in rows for m in r['messages'] if m['direction'] == 'in' for phone in contact_phone.find_all(m.get('text') or m.get('transcript') or ''))
    assert len(rows) == len(sources) == len(selected)
    for r in rows:
        assert sum(m.get('author') == r['expert'] and m['direction'] == 'out' and m.get('current_department') == 'Чатер' for m in r['messages']) >= 3
    p = out / 'sources-private.json'
    p.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n')
    p.chmod(0o600)
    db = sqlite3.connect('file:' + str(ROOT / 'test-artifacts/all-history/history-private.sqlite') + '?mode=ro', uri=True)
    new = changed = 0
    for r in rows:
        old = {mid: json.loads(raw) for mid, raw in db.execute('SELECT id,data FROM messages WHERE cid=?', (r['cid'],))}
        for m in r['messages']:
            if m['id'] not in old:
                new += 1
            elif (m.get('text') or '') != (old[m['id']].get('text') or ''):
                changed += 1
    summary = {'snapshot': fresh[0], 'full_dialogues': len(rows), 'messages': sum(len(r['messages']) for r in rows), 'new_messages_since_original_snapshot': new, 'edited_bodies_since_original_snapshot': changed, 'current_department_verified': 'Чатер', 'database_writes': 0}
    (out / 'source-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
