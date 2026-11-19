"""Client questions and hypothetical examples do not confirm PC installation."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'leadbot/brain'))
import contact_facts


def scope(*texts):
    return contact_facts.graphics_device_scope([dict(id=str(i),direction='in',body=t) for i,t in enumerate(texts)])


class GraphicsAssertionRole72Tests(unittest.TestCase):
    symptom='Подарили видеокарту, нет картинки, экран чёрный'

    def test_a_question_about_installation_is_not_a_client_assertion(self):
        self.assertEqual(scope(self.symptom,'Видеокарта установлена в компьютере?')['kind'],'device_uncertain')

    def test_a_conditional_pc_example_is_not_an_observed_host(self):
        self.assertEqual(scope('Если видеокарта установлена в компьютере, но нет изображения, в чём может быть причина?')['kind'],'device_uncertain')

    def test_a_conditional_missing_pc_is_not_observed_absence(self):
        self.assertEqual(scope(self.symptom,'А если нет компьютера?')['kind'],'device_uncertain')

    def test_a_price_question_can_contain_a_positive_factual_clause(self):
        self.assertEqual(scope('Видеокарта установлена в компьютере, нет изображения, сколько стоит диагностика?')['kind'],'host_diagnostic')

    def test_a_later_actual_statement_can_resolve_a_preceding_question(self):
        self.assertEqual(scope(self.symptom,'Видеокарта установлена в компьютере? Видеокарта установлена в моём компьютере.')['kind'],'host_diagnostic')

    def test_internet_word_does_not_assert_that_no_pc_exists(self):
        self.assertEqual(scope(self.symptom,'Интернет компьютера работает')['kind'],'device_uncertain')
