"""Short-lived admin/author attestation for the owner's browser assistant.

This key is separate from JWT signing and never reaches the browser. The
result cannot authenticate to LeadChat or send a message: native permissions
are checked again on every delegated action.
"""

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.models import User
from app.services.user_ref import user_ref

PROOF_TTL = 45
AUDIENCE = "leadbot-browser-operator"


def proof_key() -> bytes | None:
    value = os.environ.get("LEADBOT_ACTOR_PROOF_KEY", "")
    if not 32 <= len(value) <= 512 or any(c.isspace() for c in value):
        return None
    return value.encode()


def eligible_author(user: User) -> bool:
    return bool(
        user.is_active
        and user.deleted_at is None
        and not user.is_service
        and user.role in ("admin", "manager")
    )


async def resolve_author(db: AsyncSession, author_id: uuid.UUID) -> User:
    user = await db.get(User, author_id)
    if user is None or not eligible_author(user):
        raise ApiError(
            "assistant_author_unavailable",
            "Выберите действующего сотрудника, который может отвечать клиентам",
            status=409,
        )
    return user


async def capabilities(db: AsyncSession, principal: User) -> dict[str, Any]:
    users = (
        await db.scalars(
            select(User)
            .where(
                User.is_active.is_(True),
                User.deleted_at.is_(None),
                User.is_service.is_(False),
                User.role.in_(("admin", "manager")),
            )
            .order_by(User.full_name, User.id)
        )
    ).all()
    return {
        "version": 1,
        "identity_available": proof_key() is not None,
        "principal": user_ref(principal),
        "authors": [user_ref(user) for user in users],
        "activation_required": True,
        "auto_enabled": False,
    }


def issue_proof(
    principal: User,
    author: User,
    *,
    nonce: str,
    browser_session: str,
    now: int | None = None,
) -> dict[str, Any]:
    if principal.role != "admin" or not eligible_author(principal) or not eligible_author(author):
        raise ApiError("forbidden", "Выбор автора доступен действующему администратору", status=403)
    key = proof_key()
    if key is None:
        raise ApiError(
            "assistant_identity_unavailable",
            "Подключение помощника ещё настраивается. Авто не запущено",
            status=503,
        )
    stamp = int(time.time()) if now is None else now
    payload = {
        "v": 1,
        "aud": AUDIENCE,
        "principal_id": str(principal.id),
        "operator_id": str(author.id),
        "principal_name": principal.full_name,
        "operator_name": author.full_name,
        "role": "admin",
        "nonce": nonce,
        "sid": browser_session,
        "iat": stamp,
        "exp": stamp + PROOF_TTL,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(raw).rstrip(b"=")
    signature = base64.urlsafe_b64encode(hmac.new(key, encoded, hashlib.sha256).digest()).rstrip(
        b"="
    )
    return {
        "identity_proof": (encoded + b"." + signature).decode(),
        "expires_at": stamp + PROOF_TTL,
        "principal": user_ref(principal),
        "author": user_ref(author),
        "auto_enabled": False,
    }
