"""Inventory actual human conversational practices across the full snapshot.

Patterns are review candidates, not violations or proof of success. Employee
motives and CRM outcomes are not inferred. Unknown authors stay separate.
No model calls, network, training updates or customer actions.
"""
import collections
import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "test-artifacts/all-history"
OUT = ROOT / "test-artifacts/human-practice"
EXPERTS = {"Мамонтов Георгий", "Скороход Илья", "Востриков Глеб", "Казахбаев Зухратдин"}
PATTERNS = {
    "bundled_phone_address_request": r"(?:номер|телефон).{0,180}(?:адрес|улиц)|(?:адрес|улиц).{0,180}(?:номер|телефон)",
    "on_site_price_explanation": r"по\s+объ[её]м|точн\w*.{0,35}на\s+месте|на\s+месте.{0,35}(?:цен|стоим|сориентир|обсуд)|после\s+осмотр",
    "photo_request": r"(?:пришл|скин|отправ|покаж).{0,35}(?:фото|сним|изображ)|(?:есть|можно).{0,20}фото",
    "direct_visit_question": r"когда.{0,45}(?:приехать|принять|подъехать)|(?:сегодня|завтра|когда).{0,25}удобно",
    "short_ack_then_question": r"^\s*(?:да|могу|хорошо|понял|поняла|здравствуйте)\b[\s\S]{0,220}\?",
    "visit_time_statement": r"(?:через\s+час|час.?полтора).{0,35}(?:буду|приеду|подъеду)|(?:буду|приеду|подъеду).{0,35}(?:у вас|через\s+час|\bк\s*\d)",
    "completed_action_statement": r"(?:записал[аи]?|оформил[аи]?|создал[аи]?|передал[аи]?).{0,20}(?:вас|заявк|заказ)",
    "coordination_statement": r"согласую|уточню|проверю|согласова\w*.{0,25}филиал",
    "familiar_address_candidate": r"\b(?:ты|тебе|тебя|твой|твоя)\b",
    "numeric_price_statement": r"\b\d[\d ]{1,7}\s*(?:руб\w*|₽|р\.)",
}
P = {key: re.compile(value, re.I | re.S) for key, value in PATTERNS.items()}
PRICE_QUESTION = re.compile(r"сколько|цен[аыуе]|стоим|прайс", re.I)
PRICE_ANSWER = re.compile(r"руб|₽|\d\s*[рp](?![а-яёa-z])|стоим|цен[аыуе]|по\s+объ[её]м|на\s+месте|осмотр|диагност", re.I)
REFUSAL = re.compile(r"\bнаш(?:[её]л|ла|ли)\b.{0,15}друг|\bотмен\w*|\b(?:уже\s+)?не\s+(?:нужно|требуется|актуально)\b", re.I)
GREETING = re.compile(r"здравствуй|добро[еы] .{0,5}(?:утро|день|вечер)", re.I)
POST_SERVICE = re.compile(r"претензи|верн\w*.{0,20}деньг|возврат.{0,20}денег|(?:снова|вс[её]\s+равно).{0,30}(?:подтека|теч[её]|не\s+работ|слом)|работ\w*.{0,20}не\s*выполн", re.I)
REQUEST_NOTE = re.compile(r"\s*\d{6,8}(?:\s+(?:прозвон|гара|гарантия))?\s*", re.IGNORECASE)


def private_open(path):
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w")


