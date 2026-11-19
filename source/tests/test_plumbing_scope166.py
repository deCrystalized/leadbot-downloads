"""A plumbing support is not a second furniture order; real mixed work survives."""
import os
import tempfile
import unittest
from unittest.mock import patch

import assistant_catalog as catalog
from assistant_store import Store
from extension_assistant import Assistant, _parse

PLUMBING = ('Установить унитаз на готовое место, подключить к воде и канализации; '
            'установить умывальник: закрепить к стене/тумбе, подключить сифон и смеситель; '
            'посмотреть батарею, она текла, отопление отключили и перекрывается, возможен мелкий ремонт.')


class PlumbingScope166Tests(unittest.TestCase):
    def choose(self, text):
        return catalog.choose(text, dict(direction='mnc', city='Абакан'))

    def test_three_real_plumbing_jobs_do_not_create_furniture_or_wall_questions(self):
        service = self.choose(PLUMBING)
        self.assertEqual(service['status'], 'mixed')
        items = {item['id']: item for item in service['items']}
        self.assertTrue({'toilet', 'sink', 'plumbing-tap', 'pipes-riser'} <= items.keys())
        self.assertNotIn('furniture', items)
        self.assertNotIn('hanging', items)
        self.assertIn('DOC-L0286', service['rules'])
        self.assertIn('DOC-L0270', service['rules'])
        self.assertNotIn('DOC-L0350', service['rules'])

    def test_washbasin_alias_retains_sink_admission_without_cabinet_order(self):
        for text in ('Установить умывальник на тумбу', 'Заменить раковину на готовой тумбе',
                     'Починить умывальник на тумбе', 'На тумбе установить умывальник',
                     'Установить умывальник: закрепить к стене/тумбе',
                     'Установить мойку на шкаф', 'Сифон под раковиной на тумбе протекает'):
            with self.subTest(text=text):
                service = self.choose(text)
                self.assertNotIn('furniture', [item['id'] for item in service['items']])
                self.assertNotIn('DOC-L0323', service['rules'])

    def test_independent_cabinet_assembly_is_kept_in_same_sentence_or_next_clause(self):
        for text in ('Установить раковину на тумбу и собрать тумбу',
                     'Установить умывальник к стене/тумбе. Собрать тумбу',
                     'Установить тумбу под раковину', 'Собрать тумбу для умывальника'):
            with self.subTest(text=text):
                service = self.choose(text)
                self.assertIn('furniture', [item['id'] for item in service['items']])
                self.assertIn('DOC-L0323', service['rules'])

    def test_a_sink_wall_mount_does_not_supply_a_cabinet_wall_mount(self):
        service = self.choose('Установить раковину: закрепить к стене/тумбе. Отремонтировать тумбу')
        item = next(item for item in service['items'] if item['id'] == 'furniture')
        self.assertTrue(item['repair_only'])
        self.assertFalse(item.get('wall_mount_only'))
        self.assertEqual(item['questions'], ['furniture_problem'])
        self.assertNotIn('DOC-L0350', item['primary_refs'])
        mounted = self.choose('Установить раковину на тумбу. Повесить шкаф на стену')
        item = next(item for item in mounted['items'] if item['id'] == 'furniture')
        self.assertTrue(item['wall_mount_only'])
        self.assertIn('wall', item['questions'])

    def test_explicit_furniture_parts_and_reverse_order_cannot_be_erased(self):
        for text in ('На тумбе с раковиной заменить дверцу', 'Заменить тумбу под умывальником',
                     'Установить раковину, а на тумбе заменить петли',
                     'Починить ножку тумбы рядом с умывальником'):
            with self.subTest(text=text):
                self.assertIn('furniture', [item['id'] for item in self.choose(text)['items']])

    def test_heating_agreement_is_not_waived_by_off_or_shutoff_water(self):
        for text in (PLUMBING, 'Установить умывальник на тумбу; заменить радиатор, отопление отключено'):
            service = self.choose(text)
            self.assertIn('DOC-L0286', service['rules'])
            self.assertIn(service['status'], ('mixed', 'agree'))
            self.assertNotIn('furniture', [item['id'] for item in service['items']])

    def test_shared_preview_preserves_literal_jobs_and_optional_owner_scope_without_write(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='plumbing166', LEADBOT_PERSONAL_AUTO_AVAILABLE='0'):
            app = Assistant(Store(tmp + '/db'))
            ctx = dict(convId='synthetic-plumbing166', dir='mnc', city='Абакан', partner='7', channel='avito',
                       accountTitle='Учебный МНЧ', origin='С76', itemTitle='Сантехник',
                       messages=[dict(id='job', direction='in', sender_type='client', body=PLUMBING)])
            out, status = app.handle(dict(owner='plumbing166', action='preview', wording_mode='neural_review', ctx=ctx))
            self.assertEqual(status, 200)
            # OWNER-MIXED-OPTIONAL-LOOK-20261023 changes whole-job handoff:
            # primary jobs keep their conditions; heating is inspection only.
            self.assertTrue(out.get('pending_model'))
            self.assertFalse(out.get('reply'))
            self.assertFalse(out['auto_enabled'])
            self.assertFalse(out['lead']['can_create_automatically'])
            self.assertIn('DOC-L0286', out['rule_ids'])
            self.assertEqual({item['rule_id'] for item in out['service']['items']},
                             {'toilet', 'sink', 'plumbing-tap'})
            scope=out['facts']['mixed_optional_work']
            self.assertEqual(scope['extras'][0]['subject'],'heating')
            self.assertFalse(scope['extra_execution_approved'])
            self.assertRegex(scope['comment'],'по возможности посмотреть отопление')
            self.assertEqual(scope['extras'][0]['message_id'],'job')
            self.assertEqual(ctx['messages'][0]['body'], PLUMBING)
            self.assertEqual(_parse(ctx)[1][0]['body'], PLUMBING)


if __name__ == '__main__':
    unittest.main()
