"""Literal absence of one fixture property cannot assert its presence."""
import unittest
import qualification_state as qs


def row(body,role='client',ident='c'):
    return dict(id=ident,body=body,direction='in' if role=='client' else 'out',sender_type=role)


class ToiletNegation188Tests(unittest.TestCase):
    def state(self,*messages):return qs.inspect(list(messages))['toilet_type']

    def test_absence_wording_never_asserts_installation(self):
        for text in ('Унитаз без инсталляции','У унитаза нет инсталляции',
                     'Унитаз, инсталляции нету','Унитаз — отсутствие инсталляции',
                     'Унитаз, инсталляция отсутствует','Унитаз не с инсталляцией'):
            with self.subTest(text=text):
                out=self.state(row(text))
                self.assertNotIn('installation',out['type_labels'])
                self.assertIn('installation',out['excluded_type_labels'])
                self.assertEqual(out['message_id'],'c');self.assertEqual(out['quote'],text)
                self.assertNotIn('ordinary',out['type_labels']);self.assertNotIn('floorstanding',out['type_labels'])

    def test_real_positive_label_survives_separate_exclusion(self):
        for text,expected in [('Обычный унитаз, без инсталляции','ordinary'),
                              ('Унитаз напольный, инсталляции нет','floorstanding')]:
            out=self.state(row(text))
            self.assertEqual(out['status'],'answered');self.assertEqual(out['type_labels'],[expected])
            self.assertIn('installation',out['excluded_type_labels'])

    def test_later_correction_removes_only_contradicted_label(self):
        out=self.state(row('Унитаз с инсталляцией',ident='old'),row('Нет, унитаз без инсталляции',ident='fix'))
        self.assertNotIn('installation',out['type_labels']);self.assertIn('installation',out['excluded_type_labels'])
        self.assertEqual(out['message_id'],'fix')
        out=self.state(row('Унитаз без инсталляции, нет, с инсталляцией'))
        self.assertEqual(out['type_labels'],['installation']);self.assertNotIn('installation',out['excluded_type_labels'])

    def test_absence_in_delivered_question_cannot_become_positive_yes(self):
        out=self.state(row('Унитаз заменить'),row('Унитаз без инсталляции?',role='operator',ident='q'),row('Да'))
        self.assertNotIn('installation',out['type_labels'])

    def test_other_object_and_new_enquiry_do_not_supply_absence(self):
        for text in ('У компьютера без инсталляции программа','У смесителя нет инсталляции'):
            out=self.state(row('Нужно заменить унитаз'),row(text,ident='other'))
            self.assertNotIn('installation',out.get('excluded_type_labels',[]))
        out=self.state(row('Унитаз без инсталляции'),row('Новая заявка: заменить смеситель',ident='new'))
        self.assertNotIn('installation',out.get('excluded_type_labels',[]))

    def test_quotes_hypotheses_reports_and_system_are_not_absence_evidence(self):
        for text in ('Унитаз без инсталляции?','Если унитаз без инсталляции, сколько?',
                     'Унитаз будет без инсталляции','Куплю унитаз без инсталляции',
                     'Унитаз, инсталляция не нужна',
                     'Унитаз «без инсталляции» написано у соседа','Друг сказал, что унитаз без инсталляции'):
            with self.subTest(text=text):
                self.assertNotIn('installation',self.state(row(text)).get('excluded_type_labels',[]))
        self.assertNotIn('installation',self.state(row('Унитаз без инсталляции',role='system')).get('excluded_type_labels',[]))

    def test_positive_correction_and_two_item_labels_remain_literal(self):
        out=self.state(row('Унитаз без инсталляции'),row('Унитаз с инсталляцией, уточнил',ident='fix'))
        self.assertEqual(out['type_labels'],['installation']);self.assertNotIn('installation',out['excluded_type_labels'])
        out=self.state(row('Унитаз без инсталляции'),row('Унитаз с инсталляцией?',role='operator',ident='q'),row('Да',ident='fix'))
        self.assertEqual(out['type_labels'],['installation']);self.assertNotIn('installation',out['excluded_type_labels'])
        out=self.state(row('Старый унитаз без инсталляции, новый с инсталляцией'))
        self.assertEqual(out['type_labels'],['installation']);self.assertNotIn('installation',out['excluded_type_labels'])


if __name__=='__main__':unittest.main()
