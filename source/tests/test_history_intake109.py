"""Observed964/966/969/972 failures, with active requests and other devices as controls."""
import unittest

import assistant_catalog as catalog
import assistant_policy as policy
import qualification_state as qs
from test_history_intake106 import rows, known, assess


class HistoryIntake109Tests(unittest.TestCase):
    def test_swollen_cabinet_panels_are_repair_not_assembly(self):
        messages = rows(('in', 'Можно ли заменить взбухшие детали у шкафа после потопа?'))
        out = assess(messages)
        self.assertNotEqual(out.get('next_question', {}).get('kind'), 'instructions')
        self.assertTrue(catalog.furniture_repair_request(messages[0]['body']))
        self.assertEqual(qs.inspect(messages)['furniture_problem']['status'], 'answered')

    def test_explicit_new_assembly_is_not_erased_by_swollen_part_context(self):
        service = catalog.choose('Нужно собрать шкаф, одна панель немного разбухла', known())
        self.assertFalse(any(x.get('repair_only') for x in service['items']))

    def test_promised_photos_stop_intake(self):
        messages = rows(('in', 'Заменить разбухшие боковины шкафа'), ('out', 'Фото есть? Пришлите, пожалуйста'),
                        ('in', 'Хорошо, я поняла, вечером отправлю как сфотографируют'))
        self.assertEqual(assess(messages)['action'], 'wait')

    def test_acknowledgement_keeps_photo_wait_not_a_visit(self):
        messages = rows(('in', 'Заменить разбухшие боковины шкафа'), ('out', 'Фото есть?'),
                        ('in', 'Вечером отправлю как сфотографируют'), ('out', 'Буду ждать'), ('in', 'Договорились'))
        self.assertEqual(assess(messages)['action'], 'wait')

    def test_actual_question_is_answered_before_photo_wait(self):
        self.assertFalse(policy._client_deferred(['Как сфоткают отправлю. Вы берёте такую работу?']))

    def test_firm_current_action_is_not_a_photo_deferral(self):
        self.assertFalse(policy._client_deferred(['Фото отправлю вечером, но запишите на сегодня']))

    def test_ignition_symptom_uses_oven_listing_without_inventing_gas_type(self):
        source = dict(known('bt', 'Ремонт духовок на дому'), city='Саранск')
        out = assess(rows(('in', 'Электроподжиг сам срабатывает щелкает каждые 15-20 мин')), source)
        self.assertIn(out['action'], ('draft', 'question'))
        self.assertEqual(out['next_question']['kind'], 'gas_type')

    def test_explicit_gas_remains_refused(self):
        out = assess(rows(('in', 'Электроподжиг сам срабатывает'), ('in', 'У газовой плиты')),
                     dict(known('bt', 'Ремонт духовок на дому'), city='Саранск'))
        self.assertEqual(out['action'], 'refuse')

    def test_lighter_is_not_an_oven_from_listing(self):
        out = catalog.choose('Электроподжиг на зажигалке сломался', dict(known('bt', 'Ремонт духовок'), city='Саранск'))
        self.assertFalse(any(x['id'] == 'oven' for x in out.get('items', [])))

    def test_referral_question_after_gas_refusal_gets_profile_category(self):
        out = assess(rows(('in', 'Газовая плита, сам срабатывает поджиг'), ('out', 'Не смогу помочь'),
                          ('in', 'А какого мастера мне искать не подскажите?')), dict(known('bt', 'Ремонт духовок'), city='Саранск'))
        self.assertIn('Нужен мастер по газовому оборудованию', out['forced_reply'])

    def test_polite_goodbye_after_refusal_does_not_reopen_agreement(self):
        out = assess(rows(('in', 'Ремонт термопринтера'), ('out', 'С таким не смогу помочь'),
                          ('in', 'Понятно, спасибо, до свидания.')), known('kp', 'Ремонт принтеров'))
        self.assertEqual(out['action'], 'wait')

    def test_callout_only_question_clarifies_work_instead_of_handoff(self):
        out = assess(rows(('in', 'Доброе утро за вызов приехать сколько цена без работы?')),
                     known('mnc', 'Услуги электрика'))
        self.assertEqual(out['action'], 'price')
        self.assertEqual(out['next_question']['kind'], 'problem')
        self.assertIn('Выезд в черте города бесплатный.', out['mandatory_price']['reply'])

    def test_flickering_house_light_needs_object_not_inferred_diagnosis(self):
        out = assess(rows(('in', 'В ванне моргает свет по цене сколько будет стоить?')),
                     known('mnc', 'Услуги электрика'))
        self.assertIn(out['action'], ('draft', 'question'))
        self.assertEqual(out['next_question']['kind'], 'lighting_object')

    def test_breaker_location_does_not_answer_unknown_lighting_object(self):
        ms = rows(('in', 'В ванной моргает свет'), ('out', 'Где у вас щиток находится или автомат?'),
                  ('in', 'В подъезде'))
        out = assess(ms, known('mnc', 'Услуги электрика'))
        self.assertEqual(out['next_question']['kind'], 'lighting_object')

    def test_negated_flicker_is_not_treated_as_a_lighting_complaint(self):
        service = catalog.choose('Свет в ванной не моргает. Нужно собрать шкаф',
                                 known('mnc', 'Услуги электрика'))
        self.assertFalse(any(x['id'] == 'lighting-symptom' for x in service.get('items', [])))

    def test_explicit_fixture_uses_its_real_rules_and_led_repair_agreement(self):
        out = assess(rows(('in', 'Моргает свет в светодиодной люстре, нужен ремонт')),
                     known('mnc', 'Услуги электрика'))
        self.assertEqual(out['action'], 'handoff')

    def test_tv_indicator_is_not_house_lighting(self):
        service = catalog.choose('На телевизоре моргает свет индикатора', known('mnc', 'Услуги электрика'))
        self.assertFalse(any(x['id'] == 'lighting-symptom' for x in service.get('items', [])))


if __name__ == '__main__':
    unittest.main()
