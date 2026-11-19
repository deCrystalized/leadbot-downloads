"""Owner-confirmed KP service mode; never infer a workshop or an appointment."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from assistant_store import Store
from extension_assistant import Assistant
import assistant_policy as policy
from test_assistant import context, message


class OnsiteOnly114Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner')
        env.start()
        self.addCleanup(env.stop)
        self.app = Assistant(Store(tmp.name + '/db'))

    def preview(self, last, mode='reviewed', **extra):
        rows = [message('Телевизор включается и зависает.', mid='job'),
                dict(message('Когда вам будет удобно меня принять?', 'out', 'staff'), sender_type='operator'),
                message(last, mid='client')]
        out, code = self.app.handle(dict(owner='owner', action='preview', wording_mode=mode,
            ctx=context(rows, city='Челябинск', itemTitle='Ремонт телевизоров', **extra)))
        self.assertEqual(code, 200)
        return out

    def test_direct_dropoff_question_receives_an_explicit_answer(self):
        for text in ('Можно к вам привезти телевизор?', 'Куда привезти телевизор?',
                     'Я могу сам принести ноутбук?', 'Хотел вам его привезти. Есть такая возможность?'):
            with self.subTest(text=text):
                out = self.preview(text)
                self.assertIn('Привоз техники не принимаем.', out['reply'])
                self.assertIn('Мастер выезжает на адрес к клиенту.', out['reply'])
                self.assertNotIn('город', out['reply'])
                self.assertNotIn('мастерск', out['reply'])
                self.assertIn('OWNER-KP-ONSITE-ONLY-20261020', out['rule_ids'])
                self.assertNotIn('DOC-L0702', out['rule_ids'])
                self.assertNotIn('DOC-L0704', out['rule_ids'])

    def test_outoftown_does_not_inherit_ad_city_as_actual_location(self):
        out = self.preview('Я иногородний, хотел вам его привезти. Есть такая возможность?')
        self.assertIn('Привоз техники не принимаем.', out['reply'])
        self.assertIn('В каком населённом пункте нужен выезд?', out['reply'])
        self.assertNotIn('Челябинск', out['reply'])

    def test_model_receives_authoritative_service_mode_without_workshop_facts(self):
        out = self.preview('Можно к вам привезти телевизор?', 'neural_review')
        task = json.loads(out['model_task']['task'])
        mode = task['service_mode_constraint']
        self.assertFalse(mode['client_dropoff_accepted'])
        self.assertEqual(mode['source_id'], 'OWNER-KP-ONSITE-ONLY-20261020')
        self.assertIn('workshop_absent', mode['does_not_establish'])
        self.assertIn('appointment_confirmed', mode['does_not_establish'])
        sources = task.get('sources') or out.get('sources')
        self.assertIn('OWNER-KP-ONSITE-ONLY-20261020', json.dumps(sources))

    def test_supplier_delivery_report_is_not_a_client_dropoff_question(self):
        out = self.preview('Мне завтра привезут детали для телевизора.')
        self.assertNotIn('Привоз техники не принимаем.', out.get('reply', ''))

    def test_kp_rule_is_not_applied_to_other_directions(self):
        out = self.preview('Можно к вам привезти телевизор?', dir='mnc')
        self.assertNotIn('OWNER-KP-ONSITE-ONLY-20261020', out['rule_ids'])

    def test_superseded_repeat_paragraph_is_not_retrieved_as_current(self):
        self.assertEqual(policy.retrieve('', refs=['DOC-L0677'], applied_only=True), [])
        fresh = policy.retrieve('', refs=['DOC20261020-L0677', 'DOC20261020-L0678'], applied_only=True)
        self.assertEqual(len(fresh), 2)
        self.assertIn('КП/БТ', fresh[0]['text'])
        self.assertIn('МНЧ', fresh[1]['text'])


if __name__ == '__main__':
    unittest.main()
