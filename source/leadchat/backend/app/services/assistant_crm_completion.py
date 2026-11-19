"""Complete an explicitly configured CRM-only Run from its verified original card."""

import structlog
from sqlalchemy import select

from app.core.errors import ApiError
from app.models import AssistantDialog, User
from app.models import AssistantOfficeWork as Work
from app.services import assistant_runs, conversations
from app.services.assistant_office import NativeOffice, _object, _versions, _view

log = structlog.get_logger(__name__)


class NativeCRMCompletion:
    def __init__(self, office: NativeOffice):
        if (
            not isinstance(office, NativeOffice)
            or not office.enabled
            or not office.crm_only
            or office.notifications_enabled
        ):
            raise ValueError("Explicit trusted CRM-only completion required")
        self.office = office

    async def complete(self, key):
        async with self.office.sessions() as db:
            work = await db.scalar(select(Work).where(Work.key == key).with_for_update())
            if work is None:
                raise ValueError("Original CRM work required")
            if work.stage == "completed" and work.reason_code == "native_crm_only_confirmed":
                return _view(work)
            try:
                live = assistant_runs.RunAuthority(
                    work.principal_id,
                    work.operator_id,
                    work.run_id,
                    work.generation,
                    "auto",
                    _versions(work),
                )
                await self.office._source(db, work, live, require_deadline=False)
                await self.office._form(db, work)
                if work.stage != "waiting_notification" or work.card_receipt is None:
                    raise ValueError("Original verified card required")
                card = _object(work.card_receipt)
                if (
                    not work.created_id
                    or card.get("provenance") != "extension_original_card_read"
                    or card.get("same_request_conversation_ids") != []
                    or card.get("report", {}).get("id") != work.created_id
                ):
                    raise ValueError("Original no-duplicate card receipt required")
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
                    raise ValueError("Current original enrollment and no duplicates required")
            except (ValueError, ApiError):
                work.stage, work.reason_code = "created_review", "native_crm_only_close_review"
                await self.office._event(db, work, "crm_only_close_review")
                await db.commit()
                return _view(work)
            await conversations.set_crm_request(db, conv, actor, work.created_id)
            system = await conversations.change_status(db, conv, new_status="closed", actor=actor)
            job.state, work.stage = "completed", "completed"
            work.reason_code = "native_crm_only_confirmed"
            await self.office._event(db, work, "normal_crm_only_completion_without_telegram")
            await db.commit()
            # A lost UI publication cannot repeat the committed link or close.
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
                log.warning("assistant.crm_only_publication_unavailable", work_id=work.key)
            return _view(work)
