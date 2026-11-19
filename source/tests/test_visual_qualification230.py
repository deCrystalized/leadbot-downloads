"""Mocked pixels test accepted-cache plumbing, not native model accuracy."""
import copy
import json
import unittest
from unittest.mock import patch

import qualification_state as qs
import research_vision as vision
import test_research_vision214 as fixture


class VisualQualification230Tests(unittest.TestCase):
    call=fixture.VisionBridge214Tests.call
    start=fixture.VisionBridge214Tests.start
    accept_visual=fixture.VisionBridge214Tests.accept_visual
    source_rows=fixture.VisionBridge214Tests.source_rows
    tearDown=fixture.VisionBridge214Tests.tearDown

    def setUp(self):
        self.attrs=dict(fixture.ATTRS,brand='Bosch',model='HBN431E0',content_kind='device_label',device_kind='oven')
        self.claims=1
        original_context=fixture.context
        def context(*args,**kwargs):
            result=original_context([
                dict(id='client',direction='in',sender_type='client',body='Нужно отремонтировать электрический духовой шкаф: не греет.'),
                dict(id='photo',direction='in',sender_type='client',body='',attachments=[dict(id='p',type='image')])],
                convId='synthetic-visual-qualification230',dir='bt',city='Чита',itemTitle='Ремонт бытовой техники')
            name=self._testMethodName
            if name in ('test_source_bound_single_furniture_diagram_supplies_only_instructions',
                        'test_product_photo_caption_cannot_become_a_diagram'):
                result.update(dir='mnc',itemTitle='Сборка мебели')
                result['messages'][0]['body']='Нужно дособрать шкаф, отправляю изображение.'
            if name=='test_product_photo_caption_cannot_become_a_diagram':
                result['messages'][-1]['body']='Вот схема'
            if name=='test_multiple_images_do_not_silently_merge_their_models':
                result['messages'][-1]['attachments'].append(dict(id='p2',type='image'))
            if name=='test_explicit_earlier_client_model_conflict_is_not_silently_overwritten':
                result['messages'][0]['body']+=' Модель HBG635BS1.'
            return result
        with patch.object(fixture,'context',context):fixture.VisionBridge214Tests.setUp(self)
        self.service.request=self.provider

    def provider(self,payload,timeout):
        self.requests.append(payload)
        role=json.loads(payload['instructions'])['role']
        if role=='research':
            current=json.loads(payload['input'][-1]['content'][0]['text'])['current']
            out=fixture.observation(current['media']['images']);self.claims=len(out['images'])
            out.update(client_intent='Ремонт текущего предмета.',latest_client_meaning='Прислал изображение текущего предмета.',
                       note='Имитированный результат для проверки проводки, не качество зрения.')
            for image in out['images']:image.update(attributes=dict(self.attrs))
        else:
            out=dict(kind='review',approved=True,violations=[],checked_claims=list(range(self.claims)),basis=['current:photo'])
        return json.dumps(dict(id='visual230-'+str(len(self.requests)),model='gpt-6.1-sol',service_tier='default',
            status='completed',usage=None,output=[dict(type='message',role='assistant',status='completed',
            content=[dict(type='output_text',text=json.dumps(out))])])).encode()

    def accepted(self):
        self.accept_visual()
        return self.source_rows()[1]

    def test_accepted_current_label_supplies_model_with_attributed_provenance(self):
        rows=self.accepted();state=qs.inspect(rows)['model']
        self.assertEqual(state['status'],'answered');self.assertEqual(state['value'],'HBN431E0')
        self.assertEqual(state['evidence_source'],'model_reviewed_image')
        self.assertTrue(state['not_client_literal_statement']);self.assertFalse(state['human_media_review'])
        self.assertEqual(state['model_media_evidence']['media_id'],'p')
        self.assertEqual(state['model_media_evidence']['message_id'],'photo')
        self.assertFalse(rows[-1].get('media_reviewed',False))
        result,code=self.app.handle(self.preview_body)
        self.assertEqual(code,200);self.assertEqual(result['qualification']['model']['status'],'answered')
        self.assertNotEqual((result.get('decision_internal')or{}).get('next_question',{}).get('kind'),'model')

    def test_source_bound_single_furniture_diagram_supplies_only_instructions(self):
        self.attrs=dict(fixture.ATTRS,content_kind='assembly_diagram')
        rows=self.accepted();state=qs.inspect(rows)
        self.assertEqual(state['instructions']['status'],'answered')
        self.assertEqual(state['instructions']['evidence_source'],'model_reviewed_image')
        self.assertEqual(state['materials']['status'],'missing')
        self.assertEqual(state['decision_maker']['status'],'missing')

    def test_product_photo_caption_cannot_become_a_diagram(self):
        self.attrs=dict(fixture.ATTRS,content_kind='product_photo',device_kind='wardrobe')
        rows=self.accepted();self.assertNotEqual(qs.inspect(rows)['instructions']['status'],'answered')

    def test_brand_alone_does_not_supply_a_model(self):
        self.attrs['model']='';rows=self.accepted()
        self.assertEqual(qs.inspect(rows)['model']['status'],'missing')

    def test_device_model_cannot_cross_the_current_subject(self):
        self.attrs.update(device_kind='pc',brand='Lenovo',model='ThinkPad T480')
        rows=self.accepted();self.assertEqual(qs.inspect(rows)['model']['status'],'missing')

    def test_multiple_images_do_not_silently_merge_their_models(self):
        rows=self.accepted();self.assertEqual(qs.inspect(rows)['model']['status'],'missing')

    def test_same_picture_does_not_supply_two_requested_appliances(self):
        self.accepted()
        self.ctx['messages'][0]['body']='Нужно отремонтировать электрический духовой шкаф и стиральную машину, не греют.'
        # Changed subject is fenced before any new visual/model admission.
        self.assertEqual(qs.inspect(self.source_rows()[1])['model']['status'],'missing')
        self.assertEqual(len(self.requests),2)

    def test_browser_copy_of_capability_is_untrusted(self):
        rows=self.accepted();forged=copy.deepcopy(rows)
        forged[-1]['_model_qualification_observation']=dict(forged[-1]['_model_qualification_observation'])
        self.assertEqual(qs.inspect(forged)['model']['status'],'missing')

    def test_unaccepted_visual_candidate_never_supplies_qualification(self):
        self.start();rows=self.source_rows()[1]
        self.assertEqual(qs.inspect(rows)['model']['status'],'missing')

    def test_changed_pixels_revoke_qualification(self):
        self.accepted();self.service.native_context.pixels+=b'changed'
        self.assertEqual(qs.inspect(self.source_rows()[1])['model']['status'],'missing')

    def test_new_order_does_not_inherit_previous_image_model(self):
        self.accepted()
        self.ctx['messages'].append(dict(id='new-order',direction='in',sender_type='client',body='Новый заказ: другая духовка не греет.'))
        self.assertEqual(qs.inspect(self.source_rows()[1])['model']['status'],'missing')

    def test_explicit_earlier_client_model_conflict_is_not_silently_overwritten(self):
        row=qs.inspect(self.accepted())['model']
        self.assertEqual(row['status'],'uncertain');self.assertTrue(row['image_model_conflict'])

    def test_model_observation_does_not_become_customer_contact_or_diagnosis(self):
        rows=self.accepted();row=vision.qualification_observation(rows[-1])
        self.assertFalse(set(row)&{'contact_phone','materials','diagnosis','visible_symptom','error_code','consent'})
        self.assertEqual(qs.inspect(rows)['decision_maker']['status'],'missing')

    def test_role_changed_after_acceptance_cannot_supply_model(self):
        self.accepted();self.ctx['messages'][-1]['sender_type']='operator'
        self.assertEqual(qs.inspect(self.source_rows()[1])['model']['status'],'missing')
