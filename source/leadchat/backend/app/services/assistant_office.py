"""Server-owned CRM work; the existing extension remains the CRM executor.

Availability is not authority. Original Root receipts, current Main Run/source,
and one committed physical issue are distinct gates. A lost create ACK never
produces another permission. Reports preserve evidence after Stop. Only a
trusted completion policy and a fresh original card may link and close.
"""

import math
import re
import time
import uuid

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.errors import ApiError
from app.models import AssistantDialog, User
from app.models import AssistantNativeAction as Action
from app.models import AssistantOfficeResource as Resource
from app.models import AssistantOfficeWork as Work
from app.models import AssistantResearchWork as Research
from app.services import assistant_actions, assistant_runs, conversations, leadbot_reader
from app.services import leadbot_execution_protocol as wire
from app.services.audit import write_audit

TERMINAL = {"expired", "stopped", "replaced", "waiting_notification", "completed"}
CORE_FIELDS = {
    "город",
    "вид работ",
    "вид услуг",
    "тип",
    "партнёр",
    "дата",
    "время",
    "комментарий партнёра",
    "комментарий",
    "служебный комментарий",
    "имя / аккаунт объявления",
    "телефон",
    "имя клиента",
}
CONDITIONAL_FIELDS = {
    "улица",
    "дом",
    "квартира",
    "населённый пункт",
    "подъезд",
    "этаж",
    "отзыв",
    "звонок перед выездом",
    "домофон",
}
BASES = {
    "bt": "https://bt-lead-centre.ru",
    "kp": "https://kp-lead-centre.ru",
    "mnc": "https://mnc-lead-centre.ru",
}
FORM_KEYS = (
    "ok",
    "auto_enabled",
    "revision",
    "form_reference",
    "intake_form_ready",
    "completion_mode",
    "form_extraction",
    "routing",
    "facts",
    "lead",
    "crm_flags",
    "crm_route",
    "research_job_id",
    "policy_version",
    "accepted_visit",
)
TTL = 90


def _json(value):
    return wire.encode(value).decode()


def _object(raw):
    value = wire.decode((raw or "{}").encode(), 1000000)
    if not isinstance(value, dict):
        raise ValueError("Original bounded office object required")
    return value


def _view(work):
    return {
        "work_id": work.key,
        "cid": str(work.conversation_id),
        "state": work.stage,
        "source_sha256": work.source_hash,
        "snapshot_hash": work.snapshot_hash,
        "deadline": work.deadline,
        "execution_allowed": False,
        "customer_effect_confirmed": False,
        "crm_request_id": work.created_id,
        "created_id_verified": work.stage in ("waiting_notification", "completed"),
        "telegram_confirmed": work.reason_code
        in ("native_notification_confirmed", "native_notification_confirmed_review"),
        "dialog_closed": work.stage == "completed",
        **(
            {"completion_mode": "crm_only"}
            if work.reason_code == "native_crm_only_confirmed"
            else {}
        ),
    }


def _binding(row, live):
    return all(
        getattr(row, k) == getattr(live, k)
        for k in ("principal_id", "operator_id", "run_id", "generation")
    ) and row.versions == _json(live.versions)


def _versions(work):
    value = wire.decode(work.versions.encode(), 16000)
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(not isinstance(v, str) or not v or len(v) > 256 for v in value)
    ):
        raise ValueError("Original four runtime versions required")
    return tuple(value)


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,11}", value):
        raise ValueError("Exact new numeric CRM ID required")
    return value


