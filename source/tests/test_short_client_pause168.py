"""Conversational grace, verified clocks and real saved-draft transitions."""
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
import os
import tempfile
import unittest
from unittest.mock import patch

import dialogue_lifecycle as lifecycle
from assistant_store import Store
from extension_assistant import Assistant


def client(mid, text, stamp, **extra):
    return dict(id=mid, direction='in', sender_type='client', body=text,
                created_at=stamp.isoformat(), **extra)


class ShortClientPause168Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner168', LEADBOT_PERSONAL_AUTO_AVAILABLE='0')
        env.start(); self.addCleanup(env.stop)
        self.path = tmp.name + '/db'
        self.app = Assistant(Store(self.path))
        self.start = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
        self.original_pause = lifecycle.short_client_pause
        self.original_observe = lifecycle.observe_short_pause

    @contextmanager
    def at(self, seconds):
        now = self.start + timedelta(seconds=seconds)
        with ExitStack() as stack:
            stack.enter_context(patch.object(lifecycle, 'short_client_pause', lambda messages, now=None: self.original_pause(messages, self.start + timedelta(seconds=seconds))))
            stack.enter_context(patch.object(lifecycle, 'observe_short_pause', lambda store, scope, chat, messages, now=None: self.original_observe(store, scope, chat, messages, self.start + timedelta(seconds=seconds))))
            yield now

    def context(self, pause='Секунду', **extra):
        # An old source date must not shorten a newly observed public pause.
        stamp = self.start - timedelta(days=30)
        messages = [client('job', 'Нужно подключить интернет в квартиру. Роутер TP-Link Archer A6 есть.', stamp),
                    dict(id='question', direction='out', sender_type='bot', body='Интернет от провайдера уже проведён в квартиру?',
                         created_at=(stamp + timedelta(seconds=5)).isoformat(), delivery_status='delivered'),
                    client('pause', pause, stamp + timedelta(seconds=10))]
        return dict(convId='synthetic-short-pause168', dir='kp', city='Ростов-на-Дону', channel='avito', partner='7',
                    accountTitle='Учебный КП', origin='synthetic-source', itemTitle='Настройка роутера', messages=messages, **extra)

    def preview(self, ctx):
        out, status = self.app.handle(dict(owner='owner168', action='preview', wording_mode='reviewed', ctx=ctx))
        self.assertEqual(status, 200)
        self.assertFalse(out['auto_enabled'])
        self.assertFalse(out['lead']['can_create_automatically'])
        return out

    def test_source542_short_pause_has_no_repeated_question_or_model(self):
        for text in ('Секунду', 'Минутку, пожалуйста', 'Подождите одну минуту', 'Можно секундочку?', 'Секунду, сейчас посмотрю'):
            with self.subTest(text=text), self.at(0):
                ctx = self.context(text); ctx['convId'] += text
                out = self.preview(ctx)
                self.assertEqual(out['action'], 'wait')
                self.assertFalse(out.get('pending_model'))
                self.assertFalse(out['reply'])
                self.assertEqual(out['client_short_pause_evidence']['status'], 'waiting')
                self.assertEqual(out['client_short_pause_evidence']['message_id'], 'pause')
                self.assertEqual(out['client_short_pause_evidence']['anchor_source'], 'server_first_observed')

    def test_pure_causal_clock_has_exact_bounded_interval_and_no_close_action(self):
        message = client('pause', 'Секунду', self.start)
        for seconds, expected in [(0, 'waiting'), (59.999, 'waiting'), (60, 'elapsed'), (3600, 'elapsed')]:
            with self.subTest(seconds=seconds):
                out = self.original_pause([message], self.start + timedelta(seconds=seconds))
                self.assertEqual(out['status'], expected)
                self.assertNotIn('action', out)
                self.assertEqual(out['grace_seconds'], 60)

    def test_quotes_negation_other_questions_and_other_roles_are_not_wait_requests(self):
        for text in ('«Секунду»', 'Не ждите минутку', 'Если скажу «секунду»', 'Секунду, сколько будет стоить?',
                     'Вы на минутку приезжаете?', 'Через минуту приедете?', 'Мне одну минуту чинить роутер', 'Сейчас'):
            self.assertEqual(self.original_pause([client('x', text, self.start)], self.start)['status'], 'not_applicable', text)
        for sender in ('operator', 'employee', 'bot', 'assistant', 'system', 'avito'):
            m = client('x', 'Секунду', self.start); m['sender_type'] = sender
            self.assertEqual(self.original_pause([m], self.start)['status'], 'not_applicable', sender)
        m = client('x', 'Секунду', self.start); m['direction'] = 'out'
        self.assertEqual(self.original_pause([m], self.start)['status'], 'not_applicable')

    def test_later_actual_answer_cancels_pause_immediately(self):
        with self.at(0):
            self.preview(self.context())
        ctx = self.context()
        ctx['messages'].append(client('answer', 'Да, интернет в квартире уже проведён.', self.start - timedelta(days=30) + timedelta(seconds=20)))
        with self.at(2):
            out = self.preview(ctx)
        self.assertIsNone(out.get('client_short_pause_evidence'))
        self.assertNotEqual(out.get('qualification', {}).get('internet', {}).get('status'), 'missing')

    def test_elapsed_phase_replaces_cached_wait_with_a_distinct_valid_saved_reply(self):
        ctx = self.context()
        with self.at(0): first = self.preview(ctx)
        with self.at(59): cached = self.preview(ctx)
        self.assertTrue(cached['cached'])
        self.assertEqual(first['request_id'], cached['request_id'])
        with self.at(60): after = self.preview(ctx)
        self.assertEqual(after['action'], 'question')
        self.assertIn('интернет', after['reply'].casefold())
        self.assertNotEqual(after['request_id'], first['request_id'])
        self.assertNotEqual(after['draft_id'], first['draft_id'])
        with self.at(61):
            actual, status = self.app.handle(dict(owner='owner168', action='validate', ctx=ctx, draft_id=after['draft_id']))
        self.assertEqual(status, 200)
        self.assertTrue(actual['ok'])
        self.assertEqual(actual['reply'], after['reply'])
        self.assertFalse(actual['auto_enabled'])

    def test_public_pause_survives_restart_without_restarting_clock(self):
        with self.at(0): self.preview(self.context())
        self.app = Assistant(Store(self.path))
        with self.at(61): out = self.preview(self.context())
        self.assertEqual(out['action'], 'question')
        self.assertIsNone(out.get('client_short_pause_evidence'))

    def test_forged_browser_anchor_is_ignored_and_missing_source_time_gets_server_anchor(self):
        ctx = self.context()
        ctx['messages'][-1].update(short_pause_observed_at='2000-01-01T00:00:00Z', short_pause_clock_unverified=False, created_at='')
        with self.at(0): out = self.preview(ctx)
        evidence = out['client_short_pause_evidence']
        self.assertEqual(evidence['status'], 'waiting')
        self.assertEqual(evidence['anchor_at'], '2026-10-22T00:00:00Z')
        self.assertEqual(evidence['due_at'], '2026-10-22T00:01:00Z')

    def test_missing_pure_clock_and_future_anchor_require_review_not_endless_wait(self):
        for stamp in ('', (self.start + timedelta(seconds=1)).isoformat(), 'invalid'):
            m = client('x', 'Секунду', self.start); m['created_at'] = stamp
            self.assertEqual(self.original_pause([m], self.start)['status'], 'unavailable')
        ctx = self.context(); ctx['messages'][-1]['id'] = ''
        with self.at(0): out = self.preview(ctx)
        self.assertEqual(out['action'], 'handoff')
        self.assertIn('VERIFY_SHORT_PAUSE_CLOCK', [g['id'] for g in out['decision_guards']])

    def test_existing_crm_and_max_exclusion_outrank_a_pause(self):
        for extra in (dict(crmRequestId='synthetic-order168'), dict(channel='max')):
            ctx = self.context(); ctx.update(extra)
            with self.at(0): out = self.preview(ctx)
            self.assertEqual(out['action'], 'handoff')
            self.assertIsNone(out.get('client_short_pause_evidence'))

    def test_server_anchor_is_isolated_by_owner_chat_and_original_message_identity(self):
        store = Store(self.path)
        stamp = self.start.timestamp()
        self.assertEqual(store.observe_short_pause('one', 'chat', 'message', stamp), stamp)
        self.assertEqual(store.observe_short_pause('one', 'chat', 'message', stamp + 30), stamp)
        for scope, chat, identity in [('two', 'chat', 'message'), ('one', 'other', 'message'), ('one', 'chat', 'new')]:
            self.assertEqual(store.observe_short_pause(scope, chat, identity, stamp + 30), stamp + 30)

    def test_a_pause_cannot_hide_branch_approval_from_the_manual_form(self):
        ctx = self.context(); ctx.update(dir='mnc', city='Москва', itemTitle='Мастер на час')
        ctx['messages'][0]['body'] = 'Установить видеодомофон'
        with self.at(0):
            out = self.preview(ctx)
            form, status = self.app.handle(dict(owner='owner168', action='checklist', ctx=ctx))
        self.assertEqual(out['action'], 'wait')
        self.assertEqual(out['service']['status'], 'agree')
        self.assertIn('OWNER-MNC-VIDEO-INTERCOM-20261022', out['rule_ids'])
        self.assertEqual(out['lifecycle']['disposition'], 'branch_approval')
        self.assertEqual(status, 200)
        self.assertTrue(form['approval'])

    def test_unread_media_and_foreign_owner_cannot_use_a_pause_to_skip_review(self):
        ctx = self.context()
        ctx['messages'][-1]['attachments'] = [dict(type='image', url='https://example.invalid/unread.jpg')]
        with self.at(0): out = self.preview(ctx)
        self.assertEqual(out['action'], 'handoff')
        self.assertIsNone(out.get('client_short_pause_evidence'))
        with patch.object(self.app.store, 'observe_short_pause') as observer:
            out, status = self.app.handle(dict(owner='foreign', action='preview', ctx=self.context()))
        self.assertEqual(status, 403)
        observer.assert_not_called()


if __name__ == '__main__':
    unittest.main()
