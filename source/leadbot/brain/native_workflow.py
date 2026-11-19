"""Native Run action reservations; no model, LeadChat, CRM or Telegram writes.

Planning uses the same business rules as the existing browser workflow. A
reservation grants no execution. Consume is durable before dispatch and can
never be repeated; a started action needs actual transport reconciliation.
No browser lease, sid, JWT or reviewed confirmation is synthesized here.
"""
import json
import sqlite3
import time
import uuid

import assistant_policy as policy
import personal_workflow as workflow
import workflow_audit
from assistant_store import digest
from native_authority import NativeAuthority
from research_workflow import ResearchService
from source_protocol import encode


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS native_workflow_grants(
        id TEXT PRIMARY KEY,scope TEXT NOT NULL,chat TEXT NOT NULL,slot TEXT NOT NULL,
        principal TEXT NOT NULL,operator TEXT NOT NULL,launch TEXT NOT NULL,
        revision TEXT NOT NULL,source_hash TEXT NOT NULL,versions TEXT NOT NULL,
        operation_hash TEXT NOT NULL,kind TEXT NOT NULL,state TEXT NOT NULL,
        expires REAL NOT NULL,created REAL NOT NULL,started REAL)''')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS native_workflow_slot ON native_workflow_grants(chat,slot)')


def prior_native(db, chat, slot):
    return workflow.prior_native_action(db,chat,slot)


class NativeWorkflow:
    def __init__(self, app, *, enabled=False, clock=time.time):
        service=getattr(app,'research',None)
        if (type(enabled)is not bool or not callable(clock) or not isinstance(service,ResearchService)
                or not isinstance(service.native_authority,NativeAuthority) or service.native_context is None):
            raise ValueError('Typed native service and explicit action capability required')
        self.app,self.service,self.store=app,service,app.store
        self.authority=service.native_authority
        self.enabled,self.clock=enabled,clock

    @staticmethod
    def denied(code):
        return dict(ok=False,code=code,auto_enabled=False,execution_allowed=False,customer_effect_confirmed=False)

    def _context(self, body):
        from extension_assistant import _parse
        if self.service._runtime_version()!=self.service.code_version:
            raise ValueError('Native runtime changed')
        live=self.authority.current(body)
        prepared=self.service.prepare_source(self.app,body)
        owner=self.authority.owner;scope='assistant:'+digest(owner)
        chat,messages,known,revision=_parse(prepared['ctx'],self.store,scope)
        _,held=self.store.observe(scope,chat,revision)
        ctx=dict(prepared['ctx'],_parsed_messages=messages,workflowRevision=revision)
        workflow_audit.read_snapshot(self.store,scope,chat,revision,messages,known,prepared['ctx'])
        planned=workflow.plan_for_actor(messages,known,ctx,live['operator_id'],0,revision,
                                       allow_visual=self.service.profile=='sol_only')
        if held:
            planned.update(eligible=False,step='paused',operation_id='',reason='Диалог остановлен оператором')
        if live['mode']=='auto' and self.service.owner_auto_enabled:
            allowance=self.service.automatic_allowance(self.app,prepared,{})
            if allowance['blocked'] or allowance['remaining_calls']==0 and planned['step']=='claim':
                planned.update(eligible=False,step='paused',operation_id='',reason='Допуск исследования остановлен или исчерпан')
        fresh=self.authority.current(body)
        if live!=fresh:
            raise ValueError('Native authority changed during source read')
        return prepared,ctx,known,revision,planned,live

    def plan(self, body):
        try:
            prepared,_,_,revision,planned,live=self._context(body)
            return dict(planned,run_mode=live['mode'],revision=revision,
                        source_sha256=prepared['ctx']['sourceSnapshotSha256'],
                        execution_allowed=False,customer_effect_confirmed=False)
        except (ValueError,TypeError,KeyError,OSError):
            return self.denied('native_source_or_run_changed')

    @staticmethod
    def _operation(operation):
        if not isinstance(operation,dict):
            raise ValueError('Typed native operation required')
        common={'kind','operation_id','revision','preflight_only'}
        fields={'claim':set(),'reply':{'draft_id','reply'},'create_crm':{'proposal','snapshot_hash'}}
        if operation.get('kind')not in fields or set(operation)-(common|fields[operation['kind']]):
            raise ValueError('Unsupported native operation or caller authority fields')
        forbidden={'authorization','headers','cookie','api_key','access_token','password','secret','identity_proof'}
        def check(value):
            if isinstance(value,dict):
                if any(str(k).casefold()in forbidden for k in value):
                    raise ValueError('Credential-bearing operation rejected')
                for item in value.values():check(item)
            elif isinstance(value,list):
                for item in value:check(item)
        check(operation)
        raw=encode(operation)
        if len(raw)>100000:
            raise ValueError('Bounded native operation required')
        return digest(operation)

    def _checked(self, body, operation):
        # Native capability is trusted startup configuration, default OFF.
        # The old browser-availability switch cannot authorize this path or
        # substitute for its freshly authenticated native Run below.
        if not self.enabled or not self.service.owner_auto_enabled:
            return None,self.denied('native_actions_disabled')
        checksum=self._operation(operation)
        prepared,ctx,known,revision,planned,live=self._context(body)
        if live['mode']!='auto':
            return None,self.denied('native_rehearsal_has_no_action_authority')
        actor={k:live[k]for k in ('principal_id','operator_id')}
        checked=workflow.validate_operation(self.store,self.authority.owner,actor,ctx,known,revision,
                                             planned,operation,crm_only=self.service.native_crm_only_enabled)
        if not checked['ok']:
            return None,checked
        launch=self.authority.launch_binding(body,require_auto=True)
        draft=checked['draft']
        if checked['kind']=='reply':
            if draft.get('native_launch_binding')!=launch:
                return None,self.denied('native_draft_launch_changed')
            if operation.get('reply')not in (None,draft['reply']):
                return None,self.denied('native_draft_text_changed')
        if checked['kind']=='create_crm' and self.service.intake_form_enabled:
            self.service.verify_form(self.app,prepared,operation.get('proposal')or{})
        elif checked['kind']=='create_crm':
            return None,self.denied('native_intake_form_unavailable')
        opid=str(operation.get('operation_id')or'')
        slot='create_once' if checked['kind']=='create_crm' else checked['kind']+':'+opid
        return dict(scope=digest(self.authority.owner),chat=ctx['convId'],slot=slot,
            principal=actor['principal_id'],operator=actor['operator_id'],launch=launch,revision=revision,
            source_hash=prepared['ctx']['sourceSnapshotSha256'],versions=encode(live['versions']).decode(),
            operation_hash=checksum,kind=checked['kind'],draft=draft,ctx=ctx,known=known,
            preflight_only=checked['preflight_only']),None

    @staticmethod
    def _legacy(db, current):
        workflow.grant_schema(db)
        return db.execute('SELECT 1 FROM workflow_grants WHERE chat=? AND slot=?',
                          (current['chat'],current['slot'])).fetchone()is not None

    @staticmethod
    def _matches(row, current):
        return all(row[k]==current[k]for k in ('scope','chat','slot','principal','operator','launch',
                    'revision','source_hash','versions','operation_hash','kind'))

    def _audit(self, current, event, detail):
        detail=dict(detail,source_sha256=current['source_hash'],versions=json.loads(current['versions']),
                    principal_id=current['principal'],operator_id=current['operator'])
        workflow_audit.append(self.store,'assistant:'+current['scope'],current['chat'],event,
                              current['revision'],detail)

    def reserve(self, body, operation):
        try:
            current,denied=self._checked(body,operation)
            if denied:return denied
            if current['preflight_only']:
                return dict(ok=True,preflight_only=True,reserved=False,execution_allowed=False,
                            customer_effect_confirmed=False,revision=current['revision'])
            with self.store.connect()as db:
                db.execute('PRAGMA synchronous=FULL')
                db.execute('BEGIN IMMEDIATE');schema(db)
                if self._legacy(db,current):return self.denied('prior_browser_action')
                row=db.execute('SELECT *FROM native_workflow_grants WHERE chat=? AND slot=?',
                               (current['chat'],current['slot'])).fetchone()
                if row:
                    if self._matches(row,current)and row['state']=='reserved'and row['expires']>self.clock():
                        return dict(ok=True,reserved=True,grant_id=row['id'],execution_allowed=False,
                                    expires_at=row['expires'],recovered=True,customer_effect_confirmed=False)
                    return self.denied('native_action_already_reserved_or_started')
                grant=uuid.uuid4().hex;expires=self.clock()+300
                keys=('scope','chat','slot','principal','operator','launch','revision','source_hash','versions','operation_hash','kind')
                db.execute('INSERT INTO native_workflow_grants(id,'+','.join(keys)+',state,expires,created) '
                           'VALUES('+','.join('?'for _ in range(15))+')',
                           (grant,*[current[k]for k in keys],'reserved',expires,self.clock()))
            self._audit(current,'native_action_reserved',dict(grant_id=grant,kind=current['kind'],execution_allowed=False))
            return dict(ok=True,reserved=True,grant_id=grant,execution_allowed=False,
                        expires_at=expires,customer_effect_confirmed=False)
        except (ValueError,TypeError,KeyError,OSError,sqlite3.Error):
            return self.denied('native_action_not_current')

    def consume(self, body, operation, grant_id):
        try:
            current,denied=self._checked(body,operation)
            if denied:return denied
            if current['preflight_only']:return self.denied('native_preflight_not_executable')
            with self.store.connect()as db:
                db.execute('PRAGMA synchronous=FULL')
                db.execute('BEGIN IMMEDIATE');schema(db)
                row=db.execute('SELECT *FROM native_workflow_grants WHERE id=?',(grant_id,)).fetchone()
                if (not row or not self._matches(row,current)or row['state']!='reserved'
                        or row['expires']<=self.clock()or self._legacy(db,current)):
                    return self.denied('native_action_not_reserved_or_already_started')
                changed=db.execute("UPDATE native_workflow_grants SET state='started',started=? "
                    "WHERE id=? AND state='reserved'",(self.clock(),grant_id)).rowcount
                if changed!=1:return self.denied('native_action_already_started')
                if current['kind']=='create_crm':
                    fields=workflow.CRM_CORE_FIELDS+workflow.required_crm_fields(current['ctx']['_parsed_messages'],current['known'])
                    db.execute('INSERT OR REPLACE INTO workflow_crm_requirements VALUES(?,?,?,?,?)',
                        (current['scope'],current['chat'],json.dumps(fields),policy.VERSION,digest(current['ctx']['_parsed_messages'])))
                if current['kind']=='reply':
                    import own_visit
                    own_visit.anchor(db,'assistant:'+current['scope'],current['chat'],current['operator'],
                        current['known'].get('account_id',''),operation['operation_id'],current['draft'],
                        current['ctx']['_parsed_messages'],self.clock(),self.clock()+10)
            self._audit(current,'native_action_started',dict(grant_id=grant_id,kind=current['kind'],
                execution_allowed=True,customer_effect_confirmed=False))
            result=dict(ok=True,grant_id=grant_id,execution_allowed=True,dispatch_before=self.clock()+10,
                kind=current['kind'],chat=current['chat'],operator_id=current['operator'],
                revision=current['revision'],source_sha256=current['source_hash'],
                native_launch_binding=current['launch'],operation_id=operation['operation_id'],
                draft_id=operation.get('draft_id'),reply=current['draft']['reply']if current['draft']else'',
                customer_effect_confirmed=False)
            if current['kind']=='create_crm':
                result.update(snapshot_hash=operation['snapshot_hash'],
                              form_reference=operation['proposal']['form_reference'])
            return result
        except (ValueError,TypeError,KeyError,OSError,sqlite3.Error):
            return self.denied('native_action_not_current')
