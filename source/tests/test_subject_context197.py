"""Observed operations, object clauses and landmarks have separate scopes."""
import json
import unittest

import assistant_policy as policy
import contact_facts as facts
import extension_assistant as ext
import test_subject_context196 as subject196
row = subject196.row


class SourceClauses197Tests(unittest.TestCase):
    setUp = subject196.ElectricalCondition196Tests.setUp
    task = subject196.ElectricalCondition196Tests.task
    def test_each_object_has_its_exact_source_clause(self):
        task=self.task('Не работают несколько розеток в квартире и с люстрами разобраться.')
        clauses=task['electrical_object_context']['client_source_clauses']
        self.assertEqual([(v['object'],v['quote']) for v in clauses],
                         [('socket','Не работают несколько розеток в квартире'),
                          ('chandelier','и с люстрами разобраться')])
        self.assertTrue(all(v['message_id']=='job' for v in clauses))
        self.assertNotIn('electrical_condition_review',task.get('output_schema',{}))

    def test_shared_predicate_and_inverse_order_keep_exact_spelling(self):
        text='Люстры и розетки не работают'
        c=facts.electrical_condition_context([row(text,'both')])
        self.assertEqual({v['object_literal'] for v in c['client_source_clauses']},{'Люстры','розетки'})
        self.assertTrue(all(v['quote']==text for v in c['client_source_clauses']))

    def test_later_correction_and_question_remain_full_history(self):
        messages=[row('Розетки не работают','one'),row('Люстра работает?','q'),row('Розетки уже работают','fix')]
        c=facts.electrical_condition_context(messages)
        self.assertEqual({v['message_id'] for v in c['client_source_clauses']},{'one','q','fix'})
        self.assertEqual(c['objects']['socket']['working_status'],'reported')
        self.assertEqual(c['objects']['chandelier']['working_status'],'not_reported')


class FurnitureOperations197Tests(unittest.TestCase):
    known=dict(direction='mnc',channel='avito',city='Оренбург',partner='7',title='Сборка мебели',account_name='Учебный мастер')

    def assess(self,messages):
        f=facts.collect(messages,self.known)
        return policy.assess(messages,self.known,f),f

    def test_disassembly_and_packing_are_not_assembly_or_a_blanket_refusal(self):
        d,f=self.assess([row('Нужно разобрать и упаковать мебель для перевозки. Шкаф, кровать, трюмо.','job')])
        self.assertEqual(d['action'],'handoff')
        self.assertEqual(d['service']['operator_scope'],'furniture_transport')
        self.assertEqual({v['operation'] for v in f['furniture_transport_operations']},{'disassembly','packing'})
        self.assertIn('DOC-L0453',d['rule_ids']);self.assertNotIn('next_question',d)

    def test_future_assembly_does_not_cancel_immediate_operations(self):
        h=[row('Нужно разобрать и упаковать шкаф','job'),row('А потом только собрать на новом месте','later')]
        d,f=self.assess(h)
        self.assertEqual(d['action'],'handoff');self.assertEqual(len(f['furniture_transport_operations']),2)

    def test_refusal_and_why_do_not_become_contact_intake(self):
        h=[row('Нужно разобрать шкаф','job'),row('С разбором не смогу помочь','refusal','out'),row('Почему? Напишите, пожалуйста, помогите','why')]
        d,f=self.assess(h)
        self.assertEqual(d['action'],'handoff');self.assertNotIn('Номер',d.get('forced_reply',''))
        self.assertEqual(f['furniture_transport_operations'][0]['message_id'],'job')

    def test_actual_only_disassembly_and_wrap_film(self):
        h=[row('Нужно разобрать шкафчики детского сада для хранения','job'),
           row('Только разобрать?','q','out'),row('Да, только разбор. Какую-то обмотать пленкой','answer')]
        self.assertEqual({v['operation'] for v in facts.furniture_transport_operations(h)},{'disassembly','packing'})

    def test_explicit_cancellation_removes_only_named_operation(self):
        h=[row('Нужно разобрать и упаковать шкаф','job'),row('Упаковка не нужна','cancel')]
        self.assertEqual([v['operation'] for v in facts.furniture_transport_operations(h)],['disassembly'])

    def test_explicit_rescope_to_assembly_removes_previous_jobs(self):
        h=[row('Нужно разобрать и упаковать шкаф','job'),row('Теперь нужна только сборка','cancel')]
        self.assertFalse(facts.furniture_transport_operations(h))

    def test_prepacked_or_previously_disassembled_product_is_not_new_job(self):
        for body in ['Схемы нет, шкаф бу, забирала разобранным',
                     'Шкаф запакован, на озоне заказала, нужно собрать',
                     'Я уже разобрала шкаф, нужно собрать',
                     'Нужно собрать шкаф. Разбирать не надо',
                     'Сосед сказал: «нужно разобрать шкаф». Мне нужна сборка']:
            with self.subTest(body=body):self.assertFalse(facts.furniture_transport_operations([row(body)]))

    def test_other_item_operation_is_not_furniture_disassembly(self):
        h=[row('Нужно собрать шкаф','job'),row('Ещё разобрать ноутбук','other')]
        self.assertFalse(facts.furniture_transport_operations(h))

    def test_role_delivery_and_new_order_boundaries(self):
        for extra in [dict(direction='out'),dict(sender_type='system'),dict(delivery_status='failed')]:
            m=row('Разобрать шкаф','wrong');m.update(extra)
            with self.subTest(extra=extra):self.assertFalse(facts.furniture_transport_operations([m]))
        h=[row('Разобрать шкаф','old'),row('Новый заказ: собрать кровать','new')]
        self.assertFalse(facts.furniture_transport_operations(h))

    def test_evidence_is_not_execution_approval(self):
        op=facts.furniture_transport_operations([row('Нужно упаковать шкаф','pack')])[0]
        self.assertEqual(op['message_id'],'pack');self.assertEqual(op['quote'],'Нужно упаковать шкаф')
        self.assertFalse(op['execution_approved'])

    def test_cannot_do_it_themselves_is_a_help_request(self):
        h=[row('Сами разобрать шкаф не можем, помогите','help')]
        self.assertEqual(facts.furniture_transport_operations(h)[0]['operation'],'disassembly')

    def test_intended_independent_disassembly_is_not_requested_from_us(self):
        self.assertFalse(facts.furniture_transport_operations([row('Хочу сама разобрать шкаф')]))


