"""Explicit server launches, independent of observer tabs and browser leases.

This module does not dispatch models, claim conversations or send messages.
The caller owns the transaction. Readiness is resolved by trusted server code,
never accepted from a browser body. Every worker use re-reads current authority.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.models import AssistantRun, User
from app.services import assistant_identity
from app.services.audit import write_audit

Mode = Literal["rehearsal", "auto"]


@dataclass(frozen=True)
class RuntimeAdmission:
    """Server-resolved capability and exact versions; not an HTTP request model."""

    policy: str
    runtime: str
    map: str
    memory: str
    worker_ready: bool = False
    auto_ready: bool = False

    def check(self, mode: str) -> None:
        if mode not in ("rehearsal", "auto"):
            raise ApiError("bad", "Неизвестный режим помощника", status=400)
        if any(not isinstance(v, str) or not v.strip() for v in self.versions()):
            raise ApiError(
                "assistant_native_unavailable", "Версии контура не проверены", status=503
            )
        if self.worker_ready is not True or mode == "auto" and self.auto_ready is not True:
            raise ApiError(
                "assistant_native_unavailable", "Серверный контур ещё не принят", status=503
            )

    def versions(self) -> tuple[str, str, str, str]:
        return self.policy, self.runtime, self.map, self.memory


@dataclass(frozen=True)
class RunAuthority:
    principal_id: uuid.UUID
    operator_id: uuid.UUID
    run_id: uuid.UUID
    generation: int
    mode: str
    versions: tuple[str, str, str, str]

    def work_key(self, conversation_id: uuid.UUID, source_revision: str, purpose: str) -> str:
        """A restart, new launch or new runtime never authorizes a second attempt."""
        if (
            not isinstance(conversation_id, uuid.UUID)
            or not isinstance(source_revision, str)
            or not 1 <= len(source_revision) <= 512
            or source_revision.strip() != source_revision
            or purpose not in ("reply", "intake_form", "visual")
        ):
            raise ValueError("Exact source revision and supported purpose required")
        parts = [
            str(self.principal_id),
            str(self.operator_id),
            str(conversation_id),
            source_revision,
            purpose,
        ]
        return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()


async def _principal(db: AsyncSession, principal_id: uuid.UUID, *, lock: bool) -> User:
    query = select(User).where(User.id == principal_id).execution_options(populate_existing=True)
    if lock:
        query = query.with_for_update()
    user = await db.scalar(query)
    if user is None or user.role != "admin" or not assistant_identity.eligible_author(user):
        raise ApiError("forbidden", "Нужны действующие права администратора", status=403)
    return user


async def _author(db: AsyncSession, operator_id: uuid.UUID) -> User:
    user = await db.scalar(
        select(User).where(User.id == operator_id).execution_options(populate_existing=True)
    )
    if user is None or not assistant_identity.eligible_author(user):
        raise ApiError(
            "assistant_author_unavailable", "Выберите действующего сотрудника", status=409
        )
    return user


def snapshot(run: AssistantRun | None) -> dict[str, object]:
    if run is None:
        return {
            "state": "stopped",
            "mode": "rehearsal",
            "generation": 0,
            "run_id": None,
            "operator_id": None,
            "auto_enabled": False,
        }
    return {
        "state": run.state,
        "mode": run.mode,
        "generation": run.generation,
        "run_id": str(run.run_id),
        "operator_id": str(run.operator_id),
        "auto_enabled": run.state == "running" and run.mode == "auto",
    }


async def status(db: AsyncSession, principal_id: uuid.UUID) -> dict[str, object]:
    await _principal(db, principal_id, lock=False)
    return snapshot(await db.get(AssistantRun, principal_id, populate_existing=True))


async def start(
    db: AsyncSession,
    principal_id: uuid.UUID,
    operator_id: uuid.UUID,
    *,
    expected_generation: int,
    mode: Mode,
    admission: RuntimeAdmission,
) -> dict[str, object]:
    # Lock an existing principal row, including when no run row exists yet.
    # SELECT FOR UPDATE on a missing run would not serialize the first launch.
    await _principal(db, principal_id, lock=True)
    admission.check(mode)
    await _author(db, operator_id)
    run = await db.get(AssistantRun, principal_id, populate_existing=True)
    generation = run.generation if run else 0
    if type(expected_generation) is not int or expected_generation != generation:
        raise ApiError("assistant_run_stale", "Состояние запуска изменилось", status=409)
    if run is not None and run.state == "running":
        versions = (run.policy_version, run.runtime_version, run.map_version, run.memory_version)
        if run.operator_id == operator_id and run.mode == mode and versions == admission.versions():
            return snapshot(run)
        raise ApiError("assistant_run_active", "Сначала остановите прежний запуск", status=409)
    if run is None:
        run = AssistantRun(principal_id=principal_id)
        db.add(run)
    run.run_id, run.operator_id = uuid.uuid4(), operator_id
    run.generation, run.mode, run.state = generation + 1, mode, "running"
    run.policy_version, run.runtime_version, run.map_version, run.memory_version = (
        admission.versions()
    )
    await write_audit(
        db,
        user_id=principal_id,
        action="assistant.run_control",
        entity="assistant_run",
        entity_id=str(run.run_id),
        details={
            "operation": "start",
            "generation": run.generation,
            "operator_id": str(operator_id),
            "mode": mode,
        },
    )
    await db.flush()
    return snapshot(run)


async def stop(
    db: AsyncSession, principal_id: uuid.UUID, *, expected_generation: int
) -> dict[str, object]:
    await _principal(db, principal_id, lock=True)
    run = await db.get(AssistantRun, principal_id, populate_existing=True)
    generation = run.generation if run else 0
    if type(expected_generation) is not int or expected_generation != generation:
        raise ApiError("assistant_run_stale", "Состояние запуска изменилось", status=409)
    if run is None or run.state == "stopped":
        return snapshot(run)
    run.state = "stopped"
    run.generation += 1
    await write_audit(
        db,
        user_id=principal_id,
        action="assistant.run_control",
        entity="assistant_run",
        entity_id=str(run.run_id),
        details={
            "operation": "stop",
            "generation": run.generation,
            "operator_id": str(run.operator_id),
            "mode": run.mode,
        },
    )
    await db.flush()
    return snapshot(run)


async def authority(
    db: AsyncSession,
    principal_id: uuid.UUID,
    run_id: uuid.UUID,
    generation: int,
    admission: RuntimeAdmission,
) -> RunAuthority:
    live = await live_authority(db, principal_id, run_id, generation)
    admission.check(live.mode)
    if live.versions != admission.versions():
        raise ApiError("assistant_runtime_changed", "Версии контура изменились", status=409)
    return live


async def block(db: AsyncSession, live: RunAuthority, reason_code: str) -> dict[str, object]:
    """Trusted worker stops its exact launch after a technical hard failure.

    Not an HTTP operation. Revoked admin rights must not prevent stopping the
    original Run. Current-generation CAS cannot stop a later owner launch.
    """
    if not isinstance(live, RunAuthority) or reason_code not in (
        "native_transport",
        "native_runtime",
        "native_source",
        "native_model",
        "native_delivery",
    ):
        raise ValueError("Exact native Run and fixed technical reason required")
    await db.scalar(select(User).where(User.id == live.principal_id).with_for_update())
    run = await db.get(AssistantRun, live.principal_id, populate_existing=True)
    if (
        run is not None
        and run.run_id == live.run_id
        and run.generation == live.generation
        and run.state == "running"
    ):
        run.state, run.generation = "blocked", run.generation + 1
        await write_audit(
            db,
            user_id=live.principal_id,
            action="assistant.run_control",
            entity="assistant_run",
            entity_id=str(live.run_id),
            details={
                "operation": "technical_stop",
                "generation": run.generation,
                "reason_code": reason_code,
                "operator_id": str(live.operator_id),
            },
        )
        await db.flush()
    return snapshot(run)


async def live_authority(
    db: AsyncSession, principal_id: uuid.UUID, run_id: uuid.UUID, generation: int
) -> RunAuthority:
    """Fresh owner/author/run metadata only; the consumer checks its own versions."""
    await _principal(db, principal_id, lock=False)
    run = await db.get(AssistantRun, principal_id, populate_existing=True)
    if (
        type(generation) is not int
        or run is None
        or run.state != "running"
        or run.run_id != run_id
        or run.generation != generation
    ):
        raise ApiError("assistant_run_stale", "Запуск остановлен или изменился", status=409)
    await _author(db, run.operator_id)
    versions = (run.policy_version, run.runtime_version, run.map_version, run.memory_version)
    return RunAuthority(
        principal_id, run.operator_id, run.run_id, run.generation, run.mode, versions
    )


async def read_authority(
    db: AsyncSession, arguments: dict[str, object], actor: dict[str, object] | None
) -> dict[str, object]:
    """Called only after the existing reader's signed envelope/replay gate."""

    def identifier(value: object) -> uuid.UUID:
        if not isinstance(value, str):
            raise ValueError("Canonical UUID required")
        result = uuid.UUID(value)
        if str(result) != value:
            raise ValueError("Canonical UUID required")
        return result

    try:
        if (
            not isinstance(actor, dict)
            or set(actor) != {"principal_id", "operator_id"}
            or not isinstance(arguments, dict)
            or set(arguments) != {"run_id", "generation"}
        ):
            raise ValueError("Exact native run binding required")
        generation = arguments["generation"]
        if type(generation) is not int or not 1 <= generation <= 2**63 - 1:
            raise ValueError("Exact native run generation required")
        principal, operator = identifier(actor["principal_id"]), identifier(actor["operator_id"])
        run_id = identifier(arguments["run_id"])
    except (ValueError, TypeError, AttributeError):
        raise ApiError(
            "validation_error", "Некорректная привязка серверного запуска", status=400
        ) from None
    live = await live_authority(db, principal, run_id, generation)
    if live.operator_id != operator:
        raise ApiError("assistant_run_stale", "Автор запуска изменился", status=409)
    return {
        "authority": {
            "principal_id": str(live.principal_id),
            "operator_id": str(live.operator_id),
            "run_id": str(live.run_id),
            "generation": live.generation,
            "mode": live.mode,
            "versions": list(live.versions),
        }
    }
