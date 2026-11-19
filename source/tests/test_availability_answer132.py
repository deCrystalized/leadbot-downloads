"""A real Giga misunderstanding: furniture presence is not parts confirmation."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from assistant_store import Store
from extension_assistant import Assistant


class AvailabilityAnswer132Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner')
        env.start(); self.addCleanup(env.stop)
        self.app = Assistant(Store(tmp.name + '/db'))

    def prepare(self, answer='Да', question='У вас они в наличии уже?', job='Сколько стоит собрать шкаф?'):
        ctx = dict(convId='synthetic-availability132', city='Уфа', dir='mnc', channel='avito',
                   partner='7', accountTitle='Учебный мастер МНЧ', origin='С1', itemTitle='Сборка мебели',
                   messages=[dict(id='job', direction='in', body=job),
                             dict(id='staff', direction='out', body=question),
                             dict(id='client', direction='in', body=answer)])
        out, code = self.app.handle(dict(owner='owner', action='preview', wording_mode='neural_review', ctx=ctx))
        self.assertEqual(code, 200); self.assertTrue(out.get('pending_model'), out.get('reason'))
        return out, json.loads(out['model_task']['task'])

    def candidate(self, task):
        meaning = task['output_contract'].get('fixed_latest_client_meaning', 'Подтвердил наличие шкафа')
        return dict(reply=task['fixed_reply'], needs_operator=False, context_review=dict(
            last_intent='Узнать стоимость сборки шкафа', latest_client_meaning=meaning,
            selected_step_fits=True, evidence_ids=['client'],
            note='Вопрос об инструкции уместен. Наличие комплектующих не подтверждено.'))

    def finish(self, out, candidate):
        final, code = self.app.handle(dict(owner='owner', action='finalize', request_id=out['request_id'],
                                          revision=out['revision'], candidate=candidate))
        self.assertEqual(code, 200); self.assertFalse(final['auto_enabled'])
        return final

    def test_original_giga_misunderstanding_is_rejected_before_reply(self):
        out, task = self.prepare(); candidate = self.candidate(task)
        candidate['context_review']['latest_client_meaning'] = 'Подтвердил наличие комплектующих для шкафа'
        result = self.finish(out, candidate)
        self.assertFalse(result['reply'])
        self.assertIn('availability_answer_meaning_mismatch', result['validation'])

    def test_native_schema_binds_short_answer_to_observed_question(self):
        out, task = self.prepare(); context = task['availability_answer_context']
        self.assertEqual(context['question_evidence_id'], 'staff')
        self.assertEqual(context['answer_evidence_id'], 'client')
        self.assertEqual(context['question_quote'], 'У вас они в наличии уже?')
        self.assertFalse(context['extra_conditions_confirmed'])
        meaning = task['output_contract']['fixed_latest_client_meaning']
        self.assertIn('«Да»', meaning); self.assertIn('«У вас они в наличии уже?»', meaning)
        schema = out['model_task']['response_format']['schema']['properties']['context_review']['properties']
        self.assertEqual(schema['latest_client_meaning']['enum'], [meaning])
        self.assertLess(list(task).index('availability_answer_context'), list(task).index('primary_sources'))

    def test_grounded_context_and_necessary_followup_remain_accepted(self):
        out, task = self.prepare(); result = self.finish(out, self.candidate(task))
        self.assertTrue(result['reply']); self.assertEqual(result['validation'], [])
        self.assertNotIn('город', result['reply'].lower())

    def test_correct_meaning_cannot_hide_parts_claim_in_note(self):
        out, task = self.prepare(); candidate = self.candidate(task)
        candidate['context_review']['note'] = 'Клиент подтвердил наличие комплектующих, поэтому уточняем схему.'
        result = self.finish(out, candidate)
        self.assertFalse(result['reply'])
        self.assertIn('unconfirmed_availability_subject', result['validation'])

    def test_correct_meaning_cannot_hide_instruction_claim_in_intent(self):
        out, task = self.prepare(); candidate = self.candidate(task)
        candidate['context_review']['last_intent'] = 'Сборка шкафа, инструкция есть'
        result = self.finish(out, candidate)
        self.assertFalse(result['reply'])
        self.assertIn('unconfirmed_availability_subject', result['validation'])

    def test_future_followup_does_not_excuse_an_unfounded_presence_claim(self):
        out, task = self.prepare(); candidate = self.candidate(task)
        candidate['context_review']['note'] = 'Уточняем схему поскольку комплектующие уже есть'
        result = self.finish(out, candidate)
        self.assertFalse(result['reply'])
        self.assertIn('unconfirmed_availability_subject', result['validation'])

    def test_in_stock_paraphrase_is_also_a_presence_claim(self):
        out, task = self.prepare(); candidate = self.candidate(task)
        candidate['context_review']['note'] = 'Материалы уже в наличии'
        result = self.finish(out, candidate)
        self.assertFalse(result['reply'])
        self.assertIn('unconfirmed_availability_subject', result['validation'])

    def test_a_proposed_question_is_not_a_presence_claim(self):
        out, task = self.prepare(); candidate = self.candidate(task)
        candidate['context_review']['note'] = 'Следующий вопрос уместен: инструкция есть?'
        result = self.finish(out, candidate)
        self.assertTrue(result['reply']); self.assertEqual(result['validation'], [])

    def test_explicit_parts_question_is_not_erased(self):
        out, task = self.prepare(question='Комплектующие у вас в наличии?')
        self.assertNotIn('availability_answer_context', task)
        candidate = self.candidate(task)
        candidate['context_review']['latest_client_meaning'] = 'Клиент подтвердил наличие комплектующих'
        candidate['context_review']['note'] = 'Клиент подтвердил наличие комплектующих; инструкция ещё не подтверждена.'
        result = self.finish(out, candidate)
        self.assertTrue(result['reply']); self.assertEqual(result['validation'], [])

    def test_explicitly_named_lock_keeps_its_normal_context_contract(self):
        _, task = self.prepare(question='Новый замок у вас есть?', job='Нужно поменять замок двери.')
        self.assertNotIn('availability_answer_context', task)

    def test_extra_client_information_is_not_replaced_by_short_answer_contract(self):
        _, task = self.prepare(answer='Да, но инструкции нет')
        self.assertNotIn('availability_answer_context', task)
        self.assertNotIn('fixed_latest_client_meaning', task['output_contract'])

    def test_appointment_yes_is_not_an_availability_question(self):
        _, task = self.prepare(question='Когда удобно принять?', answer='Да')
        self.assertNotIn('availability_answer_context', task)

    def test_initial_request_has_no_invented_previous_question(self):
        ctx = dict(convId='synthetic-availability132-first', city='Уфа', dir='mnc', channel='avito',
                   partner='7', accountTitle='Учебный мастер МНЧ', origin='С1', itemTitle='Сборка мебели',
                   messages=[dict(id='client', direction='in', body='Сколько стоит собрать шкаф?')])
        out, code = self.app.handle(dict(owner='owner', action='preview', wording_mode='neural_review', ctx=ctx))
        self.assertEqual(code, 200)
        self.assertNotIn('availability_answer_context', json.loads(out['model_task']['task']))
