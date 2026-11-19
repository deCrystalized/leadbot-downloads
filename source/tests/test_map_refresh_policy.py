"""The real importer helper retains reviewed times without moving boundaries."""
import ast
import copy
import unittest
from pathlib import Path

source = Path(__file__).resolve().parents[1] / 'leadbot/analysis/fetch_filial_zones.py'
tree = ast.parse(source.read_text())
function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'preserve_reviewed_zone_policy')
namespace = {}
exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
preserve = namespace['preserve_reviewed_zone_policy']


class MapRefreshPolicyTests(unittest.TestCase):
    def old(self):
        return dict(direction='kp',name='Мытищи (МСК)',city='Мытищи',ring=[[1,2],[2,3],[3,1]],
                    lead='три, три с половиной часа',policy_zone='north',policy_source='TG1-670',policy_date='2026-09-24')

    def test_generic_map_label_cannot_erase_reviewed_time_in_same_contour(self):
        old=self.old();new={k:v for k,v in old.items() if not k.startswith('policy_')};new['lead']='два, два с половиной часа'
        previous=copy.deepcopy(old);areas=[new]
        self.assertEqual(preserve(areas,{'areas':[old]}),[])
        self.assertEqual(new['lead'],old['lead']);self.assertEqual(new['policy_zone'],'north')
        self.assertEqual(old,previous)

    def test_changed_or_duplicate_contours_require_review_without_copying_metadata(self):
        old=self.old()
        for areas in ([dict(old,ring=[[1,2],[2,4],[3,1]])],[dict(old),dict(old)]):
            before=copy.deepcopy(areas)
            self.assertTrue(preserve(areas,{'areas':[old]}));self.assertEqual(areas,before)

    def test_other_map_rules_are_left_to_their_original_source(self):
        old=dict(self.old(),policy_source='other-rule');new=dict(old,lead='new time')
        self.assertEqual(preserve([new],{'areas':[old]}),[]);self.assertEqual(new['lead'],'new time')


if __name__ == '__main__':
    unittest.main()
