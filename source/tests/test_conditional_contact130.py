"""A conditional future decision is not agreement, a booking or a new question."""
import os,tempfile,unittest
from unittest.mock import patch
import assistant_policy as policy
from assistant_store import Store
from extension_assistant import Assistant

POSITIVE = [
    'Если надумаю напишу вам',
    'Если я надумаю, я напишу вам.',
    'Если надумаю — сам свяжусь.',
    'Спасибо, если надумаю, напишу.',
    'Если решусь, позвоню вам.',
    'Когда определюсь, отпишусь.',
    'Как определюсь — свяжусь.',
    'Если мы надумаем, сами напишем вам.',
    'Хорошо, если решимся, позвоним вам.',
]
NEGATIVE = [
    'Если надумаю напишу вам. А сколько стоит?',
    'Если надумаю напишу вам, а сейчас запишите на сегодня.',
    'Клиент сказал: «Если надумаю напишу вам».',
    'Если не надумаю, напишу вам.',
    'Если надумаю, не напишу вам.',
    'Если вы надумаете, напишите мне.',
    'Я уже надумал, установите сегодня.',
    'Если надумаю напишу вам, но сейчас помогите настроить.',
    'Не буду писать. Нужна установка Windows.',
]


class ConditionalContactMeaning130Tests(unittest.TestCase):
    pass


def meaning_test(body, expected):
    def test(self):
        self.assertEqual(policy._client_deferred([body]), expected, body)
    return test


for group, bodies, expected in [('positive', POSITIVE, True), ('negative', NEGATIVE, False)]:
    for index, body in enumerate(bodies, 1):
        setattr(ConditionalContactMeaning130Tests, f'test_{group}_{index:02}', meaning_test(body, expected))


class ConditionalContactIntegration130Tests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        env=patch.dict(os.environ,LEADBOT_PERSONAL_OWNER_ID='synthetic-conditional130',LEADBOT_PERSONAL_AUTO_AVAILABLE='0')
        env.start();self.addCleanup(env.stop)
        self.app=Assistant(Store(tmp.name+'/db'))

    def preview(self, turns, **extra):
        ctx=dict(convId='synthetic-conditional130-'+self.id().split('.')[-1],city='Сергиев Посад',dir='kp',
                 channel='avito',partner='723',accountTitle='Учебный мастер КП',origin='Б1',
                 itemTitle='Компьютерная помощь и установка Windows',
                 messages=[dict(id=str(i),direction=d,body=b) for i,(d,b) in enumerate(turns)])
        ctx.update(extra)
        out,status=self.app.handle(dict(owner='synthetic-conditional130',action='preview',wording_mode='neural_review',ctx=ctx))
        self.assertEqual(status,200);self.assertFalse(out['auto_enabled'])
        if out.get('pending_model'):
            final,code=self.app.handle(dict(owner='synthetic-conditional130',action='finalize',request_id=out['request_id'],
                                           revision=out['revision'],candidate={},model_failure='format'))
            self.assertEqual(code,200);self.assertFalse(final['auto_enabled'])
        return out

    def test_conditional_decision_after_historical_price_is_wait(self):
        out=self.preview([('in','Сколько будет стоить установить Windows?'),('out','Какую Windows нужно установить?'),
                          ('in','Десятую'),('out','В районе 2 тысяч работа будет'),
                          ('out','Сегодня удобно утром?'),('in','Если надумаю напишу вам')])
        self.assertEqual(out['action'],'wait');self.assertEqual(out['reply'],'')
        self.assertFalse(out.get('pending_model'));self.assertFalse(out['lead']['can_create_automatically'])

    def test_prior_staff_booking_still_requires_operator(self):
        out=self.preview([('in','Установить Windows10'),('out','Записал вас на завтра'),('in','Если надумаю напишу вам')])
        self.assertEqual(out['action'],'handoff')
        self.assertTrue(any(g['id']=='VERIFY_EXISTING_APPOINTMENT' for g in out['decision_guards']))
        self.assertEqual(out['reply'],'')

    def test_existing_crm_link_is_not_silently_waited(self):
        out=self.preview([('in','Установить Windows10'),('in','Если надумаю напишу вам')],crmRequestId='synthetic-existing-claim')
        self.assertEqual(out['action'],'handoff');self.assertEqual(out['reply'],'')

    def test_max_remains_excluded(self):
        out=self.preview([('in','Установить Windows10'),('in','Если надумаю напишу вам')],channel='max')
        self.assertEqual(out['action'],'handoff');self.assertEqual(out['reply'],'')

    def test_new_question_releases_the_pause(self):
        out=self.preview([('in','Установить Windows10'),('in','Если надумаю напишу вам'),('in','А сколько стоит установка?')])
        self.assertNotEqual(out['action'],'wait')

    def test_operator_words_do_not_become_client_deferral(self):
        out=self.preview([('in','Установить Windows10'),('out','Если надумаю напишу вам'),('in','На ноутбуке нужна Windows10')])
        self.assertNotEqual(out['action'],'wait')
