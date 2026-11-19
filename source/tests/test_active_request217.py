"""Respect the active client request before advancing the intake form."""
from datetime import datetime, timedelta, timezone
import unittest

import assistant_policy as policy
import dialogue_lifecycle as lifecycle
import qualification_state as qs
from test_history_intake106 import assess


START = datetime(2026, 10, 26, tzinfo=timezone.utc)


def rows(*pairs):
    return [dict(id='active-'+str(i), direction=d, sender_type='client' if d == 'in' else 'operator',
                 body=t, delivery_status='delivered', created_at=START.isoformat())
            for i, (d, t) in enumerate(pairs)]


class ActivePause217Tests(unittest.TestCase):
    def pause(self, text, seconds=0):
        return lifecycle.short_client_pause(rows(('in', text)), START + timedelta(seconds=seconds))

    def test_pause_with_explicit_duration_and_own_purpose(self):
        for text in ('Дайте пять минут, я найду инструкцию.', 'Подождите 5 минут, я посмотрю документы.',
                     'Пожалуйста, подождите, сейчас номер найду.', 'Подождите, я сейчас проверю.'):
            self.assertEqual(self.pause(text)['status'], 'waiting', text)

    def test_source_duration_is_respected_instead_of_default_one_minute(self):
        pause = self.pause('Дайте пять минут, я найду инструкцию.', 61)
        self.assertEqual(pause['status'], 'waiting')
        self.assertEqual(pause['grace_seconds'], 300)
        self.assertEqual(pause['message_id'], 'active-0')
        self.assertEqual(self.pause('Дайте пять минут, я найду инструкцию.', 300)['status'], 'elapsed')

    def test_explicit_seconds_and_reversed_duration_order(self):
        for text in ('Подождите 30 секунд.', 'Можно две минуты?', 'Минут пять, пожалуйста.'):
            self.assertEqual(self.pause(text)['status'], 'waiting', text)
        self.assertEqual(self.pause('Подождите 30 секунд.', 30)['status'], 'elapsed')
        self.assertEqual(self.pause('Можно две минуты?')['grace_seconds'], 120)

    def test_default_short_grace_still_has_original_boundary(self):
        for text in ('Секунду', 'Минутку, пожалуйста', 'Подождите, сейчас номер найду.'):
            self.assertEqual(self.pause(text)['grace_seconds'], 60)
            self.assertEqual(self.pause(text, 60)['status'], 'elapsed')

    def test_new_price_duration_or_arrival_question_is_not_hidden_by_pause(self):
        for text in ('Секунду, сколько стоит сборка?', 'Подождите пять минут, а сколько стоит?',
                     'За пять минут соберёте?', 'Через пять минут приедете?', 'Мне пять минут чинить роутер'):
            self.assertEqual(self.pause(text)['status'], 'not_applicable', text)

    def test_quoted_reported_negative_and_hypothetical_requests_are_not_ours(self):
        for text in ('«Подождите пять минут»', 'Мастер сказал: подождите пять минут.',
                     'Если скажу подождите пять минут', 'Не ждите пять минут.',
                     'Подождите, сосед сказал найти инструкцию.'):
            self.assertEqual(self.pause(text)['status'], 'not_applicable', text)

    def test_new_substantive_client_turn_ends_only_its_pause(self):
        ms = rows(('in', 'Подождите пять минут.'), ('in', 'Нашёл инструкцию. Сможете собрать?'))
        self.assertEqual(lifecycle.short_client_pause(ms, START)['status'], 'not_applicable')

    def test_roles_and_delivery_do_not_create_a_client_pause(self):
        for change in ({'sender_type':'system'}, {'sender_type':'operator'}, {'direction':'out'},
                       {'delivery_status':'failed'}, {'out_pending':True}, {'role':'system'}, {'speaker_role':'service'}):
            ms = rows(('in', 'Подождите пять минут.')); ms[-1].update(change)
            self.assertEqual(lifecycle.short_client_pause(ms, START)['status'], 'not_applicable', change)

    def test_failed_followup_does_not_cancel_already_observed_pause(self):
        ms = rows(('in', 'Подождите пять минут.'), ('out', 'Номер для связи?'))
        ms[-1]['delivery_status'] = 'failed'
        self.assertEqual(lifecycle.short_client_pause(ms, START)['status'], 'waiting')

    def test_missing_clock_cannot_become_an_endless_verified_wait(self):
        ms = rows(('in', 'Подождите пять минут.')); ms[-1].pop('created_at')
        self.assertEqual(lifecycle.short_client_pause(ms, START)['status'], 'unavailable')

    def test_out_of_operational_bound_requires_review_not_shortened_pause(self):
        self.assertEqual(self.pause('Подождите 90 минут.')['status'], 'unavailable')

    def test_public_explicit_pause_uses_persistent_server_anchor(self):
        import test_short_client_pause168 as fixture
        original = fixture.ShortClientPause168Tests('runTest')
        original.setUp(); self.addCleanup(original.doCleanups)
        ctx = original.context('Дайте пять минут, я найду инструкцию.')
        with original.at(0): first = original.preview(ctx)
        anchor = first['client_short_pause_evidence']['anchor_at']
        from extension_assistant import Assistant
        from assistant_store import Store
        original.app = Assistant(Store(original.path))
        with original.at(61): second = original.preview(ctx)
        self.assertEqual(second['action'], 'wait')
        self.assertEqual(second['client_short_pause_evidence']['grace_seconds'], 300)
        self.assertEqual(second['client_short_pause_evidence']['anchor_at'], anchor)
        with original.at(300): after = original.preview(ctx)
        self.assertNotEqual(after['action'], 'wait')


