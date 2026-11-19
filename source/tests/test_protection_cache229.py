import unittest
from unittest.mock import patch

import source_protection as protection_module
import source_protocol as protocol
import test_native_context212 as fixture
from research_index import SourceExcluded


class ProtectionCache229Tests(unittest.TestCase):
    def setUp(self):
        fixture.ProtectionTests.setUp(self)

    def test_identical_bytes_are_parsed_once_but_every_header_reopens_private_file(self):
        with patch.object(protection_module,'private_file',wraps=protection_module.private_file) as reads, \
                patch.object(protection_module,'strict_json',wraps=protection_module.strict_json) as parses:
            for _ in range(20):
                self.assertTrue(self.protection.header(self.header))
            self.assertGreaterEqual(reads.call_count,40)
            self.assertEqual(parses.call_count,0)

    def test_cached_snapshot_cannot_mutate_protected_identities(self):
        snapshot=self.protection._read()
        with self.assertRaises(TypeError):snapshot['protected_cids']=()
        with self.assertRaises((TypeError,AttributeError)):snapshot['protected_cids'].append('new')
        with self.assertRaises((TypeError,AttributeError)):snapshot['protected_identity_keys'].clear()
        with self.assertRaises((TypeError,AttributeError)):snapshot['protected_media_refs'].clear()
        with self.assertRaises(SourceExcluded):self.protection.header(dict(self.header,identity_keys=['a'*64]))

    def test_warm_cache_does_not_accept_modified_or_missing_current_bytes(self):
        original=self.path.read_bytes()
        self.path.write_bytes(protocol.encode(dict(self.value,protected_cids=[])))
        with self.assertRaises(protocol.SourceError):self.protection.header(self.header)
        self.path.unlink()
        with self.assertRaises(OSError):self.protection.header(self.header)
        self.path.write_bytes(original);self.path.chmod(0o600)
        self.assertTrue(self.protection.header(self.header))

    def test_changed_permissions_or_symlink_are_checked_even_with_a_warm_cache(self):
        self.path.chmod(0o644)
        with self.assertRaises(ValueError):self.protection.header(self.header)
        self.path.chmod(0o600)
        alias=self.path.with_name('alias.json');alias.symlink_to(self.path)
        self.protection.path=alias
        with self.assertRaises(ValueError):self.protection.header(self.header)

    def test_new_pinned_digest_is_fully_validated_and_does_not_reuse_old_snapshot(self):
        value=dict(self.value,protected_cids=self.value['protected_cids']+['development'])
        self.path.write_bytes(protocol.encode(value));self.protection.expected=protocol.sha(self.path.read_bytes())
        with patch.object(protection_module,'strict_json',wraps=protection_module.strict_json) as parses:
            with self.assertRaises(SourceExcluded):self.protection.header(self.header)
            self.assertEqual(parses.call_count,1)

    def test_different_digest_cannot_bypass_complete_holdout_or_duplicate_validation(self):
        for bad in (dict(self.value,protected_cids=['only-one']),
                    dict(self.value,protected_identity_keys=['a'*64,'a'*64])):
            self.path.write_bytes(protocol.encode(bad));self.protection.expected=protocol.sha(self.path.read_bytes())
            with self.assertRaises(protocol.SourceError):self.protection.header(self.header)
        raw=self.path.read_bytes()[:-1]+b',"schema":1}'
        self.path.write_bytes(raw);self.protection.expected=protocol.sha(raw)
        with self.assertRaises(ValueError):self.protection.header(self.header)

    def test_metadata_preflight_still_sends_exact_ordered_lists_and_rechecks_revocation(self):
        calls=[]
        def metadata(cids,remaining):
            self.assertIsInstance(cids,list)
            calls.extend(cids)
            if len(calls)==1000:self.path.write_bytes(protocol.encode(dict(self.value,media_reference_scan_complete=False)))
            return [dict(cid=cid,identity_keys=['a'*64],media_hashes=['b'*64])for cid in cids]
        with self.assertRaises(protocol.SourceError):self.protection.verify_current_metadata(metadata)
        self.assertEqual(calls,self.value['protected_cids'])

    def test_cache_is_not_shared_between_protection_instances(self):
        other=self.path.with_name('other.json')
        other.write_bytes(protocol.encode(dict(self.value,protected_identity_keys=['d'*64])));other.chmod(0o600)
        fresh=protection_module.SourceProtection(other,protocol.sha(other.read_bytes()))
        self.assertTrue(self.protection.header(self.header))
        with self.assertRaises(SourceExcluded):fresh.header(self.header)


if __name__=='__main__':unittest.main()
