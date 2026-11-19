import copy
import unittest
from pathlib import Path
from unittest.mock import patch

import test_research_server209 as fixture
from research_server import configure_server
import research_runtime
from assistant_store import Store
from source_protocol import SourceError


class NativeServerTests(unittest.TestCase):
    def setUp(self):
        self.base=fixture.ServerSourceTests();self.base.setUp();self.addCleanup(self.base.doCleanups)
        b=self.base;self.protection=b.root/'native-protection.json'
        self.value=dict(schema=1,final_holdout_size=1000,source_final_manifest_sha256='a'*64,
            protected_cids=['sealed-'+str(i) for i in range(1000)],protected_identity_keys=['b'*64],
            protected_media_refs=[],media_reference_scan_complete=True)
        b.write(self.protection,self.value)
        self.identities=b.root/'identities.json'
        b.write(self.identities,dict(schema=1,approved_cids=['old-a'],semantic_review_credit=0,
            protection_version=b.sha(self.protection),headers={'old-a':dict(cid='old-a',identity_keys=['c'*64],
                client_group='c'*64,phone_hashes=[],media_hashes=[])}))
        self.config=dict(b.config,schema=2,native_url='https://chat.partner-lead-centre.ru',
            native_protection=str(self.protection),native_protection_sha256=b.sha(self.protection),
            native_identity_map=str(self.identities),native_identity_map_sha256=b.sha(self.identities))
        b.write(b.path,self.config)

    def service(self):
        configure_server(self.base.path,schedule=lambda _:None)
        return research_runtime.service(Store(self.base.root/'assistant.sqlite3'))

    def test_actual_startup_binds_native_context_raw_index_and_approved_sources_without_network(self):
        with patch('http.client.HTTPSConnection',side_effect=AssertionError('No network on startup')):
            service=self.service();corpus=service.corpus_factory()
        self.assertIsNotNone(service.native_context)
        self.assertEqual(corpus.native_index.state()['records'],0)
        self.assertEqual(corpus.allowed,{'old-a'})
        self.assertFalse(Path(self.config['key_file']).exists())
        self.assertEqual(service.jobs.directory.parent,self.base.root/'research')

    def test_new_identity_map_pin_changes_revoke_existing_corpus(self):
        corpus=self.service().corpus_factory();self.identities.write_bytes(self.identities.read_bytes()+b' ')
        with self.assertRaises(SourceError):corpus.check()

    def test_changed_guard_revokes_native_source_before_any_network(self):
        service=self.service();self.protection.write_bytes(self.protection.read_bytes()+b' ')
        with patch('http.client.HTTPSConnection',side_effect=AssertionError('No source after guard change')):
            with self.assertRaises(SourceError):service.native_context.client.header('old-a')

    def test_native_configuration_cannot_be_overridden_by_browser_dependency(self):
        with self.assertRaises(ValueError):configure_server(self.base.path,native_context=object())

    def test_missing_identity_publication_is_not_approved_only_silent_fallback(self):
        value=copy.deepcopy(self.config);value.pop('native_identity_map');self.base.write(self.base.path,value)
        with self.assertRaises(ValueError):configure_server(self.base.path)


if __name__=='__main__':unittest.main()
