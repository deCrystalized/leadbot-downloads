"""Source-bound human visual controls, offline only; never a live media grant."""
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
from replay_manual_program_batch import fact_mismatches

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'leadbot/brain'))
import extension_assistant
import contact_phone
import personal_media
from contact_cities import city_by_slug
from assistant_store import Store, digest


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--batch',required=True)
    parser.add_argument('--tag',choices=['baseline','final'],required=True)
    parser.add_argument('--adjudications',help='Separate source recheck; original labels and first baseline stay intact')
    parser.add_argument('--projections',help='Source-bound typed visual facts; never changes a human target')
    parser.add_argument('--controls',help='Additional separately frozen source-bound controls; default labels remain intact')
    args=parser.parse_args()
    assert re.fullmatch(r'\d+-\d+',args.batch)
    folder=ROOT/('test-artifacts/human-practice/manual-batch'+args.batch)
    selected=json.loads((folder/'selection-private.json').read_text())
    assert_development_dialogues(r['cid'] for r in selected)
    rows=json.loads((folder/'sources-private.json').read_text())
    assert {r['cid'] for r in rows}=={r['cid'] for r in selected}
    assert_development_phones(p.value for r in rows for m in r['messages'] if m['direction']=='in'
                              for p in contact_phone.find_all(m.get('text') or m.get('transcript') or ''))
    labels_path=folder/'postmedia-human-controls.json'
    if args.controls:
        labels_path=(folder/args.controls).resolve()
        assert labels_path.parent==folder.resolve() and re.fullmatch(r'[a-z0-9-]+\.json',labels_path.name)
    labels=json.loads(labels_path.read_text())
    resolutions={}
    if args.adjudications:
        path=(folder/args.adjudications).resolve()
        assert path.parent==folder.resolve() and path.suffix=='.json'
        adjudicated=json.loads(path.read_text())
        assert adjudicated['original_labels_sha256']==hashlib.sha256(labels_path.read_bytes()).hexdigest()
        for row in adjudicated['resolutions']:
            assert row['reviewed'] is True and row['reason'] and row['primary_rule_ids']
            original=next(x for x in labels['controls'] if x['id']==row['id'])
            assert original['expected_action']==row['original_expected_action']
            assert set(row['resolved_expectation']).issubset({'expected_action','required_reply_patterns','forbidden_reply_patterns','required_reason_patterns'})
            resolutions[row['id']]=row['resolved_expectation']
    images_path=folder/'image-files-private.json'
    assert hashlib.sha256(images_path.read_bytes()).hexdigest()==labels['images_manifest_sha256']
    images={i['message_id']:i for i in json.loads(images_path.read_text())}
    projections={}
    if args.projections:
        path=(folder/args.projections).resolve()
        assert path.parent==folder.resolve() and path.suffix=='.json'
        supplement=json.loads(path.read_text())
        assert supplement['original_labels_sha256']==hashlib.sha256(labels_path.read_bytes()).hexdigest()
        assert supplement['images_manifest_sha256']==labels['images_manifest_sha256']
        for entry in supplement['projections']:
            assert entry['reviewed'] is True and entry['reason']
            assert entry['sha256']==images[entry['message_id']]['sha256']
            assert set(entry['observations']).issubset({'device_kind','visible_symptom','connector_type'})
            assert entry['message_id'] not in projections
            projections[entry['message_id']]=entry['observations']
    os.environ['LEADBOT_ASSISTANT_WORDING']='reviewed'
    results=[]
    with tempfile.TemporaryDirectory() as tmp:
        app=extension_assistant.Assistant(Store(tmp+'/offline.sqlite'))
        for label in labels['controls']:
            label=dict(label,**resolutions.get(label['id'],{}))
            row=next(r for r in rows if r['number']==label['case'])
            source=row['source'];history=row['messages'][:label['cut']]
            assert history[-1]['id']==label['last_message_id']
            city=city_by_slug(source['city']);title=source['account_title']
            ctx=dict(convId='offline-postmedia-'+label['id'],city=city.name if city else source['city'],
                     dir=next((d for k,d in [('МНЧ','mnc'),('КП','kp'),('БТ','bt')] if k in title),''),
                     partner=source['partner'],channel=source['channel'],accountTitle=title,
                     itemTitle=source['item_title'],origin=source['origin'],
                     messages=[dict(id=m['id'],direction=m['direction'],sender_type=m.get('sender_type'),
                                body=m.get('text') or m.get('transcript') or '',created_at=m['ts'],
                                attachments=m.get('attachments') or [],voice_transcript=m.get('transcript') or '') for m in history])
            chat,messages,known,_=extension_assistant._parse(ctx)
            for projection in label['image_projections']:
                image=images[projection['message_id']]
                assert image['viewed'] is True and image['live_media_approval'] is False
                assert image['message_index']<=label['cut']
                assert hashlib.sha256(Path(image['path']).read_bytes()).hexdigest()==projection['sha256']==image['sha256']
                message=next(m for m in messages if m['id']==projection['message_id'])
                assert message.get('reviewable_image')
                message.update(unread_media=False,media_reviewed=True,offline_fixture=True)
                personal_media.attach_observation(message,dict(projection['observations'],**projections.get(message['id'],{})),source='offline_reviewed_image')
            revision=digest([messages,known,extension_assistant.policy.VERSION,'offline-view-projection'])
            with patch.object(extension_assistant,'_parse',return_value=(chat,messages,known,revision)):
                out,code=app.handle(dict(owner='offline-reasoning-only',action='preview',ctx=ctx))
            assert code==200 and out['auto_enabled'] is False and not out.get('pending_model') and not out.get('validation')
            errors=[]
            errors.extend(str(item) for item in fact_mismatches(out.get('facts', {}), label))
            errors.extend(str(item) for item in fact_mismatches(out, label.get('state_checks', {})))
            if out['action']!=label['expected_action']:errors.append('action: '+out['action']+' expected '+label['expected_action'])
            for field,key in [('reply','required_reply_patterns'),('reason','required_reason_patterns')]:
                for pattern in label[key]:
                    if not re.search(pattern,out.get(field,''),re.IGNORECASE):errors.append('missing '+field+' intent: '+pattern)
            for pattern in label['forbidden_reply_patterns']:
                if re.search(pattern,out.get('reply',''),re.IGNORECASE):errors.append('forbidden reply: '+pattern)
            for image in label['image_projections']:
                model=image['observations'].get('model')
                if model and not any(x.get('model')==model for x in out.get('facts',{}).get('image_observations',[])):
                    errors.append('visible model evidence lost')
            results.append(dict(id=label['id'],case=label['case'],cut=label['cut'],action=out['action'],
                                reply=out.get('reply',''),reason=out.get('reason',''),facts=out.get('facts'),
                                qualification=out.get('qualification'),passed=not errors,errors=errors))
    report=dict(policy=extension_assistant.policy.VERSION,cases=len(results),passed=sum(r['passed'] for r in results),
                labels_sha256=hashlib.sha256(labels_path.read_bytes()).hexdigest(),results=results,
                offline_projection_only=True,live_permits=0,model_calls=0,network_calls=0,crm_writes=0,customer_sends=0,
                autonomous_vision_accuracy_verified=False,final_cohort_opened=False)
    target=folder/((labels_path.stem if args.controls else 'postmedia')+'-'+args.tag+'-private.json')
    if args.tag=='baseline':assert not target.exists(),'Preserve the first frozen-label result'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');target.chmod(0o600)
    print(json.dumps({k:report[k] for k in ['policy','cases','passed','live_permits','model_calls','autonomous_vision_accuracy_verified']},ensure_ascii=False))
    for r in results:
        if not r['passed']:print(json.dumps({k:r[k] for k in ['id','action','reply','reason','errors']},ensure_ascii=False))
    if args.tag=='final':assert report['passed']==report['cases']


if __name__=='__main__':main()
