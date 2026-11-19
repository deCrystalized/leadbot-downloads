"""Admin-controlled browser jobs. Enrollment never starts auto or sends a message.

The conversation row is the common lock for enrollment, manual takeover and
outbound messages. The version rejects a prepared send after a takeover or an
author change. Ordinary human assignment and old bot_active are not enrollment.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.models import AssistantDialog, AvitoAccount, Conversation, User
from app.services import account_operators, assistant_identity, conversations, inbox
from app.services.audit import write_audit

AUDIT_ACTION = "assistant.dialog_control"


def require_admin(user: User) -> None:
    if user.role != "admin" or not assistant_identity.eligible_author(user):
        raise ApiError("forbidden", "Управление помощником доступно администратору", status=403)


def snapshot(job: AssistantDialog, conv: Conversation) -> dict[str, Any]:
    # A manual close/assignment changes Conversation, not the historical job.
    # Metadata observation is read-only and never re-enrolls a stale job.
    released = conv.assignee_id != job.operator_id or conv.transfer_to_id is not None or conv.bot_active
    paused_for_owner = job.state == "paused" and conv.assignee_id == job.principal_id
    return {
        "ok": True, "id": str(job.conversation_id),
        "principal_id": str(job.principal_id), "operator_id": str(job.operator_id),
        "version": job.version,
        "state": "completed" if conv.crm_request_id else "closed" if conv.status == "closed" else "paused" if paused_for_owner else "released" if released else job.state,
        "crm_request_id": conv.crm_request_id,
        "conversation_status": conv.status,
        "assignee_id": str(conv.assignee_id) if conv.assignee_id else None,
        "source_revision": conv.updated_at.isoformat() if conv.updated_at else None,
        "last_message_at": conv.last_message_at.isoformat() if conv.last_message_at else None,
        "in_inbox": inbox.is_waiting(conv), "auto_started": False,
    }


async def _commit_snapshot(
    db: AsyncSession, job: AssistantDialog, conv: Conversation,
) -> dict[str, Any]:
    await db.commit()
    # SQL-generated updated_at expires on UPDATE even with expire_on_commit=False.
    # Explicit async reads prevent a committed claim from returning MissingGreenlet
    # when the synchronous serializer accesses the authoritative source revision.
    await db.refresh(conv)
    await db.refresh(job)
    return snapshot(job, conv)


async def check_conversation(db: AsyncSession, conv: Conversation, author: User) -> None:
    if conv.crm_request_id:
        raise ApiError("assistant_completed", "Заявка уже создана: бот закончил работу", status=409)
    if conv.status == "closed" or conv.transfer_to_id is not None or conv.bot_active:
        raise ApiError(
            "assistant_unavailable", "Диалог закрыт, передаётся или занят другим ботом", status=409
        )
    account = await db.get(AvitoAccount, conv.account_id)
    if account is None or account.channel != "avito":
        raise ApiError(
            "assistant_channel",
            "Помощник работает только с разрешёнными каналами Авито",
            status=409,
        )
    await account_operators.assert_can_take_account(db, author, conv.account_id)


async def enroll(
    db: AsyncSession,
    principal: User,
    author: User,
    conversation_id: uuid.UUID,
    *,
    expected_assignee_id: uuid.UUID | None,
    manual: bool,
) -> dict[str, Any]:
    require_admin(principal)
    conv = await conversations.get_conversation_for_update(db, conversation_id)
    await check_conversation(db, conv, author)
    holder = conv.assignee_id or conv.claimed_by_id
    if holder != expected_assignee_id or (not manual and holder is not None):
        raise ApiError(
            "assistant_assignment_changed", "Ответственный изменился. Обновите диалог", status=409
        )
    job = await db.get(AssistantDialog, conversation_id)
    if job is not None and not manual:
        raise ApiError(
            "assistant_existing_job",
            "Этот диалог уже передавали боту. Возобновите его вручную",
            status=409,
        )
    if job is not None and job.state == "waiting":
        if job.principal_id == principal.id and job.operator_id == author.id:
            return snapshot(job, conv)
        raise ApiError("assistant_busy", "Диалог уже передан другому помощнику", status=409)
    now = datetime.now(UTC)
    # A manual admin handoff is explicit. Automatic intake can only take a free
    # conversation; it never changes an existing employee's assignment.
    conv.assignee_id = author.id
    conv.claimed_by_id = author.id
    conv.claimed_at = now
    conv.status = "in_progress"
    if job is None:
        job = AssistantDialog(
            conversation_id=conversation_id,
            principal_id=principal.id,
            operator_id=author.id,
            state="waiting",
            version=1,
        )
        db.add(job)
    else:
        job.principal_id, job.operator_id = principal.id, author.id
        job.state, job.version = "waiting", job.version + 1
    await write_audit(
        db,
        user_id=principal.id,
        action=AUDIT_ACTION,
        entity="conversation",
        entity_id=str(conversation_id),
        details={
            "operation": "handoff" if manual else "claim",
            "operator_id": str(author.id),
            "previous_assignee_id": str(holder) if holder else None,
            "version": job.version,
            "auto_started": False,
        },
    )
    return await _commit_snapshot(db, job, conv)


async def locked_job(
    db: AsyncSession,
    principal: User,
    conversation_id: uuid.UUID,
    operator_id: uuid.UUID,
    version: int,
    *,
    allow_paused: bool = False,
) -> tuple[Conversation, AssistantDialog, User]:
    require_admin(principal)
    conv = await conversations.get_conversation_for_update(db, conversation_id)
    job = await db.get(AssistantDialog, conversation_id)
    if (
        job is None
        or job.principal_id != principal.id
        or job.operator_id != operator_id
        or job.version != version
        or job.state not in (("waiting", "paused") if allow_paused else ("waiting",))
    ):
        raise ApiError("assistant_stale", "Диалог забран вручную или автор изменился", status=409)
    author = await assistant_identity.resolve_author(db, operator_id)
    await check_conversation(db, conv, author)
    if conv.assignee_id != author.id or conv.claimed_by_id != author.id:
        raise ApiError(
            "assistant_assignment_changed", "Ответственный изменился: бот остановлен", status=409
        )
    return conv, job, author


async def pause(
    db: AsyncSession,
    principal: User,
    conversation_id: uuid.UUID,
    operator_id: uuid.UUID,
    version: int,
) -> dict[str, Any]:
    # Stop must work even if the author was disabled or a CRM order appeared.
    require_admin(principal)
    conv = await conversations.get_conversation_for_update(db, conversation_id)
    job = await db.get(AssistantDialog, conversation_id)
    if (
        job is None
        or job.principal_id != principal.id
        or job.operator_id != operator_id
        or job.version != version
    ):
        raise ApiError("assistant_stale", "Состав диалога изменился. Обновите панель", status=409)
    job.state, job.version = "paused", job.version + 1
    if not conv.crm_request_id and conv.assignee_id == operator_id:
        conv.assignee_id = conv.claimed_by_id = principal.id
    await write_audit(
        db,
        user_id=principal.id,
        action=AUDIT_ACTION,
        entity="conversation",
        entity_id=str(conversation_id),
        details={"operation": "takeover", "operator_id": str(operator_id), "version": job.version},
    )
    return await _commit_snapshot(db, job, conv)


async def complete(
    db: AsyncSession,
    principal: User,
    conversation_id: uuid.UUID,
    operator_id: uuid.UUID,
    version: int,
    crm_request_id: str,
    *,
    telegram_confirmed: bool = False,
) -> dict[str, Any]:
    require_admin(principal)
    if telegram_confirmed is not True:
        raise ApiError(
            "assistant_notification_required",
            "Служебная отписка не подтверждена. Диалог не закрыт",
            status=409,
        )
    conv = await conversations.get_conversation_for_update(db, conversation_id)
    job = await db.get(AssistantDialog, conversation_id)
    if (
        job is None
        or job.principal_id != principal.id
        or job.operator_id != operator_id
        or job.version != version
        or job.state not in ("waiting", "completed")
    ):
        raise ApiError(
            "assistant_stale", "Диалог забран вручную. Заявку проверит оператор", status=409
        )
    if job.state == "completed" and conv.crm_request_id == crm_request_id:
        result = snapshot(job, conv)
        result["same_request_conversation_ids"] = await conversations.crm_request_twins(
            db, crm_request_id, except_id=conversation_id
        )
        return result
    if (
        conv.crm_request_id
        and conv.crm_request_id != crm_request_id
        or conv.assignee_id != operator_id
        or conv.status == "closed"
        or conv.transfer_to_id is not None
        or conv.bot_active
    ):
        raise ApiError("assistant_stale", "Данные изменились. Заявку проверит оператор", status=409)
    await conversations.set_crm_request(db, conv, principal, crm_request_id)
    # Owner's latest instruction supersedes returning to Incoming: close only
    # after verified creation and the acknowledged service Telegram post.
    # The normal close service retains its audit, cleanup and system event.
    await conversations.change_status(db, conv, new_status="closed", actor=principal)
    job.state = "completed"
    result = await _commit_snapshot(db, job, conv)
    result["in_inbox"] = inbox.is_waiting(conv)
    result["same_request_conversation_ids"] = await conversations.crm_request_twins(
        db, crm_request_id, except_id=conversation_id
    )
    return result


async def list_jobs(
    db: AsyncSession, principal: User, limit: int, offset: int,
    view: str = "active", operator_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    require_admin(principal)
    if view not in {"active", "archive", "all"}:
        raise ApiError("bad_view", "Неизвестная очередь помощника", status=400)
    active = (
        (Conversation.status != "closed")
        & Conversation.crm_request_id.is_(None)
        & (AssistantDialog.state != "completed")
        & Conversation.assignee_id.is_not(None)
        & (Conversation.assignee_id == AssistantDialog.operator_id)
        & Conversation.transfer_to_id.is_(None)
        & Conversation.bot_active.is_(False)
    )
    clauses = [AssistantDialog.principal_id == principal.id]
    if operator_id is not None:
        clauses.append(AssistantDialog.operator_id == operator_id)
    if view != "all":
        clauses.append(active if view == "active" else ~active)
    # Filter BEFORE count/offset/limit. Filtering a page in the browser leaves
    # stale totals, empty intermediate pages and missed active rows.
    total = await db.scalar(
        select(func.count()).select_from(AssistantDialog).join(Conversation).where(*clauses)
    )
    rows = (await db.execute(
        select(AssistantDialog, Conversation).join(Conversation).where(*clauses)
        .order_by(AssistantDialog.updated_at.desc(), AssistantDialog.conversation_id)
        .limit(limit + 1).offset(offset)
    )).all()
    return {
        "items": [snapshot(job, conv) for job, conv in rows[:limit]],
        "more": len(rows) > limit, "next_offset": offset + min(limit, len(rows)),
        "total": int(total or 0), "view": view,
    }
