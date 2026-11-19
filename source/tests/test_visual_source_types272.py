"""Wire and local visual attributes agree on the kind of source."""

import copy
import unittest

from research_openai import TransportError, compact_wire_schema
from research_pipeline import schema_matches
import research_vision as vision
import test_research_vision214 as fixture


def attributes(schema):
    return schema['properties']['images']['items']['properties']['attributes']


class VisualSourceTypes272Tests(unittest.TestCase):
    def setUp(self):
        self.schema = vision.schema('research')
        self.wire = compact_wire_schema(self.schema)
        self.image = dict(message_id='diagram', media_id='cabinet', sha256='a' * 64, speaker_role='client')
        self.current = dict(media=dict(images=[self.image]))

    def test_source_type_restrictions_are_sent_as_nested_strict_alternatives(self):
        self.assertEqual(self.wire['type'], 'object')
        self.assertNotIn('anyOf', self.wire)
        options = attributes(self.wire)['anyOf']
        self.assertEqual(len(options), 5)
        for option in options:
            self.assertEqual(option['type'], 'object')
            self.assertFalse(option['additionalProperties'])
            self.assertEqual(set(option['required']), set(fixture.ATTRS))

    def test_drawn_wardrobe_remains_in_description_without_becoming_photographed_device(self):
        value = fixture.observation([self.image])
        item, = value['images']
        item['description'] = 'На схеме отдельные панели и собранный шкаф.'
        item['attributes'].update(content_kind='assembly_diagram', device_kind='wardrobe')
        original = copy.deepcopy(value)
        self.assertFalse(schema_matches(value, self.schema))
        self.assertFalse(schema_matches(value, self.wire))
        with self.assertRaises(ValueError):
            vision.check_observation(value, self.current)
        self.assertEqual(value, original)

        candidate = fixture.observation([self.image])
        candidate['images'][0]['description'] = item['description']
        candidate['images'][0]['attributes']['content_kind'] = 'assembly_diagram'
        self.assertTrue(schema_matches(candidate, self.wire))
        self.assertEqual(vision.check_observation(candidate, self.current), candidate)

    def test_photo_label_error_and_document_keep_their_distinct_boundaries(self):
        for fields, accepted in (
                (dict(content_kind='product_photo', device_kind='tv', visible_symptom='screen_cracks'), True),
                (dict(content_kind='product_photo', device_kind='ethernet_cable', connector_type='RJ45'), True),
                (dict(content_kind='device_label', device_kind='pc', brand='Dell', model='Optiplex 9020'), True),
                (dict(content_kind='device_label', device_kind='tv', visible_symptom='screen_cracks'), False),
                (dict(content_kind='device_message', error_system='windows', error_code='ERR-123'), True),
                (dict(content_kind='device_message', error_system='windows'), False),
                (dict(content_kind='product_photo', error_system='windows', error_code='ERR-123'), False),
                (dict(content_kind='document_image'), True),
                (dict(content_kind='document_image', model='Optiplex 9020'), False)):
            with self.subTest(fields=fields):
                value = fixture.observation([self.image])
                value['images'][0]['attributes'].update(fields)
                self.assertIs(schema_matches(value, self.schema), accepted)
                self.assertIs(schema_matches(value, self.wire), accepted)
                if accepted:
                    self.assertEqual(vision.check_observation(value, self.current), value)

    def test_transport_accepts_separate_review_for_scheme_and_rejects_invalid_wire_original(self):
        case = fixture.Vision214Tests(methodName='test_two_distinct_stages_see_same_pixels_and_cannot_return_customer_reply')
        case.setUp()

        def scheme(value):
            value['images'][0]['attributes']['content_kind'] = 'assembly_diagram'
            value['images'][0]['description'] = 'На схеме шкаф, наличие крепежа неизвестно.'

        result = case.run_pair(scheme)
        self.assertTrue(result['approved'])
        self.assertEqual(len(case.payloads), 2)
        self.assertEqual(case.payloads[0]['text']['format']['schema'], self.wire)
        self.assertFalse(result['human_media_review'])
        self.assertFalse(result['can_send_or_create'])

        def wrong_source_type(value):
            scheme(value)
            value['images'][0]['attributes']['device_kind'] = 'wardrobe'

        with self.assertRaises(TransportError):
            case.run_pair(wrong_source_type)
        self.assertEqual(len(case.payloads), 1)
