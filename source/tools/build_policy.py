"""Build a versioned primary-source knowledge registry, retaining review gaps."""
import difflib
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT.parent / "leadbot-audit"
CURRENT = AUDIT / "regulation/current-google-doc.txt"
INDEX = json.loads((ROOT.parents[1] / "outputs/LeadBot-regulation-index.json").read_text())


def norm(text):
    return re.sub(r"\s+", " ", text.replace("\ufeff", "")).strip().lower()


def build():
    lines = CURRENT.read_text().splitlines()
    old_file = ROOT / "leadbot/analysis/РЕГЛАМЕНТ-ПОЛНЫЙ-2026.txt"
    old_lines = old_file.read_text().splitlines()
    mapping = {}
    for block in difflib.SequenceMatcher(None, list(map(norm, old_lines)), list(map(norm, lines)), autojunk=False).get_matching_blocks():
        for offset in range(block.size):
            mapping[block.a + offset + 1] = block.b + offset + 1
    sources = []
    for paragraph in INDEX["document"]["paragraphs"]:
        line = paragraph["line"]
        sources.append({"id": paragraph["id"], "type": "document", "line": line,
                        "text": lines[line - 1], "topics": paragraph["topics"], "date": None})
    kp_doc = AUDIT / "regulation/current-kp-doc.txt"
    kp_lines = kp_doc.read_text().splitlines()
    for index, line in enumerate(kp_lines, 1):
        if line.strip() and set(line.strip()) != {"_"}:
            sources.append({"id": f"KP-L{index:04d}", "type": "kp_document", "line": index,
                            "text": line, "scope": "kp", "date": None})
    business_ids = {p["id"] for p in INDEX["telegram_posts"] if p["scope"] == "business_rule_candidate"}
    for source in (1, 2):
        archive = json.loads((AUDIT / f"regulation/telegram-{source}.json").read_text())
        for message in archive["messages"]:
            sid = f'TG{source}-{message["id"]}'
            if sid not in business_ids:
                continue
            text = message.get("text", "")
            text = text if isinstance(text, str) else "".join(x if isinstance(x, str) else x.get("text", "") for x in text)
            text = re.sub(r'После (?:ознакомления|прочтения).*$', '', text, flags=re.I | re.S).strip()
            sources.append({"id": sid, "type": "telegram", "date": message["date"], "text": text,
                            "media_missing": bool(message.get("photo") or message.get("file"))})
    # Preserve every old matrix item, but do not turn author interpretations into permissions.
    matrix = (ROOT / "leadbot/analysis/МАТРИЦА-ПРИЁМА-2026.md").read_text()
    entries = []
    matches = list(re.finditer(r'^(✅|🔶|⛔→🔶|❓|•) \*\*(.+?)\*\*', matrix, re.M))
    for index, match in enumerate(matches):
        block = matrix[match.start():matches[index + 1].start() if index + 1 < len(matches) else len(matrix)]
        marker = re.search(r'_Источник:\s*(?:ПОЛНЫЙ[^_:;]*?(?:стр\.\s*|:))([^_;]+)', block)
        refs = []
        if marker:
            for token in re.finditer(r'(\d+)(?:\s*[-–]\s*(\d+))?', marker.group(1)):
                start, stop = int(token[1]), int(token[2] or token[1])
                if 0 < start <= stop <= len(old_lines):
                    refs.extend(range(start, stop + 1))
        aligned = [f'DOC-L{mapping[x]:04d}' for x in dict.fromkeys(refs) if x in mapping and norm(old_lines[x-1])]
        disputed = bool(re.search(r'решени[юея].{0,30}02\.08|противореч|интерпретац|двусмыс|открыт.{0,15}вопрос', block, re.I))
        entries.append({"id": f'MATRIX-{index+1:03d}', "title": match[2], "legacy_status": match[1],
                        "primary_refs": aligned, "source_alignment": "matched" if aligned else "unresolved",
                        "requires_semantic_review": disputed or not aligned,
                        "permission_source": False})
    manifest = {"schema": "leadbot.policy.v1", "version": "2026-10-15.7",
                "document_sha256": hashlib.sha256(CURRENT.read_bytes()).hexdigest(),
                "kp_document_sha256": hashlib.sha256(kp_doc.read_bytes()).hexdigest(),
                "kp_document_url": "https://docs.google.com/document/d/1hAOnFGyISfYVGjtZCw0Aq_IfEmZmZYAZ1P5NZUrVG5Y/edit",
                "sources": sources, "amendments": INDEX["curated_amendments"], "matrix_review": entries,
                "automatic_delivery_enabled": False,
                "limitations": INDEX["limitations"]}
    reviewed_path=ROOT/"leadbot/brain/reviewed_catalog.json"
    if reviewed_path.exists():
        reviewed=json.loads(reviewed_path.read_text())
        source_ids={s["id"] for s in sources}
        manifest["sources"] += [s for s in reviewed["owner_amendments"] if s["id"] not in source_ids]
        by_id={r["id"]:r for r in reviewed["matrix_review"]}
        for entry in entries:
            resolution=by_id[entry["id"]]
            entry["original_requires_semantic_review"]=entry["requires_semantic_review"]
            entry["reviewed_status"]=resolution["status"]
            entry["reviewed_primary_refs"]=resolution["primary_refs"]
            entry["resolution"]=resolution["resolution"]
            entry["requires_semantic_review"]=resolution["status"] in ("conflict","operational_unknown","needs_source_review")
    dest = ROOT / "leadbot/brain/policy_registry.json"
    dest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps({"sources": len(sources), "matrix_items": len(entries),
                      "with_primary_alignment": sum(bool(e["primary_refs"]) for e in entries),
                      "requires_semantic_review": sum(e["requires_semantic_review"] for e in entries)}, ensure_ascii=False))


if __name__ == "__main__":
    build()
