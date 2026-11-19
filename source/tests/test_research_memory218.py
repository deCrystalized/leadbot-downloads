import copy
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from api_costs import UsageLedger
from research_memory import MemoryConflict, QuickMemory
from test_research_pipeline218 import context


class QuickMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)/'quick.sqlite3';self.mem=QuickMemory(self.path)

    def current(self):
        c=context();c['owner_id']='owner';return c

    def load(self,mem=None,**patch):
        c=self.current();c.update(patch)
        return (mem or self.mem).load('owner','current',c)

    def test_restart_keeps_source_bound_facts_and_open_question(self):
        c=self.current();r=self.mem.save('owner','current',c,expected_generation=0,authoritative_revision='rev-1')
        self.assertEqual(r['generation'],1)
        out=self.load(QuickMemory(self.path));self.assertEqual(out['payload']['facts'],c['facts']);self.assertEqual(out['payload']['open_questions'],c['open_questions'])
        self.assertEqual(self.path.stat().st_mode&0o777,0o600)

    def test_owner_and_dialogue_are_isolated(self):
        c=self.current();self.mem.save('owner','current',c,expected_generation=0,authoritative_revision='rev-1')
        self.assertEqual(self.mem.load('other','current',{**c, 'owner_id': 'other'})['status'],'missing')
        self.assertEqual(self.mem.load('owner','other-dialogue',{**c, 'dialogue_id': 'other-dialogue'})['status'],'missing')
        with self.assertRaises(MemoryConflict):self.mem.save('other','current',c,expected_generation=0,authoritative_revision='rev-1')

    def test_observed_other_identity_cannot_receive_saved_context_with_same_versions(self):
        c = self.current()
        self.mem.save('owner', 'current', c, expected_generation=0, authoritative_revision='rev-1')
        for changed in ({'owner_id': 'other'}, {'dialogue_id': 'other-dialogue'}):
            with self.subTest(changed=changed), self.assertRaises(MemoryConflict):
                self.mem.load('owner', 'current', {**c, **changed})
        self.assertEqual(self.load()['payload'], c)
        self.assertEqual(self.load()['generation'], 1)

    def test_invalid_current_identity_is_rejected_before_database_read(self):
        c = self.current()
        self.mem.save('owner', 'current', c, expected_generation=0, authoritative_revision='rev-1')
        requests: list[tuple[object, object, object]] = [
            ('owner', 'current', {**c, 'owner_id': 'other'}),
            ('owner', 'current', {**c, 'dialogue_id': 'other-dialogue'}),
            ('owner', 'current', {}),
            ('owner', 'current', None),
            ('owner', 'current', []),
            ('', 'current', {**c, 'owner_id': ''}),
            ('owner', '', {**c, 'dialogue_id': ''}),
            (None, 'current', {**c, 'owner_id': None}),
            ('owner', 1, {**c, 'dialogue_id': 1}),
        ]
        with mock.patch('research_memory.sqlite3.connect', side_effect=AssertionError('Private row must not be read')):
            for owner, cid, observed in requests:
                with self.subTest(owner=owner, cid=cid), self.assertRaises(MemoryConflict):
                    self.mem.load(owner, cid, observed)
        self.assertEqual(self.load()['payload'], c)
        self.assertEqual(self.load()['generation'], 1)

    def test_bound_existing_owners_and_dialogues_keep_their_own_contexts(self):
        contexts = [self.current(), {**self.current(), 'owner_id': 'other'},
                    {**self.current(), 'dialogue_id': 'other-dialogue'}]
        for c in contexts:
            self.mem.save(c['owner_id'], c['dialogue_id'], c,
                          expected_generation=0, authoritative_revision='rev-1')
        for c in contexts:
            with self.subTest(owner=c['owner_id'], cid=c['dialogue_id']):
                self.assertEqual(self.mem.load(c['owner_id'], c['dialogue_id'], c)['payload'], c)

    def test_stale_revision_or_policy_map_or_longmemory_not_returned_as_current(self):
        self.mem.save('owner','current',self.current(),expected_generation=0,authoritative_revision='rev-1')
        for patch in [dict(revision='rev-2'),dict(policy_version='p2'),dict(memory_version='m2'),dict(map_version='map-2')]:
            out=self.load(**patch);self.assertEqual(out['status'],'stale');self.assertIsNone(out['payload'])

    def test_compare_and_swap_stops_stale_worker_and_same_revision_collision(self):
        c=self.current();self.mem.save('owner','current',c,expected_generation=0,authoritative_revision='rev-1')
        changed=copy.deepcopy(c);changed['revision']='rev-2';changed['messages'].append(dict(id='c3',direction='in',sender_type='client',body='Нашёл крепёж'))
        with self.assertRaises(MemoryConflict):self.mem.save('owner','current',changed,expected_generation=0,authoritative_revision='rev-2')
        changed['revision']='rev-1'
        with self.assertRaises(MemoryConflict):self.mem.save('owner','current',changed,expected_generation=1,authoritative_revision='rev-1')
        self.assertEqual(self.load()['payload'],c)

    def test_authoritative_revision_not_supplied_by_model(self):
        with self.assertRaises(MemoryConflict):self.mem.save('owner','current',self.current(),expected_generation=0,authoritative_revision='rev-2')
        self.assertEqual(self.load()['status'],'missing')

    def test_idempotent_save_and_parallel_one_winner(self):
        def save(_):
            try:return QuickMemory(self.path).save('owner','current',self.current(),expected_generation=0,authoritative_revision='rev-1')['generation']
            except MemoryConflict:return 'conflict'
        with ThreadPoolExecutor(max_workers=4)as pool:values=list(pool.map(save,range(4)))
        self.assertEqual(self.load()['generation'],1);self.assertTrue(all(v in(1,'conflict')for v in values))
        again=self.mem.save('owner','current',self.current(),expected_generation=1,authoritative_revision='rev-1');self.assertEqual(again['generation'],1)

    def test_new_revision_replaces_revoked_fact_without_resurrecting_old_one(self):
        c=self.current();self.mem.save('owner','current',c,expected_generation=0,authoritative_revision='rev-1')
        c['revision']='rev-2';c['facts']=[];c['open_questions']=[];c['messages'].append(dict(id='c3',direction='in',sender_type='client',body='Это другой шкаф, раньше писал не о нём'))
        self.mem.save('owner','current',c,expected_generation=1,authoritative_revision='rev-2')
        out=self.load(revision='rev-2');self.assertEqual(out['generation'],2);self.assertEqual(out['payload']['facts'],[])

    def test_unreviewed_model_lesson_never_persisted(self):
        c=self.current();c['lessons']=[dict(text='Мой ответ верен')]
        with self.assertRaises(ValueError):self.mem.save('owner','current',c,expected_generation=0,authoritative_revision='rev-1')
        self.assertEqual(self.load()['status'],'missing')


