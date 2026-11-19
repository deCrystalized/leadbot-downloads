"""Current crew questions must not become unrelated price-consent replies."""
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


def client(mid, text, **extra):
    result = dict(id=mid, direction='in', sender_type='client', body=text)
    result.update(extra)
    return result


class CrewQuestion171Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner171', LEADBOT_PERSONAL_AUTO_AVAILABLE='0')
        env.start(); self.addCleanup(env.stop)
        self.app = Assistant(Store(tmp.name + '/db'))

    def context(self, question='Вы один? Шкаф большой просто...'):
        return dict(convId='synthetic-crew171', dir='mnc', city='Тюмень', channel='avito',
                    partner='7', origin='synthetic-source', accountTitle='Учебный МНЧ', itemTitle='Сборка мебели',
                    messages=[client('job', 'Сколько стоит собрать шкаф-купе б/у, двери с зеркалами, размер 200 на 220?'),
                              dict(id='instruction', direction='out', sender_type='operator', body='Схема есть?'),
                              client('no-instruction', 'Схемы нет, шкаф б/у'),
                              dict(id='when', direction='out', sender_type='operator', body='Когда вам будет удобно?'),
                              client('price-question', 'Сколько стоит его собрать?'),
                              dict(id='price', direction='out', sender_type='operator',
                                   body='от 1500р будет идти, точную цену на месте только смогу назвать'),
                              client('crew', question)])

    def preview(self, ctx):
        out, status = self.app.handle(dict(owner='owner171', action='preview', wording_mode='neural_review', ctx=ctx))
        self.assertEqual(status, 200)
        return out

    def test_current_question_gets_owner_wording_before_price_consent(self):
        ctx = self.context(); before = copy.deepcopy(ctx)
        out = self.preview(ctx)
        self.assertEqual(out['action'], 'question')
        self.assertTrue(out.get('pending_model'))
        self.assertFalse(out['reply'])
        task = json.loads(out['model_task']['task'])
        self.assertTrue(task['proposed_reply'].startswith('Я работаю один.'))
        self.assertIn('Такая стоимость вас устраивает?', task['proposed_reply'])
        self.assertEqual(out['crew_composition_question']['message_id'], 'crew')
        self.assertFalse(out['crew_composition_question']['current_availability_verified'])
        self.assertFalse(out['facts'].get('required_crew_count'))
        self.assertFalse(out['lead']['can_create_automatically'])
        self.assertFalse(out['auto_enabled'])
        self.assertEqual(ctx, before)

    def test_direct_composition_questions_keep_literal_evidence(self):
        for text in ('Вы один?', 'Вы одна работаете?', 'Вы приедете один?',
                     'Один будете собирать?', 'Вы вдвоём приедете?',
                     'С напарником приедете?', 'У вас есть напарник?',
                     'Сколько человек приедет?', 'Сколько вас будет?',
                     'Вам одному под силу собрать такой шкаф?'):
            with self.subTest(text=text):
                evidence = policy.crew_composition_question([client('x', text)])
                self.assertEqual(evidence['message_id'], 'x')
                self.assertEqual(evidence['quote'], text)
                self.assertFalse(evidence['current_availability_verified'])

    def test_count_of_objects_clients_parts_and_ordinary_material_questions_are_not_crew(self):
        for text in ('Один шкаф собрать', 'Я одна дома', 'На телевизоре один вход',
                     'Нужен один мастер', 'Два человека живут в квартире',
                     'У вас один выключатель с собой?', 'Одну полку повесите?',
                     'Вы один шкаф собираете или ещё кухни?', 'Сколько стоит сборка?',
                     'Сколько человек живёт в квартире?'):
            self.assertIsNone(policy.crew_composition_question([client('x', text)]), text)

    def test_other_roles_and_quoted_questions_do_not_become_client_requests(self):
        for role in ('operator', 'bot', 'assistant', 'employee', 'system', 'avito'):
            self.assertIsNone(policy.crew_composition_question([client('x', 'Вы один?', sender_type=role)]))
        for text in ('«Вы один?»', 'Другой мастер спросил: «Вы один?»',
                     'Мастер спросил, вы один приедете?', 'Он один работает?',
                     'Если спросят «вы один?», что ответить?'):
            self.assertIsNone(policy.crew_composition_question([client('x', text)]), text)

    def test_negated_question_is_a_question_but_withdrawal_is_not(self):
        self.assertIsNotNone(policy.crew_composition_question([client('x', 'Вы не один приедете?')]))
        for text in ('Не важно, один вы приедете или вдвоём.', 'Не спрашиваю, вы один или с напарником.',
                     'Количество мастеров не важно', 'Напарник не нужен'):
            self.assertIsNone(policy.crew_composition_question([client('x', text)]), text)
        rows = [client('old', 'Вы один?'), client('withdraw', 'Количество мастеров не важно')]
        self.assertIsNone(policy.crew_composition_question(rows))

    def test_question_mark_and_system_note_do_not_erase_current_question(self):
        rows = [client('q', 'Вы один'), dict(id='n', direction='note', sender_type='operator', body='от1500'),
                dict(id='s', direction='system', sender_type='system', body='Назначен'), client('mark', '?')]
        self.assertEqual(policy.crew_composition_question(rows)['message_id'], 'q')

    def test_historical_staff_answer_ends_the_previous_turn_without_proving_current_crew(self):
        rows = [client('q', 'Вы один?'), dict(id='answer', direction='out', sender_type='operator', body='Есть напарник'),
                client('time', 'Завтра сможете?')]
        self.assertIsNone(policy.crew_composition_question(rows))
        out = self.preview(self.context())
        self.assertNotIn('Есть напарник', out['reason'])
        self.assertFalse(out['crew_composition_question']['current_availability_verified'])

    def test_browser_supplied_crew_confirmation_cannot_release_the_guard(self):
        ctx = self.context(); ctx.update(crew_available=True, crew_count=2, crew_verified=True,
                                        crew_composition_question=dict(current_availability_verified=True))
        out = self.preview(ctx)
        self.assertEqual(out['action'], 'question')
        self.assertFalse(out['crew_composition_question']['current_availability_verified'])

    def test_composition_question_does_not_add_technical_branch_approval_to_manual_form(self):
        out, status = self.app.handle(dict(owner='owner171', action='checklist', ctx=self.context()))
        self.assertEqual(status, 200)
        self.assertFalse(out['approval'])
        self.assertFalse(out['auto_enabled'])

    def test_real_requirement_of_two_workers_keeps_the_existing_distinct_guard(self):
        ctx = self.context('Нужны два мастера для сборки шкафа')
        out = self.preview(ctx)
        self.assertEqual(out['facts']['required_crew_count'], 2)
        self.assertIn('VERIFY_REQUIRED_CREW', [g['id'] for g in out['decision_guards']])
        self.assertIsNone(out.get('crew_composition_question'))

    def test_max_and_existing_order_guards_are_preserved(self):
        for extra in (dict(channel='max'), dict(crmRequestId='synthetic-existing171')):
            ctx = self.context(); ctx.update(extra); out = self.preview(ctx)
            self.assertEqual(out['action'], 'handoff')
            self.assertIsNone(out.get('crew_composition_question'))
            self.assertFalse(out.get('pending_model'))

    def test_foreign_owner_cannot_obtain_or_bypass_a_draft(self):
        out, status = self.app.handle(dict(owner='foreign', action='preview', ctx=self.context()))
        self.assertEqual(status, 403)
        self.assertFalse(out['ok'])

    def candidate(self, task):
        return dict(reply=task['proposed_reply'], needs_operator=False,
                    context_review=dict(last_intent='Сборка шкафа, уточнение состава исполнителей.',
                        latest_client_meaning='Спрашивает, один ли работает мастер: шкаф большой.',
                        selected_step_fits=True, evidence_ids=['crew'], note='Ответ на вопрос и согласие с ценой.'))

    def test_actual_task_exposes_owner_source_not_a_confirmed_visit_or_partner(self):
        out = self.preview(self.context()); task = json.loads(out['model_task']['task'])
        q = task['crew_composition_question_context']
        self.assertEqual(q['reply_source'], 'owner_approved_standard_wording')
        self.assertEqual(q['standard_reply'], 'Я работаю один.')
        self.assertFalse(q['current_availability_verified'])
        self.assertIn(q['rule_id'], out['rule_ids'])
        self.assertIn(q['rule_id'], [v['id'] for v in out['sources']])

    def test_original_price_only_candidate_is_rejected_without_json_repair(self):
        out = self.preview(self.context()); task = json.loads(out['model_task']['task'])
        c = self.candidate(task); c['reply'] = 'Такая стоимость вас устраивает?'; before = copy.deepcopy(c)
        final, status = self.app.handle(dict(owner='owner171', action='finalize', request_id=out['request_id'],
                                            revision=out['revision'], candidate=c))
        self.assertEqual(status, 200)
        self.assertEqual(c, before)
        self.assertIn('fixed_reply_changed', final['validation'])
        self.assertFalse(final['reply'])
        self.assertTrue(final['needs_operator'])

    def test_complete_model_reply_retains_owner_wording_and_can_be_finalized(self):
        out = self.preview(self.context()); task = json.loads(out['model_task']['task'])
        final, status = self.app.handle(dict(owner='owner171', action='finalize', request_id=out['request_id'],
                                            revision=out['revision'], candidate=self.candidate(task)))
        self.assertEqual(status, 200)
        self.assertFalse(final['validation'])
        self.assertTrue(final['reply'].startswith('Я работаю один.'))
        self.assertNotIn('напарник', final['reply'])
        self.assertFalse(final['auto_enabled'])

    def test_owner_wording_does_not_force_the_model_to_accept_an_unsuitable_step(self):
        out = self.preview(self.context()); task = json.loads(out['model_task']['task']); c = self.candidate(task)
        c.update(reply='', needs_operator=True)
        c['context_review'].update(selected_step_fits=False, note='Другие условия требуют проверки.')
        final, status = self.app.handle(dict(owner='owner171', action='finalize', request_id=out['request_id'],
                                            revision=out['revision'], candidate=c))
        self.assertEqual(status, 200)
        self.assertEqual(final['action'], 'handoff')
        self.assertFalse(final['reply'])

    def fee_case(self):
        ctx = self.context(); ctx.update(dir='kp', city='Чита', itemTitle='Ремонт компьютеров')
        ctx['messages'] = [client('fee', 'Сколько стоит выезд и диагностика компьютера?')]
        out = self.preview(ctx); task = json.loads(out['model_task']['task'])
        self.assertEqual(task['reply_field_scope'], 'exact_fixed_reply')
        c = dict(reply=task['fixed_reply'], needs_operator=False,
                 context_review=dict(last_intent='Узнать стоимость выезда и диагностики компьютера.',
                     latest_client_meaning='Спрашивает стоимость выезда и диагностики.',
                     selected_step_fits=True, evidence_ids=['fee'], note='Условия выезда без обещания записи.',
                     diagnostic_fee_review=dict(amount_rub=1000, free_when='work_performed',
                                                diagnostic_result_sets_price=False)))
        return out, task, c

    def test_exact_fixed_mode_does_not_repair_an_omitted_greeting_even_without_crew(self):
        out, task, c = self.fee_case(); c['reply'] = c['reply'].removeprefix('Здравствуйте! ')
        self.assertNotEqual(c['reply'], task['fixed_reply'])
        final, status = self.app.handle(dict(owner='owner171', action='finalize', request_id=out['request_id'],
                                            revision=out['revision'], candidate=c))
        self.assertEqual(status, 200)
        self.assertIn('fixed_reply_changed', final['validation'])
        self.assertFalse(final['reply'])

    def test_complete_exact_fixed_fee_keeps_existing_approved_tariff(self):
        out, task, c = self.fee_case()
        final, status = self.app.handle(dict(owner='owner171', action='finalize', request_id=out['request_id'],
                                            revision=out['revision'], candidate=c))
        self.assertEqual(status, 200)
        self.assertFalse(final['validation'])
        self.assertEqual(final['reply'], task['fixed_reply'])


if __name__ == '__main__':
    unittest.main()
