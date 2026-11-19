"""Local candidate preparation with client grouping and a future-time holdout.

These masked records are NOT approved training examples and are never uploaded.
Only the separately reviewed style_examples.json is used by the running assistant.
"""
import collections
import hashlib
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT.parent / "leadbot-audit"
OUT = ROOT / "test-artifacts/private-candidates"
OUT.mkdir(parents=True, exist_ok=True)
os.chmod(OUT, 0o700)


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def main():
    groups = {}
    for line in (AUDIT / "contacts-private.jsonl").open():
        row = json.loads(line)
        if row.get("kind") != "contact":
            continue
        phone = re.sub(r"\D", "", row.get("phone") or "")
        key = "phone:" + phone[-10:] if len(phone) >= 10 else "client:" + str(row["client_id"])
        groups[row["cid"]] = sha(key)
    reviewed = json.loads((ROOT / "leadbot/brain/style_examples.json").read_text())["examples"]
    approved_dialogs = {row["source_dialog_sha256"] for row in reviewed}
    approved_groups = {group for cid, group in groups.items() if sha(cid) in approved_dialogs}
    cutoff = "2026-10-01T00:00:00+00:00"
    handles = {name: (OUT / (name + ".jsonl")).open("w") for name in ("train_candidates", "evaluation_unseen_clients", "reserved")}
    counts, group_sets = collections.Counter(), collections.defaultdict(set)
    authors = collections.Counter()
    try:
        for line in (AUDIT / "human-turns-redacted.jsonl").open():
            row = json.loads(line)
            group = groups.get(row["cid"], sha("dialog:" + row["cid"]))
            held_client = group not in approved_groups and int(group[:8], 16) % 5 == 0
            recent = row["ts"] >= cutoff
            partition = "evaluation_unseen_clients" if held_client and recent else "train_candidates" if not held_client and not recent else "reserved"
            record = {"id": sha(row["cid"] + row["ts"]), "client_group": group, "source_dialog": sha(row["cid"]),
                      "timestamp": row["ts"], "author": row["author"], "context": row["context"],
                      "client": row["client"], "answer": row["answer"], "labels": row["labels"],
                      "admission": "candidate_requires_rule_and_human_review", "outcome": row["outcome"]}
            handles[partition].write(json.dumps(record, ensure_ascii=False) + "\n")
            counts[partition] += 1
            group_sets[partition].add(group)
            authors[row["author"]] += 1
    finally:
        for handle in handles.values():
            handle.close()
    assert not group_sets["train_candidates"] & group_sets["evaluation_unseen_clients"]
    for path in OUT.glob("*.jsonl"):
        os.chmod(path, 0o600)
    report = {"candidate_turns": sum(counts.values()), "partitions": dict(counts), "authors": dict(authors),
              "time_cutoff_utc": cutoff, "train_eval_client_overlap": 0, "approved_style_examples": len(reviewed),
              "admitted_full_dialogue_training_examples": 0, "uploaded_training_examples": 0,
              "privacy": "Local masked candidates; heuristic masking does not establish full anonymization.",
              "method": "group by normalized contact phone or client id; reserve unseen clients and later dates; approved style source groups excluded from evaluation"}
    (ROOT / "test-artifacts/dataset-summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
