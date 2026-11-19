"""Unavailable inbound history stays visible but has no client-fact authority."""
import copy
import os
import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
import extension_assistant as ext
import dialogue_lifecycle as lifecycle
from assistant_store import Store
from test_assistant import context
import test_native_wording209 as native


class IncomingDelivery252Tests(unittest.TestCase):
    def ctx(self,status):
        return context([dict(id='valid',direction='in',sender_type='client',body='Нужно собрать шкаф.'),
                        dict(id='unavailable',direction='in',sender_type='client',
                             body='Помощь больше не нужна.',delivery_status=status)],
                       convId='synthetic-delivery252',dir='mnc',accountTitle='Мастер на час',itemTitle='Мастер на час')

    def test_unavailable_source_is_not_normalized_as_a_current_client_fact(self):
        for status in ('failed','error','cancelled','canceled','pending','queued','sending'):
            with self.subTest(status=status):
                ctx=self.ctx(status);before=copy.deepcopy(ctx)
                _,rows,_,_=ext._parse(ctx)
                self.assertEqual([m['id']for m in rows],['valid'])
                self.assertEqual([m['id']for m in ext._source_timeline(ctx)],['valid','unavailable'])
                self.assertEqual(ctx,before)

    def test_full_assistant_does_not_stop_for_an_undelivered_withdrawal(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,LEADBOT_PERSONAL_OWNER_ID='delivery252'):
            app=ext.Assistant(Store(Path(directory)/'db'))
            out,status=app.handle(dict(owner='delivery252',action='preview',ctx=self.ctx('canceled'),wording_mode='reviewed'))
            self.assertEqual(status,200);self.assertEqual(out['action'],'question')
            self.assertFalse(out['needs_operator'])

    def test_native_task_keeps_original_row_without_making_it_latest_client_meaning(self):
        f=native.NativeWording209Tests();f.setUp()
        try:
            f.ctx['messages'].append(dict(id='undelivered',direction='in',sender_type='client',
                                         body='Помощь больше не нужна.',delivery_status='canceled'))
            import json
            prepared,status=f.app.handle(dict(owner='wording209',action='preview',wording_mode='neural_review',ctx=f.ctx))
            self.assertEqual(status,200)
            self.assertTrue(prepared.get('pending_model'),prepared.get('reason'))
            task=json.loads(prepared['model_task']['task'])
            self.assertEqual(task['latest_client_message']['id'],'client')
            self.assertEqual(task['conversation'][-1]['id'],'undelivered')
            self.assertEqual(task['conversation'][-1]['delivery_status'],'canceled')
        finally:f.tearDown()

    def test_unavailable_incoming_does_not_cancel_confirmed_silence_timer(self):
        now=datetime(2026,10,30,tzinfo=timezone.utc)
        rows=[dict(id='sent',direction='out',sender_type='operator',body='Схема есть?',
                   created_at=now.isoformat(),delivery_status='delivered'),
              dict(id='failed',direction='in',sender_type='client',body='Не нужно.',
                   created_at=(now+timedelta(seconds=1)).isoformat(),delivery_status='failed')]
        self.assertEqual(lifecycle.silence_timer(rows,dict(direction='mnc'),now=now+timedelta(seconds=2))['status'],'waiting')
