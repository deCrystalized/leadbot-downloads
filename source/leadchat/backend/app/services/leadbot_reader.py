"""Read-only service integration. No assignment, message, CRM or audit writes.

Private exporter/index updates happen in LeadBot, never in customer tables.
Source identities are returned before the consumer is allowed to request a body.
"""

import base64
import hashlib
import os
import re
import time
import uuid
from datetime import datetime
from types import SimpleNamespace
from typing import cast
from urllib.parse import parse_qsl, urlsplit, urlunsplit

import httpx
from sqlalchemy import select, tuple_

from app.core.errors import ApiError
from app.models import AssistantDialog, AvitoAccount, Client, Conversation, Message, User
from app.services import (
    account_operators,
    assistant_dialogs,
    assistant_identity,
    conversations,
    media,
    phone_parse,
)
from app.services import leadbot_source_protocol as protocol

MAX_MESSAGES = 5000
MAX_IMAGE = 5 * 1024 * 1024


def _avito_original(url):
    if not isinstance(url, str) or len(url) > 4096 or re.search(r"\s", url):
        return False
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not re.fullmatch(r"\d{2}\.img\.avito\.st", parsed.hostname or "")
            or parsed.port not in (None, 443)
            or parsed.username
            or parsed.password
            or parsed.fragment
            or not parsed.path.startswith("/")
            or parsed.path == "/"
        ):
            return False
        # cqp belongs to the exact DB-bound original URL. Preserve it rather
        # than requesting a different image after stripping the query.
        query = (
            parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
            if parsed.query
            else []
        )
        return not query or (
            len(query) == 1
            and query[0][0] == "cqp"
            and re.fullmatch(r"[A-Za-z0-9._~=-]{1,2048}", query[0][1]) is not None
        )
    except ValueError:
        return False


class SourcePending(protocol.SourceError):
    """Source-specific incomplete evidence; never a successful body."""


def _id(value):
    try:
        result = uuid.UUID(value)
        if str(result) != value:
            raise ValueError()
        return result
    except (TypeError, ValueError, AttributeError):
        raise protocol.SourceError("Exact source identity required") from None


def _digest(value):
    return protocol.sha(protocol.encode(value))


def _identity_key(kind, value):
    # Same identity-only convention as the protected manual-program manifest.
    return hashlib.sha256((kind + ":" + value).encode()).hexdigest()


