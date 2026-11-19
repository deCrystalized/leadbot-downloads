"""518/527 direct time questions retain the existing guarded answer path."""
import unittest

import assistant_policy as policy
import test_visit_time_question135 as fixture


class LiteralTime186Tests(unittest.TestCase):
    # Reuse setup helpers, without inheriting/counting the old tests twice.
    setUp = fixture.VisitTimeQuestion135Tests.setUp
    preview = fixture.VisitTimeQuestion135Tests.preview
    at = fixture.VisitTimeQuestion135Tests.at

    def test_clock_convenience_question_is_not_replaced_by_phone(self):
        with self.at(): out=self.preview(last='В 17:30 удобно сегодня?')
        self.assertEqual(out['action'],'question')
        self.assertIn('17:30',out['reply'])
        self.assertIn('не подтверждено',out['reply'])
        self.assertNotRegex(out['reply'],'номер|телефон|приеду|свободен')
        self.assertIsNone(out['visit_offer'])

    def test_bounded_arrival_typo_gets_the_same_time_answer(self):
        with self.at(): out=self.preview(last='Сегодня сможите приехать?')
        self.assertEqual(out['action'],'question')
        self.assertIn('час-полтора',out['reply'])
        self.assertNotRegex(out['reply'],'номер|телефон|приеду')

    def test_negative_quote_phone_and_materials_are_not_arrival_questions(self):
        for text in ['Не в 17:30 удобно сегодня?', '«В 17:30 удобно сегодня?»',
                     'Сегодня в 17:30 удобно созвониться?', 'Завтра в 17:30 удобно получить материалы?',
                     'Сегодня в 17:30 мне удобно.', 'Не сегодня в 17:30 удобно?']:
            with self.subTest(text=text): self.assertFalse(policy._direct_visit_time_question(text))

    def test_no_current_slot_after_working_hours_and_no_approval_bypass(self):
        with self.at(hour=23): out=self.preview(last='Сегодня сможите приехать?')
        self.assertNotIn('час-полтора',out['reply'])
        self.assertFalse(out['auto_enabled'])
        with self.at(): out=self.preview(last='Сегодня сможите приехать?',
            extra=(dict(id='agreement',direction='in',body='Заменить стояк отопления'),))
        self.assertEqual(out['action'],'handoff')
