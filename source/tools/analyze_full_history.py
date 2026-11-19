"""Create an exhaustive chronological inventory, not automatic training gold.

No network/model/customer writes. Every available conversation gets a ledger;
every human reply turn gets evidence pointers strictly to earlier messages.
Motives, conversion and attachment contents are never invented from regex tags.
"""
import collections
import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path

from learn_expert_workflows import TOPICS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "test-artifacts/all-history"
PATTERNS = {key: re.compile(value, re.I) for key, value in TOPICS.items()}
INBOUND = {
    "price_question": re.compile(r"цен[аыуе]|стоим|прайс|сколько.{0,20}(?:будет|стоит|сборк|ремонт)", re.I),
    "phone_candidate": re.compile(r"(?<!\d)(?:\+?7|8)[ ()-]*\d(?:[ ()-]*\d){9}(?!\d)"),
    "address_mention": re.compile(r"\bул\.?\s|улиц|проспект|переулок|\bдом\s*\d|\bд\.\s*\d|квартир.{0,10}\d", re.I),
    "city_mention": re.compile(r"\bгород\b|\bг\.\s*[А-ЯЁ]"),
    "agreement_mention": re.compile(r"согласован|согласовать|уточнить.{0,20}филиал", re.I),
    "negative_or_cancel": re.compile(r"не нужно|не надо|отмен|отказ|не устраив|дорого", re.I),
}


