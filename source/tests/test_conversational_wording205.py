import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experience_wording import contextual_style, verified_question
from experienced_dialogues import create_index
from assistant_store import Store
from extension_assistant import Assistant


def history():
    return [dict(id='work', direction='in', sender_type='client', body='Нужно собрать шкаф-купе'),
            dict(id='q', direction='out', sender_type='bot', delivery_status='delivered', body='Схема сборки есть?'),
            dict(id='a', direction='in', sender_type='client', body='Схема есть.')]


class ConversationalWording205Tests(unittest.TestCase):
    question = dict(kind='materials', question='Материалы и комплектующие есть?', groups=[['материал', 'комплектующ']])

    def experience(self, messages=None):
        return dict(version='a'*64, examples=[], conversation_style=contextual_style(messages or history(), self.question))

    def test_optional_short_ack_and_current_furniture_subject_can_be_preserved(self):
        for reply in ('Спасибо. Все материалы и комплектующие для шкафа есть?',
                      'Хорошо, подскажите, материалы и комплектующие для шкафа есть?',
                      'Материалы и комплектующие для шкафа есть?'):
            with self.subTest(reply=reply):
                self.assertTrue(verified_question(reply, self.question, self.experience(), 'provided'))

    def test_exact_short_question_remains_valid_without_a_fake_uniqueness_quota(self):
        self.assertTrue(verified_question(self.question['question'], self.question, self.experience(), 'provided'))

    def test_selected_phone_synonym_does_not_fall_back_just_for_different_wording(self):
        question=dict(kind='phone',question='Номер для связи подскажите?',groups=[['номер','телефон']])
        self.assertTrue(verified_question('Ваш телефон подскажите?',question,self.experience(),'provided'))

    def test_contacts_allow_one_polite_information_request_without_question_mark(self):
        question=dict(kind='phone',question='Номер для связи подскажите?',groups=[['номер','телефон']])
        for reply in ('Напишите, пожалуйста, ваш номер для связи.', 'Оставьте ваш телефон, пожалуйста.',
                      'Спасибо. Номер для связи подскажите.'):
            self.assertTrue(verified_question(reply,question,self.experience(),'provided'),reply)

    def test_contact_imperative_does_not_allow_new_actions_or_change_other_questions(self):
        question=dict(kind='phone',question='Номер для связи подскажите?',groups=[['номер','телефон']])
        for reply in ('Напишите номер, завтра позвоню.', 'Оставьте номер и адрес квартиры.',
                      'Напишите номер. Позвоню.', 'Наш номер запишите.'):
            self.assertFalse(verified_question(reply,question,self.experience(),'provided'),reply)
        self.assertFalse(verified_question('Напишите схему сборки.',dict(kind='instructions',question='Схема сборки есть?',groups=[['схем']]),self.experience(),'provided'))

    def test_complete_furniture_kit_alias_still_requires_all_parts_and_fasteners(self):
        question=dict(self.question,alternative_groups=[[['все'],['детал'],['крепёж','крепеж'],['есть','налич','комплект']]])
        experience=self.experience()
        self.assertTrue(verified_question('Все детали и крепёж для шкафа в комплекте?',question,experience,'provided'))
        self.assertFalse(verified_question('Крепёж для шкафа есть?',question,experience,'provided'))

    def test_ack_cannot_smuggle_facts_promises_or_a_second_question(self):
        for reply in ('Спасибо, схема есть. Материалы и комплектующие есть?',
                      'Завтра приеду. Материалы и комплектующие есть?',
                      'Спасибо. Материалы и комплектующие в спальне есть?',
                      'Хорошо. Материалы и комплектующие есть? Адрес какой?',
                      'Спасибо. Наши материалы и комплектующие есть?'):
            self.assertFalse(verified_question(reply, self.question, self.experience(), 'provided'))

    def test_ack_requires_a_real_client_answer_to_delivered_staff_speech(self):
        for change in ('first', 'failed', 'system', 'question'):
            messages=history()
            if change=='first': messages=messages[:1]
            elif change=='failed': messages[1]['delivery_status']='failed'
            elif change=='system': messages[-1]['sender_type']='system'
            else: messages[-1]['body']='А схема нужна?'
            style=self.experience(messages)
            self.assertFalse(verified_question('Спасибо. Материалы и комплектующие есть?', self.question, style, 'provided'))

    def test_an_unrequested_room_or_negated_other_object_cannot_supply_subject_words(self):
        messages=history();messages[0]['body']='Нужно собрать комод на кухне. Шкаф собирать не нужно.'
        style=self.experience(messages)
        for reply in ('Материалы и комплектующие для кухни есть?', 'Материалы и комплектующие для шкафа есть?'):
            self.assertFalse(verified_question(reply,self.question,style,'provided'))

    def test_missing_review_or_experience_never_expands_the_wording_contract(self):
        self.assertFalse(verified_question('Спасибо. Материалы и комплектующие есть?',self.question,None,'provided'))
        self.assertFalse(verified_question('Спасибо. Материалы и комплектующие есть?',self.question,self.experience(),'invalid'))

    def test_actual_task_has_style_bounds_instead_of_a_copied_reply_example(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive=root/'source.sqlite3'
            create_index(archive,[dict(cid='different-case',case=1,client_group='different-group',direction='mnc',
                metadata={'experienced_authors':['Сотрудник']},review_flags=dict(text_reviewed=True,media_reviewed=True),
                messages=[dict(id='old-in',direction='in',sender_type='client',text='Нужно собрать шкаф'),
                          dict(id='old-out',direction='out',sender_type='operator',author='Сотрудник',delivery='delivered',text='Материалы и комплектующие есть?')])],approved_cids=['different-case'])
            with patch.dict(os.environ,LEADBOT_PERSONAL_OWNER_ID='owner205',LEADBOT_PERSONAL_AUTO_AVAILABLE='0',LEADBOT_EXPERIENCED_DB=str(archive),LEADBOT_EXPERIENCE_REQUIRED='1'):
                app=Assistant(Store(root/'db'));ctx=dict(convId='current205',dir='mnc',city='Чита',partner='7',channel='avito',itemTitle='Сборка мебели',accountTitle='Учебный мастер МНЧ',messages=history())
                prepared,status=app.handle(dict(owner='owner205',action='preview',wording_mode='neural_review',ctx=ctx))
                self.assertEqual(status,200);self.assertTrue(prepared['pending_model'])
                task=json.loads(prepared['model_task']['task']);self.assertNotIn('example',task['output_contract'])
                self.assertNotIn('reply',task['output_contract']['decision_states'][0])
                self.assertTrue(task['experience_context']['conversation_style']['acknowledgement_allowed'])
                candidate=dict(reply='Спасибо. Материалы и комплектующие для шкафа есть?',needs_operator=False,
                    context_review=dict(last_intent='Сборка шкафа-купе',latest_client_meaning='Схема сборки есть.',selected_step_fits=True,evidence_ids=['a','q','work'],note='Комплектность ещё не сообщалась.'))
                out,status=app.handle(dict(owner='owner205',action='finalize',request_id=prepared['request_id'],revision=prepared['revision'],candidate=candidate))
                self.assertEqual(status,200);self.assertEqual(out['validation'],[])
                self.assertEqual(out['reply'],candidate['reply']);self.assertEqual(out['response_source'],'model')
                ctx['messages'] += [dict(id='out-materials',direction='out',sender_type='bot',delivery_status='delivered',body=out['reply']),
                                    dict(id='kit',direction='in',sender_type='client',body='Все детали и крепёж уже в наличии.')]
                prepared,status=app.handle(dict(owner='owner205',action='preview',wording_mode='neural_review',ctx=ctx))
                self.assertEqual(status,200);self.assertTrue(prepared['pending_model'])
                task=json.loads(prepared['model_task']['task']);self.assertEqual(task['decision']['next_question']['kind'],'phone')
                meaning=task['output_contract'].get('fixed_latest_client_meaning') or 'Все детали и крепёж в наличии.'
                candidate=dict(reply='Хорошо. Напишите, пожалуйста, ваш номер для связи.',needs_operator=False,
                    context_review=dict(last_intent='Сборка шкафа-купе',latest_client_meaning=meaning,selected_step_fits=True,
                                        evidence_ids=['kit','out-materials'],note='Клиент подтвердил комплектность, номер не сообщался.'))
                out,status=app.handle(dict(owner='owner205',action='finalize',request_id=prepared['request_id'],revision=prepared['revision'],candidate=candidate))
                self.assertEqual(status,200);self.assertEqual(out['validation'],[])
                self.assertEqual(out['reply'],candidate['reply']);self.assertEqual(out['response_source'],'model')
