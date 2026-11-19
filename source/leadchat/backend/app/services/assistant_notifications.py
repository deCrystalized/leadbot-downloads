"""Native service-post receipt and normal Main completion, never a browser boolean.

The existing Root/Node/Team bridge executes the service post. Main commits an
original private command before submit and subsequently observes that same
command only. A stopped Run may retain evidence but cannot link/close a dialog.
"""

import base64
import re
import uuid

import structlog
from sqlalchemy import or_, select, update

from app.core.errors import ApiError
from app.models import AssistantDialog, AssistantNativeAction, AssistantNativeCommand, User
from app.models import AssistantOfficeNotification as Notice
from app.models import AssistantOfficeWork as Work
from app.services import assistant_runs, conversations
from app.services import leadbot_execution_protocol as wire
from app.services.assistant_office import _json, _object, _versions, _view

TERMINAL = {"completed", "review", "unknown", "stale"}
log = structlog.get_logger(__name__)


async def seed(db, work, now):
    if work.stage != "waiting_notification" or work.card_receipt is None:
        raise ValueError("Verified original card required before notification intent")
    if await db.get(Notice, work.key) is None:
        db.add(
            Notice(
                work_key=work.key,
                intent_id=uuid.uuid4(),
                stage="pending",
                deadline=now + 90,
                due=now,
                observations=0,
                lease_until=0,
            )
        )


def verified_receipt(result, work, note):
    if (
        not isinstance(result, dict)
        or result.get("ok") is not True
        or result.get("telegram_confirmed") is not True
    ):
        raise ValueError("Independent service receipt required")
    proposal = _object(work.proposal)
    expected = {
        "work_id": work.key,
        "intent_id": str(note.intent_id),
        "crm_request_id": work.created_id,
        "source_sha256": work.source_hash,
        "snapshot_hash": work.snapshot_hash,
        "form_reference": proposal["form_reference"],
        "card_sha256": wire.sha(work.card_receipt.encode()),
    }
    if any(result.get(k) != v for k, v in expected.items()):
        raise ValueError("Original work/card/CRM notification binding changed")
    if (
        type(result.get("message_id")) is not int
        or not 1 <= result["message_id"] <= 2**53 - 1
        or type(result.get("topic_id")) is not int
        or not 1 <= result["topic_id"] <= 2**53 - 1
        or not isinstance(result.get("chat_id"), str)
        or not re.fullmatch(r"-?[1-9][0-9]{0,18}", result["chat_id"])
    ):
        raise ValueError("Actual Telegram message/chat/topic required")
    original = result.get("original_http")
    if (
        not isinstance(original, dict)
        or set(original) != {"status", "content_type", "sha256", "body"}
        or original["status"] != 200
        or original["content_type"] != "application/json"
    ):
        raise ValueError("Original successful Team response required")
    raw = base64.b64decode(original["body"], validate=True)
    if len(raw) > 200000 or wire.sha(raw) != original["sha256"]:
        raise ValueError("Original service response bytes changed")
    text = (
        work.created_id
        + " - "
        + proposal["followup"]["code"]
        + " "
        + {"kp": "КП", "mnc": "МНЧ", "bt": "БТ"}[proposal["dir"]]
    )
    actual = wire.decode(raw, 200000)
    if (
        actual
        != {
            "ok": True,
            "message_id": result["message_id"],
            "native_intent": str(note.intent_id),
            "chat_id": result["chat_id"],
            "reply_to": result["topic_id"],
            "text_sha256": wire.sha(text.encode()),
        }
        or type(actual.get("message_id")) is not int
        or type(actual.get("reply_to")) is not int
        or result.get("text_sha256") != wire.sha(text.encode())
    ):
        raise ValueError("Actual Telegram receipt differs from the exact original service text")
    return result


