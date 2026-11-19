"""A task form's category is not a second requested furniture operation."""
import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import assistant_catalog as catalog
import assistant_policy as policy
import contact_facts
from assistant_store import Store
from extension_assistant import Assistant


def task(action, extra=''):
    return ('Собрать или разобрать мебель · ' + action + ' · Шкаф · ...\n'
            'Вот подробности 👇\n\nКакая услуга нужна:\n'
            'Собрать или разобрать мебель\n\nЧто сделать с мебелью:\n' + action +
            '\n\nКакая мебель:\n- Шкаф\n\nКакой шкаф:\nШкаф-купе\n'
            '\nСколько дверей:\n5\n\nКомментарий:\n' + extra +
            '\n✨Задача составлена по ответам клиента в анкете')


class FurnitureTaskFormTests(unittest.TestCase):
    def test_selected_disassembly_requires_branch_check(self):
        result = catalog.choose(task('Разобрать'), dict(direction='mnc'))
        self.assertEqual(result['status'], 'agree')
        self.assertIn('furniture-disassembly', [r['id'] for r in result['items']])
        self.assertIn('DOC-L0453', result['rules'])

    def test_disassembly_does_not_require_assembly_instructions(self):
        self.assertFalse(catalog.furniture_assembly_request(task('Разобрать')))
        messages = [dict(id='client1', direction='in', body=task('Разобрать'))]
        known = dict(direction='mnc', city='Тула', channel='avito', partner='7')
        result = policy.assess(messages, known, contact_facts.collect(messages, known))
        self.assertEqual(result['action'], 'handoff')
        self.assertNotRegex(result.get('reply', ''), r'инструкц|схем|1500')

    def test_selected_assembly_remains_ordinary_assembly(self):
        result = catalog.choose(task('Собрать'), dict(direction='mnc'))
        self.assertEqual(result['status'], 'supported')
        self.assertTrue(catalog.furniture_assembly_request(task('Собрать')))
        self.assertIn('instructions', result['items'][0]['questions'])

    def test_selected_combined_actions_are_not_reduced_to_disassembly(self):
        self.assertTrue(catalog.furniture_assembly_request(task('Разобрать и собрать')))

    def test_separate_assembly_in_comment_is_preserved(self):
        self.assertTrue(catalog.furniture_assembly_request(task('Разобрать', 'Также собрать комод.')))

    def test_independent_approval_work_is_preserved(self):
        result = catalog.choose(task('Собрать', 'Также нужна реставрация кровати.'), dict(direction='mnc'))
        self.assertIn(result['status'], ('agree', 'mixed'))

    def test_ordinary_prose_does_not_silently_select_an_option(self):
        prose = 'Собрать или разобрать мебель, пока не решил. Шкаф.'
        self.assertEqual(catalog.clean(prose), prose.lower())


class UnresolvedVpnFeeTests(unittest.TestCase):
    def preview(self, latest):
        messages = [dict(id='client1', direction='in', body='В офисе нужно подключить VPN к Wi-Fi.'),
                    dict(id='staff1', direction='out', body='Когда вам удобно принять мастера?'),
                    dict(id='client2', direction='in', body=latest)]
        ctx = dict(convId='synthetic-vpn-fee', dir='kp', city='Рязань', channel='avito', partner='7',
                   accountTitle='Синтетический мастер КП', itemTitle='Настройка роутера и Wi-Fi',
                   messages=messages)
        with tempfile.TemporaryDirectory() as p:
            out, status = Assistant(Store(p + '/db')).handle(dict(owner='offline-test', action='preview', ctx=ctx))
        self.assertEqual(status, 200)
        self.assertFalse(out['auto_enabled'])
        return out

    def test_partner_callout_fee_answer_precedes_device_scope_question(self):
        for latest in ('выезд на просчет работы бесплатный?', 'Вызов платный?'):
            with self.subTest(latest=latest):
                out = self.preview(latest)
                self.assertIn('1000', out['reply'])
                self.assertIn('при выполнении работ', out['reply'].lower())
                self.assertIn('при отказе', out['reply'].lower())
                self.assertNotIn('на роутере или на компьютере', out['reply'])
                self.assertIn('DOC-L0812', out['rule_ids'])
                self.assertFalse(out['lead']['can_create_automatically'])

    def test_unanswered_device_scope_still_requires_clarification(self):
        out = self.preview('Да, обычный, купили у провайдера.')
        self.assertIn('на роутере или на компьютере', out['reply'])
        self.assertNotIn('1000', out['reply'])

    def test_service_price_is_not_a_callout_fee_question(self):
        out = self.preview('Сколько стоит настроить VPN?')
        self.assertNotIn('1000', out['reply'])
        self.assertFalse(out['lead']['can_create_automatically'])


if __name__ == '__main__':
    unittest.main()