class DurableCostTests(unittest.TestCase):
    def test_receipts_survive_restart_and_do_not_doublecharge(self):
        with tempfile.TemporaryDirectory()as tmp:
            p=Path(tmp)/'cost.sqlite3';u=dict(input_tokens=10000,output_tokens=2000,input_tokens_details=dict(cached_tokens=8000,cache_write_tokens=0))
            a=UsageLedger(p);a.add('resp-1','gpt-6.1-sol',u,scope=dict(owner='a',dialogue='c1',role='research'))
            b=UsageLedger(p);b.add('resp-1','gpt-6.1-sol',u,scope=dict(owner='a',dialogue='c1',role='research'))
            self.assertEqual(b.summary()['known_usd'],'0.0248');self.assertEqual(b.summary()['calls'],1)
            with self.assertRaises(ValueError):b.add('resp-1','gpt-6.1-sol',u,scope=dict(owner='b',dialogue='c1',role='research'))
            self.assertEqual(p.stat().st_mode&0o777,0o600)

    def test_dialogue_rollups_include_failed_and_unknown_receipts(self):
        with tempfile.TemporaryDirectory()as tmp:
            a=UsageLedger(Path(tmp)/'cost.sqlite3');a.add('x','gpt-6.1-sol',None,status='failed',scope=dict(owner='a',dialogue='c1',role='research'))
            a.add('y','gpt-6-astra',None,status='incomplete',scope=dict(owner='a',dialogue='c2',role='review'))
            rows=a.summary()['by_dialogue'];self.assertEqual(len(rows),2);self.assertTrue(all(r['unknown_calls']==1 for r in rows))
