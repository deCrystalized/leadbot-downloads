"""A wire schema must expose the vocabulary its unchanged validator accepts."""
import copy
import unittest

import personal_media
import research_vision as vision
from research_pipeline import schema_matches
import test_research_vision214 as fixtures


class VisualTypes227Tests(unittest.TestCase):
    def fields(self):
        return vision.schema('research')['properties']['images']['items']['properties']['attributes']['properties']

    def test_original_free_russian_types_are_rejected_without_mapping_or_json_repair(self):
        image=dict(message_id='m1',media_id='photo1',sha256='a'*64,speaker_role='client')
        value=fixtures.observation([image]);value['images'][0]['attributes'].update(content_kind='фотография мебели',device_kind='шкаф',visible_symptom='Открытые секции корпуса')
        original=copy.deepcopy(value)
        self.assertFalse(schema_matches(value,vision.schema('research')))
        with self.assertRaises(ValueError):vision.check_observation(value,dict(media=dict(images=[image])))
        self.assertEqual(value,original)

    def test_all_exposed_category_codes_respect_the_existing_semantic_validator(self):
        fields=self.fields()
        for kind in fields['content_kind']['enum']:
            if kind:
                attrs=dict(content_kind=kind)
                if kind=='device_message':attrs.update(error_system='windows',error_code='ERR-123')
                self.assertEqual(personal_media.normalize_observations(attrs)['content_kind'],kind)
        for device in fields['device_kind']['enum']:
            if device:
                self.assertEqual(personal_media.normalize_observations(dict(content_kind='product_photo',device_kind=device))['device_kind'],device)
        for symptom in fields['visible_symptom']['enum']:
            if symptom:
                device=personal_media.FURNITURE_SIGNS[symptom][0]if symptom in personal_media.FURNITURE_SIGNS else 'tv'
                self.assertEqual(personal_media.normalize_observations(dict(content_kind='product_photo',device_kind=device,visible_symptom=symptom))['visible_symptom'],symptom)
        self.assertNotIn('contact_note',fields['content_kind']['enum'])
        self.assertEqual(fields['connector_type']['enum'],['','RJ45'])
        for system in fields['error_system']['enum']:
            if system:self.assertEqual(personal_media.normalize_observations(dict(content_kind='device_message',error_system=system,error_code='ERR-123'))['error_system'],system)

    def test_free_description_and_unknown_kit_survive_a_valid_observation_pair(self):
        case=fixtures.Vision214Tests(methodName='test_two_distinct_stages_see_same_pixels_and_cannot_return_customer_reply');case.setUp()
        def details(value):
            value['images'][0].update(description='Белый частично собранный каркас; комплектность за кадром неизвестна.',unknowns=['Детали и крепёж вне кадра не проверены.'])
            value['images'][0]['attributes'].update(content_kind='product_photo',device_kind='wardrobe')
        result=case.run_pair(details)
        self.assertTrue(result['approved']);self.assertEqual(result['visual_observation']['images'][0]['attributes']['device_kind'],'wardrobe')
        self.assertIn('не проверены',result['visual_observation']['images'][0]['unknowns'][0]);self.assertFalse(result['human_media_review'])
        self.assertFalse(result['can_send_or_create']);self.assertNotIn('reply',result)

    def test_justified_visual_veto_is_still_preserved_instead_of_forcing_success(self):
        case=fixtures.Vision214Tests(methodName='test_two_distinct_stages_see_same_pixels_and_cannot_return_customer_reply');case.setUp()
        def uncertain(value):value.update(needs_operator=True);value['limitations']=['Содержимое невозможно надёжно различить.']
        result=case.run_pair(uncertain)
        self.assertFalse(result['approved']);self.assertTrue(result['visual_observation']['needs_operator']);self.assertTrue(result['review']['approved'])
        self.assertEqual(len(case.payloads),2)

    def test_cross_object_codes_still_fail_independently_of_enum_membership(self):
        image=dict(message_id='m1',media_id='p',sha256='a'*64,speaker_role='client');value=fixtures.observation([image])
        value['images'][0]['attributes'].update(content_kind='product_photo',device_kind='wardrobe',visible_symptom='screen_cracks')
        self.assertTrue(schema_matches(value,vision.schema('research')))
        with self.assertRaises(ValueError):vision.check_observation(value,dict(media=dict(images=[image])))
        value['images'][0]['attributes'].update(visible_symptom='',connector_type='RJ45')
        with self.assertRaises(ValueError):vision.check_observation(value,dict(media=dict(images=[image])))


if __name__=='__main__':unittest.main()
