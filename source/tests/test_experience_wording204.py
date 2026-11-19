import unittest
from experience_wording import verified_question


class ExperienceWordingTests(unittest.TestCase):
    def setUp(self):
        self.question = dict(question='Схема или инструкция сборки есть?', groups=[['схем', 'инструкц']])
        self.experience = dict(version='a'*64, examples=[dict(staff_question='Схема сборки есть?')])

    def test_polite_current_question_can_be_natural_without_forced_alternation(self):
        for reply in ['Подскажите, схема сборки есть?', 'У вас сохранилась схема сборки?',
                      'Схема или инструкция сборки есть?']:
            with self.subTest(reply=reply):
                self.assertTrue(verified_question(reply, self.question, self.experience, 'provided'))

    def test_unknown_attributes_actors_prices_and_extra_clauses_cannot_pass(self):
        for reply in ['Схема для двухкомнатной квартиры есть?', 'Наша схема сборки есть?',
                      'Схема сборки не нужна?', 'Схема есть? И инструкция есть?',
                      'Завтра соберу. Схема сборки есть?', 'За 1000 схема сборки есть?',
                      'Схема сборки для кухни есть?', 'По схеме сборки все сделаю?',
                      'Наш мастер возьмет схему сборки?']:
            with self.subTest(reply=reply):
                self.assertFalse(verified_question(reply, self.question, self.experience, 'provided'))

    def test_missing_experience_or_independent_review_does_not_widen_legacy_contract(self):
        for experience, status in [(None, 'provided'), ({}, 'provided'), (self.experience, 'invalid')]:
            self.assertFalse(verified_question('Схема есть?', self.question, experience, status))

    def test_selected_qualification_cannot_change_to_another_question(self):
        self.assertFalse(verified_question('Когда вам удобно?', self.question, self.experience, 'provided'))
