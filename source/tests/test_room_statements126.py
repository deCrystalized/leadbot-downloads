"""Client work location, with useful synthetic native next-step checks."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import qualification_state
from assistant_store import Store
from extension_assistant import Assistant


def client(text, ident='client-room'):
    return dict(id=ident, direction='in', sender_type='client', body=text)


class RoomStatement126Tests(unittest.TestCase):
    def test_client_preposition_variants_are_the_same_known_room(self):
        for phrase in ['в кухне', 'на кухне', 'для кухни', 'в ванной комнате']:
            with self.subTest(phrase=phrase):
                text = 'Нужно заменить шланг '+phrase+'. Шланг имеется.'
                row = qualification_state.inspect([client(text)])['room']
                self.assertEqual(row['status'], 'answered')
                self.assertEqual(row['message_id'], 'client-room')
                self.assertEqual(row['quote'], text)
                self.assertIn(phrase.removesuffix(' комнате'), row['value'])

    def test_negative_location_is_not_a_positive_work_location(self):
        for text in ['Только не на кухне.', 'Не в кухне.']:
            self.assertEqual(qualification_state.inspect([client(text)])['room']['status'], 'missing')
        row = qualification_state.inspect([client('Не на кухне, а в ванной.')])['room']
        self.assertEqual(row['status'], 'answered')
        self.assertIn('ванной', row['value'])
        self.assertNotIn('кухн', row['value'])

    def test_quoted_alternative_or_conditional_does_not_resolve_the_room(self):
        for text in ['На кухне или в ванной?',
                     'Мастер спросил: «На кухне или в ванной?»',
                     'Мастер сказал: «В кухне».',
                     'Если решим делать в кухне, напишу.',
                     'У меня кухонный смеситель.']:
            with self.subTest(text=text):
                self.assertEqual(qualification_state.inspect([client(text)])['room']['status'], 'missing')

    def test_price_question_does_not_erase_an_explicit_room(self):
        for text in ['Нужно заменить шланг в кухне. Сколько стоит?',
                     'Шланг заменить в кухне, сколько будет стоить?']:
            row = qualification_state.inspect([client(text)])['room']
            self.assertEqual(row['status'], 'answered')
            self.assertIn('кухне', row['value'])

    def test_staff_location_is_not_client_evidence(self):
        row = qualification_state.inspect([
            dict(id='staff', direction='out', sender_type='operator', body='Работа в кухне.')])['room']
        self.assertEqual(row['status'], 'missing')

    def test_a_short_actual_answer_to_the_staff_room_question_is_retained(self):
        row = qualification_state.inspect([
            dict(id='staff', direction='out', sender_type='operator',
                 delivery_status='delivered', body='Работа нужна на кухне или в ванной?'),
            client('Кухня')])['room']
        self.assertEqual(row['status'], 'answered')
        self.assertEqual(row['message_id'], 'client-room')

    def test_named_hose_availability_keeps_only_the_client_item(self):
        for text in ['Шланг имеется.', 'Шланг уже куплен.', 'Подводка есть.',
                     'Шланга нет.', 'У меня шланг есть.']:
            with self.subTest(text=text):
                row = qualification_state.inspect([client(text)])['materials']
                self.assertEqual(row['status'], 'answered')
                self.assertEqual(row['quote'], text)
                self.assertEqual(row['availability_scope'], 'client_named_item_only')
                self.assertEqual(row['message_id'], 'client-room')

    def test_other_people_questions_and_future_hoses_are_not_client_inventory(self):
        for text in ['Шланг имеется?', 'У вас шланг есть?',
                     'Сосед сказал: «Шланг имеется».',
                     'В инструкции написано: «Подводка есть».',
                     'Если шланг имеется, попробую сам.',
                     'Шланг я куплю позже.', 'У соседа шланг есть.',
                     'Мастер сказал, что шланг куплен.']:
            with self.subTest(text=text):
                self.assertEqual(qualification_state.inspect([client(text)])['materials']['status'], 'missing')

    def test_named_hose_work_is_known_without_inventing_a_job_total(self):
        for text in ['Нужно заменить шланг к смесителю.', 'Нужно сменить шланчик на кухне.',
                     'Нужно заменить два шланга.', 'Нужно заменить 2 шланга.']:
            with self.subTest(text=text):
                row = qualification_state.inspect([client(text)])['volume']
                self.assertEqual(row['status'], 'answered')
                self.assertEqual(row['quote'], text)
                self.assertEqual(row['volume_scope'], 'client_named_hose_only')
                self.assertEqual(row['message_id'], 'client-room')

    def test_inventory_quote_and_uncertain_hose_count_are_not_requested_volume(self):
        for text in ['Два шланга имеются.', 'Нужно заменить несколько шлангов.',
                     'Шланг менять не нужно.', 'Мастер сказал: «Нужно заменить шланг».',
                     'Если нужно заменить шланг, напишу.']:
            with self.subTest(text=text):
                self.assertEqual(qualification_state.inspect([client(text)])['volume']['status'], 'missing')


class RoomStatement126NativeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='room-owner',
                         LEADBOT_PERSONAL_AUTO_AVAILABLE='0')
        env.start()
        self.addCleanup(env.stop)
        self.app = Assistant(Store(temp.name+'/db'))

    def prepare(self, text):
        ctx = dict(convId='synthetic-room126', city='Нефтеюганск', dir='mnc',
                   channel='avito', partner='7', origin='С1', accountTitle='Учебный мастер МНЧ',
                   itemTitle='Услуги сантехника', messages=[client(text)])
        value, code = self.app.handle(dict(owner='room-owner', action='preview',
                                          wording_mode='neural_review', ctx=ctx))
        self.assertEqual(code, 200)
        self.assertTrue(value.get('pending_model'), value.get('reason'))
        self.assertFalse(value['auto_enabled'])
        return value, json.loads(value['model_task']['task'])

    def test_native_named_hose_job_does_not_repeat_the_known_room(self):
        prepared, task = self.prepare('Нужно заменить шланг на подачу воды к смесителю в кухне. Шланг имеется.')
        candidate = dict(reply=task['proposed_reply'], needs_operator=False, context_review=dict(
            last_intent='Заменить один шланг к кухонному смесителю; шланг есть у клиента.',
            latest_client_meaning='Клиент сообщил работу, место и наличие шланга.',
            selected_step_fits=True, evidence_ids=['client-room'],
            note='Ручной синтетический review, без обещания совместимости, деталей или результата.'))
        final, code = self.app.handle(dict(owner='room-owner', action='finalize',
            request_id=prepared['request_id'], revision=prepared['revision'], candidate=candidate))
        self.assertEqual(code, 200)
        self.assertEqual(final['validation'], [])
        self.assertTrue(final['reply'])
        self.assertNotIn('кухне или в ванной', final['reply'])
        self.assertNotIn('Материалы и комплектующие есть', final['reply'])
        self.assertNotIn('Какой объём работ', final['reply'])
        self.assertFalse(final['auto_enabled'])
        self.assertFalse(final['lead']['can_create_automatically'])

    def test_native_unknown_room_still_gets_the_specific_question(self):
        prepared, task = self.prepare('Нужно заменить шланг к смесителю. На кухне или в ванной — пока не решили.')
        self.assertEqual(task['decision']['next_question']['question'], 'Работа нужна на кухне или в ванной?')
        # No model was called; close only this local pending fixture.
        value, code = self.app.handle(dict(owner='room-owner', action='finalize',
            request_id=prepared['request_id'], revision=prepared['revision'], candidate={}, model_failure='format'))
        self.assertEqual(code, 200)
        self.assertFalse(value['auto_enabled'])


if __name__ == '__main__':
    unittest.main()