def main():
    OUT.mkdir(exist_ok=True, mode=0o700)
    db = sqlite3.connect("file:" + str(SOURCE / "history-private.sqlite") + "?mode=ro", uri=True)
    db.execute("PRAGMA query_only=ON")
    department_by_message = {r["message_id"]: r.get("department") for r in map(json.loads, (OUT / "message-departments-private.jsonl").open()) if r["kind"] == "message_department"}
    sources = {}
    for cid, raw in db.execute("SELECT id,data FROM conversations"):
        sources[hashlib.sha256(cid.encode()).hexdigest()] = (cid, json.loads(raw))
    counts, flags, years, authors, lengths, bundles = (collections.Counter() for _ in range(6))
    per_author = collections.defaultdict(collections.Counter)
    department_counts, chatter_stages, chatter_patterns = collections.Counter(), collections.Counter(), collections.Counter()
    samples = collections.defaultdict(list)
    last_dialog, rows, by_id = None, [], {}
    with private_open(OUT / "practice-ledger-private.jsonl") as ledger:
        for line in (SOURCE / "human-turns-private.jsonl").open():
            turn = json.loads(line)
            cid, source = sources[turn["source_dialog"]]
            if cid != last_dialog:
                rows = [json.loads(r[0]) for r in db.execute("SELECT data FROM messages WHERE cid=? ORDER BY ts,id", (cid,))]
                by_id = {m["id"]: m for m in rows}
                last_dialog = cid
            reply = [by_id[mid] for mid in turn["reply_message_ids"]]
            assert all(m["direction"] == "out" for m in reply)
            text = "\n".join(m.get("text") or m.get("transcript") or "" for m in reply)
            before = rows[:turn["cut_message_index"]]
            prior_client = [m for m in before if m["direction"] == "in"]
            last_in = next((m.get("text") or m.get("transcript") or "" for m in reversed(prior_client) if m.get("text") or m.get("transcript")), "")
            author = turn.get("author") or "unattributed"
            departments = {department_by_message.get(mid) for mid in turn["reply_message_ids"]}
            department = next(iter(departments)) if len(departments) == 1 else "mixed_or_unknown"
            department_counts[str(department or "unknown")] += 1
            is_chatter = department == "Чатер"
            prior_text = "\n".join(m.get("text") or m.get("transcript") or "" for m in prior_client)
            existing_note = any(m["direction"] == "note" and m.get("sender_type") == "operator" and REQUEST_NOTE.fullmatch(m.get("text") or "") for m in before)
            stage = "post_service_or_complaint" if POST_SERVICE.search(prior_text) else "existing_request_note" if existing_note else "initial_chat"
            counts["reply_blocks"] += 1
            counts["outgoing_messages"] += len(reply)
            counts["chronology_ambiguous_blocks"] += bool(turn["chronology_ambiguous"])
            counts["attributed_blocks"] += bool(turn.get("author"))
            counts["unattributed_blocks"] += not bool(turn.get("author"))
            authors[author] += 1
            years[turn["timestamp"][:4]] += 1
            lengths["under_80" if len(text) < 80 else "80_to_200" if len(text) <= 200 else "over_200"] += 1
            bundles[str(min(len(reply), 5)) + ("+" if len(reply) >= 5 else "")] += 1
            tags = [key for key, pattern in P.items() if pattern.search(text)]
            first_out = not any(m["direction"] == "out" for m in before)
            if first_out:
                counts["first_human_reply_blocks"] += 1
                tags.append("first_reply_with_greeting" if GREETING.search(text) else "first_reply_without_greeting_candidate")
            if PRICE_QUESTION.search(last_in) and "bundled_phone_address_request" in tags and not PRICE_ANSWER.search(text):
                tags.append("contact_request_after_price_question_without_price_in_same_block")
            if REFUSAL.search(last_in) and "bundled_phone_address_request" in tags:
                tags.append("contact_request_after_possible_refusal")
            # Inventory chronology only: a link may have been added after actual
            # creation; no classification as a false promise from this timestamp.
            if "completed_action_statement" in tags and not (source.get("crm_at") and source["crm_at"] <= turn["timestamp"]):
                tags.append("completed_action_statement_without_prior_crm_link")
            flags.update(tags)
            per_author[author].update(tags)
            per_author[author]["reply_blocks"] += 1
            if is_chatter:
                chatter_stages[stage] += 1
                if stage == "initial_chat":
                    chatter_patterns.update(tags)
            record = {**turn, "cid": cid, "crm_id": source.get("crm_request_id"), "tags": tags,
                      "reply_chars": len(text), "reply_messages": len(reply), "channel": source.get("channel"),
                      "current_department": department, "chatter_department": is_chatter, "stage_for_review": stage,
                      "style_learning_candidate": is_chatter and stage == "initial_chat" and not turn["chronology_ambiguous"],
                      "training_gold": False, "normative_correctness": "unreviewed", "outcome_claim": None}
            ledger.write(json.dumps(record, ensure_ascii=False) + "\n")
            # Reproducible recent examples for sequential human review; every
            # pattern can have counterexamples. Do not select by CRM success.
            if is_chatter and stage == "initial_chat" and source.get("channel") == "avito" and author in EXPERTS and turn["timestamp"] >= "2026-10-01" and not turn["chronology_ambiguous"]:
                for tag in tags:
                    rank = hashlib.sha256((tag + turn["case_id"]).encode()).hexdigest()
                    samples[tag].append((rank, record))
                    samples[tag].sort(key=lambda x: x[0])
                    del samples[tag][4:]
    coverage = json.loads((SOURCE / "coverage-summary.json").read_text())
    assert counts["reply_blocks"] == coverage["coverage"]["human_reply_turns"]
    summary = {"snapshot_at": json.loads(db.execute("SELECT data FROM metadata WHERE key='snapshot'").fetchone()[0])["at"],
               "counts": dict(counts), "patterns": dict(flags), "authors": dict(authors), "years": dict(years),
               "reply_length_buckets_chars": dict(lengths), "messages_per_reply_block": dict(bundles),
               "per_author": {key: dict(value) for key, value in per_author.items()},
               "reply_blocks_by_current_department": dict(department_counts), "chatter_department_stages": dict(chatter_stages),
               "chatter_initial_patterns": dict(chatter_patterns),
               "department_scope": "Exact current department Чатер; OKK/reviews/other/unknown are excluded from style candidates. Historical department changes are unavailable.",
               "all_snapshot_reply_blocks_scanned": True, "manually_semantically_reviewed_all": False,
               "unknown_authors_not_assumed_human_experts": True, "crm_link_is_not_creation_time": True,
               "motives_or_conversion_inferred": False, "automatic_training_updates": 0, "external_model_calls": 0,
               "customer_writes": 0, "auto_enabled": False, "interpretation": "Pattern counts are candidates for contextual review, not employee violation rates or causal measures of success."}
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    with private_open(OUT / "review-samples-private.json") as f:
        json.dump({tag: [row for _, row in ranked] for tag, ranked in samples.items()}, f, ensure_ascii=False, indent=2)
    print(json.dumps({"counts": dict(counts), "patterns": dict(flags), "authors": len(authors), "all_snapshot_reply_blocks_scanned": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
