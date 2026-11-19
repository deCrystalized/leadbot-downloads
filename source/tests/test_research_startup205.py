import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import assistant_policy as policy
import research_runtime
from assistant_store import Store
from experienced_dialogues import Reader, create_index
from research_pipeline import Corpus
from research_startup import HTTPStartup, configure_http
import test_research_pipeline218 as research_fixture


class StartupTests(unittest.TestCase):
    def test_owner_auto_requires_explicit_network_sol_and_a_finite_typed_allowance(self):
        from dataclasses import replace
        for update in [dict(owner_auto_enabled='yes'),dict(owner_auto_enabled=True),
                       dict(owner_auto_enabled=True,network_enabled=True,profile='sol_astra'),
                       dict(auto_session_call_limit=True),dict(auto_session_call_limit=3),dict(auto_session_call_limit=4097)]:
            with self.subTest(update=update),self.assertRaises(ValueError):replace(self.settings,**update)

    def test_owner_auto_cannot_be_enabled_for_a_non_native_factory(self):
        from dataclasses import replace
        self.settings=replace(self.settings,owner_auto_enabled=True,network_enabled=True)
        with self.assertRaises(ValueError):self.configure()
        self.assertFalse(self.events);self.assertFalse(self.settings.key_file.exists())

    def test_configured_owner_auto_is_not_an_activation_or_paid_call(self):
        from dataclasses import replace
        from types import SimpleNamespace
        self.settings=replace(self.settings,owner_auto_enabled=True,network_enabled=True,auto_session_call_limit=128)
        native=SimpleNamespace(resolver=lambda *args,**kwargs:None)
        result=self.configure(native_context=native)
        self.assertTrue(result['owner_auto_available'])
        service=research_runtime.service(Store(self.root/'automatic.sqlite3'))
        self.assertTrue(service.owner_auto_enabled)
        with service.jobs.connect()as db:
            self.assertEqual(db.execute('SELECT count(*)FROM grants').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*)FROM auto_sessions').fetchone()[0],0)
        self.assertFalse(self.settings.key_file.exists());self.assertNotIn(('scheduled',),self.events)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.events=[]
        self.services=patch.object(research_runtime,'_services',{});self.services.start();self.addCleanup(self.services.stop)
        self.factory=patch.object(research_runtime,'_factory',None);self.factory.start();self.addCleanup(self.factory.stop)
        self.settings=HTTPStartup(self.root/'research',self.root/'missing-key',self.root/'shared.lock',
                                  enabled=True,allowed_cids=('old-a',))
        self.archive=self.root/'archive.sqlite3'
        create_index(self.archive,[research_fixture.ResearchTests().record('old-a')],approved_cids=['old-a'])

    def guard(self,ids):self.events.append(('guard',tuple(ids)))

    def corpus(self):
        self.events.append(('corpus',))
        return Corpus(Reader(self.archive),policy.registry()['sources'],allowed_cids=getattr(self,'allowed_override',['old-a']),
                      guard=self.guard,versions=lambda:'v')

    def configure(self,**extra):
        return configure_http(self.settings,corpus_factory=self.corpus,source_guard=self.guard,
                              schedule=lambda fn:self.events.append(('scheduled',)),**extra)

    def test_default_startup_is_disabled_and_does_not_auto_detect_key(self):
        settings=HTTPStartup(self.root/'r',self.root/'missing',self.root/'shared.lock')
        result=configure_http(settings)
        self.assertFalse(result['configured']);self.assertFalse(self.events)
        self.assertIsNone(research_runtime.service(Store(self.root/'assistant.sqlite3')))

    def test_explicit_factory_is_not_a_network_call_or_a_provider_grant(self):
        result=self.configure()
        self.assertTrue(result['configured']);self.assertFalse(result['network_enabled'])
        service=research_runtime.service(Store(self.root/'assistant.sqlite3'))
        self.assertFalse(service.request.enabled)
        with service.jobs.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM grants').fetchone()[0],0)
        self.assertFalse(self.settings.key_file.exists());self.assertNotIn(('scheduled',),self.events)

    def test_guard_precedes_factory_body_access_and_allowlist_must_still_match(self):
        self.configure();service=research_runtime.service(Store(self.root/'assistant.sqlite3'))
        self.events.clear()
        service.corpus_factory()
        self.assertEqual(self.events[:2],[('guard',('old-a',)),('corpus',)])
        self.allowed_override=['other']
        with self.assertRaises(ValueError):service.corpus_factory()

    def test_missing_guard_unsafe_paths_duplicate_ids_or_wrong_flags_fail_closed(self):
        for update in [dict(enabled=1),dict(network_enabled=1),dict(profile='luna'),
                       dict(allowed_cids=('old-a','old-a')),dict(directory=Path('relative'))]:
            with self.subTest(update=list(update)),self.assertRaises(ValueError):
                values=dict(directory=self.root/'r',key_file=self.root/'k',shared_lock=self.root/'l',enabled=True,allowed_cids=('old-a',))
                values.update(update);HTTPStartup(**values)
        with self.assertRaises(ValueError):configure_http(self.settings,corpus_factory=self.corpus)

    def test_failing_source_guard_cannot_publish_factory(self):
        def denied(ids):raise ValueError('Holdout protection unavailable')
        with self.assertRaises(ValueError):configure_http(self.settings,corpus_factory=self.corpus,source_guard=denied)
        self.assertIsNone(research_runtime._factory)

    def test_explicit_network_setting_still_does_not_read_missing_key_on_startup(self):
        settings=HTTPStartup(self.root/'r',self.root/'missing-key',self.root/'lock',enabled=True,
                             network_enabled=True,allowed_cids=('old-a',))
        configure_http(settings,corpus_factory=self.corpus,source_guard=self.guard,schedule=lambda fn:None)
        service=research_runtime.service(Store(self.root/'assistant.sqlite3'))
        self.assertTrue(service.request.enabled)
        self.assertFalse(self.settings.key_file.exists())

    def test_existing_service_cannot_be_reconfigured_under_its_jobs(self):
        self.configure();research_runtime.service(Store(self.root/'assistant.sqlite3'))
        with self.assertRaises(ValueError):self.configure()


if __name__=='__main__':unittest.main()
