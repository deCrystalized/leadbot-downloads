"""Pure offline post-view reasoning; never creates a live media review or permit.

Images are manually adjudicated development fixtures with exact file hashes.
The parser boundary is projected only in this process, into a temporary Store.
No later dialogue text, CRM card, target reply or final validation cohort enters.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from manual_program_guard import assert_development_dialogues, assert_development_phones

ROOT=Path(__file__).resolve().parents[1]
BATCH=ROOT/'test-artifacts/human-practice/manual-batch221-260'
parser=argparse.ArgumentParser()
parser.add_argument('--tag',choices=('before32','after'),required=True)
parser.add_argument('--policy-dir')
parser.add_argument('--extra-controls',action='store_true')
args=parser.parse_args()
sys.path.insert(0,str(ROOT/'leadbot/brain'))
if args.policy_dir:
    frozen=(ROOT/args.policy_dir).resolve()
    assert frozen.is_relative_to(ROOT/'test-artifacts') and frozen.is_dir()
    sys.path.insert(0,str(frozen))
import extension_assistant
import contact_phone
from assistant_store import Store,digest
from contact_cities import city_by_slug

rows=json.loads((BATCH/'sources-private.json').read_text())
labels_path=BATCH/'parallel-review/review-b/closure-analysis-private.json'
labels=json.loads(labels_path.read_text())['masked_checkpoints']
adjudication_path=BATCH/'postmedia-root-adjudication.json'
adjudication=json.loads(adjudication_path.read_text())
assert adjudication['original_labels_modified'] is False
assert adjudication['id']=='B-M05' and adjudication['case']==254 and adjudication['cut']==19
assert len(labels)==9
if args.extra_controls:
    labels += json.loads((BATCH/'postmedia-extra-human-controls.json').read_text())['controls']
assert_development_dialogues(r['cid'] for r in rows)
assert_development_phones(p.value for r in rows for m in r['messages'] if m['direction']=='in' for p in contact_phone.find_all(m.get('text') or m.get('transcript') or ''))
images=json.loads((BATCH/'image-files-private.json').read_text())
manifest={r['message_id']:r for r in images}
for row in images:
    assert row['viewed'] is True and row['live_media_approval'] is False
    assert hashlib.sha256(Path(row['path']).read_bytes()).hexdigest()==row['sha256']
os.environ['LEADBOT_ASSISTANT_WORDING']='reviewed'
results=[]
with tempfile.TemporaryDirectory() as temp:
    app=extension_assistant.Assistant(Store(temp+'/offline.sqlite'))
    for label in labels:
        row=next(r for r in rows if r['number']==label['case'])
        source=row['source'];history=row['messages'][:label['cut']]
        assert history[-1]['id']==label['last_message_id']
        city=city_by_slug(source['city']);title=source['account_title']
        ctx=dict(convId='offline-visual-'+label['id'],city=city.name if city else source['city'],
                 dir=next((d for k,d in [('МНЧ','mnc'),('КП','kp'),('БТ','bt')] if k in title),''),
                 partner=source['partner'],channel=source['channel'],accountTitle=title,
                 itemTitle=source['item_title'],origin=source['origin'],
                 messages=[dict(id=m['id'],direction=m['direction'],sender_type=m.get('sender_type'),body=m.get('text') or m.get('transcript') or '',created_at=m['ts'],attachments=m.get('attachments') or [],voice_transcript=m.get('transcript') or '') for m in history])
        chat,messages,known,_=extension_assistant._parse(ctx)
        projected=[]
        for m in messages:
            image=manifest.get(m['id'])
            if image and m.get('reviewable_image'):
                observation={'content_kind':'product_photo'}
                if label['case']==247:observation=dict(model='Xiaomi PMDYJ02HT',content_kind='product_card')
                elif label['case']==254:observation={'content_kind':'product_card'}
                elif label['case']==224 and image['message_index']==8:observation=dict(model='ECOSYS M2535dn',content_kind='device_label')
                elif label['case'] in (225,236):observation={'content_kind':'product_card' if image['message_index']!=5 or label['case']!=236 else 'other'}
                m.update(unread_media=False,media_reviewed=True,offline_fixture=True,
                         media_observation=dict(observation,source='offline_reviewed_image',message_id=m['id'],signature=m['media_signature']))
                projected.append(dict(message_id=m['id'],sha256=image['sha256'],observations=observation))
        revision=digest([messages,known,extension_assistant.policy.VERSION,'offline-view-projection'])
        with patch.object(extension_assistant,'_parse',return_value=(chat,messages,known,revision)):
            out,code=app.handle(dict(owner='offline-reasoning-only',action='preview',ctx=ctx))
        assert code==200 and out['auto_enabled'] is False and not out.get('pending_model') and not out.get('validation')
        errors=[]
        wanted=label['manual_expected_action']
        if label['id']==adjudication['id']:
            wanted=adjudication['expected_action']
        if wanted.startswith('handoff') and out['action']!='handoff':errors.append('expected operator review')
        if wanted.startswith('question') or wanted=='information_then_location_question':
            if out['action']!='question':errors.append('expected a qualified question')
        reply=out.get('reply','');reason=out.get('reason','')
        if label['id']=='B-M01':
            if out['facts'].get('budget_limit',{}).get('amount')!=1500:errors.append('budget ceiling omitted')
            if out['facts']['address'].get('office'):errors.append('apartment invented')
        if label['id']=='B-M02':
            if re.search('марк|модел|что.{0,15}случил|какая.{0,15}проблем|в.{0,10}ч[её]м.{0,10}проблем',reply,re.I):errors.append('known model or stated printer symptom asked again')
            if out.get('qualification',{}).get('model',{}).get('status')!='answered':errors.append('visible model not retained')
            if not any(x.get('model')=='Xiaomi PMDYJ02HT' for x in out['facts'].get('image_observations',[])):errors.append('reviewed model evidence missing')
        if label['id']=='B-M03':
            if not re.search('выез|выезд',reply,re.I):errors.append('onsite service FAQ unanswered')
            if not re.search('город|адрес|Екатеринбург',reply,re.I):errors.append('actual onsite location not clarified')
        if label['id']=='B-M05':
            if not re.search('стоимост.*этап',reason,re.I):errors.append('primary-source price-stage adjudication missed')
            if out['facts']['conflicts']:errors.append('false address conflict')
            if re.search('какие.{0,10}стен|сколько.{0,12}шкаф',reply,re.I):errors.append('clear scope asked again')
        if label['id'] in ('B-M06','B-M07') and not re.search('договор|существующ|отмен',reason,re.I):errors.append('existing appointment missed')
        if label['id']=='B-M08' and not re.search('номер|телефон',reply,re.I):errors.append('missing contact for prior-call check not requested')
        if label['id']=='B-M09' and re.search('номер|телефон',reply,re.I):errors.append('known contact asked again')
        if label['id']=='B-M09' and not re.search('предыдущ.*(?:разговор|договор)',reason,re.I):errors.append('prior conversation lookup missed')
        if label['id'] in ('R-A03','R-A05'):
            if re.search(r'\d+\s*(?:руб|р\b|₽)',reply,re.I):errors.append('premature numerical price on stage2')
            if not re.search('стоимост|цен|бесплатн',reply,re.I):errors.append('current price objection unanswered')
        if label['id'] in ('R-A04','R-A06','R-A07') and not re.search('стоимост|цен|бюджет',reason,re.I):errors.append('unresolved price agreement missed')
        if label['id']=='R-A02' and re.search('20079|13738',reply):errors.append('retail furniture price used as labour tariff')
        if label['id']=='R-A01' and not re.search('доступ|пустят|вход',reason,re.I):errors.append('explicit onsite access restriction missed')
        if re.search('мастерск|ремонт точно|гарантир|к 18 буду',reply,re.I):errors.append('unverified promise')
        results.append(dict(id=label['id'],case=label['case'],cut=label['cut'],prefix_sha256=digest(ctx),
                            original_expected_action=label['manual_expected_action'],adjudicated_expected_action=wanted,
                            source_labels_sha256=hashlib.sha256(labels_path.read_bytes()).hexdigest(),
                            image_projections=projected,action=out['action'],reason=reason,reply=reply,
                            facts=out.get('facts'),qualification=out.get('qualification'),passed=not errors,errors=errors))
report=dict(policy=extension_assistant.policy.VERSION,cases=len(results),passed=sum(r['passed'] for r in results),
            grader_version=2,primary_adjudication_sha256=hashlib.sha256(adjudication_path.read_bytes()).hexdigest(),
            results=results,offline_projection_only=True,live_media_reviews_created=0,
            live_permits_created=0,network_calls=0,model_calls=0,crm_writes=0,customer_sends=0,
            limits=['This tests reasoning after human visual comprehension, not autonomous vision accuracy.','No production media approval or live session was created.','Current CRM cards and later dialogue messages are excluded.'])
(BATCH/('postmedia-'+('v3' if args.extra_controls else 'v2')+'-'+args.tag+'-private.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(dict(policy=report['policy'],cases=report['cases'],passed=report['passed'],
                     failures=[dict(id=r['id'],action=r['action'],reason=r['reason'],reply=r['reply'],errors=r['errors']) for r in results if not r['passed']],
                     live_grants=0,model_calls=0),ensure_ascii=False))
