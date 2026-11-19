"""A prior availability answer cannot replace the latest observed exchange."""
import json
import unittest
import test_native_wording209 as native


class LatestSpeech253Tests(unittest.TestCase):
    def task(self, middle, latest):
        f=native.NativeWording209Tests();f.setUp()
        try:
            f.ctx['messages'] += [
                dict(id='early',direction='out',sender_type='operator',body='Они в наличии?',delivery_status='delivered'),
                dict(id='a1',direction='in',body='Да.'),
                dict(id='middle',direction='out',sender_type='operator',body=middle,delivery_status='delivered'),
                dict(id='a2',direction='in',body='Да.'),
                dict(id='latest-question',direction='out',sender_type='operator',body=latest,delivery_status='delivered'),
                dict(id='latest-client',direction='in',body='А у него нет деталей.')]
            out,status=f.app.handle(dict(owner='wording209',action='preview',wording_mode='neural_review',ctx=f.ctx))
            self.assertEqual(status,200);self.assertTrue(out.get('pending_model'))
            task=json.loads(out['model_task']['task'])
            self.assertEqual(task['latest_client_message']['id'],'latest-client')
            speech=task['latest_exchange']['previous_staff_speech']
            self.assertEqual(speech['evidence_id'],'latest-question')
            self.assertEqual(speech['body'],latest)
            self.assertEqual(len(task['conversation']),7)
            return task
        finally:f.tearDown()

    def test_earlier_inventory_question_cannot_hide_the_current_third_party_report(self):
        task=self.task('У мастера детали есть?','Схема сборки есть?')
        report=task['literal_third_party_report']
        self.assertEqual(report['evidence_id'],'latest-client')
        self.assertFalse(report['referent_confirmed'])
        self.assertFalse(report['new_request_confirmed'])
        self.assertIn('contractor_inventory',report['does_not_establish'])

    def test_earlier_instruction_question_cannot_replace_the_latest_inventory_exchange(self):
        task=self.task('Схема сборки есть?','У мастера детали есть?')
        self.assertNotIn('literal_third_party_report',task)

    def test_changing_the_middle_answered_topic_does_not_change_the_latest_source(self):
        for middle in ('Схема сборки есть?','У мастера материалы есть?','Какой адрес?'):
            with self.subTest(middle=middle):
                task=self.task(middle,'Схема сборки есть?')
                self.assertEqual(task['literal_third_party_report']['quote'],'А у него нет деталей.')


if __name__=='__main__':unittest.main()