def _media_aliases(attachment):
    references = set()
    for field in ("path", "url", "media_id", "id"):
        value = attachment.get(field)
        if not isinstance(value, (str, int)) or isinstance(value, bool) or not str(value):
            continue
        value = str(value).rstrip("?")
        references.add(value)
        if field == "url":
            try:
                parsed = urlsplit(value)
                if parsed.scheme in ("https", "http") and parsed.netloc and parsed.path:
                    references.add(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", "")))
            except ValueError:
                pass
    return {_digest(["media_ref", value]) for value in references}


async def _authorize(db, conv, actor):
    if conv.channel != "avito":
        raise protocol.SourceError("Source channel is outside the read integration")
    if actor is None:
        if os.environ.get("LEADBOT_READER_ARCHIVE") != "1":
            raise protocol.SourceError("Archive read scope is disabled")
        return
    principal = await db.get(User, _id(actor["principal_id"]))
    if principal is None:
        raise protocol.SourceError("Verified native principal is unavailable")
    assistant_dialogs.require_admin(principal)
    author = await assistant_identity.resolve_author(db, _id(actor["operator_id"]))
    # Reading source evidence does not claim a dialogue or authorize intake.
    # Existing write handlers retain their lifecycle/holder/order checks.
    await account_operators.assert_can_take_account(db, author, conv.account_id)


async def _snapshot(
    db, cid, actor, *, native_own_messages: tuple[tuple[uuid.UUID, datetime], ...] = ()
):
    # Internal outbox comparison only. This is never a source-RPC argument;
    # the caller has independently bound these exact own output rows to its
    # persisted native vendor attempts. External/history reads use no exclusions.
    if not isinstance(native_own_messages, tuple) or any(
        not isinstance(value, tuple)
        or len(value) != 2
        or not isinstance(value[0], uuid.UUID)
        or not isinstance(value[1], datetime)
        for value in native_own_messages
    ):
        raise protocol.SourceError("Exact internal native message identities required")
    conv = await db.get(Conversation, _id(cid))
    if conv is None:
        return None
    await _authorize(db, conv, actor)
    client = await db.get(Client, conv.client_id)
    account = await db.get(AvitoAccount, conv.account_id)
    enrolled = await db.get(AssistantDialog, conv.id, populate_existing=True)
    listing = (
        conversations.item_out(
            # Preserve the deployed four-field read adapter. item_out only
            # consumes these listing fields; no ORM/session object is exposed.
            cast(
                Conversation,
                SimpleNamespace(
                    item_title=conv.item_title,
                    item_url=getattr(conv, "item_url", None),
                    item_price=getattr(conv, "item_price", None),
                    item_city_slug=getattr(conv, "item_city_slug", None),
                ),
            )
        )
        or {}
    )
    rows = (
        await db.scalars(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .where(tuple_(Message.id, Message.created_at).not_in(native_own_messages))
            .order_by(Message.created_at, Message.id)
            .limit(MAX_MESSAGES + 1)
        )
    ).all()
    if len(rows) > MAX_MESSAGES:
        raise SourcePending("full_source_message_budget")
    users = {}
    for row in rows:
        if row.sender_user_id is not None and row.sender_user_id not in users:
            users[row.sender_user_id] = await db.get(User, row.sender_user_id)
    messages, phones, media_refs, incomplete = [], set(), set(), []
    fragments: list[str] = []
    seen = set()

    def collect(text):
        for found in phone_parse.find_all(text):
            phones.add(re.sub(r"\D", "", found.value)[-10:])

    def flush():
        if len(fragments) > 1:
            found = phone_parse.from_fragments(fragments)
            if found:
                phones.add(re.sub(r"\D", "", found.value)[-10:])
        fragments.clear()

    collect(str(getattr(client, "phone", "") or ""))
    for row in rows:
        if str(row.id) in seen:
            raise SourcePending("source_message_identity_not_unique")
        seen.add(str(row.id))
        attachments = row.attachments or []
        if not isinstance(attachments, list) or any(not isinstance(a, dict) for a in attachments):
            raise SourcePending("original_attachment_metadata_unavailable")
        author = users.get(row.sender_user_id)
        item = {
            "id": str(row.id),
            "direction": row.direction,
            "sender_type": row.sender_type,
            "author": str(getattr(author, "full_name", "") or ""),
            "sender_user_id": str(row.sender_user_id) if row.sender_user_id else None,
            "client_message_id": str(getattr(row, "client_message_id", "") or ""),
            "body": row.body or "",
            "voice_transcript": row.voice_transcript or "",
            "voice_transcript_status": row.voice_transcript_status or "",
            "delivery_status": row.delivery_status or "",
            "attachments": attachments,
            "created_at": row.created_at.isoformat(),
        }
        messages.append(item)
        text = item["body"] + " " + item["voice_transcript"]
        collect(text)  # Exclusion only, not attribution of a quoted number.
        if (
            row.direction == "in"
            and row.sender_type in ("client", "")
            and phone_parse.is_fragment(text.strip())
        ):
            fragments.append(text.strip())
        else:
            flush()
        for attachment in attachments:
            kind = attachment.get("kind") or attachment.get("type") or attachment.get("avito_type")
            media_refs.update(_media_aliases(attachment))
            if kind not in ("voice", "audio", "contact", "contact_card", "vcard"):
                incomplete.append("original_media_identity_pending")
            if kind in ("voice", "audio") and (
                row.voice_transcript_status != "done" or not row.voice_transcript
            ):
                incomplete.append("unfinished_ASR")
            for key in ("phone", "phone_number"):
                collect(str(attachment.get(key) or ""))
        if row.voice_transcript_status and row.voice_transcript_status != "done":
            incomplete.append("unfinished_ASR")
    flush()
    client_id = str(conv.client_id)
    identity_keys = {_identity_key("dialog", cid), _identity_key("client", client_id)}
    identity_keys.update(_identity_key("phone", phone) for phone in phones)
    if getattr(conv, "origin_client_id", None):
        identity_keys.add(_identity_key("client", str(conv.origin_client_id)))
    source = {
        "cid": cid,
        "client_group": _identity_key("client", client_id),
        "phone_hashes": sorted(_digest(["phone", phone]) for phone in phones),
        "media_hashes": sorted(media_refs),
        "identity_keys": sorted(identity_keys),
        "messages": messages,
        "metadata": {
            # Actual membership is freshness evidence, not a caller flag or
            # a client fact. Same-author pause/version changes must invalidate
            # an in-flight Root source even when assignee/message IDs match.
            "assistant_dialog": {
                "principal_id": str(enrolled.principal_id),
                "operator_id": str(enrolled.operator_id),
                "version": enrolled.version,
                "state": enrolled.state,
            }
            if enrolled is not None
            else None,
            "names": [getattr(client, "name", "")] if getattr(client, "name", "") else [],
            "account_id": str(conv.account_id),
            "channel": conv.channel,
            "title": conv.item_title or "",
            "account_title": str(getattr(account, "title", "") or ""),
            "partner": str(getattr(account, "lead_partner_number", "") or ""),
            "origin": str(getattr(account, "lead_origin", "") or ""),
            "item": listing,
            "client_name": str(getattr(client, "name", "") or ""),
            "client_phone": str(getattr(client, "phone", "") or ""),
            "phone_source_conversation_id": str(getattr(client, "phone_conversation_id", "") or ""),
            "client_link_confidence": str(getattr(client, "link_confidence", "") or ""),
            "client_link_conflict": getattr(client, "link_phone_conflict", False) is True,
            "status": conv.status,
            "crm_request_id": conv.crm_request_id,
            "assignee_id": str(conv.assignee_id) if conv.assignee_id else None,
            "claimed_by_id": str(conv.claimed_by_id) if conv.claimed_by_id else None,
            "bot_active": bool(getattr(conv, "bot_active", False)),
            "transfer_to_id": str(conv.transfer_to_id)
            if getattr(conv, "transfer_to_id", None)
            else None,
            "source_authority": "raw_native_history_not_reviewed_lesson",
        },
    }
    raw = protocol.encode(source)
    if len(raw) > 5 * 1024 * 1024:
        raise SourcePending("full_source_byte_budget")
    header = {
        k: source[k]
        for k in ("cid", "client_group", "phone_hashes", "media_hashes", "identity_keys")
    }
    header.update(
        source_sha256=protocol.sha(raw),
        message_count=len(messages),
        identity_complete=not incomplete,
        pending_reasons=sorted(set(incomplete)),
        media_identity_kind="stored_reference_not_pixel_digest",
        source_authority="raw_native_history_not_reviewed_lesson",
    )
    return header, source


def _image_mime(raw):
    detected = media.sniff(raw)
    if detected is None or detected[2] != "image":
        raise protocol.SourceError("Original bytes are not a supported image")
    return detected[0]


async def original_image(attachment):
    """Only DB-bound metadata, no caller URL, local path or redirects."""
    stored = attachment.get("path")
    if stored:
        if (
            not isinstance(stored, str)
            or not media.MEDIA_RELPATH_RE.fullmatch(stored)
            or stored.startswith("exports/")
        ):
            raise protocol.SourceError("Unsupported native image storage reference")
        root = media.media_root().resolve()
        path = root / stored
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.resolve().is_relative_to(
            root
        ):
            raise protocol.SourceError("Image storage reference is not a regular original")
        if not path.is_file() or path.stat().st_size > MAX_IMAGE:
            raise protocol.SourceError("Original is unavailable or too large")
        with path.open("rb") as stream:
            raw = stream.read(MAX_IMAGE + 1)
    else:
        url = attachment.get("url")
        if not _avito_original(url):
            raise protocol.SourceError("Original is not on the supported native image CDN")
        chunks, size = [], 0
        async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False) as client:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise protocol.SourceError("Original image request did not complete")
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_IMAGE:
                        raise protocol.SourceError("Original image exceeds its budget")
                    chunks.append(chunk)
        raw = b"".join(chunks)
    if not raw or len(raw) > MAX_IMAGE:
        raise protocol.SourceError("Original image is empty or oversized")
    return raw, _image_mime(raw)


