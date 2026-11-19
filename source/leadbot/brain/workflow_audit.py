"""Owner-scoped durable audit. Never used as instructions or policy memory.

Message versions are stored once; events reference the exact versions read. No
credentials, permits, raw attachments, HTML, model prompts or service env enter it.
"""
import json
import time

import assistant_catalog
import contact_facts
import qualification_state
from assistant_store import digest

EVENTS = {"intent", "transport_started", "transport_result", "reconciled", "unknown", "stopped", "read_error", "skipped", "cycle"}


def failure(store, scope, body, error):
    ctx = body.get("ctx")
    chat = str(ctx.get("convId") or "")[:200] if isinstance(ctx, dict) else ""
    append(store, scope, chat, "read_error", "", {"action": str(body.get("action") or "")[:100], "error": str(error)[:500]})


def schema(db):
    db.executescript("""CREATE TABLE IF NOT EXISTS workflow_audit (
        id INTEGER PRIMARY KEY, scope TEXT, chat TEXT, kind TEXT, revision TEXT,
        event_key TEXT, payload TEXT, created REAL, last_seen REAL, reads INTEGER,
        UNIQUE(scope,event_key));
        CREATE INDEX IF NOT EXISTS audit_scope_id ON workflow_audit(scope,id);
        CREATE TABLE IF NOT EXISTS workflow_audit_messages (
        scope TEXT, chat TEXT, key TEXT, payload TEXT, PRIMARY KEY(scope,chat,key));""")


def append(store, scope, chat, kind, revision, payload, event_key=None):
    now = time.time()
    key = event_key or digest([chat, kind, revision, payload, now])
    with store.connect() as db:
        schema(db)
        db.execute("INSERT INTO workflow_audit(scope,chat,kind,revision,event_key,payload,created,last_seen,reads) VALUES (?,?,?,?,?,?,?,?,1) ON CONFLICT(scope,event_key) DO UPDATE SET reads=reads+1,last_seen=excluded.last_seen",
                   (scope, chat, kind, revision, key, json.dumps(payload, ensure_ascii=False), now, now))


def read_snapshot(store, scope, chat, revision, messages, known, ctx):
    refs = []
    used = {m["id"] for m in messages if m["id"]}
    archive = []
    for raw in ctx.get("messages") or []:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("body") or raw.get("text") or raw.get("voice_transcript") or "")
        archive.append({"id": str(raw.get("id") or "")[:200], "body": text[:12000],
                        "direction": str(raw.get("direction") or "")[:30], "sender_type": str(raw.get("sender_type") or "")[:30],
                        "created_at": str(raw.get("created_at") or "")[:60],
                        "voice_transcript": str(raw.get("voice_transcript") or "")[:12000],
                        "delivery_status": str(raw.get("delivery_status") or raw.get("delivery") or "")[:30],
                        "analysis_used": str(raw.get("id") or "") in used,
                        "unread_media": any(m["id"] == str(raw.get("id") or "") and m.get("unread_media") for m in messages),
                        "media_reviewed": any(m["id"] == str(raw.get("id") or "") and m.get("media_reviewed") for m in messages),
                        "truncated": len(text) > 12000})
    with store.connect() as db:
        schema(db)
        for message in archive:
            key = digest(message);refs.append(key)
            db.execute("INSERT OR IGNORE INTO workflow_audit_messages VALUES (?,?,?,?)", (scope, chat, key, json.dumps(message, ensure_ascii=False)))
    facts = contact_facts.collect(messages, known)
    state = qualification_state.inspect(messages)
    service = assistant_catalog.choose("\n".join(m["body"] for m in messages if m["direction"] == "in"), known)
    relevant = {"problem", "client_name", "visit_time", "decision_maker"}
    relevant.update(key for item in service.get("items", []) for key in item.get("questions", []))
    if known.get("direction") == "mnc":
        relevant.update(["materials", "volume", "place"])
    by_id = {m["id"]: m["body"] for m in messages}
    understood = {key: dict(row, label=qualification_state.SPECS[key][0], quote=by_id.get(row.get("message_id"), "")[:500])
                  for key, row in state.items() if key in relevant and row["status"] == "answered"}
    unknown = [{"field": key, "status": row["status"], "asked": row["asked"]} for key, row in state.items() if row["status"] != "answered"]
    # Missing rows span the whole service catalogue; the decision's next question
    # identifies what is actually needed for THIS job, not every catalogue field.
    append(store, scope, chat, "read", revision,
           {"message_refs": refs, "messages_read": len(messages), "messages_received": len(ctx.get("messages") or []),
            "known": known, "facts": facts, "understood": understood, "unknown_catalog_fields": unknown,
            "unread_media": sum(bool(m.get("unread_media")) for m in messages)}, digest([chat, revision, "read", refs]))


