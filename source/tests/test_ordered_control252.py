"""Actual SQLite/session handler: command fencing is not action permission."""
import os
import unittest
from unittest.mock import patch

import assistant_policy
import operator_identity
import personal_assistant
import test_personal_assistant as sessions
import test_operator_identity203 as identities


class OrderedControl252Tests(unittest.TestCase):
    def setUp(self):
        self.f = sessions.PersonalTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.env = patch.dict(os.environ, {'LEADBOT_PERSONAL_AUTO_AVAILABLE': '1',
            'LEADBOT_REQUIRE_ORDERED_CONTROL': '1', 'LEADBOT_REQUIRE_ADMIN_AUTO': '0'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.start = self.call('personal_start', control_protocol='ordered_v1')

    def call(self, action, **extra):
        return personal_assistant.session(self.f.store, 'owner', action,
            {**self.f.identity, **extra}, now=101)

    def command(self, action, seq, **extra):
        return self.call(action, connection_epoch=self.start['connection_epoch'],
                         control_seq=seq, **extra)

    def auto(self, seq, **extra):
        current = self.call('personal_status')
        return self.command('personal_mode', seq, execution_mode='auto', confirmed=True,
            policy_ack=assistant_policy.VERSION, client_version='2.8.36',
            activation_nonce=current['activation_nonce'], **extra)

    def test_current_auto_still_requires_explicit_nonce_and_policy(self):
        self.assertFalse(self.start['auto_enabled'])
        missing = self.command('personal_mode', 1, execution_mode='auto')
        self.assertEqual(missing['code'], 'auto_activation')
        self.assertFalse(self.call('personal_status')['auto_enabled'])
        self.assertTrue(self.auto(2)['auto_enabled'])

    def test_latest_stop_wins_over_an_earlier_auto_with_same_connection(self):
        self.assertTrue(self.auto(1)['auto_enabled'])
        stopped = self.command('personal_stop', 3)
        self.assertFalse(stopped['active'])
        older = self.command('personal_mode', 2, execution_mode='review')
        self.assertEqual(older['code'], 'personal_expired')
        self.assertFalse(self.call('personal_status')['active'])

    def test_late_review_and_stop_cannot_mutate_a_reconnected_session(self):
        original = self.start
        self.start = self.call('personal_start', control_protocol='ordered_v1')
        self.assertGreater(self.start['connection_epoch'], original['connection_epoch'])
        enabled = self.auto(1)
        for action in ('personal_stop', 'personal_mode', 'personal_heartbeat'):
            out = self.call(action, connection_epoch=original['connection_epoch'],
                            control_seq=99, execution_mode='review')
            self.assertEqual(out['code'], 'personal_control_obsolete')
            self.assertEqual(out['mode_epoch'], enabled['mode_epoch'])
            self.assertEqual(self.call('personal_status')['activation_nonce'], enabled['activation_nonce'])
            self.assertTrue(self.call('personal_status')['auto_enabled'])

    def test_out_of_order_or_duplicate_command_never_rotates_nonce(self):
        enabled = self.auto(4)
        for seq in (1, 3, 4):
            out = self.command('personal_mode', seq, execution_mode='review')
            self.assertEqual(out['code'], 'personal_control_obsolete')
            current = self.call('personal_status')
            self.assertEqual(current['activation_nonce'], enabled['activation_nonce'])
            self.assertEqual(current['mode_epoch'], enabled['mode_epoch'])
            self.assertEqual(current['control_seq'], 4)

    def test_invalid_sequences_and_missing_or_wrong_connection_fail_closed(self):
        for seq in (None, True, 1.5, '1', 0, -1, 9007199254740992):
            self.assertEqual(self.command('personal_stop', seq)['code'], 'personal_control_obsolete')
        for conn in (None, True, '1', -1, self.start['connection_epoch'] + 1):
            out = self.call('personal_stop', connection_epoch=conn, control_seq=1)
            self.assertEqual(out['code'], 'personal_control_obsolete')
        current = self.call('personal_status')
        self.assertTrue(current['active'])
        self.assertEqual(current['control_seq'], 0)
        self.assertEqual(current['activation_nonce'], self.start['activation_nonce'])

    def test_newer_rejected_auto_intent_still_fences_an_older_auto(self):
        valid_nonce = self.start['activation_nonce']
        denied = self.command('personal_mode', 8, execution_mode='auto', confirmed=True,
            policy_ack=assistant_policy.VERSION, client_version='2.8.36', activation_nonce='invalid')
        self.assertEqual(denied['code'], 'auto_activation')
        old = self.command('personal_mode', 7, execution_mode='auto', confirmed=True,
            policy_ack=assistant_policy.VERSION, client_version='2.8.36', activation_nonce=valid_nonce)
        self.assertEqual(old['code'], 'personal_control_obsolete')
        self.assertFalse(self.call('personal_status')['auto_enabled'])

    def test_legacy_stop_cannot_bypass_fencing_or_downgrade_a_live_ordered_session(self):
        self.assertEqual(self.call('personal_stop')['code'], 'personal_control_obsolete')
        self.assertEqual(self.call('personal_start')['code'], 'personal_control_protocol')
        self.assertTrue(self.call('personal_status')['active'])

    def test_legacy_review_remains_available_but_strict_deployment_denies_auto(self):
        self.command('personal_stop', 1)
        legacy = self.call('personal_start')
        self.assertTrue(legacy['active'])
        denied = self.call('personal_mode', execution_mode='auto', confirmed=True,
            policy_ack=assistant_policy.VERSION, client_version='2.8.36',
            activation_nonce=legacy['activation_nonce'])
        self.assertEqual(denied['code'], 'personal_control_protocol')
        self.assertFalse(self.call('personal_status')['auto_enabled'])

    def test_different_browser_cannot_spend_current_connection_sequence(self):
        out = self.command('personal_stop', 100, browser_session='another:browser')
        self.assertEqual(out['code'], 'personal_expired')
        self.assertEqual(self.call('personal_status')['control_seq'], 0)

    def test_strict_deployment_revokes_an_already_active_legacy_Auto_session(self):
        self.command('personal_stop',1)
        with patch.dict(os.environ,{'LEADBOT_REQUIRE_ORDERED_CONTROL':'0'}):
            old=self.call('personal_start')
            enabled=self.call('personal_mode',execution_mode='auto',confirmed=True,
                policy_ack=assistant_policy.VERSION,client_version='2.8.35',activation_nonce=old['activation_nonce'])
            self.assertTrue(enabled['auto_enabled'])
        current=self.call('personal_status')
        self.assertFalse(current['auto_enabled'])
        self.assertFalse(current['auto_available'])
        self.assertGreater(current['mode_epoch'],enabled['mode_epoch'])


class IdentityTransaction252Tests(unittest.TestCase):
    def test_challenge_revocation_between_verification_and_session_write_is_rechecked(self):
        f = identities.OperatorIdentityTests()
        f.setUp()
        self.addCleanup(f.tearDown)
        original = operator_identity.verify

        def verified_then_revoked(*args, **kwargs):
            result = original(*args, **kwargs)
            self.assertIsNotNone(result)
            operator_identity.challenge(f.store, 'owner', f.body, 101)
            return result

        with patch.object(operator_identity, 'verify', side_effect=verified_then_revoked):
            out = personal_assistant.session(f.store, 'owner', 'personal_start',
                f.body_with_proof(control_protocol='ordered_v1'), now=101)
        self.assertFalse(out['ok'])
        self.assertEqual(out['code'], 'operator_identity')
        with f.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM personal_sessions').fetchone()[0], 0)
