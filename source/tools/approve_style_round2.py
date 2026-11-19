"""Admit only individually inspected question examples; no prices or promises."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
rows=json.loads((ROOT/'test-artifacts/round2/style-candidates-private.json').read_text())
approved={1,2,3,5,6,8,9,14,16,20,21,22,23,24,25,26,27,29,42,43,44,48,49,50,51,53,54,56,59,61,62,63,64,65,69,71,72,73,74,75,76,77,78,79,80,81,82,83,84,85,86,96,97,98,99,100,101,102,103,104,106,112,114,120,121,122,123,126,128,132,133,135,136,137,138,139}
# Freeze the existing unseen-client partition; admit source text only before cutoff.
import collections
AUDIT=ROOT.parent/'leadbot-audit'
eval_groups={r['client_group'] for r in map(json.loads,(ROOT/'test-artifacts/private-candidates/evaluation_unseen_clients.jsonl').open())}
groups={}
for r in map(json.loads,(AUDIT/'contacts-private.jsonl').open()):
 if r.get('kind')!='contact':continue
 phone=re.sub(r'\D','',r.get('phone') or '')
 key='phone:'+phone[-10:] if len(phone)>=10 else 'client:'+str(r['client_id'])
 groups[r['cid']]=hashlib.sha256(key.encode()).hexdigest()
allowed={r['answer']:r for r in rows if r['candidate_id'] in approved}
eligible={}
for r in map(json.loads,(AUDIT/'human-turns-redacted.jsonl').open()):
 if r['answer'].strip() not in allowed or r['ts']>='2026-10-01T00:00:00+00:00' or groups.get(r['cid']) in eval_groups:continue
 key=r['answer'].strip();e=eligible.setdefault(key,dict(source=r,count=0,authors=collections.Counter()))
 e['count']+=1;e['authors'][r['author']]+=1
 if r['ts']<e['source']['ts']:e['source']=r
examples=[]
for r in rows:
 if r['candidate_id'] not in approved or r['answer'] not in eligible:continue
 admitted=eligible[r['answer']];source=admitted['source']
 answer=r['answer'];condition='toilet_type' if r['candidate_id'] in (132,133,135) else 'plumbing_ready' if r['candidate_id'] in (42,43,44) else r['condition']
 assert not re.search(r'\d|https?://|@|₽|руб|запишу|приеду|перезвоню',answer,re.I)
 examples.append({'id':'round2-human-'+hashlib.sha256(answer.encode()).hexdigest()[:16],'condition':condition,'answer':answer,'authors':list(admitted['authors']),'source_dialog_sha256':hashlib.sha256(source['cid'].encode()).hexdigest(),'source_client_group':groups[source['cid']],'source_timestamp':source['ts'],'training_count':admitted['count'],'approval':'style_only_individual_review_2026-10-15_round2'})
(ROOT/'leadbot/brain/style_examples.json').write_text(json.dumps({'version':'2026-10-15.2','examples':examples,'admission':'Only reviewed wording; regulation and outcomes are not inferred from operator behavior.'},ensure_ascii=False,indent=2)+'\n')
assert not {e['source_client_group'] for e in examples}&eval_groups
print('Individually reviewed question examples:',len(examples),'frozen evaluation client overlap: 0')
