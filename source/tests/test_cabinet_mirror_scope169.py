"""Cabinet attributes must not invent another service or invalidate its price."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import assistant_catalog as catalog
from assistant_store import Store
from extension_assistant import Assistant


class CabinetMirrorScope169Tests(unittest.TestCase):
    def choose(self, text):
        return catalog.choose(text, dict(direction='mnc', city='Тюмень'))

    def test_mirrored_cabinet_doors_do_not_order_wall_hanging(self):
        for text in ('Собрать шкаф-купе б/у, двери с зеркалами, размер 200 на 220',
                     'Собрать шкаф с зеркалом',
                     'Сборка шкафа, зеркальные раздвижные двери',
                     'Собрать шкаф, дверцы с зеркалами',
                     'Собрать шкаф с зеркальными дверями'):
            with self.subTest(text=text):
                service = self.choose(text)
                self.assertEqual(service['status'], 'supported')
                self.assertEqual([r['id'] for r in service['items']], ['furniture'])
                self.assertEqual(service['items'][0]['questions'], ['instructions'])

    def test_separately_requested_mirror_hanging_is_retained(self):
        for text in ('Собрать шкаф с зеркалом и повесить зеркало на стену',
                     'Собрать шкаф, зеркальные двери. Ещё закрепить зеркало',
                     'Собрать шкаф и повесить зеркало на дверь',
                     'Повесить зеркало на стену'):
            with self.subTest(text=text):
                service = self.choose(text)
                self.assertIn('hanging', [r['id'] for r in service['items']])
                hanging = next(r for r in service['items'] if r['id'] == 'hanging')
                self.assertIn('wall', hanging['questions'])

    def test_other_independent_hanging_work_is_retained(self):
        for text in ('Собрать шкаф с зеркалом и повесить картину',
                     'Собрать шкаф, двери с зеркалами. Повесить полку',
                     'Собрать шкаф, зеркальные двери. Установить карниз'):
            with self.subTest(text=text):
                self.assertIn('hanging', [r['id'] for r in self.choose(text)['items']])

    def test_wall_cabinet_still_requires_wall_information(self):
        service = self.choose('Собрать шкаф с зеркальными дверями и повесить шкаф на стену')
        furniture = next(r for r in service['items'] if r['id'] == 'furniture')
        self.assertIn('wall', furniture['questions'])

    def test_declined_mount_does_not_add_a_wall_question_to_assembly(self):
        for text in ('Собрать шкаф, повесить его не нужно',
                     'Собрать шкаф, не нужно повесить шкаф',
                     'Собрать шкаф, закрепить его на стене не надо'):
            with self.subTest(text=text):
                furniture = next(r for r in self.choose(text)['items'] if r['id'] == 'furniture')
                self.assertNotIn('wall', furniture['questions'])

    def test_other_peoples_mount_offers_do_not_add_a_wall_question(self):
        for text in ('Собрать шкаф. «Повесить шкаф на стену»',
                     'Собрать шкаф, мастер предложил повесить шкаф'):
            with self.subTest(text=text):
                furniture = next(r for r in self.choose(text)['items'] if r['id'] == 'furniture')
                self.assertNotIn('wall', furniture['questions'])

    def test_completed_mount_is_not_requested_again(self):
        furniture = next(r for r in self.choose('Шкаф уже повесили. Собрать другой шкаф')['items']
                         if r['id'] == 'furniture')
        self.assertNotIn('wall', furniture['questions'])

    def test_glass_replacement_keeps_its_own_approval(self):
        service = self.choose('Собрать шкаф с зеркалом и заменить стекло в дверце шкафа')
        self.assertIn(service['status'], ('agree', 'mixed'))
        self.assertTrue(any(r['status'] == 'agree' for r in service['items']))

    def run_action(self, messages, action='preview'):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
                os.environ, LEADBOT_PERSONAL_OWNER_ID='mirror169',
                LEADBOT_PERSONAL_AUTO_AVAILABLE='0'):
            ctx = dict(convId='synthetic-cabinet-mirror169', dir='mnc', city='Тюмень',
                       channel='avito', partner='7', origin='В43',
                       accountTitle='Учебный МНЧ', itemTitle='Сборка и ремонт мебели',
                       messages=[dict(id=str(i), direction=d,
                                      sender_type='client' if d == 'in' else 'operator', body=t)
                                 for i, (d, t) in enumerate(messages)])
            output, code = Assistant(Store(tmp+'/db')).handle(dict(
                owner='mirror169', action=action, wording_mode='neural_review', ctx=ctx))
            self.assertEqual(code, 200)
            self.assertFalse(output['auto_enabled'])
            return output

    def test_price_and_next_question_use_the_actual_single_job(self):
        out = self.run_action([('in', 'Здравствуйте, сколько стоит собрать шкаф-купе б/у, '
                                     'двери с зеркалами, размер 200 на 220?')])
        self.assertTrue(out['pending_model'])
        task = json.loads(out['model_task']['task'])
        proposed = task['proposed_reply']
        self.assertNotRegex(proposed.lower(), r'стен|600|2000')
        self.assertRegex(proposed.lower(), r'схем|инструкц')
        self.assertFalse(out['lead']['can_create_automatically'])

    def test_repeated_price_stage_uses_furniture_minimum_without_a_mirror_fee(self):
        out = self.run_action([
            ('in', 'Сколько стоит собрать шкаф-купе б/у, двери с зеркалами?'),
            ('out', 'Точная стоимость после осмотра. Схема есть?'),
            ('in', 'Схемы нет. Сколько хотя бы примерно?'),
            ('out', 'На месте сориентирую по стоимости'),
            ('in', 'Сколько у вас начинается сборка?')])
        self.assertTrue(out['pending_model'])
        proposed = json.loads(out['model_task']['task'])['proposed_reply']
        self.assertRegex(proposed, r'1500|1 500')
        self.assertNotRegex(proposed.lower(), r'стен|600|2000|за штуку')

    def test_correct_furniture_minimum_is_not_invalidated_by_mirror_attribute(self):
        out = self.run_action([
            ('in', 'Сколько стоит собрать шкаф-купе б/у, двери с зеркалами?'),
            ('out', 'Схема есть?'),
            ('in', 'Схемы нет, шкаф б/у'),
            ('out', 'От 1500 рублей, точная стоимость после осмотра'),
            ('in', 'Завтра сможете?')])
        self.assertNotIn('стоимость не подтверждена', out.get('reason', ''))
        self.assertNotIn('hanging', [r['rule_id'] for r in out['service']['items']])
        self.assertEqual(out['qualification']['instructions']['status'], 'answered')
        if out.get('pending_model'):
            proposed = json.loads(out['model_task']['task'])['proposed_reply']
            self.assertNotRegex(proposed.lower(), r'стен|схем|инструкц')

    def test_shared_manual_checklist_does_not_request_a_wall_for_mirrored_doors(self):
        out = self.run_action([('in', 'Собрать шкаф-купе, двери с зеркалами')], 'checklist')
        self.assertFalse(out['approval'])
        self.assertIn('DOC-L0326', out['rule_ids'])
        self.assertNotIn('wall', [r['key'] for r in out['results']])
        self.assertNotIn('DOC-L0352', out['rule_ids'])


if __name__ == '__main__':
    unittest.main()
