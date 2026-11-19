"""Native send fence around the existing vendor transport, disabled by default.

No HTTP route can create provenance here. The native action coordinator
binds its original durable consume command to the message in the same
transaction. A pending message/prefix alone never authorizes native delivery.
"""

import hashlib
import math
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.core.errors import ApiError
from app.integrations.avito.errors import AvitoAuthError
from app.models import AssistantNativeOutbound as Outbound
from app.models import AssistantNativePart as Part
from app.models import Message, User
from app.services import assistant_dialogs, assistant_runs, leadbot_reader
from app.services import leadbot_execution_protocol as native_wire
from app.services.avito_text import split_text
from app.services.leadbot_source_protocol import encode


class NativeDeliveryStopped(ValueError):
    def __init__(self, code: str):
        # All callers below use literal codes, never exception/provider text.
        self.code = code
        super().__init__("Native delivery stopped; do not repeat the vendor request")


class NativeDeliveryPending(NativeDeliveryStopped):
    """Observe the original attempt; its persisted row alone proves no terminal state."""

    def __init__(self):
        super().__init__("native_attempt_inflight")


@dataclass(frozen=True)
class NativeDeliveryRuntime:
    admission: assistant_runs.RuntimeAdmission
    enabled: bool = False
    clock: Callable[[], float] = time.time

    def __post_init__(self):
        if (
            not isinstance(self.admission, assistant_runs.RuntimeAdmission)
            or type(self.enabled) is not bool
            or not callable(self.clock)
        ):
            raise ValueError("Trusted native delivery configuration required")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class Ticket:
    part: int
    attempt: int
    text_hash: str
    vendor_id: str | None = None


async def for_message(ctx: dict[str, Any], message_id: uuid.UUID):
    """Called before normal outbox delivery; human messages keep the old path."""
    factory = ctx["db_session_factory"]
    async with factory() as db:
        record = await db.get(Outbound, message_id)
        if record is None:
            refs = await db.scalars(
                select(Message.client_message_id).where(Message.id == message_id)
            )
            if any(str(ref or "").startswith("native:") for ref in refs):
                raise NativeDeliveryStopped("native_provenance_missing")
            return None
        msg = await db.get(Message, (message_id, record.message_created_at))
        if msg is None or msg.delivery_status != "pending":
            return None
        runtime = ctx.get("native_delivery_runtime")
        if not isinstance(runtime, NativeDeliveryRuntime) or not runtime.enabled:
            record.state, record.reason_code = "blocked", "native_delivery_disabled"
            await db.commit()
            raise NativeDeliveryStopped("native_delivery_disabled")
    return NativeSendGuard(factory, message_id, runtime)


