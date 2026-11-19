import unittest
import qualification_state as qs


def message(text, **patch):
    return dict(dict(id='client', direction='in', sender_type='client', body=text), **patch)


class SingularHanging210Tests(unittest.TestCase):
    def test_current_singular_named_fixture_has_source_and_narrow_scope(self):
        row=qs.inspect([message('Нужно повесить полку в квартире. Схема есть.')])['volume']
        self.assertEqual(row['status'],'answered')
        self.assertEqual(row['message_id'],'client')
        self.assertEqual(row['volume_scope'],'client_named_hanging_item_only')
        self.assertEqual(row['value'],'Нужно повесить полку')

    def test_width_is_not_count_and_plural_quantity_stays_unknown(self):
        for body in ('Полка 80 сантиметров.', 'Нужно повесить полки.', 'Нужно повесить несколько полок.'):
            with self.subTest(body=body):self.assertIsNone(qs.singular_hanging_work(message(body)))

    def test_not_past_foreign_quote_or_hypothetical_work(self):
        for body in ('Вчера нужно было повесить полку.', 'Если повесить полку, сколько выйдет?',
                     'Не нужно повесить полку.', 'Сосед просил: «Нужно повесить полку».',
                     'Мастер сказал повесить полку.', 'Нужно повесить полку и картину.'):
            with self.subTest(body=body):self.assertIsNone(qs.singular_hanging_work(message(body)))

    def test_no_whole_quantity_for_mixed_job(self):
        self.assertIsNone(qs.singular_hanging_work(message('Нужно повесить полку и заменить смеситель.')))

    def test_nonclient_or_failed_work_is_not_client_quantity(self):
        for patch in (dict(sender_type='operator'),dict(role='system'),dict(speaker_role='operator'),
                      dict(delivery_status='failed'),dict(delivery='pending')):
            with self.subTest(patch=patch):self.assertIsNone(qs.singular_hanging_work(message('Нужно повесить полку.',**patch)))


if __name__=='__main__':unittest.main()
