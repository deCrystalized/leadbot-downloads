"""Private JSON-lines test fixture, never imported by the application.

Real policy, actor verifier, native context, jobs and validators; synthetic
sources/provider only. No sockets, real credential file or external writes.
"""
import base64
import copy
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'leadbot/brain'), str(Path(__file__).parent)]
import assistant_catalog
import assistant_policy as policy
from assistant_store import Store, digest
from extension_assistant import Assistant
from experienced_dialogues import Reader, create_index
from native_context import NativeContext
from research_control import Controller
from research_pipeline import Corpus
from research_workflow import ResearchService
import operator_identity
import source_protocol as protocol
import test_research_pipeline218 as fixtures
import test_workflow as crm_fixtures
from test_assistant import context, message

OWNER = 'isolated-auto231'
ACTOR = '11111111-1111-4111-8111-111111111111'
PRINCIPAL = '22222222-2222-4222-8222-222222222222'
SID = 'isolated:browser:231'
SECRET = 'synthetic-only-actor-secret-never-production'


class Simulation:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='leadbot-auto231-')
        self.root = Path(self.tmp.name).resolve()
        os.environ.update(LEADBOT_PERSONAL_OWNER_ID=OWNER, LEADBOT_ACTOR_PROOF_KEY=SECRET,
                          LEADBOT_ASSISTANT_WORDING='reviewed', LEADBOT_PERSONAL_AUTO_AVAILABLE='1',
                          LEADBOT_REQUIRE_ADMIN_AUTO='1')
        self.app = Assistant(Store(self.root / 'assistant.sqlite3'))
        self.sources = {}; self.contexts = {}; self.work = []; self.requests = []; self.events = []
        self.scripted_candidates = []
        self.provider_mode = 'normal'
        self.archive = self.root / 'archive.sqlite3'
        create_index(self.archive, [fixtures.ResearchTests().record('old-a')], approved_cids=['old-a'])
        case = self

        class Client:
            def header(self, cid, actor):
                source = case.sources[cid]
                case.events.append(dict(stage='native_header', cid=cid, actor=actor['operator_id']))
                return dict(cid=cid, source_sha256=protocol.sha(protocol.encode(source)),
                            client_group='synthetic-' + cid, phone_hashes=[], media_hashes=[])

            def history(self, header, actor):
                case.events.append(dict(stage='native_full_history', cid=header['cid']))
                return copy.deepcopy(case.sources[header['cid']])

        def corpus():
            return Corpus(Reader(self.archive), policy.registry()['sources'] + assistant_catalog.data()['owner_amendments'],
                          allowed_cids=['old-a'], guard=lambda ids: None, versions=lambda: 'synthetic-stable')

        self.service = ResearchService(self.root / 'research', shared_lock=self.root / 'provider.lock',
            corpus_factory=corpus, request=self.provider, schedule=self.work.append,
            native_context=NativeContext(Client(), self.root / 'native'), proposal_enabled=True)
        self.app.research = self.service
        self.controller = Controller(lambda: [self.service])

    def identity(self):
        body = dict(browser_session=SID, operator_id=ACTOR)
        challenge = operator_identity.challenge(self.app.store, OWNER, body, time.time())
        now = int(time.time())
        data = dict(v=1, aud='leadbot-browser-operator', principal_id=PRINCIPAL, operator_id=ACTOR,
            principal_name='Synthetic admin', operator_name='Synthetic actor', role='admin',
            nonce=challenge['nonce'], sid=SID, iat=now, exp=now + 40)
        encoded = base64.urlsafe_b64encode(protocol.encode(data)).rstrip(b'=')
        signature = base64.urlsafe_b64encode(hmac.new(SECRET.encode(), encoded, hashlib.sha256).digest()).rstrip(b'=')
        self.last_identity = dict(body, identity_proof=(encoded + b'.' + signature).decode())
        return self.last_identity

    def add(self, cid, text='Нужно повесить полку на бетонную стену.', **changes):
        ctx = context([message(text, mid=cid + '-client-1')], convId=cid, dir='mnc', dirBasis='account',
            accountTitle='Георгий МНЧ', city='Чита', itemTitle='Мастер на час', assigneeId='',
            assignmentKnown=True, conversationStatus='in_progress', botActive=False,
            hasTransfer=False, channelAssigned=True, historyComplete=True, **changes)
        self.contexts[cid] = ctx
        self.sync(cid)
        return ctx

    def sync(self, cid):
        ctx = self.contexts[cid]
        self.sources[cid] = dict(cid=cid, messages=copy.deepcopy(ctx['messages']), metadata=dict(
            status=ctx['conversationStatus'], crm_request_id=ctx.get('crmRequestId'), assignee_id=ctx['assigneeId'],
            claimed_by_id=ctx['assigneeId'], bot_active=False, transfer_to_id=None, channel='avito',
            account_title=ctx['accountTitle'], partner='7', origin='С1', client_name=ctx.get('clientName', ''),
            item=dict(title=ctx['itemTitle'], city_name='Чита', city_tz='Asia/Chita')))

    def call(self, body):
        # Models/browser cannot call this fixture's controller API. This is a
        # separate private test-driver command, outside app.handle/Node bridge.
        body = dict(body, owner=OWNER)
        result, code = self.app.handle(body)
        self.events.append(dict(stage='assistant', action=body['action'], cid=body.get('ctx', {}).get('convId'),
            code=code, result_code=result.get('code'), step=result.get('step'), reason=result.get('reason'),
            research_state=result.get('research_state')))
        return dict(status=code, body=result)

    def provider(self, payload, timeout):
        try:
            return self._provider(payload, timeout)
        except Exception as error:
            self.events.append(dict(stage='synthetic_provider_error', error=type(error).__name__, detail=str(error)))
            raise

    def _provider(self, payload, timeout):
        self.requests.append(payload)
        if self.provider_mode == 'transport':
            raise OSError('Synthetic transport failure, no external request')
        if self.provider_mode == 'invalid_json':
            return b'{invalid original response'
        role = json.loads(payload['instructions'])['role']
        if self.provider_mode=='review_transport' and role=='review':
            raise OSError('Synthetic review transport failure')
        dynamic = json.loads(payload['input'][-1]['content'][0]['text'])
        current = dynamic['current']
        if payload['text']['format']['schema']['properties'].get('kind',{}).get('enum')==['intake_form']:
            row=current['messages'][0]
            out=getattr(self,'form_candidate',dict(kind='intake_form',
                client_goal='Клиент просит разобраться с не включающимся компьютером.',
                latest_client_meaning='Клиент предоставил сведения для обращения.',note='Причина неисправности не установлена.',
                summary='Компьютер Dell Optiplex9020 не включается.',unknowns=['Причина неисправности'],needs_operator=False,
                works=[dict(subject='Компьютер Dell Optiplex9020',action='Разобраться с отсутствием включения',quantity='',status='requested',
                    evidence=[dict(message_id=row['id'],quote='Компьютер Dell Optiplex9020 не включается')])]))
            return protocol.encode(dict(id='form-mock-'+str(len(self.requests)),model='gpt-6.1-sol',status='completed',
                service_tier='default',usage=None,output=[dict(type='message',role='assistant',status='completed',
                    content=[dict(type='output_text',text=json.dumps(out,ensure_ascii=False))])]))
        if role=='review' and current['candidate_contract']['task'].get('purpose')=='intake_form_v1':
            candidate=getattr(self,'form_candidate',{'works':[{}]})
            rejected=self.provider_mode=='review_rejected'
            out=dict(kind='review',approved=not rejected,
                violations=['Описание не сохраняет заявленное клиентом условие работы'] if rejected else [],
                checked_claims=list(range(len(candidate['works'])+1)),
                basis=['current:'+current['messages'][0]['id']])
            return protocol.encode(dict(id='form-mock-'+str(len(self.requests)),model='gpt-6.1-sol',status='completed',
                service_tier='default',usage=None,output=[dict(type='message',role='assistant',status='completed',
                    content=[dict(type='output_text',text=json.dumps(out,ensure_ascii=False))])]))
        rows = [r for r in current['messages'] if r.get('role') == 'client' or r.get('sender_type') == 'client']
        if not rows:
            rows = [r for r in current['messages'] if r.get('direction') == 'in']
        ref = rows[-1]['id']; basis = ['current:' + ref]
        if role == 'review':
            rejected=self.provider_mode=='review_rejected'
            out = dict(kind='review', approved=not rejected,
                violations=['Ответ не соответствует исходному вопросу'] if rejected else [],
                checked_claims=[0], basis=basis)
        else:
            contract = current['candidate_contract']
            reply_schema = contract['schema']['properties']['reply']
            reply = reply_schema.get('enum', [contract['task']['output_contract']['example']['reply']])[0]
            candidate = dict(reply=reply, needs_operator=False, context_review=dict(
                last_intent='Клиент просит повесить полку.', latest_client_meaning=rows[-1].get('body', 'Нужно повесить полку.'),
                selected_step_fits=True, evidence_ids=[ref], note='Материал стены ещё не указан.'))
            if self.scripted_candidates:
                script = self.scripted_candidates.pop(0)
                candidate = copy.deepcopy(contract['task']['output_contract']['example'])
                candidate.update(reply=script.get('reply', reply), needs_operator=False)
                candidate.setdefault('context_review', {}).update(last_intent=script['intent'],
                    latest_client_meaning=script['meaning'], selected_step_fits=True,
                    evidence_ids=script.get('evidence_ids', [ref]), note=script['note'])
                candidate.update(script.get('candidate_fields', {}))
                reply = candidate['reply']
                from research_pipeline import schema_matches
                if not schema_matches(candidate,contract['schema']):
                    self.events.append(dict(stage='synthetic_candidate_schema_mismatch',
                        schema=contract['schema'],candidate=candidate))
            out = dict(kind='draft', reply=reply, candidate=candidate, evidence_ids=[ref], basis=basis,
                       claims=[dict(scope='question', text=reply, basis=basis)])
        return protocol.encode(dict(id='mock-response-' + str(len(self.requests)), model='gpt-6.1-sol', status='completed',
            service_tier='default', usage=dict(input_tokens=1000, output_tokens=200,
            input_tokens_details=dict(cached_tokens=0, cache_write_tokens=0)), output=[dict(type='message', role='assistant',
            status='completed', content=[dict(type='output_text', text=json.dumps(out, ensure_ascii=False))])]))

    def command(self, value):
        op = value['op']
        if op=='enable_form':
            self.service.intake_form_enabled=True;return True
        if op=='form_candidate':
            self.form_candidate=copy.deepcopy(value['candidate']);return True
        if op == 'book':
            if self.requests:
                raise ValueError('Synthetic source setup must precede generation')
            self.archive=self.root/'book.sqlite3'
            record=fixtures.ResearchTests().record('old-a',direction='kp',messages=[
                dict(id='book-request',direction='in',sender_type='client',body='Компьютер Dell Optiplex9020 не включается.'),
                dict(id='book-staff',direction='out',sender_type='operator',author='Опытный сотрудник',delivery='delivered',body='В квартире или организации?'),
                dict(id='book-place',direction='in',sender_type='client',body='В квартире.'),
                dict(id='book-closed',direction='system',sender_type='system',body='Диалог закрыт')])
            create_index(self.archive,[record],approved_cids=['old-a']);return True
        if op == 'provider_mode':
            self.provider_mode=value['mode'];return True
        if op == 'script_candidate':
            self.scripted_candidates.append(copy.deepcopy(value['candidate'])); return True
        if op == 'payloads':
            return copy.deepcopy(self.requests)
        if op == 'identity': return dict(self.identity(), expires_at=int(time.time()) + 40)
        if op == 'add': return self.add(value['cid'], value.get('text', 'Нужно повесить полку на бетонную стену.'), **value.get('changes', {}))
        if op == 'context': return copy.deepcopy(self.contexts[value['cid']])
        if op == 'ready':
            cid = value['cid']
            ctx = crm_fixtures.WorkflowTests().ctx(True)
            ctx.update(convId=cid, assigneeId=ACTOR, clientName='Иван')
            self.contexts[cid] = ctx; self.sync(cid)
            return ctx
        if op == 'proposal':
            cid = value['cid']; ctx = self.contexts[cid]
            proposal = crm_fixtures.WorkflowTests().proposal(ctx)
            body = dict(owner=OWNER, ctx=ctx, **self.last_identity)
            observed = self.service.prepare_source(self.app, body)
            from extension_assistant import _parse
            proposal['revision'] = _parse(observed['ctx'], self.app.store, 'assistant:' + digest(OWNER))[3]
            proposal['lead']['service_comment'] = 'https://lead.test/chats/' + cid
            return proposal
        if op == 'failure_audit':
            with self.app.store.connect() as db:
                return [json.loads(r['payload']) for r in db.execute(
                    "SELECT payload FROM workflow_audit WHERE kind='research_control_stopped'")]
        if op == 'update':
            self.contexts[value['cid']].update(value['changes']); self.sync(value['cid']); return True
        if op == 'call': return self.call(value['body'])
        if op == 'controller': return self.controller.handle(value['value'])
        if op == 'run_workers':
            while self.work: self.work.pop(0)()
            return True
        if op == 'evidence':
            jobs = self.controller.handle(dict(op='jobs', owner=OWNER))['jobs']
            return dict(events=self.events, simulated_model_calls=len(self.requests),
                        pending=self.controller.handle(dict(op='pending')),
                        jobs=jobs, audits=[self.service.jobs.audit_read(OWNER, j['job'], limit=100) for j in jobs])
        raise ValueError('Unsupported test command')


if __name__ == '__main__':
    def offline(event, args):
        if event in ('socket.connect', 'socket.connect_ex', 'socket.getaddrinfo', 'socket.bind', 'subprocess.Popen', 'os.system'):
            raise RuntimeError('External operation forbidden in auto simulation')
        if event == 'open' and isinstance(args[0], (str, bytes)):
            name = os.fsdecode(args[0])
            if name.endswith(('.key', 'secrets.env')):
                raise RuntimeError('Credential read forbidden in auto simulation')
    sys.addaudithook(offline)
    sim = Simulation()
    try:
        for line in sys.stdin:
            command = json.loads(line)
            try: result = dict(ok=True, value=sim.command(command))
            except Exception as error:
                result = dict(ok=False, error=type(error).__name__ + ': ' + str(error), trace=traceback.format_exc())
            print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        sim.tmp.cleanup()
