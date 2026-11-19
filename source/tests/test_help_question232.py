"""A literal current request for help must survive the price/qualification path."""
import json
import unittest
import assistant_catalog as catalog
import assistant_policy as policy
from test_history_intake106 import assess, known
import test_office_intent204 as fixture


class HelpQuestion232Tests(unittest.TestCase):
    def test_current_office_fault_help_and_price_are_both_answered(self):
        for question in ('Поможете с этим?', 'Вы поможете?', 'Можете с этим помочь?'):
            with self.subTest(question=question):
                body='На ноутбуке перестали открываться Word и Excel, ошибка 0xc0000142. '+question+' Сколько стоит помощь?'
                result=fixture.OfficeIntent204Tests().call(fixture.rows(('in',body)))
                self.assertRegex(result['reply'],r'помо[гч]')
                self.assertRegex(result['reply'],r'стоим|осмотр')
                self.assertNotRegex(result['reply'],r'модел|марка|2000|переустанов|800|гарант')

    def test_source_bound_help_question_retains_id_quote_and_has_no_execution_proof(self):
        rows=fixture.rows(('in','Word перестал открываться, ошибка запуска. Поможете с этим?'))
        source=dict(known('kp','Компьютерная помощь'),city='Чита')
        service=catalog.choose(rows[0]['body'],source)
        result=policy.intake_question_context(rows,source,service)
        self.assertIsNotNone(result)
        self.assertEqual(result['query_message_ids'],['0'])
        self.assertEqual(result['work_message_ids'],['0'])
        self.assertFalse(result['service_execution_verified'])

    def test_help_words_without_present_supported_work_do_not_grant_a_service(self):
        source=dict(known('kp','Компьютерная помощь'),city='Чита')
        for body in ('Если Word перестанет открываться, поможете?',
                     'Сосед сказал: «Word перестал открываться, поможете?»',
                     'Вы поможете привезти детали?', 'Поможете всё точно починить за один визит?'):
            rows=fixture.rows(('in',body))
            result=policy.intake_question_context(rows,source,catalog.choose(body,source))
            self.assertIsNone(result,body)

    def test_system_failed_or_foreign_help_question_cannot_supply_client_intent(self):
        source=dict(known('kp','Компьютерная помощь'),city='Чита')
        for changes in ({'sender_type':'system'},{'delivery_status':'failed'},
                        {'role':'system'},{'speaker_role':'service'}):
            rows=fixture.rows(('in','Word перестал открываться. Поможете?'));rows[0].update(changes)
            self.assertIsNone(policy.intake_question_context(rows,source,catalog.choose(rows[0]['body'],source)))


if __name__=='__main__':
    unittest.main()
