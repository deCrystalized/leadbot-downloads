"""Owner correction: listing city avoids a routine question, not address checks."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from assistant_store import Store
from extension_assistant import Assistant, _parse
import assistant_qualifiers
import contact_facts
import leadchat


def ctx(text, **extra):
    return dict(convId='synthetic-listing-city83', city='Оренбург', dir='mnc',
                partner='7', channel='avito', accountTitle='Григорий МНЧ',
                itemTitle='Сборка мебели', messages=[dict(id='client', direction='in', body=text)], **extra)


class ListingCity83Tests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Store(str(Path(temp.name) / 'db'))
        env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner', LEADBOT_ASSISTANT_WORDING='reviewed')
        env.start(); self.addCleanup(env.stop)
        self.app = Assistant(self.store)

    def preview(self, context, **extra):
        result, code = self.app.handle(dict(owner='owner', action='preview', ctx=context, **extra))
        self.assertEqual(code, 200)
        self.assertFalse(result['auto_enabled'])
        return result

    def test_price_answer_uses_listing_city_without_a_confirmation_turn(self):
        out = self.preview(ctx('Здравствуйте! Сколько стоит собрать кухонный гарнитур?'))
        self.assertTrue(out['reply'].startswith('Здравствуйте! '))
        self.assertIn('Точную стоимость скажу после осмотра.', out['reply'])
        self.assertIn('сборки', out['reply'])
        self.assertNotIn('в каком городе', out['reply'])
        self.assertEqual(out['reply'].count('?'), 1)

    def test_all_three_directions_skip_the_known_listing_city(self):
        for direction, text, title in [('kp', 'Компьютер не включается', 'Ремонт компьютеров'),
                                       ('bt', 'Холодильник не морозит', 'Ремонт холодильников'),
                                       ('mnc', 'Заменить розетку', 'Мастер на час')]:
            with self.subTest(direction=direction):
                context = ctx(text)
                context.update(dir=direction, accountTitle='Григорий ' + direction.upper(), itemTitle=title)
                out = self.preview(context)
                self.assertEqual(out['action'], 'question')
                self.assertNotIn('в каком городе', out['reply'])
                _, messages, known, _ = _parse(context)
                question = assistant_qualifiers.next_question(messages, known, contact_facts.collect(messages, known))
                self.assertNotEqual(question.get('kind'), 'city')

    def test_listing_default_is_not_labeled_as_client_or_map_confirmation(self):
        _, messages, known, _ = _parse(ctx('Собрать шкаф. Ленина 8, квартира 5'))
        facts = contact_facts.collect(messages, known)
        self.assertEqual(known['city'], 'Оренбург')
        self.assertEqual(facts['client_location']['advertised_city'], 'Оренбург')
        self.assertEqual(facts['client_location']['status'], 'missing')
        self.assertFalse(facts['client_location']['message_id'])
        self.assertFalse(facts['client_location']['map_verified'])
        self.assertFalse(facts['address'].get('city'))

    def test_unknown_listing_city_still_requires_a_city(self):
        _, messages, known, _ = _parse(dict(ctx('Нужно собрать шкаф'), city=''))
        question = assistant_qualifiers.next_question(messages, known, contact_facts.collect(messages, known))
        self.assertEqual(question['kind'], 'city')

    def test_explicit_other_city_blocks_before_collecting_contacts(self):
        out = self.preview(dict(ctx('Я в Томске. Нужно собрать шкаф'), city='Омск'))
        self.assertEqual(out['action'], 'handoff')
        self.assertEqual(out['reply'], '')
        self.assertIn('другой город', out['reason'])
        self.assertEqual(out['facts']['client_location']['city'], 'Томск')

    def test_microdistrict_is_preserved_and_requires_map_review(self):
        out = self.preview(dict(ctx('Собрать шкаф. Королева 8 южные ворота этаж 3 кв 191'), city='Омск'))
        self.assertEqual(out['action'], 'handoff')
        self.assertFalse(out['reply'])
        self.assertEqual(out['facts']['address']['settlement'], 'южные ворота')
        self.assertIn('территори', out['reason'])
        self.assertIn('DOC-L0623', out['rule_ids'])
        self.assertFalse(out['facts']['client_location']['map_verified'])

    def test_neural_task_contains_the_needed_service_question_instead_of_city(self):
        context = ctx('Компьютер не включается')
        context.update(dir='kp', accountTitle='Иван КП', itemTitle='Ремонт компьютеров')
        prepared = self.preview(context, wording_mode='neural_review')
        self.assertTrue(prepared['pending_model'])
        task = json.loads(prepared['model_task']['task'])
        self.assertNotEqual(task['decision']['next_question']['kind'], 'city')
        self.assertIn('модель', task['decision']['next_question']['question'])
        self.assertTrue(prepared['requires_operator_review'])

    def test_old_bot_input_uses_the_same_listing_city_decision(self):
        body = dict(chat='synthetic-legacy-city83', city='Оренбург', direction='mnc',
                    partner='7', channel='avito', account_title='Григорий МНЧ', item_title='Сборка мебели',
                    wording_mode='reviewed', dialog=[dict(id='client', role='user', content='Сколько стоит собрать кухонный гарнитур?')])
        result = leadchat.reviewed_answer(body, self.store)
        self.assertNotIn('в каком городе', result['meta']['draft_reply'])
        self.assertIn('сборки', result['meta']['draft_reply'])
        self.assertEqual(result['reply'], '')
        self.assertFalse(result['meta']['auto_enabled'])

    def test_neural_candidate_cannot_append_an_unselected_city_question(self):
        context = ctx('Компьютер не включается')
        context.update(dir='kp', accountTitle='Иван КП', itemTitle='Ремонт компьютеров')
        prepared = self.preview(context, wording_mode='neural_review')
        question = json.loads(prepared['model_task']['task'])['decision']['next_question']['question']
        out, code = self.app.handle(dict(owner='owner', action='finalize', ctx=context,
            request_id=prepared['request_id'], revision=prepared['revision'],
            candidate=dict(reply=question + ' В каком городе вы находитесь?', needs_operator=False)))
        self.assertEqual(code, 200)
        self.assertFalse(out['reply'])
        self.assertIn('unselected_city_question', out['validation'])
        self.assertFalse(out['auto_enabled'])


if __name__ == '__main__':
    unittest.main()
