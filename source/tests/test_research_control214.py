import copy
import json
import os
from pathlib import Path
import socket
import struct
import tempfile
import unittest
from unittest.mock import patch

from research_control import Controller,Server,peer_uid
from research_jobs import JobError
import test_research_bridge203 as fixtures


class Admission214Tests(unittest.TestCase):
    def provider(self,payload,timeout):
        return fixtures.ResearchBridgeTests.provider(self,payload,timeout)

    def setUp(self):
        fixtures.ResearchBridgeTests.setUp(self)
        now=int(self.service.jobs.clock());self.identity.update(iat=now,exp=now+40)
        self.body['browser_session']='device:private-test'
        self.controller=Controller(lambda:[self.service],clock=self.service.jobs.clock)

    def call(self,action,**extra):return self.app.handle(dict(self.body,action=action,**extra))

    def pending(self):
        result,code=self.call('research_start');self.assertEqual(code,200,result)
        self.assertTrue(result['pending_admission']);self.assertFalse(result['needs_operator']);self.assertEqual(self.requests,[])
        values=self.controller.handle(dict(op='pending'))['pending'];self.assertEqual(len(values),1)
        return values[0]

    def arm(self,value,calls=2,seconds=600):
        return self.controller.handle(dict(op='arm',bindings=[value['binding_hash']],max_calls=calls,seconds=seconds))

    def test_verified_observer_waits_without_paid_calls_or_persisting_proof(self):
        value=self.pending();self.assertEqual(value['operator'],self.identity['operator_id'])
        serialized=json.dumps(self.controller.handle(dict(op='pending')))
        self.assertNotIn(self.body['identity_proof'],serialized);self.assertNotIn('ctx',serialized)
        self.assertEqual(list(self.service.jobs.directory.glob('*.request.json')),[])
        self.assertEqual(self.controller.remaining,0)

    def test_exact_root_arm_admit_status_starts_same_job_once(self):
        value=self.pending();self.arm(value)
        receipt=self.controller.handle(dict(op='admit',binding_hash=value['binding_hash'],max_calls=2,seconds=300))
        self.assertEqual(receipt['calls_remaining'],0);self.assertFalse(receipt['can_send_or_create'])
        result,code=self.call('research_status');self.assertEqual(code,200,result);job=result['research_job_id'];self.assertTrue(job)
        jobs=self.controller.handle(dict(op='jobs',owner='owner'))['jobs'];self.assertEqual(jobs[0]['job'],job)
        self.assertNotIn('ctx',jobs[0]);self.assertNotIn('identity_proof',json.dumps(jobs))
        again,code=self.call('research_start');self.assertEqual(again['research_job_id'],job)
        self.assertEqual(len(self.work),1);self.work.pop(0)()
        status=self.service.jobs.status('owner',job);self.assertEqual(status['state'],'awaiting_root')
        self.controller.handle(dict(op='decide',owner='owner',job=job,result_sha256=status['result_sha256'],accepted=True,reviewer='local-test-root'))
        final,code=self.call('research_finalize',research_job_id=job)
        self.assertEqual(code,200,final);self.assertTrue(final['draft_id']);self.assertEqual(len(self.requests),2)

    def test_unarmed_wrong_binding_and_excess_budget_do_not_admit(self):
        value=self.pending()
        with self.assertRaises(ValueError):self.controller.handle(dict(op='admit',binding_hash=value['binding_hash'],max_calls=2,seconds=300))
        self.arm(value)
        for change in (dict(binding_hash='f'*64),dict(max_calls=3),dict(seconds=601)):
            command=dict(op='admit',binding_hash=value['binding_hash'],max_calls=2,seconds=300);command.update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):self.controller.handle(command)
        self.assertEqual(self.requests,[])

    def test_pending_source_change_before_admission_fails_without_spending_budget(self):
        value=self.pending();self.arm(value)
        self.ctx['messages'].append(dict(id='new',direction='in',sender_type='client',body='Другой запрос.'))
        # The controller holds the previously verified immutable snapshot;
        # a fresh browser observation fences that old generation first.
        self.app.handle(dict(owner='owner',action='observe',ctx=self.ctx))
        with self.assertRaises(ValueError):self.controller.handle(dict(op='admit',binding_hash=value['binding_hash'],max_calls=2,seconds=300))
        self.assertEqual(self.controller.remaining,2);self.assertEqual(self.requests,[])

    def test_expired_or_changed_actor_cannot_mint_a_grant(self):
        value=self.pending();self.arm(value);self.identity['operator_id']='another'
        with self.assertRaises(ValueError):self.controller.handle(dict(op='admit',binding_hash=value['binding_hash'],max_calls=2,seconds=300))
        self.assertEqual(self.requests,[])

    def test_pending_cancel_revokes_grant_before_any_job_or_provider(self):
        value=self.pending();self.arm(value)
        self.controller.handle(dict(op='admit',binding_hash=value['binding_hash'],max_calls=2,seconds=300))
        result,code=self.call('research_cancel');self.assertEqual(code,200,result)
        self.assertEqual(result['research_state'],'cancelled');self.assertEqual(self.requests,[])
        out,code=self.call('research_start');self.assertEqual(code,403);self.assertFalse(out.get('pending_research',False))

    def test_denial_or_root_stop_closes_campaign_and_old_grants(self):
        value=self.pending();self.arm(value,calls=4)
        self.controller.handle(dict(op='admit',binding_hash=value['binding_hash'],max_calls=2,seconds=300))
        out,_=self.call('research_start');self.work.pop(0)();job=out['research_job_id'];status=self.service.jobs.status('owner',job)
        self.controller.handle(dict(op='decide',owner='owner',job=job,result_sha256=status['result_sha256'],accepted=False,reviewer='local-test-root'))
        self.assertEqual(self.controller.remaining,0);self.assertFalse(self.controller.allowed)
        self.controller.handle(dict(op='stop',owner='owner'));self.assertEqual(self.controller.deadline,0)

    def test_browser_action_fields_cannot_arm_or_approve(self):
        for op in ('arm','admit','decide','send','create_crm','auto'):
            with self.subTest(op=op),self.assertRaises(ValueError):self.controller.handle(dict(op=op,api_key='fake-secret',accepted=True))
        self.assertEqual(self.requests,[])

    def test_missing_or_expired_fresh_proof_cannot_enter_pending_mailbox(self):
        for change in (dict(exp=0),dict(iat=0),dict(exp=int(self.service.jobs.clock())+1000)):
            old=copy.deepcopy(self.identity);self.identity.update(change)
            out,code=self.call('research_start');self.assertEqual(code,403);self.assertFalse(out.get('pending_admission',False))
            self.identity.clear();self.identity.update(old)
        self.assertEqual(self.controller.handle(dict(op='pending'))['pending'],[])

    def test_first_hard_provider_error_stops_unspent_campaign_without_retry(self):
        value=self.pending();self.arm(value,calls=4)
        self.controller.handle(dict(op='admit',binding_hash=value['binding_hash'],max_calls=2,seconds=300))
        def failed(*args):self.requests.append('attempt');raise TimeoutError('private error suppressed')
        self.service.request=failed
        out,code=self.call('research_start');self.assertEqual(code,200)
        self.work.pop(0)()
        self.assertEqual(self.requests,['attempt']);status=self.service.jobs.status('owner',out['research_job_id'])
        self.assertEqual(status['state'],'rejected');self.assertEqual(status['unresolved_provider_steps'],1)
        self.assertEqual(self.service.ledger.summary()['unknown_calls'],1)
        self.assertEqual(self.controller.handle(dict(op='pending'))['calls_remaining'],0)
        self.assertFalse(self.controller.allowed)


