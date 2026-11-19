"""Opt-in authenticated preview → research job → root gate → legacy finalize.

Construction needs trusted source/transport factories. No browser request can
configure a provider, mint a grant, approve its own result or send anything.
"""
import copy
import hashlib
import json
import sqlite3
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import assistant_policy as policy
import experience_runtime
import personal_assistant
import personal_workflow
from api_costs import UsageLedger
from experienced_dialogues import digest
from research_jobs import Jobs, JobError, WorkerBusy, FIELDS
from research_memory import QuickMemory
from research_openai import ResponsesTransport, strict_loads
from research_pipeline import Pipeline, pack_context
import research_media
import research_proposals
from research_identity import ObserverProofs

CONTROL_ACTIONS = {'research_start','research_status','research_cancel','research_finalize','research_audit'}
CONTROL_CHECKS = {'identity_unverified','preview_not_current','runtime_or_profile_changed',
    'conversation_changed','conversation_held','policy_or_experience_changed','actor_changed',
    'client_group_changed','auto_session_not_live','source_revision_changed','generation_changed',
    'pending_observer_missing','unknown_scoped_job','job_request_mismatch','job_chat_mismatch','exact_job_required','source_map_changed','map_reload_required'}
CONTROL_CHECKS |= {'auto_session_changed','auto_prefix_prior_attempt','auto_allowance_exhausted','auto_session_blocked'}
CONTROL_CHECKS |= {'finite_admission_missing','finite_admission_changed','finite_admission_expired','source_hold_invalid'}


class PendingSourceChanged(JobError):
    """An authenticated same-chat revision changed before durable submission."""
    def __init__(self, prepared):
        super().__init__('Unsubmitted source revision changed')
        self.prepared = prepared


