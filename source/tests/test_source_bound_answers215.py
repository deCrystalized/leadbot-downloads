"""Actual answers survive questions, partial inventories and later corrections."""
import copy
import unittest

import qualification_state as qs
import assistant_policy as policy
import contact_facts
from test_history_intake106 import assess, known


def rows(*pairs):
    return [dict(id='answer-'+str(i), direction=d, body=t,
                 sender_type='client' if d == 'in' else 'operator',
                 **({'delivery_status': 'delivered'} if d == 'out' else {}))
            for i, (d, t) in enumerate(pairs)]


def office():
    return rows(('in', 'В квартире на ноутбуке нужны Word и Excel.'),
                ('out', 'Вы будете принимать решение по работам и оплате и будете на месте?'),
                ('in', 'Да, решаю и оплачиваю сам. А удалённо можно?'),
                ('out', 'Работаем с выездом.'),
                ('in', 'Тогда завтра после обеда, я буду дома и сам оплачу. А сколько займёт установка?'))


class Responsibility215Tests(unittest.TestCase):
    def test_actual_split_components_not_a_repeated_whole_question(self):
        state = qs.inspect(office())
        self.assertEqual(state['decision_maker']['status'], 'answered')
        self.assertEqual(set(state['decision_maker']['components']), {'decision', 'payment', 'presence'})
        self.assertEqual(state['decision_maker']['components']['decision']['message_id'], 'answer-2')
        self.assertEqual(state['decision_maker']['components']['presence']['message_id'], 'answer-4')

    def test_later_contact_and_negative_windows_scope_keep_responsibility(self):
        ms = office() + rows(('out', 'Номер для связи подскажите?'),
                            ('in', 'Windows переустанавливать не нужно, только Word и Excel.'))
        self.assertEqual(qs.inspect(ms)['decision_maker']['status'], 'answered')

    def test_only_payment_does_not_establish_decision_or_presence(self):
        state = qs.inspect(rows(('in', 'Нужно собрать комод в квартире. Я сам оплачу.')))['decision_maker']
        self.assertNotEqual(state['status'], 'answered')
        question = qs.question('decision_maker', {'decision_maker': state})
        self.assertIn('решени', question['question'])
        self.assertIn('месте', question['question'])
        self.assertNotIn('оплат', question['question'])

    def test_decision_and_payment_require_only_the_missing_presence(self):
        state = qs.inspect(office()[:3])['decision_maker']
        self.assertNotEqual(state['status'], 'answered')
        question = qs.question('decision_maker', {'decision_maker': state})
        self.assertNotIn('оплат', question['question'])
        self.assertNotIn('решени', question['question'])
        self.assertIn('месте', question['question'])

    def test_component_withdrawal_cannot_keep_old_complete_confirmation(self):
        for text in ('Я не буду на месте.', 'Оплачивать буду не я.', 'Решение принимаю не я.'):
            ms = office() + rows(('in', text))
            self.assertNotEqual(qs.inspect(ms)['decision_maker']['status'], 'answered', text)

    def test_uncertain_presence_does_not_become_confirmation(self):
        ms = office()[:3] + rows(('in', 'Возможно, буду на месте.'))
        self.assertNotEqual(qs.inspect(ms)['decision_maker']['status'], 'answered')

    def test_later_different_decision_actor_revokes_only_the_changed_component(self):
        ms = office() + rows(('in', 'Решение теперь принимает муж.'))
        state = qs.inspect(ms)['decision_maker']
        self.assertNotEqual(state['status'], 'answered')
        self.assertEqual(state['components']['decision']['status'], 'withdrawn')
        self.assertEqual(state['components']['payment']['status'], 'confirmed')

    def test_unrelated_fault_negation_does_not_revoke_explicit_components(self):
        ms = rows(('in', 'Компьютер не включается, я решаю, сам оплачу и буду на месте.'))
        self.assertEqual(qs.inspect(ms)['decision_maker']['status'], 'answered')

    def test_failed_or_foreign_staff_question_is_not_observed_answer_evidence(self):
        for change in ({'out_pending': True}, {'sender_type': 'system'}, {'delivery_status': 'failed'}):
            ms = rows(('out', qs.SPECS['place'][0]), ('in', 'В квартире.'))
            ms[0].update(change)
            self.assertEqual(qs.observed_question_answers(ms), [])

    def test_foreign_quoted_and_question_components_are_not_own_confirmation(self):
        for text in ('Муж сказал: «Решаю, оплачиваю сам и буду на месте».',
                     'Если я решаю и оплачиваю сам, нужно быть на месте?',
                     'Я буду на месте?', 'Сосед сам решает и оплачивает и будет на месте.'):
            self.assertNotEqual(qs.inspect(rows(('in', text)))['decision_maker']['status'], 'answered', text)

    def test_system_staff_failed_and_pending_cannot_supply_presence(self):
        for patch in ({'direction': 'system', 'sender_type': 'system'},
                      {'direction': 'out', 'sender_type': 'operator'},
                      {'sender_type': 'system'}, {'delivery_status': 'failed'}, {'out_pending': True}):
            ms = office()[:3] + rows(('in', 'Я буду на месте.'));ms[-1].update(patch)
            self.assertNotEqual(qs.inspect(ms)['decision_maker']['status'], 'answered', patch)

    def test_new_enquiry_cannot_reuse_old_responsibility(self):
        ms = office() + rows(('in', 'Новая заявка: собрать шкаф у соседа.'))
        self.assertNotEqual(qs.inspect(ms)['decision_maker']['status'], 'answered')

    def test_home_is_not_presence_at_an_organisation(self):
        ms = rows(('in', 'Нужно установить программы в организации. Я решаю и сам оплачу.'),
                  ('in', 'Я буду дома.'))
        self.assertNotEqual(qs.inspect(ms)['decision_maker']['status'], 'answered')

    def test_purchase_choice_is_not_a_service_decision(self):
        ms = rows(('in', 'Я решаю, какой ноутбук купить. Я оплачу работу и буду на месте.'))
        self.assertNotEqual(qs.inspect(ms)['decision_maker']['status'], 'answered')

    def test_payment_for_parts_does_not_confirm_payment_for_work(self):
        ms = rows(('in', 'Решение принимаю я, буду на месте. Я оплачу крепёж.'))
        self.assertNotEqual(qs.inspect(ms)['decision_maker']['status'], 'answered')

    def test_yes_binds_only_the_components_of_the_delivered_question(self):
        ms = rows(('out', 'Вы принимаете решение и оплачиваете работу?'), ('in', 'Да'))
        state = qs.inspect(ms)['decision_maker']
        self.assertNotEqual(state['status'], 'answered')
        self.assertIn('месте', qs.question('decision_maker', {'decision_maker': state})['question'])

    def test_full_delivered_compound_yes_and_old_explicit_statement_stay_supported(self):
        for ms in [rows(('out', qs.SPECS['decision_maker'][0]), ('in', 'Да')),
                   rows(('in', 'Я принимаю решение, я оплачу и буду на месте.'))]:
            self.assertEqual(qs.inspect(ms)['decision_maker']['status'], 'answered')

    def test_shared_future_subject_applies_to_named_decision_and_payment_only(self):
        ms = rows(('in', 'Наличными, оплачивать и принимать решение буду я, буду на месте.'))
        self.assertEqual(qs.inspect(ms)['decision_maker']['status'], 'answered')

    def test_future_explicit_service_responsibility_does_not_require_one_word_order(self):
        ms = rows(('in', 'Я буду принимать решение и оплачивать работу. Я буду присутствовать.'))
        self.assertEqual(qs.inspect(ms)['decision_maker']['status'], 'answered')


