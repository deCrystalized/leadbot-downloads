"""Index all available expert turns causally; freeze new clients for offline checks.

Historical answers are candidates, not policy or automatically approved gold.
No network, model calls, customer sends or CRM writes occur here.
"""
import collections
import hashlib
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "test-artifacts/offline-learning"
AUTHORS = {"Мамонтов Георгий", "Скороход Илья", "Казахбаев Зухратдин", "Востриков Глеб"}
CUTOFF = "2026-10-01T00:00:00+00:00"
TOPICS = {
    "city": r"город|откуда|насел[её]н",
    "phone": r"(?:номер|телефон).{0,30}(?:связ|подскаж|остав|напиш)|(?:подскаж|остав|напиш).{0,30}(?:номер|телефон)",
    "address": r"адрес|куда.{0,20}(?:ехать|подъех)|улиц|подъезд|этаж|квартир",
    "time": r"когда.{0,20}удоб|сегодня.{0,20}удоб|день.{0,20}врем|ко скольк|к какому времени",
    "instructions": r"инструкц|схем",
    "model": r"марк|модел",
    "problem": r"что.{0,20}(?:случи|проблем)|какая.{0,20}проблем",
    "materials": r"материал|комплектующ",
    "volume": r"объ[её]м|количество|сколько.{0,20}(?:метр|шкаф|розет|штук)",
    "price": r"стоим|цен[аыуе]|руб|₽|осмотр|диагност",
    "action_or_visit": r"приеду|подъеду|перезвон|запиш|записал|создал|передал",
}


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def load():
    conversations, messages, contacts = {}, {}, {}
    for path in (ROOT.parent / "leadbot-audit/history-private.jsonl",
                 ROOT.parent / "leadbot-audit/bot-context-private.jsonl",
                 OUT.parent / "alltime-authors/history-private.jsonl",
                 ROOT.parent / "leadbot-audit/contacts-private.jsonl"):
        if not path.exists():
            continue
        for line in path.open():
            row = json.loads(line)
            if row.get("kind") == "conversation":
                conversations[row["id"]] = {**conversations.get(row["id"], {}), **row}
            elif row.get("kind") == "message":
                old = messages.get(row["id"], {})
                messages[row["id"]] = {**old, **row}
            elif row.get("kind") == "contact":
                contacts[row["cid"]] = row
    grouped = collections.defaultdict(list)
    for row in messages.values():
        if row.get("direction") in ("in", "out") and row.get("sender_type") in ("client", "operator", "bot"):
            grouped[row["cid"]].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda r: (r["ts"], r["id"]))
    return conversations, grouped, contacts


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    OUT.chmod(0o700)
    conversations, grouped, contacts = load()
    approved_groups = {r["source_client_group"] for r in json.loads((ROOT / "leadbot/brain/style_examples.json").read_text())["examples"]}
    prior_holdout = {r["client_group"] for r in map(json.loads, (OUT.parent / "private-candidates/evaluation_unseen_clients.jsonl").open())}
    groups = {}
    parent = {}

    def find(key):
        parent.setdefault(key, key)
        if parent[key] != key:
            parent[key] = find(parent[key])
        return parent[key]

    identities = {}
    for cid in grouped:
        c = contacts.get(cid, {})
        phone = re.sub(r"\D", "", c.get("phone") or "")
        keys = [sha("dialog:" + cid)]
        if c.get("client_id"):
            keys.append(sha("client:" + str(c["client_id"])))
        if len(phone) >= 10:
            keys.append(sha("phone:" + phone[-10:]))
        root = min(find(k) for k in keys)
        for k in keys:
            parent[find(k)] = root
        identities[cid] = keys
    excluded_eval = {find(k) for keys in identities.values() for k in keys
                     if k in approved_groups or k in prior_holdout}
    prior_holdout_groups = {find(k) for keys in identities.values() for k in keys if k in prior_holdout}
    earliest = {}
    for cid, rows in grouped.items():
        group = find(identities[cid][0])
        groups[cid] = group
        earliest[group] = min(earliest.get(group, rows[0]["ts"]), rows[0]["ts"])
    frozen_groups = {g for g, first in earliest.items()
                     if first >= CUTOFF and g not in excluded_eval and int(g[:8], 16) % 7 == 0}
    records, phrases = [], {}
    counts, author_messages, author_turns, topic_counts = (collections.Counter() for _ in range(4))
    dates = []
    for cid, rows in grouped.items():
        if not any(r.get("author") in AUTHORS for r in rows):
            continue
        counts["expert_dialogues"] += 1
        counts["messages_in_expert_dialogues"] += len(rows)
        source = conversations.get(cid, {})
        counts["expert_dialogues_with_linked_crm"] += bool(source.get("crm_linked"))
        for row in rows:
            if row.get("author") in AUTHORS and row["direction"] == "out":
                author_messages[row["author"]] += 1
                dates.append(row["ts"])
        for index, row in enumerate(rows):
            if row["direction"] != "out" or row.get("author") not in AUTHORS or not index or rows[index - 1]["direction"] != "in":
                continue
            block = []
            end = index
            while end < len(rows) and rows[end]["direction"] == "out" and rows[end].get("author") == row["author"]:
                block.append(rows[end].get("text") or rows[end].get("transcript") or "")
                end += 1
            target = " ".join(block).strip()
            if not target:
                continue
            tags = [key for key, pattern in TOPICS.items() if re.search(pattern, target, re.I)]
            author_turns[row["author"]] += 1
            topic_counts.update(tags)
            group = groups[cid]
            partition = "frozen_new_clients" if group in frozen_groups else "training_candidates" if row["ts"] < CUTOFF and group not in prior_holdout_groups else "reserved"
            record = {"case_id": sha(cid + row["ts"]), "source_dialog": sha(cid), "client_group": group,
                      "timestamp": row["ts"], "author": row["author"], "cut_message_index": index,
                      "partition": partition, "target_topics": tags, "target": target,
                      "context_message_count": index, "unread_media_before_cut": sum(bool(r.get("attachment_types")) and not r.get("transcript") for r in rows[:index]),
                      "first_operator_reply": not any(r["direction"] == "out" for r in rows[:index]),
                      "admission": "candidate_requires_current_rule_review"}
            records.append(record)
            counts[partition] += 1
            if record["first_operator_reply"]:
                counts["first_replies"] += 1
                counts["first_replies_with_greeting"] += bool(re.search(r"здравств|добрый (?:день|вечер)|доброе утро", target, re.I))
            if partition != "training_candidates" or not 20 <= len(target) <= 220 or "price" not in tags:
                continue
            if re.search(r"\d|https?://|@|₽|руб|бесплат|приед|подъед|перезвон|запиш|создал|передал|точно|гаранти", target, re.I):
                continue
            if not re.search(r"завис|объ[её]м|сложност|после осмотр", target, re.I):
                continue
            key = re.sub(r"\s+", " ", target.lower()).strip()
            entry = phrases.setdefault(key, {"text": target, "count": 0, "authors": collections.Counter(), "source_case": record["case_id"], "source_client_group": group, "source_timestamp": row["ts"]})
            entry["count"] += 1
            entry["authors"][row["author"]] += 1
    train_groups = {r["client_group"] for r in records if r["partition"] == "training_candidates"}
    eval_groups = {r["client_group"] for r in records if r["partition"] == "frozen_new_clients"}
    assert not train_groups & eval_groups
    path = OUT / "expert-turns-private.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    path.chmod(0o600)
    candidates = sorted(phrases.values(), key=lambda r: -r["count"])[:40]
    for n, r in enumerate(candidates):
        r["candidate_id"] = n + 1
        r["authors"] = dict(r["authors"])
    path = OUT / "price-wording-candidates-private.json"
    path.write_text(json.dumps(candidates, ensure_ascii=False, indent=2) + "\n")
    path.chmod(0o600)
    summary = {"counts": dict(counts), "author_messages": dict(author_messages), "author_turns": dict(author_turns),
               "first_expert_message_utc": min(dates), "last_expert_message_utc": max(dates), "topic_counts": dict(topic_counts),
               "frozen_new_client_groups": len(eval_groups), "train_eval_group_overlap": 0,
               "price_wording_candidates_for_review": len(candidates), "external_writes": 0, "model_calls": 0,
               "method": "Merged available exports of four named experts, not the entire platform; context strictly before the expert response; future outcome is never supplied as an input. Human answers are candidates, not current regulatory truth."}
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
