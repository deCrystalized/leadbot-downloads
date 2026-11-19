"""Unscoped legacy batch commands cannot read bodies or write audit outputs."""
import runpy
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ('analyze_all_dialogues', 'audit_complete_dialogues',
         'build_experienced_dialogues', 'index_crm_evidence')


class LegacySourceEntrypoints254Tests(unittest.TestCase):
    def no_source_io(self, stack):
        attempted = []

        def denied(*args, **kwargs):
            attempted.append(True)
            raise AssertionError('Legacy file access attempted before trusted source admission')

        for method in ('read_text', 'read_bytes', 'open', 'mkdir', 'write_text', 'write_bytes'):
            stack.enter_context(patch.object(Path, method, denied))
        return attempted

    def test_imports_are_inert_even_without_any_source_permission(self):
        for tool in TOOLS:
            with self.subTest(tool=tool), ExitStack() as stack:
                attempted = self.no_source_io(stack)
                runpy.run_path(str(ROOT / 'tools' / (tool + '.py')), run_name='legacy_import_only')
                self.assertEqual(attempted, [])

    def test_raw_batch_entrypoints_fail_before_file_access(self):
        for tool in TOOLS:
            with self.subTest(tool=tool):
                with ExitStack() as stack:
                    attempted = self.no_source_io(stack)
                    # Keep the same IO barrier around BOTH imports. A legacy
                    # module may still execute at import time before repair.
                    module = runpy.run_path(str(ROOT / 'tools' / (tool + '.py')),
                                            run_name='legacy_import_only')
                    stack.enter_context(patch.object(sys, 'argv', [tool,
                        '--source', 'test-artifacts/never-read.json',
                        '--out', 'test-artifacts/never-created']))
                    with self.assertRaisesRegex(RuntimeError, 'retired'):
                        if tool == 'build_experienced_dialogues':
                            module['build'](ROOT / 'test-artifacts/never-created')
                        else:
                            module['main']()
                    self.assertEqual(attempted, [])


if __name__ == '__main__':
    unittest.main()
