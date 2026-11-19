"""Source-literal address facts are labeled; service judgement stays with the model."""
import copy
import json
import unittest
import extension_assistant as ext
import test_photo_work_clarification514 as fixture

class PartialAddressLiteral160Tests(unittest.TestCase):
    def setUp(self):
        self.h=fixture.PhotoWorkClarificationTests('test_exact_reviewed_photo_gets_useful_work_question')
        self.h.setUp();self.addCleanup(self.h.doCleanups)

    def ready(self,body='Здравствуйте! Обнинск, улица Табулевича',price_after=False):
        ctx=self.h.context('Нужно собрать шкаф. Сколько будет стоить?')
        ctx['city']='Обнинск';ctx['itemTitle']='Сборка мебели';ctx['messages'][-1].pop('attachments')
        ctx['messages'].extend([
            dict(id='staff-address',direction='out',sender_type='operator',body='Здравствуйте! Куда надо будет приехать?'),
            dict(id='address',direction='in',sender_type='client',body=body)])
        if price_after:ctx['messages'].append(dict(id='price',direction='in',sender_type='client',body='Сколько будет стоить сборка такого шкафа?'))
        p=self.h.preview(ctx);self.assertTrue(p.get('pending_model'),p.get('reason'));t=json.loads(p['model_task']['task'])
        literal=t['output_contract'].get('fixed_latest_client_meaning')
        c=dict(reply=t['proposed_reply'],needs_operator=False,context_review=dict(
            last_intent='Узнать стоимость сборки шкафа',latest_client_meaning=literal or 'Клиент спрашивает стоимость сборки шкафа',
            selected_step_fits=True,evidence_ids=['price' if price_after else 'address'],note='Стоимость после осмотра; схема ещё не подтверждена.'))
        return p,t,c

    def test_literal_preserves_entire_reply_and_is_labeled_only_after_validation(self):
        p,t,c=self.ready();literal='Клиент сообщил: «Здравствуйте! Обнинск, улица Табулевича». Дом в распознанных данных не определён.'
        self.assertEqual(c['context_review']['latest_client_meaning'],literal)
        schema=p['model_task']['response_format']['schema']['properties']['context_review']['properties']
        self.assertEqual(schema['latest_client_meaning']['enum'],[literal]);self.assertNotIn('enum',schema['last_intent'])
        self.assertEqual({x['context_review']['selected_step_fits']for x in t['output_contract']['decision_states']},{True,False})
        before=copy.deepcopy(c);out=self.h.finish(p,c);self.assertFalse(out['validation']);self.assertEqual(c,before)
        origin=out['context_review']['field_sources']['latest_client_meaning']
        self.assertEqual(origin,dict(kind='server_literal_partial_address',evidence_id='address',model_visible_body_preserved=True,independent_model_interpretation=False))
        self.assertNotIn('field_sources',c['context_review']);self.assertFalse(out['auto_enabled'])

    def test_wrong_meaning_or_complete_address_elsewhere_is_not_silently_rewritten(self):
        for field,value,code in [('latest_client_meaning','Клиент узнал цену','partial_address_meaning_mismatch'),('note','Указан точный адрес','partial_address_claimed_complete'),('last_intent','Клиент предоставил полный адрес','partial_address_claimed_complete')]:
            p,t,c=self.ready();c['context_review'][field]=value;before=copy.deepcopy(c)
            with self.subTest(field=field):
                out=self.h.finish(p,c);self.assertIn(code,out['validation']);self.assertFalse(out['reply']);self.assertEqual(c,before)

    def test_latest_price_question_is_not_replaced_by_the_previous_address(self):
        p,t,c=self.ready(price_after=True)
        self.assertIn('partial_address_context',t)
        self.assertNotIn('latest_client_meaning_source',t['output_contract'])
        self.assertNotIn('fixed_latest_client_meaning',t['output_contract'])
        self.assertEqual(t['latest_client_message']['id'],'price')
        self.assertFalse(self.h.finish(p,c)['validation'])

    def test_long_question_voice_or_unrelated_staff_question_do_not_lose_content(self):
        p,t,c=self.ready();original=copy.deepcopy(t)
        self.assertIsNotNone(ext._literal_partial_address_answer(t));self.assertEqual(t,original)
        spaced=copy.deepcopy(t);spaced['latest_client_message']['body']='  Обнинск, улица Табулевича  '
        self.assertIn('«  Обнинск, улица Табулевича  »',ext._literal_partial_address_answer(spaced))
        spoken=copy.deepcopy(t);spoken['latest_client_message']['body']='Обнинск, улица Табулевича двенадцать'
        literal=ext._literal_partial_address_answer(spoken)
        self.assertIn('Табулевича двенадцать',literal);self.assertNotIn('не указан',literal)
        self.assertIn('в распознанных данных',literal)
        for case in ('long','question','voice','unrelated','wrong_source','service','third_party'):
            d=copy.deepcopy(t)
            if case=='long':d['latest_client_message']['body']='Обнинск, улица Табулевича '+('ориентир рядом '*25)
            if case=='question':d['latest_client_message']['body']+=' Сколько стоит?'
            if case=='voice':d['latest_client_message']['voice_transcript']='Ещё просьба из голосового сообщения'
            if case=='unrelated':d['latest_exchange']['previous_staff_speech']['body']='Схема сборки есть?'
            if case=='wrong_source':d['partial_address_context']['evidence_id']='old-address'
            if case=='service':d['latest_exchange']['previous_staff_speech']['speaker_role']='service'
            if case=='third_party':d['literal_third_party_report']={'quote':'Отдельный пересказ'}
            before=copy.deepcopy(d)
            with self.subTest(case=case):self.assertIsNone(ext._literal_partial_address_answer(d));self.assertEqual(d,before)

    def test_literal_quote_does_not_endorse_clients_own_complete_address_label(self):
        p,t,c=self.ready(body='Мой точный адрес: Обнинск, улица Табулевича')
        self.assertIn('«Мой точный адрес:',t['output_contract']['fixed_latest_client_meaning'])
        self.assertTrue(t['output_contract']['fixed_latest_client_meaning'].endswith('Дом в распознанных данных не определён.'))
        out=self.h.finish(p,c);self.assertFalse(out['validation']);self.assertEqual(out['context_review']['field_sources']['latest_client_meaning']['independent_model_interpretation'],False)
