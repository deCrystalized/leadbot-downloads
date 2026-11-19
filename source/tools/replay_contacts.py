"""Local-only replay. Emits counts; never emits customer contact data."""
import collections
import importlib.util
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'leadbot/brain'))
import prefilter
BASE=ROOT.parent/'leadbot-audit'
gaps={r['message_id'] for r in map(json.loads,(BASE/'contact-review-private.jsonl').read_text().splitlines()) if r.get('kind')=='bot_phone_gap'}
counts=collections.Counter(); found=set(); seen=set()
for file in ('history-private.jsonl','bot-context-private.jsonl'):
 for line in (BASE/file).open():
  row=json.loads(line)
  if row.get('kind')!='message' or row.get('direction')!='in' or row.get('sender_type')!='client':continue
  if row['id'] in seen:continue
  seen.add(row['id']);counts['client_messages']+=1
  if (row.get('text') or '').strip():counts['nonempty_client_text_messages']+=1
  phones=prefilter.phones_found(row.get('text') or '')
  if phones:counts['recognized_phone_messages']+=1
  if row['id'] in gaps and phones:found.add(row['id'])
summary=dict(counts,previous_gap_cases=len(gaps),previous_gaps_now_recognized=len(found),unresolved_previous_gaps=len(gaps-found))
(ROOT/'test-artifacts/contact-replay-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary))
assert found==gaps
