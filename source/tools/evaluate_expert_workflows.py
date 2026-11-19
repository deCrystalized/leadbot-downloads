"""Replay held-out expert turns with only the earlier history; never a live API."""
import argparse
import collections
import json
import os
import re
import statistics
import sys
import tempfile
import time
from pathlib import Path

from learn_expert_workflows import ROOT, OUT, load, sha
from manual_program_guard import assert_development_dialogues

sys.path.insert(0, str(ROOT / "leadbot/brain"))
from assistant_store import Store
from extension_assistant import Assistant
from contact_cities import city_by_slug
import assistant_policy as policy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--max-cases", type=int, default=0)
    args = parser.parse_args()
    assert re.fullmatch(r"[a-z0-9-]+", args.tag)
    os.environ["LEADBOT_ASSISTANT_WORDING"] = "reviewed"
    os.environ.pop("LEADBOT_PERSONAL_OWNER_ID", None)
    os.environ.pop("LEADBOT_PERSONAL_OPERATOR_ID", None)
    conversations, messages, _ = load()
    by_hash = {sha(cid): cid for cid in conversations}
    cases = [r for r in map(json.loads, (OUT / "expert-turns-private.jsonl").open()) if r["partition"] == "frozen_new_clients"]
    if args.max_cases:
        cases = cases[:args.max_cases]
    assert_development_dialogues(by_hash[r['source_dialog']] for r in cases)
    counts, signals, authors = (collections.Counter() for _ in range(3))
    latency, evidence = [], []
    with tempfile.TemporaryDirectory() as temp:
        app = Assistant(Store(str(Path(temp) / "offline.sqlite")))
        for row in cases:
            cid = by_hash[row["source_dialog"]]
            source = conversations[cid]
            history = messages[cid][:row["cut_message_index"]]
            assert all(m["ts"] < row["timestamp"] for m in history)
            title = source.get("account_title") or ""
            direction = next((d for label, d in (("МНЧ", "mnc"), ("КП", "kp"), ("БТ", "bt")) if label in title), "")
            city = city_by_slug(source.get("city"))
            ctx = {"convId": row["case_id"], "city": city.name if city else source.get("city"), "dir": direction,
                   "partner": source.get("partner"), "accountTitle": title, "accountId": source.get("account") or "", "origin": source.get("origin") or "",
                   "itemTitle": source.get("item_title"), "channel": source.get("channel"),
                   "crmRequestId": "historical-existing" if source.get("crm_at") and source["crm_at"] < row["timestamp"] else "",
                   "messages": [{"id": m["id"], "direction": m["direction"], "sender_type": m.get("sender_type"), "body": m.get("text") or m.get("transcript") or "",
                                 "created_at": m["ts"], "delivery_status": m.get("delivery") or "", "voice_transcript": m.get("transcript") or "",
                                 "attachments": [{"type": t} for t in (m.get("attachment_types") or [])]} for m in history]}
            started = time.perf_counter()
            out, code = app.handle({"owner": "offline-new-clients", "action": "preview", "ctx": ctx})
            latency.append((time.perf_counter() - started) * 1000)
            reply, flags = out.get("reply") or "", []
            prior = [m for m in ctx["messages"] if m["direction"] == "out" and m["delivery_status"] not in ("failed", "error", "cancelled", "canceled")]
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
            counts[out.get("action") or out.get("code") or "unknown"] += 1
            authors[row["author"]] += 1
            signals.update(flags)
            evidence.append({"case_id": row["case_id"], "author": row["author"], "target_topics": row["target_topics"], "target": row["target"],
                             "action": out.get("action"), "reply": reply, "reason": out.get("reason"), "flags": flags, "http": code, "ctx": ctx})
    report = {"cases": len(cases), "client_groups": len({r["client_group"] for r in cases}), "authors": dict(authors), "actions": dict(counts), "review_signals": dict(signals),
              "latency_ms": {"median": round(statistics.median(latency), 2), "p95": round(sorted(latency)[int(len(latency) * .95)], 2)},
              "policy_version": policy.VERSION, "model_calls": 0, "external_writes": 0, "auto_enabled": False,
              "quality_claim": "Diagnostic guard signals, not an independently labelled human-equivalence accuracy score."}
    private = OUT / (args.tag + "-private.json")
    private.write_text(json.dumps(evidence, ensure_ascii=False) + "\n")
    private.chmod(0o600)
    (OUT / (args.tag + ".json")).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
