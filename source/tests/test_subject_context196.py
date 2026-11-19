"""A condition belongs to its object; a placement noun is not another job."""
import json
import unittest

import assistant_policy as policy
import contact_facts as facts
import extension_assistant as ext
import test_onsite_only114 as onsite
from test_assistant import context


def row(body, mid='client', direction='in', **extra):
    return dict(id=mid,body=body,direction=direction,
                sender_type='operator' if direction=='out' else 'client',
                created_at='2026-10-01T12:00:00+00:00',**extra)


class PlacementSubject196Tests(unittest.TestCase):
    known=dict(direction='mnc',channel='avito',city='Оренбург',partner='7',title='Сантехник',account_name='Учебный мастер')

    def history(self, answer='На кухне под раковиной'):
        return [row('Протечку в насосе устраняете или предлагаете сразу замену?','job'),
                row('Какой у вас насос?','question','out'),row('', 'photo',media_reviewed=True),row(answer,'placement')]

    def test_actual_place_answer_does_not_accept_a_sink_job(self):
        messages=self.history(); f=facts.collect(messages,self.known)
        o=policy.assess(messages,self.known,f)
        self.assertEqual(o['action'],'handoff');self.assertIn('согласован',o['reason'])
        self.assertNotIn('sink',[v['id'] for v in o.get('service',{}).get('items',[])])

    def test_source_identity_and_subject_survive(self):
        value=facts.work_placement_answers(self.history())[0]
        self.assertEqual(value['message_id'],'placement');self.assertEqual(value['subject_message_id'],'job')
        self.assertEqual(value['question_message_id'],'question');self.assertFalse(value['requested_service_changed'])
        self.assertEqual(value['quote'],'На кухне под раковиной')

    def test_different_placement_objects_are_not_services(self):
        for body in ['Под мойкой','В ванной возле стиральной машины','Он стоит за унитазом',
                     'Не под раковиной, а рядом с мойкой']:
            with self.subTest(body=body):self.assertTrue(facts.work_placement_answers(self.history(body)))

    def test_explicit_added_sink_or_machine_work_is_preserved(self):
        for body in ['На кухне под раковиной, ещё заменить смеситель',
                     'Под мойкой течёт сифон','Нужно заменить раковину',
                     'Рядом со стиральной машиной, её тоже починить']:
            with self.subTest(body=body):self.assertFalse(facts.work_placement_answers(self.history(body)))

    def test_bare_object_answer_is_not_erased(self):
        self.assertFalse(facts.work_placement_answers(self.history('Раковина')))

    def test_no_prior_task_or_observed_question_no_binding(self):
        self.assertFalse(facts.work_placement_answers([row('Под раковиной')]))
        self.assertFalse(facts.work_placement_answers([row('Здравствуйте','hello'),row('Где?','q','out'),row('Под раковиной')]))

    def test_pending_failed_or_system_question_is_not_observed(self):
        for extra in [dict(out_pending=True),dict(delivery_status='failed'),dict(sender_type='system')]:
            h=self.history();h[1].update(extra)
            self.assertFalse(facts.work_placement_answers(h))

    def test_staff_system_or_failed_answer_not_client_evidence(self):
        for extra in [dict(direction='out'),dict(sender_type='bot'),dict(sender_type='system'),dict(delivery_status='pending')]:
            h=self.history();h[-1].update(extra)
            self.assertFalse(facts.work_placement_answers(h))

    def test_quote_question_and_plan_not_literal_placement(self):
        for body in ['Сосед сказал: «Под раковиной»','Под раковиной?',
                     'Если под раковиной, сможете?','Будет под раковиной']:
            with self.subTest(body=body):self.assertFalse(facts.work_placement_answers(self.history(body)))

    def test_normal_sink_request_stays_in_service_view(self):
        h=[row('Нужно заменить раковину','job'),row('Где работа?','q','out'),row('На кухне под раковиной','place')]
        f=facts.collect(h,self.known);o=policy.assess(h,self.known,f)
        self.assertIn('sink',[v['id'] for v in o.get('service',{}).get('items',[])])

    def test_new_order_is_not_bound_to_old_pump(self):
        self.assertFalse(facts.work_placement_answers(self.history('Новый заказ: заменить раковину')))

    def test_same_place_words_inside_an_actual_request_are_not_erased(self):
        h=self.history();h[0]['body']='Нужно заменить раковину. На кухне под раковиной есть насос.'
        f=facts.collect(h,self.known);text='\n'.join(m['body'] for m in h if m['direction']=='in')
        selected=facts.intent_text(text,f)
        self.assertIn('Нужно заменить раковину. На кухне под раковиной есть насос.',selected)
        self.assertNotIn('\nНа кухне под раковиной',selected)


