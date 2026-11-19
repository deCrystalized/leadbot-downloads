"""Explicit native server Run control; status is read-only observation."""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_redis, require_permission
from app.core.errors import ApiError
from app.models import User
from app.services import assistant_dialogs, assistant_runs, assistant_runtime

router = APIRouter(prefix="/bot-dialogs/assistant/native-run")
manage = require_permission("bots:manage")


class StopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_generation: StrictInt = Field(ge=0)
    expected_principal_id: uuid.UUID


class StartRequest(StopRequest):
    operator_id: uuid.UUID


def same_principal(body: StopRequest, user: User) -> None:
    # An equality check against actual authentication, never caller authority.
    if body.expected_principal_id != user.id:
        raise ApiError(
            "assistant_principal_changed", "Аккаунт изменился. Обновите панель", status=409
        )


@router.get("")
async def status(
    user: User = Depends(manage),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    assistant_dialogs.require_admin(user)
    value = await assistant_runs.status(db, user.id)
    try:
        config = assistant_runtime.configuration()
    except (ValueError, OSError):
        config = None
    ready = config is not None and await assistant_runtime.readiness(redis, config)
    return dict(
        value,
        principal_id=str(user.id),
        native_supported=True,
        configured=config is not None,
        worker_ready=ready,
        start_available=bool(ready and config.admission.auto_ready) if config else False,
        observer_disconnect_stops_run=False,
        rehearsal_in_existing_manual_workflow=True,
    )


@router.post("/start")
async def start(
    body: StartRequest,
    user: User = Depends(manage),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    assistant_dialogs.require_admin(user)
    same_principal(body, user)
    try:
        config = assistant_runtime.configuration()
    except (ValueError, OSError):
        config = None
    if config is None or not await assistant_runtime.readiness(redis, config):
        raise ApiError(
            "assistant_native_unavailable",
            "Серверный обработчик ещё не подтвердил готовность. Авто не запущено",
            status=503,
        )
    value = await assistant_runs.start(
        db,
        user.id,
        body.operator_id,
        expected_generation=body.expected_generation,
        mode="auto",
        admission=config.admission,
    )
    await db.commit()
    return dict(value, principal_id=str(user.id), observer_disconnect_stops_run=False)


@router.post("/stop")
async def stop(body: StopRequest, user: User = Depends(manage), db: AsyncSession = Depends(get_db)):
    # Stop still works while the worker/key/release manifest is unavailable.
    same_principal(body, user)
    value = await assistant_runs.stop(db, user.id, expected_generation=body.expected_generation)
    await db.commit()
    return dict(value, principal_id=str(user.id))
