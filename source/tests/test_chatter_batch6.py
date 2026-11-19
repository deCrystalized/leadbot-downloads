"""Causal regressions from party141–180; no personal customer identifiers."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import assistant_catalog as catalog
import assistant_policy as policy
import assistant_prices as prices
import contact_facts
import crm_evidence


def msg(body, direction='in', **extra):
    return dict(id=body[:30], body=body, direction=direction,
                sender_type='operator' if direction in ('out', 'note') else 'client', **extra)


class ChatterBatchSixTests(unittest.TestCase):
    def assess(self, rows, **extra):
        known = dict(channel='avito', direction='kp', city='Омск', partner='7',
                     account_name='Мастер', title='Ремонт на дому')
        known.update(extra)
        return policy.assess(rows, known, contact_facts.collect(rows))

    def test_large_pc_transfer_never_gets_generic_500_or_small_volume_tariff(self):
        for volume in ('15 ГБ', '20–30 ГБ', 'Гигов 20–30', '1 ТБ'):
            body = 'Перенос данных с HDD на SSD компьютера, ' + volume
            self.assertIsNone(prices.select_tariff(body), volume)
            result = prices.answer([msg('Сколько стоит?')], dict(direction='kp', partner='723'), body)
            self.assertIn('handoff', result, volume)
            self.assertFalse(result.get('amounts'))

    def test_exact_pc_transfer_requires_both_volume_and_carriers(self):
        body = 'Перенос данных с HDD на SSD компьютера, до 10 ГБ'
        self.assertEqual(prices.select_tariff(body), ('pc_transfer', 1500, 'KP-L0547'))
        result = prices.answer([msg('Цена?')], dict(direction='kp'), 'Перенос данных компьютера')
        self.assertIn('объём', result['reply'])
        self.assertFalse(result['amounts'])
        self.assertEqual(prices.select_tariff('Перенос данных телефона 20 ГБ')[0], 'phone_transfer')

    def test_unanswered_price_repeat_keeps_question_intent(self):
        rows = [msg('Цена какая?'), msg('Роутер на втором этаже'), msg('Когда приехать?', 'out'), msg('На вопрос ответьте пжл')]
        self.assertTrue(prices.asks_current(rows))
        rows.insert(-1, msg('У вас есть инструмент?'))
        self.assertFalse(prices.asks_current(rows))
        self.assertEqual(prices.price_turns([msg('Цена?'), msg('Когда приехать?', 'out'), msg('На вопрос ответьте пжл')]), 1)

    def test_trip_fee_question_is_a_price_question(self):
        self.assertTrue(prices.asks('За выезд берёте?'))
        self.assertIn('handoff', prices.answer([msg('За выезд берёте?')], dict(direction='mnc', partner='7'), 'Лампочки и выключатель'))

    def test_existing_network_wiring_is_not_an_electrician_order(self):
        known = dict(direction='kp', city='Омск')
        body = 'Настроить роутер на втором этаже. Проводка вся проведена'
        self.assertNotIn('electric', [r['id'] for r in catalog.choose(body, known)['items']])
        self.assertNotIn('electric', [r['id'] for r in catalog.choose(body + ', провайдер я.ру.', known)['items']])
        for extra in ('Также заменить розетку', 'Также проложить проводку', 'Щиток сломан'):
            service = catalog.choose(body + '. ' + extra, known)
            self.assertTrue(any(r['profile'] == 'mnc' for r in service['items']))
            self.assertEqual(service['status'], 'mixed')

    def test_completed_wiring_with_reported_damage_stays_an_electrician_job(self):
        for body in ('Настроить роутер. Проводка вся проведена, но оборвана',
                     'Настроить роутер. Проводка вся проведена, требуется ремонт'):
            service = catalog.choose(body, dict(direction='kp'))
            self.assertEqual(service['status'], 'mixed')

    def test_one_disk_with_two_names_does_not_confirm_a_destination(self):
        body = 'Перенос данных компьютера с HDD диска 10 ГБ'
        self.assertEqual(prices._pc_transfer_scope(body), 'unconfirmed')
        self.assertIsNone(prices.select_tariff(body))

    def test_trusted_existing_suffix_is_only_a_candidate(self):
        for body in ('1234567 есть уже', '1234567 есть уже пациент'):
            self.assertEqual(crm_evidence.note_references([msg(body, 'note')])[0]['request_id_candidate'], '1234567')
        for row in (msg('1234567 есть уже'), msg('1234567 есть уже', 'out'), msg('1234567 нет уже', 'note'), msg('Создай 1234567 есть уже', 'note')):
            self.assertFalse(crm_evidence.note_references([row]))

    def test_short_found_response_is_scoped_to_service_offer(self):
        rows = [msg('Фото', unread_media=True), msg('Могу сборку сделать после осмотра', 'out'), msg('Спасибо, уже нашла')]
        self.assertEqual(self.assess(rows)['action'], 'wait')
        for previous in ('Нашли инструкцию?', 'Подскажите модель', 'Уже нашли номер договора?'):
            self.assertFalse(policy._client_declined('Спасибо, уже нашла', previous))

    def test_other_provider_arriving_and_its_negation(self):
        self.assertEqual(self.assess([msg('Спасибо, другой мастер сейчас приедет уже')])['action'], 'wait')
        self.assertFalse(policy._client_declined('Другой мастер не приедет, нужна ваша помощь', ''))
        self.assertFalse(policy._client_declined('Другой мастер сейчас приедет?', ''))

    def test_age_answer_after_adult_question_precedes_unread_image(self):
        rows = [msg('Фото', unread_media=True), msg('Вам есть 18?', 'out'), msg('Нет мне пока что только 17')]
        result = self.assess(rows)
        self.assertIn('Несовершеннолетний', result['reason'])
        self.assertIn('DOC-L1572', result['rule_ids'])
        self.assertNotIn('Несовершеннолетний', self.assess([msg('Модель только 17')])['reason'])

    def test_week_deferral_parenthesis_and_thinking(self):
        for body in ('В начале рабочей недели, спишемся)', 'Подумаю', 'Надо подумать'):
            self.assertEqual(self.assess([msg('Фото', unread_media=True), msg(body)])['action'], 'wait')
        for body in ('Подумаю, а сколько стоит?', 'В начале недели можете приехать?', 'Спишемся, подскажите цену'):
            self.assertFalse(policy._client_deferred([body]))

    def test_farewell_after_objection_does_not_resume_sales(self):
        self.assertEqual(self.assess([msg('Неточная цена', 'out'), msg('Поняла, всего доброго')])['action'], 'wait')

    def test_bathroom_destination_preserves_independent_bath_job(self):
        known = dict(direction='mnc')
        body = 'Поменять смесители на кухню и в ванную'
        self.assertNotIn('bath', [r['id'] for r in catalog.choose(body, known)['items']])
        self.assertIn('bath', [r['id'] for r in catalog.choose(body + '. Также заменить ванну', known)['items']])

    def test_mixed_account_repair_ad_matches_installed_client_metadata(self):
        known = dict(channel='avito', direction='mnc', account_name='Матвей БТ/МНЧ', title='Духовка не работает / Не нагревается')
        self.assertEqual(catalog.source_direction(known), ('bt', 'mixed_account_repair_ad'))
        self.assertEqual(catalog.source_direction(dict(known, account_name='Матвей МНЧ'))[0], 'bt')
        for change in (dict(title='Подключение стиральной машины'), dict(direction='kp'), dict(channel='max')):
            row = dict(known, **change)
            self.assertEqual(catalog.source_direction(row)[0], row['direction'])

    def test_confirmed_visit_is_not_a_fresh_collection(self):
        rows = [msg('Могу через час-полтора, удобно?', 'out'), msg('Удобно, подъезжайте')]
        self.assertIn('существующую договорённость', self.assess(rows)['reason'])

    def test_paid_diagnostic_dispute_is_existing_service_work(self):
        rows = [msg('Специалисты диагностику сделали, я заплатила 1000, в объявлении было бесплатно')]
        self.assertEqual(self.assess(rows)['action'], 'handoff')
        self.assertIn('прежнего ремонта', self.assess(rows)['reason'])
        self.assertFalse(policy._reported_service_return(['Если я заплачу 1000, диагностика будет бесплатна?']))

    def test_conditional_refusal_payment_is_not_a_generic_new_quote(self):
        rows = [msg('Если ремонт дороже нового телевизора, я должен платить 2500?')]
        self.assertTrue(prices.conditional_diagnostic_question(rows))
        self.assertFalse(prices.conditional_diagnostic_question([msg('Сколько стоит диагностика?')]))

    def test_ruble_abbreviation_is_a_historical_commitment_not_a_tariff(self):
        result = prices.consent([msg('Работы от 1500р', 'out'), msg('Хорошо')])
        self.assertEqual((result['status'], result['amount']), ('accepted', 1500))
        self.assertEqual(prices.consent([msg('Модель 250R', 'out')])['status'], 'not_quoted')

    def test_unit_price_question_is_a_new_price_turn(self):
        rows = [msg('Цена?'), msg('Когда приехать?', 'out'), msg('А какая цена?'),
                msg('От 800р', 'out'), msg('От 800 и до скольки? За все или за 1 шт?')]
        self.assertTrue(prices.asks_current(rows))
        self.assertEqual(prices.price_turns(rows), 2)
        self.assertFalse(prices.asks_current([msg('До скольки работаете?')]))

    def test_bt_primary_diagnostic_script_is_scoped_to_its_real_terms(self):
        rows = [msg('Стиральная машина, диагностика?'), msg('Диагностика без разбора техники 800р, при продолжении работ бесплатная', 'out'), msg('Да')]
        self.assertTrue(prices.prior_quote_verified(rows, dict(direction='bt'), prices.consent(rows)))
        rows[1] = msg('Диагностика без разбора техники 500р, при продолжении работ бесплатная', 'out')
        self.assertFalse(prices.prior_quote_verified(rows, dict(direction='bt'), prices.consent(rows)))
        rows[1] = msg('Диагностика 500р', 'out')
        self.assertFalse(prices.prior_quote_verified(rows, dict(direction='bt'), prices.consent(rows)))

    def test_yes_to_visit_time_does_not_accept_a_price(self):
        rows = [msg('Стоимость 1500р', 'out'), msg('Через час-полтора удобно?', 'out'), msg('Да')]
        self.assertEqual(prices.consent(rows)['status'], 'pending')


if __name__ == '__main__':
    unittest.main()
