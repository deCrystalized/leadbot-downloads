"""A known city/street must not turn into a complete or map-verified address."""
import copy
import json
import unittest
import extension_assistant as ext
import test_photo_work_clarification514 as fixture

class PartialAddress159Tests(unittest.TestCase):
    def setUp(self):
        self.h=fixture.PhotoWorkClarificationTests('test_exact_reviewed_photo_gets_useful_work_question')
        self.h.setUp();self.addCleanup(self.h.doCleanups)

    def ready(self,house=''):
        text=('Нужно собрать шкаф. Сколько будет стоить?' if house else 'Нужно собрать шкаф. Обнинск, улица Табулевича. Сколько будет стоить?')
        ctx=self.h.context(text)
        ctx['city']='Обнинск';ctx['itemTitle']='Сборка мебели';ctx['messages'][-1].pop('attachments')
        if house:
            ctx['messages'].append(dict(id='address',direction='in',sender_type='client',body='Обнинск, улица Табулевича, дом '+house))
        p=self.h.preview(ctx);self.assertTrue(p.get('pending_model'),p.get('reason'))
        t=json.loads(p['model_task']['task'])
        c=dict(reply=t['proposed_reply'],needs_operator=False,context_review=dict(last_intent='Узнать стоимость сборки шкафа',latest_client_meaning='Клиент сообщил город и улицу; номер дома ещё не указан',selected_step_fits=True,evidence_ids=['image'],note='Точная стоимость после осмотра; схема пока не подтверждена.'))
        return p,t,c

    def test_observed_street_without_house_is_explicit_before_proposal(self):
        p,t,c=self.ready();scope=t['partial_address_context']
        self.assertEqual(scope['known'],{'city':'Обнинск','street':'улица Табулевича'})
        self.assertEqual(scope['missing_from_observed_fields'],['building']);self.assertFalse(scope['full_address_confirmed'])
        self.assertEqual(scope['evidence_id'],'image')
        self.assertLess(p['model_task']['task'].index('"partial_address_context"'),p['model_task']['task'].index('"proposed_reply"'))
        self.assertNotIn('partial_address_review',p['model_task']['response_format']['schema']['properties']['context_review']['properties'])
        self.assertFalse(self.h.finish(p,c)['validation'])

    def test_wrong_complete_address_is_rejected_in_every_review_field_and_reply(self):
        for key in ['last_intent','latest_client_meaning','note','reply']:
            p,t,c=self.ready()
            if key=='reply':c[key]='Спасибо за точный адрес. '+c[key]
            else:c['context_review'][key]='Указан точный адрес в Обнинске для проведения работ'
            with self.subTest(field=key):
                out=self.h.finish(p,c);self.assertIn('partial_address_claimed_complete',out['validation']);self.assertFalse(out['reply'])

    def test_questions_and_explicitly_incomplete_address_are_not_false_claims(self):
        for text in ['Нужно уточнить точный адрес.','Какой полный адрес?','Точный адрес пока не известен.','Клиент не указал полный адрес.','Уточнение полного адреса необходимо.','Вопрос про точный адрес уместен.','Получить точный адрес.']:
            with self.subTest(text=text):self.assertFalse(ext._partial_address_complete_claim(text))
        for text in ['Указан точный адрес','Клиент сообщил полный адрес','Адрес полностью указан','Полный адрес: Обнинск, улица Табулевича','Спасибо за точный адрес']:
            with self.subTest(text=text):self.assertTrue(ext._partial_address_complete_claim(text))

    def test_actual_house_removes_partial_scope_without_implying_map_verification(self):
        p,t,c=self.ready('12');self.assertNotIn('partial_address_context',t)
        self.assertEqual(p['facts']['address']['building'],'12')
        self.assertFalse(p['facts']['client_location']['map_verified'])

    def test_raw_house_candidate_is_not_labeled_absent_when_extraction_is_incomplete(self):
        ctx=self.h.context('Нужно собрать шкаф. Обнинск, улица Табулевича, дом 12. Сколько будет стоить?')
        ctx['city']='Обнинск';ctx['messages'][-1].pop('attachments')
        p=self.h.preview(ctx);t=json.loads(p['model_task']['task'])
        self.assertNotIn('partial_address_context',t)
        self.assertIn('дом 12.',t['latest_client_message']['body'])
