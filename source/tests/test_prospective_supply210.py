import unittest
import assistant_policy as policy
import qualification_state as qs
from test_history_intake106 import assess, known


def rows(text,**patch):
    return [dict(id='work',direction='in',sender_type='client',body='Нужно повесить полку в квартире. Схема есть, крепёж куплен.'),
            dict(id='staff',direction='out',sender_type='operator',body='Из какого материала стены?',delivery_status='delivered'),
            dict(id='question',direction='in',sender_type='client',body=text,**patch)]


class ProspectiveSupply210Tests(unittest.TestCase):
    def test_current_conditional_question_about_worker_supply_gets_uncertainty_answer(self):
        ms=rows('Стена кирпичная. Полка 80 сантиметров. А если крепежа окажется мало, мастер привезёт свой?')
        out=assess(ms,known('mnc','Мастер на час'))
        self.assertIn('По материалам смогу сориентировать после осмотра.',out['required_text'])
        self.assertNotEqual(out['action'],'handoff')
        self.assertNotEqual(qs.inspect(ms)['materials'].get('value'),'no')

    def test_current_service_subject_and_future_supply_verbs_are_not_second_person_only(self):
        for text in ('Если крепежа окажется мало, ваш мастер привезёт свой?',
                     'Крепёж есть. Специалист возьмёт крепёж с собой?',
                     'Если деталей не хватит, мастер сможет купить недостающее?',
                     'Если нужны будут материалы, ваш специалист сможет доставить их?'):
            with self.subTest(text=text):
                self.assertIn('По материалам смогу сориентировать после осмотра.',policy.service_expectation_questions(rows(text)))

    def test_statement_or_past_worker_action_is_not_new_inventory_question(self):
        for text in ('Мастер привёз крепёж.', 'Мастер привезёт крепёж.',
                     'Вчера мастер покупал детали.', 'Мастер не нашёл деталь?'):
            with self.subTest(text=text):self.assertEqual(policy.service_expectation_questions(rows(text)),[])

    def test_named_foreign_worker_is_not_our_supply(self):
        for text in ('Мой мастер привезёт крепёж?', 'Другой мастер купит детали?',
                     'Прежний специалист доставит материалы?',
                     'Сосед спросил: «Ваш мастер привезёт крепёж?»',
                     'Мастер сказал: «Специалист привезёт детали?»'):
            with self.subTest(text=text):self.assertEqual(policy.service_expectation_questions(rows(text)),[])

    def test_client_not_requesting_supply_and_worker_negation_do_not_confirm_it(self):
        for text in ('Не спрашиваю, мастер привезёт ли крепёж.',
                     'Не надо привозить детали.', 'Мастер не привезёт крепёж?'):
            with self.subTest(text=text):self.assertEqual(policy.service_expectation_questions(rows(text)),[])

    def test_ambiguous_pronoun_or_unrelated_object_is_not_parts_supply(self):
        for text in ('Мастер привезёт свой?', 'Мастер привезёт шкаф?', 'Материалы есть. Специалист купит телевизор?'):
            with self.subTest(text=text):self.assertEqual(policy.service_expectation_questions(rows(text)),[])

    def test_incoming_staff_system_and_unfinished_client_messages_are_not_own_question(self):
        for update in (dict(sender_type='operator'),dict(sender_type='system'),dict(role='system'),
                       dict(delivery_status='failed'),dict(delivery_status='pending')):
            ms=rows('Мастер привезёт крепёж?');ms[-1].update(update)
            with self.subTest(update=update):self.assertEqual(policy.service_expectation_questions(ms),[])

    def test_parts_followup_after_our_booking_retains_existing_order_guard(self):
        ms=rows('Мастер привезёт крепёж?')
        ms[1]['body']='Хорошо, записал вас — до встречи.'
        out=assess(ms,known('mnc','Мастер на час'))
        self.assertEqual(out['action'],'handoff')
        self.assertNotIn('По материалам смогу сориентировать после осмотра.',out['required_text'])


if __name__=='__main__':unittest.main()
