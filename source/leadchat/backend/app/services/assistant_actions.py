"""Durable native claim/reply coordinator, disabled unless trusted startup enables it.

Only Root's signed original command receipts provide action references/text.
Main rechecks its own Run and full source; an archived Root permission alone
never repeats an effect. HTTP, Redis dispatch and vendor I/O hold no SQL locks.
"""

import hashlib
import math
import re
import time
import uuid
from collections.abc import Callable
from typing import Any, cast

from arq.jobs import Job
from sqlalchemy import CursorResult, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import ApiError
from app.models import AssistantDialog, Message, User
from app.models import AssistantNativeAction as Action
from app.models import AssistantNativeCommand as Command
from app.models import AssistantNativeOutbound as Outbound
from app.models import AssistantNativePart as Part
from app.models import AssistantResearchWork as Research
from app.services import assistant_dialogs, assistant_runs, leadbot_reader, messages
from app.services import leadbot_execution_protocol as wire
from app.services.avito_text import split_text
from app.services.leadbot_native_client import NativeResearchClient, NativeTransportUncertain

TERMINAL = {
    "claimed",
    "screened",
    "blocked",
    "stopped",
    "expired",
    "delivered",
    "delivery_stopped",
    "office_reserved",
    "office_ready",
    "office_issued",
}
OBSERVE = {"dispatch", "queue_observing", "queued", "queue_unknown"}


def _json(value: object) -> str:
    return wire.encode(value).decode()


def _value(raw: str | None) -> dict[str, Any]:
    result = wire.decode((raw or "null").encode(), wire.MAX_RESPONSE)
    if not isinstance(result, dict):
        raise ValueError("Exact original object required")
    return result


def _view(action: Action | None) -> dict[str, Any]:
    if action is None:
        return {"state": "blocked", "execution_allowed": False, "customer_effect_confirmed": False}
    return {
        "action_key": action.key,
        "state": action.stage,
        "message_id": str(action.message_id) if action.message_id else None,
        "execution_allowed": False,
        "customer_effect_confirmed": False,
        "next_poll_after_s": None if action.stage in TERMINAL else 0.25,
    }


def _reference(value: dict[str, Any], kind: str) -> dict[str, str]:
    keys = ["operation_id", "revision"] + (["draft_id"] if kind == "reply" else [])
    if any(
        not isinstance(value.get(k), str) or not re.fullmatch(r"[A-Za-z0-9:_-]{1,200}", value[k])
        for k in keys
    ):
        raise ValueError("Exact planned action reference required")
    return {k: value[k] for k in keys}


def _draft(value: dict[str, Any]) -> dict[str, str]:
    # The actual finalized draft has revision/draft_id, not the planner's
    # operation_id. Obtain that independently from fresh Root inspection.
    keys = ("revision", "draft_id")
    if any(
        not isinstance(value.get(k), str) or not re.fullmatch(r"[A-Za-z0-9:_-]{1,200}", value[k])
        for k in keys
    ):
        raise ValueError("Original accepted draft reference required")
    return {k: value[k] for k in keys}


async def _fresh(db: AsyncSession, action: Action, admission: assistant_runs.RuntimeAdmission):
    live = await assistant_runs.authority(
        db, action.principal_id, action.run_id, action.generation, admission
    )
    if (
        live.mode != "auto"
        or live.operator_id != action.operator_id
        or _json(live.versions) != action.versions
    ):
        raise ValueError("Original native launch changed")
    principal = await db.get(User, action.principal_id)
    author = await db.get(User, action.operator_id)
    assert principal is not None and author is not None
    if action.kind in ("reply", "screen", "create_crm"):
        if type(action.dialog_version) is not int:
            raise ValueError("Exact enrollment version required")
        await assistant_dialogs.locked_job(
            db, principal, action.conversation_id, author.id, action.dialog_version
        )
    else:
        conv = await messages.get_conversation_for_update(db, action.conversation_id)
        await assistant_dialogs.check_conversation(db, conv, author)
        if conv.assignee_id is not None or conv.claimed_by_id is not None:
            raise ValueError("Native intake only takes free conversations")
        if action.kind == "intake_screen" and await db.get(AssistantDialog, conv.id) is not None:
            raise ValueError("Previously enrolled conversations are outside free intake")
    source = await leadbot_reader._snapshot(
        db,
        str(action.conversation_id),
        {"principal_id": str(principal.id), "operator_id": str(author.id)},
    )
    if source is None or source[0]["source_sha256"] != action.source_hash:
        raise ValueError("Full native source changed")
    return principal, author


