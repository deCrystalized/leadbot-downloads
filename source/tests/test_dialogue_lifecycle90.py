"""Metadata unit contract, not execution or an end-to-end assess score.

The research fixtures explicitly require source normalization and complete
qualification decisions. Here real outgoing examples are authored as confirmed
synthetic operator deliveries, never inferred from absence of pending. Existing
decline/deferral decisions are supplied as already calculated policy inputs.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'leadbot/brain'))
import dialogue_lifecycle as lifecycle
import contact_facts
import assistant_catalog

BOUNDARY = ROOT / 'tests/fixtures/lifecycle90.json'
CASES = json.loads(BOUNDARY.read_text())['cases']
NOW = datetime(2026, 10, 19, 3, 5, tzinfo=timezone.utc)
CTX = dict(conversationStatus='in_progress', assignmentKnown=True,
           assigneeId='operator-1', channelAssigned=True, botActive=False,
           hasTransfer=False, hasCrmJob=False)
KNOWN = dict(channel='avito', direction='mnc', partner='7', city='Екатеринбург', title='Сборка мебели')


def preparation():
    return dict(mode='callback', status='operator_review', ready=False,
                time_policy='nearest_branch_normative', visit_time_confirmed=False,
                can_create_automatically=False, requires_full_qualification_check=True,
                extra_preserved='existing-assess-output')


def completed_fixture(row):
    messages = deepcopy(row['messages'])
    for message in messages:
        if message['direction'] == 'out':
            message['sender_type'] = 'operator'
            if not message.get('out_pending'):
                message['delivery_status'] = 'sent'
    known = dict(row['known'], account_name='Синтетический оператор', origin='С1')
    ctx = deepcopy(row['ctx'])
    decision = dict(action='draft', rule_ids=['DOC-L0699', 'DOC-L0700'], decision_guards=[])
    identity = row['id']
    if identity in {'LC01', 'LC02', 'LC05', 'LC06', 'LC07', 'LC08', 'LC09', 'LC10', 'LC11', 'LC12', 'LC37', 'LC38'}:
        decision['action'] = 'wait'
    if identity in {'LC04', 'LC23', 'LC25', 'LC27', 'LC28', 'LC29', 'LC30', 'LC31', 'LC32', 'LC33', 'LC45', 'LC50'}:
        decision['action'] = 'handoff'
    if identity in {'LC19', 'LC26'}:
        decision.update(action='question', rule_ids=['DOC-L0693', 'DOC-L0695'])
    if identity in {'LC34', 'LC35', 'LC36', 'LC39', 'LC40', 'LC42'}:
        decision['action'] = 'wait'
    if identity in {'LC34', 'LC39'}:
        decision['crm_flags'] = dict(customer_declined=True)
    if identity == 'LC36':
        decision['crm_preparation'] = preparation()
    if identity in {'LC25', 'LC27', 'LC31', 'LC32', 'LC33'}:
        decision['decision_guards'] = [dict(id='VERIFY_EXISTING_REQUEST', message_ids=[messages[-1]['id']])]
    if identity == 'LC30':
        # The research flag is not a supported receipt. Supply an explicit
        # synthetic, confirmed receipt rather than trust the transport flag.
        ctx['workflow_receipts'] = [dict(kind='branch_warranty_refusal', confirmed=True,
                                        receipt_id='synthetic-confirmed-refusal', message_ids=['in-1'])]
    if identity == 'LC47':
        decision['service'] = dict(id='cleaning', status='excluded')
    if identity == 'LC48':
        messages[0]['body'] = 'Нужно заменить стояк отопления. Телефон9001234567, улица Ленина10.'
        decision['service'] = assistant_catalog.choose(messages[0]['body'], known)
        assert decision['service']['status'] == 'agree'
    if identity == 'LC50':
        decision['decision_guards'] = [dict(id='VERIFY_LOCATION_CONFLICT', message_ids=['in-1'])]
    return messages, known, decision, ctx, datetime.fromisoformat(row['now'].replace('Z', '+00:00'))


class BoundaryCases(unittest.TestCase):
    def assert_case(self, row):
        args = completed_fixture(row)
        before = deepcopy(args)
        output = lifecycle.classify(*args[:3], ctx=args[3], now=args[4])
        self.assertEqual(args, before, 'classify mutated an input')
        expected = row['expected_subset']
        self.assertEqual(output['disposition'], expected['disposition'])
        self.assertEqual(output['required_actions'], expected['required_actions'])
        if 'timer_status' in expected:
            self.assertEqual(output['timer']['status'], expected['timer_status'])
        if expected.get('crm_preparation') is None:
            self.assertIsNone(output['crm_preparation'])
        else:
            for key, value in expected['crm_preparation'].items():
                self.assertEqual(output['crm_preparation'].get(key), value)
        self.assertFalse(output['auto_enabled'])
        self.assertFalse(output['execution_allowed'])
        self.assertNotIn('grant', output)
        self.assertNotIn('reply', output)


for _row in CASES:
    def _test(self, row=_row):
        self.assert_case(row)
    setattr(BoundaryCases, 'test_' + _row['id'], _test)


class SafetyAndCounterexamples(unittest.TestCase):
    def classify(self, text, action='draft', **decision):
        return lifecycle.classify([dict(id='client', direction='in', body=text,
                                  created_at='2026-10-19T03:00:00Z')], KNOWN,
                                  dict(action=action, **decision), ctx=CTX, now=NOW)

    def timer_case(self):
        return completed_fixture(CASES[1])

    def test_unknown_delivery_is_not_sent(self):
        ms, known, decision, ctx, now = self.timer_case()
        ms[-1].pop('delivery_status')
        out = lifecycle.classify(ms, known, decision, ctx=ctx, now=now)
        self.assertEqual(out['disposition'], 'operator_review')
        self.assertEqual(out['timer']['status'], 'unavailable')
        self.assertNotIn('due_at', out['timer'])

    def test_pending_failed_bot_and_unknown_sender_cannot_start_timer(self):
        for change in [dict(delivery_status='failed'), dict(delivery_status='sending'),
                       dict(sender_type='bot'), dict(sender_type='')]:
            with self.subTest(change=change):
                ms, known, decision, ctx, now = self.timer_case()
                ms[-1].update(change)
                out = lifecycle.classify(ms, known, decision, ctx=ctx, now=now)
                self.assertNotEqual(out['disposition'], 'close')
                self.assertNotIn('due_at', out['timer'])

    def test_note_and_system_do_not_start_or_extend_timer(self):
        for extra in [dict(direction='note'), dict(direction='system'),
                      dict(direction='out', sender_type='system'),
                      dict(direction='out', sender_type='avito')]:
            with self.subTest(extra=extra):
                ms, known, decision, ctx, now = self.timer_case()
                ms.append(dict(id='ignored', body='служебная запись', created_at='2026-10-19T03:04:59Z', **extra))
                out = lifecycle.classify(ms, known, decision, ctx=ctx, now=now)
                self.assertEqual(out['disposition'], 'close')
                self.assertEqual(out['timer']['due_at'], '2026-10-19T03:05:00Z')
                only = lifecycle.classify([ms[-1]], known, decision, ctx=ctx, now=now)
                self.assertNotEqual(only['disposition'], 'close')

    def test_receipt_requires_confirmation_and_matching_message(self):
        for receipt, disposition in [
            (dict(kind='outgoing_delivered', confirmed=True, receipt_id='r', message_id='out-1'), 'close'),
            (dict(kind='outgoing_delivered', confirmed=False, receipt_id='r', message_id='out-1'), 'operator_review'),
            (dict(kind='outgoing_delivered', confirmed=True, receipt_id='r', message_id='another'), 'operator_review'),
            (dict(kind='outgoing_delivered', confirmed=True, message_id='out-1'), 'operator_review')]:
            ms, known, decision, ctx, now = self.timer_case(); ms[-1].pop('delivery_status')
            ctx['workflow_receipts'] = [receipt]
            self.assertEqual(lifecycle.classify(ms, known, decision, ctx=ctx, now=now)['disposition'], disposition)

    def test_epoch_aware_offset_and_order_boundaries(self):
        ms, known, decision, ctx, now = self.timer_case()
        epoch = datetime(2026, 10, 19, 3, tzinfo=timezone.utc).timestamp()
        for stamp in [epoch, str(epoch), '2026-10-19T11:00:00+08:00']:
            ms[-1]['created_at'] = stamp
            self.assertEqual(lifecycle.classify(ms, known, decision, ctx=ctx, now=now.timestamp())['disposition'], 'close')
        ms[-1]['created_at'] = '2026-10-19T02:59:00Z'
        out = lifecycle.classify(ms, known, decision, ctx=ctx, now=now)
        self.assertEqual(out['disposition'], 'operator_review')
        self.assertNotIn('due_at', out['timer'])

    def test_new_incoming_even_empty_or_media_cancels(self):
        for extra in [dict(body=''), dict(body='', attachments=[dict(kind='image')]),
                      dict(body='Новая информация'), dict(body='', unread_media=True)]:
            ms, known, decision, ctx, now = self.timer_case()
            ms.append(dict(id='new', direction='in', created_at='2026-10-19T03:04:59Z', **extra))
            out = lifecycle.classify(ms, known, decision, ctx=ctx, now=now)
            self.assertEqual(out['timer']['status'], 'cancelled_by_incoming')
            self.assertNotEqual(out['disposition'], 'close')

    def test_generic_handoff_and_reason_do_not_invent_transfer_or_approval(self):
        for reason in ['Согласование неясного случая', 'Непрофильная работа', 'Передать оператору', 'Гарантия']:
            out = self.classify('Нужна помощь.', action='handoff', reason=reason)
            self.assertEqual(out['disposition'], 'operator_review')
            self.assertEqual(out['required_actions'], [])

    def test_hypothetical_negated_quoted_or_plain_thanks_not_prior_service(self):
        for text in [
            'Если ваш мастер хорошо соберет шкаф, скажу спасибо.',
            'Если ваш мастер плохо сделает, оставлю отрицательный отзыв.',
            'Спасибо, схема есть.',
            'Увидел чужой текст «Ваш мастер вчера плохо собрал шкаф, напишу отрицательный отзыв».',
            'В отзыве написано "Ваш мастер вчера собрал шкаф, всё отлично, спасибо".',
            'Ваш мастер еще не приезжал. Какая гарантия будет?',
            'Я не общался с сотрудником отдела Авито ранее.',
        ]:
            with self.subTest(text=text):
                self.assertEqual(self.classify(text)['disposition'], 'reply')

    def test_negative_review_negation_not_transfer(self):
        for suffix in ['Не хочу писать отрицательный отзыв.', 'Отрицательный отзыв писать не буду.',
                       'Не оставлю отрицательный отзыв.']:
            out = self.classify('Ваш мастер плохо собрал шкаф. ' + suffix)
            self.assertEqual(out['disposition'], 'notify_okk')
            self.assertNotIn('transfer_avito', out['required_actions'])

    def test_current_complaint_and_conditional_review_keep_both_obligations(self):
        out = self.classify('Ваш мастер плохо собрал шкаф. Если не исправите, оставлю отрицательный отзыв.')
        self.assertEqual(out['disposition'], 'transfer_avito')
        self.assertEqual(out['required_actions'], ['notify_okk'])
        self.assertTrue({'DOC-L1631', 'DOC-L0823'} <= set(out['rule_ids']))

    def test_split_complaint_review_and_later_withdrawal(self):
        messages = [dict(id='complaint', direction='in', body='Ваш мастер плохо собрал шкаф.'),
                    dict(id='review', direction='in', body='Напишу отрицательный отзыв о нём.')]
        out = lifecycle.classify(messages, KNOWN, dict(action='handoff'), ctx=CTX, now=NOW)
        self.assertEqual(out['disposition'], 'transfer_avito')
        self.assertEqual(out['required_actions'], ['notify_okk'])
        self.assertTrue({'complaint', 'review'} <= set(out['message_ids']))
        messages.append(dict(id='withdrawal', direction='in', body='Отзыв писать не хочу, просто исправьте работу.'))
        out = lifecycle.classify(messages, KNOWN, dict(action='handoff'), ctx=CTX, now=NOW)
        self.assertEqual(out['disposition'], 'notify_okk')

    def test_future_incoming_or_inverted_order_cannot_be_an_ordinary_reply(self):
        for stamp in ['2026-10-19T04:00:00Z', '2026-10-19T02:59:00Z']:
            ms, known, decision, ctx, now = self.timer_case()
            ms.append(dict(id='new', direction='in', body='А сколько стоит?', created_at=stamp))
            decision['action'] = 'price'
            out = lifecycle.classify(ms, known, decision, ctx=ctx, now=now)
            self.assertEqual(out['disposition'], 'operator_review')
            self.assertEqual(out['timer']['status'], 'cancelled_by_incoming')

    def test_other_master_not_our_positive_or_complaint(self):
        for text in ['Другой мастер собрал шкаф, спасибо ему.', 'Другой мастер плохо собрал шкаф, хочу отзыв.']:
            self.assertEqual(self.classify(text, action='handoff')['disposition'], 'operator_review')

    def test_unverified_refusal_transport_flag_is_not_a_receipt(self):
        ctx = dict(CTX, branchWarrantyRefusalVerified=True)
        out = lifecycle.classify([dict(id='in', direction='in', body='Нужна гарантия.')], KNOWN,
                                 dict(action='handoff'), ctx=ctx, now=NOW)
        self.assertEqual(out['disposition'], 'operator_review')

    def test_callback_blockers_and_contact_ambiguity(self):
        for update, known_update, ctx_update in [
            (dict(crm_flags=dict(customer_declined=True)), {}, {}),
            (dict(visit_time_confirmed=True), {}, {}),
            (dict(existing_visit_evidence=[dict(message_id='in-1')]), {}, {}),
            ({}, dict(crm_request_id='existing'), {}),
            ({}, {}, dict(hasCrmJob=True)),
            ({}, {}, dict(assignmentKnown=False)),
            (dict(service=dict(status='agree')), {}, {}),
        ]:
            ms, known, decision, ctx, now = completed_fixture(CASES[37])
            decision.update(update); known.update(known_update); ctx.update(ctx_update)
            self.assertIsNone(lifecycle.classify(ms, known, decision, ctx=ctx, now=now)['crm_preparation'])
        for text in ['Не звоните, нужен только чат.', 'Телефон9001234567 или9007654321.',
                     'Шкаф пока не доставили, сам напишу.', 'Адрес уточню позже.']:
            ms, known, decision, ctx, now = completed_fixture(CASES[37])
            if text.startswith('Адрес'):
                ms[0]['body'] = 'Телефон9001234567. ' + text
            else:
                ms[0]['body'] += '\n' + text
            self.assertIsNone(lifecycle.classify(ms, known, decision, ctx=ctx, now=now)['crm_preparation'])

    def test_callback_does_not_copy_phone_or_address_and_uses_existing_parser(self):
        ms, known, decision, ctx, now = completed_fixture(CASES[37])
        with patch.object(contact_facts, 'collect', wraps=contact_facts.collect) as collect:
            out = lifecycle.classify(ms, known, decision, ctx=ctx, now=now)
        self.assertEqual(collect.call_count, 1)
        self.assertNotIn('phone', out['crm_preparation'])
        self.assertNotIn('address', out['crm_preparation'])
        self.assertFalse(out['crm_preparation']['ready'])

    def test_preserves_existing_preparation_guards_and_evidence_without_aliasing(self):
        decision = dict(action='wait', crm_preparation=preparation(),
                        decision_guards=[dict(id='KEEP', message_ids=['client'])],
                        example_evidence=dict(message_id='client', quote='Исходное доказательство'))
        before = deepcopy(decision)
        out = self.classify('Завтра сам напишу после13.', **decision)
        self.assertEqual(out['crm_preparation'], before['crm_preparation'])
        self.assertEqual(out['decision_guards'], before['decision_guards'])
        self.assertEqual(out['decision_evidence']['example_evidence'], before['example_evidence'])
        out['crm_preparation']['extra_preserved'] = 'modified-output'
        self.assertEqual(decision, before)

    def test_inconsistent_preparation_never_carries_ready_or_automatic_creation(self):
        for change in [dict(ready=True), dict(can_create_automatically=True),
                       dict(visit_time_confirmed=True), dict(requires_full_qualification_check=False),
                       dict(status='approved')]:
            prep = preparation(); prep.update(change)
            out = self.classify('Завтра сам напишу после13.', action='wait', crm_preparation=prep)
            self.assertEqual(out['disposition'], 'operator_review')
            self.assertIsNone(out['crm_preparation'])
            self.assertFalse(out['auto_enabled'])
            self.assertFalse(out['execution_allowed'])

    def test_no_call_or_decline_also_blocks_inherited_callback(self):
        for text, flags in [('Не звоните мне.', {}), ('Спасибо.', dict(customer_declined=True))]:
            out = self.classify(text, action='wait', crm_preparation=preparation(), crm_flags=flags)
            self.assertIsNone(out['crm_preparation'])
            self.assertEqual(out['disposition'], 'operator_review')

    def test_nonclient_sender_cannot_supply_postservice_evidence_or_cancel_timer(self):
        for sender in ['bot', 'operator', 'assistant', 'employee']:
            ms, known, decision, ctx, now = self.timer_case()
            ms.append(dict(id='fake-client', direction='in', sender_type=sender,
                           body='Ваш мастер плохо собрал шкаф, напишу отрицательный отзыв.',
                           created_at='2026-10-19T03:04:59Z'))
            out = lifecycle.classify(ms, known, decision, ctx=ctx, now=now)
            self.assertEqual(out['disposition'], 'close')
            self.assertEqual(out['timer']['status'], 'elapsed')

    def test_foreign_unassigned_bot_transfer_and_closed_context_never_close(self):
        for change in [dict(assignedToCurrentOperator=False), dict(assignmentKnown=False),
                       dict(channelAssigned=False), dict(botActive=True), dict(hasTransfer=True),
                       dict(conversationStatus='closed')]:
            ms, known, decision, ctx, now = self.timer_case(); ctx.update(change)
            self.assertEqual(lifecycle.classify(ms, known, decision, ctx=ctx, now=now)['disposition'], 'operator_review')


class KPSilencePhases(unittest.TestCase):
    def history(self, followup_at=None):
        messages = [dict(id='client', direction='in', body='Нужен ремонт компьютера.',
                         created_at='2026-10-19T02:59:59Z'),
                    dict(id='initial', direction='out', sender_type='operator',
                         body='Здравствуйте! Какая марка компьютера?',
                         delivery_status='delivered', created_at='2026-10-19T03:00:00Z')]
        if followup_at:
            messages.append(dict(id='followup', direction='out', sender_type='operator',
                                 body=lifecycle.KP_FOLLOWUP_REPLY, delivery_status='sent',
                                 created_at=followup_at))
        return messages

    def clock(self, minute=5, second=0):
        return datetime(2026, 10, 19, 3, tzinfo=timezone.utc) + timedelta(minutes=minute, seconds=second)

    def classify(self, messages, now, decision=None, ctx=None, known=None):
        return lifecycle.classify(messages, known or dict(KNOWN, direction='kp'),
                                  decision or dict(action='wait'),
                                  ctx=CTX if ctx is None else ctx, now=now)

    def test_first_phase_459_wait_and_500_followup_due(self):
        messages = self.history()
        before = lifecycle.silence_timer(messages, dict(KNOWN, direction='kp'), now=self.clock(4, 59))
        self.assertEqual(before['status'], 'waiting')
        out = self.classify(messages, self.clock())
        self.assertEqual(out['disposition'], 'reply')
        self.assertEqual(out['timer']['status'], 'followup_due')
        self.assertEqual(out['suggested_reply'], 'Подскажите, вопрос ещё актуален?')
        self.assertTrue(out['requires_operator_review'])
        self.assertFalse(out['auto_enabled'])
        self.assertFalse(out['execution_allowed'])
        self.assertTrue({'OWNER-KP-SILENCE-20261019', 'KP-L1598'} <= set(out['rule_ids']))

    def test_no_followup_means_no_close_at_15_minutes_or_later(self):
        for minute in [5, 14, 15, 16, 60]:
            out = self.classify(self.history(), self.clock(minute))
            self.assertEqual(out['disposition'], 'reply')
            self.assertEqual(out['timer']['status'], 'followup_due')

    def test_ten_minutes_are_measured_from_actual_late_followup(self):
        messages = self.history('2026-10-19T03:07:00Z')
        for minute, second, disposition in [(15, 0, 'wait'), (16, 59, 'wait'), (17, 0, 'close')]:
            out = self.classify(messages, self.clock(minute, second))
            self.assertEqual(out['disposition'], disposition)
            self.assertEqual(out['timer']['phase'], 'after_followup')
            self.assertEqual(out['timer']['due_at'], '2026-10-19T03:17:00Z')
            self.assertNotIn('suggested_reply', out)

    def test_exact_5_plus_10_boundary(self):
        messages = self.history('2026-10-19T03:05:00Z')
        self.assertEqual(self.classify(messages, self.clock(14, 59))['disposition'], 'wait')
        self.assertEqual(self.classify(messages, self.clock(15))['disposition'], 'close')

    def test_pending_unknown_failed_or_bot_followup_never_repeats_or_closes(self):
        for change, disposition in [(dict(out_pending=True), 'wait'),
                                    (dict(delivery_status='sending'), 'wait'),
                                    (dict(delivery_status=''), 'operator_review'),
                                    (dict(delivery_status='failed'), 'operator_review'),
                                    (dict(sender_type='bot'), 'operator_review')]:
            with self.subTest(change=change):
                messages = self.history('2026-10-19T03:05:00Z'); messages[-1].update(change)
                out = self.classify(messages, self.clock(30))
                self.assertEqual(out['disposition'], disposition)
                self.assertNotIn('suggested_reply', out)
                self.assertNotIn('due_at', out['timer'])

    def test_unconfirmed_initial_anchor_or_too_early_followup_cannot_close(self):
        variants = []
        too_early = self.history('2026-10-19T03:04:59Z'); variants.append(too_early)
        unknown = self.history('2026-10-19T03:05:00Z'); unknown[1]['delivery_status'] = ''; variants.append(unknown)
        bot = self.history('2026-10-19T03:05:00Z'); bot[1]['sender_type'] = 'bot'; variants.append(bot)
        variants.append(self.history('2026-10-19T03:05:00Z')[::2])
        duplicate = self.history('2026-10-19T03:05:00Z'); duplicate[-1]['id'] = 'initial'; variants.append(duplicate)
        for messages in variants:
            out = self.classify(messages, self.clock(30))
            self.assertEqual(out['disposition'], 'operator_review')
            self.assertEqual(out['timer']['status'], 'unavailable')
            self.assertNotIn('due_at', out['timer'])

    def test_incoming_between_initial_and_followup_cancels_original_chain(self):
        for extra in [dict(body='Есть вопрос'), dict(body='', unread_media=True),
                      dict(body='', attachments=[dict(kind='image')])]:
            messages = self.history('2026-10-19T03:05:00Z')
            messages.insert(2, dict(id='new', direction='in', created_at='2026-10-19T03:04:00Z', **extra))
            out = self.classify(messages, self.clock(20))
            self.assertEqual(out['disposition'], 'operator_review')
            self.assertNotIn('due_at', out['timer'])

    def test_new_incoming_after_either_phase_cancels_both_timers(self):
        for followup in [None, '2026-10-19T03:05:00Z']:
            for extra in [dict(body='А сколько стоит?'), dict(body='', unread_media=True)]:
                messages = self.history(followup)
                messages.append(dict(id='new', direction='in', created_at='2026-10-19T03:06:00Z', **extra))
                timer = lifecycle.silence_timer(messages, dict(KNOWN, direction='kp'), now=self.clock(20))
                self.assertEqual(timer['status'], 'cancelled_by_incoming')
                self.assertNotIn('due_at', timer)
                out = self.classify(messages, self.clock(20), decision=dict(action='draft'))
                self.assertNotEqual(out['disposition'], 'close')
                self.assertNotIn('suggested_reply', out)

    def test_unapproved_paraphrase_does_not_establish_second_timer(self):
        messages = self.history('2026-10-19T03:05:00Z')
        messages[-1]['body'] = 'Актуально? Заказываете ремонт?'
        out = self.classify(messages, self.clock(20))
        self.assertEqual(out['timer']['phase'], 'initial_wait')
        self.assertEqual(out['timer']['status'], 'followup_due')
        self.assertNotEqual(out['disposition'], 'close')

    def test_note_and_system_do_not_break_or_extend_followup_phase(self):
        messages = self.history('2026-10-19T03:05:00Z')
        messages.append(dict(id='note', direction='note', body='Проверка', created_at='2026-10-19T03:14:59Z'))
        out = self.classify(messages, self.clock(15))
        self.assertEqual(out['disposition'], 'close')
        self.assertEqual(out['timer']['due_at'], '2026-10-19T03:15:00Z')

    def test_public_timer_is_pure_and_independent_of_assignment(self):
        messages = self.history(); known = dict(KNOWN, direction='kp')
        before = deepcopy((messages, known))
        timer = lifecycle.silence_timer(messages, known, now=self.clock())
        self.assertEqual(timer['status'], 'followup_due')
        self.assertEqual((messages, known), before)
        out = self.classify(messages, self.clock(), ctx={})
        self.assertEqual(out['disposition'], 'operator_review')
        self.assertNotIn('suggested_reply', out)

    def test_followup_does_not_bypass_scope_existing_order_or_media(self):
        for known, ctx, decision in [
            (dict(KNOWN, direction='kp', channel='max_user'), CTX, dict(action='wait')),
            (dict(KNOWN, direction='kp', crm_request_id='existing'), CTX, dict(action='wait')),
            (dict(KNOWN, direction='kp'), dict(CTX, hasTransfer=True), dict(action='wait')),
            (dict(KNOWN, direction='kp'), CTX, dict(action='handoff')),
        ]:
            out = self.classify(self.history(), self.clock(), known=known, ctx=ctx, decision=decision)
            self.assertNotEqual(out['disposition'], 'reply')
            self.assertNotIn('suggested_reply', out)

    def test_explicit_deferred_declined_and_resolved_never_restart_sales(self):
        for marker in [dict(client_wait_intent='deferred'), dict(client_wait_intent='declined'),
                       dict(crm_flags=dict(customer_declined=True)), dict(flags=dict(customer_declined=True)),
                       dict(service_resolution_evidence=dict(message_id='client', crm_completion_confirmed=False))]:
            for followup in [None, '2026-10-19T03:05:00Z']:
                out = self.classify(self.history(followup), self.clock(30), decision=dict(action='wait', **marker))
                self.assertEqual(out['disposition'], 'wait')
                self.assertNotIn('suggested_reply', out)
                self.assertFalse(out['execution_allowed'])

    def test_deferred_preparation_preserved_declined_preparation_removed(self):
        deferred = self.classify(self.history(), self.clock(), decision=dict(action='wait',
                                 client_wait_intent='deferred', crm_preparation=preparation()))
        self.assertEqual(deferred['disposition'], 'wait')
        self.assertEqual(deferred['crm_preparation'], preparation())
        declined = self.classify(self.history(), self.clock(), decision=dict(action='wait',
                                 crm_flags=dict(customer_declined=True), crm_preparation=preparation()))
        self.assertEqual(declined['disposition'], 'wait')
        self.assertIsNone(declined['crm_preparation'])


if __name__ == '__main__':
    unittest.main()