class ElectricalCondition196Tests(unittest.TestCase):
    setUp=onsite.OnsiteOnly114Tests.setUp

    def task(self, body='Не работают несколько розеток в квартире и с люстрами разобраться.'):
        out,status=self.app.handle(dict(owner='owner',action='preview',wording_mode='neural_review',
            ctx=context([row(body,'job')],city='Оренбург',dir='mnc',itemTitle='Услуги электрика')))
        self.assertEqual(status,200)
        return json.loads(out['model_task']['task'])

    def candidate(self,task,meaning,**changes):
        r=dict(last_intent='Проверить розетки и разобраться с люстрами',latest_client_meaning=meaning,
               selected_step_fits=True,evidence_ids=['job'],note='Уточнение потолка не утверждает тип или диагноз.')
        r.update(changes);return dict(reply=task['proposed_reply'],needs_operator=False,context_review=r)

    def test_actual_unmodified_native_claim_is_rejected(self):
        task=self.task();c=self.candidate(task,'Клиент запрашивает проверку неработающих розеток и люстр, интересуется возможностью приезда и стоимостью',
            last_intent='Запрос проверки и ремонта розеток и люстр с указанием адреса')
        self.assertIn('electrical_condition_object_transfer',ext._context_review(c,task)[2])

    def test_separate_vague_light_request_has_no_nonworking_fact(self):
        c=facts.electrical_condition_context([row('Не работают розетки и с люстрами разобраться.','job')])
        self.assertEqual(c['objects']['socket']['nonworking_status'],'reported')
        self.assertEqual(c['objects']['chandelier']['nonworking_status'],'not_reported')
        self.assertEqual(c['evidence'][0]['message_id'],'job')

    def test_explicit_shared_condition_covers_both_items(self):
        for text in ['Не работают розетки и люстры','Не работают розетки, люстры','Розетки и люстры не работают',
                     'Неработающие розетки и люстры','Неисправных люстр и розеток проверка']:
            with self.subTest(text=text):
                c=facts.electrical_condition_context([row(text)])
                self.assertEqual(c['objects']['socket']['nonworking_status'],'reported')
                self.assertEqual(c['objects']['chandelier']['nonworking_status'],'reported')

    def test_inverse_and_genitive_orders_bind_the_same_object(self):
        for text in ['Люстра не работает','Не работает люстра','Проверка неработающей люстры']:
            c=facts.electrical_condition_context([row(text)])
            self.assertEqual(c['objects']['chandelier']['nonworking_status'],'reported')

    def test_explicit_two_object_reports_allow_free_combined_meaning(self):
        task=self.task('Не работают розетки и люстры.');c=self.candidate(task,'Нужно проверить неработающие люстры и розетки')
        self.assertFalse(ext._context_review(c,task)[2])

    def test_normal_qualification_and_vague_problem_meaning_stay_valid(self):
        task=self.task();c=self.candidate(task,'Не работают розетки; требуется разобраться с люстрами')
        self.assertFalse(ext._context_review(c,task)[2]);self.assertNotIn('electrical_condition_review',c['context_review'])

    def test_reply_and_each_free_field_are_checked(self):
        task=self.task()
        for field in ['reply','last_intent','latest_client_meaning','note']:
            c=self.candidate(task,'Проверить розетки и разобраться с люстрами')
            if field=='reply':c[field]='У вас не работает люстра.'
            else:c['context_review'][field]='Не работает люстра'
            with self.subTest(field=field):self.assertIn('electrical_condition_object_transfer',ext._context_review(c,task)[2])

    def test_question_uncertainty_and_negated_claim_do_not_assert_fault(self):
        c=facts.electrical_condition_context([row('Проверить розетки и разобраться с люстрами')])
        for text in ['Люстра не работает?','Возможно, люстра не работает','Если люстра не работает',
                     'Не подтверждено, что люстра не работает','Неверно, что люстра не работает']:
            with self.subTest(text=text):self.assertFalse(facts.unsupported_electrical_condition(text,c))

    def test_source_question_quote_foreign_report_or_doubt_not_positive_fact(self):
        for text in ['Люстра не работает?','Возможно, люстра не работает','Если люстра не работает',
                     'Сосед сказал: «Люстра не работает»','Не подтверждено, что люстра не работает']:
            c=facts.electrical_condition_context([row(text)])
            with self.subTest(text=text):self.assertNotEqual(c['objects']['chandelier']['nonworking_status'],'reported')

    def test_staff_and_automation_do_not_create_client_condition(self):
        for role in ['operator','system','avito','bot']:
            c=facts.electrical_condition_context([dict(row('Люстра не работает'),sender_type=role)])
            self.assertFalse(c)

    def test_failed_or_missing_ID_cannot_create_condition(self):
        for extra in [dict(id=''),dict(delivery_status='failed'),dict(delivery_status='queued')]:
            c=facts.electrical_condition_context([dict(row('Люстра не работает'),**extra)])
            self.assertFalse(c)

    def test_new_enquiry_does_not_inherit_old_condition(self):
        c=facts.electrical_condition_context([row('Не работает люстра','old'),row('Новый заказ: повесить люстру','new')])
        self.assertEqual(c['objects']['chandelier']['nonworking_status'],'not_reported')

    def test_other_electrical_object_does_not_receive_the_same_fault(self):
        c=facts.electrical_condition_context([row('Не работает выключатель. Светильник нужно повесить.')])
        self.assertTrue(facts.unsupported_electrical_condition('Не работает светильник',c))
        self.assertFalse(facts.unsupported_electrical_condition('Не работает выключатель',c))

    def test_past_failure_without_a_current_claim_is_not_current_condition(self):
        for body in ['Люстра не работала','Раньше не работала люстра']:
            c=facts.electrical_condition_context([row(body)])
            self.assertEqual(c['objects']['chandelier']['nonworking_status'],'not_reported')

    def test_unknown_is_not_proof_that_the_other_item_works(self):
        c=facts.electrical_condition_context([row('Не работают розетки и с люстрами разобраться')])
        self.assertTrue(facts.unsupported_electrical_condition('Люстры исправны',c))

    def test_later_literal_correction_supersedes_old_condition(self):
        c=facts.electrical_condition_context([row('Люстра не работает','old'),row('Теперь люстра работает','new')])
        self.assertTrue(facts.unsupported_electrical_condition('Люстра не работает',c))
        self.assertFalse(facts.unsupported_electrical_condition('Люстра работает',c))

    def test_explicit_different_states_keep_their_own_objects(self):
        c=facts.electrical_condition_context([row('Не работает розетка, люстра исправна')])
        self.assertFalse(facts.unsupported_electrical_condition('Не работает розетка',c))
        self.assertFalse(facts.unsupported_electrical_condition('Люстра исправна',c))
        self.assertTrue(facts.unsupported_electrical_condition('Не работает люстра',c))

    def test_native_schema_stays_free_without_new_required_receipt(self):
        task=self.task();self.assertIn('electrical_object_context',task)
        c=self.candidate(task,'Проверить розетки и разобраться с люстрами')
        self.assertFalse(ext._context_review(c,task)[2])
