"""Pure reviewed-roster validation; the legacy raw-file builder is retired.

It previously opened mixed batch bodies before complete identity admission.
The pinned audit-source253-v3/project/tools snapshot preserves its original source.
Current approved publications remain readable through ApprovedSources; new
raw histories use the authenticated header-first reader and guarded DailyIndex.
Historical staff speech is not automatically approved policy or training gold.
"""


def reviewed_roster(identity, ledger):
    """Verified legacy identities plus closed canonical rows, never a range."""
    base = identity['base500_registry']
    if len(base) != 500 or len({row['cid'] for row in base}) != 500:
        raise ValueError('The verified old roster is required')
    roster = {row['cid']: dict(case=row['case'], cid=row['cid']) for row in base}
    seen = set()
    for row in ledger:
        cid = row['cid']
        if cid in seen:
            raise ValueError('Duplicate canonical employee closure')
        seen.add(cid)
        primary = row.get('primary_rules_reviewed')
        reviewed_primary = primary is True or (isinstance(primary, list) and bool(primary)
            and all((isinstance(ref, str) and bool(ref)) or (isinstance(ref, dict)
                and isinstance(ref.get('id'), str) and bool(ref['id'])
                and isinstance(ref.get('text'), str) and bool(ref['text'])) for ref in primary))
        if not all(row.get(key) is True for key in ('historical_review_closed', 'full_text_read')) or not reviewed_primary:
            raise ValueError('Unclosed history cannot enter the reviewed archive')
        if cid in roster:
            if roster[cid]['case'] != row['case']:
                raise ValueError('Review identity conflict')
            continue
        roster[cid] = dict(case=row['case'], cid=cid)
    return sorted(roster.values(), key=lambda row: (row['case'], row['cid']))



def build(output):
    raise RuntimeError('Unscoped raw-file archive builder retired; use admitted guarded source publication')


def main():
    raise RuntimeError('Unscoped raw-file archive builder retired; use admitted guarded source publication')


if __name__ == '__main__':
    main()