async def _consumed(
    db: AsyncSession, action: Action, *, states: tuple[str, ...] = ("apply",)
) -> tuple[Command, dict[str, Any]]:
    """Validate the own original command for BOTH claim and reply application."""
    if (
        action.stage not in states
        or not isinstance(action.grant_id, str)
        or not isinstance(action.consume_command_id, uuid.UUID)
    ):
        raise ValueError("Original once-only native application required")
    command = await db.get(Command, action.consume_command_id)
    if command is None or command.state not in ("received", "recovered"):
        raise ValueError("Own original consume receipt required")
    request, receipt = wire.check(_value(command.request)), _value(command.response)
    data = receipt.get("data")
    if (
        command.action_key != action.key
        or request["command_id"] != str(command.id)
        or request["operation"]
        != ("consume_office" if action.kind == "create_crm" else "consume_action")
        or any(
            request[k] != v
            for k, v in {
                "principal_id": str(action.principal_id),
                "operator_id": str(action.operator_id),
                "run_id": str(action.run_id),
                "generation": action.generation,
            }.items()
        )
        or request["arguments"]
        != dict(
            cid=str(action.conversation_id),
            source_sha256=action.source_hash,
            kind=action.kind,
            grant_id=action.grant_id,
            **_value(action.reference),
        )
        or command.original_id is not None
        or command.http_status != 200
        or receipt.get("ok") is not True
        or not isinstance(data, dict)
        or data != _value(action.result)
        or data.get("execution_allowed") is not True
        or data.get("grant_id") != action.grant_id
    ):
        raise ValueError("Own original consume binding changed")
    return command, data


async def attach_outbound(db: AsyncSession, key: str, msg: Message) -> None:
    """Private messages.py hook inside the original message transaction."""
    action = await db.get(Action, key, populate_existing=True)
    if action is None or action.kind != "reply" or not isinstance(action.grant_id, str):
        raise ValueError("Original native reply required")
    command, data = await _consumed(db, action)
    if (
        msg.client_message_id != "native:" + action.grant_id
        or msg.conversation_id != action.conversation_id
        or msg.sender_user_id != action.operator_id
        or msg.body != data.get("reply")
    ):
        raise ValueError("Original native message binding changed")
    db.add(
        Outbound(
            message_id=msg.id,
            message_created_at=msg.created_at,
            principal_id=action.principal_id,
            operator_id=action.operator_id,
            run_id=action.run_id,
            generation=action.generation,
            dialog_version=action.dialog_version,
            conversation_id=action.conversation_id,
            root_grant_id=action.grant_id,
            root_reference=_json(
                {
                    "action_key": key,
                    "consume_command_id": str(command.id),
                    "operation": _value(action.reference),
                }
            ),
            versions=action.versions,
            source_hash=action.source_hash,
            body_hash=hashlib.sha256((msg.body or "").encode()).hexdigest(),
            dispatch_before=data["dispatch_before"],
            state="queued",
        )
    )
    action.message_id, action.stage = msg.id, "dispatch"
    # Release the apply lease in the same transaction as the original message.
    # The original outbound dispatch_before remains unchanged.
    action.lease_id, action.lease_until = None, 0
    await db.flush()


