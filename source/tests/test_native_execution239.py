"""Actual private command ingress +shared research; synthetic sources/model."""
import copy
import hashlib
import hmac
import io
import sqlite3
import threading
import unittest
import uuid
from email.message import Message
from unittest.mock import patch

import native_execution as execution
import native_execution_protocol as wire
import source_protocol
import server
import test_native_research238 as fixture


class NativeExecution239Tests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.NativeResearch238Tests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.ctx = self.f.sim.add(str(uuid.uuid4()), 'Нужно повесить полку.')
        self.f.body['ctx'] = self.ctx
        prepared = self.f.sim.service.prepare_source(self.f.sim.app, self.f.body)
        self.source = prepared['ctx']['sourceSnapshotSha256']
        self.key = b'only-synthetic-native-execution-key-never-production'
        self.clock = lambda: 1793517000
        self.queue, self.factory_calls = [], []
        def factory(principal):
            self.factory_calls.append(principal)
            return self.f.sim.app
        self.factory = factory
        self.directory = self.f.sim.root/'native-commands'
        self.gateway = self.gateway_instance()

    def gateway_instance(self):
        return execution.Gateway(self.directory, key=lambda: self.key, app_factory=self.factory,
                                 schedule=self.queue.append, clock=self.clock)

    def command(self, op='prepare', args=None, **changes):
        value = dict(v=1, command_id=str(uuid.uuid4()), operation=op,
            principal_id=fixture.fixture.PRINCIPAL, operator_id=fixture.fixture.ACTOR,
            run_id=self.f.run_id, generation=self.f.generation,
            arguments=args if args is not None else dict(cid=self.ctx['convId'], source_sha256=self.source, purpose='reply'))
        value.update(changes)
        return value

    def send(self, command, gateway=None):
        raw, headers = wire.request(self.key, command, now=self.clock())
        status, result, signed = (gateway or self.gateway).handle(raw, {k.lower(): v for k,v in headers.items()})
        if signed:
            value = wire.verify_response(self.key, result, headers['X-LB-Exec-Nonce'], status, signed['X-LB-Exec-Signature'])
        else:
            value = wire.decode(result, wire.MAX_RESPONSE)
        return value, status

    def commands(self):
        while self.queue:
            self.queue.pop(0)()

    def stored(self, command):
        with self.gateway.connect() as db:
            row = db.execute('SELECT * FROM commands WHERE id=?', (command['command_id'],)).fetchone()
        self.assertEqual(row['state'], 'done', dict(row))
        return wire.decode(row['response'], wire.MAX_RESPONSE)['data']

    def prepare(self):
        command = self.command()
        result, status = self.send(command)
        self.assertEqual(status, 202, result)
        self.assertEqual(self.factory_calls, [])
        self.assertEqual(self.f.sim.requests, [])
        self.commands()
        result = self.stored(command)
        self.assertTrue(result.get('research_job_id'), result)
        return command, result

    def args(self, result):
        return dict(cid=self.ctx['convId'], source_sha256=self.source,
            **{k: result[k] for k in ('request_id', 'revision', 'research_job_id')})

    def test_full_native_wire_proposal_separate_review_and_finalize_no_browser(self):
        command, prepared = self.prepare()
        self.f.workers()
        final = self.command('finalize', self.args(prepared))
        self.assertEqual(self.send(final)[1], 202)
        self.commands()
        draft = self.stored(final)
        self.assertTrue(draft.get('draft_id'), draft)
        self.assertEqual(draft['validation'], [])
        self.assertEqual(len(self.f.sim.requests), 2)
        self.assertEqual(self.f.sim.service.observers._entries, {})
        replay, status = self.send(command)
        self.assertEqual(status, 200)
        self.assertEqual(replay['command_state'], 'done')
        self.assertTrue(replay['requires_current_validation'])
        self.assertFalse(replay['can_send_or_create'])
        self.assertEqual(len(self.f.sim.requests), 2)

    def test_lost_http_observation_and_restart_do_not_dispatch_again(self):
        command, prepared = self.prepare()
        self.f.workers()
        before = self.f.sim.service.jobs.status(fixture.fixture.OWNER, prepared['research_job_id'])
        recovered = self.gateway_instance()
        result, code = self.send(command, recovered)
        self.assertEqual(code, 200)
        self.assertEqual(result['original_result']['data']['research_job_id'], before['job_id'])
        self.assertEqual(self.queue, [])
        self.assertEqual(len(self.f.sim.requests), 2)
        after = self.f.sim.service.jobs.status(fixture.fixture.OWNER, before['job_id'])
        self.assertEqual(after['deadline'], before['deadline'])
        self.assertEqual(after['result_sha256'], before['result_sha256'])

    def test_crash_after_reservation_is_unknown_not_reconstructed(self):
        command = self.command()
        self.assertEqual(self.send(command)[1], 202)
        self.queue.clear()  # Process disappeared before dispatch: no inferred no-call retry.
        recovered = self.gateway_instance()
        result, code = self.send(command, recovered)
        self.assertEqual(code, 200)
        self.assertEqual(result['command_state'], 'dispatching')
        self.assertNotIn('original_result', result)
        self.assertEqual(self.queue, [])
        self.assertEqual(self.factory_calls, [])
        self.assertEqual(self.f.sim.requests, [])

    def test_changed_id_payload_is_conflict_not_a_second_dispatch(self):
        command, result = self.prepare()
        before = len(self.factory_calls)
        changed = copy.deepcopy(command)
        changed['arguments']['purpose'] = 'intake_form_v1'
        out, code = self.send(changed)
        self.assertEqual(code, 409, out)
        self.assertEqual(len(self.factory_calls), before)
        self.assertEqual(self.queue, [])

    def test_source_mismatch_stops_before_any_provider_step_and_never_retries(self):
        command = self.command()
        command['arguments']['source_sha256'] = 'a'*64
        self.assertEqual(self.send(command)[1], 202)
        self.commands()
        recovered, status = self.send(command)
        self.assertEqual(status, 200)
        self.assertEqual(recovered['command_state'], 'uncertain')
        self.assertEqual(self.f.sim.requests, [])
        self.assertEqual(self.queue, [])

    def test_role_revoke_hides_archived_draft_and_does_not_resume(self):
        command, result = self.prepare()
        self.f.workers()
        self.f.permission = False
        recovered, code = self.send(command)
        self.assertEqual(code, 200)
        self.assertNotIn('original_result', recovered)
        self.assertTrue(recovered['source_or_run_not_current'])
        self.assertEqual(len(self.f.sim.requests), 2)

    def test_private_cancel_releases_same_job_after_run_stopped(self):
        command, result = self.prepare()
        self.f.live = False
        cancelled, status = self.send(self.command('cancel', self.args(result)))
        self.assertEqual(status, 200, cancelled)
        self.assertEqual(cancelled['data']['research_state'], 'stopped')
        self.f.workers()
        self.assertEqual(self.f.sim.requests, [])
        with self.f.sim.service.jobs.connect() as db:
            row = db.execute('SELECT deadline FROM grants WHERE job=?', (result['research_job_id'],)).fetchone()
        self.assertLessEqual(row['deadline'], self.f.sim.service.jobs.clock())

    def test_cancel_cannot_cross_launch_or_forge_an_original_job_receipt(self):
        command, result = self.prepare()
        wrong = self.command('cancel', self.args(result), generation=2)
        out, status = self.send(wrong)
        self.assertEqual(status, 409, out)
        self.assertEqual(out['command_state'], 'uncertain')
        state = self.f.sim.service.jobs.status(fixture.fixture.OWNER, result['research_job_id'])
        self.assertEqual(state['state'], 'queued')
        self.assertEqual(self.f.sim.requests, [])

    def test_recover_uses_exact_original_actor_and_launch(self):
        command, result = self.prepare()
        out, status = self.send(self.command('recover', dict(command_id=command['command_id'])))
        self.assertEqual(status, 200, out)
        self.assertEqual(out['data']['original_result']['data']['research_job_id'], result['research_job_id'])
        wrong = self.command('recover', dict(command_id=command['command_id']), operator_id=str(uuid.uuid4()))
        self.assertEqual(self.send(wrong)[1], 409)
        self.assertEqual(self.f.sim.requests, [])

    def test_signature_replay_and_status_tampering_fail_closed(self):
        raw, headers = wire.request(self.key, self.command(), now=self.clock())
        lowered = {k.lower(): v for k,v in headers.items()}
        first = self.gateway.handle(raw, lowered)
        self.assertEqual(first[0], 202)
        second = self.gateway.handle(raw, lowered)
        self.assertEqual(second[0], 409)
        self.assertEqual(len(self.queue), 1)
        with self.assertRaises(ValueError):
            wire.verify_response(self.key, first[1], headers['X-LB-Exec-Nonce'], 200, first[2]['X-LB-Exec-Signature'])

    def test_bad_authentication_has_no_factory_journal_or_read_only_rpc_fallback(self):
        raw, headers = source_protocol.request(self.key, 'catalog', {}, now=self.clock())
        result = self.gateway.handle(raw, {k.lower(): v for k,v in headers.items()})
        self.assertEqual(result[0], 403)
        self.assertEqual(self.factory_calls, [])
        with self.gateway.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM commands').fetchone()[0], 0)

    def test_strict_json_schema_cannot_supply_source_text_keys_or_action_options(self):
        for change in [dict(api_key='fake'), dict(messages=[]), dict(max_calls=99), dict(auto=True)]:
            value = self.command()
            value['arguments'].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                wire.request(self.key, value, now=self.clock())
        for raw in [b'{"v":1,"v":1}', b'{"v":NaN}']:
            stamp, nonce = str(self.clock()), 'a'*32
            signature = hmac.new(self.key, wire._message(raw, stamp, nonce), hashlib.sha256).hexdigest()
            out = self.gateway.handle(raw, dict(zip(wire.AUTH_HEADERS, (stamp, nonce, signature))))
            self.assertEqual(out[0], 403)
        self.assertEqual(self.queue, [])

    def test_raw_journal_has_no_authentication_material_or_synthetic_credential(self):
        command, result = self.prepare()
        with self.gateway.connect() as db:
            row = db.execute('SELECT request,response FROM commands WHERE id=?', (command['command_id'],)).fetchone()
            nonces = list(db.execute('SELECT digest FROM nonces'))
        data = row['request']+row['response']
        self.assertNotIn(self.key, data)
        self.assertNotIn(b'X-LB', data)
        self.assertEqual(len(nonces), 1)
        self.assertRegex(nonces[0]['digest'], r'^[a-f0-9]{64}$')

    def test_slow_run_observation_holds_no_journal_write_lock(self):
        command, result = self.prepare()
        entered, release, done = threading.Event(), threading.Event(), threading.Event()
        original = self.gateway._app_body
        def held(value):
            entered.set()
            if not release.wait(5):
                raise AssertionError('Exact observation fixture not released')
            return original(value)
        self.gateway._app_body = held
        thread = threading.Thread(target=lambda: (self.send(command), done.set()))
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            with sqlite3.connect(self.gateway.path, timeout=.1) as db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('SELECT count(*) FROM commands')
            self.assertFalse(done.is_set())
        finally:
            release.set()
            thread.join(6)
        self.assertFalse(thread.is_alive())
        self.assertTrue(done.is_set())
        self.assertEqual(self.f.sim.requests, [])

    def test_capacity_does_not_block_read_only_recovery_or_cancellation(self):
        for _ in range(32):
            self.assertEqual(self.send(self.command())[1], 202)
        self.assertEqual(len(self.queue),32)
        rejected, status = self.send(self.command())
        self.assertEqual(status,409,rejected)
        with self.gateway.connect() as db:
            first=db.execute('SELECT id FROM commands ORDER BY rowid LIMIT 1').fetchone()[0]
        observed,status=self.send(self.command('recover',dict(command_id=first)))
        self.assertEqual(status,200,observed)
        self.assertEqual(observed['data']['command_state'],'dispatching')
        self.assertEqual(len(self.queue),32)
        self.assertEqual(self.factory_calls,[])

    def test_credential_reflection_is_not_persisted_even_in_a_valid_identifier(self):
        self.key=fixture.fixture.PRINCIPAL.encode()
        result,status=self.send(self.command())
        self.assertEqual(status,403,result)
        with self.gateway.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM commands').fetchone()[0],0)
        self.assertEqual(self.queue,[])

    def test_real_background_command_outlives_http_observer_without_holding_response(self):
        entered, release = threading.Event(), threading.Event()
        def factory(principal):
            entered.set()
            if not release.wait(5):
                raise AssertionError('Actual private command thread not released')
            return self.f.sim.app
        gateway = execution.Gateway(self.f.sim.root/'actual-thread-commands', key=lambda:self.key,
            app_factory=factory, clock=self.clock)
        command = self.command()
        try:
            out, status = self.send(command,gateway)
            self.assertEqual(status,202,out)
            self.assertTrue(entered.wait(2))
            with gateway.connect() as db:
                state=db.execute('SELECT state FROM commands WHERE id=?',(command['command_id'],)).fetchone()[0]
            self.assertEqual(state,'dispatching')
            self.assertEqual(self.f.sim.requests,[])
        finally:
            release.set()
            gateway.pool.shutdown(wait=True)
        with gateway.connect() as db:
            row=db.execute('SELECT state,response FROM commands WHERE id=?',(command['command_id'],)).fetchone()
        self.assertEqual(row['state'],'done')
        self.assertTrue(wire.decode(row['response'],wire.MAX_RESPONSE)['data']['research_job_id'])
        self.assertEqual(self.f.sim.requests,[])

    def test_crash_after_core_start_recovers_same_job_without_recreating_a_command(self):
        command=self.command()
        original=self.gateway._dispatch
        def lost_response(value):
            out,status=original(value)
            self.partial=out
            raise OSError('Synthetic response journal failure after core job creation')
        self.gateway._dispatch=lost_response
        self.assertEqual(self.send(command)[1],202)
        self.commands()
        old=self.f.sim.service.jobs.status(fixture.fixture.OWNER,self.partial['research_job_id'])
        recreated=self.gateway_instance()
        recovered,status=self.send(command,recreated)
        self.assertEqual(status,200,recovered)
        self.assertEqual(recovered['original_job']['research_job_id'],old['job_id'])
        self.assertEqual(recovered['original_job']['request_id'],self.partial['request_id'])
        self.assertEqual(recovered['original_job']['revision'],self.partial['revision'])
        self.assertEqual(self.queue,[])
        self.assertEqual(self.f.sim.requests,[])
        self.assertEqual(self.f.sim.service.jobs.status(fixture.fixture.OWNER,old['job_id'])['deadline'],old['deadline'])
        self.f.live=False
        cancelled,status=self.send(self.command('cancel',self.args(self.partial)),recreated)
        self.assertEqual(status,200,cancelled)
        self.assertEqual(cancelled['data']['research_state'],'stopped')
        self.f.workers()
        self.assertEqual(self.f.sim.requests,[])

    def test_additive_command_migration_preserves_original_rows(self):
        directory=self.f.sim.root/'old-command-schema'
        directory.mkdir(mode=0o700)
        old=self.command()
        raw=wire.encode(old)
        with sqlite3.connect(directory/'commands.sqlite3') as db:
            db.execute('CREATE TABLE commands(id TEXT PRIMARY KEY,request_hash TEXT NOT NULL,request BLOB NOT NULL,'
                       'state TEXT NOT NULL,status INTEGER,response BLOB,at REAL NOT NULL)')
            db.execute("INSERT INTO commands VALUES(?,?,?,'dispatching',NULL,NULL,?)",
                       (old['command_id'],wire.sha(raw),raw,self.clock()))
        migrated=execution.Gateway(directory,key=lambda:self.key,app_factory=self.factory,
                                   schedule=self.queue.append,clock=self.clock)
        with migrated.connect() as db:
            row=db.execute('SELECT *FROM commands WHERE id=?',(old['command_id'],)).fetchone()
        self.assertEqual(row['request'],raw)
        self.assertEqual(row['request_hash'],wire.sha(raw))
        self.assertIsNone(row['progress'])
        recovered,status=self.send(old,migrated)
        self.assertEqual(status,200,recovered)
        self.assertEqual(recovered['command_state'],'dispatching')
        self.assertEqual(self.queue,[])

    def test_core_receipt_lost_before_gateway_job_id_commit_reads_exact_existing_job(self):
        command=self.command()
        handle=self.f.sim.app.handle
        def lost_receipt(body):
            out,status=handle(body)
            if body.get('action')=='research_start' and out.get('research_job_id'):
                self.created=out
                raise OSError('Synthetic lost return after durable core job creation')
            return out,status
        self.f.sim.app.handle=lost_receipt
        self.assertEqual(self.send(command)[1],202)
        self.commands()
        with self.gateway.connect() as db:
            row=db.execute('SELECT *FROM commands WHERE id=?',(command['command_id'],)).fetchone()
        progress=wire.decode(row['progress'],wire.MAX_REQUEST)
        self.assertNotIn('research_job_id',progress)
        original=self.f.sim.service.jobs.status(fixture.fixture.OWNER,self.created['research_job_id'])
        recovered,status=self.send(command,self.gateway_instance())
        self.assertEqual(status,200,recovered)
        self.assertEqual(recovered['original_job']['research_job_id'],original['job_id'])
        self.assertEqual(self.queue,[])
        self.assertEqual(self.f.sim.requests,[])
        self.f.live=False
        stopped,status=self.send(self.command('cancel',self.args(self.created)))
        self.assertEqual(status,200,stopped)
        self.assertEqual(stopped['data']['research_state'],'stopped')
        self.f.workers()
        self.assertEqual(self.f.sim.requests,[])


