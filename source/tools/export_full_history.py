"""Export one consistent, read-only LeadChat snapshot without printing private rows."""
import collections
import json
import os
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "test-artifacts/all-history"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    OUT.chmod(0o700)
    inner = 'exec psql -X -q -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -At'
    remote = "docker exec -i -e " + shlex.quote(
        "PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=120000 -c lock_timeout=500"
    ) + " leadchat-postgres-1 sh -c " + shlex.quote(inner)
    sql = """
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT json_build_object('kind','snapshot','at',now(),'conversations',(SELECT count(*) FROM conversations),'messages',(SELECT count(*) FROM messages),'first_message',(SELECT min(created_at) FROM messages),'last_message',(SELECT max(created_at) FROM messages));
SELECT json_build_object('kind','conversation','id',c.id,'channel',c.channel,'account',c.account_id,'status',c.status,'outcome',c.outcome,'item_title',c.item_title,'city',c.item_city_slug,'crm_linked',c.crm_request_id IS NOT NULL,'crm_at',c.crm_request_at,'crm_request_id',c.crm_request_id,'last_message_at',c.last_message_at,'account_title',a.title,'origin',a.lead_origin,'partner',a.lead_partner_number)
FROM conversations c LEFT JOIN avito_accounts a ON a.id=c.account_id;
SELECT json_build_object('kind','message','id',m.id,'cid',m.conversation_id,'direction',m.direction,'sender_type',m.sender_type,'author',u.full_name,'text',m.body,'ts',m.created_at,'delivery',m.delivery_status,'transcript',m.voice_transcript,'attachment_types',(SELECT json_agg(COALESCE(e->>'type',e->>'kind',e->>'avito_type','unknown')) FROM jsonb_array_elements(COALESCE(m.attachments,'[]')::jsonb) e))
FROM messages m LEFT JOIN users u ON u.id=m.sender_user_id;
SELECT json_build_object('kind','contact','cid',c.id,'client_id',c.client_id,'phone',p.phone)
FROM conversations c LEFT JOIN clients p ON p.id=c.client_id;
COMMIT;
"""
    partial = OUT / "history-private.jsonl.partial"
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as output:
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "leadchat", remote],
            input=sql, text=True, stdout=output, stderr=subprocess.PIPE, timeout=300,
        )
    if result.returncode:
        raise RuntimeError("Read-only snapshot failed; private partial export retained for diagnosis")
    counts = collections.Counter()
    snapshot = None
    with partial.open() as stream:
        for line in stream:
            row = json.loads(line)
            counts[row["kind"]] += 1
            if row["kind"] == "snapshot":
                snapshot = row
    assert snapshot and counts["conversation"] == snapshot["conversations"]
    assert counts["message"] == snapshot["messages"]
    assert counts["contact"] == counts["conversation"]
    target = OUT / "history-private.jsonl"
    partial.replace(target)
    report = {"snapshot": snapshot, "rows": dict(counts), "bytes": target.stat().st_size,
              "read_only": True, "external_model_uploads": 0, "customer_writes": 0,
              "media_scope": "Text, available voice transcripts and attachment type inventory; image pixels and untranscribed audio are not semantically reviewed."}
    (OUT / "export-summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
