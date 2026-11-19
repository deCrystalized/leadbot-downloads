import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import filials
import territory


class FarTripTests(unittest.TestCase):
    def test_owner_whole_kilometre_threshold(self):
        for km in (0, 35.9, 36, 36.4, 36.5, 36.9, 36.99):
            with self.subTest(km=km):
                self.assertTrue(filials.far_trip_distance_allowed(km))
        for km in (37, 37.01, 38, -1, None, True, '36.9', float('nan'), float('inf')):
            with self.subTest(km=km):
                self.assertFalse(filials.far_trip_distance_allowed(km))

    def test_actual_geocoded_trip_uses_the_same_threshold(self):
        for km in (36.4, 36.9, 36.99, 37, 37.4):
            with self.subTest(km=km), patch('geocode.geocode', return_value=(1, 1)), \
                    patch.object(territory, 'city_has_map', return_value=False), \
                    patch.object(territory, 'filial_coords', return_value={'Курск': {'lat': 0, 'lon': 0}}), \
                    patch.object(territory, '_haversine_km', return_value=km):
                out = territory.far_trip('село Дальнее, Ленина 5', 'Курск', 'kp', 'компьютер')
                if km < 37:
                    self.assertIsNotNone(out)
                    self.assertEqual(out[0], 'Курск')
                    self.assertLess(out[1], 37)
                else:
                    self.assertIsNone(out)

    def test_owner_rule_is_registered_with_its_scope(self):
        import assistant_policy
        rule = next(x for x in assistant_policy.registry()['sources'] if x['id'] == 'OWNER-FAR-TRIP-DECIMAL-20261018')
        self.assertEqual(rule['type'], 'user')
        self.assertIn('36,9', rule['text'])
        self.assertIn('37', rule['text'])
        self.assertIn('КП', rule['scope'])


if __name__ == '__main__':
    unittest.main()