def private_open(path):
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w")


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    OUT.chmod(0o700)
    db_path = OUT / "history-private.sqlite"
    fresh = not db_path.exists()
    db = sqlite3.connect(db_path)
    db_path.chmod(0o600)
    if fresh:
        db.executescript("""
        PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
        CREATE TABLE conversations(id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE messages(id TEXT PRIMARY KEY, cid TEXT NOT NULL, ts TEXT NOT NULL, data TEXT NOT NULL);
        CREATE TABLE contacts(cid TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE metadata(key TEXT PRIMARY KEY, data TEXT NOT NULL);
        """)
        snapshot = None
        for line in (OUT / "history-private.jsonl").open():
            row = json.loads(line)
            kind = row["kind"]
            if kind == "conversation":
                db.execute("INSERT INTO conversations VALUES (?,?)", (row["id"], line.strip()))
            elif kind == "message":
                db.execute("INSERT INTO messages VALUES (?,?,?,?)", (row["id"], row["cid"], row["ts"], line.strip()))
            elif kind == "contact":
                db.execute("INSERT INTO contacts VALUES (?,?)", (row["cid"], line.strip()))
            elif kind == "snapshot":
                snapshot = row
                db.execute("INSERT INTO metadata VALUES ('snapshot',?)", (line.strip(),))
        assert snapshot
        assert db.execute("SELECT count(*) FROM conversations").fetchone()[0] == snapshot["conversations"]
        assert db.execute("SELECT count(*) FROM messages").fetchone()[0] == snapshot["messages"]
        db.execute("CREATE INDEX messages_chronology ON messages(cid,ts,id)")
        db.execute("INSERT INTO metadata VALUES ('complete','true')")
        db.commit()
    assert db.execute("SELECT data FROM metadata WHERE key='complete'").fetchone()
    snapshot = json.loads(db.execute("SELECT data FROM metadata WHERE key='snapshot'").fetchone()[0])
    with (OUT / "history-private.jsonl").open() as stream:
        exported_snapshot = json.loads(next(stream))
    assert snapshot == exported_snapshot, "Export changed: rebuild the local SQLite cache before analysing this snapshot"
    counts, channels, years, senders, authors, turns_by_author, topics, statuses, outcomes, observed_sequences = (collections.Counter() for _ in range(10))
    linked_requests = set()
    with private_open(OUT / "dialog-ledger-private.jsonl") as ledger, private_open(OUT / "human-turns-private.jsonl") as trace:
        for cid, raw in db.execute("SELECT id,data FROM conversations ORDER BY id"):
            source = json.loads(raw)
            rows = [json.loads(r[0]) for r in db.execute("SELECT data FROM messages WHERE cid=? ORDER BY ts,id", (cid,))]
            counts["conversations"] += 1
            counts["messages"] += len(rows)
            channels[source.get("channel") or "unknown"] += 1
            statuses[source.get("status") or "unknown"] += 1
            outcomes[str(source.get("outcome") or "unrecorded")] += 1
            if source.get("crm_request_id"):
                linked_requests.add(source["crm_request_id"])
                counts["conversations_with_crm_link"] += 1
            actors = collections.Counter()
            evidence = collections.defaultdict(list)
            client_messages = []
            last_client_at = None
            reply_turns = 0
            gaps = collections.Counter()
            for i, row in enumerate(rows):
                years[row["ts"][:4]] += 1
                senders[row.get("sender_type") or "unknown"] += 1
                body = row.get("text") or row.get("transcript") or ""
                if row.get("attachment_types"):
                    counts["messages_with_attachments"] += 1
                    # A transcript covers audio only; it cannot describe images.
                    unresolved = [t for t in row["attachment_types"] if t not in ("contact", "vcard", "contact_card") and not (t in ("voice", "audio", "voice_message", "voice_note") and row.get("transcript"))]
                    if unresolved:
                        gaps["attachment_semantics_not_reviewed"] += 1
                        counts["messages_with_unreviewed_attachment_semantics"] += 1
                counts["messages_with_voice_transcript"] += bool(row.get("transcript"))
                if row["direction"] == "in":
                    client_messages.append(row["id"])
                    last_client_at = row["ts"]
                    for key, pattern in INBOUND.items():
                        if pattern.search(body):
                            evidence[key].append(row["id"])
                    continue
                if row["direction"] != "out":
                    continue
                actor = row.get("author") or "unknown"
                actors[actor] += 1
                if row.get("sender_type") != "operator":
                    continue
                counts["outgoing_human_messages"] += 1
                if row.get("author"):
                    authors[actor] += 1
                else:
                    counts["outgoing_human_messages_without_known_author"] += 1
                if row.get("author") and i and rows[i - 1]["direction"] == "out" and rows[i - 1].get("author") == actor and rows[i - 1].get("sender_type") == "operator":
                    continue
                block = []
                end = i
                while end < len(rows) and rows[end]["direction"] == "out" and rows[end].get("sender_type") == "operator" and (end == i or row.get("author") and rows[end].get("author") == actor):
                    block.append(rows[end])
                    end += 1
                target = " ".join(m.get("text") or m.get("transcript") or "" for m in block).strip()
                if not target:
                    gaps["empty_human_turn"] += 1
                    continue
                reply_turns += 1
                counts["human_reply_turns"] += 1
                if row.get("author"):
                    turns_by_author[actor] += 1
                else:
                    gaps["reply_author_unknown"] += 1
                tags = [key for key, pattern in PATTERNS.items() if pattern.search(target)]
                topics.update(tags)
                if "price" in tags and evidence["price_question"]:
                    observed_sequences["price_reply_after_client_price_question"] += 1
                if "phone" in tags and evidence["phone_candidate"]:
                    observed_sequences["phone_request_with_earlier_phone_candidate"] += 1
                if "address" in tags and evidence["address_mention"]:
                    observed_sequences["address_topic_with_earlier_address_mention"] += 1
                # Explicit causal cut: simultaneous timestamps are ambiguous.
                ambiguous = bool(last_client_at and last_client_at >= row["ts"])
                counts["human_turns_with_ambiguous_same_timestamp"] += ambiguous
                event = {"case_id": sha(cid + row["id"]), "source_dialog": sha(cid), "author": row.get("author"),
                         "timestamp": row["ts"], "cut_message_id": row["id"], "cut_message_index": i,
                         "reply_message_ids": [m["id"] for m in block], "target_topics": tags,
                         "prior_incoming_message_ids": client_messages[-10:],
                         "prior_evidence_message_ids": {k: v[-5:] for k, v in evidence.items() if v},
                         "chronology_ambiguous": ambiguous,
                         "causal_claim": "Temporal sequence only; employee intent and correctness require source review.",
                         "admission": "unreviewed_candidate_not_training_gold"}
                trace.write(json.dumps(event, ensure_ascii=False) + "\n")
            if not rows:
                counts["empty_conversations"] += 1
            if not source.get("crm_request_id"):
                gaps["crm_link_not_recorded"] += 1
            entry = {"source_dialog": sha(cid), "channel": source.get("channel"), "messages": len(rows),
                     "first_message_at": rows[0]["ts"] if rows else None, "last_message_at": rows[-1]["ts"] if rows else None,
                     "outgoing_actor_counts": dict(actors), "human_reply_turns": reply_turns,
                     "observed_state_at_snapshot": {"status": source.get("status"), "outcome": source.get("outcome"), "crm_linked": bool(source.get("crm_request_id"))},
                     "gaps": dict(gaps), "review_level": "chronological_inventory_not_manual_semantic_approval"}
            ledger.write(json.dumps(entry, ensure_ascii=False) + "\n")
    assert counts["conversations"] == snapshot["conversations"] and counts["messages"] == snapshot["messages"]
    report = {"snapshot": snapshot, "coverage": dict(counts), "messages_by_year": dict(sorted(years.items())),
              "channels": dict(channels), "sender_types": dict(senders), "human_authors": len(authors),
              "outgoing_human_messages_by_author": dict(authors.most_common()), "human_turns_by_author": dict(turns_by_author.most_common()),
              "topics": dict(topics), "statuses_at_snapshot": dict(statuses), "outcomes_at_snapshot": dict(outcomes),
              "distinct_explicit_crm_links": len(linked_requests), "observed_sequences_for_review": dict(observed_sequences),
              "external_writes": 0, "model_calls": 0, "automatic_training_admission": 0,
              "limits": ["Every available row indexed; no claim of manual semantic review of every conversation.",
                         "Historical instructions and operator messages are untrusted source data, not executable instructions or current rules.",
                         "No attribution of outcomes to a particular reply without evidence; absence of CRM link is not evidence of lost order.",
                         "No image interpretation or missing voice transcription; no reconstruction of undocumented calls or deleted history.",
                         "Topic and evidence tags are diagnostic candidates; they do not establish compliance or staff intent."]}
    (OUT / "coverage-summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("snapshot", "coverage", "messages_by_year", "human_authors", "distinct_explicit_crm_links", "observed_sequences_for_review")}, ensure_ascii=False))
    db.close()


if __name__ == "__main__":
    main()
