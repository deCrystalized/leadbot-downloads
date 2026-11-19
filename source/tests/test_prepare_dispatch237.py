import unittest
from unittest.mock import patch
import test_workflow as fixture_module


class PrepareDispatch237Tests(unittest.TestCase):
    def setUp(self):
        self.f = fixture_module.WorkflowTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)

    def grant_count(self):
        with self.f.app.store.connect() as db:
            return db.execute('SELECT count(*) FROM workflow_grants').fetchone()[0]

    def test_prepare_does_not_consume_grant_then_exact_final_dispatch_is_once(self):
        f = self.f
        ctx = f.ctx()
        ctx['assigneeId'] = ''
        with f.auto():
            op = f.operation(ctx, 'claim')
            for _ in range(2):
                result = f.call('personal_authorize', ctx=ctx, operation=dict(op, preflight_only=True))
                self.assertTrue(result['ok'], result)
                self.assertTrue(result['preflight_only'])
                self.assertFalse(result['execution_allowed'])
                self.assertFalse(result.get('permit'))
                self.assertEqual(self.grant_count(), 0)
            self.assertTrue(f.call('personal_authorize', ctx=ctx, operation=op)['execution_allowed'])
            self.assertEqual(self.grant_count(), 1)
            self.assertEqual(f.call('personal_authorize', ctx=ctx, operation=dict(op, preflight_only=True))['code'], 'already_started')
            self.assertEqual(f.call('personal_authorize', ctx=ctx, operation=op)['code'], 'already_started')

    def test_prepare_keeps_review_nonce_until_final_exact_review(self):
        f = self.f
        ctx = f.ctx()
        ctx['assigneeId'] = ''
        with patch.dict('os.environ', LEADBOT_PERSONAL_AUTO_AVAILABLE='1'):
            op = f.operation(ctx, 'claim')
            session = f.call('personal_status')
            approval = dict(confirmed=True, activation_nonce=session['activation_nonce'],
                            policy_ack=session['policy_version'], client_version='2.8.31')
            result = f.call('personal_review_authorize', ctx=ctx, operation=dict(op, preflight_only=True), **approval)
            self.assertTrue(result['ok'], result)
            self.assertFalse(result['execution_allowed'])
            self.assertEqual(f.call('personal_status')['activation_nonce'], session['activation_nonce'])
            self.assertEqual(self.grant_count(), 0)
            self.assertTrue(f.call('personal_review_authorize', ctx=ctx, operation=op, **approval)['execution_allowed'])
            self.assertNotEqual(f.call('personal_status')['activation_nonce'], session['activation_nonce'])

    def test_prepare_never_bypasses_auto_disabled(self):
        f = self.f
        ctx = f.ctx()
        ctx['assigneeId'] = ''
        result = f.call('personal_authorize', ctx=ctx, operation=dict(f.operation(ctx, 'claim'), preflight_only=True))
        self.assertFalse(result['ok'])
        self.assertFalse(result['execution_allowed'])

    def test_prepare_rejects_stale_source_and_wrong_operation(self):
        f = self.f
        ctx = f.ctx()
        ctx['assigneeId'] = ''
        with f.auto():
            op = f.operation(ctx, 'claim')
            for change in ({'revision': 'old'}, {'kind': 'create_crm'}, {'operation_id': 'forged'}):
                result = f.call('personal_authorize', ctx=ctx, operation=dict(op, preflight_only=True, **change))
                self.assertFalse(result['ok'], result)
                self.assertFalse(result['execution_allowed'])

    def test_prepare_flag_requires_exact_boolean(self):
        f = self.f
        ctx = f.ctx()
        ctx['assigneeId'] = ''
        with f.auto():
            op = f.operation(ctx, 'claim')
            for value in ('true', 1, {}, None):
                result = f.call('personal_authorize', ctx=ctx, operation=dict(op, preflight_only=value))
                self.assertFalse(result['ok'], result)
                self.assertEqual(result['code'], 'operation')

    def test_prepare_cannot_turn_a_bad_crm_form_into_permission(self):
        f = self.f
        ctx = f.ctx(True)
        with f.auto():
            op = dict(f.operation(ctx, 'create_crm'), preflight_only=True, proposal={'bad': 'form'}, snapshot_hash='forged')
            result = f.call('personal_authorize', ctx=ctx, operation=op)
            self.assertFalse(result['ok'], result)
            self.assertEqual(result['code'], 'crm_gate')
