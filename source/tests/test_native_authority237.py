import copy
import unittest
import uuid

from native_authority import NativeAuthority
from native_sources import NativeSources
import source_protocol as protocol


class NativeRunWireTests(unittest.TestCase):
    def setUp(self):
        self.key = b'public-native-run-test-key-not-a-real-credential'
        self.now = 1793500000
        self.actor = dict(principal_id=str(uuid.uuid4()), operator_id=str(uuid.uuid4()))
        self.run = str(uuid.uuid4())
        self.live = dict(self.actor, run_id=self.run, generation=3, mode='auto',
                         versions=['policy', 'runtime', 'map', 'memory'])
        self.output = dict(authority=self.live)
        self.calls = []
        self.status = 200
        self.signed = True
        self.client = NativeSources('https://chat.partner-lead-centre.ru', key=lambda: self.key,
            header_guard=self.no_source, cid_guard=self.no_source,
            connection_factory=self.factory, clock=lambda: self.now)

    def no_source(self, value):
        raise AssertionError('Run authority must not fetch customer source identities/bodies')

    def factory(self, host, port, **options):
        case = self
        self.assertTrue(options['context'].check_hostname)
        self.assertEqual((host, port), ('chat.partner-lead-centre.ru', 443))
        class Connection:
            def request(self, method, path, *, body, headers):
                value, case.nonce = protocol.verify(case.key, body,
                    {k.lower(): v for k, v in headers.items()}, now=case.now)
                case.calls.append(value)
            def getresponse(self):
                self.status = case.status
                self.raw = protocol.encode(dict(ok=True, data=case.output))
                self.position = 0
                return self
            def getheader(self, name, default=None):
                if name == 'Content-Type':return 'application/json'
                if name == 'X-LB-Read-Signature':
                    return protocol.response_signature(case.key, self.raw, case.nonce) if case.signed else 'bad'
                return default
            def read(self, size):
                result = self.raw[self.position:self.position+size]
                self.position += len(result)
                return result
            def close(self):pass
        return Connection()

    def test_native_run_has_exact_authenticated_metadata_and_no_source_access(self):
        self.assertEqual(self.client.run_authority(self.run, 3, self.actor), self.live)
        self.assertEqual(self.calls, [dict(v=1, operation='run_authority',
            arguments=dict(run_id=self.run, generation=3), actor=self.actor)])
        self.assertNotIn(self.key.decode(), protocol.encode(self.calls).decode())

    def test_bad_identifiers_boolean_generation_or_browser_credentials_have_no_network(self):
        for run, generation, actor in ((self.run, True, self.actor), ('other', 3, self.actor),
                (self.run, 0, self.actor), (self.run, 2**63, self.actor),
                (self.run, 3, dict(self.actor, jwt='not-authority')),
                (self.run, 3, dict(self.actor, operator_id='bad'))):
            with self.subTest(run=run, generation=generation), self.assertRaises(protocol.SourceError):
                self.client.run_authority(run, generation, actor)
        self.assertEqual(self.calls, [])

    def test_other_actor_run_generation_mode_or_incomplete_versions_stop(self):
        for field, value in (('principal_id', str(uuid.uuid4())), ('operator_id', str(uuid.uuid4())),
                ('run_id', str(uuid.uuid4())), ('generation', True), ('generation', 4),
                ('mode', 'browser'), ('versions', ['p']), ('versions', ['p', 'r', '', 'm']),
                ('versions', ['p', 'r', 'm', False])):
            self.output = dict(authority=dict(self.live, **{field: value}))
            with self.subTest(field=field), self.assertRaises(protocol.SourceError):
                self.client.run_authority(self.run, 3, self.actor)
        self.output = dict(authority=dict(self.live, reply='not-a-customer-response'))
        with self.assertRaises(protocol.SourceError):self.client.run_authority(self.run, 3, self.actor)

    def test_http_error_or_signature_failure_never_retries(self):
        for status, signed in ((302, True), (401, True), (500, True), (200, False)):
            self.calls.clear(); self.status = status; self.signed = signed
            with self.assertRaises(protocol.SourceError):self.client.run_authority(self.run, 3, self.actor)
            self.assertEqual(len(self.calls), 1)


class NativeAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.principal, self.operator, self.run = (str(uuid.uuid4()) for _ in range(3))
        self.versions = ['policy', 'runtime', 'map', 'memory']
        self.output = dict(principal_id=self.principal, operator_id=self.operator,
                           run_id=self.run, generation=1, mode='auto', versions=self.versions)
        self.reads = 0
        case = self
        class Client:
            def run_authority(self, run_id, generation, actor):
                case.reads += 1
                if case.output is None:raise protocol.SourceError('stopped')
                return copy.deepcopy(case.output)
        self.authority = NativeAuthority(Client(), owner='owner', principal_id=self.principal,
                                         current_versions=lambda: self.versions)
        self.body = dict(owner='owner', native_run=dict(run_id=self.run, generation=1, operator_id=self.operator))

    def test_identity_and_binding_recheck_native_run_without_browser_lease(self):
        identity = self.authority.identity(self.body)
        self.assertEqual(identity['execution_origin'], 'leadchat_native_run')
        self.assertEqual(identity['operator_id'], self.operator)
        binding = self.authority.auto_binding(self.body)
        self.assertEqual(len(binding), 64)
        self.assertEqual(self.reads, 2)
        self.output = None
        with self.assertRaises(protocol.SourceError):self.authority.identity(self.body)
        self.assertEqual(self.reads, 3)

    def test_browser_proof_wrong_owner_and_missing_launch_are_not_native_authority(self):
        for body in (dict(self.body, identity_proof='not-native'), dict(self.body, browser_session='browser'),
                     dict(self.body, owner='other'), dict(owner='owner'),
                     dict(self.body, native_run=None), dict(self.body, native_run=[])):
            with self.assertRaises(protocol.SourceError):self.authority.identity(body)
        self.assertEqual(self.reads, 0)

    def test_changed_versions_or_rehearsal_cannot_authorize_auto(self):
        self.versions = ['changed', 'runtime', 'map', 'memory']
        with self.assertRaises(protocol.SourceError):self.authority.identity(self.body)
        self.versions = list(self.output['versions'])
        self.output['mode'] = 'rehearsal'
        self.assertEqual(self.authority.identity(self.body)['mode'], 'rehearsal')
        with self.assertRaises(protocol.SourceError):self.authority.auto_binding(self.body)


if __name__ == '__main__':unittest.main()
