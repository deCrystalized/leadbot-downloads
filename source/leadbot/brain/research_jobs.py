"""Private durable research receipts. No implicit transport or action authority.

Admission and root decisions are trusted control operations, not model tools
or browser-supplied flags. Unknown provider/finalize outcomes require reading
the same job; they never authorize another generation or external action.
"""
import fcntl
import hashlib
import json
import math
import os
import re
import sqlite3
import time
import threading
import uuid
from contextlib import closing, contextmanager, ExitStack
from pathlib import Path

from experienced_dialogues import digest
from research_pipeline import models_for
from research_openai import RequestNotStarted, strict_loads
from research_receipts import validate_kind
import research_subscription
from research_publication import Holds, PublicationError
from research_receipts import HTTPReceipt, HTTPFailure, ProviderResult, StoppedProviderReceipt, transport_metadata


class JobError(ValueError):
    def __init__(self, *args, check=None, changed_fields=()):
        super().__init__(*args)
        self.check = check
        self.changed_fields = tuple(sorted({field for field in changed_fields
                                           if isinstance(field,str) and field in FIELDS}))


class JobNotStarted(JobError, RequestNotStarted):
    pass


class SavedReceiptStopped(JobError, StoppedProviderReceipt):
    def __init__(self, error, *, raw, metadata, job, step):
        super().__init__('Original provider receipt saved; context stopped before ACK; no retry',
                         check=getattr(error,'check',None), changed_fields=getattr(error,'changed_fields',()))
        self.billing_attempt_id = f'job-{job}-{step}'
        self.billing_metadata = transport_metadata(metadata)
        try:
            value = (research_subscription.decode(raw) if metadata['content_type']=='event_stream' else strict_loads(raw))
        except (ValueError,UnicodeError):
            value = None
        if isinstance(value,dict):
            # No output text, candidate, instructions or opaque reasoning crosses
            # this failure boundary. Accounting is separate from accepting a reply.
            self.billing_response = {key:value[key] for key in
                ('id','model','status','usage','service_tier','incomplete_details') if key in value}


class WorkerBusy(JobNotStarted):
    pass


FIELDS = {'owner','request','chat','revision','principal','operator','policy','memory','map','task','profile'}


