"""Refresh primary paragraphs while preserving stable historical reference IDs."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "leadbot/brain/policy_registry.json"
registry = json.loads(path.read_text())
fresh = ROOT / "test-artifacts/auto-release/general-primary-2026-10-16.txt"
normalize = lambda s: re.sub(r"\s+", " ", s.replace("\ufeff", "")).strip().casefold()
lines = fresh.read_text().splitlines();lookup = {}
for number, text in enumerate(lines, 1):
    lookup.setdefault(normalize(text), []).append(number)
matched = set();withdrawn = []
for source in registry["sources"]:
    if source.get("type") != "document":
        continue
    current = lookup.get(normalize(source["text"]), [])
    source.setdefault("original_line", source.get("line"))
    source["active_primary"] = bool(current);source["verified_at"] = "2026-10-16"
    if current:
        number = min(current, key=lambda n: abs(n-(source.get("original_line") or n)))
        source["line"] = number;matched.add(normalize(source["text"]))
    else:
        source["withdrawn_at"] = "2026-10-16";withdrawn.append(source["id"])
added = []
for number, text in enumerate(lines, 1):
    key = normalize(text)
    if not key or set(key) == {"_"} or key in matched:
        continue
    source = {"id": f"DOC26-L{number:04d}", "type": "document", "line": number, "text": text, "topics": [], "date": None, "active_primary": True, "verified_at": "2026-10-16"}
    registry["sources"].append(source);matched.add(key);added.append(source["id"])
registry["previous_document_sha256"] = registry["document_sha256"]
registry["document_sha256"] = hashlib.sha256(fresh.read_bytes()).hexdigest()
registry["document_url"] = "https://docs.google.com/document/d/1VJuB4kz8eqtXs0JjGgSeFt0pwD_Wqq6J84j8B1sAQtw/edit"
registry["version"] = "2026-10-16.9";registry["primary_verified_at"] = "2026-10-16"
registry["sources"].append(json.loads((ROOT / "leadbot/brain/reviewed_catalog.json").read_text())["owner_amendments"][-1])
path.write_text(json.dumps(registry, ensure_ascii=False, indent=2)+"\n")
summary = {"verified_at": "2026-10-16", "general_changed": True, "kp_changed": False, "stable_reference_ids_preserved": True, "withdrawn_primary_ids": withdrawn, "new_primary_ids": added, "current_document_sha256": registry["document_sha256"]}
(ROOT / "test-artifacts/auto-release/primary-refresh.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n")
print(json.dumps({"withdrawn": len(withdrawn), "new_paragraphs": len(added), "stable_ids_preserved": True}))
