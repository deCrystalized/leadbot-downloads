"""Literal fixture type answers, without reusing another object's attributes."""
import os
import tempfile
import unittest
from unittest.mock import patch

import qualification_state as qs
from assistant_store import Store
from extension_assistant import Assistant


def message(role,body,**extra):
    return dict(id=extra.pop('id',role),direction='out' if role=='operator' else
                'system' if role=='system' else 'in',sender_type=role,body=body,**extra)


class ToiletType187Tests(unittest.TestCase):
    def state(self,*messages):
        return qs.inspect(list(messages))['toilet_type']

    def context(self,reply,prompt='Напольный?',**extra):
        return self.state(message('client','Нужно заменить унитаз',id='job'),
                          message('operator',prompt,id='q',**extra),message('client',reply,id='a'))

    def test_floorstanding_reply_after_actual_question_is_not_asked_again(self):
        state=self.context('Да, напольный, старая квартира Брежневка')
        self.assertEqual(state['status'],'answered');self.assertEqual(state['message_id'],'a')
        self.assertEqual(state['question_message_id'],'q');self.assertIn('напольный',state['quote'])
        self.assertEqual(state['type_labels'],['floorstanding'])

    def test_explicit_fixture_adjective_in_either_order(self):
        for body in ('Унитаз напольный','Напольный унитаз','Обычный унитаз','Унитаз обычный',
                     'Унитаз с инсталляцией','У меня инсталляция унитаза'):
            with self.subTest(body=body):
                self.assertEqual(self.state(message('client',body))['status'],'answered')

    def test_bare_type_needs_a_real_toilet_question(self):
        for body in ('Напольный','Обычный','Инсталляция'):
            self.assertNotEqual(self.state(message('client',body))['status'],'answered')
            self.assertEqual(self.context(body,'Унитаз обычный или с инсталляцией?')['status'],'answered')

    def test_single_yes_can_confirm_only_the_actual_floorstanding_question(self):
        self.assertEqual(self.context('Да')['type_labels'],['floorstanding'])
        self.assertNotEqual(self.context('Да','Унитаз обычный или с инсталляцией?')['status'],'answered')

    def test_unknown_and_negative_are_not_positive_type(self):
        for body in ('Не знаю','Не уверен, напольный','Кажется, напольный',
                     'Не напольный','Если напольный, возьмётесь?','Напольный?'):
            with self.subTest(body=body):self.assertNotEqual(self.context(body)['status'],'answered')

    def test_a_no_does_not_guess_a_hidden_cistern(self):
        self.assertNotEqual(self.context('Нет')['status'],'answered')

    def test_trailing_doubt_and_unrelated_price_uncertainty_have_different_scope(self):
        self.assertNotEqual(self.context('Напольный, кажется')['status'],'answered')
        state=self.state(message('client','Цену не знаю, унитаз обычный'))
        self.assertEqual(state['status'],'answered');self.assertEqual(state['type_labels'],['ordinary'])

    def test_failed_and_unsent_question_cannot_supply_short_answer(self):
        for extra in (dict(out_pending=True),dict(delivery_status='failed'),dict(delivery_status='queued')):
            with self.subTest(extra=extra):self.assertNotEqual(self.context('Да',**extra)['status'],'answered')

    def test_two_questions_do_not_bind_yes(self):
        self.assertNotEqual(self.context('Да','Напольный? Уже куплен?')['status'],'answered')
        self.assertNotEqual(self.context('Да','Унитаз напольный и материалы есть?')['status'],'answered')

    def test_system_assignment_may_bridge_real_question_and_answer(self):
        state=self.state(message('client','Заменить унитаз',id='job'),message('operator','Напольный?',id='q'),
                         message('system','Диалог принят',id='take'),message('client','Да',id='answer'))
        self.assertEqual(state['message_id'],'answer');self.assertEqual(state['question_message_id'],'q')

    def test_question_needs_preexisting_client_toilet_subject(self):
        self.assertNotEqual(self.state(message('client','Нужна помощь'),message('operator','Напольный?'),
                                       message('client','Да'))['status'],'answered')

    def test_operator_system_or_bot_cannot_be_the_client_fact(self):
        for role in ('operator','system','assistant','bot','avito'):
            with self.subTest(role=role):
                self.assertNotEqual(self.state(message(role,'Унитаз напольный'))['status'],'answered')

    def test_quotes_and_someone_elses_report_are_not_client_type_assertion(self):
        for body in ('Мастер написал: «унитаз напольный»','Мастер сказал, что унитаз обычный',
                     'У соседей напольный унитаз','Вы спросили "обычный унитаз"?'):
            with self.subTest(body=body):self.assertNotEqual(self.state(message('client',body))['status'],'answered')

    def test_floor_covering_and_lamp_do_not_answer_toilet_type(self):
        for body in ('Напольное покрытие','Напольный светильник','Напольный плинтус',
                     'В квартире девятый этаж','Инсталляция программы на компьютер'):
            with self.subTest(body=body):self.assertNotEqual(self.context(body)['status'],'answered')

    def test_other_item_in_same_message_does_not_erase_actual_toilet_type(self):
        state=self.state(message('client','Унитаз напольный, а смеситель настенный'))
        self.assertEqual(state['status'],'answered');self.assertEqual(state['type_labels'],['floorstanding'])

    def test_floorstanding_does_not_imply_no_installation_or_hidden_tank(self):
        state=self.state(message('client','Напольный унитаз с инсталляцией'))
        self.assertEqual(state['status'],'answered')
        self.assertEqual(set(state['type_labels']),{'floorstanding','installation'})
        self.assertNotIn('ordinary',state['type_labels'])

    def test_positive_installation_after_negated_ordinary(self):
        self.assertEqual(self.context('Не обычный, с инсталляцией')['type_labels'],['installation'])

    def test_old_fixture_type_not_transferred_to_explicit_new_one(self):
        state=self.state(message('client','Старый унитаз напольный. Новый с инсталляцией.'))
        self.assertEqual(state['type_labels'],['installation']);self.assertNotIn('floorstanding',state['type_labels'])

    def test_explicit_correction_and_unknown_replace_prior_type(self):
        initial=message('client','Унитаз обычный',id='old')
        corrected=self.state(initial,message('operator','Унитаз какой?',id='q'),
                             message('client','Ошибся, унитаз с инсталляцией',id='new'))
        self.assertEqual(corrected['message_id'],'new');self.assertEqual(corrected['type_labels'],['installation'])
        unknown=self.state(initial,message('operator','Унитаз какой?',id='q'),
                           message('client','Не знаю тип, ошибся',id='new'))
        self.assertNotEqual(unknown['status'],'answered')

    def test_new_enquiry_cannot_reuse_the_earlier_fixture_type(self):
        # The same established current-enquiry boundary used by price/qualification.
        with patch('assistant_prices.current_enquiry_messages',side_effect=lambda rows:rows[1:]):
            self.assertNotEqual(self.state(message('client','Унитаз обычный'),
                                           message('client','Теперь другой заказ, заменить унитаз'))['status'],'answered')

    def test_type_answer_does_not_prove_material_stock(self):
        rows=[message('client','Заменить унитаз'),message('operator','Напольный?'),message('client','Да, напольный')]
        self.assertNotEqual(qs.inspect(rows)['materials']['status'],'answered')

    def test_shared_preview_moves_on_without_skipping_other_conditions(self):
        with tempfile.TemporaryDirectory()as tmp,patch.dict(os.environ,LEADBOT_PERSONAL_OWNER_ID='toilet187',LEADBOT_PERSONAL_AUTO_AVAILABLE='0'):
            app=Assistant(Store(tmp+'/db'))
            ctx=dict(convId='synthetic-toilet-type187',dir='mnc',city='Ковров',partner='7',channel='avito',
                     accountTitle='Учебный МНЧ',itemTitle='Сантехник',origin='В75',
                     messages=[message('client','Сколько стоит заменить старый унитаз на новый?',id='job'),
                               message('operator','Напольный?',id='q'),message('client','Да, напольный',id='answer')])
            out,status=app.handle(dict(owner='toilet187',action='preview',wording_mode='neural_review',ctx=ctx))
            self.assertEqual(status,200);self.assertTrue(out['pending_model'])
            self.assertEqual(out['qualification']['toilet_type']['status'],'answered')
            import json
            task=json.loads(out['model_task']['task'])
            self.assertNotEqual(task['decision'].get('next_question',{}).get('kind'),'toilet_type')
            self.assertFalse(out['auto_enabled']);self.assertFalse(out['lead']['can_create_automatically'])


if __name__=='__main__':unittest.main()
