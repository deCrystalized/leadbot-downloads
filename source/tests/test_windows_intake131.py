"""Ordinary Windows installation is not a hardware-model pricing condition."""
import json,os,tempfile,unittest
from unittest.mock import patch
import assistant_catalog as catalog
import assistant_prices as prices
import qualification_state as qs
from assistant_store import Store
from extension_assistant import Assistant

POSITIVE = ['Сколько стоит установить виндоус?', 'Нужно установить Windows10.',
            'Переустановка виндовс 10 на ноутбуке', 'Поставить Windows 11 на ПК.',
            'Установка Windows на SSD.', 'Нужно установить Windows с сохранением данных.',
            'Вы можете переустановить Windows?', 'Windows 10 установить нужно.']
NEGATIVE = ['Мне не нужна установка Windows, нужно заменить диск.',
            'Сосед сказал: «Нужно установить Windows».',
            'Если понадобится установка Windows, напишу.',
            'Ноутбук не включается. Установить Windows.',
            'Установить Windows и заменить термопасту.',
            'Нужно установить SSD и Windows.', 'Настроить AutoCAD.',
            'Windows зависает, нужен ремонт компьютера.']


class WindowsIntakeScope131Tests(unittest.TestCase):
    pass


def scope_test(body, expected):
    def test(self):
        self.assertEqual(catalog.ordinary_windows_installation(body), expected, body)
    return test


for group,bodies,expected in [('positive',POSITIVE,True),('negative',NEGATIVE,False)]:
    for index,body in enumerate(bodies,1):
        setattr(WindowsIntakeScope131Tests,f'test_{group}_{index:02}',scope_test(body,expected))


def rows(turns):
    return [dict(id=str(i),direction=d,body=b)for i,(d,b)in enumerate(turns)]


