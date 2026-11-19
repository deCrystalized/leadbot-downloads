"""A grouped task category is not extra work after a specific client request."""
import copy
import json
import unittest

import assistant_catalog as catalog
from extension_assistant import _context_review
import test_onsite_only114 as helper
from test_assistant import context, message


FORM = ('Повесить предметы интерьера\nВот подробности 👇\n\nКакие работы нужны:\n'
        '- Повесить предметы интерьера\n\nЧто повесить:\n- Полку, навесные шкафы\n\n'
        'Когда нужна услуга:\nКак можно скорее\n\n'
        '✨Задача составлена по ответам клиента в анкете')


def row(body, ident='detail', role='client', **extra):
    return dict(body=body, id=ident, evidence_id=ident, position=0,
                direction='in' if role == 'client' else 'out', speaker_role=role, **extra)


def scope(*rows):
    return catalog.questionnaire_item_scope([row(FORM, 'form'), *rows])


class QuestionnaireScope201Tests(unittest.TestCase):
    def test_before_specific_detail_category_stays_unresolved(self):
        self.assertIsNone(scope())
        self.assertIsNone(scope(row('Да, конечно')))

    def test_one_cabinet_preserves_both_operations_and_exact_source(self):
        actual = scope(row('Здравствуйте! Нужно собрать и повесить подвесную тумбочку'))
        self.assertEqual(actual['active_item_families'], ['pedestal'])
        self.assertEqual(actual['category_only_item_families'], ['shelf'])
        detail = actual['client_requests'][0]
        self.assertEqual(detail['evidence_id'], 'detail')
        self.assertIn('собрать', detail['operations']);self.assertIn('повесить', detail['operations'])
        self.assertIn('подвесную тумбочку', detail['quote'])
        self.assertEqual(actual['source'], 'server_literal_request_scope_not_model_understanding')

    def test_reverse_word_order_is_still_literal_same_item(self):
        actual = scope(row('Подвесную тумбочку нужно собрать и повесить'))
        self.assertEqual(actual['active_item_families'], ['pedestal'])

    def test_stock_answer_cannot_restore_category_items(self):
        actual = scope(row('Нужно собрать и повесить тумбу'), row('У вас всё в наличии?', 'staff', 'staff'),
                       row('Да, конечно', 'stock'))
        self.assertEqual(actual['category_only_item_families'], ['shelf'])
        self.assertEqual(len(actual['client_requests']), 1)

    def test_two_explicit_items_are_not_reduced_to_one(self):
        actual = scope(row('Нужно собрать шкаф и повесить две полки'))
        self.assertEqual(actual['active_item_families'], ['cabinet', 'shelf'])
        self.assertEqual(actual['category_only_item_families'], [])
        self.assertIn('две полки', actual['client_requests'][0]['quote'])

    def test_explicit_additional_job_survives_later_stock_reply(self):
        actual = scope(row('Нужно собрать тумбу'), row('Также нужно повесить полку', 'extra'), row('Всё есть', 'stock'))
        self.assertIn('shelf', actual['active_item_families'])
        self.assertIn('pedestal', actual['active_item_families'])

    def test_bare_explicit_additional_item_does_not_get_lost(self):
        actual = scope(row('Нужно собрать и повесить тумбу'), row('И полку тоже', 'extra'))
        self.assertIn('shelf', actual['active_item_families'])
        self.assertEqual(actual['client_requests'][-1]['operations'], [])

    def test_form_comment_is_real_customer_work_not_category(self):
        form = FORM.replace('✨Задача составлена', 'Комментарий:\nТакже нужно повесить полку\n✨Задача составлена')
        actual = catalog.questionnaire_item_scope([row(form, 'form'), row('Нужно собрать тумбу')])
        self.assertEqual(actual['active_item_families'], ['pedestal', 'shelf'])
        self.assertEqual(actual['client_requests'][0]['evidence_id'], 'form')

    def test_later_request_is_not_blind_last_noun_replacement(self):
        actual = scope(row('Нужно собрать тумбу'), row('Ещё повесить шкаф', 'extra'))
        self.assertEqual(actual['active_item_families'], ['cabinet', 'pedestal'])

    def test_instead_replaces_only_named_item_not_other_jobs(self):
        actual = scope(row('Нужно собрать шкаф и повесить полку'), row('Вместо полки собрать тумбу', 'correction'))
        self.assertEqual(actual['active_item_families'], ['cabinet', 'pedestal'])

    def test_explicit_only_item_can_narrow_previous_request(self):
        actual = scope(row('Нужно собрать шкаф и повесить полку'), row('Нужно собрать только тумбу', 'correction'))
        self.assertEqual(actual['active_item_families'], ['pedestal'])

    def test_only_operation_does_not_erase_other_requested_item(self):
        actual = scope(row('Нужно собрать тумбу и повесить полку'), row('Тумбу только повесить', 'correction'))
        self.assertIn('shelf', actual['active_item_families'])

    def test_staff_service_and_bot_cannot_supply_specific_request(self):
        for role in ('staff', 'service', 'automation'):
            self.assertIsNone(scope(row('Нужно собрать тумбу', role=role)), role)

    def test_failed_pending_and_queued_cannot_supply_request(self):
        for delivery in ('failed', 'pending', 'queued', 'sending'):
            self.assertIsNone(scope(row('Нужно собрать тумбу', delivery_status=delivery)), delivery)

    def test_quotes_reports_hypotheses_past_and_questions_do_not_add_jobs(self):
        for text in ('Сосед сказал «Нужно собрать тумбу»', 'Сосед сказал, нужно собрать тумбу',
                     'Если нужно собрать тумбу', 'Может быть нужно собрать тумбу',
                     'Уже нужно было собрать тумбу', 'Нужно собрать тумбу?'):
            self.assertIsNone(scope(row(text)), text)

    def test_negated_operation_does_not_supply_request(self):
        self.assertIsNone(scope(row('Не нужно собрать тумбу')))
        self.assertIsNone(scope(row('Собрать тумбу не нужно')))

    def test_negated_item_and_positive_item_keep_distinct_scope(self):
        actual = scope(row('Не полку, а тумбу нужно повесить'))
        self.assertEqual(actual['active_item_families'], ['pedestal'])

    def test_explicit_cancellation_withdraws_only_that_item(self):
        actual = scope(row('Нужно собрать тумбу и повесить полку'), row('Полку не надо', 'cancel'))
        self.assertEqual(actual['active_item_families'], ['pedestal'])

    def test_already_word_does_not_turn_cancellation_into_past_work(self):
        for text in ('Полку уже не надо', 'Полка больше не нужна', 'Полка совсем не нужна'):
            actual = scope(row('Нужно собрать тумбу и повесить полку'), row(text, 'cancel'))
            self.assertEqual(actual['active_item_families'], ['pedestal'], text)

    def test_new_enquiry_cannot_inherit_old_category_or_work(self):
        self.assertIsNone(scope(row('Нужно собрать тумбу'), row('Новая заявка: установить зеркало', 'new')))

    def test_quoted_new_enquiry_does_not_reset_real_request(self):
        actual = scope(row('Нужно собрать тумбу'), row('Сосед написал «Новая заявка: повесить полку»', 'quote'))
        self.assertEqual(actual['active_item_families'], ['pedestal'])

    def test_free_prose_and_separate_selected_form_rows_are_not_group_category(self):
        self.assertIsNone(catalog.questionnaire_item_scope([row('Нужно повесить полку и шкаф', 'form'), row('Нужно собрать тумбу')]))
        separate = FORM.replace('- Полку, навесные шкафы', '- Полку\n- Навесные шкафы')
        self.assertIsNone(catalog.questionnaire_item_scope([row(separate, 'form'), row('Нужно собрать тумбу')]))

    def test_other_specific_items_do_not_justify_unselected_shelf(self):
        actual = scope(row('Нужно повесить зеркало и карниз'))
        self.assertEqual(actual['active_item_families'], ['curtain_rod', 'mirror'])
        self.assertTrue(catalog.unsupported_questionnaire_item('Стоимость монтажа полки, зеркала и карниза', actual))

    def test_native_shaped_extra_item_is_rejected(self):
        actual = scope(row('Нужно собрать и повесить тумбу'))
        self.assertTrue(catalog.unsupported_questionnaire_item(
            'Узнать точную стоимость сборки и подвеса предметов интерьера (полки, навесные шкафы, подвесная тумбочка)', actual))

    def test_genitive_plural_and_negative_adjective_keep_item_scope(self):
        actual = scope(row('Нужно собрать тумбу'))
        self.assertTrue(catalog.unsupported_questionnaire_item('Стоимость монтажа полок и тумбы', actual))
        self.assertFalse(catalog.unsupported_questionnaire_item('Не просит повесить отдельную полку', actual))

    def test_instead_does_not_negate_next_positive_operation(self):
        actual = scope(row('Вместо полки собрать подвесную тумбу'))
        self.assertEqual(actual['active_item_families'], ['pedestal'])
        self.assertEqual(actual['client_requests'][0]['operations'], ['собрать'])

    def test_history_negation_and_open_question_are_not_affirmative_extra_job(self):
        actual = scope(row('Нужно собрать тумбу'))
        for text in ('В анкете категория «Полку, навесные шкафы», уточнил тумбу',
                     'Не просит полку, просит тумбу', 'Полки не нужны, нужна тумба',
                     'Нужна ли полка?', 'Если нужна полка, это другой запрос'):
            self.assertFalse(catalog.unsupported_questionnaire_item(text, actual), text)

    def test_category_word_cannot_disguise_current_extra_service(self):
        actual = scope(row('Нужно собрать тумбу'))
        for text in ('Клиент заказал монтаж категории полок',
                     'Клиент просит категорию анкеты полки и тумбы',
                     'Из анкеты клиент попросил повесить полку'):
            self.assertTrue(catalog.unsupported_questionnaire_item(text, actual), text)


