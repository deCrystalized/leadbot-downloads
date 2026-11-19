"""Offline development replay of manually reviewed chats 41-60; no live grant.

Private sources are not committed. Current CRM fields, future messages and
human conclusions are excluded. This sample is not a held-out accuracy score.
"""
import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from manual_program_guard import assert_development_dialogues, assert_development_phones

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "test-artifacts/human-practice/manual-batch41-60"
sys.path.insert(0, str(ROOT / "leadbot/brain"))
import contact_phone
from assistant_store import Store
from contact_cities import city_by_slug
from extension_assistant import Assistant

CUTS = {41:12,42:9,43:33,44:15,45:23,46:29,47:14,48:15,49:23,50:22,51:24,52:17,53:20,54:29,55:15,56:22,57:13,58:27,59:13,60:19}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", choices=("baseline", "final"), required=True)
    parser.add_argument('--adjudications', help='Separate source-bound primary review; original labels and first results remain intact')
    args = parser.parse_args()
    resolutions = {}
    if args.adjudications:
        path = (OUT / args.adjudications).resolve()
        assert path.parent == OUT.resolve() and path.suffix == '.json'
        review = json.loads(path.read_text())
        assert review['original_ledger_sha256'] == hashlib.sha256((OUT / 'manual-review-private.json').read_bytes()).hexdigest()
        assert review['source_sha256'] == hashlib.sha256((OUT / 'sources-private.json').read_bytes()).hexdigest()
        for row in review['resolutions']:
            assert row['reviewed'] is True and row['primary_rule_ids'] and row['reason']
            assert row['cut'] == CUTS[row['case']]
            original = 'question' if row['case'] in (41,49,55,57) else 'handoff'
            assert row['original_expected_action'] == original and row['case'] not in resolutions
            resolutions[row['case']] = row['resolved_expectation']['expected_action']
    rows = json.loads((OUT / "sources-private.json").read_text())
    assert_development_dialogues(row["cid"] for row in rows)
    assert_development_phones(phone.value for row in rows for m in row["messages"] if m.get("direction") == "in" for phone in contact_phone.find_all(m.get("text") or m.get("transcript") or ""))
    assert len(rows) == 20
    os.environ["LEADBOT_ASSISTANT_WORDING"] = "reviewed"
    results = []
    with tempfile.TemporaryDirectory() as temp:
        app = Assistant(Store(str(Path(temp) / "db")))
        for row in rows:
            number, source = row["number"], row["source"]
            history = row["messages"][:CUTS[number]]
            title = source.get("account_title") or ""
            city = city_by_slug(source.get("city"))
            linked = source.get("crm_at") and source["crm_at"] <= history[-1]["ts"]
            ctx = {"convId": "manual-batch3-" + str(number), "city": city.name if city else source.get("city"),
                   "dir": "bt" if number in (45, 49, 54, 60) else next((d for name, d in (("МНЧ", "mnc"), ("КП", "kp"), ("БТ", "bt")) if name in title), ""),
                   "partner": source.get("partner"), "accountTitle": title, "origin": source.get("origin"),
                   "itemTitle": source.get("item_title"), "channel": source.get("channel"),
                   "crmRequestId": str(source["crm_request_id"]) if linked else "",
                   "messages": [{"id": m["id"], "direction": m["direction"], "sender_type": m.get("sender_type"),
                                 "body": m.get("text") or m.get("transcript") or "", "created_at": m["ts"],
                                 "voice_transcript": m.get("transcript") or "", "delivery_status": m.get("delivery") or "",
                                 "attachments": m.get("attachments") or []} for m in history]}
            out, code = app.handle({"owner": "offline-manual-batch3", "action": "preview", "ctx": ctx})
            assert code == 200 and out.get("auto_enabled") is False and not out.get("pending_model") and not out.get("validation")
            if args.tag == "final":
                # Cases47/52: historical 800р/500р were quoted before the
                # permitted MNC/KP stages. DOC-L0774 requires agreement review.
                expected = "question" if number in (41, 49, 55, 57) else "handoff"
                expected = resolutions.get(number, expected)
                assert out["action"] == expected, (number, out["action"])
                facts = out["facts"]
                if number == 41:
                    assert len(facts["phone_values"]) == 1
                if number in (43, 48, 59, 60):
                    assert facts["call_before_visit"] and out["crm_flags"]["callbefore"]
                    assert any("Условия звонка" in line for line in facts["comment_lines"])
                if number == 48:
                    assert facts["address"]["building"] == "12"
                if number == 49:
                    assert facts["address"]["office"] == "ЧД"
                if number == 59:
                    assert facts["address"]["street"] == "Станиславского"
                    assert facts["address"]["office"] == "69"
                if number == 57:
                    assert facts["phone_needs_confirmation"] and not facts["contact_phone_to_use"]
                if number == 58:
                    # The explicit "second, just in case" now resolves the
                    # phone role. A separate unverified prior price still stops.
                    assert not facts['phone_needs_confirmation']
                    assert facts['contact_phone_to_use'] == facts['phone_values'][0]
                    assert facts['fallback_phones'][0]['value'] == facts['phone_values'][1]
                    assert 'Ранее названная стоимость' in out['reason']
            results.append({"case": number, "cid": row["cid"], "cut": CUTS[number], "ctx": ctx, "decision": out,
                            "current_crm_fields_used_as_input": False, "send_authorized": False})
            print(number, out.get("action"), out.get("reply"), out.get("reason"))
    path = OUT / (args.tag + "-proposals-private.json")
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    path.chmod(0o600)


if __name__ == "__main__":
    main()