class WindowsIntakeNative131Tests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        env=patch.dict(os.environ,LEADBOT_PERSONAL_OWNER_ID='synthetic-windows131',LEADBOT_PERSONAL_AUTO_AVAILABLE='0')
        env.start();self.addCleanup(env.stop)
        self.app=Assistant(Store(tmp.name+'/db'))
        self.known=dict(direction='kp',partner='723',city='Сергиев Посад',channel='avito')

    def preview(self,turns):
        ctx=dict(convId='synthetic-windows131-'+self.id().split('.')[-1],city='Сергиев Посад',dir='kp',channel='avito',
                 partner='723',accountTitle='Учебный мастер КП',origin='Б1',itemTitle='Компьютерная помощь и установка Windows',messages=rows(turns))
        out,code=self.app.handle(dict(owner='synthetic-windows131',action='preview',wording_mode='neural_review',ctx=ctx))
        self.assertEqual(code,200);self.assertFalse(out['auto_enabled']);self.assertTrue(out.get('pending_model'))
        task=json.loads(out['model_task']['task'])
        cleanup,status=self.app.handle(dict(owner='synthetic-windows131',action='finalize',request_id=out['request_id'],
                                          revision=out['revision'],candidate={},model_failure='format'))
        self.assertEqual(status,200);self.assertFalse(cleanup['auto_enabled'])
        return task

    def test_first_price_reply_has_no_unnecessary_hardware_model_gate(self):
        task=self.preview([('in','Здравствуйте, сколько будет стоить у вас установить виндоус?')])
        self.assertNotRegex(task['proposed_reply'].lower(),r'марку|модель|данные.*сохран')
        self.assertNotIn('2000',task['proposed_reply'])
        service=catalog.choose('Нужно установить Windows10.',self.known)
        self.assertNotIn('model',service['items'][0]['questions']);self.assertNotIn('keep_data',service['items'][0]['questions'])

    def test_known_windows_version_is_not_followed_by_generic_model_question(self):
        task=self.preview([('in','Сколько стоит установить Windows?'),('out','Какую Windows нужно установить?'),('in','Десятый')])
        self.assertNotRegex(task['proposed_reply'].lower(),r'марку|модель|какую.*windows|какую.*винд')
        self.assertNotIn('2000',task['proposed_reply'])

    def test_physical_pc_problem_retains_its_questions(self):
        service=catalog.choose('Ноутбук не включается. Нужно установить Windows.',self.known)
        self.assertIn('model',service['items'][0]['questions'])

    def test_bt_appliance_still_requires_model(self):
        service=catalog.choose('Стиральная машина не сливает воду.',dict(direction='bt',city='Оренбург'))
        self.assertIn('model',service['items'][0]['questions'])

    def test_client_data_requirement_is_preserved_as_fact(self):
        state=qs.inspect(rows([('in','Установить Windows10. Данные нужно сохранить.')]))
        self.assertEqual(state['keep_data']['status'],'answered')
        ctx=dict(convId='synthetic-windows-data131',city='Сергиев Посад',dir='kp',channel='avito',partner='723',
                 accountTitle='Учебный мастер КП',itemTitle='Компьютерная помощь',origin='Б1',
                 messages=rows([('in','Установить Windows10. Данные нужно сохранить.')]))
        form,code=self.app.handle(dict(owner='synthetic-windows131',action='checklist',dir='kp',ctx=ctx))
        self.assertEqual(code,200)
        self.assertFalse(form['auto_enabled'])
        self.assertTrue(any('Данные нужно сохранить' in line for line in form['facts']['comment_lines']))
        fact=form['facts']['data_preservation_context']
        self.assertEqual(fact['message_id'],'0');self.assertFalse(fact['execution_confirmed'])
        self.assertNotIn('keep_data',[row['key'] for row in form['results']])

    def test_third_price_stage_keeps_common_windows_tariff(self):
        ms=rows([('in','Сколько стоит установить Windows10?'),('out','Точную стоимость скажу после осмотра.'),
                 ('in','Хотя бы от какой суммы?'),('out','Такая услуга от 500 рублей, без запчастей.'),
                 ('in','Назовите точную стоимость установки Windows10.')])
        answer=prices.answer(ms,self.known,'Установить Windows10')
        self.assertEqual(answer['amounts'],[2000]);self.assertNotIn(1000,answer['amounts'])

    def data_form(self, turns):
        ctx=dict(convId='synthetic-windows-data131-'+self.id().split('.')[-1],city='Сергиев Посад',dir='kp',channel='avito',
                 partner='723',accountTitle='Учебный мастер КП',itemTitle='Компьютерная помощь',origin='Б1',messages=rows(turns))
        form,code=self.app.handle(dict(owner='synthetic-windows131',action='checklist',dir='kp',ctx=ctx))
        self.assertEqual(code,200);self.assertFalse(form['auto_enabled'])
        return form

    def test_data_question_stays_literal_and_not_a_preservation_promise(self):
        body='Установить Windows10. Данные сохранятся?'
        form=self.data_form([('in',body)])
        fact=form['facts']['data_preservation_context']
        self.assertEqual(fact['quote'],body);self.assertFalse(fact['execution_confirmed'])
        self.assertTrue(any('Данные сохранятся?' in line for line in form['facts']['comment_lines']))
        self.assertNotIn('value',fact)

    def test_operator_data_statement_is_not_a_client_requirement(self):
        form=self.data_form([('in','Установить Windows10'),('out','Данные нужно сохранить.')])
        self.assertNotIn('data_preservation_context',form['facts'])
        self.assertFalse(any('сохранении данных' in line for line in form['facts']['comment_lines']))

    def test_short_client_yes_preserves_its_question_link(self):
        form=self.data_form([('in','Установить Windows10'),('out','Данные нужно сохранить?'),('in','Да')])
        fact=form['facts']['data_preservation_context']
        self.assertEqual(fact['quote'],'Да');self.assertEqual(fact['message_id'],'2')
        self.assertEqual(fact['question_quote'],'Данные нужно сохранить?');self.assertFalse(fact['execution_confirmed'])
