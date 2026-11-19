import copy
import hashlib
import json
import unittest
from pathlib import Path

import research_vision as vision
import personal_workflow
import personal_assistant
from assistant_store import digest
from extension_assistant import _parse
from research_media import prepare
from research_openai import ResponsesTransport,TransportError
from api_costs import UsageLedger
from research_pipeline import pack_context
import test_research_bridge203 as bridge_fixture
import test_research_media204 as media_fixture
import test_research_pipeline218 as context_fixture
from test_assistant import context,message


ATTRS={k:'' for k in ('brand','model','content_kind','device_kind','visible_symptom','connector_type','error_system','error_code')}


def observation(images):
    return dict(kind='visual_observation',client_intent='Клиент просит повесить полку.',
        latest_client_meaning='Прислал изображение к просьбе о полке.',note='Описание изображения не подтверждает комплектность.',
        images=[dict(message_id=i['message_id'],media_id=i['media_id'],sha256=i['sha256'],speaker_role=i['speaker_role'],
            description='Тестовое изображение без доказанной комплектности.',attributes=dict(ATTRS),unknowns=['Размеры не установлены.'])for i in images],
        needs_operator=False,limitations=['Не подтверждает запасы мастера, метод или гарантию.'])


class Vision214Tests(unittest.TestCase):
    def setUp(self):
        media_fixture.MediaTests.setUp(self)
        self.current['media']=self.prepared()

    def prepared(self):return media_fixture.MediaTests.prepared(self)
    def resolver(self,scope,descriptor):return media_fixture.MediaTests.resolver(self,scope,descriptor)

    def run_pair(self,change=None):
        self.payloads=[];self.events=[]
        value=observation(self.current['media']['images'])
        if change:change(value)
        def provider(payload,timeout):
            self.payloads.append(payload);role=json.loads(payload['instructions'])['role']
            out=value if role=='research' else dict(kind='review',approved=True,violations=[],checked_claims=list(range(len(value['images']))),basis=['current:m1'])
            return dict(id='visual-'+role,model='gpt-6.1-sol',service_tier='default',status='completed',usage=None,
                output=[dict(type='message',role='assistant',status='completed',content=[dict(type='output_text',text=json.dumps(out))])])
        transport=ResponsesTransport(provider,UsageLedger(),media_resolver=self.resolver)
        return vision.run(self.current,transport,audit=lambda *args:self.events.append(args))

    def test_two_distinct_stages_see_same_pixels_and_cannot_return_customer_reply(self):
        result=self.run_pair();self.assertTrue(result['approved']);self.assertFalse(result['human_media_review'])
        self.assertEqual(len(self.payloads),2)
        pixels=lambda p:[x for item in p['input']for x in item.get('content',[]) if x.get('type')=='input_image']
        self.assertEqual(pixels(self.payloads[0]),pixels(self.payloads[1]));self.assertTrue(pixels(self.payloads[0]))
        self.assertNotIn('reply',self.payloads[0]['text']['format']['schema']['properties'])
        self.assertIn('visual_observation',self.payloads[1]['input'][1]['content'][0]['text'])

    def test_foreign_role_media_hash_or_missing_image_stops_before_review(self):
        for field in ('message_id','media_id','sha256','speaker_role'):
            with self.subTest(field=field),self.assertRaises(ValueError):self.run_pair(lambda x:x['images'][0].update({field:'foreign'}))
            self.assertEqual(len(self.payloads),1)
        with self.assertRaises(ValueError):self.run_pair(lambda x:x['images'].clear())

    def test_all_distinct_originals_required_without_first_image_only(self):
        other=dict(self.current['media']['images'][0],media_id='second',position=1)
        self.current['media']['images'].append(other)
        value=observation(self.current['media']['images']);self.assertEqual(len(vision.check_observation(value,self.current)['images']),2)
        value['images'].pop()
        with self.assertRaises(ValueError):vision.check_observation(value,self.current)

    def test_unknown_model_or_photographed_contact_is_not_imported(self):
        with self.assertRaises(ValueError):self.run_pair(lambda x:x['images'][0]['attributes'].update(model='A4'))
        value=observation(self.current['media']['images']);value['images'][0]['attributes']['contact_phone']='12345678900'
        with self.assertRaises(ValueError):vision.check_observation(value,self.current)

    def test_generic_packet_cannot_supply_an_arbitrary_new_purpose(self):
        p=pack_context('research',self.current);p['purpose']='send_message'
        with self.assertRaises(TransportError):ResponsesTransport(lambda *a:self.fail('No provider'),UsageLedger())('research',p,())


