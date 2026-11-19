"""The client can answer the kit question without copying our vocabulary."""
import os
import tempfile
import unittest
from unittest.mock import patch

import qualification_state as qs
from assistant_store import Store
from extension_assistant import Assistant


def client(text, mid):
    return dict(id=mid, direction='in', sender_type='client', body=text)


def staff(text='Материалы и комплектующие есть?', **extra):
    return dict(id='question', direction='out', sender_type='bot', body=text,
                delivery_status='delivered', **extra)


class ContextualMaterials205Tests(unittest.TestCase):
    def history(self, answer, **question):
        return [client('Нужно собрать шкаф-купе', 'work'), staff(**question), client(answer, 'answer')]

    def test_complete_parts_and_fasteners_answers_delivered_furniture_kit_question(self):
        for answer in ('Все детали и крепёж уже в наличии.', 'Да, все детали и крепеж есть.',
                       'Весь комплект деталей и крепежа куплен.'):
            with self.subTest(answer=answer):
                value = qs.inspect(self.history(answer))['materials']
                self.assertEqual(value['status'], 'answered')
                self.assertEqual(value['value'], 'yes')
                self.assertEqual(value['message_id'], 'answer')
                self.assertEqual(value['question_message_id'], 'question')
                self.assertEqual(value['quote'], answer)

    def test_partial_missing_future_doubt_and_question_do_not_establish_complete_kit(self):
        for answer in ('Не все детали и крепёж есть', 'Все детали есть, но крепежа нет',
                       'Все детали и крепёж завтра куплю', 'Деталь и крепёж есть',
                       'Наверное, все детали и крепёж есть', 'Все детали и крепёж есть?',
                       'У вас все детали и крепёж есть?', 'Все детали и крепёж заказаны'):
            with self.subTest(answer=answer):
                self.assertNotEqual(qs.inspect(self.history(answer))['materials'].get('value'), 'yes')

    def test_quote_or_third_party_inventory_is_not_client_completeness(self):
        for answer in ('Мастер сказал: «Все детали и крепёж есть»',
                       'У соседа все детали и крепёж есть', 'Если все детали и крепёж есть, то соберёте?'):
            self.assertNotEqual(qs.inspect(self.history(answer))['materials'].get('value'), 'yes')

    def test_staff_system_and_avito_cannot_answer_our_inventory_question(self):
        for role in ('operator', 'system', 'avito', 'bot'):
            history = self.history('Все детали и крепёж есть')
            history[-1]['sender_type'] = role
            self.assertNotEqual(qs.inspect(history)['materials'].get('value'), 'yes')

    def test_failed_or_unsent_question_does_not_bind_terse_kit_answer(self):
        for status in ('pending', 'sending', 'failed'):
            history = self.history('Все детали и крепёж есть')
            history[1]['delivery_status'] = status
            self.assertNotEqual(qs.inspect(history)['materials'].get('value'), 'yes')

    def test_other_item_or_order_does_not_confirm_current_furniture_kit(self):
        for answer in ('Для другого шкафа все детали и крепёж есть',
                       'Все детали и крепёж для турника есть',
                       'Новый заказ: все детали и крепёж есть'):
            self.assertNotEqual(qs.inspect(self.history(answer))['materials'].get('value'), 'yes')

    def test_not_a_reply_to_model_or_instructions_or_combined_question(self):
        for question in ('Марку и модель подскажите?', 'Схема сборки есть?',
                         'Материалы и инструкция есть?', 'Материалы или комплектующие есть?'):
            self.assertNotEqual(qs.inspect(self.history('Все детали и крепёж есть', text=question))['materials'].get('value'), 'yes')

    def test_named_fasteners_for_two_objects_are_not_global_complete_inventory(self):
        history = [client('Повесить полку с зеркалом и турник', 'work'), staff(),
                   client('Для турника есть дюбели и болты, для полки ничего нет', 'answer')]
        self.assertNotEqual(qs.inspect(history)['materials'].get('value'), 'yes')

    def test_furniture_kit_does_not_establish_materials_for_separate_plumbing(self):
        history = [client('Нужно собрать шкаф и заменить смеситель', 'work'), staff(),
                   client('Все детали и крепёж есть', 'answer')]
        self.assertNotEqual(qs.inspect(history)['materials'].get('value'), 'yes')

    def test_short_yes_stays_bound_to_natural_parts_fasteners_question(self):
        history=self.history('Да', text='Все детали и крепёж для шкафа в комплекте?')
        value=qs.inspect(history)['materials']
        self.assertEqual(value['status'],'answered');self.assertEqual(value['value'],'yes')
        self.assertEqual(value['question_message_id'],'question')
        self.assertEqual(value['message_id'],'answer')

    def test_parts_question_about_contractor_does_not_confirm_client_kit(self):
        history=self.history('Да',text='У мастера все детали и крепёж в комплекте?')
        self.assertNotEqual(qs.inspect(history)['materials'].get('value'),'yes')

    def test_real_continuation_moves_past_materials_in_reply_and_checklist(self):
        history = [client('Здравствуйте! Нужен мастер, чтобы собрать шкаф-купе.', 'work'),
                   dict(staff('Схема или инструкция сборки есть?'), id='schema'),
                   client('Схема есть.', 'schema-answer'), staff(),
                   client('Все детали и крепёж уже в наличии.', 'answer')]
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ,
                LEADBOT_PERSONAL_OWNER_ID='synthetic205', LEADBOT_PERSONAL_AUTO_AVAILABLE='0'):
            app = Assistant(Store(temp + '/db'))
            ctx = dict(convId='synthetic205', dir='mnc', city='Чита', partner='7', channel='avito',
                       itemTitle='Сборка мебели', accountTitle='Учебный мастер МНЧ', messages=history)
            for action in ('preview', 'checklist'):
                out, status = app.handle(dict(owner='synthetic205', action=action, wording_mode='reviewed', ctx=ctx))
                self.assertEqual(status, 200)
                self.assertFalse(out['auto_enabled'])
                if action == 'preview':
                    self.assertNotRegex(out['reply'].lower(), r'материал|комплектующ')
                    self.assertNotEqual(out['action'], 'handoff')
                else:
                    row = next(x for x in out['results'] if x['key'] == 'materials')
                    self.assertTrue(row['done'])
                    self.assertEqual(row['answer'], 'yes')
                    self.assertEqual(row['evidence'][0]['message_id'], 'answer')