class ObservedAnswer215Tests(unittest.TestCase):
    def test_short_models_question_links_to_actual_delivered_printer_question(self):
        ms = rows(('in', 'В организации настроить печать с компьютеров на два принтера.'),
                  ('out', 'А какими у вас прпинтеры?'), ('in', 'Модели?'))
        out = assess(ms, known('kp', 'Настройка принтеров'))
        reply = out.get('forced_reply') or policy.compose_reply(out.get('next_question', {}).get('question', ''), out)
        self.assertRegex(reply.lower(), 'марк|модел')
        self.assertNotRegex(reply.lower(), 'номер|оплат|решени')

    def test_clarification_does_not_bind_failed_or_foreign_question(self):
        for change in ({'delivery_status': 'failed'}, {'out_pending': True},
                       {'direction': 'system', 'sender_type': 'avito'}):
            ms = rows(('in', 'Нужно настроить принтер.'), ('out', 'Какие принтеры?'), ('in', 'Модели?'))
            ms[1].update(change)
            self.assertIsNone(qs.client_question_clarification(ms))

    def test_new_enquiry_and_foreign_quote_are_not_metaclarifications(self):
        for text in ('Новая заявка. Модели?', 'Мастер спросил: «Модели?»', 'Какая модель лучше?'):
            ms = rows(('out', 'Какие принтеры?'), ('in', text))
            self.assertIsNone(qs.client_question_clarification(ms))

    def test_actual_type_answer_has_source_ids_and_no_geographic_assertion(self):
        ms = rows(('in', 'Нужно собрать комод.'), ('out', qs.SPECS['place'][0]),
                  ('in', 'В квартире. А недостающее привезёте?'))
        before = copy.deepcopy(ms)
        context = qs.observed_question_answers(ms)
        self.assertEqual(ms, before)
        item = context[-1]
        self.assertEqual(item['question_message_id'], 'answer-1')
        self.assertEqual(item['answer_message_id'], 'answer-2')
        self.assertIn('place', item['question_topics'])
        self.assertEqual(item['answer_scope'], 'worksite_type_not_geographic_location')
        self.assertFalse(item['independent_model_understanding'])

    def test_short_metaquestion_is_not_recorded_as_an_answered_model(self):
        ms = rows(('out', 'Марка и модель принтера?'), ('in', 'Модели?'))
        self.assertNotEqual(qs.inspect(ms)['model']['status'], 'answered')
        self.assertEqual(qs.observed_question_answers(ms)[-1]['answer_scope'], 'client_clarification_question')