class ActualQuestionnaireScope201Tests(unittest.TestCase):
    setUp = helper.OnsiteOnly114Tests.setUp

    def preview(self, tail=None):
        rows = [message(FORM, mid='form'), message('Нужно собрать и повесить подвесную тумбочку', mid='detail')]
        rows.extend(tail or [])
        out, status = self.app.handle(dict(owner='owner', action='preview', wording_mode='neural_review',
            ctx=context(rows, dir='mnc', city='Оренбург', accountTitle='Учебный мастер', itemTitle='Мастер на час')))
        self.assertEqual(status, 200);self.assertTrue(out.get('pending_model'), out.get('reason'))
        return out, json.loads(out['model_task']['task'])

    def candidate(self, task):
        return dict(reply=task['proposed_reply'], needs_operator=False, context_review=dict(
            last_intent='Узнать стоимость сборки и навеса тумбы', latest_client_meaning='Нужно собрать и повесить тумбу',
            selected_step_fits=True, evidence_ids=['detail'], note='Уместно уточнить материал стены'))

    def test_actual_task_preserves_independent_schema_and_literal_sources(self):
        out, task = self.preview()
        actual = task['questionnaire_item_scope']
        self.assertEqual(actual['category']['evidence_id'], 'form')
        self.assertEqual(actual['client_requests'][0]['evidence_id'], 'detail')
        self.assertNotIn('questionnaire_item_review', task['output_contract']['context_review_fields'])
        self.assertFalse(out['lead']['can_create_automatically'])
        self.assertEqual(task['proposed_reply_status'], 'planned_not_sent')

    def test_all_free_review_fields_and_reply_reject_extra_work(self):
        _, task = self.preview()
        for key in ('last_intent', 'latest_client_meaning', 'note', 'reply'):
            candidate = self.candidate(task)
            target = candidate if key == 'reply' else candidate['context_review']
            target[key] = 'Клиент хочет собрать тумбу и повесить полку'
            _, state, errors = _context_review(candidate, task)
            self.assertEqual(state, 'inconsistent', key)
            self.assertEqual(errors, ['questionnaire_category_as_extra_work'], key)

    def test_actual_finalize_stops_expanded_scope_without_customer_write(self):
        out, task = self.preview();candidate = self.candidate(task)
        candidate['context_review']['last_intent'] = 'Сборка тумбочки, навес полок и шкафов'
        before = copy.deepcopy(candidate)
        final, status = self.app.handle(dict(owner='owner', action='finalize', request_id=out['request_id'],
            revision=out['revision'], candidate=candidate))
        self.assertEqual(status, 200)
        self.assertIn('questionnaire_category_as_extra_work', final['validation'])
        self.assertFalse(final['reply']);self.assertFalse(final['auto_enabled'])
        self.assertEqual(candidate, before)

    def test_correct_free_goal_and_justified_veto_stay_possible(self):
        _, task = self.preview()
        for veto in (False, True):
            candidate = self.candidate(task)
            if veto:
                candidate.update(reply='', needs_operator=True)
                candidate['context_review'].update(selected_step_fits=False, note='Следующий шаг требует проверки')
            _, state, errors = _context_review(candidate, task)
            self.assertEqual(state, 'provided')
            self.assertEqual(errors, ['model_context_mismatch'] if veto else [])

    def test_explicit_extra_shelf_is_not_rejected_by_scope_check(self):
        _, task = self.preview([message('Также нужно повесить полку', mid='extra')])
        candidate = self.candidate(task)
        candidate['context_review'].update(last_intent='Собрать тумбу и повесить полку',
            latest_client_meaning='Клиент дополнительно просит повесить полку', evidence_ids=['extra'])
        _, state, errors = _context_review(candidate, task)
        self.assertEqual(state, 'provided');self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
