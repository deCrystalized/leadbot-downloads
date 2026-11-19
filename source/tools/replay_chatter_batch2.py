"""Offline development replay of manually reviewed chats 21-40; no live grant.

Private sources are not committed. Current CRM fields, future messages and
human conclusions are excluded. This sample is not a held-out accuracy score.
"""
import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from manual_program_guard import assert_development_dialogues, assert_development_phones

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "test-artifacts/human-practice/manual-batch21-40"
sys.path.insert(0, str(ROOT / "leadbot/brain"))
import contact_phone
from assistant_store import Store
from contact_cities import city_by_slug
from extension_assistant import Assistant

CUTS = {21: 14, 22: 39, 23: 12, 24: 2, 25: 11, 26: 1, 27: 39, 28: 10, 29: 10, 30: 5,
        31: 33, 32: 37, 33: 30, 34: 13, 35: 29, 36: 35, 37: 36, 38: 21, 39: 27, 40: 17}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", choices=("baseline", "final"), required=True)
    parser.add_argument('--adjudications',help='Separate primary-source resolutions, preserving original manual labels')
    args = parser.parse_args()
    resolutions={}
    if args.adjudications:
        p=(OUT/args.adjudications).resolve()
        assert p.parent==OUT.resolve() and p.suffix=='.json'
        import hashlib
        revised=json.loads(p.read_text())
        assert revised['original_ledger_sha256']==hashlib.sha256((OUT/'manual-review-private.json').read_bytes()).hexdigest()
        for row in revised['resolutions']:
            assert row['reviewed'] is True and row['reason'] and row['primary_rule_ids']
            assert CUTS[row['case']]==row['cut']
            resolutions[row['case']]=row
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
            ctx = {"convId": "manual-batch2-" + str(number), "city": city.name if city else source.get("city"),
                   "dir": next((d for name, d in (("МНЧ", "mnc"), ("КП", "kp"), ("БТ", "bt")) if name in title), ""),
                   "partner": source.get("partner"), "accountTitle": title, "origin": source.get("origin"),
                   "itemTitle": source.get("item_title"), "channel": source.get("channel"),
                   "crmRequestId": str(source["crm_request_id"]) if linked else "",
                   "messages": [{"id": m["id"], "direction": m["direction"], "sender_type": m.get("sender_type"),
                                 "body": m.get("text") or m.get("transcript") or "", "created_at": m["ts"],
                                 "voice_transcript": m.get("transcript") or "", "delivery_status": m.get("delivery") or "",
                                 "attachments": m.get("attachments") or []} for m in history]}
            out, code = app.handle({"owner": "offline-manual-batch2", "action": "preview", "ctx": ctx})
            assert code == 200 and out.get("auto_enabled") is False and not out.get("pending_model") and not out.get("validation")
            if args.tag == "final":
                expected = "question" if number in (21, 22, 23, 24, 38, 40) else "handoff"
                if number in resolutions:
                    revised=resolutions[number]
                    assert revised['original_expected_action']==expected
                    expected=revised['resolved_expectation']['expected_action']
                    for pattern in revised['resolved_expectation'].get('required_reply_patterns',[]):
                        assert re.search(pattern,out.get('reply',''),re.IGNORECASE),(number,pattern)
                    for pattern in revised['resolved_expectation'].get('forbidden_reply_patterns',[]):
                        assert not re.search(pattern,out.get('reply',''),re.IGNORECASE),(number,pattern)
                assert out["action"] == expected, (number, out["action"], out.get("reason"))
                if number == 22:
                    assert out["crm_flags"]["callbefore"] and out["facts"]["call_before_visit"]
                if number == 27:
                    assert out["facts"]["address"]["building"] == "39"
                if number == 32:
                    assert out["facts"]["address"]["intercom"] == "62В"
                if number == 35:
                    assert "DOC-L1051" in out["rule_ids"]
                if number == 38:
                    assert out["facts"]["address"]["office"] == "2" and out["facts"]["address_needs_confirmation"]
                if number == 39:
                    assert "140" in out["facts"]["address"]["street"]
                if number == 40:
                    assert any("Калитка" in line for line in out["facts"]["comment_lines"])
            results.append({"case": number, "cid": row["cid"], "cut": CUTS[number], "ctx": ctx, "decision": out,
                            "current_crm_fields_used_as_input": False, "send_authorized": False})
            print(number, out.get("action"), out.get("reply"), out.get("reason"))
    path = OUT / (args.tag + "-proposals-private.json")
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    path.chmod(0o600)


if __name__ == "__main__":
    main()
