"""Named purchased supplies and current procurement questions keep their roles."""
import copy
from pathlib import Path
import tempfile
import unittest

import assistant_policy as policy
import qualification_state as qs
from assistant_store import Store
from extension_assistant import Assistant
from test_history_intake106 import assess, known


INITIAL = ('Здравствуйте! Нужно повесить два карниза и одну полку в комнате на бетонную стену. '
           'Карнизы, полка и крепёж куплены. Как это происходит?')
PARTS = 'Это квартира. А если крепежа вдруг не хватит, Вы докупите?'
UNCERTAINTY = 'По материалам смогу сориентировать после осмотра.'


def message(body, mid='stock', **changes):
    return dict(id=mid, direction='in', sender_type='client', body=body, **changes)


def stock(body, **changes):
    return qs.inspect([message('Нужно повесить два карниза и одну полку.', mid='work'),
                       message(body, **changes)])['materials']


def source():
    return [message(INITIAL, mid='initial'),
            dict(id='system', direction='out', sender_type='system', role='system',
                 body='Диалог принят', delivery_status='delivered'),
            dict(id='pending', direction='out', sender_type='operator',
                 body='Номер и адрес подскажите?', delivery_status='pending'),
            message('?', mid='reminder')]


class CoordinatedStock260Tests(unittest.TestCase):
    def test_coordinated_bought_items_are_known_without_claiming_complete_kit(self):
        row = stock('Карнизы, полка и крепёж куплены.')
        self.assertEqual(row['status'], 'answered')
        self.assertEqual(row.get('availability_scope'), 'client_named_item_only')
        self.assertIn('карниз', row.get('availability_subject', '').casefold())
        self.assertIn('креп', row.get('availability_subject', '').casefold())

    def test_purchase_predicate_before_the_named_list_is_also_current_evidence(self):
        self.assertEqual(stock('Куплены карнизы, полка и крепёж.')['status'], 'answered')

    def test_named_present_list_is_not_lost_because_it_has_several_subjects(self):
        self.assertEqual(stock('Карнизы и крепёж уже есть.')['status'], 'answered')

    def test_evidence_keeps_original_message_quote_and_role(self):
        body = 'Карнизы, полка и крепёж куплены.'
        row = stock(body)
        self.assertEqual(row.get('message_id'), 'stock')
        self.assertEqual(row.get('quote'), body)
        self.assertEqual(row.get('evidence_source'), 'client_message')

    def test_conditional_or_uncertain_purchase_is_not_present_stock(self):
        for body in ('Если карнизы, полка и крепёж куплены, что дальше?',
                     'Возможно карнизы, полка и крепёж куплены.',
                     'Не уверен, что карнизы, полка и крепёж куплены.'):
            with self.subTest(body=body):
                self.assertNotEqual(stock(body)['status'], 'answered')

    def test_negated_or_partial_purchase_does_not_become_all_available(self):
        for body in ('Карнизы, полка и крепёж не куплены.',
                     'Не все карнизы, полка и крепёж куплены.'):
            with self.subTest(body=body):
                self.assertNotEqual(stock(body).get('availability_subject'), 'Карнизы, полка и крепёж')

    def test_foreign_or_quoted_supply_is_not_the_clients_named_stock(self):
        for body in ('Сосед сказал: карнизы, полка и крепёж куплены.',
                     'Сосед написал: «Карнизы, полка и крепёж куплены».',
                     'Для другого заказа карнизы, полка и крепёж куплены.'):
            with self.subTest(body=body):
                self.assertNotEqual(stock(body)['status'], 'answered')

    def test_incoming_staff_system_pending_and_failed_are_not_client_assertions(self):
        for changes in (dict(sender_type='operator'), dict(sender_type='system'), dict(role='system'),
                        dict(delivery_status='pending'), dict(delivery_status='failed')):
            row = message('Карнизы, полка и крепёж куплены.')
            row.update(changes)
            with self.subTest(changes=changes):
                self.assertNotEqual(qs.inspect([row])['materials']['status'], 'answered')

    def test_future_purchase_is_not_current_stock(self):
        self.assertNotEqual(stock('Карнизы, полка и крепёж будут куплены.')['status'], 'answered')

    def test_unmentioned_fittings_do_not_enter_the_quote_or_subject(self):
        row = stock('Карнизы и полка куплены.')
        self.assertEqual(row['status'], 'answered')
        self.assertNotIn('креп', row.get('availability_subject', '').casefold())
        self.assertNotIn('комплект', row.get('availability_subject', '').casefold())

    def test_later_literal_absent_fasteners_are_not_overwritten_by_old_stock(self):
        ms = [message('Карнизы, полка и крепёж куплены.', mid='bought'),
              message('Крепежа нет.', mid='missing')]
        row = qs.inspect(ms)['materials']
        self.assertEqual(row['value'], 'no')
        self.assertEqual(row['message_id'], 'missing')

    def test_source_is_not_rewritten_to_create_purchase_evidence(self):
        ms = source()
        before = copy.deepcopy(ms)
        qs.inspect(ms)
        self.assertEqual(ms, before)


