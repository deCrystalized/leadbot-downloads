"""Owner's Evpatoria correction: acceptance parent is not the CRM visit city."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import assistant_catalog
import assistant_policy as policy
import contact_facts
import filials
import personal_workflow
from assistant_store import Store
from extension_assistant import Assistant, _parse


class SatelliteIdentityTests(unittest.TestCase):
    def ctx(self, city, direction='kp', work='компьютер не включается'):
        return dict(convId='synthetic-satellite', city=city, dir=direction, channel='avito', partner='7',
                    accountTitle='Мастер ' + dict(kp='КП', mnc='МНЧ', bt='БТ')[direction],
                    itemTitle=dict(kp='Ремонт компьютеров', mnc='Сантехник', bt='Ремонт холодильников')[direction],
                    messages=[dict(id='m1', direction='in', body='В Евпатории ' + work)])

    def test_registry_recognizes_valid_label_in_every_profile_but_not_a_wrong_parent(self):
        for direction in ('kp', 'bt', 'mnc'):
            for city in ('Евпатория', 'Евпатория (Симферополь)'):
                self.assertTrue(filials.known(city, direction))
                self.assertFalse(filials.is_main(city, direction))
                self.assertEqual(filials.satellite_of(city, direction), 'Симферополь')
            self.assertFalse(filials.known('Евпатория (Москва)', direction))
        for label in ('Красноярск (Сантехника)', 'Неизвестный (Симферополь)'):
            self.assertEqual(filials.physical_city(label, 'mnc'), label)
        self.assertEqual(filials.physical_city('Ачинск (Красноярск)', 'kp'), 'Ачинск')
        with patch.object(filials, '_overrides', return_value={'kp': {'евпатория': {'status': 'closed'}}}):
            self.assertFalse(filials.known('Евпатория (Симферополь)', 'kp'))

    def test_geography_keeps_child_city_and_separate_acceptance_parent(self):
        for direction in ('kp', 'bt', 'mnc'):
            for city in ('Евпатория', 'Евпатория (Симферополь)'):
                geo = policy.geography(city, direction)
                self.assertEqual(geo['status'], 'known')
                self.assertEqual(geo['crm_city'], 'Евпатория')
                self.assertEqual(geo['crm_label'], 'Евпатория (Симферополь)')
                self.assertEqual(geo['acceptance_city'], 'Симферополь')
                self.assertEqual(geo['satellite_of'], 'Симферополь')
                self.assertEqual(geo['lead_hours'], [2, 2.5])
                self.assertFalse(geo['far_trip'])
                self.assertIn('OWNER-EVPATORIA-SIMFEROPOL-20261017', geo['rule_ids'])
        self.assertEqual(policy.geography('Евпатория (Москва)', 'kp')['status'], 'unknown')

    def test_service_acceptance_and_conditions_match_parent_without_changing_profile(self):
        cases = [('kp', 'Компьютер не включается'), ('kp', 'Телевизор Samsung: полосы на экране'),
                 ('kp', 'Настроить лазерный принтер'), ('mnc', 'Заменить смеситель на кухне'),
                 ('mnc', 'Заменить стояк отопления'), ('mnc', 'Собрать шкаф'),
                 ('bt', 'Холодильник не морозит'), ('bt', 'Газовый бойлер не работает')]
        for direction, text in cases:
            parent = assistant_catalog.choose(text, dict(city='Симферополь', direction=direction))
            for city in ('Евпатория', 'Евпатория (Симферополь)'):
                _, _, known, _ = _parse(self.ctx(city, direction, text))
                self.assertEqual(known['city'], 'Евпатория')
                self.assertEqual(assistant_catalog.choose(text, known), parent)

    def test_normal_form_and_assistant_share_rules_with_full_crm_label(self):
        with tempfile.TemporaryDirectory() as p, patch.dict(os.environ, {'LEADBOT_ASSISTANT_WORDING': 'reviewed'}):
            app = Assistant(Store(p + '/db'))
            for direction, work in [('kp', 'компьютер не включается'), ('mnc', 'заменить смеситель на кухне'), ('bt', 'холодильник не морозит')]:
                for action in ('preview', 'checklist'):
                    out, code = app.handle(dict(owner='offline-satellite', action=action,
                                               ctx=self.ctx('Евпатория (Симферополь)', direction, work)))
                    self.assertEqual(code, 200)
                    self.assertTrue(out['ok'])
                    self.assertEqual(out['geography']['crm_label'], 'Евпатория (Симферополь)')
                    self.assertIn('OWNER-EVPATORIA-SIMFEROPOL-20261017', out['rule_ids'])
                    self.assertFalse(out['auto_enabled'])
                    if action == 'preview':
                        self.assertEqual(out['action'], 'question')
                        self.assertNotIn('другой город', out['reason'])
                    else:
                        self.assertFalse(out['hard_block'])
                        self.assertNotIn('проверить филиал', out['operator_review'])

    def test_request_verification_cannot_replace_satellite_with_parent(self):
        ctx = self.ctx('Евпатория (Симферополь)')
        _, rows, known, revision = _parse(ctx)
        ctx['workflowRevision'] = revision
        proposal = dict(revision=revision, lead=dict(addr=contact_facts.collect(rows, known)['address']),
                        prep=dict(ok=True, cityId='synthetic-child', cityText='Евпатория (Симферополь)'),
                        sel=dict(cityId='synthetic-child'), territory={})
        child = personal_workflow.check_crm(rows, known, ctx, proposal)
        self.assertFalse(any('Город CRM отличается' in r for r in child['reasons']))
        proposal['prep']['cityText'] = 'Симферополь'
        parent = personal_workflow.check_crm(rows, known, ctx, proposal)
        self.assertTrue(any('Город CRM отличается' in r for r in parent['reasons']))
        self.assertFalse(parent['execution_allowed'])


if __name__ == '__main__':
    unittest.main()
