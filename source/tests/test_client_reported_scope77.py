"""Owner: observed background objects cannot add work the client did not ask for."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import assistant_catalog
import assistant_policy
import contact_facts
import personal_media


def history(body, *observations):
    rows = [dict(id='request', direction='in', body=body)]
    for i, observation in enumerate(observations):
        row = dict(id=f'photo-{i}', direction='in', body='', attachments=[dict(kind='image', media_id=str(i))])
        row.update(personal_media.metadata(row), media_reviewed=True, unread_media=False)
        personal_media.attach_observation(row, observation, source='offline_reviewed_image')
        rows.append(row)
    return rows


def photo(device, **kw):
    return dict(content_kind='product_photo', device_kind=device, **kw)


class ClientReportedScope77Tests(unittest.TestCase):
    def interpreted(self, body, *observations):
        rows = history(body, *observations)
        facts = contact_facts.collect(rows)
        return contact_facts.intent_text(body, facts), facts

    def test_pipe_work_does_not_gain_an_oven_or_tv_repair_from_the_photo(self):
        text, facts = self.interpreted('Подтекает пластиковая труба. Нужно устранить течь.', photo('oven'), photo('tv'))
        self.assertNotRegex(text, r'духов|телевиз')
        self.assertEqual(len(facts['image_observations']), 2, 'Keep visible evidence in the review log')
        self.assertEqual({x['message_id'] for x in facts['excluded_visual_service_context']}, {'photo-0','photo-1'})
        self.assertFalse(any('духовка' in x or 'телевизор' in x for x in facts['comment_lines']))

    def test_cabinet_assembly_does_not_become_tv_bands_refusal(self):
        text, _ = self.interpreted('Нужно собрать шкаф', photo('tv', visible_symptom='tv_screen_bands'))
        out = assistant_catalog.choose(text, dict(direction='mnc', city='Москва'))
        self.assertEqual(out['status'], 'supported', out)
        self.assertNotIn('tv-bands', {x['id'] for x in out['items']})

    def test_tv_stand_is_furniture_even_with_a_tv_in_the_background(self):
        text, _ = self.interpreted('Собрать тумбу под телевизор', photo('tv', visible_symptom='tv_screen_bands'))
        self.assertNotIn('видны полосы', text)
        self.assertNotIn('Основная техника', text)

    def test_explicit_both_jobs_keep_both_objects(self):
        text, facts = self.interpreted('Нужно собрать шкаф и починить телевизор', photo('wardrobe'), photo('tv'))
        self.assertIn('Основная техника на просмотренном фото: телевизор', text)
        self.assertEqual(facts.get('excluded_visual_service_context', []), [])

    def test_unnamed_object_can_still_be_resolved_by_the_reviewed_picture(self):
        for device, expected in [('tv','телевизор'),('oven','духовка'),('wardrobe','шкаф')]:
            text, _ = self.interpreted('Собрать вот это' if device=='wardrobe' else 'Вот так не работает', photo(device))
            self.assertIn(expected, text)

    def test_pc_and_its_display_still_describe_one_computer_complaint(self):
        text, facts = self.interpreted('Компьютер не даёт изображение', photo('pc'), photo('monitor'))
        self.assertIn('компьютер', text)
        self.assertFalse(facts['visual_context_conflict'])
        self.assertEqual(facts.get('excluded_visual_service_context', []), [])

    def test_tv_repair_with_reviewed_bands_retains_the_owner_refusal(self):
        body='Телевизор показывает вот так'
        rows=history(body, photo('tv', visible_symptom='tv_screen_bands'))
        known=dict(direction='kp',channel='avito',partner='7',city='Москва')
        out=assistant_policy.assess(rows, known, contact_facts.collect(rows, known))
        self.assertEqual(out['action'], 'refuse')
        self.assertIn('OWNER-TV-BANDS-20261017', out['rule_ids'])

    def test_tv_and_pc_identity_conflict_still_needs_review(self):
        rows=history('На мониторе полосы', photo('tv',visible_symptom='tv_screen_bands'))
        facts=contact_facts.collect(rows)
        self.assertTrue(facts['visual_context_conflict'])
        out=assistant_policy.assess(rows,dict(direction='kp',channel='avito',partner='7',city='Москва'),facts)
        self.assertEqual(out['action'],'handoff')
        self.assertIn('расходится',out['reason'])

    def test_new_furniture_assembly_is_not_changed_into_repair_by_a_visible_defect(self):
        text, facts = self.interpreted('Нужно собрать шкаф', photo('wardrobe',visible_symptom='damaged_fastener_holes'))
        self.assertNotIn('Повреждённые отверстия', text)
        self.assertTrue(any('повреждённые отверстия' in line for line in facts['comment_lines']), 'Visible same-item condition remains qualified evidence')

    def test_an_actual_requested_furniture_repair_keeps_its_visible_details(self):
        text, _ = self.interpreted('Нужно починить шкаф', photo('wardrobe',visible_symptom='damaged_fastener_holes'))
        self.assertIn('Повреждённые отверстия',text)

    def test_written_heating_or_gas_scope_is_not_removed_by_the_owner_rule(self):
        for body in ('Заменить радиатор отопления', 'Плита верх газ, духовка электрическая не включается'):
            text, _ = self.interpreted(body, photo('oven'))
            out=assistant_catalog.choose(text,dict(direction='bt' if 'Плита' in body else 'mnc',city='Москва'))
            self.assertIn(out['status'],('refuse','agree'),out)


if __name__=='__main__':
    unittest.main()