class NativeOffice:
    def __init__(
        self,
        sessions,
        redis,
        *,
        admission,
        actions=None,
        enabled=False,
        clock=time.time,
        notifications_enabled=False,
        crm_only=False,
    ):
        if (
            not isinstance(sessions, async_sessionmaker)
            or not isinstance(admission, assistant_runs.RuntimeAdmission)
            or type(enabled) is not bool
            or type(notifications_enabled) is not bool
            or type(crm_only) is not bool
            or crm_only
            and (not enabled or notifications_enabled)
            or notifications_enabled
            and not enabled
            or not callable(clock)
            or actions is not None
            and (
                not isinstance(actions, assistant_actions.NativeActionCoordinator)
                or actions.sessions is not sessions
                or actions.redis is not redis
                or actions.admission != admission
                or not actions.enabled
            )
        ):
            raise ValueError("Trusted native office dependencies required")
        self.sessions, self.redis, self.admission = sessions, redis, admission
        self.actions, self.enabled, self.clock = actions, enabled, clock
        self.notifications_enabled = notifications_enabled
        self.crm_only = crm_only

    def _now(self):
        now = self.clock()
        if not math.isfinite(now):
            raise ValueError("Finite office observation time required")
        return now

    async def _event(self, db, work, kind):
        await write_audit(
            db,
            user_id=work.principal_id,
            action="assistant.office_step",
            entity="conversation",
            entity_id=str(work.conversation_id),
            details={
                "office_work_id": work.key,
                "kind": kind,
                "state": work.stage,
                "operator_id": str(work.operator_id),
                "run_id": str(work.run_id),
                "generation": work.generation,
                "source_sha256": work.source_hash,
                "form_sha256": work.form_hash,
                "proposal_sha256": work.snapshot_hash,
                "crm_request_id": work.created_id,
                "observed_at": self._now(),
                "crm_effect_independently_confirmed": False,
                "telegram_confirmed": _view(work)["telegram_confirmed"],
                "dialog_closed": _view(work)["dialog_closed"],
            },
        )

    async def _authority(self, db, live):
        if not self.enabled or not isinstance(live, assistant_runs.RunAuthority):
            raise ValueError("Native office is disabled")
        await db.scalar(select(User).where(User.id == live.principal_id).with_for_update())
        current = await assistant_runs.authority(
            db, live.principal_id, live.run_id, live.generation, self.admission
        )
        if current != live or live.mode != "auto":
            raise ValueError("Original automatic Run required")

    async def _source(self, db, work, live, *, require_deadline=True):
        await self._authority(db, live)
        if not _binding(work, live) or require_deadline and work.deadline <= self._now():
            raise ValueError("Original office Run or deadline changed")
        probe = Action(
            principal_id=work.principal_id,
            operator_id=work.operator_id,
            run_id=work.run_id,
            generation=work.generation,
            versions=work.versions,
            conversation_id=work.conversation_id,
            dialog_version=work.dialog_version,
            source_hash=work.source_hash,
            kind="create_crm",
        )
        await assistant_actions._fresh(db, probe, self.admission)

    async def _resource(self, db):
        # Additive migration seeds this singleton. ON CONFLICT also supports
        # fresh metadata-only test DBs and concurrent first startup.
        dialect = db.get_bind().dialect.name
        insert = sqlite_insert if dialect == "sqlite" else pg_insert
        await db.execute(insert(Resource).values(name="crm").on_conflict_do_nothing())
        return await db.scalar(
            select(Resource)
            .where(Resource.name == "crm")
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def _availability_key(self, live):
        return "assistant-native:office-executor:v1:" + str(live.principal_id)

    def _available_value(self, raw, live, executor=None):
        try:
            if isinstance(raw, bytes):
                raw = raw.decode()
            value = _object(raw)
            now = self._now()
            return bool(
                set(value) == {"executor", "run", "operator", "generation", "versions", "seen"}
                and value["run"] == str(live.run_id)
                and value["operator"] == str(live.operator_id)
                and value["generation"] == live.generation
                and value["versions"] == list(live.versions)
                and isinstance(value["executor"], str)
                and str(uuid.UUID(value["executor"])) == value["executor"]
                and (executor is None or value["executor"] == str(executor))
                and type(value["seen"]) in (int, float)
                and math.isfinite(value["seen"])
                and -1 <= now - value["seen"] < TTL
            )
        except (ValueError, TypeError, KeyError, AttributeError):
            return False

    async def available(self, live, executor=None):
        if not self.enabled:
            return False
        try:
            raw = await self.redis.get(self._availability_key(live))
            return self._available_value(raw, live, executor)
        except Exception:
            return False

    async def heartbeat(self, live, executor):
        if not isinstance(executor, uuid.UUID):
            raise ValueError("Exact office executor required")
        async with self.sessions() as db:
            await self._authority(db, live)
        key = self._availability_key(live)
        async with self.redis.pipeline(transaction=True) as pipe:
            await pipe.watch(key)
            old = await pipe.get(key)
            if self._available_value(old, live) and not self._available_value(old, live, executor):
                return {"available": False, "state": "another_executor", "run_started": False}
            pipe.multi()
            pipe.set(
                key,
                _json(
                    {
                        "executor": str(executor),
                        "run": str(live.run_id),
                        "operator": str(live.operator_id),
                        "generation": live.generation,
                        "versions": live.versions,
                        "seen": self._now(),
                    }
                ),
                ex=TTL,
            )
            await pipe.execute()
        return {"available": True, "state": "idle", "run_started": False}

    async def capacity(self, live, cid, source_hash):
        if not await self.available(live):
            return {"state": "waiting_executor", "model_started": False}
        key, now = live.work_key(cid, source_hash, "intake_form"), self._now()
        async with self.sessions() as db:
            resource = await self._resource(db)
            await self._authority(db, live)
            enrolled = await db.get(AssistantDialog, cid, populate_existing=True)
            if enrolled is None:
                raise ValueError("Actual enrollment required")
            candidate = Work(
                key=key,
                principal_id=live.principal_id,
                operator_id=live.operator_id,
                run_id=live.run_id,
                generation=live.generation,
                conversation_id=cid,
                dialog_version=enrolled.version,
                versions=_json(live.versions),
                source_hash=source_hash,
                stage="awaiting_form",
                deadline=now + 300,
                client_lease_until=0,
            )
            await self._source(db, candidate, live)
            work = await db.get(Work, key, populate_existing=True)
            if work is not None:
                if not _binding(work, live):
                    return {"state": "prior_attempt_review", "model_started": False}
                if work.deadline <= now or work.stage in TERMINAL:
                    if work.create_issued_at is None and work.stage not in TERMINAL:
                        work.stage = "expired"
                    if resource.work_key == key and work.create_issued_at is None:
                        resource.work_key = None
                        await self._event(db, work, "unissued_capacity_expired")
                    await db.commit()
                    return _view(work) | {"capacity": False}
                await self._source(db, work, live)
                return _view(work) | {"capacity": work.stage not in TERMINAL}
            if resource.work_key:
                prior = await db.get(Work, resource.work_key, populate_existing=True)
                if prior is None:
                    raise ValueError("Original CRM resource work missing")
                if prior.create_issued_at is not None and prior.stage != "waiting_notification":
                    return {"state": "crm_reconciliation_required", "model_started": False}
                replaced = prior.conversation_id == cid and prior.source_hash != source_hash
                if prior.deadline > now and prior.stage not in TERMINAL and not replaced:
                    return {"state": "crm_busy", "model_started": False}
                if prior.stage not in TERMINAL:
                    prior.stage = "replaced" if replaced else "expired"
                    prior.reason_code = "office_source_changed" if replaced else "office_deadline"
                    await self._event(db, prior, "unissued_capacity_released")
                resource.work_key = None
            # A new source/new controller cannot hide a prior issued create.
            issued = await db.scalar(
                select(Work.key)
                .where(Work.conversation_id == cid, Work.create_issued_at.is_not(None))
                .limit(1)
            )
            if issued:
                return {"state": "created_review", "model_started": False}
            work = candidate
            db.add(work)
            await db.flush()
            resource.work_key = key
            await self._event(db, work, "capacity_reserved_before_model")
            await db.commit()
            return _view(work) | {"capacity": True}

    async def observe_owned(self, live, cid):
        """A prior create belongs to the CID, never a new client turn/Run."""
        async with self.sessions() as db:
            await self._authority(db, live)
            rows = list(
                (
                    await db.scalars(
                        select(Work)
                        .where(Work.conversation_id == cid)
                        .order_by(Work.create_issued_at.desc().nulls_last(), Work.deadline.desc())
                    )
                ).all()
            )
            snapshot = await leadbot_reader._snapshot(
                db,
                str(cid),
                {
                    "principal_id": str(live.principal_id),
                    "operator_id": str(live.operator_id),
                },
            )
            if snapshot is None:
                raise ValueError("Current authorized source required")
            for work in rows:
                if work.create_issued_at is not None:
                    return (
                        _view(work)
                        if _binding(work, live) and work.source_hash == snapshot[0]["source_sha256"]
                        else {"state": "created_review", "execution_allowed": False}
                    )
            for work in rows:
                if work.source_hash != snapshot[0]["source_sha256"]:
                    continue
                if not _binding(work, live):
                    return {"state": "prior_attempt_review", "execution_allowed": False}
                if work.stage != "awaiting_form":
                    return _view(work)
            return None

    async def status(self, live, key, executor, lease):
        """Original metadata only, including lost card ACK; never renew a grant."""
        async with self.sessions() as db:
            work, _ = await self._own(db, live, key, current=False)
            if work.executor_id != executor or work.client_lease_id != lease:
                raise ValueError("Original evidence executor required")
            return _view(work) | {"reason_code": work.reason_code}

    async def _form(self, db, work):
        research, screen = (
            await db.get(Research, work.research_key),
            await db.get(Action, work.screen_key),
        )
        if (
            research is None
            or screen is None
            or research.stage != "ready"
            or research.purpose != "intake_form"
            or screen.kind != "screen"
            or screen.stage != "screened"
            or any(
                getattr(row, k) != getattr(work, k)
                for row in (research, screen)
                for k in (
                    "principal_id",
                    "operator_id",
                    "run_id",
                    "generation",
                    "conversation_id",
                    "dialog_version",
                    "versions",
                    "source_hash",
                )
            )
            or work.form_hash != wire.sha((research.result or "").encode())
            or work.screen_hash != wire.sha((screen.result or "").encode())
        ):
            raise ValueError("Immutable original form and read-only screen required")
        form, plan = _object(research.result), _object(screen.result)
        if form.get("completion_mode", "telegram") != ("crm_only" if self.crm_only else "telegram"):
            raise ValueError("Root form mode differs from trusted Main completion policy")
        fields = plan.get("crm_required_fields")
        if (
            form.get("ok") is not True
            or form.get("auto_enabled") is not False
            or form.get("can_send_or_create") is not False
            or form.get("needs_operator") is not False
            or form.get("reply") != ""
            or form.get("intake_form_ready") is not True
            or not isinstance(form.get("form_reference"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", form["form_reference"])
            or not isinstance(form.get("form_extraction"), dict)
            or form["form_extraction"].get("ok") is not True
            or not isinstance(form["form_extraction"].get("lead"), dict)
            or not isinstance(form.get("research_job_id"), str)
            or plan.get("eligible") is not True
            or plan.get("step") != "prepare_crm"
            or plan.get("source_sha256") != work.source_hash
            or plan.get("revision") != form.get("revision")
            or not isinstance(plan.get("message_revision"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", plan["message_revision"])
            or form.get("policy_version") != _versions(work)[0]
            or not isinstance(fields, list)
            or any(
                not isinstance(f, str) or f not in CORE_FIELDS | CONDITIONAL_FIELDS for f in fields
            )
        ):
            raise ValueError("Original accepted complete form contract required")
        if self._now() >= min(work.deadline, research.deadline, screen.deadline):
            raise ValueError("Original office form deadline expired")
        return form, plan, sorted(CORE_FIELDS | set(fields))

    async def offer(self, live, cid, source_hash, *, research_key, screen_key):
        async with self.sessions() as db:
            resource = await self._resource(db)
            work = await db.get(Work, live.work_key(cid, source_hash, "intake_form"))
            if work is None or resource.work_key != work.key:
                raise ValueError("Original CRM capacity reservation required")
            await self._source(db, work, live)
            if work.stage != "awaiting_form":
                return _view(work)
            research, screen = (
                await db.get(Research, research_key),
                await db.get(Action, screen_key),
            )
            if research is None or screen is None:
                raise ValueError("Original office inputs required")
            work.research_key, work.screen_key = research_key, screen_key
            work.form_hash = wire.sha((research.result or "").encode())
            work.screen_hash = wire.sha((screen.result or "").encode())
            work.deadline = min(work.deadline, research.deadline, screen.deadline)
            _, _, fields = await self._form(db, work)
            work.required_fields, work.stage = _json(fields), "ready"
            await self._event(db, work, "original_form_accepted")
            await db.commit()
            return _view(work)

    async def _own(self, db, live, key, *, current=True):
        if not self.enabled or not isinstance(live, assistant_runs.RunAuthority):
            raise ValueError("Enabled original office required")
        resource = await self._resource(db)
        work = await db.scalar(
            select(Work)
            .where(Work.key == key)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if work is None or not _binding(work, live):
            raise ValueError("Own original office work required")
        if current:
            await self._source(db, work, live)
            if resource.work_key != work.key:
                raise ValueError("Original CRM resource ownership changed")
        return work, resource

    def _lease(self, work, executor, lease):
        if (
            not isinstance(executor, uuid.UUID)
            or not isinstance(lease, uuid.UUID)
            or work.executor_id != executor
            or work.client_lease_id != lease
            or work.client_lease_until <= self._now()
        ):
            raise ValueError("Exact fresh office executor lease required")

    async def poll(self, live, executor):
        if not await self.available(live, executor):
            return {"state": "waiting_executor", "execution_allowed": False}
        async with self.sessions() as db:
            resource = await self._resource(db)
            await self._authority(db, live)
            if resource.work_key is None:
                return {"state": "idle", "execution_allowed": False}
            work = await db.get(Work, resource.work_key, populate_existing=True)
            if work is None or not _binding(work, live):
                return {"state": "crm_busy", "execution_allowed": False}
            await self._source(db, work, live)
            if work.stage == "awaiting_form":
                return _view(work)
            # After issue, executor ownership never moves to a different copy.
            # Recovery reads reports; it cannot adopt/repeat an old create.
            if work.create_issued_at is not None:
                # The original executor may finish its bounded card read or
                # same-ID followup. This refreshes ownership only, never the
                # original form/Root grant/physical create permission.
                if work.executor_id == executor and work.client_lease_id is not None:
                    await self._form(db, work)
                    work.client_lease_until = min(work.deadline, self._now() + TTL)
                    await db.commit()
                    return _view(work) | {
                        "reconciliation_only": True,
                        "lease_id": str(work.client_lease_id),
                        "lease_until": work.client_lease_until,
                    }
                return _view(work) | {"reconciliation_only": True}
            if work.executor_id not in (None, executor) and work.client_lease_until > self._now():
                return {"state": "crm_busy", "execution_allowed": False}
            form, plan, fields = await self._form(db, work)
            if work.executor_id != executor or work.client_lease_until <= self._now():
                if work.stage not in ("ready", "prepared", "authorizing", "office_reserved"):
                    return _view(work) | {"reconciliation_only": True}
                work.executor_id, work.client_lease_id = executor, uuid.uuid4()
                await self._event(db, work, "executor_leased")
            work.client_lease_until = min(work.deadline, self._now() + TTL)
            await db.commit()
            return _view(work) | {
                "supports_duplicate_stop": True,
                "lease_id": str(work.client_lease_id),
                "lease_until": work.client_lease_until,
                "source_sha256": work.source_hash,
                "form": {k: form[k] for k in FORM_KEYS if k in form},
                "message_revision": plan["message_revision"],
                "required_fields": fields,
                "deadline": work.deadline,
                "proposal": _object(work.proposal) if work.proposal is not None else None,
            }

    async def prepare(self, live, key, executor, lease, proposal):
        async with self.sessions() as db:
            work, _ = await self._own(db, live, key)
            self._lease(work, executor, lease)
            form, plan, _ = await self._form(db, work)
            packet = {
                "v": 1,
                "command_id": str(uuid.uuid4()),
                "operation": "reserve_office",
                "principal_id": str(live.principal_id),
                "operator_id": str(live.operator_id),
                "run_id": str(live.run_id),
                "generation": live.generation,
                "arguments": {
                    "cid": str(work.conversation_id),
                    "source_sha256": work.source_hash,
                    "kind": "create_crm",
                    "operation_id": plan["operation_id"],
                    "revision": plan["revision"],
                    "proposal": proposal,
                    "snapshot_hash": wire.sha(wire.encode(proposal)),
                },
            }
            wire.check(packet)  # Reject credential keys/extra history before the SQL journal.
            if proposal["form_reference"] != form["form_reference"]:
                raise ValueError("Original accepted form reference changed")
            original = _json(proposal)
            if work.proposal is not None:
                if work.proposal != original:
                    raise ValueError("Original office proposal is immutable")
                return _view(work)
            if work.stage != "ready":
                raise ValueError("Office work is not ready for preparation")
            work.proposal = original
            work.snapshot_hash, work.stage = wire.sha(original.encode()), "prepared"
            await self._event(db, work, "original_proposal_prepared")
            await db.commit()
            return _view(work)

    async def request_create(self, live, key, executor, lease):
        async with self.sessions() as db:
            work, _ = await self._own(db, live, key)
            self._lease(work, executor, lease)
            await self._form(db, work)
            action = await db.get(Action, work.action_key) if work.action_key else None
            if (
                work.create_issued_at is not None
                or work.stage not in ("office_reserved", "consume_requested")
                or action is None
                or action.kind != "create_crm"
                or action.stage
                not in ("office_reserved", "consume_action", "apply", "office_ready")
            ):
                raise ValueError("Original reserved office create required")
            if work.stage != "consume_requested":
                work.stage = "consume_requested"
                await self._event(db, work, "create_consumption_requested")
            await db.commit()
            return _view(work)

    async def issue_create(self, live, key, executor, lease):
        async with self.sessions() as db:
            work, _ = await self._own(db, live, key)
            self._lease(work, executor, lease)
            await self._form(db, work)
            if work.create_issued_at is not None:
                return _view(work) | {"reconciliation_only": True}
            action = await db.scalar(
                select(Action)
                .where(Action.key == work.action_key)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if work.stage != "consume_requested" or action is None:
                raise ValueError("Original requested create required")
            if action.stage != "office_ready":
                return _view(work)  # Pending, never an inferred create permission.
            if (
                action.kind != "create_crm"
                or not _binding(action, live)
                or action.conversation_id != work.conversation_id
                or action.source_hash != work.source_hash
                or action.deadline <= self._now()
                or _object(action.reference).get("proposal") != _object(work.proposal)
                or _object(action.reference).get("snapshot_hash") != work.snapshot_hash
            ):
                raise ValueError("Original office action binding changed")
            await assistant_actions._fresh(db, action, self.admission)
            _, receipt = await assistant_actions._consumed(db, action, states=("office_ready",))
            if (
                receipt["dispatch_before"] <= self._now()
                or receipt.get("snapshot_hash") != work.snapshot_hash
                or receipt.get("form_reference") != _object(work.proposal)["form_reference"]
            ):
                raise ValueError("Original create dispatch window changed")
            changed = await db.scalar(
                update(Work)
                .where(
                    Work.key == key,
                    Work.stage == "consume_requested",
                    Work.create_issued_at.is_(None),
                )
                .values(stage="create_started", create_issued_at=self._now())
                .returning(Work.key)
            )
            if changed is None:
                await db.rollback()
                original = await db.get(Work, key, populate_existing=True)
                return _view(original) | {"reconciliation_only": True}
            action.stage = "office_issued"
            await self._event(db, work, "physical_create_permission_issued")
            await db.commit()  # Lost ACK means reconcile, never issue a second permission.
            return _view(work) | {
                "execution_allowed": True,
                "kind": "create_crm",
                "snapshot_hash": work.snapshot_hash,
                "source_sha256": work.source_hash,
                "operator_id": str(work.operator_id),
                "dispatch_before": receipt["dispatch_before"],
            }

    def _reported(self, work, executor, lease, report):
        # The original executor can preserve evidence after Stop/lease expiry.
        # No fresh permission or successful completion is inferred from it.
        if work.executor_id != executor or work.client_lease_id != lease:
            raise ValueError("Original evidence executor required")
        if work.create_issued_at is None or work.proposal is None:
            raise ValueError("An issued physical create is required before reporting an ID")
        if not isinstance(report, dict) or set(report) != {"id", "url"}:
            raise ValueError("Only bounded original ID/URL evidence is accepted")
        crm_id, direction = _id(report["id"]), _object(work.proposal)["dir"]
        if report["url"] != BASES[direction] + "/admin/domain/customer-request/update?id=" + crm_id:
            raise ValueError("Exact original CRM card origin/path/ID required")
        if work.created_id not in (None, crm_id):
            raise ValueError("Original reported CRM ID cannot change")
        return crm_id

    async def capture_created(self, live, key, executor, lease, report):
        async with self.sessions() as db:
            work, _ = await self._own(db, live, key, current=False)
            crm_id = self._reported(work, executor, lease, report)
            if work.created_report is not None and work.created_report != _json(report):
                raise ValueError("Original create report is immutable")
            first_report = work.created_report is None
            work.created_id, work.created_report = crm_id, _json(report)
            if work.stage not in ("waiting_notification", "created_review"):
                work.stage = "created_unverified"
            if first_report:
                await self._event(db, work, "created_id_reported_unverified")
            await db.commit()
            return _view(work)

    async def followup(self, live, key, executor, lease, crm_id, kind):
        async with self.sessions() as db:
            work, _ = await self._own(db, live, key)
            self._lease(work, executor, lease)
            await self._form(db, work)
            proposal = _object(work.proposal)
            if (
                work.create_issued_at is None
                or work.created_id != _id(crm_id)
                or work.stage != "created_unverified"
                or kind not in ("partner_note", "customer_contact")
                or kind == "partner_note"
                and not proposal["lead"].get("partner_note")
                or kind == "customer_contact"
                and not (proposal["lead"].get("addr") or proposal["lead"].get("phones_extra"))
            ):
                raise ValueError("Exact planned same-ID followup required")
            issued = _object(work.followup_issued)
            if kind in issued:
                return _view(work) | {"reconciliation_only": True}
            issued[kind] = self._now()
            work.followup_issued = _json(issued)
            await self._event(db, work, "followup_permission_issued:" + kind)
            await db.commit()
            return _view(work) | {
                "execution_allowed": True,
                "kind": kind,
                "crm_request_id": crm_id,
                "snapshot_hash": work.snapshot_hash,
                "dispatch_before": min(work.deadline, self._now() + 10),
            }

    async def capture_card(self, live, key, executor, lease, report):
        async with self.sessions() as db:
            work, resource = await self._own(db, live, key)
            self._lease(work, executor, lease)
            form, plan, required = await self._form(db, work)
            if (
                not isinstance(report, dict)
                or set(report)
                != {
                    "id",
                    "url",
                    "form_reference",
                    "snapshot_hash",
                    "policy_version",
                    "message_revision",
                    "verified",
                    "warnings",
                }
                or work.created_id != _id(report["id"])
                or report["form_reference"] != form["form_reference"]
                or report["snapshot_hash"] != work.snapshot_hash
                or report["policy_version"] != form.get("policy_version")
                or report["message_revision"] != plan["message_revision"]
                or report["warnings"] != []
            ):
                raise ValueError("Original source-bound CRM card receipt required")
            self._reported(work, executor, lease, {"id": report["id"], "url": report["url"]})
            verified = report["verified"]
            if (
                not isinstance(verified, dict)
                or set(verified) != {"checked", "diffs", "fields"}
                or verified["diffs"] != []
                or not isinstance(verified["fields"], list)
                or any(not isinstance(x, str) for x in verified["fields"])
                or not set(required).issubset(verified["fields"])
                or type(verified["checked"]) is not int
                or verified["checked"] < len(set(verified["fields"]))
                or verified["checked"] > 100
            ):
                raise ValueError("Every required actual CRM field must have been read")
            twins = await conversations.crm_request_twins(
                db, work.created_id, except_id=work.conversation_id
            )
            work.card_receipt = _json(
                {
                    "provenance": "extension_original_card_read",
                    "independent_telegram_confirmation": False,
                    "report": report,
                    "same_request_conversation_ids": twins,
                }
            )
            work.stage = "created_review" if twins else "waiting_notification"
            await self._event(
                db, work, "card_read_duplicate" if twins else "card_read_by_extension"
            )
            if not twins:
                if self.notifications_enabled:
                    from app.services.assistant_notifications import seed

                    await seed(db, work, self._now())
                resource.work_key = None  # The original verified card remains durable.
            await db.commit()
            result = _view(work) | {"duplicate_found": bool(twins)}
        if self.crm_only and not twins:
            from app.services.assistant_crm_completion import NativeCRMCompletion

            result = await NativeCRMCompletion(self).complete(key)
            return result | {"duplicate_found": False}
        return result

    async def fail(self, live, key, executor, lease, stop_reason=None):
        async with self.sessions() as db:
            work, resource = await self._own(db, live, key, current=False)
            if work.executor_id != executor or work.client_lease_id != lease:
                raise ValueError("Original executor required")
            if work.stage in ("waiting_notification", "completed"):
                return _view(work)
            if work.stage == "stopped" and work.create_issued_at is None:
                return _view(work) | {"reason_code": work.reason_code}
            event = "executor_stopped"
            if work.create_issued_at is not None:
                work.stage, work.reason_code = "created_review", "create_result_unknown"
                event = "executor_result_unknown"
                if work.created_id is None:
                    await assistant_runs.block(db, live, "native_delivery")
                else:
                    try:
                        # Control observation only. No permission is emitted
                        # or renewed after the original deadline.
                        await self._source(db, work, live, require_deadline=False)
                    except (ValueError, ApiError):
                        pass  # A new client source/takeover is not this incident.
                    else:
                        await assistant_runs.block(db, live, "native_delivery")
            else:
                if (
                    stop_reason == "crm_existing_request"
                    and work.stage == "office_reserved"
                    and resource.work_key == key
                ):
                    work.reason_code = stop_reason
                    event = "duplicate_found_before_create"
                else:
                    work.reason_code = "executor_stopped_before_create"
                work.stage = "stopped"
                if resource.work_key == key:
                    resource.work_key = None
            await self._event(db, work, event)
            await db.commit()
            return _view(work) | {"reason_code": work.reason_code}

    async def advance(self, key):
        if not self.enabled or self.actions is None:
            return {"state": "disabled", "execution_allowed": False}
        if self.crm_only:
            async with self.sessions() as db:
                candidate = await db.get(Work, key)
                card_pending = candidate is not None and candidate.stage == "waiting_notification"
            if card_pending:
                from app.services.assistant_crm_completion import NativeCRMCompletion

                return await NativeCRMCompletion(self).complete(key)
        if self.notifications_enabled:
            async with self.sessions() as db:
                candidate = await db.get(Work, key)
                notification_pending = (
                    candidate is not None and candidate.stage == "waiting_notification"
                )
            if notification_pending:
                from app.services.assistant_notifications import NativeNotificationCompletion

                return await NativeNotificationCompletion(self).advance(key)
        async with self.sessions() as db:
            work = await db.get(Work, key)
            if work is None:
                raise ValueError("Existing office work required")
            live = assistant_runs.RunAuthority(
                work.principal_id,
                work.operator_id,
                work.run_id,
                work.generation,
                "auto",
                _versions(work),
            )
            try:
                await self._source(db, work, live)
                await self._form(db, work)
            except (ValueError, ApiError):
                # Preserve issued unknown effects. Never clear an old create fence.
                await db.refresh(work)
                if work.create_issued_at is None and work.stage not in TERMINAL:
                    work.stage = "expired" if work.deadline <= self._now() else "stopped"
                    await self._event(db, work, "authorization_no_longer_current")
                    await db.commit()
                return _view(work)
            saved = (
                work.stage,
                work.conversation_id,
                work.source_hash,
                work.research_key,
                work.screen_key,
                work.proposal,
                work.action_key,
            )
        stage, cid, source, research_key, screen_key, proposal, action_key = saved
        if stage == "prepared":
            action = await self.actions.office(
                live,
                cid,
                source,
                research_key=research_key,
                screen_key=screen_key,
                proposal=_object(proposal),
            )
            async with self.sessions() as db:
                work, _ = await self._own(db, live, key)
                if work.stage == "prepared":
                    work.action_key, work.stage = action["action_key"], "authorizing"
                    await self._event(db, work, "private_authorization_started")
                    await db.commit()
                return _view(work)
        if stage == "consume_requested":
            await self.actions.request_office_consume(live, action_key)
        async with self.sessions() as db:
            work, _ = await self._own(db, live, key)
            action = await db.get(Action, work.action_key) if work.action_key else None
            if action and action.stage in ("blocked", "stopped", "expired"):
                work.stage, work.reason_code = "stopped", "office_authorization"
                # _own/_form just rechecked the same live source and Run.
                # A current hard failure cannot bypass the ordinary driver's
                # global stop by hiding behind an office status row.
                await assistant_runs.block(db, live, "native_source")
                await self._event(db, work, "private_authorization_stopped")
            elif action and action.stage == "office_reserved" and work.stage == "authorizing":
                work.stage = "office_reserved"
                await self._event(db, work, "private_authorization_reserved")
            await db.commit()
            return _view(work)

    async def due(self):
        if not self.enabled:
            return []
        async with self.sessions() as db:
            ordinary = list(
                (
                    await db.scalars(
                        select(Work.key)
                        .where(Work.stage.in_(("prepared", "authorizing", "consume_requested")))
                        .order_by(Work.deadline, Work.key)
                        .limit(100)
                    )
                ).all()
            )
        if self.notifications_enabled:
            from app.services.assistant_notifications import NativeNotificationCompletion

            ordinary.extend(await NativeNotificationCompletion(self).due())
        if self.crm_only:
            async with self.sessions() as db:
                ordinary.extend(
                    await db.scalars(
                        select(Work.key)
                        .where(Work.stage == "waiting_notification")
                        .order_by(Work.deadline, Work.key)
                        .limit(100)
                    )
                )
        return list(dict.fromkeys(ordinary))[:100]
