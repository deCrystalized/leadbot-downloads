"""Lossless active-source dictionary for local storage/retrieval, not a summary.

Every text, number, exception and metadata field round-trips exactly. The raw
registry is never edited. Prompt selection and model-quality tests are separate.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def sha(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def canonical_sources(sources):
    by_id = {}
    for row in sources:
        if row.get('active_primary') is False:
            continue
        key = row['id']
        if not isinstance(key,str) or not key or not isinstance(row.get('text'),str):
            raise ValueError('A primary identity and full text are required')
        if key in by_id and by_id[key] != row:
            raise ValueError('Conflicting primary identity')
        by_id[key] = row
    return [by_id[k] for k in sorted(by_id)]


def compact(rows,policy_version):
    columns = {}
    for field in sorted({k for r in rows for k in r}):
        values, positions, refs, dictionary = [], [], [], {}
        for i,row in enumerate(rows):
            if field not in row:
                continue
            value = row[field]
            key = encoded(value)
            if key not in dictionary:
                dictionary[key] = len(values)
                values.append(value)
            positions.append(i);refs.append(dictionary[key])
        column = dict(values=values,refs=refs)
        if len(positions) != len(rows):
            column['positions'] = positions
        columns[field] = column
    return dict(schema='lossless_policy_columns_v1',policy_version=policy_version,
                count=len(rows),canonical_sha256=sha(rows),columns=columns,
                authority='Exact active source records; compression is not model understanding')


def expand(document,*,expected_sha256):
    if document.get('schema') != 'lossless_policy_columns_v1' or document.get('canonical_sha256') != expected_sha256:
        raise ValueError('Unexpected source snapshot identity')
    count = document.get('count')
    if type(count)is not int or not 0 <= count <= 100000:
        raise ValueError('Invalid source count')
    rows = [{} for _ in range(count)]
    for field,column in document['columns'].items():
        values,refs = column['values'],column['refs']
        positions = column.get('positions',list(range(count)))
        if len(positions) != len(refs) or len(set(positions)) != len(positions):
            raise ValueError('Invalid source positions')
        for pos,ref in zip(positions,refs):
            if type(pos)is not int or not 0 <= pos < count or type(ref)is not int or not 0 <= ref < len(values):
                raise ValueError('Invalid source dictionary reference')
            rows[pos][field] = values[ref]
    if sha(rows) != expected_sha256:
        raise ValueError('Source reconstruction failed')
    return rows


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--proof',type=Path,required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root/'leadbot/brain'))
    import assistant_policy,assistant_catalog
    registry=assistant_policy.registry()
    original=registry['sources']+assistant_catalog.data()['owner_amendments']
    rows=canonical_sources(original)
    document=compact(rows,registry['version'])
    restored=expand(document,expected_sha256=sha(rows))
    assert restored==rows and len({r['id']for r in restored})==len(rows)
    assert not args.output.exists() and not args.proof.exists()
    args.output.write_text(encoded(document)+'\n')
    pretty=json.dumps(rows,ensure_ascii=False,indent=2)
    minimal=encoded(rows)
    compressed=encoded(document)
    proof=dict(policy=registry['version'],all_current_sources=len(rows),original_entries=len(original),
        inactive_excluded=sum(r.get('active_primary')is False for r in original),
        exact_duplicate_entries_coalesced=sum(r.get('active_primary')is not False for r in original)-len(rows),
        all_fields_and_texts_roundtrip_exactly=True,canonical_sha256=sha(rows),
        pretty_characters=len(pretty),minimal_characters=len(minimal),compact_characters=len(compressed),
        compact_vs_minimal_character_saving_percent=round((1-len(compressed)/len(minimal))*100,2),
        tokens_measured=False,API_cost_saving_measured=False,registry_modified=False,
        source_registry_sha256=hashlib.sha256((root/'leadbot/brain/policy_registry.json').read_bytes()).hexdigest())
    args.proof.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(proof,ensure_ascii=False))
