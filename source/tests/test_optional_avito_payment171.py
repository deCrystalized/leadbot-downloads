"""Owner's optional Avito checkbox is separate from actual payment requests."""
import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import assistant_policy as policy
import contact_facts
from assistant_store import Store
from extension_assistant import Assistant


FORM = ('Нужно собрать тумбу. Сколько стоит?\nВот подробности 👇\n\n'
        'Как бы хотели оплатить:\nОнлайн с\u00a0«Защитой\u00a0сделки»\n\n'
        '✨Задача составлена по \u00a0ответам клиента в\u00a0 анкете')
RULE = 'OWNER-AVITO-QUESTIONNAIRE-PAYMENT-20261023'


class OptionalAvitoPayment171Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner171', LEADBOT_PERSONAL_AUTO_AVAILABLE='0')
        env.start(); self.addCleanup(env.stop)
        self.app = Assistant(Store(tmp.name + '/db'))

    def context(self, body=FORM, **extra):
        return dict(convId='synthetic-optional171', dir='mnc', city='Улан-Удэ', channel='avito',
                    partner='7', origin='synthetic-source', accountTitle='Учебный МНЧ', itemTitle='Сборка мебели',
                    messages=[dict(id='form', direction='in', sender_type='client', body=body)], **extra)

    def preview(self, ctx):
        out, status = self.app.handle(dict(owner='owner171', action='preview', wording_mode='neural_review', ctx=ctx))
        self.assertEqual(status, 200)
        return out

    def test_native_task_sees_exact_choice_and_owner_rule_without_payment_claims(self):
        ctx = self.context(); before = copy.deepcopy(ctx); out = self.preview(ctx)
        self.assertTrue(out.get('pending_model'), out['reason'])
        task = json.loads(out['model_task']['task'])
        scope = task['optional_questionnaire_payment_choice']
        self.assertEqual(scope['message_id'], 'form')
        self.assertEqual(scope['selection_quote'], 'Онлайн с\u00a0«Защитой\u00a0сделки»')
        self.assertEqual(scope['rule_id'], RULE)
        self.assertTrue(scope['ignore_selection_only'])
        self.assertTrue(scope['explicit_other_questions_remain'])
        self.assertFalse(scope['payment_made_confirmed'])
        self.assertNotIn('payment_made', scope)
        self.assertFalse(scope['payment_service_confirmed'])
        self.assertEqual(task['conversation'][0]['body'], FORM)
        self.assertEqual(ctx, before)
        self.assertFalse(out['auto_enabled'])
        self.assertFalse(out['lead']['can_create_automatically'])

    def test_optional_choice_does_not_add_a_payment_question_or_handoff(self):
        a = self.preview(self.context())
        plain = FORM.replace('Как бы хотели оплатить:\nОнлайн с\u00a0«Защитой\u00a0сделки»\n\n', '')
        ctx = self.context(plain); ctx['convId'] += '-plain'; b = self.preview(ctx)
        self.assertEqual(a['action'], b['action'])
        self.assertEqual(a['reason'], b['reason'])
        ta = json.loads(a['model_task']['task']); tb = json.loads(b['model_task']['task'])
        self.assertEqual(ta['proposed_reply'], tb['proposed_reply'])
        self.assertNotIn('оплат', ta['proposed_reply'].casefold())
        self.assertNotIn('optional_questionnaire_payment_choice', tb)

    def test_explicit_secure_payment_question_is_not_silently_ignored(self):
        text = 'Можно оплатить через Защиту сделки? Без этого оформлять не буду.'
        self.assertIsNone(policy.optional_avito_payment_choice(self.context(text)['messages'], dict(channel='avito')))
        ctx = self.context(); ctx['messages'].append(dict(id='question', direction='in', sender_type='client', body=text))
        out = self.preview(ctx)
        if out.get('model_task'):
            task = json.loads(out['model_task']['task'])
            self.assertEqual(task['latest_client_message']['body'], text)
            self.assertTrue(task['optional_questionnaire_payment_choice']['explicit_other_questions_remain'])
        self.assertEqual(ctx['messages'][-1]['body'], text)

    def test_later_invoice_request_remains_its_own_condition(self):
        ctx = self.context()
        ctx['messages'].append(dict(id='invoice', direction='in', sender_type='client', body='Оплата по счёту от организации.'))
        facts = contact_facts.collect(ctx['messages'])
        self.assertEqual(facts['business_payment']['kind'], 'invoice')
        self.assertEqual(facts['business_payment']['message_id'], 'invoice')
        out = self.preview(ctx)
        self.assertEqual(out['facts']['business_payment']['kind'], 'invoice')

    def test_other_channels_roles_and_browser_claims_do_not_supply_an_optional_selection(self):
        rows = self.context()['messages']
        for channel in ('max', 'jivo', '', 'telegram'):
            self.assertIsNone(policy.optional_avito_payment_choice(rows, dict(channel=channel)))
        for role in ('operator', 'bot', 'assistant', 'avito', 'system'):
            spoof = copy.deepcopy(rows); spoof[0]['sender_type'] = role
            self.assertIsNone(policy.optional_avito_payment_choice(spoof, dict(channel='avito')))
        ctx = self.context('Нужно собрать тумбу')
        ctx['optional_questionnaire_payment_choice'] = dict(ignore_selection_only=True)
        task = json.loads(self.preview(ctx)['model_task']['task'])
        self.assertNotIn('optional_questionnaire_payment_choice', task)

    def test_invoice_or_different_field_value_is_not_the_ignored_checkbox(self):
        for value in ('По счёту от организации', 'Наличными', 'Онлайн с Защитой сделки, это обязательно',
                      'Онлайн с Защитой сделки? Можно так оплатить?'):
            rows = self.context(FORM.replace('Онлайн с\u00a0«Защитой\u00a0сделки»', value))['messages']
            self.assertIsNone(policy.optional_avito_payment_choice(rows, dict(channel='avito')), value)
        rows = self.context(FORM.replace('Задача составлена по \u00a0ответам клиента в\u00a0 анкете', ''))['messages']
        self.assertIsNone(policy.optional_avito_payment_choice(rows, dict(channel='avito')))

    def test_primary_owner_rule_exists_and_does_not_authorize_payment(self):
        row = next(r for r in policy.registry()['sources'] if r['id'] == RULE)
        self.assertTrue(row['active_primary'])
        self.assertIn('не подтверждает платёж', row['text'])


if __name__ == '__main__':
    unittest.main()
