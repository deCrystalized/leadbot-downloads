"""The native wire must permit what the independent local wording guard permits."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import extension_assistant as ext
from assistant_store import Store
from experienced_dialogues import create_index


class NativeWording209Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.archive=self.root/'archive.sqlite3'
        create_index(self.archive,[dict(cid='other-wording209',case=1,client_group='different209',direction='mnc',
            metadata={'experienced_authors':['Сотрудник']},review_flags=dict(text_reviewed=True,media_reviewed=True),
            messages=[dict(id='old-client',direction='in',sender_type='client',text='Нужно собрать шкаф'),
                      dict(id='old-staff',direction='out',sender_type='operator',author='Сотрудник',delivery='delivered',text='Схема сборки есть?')])],approved_cids=['other-wording209'])
        self.env=patch.dict(os.environ,LEADBOT_PERSONAL_OWNER_ID='wording209',LEADBOT_PERSONAL_AUTO_AVAILABLE='0',
                            LEADBOT_EXPERIENCED_DB=str(self.archive),LEADBOT_EXPERIENCE_REQUIRED='1');self.env.start()
        self.app=ext.Assistant(Store(self.root/'db'))
        self.ctx=dict(convId='current-wording209',dir='mnc',city='Чита',partner='7',channel='avito',
                      itemTitle='Сборка мебели',accountTitle='Учебный мастер МНЧ',
                      messages=[dict(id='client',direction='in',sender_type='client',body='Нужно собрать шкаф.')])

    def tearDown(self):
        self.env.stop();self.temp.cleanup()

    def prepare(self):
        prepared,status=self.app.handle(dict(owner='wording209',action='preview',wording_mode='neural_review',ctx=self.ctx))
        self.assertEqual(status,200);self.assertTrue(prepared['pending_model'])
        return prepared,json.loads(prepared['model_task']['task'])

    def finish(self,prepared,candidate):
        original=json.dumps(candidate,ensure_ascii=False,sort_keys=True)
        out,status=self.app.handle(dict(owner='wording209',action='finalize',request_id=prepared['request_id'],revision=prepared['revision'],candidate=candidate))
        self.assertEqual(status,200);self.assertEqual(json.dumps(candidate,ensure_ascii=False,sort_keys=True),original)
        return out

    def review(self,fits=True):
        return dict(last_intent='Сборка шкафа',latest_client_meaning='Клиент просит собрать шкаф.',
                    selected_step_fits=fits,evidence_ids=['client'],note='Сведения об инструкции пока не сообщались.')

    def test_actual_native_question_schema_is_not_a_single_literal_reply_enum(self):
        prepared,task=self.prepare();style=task['experience_context']['conversation_style']
        self.assertEqual(style['source'],'server_bound_linguistic_options_not_model_understanding')
        reply=prepared['model_task']['response_format']['schema']['properties']['reply']
        self.assertNotIn('enum',reply);self.assertEqual(reply['type'],'string');self.assertEqual(reply['maxLength'],280)

    def test_native_contract_and_finalize_both_preserve_the_same_natural_question(self):
        prepared,_=self.prepare();reply='Подскажите, схема сборки есть?'
        wire=prepared['model_task']['response_format']['schema']['properties']['reply']
        self.assertTrue('enum'not in wire or reply in wire['enum'])
        out=self.finish(prepared,dict(reply=reply,needs_operator=False,context_review=self.review()))
        self.assertEqual(out['validation'],[]);self.assertEqual(out['response_source'],'model')
        self.assertIn(reply,out['reply']);self.assertFalse(out['needs_operator'])

    def test_custom_qualification_also_has_bounded_free_wording_instead_of_literal_enum(self):
        self.ctx['itemTitle']='Сантехник';self.ctx['messages'][0]['body']='Вода в унитазе медленно уходит. Что можно сделать?'
        prepared,task=self.prepare();self.assertEqual(task['decision']['next_question']['kind'],'clog_confirmation')
        self.assertNotIn('enum',prepared['model_task']['response_format']['schema']['properties']['reply'])

    def test_legacy_without_bound_style_retains_the_literal_question_contract(self):
        _,task=self.prepare();task.pop('experience_context')
        wire=ext._structured_response_format(task)['schema']['properties']['reply']
        self.assertEqual(wire['enum'],['',task['decision']['next_question']['question']])

    def test_fixed_reply_stays_exact_even_with_conversation_style(self):
        _,task=self.prepare();task['fixed_reply']='Только заранее проверенный обязательный текст.'
        wire=ext._structured_response_format(task)['schema']['properties']['reply']
        self.assertEqual(wire['enum'],['',task['fixed_reply']])

    def test_strict_shape_recent_evidence_and_independent_veto_are_not_narrowed(self):
        prepared,_=self.prepare();wire=prepared['model_task']['response_format'];schema=wire['schema']
        self.assertTrue(wire['strict']);self.assertFalse(schema['additionalProperties'])
        review=schema['properties']['context_review'];self.assertFalse(review['additionalProperties'])
        props=review['properties'];self.assertEqual(props['evidence_ids']['items']['enum'],['client'])
        self.assertNotIn('enum',props['selected_step_fits']);self.assertNotIn('enum',schema['properties']['needs_operator'])

    def test_independent_safe_veto_is_still_an_empty_handoff(self):
        prepared,_=self.prepare();candidate=dict(reply='',needs_operator=True,context_review=self.review(False))
        candidate['context_review']['note']='Выбранный шаг требует проверки уместности.'
        out=self.finish(prepared,candidate);self.assertEqual(out['reply'],'');self.assertTrue(out['needs_operator'])

    def test_natural_wording_does_not_allow_new_rooms_actions_or_a_second_question(self):
        for index,reply in enumerate(('В спальне схема сборки есть?', 'Завтра приеду. Схема сборки есть?',
                      'Схема сборки есть? И номер телефона?')):
            self.ctx['convId']='unsafe-wording209-'+str(index)
            prepared,_=self.prepare();out=self.finish(prepared,dict(reply=reply,needs_operator=False,context_review=self.review()))
            self.assertNotEqual(out['reply'],reply)
            self.assertFalse(out.get('reply')and reply in out['reply'])