class Jobs:
    def __init__(self, directory, *, shared_lock, clock=time.time, unique_replies_enabled=False):
        if type(unique_replies_enabled) is not bool:
            raise JobError('Explicit trusted unique-reply capability required')
        self.unique_replies_enabled = unique_replies_enabled
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.directory.is_symlink():
            raise JobError('Private job directory must not be a symlink')
        self.directory.chmod(0o700)
        self.path = self.directory / 'jobs.sqlite3'
        self.lock = Path(shared_lock)
        self.clock = clock
        self.holds = Holds(self.lock, self.path, clock=clock)
        self.session = threading.local()
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS grants(
                  id TEXT PRIMARY KEY,binding TEXT NOT NULL,binding_hash TEXT NOT NULL,
                  max_calls INTEGER NOT NULL,deadline REAL NOT NULL,job TEXT UNIQUE);
                CREATE TABLE IF NOT EXISTS jobs(
                  id TEXT PRIMARY KEY,grant_id TEXT NOT NULL,state TEXT NOT NULL,
                  calls_spent INTEGER NOT NULL DEFAULT 0,result_hash TEXT,accepted INTEGER,
                  reviewer TEXT,final_result TEXT,updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS steps(
                  job TEXT NOT NULL,step INTEGER NOT NULL,request_hash TEXT NOT NULL,
                  role TEXT NOT NULL,model TEXT NOT NULL,state TEXT NOT NULL,
                  raw_hash TEXT,acknowledged INTEGER NOT NULL DEFAULT 0,
                  PRIMARY KEY(job,step));
                CREATE TABLE IF NOT EXISTS events(
                  sequence INTEGER PRIMARY KEY,job TEXT NOT NULL,event TEXT NOT NULL,
                  detail TEXT NOT NULL,at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS events_job_event ON events(job,event,sequence);
                CREATE TABLE IF NOT EXISTS audit_events(
                  sequence INTEGER PRIMARY KEY AUTOINCREMENT,job TEXT NOT NULL,event TEXT NOT NULL,
                  detail TEXT NOT NULL,at REAL NOT NULL,previous_hash TEXT NOT NULL,event_hash TEXT NOT NULL);
            ''')
            db.execute('BEGIN IMMEDIATE')
            columns = {row[1] for row in db.execute('PRAGMA table_info(steps)')}
            for name in ('transport_kind','transport_hash'):
                if name not in columns:
                    db.execute('ALTER TABLE steps ADD COLUMN '+name+' TEXT')
        self.path.chmod(0o600)
        if self.unique_replies_enabled:
            with self.connect() as db:
                db.execute("CREATE INDEX IF NOT EXISTS audit_reply_fingerprint ON audit_events("
                           "event,json_extract(detail,'$.owner'),json_extract(detail,'$.reply_key'))")

    def _reply_key(self, row):
        from reply_diversity import fingerprint
        raw = self._file(row['id'],'result.json').read_bytes()
        if hashlib.sha256(raw).hexdigest() != row['result_hash']:
            raise JobError('Accepted original reply changed; uniqueness history unavailable')
        result = json.loads(raw)
        if result.get('approved') is not True:
            raise JobError('Unapproved result cannot form accepted reply history')
        if result.get('purpose') in ('intake_form_v1','visual_observation_v1'):
            return None
        candidate = result.get('candidate')
        reply = candidate.get('reply','') if isinstance(candidate,dict) else result.get('reply','')
        return fingerprint(reply)

    def _index_reply(self, db, row, owner, *, legacy, complete_reply=None):
        binding = strict_loads(row['binding'])
        original = db.execute('SELECT binding_hash FROM grants WHERE id=?',(row['grant_id'],)).fetchone()
        if original is None or original[0] != self._binding(binding) or binding['owner'] != owner:
            raise JobError('Original accepted reply owner binding changed')
        key = self._reply_key(row)
        scope = 'accepted_candidate_not_verified_customer_delivery'
        if complete_reply is not None:
            from reply_diversity import fingerprint
            key = fingerprint(complete_reply)
            scope = 'finalized_draft_not_verified_customer_delivery'
        self._event(db,row['id'],'reply_indexed',{'owner':owner,'reply_key':key,
            'version':1,'result_sha256':row['result_hash'],'legacy':legacy,
            'scope':scope})

    def _index_accepted_replies(self, db, owner):
        # Only original replies of this bot owner are read; no cross-customer
        # text is sent to the model. Existing audit hash chains remain in use.
        invalid = db.execute("SELECT 1 FROM audit_events a JOIN jobs j ON j.id=a.job "
            "JOIN grants g ON g.id=j.grant_id WHERE a.event='reply_indexed' "
            "AND json_extract(g.binding,'$.owner')=? AND (json_extract(a.detail,'$.version') IS NOT 1 "
            "OR json_extract(a.detail,'$.owner') IS NOT ? "
            "OR json_extract(a.detail,'$.result_sha256') IS NOT j.result_hash) LIMIT 1",(owner,owner)).fetchone()
        if invalid:
            raise JobError('Accepted reply index version or original binding changed')
        rows = db.execute("SELECT j.*,g.binding FROM jobs j JOIN grants g ON g.id=j.grant_id "
            "WHERE j.accepted=1 AND json_extract(g.binding,'$.owner')=? AND NOT EXISTS("
            "SELECT 1 FROM audit_events a WHERE a.job=j.id AND a.event='reply_indexed')",(owner,)).fetchall()
        for row in rows:
            self._index_reply(db,row,owner,legacy=True)
        finalized = db.execute(
            "SELECT j.*,g.binding FROM jobs j JOIN grants g ON g.id=j.grant_id "
            "WHERE j.accepted=1 AND j.state='done' AND json_extract(g.binding,'$.owner')=? "
            "AND NOT EXISTS(SELECT 1 FROM audit_events a WHERE a.job=j.id AND a.event='reply_indexed' "
            "AND json_extract(a.detail,'$.scope')='finalized_draft_not_verified_customer_delivery')",
            (owner,),
        )
        for row in finalized.fetchall():
            value = strict_loads(row['final_result'])
            if not isinstance(value, dict) or not isinstance(value.get('reply'), str):
                raise JobError('Original finalized draft unavailable for reply history')
            self._index_reply(db, row, owner, legacy=True, complete_reply=value['reply'])

    def _reply_seen(self, db, owner, key, job=''):
        return key is not None and db.execute("SELECT 1 FROM audit_events WHERE event='reply_indexed' "
            "AND json_extract(detail,'$.owner')=? AND json_extract(detail,'$.reply_key')=? "
            "AND job<>? LIMIT 1",(owner,key,job)).fetchone() is not None

    def reply_available(self, owner, reply, *, complete_reply=None):
        from reply_diversity import fingerprint
        if not isinstance(owner,str) or not owner:
            raise JobError('Exact trusted bot owner required')
        if not self.unique_replies_enabled:
            return True
        keys = {fingerprint(reply)}
        if complete_reply is not None:
            keys.add(fingerprint(complete_reply))
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._index_accepted_replies(db,owner)
            return not any(self._reply_seen(db, owner, key) for key in keys)

    def reserve_unique_reply(self, db, row):
        if not self.unique_replies_enabled:
            return
        owner = json.loads(row['binding'])['owner']
        self._index_accepted_replies(db,owner)
        key = self._reply_key(row)
        if self._reply_seen(db,owner,key,row['id']):
            raise JobError('This complete bot reply was already accepted; no duplicate acceptance',
                           check='reply_already_used')
        self._index_reply(db,row,owner,legacy=False)

    def reserve_final_reply(self, job, binding, reply):
        from reply_diversity import fingerprint
        key = fingerprint(reply)
        owner = binding['owner']
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._row(db, job)
            if (row['state'] != 'finalizing' or row['accepted'] != 1
                    or self.clock() >= row['deadline'] or row['binding_hash'] != self._binding(binding)):
                raise JobError('Original finalization is no longer current')
            self._index_accepted_replies(db, owner)
            if self._reply_seen(db, owner, key, job):
                return False
            self._index_reply(db, row, owner, legacy=False, complete_reply=reply)
        return True

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path, timeout=3)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA synchronous=FULL')
            db.execute('PRAGMA busy_timeout=3000')
            with db:
                yield db

    def _event(self, db, job, event, detail=None):
        db.execute('INSERT INTO events(job,event,detail,at) VALUES(?,?,?,?)',
                   (job,event,json.dumps(detail or {},sort_keys=True),self.clock()))
        self._audit(db,job,event,detail or {})

    def _audit(self, db, job, event, detail):
        forbidden = {'authorization','cookie','set-cookie','api_key','access_token','refresh_token',
                     'password','secret','headers','env','identity_proof'}
        def check(value):
            if isinstance(value,dict):
                if any(str(k).casefold() in forbidden for k in value):
                    raise JobError('Secret-bearing structured fields cannot enter the audit')
                for v in value.values():check(v)
            elif isinstance(value,list):
                for v in value:check(v)
        check(detail)
        if not isinstance(event,str) or not re.fullmatch(r'[a-z_]{1,60}',event) or not isinstance(detail,dict):
            raise JobError('Typed audit event required')
        data = json.dumps(detail,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
        if len(data)>2000000:
            raise JobError('Audit detail exceeds private bounded storage')
        previous = db.execute('SELECT event_hash FROM audit_events WHERE job=? ORDER BY sequence DESC LIMIT 1',(job,)).fetchone()
        previous = previous[0] if previous else ''
        at = self.clock()
        checksum = digest(dict(job=job,event=event,detail=json.loads(data),at=at,previous_hash=previous))
        db.execute('INSERT INTO audit_events(job,event,detail,at,previous_hash,event_hash) VALUES(?,?,?,?,?,?)',
                   (job,event,data,at,previous,checksum))

    def audit(self, job, event, detail):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._row(db,job)
            self._audit(db,job,event,detail)

    def audit_read(self, owner, job, *, after=0, limit=100):
        self.status(owner,job)
        if type(after)is not int or after<0 or type(limit)is not int or not 1<=limit<=200:
            raise JobError('Bounded audit cursor required')
        with self.connect() as db:
            rows = list(db.execute('SELECT * FROM audit_events WHERE job=? ORDER BY sequence',(job,)))
        previous = ''
        events = []
        for row in rows:
            detail = json.loads(row['detail'])
            checksum = digest(dict(job=job,event=row['event'],detail=detail,at=row['at'],previous_hash=previous))
            if previous!=row['previous_hash'] or checksum!=row['event_hash']:
                raise JobError('Private audit chain integrity mismatch')
            previous = checksum
            if row['sequence']>after and len(events)<limit:
                events.append(dict(sequence=row['sequence'],event=row['event'],detail=detail,at=row['at'],event_hash=checksum))
        return dict(job_id=job,events=events,chain_valid=True,head_sha256=previous,
                    next_cursor=events[-1]['sequence'] if events else after,
                    model_notes_are_assertions_not_verified_facts=True)

    def _binding(self, value):
        if (not isinstance(value,dict) or set(value) != FIELDS
                or any(not isinstance(v,str) or not v or len(v)>300 for v in value.values())):
            raise JobError('Complete trusted job binding required')
        try:
            models_for(value['profile'])
        except ValueError:
            raise JobError('Unknown exact admitted model profile') from None
        return digest(value)

    def admit(self, binding, *, max_calls, seconds):
        """Trusted controller only. No HTTP/model route calls this method."""
        checksum = self._binding(binding)
        if (type(max_calls) is not int or not 1 <= max_calls <= 20
                or isinstance(seconds,bool) or not isinstance(seconds,(int,float)) or not 0 < seconds <= 300):
            raise JobError('Finite cumulative calls and original wall deadline required')
        grant = uuid.uuid4().hex
        with self.connect() as db:
            db.execute('INSERT INTO grants VALUES(?,?,?,?,?,NULL)',
                       (grant,json.dumps(binding,sort_keys=True),checksum,max_calls,self.clock()+seconds))
        return grant

    def submit(self, binding, grant_id):
        checksum = self._binding(binding)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            grant = db.execute('SELECT * FROM grants WHERE id=?',(grant_id,)).fetchone()
            if not grant:
                raise JobError('No current exact finite admission',check='finite_admission_missing')
            if grant['binding_hash'] != checksum:
                original = strict_loads(grant['binding'])
                raise JobError('Exact finite admission binding changed',check='finite_admission_changed',
                               changed_fields=[key for key in FIELDS if original.get(key)!=binding[key]])
            if grant['deadline'] <= self.clock():
                raise JobError('Original finite admission expired',check='finite_admission_expired')
            if grant['job']:
                return dict(job_id=grant['job'],idempotent=True)
            job = uuid.uuid4().hex
            try:
                self.holds.reserve(job, checksum, grant['deadline'])
            except (PublicationError, OSError) as cause:
                error = JobError('Source admission hold unavailable',check='source_hold_invalid')
                error.source_hold_failure = 'publication' if isinstance(cause,PublicationError) else 'io'
                raise error from None
            db.execute('INSERT INTO jobs(id,grant_id,state,updated) VALUES(?,?,?,?)',
                       (job,grant_id,'queued',self.clock()))
            db.execute('UPDATE grants SET job=? WHERE id=?',(job,grant_id))
            self._event(db,job,'submitted')
        return dict(job_id=job,idempotent=False)

    def missing_admission_error(self, binding):
        """Bounded private diagnosis only; never grants, retries or changes time."""
        checksum = self._binding(binding)
        with self.connect() as db:
            exact = db.execute('SELECT deadline FROM grants WHERE binding_hash=? ORDER BY rowid DESC LIMIT 1',
                               (checksum,)).fetchone()
            if exact and exact['deadline'] <= self.clock():
                return JobError('Original finite admission expired',check='finite_admission_expired')
            rows = db.execute('SELECT binding FROM grants ORDER BY rowid DESC LIMIT 64').fetchall()
        for row in rows:
            original = strict_loads(row['binding'])
            self._binding(original)
            if all(original[key]==binding[key] for key in ('owner','request','chat','principal','operator')):
                fields = [key for key in FIELDS if original[key]!=binding[key]]
                if fields:
                    return JobError('Exact finite admission binding changed',check='finite_admission_changed',
                                    changed_fields=fields)
        return JobError('No trusted finite research admission',check='finite_admission_missing')

    def _row(self, db, job):
        row = db.execute('''SELECT j.*,g.binding,g.binding_hash,g.max_calls,g.deadline
            FROM jobs j JOIN grants g ON g.id=j.grant_id WHERE j.id=?''',(job,)).fetchone()
        if row is None:
            raise JobError('Unknown scoped research job', check='unknown_scoped_job')
        return row

    def _check(self, job, binding, fresh, *, states=('queued','running')):
        checksum = self._binding(binding)
        with self.connect() as db:
            row = dict(self._row(db,job))
        if (checksum != row['binding_hash'] or row['state'] not in states
                or self.clock() >= row['deadline']):
            raise JobError('Research cancelled, stale, expired or outside exact scope')
        try:self.holds.verify(job, checksum, row['deadline'])
        except PublicationError as error:raise JobError('Admitted source publication hold unavailable') from error
        observed = fresh()
        current=self._binding(observed)
        # Fresh identity may briefly wait for a nonce rotation. Cancellation
        # or the original deadline can change during that read-only wait.
        with self.connect() as db:
            row=dict(self._row(db,job))
        if (current!=checksum or row['binding_hash']!=checksum or row['state']not in states
                or self.clock()>=row['deadline']):
            if current != checksum:
                self.audit(job,'context_binding_changed',dict(changed_fields=sorted(
                    key for key in FIELDS if observed.get(key) != binding.get(key))))
            raise JobError('Research changed or expired during fresh identity check')
        try:self.holds.verify(job, checksum, row['deadline'])
        except PublicationError as error:raise JobError('Admitted source publication hold unavailable') from error
        return row

    def status(self, owner, job):
        with self.connect() as db:
            row = self._row(db,job)
            if json.loads(row['binding'])['owner'] != owner:
                raise JobError('Unknown scoped research job', check='unknown_scoped_job')
            steps = [dict(r) for r in db.execute('SELECT step,role,model,state,raw_hash,acknowledged FROM steps WHERE job=? ORDER BY step',(job,))]
            start = db.execute("SELECT at FROM events WHERE job=? AND event='submitted' ORDER BY sequence LIMIT 1",(job,)).fetchone()
        for step in steps:
            step['acknowledged'] = bool(step['acknowledged'])
        stage={'queued':'queued','awaiting_root':'awaiting_review','accepted':'ready',
               'finalizing':'finalizing','done':'ready'}.get(row['state'],'stopped')
        if row['state']=='running':
            if not steps:stage='preparing_context'
            elif steps[-1]['state']=='inflight':
                stage='reviewing' if steps[-1]['role']=='review' else 'generating'
            elif steps[-1]['state']in('raw','acknowledged'):stage='validating'
            else:stage='uncertain'
        end=self.clock() if row['state']in('queued','running','awaiting_root','accepted','finalizing')else row['updated']
        elapsed=None
        if (start and type(start['at'])in(int,float) and type(end)in(int,float)
                and math.isfinite(start['at']) and math.isfinite(end) and end>=start['at']):
            elapsed=int(end-start['at'])
        return dict(job_id=job,state=row['state'],calls_spent=row['calls_spent'],max_calls=row['max_calls'],
                    deadline=row['deadline'],result_sha256=row['result_hash'],steps=steps,
                    progress=dict(stage=stage,elapsed_seconds=elapsed),
                    calls_reserved_before_network=True,
                    unresolved_provider_steps=sum(s['state'] in ('inflight','unknown','format_failed') for s in steps),
                    can_send_or_create=False)

    def cancel(self, owner, job):
        self.status(owner,job)
        with self.connect() as db:
            db.execute("UPDATE jobs SET state='cancelled',updated=? WHERE id=? AND state NOT IN ('done','denied')",(self.clock(),job))
            self._event(db,job,'cancelled')

    def stop(self, owner, job):
        self.status(owner,job)
        with self.connect() as db:
            db.execute("UPDATE jobs SET state='stopped',updated=? WHERE id=? AND state IN ('queued','running','awaiting_root','accepted')",(self.clock(),job))
            self._event(db,job,'control_stopped')

    def stop_series(self, owner, *, except_job=None):
        """Revoke prior grants only. A new assessed case needs new admission."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._stop_series(db,owner,except_job)

    def _stop_series(self, db, owner, except_job):
        for grant in db.execute('SELECT id,binding,job FROM grants').fetchall():
            if json.loads(grant['binding'])['owner']!=owner or except_job is not None and grant['job']==except_job:
                continue
            db.execute('UPDATE grants SET deadline=min(deadline,?) WHERE id=?',(self.clock(),grant['id']))
            if grant['job']:
                db.execute("UPDATE jobs SET state='stopped' WHERE id=? AND state IN ('queued','running','awaiting_root','accepted')",(grant['job'],))
                self._event(db,grant['job'],'series_stopped')

    def worker_present(self, job):
        path = self._file(job,'worker.lock')
        if not path.exists():
            return False
        fd = os.open(path,os.O_RDWR|os.O_NOFOLLOW)
        try:
            try:
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            return False
        finally:
            os.close(fd)

    @contextmanager
    def session_worker(self, job):
        """Hold both ownership and shared provider lock across the whole loop."""
        fd = os.open(self._file(job,'worker.lock'),os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:
            try:
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                raise WorkerBusy('The same durable worker is still active') from None
            with ExitStack() as stack:
                try:
                    stack.enter_context(self.worker(job))
                except JobError:
                    raise WorkerBusy('Shared provider worker is busy; wait for the same job') from None
                self.session.job = job
                try:
                    self.audit(job,'worker_session_started',dict(pid=os.getpid()))
                    yield
                finally:
                    self.session.job = None
        finally:
            os.close(fd)

    @contextmanager
    def worker(self, job):
        """One provider executor, sharing the configured historical lock."""
        with self.connect() as db:
            self._row(db,job)
        self.lock.parent.mkdir(parents=True,exist_ok=True)
        fd = os.open(self.lock,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:
            try:
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                raise JobError('Another provider worker holds the shared lock') from None
            yield
        finally:
            os.close(fd)

    def _file(self, job, suffix):
        if not isinstance(job,str) or len(job)!=32 or any(c not in '0123456789abcdef' for c in job):
            raise JobError('Invalid opaque job identity')
        return self.directory / (job+'-'+suffix)

    def _save(self, path, raw):
        part = path.with_suffix(path.suffix+'.part')
        fd = os.open(part,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        try:
            with os.fdopen(fd,'wb') as out:
                out.write(raw)
                out.flush()
                os.fsync(out.fileno())
            if path.exists():
                raise JobError('Immutable raw already exists')
            os.rename(part,path)
            directory = os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except BaseException:
            # Retain a partial file as evidence; it cannot be parsed/replayed.
            raise

    def save_input(self, job, raw):
        path = self._file(job,'input.json')
        fd = os.open(self._file(job,'input.lock'),os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:
            try:
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                raise WorkerBusy('Original input writer is active; observe the same job') from None
            if path.exists():
                if path.is_symlink() or path.read_bytes()!=raw:
                    raise JobError('Immutable preview input changed')
                return
            with self.connect() as db:
                if self._row(db,job)['calls_spent']:
                    raise JobError('Missing original input after model admission; do not reconstruct')
            part = path.with_suffix('.json.part')
            if part.exists():
                # This lock proves that a prior metadata writer has gone.
                # Preserve its partial bytes; no provider call occurred yet.
                abandoned = self._file(job,'input-abandoned-'+uuid.uuid4().hex+'.part')
                os.rename(part,abandoned)
                self.audit(job,'input_partial_preserved',dict(sha256=hashlib.sha256(abandoned.read_bytes()).hexdigest()))
            self._save(path,raw)
            self.audit(job,'input_fsynced',dict(input_sha256=hashlib.sha256(raw).hexdigest()))
        finally:
            os.close(fd)

    def raw(self, job, step):
        if type(step) is not int or step < 0:
            raise JobError('Invalid step')
        path = self._file(job,str(step)+'.raw')
        if path.is_symlink():
            raise JobError('Raw file identity changed')
        return path.read_bytes()

    def _transport_receipt(self, job, step, row, raw):
        path = self._file(job,str(step)+'.transport.json')
        if row['transport_kind'] is None:
            if path.exists():raise JobError('Unexpected HTTP receipt without its durable kind')
            return None
        if row['transport_kind'] not in ('openai_https_v1','chatgpt_plan_sse_v1') or not row['transport_hash']:
            raise JobError('HTTP receipt identity is incomplete')
        if path.is_symlink() or not path.exists() or path.stat().st_size>4096:
            raise JobError('Required HTTP receipt is missing or changed')
        saved = path.read_bytes()
        if hashlib.sha256(saved).hexdigest()!=row['transport_hash']:
            raise JobError('Saved HTTP receipt changed')
        data = strict_loads(saved)
        if (not isinstance(data,dict) or set(data)!={'schema','metadata','body_sha256'}
                or data['schema']!=1 or data['body_sha256']!=hashlib.sha256(raw).hexdigest()):
            raise JobError('HTTP receipt does not bind original bytes')
        try:
            return validate_kind(row['transport_kind'], data['metadata'])
        except ValueError:
            raise JobError('Saved transport kind/content type mismatch') from None

    def requester(self, job, binding, *, fresh, request, after_raw=None):
        """Inject into ResponsesTransport. Trusted transport returns raw bytes.

        A newly created requester replays persisted steps in order. Only a
        previously unseen next step consumes a call. Unknown inflight steps
        cannot be retried, even after process death or observer timeout.
        """
        counter = 0

        def call(payload, timeout, phase):
            nonlocal counter
            row = self._check(job,binding,fresh)
            if isinstance(timeout,bool) or not isinstance(timeout,(int,float)) or not 0 < timeout <= 300:
                raise JobError('Invalid provider deadline')
            try:
                instructions = json.loads(payload['instructions'])
                role = instructions['role']
                model = models_for(binding['profile'])[role]
            except (ValueError,TypeError,KeyError):
                raise JobError('Invalid bound model stage') from None
            if payload.get('model') != model or instructions.get('profile') != binding['profile']:
                raise JobError('Unadmitted model/profile')
            checksum = digest(payload)
            step = counter
            counter += 1
            path = self._file(job,str(step)+'.raw')
            prepared = None
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                old = db.execute('SELECT * FROM steps WHERE job=? AND step=?',(job,step)).fetchone()
                if old:
                    if old['request_hash'] != checksum or old['state'] not in ('inflight','raw','acknowledged'):
                        raise JobError('Conflicting or failed persisted model step')
                else:
                    live = self._row(db,job)
                    if live['state'] not in ('queued','running') or live['calls_spent'] >= live['max_calls']:
                        raise JobError('Cumulative model call budget exhausted')
                    if db.execute('SELECT 1 FROM steps WHERE job=? AND request_hash=?',(job,checksum)).fetchone():
                        raise JobError('Duplicate model payload; no lucky regeneration')
                    prepare = getattr(request,'prepare',None)
                    if callable(prepare):
                        try:prepared = prepare(payload)
                        except RequestNotStarted:
                            raise JobNotStarted('Trusted transport preflight stopped before any request journal or provider attempt') from None
                        body = json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
                        if (not callable(prepared) or getattr(prepared,'transport_kind',None) not in ('openai_https_v1','chatgpt_plan_sse_v1')
                                or prepared.body_sha256!=hashlib.sha256(body).hexdigest() or digest(payload)!=checksum):
                            raise JobNotStarted('Prepared transport body differs from the exact grant')
                    db.execute("INSERT INTO steps(job,step,request_hash,role,model,state,transport_kind) VALUES(?,?,?,?,?,'inflight',?)",
                               (job,step,checksum,role,model,prepared.transport_kind if prepared else None))
                    db.execute("UPDATE jobs SET state='running',calls_spent=calls_spent+1,updated=? WHERE id=?",(self.clock(),job))
                    self._event(db,job,'provider_reserved',dict(step=step,request_hash=checksum,role=role,model=model))
            if old:
                if not path.exists():
                    raise JobError('Provider outcome unknown; read same job, never regenerate')
                raw = self.raw(job,step)
                phase['receipt'] = True
                if old['raw_hash'] and hashlib.sha256(raw).hexdigest() != old['raw_hash']:
                    raise JobError('Saved provider bytes changed')
                metadata = self._transport_receipt(job,step,old,raw)
            else:
                self._check(job,binding,fresh)
                # Canonical body only. The trusted HTTP transport adds its
                # credentials later; headers/keys never enter this file.
                request_raw = json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
                self._save(self._file(job,str(step)+'.request.json'),request_raw)
                self.audit(job,'provider_request_saved',dict(step=step,request_hash=checksum,
                    representation='canonical model request before transport; not observed upstream HTTP bytes'))
                # Fsync and audit can outlive cancellation, an identity/source
                # change or the original deadline. A reservation is not a
                # provider attempt: recheck after that I/O and before transport.
                try:
                    row = self._check(job,binding,fresh)
                except Exception:
                    with self.connect() as db:
                        db.execute("UPDATE steps SET state='not_started' WHERE job=? AND step=?",(job,step))
                        self._event(db,job,'provider_not_started',dict(step=step,reason='pretransport_context_changed'))
                    raise JobNotStarted('Context or admission changed before provider transport; no retry') from None
                try:
                    phase['started'] = True
                    raw = (prepared(min(timeout,row['deadline']-self.clock())) if prepared else
                           request(payload,min(timeout,row['deadline']-self.clock())))
                    if not isinstance(raw,bytes) or not raw or len(raw)>10*1024*1024:
                        raise JobError('Provider must return bounded original bytes')
                    metadata = raw.metadata if isinstance(raw,HTTPReceipt) else None
                    if prepared and metadata is None:
                        raise JobError('Prepared HTTP response lacks original transport evidence')
                    if metadata is not None:
                        kind = raw.transport_kind
                        if prepared and kind != prepared.transport_kind:
                            raise JobError('Prepared transport/receipt identity changed')
                        metadata = validate_kind(kind, metadata)
                        meta_raw = json.dumps(dict(schema=1,metadata=metadata,body_sha256=hashlib.sha256(raw).hexdigest()),
                                              sort_keys=True,separators=(',',':')).encode()
                        with self.connect() as db:
                            db.execute("UPDATE steps SET transport_kind=? WHERE job=? AND step=?",(kind,job,step))
                        self._save(self._file(job,str(step)+'.transport.json'),meta_raw)
                        with self.connect() as db:
                            db.execute('UPDATE steps SET transport_hash=? WHERE job=? AND step=?',
                                       (hashlib.sha256(meta_raw).hexdigest(),job,step))
                            self._event(db,job,'http_receipt_fsynced',dict(step=step,**metadata))
                    self._save(path,raw)
                except RequestNotStarted:
                    phase['started'] = False
                    with self.connect() as db:
                        db.execute("UPDATE steps SET state='not_started' WHERE job=? AND step=?",(job,step))
                        self._event(db,job,'provider_not_started',dict(step=step))
                    raise JobNotStarted('Transport stopped before provider body write; no retry') from None
                except Exception as error:
                    category = error.category if isinstance(error,HTTPFailure) else 'unknown'
                    if isinstance(error,HTTPFailure) and error.partial and len(error.partial)<=10*1024*1024:
                        try:
                            self._save(self._file(job,str(step)+'.partial.raw'),error.partial)
                            self.audit(job,'partial_response_fsynced',dict(step=step,sha256=hashlib.sha256(error.partial).hexdigest(),
                                complete=False,category=category))
                        except (OSError,JobError):
                            self.audit(job,'partial_response_write_failed',dict(step=step))
                    with self.connect() as db:
                        db.execute("UPDATE steps SET state='unknown' WHERE job=? AND step=?",(job,step))
                        self._event(db,job,'provider_outcome_unknown',dict(step=step,category=category))
                        if category=='credential_reflected':
                            self._event(db,job,'provider_security_stop',dict(step=step,raw_suppressed=True))
                    raise JobError('Provider outcome unknown; no retry') from None
            raw_hash = hashlib.sha256(raw).hexdigest()
            with self.connect() as db:
                db.execute("UPDATE steps SET state='raw',raw_hash=? WHERE job=? AND step=?",(raw_hash,job,step))
                self._event(db,job,'raw_fsynced',dict(step=step,raw_hash=raw_hash,recovered=bool(old)))
            try:
                if after_raw:
                    after_raw(path)
                self._check(job,binding,fresh)
            except Exception as error:
                if metadata is not None:
                    raise SavedReceiptStopped(error,raw=raw,metadata=metadata,job=job,step=step) from None
                raise
            with self.connect() as db:
                db.execute("UPDATE steps SET state='acknowledged',acknowledged=1 WHERE job=? AND step=?",(job,step))
                self._event(db,job,'raw_receipt_ack',dict(step=step,raw_hash=raw_hash))
            try:
                response = (research_subscription.decode(raw)
                            if metadata is not None and metadata['content_type']=='event_stream'
                            else strict_loads(raw))
            except (ValueError,UnicodeError):
                with self.connect() as db:
                    db.execute("UPDATE steps SET state='format_failed' WHERE job=? AND step=?",(job,step))
                raise JobError('Invalid original provider JSON; no repair') from None
            if not isinstance(response,dict):
                raise JobError('Provider JSON must be an object')
            return ProviderResult(response,metadata) if metadata is not None else response
        def locked(payload, timeout):
            phase = {}
            try:
                if getattr(self.session,'job',None)==job:
                    return call(payload,timeout,phase)
                with self.worker(job):
                    return call(payload,timeout,phase)
            except JobError as error:
                if not phase.get('started') and not phase.get('receipt'):
                    raise JobNotStarted(str(error)) from None
                raise
        return locked

    def propose(self, job, binding, result, *, fresh):
        self._check(job,binding,fresh)
        raw = json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
        path = self._file(job,'result.json')
        if path.exists():
            if path.is_symlink() or path.read_bytes()!=raw:
                raise JobError('Immutable complete candidate changed during recovery')
        else:
            self._save(path,raw)
        checksum = hashlib.sha256(raw).hexdigest()
        with self.connect() as db:
            db.execute("UPDATE jobs SET state=?,result_hash=?,updated=? WHERE id=? AND state IN ('queued','running')",
                       ('awaiting_root' if result.get('approved') is True else 'rejected',checksum,self.clock(),job))
            self._event(db,job,'candidate_saved',dict(result_hash=checksum))
        return dict(job_id=job,result_sha256=checksum,requires_root=True,can_send_or_create=False)

    def decide(self, job, expected_hash, *, accepted, reviewer):
        if type(accepted) is not bool or not isinstance(reviewer,str) or not reviewer.strip():
            raise JobError('Exact manual root decision required')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._row(db,job)
            if row['state'] != 'awaiting_root' or row['result_hash'] != expected_hash:
                raise JobError('Root decision does not match the saved complete candidate')
            if accepted:
                self.reserve_unique_reply(db,row)
            db.execute('UPDATE jobs SET accepted=?,reviewer=?,state=?,updated=? WHERE id=?',
                       (int(accepted),reviewer,'accepted' if accepted else 'denied',self.clock(),job))
            self._event(db,job,'root_accepted' if accepted else 'root_denied',dict(result_hash=expected_hash,reviewer=reviewer))
            owner = json.loads(row['binding'])['owner']
            if not accepted:
                self._stop_series(db,owner,job)

    def finalize(self, job, binding, *, fresh, finish):
        self._check(job,binding,fresh,states=('accepted',))
        raw = self._file(job,'result.json').read_bytes()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._row(db,job)
            if (row['state'] != 'accepted' or row['accepted'] != 1
                    or hashlib.sha256(raw).hexdigest() != row['result_hash']):
                raise JobError('Candidate or root decision changed')
            db.execute("UPDATE jobs SET state='finalizing',updated=? WHERE id=?",(self.clock(),job))
            self._event(db,job,'legacy_finalize_started')
        result = json.loads(raw)
        final = finish(result)
        self._check(job,binding,fresh,states=('finalizing',))
        self._complete(job,final)
        return final

    def _complete(self, job, final):
        with self.connect() as db:
            changed = db.execute("UPDATE jobs SET state='done',final_result=?,updated=? WHERE id=? AND state='finalizing'",
                                 (json.dumps(final,ensure_ascii=False),self.clock(),job)).rowcount
            if changed != 1:
                raise JobError('Finalize was cancelled or superseded; no draft returned')
            self._event(db,job,'legacy_finalize_result_saved')

    def reconcile(self, job, binding, *, fresh, read):
        self._check(job,binding,fresh,states=('finalizing',))
        saved = read()  # Trusted read-only lookup of the SAME owner/request.
        if not isinstance(saved,dict) or saved.get('done') is not True or not isinstance(saved.get('result'),dict):
            raise JobError('Finalize outcome remains unknown; no second finalize')
        self._check(job,binding,fresh,states=('finalizing',))
        self._complete(job,saved['result'])
        return saved['result']