class SupplyQuestion217Tests(unittest.TestCase):
    def questions(self, *pairs):
        return policy.service_expectation_questions(rows(*pairs))

    def test_direct_purchase_question_uses_named_missing_item_in_same_turn(self):
        for text in ('Креплений нет. Купить сможете?', 'Саморезов нет, сможете купить?',
                     'Крепежа нет. А привезти сможете?'):
            self.assertTrue(self.questions(('in', 'Нужно повесить полку.'), ('out', 'Крепления есть?'), ('in', text)), text)

    def test_elliptic_answer_can_refer_to_delivered_material_question(self):
        self.assertTrue(self.questions(('in', 'Нужно повесить полку.'), ('out', 'Крепления есть?'),
                                       ('in', 'Нет. Купить сможете?')))

    def test_supply_is_answered_before_the_next_intake_field(self):
        out = assess(rows(('in', 'Нужно повесить полку на бетонную стену.'),
                          ('out', 'Крепления есть?'), ('in', 'Креплений нет. Купить сможете?')))
        self.assertTrue(any('осмотр' in x for x in out['required_text']))
        self.assertEqual(qs.inspect(rows(('in', 'Нужно повесить полку.'), ('out', 'Крепления есть?'),
                                        ('in', 'Креплений нет. Купить сможете?')))['materials']['value'], 'no')

    def test_unanchored_purchase_question_is_not_assumed_to_mean_materials(self):
        self.assertFalse(self.questions(('in', 'Купить сможете?')))

    def test_another_object_is_not_a_parts_supply_request(self):
        self.assertFalse(self.questions(('in', 'Креплений нет. Холодильник купить сможете?')))

    def test_reported_and_negated_questions_do_not_become_our_supply(self):
        for text in ('Сосед спросил: «Креплений нет. Купить сможете?»',
                     'Не спрашиваю про крепления и не прошу купить.', 'Мастер спросил, купить сможете?'):
            self.assertFalse(self.questions(('in', text)), text)

    def test_failed_or_foreign_question_cannot_supply_missing_object(self):
        for change in ({'sender_type':'system'}, {'delivery_status':'failed'}, {'out_pending':True}):
            ms = rows(('in', 'Нужно повесить полку.'), ('out', 'Крепления есть?'), ('in', 'Нет. Купить сможете?'))
            ms[1].update(change)
            self.assertFalse(policy.service_expectation_questions(ms), change)

    def test_staff_system_or_failed_client_purchase_is_not_an_active_question(self):
        for change in ({'sender_type':'system'}, {'direction':'out'}, {'delivery_status':'failed'}, {'out_pending':True}):
            ms = rows(('in', 'Креплений нет. Купить сможете?')); ms[-1].update(change)
            self.assertFalse(policy.service_expectation_questions(ms), change)

    def test_old_enquiry_cannot_anchor_purchase_for_a_new_order(self):
        self.assertFalse(self.questions(('in', 'Креплений нет.'),
                                        ('in', 'Новая заявка: купить сможете?')))

    def test_old_staff_question_cannot_anchor_elliptic_new_order(self):
        self.assertFalse(self.questions(('in', 'Нужно повесить полку.'), ('out', 'Крепления есть?'),
                                        ('in', 'Новая заявка: нет. Купить сможете?')))

    def test_missing_fasteners_are_only_the_named_part_not_the_whole_kit(self):
        state = qs.inspect(rows(('in', 'Нужно повесить полку. Креплений нет. Купить сможете?')))['materials']
        self.assertEqual(state['value'], 'no')
        self.assertEqual(state['availability_scope'], 'client_named_item_only')
        self.assertIn('креплен', state['availability_subject'].casefold())

    def test_quoted_foreign_conditional_missing_fastener_is_not_own_stock(self):
        for text in ('Сосед сказал: «Креплений нет».', 'Если креплений нет, поможете?',
                     'Возможно, креплений нет.', 'Для другого шкафа креплений нет.'):
            self.assertNotEqual(qs.inspect(rows(('in', 'Нужно повесить полку.'), ('in', text)))['materials'].get('value'), 'no', text)

    def test_general_stock_does_not_turn_named_missing_fasteners_into_present(self):
        state = qs.inspect(rows(('in', 'Нужно повесить полку. Материалы есть, креплений нет.')))['materials']
        self.assertEqual(state['value'], 'no')
        self.assertEqual(state['availability_scope'], 'client_named_item_only')
        self.assertIn('креплен', state['availability_subject'].casefold())


