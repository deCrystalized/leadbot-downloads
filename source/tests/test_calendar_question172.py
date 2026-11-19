"""Current calendar questions precede price consent without proving a booking."""
import copy
import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

import assistant_policy as policy
from assistant_store import Store
from extension_assistant import Assistant


def client(mid, body, **extra):
    return dict(dict(id=mid, direction='in', sender_type='client', body=body), **extra)


class CalendarQuestion172Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner172',
                         LEADBOT_PERSONAL_AUTO_AVAILABLE='0')
        env.start(); self.addCleanup(env.stop)
        self.app = Assistant(Store(tmp.name + '/db'))

    def context(self, body='Завтра сможете?', **extra):
        ctx = dict(convId='synthetic-calendar172', dir='mnc', city='Тюмень', channel='avito',
                   partner='7', accountTitle='Учебный МНЧ', itemTitle='Сборка мебели', messages=[
                       client('job', 'Сколько стоит собрать шкаф-купе б/у, двери с зеркалами, 200 на 220?'),
                       dict(id='scheme', direction='out', body='Схема есть?'),
                       client('no-scheme', 'Схемы нет, шкаф б/у'),
                       dict(id='when', direction='out', body='Когда вам будет удобно?'),
                       client('fee-ask', 'Сколько стоит его собрать?'),
                       dict(id='fee', direction='out', body='от 1500р будет идти, точную цену на месте только смогу назвать'),
                       client('crew', 'Вы один? Шкаф большой просто...'),
                       dict(id='crew-answer', direction='out', body='Я работаю один.'),
                       client('calendar', body)])
        ctx.update(extra)
        return ctx

    def at(self, stamp='2026-09-11T20:19:15+05:00'):
        return patch('assistant_policy._visit_question_now', return_value=datetime.fromisoformat(stamp))

    def preview(self, ctx, stamp='2026-09-11T20:19:15+05:00'):
        with self.at(stamp):
            out, code = self.app.handle(dict(owner='owner172', action='preview',
                                            wording_mode='neural_review', ctx=ctx))
        self.assertEqual(code, 200)
        self.assertFalse(out['auto_enabled'])
        if out.get('code') == 'time_offer_expired':
            self.assertFalse(out['reply']); self.assertTrue(out['needs_operator'])
        else:
            self.assertFalse(out['lead']['can_create_automatically'])
        return out

    def test_original_day_question_is_answered_before_pending_price_consent(self):
        ctx = self.context(); before = copy.deepcopy(ctx); out = self.preview(ctx)
        task = json.loads(out['model_task']['task'])
        self.assertEqual(task['proposed_reply'], 'На завтра на какое время вам удобно?')
        self.assertNotIn('Такая стоимость', task['proposed_reply'])
        self.assertEqual(out['crm_flags']['price_consent'], 'pending')
        self.assertIsNone(out['visit_offer'])
        q = out['visit_time_question']
        self.assertEqual(q['requested_date'], '2026-09-12')
        self.assertEqual(q['timezone'], 'Asia/Yekaterinburg')
        self.assertFalse(q['availability_verified'])
        self.assertFalse(q['appointment_confirmed'])
        self.assertEqual(ctx, before)

    def test_relative_days_and_weekday_are_resolved_from_branch_clock(self):
        for text, day, label in [('Послезавтра сможете приехать?', '2026-09-13', 'послезавтра'),
                                 ('В субботу сможете?', '2026-09-12', 'субботу')]:
            with self.subTest(text=text):
                out = self.preview(self.context(text, convId='synthetic-calendar-' + day))
                self.assertEqual(out['visit_time_question']['requested_date'], day)
                self.assertIn(label, json.loads(out['model_task']['task'])['proposed_reply'])

    def test_today_retains_normative_relative_window_instead_of_reasking_the_day(self):
        out = self.preview(self.context('Сегодня можете?'), stamp='2026-09-11T13:19:15+05:00')
        self.assertEqual(json.loads(out['model_task']['task'])['proposed_reply'], 'Через час-полтора вам удобно будет?')
        self.assertEqual(out['visit_offer']['min_minutes'], 60)
        self.assertFalse(out['visit_offer']['appointment_confirmed'])

    def test_same_turn_price_question_keeps_its_own_answer_priority(self):
        out = self.preview(self.context('Завтра сможете и сколько стоит сборка?'))
        self.assertIsNone(out.get('visit_time_question'))
        self.assertRegex(json.loads(out['model_task']['task'])['proposed_reply'], 'стоим|рубл|осмотр')

    def test_calendar_is_not_callback_material_delivery_past_or_third_party(self):
        for text in ['Завтра сможете позвонить?', 'Завтра сможете привезти детали?',
                     'Вчера вы смогли приехать?', '«Завтра сможете?»',
                     'Другой мастер спросил, завтра сможете?', 'Если спросят завтра сможете, что ответить?',
                     'Мне завтра не нужно, не спрашиваю когда вы приедете.']:
            with self.subTest(text=text):
                self.assertIsNone(policy.current_visit_time_question([client('x', text)]))

    def test_other_roles_are_not_customer_questions(self):
        for role in ['operator', 'assistant', 'bot', 'system', 'avito', 'employee']:
            row = client('x', 'Завтра сможете?'); row['sender_type'] = role
            self.assertIsNone(policy.current_visit_time_question([row]))

    def test_split_question_and_system_notes_keep_the_actual_client_turn(self):
        rows = [client('day', 'Завтра'), dict(id='n', direction='note', body='от 1500'),
                dict(id='s', direction='system', body='Назначен'), client('can', 'Сможете?')]
        q = policy.current_visit_time_question(rows)
        self.assertEqual(q['evidence_ids'], ['day', 'can'])
        self.assertEqual(q['quote'], 'Завтра\nСможете?')

    def test_delivered_staff_reply_ends_question_but_failed_send_does_not(self):
        rows = [client('q', 'Завтра сможете?'), dict(id='out', direction='out', body='Уточню.',
                 delivery_status='delivered'), client('later', 'Спасибо')]
        self.assertIsNone(policy.current_visit_time_question(rows))
        rows[1]['delivery_status'] = 'failed'; rows[-1]['body'] = '?'
        self.assertIsNotNone(policy.current_visit_time_question(rows))

    def test_withdrawal_clears_old_question_in_the_same_turn(self):
        self.assertIsNone(policy.current_visit_time_question([
            client('q', 'Завтра сможете?'), client('no', 'Нет, время пока не обсуждаем')]))

    def test_existing_order_and_max_still_take_priority(self):
        for extra in [dict(crmRequestId='synthetic-order172'), dict(channel='max')]:
            out = self.preview(self.context(**extra))
            self.assertEqual(out['action'], 'handoff')
            self.assertFalse(out.get('pending_model'))

    def test_unknown_territory_cannot_silently_fall_back_to_price_consent(self):
        out = self.preview(self.context(city='Неизвестный город'))
        self.assertEqual(out['action'], 'handoff')
        self.assertIsNone(out.get('visit_time_question'))

    def test_explicit_time_is_preserved_without_confirming_a_free_slot(self):
        out = self.preview(self.context('Завтра к 14:00 сможете приехать?'))
        task = json.loads(out['model_task']['task'])
        self.assertIn('14:00', task['proposed_reply'])
        self.assertNotIn('какое время', task['proposed_reply'])
        self.assertFalse(out['visit_time_question']['availability_verified'])
        self.assertNotRegex(task['proposed_reply'], 'записал|приеду|свободен|без проблем')

    def test_outside_hours_does_not_become_an_ordinary_calendar_offer(self):
        out = self.preview(self.context('Завтра в 23:00 сможете приехать?'))
        self.assertEqual(out['action'], 'handoff')
        self.assertFalse(out.get('pending_model'))

    def test_raw_price_only_candidate_is_rejected_without_repair(self):
        out = self.preview(self.context()); candidate = dict(reply='Такая стоимость вас устраивает?',
            needs_operator=False, context_review=dict(last_intent='Сборка шкафа, вопрос о завтрашнем визите.',
                latest_client_meaning='Спрашивает, можно ли завтра.', selected_step_fits=True,
                evidence_ids=['calendar'], note='Текущее время ещё не выбрано.'))
        before = copy.deepcopy(candidate)
        with self.at():
            final, code = self.app.handle(dict(owner='owner172', action='finalize', request_id=out['request_id'],
                revision=out['revision'], candidate=candidate))
        self.assertEqual(code, 200); self.assertEqual(candidate, before)
        self.assertIn('fixed_reply_changed', final['validation'])
        self.assertFalse(final['reply']); self.assertTrue(final['needs_operator'])

    def test_complete_reply_and_model_veto_are_both_supported(self):
        for veto in [False, True]:
            out = self.preview(self.context(convId='synthetic-calendar-veto-' + str(veto)))
            task = json.loads(out['model_task']['task'])
            candidate = dict(reply='' if veto else task['proposed_reply'], needs_operator=veto,
                context_review=dict(last_intent='Сборка шкафа, выбор времени.',
                    latest_client_meaning='Спрашивает о завтрашнем визите.', selected_step_fits=not veto,
                    evidence_ids=['calendar'], note='Время и запись не подтверждены.'))
            with self.at():
                final, code = self.app.handle(dict(owner='owner172', action='finalize', request_id=out['request_id'],
                    revision=out['revision'], candidate=candidate))
            self.assertEqual(code, 200)
            self.assertEqual(final['action'], 'handoff' if veto else 'question')
            if veto:
                self.assertFalse(final['reply']); self.assertTrue(final['needs_operator'])
            else:
                self.assertFalse(final['validation'])

    def test_resolved_day_and_original_quote_are_visible_to_the_model(self):
        out = self.preview(self.context()); task = json.loads(out['model_task']['task'])
        q = task['visit_time_question_context']
        self.assertEqual(q['quote'], 'Завтра сможете?')
        self.assertEqual(q['source'], 'current_client_turn_and_branch_clock')
        self.assertEqual(q['requested_date'], '2026-09-12')
        self.assertIn('собрать шкаф-купе', task['conversation'][0]['body'].lower())
        self.assertNotIn('ремонт', task['conversation'][0]['body'].lower())

    def test_cached_question_and_finalize_expire_when_relative_day_changes(self):
        ctx = self.context(); out = self.preview(ctx)
        candidate = dict(reply='На завтра на какое время вам удобно?', needs_operator=False,
            context_review=dict(last_intent='Сборка шкафа.', latest_client_meaning='Спрашивает о завтра.',
                selected_step_fits=True, evidence_ids=['calendar'], note='Дата ещё не принята.'))
        with self.at():
            saved, code = self.app.handle(dict(owner='owner172', action='finalize', request_id=out['request_id'],
                revision=out['revision'], candidate=candidate))
        self.assertEqual(code, 200); self.assertFalse(saved['validation'])
        expired = self.preview(ctx, stamp='2026-09-12T00:01:00+05:00')
        self.assertTrue(expired['cached']); self.assertEqual(expired['code'], 'time_offer_expired')
        pending = self.preview(self.context(convId='synthetic-midnight-pending172'))
        with self.at('2026-09-12T00:01:00+05:00'):
            final, code = self.app.handle(dict(owner='owner172', action='finalize', request_id=pending['request_id'],
                revision=pending['revision'], candidate=candidate))
        self.assertEqual(code, 200); self.assertEqual(final['code'], 'time_offer_expired')
        self.assertFalse(final['reply']); self.assertTrue(final['needs_operator'])

    def test_invalid_clock_is_not_truncated_to_a_valid_hour(self):
        for text in ['Завтра в 14:90 сможете?', 'Завтра в 25:00 сможете?', 'Завтра в 14.3 сможете?']:
            with self.subTest(text=text):
                out = self.preview(self.context(text, convId='synthetic-invalid-clock-' + text))
                self.assertEqual(out['action'], 'handoff')
                self.assertFalse(out.get('pending_model'))

    def test_negated_availability_question_is_still_a_question(self):
        self.assertIsNotNone(policy.current_visit_time_question([client('q', 'Завтра не сможете?')]))

    def test_browser_calendar_and_availability_claims_are_not_trusted(self):
        out = self.preview(self.context(now='2099-01-01T00:00:00Z', freeSlot=True,
            visit_time_question=dict(requested_date='2099-01-02', availability_verified=True)))
        self.assertEqual(out['visit_time_question']['requested_date'], '2026-09-12')
        self.assertFalse(out['visit_time_question']['availability_verified'])

