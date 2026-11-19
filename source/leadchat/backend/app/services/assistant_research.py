"""Durable short research steps, with no customer or CRM action authority.

Commit the exact command before transport. After a crash observe the original
command; never submit it twice. No transaction/browser lease spans network or
model work. Source bodies stay behind the existing guarded native reader.
"""

import json
import math
import re
import time
import uuid
from collections.abc import Callable
from typing import Any, cast

from sqlalchemy import CursorResult, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import ApiError
from app.models import AssistantDialog, User
from app.models import AssistantResearchCommand as Command
from app.models import AssistantResearchResource as Resource
from app.models import AssistantResearchWork as Work
from app.services import assistant_dialogs, assistant_runs, messages
from app.services import leadbot_execution_protocol as wire
from app.services.leadbot_native_client import NativeResearchClient, NativeTransportUncertain

TERMINAL = {"ready", "parked", "blocked", "stopped", "expired"}
POLL_SECONDS = 3
LEASE_SECONDS = 60


def _json(value: object) -> str:
    return wire.encode(value).decode()


def _view(work: Work) -> dict[str, Any]:
    # Saved results are private evidence, not panel drafts or send permits.
    return {
        "work_id": work.key,
        "state": work.stage,
        "execution_allowed": False,
        "customer_effect_confirmed": False,
        "can_send_or_create": False,
        "next_poll_after_s": None if work.stage in TERMINAL else POLL_SECONDS,
    }


def ready_visual(work, live, cid, source_hash):
    """An exact finalized observation is evidence, never an action permit."""
    if work is None or work.stage != "ready" or work.purpose != "visual":
        return False
    if any(
        getattr(work, key) != value
        for key, value in {
            "principal_id": live.principal_id,
            "operator_id": live.operator_id,
            "run_id": live.run_id,
            "generation": live.generation,
            "conversation_id": cid,
            "source_hash": source_hash,
            "versions": _json(live.versions),
        }.items()
    ):
        return False
    try:
        value = wire.decode((work.result or "null").encode(), wire.MAX_RESPONSE)
        return (
            isinstance(value, dict)
            and value.get("ok") is True
            and value.get("visual_observation_ready") is True
            and value.get("human_media_review") is False
            # Assistant.finish also gives a wait/visual result an internal
            # draft ID. Purpose and the explicit visual flag keep it non-reply.
            and not value.get("reply")
            and value.get("needs_operator") is False
            and value.get("can_send_or_create") is False
            and value.get("execution_allowed") is not True
        )
    except ValueError:
        return False


def visual_source_review(data):
    """Exact signed control result, never a browser assertion or draft."""
    return (
        isinstance(data, dict)
        and data.get("ok") is True
        and data.get("code") == "research_visual_review"
        and data.get("action") == "handoff"
        and data.get("research_state") == "rejected"
        and data.get("needs_operator") is True
        and data.get("human_media_review") is False
        and data.get("retry_started") is False
        and data.get("can_send_or_create") is False
        and data.get("visual_observation_ready") is False
        and data.get("pending_research") is False
        and data.get("auto_enabled") is False
        and data.get("reply") == ""
        and not data.get("draft_id")
        and not data.get("form_reference")
        and not data.get("intake_form_ready")
        and data.get("execution_allowed", False) is False
        and data.get("customer_effect_confirmed", False) is False
    )


async def _free_visual(db, principal, operator_id, cid):
    author = await db.get(User, operator_id, populate_existing=True)
    if author is None:
        raise ApiError("assistant_stale", "Автор недоступен", status=409)
    conv = await messages.get_conversation_for_update(db, cid)
    await assistant_dialogs.check_conversation(db, conv, author)
    if (
        conv.assignee_id is not None
        or conv.claimed_by_id is not None
        or await db.get(AssistantDialog, cid) is not None
    ):
        raise ApiError("assistant_stale", "Приём обращения изменился", status=409)


async def _current(
    db: AsyncSession, work: Work, admission: assistant_runs.RuntimeAdmission
) -> None:
    live = await assistant_runs.authority(
        db, work.principal_id, work.run_id, work.generation, admission
    )
    if live.operator_id != work.operator_id or _json(live.versions) != work.versions:
        raise ApiError("assistant_run_stale", "Автор или версии изменились", status=409)
    principal = await db.get(User, work.principal_id, populate_existing=True)
    assert principal is not None  # fresh authority just checked the row
    if work.purpose == "visual" and work.dialog_version == 0:
        await _free_visual(db, principal, live.operator_id, work.conversation_id)
        return
    await assistant_dialogs.locked_job(
        db, principal, work.conversation_id, work.operator_id, work.dialog_version
    )