class VisionBridge214Tests(unittest.TestCase):
    def setUp(self):
        bridge_fixture.ResearchBridgeTests.setUp(self)
        self.ctx=context([message('Нужно повесить полку.',mid='client'),dict(id='photo',direction='in',sender_type='client',
            body='',attachments=[dict(id='p',type='image')])],convId='vision-214',dir='mnc',city='Чита',itemTitle='Мастер на час')
        identity=self.identity
        class Native:
            pixels=media_fixture.PNG
            group='a'*64
            def prepare(n,body,actor):
                ctx=copy.deepcopy(getattr(n,'source_override',body['ctx']));ctx['sourceSnapshotSha256']=digest(ctx['messages'])
                ctx.update(sourceClientGroup=n.group,sourcePhoneHashes=[],sourceMediaHashes=[])
                return dict(body,ctx=ctx),dict(cid=ctx['convId'],client_group=n.group,phone_hashes=[],media_hashes=[],source_sha256=ctx['sourceSnapshotSha256']),actor
            def bind(n,*args):pass
            def image_digest(n,*args):return hashlib.sha256(n.pixels).hexdigest()
            def resolver(n,scope,item):
                return dict(scope,message_id=item['message_id'],media_id=item['media_id'],attachment_hash=item['attachment_hash'],
                    data=n.pixels,mime='image/png',sha256=hashlib.sha256(n.pixels).hexdigest())
        self.service.native_context=Native();self.service.media_resolver=self.service.native_context.resolver
        self.preview_body=dict(owner='owner',action='preview',ctx=self.ctx,wording_mode='neural_review',
            _trusted_research_profile='sol_only',identity_proof='test-identity')
        self.prepared,code=self.app.handle(self.preview_body)
        self.assertEqual(code,200);self.assertTrue(self.prepared.get('pending_model'),self.prepared)
        self.assertEqual(self.prepared.get('research_purpose'),vision.PURPOSE)
        self.body=dict(owner='owner',ctx=self.ctx,request_id=self.prepared['request_id'],revision=self.prepared['revision'],identity_proof='test-identity')
        self.requests=[];self.work.clear();self.bad_review=False
        self.service.request=self.provider

    def provider(self,payload,timeout):
        self.requests.append(payload);role=json.loads(payload['instructions'])['role']
        if role=='research':
            current=json.loads(payload['input'][-1]['content'][0]['text'])['current'];out=observation(current['media']['images'])
        else:out=dict(kind='review',approved=not self.bad_review,violations=['Не подтверждено'] if self.bad_review else [],checked_claims=[0],basis=['current:photo'])
        return json.dumps(dict(id='vision-'+str(len(self.requests)),model='gpt-6.1-sol',service_tier='default',status='completed',usage=None,
            output=[dict(type='message',role='assistant',status='completed',content=[dict(type='output_text',text=json.dumps(out))])])).encode()

    def call(self,action,**extra):return self.app.handle(dict(self.body,action=action,**extra))

    def source_rows(self,ctx=None):
        prepared=self.service.prepare_source(self.app,dict(self.preview_body,ctx=ctx or self.ctx))
        return _parse(prepared['ctx'],self.app.store,self.scope)

    def accept_visual(self):
        job=self.start();status=self.service.jobs.status('owner',job);self.assertEqual(status['state'],'awaiting_root',status)
        self.service.jobs.decide(job,status['result_sha256'],accepted=True,reviewer='local-test-root')
        final,code=self.call('research_finalize',research_job_id=job);self.assertEqual(code,200,final)
        return job,final

    def start(self):
        self.service.admit(self.app,self.body,max_calls=2,seconds=300)
        out,code=self.call('research_start');self.assertEqual(code,200,out);self.assertEqual(len(self.work),1)
        self.work.pop(0)();return out['research_job_id']

    def test_full_preview_job_review_root_finalize_then_new_preview_without_human_ack(self):
        job=self.start();status=self.service.jobs.status('owner',job);self.assertEqual(status['state'],'awaiting_root',status)
        self.service.jobs.decide(job,status['result_sha256'],accepted=True,reviewer='local-test-root')
        final,code=self.call('research_finalize',research_job_id=job);self.assertEqual(code,200,final)
        self.assertTrue(final['visual_observation_ready']);self.assertFalse(final['human_media_review']);self.assertEqual(final['reply'],'')
        self.assertEqual(self.service.jobs.status('owner',job)['state'],'done')
        _,rows,_,revision=self.source_rows()
        photo=rows[-1];self.assertTrue(photo['media_model_reviewed']);self.assertFalse(photo['unread_media'])
        self.assertFalse(photo.get('media_reviewed',False));self.assertFalse(photo['human_media_review'])
        out,code=self.app.handle(self.preview_body);self.assertEqual(code,200,out)
        self.assertNotEqual(out.get('research_purpose'),vision.PURPOSE);self.assertNotEqual(out['revision'],self.prepared['revision'])
        final_again,code=self.call('research_status',research_job_id=job)
        self.assertEqual(code,200,final_again);self.assertTrue(final_again['visual_observation_ready'])
        self.assertEqual(out['revision'],self.source_rows()[3])
        self.assertEqual(len(self.requests),2)

    def test_denial_never_activates_visual_observations(self):
        job=self.start();status=self.service.jobs.status('owner',job)
        self.service.jobs.decide(job,status['result_sha256'],accepted=False,reviewer='local-test-root')
        _,rows,_,_=_parse(self.ctx,self.app.store,self.scope)
        self.assertTrue(rows[-1]['unread_media']);self.assertFalse(rows[-1].get('media_model_reviewed',False))

    def test_failed_separate_review_stops_without_root_or_preview_release(self):
        self.bad_review=True;job=self.start()
        self.assertEqual(self.service.jobs.status('owner',job)['state'],'rejected')
        _,rows,_,_=_parse(self.ctx,self.app.store,self.scope);self.assertTrue(rows[-1]['unread_media'])

    def test_changed_source_after_root_cannot_activate_observation(self):
        job=self.start();status=self.service.jobs.status('owner',job)
        self.service.jobs.decide(job,status['result_sha256'],accepted=True,reviewer='local-test-root')
        self.ctx['messages'][-1]['attachments'][0]['id']='new-photo'
        out,code=self.call('research_finalize',research_job_id=job)
        self.assertEqual(code,403);self.assertEqual(out['code'],'research_stopped');self.assertFalse(out.get('visual_observation_ready',False))

    def test_existing_request_and_manual_hold_are_not_overridden_for_photo(self):
        for update in (dict(crmRequestId='1234567'),dict(hasCrmJob=True)):
            ctx=copy.deepcopy(self.ctx);ctx.update(update)
            out,code=self.app.handle(dict(self.preview_body,ctx=ctx,request_id='existing-'+next(iter(update))))
            self.assertFalse(out.get('pending_model',False),out);self.assertNotEqual(out.get('research_purpose'),vision.PURPOSE)

    def test_readonly_visual_plan_reaches_service_and_territory_before_claim(self):
        ctx=dict(self.ctx,assigneeId='operator',assignmentKnown=True,conversationStatus='in_progress',botActive=False,
                 hasTransfer=False,channelAssigned=True)
        _,rows,known,revision=_parse(ctx)
        session=dict(operator_id='operator',max_dialogs=10,mode_epoch=1,execution_mode='review')
        plan=personal_workflow.plan(rows,known,ctx,session,1,revision,allow_visual=True)
        self.assertTrue(plan['eligible'],plan);self.assertEqual(plan['step'],'inspect_media')
        self.assertFalse(plan['execution_allowed']);self.assertFalse(plan['auto_enabled'])
        for update in (dict(assigneeId='colleague'),dict(crmRequestId='1234567'),dict(channelAssigned=False),dict(city='Неизвестный город')):
            different=dict(ctx,**update);_,rows,known,_=_parse(different)
            screened=personal_assistant.screen(rows,known,different,'operator',10,1,allow_visual=True)
            self.assertFalse(screened['eligible'],screened)

    def test_direct_preview_respects_other_assignee_and_explicit_wait_before_photo(self):
        for n,change in enumerate((dict(assigneeId='colleague'),dict(messages=self.ctx['messages']+[
                dict(id='wait',direction='in',sender_type='client',body='Секунду, подождите пожалуйста.')]))):
            result,code=self.app.handle(dict(self.preview_body,request_id='blocked-visual-'+str(n),ctx=dict(self.ctx,**change)))
            self.assertFalse(result.get('pending_model',False),result)
            self.assertFalse(result.get('research_purpose')==vision.PURPOSE,result)

    def test_same_photo_after_later_speech_reuses_physical_observation_without_old_intent(self):
        self.accept_visual()
        self.ctx['messages'] += [dict(id='staff-later',direction='out',sender_type='operator',delivery_status='delivered',body='Схема сборки есть?'),
                                 dict(id='client-later',direction='in',sender_type='client',body='Да, есть.')]
        _,rows,_,_=self.source_rows();photo=next(m for m in rows if m['id']=='photo')
        self.assertTrue(photo['media_model_reviewed']);self.assertFalse(photo['unread_media']);self.assertNotIn('client_intent',photo)
        result,code=self.app.handle(self.preview_body);self.assertEqual(code,200,result)
        self.assertNotEqual(result.get('research_purpose'),vision.PURPOSE);self.assertEqual(len(self.requests),2)

    def test_same_metadata_changed_pixels_revokes_old_record_and_cannot_reactivate_old_job(self):
        job,_=self.accept_visual();self.service.native_context.pixels=media_fixture.PNG+b'changed original bytes'
        result,code=self.app.handle(self.preview_body);self.assertEqual(code,200,result)
        self.assertEqual(result.get('research_purpose'),vision.PURPOSE,result)
        self.assertNotEqual(result['request_id'],self.prepared['request_id']);self.assertEqual(len(self.requests),2)
        old,code=self.call('research_status',research_job_id=job)
        self.assertEqual(code,403);self.assertFalse(old.get('visual_observation_ready',False))
        self.assertTrue(next(m for m in self.source_rows()[1] if m['id']=='photo')['unread_media'])

    def test_changed_pixels_during_provider_request_stop_before_separate_review(self):
        source = copy.deepcopy(self.ctx)

        def provider(payload, timeout):
            response = self.provider(payload, timeout)
            self.service.native_context.pixels = media_fixture.PNG + b'changed original bytes'
            return response

        self.service.request = provider
        job = self.start()
        self.assertEqual(self.ctx, source)
        self.assertEqual(len(self.requests), 1)
        status = self.service.jobs.status('owner', job)
        self.assertEqual(status['state'], 'stopped')
        self.assertEqual(status['calls_spent'], 1)
        events = self.service.jobs.audit_read('owner', job)['events']
        changes = [event['detail']['changed_fields'] for event in events
                   if event['event'] == 'context_binding_changed']
        self.assertEqual(changes, [['task']])
        final, code = self.call('research_finalize', research_job_id=job)
        self.assertFalse(final.get('visual_observation_ready', False))
        self.assertFalse(final.get('can_send_or_create', False))
        self.assertNotEqual(code, 200)
        self.assertEqual(len(self.requests), 1)

    def test_new_enquiry_prior_text_role_or_client_group_do_not_reuse_old_scope(self):
        self.accept_visual();base=copy.deepcopy(self.ctx)
        variants=[]
        changed=copy.deepcopy(base);changed['messages'].append(dict(id='another',direction='in',sender_type='client',body='Новый заказ: нужен другой шкаф.'));variants.append(changed)
        changed=copy.deepcopy(base);changed['messages'][0]['body']='Это только пример чужой мебели.';variants.append(changed)
        changed=copy.deepcopy(base);changed['messages'][-1].update(direction='out',sender_type='operator');variants.append(changed)
        for current in variants:
            with self.subTest(current=current['messages'][-1]['id']):
                photo=next(m for m in self.source_rows(current)[1]if m['id']=='photo');self.assertFalse(photo.get('media_model_reviewed',False))
        self.service.native_context.group='b'*64
        self.assertFalse(next(m for m in self.source_rows(base)[1]if m['id']=='photo').get('media_model_reviewed',False))

    def test_browser_dictionary_is_not_native_pixel_verification(self):
        self.accept_visual();ctx=copy.deepcopy(self.ctx);ctx['sourceClientGroup']='a'*64
        attachment=ctx['messages'][-1]['attachments'][0]
        signature=digest([attachment]);key=digest(['photo',signature,'p'])
        ctx['_native_visual_checks']={key:hashlib.sha256(media_fixture.PNG).hexdigest()}
        _,rows,_,_=_parse(ctx,self.app.store,self.scope)
        self.assertTrue(rows[-1]['unread_media']);self.assertFalse(rows[-1].get('media_model_reviewed',False))

    def test_missing_original_stops_cached_preview_before_another_model_call(self):
        self.accept_visual()
        def missing(*a):raise ValueError('Original absent')
        self.service.native_context.image_digest=missing
        result,code=self.app.handle(self.preview_body)
        self.assertEqual(code,409);self.assertEqual(result['code'],'native_source_unavailable');self.assertEqual(len(self.requests),2)

    def test_authenticated_timeline_replaces_browser_copy_before_observing_generation(self):
        self.service.native_context.source_override=copy.deepcopy(self.ctx)
        self.service.admit(self.app,self.body,max_calls=2,seconds=300)
        self.body['ctx']=dict(self.ctx,messages=[dict(id='forged',direction='in',sender_type='client',body='Подмена браузера')])
        out,code=self.call('research_start');self.assertEqual(code,200,out)
        self.work.pop(0)();self.assertEqual(self.service.jobs.status('owner',out['research_job_id'])['state'],'awaiting_root')

    def test_quote_negation_and_staff_new_order_words_do_not_change_physical_scope(self):
        self.accept_visual();base=copy.deepcopy(self.ctx)
        for direction,sender,text in [('in','client','Он сказал «новый заказ». Это цитата.'),
                                      ('in','client','Это не новый заказ, всё тот же шкаф.'),
                                      ('out','operator','Новый заказ: только служебная подпись.')]:
            ctx=copy.deepcopy(base);ctx['messages'].append(dict(id='later',direction=direction,sender_type=sender,body=text))
            with self.subTest(text=text):self.assertTrue(next(m for m in self.source_rows(ctx)[1]if m['id']=='photo')['media_model_reviewed'])


if __name__=='__main__':unittest.main()
