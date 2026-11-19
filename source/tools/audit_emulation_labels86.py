"""Explain old-label drift using existing hash-bound adjudications, without relabelling.

This is not independent accuracy: prior adjudications may have seen a proposal.
Media annotations/facts are deliberately not projected into the causal raw run.
"""
import hashlib
import json
import argparse
from collections import Counter, defaultdict
from pathlib import Path
from simulate_manual_thousand86 import ROOT, check_expectation, load_programme


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', choices=('corrected', 'final', 'release87-replay', 'final88', 'final89'), default='final89')
    args = parser.parse_args()
    rows, labels, sources = load_programme()  # sealed-cohort guard before source bodies
    directory = ROOT / 'test-artifacts/current-pilot/thousand86' / args.run
    differences = json.loads((directory / 'label-differences-private.json').read_text())
    candidates = defaultdict(list)
    skipped = []
    for source in sources:
        ledger = ROOT / source['path']
        if ledger.name != 'manual-review-private.json':
            continue
        for path in sorted(ledger.parent.glob('*adjudicat*.json')):
            adjudication = json.loads(path.read_text())
            if not isinstance(adjudication, dict) or adjudication.get('original_ledger_sha256') != hashlib.sha256(ledger.read_bytes()).hexdigest():
                skipped.append(str(path.relative_to(ROOT)))
                continue
            for resolution in adjudication.get('resolutions', []):
                if not (resolution.get('reviewed') is True and resolution.get('primary_rule_ids') and resolution.get('reason')):
                    continue
                key = resolution['case'], resolution['cut']
                original = next((r for r in labels[key[0]] if r.get('cut') == key[1]), None)
                if not original or original['expected_action'] != resolution['original_expected_action']:
                    skipped.append(dict(path=str(path.relative_to(ROOT)), case=key[0], cut=key[1], reason='target_not_bound_to_original_action'))
                    continue
                candidates[key].append(dict(path=str(path.relative_to(ROOT)), resolution=resolution))
    results = []
    for difference in differences:
        key = difference['case'], difference['cut']
        original = next(r for r in labels[key[0]] if r.get('cut') == key[1])
        options = candidates[key]
        expectations = {json.dumps(r['resolution']['resolved_expectation'], sort_keys=True) for r in options}
        if not options:
            classification = 'no_applicable_adjudication'
        elif len(expectations) != 1:
            classification = 'conflicting_adjudications_require_review'
        else:
            expected = dict(original, **options[0]['resolution']['resolved_expectation'])
            remaining = check_expectation(dict(action=difference['actual'], reply=difference['reply'], reason=difference['reason']), expected)
            classification = 'matches_existing_adjudication' if not remaining else 'still_differs_after_existing_adjudication'
        results.append(dict(**difference, adjudication_status=classification, prior_adjudications=options))
    counts = dict(Counter(r['adjudication_status'] for r in results))
    report = dict(original_differences=len(differences), adjudication_counts=counts,
                  skipped_unbound_files=skipped, source_labels_changed=False,
                  accuracy_claim=False, media_projection_applied=False, final_holdout_opened=False)
    private = directory / 'adjudication-audit-private.json'
    private.write_text(json.dumps(results, ensure_ascii=False, indent=2)+'\n')
    private.chmod(0o600)
    (directory / 'adjudication-audit-summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