class ResearchService:
    def __init__(self, directory, *, shared_lock, corpus_factory, request, identity=None,
                 schedule=None, profile='sol_only', media_resolver=None, proposal_enabled=False,
                 native_context=None, funding='api', intake_form_enabled=False,
                 owner_auto_enabled=False, auto_session_call_limit=128, native_authority=None,
                 native_crm_only_enabled=False, unique_replies_enabled=False, price_wording_enabled=False):
        if not callable(corpus_factory) or not callable(request):
            raise JobError('Explicit trusted source and raw transport factories required')
        if native_authority is not None:
            from native_authority import NativeAuthority
            if not isinstance(native_authority, NativeAuthority) or identity is not None or native_context is None:
                raise JobError('Separate trusted native authority and current source required')
            identity=native_authority.identity
        self.native_authority=native_authority
        self.jobs = Jobs(directory,shared_lock=shared_lock,unique_replies_enabled=unique_replies_enabled)
        self.unique_replies_enabled = self.jobs.unique_replies_enabled
        self.observers = ObserverProofs(lambda:self.jobs.clock())
        self.corpus_factory, self.request = corpus_factory, request
        self.identity = identity
        self.profile = profile
        if funding not in ('api','chatgpt_plan'):
            raise JobError('Trusted funding selection required; no fallback')
        self.funding = funding
        self.native_context = native_context
        if (type(owner_auto_enabled)is not bool or type(auto_session_call_limit)is not int
                or not 4<=auto_session_call_limit<=4096
                or owner_auto_enabled and (native_context is None or profile!='sol_only' or funding!='api')):
            raise JobError('Trusted finite owner-auto configuration and native identity source required')
        self.owner_auto_enabled=owner_auto_enabled
        self.auto_session_call_limit=auto_session_call_limit
        self.auto_mutex=threading.Lock()
        with self.jobs.connect()as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS auto_sessions(
                  tag TEXT PRIMARY KEY,owner TEXT NOT NULL,call_limit INTEGER NOT NULL,
                  reserved INTEGER NOT NULL DEFAULT 0,blocked INTEGER NOT NULL DEFAULT 0,
                  consecutive_failures INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS auto_admissions(
                  prefix TEXT PRIMARY KEY,binding_hash TEXT NOT NULL,tag TEXT NOT NULL,
                  grant_id TEXT UNIQUE,created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS auto_native_outcomes(
                  job TEXT PRIMARY KEY,valid INTEGER NOT NULL,at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS auto_source_turns(
                  source_key TEXT PRIMARY KEY,prefix TEXT UNIQUE NOT NULL,
                  chat TEXT NOT NULL,turn_hash TEXT NOT NULL,purpose TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS auto_sessions_owner ON auto_sessions(owner);
                CREATE INDEX IF NOT EXISTS grants_chat_attempt ON grants(json_extract(binding,'$.chat'));
                CREATE INDEX IF NOT EXISTS grants_source_attempt ON grants(
                  json_extract(binding,'$.principal'),json_extract(binding,'$.operator'),
                  json_extract(binding,'$.chat'),json_extract(binding,'$.revision'));
            ''')
        self.media_resolver = native_context.resolver if native_context is not None else media_resolver
        if type(proposal_enabled) is not bool:
            raise JobError('Proposal mode requires an explicit trusted boolean')
        self.proposal_enabled = proposal_enabled
        if (type(price_wording_enabled) is not bool or price_wording_enabled
                and (not proposal_enabled or profile != 'sol_only')):
            raise JobError('Price wording requires an explicit trusted Sol proposal capability')
        self.price_wording_enabled = price_wording_enabled
        if type(intake_form_enabled)is not bool:raise JobError('Explicit form capability required')
        self.intake_form_enabled=intake_form_enabled
        if (type(native_crm_only_enabled)is not bool or native_crm_only_enabled
                and (not owner_auto_enabled or not intake_form_enabled or native_context is None)):
            raise JobError('CRM-only requires explicit native owner-auto and form capabilities')
        self.native_crm_only_enabled=native_crm_only_enabled
        self.code_version = self._runtime_version()
        self.startup_map_content = None
        self.startup_map_version = self._map_version()
        self.ledger = UsageLedger(Path(directory)/'usage.sqlite3')
        self.memory = QuickMemory(Path(directory)/'quick.sqlite3')
        self.pool = ThreadPoolExecutor(max_workers=1,thread_name_prefix='leadbot-research') if schedule is None else None
        self.schedule = schedule or self.pool.submit
        self.scheduled = set()
        self.mutex = threading.Lock()
        self.pending_admissions = {}
        self.control_failure_epoch = 0

    def owner_allowed(self, owner):
        # A native namespace is process-derived and still needs fresh Run
        # authority at ingress. It cannot relax a browser's personal owner.
        return (owner == self.native_authority.owner if self.native_authority is not None
                else personal_assistant.owner_allowed(owner))

    def auto_preview_binding(self,app,body,identity=None):
        """Private launch fence, never a model input or browser-provided flag."""
        if not self.owner_auto_enabled:
            return None
        identity=identity or self._identity(app,body)
        if self.native_authority is not None:
            return self.native_authority.auto_binding(body)
        owner=str(body.get('owner')or'')
        lease=personal_assistant.session(app.store,owner,'personal_status',body)
        if lease.get('code')=='operator_identity':
            raise JobError('Fresh operator identity required',check='identity_unverified')
        if not personal_workflow.enabled(lease):
            raise JobError('Owner auto session is not live',check='auto_session_changed')
        with app.store.connect()as db:
            row=db.execute('SELECT sid,principal,operator,mode_epoch,expires,execution_mode,policy_ack FROM personal_sessions WHERE scope=?',
                (digest(owner),)).fetchone()
        if (not row or row['sid']!=body.get('browser_session') or row['principal']!=identity['principal_id']
                or row['operator']!=identity['operator_id'] or row['expires']<=self.jobs.clock()
                or row['execution_mode']!='auto' or row['policy_ack']!=policy.VERSION):
            raise JobError('Exact authenticated owner launch required',check='auto_session_changed')
        return digest([owner,row['sid'],row['mode_epoch'],row['principal'],row['operator'],policy.VERSION])

    def _automatic_grant(self,app,body,binding,payload):
        if not self.owner_auto_enabled or payload['wording_mode']!='neural_auto':
            return None
        tag=self.auto_preview_binding(app,body)
        if payload.get('auto_session_binding')!=tag:
            raise JobError('Preview belongs to another owner launch',check='auto_session_changed')
        # A new cache/publication/runtime/session is not a new client turn.
        # Only a genuinely changed source revision or a different purpose can
        # authorize another automatic attempt; an old unknown needs review.
        prefix=digest([binding[k]for k in ('owner','chat','revision','principal','operator')]
            +[payload.get('research_purpose','reply')])
        purpose=payload.get('research_purpose','reply')
        turn=self._source_turn(payload)
        source_key=digest([binding['chat'],purpose,turn])
        checksum=digest(binding)
        with self.auto_mutex:
            with self.jobs.connect()as db:
                db.execute('BEGIN IMMEDIATE')
                previous=db.execute('SELECT *FROM auto_admissions WHERE prefix=?',(prefix,)).fetchone()
                original=db.execute('SELECT prefix FROM auto_source_turns WHERE source_key=?',
                                    (source_key,)).fetchone()
                if original and original['prefix']!=prefix:
                    raise JobError('Original customer turn already reserved',check='auto_prefix_prior_attempt')
                # Existing namespaces are metadata, not new client turns. A
                # transport migration must also detect a reservation that
                # crashed before it acquired a grant/job ID.
                purpose=payload.get('research_purpose','reply')
                for prior_owner in db.execute('SELECT DISTINCT owner FROM auto_sessions'):
                    candidates=[purpose] + ([None] if purpose=='reply' else [])
                    for old_purpose in candidates:
                        prior_prefix=digest([prior_owner['owner'],binding['chat'],binding['revision'],
                            binding['principal'],binding['operator'],old_purpose])
                        if prior_prefix!=prefix and db.execute('SELECT 1 FROM auto_admissions WHERE prefix=?',
                                                               (prior_prefix,)).fetchone():
                            raise JobError('Prior source attempt belongs to another transport',check='auto_prefix_prior_attempt')
                if previous:
                    if previous['binding_hash']!=checksum or previous['tag']!=tag or not previous['grant_id']:
                        raise JobError('Prior attempt cannot be regenerated',check='auto_prefix_prior_attempt')
                    db.execute('INSERT OR IGNORE INTO auto_source_turns VALUES(?,?,?,?,?)',
                               (source_key,prefix,binding['chat'],turn,purpose))
                    return previous['grant_id']
                manual=db.execute('SELECT id FROM grants WHERE binding_hash=? ORDER BY rowid DESC LIMIT 1',(checksum,)).fetchone()
                if manual:
                    return manual['id']  # It keeps its manual Root gate; no auto journal entry.
                self._legacy_source_attempts(app,db,binding,turn,purpose)
                old_grants=db.execute("SELECT id,binding FROM grants WHERE json_extract(binding,'$.principal')=? "
                    "AND json_extract(binding,'$.operator')=? AND json_extract(binding,'$.chat')=? "
                    "AND json_extract(binding,'$.revision')=? AND id NOT IN "
                    "(SELECT grant_id FROM auto_admissions WHERE grant_id IS NOT NULL)",
                    (binding['principal'],binding['operator'],binding['chat'],binding['revision'])).fetchall()
                for old in old_grants:
                    prior_binding=json.loads(old['binding'])
                    with app.store.connect()as metadata:
                        prior=metadata.execute("SELECT result IS NOT NULL AS present,"
                            "json_extract(result,'$.research_purpose') AS purpose FROM requests WHERE scope=? AND rid=?",
                            ('assistant:'+digest(prior_binding['owner']),prior_binding['request'])).fetchone()
                    if prior is None or not prior['present'] or prior['purpose'] is None or prior['purpose']==purpose:
                        raise JobError('Prior exact source admission cannot be regenerated',check='auto_prefix_prior_attempt')
                db.execute('INSERT OR IGNORE INTO auto_sessions(tag,owner,call_limit)VALUES(?,?,?)',
                    (tag,binding['owner'],self.auto_session_call_limit))
                session=db.execute('SELECT *FROM auto_sessions WHERE tag=?',(tag,)).fetchone()
                if session['blocked']:
                    raise JobError('Owner launch stopped after a control failure',check='auto_session_blocked')
                # Grant the deadline only when the preceding job has finished.
                # Polling another CID never consumes its time or call allowance.
                busy=db.execute("SELECT 1 FROM grants g LEFT JOIN jobs j ON j.id=g.job WHERE g.deadline>? AND (g.job IS NULL OR j.state IN ('queued','running','awaiting_root','accepted','finalizing')) LIMIT 1",
                    (self.jobs.clock(),)).fetchone()
                if busy:
                    return False
                calls=2 if payload.get('research_purpose')in('intake_form_v1','visual_observation_v1')else 4
                if session['reserved']+calls>session['call_limit']:
                    raise JobError('Finite allowance of this owner launch exhausted',check='auto_allowance_exhausted')
                db.execute('INSERT INTO auto_admissions VALUES(?,?,?,NULL,?)',(prefix,checksum,tag,self.jobs.clock()))
                db.execute('INSERT INTO auto_source_turns VALUES(?,?,?,?,?)',
                           (source_key,prefix,binding['chat'],turn,purpose))
                db.execute('UPDATE auto_sessions SET reserved=reserved+? WHERE tag=?',(calls,tag))
            # Reservation is durable BEFORE creating/exposing a grant. A crash
            # here remains indeterminate; polling/restart cannot refill it.
            grant=self.jobs.admit(binding,max_calls=calls,seconds=300)
            with self.jobs.connect()as db:
                db.execute('UPDATE auto_admissions SET grant_id=? WHERE prefix=? AND grant_id IS NULL',(grant,prefix))
            return grant

    @staticmethod
    def _source_turn(payload):
        """A no-regeneration fence, never currentness, consent or action authority.

        Client message IDs/content/roles/delivery/ASR come from the complete
        original native task. Derived policy annotations, staff/system events,
        UI hints, dates and publication versions cannot refill an attempt.
        Missing or changed media identity is deliberately not a new allowance;
        full original-media/source checks remain mandatory before any use.
        """
        try:
            rows=json.loads(payload['model_task']['task'])['conversation']
            if not isinstance(rows,list):raise ValueError('Original timeline required')
            fields=('id','direction','sender_type','speaker_role','body','voice_transcript',
                    'voice_transcript_status','delivery_status','attachment_count')
            clients=[{k:row.get(k,'') for k in fields} for row in rows
                     if isinstance(row,dict) and row.get('speaker_role')=='client'
                     and row.get('direction')=='in']
            ids=[row['id'] for row in clients]
            if not clients or any(not isinstance(mid,str) or not mid for mid in ids) or len(ids)!=len(set(ids)):
                raise ValueError('Exact original client message identities required')
            return digest(clients)
        except (ValueError,TypeError,KeyError):
            raise JobError('Original customer turn cannot be established',check='source_revision_changed') from None

    def _legacy_source_attempts(self,app,db,binding,turn,purpose):
        # Metadata scope first. No directory scan, history export or unrelated
        # client's input is read, including during transport/release migration.
        rows=db.execute("SELECT id,binding,job FROM grants WHERE json_extract(binding,'$.chat')=?",
                        (binding['chat'],)).fetchall()
        for row in rows:
            indexed=db.execute('SELECT t.turn_hash,t.purpose FROM auto_source_turns t '
                'JOIN auto_admissions a ON a.prefix=t.prefix WHERE a.grant_id=?',(row['id'],)).fetchone()
            if indexed:
                if indexed['purpose']==purpose and indexed['turn_hash']==turn:
                    raise JobError('Prior exact customer turn',check='auto_prefix_prior_attempt')
                continue
            prior_binding=json.loads(row['binding'])
            if any(prior_binding.get(k)!=binding[k] for k in ('chat','principal','operator')):
                raise JobError('Prior actor attempt needs original review',check='auto_prefix_prior_attempt')
            prior=None
            if row['job']:
                self.jobs.status(prior_binding['owner'],row['job'])  # Owner before private input.
                path=self.jobs._file(row['job'],'input.json')
                if path.exists():
                    saved=json.loads(path.read_bytes())
                    if saved.get('owner')==prior_binding['owner']:
                        prior=saved.get('payload')
            else:
                _,prior=app.store.request('assistant:'+digest(prior_binding['owner']),prior_binding['request'])
            if (not isinstance(prior,dict) or prior.get('chat_id')!=binding['chat']
                    or prior.get('operator_binding')!=[binding['principal'],binding['operator']]):
                raise JobError('Prior original unavailable',check='auto_prefix_prior_attempt')
            old_purpose=prior.get('research_purpose','reply')
            if old_purpose==purpose:
                try:
                    old_turn=self._source_turn(prior)
                except JobError:
                    raise JobError('Prior original identity unavailable',check='auto_prefix_prior_attempt') from None
                if old_turn==turn:
                    raise JobError('Prior source remains the same across releases',check='auto_prefix_prior_attempt')
        # An opaque pre-migration reservation with no grant and no source index
        # cannot be assigned to a new turn safely. Cutover must reconcile such
        # control failures; never reconstruct/refill the lost reservation.
        if db.execute('SELECT 1 FROM auto_admissions a LEFT JOIN auto_source_turns t '
                      'ON t.prefix=a.prefix WHERE a.grant_id IS NULL AND t.prefix IS NULL LIMIT 1').fetchone():
            raise JobError('Legacy reservation has no original source binding',check='auto_prefix_prior_attempt')

    def _automatic_job(self,job):
        with self.jobs.connect()as db:
            return db.execute('SELECT 1 FROM auto_admissions a JOIN jobs j ON j.grant_id=a.grant_id WHERE j.id=?',
                              (job,)).fetchone()is not None

    def _automatic_accept(self,job,binding,*,fresh):
        with self.jobs.connect()as db:
            row=db.execute('SELECT a.tag FROM auto_admissions a JOIN jobs j ON j.grant_id=a.grant_id WHERE j.id=?',(job,)).fetchone()
        if row is None:
            return False
        if not self.owner_auto_enabled:
            raise JobError('Automatic API configuration revoked')
        self.jobs._check(job,binding,fresh,states=('awaiting_root',))
        with self.jobs.connect()as db:
            db.execute('BEGIN IMMEDIATE')
            saved=self.jobs._row(db,job)
            admission=db.execute('SELECT a.*,s.blocked FROM auto_admissions a JOIN auto_sessions s ON s.tag=a.tag WHERE a.grant_id=?',
                (saved['grant_id'],)).fetchone()
            raw=self.jobs._file(job,'result.json').read_bytes()
            if (not admission or admission['blocked'] or admission['binding_hash']!=digest(binding)
                    or saved['state']!='awaiting_root' or hashlib.sha256(raw).hexdigest()!=saved['result_hash']
                    or json.loads(raw).get('approved')is not True):
                raise JobError('Original separately reviewed automatic candidate is not current')
            self.jobs.reserve_unique_reply(db,saved)
            db.execute("UPDATE jobs SET accepted=1,reviewer='automatic-separate-sol-review',state='accepted',updated=? WHERE id=?",
                (self.jobs.clock(),job))
            self.jobs._event(db,job,'machine_accepted',dict(result_hash=saved['result_hash'],
                provenance='trusted_owner_launch_and_separate_sol_review',manual_root=False,
                native_finalize_still_required=True,customer_action=False,historical_credit=0))
        return True

    def _automatic_native_outcome(self,job,value):
        """The reviewer is not the final native validator; count its outcome once."""
        valid=value.get('ok')is True and not value.get('validation')
        with self.jobs.connect()as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT a.tag,s.consecutive_failures,s.blocked FROM auto_admissions a JOIN jobs j ON j.grant_id=a.grant_id JOIN auto_sessions s ON s.tag=a.tag WHERE j.id=?',
                (job,)).fetchone()
            if row is None:
                return False
            previous=db.execute('SELECT valid FROM auto_native_outcomes WHERE job=?',(job,)).fetchone()
            if previous:
                if bool(previous['valid'])!=valid:
                    raise JobError('Original native outcome changed during recovery')
                return bool(row['blocked'])
            db.execute('INSERT INTO auto_native_outcomes VALUES(?,?,?)',(job,int(valid),self.jobs.clock()))
            failures=0 if valid else row['consecutive_failures']+1
            blocked=bool(row['blocked'] or failures>=2)
            db.execute('UPDATE auto_sessions SET consecutive_failures=?,blocked=? WHERE tag=?',(failures,int(blocked),row['tag']))
            self.jobs._event(db,job,'machine_native_validated',dict(valid=valid,manual_root=False,
                validation_codes=value.get('validation')or[],historical_credit=0,customer_action=False))
            return blocked

    def _automatic_failure(self,job,*,hard):
        with self.jobs.connect()as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT a.tag,s.consecutive_failures FROM auto_admissions a JOIN jobs j ON j.grant_id=a.grant_id JOIN auto_sessions s ON s.tag=a.tag WHERE j.id=?',
                (job,)).fetchone()
            if row is None:
                return True  # Existing manual Root series stop contract.
            failures=row['consecutive_failures']+1
            blocked=hard or failures>=2
            db.execute('UPDATE auto_sessions SET consecutive_failures=?,blocked=max(blocked,?) WHERE tag=?',
                (failures,int(blocked),row['tag']))
            return blocked

    def automatic_allowance(self,app,body,session):
        result=dict(available=self.owner_auto_enabled,active=False,limit=self.auto_session_call_limit,
            reserved_calls=None,remaining_calls=None,blocked=False,scope='this_owner_launch',actual_cost=False)
        if not self.owner_auto_enabled or (self.native_authority is None and not personal_workflow.enabled(session)):
            return result
        tag=self.auto_preview_binding(app,body)
        with self.jobs.connect()as db:
            row=db.execute('SELECT *FROM auto_sessions WHERE tag=?',(tag,)).fetchone()
        limit=row['call_limit'] if row else self.auto_session_call_limit
        reserved=row['reserved'] if row else 0
        return dict(result,active=True,limit=limit,reserved_calls=reserved,remaining_calls=limit-reserved,
            blocked=bool(row and row['blocked']))

    def _runtime_version(self):
        directory = Path(__file__).parent
        names = ('research_workflow.py','research_jobs.py','research_pipeline.py','research_openai.py','research_memory.py','research_publication.py',
                 'api_costs.py','research_media.py','research_http.py','research_receipts.py','research_startup.py','research_proposals.py','research_identity.py',
                 'research_sources.py','research_server.py','research_cache.py','research_subscription.py','research_vision.py','research_form.py','research_control.py',
                 'reply_diversity.py','research_price_wording.py','research_price_components.py',
                 'source_protocol.py','native_sources.py','native_authority.py','native_execution.py','native_execution_protocol.py','source_protection.py','native_context.py',
                 'native_exporter.py','research_history.py','research_index.py',
                 'extension_assistant.py','assistant_store.py','assistant_policy.py','contact_facts.py',
                 'qualification_state.py','assistant_prices.py','assistant_catalog.py','personal_assistant.py',
                 'personal_workflow.py','native_workflow.py','operator_identity.py','personal_media.py','dialogue_lifecycle.py',
                 'experience_runtime.py','experience_memory.py','experienced_dialogues.py','policy_registry.json')
        return digest([(name,hashlib.sha256((directory/name).read_bytes()).hexdigest()) for name in names])

    def _map_version(self):
        raw=Path(policy.__file__).with_name('filial_zones.json').read_bytes()
        content=json.loads(raw)
        content.pop('снято',None)
        # territory.zones retains parsed geometry until process restart. A
        # metadata-only update may bind a fresh task, but new geometry/rules
        # must not be called active while the old parsed map is still cached.
        fingerprint=digest(content)
        if self.startup_map_content is None:self.startup_map_content=fingerprint
        elif self.startup_map_content!=fingerprint:
            raise JobError('Changed map content requires a fresh runtime',check='map_reload_required')
        return hashlib.sha256(raw).hexdigest()  # Includes the exact date bytes.

    def _identity(self, app, body):
        value = (self.identity(body) if self.identity else
                 personal_assistant.operator_identity.verify(app.store,str(body.get('owner')or''),body,self.jobs.clock()))
        if not isinstance(value,dict) or not value.get('principal_id') or not value.get('operator_id'):
            raise JobError('Fresh operator identity required', check='identity_unverified')
        return value

    def prepare_source(self, app, body):
        """Fresh current source before preview/observation, no provider grant."""
        if self.native_context is None:
            return body
        identity=self._identity(app,body)
        result,header,actor=self.native_context.prepare(body,identity)
        result=self._checked_visual_cache(app,result,header,actor)
        fresh=self._identity(app,body)
        if [fresh['principal_id'],fresh['operator_id']] != [identity['principal_id'],identity['operator_id']]:
            raise JobError('Native actor changed during current source observation')
        return result

    def _checked_visual_cache(self,app,body,header,actor):
        import research_vision
        result=dict(body,ctx=dict(body['ctx']))
        result['ctx'].pop('_native_visual_checks',None)
        loader=getattr(self.native_context,'image_digest',None)
        if callable(loader):
            result['ctx']['_native_visual_checks']=research_vision.verify_cached(app.store,'assistant:'+digest(str(body['owner'])),
                body['ctx'],header,lambda descriptor:loader(header,actor,descriptor))
        return result

    def _prepared(self, app, body, job=None, *, diagnostics=None):
        owner = str(body.get('owner')or'')
        scope = 'assistant:'+digest(owner)
        rid = str(body.get('request_id')or'')
        status, payload = app.store.request(scope,rid)
        if job:
            self.jobs.status(owner,job)  # Owner check BEFORE any private input is read.
            path = self.jobs._file(job,'input.json')
            if path.exists():
                saved = json.loads(path.read_bytes())
                if saved['owner']!=owner or saved['payload']['request_id']!=rid:
                    raise JobError('Research request scope mismatch')
                payload = saved['payload']
                if diagnostics is not None:
                    diagnostics['visual_task_fingerprints'] = saved.get('visual_task_fingerprints')
            elif self.jobs.status(owner,job)['calls_spent']:
                raise JobError('Original input missing after provider admission')
        if (status not in ('pending','done') or not isinstance(payload,dict)
                or not isinstance(payload.get('model_task'),dict)
                or payload.get('wording_mode') not in ('neural_review','neural_auto')
                or payload.get('revision') != body.get('revision')):
            raise JobError('No exact current native preview request', check='preview_not_current')
        return payload

    def _context(self, app, body, job=None, *, renewed=False):
        if self.native_authority is not None:
            # No volatile browser proof exists here. Each use repeats the
            # native Run read and every original context/source guard.
            return self._context_once(app,body,job)
        if not renewed:
            return self._context_once(app,body,job)
        observed,remembered=self.observers.body(body)
        until=None
        while True:
            try:
                return self._context_once(app,observed,job,remembered=remembered)
            except JobError as error:
                if error.check!='identity_unverified' or remembered is None:
                    raise
                status=self.jobs.status(str(body.get('owner')or''),job)
                # Later states authorize acceptance/finalize/recovery only.
                # Requester still forbids new model steps outside running.
                if status['state']not in ('queued','running','awaiting_root','accepted','finalizing'):
                    raise
                if until is None:
                    until=time.monotonic()+self.observers.wait_budget(body)
                remaining=min(until-time.monotonic(),status['deadline']-self.jobs.clock())
                if remaining<=0:
                    raise
                fresh,stamp=self.observers.body(body)
                if fresh.get('identity_proof')==observed.get('identity_proof'):
                    fresh,stamp=self.observers.wait_for_observer(observed,remaining)
                if stamp is None or fresh.get('identity_proof')==observed.get('identity_proof'):
                    raise
                # Re-read the whole source and all guards with the new proof.
                # A valid lease never substitutes for a valid observer, nor
                # does renewal accept the native snapshot seen before it.
                observed,remembered=fresh,stamp

    def _context_once(self, app, body, job=None, *, remembered=None):
        from extension_assistant import _parse
        map_hash = self._map_version()
        identity=self._identity(app,body)
        owner = str(body.get('owner')or'')
        scope = 'assistant:'+digest(owner)
        if not self.owner_allowed(owner):
            raise JobError('Owner is not authorized')
        native_header = native_actor = None
        if self.native_context is not None:
            body,native_header,native_actor = self.native_context.prepare(body,identity)
            body=self._checked_visual_cache(app,body,native_header,native_actor)
            fresh=self._identity(app,body)
            if [fresh['principal_id'],fresh['operator_id']] != [identity['principal_id'],identity['operator_id']]:
                raise JobError('Native actor changed during source observation')
        diagnostics = {}
        payload = self._prepared(app,body,job,diagnostics=diagnostics)
        self.check_native_launch(payload,body)
        if (self._runtime_version()!=self.code_version
                or payload.get('research_profile') not in (None,self.profile)):
            raise JobError('Runtime or explicitly selected model profile changed', check='runtime_or_profile_changed')
        # Pre-integration previews may lack a stamp only on the exact map the
        # service started with. Never stamp an old preview with today's data.
        if payload.get('research_map_sha256',self.startup_map_version)!=map_hash:
            if job is None:raise PendingSourceChanged(payload)
            raise JobError('Original map changed',check='source_map_changed')
        visual = payload.get('research_purpose') == 'visual_observation_v1'
        form = payload.get('research_purpose') == 'intake_form_v1'
        if form and (not self.intake_form_enabled or self.profile!='sol_only'):
            raise JobError('Form purpose is not explicitly configured')
        chat, messages, known, revision = _parse(body.get('ctx'),app.store,scope,include_model_media=not visual)
        if payload['chat_id']!=chat:
            raise JobError('Client conversation changed', check='conversation_changed')
        with app.store.connect() as db:
            row = db.execute('SELECT generation,revision,held FROM dialogs WHERE scope=? AND chat=?',(scope,chat)).fetchone()
        if not row or row['held']:
            raise JobError('Conversation held or generation changed', check='conversation_held')
        if (payload.get('policy_version')!=policy.VERSION
                or not experience_runtime.current(payload,app.store.path,policy.VERSION)):
            raise JobError('Primary rules or reviewed experience changed', check='policy_or_experience_changed')
        if payload.get('operator_binding') and payload['operator_binding'] != [identity['principal_id'],identity['operator_id']]:
            raise JobError('Prepared operator identity changed', check='actor_changed')
        if (self.native_context is not None
                and payload.get('known',{}).get('source_client_group') != known.get('source_client_group')):
            raise JobError('Native client identity changed', check='client_group_changed')
        if payload['wording_mode']=='neural_auto':
            if self.native_authority is not None:
                if not self.owner_auto_enabled:
                    raise JobError('Native auto is not configured',check='auto_session_not_live')
                self.native_authority.auto_binding(body)
            else:
                lease = personal_assistant.session(app.store,owner,'personal_status',body)
                if lease.get('code')=='operator_identity':
                    raise JobError('Fresh operator identity required',check='identity_unverified')
                if not personal_workflow.enabled(lease):
                    raise JobError('Original auto session no longer active', check='auto_session_not_live')
            if self.owner_auto_enabled and payload.get('auto_session_binding')!=self.auto_preview_binding(app,body,identity):
                raise JobError('Prepared launch changed',check='auto_session_changed')
        if payload['revision']!=revision:
            if job is None and self.native_context is not None:
                previous=payload.get('known',{})
                changed={key for key in set(previous)|set(known) if previous.get(key)!=known.get(key)}
                # Messages and these fields come from the repeated native
                # read. A changed operator route/coordinates/other context
                # must keep the original stop contract, even if a message
                # arrived at the same time.
                native_fields={'assignee_id','conversation_status','crm_request_id',
                    'bot_active','transfer_active','client_name','phone',
                    'introduced_name','introduced_name_evidence','crm_note_references'}
                if changed<=native_fields and (payload['messages']!=messages or changed):
                    raise PendingSourceChanged(payload)
            raise JobError('Client conversation changed', check='source_revision_changed')
        if row['generation']!=payload['generation'] or row['revision']!=revision:
            raise JobError('Conversation held or generation changed', check='generation_changed')
        corpus = self.corpus_factory()
        native = payload['model_task']
        task = json.loads(native['task'])
        schema = native.get('response_format',{}).get('schema')
        if not isinstance(schema,dict):
            raise JobError('Original strict native schema required')
        # The native validator keeps its full original task in the staged
        # preview. The API gets its complete timeline once, not duplicated.
        timeline = task.get('conversation')
        if not isinstance(timeline,list) or not timeline:
            raise JobError('Complete original native conversation required')
        current_rows = [dict(m,id=m.get('id')or m['review_ref'],source_message_id=m.get('id')or'') for m in timeline]
        source_task = {k:v for k,v in task.items() if k!='conversation'}
        current = dict(owner_id=owner,dialogue_id=chat,revision=revision,direction=known['direction'],
            policy_version=policy.VERSION,memory_version=corpus.initial,map_version=map_hash,
            messages=current_rows,facts=[],open_questions=[],lessons=[],verified_receipts={},
            candidate_contract=dict(system=native['system'],task=source_task,schema=schema))
        if native_header is not None:
            self.native_context.bind(owner,chat,revision,native_header,native_actor)
            current.update(client_group=native_header['client_group'],phone_hashes=native_header['phone_hashes'],
                           media_hashes=native_header['media_hashes'])
        if self.proposal_enabled and not visual and not form:
            current['candidate_contract'] = research_proposals.contract(
                payload, price_wording_enabled=self.price_wording_enabled)
        selected_lessons=(current['candidate_contract']['task'].get('experience_context')or{}).get('lessons',[])
        current['lessons']=corpus.admit_lessons(selected_lessons,current)
        media = research_media.prepare(body['ctx'], current_rows, owner=owner, chat=chat,
                                       revision=revision, resolver=self.media_resolver)
        if media is not None:
            current['media'] = media
        # Original-image IO can outlive an explicit stop or author change.
        # Reuse the exact native launch gate after the final pixel read too.
        self.check_native_launch(payload,body)
        pack_context('research',current,profile=self.profile)
        task_parts = dict(
            model_task=native, corpus=corpus.initial, dialog_generation=payload['generation'],
            runtime=self.code_version, media=media, proposal_enabled=self.proposal_enabled,
            intake_form_enabled=self.intake_form_enabled, candidate_contract=current['candidate_contract'],
            native_crm_only_enabled=self.native_crm_only_enabled,
            unique_replies_enabled=self.unique_replies_enabled,
            price_wording_enabled=self.price_wording_enabled,
            reviewed_lessons=current['lessons'],
            browser_session=body.get('browser_session'), source_header=native_header, funding=self.funding,
            owner_auto_enabled=self.owner_auto_enabled, call_limit=self.auto_session_call_limit,
            auto_session_binding=payload.get('auto_session_binding'))
        if self.native_authority is not None:
            task_parts['native_launch_binding'] = payload.get('native_launch_binding')
        if self.native_authority is not None and visual:
            fingerprints = {key: digest(value) for key, value in task_parts.items()}
            original = diagnostics.get('visual_task_fingerprints')
            if job is None:
                payload['_visual_task_fingerprints'] = fingerprints
            elif isinstance(original, dict) and original.keys() == fingerprints.keys():
                changed = sorted(key for key in fingerprints if original[key] != fingerprints[key])
                if changed:
                    self.jobs.audit(job, 'visual_task_components_changed', dict(components=changed))
        binding = dict(owner=owner,request=payload['request_id'],chat=chat,revision=revision,
            principal=identity['principal_id'],operator=identity['operator_id'],policy=policy.VERSION,
            memory=corpus.initial,map=map_hash,task=digest(list(task_parts.values())),profile=self.profile)
        if remembered is not None and remembered!=digest(binding):
            raise JobError('Renewed observer no longer matches the original task')
        if self._map_version()!=map_hash:
            if job is None:raise PendingSourceChanged(payload)
            raise JobError('Map changed during preparation',check='source_map_changed')
        return binding,current,payload,corpus

    def check_native_launch(self,payload,body):
        if (self.native_authority is not None
                and payload.get('native_launch_binding') != self.native_authority.launch_binding(body)):
            raise JobError('Prepared native launch changed',check='auto_session_changed')

    def _retire_changed_unsubmitted(self, app, body, prepared):
        """Fence only this stale preview; never authorize a replacement call."""
        owner=str(body['owner']);scope='assistant:'+digest(owner)
        request,chat=prepared['request_id'],prepared['chat_id']
        concurrent=[]
        with self.mutex:
            with self.jobs.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                for row in db.execute('SELECT id,binding,job FROM grants'):
                    binding=json.loads(row['binding'])
                    if binding['owner']==owner and binding['request']==request and binding['chat']==chat:
                        db.execute('UPDATE grants SET deadline=min(deadline,?) WHERE id=?',
                                   (self.jobs.clock(),row['id']))
                        if row['job']:concurrent.append(row['job'])
            self.pending_admissions={key:value for key,value in self.pending_admissions.items()
                if not(value['binding']['owner']==owner and value['binding']['request']==request
                       and value['binding']['chat']==chat)}
        self.observers.discard(owner,request)
        if concurrent:
            # A submit can win the SQLite race after the initial job lookup.
            # Unknown/in-flight work must retain the original stop contract.
            for job in concurrent:
                self.jobs.stop(owner,job)
                self._abort(app,body,job,'Исходный контекст изменился после допуска')
            return dict(ok=False,reply='',code='research_stopped',needs_operator=True,
                failure_stage='concurrent_admission',auto_enabled=False,can_send_or_create=False,
                error='Контекст допущенной задачи изменился; повтор не запускался'),403
        result=dict(ok=True,reply='',action='wait',needs_operator=False,auto_enabled=False,
            pending_research=True,research_state='source_changed',refresh_preview=True,
            request_id=request,revision=prepared['revision'],can_send_or_create=False,
            reason='Диалог изменился. Следующая проверка прочитает его заново')
        app.store.complete(scope,request,result)
        app.store.release_dialog(scope,chat,request)
        import workflow_audit
        workflow_audit.append(app.store,scope,chat,'research_source_changed',prepared['revision'],
            dict(before_durable_submission=True,provider_retry_started=False,
                 actual_customer_action=False,refresh_requires_new_preview=True))
        return result,200

    def _remember_observer(self, app, body, binding, *, job=None, launch=None):
        identity=self._identity(app,body)
        if [identity['principal_id'],identity['operator_id']] != [binding['principal'],binding['operator']]:
            raise JobError('Observer actor changed before renewal')
        if self.native_authority is not None:
            return  # Native Run is re-read, no browser proof is synthesized.
        self.observers.remember(body,digest(binding),identity)
        if job:
            status=self.jobs.status(binding['owner'],job)
            self.observers.anchor(body,digest(binding),identity,job=job,deadline=status['deadline'],launch=launch)

    def relay_request_identity(self, app, body):
        """Publish a signed request's identity before its slow source reads.

        A different CID can rotate the browser-session nonce while a model
        call is pending. Its fresh proof belongs to the same actor/session,
        not to that CID alone. Only existing exact-launch anchors receive it;
        the original job must still revalidate its own complete source.
        """
        if self.native_authority is not None:
            self._identity(app,body)
            return 0
        try:
            identity=self._identity(app,body)
            if not self.observers.session_candidates(body,identity):
                return 0  # Ordinary/legacy requests have no identity lease to renew.
            session=personal_assistant.session(app.store,str(body.get('owner')or''),'personal_status',body)
            if not session.get('ok') or not session.get('active'):
                return 0
            return self.relay_session_identity(app,body,session,origin='request')
        except JobError as error:
            if error.check!='identity_unverified':raise
            return 0  # Concurrent revocation is never accepted as renewal.

    def relay_session_identity(self, app, body, session, *, origin='heartbeat'):
        """A verified request renews exact live-job identity, never context.

        Provider calls and full-source observers can outlast a signed proof.
        This short path publishes the new verified proof independently of
        those slow reads. Every worker use still verifies it and re-reads all
        source/lease/version bindings; no deadline or authority is extended.
        """
        if self.native_authority is not None:
            self._identity(app,body)
            return 0
        if not session.get('ok') or not session.get('active'):
            return 0
        identity=self._identity(app,body);owner=str(body.get('owner')or'')
        if not self.owner_allowed(owner):return 0
        with app.store.connect()as db:
            lease=db.execute('SELECT sid,principal,operator,expires FROM personal_sessions WHERE scope=?',
                             (digest(owner),)).fetchone()
        if (not lease or lease['sid']!=body.get('browser_session') or lease['expires']<=self.jobs.clock()
                or lease['principal']!=identity['principal_id'] or lease['operator']!=identity['operator_id']):
            return 0
        relayed=0
        for anchor in self.observers.session_candidates(body,identity):
            status=self.jobs.status(owner,anchor['job'])
            if status['state']not in ('queued','running','awaiting_root','accepted','finalizing')or status['deadline']!=anchor['deadline']:
                continue
            with self.jobs.connect()as db:bound=json.loads(self.jobs._row(db,anchor['job'])['binding'])
            if (digest(bound)!=anchor['binding']or bound['owner']!=owner
                    or [bound['principal'],bound['operator']]!=[identity['principal_id'],identity['operator_id']]):
                continue
            if anchor['launch'] is not None:
                if not personal_workflow.enabled(session) or self.auto_preview_binding(app,body,identity)!=anchor['launch']:
                    continue
            key=anchor['key']
            scoped=dict(owner=key[0],request_id=key[1],revision=key[2],browser_session=key[3],operator_id=key[4],identity_proof='')
            prior,_=self.observers.body(scoped)
            if prior.get('identity_proof')==body.get('identity_proof'):continue
            scoped['identity_proof']=body['identity_proof']
            self.observers.remember(scoped,anchor['binding'],identity,authority='identity_only_existing_job')
            event='identity_reattested_from_heartbeat' if origin=='heartbeat' else 'identity_reattested_from_request'
            self.jobs.audit(anchor['job'],event,dict(
                authority='identity_only_not_context_approval',context_revalidation_required=True,
                original_deadline_unchanged=True,can_send_or_create=False))
            relayed+=1
        return relayed

    def _remember_job_identity(self, app, body, job, admitted):
        """Renew identity only; the worker re-reads all source/lease guards.

        Waiting for an observer's expensive corpus assembly before publishing
        its signed identity can exhaust the five-second nonce handoff. Only
        an already remembered exact job may receive this early renewal.
        """
        if self.native_authority is not None:
            self._identity(app,body)
            return
        context=body.get('ctx')
        if (not isinstance(context,dict) or body.get('owner')!=admitted['owner'] or body.get('request_id')!=admitted['request']
                or body.get('revision')!=admitted['revision']
                or context.get('convId')!=admitted['chat']):
            return
        status=self.jobs.status(admitted['owner'],job)
        if (status['state']not in ('queued','running','awaiting_root','accepted','finalizing')
                or status['deadline']<=self.jobs.clock()):
            return
        previous,stamp=self.observers.body(dict(body,identity_proof=''))
        if stamp!=digest(admitted) or previous.get('identity_proof')==body.get('identity_proof'):
            return
        identity=self._identity(app,body)
        if [identity['principal_id'],identity['operator_id']]!=[admitted['principal'],admitted['operator']]:
            return
        self.observers.remember(body,digest(admitted),identity,authority='identity_only_existing_job')
        self.jobs.audit(job,'identity_reattested_before_context',dict(
            authority='identity_only_not_context_approval',context_revalidation_required=True,
            can_send_or_create=False))

    def verify_form(self,app,body,proposal):
        """Use the same fresh source/actor/version gate before existing CRM checks."""
        import research_form
        owner=str(body['owner']);ctx=body['ctx'];scope='assistant:'+digest(owner)
        from extension_assistant import _parse
        _,_,_,revision=_parse(ctx,app.store,scope)
        value=research_form.read(app.store,scope,str(ctx['convId']),revision,proposal.get('form_reference'))
        expected_mode='crm_only' if self.native_crm_only_enabled else 'telegram'
        if value.get('completion_mode','telegram')!=expected_mode:
            raise JobError('Accepted form completion mode no longer matches trusted configuration')
        bound=value['binding'];job=value['job']
        if self.jobs.status(owner,job)['state']!='done':raise JobError('Form finalize is not confirmed')
        fresh,_,_,_=self._context(app,dict(body,request_id=bound['request'],revision=revision),job)
        if digest(fresh)!=digest(bound):raise JobError('Accepted form source or actor changed')
        lead=proposal.get('lead')or{}
        for field in ('problem','device','client_words'):
            if lead.get(field)!=value['lead'][field]:raise JobError('Reviewed work description changed')
        if value['lead']['comment'] not in str(lead.get('comment')or''):
            raise JobError('Reviewed work comment changed')

    def admit(self, app, body, *, max_calls, seconds):
        """Trusted controller only; intentionally absent from HTTP actions."""
        binding,_,_,_ = self._context(app,body)
        with self.jobs.connect() as db:
            old = db.execute('SELECT 1 FROM grants WHERE binding_hash=?',(digest(binding),)).fetchone()
        if old:
            raise JobError('This exact preview already has an admission; no lucky repeat')
        return self.jobs.admit(binding,max_calls=max_calls,seconds=seconds)

    def _remember_pending(self,app,body,binding):
        identity=self._identity(app,body);now=self.jobs.clock()
        if self.native_authority is not None:
            expires=now+45  # Metadata cache only. Admission rechecks current Run.
        else:
            issued,expires=identity.get('iat'),identity.get('exp')
            if (type(issued)is not int or type(expires)is not int or not now<expires
                    or issued>now+3 or not 0<expires-issued<=45 or not body.get('browser_session')):
                return False
        key=digest(binding)
        with self.mutex:
            self.pending_admissions={k:v for k,v in self.pending_admissions.items() if v['expires']>now}
            if key not in self.pending_admissions and len(self.pending_admissions)>=128:
                self.pending_admissions.pop(next(iter(self.pending_admissions)))
            self.pending_admissions[key]=dict(app=app,body=copy.deepcopy(body),binding=copy.deepcopy(binding),
                                             expires=expires,purpose=self._prepared(app,body).get('research_purpose','reply'))
        return True

    def pending_metadata(self):
        now=self.jobs.clock()
        with self.mutex:
            self.pending_admissions={k:v for k,v in self.pending_admissions.items() if v['expires']>now}
            return [dict(binding_hash=k,**v['binding'],expires=v['expires'],purpose=v['purpose'])
                    for k,v in self.pending_admissions.items() if not v.get('admitted')]

    def admit_pending(self,expected_hash,*,max_calls,seconds):
        with self.mutex:
            value=self.pending_admissions.get(expected_hash)
            if not value or value['expires']<=self.jobs.clock():raise JobError('Pending observer expired')
            if value.get('admitted'):raise JobError('Pending observer already admitted')
            app,body=value['app'],copy.deepcopy(value['body'])
            # Serialize minting with cancel: a cancellation must never return
            # before a concurrent admission creates a still-usable grant.
            binding,_,_,_=self._context(app,body)
            if digest(binding)!=expected_hash:raise JobError('Pending source or actor changed')
            grant=self.admit(app,body,max_calls=max_calls,seconds=seconds)
            # Bounded private cancellation capability, hidden from the queue.
            value['admitted']=True
            value['expires']=self.jobs.clock()+seconds
        return grant

    def _cancel_unsubmitted(self, app, body, chat):
        identity=self._identity(app,body)
        owner=str(body.get('owner') or '')
        with self.mutex:
            matches=[(key,value) for key,value in self.pending_admissions.items()
                if value['binding']['owner']==owner
                and value['binding']['chat']==chat
                and value['binding']['request']==body.get('request_id')
                and value['binding']['revision']==body.get('revision')
                and value['binding']['principal']==identity['principal_id']
                and value['binding']['operator']==identity['operator_id']
                and value['body'].get('browser_session')==body.get('browser_session')]
            if len(matches)!=1:
                raise JobError('No exact owned pending observer to cancel', check='pending_observer_missing')
            key,value=matches[0]
            with self.jobs.connect() as db:
                db.execute('UPDATE grants SET deadline=min(deadline,?) WHERE binding_hash=?',
                           (self.jobs.clock(),key))
            self.pending_admissions.pop(key,None)
        result=dict(ok=True,reply='',pending_research=False,research_state='cancelled',
                    auto_enabled=False,can_send_or_create=False)
        scope='assistant:'+digest(owner)
        app.store.complete(scope,body['request_id'],result)
        app.store.release_dialog(scope,chat,body['request_id'])
        return result,200

    def _enqueue(self, app, body, job):
        with self.mutex:
            if job in self.scheduled:
                return
            self.scheduled.add(job)
        def run():
            try:
                self.run(app,copy.deepcopy(body),job)
            finally:
                with self.mutex:
                    self.scheduled.discard(job)
        try:
            self.schedule(run)
        except Exception:
            with self.mutex:
                self.scheduled.discard(job)
            raise JobError('Worker scheduling failed; job retained') from None

    def _abort(self, app, body, job, reason, *, technical=True):
        owner = str(body.get('owner')or'')
        scope = 'assistant:'+digest(owner)
        self.jobs.status(owner,job)
        with self.jobs.connect() as db:
            binding = json.loads(self.jobs._row(db,job)['binding'])
        self.observers.discard(owner,binding['request'])
        status,payload = app.store.request(scope,binding['request'])
        if status=='pending' and payload:
            payload.update(reply='',action='handoff',needs_operator=True,validation=['research_stopped'],
                           response_source='research_control',reason=reason,pending_model=False)
            if technical:
                payload.update(ok=False,code='research_stopped')
            app.finish(scope,payload)

    def _finish_visual_review(self, app, binding):
        """Finish only this request; no visual facts or approved lesson is staged."""
        scope='assistant:'+digest(binding['owner'])
        status,payload=app.store.request(scope,binding['request'])
        if status=='pending' and payload:
            payload.update(reply='',action='handoff',needs_operator=True,pending_model=False,
                validation=['visual_source_review'],code='research_visual_review',
                response_source='research_source_review',can_send_or_create=False,
                reason='Фото требует проверки сотрудником; автоматического повтора не было')
            app.finish(scope,payload)

    def _visual_review_response(self, app, body, job, binding, payload, status):
        import research_vision
        if (status['state']!='rejected' or payload.get('research_purpose')!=research_vision.PURPOSE
                or not status.get('result_sha256') or not self._automatic_job(job)):
            return None
        path=self.jobs._file(job,'result.json')
        if path.is_symlink() or path.stat().st_size>1024*1024:
            raise JobError('Original visual result is unavailable or oversized')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=status.get('result_sha256'):
            raise JobError('Original visual result integrity changed')
        if not research_vision.needs_source_review(strict_loads(raw)):
            return None
        # A harmless projection still requires the original full current
        # source, launch, publication hold and finite deadline. It cannot
        # turn a denied/cancelled/stale job into permission for another step.
        self.jobs._check(job,binding,lambda:self._context(app,body,job,renewed=True)[0],states=('rejected',))
        self._finish_visual_review(app,binding)
        return dict(ok=True,code='research_visual_review',reply='',action='handoff',
            needs_operator=True,pending_research=False,research_state='rejected',
            request_id=binding['request'],revision=binding['revision'],research_job_id=job,
            result_sha256=status['result_sha256'],calls_reserved=status['calls_spent'],
            usage=self.ledger.summary(owner=binding['owner'],dialogue=binding['chat']),
            human_media_review=False,visual_observation_ready=False,retry_started=False,
            auto_enabled=False,can_send_or_create=False,
            reason='Фото требует проверки сотрудником; автоматического повтора не было')

    def handle(self, app, body):
        """The existing service-token/owner gate calls this entrypoint."""
        known_job = False
        job = ''
        failure_stage = 'observer_contract'
        try:
            from extension_assistant import _parse
            allowed_fields = {'action','owner','ctx','identity_proof','operator_id','browser_session','request_id','revision',
                              'research_job_id','audit_cursor','audit_limit'}
            if self.native_authority is not None:
                allowed_fields.add('native_run')
            if not isinstance(body,dict) or set(body)-allowed_fields:
                raise JobError('Research control accepts only scoped observer fields')
            action = body.get('action')
            job = str(body.get('research_job_id')or'')
            owner = str(body.get('owner')or'')
            failure_stage = 'identity'
            self._identity(app,body)
            if not self.owner_allowed(owner):
                raise JobError('Owner is not authorized')
            if action=='research_audit':
                # Historical debugging is read-only. It must not observe an
                # old snapshot, restart a job or require its old revision.
                return self.jobs.audit_read(owner,job,after=body.get('audit_cursor',0),limit=body.get('audit_limit',100)),200
            failure_stage = 'job_lookup'
            if action in ('research_start','research_status','research_cancel') and not job:
                with self.jobs.connect() as db:
                    for row in db.execute('SELECT jobs.id,grants.binding FROM jobs JOIN grants ON grants.id=jobs.grant_id'):
                        prior = json.loads(row['binding'])
                        if prior['owner']==owner and prior['request']==body.get('request_id'):
                            job = row['id']
                            break
            if job:
                self.jobs.status(owner,job)
                with self.jobs.connect() as db:
                    admitted = json.loads(self.jobs._row(db,job)['binding'])
                if admitted['request'] != body.get('request_id'):
                    raise JobError('Job and request mismatch', check='job_request_mismatch')
                known_job = True
                self.check_native_launch(self._prepared(app,body,job),body)
                if action in ('research_start','research_status','research_finalize'):
                    self._remember_job_identity(app,body,job,admitted)
            elif action in ('research_start','research_status'):
                # A waiting CID has its own real preview, but no job yet.
                # Reject forged request/chat fields before sharing identity;
                # an exact existing job uses the narrower ingress above.
                failure_stage='current_context'
                prepared=self._prepared(app,body)
                context=body.get('ctx')
                if not isinstance(context,dict) or context.get('convId')!=prepared['chat_id']:
                    raise JobError('Prepared conversation mismatch',check='job_chat_mismatch')
                self.relay_request_identity(app,body)
            if self.native_context is not None:
                # Identity ingress is not acceptance of a browser snapshot.
                # Observe the authenticated native timeline independently.
                failure_stage = 'native_source'
                body=self.prepare_source(app,body)
            scope = 'assistant:'+digest(owner)
            chat,_,_,revision = _parse(body.get('ctx'),app.store,scope)
            if known_job and chat != admitted['chat']:
                raise JobError('Job and conversation mismatch', check='job_chat_mismatch')
            if action=='research_cancel' and not job:
                failure_stage = 'pending_cancel'
                app.store.observe(scope,chat,revision)
                return self._cancel_unsubmitted(app,body,chat)
            if not job and action not in ('research_start','research_status'):
                raise JobError('Exact durable job required', check='exact_job_required')
            if known_job and action in ('research_start','research_status','research_finalize'):
                completed=self.jobs.status(owner,job)
                prepared=self._prepared(app,body,job)
                if completed['state']=='done' and prepared.get('research_purpose')=='visual_observation_v1':
                    # Observation activation deliberately changes the next
                    # reply revision. Read-only recovery must not roll that
                    # revision back or re-run the visual request/finalize.
                    identity=self._identity(app,body)
                    observed,header,actor=self.native_context.prepare(body,identity)
                    observed=self._checked_visual_cache(app,observed,header,actor)
                    _,_,_,base_revision=_parse(observed['ctx'],app.store,scope,include_model_media=False)
                    map_hash=hashlib.sha256(Path(policy.__file__).with_name('filial_zones.json').read_bytes()).hexdigest()
                    if (base_revision!=admitted['revision'] or policy.VERSION!=admitted['policy']
                            or map_hash!=admitted['map'] or self.corpus_factory().initial!=admitted['memory']
                            or self._runtime_version()!=self.code_version
                            or [identity['principal_id'],identity['operator_id']]!=[admitted['principal'],admitted['operator']]):
                        raise JobError('Completed visual observation no longer matches current source/actor')
                    with self.jobs.connect() as db:
                        final=json.loads(self.jobs._row(db,job)['final_result'])
                    import research_vision
                    research_vision.verify_completed(app.store,scope,prepared,job,observed['ctx'],
                        lambda descriptor:self.native_context.image_digest(header,actor,descriptor))
                    research_vision.activate(app.store,scope,prepared,job)
                    return dict(final,cached=True),200
            # A newer observed browser snapshot fences the old worker before
            # it can make another paid step or expose a stale draft. Rolling
            # back the snapshot also changes generation and cannot revive it.
            if known_job and self._prepared(app,body,job).get('research_purpose')=='visual_observation_v1':
                chat,_,_,revision=_parse(body.get('ctx'),app.store,scope,include_model_media=False)
            app.store.observe(scope,chat,revision)
            if action in ('research_start','research_status') and not job:
                failure_stage = 'current_context'
                binding,current,payload,_ = self._context(app,body,job or None)
                failure_stage = 'finite_admission'
                automatic=self._automatic_grant(app,body,binding,payload)
                if automatic is False:
                    with app.store.connect()as db:
                        db.execute("UPDATE requests SET lease=? WHERE scope=? AND rid=? AND status='pending'",
                            (self.jobs.clock()+90,scope,binding['request']))
                        db.execute('UPDATE execution SET lease=? WHERE scope=? AND chat=? AND rid=?',
                            (self.jobs.clock()+90,scope,chat,binding['request']))
                    return dict(ok=True,reply='',pending_research=True,research_state='waiting_turn',research_job_id='',
                        request_id=binding['request'],revision=binding['revision'],needs_operator=False,
                        auto_enabled=False,can_send_or_create=False,
                        reason='Ожидает очереди на проверку ответа; платный вызов и его срок ещё не выделены'),200
                if automatic:
                    grant={'id':automatic}
                else:
                    with self.jobs.connect() as db:
                        grant = db.execute('SELECT id FROM grants WHERE binding_hash=? AND deadline>? ORDER BY rowid DESC LIMIT 1',
                                           (digest(binding),self.jobs.clock())).fetchone()
                if not grant:
                    if self._remember_pending(app,body,binding):
                        return dict(ok=True,reply='',pending_research=True,pending_admission=True,
                            research_state='awaiting_admission',research_job_id='',request_id=binding['request'],revision=binding['revision'],
                            needs_operator=False,auto_enabled=False,can_send_or_create=False,
                            reason='Ожидается конечный допуск контролируемой API-проверки; платных вызовов ещё нет'),200
                    raise self.jobs.missing_admission_error(binding)
                job = self.jobs.submit(binding,grant['id'])['job_id']
                with self.mutex:self.pending_admissions.pop(digest(binding),None)
                known_job = True
                # Server identity metadata, never a rewrite of model JSON.
                # Even a previously unbound preview becomes bound before a
                # research job can expose a draft to ordinary validation.
                payload['operator_binding'] = [binding['principal'],binding['operator']]
                payload['research_profile'] = self.profile
                fingerprints = payload.pop('_visual_task_fingerprints', None)
                app.store.stage(scope,binding['request'],payload)
                path = self.jobs._file(job,'input.json')
                original_input = dict(owner=binding['owner'], payload=payload)
                if fingerprints is not None:
                    original_input['visual_task_fingerprints'] = fingerprints
                raw = json.dumps(original_input,ensure_ascii=False,sort_keys=True).encode()
                self.jobs.save_input(job,raw)
                deadline = self.jobs.status(binding['owner'],job)['deadline']
                scope = 'assistant:'+digest(binding['owner'])
                with app.store.connect() as db:
                    db.execute("UPDATE requests SET lease=? WHERE scope=? AND rid=? AND status='pending'",(deadline,scope,binding['request']))
                    db.execute('UPDATE execution SET lease=? WHERE scope=? AND chat=? AND rid=?',(deadline,scope,binding['chat'],binding['request']))
                self._remember_observer(app,body,binding,job=job,launch=payload.get('auto_session_binding'))
                if self.jobs.status(binding['owner'],job)['state'] in ('queued','running'):
                    self._enqueue(app,body,job)
            else:
                failure_stage = 'current_context'
                binding,_,payload,_ = self._context(app,body,job)
                if digest(binding) != digest(admitted):
                    self.jobs.audit(job,'context_binding_changed',dict(changed_fields=sorted(
                        key for key in admitted if binding.get(key) != admitted.get(key))))
                    raise JobError('Job actor or version binding changed')
                self._remember_observer(app,body,binding,job=job,launch=payload.get('auto_session_binding'))
            owner = binding['owner']
            scope = 'assistant:'+digest(owner)
            status = self.jobs.status(owner,job)
            if self.jobs.clock()>=status['deadline'] and status['state'] in ('queued','running','awaiting_root','accepted'):
                self.jobs.stop(owner,job)
                self._abort(app,body,job,'Истёк конечный срок исследования; новая генерация не запускалась')
                status = self.jobs.status(owner,job)
            if action in ('research_start','research_status','research_finalize'):
                source_review=self._visual_review_response(app,body,job,binding,payload,status)
                if source_review is not None:
                    return source_review,200
            if action in ('research_status','research_start') and status['state'] in ('queued','running') and not self.jobs.worker_present(job):
                self._enqueue(app,body,job)
            if status['state']=='done' and action in ('research_start','research_status','research_finalize'):
                with self.jobs.connect() as db:
                    final = json.loads(self.jobs._row(db,job)['final_result'])
                if final.get('visual_observation_ready'):
                    import research_vision
                    research_vision.activate(app.store,scope,self._prepared(app,body,job),job)
                    return dict(final,cached=True),200
                if final.get('needs_operator')is True and not final.get('reply') and not final.get('draft_id'):
                    return dict(final,cached=True),200
                checked,code = app.handle(dict(body,action='validate',draft_id=final.get('draft_id')))
                if code!=200 or not checked.get('ok'):
                    raise JobError('Completed research draft is no longer current')
                return dict(final,cached=True),200
            if action=='research_cancel':
                self.jobs.cancel(owner,job)
                self._abort(app,body,job,'Исследование отменено оператором')
                status = self.jobs.status(owner,job)
            elif action=='research_finalize':
                failure_stage = 'finalize'
                def fresh():return self._context(app,body,job,renewed=True)[0]
                if status['state']=='finalizing':
                    # A lost observer cannot cause another finalize. Only read
                    # the original request result and reconcile that result.
                    def read():
                        state,value=app.store.request(scope,binding['request'])
                        if state=='done' and isinstance(value,dict) and self._automatic_native_outcome(job,value):
                            self.jobs.stop_series(binding['owner'],except_job=job)
                        return dict(done=state=='done',result=value)
                    return self.jobs.reconcile(job,binding,fresh=fresh,read=read),200
                def finish(result):
                    def completed_native(value):
                        if self._automatic_native_outcome(job,value):
                            with self.mutex:self.control_failure_epoch+=1
                            self.jobs.stop_series(binding['owner'],except_job=job)
                        return value
                    if result.get('purpose')=='intake_form_v1':
                        import research_form
                        prepared=self._prepared(app,body,job)
                        fields=research_form.stage(app.store,scope,prepared,result,job,binding)
                        return completed_native(app.finish(scope,dict(prepared,**fields,reply='',action='ready',needs_operator=False,
                            can_send_or_create=False,auto_enabled=False,research_job_id=job)))
                    if result.get('purpose') == 'visual_observation_v1':
                        import research_vision
                        prepared=self._prepared(app,body,job)
                        research_vision.stage(app.store,scope,prepared,result,job)
                        final=dict(ok=True,action='wait',reply='',needs_operator=False,auto_enabled=False,
                            visual_observation_ready=True,refresh_preview=True,research_job_id=job,
                            request_id=binding['request'],revision=binding['revision'],human_media_review=False,
                            reason='Изображение проверено отдельно; заново оценивается текущий приём',can_send_or_create=False)
                        return completed_native(app.finish(scope,dict(prepared,**final)))
                    candidate=result.get('candidate')
                    if not isinstance(candidate,dict):
                        raise JobError('Missing original native candidate')
                    final_body = dict(request_id=binding['request'],revision=binding['revision'],candidate=candidate)
                    finalize_options: dict[str, object] = {}
                    if self.unique_replies_enabled:
                        finalize_options['reserve_reply'] = lambda reply: self.jobs.reserve_final_reply(job, binding, reply)
                    if self.proposal_enabled:
                        finalize_options['research_proposal'] = research_proposals.build(self._prepared(app,body,job),
                            price_wording_enabled=self.price_wording_enabled)
                    final = app.finalize(scope, final_body, **finalize_options)
                    self.jobs.audit(job,'legacy_validation_result',dict(validation=final.get('validation'),
                        reply=final.get('reply'),draft_id=final.get('draft_id'),source=final.get('response_source'),
                        actual_customer_send=False,actual_crm_create=False,actual_telegram_send=False))
                    return completed_native(dict(final,research_job_id=job,research_models=result['models'],research_profile=self.profile))
                final=self.jobs.finalize(job,binding,fresh=fresh,finish=finish)
                if final.get('visual_observation_ready'):
                    import research_vision
                    research_vision.activate(app.store,scope,self._prepared(app,body,job),job)
                return final,200
            elif action not in ('research_start','research_status'):
                raise JobError('Unknown read-only research operation')
            if status['state'] in ('denied','rejected','stopped','cancelled'):
                technical=True
                if status['state']=='rejected' and status.get('result_sha256'):
                    raw=self.jobs._file(job,'result.json').read_bytes()
                    if hashlib.sha256(raw).hexdigest()!=status['result_sha256']:
                        raise JobError('Original failed result integrity changed')
                    original=json.loads(raw)
                    technical=original.get('failure_kind')!='semantic'
                self._abort(app,body,job,'Проверка исследовательского ответа остановлена',technical=technical)
                if technical:
                    return dict(ok=False,reply='',code='research_stopped',auto_enabled=False,
                        research_state=status['state'],research_job_id=job,can_send_or_create=False,
                        request_id=binding['request'],revision=binding['revision'],
                        result_sha256=status['result_sha256'],
                        error='Исследовательская задача остановлена. Нужна техническая проверка; повторный вызов не запускался'),409
            usage = self.ledger.summary(owner=owner,dialogue=binding['chat'])
            usage['unresolved_provider_steps'] = status['unresolved_provider_steps']
            if status['unresolved_provider_steps']:
                usage['complete'] = False
            machine_wait=(status['state']=='awaiting_root' and self.owner_auto_enabled and self._automatic_job(job))
            return dict(ok=True,reply='',pending_research=status['state']in('queued','running','finalizing')or machine_wait,
                request_id=binding['request'],revision=binding['revision'],
                research_job_id=job,research_state=status['state'],result_sha256=status['result_sha256'],
                calls_reserved=status['calls_spent'],unresolved_provider_steps=status['unresolved_provider_steps'],
                progress=status['progress'],
                usage=usage,
                deadline=status['deadline'],auto_enabled=False,
                requires_root=status['state']=='awaiting_root'and not machine_wait,
                awaiting_machine_acceptance=machine_wait,can_send_or_create=False),200
        except PendingSourceChanged as error:
            return self._retire_changed_unsubmitted(app,body,error.prepared)
        except WorkerBusy:
            return dict(ok=True,reply='',pending_research=True,research_state='queued',research_job_id=job,
                        request_id=body.get('request_id'),revision=body.get('revision'),auto_enabled=False,
                        reason='Сохраняется исходный контекст той же задачи'),200
        except (ValueError,OSError,TypeError,KeyError,sqlite3.Error) as error:
            if known_job:
                self.jobs.stop(str(body.get('owner')or''),job)
                self._abort(app,body,job,'Контекст или допуск исследовательской задачи изменился')
            # A pre-job failure used to disappear behind a generic message.
            # Record only a bounded stage and exception class: never exception
            # text, proof, headers, body, credential or a synthetic explanation.
            import workflow_audit
            try:
                safe_body = body if isinstance(body,dict) else {}
                safe_ctx = safe_body.get('ctx') if isinstance(safe_body.get('ctx'),dict) else {}
                safe_action = safe_body.get('action')
                check = getattr(error,'check',None)
                workflow_audit.append(app.store,'assistant:'+digest(str(safe_body.get('owner')or'')),
                    str(safe_ctx.get('convId')or'')[:200], 'research_control_stopped', '',
                    dict(stage=failure_stage, category=type(error).__name__, known_job=known_job,
                         action=safe_action if isinstance(safe_action,str) and safe_action in CONTROL_ACTIONS else 'unsupported',
                         check=check if isinstance(check,str) and check in CONTROL_CHECKS else None,
                         supplied_job=bool(safe_body.get('research_job_id')),
                         changed_binding_fields=sorted({key for key in getattr(error,'changed_fields',())
                             if isinstance(key,str) and key in FIELDS}),
                         source_hold_failure=(getattr(error,'source_hold_failure',None)
                             if getattr(error,'source_hold_failure',None) in ('publication','io') else None),
                         actual_customer_action=False, retry_started=False))
            except (ValueError,OSError,TypeError,KeyError,sqlite3.Error):
                pass  # Diagnostic failure cannot authorize a retry or action.
            control_reason=getattr(error,'check',None)
            if control_reason=='auto_prefix_prior_attempt' and not known_job:
                # An earlier terminal/unknown attempt remains forbidden. It
                # is one dialog's manual review, not a new failure of this
                # explicitly restarted launch or permission to regenerate.
                return dict(ok=False,reply='',code='research_prior_attempt',needs_operator=True,
                    auto_enabled=False,can_send_or_create=False,control_reason=control_reason,
                    failure_stage=failure_stage,retry_started=False,
                    error='По этому сообщению уже была остановленная попытка. Нужна ручная сверка её журнала; повторный запрос не запускался.'),403
            message={'auto_allowance_exhausted':'Допуск API на этот запуск исчерпан. Проверьте расход и журнал перед новым запуском.',
                'auto_session_blocked':'Допуск API остановлен после ошибки проверки. Проверьте журнал перед новым запуском.',
                'auto_prefix_prior_attempt':'По этому сообщению уже была попытка. Повторная генерация остановлена; нужен разбор исходной задачи.'}.get(control_reason,
                    'Исследование остановлено: проверьте допуск, актуальность и журнал той же задачи')
            return dict(ok=False,reply='',code='research_stopped',needs_operator=True,auto_enabled=False,
                        failure_stage=failure_stage,
                        control_reason=control_reason if control_reason in CONTROL_CHECKS else None,error=message),403

    def run(self, app, body, job):
        """A worker, not a coding agent. Restart reuses exact persisted bytes."""
        try:
            with self.jobs.session_worker(job):
                if self.jobs.status(str(body.get('owner')or''),job)['state'] not in ('queued','running'):
                    return
                return self._run(app,body,job)
        except WorkerBusy:
            return  # An observer must never cancel or redispatch a live job.

    def _run(self, app, body, job):
        worker_stage='context'
        try:
            binding,current,payload,corpus = self._context(app,body,job,renewed=True)
            fresh = lambda:self._context(app,body,job,renewed=True)[0]
            worker_stage='memory'
            state = self.memory.load(binding['owner'],binding['chat'],current)
            self.memory.save(binding['owner'],binding['chat'],current,expected_generation=state['generation'],authoritative_revision=binding['revision'])
            requester = self.jobs.requester(job,binding,fresh=fresh,request=self.request)
            transport = ResponsesTransport(requester,self.ledger,media_resolver=self.media_resolver,funding=self.funding)
            status = self.jobs.status(binding['owner'],job)
            worker_stage='model_pipeline'
            if payload.get('research_purpose')=='intake_form_v1':
                import research_form
                result=research_form.run(current,transport,audit=lambda event,detail:self.jobs.audit(job,event,detail))
                self.jobs.propose(job,binding,result,fresh=fresh)
                if result['approved']:
                    self._automatic_accept(job,binding,fresh=fresh)
                if not result['approved']:
                    if self._automatic_failure(job,hard=result.get('failure_kind')!='semantic'):
                        with self.mutex:self.control_failure_epoch+=1
                        self.jobs.stop_series(binding['owner'],except_job=job)
                    self._abort(app,body,job,'Суть работы не прошла проверку',technical=result.get('failure_kind')!='semantic')
                return
            if payload.get('research_purpose') == 'visual_observation_v1':
                import research_vision
                result=research_vision.run(current,transport,audit=lambda event,detail:self.jobs.audit(job,event,detail))
                self.jobs.propose(job,binding,result,fresh=fresh)
                if result['approved']:
                    self._automatic_accept(job,binding,fresh=fresh)
                elif research_vision.needs_source_review(result) and self._automatic_job(job):
                    self._finish_visual_review(app,binding)
                    self.jobs.audit(job,'visual_source_review',dict(
                        source='model_assertion_unverified',manual_root=False,
                        no_facts_activated=True,can_send_or_create=False))
                    return
                if not result['approved']:
                    if self._automatic_failure(job,hard=result.get('failure_kind')!='semantic'):
                        with self.mutex:self.control_failure_epoch+=1
                        self.jobs.stop_series(binding['owner'],except_job=job)
                    self._abort(app,body,job,'Изображение не прошло отдельную проверку',technical=False)
                return
            rule_ids = [s['id'] for s in current['candidate_contract']['task'].get('primary_sources',[])]
            if not rule_ids:
                raise JobError('Complete current primary sources required')
            candidate_check: Callable[[dict], list[str]] | None = None
            if self.proposal_enabled:
                native_payload = copy.deepcopy(payload)
                native_plan = research_proposals.build(native_payload,
                    price_wording_enabled=self.price_wording_enabled)
                if native_plan['mode'] == 'source_bound_price':
                    # Same original bound constraints as finalization, with
                    # no Store writes, source mutation or response repair.
                    wording_enabled = self.price_wording_enabled
                    def check_price_candidate(candidate: dict) -> list[str]:
                        research_proposals.verify(native_payload, native_plan,
                            price_wording_enabled=wording_enabled)
                        return research_proposals.wording_violations(candidate['reply'], native_payload)
                    candidate_check = check_price_candidate

            def reply_available(reply: str) -> bool:
                # Use the same mandatory greeting and disclosures as native finalization.
                complete = policy.compose_reply(reply, payload['decision_internal'])
                return self.jobs.reply_available(binding['owner'], reply, complete_reply=complete)

            pipeline = Pipeline(corpus,transport,profile=self.profile,max_calls=status['max_calls'],
                max_seconds=status['deadline']-self.jobs.clock(),initial_rule_ids=rule_ids,
                audit=lambda event,detail:self.jobs.audit(job,event,detail),
                reply_available=reply_available if self.unique_replies_enabled else None,
                candidate_check=candidate_check)
            if self.proposal_enabled:
                self.jobs.audit(job,'proposal_plan_bound',dict(
                    current['candidate_contract']['task']['proposal_plan'],
                    source='trusted_wording_boundary_not_model_understanding'))
            result = pipeline.run(current)
            self.jobs.propose(job,binding,result,fresh=fresh)
            if result.get('approved'):
                self._automatic_accept(job,binding,fresh=fresh)
            if not result.get('approved'):
                if self._automatic_failure(job,hard=result.get('failure_kind')!='semantic'):
                    with self.mutex:self.control_failure_epoch+=1
                    self.jobs.stop_series(binding['owner'],except_job=job)
                self._abort(app,body,job,'Ответ не прошёл проверку исследовательского контура',
                            technical=result.get('failure_kind')!='semantic')
        except (ValueError,OSError,TypeError,KeyError,sqlite3.Error) as error:
            # Exact raw/step state remains private and durable. Do not retry,
            # switch model or expose provider exception text to the browser.
            try:
                check=getattr(error,'check',None)
                self.jobs.audit(job,'worker_control_stopped',dict(stage=worker_stage,
                    category=type(error).__name__,check=check if check in CONTROL_CHECKS else None,
                    retry_started=False,actual_customer_action=False))
            except (ValueError,OSError,TypeError,KeyError,sqlite3.Error):
                pass  # A failed diagnostic cannot bypass the stop below.
            with self.mutex:self.control_failure_epoch+=1
            self._automatic_failure(job,hard=True)
            self.jobs.stop_series(str(body.get('owner')or''),except_job=job)
            self.jobs.stop(str(body.get('owner')or''),job)
            self._abort(app,body,job,'Исследовательская задача остановлена; нужен журнал той же задачи')
