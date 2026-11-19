"""Unpaid local contract replay, NOT a human-quality or conversion benchmark."""
import collections
import hashlib
import json
import sys
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'leadbot/brain'))
from contact_cities import city_by_slug
from assistant_store import Store
from extension_assistant import Assistant
meta={}
for file in ('history-private.jsonl','bot-context-private.jsonl'):
 for line in (ROOT.parent/'leadbot-audit'/file).open():
  row=json.loads(line)
  if row.get('kind')=='conversation':meta[hashlib.sha256(row['id'].encode()).hexdigest()]=row
counts=collections.Counter();reasons=collections.Counter();questions=collections.Counter()
with tempfile.TemporaryDirectory() as temp:
 app=Assistant(Store(str(Path(temp)/'replay.sqlite3')))
 for line in (ROOT/'test-artifacts/private-candidates/evaluation_unseen_clients.jsonl').open():
  row=json.loads(line);source=meta.get(row['source_dialog'],{})
  title=source.get('account_title') or '';direction=next((d for label,d in [('МНЧ','mnc'),('КП','kp'),('БТ','bt')] if label in title),'')
  msgs=[{'id':str(i),'direction':'in' if m.get('role') in ('client','user') else 'out','body':m.get('text') or ''} for i,m in enumerate(row['context'])]
  if not msgs or msgs[-1]['body']!=row['client']:msgs.append({'id':'last','direction':'in','body':row['client']})
  city=city_by_slug(source.get('city'))
  city_name=city.name if city else source.get('city')
  ctx={'convId':row['id'],'city':city_name,'dir':direction,'partner':source.get('partner'),'channel':source.get('channel'),'accountTitle':title,'itemTitle':source.get('item_title'),'messages':msgs}
  prepared,code=app.handle({'action':'preview','owner':'local-offline-evaluation','ctx':ctx})
  assert prepared.get('auto_enabled') is False
  assert not prepared.get('lead',{}).get('can_create_automatically',False)
  if prepared.get('pending_model'):
   task=json.loads(prepared['model_task']['task']);decision=task['decision'];questions[decision['next_question']['kind']]+=1
   candidate={'reply':' '.join(decision.get('required_text',[])+[decision['next_question']['question']]),'needs_operator':False}
   out,_=app.handle({'action':'finalize','owner':'local-offline-evaluation','request_id':prepared['request_id'],'revision':prepared['revision'],'candidate':candidate})
   assert not out.get('validation'),(decision['next_question']['kind'],out.get('validation'))
   counts['model_tasks_replayed_with_approved_question']+=1
  counts[prepared.get('action') or prepared.get('code')]+=1
  if code!=200:counts['bad_context']+=1
  reasons[prepared.get('reason') or prepared.get('error')]+=1
report={'heldout_turns':sum(1 for _ in (ROOT/'test-artifacts/private-candidates/evaluation_unseen_clients.jsonl').open()),'counts':dict(counts),'questions':dict(questions),'auto_enabled_cases':0,'model_calls':0,'interpretation':'Contract/fail-closed coverage only; no learned model quality or conversion claim.'}
(ROOT/'test-artifacts/heldout-replay-summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False))
