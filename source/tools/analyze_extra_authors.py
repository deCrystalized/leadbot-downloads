"""Read complete available conversations; no network or automatic style admission.

Only aggregate results leave the private work directory. Candidate sources must
precede the existing time cutoff and exclude every frozen holdout client group.
"""
import argparse
import collections
import hashlib
import json
import os
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT.parent / "leadbot-audit"
OUT = ROOT / "test-artifacts/extra-authors"
TARGETS = {"Казахбаев Зухратдин", "Востриков Глеб"}
CUTOFF = "2026-10-01T00:00:00+00:00"
TOPICS = {
    "phone": r"(?:номер|телефон).{0,35}(?:связ|подскаж|напиш)|(?:подскаж|напиш).{0,35}(?:номер|телефон)",
    "address": r"адрес|улиц|квартир",
    "city": r"(?:како\w*.{0,20}город|город.{0,20}(?:како|подскаж))",
    "model": r"марк\w*.{0,40}модел|модел\w*.{0,40}марк",
    "problem": r"что.{0,20}(?:случи|проблем)|какая.{0,15}проблем",
    "client_name": r"как.{0,12}(?:обращаться|зовут)|имя.{0,12}подскаж",
    "visit_time": r"(?:день|время).{0,20}удоб|удоб.{0,20}(?:день|время)",
    "decision_maker": r"(?:оплачи|оплат|на месте|присутств|решени)",
    "plumbing_ready": r"подключен|подключён|воде и электр",
    "load": r"загрузк|вертикаль|горизонталь",
    "wall": r"материал.{0,15}стен|стен.{0,15}материал|бетон|кирпич",
    "height": r"высот",
    "volume": r"сколько.{0,20}(?:штук|розет|светильник)|объ[её]м",
    "internet": r"интернет.{0,20}(?:проведен|проведён|подключ)",
}
PRICE = re.compile(r"цен|стоим|сколько.*(?:руб|стоит)|\d+\s*(?:руб|₽)", re.I)
PROMISE = re.compile(r"записал|оформил|ждите мастера|мастер (?:будет|приедет)|ожидайте мастера|приеду|подъеду|перезвоню", re.I)
PHONE = re.compile(r"(?<!\d)(?:\+?7|8)?[\s().-]*9\d{2}[\s().-]*\d{3}[\s().-]*\d{2}[\s().-]*\d{2}(?!\d)")


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def main():
    global OUT
    cli=argparse.ArgumentParser();cli.add_argument("--history", type=Path);cli.add_argument("--out", type=Path);args=cli.parse_args()
    OUT=args.out or OUT
    contacts=args.history or (AUDIT / "contacts-private.jsonl")
    histories=[args.history] if args.history else [AUDIT / name for name in ("history-private.jsonl", "bot-context-private.jsonl")]
    OUT.mkdir(parents=True, exist_ok=True);os.chmod(OUT, 0o700)
    groups = {}
    for r in map(json.loads, contacts.open()):
        if r.get("kind") != "contact":
            continue
        phone = re.sub(r"\D", "", r.get("phone") or "")
        groups[r["cid"]] = sha("phone:" + phone[-10:] if len(phone) >= 10 else "client:" + str(r["client_id"]))
    held = {r["client_group"] for r in map(json.loads, (ROOT / "test-artifacts/private-candidates/evaluation_unseen_clients.jsonl").open())}
    messages = collections.defaultdict(list);seen = set()
    for history in histories:
        for r in map(json.loads, history.open()):
            if r["kind"] != "message" or (r["id"], r["ts"]) in seen:
                continue
            seen.add((r["id"], r["ts"]));messages[r["cid"]].append(r)
    dialogs = {cid for cid, rows in messages.items() if any(m.get("author") in TARGETS and m.get("direction") == "out" for m in rows)}
    stats = {};candidates = {};turns = []
    for person in sorted(TARGETS):
        owned = [m for cid in dialogs for m in messages[cid] if m.get("author") == person and m.get("direction") == "out"]
        stats[person] = {"outbound_messages": len(owned), "dialogs": len({m["cid"] for m in owned}), "first_utc": min(m["ts"] for m in owned), "last_utc": max(m["ts"] for m in owned), "blocks": 0, "topics": collections.Counter(), "lengths": [], "price_related_blocks": 0, "action_promise_blocks": 0, "phone_reask_signals": 0}
    for cid in sorted(dialogs):
        rows = sorted(messages[cid], key=lambda m: (m["ts"], m["id"]))
        visible = [m for m in rows if m.get("direction") in ("in", "out") and (m.get("text") or "").strip()]
        for i, m in enumerate(visible):
            author = m.get("author")
            if author not in TARGETS or m["direction"] != "out" or m.get("sender_type") == "bot":
                continue
            if i and visible[i-1].get("author") == author and visible[i-1]["direction"] == "out":
                continue
            end = i+1
            while end < len(visible) and visible[end].get("author") == author and visible[end]["direction"] == "out":
                end += 1
            answer = "\n".join(x["text"] for x in visible[i:end]).strip()
            topics = [k for k, rx in TOPICS.items() if re.search(rx, answer, re.I)]
            s = stats[author];s["blocks"] += 1;s["topics"].update(topics);s["lengths"].append(len(answer))
            s["price_related_blocks"] += bool(PRICE.search(answer));s["action_promise_blocks"] += bool(PROMISE.search(answer))
            previous = "\n".join(x["text"] for x in visible[:i] if x["direction"] == "in")
            s["phone_reask_signals"] += "phone" in topics and bool(PHONE.search(previous))
            group = groups.get(cid, sha("dialog:" + cid))
            turns.append({"source_dialog": sha(cid), "client_group": group, "timestamp": m["ts"], "author": author, "topics": topics})
            if group in held or m["ts"] >= CUTOFF or len(topics) != 1 or not 8 <= len(answer) <= 200:
                continue
            if re.search(r"\d|https?://|www\.|@|\[|\]|<|>|руб|₽|цен|стоим|бесплат|приед|подъед|перезвон|запис|создал|передал|мастер.{0,10}будет|сегодня|завтра|извин|не занима|не работ|согласован|(?:ул\.|улица|проспект)", answer, re.I):
                continue
            if not re.search(r"\?|подскаж|уточни", answer, re.I):
                continue
            key = (topics[0], re.sub(r"\s+", " ", answer.lower()))
            e = candidates.setdefault(key, {"condition": topics[0], "answer": answer, "authors": collections.Counter(), "training_count": 0, "source_dialog_sha256": sha(cid), "source_client_group": group, "source_timestamp": m["ts"]})
            e["authors"][author] += 1;e["training_count"] += 1
    for s in stats.values():
        lengths = s.pop("lengths");s["median_reply_chars"] = statistics.median(lengths);s["p90_reply_chars"] = sorted(lengths)[int(len(lengths)*.9)];s["topics"] = dict(s["topics"])
    selected = []
    for condition in TOPICS:
        selected.extend(sorted((v for v in candidates.values() if v["condition"] == condition), key=lambda v: -v["training_count"])[:7])
    for i, e in enumerate(selected, 1):
        e["candidate_id"] = i;e["authors"] = list(e["authors"])
    assert not {e["source_client_group"] for e in selected} & held
    report = {"authors": stats, "complete_available_dialogues_examined": len(dialogs), "messages_in_these_dialogues": sum(len(messages[cid]) for cid in dialogs), "blocks_examined": len(turns), "candidate_questions": len(selected), "cutoff_utc": CUTOFF, "frozen_holdout_client_overlap": 0, "automatic_training_admissions": 0, "model_calls": 0, "customer_writes": 0, "method": "Every available full conversation involving either author, then every author reply block. Topic/reask signals are not verified errors or conversion labels. Prices, promises and booking actions cannot override regulation."}
    for name, value in [("summary.json", report), ("question-candidates-private.json", selected), ("turns-index-private.json", turns)]:
        path = OUT / name;path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n");os.chmod(path, 0o600)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    for e in selected:
        print(e["candidate_id"], e["condition"], e["training_count"], repr(e["answer"]))


if __name__ == "__main__":
    main()