class NativeActionCoordinator:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        admission: assistant_runs.RuntimeAdmission,
        client: NativeResearchClient,
        redis,
        job_redis=None,
        enabled: bool = False,
        clock: Callable[[], float] = time.time,
    ):
        if (
            not isinstance(admission, assistant_runs.RuntimeAdmission)
            or not isinstance(client, NativeResearchClient)
            or type(enabled) is not bool
            or not callable(clock)
            or enabled
            and job_redis is None
        ):
            raise ValueError("Trusted native action dependencies required")
        self.sessions, self.admission, self.client = sessions, admission, client
        self.redis, self.enabled, self.clock = redis, enabled, clock
        # Standard app Redis decodes text, but ARQ stores binary job payloads.
        # Trusted worker startup supplies its existing ctx['arq'] byte client.
        self.job_redis = job_redis

    async def enqueue(
        self,
        live: assistant_runs.RunAuthority,
        cid: uuid.UUID,
        source_hash: str,
        *,
        research_key: str | None = None,
    ):
        return await self._enqueue(
            live,
            cid,
            source_hash,
            kind="reply" if research_key is not None else "claim",
            research_key=research_key,
        )

    async def screen(self, live: assistant_runs.RunAuthority, cid: uuid.UUID, source_hash: str):
        """Read-only plan of an already enrolled CID, never an action allowance."""
        return await self._enqueue(live, cid, source_hash, kind="screen")

    async def intake_screen(self, live, cid, source_hash):
        """Read-only free-source screen; no claim/reservation/consume."""
        return await self._enqueue(live, cid, source_hash, kind="intake_screen")

    async def office(self, live, cid, source_hash, *, research_key, screen_key, proposal):
        """Prepare the original create authority; this never submits a CRM form."""
        return await self._enqueue(
            live,
            cid,
            source_hash,
            kind="create_crm",
            research_key=research_key,
            office=(screen_key, proposal),
        )

    async def request_office_consume(self, live, key):
        """Explicit JIT intent. The ordinary observer still owns private I/O."""
        if (
            not self.enabled
            or not isinstance(live, assistant_runs.RunAuthority)
            or live.mode != "auto"
        ):
            raise ValueError("Enabled original office launch required")
        async with self.sessions() as db:
            await db.scalar(select(User).where(User.id == live.principal_id).with_for_update())
            action = await db.scalar(
                select(Action)
                .where(Action.key == key)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                action is None
                or action.kind != "create_crm"
                or any(
                    getattr(action, k) != getattr(live, k)
                    for k in ("principal_id", "operator_id", "run_id", "generation")
                )
            ):
                raise ValueError("Own original office reservation required")
            await _fresh(db, action, self.admission)
            if action.stage == "office_reserved":
                if action.deadline <= self.clock() or action.active_command_id is not None:
                    raise ValueError("Office reservation deadline changed")
                action.stage, action.due = "consume_action", self.clock()
                await db.commit()
            return _view(action)

    async def _enqueue(
        self,
        live: assistant_runs.RunAuthority,
        cid: uuid.UUID,
        source_hash: str,
        *,
        kind: str,
        research_key: str | None = None,
        office=None,
    ):
        if (
            not self.enabled
            or not isinstance(live, assistant_runs.RunAuthority)
            or live.mode != "auto"
            or not isinstance(cid, uuid.UUID)
            or not isinstance(source_hash, str)
            or not re.fullmatch(r"[a-f0-9]{64}", source_hash)
            or kind not in ("claim", "reply", "screen", "intake_screen", "create_crm")
            or (kind == "create_crm") != (office is not None)
        ):
            raise ValueError("Enabled exact native intake required")
        now = self.clock()
        if not math.isfinite(now):
            raise ValueError("Finite original deadline required")
        identity = [str(live.principal_id), str(live.operator_id), str(cid), source_hash, kind]
        if kind in ("screen", "intake_screen"):
            # A new Run can re-read a plan, not generate or repeat an effect.
            identity.extend([str(live.run_id), str(live.generation), _json(live.versions)])
        async with self.sessions() as db:
            await db.scalar(select(User).where(User.id == live.principal_id).with_for_update())
            visual_key = None
            if kind in ("screen", "intake_screen"):
                from app.services.assistant_research import ready_visual

                # Only a finalized exact visual result changes a read-only
                # plan key. No business action or original attempt is reset.
                visual = await db.get(Research, live.work_key(cid, source_hash, "visual"))
                if visual is not None and ready_visual(visual, live, cid, source_hash):
                    assert isinstance(visual.result, str)
                    checksum = hashlib.sha256(visual.result.encode()).hexdigest()
                    identity.extend(["visual:" + visual.key, checksum])
                    visual_key = visual.key
            key = hashlib.sha256(_json(identity).encode()).hexdigest()
            old = await db.get(Action, key)
            if (
                kind in ("screen", "intake_screen")
                and old is not None
                and old.stage == "screened"
                and old.deadline <= now
            ):
                # A successful read-only observation can be checked again
                # after expiry. This distinct journal entry never renews a
                # model work, business grant, or stopped/failed inspection.
                latest = await db.scalar(
                    select(Action)
                    .where(
                        Action.principal_id == live.principal_id,
                        Action.operator_id == live.operator_id,
                        Action.run_id == live.run_id,
                        Action.generation == live.generation,
                        Action.conversation_id == cid,
                        Action.source_hash == source_hash,
                        Action.versions == _json(live.versions),
                        Action.kind == kind,
                        Action.research_key == visual_key,
                    )
                    .order_by(Action.deadline.desc(), Action.key.desc())
                    .limit(1)
                )
                assert latest is not None
                if latest.stage != "screened" or latest.deadline > now:
                    return _view(latest)
                key = hashlib.sha256(
                    _json(
                        [
                            key,
                            "read_only_recheck",
                            latest.key,
                            latest.deadline,
                        ]
                    ).encode()
                ).hexdigest()
                old = await db.get(Action, key)
            if old is not None:
                return _view(old)  # New launch/version never replaces a consumed source.
            action = Action(
                key=key,
                principal_id=live.principal_id,
                operator_id=live.operator_id,
                run_id=live.run_id,
                generation=live.generation,
                conversation_id=cid,
                versions=_json(live.versions),
                source_hash=source_hash,
                kind=kind,
                research_key=visual_key or research_key,
                stage="inspect",
                deadline=now + 300,
                due=now,
                lease_until=0,
            )
            if kind == "screen":
                enrolled = await db.get(AssistantDialog, cid, populate_existing=True)
                if enrolled is None:
                    raise ValueError("Read-only screen requires actual enrolled conversation")
                action.dialog_version = enrolled.version
            if research_key is not None:
                work = await db.get(Research, research_key)
                if (
                    work is None
                    or work.stage != "ready"
                    or work.purpose != ("intake_form" if kind == "create_crm" else "reply")
                    or any(
                        getattr(work, k) != getattr(action, k)
                        for k in (
                            "principal_id",
                            "operator_id",
                            "run_id",
                            "generation",
                            "conversation_id",
                            "versions",
                            "source_hash",
                        )
                    )
                ):
                    raise ValueError("Original accepted research work required")
                result = _value(work.result)
                if kind == "create_crm":
                    screen_key, proposal = office
                    screen = await db.get(Action, screen_key)
                    if (
                        screen is None
                        or screen.kind != "screen"
                        or screen.stage != "screened"
                        or any(
                            getattr(screen, k) != getattr(action, k)
                            for k in (
                                "principal_id",
                                "operator_id",
                                "run_id",
                                "generation",
                                "conversation_id",
                                "versions",
                                "source_hash",
                            )
                        )
                        or result.get("ok") is not True
                        or result.get("needs_operator") is not False
                        or result.get("can_send_or_create") is not False
                        or result.get("intake_form_ready") is not True
                        or not isinstance(proposal, dict)
                        or proposal.get("form_reference") != result.get("form_reference")
                    ):
                        raise ValueError("Original accepted office form and screen required")
                    planned = _value(screen.result)
                    action.deadline = min(action.deadline, work.deadline, screen.deadline)
                    reference = dict(
                        **_reference(planned, "claim"),
                        proposal=proposal,
                        snapshot_hash=wire.sha(wire.encode(proposal)),
                    )
                    if planned.get("eligible") is not True or planned.get("step") != "prepare_crm":
                        raise ValueError("Office source is not ready for creation")
                    wire.check(
                        {
                            "v": 1,
                            "command_id": str(uuid.uuid4()),
                            "operation": "reserve_office",
                            "principal_id": str(live.principal_id),
                            "operator_id": str(live.operator_id),
                            "run_id": str(live.run_id),
                            "generation": live.generation,
                            "arguments": dict(
                                cid=str(cid),
                                source_sha256=source_hash,
                                kind="create_crm",
                                **reference,
                            ),
                        }
                    )
                    action.reference = _json(reference)
                else:
                    if (
                        result.get("ok") is not True
                        or result.get("validation") != []
                        or result.get("needs_operator") is True
                    ):
                        raise ValueError("Accepted non-vetoed native draft required")
                    _draft(result)
                action.dialog_version = work.dialog_version
            await _fresh(db, action, self.admission)
            db.add(action)
            await db.commit()
            return _view(action)

    def _command(self, action: Action):
        original = action.active_command_id
        op = "recover" if original else action.stage
        args: dict[str, Any] = (
            {"command_id": str(original)}
            if original
            else {"cid": str(action.conversation_id), "source_sha256": action.source_hash}
        )
        if not original and op != "inspect":
            args.update(kind=action.kind, **_value(action.reference))
            if op == "consume_action":
                args["grant_id"] = action.grant_id
            if action.kind == "create_crm":
                op = {"reserve_action": "reserve_office", "consume_action": "consume_office"}[op]
        return wire.check(
            {
                "v": 1,
                "command_id": str(uuid.uuid4()),
                "operation": op,
                "principal_id": str(action.principal_id),
                "operator_id": str(action.operator_id),
                "run_id": str(action.run_id),
                "generation": action.generation,
                "arguments": args,
            }
        )

    async def _begin(self, key):
        now, lease = self.clock(), uuid.uuid4()
        async with self.sessions() as db:
            changed = cast(
                CursorResult[Any],
                await db.execute(
                    update(Action)
                    .where(
                        Action.key == key,
                        Action.stage.not_in(TERMINAL | OBSERVE),
                        Action.due <= now,
                        or_(Action.lease_id.is_(None), Action.lease_until <= now),
                    )
                    .values(lease_id=lease, lease_until=now + 60)
                ),
            )
            action = await db.get(Action, key, populate_existing=True)
            if action is None:
                raise ValueError("Existing native action required")
            if changed.rowcount != 1:
                return _view(action)
            try:
                if action.deadline <= now:
                    action.stage = "expired"
                else:
                    await _fresh(db, action, self.admission)
            except (ApiError, ValueError):
                action.stage = "stopped"
            if action.stage in TERMINAL or action.stage == "apply":
                if action.stage in TERMINAL:
                    action.lease_id, action.lease_until = None, 0
                await db.commit()
                return _view(action) if action.stage in TERMINAL else (lease, None)
            command = self._command(action)
            command_id = uuid.UUID(command["command_id"])
            db.add(
                Command(
                    id=command_id,
                    action_key=key,
                    original_id=action.active_command_id,
                    request=_json(command),
                    state="sending",
                )
            )
            if action.active_command_id is None:
                action.active_command_id = command_id
                if command["operation"] in ("consume_action", "consume_office"):
                    action.consume_command_id = command_id
            await db.commit()  # Original command identity precedes private HTTP.
            return lease, command

    async def _receipt(self, db, action, row, result, status):
        if result.get("ok") is not True or status != 200:
            if (
                result.get("ok") is True
                and status == 202
                and result.get("command_id") == str(row.id)
                and result.get("command_state") == "dispatching"
            ):
                return
            action.stage = "blocked"
            return
        data = result.get("data")
        if not isinstance(data, dict):
            raise ValueError("Bound original action result required")
        if row.original_id:
            if (
                data.get("command_id") != str(row.original_id)
                or data.get("source_or_run_not_current") is True
            ):
                raise ValueError("Original command/launch changed")
            if data.get("command_state") == "dispatching":
                return
            if data.get("command_state") != "done":
                action.stage = "blocked"  # No inferred safe retry from unknown.
                return
            original = await db.get(Command, row.original_id)
            if original is None or original.action_key != action.key:
                raise ValueError("Own original command unavailable")
            receipt, code = data.get("original_result"), data.get("original_status")
            if not isinstance(receipt, dict) or type(code) is not int:
                raise ValueError("Original signed HTTP receipt required")
            original.state, original.response, original.http_status = (
                "recovered",
                _json(receipt),
                code,
            )
            await self._receipt(db, action, original, receipt, code)
            return
        if data.get("ok") is not True:
            action.stage = "blocked"
            return
        operation = _value(row.request)["operation"]
        if operation == "inspect":
            # Preserve the original business screen separately from a missing
            # or failed transport receipt. Neither authorizes an effect.
            action.result = _json(data)
            if action.kind in ("screen", "intake_screen"):
                if (
                    data.get("source_sha256") != action.source_hash
                    or type(data.get("eligible")) is not bool
                    or data.get("step")
                    not in (
                        {"wait", "handoff", "reply", "prepare_crm", "inspect_media", "paused"}
                        | ({"claim"} if action.kind == "intake_screen" else set())
                    )
                ):
                    raise ValueError("Current read-only native plan required")
                action.result, action.stage, action.active_command_id = (
                    _json(data),
                    "screened",
                    None,
                )
                return
            if (
                data.get("eligible") is not True
                or data.get("step")
                != ("prepare_crm" if action.kind == "create_crm" else action.kind)
                or data.get("source_sha256") != action.source_hash
            ):
                action.stage = "blocked"
                return
            reference: dict[str, Any] = _reference(data, "claim")
            if action.kind == "reply":
                work = await db.get(Research, action.research_key)
                original = _value(work.result) if work else {}
                accepted = _draft(original)
                if accepted["revision"] != reference["revision"]:
                    raise ValueError("Accepted draft is not this source action")
                reference.update(accepted)
            elif action.kind == "create_crm":
                prepared = _value(action.reference)
                work = await db.get(Research, action.research_key)
                form = _value(work.result) if work else {}
                if (
                    prepared.get("revision") != reference["revision"]
                    or prepared.get("operation_id") != reference["operation_id"]
                    or form.get("revision") != reference["revision"]
                    or form.get("form_reference") != prepared["proposal"].get("form_reference")
                ):
                    raise ValueError("Accepted office source or proposal changed")
                reference.update(prepared)
            action.reference, action.stage = _json(reference), "reserve_action"
        elif operation in ("reserve_action", "reserve_office"):
            grant = data.get("grant_id")
            if (
                data.get("reserved") is not True
                or data.get("execution_allowed") is not False
                or not isinstance(grant, str)
                or not re.fullmatch(r"[A-Za-z0-9:_-]{1,200}", grant)
            ):
                raise ValueError("Exact reservation required")
            action.grant_id = grant
            action.stage = "office_reserved" if action.kind == "create_crm" else "consume_action"
        elif operation in ("consume_action", "consume_office"):
            reference, now = _value(action.reference), self.clock()
            echoes = {k: v for k, v in reference.items() if k != "proposal"}
            if (
                action.consume_command_id != row.id
                or data.get("execution_allowed") is not True
                or data.get("customer_effect_confirmed") is not False
                or data.get("grant_id") != action.grant_id
                or data.get("chat") != str(action.conversation_id)
                or data.get("operator_id") != str(action.operator_id)
                or data.get("source_sha256") != action.source_hash
                or data.get("kind") != action.kind
                or any(data.get(k) != v for k, v in echoes.items())
                or not isinstance(data.get("native_launch_binding"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", data["native_launch_binding"])
                or type(data.get("dispatch_before")) not in (int, float)
                or not math.isfinite(data["dispatch_before"])
                or not now < data["dispatch_before"] <= now + 10
            ):
                raise ValueError("Original bounded consume binding required")
            if action.kind == "reply":
                work = await db.get(Research, action.research_key)
                if (
                    not isinstance(data.get("reply"), str)
                    or work is None
                    or data["reply"] != _value(work.result).get("reply")
                ):
                    raise ValueError("Accepted candidate text changed")
                messages.validate_text(data["reply"])
            elif action.kind == "create_crm":
                if data.get("form_reference") != reference["proposal"]["form_reference"]:
                    raise ValueError("Original office form changed at consumption")
            action.result, action.stage = _json(data), "apply"
        else:
            raise ValueError("Unadmitted action phase")
        action.active_command_id = None

    async def _apply(self, key, lease):
        async with self.sessions() as db:
            initial = await db.get(Action, key)
            if initial is None:
                raise ValueError("Original action required")
            await db.scalar(select(User).where(User.id == initial.principal_id).with_for_update())
            action = await db.scalar(
                select(Action)
                .where(Action.key == key)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if action is None or action.lease_id != lease or action.stage != "apply":
                return _view(action) if action else {"state": "blocked"}
            try:
                principal, author = await _fresh(db, action, self.admission)
                _, receipt = await _consumed(db, action)
                now = self.clock()
                if not math.isfinite(now) or receipt["dispatch_before"] <= now:
                    raise ValueError("Original dispatch window expired")
                if action.kind == "claim":
                    enrollment = await assistant_dialogs.enroll(
                        db,
                        principal,
                        author,
                        action.conversation_id,
                        expected_assignee_id=None,
                        manual=False,
                        commit=False,
                    )
                    action.dialog_version, action.stage = enrollment["version"], "claimed"
                    action.lease_id, action.lease_until = None, 0
                    await db.commit()  # Assignment and original action application together.
                elif action.kind == "create_crm":
                    action.stage, action.lease_id, action.lease_until = "office_ready", None, 0
                    await db.commit()  # No CRM request or outbound message here.
                else:
                    if not isinstance(action.grant_id, str):
                        raise ValueError("Original grant required")
                    created = await messages.create_outbound_message(
                        db,
                        self.redis,
                        conversation_id=action.conversation_id,
                        user=author,
                        text=receipt["reply"],
                        client_message_id="native:" + action.grant_id,
                        assistant_initiator=principal,
                        native_action_key=key,
                    )
                    if created.replay:
                        raise ValueError("No native application inferred from an unrelated replay")
            except (ApiError, ValueError, TypeError, KeyError):
                await db.rollback()
                action = await db.get(Action, key, populate_existing=True)
                if action is not None and action.stage == "apply":
                    action.stage, action.lease_id, action.lease_until = "stopped", None, 0
                    await db.commit()
            return _view(action)

    async def advance(self, key):
        if not self.enabled:
            return {"state": "disabled", "execution_allowed": False}
        selected = await self._begin(key)
        if isinstance(selected, dict):
            if selected["state"] == "dispatch":
                return await self._dispatch(key)
            return (
                await self.observe(key)
                if selected["state"] in (OBSERVE | {"delivered", "delivery_stopped"})
                else selected
            )
        lease, command = selected
        if command is None:
            return await self._apply(key, lease)
        result, status, not_started = None, None, False
        try:
            result, status = await self.client.submit(command)
        except NativeTransportUncertain:
            pass
        except ValueError:
            not_started = True
        async with self.sessions() as db:
            row = await db.get(Command, uuid.UUID(command["command_id"]))
            action = await db.get(Action, key, populate_existing=True)
            assert row is not None and action is not None
            row.state = (
                "received" if result is not None else "not_started" if not_started else "uncertain"
            )
            row.response, row.http_status = _json(result) if result is not None else None, status
            if action.lease_id == lease:
                try:
                    await _fresh(db, action, self.admission)
                    if action.deadline <= self.clock():
                        action.stage = "expired"
                    elif not_started:
                        action.stage = "blocked"
                    elif result is not None:
                        await self._receipt(db, action, row, result, status)
                except (ApiError, ValueError, KeyError, TypeError):
                    action.stage = "blocked"
                action.due, action.lease_id, action.lease_until = self.clock(), None, 0
            await db.commit()  # Receipt survives stop; no permission is inferred from it.
            return _view(action)

    async def _dispatch(self, key):
        async with self.sessions() as db:
            changed = cast(
                CursorResult[Any],
                await db.execute(
                    update(Action)
                    .where(Action.key == key, Action.stage == "dispatch")
                    .values(stage="queue_observing", lease_id=None, lease_until=0)
                ),
            )
            action = await db.get(Action, key)
            if action is None or changed.rowcount != 1:
                return _view(action) if action else {"state": "blocked"}
            message_id = action.message_id
            if message_id is None:
                raise ValueError("Exact original queued message required")
            await db.commit()  # Even loss before Redis is observation, never redispatch.
        accepted = await messages.enqueue_deliver(self.redis, message_id)
        async with self.sessions() as db:
            action = await db.get(Action, key)
            if action is not None and action.stage == "queue_observing":
                action.stage = "queued" if accepted else "queue_unknown"
                await db.commit()
            return _view(action)

    async def observe(self, key):
        """Only exact original message/part receipts and original ARQ job metadata."""
        async with self.sessions() as db:
            action = await db.get(Action, key)
            if action is None:
                raise ValueError("Original action required")
            result = _view(action)
            outbound = await db.get(Outbound, action.message_id) if action.message_id else None
            if outbound is None:
                return result
            msg = await db.get(Message, (outbound.message_id, outbound.message_created_at))
            parts = list(await db.scalars(select(Part).where(Part.message_id == action.message_id)))
            result.update(
                delivery_status=msg.delivery_status if msg else "unknown",
                native_delivery_state=outbound.state,
                physical_attempts=[
                    {"part": p.part, "attempt": p.attempt, "state": p.state} for p in parts
                ],
            )
            latest: dict[int, Part] = {}
            for part in parts:
                if part.part not in latest or latest[part.part].attempt < part.attempt:
                    latest[part.part] = part
            expected = split_text(msg.body or "") if msg else []
            result["customer_effect_confirmed"] = bool(
                msg
                and msg.delivery_status == "delivered"
                and outbound.state == "accepted"
                and hashlib.sha256((msg.body or "").encode()).hexdigest() == outbound.body_hash
                and msg.sender_user_id == outbound.operator_id
                and msg.conversation_id == outbound.conversation_id
                and set(latest) == set(range(len(expected)))
                and expected
                and all(
                    latest[i].state == "confirmed"
                    and latest[i].vendor_id
                    and latest[i].text_hash == hashlib.sha256(text.encode()).hexdigest()
                    for i, text in enumerate(expected)
                )
                and msg.external_message_id == latest[len(expected) - 1].vendor_id
            )
            if result["customer_effect_confirmed"]:
                action.stage = "delivered"
            elif (
                msg
                and msg.delivery_status == "failed"
                and not any(part.state == "inflight" for part in parts)
            ):
                action.stage = "delivery_stopped"
            result["state"] = action.stage
            result["next_poll_after_s"] = None if action.stage in TERMINAL else 5
            action.due = self.clock() + 5
            await db.commit()  # Derived observation only, never a new dispatch.
            job_id = f"deliver:{action.message_id}"
        try:
            info = await Job(job_id, redis=self.job_redis).info()
            result["original_job"] = {
                "id": job_id,
                "observed": info is not None,
                "try_number": info.job_try if info else None,
            }
        except Exception:
            result["original_job"] = {"id": job_id, "observed": False, "try_number": None}
        # Missing ARQ metadata is not evidence of no send or a dead worker.
        result["observation_only"] = True
        return result

    async def due(self, limit: int = 100) -> list[str]:
        """Restart observes existing actions; it never creates a Run or intake."""
        if not self.enabled:
            return []
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Bounded native action observation required")
        async with self.sessions() as db:
            return list(
                await db.scalars(
                    select(Action.key)
                    .where(
                        Action.stage.not_in(TERMINAL),
                        Action.due <= self.clock(),
                        or_(Action.lease_id.is_(None), Action.lease_until <= self.clock()),
                    )
                    .order_by(Action.due, Action.key)
                    .limit(limit)
                )
            )
