"""Client/worksite location must not come from quoted or unrelated speech."""
import unittest

import assistant_qualifiers as qualifiers
import contact_facts
import test_listing_city83 as fixtures


def incoming(body, mid='client'):
    return dict(id=mid, direction='in', sender_type='client', body=body)


class LocationSubject254Tests(unittest.TestCase):
    def test_quoted_provider_location_is_not_client_location(self):
        for quote in ('«Мы в Москве»', '“Мы в Москве”', '"Мы в Москве"'):
            with self.subTest(quote=quote):
                self.assertEqual(qualifiers.client_city([
                    incoming('Нужно собрать шкаф. В объявлении написано ' + quote + '.')]), '')

    def test_negation_cannot_overwrite_own_location(self):
        self.assertEqual(qualifiers.client_city([
            incoming('Я в Чите. Я не в Москве.')]), 'Чита')

    def test_other_person_cannot_overwrite_own_location(self):
        self.assertEqual(qualifiers.client_city([
            incoming('Я в Чите. Сестра в Москве.')]), 'Чита')

    def test_hypothetical_or_past_location_is_not_current(self):
        for other in ('Если я в Москве, Вы приедете?', 'Раньше я жил в Москве.'):
            with self.subTest(other=other):
                self.assertEqual(qualifiers.client_city([
                    incoming('Я в Чите. ' + other)]), 'Чита')

    def test_unrelated_question_does_not_override_client_location(self):
        self.assertEqual(qualifiers.client_city([
            incoming('Я в Чите. Вы работаете в Москве?')]), 'Чита')

    def test_actual_worksite_and_correction_remain_usable(self):
        for text in ('Я в Москве, нужно собрать шкаф.', 'Нужно собрать шкаф в Москве.',
                     'Я не в Чите, а в Москве.', 'Раньше жил в Чите, сейчас я в Москве.'):
            with self.subTest(text=text):
                self.assertEqual(qualifiers.client_city([incoming(text)]), 'Москва')

    def test_literal_answer_to_observed_city_question_remains_usable(self):
        for text in ('Чита', '«Чита»', 'В Чите'):
            with self.subTest(text=text):
                self.assertEqual(qualifiers.client_city([
                    dict(id='staff', direction='out', sender_type='operator',
                         body='В каком Вы городе?'), incoming(text)]), 'Чита')

    def test_source_id_points_to_affirmation_not_later_quoted_mention(self):
        rows = [incoming('Я в Чите.', 'own'),
                incoming('Сестра сказала «Я в Чите», а сама в Москве.', 'other')]
        location = qualifiers.client_location(rows, dict(city='Чита'), {})
        self.assertEqual(location['city'], 'Чита')
        self.assertEqual(location['message_id'], 'own')
        self.assertEqual(location['quote'], 'Я в Чите.')
        self.assertFalse(location['map_verified'])

    def test_provider_question_with_explicit_own_location_keeps_own_answer(self):
        self.assertEqual(qualifiers.client_city([
            incoming('Вы из Омска? Я в Томске.')]), 'Томск')

    def test_other_person_then_own_clause_keeps_explicit_own_city(self):
        self.assertEqual(qualifiers.client_city([
            incoming('Сестра в Москве, а я в Чите.')]), 'Чита')

    def test_self_pronoun_does_not_become_third_party(self):
        self.assertEqual(qualifiers.client_city([incoming('Я сам в Москве.')]), 'Москва')

    def test_reported_third_party_claim_is_not_an_own_assertion(self):
        self.assertEqual(qualifiers.client_city([
            incoming('Я в Чите.'), incoming('Мастер сказал, что я в Москве.')]), 'Чита')

    def test_explicit_requested_worksite_for_relative_remains_usable(self):
        self.assertEqual(qualifiers.client_city([
            incoming('Мне нужно собрать шкаф у сестры в Москве.')]), 'Москва')

    def test_nonclient_roles_cannot_supply_location_through_in_direction(self):
        for role in ('operator', 'employee', 'staff', 'human', 'manager', 'admin',
                     'agent', 'system', 'avito', 'bot', 'assistant', 'automation'):
            with self.subTest(role=role):
                row = dict(incoming('Я в Москве.'), sender_type=role)
                self.assertEqual(qualifiers.client_city([incoming('Я в Чите.'), row]), 'Чита')

    def test_pending_or_failed_messages_cannot_supply_location(self):
        for delivery in ('failed', 'pending', 'sending', 'queued', 'out_pending'):
            with self.subTest(delivery=delivery):
                row = dict(incoming('Я в Москве.'), delivery_status=delivery)
                self.assertEqual(qualifiers.client_city([incoming('Я в Чите.'), row]), 'Чита')

    def test_failed_city_question_does_not_give_bare_name_authority(self):
        rows = [dict(id='staff', direction='out', sender_type='operator',
                     delivery_status='failed', body='В каком Вы городе?'), incoming('Чита')]
        self.assertEqual(qualifiers.client_city(rows), '')


class LocationSubjectPreview254Tests(unittest.TestCase):
    setUp = fixtures.ListingCity83Tests.setUp

    def preview(self, text):
        result, code = self.app.handle(dict(owner='owner', action='preview',
            ctx=dict(fixtures.ctx(text), city='Чита')))
        self.assertEqual(code, 200)
        self.assertFalse(result['auto_enabled'])
        return result

    def test_quote_does_not_create_city_handoff_in_real_preview(self):
        out = self.preview('Нужно собрать шкаф. В объявлении написано «Мы в Москве».')
        self.assertEqual(out['facts']['client_location']['status'], 'missing')
        self.assertNotIn('другой город', out['reason'])

    def test_negation_preserves_city_in_real_preview_and_contact_facts(self):
        out = self.preview('Я в Чите. Я не в Москве. Нужно собрать шкаф.')
        self.assertEqual(out['facts']['client_location']['city'], 'Чита')
        self.assertEqual(out['facts']['client_location']['status'], 'confirmed')
        self.assertNotIn('другой город', out['reason'])

    def test_actual_other_worksite_still_requires_territory_verification(self):
        out = self.preview('Нужно собрать шкаф в Москве.')
        self.assertEqual(out['facts']['client_location']['city'], 'Москва')
        self.assertEqual(out['action'], 'handoff')
        self.assertFalse(out['reply'])


if __name__ == '__main__':
    unittest.main()
