"""Explicitly reviewed neutral wording from the full cohort, never policy."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "test-artifacts/alltime-authors/analysis"
path = ROOT / "leadbot/brain/style_examples.json"
data = json.loads(path.read_text())
rows = json.loads((OUT / "question-candidates-private.json").read_text())
# Reviewed all 86 candidates. These single-fact questions contain no bookings,
# payment instructions, named locations, promises, extra services or prices.
approved = {1, 13, 17, 19, 25, 29, 30, 39, 64, 69, 86}
key = lambda text: re.sub(r"\s+", " ", text.lower()).strip()
existing = {key(e["answer"]) for e in data["examples"]}
held = {r["client_group"] for r in map(json.loads, (ROOT / "test-artifacts/private-candidates/evaluation_unseen_clients.jsonl").open())}
added = []
for row in rows:
    if row["candidate_id"] not in approved or key(row["answer"]) in existing:
        continue
    assert row["source_timestamp"] < "2026-10-01T00:00:00+00:00" and row["source_client_group"] not in held
    assert not re.search(r"\d|https?://|@|₽|руб|запиш|приед|перезвон|оплат", row["answer"], re.I)
    entry = {k: v for k, v in row.items() if k != "candidate_id"}
    entry.update(id="alltime-human-" + hashlib.sha256(row["answer"].encode()).hexdigest()[:16], approval="style_only_individual_review_2026-10-16")
    data["examples"].append(entry);existing.add(key(row["answer"]));added.append(entry["id"])
data["version"] = "2026-10-16.4"
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
summary = json.loads((OUT / "summary.json").read_text())
summary.update(individually_reviewed_candidates=len(rows), approved_candidates=len(approved), new_unique_questions=len(added), approved_style_total=len(data["examples"]))
(OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"new_questions": len(added), "total": len(data["examples"]), "holdout_overlap": 0}))
