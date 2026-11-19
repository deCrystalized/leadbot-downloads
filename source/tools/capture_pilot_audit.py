"""Read-only aggregate audit on the bot host; no chat text or secrets in output."""
import datetime
import json
import re
import sqlite3
import time
from collections import Counter

db = sqlite3.connect("file:/opt/leadbot/data/assistant.sqlite3?mode=ro", uri=True)
db.execute("PRAGMA query_only=ON")
since = datetime.datetime(2026, 10, 15, 23, 39, tzinfo=datetime.timezone.utc).timestamp()
rows = db.execute("SELECT chat,kind,payload,last_seen FROM workflow_audit WHERE last_seen>?", (since,)).fetchall()
real = [r for r in rows if re.fullmatch(r"[a-f0-9-]{36}", r[0])]
kinds = Counter(r[1] for r in real)
marina = db.execute("SELECT payload FROM workflow_audit WHERE chat=? AND kind='decision' ORDER BY id DESC LIMIT 1", ("02e0fdc6-2d95-4308-8546-539a37731ea9",)).fetchone()
report = {
    "captured_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "window_start_utc": datetime.datetime.fromtimestamp(since, datetime.timezone.utc).isoformat(),
    "unique_real_dialogs_read": len({r[0] for r in real if r[1] == "read"}),
    "real_event_kinds": dict(kinds),
    "active_review_sessions": db.execute("SELECT count(*) FROM personal_sessions WHERE expires>? AND execution_mode='review'", (time.time(),)).fetchone()[0],
    "active_auto_sessions": db.execute("SELECT count(*) FROM personal_sessions WHERE expires>? AND execution_mode='auto'", (time.time(),)).fetchone()[0],
    "historical_quote_case": {k: json.loads(marina[0]).get(k) for k in ("eligible", "reason", "policy_version")} if marina else None,
    "external_writes_exercised": any(
        kinds[k] > 0 for k in ("transport_started", "transport_result", "write_confirmed")
    ),
    "raw_messages_exported": False,
}
assert report["active_auto_sessions"] == 0
print(json.dumps(report, ensure_ascii=False))