class FoundInstructions217Tests(unittest.TestCase):
    def test_completed_finding_and_receipt_preserve_current_source(self):
        for text in ('Нашёл инструкцию.', 'Инструкцию нашла.', 'Я получил схему сборки.',
                     'Скачал инструкцию.', 'Инструкция нашлась.'):
            state = qs.inspect(rows(('in', 'Нужно собрать комод.'), ('out', 'Инструкция есть?'), ('in', text)))['instructions']
            self.assertEqual(state['status'], 'answered', text)
            self.assertEqual(state['message_id'], 'active-2')
            self.assertEqual(state['quote'], text)

    def test_resume_keeps_instructions_and_does_not_repeat_them(self):
        ms = rows(('in', 'Нужно собрать комод в квартире.'), ('out', 'Инструкция сборки есть?'),
                  ('in', 'Секунду'), ('in', 'Нашёл инструкцию, все детали на месте. Сможете собрать?'))
        self.assertEqual(qs.inspect(ms)['instructions']['status'], 'answered')
        out = assess(ms)
        self.assertNotEqual(out.get('next_question', {}).get('kind'), 'instructions')
        self.assertNotEqual(out.get('next_question', {}).get('kind'), 'materials')
        self.assertNotEqual(out['action'], 'wait')

    def test_all_named_parts_on_site_is_reported_partial_stock_not_verified_fullkit(self):
        for text in ('Все детали на месте.', 'Детали все есть.'):
            state = qs.inspect(rows(('in', 'Нужно собрать комод.'), ('in', text)))['materials']
            self.assertEqual(state['status'], 'answered', text)
            self.assertEqual(state['availability_scope'], 'client_named_item_only')
            self.assertEqual(state['availability_subject'], 'детали')
            self.assertNotEqual(state['value'], 'yes')
            self.assertEqual(state['message_id'], 'active-1')

    def test_uncertain_quoted_future_foreign_parts_do_not_become_stock(self):
        for text in ('Не все детали на месте.', 'Все детали будут на месте.', 'Все детали на месте?',
                     'Сосед сказал: «Все детали на месте».', 'Для другого шкафа все детали на месте.'):
            self.assertNotEqual(qs.inspect(rows(('in', 'Нужно собрать комод.'), ('in', text)))['materials'].get('availability_subject'), 'детали', text)

    def test_new_order_revokes_old_reported_part_stock(self):
        ms = rows(('in', 'Нужно собрать комод. Все детали на месте.'), ('in', 'Новая заявка: собрать другой шкаф.'))
        self.assertNotEqual(qs.inspect(ms)['materials'].get('availability_subject'), 'детали')

    def test_plans_attempts_negations_uncertainty_and_questions_are_not_possession(self):
        for text in ('Я найду инструкцию.', 'Попробую найти инструкцию.', 'Я не нашёл инструкцию.',
                     'Инструкцию не нашёл.', 'Кажется, нашёл инструкцию.', 'Нашёл инструкцию?',
                     'Если найду инструкцию, соберёте?'):
            self.assertNotEqual(qs.inspect(rows(('in', 'Нужно собрать комод.'), ('in', text)))['instructions']['status'], 'answered', text)

    def test_foreign_quote_and_other_furniture_do_not_supply_instructions(self):
        for text in ('Сосед сказал: «Нашёл инструкцию».', 'Мастер нашёл инструкцию.',
                     'Для другого шкафа нашёл инструкцию.'):
            self.assertNotEqual(qs.inspect(rows(('in', 'Нужно собрать комод.'), ('in', text)))['instructions']['status'], 'answered', text)

    def test_roles_failed_pending_do_not_supply_a_found_instruction(self):
        for change in ({'sender_type':'system'}, {'direction':'out'}, {'delivery_status':'failed'},
                       {'out_pending':True}, {'role':'system'}, {'speaker_role':'service'}):
            ms = rows(('in', 'Нужно собрать комод.'), ('in', 'Нашёл инструкцию.')); ms[-1].update(change)
            self.assertNotEqual(qs.inspect(ms)['instructions']['status'], 'answered', change)

    def test_new_order_does_not_reuse_instructions_from_another_job(self):
        ms = rows(('in', 'Нужно собрать комод. Нашёл инструкцию.'), ('in', 'Новая заявка: собрать другой шкаф.'))
        self.assertNotEqual(qs.inspect(ms)['instructions']['status'], 'answered')

    def test_literal_later_withdrawal_is_not_overridden_by_found_history(self):
        ms = rows(('in', 'Нашёл инструкцию.'), ('in', 'Инструкции нет, потерял.'))
        state = qs.inspect(ms)['instructions']
        self.assertEqual(state['message_id'], 'active-1')
        self.assertIn('нет', state['value'])
