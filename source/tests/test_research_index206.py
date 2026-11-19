import copy
import json
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from research_index import (DailyIndex,Header,Page,IndexFailure,IndexConflict,IndexBusy,
                            SourceExcluded,source_hash,encoded)


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.epoch=source_hash('protection-v1')
        self.blocked=set();self.guards=[];self.loads=[];self.records={};self.counter=0
        self.index=DailyIndex(self.root/'index',source_instance='synthetic-exporter',
                             guard=self.guard,guard_version=lambda:self.epoch)
        self.current=dict(cid='current-client',client_group='current-group',phone_hashes=[],media_hashes=[])

    def guard(self,header):
        self.guards.append(header.cid)
        return header.cid not in self.blocked

    def record(self,cid='a',revision=1,text='Нужно собрать шкаф.',**extra):
        value=dict(cid=cid,source_revision=revision,client_group='group-'+cid,phone_hashes=[],media_hashes=[],
                   messages=[dict(id='m1',direction='in',sender_type='client',body=text)])
        value.update(extra);self.records[cid]=value;return value

    def header(self,value,**extra):
        return Header(value['cid'],value['source_revision'],value['client_group'],tuple(value['phone_hashes']),
                      tuple(value['media_hashes']),source_hash(value),**extra)

    def page(self,headers,**extra):
        self.counter+=1
        values=dict(source_instance='synthetic-exporter',batch_id='batch-'+str(self.counter),
                    after=self.index.state()['cursor'],next_cursor='cursor-'+str(self.counter),headers=tuple(headers))
        values.update(extra);return Page(**values)

    def load(self,header):
        self.assertIn(header.cid,self.guards,'Identity must be admitted before loading a body')
        self.loads.append(header.cid);return copy.deepcopy(self.records[header.cid])

    def apply(self,*values,**extra):
        page=self.page([self.header(v) for v in values])
        return self.index.apply(page,self.load,expected_version=self.index.state()['version'],**extra)

    def search(self,query='шкаф',**extra):
        return self.index.search(query,expected_version=self.index.state()['version'],current=self.current,**extra)

    def read(self,cid='a',**extra):
        values=dict(expected_version=self.index.state()['version'],current=self.current);values.update(extra)
        return self.index.read(cid,**values)

    def test_complete_source_guard_precedes_body_and_roundtrip_preserves_all_roles(self):
        value=self.record(messages=[dict(id='1',direction='in',sender_type='client',body='Шкаф, вот инструкция.'),
            dict(id='2',direction='system',sender_type='system',body='Не считать новым клиентским заказом'),
            dict(id='3',direction='out',sender_type='operator',body='Вопрос сотрудника?'),
            dict(id='4',direction='in',sender_type='client',body='',voice_transcript='Подождите минуту.',voice_transcript_status='done')])
        self.apply(value);out=self.read()
        self.assertEqual(out['source'],value);self.assertEqual(self.loads,['a'])
        self.assertEqual(out['authority'],'unreviewed_history_not_policy_or_lesson')
        self.assertFalse(out['weights_trained']);self.assertFalse(out['original_media_reviewed'])

    def test_excluded_header_never_loads_body_and_does_not_claim_a_full_pool(self):
        value=self.record();self.blocked.add('a');out=self.apply(value)
        self.assertEqual(out['excluded'],1);self.assertEqual(self.loads,[])
        self.assertEqual(out['state']['records'],0);self.assertFalse(out['state']['full_pool_verified'])

    def test_unavailable_or_implicit_guard_cannot_admit_source(self):
        for guard in (lambda h:None,lambda h:(_ for _ in ()).throw(RuntimeError('private error'))):
            self.index.guard=guard;value=self.record();page=self.page([self.header(value)])
            with self.assertRaises(IndexFailure):self.index.apply(page,self.load,expected_version=self.index.state()['version'])
            self.assertEqual(self.loads,[]);self.assertFalse(self.index.state()['healthy'])

    def test_incomplete_identities_or_duplicate_page_are_rejected_before_body(self):
        value=self.record();h=self.header(value)
        for headers in [(replace(h,identity_complete=False),),(h,h)]:
            page=self.page(headers)
            with self.assertRaises(IndexFailure):self.index.apply(page,self.load,expected_version=self.index.state()['version'])
        self.assertEqual(self.loads,[]);self.assertIsNone(self.index.state()['cursor'])

    def test_changed_source_reindexes_old_terms_and_version(self):
        self.apply(self.record(text='Собрать шкаф.'));old=self.index.state()
        self.apply(self.record(revision=2,text='Нужен сантехник, заменить смеситель.'))
        self.assertNotEqual(self.index.state()['data_version'],old['data_version'])
        self.assertEqual(self.search()['hits'],[]);self.assertEqual(self.search('смеситель')['hits'][0]['cid'],'a')
        self.assertEqual(self.read()['source']['source_revision'],2)

    def test_delete_loads_no_body_and_stale_upsert_cannot_resurrect(self):
        value=self.record();self.apply(value);loads=list(self.loads)
        deleted=replace(self.header(value),source_revision=2,source_sha256='',op='delete')
        page=self.page([deleted]);self.index.apply(page,self.load,expected_version=self.index.state()['version'])
        self.assertEqual(self.loads,loads)
        with self.assertRaises(IndexFailure):self.read()
        self.apply(value);self.assertEqual(self.index.state()['records'],0);self.assertEqual(self.loads,loads)
        self.apply(self.record(revision=3));self.assertEqual(self.index.state()['records'],1)

    def test_same_revision_hash_conflict_preserves_old_publication_but_fences_reads(self):
        self.apply(self.record());old=self.index.state()
        with self.assertRaises(IndexFailure):self.apply(self.record(text='Содержимое изменено без новой ревизии.'))
        now=self.index.state();self.assertEqual(now['cursor'],old['cursor'])
        self.assertEqual(now['data_version'],old['data_version']);self.assertFalse(now['healthy'])
        with self.assertRaises(IndexFailure):self.search()

    def test_replayed_batch_never_loads_or_rewinds_later_watermark(self):
        value=self.record();page=self.page([self.header(value)])
        old=self.index.state();self.index.apply(page,self.load,expected_version=old['version'])
        self.apply(self.record('b'));latest=self.index.state();loads=list(self.loads)
        out=self.index.apply(page,self.load,expected_version=old['version'])
        self.assertTrue(out['replayed']);self.assertEqual(out['state'],latest);self.assertEqual(self.loads,loads)

    def test_conflicting_batch_id_and_stale_observer_do_not_poison_healthy_index(self):
        value=self.record();page=self.page([self.header(value)]);old=self.index.state()
        self.index.apply(page,self.load,expected_version=old['version']);latest=self.index.state()
        with self.assertRaises(IndexConflict):
            self.index.apply(replace(page,next_cursor='different'),self.load,expected_version=latest['version'])
        other=self.page([])
        with self.assertRaises(IndexConflict):self.index.apply(other,self.load,expected_version=old['version'])
        self.assertEqual(self.index.state(),latest);self.assertTrue(latest['healthy'])

    def test_unchanged_revision_advances_cursor_without_loading_or_new_data_version(self):
        value=self.record();self.apply(value);old=self.index.state();loads=list(self.loads)
        out=self.apply(value);self.assertEqual(out['unchanged'],1)
        self.assertNotEqual(out['state']['cursor'],old['cursor'])
        self.assertEqual(out['state']['data_version'],old['data_version']);self.assertEqual(self.loads,loads)

    def test_partial_page_and_bad_source_hash_never_publish_cropped_history(self):
        value=self.record();old=self.index.state();page=self.page([self.header(value)],complete=False)
        with self.assertRaises(IndexFailure):self.index.apply(page,self.load,expected_version=old['version'])
        self.assertEqual(self.loads,[]);self.assertIsNone(self.index.state()['cursor'])
        page=self.page([self.header(value)]);self.records['a']['messages'][0]['body']='changed after header'
        with self.assertRaises(IndexFailure):self.index.apply(page,self.load,expected_version=self.index.state()['version'])
        self.assertEqual(self.index.state()['records'],0)

    def test_source_identity_cannot_differ_from_admitted_header_even_with_matching_hash(self):
        value=self.record();header=replace(self.header(value),client_group='different-group')
        page=self.page([header])
        with self.assertRaises(IndexFailure):self.index.apply(page,self.load,expected_version=self.index.state()['version'])
        self.assertEqual(self.index.state()['records'],0)

    def test_atomic_reader_sees_old_complete_snapshot_before_commit(self):
        self.apply(self.record());old=self.index.state();seen=[]
        def before():
            seen.append(self.index.state());self.assertEqual(self.index.state(),old)
            self.assertEqual([x['cid'] for x in self.search()['hits']],['a'])
        self.apply(self.record('b'),before_publish=before)
        self.assertTrue(seen);self.assertEqual(self.index.state()['records'],2)

    def test_publish_crash_rolls_back_rows_and_watermark_then_verified_retry_recovers(self):
        self.apply(self.record());old=self.index.state();value=self.record('b');page=self.page([self.header(value)])
        def crash():raise OSError('private exporter detail must not be logged')
        with self.assertRaises(IndexFailure):
            self.index.apply(page,self.load,expected_version=old['version'],before_publish=crash)
        failed=self.index.state();self.assertEqual(failed['records'],1);self.assertEqual(failed['cursor'],old['cursor'])
        self.assertFalse(failed['healthy'])
        with self.index.connect(True) as db:
            self.assertNotIn('private exporter detail',encoded([dict(r) for r in db.execute('SELECT * FROM failures')]))
        out=self.index.apply(page,self.load,expected_version=failed['version'])
        self.assertTrue(out['state']['healthy']);self.assertEqual(out['state']['records'],2)

    def test_guard_change_fences_reads_then_metadata_refresh_revokes_without_body(self):
        self.apply(self.record());old=self.index.state();loads=list(self.loads)
        self.epoch=source_hash('protection-v2');self.blocked.add('a')
        with self.assertRaises(IndexFailure):self.read()
        out=self.index.apply(self.page([]),self.load,expected_version=old['version'])
        self.assertEqual(out['protection_revoked'],1);self.assertEqual(out['state']['records'],0)
        self.assertEqual(self.loads,loads);self.assertNotEqual(out['state']['data_version'],old['data_version'])

    def test_guard_change_inside_publication_must_not_advance_watermark(self):
        value=self.record();old=self.index.state()
        def change():self.epoch=source_hash('late protection change')
        with self.assertRaises(IndexFailure):self.apply(value,before_publish=change)
        self.assertEqual(self.index.state()['cursor'],old['cursor']);self.assertEqual(self.index.state()['records'],0)

    def test_current_cid_group_phone_and_media_are_excluded_before_full_body_read(self):
        phone=source_hash('phone identity');media=source_hash('original media')
        value=self.record(phone_hashes=[phone],media_hashes=[media]);self.apply(value)
        scopes=[dict(cid='a'),dict(cid='other',client_group='group-a'),dict(cid='other',phone_hashes=[phone]),
                dict(cid='other',media_hashes=[media])]
        statements=[];connect=self.index.connect
        @contextmanager
        def trace(readonly=False):
            with connect(readonly) as db:
                db.set_trace_callback(statements.append);yield db
        with patch.object(self.index,'connect',trace):
            for current in scopes:
                with self.subTest(current=current),self.assertRaises(IndexFailure):self.read(current=current)
                self.assertEqual(self.index.search('шкаф',expected_version=self.index.state()['version'],current=current)['hits'],[])
        self.assertFalse(any('SELECT payload' in sql for sql in statements))

    def test_fresh_version_is_required_and_role_quotes_are_not_policy(self):
        old=self.index.state();self.apply(self.record(messages=[dict(id='1',direction='in',sender_type='client',body='Шкаф'),
            dict(id='2',direction='out',sender_type='operator',body='Маркерсотрудника'),
            dict(id='3',direction='system',sender_type='system',body='Маркersistem')]))
        with self.assertRaises(IndexConflict):self.read(expected_version=old['version'])
        self.assertEqual(self.search('маркерсотрудника')['hits'],[])
        out=self.search();self.assertFalse(out['full_histories_read'])
        self.assertFalse(out['hits'][0]['semantic_match_verified'])

    def test_corrupted_cached_source_never_returns_as_valid_original(self):
        self.apply(self.record())
        with self.index.connect() as db:db.execute("UPDATE sources SET payload=replace(payload,'шкаф','диван') WHERE cid='a'")
        with self.assertRaises(IndexFailure):self.read()

    def test_busy_writer_does_not_load_or_change_a_healthy_snapshot(self):
        old=self.index.state();value=self.record();page=self.page([self.header(value)])
        with self.index.writer(),self.assertRaises(IndexBusy):
            self.index.apply(page,self.load,expected_version=old['version'])
        self.assertEqual(self.index.state(),old);self.assertEqual(self.loads,[])

    def test_restart_keeps_cursor_search_and_private_file_permissions(self):
        self.apply(self.record());old=self.index.state()
        recovered=DailyIndex(self.index.directory,source_instance='synthetic-exporter',guard=self.guard,guard_version=lambda:self.epoch)
        self.assertEqual(recovered.state(),old)
        self.assertEqual(self.index.path.stat().st_mode&0o777,0o600)
        self.assertEqual(self.index.directory.stat().st_mode&0o777,0o700)
        with self.assertRaises(IndexFailure):DailyIndex(self.index.directory,source_instance='foreign',guard=self.guard,guard_version=lambda:self.epoch)

    def test_explicit_source_exclusion_can_revoke_existing_cache(self):
        self.apply(self.record());value=self.record(revision=2)
        def excluded(header):raise SourceExcluded('protected source')
        self.index.guard=excluded;self.apply(value)
        self.assertEqual(self.index.state()['records'],0);self.assertEqual(self.loads,['a'])

    def test_bounded_source_and_page_never_silently_trim(self):
        value=self.record();length=len(encoded(value).encode())
        with patch('research_index.MAX_SOURCE_BYTES',length-1),self.assertRaises(IndexFailure):self.apply(value)
        self.assertEqual(self.index.state()['records'],0)
        a=self.record();b=self.record('b')
        with patch('research_index.MAX_PAGE_BYTES',length+10),self.assertRaises(IndexFailure):self.apply(a,b)
        self.assertEqual(self.index.state()['records'],0)

    def test_foreign_source_or_unbounded_search_cannot_change_or_read_index(self):
        value=self.record();old=self.index.state();page=self.page([self.header(value)],source_instance='foreign')
        with self.assertRaises(IndexFailure):self.index.apply(page,self.load,expected_version=old['version'])
        self.assertEqual(self.index.state(),old)
        for limit in (True,0,21):
            with self.assertRaises(IndexFailure):self.search(limit=limit)

    def test_500_synthetic_sources_are_incremental_not_a_proof_of_100000_real_chats(self):
        for start in range(0,500,20):
            values=[self.record('synthetic-'+str(i),text='Шкаф, нужна инструкция.') for i in range(start,start+20)]
            self.apply(*values)
        loads=len(self.loads);out=self.search(limit=3)
        self.assertEqual(out['state']['records'],500);self.assertEqual(len(out['hits']),3)
        self.assertFalse(out['full_pool_verified']);self.assertEqual(len(self.loads),loads)

    def test_malformed_current_identity_or_source_id_is_not_an_admission(self):
        self.apply(self.record());version=self.index.state()['version']
        for current in [dict(cid=''),dict(cid='x',client_group=[]),dict(cid='x',phone_hashes=['short'])]:
            with self.subTest(current=current),self.assertRaises(IndexFailure):
                self.index.read('a',expected_version=version,current=current)
        for cid in (None,[], 'x'*201):
            with self.assertRaises(IndexFailure):self.index.read(cid,expected_version=version,current=self.current)

    def test_stale_excluded_identity_does_not_delete_a_newer_allowed_source(self):
        def guard(header):
            self.guards.append(header.cid);return header.client_group!='old-protected-group'
        self.index.guard=guard
        latest=self.record(revision=3,client_group='new-allowed-group');self.apply(latest)
        old=self.record(revision=2,client_group='old-protected-group')
        loads=list(self.loads);out=self.apply(old)
        self.assertEqual(out['stale'],1);self.assertEqual(self.loads,loads)
        self.assertEqual(self.index.state()['records'],1)
        self.assertEqual(self.read()['source'],latest)

    def test_nonempty_source_page_needs_cursor_progress_empty_protection_refresh_does_not(self):
        value=self.record();state=self.index.state();page=self.page([self.header(value)],next_cursor='cursor-fixed')
        self.index.apply(page,self.load,expected_version=state['version']);now=self.index.state()
        empty=self.page([],next_cursor=now['cursor'])
        result=self.index.apply(empty,self.load,expected_version=now['version'])
        self.assertTrue(result['state']['healthy']);now=self.index.state()
        bad=self.page([self.header(value)],next_cursor=now['cursor'])
        with self.assertRaises(IndexFailure):self.index.apply(bad,self.load,expected_version=now['version'])
        self.assertEqual(self.index.state()['cursor'],now['cursor'])
        self.assertTrue(self.index.state()['pending_source_update'])
        empty=self.page([],next_cursor=now['cursor'])
        with self.assertRaises(IndexFailure):
            self.index.apply(empty,self.load,expected_version=self.index.state()['version'])
        self.assertFalse(self.index.state()['healthy'])

    def test_boolean_body_revision_cannot_impersonate_integer_header_revision(self):
        value=self.record();value['source_revision']=True
        header=replace(self.header(value),source_revision=1)
        with self.assertRaises(IndexFailure):
            self.index.apply(self.page([header]),self.load,expected_version=self.index.state()['version'])
        self.assertEqual(self.index.state()['records'],0)


if __name__=='__main__':unittest.main()
