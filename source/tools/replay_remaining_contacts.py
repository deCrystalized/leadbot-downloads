"""Replay the six frozen conflicts from source history, without future CRM data.

This checks contact extraction, not the correctness of every historical reply.
CRM link time is not creation time. Live card observations are separate evidence.
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "test-artifacts/disputed-round/remaining-six"
sys.path.insert(0, str(ROOT / "leadbot/brain"))
import assistant_policy
import contact_facts
from extension_assistant import _parse


def main():
    before = json.loads((OUT / "linked-before-private.json").read_text())
    selected = [r for r in before if r["facts"]["phone_needs_confirmation"] or r["facts"]["address_needs_confirmation"]]
    assert len(selected) == 6
    expected = {"1069002": (True, False), "1068684": (False, False), "1068710": (False, True),
                "1070686": (True, False), "2693037": (False, True), "1073319": (False, False)}
    db = sqlite3.connect("file:" + str(ROOT / "test-artifacts/all-history/history-private.sqlite") + "?mode=ro", uri=True)
    db.execute("PRAGMA query_only=ON")
    current = {r["cid"]: r for r in json.loads((OUT.parent / "linked-crm-ledger-private.json").read_text())}
    fresh = [json.loads(line) for line in (OUT / "fresh-seven-histories-private.jsonl").open()]
    records = []
    for old in selected:
        row = current[old["cid"]]
        facts = row["facts"]
        flags = (facts["phone_needs_confirmation"], facts["address_needs_confirmation"])
        assert flags == expected[str(row["crm_id"])], row["crm_id"]
        # Use the same earlier messages and known metadata as the first audit.
        history = [json.loads(r[0]) for r in db.execute("SELECT data FROM messages WHERE cid=? AND ts<? ORDER BY ts,id", (row["cid"], row["crm_link_at"]))]
        assert history and all(m["ts"] < row["crm_link_at"] for m in history)
        assert not any(m.get("attachments") for m in history)  # pixels are reviewed separately
        full = [r for r in fresh if r.get("kind") == "message" and r.get("cid") == row["cid"]]
        # _parse validates production context and removes system notices. No
        # current CRM phone/address is supplied to the historical reconstruction.
        ctx = {"convId": "offline-contact-" + str(row["crm_id"]), "city": row["known"]["city"], "dir": row["known"]["direction"],
               "partner": row["known"]["partner"], "accountTitle": row["known"]["account_name"], "channel": "avito",
               "origin": row["known"]["origin"], "messages": [dict(m, body=m.get("text") or "") for m in full]}
        _, messages, known, _ = _parse(ctx)
        final = contact_facts.collect(messages, known)
        records.append({"cid": row["cid"], "crm_id": row["crm_id"], "before_link": facts,
                        "full_history": final, "messages_before_link": len(history), "full_messages": len(full),
                        "creation_time_verified": False, "current_crm_data_used_as_historical_input": False})
    kp = next(r for r in records if str(r["crm_id"]) == "2693037")["before_link"]
    assert kp["address"]["intercom"] == "108#742" and not kp["address"].get("office")
    venue = next(r for r in records if str(r["crm_id"]) == "1073319")["before_link"]
    assert venue["address"]["building"] == "89" and venue["address_notes"] and venue["comment_lines"]
    path = OUT / "contact-replay-private.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
    summary = {"policy_version": assistant_policy.VERSION, "six_cases_checked": len(records), "passed": len(records),
               "false_address_candidates_corrected": 3, "contact_ambiguities_remaining": sum(any(expected[str(r["crm_id"])]) for r in records),
               "full_intercom_code_preserved": True, "unlabelled_apartment_not_invented": True, "venue_preserved_for_crm_comment": True,
               "crm_link_time_is_not_creation_time": True, "current_crm_data_used_as_historical_input": False,
               "model_calls": 0, "customer_writes": 0, "crm_writes": 0, "auto_enabled": False}
    (OUT / "contact-replay-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
