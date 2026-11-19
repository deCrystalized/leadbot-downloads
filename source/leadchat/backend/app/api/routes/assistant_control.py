"""Native admin permissions for the browser assistant's explicit author picker."""

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_redis, require_permission
from app.core.errors import ApiError
from app.models import AssistantDialog, AvitoAccount, Message, User
from app.services import (
    assistant_dialogs,
    assistant_identity,
    assistant_runtime,
    conversations,
    inbox,
    leadbot_reader,
    messages,
)
from app.services.assistant_observation import NativeObservation
from app.services.user_ref import user_ref
from app.ws.events import iso, publish_event
from app.ws.hub import publish_inbox_released

router = APIRouter()
manage = require_permission("bots:manage")
log = structlog.get_logger("app.assistant_control")


async def require_source_read(
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> tuple[bytes, str]:
    """Authenticate the original bounded bytes before source/SQL dispatch, once."""
    return await leadbot_reader.handle(request, db, redis)


@router.post("/bot-dialogs/assistant/reader")
async def source_reader(reply: tuple[bytes, str] = Depends(require_source_read)) -> Response:
    """Purpose-bound service read; a browser bearer grants no authority here."""
    raw, signature = reply
    return Response(
        content=raw,
        media_type="application/json",
        headers={
            "X-LB-Read-Signature": signature,
            "Cache-Control": "no-store",
        },
    )


async def announce(db: AsyncSession, redis: Redis, user: User, conversation_id: uuid.UUID) -> None:
    """After commit only. Failed WS publication must not hide a saved handoff."""
    conv = await conversations.get_conversation(db, conversation_id)
    try:
        if inbox.is_waiting(conv):
            patch = inbox.queue_patch(conv)
            await publish_inbox_released(
                redis,
                conversation=await conversations.conversation_detail(db, conv),
                released_by=user_ref(user),
                offered_at=iso(conv.offered_at),
                conversation_patch=patch,
                eligible_operator_ids=await inbox.eligible_operator_ids(db, conv),
            )
        else:
            holder = await db.get(User, conv.assignee_id) if conv.assignee_id else None
            if holder is not None:
                await messages.publish_claimed_by_reply(redis, conv, holder)
                patch = inbox.claimed_patch(conv, holder)
            else:
                patch = {"status": conv.status}
        patch["crm_request_id"] = conv.crm_request_id
        await publish_event(
            redis, "conversation:updated", {"conversation_id": str(conv.id), "patch": patch}
        )
    except RedisError:
        log.warning("assistant_control.publish_failed", conversation_id=str(conversation_id))


class IdentityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operator_id: uuid.UUID
    nonce: str = Field(min_length=20, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    browser_session: str = Field(min_length=8, max_length=120, pattern=r"^[A-Za-z0-9:_-]+$")


@router.get("/bot-dialogs/assistant/capabilities")
async def get_capabilities(
    user: User = Depends(manage),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await assistant_identity.capabilities(db, user)


@router.post("/bot-dialogs/assistant/identity")
async def identity_proof(
    body: IdentityRequest,
    user: User = Depends(manage),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    author = await assistant_identity.resolve_author(db, body.operator_id)
    return assistant_identity.issue_proof(
        user, author, nonce=body.nonce, browser_session=body.browser_session
    )


class HandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operator_id: uuid.UUID
    expected_assignee_id: uuid.UUID | None


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operator_id: uuid.UUID
    version: int = Field(ge=1)


class ReplyRequest(JobRequest):
    expected_last_message_id: uuid.UUID
    text: str = Field(min_length=1, max_length=10000)
    client_message_id: str = Field(min_length=1, max_length=64)


class CompleteRequest(JobRequest):
    crm_request_id: str = Field(pattern=r"^[1-9][0-9]{0,11}$")
    telegram_confirmed: StrictBool


@router.get("/bot-dialogs/assistant/dialogs")
async def dialogs(
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    view: str = Query("active", pattern="^(active|archive|all)$"),
    operator_id: uuid.UUID | None = Query(None),
    user: User = Depends(manage),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict[str, Any]:
    page = await assistant_dialogs.list_jobs(db, user, limit, offset, view, operator_id)
    try:
        config = assistant_runtime.configuration()
    except (ValueError, OSError):
        config = None
    if config is None:
        return {**page, "items": [{**row, "observation": None} for row in page["items"]]}
    observer = NativeObservation(None, redis, admission=config.admission)
    return await observer.annotate(db, user, page)


@router.get("/bot-dialogs/assistant/queue")
async def author_queue(
    operator_id: uuid.UUID,
    limit: int = Query(12, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(manage),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    assistant_dialogs.require_admin(user)
    author = await assistant_identity.resolve_author(db, operator_id)
    accounts = tuple(
        await db.scalars(select(AvitoAccount.id).where(AvitoAccount.channel == "avito"))
    )
    items, total = (
        await inbox.list_inbox(
            db, author, inbox.InboxFilters(account_ids=accounts, limit=limit, offset=offset)
        )
        if accounts
        else ([], 0)
    )
    return {"items": items, "page": {"total": total, "limit": limit, "offset": offset}}


@router.get("/bot-dialogs/assistant/dialogs/{conversation_id}")
async def dialog_status(
    conversation_id: uuid.UUID,
    user: User = Depends(manage),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    job = await db.get(AssistantDialog, conversation_id)
    if job is None or job.principal_id != user.id:
        raise ApiError("not_found", "Диалог не передан вашему помощнику", status=404)
    conv = await conversations.get_conversation(db, conversation_id)
    return assistant_dialogs.snapshot(job, conv)


@router.get("/bot-dialogs/assistant/access/{conversation_id}")
async def author_access(
    conversation_id: uuid.UUID,
    operator_id: uuid.UUID,
    user: User = Depends(manage),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    assistant_dialogs.require_admin(user)
    author = await assistant_identity.resolve_author(db, operator_id)
    conv = await conversations.get_conversation(db, conversation_id)
    await assistant_dialogs.check_conversation(db, conv, author)
    return {"allowed": True, "operator_id": str(author.id), "id": str(conversation_id)}


@router.post("/bot-dialogs/assistant/dialogs/{conversation_id}/handoff")
async def handoff(
    conversation_id: uuid.UUID,
    body: HandoffRequest,
    user: User = Depends(manage),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict[str, Any]:
    author = await assistant_identity.resolve_author(db, body.operator_id)
    result = await assistant_dialogs.enroll(
        db,
        user,
        author,
        conversation_id,
        expected_assignee_id=body.expected_assignee_id,
        manual=True,
    )
    await announce(db, redis, user, conversation_id)
    return result


@router.post("/bot-dialogs/assistant/dialogs/{conversation_id}/claim")
async def claim(
    conversation_id: uuid.UUID,
    body: HandoffRequest,
    user: User = Depends(manage),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict[str, Any]:
    author = await assistant_identity.resolve_author(db, body.operator_id)
    result = await assistant_dialogs.enroll(
        db,
        user,
        author,
        conversation_id,
        expected_assignee_id=body.expected_assignee_id,
        manual=False,
    )
    await announce(db, redis, user, conversation_id)
    return result


@router.post("/bot-dialogs/assistant/dialogs/{conversation_id}/takeover")
async def takeover(
    conversation_id: uuid.UUID,
    body: JobRequest,
    user: User = Depends(manage),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict[str, Any]:
    result = await assistant_dialogs.pause(
        db, user, conversation_id, body.operator_id, body.version
    )
    await announce(db, redis, user, conversation_id)
    return result


@router.post("/bot-dialogs/assistant/dialogs/{conversation_id}/messages", status_code=201)
async def reply(
    conversation_id: uuid.UUID,
    body: ReplyRequest,
    response: Response,
    user: User = Depends(manage),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict[str, Any]:
    # Dedicated route: an old server returns404, never silently sends as admin.
    from app.api.routes.messages import SendMessageIn, send_as

    _, _, author = await assistant_dialogs.locked_job(
        db, user, conversation_id, body.operator_id, body.version
    )
    replay = await db.scalar(
        select(Message.id)
        .where(
            Message.conversation_id == conversation_id,
            Message.client_message_id == body.client_message_id,
        )
        .limit(1)
    )
    if replay is None:
        latest = await db.scalar(
            select(Message.id)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
        )
        if latest != body.expected_last_message_id:
            raise ApiError(
                "assistant_history_changed",
                "Клиент или сотрудник дописал. Ответ нужно проверить заново",
                status=409,
            )
    return await send_as(
        conversation_id,
        SendMessageIn(text=body.text, client_message_id=body.client_message_id),
        response,
        author,
        db,
        redis,
        assistant_initiator=user,
    )


@router.post("/bot-dialogs/assistant/dialogs/{conversation_id}/complete")
async def complete(
    conversation_id: uuid.UUID,
    body: CompleteRequest,
    user: User = Depends(manage),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict[str, Any]:
    result = await assistant_dialogs.complete(
        db,
        user,
        conversation_id,
        body.operator_id,
        body.version,
        body.crm_request_id,
        telegram_confirmed=body.telegram_confirmed,
    )
    await announce(db, redis, user, conversation_id)
    return result