class NativeResearchRelay:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        admission: assistant_runs.RuntimeAdmission,
        client: NativeResearchClient,
        enabled: bool = False,
        clock: Callable[[], float] = time.time,
    ):
        if (
            type(enabled) is not bool
            or not isinstance(admission, assistant_runs.RuntimeAdmission)
            or not isinstance(client, NativeResearchClient)
            or not callable(clock)
        ):
            raise ValueError("Trusted native relay dependencies required")
        self.sessions, self.admission, self.client = sessions, admission, client
        self.enabled, self.clock = enabled, clock

    @staticmethod
    async def _resource(db):
        # A real existing singleton serializes different principals as well
        # as competing workers. A missing Work row is never a free slot.
        insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else pg_insert
        await db.execute(insert(Resource).values(name="model").on_conflict_do_nothing())
        return await db.scalar(
            select(Resource)
            .where(Resource.name == "model")
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def pending(self) -> bool:
        """Metadata-only intake backpressure, not permission or a model call."""
        async with self.sessions() as db:
            return (
                await db.scalar(
                    select(Work.key)
                    .where(Work.stage.not_in(TERMINAL), Work.deadline > self.clock())
                    .limit(1)
                )
                is not None
            )

    async def enqueue(
        self,
        live: assistant_runs.RunAuthority,
        cid: uuid.UUID,
        source_hash: str,
        purpose: str,
        *,
        preclaim: bool = False,
    ) -> dict[str, Any]:
        """Internal only, after guarded inspection/claim; not an HTTP endpoint."""
        if (
            not self.enabled
            or not isinstance(live, assistant_runs.RunAuthority)
            or type(preclaim) is not bool
            or preclaim
            and purpose != "visual"
        ):
            raise ValueError("Native relay is disabled")
        if not isinstance(source_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", source_hash):
            raise ValueError("Exact source digest required")
        key, now = live.work_key(cid, source_hash, purpose), self.clock()
        if not math.isfinite(now):
            raise ValueError("Finite clock required")
        async with self.sessions() as db:
            # Same existing-row lock as start/stop also serializes first work.
            await db.scalar(select(User).where(User.id == live.principal_id).with_for_update())
            fresh = await assistant_runs.authority(
                db, live.principal_id, live.run_id, live.generation, self.admission
            )
            if fresh != live:
                raise ApiError("assistant_run_stale", "Запуск изменился", status=409)
            principal = await db.get(User, live.principal_id)
            assert principal is not None
            if preclaim:
                await _free_visual(db, principal, live.operator_id, cid)
                dialog_version = 0  # Read-only free-source preflight, never enrollment.
            else:
                enrolled = await db.get(AssistantDialog, cid, populate_existing=True)
                if enrolled is None:
                    raise ApiError("assistant_stale", "Диалог не передан помощнику", status=409)
                await assistant_dialogs.locked_job(
                    db, principal, cid, live.operator_id, enrolled.version
                )
                dialog_version = enrolled.version
            old = await db.get(Work, key, populate_existing=True)
            if old is not None:
                return _view(old)  # New Run/version never replaces an attempt.
            resource = await self._resource(db)
            # Include an older pre-capacity Work after an upgrade. The shared
            # model's original attempt must finish before any new admission.
            prior = await db.scalar(
                select(Work)
                .where(Work.stage.not_in(TERMINAL), Work.deadline > now)
                .order_by(Work.deadline, Work.key)
                .limit(1)
            )
            if resource.work_key is not None:
                exact = await db.get(Work, resource.work_key, populate_existing=True)
                if exact is None:
                    raise ValueError("Original model resource Work missing")
                if exact.stage not in TERMINAL and exact.deadline > now:
                    prior = exact
            if prior is not None:
                # No Work, model deadline, grant or call is created for the
                # waiting CID. Do not turn ordinary queueing into a handoff.
                await db.commit()
                return {
                    "state": "waiting_model_capacity",
                    "model_started": False,
                    "needs_operator": False,
                    "execution_allowed": False,
                    "can_send_or_create": False,
                    "next_poll_after_s": POLL_SECONDS,
                }
            work = Work(
                key=key,
                principal_id=live.principal_id,
                operator_id=live.operator_id,
                conversation_id=cid,
                run_id=live.run_id,
                generation=live.generation,
                dialog_version=dialog_version,
                versions=_json(live.versions),
                source_hash=source_hash,
                purpose=purpose,
                stage="prepare",
                deadline=now + 300,
                due=now,
                lease_until=0,
            )
            db.add(work)
            await db.flush()
            resource.work_key = key
            await db.commit()
            return _view(work)

    def _command(self, work: Work) -> dict[str, Any]:
        original = work.active_command_id
        operation = "recover" if original else work.stage
        args: dict[str, Any] = (
            {"command_id": str(original)}
            if original
            else {"cid": str(work.conversation_id), "source_sha256": work.source_hash}
        )
        if original is None:
            if operation == "prepare":
                args["purpose"] = {
                    "intake_form": "intake_form_v1",
                    "visual": "visual_observation_v1",
                    "reply": "reply",
                }[work.purpose]
            else:
                binding = json.loads(work.binding or "null")
                if not isinstance(binding, dict):
                    raise ValueError("Original job binding required")
                args.update(binding)
        return wire.check(
            {
                "v": 1,
                "command_id": str(uuid.uuid4()),
                "operation": operation,
                "principal_id": str(work.principal_id),
                "operator_id": str(work.operator_id),
                "run_id": str(work.run_id),
                "generation": work.generation,
                "arguments": args,
            }
        )

    async def _begin(self, key: str) -> tuple[uuid.UUID, dict[str, Any]] | dict[str, Any]:
        now, lease = self.clock(), uuid.uuid4()
        async with self.sessions() as db:
            changed = cast(
                CursorResult[Any],
                await db.execute(
                    update(Work)
                    .where(
                        Work.key == key,
                        Work.stage.not_in(TERMINAL),
                        Work.due <= now,
                        or_(Work.lease_id.is_(None), Work.lease_until <= now),
                    )
                    .values(lease_id=lease, lease_until=now + LEASE_SECONDS)
                ),
            )
            work = await db.get(Work, key, populate_existing=True)
            if work is None:
                raise ValueError("Exact existing native work required")
            if changed.rowcount != 1:
                return _view(work)
            if work.deadline <= now:
                work.stage = "expired"
            else:
                try:
                    await _current(db, work, self.admission)
                except ApiError:
                    work.stage = "stopped"
            if work.stage in TERMINAL:
                work.lease_id, work.lease_until = None, 0
                await db.commit()
                return _view(work)
            command = self._command(work)
            command_id = uuid.UUID(command["command_id"])
            db.add(
                Command(
                    id=command_id,
                    work_key=key,
                    original_id=work.active_command_id,
                    request=_json(command),
                    state="sending",
                )
            )
            if work.active_command_id is None:
                work.active_command_id = command_id
            await db.commit()  # BEFORE network; crash -> recover, not redispatch.
        return lease, command

    @staticmethod
    def _binding(data: dict[str, Any]) -> dict[str, str]:
        result = {k: data.get(k) for k in ("request_id", "revision", "research_job_id")}
        if any(not isinstance(v, str) for v in result.values()):
            raise ValueError("Original job binding required")
        # The same bounded identifier rules, without repairing the input.
        wire.check(
            {
                "v": 1,
                "command_id": str(uuid.uuid4()),
                "operation": "status",
                "principal_id": str(uuid.uuid4()),
                "operator_id": str(uuid.uuid4()),
                "run_id": str(uuid.uuid4()),
                "generation": 1,
                "arguments": dict(cid=str(uuid.uuid4()), source_sha256="a" * 64, **result),
            }
        )
        return cast(dict[str, str], result)

    def _bind(self, work: Work, data: dict[str, Any]) -> None:
        current = self._binding(data)
        previous = json.loads(work.binding) if work.binding is not None else None
        if previous is not None and (
            any(current[k] != previous[k] for k in ("request_id", "revision"))
            or previous["research_job_id"]
            and current["research_job_id"] != previous["research_job_id"]
        ):
            raise ValueError("Original request, revision or job changed")
        work.binding = _json(current)

    def _advance(self, work: Work, data: dict[str, Any]) -> None:
        if data.get("ok") is not True:
            work.stage = "blocked"
        elif data.get("code") == "research_visual_review":
            if work.purpose != "visual" or not visual_source_review(data):
                raise ValueError("Exact read-only visual source review required")
            self._bind(work, data)
            work.stage = "parked"
        elif data.get("visual_observation_ready") is True:
            if (
                work.purpose != "visual"
                or data.get("human_media_review") is not False
                or data.get("reply")
                or data.get("needs_operator") is not False
                or data.get("can_send_or_create") is not False
                or data.get("execution_allowed") is True
            ):
                raise ValueError("Exact non-executable visual result required")
            work.stage = "ready"
        elif work.purpose == "visual" and (
            data.get("intake_form_ready") is True or data.get("draft_id") or data.get("reply")
        ):
            raise ValueError("Visual work cannot authorize a reply or form")
        elif data.get("intake_form_ready") is True and data.get("form_reference"):
            work.stage = "ready"
        elif data.get("draft_id") and data.get("validation") == []:
            work.stage = "parked" if data.get("needs_operator") is True else "ready"
        elif data.get("needs_operator") is True:
            work.stage = "parked"
        elif data.get("research_state") in ("rejected", "denied", "stopped", "cancelled"):
            work.stage = "parked"
        else:
            self._bind(work, data)
            work.stage = "finalize" if data.get("research_state") == "accepted" else "status"
        work.result, work.active_command_id = _json(data), None

    def _receipt(
        self,
        work: Work,
        original_id: uuid.UUID | None,
        command_id: uuid.UUID,
        result: dict[str, Any],
        status: int,
    ) -> None:
        if status >= 400 or result.get("ok") is not True:
            data = result.get("data")
            if (
                status == 403
                and result.get("ok") is False
                and isinstance(data, dict)
                and data.get("ok") is False
                and data.get("code") == "research_prior_attempt"
                and data.get("retry_started") is False
                and data.get("can_send_or_create") is False
            ):
                # The signed original command says this case already has an
                # attempt to inspect. It is not a new transport/model error,
                # permission to regenerate or reason to stop unrelated CIDs.
                work.stage, work.active_command_id = "parked", None
                work.result = _json(
                    {
                        "ok": False,
                        "code": "research_prior_attempt",
                        "needs_operator": True,
                        "retry_started": False,
                        "can_send_or_create": False,
                    }
                )
                return
            work.stage = "blocked"
            return
        if original_id is not None:
            recovered = result.get("data")
            if (
                not isinstance(recovered, dict)
                or recovered.get("command_id") != str(original_id)
                or recovered.get("source_or_run_not_current") is True
            ):
                raise ValueError("Exact current original command receipt required")
            state = recovered.get("command_state")
            if state == "done":
                code, original = recovered.get("original_status"), recovered.get("original_result")
                if (
                    type(code) is not int
                    or not 200 <= code <= 599
                    or not isinstance(original, dict)
                ):
                    raise ValueError("Original HTTP result required")
                self._receipt(work, None, original_id, original, code)
            elif state == "uncertain":
                existing = recovered.get("original_job")
                if isinstance(existing, dict):
                    self._bind(work, existing)
                    work.active_command_id, work.stage = None, "status"
                else:
                    work.stage = "blocked"
            elif state != "dispatching":
                raise ValueError("Unknown original command state")
        elif status == 202:
            if (
                result.get("command_id") != str(command_id)
                or result.get("command_state") != "dispatching"
            ):
                raise ValueError("Exact queued command receipt required")
        else:
            data = result.get("data")
            if not isinstance(data, dict):
                raise ValueError("Original research result required")
            self._advance(work, data)

    async def advance(self, key: str) -> dict[str, Any]:
        if not self.enabled:
            return {"state": "disabled", "can_send_or_create": False, "next_poll_after_s": None}
        selected = await self._begin(key)
        if isinstance(selected, dict):
            return selected
        lease, command = selected
        result, status, not_started = None, None, False
        try:
            # No ORM session/transaction or observer heartbeat is held here.
            result, status = await self.client.submit(command)
        except NativeTransportUncertain:
            pass  # Later observation targets the sole original command.
        except ValueError:
            not_started = True  # Typed client only raises this before HTTP.
        async with self.sessions() as db:
            row = await db.get(Command, uuid.UUID(command["command_id"]))
            work = await db.get(Work, key, populate_existing=True)
            assert row is not None and work is not None
            row.state = (
                "received" if result is not None else "not_started" if not_started else "uncertain"
            )
            row.response, row.http_status = _json(result) if result is not None else None, status
            if work.lease_id == lease:
                try:
                    await _current(db, work, self.admission)
                    if work.deadline <= self.clock():
                        work.stage = "expired"
                    elif not_started:
                        work.stage = "blocked"
                    elif result is not None and status is not None:
                        self._receipt(work, row.original_id, row.id, result, status)
                except ApiError:
                    work.stage = "stopped"
                except (ValueError, TypeError, KeyError):
                    work.stage = "blocked"
                work.due, work.lease_id, work.lease_until = self.clock() + POLL_SECONDS, None, 0
            await db.commit()
            return _view(work)

    async def due(self, limit: int = 100) -> list[str]:
        """Restart recovery only; never creates work, a Run or a call grant."""
        if not self.enabled:
            return []
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Bounded recovery batch required")
        async with self.sessions() as db:
            return list(
                await db.scalars(
                    select(Work.key)
                    .where(
                        Work.stage.not_in(TERMINAL),
                        Work.due <= self.clock(),
                        or_(Work.lease_id.is_(None), Work.lease_until <= self.clock()),
                    )
                    .order_by(Work.due, Work.key)
                    .limit(limit)
                )
            )
