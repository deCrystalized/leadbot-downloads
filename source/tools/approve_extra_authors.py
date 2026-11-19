"""Explicit individually reviewed question wording; never a rule/price source."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "leadbot/brain/style_examples.json"
data = json.loads(path.read_text())
rows = json.loads((ROOT / "test-artifacts/extra-authors/question-candidates-private.json").read_text())
# Each phrase was inspected; reject booking promises, incomplete choices,
# irrelevant topic matches, personal names, transcription errors, extra questions.
approved = {1, 3, 6, 15, 16, 22, 23, 24, 26, 28, 29, 32, 33, 56}
existing = {re.sub(r"\s+", " ", e["answer"].lower()).strip() for e in data["examples"]}
held = {r["client_group"] for r in map(json.loads, (ROOT / "test-artifacts/private-candidates/evaluation_unseen_clients.jsonl").open())}
added = []
for r in rows:
    if r["candidate_id"] not in approved:
        continue
    assert r["source_timestamp"] < "2026-10-01T00:00:00+00:00" and r["source_client_group"] not in held
    key = re.sub(r"\s+", " ", r["answer"].lower()).strip()
    if key in existing:
        continue
    assert not re.search(r"\d|https?://|@|₽|руб|запишу|приеду|перезвоню", r["answer"], re.I)
    row = {k: v for k, v in r.items() if k != "candidate_id"}
    row.update(id="extra-human-" + hashlib.sha256(r["answer"].encode()).hexdigest()[:16], approval="style_only_individual_assistant_review_2026-10-16")
    data["examples"].append(row);existing.add(key);added.append(row)
data["version"] = "2026-10-16.3"
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
summary_path = ROOT / "test-artifacts/extra-authors/summary.json"
summary = json.loads(summary_path.read_text());summary.update(individually_reviewed_candidate_questions=len(approved), admitted_new_unique_questions=len(added), approved_style_total=len(data["examples"]))
summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"new_questions": len(added), "total_questions": len(data["examples"]), "holdout_overlap": 0}))
