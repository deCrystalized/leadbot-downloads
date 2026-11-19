"""Evidence audit of all explicit CRM links; does not fetch or modify CRM.

crm_request_at is the LeadChat LINK time. It is not independently verified CRM
creation time. Only the separately observed cards can support a card comparison.
"""
import collections
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "test-artifacts/disputed-round"
sys.path.insert(0, str(ROOT / "leadbot/brain"))
import contact_facts
from contact_cities import city_by_slug
from extension_assistant import _parse
from manual_program_guard import assert_development_dialogues


def development_linked_rows(db):
    rows = list(db.execute("SELECT id,data FROM conversations WHERE json_extract(data,'$.crm_request_id') IS NOT NULL"))
    # The gate is inside the executable, before any history/contacts are read.
    # A failed prior shell command cannot accidentally bypass it.
    assert_development_dialogues(cid for cid, _ in rows)
    return rows


def main():
    db = sqlite3.connect("file:" + str(ROOT / "test-artifacts/all-history/history-private.sqlite") + "?mode=ro", uri=True)
    db.execute("PRAGMA query_only=ON")
    media = {r["id"]: r["attachments"] for r in map(json.loads, (OUT / "attachments-private.jsonl").open())}
    before_path = OUT / "linked-crm-ledger-before-contact-fix-private.json"
    before = {r["cid"]: r.get("facts", {}) for r in json.loads(before_path.read_text())}
    ledger, changes = [], []
    counts = collections.Counter()
    for cid, text in development_linked_rows(db):
        source = json.loads(text)
        if not source.get("crm_request_id"):
            continue
        counts["linked_dialogues"] += 1
        history = [json.loads(r[0]) for r in db.execute("SELECT data FROM messages WHERE cid=? AND ts<? ORDER BY ts,id", (cid, source.get("crm_at") or ""))]
        if not history or len(history) > 300:
            counts["context_pending"] += 1
            continue
        city = city_by_slug(source.get("city"))
        title = source.get("account_title") or ""
        direction = next((d for label, d in (("МНЧ", "mnc"), ("КП", "kp"), ("БТ", "bt")) if label in title), "")
        ctx = {"convId": cid, "city": city.name if city else source.get("city"), "dir": direction, "partner": source.get("partner"),
               "origin": source.get("origin"), "accountTitle": title, "itemTitle": source.get("item_title"), "channel": source.get("channel"),
               "messages": [{"id": m["id"], "direction": m["direction"], "sender_type": m.get("sender_type"), "body": m.get("text") or "",
                             "voice_transcript": m.get("transcript") or "", "attachments": media.get(m["id"], [])} for m in history]}
        _, messages, known, _ = _parse(ctx)
        facts = contact_facts.collect(messages, known)
        counts["contexts_parsed"] += 1
        counts["phone_available_before_link"] += bool(facts["contact_phone_to_use"])
        counts["building_available_before_link"] += bool(facts["address"].get("building"))
        counts["office_available_before_link"] += bool(facts["address"].get("office"))
        counts["contact_conflicts_after"] += bool(facts["phone_needs_confirmation"] or facts["address_needs_confirmation"])
        old = before.get(cid, {})
        counts["contact_conflicts_before"] += bool(old.get("phone_needs_confirmation") or old.get("address_needs_confirmation"))
        if old.get("address") != facts["address"] or old.get("address_needs_confirmation") != facts["address_needs_confirmation"]:
            changes.append({"cid": cid, "before": old, "after": facts})
        ledger.append({"cid": cid, "crm_id": source["crm_request_id"], "crm_link_at": source.get("crm_at"), "crm_created_at": None,
                       "known": known, "facts": facts, "training_outcome_eligible": False,
                       "cut_semantics": "Before CRM link event; exact creation time and intermediate card edits are not verified."})
    expected_links = db.execute("SELECT count(*) FROM conversations WHERE json_extract(data,'$.crm_request_id') IS NOT NULL").fetchone()[0]
    assert counts["linked_dialogues"] == expected_links
    for name, data in (("linked-crm-ledger-private.json", ledger), ("contact-fix-changes-private.json", changes)):
        path = OUT / name
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(json.dumps(data, ensure_ascii=False) + "\n")
    report = {**dict(counts), "changed_address_contexts": len(changes), "crm_link_at_is_not_creation_time": True,
              "all_actual_crm_cards_verified": False, "phone_similarity_auto_correction": False, "external_writes": 0}
    (OUT / "contact-fix-summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
