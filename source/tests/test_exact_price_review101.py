"""A neural check cannot alter a tariff, but must allow its exact approved text."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
from assistant_store import Store
from extension_assistant import Assistant


class ExactPriceReviewTests(unittest.TestCase):
    def finalize(self, change=None, *, context=True, partner='7'):
        messages = [dict(id='c1', direction='in', body='Нужно настроить VPN к Wi-Fi в офисе.'),
                    dict(id='s1', direction='out', body='Когда вам удобно?'),
                    dict(id='c2', direction='in', body='Выезд на просчет работы бесплатный?')]
        ctx = dict(convId='synthetic-exact-price-review', dir='kp', city='Рязань', channel='avito',
                   partner=partner, accountTitle='Синтетический мастер КП',
                   itemTitle='Настройка роутера и Wi-Fi', messages=messages)
        with tempfile.TemporaryDirectory() as p:
            assistant = Assistant(Store(p + '/db'))
            preview, code = assistant.handle(dict(owner='offline', action='preview',
                                                  wording_mode='neural_review', ctx=ctx))
            self.assertEqual(code, 200)
            self.assertTrue(preview['pending_model'])
            task = json.loads(preview['model_task']['task'])
            fixed = task['fixed_reply']
            candidate = dict(reply=change(fixed) if change else fixed, needs_operator=False)
            if context:
                candidate['context_review'] = dict(last_intent='Уточнить оплату выезда для настройки VPN.',
                    latest_client_meaning='Клиент спрашивает, будет ли выезд на оценку бесплатным.',
                    selected_step_fits=True, evidence_ids=['c2'], note='Ответ объясняет условия выезда без обещания записи.')
                if task.get('diagnostic_fee_terms'):
                    candidate['context_review']['diagnostic_fee_review'] = dict(
                        amount_rub=1000,free_when='work_performed',diagnostic_result_sets_price=False)
            result, code = assistant.handle(dict(owner='offline', action='finalize',
                request_id=preview['request_id'], revision=preview['revision'], candidate=candidate))
            self.assertEqual(code, 200)
            self.assertFalse(result['auto_enabled'])
            self.assertFalse(result['lead']['can_create_automatically'])
        return result, fixed

    def test_exact_rule_approved_partner_fee_survives_neural_finalize(self):
        out, fixed = self.finalize()
        self.assertEqual(out['reply'], fixed)
        self.assertFalse(out['needs_operator'])
        self.assertFalse(out['validation'])
        self.assertIn('1000 рублей', out['reply'])

    def test_changed_amount_stays_rejected(self):
        out, _ = self.finalize(lambda fixed: fixed.replace('1000', '1500'))
        self.assertEqual(out['action'], 'handoff')
        self.assertEqual(out['reply'], '')
        self.assertIn('fixed_reply_changed', out['validation'])
        self.assertIn('unapproved_price', out['validation'])

    def test_extra_visit_promise_stays_rejected(self):
        out, _ = self.finalize(lambda fixed: fixed + ' Мастер точно приедет сегодня.')
        self.assertEqual(out['action'], 'handoff')
        self.assertIn('fixed_reply_changed', out['validation'])
        self.assertIn('unconfirmed_action_or_visit', out['validation'])

    def test_exact_price_still_requires_context_review(self):
        out, _ = self.finalize(context=False)
        self.assertEqual(out['action'], 'handoff')
        self.assertEqual(out['reply'], '')
        self.assertTrue(out['validation'])


if __name__ == '__main__':
    unittest.main()
