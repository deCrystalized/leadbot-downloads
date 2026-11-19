"""Actual118 fee-reasoning failure and source-attribution controls."""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
from assistant_store import Store
from extension_assistant import Assistant


class DiagnosticReasoning119Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner')
        env.start(); self.addCleanup(env.stop)
        self.app = Assistant(Store(tmp.name+'/db'))

    def prepare(self, job=None, latest=None, direction='kp'):
        job = job or 'У меня принтер HP Deskjet 6075.'
        latest = latest or 'Другие мастера сказали, что принтер точно нерабочий. Поэтому уточняю стоимость диагностики.'
        ctx = dict(convId='synthetic-diagnostic-reasoning119', city='Оренбург', dir=direction, channel='avito',
                   partner='7', accountTitle='Учебный мастер', origin='С1',
                   itemTitle=dict(kp='Ремонт принтеров',bt='Ремонт холодильников',mnc='Услуги электрика')[direction],
                   messages=[dict(id='job',direction='in',body=job),
                             dict(id='staff',direction='out',body='Когда вам удобно?'),
                             dict(id='client',direction='in',body=latest)])
        out, code = self.app.handle(dict(owner='owner',action='preview',wording_mode='neural_review',ctx=ctx))
        self.assertEqual(code,200)
        self.assertTrue(out.get('pending_model'),out.get('reason'))
        self.assertFalse(out['auto_enabled'])
        return out,json.loads(out['model_task']['task'])

    def candidate(self, task):
        review = dict(last_intent='Узнать стоимость диагностики принтера',
                      latest_client_meaning='Клиент передаёт чужую оценку техники и уточняет стоимость диагностики',
                      selected_step_fits=True,evidence_ids=['client'],
                      note='Плата1000рублей; бесплатно только при фактическом выполнении работ.')
        if task.get('diagnostic_fee_terms'):
            review['diagnostic_fee_review']=dict(amount_rub=1000,free_when='work_performed',diagnostic_result_sets_price=False)
        if task.get('diagnostic_only_terms'):
            review['diagnostic_only_review']=dict(minimum_rub=500,price_kind='minimum',repair_requested=False)
        if task.get('reported_device_condition'):
            review['reported_condition_review']=dict(evidence_id='client',reported_by='other_specialists',verified_diagnosis=False)
        if task.get('item_fitment_context'):
            review['item_fitment_review'] = copy.deepcopy(task['item_fitment_context']['required_review'])
        return dict(reply=task['fixed_reply'],needs_operator=False,context_review=review)

    def finish(self, out, candidate):
        final, code = self.app.handle(dict(owner='owner',action='finalize',request_id=out['request_id'],
                                          revision=out['revision'],candidate=candidate))
        self.assertEqual(code,200)
        self.assertFalse(final['auto_enabled'])
        return final

    def test_wire_schema_and_valid_actual_protocol_have_explicit_price_condition(self):
        out,task=self.prepare()
        proof=out['model_task']['response_format']['schema']['properties']['context_review']['properties']['diagnostic_fee_review']
        self.assertEqual(proof['properties']['free_when']['enum'],['work_performed'])
        self.assertEqual(proof['properties']['diagnostic_result_sets_price']['enum'],[False])
        self.assertFalse(proof['additionalProperties'])
        self.assertFalse(task['reported_device_condition']['verified_diagnosis'])
        self.assertIsNone(task['reported_device_condition']['independent_client_problem'])
        self.assertEqual(task['reported_device_condition']['evidence_id'],'client')
        self.assertIn('diagnostic_fee_review',task['output_contract']['context_review_fields'])
        final=self.finish(out,self.candidate(task))
        self.assertTrue(final['reply']);self.assertEqual(final['validation'],[])

    def test_actual118_note_is_rejected_even_with_correct_new_structured_proof(self):
        out,task=self.prepare();c=self.candidate(task)
        c['context_review']['note']='Предложенный ответ корректно информирует о стоимости диагностики в зависимости от результата.'
        final=self.finish(out,c)
        self.assertFalse(final['reply'])
        self.assertIn('diagnostic_fee_result_dependency',final['validation'])

    def test_other_masters_opinion_cannot_become_a_verified_device_condition(self):
        out,task=self.prepare();c=self.candidate(task)
        c['context_review']['last_intent']='Диагностика неисправного принтера'
        final=self.finish(out,c)
        self.assertFalse(final['reply'])
        self.assertIn('unverified_third_party_device_condition',final['validation'])

    def test_original118_summary_cannot_turn_the_opinion_into_a_fault(self):
        out,task=self.prepare();c=self.candidate(task)
        c['context_review']['latest_client_meaning']='Клиент опасается напрасной диагностики неисправного принтера'
        final=self.finish(out,c)
        self.assertFalse(final['reply'])
        self.assertIn('unverified_third_party_device_condition',final['validation'])

    def test_source_proof_preserves_other_information_in_the_latest_message(self):
        out,task=self.prepare(latest='Другие мастера сказали, что принтер нерабочий. У меня нет картриджей. Какая цена?')
        self.assertNotIn('fixed_latest_client_meaning',task['output_contract'])
        c=self.candidate(task)
        c['context_review']['latest_client_meaning']='Передаёт чужое мнение о принтере, сообщает отсутствие картриджей и спрашивает цену диагностики'
        final=self.finish(out,c)
        self.assertTrue(final['reply']);self.assertEqual(final['validation'],[])

    def test_source_review_cannot_claim_a_verified_diagnosis(self):
        out,task=self.prepare();c=self.candidate(task)
        c['context_review']['reported_condition_review']['verified_diagnosis']=True
        final=self.finish(out,c)
        self.assertIn('reported_condition_review_mismatch',final['validation'])

    def test_wrong_type_or_condition_is_not_proof(self):
        for field,value in [('amount_rub',1000.0),('free_when','repair_possible'),('diagnostic_result_sets_price',True)]:
            with self.subTest(field=field):
                self.setUp()
                out,task=self.prepare();c=self.candidate(task);c['context_review']['diagnostic_fee_review'][field]=value
                final=self.finish(out,c)
                self.assertIn('diagnostic_fee_review_mismatch',final['validation'])

    def test_explicit_attribution_and_negated_dependency_are_allowed(self):
        out,task=self.prepare();c=self.candidate(task)
        c['context_review']['last_intent']='Диагностика принтера, который по словам других мастеров нерабочий'
        c['context_review']['note']='Цена не зависит от результата диагностики; бесплатно при выполнении работ.'
        final=self.finish(out,c)
        self.assertEqual(final['validation'],[]);self.assertTrue(final['reply'])

    def test_independent_client_symptom_is_preserved_without_asserting_a_diagnosis(self):
        out,task=self.prepare(job='Принтер не печатает. Можете провести диагностику принтера?')
        self.assertIsNotNone(task['reported_device_condition']['independent_client_problem'])
        c=self.candidate(task);c['context_review']['last_intent']='Диагностика принтера, который по словам клиента не печатает'
        final=self.finish(out,c)
        self.assertTrue(final['reply']);self.assertEqual(final['validation'],[])

    def test_fee_proof_does_not_spread_to_bt_mnc_or_non_fee_question(self):
        for direction,job in [('bt','Холодильник не морозит'),('mnc','Нужно заменить розетку')]:
            self.setUp()
            out,task=self.prepare(job=job,latest='Сколько стоит диагностика?',direction=direction)
            self.assertNotIn('diagnostic_fee_terms',task)
            self.assertNotIn('diagnostic_fee_review',task['output_contract']['context_review_fields'])
        self.setUp()
        out,task=self.prepare(job='Установить Windows11 на ноутбук',latest='Что по цене?')
        self.assertNotIn('diagnostic_fee_terms',task)


if __name__=='__main__':
    unittest.main()
