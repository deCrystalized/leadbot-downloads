"""A stated current software fault is a problem, not another form question."""
import unittest
import assistant_catalog as catalog
import qualification_state as qs
import test_office_intent204 as fixture


class OfficeSymptom233Tests(unittest.TestCase):
    def test_first_office_fault_help_is_answered_once_before_cost_and_symptom(self):
        rows=fixture.rows(('in','Здравствуйте, не работают Word и Excel на компьютере. Можете помочь? И какая стоимость?'))
        out=fixture.OfficeIntent204Tests().call(rows)
        self.assertEqual(out['reply'].casefold().count('могу помочь'),1,out['reply'])
        self.assertIn('С программами могу помочь.',out['reply'])
        self.assertIn('стоимость',out['reply'].casefold());self.assertIn('запуск',out['reply'].casefold())
        self.assertNotRegex(out['reply'].casefold(),r'модел|переустановим|создал|800|1000')

    def test_stopped_opening_is_exact_current_symptom_and_problem(self):
        for body in ('Word и Excel перестали открываться','Office перестал запускаться','Word перестал сохранять документ'):
            state=qs.inspect(fixture.rows(('in',body)))
            self.assertTrue(catalog.office_fault_request(body))
            for key in ('problem','office_symptom'):
                self.assertEqual(state[key]['status'],'answered',key)
                self.assertEqual(state[key]['message_id'],'0');self.assertEqual(state[key]['quote'],body)

    def test_neither_answer_nor_form_reasks_the_already_stated_problem(self):
        rows=fixture.rows(('in','На компьютере с Windows11 перестали открываться Word и Excel. Документы нужно сохранить. Ничего переустанавливать я не просил.'))
        out=fixture.OfficeIntent204Tests().call(rows)
        self.assertNotRegex(out['reply'].casefold(),r'что у вас случилось|что происходит|марк|модел|установим|переустановим')
        state=qs.inspect(rows);self.assertEqual(state['problem']['status'],'answered')

    def test_hypothesis_quote_and_third_party_cannot_supply_a_fault(self):
        for body in ('Если Word перестал открываться, что делать?','Мастер сказал: Word перестал открываться','В инструкции «Word перестал открываться»'):
            self.assertFalse(catalog.office_fault_request(body),body)
            self.assertNotEqual(qs.inspect(fixture.rows(('in',body)))['office_symptom']['status'],'answered')
            rows=fixture.rows(('in','Word не работает'),('out','Что происходит при запуске программы: появляется ошибка или она не открывается?'),('in',body))
            self.assertNotEqual(qs.inspect(rows)['office_symptom']['status'],'answered')

    def test_negated_cessation_does_not_become_fault(self):
        for body in ('Word не перестал открываться','Excel не  перестал запускаться','Office не перестал работать'):
            self.assertFalse(catalog.office_fault_request(body),body)
            self.assertNotEqual(qs.inspect(fixture.rows(('in',body)))['office_symptom']['status'],'answered')

    def test_roles_and_delivery_remain_bound(self):
        for change in ({'sender_type':'system'},{'sender_type':'operator'},{'direction':'out'},
                       {'speaker_role':'service'},{'role':'system'},
                       {'delivery_status':'failed'},{'delivery_status':'pending'},{'out_pending':True}):
            row=fixture.rows(('in','Word перестал открываться'))[0];row.update(change)
            state=qs.inspect([row]);self.assertNotEqual(state['office_symptom']['status'],'answered',change)

    def test_new_order_cannot_borrow_old_software_symptom(self):
        rows=fixture.rows(('in','Word перестал открываться'),('in','Новая заявка. Нужна помощь с другим компьютером.'))
        self.assertNotEqual(qs.inspect(rows)['office_symptom']['status'],'answered')

    def test_generic_not_working_still_needs_concrete_symptom_without_installation(self):
        body='Word не работает'
        self.assertTrue(catalog.office_fault_request(body));self.assertFalse(catalog.office_installation_request(body))
        self.assertNotEqual(qs.inspect(fixture.rows(('in',body)))['office_symptom']['status'],'answered')
