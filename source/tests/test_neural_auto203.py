"""Working mode is explicit, full-context and still subject to every veto/guard."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import assistant_policy
from assistant_store import Store
from extension_assistant import Assistant


class NeuralAuto203Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner',
            LEADBOT_PERSONAL_OPERATOR_ID='george', LEADBOT_PERSONAL_AUTO_AVAILABLE='1')
        env.start(); self.addCleanup(env.stop)
        self.app = Assistant(Store(self.temp.name + '/db'))
        self.body = dict(owner='owner', operator_id='george', browser_session='synthetic-auto:203')
        self.ctx = dict(convId='synthetic-neural-auto203', dir='kp', city='Чита', channel='avito',
            partner='7', accountTitle='Иван КП', accountId='synthetic-account', itemTitle='Компьютерный мастер',
            adIdentity='Иван', origin='С1', messages=[dict(id='in-1', direction='in', body='Компьютер не включается, я в Чите.')])

    def call(self, action, **extra):
        return self.app.handle({**self.body, 'action':action, 'ctx':self.ctx, **extra})

    def enable(self):
        start, _ = self.call('personal_start')
        result, _ = self.call('personal_mode', execution_mode='auto', confirmed=True,
            policy_ack=assistant_policy.VERSION, client_version='2.8.18', activation_nonce=start['activation_nonce'])
        self.assertTrue(result['auto_enabled'])

    def test_flags_or_review_lease_cannot_enable_working_mode(self):
        for flags in ({}, {'auto_enabled':True}, {'confirmed':True}):
            out, status = self.call('preview', wording_mode='neural_auto', **flags)
            self.assertEqual(status,403);self.assertFalse(out['ok'])
        self.call('personal_start')
        self.assertEqual(self.call('preview', wording_mode='neural_auto')[1],403)

    def test_current_auto_uses_full_history_and_independent_free_context_contract(self):
        self.enable()
        out, status = self.call('preview', wording_mode='neural_auto')
        self.assertEqual(status,200);self.assertTrue(out['pending_model'])
        task = json.loads(out['model_task']['task'])
        self.assertEqual([m['id'] for m in task['conversation']], ['in-1'])
        self.assertFalse(task['history_coverage']['truncated'])
        self.assertTrue(task['primary_sources'])
        self.assertFalse(out['requires_operator_review'])
        question = task['decision']['next_question']['question']
        candidate = dict(reply=question, needs_operator=False, context_review=dict(
            last_intent='Починить компьютер.',latest_client_meaning='Компьютер не включается, город Чита.',
            selected_step_fits=True,evidence_ids=['in-1'],note='Марка и модель ещё не указаны.'))
        result, status = self.call('finalize', request_id=out['request_id'], revision=out['revision'],candidate=candidate)
        self.assertEqual(status,200);self.assertEqual(result['validation'],[])
        self.assertFalse(result['requires_operator_review'])
        self.assertFalse(result['auto_enabled'])  # A draft itself never grants transport.

    def test_missing_free_review_or_provider_failure_cannot_bypass_context_validation(self):
        for failure in (None, 'transport', 'format'):
            with self.subTest(failure=failure):
                self.enable()
                self.ctx['convId'] += 'x'
                out, _ = self.call('preview', wording_mode='neural_auto')
                candidate = {} if failure else {'reply':'Марку и модель подскажите?', 'needs_operator':False}
                result, _ = self.call('finalize',request_id=out['request_id'], revision=out['revision'],
                    candidate=candidate,model_failure=failure)
                self.assertTrue(result['needs_operator']);self.assertEqual(result['reply'],'')

    def test_stop_other_tab_changed_actor_or_kill_switch_end_working_mode(self):
        self.enable()
        self.assertEqual(self.call('preview',wording_mode='neural_auto',browser_session='another:tab:203')[1],403)
        self.assertEqual(self.call('preview',wording_mode='neural_auto',operator_id='colleague')[1],403)
        with patch.dict(os.environ,LEADBOT_PERSONAL_AUTO_AVAILABLE='0'):
            self.assertEqual(self.call('preview',wording_mode='neural_auto')[1],403)
        self.call('personal_stop')
        self.assertEqual(self.call('preview',wording_mode='neural_auto')[1],403)


if __name__ == '__main__':
    unittest.main()