class LocationReferences197Tests(unittest.TestCase):
    def history(self,body):
        return [row('Нужно разобрать шкаф','job'),row('Адрес подскажите?','address','out'),row(body,'place')]

    def view(self,h):
        f=dict(work_location_references=facts.work_location_references(h))
        return facts.intent_text('\n'.join(m['body'] for m in h if m['direction']=='in'),f),f

    def test_actual_uncertain_landmark_is_not_a_lock_job(self):
        text,f=self.view(self.history('Я не местная пока. Замок нюнхацзена так вроде вот район'))
        self.assertNotIn('Замок',text)
        ref=f['work_location_references'][0]
        self.assertEqual(ref['quote'],'Замок нюнхацзена так вроде вот район')
        self.assertEqual(ref['question_message_id'],'address');self.assertFalse(ref['map_verified'])

    def test_independent_actual_lock_work_survives_in_same_message(self):
        text,_=self.view(self.history('Ориентир замок. Нужно заменить замок на входной двери'))
        self.assertIn('Нужно заменить замок на входной двери',text)
        self.assertNotIn('Ориентир замок',text)

    def test_location_name_can_be_quoted_without_becoming_someone_elses_report(self):
        text,_=self.view(self.history('Ориентир магазин «Замок»'))
        self.assertNotIn('Замок',text)

    def test_work_and_landmark_in_one_undivided_clause_are_not_erased(self):
        body='Рядом с магазином нужно заменить замок'
        self.assertIn(body,self.view(self.history(body))[0])

    def test_no_observed_address_question_does_not_guess_a_location(self):
        self.assertFalse(facts.work_location_references([row('Замок неизвестный вот район')]))
        for extra in [dict(delivery_status='failed'),dict(sender_type='system'),dict(out_pending=True)]:
            h=self.history('Замок неизвестный район');h[1].update(extra)
            with self.subTest(extra=extra):self.assertFalse(facts.work_location_references(h))

    def test_staff_quote_system_or_failed_report_is_not_client_location(self):
        for body in ['Сосед сказал: «Ориентир замок»','«Ориентир замок»']:
            self.assertFalse(facts.work_location_references(self.history(body)))
        for extra in [dict(sender_type='system'),dict(delivery_status='failed'),dict(direction='out')]:
            h=self.history('Ориентир замок');h[-1].update(extra)
            with self.subTest(extra=extra):self.assertFalse(facts.work_location_references(h))

    def test_different_enquiry_does_not_inherit_address_question(self):
        h=self.history('Новый заказ: Замок неизвестный вот район')
        self.assertFalse(facts.work_location_references(h))

    def test_identical_words_inside_previous_actual_work_are_not_masked(self):
        h=[row('Ориентир замок нужно отремонтировать','job'),
           row('Адрес подскажите?','address','out'),row('Ориентир замок','place')]
        text,_=self.view(h)
        self.assertIn('Ориентир замок нужно отремонтировать',text)