def browser_event(store, scope, body):
    event = body.get("audit_event")
    ctx = body.get("ctx") or {}
    if not isinstance(ctx, dict):
        return {"ok": False, "code": "audit_context", "auto_enabled": False}
    chat = str(ctx.get("convId") or "")[:200]
    if not isinstance(event, dict) or event.get("kind") not in EVENTS or not chat:
        return {"ok": False, "code": "audit_event", "auto_enabled": False}
    data = event.get("data") or {}
    if not isinstance(data, dict):
        return {"ok": False, "code": "audit_event", "auto_enabled": False}
    safe = {"reported_by": "extension"}
    for key in ("operation", "operation_id", "text", "error", "id", "reason", "draft_id"):
        if key in data:
            safe[key] = str(data[key])[:12000 if key == "text" else 500]
    for key in ("confirmed", "success"):
        if isinstance(data.get(key), bool):
            safe[key] = data[key]
    if isinstance(data.get("duration_ms"), (int, float)) and not isinstance(data["duration_ms"], bool) and 0 <= data["duration_ms"] <= 300000:
        safe["duration_ms"] = round(data["duration_ms"])
    event_id = str(event.get("event_id") or "")[:100]
    append(store, scope, chat, event["kind"], str(event.get("revision") or "")[:100], safe,
           digest([chat, event_id, event["kind"], safe]) if event_id else None)
    return {"ok": True, "auto_enabled": False, "logged": True}


def read(store, scope, body):
    event_id = body.get("audit_event_id")
    before = body.get("audit_before")
    if before is None:
        before = 2**63-1
    if any(isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 2**63-1 for v in [before] + ([event_id] if event_id is not None else [])):
        return {"ok": False, "code": "audit_cursor", "auto_enabled": False}
    with store.connect() as db:
        schema(db)
        if event_id is not None:
            row = db.execute("SELECT * FROM workflow_audit WHERE scope=? AND id=?", (scope, event_id)).fetchone()
            if not row:
                return {"ok": False, "code": "audit_missing", "auto_enabled": False}
            event = unpack(row)
            event["messages"] = []
            for key in event["data"].get("message_refs", []):
                message = db.execute("SELECT payload FROM workflow_audit_messages WHERE scope=? AND chat=? AND key=?", (scope, row["chat"], key)).fetchone()
                if message:
                    event["messages"].append(json.loads(message["payload"]))
            return {"ok": True, "auto_enabled": False, "event": event}
        ctx = body.get("ctx") or {}
        if not isinstance(ctx, dict):
            return {"ok": False, "code": "audit_context", "auto_enabled": False}
        chat = str(ctx.get("convId") or "")[:200]
        rows = db.execute("SELECT * FROM workflow_audit WHERE scope=? AND id<? AND (?='' OR chat=?) ORDER BY id DESC LIMIT 25", (scope, before, chat, chat)).fetchall()
        events = [unpack(row) for row in rows]
        for event in events:
            event["data"].pop("message_refs", None)
            event["data"].pop("unknown_catalog_fields", None)
        return {"ok": True, "auto_enabled": False, "events": events, "next_before": rows[-1]["id"] if len(rows) == 25 else None}


def unpack(row):
    return {"id": row["id"], "chat": row["chat"], "kind": row["kind"], "revision": row["revision"],
            "at": row["created"], "last_seen": row["last_seen"], "checks": row["reads"], "data": json.loads(row["payload"])}