class PartialMaterials215Tests(unittest.TestCase):
    def test_named_plinths_are_preserved_without_claiming_all_accessories(self):
        for text in ('Есть плинтуса.', 'Плинтусы уже куплены.', 'Плинтус у меня есть.'):
            ms = rows(('in', 'Нужен монтаж плинтуса в квартире.'), ('out', 'У вас всё в наличии?'), ('in', text))
            state = qs.inspect(ms)['materials']
            self.assertEqual(state['status'], 'answered', text)
            self.assertEqual(state['availability_scope'], 'client_named_item_only')
            self.assertRegex(state['availability_subject'], 'плинтус')
            facts = contact_facts.collect(ms, known())
            self.assertEqual(facts['material_availability']['scope'], 'client_named_item_only')
            self.assertNotEqual(facts['material_availability']['value'], 'yes')

    def test_actual_partial_answer_does_not_repeat_broad_materials_question(self):
        ms = rows(('in', 'Нужно установить плинтуса, квартира.'),
                  ('out', 'У вас всё в наличии?'),
                  ('in', 'Есть плинтуса и сколько будет стоить работа примерно квартира40квм?'))
        out = assess(ms)
        self.assertEqual(qs.inspect(ms)['materials']['status'], 'answered')
        self.assertNotEqual(out.get('next_question', {}).get('kind'), 'materials')
        self.assertNotRegex(' '.join(out['required_text']), '32000|40.*800')

    def test_actual_partial_stock_and_price_question_without_punctuation(self):
        text = 'Есть плинтуса и сколько будет стоить работа примерно кв40квм'
        self.assertEqual(qs.inspect(rows(('in', text)))['materials']['availability_subject'], 'плинтус')

    def test_component_value_does_not_turn_unrelated_negation_into_an_absent_person(self):
        state = qs.inspect(office())['decision_maker']
        self.assertNotIn('не пришлось', state['value'])
        out = assess(office(), known('kp', 'Установка программ'))
        self.assertNotEqual(out['action'], 'handoff')

    def test_named_item_negative_and_unknown_are_not_a_fullkit(self):
        for text in ('Плинтусов пока нет.', 'Возможно, плинтусы уже куплены.', 'Плинтуса есть?'):
            state = qs.inspect(rows(('in', 'Нужен монтаж плинтуса.'), ('in', text)))['materials']
            self.assertFalse(state['status'] == 'answered' and state.get('value') == 'yes', text)

    def test_later_named_absence_replaces_old_stock_without_global_denial(self):
        ms = rows(('in', 'Плинтуса есть.'), ('in', 'Плинтусов пока нет.'))
        state = qs.inspect(ms)['materials']
        self.assertIn('нет', state['value'])
        self.assertEqual(state['availability_scope'], 'client_named_item_only')

    def test_later_explicit_uncertainty_does_not_keep_old_stock_confirmation(self):
        ms = rows(('in', 'Плинтуса есть.'), ('in', 'Не уверен, плинтуса есть или нет.'))
        self.assertEqual(qs.inspect(ms)['materials']['status'], 'uncertain')

    def test_quoted_other_order_and_staff_stock_are_not_current_client_stock(self):
        for text in ('Сосед сказал: «Плинтуса есть».', 'Для другого заказа плинтуса куплены.',
                     'У мастера плинтуса есть.'):
            state = qs.inspect(rows(('in', 'Нужен монтаж плинтуса.'), ('in', text)))['materials']
            self.assertNotEqual(state.get('availability_subject'), 'плинтус', text)

    def test_current_self_avito_call_remains_wait_without_our_callback(self):
        ms = rows(('in', 'Нужно установить плинтуса. Есть плинтуса.'),
                  ('out', 'Подскажите номер и адрес.'), ('in', 'Я сама по Авито позвоню.'))
        out = assess(ms)
        self.assertEqual(out['action'], 'wait')
        self.assertNotIn('наберу', ' '.join(out['required_text']).lower())

    def test_negated_windows_operation_does_not_replace_actual_software_request(self):
        ms = rows(('in', 'Установить Word и Excel на ноутбук.'),
                  ('out', 'Номер для связи?'),
                  ('in', 'Я не просил переустановку Windows, нужны именно Word и Excel.'))
        value = qs.inspect(ms)['software_use']['value']
        self.assertNotIn('переустанов', value.lower())
        self.assertIn('установ', value.lower())


if __name__ == '__main__':
    unittest.main()
