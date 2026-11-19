"""Replay every available transcribed voice with its real Avito metadata.

The source audio is not re-transcribed here. Compare only the old generic-file
guard with the corrected type guard, holding the policy and causal context fixed.
"""
import collections
import hashlib
import json
import os
import re
import socket
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "test-artifacts/disputed-round"
sys.path.insert(0, str(ROOT / "leadbot/brain"))
import extension_assistant
import assistant_policy
from assistant_store import Store
from contact_cities import city_by_slug


def legacy_unread(message):
    for attachment in message.get("attachments") or []:
        kind = str(attachment.get("type") or attachment.get("kind") or attachment.get("avito_type") or "").lower()
        if kind in ("contact", "contact_card", "vcard"):
            continue
        if kind in ("audio", "voice", "voice_message", "voice_note") and isinstance(message.get("voice_transcript"), str) and message["voice_transcript"].strip():
            continue
        return True
    return False


def main():
    def no_network(*args, **kwargs):
        raise RuntimeError("Historical replay has no network access")
    socket.socket.connect = no_network
    socket.create_connection = no_network
    os.environ["LEADBOT_ASSISTANT_WORDING"] = "reviewed"
    os.environ.pop("LEADBOT_PERSONAL_OWNER_ID", None)
    os.environ.pop("LEADBOT_PERSONAL_OPERATOR_ID", None)
    db = sqlite3.connect("file:" + str(ROOT / "test-artifacts/all-history/history-private.sqlite") + "?mode=ro", uri=True)
    db.execute("PRAGMA query_only=ON")
    raw_media = {r["id"]: r["attachments"] for r in map(json.loads, (OUT / "attachments-private.jsonl").open())}
    ids = json.loads((OUT / "transcribed-voice-message-ids-private.json").read_text())
    counts, old_actions, new_actions, transitions, skips = (collections.Counter() for _ in range(5))
    fd = os.open(OUT / "voice-replay-private.jsonl", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with tempfile.TemporaryDirectory() as temp, os.fdopen(fd, "w") as private:
        old_app = extension_assistant.Assistant(Store(str(Path(temp) / "old.sqlite")))
        new_app = extension_assistant.Assistant(Store(str(Path(temp) / "new.sqlite")))
        for mid in ids:
            row = json.loads(db.execute("SELECT data FROM messages WHERE id=?", (mid,)).fetchone()[0])
            raw = {"attachments": raw_media[mid], "voice_transcript": row["transcript"]}
            counts["transcribed_voice_messages"] += 1
            counts["unread_media_before"] += legacy_unread(raw)
            counts["unread_media_after"] += extension_assistant._unread_media(raw)
            if row["direction"] != "in":
                skips["outgoing_voice"] += 1
                continue
            source = json.loads(db.execute("SELECT data FROM conversations WHERE id=?", (row["cid"],)).fetchone()[0])
            if source.get("channel") != "avito":
                skips["excluded_channel"] += 1
                continue
            history = [json.loads(r[0]) for r in db.execute("SELECT data FROM messages WHERE cid=? AND ts<? ORDER BY ts,id", (row["cid"], row["ts"]))] + [row]
            if len(history) > 300 or any(len(m.get("text") or "") > 12000 for m in history) or sum(len(m.get("text") or "") for m in history) > 100000:
                skips["production_context_limit"] += 1
                continue
            city = city_by_slug(source.get("city"))
            title = source.get("account_title") or ""
            direction = next((value for label, value in (("МНЧ", "mnc"), ("КП", "kp"), ("БТ", "bt")) if label in title), "")
            ctx = {"convId": "offline-voice-" + hashlib.sha256(mid.encode()).hexdigest(), "city": city.name if city else source.get("city"),
                   "dir": direction, "partner": source.get("partner"), "accountTitle": title, "accountId": source.get("account") or "",
                   "origin": source.get("origin") or "", "itemTitle": source.get("item_title"), "channel": source.get("channel"),
                   "crmRequestId": "historical-existing" if source.get("crm_at") and source["crm_at"] < row["ts"] else "",
                   "messages": [{"id": m["id"], "direction": m["direction"], "sender_type": m.get("sender_type"), "body": m.get("text") or "",
                                 "voice_transcript": m.get("transcript") or "", "created_at": m["ts"], "delivery_status": m.get("delivery") or "",
                                 "attachments": raw_media.get(m["id"], [])} for m in history]}
            with patch.object(extension_assistant, "_unread_media", legacy_unread):
                before, code_before = old_app.handle({"owner": "offline-media-before", "action": "preview", "ctx": ctx})
            after, code_after = new_app.handle({"owner": "offline-media-after", "action": "preview", "ctx": ctx})
            assert code_before == code_after == 200
            assert after["auto_enabled"] is False and not after.get("pending_model") and not after.get("validation")
            counts["causal_states_replayed"] += 1
            old_actions[before["action"]] += 1
            new_actions[after["action"]] += 1
            transitions[before["action"] + " -> " + after["action"]] += 1
            counts["media_handoff_before"] += "вложение без расшифровки" in before.get("reason", "")
            counts["media_handoff_after"] += "вложение без расшифровки" in after.get("reason", "")
            private.write(json.dumps({"source_message": mid, "source_dialog": row["cid"], "before": before, "after": after, "ctx": ctx}, ensure_ascii=False) + "\n")
    report = {"policy_version": assistant_policy.VERSION, "counts": dict(counts), "before_actions": dict(old_actions), "after_actions": dict(new_actions),
              "transitions": dict(transitions), "skips": dict(skips), "network": "disabled", "model_calls": 0, "external_writes": 0, "auto_enabled": False,
              "limits": ["This checks type routing and deterministic responses, not transcription accuracy.", "Earlier unreviewed images/audio and unresolved service conditions still stop the conversation.", "Available transcripts are used only at their message cut; later replies and final outcomes are not supplied."]}
    (OUT / "voice-replay-summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
