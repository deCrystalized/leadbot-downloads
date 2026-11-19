import unittest
import qualification_state as qs


def rows(*speech):
    return [dict(id=str(i),direction=d,sender_type='operator'if d=='out'else'client',body=b)
            for i,(d,b)in enumerate(speech)]


class InventoryQuestionCounter220Tests(unittest.TestCase):
    def test_wall_question_and_material_disclosure_are_not_inventory_attempts(self):
        ms=rows(('in','Нужно повесить полку. Крепёж куплен.'),('out','Из какого материала стены?'),
                ('in','Стена кирпичная.'),('out','По материалам смогу сориентировать после осмотра.'),
                ('in','Номер сейчас найду.'))
        row=qs.inspect(ms)['materials']
        self.assertEqual(row['asked'],0)
        self.assertEqual(row['status'],'missing')

    def test_real_punctuated_or_unpunctuated_inventory_question_counts_once(self):
        for prompt in ('Материалы и комплектующие есть?', 'Материалы и комплектующие есть',
                       'Подскажите, все детали в наличии?'):
            with self.subTest(prompt=prompt):
                ms=rows(('in','Нужно повесить полку.'),('out',prompt),('in','Сейчас проверю.'))
                self.assertEqual(qs.inspect(ms)['materials']['asked'],1)

    def test_foreign_stock_wall_and_report_are_not_questions_to_client(self):
        for prompt in ('У мастера материалы есть?', 'У нас все материалы есть?',
                       'У меня материалы есть.', 'Клиент спросил: материалы есть?',
                       'Из какого материала столешница?', 'Сосед спросил: «Материалы есть?»'):
            with self.subTest(prompt=prompt):
                ms=rows(('in','Нужно повесить полку.'),('out',prompt),('in','Сейчас проверю.'))
                self.assertEqual(qs.inspect(ms)['materials']['asked'],0)

    def test_failed_pending_and_system_prompts_cannot_exhaust_client(self):
        for patch in (dict(delivery_status='failed'),dict(delivery='pending'),dict(out_pending=True),
                      dict(role='system'),dict(sender_type='system')):
            ms=rows(('in','Нужно повесить полку.'),('out','Материалы и комплектующие есть?'),('in','Сейчас проверю.'))
            ms[1].update(patch)
            with self.subTest(patch=patch):self.assertEqual(qs.inspect(ms)['materials']['asked'],0)


if __name__=='__main__':unittest.main()
