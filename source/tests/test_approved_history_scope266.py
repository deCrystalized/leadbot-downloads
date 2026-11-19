"""Trusted approved-only history keeps native identity and source guards."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'leadbot/brain'))
import test_research_history212 as history_fixture
import test_research_server209 as server_fixture
import research_runtime
from assistant_store import Store
from research_history import HistoryCorpus
from research_pipeline import ResearchError
from research_server import configure_server
from research_sources import SourceConfigurationError


class ApprovedHistoryScope266Tests(unittest.TestCase):
    def setUp(self):
        self.f=history_fixture.HistoryTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.seed()

    def corpus(self):
        return HistoryCorpus(self.f.approved,self.f.index,self.f.identities,raw_history_enabled=False)

    def test_approved_only_search_does_not_search_or_read_the_raw_index(self):
        corpus=self.corpus()
        with patch.object(self.f.index,'search',side_effect=AssertionError('Raw search'))as search,\
             patch.object(self.f.index,'read',side_effect=AssertionError('Raw read'))as read:
            result=self.f.search(corpus)
        self.assertEqual(len(result['hits']),2)
        self.assertFalse(result['raw_archive_available'])
        self.assertEqual(result['raw_archive_reason'],'approved_only_trusted_scope')
        self.assertFalse(result['full_pool_verified']);search.assert_not_called();read.assert_not_called()

    def test_direct_raw_case_read_stops_before_loading_a_body(self):
        corpus=self.corpus();self.f.search(corpus)
        with patch.object(self.f.index,'read',side_effect=AssertionError('Raw body opened'))as read:
            with self.assertRaises(ResearchError):
                corpus.call('read_history',dict(case_id='native-c'),self.f.current)
        read.assert_not_called()

    def test_native_identity_exclusion_still_precedes_approved_body_read(self):
        self.f.identities.blocked.add('old-a');corpus=self.corpus();loaded=[]
        original=corpus._body
        def body(record):loaded.append(record['cid']);return original(record)
        corpus._body=body
        self.f.search(corpus);self.assertNotIn('old-a',loaded)
        self.assertIn('old-b',loaded)

    def test_unavailable_protection_does_not_fall_back_to_plain_approved_corpus(self):
        old=self.corpus();self.f.index.source_unavailable(protection=True)
        with self.assertRaises(ResearchError):self.corpus()
        with self.assertRaises(ResearchError):self.f.search(old)

    def test_scope_is_part_of_the_stamp_and_cannot_change_on_an_existing_job(self):
        approved=self.corpus()
        legacy=HistoryCorpus(self.f.approved,self.f.index,self.f.identities,raw_history_enabled=True)
        self.assertNotEqual(approved.initial,legacy.initial)
        approved.raw_history_enabled=True
        with patch.object(self.f.index,'search',side_effect=AssertionError('Scope changed before raw query'))as search:
            with self.assertRaises(ResearchError):self.f.search(approved)
        search.assert_not_called()

    def test_capability_requires_an_actual_boolean(self):
        for value in ('false',0,1,None,{}):
            with self.subTest(value=value),self.assertRaises(ResearchError):
                HistoryCorpus(self.f.approved,self.f.index,self.f.identities,raw_history_enabled=value)


class ApprovedHistoryFactory266Tests(unittest.TestCase):
    def setUp(self):
        self.s=server_fixture.ServerSourceTests();self.s.setUp();self.addCleanup(self.s.doCleanups)
        self.h=history_fixture.HistoryTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.h.seed();self.h.index.protection=SimpleNamespace()
        self.s.config.update(schema=2,native_url='http://127.0.0.1:1',
            native_protection=str(self.s.root/'protection.json'),native_protection_sha256='a'*64,
            native_identity_map=str(self.s.root/'identities.json'),native_identity_map_sha256='b'*64,
            native_history_scope='approved_only')
        self.client=SimpleNamespace(header=lambda *a:self.fail('No native current body requested'),
                                    history=lambda *a:self.fail('No native history requested'))
        self.components=patch('research_server.source_components',return_value=(self.client,self.h.index))
        self.identities=patch('research_history.ApprovedIdentities',return_value=self.h.identities)
        self.components.start();self.addCleanup(self.components.stop)
        self.identities.start();self.addCleanup(self.identities.stop)

    def configure(self):
        self.s.write(self.s.path,self.s.config)
        return configure_server(self.s.path,schedule=lambda fn:self.fail('No job admitted'))

    def service(self):
        return research_runtime.service(Store(self.s.root/'assistant.sqlite3'))

    def test_real_factory_preserves_native_context_and_approved_scope_without_key_or_grants(self):
        result=self.configure();service=self.service();corpus=service.corpus_factory()
        self.assertIsNotNone(service.native_context);self.assertIs(service.native_context.client,self.client)
        self.assertFalse(corpus.raw_history_enabled)
        self.assertEqual(result['source_authority'],'approved_history_with_native_identity_guards_only')
        self.assertFalse(Path(self.s.config['key_file']).exists())
        with service.jobs.connect()as db:self.assertEqual(db.execute('SELECT count(*)FROM grants').fetchone()[0],0)
        with patch.object(self.h.index,'search',side_effect=AssertionError('No raw search')):
            self.assertFalse(self.h.search(corpus)['raw_archive_available'])

    def test_malformed_scope_rejects_before_constructing_sources(self):
        for value in (True,None,{},'raw','APPROVED_ONLY'):
            self.s.config['native_history_scope']=value
            self.s.write(self.s.path,self.s.config)
            with self.subTest(value=value),patch('research_server.ApprovedSources',side_effect=AssertionError('Sources opened')):
                with self.assertRaises(SourceConfigurationError):configure_server(self.s.path)

    def test_schema_one_cannot_smuggle_a_native_scope_field(self):
        self.s.config['schema']=1
        for key in ('native_url','native_protection','native_protection_sha256','native_identity_map','native_identity_map_sha256'):
            self.s.config.pop(key)
        with self.assertRaises(SourceConfigurationError):self.configure()

    def test_scope_config_change_revokes_existing_factory_instead_of_enabling_raw_reads(self):
        self.configure();corpus=self.service().corpus_factory()
        self.s.config['native_history_scope']='approved_and_unreviewed';self.s.write(self.s.path,self.s.config)
        with self.assertRaises(SourceConfigurationError):self.h.search(corpus)

    def test_native_context_cannot_be_overridden_in_approved_only_mode(self):
        self.s.write(self.s.path,self.s.config)
        with self.assertRaises(SourceConfigurationError):
            configure_server(self.s.path,native_context=object())

    def test_explicit_legacy_raw_scope_is_distinct_and_still_grants_no_model_job(self):
        self.s.config['native_history_scope']='approved_and_unreviewed'
        out=self.configure();service=self.service()
        self.assertTrue(service.corpus_factory().raw_history_enabled)
        self.assertEqual(out['source_authority'],'approved_and_guarded_unreviewed_native_history')
        with service.jobs.connect()as db:self.assertEqual(db.execute('SELECT count(*)FROM grants').fetchone()[0],0)


if __name__=='__main__':unittest.main()
