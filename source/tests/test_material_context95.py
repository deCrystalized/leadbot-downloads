"""Real506: an inventory denial is a client fact, not an invented unpurchased item."""
import os
import tempfile
import unittest
from unittest.mock import patch

from test_assistant import context, message
from assistant_store import Store
from extension_assistant import Assistant, manual_checklist, _parse
import contact_facts
import qualification_state as qs
import assistant_catalog


def rows(answer='Здравствуйте, нет не чего', prompt='У вас все в наличии есть?', delivery='sent'):
    return [message('Нужно повесить гардину.', mid='job'),
            dict(message(prompt, 'out', 'question'), sender_type='operator', delivery_status=delivery),
            message(answer, mid='answer')]


class MaterialContext95Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner', LEADBOT_ASSISTANT_WORDING='reviewed')
        env.start()
        self.addCleanup(env.stop)
        self.app = Assistant(Store(tmp.name + '/db'))

    def preview(self, history):
        ctx = context(history, dir='mnc', city='Бийск', itemTitle='Мастер на час')
        out, code = self.app.handle(dict(owner='owner', action='preview', ctx=ctx))
        self.assertEqual(code, 200)
        self.assertFalse(out['auto_enabled'])
        return out, ctx

    def test_actual506_spelling_is_bound_to_the_specific_question(self):
        row = qs.inspect(rows())['materials']
        self.assertEqual(row['status'], 'answered')
        self.assertEqual(row['value'], 'no')
        self.assertEqual(row['message_id'], 'answer')
        self.assertEqual(row['question_message_id'], 'question')
        self.assertEqual(row['quote'], 'Здравствуйте, нет не чего')
        self.assertEqual(row['availability_scope'], 'question_subject_only')

    def test_common_short_inventory_denials_preserve_their_exact_quote(self):
        for answer in ['Нет ничего', 'Ничего нет.', 'Нет ещё', 'Пока ничего нет',
                       'Добрый день! Нет не чего', 'Нету', 'Здравствуйте, нет']:
            with self.subTest(answer=answer):
                row = qs.inspect(rows(answer))['materials']
                self.assertEqual(row['value'], 'no')
                self.assertEqual(row['quote'], answer)

    def test_a_separate_greeting_does_not_break_the_inventory_answer(self):
        history = rows('Нет ничего')
        history.insert(-1, message('Здравствуйте', mid='hello'))
        self.assertEqual(qs.inspect(history)['materials']['question_message_id'], 'question')

    def test_mixed_or_negative_questions_do_not_invert_or_spread_the_answer(self):
        for prompt in ['Материалы и инструкция есть?', 'Материалы есть? Схема есть?',
                       'Материалы или схема есть?', 'Материалов нет?', 'Каких материалов не хватает?',
                       'Материалы есть, номер телефона подскажите?', 'Материалы есть.']:
            with self.subTest(prompt=prompt):
                self.assertEqual(qs.inspect(rows('Нет', prompt))['materials']['status'], 'missing')

    def test_other_topics_questions_and_explicit_deferrals_are_not_inventory(self):
        for answer, prompt in [('Нет ничего', 'Сегодня удобно?'), ('Нет ничего?', 'Материалы есть?'),
                               ('Ничего не надо', 'Материалы есть?'), ('Нет, пока не надо', 'Материалы есть?')]:
            with self.subTest(answer=answer, prompt=prompt):
                self.assertEqual(qs.inspect(rows(answer, prompt))['materials']['status'], 'missing')

    def test_failed_pending_and_cancelled_questions_cannot_create_an_answer(self):
        for delivery in ['pending', 'queued', 'sending', 'failed', 'error', 'cancelled']:
            with self.subTest(delivery=delivery):
                self.assertEqual(qs.inspect(rows(delivery=delivery))['materials']['status'], 'missing')

    def test_named_fitting_denial_stays_about_that_fitting(self):
        history = rows('Здравствуйте, нет ничего', 'Замок у вас в наличии уже?')
        history[0]['body'] = 'Нужно установить замок в межкомнатную дверь.'
        row = qs.inspect(history)['materials']
        self.assertEqual(row['value'], 'no')
        self.assertEqual(row['availability_subject'], 'замок')
        self.assertEqual(row['question_message_id'], 'question')

    def test_later_explicit_purchase_does_not_keep_the_old_negative_or_question(self):
        history = rows() + [message('Материалы уже куплены.', mid='correction')]
        row = qs.inspect(history)['materials']
        self.assertEqual(row['message_id'], 'correction')
        self.assertNotEqual(row['value'], 'no')
        self.assertNotIn('question_message_id', row)
        f = contact_facts.collect(history, dict(direction='mnc'))
        self.assertEqual(f['material_availability']['message_id'], 'correction')
        self.assertTrue(any('Материалы уже куплены.' in s for s in f['comment_lines']))
        self.assertFalse(any('нет не чего' in s for s in f['comment_lines']))

    def test_generic_denial_does_not_keep_an_earlier_named_item_scope(self):
        history = [message('Установить замок.', mid='job'),
                   message('Замок у вас в наличии уже?', 'out', 'lock-question'), message('Да', mid='yes'),
                   message('Материалы и комплектующие есть?', 'out', 'materials-question'), message('Нет ничего', mid='no')]
        row = qs.inspect(history)['materials']
        self.assertEqual(row['value'], 'no')
        self.assertEqual(row['question_message_id'], 'materials-question')
        self.assertNotIn('availability_subject', row)

    def test_fallen_existing_curtain_continues_with_the_real_wall_prerequisite(self):
        history = rows() + [message('Нужно только одну гардину повесить, она упала. Сколько стоит?', mid='scope')]
        out, _ = self.preview(history)
        self.assertEqual(out['action'], 'question')
        self.assertIn('Из какого материала стены?', out['reply'])
        self.assertNotIn('не приобретены', out['reason'])
        self.assertEqual(out['qualification']['materials']['value'], 'no')
        self.assertEqual(out['qualification']['materials']['question_message_id'], 'question')
        self.assertEqual(out['facts']['material_availability']['quote'], 'Здравствуйте, нет не чего')
        comment = '\n'.join(out['facts']['comment_lines'])
        self.assertIn('Здравствуйте, нет не чего', comment)
        self.assertIn('У вас все в наличии есть?', comment)
        self.assertNotIn('гардина отсутствует', comment)
        self.assertNotIn('не куплен', comment)
        self.assertFalse(out['lead']['can_create_automatically'])

    def test_normal_form_uses_the_same_negative_fact_without_invented_approval(self):
        history = rows() + [message('Одну упавшую гардину прикрепить к кирпичной стене в квартире.', mid='scope')]
        _, ctx = self.preview(history)
        _, parsed, known, _ = _parse(ctx)
        out = manual_checklist(parsed, known)
        self.assertEqual(out['facts']['material_availability']['value'], 'no')
        self.assertNotIn('не приобретены', out['approval'])
        self.assertFalse(out['auto_enabled'])

    def test_real_service_approval_and_pc_purchase_conditions_still_apply(self):
        history = rows() + [message('Ещё нужно заменить стояк отопления.', mid='agreement')]
        out, _ = self.preview(history)
        self.assertEqual(out['action'], 'handoff')
        state = qs.inspect([message('Комплектующих нет.'), message('Не готов покупать.', mid='decline')])
        state['pc_parts'].update(status='answered', value='no')
        state['pc_purchase'].update(status='answered', value='no')
        service = assistant_catalog.choose('Собрать компьютер', dict(direction='kp'))
        self.assertIn('DOC-L0130', assistant_catalog.condition_issue(service, state, 'Собрать компьютер')[1])
        state['pc_purchase']['value'] = 'yes'
        self.assertIsNone(assistant_catalog.condition_issue(service, state, 'Собрать компьютер'))
