"""Freeze unseen client groups across the full snapshot and replay locally.

Client/phone aliases are joined before splitting. No current contact card or
final outcome is supplied to a historical cut. This is a diagnostic check, not
a score of equivalence to human staff and not evidence of autonomous readiness.
"""
import argparse
import collections
import json
import os
import re
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path

from analyze_full_history import ROOT, OUT, private_open, sha
from learn_expert_workflows import CUTOFF
from manual_program_guard import assert_development_dialogues

sys.path.insert(0, str(ROOT / "leadbot/brain"))
import assistant_policy as policy
from assistant_store import Store
from contact_cities import city_by_slug
from extension_assistant import Assistant


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=int, default=2000)
    parser.add_argument("--attachment-metadata", type=Path)
    args = parser.parse_args()
    assert args.cases > 0
    attachment_metadata = {}
    if args.attachment_metadata:
        attachment_metadata = {row["id"]: row["attachments"] for row in map(json.loads, args.attachment_metadata.open())}
    db = sqlite3.connect("file:" + str(OUT / "history-private.sqlite") + "?mode=ro", uri=True)
    db.execute("PRAGMA query_only=ON")
    snapshot = json.loads(db.execute("SELECT data FROM metadata WHERE key='snapshot'").fetchone()[0])
    assert snapshot == json.loads((OUT / "export-summary.json").read_text())["snapshot"], "Replay cache belongs to a different snapshot"
    parent, identities, groups, dialogs = {}, {}, {}, {}

    def find(key):
        parent.setdefault(key, key)
        if parent[key] != key:
            parent[key] = find(parent[key])
        return parent[key]

    for cid, raw in db.execute("SELECT cid,data FROM contacts"):
        row = json.loads(raw)
        phone = re.sub(r"\D", "", row.get("phone") or "")
        keys = [sha("dialog:" + cid)]
        if row.get("client_id"):
            keys.append(sha("client:" + str(row["client_id"])))
        if len(phone) >= 10:
            keys.append(sha("phone:" + phone[-10:]))
        root = min(find(k) for k in keys)
        for key in keys:
            parent[find(key)] = root
        identities[cid] = keys
    for cid, raw in db.execute("SELECT id,data FROM conversations"):
        groups[cid] = find(identities[cid][0])
        dialogs[sha(cid)] = (cid, json.loads(raw))
    approved = {e["source_client_group"] for e in json.loads((ROOT / "leadbot/brain/style_examples.json").read_text())["examples"]}
    excluded = {find(key) for keys in identities.values() for key in keys if key in approved}
    train_dialogs = set()
    for line in (ROOT / "test-artifacts/offline-learning/expert-turns-private.jsonl").open():
        row = json.loads(line)
        if row["partition"] == "training_candidates":
            train_dialogs.add(row["source_dialog"])
    excluded |= {groups[dialogs[d][0]] for d in train_dialogs if d in dialogs}
    earliest = {}
    for cid, first in db.execute("SELECT cid,min(ts) FROM messages GROUP BY cid"):
        group = groups[cid]
        earliest[group] = min(first, earliest.get(group, first))
    candidates = {}
    for line in (OUT / "human-turns-private.jsonl").open():
        row = json.loads(line)
        cid, source = dialogs[row["source_dialog"]]
        group = groups[cid]
        if not row.get("author") or row["chronology_ambiguous"] or source.get("channel") != "avito" or group in excluded or earliest[group] < CUTOFF:
            continue
        if group not in candidates or row["case_id"] < candidates[group]["case_id"]:
            candidates[group] = dict(row, client_group=group)
    selected = sorted(candidates.values(), key=lambda row: sha("full-history-v1:" + row["client_group"]))[:args.cases]
    assert_development_dialogues(dialogs[r['source_dialog']][0] for r in selected)
    assert not {row["client_group"] for row in selected} & excluded
    with private_open(OUT / "frozen-new-client-cases-private.jsonl") as stream:
        for row in selected:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.environ["LEADBOT_ASSISTANT_WORDING"] = "reviewed"
    os.environ.pop("LEADBOT_PERSONAL_OWNER_ID", None)
    os.environ.pop("LEADBOT_PERSONAL_OPERATOR_ID", None)
    actions, signals, authors, handoff_reasons, skipped = (collections.Counter() for _ in range(5))
    expectations = json.loads((ROOT / "tests/historical_semantic_expectations.json").read_text())
    assert expectations["version"] == policy.VERSION
    manual_checked = 0
    latency = []
    with tempfile.TemporaryDirectory() as temp, private_open(OUT / "replay-private.jsonl") as private:
        app = Assistant(Store(str(Path(temp) / "offline.sqlite")))
        for row in selected:
            cid, source = dialogs[row["source_dialog"]]
            history = [json.loads(r[0]) for r in db.execute("SELECT data FROM messages WHERE cid=? ORDER BY ts,id", (cid,))][:row["cut_message_index"]]
            if not history or any(m["ts"] >= row["timestamp"] for m in history):
                skipped["ambiguous_chronology"] += 1
                continue
            if len(history) > 300 or sum(len(m.get("text") or "") for m in history) > 100000:
                skipped["context_exceeds_production_limit"] += 1
                continue
            title = source.get("account_title") or ""
            direction = next((d for label, d in (("МНЧ", "mnc"), ("КП", "kp"), ("БТ", "bt")) if label in title), "")
            city = city_by_slug(source.get("city"))
            ctx = {"convId": row["case_id"], "city": city.name if city else source.get("city"), "dir": direction,
                   "partner": source.get("partner"), "accountTitle": title, "accountId": source.get("account") or "", "origin": source.get("origin") or "",
                   "itemTitle": source.get("item_title"), "channel": source.get("channel"),
                   "crmRequestId": "historical-existing" if source.get("crm_at") and source["crm_at"] < row["timestamp"] else "",
                   "messages": [{"id": m["id"], "direction": m["direction"], "sender_type": m.get("sender_type"), "body": m.get("text") or m.get("transcript") or "",
                                 "created_at": m["ts"], "delivery_status": m.get("delivery") or "", "voice_transcript": m.get("transcript") or "",
                                 "attachments": attachment_metadata.get(m["id"], [{"type": t} for t in (m.get("attachment_types") or [])])} for m in history]}
            started = time.perf_counter()
            out, code = app.handle({"owner": "offline-full-history", "action": "preview", "ctx": ctx})
            latency.append((time.perf_counter() - started) * 1000)
            reply, flags = out.get("reply") or "", []
            prior = [m for m in ctx["messages"] if m["direction"] == "out" and m.get("sender_type") not in ("system", "avito") and m["delivery_status"] not in ("failed", "error", "cancelled", "canceled")]
            if code != 200:
                flags.append("preview_error")
            if out.get("auto_enabled") is not False or out.get("pending_model") or out.get("model_task"):
                flags.append("execution_or_model_violation")
            if reply and not prior and not policy.GREETING_START.match(reply):
                flags.append("missing_first_greeting")
            if reply and prior and policy.GREETING_START.match(reply):
                flags.append("repeated_greeting")
            if out.get("facts", {}).get("contact_phone_to_use") and policy.requests_contact(reply):
                flags.append("repeated_contact_request")
            if reply and "Озвучка по регламенту" in (out.get("reason") or "") and not re.search(r"\d|бесплат|\?", reply):
                flags.append("generic_price_without_next_question")
            if re.search(r"уже (?:создал|записал|передал)|мастер.{0,15}(?:точно|уже|приедет)|ждите мастера", reply, re.I):
                flags.append("unconfirmed_action_promise")
            if reply and len(reply) > 280:
                flags.append("reply_too_long")
            expected = expectations["cases"].get(row["case_id"])
            if expected:
                manual_checked += 1
                if out.get("action") != expected["expected_action"] or expected.get("empty_reply") and reply:
                    flags.append("manual_semantic_regression")
            actions[out.get("action") or out.get("code") or "unknown"] += 1
            authors[row["author"]] += 1
            signals.update(flags)
            if out.get("action") == "handoff":
                handoff_reasons[out.get("reason") or "unknown"] += 1
            private.write(json.dumps({"case_id": row["case_id"], "author": row["author"], "ctx": ctx, "output": out, "flags": flags}, ensure_ascii=False) + "\n")
    report = {"snapshot_at": snapshot["at"],
              "selected_new_client_groups": len(selected), "cases_replayed": len(latency), "authors": dict(authors),
              "actions": dict(actions), "review_signals": dict(signals), "handoff_reasons": dict(handoff_reasons), "skipped": dict(skipped),
              "manually_labelled_regression_cases_checked": manual_checked,
              "original_attachment_metadata_restored": bool(attachment_metadata),
              "train_eval_client_group_overlap": 0, "one_turn_per_client_group": True,
              "latency_ms_local_only": {"median": round(statistics.median(latency), 2), "p95": round(sorted(latency)[int(len(latency) * .95)], 2)},
              "policy_version": policy.VERSION, "model_calls": 0, "external_writes": 0, "auto_enabled": False,
              "limits": ["Diagnostic guard checks, not independently labelled semantic accuracy.", "Current advertisement metadata is used; its historical revisions are unavailable.", "Final CRM state, contact cards, later replies and human target are not supplied as input."]}
    (OUT / "replay-summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