async def dispatch(db, value):
    op, args, actor = value["operation"], value["arguments"], value["actor"]
    if op == "run_authority":
        from app.services import assistant_runs

        try:
            return await assistant_runs.read_authority(db, args, actor)
        except ApiError:
            raise protocol.SourceError("Native run is stopped, changed or unavailable") from None
    if op == "catalog":
        if actor is not None or os.environ.get("LEADBOT_READER_ARCHIVE") != "1":
            raise protocol.SourceError("Archive catalog scope is disabled")
        if (
            set(args) != {"after", "limit"}
            or type(args["limit"]) is not int
            or not 1 <= args["limit"] <= 100
        ):
            raise protocol.SourceError("Exact bounded catalog cursor required")
        query = (
            select(Conversation.id).where(Conversation.channel == "avito").order_by(Conversation.id)
        )
        if args["after"] is not None:
            query = query.where(Conversation.id > _id(args["after"]))
        ids = (await db.scalars(query.limit(args["limit"] + 1))).all()
        return {
            "cids": [str(cid) for cid in ids[: args["limit"]]],
            "next": str(ids[args["limit"] - 1]) if len(ids) > args["limit"] else None,
            "complete": len(ids) <= args["limit"],
            "consistency": (
                "ordered daily full scan; concurrent inserts reconciled on next scan, "
                "not point-in-time snapshot"
            ),
        }
    if op == "headers":
        if (
            set(args) != {"cids"}
            or not isinstance(args["cids"], list)
            or not 1 <= len(args["cids"]) <= 25
            or len(set(args["cids"])) != len(args["cids"])
        ):
            raise protocol.SourceError("Exact source metadata batch required")
        result = []
        for cid in args["cids"]:
            try:
                snap = await _snapshot(db, cid, actor)
            except SourcePending as exc:
                result.append(
                    {
                        "cid": cid,
                        "pending": True,
                        "identity_complete": False,
                        "pending_reasons": [str(exc)],
                    }
                )
                continue
            result.append(snap[0] if snap else {"cid": cid, "deleted": True})
        return {"headers": result}
    if op not in ("history", "image"):
        raise protocol.SourceError("Read-only source operation required")
    expected = {"cid", "source_sha256"} | (
        {"message_id", "position", "attachment_hash"} if op == "image" else set()
    )
    if set(args) != expected:
        raise protocol.SourceError("Exact source read binding required")
    snap = await _snapshot(db, args["cid"], actor)
    if snap is None:
        raise protocol.SourceError("Source has been deleted")
    header, source = snap
    if args["source_sha256"] != header["source_sha256"]:
        raise protocol.SourceError("Source changed after metadata observation")
    if op == "history":
        return {"header": header, "source": source}
    if actor is None:
        raise protocol.SourceError("Original image requires a current verified native actor")
    row = next((m for m in source["messages"] if m["id"] == args["message_id"]), None)
    index = args["position"]
    if row is None or type(index) is not int or not 0 <= index < len(row["attachments"]):
        raise protocol.SourceError("Original image message is unavailable")
    attachment = row["attachments"][index]
    if _digest(attachment) != args["attachment_hash"]:
        raise protocol.SourceError("Original attachment changed")
    raw, mime = await original_image(attachment)
    # Re-observe after IO; a late ASR correction/new message cancels old pixels.
    await db.rollback()
    fresh = await _snapshot(db, args["cid"], actor)
    if fresh is None or fresh[0]["source_sha256"] != header["source_sha256"]:
        raise protocol.SourceError("Source changed during original image read")
    return {
        "cid": args["cid"],
        "source_sha256": header["source_sha256"],
        "message_id": args["message_id"],
        "position": index,
        "attachment_hash": args["attachment_hash"],
        "data": base64.b64encode(raw).decode(),
        "sha256": protocol.sha(raw),
        "mime": mime,
        "byte_length": len(raw),
        "resized": False,
    }


async def handle(request, db, redis):
    if os.environ.get("LEADBOT_READER_ENABLED") != "1":
        raise ApiError("unavailable", "Чтение источников помощником отключено", status=503)
    key = assistant_identity.proof_key()
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > protocol.MAX_REQUEST:
            raise ApiError("validation_error", status=413)
        chunks.append(chunk)
    try:
        value, nonce = protocol.verify(
            key, b"".join(chunks), dict(request.headers), now=time.time()
        )
        # Nonce is only replay-control metadata; no customer table changes.
        if not await redis.set("leadbot:reader:nonce:" + nonce, "1", nx=True, ex=70):
            raise protocol.SourceError("Source read request was already consumed")
        result = await dispatch(db, value)
        raw = protocol.encode({"ok": True, "data": result})
        if len(raw) > protocol.MAX_RESPONSE:
            raise protocol.SourceError("Source response exceeds its budget")
        return raw, protocol.response_signature(key, raw, nonce)
    except protocol.SourceError:
        raise ApiError(
            "source_read_rejected",
            "Источник недоступен или изменился; обновите проверку",
            status=409,
        ) from None
