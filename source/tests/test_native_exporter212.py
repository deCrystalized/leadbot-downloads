import copy
import fcntl
import tempfile
import unittest
from pathlib import Path

from native_exporter import NativeExporter
from research_index import DailyIndex, SourceExcluded
import source_protocol as protocol


class SimulatedCrash(BaseException):pass


class ExporterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.directory=Path(self.tmp.name).resolve();self.now=2000000
        self.sources={cid:dict(cid=cid,client_group=cid,phone_hashes=[],media_hashes=[],identity_keys=['a'*64],
            messages=[dict(id=cid+'-1',direction='in',sender_type='client',body='Нужно собрать шкаф')],metadata={}) for cid in ('a','b')}
        self.complete={cid:True for cid in self.sources};self.excluded=set();self.bodies=[];self.header_reads=[]
        case=self
        class Client:
            def catalog(self,after,limit):
                ids=sorted(case.sources);return dict(cids=ids,next=None,complete=True,consistency='fixture')
            def header(self,cid):
                case.header_reads.append(cid)
                if cid in case.excluded:raise SourceExcluded('protected')
                source=case.sources[cid]
                return dict(cid=cid,source_sha256=protocol.sha(protocol.encode(source)),
                    identity_complete=case.complete[cid],message_count=len(source['messages']))
            def history(self,header):
                case.bodies.append(header['cid']);return copy.deepcopy(case.sources[header['cid']])
        self.client=Client()
        self.index=DailyIndex(self.directory/'index',source_instance='native-fixture',guard=lambda _:True,guard_version=lambda:'b'*64)
        self.lock=self.directory/'model.lock'
        self.exporter=NativeExporter(self.client,self.index,self.directory/'scan',shared_lock=self.lock,clock=lambda:self.now)

    def finish(self,**kwargs):
        for _ in range(20):
            value=self.exporter.run(max_cases=20,force=True,**kwargs)
            if value['run'] is None:return value
        self.fail('Finite scan did not finish')

    def test_complete_source_is_published_with_no_training_or_manual_credit(self):
        state=self.finish()
        self.assertEqual(state['indexed'],2);self.assertEqual(self.bodies,['a','b'])
        self.assertFalse(state['weights_trained']);self.assertFalse(state['full_pool_verified'])
        self.assertEqual(self.exporter.path.stat().st_mode&0o777,0o600)

    def test_protected_and_missing_original_cases_have_no_body_load(self):
        self.excluded.add('a');self.complete['b']=False
        state=self.finish()
        self.assertEqual(state['indexed'],0);self.assertEqual(self.bodies,[])
        self.assertEqual(state['pending_original_or_source'],1)

    def test_unchanged_daily_scan_does_not_reload_bodies(self):
        self.finish();self.bodies.clear();self.now+=86401
        self.finish();self.assertEqual(self.bodies,[])

    def test_same_id_asr_edit_advances_observation_revision(self):
        self.finish()
        old=self.index.state()['data_version'];self.sources['a']['messages'][0]['voice_transcript']='Исправление улицы'
        self.now+=86401;self.bodies.clear();self.finish()
        self.assertEqual(self.bodies,['a']);self.assertNotEqual(old,self.index.state()['data_version'])
        with self.index.connect(True) as db:
            self.assertEqual(db.execute('SELECT revision FROM sources WHERE cid=?',('a',)).fetchone()[0],2)

    def test_catalog_disappearance_removes_cache_without_customer_delete(self):
        self.finish();del self.sources['a'];self.now+=86401
        self.finish();self.assertEqual(self.index.state()['records'],1)
        with self.index.connect(True) as db:
            self.assertIsNotNone(db.execute('SELECT 1 FROM tombstones WHERE cid=?',('a',)).fetchone())

    def test_new_unavailable_original_revokes_previously_cached_example(self):
        self.finish();self.complete['a']=False;self.now+=86401;self.bodies.clear()
        state=self.finish();self.assertEqual(state['indexed'],1);self.assertEqual(self.bodies,[])

    def test_crash_after_index_commit_reuses_exact_prepared_bytes_without_body_reload(self):
        def crash():raise SimulatedCrash()
        with self.assertRaises(SimulatedCrash):self.exporter.run(max_cases=20,after_publish=crash)
        self.assertEqual(self.bodies,['a'])
        self.exporter=NativeExporter(self.client,self.index,self.directory/'scan',shared_lock=self.lock,clock=lambda:self.now)
        self.finish();self.assertEqual(self.bodies,['a','b']);self.assertEqual(self.index.state()['records'],2)

    def test_live_model_lock_defers_publication_and_reuses_prepared_source(self):
        with self.lock.open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            state=self.exporter.run(max_cases=20)
            self.assertTrue(state['waiting_for_model_lock']);self.assertEqual(self.index.state()['records'],0)
            self.assertEqual(self.bodies,['a'])
        self.finish();self.assertEqual(self.bodies,['a','b'])

    def test_initial_scan_is_finite_and_completed_scan_waits_until_daily_due(self):
        self.exporter.run(max_cases=1)
        self.assertIsNotNone(self.exporter.state()['run'])
        self.finish();self.bodies.clear()
        self.assertTrue(self.exporter.run()['not_due']);self.assertEqual(self.bodies,[])

    def test_common_transport_failure_stops_instead_of_skipping_whole_pool(self):
        def fail(*args):raise protocol.SourceError('offline')
        self.client.header=fail
        with self.assertRaises(protocol.SourceError):self.exporter.run()
        self.assertIsNotNone(self.exporter.state()['error'])
        self.assertFalse(self.index.state()['healthy'])
        with self.assertRaises(protocol.SourceError):self.exporter.run()
        self.assertEqual(self.bodies,[])

    def test_daily_protection_preflight_precedes_every_new_scan_body(self):
        events=[]
        self.exporter.preflight=lambda remaining:events.append('protection')
        original=self.client.history
        def history(header):
            self.assertEqual(events[-1],'protection')
            return original(header)
        self.client.history=history
        self.finish();self.assertEqual(events,['protection'])
        self.now+=86401;self.finish();self.assertEqual(events,['protection','protection'])

    def test_changed_protected_alias_fences_cache_before_first_source_body(self):
        def reject(remaining):raise protocol.SourceError('Protection refresh required')
        self.exporter.preflight=reject
        with self.assertRaises(protocol.SourceError):self.exporter.run()
        self.assertEqual(self.bodies,[]);self.assertFalse(self.index.state()['healthy'])
        self.assertTrue(self.index.state()['protection_unavailable'])

    def test_new_private_provider_lock_parent_is_prepared_before_publication(self):
        lock=self.directory/'new-private-provider'/'provider.lock'
        self.exporter=NativeExporter(self.client,self.index,self.directory/'scan',shared_lock=lock,clock=lambda:self.now)
        self.assertEqual(lock.parent.stat().st_mode&0o777,0o700)
        self.finish();self.assertEqual(self.index.state()['records'],2)

    def test_symlink_provider_lock_parent_cannot_redirect_publication_lock(self):
        alias=self.directory/'alias';alias.symlink_to(self.directory,target_is_directory=True)
        with self.assertRaises(protocol.SourceError):
            NativeExporter(self.client,self.index,self.directory/'other-scan',shared_lock=alias/'provider.lock')


if __name__=='__main__':unittest.main()