class NativeNotificationCompletion:
    def __init__(self, office):
        from app.services.assistant_office import NativeOffice

        if (
            not isinstance(office, NativeOffice)
            or not office.enabled
            or not office.notifications_enabled
            or office.actions is None
        ):
            raise ValueError("Trusted configured office worker required")
        self.office, self.sessions = office, office.sessions
        assert office.actions is not None
        self.client = office.actions.client

    @staticmethod
    def live(work):
        return assistant_runs.RunAuthority(
            work.principal_id,
            work.operator_id,
            work.run_id,
            work.generation,
            "auto",
            _versions(work),
        )

    async def fresh(self, db, work):
        await self.office._source(db, work, self.live(work), require_deadline=False)
        if (
            work.stage != "waiting_notification"
            or work.card_receipt is None
            or work.created_id is None
        ):
            raise ValueError("Original accepted card required")
        card = _object(work.card_receipt)
        if (
            card.get("provenance") != "extension_original_card_read"
            or card.get("same_request_conversation_ids") != []
            or card.get("report", {}).get("id") != work.created_id
        ):
            raise ValueError("Original no-duplicate card receipt required")

    async def stop_if_current(self, db, work):
        try:
            await self.office._source(db, work, self.live(work), require_deadline=False)
        except (ValueError, ApiError):
            return
        await assistant_runs.block(db, self.live(work), "native_delivery")

    async def due(self):
        async with self.sessions() as db:
            return list(
                await db.scalars(
                    select(Notice.work_key)
                    .where(
                        Notice.stage.not_in(TERMINAL),
                        Notice.due <= self.office._now(),
                        or_(Notice.lease_id.is_(None), Notice.lease_until <= self.office._now()),
                    )
                    .order_by(Notice.due, Notice.work_key)
                    .limit(100)
                )
            )

    async def advance(self, key):
        now, lease = self.office._now(), uuid.uuid4()
        async with self.sessions() as db:
            changed = await db.scalar(
                update(Notice)
                .where(
                    Notice.work_key == key,
                    Notice.stage.not_in(TERMINAL),
                    Notice.due <= now,
                    or_(Notice.lease_id.is_(None), Notice.lease_until <= now),
                )
                .values(lease_id=lease, lease_until=now + 35)
                .returning(Notice.work_key)
            )
            if changed is None:
                return {"state": "notification_observation_only", "execution_allowed": False}
            note = await db.get(Notice, key, populate_existing=True)
            work = await db.get(Work, key)
            if work is None:
                raise ValueError("Original notification Work missing")
            if now >= note.deadline or note.observations >= 180:
                note.stage, note.reason_code = "unknown", "notification_deadline"
                work.stage = "created_review"
                if note.receipt is None:
                    work.reason_code = "notification_deadline"
                await self.stop_if_current(db, work)
                note.lease_id = None
                await self.office._event(db, work, "notification_deadline")
                await db.commit()
                return _view(work)
            if note.stage == "received":
                # Completion locks and revalidates the saved receipt itself.
                await db.rollback()
                return await self.complete(key)
            if note.command_id is None:
                try:
                    await self.fresh(db, work)
                    action = await db.get(AssistantNativeAction, work.action_key)
                    proposal = _object(work.proposal)
                    if (
                        action is None
                        or action.stage != "office_issued"
                        or action.consume_command_id is None
                        or not re.fullmatch(
                            r"[АСВМБ]\d{1,3}(?:\.\d)?", proposal.get("followup", {}).get("code", "")
                        )
                    ):
                        raise ValueError("Original consumed create and source code required")
                except (ValueError, ApiError):
                    note.stage, note.reason_code, note.lease_id = (
                        "stale",
                        "notification_source_changed",
                        None,
                    )
                    work.stage, work.reason_code = "created_review", "notification_source_changed"
                    await self.office._event(db, work, "notification_source_changed")
                    await db.commit()
                    return _view(work)
                command_id = uuid.uuid4()
                packet = {
                    "v": 1,
                    "command_id": str(command_id),
                    "operation": "notify_office",
                    "principal_id": str(work.principal_id),
                    "operator_id": str(work.operator_id),
                    "run_id": str(work.run_id),
                    "generation": work.generation,
                    "arguments": {
                        "cid": str(work.conversation_id),
                        "source_sha256": work.source_hash,
                        "work_id": work.key,
                        "notification_id": str(note.intent_id),
                        "create_command_id": str(action.consume_command_id),
                        "crm_request_id": work.created_id,
                        "snapshot_hash": work.snapshot_hash,
                        "form_reference": proposal["form_reference"],
                        "card_sha256": wire.sha(work.card_receipt.encode()),
                        "dispatch_before": note.deadline,
                    },
                }
                wire.check(packet)
                note.command_id, note.stage = command_id, "observing"
                record = AssistantNativeCommand(
                    id=command_id,
                    action_key=work.action_key,
                    request=_json(packet),
                    state="dispatching",
                )
                db.add(record)
                await self.office._event(db, work, "notification_original_requested")
            else:
                if note.observation_id is not None:
                    # A previous read-only observation can be replaced. The
                    # one original notification command is never resubmitted.
                    previous = await db.get(AssistantNativeCommand, note.observation_id)
                    if previous is not None and previous.state == "dispatching":
                        previous.state = "observation_unknown"
                command_id = uuid.uuid4()
                packet = {
                    "v": 1,
                    "command_id": str(command_id),
                    "operation": "recover",
                    "principal_id": str(work.principal_id),
                    "operator_id": str(work.operator_id),
                    "run_id": str(work.run_id),
                    "generation": work.generation,
                    "arguments": {"command_id": str(note.command_id)},
                }
                note.observation_id, note.observations = command_id, note.observations + 1
                record = AssistantNativeCommand(
                    id=command_id,
                    action_key=work.action_key,
                    original_id=note.command_id,
                    request=_json(packet),
                    state="dispatching",
                )
                db.add(record)
            await db.commit()  # Original request/lease before private network.
        try:
            response, status = await self.client.submit(packet)
            error = False
        except Exception:
            response, status, error = None, None, True
        async with self.sessions() as db:
            note = await db.scalar(select(Notice).where(Notice.work_key == key).with_for_update())
            work = await db.get(Work, key)
            if note.lease_id != lease:
                return {"state": "notification_observation_only", "execution_allowed": False}
            record = await db.get(AssistantNativeCommand, command_id)
            record.response, record.http_status = (
                _json(response) if response is not None else None,
                status,
            )
            record.state = "response_received" if not error else "transport_unknown"
            note.lease_id, note.lease_until, note.due = None, 0, self.office._now() + 0.5
            if error or not isinstance(response, dict):
                work.reason_code = "notification_transport_unknown"
                await self.stop_if_current(db, work)
                await self.office._event(db, work, "notification_transport_unknown")
                await db.commit()
                return _view(work)
            original: object = response
            if packet["operation"] == "recover":
                data = response.get("data")
                if not isinstance(data, dict):
                    data = {}
                if data.get("command_state") == "dispatching":
                    await db.commit()
                    return _view(work)
                original = data.get("original_result")
            elif status == 202:
                await db.commit()
                return _view(work)
            try:
                if (
                    status != 200
                    or not isinstance(original, dict)
                    or original.get("ok") is not True
                ):
                    raise ValueError("Original notification not confirmed")
                receipt = verified_receipt(original.get("data"), work, note)
            except (ValueError, TypeError, KeyError):
                note.stage, note.reason_code = "unknown", "notification_result_unknown"
                work.stage, work.reason_code = "created_review", "notification_result_unknown"
                await self.stop_if_current(db, work)
                await self.office._event(db, work, "notification_result_unknown")
                await db.commit()
                return _view(work)
            note.receipt, note.stage = _json(receipt), "received"
            work.reason_code = "native_notification_confirmed_review"
            await self.office._event(db, work, "notification_independent_receipt_saved")
            await db.commit()  # Preserve real evidence before fresh close checks.
        return await self.complete(key)

    async def complete(self, key):
        async with self.sessions() as db:
            note = await db.scalar(select(Notice).where(Notice.work_key == key).with_for_update())
            work = await db.get(Work, key)
            if note is None or work is None:
                raise ValueError("Original notification required")
            if note.stage == "completed":
                return _view(work)
            try:
                if note.receipt is None or note.deadline <= self.office._now():
                    raise ValueError("Original timely independent receipt required")
                verified_receipt(_object(note.receipt), work, note)
                await self.fresh(db, work)
                conv = await conversations.get_conversation_for_update(db, work.conversation_id)
                twins = await conversations.crm_request_twins(
                    db, work.created_id, except_id=conv.id
                )
                job = await db.get(AssistantDialog, conv.id)
                actor = await db.get(User, work.operator_id)
                if (
                    twins
                    or job is None
                    or job.principal_id != work.principal_id
                    or job.operator_id != work.operator_id
                    or job.version != work.dialog_version
                    or job.state != "waiting"
                    or conv.crm_request_id is not None
                    or actor is None
                ):
                    raise ValueError("Current original enrollment/no duplicates required")
            except (ValueError, ApiError):
                note.stage, note.reason_code = "review", "notification_close_review"
                work.stage = "created_review"
                await self.office._event(db, work, "notification_close_review")
                await db.commit()
                return _view(work)
            await conversations.set_crm_request(db, conv, actor, work.created_id)
            system = await conversations.change_status(db, conv, new_status="closed", actor=actor)
            job.state, work.stage, note.stage = "completed", "completed", "completed"
            work.reason_code = "native_notification_confirmed"
            await self.office._event(db, work, "normal_notification_completion")
            await db.commit()
            # Use the normal state/system-message publication AFTER commit.
            # WS errors do not repeat an already committed close.
            try:
                from app.api.routes.conversations import _conversation_patch, _publish_change
                from app.ws.events import iso

                detail = await conversations.conversation_detail(db, conv)
                patch = _conversation_patch(detail)
                patch.update(
                    crm_request_id=conv.crm_request_id, crm_request_at=iso(conv.crm_request_at)
                )
                await _publish_change(self.office.redis, conv, system, patch)
            except Exception:
                log.warning(
                    "assistant.notification_publication_unavailable",
                    conversation_id=str(work.conversation_id),
                    work_id=work.key,
                )
            return _view(work)