class NativeHTTPIngress239Tests(unittest.TestCase):
    def handler(self, raw=b'{}', lengths=None):
        h = server.Handler.__new__(server.Handler)
        h.path = wire.PATH
        h.headers = Message()
        h.headers['Content-Type'] = 'application/json'
        for key in wire.AUTH_HEADERS:
            h.headers[key] = 'synthetic-framing-only'
        for length in lengths if lengths is not None else [str(len(raw))]:
            h.headers['Content-Length'] = length
        h.rfile, h.wfile = io.BytesIO(raw), io.BytesIO()
        h.connection = type('Socket', (), dict(settimeout=lambda _, value: None))()
        h.codes, h.sent_headers = [], []
        h.send_response = h.codes.append
        h.send_header = lambda key, value: h.sent_headers.append((key, value))
        h.end_headers = lambda: None
        h._gate = lambda _: (_ for _ in ()).throw(AssertionError('No browser cookie/bearer authority'))
        return h

    def test_actual_handler_reads_exact_bytes_once_and_returns_signed_opaque_body(self):
        raw = b'{"v":1,"v":2}'
        h = self.handler(raw)
        with patch.object(execution, 'serve', return_value=(202,b'{"ok":true}',{'X-LB-Exec-Signature':'synthetic'})) as serve:
            h.do_POST()
        serve.assert_called_once_with(raw, {k:'synthetic-framing-only' for k in wire.AUTH_HEADERS})
        self.assertEqual(h.wfile.getvalue(), b'{"ok":true}')
        self.assertEqual(h.codes, [202])
        self.assertIn(('Cache-Control','no-store'), h.sent_headers)

    def test_bad_framing_or_browser_credentials_do_not_read_or_dispatch(self):
        for lengths, header in [(['1','2'],None), (['16001'],None), (['-1'],None),
                (['2'],('Cookie','lb_panel=synthetic')), (['2'],('Authorization','Bearer synthetic')),
                (['2'],('Transfer-Encoding','chunked')), (['2'],(wire.AUTH_HEADERS[0],'duplicate'))]:
            with self.subTest(lengths=lengths, header=header):
                h = self.handler(lengths=lengths)
                if header: h.headers[header[0]] = header[1]
                with patch.object(execution,'serve') as serve:
                    h.do_POST()
                serve.assert_not_called()
                self.assertEqual(h.rfile.tell(),0)
                self.assertIn(h.codes[0],(400,413))

    def test_default_runtime_is_disabled_and_does_not_read_a_key(self):
        with patch.object(execution,'_gateway',None):
            status, raw, headers = execution.serve(b'{}',{})
        self.assertEqual(status,503)
        self.assertEqual(headers,{})
        self.assertEqual(wire.decode(raw,wire.MAX_RESPONSE)['code'],'native_not_configured')


if __name__ == '__main__':
    unittest.main()
