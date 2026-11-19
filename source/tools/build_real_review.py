"""Freeze a private, stratified sample from unseen clients before model evaluation."""
import collections
import datetime
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
AUDIT=ROOT.parent/'leadbot-audit'
OUT=ROOT/'test-artifacts/personal';OUT.mkdir(parents=True,exist_ok=True);os.chmod(OUT,0o700)
sys.path.insert(0,str(ROOT/'leadbot/brain'))
from assistant_store import Store
from extension_assistant import Assistant
from contact_cities import city_by_slug
import contact_facts


def ts(value):
    d=datetime.datetime.fromisoformat(value.replace('Z','+00:00'))
    return d.replace(tzinfo=datetime.timezone.utc) if not d.tzinfo else d


def mask(text):
    return re.sub(r'\d','•',re.sub(r'https?://\S+','[ССЫЛКА]',text))[:240]


def main():
    meta={};messages=collections.defaultdict(list);seen=set()
    for name in ('history-private.jsonl','bot-context-private.jsonl'):
        for r in map(json.loads,(AUDIT/name).open()):
            if r.get('kind')=='conversation':meta[hashlib.sha256(r['id'].encode()).hexdigest()]=r
            elif r.get('kind')=='message' and r['id'] not in seen:
                seen.add(r['id'])
                if r.get('sender_type') in ('client','operator','bot') and r.get('direction') in ('in','out'):
                    messages[r['cid']].append(r)
    for rows in messages.values():rows.sort(key=lambda r:(r['ts'],r['id']))
    buckets=collections.defaultdict(list)
    with tempfile.TemporaryDirectory() as temp:
        app=Assistant(Store(str(Path(temp)/'db')))
        for r in map(json.loads,(ROOT/'test-artifacts/private-candidates/evaluation_unseen_clients.jsonl').open()):
            source=meta[r['source_dialog']];title=source.get('account_title') or '';cut=ts(r['timestamp'])
            direction=next((d for label,d in [('МНЧ','mnc'),('КП','kp'),('БТ','bt')] if label in title),'')
            city=city_by_slug(source.get('city'));history=[]
            for m in messages[source['id']]:
                if ts(m['ts'])>=cut:break
                history.append({'id':m['id'],'body':m.get('text') or m.get('transcript') or '', 'voice_transcript':m.get('transcript') or '',
                                'direction':m['direction'],'sender_type':m['sender_type'],'delivery_status':m.get('delivery') or '',
                                'attachments':[{'type':t} for t in m.get('attachment_types',[])]})
            ctx={'convId':'real-review-'+r['id'][:20],'city':city.name if city else source.get('city'),'dir':direction,
                 'partner':source.get('partner'),'accountTitle':title,'itemTitle':source.get('item_title'),'channel':source.get('channel'),
                 'crmRequestId':'existing-at-time' if source.get('crm_at') and ts(source['crm_at'])<cut else '', 'messages':history}
            p,code=app.handle({'owner':'evaluation','action':'preview','ctx':ctx})
            if code!=200:continue
            task=json.loads(p['model_task']['task']) if p.get('pending_model') else {}
            kind=task.get('decision',{}).get('next_question',{}).get('kind')
            category=('model:'+str(kind)) if kind else p.get('action','handoff')+':'+str(p.get('service',{}).get('status'))
            row={'case_id':r['id'][:20],'client_group':r['client_group'],'author':r['author'],'timestamp':r['timestamp'],
                 'category':category,'expected_action':p.get('action'),'expected_question':task.get('decision',{}).get('next_question'),
                 'expected_reply':p.get('reply',''),'reason':p.get('reason',''),'rule_ids':p.get('rule_ids',[]),'ctx':ctx,
                 'human_answer_private':r['answer'],'redacted_history':task.get('history',[])}
            buckets[category].append(row)
    selected=[];groups=set()
    # Broad question types first; common city questions cannot dominate the sample.
    for kind in ['problem','model','tv_type','materials','phone','address','ceiling','room','load','instructions','volume','wall','city']:
        for r in buckets.get('model:'+kind,[]):
            if r['client_group'] in groups:continue
            selected.append(r);groups.add(r['client_group'])
            if sum(x['category']=='model:'+kind for x in selected)>=3:break
    for category in sorted(buckets):
        if category.startswith('model:'):continue
        for r in buckets[category]:
            if r['client_group'] in groups:continue
            selected.append(r);groups.add(r['client_group'])
            if sum(x['category']==category for x in selected)>=3:break
    for i,r in enumerate(selected):r['review_number']=i+1
    path=OUT/'real-cases-private.json';path.write_text(json.dumps({'cases':selected,'selection':'Frozen unseen-client holdout, distinct client groups, chronological cut before human answer; no future CRM link'},ensure_ascii=False,indent=2));os.chmod(path,0o600)
    print(json.dumps({'cases':len(selected),'categories':dict(collections.Counter(r['category'] for r in selected))},ensure_ascii=False))
    for r in selected:
        tail=r['redacted_history'][-2:] if r['redacted_history'] else [{'text':m['body']} for m in r['ctx']['messages'][-2:]]
        print(json.dumps({'n':r['review_number'],'kind':r['category'],'context':[mask(m['text']) for m in tail],
                          'question':r['expected_question'],'reason':r['reason'],'human':mask(r['human_answer_private'])},ensure_ascii=False))


if __name__=='__main__':main()
