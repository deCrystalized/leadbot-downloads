import copy
import json
import tempfile
import unittest
from pathlib import Path

from native_context import NativeContext
from source_protection import SourceProtection
from research_index import SourceExcluded
import source_protocol as protocol


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.directory=Path(self.tmp.name).resolve()
        self.calls=[];self.now=100.0
        self.source=dict(cid='cid',messages=[dict(id='m',direction='in',sender_type='client',body='Настоящий вопрос')],
            metadata=dict(status='in_progress',crm_request_id=None,assignee_id='operator',claimed_by_id='operator'))
        case=self
        class Client:
            def header(self,cid,actor):
                case.calls.append(('header',cid,copy.deepcopy(actor)))
                return dict(cid=cid,source_sha256=protocol.sha(protocol.encode(case.source)),
                            client_group='native-client',phone_hashes=[],media_hashes=[])
            def history(self,header,actor):
                case.calls.append(('body',header['cid'],copy.deepcopy(actor)))
                return copy.deepcopy(case.source)
            def image(self,header,descriptor,actor):
                case.calls.append(('image',header['cid'],copy.deepcopy(actor)))
                return dict(data=b'original',mime='image/jpeg',sha256='a'*64)
        self.bridge=NativeContext(Client(),self.directory/'source',clock=lambda:self.now)
        self.body=dict(owner='owner',ctx=dict(convId='cid',messages=[dict(id='bad',body='Подмена браузера')],
            conversationStatus='new',crmRequestId='invented'))
        self.identity=dict(principal_id='principal',operator_id='operator')

    def test_canonical_native_history_replaces_browser_text_status_and_crm(self):
        original=copy.deepcopy(self.body)
        result,header,actor=self.bridge.prepare(self.body,self.identity)
        self.assertEqual(result['ctx']['messages'],self.source['messages'])
        self.assertEqual(result['ctx']['conversationStatus'],'in_progress')
        self.assertIsNone(result['ctx']['crmRequestId'])
        self.assertEqual(self.body,original)
        files=list((self.directory/'source').glob('*.json'))
        self.assertEqual(len(files),1);self.assertEqual(files[0].stat().st_mode&0o777,0o600)
        self.assertEqual(json.loads(files[0].read_text())['source'],self.source)
        self.assertNotIn('identity_proof',files[0].read_text())

    def test_unchanged_full_snapshot_is_reused_only_after_fresh_native_header(self):
        self.bridge.prepare(self.body,self.identity);self.bridge.prepare(self.body,self.identity)
        self.assertEqual([r[0] for r in self.calls],['header','body','header'])

    def test_late_same_id_edit_loads_new_immutable_evidence(self):
        first=self.bridge.prepare(self.body,self.identity)[1]
        self.source['messages'][0]['voice_transcript']='Исправление адреса'
        second=self.bridge.prepare(self.body,self.identity)[1]
        self.assertNotEqual(first,second)
        self.assertEqual(len(list((self.directory/'source').glob('*.json'))),2)

    def test_owner_and_operator_sources_cannot_borrow_other_cache_scope(self):
        self.bridge.prepare(self.body,self.identity)
        self.body['owner']='other';self.bridge.prepare(self.body,self.identity)
        self.bridge.prepare(self.body,dict(self.identity,operator_id='other-operator'))
        self.assertEqual(len([r for r in self.calls if r[0]=='body']),3)

    def test_original_requires_fresh_exact_owner_cid_revision_binding(self):
        _,header,actor=self.bridge.prepare(self.body,self.identity)
        scope=dict(owner_id='owner',dialogue_id='cid',revision='rev')
        descriptor=dict(message_id='m',source_message_id='m',media_id='p',attachment_hash='h',position=0)
        with self.assertRaises(protocol.SourceError):self.bridge.resolver(scope,descriptor)
        self.bridge.bind('owner','cid','rev',header,actor)
        self.assertEqual(self.bridge.resolver(scope,descriptor)['data'],b'original')
        for field in ('owner_id','dialogue_id','revision'):
            with self.assertRaises(protocol.SourceError):self.bridge.resolver(dict(scope,**{field:'other'}),descriptor)
        self.now+=46
        with self.assertRaises(protocol.SourceError):self.bridge.resolver(scope,descriptor)

    def test_tampered_immutable_current_snapshot_is_not_silently_repaired(self):
        self.bridge.prepare(self.body,self.identity)
        next((self.directory/'source').glob('*.json')).write_text('{}')
        self.bridge.snapshots.clear()
        with self.assertRaises(protocol.SourceError):self.bridge.prepare(self.body,self.identity)


class ProtectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name).resolve()/'protection.json'
        self.value=dict(schema=1,final_holdout_size=1000,source_final_manifest_sha256='c'*64,
            protected_cids=['protected-'+str(i) for i in range(1000)],
            protected_identity_keys=['a'*64],protected_media_refs=['b'*64],media_reference_scan_complete=True)
        self.path.write_bytes(protocol.encode(self.value));self.path.chmod(0o600)
        self.protection=SourceProtection(self.path,protocol.sha(self.path.read_bytes()))
        self.header=dict(cid='development',client_group='d'*64,identity_keys=['d'*64],media_hashes=[])

    def test_cid_alias_phone_identity_and_media_reference_excluded_before_body(self):
        with self.assertRaises(SourceExcluded):self.protection.cids(['protected-1'])
        self.assertTrue(self.protection.header(self.header))
        for change in (dict(identity_keys=['a'*64]),dict(client_group='a'*64),dict(media_hashes=['b'*64])):
            with self.assertRaises(SourceExcluded):self.protection.header(dict(self.header,**change))

    def test_missing_complete_identity_or_changed_protection_never_admits(self):
        with self.assertRaises(protocol.SourceError):self.protection.header(dict(self.header,identity_keys=[]))
        self.path.write_bytes(protocol.encode(dict(self.value,protected_cids=[])))
        with self.assertRaises(protocol.SourceError):self.protection.cids(['development'])

    def test_fake_short_final_roster_is_not_complete_protection(self):
        self.path.write_bytes(protocol.encode(dict(self.value,protected_cids=['only-one'])))
        with self.assertRaises(protocol.SourceError):SourceProtection(self.path,protocol.sha(self.path.read_bytes()))

    def test_daily_preflight_reads_only_complete_metadata_and_detects_new_alias(self):
        calls=[]
        def metadata(cids,remaining):
            self.assertGreater(remaining,0)
            calls.append(list(cids))
            return [dict(cid=cid,identity_keys=['a'*64],media_hashes=['b'*64])for cid in cids]
        out=self.protection.verify_current_metadata(metadata)
        self.assertEqual(out['protected_headers_observed'],1000)
        self.assertEqual(out['source_bodies_read'],0);self.assertEqual(max(map(len,calls)),25)
        with self.assertRaises(protocol.SourceError):
            self.protection.verify_current_metadata(lambda cids,left:[dict(cid=cid,identity_keys=['f'*64])for cid in cids])

    def test_incomplete_protected_metadata_cannot_be_silently_skipped(self):
        with self.assertRaises(protocol.SourceError):
            self.protection.verify_current_metadata(lambda cids,left:[dict(cid=cid,pending=True)for cid in cids])


if __name__=='__main__':unittest.main()
