"""Physical presence, operation and entry codes are different CRM facts."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
from contact_facts import collect
from personal_workflow import required_crm_fields


def msg(body, direction='in', mid='client'):
    return dict(id=mid, body=body, direction=direction)


class IntercomPresenceTests(unittest.TestCase):
    def test_absence_has_negative_evidence_and_does_not_keep_an_old_card_code(self):
        for text in ('Домофона нет', 'Домофон отсутствует', 'Нет домофона'):
            with self.subTest(text=text):
                facts = collect([msg(text)], {'card_address': {'street': 'Ленина', 'building': '1', 'intercom': '123'}})
                self.assertIs(facts['intercom_present'], False)
                self.assertIs(facts['intercom_working'], False)
                self.assertEqual(facts['evidence']['intercom_present']['message_id'], 'client')
                self.assertNotIn('intercom', facts['address'])
                self.assertIn('Домофон отсутствует.', facts['comment_lines'])

    def test_broken_device_still_exists(self):
        for text in ('Домофон не работает', 'Лифт не работает, домофон тоже'):
            with self.subTest(text=text):
                facts = collect([msg(text)])
                self.assertIs(facts['intercom_present'], True)
                self.assertIs(facts['intercom_working'], False)
                self.assertIn('Домофон не работает.', facts['comment_lines'])

    def test_present_does_not_prove_working(self):
        for text in ('Домофон есть', 'Есть домофон'):
            facts = collect([msg(text)])
            self.assertIs(facts['intercom_present'], True)
            self.assertIsNone(facts['intercom_working'])
        facts = collect([msg('Домофон работает')])
        self.assertIs(facts['intercom_present'], True)
        self.assertIs(facts['intercom_working'], True)

    def test_unknown_and_staff_words_do_not_change_profile_presence(self):
        for rows in ([msg('Адрес Ленина 1')], [msg('Домофона нет', 'out')], [msg('Домофон есть', 'note')]):
            facts = collect(rows, {'card_address': {'intercom': '123'}})
            self.assertIsNone(facts['intercom_present'])
            self.assertNotIn('intercom_present', facts['evidence'])

    def test_intercom_code_proves_presence_but_door_code_does_not(self):
        known = {'card_address': {'street': 'Ленина', 'building': '1'}}
        facts = collect([msg('Домофон 123')], known)
        self.assertIs(facts['intercom_present'], True)
        self.assertIsNone(facts['intercom_working'])
        facts = collect([msg('Код двери 123')], known)
        self.assertIsNone(facts['intercom_present'])

    def test_new_door_code_can_coexist_with_absent_intercom(self):
        facts = collect([msg('Ленина 1, домофона нет. Код двери 456')])
        self.assertIs(facts['intercom_present'], False)
        self.assertEqual(facts['address']['intercom'], '456')
        self.assertIn('Код входа: 456.', facts['comment_lines'])
        self.assertNotIn('Домофон: 456.', facts['comment_lines'])

    def test_latest_absence_clears_old_client_code(self):
        facts = collect([msg('Ленина 1, домофон 123', mid='old'), msg('Домофона нет', mid='new')])
        self.assertIs(facts['intercom_present'], False)
        self.assertNotIn('intercom', facts['address'])
        self.assertEqual(facts['evidence']['intercom_present']['message_id'], 'new')

    def test_later_named_code_replaces_absence_without_inventing_working_state(self):
        facts = collect([msg('Ленина 1. Домофона нет', mid='old'), msg('Домофон 456', mid='new')])
        self.assertIs(facts['intercom_present'], True)
        self.assertIsNone(facts['intercom_working'])
        self.assertEqual(facts['address']['intercom'], '456')

    def test_changed_address_does_not_inherit_old_presence(self):
        facts = collect([msg('Ленина 1, домофон есть', mid='old'), msg('Адрес другой: Ленина 2', mid='new')])
        self.assertIsNone(facts['intercom_present'])
        self.assertIsNone(facts['intercom_working'])

    def test_new_address_code_does_not_inherit_old_broken_device(self):
        facts = collect([msg('Ленина 1, домофон не работает', mid='old'),
                         msg('Адрес другой: Пушкина 2, домофон 456', mid='new')])
        self.assertIs(facts['intercom_present'], True)
        self.assertIsNone(facts['intercom_working'])
        self.assertEqual(facts['address']['intercom'], '456')

    def test_presence_is_a_required_post_read_field_only_when_known(self):
        for text in ('Домофона нет', 'Домофон не работает', 'Домофон есть'):
            self.assertIn('домофон', required_crm_fields([msg(text)], {}))
        self.assertNotIn('домофон', required_crm_fields([msg('Ленина 1')], {}))


if __name__ == '__main__':
    unittest.main()
