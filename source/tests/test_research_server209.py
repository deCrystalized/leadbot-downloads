import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from assistant_store import Store
from experienced_dialogues import create_index, Reader
import experience_runtime
import research_runtime
import research_sources
from research_server import configure_server
from research_sources import ApprovedSources, SourceConfigurationError
import test_research_pipeline218 as fixtures


class ServerSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        for name, value in [('_services', {}), ('_factory', None)]:
            p = patch.object(research_runtime, name, value); p.start(); self.addCleanup(p.stop)
        self.archive = self.root / 'archive.sqlite3'
        create_index(self.archive, [fixtures.ResearchTests().record('old-a')], approved_cids=['old-a'])
        self.write(self.root / 'lessons.json', {'schema': 1, 'records': []})
        self.write(self.root / 'reviews.json', {'schema': 1, 'reviews': {}})
        pointer = dict(schema=1, archive=self.archive.name, archive_version=Reader(self.archive).version(),
                       lessons='lessons.json', reviews='reviews.json')
        for key in ('archive', 'lessons', 'reviews'):
            pointer[key + '_sha256'] = self.sha(self.root / pointer[key])
        self.pointer = self.root / 'current.json'; self.write(self.pointer, pointer)
        self.manifest = self.root / 'permission.json'
        self.permission = dict(schema=1, approved_cids=['old-a'], excluded_cids=['sealed'],
            protection_version='immutable-protection-hash', pointer=str(self.pointer),
            pointer_sha256=self.sha(self.pointer))
        self.write(self.manifest, self.permission)
        self.path = self.root / 'config.json'
        self.config = dict(schema=1, enabled=True, network_enabled=False, profile='sol_only',
            directory=str(self.root / 'research'), key_file=str(self.root / 'absent-key'),
            shared_lock=str(self.root / 'calls.lock'), sources_manifest=str(self.manifest),
            sources_sha256=self.sha(self.manifest), proposal_enabled=True)
        self.write(self.path, self.config)

    def write(self, path, value):
        path.write_text(json.dumps(value)); path.chmod(0o600)

    def sha(self, path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def sources(self):
        return ApprovedSources(self.manifest, self.sha(self.manifest))

    def test_actual_publication_is_used_by_server_factory_without_key_or_calls(self):
        out = configure_server(self.path, schedule=lambda fn: self.fail('No job admitted'))
        self.assertTrue(out['configured']); self.assertFalse(out['network_enabled'])
        self.assertEqual(out['source_count'], 1)
        service = research_runtime.service(Store(self.root / 'assistant.sqlite3'))
        corpus = service.corpus_factory()
        self.assertEqual(corpus.allowed, {'old-a'})
        self.assertTrue(service.proposal_enabled)
        self.assertFalse(Path(self.config['key_file']).exists())
        with service.jobs.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM grants').fetchone()[0], 0)

    def test_absent_or_disabled_config_reads_no_sources_and_cannot_detect_saved_key(self):
        with patch.object(research_sources, 'private_file', side_effect=AssertionError('source read')):
            self.assertFalse(configure_server()['configured'])
        self.write(self.path, dict(schema=1, enabled=False))
        with patch('research_server.ApprovedSources', side_effect=AssertionError('source construction')):
            self.assertFalse(configure_server(self.path)['configured'])

    def test_exclusion_guard_runs_before_archive_open_even_with_valid_pointer(self):
        self.permission['approved_cids'].append('sealed'); self.write(self.manifest, self.permission)
        with patch.object(experience_runtime, 'pointer_files', side_effect=AssertionError('body opened')):
            with self.assertRaisesRegex(ValueError, 'protected'):
                self.sources()

    def test_unknown_source_cannot_read_any_body(self):
        sources = self.sources()
        with patch.object(experience_runtime, 'pointer_files', side_effect=AssertionError('body opened')):
            with self.assertRaises(SourceConfigurationError): sources.guard(['not-approved'])

    def test_changed_permission_fences_an_existing_corpus(self):
        sources = self.sources(); corpus = sources.corpus()
        self.permission['protection_version'] = 'revoked'; self.write(self.manifest, self.permission)
        with self.assertRaises(SourceConfigurationError): corpus.check()

    def test_changed_publication_fences_existing_corpus_without_old_snapshot_fallback(self):
        corpus = self.sources().corpus()
        self.pointer.write_text(self.pointer.read_text() + ' ')
        with self.assertRaises(SourceConfigurationError): corpus.check()

    def test_changed_archive_is_detected_by_immutable_hash(self):
        self.archive.write_bytes(self.archive.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'snapshot file changed'): self.sources().corpus()

    def test_permission_cannot_approve_only_a_subset_of_publication_roster(self):
        self.permission['approved_cids'] = ['different']; self.write(self.manifest, self.permission)
        with self.assertRaisesRegex(ValueError, 'roster'): self.sources().corpus()

    def test_config_revocation_stops_already_created_service(self):
        configure_server(self.path, schedule=lambda fn: None)
        service = research_runtime.service(Store(self.root / 'assistant.sqlite3'))
        corpus = service.corpus_factory()
        self.write(self.path, dict(schema=1, enabled=False))
        with self.assertRaisesRegex(ValueError, 'revoked'): corpus.check()
        with self.assertRaisesRegex(ValueError, 'revoked'): service.corpus_factory()

    def test_invalid_config_never_publishes_factory_or_falls_back_to_giga(self):
        for field, value in [('network_enabled', 1), ('profile', 'luna'), ('directory', 'relative'),
                             ('key_file', None), ('proposal_enabled', 'yes')]:
            with self.subTest(field=field):
                config = copy.deepcopy(self.config); config[field] = value; self.write(self.path, config)
                with self.assertRaises(ValueError): configure_server(self.path)
                self.assertIsNone(research_runtime._factory)

    def test_browser_style_keys_models_endpoints_or_grants_are_not_configuration(self):
        for name in ('api_key', 'endpoint', 'model', 'grant_id', 'max_calls'):
            config = dict(self.config, **{name: 'forged'}); self.write(self.path, config)
            with self.assertRaises(ValueError): configure_server(self.path)
        self.assertIsNone(research_runtime._factory)

    def test_config_permissions_symlink_and_hardlink_fail_closed(self):
        self.path.chmod(0o644)
        with self.assertRaises(ValueError): configure_server(self.path)
        self.path.chmod(0o600)
        link = self.root / 'link.json'; link.symlink_to(self.path)
        with self.assertRaises(ValueError): configure_server(link)
        import os
        os.link(self.path, self.root / 'hard.json')
        with self.assertRaises(ValueError): configure_server(self.path)

    def test_duplicate_fields_nonfinite_and_oversized_configs_are_rejected(self):
        for raw in ('{"schema":1,"enabled":false,"enabled":true}',
                    '{"schema":1,"enabled":NaN}', ' ' * 32_001):
            self.path.write_text(raw)
            with self.assertRaises(ValueError): configure_server(self.path)

    def test_bad_approved_identity_shapes_fail_before_archive_access(self):
        for ids in ([], ['old-a', 'old-a'], [{}], ['']):
            value = dict(self.permission, approved_cids=ids); self.write(self.manifest, value)
            with self.subTest(ids=ids), self.assertRaises(ValueError): self.sources()

    def test_actual_server_main_installs_configuration_before_binding_listener(self):
        import server
        events = []
        class HTTP:
            def __init__(self, *args): events.append('listener')
            def serve_forever(self): events.append('serve')
        class ReadyStore:
            def purge(self): events.append('purge')
        def store(): events.append('store'); return ReadyStore()
        with patch('research_server.configure_from_environment', side_effect=lambda: events.append('sources')), \
                patch.object(server, '_assistant_store', store), \
                patch.object(server, 'ThreadingHTTPServer', HTTP), \
                patch.object(server, '_load_answer_cache'), \
                patch.object(server, '_legacy_transport_allowed', return_value=False), \
                patch.object(server.claude_api, 'config', return_value={}), patch('builtins.print'):
            server.main()
        self.assertEqual(events, ['sources', 'store', 'purge', 'listener', 'serve'])

    def test_invalid_enabled_configuration_prevents_actual_server_listener_start(self):
        import server
        with patch('research_server.configure_from_environment', side_effect=ValueError('revoked')), \
                patch.object(server, 'ThreadingHTTPServer') as listener:
            with self.assertRaises(ValueError): server.main()
        listener.assert_not_called()

    def test_wrong_review_catalog_shape_stops_before_factory_installation(self):
        self.write(self.root / 'reviews.json', {'schema': 1, 'reviews': []})
        self.repin_publication()
        with self.assertRaisesRegex(ValueError, 'formats'): configure_server(self.path)
        self.assertIsNone(research_runtime._factory)

    def test_wrong_lesson_catalog_shape_stops_before_factory_installation(self):
        self.write(self.root / 'lessons.json', {'schema': 1, 'records': {}})
        self.repin_publication()
        with self.assertRaisesRegex(ValueError, 'formats'): configure_server(self.path)
        self.assertIsNone(research_runtime._factory)

    def repin_publication(self):
        pointer = json.loads(self.pointer.read_text())
        for key in ('archive', 'lessons', 'reviews'):
            pointer[key + '_sha256'] = self.sha(self.root / pointer[key])
        self.write(self.pointer, pointer)
        self.permission['pointer_sha256'] = self.sha(self.pointer)
        self.write(self.manifest, self.permission)
        self.config['sources_sha256'] = self.sha(self.manifest)
        self.write(self.path, self.config)


if __name__ == '__main__':
    unittest.main()
