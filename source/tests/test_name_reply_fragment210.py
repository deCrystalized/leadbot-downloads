import unittest
import qualification_state as qs


def rows(body):
    return [dict(id='q', direction='out', sender_type='operator', body='Как к вам обращаться?', delivery_status='delivered'),
            dict(id='a', direction='in', sender_type='client', body=body)]


class NameReplyFragment210Tests(unittest.TestCase):
    def test_name_with_separate_arrival_wish_keeps_sources_and_wish(self):
        source=rows('Иван. Хотелось бы завтра к 14 часам. Можно так?')
        state=qs.inspect(source);row=state['client_name']
        self.assertEqual(row['value'],'Иван');self.assertEqual(row['message_id'],'a')
        self.assertEqual(row['question_message_id'],'q');self.assertEqual(row['quote'],source[-1]['body'])
        self.assertEqual(state['visit_time']['message_id'],'a')

    def test_no_city_pause_ack_or_multiple_names(self):
        for body in ('Чита. Хотелось бы завтра.', 'Спасибо. Хотелось бы завтра.', 'Секунду. Номер найду.',
                     'Хорошо. Можно завтра?', 'Иван. Пётр. Можно завтра?', 'Завтра к 14 часам.'):
            with self.subTest(body=body):self.assertIsNone(qs.name_reply_fragment(rows(body),1))

    def test_no_foreign_negated_or_quoted_name(self):
        for body in ('Муж Иван.', 'Не Иван. Можно завтра?', '«Иван». Можно завтра?',
                     'Сосед сказал: Иван. Можно завтра?', 'Новая заявка. Иван.'):
            with self.subTest(body=body):self.assertIsNone(qs.name_reply_fragment(rows(body),1))

    def test_nonclient_and_undelivered_names_or_prompt(self):
        for index,patch in ((0,dict(delivery_status='failed')),(0,dict(out_pending=True)),
                            (1,dict(sender_type='system')),(1,dict(role='system')),(1,dict(delivery_status='pending'))):
            source=rows('Иван. Можно завтра?');source[index].update(patch)
            with self.subTest(index=index,patch=patch):self.assertIsNone(qs.name_reply_fragment(source,1))

    def test_unasked_name_is_not_guessed_from_capitalized_fragment(self):
        source=rows('Иван. Можно завтра?');source[0]['body']='Из какого материала стены?'
        self.assertIsNone(qs.name_reply_fragment(source,1))
        source[0]['body']='Имя и телефон подскажите?'
        self.assertIsNone(qs.name_reply_fragment(source,1))


if __name__=='__main__':unittest.main()
