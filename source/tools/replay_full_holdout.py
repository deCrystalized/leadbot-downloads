"""Reconstruct every frozen holdout turn from complete earlier message history."""
import collections,datetime,hashlib,json,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];AUDIT=ROOT.parent/'leadbot-audit';sys.path.insert(0,str(ROOT/'leadbot/brain'))
from assistant_store import Store
from extension_assistant import Assistant
from contact_cities import city_by_slug
from manual_program_guard import assert_development_dialogues
meta={};messages=collections.defaultdict(list);seen=set()
def timestamp(v):
 d=datetime.datetime.fromisoformat(v.replace('Z','+00:00'));return d.replace(tzinfo=datetime.timezone.utc) if not d.tzinfo else d
for filename in ('history-private.jsonl','bot-context-private.jsonl'):
 for row in map(json.loads,(AUDIT/filename).open()):
  if row.get('kind')=='conversation':meta[hashlib.sha256(row['id'].encode()).hexdigest()]=row
  elif row.get('kind')=='message' and row['id'] not in seen:
   seen.add(row['id'])
   if row.get('sender_type') in ('client','operator','bot') and row.get('direction') in ('in','out'):
    messages[row['cid']].append((timestamp(row['ts']),row))
for seq in messages.values():seq.sort(key=lambda pair:(pair[0],pair[1]['id']))
counts=collections.Counter();questions=collections.Counter();lengths=[];blocked=[]
with tempfile.TemporaryDirectory() as temp:
 app=Assistant(Store(str(Path(temp)/'replay.sqlite')))
 rows=[json.loads(l) for l in (ROOT/'test-artifacts/private-candidates/evaluation_unseen_clients.jsonl').read_text().splitlines()]
 assert_development_dialogues(meta[row['source_dialog']]['id'] for row in rows)
 for row in rows:
  source=meta[row['source_dialog']];cut=timestamp(row['timestamp']);title=source.get('account_title') or ''
  direction=next((d for label,d in [('МНЧ','mnc'),('КП','kp'),('БТ','bt')] if label in title),'')
  city=city_by_slug(source.get('city'));history=[]
  for ts,m in messages[source['id']]:
   if ts>=cut:break
   history.append({'id':m['id'],'body':m.get('text') or m.get('transcript') or '', 'voice_transcript':m.get('transcript') or '', 'direction':m['direction'],'sender_type':m['sender_type'],'delivery_status':m.get('delivery') or '','attachments':[{'type':t} for t in (m.get('attachment_types') or [])]})
  lengths.append(len(history));existing=source.get('crm_at') and timestamp(source['crm_at'])<cut
  ctx={'convId':row['id'],'city':city.name if city else source.get('city'),'dir':direction,'partner':source.get('partner'),'accountTitle':title,'itemTitle':source.get('item_title'),'channel':source.get('channel'),'crmRequestId':'existing-at-this-time' if existing else '', 'messages':history}
  prepared,code=app.handle({'owner':'full-offline-holdout','action':'preview','ctx':ctx});assert prepared.get('auto_enabled') is False
  if prepared.get('response_source')=='reviewed_question' and prepared.get('validation'):
   blocked.append({'kind':'reviewed_question','violations':prepared['validation']})
  if prepared.get('pending_model'):
   task=json.loads(prepared['model_task']['task']);d=task['decision'];questions[d['next_question']['kind']]+=1
   out,_=app.handle({'owner':'full-offline-holdout','action':'finalize','request_id':prepared['request_id'],'revision':prepared['revision'],'candidate':{'reply':' '.join(d.get('required_text',[])+[d['next_question']['question']]),'needs_operator':False}})
   if out.get('validation'):blocked.append({'kind':d['next_question']['kind'],'violations':out['validation']})
  counts[prepared.get('action') or prepared.get('code')]+=1
  if code!=200:counts['invalid_or_overlong_context']+=1
report={'frozen_turns':len(rows),'reconstruction':'all earlier client/operator/bot messages; excludes later events and system notices; CRM link only if already existed','max_context_messages':max(lengths),'counts':dict(counts),'question_types':dict(questions),'approved_question_guard_failures':blocked,'model_calls':0,'auto_enabled_cases':0,'quality_claim':False}
(ROOT/'test-artifacts/round2/full-holdout-replay.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False));assert not blocked