class AdditionalProcurement260Tests(unittest.TestCase):
    def test_current_additional_purchase_question_gets_inspection_boundary(self):
        self.assertIn(UNCERTAINTY, policy.service_expectation_questions([message(PARTS)]))

    def test_modal_and_infinitive_forms_keep_the_same_procurement_meaning(self):
        for body in ('Если крепежа не хватит, сможете докупить его?',
                     'Докупить недостающие материалы можете?'):
            with self.subTest(body=body):
                self.assertIn(UNCERTAINTY, policy.service_expectation_questions([message(body)]))

    def test_client_infinitive_and_different_service_question_do_not_merge(self):
        for body in ('Крепёж я должен докупить, а Вы можете повесить полку?',
                     'Докупить крепёж может сосед, Вы можете приехать?'):
            with self.subTest(body=body):
                self.assertEqual(policy.service_expectation_questions([message(body)]), [])

    def test_our_worker_can_be_the_respondent_but_supply_is_not_promised(self):
        self.assertIn(UNCERTAINTY, policy.service_expectation_questions(
            [message('Если крепежа не хватит, ваш мастер докупит недостающее?')]))

    def test_different_worker_is_not_our_procurement(self):
        self.assertEqual(policy.service_expectation_questions(
            [message('Мой мастер докупит крепёж?')]), [])

    def test_client_purchase_statement_is_not_our_inventory_question(self):
        for body in ('Я докуплю крепёж.', 'Мы докупим крепёж.', 'Крепёж докуплен.'):
            with self.subTest(body=body):
                self.assertEqual(policy.service_expectation_questions([message(body)]), [])

    def test_no_anchor_or_whole_device_purchase_does_not_become_parts_supply(self):
        for body in ('Вы докупите?', 'Вы докупите телевизор?'):
            with self.subTest(body=body):
                self.assertEqual(policy.service_expectation_questions([message(body)]), [])

    def test_quotation_negated_request_and_statement_are_not_current_questions(self):
        for body in ('Сосед спросил: «Вы докупите крепёж?»',
                     'Не спрашиваю, докупите ли Вы крепёж.', 'Ваш мастер докупит крепёж.'):
            with self.subTest(body=body):
                self.assertEqual(policy.service_expectation_questions([message(body)]), [])

    def test_nonclient_or_unfinished_question_does_not_gain_reply_authority(self):
        for changes in (dict(sender_type='operator'), dict(role='system'),
                        dict(delivery_status='pending'), dict(delivery_status='failed')):
            ms = [message(PARTS)]
            ms[0].update(changes)
            with self.subTest(changes=changes):
                self.assertEqual(policy.service_expectation_questions(ms), [])

    def test_reply_does_not_promise_procurement_of_named_fasteners(self):
        for body in ('Докуплю крепёж.', 'Крепления привезу.', 'Саморезы возьму с собой.'):
            with self.subTest(body=body):
                self.assertTrue(policy.service_expectation_violations(body))
        self.assertEqual(policy.service_expectation_violations(UNCERTAINTY), [])


class NativeMaterials260Tests(unittest.TestCase):
    def preview(self, ms):
        with tempfile.TemporaryDirectory() as tmp:
            app = Assistant(Store(Path(tmp) / 'assistant.sqlite3'))
            ctx = dict(convId='synthetic-materials260', dir='mnc', city='Чита', partner='7',
                       accountTitle='Георгий МНЧ', itemTitle='Мастер на час', origin='С1',
                       channel='avito', adIdentity='Георгий', messages=ms)
            result, code = app.handle(dict(owner='isolated-materials260', action='preview',
                                          wording_mode='reviewed', ctx=ctx))
            self.assertEqual(code, 200)
            self.assertFalse(result['auto_enabled'])
            return result

    def test_full_initial_source_does_not_ask_for_already_bought_materials(self):
        result = self.preview(source())
        self.assertIn('Работаем с выездом.', result['reply'])
        self.assertEqual(result['qualification']['materials']['status'], 'answered')
        self.assertNotIn('материалы есть у вас?', result['reply'].casefold())

    def test_current_parts_question_is_answered_before_any_unknown_qualification(self):
        ms = source()
        first = self.preview(ms)
        ms += [dict(id='delivered', direction='out', sender_type='operator',
                    body=first['reply'], delivery_status='delivered'), message(PARTS, mid='parts')]
        result = self.preview(ms)
        self.assertIn(UNCERTAINTY, result['reply'])
        self.assertNotIn('материалы есть у вас?', result['reply'].casefold())
        self.assertEqual(result['qualification']['materials']['status'], 'answered')

    def test_existing_booking_is_still_outside_new_intake(self):
        ms = source() + [dict(id='booked', direction='out', sender_type='operator',
                             body='Хорошо, записал вас — до встречи.', delivery_status='delivered'),
                         message(PARTS, mid='after-booking')]
        result = assess(ms, known('mnc', 'Мастер на час'))
        self.assertEqual(result['action'], 'handoff')
        self.assertNotIn(UNCERTAINTY, result.get('required_text', []))

    def test_new_enquiry_does_not_inherit_old_named_stock(self):
        ms = [message('Карнизы, полка и крепёж куплены.', mid='old'),
              message('Новая заявка: повесить люстру.', mid='new')]
        self.assertNotEqual(qs.inspect(ms)['materials']['status'], 'answered')
