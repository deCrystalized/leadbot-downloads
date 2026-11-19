import unittest
import qualification_state as qs


def client(text, mid='answer', **fields):
    return dict(id=mid, direction='in', sender_type='client', body=text, **fields)


def question(**fields):
    return dict(id='question', direction='out', sender_type='bot',
                body=qs.SPECS['decision_maker'][0], delivery_status='delivered', **fields)


class DecisionResponsibility206Tests(unittest.TestCase):
    positive = 'Решение принимаю и оплачиваю я, буду на месте.'

    def inspect(self, text):
        return qs.inspect([question(), client(text)])['decision_maker']

    def test_conjunction_and_reversed_self_reference_keep_exact_source(self):
        for text in (self.positive, 'На месте буду я, оплачу я, решение приму я.',
                     'Я принимаю решение. Я оплачу. Я буду присутствовать.'):
            row=self.inspect(text)
            self.assertEqual(row['status'], 'answered', text)
            self.assertEqual(row['message_id'], 'answer')
            self.assertEqual(row['question_message_id'], 'question')
            self.assertEqual(row['quote'], text)

    def test_presence_or_payment_alone_does_not_supply_missing_responsibility(self):
        for text in ('Буду на месте.', 'Оплачиваю я.', 'Решение принимаю я.'):
            self.assertNotEqual(self.inspect(text)['status'], 'answered', text)

    def test_legacy_definite_self_presence_and_payment_or_decision_still_work(self):
        #215/current DOC-L0797 requires all three independently. These exact
        # legacy positives omitted one condition; retain them as stricter
        # partial-answer regressions (original saved in the198 adjudication).
        for text in ('Я оплачу и буду на месте', 'Буду на месте, я принимаю решение'):
            row=qs.inspect([client(text)])['decision_maker']
            self.assertNotEqual(row['status'], 'answered')
            self.assertEqual(len(row['missing_components']), 1)

    def test_negative_or_tentative_presence_never_becomes_confirmation(self):
        for text in ('Решение принимаю и оплачиваю я, не буду на месте.',
                     'Решение принимаю и оплачиваю я, возможно буду на месте.',
                     'Решение принимаю и оплачиваю я, постараюсь быть на месте.'):
            self.assertNotEqual(self.inspect(text)['status'], 'answered', text)

    def test_question_and_condition_are_not_positive_facts(self):
        for text in (self.positive.rstrip('.')+'?', 'Если решение принимаю и оплачиваю я, буду на месте.'):
            self.assertNotEqual(self.inspect(text)['status'], 'answered')

    def test_quote_or_report_cannot_supply_a_self_statement(self):
        for text in ('Муж написал: «'+self.positive+'»', 'Она говорит, я оплачу и буду на месте.'):
            self.assertNotEqual(self.inspect(text)['status'], 'answered')

    def test_other_decision_maker_is_not_the_client(self):
        for text in ('Я оплачу и буду на месте, решение принимает муж.',
                     'Решение принимает начальник, оплачиваю я, буду на месте.'):
            self.assertNotEqual(self.inspect(text)['status'], 'answered')

    def test_incoming_staff_system_and_platform_are_not_client_answers(self):
        for role in ('operator', 'bot', 'system', 'avito'):
            row=client(self.positive);row['sender_type']=role
            self.assertNotEqual(qs.inspect([question(),row])['decision_maker']['status'], 'answered')

    def test_short_yes_does_not_answer_a_failed_or_pending_question(self):
        for status in ('failed','pending','sending'):
            q=question();q['delivery_status']=status
            self.assertNotEqual(qs.inspect([q,client('Да')])['decision_maker']['status'], 'answered')

    def test_complete_independent_statement_does_not_claim_failed_question_was_delivered(self):
        q=question();q['delivery_status']='failed'
        row=qs.inspect([q,client(self.positive)])['decision_maker']
        self.assertEqual(row['status'],'answered');self.assertNotIn('question_message_id',row)

    def test_new_enquiry_does_not_inherit_the_old_personal_confirmation(self):
        messages=[client(self.positive,'old'),client('Новая заявка: нужно собрать комод.','new')]
        self.assertNotEqual(qs.inspect(messages)['decision_maker']['status'],'answered')

    def test_later_uncertainty_revokes_an_earlier_personal_confirmation(self):
        messages=[client(self.positive,'old'),client('Не уверен, буду ли на месте.','new')]
        row=qs.inspect(messages)['decision_maker']
        self.assertEqual(row['status'],'uncertain');self.assertEqual(row['message_id'],'new')

    def test_responsibility_does_not_create_payment_receipt_or_visit(self):
        row=self.inspect(self.positive)
        self.assertEqual(row['responsibility_scope'],'client_stated_decision_payment_presence_not_booking')
        for key in ('paid','accepted_visit','crm_request_id','price_consent'):
            self.assertNotIn(key,row)

    def test_unrelated_fault_negation_or_quoted_error_does_not_erase_self_responsibility(self):
        for text in ('Компьютер не включается. Я оплачу и буду на месте.',
                     'Компьютер не включается, я оплачу и буду на месте.',
                     'Word пишет «Ошибка». '+self.positive):
            row=self.inspect(text)
            self.assertEqual(row['components']['payment']['status'],'confirmed',text)
            self.assertEqual(row['components']['presence']['status'],'confirmed',text)
            self.assertEqual(row['status'],'answered' if 'Решение' in text else 'missing',text)

    def test_separate_doubt_prefix_cannot_establish_self_presence(self):
        for prefix in ('Возможно, ', 'Наверное, ', 'Нет, '):
            self.assertNotEqual(self.inspect(prefix+'я оплачу и буду на месте.')['status'],'answered')

    def test_quoted_new_order_does_not_reset_own_earlier_confirmation(self):
        messages=[client(self.positive,'old'),client('Муж написал: «Новая заявка: я оплачу и буду на месте».','quote')]
        row=qs.inspect(messages)['decision_maker']
        self.assertEqual(row['status'],'answered');self.assertEqual(row['message_id'],'old')

    def test_another_persons_report_does_not_replace_or_revoke_own_statement(self):
        messages=[client(self.positive,'old'),client('Она говорит, я оплачу и буду на месте.','report')]
        row=qs.inspect(messages)['decision_maker']
        self.assertEqual(row['status'],'answered');self.assertEqual(row['message_id'],'old')
