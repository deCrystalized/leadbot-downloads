"""Read current contact metadata for one guarded development party, never bodies."""
import argparse
import json
import re
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from manual_program_guard import assert_development_dialogues, assert_development_phones

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch', required=True)
    args = parser.parse_args()
    assert re.fullmatch(r'\d+-\d+', args.batch)
    folder = ROOT / ('test-artifacts/human-practice/manual-batch' + args.batch)
    selected = json.loads((folder / 'selection-private.json').read_text())
    ids = [row['cid'] for row in selected]
    assert_development_dialogues(ids)
    assert len(ids) == len(set(ids)) and all(re.fullmatch(r'[a-f0-9-]{36}', cid) for cid in ids)
    sql = "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\nSELECT json_build_object('cid',c.id,'client_id',p.id,'client_name',p.name,'client_phone',p.phone,'phone_set_at',p.phone_set_at,'phone_conversation_id',p.phone_conversation_id) FROM conversations c JOIN clients p ON p.id=c.client_id WHERE c.id IN ("
    sql += ','.join("'" + cid + "'::uuid" for cid in ids) + ');\nCOMMIT;\n'
    inner = 'exec psql -X -q -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -At'
    remote = 'docker exec -i -e ' + shlex.quote('PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=10000 -c lock_timeout=500') + ' leadchat-postgres-1 sh -c ' + shlex.quote(inner)
    proc = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                           '-o', 'ConnectTimeout=15', 'leadchat', remote],
                          input=sql, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          check=True, timeout=40)
    rows = [json.loads(line) for line in proc.stdout.splitlines() if line.startswith('{')]
    assert len(rows) == len(ids) and {row['cid'] for row in rows} == set(ids)
    assert_development_phones(row['client_phone'] for row in rows if row['client_phone'])
    numbers = {row['cid']: row['number'] for row in selected}
    for row in rows:
        row['case'] = numbers[row['cid']]
        row['phone_same_conversation'] = row['phone_conversation_id'] == row['cid']
        row['source_creation_input'] = False
    result = dict(at=datetime.now(timezone.utc).isoformat(), read_only_sql=True,
                  dialogue_bodies_read=False, platform_writes=0, heldout_contact_overlaps=[],
                  source_creation_input=False, rows=sorted(rows, key=lambda row: row['case']))
    path = folder / 'crm-current-profile-phone-audit-private.json'
    assert not path.exists(), 'Keep prior contact snapshot; do not overwrite it'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    path.chmod(0o600)
    print(json.dumps(dict(guarded_profiles=len(rows), profiles_with_phone=sum(bool(row['client_phone']) for row in rows),
                          heldout_contact_overlaps=0, dialogue_bodies_read=False, platform_writes=0)))


if __name__ == '__main__':
    main()