class Socket214Tests(unittest.TestCase):
    def test_private_parent_and_symlinks_rejected_before_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent=Path(tmp).resolve()/'public';parent.mkdir(mode=0o755)
            parent.chmod(0o755)  # Keep this deliberately public even under a private worker umask.
            with self.assertRaisesRegex(ValueError,'Private controller directory required'),patch('research_control.socket.socket',side_effect=AssertionError('No bind')):
                Server(parent/'control.sock',Controller(lambda:[])).start()
            link=Path(tmp)/'link';link.symlink_to(parent,target_is_directory=True)
            with self.assertRaises(ValueError):Server(link/'control.sock',Controller(lambda:[])).start()

    def test_linux_peer_uid_comes_from_kernel_struct_not_request(self):
        class Peer:
            def getsockopt(self,*args):return struct.pack('3i',123,987,456)
        with patch.object(socket,'SO_PEERCRED',17,create=True):self.assertEqual(peer_uid(Peer()),987)

    def exchange(self,raw,uid=None):
        control=Controller(lambda:[]);server=Server('/not-started/control.sock',control)
        class Connection:
            def __enter__(s):return s
            def __exit__(s,*args):pass
            def settimeout(s,*args):pass
            def recv(s,size):
                result=s.raw[:size];s.raw=s.raw[size:];return result
            def sendall(s,result):s.result=result
        c=Connection();c.raw=raw
        class Listener:
            def accept(s):server.stop_event.set();return c,None
        server.socket=Listener()
        with patch('research_control.peer_uid',return_value=os.getuid() if uid is None else uid):server._serve()
        return json.loads(c.result)

    def test_foreign_uid_duplicate_json_oversized_and_action_frames_never_authorize(self):
        for raw in (b'{"op":"arm","op":"pending"}\n',b'x'*32769+b'\n',b'{"op":"auto"}\n',b'{"op":"pending"}\n{"op":"arm"}\n'):
            with self.subTest(raw=raw[:40]):self.assertFalse(self.exchange(raw)['ok'])
        self.assertFalse(self.exchange(b'{"op":"pending"}\n',os.getuid()+1)['ok'])

    def test_valid_private_pending_frame_has_no_action_authority(self):
        result=self.exchange(b'{"op":"pending"}\n');self.assertTrue(result['ok']);self.assertFalse(result['can_send_or_create'])


if __name__=='__main__':unittest.main()
