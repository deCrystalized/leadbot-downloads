"""Current questions, actual unit prices, counts and consent stay source-bound."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import assistant_catalog
import assistant_policy as policy
import assistant_prices as prices
import contact_address
import contact_facts as facts
import qualification_state as qs
from assistant_store import Store
from extension_assistant import Assistant


JOB = ('В Чите нужно повесить на бетонную стену два телевизора:43 и55 дюймов. '
       'Кронштейны уже купили. Какая стоимость за оба вместе?')
ASK = 'Подскажите стоимость установки этих двух кронштейнов вместе с навесом телевизоров.'
ACCEPT = ('Озвученную стоимость 3000 рублей за установку двух кронштейнов и навес двух телевизоров принимаю. '
          'Меня зовут Ольга. Адрес:Чита, улица Ленина, дом12. '
          'Подходящий крепёж купим сами, его пока не проверяли.')


def row(body, mid='c', direction='in', **extra):
    return dict(id=mid, direction=direction, body=body,
                sender_type='client' if direction == 'in' else 'operator',
                delivery_status='delivered', **extra)


def known(city='Чита', direction='mnc'):
    return dict(city=city, direction=direction, partner='7', channel='avito')


def third(job=JOB):
    return [row(job, 'c1'), row('Точную стоимость скажу после осмотра.', 's1', 'out'),
            row('Мне нужно понять цену до выезда. Сколько стоит?', 'p2'),
            row('Выезд в черте города бесплатный. Стоимость работы определю после осмотра.', 's2', 'out'),
            row(ASK, 'p3')]


def quoted():
    rows = third()
    answer = prices.answer(rows, known(), JOB)
    return rows + [row(answer['reply'], 'q', 'out')], answer


class TvQuantity267Tests(unittest.TestCase):
    def test_actual_two_sets_get_two_unit_fees_and_a_total_at_third_stage(self):
        rows, answer = quoted()
        self.assertEqual(answer['tariff_kind'], 'fixed_service_total')
        self.assertEqual(answer['quantity']['count'], 2)
        self.assertEqual(answer['amounts'], [3000, 1500])
        self.assertIn('без учёта материалов', answer['reply'])
        self.assertNotIn('6000', answer['reply'])
        self.assertIn('OWNER-MNC-TV-MOUNT-PRICE-20261021', answer['rules'])

    def test_first_and_second_stage_and_single_unit_question_are_preserved(self):
        for cut in (1, 3):
            self.assertFalse(prices.answer(third()[:cut], known(), JOB)['amounts'])
        rows = third()[:-1] + [row('Сколько стоит за штуку?', 'p3')]
        self.assertEqual(prices.answer(rows, known(), JOB)['amounts'], [1500])

    def test_same_sentence_price_question_does_not_hide_explicit_work_count(self):
        job = 'Нужно повесить два телевизора, сколько стоит за оба?'
        self.assertEqual(prices.answer(third(job), known(), job)['amounts'], [3000, 1500])
        for text in ['Нужно повесить два телевизора?',
                     'Если нужно повесить два телевизора, сколько стоит за оба?',
                     'Нужно повесить два телевизора или три, сколько стоит за оба?']:
            context = facts.item_quantity_context([row(text)])
            with self.subTest(text=text):
                self.assertNotEqual((context or {}).get('objects', {}).get('tv', {}).get('current_count'), 2)

    def test_current_city_column_and_actual_direction_are_required(self):
        self.assertEqual(prices.answer(third(), known('Подольск'), JOB)['amounts'], [4000, 2000])
        for city, direction in [('', 'mnc'), ('Неизвестный город', 'mnc'), ('Чита', 'kp'), ('Чита', 'bt')]:
            self.assertNotEqual(prices.answer(third(), known(city, direction), JOB).get('tariff_kind'), 'fixed_service_total')

    def test_size_correction_is_not_a_new_quantity_or_new_worksite(self):
        rows = third() + [row('Уточнила: телевизоры 43 и 65 дюймов, не 55. Всего два.', 'asr')]
        quantity = facts.item_quantity_context(rows)['objects']['tv']
        self.assertEqual(quantity['current_count'], 2)
        self.assertFalse(quantity['total_unresolved'])
        self.assertIsNone(contact_address.parse('Уточнила: телевизоры 43 и 65 дюймов, не 55. Всего два.'))

    def test_dimensions_and_singular_model_number_do_not_establish_count(self):
        for text in ['Телевизоры 43 и 65 дюймов', 'Телевизор 43 дюйма', 'Телевизор 43', 'Телевизор 55″']:
            with self.subTest(text=text):
                self.assertFalse([m for m in facts._quantity_mentions(text) if m['object'] == 'tv'])
        self.assertEqual(facts._quantity_mentions('Телевизоров 2')[0]['count'], 2)
        self.assertEqual(facts._quantity_mentions('2 телевизора')[0]['count'], 2)

    def test_real_street_names_and_true_changed_addresses_still_work(self):
        self.assertIsNotNone(contact_address.parse('улица Телевизионная, дом43'))
        value = facts.collect([row('Адрес:улица Ленина, дом12', 'a'),
                               row('Адрес:улица Пушкина, дом14', 'b')], known())
        self.assertTrue(value['address_needs_confirmation'])
        self.assertTrue(any(c['kind'] == 'address_changed' for c in value['conflicts']))

    def test_unknown_conflicting_or_background_count_cannot_become_a_total(self):
        for text in ['Повесить телевизор43 дюйма. Цена за всё?',
                     'Если нужно повесить два телевизора, какая цена за оба?',
                     'Мастер сказал:«Повесить два телевизора». Сколько стоит?',
                     'Два телевизора стоят дома. Нужно повесить один из них.',
                     'Повесить два телевизора и собрать шкаф. Какая цена за всё?']:
            with self.subTest(text=text):
                answer = prices.answer(third(text), known(), text)
                self.assertNotEqual(answer.get('tariff_kind'), 'fixed_service_total')

    def test_failed_pending_system_and_other_actors_do_not_supply_quantity(self):
        tariff = prices.mnc_fixed_tariff(third(), known())
        for extra in [dict(out_pending=True), dict(delivery_status='failed'), dict(sender_type='operator'),
                      dict(direction='system'), dict(speaker_role='service'), dict(role='system')]:
            message = row('Повесить два телевизора', 'c1')
            message.update(extra)
            with self.subTest(extra=extra):
                self.assertIsNone(prices.tv_mount_quantity([message], tariff))

    def test_other_device_categories_are_not_added_to_tv_quantity(self):
        rows = third() + [row('У меня ещё2 принтера, они работают и не нужны в этой заявке.', 'other')]
        quantity = prices.tv_mount_quantity(rows, prices.mnc_fixed_tariff(third(), known()))
        self.assertEqual(quantity['count'], 2)


class TvConsent267Tests(unittest.TestCase):
    def test_total_and_unit_are_verified_before_and_after_named_consent(self):
        rows, _ = quoted()
        rows.append(row(ACCEPT, 'yes'))
        state = prices.consent(rows)
        self.assertEqual(state['status'], 'accepted')
        self.assertEqual(state['amount'], 3000)
        self.assertEqual(state['accepted_message_id'], 'yes')
        fixed = prices.mnc_fixed_quote(rows, known(), state)
        self.assertEqual(fixed['unit_amount'], 1500)
        self.assertEqual(fixed['quantity']['count'], 2)
        self.assertTrue(prices.prior_quote_verified(rows, known(), state))
        self.assertFalse(prices.asks_current(rows))

    def test_a_later_ready_material_reply_does_not_revive_the_accepted_price_ask(self):
        rows, _ = quoted()
        rows += [row(ACCEPT, 'yes'), row('Материалы есть у вас?', 'materials', 'out'),
                 row('Да, весь крепёж куплен и подходит к бетонной стене.', 'ready')]
        original = [dict(message) for message in rows]
        self.assertFalse(prices.asks_current(rows))
        self.assertEqual(rows, original)

    def test_wrong_arithmetic_unit_quantity_and_parts_promise_fail_verification(self):
        original, answer = quoted()
        for quote in [answer['reply'].replace('3000', '2500'),
                      answer['reply'].replace('1500', '800'),
                      answer['reply'].replace('За2', 'За3').replace('За 2', 'За 3'),
                      answer['reply'].replace('за штуку', 'за час'),
                      answer['reply'].replace('без учёта материалов', 'все материалы включены'),
                      '1500 рублей за два телевизора',
                      answer['reply'] + ' Всё сделаем за один визит.']:
            rows = original[:-1] + [row(quote, 'q', 'out'), row('Да', 'yes')]
            with self.subTest(quote=quote):
                self.assertFalse(prices.prior_quote_verified(rows, known(), prices.consent(rows)))

    def test_changed_count_city_or_requested_work_revokes_total(self):
        original, _ = quoted()
        for text in ['Поправка, нужно повесить три телевизора.', 'Ещё нужно заменить розетку.']:
            rows = original + [row('Да', 'yes'), row(text, 'changed')]
            self.assertFalse(prices.prior_quote_verified(rows, known(), prices.consent(rows)))
        rows = original + [row('Да', 'yes')]
        self.assertFalse(prices.prior_quote_verified(rows, known('Подольск'), prices.consent(rows)))

    def test_new_order_and_failed_quote_cannot_lend_the_old_total(self):
        rows, _ = quoted()
        failed = [dict(r, delivery_status='failed') if r['id'] == 'q' else r for r in rows]
        self.assertNotEqual(prices.consent(failed + [row(ACCEPT, 'yes')])['status'], 'accepted')
        changed = rows + [row('Новая заявка. Повесить один телевизор.', 'new'), row(ACCEPT, 'yes')]
        self.assertFalse(prices.prior_quote_verified(changed, known(), prices.consent(changed)))

    def test_question_negation_condition_wrong_amount_or_work_is_not_consent(self):
        rows, _ = quoted()
        for text in [ACCEPT.replace('принимаю.', 'принимаю?'),
                     ACCEPT.replace('принимаю.', 'не принимаю.'),
                     ACCEPT.replace('3000', '2500'),
                     ACCEPT.replace('принимаю.', 'принимаю, если всё включено.'),
                     ACCEPT.replace('навес двух телевизоров', 'ремонт двух телевизоров'),
                     ACCEPT.replace('двух телевизоров', 'трёх телевизоров')]:
            with self.subTest(text=text):
                self.assertNotEqual(prices.consent(rows + [row(text, 'yes')])['status'], 'accepted')

    def test_role_delivery_quotes_and_human_speech_do_not_supply_client_agreement(self):
        rows, answer = quoted()
        for extra in [dict(out_pending=True), dict(delivery_status='failed'), dict(role='system'),
                      dict(speaker_role='service'), dict(sender_type='operator'), dict(direction='system')]:
            message = row(ACCEPT, 'yes')
            message.update(extra)
            with self.subTest(extra=extra):
                self.assertFalse(prices._accepts_tv_total_terms(message, 3000, answer['reply']))
        self.assertFalse(prices._accepts_tv_total_terms(row('«' + ACCEPT + '»'), 3000, answer['reply']))

    def test_budget_or_new_explicit_price_question_is_not_erased_by_agreement(self):
        rows, _ = quoted()
        capped = rows + [row(ACCEPT + ' Бюджет не больше3000 рублей.', 'cap')]
        self.assertEqual(prices.consent(capped)['status'], 'conditional')
        question = rows + [row(ACCEPT.split('.')[0] + '. А сколько стоят материалы?', 'ask')]
        self.assertTrue(prices.asks_current(question))

    def test_unit_only_quote_and_other_tariffs_do_not_use_total_consent(self):
        self.assertFalse(prices._accepts_tv_total_terms(row(ACCEPT), 3000, '1500 рублей за штуку'))
        rows = [row('Повесить люстру', 'job'), row('1000 рублей за штуку', 'q', 'out'),
                row('Стоимость1000 рублей меня устраивает.', 'yes')]
        self.assertEqual(prices.consent(rows)['status'], 'accepted')
        self.assertFalse(prices.asks_current(rows))


class TvCurrentQuestion267Tests(unittest.TestCase):
    def preview(self, messages):
        with tempfile.TemporaryDirectory() as temporary:
            app = Assistant(Store(Path(temporary) / 'db'))
            ctx = dict(convId='synthetic-tv267-public', dir='mnc', city='Чита', partner='7',
                       channel='avito', accountTitle='Георгий МНЧ', itemTitle='Мастер на час', messages=messages)
            out, status = app.handle(dict(owner='offline', action='preview', ctx=ctx, wording_mode='reviewed'))
        self.assertEqual(status, 200)
        self.assertFalse(out['auto_enabled'])
        return out

    def test_current_trip_and_dowel_question_survives_unanswered_materials(self):
        rows = [row(JOB, 'c1'), row('Материалы и комплектующие есть?', 's1', 'out'),
                row('Мне нужно понять цену.', 'p2'), row('Материалы и комплектующие есть?', 's2', 'out'),
                row('А сам выезд по Чите платный? И если дюбели не подойдут, у мастера будут другие?', 'c4')]
        out = self.preview(rows)
        self.assertFalse(out['needs_operator'])
        self.assertIn('Выезд в черте города бесплатный.', out['reply'])
        self.assertIn('По материалам смогу сориентировать после осмотра.', out['reply'])
        self.assertNotIn('есть?', out['reply'])
        self.assertNotEqual(out['qualification']['materials']['status'], 'answered')

    def test_a_repeated_price_enquiry_does_not_repeat_the_same_inventory_question(self):
        rows = third()[:3]
        rows[1] = row('Точную стоимость скажу после осмотра. Материалы и комплектующие есть?', 's1', 'out')
        out = self.preview(rows)
        self.assertFalse(out['needs_operator'])
        self.assertNotIn('Материалы и комплектующие есть?', out['reply'])
        self.assertNotEqual(out['qualification']['materials']['status'], 'answered')

    def test_dowel_inventory_question_is_not_stock_or_a_confirmed_shortage(self):
        message = row('Если дюбели не подойдут, у мастера будут другие?', 'c4')
        self.assertIn('По материалам смогу сориентировать после осмотра.', policy.service_expectation_questions([message]))
        self.assertTrue(policy.service_expectation_violations('Привезу дюбели.'))
        for text in ['Дюбели уже куплены.', 'Другой мастер сказал:«Если дюбели не подойдут, у мастера будут другие?»',
                     'Не спрашиваю, будут ли у вас дюбели.']:
            self.assertFalse(policy.service_expectation_questions([row(text)]))

    def test_other_requires_operator_questions_keep_their_original_stop(self):
        rows = third()[:3]
        for question in [dict(kind='city', question='Где работы?', requires_operator=True),
                         dict(kind='decision_maker', question='Кто решает?', unanswered_attempts=2),
                         dict(kind='materials', question='Материалы есть?', requires_operator=True, unanswered_attempts=0)]:
            with self.subTest(kind=question['kind']), patch('assistant_qualifiers.next_question', return_value=question):
                self.assertTrue(self.preview(rows)['needs_operator'])

    def test_disclosure_and_price_question_do_not_add_an_inventory_attempt(self):
        rows = [row(JOB, 'job'), row('Материалы есть?', 'stock', 'out'), row('Уточню.', 'c2'),
                row('1500 рублей за штуку, без учёта материалов. Вас устраивает стоимость?', 'price', 'out'),
                row('Секунду.', 'wait')]
        self.assertEqual(qs.inspect(rows)['materials']['asked'], 1)
        self.assertFalse(qs.client_inventory_question(rows[-2]))

    def test_aggregate_price_finalizer_keeps_free_meaning_and_safe_veto(self):
        for kind in ['exact', 'wrong_total', 'wrong_unit', 'veto']:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                app = Assistant(Store(Path(temporary) / 'db'))
                ctx = dict(convId='synthetic-tv267-finalizer', dir='mnc', city='Чита', partner='7',
                           channel='avito', accountTitle='Георгий МНЧ', itemTitle='Мастер на час', messages=third())
                prepared, status = app.handle(dict(owner='offline', action='preview', ctx=ctx, wording_mode='neural_review'))
                self.assertEqual(status, 200)
                self.assertTrue(prepared['pending_model'])
                import json
                task = json.loads(prepared['model_task']['task'])
                reply = task['fixed_reply']
                self.assertIn('3000', reply)
                self.assertIn('1500', reply)
                if kind == 'wrong_total':
                    reply = reply.replace('3000', '2500')
                if kind == 'wrong_unit':
                    reply = reply.replace('за штуку', 'за час')
                review = dict(last_intent='Клиенту нужно повесить два телевизора на кронштейнах.',
                              latest_client_meaning='Просит стоимость установки обоих комплектов.',
                              selected_step_fits=kind != 'veto', evidence_ids=['c1', 'p3'],
                              note='Две работы по одному тарифу за комплект; материалы отдельно.')
                final, status = app.handle(dict(owner='offline', action='finalize',
                    request_id=prepared['request_id'], revision=prepared['revision'],
                    candidate=dict(reply=reply, needs_operator=kind == 'veto', context_review=review)))
                self.assertEqual(status, 200)
                self.assertFalse(final['auto_enabled'])
                if kind == 'exact':
                    self.assertEqual(final['reply'], task['fixed_reply'])
                    self.assertFalse(final['validation'])
                else:
                    self.assertFalse(final['reply'])


READY = ('Да, весь крепёж уже куплен и проверен по инструкции, подходит для бетонной стены. '
         'Кронштейны и телевизоры уже на месте.')


class TvPrerequisites267Tests(unittest.TestCase):
    def messages(self, answer=READY):
        return [row(JOB, 'job'), row('Материалы есть у вас?', 'question', 'out'), row(answer, 'ready')]

    def test_literal_tv_volume_and_named_readiness_have_sources_and_narrow_scope(self):
        rows = self.messages()
        state = qs.inspect(rows)
        self.assertEqual(state['volume']['status'], 'answered')
        self.assertEqual(state['volume']['message_id'], 'job')
        self.assertEqual(state['materials']['status'], 'answered')
        self.assertEqual(state['materials']['message_id'], 'ready')
        self.assertEqual(state['materials']['quote'], READY)
        self.assertEqual(state['materials']['availability_scope'], 'client_reported_hanging_parts_only')
        self.assertNotEqual(state['materials']['value'], 'yes')
        self.assertFalse(facts.tv_mount_work_volume(rows)['booking_confirmed'])

    def test_parts_alone_planned_uncertain_and_other_worker_are_not_ready(self):
        for text in ['Весь крепёж уже куплен.', 'Кронштейны уже на месте.',
                     READY.replace('уже куплен', 'купим завтра'),
                     'Не уверен. ' + READY, 'Если всё готово. ' + READY,
                     'Сосед сказал:«' + READY + '»', 'Продавец говорит: ' + READY]:
            with self.subTest(text=text):
                self.assertIsNone(qs.tv_mount_client_stock(self.messages(text), 2))

    def test_wrong_actor_delivery_and_new_order_do_not_supply_readiness(self):
        for extra in [dict(delivery_status='failed'), dict(delivery_status='processing'), dict(out_pending=True),
                      dict(sender_type='operator'), dict(role='system'), dict(speaker_role='service')]:
            rows = self.messages()
            rows[-1].update(extra)
            with self.subTest(extra=extra):
                self.assertIsNone(qs.tv_mount_client_stock(rows, 2))
        rows = self.messages('Новая заявка. ' + READY)
        self.assertIsNone(qs.tv_mount_client_stock(rows, 2))

    def test_mixed_or_nonmount_work_cannot_borrow_tv_inventory_or_volume(self):
        for text in ['Починить телевизор.', 'Нужно повесить полку.',
                     JOB + ' Ещё собрать шкаф.', 'Дома два телевизора. Повесить один из них.']:
            rows = self.messages()
            rows[0]['body'] = text
            with self.subTest(text=text):
                self.assertIsNone(qs.tv_mount_client_stock(rows, 2))
                self.assertIsNone(facts.tv_mount_work_volume(rows))

    def test_later_actual_shortage_or_uncertainty_revokes_named_readiness(self):
        for body in ['Крепежа нет.', 'Крепёж вроде есть.']:
            rows = self.messages() + [row(body, 'changed')]
            with self.subTest(body=body):
                state = qs.inspect(rows)['materials']
                self.assertTrue(state['status'] == 'uncertain' or state['value'] == 'no')
                self.assertEqual(state['message_id'], 'changed')


if __name__ == '__main__':
    unittest.main()
