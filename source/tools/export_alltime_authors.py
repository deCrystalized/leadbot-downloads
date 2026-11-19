"""Read-only export of the full available cohort of two explicitly named authors."""
import json
import os
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "test-artifacts/alltime-authors"
OUT.mkdir(parents=True, exist_ok=True)
os.chmod(OUT, 0o700)
inner = 'exec psql -X -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -At'
remote = "docker exec -i -e " + shlex.quote("PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=60000 -c lock_timeout=500") + " leadchat-postgres-1 sh -c " + shlex.quote(inner)
prefix = """BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
"""
cohort = """WITH authors AS (SELECT id,full_name FROM users WHERE full_name IN ('Казахбаев Зухратдин','Востриков Глеб')),
cohort AS (SELECT DISTINCT conversation_id FROM messages WHERE direction='out' AND sender_user_id IN (SELECT id FROM authors))
"""
sql = prefix + cohort + """SELECT json_build_object('kind','conversation','id',c.id,'channel',c.channel,'account',c.account_id,'status',c.status,'outcome',c.outcome,'item_title',c.item_title,'city',c.item_city_slug,'crm_linked',c.crm_request_id IS NOT NULL,'crm_at',c.crm_request_at,'last_message_at',c.last_message_at,'account_title',a.title,'origin',a.lead_origin,'partner',a.lead_partner_number)
FROM cohort h JOIN conversations c ON c.id=h.conversation_id LEFT JOIN avito_accounts a ON a.id=c.account_id
UNION ALL
SELECT json_build_object('kind','message','id',m.id,'cid',m.conversation_id,'direction',m.direction,'sender_type',m.sender_type,'author',u.full_name,'text',m.body,'ts',m.created_at,'delivery',m.delivery_status,'transcript',m.voice_transcript,'attachment_types',(SELECT json_agg(e->>'type') FROM jsonb_array_elements(COALESCE(m.attachments,'[]')::jsonb) e))
FROM cohort h JOIN messages m ON m.conversation_id=h.conversation_id LEFT JOIN users u ON u.id=m.sender_user_id
UNION ALL
SELECT json_build_object('kind','contact','cid',c.id,'client_id',c.client_id,'phone',p.phone)
FROM cohort h JOIN conversations c ON c.id=h.conversation_id LEFT JOIN clients p ON p.id=c.client_id
;
COMMIT;
"""
path = OUT / "history-private.jsonl"
with path.open("w") as output:
    os.chmod(path, 0o600)
    run = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "leadchat", remote], input=sql, text=True, stdout=output, stderr=subprocess.PIPE, timeout=150)
if run.returncode:
    raise RuntimeError("Read-only export failed: " + run.stderr[:400])
# Remove transaction status lines; do not print private rows.
rows = [json.loads(line) for line in path.read_text().split('\n') if line.startswith("{")]
path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
from collections import Counter
counts = Counter(r["kind"] for r in rows)
summary = {"available_rows": dict(counts), "read_only": True, "external_model_uploads": 0}
(OUT / "export-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary))
