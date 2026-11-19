"""Source roles retain full forms and independent decisions without adding jobs."""
import copy
import json
import unittest

from extension_assistant import _context_review
import test_questionnaire_scope201 as prior
from test_assistant import context, message


class QuestionnaireSourceRoles202Tests(unittest.TestCase):
    setUp = prior.ActualQuestionnaireScope201Tests.setUp
    candidate = prior.ActualQuestionnaireScope201Tests.candidate

    def preview(self, rows):
        original = copy.deepcopy(rows)
        out, status = self.app.handle(dict(owner='owner', action='preview', wording_mode='neural_review',
            ctx=context(rows, dir='mnc', city='Оренбург', accountTitle='Учебный мастер', itemTitle='Мастер на час')))
        self.assertEqual(status, 200)
        self.assertEqual(rows, original)
        self.assertTrue(out.get('pending_model'), out.get('reason'))
        return out, json.loads(out['model_task']['task'])

    def rows(self):
        return [message(prior.FORM, mid='form'),
                message('Нужно собрать и повесить подвесную тумбочку', mid='detail')]

    def test_full_form_and_other_fields_are_not_replaced_by_annotation(self):
        rows=self.rows();rows[0]['body'] += '\nЦена обсуждается\nКомментарий о безопасной сделке'
        _,task=self.preview(rows)
        self.assertEqual([r['body'] for r in task['conversation']], [r['body'] for r in rows])
        self.assertEqual(task['conversation'][0]['source_roles']['fields'][0]['quote'], 'Полку, навесные шкафы')
        self.assertFalse(task['conversation'][0]['source_roles']['fields'][0]['each_label_member_ordered'])

    def test_operations_preserve_both_assembly_and_hanging(self):
        _,task=self.preview(self.rows())
        source=task['conversation'][1]['source_roles']['fields'][0]
        self.assertEqual(source['operations'], ['собрать', 'повесить'])
        self.assertTrue(source['operations_are_literal_words_not_item_pairs'])
        self.assertEqual(source['quote'], 'Нужно собрать и повесить подвесную тумбочку')

    def test_form_comment_is_preserved_as_real_request_alongside_category(self):
        form=prior.FORM.replace('✨Задача составлена', 'Комментарий:\nТакже нужно повесить полку\n✨Задача составлена')
        _,task=self.preview([message(form, mid='form'),self.rows()[1]])
        roles=task['conversation'][0]['source_roles']['fields']
        self.assertEqual([r['kind'] for r in roles], ['grouped_questionnaire_category','literal_client_work_request'])
        self.assertIn('shelf',task['questionnaire_item_scope']['active_item_families'])
        self.assertNotIn('shelf',task['questionnaire_item_scope']['category_only_item_families'])

    def test_later_additional_shelf_still_admitted_by_semantic_guard(self):
        _,task=self.preview(self.rows()+[message('И полку тоже',mid='extra')])
        candidate=self.candidate(task)
        candidate['context_review'].update(last_intent='Собрать тумбу и повесить полку',
            latest_client_meaning='Просит также повесить полку', evidence_ids=['extra'])
        self.assertEqual(_context_review(candidate,task)[1:],('provided',[]))
        self.assertEqual(task['conversation'][-1]['source_roles']['fields'][0]['quote'],'И полку тоже')

    def test_stock_answer_does_not_gain_service_request_role(self):
        rows=self.rows()+[message('У вас всё в наличии?',direction='out',mid='stock-question'),
                          message('Да, конечно',mid='stock')]
        _,task=self.preview(rows)
        self.assertNotIn('source_roles',task['conversation'][-1])
        self.assertNotIn('source_roles',task['conversation'][-2])
        self.assertEqual(task['questionnaire_item_scope']['active_item_families'],['pedestal'])

    def test_future_detail_is_not_imported_into_initial_form(self):
        out,task=self.preview([self.rows()[0]])
        self.assertNotIn('questionnaire_item_scope',task)
        self.assertNotIn('source_roles',task['conversation'][0])
        self.assertFalse(out['model_task']['system'].startswith('Сначала различи роли исходных сообщений'))

    def test_failed_or_quoted_extra_does_not_become_literal_request(self):
        rows=self.rows()+[dict(message('Также повесить полку',mid='failed'),delivery_status='failed'),
                          message('Сосед сказал: «Нужно собрать шкаф»',mid='quote')]
        _,task=self.preview(rows)
        self.assertEqual(task['questionnaire_item_scope']['active_item_families'],['pedestal'])
        self.assertFalse(any('source_roles' in r for r in task['conversation'][2:]))

    def test_free_goal_schema_is_not_enumerated_or_replaced_by_new_receipt(self):
        out,task=self.preview(self.rows())
        schema=out['model_task']['response_format']['schema']['properties']
        review=schema['context_review']['properties']
        self.assertEqual(set(review),set(task['output_contract']['context_review_fields']))
        self.assertNotIn('enum',review['last_intent'])
        for key in ('last_intent','latest_client_meaning','note'):
            self.assertIn('Групповая категория',review[key]['description'])
        self.assertNotIn('questionnaire_item_review',review)
        self.assertEqual(out['model_task']['max_tokens'],700)

    def test_correct_goal_and_justified_veto_remain_independent(self):
        _,task=self.preview(self.rows())
        candidate=self.candidate(task)
        self.assertEqual(_context_review(candidate,task)[1:],('provided',[]))
        candidate.update(reply='',needs_operator=True)
        candidate['context_review'].update(selected_step_fits=False,note='Предложение требует проверки')
        self.assertEqual(_context_review(candidate,task)[1:],('provided',['model_context_mismatch']))

    def test_category_expansion_remains_rejected_without_repairing_candidate(self):
        _,task=self.preview(self.rows())
        candidate=self.candidate(task)
        candidate['context_review']['last_intent']='Сборка и навес полок, шкафов и тумбы'
        before=copy.deepcopy(candidate)
        self.assertEqual(_context_review(candidate,task)[1:],('inconsistent',['questionnaire_category_as_extra_work']))
        self.assertEqual(candidate,before)

    def test_duplicate_ids_use_distinct_source_positions(self):
        rows=self.rows();rows[1]['id']='form'
        _,task=self.preview(rows)
        self.assertNotEqual(task['questionnaire_item_scope']['category']['evidence_id'],
            task['questionnaire_item_scope']['client_requests'][0]['evidence_id'])
        self.assertEqual(task['conversation'][0]['source_roles']['fields'][0]['kind'],'grouped_questionnaire_category')
        self.assertEqual(task['conversation'][1]['source_roles']['fields'][0]['kind'],'literal_client_work_request')

    def test_new_enquiry_cannot_inherit_old_category_constraint(self):
        _,task=self.preview(self.rows()+[message('Новая заявка: нужно собрать шкаф',mid='new')])
        self.assertNotIn('questionnaire_item_scope',task)
        self.assertFalse(any('source_roles' in r for r in task['conversation']))


if __name__ == '__main__':
    unittest.main()
