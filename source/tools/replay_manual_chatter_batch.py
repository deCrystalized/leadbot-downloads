"""Offline proposals at explicit cuts of the manually read first 20 chats.

This is a development regression sample, not a held-out quality score. Current
CRM card fields, later replies and manually written conclusions are not input.
Private source artifacts are deliberately absent from the repository.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from manual_program_guard import assert_development_dialogues, assert_development_phones

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "test-artifacts/human-practice/manual-batch20"
sys.path.insert(0, str(ROOT / "leadbot/brain"))
import contact_phone
from assistant_store import Store
from contact_cities import city_by_slug
from extension_assistant import Assistant


def main():
    rows = json.loads((OUT / "sources-private.json").read_text())
    assert_development_dialogues(row["cid"] for row in rows)
    assert_development_phones(phone.value for row in rows for m in row["messages"] if m.get("direction") == "in" for phone in contact_phone.find_all(m.get("text") or m.get("transcript") or ""))
    assert len(rows) == 20 and all(r["manual_review_complete"] for r in rows)
    os.environ["LEADBOT_ASSISTANT_WORDING"] = "reviewed"
    results = []
    cuts = {13: 29, 14: 21, 15: 2, 16: 1, 17: 70, 18: 8, 19: 18, 20: 24}
    # Full histories were read first. Media stay unapproved for the executable
    # path: offline visual inspection must not manufacture a live permission.
    expected = {1: "wait", 2: "wait", 3: "handoff", 4: "question", 5: "wait", 6: "wait", 7: "handoff",
                8: "handoff", 9: "wait", 10: "wait", 11: "handoff", 12: "handoff", 13: "handoff",
                14: "handoff", 15: "question", 16: "question", 17: "handoff", 18: "question", 19: "handoff", 20: "handoff"}
    with tempfile.TemporaryDirectory() as temp:
        app = Assistant(Store(str(Path(temp) / "db")))
        for row in rows:
            source, number = row["source"], row["number"]
            cut = cuts.get(number)
            if cut is None:
                cut = next((i for i, m in enumerate(row["messages"]) if source.get("crm_at") and m["ts"] >= source["crm_at"]), len(row["messages"]))
            history = row["messages"][:cut]
            title = source.get("account_title") or ""
            city = city_by_slug(source.get("city"))
            linked = source.get("crm_at") and history and source["crm_at"] <= history[-1]["ts"]
            ctx = {"convId": "manual-review-" + str(number), "city": city.name if city else source.get("city"),
                   "dir": next((d for name, d in (("МНЧ", "mnc"), ("КП", "kp"), ("БТ", "bt")) if name in title), ""),
                   "partner": source.get("partner"), "accountTitle": title, "origin": source.get("origin"),
                   "itemTitle": source.get("item_title"), "channel": source.get("channel"),
                   "crmRequestId": str(source["crm_request_id"]) if linked else "",
                   "messages": [{"id": m["id"], "direction": m["direction"], "sender_type": m.get("sender_type"),
                                 "body": m.get("text") or m.get("transcript") or "", "created_at": m["ts"],
                                 "voice_transcript": m.get("transcript") or "", "delivery_status": m.get("delivery") or "",
                                 "attachments": [{"type": t} for t in (m.get("attachment_types") or [])]} for m in history]}
            out, code = app.handle({"owner": "manual-chatter-audit", "action": "preview", "ctx": ctx})
            assert code == 200 and out.get("auto_enabled") is False and not out.get("pending_model") and not out.get("validation")
            assert out["action"] == expected[number], (number, out.get("action"), out.get("reason"))
            if number == 4:
                assert "какой из указанных номеров" in out["reply"]
            if number == 14:
                assert "служебной заметке" in out["reason"]
            if number == 16:
                assert "в каком городе" in out["reply"] and not out.get("price_amounts")
            if number == 18:
                assert out["facts"]["address"]["entrance"] == "3" and out["facts"]["address"]["intercom"] == "116"
            if number == 19:
                assert "DOC-L0798" in out["rule_ids"] and not out["facts"]["address_needs_confirmation"]
            results.append({"case": number, "cid": row["cid"], "cut": cut, "last_message_id": history[-1]["id"],
                            "ctx": ctx, "decision": out, "current_crm_card_used_as_input": False})
            print(number, cut, out.get("action"), out.get("reply"), out.get("reason"))
    path = OUT / "reviewed-prefix-proposals-private.json"
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    path.chmod(0o600)


if __name__ == "__main__":
    main()
