"""An unverified work-place hint cannot become a city or a map result."""
import json,os,tempfile,unittest
from unittest.mock import patch
import test_dialogue_context150 as fixture
import contact_facts
import extension_assistant as ext
from assistant_store import Store


class WorkDestination151Tests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        env=patch.dict(os.environ,LEADBOT_PERSONAL_OWNER_ID='synthetic151',LEADBOT_PERSONAL_AUTO_AVAILABLE='0');env.start();self.addCleanup(env.stop)
        self.app=ext.Assistant(Store(tmp.name+'/db'))
    def history(self):
        return [fixture.row('Нужно собрать шкаф, схема есть',mid='job'),fixture.row('Адрес подскажите','out','addressq'),
                fixture.row('Надо ехать в сторону Богашево (Новостройка), могу только вечером',mid='where')]
    def preview(self,h=None,**extra):
        ctx=dict(convId='synthetic151-'+self.id().split('.')[-1],city='Томск',dir='mnc',channel='avito',partner='7',origin='С1',accountTitle='Учебный МНЧ',itemTitle='Сборка мебели',messages=h or self.history());ctx.update(extra)
        out,status=self.app.handle(dict(owner='synthetic151',action='preview',wording_mode='neural_review',ctx=ctx))
        self.assertEqual(status,200);self.assertFalse(out['auto_enabled']);self.assertFalse(out['lead']['can_create_automatically'])
        return out,json.loads(out['model_task']['task'])if out.get('model_task')else None
    def candidate(self,t):
        return dict(reply=t['proposed_reply'],needs_operator=False,context_review=dict(last_intent='Сборка шкафа по адресу клиента',latest_client_meaning=t['output_contract'].get('fixed_latest_client_meaning')or'Уточнил работы',selected_step_fits=True,evidence_ids=[t['latest_client_message']['evidence_id']],note='Точный адрес и территория не подтверждены; вопрос нужен.'))
    def test_routing_city_does_not_claim_known_work_location(self):
        o,t=self.preview();g=o['geography'];self.assertEqual(g['status'],'work_destination_unverified');self.assertEqual(g['routing_city'],'Томск');self.assertIsNone(g['far_trip']);self.assertFalse(g['work_location_verified']);self.assertFalse(t['work_destination_context']['listing_city_proves_work_city'])
    def test_exact_client_destination_answer_is_native_literal_not_a_district_guess(self):
        o,t=self.preview();literal=t['output_contract']['fixed_latest_client_meaning'];self.assertIn(self.history()[-1]['body'],literal);self.assertLessEqual(len(literal),200)
        schema=o['model_task']['response_format']['schema']['properties']['context_review']['properties'];self.assertEqual(schema['latest_client_meaning']['enum'],[literal])
    def test_actual_wrong_city_and_district_meaning_is_rejected(self):
        o,t=self.preview();c=self.candidate(t);c['context_review']['latest_client_meaning']='Адрес находится в Томске, район Богашево (Новостройка); клиент свободен вечером'
        _,_,errors=ext._context_review(c,t);self.assertIn('unverified_work_destination_claim',errors)
    def test_city_invention_is_rejected_in_note_and_intent_too(self):
        o,t=self.preview()
        for key in ['note','last_intent']:
            c=self.candidate(t);c['context_review'][key]='Территория не проверена, но адрес находится в Томске'
            with self.subTest(key=key):self.assertIn('unverified_work_destination_claim',ext._context_review(c,t)[2])
    def test_false_map_confirmation_is_not_a_model_proof(self):
        o,t=self.preview();c=self.candidate(t);c['context_review']['note']='Территория проверена по карте, можно собирать заявку';self.assertIn('unverified_work_destination_claim',ext._context_review(c,t)[2])
    def test_literal_uncertainty_and_listing_city_attribution_are_allowed(self):
        o,t=self.preview();c=self.candidate(t);c['context_review']['note']='Томск — город объявления; точный адрес и территория не подтверждены.'
        review,_,errors=ext._context_review(c,t);self.assertFalse(errors);self.assertIsNotNone(review)
    def test_later_work_scope_does_not_inherit_fixed_destination_answer(self):
        h=self.history()+[fixture.row('Какие ещё работы?','out','scopeq'),fixture.row('Подсоединить раковину и сделать прорезь в столешнице',mid='scope')]
        o,t=self.preview(h);self.assertEqual(t['decision']['next_question']['kind'],'countertop_material');self.assertFalse(t['work_destination_context']['latest_is_destination_answer']);self.assertNotIn('fixed_latest_client_meaning',t['output_contract'])
    def test_new_complete_explicit_work_address_replaces_unverified_hint(self):
        h=self.history()+[fixture.row('Адрес работ: Томск, улица Ленина, дом 10',mid='exact')]
        v=contact_facts.service_destination_hint(h,dict(city='Томск',building='10'),{'address.city':dict(message_id='exact'),'address.building':dict(message_id='exact')})
        self.assertEqual(v['status'],'replaced_by_explicit_work_address');self.assertEqual(v['replaced_by_message_id'],'exact')
