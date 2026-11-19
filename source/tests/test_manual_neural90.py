"""Offline semantic regressions from guarded development prefixes 501–520.

Contact details and operator identities are omitted. The cases preserve client
meaning, not a price acceptance, performed call, agreed visit or CRM receipt.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import assistant_policy as policy
import contact_facts
import qualification_state
from assistant_store import Store
from extension_assistant import Assistant


def history(*rows):
    return [dict(id=str(index), direction=direction, body=body,
                 sender_type='client' if direction == 'in' else 'operator')
            for index, (direction, body) in enumerate(rows)]


class ManualNeural90Tests(unittest.TestCase):
    """OWNER-CLIENT-REPORTED-SCOPE; DOC-L0700,0324 and time/intake rules."""

    def inspect(self, rows, *, direction='mnc', city='Томск', title='Мастер на час'):
        messages = history(*rows)
        known = dict(direction=direction, direction_source='context', city=city,
                     partner='7', channel='avito', title=title,
                     account_name='Тестовый мастер ' + ('КП' if direction == 'kp' else 'МНЧ'))
        facts = contact_facts.collect(messages, known)
        return messages, qualification_state.inspect(messages), policy.assess(messages, known, facts)

    def preview(self, rows, *, direction='mnc', city='Томск', title='Мастер на час'):
        ctx = dict(convId='synthetic-manual-neural90', city=city, dir=direction,
                   partner='7', channel='avito', itemTitle=title,
                   accountTitle='Тестовый мастер ' + ('КП' if direction == 'kp' else 'МНЧ'),
                   messages=history(*rows))
        with tempfile.TemporaryDirectory() as tmp:
            output, code = Assistant(Store(tmp + '/db')).handle(dict(
                owner='offline-manual-neural90', action='preview',
                wording_mode='reviewed', ctx=ctx))
        self.assertEqual(code, 200)
        self.assertFalse(output['auto_enabled'])
        self.assertFalse(output.get('lead', {}).get('can_create_automatically'))
        self.assertFalse(output.get('pending_model'))
        self.assertNotIn('model_task', output)
        return output

    def test_503_1_printer_chewing_paper_and_squeaking_is_an_explicit_problem(self):
        rows = [('in', 'Здравствуйте, нужна помощь. Принтер жуёт бумагу и скрипит...')]
        _, state, decision = self.inspect(rows, direction='kp', city='Саратов', title='Ремонт принтеров')
        self.assertEqual(state['problem']['status'], 'answered')
        self.assertEqual(state['problem']['message_id'], '0')
        self.assertNotEqual(decision.get('next_question', {}).get('kind'), 'problem')
        draft = self.preview(rows, direction='kp', city='Саратов', title='Ремонт принтеров')
        self.assertNotRegex(draft.get('reply', '').lower(), r'что.{0,15}случил|какая.{0,15}проблем')

    def test_511_1_purchased_mixers_answer_materials_without_inventing_consumables(self):
        rows = [('in', 'Добрый день. Можно сегодня-завтра провести замену 2 смесителей, '
                        'на кухне и на раковине в ванной? Сами смесители куплены')]
        _, state, decision = self.inspect(rows, city='Хабаровск', title='Услуги сантехника')
        self.assertEqual(state['materials']['status'], 'answered')
        self.assertEqual(state['materials']['message_id'], '0')
        self.assertNotRegex(state['materials']['value'].lower(), r'проклад|уплотнит|шланг')
        self.assertEqual(state['plumbing_ready']['status'], 'missing')
        self.assertNotEqual(decision.get('next_question', {}).get('kind'), 'materials')
        draft = self.preview(rows, city='Хабаровск', title='Услуги сантехника')
        self.assertNotRegex(draft.get('reply', '').lower(), r'(?:материал|комплектующ).{0,35}есть\s*\?')

    def test_512_5_yes_there_is_answers_the_preceding_assembly_diagram_question(self):
        rows = [('in', 'Здравствуйте, сколько стоит собрать угловой шкаф'),
                ('in', 'Маленький шкаф, узкий'),
                ('out', 'Здравствуйте, схема сборки есть?'), ('in', 'Да, есть')]
        _, state, decision = self.inspect(rows, title='Сборка мебели')
        self.assertEqual(state['instructions']['status'], 'answered')
        self.assertEqual(state['instructions']['value'], 'yes')
        self.assertEqual(state['instructions']['message_id'], '3')
        self.assertNotEqual(decision.get('next_question', {}).get('kind'), 'instructions')
        draft = self.preview(rows, title='Сборка мебели')
        self.assertNotRegex(draft.get('reply', '').lower(), r'(?:схем|инструкц)[^?]{0,55}\?')

    def test_517_7_no_none_is_a_negative_diagram_answer_not_an_unanswered_question(self):
        rows = [('out', 'Здравствуйте, с чем могу вам помочь?'),
                ('in', 'Подскажите пожалуйста меня интересует стоимость сделать в малосемейке '
                       'в общем коридорчике шкаф весь материал имеется в наличии'),
                ('out', 'Схема сборки есть?'), ('in', 'Нет нету')]
        _, state, decision = self.inspect(rows, city='Нефтеюганск', title='Сборка и ремонт мебели')
        self.assertEqual(state['instructions']['status'], 'answered')
        self.assertEqual(state['instructions']['value'], 'no')
        self.assertEqual(state['instructions']['message_id'], '3')
        self.assertFalse(decision.get('crm_flags', {}).get('customer_declined'))
        self.assertNotEqual(decision.get('next_question', {}).get('kind'), 'instructions')
        # No requirement to accept this custom work automatically: further
        # operator/branch review can be the correct next step.
        draft = self.preview(rows, city='Нефтеюганск', title='Сборка и ремонт мебели')
        self.assertNotRegex(draft.get('reply', '').lower(), r'(?:схем|инструкц)[^?]{0,55}\?')

    def test_509_8_returning_when_a_loader_is_found_pauses_intake(self):
        rows = [('in', 'Нужно разобрать кровать у продавца, перевезти ко мне и собрать. '
                       'Можете помочь с перевозкой?'),
                ('out', 'Здравствуйте! У меня нет автомобиля, перевозкой не занимаюсь. Собрать могу.'),
                ('in', 'Хорошо, тогда вернусь к вам когда найду грузчика')]
        _, _, decision = self.inspect(rows, city='Тюмень', title='Сборка и ремонт мебели')
        self.assertEqual(decision['action'], 'wait')
        self.assertFalse(decision.get('next_question'))
        self.assertFalse(decision.get('crm_preparation'))
        draft = self.preview(rows, city='Тюмень', title='Сборка и ремонт мебели')
        self.assertEqual(draft['action'], 'wait')
        self.assertFalse(draft.get('reply'))

    def test_506_15_fourteen_is_a_time_counterproposal_not_wall_requalification(self):
        rows = [('in', 'Нужно только одну гардину повесить, она упала.'),
                ('out', 'В 13:00 удобно'), ('in', 'Можно 14:00')]
        messages, _, decision = self.inspect(rows, city='Бийск')
        self.assertIsNone(policy._accepted_staff_visit(messages))
        self.assertNotIn(decision.get('next_question', {}).get('kind'),
                         ('wall', 'problem', 'instructions', 'materials'))
        self.assertIn(decision['action'], ('handoff', 'question'))
        next_purpose = ' '.join([decision.get('reason', ''), decision.get('forced_reply', ''),
                                 decision.get('next_question', {}).get('question', '')]).lower()
        self.assertRegex(next_purpose, r'врем|час|договор|визит|перенос|14')
        self.assertFalse(decision.get('existing_visit_evidence'))
        counterproposal = decision['visit_counterproposal_evidence']
        self.assertEqual(counterproposal['requested_time'], '14:00')
        self.assertFalse(counterproposal['visit_confirmed'])
        self.assertFalse(counterproposal['crm_write_confirmed'])
        draft = self.preview(rows, city='Бийск')
        self.assertNotRegex(draft.get('reply', '').lower(), r'из какого.{0,20}стен')

    def test_price_quantity_and_call_counterproposals_do_not_become_visit_slots(self):
        for proposal, answer in [
            ('В 13:00 удобно?', 'Можно 14 рублей?'),
            ('В 13:00 удобно?', 'Можно 14 полок?'),
            ('В 13:00 позвоню, удобно?', 'Можно 14:00'),
            ('В 13:00 созвонимся, удобно?', 'Можно 14:00'),
            ('Цена за 13 штук, удобно?', 'Можно 14'),
        ]:
            with self.subTest(proposal=proposal, answer=answer):
                messages = history(('in', 'Повесить гардину'), ('out', proposal), ('in', answer))
                self.assertIsNone(policy._visit_counterproposal(messages))

    def test_an_unsent_staff_time_proposal_does_not_establish_visit_negotiation(self):
        messages = history(('in', 'Повесить гардину'), ('out', 'В 13:00 удобно?'),
                           ('in', 'Можно 14:00'))
        messages[1]['out_pending'] = True
        self.assertIsNone(policy._visit_counterproposal(messages))

    def test_unknown_printer_symptom_still_requires_a_genuine_clarification(self):
        _, state, decision = self.inspect([('in', 'Здравствуйте, ремонтируете принтеры?')],
                                          direction='kp', city='Саратов', title='Ремонт принтеров')
        self.assertEqual(state['problem']['status'], 'missing')
        self.assertEqual(decision.get('next_question', {}).get('kind'), 'problem')

    def test_job_without_purchase_statement_does_not_invent_available_mixers(self):
        _, state, _ = self.inspect([('in', 'Нужно заменить два смесителя.')], title='Услуги сантехника')
        self.assertEqual(state['materials']['status'], 'missing')

    def test_an_operator_question_or_multi_question_does_not_establish_an_instruction_answer(self):
        for rows in [
            [('in', 'Собрать шкаф'), ('out', 'Схема сборки есть?')],
            [('in', 'Собрать шкаф'), ('out', 'Схема есть? Крепёж куплен?'), ('in', 'Да, есть')],
            [('in', 'Собрать шкаф'), ('out', 'Схема есть? Крепёж куплен?'), ('in', 'Нет нету')],
        ]:
            with self.subTest(rows=rows):
                self.assertEqual(qualification_state.inspect(history(*rows))['instructions']['status'], 'missing')

    def test_schema_or_parts_are_different_dimensions_not_a_single_binary_fact(self):
        for answer in ('Да, есть', 'Нет нету'):
            with self.subTest(answer=answer):
                messages = history(('in', 'Собрать шкаф'),
                                   ('out', 'Схема сборки есть или только детали в наличии?'),
                                   ('in', answer))
                self.assertEqual(qualification_state.inspect(messages)['instructions']['status'], 'missing')

    def test_negative_schema_and_fasteners_answer_does_not_identify_the_missing_item(self):
        messages = history(('in', 'Собрать шкаф'), ('out', 'Схема и крепёж есть?'),
                           ('in', 'Нет нету'))
        state = qualification_state.inspect(messages)
        self.assertEqual(state['instructions']['status'], 'missing')
        self.assertEqual(state['materials']['status'], 'missing')

    def test_schema_and_instruction_synonyms_keep_unambiguous_binary_answers(self):
        for answer, value in (('Да, есть', 'yes'), ('Нет нету', 'no')):
            with self.subTest(answer=answer):
                state = qualification_state.inspect(history(
                    ('in', 'Собрать шкаф'), ('out', 'Схема или инструкция сборки есть?'),
                    ('in', answer)))
                self.assertEqual(state['instructions']['status'], 'answered')
                self.assertEqual(state['instructions']['value'], value)

    def test_positive_schema_and_fasteners_answer_does_not_claim_a_purchase(self):
        state = qualification_state.inspect(history(
            ('in', 'Собрать шкаф'), ('out', 'Схема и крепёж есть?'), ('in', 'Да, есть')))
        self.assertEqual(state['instructions']['status'], 'answered')
        self.assertEqual(state['instructions']['value'], 'yes')
        self.assertNotRegex(state['materials']['value'].lower(), r'куплен|приобрет')

    def test_a_current_question_after_loader_deferral_is_not_silenced(self):
        _, _, decision = self.inspect([
            ('in', 'Собрать кровать'), ('in', 'Вернусь к вам когда найду грузчика'),
            ('in', 'А сейчас подскажите, сколько стоит только сборка?'),
        ], title='Сборка и ремонт мебели')
        self.assertNotEqual(decision['action'], 'wait')


if __name__ == '__main__':
    unittest.main()
