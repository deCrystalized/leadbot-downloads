"""Offline semantic controls for taking a job versus supplying its materials.

Native candidates below are explicitly manual synthetic reviews, not model calls.
"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import assistant_policy as policy
import contact_facts
from assistant_store import Store
from extension_assistant import Assistant


ACK = 'Да, помогу.'
MATERIALS = 'По материалам смогу сориентировать после осмотра.'


def messages(*bodies):
    return [dict(id='client-'+str(i), direction='in', body=body)
            for i, body in enumerate(bodies)]


class CapabilityMaterials514Tests(unittest.TestCase):
    def test_reflexive_taking_the_job_is_not_an_inventory_question(self):
        for tail in ['Возьмётесь?', 'Возьметесь?', 'Возьмитесь за замену проводов.']:
            with self.subTest(tail=tail):
                replies = policy.service_expectation_questions(messages(
                    'Нужно поменять провода и собрать в распаячную коробку', tail))
                self.assertNotIn(MATERIALS, replies)
                self.assertIn(ACK, replies)

    def test_genuine_split_materials_request_keeps_inspection_answer(self):
        replies = policy.service_expectation_questions(messages(
            'Провод возьмёте с собой', 'И розетки', '?'))
        self.assertEqual(replies, [MATERIALS])

    def test_own_materials_do_not_turn_into_our_stock(self):
        replies = policy.service_expectation_questions(messages(
            'Провод и коробку уже купил сам.', 'Возьмётесь?'))
        self.assertEqual(replies, [ACK])

    def test_attributed_question_is_not_the_clients_inventory_request(self):
        quoted = 'Другой мастер спросил: «Провод возьмёте с собой?»'
        self.assertEqual(policy.service_expectation_questions(messages(quoted)), [])
        self.assertEqual(policy.service_expectation_questions(messages(
            quoted, 'Нужно заменить участок. Возьмётесь?')), [ACK])

    def test_direct_materials_question_after_quote_is_preserved(self):
        replies = policy.service_expectation_questions(messages(
            'Другой мастер спросил: «Провод возьмёте с собой?» '
            'А вы привезёте розетки?'))
        self.assertEqual(replies, [MATERIALS])

    def test_buying_and_reflexive_verb_are_distinct(self):
        self.assertEqual(policy.service_expectation_questions(messages(
            'Купите провод?')), [MATERIALS])
        self.assertEqual(policy.service_expectation_questions(messages(
            'Вы купитесь на условие про провод и розетки?')), [])

    def test_answered_inventory_question_does_not_repeat(self):
        rows = messages('Провод возьмёте с собой?')
        rows.append(dict(id='staff', direction='out', body='Уточню после осмотра.'))
        rows.extend(messages('Нужно заменить участок. Возьмётесь?'))
        self.assertEqual(policy.service_expectation_questions(rows), [ACK])

    def test_buying_or_delivery_is_not_accepted_as_the_service(self):
        for body in ['Возьмётесь купить провод?',
                     'Возьмётесь за работу по доставке проводов?',
                     'Нужно купить провод. Возьмётесь?']:
            with self.subTest(body=body):
                self.assertNotIn(ACK, policy.service_expectation_questions(messages(body)))

    def test_prohibited_work_keeps_refusal_despite_capability_question(self):
        rows = messages('На экране телевизора полосы. Хочу ремонт. Возьмётесь?')
        known = dict(direction='kp', channel='avito', partner='7', city='Коломна',
                     title='Ремонт телевизоров', account_name='Учебный мастер')
        result = policy.assess(rows, known, contact_facts.collect(rows, known))
        self.assertEqual(result['action'], 'refuse')
        self.assertIn('OWNER-TV-BANDS-20261017', result['rule_ids'])
        self.assertNotIn(ACK, result['required_text'])

    def test_acceptance_does_not_weaken_inventory_or_outcome_guards(self):
        self.assertEqual(policy.service_expectation_violations(ACK), [])
        self.assertIn('unconfirmed_materials_promise',
                      policy.service_expectation_violations('Да, помогу. Привезу провод.'))
        self.assertIn('unconfirmed_repair_outcome',
                      policy.service_expectation_violations('Да, помогу. Сделаю за один выезд.'))


class CapabilityMaterials514NativeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner',
                         LEADBOT_PERSONAL_AUTO_AVAILABLE='0')
        env.start()
        self.addCleanup(env.stop)
        self.app = Assistant(Store(temp.name+'/db'))

    def finalize_manual(self, latest):
        rows = messages('Нужно поменять провода и собрать в распаячную коробку', latest)
        ctx = dict(convId='synthetic-capability-materials514', city='Коломна', dir='mnc',
                   channel='avito', partner='7', accountTitle='Учебный мастер', origin='С1',
                   itemTitle='Услуги электрика', messages=rows)
        preview, status = self.app.handle(dict(owner='owner', action='preview',
                                               wording_mode='neural_review', ctx=ctx))
        self.assertEqual(status, 200)
        self.assertTrue(preview.get('pending_model'), preview.get('reason'))
        self.assertFalse(preview['auto_enabled'])
        task = json.loads(preview['model_task']['task'])
        question = task['decision']['next_question']['question']
        self.assertEqual(question, 'Где расположен щиток или автомат?')
        candidate = dict(reply=question, needs_operator=False, context_review=dict(
            last_intent='Заменить участок проводов и собрать в коробку',
            latest_client_meaning=('Клиент спрашивает, возьмёмся ли за названную работу'
                                   if latest == 'Возьмётесь?' else
                                   'Клиент спрашивает, привезём ли провод'),
            selected_step_fits=True, evidence_ids=[rows[-1]['id']],
            note='Ручной синтетический review; без обещания запаса, диагноза или результата.'))
        final, code = self.app.handle(dict(owner='owner', action='finalize',
            request_id=preview['request_id'], revision=preview['revision'], candidate=candidate))
        self.assertEqual(code, 200)
        self.assertEqual(final['validation'], [])
        self.assertFalse(final['needs_operator'])
        self.assertFalse(final['auto_enabled'])
        return final['reply']

    def test_native_finalize_keeps_acceptance_and_required_next_step(self):
        reply = self.finalize_manual('Возьмётесь?')
        self.assertIn(ACK, reply)
        self.assertIn('Где расположен щиток или автомат?', reply)
        self.assertNotIn(MATERIALS, reply)
        self.assertEqual(policy.service_expectation_violations(reply), [])

    def test_native_real_inventory_question_keeps_safe_answer(self):
        reply = self.finalize_manual('Провод возьмёте с собой?')
        self.assertIn(MATERIALS, reply)
        self.assertIn('Где расположен щиток или автомат?', reply)
        self.assertNotIn(ACK, reply)


if __name__ == '__main__':
    unittest.main()
