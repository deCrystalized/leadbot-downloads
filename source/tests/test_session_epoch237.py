"""Conditional cleanup narrows only a stop; never adds action authority."""
import unittest
import test_personal_assistant as fixtures


class ConditionalStop237Tests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.PersonalTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)

    def test_old_epoch_cleanup_cannot_stop_a_new_session(self):
        first = self.f.call('personal_start')
        second = self.f.call('personal_start')
        self.assertGreater(second['mode_epoch'], first['mode_epoch'])
        result = self.f.call('personal_stop', expected_mode_epoch=first['mode_epoch'])
        self.assertTrue(result['stop_not_applied'])
        current = self.f.call('personal_status')
        self.assertTrue(current['active'])
        self.assertEqual(current['mode_epoch'], second['mode_epoch'])

    def test_exact_epoch_cleanup_retains_explicit_stop_and_tombstone(self):
        first = self.f.call('personal_start')
        result = self.f.call('personal_stop', expected_mode_epoch=first['mode_epoch'])
        self.assertFalse(result['active'])
        self.assertFalse(self.f.call('personal_status')['active'])
        next_session = self.f.call('personal_start')
        self.assertGreater(next_session['mode_epoch'], first['mode_epoch'])

    def test_malformed_expected_epoch_never_mutates_current_session(self):
        for value in (True, 0, -1, '1'):
            with self.subTest(value=value):
                first = self.f.call('personal_start')
                result = self.f.call('personal_stop', expected_mode_epoch=value)
                self.assertFalse(result['ok'])
                self.assertEqual(result['code'], 'personal_stop_epoch')
                current = self.f.call('personal_status')
                self.assertTrue(current['active'])
                self.assertEqual(current['mode_epoch'], first['mode_epoch'])

    def test_other_tab_cannot_use_epoch_cleanup_to_stop_this_session(self):
        first = self.f.call('personal_start')
        result = self.f.call('personal_stop', expected_mode_epoch=first['mode_epoch'],
                             browser_session='browser:tab:2')
        self.assertEqual(result['code'], 'personal_expired')
        self.assertTrue(self.f.call('personal_status')['active'])
