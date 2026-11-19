"""Durable private command ingress. Never claims or sends a conversation.

A trusted factory supplies an already configured native Assistant. It cannot
be installed or changed by a command. An indeterminate command is evidence to
recover, never permission to dispatch again, including after process restart.
"""
import os
import sqlite3
import threading
import time
from contextlib import closing, contextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import native_execution_protocol as wire
from native_authority import NativeAuthority


class Gateway:
    def __init__(self, directory, *, key, app_factory, clock=time.time, schedule=None,actions_enabled=False,office_enabled=False,
                 notifications_enabled=False,notify=None,notification_plan=None,notification_schedule=None):
        self.directory = Path(directory)
        if (not self.directory.is_absolute()
                or any(p.is_symlink() for p in (self.directory, *self.directory.parents))
                or not callable(key) or not callable(app_factory)or type(actions_enabled)is not bool
                or type(office_enabled)is not bool or office_enabled and not actions_enabled
                or type(notifications_enabled)is not bool or notifications_enabled and not office_enabled
                or notify is not None and not callable(notify)
                or notification_plan is not None and not callable(notification_plan)
                or notifications_enabled and ((notify is None)!=(notification_plan is None))):
            raise wire.ExecutionError('Trusted private native gateway required')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.directory.stat().st_uid != os.getuid():
            raise wire.ExecutionError('Native gateway owner mismatch')
        self.directory.chmod(0o700)
        self.path = self.directory/'commands.sqlite3'
        if self.path.is_symlink():
            raise wire.ExecutionError('Private native command journal required')
        self.key, self.app_factory, self.clock = key, app_factory, clock
        self.actions_enabled=actions_enabled
        self.office_enabled=office_enabled
        self.notifications_enabled=notifications_enabled
        if notifications_enabled and notify is None:
            from native_notification_client import NotificationClient
            client=NotificationClient(enabled=True,clock=clock)
            notify,notification_plan=client.send,client.prepare
        self.notify=notify
        self.notification_plan=notification_plan
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='native-research-command') if schedule is None else None
        self.schedule = schedule or self.pool.submit
        self.notification_pool=(ThreadPoolExecutor(max_workers=1,thread_name_prefix='native-service-notification')
            if notifications_enabled and schedule is None and notification_schedule is None else None)
        self.notification_schedule=notification_schedule or (self.notification_pool.submit if self.notification_pool else self.schedule)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS commands(
                  id TEXT PRIMARY KEY,request_hash TEXT NOT NULL,request BLOB NOT NULL,
                  state TEXT NOT NULL,status INTEGER,response BLOB,at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS nonces(digest TEXT PRIMARY KEY,expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS notifications(
                  work TEXT PRIMARY KEY,command TEXT NOT NULL,request_hash TEXT NOT NULL,
                  raw BLOB,status INTEGER,content_type TEXT);
            ''')
            db.execute('BEGIN IMMEDIATE')
            if 'progress' not in {row[1] for row in db.execute('PRAGMA table_info(commands)')}:
                db.execute('ALTER TABLE commands ADD COLUMN progress BLOB')
            columns={row[1]for row in db.execute('PRAGMA table_info(notifications)')}
            for name,kind in [('plan_raw','BLOB'),('plan_status','INTEGER'),('plan_type','TEXT')]:
                if name not in columns:db.execute('ALTER TABLE notifications ADD COLUMN '+name+' '+kind)
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path, timeout=3)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA synchronous=FULL')
            with db:
                yield db

    def _signed(self, key, nonce, status, data):
        raw = wire.encode(data)
        if len(raw) > wire.MAX_RESPONSE or key in raw:
            raise wire.ExecutionError('Native response exceeds budget')
        return status, raw, {'X-LB-Exec-Signature': wire.response_signature(key, raw, nonce, status)}

    def handle(self, raw, headers):
        try:
            key = self.key()
            value, nonce = wire.verify(key, raw, headers, now=self.clock())
            if key in raw:
                raise wire.ExecutionError('Credential reflected in command; do not persist')
        except (ValueError, TypeError, OSError, KeyError):
            return 403, wire.encode(dict(ok=False, code='native_authentication', can_send_or_create=False)), {}
        try:
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('DELETE FROM nonces WHERE expires<?', (self.clock(),))
                db.execute('INSERT INTO nonces VALUES(?,?)', (wire.sha(nonce.encode()), self.clock()+70))
                previous = db.execute('SELECT * FROM commands WHERE id=?', (value['command_id'],)).fetchone()
                if previous:
                    if previous['request_hash'] != wire.sha(raw):
                        raise wire.ExecutionError('Command identity changed')
                else:
                    if (value['operation'] not in ('recover', 'cancel')
                            and db.execute("SELECT count(*) FROM commands WHERE state='dispatching'").fetchone()[0] >= 32):
                        raise wire.ExecutionError('Native command queue is full')
                    db.execute('INSERT INTO commands(id,request_hash,request,state,status,response,at) '
                               'VALUES(?,?,?,\'dispatching\',NULL,NULL,?)',
                               (value['command_id'], wire.sha(raw), raw, self.clock()))
            if previous:
                # Observation can check the remote Run, so it must happen
                # AFTER releasing the journal write transaction. No unknown
                # command is dispatched again, even with a fresh signature.
                return self._signed(key, nonce, 200, self._recovery(previous, value))
            # FULL synchronous commit precedes source/model dispatch. Slow
            # source/finalize work outlives the HTTP observation independently.
            if value['operation'] in ('recover', 'cancel'):
                self._execute(value, key)
                with self.connect() as db:
                    saved = db.execute('SELECT * FROM commands WHERE id=?', (value['command_id'],)).fetchone()
                if saved['state'] == 'done':
                    return self._signed(key, nonce, saved['status'], wire.decode(saved['response'], wire.MAX_RESPONSE))
                return self._signed(key, nonce, 409, dict(ok=False, command_id=value['command_id'],
                    command_state=saved['state'], can_send_or_create=False))
            else:
                scheduler=self.notification_schedule if value['operation']=='notify_office' else self.schedule
                scheduler(lambda: self._execute(value, key))
            return self._signed(key, nonce, 202, dict(ok=True, command_id=value['command_id'],
                command_state='dispatching', can_send_or_create=False))
        except sqlite3.IntegrityError:
            return self._signed(key, nonce, 409, dict(ok=False, code='native_replay', can_send_or_create=False))
        except (ValueError, TypeError, OSError, KeyError, sqlite3.Error):
            # A dispatch may have reached a provider. Preserve 'dispatching',
            # and let recovery read the same command/job; do not reconstruct.
            return self._signed(key, nonce, 409, dict(ok=False, code='native_command_uncertain',
                command_id=value['command_id'], can_send_or_create=False))

    def _execute(self, value, key):
        try:
            data, status = self._dispatch(value)
            response = wire.encode(dict(ok=status < 400, data=data, can_send_or_create=False))
            if len(response) > wire.MAX_RESPONSE or key in response:
                raise wire.ExecutionError('Unsafe or oversized native response')
            with self.connect() as db:
                db.execute("UPDATE commands SET state='done',status=?,response=? WHERE id=? AND state='dispatching'",
                           (status, response, value['command_id']))
        except Exception:
            # No retry, repaired JSON, reflected credentials or exception
            # strings. The original request and original research job remain.
            with self.connect() as db:
                db.execute("UPDATE commands SET state='uncertain' WHERE id=? AND state='dispatching'",
                           (value['command_id'],))

    def _app_body(self, value):
        app = self.app_factory(value['principal_id'])
        authority = getattr(getattr(app, 'research', None), 'native_authority', None)
        if not isinstance(authority, NativeAuthority) or authority.principal_id != value['principal_id']:
            raise wire.ExecutionError('Trusted exact native principal required')
        body = dict(owner=authority.owner, ctx=dict(convId=value['arguments'].get('cid')),
            native_run=dict(run_id=value['run_id'], generation=value['generation'], operator_id=value['operator_id']))
        return app, body

    def _progress(self, value, out):
        progress = {k: out[k] for k in ('request_id', 'revision', 'research_job_id') if out.get(k)}
        if not all(isinstance(progress.get(k), str) and 0 < len(progress[k]) <= 200
                   for k in ('request_id', 'revision')):
            return
        with self.connect() as db:
            db.execute("UPDATE commands SET progress=? WHERE id=? AND state='dispatching'",
                       (wire.encode(progress), value['command_id']))

    @staticmethod
    def _original_job(app, value, progress):
        """Read exact existing metadata, never recreate a preview/job/result."""
        if not isinstance(progress, dict) or not progress.get('request_id') or not progress.get('revision'):
            return None
        service, args = app.research, value['arguments']
        owner = service.native_authority.owner
        with service.jobs.connect() as db:
            rows = db.execute('SELECT j.id,j.state,g.binding FROM jobs j JOIN grants g ON g.id=j.grant_id '
                "WHERE json_extract(g.binding,'$.owner')=? AND json_extract(g.binding,'$.principal')=? "
                "AND json_extract(g.binding,'$.operator')=? AND json_extract(g.binding,'$.chat')=? "
                "AND json_extract(g.binding,'$.request')=? AND json_extract(g.binding,'$.revision')=?",
                (owner, value['principal_id'], value['operator_id'], args.get('cid'),
                 progress['request_id'], progress['revision'])).fetchall()
        if len(rows) != 1 or progress.get('research_job_id') not in (None, rows[0]['id']):
            return None
        return dict(request_id=progress['request_id'], revision=progress['revision'],
                    research_job_id=rows[0]['id'], research_state=rows[0]['state'])

    def _recovery(self, row, value):
        original = wire.decode(row['request'], wire.MAX_OFFICE_REQUEST)
        if any(original[k] != value[k] for k in ('principal_id', 'operator_id', 'run_id', 'generation')):
            raise wire.ExecutionError('Original command belongs to another actor or launch')
        if original['operation']=='notify_office' and row['state']!='done':
            self._recover_notification(original)
            with self.connect()as db:
                row=db.execute('SELECT * FROM commands WHERE id=?',(row['id'],)).fetchone()
        result = dict(ok=True, command_id=row['id'], command_state=row['state'],
                      original_status=row['status'], can_send_or_create=False, requires_current_validation=True)
        if original['operation']=='notify_office' and row['state']=='done':
            # Operational evidence survives Stop; it is never permission to
            # send/link/close, which Main must re-authorize independently.
            result['original_result']=wire.decode(row['response'],wire.MAX_RESPONSE)
        if row['state'] == 'done' or row['progress']:
            # Archived output requires the exact current launch. It remains
            # marked for full source validation; stopped runs get metadata.
            try:
                app, body = self._app_body(original)
                # Retrieval is observation of an archived result, never an
                # action allowance. Fresh full source validation is a separate
                # exact status/finalize command before using that draft.
                app.research.native_authority.current(body)
                if row['state'] == 'done':
                    result['original_result'] = wire.decode(row['response'], wire.MAX_RESPONSE)
                elif row['progress']:
                    original_job = self._original_job(app, original, wire.decode(row['progress'], wire.MAX_REQUEST))
                    if original_job is not None:
                        result['original_job'] = original_job
            except (ValueError, TypeError, KeyError, OSError):
                result['source_or_run_not_current'] = True
        return result

    def _notification_payload(self,value):
        import re
        args=value['arguments']
        with self.connect()as db:
            row=db.execute('SELECT * FROM commands WHERE id=?',(args['create_command_id'],)).fetchone()
        if row is None or row['state']!='done':
            raise wire.ExecutionError('Original consumed office command required')
        old=wire.decode(row['request'],wire.MAX_OFFICE_REQUEST)
        data=wire.decode(row['response'],wire.MAX_RESPONSE)
        if (old['operation']!='consume_office' or row['status']!=200 or data.get('ok')is not True
                or data.get('data',{}).get('execution_allowed')is not True
                or any(old[k]!=value[k]for k in ('principal_id','operator_id','run_id','generation'))
                or any(old['arguments'].get(k)!=args[k]for k in ('cid','source_sha256','snapshot_hash'))):
            raise wire.ExecutionError('Notification and original consumed create differ')
        proposal=old['arguments']['proposal'];code=proposal.get('followup',{}).get('code')
        if (proposal['form_reference']!=args['form_reference']
                or proposal.get('followup',{}).get('required')is not True
                or proposal.get('followup',{}).get('telegram_ready')is not True
                or not isinstance(code,str) or not re.fullmatch(r'[АСВМБ]\d{1,3}(?:\.\d)?',code)):
            raise wire.ExecutionError('Original source-code service route required')
        return dict(v=1,intent_id=args['notification_id'],work_id=args['work_id'],
            **{k:value[k]for k in ('principal_id','operator_id','run_id','generation')},
            **{k:args[k]for k in ('cid','source_sha256','snapshot_hash','form_reference',
                                'card_sha256','crm_request_id','dispatch_before')},
            direction=proposal['dir'],source_code=code)

    def _recover_notification(self,value):
        from native_notification_client import receipt
        args=value['arguments']
        with self.connect()as db:
            row=db.execute('SELECT * FROM notifications WHERE work=?',(args['work_id'],)).fetchone()
        if row is None or row['command']!=value['command_id'] or row['raw']is None:
            return
        try:
            if row['status']!=200 or row['content_type']!='application/json':return
            payload=self._notification_payload(value)
            result=receipt(wire.decode(row['raw'],350000),payload)
        except (ValueError,TypeError,KeyError):return
        wrapped=wire.encode(dict(ok=True,data=result,can_send_or_create=False))
        with self.connect()as db:
            db.execute("UPDATE commands SET state='done',status=200,response=? WHERE id=? AND state!='done'",
                       (wrapped,value['command_id']))

    def _notification(self,value,app,body):
        from native_notification_client import receipt
        args=value['arguments'];payload=self._notification_payload(value)
        if not 0<args['dispatch_before']-self.clock()<=90:
            raise wire.ExecutionError('Original notification deadline expired')
        with self.connect()as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO notifications(work,command,request_hash)VALUES(?,?,?)',
                       (args['work_id'],value['command_id'],wire.sha(wire.encode(value))))
        def persist_kind(kind,status,content_type,raw):
            if (type(status)is not int or not isinstance(raw,bytes) or len(raw)>350000
                    or not isinstance(content_type,str) or len(content_type)>64):
                raise wire.ExecutionError('Bounded original notification response required')
            with self.connect()as db:
                names=('raw','status','content_type')if kind=='send'else('plan_raw','plan_status','plan_type')
                changed=db.execute('UPDATE notifications SET '+names[0]+'=?,'+names[1]+'=?,'+names[2]+'=? '
                    'WHERE work=? AND command=? AND '+names[0]+' IS NULL',
                    (raw,status,content_type,args['work_id'],value['command_id'])).rowcount
                if changed!=1:raise wire.ExecutionError('Original notification response is immutable')
        planned=self.notification_plan(payload,lambda *a:persist_kind('prepare',*a))
        with self.connect()as db:
            saved=db.execute('SELECT * FROM notifications WHERE work=?',(args['work_id'],)).fetchone()
        if (saved['plan_raw']is None or saved['plan_status']!=200 or saved['plan_type']!='application/json'
                or wire.decode(saved['plan_raw'],350000)!=planned or planned.get('ok')is not True
                or planned.get('prepared')is not True or planned.get('telegram_confirmed')is not False
                or planned.get('work_id')!=payload['work_id'] or planned.get('intent_id')!=payload['intent_id']):
            raise wire.ExecutionError('Original persisted read-only destination preparation required')
        # Group/topic reads may take tens of seconds. Recheck the exact full
        # source and Run AFTER those reads, immediately before a short issue.
        self._current(app,body,args)
        app.research.native_authority.current(body)
        out=self.notify(payload,lambda *a:persist_kind('send',*a),min(args['dispatch_before'],self.clock()+5))
        with self.connect()as db:
            original=db.execute('SELECT * FROM notifications WHERE work=?',(args['work_id'],)).fetchone()
        if (original['raw']is None or original['status']!=200 or original['content_type']!='application/json'
                or wire.decode(original['raw'],350000)!=out):
            raise wire.ExecutionError('Original persisted notification response required')
        return receipt(out,payload),200

    @staticmethod
    def _current(app, body, args):
        app.research.native_authority.current(body)
        prepared = app.research.prepare_source(app, body)
        if prepared['ctx'].get('sourceSnapshotSha256') != args.get('source_sha256'):
            raise wire.ExecutionError('Original native source changed')
        return prepared

    def _cancel(self, app, body, value):
        args, service = value['arguments'], app.research
        job = args['research_job_id']
        if not job:
            raise wire.ExecutionError('Exact durable job required for private cancellation')
        # Resource cancellation survives a stopped Run, but only an exact job
        # previously returned through this gateway can be affected. It has no
        # generation/finalize/send authority, and cannot cancel another run.
        found = False
        with self.connect() as db:
            rows = db.execute('SELECT request,response,progress FROM commands '
                              'WHERE response IS NOT NULL OR progress IS NOT NULL').fetchall()
        for row in rows:
            old = wire.decode(row['request'], wire.MAX_OFFICE_REQUEST)
            if any(old[k] != value[k] for k in ('principal_id', 'operator_id', 'run_id', 'generation')):
                continue
            result = wire.decode(row['response'], wire.MAX_RESPONSE).get('data', {}) if row['response'] else {}
            if row['progress'] and not result.get('research_job_id'):
                result = self._original_job(app, old, wire.decode(row['progress'], wire.MAX_REQUEST)) or {}
            if (old['arguments'].get('cid') == args['cid']
                    and old['arguments'].get('source_sha256') == args['source_sha256']
                    and result.get('research_job_id') == job
                    and result.get('request_id') == args['request_id']):
                found = True
                break
        if not found:
            raise wire.ExecutionError('No original native job receipt')
        with service.jobs.connect() as db:
            row = service.jobs._row(db, job)
            binding = wire.decode(row['binding'].encode(), wire.MAX_REQUEST)
        if any(binding[k] != v for k, v in dict(owner=body['owner'], principal=value['principal_id'],
                operator=value['operator_id'], chat=args['cid'], request=args['request_id'], revision=args['revision']).items()):
            raise wire.ExecutionError('Cancellation and original job mismatch')
        service.jobs.stop(body['owner'], job)
        with service.jobs.connect() as db:
            db.execute('UPDATE grants SET deadline=min(deadline,?) WHERE job=?', (service.jobs.clock(), job))
        service._abort(app, body, job, 'Серверный запуск остановлен', technical=False)
        return dict(ok=True, research_job_id=job, research_state=service.jobs.status(body['owner'], job)['state'],
                    can_send_or_create=False), 200

    def _dispatch(self, value):
        op, args = value['operation'], value['arguments']
        if op == 'recover':
            with self.connect() as db:
                row = db.execute('SELECT * FROM commands WHERE id=?', (args['command_id'],)).fetchone()
            if row is None:
                raise wire.ExecutionError('Original command unavailable')
            return self._recovery(row, value), 200
        if op in ('reserve_office','consume_office') and not self.office_enabled:
            from native_workflow import NativeWorkflow
            return NativeWorkflow.denied('native_office_disabled'),409
        if op=='notify_office' and not self.notifications_enabled:
            return dict(ok=False,code='native_notifications_disabled',telegram_confirmed=False),409
        app, body = self._app_body(value)
        if op == 'cancel':
            return self._cancel(app, body, value)
        body = self._current(app, body, args)
        if op=='notify_office':return self._notification(value,app,body)
        if op in ('reserve_action','consume_action','reserve_office','consume_office'):
            from native_workflow import NativeWorkflow
            workflow=NativeWorkflow(app,enabled=self.actions_enabled)
            operation={k:args[k]for k in ('kind','operation_id','revision')}
            if args['kind']=='reply':operation['draft_id']=args['draft_id']
            if args['kind']=='create_crm':
                operation.update(proposal=args['proposal'],snapshot_hash=args['snapshot_hash'])
            out=(workflow.reserve(body,operation)if op in ('reserve_action','reserve_office')else
                 workflow.consume(body,operation,args['grant_id']))
            return out,200 if out.get('ok')else 409
        if op == 'inspect':
            from native_workflow import NativeWorkflow
            out=NativeWorkflow(app).plan(body)
            if out.get('source_sha256')!=args['source_sha256']:
                raise wire.ExecutionError('Source changed during native intake inspection')
            return out,200 if out.get('ok')else 409
        if op == 'prepare':
            live = app.research.native_authority.current(body)
            body.update(action='form_preview' if args['purpose'] == 'intake_form_v1' else 'preview',
                        wording_mode='neural_auto' if live['mode'] == 'auto' else 'neural_review',
                        _trusted_research_profile=app.research.profile)
            out, status = app.handle(body)
            if (args['purpose']=='visual_observation_v1' and status<400
                    and (not out.get('pending_model') or out.get('research_purpose')!='visual_observation_v1')):
                return dict(ok=False,code='native_visual_plan_changed',can_send_or_create=False),409
            if status >= 400 or not out.get('pending_model'):
                return out, status
            self._progress(value, out)  # Commit exact preview before starting its durable job.
            body = {k: v for k, v in body.items() if k not in ('wording_mode', '_trusted_research_profile')}
            body.update(action='research_start', request_id=out['request_id'], revision=out['revision'])
        else:
            body.update(action='research_status' if op == 'status' else 'research_finalize',
                        **{k: args[k] for k in ('request_id', 'revision', 'research_job_id')})
        out, status = app.handle(body)
        if status < 400:
            self._progress(value, out)
        return out, status


class NativeApplications:
    """Trusted actor-scoped views of the SAME durable source-attempt store.

    Creating a view does not read a key, obtain a Run or create a model grant.
    NativeAuthority rechecks the real principal and selected author for every
    use. Stable namespaces are process-derived, never caller-controlled.
    """
    def __init__(self, store, base):
        from assistant_store import Store
        from research_workflow import ResearchService
        if (not isinstance(store, Store) or not Path(store.path).is_absolute()
                or not isinstance(base, ResearchService) or base.native_authority is not None
                or base.native_context is None):
            raise wire.ExecutionError('Trusted browser base and authenticated native sources required')
        self.store, self.base = store, base
        self.apps = {}
        self.lock = threading.Lock()

    def __call__(self, principal):
        if not wire.identifier(principal) or self.base._runtime_version() != self.base.code_version:
            raise wire.ExecutionError('Exact native principal and unchanged runtime required')
        with self.lock:
            if principal not in self.apps:
                if len(self.apps) >= 128:
                    raise wire.ExecutionError('Native principal view capacity reached')
                import assistant_policy as policy
                from extension_assistant import Assistant
                from research_workflow import ResearchService
                base = self.base
                authority = NativeAuthority(base.native_context.client, owner='native:'+principal,
                    principal_id=principal, current_versions=lambda:(policy.VERSION, service.code_version,
                        service._map_version(), service.corpus_factory().initial))
                service = ResearchService(base.jobs.directory, shared_lock=base.jobs.lock,
                    corpus_factory=base.corpus_factory, request=base.request, schedule=base.schedule,
                    profile=base.profile, native_context=base.native_context, funding=base.funding,
                    proposal_enabled=base.proposal_enabled, intake_form_enabled=base.intake_form_enabled,
                    owner_auto_enabled=base.owner_auto_enabled, auto_session_call_limit=base.auto_session_call_limit,
                    native_crm_only_enabled=base.native_crm_only_enabled,
                    unique_replies_enabled=base.unique_replies_enabled,
                    price_wording_enabled=base.price_wording_enabled,
                    native_authority=authority)
                self.apps[principal] = Assistant(self.store, research=service)
            return self.apps[principal]

    def services(self):
        with self.lock:
            return tuple(app.research for app in self.apps.values())


_gateway = None
_lock = threading.Lock()


def configure(gateway):
    """Trusted startup only; never a command operation or source-reader tool."""
    global _gateway
    if gateway is not None and not isinstance(gateway, Gateway):
        raise wire.ExecutionError('Typed native gateway required')
    with _lock:
        if _gateway is not None:
            raise wire.ExecutionError('Native gateway already configured')
        _gateway = gateway


def serve(raw, headers):
    with _lock:
        gateway = _gateway
    if gateway is None:
        return 503, wire.encode(dict(ok=False, code='native_not_configured', can_send_or_create=False)), {}
    return gateway.handle(raw, headers)


def configured_services():
    """Private root control can see native pending bindings, not just browser ones."""
    with _lock:
        gateway = _gateway
    if gateway is not None and isinstance(gateway.app_factory, NativeApplications):
        return gateway.app_factory.services()
    return ()
