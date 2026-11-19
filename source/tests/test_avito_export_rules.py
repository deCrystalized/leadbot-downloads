import unittest

import assistant_catalog
import assistant_policy
import qualification_state as qs


def msg(body, direction='in'):
    return dict(body=body, direction=direction, id=body[:15])


class ExportRuleTests(unittest.TestCase):
    def test_bands_refusal_is_confirmed_scoped_and_not_a_matrix_diagnosis(self):
        for body in ('Телевизор, на экране появились полосы', 'ТВ LED с полоской', 'Телевизор, полосы есть, возможно матрица'):
            self.assertFalse(assistant_catalog.confirmed_tv_matrix(body))
            self.assertEqual(assistant_catalog.choose(body, dict(direction='kp'))['status'], 'refuse')
        for body in ('Телевизор без полос', 'Телевизор, если появятся полосы', 'На телевизоре появились полосы. Теперь полос нет.', 'Телевизор, не полоски, это блики'):
            self.assertNotEqual(assistant_catalog.choose(body, dict(direction='kp'))['status'], 'refuse')
        self.assertNotIn('OWNER-TV-BANDS-20261017', assistant_catalog.choose('Ноутбук с полосами на экране', dict(direction='kp', title='Ремонт телевизоров'))['rules'])

    def test_age_is_explicit_and_only_answers_the_age_question(self):
        self.assertEqual(qs.client_age([msg('Мне 32 года')])['value'], 32)
        self.assertEqual(qs.client_age([msg('Мой возраст 28')])['value'], 28)
        self.assertEqual(qs.client_age([msg('А можете подсказать свой возраст?', 'out'), msg('18')])['status'], 'adult')
        for body in ('Мне нужно 15 метров провода', 'Ленина 17, квартира 32', 'Мне 500 рублей за диагностику сказали', '18', 'Сыну 15 лет'):
            self.assertEqual(qs.client_age([msg(body)])['status'], 'missing')
        self.assertEqual(qs.client_age([msg('Мне ещё нет 18 лет')])['status'], 'minor')
        self.assertEqual(qs.client_age([msg('Ваш возраст?', 'out'), msg('Не хочу говорить')])['status'], 'unavailable')

    def test_current_export_sources_are_retrievable_with_real_text(self):
        for ref, expected in [('TGAVITO-32294', 'служебный комментарий'), ('TGAVITO-33531', 'имя мастера'), ('TGAVITO-23005', 'свой возраст')]:
            sources = assistant_policy.retrieve('', refs=[ref])
            self.assertEqual(sources[0]['id'], ref)
            self.assertIn(expected, sources[0]['text'])
        self.assertFalse(next(r for r in assistant_policy.registry()['sources'] if r['id']=='TG1-594')['active_primary'])

