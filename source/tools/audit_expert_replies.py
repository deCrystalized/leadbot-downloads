"""Offline quality signals on frozen expert turns; no transport or model calls.

Flags are review candidates, not an accuracy score. Full private evidence stays
in test-artifacts. The input cut excludes the expert's answer and later events.
"""
import collections
import datetime
import hashlib
import json
import os
import re
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT.parent / "leadbot-audit"
OUT = ROOT / "test-artifacts/current-pilot"
sys.path.insert(0, str(ROOT / "leadbot/brain"))
from assistant_store import Store
from contact_cities import city_by_slug
from extension_assistant import Assistant


def timestamp(value):
    parsed = datetime.datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.UTC)


def main():
    os.environ["LEADBOT_ASSISTANT_WORDING"] = "reviewed"
    for name in ("LEADBOT_PERSONAL_OWNER_ID", "LEADBOT_PERSONAL_OPERATOR_ID"):
        os.environ.pop(name, None)
    meta = {}
    messages = collections.defaultdict(list)
    seen = set()
    for path in (
        AUDIT / "history-private.jsonl",
        AUDIT / "bot-context-private.jsonl",
        ROOT / "test-artifacts/alltime-authors/history-private.jsonl",
    ):
        for row in map(json.loads, path.open()):
            if row.get("kind") == "conversation":
                meta[hashlib.sha256(row["id"].encode()).hexdigest()] = row
            elif row.get("kind") == "message" and row["id"] not in seen:
                seen.add(row["id"])
                if row.get("sender_type") in {"client", "operator", "bot"} and row.get("direction") in {"in", "out"}:
                    messages[row["cid"]].append((timestamp(row["ts"]), row))
    for sequence in messages.values():
        sequence.sort(key=lambda pair: (pair[0], pair[1]["id"]))
    turns = [json.loads(line) for line in (ROOT / "test-artifacts/private-candidates/evaluation_unseen_clients.jsonl").read_text().splitlines()]
    held = {r["client_group"] for r in turns}
    turns += [r for r in json.loads((ROOT / "test-artifacts/alltime-authors/analysis/turns-index-private.json").read_text()) if r["client_group"] in held and r["timestamp"] >= "2026-10-01T00:00:00+00:00"]
    turns = list({(r["source_dialog"], r["timestamp"]): r for r in turns}.values())
    withdrawn = set(json.loads((ROOT / "test-artifacts/auto-release/primary-refresh.json").read_text())["withdrawn_primary_ids"])
    counts = collections.Counter()
    authors = collections.Counter()
    reasons = collections.Counter()
    signals = collections.Counter()
    latencies = []
    evidence = []
    with tempfile.TemporaryDirectory() as temp:
        app = Assistant(Store(str(Path(temp) / "offline.sqlite")))
        for turn in turns:
            source = meta[turn["source_dialog"]]
            cut = timestamp(turn["timestamp"])
            title = source.get("account_title") or ""
            direction = next((d for label, d in (("МНЧ", "mnc"), ("КП", "kp"), ("БТ", "bt")) if label in title), "")
            city = city_by_slug(source.get("city"))
            history = []
            for ts, message in messages[source["id"]]:
                if ts >= cut:
                    break
                history.append({"id": message["id"], "created_at": message["ts"], "body": message.get("text") or message.get("transcript") or "", "voice_transcript": message.get("transcript") or "", "direction": message["direction"], "sender_type": message["sender_type"], "delivery_status": message.get("delivery") or "", "attachments": [{"type": kind} for kind in (message.get("attachment_types") or [])]})
            existing = source.get("crm_at") and timestamp(source["crm_at"]) < cut
            ctx = {"convId": hashlib.sha256((turn["source_dialog"] + turn["timestamp"]).encode()).hexdigest(), "city": city.name if city else source.get("city"), "dir": direction, "partner": source.get("partner"), "accountTitle": title, "accountId": source.get("account") or "", "origin": source.get("origin") or "", "itemTitle": source.get("item_title"), "channel": source.get("channel"), "crmRequestId": "already-linked" if existing else "", "messages": history}
            started = time.perf_counter()
            result, code = app.handle({"owner": "offline-expert-audit", "action": "preview", "ctx": ctx})
            latencies.append((time.perf_counter() - started) * 1000)
            reply = result.get("reply", "")
            action = result.get("action") or result.get("code")
            counts[action] += 1
            authors[turn.get("author") or "unknown"] += 1
            if action == "handoff":
                reasons[result.get("reason") or "unknown"] += 1
            flags = []
            if code != 200 or result.get("auto_enabled") is not False or result.get("pending_model") or result.get("model_task") or result.get("validation"):
                flags.append("contract_or_transport_violation")
            if (ctx.get("channel") or "").lower().startswith("max") and reply:
                flags.append("max_reply")
            if existing and reply:
                flags.append("collecting_after_existing_crm")
            if action == "question" and not reply.strip():
                flags.append("empty_question")
            if re.search(r"(?:я\s+)?(?:оформил|создал|записал|передал заявку)|(?:мастер|специалист)\s+(?:уже\s+)?(?:приедет|будет у вас)|ждите мастера", reply, re.IGNORECASE):
                flags.append("unperformed_action_promise")
            prior_out = [m["body"] for m in history if m["direction"] == "out" and m.get("delivery_status") not in {"failed", "error", "cancelled", "canceled"}]
            if re.search(r"здравствуй|добрый\s+(?:день|вечер)|доброе\s+утро", reply, re.IGNORECASE) and any(re.search(r"здравствуй|добрый\s+(?:день|вечер)|доброе\s+утро", text, re.IGNORECASE) for text in prior_out):
                flags.append("repeated_greeting")
            incoming = "\n".join(m["body"] for m in history if m["direction"] == "in")
            last_in = next((m["body"] for m in reversed(history) if m["direction"] == "in"), "")
            if action == "question" and re.search(r"жд[еёë]м|жду", last_in, re.IGNORECASE) and any(re.search(r"\bбуду\b|\bприеду\b|\bподъеду\b", text, re.IGNORECASE) for text in prior_out):
                flags.append("qualification_after_promised_visit_wait")
            settlement = (result.get("facts", {}).get("address") or {}).get("settlement")
            if action == "question" and settlement and str(ctx.get("city") or "").casefold().replace("ё", "е").strip() != settlement.casefold().replace("ё", "е").strip():
                flags.append("qualification_before_settlement_check")
            if re.search(r"(?:номер|телефон).{0,40}(?:связ|подскаж|напиш)|(?:подскаж|напиш).{0,40}(?:номер|телефон)", reply, re.IGNORECASE) and re.search(r"(?<!\d)(?:\+?7|8)?[\s().-]*9\d{2}[\s().-]*\d{3}[\s().-]*\d{2}[\s().-]*\d{2}(?!\d)", incoming):
                flags.append("phone_present_but_asked_again")
            if withdrawn.intersection(result.get("rule_ids", [])):
                flags.append("withdrawn_source_reference")
            signals.update(flags)
            evidence.append({"case_id": ctx["convId"], "author": turn.get("author"), "action": action, "reply": reply, "reason": result.get("reason"), "flags": flags, "rule_ids": result.get("rule_ids", []), "ctx": ctx, "facts": result.get("facts"), "qualification": result.get("qualification"), "lead": result.get("lead")})
    OUT.mkdir(parents=True, exist_ok=True)
    private = OUT / "expert-quality-private.json"
    private.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    private.chmod(0o600)
    report = {"cases": len(turns), "authors": dict(authors), "actions": dict(counts), "handoff_reasons": dict(reasons), "review_signals": dict(signals), "preview_latency_ms": {"median": round(statistics.median(latencies), 2), "p95": round(sorted(latencies)[int(len(latencies) * .95)], 2), "max": round(max(latencies), 2)}, "policy_version": result["policy_version"], "model_calls": 0, "external_writes": 0, "auto_enabled": False, "manual_review_required": True, "flagged_cases_require_review": bool(signals), "accuracy_score": None}
    (OUT / "expert-quality-summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