class NativeSendGuard:
    def __init__(self, factory, message_id: uuid.UUID, runtime: NativeDeliveryRuntime):
        self.factory, self.message_id, self.runtime = factory, message_id, runtime

    async def decode_cached_progress(
        self, raw: str | bytes | None, parts_total: int
    ) -> tuple[int, str | None]:
        if raw is None:
            return 0, None
        try:
            data = native_wire.decode(raw.encode() if isinstance(raw, str) else raw, 32000)
            if (
                not isinstance(data, dict)
                or set(data) - {"sent", "external_id", "images_sent", "image_ids"}
                or type(data.get("sent")) is not int
                or not 0 <= data["sent"] <= parts_total
                or type(data.get("images_sent", 0)) is not int
                or data.get("images_sent", 0) != 0
                or data.get("image_ids", {}) != {}
                or data.get("external_id") is not None
                and not isinstance(data["external_id"], str)
            ):
                raise ValueError("Invalid native cached progress")
        except (ValueError, TypeError, UnicodeError):
            async with self.factory() as db:
                rows = list(
                    await db.scalars(
                        select(Part)
                        .where(Part.message_id == self.message_id)
                        .order_by(Part.part, Part.attempt)
                    )
                )
                latest = {row.part: row for row in rows}
                if all(
                    i in latest and latest[i].state == "confirmed" and latest[i].vendor_id
                    for i in range(parts_total)
                ):
                    # No new effect: walk the independently saved exact SQL
                    # receipts even if the disposable cache is malformed.
                    return 0, None
                first_unconfirmed = next(
                    (
                        i
                        for i in range(parts_total)
                        if i not in latest or latest[i].state != "confirmed"
                    ),
                    None,
                )
                if (
                    first_unconfirmed is not None
                    and first_unconfirmed in latest
                    and latest[first_unconfirmed].state == "inflight"
                ):
                    # Observe a possibly running original attempt; corrupt
                    # disposable cache is not proof that it failed or ended.
                    return 0, None
                record = await db.get(Outbound, self.message_id)
                if record is not None:
                    record.state, record.reason_code = "unknown", "native_cached_progress_invalid"
                    await db.commit()
            raise NativeDeliveryStopped("native_cached_progress_invalid") from None
        return data["sent"], data.get("external_id")

    async def reconcile_cached_progress(
        self, sent: int, vendor_id: str | None, images_sent: int
    ) -> None:
        """A cached cursor cannot skip native SQL attempts or prove delivery."""
        uncertain = False
        async with self.factory() as db:
            rows = list(
                await db.scalars(
                    select(Part)
                    .where(Part.message_id == self.message_id)
                    .order_by(Part.part, Part.attempt)
                )
            )
            latest = {row.part: row for row in rows}
            states = {"confirmed", "inflight", "unknown"}
            uncertain = bool(images_sent) or any(
                i not in latest or latest[i].state not in states for i in range(sent)
            )
            if vendor_id and not any(row.state in states for row in latest.values()):
                uncertain = True
            if uncertain:
                record = await db.get(Outbound, self.message_id)
                if record is not None:
                    record.state, record.reason_code = "unknown", "native_cached_receipt_unverified"
                    await db.commit()
        if uncertain:
            # Do not assume a missing SQL attempt means an earlier external
            # effect never happened. Neither resend nor mark delivered.
            raise NativeDeliveryStopped("native_cached_receipt_unverified")

    async def _source_hash(self, db, record, msg, parts) -> str:
        own = {(msg.id, msg.created_at)}
        # Only exact acknowledged vendor IDs, CID, direction and text can
        # identify an own echo; an older identical text is never evidence.
        for part in parts:
            if part.state == "confirmed" and part.vendor_id:
                expected = split_text(msg.body or "")
                if not 0 <= part.part < len(expected):
                    raise NativeDeliveryStopped("native_part_binding_changed")
                echoes = await db.scalars(
                    select(Message).where(
                        Message.conversation_id == record.conversation_id,
                        Message.external_message_id == part.vendor_id,
                        Message.direction == "out",
                        Message.body == expected[part.part],
                        Message.created_at >= msg.created_at,
                    )
                )
                for echo in echoes:
                    if not echo.attachments:
                        own.add((echo.id, echo.created_at))
        result = await leadbot_reader._snapshot(
            db,
            str(record.conversation_id),
            {"principal_id": str(record.principal_id), "operator_id": str(record.operator_id)},
            native_own_messages=tuple(own),
        )
        if result is None:
            raise NativeDeliveryStopped("native_source_unavailable")
        return result[0]["source_sha256"]

    async def stop_outbox(self) -> None:
        """Stop native technical retries; confirmed receipts remain evidence."""
        async with self.factory() as db:
            record = await db.scalar(
                select(Outbound).where(Outbound.message_id == self.message_id).with_for_update()
            )
            if record is not None and record.state != "accepted":
                uncertain = await db.scalar(
                    select(Part.message_id)
                    .where(
                        Part.message_id == self.message_id, Part.state.in_(("inflight", "unknown"))
                    )
                    .limit(1)
                )
                record.state = "unknown" if uncertain is not None else "blocked"
                record.reason_code = "native_outbox_error"
                await db.commit()

    async def _begin(self, index: int, text: str) -> Ticket:
        error = None
        ticket = None
        async with self.factory() as db:
            initial = await db.get(Outbound, self.message_id)
            if initial is None:
                raise NativeDeliveryStopped("native_provenance_missing")
            # Same principal-row ordering as explicit start/stop. No locks or
            # ORM transaction survive the return to the vendor callback.
            await db.scalar(select(User).where(User.id == initial.principal_id).with_for_update())
            record = await db.scalar(
                select(Outbound)
                .where(Outbound.message_id == self.message_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            assert record is not None
            rows = list(
                await db.scalars(
                    select(Part)
                    .where(Part.message_id == self.message_id)
                    .order_by(Part.part, Part.attempt)
                )
            )
            current = [row for row in rows if row.part == index]
            prior = current[-1] if current else None
            try:
                msg = await db.get(
                    Message, (self.message_id, record.message_created_at), populate_existing=True
                )
                if (
                    msg is None
                    or msg.conversation_id != record.conversation_id
                    or msg.sender_user_id != record.operator_id
                    or msg.direction != "out"
                    or msg.sender_type != "operator"
                    or msg.attachments
                    or msg.client_message_id != "native:" + record.root_grant_id
                    or _sha(msg.body or "") != record.body_hash
                ):
                    raise NativeDeliveryStopped("native_message_binding_changed")
                expected = split_text(msg.body or "")
                if (
                    type(index) is not int
                    or not 0 <= index < len(expected)
                    or text != expected[index]
                ):
                    raise NativeDeliveryStopped("native_part_binding_changed")
                if prior is not None and prior.state == "confirmed" and prior.vendor_id:
                    if prior.text_hash != _sha(text):
                        raise NativeDeliveryStopped("native_part_binding_changed")
                    ticket = Ticket(index, prior.attempt, prior.text_hash, prior.vendor_id)
                else:
                    if prior is not None and prior.state == "inflight":
                        raise NativeDeliveryPending()
                    if prior is not None and prior.state != "auth_refused":
                        raise NativeDeliveryStopped("native_delivery_uncertain")
                    if (
                        record.state not in ("queued", "inflight")
                        or prior is not None
                        and prior.attempt >= 2
                    ):
                        raise NativeDeliveryStopped("native_delivery_not_dispatchable")
                    now = self.runtime.clock()
                    if (
                        not math.isfinite(now)
                        or not math.isfinite(record.dispatch_before)
                        or now >= record.dispatch_before
                    ):
                        raise NativeDeliveryStopped("native_dispatch_window_expired")
                    live = await assistant_runs.authority(
                        db,
                        record.principal_id,
                        record.run_id,
                        record.generation,
                        self.runtime.admission,
                    )
                    if (
                        live.mode != "auto"
                        or live.operator_id != record.operator_id
                        or encode(live.versions).decode() != record.versions
                    ):
                        raise NativeDeliveryStopped("native_run_changed")
                    principal = await db.get(User, record.principal_id)
                    await assistant_dialogs.locked_job(
                        db,
                        principal,
                        record.conversation_id,
                        record.operator_id,
                        record.dialog_version,
                    )
                    latest = {row.part: row for row in rows}
                    if any(i not in latest or latest[i].state != "confirmed" for i in range(index)):
                        raise NativeDeliveryStopped("native_prior_part_not_confirmed")
                    if await self._source_hash(db, record, msg, rows) != record.source_hash:
                        raise NativeDeliveryStopped("native_source_changed")
                    ticket = Ticket(
                        index, prior.attempt + 1 if prior is not None else 1, _sha(text)
                    )
                    db.add(
                        Part(
                            message_id=self.message_id,
                            part=index,
                            attempt=ticket.attempt,
                            text_hash=ticket.text_hash,
                            state="inflight",
                            started_at=now,
                        )
                    )
                    record.state, record.reason_code = "inflight", None
            except (ApiError, NativeDeliveryStopped, ValueError) as exc:
                error = (
                    exc.code if isinstance(exc, NativeDeliveryStopped) else "native_context_changed"
                )
                if error != "native_attempt_inflight":
                    record.state = "unknown" if error == "native_delivery_uncertain" else "blocked"
                    record.reason_code = error
            await db.commit()  # Per-part reservation is durable BEFORE actual I/O.
        if error:
            if error == "native_attempt_inflight":
                raise NativeDeliveryPending()
            raise NativeDeliveryStopped(error)
        assert ticket is not None
        return ticket

    async def _finish(
        self, ticket: Ticket, *, vendor_id: str | None = None, auth_refused: bool = False
    ) -> None:
        async with self.factory() as db:
            record = await db.scalar(
                select(Outbound).where(Outbound.message_id == self.message_id).with_for_update()
            )
            row = await db.get(Part, (self.message_id, ticket.part, ticket.attempt))
            if (
                record is None
                or row is None
                or row.state != "inflight"
                or row.text_hash != ticket.text_hash
            ):
                raise NativeDeliveryStopped("native_attempt_binding_changed")
            row.finished_at = self.runtime.clock()
            if vendor_id is not None:
                row.state, row.vendor_id = "confirmed", vendor_id
                await db.flush()
                confirmed = list(
                    await db.scalars(
                        select(Part).where(
                            Part.message_id == self.message_id, Part.state == "confirmed"
                        )
                    )
                )
                message = await db.get(Message, (self.message_id, record.message_created_at))
                if message is not None and len({p.part for p in confirmed}) == len(
                    split_text(message.body or "")
                ):
                    record.state, record.reason_code = "accepted", None
            elif auth_refused and ticket.attempt == 1:
                row.state, row.reason_code = "auth_refused", "native_auth_refused"
            elif auth_refused:
                row.state, row.reason_code = "blocked", "native_auth_refused"
                record.state, record.reason_code = "blocked", row.reason_code
            else:
                row.state, row.reason_code = "unknown", "native_delivery_uncertain"
                record.state, record.reason_code = "unknown", row.reason_code
            await db.commit()

    async def send(
        self,
        index: int,
        text: str,
        callback: Callable[[], Awaitable[str]],
        *,
        forbidden_value: str | None = None,
    ) -> str:
        try:
            ticket = await self._begin(index, text)
        except NativeDeliveryStopped:
            raise
        except Exception:
            raise NativeDeliveryStopped("native_delivery_unavailable") from None
        if ticket.vendor_id is not None:
            return ticket.vendor_id  # Only replay the recorded receipt, never vendor I/O.
        try:
            result = await callback()
        except Exception as exc:
            auth = isinstance(exc, AvitoAuthError) and exc.status in (401, 403)
            try:
                await self._finish(ticket, auth_refused=auth)
            except Exception:
                raise NativeDeliveryStopped("native_delivery_uncertain") from None
            if auth and ticket.attempt == 1:
                raise  # Existing single token refresh; next physical send rechecks all gates.
            raise NativeDeliveryStopped(
                "native_auth_refused" if auth else "native_delivery_uncertain"
            ) from None
        if (
            not isinstance(result, str)
            or not 0 < len(result) <= 4096
            or any(ord(c) < 32 for c in result)
            or forbidden_value
            and forbidden_value in result
        ):
            await self._finish(ticket)
            raise NativeDeliveryStopped("native_delivery_uncertain")
        try:
            await self._finish(ticket, vendor_id=result)
        except NativeDeliveryStopped:
            raise
        except Exception:
            # Vendor may have accepted it. The durable INFLIGHT row is the
            # recovery evidence; never let the old outbox retry this callback.
            raise NativeDeliveryStopped("native_delivery_uncertain") from None
        return result
