"""Authenticated extension office adapter. No route starts a Run or calls CRM."""

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_redis, require_permission
from app.core.errors import ApiError
from app.db import session as db_mod
from app.models import AssistantOfficeWork, User
from app.services import assistant_dialogs, assistant_runs, assistant_runtime
from app.services.assistant_office import NativeOffice, _versions

router = APIRouter(prefix="/bot-dialogs/assistant/native-office")
manage = require_permission("bots:manage")


class ExecutorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_principal_id: uuid.UUID
    operator_id: uuid.UUID
    run_id: uuid.UUID
    generation: StrictInt = Field(ge=1)
    executor_id: uuid.UUID


class WorkRequest(ExecutorRequest):
    work_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    lease_id: uuid.UUID


class FailureRequest(WorkRequest):
    stop_reason: Literal["crm_existing_request"] | None = None


class PrepareRequest(WorkRequest):
    proposal: dict[str, Any]


class ReportRequest(WorkRequest):
    report: dict[str, Any]


class FollowupRequest(WorkRequest):
    crm_request_id: str = Field(pattern=r"^[1-9][0-9]{0,11}$")
    kind: Literal["partner_note", "customer_contact"]


async def office_service(redis: Redis = Depends(get_redis)) -> NativeOffice:
    try:
        config = assistant_runtime.configuration()
        if config is None or not config.office_enabled:
            raise ValueError("Office is not configured")
    except (ValueError, OSError):
        raise ApiError(
            "assistant_office_unavailable", "Исполнитель CRM ещё не готов", status=503
        ) from None
    # A transient worker heartbeat must not discard original ID/status
    # evidence after an issued create or Stop. New Run startup still checks
    # readiness; every physical office gate checks the original current Run,
    # source, accepted form, consumed Root command and unchanged deadline.
    # API persists intents only. The actual worker owns the real ARQ byte
    # client and existing original-command observer; no dummy queue is made.
    if db_mod.session_factory is None:
        raise ApiError("assistant_office_unavailable", "Исполнитель CRM ещё не готов", status=503)
    return NativeOffice(
        db_mod.session_factory,
        redis,
        admission=config.admission,
        enabled=True,
        notifications_enabled=config.notifications_enabled,
        crm_only=config.crm_only,
    )


async def _live(db, user, body, service, *, evidence=False):
    assistant_dialogs.require_admin(user)
    if body.expected_principal_id != user.id:
        raise ApiError("assistant_principal_changed", "Аккаунт изменился", status=409)
    if evidence:
        work = await db.get(AssistantOfficeWork, body.work_id)
        if work is None or any(
            (
                work.principal_id != user.id,
                work.operator_id != body.operator_id,
                work.run_id != body.run_id,
                work.generation != body.generation,
            )
        ):
            raise ApiError("assistant_office_stale", "Исходная задача изменилась", status=409)
        return assistant_runs.RunAuthority(
            user.id, work.operator_id, work.run_id, work.generation, "auto", _versions(work)
        )
    live = await assistant_runs.authority(
        db, user.id, body.run_id, body.generation, service.admission
    )
    if live.operator_id != body.operator_id or live.mode != "auto":
        raise ApiError("assistant_office_stale", "Исходный запуск изменился", status=409)
    return live


async def _invoke(service, db, user, body, method, *extra, evidence=False):
    try:
        live = await _live(db, user, body, service, evidence=evidence)
        if isinstance(body, WorkRequest):
            return await method(live, body.work_id, body.executor_id, body.lease_id, *extra)
        return await method(live, body.executor_id)
    except ValueError:
        raise ApiError(
            "assistant_office_stale",
            "Данные или разрешение CRM изменились. Повтор создания остановлен",
            status=409,
        ) from None


@router.post("/heartbeat")
async def heartbeat(
    body: ExecutorRequest,
    user: User = Depends(manage),
    db: AsyncSession = Depends(get_db),
    service: NativeOffice = Depends(office_service),
):
    return await _invoke(service, db, user, body, service.heartbeat)


@router.post("/poll")
async def poll(
    body: ExecutorRequest,
    user: User = Depends(manage),
    db: AsyncSession = Depends(get_db),
    service: NativeOffice = Depends(office_service),
):
    return await _invoke(service, db, user, body, service.poll)


@router.post("/prepare")
async def prepare(
    body: PrepareRequest,
    user: User = Depends(manage),
    db: AsyncSession = Depends(get_db),
    service: NativeOffice = Depends(office_service),
):
    return await _invoke(service, db, user, body, service.prepare, body.proposal)


@router.post("/request-create")
async def request_create(
    body: WorkRequest,
    user: User = Depends(manage),
    db: AsyncSession = Depends(get_db),
    service: NativeOffice = Depends(office_service),
):
    return await _invoke(service, db, user, body, service.request_create)


@router.post("/issue-create")
async def issue_create(
    body: WorkRequest,
    user: User = Depends(manage),
    db: AsyncSession = Depends(get_db),
    service: NativeOffice = Depends(office_service),
):
    return await _invoke(service, db, user, body, service.issue_create)


@router.post("/created")
async def created(
    body: ReportRequest,
    user: User = Depends(manage),
    db: AsyncSession = Depends(get_db),
    service: NativeOffice = Depends(office_service),
):
    return await _invoke(
        service, db, user, body, service.capture_created, body.report, evidence=True
    )


@router.post("/followup")
async def followup(
    body: FollowupRequest,
    user: User = Depends(manage),
    db: AsyncSession = Depends(get_db),
    service: NativeOffice = Depends(office_service),
):
    return await _invoke(service, db, user, body, service.followup, body.crm_request_id, body.kind)


@router.post("/card")
async def card(
    body: ReportRequest,
    user: User = Depends(manage),
    db: AsyncSession = Depends(get_db),
    service: NativeOffice = Depends(office_service),
):
    return await _invoke(service, db, user, body, service.capture_card, body.report)


@router.post("/failed")
async def failed(
    body: FailureRequest,
    user: User = Depends(manage),
    db: AsyncSession = Depends(get_db),
    service: NativeOffice = Depends(office_service),
):
    return await _invoke(service, db, user, body, service.fail, body.stop_reason, evidence=True)


@router.post("/status")
async def status(
    body: WorkRequest,
    user: User = Depends(manage),
    db: AsyncSession = Depends(get_db),
    service: NativeOffice = Depends(office_service),
):
    return await _invoke(service, db, user, body, service.status, evidence=True)
