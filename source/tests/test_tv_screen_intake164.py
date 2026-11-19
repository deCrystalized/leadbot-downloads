"""Screen intake: independent hazards, exact device evidence and prior visits."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import assistant_catalog as catalog
import contact_facts
import personal_media
import qualification_state as qs
from assistant_store import Store
from extension_assistant import Assistant
from test_assistant import context, message
from test_history_intake106 import rows, known, assess


MODEL = '26PFL7332S/60'


class TvScreenIntake164Tests(unittest.TestCase):
    def source(self):
        return dict(known('kp', 'Настройка телевизора'), city='Самара', partner='723')

    def test_exact_official_model_reference_establishes_type_without_guessing_a_family(self):
        state = qs.inspect(rows(('in', 'Телевизор Philips ' + MODEL)))['tv_type']
        self.assertEqual(state['status'], 'answered')
        self.assertEqual(state['value'], 'LCD')
        self.assertEqual(state['model'], MODEL)
        self.assertEqual(state['evidence_source'], 'manufacturer_model_reference')
        self.assertIn('philips.ru/c-p/26PFL7332S_60/', state['manufacturer_source_url'])
        for text in ('Philips 26PFL7332S', 'Philips 26PFL9999S/60', 'Не Philips ' + MODEL,
                     'Монитор Philips ' + MODEL, '«Philips ' + MODEL + '». У меня Hisense'):
            with self.subTest(text=text):
                self.assertNotEqual(qs.inspect(rows(('in', text)))['tv_type']['status'], 'answered')

    def test_reviewed_label_is_a_model_source_but_staff_and_raw_attachments_are_not(self):
        incoming = rows(('in', 'Телевизор показывает синий экран'), ('in', ''))
        incoming[-1]['media_signature'] = 'label'
        personal_media.attach_observation(incoming[-1],
            dict(content_kind='device_label', device_kind='tv', model=MODEL), source='offline_reviewed_image')
        self.assertNotEqual(qs.inspect(incoming)['tv_type']['status'], 'answered')
        incoming[-1]['media_reviewed'] = True
        state = qs.inspect(incoming)['tv_type']
        self.assertEqual(state['value'], 'LCD')
        self.assertEqual(state['message_id'], 'm2')
        self.assertNotEqual(qs.inspect(rows(('out', 'Philips ' + MODEL)))['tv_type']['status'], 'answered')
        self.assertNotEqual(qs.inspect(rows(('in', 'Телевизор'), ('in', MODEL + ' или Samsung UE48H5270')))['tv_type']['status'], 'answered')
        explicit = qs.inspect(rows(('in', 'Плазменный Philips ' + MODEL)))['tv_type']
        self.assertIn('Плазмен', explicit['value'])
        self.assertNotEqual(explicit.get('evidence_source'), 'manufacturer_model_reference')

    def test_impact_denial_does_not_answer_water_and_only_missing_aspect_is_asked(self):
        state = qs.inspect(rows(('in', 'Телевизор, синий экран'),
            ('out', 'Не ударяли его?'), ('in', 'Не ударяли.')))
        self.assertEqual(state['screen_damage']['status'], 'missing')
        question = qs.question('screen_damage', state)
        self.assertRegex(question['question'], r'влаг|вод')
        self.assertNotRegex(question['question'], r'удар|роня|поврежд')
        self.assertEqual(question['unanswered_attempts'], 0)
        typo = qs.inspect(rows(('in', 'Телевизор, синий экран'), ('out', 'Не ударяли его?'), ('in', 'Не удаляли')))
        self.assertEqual(typo['screen_damage']['status'], 'missing')

    def test_water_denial_does_not_answer_impact(self):
        state = qs.inspect(rows(('in', 'Телевизор показывает синий экран'), ('in', 'Вода на экран не попадала')))
        self.assertEqual(state['screen_damage']['status'], 'missing')
        question = qs.question('screen_damage', state)['question']
        self.assertRegex(question, r'поврежд|роня|удар')
        self.assertNotRegex(question, r'влаг|вод|залив')

    def test_rear_label_request_is_not_a_tv_type_question_inside_the_word_paper(self):
        state = qs.inspect(rows(('in', 'Телевизор, синий экран'),
            ('out', 'А сзади бумажки есть фото? Не ударяли?'), ('in', 'Не ударяли.')))
        self.assertEqual(state['tv_type']['asked'], 0)
        actual = qs.inspect(rows(('in', 'Телевизор'), ('out', 'Он ЖК или плазменный?'), ('in', 'Не знаю')))
        self.assertEqual(actual['tv_type']['asked'], 1)

    def test_all_negative_and_either_positive_hazard_are_distinct(self):
        for text in ('Не роняли и не заливали', 'Не ударяли, вода не попадала',
                     'Повреждений нет, влаги нет', 'Ни ударов, ни воды', 'Без повреждений и без влаги'):
            state = qs.inspect(rows(('in', 'Телевизор, синий экран'), ('in', text)))
            self.assertEqual(state['screen_damage']['status'], 'answered', text)
            self.assertEqual(state['screen_damage']['value'], 'no', text)
        for text in ('Не ударяли, но залили водой', 'Ударили, водой не заливали'):
            ms = rows(('in', 'Телевизор, синий экран'), ('in', text))
            service = catalog.choose('\n'.join(m['body'] for m in ms), self.source())
            issue = catalog.condition_issue(service, qs.inspect(ms), '\n'.join(m['body'] for m in ms))
            self.assertIsNotNone(issue, text)
            self.assertIn('DOC-L0223', issue[1])

    def test_binary_answers_bind_only_to_the_actual_hazard_question(self):
        water = qs.inspect(rows(('in', 'Телевизор, синий экран'), ('out', 'Вода попадала на экран?'), ('in', 'Нет')))
        self.assertEqual(water['screen_damage']['status'], 'missing')
        self.assertNotRegex(qs.question('screen_damage', water)['question'], r'вод|влаг')
        both = qs.inspect(rows(('in', 'Телевизор, синий экран'),
            ('out', 'Экран повреждали или на него попадала влага?'), ('in', 'Нет')))
        self.assertEqual(both['screen_damage']['value'], 'no')
        irrelevant = qs.inspect(rows(('in', 'Телевизор, синий экран'), ('out', 'Материалы есть?'), ('in', 'Нет')))
        self.assertEqual(irrelevant['screen_damage']['status'], 'missing')
        yes = qs.inspect(rows(('in', 'Телевизор, синий экран'),
            ('out', 'Экран повреждали или на него попадала влага?'), ('in', 'Да')))
        self.assertEqual(yes['screen_damage']['value'], 'yes')
        self.assertTrue(all(x['status'] == 'missing' for x in yes['screen_damage']['hazard_facts'].values()))

    def test_one_question_is_not_counted_again_for_each_subsequent_client_message(self):
        state = qs.inspect(rows(('in', 'Телевизор, синий экран'), ('out', 'Не ударяли?'),
            ('in', 'Не удаляли'), ('in', 'Когда сможете?'), ('in', 'Не ударяли.')))
        self.assertEqual(state['screen_damage']['hazard_facts']['impact']['asked'], 1)
        self.assertEqual(qs.question('screen_damage', state)['unanswered_attempts'], 0)

    def test_a_question_hypothesis_or_another_device_is_not_a_screen_hazard_fact(self):
        for text in ('Может вода попала?', 'Вы ударили телевизор?', 'Если экран повредили, что делать?',
                     'Не знаю, попадала ли вода', 'Неизвестно попадала вода или нет',
                     'Домофон залили водой, позвоните как подъедете.', '«Не роняли и не заливали»'):
            with self.subTest(text=text):
                state = qs.inspect(rows(('in', 'Телевизор, синий экран'), ('in', text)))
                self.assertEqual(state['screen_damage']['status'], 'missing')
        positive = qs.inspect(rows(('in', 'На экран телевизора попала вода, можно отремонтировать?')))
        self.assertEqual(positive['screen_damage']['value'], 'yes')

    def test_access_note_keeps_a_separate_new_appliance_symptom_in_the_same_message(self):
        state = qs.inspect(rows(('in', 'Домофон не работает, позвоните как подъедете. Телевизор зависает.')))
        self.assertEqual(state['problem']['status'], 'answered')
        self.assertIn('завис', state['problem']['value'])
        self.assertNotIn('домофон', state['problem']['value'].lower())

    def test_screen_condition_also_applies_when_request_is_called_connection(self):
        ms = rows(('in', 'Телевизор Philips ' + MODEL + ', синий экран, нужна помощь в подключении'),
                  ('out', 'Не ударяли?'), ('in', 'Не ударяли.'))
        out = assess(ms, self.source())
        self.assertEqual(out['next_question']['kind'], 'screen_damage')
        self.assertRegex(out['next_question']['question'], r'вод|влаг')
        ordinary = catalog.choose('Нужно настроить каналы телевизора', self.source())
        self.assertNotIn('screen_damage', [q for x in ordinary['items'] for q in x['questions']])

    def test_access_intercom_does_not_replace_the_device_fault(self):
        ms = rows(('in', 'Телевизор показывает синий экран, нужна помощь в подключении'),
                  ('in', 'Домофон не работает, позвоните как подъедете, спущусь открою.'))
        state = qs.inspect(ms)
        self.assertEqual(state['problem']['message_id'], 'm1')
        self.assertNotIn('домофон', state['problem']['value'].lower())
        repair = qs.inspect(rows(('in', 'Домофон не работает, нужен ремонт')))
        self.assertEqual(repair['problem']['status'], 'answered')

    def test_next_day_availability_after_accepted_visit_requires_existing_order_review(self):
        ms = rows(('in', 'Настройка телевизора'), ('out', 'Через час-полтора удобно вам будет?'),
                  ('in', 'Конечно.'), ('out', 'Хорошо'),
                  ('in', 'Добрый день, сегодня по поводу настройки телевизора сможете подъехать?'))
        out = assess(ms, self.source())
        self.assertEqual(out['action'], 'handoff')
        self.assertTrue(out.get('existing_visit_evidence'))
        self.assertIn('VERIFY_EXISTING_APPOINTMENT', [x['id'] for x in out['decision_guards']])
        fresh = assess(rows(('in', 'Телевизор, сможете сегодня подъехать?')), self.source())
        self.assertFalse(fresh.get('existing_visit_evidence'))
        new = assess(ms[:-1] + rows(('in', 'Новая заявка: установить Windows на компьютере')), self.source())
        self.assertFalse(new.get('existing_visit_evidence'))

    def test_confirmed_closed_chat_does_not_generate_a_silence_followup(self):
        ms = rows(('in', 'Нужна настройка телевизора'), ('out', 'Сейчас вас наберу.'))
        for i, row in enumerate(ms):
            row.update(created_at=f'2026-01-01T12:0{i}:00+00:00', delivery_status='delivered',
                       sender_type='client' if row['direction'] == 'in' else 'operator')
        out = assess(ms, dict(self.source(), conversation_status='closed'))
        self.assertEqual(out['action'], 'wait')
        self.assertFalse(out.get('forced_reply'))

    def test_reference_provenance_reaches_the_common_extension_brain(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner'):
            app = Assistant(Store(tmp + '/db'))
            ctx = context([message('Телевизор Philips ' + MODEL + ', синий экран, не ударяли.')],
                          dir='kp', city='Самара', partner='723', itemTitle='Настройка телевизора')
            out, status = app.handle(dict(owner='owner', action='preview', ctx=ctx, wording_mode='neural_review'))
        self.assertEqual(status, 200)
        task = json.loads(out['model_task']['task'])
        fact = task['verified_device_facts'][0]
        self.assertEqual(fact['source'], 'manufacturer_model_reference')
        self.assertEqual(fact['value'], 'LCD')
        self.assertTrue(fact['not_client_literal_statement'])
        self.assertTrue(fact['not_diagnosis'])
        self.assertTrue(fact['not_exact_product_verification'])
        self.assertTrue(fact['exact_manufacturer_reference'])


if __name__ == '__main__':
    unittest.main()
